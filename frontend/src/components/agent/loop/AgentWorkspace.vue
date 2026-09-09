<template>
  <div class="loop-workspace">
    <div class="loop-tabs"><button class="workspace-tab" :class="{active:tab==='chat'}" @click="tab='chat'">对话</button><button class="workspace-tab" :class="{active:tab==='trace'}" :disabled="!state" @click="tab='trace'">轨迹 <small v-if="state?.cursor" class="trace-tab-count">{{ state.cursor }}</small></button><span class="loop-status"><i :class="{running:busy}"/>{{ status }}</span><button @click="runtimeOpen=!runtimeOpen">运行信息</button></div>
    <p v-if="state && state.connection !== 'online'" class="loop-notice" role="status">{{ state.connection === 'connecting' ? '正在同步会话…' : '连接中断，状态待同步。' }}<button @click="store.clients.get(sessionId)?.connect()">重新连接</button></p>
    <p v-if="state?.error || error" class="loop-notice error" role="alert">{{ state?.error || error }}</p>
    <div class="loop-content">
      <div class="loop-center">
        <section v-if="tab==='chat'" ref="chatShell" class="loop-chat-shell" :class="{ 'is-resizing': isResizing, 'is-empty': !rows.length }" :style="chatShellStyle" aria-label="对话内容区域">
          <!-- 空状态：输入框上方水平居中展示 Logo + 名字及产品标语 -->
          <div v-if="!rows.length" class="loop-empty-hero">
            <div class="hero-brand">
              <div class="hero-logo-mark" aria-hidden="true">
                <svg width="22" height="22" viewBox="0 0 24 24" fill="none">
                  <path d="M12 3L4 20H8.5L10.2 15.5H13.8L15.5 20H20L12 3ZM11.1 11.8L12 7.2L12.9 11.8H11.1Z" fill="#ffffff" />
                </svg>
              </div>
              <div class="hero-brand-name-wrap">
                <span class="hero-brand-name">AI Eval</span>
                <span class="hero-brand-badge">AGENT LOOP</span>
              </div>
            </div>
            <h1 class="hero-tagline">从一个目标开始，让每一步都有依据。</h1>
            <p class="hero-subline">在工作区处理文件、查找资料，或创建评测任务。</p>
          </div>

          <!-- 对话消息滚动区：有消息时正常滚动展示；空状态隐藏以保持居中 -->
          <div ref="scroller" class="loop-conversation" :class="{ 'is-empty': !rows.length }" @scroll="trackScroll">
          <button v-if="shown < rows.length" class="history-more" @click="shown+=80">显示更早的 {{ Math.min(80, rows.length-shown) }} 条记录</button>
          <template v-for="row in visibleRows" :key="row.key">
            <article v-if="row.role==='user'" class="loop-message user"><header>你</header><div class="history-files"><AttachmentPreview v-for="file in attachments[row.key] || []" :key="file.file_id" :attachment="file"/></div><p>{{ row.content }}</p></article>
            <ToolRunCard v-else-if="'status' in row && 'name' in row" :tool="row as ToolRun" :interactions="interactions(row)" :can-control="canControl" :online="!!state?.ready" @respond="respond"/>
            <article v-else class="loop-message assistant">
              <header class="assistant-header">
                <div class="assistant-identity">
                  <ProviderLogo v-if="row.request_summary?.model" :provider="getProviderLogoKey({model:row.request_summary.model})" :size="18"/>
                  <strong>{{ row.request_summary?.model || '助手' }}</strong>
                  <time v-if="formatTimestamp(row.timestamp)" :datetime="row.timestamp">{{ formatTimestamp(row.timestamp) }}</time>
                  <small v-if="row.request_summary">{{ row.request_summary.reasoning_effort }} · step {{ row.correlation.step }}</small>
                </div>
                <div v-if="row.text" class="assistant-actions" aria-label="回答操作">
                  <button class="assistant-action" type="button" title="复制回答" aria-label="复制回答" @click="copy(row.text)"><n-icon :component="FileIcon" :size="15"/></button>
                  <button class="assistant-action" type="button" title="重新生成" aria-label="重新生成" :disabled="busy || draft.submitting || !!draft.pending" @click="regenerate(row)"><n-icon :component="RetryIcon" :size="15"/></button>
                  <button class="assistant-action" type="button" title="引用为参考记忆" aria-label="引用为参考记忆" @click="quoteMemory(row.text)"><n-icon :component="BackwardIcon" :size="15"/></button>
                </div>
              </header>
              <ReasoningBlock v-if="row.reasoning && ui?.permissions.reasoning" :content="row.reasoning" :ended="row.ended" :interrupted="row.interrupted"/>
              <MarkdownView v-if="row.text" :content="row.text"/>
              <p v-else-if="!row.ended" class="muted">正在响应…</p>
              <footer v-if="row.ended" class="assistant-metrics" aria-label="本次模型生成指标">
                <span><n-icon :component="FileIcon" :size="14"/>{{ formatTokens(answerTokens(row)) }} token</span>
                <span><n-icon :component="TimeIcon" :size="14"/>{{ formatDuration(row.latency_ms) }}</span>
              </footer>
              <small v-if="row.interrupted || row.error_code">{{ row.interrupted ? '本次输出已中断' : row.error_code }}</small>
            </article>
          </template>
          <p v-if="!busy && state?.phase && ['max_tokens','max_steps','cancelled','interrupted','error'].includes(state.phase)" class="loop-notice">{{ finishLabels[state.phase] }}</p>
          </div>
          <div class="loop-composer-wrap"><AgentComposer ref="composer" :draft="draft" :ui="ui" :profile="selectedProfile" :profiles="ui?.profiles || []" :effort="effort" :meter="summary?.context_meter" :metrics="conversationMetrics" :busy="busy" :cancelling="!!state?.cancelling" :can-stop="canControl && !!state?.ready && !state?.cancelling" :ready="ready" @effort="setEffort" @submit="submit" @stop="stop" @retry="retry" @model="selectProfile"/></div>
          <!-- 空状态时的提示词卡片（位于输入框下方，点击填充草稿） -->
          <div v-if="!rows.length" class="loop-empty-prompts">
            <button
              v-for="prompt in prompts"
              :key="prompt"
              class="empty-prompt-card"
              type="button"
              @click="fill(prompt)"
            >
              <span class="prompt-text">{{ prompt }}</span>
              <span class="prompt-arrow">↗</span>
            </button>
          </div>
          <div class="loop-width-edge loop-width-edge-left" @pointerenter="previewContentResize('left', $event)" @pointermove="moveContentResizePreview('left', $event)" @pointerleave="hideContentResizePreview('left')">
            <button class="loop-width-handle" :class="{ 'is-visible': hoverResizeEdge === 'left' || (isResizing && resizeEdge === 'left'), 'is-active': isResizing && resizeEdge === 'left' }" :style="resizeHandleStyle('left')" type="button" aria-label="向左拖拽调整对话内容宽度" aria-orientation="vertical" role="separator" :aria-valuemin="minimumChatWidth" :aria-valuemax="maximumChatWidth" :aria-valuenow="Math.round(renderedChatWidth)" @pointerdown="beginContentResize($event, 'left')" @keydown="adjustContentWidthByKey($event, 'left')">
              <span aria-hidden="true"></span>
            </button>
          </div>
          <div class="loop-width-edge loop-width-edge-right" @pointerenter="previewContentResize('right', $event)" @pointermove="moveContentResizePreview('right', $event)" @pointerleave="hideContentResizePreview('right')">
            <button class="loop-width-handle" :class="{ 'is-visible': hoverResizeEdge === 'right' || (isResizing && resizeEdge === 'right'), 'is-active': isResizing && resizeEdge === 'right' }" :style="resizeHandleStyle('right')" type="button" aria-label="向右拖拽调整对话内容宽度" aria-orientation="vertical" role="separator" :aria-valuemin="minimumChatWidth" :aria-valuemax="maximumChatWidth" :aria-valuenow="Math.round(renderedChatWidth)" @pointerdown="beginContentResize($event, 'right')" @keydown="adjustContentWidthByKey($event, 'right')">
              <span aria-hidden="true"></span>
            </button>
          </div>
        </section>
        <TraceWorkspace v-else-if="state && trace" :state="state" :trace="trace"/>
        <button v-if="!atBottom && tab==='chat'" class="jump-bottom" @click="scrollBottom">↓ 回到最新</button>
      </div>
      <aside v-if="runtimeOpen" class="loop-runtime"><button class="runtime-close" @click="runtimeOpen=false">关闭</button><h3>当前运行</h3><p>{{ status }}</p><dl><dt>会话</dt><dd>{{ sessionId || '未发送的草稿' }}</dd><dt>实际模型</dt><dd>{{ summary?.model || '尚无实际请求' }}</dd><dt>思考档位</dt><dd>{{ summary?.reasoning_effort || '未知' }}</dd><dt>协议档版本</dt><dd>{{ summary?.profile_version || '未知' }}</dd><dt>最近活动</dt><dd v-for="event in state?.facts.slice(-5) || []" :key="event.cursor">{{ event.type }}</dd></dl><h4 v-if="tasks.length">Worker 任务</h4><div v-for="task in tasks" :key="task.key"><router-link :to="'/tasks'">{{ task.key }}</router-link><p>{{ task.status || '等待状态' }}</p><p v-if="task.progress">{{ JSON.stringify(task.progress) }}</p><router-link v-if="task.report_id" :to="`/reports/${task.report_id}`">查看报告</router-link></div><p v-for="execution in quarantined" :key="execution.key" class="loop-notice">执行范围受限 · {{ execution.reason || '等待对账' }}</p></aside>
    </div>
    <div v-if="tab==='trace'" class="loop-composer-wrap loop-trace-composer"><AgentComposer ref="composer" :draft="draft" :ui="ui" :profile="selectedProfile" :profiles="ui?.profiles || []" :effort="effort" :meter="summary?.context_meter" :metrics="conversationMetrics" :busy="busy" :cancelling="!!state?.cancelling" :can-stop="canControl && !!state?.ready && !state?.cancelling" :ready="ready" @effort="setEffort" @submit="submit" @stop="stop" @retry="retry" @model="selectProfile"/></div>
  </div>
</template>
<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, ref, watch } from 'vue'
import { NIcon } from 'naive-ui'
import BackwardIcon from 'naive-ui/es/_internal/icons/Backward'
import FileIcon from 'naive-ui/es/_internal/icons/File'
import RetryIcon from 'naive-ui/es/_internal/icons/Retry'
import TimeIcon from 'naive-ui/es/_internal/icons/Time'
import http, { ApiError } from '../../../api/http'
import { createRequestId } from '../../../utils/requestId'
import type { AttachmentReference } from '../../../api/types'
import type { ConversationMetrics, Data, Effort, InteractionRecord, LoopProfile, LoopRecord, LoopUi, LoopUsage, ToolRun } from '../../../api/agentLoopTypes'
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
const rows = computed(() => state.value ? conversationRows(state.value) : [])
const visibleRows = computed(() => rows.value.slice(-shown.value))
const busy = computed(() => !!state.value?.activeTurn)
/** 草稿协议档可独立于平台默认项选择；后端在提交时再次校验。 */
const selectedProfile = computed<LoopProfile | null>(() => ui.value?.profiles.find(item => item.id === selectedProfileId.value) || ui.value?.profile || null)
const ready = computed(() => !!selectedProfile.value && !!effort.value && (props.sessionId ? !!state.value?.ready : !!ui.value?.enabled))
const canControl = computed(() => !!state.value?.controlled && !!ui.value?.permissions.interactions)
const summary = computed(() => Object.values(state.value?.attempts || {}).sort((a,b)=>b.first_cursor-a.first_cursor)[0]?.request_summary)
/** 仅聚合已提交的上游 usage；缺字段代表上游未返回，不能当作零或自行估算。 */
const conversationMetrics = computed<ConversationMetrics>(() => {
  let inputTokens = 0, outputTokens = 0, modelLatencyMs = 0, cacheReadTokens = 0, hasCacheUsage = false
  for (const attempt of Object.values(state.value?.attempts || {})) {
    const usage = attempt.usage
    if (!usage) continue
    const input = tokenValue(usage.prompt_tokens), output = tokenValue(usage.completion_tokens)
    inputTokens += input; outputTokens += output
    if (input > 0 && output > 0 && tokenValue(attempt.latency_ms) > 0) modelLatencyMs += tokenValue(attempt.latency_ms)
    const cached = tokenValue(usage.cache_read_input_tokens) || tokenValue(usage.cached_tokens)
    if (cached > 0 || typeof usage.cache_read_input_tokens === 'number' || typeof usage.cached_tokens === 'number') {
      hasCacheUsage = true; cacheReadTokens += cached
    }
  }
  return {
    inputTokens,
    outputTokens,
    outputTokensPerSecond: outputTokens > 0 && modelLatencyMs > 0 ? outputTokens / (modelLatencyMs / 1000) : null,
    cacheHitRate: hasCacheUsage && inputTokens > 0 ? cacheReadTokens / inputTokens * 100 : null,
  }
})
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
const resizeHandleHeight = 100
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
function tokenValue(value: unknown): number { return typeof value === 'number' && Number.isFinite(value) && value >= 0 ? value : 0 }
function answerTokens(row: LoopRecord): number | null {
  const usage = row.usage as LoopUsage | undefined
  if (!usage) return null
  const total = tokenValue(usage.total_tokens)
  return total > 0 ? total : tokenValue(usage.prompt_tokens) + tokenValue(usage.completion_tokens)
}
function formatTokens(value: number | null | undefined): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return '—'
  if (value >= 1_000_000) return `${(value / 1_000_000).toFixed(value >= 10_000_000 ? 0 : 1)}M`
  if (value >= 1_000) return `${(value / 1_000).toFixed(value >= 10_000 ? 0 : 1)}K`
  return String(Math.round(value))
}
function formatDuration(value: unknown): string {
  const milliseconds = tokenValue(value)
  if (typeof value !== 'number' || !Number.isFinite(value)) return '—'
  return milliseconds < 1000 ? `${milliseconds} ms` : `${(milliseconds / 1000).toFixed(milliseconds >= 10_000 ? 0 : 1)} s`
}
function formatTimestamp(value?: string): string {
  if (!value) return ''
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return ''
  return new Intl.DateTimeFormat('zh-CN', { year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false }).format(date)
}
/** 引用只写入下一轮草稿，供模型参考；不会伪造为服务端持久记忆。 */
function quoteMemory(text: string) {
  const quote = `[引用对话记忆]\n${text}\n[/引用对话记忆]`
  draft.value.content = draft.value.content.trim() ? `${draft.value.content}\n\n${quote}` : quote
  composer.value?.focus()
}
function originalUserMessage(row: LoopRecord): LoopRecord | undefined {
  return rows.value.filter(item => item.role === 'user').reverse().find(item =>
    (row.correlation.turn_id && item.correlation.turn_id === row.correlation.turn_id)
    || (row.correlation.turn !== undefined && item.correlation.turn === row.correlation.turn),
  )
}
/** 重新生成复用该回答所属的原用户内容与附件引用，仍走新的幂等提交命令。 */
function regenerate(row: LoopRecord) {
  const source = originalUserMessage(row)
  if (!source?.content) { error.value = '未找到可重新生成的原始对话'; return }
  const refs = Array.isArray(source.attachment_refs) ? source.attachment_refs.map(item => typeof item === 'string' ? item : item?.file_id).filter((item): item is string => typeof item === 'string') : []
  void submit({ content: String(source.content), attachmentRefs: refs })
}
/** 冻结输入/附件/effort 与幂等 ID；未受理时保留可恢复草稿。 */
async function submit(override?: { content: string; attachmentRefs: string[] }) {
  if (!ready.value || busy.value || draft.value.submitting) return
  const source = draft.value, selectedEffort=effort.value, profile=selectedProfile.value
  if (!selectedEffort || !profile) return
  source.submitting = true; error.value = ''
  if (state.value) state.value.error = ''
  const content=override?.content ?? source.content, refs=override?.attachmentRefs ?? source.files.filter(f=>!f.removed && f.id).map(f=>f.id!)
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
.loop-workspace{display:flex;flex:1;flex-direction:column;min-height:0;min-width:0;background:var(--bg-main,#f8faf8)}.loop-tabs{display:flex;align-items:center;gap:8px;padding:8px 20px;border-bottom:1px solid #e0e8e2}.loop-tabs button{padding:7px 12px;border:0;border-radius:7px;background:transparent;color:#61776a;cursor:pointer}.loop-tabs .active{background:#e2eee6;color:#154834}.loop-status{margin-left:auto;font-size:12px;display:flex;align-items:center;gap:6px}.loop-status i{width:7px;height:7px;border-radius:50%;background:#93a99c}.loop-status .running{background:#21a37e;animation:pulse 1.5s ease-in-out infinite}.loop-content{display:flex;flex:1;min-height:0;position:relative}.loop-center{display:flex;flex-direction:column;flex:1;min-width:0;position:relative;min-height:0}.loop-conversation{overflow:auto;flex:1;padding:24px max(20px,calc((100% - 800px)/2));scrollbar-gutter:stable}.loop-message{margin:0 0 22px;min-width:0;overflow-wrap:anywhere}.loop-message header{display:flex;gap:8px;align-items:center;font-size:13px;font-weight:600;margin-bottom:8px}.loop-message header small{font-weight:400;color:#7b8e82}.assistant-header{justify-content:space-between}.assistant-identity,.assistant-actions,.assistant-metrics{display:flex;min-width:0;align-items:center;gap:8px}.assistant-identity{flex-wrap:wrap}.assistant-identity strong{font-weight:650}.assistant-identity time{color:#8390a0;font-size:11px;font-weight:400;font-variant-numeric:tabular-nums}.assistant-actions{margin-left:auto;gap:2px}.assistant-action{display:inline-grid;width:28px;height:28px;place-items:center;border:0;border-radius:7px;background:transparent;color:#758497;padding:0;cursor:pointer}.assistant-action:hover:not(:disabled){background:#eff5f1;color:#2d6851}.assistant-action:disabled{cursor:default;opacity:.45}.assistant-metrics{margin-top:10px;color:#7a8797;font-size:11px;font-variant-numeric:tabular-nums}.assistant-metrics span{display:inline-flex;align-items:center;gap:4px}.loop-message.user{background:#eaf3ed;padding:16px 20px;border-radius:12px}.loop-message.user p{white-space:pre-wrap;margin:0;line-height:1.7}.history-files{display:flex;gap:8px;flex-wrap:wrap}.loop-composer-wrap{padding:12px 24px 18px;max-width:950px;width:100%;box-sizing:border-box;margin:0 auto}.loop-runtime{width:240px;overflow:auto;padding:18px;border-left:1px solid #e0e8e2;font-size:12px;background:#f5f8f5}.loop-runtime dd{margin:5px 0 14px;overflow-wrap:anywhere}.loop-runtime dt{color:#7d9081}.runtime-close{float:right;border:0;background:transparent;cursor:pointer}.loop-notice{padding:8px 16px;margin:4px 10px;background:#f6f0e2;color:#866934;font-size:12px}.loop-notice.error{color:#a24d43}.loop-notice button,.history-more{border:0;background:transparent;text-decoration:underline;cursor:pointer}.jump-bottom{position:absolute;bottom:10px;right:20px;border:1px solid #caddcf;background:#fff;border-radius:20px;padding:8px 15px;cursor:pointer}.muted{color:#86968b}@keyframes pulse{50%{opacity:.35}}@media(prefers-reduced-motion:reduce){*{animation:none!important;transition:none!important}}@media(max-width:768px){.loop-runtime{position:absolute;inset:0 0 0 auto;max-width:calc(100% - 35px);z-index:30;box-shadow:-20px 0 50px #173e2520}.loop-composer-wrap{padding:8px}.loop-conversation{padding:16px 12px}.loop-tabs{padding:6px;gap:0}.loop-tabs button{padding:7px}.loop-status{font-size:11px}.loop-message header{flex-wrap:wrap}}

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

/* 空状态：居中布局、输入框上方水平居中 Logo + 名字及提示词卡片 */
.loop-chat-shell.is-empty {
  justify-content: center;
  padding: 32px 0 48px;
  overflow-y: auto;
}
.loop-chat-shell.is-empty .loop-conversation.is-empty {
  display: none;
}
.loop-empty-hero {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  text-align: center;
  width: 100%;
  margin-bottom: 24px;
  padding: 0 12px;
}
.hero-brand {
  display: inline-flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 12px;
}
.hero-logo-mark {
  width: 44px;
  height: 44px;
  border-radius: 12px;
  background: linear-gradient(135deg, #1f5947 0%, #154234 100%);
  display: grid;
  place-items: center;
  box-shadow: 0 4px 14px rgba(23, 74, 58, 0.22);
}
.hero-brand-name-wrap {
  display: flex;
  align-items: center;
  gap: 8px;
}
.hero-brand-name {
  font-family: var(--font-display, inherit);
  font-size: 26px;
  font-weight: 750;
  color: #173f30;
  letter-spacing: -0.02em;
}
.hero-brand-badge {
  font-size: 10px;
  font-weight: 700;
  padding: 3px 8px;
  border-radius: 6px;
  background: #e2eee6;
  color: #154834;
  letter-spacing: 0.1em;
}
.hero-tagline {
  font-size: 22px;
  font-weight: 600;
  color: #173f30;
  margin: 0 0 6px;
  line-height: 1.4;
}
.hero-subline {
  font-size: 13.5px;
  color: #697d72;
  margin: 0;
}
.loop-empty-prompts {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 12px;
  width: 100%;
  margin-top: 14px;
  box-sizing: border-box;
}
.empty-prompt-card {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 14px 16px;
  border: 1px solid #d8e4dc;
  border-radius: 12px;
  background: #ffffff;
  color: #41594d;
  font-size: 13px;
  line-height: 1.5;
  text-align: left;
  cursor: pointer;
  box-shadow: 0 1px 3px rgba(15, 23, 42, 0.03);
  transition: all 0.18s ease;
}
.empty-prompt-card:hover {
  border-color: #1f5947;
  background: #f8faf9;
  color: #173f30;
  transform: translateY(-1px);
  box-shadow: 0 4px 14px rgba(23, 74, 58, 0.08);
}
.prompt-arrow {
  color: #8da496;
  font-size: 14px;
  margin-left: 8px;
  flex-shrink: 0;
  transition: transform 0.18s ease, color 0.18s ease;
}
.empty-prompt-card:hover .prompt-arrow {
  color: #1f5947;
  transform: translate(2px, -2px);
}

/* 深色模式适配 */
[data-theme='dark'] .hero-logo-mark {
  background: linear-gradient(135deg, #16977a 0%, #0f5e4c 100%);
  box-shadow: 0 4px 16px rgba(0, 0, 0, 0.4);
}
[data-theme='dark'] .hero-brand-name {
  color: #f3f4f6;
}
[data-theme='dark'] .hero-brand-badge {
  background: rgba(22, 151, 122, 0.2);
  color: #34d399;
}
[data-theme='dark'] .hero-tagline {
  color: #f9fafb;
}
[data-theme='dark'] .hero-subline {
  color: #9ca3af;
}
[data-theme='dark'] .empty-prompt-card {
  background: #111827;
  border-color: rgba(255, 255, 255, 0.1);
  color: #d1d5db;
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.25);
}
[data-theme='dark'] .empty-prompt-card:hover {
  border-color: #16977a;
  background: #1f2937;
  color: #ffffff;
  box-shadow: 0 4px 16px rgba(0, 0, 0, 0.4);
}
[data-theme='dark'] .empty-prompt-card:hover .prompt-arrow {
  color: #34d399;
}
@media(max-width: 768px) {
  .loop-empty-prompts {
    grid-template-columns: 1fr;
  }
}

/* 拖拽式隐藏边框：命中区与图2高品质羽化渐变悬浮手柄 */
.loop-chat-shell.is-resizing {
  user-select: none;
  cursor: col-resize;
}
.loop-chat-shell.is-resizing * {
  user-select: none !important;
}
.loop-width-edge {
  position: absolute;
  z-index: 30;
  top: 0;
  bottom: 0;
  width: 28px;
  cursor: col-resize;
}
.loop-width-edge-left {
  left: -14px;
}
.loop-width-edge-right {
  right: -14px;
}
.loop-width-handle {
  position: absolute;
  left: 0;
  width: 28px;
  height: 100px;
  border: 0;
  border-radius: 0;
  background: transparent;
  cursor: col-resize;
  opacity: 0;
  touch-action: none;
  padding: 0;
  margin: 0;
  outline: none;
  transition: opacity 0.2s cubic-bezier(0.16, 1, 0.3, 1);
  /* 默认浅色主题变量：对齐图2像素级平滑渐变消隐 (212/255 ≈ 0.17 核心实度) */
  --resizer-rgb: 15, 23, 42;
  --resizer-alpha-core: 0.17;
  --resizer-alpha-mid: 0.12;
  --resizer-alpha-soft: 0.06;
  --resizer-alpha-tip: 0.02;
  --resizer-scale-x: 1;
}
.loop-width-handle.is-visible,
.loop-width-handle.is-active,
.loop-width-handle:focus-visible {
  opacity: 1;
  background: transparent;
  backdrop-filter: none;
  -webkit-backdrop-filter: none;
}
.loop-width-handle:hover {
  background: transparent;
  --resizer-alpha-core: 0.32;
  --resizer-alpha-mid: 0.22;
  --resizer-alpha-soft: 0.10;
  --resizer-alpha-tip: 0.03;
  --resizer-scale-x: 1.25;
}
.loop-width-handle.is-active {
  background: transparent;
  --resizer-alpha-core: 0.48;
  --resizer-alpha-mid: 0.34;
  --resizer-alpha-soft: 0.16;
  --resizer-alpha-tip: 0.05;
  --resizer-scale-x: 1.35;
}
/* 深色主题适配 */
[data-theme='dark'] .loop-width-handle {
  --resizer-rgb: 255, 255, 255;
  --resizer-alpha-core: 0.22;
  --resizer-alpha-mid: 0.15;
  --resizer-alpha-soft: 0.07;
  --resizer-alpha-tip: 0.02;
}
[data-theme='dark'] .loop-width-handle:hover {
  --resizer-alpha-core: 0.38;
  --resizer-alpha-mid: 0.26;
  --resizer-alpha-soft: 0.12;
  --resizer-alpha-tip: 0.04;
}
[data-theme='dark'] .loop-width-handle.is-active {
  --resizer-alpha-core: 0.54;
  --resizer-alpha-mid: 0.38;
  --resizer-alpha-soft: 0.18;
  --resizer-alpha-tip: 0.06;
}
.loop-width-handle span {
  display: block;
  width: 2px;
  height: 100%;
  margin: auto;
  border-radius: 999px;
  background: linear-gradient(
    to bottom,
    rgba(var(--resizer-rgb), 0) 0%,
    rgba(var(--resizer-rgb), var(--resizer-alpha-tip)) 10%,
    rgba(var(--resizer-rgb), var(--resizer-alpha-soft)) 20%,
    rgba(var(--resizer-rgb), var(--resizer-alpha-mid)) 30%,
    rgba(var(--resizer-rgb), var(--resizer-alpha-core)) 38%,
    rgba(var(--resizer-rgb), var(--resizer-alpha-core)) 62%,
    rgba(var(--resizer-rgb), var(--resizer-alpha-mid)) 70%,
    rgba(var(--resizer-rgb), var(--resizer-alpha-soft)) 80%,
    rgba(var(--resizer-rgb), var(--resizer-alpha-tip)) 90%,
    rgba(var(--resizer-rgb), 0) 100%
  );
  box-shadow: none;
  transform: scaleX(var(--resizer-scale-x));
  transform-origin: center center;
  transition: transform 0.15s ease, background 0.15s ease;
  pointer-events: none;
}
@media(max-width:768px){.loop-chat-shell{width:100%!important;max-width:none;min-width:0;margin:0}.loop-chat-shell .loop-composer-wrap{padding:8px}.loop-width-edge{display:none}.loop-chat-shell .loop-conversation{padding:16px 12px}}
</style>
