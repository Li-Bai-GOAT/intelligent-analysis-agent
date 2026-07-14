import { useCallback, useEffect, useState } from 'react'
import { RefreshCw, Save } from 'lucide-react'
import { AdminApi } from '../../api/admin'
import { Button } from '../../components/ui/Button'
import { LoadingState, Notice, PageHeader } from '../components/AdminUi'
import { formatDate, textareaClass } from '../utils'

export function PromptPage() {
  const [name, setName] = useState('')
  const [title, setTitle] = useState('')
  const [content, setContent] = useState('')
  const [savedContent, setSavedContent] = useState('')
  const [updatedAt, setUpdatedAt] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')
  const [success, setSuccess] = useState('')
  const dirty = content !== savedContent

  const load = useCallback(async () => {
    setLoading(true)
    setError('')
    try {
      const prompt = await AdminApi.getSystemPrompt()
      setName(prompt.name)
      setTitle(prompt.title)
      setContent(prompt.content)
      setSavedContent(prompt.content)
      setUpdatedAt(prompt.updated_at)
      setSuccess('')
    } catch (loadError) {
      setError(loadError instanceof Error ? loadError.message : '系统提示词加载失败')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    const timer = window.setTimeout(() => void load(), 0)
    return () => window.clearTimeout(timer)
  }, [load])

  useEffect(() => {
    const warn = (event: BeforeUnloadEvent) => {
      if (!dirty) return
      event.preventDefault()
    }
    window.addEventListener('beforeunload', warn)
    return () => window.removeEventListener('beforeunload', warn)
  }, [dirty])

  const save = async () => {
    if (!content.trim()) {
      setError('系统提示词不能为空。')
      return
    }
    setSaving(true)
    setError('')
    setSuccess('')
    try {
      const result = await AdminApi.updateSystemPrompt(content)
      setSavedContent(content)
      setUpdatedAt(result.updated_at)
      setSuccess('系统提示词已保存，后续 Agent 请求将使用新内容。')
    } catch (saveError) {
      setError(saveError instanceof Error ? saveError.message : '系统提示词保存失败')
    } finally {
      setSaving(false)
    }
  }

  const reload = () => {
    if (dirty && !window.confirm('当前修改尚未保存，确定重新加载服务端内容吗？')) return
    void load()
  }

  return (
    <div className="space-y-5">
      <PageHeader
        title="系统提示词"
        description="维护产品经理 Agent 的全局行为规则。保存后仅影响后续请求。"
        actions={
          <>
            <Button variant="secondary" size="sm" onClick={reload} disabled={loading || saving}><RefreshCw size={15} />重新加载</Button>
            <Button size="sm" onClick={save} disabled={loading || saving || !dirty}><Save size={15} />{saving ? '正在保存' : '保存修改'}</Button>
          </>
        }
      />
      {error && <Notice type="error">{error}</Notice>}
      {success && <Notice type="success">{success}</Notice>}

      {loading ? <LoadingState label="正在加载系统提示词" /> : (
        <div className="space-y-3">
          <div className="flex flex-col gap-2 border border-border bg-bg-surface px-4 py-3 text-xs text-text-secondary sm:flex-row sm:items-center sm:justify-between">
            <div><span className="text-text-muted">配置：</span><span className="ml-1 text-text-primary">{title || name}</span><span className="ml-2 font-mono text-text-muted">{name}</span></div>
            <div className="flex items-center gap-3"><span>最后更新：{formatDate(updatedAt)}</span>{dirty && <span className="text-warning">有未保存修改</span>}</div>
          </div>
          <textarea
            aria-label="系统提示词内容"
            className={`${textareaClass} min-h-[520px] bg-[#0d1117] p-4 font-mono text-[13px]`}
            value={content}
            onChange={(event) => { setContent(event.target.value); setSuccess('') }}
            spellCheck={false}
          />
          <div className="flex justify-between text-xs text-text-muted">
            <span>{content.length.toLocaleString('zh-CN')} 个字符</span>
            <span>当前后端尚未提供版本历史与回滚</span>
          </div>
        </div>
      )}
    </div>
  )
}
