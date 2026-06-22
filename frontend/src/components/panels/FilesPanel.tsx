import { useState, useEffect, useCallback } from 'react'
import { Api } from '../../api/client'
import { useSessionStore } from '../../stores/session'
import { useAuthStore } from '../../stores/auth'
import { Folder, File, FileText, FileCode, FileSpreadsheet, Download, RefreshCw, ChevronRight, ArrowLeft } from 'lucide-react'

interface FileItem {
  name: string
  path: string
  is_dir: boolean
  type?: string  // 后端返回 "file" | "directory"
  size?: number
}

export function FilesPanel() {
  const currentSession = useSessionStore((s) => s.currentSession)
  const token = useAuthStore((s) => s.token)
  const [files, setFiles] = useState<FileItem[]>([])
  const [currentPath, setCurrentPath] = useState('')
  const [fileContent, setFileContent] = useState<{ name: string; content: string; fullPath: string; isImage?: boolean } | null>(null)
  const [loading, setLoading] = useState(false)

  // 带 token 的下载 URL（用于 <img> 和 <a> 标签）
  const getAuthDownloadUrl = (path: string) => {
    const base = Api.getSandboxFileDownloadUrl(currentSession!, path)
    return `${base}&token=${encodeURIComponent(token || '')}`
  }

  const loadFiles = useCallback(async (path = '') => {
    if (!currentSession) return
    setLoading(true)
    try {
      const data = await Api.listSandboxWorkspace(currentSession, path)
      // 后端返回 type: "file" | "directory"，前端使用 is_dir: boolean
      const mapped = Array.isArray(data) ? data.map(item => ({
        name: item.name,
        path: item.path,
        is_dir: item.is_dir ?? item.type === 'directory',
        size: item.size,
      })) : []
      setFiles(mapped)
      setCurrentPath(path)
      setFileContent(null)
    } catch {
      // 404 = sandbox not created yet, silently ignore
      setFiles([])
    } finally {
      setLoading(false)
    }
  }, [currentSession])

  useEffect(() => { loadFiles() }, [loadFiles])

  const viewFile = async (fullPath: string, name: string) => {
    if (!currentSession) return
    // 后端 _scan_directory 返回的 path 已经是相对于 workspace 根目录的完整路径
    try {
      const data = await Api.getSandboxFileContent(currentSession, fullPath)
      // 处理二进制文件（图片等）
      if (data.binary) {
        if (data.image) {
          setFileContent({ name, content: `[图片文件: ${name}]`, fullPath, isImage: true })
        } else {
          setFileContent({ name, content: `[二进制文件: ${name}]`, fullPath })
        }
      } else {
        setFileContent({ name, content: data.content ?? '', fullPath })
      }
    } catch {
      setFileContent({ name, content: '无法读取文件内容', fullPath })
    }
  }

  const formatSize = (bytes?: number) => {
    if (!bytes) return ''
    if (bytes < 1024) return `${bytes}B`
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)}KB`
    return `${(bytes / (1024 * 1024)).toFixed(1)}MB`
  }

  const getFileIcon = (name: string) => {
    const ext = name.split('.').pop()?.toLowerCase()
    if (['py', 'js', 'ts', 'tsx', 'jsx', 'html', 'css'].includes(ext || '')) return <FileCode size={14} className="text-accent" />
    if (['xlsx', 'xls', 'csv'].includes(ext || '')) return <FileSpreadsheet size={14} className="text-success" />
    if (['md', 'txt', 'log'].includes(ext || '')) return <FileText size={14} className="text-warning" />
    return <File size={14} className="text-text-muted" />
  }

  const breadcrumbs = currentPath ? currentPath.split('/').filter(Boolean) : []

  if (fileContent) {
    return (
      <div className="flex flex-col h-full">
        <div className="flex items-center gap-2 px-3 py-2 border-b border-border">
          <button onClick={() => setFileContent(null)} className="text-text-muted hover:text-text-primary cursor-pointer">
            <ArrowLeft size={14} />
          </button>
          <span className="text-xs font-medium text-text-primary truncate">{fileContent.name}</span>
          <div className="flex-1" />
          <a
            href={getAuthDownloadUrl(fileContent.fullPath)}
            className="text-text-muted hover:text-accent transition-colors"
            download
          >
            <Download size={14} />
          </a>
        </div>
        {fileContent.isImage ? (
          <div className="flex-1 overflow-auto p-3 flex items-center justify-center bg-bg-base">
            <img
              src={getAuthDownloadUrl(fileContent.fullPath)}
              alt={fileContent.name}
              className="max-w-full max-h-full object-contain"
            />
          </div>
        ) : (
          <pre className="flex-1 overflow-auto p-3 text-xs text-text-secondary bg-bg-base leading-relaxed whitespace-pre-wrap break-all">
            {fileContent.content}
          </pre>
        )}
      </div>
    )
  }

  return (
    <div className="flex flex-col h-full">
      <div className="flex items-center gap-2 px-3 py-2 border-b border-border">
        <div className="flex items-center gap-1 text-xs text-text-muted flex-1 min-w-0">
          <button
            onClick={() => loadFiles('')}
            className="hover:text-accent transition-colors cursor-pointer shrink-0"
          >
            workspace
          </button>
          {breadcrumbs.map((crumb, i) => (
            <span key={i} className="flex items-center gap-1">
              <ChevronRight size={10} />
              <button
                onClick={() => loadFiles(breadcrumbs.slice(0, i + 1).join('/'))}
                className="hover:text-accent transition-colors cursor-pointer truncate"
              >
                {crumb}
              </button>
            </span>
          ))}
        </div>
        <div className="flex items-center gap-1">
          <a
            href={currentSession ? `${Api.getSandboxZipDownloadUrl(currentSession)}&token=${encodeURIComponent(token || '')}` : '#'}
            className="p-1 text-text-muted hover:text-accent transition-colors"
            download
            title="下载全部(ZIP)"
          >
            <Download size={14} />
          </a>
          <button onClick={() => loadFiles(currentPath)} className="p-1 text-text-muted hover:text-accent transition-colors cursor-pointer" title="刷新">
            <RefreshCw size={14} className={loading ? 'animate-spin' : ''} />
          </button>
        </div>
      </div>

      <div className="flex-1 overflow-y-auto p-1.5">
        {files.length === 0 ? (
          <div className="text-xs text-text-muted text-center py-8">空目录</div>
        ) : (
          files.map((f) => (
            <div
              key={f.path}
              onClick={() => f.is_dir ? loadFiles(f.path) : viewFile(f.path, f.name)}
              className="flex items-center gap-2 px-2.5 py-1.5 rounded-md hover:bg-bg-hover cursor-pointer group transition-colors"
            >
              {f.is_dir ? (
                <Folder size={14} className="text-warning shrink-0" />
              ) : (
                getFileIcon(f.name)
              )}
              <span className="text-xs text-text-primary truncate flex-1">{f.name}</span>
              {!f.is_dir && f.size !== undefined && (
                <span className="text-[10px] text-text-muted shrink-0">{formatSize(f.size)}</span>
              )}
            </div>
          ))
        )}
      </div>
    </div>
  )
}
