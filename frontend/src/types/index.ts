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
}

export interface StreamData {
  type: 'text' | 'thinking' | 'tool_call' | 'tool_result' | 'end' | 'error' | 'status' | 'plan' | 'kuncode_preview' | 'plan_preview' | 'user_input_request' | 'context_update'
  content?: string
  tool_id?: string
  tool_name?: string
  tool_arguments?: string
  result?: string
  call_id?: string
  data?: unknown
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

export interface Knowledge {
  id: number
  title: string
  category: string
  content: string
  created_at?: string
  updated_at?: string
}

export interface AgentConfig {
  id: number
  name: string
  description: string
  mode: string
  enabled: boolean
  tools: string[]
  permissions: Record<string, string>
  temperature?: number
  max_steps?: number
  hidden?: boolean
  content?: string
}

export interface SkillConfig {
  id: number
  name: string
  description: string
  enabled: boolean
  permissions?: Record<string, Record<string, string>>
}

export interface McpConfig {
  id: number
  name: string
  type: 'remote' | 'local'
  url?: string
  command?: string
  headers?: Record<string, string>
  environment?: Record<string, string>
  enabled: boolean
}
