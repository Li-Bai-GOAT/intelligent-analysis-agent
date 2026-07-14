import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { ChevronRight, File, Folder, Search, Settings2, Trash2, Upload } from 'lucide-react'
import { AdminApi } from '../../api/admin'
import { Button } from '../../components/ui/Button'
import { Modal } from '../../components/ui/Modal'
import { Switch } from '../../components/ui/Switch'
import type { AgentConfig, SkillConfig, SkillFileContent, SkillFileNode, SkillPermissionValue } from '../types'
import { ConfirmDialog, EmptyState, LoadingState, Notice, PageHeader, StatusBadge } from '../components/AdminUi'
import { formatDate, inputClass } from '../utils'

function FileTreeNodes({ nodes, onOpen }: { nodes: SkillFileNode[]; onOpen: (node: SkillFileNode) => void }) {
  return (
    <ul className="space-y-0.5">
      {nodes.map((node) => (
        <li key={node.path}>
          {node.type === 'directory' ? (
            <details open>
              <summary className="flex cursor-pointer list-none items-center gap-2 px-2 py-1.5 text-xs text-text-secondary hover:bg-bg-hover hover:text-text-primary">
                <ChevronRight size={13} className="details-chevron" />
                <Folder size={14} className="text-warning" />
                <span className="truncate">{node.name}</span>
              </summary>
              <div className="ml-4 border-l border-border pl-2"><FileTreeNodes nodes={node.children ?? []} onOpen={onOpen} /></div>
            </details>
          ) : (
            <button type="button" onClick={() => onOpen(node)} className="flex w-full items-center gap-2 px-2 py-1.5 text-left text-xs text-text-secondary hover:bg-bg-hover hover:text-accent">
              <File size={14} className="shrink-0" />
              <span className="truncate">{node.name}</span>
              {node.size !== undefined && <span className="ml-auto text-[10px] text-text-muted">{node.size} B</span>}
            </button>
          )}
        </li>
      ))}
    </ul>
  )
}

export function SkillsPage() {
  const uploadRef = useRef<HTMLInputElement>(null)
  const [items, setItems] = useState<SkillConfig[]>([])
  const [query, setQuery] = useState('')
  const [loading, setLoading] = useState(true)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [success, setSuccess] = useState('')
  const [selected, setSelected] = useState<SkillConfig | null>(null)
  const [deleting, setDeleting] = useState<SkillConfig | null>(null)
  const [detailLoading, setDetailLoading] = useState(false)
  const [files, setFiles] = useState<SkillFileNode[]>([])
  const [fileContent, setFileContent] = useState<SkillFileContent | null>(null)
  const [agents, setAgents] = useState<AgentConfig[]>([])
  const [permissions, setPermissions] = useState<Record<number, SkillPermissionValue>>({})

  const load = useCallback(async () => {
    setLoading(true); setError('')
    try { setItems(await AdminApi.getSkills()) } catch (loadError) { setError(loadError instanceof Error ? loadError.message : 'Skill 列表加载失败') } finally { setLoading(false) }
  }, [])
  useEffect(() => {
    const timer = window.setTimeout(() => void load(), 0)
    return () => window.clearTimeout(timer)
  }, [load])

  const visibleItems = useMemo(() => {
    const keyword = query.trim().toLowerCase()
    return keyword ? items.filter((item) => `${item.name}\n${item.description}`.toLowerCase().includes(keyword)) : items
  }, [items, query])

  const upload = async (file?: File) => {
    if (!file) return
    if (!file.name.toLowerCase().endsWith('.zip')) { setError('Skill 仅支持 ZIP 压缩包。'); return }
    setBusy(true); setError(''); setSuccess('')
    try { const skill = await AdminApi.uploadSkill(file); setSuccess(`Skill“${skill.name}”上传成功。`); await load() } catch (uploadError) { setError(uploadError instanceof Error ? uploadError.message : 'Skill 上传失败') } finally { setBusy(false); if (uploadRef.current) uploadRef.current.value = '' }
  }

  const toggle = async (item: SkillConfig, enabled: boolean) => {
    if (enabled === item.enabled) return
    setBusy(true); setError('')
    try { await AdminApi.toggleSkill(item.id); setItems((current) => current.map((entry) => entry.id === item.id ? { ...entry, enabled } : entry)); setSuccess(`Skill“${item.name}”已${enabled ? '启用' : '停用'}。`) } catch (toggleError) { setError(toggleError instanceof Error ? toggleError.message : 'Skill 状态更新失败') } finally { setBusy(false) }
  }

  const openDetail = async (item: SkillConfig) => {
    setSelected(item); setDetailLoading(true); setFileContent(null); setFiles([]); setError('')
    try {
      const [tree, agentItems] = await Promise.all([AdminApi.getSkillFiles(item.id), AdminApi.getAgents()])
      setFiles(tree.children); setAgents(agentItems)
      const existing: Record<number, SkillPermissionValue> = {}
      for (const permission of item.agent_permissions) existing[permission.agent_id] = permission.permission
      setPermissions(existing)
    } catch (detailError) { setError(detailError instanceof Error ? detailError.message : 'Skill 详情加载失败') } finally { setDetailLoading(false) }
  }

  const openFile = async (node: SkillFileNode) => {
    if (!selected || node.type !== 'file') return
    setFileContent({ path: node.path, content: '正在读取文件...', type: 'text' })
    try { setFileContent(await AdminApi.getSkillFileContent(selected.id, node.path)) } catch (fileError) { setFileContent({ path: node.path, content: fileError instanceof Error ? fileError.message : '文件读取失败', type: 'text' }) }
  }

  const savePermissions = async () => {
    if (!selected) return
    setBusy(true); setError('')
    try {
      await AdminApi.updateSkillPermissions(selected.id, Object.entries(permissions).map(([agentId, permission]) => ({ agent_id: Number(agentId), permission })))
      setSuccess(`Skill“${selected.name}”的 Agent 权限已更新。`); setSelected(null); await load()
    } catch (permissionError) { setError(permissionError instanceof Error ? permissionError.message : 'Skill 权限保存失败') } finally { setBusy(false) }
  }

  const remove = async () => {
    if (!deleting) return
    setBusy(true)
    try { await AdminApi.deleteSkill(deleting.id); setSuccess(`Skill“${deleting.name}”已删除。`); setDeleting(null); await load() } catch (deleteError) { setError(deleteError instanceof Error ? deleteError.message : 'Skill 删除失败') } finally { setBusy(false) }
  }

  return (
    <div className="space-y-5">
      <PageHeader title="Skill 管理" description="上传 KunCode Skill 能力包，检查文件内容并配置各 Agent 的调用权限。" actions={<><input ref={uploadRef} className="hidden" type="file" accept=".zip,application/zip" onChange={(event) => void upload(event.target.files?.[0])} /><Button size="sm" onClick={() => uploadRef.current?.click()} disabled={busy}><Upload size={15} />{busy ? '处理中' : '上传 ZIP'}</Button></>} />
      {error && <Notice type="error">{error}</Notice>}{success && <Notice type="success">{success}</Notice>}
      <div className="relative max-w-xl"><Search size={15} className="absolute left-3 top-1/2 -translate-y-1/2 text-text-muted" /><input className={`${inputClass} pl-9`} value={query} onChange={(event) => setQuery(event.target.value)} placeholder="搜索名称或描述" /></div>

      {loading ? <LoadingState label="正在加载 Skill" /> : visibleItems.length === 0 ? <EmptyState title={items.length ? '没有匹配的 Skill' : '尚未上传 Skill'} description={items.length ? '调整搜索内容后重试。' : '上传包含 SKILL.md 的 ZIP 压缩包以添加能力。'} action={!items.length ? <Button size="sm" onClick={() => uploadRef.current?.click()}><Upload size={15} />上传 ZIP</Button> : undefined} /> : (
        <div className="overflow-x-auto border border-border"><table className="w-full min-w-[780px] border-collapse text-left"><thead className="bg-bg-elevated text-xs text-text-secondary"><tr><th className="px-4 py-3 font-medium">Skill</th><th className="px-4 py-3 font-medium">状态</th><th className="px-4 py-3 font-medium">Agent 权限</th><th className="px-4 py-3 font-medium">更新时间</th><th className="w-28 px-4 py-3 text-right font-medium">操作</th></tr></thead><tbody className="divide-y divide-border bg-bg-surface">
          {visibleItems.map((item) => <tr key={item.id} className="hover:bg-bg-elevated/60"><td className="max-w-lg px-4 py-3"><p className="text-sm font-medium text-text-primary">{item.name}</p><p className="mt-1 line-clamp-1 text-xs text-text-secondary">{item.description}</p></td><td className="px-4 py-3"><div className="flex items-center gap-3"><Switch checked={item.enabled} onChange={(value) => void toggle(item, value)} /><StatusBadge enabled={item.enabled} /></div></td><td className="px-4 py-3 text-xs text-text-secondary">{item.agent_permissions.length} 项已配置</td><td className="whitespace-nowrap px-4 py-3 text-xs text-text-muted">{formatDate(item.updated_at)}</td><td className="px-4 py-3"><div className="flex justify-end gap-1"><button title="文件与权限" onClick={() => void openDetail(item)} className="p-2 text-text-muted hover:bg-bg-hover hover:text-accent"><Settings2 size={15} /></button><button title="删除" onClick={() => setDeleting(item)} className="p-2 text-text-muted hover:bg-error/10 hover:text-error"><Trash2 size={15} /></button></div></td></tr>)}
        </tbody></table></div>
      )}

      {selected && <Modal open title={`Skill · ${selected.name}`} size="lg" onClose={() => !busy && setSelected(null)} footer={<><Button variant="ghost" onClick={() => setSelected(null)} disabled={busy}>关闭</Button><Button onClick={savePermissions} disabled={busy || detailLoading}>{busy ? '正在保存' : '保存权限'}</Button></>}>
        {detailLoading ? <LoadingState label="正在读取 Skill 文件与权限" /> : <div className="space-y-5">
          <div><p className="text-xs font-medium text-text-secondary">说明</p><p className="mt-1 text-sm leading-6 text-text-primary">{selected.description}</p></div>
          <div className="grid min-h-[300px] border border-border lg:grid-cols-[240px_minmax(0,1fr)]">
            <div className="border-b border-border bg-bg-base p-2 lg:border-b-0 lg:border-r"><p className="px-2 pb-2 pt-1 text-xs font-medium text-text-muted">文件</p>{files.length ? <FileTreeNodes nodes={files} onOpen={(node) => void openFile(node)} /> : <p className="px-2 py-4 text-xs text-text-muted">没有可浏览文件</p>}</div>
            <div className="min-w-0 bg-[#0d1117] p-3"><p className="mb-2 truncate font-mono text-xs text-text-muted">{fileContent?.path ?? '选择左侧文件查看内容'}</p><pre className="max-h-80 overflow-auto whitespace-pre-wrap break-words font-mono text-xs leading-5 text-text-secondary">{fileContent?.type === 'binary' ? '二进制文件不支持预览' : fileContent?.content ?? ''}</pre></div>
          </div>
          <div><div className="mb-3"><h3 className="text-sm font-semibold text-text-primary">Agent 调用权限</h3><p className="mt-1 text-xs text-text-muted">未显式配置的 Agent 将保持后端默认行为。</p></div>{agents.length === 0 ? <p className="border border-dashed border-border px-4 py-5 text-xs text-text-muted">当前没有可配置的 Agent。</p> : <div className="divide-y divide-border border border-border">{agents.map((agent) => <div key={agent.id} className="flex flex-col gap-2 px-3 py-3 sm:flex-row sm:items-center sm:justify-between"><div><p className="text-sm text-text-primary">{agent.name}</p><p className="mt-0.5 text-xs text-text-muted">{agent.description}</p></div><select className={`${inputClass} w-full sm:w-36`} value={permissions[agent.id] ?? 'ask'} onChange={(event) => setPermissions((current) => ({ ...current, [agent.id]: event.target.value as SkillPermissionValue }))}><option value="allow">允许</option><option value="ask">询问</option><option value="deny">拒绝</option></select></div>)}</div>}</div>
        </div>}
      </Modal>}
      <ConfirmDialog open={Boolean(deleting)} title="删除 Skill" message={`确定删除 Skill“${deleting?.name ?? ''}”及其本地文件吗？此操作无法恢复。`} busy={busy} onClose={() => setDeleting(null)} onConfirm={remove} />
    </div>
  )
}
