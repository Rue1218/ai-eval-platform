<template>
  <div class="loop-workspace">
    <div class="loop-tabs"><button class="workspace-tab" :class="{active:tab==='chat'}" @click="tab='chat'">对话</button><button class="workspace-tab" :class="{active:tab==='trace'}" :disabled="!state" @click="tab='trace'">轨迹 <small v-if="state?.cursor" class="trace-tab-count">{{ state.cursor }}</small></button><span class="loop-status"><i :class="{running:busy}"/>{{ status }}</span><button @click="runtimeOpen=!runtimeOpen">运行信息</button></div>
    <p v-if="state && state.connection !== 'online'" class="loop-notice" role="status">{{ state.connection === 'connecting' ? '正在同步会话…' : '连接中断，状态待同步。' }}<button @click="store.clients.get(sessionId)?.connect()">重新连接</button></p>
    <p v-if="state?.error || error" class="loop-notice error" role="alert">{{ state?.error || error }}</p>
    <div class="loop-content">
      <div class="loop-center">
        <section v-if="tab==='chat'" ref="chatShell" class="loop-chat-shell" :class="{ 'is-resizing': isResizing }" :style="chatShellStyle" aria-label="对话内容区域">
          <div ref="scroller" class="loop-conversation" @scroll="trackScroll">
          <div v-if="!rows.length" class="loop-welcome"><span>AI EVAL · AGENT LOOP</span><h2>从一个目标开始，<br>让每一步都有依据。</h2><p>在工作区处理文件、查找资料，或创建评测任务。</p><div><button v-for="prompt in prompts" :key="prompt" @click="fill(prompt)">{{ prompt }} ↗</button></div></div>
          <button v-if="shown < rows.length" class="history-more" @click="shown+=80">显示更早的 {{ Math.min(80, rows.length-shown) }} 条记录</button>
          <template v-for="row in visibleRows" :key="row.key">
            <article v-if="row.role==='user'" class="loop-message user"><header>你</header><div class="history-files"><AttachmentPreview v-for="file in attachments[row.key] || []" :key="file.file_id" :attachment="file"/></div><p>{{ row.content }}</p></article>
            <ToolRunCard v-else-if="'status' in row && 'name' in row" :tool="row as ToolRun" :interactions="interactions(row)" :can-control="canControl" :online="!!state?.ready" @respond="respond"/>
            <article v-else class="loop-message assistant"><header><ProviderLogo v-if="row.request_summary?.model" :provider="getProviderLogoKey({model:row.request_summary.model})" :size="18"/>{{ row.request_summary?.model || '助手' }}<small v-if="row.request_summary">{{ row.request_summary.reasoning_effort }} · step {{ row.correlation.step }}</small><button v-if="row.text" @click="copy(row.text)">复制</button></header><ReasoningBlock v-if="row.reasoning && ui?.permissions.reasoning" :content="row.reasoning" :ended="row.ended" :interrupted="row.interrupted"/><MarkdownView v-if="row.text" :content="row.text"/><p v-else-if="!row.ended" class="muted">正在响应…</p><small v-if="row.interrupted || row.error_code">{{ row.interrupted ? '本次输出已中断' : row.error_code }}</small></article>
          </template>
          <p v-if="!busy && state?.phase && ['max_tokens','max_steps','cancelled','interrupted','error'].includes(state.phase)" class="loop-notice">{{ finishLabels[state.phase] }}</p>
          </div>
          <div class="loop-composer-wrap">
            <AgentComposer ref="composer" :draft="draft" :ui="ui" :profile="selectedProfile" :profiles="ui?.profiles || []" :effort="effort" :meter="summary?.context_meter" :busy="busy" :cancelling="!!state?.cancelling" :can-stop="canControl && !!state?.ready && !state?.cancelling" :ready="ready" @effort="setEffort" @submit="submit" @stop="stop" @retry="retry" @model="selectProfile"/>
            <div v-if="conversationMetrics.hasData" class="conversation-metrics-bar" aria-label="全会话模型调用指标统计">
              <span class="metric-item" title="全会话平均 Token 生成速度">
                <svg class="metric-icon" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                  <path d="m12 14 4-4"/>
                  <path d="M3.34 19a10 10 0 1 1 17.32 0"/>
                </svg>
                生成token速度 {{ conversationMetrics.speed }}
              </span>
              <span class="metric-item" title="全会话 Prompt 缓存命中率">
                <svg class="metric-icon" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                  <ellipse cx="12" cy="5" rx="9" ry="3"/>
                  <path d="M3 5v14c0 1.66 4 3 9 3s9-1.34 9-3V5"/>
                  <path d="M3 12c0 1.66 4 3 9 3s9-1.34 9-3"/>
                </svg>
                缓存命中率 {{ conversationMetrics.cacheRate }}%
              </span>
              <span class="metric-item" title="全会话累计输入与输出 Token 统计">
                <svg class="metric-icon" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                  <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/>
                  <polyline points="14 2 14 8 20 8"/>
                  <line x1="16" y1="13" x2="8" y2="13"/>
                  <line x1="16" y1="17" x2="8" y2="17"/>
                  <polyline points="10 9 9 9 8 9"/>
                </svg>
                输入 {{ conversationMetrics.inputFormatted }} · 输出 {{ conversationMetrics.outputFormatted }}
              </span>
            </div>
          </div>
          <div class="loop-width-edge loop-width-edge-left" @pointerenter="previewContentResize('left', $event)" @pointermove="moveContentResizePreview('left', $event)" @pointerleave="hideContentResizePreview('left')">
            <button class="loop-width-handle" :class="{ 'is-visible': hoverResizeEdge === 'left', 'is-active': isResizing && resizeEdge === 'left' }" :style="resizeHandleStyle('left')" type="button" aria-label="向左拖拽调整对话内容宽度" aria-orientation="vertical" role="separator" :aria-valuemin="minimumChatWidth" :aria-valuemax="maximumChatWidth" :aria-valuenow="Math.round(renderedChatWidth)" @pointerdown="beginContentResize($event, 'left')" @keydown="adjustContentWidthByKey($event, 'left')">
              <span aria-hidden="true"></span>
            </button>
          </div>
          <div class="loop-width-edge loop-width-edge-right" @pointerenter="previewContentResize('right', $event)" @pointermove="moveContentResizePreview('right', $event)" @pointerleave="hideContentResizePreview('right')">
            <button class="loop-width-handle" :class="{ 'is-visible': hoverResizeEdge === 'right', 'is-active': isResizing && resizeEdge === 'right' }" :style="resizeHandleStyle('right')" type="button" aria-label="向右拖拽调整对话内容宽度" aria-orientation="vertical" role="separator" :aria-valuemin="minimumChatWidth" :aria-valuemax="maximumChatWidth" :aria-valuenow="Math.round(renderedChatWidth)" @pointerdown="beginContentResize($event, 'right')" @keydown="adjustContentWidthByKey($event, 'right')">
              <span aria-hidden="true"></span>
            </button>
          </div>
        </section>
        <TraceWorkspace v-else-if="state && trace" :state="state" :trace="trace"/>
        <button v-if="!atBottom && tab==='chat'" class="jump-bottom" @click="scrollBottom">↓ 回到最新</button>
      </div>
      <aside v-if="runtimeOpen" class="loop-runtime"><button class="runtime-close" @click="runtimeOpen=false">关闭</button><h3>当前运行</h3><p>{{ status }}</p><dl><dt>会话</dt><dd>{{ sessionId || '未发送的草稿' }}</dd><dt>实际模型</dt><dd>{{ summary?.model || '尚无实际请求' }}</dd><dt>思考档位</dt><dd>{{ summary?.reasoning_effort || '未知' }}</dd><dt>协议档版本</dt><dd>{{ summary?.profile_version || '未知' }}</dd><dt>最近活动</dt><dd v-for="event in state?.facts.slice(-5) || []" :key="event.cursor">{{ event.type }}</dd></dl><h4 v-if="tasks.length">Worker 任务</h4><div v-for="task in tasks" :key="task.key"><router-link :to="'/tasks'">{{ task.key }}</router-link><p>{{ task.status || '等待状态' }}</p><p v-if="task.progress">{{ JSON.stringify(task.progress) }}</p><router-link v-if="task.report_id" :to="`/reports/${task.report_id}`">查看报告</router-link></div><p v-for="execution in quarantined" :key="execution.key" class="loop-notice">执行范围受限 · {{ execution.reason || '等待对账' }}</p></aside>
    </div>
    <div v-if="tab==='trace'" class="loop-composer-wrap loop-trace-composer">
      <AgentComposer ref="composer" :draft="draft" :ui="ui" :profile="selectedProfile" :profiles="ui?.profiles || []" :effort="effort" :meter="summary?.context_meter" :busy="busy" :cancelling="!!state?.cancelling" :can-stop="canControl && !!state?.ready && !state?.cancelling" :ready="ready" @effort="setEffort" @submit="submit" @stop="stop" @retry="retry" @model="selectProfile"/>
      <div v-if="conversationMetrics.hasData" class="conversation-metrics-bar" aria-label="全会话模型调用指标统计">
        <span class="metric-item" title="全会话平均 Token 生成速度">
          <svg class="metric-icon" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <path d="m12 14 4-4"/>
            <path d="M3.34 19a10 10 0 1 1 17.32 0"/>
          </svg>
          生成token速度 {{ conversationMetrics.speed }}
        </span>
        <span class="metric-item" title="全会话 Prompt 缓存命中率">
          <svg class="metric-icon" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <ellipse cx="12" cy="5" rx="9" ry="3"/>
            <path d="M3 5v14c0 1.66 4 3 9 3s9-1.34 9-3V5"/>
            <path d="M3 12c0 1.66 4 3 9 3s9-1.34 9-3"/>
          </svg>
          缓存命中率 {{ conversationMetrics.cacheRate }}%
        </span>
        <span class="metric-item" title="全会话累计输入与输出 Token 统计">
          <svg class="metric-icon" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/>
            <polyline points="14 2 14 8 20 8"/>
            <line x1="16" y1="13" x2="8" y2="13"/>
            <line x1="16" y1="17" x2="8" y2="17"/>
            <polyline points="10 9 9 9 8 9"/>
          </svg>
          输入 {{ conversationMetrics.inputFormatted }} · 输出 {{ conversationMetrics.outputFormatted }}
        </span>
      </div>
    </div>
  </div>
</template>
<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, reactive, ref, watch } from 'vue'
import http, { ApiError } from '../../../api/http'
import { createRequestId } from '../../../utils/requestId'
import type { AttachmentReference } from '../../../api/types'
import type { Data, Effort, InteractionRecord, LoopProfile, LoopRecord, LoopUi, ToolRun } from '../../../api/agentLoopTypes'
import { conversationRows, identity } from '../../../agent/loop/reducer'
import type { LoopStore } from '../../../agent/loop/store'
import { useAuthStore } from '../../../stores/auth'
import { getProviderLogoKey } from '../../../utils/providerLogo'
import ProviderLogo from '../../ProviderLogo.vue'
import MarkdownView from '../MarkdownView.vue'
import AttachmentPreview from '../AttachmentPreview.vue'
import AgentComposer from './AgentComposer.vue'
import ToolRunCard from './ToolRunCard.vue'
import ReasoningBlock from './ReasoningBlock.vue'
import TraceWorkspace from './TraceWorkspace.vue'
const props = defineProps<{ sessionId: string; store: LoopStore; createSession: () => Promise<string> }>()
const auth = useAuthStore(), tab = ref('chat'), runtimeOpen = ref(false), error = ref(''), effort = ref<Effort | null>(null)
const ui = ref<LoopUi | null>(null), selectedProfileId = ref(''), shown = ref(80), attachments = ref<Record<string, AttachmentReference[]>>({})
const composer = ref<InstanceType<typeof AgentComposer>>(), scroller = ref<HTMLElement>(), chatShell = ref<HTMLElement>(), atBottom = ref(true)
type ResizeEdge = 'left' | 'right'
const chatWidth = ref<number | null>(null), isResizing = ref(false), resizeEdge = ref<ResizeEdge | null>(null), hoverResizeEdge = ref<ResizeEdge | null>(null)
const resizeHandleOffsets = ref<Record<ResizeEdge, number>>({ left: 110, right: 110 })
const minimumChatWidth = 520
const chatWidthStorageKey = 'agent-loop:chat-shell-width:v3'
const state = computed(() => props.store.sessions[props.sessionId]), trace = computed(() => props.store.traces[props.sessionId])
const draft = computed(() => props.store.draft(props.sessionId || 'draft'))

export interface ConversationMetrics {
  hasData: boolean
  speed: string
  cacheRate: number
  inputFormatted: string
  outputFormatted: string
  totalInput: number
  totalOutput: number
  totalCached: number
  totalLatencyMs: number
}

function formatMetricTokens(val: number): string {
  if (val >= 1_000_000) {
    const m = val / 1_000_000
    return `${m.toFixed(1).replace(/\.0$/, '')}M`
  }
  if (val >= 10_000) {
    return `${(val / 1_000).toFixed(0)}K`
  }
  if (val >= 1_000) {
    const k = val / 1_000
    return `${k.toFixed(1).replace(/\.0$/, '')}K`
  }
  return String(Math.max(0, Math.round(val)))
}

function loadMetricsCache(): Record<string, ConversationMetrics> {
  try {
    const raw = sessionStorage.getItem('agent-loop:conversation-metrics')
    return raw ? JSON.parse(raw) : {}
  } catch {
    return {}
  }
}

function saveMetricsCache(cache: Record<string, ConversationMetrics>) {
  try {
    sessionStorage.setItem('agent-loop:conversation-metrics', JSON.stringify(cache))
  } catch {
    // 忽略存储受限环境
  }
}

const sessionMetricsCache = reactive<Record<string, ConversationMetrics>>(loadMetricsCache())

const conversationMetrics = computed<ConversationMetrics>(() => {
  const sid = props.sessionId
  const attempts = state.value ? Object.values(state.value.attempts || {}) : []

  let totalInput = 0
  let totalOutput = 0
  let totalCached = 0
  let totalLatencyMs = 0
  let totalOutputForSpeed = 0
  let hasAttemptsData = false

  for (const a of attempts) {
    const usage = a.usage || {}
    const prompt = Number(usage.prompt_tokens ?? usage.input_tokens ?? a.request_summary?.context_meter?.input_tokens ?? 0)
    const completion = Number(usage.completion_tokens ?? usage.output_tokens ?? 0)
    const cached = Number(
      usage.cache_read_input_tokens
      ?? usage.cached_tokens
      ?? usage.prompt_tokens_details?.cached_tokens
      ?? 0
    )
    const latency = Number(a.latency_ms ?? usage.latency_ms ?? 0)

    if (prompt > 0 || completion > 0 || cached > 0 || latency > 0) {
      hasAttemptsData = true
      totalInput += prompt
      totalOutput += completion
      totalCached += cached
      if (latency > 0 && completion > 0) {
        totalLatencyMs += latency
        totalOutputForSpeed += completion
      }
    }
  }

  if (hasAttemptsData) {
    const totalLatencySec = totalLatencyMs / 1000
    const avgSpeed = totalLatencySec > 0 ? Math.round(totalOutputForSpeed / totalLatencySec) : 0
    const cacheRate = totalInput > 0 ? Math.min(100, Math.round((totalCached / totalInput) * 100)) : 0
    const result: ConversationMetrics = {
      hasData: true,
      speed: `${avgSpeed}/s`,
      cacheRate,
      inputFormatted: formatMetricTokens(totalInput),
      outputFormatted: formatMetricTokens(totalOutput),
      totalInput,
      totalOutput,
      totalCached,
      totalLatencyMs,
    }
    if (sid) {
      sessionMetricsCache[sid] = result
      saveMetricsCache(sessionMetricsCache)
    }
    return result
  }

  if (sid && sessionMetricsCache[sid]) {
    return sessionMetricsCache[sid]
  }

  return {
    hasData: false,
    speed: '0/s',
    cacheRate: 0,
    inputFormatted: '0',
    outputFormatted: '0',
    totalInput: 0,
    totalOutput: 0,
    totalCached: 0,
    totalLatencyMs: 0,
  }
})
const rows = computed(() => state.value ? conversationRows(state.value) : [])
const visibleRows = computed(() => rows.value.slice(-shown.value))
const busy = computed(() => !!state.value?.activeTurn)
/** 草稿协议档可独立于平台默认项选择；后端在提交时再次校验。 */
const selectedProfile = computed<LoopProfile | null>(() => ui.value?.profiles.find(item => item.id === selectedProfileId.value) || ui.value?.profile || null)
const ready = computed(() => !!selectedProfile.value && !!effort.value && (props.sessionId ? !!state.value?.ready : !!ui.value?.enabled))
const canControl = computed(() => !!state.value?.controlled && !!ui.value?.permissions.interactions)
const summary = computed(() => Object.values(state.value?.attempts || {}).sort((a,b)=>b.first_cursor-a.first_cursor)[0]?.request_summary)
const tasks = computed(() => Object.values(state.value?.tasks || {}))
const quarantined = computed(() => Object.values(state.value?.executions || {}).filter(e => e.event === 'execution.quarantined'))
const finishLabels: Record<string,string> = { max_tokens:'达到输出上限，本轮已结束', max_steps:'达到步骤上限，本轮已结束', cancelled:'本轮已取消', interrupted:'本轮已中断', error:'本轮失败，请查看错误信息' }
const phaseLabels: Record<string,string> = { idle:'就绪',model:'模型处理中',thinking:'正在思考',answering:'正在回答',tools:'工具执行中',waiting_interaction:'等待交互',retry_wait:'等待重试',completed:'已完成',...finishLabels }
const status = computed(() => state.value?.cancelling ? '取消中' : state.value && state.value.connection !== 'online' ? '连接待同步' : phaseLabels[state.value?.phase || 'idle'] || state.value?.phase || '就绪')
const prompts = ['查看工作区文件，说明可以如何处理', '帮我准备一次模型基准评测', '查询资料并给出可核对的来源']
const chatShellStyle = computed(() => chatWidth.value ? { width: `${chatWidth.value}px` } : undefined)
const maximumChatWidth = computed(() => Math.max(minimumChatWidth, (chatShell.value?.parentElement?.clientWidth || minimumChatWidth + 48) - 48))
const renderedChatWidth = computed(() => chatWidth.value || chatShell.value?.getBoundingClientRect().width || minimumChatWidth)
let epoch = 0
let resizeStartX = 0, resizeStartWidth = 0
const resizeHandleHeight = 96
/** 能力随会话/窗口聚焦刷新；活动请求显示自己的持久配置版本。 */
async function refreshUi() {
  const current = ++epoch, sid = props.sessionId
  try {
    const { data } = await http.get<LoopUi>(sid ? `/api/sessions/${sid}/agent-ui` : '/api/sessions/agent-ui')
    if (current !== epoch) return
    ui.value = data
    const savedProfileId = localPreference('agent-profile')
    const profile = data.profiles.find(item => item.id === selectedProfileId.value)
      || data.profiles.find(item => item.id === savedProfileId)
      || data.profile
      || null
    selectedProfileId.value = profile?.id || ''
    restoreEffort(profile)
    if (!data.permissions.reasoning && state.value) { for (const a of Object.values(state.value.attempts)) { a.reasoning = ''; delete a.reasoning_preview }; for (const event of state.value.facts) delete event.data.reasoning_preview }
    if (trace.value) {
      trace.value.denied = !data.permissions.trace
      if (!data.permissions.trace) { trace.value.events = []; trace.value.seen.clear(); trace.value.seq = -1; trace.value.catalog = null }
    }
    if (!data.permissions.interactions && state.value) for (const i of Object.values(state.value.interactions)) { delete i.nonce; delete i.spec_hash; i.restricted = true }
  } catch { if (current === epoch) { ui.value = null; error.value = '读取会话能力失败，请确认权限和服务状态' } }
}
/** 本地偏好只保存协议档 ID 和思考档位，不保存 API 端点、凭据或服务端配置。 */
function localPreference(key: string) { try { return localStorage.getItem(`${key}:${auth.user?.id}`) } catch { return null } }
function effortPreferenceKey(profile: LoopProfile) { return `agent-effort:${auth.user?.id}:${profile.id}:${profile.version}` }
function restoreEffort(profile: LoopProfile | null) {
  if (!profile) { effort.value = null; return }
  let saved: string | null = null
  try { saved = localStorage.getItem(effortPreferenceKey(profile)) } catch { /* 隐私模式下保留内存偏好。 */ }
  const previous = saved || effort.value
  effort.value = previous && profile.allowed_efforts.includes(previous as Effort) ? previous as Effort : profile.default_effort
  if (previous && previous !== effort.value) error.value = '当前协议档不支持原思考档位，已恢复默认值'
}
function setEffort(value: Effort) {
  effort.value = value
  const profile = selectedProfile.value
  if (profile) try { localStorage.setItem(effortPreferenceKey(profile), value) } catch { /* 本地存储不可用不影响发送。 */ }
}
/** 切换只影响下一轮；已经发出的 attempt 永远读取其持久 request_summary。 */
function selectProfile(id: string) {
  const profile = ui.value?.profiles.find(item => item.id === id)
  if (!profile) return
  selectedProfileId.value = profile.id
  try { localStorage.setItem(`agent-profile:${auth.user?.id}`, profile.id) } catch { /* 本地存储不可用不影响发送。 */ }
  restoreEffort(profile)
}
watch(() => props.sessionId, () => { ui.value = null; attachments.value = {}; shown.value = 80; tab.value='chat'; if (props.sessionId) props.store.open(props.sessionId); void refreshUi() }, { immediate: true })
// 轨迹订阅属于当前可见面板；切会话/卸载仅退订诊断，不关闭执行中的控制连接。
watch([tab, () => props.sessionId, () => ui.value?.permissions.trace], ([view, sid, permitted], _, cleanup) => {
  if (!sid || view !== 'trace' || !permitted) return
  const client = props.store.clients.get(sid)
  client?.trace(true, props.store.traces[sid]?.seq ?? -1)
  cleanup(() => client?.trace(false))
})
watch(() => state.value?.cursor, () => { if (atBottom.value) void nextTick(scrollBottom); void hydrateAttachments() })
const refreshTimer = setInterval(() => { if (document.visibilityState === 'visible') void refreshUi() }, 30000)
window.addEventListener('focus', refreshUi)
try {
  const savedWidth = Number(localStorage.getItem(chatWidthStorageKey))
  if (Number.isFinite(savedWidth) && savedWidth >= minimumChatWidth) chatWidth.value = savedWidth
} catch { /* 本地存储不可用时使用默认宽度。 */ }
onBeforeUnmount(() => { epoch++; clearInterval(refreshTimer); window.removeEventListener('focus', refreshUi); finishContentResize() })
function interactions(row: LoopRecord) { return Object.values(state.value?.interactions || {}).filter(i => identity({session_id:props.sessionId,correlation:i.correlation},true) === row.key) }
function fill(text: string) { draft.value.content = text; composer.value?.focus() }
function trackScroll() { const el=scroller.value; if(el) atBottom.value=el.scrollHeight-el.scrollTop-el.clientHeight<100 }
function scrollBottom() { const el=scroller.value; if(el) el.scrollTop=el.scrollHeight; atBottom.value=true }
/** 将固定高度的边缘阴影线定位到鼠标所在的纵向位置。 */
function updateResizeHandleOffset(edge: ResizeEdge, event: PointerEvent) {
  const rect = chatShell.value?.getBoundingClientRect()
  if (!rect) return
  resizeHandleOffsets.value[edge] = Math.min(Math.max(0, event.clientY - rect.top - resizeHandleHeight / 2), Math.max(0, rect.height - resizeHandleHeight))
}
/** 仅当鼠标进入左右边缘命中区时，显示随鼠标纵向移动的细玻璃阴影线。 */
function previewContentResize(edge: ResizeEdge, event: PointerEvent) {
  if (event.pointerType === 'touch' || isResizing.value) return
  hoverResizeEdge.value = edge
  updateResizeHandleOffset(edge, event)
}
function moveContentResizePreview(edge: ResizeEdge, event: PointerEvent) {
  if (event.pointerType === 'touch' || isResizing.value || hoverResizeEdge.value !== edge) return
  updateResizeHandleOffset(edge, event)
}
function hideContentResizePreview(edge: ResizeEdge) {
  if (!isResizing.value && hoverResizeEdge.value === edge) hoverResizeEdge.value = null
}
function resizeHandleStyle(edge: ResizeEdge) { return { top: `${resizeHandleOffsets.value[edge]}px` } }
/** 两侧边缘都可拖拽；外扩和内收只改变宽度，壳层始终保持页面居中。 */
function beginContentResize(event: PointerEvent, edge: ResizeEdge) {
  if (event.pointerType === 'touch' || !chatShell.value) return
  event.preventDefault()
  resizeEdge.value = edge
  hoverResizeEdge.value = edge
  updateResizeHandleOffset(edge, event)
  resizeStartX = event.clientX
  resizeStartWidth = chatShell.value.getBoundingClientRect().width
  chatWidth.value = resizeStartWidth
  isResizing.value = true
  window.addEventListener('pointermove', resizeContent)
  window.addEventListener('pointerup', finishContentResize, { once: true })
}
function resizeContent(event: PointerEvent) {
  const upper = maximumChatWidth.value
  const direction = resizeEdge.value === 'right' ? 1 : -1
  chatWidth.value = Math.min(upper, Math.max(minimumChatWidth, resizeStartWidth + direction * (event.clientX - resizeStartX)))
  if (resizeEdge.value) updateResizeHandleOffset(resizeEdge.value, event)
}
function finishContentResize() {
  if (!isResizing.value) return
  isResizing.value = false
  resizeEdge.value = null
  hoverResizeEdge.value = null
  window.removeEventListener('pointermove', resizeContent)
  try { if (chatWidth.value) localStorage.setItem(chatWidthStorageKey, String(Math.round(chatWidth.value))) } catch { /* 本地存储失败不影响本次调整。 */ }
}
/** 键盘用户可用方向键从当前侧边缘放大或缩小居中的共享壳层。 */
function adjustContentWidthByKey(event: KeyboardEvent, edge: ResizeEdge) {
  if (event.key !== 'ArrowLeft' && event.key !== 'ArrowRight') return
  event.preventDefault()
  const outward = (edge === 'left' && event.key === 'ArrowLeft') || (edge === 'right' && event.key === 'ArrowRight')
  chatWidth.value = Math.min(maximumChatWidth.value, Math.max(minimumChatWidth, renderedChatWidth.value + (outward ? 24 : -24)))
  try { localStorage.setItem(chatWidthStorageKey, String(Math.round(chatWidth.value))) } catch { /* 本地存储失败不影响本次调整。 */ }
}
async function copy(text: string) { try { await navigator.clipboard.writeText(text) } catch { error.value='复制失败' } }
/** 冻结输入/附件/effort 与幂等 ID；未受理时保留可恢复草稿。 */
async function submit() {
  if (!ready.value || busy.value || draft.value.submitting) return
  const source = draft.value, selectedEffort=effort.value, profile=selectedProfile.value
  if (!selectedEffort || !profile) return
  source.submitting = true; error.value = ''
  if (state.value) state.value.error = ''
  const content=source.content, refs=source.files.filter(f=>!f.removed && f.id).map(f=>f.id!)
  try {
    let sid=props.sessionId
    if(!sid) { sid=await props.createSession(); if(!sid) throw new Error(); props.store.drafts[sid]=source; delete props.store.drafts.draft }
    const client=props.store.open(sid)
    source.pending ??= client.command('turn.submit',{client_message_id:createRequestId(),content,attachment_refs:refs,profile_id:profile.id,reasoning_effort:selectedEffort})
    // 只有首次订阅完成后才发送；超时取消等待，不能在以后重连时偷偷补发。
    if (!props.store.sessions[sid].ready) await new Promise<void>((resolve, reject) => {
      const unwatch = watch(() => props.store.sessions[sid]?.ready, ok => {
        if (ok) { clearTimeout(timer); unwatch(); resolve() }
      })
      const timer = setTimeout(() => { unwatch(); reject(new Error('连接超时')) }, 15000)
    })
    if (!client.send(source.pending)) throw new Error('连接中断')
    props.store.sessions[sid].controlled = true
  } catch (exc) {
    source.submitting = false
    error.value = exc instanceof ApiError ? `${exc.message}，草稿已保留`
      : source.pending ? '消息尚未确认发送，请连接恢复后使用原请求 ID 重发，草稿已保留'
      : '无法创建或发送会话，草稿已保留'
  }
}
/** 重试保留原请求及正文，只有实际写入 socket 才显示发送中。 */
function retry() {
  if (draft.value.pending && state.value?.ready && props.store.send(props.sessionId, draft.value.pending)) {
    draft.value.submitting = true; error.value = ''; state.value.error = ''
  }
}
function stop() { if(!canControl.value || !state.value?.activeTurn) return; const client=props.store.clients.get(props.sessionId)!; const command=client.command('turn.cancel',{turn_id:state.value.activeTurn}); if(client.send(command)) { state.value.cancelling=true; draft.value.cancelRequestId=command.request_id } }
function respond(interaction: InteractionRecord, values: Data) {
  if(!canControl.value || !state.value?.ready || interaction.submitting) return
  const c=interaction.correlation
  const data={interaction_id:interaction.interaction_id,turn_id:c.turn_id,turn:c.turn,attempt_id:c.attempt_id,call_id:c.call_id,nonce:interaction.nonce,...values,...(interaction.kind==='task_confirmation'?{spec_hash:interaction.spec_hash}:{})}
  const client=props.store.clients.get(props.sessionId)!, command=client.command(`${interaction.kind}.respond`,data)
  if(client.send(command)){interaction.submitting=true;draft.value.pending=command;draft.value.pendingInteraction=interaction.key}
}
/** 文件元数据只取授权接口，不信任历史里的任意 URL。 */
async function hydrateAttachments() {
  const sid=props.sessionId
  for(const row of rows.value.filter(r=>r.role==='user' && r.attachment_refs?.length)){
    if(attachments.value[row.key])continue
    attachments.value[row.key]=[]
    const values=await Promise.all((row.attachment_refs as any[]).map(async item=>{const id=typeof item==='string'?item:item.file_id;try{const {data}=await http.get(`/api/files/${encodeURIComponent(id)}`);return {file_id:id,filename:data.filename,size:data.size,content_type:data.content_type,content_url:`/api/files/${encodeURIComponent(id)}/content`} as AttachmentReference}catch{return null}}))
    if(sid===props.sessionId)attachments.value[row.key]=values.filter((v):v is AttachmentReference=>v!==null)
  }
}
</script>
<style>
.loop-control{background:transparent;color:inherit;border:1px solid transparent;border-radius:7px;padding:7px 9px;font-size:12px;cursor:pointer}.loop-control:hover{background:#eaf3ee}.loop-primary{background:#174a3a!important;color:#fff!important}.loop-workspace button:focus-visible,.loop-workspace input:focus-visible,.loop-workspace summary:focus-visible{outline:2px solid #16977a;outline-offset:2px}
</style>
<style scoped>
.loop-workspace{display:flex;flex:1;flex-direction:column;min-height:0;min-width:0;background:var(--bg-main,#f8faf8)}.loop-tabs{display:flex;align-items:center;gap:8px;padding:8px 20px;border-bottom:1px solid #e0e8e2}.loop-tabs button{padding:7px 12px;border:0;border-radius:7px;background:transparent;color:#61776a;cursor:pointer}.loop-tabs .active{background:#e2eee6;color:#154834}.loop-status{margin-left:auto;font-size:12px;display:flex;align-items:center;gap:6px}.loop-status i{width:7px;height:7px;border-radius:50%;background:#93a99c}.loop-status .running{background:#21a37e;animation:pulse 1.5s ease-in-out infinite}.loop-content{display:flex;flex:1;min-height:0;position:relative}.loop-center{display:flex;flex-direction:column;flex:1;min-width:0;position:relative;min-height:0}.loop-conversation{overflow:auto;flex:1;padding:24px max(20px,calc((100% - 800px)/2));scrollbar-gutter:stable}.loop-message{margin:0 0 22px;min-width:0;overflow-wrap:anywhere}.loop-message header{display:flex;gap:8px;align-items:center;font-size:13px;font-weight:600;margin-bottom:8px}.loop-message header small{font-weight:400;color:#7b8e82}.loop-message header button{margin-left:auto;border:0;background:transparent;color:#728777;cursor:pointer}.loop-message.user{background:#eaf3ed;padding:16px 20px;border-radius:12px}.loop-message.user p{white-space:pre-wrap;margin:0;line-height:1.7}.history-files{display:flex;gap:8px;flex-wrap:wrap}.loop-welcome{max-width:750px;margin:6vh auto 24px}.loop-welcome>span{letter-spacing:.16em;color:#5c8c75;font-size:11px}.loop-welcome h2{font-size:32px;line-height:1.4;font-weight:600;color:#173f30;margin:16px 0}.loop-welcome p{color:#7d8b82}.loop-welcome>div{display:flex;gap:10px;margin-top:25px}.loop-welcome button{flex:1;text-align:left;border:1px solid #d8e4dc;border-radius:10px;padding:18px;background:#fff;color:#4d6858;line-height:1.7;cursor:pointer}.loop-composer-wrap{padding:12px 24px 18px;max-width:950px;width:100%;box-sizing:border-box;margin:0 auto}.loop-runtime{width:240px;overflow:auto;padding:18px;border-left:1px solid #e0e8e2;font-size:12px;background:#f5f8f5}.loop-runtime dd{margin:5px 0 14px;overflow-wrap:anywhere}.loop-runtime dt{color:#7d9081}.runtime-close{float:right;border:0;background:transparent;cursor:pointer}.loop-notice{padding:8px 16px;margin:4px 10px;background:#f6f0e2;color:#866934;font-size:12px}.loop-notice.error{color:#a24d43}.loop-notice button,.history-more{border:0;background:transparent;text-decoration:underline;cursor:pointer}.jump-bottom{position:absolute;bottom:10px;right:20px;border:1px solid #caddcf;background:#fff;border-radius:20px;padding:8px 15px;cursor:pointer}.muted{color:#86968b}@keyframes pulse{50%{opacity:.35}}@media(prefers-reduced-motion:reduce){*{animation:none!important;transition:none!important}}@media(max-width:768px){.loop-runtime{position:absolute;inset:0 0 0 auto;max-width:calc(100% - 35px);z-index:30;box-shadow:-20px 0 50px #173e2520}.loop-composer-wrap{padding:8px}.loop-conversation{padding:16px 12px}.loop-welcome h2{font-size:25px}.loop-welcome>div{flex-direction:column}.loop-welcome button{padding:12px}.loop-tabs{padding:6px;gap:0}.loop-tabs button{padding:7px}.loop-status{font-size:11px}.loop-message header{flex-wrap:wrap}}

/* 对话/轨迹导航采用参考页的下划线选中态。 */
.loop-tabs{--line:#e3e8f0;--text:#172033;--subtle:#748197;--accent:#5b5bd6}
    .loop-tabs { display: flex; min-height: 42px; align-items: end; gap: 22px; border-bottom: 1px solid var(--line); padding: 0 28px; background: rgba(255,255,255,.68); }
    .loop-tabs .workspace-tab { position: relative; min-height: 42px; border: 0; background: transparent; padding: 0 1px; color: var(--subtle); font-size: 12px; cursor: pointer; }
    .loop-tabs .workspace-tab::after { position: absolute; right: 0; bottom: -1px; left: 0; height: 2px; content: ""; border-radius: 2px 2px 0 0; background: transparent; }
    .loop-tabs .workspace-tab:hover { color: var(--text); }
    .loop-tabs .workspace-tab.active { color: var(--accent); font-weight: 650; }
    .loop-tabs .workspace-tab.active::after { background: var(--accent); }
    .trace-tab-count { display: inline-grid; min-width: 16px; height: 16px; place-items: center; border-radius: 999px; background: #eef0ff; padding: 0 4px; color: #4d4ebb; font-size: 9px; vertical-align: 1px; }
    .loop-tabs .workspace-tab-hint { margin: 0 0 12px auto; color: #8994a6; font: 10px ui-monospace,SFMono-Regular,Consolas,monospace; letter-spacing: .04em; }


.loop-tabs .workspace-tab{background:transparent}.loop-tabs .workspace-tab:disabled{opacity:.45;cursor:default}

/* 消息区与输入框共用同一宽度壳层，并始终在页面内容区居中。 */
.loop-chat-shell{position:relative;display:flex;flex:1;flex-direction:column;min-height:0;width:min(900px,calc(100% - 48px));max-width:calc(100% - 48px);min-width:520px;margin:0 auto}
.loop-chat-shell .loop-conversation{padding:24px 16px}
.loop-chat-shell .loop-composer-wrap{flex:0 0 auto;width:100%;max-width:none;margin:0;padding:12px 0 18px;box-sizing:border-box}

/* 两侧保留窄命中区；只有进入边缘时才显示跟随鼠标移动的细玻璃阴影线。 */
.loop-width-edge{position:absolute;z-index:3;top:0;bottom:0;width:28px;cursor:ew-resize}.loop-width-edge-left{left:-14px}.loop-width-edge-right{right:-14px}
.loop-width-handle{position:absolute;left:0;width:28px;height:96px;border:0;border-radius:14px;background:transparent;cursor:ew-resize;opacity:0;touch-action:none;transition:opacity .14s ease,background-color .14s ease}
.loop-width-handle span{display:block;width:2px;height:76px;margin:auto;border-radius:2px;background:rgba(105,128,122,.3);box-shadow:0 0 10px rgba(119,147,138,.24)}
.loop-width-handle.is-visible,.loop-width-handle.is-active,.loop-width-handle:focus-visible{opacity:1;background:rgba(255,255,255,.08);backdrop-filter:blur(12px);-webkit-backdrop-filter:blur(12px);outline:0}.loop-width-handle:hover{background:rgba(255,255,255,.2)}.loop-width-handle:hover span,.loop-width-handle:focus-visible span{background:rgba(91,129,117,.54)}
/* 全会话指标统计栏 */
.conversation-metrics-bar {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 20px;
  padding: 8px 4px 0;
  color: #748197;
  font-size: 11px;
  line-height: 1.4;
  user-select: none;
}
.metric-item {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  white-space: nowrap;
}
.metric-icon {
  display: inline-block;
  flex-shrink: 0;
  vertical-align: middle;
  color: #748197;
}
.loop-trace-composer .conversation-metrics-bar {
  padding-bottom: 8px;
}

@media(max-width:768px){.loop-chat-shell{width:100%!important;max-width:none;min-width:0;margin:0}.loop-chat-shell .loop-composer-wrap{padding:8px}.loop-width-edge{display:none}.loop-chat-shell .loop-conversation{padding:16px 12px}.conversation-metrics-bar{gap:12px;font-size:10px;flex-wrap:wrap}}
</style>
