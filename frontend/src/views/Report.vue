<template>
  <n-card :title="`报告 ${route.params.id}`">
    <n-empty description="报告对比与分享在 M2 实现，见 PRD 5.2 / F-CM-02。" />
  </n-card>
</template>

<script setup lang="ts">
import { useRoute } from 'vue-router'
const route = useRoute()
</script>
