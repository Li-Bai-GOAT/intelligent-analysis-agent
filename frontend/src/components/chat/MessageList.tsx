import { Fragment, useEffect, useRef } from 'react'
import { MessageBubble } from './MessageBubble'
import { useSessionStore } from '../../stores/session'
import { MessageSquare } from 'lucide-react'

export function MessageList() {
  const messages = useSessionStore((s) => s.messages)
  const currentSession = useSessionStore((s) => s.currentSession)
  const sessions = useSessionStore((s) => s.sessions)
  const bottomRef = useRef<HTMLDivElement>(null)
  const firstUserMessageIndex = messages.findIndex((message) => message.role === 'user')
  const currentSessionInfo = sessions.find((session) => session.session_id === currentSession)

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages])

  if (!currentSession) {
    return (
      <div className="flex-1 flex items-center justify-center text-text-muted">
        <div className="flex flex-col items-center text-center">
          <div className="mb-4 flex size-14 items-center justify-center rounded-2xl border border-border bg-bg-elevated">
            <MessageSquare size={24} className="text-text-muted" />
          </div>
          <p className="text-sm">选择或创建一个对话</p>
        </div>
      </div>
    )
  }

  if (messages.length === 0) {
    return (
      <div className="flex-1 flex items-center justify-center text-text-muted">
        <div className="flex flex-col items-center text-center">
          <div className="mb-4 flex size-14 items-center justify-center rounded-2xl border border-accent/20 bg-accent/10">
            <MessageSquare size={24} className="text-accent" />
          </div>
          <p className="text-sm mb-1">开始新的对话</p>
          <p className="text-xs text-text-muted">输入消息或上传文件开始分析</p>
        </div>
      </div>
    )
  }

  return (
    <div className="flex-1 overflow-y-auto px-5 py-4">
      {messages.map((msg, i) => (
        <Fragment key={i}>
          {i === firstUserMessageIndex && <ConversationTimeDivider timestamp={currentSessionInfo?.created_at} />}
          <MessageBubble message={msg} />
        </Fragment>
      ))}
      <div ref={bottomRef} />
    </div>
  )
}

function ConversationTimeDivider({ timestamp }: { timestamp?: string }) {
  if (!timestamp) return null

  const date = new Date(timestamp)
  const label = Number.isNaN(date.valueOf())
    ? timestamp
    : new Intl.DateTimeFormat('zh-CN', {
      year: 'numeric',
      month: 'long',
      day: 'numeric',
      hour: '2-digit',
      minute: '2-digit',
      hourCycle: 'h23',
    }).format(date)

  return (
    <div className="my-5 flex items-center gap-3" aria-label={`对话开始时间：${label}`}>
      <span className="h-px flex-1 bg-border" />
      <time dateTime={timestamp} className="shrink-0 text-xs text-text-muted">{label}</time>
      <span className="h-px flex-1 bg-border" />
    </div>
  )
}
