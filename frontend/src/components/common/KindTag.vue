<template>
  <span class="kind-tag" :class="`kind-${kind}`">
    {{ label }}
  </span>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import type { TaskKind } from '../../api/types'

const props = defineProps<{
  kind: TaskKind | string
}>()

const kindLabels: Record<string, string> = {
  benchmark: '基准评测',
  rag: 'RAG 评测',
  testcase: '用例生成',
  stress: '压测',
}

const label = computed(() => kindLabels[props.kind] || props.kind)
</script>
