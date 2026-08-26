<template>
  <div v-if="hasTaskState" class="task-state-drawer" :class="{ 'is-expanded': isExpanded, 'is-running': isRunning }">
    <!-- 抽屉头部卡条（紧凑态，点击展开/收起） -->
    <div class="drawer-header" @click="toggleExpand">
      <div class="header-left">
        <!-- 动态状态呼吸灯 / 状态图标 -->
        <span class="status-indicator" :class="phaseClass">
          <span class="indicator-dot"></span>
        </span>
        <span class="drawer-title mono">TASK BOARD</span>
        <span class="goal-text" :title="taskGoal">{{ taskGoal }}</span>
        <span class="progress-pill mono">{{ completedCount }}/{{ totalStepsCount }}</span>
      </div>

      <div class="header-right">
        <!-- 当前正在进行的步骤缩略展示（收起态可见） -->
        <div v-if="!isExpanded && activeStepText" class="current-step-preview">
          <span class="spinner-icon"></span>
          <span class="step-preview-label">{{ activeStepText }}</span>
        </div>

        <button type="button" class="drawer-toggle-btn" :title="isExpanded ? '收起任务看板' : '展开任务看板'">
          <svg class="chevron" :class="{ 'rotate-180': isExpanded }" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round">
            <polyline points="6 9 12 15 18 9"></polyline>
          </svg>
        </button>
      </div>
    </div>

    <!-- 抽屉展开主体内容 -->
    <transition name="drawer-expand">
      <div v-if="isExpanded" class="drawer-body">
        <!-- 任务步骤列表（严格对齐格式：task 1 ：XXXXX） -->
        <div class="task-list">
          <div
            v-for="(item, idx) in formattedTasks"
            :key="idx"
            class="task-item"
            :class="`status-${item.status}`"
          >
            <div class="task-status-icon">
              <!-- 成功状态：绿色对勾 -->
              <svg v-if="item.status === 'completed'" class="icon-completed" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
                <path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"></path>
                <polyline points="22 4 12 14.01 9 11.01"></polyline>
              </svg>

              <!-- 执行中状态：动态旋转加载图标 -->
              <svg v-else-if="item.status === 'running'" class="icon-running" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
                <line x1="12" y1="2" x2="12" y2="6"></line>
                <line x1="12" y1="18" x2="12" y2="22"></line>
                <line x1="4.93" y1="4.93" x2="7.76" y2="7.76"></line>
                <line x1="16.24" y1="16.24" x2="19.07" y2="19.07"></line>
                <line x1="2" y1="12" x2="6" y2="12"></line>
                <line x1="18" y1="12" x2="22" y2="12"></line>
                <line x1="4.93" y1="19.07" x2="7.76" y2="16.24"></line>
                <line x1="16.24" y1="7.76" x2="19.07" y2="4.93"></line>
              </svg>

              <!-- 失败状态：红色告警 -->
              <svg v-else-if="item.status === 'failed'" class="icon-failed" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
                <circle cx="12" cy="12" r="10"></circle>
                <line x1="15" y1="9" x2="9" y2="15"></line>
                <line x1="9" y1="9" x2="15" y2="15"></line>
              </svg>

              <!-- 待执行状态：灰色空心圆 -->
              <svg v-else class="icon-pending" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                <circle cx="12" cy="12" r="9"></circle>
                <polyline points="12 6 12 12 14 14"></polyline>
              </svg>
            </div>

            <!-- 内容格式：“task 1 ：XXXXX” -->
            <div class="task-content">
              <span class="task-line-text">{{ item.labelText }}</span>
              <span v-if="item.failReason" class="task-fail-hint">{{ item.failReason }}</span>
            </div>

            <div class="task-badge">
              <span class="status-tag" :class="item.status">{{ item.statusLabel }}</span>
            </div>
          </div>
        </div>

        <!-- 事实证据与关键信息缺口卡条（如果存在） -->
        <div v-if="evidenceCount > 0 || missingCount > 0 || rejectedCount > 0" class="drawer-footer-chips">
          <span v-if="evidenceCount > 0" class="meta-badge badge-evidence" :title="evidenceTooltip">
            📌 已沉淀证据 {{ evidenceCount }} 项
          </span>
          <span v-if="rejectedCount > 0" class="meta-badge badge-rejected" :title="rejectedTooltip">
            ❌ 已排除方向 {{ rejectedCount }} 项
          </span>
          <span v-if="missingCount > 0" class="meta-badge badge-missing" :title="missingTooltip">
            ⏳ 待探查缺口 {{ missingCount }} 项
          </span>
        </div>
      </div>
    </transition>
  </div>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue'
import type { PlanArtifact, TaskSessionState } from '../../api/types'

const props = defineProps<{
  plan?: PlanArtifact | null
  isGenerating?: boolean
}>()

// 抽屉默认展开，方便直观了解多步任务动态
const isExpanded = ref(true)

function toggleExpand() {
  isExpanded.value = !isExpanded.value
}

// 提取内嵌的 TaskSessionState
const taskState = computed<TaskSessionState | null>(() => {
  const slots = props.plan?.slots || {}
  const rawState = slots.task_state as Record<string, unknown> | undefined
  if (rawState && typeof rawState === 'object') {
    return {
      goal: String(rawState.goal || props.plan?.intent || '分析评测任务'),
      phase: (rawState.phase as any) || 'exploring',
      completed_steps: Array.isArray(rawState.completed_steps) ? rawState.completed_steps.map(String) : [],
      current_step: String(rawState.current_step || ''),
      next_actions: Array.isArray(rawState.next_actions) ? rawState.next_actions.map(String) : [],
      failed_steps: Array.isArray(rawState.failed_steps) ? (rawState.failed_steps as any) : [],
      current_hypothesis: rawState.current_hypothesis ? String(rawState.current_hypothesis) : undefined,
      confirmed_facts: Array.isArray(rawState.confirmed_facts) ? rawState.confirmed_facts.map(String) : [],
      evidence: Array.isArray(rawState.evidence) ? rawState.evidence.map(String) : [],
      rejected_hypotheses: Array.isArray(rawState.rejected_hypotheses) ? (rawState.rejected_hypotheses as any) : [],
      missing_info: Array.isArray(rawState.missing_info) ? rawState.missing_info.map(String) : [],
      can_deliver: rawState.can_deliver === true,
      notes: rawState.notes ? String(rawState.notes) : undefined,
    }
  }
  return null
})

// 判断是否存在看板可展示内容
const hasTaskState = computed(() => {
  if (!props.plan) return false
  const steps = props.plan.slots?.steps
  return Array.isArray(steps) && steps.length > 0
})

const isRunning = computed(() => props.isGenerating)

const taskGoal = computed(() => {
  return taskState.value?.goal || props.plan?.intent || '执行评测规划'
})

const phaseClass = computed(() => {
  if (!isRunning.value && (taskState.value?.can_deliver || completedCount.value === totalStepsCount.value)) {
    return 'phase-completed'
  }
  if (taskState.value?.phase === 'verifying') return 'phase-verifying'
  return isRunning.value ? 'phase-running' : 'phase-idle'
})

interface TaskItemDisplay {
  index: number
  labelText: string // 格式：“task 1 ：XXXXX”
  status: 'completed' | 'running' | 'failed' | 'pending'
  statusLabel: string
  failReason?: string
}

// 格式化全部任务步骤列表
const formattedTasks = computed<TaskItemDisplay[]>(() => {
  if (!props.plan) return []
  const rawSteps: string[] = Array.isArray(props.plan.slots?.steps)
    ? (props.plan.slots.steps as any[]).map(String)
    : []

  const completed = new Set(taskState.value?.completed_steps || [])
  const failedMap = new Map((taskState.value?.failed_steps || []).map((f) => [f.step, f.reason]))
  const currentStep = taskState.value?.current_step || ''

  // 若无细分 taskState，推导当前执行步骤：首个未完成的为 running
  let foundRunning = false

  return rawSteps.map((step, idx) => {
    let status: 'completed' | 'running' | 'failed' | 'pending' = 'pending'
    let failReason = ''

    if (completed.has(step)) {
      status = 'completed'
    } else if (failedMap.has(step)) {
      status = 'failed'
      failReason = failedMap.get(step) || ''
    } else if (step === currentStep || (!foundRunning && isRunning.value)) {
      status = 'running'
      foundRunning = true
    } else {
      status = 'pending'
    }

    // 若整体已经生成完成且 can_deliver，所有未标记失败的都收敛为完成
    if (!isRunning.value && taskState.value?.can_deliver && status !== 'failed') {
      status = 'completed'
    }

    const statusLabelMap = {
      completed: '已完成',
      running: '执行中',
      failed: '失败',
      pending: '待执行',
    }

    return {
      index: idx + 1,
      // 用户核心指定格式：task 1 ：XXXXX
      labelText: `task ${idx + 1} ：${step}`,
      status,
      statusLabel: statusLabelMap[status],
      failReason,
    }
  })
})

const completedCount = computed(() => {
  return formattedTasks.value.filter((t) => t.status === 'completed').length
})

const totalStepsCount = computed(() => {
  return formattedTasks.value.length
})

const activeStepText = computed(() => {
  const active = formattedTasks.value.find((t) => t.status === 'running')
  return active ? active.labelText : ''
})

const evidenceCount = computed(() => taskState.value?.evidence?.length || 0)
const missingCount = computed(() => taskState.value?.missing_info?.length || 0)
const rejectedCount = computed(() => taskState.value?.rejected_hypotheses?.length || 0)

const evidenceTooltip = computed(() => (taskState.value?.evidence || []).join('；'))
const missingTooltip = computed(() => (taskState.value?.missing_info || []).join('；'))
const rejectedTooltip = computed(() =>
  (taskState.value?.rejected_hypotheses || []).map((h) => `${h.hypothesis}(${h.reason})`).join('；')
)
</script>

<style scoped>
.task-state-drawer {
  background: var(--bg-main, #ffffff);
  border: 1px solid var(--border-subtle, rgba(229, 231, 235, 0.8));
  border-radius: 12px;
  box-shadow: 0 4px 16px rgba(0, 0, 0, 0.05);
  margin-bottom: 8px;
  overflow: hidden;
  transition: all 0.25s cubic-bezier(0.2, 0.9, 0.3, 1);
}

.task-state-drawer.is-running {
  border-color: rgba(16, 185, 129, 0.35);
  box-shadow: 0 4px 20px rgba(16, 185, 129, 0.08);
}

/* 抽屉头部卡条 */
.drawer-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 8px 14px;
  background: var(--bg-elevated, #f9fafb);
  cursor: pointer;
  user-select: none;
  border-bottom: 1px solid transparent;
  transition: background 0.2s ease;
}

.task-state-drawer.is-expanded .drawer-header {
  border-bottom-color: var(--border-subtle, rgba(229, 231, 235, 0.6));
}

.drawer-header:hover {
  background: var(--bg-hover, #f3f4f6);
}

.header-left {
  display: flex;
  align-items: center;
  gap: 8px;
  overflow: hidden;
}

.status-indicator {
  position: relative;
  width: 8px;
  height: 8px;
  border-radius: 50%;
  display: inline-block;
  flex-shrink: 0;
}

.status-indicator .indicator-dot {
  display: block;
  width: 100%;
  height: 100%;
  border-radius: 50%;
}

.phase-running .indicator-dot {
  background: #10b981;
  animation: pulse-ring 1.5s cubic-bezier(0.215, 0.61, 0.355, 1) infinite;
}

.phase-completed .indicator-dot {
  background: #059669;
}

.phase-verifying .indicator-dot {
  background: #3b82f6;
  animation: pulse-ring 1.5s infinite;
}

.phase-idle .indicator-dot {
  background: #9ca3af;
}

@keyframes pulse-ring {
  0% {
    box-shadow: 0 0 0 0 rgba(16, 185, 129, 0.7);
  }
  70% {
    box-shadow: 0 0 0 6px rgba(16, 185, 129, 0);
  }
  100% {
    box-shadow: 0 0 0 0 rgba(16, 185, 129, 0);
  }
}

.drawer-title {
  font-size: 11px;
  font-weight: 700;
  color: #047857;
  background: rgba(16, 185, 129, 0.12);
  padding: 1px 6px;
  border-radius: 4px;
  letter-spacing: 0.5px;
  flex-shrink: 0;
}

.goal-text {
  font-size: 13px;
  font-weight: 600;
  color: var(--text-primary, #111827);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  max-width: 280px;
}

.progress-pill {
  font-size: 11px;
  background: rgba(0, 0, 0, 0.05);
  padding: 1px 6px;
  border-radius: 999px;
  color: var(--text-secondary, #6b7280);
  flex-shrink: 0;
}

.header-right {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-shrink: 0;
}

.current-step-preview {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 12px;
  color: #059669;
  background: rgba(16, 185, 129, 0.08);
  padding: 2px 8px;
  border-radius: 6px;
}

.spinner-icon {
  width: 10px;
  height: 10px;
  border: 2px solid rgba(16, 185, 129, 0.3);
  border-top-color: #10b981;
  border-radius: 50%;
  animation: spin 0.8s linear infinite;
}

@keyframes spin {
  to {
    transform: rotate(360deg);
  }
}

.step-preview-label {
  white-space: nowrap;
  max-width: 220px;
  overflow: hidden;
  text-overflow: ellipsis;
}

.drawer-toggle-btn {
  background: none;
  border: none;
  padding: 4px;
  cursor: pointer;
  color: var(--text-tertiary, #9ca3af);
  display: flex;
  align-items: center;
  justify-content: center;
  transition: color 0.15s ease;
}

.drawer-toggle-btn:hover {
  color: var(--text-primary, #111827);
}

.chevron {
  transition: transform 0.2s cubic-bezier(0.4, 0, 0.2, 1);
}

.rotate-180 {
  transform: rotate(180deg);
}

/* 抽屉内容区 */
.drawer-body {
  padding: 10px 14px;
  background: var(--bg-main, #ffffff);
}

.task-list {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.task-item {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 6px 10px;
  border-radius: 8px;
  background: var(--bg-card, #f9fafb);
  border: 1px solid transparent;
  transition: all 0.15s ease;
}

.task-item.status-completed {
  background: rgba(16, 185, 129, 0.04);
  border-color: rgba(16, 185, 129, 0.15);
}

.task-item.status-running {
  background: rgba(59, 130, 246, 0.05);
  border-color: rgba(59, 130, 246, 0.25);
  box-shadow: 0 2px 8px rgba(59, 130, 246, 0.08);
}

.task-item.status-failed {
  background: rgba(239, 68, 68, 0.05);
  border-color: rgba(239, 68, 68, 0.2);
}

.task-status-icon {
  width: 18px;
  height: 18px;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}

.icon-completed {
  color: #10b981;
}

.icon-running {
  color: #3b82f6;
  animation: spin 1.5s linear infinite;
}

.icon-failed {
  color: #ef4444;
}

.icon-pending {
  color: #9ca3af;
}

.task-content {
  flex: 1;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

.task-line-text {
  font-size: 13px;
  font-weight: 500;
  color: var(--text-primary, #1f2937);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.status-completed .task-line-text {
  color: var(--text-secondary, #4b5563);
}

.status-running .task-line-text {
  color: #1d4ed8;
  font-weight: 600;
}

.task-fail-hint {
  font-size: 11px;
  color: #ef4444;
  margin-top: 2px;
}

.task-badge {
  flex-shrink: 0;
}

.status-tag {
  font-size: 11px;
  padding: 1px 7px;
  border-radius: 999px;
  font-weight: 500;
}

.status-tag.completed {
  background: rgba(16, 185, 129, 0.12);
  color: #047857;
}

.status-tag.running {
  background: rgba(59, 130, 246, 0.12);
  color: #1d4ed8;
}

.status-tag.failed {
  background: rgba(239, 68, 68, 0.12);
  color: #b91c1c;
}

.status-tag.pending {
  background: rgba(156, 163, 175, 0.15);
  color: #6b7280;
}

/* 底部状态徽章栏 */
.drawer-footer-chips {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-top: 10px;
  padding-top: 8px;
  border-top: 1px dashed var(--border-subtle, rgba(229, 231, 235, 0.8));
}

.meta-badge {
  font-size: 11px;
  padding: 2px 8px;
  border-radius: 6px;
  cursor: default;
}

.badge-evidence {
  background: rgba(16, 185, 129, 0.08);
  color: #065f46;
}

.badge-rejected {
  background: rgba(245, 158, 11, 0.1);
  color: #92400e;
}

.badge-missing {
  background: rgba(239, 68, 68, 0.08);
  color: #991b1b;
}

/* 抽屉平滑过渡 */
.drawer-expand-enter-active,
.drawer-expand-leave-active {
  transition: max-height 0.25s ease, opacity 0.2s ease;
  max-height: 360px;
  overflow: hidden;
}

.drawer-expand-enter-from,
.drawer-expand-leave-to {
  max-height: 0;
  opacity: 0;
}
</style>
