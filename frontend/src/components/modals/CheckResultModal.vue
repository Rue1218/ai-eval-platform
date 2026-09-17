<template>
  <n-modal
    :show="show"
    preset="card"
    :trap-focus="false"
    :auto-focus="false"
    title="连通性检查结果"
    style="width: 440px"
    @update:show="$emit('update:show', $event)"
  >
    <div style="text-align: center; padding: 12px 0">
      <div v-if="result?.ok" style="color: var(--accent-success); margin-bottom: 12px">
        <svg width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="margin: 0 auto">
          <path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"></path>
          <polyline points="22 4 12 14.01 9 11.01"></polyline>
        </svg>
        <div style="font-size: 16px; font-weight: 600; margin-top: 8px">连接成功</div>
      </div>
      <div v-else style="color: var(--accent-error); margin-bottom: 12px">
        <svg width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="margin: 0 auto">
          <circle cx="12" cy="12" r="10"></circle>
          <line x1="15" y1="9" x2="9" y2="15"></line>
          <line x1="9" y1="9" x2="15" y2="15"></line>
        </svg>
        <div style="font-size: 16px; font-weight: 600; margin-top: 8px">测试未通过</div>
      </div>

      <div class="panel" style="text-align: left; background: var(--bg-elevated); font-size: 13px">
        <div class="row-between mb8">
          <span style="color: var(--text-secondary)">模型响应:</span>
          <span class="mono">{{ result?.model || '-' }}</span>
        </div>
        <div class="row-between mb8">
          <span style="color: var(--text-secondary)">接口延迟:</span>
          <span class="mono">{{ result?.latency_ms !== undefined ? result.latency_ms + ' ms' : '-' }}</span>
        </div>
        <div v-if="result?.message || result?.error" style="color: var(--accent-error); font-size: 12px; margin-top: 6px">
          错误信息: {{ result.message || result.error }}
        </div>
      </div>
    </div>

    <template #footer>
      <div style="display: flex; justify-content: flex-end">
        <n-button type="primary" @click="$emit('update:show', false)">确定</n-button>
      </div>
    </template>
  </n-modal>
</template>

<script setup lang="ts">
import type { ProfileCheckOut } from '../../api/types'

defineProps<{
  show: boolean
  result?: ProfileCheckOut | null
}>()

defineEmits<{
  (e: 'update:show', val: boolean): void
}>()
</script>
