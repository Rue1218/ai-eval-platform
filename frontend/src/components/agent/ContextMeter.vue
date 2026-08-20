<template>
  <!-- 上下文指示器（开发说明书 §8.1 / §16.6 冻结） -->
  <n-popover trigger="click" placement="bottom-end" :width="340">
    <template #trigger>
      <button class="context-meter-btn" type="button" title="点击查看当前会话上下文四段详情">
        <span class="meter-dot"></span>
        <span class="meter-label mono">
          上下文 消息 {{ m }} · 技能 {{ s }} · 摘要 {{ c }} · 余量 {{ r }} / {{ w }}
        </span>
      </button>
    </template>

    <div class="context-popover">
      <div class="popover-head">
        <span class="popover-title">模型上下文窗口剖析</span>
        <span class="popover-cap mono">{{ m }}/{{ w }} 条消息</span>
      </div>

      <div class="popover-sections">
        <!-- 1. 人设段落 -->
        <div class="popover-row">
          <div class="row-left">
            <span class="row-tag">人设</span>
            <span class="row-desc">系统不可变人设 (约 320 字符)</span>
          </div>
          <span class="row-status ok">常驻生效</span>
        </div>

        <!-- 2. 技能说明 -->
        <div class="popover-row">
          <div class="row-left">
            <span class="row-tag">技能</span>
            <span class="row-desc">当前规划激活技能</span>
          </div>
          <span class="row-status" :class="{ active: s > 0 }">{{ s > 0 ? '已注入 1 项' : '无激活' }}</span>
        </div>

        <!-- 3. 压缩摘要 -->
        <div class="popover-row">
          <div class="row-left">
            <span class="row-tag">摘要</span>
            <span class="row-desc">/compact 历史对话压缩摘要</span>
          </div>
          <span class="row-status" :class="{ active: c > 0 }">{{ c > 0 ? '已启用 (1条)' : '0 (未压缩)' }}</span>
        </div>
        <div v-if="compactSummary" class="popover-summary-box mono">
          {{ compactSummary }}
        </div>

        <!-- 4. 消息原文 -->
        <div class="popover-row">
          <div class="row-left">
            <span class="row-tag">消息</span>
            <span class="row-desc">窗口内有效消息原文</span>
          </div>
          <span class="row-status mono">{{ m }} 条</span>
        </div>

        <!-- 5. 余量 -->
        <div class="popover-row">
          <div class="row-left">
            <span class="row-tag">余量</span>
            <span class="row-desc">当前窗口可用消息槽位</span>
          </div>
          <span class="row-status mono">{{ r }} 条</span>
        </div>

        <!-- 6. 记忆文件 -->
        <div class="popover-row disabled">
          <div class="row-left">
            <span class="row-tag dim">记忆文件</span>
            <span class="row-desc">本产品无记忆文件</span>
          </div>
          <span class="row-status dim">未启用</span>
        </div>
      </div>
    </div>
  </n-popover>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { NPopover } from 'naive-ui'

export interface ContextMeterData {
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

const m = computed(() => props.meter?.messages ?? 0)
const s = computed(() => props.meter?.skills ?? 0)
const c = computed(() => props.meter?.summary ?? 0)
const r = computed(() => props.meter?.headroom ?? (20 - (props.meter?.messages ?? 0)))
const w = computed(() => props.meter?.window ?? 20)
</script>

<style scoped>
.context-meter-btn {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 4px 10px;
  background: var(--bg-elevated, rgba(255, 255, 255, 0.04));
  border: 1px solid var(--border-subtle, rgba(255, 255, 255, 0.08));
  border-radius: 8px;
  color: var(--text-secondary, #94a3b8);
  font-size: 11.5px;
  cursor: pointer;
  transition: all 0.15s ease;
  user-select: none;
}
.context-meter-btn:hover {
  border-color: var(--accent-ai, #10b981);
  color: var(--text-primary, #ffffff);
}

.meter-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: var(--accent-ai, #10b981);
  box-shadow: 0 0 6px rgba(16, 185, 129, 0.5);
}

.context-popover {
  padding: 4px 2px;
}
.popover-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding-bottom: 8px;
  margin-bottom: 8px;
  border-bottom: 1px solid var(--border-subtle, rgba(255, 255, 255, 0.08));
}
.popover-title {
  font-size: 12.5px;
  font-weight: 700;
  color: var(--text-primary, #ffffff);
}
.popover-cap {
  font-size: 11px;
  color: var(--accent-ai, #10b981);
}

.popover-sections {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.popover-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 4px 6px;
  border-radius: 6px;
  background: rgba(255, 255, 255, 0.02);
}
.row-left {
  display: flex;
  align-items: center;
  gap: 8px;
}
.row-tag {
  font-size: 10.5px;
  font-weight: 700;
  padding: 1px 5px;
  border-radius: 4px;
  background: rgba(255, 255, 255, 0.08);
  color: var(--text-primary, #ffffff);
}
.row-tag.dim {
  background: rgba(255, 255, 255, 0.04);
  color: var(--text-tertiary, #64748b);
}
.row-desc {
  font-size: 11.5px;
  color: var(--text-secondary, #94a3b8);
}

.row-status {
  font-size: 11px;
  color: var(--text-tertiary, #64748b);
}
.row-status.ok {
  color: #38bdf8;
}
.row-status.active {
  color: var(--accent-ai, #10b981);
  font-weight: 600;
}
.row-status.dim {
  color: var(--text-tertiary, #64748b);
}

.popover-summary-box {
  font-size: 11px;
  line-height: 1.5;
  color: var(--text-secondary, #94a3b8);
  background: #0f172a;
  border: 1px solid rgba(255, 255, 255, 0.06);
  border-radius: 6px;
  padding: 6px 8px;
  max-height: 80px;
  overflow-y: auto;
}
</style>
