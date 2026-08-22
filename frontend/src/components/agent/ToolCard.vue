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
        <div class="tool-sub-tag">ToolCall · {{ tool }}</div>
      </div>

      <div class="tool-meta-right">
        <span v-if="formattedLatency" class="tool-latency mono">{{ formattedLatency }}</span>
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
        <div class="td-label">输入 arguments</div>
        <pre class="code">{{ formatJson(args ?? {}) }}</pre>
      </div>
      <div class="td-block">
        <div class="td-label">{{ status === 'fail' ? '输出 error' : '输出 result' }}</div>
        <pre class="code">{{ outputText }}</pre>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, watch } from 'vue'
import { formatLatency } from '../../utils/format'

const props = withDefaults(
  defineProps<{
    tool: string
    args?: any
    result?: any
    status?: 'pending' | 'ok' | 'fail'
    latencyMs?: number
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
    if (status === 'ok' && ['audio.speech_recognition', 'audio.speech_synthesis', 'audio.voiceclone'].includes(props.tool)) {
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
const isAudioOutput = computed(() => ['audio.speech_synthesis', 'audio.voiceclone'].includes(props.tool))

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
  max-height: 200px;
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
