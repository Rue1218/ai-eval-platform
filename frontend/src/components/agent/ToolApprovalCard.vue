<template>
  <section class="tool-approval-card" :class="{ acked: isAcked, rejected: action === 'reject' }">
    <header class="approval-head">
      <span class="approval-tag">需要确认</span>
      <div>
        <strong>危险 bash 命令待执行</strong>
        <p>命令尚未执行，等待你的明确决定。</p>
      </div>
    </header>

    <div class="approval-body">
      <div class="approval-field">
        <span>风险说明</span>
        <p>{{ reason }}</p>
      </div>
      <div class="approval-field">
        <span>待执行命令</span>
        <pre>{{ command }}</pre>
      </div>
      <div v-if="sandboxScope" class="sandbox-note">沙箱边界：{{ sandboxScope }}</div>
    </div>

    <footer class="approval-foot">
      <span v-if="isAcked" class="approval-result">
        {{ action === 'approve' ? '已确认，正在继续执行' : '已拒绝，命令不会执行' }}
      </span>
      <template v-else>
        <span class="approval-reminder">确认后才会调用受控沙箱。</span>
        <span class="spacer"></span>
        <button class="btn btn-secondary" :disabled="sending" @click="decide('reject')">拒绝</button>
        <button class="btn btn-danger" :disabled="sending" @click="decide('approve')">
          {{ sending ? '提交中…' : '确认执行' }}
        </button>
      </template>
    </footer>
  </section>
</template>

<script setup lang="ts">
import { ref } from 'vue'

const props = withDefaults(defineProps<{
  command: string
  reason: string
  sandboxScope?: string
  isAcked?: boolean
  action?: 'approve' | 'reject'
}>(), {
  sandboxScope: '',
  isAcked: false,
})

const emit = defineEmits<{
  (e: 'decide', action: 'approve' | 'reject'): void
}>()

const sending = ref(false)

/** 提交一次确认决定；实际执行仍必须等待服务端恢复 LangGraph 检查点。 */
function decide(action: 'approve' | 'reject') {
  if (props.isAcked || sending.value) return
  sending.value = true
  emit('decide', action)
}
</script>

<style scoped>
.tool-approval-card {
  max-width: 680px;
  overflow: hidden;
  border: 1px solid #f59e0b;
  border-radius: 14px;
  background: #fffbeb;
  box-shadow: 0 12px 30px rgba(146, 64, 14, 0.1);
}
.tool-approval-card.acked { border-color: var(--border-subtle); background: var(--bg-elevated); box-shadow: none; }
.tool-approval-card.rejected { border-color: #94a3b8; }
.approval-head { display: flex; gap: 10px; padding: 16px 18px 10px; align-items: flex-start; }
.approval-head strong { display: block; color: #92400e; font-size: 15px; }
.approval-head p { margin: 3px 0 0; color: var(--text-secondary); font-size: 12.5px; }
.approval-tag { flex: none; padding: 3px 9px; border-radius: 999px; background: #fef3c7; color: #b45309; font-size: 12px; font-weight: 700; }
.approval-body { padding: 4px 18px 14px; display: grid; gap: 10px; }
.approval-field > span { color: var(--text-tertiary); font-size: 12px; font-weight: 600; }
.approval-field p { margin: 4px 0 0; color: var(--text-primary); font-size: 13px; line-height: 1.6; }
.approval-field pre { max-height: 180px; margin: 5px 0 0; overflow: auto; padding: 10px 12px; border-radius: 8px; background: #1e293b; color: #e2e8f0; font: 12px/1.55 var(--font-mono, ui-monospace, monospace); white-space: pre-wrap; word-break: break-word; }
.sandbox-note { padding: 8px 10px; border-radius: 8px; background: rgba(245, 158, 11, 0.12); color: #92400e; font-size: 12px; line-height: 1.55; }
.approval-foot { min-height: 54px; display: flex; align-items: center; gap: 8px; padding: 10px 18px; border-top: 1px solid rgba(245, 158, 11, 0.25); }
.approval-reminder, .approval-result { color: var(--text-secondary); font-size: 12px; }
.approval-result { color: #475569; font-weight: 600; }
.spacer { flex: 1; }
.btn-danger { border: 1px solid #dc2626; border-radius: 7px; padding: 6px 12px; background: #dc2626; color: #fff; cursor: pointer; font-size: 12px; font-weight: 700; }
.btn-danger:disabled { cursor: not-allowed; opacity: 0.6; }
</style>
