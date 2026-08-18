<template>
  <div class="cases-page">
    <!-- 顶栏状态 -->
    <div class="row-between mb16">
      <div class="row">
        <span style="font-size: 16px; font-weight: 600">用例生成与自检工作台</span>
        <span class="mono" style="font-size: 12px; color: var(--text-tertiary)">({{ caseSets.length }} 个用例集)</span>
      </div>

      <div class="row">
        <button class="btn btn-secondary btn-sm" :disabled="loading" @click="loadCaseSets">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <polyline points="23 4 23 10 17 10"></polyline>
            <polyline points="1 20 1 14 7 14"></polyline>
            <path d="M3.51 9a9 9 0 0 1 14.85-3.36L23 10M1 14l4.64 4.36A9 9 0 0 0 20.49 15"></path>
          </svg>
          <span>刷新</span>
        </button>
      </div>
    </div>

    <!-- 用例集选择轨 -->
    <div class="panel mb16">
      <div class="case-set-chips">
        <div
          v-for="cs in caseSets"
          :key="cs.id"
          class="cs-card"
          :class="{ active: currentSet?.id === cs.id }"
          @click="selectCaseSet(cs)"
        >
          <div class="row-between">
            <span style="font-weight: 600; font-size: 13px">{{ cs.name }}</span>
            <span class="kind-tag" :class="cs.status === 'confirmed' ? 'kind-cases' : cs.status === 'cancelled' ? '' : 'kind-benchmark'">
              {{ cs.status === 'confirmed' ? '已入库' : cs.status === 'cancelled' ? '已拒绝' : '待确认' }}
            </span>
          </div>
          <div class="row-between mt8 mono" style="font-size: 11px; color: var(--text-secondary)">
            <span>采纳: {{ cs.confirmed_count }}/{{ cs.generated_count }}</span>
            <span v-if="cs.status === 'generated'" style="color: var(--accent-warning)">剩 {{ cs.expires_in_h }}h</span>
          </div>
        </div>
      </div>
    </div>

    <!-- 用例详情与自检确认区 -->
    <div v-if="currentSet" class="panel">
      <!-- 头部与操作 -->
      <div class="row-between mb16" style="padding-bottom: 12px; border-bottom: 1px solid var(--border-subtle)">
        <div>
          <div style="font-size: 16px; font-weight: 700">{{ currentSet.name }} · 生成 {{ currentSet.generated_count }} 条用例</div>
          <div v-if="currentSet.status === 'generated'" style="font-size: 12px; color: var(--text-tertiary); margin-top: 4px">
            72 小时确认窗口期，未确认任务将自动超时取消。
          </div>
        </div>

        <div class="row">
          <button class="btn btn-secondary btn-sm" @click="exportCases('xlsx')">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
              <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"></path>
              <polyline points="7 10 12 15 17 10"></polyline>
              <line x1="12" y1="15" x2="12" y2="3"></line>
            </svg>
            <span>导出 Excel</span>
          </button>
          <button class="btn btn-secondary btn-sm" @click="exportCases('xmind')">导出 XMind</button>
        </div>
      </div>

      <!-- 自检标红警告 -->
      <div v-if="currentSet.checks && currentSet.checks.length" class="error-strip mb16">
        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="flex-shrink: 0">
          <circle cx="12" cy="12" r="10"></circle>
          <line x1="12" y1="8" x2="12" y2="12"></line>
          <line x1="12" y1="16" x2="12.01" y2="16"></line>
        </svg>
        <div>
          <div style="font-weight: 600">AI 规则自检发现问题：</div>
          <div v-for="c in currentSet.checks" :key="c.code" style="font-size: 12.5px; margin-top: 2px">
            · {{ c.message }} ({{ c.code }})
          </div>
        </div>
      </div>

      <!-- 用例表格 -->
      <table class="ds-table">
        <thead>
          <tr>
            <th style="width: 40px">
              <input type="checkbox" :checked="isAllSelected" :disabled="currentSet.status !== 'generated'" @change="toggleSelectAll" />
            </th>
            <th style="width: 80px">策略</th>
            <th style="width: 60px">级别</th>
            <th style="width: 100px">模块</th>
            <th>用例名称</th>
            <th>预期结果</th>
            <th style="width: 90px">映射状态</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="c in cases" :key="c.id">
            <td>
              <input type="checkbox" v-model="c.selected" :disabled="currentSet.status !== 'generated'" />
            </td>
            <td>
              <span class="kind-tag" :style="getStrategyStyle(c.strategy)">{{ c.strategy }}</span>
            </td>
            <td>
              <span class="mono" style="font-weight: 600; font-size: 12px">{{ c.priority }}</span>
            </td>
            <td style="font-size: 13px">{{ c.module }}</td>
            <td>
              <input
                v-if="currentSet.status === 'generated'"
                v-model="c.name"
                class="cell-input"
              />
              <span v-else>{{ c.name }}</span>
            </td>
            <td>
              <input
                v-if="currentSet.status === 'generated'"
                v-model="c.expected"
                class="cell-input"
              />
              <span v-else>{{ c.expected }}</span>
            </td>
            <td>
              <span v-if="c.mapped" class="badge badge-succeeded" style="font-size: 11px">已映射</span>
              <span v-else-if="c.pending" class="badge badge-awaiting_case_confirm" style="font-size: 11px">待补全</span>
              <span v-else class="mono" style="color: var(--text-tertiary)">—</span>
            </td>
          </tr>
        </tbody>
      </table>

      <!-- 底部确认入库条 -->
      <div v-if="currentSet.status === 'generated'" class="row-between mt16" style="padding-top: 14px; border-top: 1px solid var(--border-subtle)">
        <div class="row">
          <n-select
            v-model:value="mapTargetId"
            placeholder="映射到数据集..."
            style="width: 180px"
            :options="datasetOptions"
          />
          <button class="btn btn-secondary btn-sm" :disabled="!mapTargetId" @click="handleMapCases">
            执行映射
          </button>
        </div>

        <div class="row">
          <button class="btn btn-secondary btn-sm danger-text" @click="handleRejectSet">
            拒绝这批用例
          </button>
          <button class="btn btn-sign btn-sm" @click="handleConfirmSet">
            确认入库 ({{ selectedCount }}条)
          </button>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { useMessage, useDialog } from 'naive-ui'
import { api } from '../api/http'
import type { CaseSet, TestCase, Dataset } from '../api/types'

const message = useMessage()
const dialog = useDialog()

const caseSets = ref<CaseSet[]>([])
const currentSet = ref<CaseSet | null>(null)
const cases = ref<TestCase[]>([])
const datasets = ref<Dataset[]>([])
const mapTargetId = ref<string | null>(null)
const loading = ref(false)

const selectedCount = computed(() => cases.value.filter((c) => c.selected).length)
const isAllSelected = computed(() => cases.value.length > 0 && cases.value.every((c) => c.selected))

const datasetOptions = computed(() =>
  datasets.value.map((d) => ({ label: `${d.name} (v${d.version})`, value: d.id })),
)

function getStrategyStyle(strategy: string) {
  if (strategy === '正向') return { background: 'var(--t-cases)', color: 'var(--c-cases)' }
  if (strategy === '反向') return { background: '#FEE2E2', color: '#B91C1C' }
  if (strategy === '边界') return { background: 'var(--t-profiles)', color: 'var(--c-profiles)' }
  return { background: 'var(--bg-elevated)', color: 'var(--text-secondary)' }
}

function toggleSelectAll(e: Event) {
  const checked = (e.target as HTMLInputElement).checked
  cases.value.forEach((c) => (c.selected = checked))
}

async function loadCaseSets() {
  loading.value = true
  try {
    caseSets.value = await api.cases.listSets()
    if (caseSets.value.length && !currentSet.value) {
      selectCaseSet(caseSets.value[0])
    }
    datasets.value = await api.datasets.list()
  } catch (err: any) {
    message.error(err.message || '加载用例集失败')
  } finally {
    loading.value = false
  }
}

async function selectCaseSet(cs: CaseSet) {
  currentSet.value = cs
  try {
    const full = await api.cases.getSet(cs.id)
    cases.value = (full.cases || []).map((c) => ({ ...c, selected: c.selected !== false }))
  } catch (err) {
    cases.value = []
  }
}

function exportCases(fmt: 'xlsx' | 'xmind') {
  message.success(`已开始导出 ${fmt.toUpperCase()} 文件`)
}

async function handleConfirmSet() {
  if (!currentSet.value) return
  try {
    await api.cases.confirmSet(currentSet.value.id, { ok: true })
    currentSet.value.status = 'confirmed'
    currentSet.value.confirmed_count = selectedCount.value
    message.success('用例已成功入库')
  } catch (err: any) {
    message.error(err.message || '确认入库失败')
  }
}

function handleRejectSet() {
  if (!currentSet.value) return
  dialog.warning({
    title: '拒绝这批用例？',
    content: '拒绝后此用例集任务将转为已取消 (cancelled)，用例将不被入库。',
    positiveText: '确认拒绝',
    negativeText: '取消',
    onPositiveClick: async () => {
      try {
        await api.cases.cancelSet(currentSet.value!.id, '用户手动拒绝')
        currentSet.value!.status = 'cancelled'
        message.info('已拒绝这批用例')
      } catch (err: any) {
        message.error(err.message || '拒绝失败')
      }
    },
  })
}

async function handleMapCases() {
  if (!currentSet.value || !mapTargetId.value) return
  try {
    await api.cases.mapCases(currentSet.value.id, { target_type: 'dataset', target_id: mapTargetId.value })
    message.success('用例已成功映射至数据集')
    cases.value.forEach((c) => {
      if (c.selected) c.mapped = true
    })
  } catch (err: any) {
    message.error(err.message || '映射失败')
  }
}

onMounted(loadCaseSets)
</script>

<style scoped>
.cases-page {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.case-set-chips {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(240px, 1fr));
  gap: 12px;
}
.cs-card {
  padding: 12px 14px;
  border-radius: 12px;
  border: 1px solid var(--border-subtle);
  background: var(--bg-elevated);
  cursor: pointer;
  transition: all 0.15s ease;
}
.cs-card:hover {
  border-color: var(--accent-ai);
}
.cs-card.active {
  border-color: var(--accent-ai);
  background: var(--bg-main);
  box-shadow: 0 0 0 1px var(--accent-ai);
}

.cell-input {
  width: 100%;
  border: 1px solid transparent;
  background: transparent;
  padding: 4px 6px;
  border-radius: 6px;
  font: inherit;
  font-size: 13px;
  color: var(--text-primary);
  transition: all 0.15s ease;
}
.cell-input:hover {
  border-color: var(--border-subtle);
  background: var(--bg-elevated);
}
.cell-input:focus {
  border-color: var(--accent-ai);
  background: var(--bg-main);
  outline: none;
}
</style>
