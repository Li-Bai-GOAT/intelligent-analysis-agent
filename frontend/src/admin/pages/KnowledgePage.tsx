import { useCallback, useEffect, useMemo, useState } from 'react'
import { ChevronLeft, ChevronRight, Pencil, Plus, Search, Trash2 } from 'lucide-react'
import { AdminApi } from '../../api/admin'
import { Button } from '../../components/ui/Button'
import { Input } from '../../components/ui/Input'
import { Modal } from '../../components/ui/Modal'
import type { KnowledgeInput, KnowledgeItem } from '../types'
import {
  ConfirmDialog,
  EmptyState,
  Field,
  LoadingState,
  Notice,
  PageHeader,
} from '../components/AdminUi'
import { formatDate, inputClass, textareaClass } from '../utils'

const pageSize = 50

function KnowledgeForm({
  item,
  busy,
  onCancel,
  onSave,
}: {
  item: KnowledgeItem | null
  busy: boolean
  onCancel: () => void
  onSave: (data: KnowledgeInput) => void
}) {
  const [title, setTitle] = useState(item?.title ?? '')
  const [category, setCategory] = useState(item?.category ?? 'general')
  const [content, setContent] = useState(item?.content ?? '')
  const [error, setError] = useState('')

  const submit = () => {
    if (!title.trim() || !category.trim() || !content.trim()) {
      setError('标题、分类和内容均不能为空。')
      return
    }
    onSave({ title: title.trim(), category: category.trim(), content: content.trim(), metadata: item?.metadata ?? null })
  }

  return (
    <>
      <div className="space-y-4">
        {error && <Notice type="error">{error}</Notice>}
        <Input label="标题" value={title} onChange={(event) => setTitle(event.target.value)} maxLength={256} autoFocus />
        <Input label="分类" value={category} onChange={(event) => setCategory(event.target.value)} maxLength={64} />
        <Field label="知识内容" hint={`${content.length} 个字符`}>
          <textarea className={`${textareaClass} min-h-72 font-mono`} value={content} onChange={(event) => setContent(event.target.value)} />
        </Field>
      </div>
      <div className="mt-5 flex justify-end gap-2 border-t border-border pt-4">
        <Button variant="ghost" onClick={onCancel} disabled={busy}>取消</Button>
        <Button onClick={submit} disabled={busy}>{busy ? '正在保存' : '保存条目'}</Button>
      </div>
    </>
  )
}

export function KnowledgePage() {
  const [items, setItems] = useState<KnowledgeItem[]>([])
  const [total, setTotal] = useState(0)
  const [offset, setOffset] = useState(0)
  const [category, setCategory] = useState('')
  const [query, setQuery] = useState('')
  const [loading, setLoading] = useState(true)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [success, setSuccess] = useState('')
  const [editor, setEditor] = useState<KnowledgeItem | 'new' | null>(null)
  const [deleting, setDeleting] = useState<KnowledgeItem | null>(null)

  const load = useCallback(async () => {
    setLoading(true)
    setError('')
    try {
      const result = await AdminApi.listKnowledge(category || undefined, pageSize, offset)
      setItems(result.items)
      setTotal(result.total)
    } catch (loadError) {
      setError(loadError instanceof Error ? loadError.message : '知识库加载失败')
    } finally {
      setLoading(false)
    }
  }, [category, offset])

  useEffect(() => {
    const timer = window.setTimeout(() => void load(), 0)
    return () => window.clearTimeout(timer)
  }, [load])

  const visibleItems = useMemo(() => {
    const keyword = query.trim().toLowerCase()
    if (!keyword) return items
    return items.filter((item) => `${item.title}\n${item.content}`.toLowerCase().includes(keyword))
  }, [items, query])

  const save = async (data: KnowledgeInput) => {
    setBusy(true)
    setError('')
    try {
      if (editor === 'new') {
        await AdminApi.createKnowledge(data)
        setSuccess(`已创建知识条目“${data.title}”。`)
      } else if (editor) {
        await AdminApi.updateKnowledge(editor.id, data)
        setSuccess(`已更新知识条目“${data.title}”。`)
      }
      setEditor(null)
      await load()
    } catch (saveError) {
      setError(saveError instanceof Error ? saveError.message : '知识条目保存失败')
    } finally {
      setBusy(false)
    }
  }

  const remove = async () => {
    if (!deleting) return
    setBusy(true)
    setError('')
    try {
      await AdminApi.deleteKnowledge(deleting.id)
      setSuccess(`已删除知识条目“${deleting.title}”。`)
      setDeleting(null)
      if (items.length === 1 && offset > 0) setOffset(Math.max(0, offset - pageSize))
      else await load()
    } catch (deleteError) {
      setError(deleteError instanceof Error ? deleteError.message : '知识条目删除失败')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="space-y-5">
      <PageHeader
        title="知识库"
        description="维护 Agent 可检索的业务知识。修改后将由后端知识服务统一保存。"
        actions={<Button size="sm" onClick={() => { setEditor('new'); setSuccess('') }}><Plus size={15} />新增条目</Button>}
      />
      {error && <Notice type="error">{error}</Notice>}
      {success && <Notice type="success">{success}</Notice>}

      <div className="grid gap-3 sm:grid-cols-[minmax(0,1fr)_220px]">
        <div className="relative">
          <Search size={15} className="absolute left-3 top-1/2 -translate-y-1/2 text-text-muted" />
          <input className={`${inputClass} pl-9`} value={query} onChange={(event) => setQuery(event.target.value)} placeholder="在当前页搜索标题或内容" />
        </div>
        <input
          className={inputClass}
          value={category}
          onChange={(event) => { setCategory(event.target.value); setOffset(0) }}
          placeholder="按分类筛选"
        />
      </div>

      {loading ? <LoadingState label="正在加载知识库" /> : visibleItems.length === 0 ? (
        <EmptyState
          title={items.length ? '当前搜索没有结果' : '知识库中还没有条目'}
          description={items.length ? '调整搜索关键字或分类后重试。' : '创建第一条可供 Agent 检索的业务知识。'}
          action={!items.length ? <Button size="sm" onClick={() => setEditor('new')}><Plus size={15} />新增条目</Button> : undefined}
        />
      ) : (
        <div className="overflow-x-auto border border-border">
          <table className="w-full min-w-[760px] border-collapse text-left">
            <thead className="bg-bg-elevated text-xs text-text-secondary">
              <tr>
                <th className="px-4 py-3 font-medium">标题</th>
                <th className="px-4 py-3 font-medium">分类</th>
                <th className="px-4 py-3 font-medium">内容摘要</th>
                <th className="px-4 py-3 font-medium">更新时间</th>
                <th className="w-24 px-4 py-3 text-right font-medium">操作</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-border bg-bg-surface">
              {visibleItems.map((item) => (
                <tr key={item.id} className="hover:bg-bg-elevated/60">
                  <td className="max-w-64 px-4 py-3 text-sm font-medium text-text-primary"><span className="line-clamp-2">{item.title}</span></td>
                  <td className="px-4 py-3 text-xs text-accent">{item.category}</td>
                  <td className="max-w-md px-4 py-3 text-xs leading-5 text-text-secondary"><span className="line-clamp-2">{item.content}</span></td>
                  <td className="whitespace-nowrap px-4 py-3 text-xs text-text-muted">{formatDate(item.updated_at)}</td>
                  <td className="px-4 py-3">
                    <div className="flex justify-end gap-1">
                      <button title="编辑" onClick={() => { setEditor(item); setSuccess('') }} className="p-2 text-text-muted hover:bg-bg-hover hover:text-accent"><Pencil size={15} /></button>
                      <button title="删除" onClick={() => setDeleting(item)} className="p-2 text-text-muted hover:bg-error/10 hover:text-error"><Trash2 size={15} /></button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <div className="flex items-center justify-between text-xs text-text-muted">
        <span>共 {total} 条，第 {Math.floor(offset / pageSize) + 1} 页</span>
        <div className="flex gap-1">
          <button title="上一页" className="border border-border p-2 hover:bg-bg-hover disabled:opacity-40" disabled={offset === 0 || loading} onClick={() => setOffset(Math.max(0, offset - pageSize))}><ChevronLeft size={15} /></button>
          <button title="下一页" className="border border-border p-2 hover:bg-bg-hover disabled:opacity-40" disabled={offset + pageSize >= total || loading} onClick={() => setOffset(offset + pageSize)}><ChevronRight size={15} /></button>
        </div>
      </div>

      {editor && (
        <Modal open title={editor === 'new' ? '新增知识条目' : '编辑知识条目'} size="lg" onClose={() => !busy && setEditor(null)}>
          <KnowledgeForm key={editor === 'new' ? 'new' : editor.id} item={editor === 'new' ? null : editor} busy={busy} onCancel={() => setEditor(null)} onSave={save} />
        </Modal>
      )}
      <ConfirmDialog
        open={Boolean(deleting)}
        title="删除知识条目"
        message={`确定删除“${deleting?.title ?? ''}”吗？删除后无法恢复。`}
        busy={busy}
        onClose={() => setDeleting(null)}
        onConfirm={remove}
      />
    </div>
  )
}
