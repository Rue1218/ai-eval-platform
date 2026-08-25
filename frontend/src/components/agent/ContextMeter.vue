<template>
  <!-- 双圆环上下文容量指示器与两层折叠 Popover 视图（纯圆环触发器，上弹卡片） -->
  <n-popover trigger="click" placement="top-start" raw :show-arrow="false" :style="{ width: 'min(340px, calc(100vw - 24px))' }">
    <template #trigger>
      <button
        class="context-ring-btn"
        type="button"
        :title="`上下文窗口：${formattedTotalTokens} / ${formattedMaxTokens} (${clampedPercent.toFixed(1)}%)`"
      >
        <svg class="ring-svg" viewBox="0 0 36 36">
          <!-- 底层浅灰背景环 -->
          <circle class="ring-bg" cx="18" cy="18" r="14" />
          <!-- 上层动态彩色进度环 -->
          <circle
            class="ring-fill"
            cx="18"
            cy="18"
            r="14"
            :stroke="activeColor"
            :stroke-dasharray="strokeDasharray"
            :stroke-dashoffset="strokeDashoffset"
          />
        </svg>
      </button>
    </template>

    <!-- 弹窗容器 -->
    <div class="context-popover-card">
      <!-- 头部：上下文窗口 + 已用量 / 上限 + （当前上下文） + 折叠箭头（点击可展开/折叠） -->
      <div class="popover-header" @click="isExpanded = !isExpanded">
        <span class="header-title">
          上下文窗口
          <span v-if="isCompacted" class="compacted-badge">已压缩</span>
        </span>
        <div class="header-right">
          <span class="header-tokens mono">{{ formattedTotalTokens }} / {{ formattedMaxTokens }}</span>
          <span class="header-sub">（当前上下文）</span>
          <svg
            class="chevron-icon"
            :class="{ expanded: isExpanded }"
            width="13"
            height="13"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            stroke-width="2.2"
            stroke-linecap="round"
            stroke-linejoin="round"
          >
            <polyline points="9 18 15 12 9 6" />
          </svg>
        </div>
      </div>

      <!-- 横向彩色进度条（三色健康度阶梯联动：<50% #2F8DEA, 50-80% #EA9B2C, >=80% #D03B3B） -->
      <div class="progress-bar-track">
        <div
          class="progress-bar-fill"
          :style="{ width: `${clampedPercent}%`, background: activeColor }"
        ></div>
      </div>

      <!-- 第 2 层：展开细分明细（参考图片 2） -->
      <transition name="expand">
        <div v-if="isExpanded" class="detail-section">
          <!-- 1. Messages 消息 -->
          <div class="detail-row">
            <div class="row-left">
              <span class="color-box" :style="{ background: activeColor }"></span>
              <span class="row-name">Messages</span>
            </div>
            <div class="row-right mono">
              <span class="token-num">{{ formattedMessagesTokens }}</span>
              <span class="token-pct">{{ messagesPercent.toFixed(1) }}%</span>
            </div>
          </div>

          <!-- 2. Skills 技能 -->
          <div class="detail-row">
            <div class="row-left">
              <span class="color-box" :style="{ background: activeColor }"></span>
              <span class="row-name">Skills</span>
            </div>
            <div class="row-right mono">
              <span class="token-num">{{ formattedSkillsTokens }}</span>
              <span class="token-pct">{{ skillsPercent.toFixed(1) }}%</span>
            </div>
          </div>

          <!-- 3. Free space 剩余可用空间 -->
          <div class="detail-row">
            <div class="row-left">
              <span class="color-box box-empty"></span>
              <span class="row-name">Free space</span>
            </div>
            <div class="row-right mono">
              <span class="token-num">{{ formattedFreeTokens }}</span>
              <span class="token-pct">{{ freePercent.toFixed(1) }}%</span>
            </div>
          </div>

          <!-- 4. MCP工具 -->
          <div class="detail-row sub-row">
            <div class="row-left">
              <span class="sub-arrow">›</span>
              <span class="row-name">MCP工具</span>
            </div>
            <div class="row-right mono">
              <span class="token-num">{{ mcpToolsCount }}</span>
              <span class="token-max">{{ mcpToolsMax }}</span>
            </div>
          </div>

          <!-- 5. 记忆文件 -->
          <div class="detail-row sub-row">
            <div class="row-left">
              <span class="sub-arrow">›</span>
              <span class="row-name">记忆文件</span>
            </div>
            <div class="row-right mono">
              <span class="token-num">{{ memoryFilesCount }}</span>
              <span class="token-max">{{ memoryFilesMax }}</span>
            </div>
          </div>
        </div>
      </transition>
    </div>
  </n-popover>
</template>

<script setup lang="ts">
import { ref, computed } from 'vue'
import { NPopover } from 'naive-ui'

export interface ContextMeterData {
  // Token 级度量
  total_tokens?: number
  max_tokens?: number
  messages_tokens?: number
  skills_tokens?: number
  free_tokens?: number
  used_percent?: number
  messages_percent?: number
  skills_percent?: number
  free_percent?: number
  mcp_tools_count?: number
  mcp_tools_max?: number
  memory_files_count?: number
  memory_files_max?: number
  compacted?: boolean

  // 兼容旧版消息条数字段
  messages?: number
  skills?: number
  summary?: number
  headroom?: number
  window?: number
}

const props = defineProps<{
  meter?: ContextMeterData | null
  compactSummary?: string | null
}>()

// 是否展开第 2 层细分视图
const isExpanded = ref(true)

// SVG 双圆环周长计算 (r = 14 -> 2 * PI * 14 = 87.9646)
const CIRCUMFERENCE = 87.9646
const strokeDasharray = `${CIRCUMFERENCE} ${CIRCUMFERENCE}`

// CX-7：只读服务端数字，禁止按 messages 条数估算（如 4200/条）。
const maxTokens = computed(() => props.meter?.max_tokens ?? 0)
const totalTokens = computed(() => props.meter?.total_tokens ?? 0)
const messagesTokens = computed(() => props.meter?.messages_tokens ?? 0)
const skillsTokens = computed(() => props.meter?.skills_tokens ?? 0)
const freeTokens = computed(() => props.meter?.free_tokens ?? 0)
const usedPercent = computed(() => props.meter?.used_percent ?? 0)
const clampedPercent = computed(() => Math.min(100, Math.max(0, usedPercent.value)))
const messagesPercent = computed(() => props.meter?.messages_percent ?? 0)
const skillsPercent = computed(() => props.meter?.skills_percent ?? 0)
const freePercent = computed(() => props.meter?.free_percent ?? Math.max(0, 100 - clampedPercent.value))

// 工具与记忆资源项
const mcpToolsCount = computed(() => props.meter?.mcp_tools_count ?? 0)
const mcpToolsMax = computed(() => props.meter?.mcp_tools_max ?? 28)
const memoryFilesCount = computed(() => props.meter?.memory_files_count ?? 0)
const memoryFilesMax = computed(() => props.meter?.memory_files_max ?? 1)

// SVG stroke-dashoffset 计算（从 0 到 CIRCUMFERENCE）
const strokeDashoffset = computed(() => {
  const ratio = clampedPercent.value / 100
  return CIRCUMFERENCE * (1 - ratio)
})

/**
 * 动态三色健康度阶梯：
 * < 50%：蓝色 #2F8DEA
 * 50% - 80%：橙色 #EA9B2C
 * >= 80%：红色 #D03B3B
 */
const activeColor = computed(() => {
  const pct = clampedPercent.value
  if (pct < 50) return '#2F8DEA'
  if (pct < 80) return '#EA9B2C'
  return '#D03B3B'
})

// 格式化 Token 数字显示（支持规范的 XXX.X k / XXX.X M 格式）
function formatTokens(val: number): string {
  if (val >= 1000000) {
    const m = val / 1000000
    return m % 1 === 0 ? `${m.toFixed(0)}M` : `${m.toFixed(1)}M`
  }
  const k = val / 1000
  if (k < 10) {
    return `${k.toFixed(1)}k`
  }
  return k % 1 === 0 ? `${k.toFixed(0)}k` : `${k.toFixed(1)}k`
}

const formattedTotalTokens = computed(() => formatTokens(totalTokens.value))
const formattedMaxTokens = computed(() => formatTokens(maxTokens.value))
const formattedMessagesTokens = computed(() => formatTokens(messagesTokens.value))
const formattedSkillsTokens = computed(() => formatTokens(skillsTokens.value))
const formattedFreeTokens = computed(() => formatTokens(freeTokens.value))
const isCompacted = computed(() => Boolean(props.meter?.compacted || props.compactSummary))
</script>

<style scoped>
/* 双圆环触发按钮（紧凑纯圆环小按钮） */
.context-ring-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 22px;
  height: 22px;
  padding: 0;
  background: transparent;
  border: 1px solid transparent;
  border-radius: 50%;
  cursor: pointer;
  transition: all 0.15s ease;
  user-select: none;
  flex-shrink: 0;
}

.context-ring-btn:hover {
  background: var(--bg-hover, rgba(0, 0, 0, 0.05));
  border-color: var(--border-subtle, rgba(0, 0, 0, 0.08));
  transform: scale(1.05);
}

[data-theme='dark'] .context-ring-btn:hover {
  background: rgba(255, 255, 255, 0.08);
  border-color: rgba(255, 255, 255, 0.15);
}

.ring-svg {
  width: 15px;
  height: 15px;
  display: block;
}

.ring-bg {
  fill: none;
  stroke: #cbd5e1;
  stroke-width: 4.2;
}

[data-theme='dark'] .ring-bg {
  stroke: rgba(255, 255, 255, 0.18);
}

.ring-fill {
  fill: none;
  stroke-width: 4.2;
  stroke-linecap: round;
  transform: rotate(-90deg);
  transform-origin: 50% 50%;
  transition: stroke-dashoffset 0.35s ease, stroke 0.3s ease;
}

/* 弹窗卡片 */
.context-popover-card {
  background: var(--bg-main, #ffffff);
  border: 1px solid var(--border-subtle, #e5e7eb);
  border-radius: 10px;
  padding: 12px 14px;
  box-shadow: 0 8px 24px -4px rgba(0, 0, 0, 0.12), 0 2px 6px -1px rgba(0, 0, 0, 0.06);
  color: var(--text-primary, #1e293b);
  user-select: none;
}

[data-theme='dark'] .context-popover-card {
  background: #1e293b;
  border-color: rgba(255, 255, 255, 0.12);
  color: #f1f5f9;
}

/* 头部 */
.popover-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  cursor: pointer;
  padding-bottom: 8px;
}

.header-title {
  font-size: 13px;
  font-weight: 600;
  color: var(--text-primary, #1e293b);
  display: inline-flex;
  align-items: center;
  gap: 6px;
}

.compacted-badge {
  font-size: 10px;
  font-weight: 600;
  color: #0f766e;
  background: rgba(15, 118, 110, 0.1);
  border-radius: 999px;
  padding: 1px 6px;
}

[data-theme='dark'] .header-title {
  color: #f8fafc;
}

[data-theme='dark'] .compacted-badge {
  color: #5eead4;
  background: rgba(45, 212, 191, 0.16);
}

.header-right {
  display: flex;
  align-items: center;
  gap: 4px;
  color: var(--text-secondary, #64748b);
}

.header-tokens {
  font-size: 13px;
  font-weight: 600;
  color: var(--text-primary, #1e293b);
}

[data-theme='dark'] .header-tokens {
  color: #f8fafc;
}

.header-sub {
  font-size: 11px;
  color: var(--text-tertiary, #94a3b8);
}

.chevron-icon {
  color: var(--text-tertiary, #94a3b8);
  transition: transform 0.2s ease;
  margin-left: 2px;
}

.chevron-icon.expanded {
  transform: rotate(90deg);
}

/* 横向彩色进度条 */
.progress-bar-track {
  width: 100%;
  height: 4px;
  background: #f1f5f9;
  border-radius: 2px;
  overflow: hidden;
  margin-bottom: 10px;
}

[data-theme='dark'] .progress-bar-track {
  background: rgba(255, 255, 255, 0.08);
}

.progress-bar-fill {
  height: 100%;
  border-radius: 2px;
  transition: width 0.35s ease, background 0.3s ease;
}

/* 明细列表 */
.detail-section {
  display: flex;
  flex-direction: column;
  gap: 6px;
  padding-top: 4px;
}

.detail-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  font-size: 12px;
  line-height: 1.4;
}

.row-left {
  display: flex;
  align-items: center;
  gap: 7px;
}

.color-box {
  width: 8px;
  height: 8px;
  min-width: 8px;
  min-height: 8px;
  border-radius: 2px;
  flex-shrink: 0;
  display: inline-block;
  box-sizing: border-box;
  padding: 0 !important;
  margin: 0 !important;
}

.color-box.box-empty {
  background: #e2e8f0;
}

[data-theme='dark'] .color-box.box-empty {
  background: rgba(255, 255, 255, 0.2);
}

.row-name {
  color: var(--text-primary, #334155);
  font-size: 12px;
}

[data-theme='dark'] .row-name {
  color: #cbd5e1;
}

.row-right {
  display: flex;
  align-items: center;
  gap: 12px;
  font-size: 12px;
}

.token-num {
  color: var(--text-secondary, #64748b);
  min-width: 44px;
  text-align: right;
}

.token-pct {
  color: var(--text-primary, #1e293b);
  font-weight: 600;
  min-width: 40px;
  text-align: right;
}

[data-theme='dark'] .token-pct {
  color: #f1f5f9;
}

/* 子行（MCP / 记忆文件） */
.sub-row {
  color: var(--text-secondary, #64748b);
}

.sub-arrow {
  color: var(--text-tertiary, #94a3b8);
  font-size: 12px;
  font-weight: 700;
  margin-left: 1px;
}

.sub-row .row-name {
  color: var(--text-secondary, #64748b);
}

.token-max {
  color: var(--text-tertiary, #94a3b8);
  min-width: 24px;
  text-align: right;
}

/* 过渡动画 */
.expand-enter-active,
.expand-leave-active {
  transition: all 0.2s ease-out;
  max-height: 200px;
  overflow: hidden;
}

.expand-enter-from,
.expand-leave-to {
  opacity: 0;
  max-height: 0;
  transform: translateY(-4px);
}
</style>
