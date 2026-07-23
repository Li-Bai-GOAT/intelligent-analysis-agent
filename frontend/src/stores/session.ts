import { create } from 'zustand'
import { Api } from '../api/client'
import type { Session, Message, StreamData } from '../types'
import { useUiStore } from './ui'
import { extractMessageContent, finalizeTurnMessages, mergeThinking, projectHistoryMessages } from './conversationProjection'

function updateTurn(
  messages: Message[],
  turnId: string | null,
  updater: (message: Message) => Message,
): Message[] {
  const next = [...messages]
  let index = turnId ? next.findIndex((message) => message.role === 'assistant' && message.turnId === turnId) : -1
  if (index < 0) {
    for (let i = next.length - 1; i >= 0; i--) {
      if (next[i].role === 'user') break
      if (next[i].role === 'assistant') {
        index = i
        break
      }
    }
  }
  if (index < 0) {
    next.push(updater({ role: 'assistant', content: '', turnId: turnId || undefined, status: 'running' }))
  } else {
    next[index] = updater(next[index])
  }
  return next
}

interface StreamState {
  activeTurnId: string | null
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
  sendMessage: (content: string, executionMode?: 'auto' | 'kuncode') => Promise<boolean>
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
    activeTurnId: null,
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
        activeTurnId: null,
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
      let messages = projectHistoryMessages(rawMessages)

      set({ messages, contextInfo: detail.context_info || null })

      // 检查活跃任务（断点续传）
      const taskInfo = await Api.getSessionTask(sessionId)
      if (get()._selectVersion !== version) return

      if (taskInfo.has_active_task && taskInfo.task_id) {
        const activeTaskId = taskInfo.task_id
        const lastAssistant = [...messages].reverse().find((message) => message.role === 'assistant')
        if (lastAssistant) {
          messages = messages.map((message) => message === lastAssistant
            ? { ...message, turnId: activeTaskId, status: 'running' }
            : message)
        } else {
          messages = [...messages, { role: 'assistant', content: '', turnId: activeTaskId, status: 'running' }]
        }
        set((current) => ({
          messages,
          isStreaming: true,
          streamState: { ...current.streamState, activeTurnId: activeTaskId },
        }))
        const eventSource = Api.streamTask(
          activeTaskId,
          (data) => get().handleStreamData(data as unknown as StreamData),
          (data) => {
            if (data.type === 'error' && get().isStreaming) {
              get().handleStreamData(data as unknown as StreamData)
            }
            get().disconnectStream()
          },
        )
        set({ currentEventSource: eventSource })
      } else {
        messages = finalizeTurnMessages(messages, null, 'failed', '[ERROR] 执行记录不完整，任务已结束。')
        set({ messages })
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
    if (!state.currentSession || state.isStreaming) return false

    let fileIds: string[] = []
    let uploadedFiles: Awaited<ReturnType<typeof Api.uploadFiles>> = []
    if (state.pendingFiles.length > 0) {
      try {
        uploadedFiles = await Api.uploadFiles(state.currentSession, state.pendingFiles)
        fileIds = uploadedFiles.map((file) => String(file.id))
      } catch (err) {
        console.error('Upload error:', err)
        set((current) => ({
          messages: [
            ...current.messages,
            { role: 'system', content: err instanceof Error ? `文件上传失败：${err.message}` : '文件上传失败，请重试。' },
          ],
        }))
        return false
      }
    }

    const userMsg: Message = {
      role: 'user',
      content,
      files: uploadedFiles.map((file) => ({
        file_id: String(file.id),
        filename: file.original_name || file.filename,
        size: file.size,
        mime_type: file.content_type || undefined,
      })),
    }

    try {
      set({ isStreaming: true })
      const result = await Api.submitTask(state.currentSession, content, fileIds, executionMode)
      set((current) => ({
        messages: [
          ...current.messages,
          userMsg,
          { role: 'assistant', content: '', turnId: result.task_id, status: 'running' },
        ],
        pendingFiles: [],
        uploadedFileIds: fileIds,
        streamState: {
          activeTurnId: result.task_id,
          thinkingBlock: null,
          assistantEl: null,
          currentToolId: null,
          currentToolName: null,
          seenToolIds: new Set(),
          terminalCommands: new Set(),
        },
      }))
      console.log('[SessionStore] task submitted:', result.task_id)
      const eventSource = Api.streamTask(
        result.task_id,
        (data) => get().handleStreamData(data as unknown as StreamData),
        (data) => {
          if (data.type === 'error' && get().isStreaming) {
            get().handleStreamData(data as unknown as StreamData)
          }
        },
      )
      set({ currentEventSource: eventSource })
      return true
    } catch (err) {
      console.error('Send error:', err)
      set((current) => ({
        isStreaming: false,
        messages: [
          ...current.messages,
          { role: 'system', content: err instanceof Error ? `消息发送失败：${err.message}` : '消息发送失败，请重试。' },
        ],
      }))
      return false
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

    switch (data.type) {
      case 'text': {
        const content = (data.content || '').replace(/<｜DSML｜[\s\S]*$/g, '').trim()
        if (!content) break
        set((current) => ({
          messages: updateTurn(current.messages, current.streamState.activeTurnId, (message) => ({
            ...message,
            content,
            status: 'running',
          })),
        }))
        if (data.generated_files && data.generated_files.length > 0) {
          useUiStore.getState().setRightTab('files')
        }
        break
      }
      case 'thinking': {
        const thinkingContent = (data.content || '').replace(/<｜end▁of▁thinking｜>/g, '').trim()
        if (!thinkingContent) break
        set((current) => ({
          messages: updateTurn(current.messages, current.streamState.activeTurnId, (message) => ({
            ...message,
            thinking: mergeThinking(message.thinking, thinkingContent),
            status: 'running',
          })),
        }))
        break
      }
      case 'tool_call': {
        const toolId = data.tool_id || ''
        const toolName = data.content || data.tool_name || ''
        const rawInput = data.input ?? data.tool_arguments
        const toolInput = typeof rawInput === 'object' && rawInput !== null
          ? JSON.stringify(rawInput)
          : String(rawInput || '')
        set((current) => {
          const seen = new Set(current.streamState.seenToolIds)
          seen.add(toolId)
          return {
            messages: updateTurn(current.messages, current.streamState.activeTurnId, (message) => {
              const toolCalls = [...(message.tool_calls || [])]
              const index = toolCalls.findIndex((tool) => tool.id === toolId)
              const nextTool = {
                id: toolId,
                name: toolName,
                arguments: toolInput,
                execution_status: 'running' as const,
              }
              if (index >= 0) toolCalls[index] = { ...toolCalls[index], ...nextTool }
              else toolCalls.push(nextTool)
              return { ...message, status: 'running', tool_calls: toolCalls }
            }),
            streamState: {
              ...current.streamState,
              seenToolIds: seen,
              currentToolId: toolId,
              currentToolName: toolName,
            },
          }
        })
        break
      }
      case 'tool_result': {
        const resultText = extractMessageContent(data.content ?? data.result ?? '')
        const executionStatus = data.execution_status || (
          resultText.toLowerCase().includes('[error]') ? 'failed' : 'completed'
        )
        set((current) => ({
          messages: updateTurn(current.messages, current.streamState.activeTurnId, (message) => ({
            ...message,
            tool_calls: message.tool_calls?.map((tool) => tool.id === data.tool_id
              ? { ...tool, result: resultText, execution_status: executionStatus }
              : tool),
          })),
        }))
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
        set((current) => ({
          isStreaming: false,
          currentEventSource: null,
          messages: finalizeTurnMessages(
            current.messages,
            current.streamState.activeTurnId,
            'completed',
            '[ERROR] 工具调用未返回完整结果。',
          ),
          streamState: { ...current.streamState, activeTurnId: null },
        }))
        break
      case 'error':
        set((current) => {
          const content = extractMessageContent(data.content || '执行失败')
          const msgs = finalizeTurnMessages(
            current.messages,
            current.streamState.activeTurnId,
            'failed',
            `[ERROR] ${content}`,
          )
          return {
            isStreaming: false,
            currentEventSource: null,
            messages: msgs,
            streamState: { ...current.streamState, activeTurnId: null },
          }
        })
        break
      case 'interrupted':
        set((current) => {
          const content = extractMessageContent(data.content || '用户中断了执行')
          return {
            isStreaming: false,
            currentEventSource: null,
            messages: finalizeTurnMessages(
              current.messages,
              current.streamState.activeTurnId,
              'cancelled',
              `[CANCELLED] ${content}`,
            ),
            streamState: { ...current.streamState, activeTurnId: null },
          }
        })
        break
    }
  },

  clearPendingPreview: () => set({ pendingPreview: null }),
}))
