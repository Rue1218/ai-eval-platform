<template><details :open="expanded" class="reasoning" @toggle="toggle"><summary>思考 · {{ !ended ? '进行中' : interrupted ? '已中断' : '已结束' }}</summary><pre>{{ content }}</pre></details></template>
<script setup lang="ts">
import { ref, watch } from 'vue'
const props = defineProps<{ content: string; ended: boolean; interrupted?: boolean }>()
const expanded = ref(!props.ended)
let manual = false, automatic = false
/** 流结束自动折叠；用户已经手动展开时保留选择。 */
watch(() => props.ended, ended => { if (ended && !manual) { automatic = true; expanded.value = false } })
function toggle(event: Event) { const open = (event.target as HTMLDetailsElement).open; if (automatic) automatic = false; else if (open !== expanded.value) manual = true; expanded.value = open }
</script>
<style scoped>.reasoning{color:var(--text-secondary,#64748b);border-left:2px solid #a9cabc;padding:8px 14px;margin:8px 0}summary{cursor:pointer;font-size:13px}pre{white-space:pre-wrap;overflow-wrap:anywhere;font:inherit;font-size:13px;max-height:360px;overflow:auto}</style>
