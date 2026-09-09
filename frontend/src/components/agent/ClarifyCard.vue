<template>
  <div
    class="clarify-card"
    :class="{ done: !!item.clarifyDone, 'no-anim': item.noAnim }"
    :data-od-id="`clarify-card-${item.clarify?.id || ''}`"
  >
    <div class="clarify-head">
      <span class="clarify-tag">澄清问答</span>
      <span class="clarify-title">回答以下问题以继续</span>
      <span v-if="item.clarify?.questions?.length" class="clarify-count mono">
        {{ item.clarify.questions.length }} 题 · 一次作答
      </span>
    </div>

    <div class="clarify-body">
      <fieldset
        v-for="(q, qi) in item.clarify?.questions || []"
        :key="q.id"
        class="q-field"
        :disabled="!!item.clarifyDone || !canAct"
      >
        <legend class="q-question">
          {{ qi + 1 }}. {{ q.question }}
          <i v-if="q.required !== false" class="req">*</i>
          <span v-if="q.header" class="q-header">{{ q.header }}</span>
        </legend>

        <!-- 文本题 -->
        <textarea
          v-if="q.type === 'text'"
          v-model="draft[q.id].custom"
          class="q-textarea mono"
          rows="2"
          :placeholder="q.required !== false ? '必答' : '选填'"
        />

        <!-- radio / checkbox 选择 -->
        <div v-else class="q-options">
          <label v-for="opt in q.options || []" :key="opt.label" class="q-option">
            <input
              :type="q.type === 'checkbox' || q.multi_select ? 'checkbox' : 'radio'"
              :name="`clarify-${item.clarify?.id}-${q.id}`"
              :value="opt.label"
              :checked="draft[q.id].selected.includes(opt.label)"
              @change="onToggle(q, opt.label, $event)"
            />
            <span class="q-option-label">{{ opt.label }}</span>
            <span v-if="opt.description" class="q-option-hint">{{ opt.description }}</span>
          </label>
          <div v-if="!q.options?.length" class="q-options-empty">
            <textarea
              v-model="draft[q.id].custom"
              class="q-textarea mono"
              rows="2"
              :placeholder="q.required !== false ? '请输入答案（必答）' : '选填'"
            />
          </div>
        </div>
      </fieldset>

      <div v-if="item.clarifyDone === 'submitted'" class="clarify-verdict ok">
        已提交 —— 正在按你的答复继续执行
      </div>
      <div v-else-if="item.clarifyDone === 'failed'" class="clarify-verdict expired">
        已失效 —— 回合恢复失败（检查点不可用），请重新发起该操作
      </div>
      <div v-else-if="canAct" class="clarify-actions">
        <button class="btn btn-sign btn-sm" @click="submit">提交回答</button>
        <span v-if="errorMsg" class="clarify-error">{{ errorMsg }}</span>
      </div>
      <div v-else class="clarify-verdict pending">等待作答……</div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, reactive, ref } from 'vue'

import type { ClarifyAnswer, ClarifyQuestion } from '../../api/types'

const props = defineProps<{
  item: {
    clarify?: { id?: string; questions?: ClarifyQuestion[] } | null
    clarifyDone?: 'submitted' | 'failed' | null
    noAnim?: boolean
  }
  canAct?: boolean
}>()

const emit = defineEmits<{ submit: [answers: ClarifyAnswer[]] }>()

// 注意：不设提交防抖 busy——父级乐观置 clarifyDone 后 canAct=false 即禁操作，
// 与 ApprovalCard 同构；busy 在父级拒绝发送（断线提示后未置 done）时无法复位
// 会把卡锁死，故交由一次性纪律（服务端行锁）+ 乐观盖章双保险兜底。
const errorMsg = ref('')

interface DraftValue {
  selected: string[]
  custom: string
}

/** 题目草稿：组件级本地状态，卡失活/回放态只读不渲染编辑控件。 */
const draft = reactive<Record<string, DraftValue>>({})
for (const q of props.item.clarify?.questions || []) {
  draft[q.id] = { selected: [], custom: '' }
}

function onToggle(q: ClarifyQuestion, label: string, event: Event) {
  const target = event.target as HTMLInputElement
  const value = draft[q.id]
  if (q.type === 'checkbox' || q.multi_select) {
    if (target.checked) {
      if (!value.selected.includes(label)) value.selected.push(label)
    } else {
      value.selected = value.selected.filter(v => v !== label)
    }
  } else {
    value.selected = target.checked ? [label] : []
  }
  errorMsg.value = ''
}

const canSubmit = computed(() => !!props.canAct && props.item.clarifyDone !== 'submitted')

function validate(): string | null {
  for (const q of props.item.clarify?.questions || []) {
    const value = draft[q.id]
    if (q.required === false) continue
    if (q.type === 'text') {
      if (!value.custom.trim()) return `第 ${q.question} 为必答`
    } else if (q.type === 'radio' && !value.selected.length && !value.custom.trim()) {
      return `请回答：${q.question}`
    } else if (q.type === 'checkbox' && !value.selected.length && !value.custom.trim()) {
      return `请至少选择一项：${q.question}`
    }
  }
  return null
}

function submit() {
  const missing = validate()
  if (missing) {
    errorMsg.value = missing
    return
  }
  const clarify = props.item.clarify
  if (!clarify?.id || !canSubmit.value) return
  const answers: ClarifyAnswer[] = (clarify.questions || []).map(q => ({
    id: q.id,
    selected: [...draft[q.id].selected],
    custom: q.type === 'text' ? draft[q.id].custom.trim() : (draft[q.id].custom || '').trim(),
  }))
  emit('submit', answers)
}
</script>

<style scoped>
.clarify-card {
  border: 1px solid var(--border, #e3e6ee);
  border-radius: 10px;
  overflow: hidden;
  background: #fbfdff;
  max-width: 620px;
}
.clarify-card .clarify-head {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 12px;
  background: #eef4ff;
  border-bottom: 1px solid #d3e3ff;
}
.clarify-tag {
  font-size: 11px;
  font-weight: 600;
  padding: 1px 8px;
  border-radius: 999px;
  color: #fff;
  background: #2f6fed;
}
.clarify-title {
  font-weight: 600;
  font-size: 13px;
}
.clarify-count {
  margin-left: auto;
  font-size: 12px;
  color: #6a7f9f;
}
.clarify-body {
  padding: 10px 12px;
}
.q-field {
  border: none;
  border-top: 1px dashed #e1e7f2;
  margin: 8px 0 0;
  padding: 8px 0 4px;
  min-width: 0;
}
.q-field:first-of-type {
  border-top: none;
  margin-top: 0;
}
.q-question {
  font-size: 13px;
  font-weight: 600;
  color: #33415c;
  padding: 0;
  margin-bottom: 4px;
}
.req {
  color: #d4380d;
  font-style: normal;
  margin-left: 2px;
}
.q-header {
  display: block;
  font-size: 11px;
  font-weight: 400;
  color: #7a7f8a;
}
.q-options {
  display: flex;
  flex-wrap: wrap;
  gap: 6px 14px;
  padding: 2px 0;
}
.q-option {
  display: flex;
  align-items: baseline;
  gap: 5px;
  font-size: 13px;
  cursor: pointer;
}
.q-option input {
  accent-color: #2f6fed;
}
.q-option-label {
  color: #2c3444;
}
.q-option-hint {
  font-size: 11px;
  color: #9aa0ab;
}
.q-options-empty {
  padding: 2px 0;
}
.q-textarea {
  width: 100%;
  box-sizing: border-box;
  border: 1px solid #d5dbe8;
  border-radius: 6px;
  padding: 6px 8px;
  font-size: 12px;
  resize: vertical;
  background: #fff;
  color: #1f2530;
}
.clarify-actions {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-top: 8px;
}
.clarify-error {
  font-size: 12px;
  color: #c92a2a;
}
.clarify-verdict {
  margin-top: 8px;
  font-size: 13px;
  font-weight: 600;
}
.clarify-verdict.ok {
  color: #1a7f37;
}
.clarify-verdict.pending {
  color: #b8860b;
}
.clarify-verdict.expired {
  color: #9aa0ab;
}
.clarify-card.done {
  opacity: 0.82;
}
</style>
