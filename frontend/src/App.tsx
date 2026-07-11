import { useEffect } from 'react'
import { useAuthStore } from './stores/auth'
import { useUiStore } from './stores/ui'
import { useSessionStore } from './stores/session'
import { AuthPage } from './components/auth/AuthPage'
import { Header } from './components/layout/Header'
import { Sidebar } from './components/layout/Sidebar'
import { ChatArea } from './components/chat/ChatArea'
import { RightPanel } from './components/layout/RightPanel'

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
      <div className="h-screen flex flex-col bg-bg-base">
        <Header />
        <div className="flex-1 flex items-center justify-center text-text-muted">
          <div className="text-center">
            <p className="text-sm mb-2">管理后台</p>
            <p className="text-xs">开发中...</p>
          </div>
        </div>
      </div>
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
