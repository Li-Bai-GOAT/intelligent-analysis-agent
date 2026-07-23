import { useEffect, useMemo, useRef, useState } from 'react'
import {
  AlertCircle,
  Braces,
  CheckCircle2,
  ChevronDown,
  ChevronRight,
  Database,
  FileCode2,
  Hammer,
  Loader2,
  Search,
  Server,
  Sparkles,
  Terminal,
  Wrench,
} from 'lucide-react'
import { useSessionStore } from '../../stores/session'
import type { ToolCall } from '../../types'

type ToolStatus = 'running' | 'success' | 'error'
type ToolGroup = 'kuncode' | 'sandbox' | 'builtin' | 'interaction'

interface ToolMeta {
  label: string
  group: ToolGroup
  accent: string
  icon: typeof Terminal
}

interface ParsedInput {
  summary: string
  detail: string
  lang: 'text' | 'python' | 'bash' | 'json'
  fields: Array<{ label: string; value: string }>
}

interface TerminalEntry {
  id: string
  name: string
  meta: ToolMeta
  input: ParsedInput
  output: string
  status: ToolStatus
  internalCalls: InternalCall[]
}

interface InternalCall {
  id: string
  name: string
  detail: string
  status?: ToolStatus
}

const TOOL_META: Record<string, ToolMeta> = {
  run_kuncode: { label: 'KunCode', group: 'kuncode', accent: 'cyan', icon: Sparkles },
  run_ipython_cell: { label: 'Python', group: 'sandbox', accent: 'green', icon: FileCode2 },
  run_shell_command: { label: 'Shell', group: 'sandbox', accent: 'amber', icon: Terminal },
  kuncode_session_list: { label: 'KunCode Sessions', group: 'builtin', accent: 'violet', icon: Server },
  kuncode_mcp_list: { label: 'KunCode MCP', group: 'builtin', accent: 'violet', icon: Braces },
  search_knowledge: { label: 'Knowledge Search', group: 'builtin', accent: 'blue', icon: Search },
  kuncode_prd_update: { label: 'PRD Preview', group: 'interaction', accent: 'cyan', icon: Hammer },
  preview_plan: { label: 'Plan Preview', group: 'interaction', accent: 'blue', icon: Hammer },
  ask_user: { label: 'Ask User', group: 'interaction', accent: 'amber', icon: Wrench },
}

const HIDDEN_TOOLS = new Set([
  'create_plan',
  'confirm_plan',
  'ask_user_confirm',
  'view_historical_plans',
])

const INTERNAL_TOOL_NAMES = [
  'bash',
  'read',
  'write',
  'edit',
  'grep',
  'glob',
  'ls',
  'list',
  'webfetch',
  'websearch',
  'todowrite',
  'todoread',
  'task',
]

function getMeta(name: string): ToolMeta {
  return TOOL_META[name] || { label: name, group: 'builtin', accent: 'slate', icon: Wrench }
}

function safeJsonParse(value: string): unknown {
  try {
    return JSON.parse(value)
  } catch {
    return null
  }
}

function asRecord(value: unknown): Record<string, unknown> | null {
  return value && typeof value === 'object' && !Array.isArray(value) ? value as Record<string, unknown> : null
}

function toDisplayString(value: unknown): string {
  if (value === null || value === undefined) return ''
  if (typeof value === 'string') return value
  return JSON.stringify(value, null, 2)
}

function truncate(value: string, max = 140): string {
  const clean = value.replace(/\s+/g, ' ').trim()
  if (clean.length <= max) return clean
  return `${clean.slice(0, max - 1)}...`
}

function stripAnsi(value: string): string {
  return value
    // eslint-disable-next-line no-control-regex
    .replace(/\x1B\][^\x07]*(\x07|\x1B\\)/g, '')
    // eslint-disable-next-line no-control-regex
    .replace(/\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])/g, '')
}

function parseOutput(raw?: string): string {
  if (!raw) return ''
  const parsed = safeJsonParse(raw)
  if (Array.isArray(parsed)) {
    return stripAnsi(parsed.map((item) => {
      const record = asRecord(item)
      if (!record) return ''
      if (record.type === 'text') return toDisplayString(record.text)
      if ('content' in record) return toDisplayString(record.content)
      return ''
    }).join('')).trim()
  }
  if (typeof parsed === 'string') return stripAnsi(parsed)
  const record = asRecord(parsed)
  if (record) {
    if (typeof record.text === 'string') return stripAnsi(record.text)
    if (typeof record.output === 'string') return stripAnsi(record.output)
    if (typeof record.content === 'string') return stripAnsi(record.content)
  }
  return stripAnsi(raw)
}

function getStatus(output: string, result?: string, executionStatus?: ToolCall['execution_status']): ToolStatus {
  if (executionStatus === 'running') return 'running'
  if (executionStatus === 'failed' || executionStatus === 'cancelled') return 'error'
  if (executionStatus === 'completed') return 'success'
  if (result === undefined) return 'running'
  const lower = output.toLowerCase()
  if (
    lower.includes('traceback') ||
    lower.includes('[error]') ||
    lower.includes('error:') ||
    lower.includes('exception') ||
    lower.includes('failed')
  ) {
    return 'error'
  }
  return 'success'
}

function commandFromKuncodeInput(input: Record<string, unknown>): string {
  const parts = ['kuncode run']
  if (input.continue_session) parts.push('-c')
  if (input.session_id) parts.push(`-s ${input.session_id}`)
  if (input.agent) parts.push(`--agent ${input.agent}`)
  if (input.model) parts.push(`-m ${input.model}`)
  const files = Array.isArray(input.files) ? input.files : []
  for (const file of files) parts.push(`-f ${file}`)
  if (input.output_format && input.output_format !== 'default') parts.push(`--format ${input.output_format}`)
  if (input.prompt) parts.push(JSON.stringify(String(input.prompt)))
  return parts.join(' ')
}

function parseInput(toolName: string, rawInput: string): ParsedInput {
  const parsed = safeJsonParse(rawInput)
  const record = asRecord(parsed)

  if (record) {
    if (toolName === 'run_kuncode') {
      const prompt = toDisplayString(record.prompt)
      const fields = [
        { label: 'Agent', value: toDisplayString(record.agent || 'default') },
        { label: 'Model', value: toDisplayString(record.model || 'default') },
        { label: 'Continue', value: record.continue_session ? 'yes' : 'no' },
      ]
      const files = Array.isArray(record.files) ? record.files.map(String).join(', ') : ''
      if (files) fields.push({ label: 'Files', value: files })
      return {
        summary: truncate(prompt || commandFromKuncodeInput(record)),
        detail: `${commandFromKuncodeInput(record)}\n\n${prompt}`,
        lang: 'text',
        fields,
      }
    }

    if (typeof record.code === 'string') {
      return {
        summary: truncate(record.code.split('\n')[0] || 'Python code'),
        detail: record.code,
        lang: 'python',
        fields: [],
      }
    }

    if (typeof record.command === 'string') {
      return {
        summary: truncate(record.command),
        detail: record.command,
        lang: 'bash',
        fields: [],
      }
    }

    if (typeof record.query === 'string') {
      const fields = [
        { label: 'Top K', value: toDisplayString(record.top_k || 3) },
      ]
      if (record.category) fields.push({ label: 'Category', value: toDisplayString(record.category) })
      return {
        summary: truncate(record.query),
        detail: JSON.stringify(record, null, 2),
        lang: 'json',
        fields,
      }
    }

    if (typeof record.prompt === 'string') {
      return {
        summary: truncate(record.prompt),
        detail: record.prompt,
        lang: 'text',
        fields: [],
      }
    }

    return {
      summary: truncate(JSON.stringify(record)),
      detail: JSON.stringify(record, null, 2),
      lang: 'json',
      fields: [],
    }
  }

  const fallback = rawInput || '{}'
  return {
    summary: truncate(fallback),
    detail: fallback,
    lang: fallback.trim().startsWith('{') ? 'json' : 'text',
    fields: [],
  }
}

function parseJsonLinesForInternalCalls(output: string): InternalCall[] {
  const calls: InternalCall[] = []
  output.split('\n').forEach((line, index) => {
    const parsed = safeJsonParse(line.trim())
    const record = asRecord(parsed)
    if (!record) return
    const type = String(record.type || record.event || '')
    const candidate = record.tool || record.tool_name || record.name
    if (!candidate || !/tool/i.test(type)) return
    calls.push({
      id: `json-${index}`,
      name: String(candidate),
      detail: truncate(toDisplayString(record.input || record.arguments || record.command || record.path || record.query || ''), 180),
      status: /result|done|success/i.test(type) ? 'success' : undefined,
    })
  })
  return calls
}

function parseTextForInternalCalls(output: string): InternalCall[] {
  const calls: InternalCall[] = []
  const seen = new Set<string>()

  output.split('\n').forEach((rawLine, index) => {
    const line = rawLine.trim()
    if (!line) return

    const patterns = [
      new RegExp(`(?:^|[>•●⏺*\\-\\s])(${INTERNAL_TOOL_NAMES.join('|')}|mcp__[\\w.-]+)\\s*\\((.*)`, 'i'),
      new RegExp(`(?:tool|calling|调用|工具)\\s*[:：-]?\\s*(${INTERNAL_TOOL_NAMES.join('|')}|mcp__[\\w.-]+)\\b\\s*[:：-]?\\s*(.*)`, 'i'),
      new RegExp(`^(${INTERNAL_TOOL_NAMES.join('|')}|mcp__[\\w.-]+)\\s*[:：-]\\s*(.*)`, 'i'),
    ]

    for (const pattern of patterns) {
      const match = line.match(pattern)
      if (!match) continue
      const name = match[1].toLowerCase()
      const detail = truncate((match[2] || '').replace(/\)+$/, ''), 180)
      const key = `${name}:${detail}`
      if (!seen.has(key)) {
        seen.add(key)
        calls.push({ id: `text-${index}-${calls.length}`, name, detail })
      }
      break
    }
  })

  return calls
}

function extractInternalCalls(output: string): InternalCall[] {
  const calls = [...parseJsonLinesForInternalCalls(output), ...parseTextForInternalCalls(output)]
  return calls.slice(0, 30)
}

function shouldShowTool(tool: ToolCall): boolean {
  if (HIDDEN_TOOLS.has(tool.name)) return false
  const args = tool.arguments || ''
  if (args === '{}' || args === '' || args === '{"code":""}' || args === '{"command":""}') {
    return tool.result !== undefined && parseOutput(tool.result).length > 0
  }
  return true
}

function groupLabel(group: ToolGroup): string {
  switch (group) {
    case 'kuncode': return 'KunCode 调用'
    case 'sandbox': return '沙箱执行'
    case 'builtin': return '内置工具'
    case 'interaction': return '交互确认'
  }
}

function accentClasses(accent: string, status: ToolStatus): { icon: string; badge: string; line: string } {
  if (status === 'error') {
    return { icon: 'text-[#ff6b6b]', badge: 'text-[#ff6b6b] bg-[#ff6b6b]/10 border-[#ff6b6b]/20', line: 'border-[#ff6b6b]/35' }
  }
  if (status === 'running') {
    return { icon: 'text-[#f6b44b]', badge: 'text-[#f6b44b] bg-[#f6b44b]/10 border-[#f6b44b]/20', line: 'border-[#f6b44b]/35' }
  }
  switch (accent) {
    case 'cyan': return { icon: 'text-[#55d6ff]', badge: 'text-[#55d6ff] bg-[#55d6ff]/10 border-[#55d6ff]/20', line: 'border-[#55d6ff]/35' }
    case 'green': return { icon: 'text-[#7ee787]', badge: 'text-[#7ee787] bg-[#7ee787]/10 border-[#7ee787]/20', line: 'border-[#7ee787]/35' }
    case 'amber': return { icon: 'text-[#f6b44b]', badge: 'text-[#f6b44b] bg-[#f6b44b]/10 border-[#f6b44b]/20', line: 'border-[#f6b44b]/35' }
    case 'blue': return { icon: 'text-[#7aa2ff]', badge: 'text-[#7aa2ff] bg-[#7aa2ff]/10 border-[#7aa2ff]/20', line: 'border-[#7aa2ff]/35' }
    case 'violet': return { icon: 'text-[#c792ea]', badge: 'text-[#c792ea] bg-[#c792ea]/10 border-[#c792ea]/20', line: 'border-[#c792ea]/35' }
    default: return { icon: 'text-[#a6b0c3]', badge: 'text-[#a6b0c3] bg-[#a6b0c3]/10 border-[#a6b0c3]/20', line: 'border-[#a6b0c3]/25' }
  }
}

function statusLabel(status: ToolStatus): string {
  if (status === 'running') return 'RUNNING'
  if (status === 'error') return 'ERROR'
  return 'DONE'
}

function languageLabel(lang: ParsedInput['lang']): string {
  if (lang === 'python') return 'python'
  if (lang === 'bash') return 'shell'
  if (lang === 'json') return 'json'
  return 'text'
}

function EntryDetails({ entry }: { entry: TerminalEntry }) {
  const [inputOpen, setInputOpen] = useState(entry.name === 'run_kuncode')
  const [outputOpen, setOutputOpen] = useState(false)
  const outputLines = entry.output ? entry.output.split('\n') : []
  const isLongOutput = outputLines.length > 14 || entry.output.length > 2200
  const visibleOutput = !isLongOutput || outputOpen
    ? entry.output
    : `${outputLines.slice(0, 14).join('\n')}\n... ${outputLines.length} lines total`

  return (
    <div className="ml-8 mt-2 space-y-2">
      {entry.input.fields.length > 0 && (
        <div className="flex flex-wrap gap-1.5">
          {entry.input.fields.map((field) => (
            <span key={field.label} className="rounded border border-[#303947] bg-[#101823] px-2 py-0.5 text-[10px] text-[#aeb9cc]">
              <span className="text-[#667085]">{field.label}</span>
              <span className="mx-1 text-[#3d4757]">=</span>
              {field.value}
            </span>
          ))}
        </div>
      )}

      <button
        type="button"
        onClick={() => setInputOpen((value) => !value)}
        className="flex w-full items-center gap-1.5 rounded-md px-2 py-1 text-left text-[11px] text-[#9aa7bd] hover:bg-[#18202b]"
      >
        {inputOpen ? <ChevronDown size={12} /> : <ChevronRight size={12} />}
        <span className="text-[#5f6b7f]">{languageLabel(entry.input.lang)}</span>
        <span className="min-w-0 flex-1 truncate text-[#d7deea]">{entry.input.summary}</span>
      </button>

      {inputOpen && (
        <pre className="max-h-72 overflow-auto rounded-md border border-[#263241] bg-[#0a0f16] p-3 text-[11px] leading-relaxed text-[#d7deea] whitespace-pre-wrap break-words">
          {entry.input.detail}
        </pre>
      )}

      {entry.internalCalls.length > 0 && (
        <div className="rounded-md border border-[#263241] bg-[#0f151e]">
          <div className="flex items-center gap-2 border-b border-[#263241] px-3 py-1.5 text-[10px] uppercase tracking-wide text-[#6d7890]">
            <Braces size={12} />
            KunCode 内部工具
            <span className="rounded bg-[#1d2734] px-1.5 py-0.5 text-[#9aa7bd]">{entry.internalCalls.length}</span>
          </div>
          <div className="divide-y divide-[#1d2734]">
            {entry.internalCalls.map((call) => (
              <div key={call.id} className="flex items-start gap-2 px-3 py-2">
                <span className="mt-0.5 rounded border border-[#39475a] bg-[#162030] px-1.5 py-0.5 text-[10px] text-[#55d6ff]">
                  {call.name}
                </span>
                <span className="min-w-0 flex-1 break-words text-[11px] text-[#c7d0df]">{call.detail || 'tool call'}</span>
              </div>
            ))}
          </div>
        </div>
      )}

      {entry.output && (
        <div className={`rounded-md border ${entry.status === 'error' ? 'border-[#ff6b6b]/30 bg-[#2a1116]' : 'border-[#263241] bg-[#0f151e]'}`}>
          <button
            type="button"
            onClick={() => isLongOutput && setOutputOpen((value) => !value)}
            className="flex w-full items-center gap-2 border-b border-[#263241] px-3 py-1.5 text-left text-[10px] text-[#7d889b] hover:bg-[#18202b]"
          >
            <Database size={12} />
            输出
            <span>{outputLines.length} 行</span>
            {isLongOutput && <span className="ml-auto text-[#55d6ff]">{outputOpen ? '收起' : '展开全部'}</span>}
          </button>
          <pre className={`max-h-[420px] overflow-auto p-3 text-[11px] leading-relaxed whitespace-pre-wrap break-words ${entry.status === 'error' ? 'text-[#ffb4b4]' : 'text-[#c7d0df]'}`}>
            {visibleOutput}
          </pre>
        </div>
      )}
    </div>
  )
}

export function TerminalPanel() {
  const messages = useSessionStore((s) => s.messages)
  const isStreaming = useSessionStore((s) => s.isStreaming)
  const bodyRef = useRef<HTMLDivElement>(null)

  const entries = useMemo<TerminalEntry[]>(() => {
    const collected: TerminalEntry[] = []
    for (const message of messages) {
      for (const tool of message.tool_calls || []) {
        if (!shouldShowTool(tool)) continue
        const meta = getMeta(tool.name)
        const input = parseInput(tool.name, tool.arguments || '')
        const output = parseOutput(tool.result)
        const status = getStatus(output, tool.result, tool.execution_status)
        collected.push({
          id: tool.id || `${tool.name}-${collected.length}`,
          name: tool.name,
          meta,
          input,
          output,
          status,
          internalCalls: tool.name === 'run_kuncode' ? extractInternalCalls(output) : [],
        })
      }
    }
    return collected
  }, [messages])
  const lastEntryOutput = entries[entries.length - 1]?.output

  useEffect(() => {
    if (!bodyRef.current) return
    bodyRef.current.scrollTop = bodyRef.current.scrollHeight
  }, [entries.length, lastEntryOutput])

  const counts = entries.reduce<Record<ToolGroup, number>>((acc, entry) => {
    acc[entry.meta.group] = (acc[entry.meta.group] || 0) + 1
    return acc
  }, { kuncode: 0, sandbox: 0, builtin: 0, interaction: 0 })

  return (
    <div className="flex h-full flex-col bg-[#080d13]">
      <div className="border-b border-[#263241] bg-[#101722] px-3 py-2">
        <div className="flex items-center gap-2">
          <div className="flex gap-1.5">
            <span className="h-2.5 w-2.5 rounded-full bg-[#ff5f56]" />
            <span className="h-2.5 w-2.5 rounded-full bg-[#ffbd2e]" />
            <span className="h-2.5 w-2.5 rounded-full bg-[#27c93f]" />
          </div>
          <div className="min-w-0 flex-1 text-center font-mono text-[11px] text-[#aeb9cc]">
            agent runtime
          </div>
          {isStreaming && <Loader2 size={13} className="animate-spin text-[#55d6ff]" />}
        </div>
        <div className="mt-2 flex flex-wrap gap-1.5">
          {(['kuncode', 'sandbox', 'builtin', 'interaction'] as ToolGroup[]).map((group) => (
            <span key={group} className="rounded border border-[#263241] bg-[#0b1119] px-2 py-0.5 text-[10px] text-[#7d889b]">
              {groupLabel(group)} <span className="text-[#d7deea]">{counts[group] || 0}</span>
            </span>
          ))}
        </div>
      </div>

      <div ref={bodyRef} className="flex-1 overflow-y-auto p-3 font-mono text-xs leading-relaxed">
        {entries.length === 0 ? (
          <div className="flex h-full items-center justify-center text-center">
            <div>
              <Terminal className="mx-auto mb-3 text-[#3d4a5d]" size={28} />
              <div className="text-sm text-[#aeb9cc]">等待工具调用</div>
              <div className="mt-1 text-[11px] text-[#647086]">KunCode、Shell、Python 和内置工具会在这里实时显示</div>
            </div>
          </div>
        ) : (
          <div className="space-y-3">
            {entries.map((entry, index) => {
              const Icon = entry.meta.icon
              const accent = accentClasses(entry.meta.accent, entry.status)
              return (
                <section key={entry.id} className={`rounded-lg border ${accent.line} bg-[#0d141d] px-3 py-2 shadow-[0_12px_30px_rgba(0,0,0,0.18)]`}>
                  <div className="flex items-start gap-2">
                    <span className="mt-0.5 w-5 shrink-0 text-right text-[10px] text-[#4f5d73]">{index + 1}</span>
                    <Icon size={15} className={`mt-0.5 shrink-0 ${accent.icon}`} />
                    <div className="min-w-0 flex-1">
                      <div className="flex flex-wrap items-center gap-2">
                        <span className="font-semibold text-[#f2f6fb]">{entry.meta.label}</span>
                        <span className="text-[10px] text-[#6d7890]">{groupLabel(entry.meta.group)}</span>
                        <span className={`rounded border px-1.5 py-0.5 text-[10px] ${accent.badge}`}>
                          {statusLabel(entry.status)}
                        </span>
                        {entry.status === 'success' && <CheckCircle2 size={12} className="text-[#7ee787]" />}
                        {entry.status === 'error' && <AlertCircle size={12} className="text-[#ff6b6b]" />}
                      </div>
                      <div className="mt-1 truncate text-[11px] text-[#aeb9cc]">{entry.input.summary}</div>
                    </div>
                    {entry.status === 'running' && <Loader2 size={14} className="mt-0.5 animate-spin text-[#f6b44b]" />}
                  </div>
                  <EntryDetails entry={entry} />
                </section>
              )
            })}

            {isStreaming && entries.every((entry) => entry.status !== 'running') && (
              <div className="flex items-center gap-2 rounded-md border border-[#263241] bg-[#0d141d] px-3 py-2 text-[11px] text-[#55d6ff]">
                <Loader2 size={13} className="animate-spin" />
                Agent 正在思考，等待下一次工具调用...
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  )
}
