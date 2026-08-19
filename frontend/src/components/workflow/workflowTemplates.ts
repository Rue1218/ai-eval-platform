/**
 * AI 测试与评估平台 — 预置工作流模板与节点注册元数据 (workflowTemplates.ts)
 * 依据：PRD §5.5 调度中心、§5.8 前端信息架构、API V1.3 §3.13 与 §3.8
 */
import type { NodeMeta, WorkflowNode, WorkflowTemplate, WorkflowNodeType } from './workflowTypes'

/** 节点元数据注册表（用于左侧物料库与新节点实例化） */
export const NODE_METAS: Record<WorkflowNodeType, NodeMeta> = {
  agent_kernel: {
    type: 'agent_kernel',
    category: 'trigger',
    name: 'Agent 调度内核',
    description: '意图识别、路由拆解、分发策略与并发心跳治理',
    icon: '🛰',
    color: 'var(--c-agent)',
    defaultInputs: [],
    defaultOutputs: [
      { id: 'out_bm', label: '基准路由', type: 'worker_signal', direction: 'output', description: '基准评测任务分发' },
      { id: 'out_rag', label: 'RAG 路由', type: 'worker_signal', direction: 'output', description: 'RAG 检索任务分发' },
      { id: 'out_stress', label: '压测路由', type: 'worker_signal', direction: 'output', description: '共享压测任务分发' },
    ],
    defaultConfig: {
      strategy: '负载均衡',
      max_running_tasks: 4,
      heartbeat_ms: 500,
      enable_auto_retry: true,
    },
  },
  worker_target: {
    type: 'worker_target',
    category: 'trigger',
    name: 'Worker 执行节点',
    description: '绑定指定 Worker 计算节点或专精能力池',
    icon: '💻',
    color: 'var(--c-agent)',
    defaultInputs: [{ id: 'in', label: '任务调度', type: 'worker_signal', direction: 'input', required: true }],
    defaultOutputs: [{ id: 'out', label: '执行管道', type: 'worker_signal', direction: 'output' }],
    defaultConfig: {
      worker_id: 'worker-01',
      name: 'GPU-Node-A1',
      caps: ['benchmark', 'judge'],
      weight: 100,
    },
  },
  dataset_source: {
    type: 'dataset_source',
    category: 'data',
    name: '基准数据集',
    description: '引入基准评测数据集与金标数据，支持样本抽样',
    icon: '📚',
    color: 'var(--c-datasets)',
    defaultInputs: [],
    defaultOutputs: [{ id: 'out', label: '样本流', type: 'dataset', direction: 'output' }],
    defaultConfig: {
      dataset_id: 'ds-1',
      dataset_name: 'smoke-20 基准评测集',
      sample_size: 100,
      metric: 'contain',
      auto_complete: false,
    },
  },
  case_gen: {
    type: 'case_gen',
    category: 'data',
    name: 'PRD 智能用例生成',
    description: '从 PRD 需求生成 6 大测试策略用例并支持入库映射',
    icon: '🧩',
    color: 'var(--c-cases)',
    defaultInputs: [],
    defaultOutputs: [{ id: 'out', label: '用例集', type: 'case_set', direction: 'output' }],
    defaultConfig: {
      name: 'PRD 智能用例生成',
      prd_text: '支持微信、支付宝、银联支付，失败自动重试3次并落审计日志...',
      strategy_weights: { equiv: 25, boundary: 25, cause: 15, error: 15, state: 10, ortho: 10 },
      mapping_target: 'dataset',
      target_id: '',
      auto_confirm: true,
    },
  },
  benchmark_eval: {
    type: 'benchmark_eval',
    category: 'eval',
    name: '大模型基准评测',
    description: '三大协议多模型横向对比评测（openai_chat/anthropic）',
    icon: '📊',
    color: 'var(--c-tasks)',
    defaultInputs: [
      { id: 'in_ds', label: '数据集', type: 'dataset', direction: 'input', required: false },
      { id: 'in_sig', label: '调度触发', type: 'worker_signal', direction: 'input', required: false },
    ],
    defaultOutputs: [{ id: 'out', label: '评测结果', type: 'eval_result', direction: 'output' }],
    defaultConfig: {
      profile_ids: ['p-gpt4o', 'p-claude-35'],
      temperature: 0.0,
      max_usd: 5.0,
      concurrency: 4,
      with_stress: true,
    },
  },
  rag_eval: {
    type: 'rag_eval',
    category: 'eval',
    name: 'RAG 知识库评测',
    description: 'LightRAG 4 模式检索评测与黄金 QA 召回质量质检',
    icon: '🔍',
    color: 'var(--c-kb)',
    defaultInputs: [{ id: 'in_sig', label: '调度触发', type: 'worker_signal', direction: 'input', required: false }],
    defaultOutputs: [{ id: 'out', label: 'RAG 结果', type: 'eval_result', direction: 'output' }],
    defaultConfig: {
      kb_id: 'kb-default',
      kb_name: '核心知识库',
      gold_qa_id: 'qa-v1',
      rag_modes: ['hybrid', 'local', 'global'],
      top_k: 5,
      rerank_delta: true,
      concurrency: 4,
    },
  },
  llm_judge: {
    type: 'llm_judge',
    category: 'eval',
    name: '大模型裁判 (LLM Judge)',
    description: '使用高阶裁判模型对问答与生成内容进行质量打分',
    icon: '⚖️',
    color: 'var(--c-profiles)',
    defaultInputs: [{ id: 'in', label: '被评内容', type: 'eval_result', direction: 'input', required: true }],
    defaultOutputs: [{ id: 'out', label: '裁判评分', type: 'eval_result', direction: 'output' }],
    defaultConfig: {
      judge_profile_id: 'p-gpt4o',
      judge_prompt: '请严格根据参考答案打分（0-5分），重点关注事实准确性与完整性。',
      pass_score: 4.0,
    },
  },
  quality_gate: {
    type: 'quality_gate',
    category: 'gate_stress',
    name: '质量门禁 (Gate)',
    description: '条件分支判定：达标自动触发压测，不达标报警阻断',
    icon: '🔀',
    color: 'var(--accent-warning)',
    defaultInputs: [{ id: 'in', label: '质检输入', type: 'eval_result', direction: 'input', required: true }],
    defaultOutputs: [
      { id: 'pass', label: '达标 (Pass)', type: 'gate_passed', direction: 'output', description: '质量达标，触发压测' },
      { id: 'fail', label: '未达标 (Fail)', type: 'gate_failed', direction: 'output', description: '质量不达标，阻断告警' },
    ],
    defaultConfig: {
      metric: 'contain_rate',
      operator: '>=',
      threshold: 85,
    },
  },
  stress_test: {
    type: 'stress_test',
    category: 'gate_stress',
    name: '共享压测引擎',
    description: 'go-stress-testing 阶梯发压与 SLA 拐点定位（先评后压）',
    icon: '⚡',
    color: 'var(--c-stress)',
    defaultInputs: [
      { id: 'in_gate', label: '门禁放行', type: 'gate_passed', direction: 'input', required: false },
      { id: 'in_sig', label: '调度触发', type: 'worker_signal', direction: 'input', required: false },
    ],
    defaultOutputs: [{ id: 'out', label: '压测指标', type: 'eval_result', direction: 'output' }],
    defaultConfig: {
      env: 'test',
      qps: 20,
      duration_seconds: 60,
      concurrency: 10,
      sla_p99_ms: 1500,
      sla_error_rate: 0.01,
    },
  },
  eval_report: {
    type: 'eval_report',
    category: 'output',
    name: '评测与压测报告',
    description: '汇总全链路指标，生成雷达图对比、多轴压测曲线与导出',
    icon: '📑',
    color: 'var(--c-reports)',
    defaultInputs: [{ id: 'in', label: '指标输入', type: 'any', direction: 'input', required: true }],
    defaultOutputs: [],
    defaultConfig: {
      format: 'all',
      auto_share: true,
      webhook_notify: false,
    },
  },
}

/** 实例化新节点辅助函数 */
export function createNode(type: WorkflowNodeType, x = 100, y = 100): WorkflowNode {
  const meta = NODE_METAS[type]
  const uid = 'n_' + type.slice(0, 4) + '_' + Math.random().toString(36).substring(2, 7)
  return {
    id: uid,
    type,
    category: meta.category,
    name: meta.name,
    description: meta.description,
    icon: meta.icon,
    color: meta.color,
    x,
    y,
    inputs: JSON.parse(JSON.stringify(meta.defaultInputs)),
    outputs: JSON.parse(JSON.stringify(meta.defaultOutputs)),
    config: JSON.parse(JSON.stringify(meta.defaultConfig)),
    status: 'idle',
  }
}

/** 四大内置工作流模板（采用自然清晰的两层式/分支式拓扑，屏幕自适应居中） */
export const WORKFLOW_TEMPLATES: WorkflowTemplate[] = [
  {
    id: 'tpl_benchmark_stress',
    name: '标准先评后压全链路',
    category: 'benchmark',
    description: '基准数据集 → 多模型对比评测 → LLM Judge 裁判打分 → 质量门禁 (>=85%) → 阶梯压测 → 综合报告',
    icon: '📊',
    badgeText: '推荐 · 闭环',
    nodes: [
      // 第一行：评测与质检主链路
      {
        ...createNode('dataset_source', 60, 80),
        id: 'node-bm-ds',
        name: '基准数据集 (smoke-20)',
        config: { dataset_id: 'ds-1', dataset_name: 'smoke-20 基准评测集', sample_size: 100, metric: 'contain' },
      },
      {
        ...createNode('benchmark_eval', 390, 80),
        id: 'node-bm-eval',
        name: '大模型基准评测 (横向对比)',
        config: { profile_ids: ['p-gpt4o', 'p-claude-35'], temperature: 0.0, max_usd: 5.0, concurrency: 4, with_stress: true },
      },
      {
        ...createNode('llm_judge', 720, 80),
        id: 'node-bm-judge',
        name: '大模型裁判 (GPT-4o 质检)',
        config: { judge_profile_id: 'p-gpt4o', pass_score: 4.0 },
      },
      {
        ...createNode('quality_gate', 1050, 80),
        id: 'node-bm-gate',
        name: '质量门禁 (准确率 >= 85%)',
        config: { metric: 'contain_rate', operator: '>=', threshold: 85 },
      },
      // 第二行：门禁放行后的压测与报告
      {
        ...createNode('stress_test', 1050, 290),
        id: 'node-bm-stress',
        name: '共享压测 (20 QPS 阶梯发压)',
        config: { env: 'test', qps: 20, duration_seconds: 60, concurrency: 10, sla_p99_ms: 1500 },
      },
      {
        ...createNode('eval_report', 1380, 290),
        id: 'node-bm-rep',
        name: '综合评测报告',
        config: { format: 'all', auto_share: true },
      },
    ],
    edges: [
      { id: 'e1', sourceNodeId: 'node-bm-ds', sourcePortId: 'out', targetNodeId: 'node-bm-eval', targetPortId: 'in_ds', label: '样本流' },
      { id: 'e2', sourceNodeId: 'node-bm-eval', sourcePortId: 'out', targetNodeId: 'node-bm-judge', targetPortId: 'in', label: '评测结果' },
      { id: 'e3', sourceNodeId: 'node-bm-judge', sourcePortId: 'out', targetNodeId: 'node-bm-gate', targetPortId: 'in', label: '裁判评分' },
      { id: 'e4', sourceNodeId: 'node-bm-gate', sourcePortId: 'pass', targetNodeId: 'node-bm-stress', targetPortId: 'in_gate', label: '✓ 门禁通过' },
      { id: 'e5', sourceNodeId: 'node-bm-stress', sourcePortId: 'out', targetNodeId: 'node-bm-rep', targetPortId: 'in', label: '压测指标' },
    ],
  },
  {
    id: 'tpl_rag_eval_stress',
    name: 'RAG 知识库检索质检与压测',
    category: 'rag',
    description: '知识库 & 黄金 QA → LightRAG 4 模式检索评估 → 召回门禁 (Hit Rate >= 80%) → query 接口压测',
    icon: '🔍',
    badgeText: 'RAG 专项',
    nodes: [
      // 第一行
      {
        ...createNode('rag_eval', 60, 80),
        id: 'node-rag-eval',
        name: 'LightRAG 4 模式检索评测',
        config: { kb_id: 'kb-default', kb_name: '技术文档知识库', gold_qa_id: 'qa-v1', rag_modes: ['hybrid', 'local', 'global', 'naive'], top_k: 5, rerank_delta: true },
      },
      {
        ...createNode('llm_judge', 390, 80),
        id: 'node-rag-judge',
        name: 'RAG 问答质量裁判',
        config: { judge_profile_id: 'p-gpt4o', pass_score: 4.2 },
      },
      {
        ...createNode('quality_gate', 720, 80),
        id: 'node-rag-gate',
        name: '召回门禁 (Hit Rate >= 80%)',
        config: { metric: 'hit_rate', operator: '>=', threshold: 80 },
      },
      // 第二行
      {
        ...createNode('stress_test', 720, 290),
        id: 'node-rag-stress',
        name: 'RAG Query 接口压测',
        config: { env: 'test', qps: 15, duration_seconds: 90, concurrency: 8, sla_p99_ms: 2000 },
      },
      {
        ...createNode('eval_report', 1050, 290),
        id: 'node-rag-rep',
        name: 'RAG 质检与性能报告',
        config: { format: 'all', auto_share: true },
      },
    ],
    edges: [
      { id: 're1', sourceNodeId: 'node-rag-eval', sourcePortId: 'out', targetNodeId: 'node-rag-judge', targetPortId: 'in', label: '问答流' },
      { id: 're2', sourceNodeId: 'node-rag-judge', sourcePortId: 'out', targetNodeId: 'node-rag-gate', targetPortId: 'in', label: '质检评分' },
      { id: 're3', sourceNodeId: 'node-rag-gate', sourcePortId: 'pass', targetNodeId: 'node-rag-stress', targetPortId: 'in_gate', label: '✓ 召回达标' },
      { id: 're4', sourceNodeId: 'node-rag-stress', sourcePortId: 'out', targetNodeId: 'node-rag-rep', targetPortId: 'in', label: '性能报告' },
    ],
  },
  {
    id: 'tpl_case_gen_dataset',
    name: 'PRD 智能用例生成至数据集入库',
    category: 'cases',
    description: 'PRD 需求文本 → 6 大测试策略用例生成 → 覆盖度门禁 → 自动映射转为基准数据集 → 快速冒烟评测',
    icon: '🧩',
    badgeText: '用例生成',
    nodes: [
      // 第一行
      {
        ...createNode('case_gen', 60, 80),
        id: 'node-case-gen',
        name: 'PRD 6 大策略用例生成',
        config: { name: '支付中心 PRD 用例生成', prd_text: '支持微信、支付宝、银联支付，失败自动重试3次并落审计日志...', strategy_weights: { equiv: 25, boundary: 25, cause: 15, error: 15, state: 10, ortho: 10 }, mapping_target: 'dataset' },
      },
      {
        ...createNode('quality_gate', 390, 80),
        id: 'node-case-gate',
        name: '策略覆盖率门禁 (100%)',
        config: { metric: 'strategy_coverage', operator: '>=', threshold: 100 },
      },
      {
        ...createNode('dataset_source', 720, 80),
        id: 'node-case-ds',
        name: '自动入库基准数据集',
        config: { dataset_name: '支付中心冒烟测试集 (PRD 生成)', sample_size: 50, metric: 'contain' },
      },
      // 第二行
      {
        ...createNode('benchmark_eval', 720, 290),
        id: 'node-case-bm',
        name: '冒烟基准评测',
        config: { profile_ids: ['p-gpt4o'], temperature: 0.0, concurrency: 2 },
      },
      {
        ...createNode('eval_report', 1050, 290),
        id: 'node-case-rep',
        name: '用例与评测报告',
        config: { format: 'all', auto_share: true },
      },
    ],
    edges: [
      { id: 'ce1', sourceNodeId: 'node-case-gen', sourcePortId: 'out', targetNodeId: 'node-case-gate', targetPortId: 'in', label: '生成候选' },
      { id: 'ce2', sourceNodeId: 'node-case-gate', sourcePortId: 'pass', targetNodeId: 'node-case-ds', targetPortId: 'out', label: '✓ 覆盖达标' },
      { id: 'ce3', sourceNodeId: 'node-case-ds', sourcePortId: 'out', targetNodeId: 'node-case-bm', targetPortId: 'in_ds', label: '入库样本' },
      { id: 'ce4', sourceNodeId: 'node-case-bm', sourcePortId: 'out', targetNodeId: 'node-case-rep', targetPortId: 'in', label: '评测汇总' },
    ],
  },
  {
    id: 'tpl_agent_dispatch_cluster',
    name: '多 Agent 协同与 Worker 负载编排',
    category: 'agent',
    description: 'Agent 调度内核 → 意图路由 → 专用 Worker 节点池 (GPU/Vec/Stress) → 多任务并行分发',
    icon: '🛰',
    badgeText: '调度集群',
    nodes: [
      {
        ...createNode('agent_kernel', 60, 190),
        id: 'node-kernel',
        name: '调度内核 (Kernel)',
        config: { strategy: '负载均衡', max_running_tasks: 4, heartbeat_ms: 500 },
      },
      // Worker 专精节点列
      {
        ...createNode('worker_target', 390, 60),
        id: 'node-w-gpu',
        name: 'GPU 计算节点 (worker-01)',
        config: { worker_id: 'worker-01', name: 'GPU-Node-A1', caps: ['benchmark', 'judge'], weight: 100 },
      },
      {
        ...createNode('worker_target', 390, 190),
        id: 'node-w-vec',
        name: '向量计算节点 (worker-02)',
        config: { worker_id: 'worker-02', name: 'Vec-Node-V1', caps: ['rag', 'vector'], weight: 100 },
      },
      {
        ...createNode('worker_target', 390, 320),
        id: 'node-w-stress',
        name: '压测发压节点 (worker-04)',
        config: { worker_id: 'worker-04', name: 'Stress-Node-S1', caps: ['stress', 'load'], weight: 120 },
      },
      // 任务工作流列
      {
        ...createNode('benchmark_eval', 720, 60),
        id: 'node-w-bm',
        name: '基准评测工作流',
        config: { profile_ids: ['p-gpt4o', 'p-claude-35'], concurrency: 4 },
      },
      {
        ...createNode('rag_eval', 720, 190),
        id: 'node-w-rag',
        name: 'RAG 检索工作流',
        config: { kb_id: 'kb-default', rag_modes: ['hybrid'], top_k: 5 },
      },
      {
        ...createNode('stress_test', 720, 320),
        id: 'node-w-st',
        name: '性能压测工作流',
        config: { env: 'test', qps: 30, duration_seconds: 60 },
      },
      // 汇总列
      {
        ...createNode('eval_report', 1050, 190),
        id: 'node-w-rep',
        name: '集群总览报告',
        config: { format: 'all', auto_share: true },
      },
    ],
    edges: [
      { id: 'ae1', sourceNodeId: 'node-kernel', sourcePortId: 'out_bm', targetNodeId: 'node-w-gpu', targetPortId: 'in', label: '基准路由' },
      { id: 'ae2', sourceNodeId: 'node-kernel', sourcePortId: 'out_rag', targetNodeId: 'node-w-vec', targetPortId: 'in', label: 'RAG 路由' },
      { id: 'ae3', sourceNodeId: 'node-kernel', sourcePortId: 'out_stress', targetNodeId: 'node-w-stress', targetPortId: 'in', label: '压测路由' },
      { id: 'ae4', sourceNodeId: 'node-w-gpu', sourcePortId: 'out', targetNodeId: 'node-w-bm', targetPortId: 'in_sig', label: 'GPU 管道' },
      { id: 'ae5', sourceNodeId: 'node-w-vec', sourcePortId: 'out', targetNodeId: 'node-w-rag', targetPortId: 'in_sig', label: 'Vec 管道' },
      { id: 'ae6', sourceNodeId: 'node-w-stress', sourcePortId: 'out', targetNodeId: 'node-w-st', targetPortId: 'in_sig', label: '发压管道' },
      { id: 'ae7', sourceNodeId: 'node-w-bm', sourcePortId: 'out', targetNodeId: 'node-w-rep', targetPortId: 'in', label: '评测指标' },
      { id: 'ae8', sourceNodeId: 'node-w-rag', sourcePortId: 'out', targetNodeId: 'node-w-rep', targetPortId: 'in', label: '召回指标' },
      { id: 'ae9', sourceNodeId: 'node-w-st', sourcePortId: 'out', targetNodeId: 'node-w-rep', targetPortId: 'in', label: '压测指标' },
    ],
  },
]
