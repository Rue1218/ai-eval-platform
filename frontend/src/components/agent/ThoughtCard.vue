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
      <span class="thought-title">{{ titleText }}</span>

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

const titleText = computed(() => {
  const finished = !!props.done
  if (props.stage === 'plan') return finished ? '已规划' : '规划中'
  if (props.stage === 'reflect') return finished ? '已复核' : '复核中'
  if (props.stage === 'react' && props.skillId) {
    return finished ? '已使用技能' : '正在使用技能'
  }
  if (props.stage === 'react') return finished ? '已完成 ToolCall' : '正在 ToolCall'
  return finished ? '已思考' : '深度思考中...'
})

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
  border-radius: 10px;
  background: var(--bg-elevated, rgba(30, 41, 59, 0.45));
  overflow: hidden;
  max-width: 100%;
  width: 100%;
  margin: 6px 0 10px 0;
  box-sizing: border-box;
  transition: all 0.25s cubic-bezier(0.2, 0.9, 0.3, 1);
  box-shadow: 0 1px 4px rgba(0, 0, 0, 0.04);
}

.thought-card.collapsed {
  display: inline-flex;
  width: auto;
  max-width: 100%;
  margin: 2px 0 8px 0;
  border: none;
  background: transparent;
  box-shadow: none;
}

.thought-card.done {
  border-color: var(--border-subtle, rgba(255, 255, 255, 0.06));
  background: var(--bg-elevated, rgba(30, 41, 59, 0.28));
  opacity: 1;
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
  transition: background 0.15s ease, border-color 0.15s ease;
}

.thought-card.collapsed .thought-head {
  padding: 3px 8px;
  margin-left: -8px;
  gap: 6px;
  border-radius: 6px;
  border: 1px solid transparent;
}

.thought-head:hover {
  background: rgba(255, 255, 255, 0.03);
}

.thought-card.collapsed .thought-head:hover {
  background: var(--bg-elevated, rgba(255, 255, 255, 0.06));
  border-color: var(--border-subtle, rgba(255, 255, 255, 0.08));
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
  padding: 6px 14px 14px;
  border-top: 1px dashed var(--border-subtle, rgba(255, 255, 255, 0.06));
}

.thought-guide-line {
  border-left: 2px solid color-mix(in srgb, var(--accent-ai, #10b981) 35%, transparent);
  padding-left: 12px;
  margin-top: 6px;
}

/* 思考过程专用全局统一排版体系（全面覆盖 Markdown 各级元素，防止字号忽大忽小） */
:deep(.thought-markdown) {
  font-size: 12.5px !important;
  line-height: 1.65 !important;
  color: var(--text-secondary, #94a3b8) !important;
  letter-spacing: 0.01em;
}

:deep(.thought-markdown .md-p) {
  font-size: 12.5px !important;
  line-height: 1.65 !important;
  color: var(--text-secondary, #94a3b8) !important;
  margin-bottom: 6px !important;
}

:deep(.thought-markdown .md-p:last-child) {
  margin-bottom: 0 !important;
}

/* 思考过程标题收敛（微粗体，字号收敛至 13px，杜绝巨型标题） */
:deep(.thought-markdown .md-h1),
:deep(.thought-markdown .md-h2),
:deep(.thought-markdown .md-h3),
:deep(.thought-markdown .md-h4),
:deep(.thought-markdown .md-h5),
:deep(.thought-markdown .md-h6) {
  font-size: 13px !important;
  font-weight: 600 !important;
  line-height: 1.5 !important;
  color: var(--text-primary, #e2e8f0) !important;
  margin: 10px 0 4px !important;
  padding-bottom: 0 !important;
  border-bottom: none !important;
}

/* 思考过程列表统一（序号与圆点字号统一收敛为 12.5px） */
:deep(.thought-markdown .md-ul) {
  margin: 4px 0 6px 16px !important;
  padding: 0 !important;
}

:deep(.thought-markdown .md-li-bullet),
:deep(.thought-markdown .md-li-num) {
  font-size: 12.5px !important;
  line-height: 1.65 !important;
  color: var(--text-secondary, #94a3b8) !important;
  margin-bottom: 4px !important;
}

:deep(.thought-markdown .md-li-bullet::marker) {
  font-size: 11.5px !important;
  color: var(--accent-ai, #10b981) !important;
}

:deep(.thought-markdown .md-li-num::marker) {
  font-size: 12px !important;
  font-weight: 600 !important;
  color: var(--accent-ai, #10b981) !important;
}

/* 行内加粗与强调 */
:deep(.thought-markdown strong),
:deep(.thought-markdown b) {
  font-weight: 600 !important;
  color: var(--text-primary, #f1f5f9) !important;
}

:deep(.thought-markdown em),
:deep(.thought-markdown i) {
  color: var(--text-secondary, #cbd5e1) !important;
}

/* 思考过程行内代码块 */
:deep(.thought-markdown .md-inline-code) {
  font-size: 11.5px !important;
  padding: 1px 4px !important;
  border-radius: 4px !important;
  color: var(--accent-ai, #10b981) !important;
  background: rgba(16, 185, 129, 0.08) !important;
  border: 1px solid rgba(16, 185, 129, 0.2) !important;
}

/* 思考过程引用块 */
:deep(.thought-markdown .md-quote) {
  font-size: 12px !important;
  line-height: 1.5 !important;
  margin: 6px 0 !important;
  padding: 6px 10px !important;
  border-left: 2.5px solid var(--accent-ai, #10b981) !important;
  background: rgba(255, 255, 255, 0.02) !important;
  color: var(--text-tertiary, #64748b) !important;
}

/* 思考过程代码块卡片收敛 */
:deep(.thought-markdown .md-code-card) {
  margin: 6px 0 !important;
  font-size: 11.5px !important;
}

:deep(.thought-markdown .md-code-head) {
  padding: 4px 10px !important;
}

:deep(.thought-markdown .md-code-block) {
  padding: 8px 10px !important;
  font-size: 11.5px !important;
}

/* 思考过程表格收敛 */
:deep(.thought-markdown .md-table-wrap) {
  margin: 6px 0 !important;
}

:deep(.thought-markdown .md-table) {
  font-size: 11.5px !important;
}

:deep(.thought-markdown .md-th),
:deep(.thought-markdown .md-td) {
  padding: 4px 8px !important;
}

.thought-cursor {
  display: inline-block;
  color: var(--accent-ai, #10b981);
  animation: cursor-blink 0.9s step-end infinite;
  margin-left: 2px;
  font-size: 12px;
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

@media (max-width: 640px) {
  .thought-head {
    gap: 5px;
    padding: 6px 10px;
  }
  .thought-title {
    font-size: 12px;
  }
  .thought-badge {
    font-size: 10px;
    padding: 1px 4px;
  }
  .thought-body {
    padding: 4px 8px 10px;
  }
  :deep(.thought-markdown),
  :deep(.thought-markdown .md-p),
  :deep(.thought-markdown .md-li-bullet),
  :deep(.thought-markdown .md-li-num) {
    font-size: 11.5px !important;
  }
}
</style>
