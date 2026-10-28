import { describe, expect, it } from 'vitest'
import {
  extractMessageContent,
  finalizeTurnMessages,
  mergeThinking,
  projectHistoryMessages,
  resultStatus,
} from '../../src/stores/conversationProjection'
import type { Message } from '../../src/types'

describe('extractMessageContent', () => {
  it('returns an empty string for nullish content', () => {
    expect(extractMessageContent(null)).toBe('')
    expect(extractMessageContent(undefined)).toBe('')
  })

  it('coerces scalars', () => {
    expect(extractMessageContent('text')).toBe('text')
    expect(extractMessageContent(42)).toBe('42')
  })

  it('joins multi-part text blocks', () => {
    expect(extractMessageContent([
      { type: 'text', text: 'alpha' },
      { type: 'text', text: 'beta' },
    ])).toBe('alphabeta')
  })

  it('ignores data-only blocks so tool payloads never leak into chat text', () => {
    expect(extractMessageContent([{ type: 'data', data: { call_id: 'c1' } }])).toBe('')
  })

  it('unwraps object wrappers', () => {
    expect(extractMessageContent({ text: 'wrapped' })).toBe('wrapped')
    expect(extractMessageContent({ content: 'raw' })).toBe('raw')
  })
})

describe('resultStatus', () => {
  it('treats plain output as completed', () => {
    expect(resultStatus('all good')).toBe('completed')
  })

  it('treats an empty payload as failed', () => {
    expect(resultStatus('')).toBe('failed')
    expect(resultStatus('   \n  ')).toBe('failed')
  })

  it('detects errors and tracebacks', () => {
    expect(resultStatus('[error] boom')).toBe('failed')
    expect(resultStatus('Traceback (most recent call last):\n  File "x.py"')).toBe('failed')
  })

  it('prefers the latest signal when a failure was retried successfully', () => {
    expect(resultStatus('[error] transient\nCompleted successfully')).toBe('completed')
    expect(resultStatus('Traceback\nFile generated successfully')).toBe('completed')
  })

  it('keeps a trailing error as failed even if success appeared earlier', () => {
    expect(resultStatus('Completed successfully\n[error] cleanup failed')).toBe('failed')
  })

  it('treats cancellation as not successful', () => {
    expect(resultStatus('[cancelled] user interrupted')).toBe('failed')
  })

  it('decodes JSON envelopes', () => {
    expect(resultStatus('[{"text":"done"}]')).toBe('completed')
    expect(resultStatus('{"output":"[error] nope"}')).toBe('failed')
  })
})

describe('mergeThinking', () => {
  it('initializes from nothing', () => {
    expect(mergeThinking(undefined, 'thinking')).toBe('thinking')
  })

  it('replaces a cumulative snapshot instead of duplicating it', () => {
    expect(mergeThinking('step one', 'step one and two')).toBe('step one and two')
  })

  it('ignores a shorter snapshot already contained in the current text', () => {
    expect(mergeThinking('step one and two', 'step one')).toBe('step one and two')
  })

  it('replaces only the active phase of a multi-phase block', () => {
    expect(mergeThinking('phase one\n\nphase two', 'phase two continues'))
      .toBe('phase one\n\nphase two continues')
  })

  it('appends a genuinely new phase', () => {
    expect(mergeThinking('phase one', 'phase two')).toBe('phase one\n\nphase two')
  })

  it('strips model-specific thinking terminators', () => {
    expect(mergeThinking(undefined, 'reasoning<|end_of_thinking|>')).toBe('reasoning')
    expect(mergeThinking(undefined, 'reasoning<｜end▁of▁thinking｜>')).toBe('reasoning')
  })

  it('keeps the current value when the incoming chunk is empty', () => {
    expect(mergeThinking('kept', '   ')).toBe('kept')
  })
})

describe('projectHistoryMessages', () => {
  const history = [
    { role: 'user', type: 'message', content: [{ type: 'text', text: 'count files' }] },
    { role: 'assistant', type: 'message', content: [{ type: 'text', text: 'looking' }] },
    { role: 'assistant', type: 'reasoning', content: [{ type: 'text', text: 'need a listing' }] },
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
    { role: 'assistant', type: 'message', content: [{ type: 'text', text: 'there are 3 files' }] },
  ]

  it('collapses one user turn into a single assistant message', () => {
    const projected = projectHistoryMessages(history)
    expect(projected).toHaveLength(2)
    expect(projected[0]).toMatchObject({ role: 'user', content: 'count files' })
    expect(projected[1].role).toBe('assistant')
  })

  it('keeps only the last assistant text as the deliverable', () => {
    const assistant = projectHistoryMessages(history)[1]
    expect(assistant.content).toBe('there are 3 files')
    expect(assistant.thinking).toBe('need a listing')
  })

  it('attaches tool output by call_id', () => {
    const [tool] = projectHistoryMessages(history)[1].tool_calls ?? []
    expect(tool).toMatchObject({
      id: 'call_1',
      name: 'execute_python_code',
      arguments: '{"code":"ls"}',
      result: '12K',
      execution_status: 'completed',
    })
  })

  it('keeps the raw output payload in result', () => {
    const [tool] = projectHistoryMessages([
      { role: 'user', type: 'message', content: [{ type: 'text', text: 'go' }] },
      {
        role: 'assistant',
        type: 'plugin_call',
        content: [{ type: 'data', data: { call_id: 'call_1', name: 'kuncode', arguments: {} } }],
      },
      {
        role: 'assistant',
        type: 'plugin_call_output',
        content: [{ type: 'data', data: { call_id: 'call_1', output: '[{"text":"raw"}]' } }],
      },
    ])[1].tool_calls ?? []
    // The status classifier decodes JSON envelopes, but the rendered result
    // keeps the raw payload so history and live cards show the same bytes.
    expect(tool).toMatchObject({ result: '[{"text":"raw"}]', execution_status: 'completed' })
  })

  it('leaves a tool without output in running state', () => {
    const pending = projectHistoryMessages([
      { role: 'user', type: 'message', content: [{ type: 'text', text: 'go' }] },
      {
        role: 'assistant',
        type: 'plugin_call',
        content: [{ type: 'data', data: { call_id: 'call_x', name: 'kuncode', arguments: {} } }],
      },
    ])
    expect(pending[1].tool_calls?.[0].execution_status).toBe('running')
  })

  it('starts a new assistant message per user turn', () => {
    const projected = projectHistoryMessages([
      { role: 'user', type: 'message', content: [{ type: 'text', text: 'first' }] },
      { role: 'assistant', type: 'message', content: [{ type: 'text', text: 'answer one' }] },
      { role: 'user', type: 'message', content: [{ type: 'text', text: 'second' }] },
      { role: 'assistant', type: 'message', content: [{ type: 'text', text: 'answer two' }] },
    ])
    expect(projected.filter((message) => message.role === 'assistant').map((message) => message.content))
      .toEqual(['answer one', 'answer two'])
  })

  it('never surfaces raw tool output records', () => {
    const projected = projectHistoryMessages(history)
    expect(projected.some((message) => message.content.includes('12K'))).toBe(false)
  })

  it('drops assistant shells with no text, thinking or tools', () => {
    const projected = projectHistoryMessages([
      { role: 'user', type: 'message', content: [{ type: 'text', text: 'hi' }] },
      { role: 'assistant', type: 'message', content: [] },
    ])
    expect(projected).toHaveLength(1)
  })
})

describe('finalizeTurnMessages', () => {
  const runningTool = {
    role: 'assistant' as const,
    content: '',
    turnId: 'turn-1',
    status: 'running' as const,
    tool_calls: [{ id: 'call_1', name: 'kuncode', arguments: '{}', execution_status: 'running' as const }],
  }

  it('never leaves a tool running after a completed turn', () => {
    const [assistant] = finalizeTurnMessages([runningTool], 'turn-1', 'completed', '[ERROR] incomplete')
    expect(assistant.status).toBe('completed')
    expect(assistant.tool_calls?.[0].execution_status).toBe('failed')
    expect(assistant.tool_calls?.[0].result).toBe('[ERROR] incomplete')
  })

  it('marks pending tools as cancelled when the turn was interrupted', () => {
    const [assistant] = finalizeTurnMessages([runningTool], 'turn-1', 'cancelled', '[CANCELLED] stopped')
    expect(assistant.status).toBe('cancelled')
    expect(assistant.tool_calls?.[0].execution_status).toBe('cancelled')
    expect(assistant.content).toBe('[CANCELLED] stopped')
  })

  it('leaves other turns untouched', () => {
    const other = { ...runningTool, turnId: 'turn-2' }
    const [untouched] = finalizeTurnMessages([other], 'turn-1', 'completed', 'fallback')
    expect(untouched).toBe(other)
  })

  it('never rewrites a tool that already reported a terminal state', () => {
    const finished = {
      ...runningTool,
      tool_calls: [{
        id: 'call_1',
        name: 'kuncode',
        arguments: '{}',
        result: 'ok',
        execution_status: 'completed' as const,
      }],
    }
    const [assistant] = finalizeTurnMessages([finished], 'turn-1', 'completed', 'fallback')
    expect(assistant.tool_calls?.[0]).toMatchObject({ execution_status: 'completed', result: 'ok' })
  })

  it('skips idle messages when there is no active turn', () => {
    const idle: Message = { role: 'assistant', content: 'done', turnId: 'turn-9', status: 'completed' }
    const [result] = finalizeTurnMessages([idle], null, 'failed', 'fallback')
    expect(result).toBe(idle)
  })

  it('resolves pending tools even without a turn id', () => {
    const orphan = { ...runningTool, turnId: undefined }
    const [assistant] = finalizeTurnMessages([orphan], null, 'failed', '[ERROR] record incomplete')
    expect(assistant.tool_calls?.[0].execution_status).toBe('failed')
  })

  it('keeps existing assistant text when finalizing', () => {
    const withText = { ...runningTool, content: 'partial answer' }
    const [assistant] = finalizeTurnMessages([withText], 'turn-1', 'failed', '[ERROR] boom')
    expect(assistant.content).toBe('partial answer')
  })
})
