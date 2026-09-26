/** 用户主动维护的长期记忆；使用统一鉴权和错误处理，不提供模型写入口。 */
import http from './http'

/** 常用偏好用于跨私有对话建议，事实资料按当前问题召回。 */
export type MemoryCategory = 'preference' | 'fact'

/** 保存时必须明确保留或变更范围，不能把失效工作区隐式转换为全局。 */
export interface MemoryInput {
  title: string
  content: string
  category: MemoryCategory
  workspace_id: string | null
}

/** 服务端版本用于更正和删除的乐观锁，来源编号用于聊天中的引用。 */
export interface AgentMemory extends MemoryInput {
  id: string
  workspace_name: string | null
  version: number
  source_id: string
  created_at: string
  updated_at: string
}

/** 列表始终由服务端过滤和分页，total 对应当前查询条件。 */
export interface MemoryPage { items: AgentMemory[]; total: number }

export const agentMemories = {
  /** 省略工作区筛选时返回本人全部范围的记忆。 */
  async list(params: { q?: string; workspace_id?: string; limit: number; offset: number }): Promise<MemoryPage> {
    const { data } = await http.get<MemoryPage>('/api/agent/memories', { params })
    return data
  },
  /** 仅在用户主动提交表单后保存。 */
  async create(input: MemoryInput): Promise<AgentMemory> {
    const { data } = await http.post<AgentMemory>('/api/agent/memories', input)
    return data
  },
  /** 携带用户打开编辑器时的版本；冲突不自动重试覆盖。 */
  async update(id: string, input: MemoryInput & { version: number }): Promise<AgentMemory> {
    const { data } = await http.put<AgentMemory>(`/api/agent/memories/${encodeURIComponent(id)}`, input)
    return data
  },
  /** 删除也检查版本，防止删掉其他窗口刚更正的记忆。 */
  async remove(id: string, version: number): Promise<void> {
    await http.delete(`/api/agent/memories/${encodeURIComponent(id)}`, { params: { version } })
  },
}
