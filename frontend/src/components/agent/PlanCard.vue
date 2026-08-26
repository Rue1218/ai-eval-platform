<template>
  <div class="plan-card" :class="{ 'no-anim': noAnim }">
    <div class="plan-head">
      <span class="plan-tag">规划</span>
      <div class="plan-title">{{ plan.intent || '本轮步骤' }}</div>
      <SkillBadge v-if="plan.skill_id" :skill-id="plan.skill_id" />
    </div>

    <div class="plan-body">
      <div class="plan-meta">
        <span class="meta-chip">交付 · {{ deliveryLabel }}</span>
        <span class="meta-chip">{{ plan.allows_replan ? '允许重规划' : '不可重规划' }}</span>
        <span v-if="budgetLabel" class="meta-chip mono">{{ budgetLabel }}</span>
      </div>

      <ol v-if="steps.length" class="plan-steps">
        <li v-for="(step, idx) in steps" :key="`${idx}-${step}`">{{ step }}</li>
      </ol>

      <div v-if="tools.length" class="plan-row">
        <span class="row-label">短工具</span>
        <span class="row-value mono">{{ tools.join(' · ') }}</span>
      </div>

      <div v-if="slotPairs.length" class="plan-slots">
        <div v-for="pair in slotPairs" :key="pair.key" class="plan-row">
          <span class="row-label">{{ pair.key }}</span>
          <span class="row-value">{{ pair.value }}</span>
        </div>
      </div>

      <div v-if="plan.notes" class="plan-notes">{{ plan.notes }}</div>
    </div>

    <div class="plan-foot">
      <span class="plan-hint">规划产物仅供查看，无需确认</span>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import type { PlanArtifact } from '../../api/types'
import SkillBadge from './SkillBadge.vue'

const props = defineProps<{
  plan: PlanArtifact
  noAnim?: boolean
}>()

const deliveryLabel = computed(() => {
  if (props.plan.delivery === 'confirm') return '确认卡'
  if (props.plan.delivery === 'chat') return '对话'
  return props.plan.delivery || '对话'
})

const budgetLabel = computed(() => {
  const budget = props.plan.budget || {}
  const calls = budget.model_calls
  const turns = budget.tool_turns
  const parts: string[] = []
  if (typeof calls === 'number') parts.push(`模型 ${calls} 次`)
  if (typeof turns === 'number') parts.push(`工具 ${turns} 轮`)
  return parts.join(' / ')
})

const steps = computed(() => {
  const raw = props.plan.slots?.steps
  return Array.isArray(raw) ? raw.map((step) => String(step)) : []
})

const tools = computed(() => props.plan.tools_needed || [])

const slotPairs = computed(() => {
  const slots = props.plan.slots || {}
  return Object.entries(slots)
    .filter(([key, value]) => key !== 'steps' && value !== undefined && value !== null && value !== '')
    .map(([key, value]) => ({
      key,
      value: typeof value === 'string' ? value : JSON.stringify(value),
    }))
})
</script>

<style scoped>
.plan-card {
  border: 1px solid var(--border-subtle);
  border-radius: 14px;
  background: var(--bg-main);
  box-shadow: 0 14px 40px rgba(17, 24, 39, 0.1);
  overflow: hidden;
  max-width: 640px;
  animation: card-up 0.3s cubic-bezier(0.2, 0.9, 0.3, 1.05);
}
.plan-card.no-anim {
  animation: none;
}
@keyframes card-up {
  from {
    opacity: 0;
    transform: translateY(14px);
  }
  to {
    opacity: 1;
    transform: none;
  }
}
.plan-head {
  padding: 16px 20px 0;
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
}
.plan-tag {
  font-size: 12px;
  font-weight: 700;
  padding: 2px 10px;
  border-radius: 999px;
  background: rgba(16, 185, 129, 0.14);
  color: #047857;
  white-space: nowrap;
}
.plan-title {
  font-size: 15px;
  font-weight: 700;
  flex: 1;
}
.plan-body {
  padding: 12px 20px 6px;
  display: flex;
  flex-direction: column;
  gap: 10px;
}
.plan-meta {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}
.meta-chip {
  font-size: 12px;
  padding: 2px 8px;
  border-radius: 999px;
  background: var(--bg-elevated, #f3f4f6);
  color: var(--text-secondary);
}
.plan-steps {
  margin: 0 0 0 18px;
  padding: 0;
  color: var(--text-primary);
}
.plan-steps li {
  margin: 4px 0;
}
.plan-row {
  display: flex;
  gap: 10px;
  font-size: 13px;
}
.row-label {
  color: var(--text-tertiary);
  min-width: 56px;
  flex-shrink: 0;
}
.row-value {
  color: var(--text-secondary);
  word-break: break-all;
}
.plan-notes {
  font-size: 13px;
  color: var(--text-secondary);
  line-height: 1.5;
}
.plan-foot {
  padding: 8px 20px 14px;
}
.plan-hint {
  font-size: 12px;
  color: var(--text-tertiary);
}
</style>
