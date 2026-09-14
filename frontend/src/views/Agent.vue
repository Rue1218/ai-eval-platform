<template>
  <div class="agent-layout" :class="{ 'no-list': isListCollapsed }">
    <!-- 左侧会话列表轨 (264px) -->
    <aside class="session-list" data-od-id="session-list">
      <div class="session-list-head">
        <div class="session-list-top-row">
          <button class="btn btn-secondary session-create-btn" @click="handleCreateSession">
            + 新建会话
          </button>
          <!-- 对话状态筛选下拉菜单 -->
          <n-dropdown
            trigger="click"
            :options="sessionStatusFilterOptions"
            @select="handleSelectSessionStatusFilter"
          >
            <button
              class="session-filter-btn"
              type="button"
              :class="{ active: sessionStatusFilter !== 'all' }"
              :title="`会话状态筛选：当前为 ${currentSessionStatusFilterLabel}`"
            >
              <i v-if="sessionStatusFilter !== 'all'" class="nav-dot" :class="sessionStatusFilter"></i>
              <svg v-else width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                <polygon points="22 3 2 3 10 12.46 10 19 14 21 14 12.46 22 3"></polygon>
              </svg>
              <span class="filter-label">{{ currentSessionStatusFilterLabel }}</span>
              <svg class="chevron-icon" width="9" height="9" viewBox="0 0 12 12" fill="none" stroke="currentColor" stroke-width="1.5">
                <path d="M3 4.5l3 3 3-3" stroke-linecap="round" stroke-linejoin="round" />
              </svg>
            </button>
          </n-dropdown>
          <button
            class="session-drawer-close-btn mobile-only"
            title="关闭会话列表"
            @click="isListCollapsed = true"
          >
            ✕
          </button>
        </div>
        <div v-if="deletableSessionCount" class="session-batch-toolbar">
          <label class="session-select-all">
            <input
              type="checkbox"
              :checked="allDeletableSessionsSelected"
              @change="handleSelectAllChange"
            />
            <span>{{ selectedSessionIds.length ? `已选 ${selectedSessionIds.length} 个` : '选择会话' }}</span>
          </label>
          <button
            v-if="selectedSessionIds.length"
            class="session-batch-delete"
            type="button"
            @click="handleBatchDeleteSessions"
          >
            删除选中
          </button>
        </div>
      </div>

      <div class="session-items">
        <div
          v-for="s in filteredSessions"
          :key="s.id"
          class="session-item"
          :class="{ active: currentSessionId === s.id }"
          @click="selectSession(s.id)"
        >
          <div class="session-title">
            <input
              v-if="s.can_delete"
              class="session-select"
              type="checkbox"
              :checked="selectedSessionIds.includes(s.id)"
              :aria-label="`选择会话：${displaySessionTitle(s)}`"
              @click.stop
              @change="toggleSessionSelected(s.id)"
            />
            <span class="session-title-text">{{ displaySessionTitle(s) }}</span>
            <span v-if="s.visibility === 'team'" class="session-team-badge">团队</span>
            <span
              v-if="s.workspace_id"
              class="session-ws-badge"
              :title="s.workspace_name ? '绑定工作区：' + s.workspace_name : '绑定工作区'"
              >{{ s.workspace_name || '工作区' }}</span
            >
            <div class="session-meta-right">
              <!-- D5 会话状态点多态：常驻显示 ready(就绪) / running(进行中) / succeeded(成功) / failed(失败) / offline(断线) -->
              <i class="nav-dot" :class="sessionDotClass(s)" :title="sessionDotTooltip(s)"></i>
              <button
                v-if="s.can_delete"
                class="session-del"
                title="软删除会话"
                @click.stop="handleDeleteSession(s.id)"
              >
                <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round">
                  <path d="M3 6h18M8 6V4h8v2M19 6l-1 14H6L5 6" />
                </svg>
              </button>
            </div>
          </div>
          <div class="row-between" style="margin-top: 2px">
            <span class="session-time">{{ formatRelativeTime(s.created_at) }}</span>
          </div>
        </div>
        <div v-if="filteredSessions.length === 0" class="session-empty-filter">
          <span>暂无匹配状态的会话</span>
        </div>
      </div>
    </aside>

    <!-- 中间对话主区 -->
    <section class="chat-main">
      <!-- 头部 -->
      <div class="chat-head" data-od-id="chat-head">
        <button
          class="composer-btn"
          title="折叠/展开会话列表"
          style="width: 30px; height: 30px; flex-basis: 30px; border-radius: 8px"
          @click="toggleSessionList"
        >
          <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round">
            <path d="M4 6h16M4 12h10M4 18h16" />
          </svg>
        </button>
        <span class="chat-head-title">{{ displaySessionTitle(currentSession) }}</span>
        <span v-if="currentSession?.visibility === 'team'" class="chat-team-badge">团队共享</span>
        <span
          v-if="currentSession?.workspace_id && currentSession?.workspace_name"
          class="chat-ws-chip"
          :title="'会话绑定工作区：' + currentSession.workspace_name + '（模型的文件读写与 bash 均在此进行，创建后不可更改）'"
          >工作区 · {{ currentSession.workspace_name }}</span
        >
        <span class="grow"></span>
        <button
          v-if="currentSession?.can_manage"
          class="btn btn-sm btn-ghost"
          :title="currentSession.visibility === 'team' ? '收回团队共享' : '向团队共享此会话'"
          @click="toggleSessionSharing"
        >
          {{ currentSession.visibility === 'team' ? '仅自己' : '共享团队' }}
        </button>
      </div>

      <AgentWorkspace :session-id="currentSessionId" :session="currentSession" :store="loopStore" :create-session="createLoopSession" />
    </section>

    <!-- 移动端侧边栏抽屉遮罩层 (点击遮罩收起所有侧边栏) -->
    <div
      v-if="isMobileDrawerActive"
      class="agent-mobile-backdrop"
      @click="closeMobileDrawers"
    ></div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, onBeforeUnmount, watch, h } from 'vue'
import { useRoute } from 'vue-router'
import { useMessage, useDialog, NDropdown, type DropdownOption } from 'naive-ui'
import { api } from '../api/http'
import type { AgentSession } from '../api/types'
import { useAuthStore } from '../stores/auth'
import AgentWorkspace from '../components/agent/loop/AgentWorkspace.vue'
import { createLoopStore } from '../agent/loop/store'
import { filterSessionsByStatus, loopSessionDot, loopSessionTooltip, sessionStatusFilterLabel } from '../agent/sessionList'

const message = useMessage()
const dialog = useDialog()
const route = useRoute()
const authStore = useAuthStore()

const isListCollapsed = ref(typeof window !== 'undefined' && window.innerWidth <= 768)

/** 移动端抽屉遮罩层显隐状态：在窄屏下有任一侧边栏抽屉展开时激活 */
const isMobileDrawerActive = computed(() => {
  if (typeof window === 'undefined') return false
  const isMobile = window.innerWidth <= 768
  return isMobile && !isListCollapsed.value
})

function closeMobileDrawers() {
  isListCollapsed.value = true
}

function toggleSessionList() {
  isListCollapsed.value = !isListCollapsed.value
}


const sessions = ref<AgentSession[]>([])
/** 会话状态筛选当前选项：all | running | ready | succeeded | failed */
const sessionStatusFilter = ref<string>('all')

/** 会话状态筛选下拉菜单配置项 */
const sessionStatusFilterOptions = computed<DropdownOption[]>(() => [
  { label: '全部状态', key: 'all' },
  {
    label: '进行中 (running)',
    key: 'running',
    icon: () => h('i', { class: 'nav-dot running', style: { display: 'inline-block', width: '7px', height: '7px', borderRadius: '50%' } }),
  },
  {
    label: '就绪待命 (ready)',
    key: 'ready',
    icon: () => h('i', { class: 'nav-dot ready', style: { display: 'inline-block', width: '7px', height: '7px', borderRadius: '50%' } }),
  },
  {
    label: '评测成功 (succeeded)',
    key: 'succeeded',
    icon: () => h('i', { class: 'nav-dot succeeded', style: { display: 'inline-block', width: '7px', height: '7px', borderRadius: '50%' } }),
  },
  {
    label: '评测失败 (failed)',
    key: 'failed',
    icon: () => h('i', { class: 'nav-dot failed', style: { display: 'inline-block', width: '7px', height: '7px', borderRadius: '50%' } }),
  },
])

/** 当前选中的状态筛选展示文案 */
const currentSessionStatusFilterLabel = computed(() => sessionStatusFilterLabel(sessionStatusFilter.value))

/** 切换会话状态筛选 */
function handleSelectSessionStatusFilter(key: string) {
  sessionStatusFilter.value = key
}

/** 按状态筛选后的会话列表 */
const filteredSessions = computed(() => filterSessionsByStatus(sessions.value, sessionStatusFilter.value, sessionDotClass))

const selectedSessionIds = ref<string[]>([])
const deletingSessionIds = new Set<string>()
const currentSessionId = ref<string>('')
// 未绑定服务端会话时保持草稿态，不得用列表首项冒充当前会话。
const currentSession = computed(() => sessions.value.find(s => s.id === currentSessionId.value) || null)
const loopStore = createLoopStore(id => removeInaccessibleSession(id))
watch(() => authStore.user?.id, (id, previous) => { if (previous && id !== previous) loopStore.close() })
watch(() => Object.values(loopStore.sessions).map(s => [s.sessionId, s.title]), () => {
  for (const value of Object.values(loopStore.sessions)) { const session = sessions.value.find(s => s.id === value.sessionId); if (session && value.title) session.title = value.title }
})

function displaySessionTitle(session?: AgentSession | null): string {
  if (!session) return '新会话'
  const title = (session.title || '').trim()
  if (title && title !== '新会话') return title
  const loopState = loopStore.sessions[session.id]
  if (loopState?.title && loopState.title !== '新会话') {
    return loopState.title
  }
  return '新会话'
}

/** 创建时固化 v2、工作区与权限档位，后续只使用独立 transport。 */
async function createLoopSession(
  workspaceId?: string, preparedTicket?: Promise<string>, permissionTier?: string, initialTitle?: string
): Promise<string> {
  if (currentSessionId.value) return currentSessionId.value
  const title = initialTitle || '新会话'
  const session = await api.sessions.create(title, {
    workspaceId,
    permissionTier: (permissionTier as any) || undefined,
  })
  sessions.value.unshift(session)
  // 在切换 prop 触发子组件 watch 前先建立连接，确保首次连接实际复用并行领取的短票。
  loopStore.open(session.id, preparedTicket)
  currentSessionId.value = session.id
  return session.id
}
const deletableSessionCount = computed(() => filteredSessions.value.filter((session) => session.can_delete).length)
const allDeletableSessionsSelected = computed(() => {
  const deletableIds = filteredSessions.value.filter((session) => session.can_delete).map((session) => session.id)
  return deletableIds.length > 0 && deletableIds.every((id) => selectedSessionIds.value.includes(id))
})
/** 会话列表仅展示 AgentLoop，会话和 Worker 状态均来自 v2 投影。 */
function sessionDotClass(s: AgentSession): string {
  return loopSessionDot(loopStore.sessions[s.id], s.active_task?.status)
}

/** 会话状态提示语与 v2 连接状态保持一致。 */
function sessionDotTooltip(s: AgentSession): string {
  return loopSessionTooltip(loopStore.sessions[s.id])
}

// 页面只保留后台空闲连接清理计时器，不改变活动 WS 的收发频率。
const idleTimer = window.setInterval(() => loopStore.releaseIdle(), 15000)

/** 切回本地草稿，已建会话的后台运行与草稿由 store 保留。 */
function resetToDraftSession() {
  currentSessionId.value = ''
}

async function loadSessions() {
  try {
    const list = await api.sessions.list()
    // 历史 legacy 会话保留在服务端审计数据中，但不再进入唯一的 AgentLoop 工作台。
    sessions.value = (list || []).filter((session) => session.engine_version === 'agent_loop_v2')
  } catch {
    sessions.value = []
  }
}

/** 选中可见的 v2 会话并建立或复用连接。 */
async function selectSession(sid: string) {
  if (deletingSessionIds.has(sid)) return
  const selected = sessions.value.find((session) => session.id === sid)
  // 列表已过滤历史会话；双重守卫确保任何残留点击也不会落到旧 WS transport。
  if (!selected || selected.engine_version !== 'agent_loop_v2') return
  // 移动端会话列表是覆盖式抽屉，选中会话后自动收起让出对话区。
  if (typeof window !== 'undefined' && window.innerWidth <= 768) isListCollapsed.value = true
  currentSessionId.value = sid
  loopStore.open(sid)
}

/** 打开一个新的本地草稿；服务端会话在用户真正发送消息时才创建。 */
function handleCreateSession() {
  sessionStatusFilter.value = 'all'
  resetToDraftSession()
  // 清除未持久化 AgentLoop 草稿及其对象 URL；已建会话的连接和草稿保持不动。
  loopStore.remove('draft')
}

/** 仅 owner 可切换会话私有/团队共享范围，服务端为最终权限裁决。 */
async function toggleSessionSharing() {
  const session = currentSession.value
  if (!session?.can_manage) return
  const visibility = session.visibility === 'team' ? 'private' : 'team'
  try {
    const updated = await api.sessions.updateSharing(session.id, visibility)
    const target = sessions.value.find((item) => item.id === session.id)
    if (target) Object.assign(target, updated)
    message.success(visibility === 'team' ? '已向团队共享此会话' : '已收回团队共享')
  } catch (err: any) {
    message.error(err?.message || '更新会话共享设置失败')
  }
}

/** 软删除空闲会话；成功后关闭旧连接并切换到下一个可见会话。 */
function handleDeleteSession(sid: string) {
  const target = sessions.value.find((item) => item.id === sid)
  if (!target?.can_delete) {
    message.error('仅会话创建者可以删除会话')
    return
  }
  dialog.warning({
    title: '删除会话？',
    content: '对话将在列表中隐藏，但消息、任务和报告会保留用于审计回溯。正在生成或执行中的任务需先处理。',
    positiveText: '删除会话',
    negativeText: '保留',
    positiveButtonProps: { type: 'error' },
    onPositiveClick: async () => {
      try {
        await api.sessions.remove(sid)
        removeInaccessibleSession(sid)
        message.success('会话已删除，对话与任务记录仍保留审计')
      } catch (err: any) {
        message.error(err?.message || '删除会话失败')
      }
    },
  })
}

/** 批量软删除 owner 会话；每个请求仍由服务端独立校验活动任务与权限。 */
function handleBatchDeleteSessions() {
  const ids = selectedSessionIds.value.filter((sid) => sessions.value.some((session) => session.id === sid && session.can_delete))
  if (!ids.length) {
    selectedSessionIds.value = []
    return
  }
  dialog.warning({
    title: '批量删除会话？',
    content: `将删除选中的 ${ids.length} 个会话。消息、任务和报告仍会保留用于审计回溯；包含生成中或执行中任务的会话会单独失败。`,
    positiveText: '删除选中',
    negativeText: '保留',
    positiveButtonProps: { type: 'error' },
    onPositiveClick: async () => {
      ids.forEach((sid) => deletingSessionIds.add(sid))
      const results = await Promise.allSettled(ids.map((sid) => api.sessions.remove(sid)))
      const succeeded = ids.filter((_sid, index) => results[index]?.status === 'fulfilled')
      const failed = results.filter((result) => result.status === 'rejected')
      ids.forEach((sid) => deletingSessionIds.delete(sid))
      removeInaccessibleSessions(succeeded)
      if (!failed.length) {
        message.success(`已删除 ${succeeded.length} 个会话，对话与任务记录仍保留审计`)
        return
      }
      const firstFailure = failed[0]
      const reason = firstFailure?.status === 'rejected' && firstFailure.reason?.message
        ? `（${firstFailure.reason.message}）`
        : ''
      if (succeeded.length) {
        message.warning(`已删除 ${succeeded.length} 个会话，${failed.length} 个未删除${reason}`)
      } else {
        message.error(`批量删除失败：${failed.length} 个会话均未删除${reason}`)
      }
    },
  })
}


/** 列表展示会话创建时间的相对值。 */
function formatRelativeTime(dateStr?: string) {
  if (!dateStr) return '刚刚'
  const diff = Date.now() - new Date(dateStr).getTime()
  const mins = Math.floor(diff / 60000)
  if (mins < 1) return '刚刚'
  if (mins < 60) return `${mins} 分钟前`
  return `${Math.floor(mins / 60)} 小时前`
}

/** 服务端以 4404 收回会话后同步移除本地缓存，避免列表留下无法重连的幽灵项。 */
function removeInaccessibleSession(sid: string, navigate = true) {
  if (loopStore.sessions[sid] || loopStore.drafts[sid]) loopStore.remove(sid)
  const index = sessions.value.findIndex((session) => session.id === sid)
  const wasCurrent = currentSessionId.value === sid
  selectedSessionIds.value = selectedSessionIds.value.filter((id) => id !== sid)
  if (index < 0) return

  sessions.value.splice(index, 1)
  if (!wasCurrent || !navigate) return
  const next = sessions.value[index] || sessions.value[index - 1]
  if (next) {
    void selectSession(next.id)
  } else {
    void handleCreateSession()
  }
}

/** 批量清理已删除会话后只导航一次，避免依次跳转到同批次的已删除会话。 */
function removeInaccessibleSessions(sids: string[]) {
  const wasCurrent = sids.includes(currentSessionId.value)
  sids.forEach((sid) => removeInaccessibleSession(sid, false))
  if (!wasCurrent) return
  const next = sessions.value[0]
  if (next) {
    void selectSession(next.id)
  } else {
    void handleCreateSession()
  }
}

/** 切换单个 owner 会话的批量选择状态。 */
function toggleSessionSelected(sid: string) {
  if (selectedSessionIds.value.includes(sid)) {
    selectedSessionIds.value = selectedSessionIds.value.filter((id) => id !== sid)
  } else {
    selectedSessionIds.value = [...selectedSessionIds.value, sid]
  }
}

/** 全选或清空当前列表中可由本人删除的会话。 */
function handleSelectAllChange(event: Event) {
  const checked = (event.target as HTMLInputElement).checked
  selectedSessionIds.value = checked
    ? filteredSessions.value.filter((session) => session.can_delete).map((session) => session.id)
    : []
}

onMounted(async () => {
  await loadSessions()
  // 异步初始化不能覆盖用户已经选中的 AgentLoop 会话。
  if (!currentSessionId.value) resetToDraftSession()
  // 报告直达仅预填 AgentLoop 草稿，实际发送统一经过 v2 composer。
  const interpretId = (route.query.interpret || route.query.report_id) as string | undefined
  if (interpretId) {
    handleInterpretReport(interpretId)
  }
})

onBeforeUnmount(() => {
  loopStore.close()
  window.clearInterval(idleTimer)
})

/** 报告解读入口：AgentLoop 只写入草稿，避免 v2 会话被旧 WebSocket 入口误发。 */
function handleInterpretReport(reportId: string) {
  const draft = loopStore.draft(currentSessionId.value || 'draft')
  draft.content = `请解读报告 #${reportId}`
  message.info('已将报告解读请求填入 AgentLoop 输入框')
}
</script>

<style scoped>
.agent-layout {
  /* 由 flush 内容区提供可用高度，避免紧凑输入栏落到视口外。 */
  height: 100%;
  min-height: 0;
}

/* 团队共享会话的轻量状态标识，避免把私有/共享混在同一种列表视觉中。 */
.session-team-badge,
.chat-team-badge {
  display: inline-flex;
  align-items: center;
  border-radius: 999px;
  color: var(--c-agent);
  background: var(--t-agent);
  font-size: 10px;
  font-weight: 600;
  line-height: 1;
  padding: 3px 6px;
  white-space: nowrap;
}

.chat-team-badge {
  font-size: 11px;
}

/* F3/G5：会话绑定工作区标识（列表 badge / 顶栏 chip / 草稿选择面板）。 */
.session-ws-badge {
  display: inline-flex;
  align-items: center;
  max-width: 120px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  border-radius: 999px;
  color: var(--c-success, #188038);
  background: var(--t-success, rgba(24, 128, 56, 0.12));
  font-size: 10px;
  font-weight: 600;
  line-height: 1;
  padding: 3px 6px;
}

.chat-ws-chip {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  border-radius: 999px;
  border: 1px solid var(--border-subtle);
  background: var(--bg-elevated);
  color: var(--text-secondary);
  font-size: 11px;
  font-weight: 500;
  line-height: 1;
  padding: 4px 8px;
  white-space: nowrap;
}

.session-meta-right .nav-dot {
  position: static;
  margin: 0;
  display: inline-block;
  flex: 0 0 7px;
  width: 7px;
  height: 7px;
  min-width: 7px;
  min-height: 7px;
  border-radius: 50%;
}

/* 移动端：顶栏 58px 且无外边距，对话区高度改用 dvh；头部操作收紧与安全区适配 */
@media (max-width: 768px) {
  .agent-layout {
    height: calc(100dvh - 58px);
  }
  .chat-head-title {
    max-width: calc(100vw - 200px);
  }
  .session-item {
    min-height: 42px;
    padding: 8px 10px;
  }
  .session-title {
    font-size: 13.5px;
  }
}
</style>
