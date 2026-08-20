<template>
  <n-modal
    :show="show"
    preset="card"
    :title="`MCP 工具契约详情 · ${tool?.name || ''}`"
    style="width: 720px; max-width: 95vw; border-radius: 14px"
    @update:show="$emit('update:show', $event)"
  >
    <div v-if="tool" class="mcp-modal-content">
      <!-- 头部概览条 -->
      <div class="tool-modal-header">
        <div class="tool-title-row">
          <span class="tool-icon">{{ meta.icon }}</span>
          <div>
            <div class="row" style="gap: 8px; align-items: center">
              <span class="tool-name mono">{{ tool.name }}</span>
              <span
                class="perm-badge"
                :class="tool.permission === 'write' ? 'perm-write' : 'perm-read'"
              >
                {{ tool.permission === 'write' ? '✍️ WRITE · 受控写入' : '📖 READ · 只读查询' }}
              </span>
              <span class="domain-badge">{{ meta.domain }}</span>
            </div>
            <div class="tool-desc">{{ tool.desc }}</div>
          </div>
        </div>
      </div>

      <!-- 核心规格指标 -->
      <div class="spec-grid">
        <div class="spec-item">
          <span class="spec-label">执行宿主 (Host)</span>
          <span class="spec-value mono">Eval-Core (内置进程内)</span>
        </div>
        <div class="spec-item">
          <span class="spec-label">预估执行耗时</span>
          <span class="spec-value mono text-success">{{ meta.latency }}</span>
        </div>
        <div class="spec-item">
          <span class="spec-label">鉴权策略</span>
          <span class="spec-value">JWT + ws-ticket 单次短票</span>
        </div>
        <div class="spec-item">
          <span class="spec-label">长任务阻塞</span>
          <span class="spec-value text-warning">禁止 (入队后异步执行)</span>
        </div>
      </div>

      <!-- 入参 JSON Schema -->
      <div class="section-block">
        <div class="section-title">
          <span>📥 输入参数规范 (Input Arguments Schema)</span>
          <span class="small tertiary mono">application/json</span>
        </div>
        <div v-if="meta.params && meta.params.length > 0" class="params-table-wrap">
          <table class="params-table">
            <thead>
              <tr>
                <th style="width: 140px">参数字段</th>
                <th style="width: 90px">类型</th>
                <th style="width: 70px">必填</th>
                <th>说明与约束</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="p in meta.params" :key="p.name">
                <td class="mono font-bold">{{ p.name }}</td>
                <td><span class="type-tag mono">{{ p.type }}</span></td>
                <td>
                  <span :class="p.required ? 'text-error font-bold' : 'tertiary'">
                    {{ p.required ? '是' : '否' }}
                  </span>
                </td>
                <td class="small">{{ p.desc }}</td>
              </tr>
            </tbody>
          </table>
        </div>
        <div v-else class="empty-params">
          <span class="tertiary small">无输入参数（直接调用空对象 <code>{}</code>）</span>
        </div>
      </div>

      <!-- 调用示例与返回报文 -->
      <div class="section-block">
        <div class="section-title">
          <span>📤 调用示例与返回报文 (Tool Call & Response Payload)</span>
        </div>
        <div class="code-box-tabs">
          <div class="code-preview-wrap">
            <div class="code-label">Agent ToolCall 请求示例:</div>
            <pre class="json-code"><code>{{ meta.exampleRequest }}</code></pre>
          </div>
          <div class="code-preview-wrap">
            <div class="code-label">Host 返回报文示例 (Output):</div>
            <pre class="json-code"><code>{{ meta.exampleResponse }}</code></pre>
          </div>
        </div>
      </div>

      <!-- 安全与风控约束 -->
      <div class="section-block guardrail-box">
        <div class="guardrail-title">🛡️ 安全与风控契约约束</div>
        <div class="guardrail-desc">{{ meta.securityNote }}</div>
      </div>
    </div>

    <template #footer>
      <div class="row-between" style="width: 100%">
        <span class="small tertiary mono">MCP Protocol Specification · V1.0 Internal Sandbox</span>
        <button class="btn btn-secondary btn-sm" @click="$emit('update:show', false)">关闭</button>
      </div>
    </template>
  </n-modal>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { NModal } from 'naive-ui'
import type { McpTool } from '../../api/types'

// 工具元数据与 JSON Schema 扩展定义
interface ToolParam {
  name: string
  type: string
  required: boolean
  desc: string
}

interface ToolMeta {
  icon: string
  domain: string
  latency: string
  params: ToolParam[]
  exampleRequest: string
  exampleResponse: string
  securityNote: string
}

const props = defineProps<{
  show: boolean
  tool: McpTool | null
}>()

defineEmits<{
  (e: 'update:show', val: boolean): void
}>()

// 7 大受控内置短工具的完备规格字典
const TOOL_META_MAP: Record<string, ToolMeta> = {
  'model.list': {
    icon: '🤖',
    domain: '模型资产治理',
    latency: '< 20ms',
    params: [
      { name: 'usage', type: 'string', required: false, desc: '按用途过滤：target (被测) | judge (裁判) | agent (后台)' },
    ],
    exampleRequest: JSON.stringify({ name: 'model.list', arguments: { usage: 'target' } }, null, 2),
    exampleResponse: JSON.stringify({
      items: [
        { id: 'p-1', name: 'OpenAI GPT-4o', protocol: 'openai', model: 'gpt-4o', usages: ['target', 'agent'] },
        { id: 'p-2', name: 'Claude 3.5 Sonnet', protocol: 'anthropic', model: 'claude-3-5-sonnet', usages: ['target'] },
      ],
      total: 2,
    }, null, 2),
    securityNote: '只读短工具。直接读取系统协议档缓存，不暴露 API Key 等机密凭据，免审批直接放行。',
  },
  'dataset.list': {
    icon: '📚',
    domain: '基准数据集',
    latency: '< 30ms',
    params: [
      { name: 'kind', type: 'string', required: false, desc: '评测类别：benchmark (通用) | rag (知识库) | cases (用例)' },
      { name: 'search', type: 'string', required: false, desc: '数据集名称或标签模糊匹配关键字' },
    ],
    exampleRequest: JSON.stringify({ name: 'dataset.list', arguments: { kind: 'benchmark' } }, null, 2),
    exampleResponse: JSON.stringify({
      items: [
        { id: 'ds-gsm8k', name: 'GSM8K-数学推理', sample_count: 500, version: 'v1.0' },
        { id: 'ds-humaneval', name: 'HumanEval-代码生成', sample_count: 164, version: 'v2.1' },
      ],
      total: 2,
    }, null, 2),
    securityNote: '只读短工具。返回数据集元数据与样本量统计，不回传海量原始文本，防范上下文超限。',
  },
  'kb.list': {
    icon: '🧠',
    domain: '知识库与 QA 资产',
    latency: '< 25ms',
    params: [
      { name: 'search', type: 'string', required: false, desc: '知识库名称关键字检索' },
    ],
    exampleRequest: JSON.stringify({ name: 'kb.list', arguments: {} }, null, 2),
    exampleResponse: JSON.stringify({
      items: [
        { id: 'kb-finance-2026', name: '2026金融合规知识库', doc_count: 12, chunk_count: 420, gold_qa_count: 85 },
      ],
      total: 1,
    }, null, 2),
    securityNote: '只读短工具。查询知识库索引与挂载的黄金 QA 概览，支持 RAG 意图识别与评测集关联。',
  },
  'report.get': {
    icon: '📊',
    domain: '评测报告解读',
    latency: '< 35ms',
    params: [
      { name: 'report_id', type: 'string', required: true, desc: '待查询的评测报告唯一标识 (UUID/ID)' },
    ],
    exampleRequest: JSON.stringify({ name: 'report.get', arguments: { report_id: 'rep-20260819-01' } }, null, 2),
    exampleResponse: JSON.stringify({
      report_id: 'rep-20260819-01',
      task_id: 't-9821',
      kind: 'benchmark',
      metrics: { accuracy: 0.885, latency_p95_ms: 320, token_tps: 45.2 },
      generated_at: '2026-08-19T14:30:00Z',
    }, null, 2),
    securityNote: '只读短工具。提取报告关键指标快照与聚合分析，用于 Agent 在对话中进行多模态/多模型对比解读。',
  },
  'task.create': {
    icon: '🚀',
    domain: '任务中心与调度',
    latency: '< 45ms',
    params: [
      { name: 'kind', type: 'string', required: true, desc: '任务类型：benchmark | rag | cases' },
      { name: 'config', type: 'object', required: true, desc: '完整 TaskSpec 配置（被测模型、裁判、抽样量、压测开关等）' },
      { name: 'with_stress', type: 'boolean', required: false, desc: '质量评测成功后是否自动派生压测任务 (默认 false)' },
    ],
    exampleRequest: JSON.stringify({
      name: 'task.create',
      arguments: {
        kind: 'benchmark',
        config: { target_model_ids: ['p-1', 'p-2'], dataset_id: 'ds-gsm8k', sample_size: 50 },
        with_stress: true,
      },
    }, null, 2),
    exampleResponse: JSON.stringify({
      task_id: 't-20260820-0012',
      status: 'queued',
      message: '任务已成功入队排队',
      created_at: '2026-08-20T20:45:00Z',
    }, null, 2),
    securityNote: '受控写入工具 (WRITE)。必须经由用户确认卡显式授权，采用 Pydantic 严格校验 TaskSpec；严禁在 Agent Host 同步执行评测。',
  },
  'task.cancel': {
    icon: '🛑',
    domain: '任务中心与调度',
    latency: '< 20ms',
    params: [
      { name: 'task_id', type: 'string', required: true, desc: '需要取消或熔断的目标任务 ID' },
      { name: 'reason', type: 'string', required: false, desc: '取消原因说明（用于记录操作审计日志）' },
    ],
    exampleRequest: JSON.stringify({ name: 'task.cancel', arguments: { task_id: 't-20260820-0012', reason: '用户手动中止' } }, null, 2),
    exampleResponse: JSON.stringify({
      task_id: 't-20260820-0012',
      status: 'canceled',
      message: '任务已标记取消',
    }, null, 2),
    securityNote: '受控写入工具 (WRITE)。触发 Worker 熔断信号（质量任务当前样本后安全退出，压测任务即刻停发）。',
  },
  'dispatch.overview': {
    icon: '🖥️',
    domain: '调度与算力大盘',
    latency: '< 25ms',
    params: [],
    exampleRequest: JSON.stringify({ name: 'dispatch.overview', arguments: {} }, null, 2),
    exampleResponse: JSON.stringify({
      workers: [
        { id: 'worker-01', status: 'online', load_percent: 24, running_tasks: 1 },
        { id: 'worker-02', status: 'online', load_percent: 42, running_tasks: 2 },
      ],
      queue_depth: 3,
      avg_latency_ms: 18,
    }, null, 2),
    securityNote: '只读短工具。实时读取 Worker 节点健康、显存负载与排队深度，为 Agent 分发建议提供决策依据。',
  },
}

const meta = computed<ToolMeta>(() => {
  if (!props.tool) {
    return {
      icon: '🛠️',
      domain: '通用短工具',
      latency: '< 30ms',
      params: [],
      exampleRequest: '{}',
      exampleResponse: '{}',
      securityNote: '受控内置短工具，严格遵循沙箱策略。',
    }
  }
  return (
    TOOL_META_MAP[props.tool.name] || {
      icon: '🛠️',
      domain: '系统内置',
      latency: '< 30ms',
      params: [],
      exampleRequest: JSON.stringify({ name: props.tool.name, arguments: {} }, null, 2),
      exampleResponse: JSON.stringify({ status: 'succeeded' }, null, 2),
      securityNote: '内置短工具，遵循严格沙箱与输入校验。',
    }
  )
})
</script>

<style scoped>
.mcp-modal-content {
  display: flex;
  flex-direction: column;
  gap: 16px;
}
.tool-modal-header {
  padding: 12px 14px;
  background: var(--bg-elevated, #f4f8f8);
  border-radius: 10px;
  border: 1px solid var(--border-subtle, #e5e7eb);
}
.tool-title-row {
  display: flex;
  gap: 12px;
  align-items: flex-start;
}
.tool-icon {
  font-size: 28px;
  line-height: 1;
}
.tool-name {
  font-size: 16px;
  font-weight: 700;
  color: var(--c-profiles, #b45309);
}
.perm-badge {
  font-size: 11px;
  padding: 2px 8px;
  border-radius: 6px;
  font-weight: 600;
}
.perm-read {
  background: rgba(16, 185, 129, 0.12);
  color: var(--accent-success, #10b981);
  border: 1px solid rgba(16, 185, 129, 0.3);
}
.perm-write {
  background: rgba(245, 158, 11, 0.12);
  color: var(--accent-warning, #f59e0b);
  border: 1px solid rgba(245, 158, 11, 0.3);
}
.domain-badge {
  font-size: 11px;
  background: rgba(99, 102, 241, 0.08);
  color: var(--accent-ai, #6366f1);
  padding: 2px 8px;
  border-radius: 6px;
  font-weight: 500;
  border: 1px solid rgba(99, 102, 241, 0.18);
}
.tool-desc {
  font-size: 12.5px;
  color: var(--text-secondary, #6b7280);
  margin-top: 4px;
  line-height: 1.5;
}
.spec-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
  gap: 10px;
}
.spec-item {
  display: flex;
  flex-direction: column;
  gap: 3px;
  padding: 8px 12px;
  border: 1px solid var(--border-subtle, #e5e7eb);
  border-radius: 8px;
  background: var(--bg-main, #ffffff);
}
.spec-label {
  font-size: 11px;
  color: var(--text-tertiary, #9ca3af);
}
.spec-value {
  font-size: 12.5px;
  font-weight: 600;
  color: var(--text-primary, #111827);
}
.text-success {
  color: var(--accent-success, #10b981);
}
.text-warning {
  color: var(--accent-warning, #f59e0b);
}
.text-error {
  color: var(--accent-error, #ef4444);
}
.section-block {
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.section-title {
  display: flex;
  align-items: center;
  justify-content: space-between;
  font-size: 13px;
  font-weight: 600;
  color: var(--text-primary, #111827);
}
.params-table-wrap {
  border: 1px solid var(--border-subtle, #e5e7eb);
  border-radius: 8px;
  overflow: hidden;
}
.params-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 12px;
}
.params-table th {
  background: var(--bg-elevated, #f4f8f8);
  padding: 6px 10px;
  text-align: left;
  font-weight: 600;
  color: var(--text-secondary, #6b7280);
  border-bottom: 1px solid var(--border-subtle, #e5e7eb);
}
.params-table td {
  padding: 8px 10px;
  border-bottom: 1px solid var(--border-subtle, #e5e7eb);
  color: var(--text-primary, #111827);
}
.params-table tr:last-child td {
  border-bottom: none;
}
.type-tag {
  background: rgba(15, 23, 42, 0.06);
  padding: 1px 5px;
  border-radius: 4px;
  font-size: 11px;
  color: var(--accent-ai, #6366f1);
}
.empty-params {
  padding: 12px;
  text-align: center;
  background: var(--bg-elevated, #f4f8f8);
  border-radius: 8px;
  border: 1px dashed var(--border-subtle, #e5e7eb);
}
.code-box-tabs {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 10px;
}
@media (max-width: 600px) {
  .code-box-tabs {
    grid-template-columns: 1fr;
  }
}
.code-preview-wrap {
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.code-label {
  font-size: 11px;
  font-weight: 600;
  color: var(--text-secondary, #6b7280);
}
.json-code {
  margin: 0;
  padding: 10px;
  background: #0f172a;
  color: #38bdf8;
  border-radius: 8px;
  font-family: var(--font-mono, monospace);
  font-size: 11.5px;
  line-height: 1.45;
  max-height: 160px;
  overflow: auto;
}
.guardrail-box {
  background: rgba(99, 102, 241, 0.05);
  border: 1px solid rgba(99, 102, 241, 0.18);
  border-radius: 8px;
  padding: 10px 12px;
}
.guardrail-title {
  font-size: 12px;
  font-weight: 700;
  color: var(--accent-ai, #6366f1);
  margin-bottom: 4px;
}
.guardrail-desc {
  font-size: 12px;
  color: var(--text-secondary, #6b7280);
  line-height: 1.5;
}
</style>
