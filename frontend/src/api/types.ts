/**
 * AI 测试与评估平台 — 前端核心类型定义
 * 契约依据：docs/AI测试与评估平台-API.md (V1.3) 与 docs/AI测试与评估平台-PRD.md (V1.6.4)
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
}

export interface ProfileUpdateIn {
  name?: string
  protocol?: ProtocolType
  base_url?: string
  model?: string
  api_key?: string
  anthropic_version?: string
  usages?: ProfileUsage[]
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

// 压测配置
export interface StressConfig {
  env: 'test' | 'staging' | 'prod'
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

export interface Dataset {
  id: string
  name: string
  version: number
  row_count: number
  pending_complete_count: number
  metric: DatasetMetric
  owner: string
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
  strategy: '正向' | '反向' | '边界' | '状态' | '场景'
  priority: 'P0' | 'P1' | 'P2'
  module: string
  name: string
  expected: string
  precondition?: string
  steps?: string
  test_type?: string
  mapped?: boolean
  pending?: boolean
  question?: string
  reference?: string
  selected?: boolean
}

export interface CaseSet {
  id: string
  task_id: string
  name: string
  status: 'generated' | 'confirmed' | 'cancelled'
  generated_count: number
  confirmed_count: number
  expires_in_h: number
  expires_at?: string
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
}

export interface WhitelistItem {
  id: string
  host: string
  scope: string
  creator: string
  created_at: string
  status: 'active' | 'inactive'
}

// 智能体会话
export interface AgentSession {
  id: string
  title: string
  created_at: string
  updated_at?: string
  status?: TaskStatus
}

export type WsServerEvent =
  | { event: 'thought'; session_id: string; message: string; event_id: number; ts: number }
  | { event: 'tool_call'; session_id: string; tool: string; arguments: any; event_id: number; ts: number }
  | { event: 'tool_result'; session_id: string; tool: string; result: any; ok: boolean; event_id: number; ts: number }
  | { event: 'confirm'; session_id: string; card: TaskSpec; event_id: number; ts: number }
  | { event: 'progress'; session_id: string; task_id: string; progress: TaskProgress; event_id: number; ts: number }
  | { event: 'report'; session_id: string; task_id: string; report_id: string; event_id: number; ts: number }
  | { event: 'error'; session_id: string; code: ErrorCode; message: string; event_id: number; ts: number }
  | { event: 'pong'; ts: number }
