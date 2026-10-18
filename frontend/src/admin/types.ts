export type AdminSection = 'overview' | 'knowledge' | 'prompt' | 'skills' | 'mcps' | 'model-audits'

export interface ReadyStatus {
  status: 'ok' | 'unavailable'
  dependencies: Record<string, 'ok' | 'unavailable' | 'degraded' | 'disabled'>
}

export interface KnowledgeItem {
  id: string
  title: string
  content: string
  category: string
  metadata: Record<string, unknown> | null
  created_at: string
  updated_at: string
}

export interface KnowledgeInput {
  title: string
  content: string
  category: string
  metadata?: Record<string, unknown> | null
}

export interface PaginatedResponse<T> {
  items: T[]
  total: number
  limit: number
  offset: number
}

export interface ModelAuditItem {
  event: string
  request_id: string
  trace_id?: string
  parent_task_id?: string
  session_id?: string
  source?: string
  entrypoint?: string
  provider?: string
  requested_model?: string
  actual_model?: string
  attempt?: number
  stream?: boolean
  started_at?: string
  finished_at?: string
  latency_ms?: number
  prompt_tokens?: number
  completion_tokens?: number
  total_tokens?: number
  usage_source?: string
  result?: string
  error_type?: string
  sandbox_id?: string
  execution_id?: string
}

export interface ModelAuditResponse {
  items: ModelAuditItem[]
  total: number
  limit: number
  offset: number
}

export interface SystemPrompt {
  name: string
  title: string
  content: string
  updated_at: string | null
}

export type AgentMode = 'primary' | 'subagent' | 'all'

export interface AgentConfig {
  id: number
  name: string
  description: string
  mode: AgentMode
  tools: Record<string, unknown>
  permission: Record<string, unknown>
  temperature: number | null
  max_steps: number | null
  hidden: boolean
  content: string
  enabled: boolean
  created_at: string
  updated_at: string
}

export interface AgentCreateInput {
  name: string
  description: string
  mode: AgentMode
  tools: Record<string, unknown>
  permission: Record<string, unknown>
  temperature: number | null
  max_steps: number | null
  hidden: boolean
  content: string
  enabled: boolean
}

export type AgentUpdateInput = Omit<AgentCreateInput, 'name'>

export interface SkillConfig {
  id: number
  name: string
  description: string
  metadata: Record<string, unknown>
  enabled: boolean
  created_at: string
  updated_at: string
}

export interface SkillFileNode {
  name: string
  path: string
  type: 'directory' | 'file'
  size?: number
  children?: SkillFileNode[]
}

export interface SkillFileTree {
  name: string
  children: SkillFileNode[]
}

export interface SkillFileContent {
  path: string
  content: string | null
  type: 'text' | 'binary'
  size?: number
}

export type McpType = 'local' | 'remote'

export interface McpConfig {
  id: number
  name: string
  mcp_type: McpType
  url: string | null
  command: string[]
  headers: Record<string, string>
  environment: Record<string, string>
  enabled: boolean
  created_at: string
  updated_at: string
}

export interface McpCreateInput {
  name: string
  mcp_type: McpType
  url: string | null
  command: string[]
  headers: Record<string, string>
  environment: Record<string, string>
  enabled: boolean
}

export type McpUpdateInput = Omit<McpCreateInput, 'name'>
