<template>
  <div class="dispatch-page" data-od-id="dispatch-page" style="max-width: 1400px; margin: 0 auto">
    <!-- 调度大盘 KPI 指标 -->
    <div class="kpi-grid mb16" data-od-id="dispatch-kpis" style="--glow-c: var(--c-agent)">
      <div class="kpi">
        <div class="kpi-num num">{{ onlineCount }}<span class="unit">/ {{ totalWorkers }}</span></div>
        <div class="kpi-label">在线 Worker 节点</div>
      </div>
      <div class="kpi">
        <div class="kpi-num num">{{ queue.length }}</div>
        <div class="kpi-label">排队队列深度</div>
      </div>
      <div class="kpi">
        <div class="kpi-num num">{{ avgDispatchCost }}<span class="unit">ms</span></div>
        <div class="kpi-label">平均分发调度延迟</div>
      </div>
      <div class="kpi">
        <div class="kpi-num num">{{ assignedTodayDisplay }}</div>
        <div class="kpi-label">今日已分配任务</div>
      </div>
    </div>

    <div class="dispatch-grid">
      <!-- 左栏：调度器控制与策略 -->
      <div class="section-gap">
        <!-- 调度内核状态面板与雷达 -->
        <div class="panel glow" data-od-id="dispatch-radar" style="--glow-c: var(--c-agent)">
          <div class="panel-title">
            <span>调度内核状态</span>
            <span class="badge" :class="isRunning ? 'badge-running' : 'badge-cancelled'"><i class="bdot"></i>{{ isRunning ? '运行中' : '已暂停' }}</span>
          </div>
          <!-- 调度器操作入口（对齐原型顶栏 actions；顶栏无页面级插槽，故置于本面板） -->
          <div class="row mb12" style="gap: 6px">
            <button class="btn btn-secondary btn-sm" style="flex: 1" @click="toggleScheduler">
              {{ isRunning ? '暂停调度' : '恢复调度' }}
            </button>
            <button class="btn btn-primary btn-sm" style="flex: 1" @click="showRegisterModal = true">
              + 注册节点
            </button>
          </div>
          <div style="max-width: 170px; margin: 6px auto 12px">
            <div class="radar">
              <span class="radar-core"></span>
              <i class="radar-blip" style="left: 62%; top: 26%"></i>
              <i class="radar-blip" style="left: 30%; top: 58%; animation-delay: 1.3s"></i>
              <i class="radar-blip" style="left: 68%; top: 70%; animation-delay: 2.4s"></i>
            </div>
          </div>
          <p class="small tertiary" style="text-align: center; line-height: 1.6">
            心跳周期 500ms · {{ onlineCount }}/{{ totalWorkers }} 节点就绪
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

      <!-- 中栏：实时分发拓扑 -->
      <div class="panel glow" data-od-id="dispatch-topo" style="--glow-c: var(--c-agent)">
        <div class="row-between mb12">
          <div class="panel-title" style="margin: 0">
            实时分发拓扑
            <span class="small tertiary mono" style="font-weight: 400">Task Queue → Worker Pool</span>
          </div>
          <div class="row" style="gap: 6px">
            <button class="btn btn-secondary btn-sm" style="font-size: 11px" @click="handleManualEnqueue">
              + 插入任务
            </button>
          </div>
        </div>

        <div ref="topoRef" class="topo" style="position: relative">
          <svg ref="wiresRef" class="wires" aria-hidden="true" style="position: absolute; inset: 0; width: 100%; height: 100%; pointer-events: none; z-index: 5">
            <path
              v-for="(w, idx) in activeWires"
              :key="idx"
              class="wire live"
              :d="w.d"
            />
          </svg>

          <div class="topo-container">
            <!-- 待分发队列 -->
            <div>
              <div class="rail-label">待分发任务队列</div>
              <div class="section-gap" style="gap: 8px" data-od-id="dispatch-queue">
                <template v-if="queue.length">
                  <div
                    v-for="q in queue"
                    :key="q.qid"
                    class="queue-item"
                    :class="{ assigning: assignments.some(a => a.qid === q.qid) }"
                    :data-qid="q.qid"
                  >
                    <div class="row-between" style="align-items: center">
                      <div class="row" style="gap: 5px; align-items: center">
                        <KindTag :kind="q.kind" />
                        <span class="q-id mono">{{ q.qid }}</span>
                      </div>
                      <span class="tag-soft" :class="`prio-${q.prio || 'P1'}`" style="font-size: 10px; padding: 0 5px">
                        {{ q.prio || 'P1' }}
                      </span>
                    </div>
                    <div class="small" style="margin-top: 4px; font-weight: 500; line-height: 1.4">{{ q.label }}</div>
                  </div>
                </template>
                <div v-else class="empty" style="padding: 32px 10px">
                  <div class="small tertiary">队列就绪，等待新任务入队</div>
                </div>
              </div>
            </div>

            <!-- Worker 执行节点池 -->
            <div>
              <div class="rail-label">Worker 执行节点池 (点击卡片可治理)</div>
              <div class="agent-pool" data-od-id="dispatch-pool">
                <div
                  v-for="a in workerPool"
                  :key="a.id"
                  class="agent-node"
                  :class="a.state"
                  :data-aid="a.id"
                  style="cursor: pointer"
                  title="点击查看节点详情与治理"
                  @click="openWorkerModal(a)"
                >
                  <div class="an-head">
                    <span class="an-name">{{ a.id }}</span>
                    <span class="an-state" :class="a.state">
                      {{ a.state === 'idle' ? 'IDLE' : a.state === 'busy' ? 'BUSY' : a.state === 'offline' ? 'OFFLINE' : 'DRAIN' }}
                    </span>
                  </div>
                  <div class="an-caps">
                    <span v-for="c in a.caps" :key="c" class="an-cap">{{ c }}</span>
                  </div>

                  <div class="worker-metrics">
                    <div class="worker-metric-row">
                      <span>CPU</span>
                      <span>{{ a.load }}%</span>
                    </div>
                    <div class="load-track" :class="{ hot: a.load >= 80 }">
                      <i :style="{ width: `${a.load}%` }"></i>
                    </div>
                    <div class="worker-metric-row" style="margin-top: 2px">
                      <span>RAM</span>
                      <span class="mono">{{ a.ram || '2.4GB' }}</span>
                    </div>
                  </div>

                  <div class="an-task" :title="a.task || '空闲待命'">
                    <span v-if="a.task">{{ a.task }}</span>
                    <span v-else class="tertiary">空闲待命</span>
                  </div>
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>

      <!-- 右栏：分配日志流 -->
      <div class="dispatch-log-col">
        <div class="panel glow dispatch-log-panel" data-od-id="dispatch-log" style="--glow-c: var(--c-agent)">
          <div class="row-between mb8">
            <div class="panel-title" style="margin: 0">
              调度日志流 <span class="small tertiary mono">latest {{ logs.length }}</span>
            </div>
            <button class="link-btn" style="font-size: 11px" @click="logs = []">清空</button>
          </div>
          <div class="log-stream">
            <div v-for="(l, idx) in logs" :key="idx" class="log-line">
              <span class="lt">{{ l.time }}</span>
              <span class="lk">[{{ l.kind }}]</span>
              <span class="lr" v-html="l.html"></span>
            </div>
            <div v-if="!logs.length" class="empty" style="padding: 28px 10px">
              <div class="small tertiary">暂无调度事件（日志由调度器/Worker 写入，浏览器只读）</div>
            </div>
          </div>
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
              <span v-else style="color: var(--accent-success)">正常 · 500ms</span>
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
import { useMessage } from 'naive-ui'
import KindTag from '../components/common/KindTag.vue'
import { api } from '../api/http'
import type { DispatchWorker } from '../api/types'

const message = useMessage()
// live 模式接真实调度 API（§3.13）；mock 模式保留本地仿真演示
const liveMode = !api.isMock()

const topoRef = ref<HTMLDivElement | null>(null)
const wiresRef = ref<SVGElement | null>(null)

const isRunning = ref(true)
const strategy = ref('负载均衡')
const capacity = ref(4)
const assignedToday = ref(126)
const assignCosts = ref([72, 85, 94, 68, 88])
// live 模式大盘快照：KPI 与策略/容量以服务端返回为准
const overviewData = ref<{ online_workers: number; total_workers: number; avg_dispatch_cost_ms: number; assigned_today: number } | null>(null)
const avgDispatchCost = computed(() => {
  if (liveMode) return overviewData.value?.avg_dispatch_cost_ms ?? 0
  if (!assignCosts.value.length) return 81
  return Math.round(assignCosts.value.reduce((a, b) => a + b, 0) / assignCosts.value.length)
})

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

const onlineCount = computed(() =>
  liveMode && overviewData.value
    ? overviewData.value.online_workers
    : workerPool.value.filter(w => w.state !== 'offline').length
)
const totalWorkers = computed(() =>
  liveMode && overviewData.value ? overviewData.value.total_workers : workerPool.value.length
)
const assignedTodayDisplay = computed(() =>
  liveMode && overviewData.value ? overviewData.value.assigned_today : assignedToday.value
)

interface QueueItem {
  qid: string
  kind: 'benchmark' | 'rag' | 'testcase' | 'stress'
  label: string
  prio: string
  wait_ms?: number
}

const queue = ref<QueueItem[]>([
  { qid: 'q-101', kind: 'benchmark', label: 'smoke-20 v3 · shard 3/5', prio: 'P0', wait_ms: 120 },
  { qid: 'q-102', kind: 'rag', label: 'default 库 · qa-v1 回归', prio: 'P1', wait_ms: 450 },
  { qid: 'q-103', kind: 'stress', label: 'env=test · 10 QPS 压测', prio: 'P2', wait_ms: 890 },
])

const assignments = ref<{ qid: string; aid: string }[]>([])
const activeWires = ref<{ d: string }[]>([])

interface LogItem {
  time: string
  kind: string
  html: string
}

const logs = ref<LogItem[]>([
  { time: new Date().toTimeString().slice(0, 8), kind: 'ENQUEUE', html: '<span class="la">q-101</span> smoke-20 v3 · shard 3/5 (P0)' },
  { time: new Date().toTimeString().slice(0, 8), kind: 'ASSIGN', html: '<span class="la">q-100</span> → worker-01 · 耗时 82ms' },
])

/** 统一日志入口：prepend 并截断至 50 条，与原型 log() 语义一致。 */
function addLog(kind: string, html: string) {
  logs.value.unshift({ time: new Date().toTimeString().slice(0, 8), kind, html })
  if (logs.value.length > 50) logs.value.pop()
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
  const seq = Math.floor(Math.random() * 900) + 100
  const kinds: ('benchmark' | 'rag' | 'testcase' | 'stress')[] = ['benchmark', 'rag', 'testcase', 'stress']
  const k = kinds[Math.floor(Math.random() * kinds.length)]
  const newItem: QueueItem = {
    qid: `q-${seq}`,
    kind: k,
    label: `${k === 'benchmark' ? 'smoke-20 评测' : k === 'rag' ? 'default 知识库检索' : k === 'testcase' ? 'PRD 用例生成' : '10 QPS 压测'}`,
    prio: Math.random() < 0.3 ? 'P0' : 'P1',
  }
  queue.value.push(newItem)
  addLog('ENQUEUE', `<span class="la">${newItem.qid}</span> ${newItem.label} (${newItem.prio})`)
}

/* ─── 实时分发连线：按队列项与节点卡片的 DOM 坐标计算三次贝塞尔路径（还原原型 drawWires） ─── */
function drawWires() {
  const box = topoRef.value?.getBoundingClientRect()
  if (!box) {
    activeWires.value = []
    return
  }
  const paths: { d: string }[] = []
  assignments.value.forEach(as => {
    const q = topoRef.value!.querySelector(`[data-qid="${as.qid}"]`)
    const a = topoRef.value!.querySelector(`[data-aid="${as.aid}"]`)
    if (!q || !a) return
    const qr = q.getBoundingClientRect()
    const ar = a.getBoundingClientRect()
    const x1 = qr.right - box.left
    const y1 = qr.top + qr.height / 2 - box.top
    const x2 = ar.left - box.left
    const y2 = ar.top + ar.height / 2 - box.top
    const mx = (x1 + x2) / 2
    paths.push({ d: `M ${x1} ${y1} C ${mx} ${y1}, ${mx} ${y2}, ${x2} ${y2}` })
  })
  activeWires.value = paths
}

/* ─── 调度分发循环（还原原型 tryAssign/tick：按策略选节点 → 连线 → 4~8s 后完成释放） ─── */
let enqueueSeq = 200
const QUEUE_TPL: { kind: QueueItem['kind']; label: string; prio: string }[] = [
  { kind: 'benchmark', label: 'smoke-20 v3 · 规则评分', prio: 'P1' },
  { kind: 'rag', label: 'default 库 · qa-v1 检索回归', prio: 'P1' },
  { kind: 'testcase', label: 'PRD-支付链路 用例生成', prio: 'P2' },
  { kind: 'stress', label: 'env=test · 10 QPS 压测', prio: 'P2' },
]

/** 按当前策略挑选可接单节点：离线/排空节点与满载（≥92%）节点不参与。 */
function pickAgent(): WorkerNode | null {
  const candidates = workerPool.value.filter(w => w.state !== 'offline' && w.state !== 'draining' && w.state !== 'busy' && w.load < 92)
  if (!candidates.length) return null
  if (strategy.value === '负载均衡') return candidates.sort((x, y) => x.load - y.load)[0]
  if (strategy.value === '优先级抢占') return candidates[Math.floor(Math.random() * candidates.length)]
  return candidates.sort((x, y) => (y.caps.length - x.caps.length) || (x.load - y.load))[0] // 亲和性
}

function tryAssign() {
  const waiting = queue.value.filter(q => !assignments.value.some(a => a.qid === q.qid))
  if (!waiting.length) return
  const busyCount = workerPool.value.filter(w => w.state === 'busy').length
  if (busyCount >= capacity.value) {
    if (Math.random() < 0.3) addLog('HOLD', `并发已满（${busyCount}/${capacity.value}），<span class="la">${waiting[0].qid}</span> 保持排队`)
    return
  }
  const q = waiting[0]
  const agent = pickAgent()
  if (!agent) return
  const cost = 55 + Math.round(Math.random() * 70)
  assignCosts.value.push(cost)
  if (assignCosts.value.length > 12) assignCosts.value.shift()
  assignments.value.push({ qid: q.qid, aid: agent.id })
  agent.state = 'busy'
  agent.load = Math.min(96, agent.load + 24 + Math.round(Math.random() * 22))
  agent.task = q.qid + ' · ' + q.label
  assignedToday.value++
  // 队列项在分发期间保留并以 assigning 态高亮（连线端点依赖其 DOM），完成后再移出队列。
  addLog('ASSIGN', `<span class="la">${q.qid}</span> → ${agent.id} · 策略=${strategy.value} · 耗时 ${cost}ms`)

  // 4~8s 后模拟执行完成并释放并发槽位（登记句柄，卸载时统一清理）
  const doneTimer = window.setTimeout(() => {
    assignTimers.delete(doneTimer)
    assignments.value = assignments.value.filter(x => x.qid !== q.qid)
    queue.value = queue.value.filter(x => x.qid !== q.qid)
    agent.load = Math.max(4, agent.load - 32 - Math.round(Math.random() * 20))
    if (agent.load < 30) {
      agent.state = 'idle'
      agent.task = null
    }
    addLog('DONE', `${agent.id} 执行完成，释放并发槽位 · 负载回落至 ${agent.load}%`)
  }, 4000 + Math.random() * 4500)
  assignTimers.add(doneTimer)
}

/** 调度主循环节拍：45% 概率自动入队新任务，其余时间尝试分发。 */
function dispatchTick() {
  if (!isRunning.value) return
  const r = Math.random()
  if (r < 0.45 && queue.value.length < 5) {
    const tpl = QUEUE_TPL[Math.floor(Math.random() * QUEUE_TPL.length)]
    const q: QueueItem = { qid: 'q-' + enqueueSeq++, kind: tpl.kind, label: tpl.label, prio: tpl.prio }
    queue.value.push(q)
    addLog('ENQUEUE', `<span class="la">${q.qid}</span> ${tpl.label} (${q.prio})`)
    const t = window.setTimeout(() => {
      assignTimers.delete(t)
      tryAssign()
    }, 600)
    assignTimers.add(t)
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
    caps: registerForm.value.caps.split(',').map(s => s.trim()).filter(Boolean),
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

/* ─── live 模式数据接入：大盘/节点/队列周期拉取 + 调度事件增量轮询（§3.13） ─── */
let lastEventId = 0
let pollTimer: number | null = null
let pollRound = 0

/** 服务端 Worker 快照映射为拓扑卡片模型；RAM 用量契约未提供时显示占位。 */
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

/** 排队任务映射为待分发队列项；label 取关联资产 ID，优先级契约未定义时按 P1 展示。 */
function mapTaskToQueueItem(t: { id: string; kind: QueueItem['kind']; config?: any }): QueueItem {
  const cfg = t.config || {}
  const label = cfg.dataset_id
    ? `数据集 ${cfg.dataset_id}`
    : cfg.kb_id
      ? `知识库 ${cfg.kb_id}`
      : cfg.parent_task_id
        ? `↳ 派生自 ${String(cfg.parent_task_id).substring(0, 8)}`
        : `${t.kind} 任务`
  return { qid: t.id.substring(0, 8), kind: t.kind, label, prio: 'P1' }
}

function escapeHtml(s: string): string {
  return s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
}

/** 全量刷新大盘指标、节点池与排队队列（queued 任务来自任务域）。 */
async function loadLiveAll() {
  try {
    const [ov, workers, queued] = await Promise.all([
      api.dispatch.overview(),
      api.dispatch.workers(),
      api.tasks.list({ status: 'queued' }),
    ])
    if (ov) {
      overviewData.value = ov
      strategy.value = ov.strategy
      capacity.value = ov.max_running_tasks
    }
    if (workers) workerPool.value = workers.map(mapWorker)
    queue.value = queued.map(mapTaskToQueueItem)
  } catch (err: any) {
    message.error(err.message || '调度数据加载失败')
  }
}

/** 增量拉取调度事件流：日志只能由调度器/Worker 写入，浏览器不生成不改写。 */
async function pollLiveEvents() {
  try {
    const page = await api.dispatch.events(lastEventId || undefined)
    if (!page) return
    if (page.items.length) {
      const mapped = page.items.map(e => ({
        time: new Date(e.ts).toTimeString().slice(0, 8),
        kind: e.event.toUpperCase(),
        html: escapeHtml(e.message),
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

// 调度心跳
let timer: any = null
let dispatchTimer: any = null
/** 分发模拟的延时句柄登记：组件卸载时统一清理，避免回调写入已销毁状态 */
const assignTimers = new Set<number>()
onMounted(async () => {
  window.addEventListener('resize', drawWires)
  if (liveMode) {
    // 真实模式：首屏全量加载后按 3s 节拍轮询事件，6s 全量刷新，不启动本地仿真
    await loadLiveAll()
    await pollLiveEvents()
    pollTimer = window.setInterval(liveTick, 3000)
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

// 分配关系变化时在 DOM 更新后重绘连线
watch(assignments, () => nextTick(drawWires), { deep: true })

onBeforeUnmount(() => {
  if (timer) clearInterval(timer)
  if (dispatchTimer) clearInterval(dispatchTimer)
  if (pollTimer !== null) window.clearInterval(pollTimer)
  assignTimers.forEach(id => window.clearTimeout(id))
  assignTimers.clear()
  window.removeEventListener('resize', drawWires)
})
</script>

<style scoped>
.dispatch-grid {
  display: grid;
  grid-template-columns: 270px minmax(0, 1fr) 310px;
  gap: 16px;
  align-items: start;
}
.topo-container {
  position: relative;
  display: grid;
  grid-template-columns: 200px minmax(0, 1fr);
  column-gap: 56px;
  min-height: 520px;
}
.agent-pool {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(140px, 1fr));
  gap: 10px;
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
  max-height: 640px;
}
.dispatch-log-panel .log-stream {
  flex: 1;
  overflow-y: auto;
  min-height: 220px;
}
.worker-metrics {
  display: flex;
  flex-direction: column;
  gap: 4px;
  margin: 6px 0;
  font-family: var(--font-mono);
  font-size: 10px;
  color: var(--text-secondary);
}
.worker-metric-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

@media (max-width: 1360px) {
  .dispatch-grid {
    grid-template-columns: 250px minmax(0, 1fr);
  }
  .dispatch-log-col {
    grid-column: 1 / -1;
  }
  .dispatch-log-panel {
    max-height: 300px;
  }
}

@media (max-width: 880px) {
  .dispatch-grid {
    grid-template-columns: 1fr;
  }
  .topo-container {
    grid-template-columns: 1fr;
    row-gap: 24px;
  }
}
</style>
