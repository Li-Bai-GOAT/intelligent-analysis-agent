import { lazy, Suspense, useEffect } from 'react'
import { useAuthStore } from './stores/auth'
import { useUiStore } from './stores/ui'
import { useSessionStore } from './stores/session'
import { AuthPage } from './components/auth/AuthPage'
import { Header } from './components/layout/Header'
import { Sidebar } from './components/layout/Sidebar'
import { ChatArea } from './components/chat/ChatArea'
import { RightPanel } from './components/layout/RightPanel'

const AdminApp = lazy(() => import('./admin/AdminApp').then((m) => ({ default: m.AdminApp })))

export default function App() {
  const isAuthenticated = useAuthStore((s) => s.isAuthenticated)
  const page = useUiStore((s) => s.page)
  const loadSessions = useSessionStore((s) => s.loadSessions)

  useEffect(() => {
    if (isAuthenticated) {
      loadSessions()
    }
  }, [isAuthenticated, loadSessions])

  if (!isAuthenticated || page === 'auth') {
    return <AuthPage />
  }

  if (page === 'admin') {
    return (
      <Suspense fallback={<div className="flex h-screen items-center justify-center bg-bg-base text-sm text-text-muted">加载管理后台...</div>}>
        <AdminApp />
      </Suspense>
    )
  }

  return (
    <div className="h-screen flex flex-col bg-bg-base">
      <Header />
      <div className="flex flex-1 overflow-hidden">
        <Sidebar />
        <ChatArea />
        <RightPanel />
      </div>
    </div>
  )
}
