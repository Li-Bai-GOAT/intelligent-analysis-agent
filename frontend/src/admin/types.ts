export type AdminSection = 'overview' | 'knowledge' | 'prompt' | 'agents' | 'skills' | 'mcps'

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

export type SkillPermissionValue = 'allow' | 'deny' | 'ask'

export interface SkillAgentPermission {
  agent_id: number
  agent_name: string
  permission: SkillPermissionValue
}

export interface SkillConfig {
  id: number
  name: string
  description: string
  metadata: Record<string, unknown>
  enabled: boolean
  created_at: string
  updated_at: string
  agent_permissions: SkillAgentPermission[]
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

