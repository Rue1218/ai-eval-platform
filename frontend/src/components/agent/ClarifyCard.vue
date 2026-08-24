<template>
  <div class="clarify-card" :class="{ acked: isAcked }">
    <!-- 卡头 -->
    <div class="clarify-head">
      <span class="clarify-tag">澄清</span>
      <div class="clarify-title">{{ question || '需要补充信息' }}</div>
      <div v-if="isAcked" class="clarify-summary">已回复</div>
    </div>

    <!-- 卡身：仅回复输入，无确认入队（与 ConfirmCard 互斥，M4 §8.2） -->
    <div class="clarify-body">
      <div v-if="options && options.length" class="option-group">
        <button
          v-for="opt in options"
          :key="opt"
          class="chip"
          :class="{ on: answer === opt }"
          :disabled="isAcked"
          @click="answer = opt"
        >
          {{ opt }}
        </button>
      </div>
      <n-input
        v-model:value="answer"
        type="textarea"
        :rows="2"
        :disabled="isAcked"
        placeholder="回复以补充所需信息…"
        @keydown.enter.exact.prevent="handleSend"
      />
    </div>

    <!-- 卡底操作条 -->
    <div class="clarify-foot">
      <div v-if="isAcked" class="ack-stamp ok">✓ 已回复，继续执行</div>
      <div class="spacer"></div>
      <template v-if="!isAcked">
        <button class="btn btn-sign btn-sm" :disabled="sending || !answer.trim()" @click="handleSend">
          {{ sending ? '发送中…' : '发送回复' }}
        </button>
      </template>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref } from 'vue'

const props = defineProps<{
  question: string
  options?: string[] | null
  isAcked?: boolean
}>()

const emit = defineEmits<{
  (e: 'reply', answer: string): void
}>()

const answer = ref('')
const sending = ref(false)

function handleSend() {
  const text = answer.value.trim()
  if (!text || props.isAcked || sending.value) return
  sending.value = true
  emit('reply', text)
}
</script>

<style scoped>
.clarify-card {
  border: 1px solid var(--border-subtle);
  border-radius: 14px;
  background: var(--bg-main);
  box-shadow: 0 14px 40px rgba(17, 24, 39, 0.1);
  overflow: hidden;
  max-width: 640px;
  transition: all 0.25s ease;
  animation: card-up 0.3s cubic-bezier(0.2, 0.9, 0.3, 1.05);
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
.clarify-card.acked {
  background: var(--bg-elevated);
  box-shadow: none;
}

.clarify-head {
  padding: 16px 20px 0;
  display: flex;
  align-items: center;
  gap: 10px;
}
.clarify-tag {
  font-size: 12px;
  font-weight: 700;
  padding: 2px 10px;
  border-radius: 999px;
  background: #fef3c7;
  color: #b45309;
  white-space: nowrap;
}
.clarify-title {
  font-size: 15px;
  font-weight: 700;
}
.clarify-summary {
  margin-left: auto;
  font-size: 12px;
  color: var(--text-tertiary);
}

.clarify-body {
  padding: 14px 20px 6px;
  display: flex;
  flex-direction: column;
  gap: 10px;
}
.option-group {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}
.chip {
  border: 1px solid var(--border-subtle);
  background: var(--bg-main);
  border-radius: 999px;
  padding: 4px 12px;
  font-size: 12.5px;
  color: var(--text-secondary);
  cursor: pointer;
  transition: all 0.15s ease;
}
.chip.on {
  background: #d1fae5;
  border-color: #10b981;
  color: #047857;
}

.clarify-foot {
  padding: 10px 20px 16px;
  display: flex;
  align-items: center;
  gap: 10px;
}
.clarify-foot .spacer {
  flex: 1;
}
.ack-stamp {
  font-size: 12px;
  font-weight: 600;
  padding: 3px 10px;
  border-radius: 999px;
}
.ack-stamp.ok {
  background: #d1fae5;
  color: #047857;
}
</style>
