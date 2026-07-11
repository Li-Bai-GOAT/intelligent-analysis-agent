import { create } from 'zustand'
import { Api } from '../api/client'
import type { Session, Message, StreamData } from '../types'

function extractContent(content: unknown): string {
  if (content === null || content === undefined) return ''
  if (typeof content === 'string') return content
  if (typeof content === 'number') return String(content)
  if (Array.isArray(content)) {
    return content
      .map((item: unknown) => {
        if (typeof item === 'string') return item
        if (item && typeof item === 'object') {
          const obj = item as Record<string, unknown>
          if ('text' in obj && typeof obj.text === 'string') return obj.text
          if ('content' in obj && typeof obj.content === 'string') return obj.content
        }
        return ''
      })
      .filter(Boolean)
      .join('')
  }
  if (typeof content === 'object') {
    const obj = content as Record<string, unknown>
    if ('text' in obj) return String(obj.text)
    if ('content' in obj) return String(obj.content)
  }
  return String(content)
}

interface StreamState {
  thinkingBlock: string | null
  assistantEl: string | null
  currentToolId: string | null
  currentToolName: string | null
  seenToolIds: Set<string>
  terminalCommands: Set<string>
}

interface StreamConnection {
  close: () => void
}

export interface PendingPreview {
  type: 'kuncode_preview' | 'plan_preview' | 'user_input_request' | 'user_input_required' | 'auto_continue'
  preview_id: string
  prompt?: string
  plan?: unknown
  agent?: string
  remaining_seconds?: number
  task_id?: string
  [key: string]: unknown
}

interface SessionState {
  sessions: Session[]
  currentSession: string | null
  messages: Message[]
  pendingFiles: File[]
  uploadedFileIds: string[]
  contextInfo: { usage_percent: number; estimated_tokens: number; max_tokens: number } | null
  isStreaming: boolean
  streamState: StreamState
  currentEventSource: StreamConnection | null
  _selectVersion: number
  pendingPreview: PendingPreview | null

  loadSessions: () => Promise<void>
  selectSession: (sessionId: string) => Promise<void>
  createSession: () => Promise<void>
  deleteSession: (sessionId: string) => Promise<void>
  sendMessage: (content: string, executionMode?: 'auto' | 'kuncode') => Promise<void>
  addPendingFiles: (files: File[]) => void
  removePendingFile: (index: number) => void
  clearPendingFiles: () => void
  handleStreamData: (data: StreamData) => void
  disconnectStream: () => void
  addMessage: (msg: Message) => void
  updateLastAssistant: (content: string) => void
  appendToLastAssistant: (content: string) => void
  clearPendingPreview: () => void
}

export const useSessionStore = create<SessionState>((set, get) => ({
  sessions: [],
  currentSession: null,
  messages: [],
  pendingFiles: [],
  uploadedFileIds: [],
  contextInfo: null,
  isStreaming: false,
  streamState: {
    thinkingBlock: null,
    assistantEl: null,
    currentToolId: null,
    currentToolName: null,
    seenToolIds: new Set(),
    terminalCommands: new Set(),
  },
  currentEventSource: null,
  _selectVersion: 0,
  pendingPreview: null,

  loadSessions: async () => {
    try {
      const sessions = await Api.listSessions()
      set({ sessions })
    } catch (err) {
      console.error('Load sessions error:', err)
    }
  },

  selectSession: async (sessionId: string) => {
    const state = get()
    state.disconnectStream()

    const version = state._selectVersion + 1
    set({
      _selectVersion: version,
      currentSession: sessionId,
      messages: [],
      isStreaming: false,
      pendingPreview: null,
      streamState: {
        thinkingBlock: null,
        assistantEl: null,
        currentToolId: null,
        currentToolName: null,
        seenToolIds: new Set(),
        terminalCommands: new Set(),
      },
    })

    try {
      const detail = await Api.getSession(sessionId)

      // 如果已有更新的 selectSession 调用，丢弃这次的结果
      if (get()._selectVersion !== version) return

      const rawMessages = (detail.messages || []) as unknown as Record<string, unknown>[]

      // 辅助函数：从 content 数组中提取 data 字段
      const extractContentData = (content: unknown): Record<string, unknown> | null => {
        if (Array.isArray(content) && content.length > 0) {
          const first = content[0] as Record<string, unknown>
          if (first && first.data) return first.data as Record<string, unknown>
        }
        return null
      }

      // 第一遍：收集所有 plugin_call_output 结果
      const toolResults = new Map<string, string>()
      for (const m of rawMessages) {
        const msgType = String(m.type || m.msg_type || 'message')
        if (msgType === 'plugin_call_output' || msgType === 'plugin_call_result') {
          const data = extractContentData(m.content)
          const callId = data ? String(data.call_id || '') : String(m.call_id || '')
          const output = data ? String(data.output || '') : extractContent(m.content)
          if (callId && output) {
            toolResults.set(callId, output)
          }
        }
      }

      // 第二遍：构建消息列表
      const messages: Message[] = []
      const seenToolIds = new Set<string>()

      for (const m of rawMessages) {
        const role = String(m.role || 'user')
        const msgType = String(m.type || m.msg_type || 'message')
        const content = extractContent(m.content)

        // 跳过 plugin_call_output（已合并到 tool_calls 中）
        if (msgType === 'plugin_call_output' || msgType === 'plugin_call_result') continue

        // plugin_call 消息 -> 提取 tool_calls
        if (msgType === 'plugin_call') {
          // 后端结构: content = [{ data: { name, call_id, arguments } }]
          const data = extractContentData(m.content)
          const toolId = data ? String(data.call_id || '') : String(m.call_id || '')
          const toolName = data ? String(data.name || '') : String(m.tool_name || m.name || '')
          const rawToolInput = data ? (data.arguments ?? data.code ?? '') : (m.tool_input ?? content ?? '')
          const toolInput = typeof rawToolInput === 'object' && rawToolInput !== null
            ? JSON.stringify(rawToolInput)
            : String(rawToolInput)
          if (toolId && !seenToolIds.has(toolId)) {
            seenToolIds.add(toolId)
            // 找到上一条 assistant 消息，添加 tool_calls
            const lastMsg = messages[messages.length - 1]
            if (lastMsg && lastMsg.role === 'assistant') {
              if (!Array.isArray(lastMsg.tool_calls)) lastMsg.tool_calls = []
              lastMsg.tool_calls.push({
                id: toolId,
                name: toolName,
                arguments: toolInput,
                result: toolResults.get(toolId) || '',
              })
            } else {
              // 没有前置 assistant 消息，创建一个空的
              messages.push({
                role: 'assistant',
                content: '',
                tool_calls: [{
                  id: toolId,
                  name: toolName,
                  arguments: toolInput,
                  result: toolResults.get(toolId) || '',
                }],
              })
            }
          }
          continue
        }

        // 跳过空消息
        if (!content && msgType !== 'reasoning') continue

        const msg: Message = {
          role: role as Message['role'],
          content,
        }

        // reasoning 消息作为 thinking 块
        if (msgType === 'reasoning' && role === 'assistant') {
          msg.thinking = content
          msg.content = ''
        }

        messages.push(msg)
      }

      set({ messages, contextInfo: detail.context_info || null })

      // 检查活跃任务（断点续传）
      const taskInfo = await Api.getSessionTask(sessionId)
      if (get()._selectVersion !== version) return

      if (taskInfo.has_active_task && taskInfo.task_id) {
        set({ isStreaming: true })
        const eventSource = Api.streamTask(
          taskInfo.task_id,
          (data) => get().handleStreamData(data as unknown as StreamData),
          () => {
            get().disconnectStream()
            set({ isStreaming: false })
          },
        )
        set({ currentEventSource: eventSource })
      }
    } catch (err) {
      console.error('Load session error:', err)
    }
  },

  createSession: async () => {
    try {
      const data = await Api.createSession()
      await get().loadSessions()
      await get().selectSession(data.session_id)
    } catch (err) {
      console.error('Create session error:', err)
    }
  },

  deleteSession: async (sessionId: string) => {
    try {
      await Api.deleteSession(sessionId)
      const state = get()
      if (state.currentSession === sessionId) {
        set({ currentSession: null, messages: [] })
      }
      await state.loadSessions()
    } catch (err) {
      console.error('Delete session error:', err)
    }
  },

  sendMessage: async (content: string, executionMode = 'auto') => {
    const state = get()
    if (!state.currentSession || state.isStreaming) return

    let fileIds: string[] = []
    if (state.pendingFiles.length > 0) {
      try {
        const result = await Api.uploadFiles(state.currentSession, state.pendingFiles)
        fileIds = result.file_ids || []
      } catch (err) {
        console.error('Upload error:', err)
      }
    }

    const userMsg: Message = {
      role: 'user',
      content,
      files: state.pendingFiles.map((f) => ({
        file_id: '',
        filename: f.name,
        size: f.size,
      })),
    }
    set({ messages: [...state.messages, userMsg], pendingFiles: [], uploadedFileIds: fileIds })

    try {
      set({ isStreaming: true })
      const result = await Api.submitTask(state.currentSession, content, fileIds, executionMode)
      console.log('[SessionStore] task submitted:', result.task_id)
      const eventSource = Api.streamTask(
        result.task_id,
        (data) => get().handleStreamData(data as unknown as StreamData),
        () => set({ isStreaming: false }),
      )
      set({ currentEventSource: eventSource })
    } catch (err) {
      console.error('Send error:', err)
      set({ isStreaming: false })
    }
  },

  addPendingFiles: (files) => set((s) => ({ pendingFiles: [...s.pendingFiles, ...files] })),
  removePendingFile: (index) => set((s) => ({ pendingFiles: s.pendingFiles.filter((_, i) => i !== index) })),
  clearPendingFiles: () => set({ pendingFiles: [] }),

  disconnectStream: () => {
    const { currentEventSource } = get()
    if (currentEventSource) {
      currentEventSource.close()
      set({ currentEventSource: null })
    }
  },

  addMessage: (msg) => set((s) => ({ messages: [...s.messages, msg] })),

  updateLastAssistant: (content) =>
    set((s) => {
      const msgs = [...s.messages]
      for (let i = msgs.length - 1; i >= 0; i--) {
        if (msgs[i].role === 'assistant') {
          msgs[i] = { ...msgs[i], content }
          break
        }
      }
      return { messages: msgs }
    }),

  appendToLastAssistant: (content) =>
    set((s) => {
      const msgs = [...s.messages]
      for (let i = msgs.length - 1; i >= 0; i--) {
        if (msgs[i].role === 'assistant') {
          msgs[i] = { ...msgs[i], content: msgs[i].content + content }
          break
        }
      }
      return { messages: msgs }
    }),

  handleStreamData: (data: StreamData) => {
    console.log('[StreamData]', data.type, (data.content || '').substring(0, 50))
    const state = get()

    switch (data.type) {
      case 'text': {
        const content = (data.content || '').replace(/<｜DSML｜[\s\S]*$/g, '').trim()
        if (!content) break
        const msgs = [...state.messages]
        const last = msgs[msgs.length - 1]
        if (last && last.role === 'assistant') {
          msgs[msgs.length - 1] = { ...last, content }
        } else {
          msgs.push({ role: 'assistant', content })
        }
        set({ messages: msgs })
        break
      }
      case 'thinking': {
        const thinkingContent = (data.content || '').replace(/<｜end▁of▁thinking｜>/g, '').trim()
        if (!thinkingContent) break
        const msgs = [...state.messages]
        const last = msgs[msgs.length - 1]
        if (last && last.role === 'assistant') {
          msgs[msgs.length - 1] = { ...last, thinking: thinkingContent }
        }
        set({ messages: msgs })
        break
      }
      case 'tool_call': {
        // 后端字段: content=tool_name, tool_id, input=tool_arguments
        const toolId = data.tool_id || ''
        const seen = new Set(state.streamState.seenToolIds)
        const toolName = data.content || data.tool_name || ''
        const rawInput = data.input ?? data.tool_arguments
        // 如果 input 是对象，序列化为 JSON 字符串；否则转为字符串
        const toolInput = typeof rawInput === 'object' && rawInput !== null
          ? JSON.stringify(rawInput)
          : String(rawInput || '')

        if (toolId && seen.has(toolId)) {
          const msgs = [...state.messages]
          for (let i = msgs.length - 1; i >= 0; i--) {
            const msg = msgs[i]
            if (!msg.tool_calls?.some((tc) => tc.id === toolId)) continue
            const toolCalls = msg.tool_calls.map((tc) =>
              tc.id === toolId ? { ...tc, name: toolName || tc.name, arguments: toolInput || tc.arguments } : tc,
            )
            msgs[i] = { ...msg, tool_calls: toolCalls }
            set({ messages: msgs })
            break
          }
          break
        }
        seen.add(toolId)

        const msgs = [...state.messages]
        const last = msgs[msgs.length - 1]
        if (last && last.role === 'assistant') {
          const toolCalls = [...(last.tool_calls || [])]
          toolCalls.push({
            id: toolId,
            name: toolName,
            arguments: toolInput,
          })
          msgs[msgs.length - 1] = { ...last, tool_calls: toolCalls }
        } else {
          // 如果还没有 assistant 消息，创建一个
          msgs.push({
            role: 'assistant',
            content: '',
            tool_calls: [{ id: toolId, name: toolName, arguments: toolInput }],
          })
        }
        set({
          messages: msgs,
          streamState: { ...state.streamState, seenToolIds: seen, currentToolId: toolId, currentToolName: toolName },
        })
        break
      }
      case 'tool_result': {
        // 后端字段: content=result_text, tool_id (匹配 tool_call 的 id)
        const msgs = [...state.messages]
        const resultText = extractContent(data.content ?? data.result ?? '')
        let updated = false
        for (let i = msgs.length - 1; i >= 0; i--) {
          const msg = msgs[i]
          if (!msg.tool_calls?.some((tc) => tc.id === data.tool_id)) continue
          const toolCalls = msg.tool_calls.map((tc) =>
            tc.id === data.tool_id ? { ...tc, result: resultText } : tc,
          )
          msgs[i] = { ...msg, tool_calls: toolCalls }
          updated = true
          break
        }
        if (updated) set({ messages: msgs })
        break
      }
      case 'context_update': {
        set({ contextInfo: (data.context_info || data.data) as SessionState['contextInfo'] })
        break
      }
      case 'step_complete': {
        if (data.context_info) set({ contextInfo: data.context_info })
        break
      }
      case 'kuncode_preview':
      case 'plan_preview':
      case 'user_input_request':
      case 'user_input_required':
      case 'auto_continue': {
        // Human-in-the-loop 预览确认事件
        set({ pendingPreview: data as unknown as PendingPreview })
        break
      }
      case 'status':
        break
      case 'end':
        set({ isStreaming: false })
        break
      case 'error':
        set({ isStreaming: false })
        if (data.content) {
          const msgs = [...state.messages]
          msgs.push({ role: 'system', content: data.content })
          set({ messages: msgs })
        }
        break
    }
  },

  clearPendingPreview: () => set({ pendingPreview: null }),
}))
