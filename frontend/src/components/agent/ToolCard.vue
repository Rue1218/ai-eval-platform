<template>
  <div
    class="tool-card"
    :class="{
      open: isOpen,
      'no-anim': noAnim,
      'is-pending': status === 'pending',
      'is-streaming': isStreamingOutput || hasLiveOutput,
    }"
    :data-tool="tool"
  >
    <div class="tool-head" @click="isOpen = !isOpen">
      <div class="tool-status" :class="statusClass">
        <!-- pending 旋转 -->
        <svg v-if="status === 'pending'" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
          <line x1="12" y1="2" x2="12" y2="6"></line>
          <line x1="12" y1="18" x2="12" y2="22"></line>
          <line x1="4.93" y1="4.93" x2="7.76" y2="7.76"></line>
          <line x1="16.24" y1="16.24" x2="19.07" y2="19.07"></line>
          <line x1="2" y1="12" x2="6" y2="12"></line>
          <line x1="18" y1="12" x2="22" y2="12"></line>
          <line x1="4.93" y1="19.07" x2="7.76" y2="16.24"></line>
          <line x1="16.24" y1="7.76" x2="19.07" y2="4.93"></line>
        </svg>
        <!-- ok 成功 -->
        <svg v-else-if="status === 'ok'" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
          <polyline points="20 6 9 17 4 12"></polyline>
        </svg>
        <!-- fail 失败 -->
        <svg v-else width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
          <line x1="18" y1="6" x2="6" y2="18"></line>
          <line x1="6" y1="6" x2="18" y2="18"></line>
        </svg>
      </div>

      <div class="tool-title-wrap">
        <div class="tool-name">{{ toolDisplayName }}</div>
        <div class="tool-sub-tag" :title="headerHint">{{ headerHint }}</div>
      </div>

      <div class="tool-meta-right">
        <span v-if="formattedLatency" class="tool-latency mono">{{ formattedLatency }}</span>
        <span v-if="redacted" class="tool-flag">已脱敏</span>
        <span v-if="truncated" class="tool-flag">已截断</span>
        <!-- 分页级「已截断」之外的预览级截断：受控窗口停在了完整行 -->
        <span v-if="previewCut" class="tool-flag">预览截断</span>
        <span v-if="source" class="tool-source mono" :title="source">{{ source }}</span>
        <span class="tool-state-text" :class="statusClass">
          {{ stateText }}
        </span>
        <span v-if="status === 'pending'" class="tool-pulse" aria-hidden="true"></span>
      </div>

      <div class="chev">
        <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
          <polyline points="6 9 12 15 18 9"></polyline>
        </svg>
      </div>
    </div>

    <Transition name="tool-detail">
    <div v-if="isOpen" class="tool-detail">
      <audio
        v-if="isAudioOutput && status === 'ok' && playUrl"
        class="tool-audio"
        controls
        preload="metadata"
        :src="playUrl"
      />
      <div v-if="tool === 'audio.speech_recognition' && status === 'ok' && transcriptText" class="transcript-card">
        <div class="transcript-label">识别文本</div>
        <div class="transcript-text">{{ transcriptText }}</div>
      </div>
      <div class="td-block">
        <div class="td-label">ToolCall</div>
        <dl v-if="inputFields.length" class="td-fields">
          <div v-for="(field, fieldIdx) in inputFields" :key="`${field.label}-${fieldIdx}`" class="td-field">
            <dt>{{ field.label }}</dt>
            <dd :class="{ mono: field.mono, cmd: field.cmd }">{{ field.value }}</dd>
          </div>
        </dl>
        <div v-if="toolCallLines.length" class="tool-call-code-wrap">
          <div v-if="toolCallCodeLabel" class="td-code-caption mono">{{ toolCallCodeLabel }}</div>
          <div class="line-block tool-call-code" role="region" aria-label="ToolCall 参数">
            <div v-for="line in toolCallLines" :key="line.n" class="ln-row">
              <span class="ln-no mono">{{ line.n }}</span>
              <span class="ln-text">{{ line.text }}</span>
            </div>
          </div>
        </div>
      </div>
      <div class="td-block">
        <div class="td-label-row">
          <div class="td-label">输出</div>
          <div v-if="isStreamingOutput || hasLiveOutput" class="td-stream-state">
            <span class="td-stream-dot" aria-hidden="true"></span>
            {{ hasLiveOutput ? '正在接收输出' : '正在流式呈现' }}
          </div>
        </div>
        <div
          v-if="hasLiveOutput"
          class="line-block is-streaming-output"
          role="region"
          aria-label="工具实时输出"
        >
          <div v-for="line in liveOutputLines" :key="`${line.n}-${line.text}`" class="ln-row">
            <span class="ln-no mono">{{ line.n }}</span>
            <span class="ln-text">{{ line.text }}</span>
          </div>
          <div class="stream-tail mono"><span class="stream-cursor">▋</span></div>
          <div v-if="status === 'fail'" class="tool-recovery" role="alert">
            <div class="tool-recovery-title">{{ resolvedOutputText }}</div>
            <p v-if="recoveryHint" class="tool-recovery-hint">{{ recoveryHint }}</p>
            <span v-if="recoveryAction" class="tool-recovery-action mono">建议：{{ recoveryAction }}</span>
          </div>
        </div>
        <div v-else-if="status === 'fail'" class="tool-recovery" role="alert">
          <div class="tool-recovery-title">{{ resolvedOutputText }}</div>
          <p v-if="recoveryHint" class="tool-recovery-hint">{{ recoveryHint }}</p>
          <span v-if="recoveryAction" class="tool-recovery-action mono">建议：{{ recoveryAction }}</span>
        </div>
        <div v-else-if="status === 'pending'" class="tool-output-loading" role="status">
          <div class="tool-loading-copy">
            <span class="tool-loading-orbit" aria-hidden="true"></span>
            {{ toolDisplayName }} 正在执行，等待安全输出…
          </div>
          <div class="tool-loading-lines" aria-hidden="true">
            <span></span><span></span><span></span>
          </div>
        </div>
        <template v-else>
          <p v-if="resultSummary && !previewText && status === 'ok'" class="td-summary">{{ resultSummary }}</p>
          <div v-if="readMeta" class="td-meta mono">
            第 {{ readMeta.start }}–{{ readMeta.end }} 行 · 本次 {{ readMeta.count }} 行 / 共 {{ readMeta.total }} 行
            <span v-if="readMeta.next != null"> · 下一页 offset={{ readMeta.next }}</span>
            <span v-else> · 已读完</span>
          </div>
          <div v-if="isMarkdownOutput && previewText && status === 'ok'" class="td-tabs">
            <button type="button" class="td-tab" :class="{ active: previewMode === 'render' }" @click="previewMode = 'render'">渲染</button>
            <button type="button" class="td-tab" :class="{ active: previewMode === 'source' }" @click="previewMode = 'source'">源码</button>
          </div>
          <MarkdownView
            v-if="showMarkdownOutput"
            :content="previewText"
            custom-class="tool-md"
          />
          <div
            v-else-if="outputLines.length && status === 'ok'"
            class="line-block"
            :class="{ 'is-streaming-output': isStreamingOutput }"
            role="region"
            aria-label="工具输出"
          >
            <div v-for="line in outputLines" :key="line.n" class="ln-row">
              <span class="ln-no mono">{{ line.n }}</span>
              <span class="ln-text">{{ line.text }}</span>
            </div>
            <div v-if="isStreamingOutput" class="stream-tail mono"><span class="stream-cursor">▋</span></div>
          </div>
          <pre v-else-if="displayedPreviewText && status === 'ok'" class="code">{{ displayedPreviewText }}<span v-if="isStreamingOutput" class="stream-cursor">▋</span></pre>
          <pre v-else class="code">{{ status === 'ok' ? displayedOutputText : resolvedOutputText }}<span v-if="isStreamingOutput" class="stream-cursor">▋</span></pre>
          <!-- 服务端受控预览停在完整行：明示截断事实，避免误判为内容丢失 -->
          <div v-if="previewCutHint" class="td-preview-cut mono">{{ previewCutHint }}</div>
        </template>
      </div>
    </div>
    </Transition>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, watch, onBeforeUnmount } from 'vue'
import { formatLatency } from '../../utils/format'
import { shouldKeepToolCardOpen } from '../../utils/toolCard'
import MarkdownView from './MarkdownView.vue'

const props = withDefaults(
  defineProps<{
    tool: string
    args?: any
    result?: any
    status?: 'pending' | 'ok' | 'fail'
    latencyMs?: number
    truncated?: boolean
    source?: string
    redacted?: boolean
    progress?: { stage: string; message: string }
    streamOutput?: { text: string; channel: string; startLine: number; seq: number }
    recovery?: { retryable?: boolean; suggested_action?: string; repair_hint?: string; max_auto_repairs?: number }
    defaultOpen?: boolean
    noAnim?: boolean
  }>(),
  {
    status: 'pending',
    defaultOpen: false,
    noAnim: false,
  },
)

const isOpen = ref(!!props.defaultOpen)

watch(
  () => props.status,
  (status) => {
    if (status === 'pending') {
      isOpen.value = true
      return
    }
    if (status === 'ok' && shouldKeepToolCardOpen(props.tool)) {
      isOpen.value = true
      return
    }
    if (status === 'ok' || status === 'fail') {
      isOpen.value = false
    }
  },
)

const toolNameMap: Record<string, string> = {
  'model.list': '列出协议档',
  'dataset.list': '列出数据集',
  'kb.list': '列出知识库',
  'task.get': '查询任务详情',
  'task.create': '创建评测任务',
  'task.cancel': '取消任务',
  'report.get': '读取评测报告',
  'dispatch.overview': '调度概览',
  'testcase.confirm': '确认用例入库',
  'audio.speech_recognition': '语音识别转写',
  'audio.speech_synthesis': '语音合成',
  'audio.voiceclone': '音色克隆配音',
  'image.generate': 'Qwen Image 生图',
  read: '读取文件',
  write: '写入文件',
  edit: '编辑文件',
  bash: '运行沙箱命令',
  web_search: '网络搜索',
  web_fetch: '抓取网页',
  task: '拆解任务',
  // 兼容旧下划线命名
  list_profiles: '列出协议档',
  get_profile: '获取协议档详情',
  list_datasets: '列出数据集',
  get_dataset: '获取数据集详情',
  list_kbs: '列出知识库',
  query_kb: '知识库检索',
  list_tasks: '查询任务列表',
  get_task: '查询任务详情',
  create_task: '创建评测任务',
  cancel_task: '取消任务',
  confirm_case_set: '确认用例入库',
  get_report: '读取评测报告',
}

const nativeToolNames = new Set(['read', 'write', 'edit', 'bash', 'web_search', 'web_fetch', 'task'])

const toolDisplayName = computed(() => {
  if (nativeToolNames.has(props.tool)) return props.tool
  return toolNameMap[props.tool] || props.tool
})

const formattedLatency = computed(() => formatLatency(props.latencyMs))
const truncated = computed(() => props.truncated === true)
const source = computed(() => props.source || '')
const redacted = computed(() => props.redacted === true)
const isAudioOutput = computed(() => ['audio.speech_synthesis', 'audio.voiceclone'].includes(props.tool))
const previewMode = ref<'render' | 'source'>('render')
// 最终 tool_result 仍是唯一持久化终态；运行中的 output_delta 只来自服务端
// 受控窗口，不含完整 Observation、历史正文或未脱敏错误。
const displayedOutputText = ref('')
const isStreamingOutput = ref(false)

function asRecord(value: unknown): Record<string, unknown> | null {
  return value && typeof value === 'object' && !Array.isArray(value) ? (value as Record<string, unknown>) : null
}

function stringField(value: unknown): string {
  return typeof value === 'string' ? value : value == null ? '' : String(value)
}

function asNonNegInt(value: unknown, fallback = 0): number {
  const parsed = Number(value)
  return Number.isFinite(parsed) && parsed >= 0 ? Math.trunc(parsed) : fallback
}

const argsRecord = computed(() => asRecord(props.args) || {})
const resultRecord = computed(() => asRecord(props.result))
const liveOutputText = computed(() => props.streamOutput?.text || '')
const hasLiveOutput = computed(() => !!liveOutputText.value)
const liveOutputLines = computed(() => toLineItems(liveOutputText.value, props.streamOutput?.startLine || 1))
const recoveryHint = computed(() => props.recovery?.repair_hint || '')
const recoveryAction = computed(() => props.recovery?.suggested_action || '')

const headerHint = computed(() => {
  // 收起态只标识这是一次 ToolCall，具体路径、命令和内容统一放到展开区。
  if (nativeToolNames.has(props.tool)) return 'ToolCall'
  return `ToolCall · ${props.tool}`
})

type InputField = { label: string; value: string; mono?: boolean; cmd?: boolean }

const inputFields = computed(() => {
  const args = argsRecord.value
  const fields: InputField[] = []
  if (props.tool === 'read') {
    if (args.path) fields.push({ label: '文件', value: stringField(args.path), mono: true })
    const offset = args.offset ?? args.next_offset ?? 0
    fields.push({ label: '起始行', value: String(asNonNegInt(offset) + 1) })
    if (args.limit != null) fields.push({ label: '行数', value: String(args.limit) })
    return fields
  }
  if (props.tool === 'bash') return fields
  if ((props.tool === 'write' || props.tool === 'edit') && args.path) {
    fields.push({ label: '文件', value: stringField(args.path), mono: true })
    if (props.tool === 'edit' && args.old) {
      fields.push({ label: '查找', value: stringField(args.old) })
    }
    return fields
  }
  if (props.tool === 'web_search' && args.query) {
    fields.push({ label: '关键词', value: stringField(args.query) })
    return fields
  }
  if (props.tool === 'web_fetch' && args.url) {
    fields.push({ label: '网址', value: stringField(args.url), mono: true })
    return fields
  }
  return Object.entries(args)
    .filter(([, value]) => value !== undefined)
    .slice(0, 8)
    .map(([key, value]): InputField => ({
      label: key,
      value: typeof value === 'string' ? value : formatJson(value),
      mono: true,
    }))
})

/** 工具卡代码/文档预览的行号与正文，避免长文本失去定位上下文。 */
type LineItem = { n: number; text: string }

/** 将工具入参或受控输出按完整行拆分，保留 read 的实际起始行号。 */
function toLineItems(text: string, start = 1): LineItem[] {
  if (!text) return []
  return text.replace(/\r\n?/g, '\n').replace(/\n$/, '').split('\n').map((line, index) => ({
    n: start + index,
    text: line,
  }))
}

const toolCallText = computed(() => {
  const args = argsRecord.value
  if (props.tool === 'bash') return stringField(args.command)
  if (props.tool === 'write') return stringField(args.content)
  if (props.tool === 'edit') return stringField(args.new)
  if (inputFields.value.length) return ''
  return formatJson(props.args ?? {})
})

const toolCallLines = computed(() => toLineItems(toolCallText.value))

const toolCallCodeLabel = computed(() => {
  if (props.tool === 'bash') return 'command'
  if (props.tool === 'write') return 'content'
  if (props.tool === 'edit') return 'new'
  return ''
})

const readMeta = computed(() => {
  const data = resultRecord.value
  const read = asRecord(data?.read)
  if (!read) return null
  return {
    start: asNonNegInt(read.start_line) + 1,
    end: asNonNegInt(read.end_line),
    total: asNonNegInt(read.total_lines),
    count: asNonNegInt(read.lines_read),
    next: read.next_offset,
  }
})

const previewText = computed(() => {
  const data = resultRecord.value
  const read = asRecord(data?.read)
  if (read && typeof read.preview === 'string') return read.preview
  const write = asRecord(data?.write)
  if (write && typeof write.preview === 'string') return write.preview
  if (props.tool === 'bash') {
    if (typeof props.result === 'string') return props.result
    const bash = asRecord(data?.bash)
    if (bash && typeof bash.preview === 'string') return bash.preview
    if (typeof data?.summary === 'string') return data.summary
  }
  const web = asRecord(data?.web)
  if (web && typeof web.preview === 'string') return web.preview
  return ''
})

const displayedPreviewText = computed(() => (previewText.value ? displayedOutputText.value : ''))

/** 服务端下发的实际预览上限（read/web 的 preview_limit_chars），提示文案不硬编码数字。 */
const previewLimitLabel = computed(() => {
  const limit =
    asNonNegInt(asRecord(resultRecord.value?.read)?.preview_limit_chars) ||
    asNonNegInt(asRecord(resultRecord.value?.web)?.preview_limit_chars)
  return limit > 0 ? limit.toLocaleString('en-US') : ''
})

/** read/write/bash/web 的受控预览是否停在截断边界（服务端 preview_truncated 标记）。 */
const previewCut = computed(
  () =>
    asRecord(resultRecord.value?.read)?.preview_truncated === true ||
    asRecord(resultRecord.value?.write)?.preview_truncated === true ||
    asRecord(resultRecord.value?.bash)?.preview_truncated === true ||
    asRecord(resultRecord.value?.web)?.preview_truncated === true,
)

/** 截断尾部提示：read 说明全文行数仍已提供给模型；其余工具不夸大模型可见范围。 */
const previewCutHint = computed(() => {
  if (!previewCut.value) return ''
  const limit = previewLimitLabel.value
  if (props.tool === 'read' && readMeta.value?.total) {
    return `预览已截断：${limit ? `仅展示前 ${limit} 字符，` : ''}全文 ${readMeta.value.total} 行已提供给模型`
  }
  return `预览已按受控上限截断${limit ? `（前 ${limit} 字符）` : ''}，超出部分不在浏览器展示`
})

const outputLines = computed(() => {
  if (!displayedPreviewText.value || !['read', 'write', 'bash', 'web_fetch'].includes(props.tool)) return []
  const start = props.tool === 'read'
    ? asNonNegInt(asRecord(resultRecord.value?.read)?.start_line) + 1
    : 1
  return toLineItems(displayedPreviewText.value, start)
})

const isMarkdownFile = computed(() => {
  const path = stringField(argsRecord.value.path || asRecord(resultRecord.value?.read)?.path)
  return /\.(md|markdown|mdx)$/i.test(path)
})

/** web_fetch 返回 Markdown 正文时与 .md 文件同样支持「渲染/源码」双视图。 */
const webMeta = computed(() => {
  if (props.tool !== 'web_fetch') return null
  const web = asRecord(resultRecord.value?.web)
  return web ? { format: stringField(web.format) } : null
})

const isMarkdownOutput = computed(
  () => isMarkdownFile.value || webMeta.value?.format === 'markdown',
)

const showMarkdownOutput = computed(
  () =>
    props.status === 'ok' &&
    !!previewText.value &&
    isMarkdownOutput.value &&
    previewMode.value === 'render' &&
    !isStreamingOutput.value,
)

const resultSummary = computed(() => {
  const data = resultRecord.value
  if (typeof data?.summary === 'string') return data.summary
  return ''
})

const playUrl = computed(() => {
  const result = props.result
  if (!result || typeof result !== 'object') return ''
  const data = result as Record<string, unknown>
  const url = data.content_url
  if (typeof url === 'string' && url.startsWith('/api/files/') && url.includes('/content')) return url
  const id = data.file_id
  if (typeof id === 'string' && id) return `/api/files/${id}/content`
  return ''
})

const transcriptText = computed(() => {
  if (!props.result || typeof props.result !== 'object') return ''
  const transcript = (props.result as Record<string, unknown>).transcript
  return typeof transcript === 'string' ? transcript : ''
})

const statusClass = computed(() => props.status)

const stateText = computed(() => {
  if (props.status === 'pending') return props.progress?.message || '执行中'
  if (isStreamingOutput.value) return '输出呈现中'
  if (props.status === 'fail') return '调用失败'
  return '调用成功'
})

const resolvedOutputText = computed(() => {
  if (props.result === undefined || props.result === null || props.result === '') return '{}'
  if (props.tool === 'task' && typeof props.result === 'object') {
    const data = props.result as Record<string, unknown>
    const task = data.task
    if (task && typeof task === 'object') {
      const meta = task as Record<string, unknown>
      const goal = typeof meta.goal === 'string' ? meta.goal : '未命名目标'
      const steps = Array.isArray(meta.steps) ? meta.steps : []
      const summary = typeof data.summary === 'string' ? data.summary : '任务已拆解'
      const lines = steps.map((step, index) => {
        if (!step || typeof step !== 'object') return `${index + 1}. 无效步骤`
        const item = step as Record<string, unknown>
        return `${index + 1}. [${String(item.status || 'pending')}] ${String(item.title || '')}`
      })
      return `${summary}\n目标：${goal}${lines.length ? `\n${lines.join('\n')}` : ''}`
    }
  }
  if ((props.tool === 'web_search' || props.tool === 'web_fetch') && typeof props.result === 'object') {
    const data = props.result as Record<string, unknown>
    const summary = typeof data.summary === 'string' ? data.summary : '网络工具已完成'
    const web = data.web
    if (web && typeof web === 'object') {
      const meta = web as Record<string, unknown>
      const title = typeof meta.title === 'string' && meta.title ? meta.title : '网页正文'
      const preview = typeof meta.preview === 'string' ? meta.preview : ''
      return `${summary}\n${title}${preview ? `\n\n受控预览：\n${preview}` : ''}`
    }
    const search = data.search
    if (search && typeof search === 'object') {
      const meta = search as Record<string, unknown>
      const query = typeof meta.query === 'string' ? meta.query : ''
      const results = Array.isArray(meta.results) ? meta.results : []
      const lines = results.map((result, index) => {
        if (!result || typeof result !== 'object') return `${index + 1}. 无效结果`
        const item = result as Record<string, unknown>
        return `${index + 1}. ${String(item.title || item.url || '')}`
      })
      return `${summary}${query ? `\n关键词：${query}` : ''}${lines.length ? `\n${lines.join('\n')}` : ''}`
    }
  }
  return formatJson(props.result)
})

function formatJson(val: any): string {
  if (typeof val === 'string') return val
  try {
    return JSON.stringify(val, null, 2)
  } catch (_) {
    return String(val)
  }
}

const streamSourceText = computed(() => {
  if (props.status !== 'ok') return ''
  return previewText.value || resolvedOutputText.value
})

let streamFrame: number | undefined
let streamVersion = 0

/** 停止旧结果的渲染帧，避免连续 ToolCall 回填时串写到下一张卡片。 */
function stopOutputStream(): void {
  streamVersion += 1
  if (streamFrame !== undefined) {
    window.cancelAnimationFrame(streamFrame)
    streamFrame = undefined
  }
}

function prefersReducedMotion(): boolean {
  if (typeof window === 'undefined') return false
  return window.matchMedia?.('(prefers-reduced-motion: reduce)')?.matches === true
}

/** 将已脱敏的 ToolCard 输出按帧渐显，保留行号和可读性。 */
function revealOutput(text: string): void {
  stopOutputStream()
  if (!text) {
    displayedOutputText.value = ''
    isStreamingOutput.value = false
    return
  }
  const shouldAnimate = !props.noAnim
    && !prefersReducedMotion()
    && !isAudioOutput.value
    && props.tool !== 'image.generate'
  if (!shouldAnimate) {
    displayedOutputText.value = text
    isStreamingOutput.value = false
    return
  }

  const version = streamVersion
  const duration = Math.min(1400, Math.max(420, text.length * 4))
  const startedAt = performance.now()
  displayedOutputText.value = ''
  isStreamingOutput.value = true
  isOpen.value = true

  const step = (now: number) => {
    if (version !== streamVersion) return
    const progress = Math.min(1, (now - startedAt) / duration)
    const chars = Math.max(1, Math.ceil(text.length * progress))
    displayedOutputText.value = text.slice(0, chars)
    if (progress < 1) {
      streamFrame = window.requestAnimationFrame(step)
      return
    }
    streamFrame = undefined
    isStreamingOutput.value = false
  }
  streamFrame = window.requestAnimationFrame(step)
}

watch(
  streamSourceText,
  (text) => {
    if (props.status !== 'ok') {
      stopOutputStream()
      displayedOutputText.value = ''
      isStreamingOutput.value = false
      return
    }
    revealOutput(text)
  },
  { immediate: true },
)

onBeforeUnmount(stopOutputStream)
</script>

<style scoped>
.tool-card {
  border: 1px solid var(--border-subtle);
  border-radius: 14px;
  background: var(--bg-main);
  overflow: hidden;
  max-width: 92%;
  box-shadow: 0 1px 2px rgba(17, 24, 39, 0.04);
  transform-origin: 28px 100%;
  will-change: transform, opacity;
  animation: tool-card-pop 0.42s cubic-bezier(0.22, 0.9, 0.28, 1);
  transition: border-color 0.24s ease, box-shadow 0.24s ease, background 0.24s ease;
}
.tool-card.is-pending {
  border-color: color-mix(in srgb, var(--accent-info) 34%, var(--border-subtle));
  box-shadow: 0 7px 22px color-mix(in srgb, var(--accent-info) 12%, transparent);
}
.tool-card.is-streaming {
  border-color: color-mix(in srgb, var(--accent-success) 30%, var(--border-subtle));
}
.tool-head {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 11px 14px;
  cursor: pointer;
  user-select: none;
}
.tool-head:hover {
  background: var(--row-hover);
}
.tool-status {
  width: 18px;
  height: 18px;
  flex: 0 0 18px;
  display: grid;
  place-items: center;
}
.tool-status.pending {
  color: var(--accent-info);
  animation: spin 1.2s linear infinite;
}
.tool-pulse {
  width: 7px;
  height: 7px;
  border-radius: 999px;
  background: var(--accent-info);
  box-shadow: 0 0 0 0 color-mix(in srgb, var(--accent-info) 50%, transparent);
  animation: tool-pulse 1.45s ease-out infinite;
}
@keyframes spin {
  to {
    transform: rotate(360deg);
  }
}
@keyframes tool-pulse {
  70% {
    box-shadow: 0 0 0 6px transparent;
  }
  100% {
    box-shadow: 0 0 0 0 transparent;
  }
}
.tool-status.ok {
  color: var(--accent-success);
}
.tool-status.fail {
  color: var(--accent-error);
}
.tool-title-wrap {
  display: flex;
  flex-direction: column;
  gap: 2px;
}
.tool-name {
  font-size: 13px;
  font-weight: 600;
  color: var(--text-primary);
}
.tool-sub-tag {
  font-size: 10px;
  font-weight: 500;
  color: var(--text-tertiary);
  letter-spacing: 0.02em;
}
.tool-meta-right {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-left: auto;
}
.tool-latency {
  font-size: 11px;
  font-weight: 500;
  color: var(--text-tertiary);
  background: var(--bg-elevated);
  padding: 1px 6px;
  border-radius: 4px;
}
.tool-flag,
.tool-source {
  font-size: 10px;
  color: var(--text-tertiary);
  background: var(--bg-elevated);
  padding: 1px 5px;
  border-radius: 4px;
  max-width: 130px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.tool-state-text {
  font-size: 12px;
  color: var(--text-tertiary);
}
.tool-state-text.pending {
  color: var(--accent-info);
  font-weight: 600;
}
.tool-state-text.ok {
  color: var(--accent-success);
}
.tool-state-text.fail {
  color: var(--accent-error);
  font-weight: 500;
}
.tool-head .chev {
  margin-left: 4px;
  transition: transform 0.18s ease;
  color: var(--text-tertiary);
  display: grid;
  place-items: center;
}
.tool-card.open .tool-head .chev {
  transform: rotate(180deg);
}
.tool-detail {
  border-top: 1px solid var(--border-subtle);
  padding: 12px 14px;
  background: var(--bg-elevated);
  overflow: hidden;
}
.tool-detail-enter-active,
.tool-detail-leave-active {
  transition: max-height 0.28s cubic-bezier(0.22, 0.9, 0.28, 1), opacity 0.18s ease, transform 0.28s ease, padding 0.28s ease;
}
.tool-detail-enter-from,
.tool-detail-leave-to {
  max-height: 0;
  opacity: 0;
  padding-top: 0;
  padding-bottom: 0;
  transform: translateY(-6px);
}
.tool-detail-enter-to,
.tool-detail-leave-from {
  max-height: 760px;
  opacity: 1;
  transform: translateY(0);
}
.td-label-row {
  display: flex;
  align-items: center;
  gap: 8px;
}
.td-label {
  font-family: var(--font-mono);
  font-size: 10px;
  letter-spacing: 0.1em;
  text-transform: uppercase;
  color: var(--text-tertiary);
  margin-bottom: 5px;
}
.td-label-row .td-label {
  margin-bottom: 5px;
}
.td-stream-state {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  margin-bottom: 5px;
  color: var(--accent-success);
  font-size: 10px;
  font-weight: 600;
}
.td-stream-dot {
  width: 5px;
  height: 5px;
  border-radius: 50%;
  background: currentColor;
  animation: stream-dot 0.9s ease-in-out infinite;
}
@keyframes stream-dot {
  50% {
    opacity: 0.35;
    transform: scale(0.65);
  }
}
.td-block {
  margin-bottom: 8px;
}
.td-block:last-child {
  margin-bottom: 0;
}
pre.code {
  margin: 0;
  background: #0f172a;
  color: #e2e8f0;
  border-radius: 8px;
  padding: 10px 12px;
  font-family: var(--font-mono);
  font-size: 11.5px;
  line-height: 1.6;
  overflow: auto;
  max-height: 320px;
}
.td-fields {
  margin: 0;
  display: grid;
  gap: 6px;
}
.tool-call-code-wrap {
  margin-top: 8px;
}
.td-code-caption {
  margin: 0 0 4px 2px;
  color: var(--text-tertiary);
  font-size: 10px;
  letter-spacing: 0.04em;
}
.td-field {
  display: grid;
  grid-template-columns: 56px 1fr;
  gap: 8px;
  align-items: start;
}
.td-field dt {
  color: var(--text-tertiary);
  font-size: 11px;
  padding-top: 1px;
}
.td-field dd {
  margin: 0;
  color: var(--text-primary);
  font-size: 12.5px;
  line-height: 1.5;
  overflow-wrap: anywhere;
  white-space: pre-wrap;
}
.td-field dd.mono,
.td-field dd.cmd {
  font-family: var(--font-mono);
  font-size: 12px;
}
.td-field dd.cmd {
  background: #0f172a;
  color: #e2e8f0;
  border-radius: 6px;
  padding: 6px 8px;
}
.td-summary {
  margin: 0 0 6px;
  color: var(--text-secondary);
  font-size: 12.5px;
  line-height: 1.5;
}
.tool-recovery {
  display: grid;
  gap: 6px;
  padding: 10px 11px;
  border: 1px solid color-mix(in srgb, var(--accent-error) 28%, var(--border-subtle));
  border-radius: 8px;
  background: color-mix(in srgb, var(--accent-error) 5%, var(--bg-main));
  color: var(--text-secondary);
  font-size: 12px;
  line-height: 1.5;
}
.tool-recovery-title {
  color: var(--accent-error);
  font-weight: 600;
}
.tool-recovery-hint {
  margin: 0;
}
.tool-recovery-action {
  color: var(--text-tertiary);
  font-size: 10px;
}
.tool-output-loading {
  padding: 11px 12px;
  border: 1px solid color-mix(in srgb, var(--accent-info) 18%, var(--border-subtle));
  border-radius: 8px;
  background: color-mix(in srgb, var(--accent-info) 5%, var(--bg-main));
}
.tool-loading-copy {
  display: flex;
  align-items: center;
  gap: 8px;
  color: var(--text-secondary);
  font-size: 12px;
}
.tool-loading-orbit {
  width: 12px;
  height: 12px;
  flex: 0 0 12px;
  border: 2px solid color-mix(in srgb, var(--accent-info) 24%, transparent);
  border-top-color: var(--accent-info);
  border-radius: 50%;
  animation: spin 0.8s linear infinite;
}
.tool-loading-lines {
  display: grid;
  gap: 6px;
  margin-top: 11px;
}
.tool-loading-lines span {
  display: block;
  height: 7px;
  border-radius: 999px;
  background: linear-gradient(90deg, var(--bg-elevated) 20%, color-mix(in srgb, var(--accent-info) 14%, var(--bg-elevated)) 45%, var(--bg-elevated) 70%);
  background-size: 220% 100%;
  animation: output-shimmer 1.3s ease-in-out infinite;
}
.tool-loading-lines span:nth-child(2) {
  width: 82%;
  animation-delay: 0.12s;
}
.tool-loading-lines span:nth-child(3) {
  width: 60%;
  animation-delay: 0.24s;
}
@keyframes output-shimmer {
  to {
    background-position: -220% 0;
  }
}
.td-meta {
  margin-bottom: 8px;
  color: var(--text-tertiary);
  font-size: 11px;
}
.td-preview-cut {
  margin-top: 6px;
  padding-top: 6px;
  border-top: 1px dashed var(--border-subtle);
  color: var(--text-tertiary);
  font-size: 11px;
}
.td-tabs {
  display: flex;
  gap: 6px;
  margin-bottom: 8px;
}
.td-tab {
  border: 1px solid var(--border-subtle);
  background: var(--bg-main);
  color: var(--text-secondary);
  border-radius: 6px;
  padding: 2px 8px;
  font-size: 11px;
  cursor: pointer;
}
.td-tab.active {
  color: var(--accent-success);
  border-color: color-mix(in srgb, var(--accent-success) 40%, var(--border-subtle));
  background: color-mix(in srgb, var(--accent-success) 10%, var(--bg-main));
}
.line-block {
  max-height: 360px;
  overflow: auto;
  background: #0f172a;
  color: #e2e8f0;
  border-radius: 8px;
  padding: 6px 0;
}
.line-block.is-streaming-output {
  border: 1px solid color-mix(in srgb, var(--accent-success) 26%, transparent);
}
.tool-call-code {
  max-height: 300px;
}
.ln-row {
  display: grid;
  grid-template-columns: 44px 1fr;
  gap: 8px;
  min-height: 20px;
}
.ln-no {
  color: #64748b;
  text-align: right;
  font-size: 11px;
  line-height: 1.65;
  user-select: none;
}
.ln-text {
  font-family: var(--font-mono);
  font-size: 12px;
  line-height: 1.65;
  white-space: pre-wrap;
  overflow-wrap: anywhere;
  padding-right: 10px;
}
.stream-tail {
  min-height: 20px;
  padding-left: 52px;
  color: var(--accent-success);
  font-size: 12px;
}
.stream-cursor {
  display: inline-block;
  margin-left: 1px;
  color: var(--accent-success);
  animation: stream-cursor-blink 0.78s steps(2, start) infinite;
}
@keyframes stream-cursor-blink {
  50% {
    opacity: 0;
  }
}
.tool-card :deep(.tool-md) {
  font-size: 13.5px;
  line-height: 1.65;
  max-height: 360px;
  overflow: auto;
  padding: 8px 10px;
  border-radius: 8px;
  background: var(--bg-main);
}
.tool-card :deep(.tool-md .md-p),
.tool-card :deep(.tool-md .md-li-bullet),
.tool-card :deep(.tool-md .md-li-num) {
  font-size: 13.5px;
}
.tool-card.no-anim {
  animation: none;
}
.tool-audio {
  display: block;
  width: 100%;
  margin-bottom: 10px;
  height: 36px;
}
.transcript-card {
  margin-bottom: 10px;
  padding: 10px 12px;
  border: 1px solid color-mix(in srgb, var(--accent-info) 28%, var(--border-subtle));
  border-radius: 8px;
  background: var(--bg-main);
}
.transcript-label {
  margin-bottom: 5px;
  color: var(--accent-info);
  font-size: 10px;
  font-weight: 700;
  letter-spacing: 0.08em;
}
.transcript-text {
  color: var(--text-primary);
  font-size: 13px;
  line-height: 1.65;
  white-space: pre-wrap;
  overflow-wrap: anywhere;
}
@keyframes tool-card-pop {
  from {
    opacity: 0;
    transform: translateY(14px) scale(0.98);
  }
  65% {
    opacity: 1;
    transform: translateY(-1px) scale(1.005);
  }
  to {
    opacity: 1;
    transform: translateY(0) scale(1);
  }
}

@media (prefers-reduced-motion: reduce) {
  .tool-card,
  .tool-status.pending,
  .tool-pulse,
  .tool-loading-orbit,
  .tool-loading-lines span,
  .td-stream-dot,
  .stream-cursor {
    animation: none;
  }
  .tool-detail-enter-active,
  .tool-detail-leave-active,
  .tool-head .chev {
    transition: none;
  }
}

@media (max-width: 640px) {
  .tool-head {
    padding: 8px 10px;
    gap: 8px;
  }
  .tool-name {
    font-size: 12.5px;
  }
  .tool-sub-tag {
    font-size: 10px;
  }
  .tool-meta-right {
    gap: 6px;
  }
  .tool-latency {
    font-size: 10px;
    padding: 1px 4px;
  }
  .tool-state-text {
    font-size: 11px;
  }
  .tool-detail {
    padding: 10px 10px;
  }
  pre.code {
    font-size: 11px;
    padding: 8px 10px;
  }
}
</style>
