<template>
  <div class="approval-card" :class="{ done: !!item.approvalDone, 'no-anim': item.noAnim }">
    <div class="approval-head">
      <span class="risk-tag" :class="riskClass">{{ riskLabel }}</span>
      <span class="approval-title">工具执行审批</span>
      <span class="approval-name mono">{{ item.approval?.name || 'tool' }}</span>
    </div>

    <div class="approval-body">
      <div class="field">
        <span class="field-label">待执行命令</span>
        <pre class="cmd mono">{{ item.approval?.command || '' }}</pre>
      </div>
      <div v-if="item.approval?.reason" class="field">
        <span class="field-label">审批原因</span>
        <div class="reason">{{ item.approval.reason }}</div>
      </div>
      <div v-if="item.approval?.sandbox_scope" class="field">
        <span class="field-label">沙箱范围</span>
        <div class="reason tertiary">{{ item.approval.sandbox_scope }}</div>
      </div>
      <div class="field meta">
        <span class="mono small tertiary">call_id: {{ item.approval?.call_id }}</span>
      </div>

      <div v-if="item.approvalDone === 'approved'" class="approval-verdict ok">已批准 —— 命令已放行执行</div>
      <div v-else-if="item.approvalDone === 'rejected'" class="approval-verdict no">已拒绝 —— 命令未执行</div>
      <div v-else-if="canAct" class="approval-actions">
        <button class="btn btn-sign btn-sm" @click="$emit('approve', item)">批准并执行</button>
        <button class="btn btn-secondary btn-sm" @click="$emit('reject', item)">拒绝</button>
      </div>
      <div v-else class="approval-verdict pending">等待审批……</div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'

const props = defineProps<{
  item: {
    approval?: { name?: string; command?: string; reason?: string; risk_level?: string; sandbox_scope?: string; call_id?: string } | null
    approvalDone?: 'approved' | 'rejected' | null
    noAnim?: boolean
  }
  canAct?: boolean
}>()

defineEmits<{ approve: [item: any]; reject: [item: any] }>()

const riskClass = computed(() => {
  const level = props.item.approval?.risk_level
  return level === 'high' ? 'high' : level === 'medium' ? 'medium' : 'low'
})
const riskLabel = computed(() => {
  const level = props.item.approval?.risk_level
  return level === 'high' ? '高风险' : level === 'medium' ? '中风险' : '低风险'
})
</script>

<style scoped>
.approval-card {
  border: 1px solid var(--border, #e3e6ee);
  border-radius: 10px;
  overflow: hidden;
  background: #fffdfa;
  max-width: 620px;
}
.approval-card .approval-head {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 12px;
  background: #fff3f0;
  border-bottom: 1px solid #ffd9d1;
}
.risk-tag {
  font-size: 11px;
  font-weight: 600;
  padding: 1px 8px;
  border-radius: 999px;
  color: #fff;
}
.risk-tag.high {
  background: #d4380d;
}
.risk-tag.medium {
  background: #d46b08;
}
.risk-tag.low {
  background: #874d00;
}
.approval-title {
  font-weight: 600;
  font-size: 13px;
}
.approval-name {
  margin-left: auto;
  font-size: 12px;
  opacity: 0.85;
}
.approval-body {
  padding: 10px 12px;
}
.field {
  margin-bottom: 8px;
}
.field-label {
  display: block;
  font-size: 11px;
  color: #7a7f8a;
  margin-bottom: 4px;
}
.cmd {
  background: #1e1e1e;
  color: #d4d4d4;
  border-radius: 6px;
  padding: 8px 10px;
  font-size: 12px;
  white-space: pre-wrap;
  word-break: break-all;
  margin: 0;
}
.reason {
  font-size: 12px;
  color: #4a4f5a;
}
.tertiary {
  color: #9aa0ab;
}
.meta {
  margin-top: 2px;
}
.approval-actions {
  display: flex;
  gap: 8px;
  margin-top: 4px;
}
.approval-verdict {
  margin-top: 6px;
  font-size: 13px;
  font-weight: 600;
}
.approval-verdict.ok {
  color: #1a7f37;
}
.approval-verdict.no {
  color: #c92a2a;
}
.approval-verdict.pending {
  color: #b8860b;
}
.approval-card.done {
  opacity: 0.82;
}
</style>
