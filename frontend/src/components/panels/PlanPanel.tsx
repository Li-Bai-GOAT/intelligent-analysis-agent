import { useMemo, useState } from 'react'
import type { ReactNode } from 'react'
import { AlertCircle, CheckCircle2, Circle, Clock, Plus, RefreshCw, Trash2 } from 'lucide-react'
import { Api } from '../../api/client'
import { useSessionStore } from '../../stores/session'
import type { PlanData, PlanSubtaskData } from '../../types'

type ApiSubtaskState = 'todo' | 'in_progress' | 'done' | 'failed' | 'abandoned'
type ViewSubtaskStatus = 'pending' | 'in_progress' | 'completed' | 'failed'

interface ViewSubtask {
  title: string
  description: string
  expectedOutcome: string
  status: ViewSubtaskStatus
  rawState: ApiSubtaskState | string
}

interface ViewPlanData {
  goal: string
  description: string
  expectedOutcome: string
  subtasks: ViewSubtask[]
}

const statusMeta: Record<ViewSubtaskStatus, { label: string; icon: ReactNode; className: string }> = {
  pending: {
    label: '待执行',
    icon: <Circle size={14} />,
    className: 'text-text-muted bg-bg-muted/40 border-border',
  },
  in_progress: {
    label: '执行中',
    icon: <Clock size={14} />,
    className: 'text-warning bg-warning/10 border-warning/25',
  },
  completed: {
    label: '已完成',
    icon: <CheckCircle2 size={14} />,
    className: 'text-success bg-success/10 border-success/25',
  },
  failed: {
    label: '失败',
    icon: <AlertCircle size={14} />,
    className: 'text-error bg-error/10 border-error/25',
  },
}

function normalizeStatus(state?: string): ViewSubtaskStatus {
  if (state === 'done' || state === 'completed') return 'completed'
  if (state === 'in_progress' || state === 'running') return 'in_progress'
  if (state === 'failed' || state === 'error' || state === 'abandoned') return 'failed'
  return 'pending'
}

function toViewPlan(data: PlanData | null | undefined): ViewPlanData | null {
  if (!data || !data.name) return null
  return {
    goal: data.name,
    description: data.description || '',
    expectedOutcome: data.expected_outcome || '',
    subtasks: (data.subtasks || []).map((task: PlanSubtaskData) => ({
      title: task.name || '未命名子任务',
      description: task.description || '',
      expectedOutcome: task.expected_outcome || '',
      status: normalizeStatus(task.state),
      rawState: task.state || 'todo',
    })),
  }
}

export function PlanPanel() {
  const currentSession = useSessionStore((s) => s.currentSession)
  const currentPlan = useSessionStore((s) => s.currentPlan)
  const loading = useSessionStore((s) => s.planLoading)
  const planError = useSessionStore((s) => s.planError)
  const loadPlan = useSessionStore((s) => s.loadPlan)
  const [editing, setEditing] = useState(false)
  const [newTaskTitle, setNewTaskTitle] = useState('')

  const plan = useMemo(() => toViewPlan(currentPlan), [currentPlan])

  const progress = useMemo(() => {
    if (!plan || plan.subtasks.length === 0) return 0
    const done = plan.subtasks.filter((task) => task.status === 'completed').length
    return Math.round((done / plan.subtasks.length) * 100)
  }, [plan])

  const handleDelete = async (index: number) => {
    if (!currentSession) return
    await Api.deleteSubtask(currentSession, index)
    await loadPlan(currentSession)
  }

  const handleAdd = async () => {
    if (!currentSession || !newTaskTitle.trim()) return
    await Api.addSubtask(currentSession, {
      name: newTaskTitle.trim(),
      state: 'todo',
    })
    setNewTaskTitle('')
    await loadPlan(currentSession)
  }

  if (!currentSession) {
    return <div className="flex h-full items-center justify-center text-sm text-text-muted">选择会话后查看计划</div>
  }

  if (!plan) {
    return (
      <div className="flex h-full flex-col items-center justify-center gap-3 text-sm text-text-muted">
        <div>{loading ? '正在加载计划...' : planError ? `计划加载失败：${planError}` : '暂无分析计划'}</div>
        <button
          type="button"
          onClick={() => void loadPlan(currentSession)}
          className="inline-flex items-center gap-1.5 rounded-md border border-border bg-bg-elevated px-3 py-1.5 text-xs text-text-secondary hover:text-accent"
        >
          <RefreshCw size={13} className={loading ? 'animate-spin' : ''} />
          刷新
        </button>
      </div>
    )
  }

  return (
    <div className="flex h-full flex-col">
      <div className="border-b border-border px-3 py-2">
        <div className="flex items-center justify-between gap-2">
          <h3 className="text-xs font-semibold uppercase tracking-wide text-text-muted">分析计划</h3>
          <div className="flex items-center gap-1.5">
            <button
              type="button"
              onClick={() => void loadPlan(currentSession)}
              className="rounded-md p-1 text-text-muted hover:bg-bg-hover hover:text-accent"
              title="刷新"
            >
              <RefreshCw size={14} className={loading ? 'animate-spin' : ''} />
            </button>
            <button
              type="button"
              onClick={() => setEditing((value) => !value)}
              className="rounded-md px-2 py-1 text-xs text-accent hover:bg-accent/10"
            >
              {editing ? '完成' : '编辑'}
            </button>
          </div>
        </div>
        <div className="mt-2 h-1.5 overflow-hidden rounded-full bg-bg-muted">
          <div className="h-full rounded-full bg-accent transition-all" style={{ width: `${progress}%` }} />
        </div>
        <div className="mt-1 text-[10px] text-text-muted">{progress}% 完成</div>
      </div>

      <div className="flex-1 overflow-y-auto p-3">
        <div className="rounded-lg border border-border bg-bg-elevated p-3">
          <div className="text-sm font-medium text-text-primary">{plan.goal}</div>
          {plan.description && <div className="mt-1 text-xs leading-relaxed text-text-secondary">{plan.description}</div>}
          {plan.expectedOutcome && <div className="mt-2 text-[11px] text-text-muted">预期结果：{plan.expectedOutcome}</div>}
        </div>

        <div className="mt-3 space-y-2">
          {plan.subtasks.map((task, index) => {
            const meta = statusMeta[task.status]
            return (
              <div key={`${task.title}-${index}`} className="group rounded-lg border border-border/70 bg-bg-elevated/50 p-2.5">
                <div className="flex items-start gap-2">
                  <span className={`mt-0.5 inline-flex h-6 w-6 shrink-0 items-center justify-center rounded-md border ${meta.className}`}>
                    {meta.icon}
                  </span>
                  <div className="min-w-0 flex-1">
                    <div className="flex items-center gap-2">
                      <div className="truncate text-xs font-medium text-text-primary">{task.title}</div>
                      <span className={`shrink-0 rounded border px-1.5 py-0.5 text-[10px] ${meta.className}`}>{meta.label}</span>
                    </div>
                    {task.description && <div className="mt-1 text-[11px] leading-relaxed text-text-muted">{task.description}</div>}
                    {task.expectedOutcome && <div className="mt-1 text-[10px] text-text-muted">产出：{task.expectedOutcome}</div>}
                  </div>
                  {editing && (
                    <button
                      type="button"
                      onClick={() => void handleDelete(index)}
                      className="rounded p-1 text-text-muted opacity-0 transition-all hover:bg-error/10 hover:text-error group-hover:opacity-100"
                      title="删除子任务"
                    >
                      <Trash2 size={13} />
                    </button>
                  )}
                </div>
              </div>
            )
          })}
        </div>

        {editing && (
          <div className="mt-3 flex gap-2">
            <input
              value={newTaskTitle}
              onChange={(event) => setNewTaskTitle(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === 'Enter') void handleAdd()
              }}
              placeholder="新增子任务"
              className="min-w-0 flex-1 rounded-lg border border-border bg-bg-base px-3 py-2 text-xs text-text-primary outline-none focus:border-accent"
            />
            <button
              type="button"
              onClick={() => void handleAdd()}
              disabled={!newTaskTitle.trim()}
              className="inline-flex items-center gap-1.5 rounded-lg bg-accent px-3 py-2 text-xs font-medium text-bg-base disabled:cursor-not-allowed disabled:opacity-50"
            >
              <Plus size={13} />
              添加
            </button>
          </div>
        )}
      </div>
    </div>
  )
}
