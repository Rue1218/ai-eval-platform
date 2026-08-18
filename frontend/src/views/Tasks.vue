<template>
  <div class="tasks-page page-narrow" style="max-width: 1320px">
    <!-- 顶部大盘与吞吐概览 (Prototype 高保真) -->
    <div class="panel glow mb16" style="--glow-c: var(--c-tasks)">
      <div class="row-between" style="margin-bottom: 10px">
        <span class="eyebrow">近 24h 吞吐 · 状态分布大盘</span>
        <span class="small tertiary mono">Worker 节点在线 8/10 · 调度周期 500ms</span>
      </div>
      <div class="row wrap" style="gap: 28px; align-items: center">
        <div>
          <svg width="230" height="60" viewBox="0 0 230 60" aria-hidden="true">
            <polygon
              points="2,58 2,54 11.9,56 21.8,52 31.7,54 41.7,50 51.6,46 61.5,48 71.4,42 81.3,44 91.3,40 101.2,46 111.1,38 121.0,42 131.0,36 140.9,40 150.8,34 160.7,44 170.7,40 180.6,38 190.5,42 200.4,34 210.3,30 220.3,36 228.0,32 228.0,58"
              fill="var(--c-tasks)"
              fill-opacity=".12"
            />
            <polyline
              points="2,54 11.9,56 21.8,52 31.7,54 41.7,50 51.6,46 61.5,48 71.4,42 81.3,44 91.3,40 101.2,46 111.1,38 121.0,42 131.0,36 140.9,40 150.8,34 160.7,44 170.7,40 180.6,38 190.5,42 200.4,34 210.3,30 220.3,36 228.0,32"
              fill="none"
              stroke="var(--c-tasks)"
              stroke-width="1.8"
              stroke-linecap="round"
              stroke-linejoin="round"
            />
          </svg>
          <div class="small tertiary mono" style="margin-top: 2px">完成 {{ tasks.length }} 任务 / 24h</div>
        </div>
        <div class="grow" style="min-width: 260px">
          <!-- 状态分布分段条 -->
          <div class="dist">
            <i
              v-for="s in statusList"
              :key="s.key"
              :style="{ width: `${statusPercentages[s.key] || 0}%`, background: s.color }"
              :title="`${s.label}: ${statusCounts[s.key] || 0}`"
            ></i>
          </div>
          <!-- 交互图例 -->
          <div class="chart-legend" style="margin-top: 8px">
            <span
              v-for="s in statusList"
              :key="s.key"
              style="cursor: pointer"
              @click="toggleStatusFilter(s.key)"
            >
              <i :style="{ background: s.color }"></i>
              {{ s.label }} <b class="num">{{ statusCounts[s.key] || 0 }}</b>
            </span>
          </div>
        </div>
      </div>
    </div>

    <!-- AI 巡检诊断卡片 -->
    <div class="ai-card mb16">
      <div class="ai-card-head">
        <span class="ai-badge"><i class="ai-dot"></i>AI 巡检诊断</span>
        <span class="small tertiary mono">近 24h · 自动异常归因</span>
        <span class="grow"></span>
        <button class="link-btn" style="font-size: 12px" @click="nextInsight">换一批</button>
      </div>
      <div class="ai-gen-line small" style="color: var(--text-secondary)">
        {{ currentInsight.text }}
      </div>
      <div class="mt8">
        <router-link :to="currentInsight.link" class="link-btn" style="font-size: 12px">
          {{ currentInsight.actionText }} →
        </router-link>
      </div>
    </div>

    <!-- 筛选与操作工具栏 -->
    <div class="filter-bar row wrap" style="gap: 10px; margin-bottom: 14px">
      <span
        class="tag-soft"
        style="cursor: default"
        :style="{
          color: modeStore.mode === 'rag' ? 'var(--c-kb)' : 'var(--c-datasets)',
          borderColor: modeStore.mode === 'rag' ? 'var(--t-kb)' : 'var(--t-datasets)'
        }"
      >
        {{ modeStore.mode === 'rag' ? 'RAG 测试' : '大模型测试' }} · {{ modeTaskLabel }}
      </span>

      <n-input
        v-model:value="searchKw"
        :placeholder="modeStore.mode === 'rag' ? '搜索任务 ID / 知识库 / 创建者…' : '搜索任务 ID / 数据集 / 创建者…'"
        style="width: 240px"
        clearable
      />

      <n-select
        v-model:value="filterStatus"
        placeholder="全部状态"
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

      <span class="tag-soft" style="cursor: default">
        类型已限定为 {{ modeTaskLabel }}
      </span>

      <span class="grow"></span>

      <button class="btn btn-secondary btn-sm" :disabled="loading" @click="handleRefresh">
        <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round">
          <path d="M21 12a9 9 0 0 0-9-9 9.75 9.75 0 0 0-6.74 2.74L3 8" />
          <path d="M3 3v5h5" />
          <path d="M3 12a9 9 0 0 0 9 9 9.75 9.75 0 0 0 6.74-2.74L21 16" />
          <path d="M16 21h5v-5" />
        </svg>
        <span>刷新</span>
      </button>

      <button class="btn btn-ai btn-sm" @click="openPlannerDrawer">
        <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
          <path d="M12 3l1.9 5.6L19.5 10l-5.6 1.9L12 17.5l-1.9-5.6L4.5 10l5.6-1.4Z" />
        </svg>
        <span>智能编排</span>
      </button>
    </div>

    <!-- 任务数据表格 -->
    <div class="panel" style="padding: 6px 8px">
      <table class="ds-table">
        <thead>
          <tr>
            <th style="width: 100px">任务 ID</th>
            <th style="width: 130px">评测类型</th>
            <th style="width: 120px">当前状态</th>
            <th style="width: 160px">执行进度 / 指标</th>
            <th>关联资产 / 目标</th>
            <th style="width: 100px">创建者</th>
            <th style="width: 130px">创建时间</th>
            <th style="width: 220px; text-align: right">操作</th>
          </tr>
        </thead>
        <tbody v-if="loading">
          <tr v-for="i in 5" :key="i">
            <td v-for="j in 8" :key="j">
              <div class="skl" style="height: 14px; margin: 8px 0"></div>
            </td>
          </tr>
        </tbody>
        <tbody v-else>
          <tr v-for="t in filteredTasks" :key="t.id">
            <td class="num-col mono" style="font-weight: 600; color: var(--c-tasks)">
              {{ t.id.length > 8 ? t.id.substring(0, 8) : t.id }}
            </td>
            <td>
              <div class="row" style="gap: 4px">
                <KindTag :kind="t.kind" />
                <span
                  v-if="t.with_stress || t.child_stress_task_id || t.config?.with_stress"
                  class="tag-soft"
                  style="font-size: 11px; background: var(--t-stress); color: var(--c-stress); border-color: transparent"
                  title="已配置先评后压"
                >
                  先评后压
                </span>
              </div>
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
              <div v-if="t.status === 'running' && t.progress" style="width: 140px">
                <div class="row-between" style="font-size: 11px; margin-bottom: 2px">
                  <span class="mono">{{ t.progress.done }}/{{ t.progress.total }}</span>
                  <span style="color: var(--text-tertiary)">{{ t.progress.percent ? t.progress.percent + '%' : '' }}</span>
                </div>
                <div class="progress-bar" style="height: 4px">
                  <i :style="{ width: `${t.progress.percent || Math.round((t.progress.done / (t.progress.total || 1)) * 100)}%` }"></i>
                </div>
              </div>
              <span v-else class="small tertiary mono">{{ t.progress?.message || '—' }}</span>
            </td>
            <td class="small" style="max-width: 240px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap">
              <span v-if="t.parent_task_id" class="mono" style="color: var(--c-tasks)">
                ↳ 父任务 {{ t.parent_task_id.substring(0, 8) }}
              </span>
              <span v-else-if="t.config?.dataset_id">
                数据集: {{ t.config.dataset_id }}
              </span>
              <span v-else-if="t.config?.kb_id">
                知识库: {{ t.config.kb_id }}
              </span>
              <span v-else>{{ t.id }}</span>
            </td>
            <td class="small">{{ t.creator || t.created_by || 'admin' }}</td>
            <td class="small tertiary mono">{{ formatRelativeTime(t.created_at) }}</td>
            <td style="text-align: right">
              <div class="row-actions" style="justify-content: flex-end">
                <button class="link-btn" @click="handleOpenDetail(t)">详情</button>
                <button
                  v-if="canCancel(t)"
                  class="link-btn danger"
                  @click="handleCancel(t)"
                >
                  取消
                </button>
                <button
                  v-if="['succeeded', 'failed', 'cancelled'].includes(t.status)"
                  class="link-btn"
                  @click="handleRerun(t)"
                >
                  复制为新任务
                </button>
                <router-link
                  v-if="t.report_id || t.status === 'succeeded'"
                  :to="`/reports/${t.report_id || 'r-bm-1'}`"
                  class="link-btn"
                  style="color: var(--accent-ai); font-weight: 600"
                >
                  查看报告
                </router-link>
              </div>
            </td>
          </tr>
        </tbody>
      </table>

      <EmptyState
        v-if="!loading && filteredTasks.length === 0"
        title="暂无符合条件的任务"
        description="可点击上方「智能编排」或智能体对话快速创建测试任务"
      />
    </div>

    <!-- 智能编排抽屉 (AI Planner) -->
    <n-drawer v-model:show="showPlannerDrawer" :width="560">
      <n-drawer-content title="智能编排 · 评测任务方案生成" closable>
        <div class="field">
          <span class="field-label">用一句话描述测试目标 <i class="req">*</i></span>
          <textarea
            v-model="plannerGoal"
            class="textarea"
            rows="3"
            placeholder="如：对比 gpt-test 与 claude-x 在 smoke-20 上的表现，质量达标后自动压测"
          ></textarea>
        </div>

        <div class="row" style="justify-content: flex-end; margin-bottom: 14px">
          <button class="btn btn-ai btn-sm" :disabled="isPlanning" @click="generatePlan">
            <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
              <path d="M12 3l1.9 5.6L19.5 10l-5.6 1.9L12 17.5l-1.9-5.6L4.5 10l5.6-1.4Z" />
            </svg>
            <span>{{ isPlanning ? '正在解析生成中...' : '生成编排方案' }}</span>
          </button>
        </div>

        <div v-if="plannerSteps.length > 0" class="ai-card">
          <div class="ai-card-head">
            <span class="ai-badge"><i class="ai-dot"></i>评测编排方案</span>
            <span class="small tertiary mono">task.create · 与确认卡同一 schema</span>
          </div>
          <div class="section-gap" style="gap: 7px">
            <div
              v-for="(step, idx) in plannerSteps"
              :key="idx"
              class="ai-gen-line small"
              style="color: var(--text-secondary)"
            >
              · {{ step }}
            </div>
          </div>
        </div>

        <template #footer>
          <div class="row" style="justify-content: flex-end; gap: 10px">
            <button class="btn btn-secondary" @click="showPlannerDrawer = false">取消</button>
            <button
              class="btn btn-sign"
              :disabled="plannerSteps.length === 0"
              @click="submitPlannerTask"
            >
              采纳并创建任务
            </button>
          </div>
        </template>
      </n-drawer-content>
    </n-drawer>

    <!-- 任务详情抽屉 -->
    <TaskDetailDrawer
      v-model:show="showDetailDrawer"
      :task="selectedTask"
      @cancel="handleCancel(selectedTask!)"
      @rerun="handleRerun(selectedTask!)"
    />
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, watch } from 'vue'
import { useMessage, useDialog, NSelect, NInput, NDrawer, NDrawerContent } from 'naive-ui'
import { api } from '../api/http'
import type { Task } from '../api/types'
import { useModeStore } from '../stores/mode'
import StatusBadge from '../components/common/StatusBadge.vue'
import KindTag from '../components/common/KindTag.vue'
import EmptyState from '../components/common/EmptyState.vue'
import TaskDetailDrawer from '../components/drawers/TaskDetailDrawer.vue'

const message = useMessage()
const dialog = useDialog()
const modeStore = useModeStore()

const tasks = ref<Task[]>([])
const loading = ref(false)
const filterStatus = ref('')
const searchKw = ref('')

const showDetailDrawer = ref(false)
const selectedTask = ref<Task | null>(null)

// 当前模式只查询同类质量评测，派生压测通过其父质量任务进入，不混入另一条业务工作流。
const modeTaskKind = computed<'benchmark' | 'rag'>(() => modeStore.mode === 'rag' ? 'rag' : 'benchmark')
const modeTaskLabel = computed(() => modeStore.mode === 'rag' ? 'RAG 评测' : '基准评测')

// 状态分布与色值
const statusList = [
  { key: 'queued', label: '排队中', color: '#9CA3AF' },
  { key: 'running', label: '运行中', color: '#4F46E5' },
  { key: 'awaiting_case_confirm', label: '待确认', color: '#F59E0B' },
  { key: 'succeeded', label: '已成功', color: '#10B981' },
  { key: 'failed', label: '已失败', color: '#EF4444' },
  { key: 'cancelled', label: '已取消', color: '#6B7280' },
]

const statusCounts = computed(() => {
  const map: Record<string, number> = {}
  statusList.forEach(s => { map[s.key] = 0 })
  tasks.value.forEach(t => {
    if (map[t.status] !== undefined) map[t.status]++
  })
  return map
})

const statusPercentages = computed(() => {
  const total = tasks.value.length || 1
  const map: Record<string, number> = {}
  statusList.forEach(s => {
    map[s.key] = Math.round((statusCounts.value[s.key] / total) * 100)
  })
  return map
})

// 巡检异常诊断轮播
const insights = [
  {
    text: '2 个失败任务（t-9c21、g7b3d5）的 UPSTREAM 错误均指向协议档「rag-客服外挂」401，疑似 Key 失效。',
    actionText: '去协议档做连通性检查',
    link: '/admin/profiles',
  },
  {
    text: '「smoke-20 v3」近 3 次评测 contain 连续下滑（0.86 → 0.81），退化集中在长上下文样本。',
    actionText: '查看最近报告',
    link: '/reports/r-bm-1',
  },
  {
    text: '调度队列中有 1 个 prod 压测等待会签已 42 分钟，超过历史均值（12 分钟）。',
    actionText: '去任务中心查看',
    link: '/tasks',
  },
]
const insightIdx = ref(0)
const currentInsight = computed(() => insights[insightIdx.value % insights.length])
function nextInsight() {
  insightIdx.value++
}

function toggleStatusFilter(st: string) {
  filterStatus.value = filterStatus.value === st ? '' : st
}

// 智能编排
const showPlannerDrawer = ref(false)
const plannerGoal = ref('')
const isPlanning = ref(false)
const plannerSteps = ref<string[]>([])

function openPlannerDrawer() {
  // 每次打开均按当前模式写入明确目标，防止模式切换后沿用另一类任务文案。
  plannerGoal.value = modeStore.mode === 'rag'
    ? '评测知识库的 hybrid 检索质量，质量达标后自动压测 query 接口'
    : '对比被测模型在基准数据集上的表现，质量达标后自动压测'
  plannerSteps.value = []
  showPlannerDrawer.value = true
}

async function generatePlan() {
  if (!plannerGoal.value.trim()) {
    message.error('请先输入测试目标')
    return
  }
  isPlanning.value = true
  plannerSteps.value = []
  const steps = modeStore.mode === 'rag'
    ? [
      '解析目标：识别为 rag + 级联 stress（先评后压）',
      '目标资产：知识库 + 黄金 QA，按当前版本锁定评测输入',
      '检索配置：hybrid · Top-K=5，统计 Hit Rate、MRR、Recall 与 Contain',
      '运行参数：sample_size=1000 · concurrency=4 · timeout_s=60',
      '级联策略：质量成功后压测同一 query 接口（env=test · 10 QPS · 2min）',
    ]
    : [
      '解析目标：识别为 benchmark + 级联 stress（先评后压）',
      '被测协议档：选择 1–5 个目标模型进行横向对比',
      '数据集：选择当前基准数据集，主指标为 contain / exact 等',
      '运行参数：sample_size=1000 · concurrency=4 · temperature=0 · max_usd=5',
      '级联策略：质量成功后自动入队压测（env=test · 10 QPS · 2min）',
    ]
  for (let i = 0; i < steps.length; i++) {
    await new Promise(r => setTimeout(r, 200))
    plannerSteps.value.push(steps[i])
  }
  isPlanning.value = false
}

async function submitPlannerTask() {
  try {
    if (modeStore.mode === 'rag') {
      const kbs = await api.kb.list()
      const kb = kbs[0]
      if (!kb) throw new Error('当前没有可用知识库，请先在知识库工作台创建并上传黄金 QA')
      const goldQas = await api.kb.getGoldQA(kb.id)
      const goldQa = goldQas[0]
      if (!goldQa) throw new Error('当前知识库没有黄金 QA，请先上传后再编排评测')
      await api.tasks.create({
        kind: 'rag',
        kb_id: kb.id,
        gold_qa_id: goldQa.id,
        rag_mode: ['hybrid'],
        with_stress: true,
        run: { sample_size: 1000, concurrency: 4, timeout_s: 60, retry: 1, k: 5 },
        stress: { env: 'test', qps: 10, duration_s: 120 },
      })
    } else {
      const [profiles, datasets] = await Promise.all([api.profiles.list(), api.datasets.list()])
      const profileIds = profiles.slice(0, 2).map(profile => profile.id)
      const dataset = datasets[0]
      if (!profileIds.length || !dataset) throw new Error('请先准备被测协议档和基准数据集后再编排评测')
      await api.tasks.create({
        kind: 'benchmark',
        profile_ids: profileIds,
        dataset_id: dataset.id,
        with_stress: true,
        run: { sample_size: 1000, concurrency: 4, timeout_s: 60, retry: 1, temperature: 0 },
        stress: { env: 'test', qps: 10, duration_s: 120 },
      })
    }
    message.success('任务已创建（queued），编排方案已成功转为 TaskSpec')
    showPlannerDrawer.value = false
    loadTasks()
  } catch (err: any) {
    message.error(err.message || '创建任务失败')
  }
}

// 任务加载与过滤
const filteredTasks = computed(() => {
  return tasks.value.filter((t) => {
    if (t.kind !== modeTaskKind.value) return false
    if (filterStatus.value && t.status !== filterStatus.value) return false
    if (searchKw.value) {
      const kw = searchKw.value.toLowerCase()
      const matchId = t.id.toLowerCase().includes(kw)
      const matchCreator = (t.creator || t.created_by || '').toLowerCase().includes(kw)
      const matchDataset = (t.config?.dataset_id || '').toLowerCase().includes(kw)
      const matchKb = (t.config?.kb_id || '').toLowerCase().includes(kw)
      if (!matchId && !matchCreator && !matchDataset && !matchKb) return false
    }
    return true
  })
})

function canCancel(t: Task) {
  return !['succeeded', 'failed', 'cancelled'].includes(t.status)
}

function handleOpenDetail(t: Task) {
  selectedTask.value = t
  showDetailDrawer.value = true
}

async function handleCancel(t: Task) {
  dialog.warning({
    title: t.kind === 'stress' ? '立即停止发压？' : '取消评测任务？',
    content: t.kind === 'stress'
      ? `压测任务 ${t.id} 正在对目标发压，确认后立即切断连接并停止发压。`
      : `任务 ${t.id} 将在当前样本推理完成后安全停止，已完成的评测得分与报文将完整保留。`,
    positiveText: t.kind === 'stress' ? '立即停止发压' : '确认取消',
    negativeText: '放弃',
    onPositiveClick: async () => {
      try {
        await api.tasks.cancel(t.id)
        message.success('任务已成功取消')
        loadTasks()
      } catch (err: any) {
        message.error(err.message || '取消失败')
      }
    },
  })
}

async function handleRerun(t: Task) {
  try {
    await api.tasks.rerun(t.id)
    message.success('已成功复制任务并重新入队（queued）')
    loadTasks()
  } catch (err: any) {
    message.error(err.message || '重跑失败')
  }
}

async function handleRefresh() {
  loading.value = true
  await new Promise(r => setTimeout(r, 350))
  await loadTasks()
  message.info('任务列表已刷新')
}

async function loadTasks() {
  loading.value = true
  try {
    const res = await api.tasks.list({
      status: filterStatus.value || undefined,
      kind: modeTaskKind.value,
    })
    tasks.value = Array.isArray(res) ? res : ((res as any).items || [])
  } catch (err: any) {
    message.error(err.message || '加载任务列表失败')
  } finally {
    loading.value = false
  }
}

function formatRelativeTime(dateStr?: string) {
  if (!dateStr) return '刚刚'
  const diff = Date.now() - new Date(dateStr).getTime()
  const mins = Math.floor(diff / 60000)
  if (mins < 1) return '刚刚'
  if (mins < 60) return `${mins} 分钟前`
  const hours = Math.floor(mins / 60)
  if (hours < 24) return `${hours} 小时前`
  return `${Math.floor(hours / 24)} 天前`
}

onMounted(() => {
  loadTasks()
})

// 顶栏切换后立即清空局部筛选并重新请求同类任务，统计大盘与表格始终使用当前模式数据。
watch(() => modeStore.mode, () => {
  filterStatus.value = ''
  searchKw.value = ''
  void loadTasks()
})
</script>

<style scoped>
.tasks-page {
  padding-bottom: 24px;
}
.filter-bar {
  align-items: center;
}
</style>
