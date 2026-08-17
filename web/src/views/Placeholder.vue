<template>
  <n-card :title="route.meta?.title || '页面'">
    <n-empty description="该模块在后续里程碑（M2/M3/M4）中实现，见 PRD 5.2 / 5.3 / 5.6。" />
  </n-card>
</template>

<script setup>
import { useRoute } from 'vue-router'
const route = useRoute()
</script>
