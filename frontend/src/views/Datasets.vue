<template>
  <div class="datasets-workbench">
    <div class="ft-layout">
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

          <div class="row" style="gap: 8px; align-items: center; margin-left: auto">
            <button class="btn btn-secondary btn-sm" @click="addRow">+ 新增行</button>
            <button class="btn btn-ai btn-sm" @click="handleAiSynthetic">✨ AI 合成新数据</button>
            <button class="btn btn-ai btn-sm" @click="handleAiFill">AI 补全缺失行</button>
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
                    @blur="editingCell = null"
                    @keyup.enter="editingCell = null"
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
                    @blur="editingCell = null"
                    @keyup.enter="editingCell = null"
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
                    @blur="editingCell = null"
                    @keyup.enter="editingCell = null"
                  />
                  <span v-else>{{ r.c || '—' }}</span>
                </td>
                <td class="cell-edit" @click="editCell(r, 'tags')">
                  <span class="tag-soft" style="font-size: 11px">{{ r.tags || '常规' }}</span>
                </td>
                <td class="cell-edit">
                  <span class="tag-soft" style="font-size: 11px">{{ r.difficulty || '简单' }}</span>
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
            <select v-model="currentDataset.metric" class="select" style="height: 28px; padding: 2px 24px 2px 8px; font-size: 12px">
              <option value="contain">Contain (包含匹配)</option>
              <option value="exact">Exact (完全一致)</option>
              <option value="rouge_l">ROUGE-L</option>
              <option value="bleu">BLEU</option>
            </select>
          </div>
        </div>
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
import { ref, computed, onMounted } from 'vue'
import { useMessage } from 'naive-ui'
import { api } from '../api/http'
import type { Dataset } from '../api/types'
import UploadDatasetModal from '../components/modals/UploadDatasetModal.vue'
import BenchmarkLaunchDrawer from '../components/drawers/BenchmarkLaunchDrawer.vue'

const message = useMessage()

const treeSearch = ref('')
const datasets = ref<Dataset[]>([
  { id: 'ds-smoke', name: 'smoke-20', version: 3, row_count: 20, pending_complete_count: 2, metric: 'contain', owner: 'alice', created_at: new Date().toISOString() },
  { id: 'ds-pay', name: '支付链路问答', version: 1, row_count: 156, pending_complete_count: 0, metric: 'rouge_l', owner: 'bob', created_at: new Date().toISOString() },
  { id: 'ds-faq', name: 'FAQ-标准问', version: 2, row_count: 480, pending_complete_count: 6, metric: 'exact', owner: 'alice', created_at: new Date().toISOString() },
])
const activeDatasetId = ref('ds-smoke')
const currentDataset = computed(() => datasets.value.find(d => d.id === activeDatasetId.value) || datasets.value[0])

const folders = ref([
  {
    id: 'f-core',
    name: '核心主干基准',
    open: true,
    items: [
      { id: 'ds-smoke', name: 'smoke-20', version: 3, isGoldQa: false, pending_complete_count: 2 },
    ],
  },
  {
    id: 'f-biz',
    name: '支付风控链路',
    open: true,
    items: [
      { id: 'ds-pay', name: '支付链路问答', version: 1, isGoldQa: false, pending_complete_count: 0 },
    ],
  },
  {
    id: 'f-faq',
    name: '客服与知识库 FAQ',
    open: true,
    items: [
      { id: 'ds-faq', name: 'FAQ-标准问', version: 2, isGoldQa: false, pending_complete_count: 6 },
    ],
  },
])

const filteredFolders = computed(() => {
  const kw = treeSearch.value.trim().toLowerCase()
  if (!kw) return folders.value
  return folders.value.map(f => ({
    ...f,
    items: f.items.filter(it => it.name.toLowerCase().includes(kw)),
  })).filter(f => f.items.length > 0)
})

const sampleRows = ref([
  { row_no: 1, q: '如何修改默认结算账户？', r: '进入「设置-账户-结算账户」，选择「修改默认账户」并完成短信验证。', c: '用户需已绑定手机号', tags: '账户,安全', difficulty: '中等' },
  { row_no: 2, q: '支持哪些付款方式？', r: '支持余额、银行卡与对公转账三种方式。', c: '', tags: '收银台', difficulty: '简单' },
  { row_no: 3, q: '', r: '在「设置-账单」中申请', c: '', tags: '账单', difficulty: '简单' },
  { row_no: 4, q: '支付密码输错被锁定怎么办？', r: '连续输错 5 次锁定 2 小时，可通过人脸验证立即解锁。', c: '', tags: '风控', difficulty: '高' },
  { row_no: 5, q: '余额提现有限额吗？', r: '单笔提现不超过 5 万元，单日不超过 20 万元。', c: '', tags: '资金', difficulty: '中等' },
  { row_no: 6, q: '退款多久到账？', r: '审核通过后 1-3 个工作日原路退回。', c: '', tags: '售后', difficulty: '简单' },
  { row_no: 7, q: '如何导出上一年度对账单？', r: '', c: '', tags: '财务', difficulty: '中等' },
])

const pendingCount = computed(() => sampleRows.value.filter(r => !r.q || !r.r).length)

const editingCell = ref<{ row: any; field: string } | null>(null)
function editCell(row: any, field: string) {
  editingCell.value = { row, field }
}

const showUploadModal = ref(false)
const datasetForUpload = ref<Dataset | null>(null)
const showLaunchDrawer = ref(false)

function selectDataset(id: string) {
  activeDatasetId.value = id
}

function openUploadModal(d: Dataset | null) {
  datasetForUpload.value = d
  showUploadModal.value = true
}

function openLaunchDrawer() {
  showLaunchDrawer.value = true
}

function addRow() {
  sampleRows.value.push({
    row_no: sampleRows.value.length + 1,
    q: '新测试样本问句',
    r: '新测试标准答案',
    c: '',
    tags: '新增',
    difficulty: '简单',
  })
  message.success('已添加新行')
}

function deleteRow(idx: number) {
  sampleRows.value.splice(idx, 1)
  message.success('已删除该行')
}

function handleAiSynthetic() {
  message.info('AI 正在基于当前样本分布合成扩增 10 条高质量问答对...')
  setTimeout(() => {
    for (let i = 1; i <= 3; i++) {
      sampleRows.value.push({
        row_no: sampleRows.value.length + 1,
        q: `AI 合成测试问句 #${sampleRows.value.length + 1}`,
        r: `对应标准参考解答 #${sampleRows.value.length + 1}`,
        c: 'AI 自动生成',
        tags: 'AI扩增',
        difficulty: '中等',
      })
    }
    message.success('已成功合成扩增新样本')
  }, 1000)
}

function handleAiFill() {
  message.info('AI 正在自动补全缺失行中的测试句与标准参考...')
  setTimeout(() => {
    sampleRows.value.forEach(r => {
      if (!r.q) r.q = 'AI 补全：在「设置-账单」中申请开票的方法是什么？'
      if (!r.r) r.r = 'AI 补全：进入财务中心，选择时间范围后点击「导出对账单」即可。'
    })
    message.success('已成功补全缺失行')
  }, 900)
}

function exportJsonl() {
  const content = sampleRows.value.map(r => JSON.stringify({ question: r.q, reference: r.r, context: r.c })).join('\n')
  const blob = new Blob([content], { type: 'application/jsonl' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = `${currentDataset.value?.name || 'dataset'}-v${currentDataset.value?.version || 1}.jsonl`
  a.click()
  message.success('JSONL 数据集已导出')
}

async function loadDatasets() {
  try {
    const list = await api.datasets.list()
    if (list && list.length) datasets.value = list
  } catch {}
}

onMounted(() => {
  loadDatasets()
})
</script>

<style scoped>
.datasets-workbench {
  height: calc(100vh - var(--topbar-h) - 20px);
}
.ft-layout {
  display: grid;
  grid-template-columns: 260px 1fr;
  height: 100%;
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
</style>
