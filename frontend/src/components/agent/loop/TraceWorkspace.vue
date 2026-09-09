<template>
  <div class="trace-workspace trace-view">
    <div class="trace-toolbar">
      <nav class="trace-filters trace-filter-group" aria-label="事件分类"><button v-for="(name, key) in categories" :key="key" class="trace-filter" :aria-pressed="filter === key" :class="{ active: filter === key }" @click="filter = key">{{ name }}</button></nav>
      <label class="trace-search"><input v-model="search" placeholder="搜索事件、工具、内容…" aria-label="搜索轨迹"/></label>
    </div>
    <p v-if="trace.denied">没有轨迹权限；普通对话与工具结果仍可使用。</p>
    <div class="trace-waterfall-panel">
      <div class="trace-lanes trace-lane-labels" aria-hidden="true"><span>会话</span><span>模型</span><span>工具</span></div>
      <div class="trace-axis trace-waterfall" @pointerdown="start" @pointermove="move" @pointerup="finish" @pointercancel="dragging = false" @dblclick="clear" @contextmenu.prevent="clear" @keydown.esc="clear" tabindex="0" aria-label="事件顺序轴，点击选择；Shift 加方向键扩选；Escape 清除" @keydown="keyRange">
        <span v-if="range" class="trace-range trace-selection-range" :style="rangeStyle"/>
        <button v-for="(row, index) in rows" :key="row.cursor" class="trace-segment" :data-index="index" :data-kind="role(row) === 'USER' ? 'user' : category(row.type) === 'model' ? 'message' : category(row.type)" :class="{ selected: selected === row.cursor, 'out-of-range': range && !inRange(index) }" :style="segmentStyle(row, index)" :title="`#${row.cursor} ${title(row)}`" :aria-label="`定位 #${row.cursor} ${title(row)}`" tabindex="-1"/>
      </div>
    </div>
    <div class="trace-split trace-main" :class="{ 'has-selection': current }">
      <div class="trace-list trace-list-panel">
        <p v-if="!rows.length" class="trace-empty">{{ state.facts.length ? '没有匹配的轨迹，请调整分类或搜索内容。' : '发送一条消息后，在这里查看模型请求、工具执行和事件详情。' }}</p>
        <button v-for="(row, index) in pageRows" :key="row.cursor" class="trace-row" :class="{selected:selected === row.cursor, 'timeline-inside': range && inRange(page * 80 + index), 'timeline-outside': range && !inRange(page * 80 + index)}" @click="select(page * 80 + index)">
          <span class="trace-seq trace-row-seq">#{{ row.cursor }}</span><span class="trace-row-main"><span class="trace-row-title"><span class="trace-badge" :data-category="category(row.type)" :data-role="role(row).toLowerCase()">{{ role(row) }}</span><b>{{ title(row) }}</b></span><span class="trace-preview trace-row-preview">{{ preview(row) }}</span><small v-if="row.layers.length > 1" class="trace-schema-badge" title="该语义行包含的传输事件数量">{{ row.layers.length }} 层</small></span>
        </button>
        <div v-if="rows.length > 80" class="trace-pagination"><button :disabled="page === 0" @click="page--">上一页</button><span>{{ page + 1 }} / {{ Math.max(1, Math.ceil(rows.length / 80)) }}</span><button :disabled="(page + 1) * 80 >= rows.length" @click="page++">下一页</button></div>
      </div>
      <section v-if="current" class="trace-inspector trace-detail">
        <div class="inspector-head trace-detail-head"><div><small class="trace-detail-eyebrow">RECORD · PACKET INSPECTOR</small><b class="trace-detail-title">{{ title(current) }}</b></div><div class="trace-detail-actions"><button class="trace-copy-button" @click="copy">复制脱敏包</button><button class="trace-close" aria-label="关闭详情" @click="selected = null">×</button></div></div>
        <nav class="trace-detail-tabs" aria-label="事件详情"><button v-for="name in tabs" :key="name" class="trace-detail-tab" :class="{active:tab===name}" :aria-pressed="tab===name" @click="tab=name">{{ name }}</button></nav>
        <div class="inspector-body trace-detail-body">
        <template v-if="tab === '概览'">
          <p class="trace-purpose">{{ title(current) }}<span v-if="current.data.status"> · {{ current.data.status }}</span></p>
          <dl class="trace-kv"><dt>事件类型</dt><dd>{{ current.type }}</dd><dt>记录序号</dt><dd>#{{ current.cursor }}</dd><dt>回合 / 步骤</dt><dd>{{ current.correlation.turn ?? '—' }} / {{ current.correlation.step ?? '—' }}</dd><dt>请求标识</dt><dd>{{ current.correlation.attempt_id ?? '—' }}</dd><dt>服务端时间</dt><dd>{{ current.ts }}</dd><dt>来源序号</dt><dd>{{ current.correlation.source_seq ?? '未提供' }}</dd></dl>
          <div class="trace-chain"><span class="trace-chain-label">关联记录</span><button v-for="layer in current.layers" :key="layer.cursor" class="trace-chain-link" @click="tab = '已授权内容'">#{{ layer.cursor }} {{ layer.type }}</button></div>
        </template>
        <template v-else-if="tab === '预览'"><div v-if="preview(current)" class="trace-preview-card"><pre>{{ preview(current, true) }}</pre></div><p v-else class="trace-preview-empty">该事件未提供内容预览。</p></template>
        <template v-else-if="tab === '计时'"><p>事件时间：{{ current.ts }}</p><p>未提供服务端请求起止时点时，不推算 TTFT 或历史耗时。</p></template>
        <template v-else-if="tab === 'Schema'"><div v-if="trace.catalog" class="trace-json-tree"><JsonTree :value="schema"/></div><p v-else>服务端尚未提供 Schema 目录。</p></template>
        <template v-else-if="tab === '来源'"><div v-if="sources.length" class="trace-json-tree"><JsonTree :value="sources"/></div><p v-else>未取得授权源记录，源 seq 与语义 cursor 独立。</p></template>
        <template v-else><div v-if="detail != null" class="trace-json-tree"><JsonTree :value="detail"/></div><p v-else>该事件未提供此项授权数据。原始系统提示词、请求头与协议内部状态不公开。</p></template>
        </div>
      </section>
    </div>
    <small class="trace-help" title="按事件顺序排列，宽度不代表真实耗时。拖选范围；双击、右键或 Escape 清除。">{{ rows.length }} 条语义记录 · {{ trace.events.length }} 条源记录 · 事件顺序轴</small>
    <p v-if="notice" role="status">{{ notice }}</p>
  </div>
</template>
<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import type { LoopState } from '../../../agent/loop/reducer'
import type { LoopFrame } from '../../../api/agentLoopTypes'
import { category, safePacket, semanticTraceRows, type TraceState } from '../../../agent/loop/trace'
import JsonTree from './JsonTree.vue'
const props = defineProps<{ state: LoopState; trace: TraceState }>()
const filter = ref('all'), search = ref(''), selected = ref<number | null>(null), page = ref(0), tab = ref('概览'), notice = ref('')
const range = ref<[number, number] | null>(null)
let anchor = 0
const dragging = ref(false)
const categories: Record<string,string> = { all:'全部', lifecycle:'生命周期', model:'模型', tool:'工具', approval:'审批', question:'问答', task:'任务' }
const tabs = ['概览','预览','已授权内容','参数','结果','选项','用量','来源','Schema','工具 Schema','计时','关联']
const rows = computed(() => semanticTraceRows(props.state.facts).filter(row => (filter.value === 'all' || category(row.type) === filter.value) && JSON.stringify(safePacket(row)).toLowerCase().includes(search.value.toLowerCase())))
const pageRows = computed(() => rows.value.slice(page.value * 80, page.value * 80 + 80))
const current = computed(() => rows.value.find(row => row.cursor === selected.value))
const rangeStyle = computed(() => range.value ? { left: `${Math.min(...range.value) / rows.value.length * 100}%`, width: `${(Math.abs(range.value[1] - range.value[0]) + 1) / rows.value.length * 100}%` } : {})
/** 泳道表达类别，横坐标只表达持久顺序，避免伪造模型耗时。 */
function segmentStyle(row: LoopFrame, index: number) {
  const kind = category(row.type), lane = kind === 'model' ? 1 : ['tool', 'approval', 'question', 'task'].includes(kind) ? 2 : 0
  return { left: `${index / rows.value.length * 100}%`, width: `max(2px, calc(${100 / rows.value.length}% - 2px))`, top: `${7 + lane * 14}px` }
}
/** 使用授权摘要生成紧凑语义行，原始事件保留在详情的数据层。 */
function role(row: LoopFrame) { return row.type === 'user.message' ? 'USER' : category(row.type) === 'model' ? 'ASSISTANT' : category(row.type).toUpperCase() }
function title(row: LoopFrame) { return row.data.name || row.data.request_summary?.model || ({ 'user.message': '用户消息', 'turn.start': '回合开始', 'turn.end': '回合结束' } as Record<string, string>)[row.type] || row.type }
/** 列表只显示短摘要；详情保留服务端已经授权的完整预览，不再二次截断。 */
function preview(row: LoopFrame, full = false) { const d = row.data; const text = String(safePacket(d.display?.result_preview || d.display?.target || d.content || d.reason || d.status || row.correlation.attempt_id || '')); return full ? text : text.slice(0, 240) }
const sources = computed(() => props.trace.events.filter(event => current.value?.layers.some(layer => layer.correlation.source_seq === event.seq)))
const schema = computed(() => ({ stream: props.trace.catalog?.stream?.types?.[current.value?.type || ''] ?? '未知事件 Schema', source: props.trace.catalog?.facts?.events?.[sources.value[0]?.type] ?? '未取得源 Schema', catalog: props.trace.catalog?.facts }))
const detail = computed(() => { const row = current.value; if (!row) return null; const d = row.data
  const summary = d.request_summary ?? Object.values(props.state.attempts).find(a => a.correlation.attempt_id === row.correlation.attempt_id)?.request_summary
  return safePacket(({ '预览': d.display ?? d.content, '已授权内容': row.layers, '参数': d.display?.arguments_preview, '结果': d.display?.result_preview, '选项': summary, '用量': d.usage, '工具 Schema': summary?.tools, '关联': props.state.facts.filter(f => f.correlation.turn_id === row.correlation.turn_id && (!row.correlation.call_id || f.correlation.call_id === row.correlation.call_id)) } as Record<string,any>)[tab.value]) })
watch([filter, search], () => { page.value = 0; clear() })
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
async function copy() { try { await navigator.clipboard.writeText(JSON.stringify(safePacket(range.value ? rows.value.filter((_, i) => inRange(i)) : current.value ?? rows.value), null, 2)); notice.value = '已复制脱敏数据' } catch { notice.value = '无法访问剪贴板' } }
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
