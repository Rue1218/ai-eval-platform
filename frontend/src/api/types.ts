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
export const ERROR_MESSAGES: Record<ErrorCode | string, string> = {
  [ErrorCode.UNAUTHORIZED]: '没有权限执行此操作',
  [ErrorCode.VALIDATION]: '请检查表单标红字段',
  [ErrorCode.NOT_FOUND]: '请求的资源不存在或已删除',
  [ErrorCode.BUDGET_EXCEEDED]: '已达到任务预算上限 ($5)',
  [ErrorCode.CONCURRENCY]: '平台并发已满，任务保持排队中',
  [ErrorCode.WHITELIST]: '目标主机不在压测白名单中',
  [ErrorCode.NEED_APPROVAL]: '等待管理员会签后才能对生产发压',
  [ErrorCode.UPSTREAM]: '被测服务接口调用失败，请查看样本错误详情',
  [ErrorCode.TIMEOUT]: '请求或执行超时',
  [ErrorCode.INTERNAL]: '平台内部错误，请重试或联系维护人员',
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

// 协议档用途
export type ProfileUsage = 'target' | 'agent' | 'judge'

export interface Profile {
  id: string
  name: string
  protocol: ProtocolType
  base_url: string
  model: string
  api_key?: string // 永不回显，仅在提交时可选填写
  anthropic_version?: string
  usages?: ProfileUsage[]
  context_window?: number // 上下文窗口容量 (Tokens)
  created_at: string
  updated_at?: string
}

export interface ProfileCreateIn {
  name: string
  protocol: ProtocolType
  base_url: string
  model: string
  api_key: string
  anthropic_version?: string
  usages?: ProfileUsage[]
  context_window?: number
}

export interface ProfileUpdateIn {
  name?: string
  protocol?: ProtocolType
  base_url?: string
  model?: string
  api_key?: string
  anthropic_version?: string
  usages?: ProfileUsage[]
  context_window?: number
}

export interface ProfileCheckOut {
  ok: boolean
  latency_ms?: number
  model?: string
  error?: string
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

// MCP 内置短工具（API V1.3 §3.6.1，只读）
export interface McpTool {
  name: string
  desc: string
  permission: 'read' | 'write'
  enabled: boolean
  source: 'builtin'
}

export interface TaskProgress {
  percent?: number
  done: number
  total: number
  message: string
}

export interface TaskEvent {
  id: string
  task_id: string
  event_type: string
  message: string
  data?: any
  created_at: string
}

export interface Task {
  id: string
  kind: TaskKind
  status: TaskStatus
  config: TaskSpec
  progress?: TaskProgress
  report_id?: string | null
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
  // 优先级支持 P0–P3 四档
  priority: 'P0' | 'P1' | 'P2' | 'P3'
  module: string
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
  profile: string
  profile_name?: string
  contain?: number
  exact?: number
  regex?: number
  rouge_l?: number
  bleu?: number
  fail_rate: number
  latency: string | number
  judge?: number
  judge_breakdown?: {
    accuracy?: number
    completeness?: number
    logic?: number
  }
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

export interface AgentSession {
  id: string
  title: string
  owner_id: string
  visibility: SessionVisibility
  created_at: string
  updated_at?: string
  status?: TaskStatus
  can_manage: boolean
  can_delete: boolean
  active_task?: { id: string; kind: TaskKind; status: TaskStatus } | null
}

export interface SessionMessage {
  id: string
  role: 'user' | 'assistant' | 'system'
  content: string
  attachments: string[]
  author_id?: string | null
  author?: SessionAuthor | null
  client_message_id?: string | null
  // assistant 交付句的回复生成耗时（毫秒），仅 assistant 非空，气泡展示「耗时 x 秒」。
  latency_ms?: number | null
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
  }
}

// WS 事件公共头（API.md §4.2）：payload 嵌套，task_id 入队后才有
export interface WsServerEvent {
  event:
    | 'thought'
    | 'message'
    | 'tool_call'
    | 'tool_result'
    | 'confirm'
    | 'confirm_ack'
    | 'progress'
    | 'report'
    | 'error'
    | 'pong'
  session_id: string
  task_id: string | null
  event_id: number
  ts: string
  payload: any
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

