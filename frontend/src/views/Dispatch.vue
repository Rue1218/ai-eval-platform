<template>
  <div class="dispatch-page" data-od-id="dispatch-page" style="max-width: 1400px; margin: 0 auto">
    <!-- 调度大盘 KPI 指标 -->
    <div class="kpi-grid mb16" data-od-id="dispatch-kpis" style="--glow-c: var(--c-agent)">
      <div class="kpi">
        <div class="kpi-num num">{{ onlineCount }}<span class="unit">/ {{ workerPool.length }}</span></div>
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
        <div class="kpi-num num">{{ assignedToday }}</div>
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
            <span class="badge badge-running"><i class="bdot"></i>{{ isRunning ? '运行中' : '已暂停' }}</span>
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
            心跳周期 500ms · {{ onlineCount }}/{{ workerPool.length }} 节点就绪
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
              @click="strategy = s"
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
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, onBeforeUnmount, nextTick } from 'vue'
import { useMessage } from 'naive-ui'
import KindTag from '../components/common/KindTag.vue'

const message = useMessage()

const topoRef = ref<HTMLDivElement | null>(null)
const wiresRef = ref<SVGElement | null>(null)

const isRunning = ref(true)
const strategy = ref('负载均衡')
const capacity = ref(4)
const assignedToday = ref(126)
const assignCosts = ref([72, 85, 94, 68, 88])
const avgDispatchCost = computed(() => {
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

const onlineCount = computed(() => workerPool.value.filter(w => w.state !== 'offline').length)

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

const aiAdvices = [
  '当前 GPU-Node-A1 负载偏高（62%），建议将 judge 任务分流至 Eval-Node-E1。',
  '检测到 Stress-Node-S2 负载达 88%，可动态将流式压测切分到 S1 节点分担。',
  '亲和性策略下 RAG 评测排队时间缩短 34%，建议持续保持该模式。',
]
const aiAdviceIdx = ref(0)
const currentAiAdvice = computed(() => aiAdvices[aiAdviceIdx.value])

function nextAiAdvice() {
  aiAdviceIdx.value = (aiAdviceIdx.value + 1) % aiAdvices.length
}

function applyAiAdvice() {
  strategy.value = '亲和性'
  message.success('已采纳 AI 优化建议，策略已自动切为「亲和性」')
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
  const target = workerPool.value.find(w => w.id === selectedWorker.value?.id)
  if (target) {
    target.state = 'idle'
    target.load = 4
    target.task = null
  }
  logs.value.unshift({
    time: new Date().toTimeString().slice(0, 8),
    kind: 'NODE',
    html: `管理员重启了节点 <span class="la">${selectedWorker.value.id}</span>`,
  })
  message.success(`节点 ${selectedWorker.value.id} 已重启完毕`)
  showWorkerModal.value = false
}

function handleSaveWorker() {
  if (!selectedWorker.value) return
  const target = workerPool.value.find(w => w.id === selectedWorker.value?.id)
  if (target) {
    target.state = selectedWorker.value.state
    target.weight = selectedWorker.value.weight
    target.caps = capsInput.value.split(',').map(s => s.trim()).filter(Boolean)
  }
  logs.value.unshift({
    time: new Date().toTimeString().slice(0, 8),
    kind: 'CONFIG',
    html: `更新节点 <span class="la">${selectedWorker.value.id}</span> 配置 · 状态=${selectedWorker.value.state} · 权重=${selectedWorker.value.weight}`,
  })
  message.success(`已保存 ${selectedWorker.value.id} 节点配置`)
  showWorkerModal.value = false
}

function handleManualEnqueue() {
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
  logs.value.unshift({
    time: new Date().toTimeString().slice(0, 8),
    kind: 'ENQUEUE',
    html: `<span class="la">${newItem.qid}</span> ${newItem.label} (${newItem.prio})`,
  })
}

// 调度心跳
let timer: any = null
onMounted(() => {
  timer = setInterval(() => {
    if (!isRunning.value) return
    // 随机微调负载
    workerPool.value.forEach(w => {
      if (w.state === 'busy') {
        w.load = Math.max(10, Math.min(96, w.load + (Math.random() < 0.5 ? -2 : 2)))
      }
    })
  }, 2000)
})

onBeforeUnmount(() => {
  if (timer) clearInterval(timer)
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
