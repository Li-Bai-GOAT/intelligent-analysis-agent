import { useState } from 'react'
import { useAuthStore } from '../../stores/auth'
import { useUiStore } from '../../stores/ui'
import { Button } from '../ui/Button'
import { Input } from '../ui/Input'

export function AuthPage() {
  const [tab, setTab] = useState<'login' | 'register'>('login')
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [confirm, setConfirm] = useState('')
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)
  const { login, register } = useAuthStore()
  const { setPage } = useUiStore()

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    setError('')
    setLoading(true)
    try {
      if (tab === 'register') {
        if (password !== confirm) { setError('密码不一致'); return }
        await register(username, password)
      } else {
        await login(username, password)
      }
      setPage('app')
    } catch (err) {
      setError(err instanceof Error ? err.message : '请求失败')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="h-screen flex items-center justify-center bg-bg-base">
      <div className="w-full max-w-sm px-6">
        <div className="text-center mb-8">
          <h1 className="text-2xl font-bold tracking-tight">
            <span className="text-accent">Data</span>
            <span className="text-text-primary">Agent</span>
          </h1>
          <p className="text-xs text-text-muted mt-2">智能数据分析平台</p>
        </div>

        <div className="flex gap-1 bg-bg-surface rounded-lg p-1 mb-6">
          {(['login', 'register'] as const).map((t) => (
            <button
              key={t}
              onClick={() => { setTab(t); setError('') }}
              className={`flex-1 py-2 rounded-md text-sm font-medium transition-all cursor-pointer
                ${tab === t ? 'bg-bg-elevated text-text-primary' : 'text-text-muted hover:text-text-secondary'}`}
            >
              {t === 'login' ? '登录' : '注册'}
            </button>
          ))}
        </div>

        <form onSubmit={handleSubmit} className="space-y-4">
          <Input
            placeholder="用户名"
            value={username}
            onChange={(e) => setUsername(e.target.value)}
            required
          />
          <Input
            type="password"
            placeholder="密码"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            required
          />
          {tab === 'register' && (
            <Input
              type="password"
              placeholder="确认密码"
              value={confirm}
              onChange={(e) => setConfirm(e.target.value)}
              required
            />
          )}
          {error && <p className="text-xs text-error">{error}</p>}
          <Button type="submit" className="w-full" disabled={loading}>
            {loading ? '处理中...' : tab === 'login' ? '登录' : '注册'}
          </Button>
        </form>
      </div>
    </div>
  )
}
