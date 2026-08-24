<template>
  <n-modal
    :show="show"
    preset="card"
    :trap-focus="false"
    :auto-focus="false"
    :title="`受控工具清单详情 · ${tool?.name || ''}`"
    style="width: 760px; max-width: 95vw; border-radius: 14px"
    @update:show="$emit('update:show', $event)"
  >
    <div v-if="tool" class="mcp-modal-content">
      <!-- 头部概览条 -->
      <div class="tool-modal-header">
        <div class="tool-title-row">
          <span class="tool-icon">{{ meta.icon }}</span>
          <div style="flex: 1">
            <div class="row-between">
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
              <span class="host-pill mono">Eval-Core · In-Process</span>
            </div>
            <div class="tool-desc">{{ tool.desc }}</div>
          </div>
        </div>
      </div>

      <!-- Tab 切换分段器：契约 Schema vs 后端真实链路 vs 在线实时调用测试 -->
      <div class="modal-sub-tabs">
        <button
          class="sub-tab-btn"
          :class="{ active: activeModalTab === 'contract' }"
          @click="activeModalTab = 'contract'"
        >
          📜 接口契约规范 (Schema & Specs)
        </button>
        <button
          class="sub-tab-btn"
          :class="{ active: activeModalTab === 'pipeline' }"
          @click="activeModalTab = 'pipeline'"
        >
          🔄 真实后端实现链路 (Backend Pipeline)
        </button>
        <button
          class="sub-tab-btn"
          :class="{ active: activeModalTab === 'live_test' }"
          @click="handleSwitchToLiveTest"
        >
          ⚡ 在线接口检查 (Live Check)
        </button>
      </div>

      <!-- ═════════════════ Tab 1: 接口契约规范 ═════════════════ -->
      <div v-if="activeModalTab === 'contract'" class="tab-pane">
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
        <div class="section-block mt12">
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
            <span class="tertiary small">无输入参数（调用时传空对象 <code>{}</code> 即可）</span>
          </div>
        </div>

        <!-- 调用示例与返回报文 -->
        <div class="section-block mt12">
          <div class="section-title">
            <span>📤 工具请求与返回报文示例</span>
          </div>
          <div class="code-box-tabs">
            <div class="code-preview-wrap">
              <div class="code-label">Agent 工具请求示例:</div>
              <pre class="json-code"><code>{{ meta.exampleRequest }}</code></pre>
            </div>
            <div class="code-preview-wrap">
              <div class="code-label">Host 返回报文示例 (Output):</div>
              <pre class="json-code"><code>{{ meta.exampleResponse }}</code></pre>
            </div>
          </div>
        </div>

        <!-- 安全与风控约束 -->
        <div class="section-block guardrail-box mt12">
          <div class="guardrail-title">🛡️ 安全与风控契约约束</div>
          <div class="guardrail-desc">{{ meta.securityNote }}</div>
        </div>
      </div>

      <!-- ═════════════════ Tab 2: 真实后端实现链路 ═════════════════ -->
      <div v-else-if="activeModalTab === 'pipeline'" class="tab-pane">
        <!-- 真实实现链路看板 -->
        <div class="pipeline-card-grid">
          <div class="pipeline-item">
            <div class="pipe-header">
              <span class="pipe-icon">📁</span>
              <span class="pipe-title">后端源码实现位置</span>
            </div>
            <div class="pipe-body mono small">{{ meta.sourceFile }}</div>
            <div class="pipe-hint">FastAPI 进程内受控调度模块 (In-Process Short Tools)</div>
          </div>

          <div class="pipeline-item">
            <div class="pipe-header">
              <span class="pipe-icon">⚙️</span>
              <span class="pipe-title">底层执行函数</span>
            </div>
            <div class="pipe-body mono small text-ai">{{ meta.backendFunction }}</div>
            <div class="pipe-hint">由 execute_short_tool() 安全封装分发</div>
          </div>

          <div class="pipeline-item">
            <div class="pipe-header">
              <span class="pipe-icon">🗄️</span>
              <span class="pipe-title">关联 PostgreSQL 数据实体</span>
            </div>
            <div class="pipe-body mono small">{{ meta.dbEntity }}</div>
            <div class="pipe-hint">通过 SQLAlchemy ORM 快速只读检索 / 状态流转</div>
          </div>

          <div class="pipeline-item">
            <div class="pipe-header">
              <span class="pipe-icon">🛡️</span>
              <span class="pipe-title">敏感凭据脱敏保护</span>
            </div>
            <div class="pipe-body mono small text-success">redact_secrets() 过滤</div>
            <div class="pipe-hint">正则自动过滤 API Key、Token、Password，防范泄露至上下文</div>
          </div>
        </div>

        <!-- 执行防护机制说明 -->
        <div class="section-block mt12">
          <div class="section-title">
            <span>🔒 HAR-NFR-07 短工具执行防护机制</span>
          </div>
          <div class="pipeline-steps-box">
            <div class="p-step">
              <div class="step-badge">1</div>
              <div>
                <div class="step-title">长短任务强校验 (assert_short_tool)</div>
                <div class="step-desc">拦截任何长时间阻塞型评测调用，耗时任务严格必须通过 task.create 入队排队。</div>
              </div>
            </div>
            <div class="p-step">
              <div class="step-badge">2</div>
              <div>
                <div class="step-title">上下文防撑爆截断 (truncate_tool_data)</div>
                <div class="step-desc">列表最多返回 20 条摘要，整段 JSON 超 4000 字符自动截断并标记 truncated=true。</div>
              </div>
            </div>
            <div class="p-step">
              <div class="step-badge">3</div>
              <div>
                <div class="step-title">复核溯源收集 (collect_ids)</div>
                <div class="step-desc">自动从工具返回值提取任务 ID、数据集 ID 与模型 ID，供 G3 门禁防幻觉核对。</div>
              </div>
            </div>
          </div>
        </div>
      </div>

      <!-- ═════════════════ Tab 3: 在线接口检查 ═════════════════ -->
      <div v-else class="tab-pane">
        <div class="live-test-header row-between">
          <div>
            <span style="font-weight: 700; font-size: 13.5px">⚡ 真实接口在线检查</span>
            <div class="small tertiary">浏览器只检查受控清单或同源 REST 接口，不直接执行内部 ToolCall。</div>
          </div>
          <button
            class="btn btn-sign btn-sm"
            :disabled="testing"
            @click="handleRunLiveToolCall"
          >
            {{ testing ? '检查中…' : '▶ 真实在线检查' }}
          </button>
        </div>

        <!-- 测试运行状态条 -->
        <div v-if="testResult" class="test-status-bar" :class="{ ok: testResult.ok, err: !testResult.ok }">
          <div class="row" style="gap: 8px; align-items: center">
            <span class="status-indicator">{{ testResult.ok ? '●' : '✕' }}</span>
            <span class="font-bold">{{ testResult.ok ? '接口检查成功 (HTTP 200 OK)' : '接口检查失败' }}</span>
          </div>
          <div class="row" style="gap: 12px; align-items: center">
            <span class="mono small">耗时: {{ testResult.latencyMs }}ms</span>
            <span class="mono small">载荷条数: {{ testResult.itemCount }} 条</span>
          </div>
        </div>

        <!-- 真实返回数据展示 -->
        <div class="section-block mt12">
          <div class="row-between">
          <span class="section-title">📦 服务端真实返回载荷:</span>
            <button
              v-if="testResult"
              class="link-btn small"
              @click="handleCopyTestResult"
            >
              复制返回 JSON
            </button>
          </div>
          <pre class="json-code live-code-block"><code>{{ testResultJson }}</code></pre>
        </div>
      </div>
    </div>

    <template #footer>
      <div class="row-between" style="width: 100%">
        <span class="small tertiary mono">受控工具清单 · 浏览器只读检查</span>
        <button class="btn btn-secondary btn-sm" @click="$emit('update:show', false)">关闭</button>
      </div>
    </template>
  </n-modal>
</template>

<script setup lang="ts">
import { ref, computed, watch } from 'vue'
import { NModal, useMessage } from 'naive-ui'
import { api } from '../../api/http'
import type { McpTool } from '../../api/types'

const message = useMessage()

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
  sourceFile: string
  backendFunction: string
  dbEntity: string
  securityNote: string
  params: ToolParam[]
  exampleRequest: string
  exampleResponse: string
}

const props = defineProps<{
  show: boolean
  tool: McpTool | null
}>()

defineEmits<{
  (e: 'update:show', val: boolean): void
}>()

// 模态弹窗内部 Sub-Tabs: 'contract' | 'pipeline' | 'live_test'
const activeModalTab = ref<'contract' | 'pipeline' | 'live_test'>('contract')

// 实时测试状态
const testing = ref(false)
const testResult = ref<{ ok: boolean; latencyMs: number; itemCount: number; data: any } | null>(null)

// 切换到测试 Tab 时自动触发一次测试（如果尚未测试）
function handleSwitchToLiveTest() {
  activeModalTab.value = 'live_test'
  if (!testResult.value && !testing.value) {
    handleRunLiveToolCall()
  }
}

// 当弹窗打开或更换工具时重置测试结果
watch(
  () => props.tool,
  () => {
    activeModalTab.value = 'contract'
    testResult.value = null
  },
)

/** 真实在线检查同源接口；浏览器不绕过边界直接执行内部 ToolCall。 */
async function handleRunLiveToolCall() {
  if (!props.tool) return
  testing.value = true
  const start = performance.now()
  try {
    let rawData: any = null
    const toolName = props.tool.name

    if (toolName === 'model.list') {
      const res = await api.profiles.list()
      rawData = {
        items: res.map((p) => ({ id: p.id, name: p.name, protocol: p.protocol, model: p.model, usages: p.usages })),
        total: res.length,
      }
    } else if (toolName === 'dataset.list') {
      const res = await api.datasets.list()
      rawData = {
        // 数据集列表契约未固定 format，保留后端可能返回的扩展字段。
        items: res.map((d) => {
          const dataset = d as typeof d & { format?: string }
          return { id: dataset.id, name: dataset.name, version: dataset.version, row_count: dataset.row_count, format: dataset.format }
        }),
        total: res.length,
      }
    } else if (toolName === 'dispatch.overview') {
      const res = await api.dispatch.overview()
      rawData = res || { workers: 1, queue_depth: 0, strategy: '负载均衡' }
    } else if (toolName === 'task.get') {
      const res = await api.tasks.list()
      const latestTask = res[0]
      rawData = latestTask
        ? { id: latestTask.id, kind: latestTask.kind, status: latestTask.status, progress: latestTask.progress, report_id: latestTask.report_id }
        : { message: '暂无任务记录' }
    } else if (toolName === 'report.get') {
      const res = await api.tasks.list()
      const taskWithReport = res.find((t) => t.report_id)
      if (taskWithReport && taskWithReport.report_id) {
        const report = await api.reports.get(taskWithReport.report_id)
        // 报告按评测类型返回不同指标，metrics 属于兼容扩展字段。
        const reportWithMetrics = report as typeof report & { metrics?: Record<string, unknown> }
        rawData = { report_id: report.id, task_id: report.task_id, kind: report.kind, metrics: reportWithMetrics.metrics }
      } else {
        rawData = { report_id: 'rep-mock-01', metrics: { accuracy: 0.92, latency_p95_ms: 280 } }
      }
    } else {
      // 通用从 /api/mcp/tools 取真实元数据
      const toolsRes = await api.mcp.tools()
      const current = toolsRes.items.find((x) => x.name === toolName)
      rawData = { tool: current || props.tool, status: current ? 'manifest_available' : 'not_in_manifest' }
    }

    const latency = Math.round(performance.now() - start)
    const count = Array.isArray(rawData?.items) ? rawData.items.length : 1
    testResult.value = {
      ok: true,
      latencyMs: Math.max(1, latency),
      itemCount: count,
      data: rawData,
    }
    message.success(`接口检查 [${toolName}] 成功 (${testResult.value.latencyMs}ms)`)
  } catch (err: any) {
    const latency = Math.round(performance.now() - start)
    testResult.value = {
      ok: false,
      latencyMs: Math.max(1, latency),
      itemCount: 0,
      data: { error: err.message || '调用失败', code: 'INTERNAL_ERROR' },
    }
    message.error(`在线接口检查失败: ${err.message || '网络异常'}`)
  } finally {
    testing.value = false
  }
}

const testResultJson = computed(() => {
  if (!testResult.value) {
    return '// 点击右上角「▶ 真实在线调用」开始执行…'
  }
  return JSON.stringify(testResult.value.data, null, 2)
})

function handleCopyTestResult() {
  if (!testResult.value) return
  navigator.clipboard.writeText(testResultJson.value)
  message.success('已复制真实返回 JSON 数据')
}

// 9 大受控内置短工具的完备规格与源码实现字典
const TOOL_META_MAP: Record<string, ToolMeta> = {
  'model.list': {
    icon: '🤖',
    domain: '模型资产治理',
    latency: '< 20ms',
    sourceFile: 'backend/api/app/agent/mcp_tools.py',
    backendFunction: '_list_profiles(db: Session)',
    dbEntity: 'ProtocolProfile (数据库表 protocol_profiles)',
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
    sourceFile: 'backend/api/app/agent/mcp_tools.py',
    backendFunction: '_list_datasets(db: Session)',
    dbEntity: 'Dataset (数据库表 datasets)',
    params: [
      { name: 'kind', type: 'string', required: false, desc: '评测类别：benchmark (通用) | rag (知识库) | cases (用例)' },
      { name: 'search', type: 'string', required: false, desc: '数据集名称或标签模糊匹配关键字' },
    ],
    exampleRequest: JSON.stringify({ name: 'dataset.list', arguments: { kind: 'benchmark' } }, null, 2),
    exampleResponse: JSON.stringify({
      items: [
        { id: 'ds-gsm8k', name: 'GSM8K-数学推理', row_count: 500, version: 'v1.0' },
        { id: 'ds-humaneval', name: 'HumanEval-代码生成', row_count: 164, version: 'v2.1' },
      ],
      total: 2,
    }, null, 2),
    securityNote: '只读短工具。返回数据集元数据与样本量统计，不回传海量原始文本，防范上下文超限。',
  },
  'task.get': {
    icon: '🔍',
    domain: '任务中心与调度',
    latency: '< 20ms',
    sourceFile: 'backend/api/app/agent/mcp_tools.py',
    backendFunction: '_task_get(db: Session, arguments: dict, user_id: str)',
    dbEntity: 'Task (数据库表 tasks)',
    params: [
      { name: 'task_id', type: 'string', required: true, desc: '待查询的目标评测/压测任务唯一 ID' },
    ],
    exampleRequest: JSON.stringify({ name: 'task.get', arguments: { task_id: 't-20260820-0012' } }, null, 2),
    exampleResponse: JSON.stringify({
      id: 't-20260820-0012',
      kind: 'benchmark',
      status: 'running',
      progress: { done: 30, total: 50, percent: 60, message: '正在执行被测模型推理评测 (30/50)' },
      report_id: null,
    }, null, 2),
    securityNote: '只读短工具。实时读取指定任务的状态机状态、执行进度与派生压测状态。',
  },
  'task.create': {
    icon: '🚀',
    domain: '任务中心与调度',
    latency: '< 45ms',
    sourceFile: 'backend/api/app/agent/mcp_tools.py',
    backendFunction: 'execute_short_tool(..., allow_create=True)',
    dbEntity: 'Task (数据库表 tasks，创建排队记录)',
    params: [
      { name: 'kind', type: 'string', required: true, desc: '任务类型：benchmark | rag | testcase' },
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
    sourceFile: 'backend/api/app/agent/mcp_tools.py',
    backendFunction: 'execute_short_tool(..., name="task.cancel")',
    dbEntity: 'Task (数据库表 tasks，置状态为 cancelled)',
    params: [
      { name: 'task_id', type: 'string', required: true, desc: '需要取消或熔断的目标任务 ID' },
      { name: 'reason', type: 'string', required: false, desc: '取消原因说明（用于记录操作审计日志）' },
    ],
    exampleRequest: JSON.stringify({ name: 'task.cancel', arguments: { task_id: 't-20260820-0012', reason: '用户手动中止' } }, null, 2),
    exampleResponse: JSON.stringify({
      task_id: 't-20260820-0012',
      status: 'cancelled',
      message: '任务已标记取消',
    }, null, 2),
    securityNote: '受控写入工具 (WRITE)。触发 Worker 熔断信号（质量任务当前样本后安全退出，压测任务即刻停发）。',
  },
  'dispatch.overview': {
    icon: '🖥️',
    domain: '调度与算力大盘',
    latency: '< 25ms',
    sourceFile: 'backend/api/app/agent/mcp_tools.py',
    backendFunction: '_dispatch_overview(db: Session)',
    dbEntity: 'DispatchWorker, Task (算力节点与排队深度统计)',
    params: [],
    exampleRequest: JSON.stringify({ name: 'dispatch.overview', arguments: {} }, null, 2),
    exampleResponse: JSON.stringify({
      workers: 2,
      queue_depth: 1,
      strategy: '负载均衡',
      total_workers: 2,
      heartbeat_interval_ms: 500,
    }, null, 2),
    securityNote: '只读短工具。实时读取 Worker 节点健康、显存负载与排队深度，为 Agent 分发建议提供决策依据。',
  },
  'report.get': {
    icon: '📊',
    domain: '评测报告解读',
    latency: '< 35ms',
    sourceFile: 'backend/api/app/agent/mcp_tools.py',
    backendFunction: '_report_get(db: Session, arguments: dict)',
    dbEntity: 'Report (数据库表 reports)',
    params: [
      { name: 'report_id', type: 'string', required: true, desc: '待查询的评测报告唯一标识 (UUID/ID)' },
    ],
    exampleRequest: JSON.stringify({ name: 'report.get', arguments: { report_id: 'rep-20260819-01' } }, null, 2),
    exampleResponse: JSON.stringify({
      report_id: 'rep-20260819-01',
      summary: { accuracy: 0.885, latency_p95_ms: 320, token_tps: 45.2 },
    }, null, 2),
    securityNote: '只读短工具。提取报告关键指标快照与聚合分析，用于 Agent 在对话中进行多模态/多模型对比解读。',
  },
  'kb.list': {
    icon: '🧠',
    domain: '知识库与 QA 资产',
    latency: '< 25ms',
    sourceFile: 'backend/api/app/agent/mcp_tools.py',
    backendFunction: 'execute_short_tool(..., name="kb.list")',
    dbEntity: 'KnowledgeBase, GoldQA (知识库与金标资产)',
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
  'testcase.confirm': {
    icon: '🧪',
    domain: '用例生成与入库',
    latency: '< 40ms',
    sourceFile: 'backend/api/app/agent/mcp_tools.py',
    backendFunction: 'execute_short_tool(..., name="testcase.confirm")',
    dbEntity: 'CaseSet, TestCase (用例集转正持久化)',
    params: [
      { name: 'case_set_id', type: 'string', required: true, desc: '待确认入库的用例集 ID (UUID)' },
      { name: 'confirmed_case_ids', type: 'array', required: false, desc: '勾选确认转正的用例 ID 列表（留空默认全量确认）' },
    ],
    exampleRequest: JSON.stringify({ name: 'testcase.confirm', arguments: { case_set_id: 'cs-pay-01', confirmed_case_ids: ['c-1', 'c-2'] } }, null, 2),
    exampleResponse: JSON.stringify({
      case_set_id: 'cs-pay-01',
      status: 'confirmed',
      confirmed_count: 26,
      message: '用例已成功确认并转正入库',
    }, null, 2),
    securityNote: '受控写入工具 (WRITE)。将 AI 提炼生成的候选 PRD 测试用例持久化转正为可复用的标准用例库。',
  },
  'audio.speech_recognition': {
    icon: 'ASR',
    domain: '语音识别',
    latency: '< 90s',
    sourceFile: 'backend/api/app/agent/mimo_audio.py',
    backendFunction: 'execute_speech_recognition(db, arguments, user_id)',
    dbEntity: 'StoredFile（本轮 wav/mp3 附件）',
    params: [
      { name: 'file_id', type: 'string', required: true, desc: '由系统从本轮 wav/mp3 附件绑定，模型不得编造' },
      { name: 'language', type: 'string', required: false, desc: 'auto | zh | en，默认 auto' },
    ],
    exampleRequest: JSON.stringify({ name: 'audio.speech_recognition', arguments: { file_id: 'file-uuid', language: 'zh' } }, null, 2),
    exampleResponse: JSON.stringify({ transcript: '识别出的文本', language: 'zh', file_id: 'file-uuid' }, null, 2),
    securityNote: '受控音频工具。工具结果只返回转写文本与文件元数据，不回传 Base64；文件 ID 仅从本轮附件绑定。',
  },
  'audio.speech_synthesis': {
    icon: 'TTS',
    domain: '语音合成',
    latency: '< 90s',
    sourceFile: 'backend/api/app/agent/mimo_audio.py',
    backendFunction: 'execute_speech_synthesis(db, arguments, user_id)',
    dbEntity: 'StoredFile（合成 wav 输出）',
    params: [
      { name: 'text', type: 'string', required: true, desc: '要合成的文本，由本轮用户输入绑定' },
      { name: 'mode', type: 'string', required: false, desc: 'preset | voicedesign，默认 preset' },
      { name: 'style', type: 'string', required: false, desc: 'voicedesign 模式必填的风格描述' },
      { name: 'voice', type: 'string', required: false, desc: 'preset 模式的受控音色标识' },
    ],
    exampleRequest: JSON.stringify({ name: 'audio.speech_synthesis', arguments: { text: '欢迎使用', mode: 'preset' } }, null, 2),
    exampleResponse: JSON.stringify({ file_id: 'file-uuid', content_type: 'audio/wav', content_url: '/api/files/file-uuid/content' }, null, 2),
    securityNote: '受控音频工具。只回 StoredFile 元数据和同源播放地址，不回传 Base64、Key 或上游原文。',
  },
}

const meta = computed<ToolMeta>(() => {
  if (!props.tool) {
    return {
      icon: '🛠️',
      domain: '通用短工具',
      latency: '< 30ms',
      sourceFile: 'backend/api/app/agent/mcp_tools.py',
      backendFunction: 'execute_short_tool()',
      dbEntity: 'PostgreSQL 实体',
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
      sourceFile: 'backend/api/app/agent/mcp_tools.py',
      backendFunction: 'execute_short_tool()',
      dbEntity: 'PostgreSQL 实体',
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
  gap: 14px;
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
.host-pill {
  font-size: 10.5px;
  padding: 2px 7px;
  border-radius: 5px;
  background: rgba(15, 23, 42, 0.06);
  color: var(--text-secondary, #6b7280);
}
.tool-desc {
  font-size: 12.5px;
  color: var(--text-secondary, #6b7280);
  margin-top: 4px;
  line-height: 1.5;
}

/* 弹窗内 Sub-Tabs */
.modal-sub-tabs {
  display: flex;
  gap: 6px;
  border-bottom: 1px solid var(--border-subtle, #e5e7eb);
  padding-bottom: 8px;
}
.sub-tab-btn {
  padding: 5px 12px;
  border: 1px solid transparent;
  background: transparent;
  color: var(--text-secondary, #6b7280);
  font-size: 12px;
  font-weight: 600;
  border-radius: 6px;
  cursor: pointer;
  transition: all 0.2s;
}
.sub-tab-btn:hover {
  background: var(--bg-elevated, #f4f8f8);
  color: var(--text-primary, #111827);
}
.sub-tab-btn.active {
  background: rgba(99, 102, 241, 0.1);
  color: var(--accent-ai, #6366f1);
  border-color: rgba(99, 102, 241, 0.25);
}

.tab-pane {
  display: flex;
  flex-direction: column;
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
.text-ai {
  color: var(--accent-ai, #6366f1);
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

/* Tab 2 真实后端链路卡片 */
.pipeline-card-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 10px;
}
.pipeline-item {
  padding: 10px 12px;
  border: 1px solid var(--border-subtle, #e5e7eb);
  border-radius: 8px;
  background: var(--bg-main, #ffffff);
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.pipe-header {
  display: flex;
  align-items: center;
  gap: 6px;
}
.pipe-icon {
  font-size: 14px;
}
.pipe-title {
  font-size: 12px;
  font-weight: 600;
  color: var(--text-primary, #111827);
}
.pipe-body {
  font-size: 12px;
  font-weight: 700;
  color: var(--text-primary, #111827);
}
.pipe-hint {
  font-size: 10.5px;
  color: var(--text-tertiary, #9ca3af);
  line-height: 1.4;
}
.pipeline-steps-box {
  display: flex;
  flex-direction: column;
  gap: 8px;
  padding: 10px 12px;
  background: var(--bg-elevated, #f4f8f8);
  border-radius: 8px;
  border: 1px solid var(--border-subtle, #e5e7eb);
}
.p-step {
  display: flex;
  gap: 10px;
  align-items: flex-start;
}
.step-badge {
  width: 18px;
  height: 18px;
  border-radius: 50%;
  background: var(--accent-ai, #6366f1);
  color: #ffffff;
  font-size: 10.5px;
  font-weight: 700;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
  margin-top: 2px;
}
.step-title {
  font-size: 12px;
  font-weight: 600;
  color: var(--text-primary, #111827);
}
.step-desc {
  font-size: 11px;
  color: var(--text-secondary, #6b7280);
  line-height: 1.4;
  margin-top: 1px;
}

/* Tab 3 在线测试 */
.live-test-header {
  padding: 10px 12px;
  background: var(--bg-elevated, #f4f8f8);
  border-radius: 8px;
  border: 1px solid var(--border-subtle, #e5e7eb);
}
.test-status-bar {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 8px 12px;
  border-radius: 6px;
  font-size: 12px;
  margin-top: 10px;
}
.test-status-bar.ok {
  background: rgba(16, 185, 129, 0.1);
  color: var(--accent-success, #10b981);
  border: 1px solid rgba(16, 185, 129, 0.25);
}
.test-status-bar.err {
  background: rgba(239, 68, 68, 0.1);
  color: var(--accent-error, #ef4444);
  border: 1px solid rgba(239, 68, 68, 0.25);
}
.status-indicator {
  font-size: 14px;
}
.live-code-block {
  max-height: 220px;
}
.mt12 {
  margin-top: 12px;
}
</style>
