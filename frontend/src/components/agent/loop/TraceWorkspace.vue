<template>
  <div class="trace-workspace">
    <div class="trace-toolbar"><select v-model="filter" aria-label="事件分类"><option v-for="(name, key) in categories" :key="key" :value="key">{{ name }}</option></select><input v-model="search" placeholder="搜索类型、工具、身份…" aria-label="搜索轨迹"/><span>{{ rows.length }} 条语义记录 · {{ trace.events.length }} 条授权源记录</span><button @click="copy">复制脱敏包</button></div>
    <p v-if="trace.denied">没有轨迹权限；普通对话与工具结果仍可使用。</p>
    <div class="trace-axis" @pointerdown="start" @pointerup="finish" @dblclick="clear" @contextmenu.prevent="clear" @keydown.esc="clear" tabindex="0" aria-label="事件顺序轴，点击选择；Shift 加方向键扩选；Escape 清除" @keydown="keyRange">
      <button v-for="(row, index) in rows" :key="row.cursor" :data-index="index" :class="{ selected: inRange(index) }" :title="`${row.cursor} ${row.type}`" tabindex="-1" @click="selected = row.cursor!">▏</button>
    </div><small>排序轴按持久 cursor 排列，宽度不代表真实耗时。拖选范围 · 双击 / 右键 / Escape 清除</small>
    <div class="trace-split">
      <div class="trace-list"><div v-for="row in pageRows" :key="row.cursor" class="trace-row"><button :class="{active:selected === row.cursor}" @click="selected = row.cursor!"><span>#{{ row.cursor }}</span><b>{{ row.type }}</b><small>{{ row.data.name || row.correlation.attempt_id || row.correlation.turn_id }}</small></button></div><div class="trace-pagination"><button :disabled="page === 0" @click="page--">上一页</button><span>{{ page + 1 }} / {{ Math.max(1, Math.ceil(rows.length / 80)) }}</span><button :disabled="(page + 1) * 80 >= rows.length" @click="page++">下一页</button></div></div>
      <section v-if="current" class="trace-inspector">
        <div class="inspector-head"><b>#{{ current.cursor }} {{ current.type }}</b><button @click="selected = null">关闭详情</button></div>
        <nav><button v-for="name in tabs" :key="name" :class="{active:tab===name}" @click="tab=name">{{ name }}</button></nav>
        <template v-if="tab === '概览'"><p>会话 → 回合 {{ current.correlation.turn }} → step {{ current.correlation.step ?? '未知' }} → attempt {{ current.correlation.attempt_id ?? '无' }}</p><p>服务端时间：{{ current.ts }}</p><p>持久事件 #{{ current.cursor }} · 源 seq {{ current.correlation.source_seq ?? '未提供' }}</p></template>
        <template v-else-if="tab === '计时'"><p>事件时间：{{ current.ts }}</p><p>未提供服务端请求起止时点时，不推算 TTFT 或历史耗时。</p></template>
        <template v-else-if="tab === 'Schema'"><JsonTree v-if="trace.catalog" :value="schema"/><p v-else>服务端尚未提供 Schema 目录。</p></template>
        <template v-else-if="tab === '来源'"><JsonTree v-if="sources.length" :value="sources"/><p v-else>未取得授权源记录，源 seq 与语义 cursor 独立。</p></template>
        <template v-else><JsonTree v-if="detail != null" :value="detail"/><p v-else>该事件未提供此项授权数据。原始系统提示词、请求头与协议内部状态不公开。</p></template>
      </section>
    </div>
    <p v-if="notice" role="status">{{ notice }}</p>
  </div>
</template>
<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import type { LoopState } from '../../../agent/loop/reducer'
import { category, safePacket, semanticTraceRows, type TraceState } from '../../../agent/loop/trace'
import JsonTree from './JsonTree.vue'
const props = defineProps<{ state: LoopState; trace: TraceState }>()
const filter = ref('all'), search = ref(''), selected = ref<number | null>(null), page = ref(0), tab = ref('概览'), notice = ref('')
const range = ref<[number, number] | null>(null)
let anchor = 0
const categories: Record<string,string> = { all:'全部', lifecycle:'生命周期', model:'模型', tool:'工具', approval:'审批', question:'问答', task:'任务' }
const tabs = ['概览','预览','已授权内容','参数','结果','选项','用量','来源','Schema','工具 Schema','计时','关联']
const rows = computed(() => semanticTraceRows(props.state.facts).filter(row => (filter.value === 'all' || category(row.type) === filter.value) && JSON.stringify(safePacket(row)).toLowerCase().includes(search.value.toLowerCase())))
const pageRows = computed(() => rows.value.slice(page.value * 80, page.value * 80 + 80))
const current = computed(() => rows.value.find(row => row.cursor === selected.value))
const sources = computed(() => props.trace.events.filter(event => current.value?.layers.some(layer => layer.correlation.source_seq === event.seq)))
const schema = computed(() => ({ stream: props.trace.catalog?.stream?.types?.[current.value?.type || ''] ?? '未知事件 Schema', source: props.trace.catalog?.facts?.events?.[sources.value[0]?.type] ?? '未取得源 Schema', catalog: props.trace.catalog?.facts }))
const detail = computed(() => { const row = current.value; if (!row) return null; const d = row.data
  const summary = d.request_summary ?? Object.values(props.state.attempts).find(a => a.correlation.attempt_id === row.correlation.attempt_id)?.request_summary
  return safePacket(({ '预览': d.display ?? d.content, '已授权内容': row.layers, '参数': d.display?.arguments_preview, '结果': d.display?.result_preview, '选项': summary, '用量': d.usage, '工具 Schema': summary?.tools, '关联': props.state.facts.filter(f => f.correlation.turn_id === row.correlation.turn_id && (!row.correlation.call_id || f.correlation.call_id === row.correlation.call_id)) } as Record<string,any>)[tab.value]) })
watch([filter, search], () => { page.value = 0; clear() })
function clear() { range.value = null; selected.value = null }
function inRange(index: number) { return range.value && index >= Math.min(...range.value) && index <= Math.max(...range.value) }
function indexOf(event: PointerEvent) { const target = event.target as HTMLElement; const index = Number(target.dataset.index); return Number.isFinite(index) ? index : -1 }
function start(event: PointerEvent) { const index = indexOf(event); if (index >= 0) { anchor = index; range.value = [index,index] } }
function finish(event: PointerEvent) { const index = indexOf(event); if (index >= 0) range.value = [anchor,index] }
/** 时间选区提供键盘等价操作，事件位置与屏幕像素无关。 */
function keyRange(event: KeyboardEvent) { if (!['ArrowLeft','ArrowRight','Home','End'].includes(event.key) || !rows.value.length) return; event.preventDefault(); const previous = range.value?.[1] ?? 0; const next = event.key === 'Home' ? 0 : event.key === 'End' ? rows.value.length - 1 : Math.max(0, Math.min(rows.value.length - 1, previous + (event.key === 'ArrowRight' ? 1 : -1))); range.value = [event.shiftKey ? range.value?.[0] ?? previous : next, next]; selected.value = rows.value[next].cursor!; page.value = Math.floor(next / 80) }
async function copy() { try { await navigator.clipboard.writeText(JSON.stringify(safePacket(range.value ? rows.value.filter((_, i) => inRange(i)) : current.value ?? rows.value), null, 2)); notice.value = '已复制脱敏数据' } catch { notice.value = '无法访问剪贴板' } }
</script>
<style scoped>.trace-workspace{min-height:0;display:flex;flex-direction:column;gap:10px;padding:16px;overflow:auto}.trace-toolbar{display:flex;flex-wrap:wrap;gap:8px;align-items:center;font-size:12px}.trace-toolbar input{flex:1;min-width:140px}.trace-toolbar input,.trace-toolbar select,button{border:1px solid #dce6e0;border-radius:6px;background:var(--bg-card,#fff);color:inherit;padding:6px 9px}.trace-axis{display:flex;overflow:auto;min-height:42px;align-items:center;background:#edf4f0;border-radius:7px}.trace-axis button{border:0;border-radius:0;padding:0;min-width:4px;max-width:12px;flex:1;color:#85ad9b}.trace-axis .selected{background:#198e70;color:white}.trace-split{display:flex;gap:16px;min-height:0}.trace-list{flex:1;min-width:180px}.trace-row button{width:100%;text-align:left;display:flex;gap:10px;align-items:center;border:0;border-bottom:1px solid #e5ebe7}.trace-row small{overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.trace-row b{font-size:12px}.active{background:#e2f1e9!important}.trace-inspector{flex:1;min-width:0;overflow:auto;border:1px solid #dbe5df;padding:14px;border-radius:10px;font-size:12px}.trace-inspector nav{display:flex;gap:4px;flex-wrap:wrap;margin:12px 0}.inspector-head,.trace-pagination{display:flex;justify-content:space-between;gap:8px}.trace-workspace>small{color:#64748b}@media(max-width:768px){.trace-split{display:block}.trace-inspector{position:fixed;inset:80px 12px 20px;background:var(--bg-card,#fff);z-index:100;box-shadow:0 10px 80px #1236}.trace-toolbar span{width:100%}}
</style>
