import { useCallback, useEffect, useState } from 'react'
import { RefreshCw } from 'lucide-react'
import { AdminApi } from '../../api/admin'
import { Button } from '../../components/ui/Button'
import type { ModelAuditItem } from '../types'
import { EmptyState, LoadingState, Notice, PageHeader } from '../components/AdminUi'
import { adminTableCellClass, adminTableClass, adminTableHeaderCellClass, formatDate, inputClass } from '../utils'

type Filters = {
  start_time: string
  end_time: string
  provider: string
  model: string
  source: string
  result: string
}

const initialFilters: Filters = { start_time: '', end_time: '', provider: '', model: '', source: '', result: '' }

function dateValue(value: string) {
  return value ? new Date(value).toISOString() : ''
}

function resultLabel(value?: string) {
  if (value === 'success') return '成功'
  if (value === 'failed') return '失败'
  if (value === 'partial') return '部分失败'
  if (value === 'cancelled') return '已取消'
  return value || '进行中'
}

function resultClass(value?: string) {
  if (value === 'success') return 'text-success'
  if (value === 'failed' || value === 'partial') return 'text-error'
  if (value === 'cancelled') return 'text-warning'
  return 'text-text-muted'
}

export function ModelAuditsPage() {
  const [filters, setFilters] = useState<Filters>(initialFilters)
  const [items, setItems] = useState<ModelAuditItem[]>([])
  const [total, setTotal] = useState(0)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  const load = useCallback(async (nextFilters: Filters) => {
    setLoading(true)
    setError('')
    try {
      const requestFilters = {
        ...nextFilters,
        start_time: dateValue(nextFilters.start_time),
        end_time: dateValue(nextFilters.end_time),
      }
      const result = await AdminApi.getModelAudits(requestFilters)
      setItems(result.items)
      setTotal(result.total)
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : '模型审计记录读取失败')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    const timer = window.setTimeout(() => void load(initialFilters), 0)
    return () => window.clearTimeout(timer)
  }, [load])

  const setFilter = (key: keyof Filters, value: string) => {
    setFilters((current) => ({ ...current, [key]: value }))
  }

  return (
    <div className="space-y-6">
      <PageHeader
        title="模型审计"
        description="查看模型请求的链路、耗时、Token 和结果。页面不会展示 Prompt、密钥、Authorization 或响应正文。"
        actions={<Button variant="secondary" size="sm" onClick={() => void load(filters)} disabled={loading}><RefreshCw size={15} className={loading ? 'animate-spin' : ''} />刷新</Button>}
      />

      {error && <Notice type="error">{error}</Notice>}
      <section className="grid grid-cols-1 gap-3 border border-border bg-bg-surface p-4 sm:grid-cols-2 lg:grid-cols-3">
        <label className="flex flex-col gap-1.5"><span className="text-xs font-medium text-text-secondary">开始时间</span><input className={inputClass} type="datetime-local" value={filters.start_time} onChange={(event) => setFilter('start_time', event.target.value)} /></label>
        <label className="flex flex-col gap-1.5"><span className="text-xs font-medium text-text-secondary">结束时间</span><input className={inputClass} type="datetime-local" value={filters.end_time} onChange={(event) => setFilter('end_time', event.target.value)} /></label>
        <label className="flex flex-col gap-1.5"><span className="text-xs font-medium text-text-secondary">Provider</span><input className={inputClass} placeholder="deepseek" value={filters.provider} onChange={(event) => setFilter('provider', event.target.value)} /></label>
        <label className="flex flex-col gap-1.5"><span className="text-xs font-medium text-text-secondary">模型</span><input className={inputClass} placeholder="模型名称" value={filters.model} onChange={(event) => setFilter('model', event.target.value)} /></label>
        <label className="flex flex-col gap-1.5"><span className="text-xs font-medium text-text-secondary">来源</span><select className={inputClass} value={filters.source} onChange={(event) => setFilter('source', event.target.value)}><option value="">全部来源</option><option value="backend">backend</option><option value="sandbox">sandbox</option><option value="gateway">gateway</option></select></label>
        <label className="flex flex-col gap-1.5"><span className="text-xs font-medium text-text-secondary">结果</span><select className={inputClass} value={filters.result} onChange={(event) => setFilter('result', event.target.value)}><option value="">全部结果</option><option value="success">成功</option><option value="failed">失败</option><option value="partial">部分失败</option><option value="cancelled">已取消</option></select></label>
        <div className="flex items-end gap-2 sm:col-span-2 lg:col-span-3"><Button size="sm" onClick={() => void load(filters)}>应用筛选</Button><Button variant="ghost" size="sm" onClick={() => { setFilters(initialFilters); void load(initialFilters) }}>清空</Button><span className="ml-auto pb-2 text-xs text-text-muted">共 {total} 条记录</span></div>
      </section>

      {loading && !items.length ? <LoadingState label="正在读取模型审计记录" /> : items.length === 0 ? <EmptyState title="暂无模型审计记录" description="当前筛选条件下没有可展示的请求事件。" /> : (
        <div className="overflow-x-auto border border-border">
          <table className={adminTableClass + ' min-w-[1180px]'}>
            <thead className="bg-bg-elevated"><tr><th className={adminTableHeaderCellClass}>时间 / 结果</th><th className={adminTableHeaderCellClass}>请求链路</th><th className={adminTableHeaderCellClass}>Provider / 模型</th><th className={adminTableHeaderCellClass}>来源</th><th className={adminTableHeaderCellClass}>尝试</th><th className={adminTableHeaderCellClass}>延迟</th><th className={adminTableHeaderCellClass}>Token</th></tr></thead>
            <tbody className="divide-y divide-border bg-bg-surface">
              {items.map((item, index) => <tr key={item.request_id + '-' + item.event + '-' + index} className="hover:bg-bg-elevated/60">
                <td className={adminTableCellClass}><div className="whitespace-nowrap text-text-secondary">{formatDate(item.finished_at || item.started_at)}</div><div className={'mt-1 text-xs ' + resultClass(item.result)}>{resultLabel(item.result)} · {item.event}</div></td>
                <td className={adminTableCellClass + ' max-w-[300px]'}><div className="truncate font-mono text-xs text-text-primary" title={item.request_id}>{item.request_id}</div><div className="mt-1 truncate font-mono text-xs text-text-muted" title={item.trace_id}>{item.trace_id || '无 trace'}</div><div className="mt-1 truncate text-xs text-text-muted">任务 {item.parent_task_id || '-'} · 会话 {item.session_id || '-'}</div></td>
                <td className={adminTableCellClass}><div className="font-medium text-text-primary">{item.provider || '-'}</div><div className="mt-1 max-w-[220px] truncate font-mono text-xs text-text-secondary" title={item.actual_model || item.requested_model}>{item.actual_model || item.requested_model || '-'}</div></td>
                <td className={adminTableCellClass}><div className="text-text-secondary">{item.source || '-'}</div><div className="mt-1 text-xs text-text-muted">{item.entrypoint || '-'}</div></td>
                <td className={adminTableCellClass + ' text-text-secondary'}>{item.attempt ?? '-'}</td>
                <td className={adminTableCellClass + ' text-text-secondary'}>{item.latency_ms != null ? item.latency_ms + ' ms' : '-'}</td>
                <td className={adminTableCellClass + ' font-mono text-xs text-text-secondary'}>{item.total_tokens != null ? <><div>{item.total_tokens.toLocaleString()}</div><div className="mt-1 text-text-muted">入 {item.prompt_tokens ?? 0} / 出 {item.completion_tokens ?? 0}</div></> : '-'}</td>
              </tr>)}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}
