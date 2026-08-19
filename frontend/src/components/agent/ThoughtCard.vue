<template>
  <div class="thought-card" :class="{ done, collapsed }">
    <div class="thought-head" @click="collapsed = !collapsed">
      <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
        <path d="M12 2a8 8 0 0 0-8 8c0 3 2 5.5 5 7v3h6v-3c3-1.5 5-4 5-7a8 8 0 0 0-8-8z"></path>
        <line x1="10" y1="22" x2="14" y2="22"></line>
      </svg>
      <span>思考过程</span>
      <span v-if="formattedLatency" class="thought-latency mono">{{ formattedLatency }}</span>
      <span class="chev">
        <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
          <polyline points="6 9 12 15 18 9"></polyline>
        </svg>
      </span>
    </div>
    <div class="thought-body">
      {{ text }}
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, watch, onMounted } from 'vue'
import { formatLatency } from '../../utils/format'

const props = defineProps<{
  text: string
  done?: boolean
  latencyMs?: number
}>()

const collapsed = ref(false)

const formattedLatency = computed(() => formatLatency(props.latencyMs))

// 思考完成 800ms 后平滑自动折叠
let collapseTimer: number | null = null

function triggerAutoCollapse() {
  if (collapseTimer) clearTimeout(collapseTimer)
  collapseTimer = window.setTimeout(() => {
    collapsed.value = true
  }, 800)
}

watch(
  () => props.done,
  (isDone) => {
    if (isDone) {
      triggerAutoCollapse()
    }
  },
)

onMounted(() => {
  if (props.done) {
    collapsed.value = true
  }
})
</script>

<style scoped>
.thought-card {
  border: 1px solid var(--border-subtle);
  border-radius: 14px;
  background: var(--bg-elevated);
  overflow: hidden;
  max-width: 92%;
  transition: opacity 0.5s ease;
  animation: msg-in 0.26s cubic-bezier(0.2, 0.9, 0.3, 1);
}
.thought-card.done {
  opacity: 0.85;
}
.thought-head {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 9px 14px;
  font-size: 12px;
  font-weight: 600;
  color: var(--c-agent, #10b981);
  cursor: pointer;
  user-select: none;
}
.thought-latency {
  font-size: 11px;
  font-weight: 500;
  color: var(--text-tertiary, #94a3b8);
  background: var(--bg-main, #0f172a);
  padding: 1px 6px;
  border-radius: 4px;
  margin-left: 2px;
}
.thought-body {
  padding: 0 14px 12px;
  font-size: 13px;
  color: var(--text-secondary);
  line-height: 1.7;
  white-space: pre-wrap;
}
.thought-card.collapsed .thought-body {
  display: none;
}
.thought-head .chev {
  margin-left: auto;
  transition: transform 0.18s ease;
  color: var(--text-tertiary);
  display: grid;
  place-items: center;
}
.thought-card.collapsed .chev {
  transform: rotate(-90deg);
}

.thought-card:not(.done) .thought-body::after {
  content: '';
  display: inline-block;
  width: 2px;
  height: 13px;
  background: var(--c-agent, #10b981);
  margin-left: 3px;
  vertical-align: -2px;
  animation: caret-blink 0.8s steps(2, jump-none) infinite;
}
@keyframes caret-blink {
  50% {
    opacity: 0;
  }
}
@keyframes msg-in {
  from {
    opacity: 0;
    transform: translateY(8px);
  }
  to {
    opacity: 1;
    transform: none;
  }
}
</style>
