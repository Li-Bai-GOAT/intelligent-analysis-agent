import { useState } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { PrismLight as SyntaxHighlighter } from 'react-syntax-highlighter'
import { oneDark } from 'react-syntax-highlighter/dist/esm/styles/prism'
import css from 'react-syntax-highlighter/dist/esm/languages/prism/css'
import python from 'react-syntax-highlighter/dist/esm/languages/prism/python'
import bash from 'react-syntax-highlighter/dist/esm/languages/prism/bash'
import json from 'react-syntax-highlighter/dist/esm/languages/prism/json'
import typescript from 'react-syntax-highlighter/dist/esm/languages/prism/typescript'
import jsx from 'react-syntax-highlighter/dist/esm/languages/prism/jsx'
import tsx from 'react-syntax-highlighter/dist/esm/languages/prism/tsx'
import sql from 'react-syntax-highlighter/dist/esm/languages/prism/sql'
import yaml from 'react-syntax-highlighter/dist/esm/languages/prism/yaml'
import markdown from 'react-syntax-highlighter/dist/esm/languages/prism/markdown'
import { ChevronRight, User, Bot } from 'lucide-react'
import type { Message } from '../../types'

// PrismLight 使用精简核心，显式注册所需语言，不依赖其他入口的隐式注册。
// 避免全量 Prism(~300+ 语言)打入首屏 bundle。注意按依赖顺序注册。
SyntaxHighlighter.registerLanguage('css', css)
SyntaxHighlighter.registerLanguage('python', python)
SyntaxHighlighter.registerLanguage('bash', bash)
SyntaxHighlighter.registerLanguage('json', json)
SyntaxHighlighter.registerLanguage('typescript', typescript)
SyntaxHighlighter.registerLanguage('jsx', jsx)
SyntaxHighlighter.registerLanguage('tsx', tsx)
SyntaxHighlighter.registerLanguage('sql', sql)
SyntaxHighlighter.registerLanguage('yaml', yaml)
SyntaxHighlighter.registerLanguage('markdown', markdown)

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
      <div className="flex items-start gap-2.5 max-w-[80%]">
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
          <div className="rounded-xl border border-transparent bg-accent px-3.5 py-2.5 text-sm leading-relaxed text-bg-base whitespace-pre-wrap">
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
      <div className="flex items-start gap-2.5 max-w-[80%]">
        <div className="w-7 h-7 rounded-full bg-bg-elevated text-text-muted flex items-center justify-center shrink-0 mt-0.5 border border-border">
          <Bot size={14} />
        </div>
        <div className="flex flex-col gap-2 min-w-0">
          {message.thinking && <ThinkingBlock content={message.thinking} running={message.status === 'running'} />}
          {message.content && (
            <div className="rounded-xl border border-border bg-bg-surface px-3.5 py-2.5 text-sm leading-relaxed">
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

function ThinkingBlock({ content, running }: { content: string; running: boolean }) {
  const [expanded, setExpanded] = useState(false)

  return (
    <div className={`rounded-lg border overflow-hidden transition-colors ${expanded ? 'bg-warning/5 border-warning/20' : 'bg-warning/5 border-warning/15'}`}>
      <button
        onClick={() => setExpanded(!expanded)}
        className="flex items-center gap-2 px-3 py-2 w-full text-xs text-warning/80 hover:text-warning transition-colors cursor-pointer"
      >
        <ChevronRight size={12} className={`transition-transform ${expanded ? 'rotate-90' : ''}`} />
        <span className="font-medium">{running ? '正在分析' : '思考过程'}</span>
      </button>
      {expanded && (
        <div className="px-3 pb-2.5 text-xs text-warning/70 max-h-60 overflow-y-auto whitespace-pre-wrap leading-relaxed">
          {content}
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
