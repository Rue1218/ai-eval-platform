/** v2 身份、持久信封与安全展示 DTO；未知扩展字段保存为数据。 */
export type Data = Record<string, any>
export type Effort = 'off' | 'low' | 'medium' | 'high' | 'xhigh' | 'max'
export interface Correlation {
  turn_id?: string; turn?: number; step?: number; attempt_id?: string
  call_id?: string; call_seq?: number; source_seq?: number; task_id?: string
}
export interface LoopFrame {
  protocol_version: 2; type: string; durability: 'persistent' | 'transient' | 'control'
  session_id?: string; cursor?: number; request_id?: string; ts: string
  correlation: Correlation; data: Data
}
export interface LoopCommand {
  protocol_version: 2; type: string; session_id: string; request_id: string; data: Data
}
export interface LoopMeter {
  basis: string; estimated: boolean; profile_version: string; input_fingerprint: string
  history_upto_seq: number; capacity: number; input_tokens: number; reserved_output_tokens: number
  /** 本次真实请求的输入估算明细；旧历史缺失时由前端按总输入兼容展示。 */
  breakdown?: {
    system_prompt: number; conversation_messages: number; tools: number
    mcp: number; skill: number; memory_files: number
  }
}

/** 上游已归一化的真实 token 用量；缺失字段表示该协议未返回，而不是零。 */
export interface LoopUsage {
  prompt_tokens?: number; completion_tokens?: number; total_tokens?: number
  cache_read_input_tokens?: number; cache_creation_input_tokens?: number; cached_tokens?: number
}

/** 当前会话聚合后的模型消耗指标，只由已持久化的助手消息计算。 */
export interface ConversationMetrics {
  inputTokens: number; outputTokens: number
  outputTokensPerSecond: number | null; cacheHitRate: number | null
}

/** 已授权的 Agent 协议档；只包含选择模型所需的公开元数据。 */
export interface LoopProfile {
  provider?: string; reasoning_note?: string
  /** 后端模板的控制方式，legacy 不声明。 */
  reasoning_mode?: import('./types').ReasoningMode | null
  id: string; name: string; version: string; model: string; protocol: string
  allowed_efforts: Effort[]; default_effort: Effort | null
}
/** 可选择的 Agent 专家；只包含展示字段，不含提示词与工具视野。 */
export interface LoopAgent {
  id: string; name: string; description: string; badge: string; default: boolean
}
export interface LoopUi {
  version: 1; enabled: boolean; unavailable_reason?: string
  /** 当前草稿选中的协议档；实际回合继续以 request_summary 为准。 */
  profile: LoopProfile | null
  /** 当前账号可以用于 AgentLoop 的协议档，不返回端点或凭据。 */
  profiles: LoopProfile[]
  /** 会话/草稿当前选中的专家 ID；已有会话按最近一轮记忆。 */
  agent: string
  /** 当前账号可以选择的专家列表。 */
  agents: LoopAgent[]
  allowed_efforts: Effort[]; default_effort: Effort | null
  permissions: { write: boolean; trace: boolean; reasoning: boolean; interactions: boolean; settings: boolean }
  controller: { active: boolean; owned_by_actor: boolean }
  attachments: { upload_suffixes: string[]; inline_suffixes: string[]; image_suffixes: string[]; max_bytes: number; max_image_bytes: number; content_required: boolean }
}
export type ToolStatus = 'pending' | 'waiting_approval' | 'running' | 'succeeded' | 'failed' | 'denied' | 'cancelled' | 'not_started' | 'outcome_unknown'
/** 原生 task 的权威会话规划投影；仅来自持久 task_plan.updated。 */
export interface TaskPlanDisplay {
  goal: string
  description: string
  steps: Array<{ title: string; status: 'pending' | 'in_progress' | 'completed' }>
  counts: { pending: number; in_progress: number; completed: number }
}
export interface ToolDisplay {
  version?: number; title?: string; target?: string; registry_name?: string; wire_name?: string
  arguments_preview?: string; result_preview?: string; format?: string; truncated?: boolean; unavailable_reason?: string
}
/** 业务记录保持稳定引用，页面展开状态由组件管理。 */
export interface LoopRecord extends Data { key: string; first_cursor: number; correlation: Correlation; event: string; timestamp?: string }
export interface Attempt extends LoopRecord { text: string; reasoning: string; ended: boolean; chunks: Record<string, number>; request_summary?: Data; usage?: LoopUsage; latency_ms?: number }
export interface ToolRun extends LoopRecord {
  name: string; status: ToolStatus; display: ToolDisplay; synthetic?: boolean
  /** 调度边界公开名称映射与契约版本，不包含实际工具参数。 */
  registry_name?: string; wire_name?: string; tool_contract_version?: string
}
export interface InteractionRecord extends LoopRecord {
  interaction_id: string; kind: string; resolved: boolean; submitting?: boolean; restricted?: boolean
  /** 三档权限等级与工具风险等级（审批卡展示用，来自服务端事实）。 */
  permission_tier?: string; risk_level?: string
}
export type Connection = 'connecting' | 'online' | 'reconnecting' | 'offline' | 'revoked'
