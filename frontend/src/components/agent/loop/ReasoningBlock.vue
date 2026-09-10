<template>
  <details
    :open="expanded"
    class="reasoning-block"
    :class="{ 'is-ended': ended, 'is-interrupted': interrupted }"
    @toggle="toggle"
  >
    <summary class="reasoning-summary">
      <!-- 线性量子轨道/原子图标（类似图3效果） -->
      <span class="reasoning-icon-wrap" :class="{ 'is-thinking': !ended }">
        <svg
          class="thinking-atom-icon"
          viewBox="0 0 24 24"
          width="15"
          height="15"
          fill="none"
          stroke="currentColor"
          stroke-width="1.8"
          stroke-linecap="round"
          stroke-linejoin="round"
          aria-hidden="true"
        >
          <circle cx="12" cy="12" r="1.3" fill="currentColor" />
          <path d="M20.2 20.2c2.04-2.03.02-7.36-4.5-11.9-4.54-4.52-9.87-6.54-11.9-4.5-2.04 2.03-.02 7.36 4.5 11.9 4.54 4.52 9.87 6.54 11.9 4.5Z" />
          <path d="M15.7 15.7c4.52-4.54 6.54-9.87 4.5-11.9-2.03-2.04-7.36-.02-11.9 4.5-4.52 4.54-6.54 9.87-4.5 11.9 2.03 2.04 7.36.02 11.9-4.5Z" />
        </svg>
      </span>

      <!-- 状态文字：正在思考 / 思考 · 已结束 / 思考 · 已中断 -->
      <span class="reasoning-label">{{ statusLabel }}</span>

      <!-- 思考内容摘要预览（单行截断，折叠时展示，参考图1与图3） -->
      <span v-if="previewSnippet && !expanded" class="reasoning-preview">
        {{ previewSnippet }}
      </span>

      <!-- 状态指示（Live 徽标）与展开/折叠箭头 -->
      <div class="reasoning-meta">
        <span v-if="!ended" class="thinking-live" aria-label="思考流进行中">
          <span class="live-dot" />
          LIVE
        </span>
        <svg
          class="reasoning-chevron"
          :class="{ 'is-open': expanded }"
          viewBox="0 0 24 24"
          width="12"
          height="12"
          fill="none"
          stroke="currentColor"
          stroke-width="2.2"
          stroke-linecap="round"
          stroke-linejoin="round"
          aria-hidden="true"
        >
          <polyline points="6 9 12 15 18 9" />
        </svg>
      </div>
    </summary>

    <!-- 展开后的思考详情内容（无外边框、无底色背景） -->
    <div class="reasoning-content">
      <pre>{{ content }}</pre>
    </div>
  </details>
</template>

<script setup lang="ts">
import { ref, computed, watch } from 'vue'

const props = defineProps<{
  content: string
  ended: boolean
  interrupted?: boolean
}>()

const expanded = ref(!props.ended)
let manual = false
let automatic = false

/** 状态文案：未结束时展示“正在思考”，结束后展示“思考 · 已结束” */
const statusLabel = computed(() => {
  if (!props.ended) return '正在思考'
  if (props.interrupted) return '思考 · 已中断'
  return '思考 · 已结束'
})

/** 提取思考内容的单行精简摘要（参考图1与图3） */
const previewSnippet = computed(() => {
  if (!props.content) return ''
  const trimmed = props.content.trim()
  const firstLine = trimmed.split('\n').find(line => line.trim().length > 0) || ''
  return firstLine.trim()
})

/** 流结束自动折叠；用户已经手动展开时保留选择。 */
watch(
  () => props.ended,
  ended => {
    if (ended && !manual) {
      automatic = true
      expanded.value = false
    }
  }
)

function toggle(event: Event) {
  const open = (event.target as HTMLDetailsElement).open
  if (automatic) {
    automatic = false
  } else if (open !== expanded.value) {
    manual = true
  }
  expanded.value = open
}
</script>

<style scoped>
/* 思考区块：纯粹透气，去除外边框和背景底色（参考图1交互与图3无框底质感） */
.reasoning-block {
  margin: 4px 0 10px;
  padding: 0;
  border: none !important;
  background: transparent !important;
  color: var(--text-secondary, #64748b);
}

.reasoning-summary {
  display: flex;
  align-items: center;
  gap: 8px;
  cursor: pointer;
  user-select: none;
  list-style: none;
  outline: none;
  padding: 4px 0;
  min-height: 24px;
  font-size: 13px;
  line-height: 1.4;
  color: var(--text-secondary, #64748b);
  transition: color 0.15s ease;
}

.reasoning-summary::-webkit-details-marker,
.reasoning-summary::marker {
  display: none;
}

.reasoning-summary:hover {
  color: var(--text-primary, #1e293b);
}

/* 左侧线性原子/量子轨道图标（图3风格） */
.reasoning-icon-wrap {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
  width: 16px;
  height: 16px;
  color: #1f5947;
  transition: color 0.15s ease, transform 0.2s ease;
}

.reasoning-block.is-ended .reasoning-icon-wrap {
  color: var(--text-secondary, #64748b);
}

.reasoning-summary:hover .reasoning-icon-wrap {
  color: #1f5947;
}

/* 正在思考时图标缓慢自转，生动表达 AI 推理中 */
.reasoning-icon-wrap.is-thinking .thinking-atom-icon {
  animation: thinking-spin 4s linear infinite;
  transform-origin: center center;
}

@keyframes thinking-spin {
  from {
    transform: rotate(0deg);
  }
  to {
    transform: rotate(360deg);
  }
}

/* 状态标签 */
.reasoning-label {
  flex-shrink: 0;
  font-size: 13px;
  font-weight: 600;
  letter-spacing: -0.01em;
  color: #1f5947;
}

.reasoning-block.is-ended .reasoning-label {
  color: var(--text-secondary, #475569);
  font-weight: 500;
}

.reasoning-block.is-interrupted .reasoning-label {
  color: #d97706;
}

/* 思考内容单行摘要（折叠时展示） */
.reasoning-preview {
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-size: 12.5px;
  color: var(--text-tertiary, #94a3b8);
  font-family: inherit;
  margin-left: 2px;
}

/* 右侧元信息（LIVE 徽章与展开箭头） */
.reasoning-meta {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  margin-left: auto;
  flex-shrink: 0;
}

.thinking-live {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  font-size: 10px;
  font-weight: 700;
  color: #1f5947;
  background: #e6f4ee;
  padding: 1px 6px;
  border-radius: 4px;
  letter-spacing: 0.05em;
}

.live-dot {
  width: 5px;
  height: 5px;
  border-radius: 50%;
  background: #1f5947;
  animation: live-pulse 1.4s ease-in-out infinite;
}

@keyframes live-pulse {
  0%, 100% {
    opacity: 1;
    transform: scale(1);
  }
  50% {
    opacity: 0.35;
    transform: scale(0.75);
  }
}

.reasoning-chevron {
  color: var(--text-tertiary, #94a3b8);
  transition: transform 0.2s cubic-bezier(0.16, 1, 0.3, 1), color 0.15s ease;
}

.reasoning-summary:hover .reasoning-chevron {
  color: var(--text-primary, #334155);
}

.reasoning-chevron.is-open {
  transform: rotate(180deg);
}

/* 展开后的思考内容主体：无外边框、无底色背景，微缩进保持对齐 */
.reasoning-content {
  margin-top: 6px;
  padding: 6px 0 6px 24px;
  border: none;
  background: transparent;
}

.reasoning-content pre {
  margin: 0;
  padding: 0;
  border: none;
  background: transparent;
  font: inherit;
  font-size: 12.5px;
  line-height: 1.65;
  color: var(--text-secondary, #475569);
  white-space: pre-wrap;
  overflow-wrap: anywhere;
  max-height: 380px;
  overflow-y: auto;
}

/* 深色模式适配 */
[data-theme='dark'] .reasoning-icon-wrap {
  color: #34d399;
}

[data-theme='dark'] .reasoning-block.is-ended .reasoning-icon-wrap {
  color: #94a3b8;
}

[data-theme='dark'] .reasoning-label {
  color: #34d399;
}

[data-theme='dark'] .reasoning-block.is-ended .reasoning-label {
  color: #cbd5e1;
}

[data-theme='dark'] .reasoning-preview {
  color: #64748b;
}

[data-theme='dark'] .thinking-live {
  background: rgba(16, 185, 129, 0.15);
  color: #34d399;
}

[data-theme='dark'] .live-dot {
  background: #34d399;
}

[data-theme='dark'] .reasoning-content pre {
  color: #94a3b8;
}

@media (prefers-reduced-motion: reduce) {
  .thinking-atom-icon,
  .live-dot,
  .reasoning-chevron {
    animation: none !important;
    transition: none !important;
  }
}
</style>
