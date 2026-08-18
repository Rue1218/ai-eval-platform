<template>
  <div class="dispatch-page" data-od-id="dispatch-page">
    <!-- ═══ 1. 调度大盘 KPI 趋势带（数字滚动 + 迷你趋势线） ═══ -->
    <div class="kpi-grid mb16" data-od-id="dispatch-kpis" style="--glow-c: var(--c-agent)">
      <div class="kpi">
        <div class="kpi-num num">{{ onlineDisplay }}<span class="unit">/ {{ totalWorkers }}</span></div>
        <div class="kpi-label">在线 Worker 节点</div>
      </div>
      <div class="kpi kpi-trend">
        <div class="kpi-num num">{{ queueDisplay }}</div>
        <div class="kpi-label">排队队列深度</div>
        <svg class="spark" viewBox="0 0 76 24" preserveAspectRatio="none"><polyline :points="sparkPoints(histQueue)" /></svg>
      </div>
      <div class="kpi kpi-trend">
        <div class="kpi-num num">{{ runningDisplay }}</div>
        <div class="kpi-label">运行中任务</div>
        <svg class="spark" viewBox="0 0 76 24" preserveAspectRatio="none"><polyline :points="sparkPoints(histRunning)" /></svg>
      </div>
      <div class="kpi kpi-trend">
        <div class="kpi-num num">{{ costDisplay }}<span class="unit">ms</span></div>
        <div class="kpi-label">平均分发调度延迟</div>
        <svg class="spark" viewBox="0 0 76 24" preserveAspectRatio="none"><polyline :points="sparkPoints(histCost)" /></svg>
      </div>
      <div class="kpi kpi-trend">
        <div class="kpi-num num">{{ assignedDisplay }}</div>
        <div class="kpi-label">今日已分配任务</div>
        <svg class="spark" viewBox="0 0 76 24" preserveAspectRatio="none"><polyline :points="sparkPoints(histAssigned)" /></svg>
      </div>
    </div>

    <!-- ═══ 2. 多 Agent 协作编排画布：四条业务流水线泳道（Benchmark / RAG / 用例 / 压测） ═══ -->
    <div class="panel glow mb16" data-od-id="dispatch-canvas" style="--glow-c: var(--c-agent)">
      <div class="row-between mb12" style="flex-wrap: wrap; gap: 8px">
        <div class="panel-title" style="margin: 0">
          多 Agent 协作编排画布
          <span class="small tertiary mono" style="font-weight: 400">Skill Agent → 任务工单 → Worker 实时流转</span>
        </div>
        <div class="row" style="gap: 6px; align-items: center">
          <span class="tag-soft" :style="modeTagStyle">{{ modeStore.mode === 'rag' ? 'RAG 模式' : '大模型模式' }}</span>
          <button class="btn btn-secondary btn-sm" style="font-size: 11px" @click="handleManualEnqueue">
            + 插入任务
          </button>
        </div>
      </div>

      <div class="canvas-wrap">
        <div ref="canvasRef" class="orch-canvas" :style="{ height: canvasLayout.totalHeight + 'px' }">
          <!-- 连线层：技能→工单灰虚线缓流；工单→Worker 蓝色流动 + 粒子 -->
          <svg class="wires" aria-hidden="true">
            <template v-for="w in activeWires" :key="w.key">
              <path :class="w.cls" :d="w.d" />
              <circle v-if="w.particle" class="particle" r="2.6">
                <animateMotion :path="w.d" dur="1.8s" repeatCount="indefinite" />
              </circle>
            </template>
          </svg>

          <template v-for="l in canvasLayout.lanes" :key="l.kind">
            <!-- 泳道背景带（左色条标识业务域） -->
            <div
              class="lane-band"
              :style="{ top: l.top + 'px', height: l.height + 'px', borderLeftColor: l.color }"
            >
              <span class="lane-caption mono" :style="{ color: l.color }">{{ l.name }}</span>
            </div>

            <!-- 泳道技能 Agent 节点（固定于泳道左侧） -->
            <div
              class="skill-node"
              :class="{ on: l.activeCount > 0 }"
              :data-skill="l.kind"
              :style="{ top: l.top + l.height / 2 - 30 + 'px' }"
              :title="l.desc"
            >
              <span class="skill-ico">{{ l.icon }}</span>
              <div class="skill-meta">
                <div class="skill-name">{{ l.name }}</div>
                <div class="skill-count mono">
                  <template v-if="l.activeCount > 0"><b class="num">{{ l.runningCount }}</b> 运行 / <b class="num">{{ l.activeCount }}</b> 活跃</template>
                  <template v-else><span class="tertiary">待命</span></template>
                </div>
              </div>
              <i v-if="l.runningCount > 0" class="skill-pulse"></i>
            </div>

            <!-- 任务工单卡片：位置由状态驱动，CSS transition 实现队列→Worker 的飞行动效 -->
            <div
              v-for="p in l.tpos"
              :key="p.t.id"
              class="canvas-task"
              :class="[p.t.status, { flash: flashTaskId === p.t.id || flashTaskId === p.t.shortId }]"
              :data-ctid="p.t.id"
              :style="{ left: p.x + '%', top: p.y + 'px' }"
              :title="`${p.t.label}\n${statusLabel(p.t.status)} · 点击前往任务中心`"
              @click="goTasks"
            >
              <div class="row" style="gap: 5px; align-items: center; min-width: 0">
                <KindTag :kind="p.t.kind" />
                <span class="ct-id mono">{{ p.t.shortId }}</span>
                <span v-if="p.t.parentId" class="tertiary" style="font-size: 10px">↳</span>
                <span class="badge ct-badge" :class="`badge-${p.t.status}`">{{ statusLabel(p.t.status) }}</span>
              </div>
              <div class="ct-label">{{ p.t.label }}</div>
              <div v-if="p.t.status === 'running'" class="ct-progress"><i :style="{ width: `${p.t.progress ?? 0}%` }"></i></div>
            </div>

            <!-- Worker 节点（单列堆叠于泳道右侧） -->
            <div
              v-for="pw in l.wpos"
              :key="pw.w.id"
              class="canvas-worker"
              :class="pw.w.state"
              :data-caid="pw.w.id"
              :style="{ left: pw.x + '%', top: pw.y + 'px' }"
              :title="`${pw.w.name} · 点击治理`"
              @click="openWorkerModal(pw.w)"
            >
              <div class="row" style="gap: 6px; align-items: center; min-width: 0">
                <i class="cw-dot" :class="pw.w.state"></i>
                <span class="cw-name mono">{{ pw.w.id }}</span>
                <span class="cw-load mono">{{ pw.w.load }}%</span>
              </div>
              <div class="load-track" :class="{ hot: pw.w.load >= 80 }" style="margin-top: 5px">
                <i :style="{ width: `${pw.w.load}%` }"></i>
              </div>
            </div>

            <!-- 泳道队列区空态提示 -->
            <div
              v-if="!l.tpos.length"
              class="lane-empty tertiary small"
              :style="{ top: l.top + l.height / 2 - 9 + 'px' }"
            >暂无工单</div>
          </template>

          <!-- 任务完成涟漪 -->
          <span v-for="r in ripples" :key="r.id" class="ripple" :style="{ left: r.x + 'px', top: r.y + 'px' }"></span>
        </div>
      </div>

      <!-- 画布图例 -->
      <div class="row mt12" style="gap: 14px; font-size: 11px; flex-wrap: wrap">
        <span class="row" style="gap: 5px; align-items: center"><i class="legend-line" style="background: repeating-linear-gradient(90deg, var(--text-tertiary) 0 3px, transparent 3px 7px)"></i><span class="tertiary">技能编排链路</span></span>
        <span class="row" style="gap: 5px; align-items: center"><i class="legend-line" style="background: var(--accent-ai)"></i><span class="tertiary">执行分发链路</span></span>
        <span class="row" style="gap: 5px; align-items: center"><i class="legend-dot" style="background: var(--accent-ai)"></i><span class="tertiary">数据流粒子</span></span>
        <span class="row" style="gap: 5px; align-items: center"><i class="legend-dot" style="background: var(--accent-success)"></i><span class="tertiary">完成涟漪</span></span>
      </div>
    </div>

    <!-- ═══ 3. 底部三栏：调度控制面 / 事件流 / 编排时间线 ═══ -->
    <div class="bottom-grid">
      <div class="section-gap">
        <!-- 调度内核状态面板与雷达 -->
        <div class="panel glow" data-od-id="dispatch-radar" style="--glow-c: var(--c-agent)">
          <div class="panel-title">
            <span>调度内核状态</span>
            <span class="badge" :class="isRunning ? 'badge-running' : 'badge-cancelled'"><i class="bdot"></i>{{ isRunning ? '运行中' : '已暂停' }}</span>
          </div>
          <div class="row mb12" style="gap: 6px">
            <button class="btn btn-secondary btn-sm" style="flex: 1" @click="toggleScheduler">
              {{ isRunning ? '暂停调度' : '恢复调度' }}
            </button>
            <button class="btn btn-primary btn-sm" style="flex: 1" @click="showRegisterModal = true">
              + 注册节点
            </button>
          </div>
          <div style="max-width: 150px; margin: 4px auto 10px">
            <div class="radar">
              <span class="radar-core"></span>
              <i class="radar-blip" style="left: 62%; top: 26%"></i>
              <i class="radar-blip" style="left: 30%; top: 58%; animation-delay: 1.3s"></i>
              <i class="radar-blip" style="left: 68%; top: 70%; animation-delay: 2.4s"></i>
            </div>
          </div>
          <p class="small tertiary" style="text-align: center; line-height: 1.6">
            心跳周期 {{ heartbeatMs }}ms · {{ onlineCount }}/{{ totalWorkers }} 节点就绪
          </p>
        </div>

        <!-- 调度分发策略面板 -->
        <div class="panel glow" data-od-id="dispatch-strategy" style="--glow-c: var(--c-agent)">
          <div class="panel-title">调度分发策略</div>
          <div class="chip-group" style="margin-bottom: 12px">
            <button
              v-for="s in ['负载均衡', '优先级抢占', '亲和性']"
              :key="s"
              class="chip"
              :class="{ on: strategy === s }"
              @click="handleStrategyChange(s)"
            >
              {{ s }}
            </button>
          </div>
          <div class="field" style="margin: 12px 0 4px">
            <div class="row-between">
              <span class="field-label" style="margin: 0">并发容量 (max_running_tasks)</span>
              <b class="num" style="color: var(--accent-ai); font-size: 15px">{{ capacity }}</b>
            </div>
            <input
              v-model.number="capacity"
              type="range"
              class="cap-slider"
              min="1"
              max="8"
              step="1"
              style="margin-top: 6px"
              @change="handleCapacityChange"
            />
            <span class="field-hint">满载时新入队任务在队列中保持 queued</span>
          </div>
        </div>

        <!-- AI 调度优化建议卡 -->
        <div class="ai-card" data-od-id="dispatch-ai">
          <div class="ai-card-head">
            <span class="ai-badge"><i class="ai-dot"></i>AI 调度优化建议</span>
            <span class="grow"></span>
            <button class="link-btn" style="font-size: 12px" @click="nextAiAdvice">换一条</button>
          </div>
          <div class="small" style="line-height: 1.5; color: var(--text-secondary); margin-top: 6px">
            {{ currentAiAdvice }}
          </div>
          <div class="row mt8" style="justify-content: flex-end">
            <button class="btn btn-ai btn-sm" @click="applyAiAdvice">采纳建议</button>
          </div>
        </div>
      </div>

      <!-- 调度事件流（分类过滤 + 点击定位画布工单） -->
      <div class="panel glow dispatch-log-panel" data-od-id="dispatch-log" style="--glow-c: var(--c-agent)">
        <div class="row-between mb8">
          <div class="panel-title" style="margin: 0">
            调度日志流 <span class="small tertiary mono">latest {{ filteredLogs.length }}</span>
          </div>
          <button class="link-btn" style="font-size: 11px" @click="logs = []">清空</button>
        </div>
        <div class="chip-group mb8" style="gap: 4px">
          <button
            v-for="c in logCats"
            :key="c.key"
            class="chip chip-xs"
            :class="{ on: logCat === c.key }"
            @click="logCat = c.key"
          >{{ c.label }}</button>
        </div>
        <div class="log-stream">
          <div
            v-for="(l, idx) in filteredLogs"
            :key="idx"
            class="log-line"
            :class="[`cat-${l.cat}`, { clickable: !!l.tid }]"
            :title="l.tid ? '点击定位画布中的任务工单' : ''"
            @click="l.tid && flashTask(l.tid)"
          >
            <span class="lt">{{ l.time }}</span>
            <span class="lk">[{{ l.kind }}]</span>
            <span class="lr" v-html="l.html"></span>
          </div>
          <div v-if="!filteredLogs.length" class="empty" style="padding: 28px 10px">
            <div class="small tertiary">暂无调度事件（日志由调度器/Worker 写入，浏览器只读）</div>
          </div>
        </div>
      </div>

      <!-- 任务编排时间线（甘特 · 先评后压父子关联） -->
      <div class="panel glow" data-od-id="dispatch-gantt" style="--glow-c: var(--c-agent)">
        <div class="row-between mb12">
          <div class="panel-title" style="margin: 0">
            任务编排时间线
            <span class="small tertiary" style="font-weight: 400">最近 {{ ganttRows.length }} 条</span>
          </div>
          <div class="row" style="gap: 8px; font-size: 11px">
            <span v-for="lg in ganttLegend" :key="lg.label" class="row" style="gap: 4px; align-items: center">
              <i class="gantt-dot" :style="{ background: lg.color }"></i><span class="tertiary">{{ lg.label }}</span>
            </span>
          </div>
        </div>
        <div v-if="ganttRows.length" class="gantt">
          <div class="gantt-axis">
            <span v-for="(tick, i) in ganttTicks" :key="i" class="mono">{{ tick }}</span>
          </div>
          <div
            v-for="row in ganttRows"
            :key="row.id"
            class="gantt-row"
            :class="{ child: row.isChild }"
            :title="`${row.label}\n${statusLabel(row.status)} · ${fmtTime(row.start)} → ${fmtTime(row.end)}`"
            @click="goTasks"
          >
            <div class="gantt-name">
              <span v-if="row.isChild" class="tertiary">↳</span>
              <KindTag :kind="row.kind" />
              <span class="mono" style="font-size: 10px">{{ row.shortId }}</span>
            </div>
            <div class="gantt-track">
              <i
                class="gantt-bar"
                :class="`st-${row.status}`"
                :style="{ left: row.left + '%', width: row.width + '%' }"
              ></i>
            </div>
          </div>
        </div>
        <div v-else class="empty" style="padding: 28px 10px">
          <div class="small tertiary">暂无任务记录，通过智能体对话或任务中心创建评测任务后此处展示编排链路</div>
        </div>
      </div>
    </div>

    <!-- 节点治理弹窗 -->
    <n-modal
      v-model:show="showWorkerModal"
      preset="card"
      :title="`Worker 节点详情 · ${selectedWorker?.id} (${selectedWorker?.name || 'Worker Node'})`"
      style="width: 580px"
    >
      <div v-if="selectedWorker">
        <div class="form-row mb12">
          <div class="field">
            <span class="field-label">节点状态</span>
            <select v-model="selectedWorker.state" class="select">
              <option value="idle">在线空闲 (IDLE)</option>
              <option value="busy">执行中 (BUSY)</option>
              <option value="draining">排空下线 (DRAINING · 不接新单)</option>
              <option value="offline">离线维护 (OFFLINE)</option>
            </select>
          </div>
          <div class="field">
            <span class="field-label">调度权重 (Weight)</span>
            <input v-model.number="selectedWorker.weight" class="input num" type="number" min="10" max="500" />
          </div>
        </div>

        <div class="field">
          <span class="field-label">专精能力标签 (Capabilities，逗号分隔)</span>
          <input v-model="capsInput" class="input mono" />
          <span class="field-hint">可选能力: benchmark, judge, rag, vector, chunking, testcase, prd, openapi, stress, load, sse</span>
        </div>

        <div class="grid-2 mt12" style="gap: 8px; background: var(--bg-elevated); padding: 12px; border-radius: 8px">
          <div>
            <div class="small tertiary">当前执行任务</div>
            <div class="small font-bold" style="margin-top: 2px">{{ selectedWorker.task || '空闲待命中' }}</div>
          </div>
          <div>
            <div class="small tertiary">资源占用</div>
            <div class="small font-bold mono" style="margin-top: 2px">CPU {{ selectedWorker.load }}% · RAM {{ selectedWorker.ram }}</div>
          </div>
          <div style="margin-top: 6px">
            <div class="small tertiary">心跳周期</div>
            <div class="small font-bold" style="margin-top: 2px">
              <span v-if="selectedWorker.state === 'offline'" style="color: var(--accent-error)">丢失（心跳超时）</span>
              <span v-else style="color: var(--accent-success)">正常 · {{ heartbeatMs }}ms</span>
            </div>
          </div>
          <div style="margin-top: 6px">
            <div class="small tertiary">权重系数</div>
            <div class="small font-bold mono" style="margin-top: 2px">{{ selectedWorker.weight }}</div>
          </div>
        </div>
      </div>

      <template #footer>
        <div style="display: flex; justify-content: space-between; width: 100%">
          <button class="btn btn-secondary" @click="handleRebootWorker">重启节点</button>
          <div style="display: flex; gap: 8px">
            <button class="btn btn-secondary" @click="showWorkerModal = false">关闭</button>
            <button class="btn btn-sign" @click="handleSaveWorker">保存配置</button>
          </div>
        </div>
      </template>
    </n-modal>

    <!-- 注册 Worker 节点弹窗（对齐原型 dispatch.html：ID/名称/能力） -->
    <n-modal v-model:show="showRegisterModal" preset="card" title="注册 Worker 节点" style="width: 460px">
      <div class="field mb12">
        <span class="field-label">节点 ID <span style="color: var(--accent-error)">*</span></span>
        <input v-model="registerForm.id" class="input mono" placeholder="例如 worker-11" />
      </div>
      <div class="field mb12">
        <span class="field-label">节点名称</span>
        <input v-model="registerForm.name" class="input" placeholder="例如 GPU-Node-B1" />
      </div>
      <div class="field">
        <span class="field-label">专精能力标签（逗号分隔）</span>
        <input v-model="registerForm.caps" class="input mono" placeholder="benchmark, judge" />
        <span class="field-hint">可选能力: benchmark, judge, rag, vector, chunking, testcase, prd, openapi, stress, load, sse</span>
      </div>
      <template #footer>
        <div style="display: flex; gap: 8px; justify-content: flex-end">
          <button class="btn btn-secondary" @click="showRegisterModal = false">取消</button>
          <button class="btn btn-sign" @click="handleRegisterWorker">注册</button>
        </div>
      </template>
    </n-modal>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, onBeforeUnmount, nextTick, watch } from 'vue'
import { useRouter } from 'vue-router'
import { useMessage } from 'naive-ui'
import KindTag from '../components/common/KindTag.vue'
import { api } from '../api/http'
import type { DispatchOverview, DispatchWorker, Task, TaskKind, TaskStatus } from '../api/types'
import { useModeStore } from '../stores/mode'

const message = useMessage()
const router = useRouter()
const modeStore = useModeStore()
// live 模式接真实调度 API（§3.13）；mock 模式保留本地仿真演示
const liveMode = !api.isMock()

const canvasRef = ref<HTMLDivElement | null>(null)

const isRunning = ref(true)
const strategy = ref('负载均衡')
const capacity = ref(4)
const assignedToday = ref(126)
const assignCosts = ref([72, 85, 94, 68, 88])
// live 模式大盘快照：KPI 与策略/容量以服务端返回为准
const overviewData = ref<DispatchOverview | null>(null)
const heartbeatMs = computed(() => overviewData.value?.heartbeat_interval_ms ?? 500)
const avgDispatchCost = computed(() => {
  if (liveMode) return overviewData.value?.avg_dispatch_cost_ms ?? 0
  if (!assignCosts.value.length) return 81
  return Math.round(assignCosts.value.reduce((a, b) => a + b, 0) / assignCosts.value.length)
})

// 顶栏模式标签配色（与全站双模式切换器联动展示）
const modeTagStyle = computed(() => ({
  color: modeStore.mode === 'rag' ? 'var(--c-kb)' : 'var(--c-datasets)',
  borderColor: modeStore.mode === 'rag' ? 'var(--t-kb)' : 'var(--t-datasets)',
}))

/* ─── KPI 数字滚动（count-up）与迷你趋势线 ─── */
function useCountUp(get: () => number) {
  const display = ref(get())
  let raf = 0
  watch(get, (to) => {
    const from = display.value
    const t0 = performance.now()
    cancelAnimationFrame(raf)
    const step = (t: number) => {
      const p = Math.min(1, (t - t0) / 350)
      display.value = Math.round(from + (to - from) * (1 - Math.pow(1 - p, 3)))
      if (p < 1) raf = requestAnimationFrame(step)
    }
    raf = requestAnimationFrame(step)
  })
  return display
}

/** 迷你趋势线：历史序列 → polyline 坐标点（76×24 视窗） */
function sparkPoints(hist: number[]): string {
  if (hist.length < 2) return ''
  const max = Math.max(...hist, 1)
  const min = Math.min(...hist, 0)
  const span = Math.max(max - min, 1)
  return hist
    .map((v, i) => `${((i / (hist.length - 1)) * 74 + 1).toFixed(1)},${(22 - ((v - min) / span) * 20).toFixed(1)}`)
    .join(' ')
}

// 各 KPI 历史序列（每次全量刷新追加，保留最近 24 点）
const histQueue = ref<number[]>([])
const histRunning = ref<number[]>([])
const histCost = ref<number[]>([])
const histAssigned = ref<number[]>([])

function pushHist(hist: number[], v: number) {
  hist.push(v)
  if (hist.length > 24) hist.shift()
}

/* ─── 编排画布数据模型 ─── */
interface WorkerNode {
  id: string
  name: string
  caps: string[]
  state: 'idle' | 'busy' | 'offline' | 'draining'
  load: number
  ram: string
  task: string | null
  weight: number
}

const workerPool = ref<WorkerNode[]>([
  { id: 'worker-01', name: 'GPU-Node-A1', caps: ['benchmark', 'judge'], state: 'busy', load: 62, ram: '4.8GB/16GB', task: 'a1f3c2 · smoke-20 v3 (shard 2/5)', weight: 100 },
  { id: 'worker-02', name: 'Vec-Node-V1', caps: ['rag', 'vector'], state: 'idle', load: 8, ram: '2.1GB/16GB', task: null, weight: 100 },
  { id: 'worker-03', name: 'Gen-Node-G1', caps: ['testcase', 'prd'], state: 'busy', load: 45, ram: '3.4GB/16GB', task: 'd4c1a9 · PRD-支付 生成用例', weight: 80 },
  { id: 'worker-04', name: 'Stress-Node-S1', caps: ['stress', 'load'], state: 'idle', load: 12, ram: '1.8GB/16GB', task: null, weight: 120 },
  { id: 'worker-05', name: 'Judge-Node-J1', caps: ['benchmark', 'prompt'], state: 'offline', load: 0, ram: '0GB/16GB', task: null, weight: 100 },
  { id: 'worker-06', name: 'Chunk-Node-C1', caps: ['rag', 'chunking'], state: 'idle', load: 5, ram: '1.2GB/16GB', task: null, weight: 80 },
  { id: 'worker-07', name: 'Stress-Node-S2', caps: ['stress', 'sse'], state: 'busy', load: 88, ram: '7.2GB/16GB', task: 'g7b3d5 · 118 QPS 流式发压', weight: 150 },
  { id: 'worker-08', name: 'Eval-Node-E1', caps: ['benchmark', 'judge'], state: 'idle', load: 18, ram: '2.6GB/16GB', task: null, weight: 100 },
  { id: 'worker-09', name: 'RAG-Node-R1', caps: ['rag', 'lightrag'], state: 'offline', load: 0, ram: '0GB/16GB', task: null, weight: 100 },
  { id: 'worker-10', name: 'Case-Node-C2', caps: ['testcase', 'openapi'], state: 'idle', load: 9, ram: '1.5GB/16GB', task: null, weight: 90 },
])

// 任务工单：统一 mock 仿真项与 live 任务的画布展示模型
interface TaskNode {
  id: string
  shortId: string
  kind: TaskKind
  label: string
  status: TaskStatus
  progress: number | null
  workerId: string | null
  parentId: string | null
}

// mock 队列项扩展：分配后携带 workerId / 进度 / 开始时间，驱动飞行连线与甘特
interface QueueItem {
  qid: string
  kind: TaskKind
  label: string
  prio: string
  workerId?: string | null
  progress?: number
  startedAt?: number
  parentId?: string | null
}

const queue = ref<QueueItem[]>([
  { qid: 'q-101', kind: 'benchmark', label: '2 模型 × 数据集 smoke-20 v3 · shard 3/5', prio: 'P0' },
  { qid: 'q-102', kind: 'rag', label: '知识库 default · 黄金 QA qa-v1 · hybrid 回归', prio: 'P1' },
  { qid: 'q-103', kind: 'stress', label: '派生压测 · env=test · 10 QPS', prio: 'P2', parentId: 'q-101' },
])

// live 模式：活跃任务（queued/running/awaiting_case_confirm）与近期任务（甘特）
const liveActiveTasks = ref<Task[]>([])
const liveRecentTasks = ref<Task[]>([])
// live 模式任务→节点映射：由 assigned 事件维护，终态事件解除
const taskWorkerMap = ref<Record<string, string>>({})

/** 任务业务上下文标签：基准=模型×数据集；RAG=知识库×黄金QA×模式；用例=PRD 来源；压测=父任务+env/QPS */
function taskLabel(t: Task): string {
  const cfg = t.config || {}
  if (t.kind === 'benchmark') {
    const models = cfg.profile_ids?.length ? `${cfg.profile_ids.length} 模型` : ''
    const ds = cfg.dataset_id ? `数据集 ${cfg.dataset_id}` : ''
    return [models, ds].filter(Boolean).join(' × ') || 'Benchmark 基准评测'
  }
  if (t.kind === 'rag') {
    const kb = cfg.kb_id ? `知识库 ${cfg.kb_id}` : 'RAG 质量评测'
    const qa = cfg.gold_qa_id ? `黄金 QA ${cfg.gold_qa_id}` : ''
    const modes = cfg.rag_mode?.length ? cfg.rag_mode.join('/') : ''
    return [kb, qa, modes].filter(Boolean).join(' · ')
  }
  if (t.kind === 'testcase') {
    if (cfg.case_source?.text) return 'PRD 文本生成用例（6 大策略配比）'
    if (cfg.case_source?.file_id) return `文件 ${cfg.case_source.file_id} 生成用例`
    return 'PRD 用例生成'
  }
  const parent = cfg.parent_task_id || t.parent_task_id ? `派生自 ${String(cfg.parent_task_id || t.parent_task_id).substring(0, 8)}` : ''
  const env = cfg.stress?.env ? `env=${cfg.stress.env}` : ''
  const qps = cfg.stress?.qps ? `${cfg.stress.qps} QPS` : ''
  return [parent, env, qps].filter(Boolean).join(' · ') || '共享压测'
}

/** live 任务 → 画布工单；workerId 优先取事件映射，兜底用节点 current_task 短号前缀匹配 */
function mapLiveTask(t: Task): TaskNode {
  const short = t.id.substring(0, 6)
  let workerId = taskWorkerMap.value[t.id] || null
  if (!workerId && t.status === 'running') {
    const w = workerPool.value.find(x => x.current_task && x.current_task.includes(short))
    workerId = w?.id || null
  }
  const pct = t.progress
    ? Math.round(t.progress.percent ?? (t.progress.total ? (t.progress.done / t.progress.total) * 100 : 0))
    : null
  return {
    id: t.id,
    shortId: t.id.substring(0, 8),
    kind: t.kind,
    label: taskLabel(t),
    status: t.status,
    progress: pct,
    workerId,
    parentId: t.parent_task_id || t.config?.parent_task_id || null,
  }
}

// 统一任务工单：live 取服务端活跃任务；mock 由仿真队列合成
const taskNodes = computed<TaskNode[]>(() => {
  if (liveMode) return liveActiveTasks.value.map(mapLiveTask)
  return queue.value.map(q => ({
    id: q.qid,
    shortId: q.qid,
    kind: q.kind,
    label: q.label,
    status: q.workerId ? 'running' as TaskStatus : 'queued' as TaskStatus,
    progress: q.workerId ? Math.round(q.progress ?? 0) : null,
    workerId: q.workerId || null,
    parentId: q.parentId || null,
  }))
})

/* ─── 业务泳道布局：四条流水线（PRD §5.5.2 技能域）+ 通用兜底泳道 ─── */
const LANE_DEFS = [
  { kind: 'benchmark' as TaskKind, name: 'Benchmark 基准评测', icon: '📊', color: 'var(--c-datasets)', desc: '模型评测 · 数据集 · 先评后压' },
  { kind: 'rag' as TaskKind, name: 'RAG 质量评估', icon: '🔍', color: 'var(--c-kb)', desc: '知识库 · 黄金 QA · 4 模式检索' },
  { kind: 'testcase' as TaskKind, name: '用例生成', icon: '🧩', color: 'var(--c-cases)', desc: 'PRD/OpenAPI · 6 大策略配比' },
  { kind: 'stress' as TaskKind, name: '共享压测', icon: '⚡', color: 'var(--c-stress)', desc: '继承父任务 · SLA 拐点定位' },
]

/** Worker 归属泳道：取能力标签中首个匹配的业务域，无匹配进通用泳道 */
function workerLane(w: WorkerNode): TaskKind | 'general' {
  const lane = LANE_DEFS.find(l => w.caps.includes(l.kind))
  return lane ? lane.kind : 'general'
}

// 画布几何常量（x 为百分比，y 为 px）
const AGENT_X = 1
const QUEUE_X = 18
const RUN_X = 46
const WORKER_X = 74
const CHIP_H = 40
const CHIP_GAP = 8
const WORKER_H = 46
const WORKER_GAP = 8
const LANE_PAD = 10

interface CanvasPos { x: number; y: number }

// 画布布局：先按泳道堆叠 Worker 得到全局节点坐标，再按状态摆放任务工单（队列区 / 随节点）
const canvasLayout = computed(() => {
  // 启用泳道：四条业务流水线 + 有未匹配节点时的通用泳道
  const defs: typeof LANE_DEFS = [...LANE_DEFS]
  if (workerPool.value.some(w => workerLane(w) === 'general')) {
    defs.push({ kind: 'general' as any, name: '通用执行', icon: '🛠', color: 'var(--text-tertiary)', desc: '未匹配业务域的执行节点' })
  }

  // 第一遍：Worker 单列堆叠，建立全局节点坐标表
  const workerPos = new Map<string, CanvasPos>()
  const laneWorkers = new Map<string, WorkerNode[]>()
  defs.forEach(d => laneWorkers.set(d.kind, workerPool.value.filter(w => workerLane(w) === d.kind)))

  const lanes: {
    kind: TaskKind | 'general'
    name: string
    icon: string
    color: string
    desc: string
    top: number
    height: number
    activeCount: number
    runningCount: number
    tpos: { t: TaskNode; x: number; y: number }[]
    wpos: { w: WorkerNode; x: number; y: number }[]
  }[] = []

  let top = 0
  defs.forEach(d => {
    const workers = laneWorkers.get(d.kind) || []
    const tasks = taskNodes.value.filter(t => t.kind === d.kind)
    const queuedCount = tasks.filter(t => t.status !== 'running').length
    // 泳道高度容纳：Worker 堆叠 / 队列堆叠 / Agent 节点
    const height = Math.max(
      84,
      LANE_PAD * 2 + workers.length * (WORKER_H + WORKER_GAP),
      LANE_PAD * 2 + queuedCount * (CHIP_H + CHIP_GAP),
    )
    const wpos = workers.map((w, i) => {
      const pos = { x: WORKER_X, y: top + LANE_PAD + i * (WORKER_H + WORKER_GAP) }
      workerPos.set(w.id, pos)
      return { w, ...pos }
    })
    lanes.push({
      kind: d.kind,
      name: d.name,
      icon: d.icon,
      color: d.color,
      desc: d.desc,
      top,
      height,
      activeCount: tasks.length,
      runningCount: tasks.filter(t => t.status === 'running').length,
      tpos: [],
      wpos,
    })
    top += height + 6
  })

  // 第二遍：任务工单定位——运行中跟随其 Worker（跨泳道允许），其余在队列区堆叠
  lanes.forEach(l => {
    const tasks = taskNodes.value.filter(t => t.kind === l.kind)
    const queued = tasks.filter(t => t.status !== 'running')
    const running = tasks.filter(t => t.status === 'running')
    const runStack = new Map<string, number>()
    l.tpos = tasks.map(t => {
      if (t.status === 'running' && t.workerId && workerPos.has(t.workerId)) {
        const wp = workerPos.get(t.workerId)!
        const stackIdx = runStack.get(t.workerId) || 0
        runStack.set(t.workerId, stackIdx + 1)
        return { t, x: RUN_X, y: wp.y + 3 + stackIdx * (CHIP_H + 4) }
      }
      // 运行中但尚未解析到节点：停在队列区右缘等待连线
      if (t.status === 'running') {
        const idx = running.indexOf(t)
        return { t, x: RUN_X, y: l.top + LANE_PAD + idx * (CHIP_H + CHIP_GAP) }
      }
      const qi = queued.indexOf(t)
      return { t, x: QUEUE_X, y: l.top + LANE_PAD + qi * (CHIP_H + CHIP_GAP) }
    })
  })

  return { lanes, totalHeight: Math.max(top - 6, 120) }
})

const onlineCount = computed(() =>
  liveMode && overviewData.value
    ? overviewData.value.online_workers
    : workerPool.value.filter(w => w.state !== 'offline').length,
)
const totalWorkers = computed(() =>
  liveMode && overviewData.value ? overviewData.value.total_workers : workerPool.value.length,
)
const queueDepth = computed(() =>
  liveMode && overviewData.value ? overviewData.value.queue_depth : queue.value.filter(q => !q.workerId).length,
)
const runningCount = computed(() => taskNodes.value.filter(t => t.status === 'running').length)
const assignedTodayNum = computed(() =>
  liveMode && overviewData.value ? overviewData.value.assigned_today : assignedToday.value,
)

// KPI 数字滚动显示值
const onlineDisplay = useCountUp(onlineCount)
const queueDisplay = useCountUp(queueDepth)
const runningDisplay = useCountUp(runningCount)
const costDisplay = useCountUp(avgDispatchCost)
const assignedDisplay = useCountUp(assignedTodayNum)

/* ─── 调度事件流（分类过滤 + 点击定位画布工单） ─── */
interface LogItem {
  time: string
  kind: string
  cat: 'assign' | 'done' | 'error' | 'node'
  html: string
  tid?: string
}

const logs = ref<LogItem[]>([
  { time: new Date().toTimeString().slice(0, 8), kind: 'ENQUEUE', cat: 'assign', html: '<span class="la">q-101</span> 2 模型 × smoke-20 v3 · shard 3/5 (P0)', tid: 'q-101' },
  { time: new Date().toTimeString().slice(0, 8), kind: 'ASSIGN', cat: 'assign', html: '<span class="la">q-100</span> → worker-01 · 耗时 82ms', tid: 'q-100' },
])

const logCat = ref<'all' | LogItem['cat']>('all')
const logCats = [
  { key: 'all' as const, label: '全部' },
  { key: 'assign' as const, label: '分配' },
  { key: 'done' as const, label: '完成' },
  { key: 'error' as const, label: '异常' },
  { key: 'node' as const, label: '节点' },
]
const filteredLogs = computed(() => (logCat.value === 'all' ? logs.value : logs.value.filter(l => l.cat === logCat.value)))

/** 事件类型归一化为展示分类 */
function eventCat(kind: string): LogItem['cat'] {
  const k = kind.toUpperCase()
  if (['ASSIGN', 'ENQUEUE', 'HOLD', 'START'].some(x => k.includes(x))) return 'assign'
  if (['DONE', 'SUCCEEDED', 'COMPLETE', 'FINISH'].some(x => k.includes(x))) return 'done'
  if (['FAIL', 'ERROR', 'TIMEOUT', 'CANCEL'].some(x => k.includes(x))) return 'error'
  return 'node'
}

/** 统一日志入口：prepend 并截断至 50 条，与原型 log() 语义一致。 */
function addLog(kind: string, html: string, tid?: string) {
  logs.value.unshift({ time: new Date().toTimeString().slice(0, 8), kind, cat: eventCat(kind), html, tid })
  if (logs.value.length > 50) logs.value.pop()
}

// 点击日志定位：闪烁画布中对应任务工单
const flashTaskId = ref('')
let flashTimer = 0
function flashTask(tid: string) {
  flashTaskId.value = tid
  window.clearTimeout(flashTimer)
  flashTimer = window.setTimeout(() => { flashTaskId.value = '' }, 1600)
}

function goTasks() {
  router.push('/tasks')
}

/* AI 建议结构化：携带建议动作（策略切换/容量调整），采纳时按内容生效（对齐原型 dispatch.html） */
interface AiAdvice {
  text: string
  strategy?: string
  cap?: number
}

const aiAdvices: AiAdvice[] = [
  { text: '当前 GPU-Node-A1 负载偏高（62%），建议切换「负载均衡」策略分流 judge 任务。', strategy: '负载均衡' },
  { text: '排队深度上升，建议将并发容量提升至 6 以消化积压任务。', cap: 6 },
  { text: '亲和性策略下 RAG 评测排队时间缩短 34%，建议持续保持该模式。', strategy: '亲和性' },
]
const aiAdviceIdx = ref(0)
const currentAiAdvice = computed(() => aiAdvices[aiAdviceIdx.value].text)

function nextAiAdvice() {
  aiAdviceIdx.value = (aiAdviceIdx.value + 1) % aiAdvices.length
}

/** 采纳建议：按建议内容切换策略/调整容量，并写入调度日志 */
function applyAiAdvice() {
  const advice = aiAdvices[aiAdviceIdx.value]
  const actions: string[] = []
  if (advice.strategy) {
    strategy.value = advice.strategy
    actions.push(`策略切换为「${advice.strategy}」`)
  }
  if (advice.cap) {
    capacity.value = advice.cap
    actions.push(`并发容量调整为 ${advice.cap}`)
  }
  if (!actions.length) actions.push('无参数变更')
  addLog('AI', `采纳调度建议：${actions.join('；')}`)
  message.success(`已采纳 AI 优化建议（${actions.join('；')}）`)
}

// 节点治理弹窗
const showWorkerModal = ref(false)
const selectedWorker = ref<WorkerNode | null>(null)
const capsInput = ref('')

function openWorkerModal(w: WorkerNode) {
  selectedWorker.value = { ...w }
  capsInput.value = (w.caps || []).join(', ')
  showWorkerModal.value = true
}

function handleRebootWorker() {
  if (!selectedWorker.value) return
  if (liveMode) {
    // 契约未定义节点重启接口，live 模式仅允许状态/权重/能力治理
    message.warning('节点重启接口尚未在 API 契约中定义，可在本弹窗调整节点状态进行治理')
    return
  }
  const target = workerPool.value.find(w => w.id === selectedWorker.value?.id)
  if (target) {
    target.state = 'idle'
    target.load = 4
    target.task = null
  }
  addLog('NODE', `管理员重启了节点 <span class="la">${selectedWorker.value.id}</span>`)
  message.success(`节点 ${selectedWorker.value.id} 已重启完毕`)
  showWorkerModal.value = false
}

async function handleSaveWorker() {
  if (!selectedWorker.value) return
  const caps = capsInput.value.split(',').map(s => s.trim()).filter(Boolean)
  if (liveMode) {
    try {
      await api.dispatch.updateWorker(selectedWorker.value.id, {
        state: selectedWorker.value.state,
        weight: selectedWorker.value.weight,
        caps,
      })
      message.success(`已保存 ${selectedWorker.value.id} 节点配置`)
      showWorkerModal.value = false
      await loadLiveAll()
    } catch (err: any) {
      message.error(err.message || '节点配置保存失败')
    }
    return
  }
  const target = workerPool.value.find(w => w.id === selectedWorker.value?.id)
  if (target) {
    target.state = selectedWorker.value.state
    target.weight = selectedWorker.value.weight
    target.caps = caps
  }
  addLog('CONFIG', `更新节点 <span class="la">${selectedWorker.value.id}</span> 配置 · 状态=${selectedWorker.value.state} · 权重=${selectedWorker.value.weight}`)
  message.success(`已保存 ${selectedWorker.value.id} 节点配置`)
  showWorkerModal.value = false
}

function handleManualEnqueue() {
  if (liveMode) {
    // 契约要求任务由智能体/表单真实创建，浏览器不得伪造入队
    message.warning('演示插单仅 mock 模式可用；请通过智能体对话或任务页「新建任务」创建真实任务')
    return
  }
  enqueueMockTask()
}

/* ─── 画布连线：技能 Agent→工单（灰虚线缓流）、工单→Worker（蓝色流动 + 粒子） ─── */
interface WirePath { key: string; d: string; cls: string; particle: boolean }
const activeWires = ref<WirePath[]>([])

// 连线规格：所有活跃工单挂技能链路；运行中工单向执行节点挂分发链路
const wireSpecs = computed(() => {
  const specs: { key: string; fromSel: string; toSel: string; cls: string; particle: boolean }[] = []
  taskNodes.value.forEach(t => {
    specs.push({ key: `s-${t.id}`, fromSel: `[data-skill="${t.kind}"]`, toSel: `[data-ctid="${t.id}"]`, cls: 'wire wire-skill', particle: false })
    if (t.status === 'running' && t.workerId) {
      specs.push({ key: `w-${t.id}`, fromSel: `[data-ctid="${t.id}"]`, toSel: `[data-caid="${t.workerId}"]`, cls: 'wire live', particle: true })
    }
  })
  return specs
})

function drawWires() {
  const box = canvasRef.value?.getBoundingClientRect()
  if (!box) {
    activeWires.value = []
    return
  }
  const paths: WirePath[] = []
  wireSpecs.value.forEach(spec => {
    const from = canvasRef.value!.querySelector(spec.fromSel)
    const to = canvasRef.value!.querySelector(spec.toSel)
    if (!from || !to) return
    const fr = from.getBoundingClientRect()
    const tr = to.getBoundingClientRect()
    const x1 = fr.right - box.left
    const y1 = fr.top + fr.height / 2 - box.top
    const x2 = tr.left - box.left
    const y2 = tr.top + tr.height / 2 - box.top
    const mx = (x1 + x2) / 2
    paths.push({ key: spec.key, cls: spec.cls, particle: spec.particle, d: `M ${x1} ${y1} C ${mx} ${y1}, ${mx} ${y2}, ${x2} ${y2}` })
  })
  activeWires.value = paths
}

/* ─── 完成涟漪：任务终态时在执行节点位置扩散一圈 ─── */
const ripples = ref<{ id: number; x: number; y: number }[]>([])
let rippleSeq = 0
function addRippleAtWorker(workerId: string | null | undefined) {
  const canvas = canvasRef.value
  if (!canvas || !workerId) return
  const el = canvas.querySelector(`[data-caid="${workerId}"]`)
  if (!el) return
  const box = canvas.getBoundingClientRect()
  const r = el.getBoundingClientRect()
  const id = ++rippleSeq
  ripples.value.push({ id, x: r.left - box.left + r.width / 2, y: r.top - box.top + r.height / 2 })
  window.setTimeout(() => { ripples.value = ripples.value.filter(p => p.id !== id) }, 1100)
}

/* ─── mock 调度分发循环：按策略选节点 → 工单飞向节点 → 进度推进 → 完成涟漪 + 甘特沉淀 ─── */
let enqueueSeq = 200
const QUEUE_TPL: { kind: TaskKind; label: string; prio: string; parentId?: string }[] = [
  { kind: 'benchmark', label: '2 模型 × 数据集 smoke-20 v3 · 规则评分', prio: 'P1' },
  { kind: 'rag', label: '知识库 default · 黄金 QA qa-v1 · naive/local 对比', prio: 'P1' },
  { kind: 'testcase', label: 'PRD-支付链路 用例生成（40/25/15/10/5/5）', prio: 'P2' },
  { kind: 'stress', label: '派生压测 · env=test · 10 QPS', prio: 'P2', parentId: 'q-101' },
]

// mock 甘特历史：完成的编排段沉淀于此（最近 12 条）
interface GanttRow {
  id: string
  shortId: string
  kind: TaskKind
  label: string
  status: TaskStatus
  start: number
  end: number
  parentId: string | null
  isChild: boolean
  left: number
  width: number
}
const mockGanttDone = ref<GanttRow[]>([])
// 甘特「当前时刻」游标：运行中条形随时间延展
const nowTs = ref(Date.now())

/** 按当前策略挑选可接单节点：离线/排空节点与满载（≥92%）节点不参与。 */
function pickAgent(): WorkerNode | null {
  const candidates = workerPool.value.filter(w => w.state !== 'offline' && w.state !== 'draining' && w.state !== 'busy' && w.load < 92)
  if (!candidates.length) return null
  if (strategy.value === '负载均衡') return candidates.sort((x, y) => x.load - y.load)[0]
  if (strategy.value === '优先级抢占') return candidates[Math.floor(Math.random() * candidates.length)]
  return candidates.sort((x, y) => (y.caps.length - x.caps.length) || (x.load - y.load))[0] // 亲和性
}

function enqueueMockTask() {
  const tpl = QUEUE_TPL[Math.floor(Math.random() * QUEUE_TPL.length)]
  const q: QueueItem = { qid: 'q-' + enqueueSeq++, kind: tpl.kind, label: tpl.label, prio: tpl.prio, parentId: tpl.parentId || null }
  queue.value.push(q)
  addLog('ENQUEUE', `<span class="la">${q.qid}</span> ${tpl.label} (${q.prio})`, q.qid)
  const t = window.setTimeout(() => {
    assignTimers.delete(t)
    tryAssign()
  }, 600)
  assignTimers.add(t)
}

function tryAssign() {
  const waiting = queue.value.filter(q => !q.workerId)
  if (!waiting.length) return
  const busyCount = workerPool.value.filter(w => w.state === 'busy').length
  if (busyCount >= capacity.value) {
    if (Math.random() < 0.3) addLog('HOLD', `并发已满（${busyCount}/${capacity.value}），<span class="la">${waiting[0].qid}</span> 保持排队`, waiting[0].qid)
    return
  }
  const q = waiting[0]
  const agent = pickAgent()
  if (!agent) return
  const cost = 55 + Math.round(Math.random() * 70)
  assignCosts.value.push(cost)
  if (assignCosts.value.length > 12) assignCosts.value.shift()
  // 工单状态置为运行并绑定节点：画布位置由 computed 驱动，CSS transition 自动播放飞行动效
  q.workerId = agent.id
  q.progress = 0
  q.startedAt = Date.now()
  agent.state = 'busy'
  agent.load = Math.min(96, agent.load + 24 + Math.round(Math.random() * 22))
  agent.task = q.qid + ' · ' + q.label
  assignedToday.value++
  addLog('ASSIGN', `<span class="la">${q.qid}</span> → ${agent.id} · 策略=${strategy.value} · 耗时 ${cost}ms`, q.qid)

  // 执行 4~8.5s：期间按节拍推进进度，完成后释放槽位、触发涟漪并沉淀甘特历史
  const duration = 4000 + Math.random() * 4500
  const progressTimer = window.setInterval(() => {
    if (q.startedAt) q.progress = Math.min(99, ((Date.now() - q.startedAt) / duration) * 100)
  }, 400)
  assignTimers.add(progressTimer)
  const doneTimer = window.setTimeout(() => {
    assignTimers.delete(doneTimer)
    window.clearInterval(progressTimer)
    assignTimers.delete(progressTimer)
    queue.value = queue.value.filter(x => x.qid !== q.qid)
    agent.load = Math.max(4, agent.load - 32 - Math.round(Math.random() * 20))
    if (agent.load < 30) {
      agent.state = 'idle'
      agent.task = null
    }
    addRippleAtWorker(agent.id)
    mockGanttDone.value.unshift({
      id: q.qid, shortId: q.qid, kind: q.kind, label: q.label, status: 'succeeded',
      start: q.startedAt || Date.now() - duration, end: Date.now(),
      parentId: q.parentId || null, isChild: !!q.parentId, left: 0, width: 0,
    })
    if (mockGanttDone.value.length > 12) mockGanttDone.value.pop()
    addLog('DONE', `${agent.id} 执行完成 <span class="la">${q.qid}</span>，释放并发槽位 · 负载回落至 ${agent.load}%`, q.qid)
  }, duration)
  assignTimers.add(doneTimer)
}

/** 调度主循环节拍：45% 概率自动入队新任务，其余时间尝试分发。 */
function dispatchTick() {
  if (!isRunning.value) return
  nowTs.value = Date.now()
  pushHist(histQueue.value, queueDepth.value)
  pushHist(histRunning.value, runningCount.value)
  pushHist(histCost.value, avgDispatchCost.value)
  pushHist(histAssigned.value, assignedTodayNum.value)
  const r = Math.random()
  if (r < 0.45 && queue.value.length < 5) {
    enqueueMockTask()
  } else {
    tryAssign()
  }
}

/** 暂停/恢复调度：暂停后已有任务继续执行，仅停止新任务入队与分发；契约未定义暂停接口，live 模式提示能力未启用 */
function toggleScheduler() {
  if (liveMode) {
    message.warning('调度暂停/恢复接口尚未在 API 契约中定义，当前仅演示模式可用')
    return
  }
  isRunning.value = !isRunning.value
  addLog('CONFIG', isRunning.value ? '调度器已恢复运行' : '调度器已暂停（已有任务继续执行）')
  message.info(isRunning.value ? '调度器已恢复' : '调度器已暂停（已有任务继续执行）')
}

/** 切换分发策略：live 模式即写 PUT /api/dispatch/config */
async function handleStrategyChange(s: string) {
  strategy.value = s
  if (!liveMode) return
  try {
    await api.dispatch.updateConfig({ strategy: s as '负载均衡' | '优先级抢占' | '亲和性' })
    message.success(`分发策略已切换为「${s}」`)
  } catch (err: any) {
    message.error(err.message || '策略更新失败')
  }
}

/** 调整全局并发容量：live 模式在滑块释放时落库 */
async function handleCapacityChange() {
  if (!liveMode) return
  try {
    await api.dispatch.updateConfig({ max_running_tasks: capacity.value })
    message.success(`并发容量已调整为 ${capacity.value}`)
  } catch (err: any) {
    message.error(err.message || '并发容量更新失败')
  }
}

// 注册节点弹窗
const showRegisterModal = ref(false)
const registerForm = ref({ id: '', name: '', caps: '' })

/** 注册新 Worker 节点：live 模式走 POST /api/dispatch/workers，mock 本地入池 */
async function handleRegisterWorker() {
  const id = registerForm.value.id.trim()
  if (!id) {
    message.warning('请输入节点 ID')
    return
  }
  if (workerPool.value.some(w => w.id === id)) {
    message.error(`节点 ${id} 已存在`)
    return
  }
  const caps = registerForm.value.caps.split(',').map(s => s.trim()).filter(Boolean)
  if (liveMode) {
    try {
      await api.dispatch.createWorker({ id, name: registerForm.value.name.trim() || id, caps })
      message.success(`节点 ${id} 已注册，等待首次心跳上报`)
      registerForm.value = { id: '', name: '', caps: '' }
      showRegisterModal.value = false
      await loadLiveAll()
    } catch (err: any) {
      message.error(err.message || '节点注册失败')
    }
    return
  }
  workerPool.value.push({
    id,
    name: registerForm.value.name.trim() || id,
    caps,
    state: 'idle',
    load: 2,
    ram: '0.5GB/16GB',
    task: null,
    weight: 100,
  })
  addLog('NODE', `注册新节点 <span class="la">${id}</span>，状态 IDLE 待接单`)
  message.success(`节点 ${id} 已注册`)
  registerForm.value = { id: '', name: '', caps: '' }
  showRegisterModal.value = false
}

/* ─── live 模式数据接入：大盘/节点/任务周期拉取 + 调度事件增量轮询（§3.13） ─── */
let lastEventId = 0
let pollTimer: number | null = null
let pollRound = 0

/** 服务端 Worker 快照映射为画布节点模型；RAM 用量契约未提供时显示占位。 */
function mapWorker(w: DispatchWorker): WorkerNode {
  return {
    id: w.id,
    name: w.name,
    caps: w.caps || [],
    state: w.state,
    load: Math.round(w.load_percent ?? 0),
    ram: '—',
    task: w.current_task || null,
    weight: w.weight,
  }
}

function escapeHtml(s: string): string {
  return s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
}

/** 全量刷新大盘指标、节点池与任务域（活跃任务进画布，近期任务进甘特）。 */
async function loadLiveAll() {
  try {
    const [ov, workers, allTasks] = await Promise.all([
      api.dispatch.overview(),
      api.dispatch.workers(),
      api.tasks.list(),
    ])
    if (ov) {
      overviewData.value = ov
      strategy.value = ov.strategy
      capacity.value = ov.max_running_tasks
    }
    if (workers) workerPool.value = workers.map(mapWorker)
    const sorted = [...allTasks].sort((a, b) => +new Date(b.created_at) - +new Date(a.created_at))
    liveActiveTasks.value = sorted.filter(t => ['queued', 'running', 'awaiting_case_confirm'].includes(t.status))
    liveRecentTasks.value = sorted.slice(0, 12)
    nowTs.value = Date.now()
    pushHist(histQueue.value, queueDepth.value)
    pushHist(histRunning.value, runningCount.value)
    pushHist(histCost.value, avgDispatchCost.value)
    pushHist(histAssigned.value, assignedTodayNum.value)
  } catch (err: any) {
    message.error(err.message || '调度数据加载失败')
  }
}

/** 增量拉取调度事件流：维护任务→节点映射与终态涟漪；日志只能由调度器/Worker 写入，浏览器不生成不改写。 */
async function pollLiveEvents() {
  try {
    const page = await api.dispatch.events(lastEventId || undefined)
    if (!page) return
    if (page.items.length) {
      page.items.forEach(e => {
        const ev = e.event.toLowerCase()
        // assigned 事件建立任务→节点映射，终态事件解除并在节点上触发涟漪
        if (ev === 'assigned' && e.task_id && e.worker_id) taskWorkerMap.value[e.task_id] = e.worker_id
        if (['succeeded', 'failed', 'cancelled'].includes(ev) && e.task_id) {
          addRippleAtWorker(taskWorkerMap.value[e.task_id])
          delete taskWorkerMap.value[e.task_id]
        }
      })
      const mapped = page.items.map(e => ({
        time: new Date(e.ts).toTimeString().slice(0, 8),
        kind: e.event.toUpperCase(),
        cat: eventCat(e.event),
        html: escapeHtml(e.message),
        tid: e.task_id || undefined,
      }))
      logs.value = [...mapped.reverse(), ...logs.value].slice(0, 50)
    }
    lastEventId = page.next_after_id
  } catch {
    // 事件轮询失败不打断页面，等待下一轮
  }
}

async function liveTick() {
  pollRound++
  await pollLiveEvents()
  if (pollRound % 2 === 0) await loadLiveAll()
}

/* ─── 任务编排时间线（甘特）：先评后压父子关联、运行中条形随时间延展 ─── */
const ganttLegend = [
  { label: '排队', color: '#9CA3AF' },
  { label: '运行中', color: 'var(--accent-ai)' },
  { label: '待确认', color: 'var(--accent-warning)' },
  { label: '成功', color: 'var(--accent-success)' },
  { label: '失败/取消', color: 'var(--accent-error)' },
]

// 甘特行：live 取近期任务；mock 取运行中队列项 + 已完成历史
const ganttBase = computed<Omit<GanttRow, 'left' | 'width'>[]>(() => {
  if (liveMode) {
    return liveRecentTasks.value.map(t => {
      const active = ['queued', 'running', 'awaiting_case_confirm'].includes(t.status)
      return {
        id: t.id,
        shortId: t.id.substring(0, 8),
        kind: t.kind,
        label: taskLabel(t),
        status: t.status,
        start: +new Date(t.created_at),
        end: active ? nowTs.value : +new Date(t.updated_at || t.created_at),
        parentId: t.parent_task_id || t.config?.parent_task_id || null,
        isChild: !!(t.parent_task_id || t.config?.parent_task_id),
      }
    })
  }
  const running: Omit<GanttRow, 'left' | 'width'>[] = queue.value
    .filter(q => q.workerId && q.startedAt)
    .map(q => ({
      id: q.qid, shortId: q.qid, kind: q.kind, label: q.label, status: 'running' as TaskStatus,
      start: q.startedAt!, end: nowTs.value, parentId: q.parentId || null, isChild: !!q.parentId,
    }))
  return [...running, ...mockGanttDone.value].slice(0, 12)
})

// 父子分组排序：父任务在前，派生压测紧随其后
const ganttRows = computed<GanttRow[]>(() => {
  const rows = [...ganttBase.value]
  if (!rows.length) return []
  const minStart = Math.min(...rows.map(r => r.start))
  const maxEnd = Math.max(nowTs.value, ...rows.map(r => r.end))
  const span = Math.max(maxEnd - minStart, 60_000)
  const positioned = rows.map(r => ({
    ...r,
    left: Math.max(0, ((r.start - minStart) / span) * 100),
    width: Math.max(1.5, ((Math.max(r.end, r.start + 800) - r.start) / span) * 100),
  }))
  // 父任务（含派生子任务的）优先，子任务紧跟其父
  const ids = new Set(positioned.map(r => r.id))
  const parents = positioned.filter(r => !r.isChild || !ids.has(r.parentId || ''))
  const children = positioned.filter(r => r.isChild && ids.has(r.parentId || ''))
  const ordered: GanttRow[] = []
  parents.sort((a, b) => a.start - b.start).forEach(p => {
    ordered.push(p)
    children.filter(c => c.parentId === p.id).forEach(c => ordered.push(c))
  })
  return ordered
})

// 时间轴刻度（起止 + 两个中间点）
const ganttTicks = computed(() => {
  const rows = ganttRows.value
  if (!rows.length) return []
  const minStart = Math.min(...rows.map(r => r.start))
  const maxEnd = Math.max(nowTs.value, ...rows.map(r => r.end))
  return [0, 1 / 3, 2 / 3, 1].map(p => fmtTime(minStart + (maxEnd - minStart) * p))
})

function fmtTime(ts: number): string {
  const d = new Date(ts)
  return `${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}:${String(d.getSeconds()).padStart(2, '0')}`
}

function statusLabel(s: string): string {
  const map: Record<string, string> = {
    queued: '排队',
    running: '运行中',
    awaiting_case_confirm: '待确认',
    succeeded: '已成功',
    failed: '已失败',
    cancelled: '已取消',
  }
  return map[s] || s
}

// 调度心跳
let timer: any = null
let dispatchTimer: any = null
let nowTimer: any = null
/** 分发模拟的延时句柄登记：组件卸载时统一清理，避免回调写入已销毁状态 */
const assignTimers = new Set<number>()
onMounted(async () => {
  window.addEventListener('resize', drawWires)
  // 甘特时间游标：运行中条形每秒延展
  nowTimer = window.setInterval(() => { nowTs.value = Date.now() }, 1000)
  if (liveMode) {
    // 真实模式：首屏全量加载后按 3s 节拍轮询事件，6s 全量刷新，不启动本地仿真
    await loadLiveAll()
    await pollLiveEvents()
    pollTimer = window.setInterval(liveTick, 3000)
    nextTick(drawWires)
    return
  }
  timer = setInterval(() => {
    if (!isRunning.value) return
    // 随机微调负载
    workerPool.value.forEach(w => {
      if (w.state === 'busy') {
        w.load = Math.max(10, Math.min(96, w.load + (Math.random() < 0.5 ? -2 : 2)))
      }
    })
  }, 2000)

  dispatchTimer = setInterval(dispatchTick, 2600)
  nextTick(drawWires)
})

// 画布布局变化时在 DOM 更新后重绘连线
watch([wireSpecs, canvasLayout], () => nextTick(drawWires), { deep: true })

onBeforeUnmount(() => {
  if (timer) clearInterval(timer)
  if (dispatchTimer) clearInterval(dispatchTimer)
  if (nowTimer) clearInterval(nowTimer)
  if (pollTimer !== null) window.clearInterval(pollTimer)
  assignTimers.forEach(id => { window.clearTimeout(id); window.clearInterval(id) })
  assignTimers.clear()
  window.clearTimeout(flashTimer)
  window.removeEventListener('resize', drawWires)
})
</script>

<style scoped>
.dispatch-page {
  max-width: 1440px;
  margin: 0 auto;
}
.bottom-grid {
  display: grid;
  grid-template-columns: 270px minmax(0, 1fr) minmax(0, 1.2fr);
  gap: 16px;
  align-items: start;
}
.cap-slider {
  width: 100%;
  accent-color: var(--accent-ai);
  cursor: pointer;
}
.dispatch-log-panel {
  display: flex;
  flex-direction: column;
  height: 100%;
  max-height: 560px;
}
.dispatch-log-panel .log-stream {
  flex: 1;
  overflow-y: auto;
  min-height: 220px;
}

/* KPI 迷你趋势线 */
.kpi-trend {
  position: relative;
  padding-bottom: 30px;
}
.kpi-trend .spark {
  position: absolute;
  left: 14px;
  right: 14px;
  bottom: 8px;
  width: calc(100% - 28px);
  height: 22px;
}
.kpi-trend .spark polyline {
  fill: none;
  stroke: var(--accent-ai);
  stroke-width: 1.4;
  opacity: 0.7;
  stroke-linejoin: round;
  stroke-linecap: round;
}

/* ═══ 编排画布 ═══ */
.canvas-wrap {
  overflow-x: auto;
  border: 1px solid var(--border-subtle);
  border-radius: 12px;
  background:
    linear-gradient(rgba(17, 24, 39, 0.03) 1px, transparent 1px),
    linear-gradient(90deg, rgba(17, 24, 39, 0.03) 1px, transparent 1px),
    var(--bg-elevated);
  background-size: 24px 24px, 24px 24px, 100% 100%;
}
.orch-canvas {
  position: relative;
  min-width: 880px;
}
.orch-canvas .wires {
  position: absolute;
  inset: 0;
  width: 100%;
  height: 100%;
  pointer-events: none;
  overflow: visible;
  z-index: 5;
}
/* 数据流粒子：沿分发链路运动 */
.particle {
  fill: var(--accent-ai);
  filter: drop-shadow(0 0 3px rgba(99, 102, 241, 0.8));
}

/* 泳道背景带：左侧业务域色条 + 顶部 caption */
.lane-band {
  position: absolute;
  left: 0;
  right: 0;
  border-left: 3px solid transparent;
  border-bottom: 1px dashed var(--border-subtle);
  background: color-mix(in srgb, var(--bg-main) 55%, transparent);
}
.lane-caption {
  position: absolute;
  top: 6px;
  right: 10px;
  font-size: 10px;
  letter-spacing: 0.06em;
  opacity: 0.75;
}

/* 技能 Agent 节点：泳道左侧固定，活跃时发光 + 脉冲点 */
.skill-node {
  position: absolute;
  left: 1%;
  width: 14%;
  min-width: 118px;
  z-index: 6;
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 10px;
  border: 1px solid var(--border-subtle);
  border-radius: 12px;
  background: var(--bg-main);
  box-shadow: 0 2px 8px rgba(17, 24, 39, 0.05);
  transition: border-color 0.2s ease, box-shadow 0.2s ease;
}
.skill-node.on {
  border-color: color-mix(in srgb, var(--accent-ai) 45%, var(--border-subtle));
  box-shadow: 0 0 0 1px color-mix(in srgb, var(--accent-ai) 18%, transparent), 0 4px 16px rgba(99, 102, 241, 0.14);
}
.skill-ico {
  width: 30px;
  height: 30px;
  flex: 0 0 30px;
  display: grid;
  place-items: center;
  border-radius: 9px;
  background: var(--bg-elevated);
  border: 1px solid var(--border-subtle);
  font-size: 15px;
}
.skill-meta {
  min-width: 0;
}
.skill-name {
  font-size: 12px;
  font-weight: 600;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.skill-count {
  font-size: 10px;
  color: var(--text-secondary);
  margin-top: 1px;
}
.skill-pulse {
  position: absolute;
  top: 6px;
  right: 6px;
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: var(--accent-ai);
  animation: dot-breathe 1.4s ease-in-out infinite;
}

/* 任务工单卡片：绝对定位 + left/top transition = 状态驱动的飞行动效 */
.canvas-task {
  position: absolute;
  width: 24%;
  z-index: 7;
  padding: 6px 10px;
  border: 1px solid var(--border-subtle);
  border-radius: 10px;
  background: var(--bg-main);
  font-size: 11.5px;
  cursor: pointer;
  box-shadow: 0 2px 8px rgba(17, 24, 39, 0.06);
  transition:
    left 0.7s cubic-bezier(0.2, 0.9, 0.3, 1),
    top 0.7s cubic-bezier(0.2, 0.9, 0.3, 1),
    border-color 0.2s ease,
    box-shadow 0.2s ease;
}
.canvas-task:hover {
  border-color: var(--accent-ai);
}
.canvas-task.queued {
  border-style: dashed;
  opacity: 0.9;
}
.canvas-task.running {
  border-color: color-mix(in srgb, var(--accent-ai) 45%, var(--border-subtle));
  box-shadow: 0 0 0 1px color-mix(in srgb, var(--accent-ai) 18%, transparent), 0 4px 14px rgba(99, 102, 241, 0.12);
}
.canvas-task.flash {
  animation: task-flash 0.8s ease-in-out 2;
}
@keyframes task-flash {
  0%, 100% { box-shadow: 0 0 0 1px color-mix(in srgb, var(--accent-ai) 18%, transparent); }
  50% { box-shadow: 0 0 0 5px color-mix(in srgb, var(--accent-ai) 45%, transparent); }
}
.ct-id {
  font-size: 10.5px;
  color: var(--c-tasks);
}
.ct-badge {
  margin-left: auto;
  font-size: 9.5px;
  padding: 0 5px;
}
.ct-label {
  margin-top: 3px;
  font-weight: 500;
  line-height: 1.35;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
/* 运行中工单底部进度条（流动条纹） */
.ct-progress {
  margin-top: 4px;
  height: 3px;
  border-radius: 999px;
  background: var(--bg-elevated);
  overflow: hidden;
}
.ct-progress > i {
  display: block;
  height: 100%;
  border-radius: 999px;
  background: repeating-linear-gradient(45deg, var(--accent-ai) 0 6px, color-mix(in srgb, var(--accent-ai) 55%, #fff) 6px 12px);
  background-size: 17px 100%;
  animation: bar-stripes 0.9s linear infinite;
  transition: width 0.4s ease;
}
@keyframes bar-stripes {
  to { background-position: 17px 0; }
}

/* Worker 画布节点：紧凑卡片，状态点 + 负载条 */
.canvas-worker {
  position: absolute;
  width: 25%;
  z-index: 6;
  padding: 7px 10px;
  border: 1px solid var(--border-subtle);
  border-radius: 10px;
  background: var(--bg-main);
  cursor: pointer;
  transition: border-color 0.2s ease, box-shadow 0.2s ease, opacity 0.2s ease;
}
.canvas-worker:hover {
  border-color: var(--text-tertiary);
}
.canvas-worker.busy {
  border-color: color-mix(in srgb, var(--accent-ai) 40%, var(--border-subtle));
  box-shadow: 0 0 0 1px color-mix(in srgb, var(--accent-ai) 16%, transparent);
}
.canvas-worker.offline {
  opacity: 0.45;
}
.cw-dot {
  width: 7px;
  height: 7px;
  flex: 0 0 7px;
  border-radius: 50%;
  background: var(--text-tertiary);
}
.cw-dot.idle { background: var(--accent-success); }
.cw-dot.busy { background: var(--accent-ai); animation: dot-breathe 1.4s ease-in-out infinite; }
.cw-dot.draining { background: var(--accent-warning); }
.cw-name {
  font-size: 11px;
  font-weight: 600;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.cw-load {
  margin-left: auto;
  font-size: 10px;
  color: var(--text-secondary);
}
.load-track {
  height: 4px;
  border-radius: 999px;
  background: var(--bg-elevated);
  overflow: hidden;
}
.load-track > i {
  display: block;
  height: 100%;
  border-radius: 999px;
  background: var(--accent-ai);
  transition: width 0.5s cubic-bezier(0.2, 0.9, 0.3, 1);
}
.load-track.hot > i {
  background: var(--accent-warning);
}

/* 泳道队列区空态 */
.lane-empty {
  position: absolute;
  left: 18%;
  width: 24%;
  text-align: center;
  z-index: 4;
}

/* 完成涟漪 */
.ripple {
  position: absolute;
  z-index: 8;
  width: 10px;
  height: 10px;
  margin: -5px;
  border-radius: 50%;
  background: var(--accent-success);
  pointer-events: none;
  animation: ripple-out 1s ease-out forwards;
}
@keyframes ripple-out {
  0% { transform: scale(1); opacity: 0.9; }
  100% { transform: scale(7); opacity: 0; }
}

/* 技能→工单连线：灰色虚线缓流（区别于工单→Worker 的高亮流动） */
:deep(.wire-skill) {
  stroke: var(--text-tertiary);
  stroke-dasharray: 3 6;
  opacity: 0.55;
  animation: dash-flow 2.4s linear infinite;
}

/* 图例 */
.legend-line {
  display: inline-block;
  width: 18px;
  height: 2px;
  border-radius: 2px;
}
.legend-dot {
  display: inline-block;
  width: 7px;
  height: 7px;
  border-radius: 50%;
}

/* 小号过滤 chip */
.chip-xs {
  font-size: 10.5px;
  padding: 2px 8px;
  min-height: 22px;
}

/* 事件流分类着色与可点击定位 */
.log-line.cat-error .lk { color: var(--accent-error); }
.log-line.cat-done .lk { color: var(--accent-success); }
.log-line.cat-node .lk { color: var(--text-tertiary); }
.log-line.clickable { cursor: pointer; border-radius: 4px; }
.log-line.clickable:hover { background: var(--row-hover); }

/* ─── 任务编排时间线（甘特） ─── */
.gantt {
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.gantt-axis {
  display: flex;
  justify-content: space-between;
  font-size: 10px;
  color: var(--text-tertiary);
  padding: 0 4px 4px 150px;
}
.gantt-row {
  display: grid;
  grid-template-columns: 150px 1fr;
  align-items: center;
  gap: 8px;
  padding: 3px 4px;
  border-radius: 6px;
  cursor: pointer;
  transition: background 0.15s ease;
}
.gantt-row:hover {
  background: var(--row-hover);
}
.gantt-row.child .gantt-name {
  padding-left: 14px;
}
.gantt-name {
  display: flex;
  align-items: center;
  gap: 6px;
  min-width: 0;
  overflow: hidden;
  white-space: nowrap;
}
.gantt-track {
  position: relative;
  height: 14px;
  border-radius: 4px;
  background: var(--bg-elevated);
  overflow: hidden;
}
.gantt-bar {
  position: absolute;
  top: 2px;
  bottom: 2px;
  border-radius: 4px;
  transition: left 0.6s ease, width 0.6s ease;
}
.gantt-bar.st-queued { background: #9ca3af; }
.gantt-bar.st-running {
  background: repeating-linear-gradient(45deg, var(--accent-ai) 0 8px, color-mix(in srgb, var(--accent-ai) 55%, #fff) 8px 16px);
  background-size: 23px 100%;
  animation: bar-stripes 0.9s linear infinite;
}
.gantt-bar.st-awaiting_case_confirm { background: var(--accent-warning); }
.gantt-bar.st-succeeded { background: var(--accent-success); }
.gantt-bar.st-failed,
.gantt-bar.st-cancelled { background: var(--accent-error); opacity: 0.75; }
.gantt-dot {
  display: inline-block;
  width: 8px;
  height: 8px;
  border-radius: 3px;
}

@media (max-width: 1200px) {
  .bottom-grid {
    grid-template-columns: 250px minmax(0, 1fr);
  }
  .bottom-grid > :last-child {
    grid-column: 1 / -1;
  }
}

@media (max-width: 880px) {
  .bottom-grid {
    grid-template-columns: 1fr;
  }
  .gantt-axis {
    padding-left: 110px;
  }
  .gantt-row {
    grid-template-columns: 110px 1fr;
  }
}
</style>
