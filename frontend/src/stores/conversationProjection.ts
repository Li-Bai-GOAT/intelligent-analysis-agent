import type { Message, ToolCall, ToolExecutionStatus } from '../types'

export function extractMessageContent(content: unknown): string {
  if (content === null || content === undefined) return ''
  if (typeof content === 'string') return content
  if (typeof content === 'number') return String(content)
  if (Array.isArray(content)) {
    return content.map((item) => {
      if (typeof item === 'string') return item
      if (item && typeof item === 'object') {
        const value = item as Record<string, unknown>
        if (typeof value.text === 'string') return value.text
        if (typeof value.content === 'string') return value.content
      }
      return ''
    }).filter(Boolean).join('')
  }
  if (typeof content === 'object') {
    const value = content as Record<string, unknown>
    if ('text' in value) return String(value.text)
    if ('content' in value) return String(value.content)
  }
  return String(content)
}

function contentData(content: unknown): Record<string, unknown> | null {
  if (!Array.isArray(content)) return null
  for (const item of content) {
    if (item && typeof item === 'object') {
      const data = (item as Record<string, unknown>).data
      if (data && typeof data === 'object') return data as Record<string, unknown>
    }
  }
  return null
}

export function resultStatus(output: string): ToolExecutionStatus {
  let rendered = output
  try {
    const parsed = JSON.parse(output)
    if (Array.isArray(parsed)) {
      rendered = parsed.map((item) => {
        if (!item || typeof item !== 'object') return ''
        const value = item as Record<string, unknown>
        return String(value.text ?? value.content ?? '')
      }).join('')
    } else if (parsed && typeof parsed === 'object') {
      const value = parsed as Record<string, unknown>
      rendered = String(value.text ?? value.output ?? value.content ?? output)
    }
  } catch {
    // Plain text tool output needs no decoding.
  }

  const lower = rendered.toLowerCase().trim()
  if (!lower) return 'failed'
  const errorIndex = Math.max(
    lower.lastIndexOf('[error]'),
    lower.lastIndexOf('traceback'),
    lower.lastIndexOf('exception'),
  )
  const recoveryIndex = Math.max(
    lower.lastIndexOf('successfully'),
    lower.lastIndexOf('completed successfully'),
    lower.lastIndexOf('已成功'),
    lower.lastIndexOf('成功生成'),
    lower.lastIndexOf('已生成'),
    lower.lastIndexOf('核对通过'),
    lower.lastIndexOf('验证通过'),
    lower.lastIndexOf('输出成功'),
    lower.lastIndexOf('文件已输出'),
  )
  const lastLine = lower.split(/\r?\n/).map((line) => line.trim()).filter(Boolean).at(-1) || ''
  const legacyHint = lastLine.startsWith('[error] kuncode execution failed')

  if (legacyHint && recoveryIndex > lower.lastIndexOf('traceback')) return 'completed'
  if (lastLine.startsWith('[error]') || lastLine.startsWith('[cancelled]')) return 'failed'
  return errorIndex >= 0 && recoveryIndex < errorIndex ? 'failed' : 'completed'
}

export function mergeThinking(previous: string | undefined, next: string): string {
  const clean = next
    .replace(/<\uFF5Cend\u2581of\u2581thinking\uFF5C>/g, '')
    .replace(/<\|end_of_thinking\|>/g, '')
    .trim()
  const current = (previous || '').trim()

  if (!clean) return current
  if (!current || clean.startsWith(current)) return clean
  if (current.includes(clean)) return current

  // DeepSeek may stream a new reasoning phase as cumulative snapshots:
  // "刚才" -> "刚才K" -> "刚才KunCode...". Replace the active phase
  // in place so the expanded thinking block does not list every snapshot.
  const separator = '\n\n'
  const candidateStarts = [0]
  let separatorIndex = current.indexOf(separator)
  while (separatorIndex >= 0) {
    candidateStarts.push(separatorIndex + separator.length)
    separatorIndex = current.indexOf(separator, separatorIndex + separator.length)
  }

  // The active reasoning phase may contain its own blank paragraphs, so the
  // final separator is not necessarily the phase boundary. Find the longest
  // suffix that is a prefix of the new cumulative snapshot and replace that
  // suffix in place.
  let cumulativePhaseStart = -1
  let cumulativePhaseLength = -1
  for (const start of candidateStarts) {
    const candidate = current.slice(start)
    if (candidate && clean.startsWith(candidate) && candidate.length > cumulativePhaseLength) {
      cumulativePhaseStart = start
      cumulativePhaseLength = candidate.length
    }
  }
  if (cumulativePhaseStart >= 0) {
    return `${current.slice(0, cumulativePhaseStart)}${clean}`
  }

  return `${current}${separator}${clean}`
}

export function projectHistoryMessages(rawMessages: Record<string, unknown>[]): Message[] {
  const results = new Map<string, { output: string; status: ToolExecutionStatus }>()
  for (const raw of rawMessages) {
    const type = String(raw.type || raw.msg_type || 'message')
    if (type !== 'plugin_call_output' && type !== 'plugin_call_result') continue
    const data = contentData(raw.content)
    const callId = data ? String(data.call_id || '') : String(raw.call_id || '')
    const output = data ? String(data.output ?? '') : extractMessageContent(raw.content)
    if (callId) results.set(callId, { output, status: resultStatus(output) })
  }

  const projected: Message[] = []
  let assistantIndex = -1
  let turn = 0

  const ensureAssistant = (): Message => {
    if (assistantIndex >= 0) return projected[assistantIndex]
    const assistant: Message = {
      role: 'assistant',
      content: '',
      turnId: `history-${turn}`,
      status: 'completed',
    }
    projected.push(assistant)
    assistantIndex = projected.length - 1
    return assistant
  }

  for (const raw of rawMessages) {
    const role = String(raw.role || 'user')
    const type = String(raw.type || raw.msg_type || 'message')
    const content = extractMessageContent(raw.content)

    if (type === 'plugin_call_output' || type === 'plugin_call_result') continue

    if (role === 'user') {
      turn += 1
      assistantIndex = -1
      if (content) projected.push({ role: 'user', content })
      continue
    }

    if (type === 'plugin_call') {
      const data = contentData(raw.content)
      const id = data ? String(data.call_id || '') : String(raw.call_id || '')
      if (!id) continue
      const name = data ? String(data.name || '') : String(raw.tool_name || raw.name || '')
      const input = data ? (data.arguments ?? data.code ?? '') : (raw.tool_input ?? content)
      const existingResult = results.get(id)
      const tool: ToolCall = {
        id,
        name,
        arguments: typeof input === 'object' && input !== null ? JSON.stringify(input) : String(input || ''),
        ...(existingResult ? { result: existingResult.output, execution_status: existingResult.status } : { execution_status: 'running' as const }),
      }
      const assistant = ensureAssistant()
      const toolCalls = [...(assistant.tool_calls || [])]
      const existing = toolCalls.findIndex((item) => item.id === id)
      if (existing >= 0) toolCalls[existing] = { ...toolCalls[existing], ...tool }
      else toolCalls.push(tool)
      projected[assistantIndex] = { ...assistant, tool_calls: toolCalls }
      continue
    }

    if (role === 'assistant') {
      const assistant = ensureAssistant()
      if (type === 'reasoning') {
        projected[assistantIndex] = { ...assistant, thinking: mergeThinking(assistant.thinking, content) }
      } else if (content) {
        // AgentScope stores intermediate assistant texts as separate records.
        // The final non-empty text in the user turn is the chat deliverable.
        projected[assistantIndex] = { ...assistant, content }
      }
      continue
    }

    if (role === 'system' && content) projected.push({ role: 'system', content })
  }

  return projected.filter((message) => message.role !== 'assistant' || message.content || message.thinking || message.tool_calls?.length)
}

export function finalizeTurnMessages(
  messages: Message[],
  turnId: string | null,
  status: Exclude<ToolExecutionStatus, 'running'>,
  fallback: string,
): Message[] {
  return messages.map((message) => {
    if (message.role !== 'assistant' || (turnId && message.turnId !== turnId)) return message
    const hasPendingTool = message.tool_calls?.some((tool) => tool.execution_status === 'running' || tool.execution_status === undefined)
    if (!turnId && !hasPendingTool) return message
    const pendingStatus = status === 'completed' ? 'failed' : status
    const tool_calls = message.tool_calls?.map((tool) => tool.execution_status === 'running' || tool.execution_status === undefined
      ? { ...tool, result: tool.result ?? fallback, execution_status: pendingStatus }
      : tool)
    return {
      ...message,
      status,
      content: message.content || (status === 'completed' ? '' : fallback),
      tool_calls,
    }
  })
}
