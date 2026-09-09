<template>
  <n-popover trigger="click" placement="top" :show-arrow="false">
    <template #trigger>
      <button class="loop-control meter" :aria-label="label" :title="label" type="button">
        <svg viewBox="0 0 36 36" aria-hidden="true">
          <circle class="meter-base" cx="18" cy="18" r="12" fill="none" stroke-width="3" />
          <circle
            v-for="segment in ringSegments"
            :key="segment.key"
            cx="18"
            cy="18"
            r="12"
            fill="none"
            stroke-width="3"
            :stroke="segment.color"
            :stroke-dasharray="`${segment.length} ${ringLength - segment.length}`"
            :stroke-dashoffset="-segment.offset"
            transform="rotate(-90 18 18)"
          />
        </svg>
        <span v-if="!meter">?</span>
      </button>
    </template>

    <section class="meter-detail" aria-label="实际请求上下文用量">
      <template v-if="meter">
        <header class="meter-header">
          <strong>上下文预计占用 {{ Math.round(percent) }}%</strong>
          <strong>{{ formatTokens(usedTokens) }} / {{ formatTokens(meter.capacity) }}</strong>
        </header>
        <div
          class="meter-progress"
          role="progressbar"
          aria-label="上下文预计占用"
          :aria-valuenow="Math.round(percent)"
          aria-valuemin="0"
          aria-valuemax="100"
        >
          <span
            v-for="segment in progressSegments"
            :key="segment.key"
            :style="{ width: `${segment.percent}%`, backgroundColor: segment.color }"
          />
        </div>
        <ul class="meter-breakdown">
          <li v-for="item in breakdownItems" :key="item.key">
            <span class="meter-dot" :style="{ backgroundColor: item.color }" />
            <span>{{ item.label }}</span>
            <strong>{{ formatTokens(item.tokens) }}</strong>
          </li>
        </ul>
        <p v-if="meter.reserved_output_tokens" class="meter-reserved">
          <span />输出预留<strong>{{ formatTokens(meter.reserved_output_tokens) }}</strong>
        </p>
        <small>
          {{ meter.basis === 'serialized_request.v2' ? '同源序列化估算 · 最近一次实际请求' : '历史请求未记录来源细分，输入已合并到对话消息' }}<br>
          不包含尚未发送的草稿
        </small>
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

const palette = {
  system_prompt: '#97a1af',
  conversation_messages: '#4d8df7',
  tools: '#9571f4',
  mcp: '#ea885f',
  skill: '#bd8a2d',
  memory_files: '#22a47b',
  reserved_output: '#d5dbe2',
} as const

const labels = {
  system_prompt: '系统提示词',
  conversation_messages: '对话消息',
  tools: '工具',
  mcp: 'MCP',
  skill: 'Skill',
  memory_files: '记忆文件',
} as const

const ringLength = 75.4
const usedTokens = computed(() => props.meter ? props.meter.input_tokens + props.meter.reserved_output_tokens : 0)
const percent = computed(() => props.meter?.capacity ? Math.min(100, usedTokens.value / props.meter.capacity * 100) : 0)
const label = computed(() => props.meter ? `上下文预计占用 ${Math.round(percent.value)}%（含输出预留）` : '上下文用量未知')
const breakdown = computed(() => props.meter?.breakdown ?? {
  system_prompt: 0,
  conversation_messages: props.meter?.input_tokens ?? 0,
  tools: 0,
  mcp: 0,
  skill: 0,
  memory_files: 0,
})
const breakdownItems = computed(() => Object.entries(labels).map(([key, label]) => ({
  key: key as keyof typeof labels,
  label,
  color: palette[key as keyof typeof labels],
  tokens: breakdown.value[key as keyof typeof labels],
})))
const progressSegments = computed(() => {
  if (!props.meter?.capacity) return []
  return [
    ...breakdownItems.value,
    { key: 'reserved_output', color: palette.reserved_output, tokens: props.meter.reserved_output_tokens },
  ].filter(item => item.tokens > 0).map(item => ({
    ...item,
    percent: Math.min(100, item.tokens / props.meter!.capacity * 100),
  }))
})
const ringSegments = computed(() => {
  let offset = 0
  return progressSegments.value.map(segment => {
    const length = ringLength * segment.percent / 100
    const result = { ...segment, length, offset }
    offset += length
    return result
  })
})

/** 使用 K/M 紧凑格式，和输入栏的小型信息密度保持一致。 */
function formatTokens(value: number): string {
  if (value >= 1_000_000) return `~${(value / 1_000_000).toFixed(value >= 10_000_000 ? 0 : 1)}M`
  if (value >= 1_000) return `~${(value / 1_000).toFixed(value >= 10_000 ? 0 : 1)}K`
  return value.toLocaleString()
}
</script>

<style scoped>
.meter{position:relative;width:28px;height:30px;justify-content:center;padding:0!important}.meter svg{width:21px;height:21px;overflow:visible}.meter-base{stroke:#e4e9e8}.meter>span{position:absolute;inset:6px;font-size:11px;line-height:18px}.meter-detail{width:min(280px,calc(100vw - 32px));padding:2px 1px}.meter-header{display:flex;align-items:baseline;justify-content:space-between;gap:12px;color:#303a48;font-size:12px;line-height:20px}.meter-header strong:last-child{font-variant-numeric:tabular-nums}.meter-progress{display:flex;overflow:hidden;height:4px;margin:8px 0 10px;border-radius:99px;background:#edf0f1}.meter-progress span{display:block;min-width:0;height:100%}.meter-breakdown{display:grid;gap:6px;margin:0;padding:0;list-style:none}.meter-breakdown li,.meter-reserved{display:grid;grid-template-columns:7px minmax(0,1fr) auto;align-items:center;column-gap:6px;color:#667385;font-size:12px;line-height:16px}.meter-dot,.meter-reserved>span{display:block;width:7px;height:7px;border-radius:2px}.meter-breakdown strong,.meter-reserved strong{color:#435064;font-variant-numeric:tabular-nums;font-weight:500}.meter-reserved{margin:8px 0 0;padding-top:7px;border-top:1px solid #edf0f1}.meter-reserved>span{background:#d5dbe2}.meter-detail small{display:block;margin-top:9px;color:#8994a1;font-size:10px;line-height:1.5}.meter-detail>p{margin:0;color:#6f7b89;font-size:12px}@media(max-width:560px){.meter-detail{width:min(260px,calc(100vw - 24px))}}
</style>
