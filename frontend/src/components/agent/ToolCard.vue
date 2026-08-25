<template>
  <div class="tool-card" :class="{ open: isOpen, 'no-anim': noAnim }" :data-tool="tool">
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
        <div class="tool-name">{{ toolChineseName }}</div>
        <div class="tool-sub-tag" :title="headerHint">{{ headerHint }}</div>
      </div>

      <div class="tool-meta-right">
        <span v-if="formattedLatency" class="tool-latency mono">{{ formattedLatency }}</span>
        <span v-if="redacted" class="tool-flag">已脱敏</span>
        <span v-if="truncated" class="tool-flag">已截断</span>
        <span v-if="source" class="tool-source mono" :title="source">{{ source }}</span>
        <span class="tool-state-text" :class="statusClass">
          {{ stateText }}
        </span>
      </div>

      <div class="chev">
        <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
          <polyline points="6 9 12 15 18 9"></polyline>
        </svg>
      </div>
    </div>

    <div v-show="isOpen" class="tool-detail">
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
        <div class="td-label">输入</div>
        <dl v-if="inputFields.length" class="td-fields">
          <div v-for="(field, fieldIdx) in inputFields" :key="`${field.label}-${fieldIdx}`" class="td-field">
            <dt>{{ field.label }}</dt>
            <dd :class="{ mono: field.mono, cmd: field.cmd }">{{ field.value }}</dd>
          </div>
        </dl>
        <pre v-else class="code">{{ formatJson(args ?? {}) }}</pre>
      </div>
      <div class="td-block">
        <div class="td-label">{{ status === 'fail' ? '输出' : '结果' }}</div>
        <p v-if="resultSummary && !readMeta" class="td-summary">{{ resultSummary }}</p>
        <div v-if="readMeta" class="td-meta mono">
          第 {{ readMeta.start }}–{{ readMeta.end }} 行 / 共 {{ readMeta.total }} 行
          <span v-if="readMeta.next != null"> · 下一页 offset={{ readMeta.next }}</span>
          <span v-else> · 已读完</span>
        </div>
        <div v-if="isMarkdownFile && previewText && status === 'ok'" class="td-tabs">
          <button type="button" class="td-tab" :class="{ active: previewMode === 'render' }" @click="previewMode = 'render'">渲染</button>
          <button type="button" class="td-tab" :class="{ active: previewMode === 'source' }" @click="previewMode = 'source'">源码</button>
        </div>
        <MarkdownView
          v-if="showMarkdownOutput"
          :content="previewText"
          custom-class="tool-md"
        />
        <div v-else-if="previewLines.length && status === 'ok'" class="line-block" role="region" aria-label="文件内容">
          <div v-for="line in previewLines" :key="line.n" class="ln-row">
            <span class="ln-no mono">{{ line.n }}</span>
            <span class="ln-text">{{ line.text }}</span>
          </div>
        </div>
        <pre v-else-if="previewText && status === 'ok'" class="code">{{ previewText }}</pre>
        <pre v-else class="code">{{ outputText }}</pre>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, watch } from 'vue'
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

const toolChineseName = computed(() => {
  return toolNameMap[props.tool] || props.tool
})

const formattedLatency = computed(() => formatLatency(props.latencyMs))
const truncated = computed(() => props.truncated === true)
const source = computed(() => props.source || '')
const redacted = computed(() => props.redacted === true)
const isAudioOutput = computed(() => ['audio.speech_synthesis', 'audio.voiceclone'].includes(props.tool))
const previewMode = ref<'render' | 'source'>('render')

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

const headerHint = computed(() => {
  const path = stringField(argsRecord.value.path)
  const command = stringField(argsRecord.value.command)
  if (props.tool === 'read' && path) return path
  if (props.tool === 'bash' && command) return command
  if ((props.tool === 'write' || props.tool === 'edit') && path) return path
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
  if (props.tool === 'bash' && args.command) {
    fields.push({ label: '命令', value: stringField(args.command), mono: true, cmd: true })
    return fields
  }
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

const readMeta = computed(() => {
  const data = resultRecord.value
  const read = asRecord(data?.read)
  if (!read) return null
  return {
    start: asNonNegInt(read.start_line) + 1,
    end: asNonNegInt(read.end_line),
    total: asNonNegInt(read.total_lines),
    next: read.next_offset,
  }
})

const previewText = computed(() => {
  const data = resultRecord.value
  const read = asRecord(data?.read)
  if (read && typeof read.preview === 'string') return read.preview
  if (props.tool === 'bash') {
    if (typeof props.result === 'string') return props.result
    if (typeof data?.summary === 'string') return data.summary
  }
  const web = asRecord(data?.web)
  if (web && typeof web.preview === 'string') return web.preview
  return ''
})

const previewLines = computed(() => {
  if (props.tool !== 'read' || !previewText.value) return []
  const start = asNonNegInt(asRecord(resultRecord.value?.read)?.start_line)
  return previewText.value.replace(/\n$/, '').split('\n').map((text, index) => ({
    n: start + index + 1,
    text,
  }))
})

const isMarkdownFile = computed(() => {
  const path = stringField(argsRecord.value.path || asRecord(resultRecord.value?.read)?.path)
  return /\.(md|markdown|mdx)$/i.test(path)
})

const showMarkdownOutput = computed(
  () =>
    props.status === 'ok' &&
    !!previewText.value &&
    isMarkdownFile.value &&
    previewMode.value === 'render',
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
  if (props.status === 'pending') return '调用中'
  if (props.status === 'fail') return '调用失败'
  return '调用成功'
})

const outputText = computed(() => {
  if (props.status === 'pending') return '…'
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
</script>

<style scoped>
.tool-card {
  border: 1px solid var(--border-subtle);
  border-radius: 14px;
  background: var(--bg-main);
  overflow: hidden;
  max-width: 92%;
  box-shadow: 0 1px 2px rgba(17, 24, 39, 0.04);
  animation: msg-in 0.26s cubic-bezier(0.2, 0.9, 0.3, 1);
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
@keyframes spin {
  to {
    transform: rotate(360deg);
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
}
.td-label {
  font-family: var(--font-mono);
  font-size: 10px;
  letter-spacing: 0.1em;
  text-transform: uppercase;
  color: var(--text-tertiary);
  margin-bottom: 5px;
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
.td-meta {
  margin-bottom: 8px;
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
@keyframes msg-in {
  from {
    opacity: 0;
    transform: translateY(8px);
  }
  to {
    opacity: 1;
    transform: none;
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
