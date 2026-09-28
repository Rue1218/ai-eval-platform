import { computed, onScopeDispose, ref, watch } from 'vue'
import { useDialog, useMessage } from 'naive-ui'
import { api } from '../api/http'
import type { CaseDesign, CaseGenerationSkill, TestCase, TestCaseInput } from '../api/types'

/** 页面六策略与平台百分比字段保持一致。 */
export const STRATEGY_OPTIONS = [
  { label: '正向', key: 'positive', weight: 40 }, { label: '反向', key: 'negative', weight: 25 },
  { label: '边界', key: 'boundary', weight: 15 }, { label: '等价类', key: 'equivalence', weight: 10 },
  { label: '状态迁移', key: 'state', weight: 5 }, { label: '场景', key: 'scenario', weight: 5 },
] as const
export type CaseStrategy = (typeof STRATEGY_OPTIONS)[number]['label']
export type CasePriority = 'HX' | 'FHX' | 'BJ' | 'YC' | 'ZD' | 'BL'

/** 人工候选编辑独立于持久化 ID，保存仍由用例库的修订事务处理。 */
export interface AiCaseCandidate {
  selected: boolean
  code: string
  name: string
  module: string
  feature_point: string
  strategy: CaseStrategy
  priority: CasePriority
  preconditions: string
  stepsText: string
  expected_result: string
  source?: TestCase
}

/** 三阶段状态：需求、测试设计、候选审核；失败不丢弃已有人工编辑。 */
export interface CaseGenerationState {
  show: boolean
  step: 1 | 2 | 3
  prdText: string
  sourceMode: 'text' | 'file'
  sourceDocId: string
  sourceFileName: string
  sourceUploading: boolean
  sourceUploadPercent: number
  skillId: string
  design: CaseDesign | null
  selectedPointIds: string[]
  analyzing: boolean
  error: string
  strategyWeights: Record<string, number>
  count: number
  generating: boolean
  applying: boolean
  target: 'current' | 'new'
  newSetName: string
  appliedToSetId: string
  rehomePending: boolean
  appliedCaseIds: string[]
  appliedBaseSnapshot: string
  appliedBaseUnsaved: boolean
  candidates: AiCaseCandidate[]
  candidateSource: string
  candidatePointIds: string[]
}

/** 仅转换被审核的用例字段，服务端额外的追溯字段仍随正文保存。 */
export function candidatePayload(c: AiCaseCandidate): TestCaseInput {
  return { ...c.source, id: undefined, code: c.code, name: c.name.trim(), module: c.module.trim(),
    feature_point: c.feature_point.trim(), strategy: c.strategy, priority: c.priority,
    precondition: c.preconditions.trim(), steps: c.stepsText.trim(), expected: c.expected_result.trim() }
}

/** 独立管理 Skill 发现、需求分析和生成；用例集保存由调用方继续保证版本一致性。 */
export function useCaseGeneration() {
  const message = useMessage(), dialog = useDialog()
  const skills = ref<CaseGenerationSkill[]>([]), skillsLoading = ref(false), skillsError = ref('')
  const candidateVersion = ref(0)
  let active = true, requestVersion = 0
  onScopeDispose(() => { active = false; requestVersion++ })
  const aiGen = ref<CaseGenerationState>({
    show: false, step: 1, prdText: '', sourceMode: 'text', sourceDocId: '', sourceFileName: '',
    sourceUploading: false, sourceUploadPercent: 0, skillId: '', design: null, selectedPointIds: [],
    analyzing: false, error: '', count: 10, generating: false, applying: false, target: 'new', newSetName: '',
    appliedToSetId: '', rehomePending: false, appliedCaseIds: [], appliedBaseSnapshot: '', appliedBaseUnsaved: false,
    candidates: [], candidateSource: '', candidatePointIds: [], strategyWeights: Object.fromEntries(STRATEGY_OPTIONS.map(s => [s.key, s.weight])),
  })
  const aiSelectedCount = computed(() => aiGen.value.candidates.filter(c => c.selected).length)
  const sourceKey = () => JSON.stringify([aiGen.value.sourceMode, aiGen.value.prdText, aiGen.value.sourceDocId, aiGen.value.skillId])
  watch(sourceKey, () => {
    aiGen.value.design = null
    aiGen.value.selectedPointIds = []
    if (aiGen.value.step === 2) aiGen.value.step = 1
  })

  /** 失败明确展示，不把失联的技能目录当作默认技能可用。 */
  async function loadSkills() {
    if (skillsLoading.value) return
    skillsLoading.value = true; skillsError.value = ''
    try {
      const result = await api.cases.generationSkills()
      if (!active) return
      skills.value = result
      if (!result.length) throw new Error('尚未安装可用的用例生成技能')
      if (!result.some(skill => skill.id === aiGen.value.skillId)) aiGen.value.skillId = result[0]!.id
    } catch (error: any) {
      if (active) skillsError.value = error.message || '技能目录加载失败'
    } finally { if (active) skillsLoading.value = false }
  }

  /** 再次进入时恢复已有设计或候选，保留本轮尚未保存的编辑。 */
  function openAiGenDrawer() {
    aiGen.value.show = true
    aiGen.value.step = aiGen.value.generating ? 2 : aiGen.value.candidates.length ? 3 : aiGen.value.design ? 2 : 1
    if (aiGen.value.appliedToSetId) aiGen.value.target = aiGen.value.rehomePending ? 'new' : 'current'
    if (!aiGen.value.newSetName) aiGen.value.newSetName = `需求用例-${new Date().toISOString().slice(0, 10)}`
    if (!skills.value.length) void loadSkills()
  }

  /** 上传成功才替换旧来源，失败和迟到响应不能清空原需求。 */
  async function uploadSourceFile(e: Event) {
    const input = e.target as HTMLInputElement, state = aiGen.value
    if (state.generating || state.analyzing || state.applying || state.sourceUploading) return
    const file = input.files?.[0]
    if (!file) return
    if (!/\.(txt|md|csv|json|yaml|yml|xlsx)$/i.test(file.name)) {
      message.warning('仅支持 UTF-8 文本、Markdown、CSV、JSON、YAML 或 Excel 文件'); input.value = ''; return
    }
    state.sourceUploading = true; state.sourceUploadPercent = 0
    try {
      const uploaded = await api.files.upload(file, percent => { if (active) state.sourceUploadPercent = percent }, 180_000)
      if (active) { state.sourceDocId = uploaded.id; state.sourceFileName = uploaded.filename }
    } catch (error: any) { if (active) message.error(error.message || '需求文件上传失败') }
    finally { state.sourceUploading = false; input.value = '' }
  }

  /** 文本与文件来源互斥提交，避免旧文件 ID 覆盖当前粘贴内容。 */
  function sourcePayload() {
    const state = aiGen.value
    return { source_text: state.sourceMode === 'text' ? state.prdText.trim() : '', skill_id: state.skillId,
      ...(state.sourceMode === 'file' ? { source_doc_id: state.sourceDocId } : {}) }
  }

  /** 分析是独立步骤；用户必须看到测试点和待澄清项后才能展开用例。 */
  async function analyzeRequirements() {
    const state = aiGen.value
    if (state.analyzing || state.generating || state.applying || state.sourceUploading) return
    if (!skills.value.some(skill => skill.id === state.skillId)) { message.warning('请先加载并选择生成技能'); return }
    if (state.sourceMode === 'text' ? !state.prdText.trim() : !state.sourceDocId) {
      message.warning(state.sourceMode === 'text' ? '请填写需求描述' : '请先上传需求文件'); return
    }
    state.analyzing = true; state.error = ''
    const request = ++requestVersion, source = sourceKey()
    try {
      const result = await api.cases.designCases(sourcePayload())
      if (!active || request !== requestVersion || source !== sourceKey()) return
      state.design = result.design
      state.selectedPointIds = result.design.test_points.map(point => point.id)
      state.step = 2
    } catch (error: any) { if (active && request === requestVersion) state.error = error.message || '需求分析失败，请重试' }
    finally { if (active && request === requestVersion) state.analyzing = false }
  }

  /** 只发送选中的测试点；新结果成功返回前保留上次候选和人工编辑。 */
  async function runAiGenerateCases(replaceExisting = false) {
    const state = aiGen.value
    if (state.generating || state.analyzing || state.applying || state.sourceUploading || state.appliedToSetId) return
    if (!state.design || !state.selectedPointIds.length) { message.warning('请先分析需求并选择测试点'); return }
    if (!Number.isInteger(state.count) || state.count < 1 || state.count > 80) { message.warning('生成条数须为 1–80 的整数'); return }
    const weights = Object.values(state.strategyWeights)
    if (weights.some(v => !Number.isInteger(v) || v < 0 || v > 100) || weights.reduce((a, b) => a + b, 0) !== 100) {
      message.warning('六策略百分比须为 0 到 100 的整数，合计 100%'); return
    }
    if (state.candidates.length && !replaceExisting) {
      dialog.warning({ title: '重新生成候选？', content: '新结果成功返回后才替换已编辑候选，失败会保留原内容。',
        positiveText: '覆盖并重新生成', negativeText: '保留候选', onPositiveClick: () => runAiGenerateCases(true) })
      return
    }
    state.generating = true; state.error = ''
    const request = ++requestVersion
    const design = JSON.parse(JSON.stringify({ ...state.design,
      test_points: state.design.test_points.filter(point => state.selectedPointIds.includes(point.id)) })) as CaseDesign
    try {
      const generated = await api.cases.generateCases({ ...sourcePayload(), design,
        strategy_weights: { ...state.strategyWeights }, max_count: state.count })
      if (!active || request !== requestVersion) return
      if (!generated.length) throw new Error('未生成候选用例，请补充需求后重试')
      state.candidates = generated.map((c, i) => ({ selected: true, code: c.code || `TC-${String(i + 1).padStart(3, '0')}`,
        name: c.name || '', module: c.module || '通用', feature_point: c.feature_point || '',
        strategy: (c.strategy === '状态' ? '状态迁移' : c.strategy === '等价' ? '等价类' : c.strategy) as CaseStrategy,
        priority: c.priority || 'HX', preconditions: c.precondition || '',
        stepsText: Array.isArray(c.steps) ? c.steps.join('\n') : c.steps || '', expected_result: c.expected || '', source: c }))
      candidateVersion.value++
      state.candidatePointIds = design.test_points.map(point => point.id)
      state.candidateSource = state.sourceMode === 'file' ? state.sourceFileName : state.prdText.trim().slice(0, 60)
      state.appliedToSetId = ''; state.target = 'new'; state.step = 3
    } catch (error: any) { if (active && request === requestVersion) state.error = error.message || '用例生成失败，请重试' }
    finally { if (active && request === requestVersion) state.generating = false }
  }

  /** 已追加但尚未保存的候选固定采纳范围，防止重试时重复追加。 */
  function toggleAllCandidates() {
    if (aiGen.value.appliedToSetId || aiGen.value.applying || aiGen.value.generating) return
    const select = aiSelectedCount.value < aiGen.value.candidates.length
    aiGen.value.candidates.forEach(candidate => { candidate.selected = select })
  }
  return { aiGen, skills, skillsLoading, skillsError, candidateVersion, aiSelectedCount,
    loadSkills, openAiGenDrawer, uploadSourceFile, analyzeRequirements, runAiGenerateCases, toggleAllCandidates }
}
