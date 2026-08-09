import { useState, useRef, useEffect } from 'react'
import { Loader2, Paperclip, Send, Square } from 'lucide-react'
import { useSessionStore } from '../../stores/session'
import { ContextRing } from './ContextRing'

export function InputArea() {
  const [text, setText] = useState('')
  const [executionMode, setExecutionMode] = useState<'auto' | 'kuncode'>('auto')
  const textareaRef = useRef<HTMLTextAreaElement>(null)
  const fileInputRef = useRef<HTMLInputElement>(null)
  const { sendMessage, pendingFiles, addPendingFiles, removePendingFile, isStreaming, contextInfo, disconnectStream, currentSession, streamState } = useSessionStore()

  useEffect(() => {
    if (textareaRef.current) {
      textareaRef.current.style.height = 'auto'
      textareaRef.current.style.height = Math.min(textareaRef.current.scrollHeight, 150) + 'px'
    }
  }, [text])

  const handleSend = async () => {
    if (!text.trim() || !currentSession) return
    if (await sendMessage(text.trim(), executionMode)) setText('')
  }

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      void handleSend()
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
    <div className="border-t border-border bg-bg-surface px-4 py-2.5">
      <div className="mx-auto w-full max-w-6xl">
      {pendingFiles.length > 0 && (
        <div className="mb-2 flex flex-wrap gap-2">
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

      {isStreaming && streamState.currentToolMessage && (
        <div className="mb-3 inline-flex items-center gap-2 rounded-lg border border-accent/25 bg-accent/10 px-3 py-1.5 text-xs text-accent" role="status">
          <Loader2 size={13} className="animate-spin" />
          <span>{streamState.currentToolName === 'run_kuncode' ? 'KunCode：' : ''}{streamState.currentToolMessage}</span>
          {streamState.currentToolStage === 'repairing' && streamState.currentToolAttemptIndex && (
            <span className="text-text-secondary">第 {streamState.currentToolAttemptIndex} 次尝试</span>
          )}
        </div>
      )}

      <div className="mb-2 inline-flex items-center gap-1" role="group" aria-label="执行模式">
        <button type="button" onClick={() => setExecutionMode('auto')} className={`inline-flex h-[38px] w-[82px] items-center justify-center rounded-lg border text-[11px] font-medium transition-colors ${executionMode === 'auto' ? 'border-accent bg-accent text-bg-base shadow-sm' : 'border-border bg-bg-elevated text-text-muted hover:border-border-light hover:bg-bg-hover hover:text-text-primary'}`}>自动</button>
        <button type="button" onClick={() => setExecutionMode('kuncode')} className={`inline-flex h-[38px] w-[82px] items-center justify-center rounded-lg border text-[11px] font-medium transition-colors ${executionMode === 'kuncode' ? 'border-accent bg-accent text-bg-base shadow-sm' : 'border-border bg-bg-elevated text-text-muted hover:border-border-light hover:bg-bg-hover hover:text-text-primary'}`}>KunCode</button>
      </div>

      <div className="flex h-[42px] items-center gap-1.5 rounded-xl border border-border-light bg-bg-elevated p-[3px] shadow-sm transition-colors focus-within:border-accent/60 focus-within:ring-1 focus-within:ring-accent/15">
        <input type="file" ref={fileInputRef} multiple hidden onChange={handleFileSelect} />
        <button
          onClick={() => fileInputRef.current?.click()}
          className="inline-flex size-[34px] shrink-0 items-center justify-center rounded-lg bg-bg-muted text-text-secondary transition-colors hover:bg-bg-hover hover:text-text-primary cursor-pointer"
          title="上传文件"
        >
          <Paperclip size={17} />
        </button>

        <div className="relative min-h-[34px] min-w-0 flex-1">
          <textarea
            ref={textareaRef}
            value={text}
            onChange={(e) => setText(e.target.value)}
            onKeyDown={handleKeyDown}
            onPaste={handlePaste}
            rows={1}
            placeholder="问问 Data agent"
            aria-label="向 Data agent 提问"
            className="block h-[34px] min-h-[34px] max-h-[150px] w-full resize-none overflow-y-auto bg-transparent px-2 py-0 text-base leading-[34px] text-text-primary placeholder:text-transparent focus:outline-none"
          />
          {!text && (
            <span aria-hidden="true" className="pointer-events-none absolute inset-0 flex items-center px-2 text-base leading-none text-text-muted">
              问问 Data agent
            </span>
          )}
        </div>

        {contextInfo && (
          <ContextRing
            percent={contextInfo.usage_percent}
            tokens={contextInfo.estimated_tokens}
            maxTokens={contextInfo.max_tokens}
          />
        )}

        <button
          onClick={isStreaming ? disconnectStream : () => void handleSend()}
          disabled={!isStreaming && (!text.trim() || !currentSession)}
          className={`inline-flex size-[34px] shrink-0 items-center justify-center rounded-lg transition-all cursor-pointer disabled:opacity-40 disabled:cursor-not-allowed
            ${isStreaming
              ? 'bg-error/15 text-error border border-error/30 hover:bg-error/25'
              : 'bg-accent text-bg-base hover:bg-accent-hover shadow-[0_2px_8px_rgba(45,212,168,0.25)]'
            }`}
          title={isStreaming ? '暂停' : '发送'}
        >
          {isStreaming ? <Square size={16} /> : <Send size={17} />}
        </button>
      </div>
      </div>
    </div>
  )
}
