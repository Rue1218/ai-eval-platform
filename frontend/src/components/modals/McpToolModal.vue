<template>
  <n-modal
    :show="show"
    preset="card"
    :trap-focus="false"
    :auto-focus="false"
    :title="`工具契约与代码详情 · ${tool?.display_name || tool?.name || ''}`"
    style="width: 840px; max-width: 95vw; border-radius: 14px"
    @update:show="$emit('update:show', $event)"
  >
    <div v-if="tool" class="mcp-modal-content">
      <!-- 头部概览条 -->
      <div class="tool-modal-header">
        <div class="tool-title-row">
          <span class="tool-icon">{{ toolIcon }}</span>
          <div style="flex: 1">
            <div class="row-between">
              <div class="row" style="gap: 8px; align-items: center">
                <span class="tool-name">{{ tool.display_name || tool.name }}</span>
                <span class="tool-id-tag mono">{{ tool.name }}</span>
                <!-- 通道标识 -->
                <span
                  class="channel-pill"
                  :class="tool.transport === 'native' ? 'channel-native' : 'channel-mcp'"
                >
                  {{ tool.transport === 'native' ? '⚡ 原生 ToolCall' : '🔗 内部 MCP Server' }}
                </span>
                <!-- 风险级别 -->
                <span class="perm-badge" :class="riskBadgeClass">
                  {{ riskBadgeLabel }}
                </span>
              </div>
              <span class="host-pill mono">{{ hostPillText }}</span>
            </div>
            <div class="tool-desc">{{ tool.desc }}</div>
          </div>
        </div>
      </div>

      <!-- 4 Tab 切换分段器 -->
      <div class="modal-sub-tabs">
        <button
          class="sub-tab-btn"
          :class="{ active: activeModalTab === 'contract' }"
          @click="activeModalTab = 'contract'"
        >
          📜 输入输出参数契约 (Schema)
        </button>
        <button
          class="sub-tab-btn"
          :class="{ active: activeModalTab === 'pipeline' }"
          @click="activeModalTab = 'pipeline'"
        >
          🔄 执行链路流程 (Pipeline)
        </button>
        <button
          class="sub-tab-btn"
          :class="{ active: activeModalTab === 'code' }"
          @click="activeModalTab = 'code'"
        >
          💻 源码实现与 Handler (Code)
        </button>
        <button
          class="sub-tab-btn"
          :class="{ active: activeModalTab === 'live_test' }"
          @click="handleSwitchToLiveTest"
        >
          ⚡ 在线接口检查 (Live Check)
        </button>
      </div>

      <!-- ═════════════════ Tab 1: 接口契约规范 (Schema & Specs) ═════════════════ -->
      <div v-if="activeModalTab === 'contract'" class="tab-pane">
        <!-- 核心规格指标 -->
        <div class="spec-grid">
          <div class="spec-item">
            <span class="spec-label">执行通道 (Transport)</span>
            <span class="spec-value mono font-bold" :class="tool.transport === 'native' ? 'text-success' : 'text-ai'">
              {{ tool.transport === 'native' ? 'NativeToolExecutor (直连)' : 'MCPClientManager (MCP Host)' }}
            </span>
          </div>
          <div class="spec-item">
            <span class="spec-label">超时上限 (Timeout)</span>
            <span class="spec-value mono text-success">{{ tool.timeout_s ? `${tool.timeout_s}s` : '默认 20s' }}</span>
          </div>
          <div class="spec-item">
            <span class="spec-label">流式支持 (Streaming)</span>
            <span class="spec-value mono">{{ tool.supports_streaming ? '✅ 启用流式反馈' : '📦 整体返回' }}</span>
          </div>
          <div class="spec-item">
            <span class="spec-label">确认卡门禁 (Confirmation)</span>
            <span class="spec-value" :class="tool.requires_confirmation ? 'text-warning font-bold' : 'text-secondary'">
              {{ tool.requires_confirmation ? '⚠️ 必须显式授权' : '自动安全执行' }}
            </span>
          </div>
        </div>

        <!-- 1. 输入参数 JSON Schema (Input Arguments Schema) -->
        <div class="section-block mt12">
          <div class="section-title">
            <div class="row" style="gap: 6px; align-items: center">
              <span>📥 输入参数规范 (Input Parameters Schema)</span>
              <span class="small tertiary mono">application/json</span>
            </div>
            <span class="param-count-badge">{{ parsedInputParams.length }} 个参数</span>
          </div>

          <div v-if="parsedInputParams.length > 0" class="params-table-wrap">
            <table class="params-table">
              <thead>
                <tr>
                  <th style="width: 150px">参数字段 (Field)</th>
                  <th style="width: 90px">数据类型</th>
                  <th style="width: 70px">必填</th>
                  <th style="width: 140px">约束条件</th>
                  <th>说明与描述</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="p in parsedInputParams" :key="p.name">
                  <td class="mono font-bold" style="color: var(--c-profiles)">{{ p.name }}</td>
                  <td><span class="type-tag mono">{{ p.type }}</span></td>
                  <td>
                    <span :class="p.required ? 'text-error font-bold' : 'tertiary'">
                      {{ p.required ? '是' : '否' }}
                    </span>
                  </td>
                  <td class="mono small tertiary">{{ p.constraints || '—' }}</td>
                  <td class="small">{{ p.desc }}</td>
                </tr>
              </tbody>
            </table>
          </div>
          <div v-else class="empty-params">
            <span class="tertiary small">无输入参数（调用时直接传空参数对象 <code>{}</code> 即可）</span>
          </div>
        </div>

        <!-- 2. 输出参数规范 (Output Schema & Response Fields) -->
        <div class="section-block mt12">
          <div class="section-title">
            <div class="row" style="gap: 6px; align-items: center">
              <span>📤 输出参数结构 (Output Response Schema)</span>
              <span class="small tertiary mono">结构化返回值规范</span>
            </div>
            <span class="param-count-badge">{{ parsedOutputFields.length }} 个响应字段</span>
          </div>

          <div v-if="parsedOutputFields.length > 0" class="params-table-wrap">
            <table class="params-table">
              <thead>
                <tr>
                  <th style="width: 160px">输出字段 (Key)</th>
                  <th style="width: 100px">数据类型</th>
                  <th>字段说明与结构</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="f in parsedOutputFields" :key="f.name">
                  <td class="mono font-bold text-success">{{ f.name }}</td>
                  <td><span class="type-tag mono">{{ f.type }}</span></td>
                  <td class="small">{{ f.desc }}</td>
                </tr>
              </tbody>
            </table>
          </div>
          <div v-else class="empty-params">
            <span class="tertiary small">返回基础状态回执对象 <code>{"summary": string}</code></span>
          </div>
        </div>

        <!-- 3. 调用示例与返回报文 -->
        <div class="section-block mt12">
          <div class="section-title">
            <span>📦 请求与返回载荷示例 (JSON Payloads)</span>
          </div>
          <div class="code-box-tabs">
            <div class="code-preview-wrap">
              <div class="code-label">Agent 工具请求示例 (Input Arguments):</div>
              <pre class="json-code"><code>{{ exampleRequestJson }}</code></pre>
            </div>
            <div class="code-preview-wrap">
              <div class="code-label">Handler 输出报文示例 (Output Response):</div>
              <pre class="json-code"><code>{{ exampleResponseJson }}</code></pre>
            </div>
          </div>
        </div>

        <!-- 4. 权限与风控策略 -->
        <div class="section-block guardrail-box mt12">
          <div class="guardrail-title">🛡️ 权限策略与恢复建议 (Policy & Recovery)</div>
          <div class="guardrail-desc">
            <div><strong>权限标识：</strong><code>{{ tool.permission || 'sandbox.default' }}</code></div>
            <div v-if="tool.recovery_policy?.default_hint" class="mt4">
              <strong>恢复提示：</strong>{{ tool.recovery_policy.default_hint }}
            </div>
          </div>
        </div>
      </div>

      <!-- ═════════════════ Tab 2: 真实后端实现链路 (Pipeline) ═════════════════ -->
      <div v-else-if="activeModalTab === 'pipeline'" class="tab-pane">
        <!-- 链路架构指标 -->
        <div class="pipeline-card-grid">
          <div class="pipeline-item">
            <div class="pipe-header">
              <span class="pipe-icon">📁</span>
              <span class="pipe-title">源码实现位置</span>
            </div>
            <div class="pipe-body mono small">{{ tool.code_details?.source_file || 'backend/api/app/harness/execution/registry.py' }}</div>
            <div class="pipe-hint">FastAPI 进程内受控模块，严禁暴露敏感配置</div>
          </div>

          <div class="pipeline-item">
            <div class="pipe-header">
              <span class="pipe-icon">⚙️</span>
              <span class="pipe-title">底层执行函数</span>
            </div>
            <div class="pipe-body mono small text-ai">{{ tool.code_details?.handler_function || `_${tool.short_name || tool.name}_handler()` }}</div>
            <div class="pipe-hint">{{ tool.transport === 'native' ? 'NativeToolExecutor 进程内直接调用' : 'MCP InProcessProvider 桥接' }}</div>
          </div>

          <div class="pipeline-item">
            <div class="pipe-header">
              <span class="pipe-icon">🛡️</span>
              <span class="pipe-title">沙箱与隔离策略</span>
            </div>
            <div class="pipe-body mono small text-success">
              {{ tool.transport === 'native' ? (tool.risk_level === 'code' ? 'bwrap 沙箱 (无网络/只读根)' : '会话工作区隔离') : 'PostgreSQL 状态机解耦' }}
            </div>
            <div class="pipe-hint">限制运行空间与并发资源，防止越权破坏</div>
          </div>

          <div class="pipeline-item">
            <div class="pipe-header">
              <span class="pipe-icon">🔒</span>
              <span class="pipe-title">凭据脱敏与防爆仓</span>
            </div>
            <div class="pipe-body mono small text-success">redact_secrets() + 截断保护</div>
            <div class="pipe-hint">正则脱敏 Token/Key，超长内容生成 next_offset 引导分页</div>
          </div>
        </div>

        <!-- 执行流阶段 Pipeline 步骤卡片 -->
        <div class="section-block mt12">
          <div class="section-title">
            <span>🔄 执行流程阶段 (Execution Pipeline Stages)</span>
            <span class="small tertiary">从 Agent 意图识别到结果回填的完整生命周期</span>
          </div>

          <div class="pipeline-steps-box">
            <div v-for="st in pipelineStages" :key="st.step" class="p-step">
              <div class="step-badge">{{ st.step }}</div>
              <div style="flex: 1">
                <div class="step-title">{{ st.name }}</div>
                <div class="step-desc">{{ st.desc }}</div>
              </div>
            </div>
          </div>
        </div>

        <!-- 架构防御机制 -->
        <div class="section-block mt12">
          <div class="section-title">
            <span>🔒 HAR-NFR-07 安全执行保障</span>
          </div>
          <div class="guardrail-box">
            <div class="guardrail-desc" style="font-size: 11.5px; line-height: 1.6">
              • <strong>长短任务分离</strong>：耗时评测与压测绝不直接在此执行，统一通过 <code>task.create</code> 入队排队由异步 Worker 消费。<br>
              • <strong>防幻觉复核</strong>：自动提取关联的任务 ID、数据集 ID 与模型 ID，供 G3 门禁防幻觉核对。<br>
              • <strong>原子操作</strong>：文件修改（write/edit）严格保证原子性，支持回滚与修复提示。
            </div>
          </div>
        </div>
      </div>

      <!-- ═════════════════ Tab 3: 底层源码与 Handler (Code) ═════════════════ -->
      <div v-else-if="activeModalTab === 'code'" class="tab-pane">
        <div class="section-block">
          <div class="row-between">
            <div class="section-title">
              <span>💻 Python Handler 实现源码片段 (Source Code)</span>
            </div>
            <div class="row" style="gap: 8px">
              <button class="link-btn small" @click="handleCopyCode">
                📋 复制代码
              </button>
            </div>
          </div>

          <div class="code-meta-bar">
            <div class="code-meta-item">
              <span class="meta-label">文件路径:</span>
              <span class="meta-val mono">{{ tool.code_details?.source_file || 'backend/api/app/harness/execution/registry.py' }}</span>
            </div>
            <div class="code-meta-item">
              <span class="meta-label">入口函数:</span>
              <span class="meta-val mono text-ai">{{ tool.code_details?.handler_function || `_${tool.name}_handler` }}</span>
            </div>
          </div>

          <!-- 代码高亮预览框 -->
          <pre class="json-code code-full-block"><code>{{ codeSnippetText }}</code></pre>
        </div>

        <div class="section-block mt12">
          <div class="section-title">
            <span>💡 核心执行逻辑摘要 (Implementation Summary)</span>
          </div>
          <div class="guardrail-box">
            <div class="guardrail-desc">
              {{ tool.code_details?.code_summary || '受控执行逻辑：解析参数 -> 安全门禁 -> 进程内直连执行 -> 结果脱敏与上下文截断。' }}
            </div>
          </div>
        </div>
      </div>

      <!-- ═════════════════ Tab 4: 在线接口检查 (Live Check) ═════════════════ -->
      <div v-else class="tab-pane">
        <div class="live-test-header row-between">
          <div>
            <span style="font-weight: 700; font-size: 13.5px">⚡ 真实接口在线自检</span>
            <div class="small tertiary">
              {{ tool.transport === 'native' ? '检查 NativeToolExecutor 注册状态与参数 Schema 连通' : '检查内部 MCP Server 目录索引与接口健康' }}
            </div>
          </div>
          <button
            class="btn btn-sign btn-sm"
            :disabled="testing"
            @click="handleRunLiveToolCall"
          >
            {{ testing ? '检查中…' : '▶ 真实在线自检' }}
          </button>
        </div>

        <!-- 测试运行状态条 -->
        <div v-if="testResult" class="test-status-bar" :class="{ ok: testResult.ok, err: !testResult.ok }">
          <div class="row" style="gap: 8px; align-items: center">
            <span class="status-indicator">{{ testResult.ok ? '●' : '✕' }}</span>
            <span class="font-bold">{{ testResult.ok ? '接口自检成功 · 状态正常' : '接口自检异常' }}</span>
          </div>
          <div class="row" style="gap: 12px; align-items: center">
            <span class="mono small">耗时: {{ testResult.latencyMs }}ms</span>
            <span class="mono small">载荷大小: {{ testResult.payloadSize }} 字符</span>
          </div>
        </div>

        <!-- 真实返回数据展示 -->
        <div class="section-block mt12">
          <div class="row-between">
            <span class="section-title">📦 服务端真实返回载荷 (Live Response Payload):</span>
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
        <span class="small tertiary mono">受控工具清单与代码详情 · 浏览器只读</span>
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

const props = defineProps<{
  show: boolean
  tool: McpTool | null
}>()

defineEmits<{
  (e: 'update:show', val: boolean): void
}>()

// 4 大 Sub-Tabs: 'contract' | 'pipeline' | 'code' | 'live_test'
const activeModalTab = ref<'contract' | 'pipeline' | 'code' | 'live_test'>('contract')

// 实时自检状态
const testing = ref(false)
const testResult = ref<{ ok: boolean; latencyMs: number; payloadSize: number; data: any } | null>(null)

function handleSwitchToLiveTest() {
  activeModalTab.value = 'live_test'
  if (!testResult.value && !testing.value) {
    handleRunLiveToolCall()
  }
}

watch(
  () => props.tool,
  () => {
    activeModalTab.value = 'contract'
    testResult.value = null
  },
)

/** 工具展示图标 */
const toolIcon = computed(() => {
  if (!props.tool) return '🛠️'
  const name = props.tool.name
  if (name === 'read' || name === 'write' || name === 'edit') return '📂'
  if (name === 'web_search' || name === 'web_fetch') return '🌐'
  if (name === 'bash') return '💻'
  if (name === 'task') return '📋'
  if (name.includes('task.')) return '🚀'
  if (name.startsWith('model.')) return '🤖'
  if (name.startsWith('dataset.')) return '📚'
  if (name.startsWith('kb.')) return '🧠'
  if (name.startsWith('audio.')) return '🔊'
  if (name.startsWith('image.')) return '🖼️'
  return '🛠️'
})

/** 风险等级标签与样式 */
const riskBadgeLabel = computed(() => {
  const risk = props.tool?.risk_level
  switch (risk) {
    case 'read': return '📖 READ · 只读'
    case 'network': return '🌐 NET · 网络'
    case 'modify': return '✍️ MODIFY · 写入'
    case 'code': return '💻 CODE · 命令执行'
    case 'long': return '⏱️ LONG · 长任务'
    default: return '🛠️受控调用'
  }
})

const riskBadgeClass = computed(() => {
  const risk = props.tool?.risk_level
  switch (risk) {
    case 'read': return 'perm-read'
    case 'network': return 'perm-network'
    case 'code': return 'perm-code'
    default: return 'perm-write'
  }
})

const hostPillText = computed(() => {
  if (!props.tool) return 'Eval-Core'
  if (props.tool.transport === 'native') return 'Native Host · 进程内直连'
  return `MCP Server · ${props.tool.server_id || 'platform.tasks'}`
})

/** 解析输入参数列表 */
const parsedInputParams = computed(() => {
  if (!props.tool) return []
  const schema = props.tool.parameters_schema
  if (!schema || !schema.properties) return []
  const requiredList: string[] = Array.isArray(schema.required) ? schema.required : []
  return Object.entries(schema.properties).map(([name, prop]: [string, any]) => {
    let constraints = ''
    if (prop.minimum !== undefined || prop.maximum !== undefined) {
      constraints = `范围: [${prop.minimum ?? '—'}, ${prop.maximum ?? '—'}]`
    } else if (prop.enum) {
      constraints = `可选: ${prop.enum.join(' | ')}`
    } else if (prop.minLength !== undefined || prop.maxLength !== undefined) {
      constraints = `长度: [${prop.minLength ?? 0}, ${prop.maxLength ?? '—'}]`
    }
    return {
      name,
      type: prop.type || 'any',
      required: requiredList.includes(name),
      constraints,
      desc: prop.description || '无详细描述',
    }
  })
})

/** 解析输出参数结构 */
const parsedOutputFields = computed(() => {
  if (!props.tool) return []
  const schema = props.tool.output_schema
  if (!schema || !schema.properties) {
    return [
      { name: 'summary', type: 'string', desc: '执行操作结果摘要文本' },
    ]
  }
  const fields: { name: string; type: string; desc: string }[] = []
  for (const [key, prop] of Object.entries(schema.properties as Record<string, any>)) {
    if (prop.type === 'object' && prop.properties) {
      for (const [subKey, subProp] of Object.entries(prop.properties as Record<string, any>)) {
        fields.push({
          name: `${key}.${subKey}`,
          type: subProp.type || 'any',
          desc: subProp.description || `${key} 嵌套输出属性`,
        })
      }
    } else {
      fields.push({
        name: key,
        type: prop.type || 'any',
        desc: prop.description || `${key} 顶层返回字段`,
      })
    }
  }
  return fields
})

/** 执行流程步骤 */
const pipelineStages = computed(() => {
  if (props.tool?.pipeline?.stages && props.tool.pipeline.stages.length > 0) {
    return props.tool.pipeline.stages
  }
  return [
    { step: 1, name: '参数解析与有效性校验', desc: '基于 Pydantic / JSON Schema 严格校验输入参数' },
    { step: 2, name: '沙箱与权限策略门禁', desc: '校验当前会话工作区访问权限与执行风险拦截' },
    { step: 3, name: '核心 Handler 执行', desc: props.tool?.transport === 'native' ? 'NativeToolExecutor 进程内直接分派' : 'MCPClientManager 桥接执行' },
    { step: 4, name: '凭据脱敏与防爆仓截断', desc: '自动过滤敏感 Token/Key 并保护上下文窗口' },
    { step: 5, name: '结构化回填与状态同步', desc: '更新 GraphState 状态机并将响应投影给 Agent' },
  ]
})

/** 源码片段展示 */
const codeSnippetText = computed(() => {
  if (props.tool?.code_details?.code_snippet) {
    return props.tool.code_details.code_snippet
  }
  return `# ${props.tool?.name || 'tool'} 底层实现函数\ndef _${props.tool?.name || 'handler'}(arguments, sandbox_dir, context):\n    # 1. 路径校验与参数安全检查\n    # 2. 核心业务处理\n    return {"summary": "执行完成"}`
})

/** 示例请求 JSON */
const exampleRequestJson = computed(() => {
  if (!props.tool) return '{}'
  const args: Record<string, any> = {}
  const schema = props.tool.parameters_schema
  if (schema && schema.properties) {
    for (const [key, prop] of Object.entries(schema.properties as Record<string, any>)) {
      if (prop.type === 'string') args[key] = key === 'path' ? 'workspace/example.txt' : (key === 'query' ? '大模型评测' : 'sample_value')
      else if (prop.type === 'integer') args[key] = prop.minimum || 0
      else if (prop.type === 'boolean') args[key] = true
      else if (prop.type === 'array') args[key] = []
      else args[key] = {}
    }
  }
  return JSON.stringify({ name: props.tool.name, arguments: args }, null, 2)
})

/** 示例响应 JSON */
const exampleResponseJson = computed(() => {
  if (!props.tool) return '{}'
  const res: Record<string, any> = { summary: `已成功执行 ${props.tool.display_name || props.tool.name}` }
  const shortName = props.tool.name.includes('.') ? props.tool.name.split('.').pop()! : props.tool.name
  if (shortName === 'read') {
    res.read = { path: 'example.txt', total_lines: 42, preview: 'File preview text...' }
  } else if (shortName === 'write') {
    res.write = { path: 'example.txt', bytes_written: 1024, lines_written: 30 }
  } else if (shortName === 'create') {
    res.task = { task_id: 't-20260820-0012', kind: 'benchmark', status: 'queued' }
  } else if (shortName === 'status') {
    res.task = { task_id: 't-20260820-0012', status: 'running', progress: { done: 30, total: 50, percent: 60 } }
  }
  return JSON.stringify(res, null, 2)
})

const testResultJson = computed(() => {
  if (!testResult.value) {
    return '// 点击右上角「▶ 真实在线自检」开始执行…'
  }
  return JSON.stringify(testResult.value.data, null, 2)
})

function handleCopyCode() {
  navigator.clipboard.writeText(codeSnippetText.value)
  message.success('已复制 Python Handler 源码片段')
}

function handleCopyTestResult() {
  if (!testResult.value) return
  navigator.clipboard.writeText(testResultJson.value)
  message.success('已复制返回载荷 JSON')
}

/** 在线真实自检 */
async function handleRunLiveToolCall() {
  if (!props.tool) return
  testing.value = true
  const start = performance.now()
  try {
    const res = await api.mcp.code(props.tool.name)
    const latency = Math.round(performance.now() - start)
    const payloadStr = JSON.stringify(res)
    testResult.value = {
      ok: true,
      latencyMs: Math.max(1, latency),
      payloadSize: payloadStr.length,
      data: res,
    }
    message.success(`自检 [${props.tool.display_name || props.tool.name}] 成功 (${testResult.value.latencyMs}ms)`)
  } catch (err: any) {
    const latency = Math.round(performance.now() - start)
    testResult.value = {
      ok: false,
      latencyMs: Math.max(1, latency),
      payloadSize: 0,
      data: { error: err.message || '自检异常', code: 'CHECK_FAILED' },
    }
    message.error(`在线自检失败: ${err.message || '网络异常'}`)
  } finally {
    testing.value = false
  }
}
</script>

<style scoped>
.mcp-modal-content {
  display: flex;
  flex-direction: column;
  gap: 14px;
}
.tool-modal-header {
  padding: 12px 16px;
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
  font-size: 30px;
  line-height: 1;
}
.tool-name {
  font-size: 16px;
  font-weight: 700;
  color: var(--text-primary, #111827);
}
.tool-id-tag {
  font-size: 11.5px;
  color: var(--text-tertiary, #9ca3af);
  background: rgba(15, 23, 42, 0.05);
  padding: 1px 6px;
  border-radius: 4px;
}
.channel-pill {
  font-size: 11px;
  font-weight: 600;
  padding: 2px 8px;
  border-radius: 6px;
  border: 1px solid;
}
.channel-native {
  background: rgba(16, 185, 129, 0.1);
  color: var(--accent-success, #10b981);
  border-color: rgba(16, 185, 129, 0.25);
}
.channel-mcp {
  background: rgba(99, 102, 241, 0.1);
  color: var(--accent-ai, #6366f1);
  border-color: rgba(99, 102, 241, 0.25);
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
.perm-network {
  background: rgba(59, 130, 246, 0.12);
  color: #3b82f6;
  border: 1px solid rgba(59, 130, 246, 0.3);
}
.perm-code {
  background: rgba(245, 158, 11, 0.12);
  color: #f59e0b;
  border: 1px solid rgba(245, 158, 11, 0.4);
}
.host-pill {
  font-size: 11px;
  padding: 2px 8px;
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

/* 4 Tab 切换 */
.modal-sub-tabs {
  display: flex;
  gap: 6px;
  border-bottom: 1px solid var(--border-subtle, #e5e7eb);
  padding-bottom: 8px;
}
.sub-tab-btn {
  padding: 6px 12px;
  border: 1px solid transparent;
  background: transparent;
  color: var(--text-secondary, #6b7280);
  font-size: 12px;
  font-weight: 600;
  border-radius: 6px;
  cursor: pointer;
  transition: all 0.15s;
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
  gap: 12px;
}

.spec-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(170px, 1fr));
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
  font-size: 12px;
  color: var(--text-primary, #111827);
}
.text-success { color: var(--accent-success, #10b981); }
.text-warning { color: var(--accent-warning, #f59e0b); }
.text-error { color: var(--accent-error, #ef4444); }
.text-ai { color: var(--accent-ai, #6366f1); }

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
.param-count-badge {
  font-size: 11px;
  color: var(--text-tertiary, #9ca3af);
  background: rgba(15, 23, 42, 0.05);
  padding: 1px 6px;
  border-radius: 4px;
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
  max-height: 170px;
  overflow: auto;
}
.code-full-block {
  max-height: 320px;
  color: #a5f3fc;
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

.code-meta-bar {
  display: flex;
  gap: 16px;
  padding: 6px 10px;
  background: var(--bg-elevated, #f4f8f8);
  border-radius: 6px;
  font-size: 11.5px;
}
.code-meta-item {
  display: flex;
  gap: 6px;
  align-items: center;
}
.meta-label {
  color: var(--text-tertiary, #9ca3af);
}
.meta-val {
  color: var(--text-primary, #111827);
  font-weight: 600;
}

/* Tab 2 流程卡片 */
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
  gap: 3px;
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
  font-size: 11.5px;
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
  width: 20px;
  height: 20px;
  border-radius: 50%;
  background: var(--accent-ai, #6366f1);
  color: #ffffff;
  font-size: 11px;
  font-weight: 700;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
  margin-top: 1px;
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

/* Tab 4 在线自检 */
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
  margin-top: 6px;
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
.mt4 { margin-top: 4px; }
.mt12 { margin-top: 12px; }
</style>
