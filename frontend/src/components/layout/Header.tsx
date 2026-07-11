import { useState, useRef, useEffect } from 'react'
import { ChevronDown, Shield, LogOut } from 'lucide-react'
import { useAuthStore } from '../../stores/auth'
import { useUiStore } from '../../stores/ui'

export function Header() {
  const { user, logout } = useAuthStore()
  const { page, setPage } = useUiStore()
  const [open, setOpen] = useState(false)
  const ref = useRef<HTMLDivElement>(null)

  useEffect(() => {
    const handleClick = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false)
    }
    document.addEventListener('mousedown', handleClick)
    return () => document.removeEventListener('mousedown', handleClick)
  }, [])

  return (
    <header className="flex items-center justify-between px-5 h-13 bg-bg-surface border-b border-border shrink-0">
      <div className="flex items-center gap-3">
        <div className="text-base font-bold tracking-tight text-text-primary">
          <span className="text-accent">Data</span>Agent
        </div>
        {page === 'admin' && (
          <button
            onClick={() => setPage('app')}
            className="text-xs text-text-muted hover:text-accent transition-colors cursor-pointer"
          >
            ← 返回应用
          </button>
        )}
      </div>

      <div className="relative" ref={ref}>
        <button
          onClick={() => setOpen(!open)}
          className="flex items-center gap-2 px-3 py-1.5 rounded-lg text-sm text-text-secondary hover:text-text-primary hover:bg-bg-hover transition-colors cursor-pointer"
        >
          <span className="w-6 h-6 rounded-full bg-accent/20 text-accent flex items-center justify-center text-xs font-semibold">
            {user?.username?.[0]?.toUpperCase()}
          </span>
          <span>{user?.username}</span>
          <ChevronDown size={14} className={`transition-transform ${open ? 'rotate-180' : ''}`} />
        </button>

        {open && (
          <div className="absolute right-0 top-full mt-1 w-44 bg-bg-surface border border-border rounded-lg shadow-xl overflow-hidden z-50">
            {user?.is_admin && (
              <button
                onClick={() => { setPage('admin'); setOpen(false) }}
                className="w-full flex items-center gap-2 px-3 py-2.5 text-sm text-text-secondary hover:text-text-primary hover:bg-bg-hover transition-colors cursor-pointer"
              >
                <Shield size={14} />
                管理后台
              </button>
            )}
            <button
              onClick={() => { logout(); setOpen(false) }}
              className="w-full flex items-center gap-2 px-3 py-2.5 text-sm text-text-secondary hover:text-error hover:bg-error/10 transition-colors cursor-pointer"
            >
              <LogOut size={14} />
              退出登录
            </button>
          </div>
        )}
      </div>
    </header>
  )
}
