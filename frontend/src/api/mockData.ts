/**
 * AI 测试与评估平台 — 示例 Mock 数据种子
 * 依据：Web-Prototype MOCK_SEED 与 PRD V1.6.4 / API V1.3
 */
import type {
  Profile,
  Dataset,
  DatasetRow,
  KnowledgeBase,
  KbDocument,
  GoldQA,
  AuthUser,
  AdminSettings,
  CaseSet,
  TestCase,
  Task,
  Report,
  WhitelistItem,
  McpTool,
} from './types'

export const MOCK_PROFILES: Profile[] = [
  {
    id: 'p-gpt',
    name: 'gpt-test',
    protocol: 'openai_chat',
    base_url: 'https://api.openai.com/v1',
    model: 'gpt-4o',
    usages: ['target'],
    created_at: '2026-08-02T09:00:00Z',
  },
  {
    id: 'p-claude',
    name: 'claude-x',
    protocol: 'anthropic_messages',
    base_url: 'https://api.anthropic.com/v1',
    model: 'claude-3-5-sonnet-20241022',
    usages: ['target'],
    created_at: '2026-08-02T09:10:00Z',
  },
  {
    id: 'p-agent',
    name: 'agent-主',
    protocol: 'anthropic_messages',
    base_url: 'https://api.anthropic.com/v1',
    model: 'claude-3-5-sonnet-20241022',
    usages: ['agent'],
    created_at: '2026-08-01T08:00:00Z',
  },
  {
    id: 'p-judge',
    name: 'judge-1',
    protocol: 'openai_responses',
    base_url: 'https://api.openai.com/v1',
    model: 'o4',
    usages: ['judge'],
    created_at: '2026-08-03T10:00:00Z',
  },
  {
    id: 'p-ragsvc',
    name: 'rag-客服外挂',
    protocol: 'openai_chat',
    base_url: 'http://10.0.0.8:8080',
    model: 'rag-chat-v2',
    usages: ['target'],
    created_at: '2026-08-05T11:00:00Z',
  },
]

export const MOCK_DATASETS: Dataset[] = [
  {
    id: 'ds-smoke',
    name: 'smoke-20',
    version: 3,
    row_count: 20,
    pending_complete_count: 2,
    metric: 'contain',
    owner: 'alice',
    created_at: '2026-08-10T03:00:00Z',
  },
  {
    id: 'ds-pay',
    name: '支付链路问答',
    version: 1,
    row_count: 156,
    pending_complete_count: 0,
    metric: 'rouge_l',
    owner: 'bob',
    created_at: '2026-08-12T07:30:00Z',
  },
  {
    id: 'ds-faq',
    name: 'FAQ-标准问',
    version: 2,
    row_count: 480,
    pending_complete_count: 6,
    metric: 'exact',
    owner: 'alice',
    created_at: '2026-08-14T02:20:00Z',
  },
]

export const MOCK_PENDING_ROWS: DatasetRow[] = [
  {
    row_no: 3,
    question: '',
    reference: '在「设置-账单」中申请',
    context: null,
    source_case_id: 'c-018',
    is_pending: true,
  },
  {
    row_no: 17,
    question: '如何导出上一年度对账单？',
    reference: '',
    context: null,
    source_case_id: 'c-031',
    is_pending: true,
  },
]

export const MOCK_KBS: KnowledgeBase[] = [
  {
    id: 'kb-default',
    name: 'default',
    kind: 'lightrag',
    doc_count: 12,
    is_core: true,
    owner: 'admin',
    // 内置 LightRAG 库默认具备向量投影与重排对比能力，用于解锁知识库工作台对应面板。
    capabilities: { projection: true, rerank_compare: true },
    created_at: '2026-08-01T00:00:00Z',
  },
  {
    id: 'kb-cs',
    name: '外挂客服',
    kind: 'external_chat',
    doc_count: null,
    is_core: false,
    owner: 'alice',
    profile_id: 'p-ragsvc',
    created_at: '2026-08-05T00:00:00Z',
  },
]

export const MOCK_KB_DOCS: KbDocument[] = [
  { doc_id: 'd-01', filename: 'product-manual.pdf', status: 'indexed', size: '2.4 MB', created_at: '2026-08-10' },
  { doc_id: 'd-02', filename: 'faq-2026.md', status: 'indexed', size: '88 KB', created_at: '2026-08-11' },
  { doc_id: 'd-03', filename: 'refund-policy.html', status: 'indexing', size: '41 KB', created_at: '2026-08-12' },
]

export const MOCK_GOLD_QAS: GoldQA[] = [
  {
    id: 'gq-1',
    kb_id: 'kb-default',
    name: 'qa-v1',
    version: 2,
    row_count: 20,
    owner: 'admin',
    created_at: '2026-08-13T02:00:00Z',
  },
  {
    id: 'gq-2',
    kb_id: 'kb-cs',
    name: '客服黄金集',
    version: 1,
    row_count: 64,
    owner: 'alice',
    created_at: '2026-08-15T09:30:00Z',
  },
]

export const MOCK_USERS: AuthUser[] = [
  { id: 'u-admin', username: 'admin', role: 'member', disabled: false, created_at: '2026-08-01T00:00:00Z' },
  { id: 'u-alice', username: 'alice', role: 'member', disabled: false, created_at: '2026-08-02T03:00:00Z' },
  { id: 'u-bob', username: 'bob', role: 'member', disabled: false, created_at: '2026-08-04T06:00:00Z' },
  { id: 'u-boss', username: 'boss', role: 'member', disabled: false, created_at: '2026-08-06T08:00:00Z' },
  { id: 'u-carol', username: 'carol', role: 'member', disabled: true, created_at: '2026-08-07T09:00:00Z' },
]

export const MOCK_SETTINGS: AdminSettings = {
  agent_profile_id: 'p-agent',
  agent_reasoning: { enabled: true, effort: 'medium' },
  max_running_tasks: 3,
  max_inflight_model_calls: 8,
  default_max_usd: 5,
  stress: {
    host_whitelist: ['10.0.0.8', 'api.internal.eval'],
    max_qps: 500,
    max_duration_s: 1800,
    price_per_1k_tokens: 0.002,
  },
  notify: {
    wecom: false,
    email: false,
    webhook: false,
  },
  prod_approvers: ['admin', 'bob'],
}

export const MOCK_WHITELIST: WhitelistItem[] = [
  { id: 'wl-1', host: '10.0.0.8', scope: 'test,staging', creator: 'admin', created_at: '2026-08-01', status: 'active' },
  { id: 'wl-2', host: 'api.internal.eval', scope: 'test', creator: 'admin', created_at: '2026-08-05', status: 'active' },
]

// 内置 MCP 短工具清单（与后端 /api/mcp/tools 保持一致）
export const MOCK_MCP_TOOLS: McpTool[] = [
  { name: 'audio.speech_recognition', desc: '将本轮 wav/mp3 音频识别为文本', permission: 'write', enabled: true, source: 'builtin' },
  { name: 'audio.speech_synthesis', desc: '按文本与风格生成语音文件', permission: 'write', enabled: true, source: 'builtin' },
  { name: 'audio.voiceclone', desc: '用本轮 wav/mp3 参考音频克隆音色并合成配音', permission: 'write', enabled: true, source: 'builtin' },
  { name: 'image.generate', desc: 'Qwen Image 3.0 文本或参考图生图', permission: 'write', enabled: true, source: 'builtin' },
]

export const MOCK_CASE_SETS: CaseSet[] = [
  {
    id: 'cs-pay',
    task_id: 't-case-1',
    name: 'PRD-支付',
    status: 'generated',
    generated_count: 40,
    confirmed_count: 0,
    expires_in_h: 70.2,
    checks: [
      { level: 'error', code: 'no_core_positive', message: '无核心正向用例' },
      { level: 'error', code: 'missing_constraint_negative', message: '缺约束反向用例' },
    ],
    created_at: '2026-08-17T09:00:00Z',
  },
  {
    id: 'cs-login',
    task_id: 't-case-0',
    name: 'PRD-登录',
    status: 'confirmed',
    generated_count: 32,
    confirmed_count: 26,
    expires_in_h: 0,
    checks: [],
    created_at: '2026-08-16T14:00:00Z',
  },
  {
    id: 'cs-coupon',
    task_id: 't-case-2',
    name: 'PRD-优惠券',
    status: 'cancelled',
    generated_count: 45,
    confirmed_count: 0,
    expires_in_h: 0,
    checks: [],
    created_at: '2026-08-15T11:20:00Z',
  },
]

export const MOCK_TEST_CASES: TestCase[] = [
  { id: 'c-001', strategy: '正向', priority: 'HX', module: '登录', name: '正确账密登录成功', expected: '进入工作台首页', mapped: true, pending: false, selected: true },
  { id: 'c-002', strategy: '正向', priority: 'HX', module: '支付', name: '余额充足时支付成功', expected: '订单状态变为已支付', mapped: true, pending: false, selected: true },
  { id: 'c-003', strategy: '反向', priority: 'YC', module: '登录', name: '错误密码登录', expected: '提示用户名或密码错误', mapped: false, pending: true, selected: false },
  { id: 'c-004', strategy: '反向', priority: 'YC', module: '支付', name: '余额不足支付', expected: '返回余额不足错误码', mapped: true, pending: false, selected: true },
  { id: 'c-005', strategy: '边界', priority: 'BJ', module: '支付', name: '支付金额为 0.01', expected: '允许最小金额支付', mapped: true, pending: false, selected: true },
  { id: 'c-006', strategy: '边界', priority: 'BJ', module: '支付', name: '支付金额达单笔上限', expected: '按限额规则拦截', mapped: false, pending: true, selected: false },
  { id: 'c-007', strategy: '状态', priority: 'FHX', module: '订单', name: '重复提交支付请求', expected: '幂等返回同一订单', mapped: true, pending: false, selected: true },
  { id: 'c-008', strategy: '场景', priority: 'FHX', module: '支付', name: '支付中断网重试', expected: '恢复后可查询最终状态', mapped: true, pending: false, selected: true },
]

export const MOCK_TASKS: Task[] = [
  {
    id: 'a1f3c2',
    kind: 'benchmark',
    status: 'running',
    config: { kind: 'benchmark', profile_ids: ['p-gpt', 'p-claude'], dataset_id: 'ds-smoke' },
    progress: { percent: 40, done: 40, total: 100, message: '正在调用被测 gpt-test' },
    creator: 'alice',
    created_at: new Date(Date.now() - 120 * 1000).toISOString(),
    report_id: null,
    parent_task_id: null,
    events: [
      { id: 1, task_id: 'a1f3c2', event: 'queued', level: 'info', message: '任务已入队排队中', payload: {}, ts: '2026-08-24T12:00:00Z' },
      { id: 2, task_id: 'a1f3c2', event: 'start', level: 'info', message: '任务开始执行', payload: {}, ts: '2026-08-24T12:00:05Z' },
      { id: 3, task_id: 'a1f3c2', event: 'progress', level: 'info', message: '执行中（40/100）', payload: {}, ts: '2026-08-24T12:01:20Z' },
    ],
  },
  {
    id: 'b2e8d1',
    kind: 'rag',
    status: 'succeeded',
    config: { kind: 'rag', kb_id: 'kb-default', gold_qa_id: 'gq-1', rag_mode: ['hybrid'] },
    progress: { done: 20, total: 20, message: '完成' },
    creator: 'bob',
    created_at: new Date(Date.now() - 3700 * 1000).toISOString(),
    report_id: 'r-rag-1',
    parent_task_id: null,
  },
  {
    id: 'c3d9e7',
    kind: 'stress',
    status: 'queued',
    config: { kind: 'stress', stress: { env: 'prod', qps: 200, duration_s: 300, sla_p99_ms: 1500 } },
    progress: { done: 0, total: 1, message: '等待会签' },
    creator: 'bob',
    created_at: new Date(Date.now() - 3600 * 1000).toISOString(),
    report_id: null,
    parent_task_id: 'b2e8d1',
    need_approval: true,
  },
  {
    id: 'd4c1a9',
    kind: 'testcase',
    status: 'awaiting_case_confirm',
    config: { kind: 'testcase', case_source: { text: 'PRD-支付链路' } },
    progress: { done: 1, total: 2, message: '用例已生成，等待确认' },
    creator: 'alice',
    created_at: new Date(Date.now() - 86400 * 1000).toISOString(),
    report_id: null,
    parent_task_id: null,
  },
  {
    id: 'e5f2b8',
    kind: 'benchmark',
    status: 'succeeded',
    config: { kind: 'benchmark', profile_ids: ['p-gpt', 'p-claude'], dataset_id: 'ds-smoke' },
    progress: { done: 20, total: 20, message: '完成' },
    creator: 'alice',
    created_at: new Date(Date.now() - 90000 * 1000).toISOString(),
    report_id: 'r-bm-1',
    parent_task_id: null,
  },
  {
    id: 'f6a7c4',
    kind: 'benchmark',
    status: 'failed',
    config: { kind: 'benchmark', profile_ids: ['p-gpt'], dataset_id: 'ds-faq' },
    progress: { done: 11, total: 100, message: 'UPSTREAM：被测接口持续 5xx' },
    creator: 'bob',
    created_at: new Date(Date.now() - 180000 * 1000).toISOString(),
    report_id: null,
    parent_task_id: null,
  },
  {
    id: 'g7b3d5',
    kind: 'stress',
    status: 'succeeded',
    config: { kind: 'stress', stress: { env: 'test', qps: 120, duration_s: 120 } },
    progress: { done: 1, total: 1, message: '完成' },
    creator: 'alice',
    created_at: new Date(Date.now() - 89000 * 1000).toISOString(),
    report_id: 'r-st-1',
    parent_task_id: 'e5f2b8',
  },
  {
    id: 'h8c4e6',
    kind: 'rag',
    status: 'cancelled',
    config: { kind: 'rag', kb_id: 'kb-cs', gold_qa_id: 'gq-2' },
    progress: { done: 7, total: 20, message: '已被创建者取消' },
    creator: 'alice',
    created_at: new Date(Date.now() - 260000 * 1000).toISOString(),
    report_id: null,
    parent_task_id: null,
  },
]

export const MOCK_REPORTS: Record<string, Report> = {
  'r-bm-1': {
    id: 'r-bm-1',
    task_id: 'e5f2b8',
    kind: 'benchmark',
    created_at: '2026-08-15T06:02:00Z',
    title: 'Benchmark 报告 · smoke-20 v3 · 主指标 contain',
    snapshot: {
      dataset: 'smoke-20',
      dataset_version: 3,
      metric: 'contain',
      sample_size: 20,
      concurrency: 4,
      timeout_s: 60,
      seed: 20260815,
    },
    baseline: {
      task_id: 'e0base88',
      delta: -0.07,
    },
    scores: [
      {
        profile: 'p-gpt',
        profile_name: 'gpt-test',
        contain: 0.86,
        fail_rate: 0.02,
        latency: '820ms',
        judge: 4.2,
      },
      {
        profile: 'p-claude',
        profile_name: 'claude-x',
        contain: 0.79,
        fail_rate: 0.05,
        latency: '1.1s',
        judge: 3.9,
      },
    ],
    failed_items: [
      {
        row: 7,
        question: '如何修改默认结算账户？',
        error: 'UPSTREAM',
        raw: 'HTTP 502 Bad Gateway from upstream endpoint',
      },
      {
        row: 13,
        question: '退款多久到账？',
        error: 'TIMEOUT',
        raw: 'Request timed out after 60s without response',
      },
    ],
  },
  'r-rag-1': {
    id: 'r-rag-1',
    task_id: 'b2e8d1',
    kind: 'rag',
    created_at: '2026-08-17T01:12:00Z',
    title: 'RAG 报告 · default 库 · qa-v1 v2 · K=5',
    k: 5,
    modes: ['naive', 'local', 'global', 'hybrid'],
    rag_scores: {
      naive: { hit: 0.62, mrr: 0.55, recall: 0.7, contain: 0.74 },
      local: { hit: 0.71, mrr: 0.66, recall: 0.78, contain: 0.77 },
      global: { hit: 0.68, mrr: 0.61, recall: 0.75, contain: 0.72 },
      hybrid: { hit: 0.8, mrr: 0.74, recall: 0.85, contain: 0.83 },
    },
    degraded: {
      mode: 'hybrid',
      pp: -6,
    },
    hit_note: '20 条样本中 3 条无 expected_doc_ids，未计入 Hit Rate 分母',
  },
  'r-st-1': {
    id: 'r-st-1',
    task_id: 'g7b3d5',
    kind: 'stress',
    created_at: '2026-08-15T06:40:00Z',
    title: '压测报告 · 继承自任务 e5f2b8 · env=test',
    // 「先评后压」回溯字段：用于报告页展示父质量报告横幅
    parent_task_id: 'e5f2b8',
    parent_report_id: 'r-bm-1',
    env: 'test',
    qps_peak: 118,
    p99: '1.2s',
    error_rate: '0.4%',
    ttft: '320ms',
    tpot: '45ms',
    tokens_per_s: '1.8k',
    est_cost: '$0.42',
    sla_p99_ms: 1500,
    sla_met: true,
    knee: '第 3 分钟首次 P99 > SLA（或错误率 ≥1%）',
    series: [
      { ts: '00:00', qps: 20, rt_ms: 280, error_rate: 0 },
      { ts: '00:30', qps: 55, rt_ms: 320, error_rate: 0 },
      { ts: '01:00', qps: 90, rt_ms: 450, error_rate: 0.001 },
      { ts: '01:30', qps: 118, rt_ms: 780, error_rate: 0.002 },
      { ts: '02:00', qps: 115, rt_ms: 1100, error_rate: 0.004 },
    ],
  },
}

/**
 * 拼装 Mock 模式下的报告 Markdown 文本，模拟服务端 GET /api/reports/{id}?fmt=md 的返回。
 * 仅覆盖标题、关键 KPI 与指标表，供「导出 Markdown」按钮在演示模式下生成下载文件。
 */
export function buildMockReportMarkdown(r: Report): string {
  // 指标值统一保留两位小数，缺失时输出占位符
  const fmtNum = (v?: number) => (v === undefined ? '—' : v.toFixed(2))
  const lines: string[] = [
    `# ${r.title}`,
    '',
    `- 报告 ID: ${r.id}`,
    `- 关联任务: ${r.task_id}`,
    `- 生成时间: ${r.created_at}`,
    '',
  ]

  if (r.kind === 'benchmark' && r.scores?.length) {
    lines.push('## 核心指标', '', '| 协议档 | contain | exact | ROUGE-L | 失败率 | 平均延迟 |', '| --- | --- | --- | --- | --- | --- |')
    for (const s of r.scores) {
      lines.push(
        `| ${s.profile_name || s.profile} | ${fmtNum(s.contain)} | ${fmtNum(s.exact)} | ${fmtNum(s.rouge_l)} | ${((s.fail_rate ?? 0) * 100).toFixed(1)}% | ${s.latency ?? '—'} |`,
      )
    }
    lines.push('')
  }

  if (r.kind === 'rag' && r.rag_scores) {
    lines.push(`## RAG 检索指标 (K=${r.k ?? 5})`, '', '| 检索模式 | Hit Rate | MRR | Recall | Contain |', '| --- | --- | --- | --- | --- |')
    for (const m of r.modes || ['naive', 'local', 'global', 'hybrid']) {
      const sc = r.rag_scores[m]
      lines.push(`| ${m} | ${fmtNum(sc?.hit)} | ${fmtNum(sc?.mrr)} | ${fmtNum(sc?.recall)} | ${fmtNum(sc?.contain)} |`)
    }
    lines.push('')
  }

  if (r.kind === 'stress') {
    lines.push(
      '## 压测 KPI',
      '',
      `- 峰值 QPS: ${r.qps_peak ?? '—'}`,
      `- P99 延迟: ${r.p99 ?? '—'}`,
      `- 请求错误率: ${r.error_rate ?? '—'}`,
      `- TTFT 首字延迟: ${r.ttft ?? '—'}`,
      `- 估算费用: ${r.est_cost ?? '—'}`,
      '',
    )
  }

  return lines.join('\n')
}
