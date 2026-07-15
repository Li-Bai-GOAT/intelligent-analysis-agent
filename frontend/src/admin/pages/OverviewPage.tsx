import { useCallback, useEffect, useState } from 'react'
import { Boxes, Database, PlugZap, RefreshCw, Server } from 'lucide-react'
import { AdminApi } from '../../api/admin'
import { Button } from '../../components/ui/Button'
import type { ReadyStatus } from '../types'
import { LoadingState, Notice, PageHeader } from '../components/AdminUi'
import { formatDate } from '../utils'

interface OverviewData {
  ready: ReadyStatus
  knowledge: number
  skills: number
  enabledSkills: number
  mcps: number
  enabledMcps: number
  promptUpdatedAt: string | null
}

const statusLabel = {
  ok: '正常',
  unavailable: '不可用',
  degraded: '降级',
  disabled: '未启用',
}

export function OverviewPage() {
  const [data, setData] = useState<OverviewData | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  const load = useCallback(async () => {
    setLoading(true)
    setError('')
    const results = await Promise.allSettled([
      AdminApi.getReadyStatus(),
      AdminApi.listKnowledge(undefined, 1, 0),
      AdminApi.getSkills(),
      AdminApi.getMcps(),
      AdminApi.getSystemPrompt(),
    ])

    const ready = results[0].status === 'fulfilled'
      ? results[0].value
      : { status: 'unavailable' as const, dependencies: {} }
    const knowledge = results[1].status === 'fulfilled' ? results[1].value.total : 0
    const skills = results[2].status === 'fulfilled' ? results[2].value : []
    const mcps = results[3].status === 'fulfilled' ? results[3].value : []
    const prompt = results[4].status === 'fulfilled' ? results[4].value : null
    const failed = results.filter((result) => result.status === 'rejected').length

    setData({
      ready,
      knowledge,
      skills: skills.length,
      enabledSkills: skills.filter((item) => item.enabled).length,
      mcps: mcps.length,
      enabledMcps: mcps.filter((item) => item.enabled).length,
      promptUpdatedAt: prompt?.updated_at ?? null,
    })
    if (failed) setError(`${failed} 项数据暂时无法读取，其余可用信息已显示。`)
    setLoading(false)
  }, [])

  useEffect(() => {
    const timer = window.setTimeout(() => void load(), 0)
    return () => window.clearTimeout(timer)
  }, [load])

  const metrics = data ? [
    { label: '知识条目', value: String(data.knowledge), detail: '当前总量', icon: Database },
    { label: 'Skills', value: String(data.skills), detail: `${data.enabledSkills} 个启用`, icon: Boxes },
    { label: 'MCP 服务', value: String(data.mcps), detail: `${data.enabledMcps} 个启用`, icon: PlugZap },
  ] : []

  return (
    <div className="space-y-6">
      <PageHeader
        title="运行总览"
        description="检查核心依赖状态与当前管理配置，数据直接来自运行中的后端服务。"
        actions={
          <Button variant="secondary" size="sm" onClick={load} disabled={loading}>
            <RefreshCw size={15} className={loading ? 'animate-spin' : ''} />
            重新检测
          </Button>
        }
      />

      {error && <Notice type="error">{error}</Notice>}
      {loading && !data ? <LoadingState label="正在汇总运行状态" /> : data && (
        <>
          <section>
            <div className="mb-3 flex items-center gap-2">
              <Server size={16} className="text-accent" />
              <h2 className="text-sm font-semibold text-text-primary">核心依赖</h2>
              <span className={`ml-auto text-xs ${data.ready.status === 'ok' ? 'text-success' : 'text-warning'}`}>
                {data.ready.status === 'ok' ? '服务已就绪' : '服务未完全就绪'}
              </span>
            </div>
            <div className="divide-y divide-border border border-border bg-bg-surface">
              {Object.keys(data.ready.dependencies).length === 0 ? (
                <p className="px-4 py-6 text-sm text-text-secondary">未获取到依赖状态，请确认后端服务可访问。</p>
              ) : Object.entries(data.ready.dependencies).map(([name, status]) => (
                <div key={name} className="flex items-center justify-between px-4 py-3">
                  <span className="font-mono text-sm text-text-primary">{name}</span>
                  <span className={`flex items-center gap-2 text-xs ${
                    status === 'ok' ? 'text-success' : status === 'disabled' ? 'text-text-muted' : 'text-warning'
                  }`}>
                    <span className={`h-1.5 w-1.5 rounded-full ${
                      status === 'ok' ? 'bg-success' : status === 'disabled' ? 'bg-text-muted' : 'bg-warning'
                    }`} />
                    {statusLabel[status]}
                  </span>
                </div>
              ))}
            </div>
          </section>

          <section>
            <h2 className="mb-3 text-sm font-semibold text-text-primary">配置摘要</h2>
            <div className="grid grid-cols-1 gap-px overflow-hidden border border-border bg-border sm:grid-cols-2 xl:grid-cols-4">
              {metrics.map(({ label, value, detail, icon: Icon }) => (
                <div key={label} className="bg-bg-surface px-4 py-4">
                  <div className="flex items-center justify-between">
                    <span className="text-xs text-text-secondary">{label}</span>
                    <Icon size={16} className="text-text-muted" />
                  </div>
                  <p className="mt-3 text-2xl font-semibold text-text-primary">{value}</p>
                  <p className="mt-1 text-xs text-text-muted">{detail}</p>
                </div>
              ))}
            </div>
          </section>

          <section className="border-t border-border pt-4">
            <p className="text-xs text-text-muted">系统提示词最后更新：{formatDate(data.promptUpdatedAt)}</p>
          </section>
        </>
      )}
    </div>
  )
}
