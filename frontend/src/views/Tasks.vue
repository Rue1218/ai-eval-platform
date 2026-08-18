<template>
  <div class="tasks-page">
    <!-- KPI 状态分布摘要 -->
    <div class="kpi-grid mb16">
      <div class="kpi">
        <div class="kpi-num mono">{{ tasks.length }}</div>
        <div class="kpi-label">总任务数</div>
      </div>
      <div class="kpi">
        <div class="kpi-num mono" style="color: var(--accent-info)">{{ runningCount }}</div>
        <div class="kpi-label">运行中</div>
      </div>
      <div class="kpi">
        <div class="kpi-num mono" style="color: var(--accent-warning)">{{ awaitingCount }}</div>
        <div class="kpi-label">待用例确认</div>
      </div>
      <div class="kpi">
        <div class="kpi-num mono" style="color: var(--accent-success)">{{ successCount }}</div>
        <div class="kpi-label">评测成功</div>
      </div>
    </div>

    <!-- 任务列表面板 -->
    <div class="panel">
      <div class="panel-title">
        <div class="row">
          <span>任务列表</span>
          <span class="mono" style="font-size: 12px; color: var(--text-tertiary)">({{ filteredTasks.length }} 条)</span>
        </div>

        <div class="row">
          <n-select
            v-model:value="filterStatus"
            placeholder="筛选状态"
            clearable
            style="width: 140px"
            :options="[
              { label: '全部状态', value: '' },
              { label: '排队中 (queued)', value: 'queued' },
              { label: '运行中 (running)', value: 'running' },
              { label: '待确认 (awaiting)', value: 'awaiting_case_confirm' },
              { label: '已成功 (succeeded)', value: 'succeeded' },
              { label: '已失败 (failed)', value: 'failed' },
              { label: '已取消 (cancelled)', value: 'cancelled' },
            ]"
          />

          <n-select
            v-model:value="filterKind"
            placeholder="筛选类型"
            clearable
            style="width: 140px"
            :options="[
              { label: '全部类型', value: '' },
              { label: '基准评测 (benchmark)', value: 'benchmark' },
              { label: 'RAG 评测 (rag)', value: 'rag' },
              { label: '用例生成 (testcase)', value: 'testcase' },
              { label: '共享压测 (stress)', value: 'stress' },
            ]"
          />

          <button class="btn btn-secondary btn-sm" :disabled="loading" @click="loadTasks">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
              <polyline points="23 4 23 10 17 10"></polyline>
              <polyline points="1 20 1 14 7 14"></polyline>
              <path d="M3.51 9a9 9 0 0 1 14.85-3.36L23 10M1 14l4.64 4.36A9 9 0 0 0 20.49 15"></path>
            </svg>
            <span>刷新</span>
          </button>
        </div>
      </div>

      <!-- 表格呈现 -->
      <table class="ds-table">
        <thead>
          <tr>
            <th style="width: 110px">任务 ID</th>
            <th style="width: 110px">类型</th>
            <th style="width: 140px">状态</th>
            <th style="width: 160px">进度</th>
            <th>关联资源 / 目标</th>
            <th style="width: 100px">创建者</th>
            <th style="width: 150px">创建时间</th>
            <th style="width: 180px; text-align: right">操作</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="t in filteredTasks" :key="t.id">
            <td class="mono" style="font-size: 13px; font-weight: 500; color: var(--c-tasks)">
              {{ t.id.length > 8 ? t.id.substring(0, 8) : t.id }}
            </td>
            <td>
              <KindTag :kind="t.kind" />
            </td>
            <td>
              <div class="row">
                <StatusBadge :status="t.status" />
                <span v-if="t.need_approval && t.status === 'queued'" style="font-size: 11px; color: var(--accent-warning)">
                  等待会签
                </span>
              </div>
            </td>
            <td>
              <div v-if="t.progress" style="width: 140px">
                <div class="row-between" style="font-size: 11px; margin-bottom: 2px">
                  <span class="mono">{{ t.progress.done }}/{{ t.progress.total }}</span>
                  <span style="color: var(--text-tertiary)">{{ t.progress.percent ? t.progress.percent + '%' : '' }}</span>
                </div>
                <div class="progress-bar" style="height: 4px">
                  <i :style="{ width: `${t.progress.percent || Math.round((t.progress.done / (t.progress.total || 1)) * 100)}%` }"></i>
                </div>
              </div>
              <span v-else class="mono" style="color: var(--text-tertiary)">—</span>
            </td>
            <td style="font-size: 13px">
              <span v-if="t.parent_task_id" class="mono" style="color: var(--c-tasks)">
                ↳ 父任务 {{ t.parent_task_id.substring(0, 8) }}
              </span>
              <span v-else-if="t.config?.dataset_id">
                数据集: {{ t.config.dataset_id }}
              </span>
              <span v-else-if="t.config?.kb_id">
                知识库: {{ t.config.kb_id }}
              </span>
              <span v-else-if="t.config?.case_source?.text">
                {{ t.config.case_source.text.substring(0, 20) }}...
              </span>
              <span v-else style="color: var(--text-tertiary)">—</span>
            </td>
            <td style="font-size: 13px">{{ t.creator || 'admin' }}</td>
            <td class="mono" style="font-size: 12px; color: var(--text-tertiary)">
              {{ formatDate(t.created_at) }}
            </td>
            <td style="text-align: right">
              <div class="row" style="justify-content: flex-end; gap: 4px">
                <button class="link-btn" @click="openDetail(t)">详情</button>
                <router-link v-if="t.report_id" :to="`/reports/${t.report_id}`" class="link-btn">
                  报告
                </router-link>
                <button
                  v-if="['queued', 'running'].includes(t.status)"
                  class="link-btn danger"
                  @click="handleCancel(t)"
                >
                  取消
                </button>
                <button v-else class="link-btn" @click="handleRerun(t)">
                  重跑
                </button>
              </div>
            </td>
          </tr>

          <tr v-if="filteredTasks.length === 0">
            <td colspan="8">
              <EmptyState title="暂无任务" description="可在智能体对话中下发或在数据集/知识库工作台发起评测" />
            </td>
          </tr>
        </tbody>
      </table>
    </div>

    <!-- 任务详情抽屉 -->
    <TaskDetailDrawer
      v-model:show="showDrawer"
      :task="selectedTask"
      @cancel="handleCancel"
      @rerun="handleRerun"
    />
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { useMessage, useDialog } from 'naive-ui'
import { api } from '../api/http'
import type { Task } from '../api/types'
import StatusBadge from '../components/common/StatusBadge.vue'
import KindTag from '../components/common/KindTag.vue'
import EmptyState from '../components/common/EmptyState.vue'
import TaskDetailDrawer from '../components/drawers/TaskDetailDrawer.vue'

const message = useMessage()
const dialog = useDialog()

const tasks = ref<Task[]>([])
const loading = ref(false)
const filterStatus = ref('')
const filterKind = ref('')

const showDrawer = ref(false)
const selectedTask = ref<Task | null>(null)

const runningCount = computed(() => tasks.value.filter((t) => t.status === 'running').length)
const awaitingCount = computed(() => tasks.value.filter((t) => t.status === 'awaiting_case_confirm').length)
const successCount = computed(() => tasks.value.filter((t) => t.status === 'succeeded').length)

const filteredTasks = computed(() => {
  return tasks.value.filter((t) => {
    if (filterStatus.value && t.status !== filterStatus.value) return false
    if (filterKind.value && t.kind !== filterKind.value) return false
    return true
  })
})

function formatDate(dateStr?: string) {
  if (!dateStr) return ''
  return new Date(dateStr).toLocaleString('zh-CN', { hour12: false })
}

async function loadTasks() {
  loading.value = true
  try {
    tasks.value = await api.tasks.list()
  } catch (err: any) {
    message.error(err.message || '加载任务列表失败')
  } finally {
    loading.value = false
  }
}

function openDetail(task: Task) {
  selectedTask.value = task
  showDrawer.value = true
}

function handleCancel(task: Task) {
  const isStress = task.kind === 'stress'
  dialog.warning({
    title: isStress ? '立即停止发压？' : '取消评测任务？',
    content: isStress
      ? '发压引擎将立即中断发压。'
      : '评测任务将在当前样本结束后停止。',
    positiveText: isStress ? '立即停止' : '取消任务',
    negativeText: '暂不取消',
    onPositiveClick: async () => {
      try {
        await api.tasks.cancel(task.id)
        message.success('已提交取消请求')
        loadTasks()
      } catch (err: any) {
        message.error(err.message || '取消任务失败')
      }
    },
  })
}

async function handleRerun(task: Task) {
  try {
    const newT = await api.tasks.rerun(task.id)
    message.success(`任务 #${newT.id} 已重新入队`)
    loadTasks()
  } catch (err: any) {
    message.error(err.message || '重新发起任务失败')
  }
}

onMounted(loadTasks)
</script>

<style scoped>
.tasks-page {
  display: flex;
  flex-direction: column;
  gap: 16px;
}
</style>
