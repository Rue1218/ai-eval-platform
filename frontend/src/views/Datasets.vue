<template>
  <div class="datasets-page">
    <!-- 顶部操作条 -->
    <div class="row-between mb16">
      <div class="row">
        <span style="font-size: 16px; font-weight: 600">评测数据集</span>
        <span class="mono" style="font-size: 12px; color: var(--text-tertiary)">({{ datasets.length }} 个)</span>
      </div>

      <div class="row">
        <button class="btn btn-primary btn-sm" @click="openUploadModal(null)">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <line x1="12" y1="5" x2="12" y2="19"></line>
            <line x1="5" y1="12" x2="19" y2="12"></line>
          </svg>
          <span>上传数据集</span>
        </button>

        <button class="btn btn-secondary btn-sm" :disabled="loading" @click="loadDatasets">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <polyline points="23 4 23 10 17 10"></polyline>
            <polyline points="1 20 1 14 7 14"></polyline>
            <path d="M3.51 9a9 9 0 0 1 14.85-3.36L23 10M1 14l4.64 4.36A9 9 0 0 0 20.49 15"></path>
          </svg>
          <span>刷新</span>
        </button>
      </div>
    </div>

    <!-- 数据集表格面板 -->
    <div class="panel">
      <table class="ds-table">
        <thead>
          <tr>
            <th>数据集名称</th>
            <th style="width: 80px">版本</th>
            <th style="width: 100px">总行数</th>
            <th style="width: 160px">主评分指标</th>
            <th style="width: 110px">待补全样本</th>
            <th style="width: 100px">创建者</th>
            <th style="width: 150px">创建时间</th>
            <th style="width: 240px; text-align: right">操作</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="d in datasets" :key="d.id">
            <td style="font-weight: 600; font-size: 14px">
              <span class="row" style="gap: 6px">
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="color: var(--c-datasets)">
                  <ellipse cx="12" cy="5" rx="9" ry="3"></ellipse>
                  <path d="M21 12c0 1.66-4 3-9 3s-9-1.34-9-3"></path>
                  <path d="M3 5v14c0 1.66 4 3 9 3s9-1.34 9-3V5"></path>
                </svg>
                <span>{{ d.name }}</span>
              </span>
            </td>
            <td>
              <span class="kind-tag" style="background: var(--bg-elevated); color: var(--text-secondary)">
                v{{ d.version }}
              </span>
            </td>
            <td class="mono">{{ d.row_count }} 行</td>
            <td>
              <n-select
                v-model:value="d.metric"
                size="small"
                style="width: 140px"
                :options="[
                  { label: 'Contain (包含)', value: 'contain' },
                  { label: 'Exact (全等)', value: 'exact' },
                  { label: 'Regex (正则)', value: 'regex' },
                  { label: 'ROUGE-L', value: 'rouge_l' },
                  { label: 'BLEU', value: 'bleu' },
                ]"
                @update:value="(val: any) => updateMetric(d.id, val)"
              />
            </td>
            <td>
              <span
                v-if="d.pending_complete_count > 0"
                class="badge badge-awaiting_case_confirm"
                style="cursor: pointer"
                @click="openRowsDrawer(d, true)"
              >
                {{ d.pending_complete_count }} 条待补全
              </span>
              <span v-else class="mono" style="color: var(--text-tertiary)">0</span>
            </td>
            <td style="font-size: 13px">{{ d.owner }}</td>
            <td class="mono" style="font-size: 12px; color: var(--text-tertiary)">
              {{ formatDate(d.created_at) }}
            </td>
            <td style="text-align: right">
              <div class="row" style="justify-content: flex-end; gap: 4px">
                <button class="link-btn" @click="openRowsDrawer(d, false)">样本</button>
                <button class="link-btn" @click="openUploadModal(d)">覆盖上传</button>
                <button class="link-btn" style="color: var(--c-tasks); font-weight: 600" @click="openLaunchDrawer(d)">
                  发起评测
                </button>
                <button class="link-btn danger" @click="handleDelete(d)">删除</button>
              </div>
            </td>
          </tr>

          <tr v-if="datasets.length === 0">
            <td colspan="8">
              <EmptyState title="暂无评测数据集" description="点击右上角上传第一份 JSONL 或 CSV 格式的测试样本集">
                <template #action>
                  <button class="btn btn-primary btn-sm" @click="openUploadModal(null)">上传数据集</button>
                </template>
              </EmptyState>
            </td>
          </tr>
        </tbody>
      </table>
    </div>

    <!-- 上传 / 覆盖上传弹窗 -->
    <UploadDatasetModal
      v-model:show="showUploadModal"
      :dataset="selectedDatasetForUpload"
      @success="loadDatasets"
    />

    <!-- 发起评测抽屉 -->
    <BenchmarkLaunchDrawer
      v-model:show="showLaunchDrawer"
      :default-dataset-id="selectedDatasetForLaunch?.id"
      @success="handleLaunchSuccess"
    />

    <!-- 查看样本数据抽屉 -->
    <n-drawer v-model:show="showRowsDrawer" :width="640">
      <n-drawer-content :title="`「${currentViewingDataset?.name}」样本数据预览`" closable>
        <div style="margin-bottom: 12px; display: flex; align-items: center; justify-content: space-between">
          <n-radio-group v-model:value="rowsTab" size="small">
            <n-radio-button value="all">全部样本</n-radio-button>
            <n-radio-button value="pending">待补全样本 ({{ currentViewingDataset?.pending_complete_count || 0 }})</n-radio-button>
          </n-radio-group>
        </div>

        <div v-if="rowsTab === 'pending'" class="warn-strip mb16" style="font-size: 12px">
          说明：缺失 question 或 reference 的待补全样本将不会计入 Benchmark 打分分母。
        </div>

        <table class="ds-table">
          <thead>
            <tr>
              <th style="width: 60px">行号</th>
              <th>Question (测试输入)</th>
              <th>Reference (标准答案)</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="r in datasetRows" :key="r.row_no">
              <td class="mono">{{ r.row_no }}</td>
              <td style="font-size: 13px">
                <span v-if="r.question">{{ r.question }}</span>
                <span v-else style="color: var(--accent-error); font-style: italic">缺失输入 (待补全)</span>
              </td>
              <td style="font-size: 13px">
                <span v-if="r.reference">{{ r.reference }}</span>
                <span v-else style="color: var(--accent-error); font-style: italic">缺失参考答案 (待补全)</span>
              </td>
            </tr>
          </tbody>
        </table>
      </n-drawer-content>
    </n-drawer>
  </div>
</template>

<script setup lang="ts">
import { ref, watch, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { useMessage, useDialog } from 'naive-ui'
import { api } from '../api/http'
import type { Dataset, DatasetRow, DatasetMetric } from '../api/types'
import EmptyState from '../components/common/EmptyState.vue'
import UploadDatasetModal from '../components/modals/UploadDatasetModal.vue'
import BenchmarkLaunchDrawer from '../components/drawers/BenchmarkLaunchDrawer.vue'

const router = useRouter()
const message = useMessage()
const dialog = useDialog()

const datasets = ref<Dataset[]>([])
const loading = ref(false)

const showUploadModal = ref(false)
const selectedDatasetForUpload = ref<Dataset | null>(null)

const showLaunchDrawer = ref(false)
const selectedDatasetForLaunch = ref<Dataset | null>(null)

const showRowsDrawer = ref(false)
const currentViewingDataset = ref<Dataset | null>(null)
const datasetRows = ref<DatasetRow[]>([])
const rowsTab = ref<'all' | 'pending'>('all')

function formatDate(d?: string) {
  if (!d) return ''
  return new Date(d).toLocaleDateString('zh-CN')
}

async function loadDatasets() {
  loading.value = true
  try {
    datasets.value = await api.datasets.list()
  } catch (err: any) {
    message.error(err.message || '加载数据集失败')
  } finally {
    loading.value = false
  }
}

async function updateMetric(id: string, metric: DatasetMetric) {
  try {
    await api.datasets.update(id, { metric })
    message.success('主评分指标已更新')
  } catch (err: any) {
    message.error(err.message || '更新指标失败')
  }
}

function openUploadModal(ds: Dataset | null) {
  selectedDatasetForUpload.value = ds
  showUploadModal.value = true
}

function openLaunchDrawer(ds: Dataset) {
  selectedDatasetForLaunch.value = ds
  showLaunchDrawer.value = true
}

function handleLaunchSuccess(taskId: string) {
  router.push('/tasks')
}

async function openRowsDrawer(ds: Dataset, isPending: boolean = false) {
  currentViewingDataset.value = ds
  rowsTab.value = isPending ? 'pending' : 'all'
  showRowsDrawer.value = true
  loadRows()
}

async function loadRows() {
  if (!currentViewingDataset.value) return
  try {
    datasetRows.value = await api.datasets.getRows(currentViewingDataset.value.id, {
      pending_complete: rowsTab.value === 'pending',
    })
  } catch (err) {
    datasetRows.value = []
  }
}

watch(rowsTab, () => {
  loadRows()
})

function handleDelete(ds: Dataset) {
  dialog.warning({
    title: `删除数据集「${ds.name}」？`,
    content: '删除后无法恢复，且历史基于此数据集的关联任务配置将转为快照存储。',
    positiveText: '确认删除',
    negativeText: '取消',
    onPositiveClick: async () => {
      try {
        await api.datasets.delete(ds.id)
        message.success('数据集已删除')
        loadDatasets()
      } catch (err: any) {
        message.error(err.message || '删除失败')
      }
    },
  })
}

onMounted(loadDatasets)
</script>

<style scoped>
.datasets-page {
  display: flex;
  flex-direction: column;
  gap: 16px;
}
</style>
