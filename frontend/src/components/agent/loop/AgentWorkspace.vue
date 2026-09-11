<template>
  <div class="loop-workspace">
    <div class="loop-tabs">
      <button class="workspace-tab" :class="{active:tab==='chat'}" @click="tab='chat'">对话</button>
      <button class="workspace-tab" :class="{active:tab==='trace'}" :disabled="!state" @click="tab='trace'">轨迹 <small v-if="state?.cursor" class="trace-tab-count">{{ state.cursor }}</small></button>
      <div class="loop-tabs-actions">
        <span v-if="sessionId" class="loop-status">
          <i :class="{running:busy}"/>{{ status }}
        </span>
        <button class="loop-runtime-btn" type="button" @click="runtimeOpen=!runtimeOpen">运行信息</button>
      </div>
    </div>
    <p v-if="state && state.connection !== 'online'" class="loop-notice" role="status">{{ state.connection === 'connecting' ? '正在同步会话…' : '连接中断，状态待同步。' }}<button @click="store.clients.get(sessionId)?.connect()">重新连接</button></p>
    <p v-if="state?.error || error" class="loop-notice error" role="alert">{{ state?.error || error }}</p>
    <div class="loop-content">
      <div class="loop-center">
        <section v-if="tab==='chat'" ref="chatShell" class="loop-chat-shell" :class="{ 'is-resizing': isResizing, 'is-empty': !rows.length }" :style="chatShellStyle" aria-label="对话内容区域">
          <!-- 空状态：输入框上方水平居中展示 Logo + 名字及产品标语 -->
          <div v-if="!rows.length" class="loop-empty-hero">
            <div class="hero-brand">
              <div class="hero-logo-mark" aria-hidden="true">
                <svg width="22" height="22" viewBox="0 0 24 24" fill="none">
                  <path d="M12 3L4 20H8.5L10.2 15.5H13.8L15.5 20H20L12 3ZM11.1 11.8L12 7.2L12.9 11.8H11.1Z" fill="#ffffff" />
                </svg>
              </div>
              <div class="hero-brand-name-wrap">
                <span class="hero-brand-name">AI Eval</span>
                <span class="hero-brand-badge">AGENT LOOP</span>
              </div>
            </div>
            <h1 class="hero-tagline">从一个目标开始，让每一步都有依据。</h1>
            <p class="hero-subline">在工作区处理文件、查找资料，或创建评测任务。</p>
          </div>

          <!-- 对话消息滚动区：有消息时正常滚动展示；空状态隐藏以保持居中 -->
          <div ref="scroller" class="loop-conversation" :class="{ 'is-empty': !rows.length }" @scroll="trackScroll">
          <button v-if="shown < rows.length" class="history-more" @click="shown+=80">显示更早的 {{ Math.min(80, rows.length-shown) }} 条记录</button>
          <template v-for="row in visibleRows" :key="row.key">
            <article v-if="row.role==='user'" class="loop-message user"><header>你</header><div class="history-files"><AttachmentPreview v-for="file in attachments[row.key] || []" :key="file.file_id" :attachment="file"/></div><p>{{ row.content }}</p></article>
            <TaskRunCard v-else-if="'status' in row && 'name' in row && isTaskTool((row as ToolRun).name)" :tool="row as ToolRun" :task="taskForTool(row as ToolRun)" :interactions="interactions(row)" :can-control="canControl" :online="!!state?.ready" @respond="respond"/>
            <ToolRunCard v-else-if="'status' in row && 'name' in row && (row as ToolRun).name !== 'task'" :tool="row as ToolRun" :interactions="interactions(row)" :can-control="canControl" :online="!!state?.ready" @respond="respond"/>
            <article v-else class="loop-message assistant" :class="{ 'is-continuation': !isFirstAssistantInTurn(row) }">
              <header v-if="isFirstAssistantInTurn(row)" class="assistant-header">
                <div class="assistant-identity">
                  <ProviderLogo v-if="row.request_summary?.model" :provider="getModelLogoKey(row.request_summary.model)" :size="18"/>
                  <strong>{{ row.request_summary?.model || '助手' }}</strong>
                  <time v-if="formatTimestamp(row.timestamp)" :datetime="row.timestamp">{{ formatTimestamp(row.timestamp) }}</time>
                  <small v-if="row.request_summary">第 {{ row.correlation.turn ?? '—' }} 轮 · {{ row.request_summary.reasoning_effort }} · step {{ row.correlation.step }}</small>
                </div>
              </header>
              <ReasoningBlock v-if="row.reasoning && ui?.permissions.reasoning" :content="row.reasoning" :ended="row.ended" :interrupted="row.interrupted"/>
              <MarkdownView v-if="row.text" :content="row.text"/>
              <p v-else-if="!row.ended" class="muted">正在响应…</p>
              <small v-if="row.interrupted || row.error_code">{{ row.interrupted ? '本次输出已中断' : row.error_code }}</small>
            </article>
            <!-- 每轮对话结尾的统一操作与指标栏：复制、重新生成、引用记忆、token消耗、用时依次排列 -->
            <div v-if="turnSummaryByLastRowKey.get(row.key)" class="turn-end-toolbar" aria-label="本轮对话操作与指标">
              <div class="turn-end-actions">
                <button
                  class="assistant-action"
                  type="button"
                  title="复制回答"
                  aria-label="复制回答"
                  :disabled="!turnSummaryByLastRowKey.get(row.key)!.text"
                  @click="copy(turnSummaryByLastRowKey.get(row.key)!.text)"
                >
                  <n-icon :component="FileIcon" :size="15"/>
                </button>
                <button
                  class="assistant-action"
                  type="button"
                  title="重新生成"
                  aria-label="重新生成"
                  :disabled="busy || draft.submitting || !!draft.pending"
                  @click="regenerate(turnSummaryByLastRowKey.get(row.key)!.representativeRow)"
                >
                  <n-icon :component="RetryIcon" :size="15"/>
                </button>
                <button
                  class="assistant-action"
                  type="button"
                  title="引用为参考记忆"
                  aria-label="引用为参考记忆"
                  :disabled="!turnSummaryByLastRowKey.get(row.key)!.text"
                  @click="quoteMemory(turnSummaryByLastRowKey.get(row.key)!.text)"
                >
                  <n-icon :component="BackwardIcon" :size="15"/>
                </button>
              </div>
              <div class="turn-end-metrics assistant-metrics">
                <span v-if="turnSummaryByLastRowKey.get(row.key)!.totalTokens !== null" class="turn-end-metric">
                  <n-icon :component="FileIcon" :size="13"/>
                  {{ formatTokens(turnSummaryByLastRowKey.get(row.key)!.totalTokens) }} token
                </span>
                <span v-if="turnSummaryByLastRowKey.get(row.key)!.totalLatencyMs !== null" class="turn-end-metric">
                  <n-icon :component="TimeIcon" :size="13"/>
                  {{ formatDuration(turnSummaryByLastRowKey.get(row.key)!.totalLatencyMs) }}
                </span>
              </div>
            </div>
          </template>
          <p v-if="!busy && state?.phase && ['max_tokens','max_steps','cancelled','interrupted','error'].includes(state.phase)" class="loop-notice">{{ finishLabels[state.phase] }}</p>
          </div>
          <div class="loop-composer-wrap">
            <div class="composer-top-bar" :class="{ 'is-workspace-open': workspacePopoverOpen, 'is-locked': !!sessionId }">
              <n-popover
                ref="workspacePopoverRef"
                :show="workspacePopoverOpen"
                trigger="click"
                placement="bottom-start"
                :show-arrow="false"
                :animated="false"
                :flip="false"
                :content-style="{ padding: '0' }"
                class="workspace-popover-layer"
                @update:show="handleWorkspacePopoverVisibility"
              >
                <template #trigger>
                  <button
                    type="button"
                    class="composer-ws-btn"
                    :class="{ 'has-ws': !!activeWorkspaceId, 'is-draft': !sessionId, 'is-open': workspacePopoverOpen }"
                    :title="activeWorkspaceId ? `当前绑定工作区：${activeWorkspaceName}` : '点击选择或新建沙箱工作区（可选）'"
                    aria-haspopup="dialog"
                    :aria-expanded="workspacePopoverOpen"
                  >
                    <span class="ws-btn-folder-icon" aria-hidden="true">
                      <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">
                        <path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"></path>
                      </svg>
                    </span>
                    <span class="ws-btn-name">{{ activeWorkspaceId ? activeWorkspaceName : '绑定工作区' }}</span>
                    <span class="ws-btn-arrow" aria-hidden="true">
                      <svg width="10" height="10" viewBox="0 0 12 12" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round">
                        <path d="M3 4.5l3 3 3-3" />
                      </svg>
                    </span>
                  </button>
                </template>

                <div v-if="workspacePopoverOpen" :key="workspacePopoverEpoch" class="ws-popover-card">
                  <header class="ws-popover-header">
                    <div class="ws-popover-title">
                      <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                        <path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"></path>
                      </svg>
                      <span>沙箱工作区</span>
                    </div>
                    <span v-if="sessionId" class="ws-popover-badge">已绑定会话</span>
                    <span v-else-if="activeWorkspaceId" class="ws-popover-badge is-active">已预选</span>
                    <span v-else class="ws-popover-badge-draft">可选</span>
                  </header>

                  <p v-if="sessionId" class="ws-popover-tip">
                    当前会话已绑定此工作区{{ activeWorkspaceName ? `「${activeWorkspaceName}」` : '' }}，创建后不可更改。如需切换工作区，请新建会话。
                  </p>
                  <p v-else class="ws-popover-tip">
                    选择绑定的沙箱工作区（可选）。绑定后模型的文件读写与终端命令将在此工作区内隔离执行。
                  </p>

                  <template v-if="!sessionId">
                    <div v-if="loadingWorkspaces" class="ws-popover-loading">加载工作区中…</div>
                    <div v-else class="ws-popover-list">
                      <!-- 选项 1：不绑定工作区（默认沙箱） -->
                      <button
                        type="button"
                        class="ws-popover-item"
                        :class="{ 'is-selected': !activeWorkspaceId }"
                        @click="handleSelectWorkspace(null)"
                      >
                        <span class="ws-item-folder">
                          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">
                            <circle cx="12" cy="12" r="10"></circle>
                            <line x1="4.93" y1="4.93" x2="19.07" y2="19.07"></line>
                          </svg>
                        </span>
                        <span class="ws-item-name">不绑定工作区（默认沙箱）</span>
                        <span v-if="!activeWorkspaceId" class="ws-item-check">
                          <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
                            <polyline points="20 6 9 17 4 12"></polyline>
                          </svg>
                        </span>
                      </button>

                      <!-- 工作区列表项 -->
                      <button
                        v-for="ws in workspaces"
                        :key="ws.id"
                        type="button"
                        class="ws-popover-item"
                        :class="{ 'is-selected': ws.id === activeWorkspaceId }"
                        @click="handleSelectWorkspace(ws)"
                      >
                        <span class="ws-item-folder">
                          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">
                            <path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"></path>
                          </svg>
                        </span>
                        <span class="ws-item-name" :title="ws.name">{{ ws.name }}</span>
                        <span v-if="ws.id === activeWorkspaceId" class="ws-item-check">
                          <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
                            <polyline points="20 6 9 17 4 12"></polyline>
                          </svg>
                        </span>
                      </button>

                      <div v-if="workspaces.length === 0" class="ws-popover-empty">
                        暂无自定义工作区，可在下方新建
                      </div>
                    </div>

                    <footer class="ws-popover-footer">
                      <input
                        v-model="newWorkspaceName"
                        class="ws-popover-input"
                        placeholder="新建工作区名称…"
                        :disabled="creatingWorkspace"
                        maxlength="80"
                        @keydown.enter.prevent="handleCreateWorkspace"
                      />
                      <button
                        type="button"
                        class="ws-popover-create-btn"
                        :disabled="creatingWorkspace || !newWorkspaceName.trim()"
                        @click="handleCreateWorkspace"
                      >
                        {{ creatingWorkspace ? '创建中…' : '新建' }}
                      </button>
                    </footer>
                  </template>
                </div>
              </n-popover>
            </div>
            <TaskStateDrawer :plan="taskPlan" />
            <AgentComposer ref="composer" :draft="draft" :ui="ui" :profile="selectedProfile" :profiles="ui?.profiles || []" :effort="effort" :meter="summary?.context_meter" :metrics="conversationMetrics" :busy="busy" :cancelling="!!state?.cancelling" :can-stop="canControl && !!state?.ready && !state?.cancelling" :ready="ready" :has-workspace="true" :agent="selectedAgent" :agents="ui?.agents || []" :permission-tier="sessionTier" @effort="setEffort" @submit="submit" @stop="stop" @retry="retry" @model="selectProfile" @agent="selectAgent" @request-workspace="handleRequestWorkspace" @update-permission-tier="handleTierChange"/>
          </div>
          <!-- 空状态时的提示词卡片（位于输入框下方，点击填充草稿） -->
          <div v-if="!rows.length" class="loop-empty-prompts">
            <button
              v-for="prompt in prompts"
              :key="prompt"
              class="empty-prompt-card"
              type="button"
              @click="fill(prompt)"
            >
              <span class="prompt-text">{{ prompt }}</span>
              <span class="prompt-arrow">↗</span>
            </button>
          </div>
          <div class="loop-width-edge loop-width-edge-left" @pointerenter="previewContentResize('left', $event)" @pointermove="moveContentResizePreview('left', $event)" @pointerleave="hideContentResizePreview('left')">
            <button class="loop-width-handle" :class="{ 'is-visible': hoverResizeEdge === 'left' || (isResizing && resizeEdge === 'left'), 'is-active': isResizing && resizeEdge === 'left' }" :style="resizeHandleStyle('left')" type="button" aria-label="向左拖拽调整对话内容宽度" aria-orientation="vertical" role="separator" :aria-valuemin="minimumChatWidth" :aria-valuemax="maximumChatWidth" :aria-valuenow="Math.round(renderedChatWidth)" @pointerdown="beginContentResize($event, 'left')" @keydown="adjustContentWidthByKey($event, 'left')">
              <span aria-hidden="true"></span>
            </button>
          </div>
          <div class="loop-width-edge loop-width-edge-right" @pointerenter="previewContentResize('right', $event)" @pointermove="moveContentResizePreview('right', $event)" @pointerleave="hideContentResizePreview('right')">
            <button class="loop-width-handle" :class="{ 'is-visible': hoverResizeEdge === 'right' || (isResizing && resizeEdge === 'right'), 'is-active': isResizing && resizeEdge === 'right' }" :style="resizeHandleStyle('right')" type="button" aria-label="向右拖拽调整对话内容宽度" aria-orientation="vertical" role="separator" :aria-valuemin="minimumChatWidth" :aria-valuemax="maximumChatWidth" :aria-valuenow="Math.round(renderedChatWidth)" @pointerdown="beginContentResize($event, 'right')" @keydown="adjustContentWidthByKey($event, 'right')">
              <span aria-hidden="true"></span>
            </button>
          </div>
        </section>
        <TraceWorkspace v-else-if="state && trace" :state="state" :trace="trace"/>
        <button v-if="!atBottom && tab==='chat'" class="jump-bottom" @click="scrollBottom">↓ 回到最新</button>
      </div>
      <aside v-if="runtimeOpen" class="loop-runtime"><button class="runtime-close" @click="runtimeOpen=false">关闭</button><h3>当前运行</h3><p>{{ status }}</p><dl><dt>会话</dt><dd>{{ sessionId || '未发送的草稿' }}</dd><dt>实际模型</dt><dd>{{ summary?.model || '尚无实际请求' }}</dd><dt>思考档位</dt><dd>{{ summary?.reasoning_effort || '未知' }}</dd><dt>协议档版本</dt><dd>{{ summary?.profile_version || '未知' }}</dd><dt>最近活动</dt><dd v-for="event in state?.facts.slice(-5) || []" :key="event.cursor">{{ event.type }}</dd></dl><h4 v-if="tasks.length">Worker 任务</h4><div v-for="task in tasks" :key="task.key"><router-link :to="'/tasks'">{{ task.key }}</router-link><p>{{ task.status || '等待状态' }}</p><p v-if="task.progress">{{ JSON.stringify(task.progress) }}</p><router-link v-if="task.report_id" :to="`/reports/${task.report_id}`">查看报告</router-link></div><p v-for="execution in quarantined" :key="execution.key" class="loop-notice">执行范围受限 · {{ execution.reason || '等待对账' }}</p></aside>
    </div>
    <div v-if="tab==='trace'" class="loop-composer-wrap loop-trace-composer">
      <div class="composer-top-bar">
        <button
          type="button"
          class="composer-ws-btn"
          :class="{ 'has-ws': !!activeWorkspaceId, 'is-draft': !sessionId }"
          :title="activeWorkspaceId ? `当前绑定工作区：${activeWorkspaceName}` : '点击选择或新建沙箱工作区（可选）'"
          @click="handleOpenWorkspacePopover"
        >
          <span class="ws-btn-folder-icon" aria-hidden="true">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">
              <path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"></path>
            </svg>
          </span>
          <span class="ws-btn-name">{{ activeWorkspaceId ? activeWorkspaceName : '绑定工作区' }}</span>
          <span class="ws-btn-arrow" aria-hidden="true">
            <svg width="10" height="10" viewBox="0 0 12 12" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round">
              <path d="M3 4.5l3 3 3-3" />
            </svg>
          </span>
        </button>
      </div>
      <TaskStateDrawer :plan="taskPlan" />
      <AgentComposer ref="composer" :draft="draft" :ui="ui" :profile="selectedProfile" :profiles="ui?.profiles || []" :effort="effort" :meter="summary?.context_meter" :metrics="conversationMetrics" :busy="busy" :cancelling="!!state?.cancelling" :can-stop="canControl && !!state?.ready && !state?.cancelling" :ready="ready" :has-workspace="true" :agent="selectedAgent" :agents="ui?.agents || []" :permission-tier="sessionTier" @effort="setEffort" @submit="submit" @stop="stop" @retry="retry" @model="selectProfile" @agent="selectAgent" @request-workspace="handleRequestWorkspace" @update-permission-tier="handleTierChange"/>
    </div>
    <!-- 页面最底部指标栏：只有开始对话后（rows.length > 0）且有 conversationMetrics 时显示 -->
    <footer v-if="rows.length && conversationMetrics" class="conversation-metrics loop-bottom-metrics" aria-label="会话模型总用量指标">
      <span title="全会话平均 Token 生成速度">
        <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
          <path d="m12 14 4-4"/>
          <path d="M3.34 19a10 10 0 1 1 17.32 0"/>
        </svg>
        生成token速度 {{ formatSpeed(conversationMetrics.outputTokensPerSecond) }}
      </span>
      <span title="全会话 Prompt 缓存命中率">
        <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
          <ellipse cx="12" cy="5" rx="9" ry="3"/>
          <path d="M3 5v14c0 1.66 4 3 9 3s9-1.34 9-3V5"/>
          <path d="M3 12c0 1.66 4 3 9 3s9-1.34 9-3"/>
        </svg>
        缓存命中率 {{ formatRate(conversationMetrics.cacheHitRate) }}
      </span>
      <span title="全会话累计输入与输出 Token 统计">
        <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
          <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"></path>
          <polyline points="14 2 14 8 20 8"></polyline>
          <line x1="16" y1="13" x2="8" y2="13"></line>
          <line x1="16" y1="17" x2="8" y2="17"></line>
        </svg>
        输入 {{ formatTokens(conversationMetrics.inputTokens) }} · 输出 {{ formatTokens(conversationMetrics.outputTokens) }}
      </span>
    </footer>
  </div>
</template>
<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, ref, watch } from 'vue'
import { NIcon, NPopover, useMessage } from 'naive-ui'
import BackwardIcon from 'naive-ui/es/_internal/icons/Backward'
import FileIcon from 'naive-ui/es/_internal/icons/File'
import RetryIcon from 'naive-ui/es/_internal/icons/Retry'
import TimeIcon from 'naive-ui/es/_internal/icons/Time'
import http, { ApiError, api } from '../../../api/http'
import { createRequestId } from '../../../utils/requestId'
import type { AttachmentReference, AgentSession } from '../../../api/types'
import type { ConversationMetrics, Data, Effort, InteractionRecord, LoopAgent, LoopProfile, LoopRecord, LoopUi, TaskPlanDisplay, ToolRun } from '../../../api/agentLoopTypes'
import { conversationRows, identity } from '../../../agent/loop/reducer'
import type { LoopStore } from '../../../agent/loop/store'
import { useAuthStore } from '../../../stores/auth'
import { getModelLogoKey } from '../../../utils/providerLogo'
import { copyText } from '../../../utils/clipboard'
import ProviderLogo from '../../ProviderLogo.vue'
import MarkdownView from '../MarkdownView.vue'
import AttachmentPreview from '../AttachmentPreview.vue'
import AgentComposer from './AgentComposer.vue'
import TaskStateDrawer from './TaskStateDrawer.vue'
import ToolRunCard from './ToolRunCard.vue'
import TaskRunCard from './TaskRunCard.vue'
import ReasoningBlock from './ReasoningBlock.vue'
import TraceWorkspace from './TraceWorkspace.vue'
import { isTaskTool, taskCardSnapshot } from '../../../agent/loop/taskPresentation'
import { calculateTurnSummaries, formatDuration, formatTokens, tokenValue, type TurnSummary } from '../../../agent/loop/turnSummary'
import { assistantKeysByTurn, conversationMetricsFrom, firstAssistantInTurn, pickAgent, pickProfile } from '../../../agent/loop/workspaceDerived'

const props = withDefaults(
  defineProps<{
    sessionId: string
    session?: AgentSession | null
    store: LoopStore
    createSession: (workspaceId?: string, preparedTicket?: Promise<string>, permissionTier?: string, initialTitle?: string) => Promise<string>
  }>(),
  {
    session: null
  }
)
const auth = useAuthStore(), tab = ref('chat')
const message = useMessage()
const workspaces = ref<Array<{ id: string; name: string }>>([])
const loadingWorkspaces = ref(false)
const workspacePopoverOpen = ref(false)
const workspacePopoverEpoch = ref(0)
const workspacePopoverRef = ref<{ syncPosition: () => void } | null>(null)
const draftWorkspaceId = ref<string | null>(null)
const draftWorkspaceName = ref<string>('')
const newWorkspaceName = ref('')
const creatingWorkspace = ref(false)
let workspacePopoverSyncFrame: number | undefined

const sessionTier = ref<string>('')
watch(() => props.session?.permission_tier, (value) => { sessionTier.value = value || '' }, { immediate: true })
async function handleTierChange(value: string) {
  sessionTier.value = value || ''
  if (!props.sessionId) return
  const tier = (value || null) as 'tier1' | 'tier2' | 'tier3' | null
  try {
    await api.sessions.updatePermissionTier(props.sessionId, tier)
    message.success('本会话权限档位已更新')
  } catch (err: any) {
    message.error(err?.message || '权限档位更新失败')
  }
}

const activeWorkspaceId = computed<string | null>(() => {
  if (props.sessionId) {
    return props.session?.workspace_id || null
  }
  return draftWorkspaceId.value
})

const activeWorkspaceName = computed<string>(() => {
  if (props.sessionId) {
    return props.session?.workspace_name || (props.session?.workspace_id ? '工作区' : '')
  }
  return draftWorkspaceName.value || (draftWorkspaceId.value ? '工作区' : '')
})

const hasWorkspace = computed<boolean>(() => {
  if (props.sessionId) return true
  return !!activeWorkspaceId.value
})

async function loadWorkspaces(autoSelect = true) {
  if (loadingWorkspaces.value) return
  loadingWorkspaces.value = true
  try {
    const payload = await api.workspaces.list()
    const items = Array.isArray(payload) ? payload : (payload as any)?.items || []
    workspaces.value = items.map((item: any) => ({
      id: String(item.id),
      name: String(item.name)
    }))
    if (!props.sessionId && !draftWorkspaceId.value && workspaces.value.length > 0 && autoSelect) {
      const savedWsId = localPreference('last-workspace')
      if (savedWsId) {
        const matched = workspaces.value.find(ws => ws.id === savedWsId)
        if (matched) {
          draftWorkspaceId.value = matched.id
          draftWorkspaceName.value = matched.name
        }
      }
    }
  } catch {
    // 忽略加载异常
  } finally {
    loadingWorkspaces.value = false
  }
}

function handleOpenWorkspacePopover() {
  handleWorkspacePopoverVisibility(!workspacePopoverOpen.value)
}

/** 统一由 Naive Popover 回调驱动开关，避免点击触发器时被双重翻转。 */
function handleWorkspacePopoverVisibility(open: boolean) {
  workspacePopoverOpen.value = open
  if (open) {
    workspacePopoverEpoch.value += 1
    syncWorkspacePopoverDuringEntrance()
  } else if (workspacePopoverSyncFrame !== undefined) {
    cancelAnimationFrame(workspacePopoverSyncFrame)
    workspacePopoverSyncFrame = undefined
  }
  if (open && !workspaces.value.length) {
    void loadWorkspaces(false)
  }
}

/** 顶栏扩展会推动触发器上移；逐帧同步浮层，避免浮层与“147”脱节。 */
function syncWorkspacePopoverDuringEntrance() {
  if (workspacePopoverSyncFrame !== undefined) cancelAnimationFrame(workspacePopoverSyncFrame)
  void nextTick(() => {
    if (!workspacePopoverOpen.value) return
    const startedAt = performance.now()
    const sync = (now: number) => {
      workspacePopoverRef.value?.syncPosition()
      if (workspacePopoverOpen.value && now - startedAt < 380) {
        workspacePopoverSyncFrame = requestAnimationFrame(sync)
      } else {
        workspacePopoverSyncFrame = undefined
      }
    }
    workspacePopoverRef.value?.syncPosition()
    workspacePopoverSyncFrame = requestAnimationFrame(sync)
  })
}

function handleSelectWorkspace(ws: { id: string; name: string } | null) {
  if (props.sessionId) {
    workspacePopoverOpen.value = false
    return
  }
  if (!ws) {
    draftWorkspaceId.value = null
    draftWorkspaceName.value = ''
    try { localStorage.removeItem(`last-workspace:${auth.user?.id}`) } catch { /* 忽略 */ }
    workspacePopoverOpen.value = false
    return
  }
  draftWorkspaceId.value = ws.id
  draftWorkspaceName.value = ws.name
  try { localStorage.setItem(`last-workspace:${auth.user?.id}`, ws.id) } catch { /* 忽略 */ }
  workspacePopoverOpen.value = false
}

async function handleCreateWorkspace() {
  const name = newWorkspaceName.value.trim()
  if (!name || creatingWorkspace.value || props.sessionId) return
  creatingWorkspace.value = true
  try {
    const created = await api.workspaces.create(name)
    const newWs = { id: String(created.id), name: String(created.name) }
    workspaces.value.unshift(newWs)
    draftWorkspaceId.value = newWs.id
    draftWorkspaceName.value = newWs.name
    try { localStorage.setItem(`last-workspace:${auth.user?.id}`, newWs.id) } catch { /* 忽略 */ }
    newWorkspaceName.value = ''
    workspacePopoverOpen.value = false
    message.success('工作区已创建并选中')
  } catch (err: any) {
    message.error(err?.message || '创建工作区失败')
  } finally {
    creatingWorkspace.value = false
  }
}

function handleRequestWorkspace() {
  handleWorkspacePopoverVisibility(true)
}
const runtimeOpen = ref(false), error = ref(''), effort = ref<Effort | null>(null)
const ui = ref<LoopUi | null>(null), selectedProfileId = ref(''), selectedAgentId = ref(''), shown = ref(80), attachments = ref<Record<string, AttachmentReference[]>>({})
const composer = ref<InstanceType<typeof AgentComposer>>(), scroller = ref<HTMLElement>(), chatShell = ref<HTMLElement>(), atBottom = ref(true)
type ResizeEdge = 'left' | 'right'
const chatWidth = ref<number | null>(null), isResizing = ref(false), resizeEdge = ref<ResizeEdge | null>(null), hoverResizeEdge = ref<ResizeEdge | null>(null)
const resizeHandleOffsets = ref<Record<ResizeEdge, number>>({ left: 110, right: 110 })
const minimumChatWidth = 520
const chatWidthStorageKey = 'agent-loop:chat-shell-width:v3'
const state = computed(() => props.store.sessions[props.sessionId]), trace = computed(() => props.store.traces[props.sessionId])
const draft = computed(() => props.store.draft(props.sessionId || 'draft'))
const rows = computed(() => state.value ? conversationRows(state.value) : [])
const visibleRows = computed(() => rows.value.slice(-shown.value))
/** 只读取 task_plan.updated 的会话快照；工具调用草稿与失败结果不能改变抽屉。 */
const taskPlan = computed<TaskPlanDisplay | null>(() => state.value?.taskPlan || null)

/** 轮次分组与首条判定抽离到 workspaceDerived（纯函数可单测）；此处仅保留 computed 缓存。 */
const firstAssistantKeyByTurn = computed<Map<string, string>>(() => assistantKeysByTurn(rows.value))

function isFirstAssistantInTurn(row: LoopRecord): boolean {
  return firstAssistantInTurn(row, firstAssistantKeyByTurn.value)
}

const busy = computed(() => !!state.value?.activeTurn)
/** 草稿协议档可独立于平台默认项选择；后端在提交时再次校验。 */
const selectedProfile = computed<LoopProfile | null>(() => pickProfile(ui.value, selectedProfileId.value))
/** 草稿专家可独立选择；后端按会话最近一轮记忆并在提交时复核（未知 ID 回落默认专家）。 */
const selectedAgent = computed<LoopAgent | null>(() => pickAgent(ui.value, selectedAgentId.value))
const ready = computed(() => !!selectedProfile.value && !!effort.value && (props.sessionId ? !!state.value?.ready : !!ui.value?.enabled))
const canControl = computed(() => !!state.value?.controlled && !!ui.value?.permissions.interactions)
const summary = computed(() => Object.values(state.value?.attempts || {}).sort((a,b)=>b.first_cursor-a.first_cursor)[0]?.request_summary)
/** 仅聚合已提交的上游 usage；缺字段代表上游未返回，不能当作零或自行估算。 */
const conversationMetrics = computed<ConversationMetrics>(() => conversationMetricsFrom(state.value?.attempts))
const tasks = computed(() => Object.values(state.value?.tasks || {}))
/** 从脱敏参数/结果解析 task_id，再关联实时 Worker 事实，不能靠工具名称猜测任务。 */
function taskForTool(tool: ToolRun): LoopRecord | null {
  const taskId = taskCardSnapshot(tool, null).taskId
  return taskId ? state.value?.tasks[taskId] || null : null
}
const quarantined = computed(() => Object.values(state.value?.executions || {}).filter(e => e.event === 'execution.quarantined'))
const finishLabels: Record<string,string> = { max_tokens:'达到输出上限，本轮已结束', max_steps:'达到步骤上限，本轮已结束', cancelled:'本轮已取消', interrupted:'本轮已中断', error:'本轮失败，请查看错误信息' }
const phaseLabels: Record<string,string> = { idle:'就绪',model:'模型处理中',thinking:'正在思考',answering:'正在回答',tools:'工具执行中',waiting_interaction:'等待交互',retry_wait:'等待重试',completed:'已完成',...finishLabels }
const status = computed(() => state.value?.cancelling ? '取消中' : state.value && state.value.connection !== 'online' ? '连接待同步' : phaseLabels[state.value?.phase || 'idle'] || state.value?.phase || '就绪')
const prompts = ['查看工作区文件，说明可以如何处理', '帮我准备一次模型基准评测', '查询资料并给出可核对的来源']
const chatShellStyle = computed(() => chatWidth.value ? { width: `${chatWidth.value}px` } : undefined)
const maximumChatWidth = computed(() => Math.max(minimumChatWidth, (chatShell.value?.parentElement?.clientWidth || minimumChatWidth + 48) - 48))
const renderedChatWidth = computed(() => chatWidth.value || chatShell.value?.getBoundingClientRect().width || minimumChatWidth)
let epoch = 0
let resizeStartX = 0, resizeStartWidth = 0
const resizeHandleHeight = 100
/** 能力随会话/窗口聚焦刷新；活动请求显示自己的持久配置版本。 */
async function refreshUi() {
  const current = ++epoch, sid = props.sessionId
  try {
    const { data } = await http.get<LoopUi>(sid ? `/api/sessions/${sid}/agent-ui` : '/api/sessions/agent-ui')
    if (current !== epoch) return
    ui.value = data
    const savedProfileId = localPreference('agent-profile')
    const profile = data.profiles.find(item => item.id === selectedProfileId.value)
      || data.profiles.find(item => item.id === savedProfileId)
      || data.profile
      || null
    selectedProfileId.value = profile?.id || ''
    restoreEffort(profile)
    // 专家优先沿用会话记忆（data.agent 由后端按最近一轮解析），草稿回落本地偏好与默认专家。
    const savedAgentId = localPreference('agent-expert')
    const agentList = data.agents || []
    const agent = agentList.find(item => item.id === selectedAgentId.value)
      || agentList.find(item => item.id === data.agent)
      || agentList.find(item => item.id === savedAgentId)
      || agentList.find(item => item.default)
      || null
    selectedAgentId.value = agent?.id || ''
    if (!data.permissions.reasoning && state.value) { for (const a of Object.values(state.value.attempts)) { a.reasoning = ''; delete a.reasoning_preview }; for (const event of state.value.facts) delete event.data.reasoning_preview }
    if (trace.value) {
      trace.value.denied = !data.permissions.trace
      if (!data.permissions.trace) { trace.value.events = []; trace.value.seen.clear(); trace.value.seq = -1; trace.value.catalog = null }
    }
    if (!data.permissions.interactions && state.value) for (const i of Object.values(state.value.interactions)) { delete i.nonce; delete i.spec_hash; i.restricted = true }
  } catch { if (current === epoch) { ui.value = null; error.value = '读取会话能力失败，请确认权限和服务状态' } }
}
/** 本地偏好只保存协议档 ID 和思考档位，不保存 API 端点、凭据或服务端配置。 */
function localPreference(key: string) { try { return localStorage.getItem(`${key}:${auth.user?.id}`) } catch { return null } }
function effortPreferenceKey(profile: LoopProfile) { return `agent-effort:${auth.user?.id}:${profile.id}:${profile.version}` }
let effortProfileKey = ''
function restoreEffort(profile: LoopProfile | null) {
  if (!profile) { effort.value = null; return }
  let saved: string | null = null
  try { saved = localStorage.getItem(effortPreferenceKey(profile)) } catch { /* 隐私模式下保留内存偏好。 */ }
  // 首次切到另一个供应商使用该模型默认值，避免普通模型的 off 覆盖 Claude 默认开启。
  const key = effortPreferenceKey(profile)
  const previous = saved || (effortProfileKey === key ? effort.value : null)
  effortProfileKey = key
  effort.value = previous && profile.allowed_efforts.includes(previous as Effort) ? previous as Effort : profile.default_effort
  if (previous && previous !== effort.value) error.value = '当前协议档不支持原思考档位，已恢复默认值'
}
function setEffort(value: Effort) {
  effort.value = value
  const profile = selectedProfile.value
  if (profile) try { localStorage.setItem(effortPreferenceKey(profile), value) } catch { /* 本地存储不可用不影响发送。 */ }
}
/** 切换只影响下一轮；已经发出的 attempt 永远读取其持久 request_summary。 */
function selectProfile(id: string) {
  const profile = ui.value?.profiles.find(item => item.id === id)
  if (!profile) return
  selectedProfileId.value = profile.id
  try { localStorage.setItem(`agent-profile:${auth.user?.id}`, profile.id) } catch { /* 本地存储不可用不影响发送。 */ }
  restoreEffort(profile)
}
/** 专家切换同样只影响下一轮；会话内选择由后端按最近一轮记忆，本地仅作草稿偏好。 */
function selectAgent(id: string) {
  const agent = ui.value?.agents.find(item => item.id === id)
  if (!agent) return
  selectedAgentId.value = agent.id
  try { localStorage.setItem(`agent-expert:${auth.user?.id}`, agent.id) } catch { /* 本地存储不可用不影响发送。 */ }
}
watch(() => props.sessionId, (newSid) => { ui.value = null; attachments.value = {}; shown.value = 80; tab.value='chat'; if (props.sessionId) props.store.open(props.sessionId); void refreshUi(); if (!newSid) void loadWorkspaces(true) }, { immediate: true })
// 轨迹订阅属于当前可见面板；切会话/卸载仅退订诊断，不关闭执行中的控制连接。
watch([tab, () => props.sessionId, () => ui.value?.permissions.trace], ([view, sid, permitted], _, cleanup) => {
  if (!sid || view !== 'trace' || !permitted) return
  const client = props.store.clients.get(sid)
  client?.trace(true, props.store.traces[sid]?.seq ?? -1)
  cleanup(() => client?.trace(false))
})
watch(() => state.value?.cursor, () => { if (atBottom.value) void nextTick(scrollBottom); void hydrateAttachments() })
const refreshTimer = setInterval(() => { if (document.visibilityState === 'visible') void refreshUi() }, 30000)
window.addEventListener('focus', refreshUi)
try {
  const savedWidth = Number(localStorage.getItem(chatWidthStorageKey))
  if (Number.isFinite(savedWidth) && savedWidth >= minimumChatWidth) chatWidth.value = savedWidth
} catch { /* 本地存储不可用时使用默认宽度。 */ }
onBeforeUnmount(() => { epoch++; clearInterval(refreshTimer); if (workspacePopoverSyncFrame !== undefined) cancelAnimationFrame(workspacePopoverSyncFrame); window.removeEventListener('focus', refreshUi); finishContentResize() })
function interactions(row: LoopRecord) { return Object.values(state.value?.interactions || {}).filter(i => identity({session_id:props.sessionId,correlation:i.correlation},true) === row.key) }
function fill(text: string) { draft.value.content = text; composer.value?.focus() }
function trackScroll() { const el=scroller.value; if(el) atBottom.value=el.scrollHeight-el.scrollTop-el.clientHeight<100 }
function scrollBottom() { const el=scroller.value; if(el) el.scrollTop=el.scrollHeight; atBottom.value=true }
/** 将固定高度的边缘阴影线定位到鼠标所在的纵向位置。 */
function updateResizeHandleOffset(edge: ResizeEdge, event: PointerEvent) {
  const rect = chatShell.value?.getBoundingClientRect()
  if (!rect) return
  resizeHandleOffsets.value[edge] = Math.min(Math.max(0, event.clientY - rect.top - resizeHandleHeight / 2), Math.max(0, rect.height - resizeHandleHeight))
}
/** 仅当鼠标进入左右边缘命中区时，显示随鼠标纵向移动的细玻璃阴影线。 */
function previewContentResize(edge: ResizeEdge, event: PointerEvent) {
  if (event.pointerType === 'touch' || isResizing.value) return
  hoverResizeEdge.value = edge
  updateResizeHandleOffset(edge, event)
}
function moveContentResizePreview(edge: ResizeEdge, event: PointerEvent) {
  if (event.pointerType === 'touch' || isResizing.value || hoverResizeEdge.value !== edge) return
  updateResizeHandleOffset(edge, event)
}
function hideContentResizePreview(edge: ResizeEdge) {
  if (!isResizing.value && hoverResizeEdge.value === edge) hoverResizeEdge.value = null
}
function resizeHandleStyle(edge: ResizeEdge) { return { top: `${resizeHandleOffsets.value[edge]}px` } }
/** 两侧边缘都可拖拽；外扩和内收只改变宽度，壳层始终保持页面居中。 */
function beginContentResize(event: PointerEvent, edge: ResizeEdge) {
  if (event.pointerType === 'touch' || !chatShell.value) return
  event.preventDefault()
  resizeEdge.value = edge
  hoverResizeEdge.value = edge
  updateResizeHandleOffset(edge, event)
  resizeStartX = event.clientX
  resizeStartWidth = chatShell.value.getBoundingClientRect().width
  chatWidth.value = resizeStartWidth
  isResizing.value = true
  window.addEventListener('pointermove', resizeContent)
  window.addEventListener('pointerup', finishContentResize, { once: true })
}
function resizeContent(event: PointerEvent) {
  const upper = maximumChatWidth.value
  const direction = resizeEdge.value === 'right' ? 1 : -1
  chatWidth.value = Math.min(upper, Math.max(minimumChatWidth, resizeStartWidth + direction * (event.clientX - resizeStartX)))
  if (resizeEdge.value) updateResizeHandleOffset(resizeEdge.value, event)
}
function finishContentResize() {
  if (!isResizing.value) return
  isResizing.value = false
  resizeEdge.value = null
  hoverResizeEdge.value = null
  window.removeEventListener('pointermove', resizeContent)
  try { if (chatWidth.value) localStorage.setItem(chatWidthStorageKey, String(Math.round(chatWidth.value))) } catch { /* 本地存储失败不影响本次调整。 */ }
}
/** 键盘用户可用方向键从当前侧边缘放大或缩小居中的共享壳层。 */
function adjustContentWidthByKey(event: KeyboardEvent, edge: ResizeEdge) {
  if (event.key !== 'ArrowLeft' && event.key !== 'ArrowRight') return
  event.preventDefault()
  const outward = (edge === 'left' && event.key === 'ArrowLeft') || (edge === 'right' && event.key === 'ArrowRight')
  chatWidth.value = Math.min(maximumChatWidth.value, Math.max(minimumChatWidth, renderedChatWidth.value + (outward ? 24 : -24)))
  try { localStorage.setItem(chatWidthStorageKey, String(Math.round(chatWidth.value))) } catch { /* 本地存储失败不影响本次调整。 */ }
}
/** 使用兼容复制方案，HTTP 或受限浏览器仍可复制已生成回答。 */
async function copy(text: string) {
  if (!text) return
  if (await copyText(text)) {
    message.success('已复制回答到剪贴板')
  } else {
    error.value = '复制失败，请检查浏览器剪贴板权限'
  }
}
function formatSpeed(value: number | null): string {
  return value === null ? '—' : `${formatTokens(value)}/s`
}
function formatRate(value: number | null): string {
  return value === null ? '—' : `${value.toFixed(value >= 10 ? 0 : 1)}%`
}
/** tokenValue / formatTokens / formatDuration 与 turnSummary 同源（顶部导入），消除双份实现。 */
function formatTimestamp(value?: string): string {
  if (!value) return ''
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return ''
  return new Intl.DateTimeFormat('zh-CN', { year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false }).format(date)
}
/** 引用只写入下一轮草稿，供模型参考；不会伪造为服务端持久记忆。 */
function quoteMemory(text: string) {
  if (!text) return
  const quote = `[引用对话记忆]\n${text}\n[/引用对话记忆]`
  draft.value.content = draft.value.content.trim() ? `${draft.value.content}\n\n${quote}` : quote
  composer.value?.focus()
  message.success('已引用到输入框')
}
function originalUserMessage(row: LoopRecord): LoopRecord | undefined {
  return rows.value.filter(item => item.role === 'user').reverse().find(item =>
    (row.correlation.turn_id && item.correlation.turn_id === row.correlation.turn_id)
    || (row.correlation.turn !== undefined && item.correlation.turn === row.correlation.turn),
  )
}
/** 重新生成复用该回答所属的原用户内容与附件引用，仍走新的幂等提交命令。 */
function regenerate(row: LoopRecord) {
  const source = originalUserMessage(row)
  if (!source?.content) { error.value = '未找到可重新生成的原始对话'; return }
  const refs = Array.isArray(source.attachment_refs) ? source.attachment_refs.map(item => typeof item === 'string' ? item : item?.file_id).filter((item): item is string => typeof item === 'string') : []
  void submit({ content: String(source.content), attachmentRefs: refs })
}

/** 每轮对话聚合后的操作与统计信息，仅在轮次到达结尾时挂载在轮次最后一行展示。 */
const turnSummaryByLastRowKey = computed<Map<string, TurnSummary>>(() =>
  calculateTurnSummaries(rows.value, {
    activeTurnId: state.value?.activeTurn,
    isBusy: busy.value,
    sessionId: props.sessionId,
  }),
)
function formatSessionTitle(rawText: string): string {
  if (!rawText) return '新会话'
  let cleaned = rawText.trim()
  // 剥除 [引用对话记忆] ... [/引用对话记忆]
  cleaned = cleaned.replace(/\[引用对话记忆\][\s\S]*?\[\/引用对话记忆\]/g, '').trim()
  // 剥除其他 [引用...] 标签
  cleaned = cleaned.replace(/^\[[^\]]+\]\s*/g, '').trim()
  // 剥除 markdown 标题符 # 或列表符 * -
  cleaned = cleaned.replace(/^[#*\-\s]+/g, '').trim()
  // 压缩连续空白
  cleaned = cleaned.replace(/\s+/g, ' ')
  // 剥离首尾引号
  cleaned = cleaned.replace(/^["'“”‘’]+|["'“”‘’]+$/g, '')
  if (!cleaned) return '新会话'
  return cleaned.slice(0, 24)
}

/** 冻结输入/附件/effort 与幂等 ID；未受理时保留可恢复草稿。 */
async function submit(override?: { content: string; attachmentRefs: string[] }) {
  if (!ready.value || busy.value || draft.value.submitting) return
  const source = draft.value, selectedEffort=effort.value, profile=selectedProfile.value
  if (!selectedEffort || !profile) return
  source.submitting = true; error.value = ''
  if (state.value) state.value.error = ''
  const content=override?.content ?? source.content, refs=override?.attachmentRefs ?? source.files.filter(f=>!f.removed && f.id).map(f=>f.id!)
  try {
    let sid=props.sessionId
    // 短票与 REST 建会没有依赖关系，先并行领取可缩短新会话的首次发送等待。
    let preparedTicket: Promise<string> | undefined
    if(!sid) {
      preparedTicket=api.auth.getWsTicket().then(({ticket})=>ticket)
      // 建会失败时仍消费此 Promise 的拒绝，避免后台短票请求产生未处理异常。
      void preparedTicket.catch(()=>undefined)
      const initialTitle = formatSessionTitle(content)
      sid=await props.createSession(activeWorkspaceId.value || undefined, preparedTicket, sessionTier.value || undefined, initialTitle)
      if(!sid) throw new Error()
      props.store.drafts[sid]=source
      delete props.store.drafts.draft
    } else if (props.session && (!props.session.title || props.session.title === '新会话')) {
      const newTitle = formatSessionTitle(content)
      if (newTitle && newTitle !== '新会话') {
        props.session.title = newTitle
        void api.sessions.updateTitle(sid, newTitle).catch(() => {})
      }
    }
    const client=props.store.open(sid, preparedTicket)
    source.pending ??= client.command('turn.submit',{client_message_id:createRequestId(),content,attachment_refs:refs,profile_id:profile.id,reasoning_effort:selectedEffort,agent_id:selectedAgent.value?.id})
    // 只有首次订阅完成后才发送；超时取消等待，不能在以后重连时偷偷补发。
    if (!props.store.sessions[sid].ready) await new Promise<void>((resolve, reject) => {
      const unwatch = watch(() => props.store.sessions[sid]?.ready, ok => {
        if (ok) { clearTimeout(timer); unwatch(); resolve() }
      })
      const timer = setTimeout(() => { unwatch(); reject(new Error('连接超时')) }, 15000)
    })
    if (!client.send(source.pending)) throw new Error('连接中断')
    props.store.sessions[sid].controlled = true
  } catch (exc) {
    source.submitting = false
    error.value = exc instanceof ApiError ? `${exc.message}，草稿已保留`
      : source.pending ? '消息尚未确认发送，请连接恢复后使用原请求 ID 重发，草稿已保留'
      : '无法创建或发送会话，草稿已保留'
  }
}
/** 重试保留原请求及正文，只有实际写入 socket 才显示发送中。 */
function retry() {
  if (draft.value.pending && state.value?.ready && props.store.send(props.sessionId, draft.value.pending)) {
    draft.value.submitting = true; error.value = ''; state.value.error = ''
  }
}
function stop() { if(!canControl.value || !state.value?.activeTurn) return; const client=props.store.clients.get(props.sessionId)!; const command=client.command('turn.cancel',{turn_id:state.value.activeTurn}); if(client.send(command)) { state.value.cancelling=true; draft.value.cancelRequestId=command.request_id } }
function respond(interaction: InteractionRecord, values: Data) {
  if(!canControl.value || !state.value?.ready || interaction.submitting) return
  const c=interaction.correlation
  const data={interaction_id:interaction.interaction_id,turn_id:c.turn_id,turn:c.turn,attempt_id:c.attempt_id,call_id:c.call_id,nonce:interaction.nonce,...values,...(interaction.kind==='task_confirmation'?{spec_hash:interaction.spec_hash}:{})}
  const client=props.store.clients.get(props.sessionId)!, command=client.command(`${interaction.kind}.respond`,data)
  if(client.send(command)){interaction.submitting=true;draft.value.pending=command;draft.value.pendingInteraction=interaction.key}
}
/** 文件元数据只取授权接口，不信任历史里的任意 URL。 */
async function hydrateAttachments() {
  const sid=props.sessionId
  for(const row of rows.value.filter(r=>r.role==='user' && r.attachment_refs?.length)){
    if(attachments.value[row.key])continue
    attachments.value[row.key]=[]
    const values=await Promise.all((row.attachment_refs as any[]).map(async item=>{const id=typeof item==='string'?item:item.file_id;try{const {data}=await http.get(`/api/files/${encodeURIComponent(id)}`);return {file_id:id,filename:data.filename,size:data.size,content_type:data.content_type,content_url:`/api/files/${encodeURIComponent(id)}/content`} as AttachmentReference}catch{return null}}))
    if(sid===props.sessionId)attachments.value[row.key]=values.filter((v):v is AttachmentReference=>v!==null)
  }
}
</script>
<style>
.loop-control{background:transparent;color:inherit;border:1px solid transparent;border-radius:7px;padding:7px 9px;font-size:12px;cursor:pointer}.loop-control:hover{background:#eaf3ee}.loop-primary{background:#174a3a!important;color:#fff!important}.loop-workspace button:focus-visible,.loop-workspace input:focus-visible,.loop-workspace summary:focus-visible{outline:2px solid #16977a;outline-offset:2px}
</style>
<style scoped>
.loop-workspace{display:flex;flex:1;flex-direction:column;min-height:0;min-width:0;background:var(--bg-main,#f8faf8)}.loop-tabs{display:flex;align-items:center;gap:8px;padding:8px 20px;border-bottom:1px solid #e0e8e2}.loop-tabs button{padding:7px 12px;border:0;border-radius:7px;background:transparent;color:#61776a;cursor:pointer}.loop-tabs .active{background:#e2eee6;color:#154834}.loop-status{margin-left:auto;font-size:12px;display:flex;align-items:center;gap:6px}.loop-status i{width:7px;height:7px;border-radius:50%;background:#93a99c}.loop-status .running{background:#21a37e;animation:pulse 1.5s ease-in-out infinite}.loop-content{display:flex;flex:1;min-height:0;position:relative}.loop-center{display:flex;flex-direction:column;flex:1;min-width:0;position:relative;min-height:0}.loop-conversation{overflow:auto;flex:1;padding:24px max(20px,calc((100% - 800px)/2));scrollbar-gutter:stable}.loop-message{margin:0 0 22px;min-width:0;overflow-wrap:anywhere}.loop-message header{display:flex;gap:8px;align-items:center;font-size:13px;font-weight:600;margin-bottom:8px}.loop-message header small{font-weight:400;color:#7b8e82}.assistant-header{display:flex;align-items:center}.assistant-identity{display:flex;min-width:0;align-items:center;gap:8px;flex-wrap:wrap}.assistant-identity strong{font-weight:650}.assistant-identity time{color:#8390a0;font-size:11px;font-weight:400;font-variant-numeric:tabular-nums}.loop-message.assistant.is-continuation{margin-top:12px}.loop-message.user{background:#eaf3ed;padding:16px 20px;border-radius:12px}.loop-message.user p{white-space:pre-wrap;margin:0;line-height:1.7}.history-files{display:flex;gap:8px;flex-wrap:wrap}.loop-composer-wrap{padding:12px 24px 18px;max-width:950px;width:100%;box-sizing:border-box;margin:0 auto}.loop-runtime{width:240px;overflow:auto;padding:18px;border-left:1px solid #e0e8e2;font-size:12px;background:#f5f8f5}.loop-runtime dd{margin:5px 0 14px;overflow-wrap:anywhere}.loop-runtime dt{color:#7d9081}.runtime-close{float:right;border:0;background:transparent;cursor:pointer}.loop-notice{padding:8px 16px;margin:4px 10px;background:#f6f0e2;color:#866934;font-size:12px}.loop-notice.error{color:#a24d43}.loop-notice button,.history-more{border:0;background:transparent;text-decoration:underline;cursor:pointer}.jump-bottom{position:absolute;bottom:10px;right:20px;border:1px solid #caddcf;background:#fff;border-radius:20px;padding:8px 15px;cursor:pointer}.muted{color:#86968b}@keyframes pulse{50%{opacity:.35}}@media(prefers-reduced-motion:reduce){*{animation:none!important;transition:none!important}}@media(max-width:768px){.loop-runtime{position:absolute;inset:0 0 0 auto;max-width:calc(100% - 35px);z-index:30;box-shadow:-20px 0 50px #173e2520}.loop-composer-wrap{padding:8px}.loop-conversation{padding:16px 12px}.loop-tabs{padding:6px;gap:0}.loop-tabs button{padding:7px}.loop-status{font-size:11px}.loop-message header{flex-wrap:wrap}}

/* 每轮对话结尾的统一操作与指标栏 */
.turn-end-toolbar {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-top: 4px;
  margin-bottom: 22px;
  padding: 0 4px;
  color: #7a8797;
  font-size: 11.5px;
  font-variant-numeric: tabular-nums;
  user-select: none;
}
.turn-end-actions {
  display: inline-flex;
  align-items: center;
  gap: 4px;
}
.turn-end-actions .assistant-action {
  display: inline-grid;
  width: 26px;
  height: 26px;
  place-items: center;
  border: 0;
  border-radius: 6px;
  background: transparent;
  color: #758497;
  padding: 0;
  cursor: pointer;
  transition: background-color 0.15s ease, color 0.15s ease;
}
.turn-end-actions .assistant-action:hover:not(:disabled) {
  background: #edf5f1;
  color: #174a3a;
}
.turn-end-actions .assistant-action:disabled {
  cursor: default;
  opacity: 0.35;
}
.turn-end-metrics {
  display: inline-flex;
  align-items: center;
  gap: 12px;
}
.turn-end-metric {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  color: #7a8797;
  font-size: 11.5px;
}
[data-theme='dark'] .turn-end-toolbar,
[data-theme='dark'] .turn-end-metric {
  color: #94a3b8;
}
[data-theme='dark'] .turn-end-actions .assistant-action {
  color: #94a3b8;
}
[data-theme='dark'] .turn-end-actions .assistant-action:hover:not(:disabled) {
  background: rgba(255, 255, 255, 0.08);
  color: #34d399;
}

/* 对话/轨迹导航采用参考页的下划线选中态。 */
.loop-tabs{--line:#e3e8f0;--text:#172033;--subtle:#748197;--accent:#5b5bd6}
    .loop-tabs { display: flex; min-height: 42px; align-items: end; gap: 22px; border-bottom: 1px solid var(--line); padding: 0 28px; background: rgba(255,255,255,.68); }
    .loop-tabs .workspace-tab { position: relative; min-height: 42px; border: 0; background: transparent; padding: 0 1px; color: var(--subtle); font-size: 12px; cursor: pointer; }
    .loop-tabs .workspace-tab::after { position: absolute; right: 0; bottom: -1px; left: 0; height: 2px; content: ""; border-radius: 2px 2px 0 0; background: transparent; }
    .loop-tabs .workspace-tab:hover { color: var(--text); }
    .loop-tabs .workspace-tab.active { color: var(--accent); font-weight: 650; }
    .loop-tabs .workspace-tab.active::after { background: var(--accent); }
    .trace-tab-count { display: inline-grid; min-width: 16px; height: 16px; place-items: center; border-radius: 999px; background: #eef0ff; padding: 0 4px; color: #4d4ebb; font-size: 9px; vertical-align: 1px; }
    .loop-tabs .workspace-tab-hint { margin: 0 0 12px auto; color: #8994a6; font: 10px ui-monospace,SFMono-Regular,Consolas,monospace; letter-spacing: .04em; }


.loop-tabs .workspace-tab{background:transparent}.loop-tabs .workspace-tab:disabled{opacity:.45;cursor:default}

/* 消息区与输入框共用同一宽度壳层，并始终在页面内容区居中。 */
.loop-chat-shell{position:relative;display:flex;flex:1;flex-direction:column;min-height:0;width:min(900px,calc(100% - 48px));max-width:calc(100% - 48px);min-width:520px;margin:0 auto}
.loop-chat-shell .loop-conversation{padding:24px 16px}
.loop-chat-shell .loop-composer-wrap{flex:0 0 auto;width:100%;max-width:none;margin:0;padding:12px 0 18px;box-sizing:border-box}

/* 空状态：居中布局、输入框上方水平居中 Logo + 名字及提示词卡片 */
.loop-chat-shell.is-empty {
  justify-content: center;
  padding: 32px 0 48px;
  overflow-y: auto;
}
.loop-chat-shell.is-empty .loop-conversation.is-empty {
  display: none;
}
.loop-empty-hero {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  text-align: center;
  width: 100%;
  margin-bottom: 24px;
  padding: 0 12px;
}
.hero-brand {
  display: inline-flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 12px;
}
.hero-logo-mark {
  width: 44px;
  height: 44px;
  border-radius: 12px;
  background: linear-gradient(135deg, #1f5947 0%, #154234 100%);
  display: grid;
  place-items: center;
  box-shadow: 0 4px 14px rgba(23, 74, 58, 0.22);
}
.hero-brand-name-wrap {
  display: flex;
  align-items: center;
  gap: 8px;
}
.hero-brand-name {
  font-family: var(--font-display, inherit);
  font-size: 26px;
  font-weight: 750;
  color: #173f30;
  letter-spacing: -0.02em;
}
.hero-brand-badge {
  font-size: 10px;
  font-weight: 700;
  padding: 3px 8px;
  border-radius: 6px;
  background: #e2eee6;
  color: #154834;
  letter-spacing: 0.1em;
}
.hero-tagline {
  font-size: 22px;
  font-weight: 600;
  color: #173f30;
  margin: 0 0 6px;
  line-height: 1.4;
}
.hero-subline {
  font-size: 13.5px;
  color: #697d72;
  margin: 0;
}
.loop-empty-prompts {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 12px;
  width: 100%;
  margin-top: 14px;
  box-sizing: border-box;
}
.empty-prompt-card {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 14px 16px;
  border: 1px solid #d8e4dc;
  border-radius: 12px;
  background: #ffffff;
  color: #41594d;
  font-size: 13px;
  line-height: 1.5;
  text-align: left;
  cursor: pointer;
  box-shadow: 0 1px 3px rgba(15, 23, 42, 0.03);
  transition: all 0.18s ease;
}
.empty-prompt-card:hover {
  border-color: #1f5947;
  background: #f8faf9;
  color: #173f30;
  transform: translateY(-1px);
  box-shadow: 0 4px 14px rgba(23, 74, 58, 0.08);
}
.prompt-arrow {
  color: #8da496;
  font-size: 14px;
  margin-left: 8px;
  flex-shrink: 0;
  transition: transform 0.18s ease, color 0.18s ease;
}
.empty-prompt-card:hover .prompt-arrow {
  color: #1f5947;
  transform: translate(2px, -2px);
}

/* 深色模式适配 */
[data-theme='dark'] .hero-logo-mark {
  background: linear-gradient(135deg, #16977a 0%, #0f5e4c 100%);
  box-shadow: 0 4px 16px rgba(0, 0, 0, 0.4);
}
[data-theme='dark'] .hero-brand-name {
  color: #f3f4f6;
}
[data-theme='dark'] .hero-brand-badge {
  background: rgba(22, 151, 122, 0.2);
  color: #34d399;
}
[data-theme='dark'] .hero-tagline {
  color: #f9fafb;
}
[data-theme='dark'] .hero-subline {
  color: #9ca3af;
}
[data-theme='dark'] .empty-prompt-card {
  background: #111827;
  border-color: rgba(255, 255, 255, 0.1);
  color: #d1d5db;
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.25);
}
[data-theme='dark'] .empty-prompt-card:hover {
  border-color: #16977a;
  background: #1f2937;
  color: #ffffff;
  box-shadow: 0 4px 16px rgba(0, 0, 0, 0.4);
}
[data-theme='dark'] .empty-prompt-card:hover .prompt-arrow {
  color: #34d399;
}
@media(max-width: 768px) {
  .loop-empty-prompts {
    grid-template-columns: 1fr;
  }
}

/* 拖拽式隐藏边框：命中区与图2高品质羽化渐变悬浮手柄 */
.loop-chat-shell.is-resizing {
  user-select: none;
  cursor: col-resize;
}
.loop-chat-shell.is-resizing * {
  user-select: none !important;
}
.loop-width-edge {
  position: absolute;
  z-index: 30;
  top: 0;
  bottom: 0;
  width: 28px;
  cursor: col-resize;
}
.loop-width-edge-left {
  left: -14px;
}
.loop-width-edge-right {
  right: -14px;
}
.loop-width-handle {
  position: absolute;
  left: 0;
  width: 28px;
  height: 100px;
  border: 0;
  border-radius: 0;
  background: transparent;
  cursor: col-resize;
  opacity: 0;
  touch-action: none;
  padding: 0;
  margin: 0;
  outline: none;
  transition: opacity 0.2s cubic-bezier(0.16, 1, 0.3, 1);
  /* 默认浅色主题变量：对齐图2像素级平滑渐变消隐 (212/255 ≈ 0.17 核心实度) */
  --resizer-rgb: 15, 23, 42;
  --resizer-alpha-core: 0.17;
  --resizer-alpha-mid: 0.12;
  --resizer-alpha-soft: 0.06;
  --resizer-alpha-tip: 0.02;
  --resizer-scale-x: 1;
}
.loop-width-handle.is-visible,
.loop-width-handle.is-active,
.loop-width-handle:focus-visible {
  opacity: 1;
  background: transparent;
  backdrop-filter: none;
  -webkit-backdrop-filter: none;
}
.loop-width-handle:hover {
  background: transparent;
  --resizer-alpha-core: 0.32;
  --resizer-alpha-mid: 0.22;
  --resizer-alpha-soft: 0.10;
  --resizer-alpha-tip: 0.03;
  --resizer-scale-x: 1.25;
}
.loop-width-handle.is-active {
  background: transparent;
  --resizer-alpha-core: 0.48;
  --resizer-alpha-mid: 0.34;
  --resizer-alpha-soft: 0.16;
  --resizer-alpha-tip: 0.05;
  --resizer-scale-x: 1.35;
}
/* 深色主题适配 */
[data-theme='dark'] .loop-width-handle {
  --resizer-rgb: 255, 255, 255;
  --resizer-alpha-core: 0.22;
  --resizer-alpha-mid: 0.15;
  --resizer-alpha-soft: 0.07;
  --resizer-alpha-tip: 0.02;
}
[data-theme='dark'] .loop-width-handle:hover {
  --resizer-alpha-core: 0.38;
  --resizer-alpha-mid: 0.26;
  --resizer-alpha-soft: 0.12;
  --resizer-alpha-tip: 0.04;
}
[data-theme='dark'] .loop-width-handle.is-active {
  --resizer-alpha-core: 0.54;
  --resizer-alpha-mid: 0.38;
  --resizer-alpha-soft: 0.18;
  --resizer-alpha-tip: 0.06;
}
.loop-width-handle span {
  display: block;
  width: 2px;
  height: 100%;
  margin: auto;
  border-radius: 999px;
  background: linear-gradient(
    to bottom,
    rgba(var(--resizer-rgb), 0) 0%,
    rgba(var(--resizer-rgb), var(--resizer-alpha-tip)) 10%,
    rgba(var(--resizer-rgb), var(--resizer-alpha-soft)) 20%,
    rgba(var(--resizer-rgb), var(--resizer-alpha-mid)) 30%,
    rgba(var(--resizer-rgb), var(--resizer-alpha-core)) 38%,
    rgba(var(--resizer-rgb), var(--resizer-alpha-core)) 62%,
    rgba(var(--resizer-rgb), var(--resizer-alpha-mid)) 70%,
    rgba(var(--resizer-rgb), var(--resizer-alpha-soft)) 80%,
    rgba(var(--resizer-rgb), var(--resizer-alpha-tip)) 90%,
    rgba(var(--resizer-rgb), 0) 100%
  );
  box-shadow: none;
  transform: scaleX(var(--resizer-scale-x));
  transform-origin: center center;
  transition: transform 0.15s ease, background 0.15s ease;
  pointer-events: none;
}
@media(max-width:768px){.loop-chat-shell{width:100%!important;max-width:none;min-width:0;margin:0}.loop-chat-shell .loop-composer-wrap{padding:8px}.loop-width-edge{display:none}.loop-chat-shell .loop-conversation{padding:16px 12px}}

/* 顶栏操作区：对齐与垂直居中 */
.loop-tabs-actions {
  margin-left: auto;
  align-self: center;
  display: inline-flex;
  align-items: center;
  gap: 12px;
}
.loop-tabs-actions .loop-status {
  margin: 0;
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-size: 12px;
  color: #55685e;
}
.loop-runtime-btn {
  padding: 4px 10px;
  border: 1px solid #d3dee2;
  border-radius: 6px;
  background: #ffffff;
  color: #485c52;
  font-size: 12px;
  cursor: pointer;
  line-height: 1.4;
  transition: all 0.15s ease;
}
.loop-runtime-btn:hover {
  background: #f2f7f4;
  border-color: #b0c9bd;
  color: #1a4233;
}
[data-theme='dark'] .loop-runtime-btn {
  background: #1e293b;
  border-color: rgba(255, 255, 255, 0.12);
  color: #cbd5e1;
}
[data-theme='dark'] .loop-runtime-btn:hover {
  background: #334155;
  color: #f1f5f9;
}

/* 输入框上方工作区选择器（图2样式） */
.composer-top-bar {
  display: flex;
  align-items: center;
  gap: 8px;
  min-height: 28px;
  margin-bottom: 6px;
  padding: 0 4px;
  transition: margin-bottom 0.36s cubic-bezier(0.16, 1, 0.3, 1);
}
/* 浮层占用输入区上方的蓝色缓冲带，布局扩展会自然把工作区选择器平滑推上去。 */
.composer-top-bar.is-workspace-open {
  margin-bottom: 356px;
}
.composer-top-bar.is-workspace-open.is-locked {
  margin-bottom: 118px;
}
.composer-ws-btn {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  border: 1px solid transparent;
  border-radius: 6px;
  background: transparent;
  padding: 4px 8px;
  color: #263548;
  font-size: 13px;
  font-weight: 550;
  cursor: pointer;
  position: relative;
  z-index: 1;
  transition: transform 0.36s cubic-bezier(0.16, 1, 0.3, 1), background-color 0.16s ease, color 0.16s ease, border-color 0.16s ease, box-shadow 0.2s ease;
  user-select: none;
  will-change: transform;
}
.composer-ws-btn.is-open {
  transform: translate3d(0, -10px, 0);
  background: #edf7f1;
  border-color: #c6dfd1;
  color: #174a3a;
  box-shadow: 0 7px 18px rgba(23, 74, 58, 0.11);
}
.composer-ws-btn.is-open .ws-btn-arrow {
  transform: rotate(180deg);
  color: #1f7155;
}
.composer-ws-btn:hover {
  background: #edf3f0;
  color: #174a3a;
}
.composer-ws-btn.is-draft:hover {
  border-color: #d1ded7;
}
.ws-btn-folder-icon {
  display: inline-flex;
  align-items: center;
  color: #4a5c53;
}
.composer-ws-btn:hover .ws-btn-folder-icon {
  color: #174a3a;
}
.ws-btn-name {
  max-width: 180px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.ws-btn-arrow {
  display: inline-flex;
  align-items: center;
  color: #7b8e84;
  margin-left: -1px;
  transition: transform 0.24s cubic-bezier(0.16, 1, 0.3, 1), color 0.16s ease;
}
[data-theme='dark'] .composer-ws-btn {
  color: #e2e8f0;
}
[data-theme='dark'] .composer-ws-btn:hover {
  background: rgba(255, 255, 255, 0.08);
  color: #ffffff;
}
[data-theme='dark'] .ws-btn-folder-icon {
  color: #94a3b8;
}

/* 工作区弹窗面板 */
.ws-popover-card {
  width: 300px;
  max-width: calc(100vw - 32px);
  background: #ffffff;
  border-radius: 12px;
  padding: 12px;
  box-shadow: 0 10px 30px -4px rgba(23, 74, 58, 0.15), 0 4px 12px -2px rgba(15, 23, 42, 0.08);
  border: 1px solid #d8e4dc;
  font-size: 13px;
  transform-origin: 22px 0;
  animation: workspace-popover-enter 0.32s cubic-bezier(0.16, 1, 0.3, 1) both;
  backface-visibility: hidden;
  will-change: transform, opacity;
}
@keyframes workspace-popover-enter {
  from { opacity: 0; transform: translate3d(0, -8px, 0) scale(0.985); }
  to { opacity: 1; transform: translate3d(0, 0, 0) scale(1); }
}
:deep(.workspace-popover-layer) {
  border: 0;
  border-radius: 12px;
  box-shadow: none;
  overflow: visible;
}
.ws-popover-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 6px;
}
.ws-popover-title {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-weight: 650;
  color: #1e332a;
}
.ws-popover-badge {
  font-size: 10px;
  font-weight: 600;
  padding: 2px 6px;
  border-radius: 4px;
  background: #eef2f5;
  color: #64748b;
}
.ws-popover-badge.is-active {
  background: #e6f1ec;
  color: #174a3a;
}
.ws-popover-badge-draft {
  font-size: 10px;
  font-weight: 500;
  padding: 2px 6px;
  border-radius: 4px;
  background: #f1f5f3;
  color: #647d70;
}
.ws-popover-tip {
  margin: 0 0 10px;
  font-size: 11.5px;
  color: #74877c;
  line-height: 1.45;
}
.ws-popover-loading,
.ws-popover-empty {
  padding: 14px 0;
  text-align: center;
  color: #8c9e94;
  font-size: 12px;
}
.ws-popover-list {
  max-height: 190px;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  gap: 3px;
  margin-bottom: 10px;
  padding-right: 2px;
}
.ws-popover-item {
  display: flex;
  align-items: center;
  gap: 8px;
  width: 100%;
  padding: 7px 9px;
  border: 1px solid transparent;
  border-radius: 7px;
  background: transparent;
  color: #33443c;
  text-align: left;
  cursor: pointer;
  transition: all 0.14s ease;
  font-size: 12.5px;
}
.ws-popover-item:hover:not(:disabled) {
  background: #f0f6f3;
  color: #174a3a;
}
.ws-popover-item.is-selected {
  background: #e6f1ec;
  border-color: #cde0d6;
  color: #174a3a;
  font-weight: 600;
}
.ws-popover-item:disabled {
  cursor: default;
}
.ws-item-folder {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  color: #7b8e84;
  flex-shrink: 0;
}
.ws-popover-item.is-selected .ws-item-folder {
  color: #1f5947;
}
.ws-item-name {
  flex: 1;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.ws-item-check {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  color: #1f5947;
  flex-shrink: 0;
}
.ws-popover-footer {
  display: flex;
  align-items: center;
  gap: 6px;
  padding-top: 8px;
  border-top: 1px solid #e7eee9;
}
.ws-popover-input {
  flex: 1;
  min-width: 0;
  height: 32px;
  box-sizing: border-box;
  padding: 6px 10px;
  border: 1px solid #d2ded7;
  border-radius: 6px;
  background: #f9fbf9;
  font-size: 12px;
  color: #1e332a;
  outline: none !important;
  transition: border-color 0.15s ease, box-shadow 0.15s ease;
}
.ws-popover-input:focus,
.ws-popover-input:focus-visible {
  outline: none !important;
  border-color: #1f5947 !important;
  box-shadow: 0 0 0 2px rgba(31, 89, 71, 0.12) !important;
  background: #ffffff;
}
.ws-popover-create-btn {
  height: 32px;
  box-sizing: border-box;
  padding: 0 12px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  border: 0;
  border-radius: 6px;
  background: #1f5947;
  color: #ffffff;
  font-size: 12px;
  font-weight: 550;
  cursor: pointer;
  transition: all 0.15s ease;
  white-space: nowrap;
}
.ws-popover-create-btn:hover:not(:disabled) {
  background: #174a3a;
}
.ws-popover-create-btn:disabled {
  background: #edf3f0;
  color: #9ab0a4;
  opacity: 1;
  cursor: not-allowed;
}

[data-theme='dark'] .ws-popover-card {
  background: #1e293b;
  border-color: rgba(255, 255, 255, 0.12);
  box-shadow: 0 10px 30px -4px rgba(0, 0, 0, 0.5);
}
@media (prefers-reduced-motion: reduce) {
  .composer-top-bar,
  .composer-ws-btn,
  .ws-btn-arrow { transition: none; }
  .ws-popover-card { animation: none; }
}
@media (max-height: 640px) {
  .composer-top-bar.is-workspace-open { margin-bottom: 282px; }
  .composer-top-bar.is-workspace-open.is-locked { margin-bottom: 104px; }
  .ws-popover-list { max-height: 132px; }
}
[data-theme='dark'] .ws-popover-title {
  color: #f1f5f9;
}
[data-theme='dark'] .ws-popover-badge-draft {
  background: rgba(255, 255, 255, 0.08);
  color: #94a3b8;
}
[data-theme='dark'] .ws-popover-tip {
  color: #94a3b8;
}
[data-theme='dark'] .ws-popover-item {
  color: #cbd5e1;
}
[data-theme='dark'] .ws-popover-item:hover:not(:disabled) {
  background: rgba(255, 255, 255, 0.08);
  color: #ffffff;
}
[data-theme='dark'] .ws-popover-item.is-selected {
  background: rgba(22, 151, 122, 0.2);
  border-color: rgba(22, 151, 122, 0.4);
  color: #34d399;
}
[data-theme='dark'] .ws-item-folder {
  color: #94a3b8;
}
[data-theme='dark'] .ws-popover-item.is-selected .ws-item-folder {
  color: #34d399;
}
[data-theme='dark'] .ws-item-check {
  color: #34d399;
}
[data-theme='dark'] .ws-popover-footer {
  border-top-color: rgba(255, 255, 255, 0.1);
}
[data-theme='dark'] .ws-popover-input {
  background: #0f172a;
  border-color: rgba(255, 255, 255, 0.15);
  color: #f8fafc;
}
[data-theme='dark'] .ws-popover-input:focus,
[data-theme='dark'] .ws-popover-input:focus-visible {
  border-color: #16977a !important;
  box-shadow: 0 0 0 2px rgba(22, 151, 122, 0.25) !important;
  background: #1e293b;
}
[data-theme='dark'] .ws-popover-create-btn {
  background: #16977a;
  color: #ffffff;
}
[data-theme='dark'] .ws-popover-create-btn:hover:not(:disabled) {
  background: #148369;
}
[data-theme='dark'] .ws-popover-create-btn:disabled {
  background: rgba(255, 255, 255, 0.08);
  color: rgba(255, 255, 255, 0.3);
}

/* 页面底部指标条 */
.loop-bottom-metrics {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: center;
  gap: 8px 24px;
  padding: 8px 20px 10px;
  color: #7b8b9d;
  font-size: 11.5px;
  font-variant-numeric: tabular-nums;
  border-top: 1px solid #eef2f1;
  background: rgba(255, 255, 255, 0.85);
  backdrop-filter: blur(8px);
  -webkit-backdrop-filter: blur(8px);
  flex-shrink: 0;
}
.loop-bottom-metrics span {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  white-space: nowrap;
}
.loop-bottom-metrics svg {
  color: #8da0b3;
  flex-shrink: 0;
}
[data-theme='dark'] .loop-bottom-metrics {
  border-top-color: rgba(255, 255, 255, 0.08);
  background: rgba(17, 24, 39, 0.8);
  color: #94a3b8;
}
[data-theme='dark'] .loop-bottom-metrics svg {
  color: #64748b;
}
</style>
