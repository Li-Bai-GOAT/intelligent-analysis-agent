import type { ReactNode } from 'react'
import { AlertCircle, CheckCircle2, Inbox, LoaderCircle, Trash2 } from 'lucide-react'
import { Button } from '../../components/ui/Button'
import { Modal } from '../../components/ui/Modal'

export function PageHeader({
  title,
  description,
  actions,
}: {
  title: string
  description: string
  actions?: ReactNode
}) {
  return (
    <div className="flex flex-col gap-3 border-b border-border pb-5 sm:flex-row sm:items-end sm:justify-between">
      <div className="min-w-0">
        <h1 className="text-xl font-semibold text-text-primary">{title}</h1>
        <p className="mt-1 text-sm leading-6 text-text-secondary">{description}</p>
      </div>
      {actions && <div className="flex shrink-0 items-center gap-2">{actions}</div>}
    </div>
  )
}

export function Notice({ type, children }: { type: 'success' | 'error'; children: ReactNode }) {
  const Icon = type === 'success' ? CheckCircle2 : AlertCircle
  return (
    <div
      className={`flex items-start gap-2 border px-3 py-2.5 text-sm ${
        type === 'success'
          ? 'border-success/30 bg-success/10 text-success'
          : 'border-error/30 bg-error/10 text-error'
      }`}
      role={type === 'error' ? 'alert' : 'status'}
    >
      <Icon size={16} className="mt-0.5 shrink-0" />
      <span>{children}</span>
    </div>
  )
}

export function LoadingState({ label = '正在加载' }: { label?: string }) {
  return (
    <div className="flex min-h-48 items-center justify-center gap-2 text-sm text-text-secondary">
      <LoaderCircle size={18} className="animate-spin text-accent" />
      {label}
    </div>
  )
}

export function EmptyState({ title, description, action }: { title: string; description: string; action?: ReactNode }) {
  return (
    <div className="flex min-h-52 flex-col items-center justify-center border border-dashed border-border px-6 text-center">
      <Inbox size={24} className="mb-3 text-text-muted" />
      <p className="text-sm font-medium text-text-primary">{title}</p>
      <p className="mt-1 max-w-md text-xs leading-5 text-text-secondary">{description}</p>
      {action && <div className="mt-4">{action}</div>}
    </div>
  )
}

export function StatusBadge({ enabled, on = '已启用', off = '已停用' }: { enabled: boolean; on?: string; off?: string }) {
  return (
    <span
      className={`inline-flex items-center gap-1.5 whitespace-nowrap text-xs ${
        enabled ? 'text-success' : 'text-text-muted'
      }`}
    >
      <span className={`h-1.5 w-1.5 rounded-full ${enabled ? 'bg-success' : 'bg-text-muted'}`} />
      {enabled ? on : off}
    </span>
  )
}

export function ConfirmDialog({
  open,
  title,
  message,
  busy,
  onClose,
  onConfirm,
}: {
  open: boolean
  title: string
  message: string
  busy?: boolean
  onClose: () => void
  onConfirm: () => void
}) {
  return (
    <Modal
      open={open}
      onClose={() => {
        if (!busy) onClose()
      }}
      title={title}
      size="sm"
      footer={
        <>
          <Button variant="ghost" onClick={onClose} disabled={busy}>取消</Button>
          <Button variant="danger" onClick={onConfirm} disabled={busy}>
            {busy ? <LoaderCircle size={15} className="animate-spin" /> : <Trash2 size={15} />}
            确认删除
          </Button>
        </>
      }
    >
      <p className="text-sm leading-6 text-text-secondary">{message}</p>
    </Modal>
  )
}

export function Field({ label, hint, children }: { label: string; hint?: string; children: ReactNode }) {
  return (
    <label className="flex flex-col gap-1.5">
      <span className="text-xs font-medium text-text-secondary">{label}</span>
      {children}
      {hint && <span className="text-xs leading-5 text-text-muted">{hint}</span>}
    </label>
  )
}
