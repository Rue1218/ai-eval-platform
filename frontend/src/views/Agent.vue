<template>
  <div class="agent-layout" :class="{ 'with-rail': isRailOpen, 'no-list': isListCollapsed }">
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
        <span v-if="isGenerating" class="gen-pill">
          <i class="bdot"></i>
          <span>生成中</span>
          <span v-if="turnLatencyLabel" class="mono" style="opacity:.8">{{ turnLatencyLabel }}</span>
        </span>

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

      <AgentWorkspace v-if="isLoopView" :session-id="currentSessionId" :session="currentSession" :store="loopStore" :create-session="createLoopSession" />
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
import { ref, computed, reactive, onMounted, onBeforeUnmount, nextTick, watch, h } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useMessage, useDialog, NDropdown, type DropdownOption } from 'naive-ui'
import { api } from '../api/http'
import { AgentWebSocket } from '../api/ws'
import type {
  AgentPrefs,
  AgentSession,
  ClarifyAnswer,
  ClarifyPayload,
  Dataset,
  GoldQA,
  KnowledgeBase,
  Profile,
  SessionAuthor,
  Task,
  ToolApprovalPayload,
  WsServerEvent,
} from '../api/types'
import { useModeStore } from '../stores/mode'
import { useAuthStore } from '../stores/auth'
import { getModelLogoKey, getServiceLogoKey, type ProviderLogoKey } from '../utils/providerLogo'
import { formatLatency } from '../utils/format'
import type { ContextMeterData } from '../components/agent/ContextMeter.vue'
import AgentWorkspace from '../components/agent/loop/AgentWorkspace.vue'
import { createLoopStore } from '../agent/loop/store'
import { filterSessionsByStatus, legacySessionDot, legacySessionTooltip, loopSessionDot, loopSessionTooltip, sessionStatusFilterLabel } from '../agent/sessionList'
import { attachmentRejectionReason, createPreviewTracker } from '../agent/attachments'
import { getDefaultRunConfig, getDefaultStressConfig } from '../schemas/confirmCard'

const message = useMessage()
const dialog = useDialog()
const route = useRoute()
const router = useRouter()
const authStore = useAuthStore()
const textareaRef = ref<HTMLTextAreaElement | null>(null)

const isListCollapsed = ref(typeof window !== 'undefined' && window.innerWidth <= 768)
const isRailOpen = ref(false)

/** 移动端抽屉遮罩层显隐状态：在窄屏下有任一侧边栏抽屉展开时激活 */
const isMobileDrawerActive = computed(() => {
  if (typeof window === 'undefined') return false
  const isMobile = window.innerWidth <= 768
  return isMobile && (!isListCollapsed.value || isRailOpen.value)
})

function closeMobileDrawers() {
  isListCollapsed.value = true
  isRailOpen.value = false
}

function toggleSessionList() {
  isListCollapsed.value = !isListCollapsed.value
  if (!isListCollapsed.value && typeof window !== 'undefined' && window.innerWidth <= 768) {
    isRailOpen.value = false
  }
}


const isWsOnline = ref(true)
const isGenerating = ref(false)
const turnLatencyMs = ref(0)
const turnLatencyLabel = computed(() => formatLatency(turnLatencyMs.value) || '')
const currentAgentProfileId = ref<string>('')
const allProfiles = ref<Profile[]>([])
const activeAgentProfile = computed(() => {
  const activeId = currentAgentProfileId.value || allProfiles.value[0]?.id
  return allProfiles.value.find((item) => item.id === activeId) || null
})
const agentProfileLogoKey = computed<ProviderLogoKey>(() => {
  return activeAgentProfile.value ? getModelLogoKey(activeAgentProfile.value.model) : 'custom'
})
const agentDisplayModelName = computed(() => activeAgentProfile.value?.model || 'Agent')
const agentProfileDisplayName = computed(() => activeAgentProfile.value?.name || '')

// 上下文度量状态
const currentContextMeter = ref<ContextMeterData | null>(null)
const currentCompactSummary = ref<string | null>(null)

/** 模型选择下拉菜单项（对齐 /admin/profiles 接入池） */

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
const isCreatingSession = ref(false)
// F3/G5：草稿会话可预选绑定工作区（首条消息发送时随 create 固化；已建会话
// 绑定关系只读展示 workspace_name，运行期不可变更——换绑 = 新建会话）。
const draftWorkspaceId = ref<string | null>(null)
const draftWorkspaceName = ref<string>('')
const bindingPanelOpen = ref(false)
// 面板内新建工作区（即建即绑，无需跳「我的工作区」）
// 未绑定服务端会话时保持草稿态，不得用列表首项冒充当前会话。
const currentSession = computed(() => sessions.value.find(s => s.id === currentSessionId.value) || null)
// 产品入口已收敛为 AgentLoop；保留 v-else 源码仅用于历史审计与后续删除。
const isLoopView = computed(() => true)
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
  const targetWsId = workspaceId || draftWorkspaceId.value || undefined
  const title = initialTitle || '新会话'
  const session = await api.sessions.create(title, {
    workspaceId: targetWsId,
    permissionTier: (permissionTier as any) || undefined,
  })
  sessions.value.unshift(session)
  // 在切换 prop 触发子组件 watch 前先建立连接，确保首次连接实际复用并行领取的短票。
  loopStore.open(session.id, preparedTicket)
  currentSessionId.value = session.id; clearDraftWorkspace()
  return session.id
}
const deletableSessionCount = computed(() => filteredSessions.value.filter((session) => session.can_delete).length)
const allDeletableSessionsSelected = computed(() => {
  const deletableIds = filteredSessions.value.filter((session) => session.can_delete).map((session) => session.id)
  return deletableIds.length > 0 && deletableIds.every((id) => selectedSessionIds.value.includes(id))
})
const inputText = ref('')

interface StagedAttachment {
  localId: string
  id: string
  name: string
  size: number
  contentType: string
  previewUrl: string
  file: File
  uploading: boolean
  uploadProgress: number
  error: boolean
}

const attachmentPreviews = createPreviewTracker()
const activeTask = ref<Task | null>(null)
// 取消请求发送后等待服务端确认，避免重复提交且不提前伪造 cancelled。
const cancellingTaskId = ref<string | null>(null)

/** 共享会话里进度坞只给任务创建者展示取消入口，服务端仍是最终权限裁决。 */

// 智能体能力卡与顶栏共用同一模式状态，避免出现页面内外不一致的评测上下文。




// 快捷芯片：短标签 + 完整 prompt（对齐原型 data-say），顺序随顶栏模式重排

/** 旧栈会话判定输入：生成中 / 任务（当前会话优先）/ 会话状态 / 当前会话断线。 */
function legacyDotInput(s: any) {
  const rt = sessionRuntimes.get(s.id)
  const generating = Boolean(generatingBySession.value[s.id] || (s.id === currentSessionId.value && isGenerating.value) || rt?.isGenerating)
  const task = (s.id === currentSessionId.value ? activeTask.value : null) || rt?.activeTask || s.active_task
  return {
    generating,
    taskStatus: task?.status as string | undefined,
    sessionStatus: s.status as string | undefined,
    offline: s.id === currentSessionId.value && !isWsOnline.value,
  }
}

/** D5 会话列表状态点多态：按 status / active_task / 本轮生成中 / 断线重连 映射 nav-dot 样式，常驻显示就绪状态。 */
function sessionDotClass(s: any): string {
  if (s.engine_version === 'agent_loop_v2') return loopSessionDot(loopStore.sessions[s.id], s.active_task?.status)
  return legacySessionDot(legacyDotInput(s))
}

/** 会话状态提示语（鼠标悬停指示点时展示）。 */
function sessionDotTooltip(s: any): string {
  if (s.engine_version === 'agent_loop_v2') return loopSessionTooltip(loopStore.sessions[s.id])
  return legacySessionTooltip(legacyDotInput(s))
}

/* S10 进度坞收尾提示：非空时坞保持可见，2.6s 后隐藏 */
const dockClosingNote = ref('')

/** S10 任务结束收尾：先展示完成 note，2.6s 后再隐藏进度坞（对齐原型 hideDock）。 */

/** 仅在服务端确认取消后关闭进度坞，避免网络失败被前端误报为已取消。 */

/* ─── 页面级定时器登记：所有演示/兜底定时器统一登记，组件卸载时集中清理，避免回调写入已销毁状态 ─── */
const pendingTimers = new Set<number>()

function trackTimeout(fn: () => void, ms: number): number {
  const id = window.setTimeout(() => {
    pendingTimers.delete(id)
    fn()
  }, ms)
  pendingTimers.add(id)
  return id
}


/** 主动清除已登记定时器（任务提前完成时使用）。 */

/** 滚动锚定：仅当视口贴底（距底 <72px）时才跟随新消息，上翻阅读不被打断（对齐原型行为）。 */



/** 自适应调整多行输入框高度（最小 38px，最大 200px 限制，超高自动滚动） */
function adjustTextareaHeight() {
  const el = textareaRef.value
  if (!el) return
  if (!inputText.value) {
    el.style.height = ''
    el.style.overflowY = 'hidden'
    return
  }
  // 先将高度置为 0px，强制浏览器依据当前文本行数精确重算真实的 scrollHeight
  el.style.height = '0px'
  const scrollH = el.scrollHeight
  const minH = 38
  const maxH = 200
  const targetH = Math.min(maxH, Math.max(minH, scrollH))
  el.style.height = `${targetH}px`
  el.style.overflowY = scrollH > maxH ? 'auto' : 'hidden'
}

// 深度监听输入文本变化，无论是快捷 Prompt 填入还是换行均即时同步高度
watch(inputText, () => {
  nextTick(adjustTextareaHeight)
})


/** 后缀白名单、准入校验与预览 URL 追踪见 agent/attachments；此处只做上传编排。 */

/** 把文件加入暂存架并立即上传，发送时只把成功换取的 file_id 写入 WS 消息。 */

/** 文件选择支持多选，与拖拽上传共用同一校验和上传流程。 */

/** 拖拽进入时用深度计数避免经过子节点触发闪烁。 */





/** 键盘事件监听：Enter 发送，Shift + Enter 换行。 */


/** 快捷芯片/能力卡点击仅填入输入框并聚焦，由用户确认后再发送（对齐原型行为）。 */

/** 将当前页面切换为未持久化的新会话草稿，保留其他会话的后台生成状态。 */
function resetToDraftSession() {
  persistCurrentRuntime()
  stopFlowAnimations()
  // 失效尚未完成的历史回放，避免旧会话回放结果覆盖草稿页。
  selectEpoch += 1
  gcIdleSockets('')
  currentSessionId.value = ''
  agentWs = null
  events.value = []
  isGenerating.value = false
  turnLatencyMs.value = 0
  activeTask.value = null
  currentContextMeter.value = null
  currentCompactSummary.value = null
  dockClosingNote.value = ''
  isRailOpen.value = false
  // 草稿尚未绑定 WS，页面不应因为没有会话而显示离线错误。
  isWsOnline.value = true
}

/** 将服务端新建的会话绑定到当前页面，并初始化空的运行时缓存。 */

/** F3/G5：打开草稿绑定面板并加载可选工作区（仅属主自己的，无 share）。 */


/** 面板内新建工作区并自动选中（即建即绑；失败保留面板与输入，便于重试）。 */

function clearDraftWorkspace() {
  draftWorkspaceId.value = null
  draftWorkspaceName.value = ''
  bindingPanelOpen.value = false
}

/** 首次发送消息时才向服务端创建会话；mock 列表已由 API 层写入时避免重复插入。 */

/** 确保当前会话的实时连接已建立，首次发送和报告解读共用此连接门禁。 */


/** Mock 模式：本地模拟一次纯文本回复（不再伪造思考卡/工具/确认卡）。 */



async function loadSessions() {
  try {
    const list = await api.sessions.list()
    // 历史 legacy 会话保留在服务端审计数据中，但不再进入唯一的 AgentLoop 工作台。
    sessions.value = (list || []).filter((session) => session.engine_version === 'agent_loop_v2')
  } catch {
    sessions.value = []
  }
}

/** 加载全部接入协议档并解析当前 Agent 驱动模型 */
async function resolveAgentModelName() {
  try {
    const [settings, profiles] = await Promise.all([
      api.admin.getSettings().catch(() => null),
      api.profiles.list().catch(() => []),
    ])
    allProfiles.value = profiles || []
    const pid = settings?.agent_profile_id
    currentAgentProfileId.value = pid || ''
  } catch {
    currentAgentProfileId.value = ''
  }
}

/** 切换当前 Agent 调用的后端接入模型（直接持久化至 admin settings 并即时生效） */

/** F4 会话历史回放：按回合容器恢复模型头部与助手正文的顺序。 */

async function selectSession(sid: string) {
  if (deletingSessionIds.has(sid)) return
  const selected = sessions.value.find((session) => session.id === sid)
  // 列表已过滤历史会话；双重守卫确保任何残留点击也不会落到旧 WS transport。
  if (!selected || selected.engine_version !== 'agent_loop_v2') return
  // S2 修复：切换会话即关闭草稿绑定面板（绑定仅草稿态可用，避免误操作残留）
  bindingPanelOpen.value = false
  // 移动端会话列表是覆盖式抽屉，选中会话后自动收起让出对话区。
  if (typeof window !== 'undefined' && window.innerWidth <= 768) isListCollapsed.value = true
  if (sid === currentSessionId.value && sockets.has(sid)) {
    const existing = sockets.get(sid)
    if (existing?.isConnected) return
    existing?.close()
    sockets.delete(sid)
  }
  selectEpoch += 1
  persistCurrentRuntime()
  stopFlowAnimations()
  currentSessionId.value = sid
  // 统一由 AgentLoop store 持有 v2 连接；不再为会话建立旧 AgentWebSocket。
  isGenerating.value = false; isWsOnline.value = true; isRailOpen.value = false; agentWs = null
  loopStore.open(sid)
}

/** 打开一个新的本地草稿；服务端会话在用户真正发送消息时才创建。 */
function handleCreateSession() {
  if (isCreatingSession.value) return
  sessionStatusFilter.value = 'all'
  resetToDraftSession()
  // 清除未持久化 AgentLoop 草稿及其对象 URL；已建会话的连接和草稿保持不动。
  loopStore.remove('draft')
  // 新会话不带上次草稿的工作区预选
  clearDraftWorkspace()
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


/** 等待 WebSocket 首次连接完成，避免草稿首条消息落在连接竞态窗口内。 */

/** 移除打字占位气泡：服务端首个事件到达即表明流式已开始。 */

/** 把纯文本渲染为气泡 HTML（转义防 XSS + 换行转 <br>）。 */

/** 本轮最后一条用户消息之后仍在流式的助手气泡。 */

/** 停掉当前页打字机，避免切会话后定时器改旧缓存并滚动新会话。 */
function stopFlowAnimations() {
  events.value.forEach((item) => {
    if (item.type === 'agent') {
      if (item.streaming) item.streaming = false
      for (const block of item.blocks || []) {
        if (block.type === 'assistant' && block.streaming) block.streaming = false
      }
    }
  })
}

/** 交付后向服务端重拉 ContextMeter，禁止前端自己加减条数。 */

/** AI 生成的会话标题回写侧边栏；currentSession 是列表派生值，头部标题随之联动。 */

/** 后台会话继续生成：把事件写入该会话缓存，不打断当前正在看的对话。 */


function formatRelativeTime(dateStr?: string) {
  if (!dateStr) return '刚刚'
  const diff = Date.now() - new Date(dateStr).getTime()
  const mins = Math.floor(diff / 60000)
  if (mins < 1) return '刚刚'
  if (mins < 60) return `${mins} 分钟前`
  return `${Math.floor(mins / 60)} 小时前`
}

/** HTML 转义：历史 assistant 消息纯文本安全注入气泡（对齐原型 AE.esc）。 */

/** 将历史或 WS 的文件 ID 统一成既有附件芯片可读取的对象。 */

/** 返回用户气泡展示名：自己的消息显示“我”，协作者优先显示昵称。 */

/** 判断用户气泡是否来自当前成员以外的团队协作者。 */

/** 将助手消息时间格式化为原型中的 MM/DD HH:mm。 */

/** 记录本轮助手消息头所需的供应商、模型和协议档信息。 */

/** 追加本地演示助手消息，并同步当前 Agent 的供应商 Logo 与模型元数据。 */

/** 按消息模型快照解析品牌图标，避免协议档后续改动影响历史回合。 */

/** 解析历史消息中的模型显示名称，优先使用快照字段。 */

/** 解析历史消息中的协议档显示名称，优先使用快照字段。 */

/** 将 assistant_message 的服务端模型快照转换为前端回合元数据。 */

/** 把服务端确认的模型快照应用到助手回合，避免继续使用全局当前模型。 */

/** 返回当前用户回合的助手容器；错误、报告等顶层事件会结束当前容器。 */

/** 获取或创建一个 Agent 回合容器；助手正文追加到其 blocks。 */

/** 返回或创建当前回合的助手正文块。已落库的段落不再覆盖，保证中间叙述另起一段。 */

/** 为每次用户发送生成浏览器侧幂等键，断线重发时避免重复触发 Harness。 */

const events = ref<StreamItem[]>([])
let agentWs: AgentWebSocket | null = null

/** 按会话缓存对话流与生成态：切换会话不丢历史，生成中的 WS 不拆。 */
interface SessionRuntime {
  events: StreamItem[]
  isGenerating: boolean
  harnessStage: string
  turnLatencyMs: number
  activeTask: any
  contextMeter: ContextMeterData | null
  compactSummary: string | null
}

const sessionRuntimes = new Map<string, SessionRuntime>()
const sockets = new Map<string, AgentWebSocket>()
const generatingBySession = ref<Record<string, boolean>>({})
let selectEpoch = 0

function emptyRuntime(): SessionRuntime {
  return {
    events: [],
    isGenerating: false,
    harnessStage: '',
    turnLatencyMs: 0,
    activeTask: null,
    contextMeter: null,
    compactSummary: null,
  }
}

function ensureRuntime(sid: string): SessionRuntime {
  let rt = sessionRuntimes.get(sid)
  if (!rt) {
    rt = emptyRuntime()
    sessionRuntimes.set(sid, rt)
  }
  return rt
}

function markGenerating(sid: string, value: boolean) {
  if (!sid) return
  const rt = ensureRuntime(sid)
  rt.isGenerating = value
  if (generatingBySession.value[sid] === value) return
  generatingBySession.value = { ...generatingBySession.value, [sid]: value }
}

/** 当前会话生成态：同步列表小点与缓存，切走后后台仍显示「正在生成」。 */

/** 把当前 UI 状态写回该会话缓存（切走前调用）。 */
function persistCurrentRuntime() {
  const sid = currentSessionId.value
  if (!sid) return
  const rt = ensureRuntime(sid)
  rt.events = events.value
  rt.isGenerating = isGenerating.value
  rt.harnessStage = harnessStage.value
  rt.turnLatencyMs = turnLatencyMs.value
  rt.activeTask = activeTask.value
  rt.contextMeter = currentContextMeter.value
  rt.compactSummary = currentCompactSummary.value
  markGenerating(sid, isGenerating.value)
}

/** 关闭已结束生成且非当前会话的连接，生成中的会话保持 WS 以便后台继续收事件。 */
function gcIdleSockets(keepId: string) {
  for (const [id, ws] of sockets) {
    if (id === keepId) continue
    if (sessionRuntimes.get(id)?.isGenerating) continue
    ws.close()
    sockets.delete(id)
  }
}

/** 服务端以 4404 收回会话后同步移除本地缓存，避免列表留下无法重连的幽灵项。 */
function removeInaccessibleSession(sid: string, navigate = true) {
  if (loopStore.sessions[sid] || loopStore.drafts[sid]) loopStore.remove(sid)
  const index = sessions.value.findIndex((session) => session.id === sid)
  const wasCurrent = currentSessionId.value === sid
  const socket = sockets.get(sid)
  if (socket) socket.close()
  sockets.delete(sid)
  sessionRuntimes.delete(sid)
  selectedSessionIds.value = selectedSessionIds.value.filter((id) => id !== sid)
  const nextGenerating = { ...generatingBySession.value }
  delete nextGenerating[sid]
  generatingBySession.value = nextGenerating
  if (index < 0) return

  sessions.value.splice(index, 1)
  if (wasCurrent && agentWs === socket) agentWs = null
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
  if (wasCurrent) selectEpoch += 1
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

/** ToolCard：点击折叠/展开详情。 */




interface AgentAssistantItem {
  type: 'assistant'
  raw?: string
  text?: string
  streaming?: boolean
  latency_ms?: number
}

interface AgentErrorItem {
  type: 'error'
  code?: string
  message?: string
  noAnim?: boolean
}

/** H3 ToolCard 运行时状态（tool_call → tool_result 生命周期）。 */
interface ToolRunItem {
  call_id: string
  name: string
  arguments?: unknown
  status: 'running' | 'done' | 'error'
  ok?: boolean
  error?: string
}

type AgentBlock = AgentAssistantItem | AgentErrorItem

interface StreamItem {
  type: 'user' | 'agent' | 'report' | 'confirm' | 'toolApproval' | 'clarify' | 'error' | 'typing'
  text?: string
  latency_ms?: number
  streaming?: boolean
  raw?: string
  noAnim?: boolean
  messageId?: string
  clientMessageId?: string
  author?: SessionAuthor | null
  files?: any[]
  blocks?: AgentBlock[]
  toolItems?: ToolRunItem[]
  openToolId?: string
  providerLogoKey?: ProviderLogoKey
  profileId?: string
  modelName?: string
  profileName?: string
  createdAt?: string
  reportId?: string
  kpis?: any[]
  bars?: any[]
  code?: string
  message?: string
  // 确认卡（V1.67 恢复）：card 为 TaskSpec；confirmAuthor 为服务端元数据（提交前剥离）
  card?: any
  confirmAuthor?: SessionAuthor | null
  isAcked?: boolean
  ackResult?: boolean
  summary?: string
  open?: boolean
  fieldErrors?: Record<string, string>
  // 工具审批卡（H5 HITL，API.md V1.70 / V1.73 / F5-G6）：approval 为中断载荷
  // 快照；approvalDone 由 tool_approval_ack 回执盖章（approved/rejected）或
  // approval_terminal 终态事件驱动（expired 超时 / cancelled 放弃 /
  // voided 检查点缺失作废 / recovery_failed 恢复失败——M-R3-7 成组扩展）。
  approval?: ToolApprovalPayload | null
  approvalDone?: 'approved' | 'rejected' | 'expired' | 'cancelled' | 'voided' | 'recovery_failed' | null
  // 澄清卡（V1.72 / dsh #1，API.md §4.3）：clarify 为中断问卷快照；
  // clarifyDone 由 clarify_reply 乐观盖章 + clarify_ack 广播回执确认；
  // M3：failed = approval_terminal(recovery_failed, card_type=clarify) 终态。
  clarify?: ClarifyPayload | null
  clarifyDone?: 'submitted' | 'failed' | null
}

const harnessStage = ref<string>('')
// ════════ 确认卡（V1.67 / H2 批次 2 恢复）：选项加载、规范化、校验与 ack ════════

const availableProfiles = ref<Profile[]>([])
const availableDatasets = ref<Dataset[]>([])
const availableKbs = ref<KnowledgeBase[]>([])
/** 跨会话下单偏好（/api/agent/prefs）：首单空槽预填，后端已给的值不覆盖。 */
const agentPrefs = ref<AgentPrefs | null>(null)
/** F12 prod 会签人名单：取自 api.admin.getSettings().prod_approvers，失败回退静态文案。 */
const prodApprovers = ref<string[]>([])
/** A1：确认成功前不盖章，等服务端 confirm_ack 到达后再清除乐观态。 */


/** 工具审批卡可操作：实时连接且该卡尚未回执（owner 校验由服务端行锁把关）。 */

/** H5 HITL 审批回执：乐观盖章（服务端行锁兜底重复 ack；tool_approval_ack
 * 广播回执到达后终态一致）。审批放行以原 thread_id 恢复检查点回合。 */


/** 澄清卡可作答：实时连接且尚未终态（submitted/failed 均禁操作；owner 校验由服务端行锁把关）。 */

/** V1.72（dsh #1）澄清作答：乐观盖章（服务端行锁兜底重复 reply；clarify_ack
 * 广播回执到达后终态一致）。作答后回合按 answers[] 以原 thread_id 续跑。 */


/** F10：当前选中知识库是否为外部 Chat 库（无 rag_mode，改选恰好 1 个外部 RAG 服务档）。 */

/** F8 确认卡内联校验：错误留在卡内 .field-error 红字，不 Toast。 */

/** 现网列表加载后，丢掉确认卡上已删除、chip 点不掉的资产 ID。 */
function sanitizeConfirmAssets(card: any) {
  if (!card || typeof card !== 'object') return card
  const liveProfiles = new Set(availableProfiles.value.map(p => p.id))
  if (liveProfiles.size && Array.isArray(card.profile_ids)) {
    card.profile_ids = card.profile_ids.filter((id: string) => liveProfiles.has(String(id)))
  }
  const liveDatasets = new Set(availableDatasets.value.map(d => d.id))
  if (liveDatasets.size && card.dataset_id && !liveDatasets.has(card.dataset_id)) {
    card.dataset_id = null
  }
  const liveKbs = new Set(availableKbs.value.map(k => k.id))
  if (liveKbs.size && card.kb_id && !liveKbs.has(card.kb_id)) {
    card.kb_id = null
    card.gold_qa_id = null
  }
  return card
}

/** 选项列表到达后，再滤一遍未 ack 确认卡上的失效 ID。 */
function sanitizeOpenConfirmCards() {
  for (const item of events.value) {
    if (item?.type === 'confirm' && item.card && !item.isAcked) {
      sanitizeConfirmAssets(item.card)
    }
  }
}

/** 确认卡规范化：补齐 run / stress / case_source 默认值，保证折叠区 v-model 绑定路径始终存在。 */

/** 实时模式预装确认卡选项（API.md §4.3 confirm：卡即补槽 UI）。 */
async function loadConfirmOptions() {
  if (api.isMock()) return
  try {
    const [profiles, datasets, kbs] = await Promise.all([
      api.profiles.list().catch(() => []),
      api.datasets.list().catch(() => []),
      api.kb.list().catch(() => []),
    ])
    if (profiles?.length) availableProfiles.value = profiles
    if (datasets?.length) availableDatasets.value = datasets
    if (kbs?.length) availableKbs.value = kbs
    // 黄金 QA 选项仅在 rag 卡可用（skill-rag 现行 fail-closed，暂无实时来源）
    sanitizeOpenConfirmCards()
  } catch {
    // 选项留空，确认时仍走卡内校验，不阻断会话
  }
}



onMounted(async () => {
  // 跨会话下单偏好先行加载：历史回放中的确认卡规范化要用它预填空槽
  try {
    agentPrefs.value = await api.agent.getPrefs()
  } catch {
    agentPrefs.value = null
  }
  await loadSessions()
  // 顶栏/输入框的 Agent 模型名改为按后端协议档动态解析，不再硬编码
  // 先解析协议档，再回放历史消息，保证助手消息头能显示正确供应商 Logo 与模型名称。
  await resolveAgentModelName()
  // V1.67：预装确认卡选项（协议档/数据集/知识库），刷新后的待确认卡才能补槽
  await loadConfirmOptions()
  // F12 拉取 prod 会签人名单用于确认卡动态提示；失败静默回退静态文案
  try {
    const settings = await api.admin.getSettings()
    if (settings?.prod_approvers?.length) prodApprovers.value = settings.prod_approvers
  } catch {}
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
  // 统一清理登记的全部定时器，防止卸载后回调触发
  pendingTimers.forEach(id => {
    window.clearTimeout(id)
    window.clearInterval(id)
  })
  pendingTimers.clear()
  for (const ws of sockets.values()) {
    ws.close()
  }
  sockets.clear()
  agentWs = null
  attachmentPreviews.revokeAll()
})

/** 移除打字占位气泡：服务端首个事件到达即表明流式已开始（旧栈 WS 事件链仍在引用，保留定义）。 */

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

.chat-ws-chip.draft {
  color: var(--c-success, #188038);
  border-color: var(--t-success, rgba(24, 128, 56, 0.3));
}

.ws-chip-x {
  cursor: pointer;
  font-weight: 700;
  padding: 0 2px;
  color: var(--text-tertiary);
}

.ws-chip-x:hover {
  color: var(--text-primary);
}

.ws-binding-panel {
  position: absolute;
  top: 52px;
  right: 16px;
  z-index: 40;
  width: min(360px, calc(100vw - 32px));
  max-height: 300px;
  overflow: auto;
  padding: 10px 12px;
  border-radius: 12px;
  border: 1px solid var(--border-subtle);
  background: var(--bg-elevated);
  box-shadow: 0 8px 24px rgba(0, 0, 0, 0.12);
}

.ws-binding-panel-title {
  font-size: 12px;
  font-weight: 600;
  padding-bottom: 6px;
  border-bottom: 1px solid var(--border-subtle);
  margin-bottom: 4px;
}

.ws-binding-item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  width: 100%;
  text-align: left;
  gap: 8px;
  border: none;
  background: transparent;
  color: var(--text-primary);
  font-size: 13px;
  padding: 8px 4px;
  border-radius: 8px;
  cursor: pointer;
}

.ws-binding-item:hover {
  background: var(--bg-hover, rgba(128, 128, 128, 0.08));
}

/* 面板内新建工作区（即建即绑） */
.ws-binding-create {
  display: flex;
  gap: 8px;
  margin-top: 8px;
  padding-top: 8px;
  border-top: 1px solid var(--border-subtle);
}

.ws-binding-create-input {
  flex: 1;
  min-width: 0;
  font-size: 13px;
  padding: 6px 10px;
}

/* 协作者消息左对齐并弱化背景色，作者行让多人记录可以追溯。 */
.msg-user.remote {
  align-items: flex-start;
}

.msg-user.remote .bubble-user {
  background: var(--bg-elevated);
  border: 1px solid var(--border-subtle);
  border-bottom-left-radius: 6px;
  border-bottom-right-radius: 20px;
  color: var(--text-primary);
}

.bubble-user-markdown {
  color: #ffffff;
  word-break: break-word;
}

.bubble-user-markdown :deep(.markdown-content) {
  font-size: 15px;
  line-height: 1.65;
  color: #ffffff;
  tab-size: 4;
  -moz-tab-size: 4;
  white-space: pre-wrap;
  word-break: break-word;
}

.bubble-user-markdown :deep(.md-p) {
  margin: 0;
  line-height: 1.65;
  color: inherit;
  font-size: 15px;
  white-space: pre-wrap;
}

.bubble-user-markdown :deep(.md-p + .md-p) {
  margin-top: 10px;
}

.bubble-user-markdown :deep(strong) {
  color: #ffffff;
  font-weight: 700;
}

.bubble-user-markdown :deep(em) {
  color: #ffffff;
  font-style: italic;
}

.bubble-user-markdown :deep(.md-inline-code) {
  background: rgba(255, 255, 255, 0.22);
  color: #ffffff;
  border: 1px solid rgba(255, 255, 255, 0.35);
  border-radius: 4px;
  padding: 1.5px 6px;
  font-family: var(--font-mono);
  font-size: 13.5px;
  white-space: pre-wrap;
}

.bubble-user-markdown :deep(.md-code-card) {
  margin: 8px 0;
  background: rgba(15, 23, 42, 0.95);
  border: 1px solid rgba(255, 255, 255, 0.2);
  border-radius: 8px;
  text-align: left;
}

.bubble-user-markdown :deep(.md-code-body) {
  color: #f1f5f9;
  font-size: 13.5px;
}

.bubble-user-markdown :deep(.md-ul) {
  padding-left: 20px;
  margin: 6px 0;
}

.bubble-user-markdown :deep(.md-li-bullet),
.bubble-user-markdown :deep(.md-li-num) {
  color: #ffffff;
  margin-bottom: 4px;
  line-height: 1.6;
  font-size: 15px;
}

.bubble-user-markdown :deep(.md-li-bullet::marker),
.bubble-user-markdown :deep(.md-li-num::marker) {
  color: rgba(255, 255, 255, 0.85);
}

.bubble-user-markdown :deep(.md-quote) {
  border-left-color: rgba(255, 255, 255, 0.6);
  background: rgba(255, 255, 255, 0.12);
  color: rgba(255, 255, 255, 0.95);
  margin: 8px 0;
  padding: 6px 12px;
}

/* 远端协作者用户气泡颜色自适应 */
.msg-user.remote .bubble-user-markdown,
.msg-user.remote .bubble-user-markdown :deep(.markdown-content),
.msg-user.remote .bubble-user-markdown :deep(.md-p),
.msg-user.remote .bubble-user-markdown :deep(strong),
.msg-user.remote .bubble-user-markdown :deep(.md-li-bullet),
.msg-user.remote .bubble-user-markdown :deep(.md-li-num) {
  color: var(--text-primary);
}

.msg-user.remote .bubble-user-markdown :deep(.md-inline-code) {
  background: rgba(0, 0, 0, 0.06);
  color: var(--accent-ai);
  border-color: var(--border-subtle);
}

.user-author {
  color: var(--text-tertiary);
  font-size: 11px;
  font-weight: 600;
}

/* 助手消息头：用真实供应商图形对齐模型名和协议档名称。 */
.assistant-message-layout {
  display: flex;
  align-items: flex-start;
  gap: 10px;
}

.assistant-message-logo {
  margin-top: 2px;
}

.assistant-message-main {
  min-width: 0;
  flex: 1;
}

.assistant-message-header {
  margin-bottom: 7px;
  line-height: 1.25;
}

.assistant-message-model {
  color: var(--text-primary);
  font-size: 14px;
  font-weight: 700;
  letter-spacing: -0.01em;
}

.assistant-message-profile {
  color: var(--text-secondary);
  font-weight: 650;
}

.assistant-message-time {
  margin-top: 3px;
  color: var(--text-tertiary);
  font-size: 10px;
  line-height: 1.2;
}

/* 顶部与输入框模型选择胶囊按钮 */
.chat-head-model-pill,
.chat-head-model-btn {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 3px 10px;
  border-radius: 999px;
  border: 1px solid var(--border-subtle);
  background: var(--bg-elevated);
  color: var(--text-secondary);
  font-family: var(--font-mono);
  font-size: 11px;
  cursor: pointer;
  user-select: none;
  transition: all 0.15s ease;
}
.chat-head-model-btn:hover {
  background: var(--bg-hover, #f3f4f6);
  border-color: var(--border-color, #d1d5db);
  color: var(--text-primary, #111827);
}
.composer-model-btn {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  padding: 2px 8px;
  border-radius: 6px;
  border: 1px solid var(--border-subtle);
  background: var(--bg-elevated);
  color: var(--text-secondary);
  font-family: var(--font-mono);
  font-size: 11px;
  cursor: pointer;
  user-select: none;
  transition: all 0.15s ease;
}
.composer-model-btn:hover {
  background: var(--bg-hover, #f3f4f6);
  border-color: var(--border-color, #d1d5db);
  color: var(--text-primary, #111827);
}

/* 底部输入框整体容器（固定吸附于对话流底部，不随会话滚动消失） */
.composer {
  padding: 6px 20px 14px;
  flex-shrink: 0;
  background: var(--bg-main);
}

.quick-chips {
  max-width: 840px;
  margin: 0 auto 8px;
}

/* 用户消息与输入区共用附件卡片布局，图片优先给出可识别的缩略图。 */
.message-attachments,
.attach-stage {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.message-attachments {
  justify-content: flex-end;
}

.msg-user.remote .message-attachments {
  justify-content: flex-start;
}

.attach-stage {
  width: 100%;
  max-width: none;
  margin: 0 0 2px;
}

/* 输入卡片：上部多行文本，下部操作底栏（对齐 Gemini / Cursor / Claude 对话框） */
.composer-card {
  max-width: 840px;
  margin: 0 auto;
  border: 1px solid var(--border-subtle);
  border-radius: 16px;
  background: var(--bg-main);
  box-shadow: 0 2px 14px rgba(0, 0, 0, 0.04);
  padding: 10px 12px 8px;
  display: flex;
  flex-direction: column;
  gap: 4px;
  transition: border-color 0.18s ease, box-shadow 0.18s ease, background-color 0.18s ease;
}

.composer-card:focus-within {
  border-color: var(--accent-ai);
  box-shadow: 0 0 0 3px color-mix(in srgb, var(--accent-ai) 15%, transparent), 0 4px 18px rgba(0, 0, 0, 0.06);
}

.composer-card.drag-active {
  border-color: var(--accent-ai);
  background: color-mix(in srgb, var(--accent-ai) 5%, var(--bg-main));
  box-shadow: 0 0 0 4px color-mix(in srgb, var(--accent-ai) 13%, transparent);
}

.composer-drop-hint {
  position: absolute;
  inset: 0;
  z-index: 3;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  border-radius: inherit;
  background: color-mix(in srgb, var(--bg-main) 92%, var(--accent-ai));
  color: var(--text-primary);
  font-size: 13px;
  pointer-events: none;
}

.composer-drop-hint span:last-child {
  color: var(--text-tertiary);
  font-size: 11px;
}

.composer-drop-icon {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 24px;
  height: 24px;
  border-radius: 50%;
  background: var(--t-agent);
  color: var(--c-agent);
  font-size: 17px;
  line-height: 1;
}

/* 运行生成中的动态环绕光束特效 (Border Beam) */
@property --composer-border-angle {
  syntax: '<angle>';
  inherits: false;
  initial-value: 0deg;
}

.composer-card.generating {
  border-color: transparent !important;
  box-shadow: 0 0 20px color-mix(in srgb, var(--accent-ai, #10b981) 22%, transparent),
              0 4px 20px rgba(0, 0, 0, 0.12);
}

.composer-card.generating::before {
  content: '';
  position: absolute;
  inset: -1.5px;
  border-radius: 17.5px;
  padding: 1.5px;
  background: conic-gradient(
    from var(--composer-border-angle, 0deg),
    transparent 0%,
    transparent 40%,
    var(--accent-ai, #10b981) 60%,
    #38bdf8 76%,
    #818cf8 88%,
    transparent 100%
  );
  -webkit-mask: linear-gradient(#fff 0 0) content-box, linear-gradient(#fff 0 0);
  -webkit-mask-composite: xor;
  mask-composite: exclude;
  pointer-events: none;
  z-index: 1;
  animation: rotate-composer-border 2.4s linear infinite;
}

@keyframes rotate-composer-border {
  from {
    --composer-border-angle: 0deg;
  }
  to {
    --composer-border-angle: 360deg;
  }
}

/* 输入框上半区行容器 */
.composer-input-row {
  display: flex;
  align-items: flex-start;
  gap: 2px;
  width: 100%;
  min-height: 38px;
}

/* 多行文本域自适应高度（最小 38px，最大 200px 限制） */
.composer-textarea {
  flex: 1;
  width: 100% !important;
  border: none !important;
  outline: none !important;
  box-shadow: none !important;
  resize: none !important;
  font-family: var(--font-chat, inherit) !important;
  font-size: 14.5px !important;
  line-height: 1.55 !important;
  min-height: 38px !important;
  max-height: 200px !important;
  padding: 4px 6px !important;
  background: transparent !important;
  color: var(--text-primary, #111827) !important;
  box-sizing: border-box !important;
  overflow-y: hidden;
  -webkit-appearance: none !important;
  -moz-appearance: none !important;
  appearance: none !important;
}

.composer-textarea:focus,
.composer-textarea:hover,
.composer-textarea:active {
  border: none !important;
  outline: none !important;
  box-shadow: none !important;
}

.composer-textarea::placeholder {
  color: var(--text-tertiary);
  font-size: 13.5px;
}

/* 操作底栏 */
.composer-bottom-bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding-top: 2px;
}

.composer-left-actions {
  display: flex;
  align-items: center;
  gap: 6px;
}

/* 附件小按钮 (+) */
.composer-action-btn {
  width: 22px;
  height: 22px;
  border-radius: 6px;
  border: none;
  background: transparent;
  color: var(--text-tertiary);
  display: flex;
  align-items: center;
  justify-content: center;
  cursor: pointer;
  transition: all 0.15s ease;
}

.composer-attach-btn {
  flex: 0 0 22px;
  margin-top: 5px;
}

.composer-action-btn:hover {
  background: var(--bg-elevated);
  color: var(--text-primary);
}

/* 模型切换下拉按钮（对齐参考图：模型名 + 箭头） */
.composer-model-dropdown-btn {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  padding: 4px 8px;
  border-radius: 6px;
  border: none;
  background: transparent;
  color: var(--text-secondary);
  font-size: 12.5px;
  font-weight: 500;
  cursor: pointer;
  white-space: nowrap;
  user-select: none;
  transition: all 0.15s ease;
}

.composer-model-dropdown-btn:hover {
  background: var(--bg-elevated);
  color: var(--text-primary);
}

.composer-model-dropdown-btn .model-name {
  max-width: 220px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-family: var(--font-mono, monospace);
  font-size: 12px;
}

.composer-model-dropdown-btn .chevron-icon {
  opacity: 0.65;
  transition: transform 0.15s ease;
}

/* 右侧圆形发送/暂停按钮 */
.composer-send-btn {
  width: 32px;
  height: 32px;
  border-radius: 50%;
  border: none;
  display: flex;
  align-items: center;
  justify-content: center;
  background: var(--bg-elevated);
  color: var(--text-tertiary);
  cursor: not-allowed;
  transition: all 0.18s ease;
  flex-shrink: 0;
}

.composer-send-btn.active {
  background: #1f5947;
  color: #ffffff;
  cursor: pointer;
  box-shadow: 0 1px 3px rgba(23, 74, 58, 0.25);
}

.composer-send-btn.active:hover {
  background: #184738;
  color: #ffffff;
  transform: scale(1.05);
  box-shadow: 0 2px 6px rgba(23, 74, 58, 0.35);
}

.composer-send-btn.active:active {
  background: #143d30;
  transform: scale(0.96);
}

[data-theme='dark'] .composer-send-btn.active {
  background: #16977a;
  color: #ffffff;
}

[data-theme='dark'] .composer-send-btn.active:hover {
  background: #148369;
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
  .composer {
    padding: 6px 10px max(12px, env(safe-area-inset-bottom));
  }
  .composer-card {
    border-radius: 14px;
  }
  .composer-drop-hint {
    flex-wrap: wrap;
    padding: 12px 24px;
    text-align: center;
  }
  .composer-model-dropdown-btn .model-name {
    max-width: 100px;
  }
  .quick-chips {
    overflow-x: auto;
    white-space: nowrap;
    -webkit-overflow-scrolling: touch;
  }
  .chat-scroll {
    padding: 12px 10px;
  }
  .msg-agent pre,
  .msg-agent table {
    max-width: calc(100vw - 44px);
    overflow-x: auto;
    -webkit-overflow-scrolling: touch;
  }
}
</style>
