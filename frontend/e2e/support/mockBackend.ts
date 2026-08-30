import type { Page, Route } from '@playwright/test'

export interface MockBackendOptions {
  streamBodies?: string[]
  pendingPreview?: Record<string, unknown> | null
  files?: Array<{ name: string; path: string; type: 'file' | 'directory'; size?: number }>
}

export interface MockBackendState {
  confirmations: Array<{ path: string; body: Record<string, unknown> }>
  interruptCalls: number
  lastEventIds: string[]
  writeStatuses: number[]
}

const now = '2026-08-30T08:00:00Z'

export function sse(...events: Array<Record<string, unknown>>): string {
  return events.map((event, index) => `id: ${index + 1}-0\ndata: ${JSON.stringify(event)}\n\n`).join('')
}

function json(route: Route, body: unknown, status = 200) {
  return route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(body) })
}

export async function installMockBackend(page: Page, options: MockBackendOptions = {}): Promise<MockBackendState> {
  const state: MockBackendState = {
    confirmations: [],
    interruptCalls: 0,
    lastEventIds: [],
    writeStatuses: [],
  }
  const sessions: Array<{ session_id: string; name: string; created_at: string }> = []
  let currentUser = { id: 1, username: 'user', is_admin: false }
  let streamIndex = 0

  await page.route('**/ready', (route) => json(route, {
    status: 'ok',
    dependencies: { database: 'ok', redis: 'ok', sandbox: 'ok' },
  }))

  await page.route((url) => url.pathname.startsWith('/api/'), async (route) => {
    const request = route.request()
    const url = new URL(request.url())
    const path = url.pathname.replace(/^\/api/, '')
    const method = request.method()
    const body = request.postDataJSON?.() as Record<string, unknown> | null

    if (path === '/auth/login' && method === 'POST') {
      const username = String(body?.username || 'user')
      currentUser = { id: username === 'admin' ? 2 : 1, username, is_admin: username === 'admin' }
      return json(route, { access_token: `token-${username}`, token_type: 'bearer', user: currentUser })
    }
    if (path === '/auth/register' && method === 'POST') return json(route, currentUser, 201)
    if (path === '/sessions' && method === 'GET') return json(route, sessions)
    if (path === '/conversation/sessions' && method === 'POST') {
      const session = { session_id: 'session-e2e', name: 'E2E 会话', created_at: now }
      if (!sessions.length) sessions.push(session)
      return json(route, { session_id: session.session_id })
    }
    if (path === '/sessions/session-e2e' && method === 'GET') {
      return json(route, { messages: [], context_info: { usage_percent: 2, estimated_tokens: 128, max_tokens: 64000 } })
    }
    if (path === '/conversation/session/session-e2e/task' && method === 'GET') {
      return json(route, { session_id: 'session-e2e', has_active_task: false })
    }
    if (path === '/plans/session-e2e' && method === 'GET') {
      const preview = options.pendingPreview
      return json(route, preview?.preview_type === 'plan' ? {
        name: preview.name,
        state: 'todo',
        subtasks: Array.isArray(preview.subtasks)
          ? preview.subtasks.map((name) => ({ name, state: 'todo' }))
          : [],
      } : null)
    }
    if (path === '/kuncode/session-e2e/pending' && method === 'GET') {
      return json(route, options.pendingPreview || { has_pending: false })
    }
    if (path === '/conversation/async' && method === 'POST') return json(route, { task_id: 'task-e2e' })
    if (path === '/conversation/stream/task-e2e' && method === 'GET') {
      state.lastEventIds.push(request.headers()['last-event-id'] || '0')
      const bodies = options.streamBodies || [sse(
        { type: 'text', content: '简单问题回答成功。' },
        { type: 'end' },
      )]
      const responseBody = bodies[Math.min(streamIndex, bodies.length - 1)]
      streamIndex += 1
      return route.fulfill({
        status: 200,
        contentType: 'text/event-stream',
        headers: { 'Cache-Control': 'no-cache' },
        body: responseBody,
      })
    }
    if (path === '/conversation/session/session-e2e/interrupt' && method === 'POST') {
      state.interruptCalls += 1
      return json(route, {
        success: true,
        message: '代理已中断，容器内进程终止已确认',
        termination_reason: 'cancelled',
        termination_confirmed: true,
      })
    }
    if ((path.includes('/confirm/') || path.endsWith('/auto_continue/confirm')) && method === 'POST') {
      state.confirmations.push({ path, body: body || {} })
      return json(route, { success: true })
    }
    if (path === '/files/sandbox/session-e2e/workspace' && method === 'GET') {
      return json(route, options.files || [])
    }
    if (path === '/files/sandbox/session-e2e/workspace/content' && method === 'GET') {
      return json(route, { content: '# E2E 报告\n文件预览成功', binary: false, path: url.searchParams.get('path') })
    }
    if (path === '/files/sandbox/session-e2e/workspace/download' && method === 'GET') {
      return route.fulfill({
        status: 200,
        headers: { 'Content-Type': 'text/plain', 'Content-Disposition': 'attachment; filename="report.md"' },
        body: '# E2E report\n',
      })
    }
    if (path === '/files/sandbox/session-e2e/workspace/zip' && method === 'GET') {
      return route.fulfill({ status: 200, contentType: 'application/zip', body: 'mock-zip' })
    }
    if (path === '/system-prompt' && method === 'GET') {
      return json(route, { name: 'data_pm', title: 'DataPM 系统提示词', content: '只读测试内容', updated_at: now })
    }
    if (path === '/system-prompt' && method === 'PUT') {
      const status = currentUser.is_admin ? 200 : 403
      state.writeStatuses.push(status)
      return json(route, currentUser.is_admin
        ? { success: true, message: '已保存', updated_at: now }
        : { detail: '需要管理员权限' }, status)
    }
    if (path.startsWith('/knowledge') && method === 'GET') return json(route, { items: [], total: 0, limit: 50, offset: 0 })
    if (path === '/sandbox/skills' && method === 'GET') return json(route, [])
    if (path === '/sandbox/mcps' && method === 'GET') return json(route, [])

    return json(route, { detail: `Unhandled mock route: ${method} ${path}` }, 404)
  })

  return state
}
