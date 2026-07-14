import { useCallback, useEffect, useMemo, useState } from 'react'
import { Pencil, Plus, Search, Trash2 } from 'lucide-react'
import { AdminApi } from '../../api/admin'
import { Button } from '../../components/ui/Button'
import { Input } from '../../components/ui/Input'
import { Modal } from '../../components/ui/Modal'
import { Switch } from '../../components/ui/Switch'
import type { McpConfig, McpCreateInput, McpType } from '../types'
import { ConfirmDialog, EmptyState, Field, LoadingState, Notice, PageHeader, StatusBadge } from '../components/AdminUi'
import { formatDate, inputClass, textareaClass } from '../utils'

function parseStringMap(value: string, label: string) {
  try {
    const parsed = JSON.parse(value) as unknown
    if (!parsed || Array.isArray(parsed) || typeof parsed !== 'object' || Object.values(parsed).some((entry) => typeof entry !== 'string')) throw new Error()
    return parsed as Record<string, string>
  } catch {
    throw new Error(`${label}必须是值为字符串的 JSON 对象。`)
  }
}

function McpForm({ item, busy, onCancel, onSave }: { item: McpConfig | null; busy: boolean; onCancel: () => void; onSave: (data: McpCreateInput) => void }) {
  const [name, setName] = useState(item?.name ?? '')
  const [type, setType] = useState<McpType>(item?.mcp_type ?? 'remote')
  const [url, setUrl] = useState(item?.url ?? '')
  const [command, setCommand] = useState((item?.command ?? []).join('\n'))
  const [headers, setHeaders] = useState(JSON.stringify(item?.headers ?? {}, null, 2))
  const [environment, setEnvironment] = useState(JSON.stringify(item?.environment ?? {}, null, 2))
  const [enabled, setEnabled] = useState(item?.enabled ?? true)
  const [error, setError] = useState('')

  const submit = () => {
    if (!name.trim()) { setError('MCP 名称不能为空。'); return }
    if (type === 'remote' && !url.trim()) { setError('Remote MCP 必须填写 URL。'); return }
    const commandParts = command.split('\n').map((part) => part.trim()).filter(Boolean)
    if (type === 'local' && commandParts.length === 0) { setError('Local MCP 必须填写启动命令。'); return }
    try {
      onSave({
        name: name.trim(),
        mcp_type: type,
        url: type === 'remote' ? url.trim() : null,
        command: type === 'local' ? commandParts : [],
        headers: type === 'remote' ? parseStringMap(headers, '请求头') : {},
        environment: type === 'local' ? parseStringMap(environment, '环境变量') : {},
        enabled,
      })
    } catch (parseError) {
      setError(parseError instanceof Error ? parseError.message : '配置格式无效')
    }
  }

  return (
    <>
      <div className="space-y-4">
        {error && <Notice type="error">{error}</Notice>}
        <Input label="MCP 名称" value={name} onChange={(event) => setName(event.target.value)} disabled={Boolean(item)} maxLength={64} autoFocus={!item} />
        <Field label="服务类型">
          <div className="grid grid-cols-2 border border-border bg-bg-base p-1">
            {(['remote', 'local'] as McpType[]).map((value) => <button key={value} type="button" onClick={() => setType(value)} className={`px-3 py-2 text-sm ${type === value ? 'bg-bg-elevated text-text-primary' : 'text-text-muted hover:text-text-secondary'}`}>{value === 'remote' ? 'Remote' : 'Local'}</button>)}
          </div>
        </Field>
        {type === 'remote' ? (
          <>
            <Input label="服务 URL" type="url" value={url} onChange={(event) => setUrl(event.target.value)} placeholder="https://example.com/mcp" />
            <Field label="请求头（JSON）" hint="敏感值会提交到后端，请勿在截图或日志中公开。"><textarea className={`${textareaClass} min-h-40 font-mono text-xs`} value={headers} onChange={(event) => setHeaders(event.target.value)} spellCheck={false} /></Field>
          </>
        ) : (
          <>
            <Field label="启动命令" hint="每行一个数组元素，第一行为可执行程序，其余行为参数。"><textarea className={`${textareaClass} min-h-32 font-mono text-xs`} value={command} onChange={(event) => setCommand(event.target.value)} spellCheck={false} placeholder={'npx\n-y\n@modelcontextprotocol/server-filesystem'} /></Field>
            <Field label="环境变量（JSON）"><textarea className={`${textareaClass} min-h-40 font-mono text-xs`} value={environment} onChange={(event) => setEnvironment(event.target.value)} spellCheck={false} /></Field>
          </>
        )}
        <Switch checked={enabled} onChange={setEnabled} label="启用 MCP" />
      </div>
      <div className="mt-5 flex justify-end gap-2 border-t border-border pt-4"><Button variant="ghost" onClick={onCancel} disabled={busy}>取消</Button><Button onClick={submit} disabled={busy}>{busy ? '正在保存' : '保存 MCP'}</Button></div>
    </>
  )
}

export function McpsPage() {
  const [items, setItems] = useState<McpConfig[]>([])
  const [query, setQuery] = useState('')
  const [loading, setLoading] = useState(true)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [success, setSuccess] = useState('')
  const [editor, setEditor] = useState<McpConfig | 'new' | null>(null)
  const [deleting, setDeleting] = useState<McpConfig | null>(null)

  const load = useCallback(async () => {
    setLoading(true); setError('')
    try { setItems(await AdminApi.getMcps()) } catch (loadError) { setError(loadError instanceof Error ? loadError.message : 'MCP 列表加载失败') } finally { setLoading(false) }
  }, [])
  useEffect(() => {
    const timer = window.setTimeout(() => void load(), 0)
    return () => window.clearTimeout(timer)
  }, [load])

  const visibleItems = useMemo(() => {
    const keyword = query.trim().toLowerCase()
    return keyword ? items.filter((item) => `${item.name}\n${item.url ?? ''}\n${item.command.join(' ')}`.toLowerCase().includes(keyword)) : items
  }, [items, query])

  const save = async (data: McpCreateInput) => {
    setBusy(true); setError('')
    try {
      if (editor === 'new') await AdminApi.createMcp(data)
      else if (editor) {
        await AdminApi.updateMcp(editor.id, {
          mcp_type: data.mcp_type,
          url: data.url,
          command: data.command,
          headers: data.headers,
          environment: data.environment,
          enabled: data.enabled,
        })
      }
      setSuccess(`MCP“${data.name}”已保存。`); setEditor(null); await load()
    } catch (saveError) { setError(saveError instanceof Error ? saveError.message : 'MCP 保存失败') } finally { setBusy(false) }
  }

  const remove = async () => {
    if (!deleting) return
    setBusy(true)
    try { await AdminApi.deleteMcp(deleting.id); setSuccess(`MCP“${deleting.name}”已删除。`); setDeleting(null); await load() } catch (deleteError) { setError(deleteError instanceof Error ? deleteError.message : 'MCP 删除失败') } finally { setBusy(false) }
  }

  return (
    <div className="space-y-5">
      <PageHeader title="MCP 管理" description="维护 KunCode 可调用的本地与远程 MCP 工具服务。" actions={<Button size="sm" onClick={() => { setEditor('new'); setSuccess('') }}><Plus size={15} />新建 MCP</Button>} />
      {error && <Notice type="error">{error}</Notice>}{success && <Notice type="success">{success}</Notice>}
      <div className="relative max-w-xl"><Search size={15} className="absolute left-3 top-1/2 -translate-y-1/2 text-text-muted" /><input className={`${inputClass} pl-9`} value={query} onChange={(event) => setQuery(event.target.value)} placeholder="搜索名称、URL 或命令" /></div>
      <Notice type="error">当前后端尚未提供 MCP 连接测试和密钥脱敏接口；保存前请确认配置来源可信。</Notice>

      {loading ? <LoadingState label="正在加载 MCP 配置" /> : visibleItems.length === 0 ? <EmptyState title={items.length ? '没有匹配的 MCP' : '尚未配置 MCP'} description={items.length ? '调整搜索内容后重试。' : '创建 MCP 后可将外部工具能力提供给 KunCode。'} action={!items.length ? <Button size="sm" onClick={() => setEditor('new')}><Plus size={15} />新建 MCP</Button> : undefined} /> : (
        <div className="overflow-x-auto border border-border"><table className="w-full min-w-[800px] border-collapse text-left"><thead className="bg-bg-elevated text-xs text-text-secondary"><tr><th className="px-4 py-3 font-medium">MCP</th><th className="px-4 py-3 font-medium">类型</th><th className="px-4 py-3 font-medium">连接目标</th><th className="px-4 py-3 font-medium">状态</th><th className="px-4 py-3 font-medium">更新时间</th><th className="w-24 px-4 py-3 text-right font-medium">操作</th></tr></thead><tbody className="divide-y divide-border bg-bg-surface">
          {visibleItems.map((item) => <tr key={item.id} className="hover:bg-bg-elevated/60"><td className="px-4 py-3 text-sm font-medium text-text-primary">{item.name}</td><td className="px-4 py-3 font-mono text-xs text-accent">{item.mcp_type}</td><td className="max-w-md px-4 py-3"><p className="truncate font-mono text-xs text-text-secondary">{item.mcp_type === 'remote' ? item.url : item.command.join(' ')}</p></td><td className="px-4 py-3"><StatusBadge enabled={item.enabled} /></td><td className="whitespace-nowrap px-4 py-3 text-xs text-text-muted">{formatDate(item.updated_at)}</td><td className="px-4 py-3"><div className="flex justify-end gap-1"><button title="编辑" onClick={() => { setEditor(item); setSuccess('') }} className="p-2 text-text-muted hover:bg-bg-hover hover:text-accent"><Pencil size={15} /></button><button title="删除" onClick={() => setDeleting(item)} className="p-2 text-text-muted hover:bg-error/10 hover:text-error"><Trash2 size={15} /></button></div></td></tr>)}
        </tbody></table></div>
      )}
      {editor && <Modal open title={editor === 'new' ? '新建 MCP' : `编辑 ${editor.name}`} size="lg" onClose={() => !busy && setEditor(null)}><McpForm key={editor === 'new' ? 'new' : editor.id} item={editor === 'new' ? null : editor} busy={busy} onCancel={() => setEditor(null)} onSave={save} /></Modal>}
      <ConfirmDialog open={Boolean(deleting)} title="删除 MCP" message={`确定删除 MCP“${deleting?.name ?? ''}”吗？后续沙箱将无法注入该服务。`} busy={busy} onClose={() => setDeleting(null)} onConfirm={remove} />
    </div>
  )
}
