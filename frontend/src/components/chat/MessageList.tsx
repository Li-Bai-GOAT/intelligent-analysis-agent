import { useEffect, useRef } from 'react'
import { MessageBubble } from './MessageBubble'
import { useSessionStore } from '../../stores/session'
import { MessageSquare } from 'lucide-react'

export function MessageList() {
  const messages = useSessionStore((s) => s.messages)
  const currentSession = useSessionStore((s) => s.currentSession)
  const bottomRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages])

  if (!currentSession) {
    return (
      <div className="flex-1 flex items-center justify-center text-text-muted">
        <div className="text-center">
          <div className="w-14 h-14 rounded-2xl bg-bg-elevated border border-border flex items-center justify-center mx-auto mb-4">
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
        <div className="text-center">
          <div className="w-14 h-14 rounded-2xl bg-accent/10 border border-accent/20 flex items-center justify-center mx-auto mb-4">
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
        <MessageBubble key={i} message={msg} />
      ))}
      <div ref={bottomRef} />
    </div>
  )
}
