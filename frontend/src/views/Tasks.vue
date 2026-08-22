<template>
  <div class="tasks-page page-narrow" style="max-width: 1320px">
    <!-- 顶部大盘与吞吐概览 (Prototype 高保真) -->
    <div class="panel glow mb16" style="--glow-c: var(--c-tasks)">
      <div class="row-between mb10" style="flex-wrap: wrap; gap: 8px">
        <span class="eyebrow">近 24h 吞吐 · 状态分布大盘</span>
        <router-link
          to="/dispatch"
          class="small tertiary mono"
          style="display: inline-flex; align-items: center; gap: 5px; text-decoration: none; cursor: pointer; transition: color 0.15s"
          title="点击直达调度中心，查看 Worker 节点池与实时算力拓扑"
        >
          <span>Worker 节点在线 8/10 · 调度中心 🪐</span>
        </router-link>
      </div>
      <div class="tasks-overview-row">
        <div class="tasks-spark-wrap">
          <svg class="tasks-spark-svg" viewBox="0 0 230 60" preserveAspectRatio="none" aria-hidden="true">
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
          <div class="small tertiary mono spark-caption">完成 {{ tasks.length }} 任务 / 24h</div>
        </div>
        <div class="tasks-dist-wrap grow">
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
          <div class="chart-legend">
            <span
              v-for="s in statusList"
              :key="s.key"
              class="legend-pill"
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
      <div class="ai-card-head" style="flex-wrap: wrap; gap: 6px">
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
        {{ modeStore.mode === 'rag' ? 'RAG 模式' : '大模型模式' }}{{ hiddenCount > 0 ? ` · 已隐藏 ${hiddenCount} 个他域任务` : ' · 全量视图' }}
      </span>

      <div class="filter-inputs-row">
        <n-input
          v-model:value="searchKw"
          :placeholder="modeStore.mode === 'rag' ? '搜索任务 ID / 知识库 / 创建者…' : '搜索任务 ID / 数据集 / 创建者…'"
          class="filter-search-input"
          clearable
        />

        <n-select
          v-model:value="filterStatus"
          placeholder="全部状态"
          clearable
          class="filter-status-select"
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
          placeholder="全部类型"
          clearable
          class="filter-kind-select"
          :options="[
            { label: '全部类型', value: '' },
            { label: '基准评测 (benchmark)', value: 'benchmark' },
            { label: 'RAG 评测 (rag)', value: 'rag' },
            { label: '用例生成 (testcase)', value: 'testcase' },
            { label: '共享压测 (stress)', value: 'stress' },
          ]"
        />
      </div>

      <span class="grow filter-spacer"></span>

      <div class="filter-actions-row">
        <button class="btn btn-primary btn-sm" @click="openCreateModal">
          <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round">
            <path d="M12 5v14M5 12h14" />
          </svg>
          <span>新建任务</span>
        </button>

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
    </div>

    <!-- 任务数据大屏容器 (桌面表格 / 移动端卡片流) -->
    <div class="panel tasks-main-panel" style="padding: 6px 8px">
      <!-- 桌面端完整数据表格 -->
      <div class="tasks-desktop-table">
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
                  <router-link
                    v-if="['queued', 'running', 'awaiting_case_confirm'].includes(t.status)"
                    :to="{ path: '/dispatch', query: { task_id: t.id } }"
                    class="link-btn"
                    style="color: var(--accent-ai); font-weight: 500"
                    title="在调度星图中定位该任务执行链路"
                  >
                    🪐 调度
                  </router-link>
                  <button
                    v-if="canCancel(t)"
                    class="link-btn danger"
                    @click="handleCancel(t)"
                  >
                    取消
                  </button>
                  <span
                    v-else-if="isActiveTask(t)"
                    class="small tertiary"
                    title="任务取消仅限创建者本人"
                  >
                    仅创建者可取消
                  </span>
                  <button
                    v-if="canRerun(t)"
                    class="link-btn"
                    @click="handleRerun(t)"
                  >
                    复制为新任务
                  </button>
                  <span
                    v-else-if="isTerminalTask(t)"
                    class="small tertiary"
                    title="任务重跑仅限创建者本人"
                  >
                    仅创建者可重跑
                  </span>
                  <router-link
                    v-if="t.report_id"
                    :to="`/reports/${t.report_id}`"
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
      </div>

      <!-- 移动端专享任务卡片列表 (小屏设备优雅排版) -->
      <div v-if="!loading" class="tasks-mobile-card-list">
        <div
          v-for="t in filteredTasks"
          :key="'mobile-' + t.id"
          class="task-mobile-card"
          @click="handleOpenDetail(t)"
        >
          <div class="tmc-header">
            <div class="tmc-header-left">
              <span class="tmc-id mono">{{ t.id.length > 8 ? t.id.substring(0, 8) : t.id }}</span>
              <KindTag :kind="t.kind" />
              <span
                v-if="t.with_stress || t.child_stress_task_id || t.config?.with_stress"
                class="tag-soft tag-stress-mini"
              >
                先评后压
              </span>
            </div>
            <StatusBadge :status="t.status" />
          </div>

          <div class="tmc-body">
            <div class="tmc-target small">
              <span v-if="t.parent_task_id" class="mono text-task-color">
                ↳ 父任务 {{ t.parent_task_id.substring(0, 8) }}
              </span>
              <span v-else-if="t.config?.dataset_id">
                数据集: {{ t.config.dataset_id }}
              </span>
              <span v-else-if="t.config?.kb_id">
                知识库: {{ t.config.kb_id }}
              </span>
              <span v-else>目标: {{ t.id.substring(0, 12) }}</span>
            </div>

            <!-- 运行中进度条 -->
            <div v-if="t.status === 'running' && t.progress" class="tmc-progress-box">
              <div class="row-between small" style="font-size: 11px; margin-bottom: 2px">
                <span class="mono">{{ t.progress.done }}/{{ t.progress.total }}</span>
                <span class="tertiary">{{ t.progress.percent ? t.progress.percent + '%' : '' }}</span>
              </div>
              <div class="progress-bar" style="height: 4px">
                <i :style="{ width: `${t.progress.percent || Math.round((t.progress.done / (t.progress.total || 1)) * 100)}%` }"></i>
              </div>
            </div>

            <div class="tmc-meta small tertiary mono">
              <span>{{ t.creator || t.created_by || 'admin' }}</span>
              <span>·</span>
              <span>{{ formatRelativeTime(t.created_at) }}</span>
            </div>
          </div>

          <div class="tmc-footer" @click.stop>
            <button class="btn btn-secondary btn-xs" @click="handleOpenDetail(t)">详情</button>
            <router-link
              v-if="['queued', 'running', 'awaiting_case_confirm'].includes(t.status)"
              :to="{ path: '/dispatch', query: { task_id: t.id } }"
              class="btn btn-secondary btn-xs"
              style="color: var(--accent-ai)"
            >
              🪐 调度
            </router-link>
            <button
              v-if="canCancel(t)"
              class="btn btn-secondary btn-xs danger-text"
              @click="handleCancel(t)"
            >
              取消
            </button>
            <button
              v-if="canRerun(t)"
              class="btn btn-secondary btn-xs"
              @click="handleRerun(t)"
            >
              复制
            </button>
            <router-link
              v-if="t.report_id"
              :to="`/reports/${t.report_id}`"
              class="btn btn-primary btn-xs"
            >
              查看报告
            </router-link>
          </div>
        </div>
      </div>

      <EmptyState
        v-if="!loading && filteredTasks.length === 0"
        title="暂无符合条件的任务"
        description="可点击上方「智能编排」或智能体对话快速创建测试任务"
      />
    </div>

    <!-- 手动发起评测弹窗 (Create Task Modal · 与智能体确认卡同一 TaskSpec) -->
    <n-modal
      v-model:show="showCreateModal"
      preset="card"
      title="发起新评测任务 (POST /api/tasks)"
      style="width: 640px; max-width: calc(100vw - 24px)"
      :bordered="false"
    >
      <div class="form-row mb12" style="display: flex; gap: 14px; flex-wrap: wrap">
        <div class="field grow" style="min-width: 200px">
          <span class="field-label">评测类型 (Kind) <i class="req">*</i></span>
          <n-select
            v-model:value="createForm.kind"
            :options="[
              { label: 'Benchmark 基准评测', value: 'benchmark' },
              { label: 'RAG 检索质量评测', value: 'rag' },
              { label: '用例智能生成', value: 'testcase' },
              { label: '独立发压测试', value: 'stress' },
            ]"
          />
        </div>
        <div class="field" style="width: 180px; min-width: 140px">
          <span class="field-label">并发数 (Concurrency)</span>
          <n-input-number v-model:value="createForm.concurrency" :min="1" :max="16" style="width: 100%" />
        </div>
      </div>

      <div v-if="createForm.kind === 'benchmark' || createForm.kind === 'stress'" class="field mb12">
        <span class="field-label">被测协议档 (可多选，1-5个) <i class="req">*</i></span>
        <div class="row wrap" style="gap: 8px">
          <label
            v-for="p in targetProfiles"
            :key="p.id"
            class="tag-soft"
            style="cursor: pointer"
            :style="createForm.profileIds.includes(p.id) ? { color: 'var(--accent-primary)', borderColor: 'var(--accent-primary)' } : {}"
          >
            <input
              type="checkbox"
              :value="p.id"
              :checked="createForm.profileIds.includes(p.id)"
              style="margin-right: 4px"
              @change="toggleCreateProfile(p.id)"
            />
            {{ p.name }} ({{ p.model }})
          </label>
          <span v-if="targetProfiles.length === 0" class="small tertiary">暂无用途为「被测目标」的协议档，请先在协议档页创建</span>
        </div>
      </div>

      <div v-if="createForm.kind === 'benchmark'" class="field mb12">
        <span class="field-label">评测数据集 <i class="req">*</i></span>
        <n-select
          v-model:value="createForm.assetId"
          placeholder="选择基准数据集"
          :options="datasetOptions"
        />
      </div>

      <div v-if="createForm.kind === 'rag'" class="field mb12">
        <span class="field-label">评测知识库 <i class="req">*</i></span>
        <n-select
          v-model:value="createForm.assetId"
          placeholder="选择知识库"
          :options="kbOptions"
        />
      </div>

      <div v-if="createForm.kind === 'benchmark' || createForm.kind === 'rag'" class="field mb12">
        <label class="row" style="gap: 8px; cursor: pointer; user-select: none">
          <n-checkbox v-model:checked="createForm.withStress" />
          <span style="font-weight: 600">先评后压：质量任务成功后，自动对相同接口追加发压 (10 QPS / 2min)</span>
        </label>
      </div>

      <template #footer>
        <div class="row" style="justify-content: flex-end; gap: 10px">
          <button class="btn btn-secondary" @click="showCreateModal = false">取消</button>
          <button class="btn btn-sign" :disabled="createSubmitting" @click="submitCreateTask">
            {{ createSubmitting ? '入队中...' : '确认下单入队' }}
          </button>
        </div>
      </template>
    </n-modal>

    <!-- 智能编排抽屉 (AI Planner) -->
    <n-drawer v-model:show="showPlannerDrawer" :width="plannerDrawerWidth">
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
      :can-cancel="selectedTask ? canCancel(selectedTask) : false"
      :can-rerun="selectedTask ? canRerun(selectedTask) : false"
      @cancel="handleCancel(selectedTask!)"
      @rerun="handleRerun(selectedTask!)"
    />
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, watch } from 'vue'
import { useRoute } from 'vue-router'
import { useMessage, useDialog, NSelect, NInput, NInputNumber, NCheckbox, NModal, NDrawer, NDrawerContent } from 'naive-ui'
import { api } from '../api/http'
import type { Task, TaskKind, Profile, Dataset, KnowledgeBase } from '../api/types'
import { useAuthStore } from '../stores/auth'
import { useModeStore } from '../stores/mode'
import StatusBadge from '../components/common/StatusBadge.vue'
import KindTag from '../components/common/KindTag.vue'
import EmptyState from '../components/common/EmptyState.vue'
import TaskDetailDrawer from '../components/drawers/TaskDetailDrawer.vue'

const message = useMessage()
const dialog = useDialog()
const route = useRoute()
const auth = useAuthStore()
const modeStore = useModeStore()

const tasks = ref<Task[]>([])
const loading = ref(false)
const filterStatus = ref('')
const filterKind = ref('')
const searchKw = ref('')

const showDetailDrawer = ref(false)
const selectedTask = ref<Task | null>(null)

// 全局模式域：大模型域含 benchmark/stress/testcase，RAG 域含 rag/testcase；
// 他域任务不直接删除，而是按原型在列表层隐藏并在模式标签上提示隐藏数量。
const modeKinds = computed<TaskKind[]>(() =>
  modeStore.mode === 'rag' ? ['rag', 'testcase'] : ['benchmark', 'stress', 'testcase']
)
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
    // 跳转报告列表页而非硬编码报告 ID，避免 live 模式下 404
    link: '/reports',
  },
  {
    text: '调度队列中有 1 个 prod 压测等待会签已 42 分钟，超过历史均值（12 分钟）。',
    // 队列类异常应跳转调度中心，避免自跳转回本页。
    actionText: '去调度中心查看',
    link: '/dispatch',
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

/** 智能编排抽屉自适应宽度 */
const plannerDrawerWidth = computed(() => {
  if (typeof window !== 'undefined' && window.innerWidth <= 640) {
    return '100%'
  }
  return 560
})

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

// 任务加载与过滤：先按状态/类型/关键字过滤，再按全局模式隐藏他域任务
const baseFilteredTasks = computed(() => {
  return tasks.value.filter((t) => {
    if (filterStatus.value && t.status !== filterStatus.value) return false
    if (filterKind.value && t.kind !== filterKind.value) return false
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

const hiddenCount = computed(() => baseFilteredTasks.value.filter(t => !modeKinds.value.includes(t.kind)).length)
const filteredTasks = computed(() => baseFilteredTasks.value.filter(t => modeKinds.value.includes(t.kind)))

/** 判断任务是否仍处于可写的非终态。 */
function isActiveTask(t: Task) {
  return !['succeeded', 'failed', 'cancelled'].includes(t.status)
}

/** 终态任务才允许复制重跑。 */
function isTerminalTask(t: Task) {
  return ['succeeded', 'failed', 'cancelled'].includes(t.status)
}

/** 仅创建者可取消或重跑任务，和 API 的 _owned_task 权限口径保持一致。 */
function isTaskOwner(t: Task) {
  const user = auth.user
  if (!user) return false
  const creatorId = t.creator_id || t.created_by
  if (creatorId) return creatorId === user.id
  // mock 数据沿用创建者用户名，真实接口优先使用 creator_id。
  return t.creator === user.username || t.creator === user.id
}

function canCancel(t: Task) {
  return isActiveTask(t) && isTaskOwner(t)
}

function canRerun(t: Task) {
  return isTerminalTask(t) && isTaskOwner(t)
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
    // 全量拉取后在客户端按模式域隐藏他域任务，保证大盘统计与「已隐藏 N 个」提示一致
    const res = await api.tasks.list({
      status: filterStatus.value || undefined,
    })
    tasks.value = Array.isArray(res) ? res : ((res as any).items || [])
    checkRouteTaskId()
  } catch (err: any) {
    message.error(err.message || '加载任务列表失败')
  } finally {
    loading.value = false
  }
}

function checkRouteTaskId() {
  const targetId = route.query.id as string | undefined
  if (targetId) {
    const match = tasks.value.find(t => t.id === targetId || t.id.startsWith(targetId))
    if (match) {
      handleOpenDetail(match)
      message.info(`已聚焦任务 ${match.id.substring(0, 8)} 详情`)
    }
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

// 监听路由参数变化，支持外部页面直接透传跳转联动
watch(() => route.query.id, () => {
  checkRouteTaskId()
})

// 顶栏切换后立即清空局部筛选并重新拉取全量任务，统计大盘与表格始终使用当前模式数据。
watch(() => modeStore.mode, () => {
  filterStatus.value = ''
  filterKind.value = ''
  searchKw.value = ''
  void loadTasks()
})

/* ─── 手动发起评测弹窗：动态加载协议档 / 数据集 / 知识库，提交与确认卡同一 TaskSpec ─── */
const showCreateModal = ref(false)
const createSubmitting = ref(false)
const createForm = ref({
  kind: 'benchmark' as TaskKind,
  concurrency: 4,
  profileIds: [] as string[],
  assetId: null as string | null,
  withStress: true,
})
const targetProfiles = ref<Profile[]>([])
const createDatasets = ref<Dataset[]>([])
const createKbs = ref<KnowledgeBase[]>([])

const datasetOptions = computed(() =>
  createDatasets.value.map(d => ({
    label: `${d.name} (v${d.version} · ${d.row_count}条 · ${d.metric || 'contain'})`,
    value: d.id,
  }))
)
const kbOptions = computed(() =>
  createKbs.value.map(k => ({
    label: `${k.name} (${k.kind === 'lightrag' ? 'LightRAG' : '外部 Chat'})`,
    value: k.id,
  }))
)

function toggleCreateProfile(id: string) {
  const idx = createForm.value.profileIds.indexOf(id)
  if (idx >= 0) createForm.value.profileIds.splice(idx, 1)
  else if (createForm.value.profileIds.length < 5) createForm.value.profileIds.push(id)
  else message.warning('被测协议档最多选择 5 个')
}

async function openCreateModal() {
  // 默认类型跟随当前模式；先评后压默认勾选与原型一致（RAG 模式默认不勾选）
  const isRag = modeStore.mode === 'rag'
  createForm.value = {
    kind: isRag ? 'rag' : 'benchmark',
    concurrency: 4,
    profileIds: [],
    assetId: null,
    withStress: !isRag,
  }
  showCreateModal.value = true
  try {
    const [profiles, datasets, kbs] = await Promise.all([
      api.profiles.list(),
      api.datasets.list(),
      api.kb.list(),
    ])
    // 仅「被测目标」用途的协议档可参与评测/发压
    targetProfiles.value = profiles.filter(p => p.usages && p.usages.includes('target'))
    createDatasets.value = datasets
    createKbs.value = kbs
    // 原型默认勾选前两个被测协议档，降低手动建单操作成本
    createForm.value.profileIds = targetProfiles.value.slice(0, 2).map(p => p.id)
  } catch (err: any) {
    message.error(err.message || '加载协议档 / 数据集失败')
  }
}

async function submitCreateTask() {
  const f = createForm.value
  if ((f.kind === 'benchmark' || f.kind === 'stress') && f.profileIds.length === 0) {
    message.error('请至少选择 1 个被测协议档')
    return
  }
  if (f.kind === 'benchmark' && !f.assetId) {
    message.error('请选择评测数据集')
    return
  }
  if (f.kind === 'rag' && !f.assetId) {
    message.error('请选择评测知识库')
    return
  }
  createSubmitting.value = true
  try {
    await api.tasks.create({
      kind: f.kind,
      profile_ids: f.kind === 'benchmark' || f.kind === 'stress' ? [...f.profileIds] : undefined,
      dataset_id: f.kind === 'benchmark' ? f.assetId! : undefined,
      kb_id: f.kind === 'rag' ? f.assetId! : undefined,
      with_stress: f.kind === 'benchmark' || f.kind === 'rag' ? f.withStress : false,
      run: { sample_size: 1000, concurrency: f.concurrency, timeout_s: 60, retry: 1, temperature: 0, max_tokens: 1024 },
      ...(f.withStress && (f.kind === 'benchmark' || f.kind === 'rag')
        ? { stress: { env: 'test' as const, qps: 10, duration_s: 120 } }
        : {}),
    })
    message.success('评测任务已成功创建并进入调度队列（queued）')
    showCreateModal.value = false
    loadTasks()
  } catch (err: any) {
    message.error(err.message || '创建任务失败')
  } finally {
    createSubmitting.value = false
  }
}
</script>

<style scoped>
.tasks-page {
  padding-bottom: 24px;
}
.filter-bar {
  align-items: center;
}
.filter-inputs-row {
  display: flex;
  align-items: center;
  gap: 10px;
}
.filter-search-input {
  width: 240px;
}
.filter-status-select {
  width: 140px;
}
.filter-kind-select {
  width: 150px;
}
.filter-actions-row {
  display: flex;
  align-items: center;
  gap: 8px;
}

.tasks-overview-row {
  display: flex;
  align-items: center;
  gap: 28px;
}
.tasks-spark-wrap {
  flex-shrink: 0;
}
.tasks-spark-svg {
  width: 230px;
  height: 60px;
}
.chart-legend {
  margin-top: 8px;
  display: flex;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
}
.legend-pill {
  cursor: pointer;
  user-select: none;
  font-size: 12px;
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 2px 6px;
  border-radius: 4px;
  transition: background 0.15s ease;
}
.legend-pill:hover {
  background: var(--row-hover);
}

.tasks-desktop-table {
  width: 100%;
}
.tasks-mobile-card-list {
  display: none;
}

/* 移动端与小屏响应式适配 (<= 900px) */
@media (max-width: 900px) {
  .tasks-overview-row {
    gap: 16px;
  }
  .filter-search-input {
    width: 200px;
  }
}

/* 平板小屏与主流手机 (<= 768px) */
@media (max-width: 768px) {
  .tasks-page {
    padding-bottom: 16px;
  }
  .tasks-overview-row {
    flex-direction: column;
    align-items: stretch;
    gap: 12px;
  }
  .tasks-spark-wrap {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 12px;
  }
  .tasks-spark-svg {
    width: 160px;
    height: 48px;
  }
  .spark-caption {
    margin-top: 0;
  }
  .chart-legend {
    gap: 6px;
  }
  .legend-pill {
    font-size: 11px;
    padding: 2px 4px;
  }
  .filter-bar {
    flex-direction: column;
    align-items: stretch !important;
    gap: 8px !important;
  }
  .filter-inputs-row {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 8px;
    width: 100%;
  }
  .filter-search-input {
    grid-column: 1 / -1;
    width: 100% !important;
  }
  .filter-status-select,
  .filter-kind-select {
    width: 100% !important;
  }
  .filter-spacer {
    display: none;
  }
  .filter-actions-row {
    width: 100%;
    gap: 6px;
  }
  .filter-actions-row .btn {
    flex: 1;
    justify-content: center;
    font-size: 12px;
  }

  /* 切换为移动端精致卡片流 */
  .tasks-desktop-table {
    display: none;
  }
  .tasks-main-panel {
    background: transparent !important;
    border: none !important;
    padding: 0 !important;
    box-shadow: none !important;
  }
  .tasks-mobile-card-list {
    display: flex;
    flex-direction: column;
    gap: 10px;
  }
  .task-mobile-card {
    background: var(--bg-main);
    border: 1px solid var(--border-subtle);
    border-radius: 12px;
    padding: 12px 14px;
    display: flex;
    flex-direction: column;
    gap: 10px;
    box-shadow: 0 2px 8px rgba(0, 0, 0, 0.04);
    transition: all 0.15s ease;
    cursor: pointer;
  }
  .task-mobile-card:hover {
    border-color: var(--c-tasks);
    box-shadow: 0 4px 14px rgba(0, 0, 0, 0.08);
  }
  .tmc-header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 8px;
  }
  .tmc-header-left {
    display: flex;
    align-items: center;
    gap: 6px;
    flex-wrap: wrap;
  }
  .tmc-id {
    font-weight: 700;
    color: var(--c-tasks);
    font-size: 13px;
  }
  .tag-stress-mini {
    font-size: 10px;
    background: var(--t-stress);
    color: var(--c-stress);
    border-color: transparent;
    padding: 1px 5px;
  }
  .tmc-body {
    display: flex;
    flex-direction: column;
    gap: 6px;
  }
  .tmc-target {
    font-size: 12px;
    color: var(--text-secondary);
  }
  .text-task-color {
    color: var(--c-tasks);
  }
  .tmc-progress-box {
    margin: 2px 0;
  }
  .tmc-meta {
    display: flex;
    align-items: center;
    gap: 6px;
    font-size: 11px;
  }
  .tmc-footer {
    display: flex;
    align-items: center;
    justify-content: flex-end;
    gap: 6px;
    flex-wrap: wrap;
    padding-top: 8px;
    border-top: 1px dashed var(--border-subtle);
  }
}

/* 超窄屏手机 (<= 420px) */
@media (max-width: 420px) {
  .filter-inputs-row {
    grid-template-columns: 1fr;
  }
  .tasks-spark-wrap {
    flex-direction: column;
    align-items: flex-start;
  }
  .tasks-spark-svg {
    width: 100%;
  }
  .filter-actions-row {
    flex-wrap: wrap;
  }
  .filter-actions-row .btn {
    min-width: calc(50% - 4px);
  }
}
</style>
