<template>
  <!-- 深度思考卡组件：支持流式脉冲、技能徽标、耗时与字数统计、Markdown 渲染与平滑自动折叠 -->
  <div class="thought-card" :class="{ done, collapsed }">
    <div class="thought-head" @click="toggleCollapse">
      <!-- 左侧图标：思考中为动态波纹呼吸光点，已完成为灵感星标 -->
      <div class="thought-icon-wrap">
        <span v-if="!done" class="thought-pulse-ring"></span>
        <svg v-if="!done" class="thought-spark-icon spinning" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
          <path d="M12 2v4M12 18v4M4.93 4.93l2.83 2.83M16.24 16.24l2.83 2.83M2 12h4M18 12h4M4.93 19.07l2.83-2.83M16.24 7.76l2.83-2.83" />
        </svg>
        <svg v-else class="thought-spark-icon" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
          <path d="M12 3c.132 0 .263 0 .393 0a7.5 7.5 0 0 0 7.92 12.446a9 9 0 1 1 -8.313 -12.454z" />
          <path d="M17 4a2 2 0 0 0 2 2a2 2 0 0 0 -2 2a2 2 0 0 0 -2 -2a2 2 0 0 0 2 -2" />
        </svg>
      </div>

      <!-- 思考状态标题 -->
      <span class="thought-title">{{ done ? '已思考' : '深度思考中...' }}</span>

      <!-- 关联技能徽标 -->
      <SkillBadge v-if="skillId" :skill-id="skillId" />

      <!-- 耗时徽章 -->
      <span v-if="formattedLatency" class="thought-badge mono" title="模型思考耗时">{{ formattedLatency }}</span>

      <!-- 字数徽章 -->
      <span v-if="text.length > 0" class="thought-badge mono" title="思考文本字数">{{ text.length }} 字</span>

      <!-- 右侧折叠指示箭头 -->
      <span class="chev" :class="{ open: !collapsed }">
        <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round">
          <polyline points="6 9 12 15 18 9"></polyline>
        </svg>
      </span>
    </div>

    <!-- 思考内容主体（支持 Markdown 语法与代码格式） -->
    <div v-show="!collapsed" class="thought-body">
      <div class="thought-guide-line">
        <MarkdownView :content="text" custom-class="thought-markdown" />
        <span v-if="!done" class="thought-cursor">▍</span>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, watch, onMounted } from 'vue'
import { formatLatency } from '../../utils/format'
import SkillBadge from './SkillBadge.vue'
import MarkdownView from './MarkdownView.vue'

const props = defineProps<{
  text: string
  done?: boolean
  latencyMs?: number
  skillId?: string | null
  stage?: string | null
}>()

const collapsed = ref(false)

const formattedLatency = computed(() => formatLatency(props.latencyMs))

function toggleCollapse() {
  collapsed.value = !collapsed.value
}

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
  border: 1px solid var(--border-subtle, rgba(255, 255, 255, 0.08));
  border-radius: 12px;
  background: var(--bg-elevated, rgba(30, 41, 59, 0.45));
  overflow: hidden;
  max-width: 88%;
  margin: 6px 0;
  transition: all 0.25s cubic-bezier(0.2, 0.9, 0.3, 1);
  box-shadow: 0 1px 4px rgba(0, 0, 0, 0.04);
}

.thought-card.done {
  border-color: var(--border-subtle, rgba(255, 255, 255, 0.06));
  background: var(--bg-elevated, rgba(30, 41, 59, 0.28));
}

.thought-card:not(.done) {
  border-color: color-mix(in srgb, var(--accent-ai, #10b981) 35%, transparent);
  box-shadow: 0 0 12px color-mix(in srgb, var(--accent-ai, #10b981) 8%, transparent);
}

.thought-head {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 12px;
  cursor: pointer;
  user-select: none;
  background: transparent;
  transition: background 0.15s ease;
}

.thought-head:hover {
  background: rgba(255, 255, 255, 0.03);
}

.thought-icon-wrap {
  position: relative;
  display: flex;
  align-items: center;
  justify-content: center;
  width: 18px;
  height: 18px;
  color: var(--accent-ai, #10b981);
}

.thought-spark-icon {
  width: 14px;
  height: 14px;
}

.thought-spark-icon.spinning {
  animation: slow-spin 4s linear infinite;
}

.thought-pulse-ring {
  position: absolute;
  width: 18px;
  height: 18px;
  border-radius: 50%;
  border: 1.5px solid var(--accent-ai, #10b981);
  animation: pulse-ring 1.8s cubic-bezier(0.215, 0.61, 0.355, 1) infinite;
}

.thought-title {
  font-size: 13px;
  font-weight: 600;
  color: var(--text-secondary, #94a3b8);
  letter-spacing: 0.2px;
}

.thought-card:not(.done) .thought-title {
  color: var(--accent-ai, #10b981);
}

.thought-badge {
  font-size: 11px;
  font-weight: 500;
  color: var(--text-tertiary, #64748b);
  background: var(--bg-main, rgba(15, 23, 42, 0.6));
  padding: 1.5px 6px;
  border-radius: 4px;
  border: 1px solid var(--border-subtle, rgba(255, 255, 255, 0.05));
}

.thought-head .chev {
  margin-left: auto;
  transition: transform 0.2s cubic-bezier(0.4, 0, 0.2, 1);
  color: var(--text-tertiary, #64748b);
  display: grid;
  place-items: center;
}

.thought-head .chev.open {
  transform: rotate(180deg);
}

.thought-body {
  padding: 4px 12px 12px;
  border-top: 1px dashed var(--border-subtle, rgba(255, 255, 255, 0.06));
}

.thought-guide-line {
  border-left: 2px solid color-mix(in srgb, var(--accent-ai, #10b981) 40%, transparent);
  padding-left: 10px;
  margin-top: 6px;
}

:deep(.thought-markdown) {
  font-size: 13.5px !important;
  line-height: 1.7 !important;
  color: var(--text-secondary, #94a3b8) !important;
}

:deep(.thought-markdown .md-p) {
  font-size: 13.5px !important;
  line-height: 1.7 !important;
  margin-bottom: 8px !important;
}

.thought-cursor {
  display: inline-block;
  color: var(--accent-ai, #10b981);
  animation: cursor-blink 0.9s step-end infinite;
  margin-left: 2px;
  font-size: 13px;
}

@keyframes slow-spin {
  from { transform: rotate(0deg); }
  to { transform: rotate(360deg); }
}

@keyframes pulse-ring {
  0% {
    transform: scale(0.6);
    opacity: 0.8;
  }
  50% {
    transform: scale(1.3);
    opacity: 0.15;
  }
  100% {
    transform: scale(1.6);
    opacity: 0;
  }
}

@keyframes cursor-blink {
  50% { opacity: 0; }
}
</style>
