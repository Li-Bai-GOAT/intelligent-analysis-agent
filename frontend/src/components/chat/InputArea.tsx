import { useState, useRef, useEffect } from 'react'
import { Paperclip, Send, Square } from 'lucide-react'
import { useSessionStore } from '../../stores/session'
import { ContextRing } from './ContextRing'

export function InputArea() {
  const [text, setText] = useState('')
  const [executionMode, setExecutionMode] = useState<'auto' | 'kuncode'>('auto')
  const textareaRef = useRef<HTMLTextAreaElement>(null)
  const fileInputRef = useRef<HTMLInputElement>(null)
  const { sendMessage, pendingFiles, addPendingFiles, removePendingFile, isStreaming, contextInfo, disconnectStream, currentSession } = useSessionStore()

  useEffect(() => {
    if (textareaRef.current) {
      textareaRef.current.style.height = 'auto'
      textareaRef.current.style.height = Math.min(textareaRef.current.scrollHeight, 150) + 'px'
    }
  }, [text])

  const handleSend = () => {
    if (!text.trim() || !currentSession) return
    sendMessage(text.trim(), executionMode)
    setText('')
  }

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      handleSend()
    }
  }

  const handleFileSelect = (e: React.ChangeEvent<HTMLInputElement>) => {
    if (e.target.files) addPendingFiles(Array.from(e.target.files))
    e.target.value = ''
  }

  const handlePaste = (e: React.ClipboardEvent) => {
    const files = Array.from(e.clipboardData.items).filter((i) => i.kind === 'file').map((i) => i.getAsFile()).filter(Boolean) as File[]
    if (files.length > 0) addPendingFiles(files)
  }

  return (
    <div className="px-5 py-3 bg-bg-surface border-t border-border">
      {pendingFiles.length > 0 && (
        <div className="flex flex-wrap gap-2 mb-2">
          {pendingFiles.map((f, i) => (
            <span key={i} className="inline-flex items-center gap-1.5 px-2.5 py-1 bg-bg-elevated rounded-md text-xs text-text-secondary border border-border">
              <span className="w-5 h-5 rounded bg-success/20 text-success flex items-center justify-center text-[10px] font-bold">
                {f.name.split('.').pop()?.toUpperCase().slice(0, 3)}
              </span>
              <span className="max-w-32 truncate">{f.name}</span>
              <button onClick={() => removePendingFile(i)} className="text-text-muted hover:text-error cursor-pointer">×</button>
            </span>
          ))}
        </div>
      )}

      <div className="mb-2 flex items-center gap-1" role="group" aria-label="执行模式">
        <button type="button" onClick={() => setExecutionMode('auto')} className={`rounded px-2.5 py-1 text-xs transition-colors ${executionMode === 'auto' ? 'bg-accent text-bg-base' : 'bg-bg-elevated text-text-muted hover:text-text-primary'}`}>自动</button>
        <button type="button" onClick={() => setExecutionMode('kuncode')} className={`rounded px-2.5 py-1 text-xs transition-colors ${executionMode === 'kuncode' ? 'bg-accent text-bg-base' : 'bg-bg-elevated text-text-muted hover:text-text-primary'}`}>KunCode</button>
      </div>

      <div className="flex items-end gap-2.5">
        <input type="file" ref={fileInputRef} multiple hidden onChange={handleFileSelect} />
        <button
          onClick={() => fileInputRef.current?.click()}
          className="p-2.5 rounded-lg bg-bg-elevated border border-border text-text-muted hover:text-accent hover:border-accent/30 transition-colors cursor-pointer"
          title="上传文件"
        >
          <Paperclip size={18} />
        </button>

        <textarea
          ref={textareaRef}
          value={text}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={handleKeyDown}
          onPaste={handlePaste}
          placeholder="输入消息..."
          rows={1}
          className="flex-1 resize-none bg-bg-elevated border border-border rounded-lg px-3.5 py-2.5 text-sm text-text-primary placeholder:text-text-muted focus:outline-none focus:border-accent focus:ring-1 focus:ring-accent/30 transition-all"
        />

        {contextInfo && (
          <ContextRing
            percent={contextInfo.usage_percent}
            tokens={contextInfo.estimated_tokens}
            maxTokens={contextInfo.max_tokens}
          />
        )}

        <button
          onClick={isStreaming ? disconnectStream : handleSend}
          disabled={!isStreaming && (!text.trim() || !currentSession)}
          className={`p-2.5 rounded-lg transition-all cursor-pointer disabled:opacity-40 disabled:cursor-not-allowed
            ${isStreaming
              ? 'bg-error/15 text-error border border-error/30 hover:bg-error/25'
              : 'bg-accent text-bg-base hover:bg-accent-hover shadow-[0_2px_8px_rgba(45,212,168,0.25)]'
            }`}
          title={isStreaming ? '暂停' : '发送'}
        >
          {isStreaming ? <Square size={18} /> : <Send size={18} />}
        </button>
      </div>
    </div>
  )
}
