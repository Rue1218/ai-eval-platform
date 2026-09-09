<template><n-popover trigger="click" placement="top"><template #trigger><button class="loop-control meter" :aria-label="label" :title="label"><svg viewBox="0 0 36 36" aria-hidden="true"><circle cx="18" cy="18" r="14" fill="none" stroke="#dfe8e4" stroke-width="3"/><circle v-if="meter" cx="18" cy="18" r="14" fill="none" :stroke="percent > 80 ? '#bd643d' : '#16977a'" stroke-width="3" :stroke-dasharray="`${percent * .88} 88`" transform="rotate(-90 18 18)"/></svg><span v-if="!meter">?</span></button></template><div class="meter-detail"><strong>实际请求上下文</strong><p>{{ label }}</p><template v-if="meter"><p>输入估算（含系统、工具、图文）：{{ meter.input_tokens.toLocaleString() }}</p><p>输出预留：{{ meter.reserved_output_tokens.toLocaleString() }}</p><p>容量：{{ meter.capacity.toLocaleString() }}</p><small>序列化估算 · 最近一次实际请求<br>不包含尚未发送的草稿</small></template><p v-else>尚无实际请求统计，当前用量未知。</p></div></n-popover></template>
<script setup lang="ts">
import { computed } from 'vue'
import { NPopover } from 'naive-ui'
import type { LoopMeter } from '../../../api/agentLoopTypes'
const props = defineProps<{ meter?: LoopMeter | null }>()
const percent = computed(() => props.meter ? Math.min(100, (props.meter.input_tokens + props.meter.reserved_output_tokens) / props.meter.capacity * 100) : 0)
const label = computed(() => props.meter ? `上下文预计占用 ${Math.round(percent.value)}%（含输出预留）` : '上下文用量未知')
</script>
<style scoped>.meter{position:relative;width:36px;height:36px;padding:2px!important}.meter svg{width:30px}.meter>span{position:absolute;inset:8px}.meter-detail{max-width:min(330px,calc(100vw - 50px))}</style>
