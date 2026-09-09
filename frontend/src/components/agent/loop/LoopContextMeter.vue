<template>
  <n-popover trigger="click" placement="top" :show-arrow="false">
    <template #trigger>
      <button class="loop-control meter" :aria-label="label" :title="label" type="button">
        <svg viewBox="0 0 20 20" aria-hidden="true">
          <circle cx="10" cy="10" r="7" fill="none" stroke="#dfe8e4" stroke-width="2"/>
          <circle v-if="meter" cx="10" cy="10" r="7" fill="none" stroke="#587be8" stroke-width="2" :stroke-dasharray="`${percent * .44} 44`" transform="rotate(-90 10 10)"/>
        </svg>
        <span v-if="!meter">?</span>
      </button>
    </template>
    <section class="meter-detail" :aria-label="label">
      <template v-if="meter">
        <header class="meter-header">
          <strong>上下文已用 <b>{{ percent }}%</b></strong>
          <span>~{{ formatTokens(meter.input_tokens) }} / {{ formatTokens(meter.capacity) }}</span>
        </header>
        <div class="meter-track" role="progressbar" aria-label="实际请求上下文占用" :aria-valuenow="percent" aria-valuemin="0" aria-valuemax="100">
          <span v-for="segment in segments" :key="segment.key" class="meter-segment" :data-source="segment.key" :style="{ width: `${segment.percent}%`, background: segment.color }"/>
        </div>
        <div class="meter-legend">
          <div v-for="segment in segments" :key="segment.key" class="meter-row">
            <span class="meter-name"><i :style="{ background: segment.color }"/>{{ segment.label }}</span>
            <span>~{{ formatTokens(segment.tokens) }}</span>
          </div>
        </div>
        <footer>输出预留 ~{{ formatTokens(meter.reserved_output_tokens) }} · 最近一次实际请求</footer>
      </template>
      <p v-else>尚无实际请求统计，当前用量未知。</p>
    </section>
  </n-popover>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { NPopover } from 'naive-ui'
import type { LoopMeter } from '../../../api/agentLoopTypes'

const props = defineProps<{ meter?: LoopMeter | null }>()

/** 各段只计算实际发往模型的序列化内容，旧回合缺明细时归入对话消息。 */
const inputTokens = computed(() => props.meter?.input_tokens || 0)
const capacity = computed(() => Math.max(1, props.meter?.capacity || 1))
const percent = computed(() => Math.min(100, Math.max(0, Math.round(inputTokens.value / capacity.value * 100))))
const label = computed(() => props.meter ? `上下文已用 ${percent.value}%` : '上下文用量未知')
const hasBreakdown = computed(() => props.meter && [
  props.meter.system_tokens, props.meter.skills_tokens, props.meter.mcp_tokens,
  props.meter.tools_tokens, props.meter.conversation_tokens,
].some(value => value !== undefined))
const segments = computed(() => {
  const meter = props.meter
  const system = meter?.system_tokens || 0
  const skills = meter?.skills_tokens || 0
  const mcp = meter?.mcp_tokens || 0
  const tools = meter?.tools_tokens || 0
  const conversation = hasBreakdown.value ? meter?.conversation_tokens || 0 : inputTokens.value
  return [
    { key: 'system', label: '系统提示词', tokens: system, color: '#98a2b3' },
    { key: 'skill', label: 'Skill', tokens: skills, color: '#9b8afb' },
    { key: 'mcp', label: 'MCP', tokens: mcp, color: '#e6a23c' },
    { key: 'tools', label: '工具', tokens: tools, color: '#5f8fe8' },
    { key: 'conversation', label: '对话消息', tokens: conversation, color: '#7c9ff5' },
  ].map(segment => ({ ...segment, percent: Math.min(100, Math.max(0, segment.tokens / capacity.value * 100)) }))
})

/** 对齐截图的紧凑 K/M 格式；0 不伪装成近似值。 */
function formatTokens(tokens: number): string {
  if (!tokens) return '0'
  if (tokens >= 1_000_000) return `${(tokens / 1_000_000).toFixed(tokens % 1_000_000 ? 1 : 0)}M`
  if (tokens >= 1_000) return `${(tokens / 1_000).toFixed(1)}K`
  return tokens.toLocaleString()
}
</script>

<style scoped>
/* 触发器仅保留 18px 小圆环，避免占据输入栏操作位。 */
.meter{position:relative;width:26px;height:30px;justify-content:center;padding:0!important}.meter svg{width:18px;height:18px}.meter>span{position:absolute;inset:6px;display:grid;place-items:center;font-size:11px}.meter-detail{width:min(268px,calc(100vw - 28px));padding:12px 13px 10px;color:#344054}.meter-header{display:flex;align-items:baseline;justify-content:space-between;gap:12px;font-size:12px}.meter-header strong{font-weight:650}.meter-header b{color:#415b9c}.meter-header>span{color:#344054;font-family:ui-monospace,SFMono-Regular,Consolas,monospace;font-size:11px;font-weight:600;white-space:nowrap}.meter-track{display:flex;overflow:hidden;width:100%;height:4px;margin:9px 0 11px;border-radius:999px;background:#edf0f5}.meter-segment{display:block;min-width:0;height:100%;transition:width .2s ease}.meter-legend{display:grid;gap:7px}.meter-row{display:flex;align-items:center;justify-content:space-between;color:#536071;font-size:12px;line-height:1.2}.meter-name{display:flex;align-items:center;gap:7px}.meter-name i{display:block;width:7px;height:7px;border-radius:2px}.meter-row>span:last-child{font-family:ui-monospace,SFMono-Regular,Consolas,monospace;font-size:11px;color:#344054}footer{margin-top:10px;padding-top:8px;border-top:1px solid #eef1f4;color:#8a95a4;font-size:10px;line-height:1.35}@media(prefers-reduced-motion:reduce){.meter-segment{transition:none}}
</style>
