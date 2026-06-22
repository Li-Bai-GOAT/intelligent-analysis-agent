const API_BASE = '/api'

export class Api {
  static token = localStorage.getItem('token')
  static user = JSON.parse(localStorage.getItem('user') || 'null')

  static setAuth(token: string, user: { id: number; username: string; is_admin: boolean }) {
    this.token = token
    this.user = user
    localStorage.setItem('token', token)
    localStorage.setItem('user', JSON.stringify(user))
  }

  static clearAuth() {
    this.token = null
    this.user = null
    localStorage.removeItem('token')
    localStorage.removeItem('user')
  }

  private static headers(extra: Record<string, string> = {}) {
    const h: Record<string, string> = { 'Content-Type': 'application/json', ...extra }
    if (this.token) h['Authorization'] = `Bearer ${this.token}`
    return h
  }

  static async request<T = unknown>(method: string, path: string, body?: unknown): Promise<T> {
    const opts: RequestInit = { method, headers: this.headers() }
    if (body) opts.body = JSON.stringify(body)
    const res = await fetch(`${API_BASE}${path}`, opts)
    if (res.status === 401) {
      this.clearAuth()
      location.reload()
      throw new Error('未授权')
    }
    const data = await res.json()
    if (!res.ok) throw new Error(data.detail || '请求失败')
    return data as T
  }

  // Auth
  static register(username: string, password: string) {
    return this.request('POST', '/auth/register', { username, password })
  }

  static async login(username: string, password: string) {
    const data = await this.request<{ access_token: string; user: { id: number; username: string; is_admin: boolean } }>(
      'POST', '/auth/login', { username, password }
    )
    this.setAuth(data.access_token, data.user)
    return data
  }

  // Sessions
  static listSessions() {
    return this.request<Array<{ session_id: string; name?: string; created_at: string }>>('GET', '/sessions')
  }

  static getSession(sessionId: string) {
    return this.request<{ messages: Array<{ role: string; content: string; files?: unknown[] }>; context_info?: { usage_percent: number; estimated_tokens: number; max_tokens: number } }>(
      'GET', `/sessions/${sessionId}`
    )
  }

  static deleteSession(sessionId: string) {
    return this.request('DELETE', `/sessions/${sessionId}`)
  }

  static createSession() {
    return this.request<{ session_id: string }>('POST', '/conversation/sessions')
  }

  // Async Chat
  static submitTask(sessionId: string, message: string, fileIds: string[] = []) {
    return this.request<{ task_id: string }>('POST', '/conversation/async', {
      session_id: sessionId,
      message,
      file_ids: fileIds,
    })
  }

  static getSessionTask(sessionId: string) {
    return this.request<{ has_active_task: boolean; task_id?: string }>('GET', `/conversation/session/${sessionId}/task`)
  }

  static streamTask(taskId: string, onMessage: (data: Record<string, unknown>) => void, onDone: (data: Record<string, unknown>) => void) {
    const token = this.token || ''
    const eventSource = new EventSource(`${API_BASE}/conversation/stream/${taskId}?token=${encodeURIComponent(token)}`)
    eventSource.onmessage = (e) => {
      try {
        const data = JSON.parse(e.data)
        if (data.type === 'end' || data.type === 'error') {
          eventSource.close()
          onDone(data)
        } else {
          onMessage(data)
        }
      } catch (err) {
        console.error('Parse error:', err)
      }
    }
    eventSource.onerror = () => {
      eventSource.close()
      onDone({ type: 'error', content: '连接断开' })
    }
    return eventSource
  }

  // Files
  static async uploadFiles(sessionId: string, files: File[]) {
    const formData = new FormData()
    for (const f of files) formData.append('files', f)
    const res = await fetch(`${API_BASE}/files/upload?session_id=${sessionId}`, {
      method: 'POST',
      headers: { Authorization: `Bearer ${this.token}` },
      body: formData,
    })
    if (!res.ok) throw new Error('上传失败')
    return res.json()
  }

  static listUploadedFiles(sessionId: string) {
    return this.request<Array<{ file_id: string; filename: string; size: number }>>(`GET`, `/files/uploads/${sessionId}/list`)
  }

  static listSandboxWorkspace(sessionId: string, path = '') {
    const params = path ? `?path=${encodeURIComponent(path)}` : ''
    return this.request<Array<{ name: string; path: string; type: string; is_dir?: boolean; size?: number }>>(
      'GET', `/files/sandbox/${sessionId}/workspace${params}`
    )
  }

  static getSandboxFileContent(sessionId: string, path: string) {
    return this.request<{ content: string | null; binary?: boolean; image?: boolean; size?: number; path?: string }>(
      'GET', `/files/sandbox/${sessionId}/workspace/content?path=${encodeURIComponent(path)}`
    )
  }

  static saveSandboxFileContent(sessionId: string, path: string, content: string) {
    return this.request('PUT', `/files/sandbox/${sessionId}/workspace/content?path=${encodeURIComponent(path)}`, { content })
  }

  static getSandboxFileDownloadUrl(sessionId: string, path: string) {
    return `${API_BASE}/files/sandbox/${sessionId}/workspace/download?path=${encodeURIComponent(path)}`
  }

  static getSandboxZipDownloadUrl(sessionId: string) {
    return `${API_BASE}/files/sandbox/${sessionId}/workspace/zip`
  }

  // Knowledge
  static listKnowledge(category?: string, limit = 100, offset = 0) {
    let url = `/knowledge?limit=${limit}&offset=${offset}`
    if (category) url += `&category=${encodeURIComponent(category)}`
    return this.request<{ items: Array<{ id: number; title: string; category: string; content: string }>; total: number }>('GET', url)
  }

  static createKnowledge(data: { title: string; category: string; content: string }) {
    return this.request('POST', '/knowledge', data)
  }

  static updateKnowledge(id: number, data: { title: string; category: string; content: string }) {
    return this.request('PUT', `/knowledge/${id}`, data)
  }

  static deleteKnowledge(id: number) {
    return this.request('DELETE', `/knowledge/${id}`)
  }

  // System Prompt
  static getSystemPrompt() {
    return this.request<{ content: string }>('GET', '/system-prompt')
  }

  static updateSystemPrompt(content: string) {
    return this.request('PUT', '/system-prompt', { content })
  }

  // Sandbox Management - Agents
  static getAgents() {
    return this.request<Array<Record<string, unknown>>>('GET', '/sandbox/agents')
  }

  static getAgent(id: number) {
    return this.request<Record<string, unknown>>(`GET`, `/sandbox/agents/${id}`)
  }

  static createAgent(data: Record<string, unknown>) {
    return this.request('POST', '/sandbox/agents', data)
  }

  static updateAgent(id: number, data: Record<string, unknown>) {
    return this.request('PUT', `/sandbox/agents/${id}`, data)
  }

  static deleteAgent(id: number) {
    return this.request('DELETE', `/sandbox/agents/${id}`)
  }

  // Skills
  static getSkills() {
    return this.request<Array<Record<string, unknown>>>('GET', '/sandbox/skills')
  }

  static getSkill(id: number) {
    return this.request<Record<string, unknown>>(`GET`, `/sandbox/skills/${id}`)
  }

  static async uploadSkill(file: File) {
    const formData = new FormData()
    formData.append('file', file)
    const headers: Record<string, string> = {}
    if (this.token) headers['Authorization'] = `Bearer ${this.token}`
    const response = await fetch(`${API_BASE}/sandbox/skills/upload`, {
      method: 'POST',
      headers,
      body: formData,
    })
    if (!response.ok) {
      const err = await response.json()
      throw new Error(err.detail || '上传失败')
    }
    return response.json()
  }

  static toggleSkill(id: number) {
    return this.request('PATCH', `/sandbox/skills/${id}/toggle`)
  }

  static deleteSkill(id: number) {
    return this.request('DELETE', `/sandbox/skills/${id}`)
  }

  static updateSkillPermissions(skillId: number, permissions: Record<string, Record<string, string>>) {
    return this.request('PUT', `/sandbox/skills/${skillId}/permissions`, permissions)
  }

  static getSkillFiles(skillId: number) {
    return this.request<unknown>('GET', `/sandbox/skills/${skillId}/files`)
  }

  static getSkillFileContent(skillId: number, filePath: string) {
    return this.request<{ content: string }>('GET', `/sandbox/skills/${skillId}/files/${encodeURIComponent(filePath)}`)
  }

  // MCPs
  static getMcps() {
    return this.request<Array<Record<string, unknown>>>('GET', '/sandbox/mcps')
  }

  static getMcp(id: number) {
    return this.request<Record<string, unknown>>(`GET`, `/sandbox/mcps/${id}`)
  }

  static createMcp(data: Record<string, unknown>) {
    return this.request('POST', '/sandbox/mcps', data)
  }

  static updateMcp(id: number, data: Record<string, unknown>) {
    return this.request('PUT', `/sandbox/mcps/${id}`, data)
  }

  static deleteMcp(id: number) {
    return this.request('DELETE', `/sandbox/mcps/${id}`)
  }

  // Plan
  static getPlan(sessionId: string) {
    return this.request<Record<string, unknown>>(`GET`, `/plans/${sessionId}`)
  }

  static updatePlan(sessionId: string, data: Record<string, unknown>) {
    return this.request('PUT', `/plans/${sessionId}`, data)
  }

  static updateSubtask(sessionId: string, idx: number, data: Record<string, unknown>) {
    return this.request('PUT', `/plans/${sessionId}/subtasks/${idx}`, data)
  }

  static addSubtask(sessionId: string, data: Record<string, unknown>) {
    return this.request('POST', `/plans/${sessionId}/subtasks`, data)
  }

  static deleteSubtask(sessionId: string, idx: number) {
    return this.request('DELETE', `/plans/${sessionId}/subtasks/${idx}`)
  }

  // KunCode preview
  static getPendingPreview(sessionId: string) {
    return this.request<Record<string, unknown>>(`GET`, `/kuncode/${sessionId}/pending`)
  }

  static confirmKuncode(previewId: string) {
    return this.request('POST', `/kuncode/${previewId}/confirm`)
  }

  static cancelKuncode(previewId: string) {
    return this.request('POST', `/kuncode/${previewId}/cancel`)
  }

  static sendKuncodeInput(previewId: string, message: string) {
    return this.request('POST', `/kuncode/${previewId}/input`, { message })
  }

  // Plan preview
  static confirmPlanPreview(previewId: string) {
    return this.request('POST', `/plans/preview/${previewId}/confirm`)
  }

  static cancelPlanPreview(previewId: string) {
    return this.request('POST', `/plans/preview/${previewId}/cancel`)
  }

  // Interrupt
  static interruptSession(sessionId: string) {
    return this.request('POST', `/conversation/session/${sessionId}/interrupt`)
  }

  // Auto-continue
  static getAutoContinueStatus(sessionId: string) {
    return this.request<Record<string, unknown>>(`GET`, `/kuncode/${sessionId}/auto_continue/status`)
  }

  static confirmAutoContinue(sessionId: string) {
    return this.request('POST', `/kuncode/${sessionId}/auto_continue/confirm`)
  }

  static cancelAutoContinue(sessionId: string) {
    return this.request('POST', `/kuncode/${sessionId}/auto_continue/cancel`)
  }
}
