<template>
  <n-card title="Agent 会话" style="height: 100%">
    <div class="chat-box">
      <n-scrollbar ref="scrollRef" style="max-height: 60vh">
        <div v-for="(m, i) in events" :key="i" class="msg" :class="m.kind">
          <div v-if="m.kind === 'user'" class="bubble user">{{ m.text }}</div>
          <div v-else-if="m.kind === 'thought'" class="bubble thought">{{ m.text }}</div>
          <div v-else-if="m.kind === 'confirm'" class="bubble confirm">
            确认卡：kind={{ m.card?.kind }}
            <n-button size="tiny" type="primary" style="margin-left: 8px" @click="onAck(m)">确认下单</n-button>
          </div>
          <div v-else-if="m.kind === 'report'" class="bubble system">报告已生成：{{ m.report_id }}</div>
          <div v-else class="bubble system">{{ m.text }}</div>
        </div>
      </n-scrollbar>
      <n-input-group class="input-row">
        <n-input v-model:value="text" placeholder="描述你要执行的评测任务" @keyup.enter="send" />
        <n-button type="primary" :disabled="!connected" @click="send">发送</n-button>
      </n-input-group>
      <div class="status">{{ connected ? '已连接' : '未连接' }}</div>
    </div>
  </n-card>
</template>

<script setup lang="ts">
import { ref, onMounted, onBeforeUnmount } from 'vue'
import { useMessage } from 'naive-ui'
import http from '../api/http'

const message = useMessage()
const events = ref<any[]>([])
const text = ref('')
const connected = ref(false)
let ws: WebSocket | null = null
let sessionId: string | null = null

function wsUrl() {
  const proto = location.protocol === 'https:' ? 'wss' : 'ws'
  return `${proto}://${location.host}/ws/agent`
}

async function connect() {
  const { data } = await http.post('/api/auth/ws-ticket')
  const params = new URLSearchParams({ ticket: data.ticket })
  if (sessionId) params.set('session_id', sessionId)
  const socket = new WebSocket(`${wsUrl()}?${params.toString()}`)
  ws = socket

  socket.onopen = () => (connected.value = true)
  socket.onclose = () => (connected.value = false)
  socket.onmessage = (ev) => {
    const m = JSON.parse(ev.data)
    if (m.event === 'pong') return
    if (m.session_id) sessionId = m.session_id
    if (m.event === 'thought') events.value.push({ kind: 'thought', text: m.message })
    else if (m.event === 'confirm') events.value.push({ kind: 'confirm', card: m.card })
    else if (m.event === 'report') events.value.push({ kind: 'report', report_id: m.report_id })
    else if (m.event === 'error') events.value.push({ kind: 'system', text: m.message })
  }
}

function send() {
  if (!text.value.trim()) return
  events.value.push({ kind: 'user', text: text.value })
  ws?.send(JSON.stringify({ type: 'user_message', text: text.value }))
  text.value = ''
}

async function onAck(m: any) {
  try {
    await http.post('/api/tasks', {
      kind: m.card?.kind || 'benchmark',
      config: m.card || {},
      session_id: sessionId,
    })
    message.success('已下单')
    events.value.push({ kind: 'system', text: '任务已入队，前往「任务中心」查看' })
  } catch (e: any) {
    message.error(e.response?.data?.message || '下单失败')
  }
}

onMounted(connect)
onBeforeUnmount(() => ws && ws.close())
</script>

<style scoped>
.chat-box {
  display: flex;
  flex-direction: column;
  gap: 12px;
}
.msg {
  margin-bottom: 8px;
}
.msg.user {
  text-align: right;
}
.bubble {
  display: inline-block;
  max-width: 70%;
  padding: 8px 12px;
  border-radius: 8px;
  background: var(--bg-elevated);
}
.bubble.user {
  background: var(--accent-ai);
  color: #fff;
}
.bubble.thought {
  background: #fff7e6;
}
.bubble.confirm {
  background: var(--t-datasets);
}
.bubble.system {
  background: var(--bg-elevated);
  color: var(--text-tertiary);
}
.input-row {
  margin-top: 12px;
}
.status {
  margin-top: 6px;
  font-size: 12px;
  color: var(--text-tertiary);
}
</style>
