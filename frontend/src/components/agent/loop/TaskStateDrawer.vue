<template>
  <Transition name="task-drawer">
    <section v-if="hasPlan" class="task-state-drawer" :class="`is-${planPhase}`" aria-label="任务规划看板">
      <button
        class="task-drawer-header"
        type="button"
        :aria-expanded="isExpanded"
        aria-controls="task-state-drawer-body"
        @click="isExpanded = !isExpanded"
      >
        <span class="task-phase-dot" aria-hidden="true" />
        <span class="task-drawer-label">任务规划</span>
        <span class="task-goal" :title="plan?.goal">{{ plan?.goal }}</span>
        <span class="task-progress">{{ completedCount }}/{{ plan?.steps.length }}</span>
        <span v-if="!isExpanded && activeStep" class="task-active-preview">进行中：{{ activeStep.title }}</span>
        <svg class="task-chevron" :class="{ 'is-expanded': isExpanded }" viewBox="0 0 16 16" aria-hidden="true">
          <path d="m4 6 4 4 4-4" />
        </svg>
      </button>

      <Transition name="task-drawer-body">
        <div v-if="isExpanded" id="task-state-drawer-body" class="task-drawer-body">
          <ol class="task-step-list">
            <li v-for="(step, index) in plan?.steps" :key="`${index}:${step.title}`" class="task-step" :class="`is-${step.status}`">
              <span class="task-step-icon" :aria-label="statusLabel(step.status)">
                <svg v-if="step.status === 'completed'" viewBox="0 0 16 16" aria-hidden="true"><path d="m3 8 3 3 7-7" /></svg>
                <svg v-else-if="step.status === 'in_progress'" class="task-spinner" viewBox="0 0 16 16" aria-hidden="true"><path d="M13.5 8A5.5 5.5 0 1 1 8 2.5" /></svg>
                <svg v-else viewBox="0 0 16 16" aria-hidden="true"><circle cx="8" cy="8" r="5.5" /><path d="M8 5v3l2 1" /></svg>
              </span>
              <span class="task-step-title">task {{ index + 1 }} ：{{ step.title }}</span>
              <span class="task-step-state">{{ statusLabel(step.status) }}</span>
            </li>
          </ol>
          <p class="task-drawer-hint">此清单仅跟踪当前会话的执行步骤，不会创建或调度评测 Worker 任务。</p>
        </div>
      </Transition>
    </section>
  </Transition>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue'
import type { TaskPlanDisplay } from '../../../api/agentLoopTypes'

const props = defineProps<{ plan: TaskPlanDisplay | null }>()

/** task 调用默认收起任务列表；展开状态仅由用户手动控制，进度更新不会打断阅读。 */
const isExpanded = ref(false)

const hasPlan = computed(() => Boolean(props.plan?.goal && props.plan.steps.length))
const completedCount = computed(() => props.plan?.steps.filter(step => step.status === 'completed').length || 0)
const activeStep = computed(() => props.plan?.steps.find(step => step.status === 'in_progress'))

/** 步骤状态优先于一次工具调用终态，避免规划工具返回成功后误报整个计划已完成。 */
const planPhase = computed(() => {
  if (activeStep.value) return 'running'
  if (props.plan && completedCount.value === props.plan.steps.length) return 'completed'
  return 'pending'
})

function statusLabel(status: TaskPlanDisplay['steps'][number]['status']): string {
  return { pending: '待执行', in_progress: '进行中', completed: '已完成' }[status]
}
</script>

<style scoped>
.task-state-drawer{margin:0 4px 8px;overflow:hidden;border:1px solid #d6e2f5;border-radius:10px;background:#fff;box-shadow:0 5px 16px rgba(28,78,153,.07)}
.task-drawer-header{display:flex;width:100%;min-height:38px;align-items:center;gap:8px;border:0;background:linear-gradient(105deg,#f8fbff,#f3f8ff);padding:8px 11px;color:#26384f;text-align:left;cursor:pointer}
.task-drawer-header:hover{background:#edf5ff}.task-drawer-header:focus-visible{outline:2px solid #4f8ff7;outline-offset:-2px}
.task-phase-dot{width:8px;height:8px;flex:0 0 auto;border-radius:50%;background:#96a5b8}.is-running .task-phase-dot{background:#2c7be5;animation:task-pulse 1.45s ease-in-out infinite}.is-completed .task-phase-dot{background:#28a36a}
.task-drawer-label{flex:0 0 auto;border-radius:4px;background:#e4efff;padding:2px 5px;color:#2f6dc9;font-size:11px;font-weight:700;letter-spacing:.04em}.task-goal{min-width:0;overflow:hidden;color:#253852;font-size:13px;font-weight:650;text-overflow:ellipsis;white-space:nowrap}.task-progress{margin-left:auto;flex:0 0 auto;border-radius:999px;background:#e9eef6;padding:2px 7px;color:#586a81;font:11px/1.2 var(--font-mono,ui-monospace,Consolas,monospace);font-variant-numeric:tabular-nums}.task-active-preview{max-width:240px;overflow:hidden;color:#2c6ebb;font-size:11px;text-overflow:ellipsis;white-space:nowrap}.task-chevron{width:16px;height:16px;flex:0 0 auto;fill:none;stroke:currentColor;stroke-width:1.8;transition:transform .2s ease}.task-chevron.is-expanded{transform:rotate(180deg)}
.task-drawer-body{border-top:1px solid #e4edf9;background:#fff;padding:8px 10px 10px}.task-step-list{display:grid;gap:5px;margin:0;padding:0;list-style:none}.task-step{display:flex;min-width:0;align-items:center;gap:8px;border:1px solid transparent;border-radius:7px;background:#f8fafc;padding:6px 8px}.task-step.is-in_progress{border-color:#b9d4f8;background:#f1f7ff}.task-step.is-completed{background:#f5fbf7}.task-step-icon{display:grid;width:17px;height:17px;flex:0 0 17px;place-items:center;color:#98a6b7}.task-step-icon svg{width:16px;height:16px;fill:none;stroke:currentColor;stroke-linecap:round;stroke-linejoin:round;stroke-width:1.8}.is-in_progress .task-step-icon{color:#2678dc}.is-completed .task-step-icon{color:#299864}.task-spinner{animation:task-spin .9s linear infinite}.task-step-title{min-width:0;flex:1;overflow:hidden;color:#33465e;font-size:13px;text-overflow:ellipsis;white-space:nowrap}.is-in_progress .task-step-title{color:#1d63b5;font-weight:650}.is-completed .task-step-title{color:#658071}.task-step-state{flex:0 0 auto;color:#8391a3;font-size:11px}.is-in_progress .task-step-state{color:#276ebe}.is-completed .task-step-state{color:#25855a}.task-drawer-hint{margin:8px 2px 0;color:#8491a2;font-size:11px;line-height:1.45}
.task-drawer-enter-active,.task-drawer-leave-active{transition:max-height .26s cubic-bezier(.2,.8,.2,1),margin .26s ease,opacity .2s ease}.task-drawer-enter-from,.task-drawer-leave-to{max-height:0;margin-bottom:0;opacity:0}.task-drawer-enter-to,.task-drawer-leave-from{max-height:480px;opacity:1}.task-drawer-body-enter-active,.task-drawer-body-leave-active{overflow:hidden;transition:max-height .22s ease,opacity .18s ease,padding .22s ease}.task-drawer-body-enter-from,.task-drawer-body-leave-to{max-height:0;padding-top:0;padding-bottom:0;opacity:0}.task-drawer-body-enter-to,.task-drawer-body-leave-from{max-height:420px;opacity:1}
@keyframes task-spin{to{transform:rotate(360deg)}}@keyframes task-pulse{50%{box-shadow:0 0 0 5px rgba(44,123,229,.12)}}
@media (max-width:700px){.task-active-preview{display:none}.task-goal{font-size:12px}.task-state-drawer{margin-right:0;margin-left:0}}
@media (prefers-reduced-motion:reduce){.task-phase-dot,.task-spinner{animation:none}.task-chevron,.task-drawer-enter-active,.task-drawer-leave-active,.task-drawer-body-enter-active,.task-drawer-body-leave-active{transition:none}}
</style>
