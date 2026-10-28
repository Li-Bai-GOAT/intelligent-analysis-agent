import { beforeEach, describe, expect, it, vi } from 'vitest'
import { projectHistoryMessages } from '../../src/stores/conversationProjection'
import { useSessionStore } from '../../src/stores/session'
import type { Message, StreamData } from '../../src/types'

function resetStore() {
  useSessionStore.setState(useSessionStore.getInitialState(), true)
}

function seedTurn(turnId = 'task-1', userText = 'question') {
  useSessionStore.setState((current) => ({
    messages: [
      { role: 'user', content: userText },
      { role: 'assistant', content: '', turnId, status: 'running' },
    ],
    isStreaming: true,
    streamState: { ...current.streamState, activeTurnId: turnId },
  }))
}

function emit(...events: StreamData[]) {
  for (const event of events) useSessionStore.getState().handleStreamData(event)
}

const state = () => useSessionStore.getState()
const lastAssistant = (): Message | undefined =>
  [...state().messages].reverse().find((message) => message.role === 'assistant')
const tools = () => lastAssistant()?.tool_calls ?? []

function normalize(messages: Message[]) {
  return messages.map((message) => ({
    role: message.role,
    content: message.content,
    thinking: message.thinking ?? '',
    tools: (message.tool_calls ?? []).map((tool) => ({
      id: tool.id,
      name: tool.name,
      arguments: tool.arguments,
      result: tool.result ?? '',
      status: tool.execution_status ?? 'running',
    })),
  }))
}

beforeEach(() => {
  resetStore()
  vi.spyOn(console, 'log').mockImplementation(() => {})
})

describe('tool_id in-place merging', () => {
  it('merges repeated tool_call records instead of duplicating cards', () => {
    seedTurn()
    emit(
      { type: 'tool_call', tool_id: 'call_1', content: 'kuncode' },
      { type: 'tool_call', tool_id: 'call_1', content: 'kuncode' },
    )
    expect(tools()).toHaveLength(1)
  })

  it('keeps distinct calls in arrival order', () => {
    seedTurn()
    emit(
      { type: 'tool_call', tool_id: 'call_1', content: 'first' },
      { type: 'tool_call', tool_id: 'call_2', content: 'second' },
    )
    expect(tools().map((tool) => tool.id)).toEqual(['call_1', 'call_2'])
  })

  it('updates stage metadata in place without losing arguments', () => {
    seedTurn()
    emit(
      { type: 'tool_call', tool_id: 'call_1', content: 'kuncode', input: { code: 'ls' } },
      { type: 'tool_call', tool_id: 'call_1', content: 'kuncode', stage: 'file_generating', message: 'writing' },
    )
    const [tool] = tools()
    expect(tool).toMatchObject({ stage: 'file_generating', stage_message: 'writing', arguments: '{"code":"ls"}' })
  })

  it('routes progress and result to the right card when two tools are running', () => {
    seedTurn()
    emit(
      { type: 'tool_call', tool_id: 'call_1', content: 'kuncode' },
      { type: 'tool_call', tool_id: 'call_2', content: 'kuncode' },
      { type: 'tool_result', tool_id: 'call_2', content: 'second done' },
      { type: 'tool_result', tool_id: 'call_1', content: 'first done' },
    )
    expect(tools().map((tool) => [tool.id, tool.result])).toEqual([
      ['call_1', 'first done'],
      ['call_2', 'second done'],
    ])
  })
})

describe('duplicate events', () => {
  it('is idempotent when the same tool_result is replayed', () => {
    seedTurn()
    emit(
      { type: 'tool_call', tool_id: 'call_1', content: 'kuncode' },
      { type: 'tool_result', tool_id: 'call_1', content: 'done' },
      { type: 'tool_result', tool_id: 'call_1', content: 'done' },
    )
    expect(tools()).toHaveLength(1)
    expect(tools()[0]).toMatchObject({ result: 'done', execution_status: 'completed' })
  })

  it('does not duplicate text or thinking that arrives twice', () => {
    seedTurn()
    emit(
      { type: 'text', content: 'answer' },
      { type: 'text', content: 'answer' },
      { type: 'thinking', content: 'reasoning' },
      { type: 'thinking', content: 'reasoning' },
    )
    expect(lastAssistant()?.content).toBe('answer')
    expect(lastAssistant()?.thinking).toBe('reasoning')
  })
})

describe('late and out-of-order events', () => {
  it('ignores a progress event that arrives after the tool finished', () => {
    seedTurn()
    emit(
      { type: 'tool_call', tool_id: 'call_1', content: 'kuncode' },
      { type: 'tool_result', tool_id: 'call_1', content: 'ok', execution_status: 'completed' },
      { type: 'tool_progress', tool_id: 'call_1', content: 'still working', stage: 'validating' },
    )
    expect(tools()[0]).toMatchObject({ execution_status: 'completed', result: 'ok' })
  })

  it('keeps a result that arrives before its call', () => {
    seedTurn()
    emit(
      { type: 'tool_result', tool_id: 'call_9', content: 'late output', execution_status: 'completed' },
      { type: 'tool_call', tool_id: 'call_9', content: 'kuncode' },
    )
    expect(tools()).toHaveLength(1)
    expect(tools()[0]).toMatchObject({ result: 'late output', execution_status: 'completed' })
  })

  it('does not let the buffered result leak into another tool', () => {
    seedTurn()
    emit(
      { type: 'tool_result', tool_id: 'call_9', content: 'orphan output' },
      { type: 'tool_call', tool_id: 'call_1', content: 'kuncode' },
    )
    expect(tools()).toHaveLength(1)
    expect(tools()[0].result).toBeUndefined()
  })

  it('does not resurrect a finished tool when the turn ends', () => {
    seedTurn()
    emit(
      { type: 'tool_call', tool_id: 'call_1', content: 'kuncode' },
      { type: 'tool_result', tool_id: 'call_1', content: 'ok' },
      { type: 'end' },
    )
    expect(tools()[0]).toMatchObject({ execution_status: 'completed', result: 'ok' })
  })
})

describe('reconnect replay', () => {
  const historyRecords = [
    { role: 'user', type: 'message', content: [{ type: 'text', text: 'count files' }] },
    {
      role: 'assistant',
      type: 'plugin_call',
      content: [{ type: 'data', data: { call_id: 'call_1', name: 'execute_python_code', arguments: { code: 'ls' } } }],
    },
    {
      role: 'assistant',
      type: 'plugin_call_output',
      content: [{ type: 'data', data: { call_id: 'call_1', output: '12K' } }],
    },
  ]

  it('does not duplicate tools when the stream replays after a reload', () => {
    const projected = projectHistoryMessages(historyRecords)
    projected[1] = { ...projected[1], turnId: 'task-1', status: 'running' }
    useSessionStore.setState({
      messages: projected,
      isStreaming: true,
      streamState: { ...state().streamState, activeTurnId: 'task-1' },
    })

    emit(
      { type: 'tool_call', tool_id: 'call_1', content: 'execute_python_code', input: { code: 'ls' } },
      { type: 'tool_result', tool_id: 'call_1', content: '12K' },
    )

    expect(tools()).toHaveLength(1)
    expect(tools()[0]).toMatchObject({ id: 'call_1', result: '12K', execution_status: 'completed' })
  })

  it('never downgrades a settled tool back to running when the call is replayed', () => {
    seedTurn()
    emit(
      { type: 'tool_call', tool_id: 'call_1', content: 'kuncode' },
      { type: 'tool_result', tool_id: 'call_1', content: 'ok' },
      { type: 'tool_call', tool_id: 'call_1', content: 'kuncode' },
    )
    expect(tools()[0].execution_status).toBe('completed')
  })
})

describe('history projection equals live projection', () => {
  function projectLive(events: StreamData[], userText = 'question') {
    seedTurn('task-1', userText)
    emit(...events)
    return state().messages
  }

  it('produces the same message for a successful tool turn', () => {
    const recorded = [
      { role: 'user', type: 'message', content: [{ type: 'text', text: '统计文件' }] },
      { role: 'assistant', type: 'reasoning', content: [{ type: 'text', text: '先看工作区' }] },
      { role: 'assistant', type: 'message', content: [{ type: 'text', text: '我先扫描' }] },
      {
        role: 'assistant',
        type: 'plugin_call',
        content: [{ type: 'data', data: { call_id: 'call_1', name: 'execute_python_code', arguments: { code: 'ls' } } }],
      },
      {
        role: 'assistant',
        type: 'plugin_call_output',
        content: [{ type: 'data', data: { call_id: 'call_1', output: '12K' } }],
      },
      { role: 'assistant', type: 'message', content: [{ type: 'text', text: '共 3 个文件' }] },
    ]

    const live = projectLive([
      { type: 'thinking', content: '先看工作区' },
      { type: 'text', content: '我先扫描' },
      { type: 'tool_call', tool_id: 'call_1', content: 'execute_python_code', input: { code: 'ls' } },
      { type: 'tool_result', tool_id: 'call_1', content: '12K' },
      { type: 'text', content: '共 3 个文件' },
      { type: 'end' },
    ], '统计文件')

    expect(normalize(live)).toEqual(normalize(projectHistoryMessages(recorded)))
  })

  it('agrees with history on a failed tool', () => {
    const output = '[error] kuncode execution failed\nTraceback (most recent call last):\nModuleNotFoundError'
    const recorded = [
      { role: 'user', type: 'message', content: [{ type: 'text', text: 'run it' }] },
      {
        role: 'assistant',
        type: 'plugin_call',
        content: [{ type: 'data', data: { call_id: 'call_1', name: 'kuncode', arguments: {} } }],
      },
      {
        role: 'assistant',
        type: 'plugin_call_output',
        content: [{ type: 'data', data: { call_id: 'call_1', output } }],
      },
    ]

    const live = projectLive([
      { type: 'tool_call', tool_id: 'call_1', content: 'kuncode', input: {} },
      { type: 'tool_result', tool_id: 'call_1', content: output },
      { type: 'end' },
    ], 'run it')

    expect(normalize(live)).toEqual(normalize(projectHistoryMessages(recorded)))
    expect(tools()[0].execution_status).toBe('failed')
  })

  it('agrees with history when a retry eventually succeeded', () => {
    const output = '[error] transient failure\nCompleted successfully'
    const recorded = [
      { role: 'user', type: 'message', content: [{ type: 'text', text: 'run it' }] },
      {
        role: 'assistant',
        type: 'plugin_call',
        content: [{ type: 'data', data: { call_id: 'call_1', name: 'kuncode', arguments: {} } }],
      },
      {
        role: 'assistant',
        type: 'plugin_call_output',
        content: [{ type: 'data', data: { call_id: 'call_1', output } }],
      },
    ]

    const live = projectLive([
      { type: 'tool_call', tool_id: 'call_1', content: 'kuncode', input: {} },
      { type: 'tool_result', tool_id: 'call_1', content: output },
    ], 'run it')

    expect(normalize(live)).toEqual(normalize(projectHistoryMessages(recorded)))
    expect(tools()[0].execution_status).toBe('completed')
  })

  it('treats an empty tool_result as failed on both paths', () => {
    const recorded = [
      { role: 'user', type: 'message', content: [{ type: 'text', text: 'run it' }] },
      {
        role: 'assistant',
        type: 'plugin_call',
        content: [{ type: 'data', data: { call_id: 'call_1', name: 'kuncode', arguments: {} } }],
      },
      {
        role: 'assistant',
        type: 'plugin_call_output',
        content: [{ type: 'data', data: { call_id: 'call_1', output: '' } }],
      },
    ]

    projectLive([
      { type: 'tool_call', tool_id: 'call_1', content: 'kuncode' },
      { type: 'tool_result', tool_id: 'call_1', content: '' },
    ])

    expect(tools()[0].execution_status).toBe('failed')
    expect(projectHistoryMessages(recorded)[1].tool_calls?.[0].execution_status).toBe('failed')
  })

  it('rebuilds the same thinking text from cumulative snapshots', () => {
    const recorded = [
      { role: 'user', type: 'message', content: [{ type: 'text', text: 'go' }] },
      { role: 'assistant', type: 'reasoning', content: [{ type: 'text', text: 'step one\n\nstep two' }] },
      { role: 'assistant', type: 'reasoning', content: [{ type: 'text', text: 'step one\n\nstep two and three' }] },
    ]

    const live = projectLive([
      { type: 'thinking', content: 'step one\n\nstep two' },
      { type: 'thinking', content: 'step one\n\nstep two and three' },
    ], 'go')

    expect(live[1].thinking).toBe('step one\n\nstep two and three')
    expect(normalize(live)).toEqual(normalize(projectHistoryMessages(recorded)))
  })
})

describe('terminal states never leave a tool running', () => {
  it('marks unfinished tools as failed when the turn completes', () => {
    seedTurn()
    emit(
      { type: 'tool_call', tool_id: 'call_1', content: 'kuncode' },
      { type: 'end' },
    )
    expect(tools()[0]).toMatchObject({
      execution_status: 'failed',
      result: '[ERROR] 工具调用未返回完整结果。',
    })
    expect(lastAssistant()?.status).toBe('completed')
    expect(state().isStreaming).toBe(false)
    expect(state().streamState.activeTurnId).toBeNull()
  })

  it('marks unfinished tools as cancelled when the user interrupts', () => {
    seedTurn()
    emit(
      { type: 'tool_call', tool_id: 'call_1', content: 'kuncode' },
      { type: 'interrupted', content: '用户中断了执行' },
    )
    expect(tools()[0].execution_status).toBe('cancelled')
    expect(lastAssistant()?.status).toBe('cancelled')
    expect(lastAssistant()?.content).toBe('[CANCELLED] 用户中断了执行')
  })

  it('marks unfinished tools as failed on a stream error', () => {
    seedTurn()
    emit(
      { type: 'tool_call', tool_id: 'call_1', content: 'kuncode' },
      { type: 'error', content: 'upstream failed' },
    )
    expect(tools()[0].execution_status).toBe('failed')
    expect(lastAssistant()?.status).toBe('failed')
    expect(lastAssistant()?.content).toBe('[ERROR] upstream failed')
  })

  it('keeps a completed tool intact when the turn fails later', () => {
    seedTurn()
    emit(
      { type: 'tool_call', tool_id: 'call_1', content: 'kuncode' },
      { type: 'tool_result', tool_id: 'call_1', content: 'ok' },
      { type: 'tool_call', tool_id: 'call_2', content: 'kuncode' },
      { type: 'error', content: 'second call failed' },
    )
    expect(tools().map((tool) => tool.execution_status)).toEqual(['completed', 'failed'])
  })
})
