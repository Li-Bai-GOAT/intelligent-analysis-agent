import { useState, useEffect, useCallback } from 'react'
import { Api } from '../../api/client'
import { useSessionStore } from '../../stores/session'
import { CheckCircle2, Circle, Clock, AlertCircle, Plus, Trash2 } from 'lucide-react'

interface Subtask {
  title: string
  description: string
  status: 'pending' | 'in_progress' | 'completed' | 'failed'
}

interface PlanData {
  goal: string
  subtasks: Subtask[]
}

const statusIcons = {
  pending: <Circle size={14} className="text-text-muted" />,
  in_progress: <Clock size={14} className="text-warning" />,
  completed: <CheckCircle2 size={14} className="text-success" />,
  failed: <AlertCircle size={14} className="text-error" />,
}

export function PlanPanel() {
  const currentSession = useSessionStore((s) => s.currentSession)
  const [plan, setPlan] = useState<PlanData | null>(null)
  const [editing, setEditing] = useState(false)

  const loadPlan = useCallback(async () => {
    if (!currentSession) return
    try {
      const data = await Api.getPlan(currentSession) as unknown as PlanData
      if (data && data.goal) setPlan(data)
      else setPlan(null)
    } catch {
      setPlan(null)
    }
  }, [currentSession])

  useEffect(() => { loadPlan() }, [loadPlan])

  if (!plan) {
    return (
      <div className="flex items-center justify-center h-full text-text-muted text-sm">
        暂无计划
      </div>
    )
  }

  return (
    <div className="p-3 space-y-3">
      <div className="flex items-center justify-between">
        <h3 className="text-xs font-semibold text-text-muted uppercase tracking-wider">分析计划</h3>
        <button
          onClick={() => setEditing(!editing)}
          className="text-xs text-accent hover:text-accent-hover transition-colors cursor-pointer"
        >
          {editing ? '完成' : '编辑'}
        </button>
      </div>

      <div className="text-sm text-text-primary bg-bg-elevated rounded-lg p-3 border border-border">
        {plan.goal}
      </div>

      <div className="space-y-1.5">
        {plan.subtasks.map((task, i) => (
          <div key={i} className="flex items-start gap-2 px-2.5 py-2 rounded-md bg-bg-elevated/50 border border-border/50 group">
            <span className="mt-0.5 shrink-0">{statusIcons[task.status]}</span>
            <div className="flex-1 min-w-0">
              <div className="text-xs font-medium text-text-primary">{task.title}</div>
              {task.description && <div className="text-[11px] text-text-muted mt-0.5">{task.description}</div>}
            </div>
            {editing && (
              <button className="opacity-0 group-hover:opacity-100 p-0.5 text-text-muted hover:text-error transition-all cursor-pointer">
                <Trash2 size={12} />
              </button>
            )}
          </div>
        ))}
      </div>

      {editing && (
        <button className="flex items-center gap-1.5 text-xs text-accent hover:text-accent-hover transition-colors cursor-pointer">
          <Plus size={12} />
          添加子任务
        </button>
      )}
    </div>
  )
}
