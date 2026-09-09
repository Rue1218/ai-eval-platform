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
              :aria-label="`选择会话：${s.title || '新会话'}`"
              @click.stop
              @change="toggleSessionSelected(s.id)"
            />
            <span class="session-title-text">{{ s.title || '新会话' }}</span>
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
        <span class="chat-head-title">{{ currentSession?.title || '新会话' }}</span>
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
      <!-- 历史 v1 界面仅保留源码供审计；isLoopView 恒为真，不能再到达此分支。 -->
      <template v-else>
      <!-- 断线重连横幅提示（真实 WS 状态） -->
      <div v-if="!isWsOnline" class="info-strip">
        <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round">
          <circle cx="12" cy="12" r="9" />
          <path d="M12 11v5" />
          <circle cx="12" cy="7.6" r=".4" fill="currentColor" />
        </svg>
        <span>已断线，正在重连（重连后按 last_event_id 自动补发）…</span>
      </div>

      <!-- 消息流滚动区 -->
      <div ref="chatScrollRef" class="chat-scroll" @scroll="handleScroll">
        <div class="chat-col">
          <!-- 1. 空会话内联欢迎态 -->
          <div v-if="events.length === 0" class="welcome" data-od-id="welcome">
            <div class="welcome-eyebrow">AI Eval · 智能体</div>
            <!-- 固定文案两行排版（对齐原型 <br> 换行），非用户输入，无注入风险 -->
            <h2 class="welcome-title" v-html="isRagMode ? '知识库检索质量评估，<br>全链路调优与召回分析。' : '说一句目标，<br>拿回一份评测报告。'"></h2>
            <p class="welcome-sub">
              {{ isRagMode ? '说明要评测的知识库或外部 RAG 接口。' : '说明要评测的模型或 PRD 生成需求。' }}
            </p>

            <div class="welcome-caps">
              <button
                v-for="cap in currentCaps"
                :key="cap.id"
                class="cap"
                :data-od-id="cap.id"
                @click="sendPredefined(cap.say)"
              >
                <span class="cap-ico">
                  <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" v-html="cap.icoSvg"></svg>
                </span>
                <span>
                  <span class="cap-name">{{ cap.name }}</span>
                  <span class="cap-desc">{{ cap.desc }}</span>
                </span>
              </button>
            </div>
          </div>

          <!-- 2. 消息流组件渲染 -->
          <template v-for="(item, idx) in events" :key="idx">
            <!-- 2.1 用户气泡（no-anim：历史回放项跳过入场动画） -->
            <div
              v-if="item.type === 'user'"
              class="msg-user"
              :class="{ 'no-anim': item.noAnim, remote: isRemoteUserMessage(item) }"
            >
              <div v-if="item.author" class="user-author">{{ userMessageAuthorLabel(item) }}</div>
              <div v-if="item.files && item.files.length" class="message-attachments">
                <AttachmentPreview
                  v-for="f in item.files"
                  :key="f.localId || f.id || f.file_id || f.name"
                  :attachment="f"
                  compact
                />
              </div>
              <div v-if="item.text" class="bubble-user">
                <MarkdownView :content="item.text" custom-class="bubble-user-markdown" />
              </div>
            </div>

            <!-- 2.1.1 打字占位气泡：服务端流式开始前的即时反馈（收到事件后由 dismissTyping 移除） -->
            <div v-else-if="item.type === 'typing'" class="msg-agent typing-bubble">
              <span class="tdot"></span><span class="tdot"></span><span class="tdot"></span>
            </div>

            <!-- 2.5 评测报告卡片 -->
            <div
              v-else-if="item.type === 'report'"
              class="report-card"
              :class="{ 'no-anim': item.noAnim }"
              data-od-id="report-card"
            >
              <div class="row">
                <span class="badge badge-succeeded"><i class="bdot"></i>报告已生成</span>
                <span class="small tertiary mono">{{ item.reportId }}</span>
              </div>
              <div class="report-card-kpis">
                <div v-for="k in item.kpis || defaultKpis" :key="k.label">
                  <div class="kpi-num num">{{ k.value }}<span class="unit">{{ k.unit || '' }}</span></div>
                  <div class="kpi-label">{{ k.label }}</div>
                </div>
              </div>
              <div v-if="item.bars && item.bars.length" class="rc-bars">
                <div v-for="b in item.bars" :key="b.label" class="rc-bar-row">
                  <span class="rc-bar-label">{{ b.label }}</span>
                  <span class="rc-bar-track">
                    <i :style="{ width: `${Math.round((b.value / (b.max || 1)) * 100)}%` }"></i>
                  </span>
                  <span class="rc-bar-val mono">{{ b.value.toFixed(2) }}</span>
                </div>
              </div>
              <div class="row" style="gap: 8px">
                <!-- 无 reportId 不渲染入口，避免跳转 /reports/undefined -->
                <router-link v-if="item.reportId" :to="`/reports/${item.reportId}`" class="btn btn-sign btn-sm">
                  查看报告
                </router-link>
                <button v-if="item.reportId" class="btn btn-secondary btn-sm" @click="handleInterpretReport(item.reportId)">
                  在对话中解读
                </button>
              </div>
            </div>

            <!-- 2.5.1 任务确认卡（V1.67 恢复）：事实源在 ConfirmCard.vue，仅发起成员可操作 -->
            <ConfirmCard
              v-else-if="item.type === 'confirm' && item.card"
              :item="item"
              :available-profiles="availableProfiles"
              :available-datasets="availableDatasets"
              :available-kbs="availableKbs"
              :available-gold-qas="availableGoldQas"
              :active-task="activeTask"
              :prod-approvers-text="prodApproversText"
              :can-confirm="canConfirmItem(item)"
              :confirm-author-label="confirmAuthorLabel(item)"
              @confirm="handleConfirmAck(item, true)"
              @cancel="handleConfirmAck(item, false)"
            />

            <!-- 2.5.2 工具审批卡（H5 HITL，API.md V1.70）：危险 bash 命令执行前暂停，
                 批准/拒绝经 tool_approval_ack 回执恢复原图回合（resume 至多一次） -->
            <ApprovalCard
              v-else-if="item.type === 'toolApproval' && item.approval"
              :item="item"
              :can-act="canActApproval(item)"
              @approve="handleApprovalAck"
              @reject="handleApprovalReject"
            />

            <!-- 2.5.3 澄清卡（V1.72 / dsh #1，API.md §4.3）：ask_user_question 的
                 图内中断载荷即澄清问卷；提交经 clarify_reply 恢复原回合（至多一次） -->
            <ClarifyCard
              v-else-if="item.type === 'clarify' && item.clarify"
              :item="item"
              :can-act="canActClarify(item)"
              @submit="handleClarifySubmit(item, $event)"
            />

            <!-- 2.6 错误条 -->
            <div v-else-if="item.type === 'error'" class="error-strip" :class="{ 'no-anim': item.noAnim }">
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" style="flex: 0 0 16px; margin-top: 1px">
                <circle cx="12" cy="12" r="9" />
                <path d="M12 7.5v5.5" />
                <circle cx="12" cy="16.4" r=".4" fill="currentColor" />
              </svg>
              <div>
                <b>{{ item.code || 'ERROR' }}</b> · {{ item.message }}
              </div>
            </div>

            <!-- 2.7 Agent 回合：模型头部固定在最前，助手正文按流式增量顺序排列 -->
            <div
              v-else-if="item.type === 'agent'"
              class="msg-agent"
              :class="{ 'no-anim': item.noAnim, 'streaming-bubble': item.streaming }"
            >
              <div class="assistant-message-layout">
                <ProviderLogo
                  class="assistant-message-logo"
                  :provider="item.providerLogoKey || 'custom'"
                />
                <div class="assistant-message-main">
                  <!-- 顶部模型与时间标识（仅展示 Provider 图标、模型标识与发送时间） -->
                  <div class="assistant-message-header">
                    <div class="assistant-message-model">
                      {{ item.modelName || 'Agent' }}
                    </div>
                    <div v-if="formatAgentMessageTime(item.createdAt)" class="assistant-message-time mono">
                      {{ formatAgentMessageTime(item.createdAt) }}
                    </div>
                  </div>

                  <!-- 回合内容：纯助手正文（骨架版无思考卡 / 工具卡 / 确认卡）。 -->
                  <template v-for="(block, blockIdx) in item.blocks" :key="blockIdx">
                    <div v-if="block.type === 'assistant'">
                      <MarkdownView
                        v-if="block.raw || block.text"
                        :content="block.raw || block.text || ''"
                        :is-streaming="block.streaming"
                      />
                      <div v-if="!block.streaming" class="reply-latency mono">
                        <template v-if="formatLatency(block.latency_ms)">耗时 {{ formatLatency(block.latency_ms) }}</template>
                      </div>
                    </div>
                    <div v-else-if="block.type === 'error'" class="error-strip" :class="{ 'no-anim': block.noAnim }">
                      <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round">
                        <circle cx="12" cy="12" r="9" />
                        <path d="M12 7.5v5.5" />
                        <circle cx="12" cy="16.4" r=".4" fill="currentColor" />
                      </svg>
                      <div><b>{{ block.code || 'ERROR' }}</b> · {{ block.message }}</div>
                    </div>
                  </template>

                  <!-- H3 工具卡：Agent TAOR 的 Act 与结果（ToolCard 只展示脱敏摘要）。 -->
                  <div v-if="item.toolItems?.length" class="tool-stack">
                    <div
                      v-for="tool in item.toolItems"
                      :key="tool.call_id"
                      class="tool-card"
                      :class="{ open: item.openToolId === tool.call_id }"
                    >
                      <div class="tool-head" @click="toggleToolCard(item, tool.call_id)">
                        <span class="tool-status" :class="tool.status === 'running' ? 'pending' : tool.ok ? 'ok' : 'fail'">
                          <svg v-if="tool.status === 'running'" width="14" height="14" viewBox="0 0 24 24" fill="none">
                            <circle cx="12" cy="12" r="9" stroke="currentColor" stroke-width="3" stroke-dasharray="18 40" />
                          </svg>
                          <svg v-else-if="tool.ok" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3" stroke-linecap="round" stroke-linejoin="round">
                            <path d="M4 12.5l5.5 5.5L20 6.5" />
                          </svg>
                          <svg v-else width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3" stroke-linecap="round">
                            <path d="M6 6l12 12M18 6L6 18" />
                          </svg>
                        </span>
                        <span class="tool-name">{{ tool.name }}</span>
                        <span class="tool-state-text" :class="{ fail: tool.status === 'error' }">
                          {{ toolStateText(tool) }}
                        </span>
                        <span class="chev">▾</span>
                      </div>
                      <div class="tool-detail">
                        <template v-if="hasToolArguments(tool)">
                          <div class="td-label">参数摘要</div>
                          <pre class="mono tool-args">{{ formatToolArguments(tool.arguments) }}</pre>
                        </template>
                        <template v-if="tool.status === 'error'">
                          <div class="td-label">结果</div>
                          <div class="tool-state-text fail">{{ tool.error }}</div>
                        </template>
                      </div>
                    </div>
                  </div>

                  <!-- 兼容历史旧缓存：没有 blocks 时仍渲染原助手正文。 -->
                  <MarkdownView
                    v-if="!item.blocks?.length && (item.raw || item.text)"
                    :content="item.raw || item.text || ''"
                    :is-streaming="item.streaming"
                  />

                  <!-- 兼容历史旧缓存的回复耗时。 -->
                  <div v-if="!item.blocks?.length && !item.streaming" class="reply-latency mono">
                    <template v-if="formatLatency(item.latency_ms)">耗时 {{ formatLatency(item.latency_ms) }}</template>
                  </div>
                </div>
              </div>
            </div>
          </template>
        </div>

        <!-- 回到底部悬浮胶囊 -->
        <div class="jump-wrap">
          <button class="jump-bottom" :class="{ show: showJumpBottom }" data-od-id="jump-bottom" @click="scrollToBottom(true)">
            <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round">
              <path d="M12 5v14M5 12l7 7 7-7" />
            </svg>
            <span>回到底部</span>
          </button>
        </div>
      </div>

      <!-- 3. 吸附式进度坞（S10：任务结束后先展示完成 note，2.6s 后再隐藏） -->
      <div v-if="activeTask || dockClosingNote" class="progress-dock" data-od-id="progress-dock">
        <div v-if="!activeTask" class="progress-dock-inner">
          <span class="small tertiary">{{ dockClosingNote }}</span>
        </div>
        <div v-else class="progress-dock-inner">
          <KindTag :kind="activeTask.kind" />
          <div class="progress-bar">
            <i :style="{ width: `${activeTask.progress?.percent || 0}%` }"></i>
          </div>
          <span class="progress-nums mono">{{ activeTask.progress?.done || 0 }}/{{ activeTask.progress?.total || 100 }}</span>
          <span class="progress-msg">{{ activeTask.progress?.message || '任务进行中...' }}</span>
          <button
            v-if="canCancelActiveTask"
            class="btn btn-ghost btn-sm"
            :disabled="cancellingTaskId === activeTask.id"
            @click="handleCancelActiveTask(activeTask.id)"
          >
            {{ cancellingTaskId === activeTask.id ? '取消中…' : '取消' }}
          </button>
        </div>
      </div>

      <!-- 4. 底部多功能输入区 -->
      <div class="composer" data-od-id="composer">
        <!-- 快捷 Prompt 芯片栏（欢迎态期间隐藏，首发消息后渐进披露） -->
        <div v-show="events.length > 0" class="quick-chips">
          <button
            v-for="chip in currentQuickChips"
            :key="chip.label"
            class="chip"
            @click="sendPredefined(chip.say)"
          >
            {{ chip.label }}
          </button>
        </div>

        <div
          class="composer-card"
          :class="{ generating: isGenerating, 'drag-active': isDragActive }"
          style="position: relative;"
          @dragenter.prevent="handleDragEnter"
          @dragover.prevent="handleDragOver"
          @dragleave.prevent="handleDragLeave"
          @drop.prevent="handleDrop"
        >
          <!-- 待发送附件固定在输入框内部，位于正文输入区上方。 -->
          <div v-if="stagedFiles.length" class="attach-stage">
            <AttachmentPreview
              v-for="f in stagedFiles"
              :key="f.localId"
              :attachment="f"
              compact
              removable
              @remove="removeStagedFile(f.localId)"
            />
          </div>
          <div v-if="isDragActive" class="composer-drop-hint">
            <span class="composer-drop-icon">＋</span>
            <strong>松开以上传附件</strong>
            <span>支持图片、Markdown、PDF、Word、Excel 等格式</span>
          </div>

          <!-- 上半区：正常黑色多行文本域 -->
          <div class="composer-input-row">
            <!-- 添加附件按钮紧贴输入内容左侧，保持在输入框边界内。 -->
            <button class="composer-action-btn composer-attach-btn" type="button" title="添加附件（≤20MB，支持图片、Markdown、PDF、Word、Excel 等）" @click="triggerFileInput">
              <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round">
                <line x1="12" y1="5" x2="12" y2="19"></line>
                <line x1="5" y1="12" x2="19" y2="12"></line>
              </svg>
            </button>
            <textarea
              ref="textareaRef"
              v-model="inputText"
              class="composer-textarea"
              rows="1"
              :placeholder="'输入任何评测问题或需求，Shift + Enter 换行，Enter 发送'"
              @keydown="handleKeydown"
              @input="adjustTextareaHeight"
              @paste="() => nextTick(adjustTextareaHeight)"
            ></textarea>
          </div>

          <!-- 下半区：操作底栏（附件 + 只读模型标识 + 发送按钮） -->
          <div class="composer-bottom-bar">
            <div class="composer-left-actions">
              <input
                ref="fileInputRef"
                type="file"
                hidden
                accept=".md,.txt,.html,.pdf,.json,.yaml,.yml,.xlsx,.xls,.csv,.jsonl,.doc,.docx,.wav,.mp3,.png,.jpg,.jpeg,.webp,.gif"
                multiple
                @change="handleFileUpload"
              />

              <!-- 模型切换下拉按钮（模型名 + 箭头，点击可自由切换） -->
              <n-dropdown
                trigger="click"
                :options="agentProfileDropdownOptions"
                @select="handleSelectAgentModel"
              >
                <button
                  class="composer-model-dropdown-btn"
                  type="button"
                  title="点击切换当前 Agent 驱动模型"
                >
                  <ProviderLogo :provider="agentProfileLogoKey" compact />
                  <span class="model-name mono">{{ agentDisplayModelName || '选择模型' }}</span>
                  <svg class="chevron-icon" width="10" height="10" viewBox="0 0 12 12" fill="none" stroke="currentColor" stroke-width="1.5">
                    <path d="M3 4.5l3 3 3-3" stroke-linecap="round" stroke-linejoin="round" />
                  </svg>
                </button>
              </n-dropdown>

              <!-- 上下文容量小圆环：只读服务端 context_meter，null 不渲染（CX-7） -->
              <ContextMeter
                v-if="currentContextMeter"
                :meter="currentContextMeter"
                :compact-summary="currentCompactSummary"
              />
            </div>

            <!-- 右侧圆形发送/暂停按钮 -->
            <button
              class="composer-send-btn"
              :class="{ active: isGenerating || inputText.trim().length > 0 || stagedFiles.length > 0 }"
              :disabled="!isGenerating && (isUploadingAttachments || (inputText.trim().length === 0 && !hasUploadedAttachments))"
              :title="isGenerating ? '暂停生成（不取消已入队任务）' : '发送 (Enter)'"
              @click="handleSendClick"
            >
              <svg v-if="isGenerating" width="12" height="12" viewBox="0 0 24 24" fill="currentColor">
                <rect x="6" y="6" width="12" height="12" rx="2" />
              </svg>
              <svg v-else width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
                <line x1="12" y1="19" x2="12" y2="5"></line>
                <polyline points="5 12 12 5 19 12"></polyline>
              </svg>
            </button>
          </div>
        </div>
      </div>
      </template>
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
import KindTag from '../components/common/KindTag.vue'
import ProviderLogo from '../components/ProviderLogo.vue'
import { getProviderLogoKey, type ProviderLogoKey } from '../utils/providerLogo'
import { formatLatency } from '../utils/format'
import AttachmentPreview from '../components/agent/AttachmentPreview.vue'
import MarkdownView from '../components/agent/MarkdownView.vue'
import ContextMeter, { type ContextMeterData } from '../components/agent/ContextMeter.vue'
import AgentWorkspace from '../components/agent/loop/AgentWorkspace.vue'
import { createLoopStore } from '../agent/loop/store'
import ApprovalCard from '../components/agent/ApprovalCard.vue'
import ClarifyCard from '../components/agent/ClarifyCard.vue'
import ConfirmCard from '../components/agent/ConfirmCard.vue'
import { getDefaultRunConfig, getDefaultStressConfig } from '../schemas/confirmCard'

const message = useMessage()
const dialog = useDialog()
const route = useRoute()
const router = useRouter()
const modeStore = useModeStore()
const authStore = useAuthStore()
const chatScrollRef = ref<HTMLDivElement | null>(null)
const textareaRef = ref<HTMLTextAreaElement | null>(null)
const fileInputRef = ref<HTMLInputElement | null>(null)

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

function toggleDispatchRail() {
  isRailOpen.value = !isRailOpen.value
  if (isRailOpen.value && typeof window !== 'undefined' && window.innerWidth <= 768) {
    isListCollapsed.value = true
  }
}

const isWsOnline = ref(true)
const isGenerating = ref(false)
const turnLatencyMs = ref(0)
const turnLatencyLabel = computed(() => formatLatency(turnLatencyMs.value) || '')
const showJumpBottom = ref(false)
const currentAgentProfileId = ref<string>('')
const allProfiles = ref<Profile[]>([])
const activeAgentProfile = computed(() => {
  const activeId = currentAgentProfileId.value || allProfiles.value[0]?.id
  return allProfiles.value.find((item) => item.id === activeId) || null
})
const agentProfileLogoKey = computed<ProviderLogoKey>(() => {
  return activeAgentProfile.value ? getProviderLogoKey(activeAgentProfile.value) : 'custom'
})
const agentDisplayModelName = computed(() => activeAgentProfile.value?.model || 'Agent')
const agentProfileDisplayName = computed(() => activeAgentProfile.value?.name || '')

// 上下文度量状态
const currentContextMeter = ref<ContextMeterData | null>(null)
const currentCompactSummary = ref<string | null>(null)

/** 模型选择下拉菜单项（对齐 /admin/profiles 接入池） */
const agentProfileDropdownOptions = computed<DropdownOption[]>(() => {
  if (!allProfiles.value.length) {
    return [
      { label: '暂无接入模型协议档', key: '__none__', disabled: true },
      { type: 'divider', key: 'd1' },
      { label: '⚙ 前往接入协议档 ↗', key: '__goto_profiles__' },
    ]
  }
  const activeId = currentAgentProfileId.value || allProfiles.value[0]?.id
  const list: DropdownOption[] = allProfiles.value.map((p) => {
    const isCurrent = p.id === activeId
    return {
      label: `${p.name} (${p.model || p.protocol})${isCurrent ? ' ✓' : ''}`,
      key: p.id,
      disabled: isCurrent,
      icon: () => h(ProviderLogo, { provider: getProviderLogoKey(p), compact: true }),
    }
  })
  return [
    ...list,
    { type: 'divider', key: 'd1' },
    { label: '⚙ 管理模型接入协议档 ↗', key: '__goto_profiles__' },
  ]
})

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
const currentSessionStatusFilterLabel = computed(() => {
  switch (sessionStatusFilter.value) {
    case 'running': return '进行中'
    case 'ready': return '就绪'
    case 'succeeded': return '成功'
    case 'failed': return '失败'
    default: return '状态'
  }
})

/** 切换会话状态筛选 */
function handleSelectSessionStatusFilter(key: string) {
  sessionStatusFilter.value = key
}

/** 按状态筛选后的会话列表 */
const filteredSessions = computed(() => {
  if (sessionStatusFilter.value === 'all') return sessions.value
  return sessions.value.filter((s) => sessionDotClass(s) === sessionStatusFilter.value)
})

const selectedSessionIds = ref<string[]>([])
const deletingSessionIds = new Set<string>()
const currentSessionId = ref<string>('')
const isCreatingSession = ref(false)
// F3/G5：草稿会话可预选绑定工作区（首条消息发送时随 create 固化；已建会话
// 绑定关系只读展示 workspace_name，运行期不可变更——换绑 = 新建会话）。
const draftWorkspaceId = ref<string | null>(null)
const draftWorkspaceName = ref<string>('')
const bindingPanelOpen = ref(false)
const bindableWorkspaces = ref<Array<{ id: string; name: string }>>([])
const bindingLoading = ref(false)
// 面板内新建工作区（即建即绑，无需跳「我的工作区」）
const newWorkspaceName = ref('')
const newWorkspaceBusy = ref(false)
// 未绑定服务端会话时保持草稿态，不得用列表首项冒充当前会话。
const currentSession = computed(() => sessions.value.find(s => s.id === currentSessionId.value) || null)
// 产品入口已收敛为 AgentLoop；保留 v-else 源码仅用于历史审计与后续删除。
const isLoopView = computed(() => true)
const loopStore = createLoopStore(id => removeInaccessibleSession(id))
watch(() => authStore.user?.id, (id, previous) => { if (previous && id !== previous) loopStore.close() })
watch(() => Object.values(loopStore.sessions).map(s => [s.sessionId, s.title]), () => {
  for (const value of Object.values(loopStore.sessions)) { const session = sessions.value.find(s => s.id === value.sessionId); if (session && value.title) session.title = value.title }
})
/** 创建时固化 v2 和工作区，后续只使用独立 transport。 */
async function createLoopSession(workspaceId?: string): Promise<string> {
  if (currentSessionId.value) return currentSessionId.value
  const targetWsId = workspaceId || draftWorkspaceId.value || undefined
  const session = await api.sessions.create('新会话', { workspaceId: targetWsId })
  sessions.value.unshift(session); currentSessionId.value = session.id; clearDraftWorkspace()
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

const stagedFiles = ref<StagedAttachment[]>([])
const isDragActive = ref(false)
const isUploadingAttachments = computed(() => stagedFiles.value.some((file) => file.uploading))
const hasUploadedAttachments = computed(() => stagedFiles.value.some((file) => Boolean(file.id) && !file.error))
let dragDepth = 0
const localAttachmentUrls = new Set<string>()
const activeTask = ref<Task | null>(null)
// 取消请求发送后等待服务端确认，避免重复提交且不提前伪造 cancelled。
const cancellingTaskId = ref<string | null>(null)

/** 共享会话里进度坞只给任务创建者展示取消入口，服务端仍是最终权限裁决。 */
const canCancelActiveTask = computed(() => {
  const task = activeTask.value
  const user = authStore.user
  if (!task || !user) return false
  const creatorId = task.creator_id || task.created_by
  // 无创建者信息时宁可暂不展示，异步补齐后再开放，避免协作者得到越权入口。
  return !!creatorId && creatorId === user.id
})

// 智能体能力卡与顶栏共用同一模式状态，避免出现页面内外不一致的评测上下文。
const isRagMode = computed(() => modeStore.mode === 'rag')

const LLM_CAPS = [
  { id: 'cap-benchmark', name: '多模型基准对比', desc: '1–5 个协议档并排测试，输出 contain / exact / Judge 打分', say: '帮我对两个已配置模型进行基准评测', icoSvg: '<path d="M4 20V10M10 20V4M16 20v-8M3 20h18"/>' },
  { id: 'cap-prompt', name: 'Prompt 效果评测', desc: '评测不同系统提示词与上下文在同一数据集上的得分差异', say: '评测系统 Prompt 在支付链路问答上的准确率', icoSvg: '<rect x="4" y="4" width="16" height="16" rx="3"/><path d="M8 9h8M8 13h5"/>' },
  { id: 'cap-testcase', name: 'PRD 生成用例', desc: '附 PRD / OpenAPI，按 6 种策略生成，72h 内确认入库', say: '帮我把这份支付 PRD 生成测试用例', icoSvg: '<path d="M9 11.5 11 14l4.5-5"/><rect x="4" y="4" width="16" height="16" rx="3"/>' },
]

const RAG_CAPS = [
  { id: 'cap-rag', name: 'RAG 检索评测', desc: '知识库 + 黄金 QA，输出 Hit Rate@5 / MRR / Recall', say: '帮我评估已配置知识库的检索质量', icoSvg: '<path d="M5 5.5A2.5 2.5 0 0 1 7.5 3H19v15H7.5A2.5 2.5 0 0 0 5 20.5Z"/><path d="M5 18.5V5.5"/><path d="M9 7.5h6"/>' },
  { id: 'cap-modes', name: '4 模式横向对比', desc: '对比 LightRAG naive / local / global / hybrid 检索表现', say: '横向对比已配置知识库的四种检索模式', icoSvg: '<circle cx="12" cy="12" r="3"/><path d="M3 12h3M18 12h3M12 3v3M12 18v3"/>' },
  { id: 'cap-qa', name: '黄金 QA 检验', desc: '校验 expected_doc_ids 召回命中与相似度分布', say: '检验已配置知识库的黄金 QA 覆盖度', icoSvg: '<path d="M9 11.5 11 14l4.5-5"/><circle cx="12" cy="12" r="9"/>' },
]

const currentCaps = computed(() => isRagMode.value ? RAG_CAPS : LLM_CAPS)

// 快捷芯片：短标签 + 完整 prompt（对齐原型 data-say），顺序随顶栏模式重排
const QUICK_CHIPS = [
  { label: '生成用例', say: '帮我把这份 PRD 生成测试用例' },
  { label: '基准评测', say: '对比一下 gpt-test 和 claude-x 在 smoke-20 上的表现' },
  { label: 'RAG 评测', say: '评估 default 知识库的检索质量' },
]

const currentQuickChips = computed(() => {
  // RAG 模式 RAG 优先（对齐原型 orderChipsByMode）
  if (isRagMode.value) return [QUICK_CHIPS[2], QUICK_CHIPS[0], QUICK_CHIPS[1]]
  return QUICK_CHIPS
})

const defaultKpis = [
  { value: '2%', label: '失败率' },
  { value: '820ms', label: '平均延迟' },
  { value: '0.86', label: '主指标 contain' },
]

/** D5 会话列表状态点多态：按 status / active_task / 本轮生成中 / 断线重连 映射 nav-dot 样式，常驻显示就绪状态。 */
function sessionDotClass(s: any): string {
  if (s.engine_version === 'agent_loop_v2') {
    const value = loopStore.sessions[s.id]
    if (!value) return s.active_task?.status === 'running' || s.active_task?.status === 'queued' ? 'running' : 'ready'
    if (value.connection !== 'online') return 'offline'
    if (value.activeTurn || Object.values(value.tasks).some(task => ['running','queued','awaiting_case_confirm'].includes(task.status))) return 'running'
    return value.phase === 'error' ? 'failed' : value.phase === 'completed' ? 'succeeded' : 'ready'
  }
  const rt = sessionRuntimes.get(s.id)
  const isGen = generatingBySession.value[s.id] || (s.id === currentSessionId.value && isGenerating.value) || rt?.isGenerating
  if (isGen) return 'running'

  const task = (s.id === currentSessionId.value ? activeTask.value : null) || rt?.activeTask || s.active_task
  if (task) {
    if (task.status === 'running' || task.status === 'queued') return 'running'
    if (task.status === 'failed') return 'failed'
    if (task.status === 'succeeded') return 'succeeded'
    if (task.status === 'cancelled') return 'offline'
  }
  if (s.status === 'running' || s.status === 'queued') return 'running'
  if (s.status === 'failed') return 'failed'
  if (s.status === 'succeeded') return 'succeeded'
  if (s.id === currentSessionId.value && !isWsOnline.value) return 'offline'
  return 'ready'
}

/** 会话状态提示语（鼠标悬停指示点时展示）。 */
function sessionDotTooltip(s: any): string {
  if (s.engine_version === 'agent_loop_v2') {
    const value = loopStore.sessions[s.id]
    return !value ? 'AgentLoop 会话' : value.connection !== 'online' ? '连接中断，状态待同步' : value.activeTurn ? 'Agent 回合进行中' : 'Agent 回合已结束；Worker 状态独立'
  }
  const rt = sessionRuntimes.get(s.id)
  const isGen = generatingBySession.value[s.id] || (s.id === currentSessionId.value && isGenerating.value) || rt?.isGenerating
  if (isGen) return '智能体正在思考生成中…'

  const task = (s.id === currentSessionId.value ? activeTask.value : null) || rt?.activeTask || s.active_task
  if (task) {
    if (task.status === 'running' || task.status === 'queued') return '评测任务进行中…'
    if (task.status === 'failed') return '任务执行失败 (failed)'
    if (task.status === 'succeeded') return '任务评测成功 (succeeded)'
    if (task.status === 'cancelled') return '任务已取消 (cancelled)'
  }
  if (s.status === 'running' || s.status === 'queued') return '评测任务进行中…'
  if (s.status === 'failed') return '任务执行失败 (failed)'
  if (s.status === 'succeeded') return '任务评测成功 (succeeded)'
  if (s.id === currentSessionId.value && !isWsOnline.value) return 'WebSocket 已断开，正在重连…'
  return '智能体就绪 (在线)'
}

/* S10 进度坞收尾提示：非空时坞保持可见，2.6s 后隐藏 */
const dockClosingNote = ref('')

/** S10 任务结束收尾：先展示完成 note，2.6s 后再隐藏进度坞（对齐原型 hideDock）。 */
function finishDock(note: string) {
  activeTask.value = null
  const sid = currentSessionId.value
  if (sid) {
    const rt = sessionRuntimes.get(sid)
    if (rt) rt.activeTask = null
  }
  cancellingTaskId.value = null
  dockClosingNote.value = note
  trackTimeout(() => { dockClosingNote.value = '' }, 2600)
}

/** 仅在服务端确认取消后关闭进度坞，避免网络失败被前端误报为已取消。 */
function finishCancelledTask(taskId: string) {
  if (activeTask.value?.id === taskId) {
    activeTask.value.status = 'cancelled'
    activeTask.value.progress = {
      ...(activeTask.value.progress || { done: 0, total: 0 }),
      message: '任务已取消',
    }
    finishDock('任务已取消')
    return
  }
  if (cancellingTaskId.value === taskId) cancellingTaskId.value = null
}

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

function trackInterval(fn: () => void, ms: number): number {
  const id = window.setInterval(fn, ms)
  pendingTimers.add(id)
  return id
}

/** 主动清除已登记定时器（任务提前完成时使用）。 */
function clearTracked(id: number) {
  window.clearTimeout(id)
  window.clearInterval(id)
  pendingTimers.delete(id)
}

/** 滚动锚定：仅当视口贴底（距底 <72px）时才跟随新消息，上翻阅读不被打断（对齐原型行为）。 */
const stickToBottom = ref(true)

function handleScroll() {
  if (!chatScrollRef.value) return
  const { scrollTop, scrollHeight, clientHeight } = chatScrollRef.value
  const dist = scrollHeight - scrollTop - clientHeight
  showJumpBottom.value = dist > 72
  stickToBottom.value = dist <= 72
}

function scrollToBottom(force = false) {
  nextTick(() => {
    if (chatScrollRef.value && (force || stickToBottom.value)) {
      chatScrollRef.value.scrollTop = chatScrollRef.value.scrollHeight
    }
  })
}

/** 自适应调整多行输入框高度（最小 38px，最大 200px 限制，超高自动滚动） */
function adjustTextareaHeight() {
  const el = textareaRef.value
  if (!el) return
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

function triggerFileInput() {
  fileInputRef.value?.click()
}

const ALLOWED_ATTACHMENT_SUFFIXES = new Set([
  '.md', '.txt', '.html', '.pdf', '.json', '.yaml', '.yml', '.xlsx', '.xls', '.csv', '.jsonl',
  '.doc', '.docx', '.wav', '.mp3', '.png', '.jpg', '.jpeg', '.webp', '.gif',
])

function hasAllowedAttachmentSuffix(file: File): boolean {
  const dotIndex = file.name.lastIndexOf('.')
  return dotIndex >= 0 && ALLOWED_ATTACHMENT_SUFFIXES.has(file.name.slice(dotIndex).toLowerCase())
}

function createAttachmentPreviewUrl(file: File): string {
  const url = URL.createObjectURL(file)
  localAttachmentUrls.add(url)
  return url
}

function releaseAttachmentPreviewUrl(file: Pick<StagedAttachment, 'previewUrl'>) {
  if (!file.previewUrl || !localAttachmentUrls.has(file.previewUrl)) return
  URL.revokeObjectURL(file.previewUrl)
  localAttachmentUrls.delete(file.previewUrl)
}

/** 把文件加入暂存架并立即上传，发送时只把成功换取的 file_id 写入 WS 消息。 */
async function stageAttachmentFiles(files: File[]) {
  const validFiles: File[] = []
  let invalidCount = 0
  for (const file of files) {
    if (!file.size || file.size > 20 * 1024 * 1024 || !hasAllowedAttachmentSuffix(file)) {
      invalidCount += 1
      continue
    }
    validFiles.push(file)
  }
  if (invalidCount) {
    message.error('有附件为空、格式不支持或超过 20MB，请检查后重试')
  }

  await Promise.all(validFiles.map(async (file) => {
    const staged: StagedAttachment = {
      localId: createClientMessageId(),
      id: '',
      name: file.name,
      size: file.size,
      contentType: file.type,
      previewUrl: createAttachmentPreviewUrl(file),
      file,
      uploading: true,
      uploadProgress: 0,
      error: false,
    }
    stagedFiles.value.push(staged)
    try {
      const res = await api.files.upload(file, (percent) => {
        const current = stagedFiles.value.find((item) => item.localId === staged.localId)
        if (current) current.uploadProgress = percent
      })
      const current = stagedFiles.value.find((item) => item.localId === staged.localId)
      if (!current) return
      current.id = res.id
      current.contentType = res.content_type || file.type
      current.uploading = false
      current.uploadProgress = 100
      message.success(`附件 ${file.name} 已上传`)
    } catch {
      const current = stagedFiles.value.find((item) => item.localId === staged.localId)
      if (!current) return
      current.uploading = false
      current.error = true
      message.error(`附件 ${file.name} 上传失败`)
    }
  }))
}

/** 文件选择支持多选，与拖拽上传共用同一校验和上传流程。 */
async function handleFileUpload(e: Event) {
  const target = e.target as HTMLInputElement
  const files = Array.from(target.files || [])
  target.value = ''
  if (files.length) await stageAttachmentFiles(files)
}

/** 拖拽进入时用深度计数避免经过子节点触发闪烁。 */
function handleDragEnter(e: DragEvent) {
  if (!e.dataTransfer?.types.includes('Files')) return
  dragDepth += 1
  isDragActive.value = true
}

function handleDragOver(e: DragEvent) {
  if (!e.dataTransfer?.types.includes('Files')) return
  e.dataTransfer.dropEffect = 'copy'
  isDragActive.value = true
}

function handleDragLeave() {
  dragDepth = Math.max(0, dragDepth - 1)
  if (dragDepth === 0) isDragActive.value = false
}

function handleDrop(e: DragEvent) {
  dragDepth = 0
  isDragActive.value = false
  const files = Array.from(e.dataTransfer?.files || [])
  if (files.length) void stageAttachmentFiles(files)
}

function removeStagedFile(localId: string) {
  const index = stagedFiles.value.findIndex((file) => file.localId === localId)
  if (index < 0) return
  const [removed] = stagedFiles.value.splice(index, 1)
  if (removed) releaseAttachmentPreviewUrl(removed)
}

/** 键盘事件监听：Enter 发送，Shift + Enter 换行。 */
function handleKeydown(e: KeyboardEvent) {
  if (e.key === 'Enter') {
    if (e.shiftKey) {
      // Shift + Enter: 允许原生换行，并在 DOM 渲染后重新计算自适应高度
      nextTick(() => {
        adjustTextareaHeight()
      })
    } else if (!e.isComposing) {
      // 纯 Enter: 发送消息
      e.preventDefault()
      handleSendClick()
    }
  }
}

function handleSendClick() {
  if (isGenerating.value) {
    // /stop：只停本轮生成，走 user_message，不清 queued 任务
    if (agentWs?.isConnected) {
      agentWs.sendUserMessage('/stop', [], createClientMessageId())
    } else {
      setCurrentGenerating(false)
      pushAgentMessage('<p class="muted">已暂停生成。已入队的任务不受影响。</p>')
    }
    scrollToBottom()
    return
  }
  const text = inputText.value.trim()
  if (isUploadingAttachments.value) return
  if (!text && !hasUploadedAttachments.value) return

  const files = [...stagedFiles.value]
  stagedFiles.value = []
  inputText.value = ''
  adjustTextareaHeight()

  void handleUserSend(text, files)
}

/** 快捷芯片/能力卡点击仅填入输入框并聚焦，由用户确认后再发送（对齐原型行为）。 */
function sendPredefined(prompt: string) {
  inputText.value = prompt
  nextTick(() => {
    adjustTextareaHeight()
    textareaRef.value?.focus()
  })
}

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
function activateCreatedSession(session: AgentSession) {
  bindingPanelOpen.value = false
  currentSessionId.value = session.id
  const runtime = ensureRuntime(session.id)
  events.value = runtime.events
  isGenerating.value = runtime.isGenerating
  turnLatencyMs.value = runtime.turnLatencyMs
  activeTask.value = runtime.activeTask
  currentContextMeter.value = runtime.contextMeter
  currentCompactSummary.value = runtime.compactSummary
  dockClosingNote.value = ''
  agentWs = null
  isWsOnline.value = api.isMock()
  markGenerating(session.id, runtime.isGenerating)
}

/** F3/G5：打开草稿绑定面板并加载可选工作区（仅属主自己的，无 share）。 */
async function openBindingPanel() {
  if (currentSessionId.value) return
  bindingPanelOpen.value = !bindingPanelOpen.value
  if (!bindingPanelOpen.value || bindableWorkspaces.value.length) return
  bindingLoading.value = true
  try {
    const payload = await api.workspaces.list()
    const items = Array.isArray(payload) ? payload : payload.items || []
    bindableWorkspaces.value = items.map((item) => ({
      id: String(item.id),
      name: String(item.name),
    }))
  } catch {
    message.error('加载工作区失败')
  } finally {
    bindingLoading.value = false
  }
}

function pickDraftWorkspace(id: string, name: string) {
  // S2 修复：绑定仅草稿态可操作（已激活会话绑定随创建固化，不可事后设置）
  if (currentSessionId.value) {
    bindingPanelOpen.value = false
    return
  }
  draftWorkspaceId.value = id
  draftWorkspaceName.value = name
  bindingPanelOpen.value = false
}

/** 面板内新建工作区并自动选中（即建即绑；失败保留面板与输入，便于重试）。 */
async function createDraftWorkspace() {
  const name = newWorkspaceName.value.trim()
  if (!name || newWorkspaceBusy.value || currentSessionId.value) return
  newWorkspaceBusy.value = true
  try {
    const created = await api.workspaces.create(name)
    bindableWorkspaces.value.unshift({
      id: String(created.id),
      name: String(created.name),
    })
    newWorkspaceName.value = ''
    pickDraftWorkspace(String(created.id), String(created.name))
    message.success('工作区已创建并绑定该会话')
  } catch (err: any) {
    message.error(err?.message || '创建工作区失败')
  } finally {
    newWorkspaceBusy.value = false
  }
}

function clearDraftWorkspace() {
  draftWorkspaceId.value = null
  draftWorkspaceName.value = ''
  bindingPanelOpen.value = false
}

/** 首次发送消息时才向服务端创建会话；mock 列表已由 API 层写入时避免重复插入。 */
async function ensureActiveSession(): Promise<boolean> {
  if (currentSessionId.value) return true
  if (isCreatingSession.value) return false
  isCreatingSession.value = true
  try {
    const newSession = await api.sessions.create('新会话', {
      workspaceId: draftWorkspaceId.value || undefined,
    })
    // 绑定已随会话固化（会话卡片展示 workspace_name）；草稿预选清空防误带。
    clearDraftWorkspace()
    if (!sessions.value.some((session) => session.id === newSession.id)) {
      sessions.value.unshift(newSession)
    }
    activateCreatedSession(newSession)
    return true
  } catch (err: any) {
    message.error(err?.message || '新建会话失败')
    return false
  } finally {
    isCreatingSession.value = false
  }
}

/** 确保当前会话的实时连接已建立，首次发送和报告解读共用此连接门禁。 */
async function ensureLiveAgentSocket(): Promise<boolean> {
  const sid = currentSessionId.value
  if (!sid || api.isMock()) return false
  if (agentWs?.isConnected && (!agentWs.sessionId || agentWs.sessionId === sid)) return true
  const ws = initWebSocket(sid)
  const connected = await waitForWebSocketConnection(ws)
  return connected && currentSessionId.value === sid && agentWs === ws && ws.isConnected
}

async function handleUserSend(text: string, files: any[] = []) {
  if (isCreatingSession.value) return
  // 页面初始态是草稿，首次发送才创建持久化会话。
  if (!currentSessionId.value && !(await ensureActiveSession())) return
  const targetSessionId = currentSessionId.value
  const clientMessageId = createClientMessageId()
  // 新回合开始前封口上一轮打字机，避免第二轮 chunk 写进同一气泡
  events.value.forEach((item) => {
    if (item.type === 'agent' && item.streaming) item.streaming = false
  })
  events.value.push({
    type: 'user',
    text,
    files,
    clientMessageId,
    author: authStore.user
      ? {
          id: authStore.user.id,
          username: authStore.user.username,
          display_name: authStore.user.display_name,
        }
      : null,
  })
  setCurrentGenerating(true)
  turnLatencyMs.value = 0
  scrollToBottom(true)

  // 首发消息后先用首条消息截断做乐观标题占位；服务端 AI 标题生成完成后
  // 经 session_title 事件（API.md §4.3）覆盖，刷新后以服务端为准。
  const session = sessions.value.find(s => s.id === targetSessionId)
  if (session && session.title === '新会话' && text) {
    session.title = text.slice(0, 18)
  }

  if (!api.isMock() && !(await ensureLiveAgentSocket())) {
    setCurrentGenerating(false)
    events.value.push({ type: 'error', code: 'UPSTREAM', message: 'Agent 连接未就绪，请等待重连后重试。' })
    message.error('Agent 连接未就绪，请等待重连后重试')
    scrollToBottom()
    return
  }

  // 会话匹配守卫：等待连接期间若用户切换了会话，不能把消息发送到新页面的错误连接。
  if (currentSessionId.value !== targetSessionId) return
  if (agentWs?.isConnected && (!agentWs.sessionId || agentWs.sessionId === targetSessionId)) {
    // 打字占位气泡：服务端流式开始前给用户即时反馈，收到任意事件后移除
    events.value.push({ type: 'typing' })
    scrollToBottom()
    // 契约：attachments = [{ file_id }]，仅回传上传成功的附件，失败附件按提示忽略
    agentWs.sendUserMessage(
      text,
      files.filter(f => f.id).map(f => ({ file_id: f.id })),
      clientMessageId,
    )
  } else if (api.isMock()) {
    // 显式 mock 模式保留本地演示，实时模式绝不伪造任务、资产或报告。
    simulateAgentFlow(text, files)
  } else {
    setCurrentGenerating(false)
    events.value.push({ type: 'error', code: 'UPSTREAM', message: 'Agent 连接未就绪，请等待重连后重试。' })
    message.error('Agent 连接未就绪，请等待重连后重试')
    scrollToBottom()
  }
}

/** Mock 模式：本地模拟一次纯文本回复（不再伪造思考卡/工具/确认卡）。 */
function simulateAgentFlow(text: string, _files: any[]) {
  const turn = getOrCreateTurnAgent(events.value)
  trackTimeout(() => {
    pushAgentMessage(`<p>已收到你的消息：<b>${escapeHtml(text.slice(0, 120))}</b>。</p><p>（当前为显式 mock 模式：仅演示纯对话回复，实时评测任务请连接真实服务端。）</p>`)
    setCurrentGenerating(false)
    scrollToBottom()
  }, 600)
}

function handleInterpretReport(reportId: string) {
  /**
   * AgentLoop 的提交由工作台冻结 request_id、思考档位与附件后统一发送。
   * 此处只写入草稿，避免 v2 会话被旧 WebSocket 入口误发。
   */
  const draft = loopStore.draft(currentSessionId.value || 'draft')
  draft.content = `请解读报告 #${reportId}`
  message.info('已将报告解读请求填入 AgentLoop 输入框')
}

function handleCancelActiveTask(taskId: string) {
  if (!canCancelActiveTask.value || activeTask.value?.id !== taskId) {
    message.error('仅任务创建者可以取消任务')
    return
  }
  if (cancellingTaskId.value === taskId) return
  dialog.warning({
    title: '取消任务？',
    content: '将在当前样本推理完成后停止，已完成的评测得分与报文将完整保留。',
    positiveText: '确认取消',
    negativeText: '放弃',
    onPositiveClick: async () => {
      if (cancellingTaskId.value === taskId) return
      cancellingTaskId.value = taskId
      try {
        // 契约：优先使用 WS 上行 cancel_task；发送失败才回退 REST，避免链路半开时静默丢请求。
        const sentByWs = agentWs?.sendCancelTask(taskId) ?? false
        if (sentByWs) {
          message.info('取消请求已提交，等待服务端确认')
          return
        }
        const cancelled = await api.tasks.cancel(taskId)
        finishCancelledTask(cancelled.id)
        message.success('评测任务已取消（cancelled）')
      } catch (err: any) {
        if (cancellingTaskId.value === taskId) cancellingTaskId.value = null
        message.error(err?.message || '取消请求失败，请稍后重试')
      }
    },
  })
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
async function handleSelectAgentModel(key: string) {
  if (key === '__goto_profiles__') {
    router.push('/admin/profiles')
    return
  }
  const hit = allProfiles.value.find((p) => p.id === key)
  if (!hit) return
  try {
    await api.admin.updateSettings({ agent_profile_id: key })
    currentAgentProfileId.value = key
    message.success(`已将 Agent 驱动模型切换为「${hit.name}」(${hit.model || hit.protocol})`)
  } catch (err: any) {
    message.error(err.message || '切换模型失败')
  }
}

/** F4 会话历史回放：按回合容器恢复模型头部与助手正文的顺序。 */
async function loadSessionHistory(sid: string): Promise<number> {
  if (deletingSessionIds.has(sid)) return 0
  try {
    const history = await api.sessions.getMessages(sid)
    interface TimelineItem {
      time: number
      priority: number
      eventId?: number
      item: StreamItem
    }
    const rawList: TimelineItem[] = []

    // 1. 收集 user 与 assistant 历史消息
    for (const m of history.messages || []) {
      const t = m.created_at ? new Date(m.created_at).getTime() : 0
      if (m.role === 'user') {
        rawList.push({
          time: t,
          priority: 1,
          item: {
            type: 'user',
            text: m.content || '',
            files: normalizeMessageFiles(m.attachments),
            messageId: m.id,
            clientMessageId: m.client_message_id || undefined,
            author: m.author || null,
            noAnim: true,
          },
        })
      } else if (m.role === 'assistant') {
        const logoKey = resolveMessageLogoKey(m)
        const modelName = resolveMessageModelName(m)
        const profileName = resolveMessageProfileName(m)
        rawList.push({
          time: t,
          priority: 5,
          item: {
            type: 'agent',
            text: m.content || '',
            raw: m.content || '',
            latency_ms: m.latency_ms ?? undefined,
            providerLogoKey: logoKey,
            profileId: m.profile_id || undefined,
            modelName: modelName,
            profileName: profileName,
            createdAt: m.created_at,
            noAnim: true,
          },
        })
      }
    }

    // 2. 收集 WS 事件流：骨架版只回放错误与报告；历史 thought/tool/plan/confirm
    //    /clarify 等旧范式事件一律不再渲染。
    for (const ev of history.events || []) {
      const p = ev.payload || {}
      const t = ev.ts ? new Date(ev.ts).getTime() : 0
      const eid = Number(ev.event_id) || 0

      if (ev.event === 'error') {
        rawList.push({
          time: t,
          priority: 7,
          eventId: eid,
          item: { type: 'error', code: p.code, message: p.message, noAnim: true },
        })
      } else if (ev.event === 'report' && p.report_id) {
        rawList.push({
          time: t,
          priority: 6,
          eventId: eid,
          item: { type: 'report', reportId: p.report_id, noAnim: true },
        })
      } else if (ev.event === 'confirm') {
        // V1.67：历史卡默认按已处理只读回放；当前仍待确认的卡由
        // sessions.pending_confirm 在回放末尾覆盖为可编辑卡。
        rawList.push({
          time: t,
          priority: 4,
          eventId: eid,
          item: {
            type: 'confirm',
            card: normalizeConfirmCard(p),
            confirmAuthor: p.confirm_author || null,
            isAcked: true,
            summary: '',
            open: false,
            noAnim: true,
          },
        })
      } else if (ev.event === 'confirm_ack') {
        const confirm = [...rawList].reverse().find(x => x.item.type === 'confirm')
        if (confirm) {
          confirm.item.isAcked = true
          confirm.item.ackResult = Boolean(p.ok)
          confirm.item.open = false
        }
      } else if (ev.event === 'tool_approval') {
        // V1.70：历史审批卡只读回放；其后紧跟的 tool_approval_ack 会盖章终态。
        rawList.push({
          time: t,
          priority: 4,
          eventId: eid,
          item: {
            type: 'toolApproval',
            approval: p,
            approvalDone: null,
            noAnim: true,
          },
        })
      } else if (ev.event === 'tool_approval_ack') {
        const target = [...rawList].reverse().find(
          x => x.item.type === 'toolApproval' && x.item.approval?.id === p.approval_id,
        )
        if (target) target.item.approvalDone = p.action === 'approve' ? 'approved' : 'rejected'
      } else if (ev.event === 'approval_terminal') {
        // V1.73/F5-G6：历史卡终态只读回放（expired/cancelled/voided/recovery_failed）
        // M3：payload.card_type=clarify → 澄清卡 recovery_failed（标 failed）；
        // 其余/缺省（旧事件）→ 审批卡终态。
        const terminal = ['expired', 'cancelled', 'voided', 'recovery_failed'].includes(p.outcome)
        if (terminal && p.card_type === 'clarify') {
          const target = [...rawList].reverse().find(
            x => x.item.type === 'clarify' && x.item.clarify?.id === p.approval_id,
          )
          if (target) target.item.clarifyDone = 'failed'
        } else if (terminal) {
          const target = [...rawList].reverse().find(
            x => x.item.type === 'toolApproval' && x.item.approval?.id === p.approval_id,
          )
          if (target) target.item.approvalDone = p.outcome
        }
      } else if (ev.event === 'clarify') {
        // V1.72（dsh #1）：历史澄清卡只读回放；其后紧跟的 clarify_ack 会盖章终态。
        rawList.push({
          time: t,
          priority: 4,
          eventId: eid,
          item: {
            type: 'clarify',
            clarify: p,
            clarifyDone: null,
            noAnim: true,
          },
        })
      } else if (ev.event === 'clarify_ack') {
        const target = [...rawList].reverse().find(
          x => x.item.type === 'clarify' && x.item.clarify?.id === p.id,
        )
        if (target) target.item.clarifyDone = 'submitted'
      }
    }

    // 3. 持久化事件优先按 event_id 排序；消息与事件之间按时间戳，再按展示优先级兜底
    rawList.sort((a, b) => {
      if (a.eventId && b.eventId) return a.eventId - b.eventId
      if (a.time !== b.time) return a.time - b.time
      return a.priority - b.priority
    })

    // 4. 将事件块折叠进同一助手回合，模型名称和时间只渲染一次。
    const replay: StreamItem[] = []
    let activeTurn: StreamItem | null = null
    const ensureReplayTurn = (source: StreamItem, time: number): StreamItem => {
      if (!activeTurn) {
        activeTurn = getOrCreateTurnAgent(replay, {
          providerLogoKey: source.providerLogoKey,
          profileId: source.profileId,
          modelName: source.modelName,
          profileName: source.profileName,
          createdAt: source.createdAt || (time > 0 ? new Date(time).toISOString() : undefined),
          noAnim: true,
        })
        activeTurn.noAnim = true
        activeTurn.streaming = false
      }
      return activeTurn
    }

    for (const timeline of rawList) {
      const item = timeline.item
      if (item.type === 'user') {
        replay.push(item)
        activeTurn = null
        continue
      }
      if (item.type === 'agent') {
        const turn = ensureReplayTurn(item, timeline.time)
        turn.profileId = item.profileId || turn.profileId
        turn.providerLogoKey = item.providerLogoKey || turn.providerLogoKey
        turn.modelName = item.modelName || turn.modelName
        turn.profileName = item.profileName || turn.profileName
        turn.createdAt = item.createdAt || turn.createdAt
        if (item.raw || item.text) {
          const block = getOrCreateAssistantBlock(turn)
          block.raw = item.raw || item.text || ''
          block.text = item.text || item.raw || ''
          block.latency_ms = item.latency_ms
          block.streaming = false
        }
        turn.streaming = false
        continue
      }
      replay.push(item)
      if (item.type === 'error' || item.type === 'report' || item.type === 'confirm') {
        activeTurn = null
      }
    }

    // V1.67：仍待确认的卡以 sessions.pending_confirm 为准覆盖为可编辑卡
    // （API.md §3.4：前端优先该字段做成可编辑卡，events 里的 confirm 只作只读回放）。
    if (history.pending_confirm) {
      const card = normalizeConfirmCard({
        ...history.pending_confirm,
        confirm_author: history.pending_confirm_author || undefined,
      })
      const existing = [...replay].reverse().find(x => x.type === 'confirm')
      if (existing) {
        existing.card = card
        existing.confirmAuthor = history.pending_confirm_author || null
        existing.isAcked = false
        existing.open = true
      } else {
        replay.push({
          type: 'confirm',
          card,
          confirmAuthor: history.pending_confirm_author || null,
          isAcked: false,
          summary: '',
          open: true,
          noAnim: true,
        })
      }
    }

    currentContextMeter.value = history.context_meter || null
    currentCompactSummary.value = history.compact_summary || null

    const rt = ensureRuntime(sid)
    // 本轮仍在生成时服务端回放可能落后于内存流，避免用旧快照盖掉正在产出的卡片
    if (!rt.isGenerating) {
      rt.events = replay
    }
    rt.contextMeter = history.context_meter || null
    rt.compactSummary = history.compact_summary || null
    if (sid === currentSessionId.value) {
      events.value = rt.events
      currentContextMeter.value = rt.contextMeter
      currentCompactSummary.value = rt.compactSummary
      if (rt.events.length) scrollToBottom(true)
    }
    const eventIds = [
      ...(history.events || []).map((e: any) => Number(e?.event_id) || 0),
      ...(history.messages || []).map((m: any) => Number(m?.event_id) || 0),
    ]
    return eventIds.length ? Math.max(0, ...eventIds) : 0
  } catch (err: any) {
    // 软删除或权限收回后，清理旧列表缓存，避免用户再次点击幽灵会话。
    if (err?.status === 404 && sessions.value.some((session) => session.id === sid)) {
      removeInaccessibleSession(sid)
    }
    return 0
  }
}

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

function initWebSocket(sessionId: string, lastEventId = 0): AgentWebSocket {
  const reused = sockets.get(sessionId)
  if (reused) {
    agentWs = reused
    isWsOnline.value = reused.isConnected
    gcIdleSockets(sessionId)
    return reused
  }

  gcIdleSockets(sessionId)

  const ws = new AgentWebSocket(sessionId)
  if (lastEventId > 0) ws.lastEventId = lastEventId
  ws.onStatus((connected) => {
    if (sessionId === currentSessionId.value) {
      isWsOnline.value = connected
    }
  })
  ws.onClosed((code) => {
    if (code === 4401) message.info('短票过期，重新连接中')
    if (code === 4404) removeInaccessibleSession(sessionId)
  })
  ws.onEvent((ev: WsServerEvent) => {
    const sid = (ev.session_id || sessionId || currentSessionId.value || '') as string
    if (sid && sid !== currentSessionId.value) {
      ingestBackground(sid, ev)
      return
    }
    handleWsEvent(ev)
  })
  sockets.set(sessionId, ws)
  agentWs = ws
  ws.connect()
  return ws
}

/** 等待 WebSocket 首次连接完成，避免草稿首条消息落在连接竞态窗口内。 */
function waitForWebSocketConnection(ws: AgentWebSocket, timeoutMs = 10000): Promise<boolean> {
  if (ws.isConnected) return Promise.resolve(true)
  return new Promise((resolve) => {
    let timer: number | null = null
    let unsubscribe = () => {}
    const finish = (connected: boolean) => {
      if (timer !== null) window.clearTimeout(timer)
      unsubscribe()
      resolve(connected)
    }
    unsubscribe = ws.onStatus((connected) => {
      if (connected) finish(true)
    })
    timer = window.setTimeout(() => finish(ws.isConnected), timeoutMs)
  })
}

/** 移除打字占位气泡：服务端首个事件到达即表明流式已开始。 */
function dismissTyping() {
  const idx = events.value.findIndex((e) => e.type === 'typing')
  if (idx >= 0) events.value.splice(idx, 1)
}

/** 把纯文本渲染为气泡 HTML（转义防 XSS + 换行转 <br>）。 */
function renderBubbleHtml(raw: string): string {
  return escapeHtml(raw).replace(/\n/g, '<br>')
}

/** 本轮最后一条用户消息之后仍在流式的助手气泡。 */
function turnStreamingAgent(list: StreamItem[]): StreamItem | undefined {
  let from = -1
  for (let i = list.length - 1; i >= 0; i--) {
    if (list[i].type === 'user') {
      from = i
      break
    }
  }
  for (let i = list.length - 1; i > from; i--) {
    const item = list[i]
    if (item.type === 'agent' && item.streaming) return item
  }
  return undefined
}

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
async function refreshContextMeter(sid: string) {
  if (!sid || deletingSessionIds.has(sid)) return
  try {
    const history = await api.sessions.getMessages(sid)
    const rt = ensureRuntime(sid)
    rt.contextMeter = history.context_meter || null
    rt.compactSummary = history.compact_summary || null
    if (sid === currentSessionId.value) {
      currentContextMeter.value = rt.contextMeter
      currentCompactSummary.value = rt.compactSummary
    }
  } catch {
    /* 仪表刷新失败不挡对话 */
  }
}

/** AI 生成的会话标题回写侧边栏；currentSession 是列表派生值，头部标题随之联动。 */
function applySessionTitle(sid: string, title: string) {
  const trimmed = title.trim()
  if (!trimmed) return
  const target = sessions.value.find(s => s.id === sid)
  if (target) target.title = trimmed
}

/** 后台会话继续生成：把事件写入该会话缓存，不打断当前正在看的对话。 */
function ingestBackground(sid: string, ev: WsServerEvent) {
  if (ev.event === 'pong') return
  const rt = ensureRuntime(sid)
  const buf = rt.events
  const p = ev.payload || {}
  switch (ev.event) {
    case 'user_message':
    case 'message': {
      const messageId = String(p.id || '')
      const clientMessageId = typeof p.client_message_id === 'string' ? p.client_message_id : ''
      const existing = buf.find((item) => (
        item.type === 'user'
        && ((messageId && item.messageId === messageId)
          || (clientMessageId && item.clientMessageId === clientMessageId))
      ))
      const author = p.author && typeof p.author === 'object' ? p.author as SessionAuthor : null
      if (existing) {
        existing.messageId = messageId || existing.messageId
        existing.clientMessageId = clientMessageId || existing.clientMessageId
        existing.author = author || existing.author
        existing.files = normalizeMessageFiles(p.attachments)
      } else {
        buf.push({
          type: 'user',
          text: String(p.content || ''),
          files: normalizeMessageFiles(p.attachments),
          messageId: messageId || undefined,
          clientMessageId: clientMessageId || undefined,
          author,
        })
      }
      if (author?.id && author.id !== authStore.user?.id) {
        markGenerating(sid, true)
      }
      break
    }
    case 'assistant_delta': {
      const delta = String(p.text || '')
      if (!delta) break
      const agent = getOrCreateTurnAgent(buf)
      const target = getOrCreateAssistantBlock(agent)
      target.raw = (target.raw || '') + delta
      target.text = renderBubbleHtml(target.raw)
      target.streaming = true
      agent.streaming = true
      markGenerating(sid, true)
      break
    }
    case 'assistant_message': {
      const text = String(p.text || '')
      const targetAgent = getOrCreateTurnAgent(buf, messageMetaFromPayload(p))
      const target = getOrCreateAssistantBlock(targetAgent)
      if (text) {
        target.raw = text
        target.text = renderBubbleHtml(text)
        target.streaming = false
        if (typeof p.reply_latency_ms === 'number') target.latency_ms = p.reply_latency_ms
      } else {
        target.streaming = false
      }
      targetAgent.streaming = false
      markGenerating(sid, false)
      rt.harnessStage = ''
      void refreshContextMeter(sid)
      break
    }
    case 'response.completed':
    case 'done': {
      const agent = getCurrentTurnAgent(buf)
      if (agent) agent.streaming = false
      const orphan = turnStreamingAgent(buf)
      if (orphan) orphan.streaming = false
      markGenerating(sid, false)
      rt.harnessStage = ''
      break
    }
    case 'confirm':
      markGenerating(sid, false)
      rt.harnessStage = ''
      buf.push({
        type: 'confirm',
        card: normalizeConfirmCard(p),
        confirmAuthor: p.confirm_author || null,
        isAcked: false,
        summary: '',
        open: true,
      })
      break
    case 'confirm_ack': {
      const confirm = [...buf].reverse().find(x => x.type === 'confirm')
      if (confirm) {
        stampConfirmCard(confirm, Boolean(p.ok))
        if (!p.ok) confirm.summary = ''
      }
      void refreshContextMeter(sid)
      break
    }
    case 'error':
      markGenerating(sid, false)
      rt.activeTask = null
      buf.push({ type: 'error', code: p.code, message: p.message || '执行遇到错误' })
      break
    case 'report':
      markGenerating(sid, false)
      rt.activeTask = null
      if (p.report_id) buf.push({ type: 'report', reportId: p.report_id })
      break
    case 'task_cancelled':
      // 取消结果是平台任务流，不再伪装为已移除的 tool_result。
      if (ev.task_id && rt.activeTask?.id === ev.task_id) rt.activeTask = null
      break
    case 'progress': {
      if (ev.task_id) {
        const progress = { percent: p.percent, done: p.done, total: p.total, message: p.message }
        if (!rt.activeTask || rt.activeTask.id !== ev.task_id) {
          rt.activeTask = {
            id: ev.task_id,
            kind: 'benchmark',
            status: 'running',
            config: {},
            progress,
            created_at: new Date().toISOString(),
          }
        } else {
          rt.activeTask.progress = progress
        }
        if ((progress.percent ?? 0) >= 100) rt.activeTask = null
      }
      break
    }
    case 'session_title': {
      // AI 生成的会话标题（API.md §4.3）：同步侧边栏，重连回放幂等
      applySessionTitle(ev.session_id, String(p.title || ''))
      break
    }
    default:
      break
  }
}

function handleWsEvent(ev: WsServerEvent) {
  // 用户自己的 user_message 回显不是「本轮已出结果」。过早移除打字占位时，
  // 流式开始前对话区只剩用户气泡，看起来像模型没有回复。
  // session_title 在首轮期间到达，同样不属于回合产出，不收占位气泡。
  if (
    ev.event !== 'pong' &&
    ev.event !== 'message' &&
    ev.event !== 'user_message' &&
    ev.event !== 'session_title'
  ) {
    dismissTyping()
  }
  const p = ev.payload || {}
  switch (ev.event) {
    case 'user_message':
    case 'message': {
      // 用户消息已同时存在于 REST 历史与 WS 事件中；按服务端 ID 或浏览器幂等键合并。
      const messageId = String(p.id || '')
      const clientMessageId = typeof p.client_message_id === 'string' ? p.client_message_id : ''
      const existing = events.value.find((item) => (
        item.type === 'user'
        && ((messageId && item.messageId === messageId)
          || (clientMessageId && item.clientMessageId === clientMessageId))
      ))
      const author = p.author && typeof p.author === 'object' ? p.author as SessionAuthor : null
      if (existing) {
        existing.messageId = messageId || existing.messageId
        existing.clientMessageId = clientMessageId || existing.clientMessageId
        existing.author = author || existing.author
        existing.files = normalizeMessageFiles(p.attachments)
      } else {
        events.value.push({
          type: 'user',
          text: String(p.content || ''),
          files: normalizeMessageFiles(p.attachments),
          messageId: messageId || undefined,
          clientMessageId: clientMessageId || undefined,
          author,
        })
      }
      // 协作者发言意味着本会话即将生成一轮回复，复用现有阶段提示与流式气泡。
      if (author?.id && author.id !== authStore.user?.id) {
        isGenerating.value = true
        turnLatencyMs.value = 0
      }
      scrollToBottom()
      break
    }
    case 'assistant_delta': {
      const delta = String(p.text || '')
      if (!delta) break
      const agent = getOrCreateTurnAgent(events.value)
      const target = getOrCreateAssistantBlock(agent)
      target.raw = (target.raw || '') + delta
      target.text = renderBubbleHtml(target.raw)
      target.streaming = true
      agent.streaming = true
      scrollToBottom()
      setCurrentGenerating(true)
      break
    }
    case 'assistant_message': {
      const text = String(p.text || '')
      // assistant_message 携带服务端实际使用的协议档快照；以 profile_id 覆盖
      // 回合创建时的全局选择，保证切换模型后每个回合仍显示自己的模型。
      const targetAgent = getOrCreateTurnAgent(events.value, messageMetaFromPayload(p))
      const target = getOrCreateAssistantBlock(targetAgent)
      if (text) {
        target.raw = text
        target.text = renderBubbleHtml(text)
        target.streaming = false
        if (typeof p.reply_latency_ms === 'number') target.latency_ms = p.reply_latency_ms
      } else {
        target.streaming = false
      }
      targetAgent.streaming = false
      setCurrentGenerating(false)
      if (typeof p.reply_latency_ms === 'number') turnLatencyMs.value = p.reply_latency_ms
      if (currentSessionId.value) void refreshContextMeter(currentSessionId.value)
      if (text) scrollToBottom()
      break
    }
    case 'tool_call': {
      // H3 Agent TAOR：Act 发起即入列（幂等：同 call_id 不重复追加）。
      const agent = getOrCreateTurnAgent(events.value)
      const toolItems = agent.toolItems || (agent.toolItems = [])
      const callId = String(p.call_id || '')
      if (callId && !toolItems.some((t) => t.call_id === callId)) {
        toolItems.push(
          reactive({
            call_id: callId,
            name: String(p.name || 'unknown'),
            arguments: p.arguments,
            status: 'running',
          }) as ToolRunItem,
        )
      }
      agent.streaming = true
      scrollToBottom()
      break
    }
    case 'tool_result': {
      // H3：工具终态回填对应卡片（error 展示脱敏原因，不含观察全文）。
      const agent = getCurrentTurnAgent(events.value)
      const tool = agent?.toolItems?.find((t) => t.call_id === String(p.call_id || ''))
      if (!tool) break
      tool.ok = p.ok !== false
      tool.status = p.ok === false ? 'error' : 'done'
      if (p.ok === false) tool.error = String(p.error || '工具执行失败')
      scrollToBottom()
      break
    }
    case 'response.completed':
    case 'done': {
      const orphan = turnStreamingAgent(events.value)
      if (orphan) orphan.streaming = false
      setCurrentGenerating(false)
      break
    }
    case 'tool_approval': {
      // H5 HITL：危险命令执行前中断，落审批卡（可折叠只读展开命令全文）。
      setCurrentGenerating(false)
      harnessStage.value = ''
      const id = String(p.id || '')
      if (id && !events.value.some(e => e.type === 'toolApproval' && e.approval?.id === id)) {
        events.value.push(
          reactive({
            type: 'toolApproval',
            approval: p,
            approvalDone: null,
          }) as StreamItem,
        )
      }
      scrollToBottom()
      break
    }
    case 'tool_approval_ack': {
      const target = [...events.value].reverse().find(
        e => e.type === 'toolApproval' && e.approval?.id === p.approval_id,
      )
      if (target) {
        target.approvalDone = p.action === 'approve' ? 'approved' : 'rejected'
        target.streaming = false
      }
      break
    }
    case 'approval_terminal': {
      // V1.73（#3）：审批卡终态——expired（TTL 超时）/cancelled（/stop 放弃）
      // 与用户 reject 区分；F5/G6（M-R3-7）成组扩展：voided（检查点缺失卡
      // 作废）/recovery_failed（resume 恢复失败）→ 同为终态禁操作。
      // M3：payload.card_type 按卡型路由——clarify → 澄清卡 recovery_failed
      // 终态；其余/缺省（旧事件）→ 审批卡（行为不回归）。
      const terminal = ['expired', 'cancelled', 'voided', 'recovery_failed'].includes(p.outcome)
      if (!terminal) break
      if (p.card_type === 'clarify') {
        const clarify = [...events.value].reverse().find(
          e => e.type === 'clarify' && e.clarify?.id === p.approval_id,
        )
        if (clarify) {
          clarify.clarifyDone = 'failed'
          clarify.streaming = false
          setCurrentGenerating(false)
        }
      } else {
        const target = [...events.value].reverse().find(
          e => e.type === 'toolApproval' && e.approval?.id === p.approval_id,
        )
        if (target) {
          target.approvalDone = p.outcome
          target.streaming = false
          setCurrentGenerating(false)
        }
      }
      break
    }
    case 'clarify': {
      // V1.72（dsh #1）：ask_user_question 图内中断落澄清卡（问卷一次作答）
      setCurrentGenerating(false)
      harnessStage.value = ''
      const id = String(p.id || '')
      if (id && !events.value.some(e => e.type === 'clarify' && e.clarify?.id === id)) {
        events.value.push(
          reactive({
            type: 'clarify',
            clarify: p,
            clarifyDone: null,
          }) as StreamItem,
        )
      }
      scrollToBottom()
      break
    }
    case 'clarify_ack': {
      // 服务端回执：澄清卡提交成功（resume 已派发；重复 reply 由服务端行锁拒绝）
      const target = [...events.value].reverse().find(
        e => e.type === 'clarify' && e.clarify?.id === p.id,
      )
      if (target) {
        target.clarifyDone = 'submitted'
        target.streaming = false
      }
      break
    }
    case 'confirm': {
      // V1.67 恢复：确认卡 TaskSpec 在 payload；规范化补齐 run / stress 默认值
      setCurrentGenerating(false)
      harnessStage.value = ''
      events.value.push({
        type: 'confirm',
        card: normalizeConfirmCard(p),
        confirmAuthor: p.confirm_author || null,
        isAcked: false,
        summary: '',
        open: true,
      })
      scrollToBottom()
      break
    }
    case 'confirm_ack': {
      const target = [...events.value].reverse().find(e => e.type === 'confirm')
      if (target) {
        stampConfirmCard(target, Boolean(p.ok))
        if (!p.ok) target.summary = ''
      }
      // 服务端回执（含真实 task_id）才是权威结果
      if (pendingAckItem.value && p.ok) pendingAckItem.value = null
      if (typeof p.message === 'string' && p.message) message.info(p.message)
      if (currentSessionId.value) void refreshContextMeter(currentSessionId.value)
      break
    }
    case 'progress': {
      if (ev.task_id) {
        // 契约：进度字段在 payload（percent/done/total/message）；首个进度事件到达时自动起坞
        const progress = { percent: p.percent, done: p.done, total: p.total, message: p.message }
        if (!activeTask.value || activeTask.value.id !== ev.task_id) {
          activeTask.value = {
            id: ev.task_id,
            kind: 'benchmark',
            status: 'running',
            config: {},
            progress,
            created_at: new Date().toISOString(),
          } as any
          // Worker 进度事件不携带创建者，补读任务以决定共享会话里的取消按钮归属。
          void api.tasks.get(ev.task_id).then((task) => {
            if (activeTask.value?.id === task.id) {
              activeTask.value.creator_id = task.creator_id
              activeTask.value.created_by = task.created_by
              activeTask.value.creator = task.creator
            }
          }).catch(() => undefined)
        } else {
          activeTask.value.progress = progress
        }
        if ((progress.percent ?? 0) >= 100) finishDock('任务已完成')
      }
      break
    }
    case 'report': {
      // S10 坞先显示「任务 succeeded」note，2.6s 后再隐藏
      finishDock('任务 succeeded')
      setCurrentGenerating(false)
      // 契约：report 载荷仅 { report_id }；空 id（如无报告的用例任务）不渲染报告卡，避免跳转 /reports/undefined
      if (p.report_id) {
        // 实时模式不伪造指标（对齐原型 addReportCard 占位 KPI），真实数据进报告页查看
        events.value.push({
          type: 'report',
          reportId: p.report_id,
          kpis: [{ value: '—', label: '报告已生成' }],
        })
      }
      scrollToBottom()
      break
    }
    case 'task_cancelled': {
      // 仅收到服务端持久化确认后才收起取消态，避免网络失败时出现假成功。
      if (ev.task_id) {
        finishCancelledTask(ev.task_id)
        message.success('评测任务已取消（cancelled）')
      }
      break
    }
    case 'error': {
      // 取消失败时恢复按钮；不能保留“取消中”假象阻断用户重试。
      if (cancellingTaskId.value && (!ev.task_id || ev.task_id === cancellingTaskId.value)) {
        cancellingTaskId.value = null
      }
      events.value.push({
        type: 'error',
        code: p.code,
        message: p.message || '执行遇到错误',
      })
      // 内联错误条之外同步弹出 Toast，避免用户错过失败反馈
      message.error(p.message || '执行遇到错误')
      setCurrentGenerating(false)
      scrollToBottom()
      break
    }
    case 'session_title': {
      // AI 生成的会话标题（API.md §4.3）：更新侧边栏与当前会话头部
      applySessionTitle(ev.session_id, String(p.title || ''))
      break
    }
    default:
      break
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

/** HTML 转义：历史 assistant 消息纯文本安全注入气泡（对齐原型 AE.esc）。 */
function escapeHtml(s: string) {
  return s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;')
}

/** 将历史或 WS 的文件 ID 统一成既有附件芯片可读取的对象。 */
function normalizeMessageFiles(attachments: unknown): any[] {
  if (!Array.isArray(attachments)) return []
  return attachments.map((item) => (
    typeof item === 'string' ? { id: item, name: item, size: '' } : item
  ))
}

/** 返回用户气泡展示名：自己的消息显示“我”，协作者优先显示昵称。 */
function userMessageAuthorLabel(item: StreamItem): string {
  if (!item.author) return ''
  if (item.author.id === authStore.user?.id) return '我'
  return item.author.display_name || item.author.username
}

/** 判断用户气泡是否来自当前成员以外的团队协作者。 */
function isRemoteUserMessage(item: StreamItem): boolean {
  return Boolean(item.author?.id && authStore.user?.id && item.author.id !== authStore.user.id)
}

/** 将助手消息时间格式化为原型中的 MM/DD HH:mm。 */
function formatAgentMessageTime(dateStr?: string): string {
  if (!dateStr) return ''
  const date = new Date(dateStr)
  if (Number.isNaN(date.getTime())) return ''
  const month = String(date.getMonth() + 1).padStart(2, '0')
  const day = String(date.getDate()).padStart(2, '0')
  const hours = String(date.getHours()).padStart(2, '0')
  const minutes = String(date.getMinutes()).padStart(2, '0')
  return `${month}/${day} ${hours}:${minutes}`
}

/** 记录本轮助手消息头所需的供应商、模型和协议档信息。 */
function currentAgentMessageMeta(): Pick<StreamItem, 'providerLogoKey' | 'profileId' | 'modelName' | 'profileName' | 'createdAt'> {
  return {
    providerLogoKey: agentProfileLogoKey.value,
    profileId: currentAgentProfileId.value || activeAgentProfile.value?.id || undefined,
    modelName: agentDisplayModelName.value,
    profileName: agentProfileDisplayName.value,
    createdAt: new Date().toISOString(),
  }
}

/** 追加本地演示助手消息，并同步当前 Agent 的供应商 Logo 与模型元数据。 */
function pushAgentMessage(text: string) {
  const agent = getOrCreateTurnAgent(events.value)
  const block = getOrCreateAssistantBlock(agent)
  block.raw = text
  block.text = text
  block.streaming = false
  agent.streaming = false
}

/** 解析历史消息中的供应商 Logo 标识，优先使用快照字段。 */
function resolveMessageLogoKey(m: { provider?: string | null; profile_id?: string | null; model_name?: string | null }): ProviderLogoKey {
  // 同一模型可能托管在不同供应商，必须优先按消息快照的 profile_id 取图标。
  if (m.profile_id) {
    const prof = allProfiles.value.find((p) => p.id === m.profile_id)
    if (prof) return getProviderLogoKey(prof)
  }
  if (m.model_name) {
    const key = getProviderLogoKey({ model: m.model_name })
    if (key !== 'custom') return key
  }
  if (m.provider) {
    return getProviderLogoKey({ name: m.provider, model: m.model_name || '' })
  }
  return agentProfileLogoKey.value || 'custom'
}

/** 解析历史消息中的模型显示名称，优先使用快照字段。 */
function resolveMessageModelName(m: { model_name?: string | null; profile_id?: string | null }): string {
  if (m.model_name) return m.model_name
  if (m.profile_id) {
    const prof = allProfiles.value.find((p) => p.id === m.profile_id)
    if (prof) return prof.model || prof.name
  }
  return agentDisplayModelName.value || 'Agent'
}

/** 解析历史消息中的协议档显示名称，优先使用快照字段。 */
function resolveMessageProfileName(m: { profile_name?: string | null; profile_id?: string | null }): string {
  if (m.profile_name) return m.profile_name
  if (m.profile_id) {
    const prof = allProfiles.value.find((p) => p.id === m.profile_id)
    if (prof) return prof.name
  }
  return ''
}

/** 将 assistant_message 的服务端模型快照转换为前端回合元数据。 */
function messageMetaFromPayload(payload: Record<string, any>): Partial<StreamItem> {
  const profileId = typeof payload.profile_id === 'string' && payload.profile_id
    ? payload.profile_id
    : undefined
  const profile = profileId ? allProfiles.value.find((item) => item.id === profileId) : undefined
  const modelName = typeof payload.model_name === 'string' && payload.model_name
    ? payload.model_name
    : profile?.model || profile?.name || undefined
  const profileName = typeof payload.profile_name === 'string' && payload.profile_name
    ? payload.profile_name
    : profile?.name || undefined
  const meta: Partial<StreamItem> = {
    profileId,
    modelName,
    profileName,
    createdAt: typeof payload.created_at === 'string' ? payload.created_at : undefined,
  }
  // 旧事件可能没有模型快照，不能用默认 custom 覆盖回合初始展示信息。
  if (profile || modelName || typeof payload.provider === 'string') {
    meta.providerLogoKey = profile
      ? getProviderLogoKey(profile)
      : getProviderLogoKey({ name: payload.provider, model: modelName })
  }
  return meta
}

/** 把服务端确认的模型快照应用到助手回合，避免继续使用全局当前模型。 */
function applyAgentMessageMeta(agent: StreamItem, meta?: Partial<StreamItem>) {
  if (!meta) return
  if (meta.profileId) agent.profileId = meta.profileId
  if (meta.modelName) agent.modelName = meta.modelName
  if (meta.profileName) agent.profileName = meta.profileName
  if (meta.providerLogoKey) agent.providerLogoKey = meta.providerLogoKey
  if (meta.createdAt) agent.createdAt = meta.createdAt
}

/** 返回当前用户回合的助手容器；错误、报告等顶层事件会结束当前容器。 */
function getCurrentTurnAgent(list: StreamItem[]): StreamItem | undefined {
  let from = -1
  for (let i = list.length - 1; i >= 0; i--) {
    if (list[i].type === 'user') {
      from = i
      break
    }
  }
  // 从尾部回溯寻找本回合容器：error / report 等独立收尾条目会插在容器之后，
  // 若只认「最后一条必须是 agent」，同回合的后续帧会被误判为新回合。
  for (let i = list.length - 1; i > from; i--) {
    const item = list[i]
    if (item.type === 'user') break
    if (item.type === 'agent') return item
    // error / report 等独立条目：不属于任何容器，跳过继续回溯
  }
  return undefined
}

/** 获取或创建一个 Agent 回合容器；助手正文追加到其 blocks。 */
function getOrCreateTurnAgent(list: StreamItem[], meta?: Partial<StreamItem>): StreamItem {
  const current = getCurrentTurnAgent(list)
  if (current) {
    applyAgentMessageMeta(current, meta)
    return current
  }
  const defaultMeta = currentAgentMessageMeta()
  const newAgent = reactive({
    type: 'agent',
    blocks: [] as AgentBlock[],
    streaming: true,
    noAnim: meta?.noAnim,
    profileId: meta?.profileId || defaultMeta.profileId,
    providerLogoKey: meta?.providerLogoKey || defaultMeta.providerLogoKey,
    modelName: meta?.modelName || defaultMeta.modelName,
    profileName: meta?.profileName || defaultMeta.profileName,
    createdAt: meta?.createdAt || defaultMeta.createdAt,
  }) as StreamItem
  list.push(newAgent)
  return newAgent
}

/** 返回或创建当前回合的助手正文块。已落库的段落不再覆盖，保证中间叙述另起一段。 */
function getOrCreateAssistantBlock(agent: StreamItem): AgentAssistantItem {
  const blocks = agent.blocks || (agent.blocks = [])
  const last = blocks[blocks.length - 1]
  if (last?.type === 'assistant' && (last.streaming || !last.raw)) return last
  const block = reactive({ type: 'assistant', raw: '', text: '', streaming: true }) as AgentAssistantItem
  blocks.push(block)
  agent.streaming = true
  return block
}

/** 为每次用户发送生成浏览器侧幂等键，断线重发时避免重复触发 Harness。 */
function createClientMessageId(): string {
  if (typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function') {
    return crypto.randomUUID()
  }
  return `browser-${Date.now()}-${Math.random().toString(36).slice(2, 10)}`
}

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
function setCurrentGenerating(value: boolean) {
  isGenerating.value = value
  const sid = currentSessionId.value
  if (!sid) return
  const rt = ensureRuntime(sid)
  rt.events = events.value
  rt.isGenerating = value
  rt.harnessStage = harnessStage.value
  markGenerating(sid, value)
}

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
function toggleToolCard(item: StreamItem, callId: string) {
  item.openToolId = item.openToolId === callId ? undefined : callId
}

function toolStateText(tool: ToolRunItem): string {
  if (tool.status === 'running') return '执行中…'
  if (tool.status === 'error') return '执行失败'
  return '已完成'
}

function hasToolArguments(tool: ToolRunItem): boolean {
  return !!(tool.arguments && Object.keys(tool.arguments as object).length)
}

function formatToolArguments(args: unknown): string {
  try {
    const text = JSON.stringify(args, null, 1)
    return text.length > 600 ? `${text.slice(0, 600)}…` : text
  } catch {
    return String(args)
  }
}

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
const availableGoldQas = ref<GoldQA[]>([])
/** 跨会话下单偏好（/api/agent/prefs）：首单空槽预填，后端已给的值不覆盖。 */
const agentPrefs = ref<AgentPrefs | null>(null)
/** F12 prod 会签人名单：取自 api.admin.getSettings().prod_approvers，失败回退静态文案。 */
const prodApprovers = ref<string[]>([])
const prodApproversText = computed(() => (prodApprovers.value.length ? prodApprovers.value.join('、') : 'admin、bob'))
/** A1：确认成功前不盖章，等服务端 confirm_ack 到达后再清除乐观态。 */
const pendingAckItem = ref<StreamItem | null>(null)

function canConfirmItem(item: StreamItem): boolean {
  return !item.confirmAuthor?.id || item.confirmAuthor.id === authStore.user?.id
}

/** 工具审批卡可操作：实时连接且该卡尚未回执（owner 校验由服务端行锁把关）。 */
function canActApproval(item: StreamItem): boolean {
  return !item.approvalDone && !!(agentWs && agentWs.isConnected)
}

/** H5 HITL 审批回执：乐观盖章（服务端行锁兜底重复 ack；tool_approval_ack
 * 广播回执到达后终态一致）。审批放行以原 thread_id 恢复检查点回合。 */
function handleApprovalAck(item: StreamItem) {
  const approval = item.approval
  if (!approval || item.approvalDone) return
  const useLive = !!(agentWs && agentWs.isConnected)
  if (!useLive) {
    message.warning('连接已断开，审批卡将保留；重连后仍可审批')
    return
  }
  item.approvalDone = 'approved'
  agentWs!.sendApprovalAck('approve', approval.id)
  scrollToBottom()
}

function handleApprovalReject(item: StreamItem) {
  const approval = item.approval
  if (!approval || item.approvalDone) return
  if (!agentWs || !agentWs.isConnected) {
    message.warning('连接已断开，审批卡将保留；重连后仍可审批')
    return
  }
  item.approvalDone = 'rejected'
  agentWs.sendApprovalAck('reject', approval.id)
  scrollToBottom()
}

/** 澄清卡可作答：实时连接且尚未终态（submitted/failed 均禁操作；owner 校验由服务端行锁把关）。 */
function canActClarify(item: StreamItem): boolean {
  return !item.clarifyDone && !!(agentWs && agentWs.isConnected)
}

/** V1.72（dsh #1）澄清作答：乐观盖章（服务端行锁兜底重复 reply；clarify_ack
 * 广播回执到达后终态一致）。作答后回合按 answers[] 以原 thread_id 续跑。 */
function handleClarifySubmit(item: StreamItem, answers: ClarifyAnswer[]) {
  const clarify = item.clarify
  if (!clarify?.id || item.clarifyDone) return
  if (!agentWs || !agentWs.isConnected) {
    message.warning('连接已断开，澄清卡将保留；重连后仍可作答')
    return
  }
  item.clarifyDone = 'submitted'
  agentWs.sendClarifyReply(clarify.id, answers)
  scrollToBottom()
}

function confirmAuthorLabel(item: StreamItem): string {
  return item.confirmAuthor?.display_name || item.confirmAuthor?.username || '发起人'
}

/** F10：当前选中知识库是否为外部 Chat 库（无 rag_mode，改选恰好 1 个外部 RAG 服务档）。 */
function isExternalKb(card: any): boolean {
  return availableKbs.value.find(k => k.id === card?.kb_id)?.kind === 'external_chat'
}

/** F8 确认卡内联校验：错误留在卡内 .field-error 红字，不 Toast。 */
function validateConfirmCard(item: StreamItem): boolean {
  const errors: Record<string, string> = {}
  const card = item.card
  if (card?.kind === 'benchmark') {
    if (!card.profile_ids || card.profile_ids.length < 1) errors.profile_ids = '至少选择 1 个被测协议档'
    else if (card.profile_ids.length > 5) errors.profile_ids = '被测协议档不能超过 5 个'
  }
  if (card?.kind === 'rag') {
    if (isExternalKb(card)) {
      if (!card.profile_ids || card.profile_ids.length !== 1) errors.profile_ids = '外部 RAG 服务档需恰好选择 1 个'
    } else if (!card.rag_mode || card.rag_mode.length < 1) {
      errors.rag_mode = '请至少选择 1 种检索模式'
    }
  }
  if (card?.kind === 'testcase') {
    const sourceText = String(card.case_source?.text ?? '')
    if (!sourceText.trim()) errors.case_source = '请提供 file_id 或粘贴文本'
  }
  item.fieldErrors = errors
  return Object.keys(errors).length === 0
}

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
function normalizeConfirmCard(card: any) {
  if (!card) return card
  const prefs = agentPrefs.value
  if (prefs) {
    if (!card.kind && prefs.last_kind) card.kind = prefs.last_kind
    if ((!card.profile_ids || card.profile_ids.length === 0) && prefs.last_profile_ids?.length) {
      card.profile_ids = [...prefs.last_profile_ids]
    }
    if (!card.dataset_id && prefs.last_dataset_id) card.dataset_id = prefs.last_dataset_id
    if (!card.kb_id && prefs.last_kb_id) card.kb_id = prefs.last_kb_id
    if (!card.gold_qa_id && prefs.last_gold_qa_id) card.gold_qa_id = prefs.last_gold_qa_id
    if (card.with_stress == null && prefs.last_with_stress != null) {
      card.with_stress = prefs.last_with_stress
    }
  }
  card.run = { ...getDefaultRunConfig(), ...(card.run || {}) }
  card.stress = { ...getDefaultStressConfig(), ...(card.stress || {}) }
  if (card.kind === 'testcase') {
    card.case_source = { text: '', ...(card.case_source || {}) }
  }
  return sanitizeConfirmAssets(card)
}

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

function stampConfirmCard(item: StreamItem, confirmed: boolean) {
  item.isAcked = true
  item.ackResult = confirmed
  item.open = false
  if (item.card?.kind === 'benchmark') {
    item.summary = `${item.card.profile_ids?.length || 0} 个协议档 · 待入队`
  } else if (item.card?.kind === 'rag') {
    item.summary = 'RAG 评测 · 待入队'
  } else if (item.card?.kind === 'testcase') {
    item.summary = '用例生成 · 待入队'
  }
}

function handleConfirmAck(item: StreamItem, confirmed: boolean) {
  if (!canConfirmItem(item)) {
    message.error(`仅 ${confirmAuthorLabel(item)} 可以确认或取消该任务`)
    return
  }
  // F8 确认前卡内校验：不通过则留卡内显示红字，不盖章、不 Toast
  if (confirmed && !validateConfirmCard(item)) return
  const useLive = !!(agentWs && agentWs.isConnected)
  // 实时模式断线时不可将确认卡伪造成任务成功；保留卡片供重连后再次确认。
  if (!useLive && !api.isMock()) {
    message.error('Agent 连接未就绪，暂不能确认入队')
    return
  }
  if (useLive && agentWs!.sessionId && agentWs!.sessionId !== currentSessionId.value) {
    message.error('会话切换中，请稍后再确认')
    return
  }
  if (useLive) {
    if (confirmed) {
      // 确认成功前不盖章（A1）；confirm_author 是服务端事件元数据，提交前必须剥离。
      pendingAckItem.value = item
      const { confirm_author: _confirmAuthor, ...patch } = item.card || {}
      agentWs!.sendConfirmAck(true, patch)
      return
    }
    stampConfirmCard(item, false)
    agentWs!.sendConfirmAck(false, item.card)
    scrollToBottom()
    return
  }
  // 显式 mock 模式：仅本地盖章演示，不伪造任务进度。
  stampConfirmCard(item, confirmed)
  message.info(confirmed ? '演示模式：已确认（未真实入队）' : '已取消，未创建任务')
  scrollToBottom()
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
  for (const url of localAttachmentUrls) URL.revokeObjectURL(url)
  localAttachmentUrls.clear()
})
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
