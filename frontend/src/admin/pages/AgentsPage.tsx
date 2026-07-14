import { useCallback, useEffect, useMemo, useState } from 'react'
import { EyeOff, Pencil, Plus, Search, Trash2 } from 'lucide-react'
import { AdminApi } from '../../api/admin'
import { Button } from '../../components/ui/Button'
import { Input } from '../../components/ui/Input'
import { Modal } from '../../components/ui/Modal'
import { Switch } from '../../components/ui/Switch'
import type { AgentConfig, AgentCreateInput, AgentMode } from '../types'
import {
  ConfirmDialog,
  EmptyState,
  Field,
  LoadingState,
  Notice,
  PageHeader,
  StatusBadge,
} from '../components/AdminUi'
import { formatDate, inputClass, textareaClass } from '../utils'

function parseObject(value: string, label: string) {
  try {
    const parsed = JSON.parse(value) as unknown
    if (!parsed || Array.isArray(parsed) || typeof parsed !== 'object') throw new Error()
    return parsed as Record<string, unknown>
  } catch {
    throw new Error(`${label}必须是合法的 JSON 对象。`)
  }
}

function AgentForm({
  item,
  busy,
  onCancel,
  onSave,
}: {
  item: AgentConfig | null
  busy: boolean
  onCancel: () => void
  onSave: (data: AgentCreateInput) => void
}) {
  const [name, setName] = useState(item?.name ?? '')
  const [description, setDescription] = useState(item?.description ?? '')
  const [mode, setMode] = useState<AgentMode>(item?.mode ?? 'all')
  const [temperature, setTemperature] = useState(item?.temperature?.toString() ?? '')
  const [maxSteps, setMaxSteps] = useState(item?.max_steps?.toString() ?? '')
  const [tools, setTools] = useState(JSON.stringify(item?.tools ?? {}, null, 2))
  const [permission, setPermission] = useState(JSON.stringify(item?.permission ?? {}, null, 2))
  const [content, setContent] = useState(item?.content ?? '')
  const [hidden, setHidden] = useState(item?.hidden ?? false)
  const [enabled, setEnabled] = useState(item?.enabled ?? true)
  const [error, setError] = useState('')

  const submit = () => {
    if (!name.trim() || !description.trim()) {
      setError('名称和描述不能为空。')
      return
    }
    const parsedTemperature = temperature === '' ? null : Number(temperature)
    const parsedMaxSteps = maxSteps === '' ? null : Number(maxSteps)
    if (parsedTemperature !== null && (!Number.isFinite(parsedTemperature) || parsedTemperature < 0 || parsedTemperature > 1)) {
      setError('温度必须在 0 到 1 之间。')
      return
    }
    if (parsedMaxSteps !== null && (!Number.isInteger(parsedMaxSteps) || parsedMaxSteps < 1)) {
      setError('最大步骤数必须是大于 0 的整数。')
      return
    }
    try {
      onSave({
        name: name.trim(),
        description: description.trim(),
        mode,
        tools: parseObject(tools, '工具配置'),
        permission: parseObject(permission, '权限配置'),
        temperature: parsedTemperature,
        max_steps: parsedMaxSteps,
        hidden,
        content,
        enabled,
      })
    } catch (parseError) {
      setError(parseError instanceof Error ? parseError.message : 'JSON 配置无效')
    }
  }

  return (
    <>
      <div className="space-y-4">
        {error && <Notice type="error">{error}</Notice>}
        <div className="grid gap-4 sm:grid-cols-2">
          <Input label="Agent 名称" value={name} onChange={(event) => setName(event.target.value)} disabled={Boolean(item)} maxLength={64} autoFocus={!item} />
          <Field label="运行模式">
            <select className={inputClass} value={mode} onChange={(event) => setMode(event.target.value as AgentMode)}>
              <option value="all">全部模式</option>
              <option value="primary">主 Agent</option>
              <option value="subagent">子 Agent</option>
            </select>
          </Field>
        </div>
        <Input label="描述" value={description} onChange={(event) => setDescription(event.target.value)} maxLength={1024} />
        <div className="grid gap-4 sm:grid-cols-2">
          <Input label="温度（可选）" type="number" min="0" max="1" step="0.1" value={temperature} onChange={(event) => setTemperature(event.target.value)} placeholder="使用运行时默认值" />
          <Input label="最大步骤数（可选）" type="number" min="1" step="1" value={maxSteps} onChange={(event) => setMaxSteps(event.target.value)} placeholder="使用运行时默认值" />
        </div>
        <div className="grid gap-4 lg:grid-cols-2">
          <Field label="工具配置（JSON 对象）"><textarea className={`${textareaClass} min-h-44 font-mono text-xs`} value={tools} onChange={(event) => setTools(event.target.value)} spellCheck={false} /></Field>
          <Field label="权限配置（JSON 对象）"><textarea className={`${textareaClass} min-h-44 font-mono text-xs`} value={permission} onChange={(event) => setPermission(event.target.value)} spellCheck={false} /></Field>
        </div>
        <Field label="Agent 指令内容" hint={`${content.length} 个字符`}><textarea className={`${textareaClass} min-h-56 font-mono text-xs`} value={content} onChange={(event) => setContent(event.target.value)} spellCheck={false} /></Field>
        <div className="flex flex-wrap gap-6 border-t border-border pt-4">
          <Switch checked={enabled} onChange={setEnabled} label="启用 Agent" />
          <Switch checked={hidden} onChange={setHidden} label="在选择列表中隐藏" />
        </div>
      </div>
      <div className="mt-5 flex justify-end gap-2 border-t border-border pt-4">
        <Button variant="ghost" onClick={onCancel} disabled={busy}>取消</Button>
        <Button onClick={submit} disabled={busy}>{busy ? '正在保存' : '保存 Agent'}</Button>
      </div>
    </>
  )
}

export function AgentsPage() {
  const [items, setItems] = useState<AgentConfig[]>([])
  const [query, setQuery] = useState('')
  const [loading, setLoading] = useState(true)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [success, setSuccess] = useState('')
  const [editor, setEditor] = useState<AgentConfig | 'new' | null>(null)
  const [deleting, setDeleting] = useState<AgentConfig | null>(null)

  const load = useCallback(async () => {
    setLoading(true)
    setError('')
    try {
      setItems(await AdminApi.getAgents())
    } catch (loadError) {
      setError(loadError instanceof Error ? loadError.message : 'Agent 列表加载失败')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    const timer = window.setTimeout(() => void load(), 0)
    return () => window.clearTimeout(timer)
  }, [load])

  const visibleItems = useMemo(() => {
    const keyword = query.trim().toLowerCase()
    if (!keyword) return items
    return items.filter((item) => `${item.name}\n${item.description}`.toLowerCase().includes(keyword))
  }, [items, query])

  const save = async (data: AgentCreateInput) => {
    setBusy(true)
    setError('')
    try {
      if (editor === 'new') await AdminApi.createAgent(data)
      else if (editor) {
        await AdminApi.updateAgent(editor.id, {
          description: data.description,
          mode: data.mode,
          tools: data.tools,
          permission: data.permission,
          temperature: data.temperature,
          max_steps: data.max_steps,
          hidden: data.hidden,
          content: data.content,
          enabled: data.enabled,
        })
      }
      setSuccess(`Agent“${data.name}”已保存。`)
      setEditor(null)
      await load()
    } catch (saveError) {
      setError(saveError instanceof Error ? saveError.message : 'Agent 保存失败')
    } finally {
      setBusy(false)
    }
  }

  const remove = async () => {
    if (!deleting) return
    setBusy(true)
    try {
      await AdminApi.deleteAgent(deleting.id)
      setSuccess(`Agent“${deleting.name}”已删除。`)
      setDeleting(null)
      await load()
    } catch (deleteError) {
      setError(deleteError instanceof Error ? deleteError.message : 'Agent 删除失败')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="space-y-5">
      <PageHeader title="Agent 管理" description="配置主 Agent、子 Agent 的指令、工具权限和运行参数。" actions={<Button size="sm" onClick={() => { setEditor('new'); setSuccess('') }}><Plus size={15} />新建 Agent</Button>} />
      {error && <Notice type="error">{error}</Notice>}
      {success && <Notice type="success">{success}</Notice>}
      <div className="relative max-w-xl">
        <Search size={15} className="absolute left-3 top-1/2 -translate-y-1/2 text-text-muted" />
        <input className={`${inputClass} pl-9`} value={query} onChange={(event) => setQuery(event.target.value)} placeholder="搜索名称或描述" />
      </div>

      {loading ? <LoadingState label="正在加载 Agent 配置" /> : visibleItems.length === 0 ? (
        <EmptyState title={items.length ? '没有匹配的 Agent' : '尚未配置 Agent'} description={items.length ? '调整搜索内容后重试。' : '创建 Agent 后可在对话中选择并运行。'} action={!items.length ? <Button size="sm" onClick={() => setEditor('new')}><Plus size={15} />新建 Agent</Button> : undefined} />
      ) : (
        <div className="overflow-x-auto border border-border">
          <table className="w-full min-w-[820px] border-collapse text-left">
            <thead className="bg-bg-elevated text-xs text-text-secondary"><tr><th className="px-4 py-3 font-medium">Agent</th><th className="px-4 py-3 font-medium">模式</th><th className="px-4 py-3 font-medium">状态</th><th className="px-4 py-3 font-medium">运行参数</th><th className="px-4 py-3 font-medium">更新时间</th><th className="w-24 px-4 py-3 text-right font-medium">操作</th></tr></thead>
            <tbody className="divide-y divide-border bg-bg-surface">
              {visibleItems.map((item) => (
                <tr key={item.id} className="hover:bg-bg-elevated/60">
                  <td className="max-w-sm px-4 py-3"><div className="flex items-center gap-2"><span className="text-sm font-medium text-text-primary">{item.name}</span>{item.hidden && <EyeOff size={13} className="text-text-muted" />}</div><p className="mt-1 line-clamp-1 text-xs text-text-secondary">{item.description}</p></td>
                  <td className="px-4 py-3 text-xs text-text-secondary">{item.mode === 'all' ? '全部' : item.mode === 'primary' ? '主 Agent' : '子 Agent'}</td>
                  <td className="px-4 py-3"><StatusBadge enabled={item.enabled} /></td>
                  <td className="px-4 py-3 font-mono text-xs text-text-muted">T {item.temperature ?? 'default'} · Steps {item.max_steps ?? 'default'}</td>
                  <td className="whitespace-nowrap px-4 py-3 text-xs text-text-muted">{formatDate(item.updated_at)}</td>
                  <td className="px-4 py-3"><div className="flex justify-end gap-1"><button title="编辑" onClick={() => { setEditor(item); setSuccess('') }} className="p-2 text-text-muted hover:bg-bg-hover hover:text-accent"><Pencil size={15} /></button><button title="删除" onClick={() => setDeleting(item)} className="p-2 text-text-muted hover:bg-error/10 hover:text-error"><Trash2 size={15} /></button></div></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {editor && <Modal open title={editor === 'new' ? '新建 Agent' : `编辑 ${editor.name}`} size="lg" onClose={() => !busy && setEditor(null)}><AgentForm key={editor === 'new' ? 'new' : editor.id} item={editor === 'new' ? null : editor} busy={busy} onCancel={() => setEditor(null)} onSave={save} /></Modal>}
      <ConfirmDialog open={Boolean(deleting)} title="删除 Agent" message={`确定删除 Agent“${deleting?.name ?? ''}”吗？相关 Skill 权限可能同时失效。`} busy={busy} onClose={() => setDeleting(null)} onConfirm={remove} />
    </div>
  )
}
