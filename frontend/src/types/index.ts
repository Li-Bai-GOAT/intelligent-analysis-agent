export interface User {
  id: number
  username: string
  is_admin: boolean
}

export interface Session {
  session_id: string
  name?: string
  created_at: string
  updated_at?: string
}

export interface Message {
  role: 'user' | 'assistant' | 'system'
  content: string
  timestamp?: string
  files?: UploadedFile[]
  tool_calls?: ToolCall[]
  thinking?: string
  turnId?: string
  status?: ToolExecutionStatus
}

export interface UploadedFile {
  file_id: string
  filename: string
  size: number
  mime_type?: string
}

export interface ToolCall {
  id: string
  name: string
  arguments: string
  result?: string
  execution_status?: ToolExecutionStatus
}

export type ToolExecutionStatus = 'running' | 'completed' | 'failed' | 'cancelled'

export interface StreamData {
  type: 'text' | 'thinking' | 'tool_call' | 'tool_result' | 'end' | 'error' | 'status' | 'plan' | 'kuncode_preview' | 'plan_preview' | 'user_input_request' | 'user_input_required' | 'context_update' | 'auto_continue' | 'interrupted' | 'step_complete'
  content?: string
  tool_id?: string
  tool_name?: string
  tool_arguments?: string
  result?: string
  call_id?: string
  data?: unknown
  input?: unknown
  context_info?: { usage_percent: number; estimated_tokens: number; max_tokens: number }
  event_id?: string
  task_id?: string
  session_id?: string
  phase?: 'started' | 'progress' | 'completed' | 'failed' | 'cancelled'
  execution_status?: 'running' | 'completed' | 'failed' | 'cancelled'
  generated_files?: string[]
}

export interface Plan {
  goal: string
  subtasks: PlanSubtask[]
}

export interface PlanSubtask {
  title: string
  description: string
  status: 'pending' | 'in_progress' | 'completed' | 'failed'
}

export interface FileItem {
  name: string
  path: string
  is_dir: boolean
  size?: number
  modified?: string
}
