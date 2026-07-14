import { Api } from './client'
import type {
  AgentConfig,
  AgentCreateInput,
  AgentUpdateInput,
  KnowledgeInput,
  KnowledgeItem,
  McpConfig,
  McpCreateInput,
  McpUpdateInput,
  PaginatedResponse,
  ReadyStatus,
  SkillConfig,
  SkillFileContent,
  SkillFileTree,
  SkillPermissionValue,
  SystemPrompt,
} from '../admin/types'

async function errorMessage(response: Response, fallback: string) {
  const body = await response.json().catch(() => null) as { detail?: string } | null
  return body?.detail || fallback
}

export class AdminApi {
  static async getReadyStatus(): Promise<ReadyStatus> {
    const response = await fetch('/ready', { headers: Api.token ? { Authorization: `Bearer ${Api.token}` } : {} })
    const data = await response.json().catch(() => null) as ReadyStatus | null
    if (!data) throw new Error('无法读取服务状态')
    return data
  }

  static listKnowledge(category?: string, limit = 50, offset = 0) {
    const params = new URLSearchParams({ limit: String(limit), offset: String(offset) })
    if (category) params.set('category', category)
    return Api.request<PaginatedResponse<KnowledgeItem>>('GET', `/knowledge?${params}`)
  }

  static createKnowledge(data: KnowledgeInput) {
    return Api.request<KnowledgeItem>('POST', '/knowledge', data)
  }

  static updateKnowledge(id: string, data: KnowledgeInput) {
    return Api.request<{ success: boolean; message: string }>('PUT', `/knowledge/${id}`, data)
  }

  static deleteKnowledge(id: string) {
    return Api.request<{ success: boolean; message: string }>('DELETE', `/knowledge/${id}`)
  }

  static getSystemPrompt() {
    return Api.request<SystemPrompt>('GET', '/system-prompt')
  }

  static updateSystemPrompt(content: string) {
    return Api.request<{ success: boolean; message: string; updated_at: string }>('PUT', '/system-prompt', { content })
  }

  static getAgents() {
    return Api.request<AgentConfig[]>('GET', '/sandbox/agents')
  }

  static createAgent(data: AgentCreateInput) {
    return Api.request<AgentConfig>('POST', '/sandbox/agents', data)
  }

  static updateAgent(id: number, data: AgentUpdateInput) {
    return Api.request<AgentConfig>('PUT', `/sandbox/agents/${id}`, data)
  }

  static deleteAgent(id: number) {
    return Api.request<{ success: boolean; message: string }>('DELETE', `/sandbox/agents/${id}`)
  }

  static getSkills() {
    return Api.request<SkillConfig[]>('GET', '/sandbox/skills')
  }

  static async uploadSkill(file: File) {
    const formData = new FormData()
    formData.append('file', file)
    const headers: Record<string, string> = {}
    if (Api.token) headers.Authorization = `Bearer ${Api.token}`
    const response = await fetch('/api/sandbox/skills/upload', { method: 'POST', headers, body: formData })
    if (!response.ok) throw new Error(await errorMessage(response, 'Skill 上传失败'))
    return response.json() as Promise<SkillConfig>
  }

  static toggleSkill(id: number) {
    return Api.request<{ success: boolean; enabled: boolean }>('PATCH', `/sandbox/skills/${id}/toggle`)
  }

  static deleteSkill(id: number) {
    return Api.request<{ success: boolean; message: string }>('DELETE', `/sandbox/skills/${id}`)
  }

  static getSkillFiles(id: number) {
    return Api.request<SkillFileTree>('GET', `/sandbox/skills/${id}/files`)
  }

  static getSkillFileContent(id: number, path: string) {
    return Api.request<SkillFileContent>('GET', `/sandbox/skills/${id}/files/${encodeURIComponent(path)}`)
  }

  static updateSkillPermissions(
    id: number,
    permissions: Array<{ agent_id: number; permission: SkillPermissionValue }>,
  ) {
    return Api.request<{ success: boolean; message: string }>('PUT', `/sandbox/skills/${id}/permissions`, permissions)
  }

  static getMcps() {
    return Api.request<McpConfig[]>('GET', '/sandbox/mcps')
  }

  static createMcp(data: McpCreateInput) {
    return Api.request<McpConfig>('POST', '/sandbox/mcps', data)
  }

  static updateMcp(id: number, data: McpUpdateInput) {
    return Api.request<McpConfig>('PUT', `/sandbox/mcps/${id}`, data)
  }

  static deleteMcp(id: number) {
    return Api.request<{ success: boolean; message: string }>('DELETE', `/sandbox/mcps/${id}`)
  }
}

