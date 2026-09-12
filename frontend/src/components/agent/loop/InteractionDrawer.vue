<template>
  <section
    class="interaction-drawer"
    :class="`is-${interaction.kind}`"
    role="dialog"
    :aria-label="title"
    aria-live="polite"
  >
    <header class="interaction-drawer-head">
      <div>
        <span class="interaction-kicker">{{ interaction.kind === 'approval' ? '工具权限' : '需要你的回答' }}</span>
        <h3>{{ title }}</h3>
      </div>
      <span class="interaction-state">{{ interaction.submitting ? '正在提交' : '等待处理' }}</span>
    </header>

    <template v-if="interaction.restricted">
      <p class="interaction-notice">交互内容受权限限制，无法在当前连接中处理。</p>
    </template>
    <template v-else-if="interaction.kind === 'approval'">
      <p class="interaction-summary">{{ interaction.name ? `工具“${interaction.name}”需要你的授权后才能继续。` : '该工具需要你的授权后才能继续。' }}</p>
      <dl class="approval-details">
        <template v-if="interaction.permission_tier">
          <dt>权限档位</dt>
          <dd>{{ tierLabels[interaction.permission_tier] || interaction.permission_tier }}</dd>
        </template>
        <template v-if="interaction.risk_level">
          <dt>风险等级</dt>
          <dd>{{ interaction.risk_level }}</dd>
        </template>
      </dl>
      <pre v-if="interaction.display" class="approval-preview">{{ JSON.stringify(interaction.display, null, 2) }}</pre>
      <div class="interaction-actions">
        <button class="interaction-primary" type="button" :disabled="disabled" @click="respond({ decision: 'allow' })">允许一次</button>
        <button type="button" :disabled="disabled" @click="respond({ decision: 'deny' })">拒绝</button>
        <button type="button" :disabled="disabled" @click="respond({ decision: 'always' })">本连接持续允许</button>
      </div>
    </template>
    <form v-else class="question-form" @submit.prevent="submitAnswers">
      <p class="interaction-summary">请补充以下信息，回答会作为当前工具的结果继续本轮执行。</p>
      <div class="question-progress" aria-live="polite">
        <strong>问题 {{ activeQuestionIndex + 1 }} / {{ questions.length }}</strong>
        <span>可使用上一题和下一题检查回答</span>
      </div>
      <div class="question-page-shell">
        <Transition :name="questionTransitionName">
          <fieldset v-if="currentQuestion" :key="currentQuestion.id" :disabled="disabled" class="question-fieldset question-page">
            <legend>
              <span>{{ currentQuestion.question || currentQuestion.title }}</span>
              <small>{{ questionTypeLabel(currentQuestion.type) }}{{ currentQuestion.required === false ? ' · 选填' : ' · 必答' }}</small>
            </legend>

            <template v-if="currentQuestion.type === 'text'">
              <textarea
                v-model="textValues[currentQuestion.id]"
                :aria-label="currentQuestion.question || currentQuestion.title"
                class="question-textarea"
                maxlength="16000"
                rows="3"
                placeholder="请输入你的回答…"
              />
            </template>
            <template v-else>
              <label v-for="option in currentQuestion.options || []" :key="option.label" class="choice-option">
                <input
                  :type="currentQuestion.type === 'checkbox' ? 'checkbox' : 'radio'"
                  :name="`${interaction.key}-${currentQuestion.id}`"
                  :checked="isSelected(currentQuestion.id, option.label)"
                  @change="choose(currentQuestion, option.label, ($event.target as HTMLInputElement).checked)"
                />
                <span>{{ option.label }}</span>
                <small v-if="option.description">{{ option.description }}</small>
              </label>
              <!-- 自定义答案独立传入 custom，避免伪装成服务端未提供的选项。 -->
              <label class="choice-option choice-custom">
                <input
                  :type="currentQuestion.type === 'checkbox' ? 'checkbox' : 'radio'"
                  :name="`${interaction.key}-${currentQuestion.id}`"
                  :checked="customEnabled[currentQuestion.id] === true"
                  @change="toggleCustom(currentQuestion, ($event.target as HTMLInputElement).checked)"
                />
                <span>其他，请填写</span>
                <input
                  v-model="customValues[currentQuestion.id]"
                  class="custom-answer-input"
                  :disabled="customEnabled[currentQuestion.id] !== true"
                  :aria-label="`${currentQuestion.question || currentQuestion.title}的自定义回答`"
                  maxlength="16000"
                  placeholder="输入自定义答案"
                  @focus="enableCustom(currentQuestion)"
                  @input="enableCustom(currentQuestion)"
                />
              </label>
            </template>
          </fieldset>
        </Transition>
      </div>
      <p v-if="formError" class="question-error" role="alert">{{ formError }}</p>
      <div class="interaction-actions question-navigation">
        <button type="button" :disabled="disabled || !hasPreviousQuestion" @click="moveQuestion(-1)">上一题</button>
        <button v-if="hasNextQuestion" class="interaction-primary" type="button" :disabled="disabled" @click="moveQuestion(1)">下一题</button>
        <button v-else class="interaction-primary" type="submit" :disabled="disabled">提交回答</button>
      </div>
    </form>

    <p class="interaction-hint">
      {{ interaction.submitting ? '已提交，正在等待服务端确认。' : expired ? '交互已到期，等待服务端结算。' : !canControl ? '当前连接没有控制权。' : '仅本次交互会使用这些回答。' }}
    </p>
  </section>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, reactive, ref } from 'vue'
import type { Data, InteractionRecord } from '../../../api/agentLoopTypes'

const props = defineProps<{ interaction: InteractionRecord; canControl: boolean; online: boolean }>()
const emit = defineEmits<{ respond: [InteractionRecord, Data] }>()

const now = ref(Date.now())
const timer = setInterval(() => { now.value = Date.now() }, 1000)
const selected = reactive<Record<string, string[]>>({})
const textValues = reactive<Record<string, string>>({})
const customValues = reactive<Record<string, string>>({})
const customEnabled = reactive<Record<string, boolean>>({})
const formError = ref('')
const activeQuestionIndex = ref(0)
const questionTransitionName = ref<'question-forward' | 'question-backward'>('question-forward')

const title = computed(() => props.interaction.kind === 'approval' ? '工具权限请求' : '请补充执行所需信息')
const questions = computed<Data[]>(() => Array.isArray(props.interaction.questions) ? props.interaction.questions : [])
const currentQuestion = computed<Data | null>(() => questions.value[activeQuestionIndex.value] || null)
const hasPreviousQuestion = computed(() => activeQuestionIndex.value > 0)
const hasNextQuestion = computed(() => activeQuestionIndex.value < questions.value.length - 1)
const tierLabels: Record<string, string> = { tier1: '档1 请求批准', tier2: '档2 帮我批准', tier3: '档3 完全访问' }
const expired = computed(() => props.interaction.expires_at && props.interaction.expires_at * 1000 <= now.value)
const disabled = computed(() => !props.canControl || !props.online || expired.value || props.interaction.submitting || !props.interaction.nonce)

onBeforeUnmount(() => clearInterval(timer))

/** 选择题型保持后端 radio/checkbox/text 的单一事实源。 */
function questionTypeLabel(type: string) {
  return ({ radio: '单择题', checkbox: '多选题', text: '简答题' } as Record<string, string>)[type] || '简答题'
}

function isSelected(questionId: string, label: string) {
  return (selected[questionId] || []).includes(label)
}

/** 单选替换答案，多选增删答案；单选选择既有项时自动退出“其他”。 */
function choose(question: Data, label: string, checked: boolean) {
  const questionId = String(question.id)
  if (question.type === 'checkbox') {
    selected[questionId] = checked
      ? [...(selected[questionId] || []).filter(item => item !== label), label]
      : (selected[questionId] || []).filter(item => item !== label)
    return
  }
  selected[questionId] = checked ? [label] : []
  customEnabled[questionId] = false
}

/** 其他选项可与多选并存；单选选择其他时清空既有选项。 */
function toggleCustom(question: Data, checked: boolean) {
  const questionId = String(question.id)
  customEnabled[questionId] = checked
  if (question.type !== 'checkbox' && checked) selected[questionId] = []
}

function enableCustom(question: Data) {
  const questionId = String(question.id)
  customEnabled[questionId] = true
  if (question.type !== 'checkbox') selected[questionId] = []
}

function answerFor(question: Data): { question_id: string; answer: string | string[]; custom?: string } {
  const questionId = String(question.id)
  const custom = question.type === 'text'
    ? (textValues[questionId] || '').trim()
    : customEnabled[questionId] ? (customValues[questionId] || '').trim() : ''
  if (question.type === 'checkbox') {
    return { question_id: questionId, answer: selected[questionId] || [], custom }
  }
  if (question.type === 'text') return { question_id: questionId, answer: '', custom }
  return { question_id: questionId, answer: selected[questionId]?.[0] || '', custom }
}

function hasAnswer(question: Data, answer: { answer: string | string[]; custom?: string }) {
  if (question.type === 'checkbox') return (answer.answer as string[]).length > 0 || !!answer.custom
  return !!answer.answer || !!answer.custom
}

/** 切换题目不丢弃已填写答案；统一在最终提交时校验全部必答题。 */
function moveQuestion(direction: -1 | 1) {
  const next = activeQuestionIndex.value + direction
  if (next < 0 || next >= questions.value.length) return
  questionTransitionName.value = direction === 1 ? 'question-forward' : 'question-backward'
  activeQuestionIndex.value = next
  formError.value = ''
}

/** 提交前只做题面必填校验，并将焦点留在首个缺答题；服务端仍作权威校验。 */
function submitAnswers() {
  const answers = questions.value.map(answerFor)
  const missingIndex = questions.value.findIndex((question, index) => question.required !== false && !hasAnswer(question, answers[index]))
  if (missingIndex >= 0) {
    const missing = questions.value[missingIndex]
    questionTransitionName.value = missingIndex < activeQuestionIndex.value ? 'question-backward' : 'question-forward'
    activeQuestionIndex.value = missingIndex
    formError.value = `请回答：${missing.question || missing.title}`
    return
  }
  formError.value = ''
  emit('respond', props.interaction, { answers })
}

function respond(data: Data) {
  if (!disabled.value) emit('respond', props.interaction, data)
}
</script>

<style scoped>
.interaction-drawer{max-height:min(54vh,480px);overflow:auto;border:1px solid #cbded4;border-radius:14px;background:linear-gradient(135deg,#fbfefc,#f4faf6);box-shadow:0 -12px 32px rgba(18,65,48,.12);padding:16px 18px 14px;color:#243b31}.interaction-drawer.is-question{border-color:#cbd9ed;background:linear-gradient(135deg,#fbfdff,#f3f8ff);box-shadow:0 -12px 32px rgba(42,87,152,.12)}.interaction-drawer-head{display:flex;align-items:flex-start;justify-content:space-between;gap:16px;padding-bottom:12px;border-bottom:1px solid #dce9e1}.is-question .interaction-drawer-head{border-color:#dbe6f5}.interaction-kicker{display:block;color:#647b6e;font-size:11px;font-weight:700;letter-spacing:.08em}.interaction-drawer h3{margin:3px 0 0;color:#173f30;font-size:16px;line-height:1.35}.interaction-state{flex:0 0 auto;border-radius:999px;background:#e3f2e9;padding:4px 8px;color:#1f7254;font-size:11px;font-weight:650}.is-question .interaction-state{background:#e7f0ff;color:#386db1}.interaction-summary{margin:12px 0;color:#496257;font-size:13px;line-height:1.55}.approval-details{display:grid;grid-template-columns:auto minmax(0,1fr);gap:5px 12px;margin:0;color:#536c60;font-size:12px}.approval-details dt{color:#7c9185}.approval-details dd{margin:0;overflow-wrap:anywhere}.approval-preview{max-height:130px;overflow:auto;margin:12px 0 0;border:1px solid #dce8e1;border-radius:8px;background:#f7fbf8;padding:9px;color:#325847;font:11px/1.55 var(--font-mono,ui-monospace,Consolas,monospace);white-space:pre-wrap}.question-form{margin-top:12px}.question-fieldset{min-width:0;margin:0;padding:12px 0;border:0;border-bottom:1px solid #dce6f2}.question-fieldset:last-of-type{border-bottom:0}.question-fieldset legend{width:100%;padding:0;color:#253b54;font-size:13px;font-weight:650;line-height:1.5}.question-fieldset legend small{margin-left:7px;color:#788ba5;font-size:11px;font-weight:500}.choice-option{display:grid;grid-template-columns:auto minmax(0,1fr);align-items:start;gap:7px;margin-top:9px;color:#405570;font-size:13px;line-height:1.45;cursor:pointer}.choice-option input[type=radio],.choice-option input[type=checkbox]{margin:3px 0 0;accent-color:#3d78c5}.choice-option small{grid-column:2;color:#7b8ea8;font-size:11px}.choice-custom{grid-template-columns:auto auto minmax(0,1fr);align-items:center}.choice-custom .custom-answer-input{min-width:0;height:29px;border:1px solid #cddbec;border-radius:7px;background:#fff;padding:4px 8px;color:#243b54;font:12px var(--font-body,inherit);outline:0}.choice-custom .custom-answer-input:focus{border-color:#4d85cf;box-shadow:0 0 0 2px rgba(77,133,207,.14)}.choice-custom .custom-answer-input:disabled{background:#f2f5f8;color:#9ba8b8;cursor:not-allowed}.question-textarea{width:100%;box-sizing:border-box;resize:vertical;margin-top:10px;border:1px solid #cddbec;border-radius:8px;background:#fff;padding:8px 9px;color:#243b54;font:13px/1.5 var(--font-body,inherit);outline:0}.question-textarea:focus{border-color:#4d85cf;box-shadow:0 0 0 2px rgba(77,133,207,.14)}.interaction-actions{display:flex;flex-wrap:wrap;gap:8px;margin-top:14px}.interaction-actions button{min-height:32px;border:1px solid #bfd3c7;border-radius:8px;background:#fff;padding:6px 11px;color:#315343;font:600 12px var(--font-body,inherit);cursor:pointer}.interaction-actions .interaction-primary{border-color:#1e7455;background:#1f7858;color:#fff}.is-question .interaction-actions button{border-color:#c7d6e9;color:#315272}.is-question .interaction-actions .interaction-primary{border-color:#437dc6;background:#447fc8;color:#fff}.interaction-actions button:disabled{opacity:.52;cursor:not-allowed}.question-error{margin:10px 0 0;color:#b34b3d;font-size:12px}.interaction-hint{margin:11px 0 0;color:#718479;font-size:11px;line-height:1.45}.interaction-notice{margin:14px 0 0;color:#8c6136;font-size:13px}@media(max-width:768px){.interaction-drawer{max-height:min(56vh,460px);border-radius:12px;padding:14px}.interaction-drawer-head{gap:8px}.choice-custom{grid-template-columns:auto minmax(0,1fr)}.choice-custom .custom-answer-input{grid-column:2;width:100%}.interaction-actions button{flex:1 1 120px}}[data-theme='dark'] .interaction-drawer{border-color:rgba(74,180,132,.32);background:linear-gradient(135deg,#112820,#10241d);box-shadow:0 -12px 32px rgba(0,0,0,.35);color:#d3e9dc}[data-theme='dark'] .interaction-drawer.is-question{border-color:rgba(96,165,250,.32);background:linear-gradient(135deg,#132239,#111e32)}[data-theme='dark'] .interaction-drawer h3{color:#ecfdf5}[data-theme='dark'] .interaction-kicker,[data-theme='dark'] .interaction-summary,[data-theme='dark'] .interaction-hint{color:#a9c6b4}[data-theme='dark'] .is-question .interaction-summary,[data-theme='dark'] .is-question .interaction-hint{color:#b8cce8}[data-theme='dark'] .interaction-drawer-head,.is-question .interaction-drawer-head{border-color:rgba(255,255,255,.1)}[data-theme='dark'] .approval-preview{border-color:rgba(255,255,255,.1);background:#0c1b15;color:#bce7ce}[data-theme='dark'] .question-fieldset{border-color:rgba(255,255,255,.1)}[data-theme='dark'] .question-fieldset legend{color:#d9e9ff}[data-theme='dark'] .choice-option{color:#c6d8ee}[data-theme='dark'] .choice-custom .custom-answer-input,[data-theme='dark'] .question-textarea{border-color:rgba(255,255,255,.14);background:#0b1728;color:#e5effd}
.question-progress{display:flex;align-items:center;justify-content:space-between;gap:12px;margin-top:10px;border-radius:8px;background:#edf4ff;padding:7px 9px;color:#456b9e;font-size:11px}.question-progress strong{color:#315d96;font-size:12px}.question-progress span{color:#7189aa}.question-navigation{justify-content:space-between}.question-navigation .interaction-primary{margin-left:auto}[data-theme='dark'] .question-progress{background:rgba(96,165,250,.12);color:#b8cce8}[data-theme='dark'] .question-progress strong{color:#d9e9ff}[data-theme='dark'] .question-progress span{color:#a8c0df}@media(max-width:560px){.question-progress{align-items:flex-start;flex-direction:column;gap:3px}.question-navigation button{flex:1 1 0}}
.question-page-shell{display:grid;min-width:0;overflow:hidden}.question-page{grid-area:1/1;min-width:0}.question-forward-enter-active,.question-forward-leave-active,.question-backward-enter-active,.question-backward-leave-active{transition:opacity .2s ease,transform .24s cubic-bezier(.2,.8,.2,1);will-change:opacity,transform}.question-forward-enter-from,.question-backward-leave-to{opacity:0;transform:translate3d(18px,0,0)}.question-forward-leave-to,.question-backward-enter-from{opacity:0;transform:translate3d(-18px,0,0)}.question-forward-leave-active,.question-backward-leave-active{pointer-events:none}@media(prefers-reduced-motion:reduce){.question-forward-enter-active,.question-forward-leave-active,.question-backward-enter-active,.question-backward-leave-active{transition:none}}
</style>
