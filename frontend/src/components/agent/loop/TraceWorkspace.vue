<template>
  <div class="trace-workspace trace-view">
    <div class="trace-toolbar">
      <nav class="trace-filters trace-filter-group" aria-label="事件分类"><button v-for="(name, key) in categories" :key="key" class="trace-filter" :aria-pressed="filter === key" :class="{ active: filter === key }" @click="filter = key">{{ name }}</button></nav>
      <label class="trace-search"><input v-model="search" placeholder="搜索类型、字段或内容" aria-label="搜索轨迹"/></label>
    </div>
    <p v-if="trace.denied">没有轨迹权限；普通对话与工具结果仍可使用。</p>
    <div class="trace-waterfall-panel">
      <div class="trace-lanes trace-lane-labels" aria-hidden="true"><span>输入</span><span>模型</span><span>工具</span></div>
      <div class="trace-axis trace-waterfall" @pointerdown="start" @pointermove="move" @pointerup="finish" @pointercancel="dragging = false" @dblclick="clear" @contextmenu.prevent="clear" @keydown.esc="clear" tabindex="0" aria-label="事件顺序轴，点击选择；Shift 加方向键扩选；Escape 清除" @keydown="keyRange">
        <span v-if="range" class="trace-range trace-selection-range" :style="rangeStyle"/>
        <button v-for="(row, index) in rows" :key="row.cursor" class="trace-segment" :data-index="index" :data-kind="timelineKind(row)" :data-state="status(row)" :class="{ selected: selected === row.cursor, 'out-of-range': range && !inRange(index) }" :style="segmentStyle(row, index)" :title="`#${displaySeq(row)} ${title(row)}`" :aria-label="`定位 #${displaySeq(row)} ${title(row)}`" tabindex="-1"/>
      </div>
    </div>
    <div class="trace-split trace-main" :class="{ 'has-selection': current }">
      <div class="trace-list trace-list-panel">
        <p v-if="!rows.length" class="trace-empty">{{ state.facts.length ? '没有匹配的轨迹，请调整分类或搜索内容。' : '发送一条消息后，在这里查看模型请求、工具执行和事件详情。' }}</p>
        <button v-for="(row, index) in pageRows" :key="row.cursor" class="trace-row" :class="{selected:selected === row.cursor, 'timeline-inside': range && inRange(page * 80 + index), 'timeline-outside': range && !inRange(page * 80 + index)}" @click="select(page * 80 + index)">
          <span class="trace-seq trace-row-seq">#{{ displaySeq(row) }}</span><span class="trace-row-main"><span class="trace-row-title"><span class="trace-badge" :data-category="category(row.type)" :data-role="role(row).key">{{ role(row).label }}</span><b>{{ title(row) }}</b></span><span class="trace-preview trace-row-preview">{{ preview(row) }}</span></span>
        </button>
        <div v-if="rows.length > 80" class="trace-pagination"><button :disabled="page === 0" @click="page--">上一页</button><span>{{ page + 1 }} / {{ Math.max(1, Math.ceil(rows.length / 80)) }}</span><button :disabled="(page + 1) * 80 >= rows.length" @click="page++">下一页</button></div>
      </div>
      <section v-if="current" class="trace-inspector trace-detail">
        <div class="inspector-head trace-detail-head"><div><small class="trace-detail-eyebrow">{{ kind(current).toUpperCase() }} RECORD · {{ current.durability === 'persistent' ? 'DURABLE' : 'LIVE' }}</small><b class="trace-detail-title">{{ title(current) }}</b></div><div class="trace-detail-actions"><button class="trace-copy-button" @click="copy">{{ copyLabel }}</button><span class="trace-detail-state">{{ status(current) }}</span></div></div>
        <nav class="trace-detail-tabs" aria-label="事件详情"><button v-for="item in tabs" :key="item.key" class="trace-detail-tab" :class="{active:tab===item.key}" :aria-pressed="tab===item.key" @click="tab=item.key">{{ item.label }}</button></nav>
        <div class="inspector-body trace-detail-body">
        <template v-if="tab === 'overview'">
          <p class="trace-purpose">{{ purpose(current) }}</p>
          <div class="trace-overview-label">业务记录概览</div>
          <dl class="trace-kv"><template v-for="item in overview" :key="item[0]"><dt>{{ item[0] }}</dt><dd>{{ item[1] }}</dd></template></dl>
          <div v-if="related.length" class="trace-chain"><span class="trace-chain-label">关联链</span><button v-for="row in related" :key="row.cursor" class="trace-chain-link" :class="{current:row.cursor===current.cursor}" @click="focus(row)">{{ relationLabel(row) }}</button></div>
          <div class="trace-notice">{{ overviewNotice }}</div>
        </template>
        <template v-else-if="tab === 'preview'"><div v-if="preview(current, true)" class="trace-preview-card"><pre>{{ preview(current, true) }}</pre></div><p v-else class="trace-preview-empty">当前事件没有可直接预览的文本内容；请查看概览、参数、结果或原始内容。</p></template>
        <template v-else-if="tab === 'timing'"><div class="trace-section-title">计时</div><dl class="trace-kv"><template v-for="item in timing" :key="item[0]"><dt>{{ item[0] }}</dt><dd>{{ item[1] }}</dd></template></dl><div class="trace-notice">仅显示服务端记录的时间和耗时；缺失时不推算 TTFT。</div></template>
        <template v-else><div class="trace-section-title">{{ activeTabLabel }}</div><div v-if="detail != null" class="trace-json-tree"><JsonTree :value="detail"/></div><p v-else class="trace-preview-empty">{{ emptyDetail }}</p></template>
        </div>
      </section>
    </div>
    <small class="trace-help" title="按事件顺序排列，宽度不代表真实耗时。拖选范围；双击、右键或 Escape 清除。">{{ rows.length }} 条业务记录 · {{ trace.events.length }} 条源记录 · 事件顺序轴</small>
    <p v-if="notice" role="status">{{ notice }}</p>
  </div>
</template>
<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import type { LoopState } from '../../../agent/loop/reducer'
import type { Data, LoopFrame } from '../../../api/agentLoopTypes'
import { category, safePacket, semanticTraceRows, type SemanticTraceRow, type TraceState } from '../../../agent/loop/trace'
import JsonTree from './JsonTree.vue'
const props = defineProps<{ state: LoopState; trace: TraceState }>()
type DetailKey = 'overview' | 'preview' | 'content' | 'parameters' | 'result' | 'options' | 'usage' | 'source' | 'schema' | 'timing' | 'packet'
const filter = ref('all'), search = ref(''), selected = ref<number | null>(null), page = ref(0), tab = ref<DetailKey>('overview'), notice = ref(''), copyLabel = ref('复制脱敏包')
const range = ref<[number, number] | null>(null)
let anchor = 0
const dragging = ref(false)
const categories: Record<string,string> = { all:'全部', lifecycle:'生命周期', model:'模型', tool:'工具', approval:'授权' }
const tabLabels: Record<DetailKey,string> = { overview:'概览', preview:'预览', content:'原始内容', parameters:'参数', result:'结果', options:'选项', usage:'用量', source:'来源', schema:'Schema', timing:'计时', packet:'数据包' }
const allRows = computed(() => semanticTraceRows(props.state.facts))
const rows = computed(() => allRows.value.filter(row => {
  const matchesCategory = filter.value === 'all' ? kind(row) !== 'lifecycle' || row.type === 'session.updated' : category(row.type) === filter.value
  return matchesCategory && JSON.stringify(safePacket(row)).toLowerCase().includes(search.value.trim().toLowerCase())
}))
const pageRows = computed(() => rows.value.slice(page.value * 80, page.value * 80 + 80))
const current = computed(() => rows.value.find(row => row.cursor === selected.value))
const rangeStyle = computed(() => range.value ? { left: `${Math.min(...range.value) / rows.value.length * 100}%`, width: `${(Math.abs(range.value[1] - range.value[0]) + 1) / rows.value.length * 100}%` } : {})
/** 泳道表达类别，横坐标只表达持久顺序，避免伪造模型耗时。 */
function segmentStyle(row: LoopFrame, index: number) {
  const lane = role(row).key === 'assistant' ? 1 : ['tool', 'approval'].includes(role(row).key) ? 2 : 0
  return { left: `${index / rows.value.length * 100}%`, width: `max(2px, calc(${100 / rows.value.length}% - 2px))`, top: `${7 + lane * 14}px` }
}
const docs: Record<string,[string,string]> = {
  'session.updated':['会话信息已更新','会话的公开展示信息已经更新。'], 'turn.start':['轮次开始','一轮 Agent 执行的持久边界。'], 'turn.end':['轮次结束','本轮已经结算，原因字段说明完成、取消或失败。'],
  'step.start':['步骤开始','一个步骤包含一次模型请求以及它触发的工具工作。'], 'step.end':['步骤结束','当前模型与工具步骤已经收束。'], 'user.message':['用户输入已提交','已写入持久记录并纳入后续模型历史的用户消息。'],
  'assistant.start':['模型请求快照','模型实际使用的模型、工具、输出上限与思考配置的安全摘要。'], 'assistant.message':['助手消息已提交','流式文本合并后的持久模型输出，可能带有工具调用、用量与结束原因。'], 'assistant.end':['模型尝试结算','本次模型尝试已经提交、失败或中断。'], 'assistant.retry':['模型重试','可重试的模型异常已经记录，随后会在同一步骤中重新尝试。'],
  'tool.call':['工具调用','模型声明的工具调用；参数只显示服务端授权的安全预览。'], 'tool.dispatch':['工具已派发','工具调用已经跨过副作用边界。'], 'tool.result':['工具结果','工具终态结果用于判断执行是否成功。'],
  'approval.requested':['请求授权','需要写入或执行权限的工具在派发前等待用户决定。'], 'approval.resolved':['授权已结算','授权决定已进入持久记录。'], 'question.requested':['请求补充信息','Agent 等待用户补充继续执行所需的信息。'], 'question.resolved':['补充信息已提交','用户回答已进入持久记录。'],
  'task_confirmation.requested':['请求确认任务','长任务入队前等待用户确认业务规格。'], 'task_confirmation.resolved':['任务确认已结算','任务规格确认已经进入持久记录。'], 'context.trimmed':['上下文已裁剪','上下文窗口裁剪只记录元信息，不公开被裁剪正文。'],
  'execution.quarantined':['执行已隔离','远端执行结果未知，工作区保持隔离。'], 'execution.reconciled':['执行已对账','可信执行证据已经完成对账。'], 'runtime.error':['运行时错误','Agent 图无法继续时记录的安全错误边界。'],
}
function kind(row: LoopFrame): 'lifecycle'|'message'|'system'|'assistant'|'tool'|'approval' {
  if (row.type === 'user.message') return 'message'
  if (row.type === 'assistant.start') return 'system'
  if (row.type.startsWith('assistant.')) return 'assistant'
  if (/^(approval|question|task_confirmation)\./.test(row.type)) return 'approval'
  if (/^(tool|task|execution)\./.test(row.type)) return 'tool'
  return 'lifecycle'
}
function role(row: LoopFrame) { const key = ({message:'user',system:'context',assistant:'assistant',tool:'tool',approval:'approval',lifecycle:'system'} as const)[kind(row)]; return { key, label: ({user:'用户',context:'上下文',assistant:'助手',tool:'工具',approval:'授权',system:'系统'} as const)[key] } }
function timelineKind(row: LoopFrame) { const value = role(row).key; return value === 'assistant' ? 'message' : value }
function title(row: LoopFrame) { return docs[row.type]?.[0] || row.data.display?.title || row.data.name || row.type }
function displaySeq(row: SemanticTraceRow) { return row.layers[0]?.correlation.source_seq ?? row.layers[0]?.cursor ?? row.cursor }
function requestSummary(row: LoopFrame): Data | null { return row.data.request_summary ?? Object.values(props.state.attempts).find(attempt => attempt.correlation.attempt_id === row.correlation.attempt_id)?.request_summary ?? null }
function interactionId(row: LoopFrame) { return typeof row.data.interaction_id === 'string' ? row.data.interaction_id : '' }
function relatedTool(row: LoopFrame) { return allRows.value.find(item => category(item.type) === 'tool' && item.correlation.call_id && item.correlation.call_id === row.correlation.call_id) }
function relatedAssistant(row: LoopFrame) { return allRows.value.find(item => kind(item) === 'assistant' && item.correlation.attempt_id && item.correlation.attempt_id === row.correlation.attempt_id) }
function textPreview(value: unknown) { const text = typeof value === 'string' ? value : ''; return text.length > 240 ? `${text.slice(0,239)}…` : text }
/** 列表只展示真实授权字段，缺失内容保持空值。 */
function preview(row: LoopFrame, full = false) { const d = row.data, summary = requestSummary(row); let value = ''
  if (row.type === 'assistant.start') value = `model=${summary?.model ?? '—'} · tools=${Array.isArray(summary?.tools) ? summary.tools.length : 0}`
  else if (kind(row) === 'approval') value = d.decision || d.source_outcome ? `授权结果：${status(row)}` : `等待 ${d.name || relatedTool(row)?.data.name || '工具'} 授权`
  else if (kind(row) === 'tool') value = String(row.type === 'tool.call' ? d.name || d.display?.target || '' : d.display?.result_preview || d.name || d.status || '')
  else value = String(d.content || d.display?.result_preview || d.reason || d.status || '')
  return full ? value : textPreview(value)
}
const sources = computed(() => { if (!current.value) return []; const seqs = new Set(current.value.layers.flatMap(layer => [layer.correlation.source_seq, layer.data.header_seq]).filter(Number.isSafeInteger)); return props.trace.events.filter(event => seqs.has(event.seq)) })
const related = computed(() => { if (!current.value) return []; const row = current.value; return allRows.value.filter(item => {
  if (item.cursor === row.cursor) return true
  if (interactionId(row) && interactionId(item) === interactionId(row)) return true
  if (row.correlation.call_id && item.correlation.call_id === row.correlation.call_id) return ['tool','approval'].includes(kind(item))
  if (row.correlation.attempt_id && item.correlation.attempt_id === row.correlation.attempt_id) return kind(item) === 'system'
  return false
}).slice(0,8) })
function relationLabel(row: SemanticTraceRow) { return `${row.cursor === current.value?.cursor ? '当前 · ' : ''}${title(row)} #${displaySeq(row)}` }
function purpose(row: LoopFrame) { return docs[row.type]?.[1] || '该业务记录由已授权的持久事件投影得出。' }
const statusNames: Record<string,string> = { succeeded:'成功', completed:'已完成', committed:'已完成', failed:'失败', denied:'已拒绝', rejected:'已拒绝', cancelled:'已取消', interrupted:'已中断', not_started:'未开始', outcome_unknown:'结果未知', allow:'已允许', always:'始终允许', pending:'等待中', running:'进行中', error:'失败' }
function status(row: LoopFrame) { const d = row.data, raw = d.status || d.outcome || d.decision
  if (raw) return statusNames[raw] || String(raw)
  if (row.type === 'assistant.start') return '请求快照'
  if (row.type === 'assistant.message') return d.interrupted ? '已中断' : '已完成'
  if (row.type.endsWith('.requested')) return '等待确认'
  if (row.type === 'user.message') return '已提交'
  if (row.type.endsWith('.end')) return d.reason === 'error' ? '失败' : d.reason === 'cancelled' ? '已取消' : '已完成'
  return row.durability === 'persistent' ? '已记录' : '实时'
}
const tabs = computed(() => { const currentKind = current.value ? kind(current.value) : 'lifecycle'; const keys: Record<string,DetailKey[]> = {
  tool:['overview','parameters','result','schema','timing'], approval:['overview','parameters','result','source','timing','packet'], message:['overview','preview','content','source','packet'], assistant:['overview','preview','content','source','timing','packet'], system:['overview','preview','content','source','schema','packet'], lifecycle:['overview','preview','packet','source'],
  }; return keys[currentKind].map(key => ({key,label:tabLabels[key]})) })
const activeTabLabel = computed(() => tabLabels[tab.value])
const overview = computed<[string,string][]>(() => { if (!current.value) return []; const row = current.value, d = row.data, summary = requestSummary(row), values: Array<[string,unknown]> = [['来源',sources.value.length ? 'JSONL 回放' : '持久语义流'],['状态',status(row)]]
  if (d.reason) values.push([kind(row) === 'system' ? '快照原因' : '事件原因',d.reason])
  if (kind(row) === 'system') values.push(['Provider',summary?.provider],['模型',summary?.model],['思考强度',summary?.reasoning_effort],['工具',Array.isArray(summary?.tools) ? `${summary.tools.length} 个` : null],['快照',`#${displaySeq(row)}`])
  if (kind(row) === 'assistant') { const request = allRows.value.find(item => kind(item) === 'system' && item.correlation.attempt_id === row.correlation.attempt_id); values.push(['请求',request ? `#${displaySeq(request)}` : null],['模型',summary?.model],['尝试',row.correlation.attempt_id],['输出 Token',d.usage?.completion_tokens == null ? null : `${d.usage.completion_tokens} tok`],['耗时',d.latency_ms == null ? null : formatDuration(d.latency_ms)]) }
  if (kind(row) === 'tool') values.push(['工具',d.name],['调用',row.correlation.call_id],['步骤',row.correlation.step == null ? null : `第 ${row.correlation.step} 步`],['退出码',d.exit_code])
  if (kind(row) === 'approval') values.push(['类型','扩展审计事件'],['工具',d.name || relatedTool(row)?.data.name],['调用',row.correlation.call_id])
  if (kind(row) === 'lifecycle') values.push(['轮次',row.correlation.turn == null ? null : `第 ${row.correlation.turn} 轮`],['序号',`#${displaySeq(row)}`])
  return values.filter((item): item is [string,string|number] => item[1] !== null && item[1] !== undefined && item[1] !== '').map(([name,value]) => [name,String(value)]) })
const overviewNotice = computed(() => current.value && kind(current.value) === 'system' ? `${title(current.value)} 是模型可见配置的安全摘要；完整系统提示词、请求头和协议内部状态不会发送到浏览器。` : '可读字段由关联事件投影得出；原始状态、授权来源和事件包分别保留。复制时会再次脱敏。')
function parsePreview(value: unknown) { if (typeof value !== 'string') return value ?? null; try { return JSON.parse(value) } catch { return value || null } }
const rawContent = computed(() => { if (!current.value) return null; const d = current.value.data
  if (kind(current.value) === 'message') return d.content ? {content:d.content} : null
  if (kind(current.value) === 'assistant') return Object.fromEntries(Object.entries({content:d.content,reasoning_preview:d.reasoning_preview,tool_calls:d.tool_calls}).filter(([,value]) => value != null && value !== ''))
  return null
})
const detail = computed(() => { if (!current.value) return null; const row = current.value, d = row.data, tool = relatedTool(row), assistant = relatedAssistant(row), summary = requestSummary(row)
  if (tab.value === 'content') return rawContent.value && Object.keys(rawContent.value).length ? rawContent.value : null
  if (tab.value === 'parameters') return parsePreview(d.display?.arguments_preview || tool?.data.display?.arguments_preview)
  if (tab.value === 'result') return kind(row) === 'approval' ? d.decision || d.source_outcome || null : d.display?.result_preview || tool?.data.display?.result_preview || null
  if (tab.value === 'options') return summary ? safePacket({provider:summary.provider,model:summary.model,protocol:summary.protocol,profile_id:summary.profile_id,profile_version:summary.profile_version,reasoning_effort:summary.reasoning_effort,max_tokens:summary.max_tokens}) : null
  if (tab.value === 'usage') return d.usage || assistant?.data.usage || null
  if (tab.value === 'schema') { const tools = summary?.tools; if (!Array.isArray(tools)) return null; const name = d.name || tool?.data.name; return name ? tools.find(item => item.name === name) ?? null : tools }
  if (tab.value === 'source') return sources.value.length ? sources.value : null
  if (tab.value === 'packet') return safePacket({record:row.layers,source_events:sources.value})
  return null
})
const emptyDetail = computed(() => ({content:'当前记录没有可公开的原始内容；系统提示词、请求头与协议内部状态不会发送到浏览器。',parameters:'此事件没有独立参数；工具参数会在调用记录到达后显示。',result:'尚未收到终态结果，当前展示的是调用或授权阶段。',options:'当前事件没有关联到模型请求快照，因此不会猜测请求选项。',usage:'Provider 尚未在关联助手消息中返回用量，页面不会估算 Token。',schema:'关联的模型请求没有提供可展示的工具 Schema。',source:'未取得授权源记录；源 seq 与业务 cursor 独立。',packet:'当前事件没有可复制的数据包。'} as Partial<Record<DetailKey,string>>)[tab.value] || '该事件未提供此项授权数据。')
const timing = computed<[string,string][]>(() => { if (!current.value) return []; const values: [string,string][] = [['事件时间',formatTime(current.value.ts)]]; if (Number.isFinite(current.value.data.latency_ms)) values.push(['模型耗时',formatDuration(current.value.data.latency_ms)]); return values })
function formatTime(value: string) { const date = new Date(value); return Number.isNaN(date.valueOf()) ? '—' : new Intl.DateTimeFormat('zh-CN',{hour:'2-digit',minute:'2-digit',second:'2-digit'}).format(date) }
function formatDuration(ms: number) { return ms < 1000 ? `${Math.max(0,Math.round(ms))} ms` : `${(ms / 1000).toFixed(ms < 10000 ? 2 : 1)} s` }
watch([filter, search], () => { page.value = 0; clear() })
watch(tabs, value => { if (!value.some(item => item.key === tab.value)) tab.value = 'overview' })
function clear() { dragging.value = false; range.value = null; selected.value = null }
function inRange(index: number) { return range.value && index >= Math.min(...range.value) && index <= Math.max(...range.value) }
/** 指针捕获让跨泳道、空白处及轴外松手都保持同一次选区操作。 */
function indexOf(event: PointerEvent) { const rect = (event.currentTarget as HTMLElement).getBoundingClientRect(); return rows.value.length ? Math.max(0, Math.min(rows.value.length - 1, Math.floor((event.clientX - rect.left) / rect.width * rows.value.length))) : -1 }
function select(index: number) { if (!rows.value[index]) return; selected.value = rows.value[index].cursor!; page.value = Math.floor(index / 80) }
function start(event: PointerEvent) { if (event.button !== 0) return; const index = indexOf(event); if (index >= 0) { (event.currentTarget as HTMLElement).setPointerCapture(event.pointerId); dragging.value = true; anchor = index; range.value = [index,index]; select(index) } }
function move(event: PointerEvent) { const index = indexOf(event); if (dragging.value && index >= 0) range.value = [anchor,index] }
function finish(event: PointerEvent) { if (!dragging.value) return; move(event); dragging.value = false; const target = event.currentTarget as HTMLElement; if (target.hasPointerCapture(event.pointerId)) target.releasePointerCapture(event.pointerId); select(indexOf(event)) }
/** 时间选区提供键盘等价操作，事件位置与屏幕像素无关。 */
function keyRange(event: KeyboardEvent) { if (!['ArrowLeft','ArrowRight','Home','End'].includes(event.key) || !rows.value.length) return; event.preventDefault(); const previous = range.value?.[1] ?? 0; const next = event.key === 'Home' ? 0 : event.key === 'End' ? rows.value.length - 1 : Math.max(0, Math.min(rows.value.length - 1, previous + (event.key === 'ArrowRight' ? 1 : -1))); range.value = [event.shiftKey ? range.value?.[0] ?? previous : next, next]; selected.value = rows.value[next].cursor!; page.value = Math.floor(next / 80) }
function focus(row: SemanticTraceRow) { const index = rows.value.findIndex(item => item.cursor === row.cursor); if (index >= 0) select(index); tab.value = 'overview' }
async function copy() { try { await navigator.clipboard.writeText(JSON.stringify(safePacket(range.value ? rows.value.filter((_, i) => inRange(i)) : detail.value ?? current.value ?? rows.value), null, 2)); notice.value = '已复制脱敏数据'; copyLabel.value = '已复制' } catch { notice.value = '无法访问剪贴板'; copyLabel.value = '复制失败' } finally { window.setTimeout(() => { copyLabel.value = '复制脱敏包' },1600) } }
</script>
<style scoped>    .trace-view { display: flex; min-height: 0; flex: 1; flex-direction: column; overflow: hidden; background: #fff; padding-bottom: 102px; }
    .trace-toolbar { display: flex; min-height: 44px; align-items: center; justify-content: space-between; gap: 16px; border-bottom: 1px solid var(--line); padding: 0 22px; background: #fff; }
    .trace-filter-group { display: flex; min-width: 0; align-items: center; gap: 3px; overflow-x: auto; }
    .trace-filter { flex: 0 0 auto; min-height: 27px; border: 1px solid transparent; border-radius: 7px; background: transparent; padding: 0 8px; color: var(--muted); font-size: 11px; cursor: pointer; }
    .trace-filter:hover { background: var(--surface-hover); color: var(--text); }
    .trace-filter.active { border-color: #d9dcff; background: #f0f1ff; color: #4546aa; font-weight: 650; }
    .trace-search { display: flex; width: min(230px,32vw); align-items: center; }
    .trace-search input { width: 100%; height: 28px; border: 1px solid #dce2eb; border-radius: 7px; outline: 0; background: #fbfcfe; padding: 0 9px; color: var(--text); font-size: 11px; }
    .trace-search input:focus { border-color: #aeb1ed; box-shadow: 0 0 0 3px rgba(91,91,214,.09); }

    .trace-waterfall-panel { display: grid; height: 50px; flex: 0 0 50px; grid-template-columns: 44px minmax(0,1fr); overflow: hidden; border-bottom: 1px solid var(--line); background: #fcfdff; padding: 0; user-select: none; }
    .trace-lane-labels { position: relative; border-right: 1px solid #edf0f4; color: #8b96a8; font-size: 10px; line-height: 1; }
    .trace-lane-labels span { position: absolute; right: 4px; display: flex; height: 8px; align-items: center; justify-content: flex-end; }
    .trace-lane-labels span:nth-child(1) { top: 7px; } .trace-lane-labels span:nth-child(2) { top: 21px; } .trace-lane-labels span:nth-child(3) { top: 35px; }
    .trace-waterfall-scroll { min-width: 0; overflow: hidden; }
    .trace-waterfall { position: relative; width: 100%; height: 50px; overflow: hidden; cursor: crosshair; touch-action: none; }
    .trace-waterfall:focus-visible { outline: 1px solid #536fe4; outline-offset: -1px; }
    .trace-selection-range { position: absolute; z-index: 0; top: 0; bottom: 0; min-width: 1px; border-right: 3px solid #536fe4; border-left: 3px solid #536fe4; background: rgba(83,111,228,.12); box-shadow: -100vw 0 0 100vw rgba(255,255,255,.58), 100vw 0 0 100vw rgba(255,255,255,.58); pointer-events: none; }
    .trace-segment { position: absolute; z-index: 1; top: calc(7px + var(--trace-segment-lane) * 14px); left: calc(var(--trace-segment-left) + var(--trace-segment-gap)); width: max(2px,calc(var(--trace-segment-width) - var(--trace-segment-gap) - var(--trace-segment-gap))); height: 8px; min-width: 2px; border: 0; border-radius: 1px; outline: 0; background: #78879d; padding: 0; cursor: pointer; opacity: .78; }
    .trace-segment:hover { z-index: 2; opacity: 1; }
    .trace-segment.selected { z-index: 2; opacity: 1; box-shadow: 0 0 0 1px #fcfdff,0 0 0 2px #536fe4; }
    .trace-segment.out-of-range { opacity: .2; }
    .trace-segment[data-kind="user"] { background: #5c78dc; }
    .trace-segment[data-kind="context"] { background: #58aa71; }
    .trace-segment[data-kind="message"] { background: #8166b2; opacity: 1; }
    .trace-segment[data-kind="message"][data-assistant-timing="true"] { background: linear-gradient(to right,#c6bdd8 0,#c6bdd8 var(--trace-assistant-ttft),#8166b2 var(--trace-assistant-ttft),#8166b2 100%); }
    .trace-segment[data-kind="tool"], .trace-segment[data-kind="approval"] { background: #d78127; opacity: 1; }
    .trace-segment[data-state="error"] { background: #de5147; }
    .trace-segment[data-search-match="false"] { opacity: .14; }
    .trace-waterfall-foot { display: none; }
    .trace-main { display: grid; min-height: 0; height: auto; flex: 1; grid-template-columns: minmax(0,1fr) minmax(360px,430px); overflow: hidden; }
    .trace-main:not(.has-selection) { grid-template-columns: minmax(0,1fr); }
    .trace-list-panel { min-width: 0; min-height: 0; overflow: auto; background: #fff; }
    .trace-list-header { display: none; }
    .trace-list { min-height: 100%; }
    .trace-empty { max-width: 520px; margin: 56px auto; padding: 18px; border: 1px dashed #d9e0ea; border-radius: 12px; background: #fbfcfe; color: #778397; font-size: 12px; line-height: 1.65; text-align: center; }
    .trace-row { display: grid; width: 100%; min-height: 30px; grid-template-columns: 56px minmax(0,1fr); align-items: center; gap: 8px; border: 0; border-bottom: 1px solid #eef1f5; border-left: 3px solid transparent; background: #fff; padding: 4px 10px 4px 8px; color: inherit; text-align: left; cursor: pointer; transition: background .13s ease, border-color .13s ease; }
    .trace-row:hover { background: #fafbfe; } .trace-row.selected { border-left-color: var(--accent); background: #f5f6ff; }
    .trace-row.timeline-inside:not(.selected) { background: #fafbff; }
    .trace-row.timeline-outside { opacity: .28; }
    .trace-row.timeline-outside:hover { opacity: .8; }
    .trace-row-seq { color: #8390a3; font: 10px/1.5 ui-monospace,SFMono-Regular,Consolas,monospace; }
    .trace-row-main { display: flex; min-width: 0; align-items: center; gap: 8px; } .trace-row-title { display: flex; min-width: 0; flex: 0 1 auto; align-items: center; gap: 7px; color: #334158; font-size: 11px; font-weight: 620; white-space: nowrap; }
    .trace-badge { flex: 0 0 auto; border-radius: 4px; padding: 1px 5px; font-size: 9px; font-weight: 700; letter-spacing: .04em; }
    .trace-badge[data-category="model"] { background: #f0ebfb; color: #6e4eaa; } .trace-badge[data-category="tool"] { background: #fff1dc; color: #aa6510; } .trace-badge[data-category="approval"] { background: #fff5d9; color: #946617; } .trace-badge[data-category="lifecycle"] { background: #edf1f5; color: #667589; }
    .trace-badge[data-role="system"] { background: #eef1f5; color: #667589; } .trace-badge[data-role="user"] { background: #eaf0ff; color: #4b68a8; } .trace-badge[data-role="context"] { background: #e8f8ea; color: #378553; } .trace-badge[data-role="assistant"] { background: #f3ecff; color: #7860aa; } .trace-badge[data-role="tool"] { background: #fff1dc; color: #aa6510; } .trace-badge[data-role="approval"] { background: #fff5d9; color: #946617; } .trace-badge[data-role="protocol"] { background: #f2f4f7; color: #758399; }
    .trace-schema-badge { flex: 0 0 auto; border: 1px solid #dce2ea; border-radius: 999px; background: #f8fafc; padding: 1px 5px; color: #738197; font: 9px/1.25 ui-monospace,SFMono-Regular,Consolas,monospace; letter-spacing: 0; }
    .trace-schema-badge[data-schema-status="known"] { border-color: #bce6d4; background: #effaf5; color: #177451; } .trace-schema-badge[data-schema-status="partial"] { border-color: #d7ccf4; background: #f6f3ff; color: #6952a4; } .trace-schema-badge[data-schema-status="unknown"] { border-color: #f0d49e; background: #fff9ec; color: #9a6516; } .trace-schema-badge[data-schema-status="unavailable"] { border-color: #dfe4eb; background: #f7f8fa; color: #7b8798; }
    .trace-row-preview { overflow: hidden; min-width: 0; flex: 1; margin: 0; color: #748197; font: 10px/1.45 ui-monospace,SFMono-Regular,Consolas,monospace; text-overflow: ellipsis; white-space: nowrap; }
    .trace-row-ref { display: none; }
    .trace-row-ref strong { color: #5c6c82; font-weight: 600; }

    .trace-detail { min-width: 0; min-height: 0; overflow: auto; border-left: 1px solid var(--line); background: #fff; }
    .trace-detail-head { display: flex; align-items: flex-start; justify-content: space-between; gap: 10px; border-bottom: 1px solid #edf0f5; padding: 13px 15px 10px; }
    .trace-detail-head > div { display: grid; min-width: 0; gap: 3px; }
    .trace-detail-eyebrow { color: #8581d9; font: 9px ui-monospace,SFMono-Regular,Consolas,monospace; letter-spacing: .08em; }
    .trace-detail-title { overflow: hidden; color: #28364d; font: 600 13px/1.3 ui-monospace,SFMono-Regular,Consolas,monospace; text-overflow: ellipsis; white-space: nowrap; }
    .trace-detail-head > .trace-detail-actions { display: flex; flex: 0 0 auto; align-items: center; gap: 6px; }
    .trace-detail-state { border-radius: 999px; background: #eef1f5; padding: 3px 7px; color: #68788d; font-size: 9px; }
    .trace-copy-button { min-height: 24px; border: 1px solid #d8def0; border-radius: 6px; background: #fafbff; padding: 0 7px; color: #555ba8; font-size: 10px; cursor: pointer; }
    .trace-copy-button:hover:not(:disabled) { border-color: #afb6e8; background: #f1f2ff; } .trace-copy-button:disabled { cursor: not-allowed; opacity: .5; }
    .trace-detail-tabs { display: flex; overflow-x: auto; border-bottom: 1px solid #e7ebf1; padding: 0 11px; }
    .trace-detail-tab { position: relative; flex: 0 0 auto; min-height: 36px; border: 0; background: transparent; padding: 0 7px; color: #788598; font-size: 10px; cursor: pointer; }
    .trace-detail-tab::after { position: absolute; right: 7px; bottom: -1px; left: 7px; height: 2px; content: ""; background: transparent; }
    .trace-detail-tab.active { color: #4c4db6; font-weight: 700; } .trace-detail-tab.active::after { background: #5b5bd6; }
    .trace-detail-body { padding: 13px 15px 20px; }
    .trace-detail-empty { margin: 22px 0; color: #788598; font-size: 12px; line-height: 1.65; }
    .trace-purpose { margin: 0 0 13px; color: #44536a; font-size: 12px; line-height: 1.65; }
    .trace-kv { display: grid; grid-template-columns: 96px minmax(0,1fr); gap: 7px 10px; margin: 0; font-size: 11px; }
    .trace-kv dt { color: #8490a3; } .trace-kv dd { overflow-wrap: anywhere; margin: 0; color: #3d4b61; font-family: ui-monospace,SFMono-Regular,Consolas,monospace; }
    .trace-overview-label { margin: 0 0 8px; color: #5f6f85; font-size: 10px; font-weight: 700; letter-spacing: .06em; }
    .trace-preview-card { overflow: hidden; border: 1px solid #e2e7ef; border-radius: 9px; background: #fbfcfe; }
    .trace-preview-card > pre { max-height: 400px; overflow: auto; margin: 0; padding: 11px; color: #33445d; font: 11px/1.65 ui-monospace,SFMono-Regular,Consolas,monospace; white-space: pre-wrap; overflow-wrap: anywhere; }
    .trace-preview-empty { border: 1px dashed #dde3ec; border-radius: 8px; padding: 13px; color: #8290a3; font-size: 11px; line-height: 1.6; }
    .trace-result-state { display: inline-flex; margin: 0 0 10px; border-radius: 999px; background: #edf8f1; padding: 3px 7px; color: #287351; font: 10px ui-monospace,SFMono-Regular,Consolas,monospace; }
    .trace-result-state.is-error { background: #fff0ed; color: #ad5245; }
    .trace-inline-summary { margin: 0 0 12px; color: #46566d; font-size: 11px; line-height: 1.6; }
    .trace-notice { margin: 14px 0 0; border-left: 3px solid #c7c9f4; background: #f7f7ff; padding: 8px 9px; color: #5d6480; font-size: 10px; line-height: 1.6; }
    .trace-chain { display: flex; flex-wrap: wrap; align-items: center; gap: 5px; margin-top: 14px; }
    .trace-chain-label { margin-right: 2px; color: #8290a3; font-size: 10px; font-weight: 650; }
    .trace-chain-link { max-width: 100%; overflow: hidden; border: 1px solid #dde2ed; border-radius: 999px; background: #fbfcfe; padding: 3px 7px; color: #56647a; font: 10px/1.2 ui-monospace,SFMono-Regular,Consolas,monospace; text-overflow: ellipsis; white-space: nowrap; cursor: pointer; }
    .trace-chain-link:hover { border-color: #aeb6e9; background: #f3f4ff; color: #494eb1; } .trace-chain-link.current { border-color: #aeb6e9; background: #e9eaff; color: #454aae; font-weight: 700; }
    .trace-field-table { width: 100%; border-collapse: collapse; font-size: 10px; } .trace-field-table th { padding: 0 0 7px; color: #8290a3; font-weight: 650; text-align: left; } .trace-field-table td { vertical-align: top; border-top: 1px solid #edf0f4; padding: 7px 3px 7px 0; color: #59687d; line-height: 1.5; } .trace-field-table td:first-child { width: 34%; color: #35445d; font-family: ui-monospace,SFMono-Regular,Consolas,monospace; } .trace-field-table code { overflow-wrap: anywhere; color: #495970; font-family: ui-monospace,SFMono-Regular,Consolas,monospace; font-size: 10px; }
    .trace-schema-table { width: 100%; border-collapse: collapse; font-size: 10px; } .trace-schema-table th { padding: 0 4px 7px 0; color: #8290a3; font-weight: 650; text-align: left; white-space: nowrap; } .trace-schema-table td { vertical-align: top; border-top: 1px solid #edf0f4; padding: 7px 5px 7px 0; color: #59687d; line-height: 1.5; } .trace-schema-table td:first-child { color: #35445d; font-family: ui-monospace,SFMono-Regular,Consolas,monospace; } .trace-schema-table code { overflow-wrap: anywhere; color: #495970; font-family: ui-monospace,SFMono-Regular,Consolas,monospace; font-size: 10px; } .trace-schema-source { color: #7b8799; font-size: 9px; } .trace-schema-sensitive { color: #a26316; font-size: 9px; font-weight: 650; }
    .trace-json { max-height: 440px; overflow: auto; margin: 0; border: 1px solid #e3e8ef; border-radius: 8px; background: #f7f9fc; padding: 10px; color: #43536b; font: 10px/1.55 ui-monospace,SFMono-Regular,Consolas,monospace; white-space: pre-wrap; overflow-wrap: anywhere; }
    .trace-schema-card { margin: 0 0 13px; border: 1px solid #e1e6ef; border-radius: 9px; background: #fbfcfe; padding: 10px; }
    .trace-schema-card:last-child { margin-bottom: 0; }
    .trace-schema-card-head { display: grid; gap: 4px; margin-bottom: 8px; }
    .trace-schema-card-head strong { color: #35445d; font: 600 11px/1.45 ui-monospace,SFMono-Regular,Consolas,monospace; }
    .trace-schema-card-head p { margin: 0; color: #617087; font-size: 10px; line-height: 1.55; }
    .trace-json-tree { overflow: auto; border: 1px solid #e3e8ef; border-radius: 7px; background: #fff; padding: 6px 8px; color: #43536b; font: 10px/1.55 ui-monospace,SFMono-Regular,Consolas,monospace; }
    .trace-json-tree details { margin: 1px 0; padding-left: 10px; }
    .trace-json-tree summary { color: #54647b; cursor: pointer; }
    .trace-json-tree-row { display: grid; grid-template-columns: minmax(92px,auto) minmax(0,1fr); gap: 7px; padding: 1px 0; }
    .trace-json-tree-key { color: #6a5baa; } .trace-json-tree-value { color: #3f607a; overflow-wrap: anywhere; }
    .trace-packet-details > summary { margin: 0 0 8px; color: #626fa5; font-size: 10px; cursor: pointer; }
    .trace-section-title { margin: 0 0 8px; color: #64738a; font-size: 10px; font-weight: 700; letter-spacing: .06em; text-transform: uppercase; }
    .trace-section-title + .trace-json { margin-bottom: 14px; }
    .trace-timing { display: grid; gap: 0; } .trace-timing-row { display: grid; grid-template-columns: minmax(0,1fr) auto; gap: 10px; border-bottom: 1px solid #edf0f4; padding: 8px 0; color: #536278; font-size: 11px; } .trace-timing-row strong { color: #394960; font-weight: 600; } .trace-timing-row time { color: #758298; font-family: ui-monospace,SFMono-Regular,Consolas,monospace; font-size: 10px; }

    @media (max-width:960px) { .trace-main { grid-template-columns: 1fr; overflow: auto; } .trace-list-panel { min-height: 330px; overflow: visible; } .trace-detail { min-height: 360px; border-top: 1px solid var(--line); border-left: 0; overflow: visible; } }
    @media (max-width:680px) { .workspace-tabs { padding: 0 14px; gap: 16px; } .workspace-tab-hint { display: none; } .trace-toolbar { padding-right: 14px; padding-left: 14px; } .trace-toolbar { align-items: stretch; flex-direction: column; gap: 5px; padding-top: 7px; padding-bottom: 7px; } .trace-search { width: 100%; } .trace-list-header, .trace-row { grid-template-columns: 42px minmax(0,1fr); gap: 8px; } .trace-list-header > :last-child, .trace-row-ref { display: none; } }
/* 参考 CSS 限于轨迹面板；平台输入栏独立占位，因此不重复预留源悬浮输入栏的 102px。 */
.trace-workspace{--canvas:#f7f8fc;--surface-hover:#f1f4f9;--line:#e3e8f0;--text:#172033;--muted:#5f6d82;--subtle:#748197;--accent:#5b5bd6;box-sizing:border-box;min-width:0;padding-bottom:0;color:var(--text);font:14px/1.5 Inter,"Segoe UI Variable Text","Microsoft YaHei UI","Microsoft YaHei",system-ui,sans-serif}
.trace-workspace *{box-sizing:border-box}.trace-workspace button,.trace-workspace input{font-family:inherit}.trace-row-title b{font-weight:inherit;overflow:hidden;text-overflow:ellipsis}.trace-row-title{overflow:hidden}.trace-list-panel{min-height:0}.trace-search input{box-shadow:none}.trace-close{height:24px;width:24px;border:0;border-radius:6px;background:transparent;color:#788598;font-size:17px;cursor:pointer}.trace-close:hover{background:#f1f4f9}.trace-help{padding:5px 14px;border-top:1px solid #edf0f4;color:#8994a6;font:10px/1.5 ui-monospace,SFMono-Regular,Consolas,monospace}.trace-pagination{display:flex;justify-content:space-between;align-items:center;padding:10px;font-size:10px}.trace-pagination button{border:1px solid #d8def0;border-radius:6px;background:#fafbff;padding:3px 7px;color:#555ba8}.trace-detail-body{overflow-wrap:anywhere}.trace-detail-body>p{color:#788598;font-size:12px;line-height:1.65}.trace-workspace>p{padding:8px 14px;margin:0;color:#788598;font-size:12px}
@media(max-width:960px){.trace-main.has-selection{grid-template-columns:1fr}.trace-list-panel{min-height:0;flex-shrink:0}.trace-detail{min-height:260px}.trace-main.has-selection .trace-list-panel{min-height:330px}}
@media(prefers-reduced-motion:reduce){.trace-row{transition:none}}
.trace-json-tree :deep(summary){padding:1px 0;color:#54647b}.trace-json-tree :deep(.json-children){padding-left:10px;border-left:1px solid #e3e8ef}.trace-json-tree :deep(.json-leaf){padding:1px 0;color:#3f607a}.trace-json-tree :deep(.json-leaf b){color:#6a5baa;font-weight:400}</style>
