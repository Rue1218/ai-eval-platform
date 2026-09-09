<template><details v-if="value !== null && typeof value === 'object'" :open="depth < 1"><summary>{{ label || (Array.isArray(value) ? '数组' : '对象') }} · {{ Object.keys(value).length }}</summary><div class="json-children"><JsonTree v-for="(item, key) in value" :key="key" :value="item" :label="String(key)" :depth="depth + 1"/></div></details><div v-else class="json-leaf"><b v-if="label">{{ label }}: </b>{{ JSON.stringify(value) ?? '未提供' }}</div></template>
<script setup lang="ts">
/** 已授权 JSON 的递归树，不执行数据中的 HTML、脚本或 schema。 */
withDefaults(defineProps<{ value: any; label?: string; depth?: number }>(), { depth: 0 })
</script>
<style scoped>.json-children{padding-left:16px;border-left:1px solid #dbe4df}.json-leaf{white-space:pre-wrap;overflow-wrap:anywhere;padding:3px 0}summary{cursor:pointer;padding:4px 0}</style>
