<template>
  <section
    class="interaction-drawer"
    :class="[`is-${interaction.kind}`, { 'is-collapsed': isCollapsed }]"
    role="dialog"
    :aria-label="title"
    aria-live="polite"
  >
    <header class="interaction-drawer-head">
      <div class="head-title-wrap">
        <div class="head-tag-row">
          <span class="interaction-kicker">{{ interaction.kind === 'approval' ? '工具权限' : '需要你的回答' }}</span>
          <span class="interaction-state" :class="{ 'is-submitting': interaction.submitting }">
            <span class="state-dot" aria-hidden="true" />
            {{ interaction.submitting ? '正在提交' : '等待处理' }}
          </span>
        </div>
        <h3 class="head-heading">{{ title }}</h3>
      </div>
      <div class="head-controls">
        <button
          type="button"
          class="drawer-toggle-btn"
          :aria-expanded="!isCollapsed"
          :title="isCollapsed ? '展开作答面板' : '收起面板以查看上方对话'"
          @click="isCollapsed = !isCollapsed"
        >
          <span>{{ isCollapsed ? '展开' : '收起' }}</span>
          <svg class="toggle-icon" :class="{ 'is-rotated': isCollapsed }" width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" aria-hidden="true">
            <polyline points="6 9 12 15 18 9"></polyline>
          </svg>
        </button>
      </div>
    </header>

    <!-- 收起状态提示条：紧凑轻量，点击即可展开 -->
    <div
      v-if="isCollapsed"
      class="drawer-collapsed-bar"
      role="button"
      tabindex="0"
      title="点击展开作答面板"
      @click="isCollapsed = false"
      @keydown.enter="isCollapsed = false"
      @keydown.space.prevent="isCollapsed = false"
    >
      <div class="collapsed-summary">
        <span class="collapsed-badge">待作答</span>
        <span class="collapsed-text">
          {{ currentQuestion ? (currentQuestion.question || currentQuestion.title) : title }}
        </span>
        <span v-if="questions.length > 1" class="collapsed-step">（第 {{ activeQuestionIndex + 1 }} / {{ questions.length }} 题）</span>
      </div>
      <span class="collapsed-trigger">
        点击展开
        <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" aria-hidden="true">
          <polyline points="18 15 12 9 6 15"></polyline>
        </svg>
      </span>
    </div>

    <!-- 展开内容主体 -->
    <div v-show="!isCollapsed" class="drawer-body-wrap">
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
      
      <!-- 现代分段进度指示条 -->
      <div class="question-progress-wrap" aria-live="polite">
        <div class="stepper-track" aria-hidden="true">
          <div
            v-for="(_, sIdx) in questions"
            :key="sIdx"
            class="stepper-segment"
            :class="{
              'is-current': sIdx === activeQuestionIndex,
              'is-completed': isQuestionCompleted(sIdx),
              'is-upcoming': sIdx > activeQuestionIndex && !isQuestionCompleted(sIdx)
            }"
          />
        </div>
        <div class="question-progress-meta">
          <div class="progress-left">
            <strong class="progress-title">问题 {{ activeQuestionIndex + 1 }} / {{ questions.length }}</strong>
            <span v-if="currentQuestion?.type === 'checkbox'" class="type-pill is-checkbox">可多选</span>
          </div>
          <span class="progress-tip">可使用上一题和下一题检查回答</span>
        </div>
      </div>

      <div class="question-page-shell">
        <Transition :name="questionTransitionName">
          <fieldset v-if="currentQuestion" :key="currentQuestion.id" :disabled="disabled" class="question-fieldset question-page">
            <legend class="question-legend">
              <span class="question-title-text">{{ currentQuestion.question || currentQuestion.title }}</span>
              <span class="question-type-badge" :class="[`type-${currentQuestion.type}`, currentQuestion.required === false ? 'is-optional' : 'is-required']">
                {{ questionTypeLabel(currentQuestion.type) }}{{ currentQuestion.required === false ? ' · 选填' : ' · 必答' }}
              </span>
            </legend>

            <!-- 简答题 -->
            <template v-if="currentQuestion.type === 'text'">
              <div class="text-question-card">
                <textarea
                  v-model="textValues[currentQuestion.id]"
                  :aria-label="currentQuestion.question || currentQuestion.title"
                  class="question-textarea"
                  maxlength="16000"
                  rows="4"
                  placeholder="请输入你的回答…"
                  @keydown.ctrl.enter="handleTextShortcut"
                  @keydown.meta.enter="handleTextShortcut"
                />
                <div class="textarea-bar">
                  <span class="textarea-shortcut">提示：支持换行；完成可点击下方按钮</span>
                  <span class="textarea-counter">{{ (textValues[currentQuestion.id] || '').length }} / 16000</span>
                </div>
              </div>
            </template>

            <!-- 单选与多选 -->
            <template v-else>
              <div class="choices-list" role="group" :aria-label="currentQuestion.question || currentQuestion.title">
                <label
                  v-for="(option, optIdx) in currentQuestion.options || []"
                  :key="option.label"
                  class="choice-card"
                  :class="{
                    'is-selected': isSelected(currentQuestion.id, option.label),
                    'is-checkbox': currentQuestion.type === 'checkbox',
                    'is-radio': currentQuestion.type !== 'checkbox'
                  }"
                >
                  <div class="choice-header">
                    <div class="choice-badge" :class="`is-${currentQuestion.type}`">
                      <span class="choice-letter">{{ getOptionLetter(optIdx) }}</span>
                    </div>
                    <div class="choice-content">
                      <span class="choice-label">{{ option.label }}</span>
                      <small v-if="option.description" class="choice-description">{{ option.description }}</small>
                    </div>
                    <input
                      :type="currentQuestion.type === 'checkbox' ? 'checkbox' : 'radio'"
                      :name="`${interaction.key}-${currentQuestion.id}`"
                      :checked="isSelected(currentQuestion.id, option.label)"
                      class="choice-native-input"
                      @change="choose(currentQuestion, option.label, ($event.target as HTMLInputElement).checked)"
                    />
                  </div>
                </label>

                <!-- 自定义答案卡片 -->
                <label
                  class="choice-card choice-custom"
                  :class="{
                    'is-selected': customEnabled[currentQuestion.id] === true,
                    'is-checkbox': currentQuestion.type === 'checkbox',
                    'is-radio': currentQuestion.type !== 'checkbox'
                  }"
                >
                  <div class="choice-header">
                    <div class="choice-badge choice-custom-badge" :class="`is-${currentQuestion.type}`">
                      <span class="choice-letter">{{ getOptionLetter(currentQuestion.options?.length || 0) }}</span>
                    </div>
                    <div class="choice-content">
                      <span class="choice-label">其他，请填写</span>
                    </div>
                    <input
                      :type="currentQuestion.type === 'checkbox' ? 'checkbox' : 'radio'"
                      :name="`${interaction.key}-${currentQuestion.id}`"
                      :checked="customEnabled[currentQuestion.id] === true"
                      class="choice-native-input"
                      @change="toggleCustom(currentQuestion, ($event.target as HTMLInputElement).checked)"
                    />
                  </div>
                  <div class="custom-input-box">
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
                  </div>
                </label>
              </div>
            </template>
          </fieldset>
        </Transition>
      </div>

      <p v-if="formError" class="question-error" role="alert">
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="12"/><line x1="12" y1="16" x2="12.01" y2="16"/></svg>
        {{ formError }}
      </p>

      <div class="interaction-actions question-navigation">
        <button
          type="button"
          class="btn-nav btn-prev"
          :disabled="disabled || !hasPreviousQuestion"
          @click="moveQuestion(-1)"
        >
          <svg class="nav-icon" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><path d="M19 12H5M12 19l-7-7 7-7"/></svg>
          上一题
        </button>
        <button
          v-if="hasNextQuestion"
          class="interaction-primary btn-nav btn-next"
          type="button"
          :disabled="disabled"
          @click="moveQuestion(1)"
        >
          下一题
          <svg class="nav-icon" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><path d="M5 12h14M12 5l7 7-7 7"/></svg>
        </button>
        <button
          v-else
          class="interaction-primary btn-nav btn-submit"
          type="submit"
          :disabled="disabled"
        >
          <svg class="nav-icon" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" aria-hidden="true"><path d="M20 6L9 17l-5-5"/></svg>
          提交回答
        </button>
      </div>
    </form>

    <p class="interaction-hint">
      {{ interaction.submitting ? '已提交，正在等待服务端确认。' : expired ? '交互已到期，等待服务端结算。' : !canControl ? '当前连接没有控制权。' : '仅本次交互会使用这些回答。' }}
    </p>
    </div>
  </section>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, reactive, ref, watch } from 'vue'
import type { Data, InteractionRecord } from '../../../api/agentLoopTypes'

const props = defineProps<{ interaction: InteractionRecord; canControl: boolean; online: boolean }>()
const emit = defineEmits<{ respond: [InteractionRecord, Data] }>()

const isCollapsed = ref(false)
watch(() => props.interaction.submitting, (submitting) => {
  if (submitting) isCollapsed.value = false
})

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

/** 获取字母选项序号 (0 -> A, 1 -> B, ...) */
function getOptionLetter(index: number): string {
  return String.fromCharCode(65 + index)
}

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

/** 检查指定索引的题目是否已有有效答案（用于步进器高亮）。 */
function isQuestionCompleted(index: number): boolean {
  const q = questions.value[index]
  if (!q) return false
  return hasAnswer(q, answerFor(q))
}

/** 切换题目不丢弃已填写答案；统一在最终提交时校验全部必答题。 */
function moveQuestion(direction: -1 | 1) {
  const next = activeQuestionIndex.value + direction
  if (next < 0 || next >= questions.value.length) return
  questionTransitionName.value = direction === 1 ? 'question-forward' : 'question-backward'
  activeQuestionIndex.value = next
  formError.value = ''
}

/** 简答题支持快捷键下一题或提交。 */
function handleTextShortcut() {
  if (hasNextQuestion.value) {
    moveQuestion(1)
  } else {
    submitAnswers()
  }
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
.interaction-drawer {
  max-height: min(58vh, 520px);
  overflow-y: auto;
  border: 1px solid #cbded4;
  border-radius: 14px;
  background: linear-gradient(135deg, #fbfefc, #f4faf6);
  box-shadow: 0 -12px 32px rgba(18, 65, 48, 0.12);
  padding: 16px 20px;
  color: #243b31;
  transition: all 0.25s cubic-bezier(0.16, 1, 0.3, 1);
}
.interaction-drawer.is-question {
  border-color: #cbd9ed;
  background: linear-gradient(145deg, #ffffff 0%, #f6f9fc 100%);
  box-shadow: 0 -12px 32px rgba(37, 99, 235, 0.08);
}
.interaction-drawer.is-collapsed {
  max-height: none;
  overflow: visible;
  padding: 12px 18px;
  box-shadow: 0 -8px 24px rgba(37, 99, 235, 0.08);
}

.interaction-drawer-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  padding-bottom: 12px;
  border-bottom: 1px solid #e2e8f0;
}
.is-collapsed .interaction-drawer-head {
  padding-bottom: 0;
  border-bottom: none;
}
.head-title-wrap {
  display: flex;
  flex-direction: column;
  gap: 4px;
  min-width: 0;
  flex: 1 1 auto;
}
.head-tag-row {
  display: flex;
  align-items: center;
  gap: 8px;
}
.interaction-kicker {
  display: inline-block;
  color: #64748b;
  font-size: 11px;
  font-weight: 700;
  letter-spacing: 0.06em;
  text-transform: uppercase;
}
.head-heading {
  margin: 0;
  color: #0f172a;
  font-size: 17px;
  font-weight: 700;
  line-height: 1.35;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.interaction-state {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  border-radius: 999px;
  background: #eff6ff;
  padding: 3px 9px;
  color: #2563eb;
  font-size: 11px;
  font-weight: 600;
}
.interaction-state .state-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: #3b82f6;
}
.interaction-state.is-submitting .state-dot {
  background: #10b981;
  animation: pulse-dot 1.2s infinite ease-in-out;
}
@keyframes pulse-dot {
  0%, 100% { opacity: 0.4; transform: scale(0.9); }
  50% { opacity: 1; transform: scale(1.2); }
}

/* 头部收起/展开按钮 */
.head-controls {
  display: flex;
  align-items: center;
  gap: 8px;
  flex: 0 0 auto;
}
.drawer-toggle-btn {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  height: 28px;
  padding: 0 10px;
  border: 1px solid #cbd5e1;
  border-radius: 7px;
  background: #ffffff;
  color: #475569;
  font-size: 12px;
  font-weight: 600;
  cursor: pointer;
  transition: all 0.18s ease;
}
.drawer-toggle-btn:hover {
  background: #f8fafc;
  border-color: #94a3b8;
  color: #0f172a;
}
.toggle-icon {
  transition: transform 0.22s ease;
}
.toggle-icon.is-rotated {
  transform: rotate(180deg);
}

/* 折叠状态胶囊提示条 */
.drawer-collapsed-bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 14px;
  margin-top: 10px;
  padding: 9px 14px;
  border: 1px solid #bfdbfe;
  border-radius: 9px;
  background: #eff6ff;
  cursor: pointer;
  transition: all 0.2s ease;
}
.drawer-collapsed-bar:hover {
  background: #e0f2fe;
  border-color: #93c5fd;
  transform: translateY(-1px);
}
.collapsed-summary {
  display: flex;
  align-items: center;
  gap: 8px;
  min-width: 0;
  flex: 1 1 auto;
}
.collapsed-badge {
  flex: 0 0 auto;
  border-radius: 4px;
  background: #2563eb;
  padding: 2px 6px;
  color: #ffffff;
  font-size: 10.5px;
  font-weight: 600;
}
.collapsed-text {
  color: #1e293b;
  font-size: 13px;
  font-weight: 600;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.collapsed-step {
  flex: 0 0 auto;
  color: #64748b;
  font-size: 11.5px;
}
.collapsed-trigger {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  flex: 0 0 auto;
  color: #2563eb;
  font-size: 12px;
  font-weight: 600;
}

.drawer-body-wrap {
  min-width: 0;
}

.interaction-summary {
  margin: 12px 0 10px;
  color: #475569;
  font-size: 13px;
  line-height: 1.5;
}

/* 分段进度条 */
.question-progress-wrap {
  margin-top: 12px;
  margin-bottom: 4px;
  border: 1px solid #e2e8f0;
  border-radius: 10px;
  background: #f8fafc;
  padding: 10px 14px;
}
.stepper-track {
  display: flex;
  gap: 6px;
  margin-bottom: 8px;
}
.stepper-segment {
  flex: 1 1 0;
  height: 4px;
  border-radius: 999px;
  background: #e2e8f0;
  transition: all 0.25s cubic-bezier(0.16, 1, 0.3, 1);
}
.stepper-segment.is-completed {
  background: #10b981;
}
.stepper-segment.is-current {
  background: #2563eb;
  box-shadow: 0 0 6px rgba(37, 99, 235, 0.4);
}
.question-progress-meta {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}
.progress-left {
  display: flex;
  align-items: center;
  gap: 8px;
}
.progress-title {
  color: #1e293b;
  font-size: 12px;
  font-weight: 700;
}
.type-pill {
  border-radius: 4px;
  padding: 1px 6px;
  font-size: 10.5px;
  font-weight: 600;
}
.type-pill.is-checkbox {
  background: #dbeafe;
  color: #1d4ed8;
}
.progress-tip {
  color: #64748b;
  font-size: 11px;
}

/* 题目表单与翻页容器 */
.question-form {
  margin-top: 10px;
}

/* 题目间距优化关键：拉开与上方进度条的间隙 */
.question-page-shell {
  display: grid;
  min-width: 0;
  overflow: hidden;
  margin-top: 18px;
  margin-bottom: 6px;
}
.question-page {
  grid-area: 1 / 1;
  min-width: 0;
}
.question-fieldset {
  min-width: 0;
  margin: 0;
  padding: 4px 0 6px;
  border: 0;
}

/* 题干标题与标签间距排版 */
.question-legend {
  display: flex;
  align-items: center;
  justify-content: space-between;
  flex-wrap: wrap;
  gap: 12px;
  width: 100%;
  padding: 4px 0 14px;
  margin-bottom: 12px;
  border-bottom: 1px solid #eef2f6;
}
.question-title-text {
  color: #0f172a;
  font-size: 15px;
  font-weight: 700;
  line-height: 1.6;
  flex: 1 1 240px;
}
.question-type-badge {
  display: inline-flex;
  align-items: center;
  border-radius: 999px;
  padding: 2px 9px;
  font-size: 11.5px;
  font-weight: 600;
  flex: 0 0 auto;
}
.question-type-badge.is-required {
  background: #fef3c7;
  color: #b45309;
}
.question-type-badge.is-optional {
  background: #f1f5f9;
  color: #64748b;
}

/* 选项列表 */
.choices-list {
  display: flex;
  flex-direction: column;
  gap: 12px;
  margin-top: 4px;
}

.choice-card {
  position: relative;
  display: flex;
  flex-direction: column;
  padding: 13px 16px;
  border: 1.5px solid #e2e8f0;
  border-radius: 12px;
  background: #ffffff;
  cursor: pointer;
  transition: all 0.2s cubic-bezier(0.16, 1, 0.3, 1);
  box-shadow: 0 1px 2px rgba(0, 0, 0, 0.02);
}
.choice-card:hover {
  border-color: #93c5fd;
  background: #f8fafc;
  transform: translateY(-1px);
  box-shadow: 0 4px 10px rgba(37, 99, 235, 0.06);
}
.choice-card.is-selected {
  border-color: #3b82f6;
  background: #eff6ff;
  box-shadow: 0 4px 12px rgba(37, 99, 235, 0.1);
}

.choice-header {
  display: flex;
  align-items: center;
  gap: 14px;
  width: 100%;
}

/* ABCD 字母徽标 */
.choice-badge {
  flex: 0 0 28px;
  width: 28px;
  height: 28px;
  border-radius: 8px;
  background: #f1f5f9;
  color: #475569;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 13px;
  font-weight: 700;
  font-family: var(--font-mono, ui-monospace, Consolas, monospace);
  transition: all 0.2s ease;
}
.choice-badge.is-radio {
  border-radius: 50%;
}
.choice-card:hover .choice-badge {
  background: #e2e8f0;
  color: #0f172a;
}
.choice-card.is-selected .choice-badge {
  background: #2563eb;
  color: #ffffff;
  box-shadow: 0 2px 6px rgba(37, 99, 235, 0.35);
}

.choice-content {
  flex: 1 1 auto;
  min-width: 0;
}
.choice-label {
  display: block;
  color: #1e293b;
  font-size: 13.5px;
  font-weight: 500;
  line-height: 1.45;
  overflow-wrap: break-word;
}
.choice-card.is-selected .choice-label {
  color: #1d4ed8;
  font-weight: 600;
}
.choice-description {
  display: block;
  margin-top: 3px;
  color: #64748b;
  font-size: 11.5px;
  line-height: 1.4;
}

.choice-native-input {
  flex: 0 0 auto;
  width: 17px;
  height: 17px;
  margin: 0;
  accent-color: #2563eb;
  cursor: pointer;
}

/* 自定义答案卡片 */
.custom-input-box {
  margin-top: 10px;
  padding-left: 42px;
  width: 100%;
  box-sizing: border-box;
}
.custom-answer-input {
  width: 100%;
  box-sizing: border-box;
  height: 36px;
  border: 1px solid #cbd5e1;
  border-radius: 8px;
  background: #ffffff;
  padding: 6px 12px;
  color: #1e293b;
  font: 13px var(--font-body, inherit);
  outline: none;
  transition: all 0.2s ease;
}
.custom-answer-input:focus {
  border-color: #2563eb;
  box-shadow: 0 0 0 3px rgba(37, 99, 235, 0.14);
}
.custom-answer-input:disabled {
  background: #f8fafc;
  color: #94a3b8;
  cursor: not-allowed;
  border-color: #e2e8f0;
}
.choice-card.is-selected .custom-answer-input:not(:disabled) {
  border-color: #93c5fd;
}

/* 简答题卡片 */
.text-question-card {
  margin-top: 6px;
  border: 1.5px solid #e2e8f0;
  border-radius: 12px;
  background: #ffffff;
  padding: 10px 12px 8px;
  box-shadow: 0 1px 2px rgba(0, 0, 0, 0.02);
  transition: all 0.2s ease;
}
.text-question-card:focus-within {
  border-color: #3b82f6;
  box-shadow: 0 0 0 3px rgba(59, 130, 246, 0.14);
}
.question-textarea {
  width: 100%;
  box-sizing: border-box;
  resize: vertical;
  min-height: 96px;
  border: none;
  background: transparent;
  padding: 4px 2px;
  color: #0f172a;
  font: 14px/1.6 var(--font-body, inherit);
  outline: none;
}
.textarea-bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 8px 2px 2px;
  border-top: 1px solid #f1f5f9;
  color: #94a3b8;
  font-size: 11.5px;
}

/* 题目切换动画 */
.question-forward-enter-active,
.question-forward-leave-active,
.question-backward-enter-active,
.question-backward-leave-active {
  transition: opacity 0.2s ease, transform 0.24s cubic-bezier(0.16, 1, 0.3, 1);
  will-change: opacity, transform;
}
.question-forward-enter-from,
.question-backward-leave-to {
  opacity: 0;
  transform: translate3d(20px, 0, 0);
}
.question-forward-leave-to,
.question-backward-enter-from {
  opacity: 0;
  transform: translate3d(-20px, 0, 0);
}
.question-forward-leave-active,
.question-backward-leave-active {
  pointer-events: none;
}
@media (prefers-reduced-motion: reduce) {
  .question-forward-enter-active,
  .question-forward-leave-active,
  .question-backward-enter-active,
  .question-backward-leave-active {
    transition: none;
  }
}

/* 操作与导航按钮 */
.interaction-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
  margin-top: 18px;
}
.interaction-actions button {
  min-height: 36px;
  border: 1px solid #cbd5e1;
  border-radius: 8px;
  background: #ffffff;
  padding: 6px 16px;
  color: #334155;
  font: 600 13px var(--font-body, inherit);
  cursor: pointer;
  transition: all 0.18s ease;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
}
.interaction-actions button:hover:not(:disabled) {
  background: #f8fafc;
  border-color: #94a3b8;
  color: #0f172a;
}
.interaction-actions .interaction-primary {
  border-color: #2563eb;
  background: #2563eb;
  color: #ffffff;
}
.interaction-actions .interaction-primary:hover:not(:disabled) {
  border-color: #1d4ed8;
  background: #1d4ed8;
  color: #ffffff;
}
.interaction-actions button:disabled {
  opacity: 0.45;
  cursor: not-allowed;
}

.question-navigation {
  justify-content: space-between;
}
.question-navigation .interaction-primary {
  margin-left: auto;
}

.nav-icon {
  flex: 0 0 14px;
}

/* 错误与状态提示 */
.question-error {
  display: flex;
  align-items: center;
  gap: 6px;
  margin: 12px 0 0;
  color: #dc2626;
  font-size: 12px;
  font-weight: 500;
  animation: shake-err 0.3s ease-in-out;
}
@keyframes shake-err {
  0%, 100% { transform: translateX(0); }
  25% { transform: translateX(-4px); }
  75% { transform: translateX(4px); }
}

.interaction-hint {
  margin: 14px 0 0;
  color: #64748b;
  font-size: 11.5px;
  line-height: 1.45;
}
.interaction-notice {
  margin: 14px 0 0;
  color: #b45309;
  font-size: 13px;
}

/* 审批视图适配 */
.approval-details {
  display: grid;
  grid-template-columns: auto minmax(0, 1fr);
  gap: 5px 12px;
  margin: 0;
  color: #536c60;
  font-size: 12px;
}
.approval-details dt { color: #7c9185; }
.approval-details dd { margin: 0; overflow-wrap: anywhere; }
.approval-preview {
  max-height: 130px;
  overflow: auto;
  margin: 12px 0 0;
  border: 1px solid #dce8e1;
  border-radius: 8px;
  background: #f7fbf8;
  padding: 9px;
  color: #325847;
  font: 11px/1.55 var(--font-mono, ui-monospace, Consolas, monospace);
  white-space: pre-wrap;
}

/* 响应式调整 */
@media (max-width: 560px) {
  .interaction-drawer {
    padding: 14px;
    border-radius: 12px;
  }
  .question-progress-meta {
    flex-direction: column;
    align-items: flex-start;
    gap: 4px;
  }
  .custom-input-box {
    padding-left: 0;
  }
  .question-navigation button {
    flex: 1 1 0;
  }
}

/* 深色模式适配 */
[data-theme='dark'] .interaction-drawer {
  border-color: rgba(74, 180, 132, 0.32);
  background: linear-gradient(135deg, #112820, #10241d);
  box-shadow: 0 -12px 32px rgba(0, 0, 0, 0.35);
  color: #d3e9dc;
}
[data-theme='dark'] .interaction-drawer.is-question {
  border-color: rgba(96, 165, 250, 0.28);
  background: linear-gradient(145deg, #0f172a 0%, #1e293b 100%);
  box-shadow: 0 -12px 32px rgba(0, 0, 0, 0.4);
  color: #e2e8f0;
}
[data-theme='dark'] .interaction-drawer-head {
  border-color: rgba(255, 255, 255, 0.08);
}
[data-theme='dark'] .head-heading {
  color: #f8fafc;
}
[data-theme='dark'] .interaction-kicker {
  color: #94a3b8;
}
[data-theme='dark'] .drawer-toggle-btn {
  border-color: rgba(255, 255, 255, 0.12);
  background: #1e293b;
  color: #cbd5e1;
}
[data-theme='dark'] .drawer-toggle-btn:hover {
  background: #334155;
  color: #ffffff;
}
[data-theme='dark'] .drawer-collapsed-bar {
  border-color: rgba(96, 165, 250, 0.3);
  background: rgba(30, 58, 138, 0.3);
}
[data-theme='dark'] .drawer-collapsed-bar:hover {
  background: rgba(30, 58, 138, 0.45);
}
[data-theme='dark'] .collapsed-text {
  color: #f1f5f9;
}
[data-theme='dark'] .collapsed-step {
  color: #94a3b8;
}
[data-theme='dark'] .collapsed-trigger {
  color: #60a5fa;
}
[data-theme='dark'] .interaction-state {
  background: rgba(37, 99, 235, 0.2);
  color: #93c5fd;
}
[data-theme='dark'] .interaction-summary,
[data-theme='dark'] .interaction-hint {
  color: #94a3b8;
}
[data-theme='dark'] .question-progress-wrap {
  border-color: rgba(255, 255, 255, 0.08);
  background: rgba(15, 23, 42, 0.6);
}
[data-theme='dark'] .stepper-segment {
  background: rgba(255, 255, 255, 0.12);
}
[data-theme='dark'] .stepper-segment.is-completed {
  background: #10b981;
}
[data-theme='dark'] .stepper-segment.is-current {
  background: #60a5fa;
  box-shadow: 0 0 8px rgba(96, 165, 250, 0.5);
}
[data-theme='dark'] .progress-title {
  color: #f1f5f9;
}
[data-theme='dark'] .progress-tip {
  color: #64748b;
}
[data-theme='dark'] .question-legend {
  border-color: rgba(255, 255, 255, 0.08);
}
[data-theme='dark'] .question-title-text {
  color: #f8fafc;
}
[data-theme='dark'] .question-type-badge.is-optional {
  background: rgba(255, 255, 255, 0.08);
  color: #94a3b8;
}
[data-theme='dark'] .question-type-badge.is-required {
  background: rgba(245, 158, 11, 0.2);
  color: #fcd34d;
}
[data-theme='dark'] .choice-card {
  border-color: rgba(255, 255, 255, 0.1);
  background: rgba(30, 41, 59, 0.4);
}
[data-theme='dark'] .choice-card:hover {
  border-color: rgba(96, 165, 250, 0.4);
  background: rgba(30, 41, 59, 0.8);
}
[data-theme='dark'] .choice-card.is-selected {
  border-color: #3b82f6;
  background: rgba(37, 99, 235, 0.16);
}
[data-theme='dark'] .choice-badge {
  background: #1e293b;
  color: #94a3b8;
}
[data-theme='dark'] .choice-card:hover .choice-badge {
  background: #334155;
  color: #f1f5f9;
}
[data-theme='dark'] .choice-card.is-selected .choice-badge {
  background: #3b82f6;
  color: #ffffff;
}
[data-theme='dark'] .choice-label {
  color: #f1f5f9;
}
[data-theme='dark'] .choice-card.is-selected .choice-label {
  color: #93c5fd;
}
[data-theme='dark'] .choice-description {
  color: #94a3b8;
}
[data-theme='dark'] .custom-answer-input {
  border-color: rgba(255, 255, 255, 0.14);
  background: #0f172a;
  color: #f1f5f9;
}
[data-theme='dark'] .custom-answer-input:disabled {
  background: #0b1320;
  border-color: rgba(255, 255, 255, 0.06);
  color: #475569;
}
[data-theme='dark'] .text-question-card {
  border-color: rgba(255, 255, 255, 0.1);
  background: rgba(15, 23, 42, 0.6);
}
[data-theme='dark'] .text-question-card:focus-within {
  border-color: #3b82f6;
}
[data-theme='dark'] .question-textarea {
  color: #f1f5f9;
}
[data-theme='dark'] .textarea-bar {
  border-color: rgba(255, 255, 255, 0.08);
  color: #64748b;
}
[data-theme='dark'] .interaction-actions button {
  border-color: rgba(255, 255, 255, 0.14);
  background: #1e293b;
  color: #cbd5e1;
}
[data-theme='dark'] .interaction-actions button:hover:not(:disabled) {
  background: #334155;
  color: #ffffff;
}
[data-theme='dark'] .interaction-actions .interaction-primary {
  border-color: #2563eb;
  background: #2563eb;
  color: #ffffff;
}
</style>
