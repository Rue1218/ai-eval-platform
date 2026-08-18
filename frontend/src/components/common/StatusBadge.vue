<template>
  <span class="badge" :class="`badge-${status}`">
    <i class="bdot"></i>
    <span>{{ label }}</span>
  </span>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import type { TaskStatus } from '../../api/types'

const props = defineProps<{
  status: TaskStatus | string
}>()

const statusLabels: Record<string, string> = {
  queued: '排队中',
  running: '运行中',
  awaiting_case_confirm: '待用例确认',
  succeeded: '已成功',
  failed: '已失败',
  cancelled: '已取消',
}

const label = computed(() => statusLabels[props.status] || props.status)
</script>
