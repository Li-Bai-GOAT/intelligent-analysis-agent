import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { StreamData } from '../../src/types'

const { api } = vi.hoisted(() => ({
  api: {
    listSessions: vi.fn(),
    getSession: vi.fn(),
    getPlan: vi.fn(),
    getPendingPreview: vi.fn(),
    getSessionTask: vi.fn(),
    createSession: vi.fn(),
    deleteSession: vi.fn(),
    submitTask: vi.fn(),
    uploadFiles: vi.fn(),
    streamTask: vi.fn(),
    interruptSession: vi.fn(),
  },
}))

vi.mock('../../src/api/client', () => ({ Api: api }))

const { useSessionStore } = await import('../../src/stores/session')

function detail(sessionId: string, answer: string) {
  return {
    session_id: sessionId,
    messages: [
      { role: 'user', type: 'message', content: [{ type: 'text', text: `ask-${sessionId}` }] },
      { role: 'assistant', type: 'message', content: [{ type: 'text', text: answer }] },
    ],
    context_info: null,
  }
}

const contents = () => useSessionStore.getState().messages.map((message) => message.content)

beforeEach(() => {
  useSessionStore.setState(useSessionStore.getInitialState(), true)
  api.getPlan.mockResolvedValue(null)
  api.getPendingPreview.mockResolvedValue({ has_pending: false })
  api.getSessionTask.mockResolvedValue({ has_active_task: false })
  api.streamTask.mockReturnValue({ close: vi.fn() })
  vi.spyOn(console, 'log').mockImplementation(() => {})
  vi.spyOn(console, 'error').mockImplementation(() => {})
})

describe('session switching races', () => {
  it('discards a session load that resolves after the user switched away', async () => {
    let resolveA: ((value: unknown) => void) | undefined
    api.getSession.mockImplementation((sessionId: string) => {
      if (sessionId === 'session-a') {
        return new Promise((resolve) => {
          resolveA = resolve
        })
      }
      return Promise.resolve(detail('session-b', 'answer-b'))
    })

    const slow = useSessionStore.getState().selectSession('session-a')
    await useSessionStore.getState().selectSession('session-b')

    resolveA?.(detail('session-a', 'answer-a'))
    await slow

    expect(useSessionStore.getState().currentSession).toBe('session-b')
    expect(contents()).toEqual(['ask-session-b', 'answer-b'])
  })

  it('ignores an intermediate session that resolves after switching back', async () => {
    let resolveB: ((value: unknown) => void) | undefined
    api.getSession.mockImplementation((sessionId: string) => {
      if (sessionId === 'session-b') {
        return new Promise((resolve) => {
          resolveB = resolve
        })
      }
      return Promise.resolve(detail(sessionId, `answer-${sessionId}`))
    })

    const slowB = useSessionStore.getState().selectSession('session-b')
    await useSessionStore.getState().selectSession('session-a')
    resolveB?.(detail('session-b', 'answer-b'))
    await slowB

    expect(useSessionStore.getState().currentSession).toBe('session-a')
    expect(contents()).toEqual(['ask-session-a', 'answer-session-a'])
  })

  it('drops stream events that still belong to the previous session', async () => {
    const streams: Array<{ taskId: string; onMessage: (data: StreamData) => void }> = []
    api.streamTask.mockImplementation((taskId: string, onMessage: (data: StreamData) => void) => {
      streams.push({ taskId, onMessage })
      return { close: vi.fn() }
    })
    api.submitTask.mockResolvedValue({ task_id: 'task-a' })
    api.getSession.mockResolvedValue(detail('session-b', 'answer-b'))

    useSessionStore.setState({ currentSession: 'session-a' })
    expect(await useSessionStore.getState().sendMessage('hello')).toBe(true)
    expect(streams).toHaveLength(1)

    await useSessionStore.getState().selectSession('session-b')
    streams[0].onMessage({ type: 'text', content: 'stale output' })

    expect(contents()).not.toContain('stale output')
  })

  it('still applies events for the session that is on screen', async () => {
    const streams: Array<{ onMessage: (data: StreamData) => void }> = []
    api.streamTask.mockImplementation((_taskId: string, onMessage: (data: StreamData) => void) => {
      streams.push({ onMessage })
      return { close: vi.fn() }
    })
    api.submitTask.mockResolvedValue({ task_id: 'task-a' })

    useSessionStore.setState({ currentSession: 'session-a' })
    await useSessionStore.getState().sendMessage('hello')
    streams[0].onMessage({ type: 'text', content: 'live output' })

    expect(contents()).toContain('live output')
  })

  it('closes the previous stream when switching sessions', async () => {
    const close = vi.fn()
    api.streamTask.mockReturnValue({ close })
    api.submitTask.mockResolvedValue({ task_id: 'task-a' })
    api.getSession.mockResolvedValue(detail('session-b', 'answer-b'))

    useSessionStore.setState({ currentSession: 'session-a' })
    await useSessionStore.getState().sendMessage('hello')
    await useSessionStore.getState().selectSession('session-b')

    expect(close).toHaveBeenCalled()
  })
})

describe('reconnect on load', () => {
  it('resumes an active task without adding a second assistant bubble', async () => {
    api.getSession.mockResolvedValue(detail('session-a', 'partial answer'))
    api.getSessionTask.mockResolvedValue({ has_active_task: true, task_id: 'task-live' })

    await useSessionStore.getState().selectSession('session-a')

    const current = useSessionStore.getState()
    expect(current.messages).toHaveLength(2)
    expect(current.messages[1]).toMatchObject({ turnId: 'task-live', status: 'running' })
    expect(current.streamState.activeTurnId).toBe('task-live')
    expect(current.isStreaming).toBe(true)
  })

  it('closes the abandoned turn when the session has no active task', async () => {
    api.getSession.mockResolvedValue({
      session_id: 'session-a',
      messages: [
        { role: 'user', type: 'message', content: [{ type: 'text', text: 'go' }] },
        {
          role: 'assistant',
          type: 'plugin_call',
          content: [{ type: 'data', data: { call_id: 'call_1', name: 'kuncode', arguments: {} } }],
        },
      ],
      context_info: null,
    })

    await useSessionStore.getState().selectSession('session-a')

    const tool = useSessionStore.getState().messages[1].tool_calls?.[0]
    expect(tool?.execution_status).toBe('failed')
    expect(tool?.result).toContain('执行记录不完整')
    expect(useSessionStore.getState().isStreaming).toBe(false)
  })
})
