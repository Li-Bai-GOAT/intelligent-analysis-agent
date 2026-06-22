import { Plus, PanelLeftClose, PanelLeftOpen, Trash2 } from 'lucide-react'
import { useSessionStore } from '../../stores/session'
import { useUiStore } from '../../stores/ui'

export function Sidebar() {
  const { sessions, currentSession, selectSession, createSession, deleteSession } = useSessionStore()
  const { sidebarCollapsed, toggleSidebar } = useUiStore()

  const formatName = (s: { name?: string; created_at: string }) => {
    if (s.name) return s.name.length > 28 ? s.name.slice(0, 28) + '…' : s.name
    const d = new Date(s.created_at)
    return `对话 ${d.toLocaleDateString()} ${d.toLocaleTimeString().slice(0, 5)}`
  }

  return (
    <aside
      className={`flex flex-col bg-bg-surface border-r border-border shrink-0 transition-all duration-200
        ${sidebarCollapsed ? 'w-11' : 'w-60'}`}
    >
      <div className="flex items-center justify-between px-2.5 h-11 border-b border-border">
        {!sidebarCollapsed && <span className="text-xs font-medium text-text-muted">历史对话</span>}
        <div className="flex items-center gap-1">
          {!sidebarCollapsed && (
            <button
              onClick={createSession}
              className="p-1 rounded-md text-text-muted hover:text-accent hover:bg-bg-hover transition-colors cursor-pointer"
              title="新建对话"
            >
              <Plus size={16} />
            </button>
          )}
          <button
            onClick={toggleSidebar}
            className="p-1 rounded-md text-text-muted hover:text-text-primary hover:bg-bg-hover transition-colors cursor-pointer"
            title={sidebarCollapsed ? '展开' : '收缩'}
          >
            {sidebarCollapsed ? <PanelLeftOpen size={16} /> : <PanelLeftClose size={16} />}
          </button>
        </div>
      </div>

      {!sidebarCollapsed && (
        <div className="flex-1 overflow-y-auto p-1.5">
          {sessions.length === 0 ? (
            <div className="text-xs text-text-muted text-center py-8">暂无对话</div>
          ) : (
            sessions.map((s) => (
              <div
                key={s.session_id}
                onClick={() => selectSession(s.session_id)}
                className={`group flex items-center justify-between px-2.5 py-2 rounded-md cursor-pointer transition-colors text-sm
                  ${s.session_id === currentSession
                    ? 'bg-accent/15 text-accent'
                    : 'text-text-secondary hover:bg-bg-hover hover:text-text-primary'
                  }`}
              >
                <span className="truncate flex-1 min-w-0">{formatName(s)}</span>
                <button
                  onClick={(e) => {
                    e.stopPropagation()
                    if (confirm('确定删除此对话？')) deleteSession(s.session_id)
                  }}
                  className="opacity-0 group-hover:opacity-60 hover:!opacity-100 p-0.5 rounded text-text-muted hover:text-error transition-all cursor-pointer"
                >
                  <Trash2 size={13} />
                </button>
              </div>
            ))
          )}
        </div>
      )}
    </aside>
  )
}
