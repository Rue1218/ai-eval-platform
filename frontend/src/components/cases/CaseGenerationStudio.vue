<template>
  <section class="generation-studio" aria-label="测试用例生成工作台">
    <nav class="generation-steps" aria-label="用例生成步骤">
      <button v-for="(label, index) in steps" :key="label" :class="{ active: state.step === index + 1, done: state.step > index + 1 }"
        :aria-current="state.step === index + 1 ? 'step' : undefined" :disabled="busy || !!state.appliedToSetId || !canVisit(index + 1)" @click="state.step = (index + 1) as 1 | 2 | 3">
        <span>{{ index + 1 }}</span><b>{{ label }}</b>
      </button>
    </nav>
    <div ref="stageScroll" class="studio-scroll">
      <div v-if="state.error" class="studio-error" role="alert">{{ state.error }}</div>
      <div class="studio-grid">
        <main class="stage-content">
          <template v-if="state.step === 1">
            <header class="stage-heading"><p>从需求开始</p><h2>明确要测什么，再展开用例</h2><span>分析会给出测试点、风险与原文依据，你可以先调整范围。</span></header>
            <fieldset :disabled="busy" class="source-fields">
              <div class="source-switch"><label><input v-model="state.sourceMode" type="radio" value="text" />粘贴需求文本</label><label><input v-model="state.sourceMode" type="radio" value="file" />上传需求文件</label></div>
              <label v-if="state.sourceMode === 'text'" class="stack">需求描述 / 业务规则 / 接口规范<textarea v-model="state.prdText" rows="13" placeholder="粘贴需求文档段落、状态转移逻辑或 OpenAPI 规范..." aria-label="需求正文" /></label>
              <div v-else class="source-upload">
                <input ref="sourceInput" type="file" accept=".txt,.md,.csv,.json,.yaml,.yml,.xlsx" aria-label="选择需求文件" @change="emit('upload', $event)" />
                <p>{{ state.sourceFileName || '选择文本、Markdown、CSV、JSON、YAML 或 Excel 需求文件' }}</p>
                <p v-if="state.sourceUploading" role="status">已上传 {{ state.sourceUploadPercent }}%，等待服务端保存…</p>
                <small>仅使用你有权限读取的来源；上传成功后才替换当前文件。</small>
              </div>
            </fieldset>
            <p class="stage-tip">尽量包含角色、起始状态、操作与预期。未知规则会列为待澄清项。</p>
          </template>

          <template v-else-if="state.step === 2 && state.design">
            <header class="stage-heading"><p>确认测试设计</p><h2>选择本次要覆盖的测试点</h2><span>{{ state.design.summary }}</span></header>
            <section v-if="state.design.questions.length || state.design.assumptions.length" class="design-questions" aria-label="需求待澄清事项">
              <strong>生成前需要核对</strong>
              <p v-for="question in state.design.questions" :key="question">待澄清：{{ question }}</p>
              <p v-for="assumption in state.design.assumptions" :key="assumption">假设：{{ assumption }}</p>
              <small>可以返回需求补充规则并重新分析；未确定的预期会保留为待澄清。</small>
            </section>
            <div class="point-toolbar"><b>已选 {{ state.selectedPointIds.length }} / {{ state.design.test_points.length }} 个测试点</b><button class="link-btn" :disabled="busy" @click="togglePoints">全选 / 全不选测试点</button></div>
            <article v-for="point in state.design.test_points" :key="point.id" class="test-point" :class="{ excluded: !state.selectedPointIds.includes(point.id) }">
              <header><label><input v-model="state.selectedPointIds" type="checkbox" :value="point.id" :disabled="busy" :aria-label="`选择测试点 ${point.id}`" />{{ point.id }}</label><span :class="`risk-${point.risk}`">{{ riskNames[point.risk] }}风险</span></header>
              <fieldset :disabled="busy">
                <label class="stack">测试点<input v-model="point.title" :aria-label="`测试点 ${point.id} 名称`" maxlength="200" /></label>
                <div class="point-options"><label class="stack">模块<input v-model="point.module" :aria-label="`测试点 ${point.id} 模块`" maxlength="100" /></label><label class="stack">风险<select v-model="point.risk" :aria-label="`测试点 ${point.id} 风险`"><option value="high">高</option><option value="medium">中</option><option value="low">低</option></select></label></div>
                <blockquote><small>需求原文依据</small><p>{{ point.source_quote }}</p></blockquote>
                <label class="stack">预期与验收依据<textarea v-model="point.expected" rows="2" :aria-label="`测试点 ${point.id} 预期`" placeholder="没有明确依据时保留为空" maxlength="2000" /></label>
                <label class="stack">补充约束 / 待澄清<textarea v-model="point.constraints" rows="2" :aria-label="`测试点 ${point.id} 约束`" maxlength="2000" /></label>
              </fieldset>
            </article>
          </template>

          <template v-else-if="state.step === 3">
            <header class="stage-heading"><p>审核候选</p><h2>核对每一步和预期，再保存草稿</h2><span>来源：{{ state.candidateSource }}；已选 {{ selectedCount }} / {{ state.candidates.length }} 条</span></header>
            <p class="stage-tip" role="status">本次勾选候选关联 {{ state.candidatePointIds.length - uncoveredPoints.length }} / {{ state.candidatePointIds.length }} 个测试点。<span v-if="uncoveredPoints.length">尚无勾选候选的测试点：{{ uncoveredPoints.join('、') }}。</span>请人工核对覆盖范围。</p>
            <CaseCandidateReview v-model="state.candidates" :locked="state.applying || !!state.appliedToSetId" @toggle-all="emit('toggle-candidates')" />
          </template>
        </main>

        <aside class="studio-aside">
          <section class="aside-card">
            <h3>生成方法</h3>
            <p v-if="skillsLoading" role="status">正在读取技能目录…</p>
            <div v-else-if="skillsError" role="alert">{{ skillsError }} <button class="link-btn" @click="emit('reload-skills')">重试加载</button></div>
            <label v-else class="stack">用例设计 Skill<select v-model="state.skillId" :disabled="busy || !!state.appliedToSetId" aria-label="用例设计 Skill"><option v-for="skill in skills" :key="skill.id" :value="skill.id">{{ skill.name }}</option></select></label>
            <p v-if="activeSkill">{{ activeSkill.description }}</p>
            <details v-if="activeSkill"><summary>方法与开源来源</summary><p>{{ activeSkill.name }} · {{ activeSkill.version }} · {{ activeSkill.license }}</p><a :href="activeSkill.source_url" target="_blank" rel="noopener noreferrer">查看开源 Skill</a><p>按需读取：先工作流与需求分析，再读取用例模板和所选策略资料。</p></details>
          </section>
          <section v-if="state.step !== 3" class="aside-card">
            <h3>生成范围</h3>
            <label class="stack">最多生成条数<input v-model.number="state.count" type="number" min="1" max="80" step="1" :disabled="busy" aria-label="最多生成条数" /></label>
            <p>1–80 条，按风险与需求深度生成，不为凑数重复。</p>
            <div class="strategy-fields"><label v-for="strategy in STRATEGY_OPTIONS" :key="strategy.key">{{ strategy.label }}<span><input v-model.number="state.strategyWeights[strategy.key]" type="number" min="0" max="100" step="1" :disabled="busy" :aria-label="`${strategy.label}策略百分比`" />%</span></label></div>
            <p :class="{ invalid: !weightsValid }">策略合计 {{ weightTotal }}%（需为 100%）</p>
          </section>
          <section v-else class="aside-card save-target">
            <h3>保存到用例库</h3>
            <label v-if="canAppend"><input v-model="state.target" type="radio" value="current" :disabled="state.applying || !!state.appliedToSetId" />追加到当前草稿「{{ currentSetName }}」</label>
            <label><input v-model="state.target" type="radio" value="new" :disabled="state.applying || !!state.appliedToSetId" />新建草稿并保存候选</label>
            <label v-if="state.target === 'new'" class="stack">新草稿名称<input v-model="state.newSetName" aria-label="新草稿名称" :disabled="state.applying" placeholder="输入新草稿名称" /></label>
            <p>这里只保存草稿。回到用例库核对自检结果后，由你确认入库。</p>
            <button v-if="state.appliedToSetId && !state.applying" class="btn btn-secondary" :disabled="savingCases" @click="emit('move-candidates')">{{ state.rehomePending ? '返回当前草稿' : '改存新草稿' }}</button>
          </section>
        </aside>
      </div>
    </div>
    <footer class="studio-footer">
      <button class="btn btn-secondary" :disabled="state.applying" @click="emit('close')">返回用例库</button>
      <button v-if="state.step > 1" class="btn btn-secondary" :disabled="busy || !!state.appliedToSetId" @click="state.step = state.step === 3 && state.design ? 2 : 1">{{ state.step === 3 && state.design ? '返回测试设计' : '返回修改需求' }}</button>
      <span class="footer-status" role="status">{{ state.analyzing ? '正在分析需求并提取测试点…' : state.generating ? '正在按确认的测试点生成用例…' : '生成内容不会自动确认入库' }}</span>
      <button v-if="state.step === 1" class="btn btn-primary" :disabled="busy || !activeSkill || !!skillsError" @click="emit('analyze')">{{ state.analyzing ? '分析中…' : '分析需求与测试点' }}</button>
      <button v-else-if="state.step === 2" class="btn btn-primary" :disabled="busy || !weightsValid || !countValid || !state.selectedPointIds.length" @click="emit('generate')">{{ state.generating ? '生成中…' : '生成候选用例' }}</button>
      <button v-else class="btn btn-primary" :disabled="!selectedCount || busy || (!!state.appliedToSetId && !state.rehomePending && saveConflict)" @click="emit('adopt')">{{ state.applying ? '保存中…' : state.appliedToSetId && !state.rehomePending ? (saveConflict ? '版本冲突，请先核对' : '重试保存候选') : `采纳并保存候选 (${selectedCount} 条)` }}</button>
    </footer>
  </section>
</template>

<script setup lang="ts">
import { computed, nextTick, ref, watch } from 'vue'
import type { CaseGenerationSkill } from '../../api/types'
import { STRATEGY_OPTIONS, type CaseGenerationState } from '../../composables/useCaseGeneration'
import CaseCandidateReview from './CaseCandidateReview.vue'
const state = defineModel<CaseGenerationState>({ required: true })
const props = defineProps<{ skills: CaseGenerationSkill[]; skillsLoading: boolean; skillsError: string;
  canAppend: boolean; currentSetName?: string; saveConflict: boolean; savingCases: boolean }>()
const emit = defineEmits<{ analyze: []; generate: []; adopt: []; close: []; upload: [Event];
  'toggle-candidates': []; 'move-candidates': []; 'reload-skills': [] }>()
const sourceInput = ref<HTMLInputElement | null>(null)
const stageScroll = ref<HTMLElement | null>(null)
// 切换阶段从新阶段标题开始，避免继承上一阶段的长列表滚动位置。
watch(() => state.value.step, async () => {
  await nextTick()
  stageScroll.value?.scrollTo({ top: 0 })
})
const steps = ['需求与范围', '测试设计', '审核与保存']
const riskNames = { high: '高', medium: '中', low: '低' }
const busy = computed(() => state.value.analyzing || state.value.generating || state.value.applying || state.value.sourceUploading)
const activeSkill = computed(() => props.skills.find(skill => skill.id === state.value.skillId))
const selectedCount = computed(() => state.value.candidates.filter(candidate => candidate.selected).length)
/** 按本批设计快照统计真实关联，改需求或重新生成失败不覆盖旧候选的范围。 */
const uncoveredPoints = computed(() => {
  const covered = new Set(state.value.candidates.filter(candidate => candidate.selected).map(candidate => candidate.source?.test_point_id))
  return state.value.candidatePointIds.filter(id => !covered.has(id))
})
const weightTotal = computed(() => Object.values(state.value.strategyWeights).reduce((sum, value) => sum + Number(value || 0), 0))
const weightsValid = computed(() => weightTotal.value === 100 && Object.values(state.value.strategyWeights).every(value => Number.isInteger(value) && value >= 0 && value <= 100))
const countValid = computed(() => Number.isInteger(state.value.count) && state.value.count >= 1 && state.value.count <= 80)
/** 未产生设计或候选时不能跳过前置阶段。 */
function canVisit(step: number) { return step === 1 || step === 2 && !!state.value.design || step === 3 && !!state.value.candidates.length }
/** 选择只改变本次生成范围，保留未选测试点供以后使用。 */
function togglePoints() {
  const points = state.value.design?.test_points || []
  state.value.selectedPointIds = state.value.selectedPointIds.length === points.length ? [] : points.map(point => point.id)
}
</script>

<style scoped>
.generation-studio {
  display:flex;
  flex:1;
  flex-direction:column;
  min-height:0;
  min-width:0;
  border:1px solid var(--border-subtle);
  border-radius:14px;
  background:var(--bg-main);
  overflow:hidden;
}
.generation-steps {
  display:flex;
  gap:14px;
  padding:18px 24px;
  border-bottom:1px solid var(--border-subtle);
}
.generation-steps button {
  display:flex;
  align-items:center;
  gap:10px;
  border:0;
  background:none;
  color:var(--text-secondary);
  padding:5px 12px;
  font:inherit;
  cursor:pointer;
}
.generation-steps span {
  display:grid;
  place-items:center;
  width:27px;
  height:27px;
  border-radius:50%;
  background:var(--bg-elevated);
}
.generation-steps .active {
  color:var(--c-agent);
}
.generation-steps .active span,.generation-steps .done span {
  background:var(--t-agent);
  color:var(--c-agent);
}
.generation-steps button:disabled {
  cursor:default;
}
.studio-scroll {
  overflow:auto;
  min-height:0;
  flex:1;
  padding:26px;
}
.studio-grid {
  display:grid;
  grid-template-columns:minmax(0,1fr) 280px;
  gap:28px;
  max-width:1400px;
  margin:auto;
}
.stage-content {
  min-width:0;
}
.stage-heading {
  margin:0 0 22px;
}
.stage-heading>p {
  color:var(--c-agent);
  font-size:12px;
  font-weight:600;
  margin:0 0 8px;
}
.stage-heading h2 {
  font-size:23px;
  margin:0 0 12px;
  line-height:1.4;
}
.stage-heading>span,.stage-tip {
  font-size:13px;
  color:var(--text-secondary);
  line-height:1.8;
}
.source-fields,.test-point fieldset {
  border:0;
  padding:0;
  margin:0;
  min-width:0;
}
.source-switch {
  display:flex;
  gap:22px;
  margin-bottom:20px;
}
.source-switch label {
  display:flex;
  align-items:center;
  gap:7px;
}
.stack {
  display:flex;
  flex-direction:column;
  gap:8px;
  font-size:12px;
  color:var(--text-secondary);
  min-width:0;
}
.source-upload {
  border:1px dashed var(--border-subtle);
  border-radius:12px;
  padding:30px 18px;
  min-height:210px;
  background:var(--bg-elevated);
}
.source-upload p {
  line-height:1.7;
}
.source-upload small {
  color:var(--text-secondary);
}
input:not([type=checkbox]):not([type=radio]):not([type=file]),textarea,select {
  box-sizing:border-box;
  width:100%;
  border:1px solid var(--border-subtle);
  border-radius:8px;
  padding:10px 12px;
  background:var(--bg-main);
  color:var(--text-primary);
  font:inherit;
}
textarea {
  resize:vertical;
  line-height:1.75;
}
input:focus,textarea:focus,select:focus,button:focus-visible {
  outline:2px solid var(--c-agent);
  outline-offset:2px;
}
.aside-card {
  border:1px solid var(--border-subtle);
  border-radius:12px;
  padding:18px;
  margin-bottom:16px;
  background:var(--bg-elevated);
}
.aside-card h3 {
  margin:0 0 16px;
  font-size:14px;
}
.aside-card p,.aside-card details {
  font-size:12px;
  line-height:1.8;
  color:var(--text-secondary);
}
.aside-card summary {
  cursor:pointer;
}
.aside-card a {
  color:var(--c-agent);
}
.strategy-fields {
  display:grid;
  gap:9px;
}
.strategy-fields label {
  display:flex;
  align-items:center;
  justify-content:space-between;
  font-size:12px;
}
.strategy-fields span {
  display:flex;
  align-items:center;
  gap:6px;
  width:90px;
}
.strategy-fields input {
  padding:6px!important;
}
.invalid,.studio-error {
  color:#b45309;
}
.studio-error {
  padding:12px 16px;
  border:1px solid #f0bc88;
  border-radius:9px;
  margin-bottom:18px;
  line-height:1.6;
}
.design-questions {
  border:1px solid #edc995;
  background:var(--bg-elevated);
  border-radius:10px;
  padding:16px;
  line-height:1.7;
  margin-bottom:18px;
}
.design-questions p {
  margin:6px 0;
}
.design-questions small {
  color:var(--text-secondary);
}
.point-toolbar {
  display:flex;
  justify-content:space-between;
  gap:12px;
  align-items:center;
  margin-bottom:14px;
}
.test-point {
  border:1px solid var(--border-subtle);
  border-radius:12px;
  padding:18px;
  margin-bottom:16px;
}
.test-point.excluded {
  opacity:.65;
}
.test-point header {
  display:flex;
  justify-content:space-between;
  font-size:12px;
  margin-bottom:14px;
}
.test-point header label {
  display:flex;
  align-items:center;
  gap:7px;
}
.risk-high {
  color:#b45309;
}
.risk-medium {
  color:var(--c-agent);
}
.risk-low {
  color:var(--text-secondary);
}
.point-options {
  display:grid;
  grid-template-columns:2fr 1fr;
  gap:12px;
  margin:12px 0;
}
.test-point blockquote {
  margin:14px 0;
  padding:10px 13px;
  background:var(--bg-elevated);
  border-left:3px solid var(--c-agent);
  font-size:12px;
  line-height:1.7;
  overflow-wrap:anywhere;
}
.test-point blockquote p {
  margin:4px 0;
}
.test-point .stack+.stack {
  margin-top:12px;
}
.save-target>label {
  display:block;
  font-size:13px;
  line-height:1.7;
  margin:12px 0;
}
.save-target>.stack {
  display:flex;
}
.studio-footer {
  display:flex;
  align-items:center;
  gap:10px;
  padding:16px 22px;
  border-top:1px solid var(--border-subtle);
  background:var(--bg-main);
}
.footer-status {
  flex:1;
  color:var(--text-secondary);
  font-size:12px;
  line-height:1.6;
}
.studio-footer button {
  white-space:nowrap;
}
@media(max-width:1050px) {
  .studio-grid {
    grid-template-columns:minmax(0,1fr) 235px;
    gap:18px;
  }
  .studio-scroll {
    padding:18px;
  }
  .generation-steps {
    padding:12px;
  }
  .generation-steps button {
    padding:5px;
  }
}
@media(max-width:760px) {
  .studio-grid {
    display:flex;
    flex-direction:column;
  }
  .studio-aside {
    order:-1;
    display:grid;
    grid-template-columns:1fr;
    gap:10px;
  }
  .aside-card {
    margin:0;
    padding:14px;
  }
  .studio-scroll {
    padding:14px;
  }
  .generation-steps {
    gap:3px;
    justify-content:space-between;
  }
  .generation-steps button {
    gap:5px;
    font-size:11px;
  }
  .generation-steps span {
    width:23px;
    height:23px;
  }
  .studio-footer {
    flex-wrap:wrap;
    padding:12px;
  }
  .footer-status {
    order:3;
    flex-basis:100%;
  }
  .stage-heading h2 {
    font-size:19px;
  }
  .source-switch {
    flex-wrap:wrap;
  }
  .point-options {
    grid-template-columns:1fr;
  }
}
</style>
