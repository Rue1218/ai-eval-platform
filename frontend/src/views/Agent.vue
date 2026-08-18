<template>
  <div class="agent-layout">
    <!-- 左侧会话轨 -->
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
        <div v-if="!wsConnected" class="offline-tag mono">
          断线重连中...
        </div>
      </div>

      <!-- 消息流滚动区 -->
      <div ref="chatScrollRef" class="chat-scroll">
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

let agentWs: AgentWebSocket | null = null

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
  reportId?: string
  message?: string
  file?: any
}

const events = ref<StreamItem[]>([])

const currentSession = computed(() => {
  return sessions.value.find((s) => s.id === currentSessionId.value)
})

function formatRelativeTime(dateStr?: string) {
  if (!dateStr) return '刚刚'
  return '刚刚'
}

function scrollToBottom() {
  nextTick(() => {
    if (chatScrollRef.value) {
      chatScrollRef.value.scrollTop = chatScrollRef.value.scrollHeight
    }
  })
}

async function loadSessions() {
  try {
    const list = await api.sessions.list()
    if (list && list.length) {
      sessions.value = list
      if (!currentSessionId.value) currentSessionId.value = list[0].id
    }
  } catch (err) {
    console.error('Failed to load sessions:', err)
  }
}

async function loadAgentSettings() {
  try {
    const settings = await api.admin.getSettings()
    if (settings.agent_profile_id) {
      const profiles = await api.profiles.list()
      const p = profiles.find((x) => x.id === settings.agent_profile_id)
      if (p) agentProfileName.value = `Agent · ${p.name}`
    }
  } catch (err) {
    console.error('Failed to load agent settings:', err)
  }
}

function selectSession(id: string) {
  currentSessionId.value = id
  events.value = []
  activeTask.value = null
  initWebSocket()
}

async function handleCreateSession() {
  try {
    const newS = await api.sessions.create('新评测对话')
    sessions.value.unshift(newS)
    selectSession(newS.id)
  } catch (err: any) {
    message.error(err.message || '创建会话失败')
  }
}

function sendPredefined(prompt: string) {
  handleUserSend(prompt)
}

function handleUserSend(text: string, fileId?: string) {
  events.value.push({
    type: 'user',
    text,
    file: fileId ? { filename: '需求文件.pdf' } : undefined,
  })
  scrollToBottom()

  isGenerating.value = true

  if (agentWs && wsConnected.value) {
    agentWs.sendUserMessage(text, fileId ? [fileId] : [])
  } else {
    // Mock Agent 交互流程
    simulateMockAgentReply(text)
  }
}

function simulateMockAgentReply(userText: string) {
  setTimeout(() => {
    // 思考卡
    events.value.push({
      type: 'thought',
      text: `正在分析用户请求：「${userText}」，准备检索已有协议档与数据集信息...`,
      done: false,
    })
    scrollToBottom()

    setTimeout(() => {
      // 工具调用
      events.value.push({
        type: 'tool',
        tool: 'list_profiles',
        args: { usage: 'target' },
        result: { count: 2, profiles: ['gpt-test', 'claude-x'] },
        status: 'ok',
      })
      scrollToBottom()

      setTimeout(() => {
        // 确认卡
        const isRag = userText.includes('RAG') || userText.includes('知识库')
        const isCase = userText.includes('用例')
        const kind = isRag ? 'rag' : isCase ? 'testcase' : 'benchmark'

        events.value.push({
          type: 'confirm',
          card: {
            kind,
            profile_ids: ['p-gpt', 'p-claude'],
            dataset_id: 'ds-smoke',
            kb_id: 'kb-default',
            gold_qa_id: 'gq-1',
            rag_mode: ['hybrid'],
            case_source: { text: userText },
            with_stress: userText.includes('压测'),
          },
        })
        isGenerating.value = false
        scrollToBottom()
      }, 700)
    }, 600)
  }, 400)
}

async function handleConfirmAck(item: StreamItem, ok: boolean, patch?: TaskSpec) {
  item.isAcked = true
  item.ackResult = ok

  if (agentWs && wsConnected.value) {
    agentWs.sendConfirmAck(ok, patch)
  }

  if (ok) {
    try {
      const task = await api.tasks.create(patch || item.card!)
      activeTask.value = task
      message.success('评测任务已入队')

      // 模拟进度更新
      simulateTaskProgress(task)
    } catch (err: any) {
      message.error(err.message || '下单失败')
    }
  } else {
    message.info('已取消下单')
  }
}

function simulateTaskProgress(task: Task) {
  task.status = 'running'
  task.progress = { done: 10, total: 100, message: '正在启动评测容器与被测连接...' }
  activeTask.value = { ...task }

  let current = 10
  const interval = setInterval(() => {
    current += 30
    if (current >= 100) {
      clearInterval(interval)
      task.status = 'succeeded'
      task.progress = { done: 100, total: 100, message: '评测完成' }
      activeTask.value = null

      events.value.push({
        type: 'report',
        reportId: 'r-bm-1',
      })
      scrollToBottom()
    } else {
      task.progress = { done: current, total: 100, message: `正在调用被测模型 sample ${current}/100...` }
      activeTask.value = { ...task }
    }
  }, 1200)
}

async function handleCancelActiveTask(taskId: string) {
  if (agentWs && wsConnected.value) {
    agentWs.sendCancelTask(taskId)
  }
  await api.tasks.cancel(taskId)
  if (activeTask.value && activeTask.value.id === taskId) {
    activeTask.value.status = 'cancelled'
    activeTask.value = null
  }
  message.success('任务已取消')
}

function handleInterpretReport(reportId: string) {
  handleUserSend(`请对评测报告 #${reportId} 的指标得分进行详细解读，并分析潜在的退化原因与改进建议。`)
}

function handleWsEvent(event: WsServerEvent) {
  isGenerating.value = false

  if (event.event === 'thought') {
    events.value.push({ type: 'thought', text: event.message, done: true })
  } else if (event.event === 'tool_call') {
    events.value.push({ type: 'tool', tool: event.tool, args: event.arguments, status: 'pending' })
  } else if (event.event === 'tool_result') {
    const lastTool = [...events.value].reverse().find((x) => x.type === 'tool' && x.status === 'pending')
    if (lastTool) {
      lastTool.result = event.result
      lastTool.status = event.ok ? 'ok' : 'fail'
    }
  } else if (event.event === 'confirm') {
    events.value.push({ type: 'confirm', card: event.card })
  } else if (event.event === 'progress') {
    if (activeTask.value) {
      activeTask.value.progress = event.progress
    }
  } else if (event.event === 'report') {
    events.value.push({ type: 'report', reportId: event.report_id })
    activeTask.value = null
  } else if (event.event === 'error') {
    events.value.push({ type: 'error', message: event.message })
  }

  scrollToBottom()
}

function initWebSocket() {
  if (agentWs) agentWs.close()

  agentWs = new AgentWebSocket(currentSessionId.value)
  agentWs.onStatus((connected) => {
    wsConnected.value = connected
  })
  agentWs.onEvent(handleWsEvent)
  agentWs.connect()
}

onMounted(() => {
  loadSessions()
  loadAgentSettings()
  initWebSocket()
})

onBeforeUnmount(() => {
  if (agentWs) agentWs.close()
})
</script>

<style scoped>
.agent-layout {
  display: grid;
  grid-template-columns: 264px 1fr;
  height: 100%;
  min-height: 0;
}

.session-list {
  border-right: 1px solid var(--border-subtle);
  display: flex;
  flex-direction: column;
  min-height: 0;
  background: var(--bg-main);
}
.session-list-head {
  padding: 14px;
}
.session-items {
  flex: 1;
  overflow-y: auto;
  padding: 0 10px 14px;
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.session-item {
  padding: 10px 12px;
  border-radius: 12px;
  cursor: pointer;
  transition: all 0.13s ease;
  border: 1px solid transparent;
}
.session-item:hover {
  background: var(--bg-elevated);
}
.session-item.active {
  background: var(--t-agent);
}
.session-item.active .session-title {
  color: var(--c-agent);
  font-weight: 600;
}
.session-item.active .session-time {
  color: var(--c-agent);
  opacity: 0.7;
}
.session-title {
  font-size: 13px;
  font-weight: 500;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.session-time {
  font-size: 11px;
  color: var(--text-tertiary);
  margin-top: 3px;
}

.chat-main {
  display: flex;
  flex-direction: column;
  min-width: 0;
  min-height: 0;
  background: var(--bg-main);
}
.chat-head {
  height: 56px;
  flex: 0 0 56px;
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 0 20px;
  border-bottom: 1px solid var(--border-subtle);
}
.chat-head-title {
  font-size: 15px;
  font-weight: 600;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.chat-head-model {
  font-size: 11px;
  color: var(--text-tertiary);
  border: 1px solid var(--border-subtle);
  border-radius: 999px;
  padding: 2px 10px;
}
.gen-pill {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-size: 11px;
  font-family: var(--font-mono);
  color: var(--c-agent);
  background: var(--t-agent);
  border-radius: 999px;
  padding: 2px 10px;
}
.gen-pill .bdot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: currentColor;
  animation: dot-breathe 1.2s infinite;
}
.offline-tag {
  font-size: 11px;
  color: var(--accent-warning);
}

.chat-scroll {
  flex: 1;
  overflow-y: auto;
  min-height: 0;
}
.chat-col {
  max-width: 760px;
  margin: 0 auto;
  padding: 24px 20px;
  display: flex;
  flex-direction: column;
  gap: 16px;
  min-height: 100%;
}

.welcome {
  margin: auto;
  width: 100%;
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  padding: 20px 0;
}
.welcome-eyebrow {
  font-family: var(--font-mono);
  font-size: 11px;
  letter-spacing: 0.14em;
  text-transform: uppercase;
  color: var(--text-tertiary);
}
.welcome-title {
  margin-top: 10px;
  font-family: var(--font-display);
  font-size: 28px;
  font-weight: 700;
  letter-spacing: -0.01em;
  line-height: 1.35;
}
.welcome-sub {
  margin-top: 10px;
  font-size: 13.5px;
  color: var(--text-secondary);
  max-width: 60ch;
  line-height: 1.6;
}
.welcome-caps {
  margin-top: 20px;
  width: 100%;
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 12px;
}
.cap {
  display: flex;
  align-items: flex-start;
  gap: 12px;
  border: 1px solid var(--border-subtle);
  border-radius: 14px;
  background: var(--bg-main);
  padding: 12px 14px;
  cursor: pointer;
  transition: all 0.15s ease;
}
.cap:hover {
  border-color: var(--accent-ai);
  background: var(--bg-elevated);
  transform: translateY(-1px);
}
.cap-ico {
  width: 32px;
  height: 32px;
  flex: 0 0 32px;
  border-radius: 8px;
  display: grid;
  place-items: center;
  background: var(--bg-elevated);
  border: 1px solid var(--border-subtle);
  color: var(--text-secondary);
}
.cap:hover .cap-ico {
  color: var(--accent-ai);
}
.cap-name {
  display: block;
  font-size: 13px;
  font-weight: 600;
}
.cap-desc {
  display: block;
  font-size: 12px;
  color: var(--text-tertiary);
  margin-top: 2px;
}

.msg-user {
  display: flex;
  flex-direction: column;
  align-items: flex-end;
  gap: 6px;
}
.bubble-user {
  background: var(--accent-ai);
  color: #fff;
  border-radius: 18px;
  border-bottom-right-radius: 4px;
  padding: 10px 16px;
  font-size: 14.5px;
  line-height: 1.6;
  max-width: 80%;
  animation: msg-in 0.26s cubic-bezier(0.2, 0.9, 0.3, 1);
}
.attach-chip {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  background: var(--bg-elevated);
  border: 1px solid var(--border-subtle);
  border-radius: 8px;
  padding: 3px 8px;
  font-size: 11px;
  color: var(--text-secondary);
}

.msg-agent {
  font-size: 15px;
  line-height: 1.8;
  color: var(--text-primary);
  max-width: 92%;
  animation: msg-in 0.26s cubic-bezier(0.2, 0.9, 0.3, 1);
}
</style>
