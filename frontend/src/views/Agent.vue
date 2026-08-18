<template>
  <div class="agent-layout" :class="{ 'with-rail': isRailOpen }">
    <!-- 左侧会话列表轨 (264px) -->
    <aside class="session-list">
      <div class="session-list-head">
        <button class="btn btn-secondary btn-sm" style="width: 100%" @click="handleCreateSession">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <line x1="12" y1="5" x2="12" y2="19"></line>
            <line x1="5" y1="12" x2="19" y2="12"></line>
          </svg>
          <span>新建会话</span>
        </button>
      </div>

      <div class="session-items">
        <div
          v-for="s in sessions"
          :key="s.id"
          class="session-item"
          :class="{ active: currentSessionId === s.id }"
          @click="selectSession(s.id)"
        >
          <div class="session-title">
            <span>{{ s.title || '新对话' }}</span>
            <i v-if="s.active_task" class="nav-dot running"></i>
          </div>
          <div class="session-time mono">{{ formatRelativeTime(s.created_at) }}</div>
        </div>
      </div>
    </aside>

    <!-- 中间对话主区 -->
    <section class="chat-main">
      <!-- 头部 -->
      <div class="chat-head">
        <div class="chat-head-title">{{ currentSession?.title || '新对话' }}</div>
        <div class="chat-head-model mono">{{ agentProfileName }}</div>
        <div v-if="isGenerating" class="gen-pill">
          <i class="bdot"></i>
          <span>生成中...</span>
        </div>
        <div v-if="!wsConnected" class="offline-tag mono" style="font-size: 11px; color: var(--accent-warning)">
          断线重连中...
        </div>

        <span class="grow"></span>

        <!-- 调度视图切换按钮 -->
        <button
          class="btn btn-sm"
          :class="isRailOpen ? 'btn-secondary' : 'btn-ghost'"
          title="展开/折叠任务调度分配侧轨"
          @click="isRailOpen = !isRailOpen"
        >
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <rect x="3" y="3" width="18" height="18" rx="2" ry="2"></rect>
            <line x1="9" y1="3" x2="9" y2="21"></line>
          </svg>
          <span>调度视图</span>
        </button>
      </div>

      <!-- 消息流滚动区 -->
      <div ref="chatScrollRef" class="chat-scroll" @scroll="handleScroll">
        <div class="chat-col">
          <!-- 空会话欢迎态 -->
          <div v-if="events.length === 0" class="welcome">
            <div class="welcome-eyebrow">AI EVAL AGENT · 大模型与 RAG 评测智能体</div>
            <div class="welcome-title">说明要评什么，剩下的交给我</div>
            <div class="welcome-sub">
              通过对话自动拆解评测需求，完成用例生成、三协议 Benchmark 自动化跑测、LightRAG 混合检索评测及先评后压。
            </div>

            <div class="welcome-caps">
              <div class="cap" @click="sendPredefined('帮我对 OpenAI 与 Claude 两个主流模型进行一单 Benchmark 基准评测')">
                <div class="cap-ico">
                  <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                    <ellipse cx="12" cy="5" rx="9" ry="3"></ellipse>
                    <path d="M21 12c0 1.66-4 3-9 3s-9-1.34-9-3"></path>
                    <path d="M3 5v14c0 1.66 4 3 9 3s9-1.34 9-3V5"></path>
                  </svg>
                </div>
                <div>
                  <span class="cap-name">基准评测 (Benchmark)</span>
                  <span class="cap-desc">多模型并排对比，自动打分与失败样本归因</span>
                </div>
              </div>

              <div class="cap" @click="sendPredefined('帮我对知识库 default 进行一次 RAG 混合检索能力评测')">
                <div class="cap-ico">
                  <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                    <path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20"></path>
                    <path d="M6.5 2H20v20H6.5A2.5 2.5 0 0 1 4 19.5v-15A2.5 2.5 0 0 1 6.5 2z"></path>
                  </svg>
                </div>
                <div>
                  <span class="cap-name">知识库评测 (RAG)</span>
                  <span class="cap-desc">评估 LightRAG 混合召回与图谱命中率 Hit Rate@5</span>
                </div>
              </div>

              <div class="cap" @click="sendPredefined('请根据附件需求文档生成一批测试用例并进行约束反向自检')">
                <div class="cap-ico">
                  <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                    <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"></path>
                    <polyline points="14 2 14 8 20 8"></polyline>
                  </svg>
                </div>
                <div>
                  <span class="cap-name">用例生成与自检</span>
                  <span class="cap-desc">生成结构化正反向用例，支持映射入库</span>
                </div>
              </div>

              <div class="cap" @click="sendPredefined('帮我发起模型质量评测，并在质量成功后自动派生压测')">
                <div class="cap-ico">
                  <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                    <polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2"></polygon>
                  </svg>
                </div>
                <div>
                  <span class="cap-name">先评后压 (Stress)</span>
                  <span class="cap-desc">质量 succeeded 后自动执行 QPS/RT/SLA 压测</span>
                </div>
              </div>
            </div>
          </div>

          <!-- 消息流组件渲染 -->
          <template v-for="(item, idx) in events" :key="idx">
            <!-- 1. 用户气泡 -->
            <div v-if="item.type === 'user'" class="msg-user">
              <div class="bubble-user">{{ item.text }}</div>
              <div v-if="item.file" class="attach-chip">
                <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                  <path d="M21.44 11.05l-9.19 9.19a6 6 0 0 1-8.49-8.49l9.19-9.19a4 4 0 0 1 5.66 5.66l-9.2 9.19a2 2 0 0 1-2.83-2.83l8.49-8.48"></path>
                </svg>
                <span>{{ item.file.filename || '附件' }}</span>
              </div>
            </div>

            <!-- 2. 思考卡 -->
            <ThoughtCard
              v-else-if="item.type === 'thought'"
              :text="item.text || ''"
              :done="item.done"
            />

            <!-- 3. 工具调用卡 -->
            <ToolCard
              v-else-if="item.type === 'tool'"
              :tool="item.tool || ''"
              :args="item.args"
              :result="item.result"
              :status="item.status"
            />

            <!-- 4. 确认卡 -->
            <ConfirmCard
              v-else-if="item.type === 'confirm' && item.card"
              :card="item.card"
              :is-acked="item.isAcked"
              :ack-result="item.ackResult"
              :submitting="item.submitting"
              @confirm="(patch) => handleConfirmAck(item, true, patch)"
              @cancel="() => handleConfirmAck(item, false)"
            />

            <!-- 5. 报告卡 -->
            <ReportCard
              v-else-if="item.type === 'report' && item.reportId"
              :report-id="item.reportId"
              @interpret="handleInterpretReport"
            />

            <!-- 6. 错误条 -->
            <ErrorStrip
              v-else-if="item.type === 'error'"
              :message="item.message"
            />

            <!-- 7. Agent 文本回复 -->
            <div v-else-if="item.type === 'agent'" class="msg-agent">
              <p>{{ item.text }}</p>
            </div>
          </template>
        </div>

        <!-- 回到底部悬浮按钮 -->
        <div class="jump-wrap">
          <button class="jump-bottom" :class="{ show: showJumpBottom }" @click="scrollToBottom(true)">
            <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round">
              <polyline points="6 9 12 15 18 9"></polyline>
            </svg>
            <span>回到底部</span>
          </button>
        </div>
      </div>

      <!-- 进度坞 (吸附输入框上方) -->
      <ProgressDock
        :task="activeTask"
        @cancel="handleCancelActiveTask"
      />

      <!-- 输入栏 -->
      <Composer
        :connected="wsConnected"
        :agent-model-name="agentProfileName"
        @send="handleUserSend"
      />
    </section>

    <!-- 右侧迷你调度视图 (308px) -->
    <aside class="dispatch-rail">
      <div class="rail-head">
        <div class="row-between">
          <span style="font-size: 13px; font-weight: 600">调度视图</span>
          <router-link to="/tasks" class="link-btn" style="font-size: 12px">任务中心 →</router-link>
        </div>
        <div class="small tertiary" style="margin-top: 4px">当前会话任务的实时分配</div>
      </div>
      <div class="rail-body">
        <div>
          <div class="rail-label">运行中任务</div>
          <div v-if="activeTask" class="queue-item assigning">
            <KindTag :kind="activeTask.kind" />
            <div class="small mono" style="margin-top: 4px">
              {{ activeTask.id.substring(0, 8) }} · {{ activeTask.kind === 'stress' ? 'go-stress-testing' : '评测执行中' }}
            </div>
          </div>
          <p v-else class="small tertiary" style="margin: 0">当前会话没有运行中的任务</p>
        </div>

        <div>
          <div class="rail-label">Worker 节点状态</div>
          <div style="display: flex; flex-direction: column; gap: 8px">
            <div
              v-for="w in railWorkers"
              :key="w.id"
              class="agent-node"
              :class="{ busy: w.load > 30 }"
            >
              <div class="an-head">
                <span class="an-name mono">{{ w.id }}</span>
                <span class="an-state" :class="w.load > 30 ? 'busy' : 'idle'">
                  {{ w.load > 30 ? 'BUSY' : 'IDLE' }}
                </span>
              </div>
              <div class="load-track" :class="{ hot: w.load >= 80 }" style="margin-top: 6px">
                <i :style="{ width: `${w.load}%` }"></i>
              </div>
            </div>
          </div>
        </div>

        <div>
          <div class="rail-label">调度日志</div>
          <div class="log-stream">
            <div v-for="(l, idx) in dispatchLogs" :key="idx" class="log-line">
              <span class="lt">{{ l.time }}</span>
              <span class="lk">{{ l.kind }}</span>
              <span class="lr">{{ l.msg }}</span>
            </div>
          </div>
        </div>
      </div>
    </aside>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, onBeforeUnmount, nextTick } from 'vue'
import { useMessage } from 'naive-ui'
import { api } from '../api/http'
import { AgentWebSocket } from '../api/ws'
import type { Task, TaskSpec, WsServerEvent } from '../api/types'
import ThoughtCard from '../components/agent/ThoughtCard.vue'
import ToolCard from '../components/agent/ToolCard.vue'
import ConfirmCard from '../components/agent/ConfirmCard.vue'
import ReportCard from '../components/agent/ReportCard.vue'
import ProgressDock from '../components/agent/ProgressDock.vue'
import Composer from '../components/agent/Composer.vue'
import ErrorStrip from '../components/common/ErrorStrip.vue'
import KindTag from '../components/common/KindTag.vue'

const message = useMessage()
const chatScrollRef = ref<HTMLDivElement | null>(null)

const sessions = ref<any[]>([
  { id: 's-01', title: 'GPT-4o 与 Claude 3.5 对比评测', created_at: new Date().toISOString() },
])
const currentSessionId = ref<string>('s-01')
const isGenerating = ref(false)
const wsConnected = ref(false)
const activeTask = ref<Task | null>(null)
const agentProfileName = ref('Agent · 主模型')
const isRailOpen = ref(false)
const showJumpBottom = ref(false)

// 调度侧轨节点与日志
const railWorkers = ref([
  { id: 'worker-01', load: 62 },
  { id: 'worker-02', load: 24 },
  { id: 'worker-03', load: 8 },
])
const dispatchLogs = ref([
  { time: '12:01:02', kind: 'ENQUEUE', msg: 'a1f3c2 smoke-20 v3' },
  { time: '12:01:08', kind: 'ASSIGN', msg: 'shard 1/4 → worker-01' },
])

let agentWs: AgentWebSocket | null = null
let taskPollingTimer: number | null = null

interface StreamItem {
  type: 'user' | 'agent' | 'thought' | 'tool' | 'confirm' | 'report' | 'error'
  text?: string
  done?: boolean
  tool?: string
  args?: any
  result?: any
  status?: 'pending' | 'ok' | 'fail'
  card?: TaskSpec
  isAcked?: boolean
  ackResult?: boolean
  submitting?: boolean
  reportId?: string
  message?: string
  file?: any
}

const events = ref<StreamItem[]>([])

const currentSession = computed(() => {
  return sessions.value.find((s) => s.id === currentSessionId.value)
})

function handleScroll() {
  if (!chatScrollRef.value) return
  const { scrollTop, scrollHeight, clientHeight } = chatScrollRef.value
  const distFromBottom = scrollHeight - scrollTop - clientHeight
  showJumpBottom.value = distFromBottom > 80
}

function scrollToBottom(force = false) {
  nextTick(() => {
    if (chatScrollRef.value) {
      chatScrollRef.value.scrollTop = chatScrollRef.value.scrollHeight
    }
  })
}

async function loadSessions() {
  // 拉取服务端会话后优先保留当前选择，否则切换到第一条可用会话。
  try {
    const list = await api.sessions.list()
    if (list && list.length > 0) {
      sessions.value = list
      if (!list.some((session) => session.id === currentSessionId.value)) {
        currentSessionId.value = list[0].id
      }
    }
  } catch {
    // 离线使用默认会话
  }
}

async function selectSession(sid: string) {
  // 会话切换需恢复持久化内容，并以最后事件号建立 WebSocket 补发连接。
  currentSessionId.value = sid
  events.value = []
  activeTask.value = null
  stopTaskPolling()
  const lastEventId = await restoreSession(sid)
  initWebSocket(sid, lastEventId)
}

async function handleCreateSession() {
  try {
    const newSession = await api.sessions.create('新评测对话')
    sessions.value.unshift(newSession)
    selectSession(newSession.id)
  } catch (err: any) {
    message.error(err.message || '创建会话失败')
  }
}

function initWebSocket(sessionId: string, lastEventId = 0) {
  // 每个会话只维持一个连接，重建前关闭旧连接以避免事件串流。
  if (agentWs) {
    agentWs.close()
    agentWs = null
  }

  agentWs = new AgentWebSocket(sessionId)
  agentWs.lastEventId = lastEventId
  agentWs.onStatus((connected) => {
    wsConnected.value = connected
  })
  agentWs.onEvent((ev: WsServerEvent) => {
    handleWsEvent(ev)
  })
  agentWs.connect()
}

async function restoreSession(sessionId: string): Promise<number> {
  // 恢复会话消息与持久化事件，并返回断线补发所需的最后事件号。
  try {
    const history = await api.sessions.getMessages(sessionId)
    const messages = history.messages || []
    const persistedEvents = history.events || []

    events.value = messages.map((row: any) => ({
      type: row.role === 'user' ? 'user' : 'agent',
      text: row.content || '',
      file: row.attachments?.length ? { filename: '已上传附件' } : undefined,
    }))

    let lastEventId = 0
    persistedEvents.forEach((row: any) => {
      lastEventId = Math.max(lastEventId, Number(row.event_id) || 0)
      handleWsEvent({
        event: row.event,
        event_id: row.event_id,
        task_id: row.task_id,
        ...(row.payload || {}),
      } as WsServerEvent)
    })
    scrollToBottom(true)
    return lastEventId
  } catch (err: any) {
    message.error(err.message || '恢复会话记录失败')
    return 0
  }
}

function handleWsEvent(ev: WsServerEvent) {
  switch (ev.event) {
    case 'thought': {
      let last = events.value[events.value.length - 1]
      if (!last || last.type !== 'thought' || last.done) {
        events.value.push({ type: 'thought', text: ev.message || '', done: false })
      } else {
        last.text = (last.text || '') + (ev.message || '')
      }
      scrollToBottom()
      break
    }
    case 'tool_call': {
      events.value.push({
        type: 'tool',
        tool: ev.tool,
        args: ev.arguments,
        status: 'pending',
      })
      scrollToBottom()
      break
    }
    case 'tool_result': {
      const target = [...events.value].reverse().find(
        (x) => x.type === 'tool' && x.tool === ev.tool
      )
      if (target) {
        target.result = ev.result
        target.status = ev.ok ? 'ok' : 'fail'
      }
      scrollToBottom()
      break
    }
    case 'confirm': {
      events.value.push({
        type: 'confirm',
        card: ev.card,
        isAcked: false,
      })
      scrollToBottom()
      break
    }
    case 'progress': {
      if (activeTask.value) {
        activeTask.value.progress = ev.progress
      }
      if (dispatchLogs.value.length > 8) dispatchLogs.value.pop()
      dispatchLogs.value.unshift({
        time: new Date().toTimeString().slice(0, 8),
        kind: 'TICK',
        msg: `${ev.task_id?.substring(0, 6)} 进度 ${ev.progress?.percent || 0}%`,
      })
      break
    }
    case 'report': {
      activeTask.value = null
      events.value.push({
        type: 'report',
        reportId: ev.report_id,
      })
      scrollToBottom()
      break
    }
    case 'error': {
      events.value.push({
        type: 'error',
        message: ev.message || '执行遇到错误',
      })
      isGenerating.value = false
      scrollToBottom()
      break
    }
  }
}

function handleUserSend(text: string, file?: any) {
  events.value.push({
    type: 'user',
    text,
    file,
  })
  isGenerating.value = true
  scrollToBottom(true)

  if (agentWs) {
    agentWs.sendUserMessage(text, file ? [file.id] : [])
  }
}

function sendPredefined(prompt: string) {
  handleUserSend(prompt)
}

async function handleConfirmAck(item: StreamItem, confirmed: boolean, patch?: Partial<TaskSpec>) {
  // 确认卡经 REST 真正创建任务，WebSocket 仅同步对话控制事件。
  if (item.submitting || item.isAcked) return

  if (!confirmed) {
    item.isAcked = true
    item.ackResult = false
    agentWs?.sendConfirmAck(false)
    return
  }

  const spec: TaskSpec = {
    ...(item.card as TaskSpec),
    ...(patch || {}),
    session_id: currentSessionId.value,
  }
  item.submitting = true
  try {
    const task = await api.tasks.create(spec)
    item.card = spec
    item.isAcked = true
    item.ackResult = true
    activeTask.value = task
    startTaskPolling(task.id)
    agentWs?.sendConfirmAck(true, spec)
    isGenerating.value = false
    message.success('任务已入队，将在当前会话持续同步状态')
  } catch (err: any) {
    events.value.push({ type: 'error', message: err.message || '任务入队失败' })
    scrollToBottom()
  } finally {
    item.submitting = false
  }
}

function stopTaskPolling() {
  // 停止当前会话任务的状态轮询，避免切换会话后继续更新旧任务。
  if (taskPollingTimer !== null) {
    window.clearInterval(taskPollingTimer)
    taskPollingTimer = null
  }
}

function startTaskPolling(taskId: string) {
  // 长任务通过 Worker 执行，前端轮询任务接口以获取持久化进度。
  stopTaskPolling()
  void refreshActiveTask(taskId)
  taskPollingTimer = window.setInterval(() => {
    void refreshActiveTask(taskId)
  }, 3000)
}

async function refreshActiveTask(taskId: string) {
  // 到达终态时停止轮询并在对话流中补充报告或结果反馈。
  try {
    const task = await api.tasks.get(taskId)
    activeTask.value = task
    if (!['succeeded', 'failed', 'cancelled'].includes(task.status)) return

    stopTaskPolling()
    activeTask.value = null
    if (task.status === 'succeeded' && task.report_id) {
      events.value.push({ type: 'report', reportId: task.report_id })
    } else if (task.status === 'cancelled') {
      events.value.push({ type: 'thought', text: '任务已取消。', done: true })
    } else {
      events.value.push({ type: 'error', message: task.progress?.message || '任务执行失败' })
    }
    scrollToBottom()
  } catch (err: any) {
    stopTaskPolling()
    message.error(err.message || '同步任务状态失败')
  }
}

function handleInterpretReport(reportId: string) {
  handleUserSend(`请深入解读评测报告 #${reportId} 的关键退化指标并给出优化建议`)
}

async function handleCancelActiveTask(taskId: string) {
  try {
    await api.tasks.cancel(taskId)
    message.success('已发送任务取消指令')
    activeTask.value = null
    stopTaskPolling()
  } catch (err: any) {
    message.error(err.message || '取消失败')
  }
}

function formatRelativeTime(dateStr?: string) {
  if (!dateStr) return '刚刚'
  const diff = Date.now() - new Date(dateStr).getTime()
  const mins = Math.floor(diff / 60000)
  if (mins < 1) return '刚刚'
  if (mins < 60) return `${mins} 分钟前`
  return `${Math.floor(mins / 60)} 小时前`
}

onMounted(async () => {
  await loadSessions()
  if (currentSessionId.value) {
    await selectSession(currentSessionId.value)
  }
})

onBeforeUnmount(() => {
  if (agentWs) {
    agentWs.close()
  }
  stopTaskPolling()
})
</script>

<style scoped>
.agent-layout {
  height: calc(100vh - var(--topbar-h) - 20px);
}
</style>
