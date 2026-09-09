<template>
  <n-popover v-model:show="open" trigger="click" placement="top-start" :show-arrow="false" :raw="true" :style="{ boxShadow: 'none', background: 'transparent' }">
    <template #trigger>
      <button ref="trigger" class="thinking-trigger" type="button" :aria-label="`思考强度：${label}`" aria-haspopup="dialog" :aria-expanded="open" :data-effort="current || 'off'" :disabled="!allowed.length" @keydown.esc="close">
        <span class="thinking-dial" aria-hidden="true"></span><span class="thinking-copy"><small>思考</small><span>{{ label }}</span></span><n-icon :component="ChevronDownIcon" :size="13" class="thinking-chevron"/>
      </button>
    </template>
    <section class="thinking-menu" role="dialog" aria-label="思考强度设置" @keydown.esc.stop.prevent="close" @wheel.prevent="wheel">
      <div class="effort-slider-card" :data-effort="current || 'off'">
        <header class="effort-slider-header"><div><strong>{{ label }}</strong><span>{{ model || '未配置模型' }}</span></div><span class="effort-slider-caption">{{ caption }}</span></header>
        <label class="sr-only" for="agent-loop-effort-slider">思考强度</label>
        <div class="effort-slider-wrap" :class="{ 'is-max': current === 'max' }">
          <span class="effort-particles" aria-hidden="true"><span v-for="offset in ['-100%', '0%']" :key="offset" class="effort-liquid" :style="{ '--liquid-start': offset }"><span v-for="(particle, particleIndex) in particles" :key="particleIndex" class="effort-particle" :style="{ '--x': `${particle[0]}%`, '--y': `${particle[1]}%`, '--size': `${particle[2]}px` }"/></span></span>
          <span class="effort-slider-marks" :style="{ gridTemplateColumns: `repeat(${allowed.length}, 1fr)` }" aria-hidden="true"><span v-for="(item, position) in allowed" :key="item" class="effort-slider-mark" :class="{ 'is-active': position <= index }"></span></span>
          <input id="agent-loop-effort-slider" ref="slider" class="effort-slider" type="range" min="0" :max="Math.max(0, allowed.length - 1)" step="1" :value="index" :style="sliderStyle" aria-label="思考强度" :aria-valuetext="label" @input="change(Number(($event.target as HTMLInputElement).value))" />
        </div>
      </div>
    </section>
  </n-popover>
</template>
<script setup lang="ts">
import { computed, nextTick, ref, watch } from 'vue'
import { NIcon, NPopover } from 'naive-ui'
import ChevronDownIcon from 'naive-ui/es/_internal/icons/ChevronDown'
import type { Effort } from '../../../api/agentLoopTypes'

const props = defineProps<{ modelValue: Effort | null; allowed: Effort[]; model?: string }>()
const emit = defineEmits<{ 'update:modelValue': [Effort] }>()
const open = ref(false), trigger = ref<HTMLButtonElement>(), slider = ref<HTMLInputElement>()
const labels: Record<Effort, string> = { off: '关闭', low: '低强度', medium: '中强度', high: '高强度', xhigh: '更高强度', max: '最高强度' }
const captions: Record<Effort, string> = { off: '直接回答', low: '快速推理', medium: '均衡推理', high: '深入推理', xhigh: '更深推理', max: '最大推理' }
/** 原始参考页的两组粒子坐标；仅最高档显示，减少动态效果时停止动画。 */
const particles = [[7,28,2],[14,68,2],[21,17,1],[31,60,2],[39,29,1],[48,66,2],[57,24,2],[65,72,1],[74,31,2],[83,66,2],[86,20,1]]
const current = computed<Effort | null>(() => props.modelValue && props.allowed.includes(props.modelValue) ? props.modelValue : props.allowed[0] || null)
const index = computed(() => Math.max(0, props.allowed.indexOf(current.value || props.allowed[0])))
const label = computed(() => current.value ? labels[current.value] : '不可用')
const caption = computed(() => current.value ? captions[current.value] : '当前协议档未公开思考档位')
const sliderStyle = computed(() => ({ '--slider-progress': `${index.value / Math.max(1, props.allowed.length - 1) * 100}%` }))
watch(open, value => { if (value) void nextTick(() => slider.value?.focus()) })
// 能力刷新为空时关闭弹层，不保留可操作的过期档位。
watch(() => props.allowed.length, length => { if (!length) close() })
/** 原生 range 提供方向键/Home/End；滚轮仅在弹层内依档位顺序调节。 */
function change(value: number) { const effort = props.allowed[Math.max(0, Math.min(props.allowed.length - 1, value))]; if (effort) emit('update:modelValue', effort) }
function wheel(event: WheelEvent) { if (event.deltaY) change(index.value + (event.deltaY > 0 ? 1 : -1)) }
function close() { open.value = false; trigger.value?.focus() }
</script>
<style scoped>
.thinking-trigger{display:inline-flex;min-width:0;height:30px;align-items:center;gap:6px;border:1px solid transparent;border-radius:999px;background:transparent;color:#46546a;padding:0 6px 0 3px;cursor:pointer;transition:.15s ease}.thinking-trigger:hover:not(:disabled),.thinking-trigger[aria-expanded="true"]{border-color:#dce4e6;background:#f3f7f5}.thinking-trigger:disabled{cursor:default;opacity:.55}.thinking-dial{position:relative;display:grid;width:20px;height:20px;flex:0 0 auto;place-items:center;border:1px solid #a9acec;border-radius:50%;background:conic-gradient(from 32deg,#5b5bd6 0 18%,rgba(147,140,255,.18) 18% 33%,#47a783 33% 46%,rgba(87,216,193,.16) 46% 100%)}.thinking-dial::before{width:12px;height:12px;content:"";border-radius:50%;background:#fff}.thinking-dial::after{position:absolute;top:3px;width:2px;height:5px;content:"";border-radius:4px;background:#42439f;transform-origin:50% 8px;transition:transform .2s ease}.thinking-trigger[data-effort="off"] .thinking-dial::after{transform:rotate(-100deg)}.thinking-trigger[data-effort="low"] .thinking-dial::after{transform:rotate(-52deg)}.thinking-trigger[data-effort="medium"] .thinking-dial::after{transform:rotate(0deg)}.thinking-trigger[data-effort="high"] .thinking-dial::after{transform:rotate(52deg)}.thinking-trigger[data-effort="xhigh"] .thinking-dial::after{transform:rotate(76deg)}.thinking-trigger[data-effort="max"] .thinking-dial::after{transform:rotate(102deg)}.thinking-copy{display:grid;line-height:1.08;text-align:left}.thinking-copy small{color:#8e9aac;font-size:9px;letter-spacing:.04em}.thinking-copy span{font-size:11px;font-weight:620}.thinking-chevron{flex:0 0 auto;color:#8e9aac;transition:transform .16s ease}.thinking-trigger[aria-expanded="true"] .thinking-chevron{transform:rotate(180deg)}.thinking-menu{width:min(272px,calc(100vw - 24px));padding:0}    .effort-slider-card { border: 1px solid #e1e5ec; border-radius: 16px; background: rgba(255,255,255,.98); padding: 14px 14px 13px; box-shadow: 0 12px 28px rgba(32,48,76,.14), 0 1px 2px rgba(32,48,76,.04); }
    .effort-slider-header { display: flex; min-width: 0; align-items: flex-start; justify-content: space-between; gap: 12px; padding: 0 2px; }
    .effort-slider-header > div { display: grid; min-width: 0; gap: 1px; }
    .effort-slider-header strong { color: #5b5bd6; font-size: 14px; font-weight: 700; letter-spacing: -.01em; }
    .effort-slider-header span { overflow: hidden; color: #778397; font-size: 11px; text-overflow: ellipsis; white-space: nowrap; }
    .effort-slider-card[data-effort="off"] .effort-slider-header strong { color: #7d899b; }
    .effort-slider-card[data-effort="off"] .effort-slider-caption { color: #8e99aa; }
    .effort-slider-card[data-effort="low"] .effort-slider-header strong { color: #bf8614; }
    .effort-slider-card[data-effort="medium"] .effort-slider-header strong { color: #168457; }
    .effort-slider-card[data-effort="high"] .effort-slider-header strong { color: #286dd6; }
    .effort-slider-card[data-effort="max"] .effort-slider-header strong { color: #7344d3; }
    .effort-slider-caption { flex: 0 0 auto; margin-top: 2px; color: #59677d; font-size: 11px; }
    .effort-slider-wrap { position: relative; width: min(216px, 100%); height: 42px; margin: 12px 0 0; isolation: isolate; }
    .effort-slider-wrap::before { position: absolute; z-index: 0; top: 9px; right: 0; left: 0; height: 24px; content: ""; border: 0; border-radius: 999px; background: #edf0f5; box-shadow: inset 0 1px 1px rgba(45,44,130,.08); }
    .effort-slider-wrap.is-max::before { background: linear-gradient(90deg, #4a3bb3 0%, #6e55d5 22%, #b68afa 48%, #d3b0ff 63%, #8f63de 80%, #4a3bb3 100%); background-size: 220% 100%; box-shadow: inset 0 1px 1px rgba(255,255,255,.26), 0 0 10px rgba(116,72,224,.2); animation: max-liquid-flow-right 8s linear infinite; }
    .effort-slider { --slider-progress: 75%; --effort-start: #5b5bd6; --effort-end: #9969f2; --effort-glow: rgba(91,91,214,.22); position: relative; z-index: 3; display: block; width: 100%; height: 42px; margin: 0; appearance: none; -webkit-appearance: none; border: 0; background: transparent; cursor: pointer; }
    .effort-slider-card[data-effort="off"] .effort-slider { --effort-start: #a3adbc; --effort-end: #cbd2dc; --effort-glow: rgba(125,137,155,.12); }
    .effort-slider-card[data-effort="low"] .effort-slider { --effort-start: #edaa24; --effort-end: #f7d05a; --effort-glow: rgba(237,170,36,.24); }
    .effort-slider-card[data-effort="medium"] .effort-slider { --effort-start: #21a868; --effort-end: #75d598; --effort-glow: rgba(33,168,104,.23); }
    .effort-slider-card[data-effort="high"] .effort-slider { --effort-start: #3678ea; --effort-end: #79a9ff; --effort-glow: rgba(54,120,234,.24); }
    .effort-slider-card[data-effort="max"] .effort-slider { --effort-start: #5b38cf; --effort-end: #b06cf0; --effort-glow: rgba(112,70,221,.28); }
    .effort-slider::-webkit-slider-runnable-track { height: 24px; border: 0; border-radius: 999px; background: linear-gradient(90deg, var(--effort-start) 0%, var(--effort-end) var(--slider-progress), #edf0f5 var(--slider-progress), #edf0f5 100%); box-shadow: inset 0 1px 1px rgba(45,44,130,.08), 0 0 8px var(--effort-glow); }
    .effort-slider::-webkit-slider-thumb { width: 30px; height: 30px; margin-top: -4px; appearance: none; -webkit-appearance: none; border: 1px solid #dfe4ed; border-radius: 50%; background: #fff; box-shadow: 0 3px 8px rgba(32,48,76,.18); }
    .effort-slider::-moz-range-track { height: 24px; border: 0; border-radius: 999px; background: #edf0f5; box-shadow: inset 0 1px 1px rgba(45,44,130,.08); }
    .effort-slider::-moz-range-progress { height: 24px; border-radius: 999px; background: linear-gradient(90deg, var(--effort-start), var(--effort-end)); box-shadow: 0 0 8px var(--effort-glow); }
    .effort-slider::-moz-range-thumb { width: 28px; height: 28px; border: 1px solid #dfe4ed; border-radius: 50%; background: #fff; box-shadow: 0 3px 8px rgba(32,48,76,.18); }
    .effort-slider-wrap.is-max .effort-slider::-webkit-slider-runnable-track, .effort-slider-wrap.is-max .effort-slider::-moz-range-track { border-color: transparent; background: transparent; box-shadow: none; }
    .effort-slider-wrap.is-max .effort-slider::-moz-range-progress { background: transparent; }
    .effort-slider-marks { position: absolute; z-index: 2; top: 0; right: 15px; left: 15px; display: grid; height: 42px; grid-template-columns: repeat(5, 1fr); align-items: center; pointer-events: none; }
    .effort-slider-mark { width: 3px; height: 3px; justify-self: center; border-radius: 50%; background: rgba(91,91,214,.28); transition: background .2s ease, box-shadow .2s ease, transform .2s ease; }
    .effort-slider-mark:first-child { justify-self: start; } .effort-slider-mark:last-child { justify-self: end; }
    .effort-slider-mark.is-active { background: rgba(255,255,255,.9); box-shadow: 0 0 0 1px rgba(91,91,214,.12); }
    .effort-slider-wrap.is-max .effort-slider-mark { background: rgba(255,255,255,.46); } .effort-slider-wrap.is-max .effort-slider-mark.is-active { background: #fff; box-shadow: 0 0 6px rgba(255,255,255,.95); transform: scale(1.08); }
    .effort-particles { position: absolute; z-index: 4; top: 10px; right: 1px; bottom: 9px; left: 1px; overflow: hidden; border-radius: 999px; opacity: 0; pointer-events: none; transition: opacity .24s ease; }
    .effort-slider-wrap.is-max .effort-particles { right: 30px; opacity: 1; }
    .effort-liquid { position: absolute; top: -4px; bottom: -4px; left: var(--liquid-start); display: block; width: 100%; will-change: transform; }
    .effort-slider-wrap.is-max .effort-liquid { animation: max-liquid-carry 8s linear infinite; }
    .effort-particle { position: absolute; z-index: 1; top: var(--y); left: var(--x); width: max(1px, calc(var(--size) + .2px)); height: max(1px, calc(var(--size) + .2px)); border-radius: 50%; background: rgba(255,255,255,.88); box-shadow: 0 0 2px rgba(255,255,255,.76), 0 0 4px rgba(222,202,255,.42); opacity: .74; }
    .effort-particle:nth-child(3n) { background: rgba(237,229,255,.8); }
    .effort-slider:focus-visible { outline: none; }
    .effort-slider:focus-visible::-webkit-slider-thumb { box-shadow: 0 0 0 3px rgba(91,91,214,.18), 0 3px 8px rgba(32,48,76,.18); }
    .effort-slider:focus-visible::-moz-range-thumb { box-shadow: 0 0 0 3px rgba(91,91,214,.18), 0 3px 8px rgba(32,48,76,.18); }
    @keyframes max-liquid-flow-right { from { background-position: 100% 50%; } to { background-position: 0% 50%; } }
    @keyframes max-liquid-carry { from { transform: translate3d(0, 0, 0); } to { transform: translate3d(100%, 0, 0); } }
    @media (prefers-reduced-motion: reduce) { .effort-slider-wrap.is-max::before, .effort-liquid { animation: none; } }
    .sr-only { position: absolute; width: 1px; height: 1px; overflow: hidden; clip: rect(0,0,0,0); clip-path: inset(50%); white-space: nowrap; }
/* 只隔离字体与盒模型，避免 Naive UI 和平台全局输入框规则覆盖参考样式。 */
.thinking-menu{box-sizing:border-box;width:min(272px,calc(100vw - 24px));font-family:Inter,"Segoe UI Variable Text","Microsoft YaHei UI","Microsoft YaHei",system-ui,sans-serif;line-height:1.5;color:#172033}
.thinking-menu *{box-sizing:border-box}.thinking-menu .effort-slider{padding:0;box-shadow:none;outline:none;border:0;border-radius:0}
.effort-slider-card[data-effort="xhigh"] .effort-slider-header strong{color:#5b5bd6}.effort-slider-card[data-effort="xhigh"] .effort-slider{--effort-start:#5b5bd6;--effort-end:#9d84f5;--effort-glow:rgba(91,91,214,.25)}
@media(prefers-reduced-motion:reduce){.thinking-trigger,.thinking-chevron,.thinking-dial::after,.effort-slider-mark{transition:none}}
</style>
