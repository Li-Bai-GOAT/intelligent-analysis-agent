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
  static submitTask(sessionId: string, message: string, fileIds: string[] = [], executionMode: 'auto' | 'kuncode' = 'auto') {
    return this.request<{ task_id: string }>('POST', '/conversation/async', {
      session_id: sessionId,
      message,
      file_ids: fileIds,
      execution_mode: executionMode,
    })
  }

  static getSessionTask(sessionId: string) {
    return this.request<{ has_active_task: boolean; task_id?: string }>('GET', `/conversation/session/${sessionId}/task`)
  }

  static streamTask(taskId: string, onMessage: (data: Record<string, unknown>) => void, onDone: (data: Record<string, unknown>) => void) {
    const controller = new AbortController()
    let finished = false
    let lastEventId = '0'
    let reconnectAttempts = 0
    const maxReconnectAttempts = 3

    const finish = (data: Record<string, unknown>) => {
      if (finished) return
      finished = true
      onDone(data)
    }

    const consume = async (): Promise<void> => {
      try {
        const headers = this.headers({ Accept: 'text/event-stream' })
        if (lastEventId !== '0') headers['Last-Event-ID'] = lastEventId
        const response = await fetch(`${API_BASE}/conversation/stream/${taskId}`, {
          method: 'GET',
          headers,
          signal: controller.signal,
        })
        if (!response.ok || !response.body) {
          let detail = '任务流连接失败'
          const body = await response.json().catch(() => null) as { detail?: string } | null
          detail = body?.detail || detail
          throw new Error(detail)
        }

        const reader = response.body.getReader()
        const decoder = new TextDecoder()
        let buffer = ''
        const handleEvent = (rawEvent: string) => {
          const lines = rawEvent.split(/\r?\n/)
          const idLine = lines.find((line) => line.startsWith('id:'))
          if (idLine) lastEventId = idLine.slice(3).trim()
          const payload = lines
            .filter((line) => line.startsWith('data:'))
            .map((line) => line.slice(5).trimStart())
            .join('\n')
          if (!payload || payload === '[DONE]') return
          try {
            const data = JSON.parse(payload) as Record<string, unknown>
            if (data.type === 'end' || data.type === 'error') {
              onMessage(data)
              finish(data)
            } else {
              onMessage(data)
            }
          } catch (error) {
            console.error('SSE parse error:', error)
          }
        }

        while (!finished) {
          const { value, done } = await reader.read()
          buffer += decoder.decode(value || new Uint8Array(), { stream: !done })
          const events = buffer.split(/\r?\n\r?\n/)
          buffer = events.pop() || ''
          events.forEach(handleEvent)
          if (done) break
        }
        if (!finished && !controller.signal.aborted) throw new Error('任务流意外结束')
      } catch (error) {
        if (controller.signal.aborted) return
        if (reconnectAttempts < maxReconnectAttempts) {
          reconnectAttempts += 1
          await new Promise((resolve) => window.setTimeout(resolve, reconnectAttempts * 800))
          if (!controller.signal.aborted) await consume()
          return
        }
        finish({ type: 'error', content: error instanceof Error ? error.message : '任务流连接失败' })
      }
    }

    void consume()
    return { close: () => controller.abort() }
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

  private static async authenticatedBlob(url: string): Promise<Blob> {
    const response = await fetch(url, { headers: this.headers() })
    if (!response.ok) throw new Error('文件下载失败')
    return response.blob()
  }

  static downloadSandboxFile(sessionId: string, path: string) {
    return this.authenticatedBlob(this.getSandboxFileDownloadUrl(sessionId, path))
  }

  static downloadSandboxZip(sessionId: string) {
    return this.authenticatedBlob(this.getSandboxZipDownloadUrl(sessionId))
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

  static confirmKuncode(sessionId: string, previewId: string, action: 'confirm' | 'cancel', prompt?: string) {
    return this.request('POST', `/kuncode/${sessionId}/confirm/${previewId}`, { action, prompt })
  }

  static sendKuncodeInput(sessionId: string, previewId: string, message: string) {
    return this.request('POST', `/kuncode/${sessionId}/confirm/${previewId}`, { action: 'confirm', prompt: message })
  }

  // Plan preview
  static confirmPlanPreview(sessionId: string, previewId: string, action: 'confirm' | 'cancel') {
    return this.request('POST', `/kuncode/${sessionId}/plan/confirm/${previewId}`, { action })
  }

  static cancelPlanPreview(sessionId: string, previewId: string) {
    return this.request('POST', `/kuncode/${sessionId}/plan/confirm/${previewId}`, { action: 'cancel' })
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
