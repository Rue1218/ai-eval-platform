<template>
  <div class="cases-workbench">
    <div class="ft-layout">
      <!-- 左侧：目录树侧边栏 -->
      <div class="ft-sidebar">
        <div class="ft-header">
          <div class="row-between mb8">
            <span style="font-weight: 600; font-size: 13px">用例集目录</span>
            <button class="btn btn-secondary btn-sm" style="font-size: 11px" @click="handleCreateCaseSet">+ 新建集</button>
          </div>
          <input v-model="treeSearch" class="input" placeholder="搜索用例集..." style="height: 30px; font-size: 12px" />
        </div>

        <div class="ft-tree">
          <div v-for="folder in filteredFolders" :key="folder.id">
            <div class="ft-node folder" @click="folder.open = !folder.open">
              <span class="ft-icon">{{ folder.open ? '▾' : '▸' }}</span>
              <span>📁 {{ folder.name }}</span>
              <span class="ft-badge">{{ folder.items.length }}</span>
            </div>

            <div v-if="folder.open" class="ft-folder-child">
              <div
                v-for="item in folder.items"
                :key="item.id"
                class="ft-node"
                :class="{ active: activeSetId === item.id }"
                @click="selectCaseSet(item.id)"
              >
                <span class="ft-icon">📋</span>
                <span style="overflow: hidden; text-overflow: ellipsis; white-space: nowrap">{{ item.name }}</span>
                <span
                  class="badge"
                  :class="item.status === 'confirmed' ? 'badge-succeeded' : item.status === 'cancelled' ? 'badge-cancelled' : 'badge-awaiting_case_confirm'"
                  style="font-size: 10px; padding: 1px 5px; margin-left: auto"
                >
                  {{ item.status === 'confirmed' ? '已入库' : item.status === 'cancelled' ? '已废弃' : '待确认' }}
                </span>
              </div>
            </div>
          </div>
        </div>
      </div>

      <!-- 右侧：用例数据表格工作台 -->
      <div v-if="currentSet" class="workspace-main">
        <!-- 1. 顶部工具栏 -->
        <div class="ws-toolbar">
          <div class="row" style="gap: 8px; align-items: center">
            <span style="font-weight: 700; font-size: 15px">{{ currentSet.name }}</span>
            <span class="tag-soft">生成 <b class="num mono">{{ currentSet.generated_count }}</b> 条</span>
            <span class="tag-soft" style="color: var(--accent-warning); border-color: #FDE68A">
              {{ currentSet.status === 'confirmed' ? '✓ 已入库' : currentSet.status === 'cancelled' ? '已废弃' : `72h 倒计时: 剩 ${Math.floor(currentSet.expires_in_h || 70)}h` }}
            </span>
            <span class="tag-soft" :style="modeTagStyle">{{ modeMappingLabel }}</span>
          </div>

          <div class="row" style="gap: 8px; align-items: center; margin-left: auto; flex-wrap: wrap; justify-content: flex-end">
            <button class="btn btn-secondary btn-sm" @click="addCase">+ 新增用例</button>
            <button class="btn btn-ai btn-sm" @click="handleAiGenCases">✨ AI 生成用例集</button>
            <button class="btn btn-ai btn-sm" @click="handleAiFillCase">AI 补全断言</button>
            <button class="btn btn-secondary btn-sm" :disabled="!hasUnsavedChanges || savingCases" @click="persistCases">
              {{ savingCases ? '保存中…' : '保存修改' }}
            </button>
            <button class="btn btn-secondary btn-sm" @click="exportXlsx">导出 xlsx</button>
            <button class="btn btn-secondary btn-sm" @click="exportXmind">导出 xmind</button>
            <button
              v-if="currentSet.status === 'generated'"
              class="btn btn-sign btn-sm"
              @click="confirmAllCases"
            >
              确认入库
            </button>
          </div>
        </div>

        <!-- 2. 策略分布与 AI 自检横幅 -->
        <div class="strategy-banner">
          <span class="tertiary" style="font-weight: 600">策略覆盖分布:</span>
          <div class="row wrap" style="gap: 6px">
            <span v-for="st in strategyCounts" :key="st.name" class="tag-soft" style="font-size: 11px">
              {{ st.name }} <b class="num mono">{{ st.count }}</b>
            </span>
          </div>
          <span class="grow"></span>
          <span v-if="currentSet.checks?.length" class="badge badge-failed" style="font-size: 11px">
            ⚠ 自检: {{ currentSet.checks.map(c => c.message).join('; ') }}
          </span>
          <span v-else class="st-ok small">✓ 策略自检通过</span>
        </div>

        <!-- 3. 用例表格数据网格 -->
        <div class="ws-grid-container">
          <table class="ds-table">
            <thead>
              <tr>
                <th style="width: 40px"><input type="checkbox" checked /></th>
                <th style="width: 75px">策略</th>
                <th style="width: 65px">级别</th>
                <th style="min-width: 90px">模块</th>
                <th style="min-width: 180px">用例名称 <i class="req" style="color: var(--accent-error)">*</i></th>
                <th style="min-width: 220px">预期结果 <i class="req" style="color: var(--accent-error)">*</i></th>
                <th style="min-width: 140px">前置条件</th>
                <th style="width: 90px">映射状态</th>
                <th style="width: 75px; text-align: right">操作</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="(c, idx) in cases" :key="c.id">
                <td><input v-model="selectedCaseIds" type="checkbox" :value="c.id" /></td>
                <td class="cell-edit">
                  <span class="kind-tag" :class="getStrategyTagClass(c.strategy)">{{ c.strategy }}</span>
                </td>
                <td class="cell-edit">
                  <span class="prio" :class="`prio-${c.priority}`">{{ c.priority }}</span>
                </td>
                <td class="cell-edit" @click="editCell(c, 'module')">
                  <input
                    v-if="editingCell?.row === c && editingCell?.field === 'module'"
                    v-model="c.module"
                    class="cell-input"
                    autofocus
                    @blur="finishEditing"
                    @keyup.enter="finishEditing"
                  />
                  <span v-else>{{ c.module }}</span>
                </td>
                <td class="cell-edit" @click="editCell(c, 'name')">
                  <input
                    v-if="editingCell?.row === c && editingCell?.field === 'name'"
                    v-model="c.name"
                    class="cell-input"
                    autofocus
                    @blur="finishEditing"
                    @keyup.enter="finishEditing"
                  />
                  <span v-else style="font-weight: 500">{{ c.name }}</span>
                </td>
                <td class="cell-edit" @click="editCell(c, 'expected')">
                  <input
                    v-if="editingCell?.row === c && editingCell?.field === 'expected'"
                    v-model="c.expected"
                    class="cell-input"
                    autofocus
                    @blur="finishEditing"
                    @keyup.enter="finishEditing"
                  />
                  <span v-else>{{ c.expected }}</span>
                </td>
                <td class="cell-edit" @click="editCell(c, 'precondition')">
                  <input
                    v-if="editingCell?.row === c && editingCell?.field === 'precondition'"
                    v-model="c.precondition"
                    class="cell-input"
                    autofocus
                    @blur="editingCell = null"
                    @keyup.enter="editingCell = null"
                  />
                  <span v-else class="small tertiary">{{ c.precondition || '无' }}</span>
                </td>
                <td>
                  <span v-if="c.mapped" class="badge badge-succeeded">✓ 已映射</span>
                  <span v-else class="badge badge-awaiting_case_confirm">待补全</span>
                </td>
                <td style="text-align: right">
                  <button class="link-btn danger" @click="deleteCase(idx)">删除</button>
                </td>
              </tr>
            </tbody>
          </table>
        </div>

        <!-- 4. 底部状态栏与批量映射 -->
        <div class="ws-status-bar">
          <span>已选 <b class="num mono">{{ selectedCaseIds.length }}</b> / {{ cases.length }} 条</span>
          <span class="tag-soft" :style="modeTagStyle">{{ modeMappingLabel }}</span>
          <select v-model="mapTargetId" class="select" style="height: 28px; padding: 2px 24px 2px 8px; font-size: 12px" :disabled="mappingTargets.length === 0">
            <option value="">选择目标</option>
            <option v-for="target in mappingTargets" :key="target.id" :value="target.id">{{ target.name }}</option>
          </select>
          <button class="btn btn-secondary btn-sm" @click="handleBatchMap">批量执行映射</button>
          <span class="grow"></span>
          <span class="tertiary">采纳率: <b class="num mono">{{ adoptionRate }}%</b></span>
        </div>
      </div>
      <div v-else class="info-strip" style="margin: 20px">
        暂无用例集。可新建空用例集，或通过 AI 生成候选后保存。
      </div>
    </div>

    <n-modal v-model:show="showCreateSetModal" preset="card" title="新建用例集" style="width: 440px">
      <div class="field">
        <label class="field-label">用例集名称 <span class="req">*</span></label>
        <n-input v-model:value="newSetName" placeholder="例如：支付模块回归用例" />
      </div>
      <template #footer>
        <div style="display: flex; justify-content: flex-end; gap: 8px">
          <n-button @click="showCreateSetModal = false">取消</n-button>
          <n-button type="primary" :loading="creatingSet" @click="createCaseSet">创建</n-button>
        </div>
      </template>
    </n-modal>

    <n-modal v-model:show="showGenerateCasesModal" preset="card" title="AI 生成用例候选" style="width: 560px">
      <div class="field">
        <label class="field-label">PRD / OpenAPI 内容 <span class="req">*</span></label>
        <n-input v-model:value="generationSource" type="textarea" :autosize="{ minRows: 6, maxRows: 10 }" placeholder="粘贴待分析的 PRD、OpenAPI 或业务约束说明" />
      </div>
      <template #footer>
        <div style="display: flex; justify-content: flex-end; gap: 8px">
          <n-button @click="showGenerateCasesModal = false">取消</n-button>
          <n-button type="primary" :loading="generatingCases" @click="generateCaseCandidates">生成候选</n-button>
        </div>
      </template>
    </n-modal>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, watch } from 'vue'
import { useMessage } from 'naive-ui'
import { api } from '../api/http'
import type { CaseSet, KnowledgeBase, TestCase } from '../api/types'
import { useModeStore } from '../stores/mode'

interface MappingTarget {
  id: string
  name: string
}

const message = useMessage()
const modeStore = useModeStore()
const treeSearch = ref('')
const activeSetId = ref('')
const mapTargetId = ref('')
const mappingTargets = ref<MappingTarget[]>([])
const caseSets = ref<CaseSet[]>([])
const cases = ref<TestCase[]>([])
const selectedCaseIds = ref<string[]>([])
const savingCases = ref(false)
const hasUnsavedChanges = ref(false)
const editingCell = ref<{ row: TestCase; field: keyof TestCase } | null>(null)
const showCreateSetModal = ref(false)
const newSetName = ref('')
const creatingSet = ref(false)
const showGenerateCasesModal = ref(false)
const generationSource = ref('')
const generatingCases = ref(false)
const folders = ref([{ id: 'case-sets', name: '用例集', open: true, items: [] as Array<{ id: string; name: string; status: CaseSet['status'] }> }])

const currentSet = computed(() => caseSets.value.find(item => item.id === activeSetId.value) || caseSets.value[0])
const filteredFolders = computed(() => {
  const keyword = treeSearch.value.trim().toLowerCase()
  if (!keyword) return folders.value
  return folders.value.map(folder => ({
    ...folder,
    items: folder.items.filter(item => item.name.toLowerCase().includes(keyword)),
  })).filter(folder => folder.items.length > 0)
})
const strategyCounts = computed(() => {
  const strategies: TestCase['strategy'][] = ['正向', '反向', '边界', '状态', '场景']
  return strategies.map(strategy => ({ name: strategy, count: cases.value.filter(item => item.strategy === strategy).length }))
})
const adoptionRate = computed(() => Math.round((cases.value.filter(item => item.mapped).length / (cases.value.length || 1)) * 100))
// 映射目标由全局业务模式固定：大模型用例写入基准数据集，RAG 用例写入黄金 QA。
const mapTarget = computed<'dataset' | 'gold_qa'>(() => modeStore.mode === 'rag' ? 'gold_qa' : 'dataset')
const modeMappingLabel = computed(() => modeStore.mode === 'rag' ? '映射至黄金 QA' : '映射至基准数据集')
const modeTagStyle = computed(() => ({
  color: modeStore.mode === 'rag' ? 'var(--c-kb)' : 'var(--c-datasets)',
  borderColor: modeStore.mode === 'rag' ? 'var(--t-kb)' : 'var(--t-datasets)',
}))

// 目录树由接口用例集清单驱动，避免保留原型中的固定名称与状态。
function syncCaseSetTree(list: CaseSet[]) {
  folders.value[0].items = list.map(item => ({ id: item.id, name: item.name, status: item.status }))
}

function editCell(row: TestCase, field: keyof TestCase) {
  // 已确认用例集不可编辑，浏览器侧提前阻止无效编辑操作。
  if (currentSet.value?.status === 'confirmed') return
  editingCell.value = { row, field }
}

function finishEditing() {
  // 失焦后只标记待保存，不在浏览器中假装已持久化。
  editingCell.value = null
  hasUnsavedChanges.value = true
}

// 切换用例集时拉取详情与具体用例，不复用上一套的本地编辑内容。
async function selectCaseSet(id: string) {
  activeSetId.value = id
  try {
    const detail = await api.cases.getSet(id)
    const index = caseSets.value.findIndex(item => item.id === id)
    if (index !== -1) caseSets.value[index] = { ...caseSets.value[index], ...detail }
    cases.value = detail.cases || []
    selectedCaseIds.value = cases.value.filter(item => item.selected || !item.pending).map(item => item.id)
    hasUnsavedChanges.value = false
  } catch (err: any) {
    cases.value = []
    selectedCaseIds.value = []
    message.error(err.message || '加载用例集详情失败')
  }
}

function getStrategyTagClass(strategy: TestCase['strategy']) {
  // 将既定五类策略映射到现有视觉令牌。
  switch (strategy) {
    case '正向': return 'kind-testcase'
    case '反向': return 'kind-stress'
    case '边界': return 'kind-profiles'
    case '状态': return 'kind-benchmark'
    default: return 'kind-rag'
  }
}

function addCase() {
  // 新增空白用例，填写后需通过保存按钮提交。
  if (!currentSet.value || currentSet.value.status === 'confirmed') return
  const item: TestCase = {
    id: `c-${Date.now()}`,
    strategy: '正向',
    priority: 'P1',
    module: '通用',
    name: '',
    expected: '',
    precondition: '',
    mapped: false,
    pending: false,
  }
  cases.value.push(item)
  selectedCaseIds.value.push(item.id)
  hasUnsavedChanges.value = true
  message.info('已新增空白用例，填写后点击“保存修改”落库')
}

function deleteCase(index: number) {
  // 删除在保存前仅影响本地编辑态，避免误删服务端快照。
  if (currentSet.value?.status === 'confirmed') return
  const [removed] = cases.value.splice(index, 1)
  if (removed) selectedCaseIds.value = selectedCaseIds.value.filter(id => id !== removed.id)
  hasUnsavedChanges.value = true
  message.info('已删除用例，点击“保存修改”后生效')
}

// 保存全部编辑用例，已确认用例集的不可修改规则由后端作最终校验。
async function persistCases(): Promise<boolean> {
  if (!currentSet.value || savingCases.value) return false
  savingCases.value = true
  try {
    const saved = await api.cases.saveCases(currentSet.value.id, cases.value)
    cases.value = saved
    const set = caseSets.value.find(item => item.id === currentSet.value!.id)
    if (set) set.generated_count = saved.length
    hasUnsavedChanges.value = false
    message.success('用例修改已保存')
    return true
  } catch (err: any) {
    message.error(err.message || '保存用例失败')
    return false
  } finally {
    savingCases.value = false
  }
}

function handleCreateCaseSet() {
  // 每次打开新建弹窗清空上一次未提交的名称。
  newSetName.value = ''
  showCreateSetModal.value = true
}

// 新建空用例集只在接口成功后更新目录树，避免“创建成功”假象。
async function createCaseSet() {
  const name = newSetName.value.trim()
  if (!name) {
    message.warning('请输入用例集名称')
    return
  }
  creatingSet.value = true
  try {
    const created = await api.cases.createSet({ name })
    caseSets.value.unshift(created)
    syncCaseSetTree(caseSets.value)
    showCreateSetModal.value = false
    await selectCaseSet(created.id)
    message.success('用例集已创建')
  } catch (err: any) {
    message.error(err.message || '创建用例集失败')
  } finally {
    creatingSet.value = false
  }
}

function handleAiGenCases() {
  // 生成前必须由用户提供 PRD 或 OpenAPI 文本。
  generationSource.value = ''
  showGenerateCasesModal.value = true
}

// API 仅返回候选；将候选加入当前表格供人工审核，用户保存后才会实际入库。
async function generateCaseCandidates() {
  if (!currentSet.value) {
    message.warning('请先新建或选择用例集')
    return
  }
  if (!generationSource.value.trim()) {
    message.warning('请输入 PRD、OpenAPI 或业务约束内容')
    return
  }
  generatingCases.value = true
  try {
    const candidates = await api.cases.generateCases({ source_text: generationSource.value.trim(), max_count: 45 })
    cases.value.push(...candidates.map(item => ({ ...item, id: item.id || `c-${Date.now()}`, mapped: false, pending: false })))
    selectedCaseIds.value = cases.value.map(item => item.id)
    hasUnsavedChanges.value = candidates.length > 0 || hasUnsavedChanges.value
    showGenerateCasesModal.value = false
    message.success(`已加入 ${candidates.length} 条 AI 候选，请审核后保存`)
  } catch (err: any) {
    message.error(err.message || 'AI 生成候选失败')
  } finally {
    generatingCases.value = false
  }
}

// 契约没有定义单独的“AI 补全断言”写接口，不能在浏览器伪造已补全状态。
function handleAiFillCase() {
  message.warning('请使用“AI 生成用例集”补充候选；单独补全断言接口尚未提供')
}

// 确认前先保存未提交编辑，再用实际映射目标完成确认入库。
async function confirmAllCases() {
  if (!currentSet.value) return
  if (!mapTargetId.value) {
    message.warning('请选择确认入库的映射目标')
    return
  }
  if (hasUnsavedChanges.value && !await persistCases()) return
  try {
    await api.cases.confirmSet(currentSet.value.id, {
      ok: true,
      edits: cases.value,
      mapping_target: mapTarget.value,
      target_id: mapTargetId.value,
    })
    await selectCaseSet(currentSet.value.id)
    message.success('用例集已正式确认入库')
  } catch (err: any) {
    message.error(err.message || '确认用例集失败')
  }
}

// 批量映射严格提交选中用例与目标 ID，不再把全部本地行标记为已映射。
async function handleBatchMap() {
  if (!currentSet.value) return
  if (!mapTargetId.value) {
    message.warning('请选择映射目标')
    return
  }
  if (!selectedCaseIds.value.length) {
    message.warning('请至少选择一条用例')
    return
  }
  try {
    await api.cases.mapCases(currentSet.value.id, {
      target: mapTarget.value,
      target_id: mapTargetId.value,
      case_ids: selectedCaseIds.value,
    })
    cases.value = cases.value.map(item => selectedCaseIds.value.includes(item.id) ? { ...item, mapped: true, pending: false } : item)
    message.success(`已映射 ${selectedCaseIds.value.length} 条用例`)
  } catch (err: any) {
    message.error(err.message || '批量映射失败')
  }
}

// 拉取当前映射类型的实际可选目标，防止使用原型中写死的目标标识。
async function loadMappingTargets() {
  mapTargetId.value = ''
  try {
    if (mapTarget.value === 'dataset') {
      mappingTargets.value = (await api.datasets.list()).map(item => ({ id: item.id, name: `${item.name} · v${item.version}` }))
      return
    }
    const kbs: KnowledgeBase[] = await api.kb.list()
    const qaLists = await Promise.all(kbs.map(async kb => api.kb.getGoldQA(kb.id)))
    mappingTargets.value = qaLists.flat().map(item => ({ id: item.id, name: `${item.name} · v${item.version}` }))
  } catch (err: any) {
    mappingTargets.value = []
    message.error(err.message || '加载映射目标失败')
  }
}

// 服务端负责生成规范导出文件，页面只负责下载二进制结果。
async function downloadCaseSet(fmt: 'xlsx' | 'xmind') {
  if (!currentSet.value) return
  try {
    const blob = await api.cases.exportSet(currentSet.value.id, fmt)
    const url = URL.createObjectURL(blob)
    const anchor = document.createElement('a')
    anchor.href = url
    anchor.download = `${currentSet.value.name}.${fmt}`
    anchor.click()
    URL.revokeObjectURL(url)
    message.success(`用例集已导出为 ${fmt}`)
  } catch (err: any) {
    message.error(err.message || '导出用例集失败')
  }
}

function exportXlsx() {
  // 触发服务端 Excel 导出。
  void downloadCaseSet('xlsx')
}

function exportXmind() {
  // 触发服务端脑图导出。
  void downloadCaseSet('xmind')
}

async function loadCaseSets() {
  try {
    const list = await api.cases.listSets()
    caseSets.value = list
    syncCaseSetTree(list)
    const selected = list.find(item => item.id === activeSetId.value) || list[0]
    if (selected) await selectCaseSet(selected.id)
    else cases.value = []
  } catch (err: any) {
    caseSets.value = []
    cases.value = []
    syncCaseSetTree([])
    message.error(err.message || '加载用例集失败')
  }
}

onMounted(() => {
  void loadCaseSets()
  void loadMappingTargets()
})

// 模式变化后强制清空原目标，并只加载当前业务链路允许映射的资产。
watch(() => modeStore.mode, () => {
  void loadMappingTargets()
})
</script>

<style scoped>
.cases-workbench {
  height: calc(100vh - var(--topbar-h) - 20px);
}
.ft-layout {
  display: grid;
  grid-template-columns: 260px 1fr;
  height: 100%;
  min-width: 0;
  background: var(--bg-main);
  border-radius: 14px;
  overflow: hidden;
  border: 1px solid var(--border-subtle);
}
.ft-sidebar {
  border-right: 1px solid var(--border-subtle);
  background: var(--bg-elevated);
  display: flex;
  flex-direction: column;
  height: 100%;
}
.ft-header {
  padding: 12px 14px;
  border-bottom: 1px solid var(--border-subtle);
}
.ft-tree {
  flex: 1;
  overflow-y: auto;
  padding: 10px 8px;
}
.ft-node {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 7px 10px;
  border-radius: 8px;
  font-size: 13px;
  cursor: pointer;
  transition: all 0.12s ease;
}
.ft-node:hover {
  background: rgba(17, 24, 39, 0.04);
}
.ft-node.active {
  background: color-mix(in srgb, var(--accent-ai) 12%, var(--bg-main));
  color: var(--accent-ai);
  font-weight: 600;
}
.ft-node.folder {
  font-weight: 600;
  color: var(--text-secondary);
}
.ft-folder-child {
  padding-left: 14px;
  display: flex;
  flex-direction: column;
  gap: 2px;
}
.ft-icon {
  width: 16px;
  height: 16px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  flex: 0 0 16px;
}
.ft-badge {
  margin-left: auto;
  font-family: var(--font-mono);
  font-size: 11px;
  color: var(--text-tertiary);
}
.workspace-main {
  display: flex;
  flex-direction: column;
  height: 100%;
  min-width: 0;
  min-height: 0;
  background: var(--bg-main);
}
.ws-toolbar {
  padding: 10px 16px;
  border-bottom: 1px solid var(--border-subtle);
  display: flex;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
}
.strategy-banner {
  padding: 8px 16px;
  background: color-mix(in srgb, var(--accent-ai) 4%, var(--bg-main));
  border-bottom: 1px solid var(--border-subtle);
  display: flex;
  align-items: center;
  gap: 16px;
  font-size: 12.5px;
}
.ws-grid-container {
  flex: 1;
  min-width: 0;
  overflow: auto;
}
.ws-status-bar {
  padding: 8px 16px;
  border-top: 1px solid var(--border-subtle);
  display: flex;
  align-items: center;
  gap: 16px;
  font-family: var(--font-mono);
  font-size: 12px;
  background: var(--bg-elevated);
  color: var(--text-secondary);
}
.prio {
  font-family: var(--font-mono);
  font-weight: 700;
  font-size: 11px;
  padding: 1px 6px;
  border-radius: 4px;
}
.prio-P0 { background: #FEE2E2; color: #DC2626; }
.prio-P1 { background: #FEF3C7; color: #D97706; }
.prio-P2 { background: #E0E7FF; color: #4F46E5; }
.prio-P3 { background: #F3F4F6; color: #6B7280; }
.st-ok {
  color: var(--accent-success);
}
@media (max-width: 900px) {
  .cases-workbench {
    height: auto;
    min-height: calc(100dvh - var(--topbar-h) - 24px);
  }
  .ft-layout {
    grid-template-columns: 1fr;
    height: auto;
    overflow: visible;
  }
  .ft-sidebar {
    max-height: 250px;
    border-right: 0;
    border-bottom: 1px solid var(--border-subtle);
  }
  .workspace-main {
    min-height: 660px;
  }
  .ws-toolbar .row:last-child {
    width: 100%;
    margin-left: 0 !important;
    justify-content: flex-start !important;
  }
  .strategy-banner,
  .ws-status-bar {
    flex-wrap: wrap;
    gap: 8px;
  }
}
</style>
