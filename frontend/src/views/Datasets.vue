<template>
  <div class="datasets-workbench">
    <div v-if="modeStore.mode === 'rag'" class="mode-context-panel panel">
      <span class="eyebrow">RAG 测试模式</span>
      <h2>RAG 评测使用知识库与黄金 QA</h2>
      <p>基准数据集只服务于大模型对比评测。当前模式下，请在知识库工作台管理文档、切块、检索与黄金 QA，再发起 RAG 评测。</p>
      <router-link to="/kb" class="btn btn-sign btn-sm">进入知识库工作台</router-link>
    </div>

    <div v-else class="ft-layout">
      <!-- 左侧：目录树侧边栏 -->
      <div class="ft-sidebar">
        <div class="ft-header">
          <div class="row-between mb8">
            <span style="font-weight: 600; font-size: 13px">资源目录树</span>
            <button class="btn btn-secondary btn-sm" style="font-size: 11px" @click="openUploadModal(null)">+ 上传</button>
          </div>
          <input v-model="treeSearch" class="input" placeholder="搜索数据集 / 黄金 QA..." style="height: 30px; font-size: 12px" />
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
                :class="{ active: activeDatasetId === item.id }"
                @click="selectDataset(item.id)"
              >
                <span class="ft-icon">{{ item.isGoldQa ? '⭐' : '📄' }}</span>
                <span style="overflow: hidden; text-overflow: ellipsis; white-space: nowrap">{{ item.name }}</span>
                <span class="tag-soft" style="font-size: 10px; padding: 1px 5px; margin-left: auto">v{{ item.version }}</span>
                <span v-if="item.pending_complete_count > 0" class="ft-status-dot" :title="`${item.pending_complete_count} 行待补全`"></span>
              </div>
            </div>
          </div>
        </div>
      </div>

      <!-- 右侧：数据表格工作台 -->
      <div v-if="currentDataset" class="workspace-main">
        <!-- 1. 顶部工具栏 -->
        <div class="ws-toolbar">
          <div class="row" style="gap: 8px; align-items: center">
            <span style="font-weight: 700; font-size: 15px">{{ currentDataset.name }}</span>
            <span class="tag-soft" style="font-size: 11px">v{{ currentDataset.version }}</span>
            <span class="tag-soft" style="color: var(--c-datasets); border-color: var(--t-datasets)">基准数据集</span>
            <span v-if="currentDataset.pending_complete_count > 0" class="badge badge-awaiting_case_confirm">
              {{ currentDataset.pending_complete_count }} 条待补全
            </span>
          </div>

          <div class="row" style="gap: 8px; align-items: center; margin-left: auto; flex-wrap: wrap; justify-content: flex-end">
            <button class="btn btn-secondary btn-sm" @click="addRow">+ 新增行</button>
            <button class="btn btn-ai btn-sm" @click="handleAiSynthetic">✨ AI 合成新数据</button>
            <button class="btn btn-ai btn-sm" @click="handleAiFill">AI 补全缺失行</button>
            <button class="btn btn-secondary btn-sm" :disabled="!hasUnsavedChanges || savingRows" @click="persistRows">
              {{ savingRows ? '保存中…' : '保存修改' }}
            </button>
            <button class="btn btn-secondary btn-sm" @click="exportJsonl">导出 JSONL</button>
            <button class="btn btn-sign btn-sm" @click="openLaunchDrawer">发起基准评测</button>
          </div>
        </div>

        <!-- 2. 表格数据网格 -->
        <div class="ws-grid-container">
          <table class="ds-table">
            <thead>
              <tr>
                <th style="width: 44px"><input type="checkbox" checked /></th>
                <th style="width: 70px">行号</th>
                <th style="min-width: 220px">测试问句 (Question) <i class="req" style="color: var(--accent-error)">*</i></th>
                <th style="min-width: 260px">标准答案 (Reference) <i class="req" style="color: var(--accent-error)">*</i></th>
                <th style="min-width: 140px">上下文 / 前置 (Context)</th>
                <th style="min-width: 110px">标签</th>
                <th style="min-width: 90px">难度</th>
                <th style="width: 80px; text-align: right">操作</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="(r, idx) in sampleRows" :key="idx" :class="{ 'cell-bad': !r.q || !r.r }">
                <td><input type="checkbox" checked /></td>
                <td class="mono small">{{ r.row_no }}</td>
                <td class="cell-edit" @click="editCell(r, 'q')">
                  <input
                    v-if="editingCell?.row === r && editingCell?.field === 'q'"
                    v-model="r.q"
                    class="cell-input"
                    autofocus
                    @blur="finishEditing"
                    @keyup.enter="finishEditing"
                  />
                  <span v-else :style="{ color: !r.q ? 'var(--accent-error)' : undefined }">
                    {{ r.q || '（空缺失，待补全）' }}
                  </span>
                </td>
                <td class="cell-edit" @click="editCell(r, 'r')">
                  <input
                    v-if="editingCell?.row === r && editingCell?.field === 'r'"
                    v-model="r.r"
                    class="cell-input"
                    autofocus
                    @blur="finishEditing"
                    @keyup.enter="finishEditing"
                  />
                  <span v-else :style="{ color: !r.r ? 'var(--accent-error)' : undefined }">
                    {{ r.r || '（空缺失，待补全）' }}
                  </span>
                </td>
                <td class="cell-edit" @click="editCell(r, 'c')">
                  <input
                    v-if="editingCell?.row === r && editingCell?.field === 'c'"
                    v-model="r.c"
                    class="cell-input"
                    autofocus
                    @blur="finishEditing"
                    @keyup.enter="finishEditing"
                  />
                  <span v-else>{{ r.c || '—' }}</span>
                </td>
                <td class="cell-edit" @click="editCell(r, 'tags')">
                  <input
                    v-if="editingCell?.row === r && editingCell?.field === 'tags'"
                    v-model="r.tags"
                    class="cell-input"
                    autofocus
                    @blur="finishEditing"
                    @keyup.enter="finishEditing"
                  />
                  <span v-else class="tag-soft" style="font-size: 11px">{{ r.tags || '常规' }}</span>
                </td>
                <td class="cell-edit" @click="editCell(r, 'difficulty')">
                  <select
                    v-if="editingCell?.row === r && editingCell?.field === 'difficulty'"
                    v-model="r.difficulty"
                    class="select"
                    style="height: 28px; padding: 2px 20px 2px 6px; font-size: 11px"
                    autofocus
                    @blur="finishEditing"
                    @change="finishEditing"
                  >
                    <option>简单</option>
                    <option>中等</option>
                    <option>高</option>
                  </select>
                  <span v-else class="tag-soft" style="font-size: 11px">{{ r.difficulty || '简单' }}</span>
                </td>
                <td style="text-align: right">
                  <button class="link-btn danger" @click="deleteRow(idx)">删除</button>
                </td>
              </tr>
            </tbody>
          </table>
        </div>

        <!-- 3. 底部状态栏 -->
        <div class="ws-status-bar">
          <span>共 <b class="num mono">{{ sampleRows.length }}</b> 行数据</span>
          <span v-if="pendingCount > 0" class="st-bad">
            ⚠ {{ pendingCount }} 行缺失测试句或参考答案
          </span>
          <span v-else class="st-ok">✓ 数据格式校验通过</span>
          <span class="grow"></span>
          <div class="row" style="gap: 6px; align-items: center">
            <span class="tertiary">主指标:</span>
            <select v-model="currentDataset.metric" class="select" style="height: 28px; padding: 2px 24px 2px 8px; font-size: 12px" @change="saveMetric">
              <option value="contain">Contain (包含匹配)</option>
              <option value="exact">Exact (完全一致)</option>
              <option value="rouge_l">ROUGE-L</option>
              <option value="bleu">BLEU</option>
            </select>
          </div>
        </div>
      </div>
      <div v-else class="info-strip" style="margin: 20px">
        暂无可用数据集。请上传一个 JSONL 或 CSV 数据集。
      </div>
    </div>

    <!-- 弹窗与抽屉 -->
    <UploadDatasetModal
      v-model:show="showUploadModal"
      :dataset="datasetForUpload"
      @success="loadDatasets"
    />

    <BenchmarkLaunchDrawer
      v-model:show="showLaunchDrawer"
      :dataset="currentDataset"
    />
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, watch } from 'vue'
import { useMessage } from 'naive-ui'
import { api } from '../api/http'
import type { Dataset, DatasetRow } from '../api/types'
import { useModeStore } from '../stores/mode'
import UploadDatasetModal from '../components/modals/UploadDatasetModal.vue'
import BenchmarkLaunchDrawer from '../components/drawers/BenchmarkLaunchDrawer.vue'

/** 数据集表格在契约行字段外保留可扩展的标签与难度列。 */
interface EditableDatasetRow {
  row_no: number
  q: string
  r: string
  c: string
  tags: string
  difficulty: string
}

const message = useMessage()
const modeStore = useModeStore()
const treeSearch = ref('')
const datasets = ref<Dataset[]>([])
const activeDatasetId = ref('')
const sampleRows = ref<EditableDatasetRow[]>([])
const savingRows = ref(false)
const hasUnsavedChanges = ref(false)
const editingCell = ref<{ row: EditableDatasetRow; field: keyof EditableDatasetRow } | null>(null)
const showUploadModal = ref(false)
const datasetForUpload = ref<Dataset | null>(null)
const showLaunchDrawer = ref(false)

const currentDataset = computed(() => datasets.value.find(dataset => dataset.id === activeDatasetId.value) || datasets.value[0])
const folders = ref([{ id: 'datasets', name: '数据集', open: true, items: [] as Array<{ id: string; name: string; version: number; isGoldQa: boolean; pending_complete_count: number }> }])
const pendingCount = computed(() => sampleRows.value.filter(row => !row.q.trim() || !row.r.trim()).length)
const filteredFolders = computed(() => {
  const keyword = treeSearch.value.trim().toLowerCase()
  if (!keyword) return folders.value
  return folders.value.map(folder => ({
    ...folder,
    items: folder.items.filter(item => item.name.toLowerCase().includes(keyword)),
  })).filter(folder => folder.items.length > 0)
})

// 将接口行字段和页面可编辑字段归一化，兼容历史 q/r/c 与正式 question/reference/context 响应。
function toEditableRow(row: DatasetRow): EditableDatasetRow {
  const extendedRow = row as DatasetRow & Record<string, unknown>
  return {
    row_no: row.row_no,
    q: String(row.question || extendedRow.q || ''),
    r: String(row.reference || extendedRow.r || ''),
    c: String(row.context || extendedRow.c || ''),
    tags: String(extendedRow.tags || ''),
    difficulty: String(extendedRow.difficulty || '简单'),
  }
}

// 将页面编辑结果转换为接口约定的行载荷，并保留扩展字段。
function toApiRows(): Array<DatasetRow & Record<string, unknown>> {
  return sampleRows.value.map(row => ({
    row_no: row.row_no,
    question: row.q,
    reference: row.r,
    context: row.c || null,
    q: row.q,
    r: row.r,
    c: row.c,
    tags: row.tags,
    difficulty: row.difficulty,
  }))
}

// 让目录树始终使用当前接口返回的数据集，而不是原型中固定的示例名称。
function syncDatasetTree(list: Dataset[]) {
  folders.value[0].items = list.map(dataset => ({
    id: dataset.id,
    name: dataset.name,
    version: dataset.version,
    isGoldQa: false,
    pending_complete_count: dataset.pending_complete_count,
  }))
}

function editCell(row: EditableDatasetRow, field: keyof EditableDatasetRow) {
  // 记录当前编辑单元格，失焦时再标记为待保存。
  editingCell.value = { row, field }
}

function finishEditing() {
  // 统一结束单元格编辑并提示用户显式保存。
  editingCell.value = null
  hasUnsavedChanges.value = true
}

// 切换数据集后读取服务端行数据，避免不同数据集共用浏览器中的旧表格。
async function selectDataset(id: string) {
  activeDatasetId.value = id
  await loadRows(id)
}

function openUploadModal(dataset: Dataset | null) {
  // 传入空值创建数据集，传入已有数据集则覆盖上传新版本。
  datasetForUpload.value = dataset
  showUploadModal.value = true
}

function openLaunchDrawer() {
  // 仅打开评测配置抽屉，任务创建仍由抽屉确认动作完成。
  showLaunchDrawer.value = true
}

function addRow() {
  // 新增空白候选行，避免以示例文本伪造已验证数据。
  sampleRows.value.push({
    row_no: Math.max(0, ...sampleRows.value.map(row => row.row_no)) + 1,
    q: '',
    r: '',
    c: '',
    tags: '',
    difficulty: '简单',
  })
  hasUnsavedChanges.value = true
  message.info('已新增空白行，填写后点击“保存修改”落库')
}

function deleteRow(index: number) {
  // 删除先保留在本地编辑态，显式保存后才同步服务端。
  sampleRows.value.splice(index, 1)
  hasUnsavedChanges.value = true
  message.info('已删除该行，点击“保存修改”后生效')
}

// 保存所有可编辑行，服务端会统一校验并持久化扩展列。
async function persistRows() {
  if (!currentDataset.value || savingRows.value) return
  savingRows.value = true
  try {
    await api.datasets.saveRows(currentDataset.value.id, toApiRows())
    const dataset = datasets.value.find(item => item.id === currentDataset.value!.id)
    if (dataset) {
      dataset.row_count = sampleRows.value.length
      dataset.pending_complete_count = pendingCount.value
    }
    syncDatasetTree(datasets.value)
    hasUnsavedChanges.value = false
    message.success('数据集行已保存')
  } catch (err: any) {
    message.error(err.message || '保存数据集行失败')
  } finally {
    savingRows.value = false
  }
}

// AI 只返回候选行；页面将其放入可编辑表格，用户确认后再主动保存。
async function handleAiSynthetic() {
  if (!currentDataset.value) return
  try {
    const candidates = await api.datasets.generateRows({
      dataset_id: currentDataset.value.id,
      mode: 'seed',
      seed: sampleRows.value.slice(0, 5).map(row => `${row.q} => ${row.r}`).join('\n'),
      instruction: '基于当前样本补充覆盖不同业务场景的高质量问答。',
      max_count: 10,
    })
    sampleRows.value.push(...candidates.map(toEditableRow).map((row, index) => ({
      ...row,
      row_no: Math.max(0, ...sampleRows.value.map(item => item.row_no)) + index + 1,
    })))
    hasUnsavedChanges.value = candidates.length > 0 || hasUnsavedChanges.value
    message.success(`已加入 ${candidates.length} 条 AI 候选，请审核后保存`)
  } catch (err: any) {
    message.error(err.message || 'AI 生成候选失败')
  }
}

// 只提交缺失行给 AI，返回内容仍需用户确认并通过保存按钮落库。
async function handleAiFill() {
  if (!currentDataset.value || pendingCount.value === 0) {
    message.info('当前没有待补全的行')
    return
  }
  try {
    const candidates = await api.datasets.generateRows({
      dataset_id: currentDataset.value.id,
      mode: 'fill_missing',
      rows: toApiRows().filter(row => !row.question || !row.reference),
      max_count: pendingCount.value,
    })
    candidates.map(toEditableRow).forEach(candidate => {
      const target = sampleRows.value.find(row => row.row_no === candidate.row_no)
      if (target) Object.assign(target, candidate)
    })
    hasUnsavedChanges.value = candidates.length > 0 || hasUnsavedChanges.value
    message.success(`已回填 ${candidates.length} 条 AI 候选，请审核后保存`)
  } catch (err: any) {
    message.error(err.message || 'AI 补全候选失败')
  }
}

function exportJsonl() {
  // 导出当前可见表格，便于在保存前人工复核候选内容。
  const content = sampleRows.value.map(row => JSON.stringify({ question: row.q, reference: row.r, context: row.c || null })).join('\n')
  const blob = new Blob([content], { type: 'application/jsonl' })
  const url = URL.createObjectURL(blob)
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = `${currentDataset.value?.name || 'dataset'}-v${currentDataset.value?.version || 1}.jsonl`
  anchor.click()
  URL.revokeObjectURL(url)
  message.success('当前表格内容已导出为 JSONL')
}

// 更新主评分指标并用接口响应替换本地数据，避免刷新后回退。
async function saveMetric() {
  if (!currentDataset.value) return
  try {
    const updated = await api.datasets.update(currentDataset.value.id, { metric: currentDataset.value.metric })
    const index = datasets.value.findIndex(item => item.id === updated.id)
    if (index !== -1) datasets.value[index] = updated
    syncDatasetTree(datasets.value)
    message.success('主评分指标已更新')
  } catch (err: any) {
    message.error(err.message || '更新主评分指标失败')
  }
}

async function loadRows(datasetId: string) {
  try {
    sampleRows.value = (await api.datasets.getRows(datasetId)).map(toEditableRow)
    hasUnsavedChanges.value = false
  } catch (err: any) {
    sampleRows.value = []
    message.error(err.message || '加载数据集行失败')
  }
}

async function loadDatasets() {
  try {
    const list = await api.datasets.list()
    datasets.value = list
    syncDatasetTree(list)
    const selected = list.find(dataset => dataset.id === activeDatasetId.value) || list[0]
    if (selected) await selectDataset(selected.id)
    else sampleRows.value = []
  } catch (err: any) {
    datasets.value = []
    syncDatasetTree([])
    sampleRows.value = []
    message.error(err.message || '加载数据集失败')
  }
}

onMounted(() => {
  // 基准数据只在大模型模式加载，避免 RAG 模式访问后展示错误资产。
  if (modeStore.mode === 'llm') void loadDatasets()
})

// 用户在当前页切回大模型模式时，按需读取基准数据资产。
watch(() => modeStore.mode, (mode) => {
  if (mode === 'llm' && !datasets.value.length) void loadDatasets()
})
</script>

<style scoped>
.datasets-workbench {
  height: calc(100vh - var(--topbar-h) - 20px);
}
.mode-context-panel {
  max-width: 680px;
  margin: 48px auto;
  padding: 28px;
}
.mode-context-panel h2 {
  margin: 8px 0 10px;
  font-size: 20px;
}
.mode-context-panel p {
  max-width: 560px;
  margin: 0 0 20px;
  color: var(--text-secondary);
  line-height: 1.7;
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
.ft-status-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: var(--accent-warning);
  margin-left: 4px;
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
.st-ok {
  color: var(--accent-success);
}
.st-bad {
  color: var(--accent-error);
}
@media (max-width: 900px) {
  .datasets-workbench {
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
    min-height: 620px;
  }
  .ws-toolbar .row:last-child {
    width: 100%;
    margin-left: 0 !important;
    justify-content: flex-start !important;
  }
  .ws-status-bar {
    flex-wrap: wrap;
    gap: 8px;
  }
}
</style>
