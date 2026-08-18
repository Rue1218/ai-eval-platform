<template>
  <div v-if="message" class="error-strip">
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="flex-shrink: 0; margin-top: 1px">
      <circle cx="12" cy="12" r="10"></circle>
      <line x1="12" y1="8" x2="12" y2="12"></line>
      <line x1="12" y1="16" x2="12.01" y2="16"></line>
    </svg>
    <div style="flex: 1">
      <div style="font-weight: 500">{{ message }}</div>
      <div v-if="details" style="font-size: 11px; margin-top: 4px; opacity: 0.85; font-family: var(--font-mono)">
        {{ typeof details === 'string' ? details : JSON.stringify(details) }}
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
defineProps<{
  message?: string
  details?: any
}>()
</script>
