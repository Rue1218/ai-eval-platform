<template>
  <n-popover v-model:show="open" trigger="click" placement="top" :show-arrow="false">
    <template #trigger><button ref="trigger" class="loop-control" type="button" :disabled="!allowed.length" @keydown.esc="close">思考 · {{ label }}</button></template>
    <section class="thinking-panel" @keydown.esc.stop.prevent="close" @wheel.prevent="wheel">
      <strong>{{ label }}</strong><p>{{ model }}</p>
      <p>{{ descriptions[modelValue || 'off'] }}</p>
      <input v-if="allowed.length > 1" type="range" min="0" :max="allowed.length - 1" step="1" :value="index" aria-label="思考强度" :aria-valuetext="label" @input="change(Number(($event.target as HTMLInputElement).value))" />
      <div class="thinking-ticks"><span v-for="effort in allowed" :key="effort">{{ labels[effort] }}</span></div>
      <small>随下一轮发送；当前请求配置保持不变。</small>
    </section>
  </n-popover>
</template>
<script setup lang="ts">
import { computed, ref } from 'vue'
import { NPopover } from 'naive-ui'
import type { Effort } from '../../../api/agentLoopTypes'
const props = defineProps<{ modelValue: Effort | null; allowed: Effort[]; model?: string }>()
const emit = defineEmits<{ 'update:modelValue': [Effort] }>()
const open = ref(false), trigger = ref<HTMLButtonElement>()
const labels: Record<Effort, string> = { off: '关闭', low: '轻量', medium: '标准', high: '深入', xhigh: '更深入', max: '最高' }
const descriptions: Record<Effort, string> = { off: '关闭额外思考。', low: '适合简单问题，较快响应。', medium: '兼顾推理深度与响应时间。', high: '为复杂分析投入更多思考。', xhigh: '进一步提高推理投入，响应可能更慢。', max: '使用当前模型允许的最高思考档位。' }
const index = computed(() => Math.max(0, props.allowed.indexOf(props.modelValue!)))
const label = computed(() => props.modelValue ? labels[props.modelValue] : '不可用')
/** 原生 range 提供方向键/Home/End；滚轮仅在弹层内响应。 */
function change(value: number) { const effort = props.allowed[Math.max(0, Math.min(props.allowed.length - 1, value))]; if (effort) emit('update:modelValue', effort) }
function wheel(event: WheelEvent) { if (event.deltaY) change(index.value + (event.deltaY < 0 ? 1 : -1)) }
function close() { open.value = false; trigger.value?.focus() }
</script>
<style scoped>
.thinking-panel{width:min(300px,calc(100vw - 48px));padding:8px}.thinking-panel p,.thinking-panel small{color:var(--text-secondary,#64748b)}input{width:100%;accent-color:#16977a}.thinking-ticks{display:flex;justify-content:space-between;margin:8px 0;font-size:12px}
</style>
