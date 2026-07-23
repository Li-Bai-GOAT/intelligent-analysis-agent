[CmdletBinding()]
param(
    [ValidateSet('up', 'down', 'restart', 'status', 'logs')]
    [string]$Action = 'up',
    [ValidateSet('main', 'sandbox')]
    [string]$Service = 'main'
)

$ErrorActionPreference = 'Stop'
$ProjectRoot = Split-Path -Parent $PSScriptRoot
$PidDirectory = Join-Path $ProjectRoot '.pids'
$LogDirectory = Join-Path $ProjectRoot 'logs'
$Python = Join-Path $ProjectRoot '.venv\Scripts\python.exe'
$SandboxServer = Join-Path $ProjectRoot '.venv\Scripts\runtime-sandbox-server.exe'
$OllamaRuntime = Join-Path (Split-Path -Parent $ProjectRoot) '.runtime\ollama'
$Ollama = Join-Path $OllamaRuntime 'bin\ollama.exe'
$OllamaModels = Join-Path $OllamaRuntime 'models'

New-Item -ItemType Directory -Path $PidDirectory, $LogDirectory -Force | Out-Null

# Some Windows hosts inherit both Path and PATH as separate entries. PowerShell
# treats them as duplicate dictionary keys when Start-Process builds a child
# environment, so normalize them once before starting managed services.
$processPath = [System.Environment]::GetEnvironmentVariable('Path', 'Process')
if ($processPath) {
    [System.Environment]::SetEnvironmentVariable('PATH', $null, 'Process')
    [System.Environment]::SetEnvironmentVariable('Path', $processPath, 'Process')
}

function Test-TcpPort([int]$Port) {
    try {
        return Test-NetConnection -ComputerName '127.0.0.1' -Port $Port -InformationLevel Quiet -WarningAction SilentlyContinue
    } catch {
        return $false
    }
}

function Wait-Http([string]$Url, [int]$TimeoutSeconds = 90) {
    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    while ((Get-Date) -lt $deadline) {
        try {
            $response = Invoke-WebRequest -UseBasicParsing -Uri $Url -TimeoutSec 3
            if ($response.StatusCode -ge 200 -and $response.StatusCode -lt 300) {
                return $true
            }
        } catch {}
        Start-Sleep -Seconds 2
    }
    return $false
}

function Get-ListenerPid([int]$Port) {
    $listener = netstat -ano | Select-String "0.0.0.0:$Port\s+0.0.0.0:0\s+LISTENING" | Select-Object -First 1
    if (-not $listener) { return $null }
    $value = (($listener -split '\s+')[-1])
    if ($value -match '^\d+$') { return [int]$value }
    return $null
}

function Start-ManagedService([string]$Name, [int]$Port, [string]$HealthUrl, [string]$Executable, [string[]]$Arguments) {
    $existingPid = Get-ListenerPid $Port
    if ($existingPid) {
        Write-Host "[running] $Name is already listening on $Port (PID $existingPid)"
        return
    }

    if (-not (Test-Path $Executable)) {
        throw "$Name executable was not found: $Executable"
    }

    $environment = @{
        DEBUG = 'release'
        PYTHONUTF8 = '1'
    }
    $stdout = Join-Path $LogDirectory "$Name.out.log"
    $stderr = Join-Path $LogDirectory "$Name.err.log"
    $previousLocation = Get-Location
    try {
        Set-Location $ProjectRoot
        $environment.GetEnumerator() | ForEach-Object { Set-Item -Path "Env:$($_.Key)" -Value $_.Value }
        $process = Start-Process -FilePath $Executable -ArgumentList $Arguments -WorkingDirectory $ProjectRoot -RedirectStandardOutput $stdout -RedirectStandardError $stderr -WindowStyle Hidden -PassThru
    } finally {
        Set-Location $previousLocation
    }

    Set-Content -Path (Join-Path $PidDirectory "$Name.pid") -Value $process.Id -Encoding ascii
    if (-not (Wait-Http $HealthUrl)) {
        throw "$Name did not become healthy. Check $stderr"
    }
    Write-Host "[started] $Name is ready on $Port"
}

function Stop-ManagedService([string]$Name) {
    $pidFile = Join-Path $PidDirectory "$Name.pid"
    if (-not (Test-Path $pidFile)) {
        Write-Host "[skip] No managed PID file for $Name"
        return
    }

    $pidValue = Get-Content $pidFile -Raw
    if ($pidValue -match '^\s*(\d+)\s*$') {
        $processId = [int]$Matches[1]
        $process = Get-Process -Id $processId -ErrorAction SilentlyContinue
        if ($process) {
            $processInfo = Get-CimInstance Win32_Process -Filter "ProcessId = $processId" -ErrorAction SilentlyContinue
            $commandLine = if ($processInfo) { [string]$processInfo.CommandLine } else { '' }
            $isExpectedProcess = switch ($Name) {
                'main' { $process.Name -match '^python' -and $commandLine -match 'app\.main:app' }
                'sandbox' { $process.Name -eq 'runtime-sandbox-server' }
                'embedding' { $process.Name -eq 'ollama' -and $commandLine -match '\bserve\b' }
                default { $false }
            }
            if ($isExpectedProcess) {
                Stop-Process -Id $process.Id -Force
                Write-Host "[stopped] $Name (PID $($process.Id))"
            } else {
                Write-Warning "Ignoring stale PID file for $Name; PID $processId belongs to $($process.Name)."
            }
        }
    }
    Remove-Item -LiteralPath $pidFile -Force -ErrorAction SilentlyContinue
}

function Start-EmbeddingService {
    $existingPid = Get-ListenerPid 9997
    if ($existingPid) {
        Write-Host "[running] embedding is already listening on 9997 (PID $existingPid)"
        return
    }
    if (-not (Test-Path $Ollama)) {
        Write-Warning "Ollama executable was not found: $Ollama"
        return
    }

    New-Item -ItemType Directory -Path $OllamaModels -Force | Out-Null
    $env:OLLAMA_HOST = '127.0.0.1:9997'
    $env:OLLAMA_MODELS = $OllamaModels
    $stdout = Join-Path $LogDirectory 'embedding.out.log'
    $stderr = Join-Path $LogDirectory 'embedding.err.log'
    $process = Start-Process -FilePath $Ollama -ArgumentList @('serve') -WorkingDirectory $ProjectRoot -RedirectStandardOutput $stdout -RedirectStandardError $stderr -WindowStyle Hidden -PassThru
    Set-Content -Path (Join-Path $PidDirectory 'embedding.pid') -Value $process.Id -Encoding ascii
    if (-not (Wait-Http 'http://127.0.0.1:9997/v1/models' 60)) {
        throw "Embedding service did not become healthy. Check $stderr"
    }
    Write-Host '[started] embedding is ready on 9997'
}

function Show-Status {
    foreach ($item in @(
        @{ Name = 'postgres'; Port = 5488; Url = $null },
        @{ Name = 'redis'; Port = 6380; Url = $null },
        @{ Name = 'milvus'; Port = 19530; Url = $null },
        @{ Name = 'embedding'; Port = 9997; Url = 'http://127.0.0.1:9997/v1/models' },
        @{ Name = 'sandbox'; Port = 10001; Url = 'http://127.0.0.1:10001/docs' },
        @{ Name = 'main'; Port = 8090; Url = 'http://127.0.0.1:8090/ready' }
    )) {
        $listening = Test-TcpPort $item.Port
        $health = 'n/a'
        if ($listening -and $item.Url) { $health = if (Wait-Http $item.Url 3) { 'ok' } else { 'unavailable' } }
        Write-Host ('{0,-10} port={1,-5} listening={2,-5} health={3}' -f $item.Name, $item.Port, $listening, $health)
    }
}

function Assert-Dependencies {
    foreach ($dependency in @(@{ Name = 'PostgreSQL'; Port = 5488 }, @{ Name = 'Redis'; Port = 6380 })) {
        if (-not (Test-TcpPort $dependency.Port)) {
            throw "$($dependency.Name) is unavailable on port $($dependency.Port). Start its Docker container first."
        }
    }
    if (-not (Test-TcpPort 19530)) {
        Write-Warning 'Milvus is unavailable on port 19530. Knowledge-base features will be degraded.'
    } elseif (-not (Wait-Http 'http://127.0.0.1:9091/healthz' 60)) {
        Write-Warning 'Milvus port is open but the service did not become healthy. Knowledge-base features will be degraded.'
    }
    if (-not (Test-TcpPort 9997) -and -not (Test-Path $Ollama)) {
        Write-Warning 'Embedding service is unavailable on port 9997. Vector indexing will be disabled.'
    }
}

switch ($Action) {
    'up' {
        Assert-Dependencies
        Start-EmbeddingService
        Start-ManagedService 'sandbox' 10001 'http://127.0.0.1:10001/docs' $SandboxServer @(
            '--config', (Join-Path $ProjectRoot 'sandbox.env'),
            '--extension', (Join-Path $ProjectRoot 'data_analysis_sandbox.py'),
            '--extension', (Join-Path $ProjectRoot 'sandbox_proxy_extension.py')
        )
        Start-ManagedService 'main' 8090 'http://127.0.0.1:8090/ready' $Python @(
            '-m', 'uvicorn', 'app.main:app', '--host', '0.0.0.0', '--port', '8090'
        )
        Show-Status
    }
    'down' {
        Stop-ManagedService 'main'
        Stop-ManagedService 'sandbox'
        Stop-ManagedService 'embedding'
    }
    'restart' {
        Stop-ManagedService 'main'
        Stop-ManagedService 'sandbox'
        Stop-ManagedService 'embedding'
        & $PSCommandPath -Action up
    }
    'status' { Show-Status }
    'logs' {
        $log = Join-Path $LogDirectory "$Service.err.log"
        if (-not (Test-Path $log)) { throw "Log file not found: $log" }
        Get-Content -Path $log -Wait
    }
}
