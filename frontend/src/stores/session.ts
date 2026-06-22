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

interface SessionState {
  sessions: Session[]
  currentSession: string | null
  messages: Message[]
  pendingFiles: File[]
  uploadedFileIds: string[]
  contextInfo: { usage_percent: number; estimated_tokens: number; max_tokens: number } | null
  isStreaming: boolean
  streamState: StreamState
  currentEventSource: EventSource | null
  _selectVersion: number

  loadSessions: () => Promise<void>
  selectSession: (sessionId: string) => Promise<void>
  createSession: () => Promise<void>
  deleteSession: (sessionId: string) => Promise<void>
  sendMessage: (content: string) => Promise<void>
  addPendingFiles: (files: File[]) => void
  removePendingFile: (index: number) => void
  clearPendingFiles: () => void
  handleStreamData: (data: StreamData) => void
  disconnectStream: () => void
  addMessage: (msg: Message) => void
  updateLastAssistant: (content: string) => void
  appendToLastAssistant: (content: string) => void
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

      const rawMessages = detail.messages || []
      const messages: Message[] = rawMessages
        .map((m: Record<string, unknown>) => {
          const role = String(m.role || 'user')
          const msgType = String(m.msg_type || 'message')
          const content = extractContent(m.content)

          // 跳过空消息
          if (!content && msgType !== 'reasoning') return null

          const msg: Message = {
            role: role as Message['role'],
            content,
          }

          // reasoning 消息作为 thinking 块
          if (msgType === 'reasoning' && role === 'assistant') {
            msg.thinking = content
            msg.content = ''
          }

          return msg
        })
        .filter(Boolean) as Message[]

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

  sendMessage: async (content: string) => {
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
      const result = await Api.submitTask(state.currentSession, content, fileIds)
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
        const toolId = data.tool_id || ''
        const seen = new Set(state.streamState.seenToolIds)
        if (seen.has(toolId)) break
        seen.add(toolId)

        const msgs = [...state.messages]
        const last = msgs[msgs.length - 1]
        if (last && last.role === 'assistant') {
          const toolCalls = [...(last.tool_calls || [])]
          toolCalls.push({
            id: toolId,
            name: data.tool_name || '',
            arguments: data.tool_arguments || '',
          })
          msgs[msgs.length - 1] = { ...last, tool_calls: toolCalls }
        }
        set({
          messages: msgs,
          streamState: { ...state.streamState, seenToolIds: seen, currentToolId: toolId, currentToolName: data.tool_name || '' },
        })
        break
      }
      case 'tool_result': {
        const msgs = [...state.messages]
        const last = msgs[msgs.length - 1]
        if (last && last.role === 'assistant' && last.tool_calls) {
          const toolCalls = last.tool_calls.map((tc) =>
            tc.id === data.call_id ? { ...tc, result: data.result || data.content || '' } : tc,
          )
          msgs[msgs.length - 1] = { ...last, tool_calls: toolCalls }
        }
        set({ messages: msgs })
        break
      }
      case 'context_update': {
        set({ contextInfo: data.data as SessionState['contextInfo'] })
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
}))
