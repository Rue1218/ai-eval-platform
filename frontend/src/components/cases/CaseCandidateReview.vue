<template>
  <section class="candidate-review">
    <div class="review-tools">
      <input v-model="search" aria-label="搜索候选用例" placeholder="搜索名称、功能点或需求依据" />
      <label><input v-model="onlyIncomplete" type="checkbox" />仅看待补全</label>
      <button class="btn btn-secondary" :disabled="locked" @click="emit('toggle-all')">全选 / 全不选</button>
    </div>
    <p class="review-count">显示 {{ visible.length }} / {{ candidates.length }} 条；勾选表示本次采纳，仍需保存草稿后审核入库。</p>
    <article v-for="{ candidate: cand, index: ci } in visible" :key="ci" class="candidate-card">
      <header>
        <label><input v-model="cand.selected" type="checkbox" :disabled="locked" :aria-label="`采纳候选 ${ci + 1}`" />候选 {{ ci + 1 }}</label>
        <span v-if="cand.source?.test_point_id" class="point-id">{{ cand.source.test_point_id }}</span>
        <span v-if="needsClarification(cand)" class="pending">待澄清 / 补全</span>
        <button class="link-btn" :disabled="locked" @click="candidates.splice(ci, 1)">移除</button>
      </header>
      <details v-if="cand.source?.requirement_quote" class="requirement-evidence">
        <summary>需求依据</summary><p>{{ cand.source.requirement_quote }}</p>
      </details>
      <fieldset class="candidate-fields" :disabled="locked">
        <label>用例名称<input v-model="cand.name" :aria-label="`候选 ${ci + 1} 名称`" /></label>
        <label>所属模块<input v-model="cand.module" :aria-label="`候选 ${ci + 1} 模块`" /></label>
        <label>功能点<input v-model="cand.feature_point" :aria-label="`候选 ${ci + 1} 功能点`" /></label>
        <label>测试策略<select v-model="cand.strategy" :aria-label="`候选 ${ci + 1} 策略`"><option v-for="strategy in STRATEGY_OPTIONS" :key="strategy.key">{{ strategy.label }}</option></select></label>
        <label>优先级<select v-model="cand.priority" :aria-label="`候选 ${ci + 1} 优先级`"><option v-for="priority in priorities" :key="priority">{{ priority }}</option></select></label>
        <label class="wide">前置条件<textarea v-model="cand.preconditions" rows="2" :aria-label="`候选 ${ci + 1} 前置条件`" /></label>
        <label class="wide">执行步骤（每行一步）<textarea v-model="cand.stepsText" rows="3" :aria-label="`候选 ${ci + 1} 执行步骤`" /></label>
        <label class="wide">预期结果<textarea v-model="cand.expected_result" rows="2" :aria-label="`候选 ${ci + 1} 预期结果`" /></label>
      </fieldset>
    </article>
    <p v-if="!visible.length" class="review-empty">没有符合当前筛选条件的候选。</p>
  </section>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue'
import { STRATEGY_OPTIONS, type AiCaseCandidate } from '../../composables/useCaseGeneration'
const candidates = defineModel<AiCaseCandidate[]>({ required: true })
defineProps<{ locked: boolean }>()
const emit = defineEmits<{ 'toggle-all': [] }>()
const search = ref(''), onlyIncomplete = ref(false)
const priorities = ['HX', 'FHX', 'BJ', 'YC', 'ZD', 'BL']
/** 缺少可执行内容的候选保持可见标记，不静默伪造默认预期。 */
function needsClarification(candidate: AiCaseCandidate) {
  return !candidate.name.trim() || !candidate.stepsText.trim() || !candidate.expected_result.trim()
}
const visible = computed(() => candidates.value.map((candidate, index) => ({ candidate, index })).filter(({ candidate }) =>
  (!onlyIncomplete.value || needsClarification(candidate)) && (!search.value.trim() ||
    `${candidate.name} ${candidate.feature_point} ${candidate.source?.requirement_quote || ''}`.toLowerCase().includes(search.value.trim().toLowerCase()))))
</script>

<style scoped>
.review-tools {
  display:flex;
  align-items:center;
  gap:12px;
  flex-wrap:wrap;
}
.review-tools>input {
  flex:1;
  min-width:180px;
}
.review-tools label {
  display:flex;
  gap:6px;
  align-items:center;
}
.review-count {
  font-size:12px;
  color:var(--text-secondary);
  line-height:1.7;
}
.candidate-card {
  margin:16px 0;
  border:1px solid var(--border-subtle);
  border-radius:12px;
  padding:18px;
  background:var(--bg-main);
}
.candidate-card header {
  display:flex;
  align-items:center;
  gap:10px;
  margin-bottom:12px;
}
.candidate-card header label {
  font-weight:600;
}
.candidate-card header button {
  margin-left:auto;
}
.point-id {
  font:12px var(--font-mono);
  color:var(--c-agent);
}
.pending {
  font-size:12px;
  color:#b45309;
}
.candidate-fields {
  border:0;
  padding:0;
  margin:0;
  display:grid;
  grid-template-columns:1fr 1fr;
  gap:14px;
}
.candidate-fields label {
  display:flex;
  flex-direction:column;
  gap:7px;
  font-size:12px;
  color:var(--text-secondary);
  min-width:0;
}
.wide {
  grid-column:1/-1;
}
input:not([type=checkbox]),textarea,select {
  width:100%;
  box-sizing:border-box;
  border:1px solid var(--border-subtle);
  border-radius:7px;
  background:var(--bg-main);
  color:var(--text-primary);
  font:inherit;
  padding:9px 11px;
}
textarea {
  resize:vertical;
  line-height:1.6;
}
input:focus,textarea:focus,select:focus {
  outline:2px solid var(--c-agent);
  outline-offset:1px;
}
.requirement-evidence {
  font-size:12px;
  color:var(--text-secondary);
  margin-bottom:14px;
}
.requirement-evidence p {
  white-space:pre-wrap;
  line-height:1.7;
  overflow-wrap:anywhere;
}
.requirement-evidence summary {
  cursor:pointer;
}
.review-empty {
  padding:32px;
  text-align:center;
  color:var(--text-secondary);
}
@media(max-width:720px) {
  .candidate-fields {
    grid-template-columns:1fr;
  }
  .candidate-card {
    padding:12px;
  }
  .candidate-card header {
    flex-wrap:wrap;
  }
}
</style>
