<template>
  <div class="empty">
    <div class="empty-ico">
      <slot name="icon">
        <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">
          <circle cx="12" cy="12" r="10"></circle>
          <line x1="8" y1="12" x2="16" y2="12"></line>
        </svg>
      </slot>
    </div>
    <div style="font-size: 14px; font-weight: 500; color: var(--text-secondary)">{{ title || '暂无数据' }}</div>
    <div v-if="description" style="font-size: 12px; color: var(--text-tertiary); max-width: 320px">
      {{ description }}
    </div>
    <div v-if="$slots.action" style="margin-top: 10px">
      <slot name="action" />
    </div>
  </div>
</template>

<script setup lang="ts">
defineProps<{
  title?: string
  description?: string
}>()
</script>
