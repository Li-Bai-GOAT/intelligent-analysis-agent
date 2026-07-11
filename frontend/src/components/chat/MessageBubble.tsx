import { useState } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { Prism as SyntaxHighlighter } from 'react-syntax-highlighter'
import { oneDark } from 'react-syntax-highlighter/dist/esm/styles/prism'
import { ChevronRight, Loader2, Wrench, User, Bot } from 'lucide-react'
import type { Message } from '../../types'

interface MessageBubbleProps {
  message: Message
}

export function MessageBubble({ message }: MessageBubbleProps) {
  if (message.role === 'user') return <UserMessage message={message} />
  if (message.role === 'assistant') return <AssistantMessage message={message} />
  if (message.role === 'system') return <SystemMessage message={message} />
  return null
}

function UserMessage({ message }: MessageBubbleProps) {
  return (
    <div className="flex justify-end mb-4">
      <div className="flex items-start gap-2.5 max-w-[75%]">
        <div className="flex flex-col items-end gap-1.5">
          {message.files && message.files.length > 0 && (
            <div className="flex flex-wrap gap-1.5 mb-1">
              {message.files.map((f, i) => (
                <span key={i} className="inline-flex items-center gap-1.5 px-2 py-1 bg-bg-surface rounded-md text-xs text-text-secondary border border-border">
                  <span className="w-4 h-4 rounded bg-success/20 text-success flex items-center justify-center text-[8px] font-bold">
                    {f.filename.split('.').pop()?.toUpperCase().slice(0, 3)}
                  </span>
                  {f.filename}
                </span>
              ))}
            </div>
          )}
          <div className="px-3.5 py-2.5 rounded-xl rounded-tr-md bg-accent text-bg-base text-sm whitespace-pre-wrap leading-relaxed">
            {message.content}
          </div>
        </div>
        <div className="w-7 h-7 rounded-full bg-accent/20 text-accent flex items-center justify-center shrink-0 mt-0.5">
          <User size={14} />
        </div>
      </div>
    </div>
  )
}

function AssistantMessage({ message }: MessageBubbleProps) {
  return (
    <div className="flex justify-start mb-4">
      <div className="flex items-start gap-2.5 max-w-[85%]">
        <div className="w-7 h-7 rounded-full bg-bg-elevated text-text-muted flex items-center justify-center shrink-0 mt-0.5 border border-border">
          <Bot size={14} />
        </div>
        <div className="flex flex-col gap-2 min-w-0">
          {message.thinking && <ThinkingBlock content={message.thinking} />}
          {(() => {
            const skipNames = new Set(['ask_user', 'view_historical_plans', 'create_plan', 'confirm_plan', 'ask_user_confirm'])
            const visibleCalls = (message.tool_calls || []).filter((tc) => {
              if (skipNames.has(tc.name)) return false
              const args = tc.arguments || ''
              if (args === '{}' || args === '' || args === '{"code":""}' || args === '{"command":""}') return false
              return true
            })
            if (visibleCalls.length === 0) return null
            return (
              <div className="flex flex-col gap-1.5">
                {visibleCalls.map((tc) => (
                  <ToolCallBlock key={tc.id} name={tc.name} args={tc.arguments} result={tc.result} />
                ))}
              </div>
            )
          })()}
          {message.content && (
            <div className="px-3.5 py-2.5 rounded-xl rounded-tl-md bg-bg-surface border border-border text-sm leading-relaxed">
              <MarkdownContent content={message.content} />
            </div>
          )}
        </div>
      </div>
    </div>
  )
}

function SystemMessage({ message }: MessageBubbleProps) {
  return (
    <div className="flex justify-center mb-3">
      <div className="px-3 py-1.5 rounded-full bg-error/10 border border-error/20 text-xs text-error">
        {message.content}
      </div>
    </div>
  )
}

function ThinkingBlock({ content }: { content: string }) {
  const [expanded, setExpanded] = useState(false)

  return (
    <div className={`rounded-lg border overflow-hidden transition-colors ${expanded ? 'bg-warning/5 border-warning/20' : 'bg-warning/5 border-warning/15'}`}>
      <button
        onClick={() => setExpanded(!expanded)}
        className="flex items-center gap-2 px-3 py-2 w-full text-xs text-warning/80 hover:text-warning transition-colors cursor-pointer"
      >
        <ChevronRight size={12} className={`transition-transform ${expanded ? 'rotate-90' : ''}`} />
        <span className="font-medium">思考过程</span>
      </button>
      {expanded && (
        <div className="px-3 pb-2.5 text-xs text-warning/70 max-h-60 overflow-y-auto whitespace-pre-wrap leading-relaxed">
          {content}
        </div>
      )}
    </div>
  )
}

function ToolCallBlock({ name, args, result }: { name: string; args: string; result?: string }) {
  const [expanded, setExpanded] = useState(false)
  const safeArgs = typeof args === 'string' ? args : JSON.stringify(args || '')

  return (
    <div className="rounded-lg bg-bg-elevated border border-border overflow-hidden">
      <button
        onClick={() => setExpanded(!expanded)}
        className="flex items-center gap-2 px-3 py-2 w-full text-xs text-text-secondary hover:text-text-primary transition-colors cursor-pointer"
      >
        {result !== undefined ? (
          <Wrench size={12} className="text-accent" />
        ) : (
          <Loader2 size={12} className="text-warning animate-spin" />
        )}
        <span className="font-medium">{name}</span>
        <span className="text-text-muted text-[10px] truncate flex-1 text-left">{safeArgs.slice(0, 60)}</span>
        <ChevronRight size={12} className={`transition-transform text-text-muted ${expanded ? 'rotate-90' : ''}`} />
      </button>
      {expanded && (
        <div className="px-3 pb-2.5">
          <pre className="text-[11px] text-text-muted bg-bg-base rounded-md p-2.5 overflow-x-auto max-h-48 leading-relaxed">
            {safeArgs}
          </pre>
          {result !== undefined && (
            <>
              <div className="text-[10px] text-text-muted mt-2 mb-1 font-medium">结果</div>
              <pre className="text-[11px] text-text-secondary bg-bg-base rounded-md p-2.5 overflow-x-auto max-h-48 leading-relaxed">
                {result}
              </pre>
            </>
          )}
        </div>
      )}
    </div>
  )
}

function MarkdownContent({ content }: { content: string }) {
  return (
    <div className="markdown-body">
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        components={{
          code({ className, children, ...props }) {
            const match = /language-(\w+)/.exec(className || '')
            const codeStr = String(children).replace(/\n$/, '')
            if (match) {
              return (
                <SyntaxHighlighter
                  style={oneDark}
                  language={match[1]}
                  PreTag="div"
                  customStyle={{ margin: '0.5em 0', borderRadius: '8px', fontSize: '13px' }}
                >
                  {codeStr}
                </SyntaxHighlighter>
              )
            }
            return <code className={className} {...props}>{children}</code>
          },
        }}
      >
        {content}
      </ReactMarkdown>
    </div>
  )
}
