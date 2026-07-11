import { useEffect, useMemo, useState } from 'react'
import { Check, Clock, Send, X } from 'lucide-react'
import { Api } from '../../api/client'
import { useSessionStore } from '../../stores/session'

export function PreviewConfirm() {
  const pendingPreview = useSessionStore((s) => s.pendingPreview)
  const currentSession = useSessionStore((s) => s.currentSession)
  const clearPendingPreview = useSessionStore((s) => s.clearPendingPreview)
  const [input, setInput] = useState('')
  const [loading, setLoading] = useState(false)

  useEffect(() => {
    const timer = window.setTimeout(() => {
      if (pendingPreview?.type === 'kuncode_preview') {
        setInput(String(pendingPreview.prompt || ''))
      } else {
        setInput('')
      }
    }, 0)
    return () => window.clearTimeout(timer)
  }, [pendingPreview?.preview_id, pendingPreview?.type, pendingPreview?.prompt])

  const meta = useMemo(() => {
    if (!pendingPreview) {
      return { title: '', message: '', confirmLabel: '确认', showInput: false, multiline: false }
    }
    switch (pendingPreview.type) {
      case 'user_input_request':
      case 'user_input_required':
        return {
          title: 'AI 等待输入',
          message: String(pendingPreview.message || 'AI 需要你补充信息后继续执行。'),
          confirmLabel: '发送',
          showInput: true,
          multiline: false,
        }
      case 'kuncode_preview':
        return {
          title: '确认 KunCode 调用',
          message: '确认或编辑即将交给 KunCode 执行的任务描述。',
          confirmLabel: '执行',
          showInput: true,
          multiline: true,
        }
      case 'plan_preview':
        return {
          title: '确认分析计划',
          message: '确认后，Agent 会按该计划继续执行。',
          confirmLabel: '确认计划',
          showInput: false,
          multiline: false,
        }
      case 'auto_continue':
        return {
          title: '继续执行',
          message: '当前计划仍有未完成子任务，是否继续执行？',
          confirmLabel: '继续',
          showInput: false,
          multiline: false,
        }
      default:
        return { title: '确认操作', message: '', confirmLabel: '确认', showInput: false, multiline: false }
    }
  }, [pendingPreview])

  if (!pendingPreview || !currentSession) return null

  const isUserInput = pendingPreview.type === 'user_input_required' || pendingPreview.type === 'user_input_request'
  const isKuncode = pendingPreview.type === 'kuncode_preview'
  const isPlan = pendingPreview.type === 'plan_preview'
  const isAutoContinue = pendingPreview.type === 'auto_continue'

  const handleConfirm = async () => {
    if (loading) return
    if (isUserInput && !input.trim()) return

    setLoading(true)
    try {
      if (isUserInput) {
        await Api.sendKuncodeInput(currentSession, pendingPreview.preview_id, input.trim())
      } else if (isKuncode) {
        await Api.confirmKuncode(currentSession, pendingPreview.preview_id, 'confirm', input.trim() || String(pendingPreview.prompt || ''))
      } else if (isPlan) {
        await Api.confirmPlanPreview(currentSession, pendingPreview.preview_id, 'confirm')
      } else if (isAutoContinue) {
        await Api.confirmAutoContinue(currentSession)
      }
      clearPendingPreview()
      setInput('')
    } catch (error) {
      console.error('Preview confirm failed:', error)
      clearPendingPreview()
      setInput('')
    } finally {
      setLoading(false)
    }
  }

  const handleCancel = async () => {
    if (loading) return
    setLoading(true)
    try {
      if (isKuncode || isUserInput) {
        await Api.confirmKuncode(currentSession, pendingPreview.preview_id, 'cancel').catch(() => undefined)
      } else if (isPlan) {
        await Api.cancelPlanPreview(currentSession, pendingPreview.preview_id).catch(() => undefined)
      } else if (isAutoContinue) {
        await Api.cancelAutoContinue(currentSession).catch(() => undefined)
      }
      clearPendingPreview()
      setInput('')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="mx-4 mb-3">
      <div className="overflow-hidden rounded-lg border border-accent/30 bg-bg-surface shadow-lg">
        <div className="flex items-center justify-between gap-3 border-b border-accent/20 bg-accent/10 px-4 py-2.5">
          <div className="flex min-w-0 items-center gap-2">
            <Clock size={14} className="shrink-0 text-accent" />
            <span className="truncate text-sm font-medium text-accent">{meta.title}</span>
          </div>
          <div className="flex shrink-0 items-center gap-2">
            {pendingPreview.remaining_seconds != null && (
              <span className="rounded border border-border bg-bg-base px-1.5 py-0.5 font-mono text-[10px] text-text-muted">
                {pendingPreview.remaining_seconds}s
              </span>
            )}
            <button
              type="button"
              onClick={() => void handleCancel()}
              className="rounded-md p-1 text-text-muted transition-colors hover:bg-error/10 hover:text-error"
              title="取消"
            >
              <X size={14} />
            </button>
          </div>
        </div>

        <div className="space-y-3 px-4 py-3">
          {meta.message && <p className="text-sm leading-relaxed text-text-secondary">{meta.message}</p>}

          {meta.showInput && (
            meta.multiline ? (
              <textarea
                value={input}
                onChange={(event) => setInput(event.target.value)}
                className="min-h-28 w-full resize-y rounded-lg border border-border bg-bg-base px-3 py-2 font-mono text-xs leading-relaxed text-text-primary outline-none transition-colors focus:border-accent"
                placeholder="编辑 KunCode 任务描述..."
                autoFocus
              />
            ) : (
              <input
                type="text"
                value={input}
                onChange={(event) => setInput(event.target.value)}
                onKeyDown={(event) => {
                  if (event.key === 'Enter') void handleConfirm()
                }}
                className="w-full rounded-lg border border-border bg-bg-base px-3 py-2 text-sm text-text-primary outline-none transition-colors placeholder:text-text-muted focus:border-accent"
                placeholder="输入回复..."
                autoFocus
              />
            )
          )}

          <div className="flex justify-end gap-2">
            <button
              type="button"
              onClick={() => void handleCancel()}
              disabled={loading}
              className="rounded-lg border border-border bg-bg-elevated px-3 py-2 text-sm text-text-secondary transition-colors hover:text-text-primary disabled:cursor-not-allowed disabled:opacity-50"
            >
              取消
            </button>
            <button
              type="button"
              onClick={() => void handleConfirm()}
              disabled={loading || (isUserInput && !input.trim())}
              className="inline-flex items-center gap-1.5 rounded-lg bg-accent px-3 py-2 text-sm font-medium text-bg-base transition-colors hover:bg-accent-hover disabled:cursor-not-allowed disabled:opacity-50"
            >
              {isUserInput ? <Send size={14} /> : <Check size={14} />}
              {loading ? '处理中...' : meta.confirmLabel}
            </button>
          </div>
        </div>
      </div>
    </div>
  )
}
