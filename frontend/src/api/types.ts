/**
 * AI 测试与评估平台 — 前端核心类型定义
 * 契约依据：docs/AI测试与评估平台-API.md (V1.5) 与 docs/AI测试与评估平台-PRD.md (V1.6.5)
 */

// 10 大标准业务错误码
export enum ErrorCode {
  UNAUTHORIZED = 'UNAUTHORIZED',
  VALIDATION = 'VALIDATION',
  NOT_FOUND = 'NOT_FOUND',
  BUDGET_EXCEEDED = 'BUDGET_EXCEEDED',
  CONCURRENCY = 'CONCURRENCY',
  WHITELIST = 'WHITELIST',
  NEED_APPROVAL = 'NEED_APPROVAL',
  UPSTREAM = 'UPSTREAM',
  TIMEOUT = 'TIMEOUT',
  INTERNAL = 'INTERNAL',
}

// 错误码中文映射表（规范 §7.3）
// 10 大码中性 fallback；场景文案一律优先用后端 payload.message（API.md §1.3）
export const ERROR_MESSAGES: Record<ErrorCode | string, string> = {
  [ErrorCode.UNAUTHORIZED]: '操作未完成，详见提示',
  [ErrorCode.VALIDATION]: '操作未完成，详见提示',
  [ErrorCode.NOT_FOUND]: '操作未完成，详见提示',
  [ErrorCode.BUDGET_EXCEEDED]: '操作未完成，详见提示',
  [ErrorCode.CONCURRENCY]: '操作未完成，详见提示',
  [ErrorCode.WHITELIST]: '操作未完成，详见提示',
  [ErrorCode.NEED_APPROVAL]: '操作未完成，详见提示',
  [ErrorCode.UPSTREAM]: '操作未完成，详见提示',
  [ErrorCode.TIMEOUT]: '操作未完成，详见提示',
  [ErrorCode.INTERNAL]: '操作未完成，详见提示',
}

// 用户角色（PRD 2.1 冻结为单一角色 member，全员同权）
export type Role = 'member' | 'admin' | 'engineer' | 'readonly'

export interface AuthUser {
  id: string
  username: string
  display_name?: string | null
  role: Role
  disabled: boolean
  must_change_password?: boolean
  created_at?: string
}

export interface WsTicketOut {
  ticket: string
  expires_in: number
}

// 协议类型
export type ProtocolType = 'openai_chat' | 'openai_responses' | 'anthropic_messages'

// Agent 思考强度；具体模型不支持某档位时由上游返回统一 UPSTREAM 错误。
export type ReasoningEffort = 'low' | 'medium' | 'high' | 'xhigh' | 'max'

export interface AgentReasoningSettings {
  enabled: boolean
  effort: ReasoningEffort
}

// 协议档用途
// benchmark 为 legacy usage 值（种子协议档使用），后端仍接受
export type ProfileUsage = 'target' | 'agent' | 'judge' | 'benchmark'
export type ToolCallMode = 'native' | 'legacy'

export interface Profile {
  id: string
  name: string
  protocol: ProtocolType
  base_url: string
  model: string
  api_key?: string // 永不回显，仅在提交时可选填写
  embedding_base_url?: string | null
  embedding_model?: string | null
  has_embedding_api_key?: boolean
  reranker_base_url?: string | null
  reranker_model?: string | null
  has_reranker_api_key?: boolean
  has_api_key?: boolean
  anthropic_version?: string
  usages?: ProfileUsage[]
  context_window?: number // 上下文窗口容量 (Tokens)
  max_output_tokens?: number // Agent 单回合模型输出上限 (max_tokens)
  tool_call_mode?: ToolCallMode
  created_at: string
  updated_at?: string
}

export interface ProfileCreateIn {
  name: string
  protocol: ProtocolType
  base_url: string
  model: string
  api_key: string
  embedding_base_url?: string
  embedding_model?: string
  embedding_api_key?: string
  reranker_base_url?: string
  reranker_model?: string
  reranker_api_key?: string
  anthropic_version?: string
  usages?: ProfileUsage[]
  context_window?: number
  max_output_tokens?: number
  tool_call_mode?: ToolCallMode
}

export interface ProfileUpdateIn {
  name?: string
  protocol?: ProtocolType
  base_url?: string
  model?: string
  api_key?: string
  embedding_base_url?: string
  embedding_model?: string
  embedding_api_key?: string
  reranker_base_url?: string
  reranker_model?: string
  reranker_api_key?: string
  anthropic_version?: string
  usages?: ProfileUsage[]
  context_window?: number
  max_output_tokens?: number
  tool_call_mode?: ToolCallMode
}

export interface ProfileCheckOut {
  ok: boolean
  latency_ms?: number
  model?: string
  error?: string
}

// 远程 /models 目录可选的模型请求字段；CursorAPI 用于构造 model[param=value]。
export interface RemoteModelParameter {
  id: string
  values: string[]
}

export interface RemoteModel {
  id: string
  name: string
  owned_by?: string
  parameters?: RemoteModelParameter[]
}

// 任务类型与状态
export type TaskKind = 'benchmark' | 'rag' | 'testcase' | 'stress'

export type TaskStatus =
  | 'queued'
  | 'running'
  | 'awaiting_case_confirm'
  | 'succeeded'
  | 'failed'
  | 'cancelled'

// 压测配置（env 枚举对齐 API.md §1.4 与后端 schemas.py：含 dev）
export interface StressConfig {
  env: 'dev' | 'test' | 'staging' | 'prod'
  qps: number
  duration_s: number
  sla_p99_ms?: number
}

// 运行高级参数
export interface RunConfig {
  sample_size?: number
  concurrency?: number
  timeout_s?: number
  retry?: number
  temperature?: number
  max_tokens?: number
  // 单任务预算上限（美元）：累计 usage 超限即停并返回 BUDGET_EXCEEDED（F-CM-06）
  max_usd?: number
  system_prompt?: string
  k?: number
  use_judge?: boolean
  judge_profile_id?: string
  seed?: number
}

// 任务规格 TaskSpec（ConfirmCard 与 FormDrawer 共享同一模型）
export interface TaskSpec {
  kind: TaskKind
  profile_ids?: string[]
  dataset_id?: string
  kb_id?: string
  gold_qa_id?: string
  rag_mode?: Array<'naive' | 'local' | 'global' | 'hybrid'>
  case_source?: {
    file_id?: string
    text?: string
  }
  run?: RunConfig
  with_stress?: boolean
  stress?: StressConfig
  session_id?: string
  parent_task_id?: string
}

// 调度中心（API V1.3 §3.13）
export interface DispatchOverview {
  online_workers: number
  total_workers: number
  queue_depth: number
  avg_dispatch_cost_ms: number
  assigned_today: number
  strategy: string
  max_running_tasks: number
  heartbeat_interval_ms: number
}

export interface DispatchWorker {
  id: string
  name: string
  caps: string[]
  state: 'idle' | 'busy' | 'offline' | 'draining'
  weight: number
  load_percent?: number | null
  current_task?: string | null
  last_heartbeat_at?: string | null
}

export interface DispatchEvent {
  id: number
  task_id?: string | null
  worker_id?: string | null
  event: string
  message: string
  ts: string
}

export interface DispatchEventPage {
  items: DispatchEvent[]
  next_after_id: number
}

export interface DispatchConfig {
  strategy: '负载均衡' | '优先级抢占' | '亲和性'
  max_running_tasks: number
}

export interface RagModelsConfig {
  embedding_base_url: string
  embedding_model: string
  embedding_api_key?: string
  has_embedding_api_key?: boolean
  reranker_base_url: string
  reranker_model: string
  reranker_api_key?: string
  has_reranker_api_key?: boolean
}

// 工具实现位置与摘要接口（API §3.6.1；code_snippet 已移除——原为手写示意代码且与真实 handler 不符）
export interface ToolCodeDetails {
  source_file: string
  handler_function: string
  code_summary: string
}

// 工具执行阶段流接口
export interface ToolPipelineStage {
  step: number
  name: string
  desc: string
}

export interface ToolPipeline {
  stages: ToolPipelineStage[]
}

// MCP 通道健康检查状态接口
export interface McpChannelStatus {
  channel: 'native_toolcall' | 'internal_mcp' | 'external_mcp'
  name: string
  ok: boolean
  tools_count?: number
  tools?: string[]
  latency_ms?: number
  sandbox_mode?: string
  bwrap_ready?: boolean
  workspace_access?: string
  provider?: string
  task_queue_bridge?: string
  status?: string
  active_external_servers?: number
  isolation_guard?: string
  message: string
}

// 全通道健康自检响应
export interface McpHealthCheckResponse {
  ok: boolean
  timestamp: number
  total_latency_ms: number
  summary: {
    total_tools: number
    native_tools_count: number
    internal_mcp_tools_count: number
    external_mcp_servers_count: number
  }
  channels: {
    native: McpChannelStatus
    internal_mcp: McpChannelStatus
    external_gateway: McpChannelStatus
  }
}

// MCP 内置短工具与原生 ToolCall（API V1.3 §3.6.1，只读契约）
// transport='native'：原生基础工具（read/write/edit/bash 等）由 NativeToolExecutor 直连执行；
// transport='mcp'：内部 MCP 扩展工具（platform.tasks 等）通过 MCPClientManager 调用。
export interface McpTool {
  name: string
  desc: string
  permission: string
  enabled: boolean
  source: 'builtin' | 'standalone'
  // 扩展全量契约字段（来自 /api/mcp/all-tools）
  transport?: 'native' | 'mcp'
  category?: 'native_toolcall' | 'internal_mcp' | 'external_mcp'
  display_name?: string
  risk_level?: 'read' | 'modify' | 'network' | 'code' | 'long'
  server_id?: string
  short_name?: string
  tool_id?: string
  timeout_s?: number
  supports_streaming?: boolean
  requires_confirmation?: boolean
  execution_mode?: 'short' | 'long'
  concurrency_class?: string
  parameters_schema?: Record<string, any>
  output_schema?: Record<string, any>
  permission_policy?: Record<string, any>
  recovery_policy?: Record<string, any>
  code_details?: ToolCodeDetails
  pipeline?: ToolPipeline
}

export interface TaskProgress {
  percent?: number
  done: number
  total: number
  message: string
}

export interface TaskEvent {
  id: number
  task_id: string
  event: string
  level: string
  message: string | null
  payload: any
  ts: string
}

export interface Task {
  id: string
  kind: TaskKind
  status: TaskStatus
  config: TaskSpec
  progress?: TaskProgress
  report_id?: string | null
  result?: { error_code?: string; error_message?: string; metric?: string; profile_count?: number; sample_total?: number } | null
  parent_task_id?: string | null
  child_stress_task_id?: string | null
  with_stress?: boolean
  creator?: string
  /** API 契约中的创建者用户 ID；任务写操作须与当前登录用户精确比对。 */
  creator_id?: string
  created_by?: string
  created_at: string
  updated_at?: string
  events?: TaskEvent[]
  need_approval?: boolean
}

// 数据集
export type DatasetMetric = 'contain' | 'exact' | 'regex' | 'rouge_l' | 'bleu'

export interface DatasetRow {
  row_no: number
  question: string
  reference: string
  context?: string | null
  source_case_id?: string
  is_pending?: boolean
}

// 数据集自定义扩展列定义（契约 column_schema 项）
export interface ColumnSchemaItem {
  key: string
  name: string
  type?: string
  required?: boolean
  sort_order?: number
}

export interface Dataset {
  id: string
  name: string
  version: number
  row_count: number
  pending_complete_count: number
  metric: DatasetMetric
  owner: string
  folder_id?: string | null
  column_schema?: ColumnSchemaItem[]
  created_at: string
  updated_at?: string
  rows?: DatasetRow[]
}

// 用例集
export interface TestCaseCheck {
  level: 'error' | 'warning'
  code: string
  message: string
}

export interface TestCase {
  id: string
  // 6 类用例策略：正向 / 反向 / 边界 / 状态 / 场景 / 等价（后端亦可能回写 等价类 / 状态迁移）
  strategy: '正向' | '反向' | '边界' | '状态' | '场景' | '等价'
  // 优先级六档：HX 核心 / FHX 非核心 / BJ 边界问题 / YC 异常 / ZD 中断 / BL 遍历
  priority: 'HX' | 'FHX' | 'BJ' | 'YC' | 'ZD' | 'BL'
  module: string
  submodule?: string
  feature_point?: string
  name: string
  expected: string
  precondition?: string
  steps?: string
  test_type?: string
  mapped?: boolean
  pending?: boolean
  pending_complete?: boolean
  question?: string
  reference?: string
  selected?: boolean
}

export interface CaseFolder {
  id: string
  name: string
  parent_id?: string | null
  sort_order: number
  created_at: string
}

export interface DatasetFolder {
  id: string
  name: string
  parent_id?: string | null
  sort_order: number
  created_at: string
}

export interface CaseImportResult {
  ok: boolean
  format: 'platform' | 'standard' | 'simple'
  mode: 'append' | 'replace'
  imported_count: number
  skipped_count: number
  generated_count: number
  checks: TestCaseCheck[]
}

export interface CaseSet {
  id: string
  task_id?: string | null
  name: string
  status: 'generated' | 'confirmed' | 'cancelled'
  generated_count: number
  confirmed_count: number
  expires_in_h?: number
  expires_at?: string | null
  folder_id?: string | null
  column_schema?: ColumnSchemaItem[]
  checks: TestCaseCheck[]
  cases?: TestCase[]
  created_at?: string
}

// 知识库与黄金 QA
export interface KnowledgeBase {
  id: string
  name: string
  kind: 'lightrag' | 'external_chat'
  doc_count: number | null
  is_core: boolean
  owner: string
  profile_id?: string
  created_at?: string
  capabilities?: {
    projection: boolean
    rerank_compare: boolean
  }
}

export interface KbDocument {
  doc_id: string
  filename: string
  status: 'indexed' | 'indexing' | 'failed'
  size: string
  created_at?: string
}

export type KbDoc = KbDocument

export interface GoldQA {
  id: string
  kb_id: string
  name: string
  version: number
  row_count: number
  owner: string
  created_at: string
}

export interface KbChunk {
  chunk_id: string
  doc_id: string
  text: string
  tokens: number
  similarity?: number
}

// 评测报告
export interface BenchmarkScore {
  // Worker 实际输出字段（benchmark _finish）
  profile_id?: string
  profile_name?: string
  model?: string
  metric?: string
  score?: number
  exact?: number
  rouge_l?: number
  judge?: number
  fail_rate?: number
  latency_ms_avg?: number
  sample_total?: number
  sample_failed?: number
  usage?: { prompt_tokens: number; completion_tokens: number; total_tokens: number }
  est_cost_usd?: number
  // 兼容旧 spec（seed / Report.vue 旧模板）
  profile: string
  contain?: number
  regex?: number
  bleu?: number
  latency: string | number
  judge_breakdown?: {
    accuracy?: number
    completeness?: number
    logic?: number
  }
}

export interface ReportJudgeInfo {
  profile_id?: string | null
  profile_name?: string | null
  model?: string | null
  usage?: { prompt_tokens: number; completion_tokens: number; total_tokens: number }
  est_cost_usd?: number
  judged_count?: number
  failed_count?: number
}

// 模型对比页：逐题样本
export interface ComparePrediction {
  profile_id: string
  profile_name: string | null
  model: string | null
  output: string
  score: number | null
  exact: number | null
  rouge_l: number | null
  judge_score: number | null
  judge_reason?: string | null
  latency_ms: number | null
  usage?: { prompt_tokens: number; completion_tokens: number; total_tokens: number } | null
  error?: string | null
  raw?: any
}

export interface CompareSampleRow {
  row_no: number
  question: string
  reference: string
  context?: string | null
  diff: boolean
  predictions: ComparePrediction[]
}

export interface FailedSample {
  row: number
  question: string
  error: string
  raw: string
}

export interface RagScores {
  naive?: { hit: number; mrr: number; recall: number; contain: number }
  local?: { hit: number; mrr: number; recall: number; contain: number }
  global?: { hit: number; mrr: number; recall: number; contain: number }
  hybrid?: { hit: number; mrr: number; recall: number; contain: number }
}

export interface StressSeriesPoint {
  ts: string
  qps: number
  rt_ms: number
  error_rate: number
}

/** 压测时序接口响应：报告内嵌 series 或独立 stress-series 接口均可返回 points/series。 */
export interface StressSeriesResponse {
  task_id?: string
  points?: StressSeriesPoint[]
  series?: StressSeriesPoint[]
}

export interface Report {
  id: string
  task_id: string
  kind: TaskKind
  title: string
  created_at: string
  snapshot?: any
  child_stress_task_id?: string
  child_stress_report_id?: string
  // 「先评后压」链路回溯：压测报告派生来源的父质量评测任务与报告
  parent_task_id?: string
  parent_report_id?: string
  baseline?: {
    task_id: string
    delta: number
    name?: string
  }
  judge_info?: {
    profile_name: string
    criteria: string
    reasoning_summary: string
  }
  sample_items?: any[]
  // Benchmark 报告
  scores?: BenchmarkScore[]
  failed_items?: FailedSample[]
  metric?: string
  denominator_note?: string
  judge?: ReportJudgeInfo | null
  // 报告内嵌数据集元信息与样本总量（worker 写入 metrics 并平铺到报告响应）
  dataset_id?: string
  dataset_name?: string
  dataset_version?: number
  sample_total?: number
  // RAG 报告
  k?: number
  modes?: Array<'naive' | 'local' | 'global' | 'hybrid'>
  rag_scores?: RagScores
  degraded?: {
    mode: string
    pp: number
  }
  hit_note?: string
  // 压测报告
  env?: string
  qps_peak?: number
  p99?: string | number
  error_rate?: string | number
  ttft?: string | number
  tpot?: string | number
  tokens_per_s?: string | number
  est_cost?: string | number
  sla_p99_ms?: number
  sla_met?: boolean
  knee?: string
  series?: StressSeriesPoint[]
}

// 管理员设置
export interface AdminSettings {
  agent_profile_id: string
  agent_reasoning: AgentReasoningSettings
  max_running_tasks: number
  max_inflight_model_calls: number
  default_max_usd: number
  stress: {
    host_whitelist: string[]
    max_qps: number
    max_duration_s: number
    price_per_1k_tokens: number
  }
  notify: {
    wecom: boolean
    email: boolean
    webhook: boolean
  }
  prod_approvers: string[]
  // Agent 运行时治理（协议档页运行时 Tab）
  runtime?: {
    ws_ping_s: number
    ws_timeout_s: number
    strict_session_slot: boolean
  }
}

/** Agent 技能文件的轻量目录；不携带工作流正文。 */
export interface AgentSkillMetadata {
  id: string
  name: string
  kind: 'benchmark' | 'rag' | 'testcase' | 'stress'
  version: string
  enabled: boolean
  summary: string
}

/** 管理端预览或编辑的单个 SKILL.md 文件。 */
export interface AgentSkillDocument {
  id: string
  content: string
  revision: string
  metadata: AgentSkillMetadata
}

/** Agent 协议档的只读核心提示词与可写补充层。 */
export interface AgentPromptConfig {
  profile_id: string
  base_prompt: string
  overlay: string
}

export interface WhitelistItem {
  id: string
  host: string
  scope: string
  creator: string
  created_at: string
  status: 'active' | 'inactive'
}

// 智能体会话：默认 private，owner 可切换为当前内部团队共享。
export type SessionVisibility = 'private' | 'team'

export interface SessionAuthor {
  id: string
  username: string
  display_name?: string | null
}

export interface AttachmentReference {
  file_id: string
  filename?: string
  size?: number
  content_type?: string | null
  content_url?: string
}

export interface AgentSession {
  /** 创建时固化，打开历史时必须据此选择 transport。 */
  engine_version?: 'legacy' | 'agent_loop_v2'
  id: string
  title: string
  owner_id: string
  visibility: SessionVisibility
  created_at: string
  updated_at?: string
  status?: TaskStatus
  can_manage: boolean
  can_delete: boolean
  /** F3/G5：绑定工作区（创建时固化；未绑定为 null） */
  workspace_id?: string | null
  workspace_name?: string | null
  scope_path?: string | null
  active_task?: { id: string; kind: TaskKind; status: TaskStatus } | null
}

/** turn 级观测指标（messages.turn_stats / assistant_message 事件）：模型轮数、工具成败计数与 token 用量。 */
export interface TurnStats {
  model_calls?: number | null
  tool_calls?: number | null
  tool_failures?: number | null
  prompt_tokens?: number | null
  completion_tokens?: number | null
  total_tokens?: number | null
}

export interface SessionMessage {
  id: string
  role: 'user' | 'assistant' | 'system'
  content: string
  attachments: Array<string | AttachmentReference>
  author_id?: string | null
  author?: SessionAuthor | null
  client_message_id?: string | null
  // assistant 交付句的回复生成耗时（毫秒），仅 assistant 非空，气泡展示「耗时 x 秒」。
  latency_ms?: number | null
  // turn 级观测指标（仅 assistant）：模型轮数/token/工具成败，供气泡元信息展示。
  turn_stats?: TurnStats | null
  model_name?: string | null
  profile_id?: string | null
  profile_name?: string | null
  provider?: string | null
  created_at: string
}

export interface SessionHistory {
  messages: SessionMessage[]
  events: Array<Omit<WsServerEvent, 'session_id'>>
  pending_confirm?: Record<string, unknown> | null
  pending_confirm_author_id?: string | null
  pending_confirm_author?: SessionAuthor | null
  compact_summary?: string | null
  context_meter?: {
    messages: number
    skills: number
    summary: number
    headroom: number
    window: number
    total_tokens?: number
    max_tokens?: number
    messages_tokens?: number
    skills_tokens?: number
    free_tokens?: number
    used_percent?: number
    messages_percent?: number
    skills_percent?: number
    free_percent?: number
    mcp_tools_count?: number
    mcp_tools_max?: number
    memory_files_count?: number
    memory_files_max?: number
    compacted?: boolean
  }
}

/** PlanArtifact（API.md §4.3 `plan` / M7 晚波），用户可查看无需 ack */
export interface PlanArtifact {
  intent: string
  skill_id?: string | null
  slots: Record<string, unknown>
  tools_needed: string[]
  delivery: string
  budget: Record<string, number>
  allows_replan: boolean
  notes?: string
}

/** 结构化任务状态机（TaskSessionState 契约） */
export interface TaskSessionState {
  protocol?: string
  version?: string
  goal: string
  phase: 'exploring' | 'verifying' | 'converging' | 'completed' | 'blocked'
  completed_steps: string[]
  current_step: string
  next_actions: string[]
  failed_steps: Array<{ step: string; reason: string; repair_hint?: string }>
  current_hypothesis?: string
  confirmed_facts: string[]
  evidence: string[]
  rejected_hypotheses: Array<{ hypothesis: string; reason: string; evidence_ref?: string }>
  missing_info: string[]
  can_deliver: boolean
  blocked_reason?: string
  notes?: string
}

/** 跨会话下单偏好（API.md §3.4 GET /api/agent/prefs） */
export interface AgentPrefs {
  last_kind?: string | null
  last_profile_ids?: string[] | null
  last_dataset_id?: string | null
  last_kb_id?: string | null
  last_gold_qa_id?: string | null
  last_with_stress?: boolean | null
  updated_at?: string | null
}

// WS 事件公共头（API.md §4.2）：payload 嵌套，task_id 入队后才有
// H3 起 Agent 引擎恢复 tool_call / tool_result（ToolCard 只渲染脱敏摘要）；
// V1.68（H2 批次 2）恢复确认卡 confirm / confirm_ack；历史旧事件一律不重放。 (feat(agent): H2 批次 2 确认卡链路——W5 发卡与 ack 重放经 W6 唯一入队)
export interface WsServerEvent {
  event:
    | 'user_message'
    | 'message'
    | 'assistant_delta'
    | 'assistant_message'
    | 'response.completed'
    | 'done'
    | 'thought'
    | 'tool_call'
    | 'tool_result'
    | 'progress'
    | 'report'
    | 'task_cancelled'
    | 'confirm'
    | 'confirm_ack'
    | 'tool_approval'
    | 'tool_approval_ack'
    | 'approval_terminal'
    | 'clarify'
    | 'clarify_ack'
    | 'error'
    | 'session_title'
    | 'pong'
  session_id: string
  task_id: string | null
  event_id: number
  ts: string
  payload: any
}

// response.completed payload（API.md §4.3 V1.67）：混合引擎开启时的引擎审计。
// engine 即分流结论；H2/H3 起 workflow（W0–W7 DAG）/ agent（TAOR）均已真实执行，
// 主开关关闭时三个可选字段不出现，旧客户端忽略即可。
export interface ResponseCompletedPayload {
  finish_reason: 'stop' | 'cancelled' | 'error'
  role: string
  engine?: 'direct' | 'chat' | 'workflow' | 'agent'
  agent_id?: string
  router_confidence?: number
  router_reason?: string
}

// tool_call payload（H3 Agent TAOR）：orchestrator 发起 Act 时产出；
// arguments 已脱敏（值截断/路径取末段/对象折叠），ToolCard 只展示摘要。
export interface ToolCallPayload {
  call_id: string
  name: string
  arguments?: Record<string, unknown>
}

// tool_result payload（toolnode 十层链产出）：仅受控投影
// （data 为 display_data 摘要；失败时 error 为脱敏原因），不含观察全文。
export interface ToolResultPayload {
  call_id: string
  name: string
  ok: boolean
  latency_ms?: number
  truncated?: boolean
  redacted?: boolean
  data?: Record<string, unknown>
  error?: string
  source?: string
}

// tool_approval payload（API.md §4.3 V1.70 / H5 HITL）：危险 bash 等命令在
// 执行前中断，事件载荷即审批卡；approved/rejected 由上行 tool_approval_ack 回执。
export interface ToolApprovalPayload {
  type: 'tool_approval'
  id: string
  call_id: string
  name: string
  command: string
  reason?: string
  risk_level?: 'high' | 'medium' | 'low'
  sandbox_scope?: string
  allowed_decisions?: Array<'approve' | 'reject'>
}

// clarify payload（API.md §4.3 V1.72 / dsh #1）：ask_user_question 的图内
// interrupt 载荷即澄清卡（≤8 题三题型一次作答）；submitted 由上行 clarify_reply
// 乐观盖章并经 clarify_ack 广播回执确认（与 tool_approval_ack 同构）。
export interface ClarifyQuestion {
  id: string
  question: string
  header?: string
  options?: Array<{ label: string; description?: string }>
  multi_select?: boolean
  required?: boolean
  type: 'radio' | 'checkbox' | 'text'
}

export interface ClarifyPayload {
  type: 'clarify'
  id: string
  questions: ClarifyQuestion[]
}

/** 澄清答案（API.md §4.4 V1.72 clarify_reply.answers[]）：radio/checkbox 用
 * selected（label 列表），text 用 custom。 */
export interface ClarifyAnswer {
  id: string
  selected: string[]
  custom?: string
}

// ══════════════════════════════════════════════════════════════════════════════
// Dify 风格可视化工作流编排相关数据结构 (Workflow Studio & DAG)
// ══════════════════════════════════════════════════════════════════════════════

export type WorkflowNodeType =
  | 'dataset'
  | 'testcase'
  | 'prompt'
  | 'llm'
  | 'agent'
  | 'rag'
  | 'judge'
  | 'assert'
  | 'metrics'
  | 'gate'
  | 'stress'
  | 'worker'
  | 'report'
  | 'webhook'

export type WorkflowNodeStatus = 'idle' | 'running' | 'succeeded' | 'failed' | 'skipped'

export interface WorkflowPort {
  id: string
  name: string
  type: 'input' | 'output'
  dataType?: 'dataset' | 'cases' | 'text' | 'json' | 'score' | 'boolean' | 'any'
}

export interface WorkflowNode<T = Record<string, any>> {
  id: string
  type: WorkflowNodeType
  title: string
  description?: string
  x: number
  y: number
  inputs?: WorkflowPort[]
  outputs?: WorkflowPort[]
  config: T
  status?: WorkflowNodeStatus
  progress?: number
  outputData?: any
  errorMsg?: string
  costMs?: number
}

export interface WorkflowEdge {
  id: string
  fromNodeId: string
  fromPortId: string
  toNodeId: string
  toPortId: string
  label?: string
  condition?: string
}

export interface WorkflowTemplate {
  id: string
  name: string
  description: string
  icon: string
  category: string
  nodes: WorkflowNode[]
  edges: WorkflowEdge[]
}


// ─── 管理端 · 工作区（会话 → 沙箱文件夹） ───
export interface WorkspaceFolder {
  name: string
  path: string
  exists: boolean
  file_count: number
  total_bytes: number
  updated_at?: string | null
}

export interface WorkspaceSession {
  session_id: string
  title: string
  owner?: string | null
  visibility: SessionVisibility
  deleted: boolean
  created_at?: string | null
  updated_at?: string | null
  folder: WorkspaceFolder | null
}

// 工作区整体聚合统计（不受筛选影响，供 KPI 卡片）
export interface WorkspaceStats {
  total_sessions: number
  with_folder: number
  orphan_count: number
}

export interface WorkspaceOverview {
  root: string
  items: WorkspaceSession[]
  // 服务端分页：items 仅当前页，total 为过滤后的会话总数
  total: number
  offset: number
  limit: number
  stats: WorkspaceStats
  orphans: WorkspaceFolder[]
}

export interface WorkspaceFile {
  name: string
  size: number
  updated_at: string
}

export interface WorkspaceFileList {
  session_id: string
  path: string
  files: WorkspaceFile[]
  total: number
}

// —— 用户域工作区（F1/G1）——
export interface UserWorkspace {
  id: string
  name: string
  owner_id: string
  created_at?: string | null
  updated_at?: string | null
  deleted: boolean
  folder: WorkspaceFolder | null
}

export interface UserWorkspaceList {
  items: UserWorkspace[]
  total: number
}

export interface UserWorkspaceFileEntry {
  name: string
  kind: 'dir' | 'file' | 'link'
  size: number
  updated_at?: string | null
}

export interface UserWorkspaceFileList {
  workspace_id: string
  path: string
  entries: UserWorkspaceFileEntry[]
  total: number
}
