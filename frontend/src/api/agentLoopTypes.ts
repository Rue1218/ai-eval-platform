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
}
export interface LoopUi {
  version: 1; enabled: boolean; unavailable_reason?: string
  profile: { id: string; version: string; model: string; protocol: string } | null
  allowed_efforts: Effort[]; default_effort: Effort | null
  permissions: { write: boolean; trace: boolean; reasoning: boolean; interactions: boolean; settings: boolean }
  controller: { active: boolean; owned_by_actor: boolean }
  attachments: { upload_suffixes: string[]; inline_suffixes: string[]; image_suffixes: string[]; max_bytes: number; max_image_bytes: number; content_required: boolean }
}
export type ToolStatus = 'pending' | 'waiting_approval' | 'running' | 'succeeded' | 'failed' | 'denied' | 'cancelled' | 'not_started' | 'outcome_unknown'
export interface ToolDisplay {
  version?: number; title?: string; target?: string; registry_name?: string; wire_name?: string
  arguments_preview?: string; result_preview?: string; format?: string; truncated?: boolean; unavailable_reason?: string
}
/** 业务记录保持稳定引用，页面展开状态由组件管理。 */
export interface LoopRecord extends Data { key: string; first_cursor: number; correlation: Correlation; event: string }
export interface Attempt extends LoopRecord { text: string; reasoning: string; ended: boolean; chunks: Record<string, number>; request_summary?: Data }
export interface ToolRun extends LoopRecord { name: string; status: ToolStatus; display: ToolDisplay; synthetic?: boolean }
export interface InteractionRecord extends LoopRecord { interaction_id: string; kind: string; resolved: boolean; submitting?: boolean; restricted?: boolean }
export type Connection = 'connecting' | 'online' | 'reconnecting' | 'offline' | 'revoked'
