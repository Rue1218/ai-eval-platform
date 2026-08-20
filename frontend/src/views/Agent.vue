<template>
  <div class="agent-layout" :class="{ 'with-rail': isRailOpen, 'no-list': isListCollapsed }">
    <!-- 左侧会话列表轨 (264px) -->
    <aside class="session-list" data-od-id="session-list">
      <div class="session-list-head">
        <button class="btn btn-secondary" style="width: 100%" @click="handleCreateSession">
          + 新建会话
        </button>
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
          v-for="s in sessions"
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
            <div class="session-meta-right">
              <!-- D5 会话状态点多态：running / succeeded / failed -->
              <i v-if="sessionDotClass(s)" class="nav-dot" :class="sessionDotClass(s)" :title="sessionDotTooltip(s)"></i>
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
          @click="isListCollapsed = !isListCollapsed"
        >
          <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round">
            <path d="M4 6h16M4 12h10M4 18h16" />
          </svg>
        </button>
        <span class="chat-head-title">{{ currentSession?.title || '新会话' }}</span>
        <span v-if="currentSession?.visibility === 'team'" class="chat-team-badge">团队共享</span>
        <span v-if="isGenerating" class="gen-pill">
          <i class="bdot"></i>
          <span>{{ harnessStageLabel }}</span>
          <span v-if="turnLatencyLabel" class="mono" style="opacity:.8">{{ turnLatencyLabel }}</span>
        </span>
        <span v-else-if="awaitingConfirm" class="gen-pill">
          <span>等待确认</span>
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

        <!-- 调度视图切换按钮 -->
        <button
          class="btn btn-sm"
          :class="isRailOpen ? 'btn-secondary' : 'btn-ghost'"
          title="展开/折叠任务调度分配侧轨"
          @click="isRailOpen = !isRailOpen"
        >
          调度视图
        </button>
      </div>

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
            <div class="welcome-eyebrow">{{ isRagMode ? 'AI Eval · RAG 评估智能体' : 'AI Eval · 大模型测试智能体' }}</div>
            <!-- 固定文案两行排版（对齐原型 <br> 换行），非用户输入，无注入风险 -->
            <h2 class="welcome-title" v-html="isRagMode ? '知识库检索质量评估，<br>全链路调优与召回分析。' : '说一句目标，<br>拿回一份评测报告。'"></h2>
            <p class="welcome-sub">
              {{ isRagMode ? '说明要评测的知识库或外部 RAG 接口，我会澄清后给您确认卡。支持 LightRAG 4 模式对比与召回命中归因。' : '说明要评测的模型或 PRD 生成需求，我会澄清后给您确认卡。未确认不入队，确认前字段都能修改。' }}
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
              <div class="bubble-user">{{ item.text }}</div>
              <template v-if="item.files && item.files.length">
                <span v-for="f in item.files" :key="f.name" class="attach-chip">
                  <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8">
                    <path d="M6 3h9l4 4v14H6Z" />
                    <path d="M14 3v5h5" />
                  </svg>
                  <span>{{ f.name }}</span>
                  <span class="mono">{{ f.size }}</span>
                </span>
              </template>
            </div>

            <!-- 2.1.1 打字占位气泡：LLM 意图识别期间的即时反馈（收到事件后由 dismissTyping 移除） -->
            <div v-else-if="item.type === 'typing'" class="msg-agent typing-bubble">
              <span class="tdot"></span><span class="tdot"></span><span class="tdot"></span>
            </div>

            <!-- 2.2 思考卡：深度思考链流式展示，完成后自动折叠，可展开/收起 -->
            <ThoughtCard
              v-else-if="item.type === 'thought'"
              :text="item.text || ''"
              :done="item.done"
              :latency-ms="item.latency_ms"
              :skill-id="item.skill_id"
              :stage="item.stage"
            />

            <!-- 2.3 短 MCP 工具调用卡 -->
            <div
              v-else-if="item.type === 'tool'"
              class="tool-card"
              :class="{ open: item.open, 'no-anim': item.noAnim }"
              :data-tool="item.tool"
            >
              <div class="tool-head" @click="item.open = !item.open">
                <span class="tool-status" :class="item.status">
                  <svg v-if="item.status === 'pending'" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round">
                    <path d="M12 3a9 9 0 1 0 9 9" />
                  </svg>
                  <svg v-else-if="item.status === 'ok'" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round">
                    <circle cx="12" cy="12" r="9" />
                    <path d="m8.5 12.2 2.4 2.4 4.6-5" />
                  </svg>
                  <svg v-else width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round">
                    <circle cx="12" cy="12" r="9" />
                    <path d="M9 9l6 6M15 9l-6 6" />
                  </svg>
                </span>
                <div class="tool-title-wrap">
                  <span class="tool-name">{{ getToolDisplayName(item.tool) }}</span>
                  <span class="tool-sub-tag">MCP · 短工具</span>
                </div>
                <div class="tool-meta-right">
                  <span v-if="formatLatency(item.latency_ms)" class="tool-latency mono">{{ formatLatency(item.latency_ms) }}</span>
                  <span class="tool-state-text" :class="{ fail: item.status === 'fail' }">
                    {{ item.status === 'pending' ? '调用中' : item.status === 'ok' ? '完成' : '失败' }}
                  </span>
                </div>
                <svg class="chev" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round">
                  <path d="m6 9 6 6 6-6" />
                </svg>
              </div>
              <div v-show="item.open" class="tool-detail">
                <div class="td-label">输入</div>
                <pre class="code">{{ JSON.stringify(item.args || {}, null, 2) }}</pre>
                <div class="td-label">输出</div>
                <pre class="code">{{ item.status === 'pending' ? '…' : (typeof item.result === 'string' ? item.result : JSON.stringify(item.result || {}, null, 2)) }}</pre>
              </div>
            </div>

            <!-- 2.4 任务确认卡 (Benchmark / RAG / TestCase) -->
            <div
              v-else-if="item.type === 'confirm' && item.card"
              class="confirm-card"
              :class="{ acked: item.isAcked, open: item.open, 'no-anim': item.noAnim }"
              :data-od-id="`confirm-card-${item.card.kind}`"
            >
              <div class="confirm-head" @click="item.isAcked && (item.open = !item.open)">
                <KindTag :kind="item.card.kind" />
                <span class="confirm-title">{{ getConfirmTitle(item.card.kind) }}</span>
                <span class="confirm-summary">{{ item.summary }}</span>
                <svg class="chev" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round">
                  <path d="m6 9 6 6 6-6" />
                </svg>
              </div>

              <!-- 卡片主体内容 -->
              <div class="confirm-body">
                <!-- Benchmark 模式字段 -->
                <template v-if="item.card.kind === 'benchmark'">
                  <div class="field">
                    <span class="field-label">kind</span>
                    <div>
                      <KindTag kind="benchmark" />
                      <span class="small tertiary">　一任务一种 kind</span>
                    </div>
                  </div>

                  <div class="field">
                    <span class="field-label">profile_ids（被测协议档，1–5 个）<i class="req">*</i></span>
                    <div class="chip-group">
                      <button
                        v-for="p in availableProfiles"
                        :key="p.id"
                        class="chip"
                        :class="{ on: item.card.profile_ids?.includes(p.id) }"
                        @click="toggleProfile(item, p.id)"
                      >
                        {{ p.name }} <span class="mono" style="opacity: 0.7">{{ p.model }}</span>
                      </button>
                    </div>
                    <!-- F8 卡内内联校验错误（不 Toast） -->
                    <div v-if="item.fieldErrors?.profile_ids" class="field-error">{{ item.fieldErrors.profile_ids }}</div>
                  </div>

                  <div class="field">
                    <span class="field-label">dataset_id <i class="req">*</i></span>
                    <select v-model="item.card.dataset_id" class="select">
                      <option v-for="d in availableDatasets" :key="d.id" :value="d.id">
                        {{ d.name }} v{{ d.version }} · {{ d.row_count }} 行
                      </option>
                    </select>
                  </div>
                </template>

                <!-- RAG 模式字段 -->
                <template v-else-if="item.card.kind === 'rag'">
                  <div class="field">
                    <span class="field-label">kind</span>
                    <div><KindTag kind="rag" /></div>
                  </div>

                  <div class="form-row">
                    <div class="field">
                      <span class="field-label">kb_id <i class="req">*</i></span>
                      <select v-model="item.card.kb_id" class="select" @change="onKbChange(item)">
                        <option v-for="k in availableKbs" :key="k.id" :value="k.id">
                          {{ k.name }}（{{ k.kind === 'lightrag' ? 'LightRAG' : '外部 Chat' }}）
                        </option>
                      </select>
                    </div>
                    <div class="field">
                      <span class="field-label">gold_qa_id <i class="req">*</i></span>
                      <select v-model="item.card.gold_qa_id" class="select">
                        <option v-for="g in availableGoldQas" :key="g.id" :value="g.id">
                          {{ g.name }} v{{ g.version }} · {{ g.row_count }} 条
                        </option>
                      </select>
                    </div>
                  </div>

                  <!-- F10 外部库条件联动：external_chat 库无 rag_mode，改选恰好 1 个外部 RAG 服务档 -->
                  <div v-if="isExternalKb(item.card)" class="field">
                    <span class="field-label">profile_ids（外部 RAG 服务档，恰好 1 个）<i class="req">*</i></span>
                    <select
                      class="select"
                      :value="item.card.profile_ids?.[0] || ''"
                      @change="onExternalProfileChange(item, ($event.target as HTMLSelectElement).value)"
                    >
                      <option value="" disabled>请选择外部 RAG 服务档</option>
                      <option v-for="p in availableProfiles" :key="p.id" :value="p.id">
                        {{ p.name }} · {{ p.model }}
                      </option>
                    </select>
                    <div v-if="item.fieldErrors?.profile_ids" class="field-error">{{ item.fieldErrors.profile_ids }}</div>
                  </div>
                  <div v-else class="field">
                    <span class="field-label">rag_mode（1–4 个，默认 hybrid）</span>
                    <div class="chip-group">
                      <button
                        v-for="m in ['naive', 'local', 'global', 'hybrid']"
                        :key="m"
                        class="chip"
                        :class="{ on: item.card.rag_mode?.includes(m as any) }"
                        @click="toggleRagMode(item, m)"
                      >
                        {{ m }}
                      </button>
                    </div>
                    <div v-if="item.fieldErrors?.rag_mode" class="field-error">{{ item.fieldErrors.rag_mode }}</div>
                  </div>
                </template>

                <!-- TestCase 模式字段 -->
                <template v-else-if="item.card.kind === 'testcase'">
                  <div class="field">
                    <span class="field-label">kind</span>
                    <div><KindTag kind="testcase" /></div>
                  </div>
                  <div class="field">
                    <span class="field-label">case_source <i class="req">*</i></span>
                    <textarea
                      v-model="item.card.case_source.text"
                      class="textarea"
                      placeholder="粘贴 PRD / 接口描述文本（或用附件上传 OpenAPI / Excel）"
                      @input="clearFieldError(item, 'case_source')"
                    ></textarea>
                    <!-- F8 卡内内联校验错误（不 Toast） -->
                    <div v-if="item.fieldErrors?.case_source" class="field-error">{{ item.fieldErrors.case_source }}</div>
                  </div>
                  <div class="field-hint">
                    规模参考上限：PRD 简单 / 中 / 复杂 → 20 / 45 / 80 条；超上限将停止并提示拆分。生成后需在 72h 内确认入库。
                  </div>
                </template>

                <!-- F11 高级运行参数折叠项：8 项统一挂 card.run（RunConfig 契约） -->
                <div v-if="['benchmark', 'rag'].includes(item.card.kind)" class="fold-card" :class="{ open: item.showRunConfig }">
                  <div class="fold-head" @click="item.showRunConfig = !item.showRunConfig">
                    <span class="fold-title">高级运行参数</span>
                    <span class="small tertiary mono">sample 20 · 并发 4 · 超时 60s · 重试 1 · T=0.2 · 2048 tokens</span>
                    <svg class="chev" width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2">
                      <path d="m6 9 6 6 6-6" />
                    </svg>
                  </div>
                  <div v-show="item.showRunConfig" class="fold-body">
                    <div class="form-row">
                      <div class="field">
                        <span class="field-label">sample_size（抽样行数）</span>
                        <n-input-number v-model:value="item.card.run.sample_size" :min="1" :max="1000" placeholder="默认 20" size="small" />
                      </div>
                      <div class="field">
                        <span class="field-label">concurrency（并发数）</span>
                        <n-input-number v-model:value="item.card.run.concurrency" :min="1" :max="64" placeholder="默认 4" size="small" />
                      </div>
                    </div>
                    <div class="form-row">
                      <div class="field">
                        <span class="field-label">timeout_s（单次超时秒）</span>
                        <n-input-number v-model:value="item.card.run.timeout_s" :min="1" placeholder="默认 60s" size="small" />
                      </div>
                      <div class="field">
                        <span class="field-label">retry（失败重试次数）</span>
                        <n-input-number v-model:value="item.card.run.retry" :min="0" :max="5" placeholder="默认 1" size="small" />
                      </div>
                    </div>
                    <div class="form-row">
                      <div class="field">
                        <span class="field-label">temperature（采样温度）</span>
                        <n-input-number v-model:value="item.card.run.temperature" :min="0" :max="2" :step="0.1" placeholder="默认 0.2" size="small" />
                      </div>
                      <div class="field">
                        <span class="field-label">max_tokens（最大生成 tokens）</span>
                        <n-input-number v-model:value="item.card.run.max_tokens" :min="1" placeholder="默认 2048" size="small" />
                      </div>
                    </div>
                    <div class="field">
                      <span class="field-label">max_usd（单任务预算上限）</span>
                      <n-input-number v-model:value="item.card.run.max_usd" :min="0" :step="0.5" placeholder="默认 5" size="small" />
                      <span class="field-hint">累计 usage 超限即停并返回 BUDGET_EXCEEDED（F-CM-06）</span>
                    </div>
                    <div class="field" style="margin-bottom: 0">
                      <span class="field-label">system_prompt（可选）</span>
                      <n-input v-model:value="item.card.run.system_prompt" placeholder="留空则不注入" size="small" />
                    </div>
                  </div>
                </div>

                <!-- 先评后压开关与参数折叠 -->
                <div v-if="['benchmark', 'rag'].includes(item.card.kind)" class="fold-card" :class="{ open: item.card.with_stress }">
                  <div class="fold-head" @click="item.card.with_stress = !item.card.with_stress">
                    <label class="row" style="gap: 8px; cursor: pointer" @click.stop>
                      <input v-model="item.card.with_stress" type="checkbox" />
                      <span class="fold-title">先评后压（质量成功后自动派生共享压测）</span>
                    </label>
                    <svg class="chev" width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2">
                      <path d="m6 9 6 6 6-6" />
                    </svg>
                  </div>
                  <!-- F12 压测参数：统一挂 card.stress（StressConfig 契约）；env 枚举含 dev（API.md §1.4） -->
                  <div v-show="item.card.with_stress" class="fold-body">
                    <div class="form-row">
                      <div class="field">
                        <span class="field-label">压测环境 (env) <i class="req">*</i></span>
                        <select v-model="item.card.stress.env" class="select">
                          <option value="dev">dev · 开发环境</option>
                          <option value="test">test · 测试环境（免会签）</option>
                          <option value="staging">staging · 预发环境</option>
                          <option value="prod">prod · 生产环境（需双人会签）</option>
                        </select>
                      </div>
                      <div class="field">
                        <span class="field-label">目标 QPS (qps) <i class="req">*</i></span>
                        <n-input-number v-model:value="item.card.stress.qps" :min="1" :max="1000" placeholder="例如 50" size="small" />
                      </div>
                    </div>
                    <div class="form-row">
                      <div class="field">
                        <span class="field-label">压测时长 duration_s（秒）<i class="req">*</i></span>
                        <n-input-number v-model:value="item.card.stress.duration_s" :min="10" :max="3600" placeholder="默认 60s" size="small" />
                      </div>
                      <div class="field">
                        <span class="field-label">sla_p99_ms（可选）</span>
                        <n-input-number v-model:value="item.card.stress.sla_p99_ms" :min="1" placeholder="如 1500" size="small" />
                        <span class="field-hint">不填不出「是否达标」</span>
                      </div>
                    </div>
                    <div v-if="item.card.stress.env === 'prod'" class="badge badge-warning" style="margin-top: 6px">
                      ⚠ prod 生产压测：评测成功后子任务将处于待会签状态，会签完成后才开始发压。会签人：{{ prodApproversText }}
                    </div>
                  </div>
                </div>
              </div>

              <!-- 卡片底部按钮与盖章状态 -->
              <div class="confirm-foot">
                <template v-if="!item.isAcked">
                  <!-- F9 会话占槽：有进行中任务（含压测子任务）时主按钮禁用，note 转 warning 色 -->
                  <span class="confirm-note" :class="{ warn: !!activeTask }">
                    {{
                      !canConfirmItem(item)
                        ? `等待 ${confirmAuthorLabel(item)} 确认`
                        : activeTask
                          ? '当前会话已有任务进行中（槽位含压测子任务），完成后才能再开新长任务'
                          : '未确认不入队；确认前可修改字段'
                    }}
                  </span>
                  <span class="spacer"></span>
                  <template v-if="canConfirmItem(item)">
                    <button class="btn btn-secondary" @click="handleConfirmAck(item, false)">取消</button>
                    <button class="btn btn-sign" :disabled="!!activeTask" @click="handleConfirmAck(item, true)">确认并开始</button>
                  </template>
                </template>
                <template v-else>
                  <span class="ack-stamp" :class="item.ackResult ? 'ok' : 'no'">
                    {{ item.ackResult ? '已确认 · 任务入队 queued' : '已取消 · confirm_ack { ok: false }' }}
                  </span>
                </template>
              </div>
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

            <!-- 2.7 Agent 文本回复（非 streaming 时使用 MarkdownView 渲染富文本） -->
            <div
              v-else-if="item.type === 'agent'"
              class="msg-agent"
              :class="{ 'no-anim': item.noAnim, 'streaming-bubble': item.streaming }"
            >
              <MarkdownView v-if="!item.streaming" :content="item.raw || item.text || ''" />
              <div v-else v-html="item.text"></div>
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
        <div v-else class="progress-dock-inner" :class="{ stress: activeTask.kind === 'stress' }">
          <template v-if="activeTask.kind === 'stress'">
            <div class="dock-row">
              <KindTag kind="stress" />
              <svg class="spark" viewBox="0 0 180 36" preserveAspectRatio="none">
                <polygon class="a-qps" :points="sparkPolygonPoints" />
                <polyline class="l-qps" :points="sparkLinePoints" />
                <polyline class="l-rt" :points="sparkRtPoints" />
                <polyline class="l-err" :points="sparkErrPoints" />
                <circle class="dot-end" :cx="sparkLastPoint.x" :cy="sparkLastPoint.y" r="2.4" />
              </svg>
              <span class="mini-series">
                <span class="ms ms-qps">QPS <b>{{ currentStressMetrics.qps }}</b></span>
                <span class="ms ms-rt">RT <b>{{ currentStressMetrics.rt }}ms</b></span>
                <span class="ms ms-err">错误率 <b>{{ currentStressMetrics.err }}%</b></span>
              </span>
              <span class="progress-msg">{{ activeTask.progress?.message || '压测执行中' }}</span>
              <button
                v-if="canCancelActiveTask"
                class="btn btn-ghost btn-sm"
                :disabled="cancellingTaskId === activeTask.id"
                @click="handleCancelActiveTask(activeTask.id)"
              >
                {{ cancellingTaskId === activeTask.id ? '停止中…' : '立即停止' }}
              </button>
            </div>
            <div class="progress-bar">
              <i :style="{ width: `${activeTask.progress?.percent || 50}%` }"></i>
            </div>
          </template>

          <template v-else>
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
          </template>
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

        <!-- 附件暂存架（与输入区同宽居中对齐） -->
        <div v-if="stagedFiles.length" class="attach-stage" style="display: flex; gap: 8px; flex-wrap: wrap; max-width: 760px; margin: 0 auto 8px">
          <span v-for="(f, i) in stagedFiles" :key="f.name" class="attach-chip">
            <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8">
              <path d="M6 3h9l4 4v14H6Z" />
              <path d="M14 3v5h5" />
            </svg>
            <span>{{ f.name }}</span>
            <span class="mono">{{ f.size }}</span>
            <button class="link-btn" style="padding: 0 2px" @click="stagedFiles.splice(i, 1)">✕</button>
          </span>
        </div>

        <div class="composer-card" :class="{ generating: isGenerating }" style="position: relative;">
          <!-- 斜杠命令悬浮面板 (宽 380px，键入 / 触发) -->
          <SlashPalette
            ref="slashPaletteRef"
            :show="showSlashPalette"
            :filter-query="inputText"
            @select="handleSlashSelect"
            @close="handleSlashClose"
          />

          <!-- 上半区：行内命令纯文本强调色前缀 + 正常黑色多行文本域 -->
          <div class="composer-input-row">
            <span v-if="selectedSlashCmd" class="composer-cmd-prefix mono">/{{ selectedSlashCmd }}&nbsp;</span>
            <textarea
              ref="textareaRef"
              v-model="inputText"
              class="composer-textarea"
              rows="1"
              :placeholder="selectedSlashCmd ? '输入命令参数（可选），Enter 发送' : '输入任何评测问题或需求，或键入 / 选择命令，Shift + Enter 换行，Enter 发送'"
              @keydown="handleKeydown"
              @input="adjustTextareaHeight"
              @paste="() => nextTick(adjustTextareaHeight)"
            ></textarea>
          </div>

          <!-- 下半区：操作底栏（附件 + 只读模型标识 + 发送按钮） -->
          <div class="composer-bottom-bar">
            <div class="composer-left-actions">
              <!-- 添加附件按钮 -->
              <button class="composer-action-btn" title="添加附件（≤20MB，支持 PRD/OpenAPI/Excel/CSV/PDF 等）" @click="triggerFileInput">
                <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round">
                  <line x1="12" y1="5" x2="12" y2="19"></line>
                  <line x1="5" y1="12" x2="19" y2="12"></line>
                </svg>
              </button>
              <input
                ref="fileInputRef"
                type="file"
                hidden
                accept=".md,.txt,.html,.pdf,.json,.yaml,.yml,.xlsx,.xls,.csv,.jsonl"
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
                  <span class="head-model-dot"></span>
                  <span class="model-name mono">Agent · {{ agentModelName || '选择模型' }}</span>
                  <svg class="chevron-icon" width="10" height="10" viewBox="0 0 12 12" fill="none" stroke="currentColor" stroke-width="1.5">
                    <path d="M3 4.5l3 3 3-3" stroke-linecap="round" stroke-linejoin="round" />
                  </svg>
                </button>
              </n-dropdown>

              <!-- 上下文容量小圆环指示器（紧邻模型选择器右侧） -->
              <ContextMeter :meter="currentContextMeter" :compact-summary="currentCompactSummary" />
            </div>

            <!-- 右侧圆形发送/暂停按钮 -->
            <button
              class="composer-send-btn"
              :class="{ active: isGenerating || inputText.trim().length > 0 || stagedFiles.length > 0 }"
              :disabled="!isGenerating && inputText.trim().length === 0 && stagedFiles.length === 0"
              :title="isGenerating ? '暂停生成（不取消已入队任务）' : '发送 (Enter)'"
              @click="handleSendClick"
            >
              <svg v-if="isGenerating" width="12" height="12" viewBox="0 0 24 24" fill="currentColor">
                <rect x="6" y="6" width="12" height="12" rx="2" />
              </svg>
              <svg v-else width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round">
                <line x1="5" y1="12" x2="19" y2="12"></line>
                <polyline points="12 5 19 12 12 19"></polyline>
              </svg>
            </button>
          </div>
        </div>
      </div>
    </section>

    <!-- 右侧迷你调度视图侧轨 (308px) -->
    <aside class="dispatch-rail" data-od-id="dispatch-rail">
      <div class="rail-head">
        <div class="row-between">
          <span style="font-size: 13px; font-weight: 600">调度视图</span>
          <router-link to="/tasks" class="link-btn" data-od-id="rail-open-dispatch">打开任务中心 →</router-link>
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
          <div class="rail-label">分配节点</div>
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
import { ref, computed, reactive, onMounted, onBeforeUnmount, nextTick, watch, h } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useMessage, useDialog, NDropdown, type DropdownOption } from 'naive-ui'
import { api } from '../api/http'
import { AgentWebSocket } from '../api/ws'
import type {
  AgentSession,
  GoldQA,
  KnowledgeBase,
  Profile,
  Dataset,
  SessionAuthor,
  Task,
  TaskSpec,
  WsServerEvent,
} from '../api/types'
import { getDefaultRunConfig, getDefaultStressConfig } from '../schemas/confirmCard'
import { useModeStore } from '../stores/mode'
import { useAuthStore } from '../stores/auth'
import KindTag from '../components/common/KindTag.vue'
import { formatLatency } from '../utils/format'
import { skillLabel } from '../agent/skillLabels'
import SkillBadge from '../components/agent/SkillBadge.vue'
import ThoughtCard from '../components/agent/ThoughtCard.vue'
import MarkdownView from '../components/agent/MarkdownView.vue'
import SlashPalette from '../components/agent/SlashPalette.vue'
import { SYSTEM_SLASH_COMMANDS } from '../agent/slashRegistry'
import ContextMeter, { type ContextMeterData } from '../components/agent/ContextMeter.vue'

const message = useMessage()
const dialog = useDialog()
const route = useRoute()
const router = useRouter()
const modeStore = useModeStore()
const authStore = useAuthStore()
const chatScrollRef = ref<HTMLDivElement | null>(null)
const textareaRef = ref<HTMLTextAreaElement | null>(null)
const fileInputRef = ref<HTMLInputElement | null>(null)

const isListCollapsed = ref(false)
const isRailOpen = ref(false)
const isWsOnline = ref(true)
const isGenerating = ref(false)
const harnessStage = ref<'plan' | 'react' | 'reflect' | ''>('')
const lastToolTitle = ref('')
const turnLatencyMs = ref(0)
const awaitingConfirm = computed(() =>
  events.value.some((item) => item.type === 'confirm' && !item.isAcked) && !isGenerating.value
)
const harnessStageLabel = computed(() => {
  if (harnessStage.value === 'plan') return '规划中'
  if (harnessStage.value === 'reflect') return '复核中'
  if (harnessStage.value === 'react' && lastToolTitle.value) return `调用「${lastToolTitle.value}」`
  if (harnessStage.value === 'react') return '调用工具中'
  return '生成中'
})
const turnLatencyLabel = computed(() => formatLatency(turnLatencyMs.value) || '')
const showJumpBottom = ref(false)
const agentModelName = ref('')
const currentAgentProfileId = ref<string>('')
const allProfiles = ref<Profile[]>([])

// 上下文度量与斜杠命令面板状态
const currentContextMeter = ref<ContextMeterData | null>(null)
const currentCompactSummary = ref<string | null>(null)
const slashPaletteRef = ref<InstanceType<typeof SlashPalette> | null>(null)
const paletteClosedManually = ref(false)
const selectedSlashCmd = ref<string>('')

const showSlashPalette = computed(() => {
  const text = inputText.value
  return !selectedSlashCmd.value && text.startsWith('/') && !text.includes(' ') && !paletteClosedManually.value
})

function handleSlashSelect(cmdText: string) {
  const cleanName = cmdText.trim().replace(/^\//, '')
  selectedSlashCmd.value = cleanName
  inputText.value = ''
  paletteClosedManually.value = true
  nextTick(() => {
    textareaRef.value?.focus()
    adjustTextareaHeight()
  })
}

function removeSelectedSlashCmd() {
  selectedSlashCmd.value = ''
  nextTick(() => {
    textareaRef.value?.focus()
    adjustTextareaHeight()
  })
}

function handleSlashClose() {
  paletteClosedManually.value = true
}

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
    }
  })
  return [
    ...list,
    { type: 'divider', key: 'd1' },
    { label: '⚙ 管理模型接入协议档 ↗', key: '__goto_profiles__' },
  ]
})

const sessions = ref<AgentSession[]>([])
const selectedSessionIds = ref<string[]>([])
const deletingSessionIds = new Set<string>()
const currentSessionId = ref<string>('')
const currentSession = computed(() => sessions.value.find(s => s.id === currentSessionId.value) || sessions.value[0] || null)
const deletableSessionCount = computed(() => sessions.value.filter((session) => session.can_delete).length)
const allDeletableSessionsSelected = computed(() => {
  const deletableIds = sessions.value.filter((session) => session.can_delete).map((session) => session.id)
  return deletableIds.length > 0 && deletableIds.every((id) => selectedSessionIds.value.includes(id))
})
const inputText = ref('')
const stagedFiles = ref<any[]>([])
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

const isSlashCommandMode = computed(() => {
  return (inputText.value || '').trimStart().startsWith('/')
})

// 模拟资产只允许在显式 mock 模式中存在；实时模式必须等待服务端短工具回填。
const availableProfiles = ref<Profile[]>(api.isMock() ? [
  { id: 'p-gpt', name: 'gpt-test', model: 'gpt-4o', protocol: 'openai_chat', base_url: 'https://api.openai.com/v1', usages: ['target'], created_at: new Date().toISOString() },
  { id: 'p-claude', name: 'claude-x', model: 'claude-3-5-sonnet-20241022', protocol: 'anthropic_messages', base_url: 'https://api.anthropic.com', usages: ['target'], created_at: new Date().toISOString() },
  // F10 外部 RAG 服务档（external_chat 库确认卡单选选项）
  { id: 'p-ragsvc', name: 'rag-客服外挂', model: 'rag-chat-v2', protocol: 'openai_chat', base_url: 'https://rag.internal.example.com/v1', usages: ['target'], created_at: new Date().toISOString() },
 ] : [])
const availableDatasets = ref<Dataset[]>(api.isMock() ? [
  { id: 'ds-smoke', name: 'smoke-20', version: 3, row_count: 20, pending_complete_count: 0, metric: 'contain', owner: 'admin', created_at: new Date().toISOString() },
 ] : [])
const availableKbs = ref<KnowledgeBase[]>(api.isMock() ? [
  { id: 'kb-default', name: 'default', kind: 'lightrag', doc_count: 12, is_core: true, owner: 'admin' },
  { id: 'kb-cs', name: '外挂客服', kind: 'external_chat', doc_count: null, is_core: false, owner: 'alice' },
 ] : [])
const availableGoldQas = ref<GoldQA[]>(api.isMock() ? [
  { id: 'gq-1', kb_id: 'kb-default', name: 'qa-v1', version: 2, row_count: 20, owner: 'admin', created_at: new Date().toISOString() },
 ] : [])

// 智能体能力卡与顶栏共用同一模式状态，避免出现页面内外不一致的评测上下文。
const isRagMode = computed(() => modeStore.mode === 'rag')

const LLM_CAPS = [
  { id: 'cap-benchmark', name: '多模型基准对比', desc: '1–5 个协议档并排测试，输出 contain / exact / Judge 打分', say: '帮我对两个已配置模型进行基准评测', icoSvg: '<path d="M4 20V10M10 20V4M16 20v-8M3 20h18"/>' },
  { id: 'cap-prompt', name: 'Prompt 效果评测', desc: '评测不同系统提示词与上下文在同一数据集上的得分差异', say: '评测系统 Prompt 在支付链路问答上的准确率', icoSvg: '<rect x="4" y="4" width="16" height="16" rx="3"/><path d="M8 9h8M8 13h5"/>' },
  { id: 'cap-testcase', name: 'PRD 生成用例', desc: '附 PRD / OpenAPI，按 6 种策略生成，72h 内确认入库', say: '帮我把这份支付 PRD 生成测试用例', icoSvg: '<path d="M9 11.5 11 14l4.5-5"/><rect x="4" y="4" width="16" height="16" rx="3"/>' },
  { id: 'cap-stress', name: '先评后压', desc: '质量达标后自动压测同一 endpoint，实时监控 QPS / RT', say: '帮我评测已配置模型，并在成功后自动执行压测', icoSvg: '<path d="M3 17l5-6 4 3 6-8"/><path d="M18 6h3v3"/>' }
]

const RAG_CAPS = [
  { id: 'cap-rag', name: 'RAG 检索评测', desc: '知识库 + 黄金 QA，输出 Hit Rate@5 / MRR / Recall', say: '帮我评估已配置知识库的检索质量', icoSvg: '<path d="M5 5.5A2.5 2.5 0 0 1 7.5 3H19v15H7.5A2.5 2.5 0 0 0 5 20.5Z"/><path d="M5 18.5V5.5"/><path d="M9 7.5h6"/>' },
  { id: 'cap-modes', name: '4 模式横向对比', desc: '对比 LightRAG naive / local / global / hybrid 检索表现', say: '横向对比已配置知识库的四种检索模式', icoSvg: '<circle cx="12" cy="12" r="3"/><path d="M3 12h3M18 12h3M12 3v3M12 18v3"/>' },
  { id: 'cap-qa', name: '黄金 QA 检验', desc: '校验 expected_doc_ids 召回命中与相似度分布', say: '检验已配置知识库的黄金 QA 覆盖度', icoSvg: '<path d="M9 11.5 11 14l4.5-5"/><circle cx="12" cy="12" r="9"/>' },
  { id: 'cap-rag-stress', name: 'RAG 接口加压', desc: '对 LightRAG query 或外部 RAG HTTP 服务发起高并发压测', say: '对已配置知识库的查询接口执行压测', icoSvg: '<path d="M3 17l5-6 4 3 6-8"/><path d="M18 6h3v3"/>' }
]

const currentCaps = computed(() => isRagMode.value ? RAG_CAPS : LLM_CAPS)

// 快捷芯片：短标签 + 完整 prompt（对齐原型 data-say），顺序随顶栏模式重排
const QUICK_CHIPS = [
  { label: '生成用例', say: '帮我把这份 PRD 生成测试用例' },
  { label: '基准评测', say: '对比一下 gpt-test 和 claude-x 在 smoke-20 上的表现' },
  { label: 'RAG 评测', say: '评估 default 知识库的检索质量' },
  { label: '先评后压', say: '跑完基准评测后自动加压测' },
]

const currentQuickChips = computed(() => {
  // RAG 模式 RAG 优先（对齐原型 orderChipsByMode）
  if (isRagMode.value) return [QUICK_CHIPS[2], QUICK_CHIPS[0], QUICK_CHIPS[1], QUICK_CHIPS[3]]
  return QUICK_CHIPS
})

const defaultKpis = [
  { value: '2%', label: '失败率' },
  { value: '820ms', label: '平均延迟' },
  { value: '0.86', label: '主指标 contain' },
]

const railWorkers = ref([
  { id: 'agent-01', load: 62 },
  { id: 'agent-06', load: 18 },
  { id: 'agent-10', load: 9 },
])

const dispatchLogs = ref([
  { time: '12:01:02', kind: 'ENQUEUE', msg: 'a1f3c2 smoke-20 v3 · 5 shards' },
  { time: '12:01:08', kind: 'ASSIGN', msg: 'shard 2/5 → agent-01 · 84ms' },
])

const currentStressMetrics = ref({ qps: 118, rt: 890, err: 0.4 })
// 压测迷你曲线数据：[QPS, RT, 错误率] 三元组（对齐原型 STRESS_SERIES）
const sparkPointsData = [[12, 210, 0.0], [38, 260, 0.0], [64, 340, 0.1], [92, 520, 0.2], [118, 890, 0.4], [118, 1200, 0.4]]

/** 按列独立归一化生成折线点串（原型 drawSpark：QPS 面积+线 / RT / 错误率三线） */
function sparkLineFor(colIdx: number): string {
  const W = 180, H = 36, P = 3
  const maxV = Math.max(...sparkPointsData.map(p => p[colIdx])) || 1
  return sparkPointsData.map((p, i) => {
    const x = P + i * (W - 2 * P) / (sparkPointsData.length - 1)
    const y = H - P - (p[colIdx] / maxV) * (H - 2 * P)
    return `${x.toFixed(1)},${y.toFixed(1)}`
  }).join(' ')
}

const sparkLinePoints = computed(() => sparkLineFor(0))
const sparkRtPoints = computed(() => sparkLineFor(1))
const sparkErrPoints = computed(() => sparkLineFor(2))

const sparkPolygonPoints = computed(() => {
  const W = 180, H = 36, P = 3
  const firstX = P, lastX = W - P
  return `${firstX},${H - P} ${sparkLinePoints.value} ${lastX},${H - P}`
})

const sparkLastPoint = computed(() => {
  const W = 180, H = 36, P = 3
  const maxQ = Math.max(...sparkPointsData.map(p => p[0])) || 1
  const last = sparkPointsData[sparkPointsData.length - 1]
  return {
    x: W - P,
    y: H - P - (last[0] / maxQ) * (H - 2 * P),
  }
})

interface StreamItem {
  type: 'user' | 'agent' | 'thought' | 'tool' | 'confirm' | 'report' | 'error' | 'typing'
  text?: string
  done?: boolean
  collapsed?: boolean
  latency_ms?: number
  stage?: 'plan' | 'react' | 'reflect'
  skill_id?: string
  // 推理思考链标记：由 stream=think 瞬态增量帧创建，终帧只结束折叠、不得覆盖其内容
  streamThink?: boolean
  // 流式标记：true 表示该 agent 气泡正在接收 LLM 增量帧，终帧到达后置 false
  streaming?: boolean
  // 已显示的纯文本进度（流式增量与打字机共用，text 为其渲染后的 HTML）
  raw?: string
  tool?: string
  args?: any
  result?: any
  status?: 'pending' | 'ok' | 'fail'
  open?: boolean
  card?: any
  isAcked?: boolean
  ackResult?: boolean
  summary?: string
  showRunConfig?: boolean
  reportId?: string
  kpis?: any[]
  bars?: any[]
  code?: string
  message?: string
  files?: any[]
  // 用户消息的服务端 ID / 浏览器幂等键与作者，用于团队协作实时回显去重。
  messageId?: string
  clientMessageId?: string
  author?: SessionAuthor | null
  // 确认卡作者不属于 TaskSpec；只能用于前端权限展示，提交 patch 前必须剥离。
  confirmAuthor?: SessionAuthor | null
  // F4 历史回放标记：跳过入场动画（对齐原型 no-anim）
  noAnim?: boolean
  // S3 思考卡流式打字：fullText 为应显示全文，复用上方 streaming 标记表示打字机进行中
  fullText?: string
  // F8 确认卡内联校验错误（字段名 → 红字文案）
  fieldErrors?: Record<string, string>
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

/** 判断当前成员是否是待确认卡的唯一作者；兼容迁移前无作者字段的历史卡。 */
function canConfirmItem(item: StreamItem): boolean {
  return !item.confirmAuthor?.id || item.confirmAuthor.id === authStore.user?.id
}

/** 返回待确认卡作者的展示名称，供协作者只读提示使用。 */
function confirmAuthorLabel(item: StreamItem): string {
  return item.confirmAuthor?.display_name || item.confirmAuthor?.username || '发起人'
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
let lastConfirmKind = 'benchmark'

/** 按会话缓存对话流与生成态：切换会话不丢历史，生成中的 WS 不拆。 */
interface SessionRuntime {
  events: StreamItem[]
  isGenerating: boolean
  harnessStage: 'plan' | 'react' | 'reflect' | ''
  lastToolTitle: string
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
    lastToolTitle: '',
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
  rt.lastToolTitle = lastToolTitle.value
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
    ? sessions.value.filter((session) => session.can_delete).map((session) => session.id)
    : []
}

/* ─── 页面级定时器登记：所有演示/兜底定时器统一登记，组件卸载时集中清理，避免回调写入已销毁状态 ─── */
const pendingTimers = new Set<number>()
/* F19 生成流定时器子集：mock 场景步骤 / 思考打字机 / mock 进度推进专用，
   「暂停生成」只清理该子集（保留 WS 连接与 F15 侧轨心跳等页面级定时器）。 */
const flowTimers = new Set<number>()
let interpretStopWatch: (() => void) | null = null

function trackTimeout(fn: () => void, ms: number, flow = false): number {
  const id = window.setTimeout(() => {
    pendingTimers.delete(id)
    flowTimers.delete(id)
    fn()
  }, ms)
  pendingTimers.add(id)
  if (flow) flowTimers.add(id)
  return id
}

function trackInterval(fn: () => void, ms: number, flow = false): number {
  const id = window.setInterval(fn, ms)
  pendingTimers.add(id)
  if (flow) flowTimers.add(id)
  return id
}

/** 主动清除已登记定时器（任务提前完成时使用）。 */
function clearTracked(id: number) {
  window.clearTimeout(id)
  window.clearInterval(id)
  pendingTimers.delete(id)
  flowTimers.delete(id)
}

function getToolDisplayName(name?: string) {
  const names: Record<string, string> = {
    'model.list': '列出协议档',
    'dataset.list': '列出数据集',
    'kb.list': '列出知识库',
    'task.get': '查询任务',
    'report.get': '读取报告',
    'task.create': '创建任务',
    'task.cancel': '取消任务',
    'testcase.confirm': '确认用例入库',
  }
  return (name && names[name]) || name || '调用工具'
}

function getConfirmTitle(kind: string) {
  const titles: Record<string, string> = {
    benchmark: '确认基准评测',
    rag: '确认 RAG 评测',
    testcase: '确认生成用例',
    stress: '确认压测',
  }
  return titles[kind] || '确认评测任务'
}

function toggleProfile(item: StreamItem, pid: string) {
  const card = item.card
  if (!card.profile_ids) card.profile_ids = []
  const idx = card.profile_ids.indexOf(pid)
  if (idx >= 0) card.profile_ids.splice(idx, 1)
  else card.profile_ids.push(pid)
  clearFieldError(item, 'profile_ids')
}

function toggleRagMode(item: StreamItem, mode: string) {
  const card = item.card
  if (!card.rag_mode) card.rag_mode = ['hybrid']
  const idx = card.rag_mode.indexOf(mode)
  if (idx >= 0) {
    if (card.rag_mode.length > 1) card.rag_mode.splice(idx, 1)
  } else {
    card.rag_mode.push(mode)
  }
  clearFieldError(item, 'rag_mode')
}

/** F8 用户修正字段后即时清除对应内联错误。 */
function clearFieldError(item: StreamItem, key: string) {
  if (item.fieldErrors) delete item.fieldErrors[key]
}

/** F10 判断确认卡当前选中知识库是否为外部 Chat 库（外部库无 rag_mode，改选恰好 1 个外部 RAG 服务档）。 */
function isExternalKb(card: any): boolean {
  return availableKbs.value.find(k => k.id === card?.kb_id)?.kind === 'external_chat'
}

/** F10 切换知识库：外部库与内置库的 profile_ids / rag_mode 互斥，切换时清空残留选择。 */
function onKbChange(item: StreamItem) {
  item.card.profile_ids = []
  clearFieldError(item, 'profile_ids')
  clearFieldError(item, 'rag_mode')
}

/** F10 外部 RAG 服务档单选：恰好 1 个，写入 card.profile_ids。 */
function onExternalProfileChange(item: StreamItem, pid: string) {
  item.card.profile_ids = pid ? [pid] : []
  clearFieldError(item, 'profile_ids')
}

/** F8 确认卡内联校验：错误留在卡内 .field-error 红字，不 Toast（对齐原型 556-564）。 */
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
    // 契约字段为 case_source.text（后端确认卡结构），历史 mock 曾用 case_source_text，两者兼容
    const sourceText = String(card.case_source?.text ?? card.case_source_text ?? '')
    if (!sourceText.trim()) errors.case_source = '请提供 file_id 或粘贴文本'
  }
  item.fieldErrors = errors
  return Object.keys(errors).length === 0
}

/** 确认卡规范化：补齐 run / stress / case_source 默认值，保证折叠区 v-model 绑定路径始终存在（对齐 TaskSpec 契约）。 */
function normalizeConfirmCard(card: any) {
  if (!card) return card
  card.run = { ...getDefaultRunConfig(), ...(card.run || {}) }
  card.stress = { ...getDefaultStressConfig(), ...(card.stress || {}) }
  // testcase 确认卡的 case_source 可能由后端缺省下发，此处兜底初始化避免模板 v-model 崩溃
  if (card.kind === 'testcase') {
    card.case_source = { text: '', ...(card.case_source || {}) }
  }
  return card
}

/** D5 会话列表状态点多态：按 status / active_task / 本轮生成中 映射 nav-dot 样式。 */
function sessionDotClass(s: any): string | null {
  if (generatingBySession.value[s.id] || (s.id === currentSessionId.value && isGenerating.value)) return 'running'
  if (s.active_task || s.status === 'running' || s.status === 'queued') return 'running'
  if (s.status === 'succeeded') return 'succeeded'
  if (s.status === 'failed') return 'failed'
  return null
}

/** 会话状态提示语（鼠标悬停指示点时展示）。 */
function sessionDotTooltip(s: any): string {
  if (generatingBySession.value[s.id] || (s.id === currentSessionId.value && isGenerating.value)) return '正在生成…'
  if (s.active_task || s.status === 'running' || s.status === 'queued') return '任务进行中…'
  if (s.status === 'succeeded') return '任务评测成功 (succeeded)'
  if (s.status === 'failed') return '任务执行失败 (failed)'
  return '会话就绪'
}

/** HTML 转义：历史 assistant 消息纯文本安全注入气泡（对齐原型 AE.esc）。 */
function escapeHtml(s: string) {
  return s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;')
}

/* F12 prod 会签人名单：取自 api.admin.getSettings().prod_approvers，失败回退静态文案 */
const prodApprovers = ref<string[]>([])
const prodApproversText = computed(() => (prodApprovers.value.length ? prodApprovers.value.join('、') : 'admin、bob'))

/* S10 进度坞收尾提示：非空时坞保持可见，2.6s 后隐藏 */
const dockClosingNote = ref('')

/** S10 任务结束收尾：先展示完成 note，2.6s 后再隐藏进度坞（对齐原型 hideDock）。 */
function finishDock(note: string) {
  activeTask.value = null
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

/* ─── S3 思考卡流式打字（原型 300-328） ─── */
/** 是否偏好减弱动效：是则思考卡整段直出，不做流式打字。 */
const REDUCED_MOTION = typeof window !== 'undefined' && !!window.matchMedia?.('(prefers-reduced-motion: reduce)').matches

/** S3 打字机推进：26ms 追加 2 字直至逼近 fullText；计时器登记为 flow，暂停/切会话即中断。 */
function pumpThought(item: StreamItem) {
  const full = item.fullText ?? item.text ?? ''
  if (REDUCED_MOTION) { item.text = full; return }
  if (item.done || item.streaming) return
  item.streaming = true
  const step = () => {
    if (item.done) { item.streaming = false; return }
    const target = item.fullText ?? ''
    const cur = item.text ?? ''
    if (cur.length >= target.length) { item.streaming = false; return }
    item.text = target.slice(0, cur.length + 2)
    scrollToBottom()
    trackTimeout(step, 26, true)
  }
  step()
}

/** S3 思考卡收尾：补齐全文 → 200ms 置 done → 再 800ms 自动折叠（对齐原型 finishThought 两段延迟）。 */
function finishThought(item: StreamItem) {
  if (item.done) return
  item.text = item.fullText ?? item.text ?? ''
  item.streaming = false
  trackTimeout(() => {
    item.done = true
    trackTimeout(() => { item.collapsed = true }, 800)
  }, 200)
}

/** 实时模式：下一个非 thought 事件到达时收尾当前思考卡（对齐原型 finishLiveThought）。 */
function finishLiveThought() {
  const last = events.value[events.value.length - 1]
  if (last?.type === 'thought' && !last.done) finishThought(last)
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
watch(inputText, (newVal) => {
  // 当用户在输入框键入 "/stress xxx" 时自动转为行内命令标签
  if (!selectedSlashCmd.value && newVal.startsWith('/') && newVal.includes(' ')) {
    const match = newVal.match(/^(\/[a-zA-Z0-9_-]+)\s([\s\S]*)$/)
    if (match) {
      selectedSlashCmd.value = match[1].slice(1)
      inputText.value = match[2]
      paletteClosedManually.value = true
      nextTick(adjustTextareaHeight)
      return
    }
  }
  if (newVal === '/' || (newVal.startsWith('/') && !newVal.includes(' '))) {
    paletteClosedManually.value = false
  }
  nextTick(adjustTextareaHeight)
})

function triggerFileInput() {
  fileInputRef.value?.click()
}

/** 附件选择后立即调 api.files.upload 换取 file_id，发送消息时随 WS attachments 回传（对齐原型）。 */
async function handleFileUpload(e: Event) {
  const target = e.target as HTMLInputElement
  const f = target.files?.[0]
  if (!f) return
  target.value = ''
  if (f.size > 20 * 1024 * 1024) {
    message.error('单文件不超过 20MB')
    return
  }
  // 先上传拿到 file_id，消息内仅引用 id（契约：attachments = [{ file_id }]）
  const staged = {
    name: f.name,
    size: f.size > 1048576 ? `${(f.size / 1048576).toFixed(1)} MB` : `${Math.max(1, Math.round(f.size / 1024))} KB`,
    file: f,
    id: '',
    uploading: true,
  }
  stagedFiles.value.push(staged)
  try {
    const res = await api.files.upload(f)
    staged.id = res.id
    staged.uploading = false
    message.success('附件已上传')
  } catch {
    staged.uploading = false
    message.error('附件上传失败，发送时将被忽略')
  }
}

/** 键盘事件监听：SlashPalette 导航、Enter 发送，Shift + Enter 换行，Backspace 删除命令 Tag */
function handleKeydown(e: KeyboardEvent) {
  if (paletteClosedManually.value && e.key !== 'Escape') {
    paletteClosedManually.value = false
  }

  // 1. 若斜杠面板可见且非中文输入法合成期，委托斜杠面板处理按键 (↑ / ↓ / Enter / Esc)
  if (showSlashPalette.value && !e.isComposing && slashPaletteRef.value) {
    const handled = slashPaletteRef.value.handleKeyDown(e)
    if (handled) return
  }

  // 2. 参数为空时，按 Backspace 回退命令标签为输入框文字
  if (e.key === 'Backspace' && selectedSlashCmd.value && !inputText.value) {
    e.preventDefault()
    const prev = selectedSlashCmd.value
    selectedSlashCmd.value = ''
    inputText.value = `/${prev}`
    paletteClosedManually.value = false
    nextTick(adjustTextareaHeight)
    return
  }

  // 3. 正常输入换行 / 发送
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

function handleEnterPress() {
  handleSendClick()
}

function handleSendClick() {
  if (isGenerating.value) {
    // /stop：只停本轮生成，走 user_message，不清 queued 任务
    flowTimers.forEach(id => clearTracked(id))
    events.value.forEach(ev => { if (ev.type === 'thought' && !ev.done) finishThought(ev) })
    if (agentWs?.isConnected) {
      agentWs.sendUserMessage('/stop', [], createClientMessageId())
    } else {
      setCurrentGenerating(false)
      events.value.push({
        type: 'agent',
        text: '<p class="muted">已暂停生成。已入队的任务不受影响。</p>',
      })
    }
    scrollToBottom()
    return
  }
  const rawInput = inputText.value.trim()
  const text = selectedSlashCmd.value ? `/${selectedSlashCmd.value}${rawInput ? ' ' + rawInput : ''}` : rawInput
  if (!text && stagedFiles.value.length === 0) return

  const files = [...stagedFiles.value]
  stagedFiles.value = []
  selectedSlashCmd.value = ''
  inputText.value = ''
  adjustTextareaHeight()

  handleUserSend(text, files)
}

/** 快捷芯片/能力卡点击仅填入输入框并聚焦，由用户确认后再发送（对齐原型行为）。 */
function sendPredefined(prompt: string) {
  if (prompt.startsWith('/')) {
    const match = prompt.match(/^(\/[a-zA-Z0-9_-]+)\s*([\s\S]*)$/)
    if (match) {
      selectedSlashCmd.value = match[1].slice(1)
      inputText.value = match[2]
      paletteClosedManually.value = true
      nextTick(() => {
        adjustTextareaHeight()
        textareaRef.value?.focus()
      })
      return
    }
  }
  selectedSlashCmd.value = ''
  inputText.value = prompt
  nextTick(() => {
    adjustTextareaHeight()
    textareaRef.value?.focus()
  })
}

function handleUserSend(text: string, files: any[] = []) {
  const clientMessageId = createClientMessageId()
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
  harnessStage.value = 'plan'
  turnLatencyMs.value = 0
  scrollToBottom(true)

  // 首发消息后以首条消息截断更新会话标题
  const session = sessions.value.find(s => s.id === currentSessionId.value)
  if (session && session.title === '新会话' && text) {
    session.title = text.slice(0, 18)
  }

  // 会话匹配守卫：切换会话时 initWebSocket 在历史回放完成后才指向新会话，
  // 竞态窗口内 agentWs 仍指旧会话——此时发送会把消息写进旧会话且回复被后台分流，
  // 当前视图永远等不到事件（表现为打字占位/空光标气泡卡住）。
  if (agentWs?.isConnected && (!agentWs.sessionId || agentWs.sessionId === currentSessionId.value)) {
    console.log('%c[Agent] 🚀 发送用户消息:', 'color: #3b82f6; font-weight: bold;', text)
    // 打字占位气泡：服务端 LLM 意图识别期间给用户即时反馈，收到任意事件后移除
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
    harnessStage.value = ''
    events.value.push({ type: 'error', code: 'UPSTREAM', message: 'Agent 连接未就绪，请等待重连后重试。' })
    message.error('Agent 连接未就绪，请等待重连后重试')
    scrollToBottom()
  }
}

function simulateAgentFlow(text: string, files: any[]) {
  if (/PRD|用例|测试用例/i.test(text)) {
    runTestCaseFlow(files[0])
  } else if (/RAG|知识库|检索/i.test(text)) {
    runRagFlow()
  } else {
    runBenchmarkFlow(/压测|加压|先评后压/.test(text))
  }
}

function runBenchmarkFlow(withStress = false) {
  const th: StreamItem = {
    type: 'thought',
    text: '',
    fullText: '正在梳理评测目标：对比被测协议档在同一数据集上的规则分。先列出可用协议档与数据集…',
    done: false,
    collapsed: false,
  }
  events.value.push(th)
  pumpThought(th)
  scrollToBottom()

  trackTimeout(() => {
    finishThought(th)
    events.value.push({
      type: 'tool',
      tool: 'model.list',
      args: {},
      result: { items: availableProfiles.value },
      status: 'ok',
      open: false,
    })
    events.value.push({
      type: 'tool',
      tool: 'dataset.list',
      args: {},
      result: { items: availableDatasets.value },
      status: 'ok',
      open: false,
    })
    events.value.push({
      type: 'agent',
      text: `<p>找到 <b>${availableProfiles.value.length}</b> 个被测协议档与 <b>${availableDatasets.value.length}</b> 个数据集。建议用 <b>smoke-20 v3</b>（20 行，主指标 contain）做对比。请确认评测单${withStress ? '；已按「先评后压」预开压测开关' : ''}：</p>`,
    })
    events.value.push({
      type: 'confirm',
      card: normalizeConfirmCard({
        kind: 'benchmark',
        profile_ids: ['p-gpt', 'p-claude'],
        dataset_id: 'ds-smoke',
        run: { concurrency: 5, timeout_s: 60 },
        with_stress: withStress,
        stress: { env: 'test', qps: 20 },
      }),
      isAcked: false,
      summary: '',
      open: true,
    })
    setCurrentGenerating(false)
    scrollToBottom()
  }, 900, true)
}

function runRagFlow() {
  const th: StreamItem = {
    type: 'thought',
    text: '',
    fullText: '目标是评估知识库检索质量。需要知识库与黄金 QA，先列出现有库…',
    done: false,
    collapsed: false,
  }
  events.value.push(th)
  pumpThought(th)
  scrollToBottom()

  trackTimeout(() => {
    finishThought(th)
    events.value.push({
      type: 'tool',
      tool: 'kb.list',
      args: {},
      result: { items: availableKbs.value },
      status: 'ok',
      open: false,
    })
    events.value.push({
      type: 'agent',
      text: '<p>内置库 <b>default</b>（LightRAG，12 篇文档）配有黄金 QA <b>qa-v1 v2</b>（20 条）。默认用 hybrid 模式、K=5。请确认：</p>',
    })
    events.value.push({
      type: 'confirm',
      card: normalizeConfirmCard({
        kind: 'rag',
        kb_id: 'kb-default',
        gold_qa_id: 'gq-1',
        rag_mode: ['hybrid'],
        run: { k: 5, concurrency: 5, timeout_s: 60 },
        with_stress: false,
        stress: { env: 'test', qps: 20 },
      }),
      isAcked: false,
      summary: '',
      open: true,
    })
    setCurrentGenerating(false)
    scrollToBottom()
  }, 900, true)
}

function runTestCaseFlow(file?: any) {
  const th: StreamItem = {
    type: 'thought',
    text: '',
    fullText: '解析输入材料，按正向 / 反向 / 边界 / 等价 / 状态 / 场景策略生成用例，规模按 PRD 复杂度上限控制…',
    done: false,
    collapsed: false,
  }
  events.value.push(th)
  pumpThought(th)
  scrollToBottom()

  trackTimeout(() => {
    finishThought(th)
    events.value.push({
      type: 'agent',
      text: '<p>将基于「支付」模块 PRD 生成用例，预计 40 条（中等复杂度上限 45）。生成后进入 <b>awaiting_case_confirm</b>，需你在 72h 内确认入库。请确认：</p>',
    })
    events.value.push({
      type: 'confirm',
      card: normalizeConfirmCard({
        kind: 'testcase',
        case_source: { text: file ? `附件：${file.name}` : '' },
      }),
      isAcked: false,
      summary: file ? file.name : '粘贴文本输入',
      open: true,
    })
    setCurrentGenerating(false)
    scrollToBottom()
  }, 1000, true)
}

/** A1：ack 校验失败时卡保持可编辑，待 task.create 成功后再盖章。 */
const pendingAckItem = ref<StreamItem | null>(null)

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

  // 真实链路：确认成功前不盖章（A1）；取消可以立即折叠
  if (useLive) {
    if (confirmed) {
      pendingAckItem.value = item
      // confirm_author 是服务端事件元数据，TaskSpec 输入模型严格拒绝，提交前必须移除。
      const { confirm_author: _confirmAuthor, ...patch } = item.card || {}
      agentWs!.sendConfirmAck(true, patch)
      return
    }
    stampConfirmCard(item, false)
    agentWs!.sendConfirmAck(false, item.card)
    events.value.push({ type: 'agent', text: '<p>已取消，未创建任务。需要调整目标可以继续说。</p>' })
    scrollToBottom()
    return
  }

  stampConfirmCard(item, confirmed)

  // 显式 mock 模式：本地演示入队与进度。
  if (!confirmed) {
    events.value.push({
      type: 'agent',
      text: '<p>已取消，未创建任务。需要调整目标可以继续说。</p>',
    })
    scrollToBottom()
    return
  }

  // Mock 模式：本地模拟入队与进度，便于无后端环境演示。
  events.value.push({
    type: 'tool',
    tool: 'task.create',
    args: item.card,
    result: { task_id: 't-' + Date.now().toString(16).slice(4), status: 'queued' },
    status: 'ok',
    open: false,
  })

  activeTask.value = {
    id: 't-' + Math.random().toString(16).slice(2, 8),
    kind: item.card.kind,
    status: 'running',
    config: item.card,
    progress: { done: 20, total: 100, percent: 20, message: '正在执行多模型对比推理与规则打分' },
    created_at: new Date().toISOString(),
  }

  let prog = 20
  const timer = trackInterval(() => {
    prog += 25
    if (activeTask.value) {
      activeTask.value.progress = {
        done: Math.min(100, prog),
        total: 100,
        percent: Math.min(100, prog),
        message: '正在计算规则评分与大模型裁判一致性',
      }
    }
    if (prog >= 100) {
      clearTracked(timer)
      trackTimeout(() => {
        // S10 坞先显示「任务 succeeded」note，2.6s 后再隐藏
        finishDock('任务 succeeded')
        events.value.push({
          type: 'report',
          reportId: 'r-bm-1',
          kpis: defaultKpis,
          bars: [
            { label: 'gpt-test · contain', value: 0.86, max: 1 },
            { label: 'claude-x · contain', value: 0.79, max: 1 },
          ],
        })
        scrollToBottom()
        // 先评后压：质量评测 succeeded 且勾选压测后自动派生共享压测子任务
        if (item.card?.with_stress) runStressChild(item.card)
      }, 600, true)
    }
  }, 1000, true)
}

/** 派生压测子任务（mock 演示）：agent 说明 → stress 进度坞实时序列 → prod 会签 → 压测报告卡。 */
function runStressChild(card: any) {
  const env = card.stress_env || card.stress?.env || 'test'
  const qps = card.stress_qps || card.stress?.qps || 20
  events.value.push({
    type: 'agent',
    text: `<p>质量评测 <b>succeeded</b>，已按「先评后压」自动派生共享压测子任务（env=${env} · ${qps} QPS）。</p>`,
  })
  activeTask.value = {
    id: 't-stress-' + Math.random().toString(16).slice(2, 6),
    kind: 'stress',
    status: env === 'prod' ? 'queued' : 'running',
    need_approval: env === 'prod',
    config: { kind: 'stress', stress: { env, qps, duration_s: card.stress?.duration_s || 120 } },
    progress: { done: 0, total: 100, percent: 0, message: env === 'prod' ? '等待双人会签审批…' : '正在发压…' },
    created_at: new Date().toISOString(),
  }
  scrollToBottom()

  const startStress = () => {
    if (!activeTask.value) return
    activeTask.value.status = 'running'
    activeTask.value.need_approval = false
    let p = 0
    const stressTimer = trackInterval(() => {
      p += 20
      // 压测实时指标驱动坞内 sparkline 与 KPI
      currentStressMetrics.value = {
        qps: Math.round(qps * (0.85 + Math.random() * 0.3)),
        rt: 600 + Math.round(Math.random() * 600),
        err: +(Math.random() * 0.8).toFixed(1),
      }
      if (activeTask.value) {
        activeTask.value.progress = {
          done: Math.min(100, p),
          total: 100,
          percent: Math.min(100, p),
          message: '正在发压并采集 QPS / RT / 错误率',
        }
      }
      if (p >= 100) {
        clearTracked(stressTimer)
        trackTimeout(() => {
          // S10 坞先显示「压测完成」note，2.6s 后再隐藏
          finishDock('压测完成')
          events.value.push({
            type: 'report',
            reportId: 'r-st-1',
            kpis: [
              { value: String(Math.round(qps * 1.1)), label: '峰值 QPS' },
              { value: '1.2s', label: 'P99 延迟' },
              { value: '0.4%', label: '错误率' },
            ],
          })
          scrollToBottom()
        }, 600, true)
      }
    }, 900, true)
  }

  if (env === 'prod') {
    // prod 生产压测需双人会签：模拟会签通过后开始发压
    events.value.push({
      type: 'agent',
      text: '<p>⚠ <b>NEED_APPROVAL</b>：prod 环境压测需双人会签，子任务已挂起等待审批。</p>',
    })
    trackTimeout(() => {
      events.value.push({
        type: 'agent',
        text: '<p>prod 会签已通过（双人确认），压测子任务开始发压。</p>',
      })
      startStress()
    }, 2600, true)
  } else {
    startStress()
  }
}

function handleInterpretReport(reportId: string) {
  const clientMessageId = createClientMessageId()
  events.value.push({
    type: 'user',
    text: `解读报告 #${reportId}`,
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
  scrollToBottom(true)

  // 实时模式交由服务端智能体解读，结果经 WS 事件回流。
  if (agentWs?.isConnected) {
    agentWs.sendUserMessage(`解读报告 #${reportId}`, [], clientMessageId)
    return
  }

  if (!api.isMock()) {
    setCurrentGenerating(false)
    events.value.push({ type: 'error', code: 'UPSTREAM', message: 'Agent 连接未就绪，暂不能解读报告。' })
    message.error('Agent 连接未就绪，暂不能解读报告')
    scrollToBottom()
    return
  }

  const th: StreamItem = {
    type: 'thought',
    text: '',
    fullText: `读取报告 ${reportId} 的指标摘要与失败样本，进行关键退化原因归因…`,
    done: false,
    collapsed: false,
  }
  events.value.push(th)
  pumpThought(th)

  trackTimeout(() => {
    finishThought(th)
    events.value.push({
      type: 'tool',
      tool: 'report.get',
      args: { report_id: reportId },
      result: { scores: [{ profile: 'gpt-test', score: 0.86 }, { profile: 'claude-x', score: 0.79 }] },
      status: 'ok',
      open: false,
    })
    events.value.push({
      type: 'agent',
      text: '<p><b>解读（基于已有报告，不重跑）：</b>gpt-test 以 contain 0.86 领先 claude-x 0.79，失败率 2% 对 5%。两条失败样本分别为 UPSTREAM 502 与超时，与模型能力无关，建议复跑失败行后再冻结基线。</p>',
    })
    setCurrentGenerating(false)
    scrollToBottom()
  }, 1000, true)
}

function handleFailDemo() {
  // 生成中禁止重复触发演示，避免事件流交叉
  if (isGenerating.value) return
  events.value.push({
    type: 'user',
    text: '对比一下 gpt-test 和 claude-x 在 smoke-20 上的表现',
  })
  setCurrentGenerating(true)
  const th: StreamItem = {
    type: 'thought',
    text: '',
    fullText: '目标明确：Benchmark 对比。准备创建任务并检查协议档连通性…',
    done: false,
  }
  events.value.push(th)
  pumpThought(th)
  scrollToBottom(true)

  trackTimeout(() => {
    finishThought(th)
    const toolItem: StreamItem = {
      type: 'tool',
      tool: 'task.create',
      args: { kind: 'benchmark', profile_ids: ['p-gpt', 'p-claude'], dataset_id: 'ds-smoke' },
      status: 'pending',
    }
    events.value.push(toolItem)

    trackTimeout(() => {
      toolItem.status = 'fail'
      toolItem.result = 'UPSTREAM 502: bad gateway（gpt-test 网关超时）'
      events.value.push({
        type: 'error',
        code: 'UPSTREAM',
        message: '被测协议档 gpt-test 返回 502，任务未入队',
      })
      events.value.push({
        type: 'agent',
        text: '<p>创建失败：<b>UPSTREAM 502</b>（gpt-test 网关错误），与模型能力无关。建议先到「协议档」页对 gpt-test 做连通性检查，恢复后重新发送目标即可。</p>',
      })
      setCurrentGenerating(false)
      scrollToBottom()
    }, 800, true)
  }, 800, true)
}

function handleWsToggle() {
  if (isWsOnline.value) {
    message.info('正在断开连接…')
    agentWs?.close()
  } else {
    message.info('正在重新连接（按 last_event_id 补发）…')
    agentWs?.connect()
  }
}

function handleCancelActiveTask(taskId: string) {
  if (!canCancelActiveTask.value || activeTask.value?.id !== taskId) {
    message.error('仅任务创建者可以取消任务')
    return
  }
  if (cancellingTaskId.value === taskId) return
  // S9 取消弹窗区分压测/评测：压测立即停发（危险语义按钮），评测当前样本结束后停止
  const isStress = activeTask.value?.kind === 'stress'
  dialog.warning({
    title: isStress ? '立即停止发压？' : '取消任务？',
    content: isStress
      ? '与评测不同，确认后立刻停发。'
      : '将在当前样本推理完成后停止，已完成的评测得分与报文将完整保留。',
    positiveText: isStress ? '立刻停发' : '确认取消',
    negativeText: '放弃',
    positiveButtonProps: isStress ? { type: 'error' } : undefined,
    onPositiveClick: async () => {
      if (cancellingTaskId.value === taskId) return
      cancellingTaskId.value = taskId
      try {
        // 契约：优先使用 WS 上行 cancel_task；发送失败才回退 REST，避免链路半开时静默丢请求。
        const sentByWs = agentWs?.sendCancelTask(taskId) ?? false
        if (sentByWs) {
          message.info(isStress ? '停止发压请求已提交，等待服务端确认' : '取消请求已提交，等待服务端确认')
          return
        }
        const cancelled = await api.tasks.cancel(taskId)
        finishCancelledTask(cancelled.id)
        message.success(isStress ? '压测任务已停止' : '评测任务已取消（cancelled）')
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
    sessions.value = list || []
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
    if (pid) {
      const hit = (profiles || []).find((p) => p.id === pid)
      agentModelName.value = hit ? hit.model || hit.name : ''
    } else {
      agentModelName.value = ''
    }
  } catch {
    agentModelName.value = ''
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
    agentModelName.value = hit.model || hit.name
    message.success(`已将 Agent 驱动模型切换为「${hit.name}」(${hit.model || hit.protocol})`)
  } catch (err: any) {
    message.error(err.message || '切换模型失败')
  }
}

/** F4 会话历史回放：拉取历史 user/assistant 消息与事件流，严格按时间序与优先级排列
 *  保证思考卡 (ThoughtCard) 与 MCP 短工具卡 (ToolCard) 永远在 AI 回复内容 (Agent Message) 的上方。 */
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
        rawList.push({
          time: t,
          priority: 5,
          item: { type: 'agent', text: m.content || '', raw: m.content || '', noAnim: true },
        })
      }
    }

    // 2. 收集 WS 事件流（思考过程、短工具、确认卡、报告卡等）
    for (const ev of history.events || []) {
      const p = ev.payload || {}
      const t = ev.ts ? new Date(ev.ts).getTime() : 0
      const eid = Number(ev.event_id) || 0

      if (ev.event === 'thought' && !p.stream) {
        // 交付终帧判定：无 stage / skill_id / latency 的 thought 落库事件即助手交付句，
        // 其正文已随 messages.role=assistant 回放成气泡；若再渲染成思考卡会造成
        // 「已思考 N 字」重复卡（原条件 p.stage !== null 对 undefined 恒真，属逻辑缺陷）。
        const isDeliveryFrame = !p.stage && !p.skill_id && p.latency_ms === undefined
        if (!isDeliveryFrame && p.text) {
          rawList.push({
            time: t,
            priority: 2,
            eventId: eid,
            item: {
              type: 'thought',
              text: p.text || '',
              done: true,
              collapsed: true,
              noAnim: true,
              latency_ms: p.latency_ms,
              stage: p.stage,
              skill_id: p.skill_id,
            },
          })
        }
      } else if (ev.event === 'tool_call') {
        rawList.push({
          time: t,
          priority: 3,
          eventId: eid,
          item: { type: 'tool', tool: p.name, args: p.arguments, status: 'pending', open: false, noAnim: true },
        })
      } else if (ev.event === 'tool_result') {
        const target = [...rawList].reverse().find((x) => x.item.type === 'tool' && x.item.tool === p.name && x.item.status === 'pending')
        if (target) {
          target.item.result = p.ok ? p.data : p.error
          target.item.status = p.ok ? 'ok' : 'fail'
          target.item.latency_ms = p.latency_ms
        }
      } else if (ev.event === 'confirm') {
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
      } else if (ev.event === 'error') {
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
      }
    }

    // 3. 严格按时间戳递增排序；若时间戳相同则按优先级排列 (user:1 -> thought:2 -> tool:3 -> confirm:4 -> agent:5 -> report:6 -> error:7)
    rawList.sort((a, b) => {
      if (a.time !== b.time) return a.time - b.time
      if (a.eventId && b.eventId) return a.eventId - b.eventId
      return a.priority - b.priority
    })

    const replay = rawList.map((x) => x.item)

    if (history.pending_confirm) {
      const card = normalizeConfirmCard({
        ...history.pending_confirm,
        confirm_author: history.pending_confirm_author || undefined,
      })
      const existing = [...replay].reverse().find((x) => x.type === 'confirm')
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
    if (!(rt.isGenerating && rt.events.length > replay.length)) {
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
  if (sid === currentSessionId.value && sockets.has(sid)) {
    return
  }
  const epoch = ++selectEpoch
  persistCurrentRuntime()
  currentSessionId.value = sid

  const rt = ensureRuntime(sid)
  events.value = rt.events
  isGenerating.value = rt.isGenerating
  harnessStage.value = rt.harnessStage
  lastToolTitle.value = rt.lastToolTitle
  turnLatencyMs.value = rt.turnLatencyMs
  activeTask.value = rt.activeTask
  currentContextMeter.value = rt.contextMeter
  currentCompactSummary.value = rt.compactSummary
  dockClosingNote.value = ''
  markGenerating(sid, rt.isGenerating)

  const sess = sessions.value.find(s => s.id === sid)
  isRailOpen.value = !!sess?.active_task || rt.isGenerating

  const activeTaskId = sess?.active_task?.id || rt.activeTask?.id
  if (activeTaskId) {
    try {
      const t = await api.tasks.get(activeTaskId)
      if (epoch !== selectEpoch || currentSessionId.value !== sid) return
      if (t && ['queued', 'running', 'awaiting_case_confirm'].includes(t.status)) {
        activeTask.value = {
          id: t.id,
          kind: t.kind,
          status: t.status,
          config: t.config,
          progress: t.progress || { percent: 0, done: 0, total: 100, message: '任务进行中...' },
          creator_id: t.creator_id,
          created_by: t.created_by,
          creator: t.creator,
          created_at: t.created_at,
        }
        rt.activeTask = activeTask.value
      }
    } catch { /* 进度坞失败不阻断切会话 */ }
  }

  const existingWs = sockets.get(sid)
  if (existingWs) {
    agentWs = existingWs
    isWsOnline.value = existingWs.isConnected
    gcIdleSockets(sid)
    scrollToBottom(true)
    return
  }

  const lastEventId = await loadSessionHistory(sid)
  if (epoch !== selectEpoch || currentSessionId.value !== sid) return
  initWebSocket(sid, lastEventId)
}

async function handleCreateSession() {
  try {
    const newSession = await api.sessions.create('新会话')
    sessions.value.unshift(newSession)
    selectSession(newSession.id)
  } catch {
    const localS: AgentSession = {
      id: `s-${Date.now()}`,
      title: '新会话',
      owner_id: authStore.user?.id || '',
      visibility: 'private',
      can_manage: true,
      can_delete: true,
      created_at: new Date().toISOString(),
    }
    sessions.value.unshift(localS)
    selectSession(localS.id)
  }
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
    content: '对话将在列表中隐藏，但消息、任务和报告会保留用于审计回溯。正在生成、待确认或执行中的任务需先处理。',
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
    content: `将删除选中的 ${ids.length} 个会话。消息、任务和报告仍会保留用于审计回溯；包含生成中、待确认或执行中任务的会话会单独失败。`,
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

function initWebSocket(sessionId: string, lastEventId = 0) {
  const reused = sockets.get(sessionId)
  if (reused) {
    agentWs = reused
    isWsOnline.value = reused.isConnected
    gcIdleSockets(sessionId)
    return
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
}

/** 移除打字占位气泡：服务端首个事件到达即表明意图识别已出结果。 */
function dismissTyping() {
  const idx = events.value.findIndex(e => e.type === 'typing')
  if (idx >= 0) events.value.splice(idx, 1)
}

/** 把纯文本渲染为气泡 HTML（转义防 XSS + 换行转 <br>）。 */
function renderBubbleHtml(raw: string): string {
  return escapeHtml(raw).replace(/\n/g, '<br>')
}

/** 后台会话继续生成：把事件写入该会话缓存，不打断当前正在看的对话。 */
function ingestBackground(sid: string, ev: WsServerEvent) {
  if (ev.event === 'pong') return
  const rt = ensureRuntime(sid)
  const buf = rt.events
  const p = ev.payload || {}
  switch (ev.event) {
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
        rt.harnessStage = 'plan'
      }
      break
    }
    case 'thought': {
      if (p.stream === 'think') {
        const delta = String(p.text || '')
        if (!delta) break
        const target = [...buf].reverse().find(e => e.type === 'thought' && !e.done)
        if (target) target.text = (target.text || '') + delta
        else buf.push({ type: 'thought', text: delta, done: false, collapsed: false, streamThink: true })
        markGenerating(sid, true)
        rt.harnessStage = rt.harnessStage || 'plan'
        break
      }
      if (p.stream === 'chunk') {
        const delta = String(p.text || '')
        if (!delta) break
        let target = [...buf].reverse().find(e => e.type === 'agent' && e.streaming)
        if (!target) {
          target = { type: 'agent', raw: '', text: '', streaming: true }
          buf.push(target)
        }
        target.raw = (target.raw || '') + delta
        target.text = renderBubbleHtml(target.raw)
        markGenerating(sid, true)
        break
      }
      const text = String(p.text || '').trim()
      const stage = p.stage as StreamItem['stage'] | undefined
      if (stage) rt.harnessStage = stage
      const think = [...buf].reverse().find(e => e.type === 'thought' && !e.done)
      if (think) {
        // 与前台一致：交付终帧（无 stage）不得覆盖 streamThink 卡的推理内容
        if (text && (stage || !think.streamThink)) think.text = text
        think.done = true
        think.collapsed = true
        if (p.latency_ms !== undefined) think.latency_ms = p.latency_ms
        if (p.skill_id) think.skill_id = p.skill_id
        if (stage) think.stage = stage
      } else if (stage || p.skill_id) {
        buf.push({
          type: 'thought',
          text,
          done: true,
          collapsed: true,
          latency_ms: p.latency_ms,
          stage,
          skill_id: p.skill_id,
        })
      }
      if (text && !stage) {
        const streaming = [...buf].reverse().find(e => e.type === 'agent' && e.streaming)
        if (streaming) {
          streaming.raw = text
          streaming.text = renderBubbleHtml(text)
          streaming.streaming = false
        } else {
          buf.push({ type: 'agent', raw: text, text: renderBubbleHtml(text), streaming: false })
        }
        markGenerating(sid, false)
        rt.harnessStage = ''
      } else if (!stage) {
        const orphan = [...buf].reverse().find(e => e.type === 'agent' && e.streaming)
        if (orphan) orphan.streaming = false
        markGenerating(sid, false)
        rt.harnessStage = ''
      } else {
        markGenerating(sid, true)
      }
      break
    }
    case 'tool_call':
      markGenerating(sid, true)
      rt.harnessStage = 'react'
      buf.push({ type: 'tool', tool: p.name, args: p.arguments, status: 'pending', open: false })
      break
    case 'tool_result': {
      const target = [...buf].reverse().find(x => x.type === 'tool' && x.tool === p.name)
      if (target) {
        target.result = p.ok ? p.data : p.error
        target.status = p.ok ? 'ok' : 'fail'
        if (p.latency_ms !== undefined) target.latency_ms = p.latency_ms
      }
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
    case 'error':
      markGenerating(sid, false)
      buf.push({ type: 'error', code: p.code, message: p.message || '执行遇到错误' })
      break
    case 'report':
      markGenerating(sid, false)
      if (p.report_id) buf.push({ type: 'report', reportId: p.report_id })
      break
    default:
      break
  }
}

/* ─── 打字机渲染：终帧权威全文逐字补齐 ───
   无论是真流式增量、网关不支持 SSE 的单块兜底、还是降级规则版的整段回复，
   终帧到达后都从已显示长度逐字推进到全文，保证任何链路下用户都看到
   「一个字一个字弹出」的效果。定时器登记进 flowTimers，「暂停生成」可中断。 */
function typewriteTo(rawItem: StreamItem, fullText: string) {
  // 响应式关键修复：调用方可能传入 push 进响应式数组前的原始对象引用，
  // 直接修改原始对象不会触发 Vue 重渲染（气泡停留在空文本 + 光标卡死）。
  // reactive() 对同一目标有缓存，与 v-for 渲染取到的是同一个代理，修改即触发更新。
  const item = reactive(rawItem) as StreamItem
  // 已显示前缀可续播时从其长度继续，否则（前缀不匹配）从头渲染
  const start = item.raw && fullText.startsWith(item.raw) ? item.raw.length : 0
  let pos = start
  const total = fullText.length
  if (total === 0) {
    item.streaming = false
    return
  }
  item.streaming = true
  // 长文本提速：避免长回复打字机拖沓（80 字内 24ms/字，超长 10ms/字，每 tick 推进 2 字）
  const stepMs = total > 120 ? 10 : total > 60 ? 16 : 24
  const id = trackInterval(() => {
    pos = Math.min(total, pos + 2)
    item.raw = fullText.slice(0, pos)
    item.text = renderBubbleHtml(item.raw)
    scrollToBottom()
    if (pos >= total) {
      clearTracked(id)
      item.streaming = false
    }
  }, stepMs, true)
}

function handleWsEvent(ev: WsServerEvent) {
  // pong 心跳不参与交互流；其余任何事件到达都意味着本轮已出结果，移除打字占位
  if (ev.event !== 'pong') {
    dismissTyping()
    const isStream = ev.payload && typeof ev.payload.stream === 'string'
    if (!isStream) {
      console.log(`%c[Agent WS] 📩 收到事件: ${ev.event}`, 'color: #8b5cf6; font-weight: bold;', ev)
    }
  }
  const p = ev.payload || {}
  switch (ev.event) {
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
        harnessStage.value = 'plan'
        turnLatencyMs.value = 0
      }
      scrollToBottom()
      break
    }
    case 'thought': {
      // 思考链增量帧（瞬态）：追加到可展开/收起的思考卡，无则新建
      if (p.stream === 'think') {
        const delta = String(p.text || '')
        if (delta) {
          const target = [...events.value].reverse().find(e => e.type === 'thought' && !e.done)
          if (target) {
            target.text = (target.text || '') + delta
          } else {
            console.log('%c[Agent] 💭 深度思考链流式输出中...', 'color: #10b981; font-weight: bold;')
            // reactive 包装：push 后的增量追加必须走响应式代理，否则首帧之后的修改不触发渲染
            events.value.push(reactive({ type: 'thought', text: delta, done: false, collapsed: false, streamThink: true }))
          }
          scrollToBottom()
          setCurrentGenerating(true)
        }
        break
      }
      // 流式增量帧（瞬态，服务端不落库）：追加到当前流式气泡，无则新建
      if (p.stream === 'chunk') {
        const delta = String(p.text || '')
        if (delta) {
          let target = [...events.value].reverse().find(e => e.type === 'agent' && e.streaming)
          if (!target) {
            // reactive 包装：新建后立即修改 raw/text，原始对象不触发渲染会丢首帧
            target = reactive({ type: 'agent', raw: '', text: '', streaming: true }) as StreamItem
            events.value.push(target)
          }
          target.raw = (target.raw || '') + delta
          target.text = renderBubbleHtml(target.raw)
          scrollToBottom()
          setCurrentGenerating(true)
        }
        break
      }
      // 完整回复（终帧或非流式）
      const text = String(p.text || '').trim()
      const stage = p.stage as StreamItem['stage'] | undefined
      if (stage) {
        harnessStage.value = stage
        setCurrentGenerating(true)
      }
      if (typeof p.latency_ms === 'number') turnLatencyMs.value += p.latency_ms
      const think = [...events.value].reverse().find(e => e.type === 'thought' && !e.done)
      if (think) {
        // 终帧是权威全文，不能只依赖可能丢失的瞬态增量帧。
        // 但交付终帧（无 stage）不得覆盖 streamThink 卡的推理内容——那是模型 reasoning，
        // 与交付句是两回事；只结束并折叠该卡，正文走下方打字机气泡。
        if (text && (stage || !think.streamThink)) think.text = text
        think.done = true
        think.collapsed = true
        if (p.latency_ms !== undefined) think.latency_ms = p.latency_ms
        if (p.skill_id) think.skill_id = p.skill_id
        if (stage) think.stage = stage
      } else if (stage || p.skill_id) {
        events.value.push(reactive({
          type: 'thought',
          text,
          done: true,
          collapsed: true,
          latency_ms: p.latency_ms,
          stage,
          skill_id: p.skill_id,
        }))
      }
      console.log('%c[Agent] 💡 思考完成 / 助手回复交付:', 'color: #10b981; font-weight: bold;', {
        chars: text.length,
        latency: p.latency_ms ? `${p.latency_ms}ms` : '未知',
        stage: stage || '-',
        text: text.slice(0, 100) + (text.length > 100 ? '...' : ''),
      })
      if (text && !stage) {
        const streaming = [...events.value].reverse().find(e => e.type === 'agent' && e.streaming)
        if (streaming) {
          typewriteTo(streaming, text)
        } else {
          const item: StreamItem = { type: 'agent', raw: '', text: '', streaming: true }
          events.value.push(item)
          typewriteTo(item, text)
        }
        setCurrentGenerating(false)
        harnessStage.value = ''
      } else if (!stage) {
        const orphan = [...events.value].reverse().find(e => e.type === 'agent' && e.streaming)
        if (orphan) orphan.streaming = false
        setCurrentGenerating(false)
        harnessStage.value = ''
      }
      if (text) scrollToBottom()
      break
    }
    case 'tool_call': {
      console.log('%c[Agent] ⚙️ 短工具调用:', 'color: #f59e0b; font-weight: bold;', p.name, p.arguments)
      finishLiveThought()
      harnessStage.value = 'react'
      lastToolTitle.value = getToolDisplayName(p.name)
      setCurrentGenerating(true)
      events.value.push({
        type: 'tool',
        tool: p.name,
        args: p.arguments,
        status: 'pending',
        open: false,
      })
      scrollToBottom()
      break
    }
    case 'tool_result': {
      console.log('%c[Agent] ✅ 短工具完成:', 'color: #10b981; font-weight: bold;', p.name, {
        ok: p.ok,
        latency: `${p.latency_ms || 0}ms`,
        data: p.data || p.error,
      })
      const target = [...events.value].reverse().find(x => x.type === 'tool' && x.tool === p.name)
      if (target) {
        target.result = p.ok ? p.data : p.error
        target.status = p.ok ? 'ok' : 'fail'
        if (p.latency_ms !== undefined) {
          target.latency_ms = p.latency_ms
          turnLatencyMs.value += p.latency_ms
        }
      }
      // 把短工具发现结果回填到确认卡可选项
      if (p.ok) {
        if (p.name === 'model.list') availableProfiles.value = p.data?.items || []
        if (p.name === 'dataset.list') availableDatasets.value = p.data?.items || []
        if (p.name === 'kb.list') availableKbs.value = p.data?.items || []
        if (p.name === 'task.cancel' && p.data?.task_id) {
          finishCancelledTask(p.data.task_id)
          message.success('任务已取消（cancelled）')
        }
        if (p.name === 'task.create' && pendingAckItem.value) {
          stampConfirmCard(pendingAckItem.value, true)
          pendingAckItem.value = null
        }
      }
      scrollToBottom()
      break
    }
    case 'confirm': {
      console.log('%c[Agent] 📋 任务确认卡到达:', 'color: #8b5cf6; font-weight: bold;', p)
      lastConfirmKind = p.kind || 'benchmark'
      finishLiveThought()
      setCurrentGenerating(false)
      harnessStage.value = ''
      events.value.push({
        type: 'confirm',
        // 契约：确认卡 TaskSpec 在 payload；规范化补齐 run / stress 默认值，折叠区绑定路径始终有效
        card: normalizeConfirmCard(p),
        confirmAuthor: p.confirm_author || null,
        isAcked: false,
        summary: '',
        open: true,
      })
      scrollToBottom()
      break
    }
    case 'progress': {
      if (ev.task_id) {
        // 契约：进度字段在 payload（percent/done/total/message）；首个进度事件到达时自动起坞
        const progress = { percent: p.percent, done: p.done, total: p.total, message: p.message }
        if (!activeTask.value || activeTask.value.id !== ev.task_id) {
          const lastCard = [...events.value].reverse().find(x => x.type === 'confirm')?.card
          activeTask.value = {
            id: ev.task_id,
            kind: lastCard?.kind || lastConfirmKind,
            status: 'running',
            config: lastCard || { kind: lastConfirmKind },
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
        // 无报告的任务类型（如 testcase 骨架）以 100% 进度作为坞收尾信号
        if ((progress.percent ?? 0) >= 100) finishDock('任务已完成')
      }
      break
    }
    case 'report': {
      finishLiveThought()
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
    case 'error': {
      finishLiveThought()
      // 取消失败时恢复按钮；不能保留“取消中”假象阻断用户重试。
      if (cancellingTaskId.value && (!ev.task_id || ev.task_id === cancellingTaskId.value)) {
        cancellingTaskId.value = null
      }
      // A1：校验失败保留确认卡可编辑，不盖章
      if (pendingAckItem.value) {
        pendingAckItem.value.isAcked = false
        pendingAckItem.value.open = true
        pendingAckItem.value = null
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
  // 顶栏/输入框的 Agent 模型名改为按后端协议档动态解析，不再硬编码
  resolveAgentModelName()
  if (sessions.value.length > 0) {
    // selectSession 内部完成历史回放对齐、WS 建立与侧轨展开（F4/F17）
    selectSession(sessions.value[0].id)
  } else {
    await handleCreateSession()
  }
  // F12 拉取 prod 会签人名单用于确认卡动态提示；失败静默回退静态文案
  try {
    const settings = await api.admin.getSettings()
    if (settings?.prod_approvers?.length) prodApprovers.value = settings.prod_approvers
  } catch {}
  // F15 调度侧轨心跳：2.8s 随机推进节点负载；有运行中任务时 40% 概率 prepend TICK 日志（上限 12 条截断）
  trackInterval(() => {
    if (!api.isMock() || !isRailOpen.value) return
    const w = railWorkers.value[Math.floor(Math.random() * railWorkers.value.length)]
    w.load = Math.max(6, Math.min(94, w.load + (Math.random() < 0.5 ? -1 : 1) * (4 + Math.round(Math.random() * 10))))
    if (activeTask.value && Math.random() < 0.4) {
      dispatchLogs.value.unshift({
        time: new Date().toTimeString().slice(0, 8),
        kind: 'TICK',
        msg: `${w.id} 负载 ${w.load}% · 心跳正常`,
      })
      if (dispatchLogs.value.length > 12) dispatchLogs.value.length = 12
    }
  }, 2800)
  // 消费报告页「在对话中解读」直达参数（兼容 ?interpret= 与 ?report_id=）。
  const interpretId = (route.query.interpret || route.query.report_id) as string | undefined
  if (interpretId) {
    if (api.isMock()) {
      handleInterpretReport(interpretId)
    } else {
      // 实时模式需等待 WS 建立连接后再发送解读请求；超时只提示连接异常，禁止伪造解读。
      // 兜底定时器与 watch 均登记在册，组件卸载时统一清理。
      const fallbackTimer = trackTimeout(() => {
        events.value.push({ type: 'error', code: 'UPSTREAM', message: 'Agent 连接未就绪，报告解读将在重连后继续。' })
        message.warning('Agent 连接未就绪，正在等待重连')
        scrollToBottom()
      }, 5000)
      interpretStopWatch = watch(isWsOnline, (online) => {
        if (online) {
          clearTracked(fallbackTimer)
          interpretStopWatch?.()
          interpretStopWatch = null
          handleInterpretReport(interpretId)
        }
      })
    }
  }
})

onBeforeUnmount(() => {
  // 统一清理登记的全部定时器与解读监听，防止卸载后回调触发
  pendingTimers.forEach(id => {
    window.clearTimeout(id)
    window.clearInterval(id)
  })
  pendingTimers.clear()
  interpretStopWatch?.()
  interpretStopWatch = null
  for (const ws of sockets.values()) {
    ws.close()
  }
  sockets.clear()
  agentWs = null
})
</script>

<style scoped>
.agent-layout {
  height: calc(100vh - var(--topbar-h) - 20px);
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

.user-author {
  color: var(--text-tertiary);
  font-size: 11px;
  font-weight: 600;
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
.think-latency {
  font-size: 11px;
  font-weight: 500;
  color: var(--text-tertiary);
  background: var(--bg-main);
  padding: 1px 6px;
  border-radius: 4px;
  margin-left: 2px;
}
.head-model-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: var(--accent-ai);
}

/* 底部输入框整体容器（固定吸附于对话流底部，不随会话滚动消失） */
.composer {
  padding: 6px 20px 14px;
  flex-shrink: 0;
  background: var(--bg-main);
}

/* 输入卡片：上部多行文本，下部操作底栏（对齐 Gemini / Cursor / Claude 对话框） */
.composer-card {
  max-width: 780px;
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

/* 顶部激活的斜杠命令状态识别芯片 */
.composer-command-pill {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 3px 8px;
  margin-bottom: 4px;
  background: var(--t-tasks, #e0e7ff);
  border: 1px solid color-mix(in srgb, var(--accent-ai, #6366f1) 25%, transparent);
  border-radius: 6px;
  width: fit-content;
  animation: pill-pop 0.15s ease-out;
  user-select: none;
}

/* 输入框上半区行容器 */
.composer-input-row {
  display: flex;
  align-items: flex-start;
  gap: 0;
  width: 100%;
  min-height: 38px;
}

/* 行内命令前缀：纯文本高亮，无卡片框/无背景/无边框 */
.composer-cmd-prefix {
  display: inline-block;
  padding: 4px 0 4px 6px;
  background: transparent;
  color: var(--accent-ai, #6366f1);
  font-family: var(--font-mono, monospace);
  font-size: 14.5px;
  line-height: 1.55;
  font-weight: 700;
  flex-shrink: 0;
  user-select: none;
}

[data-theme='dark'] .composer-cmd-prefix {
  color: #818cf8;
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
  width: 26px;
  height: 26px;
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
  width: 30px;
  height: 30px;
  border-radius: 50%;
  border: none;
  display: flex;
  align-items: center;
  justify-content: center;
  background: var(--bg-elevated);
  color: var(--text-tertiary);
  cursor: not-allowed;
  transition: all 0.15s ease;
  flex-shrink: 0;
}

.composer-send-btn.active {
  background: var(--text-primary);
  color: #fff;
  cursor: pointer;
}

.composer-send-btn.active:hover {
  opacity: 0.88;
  transform: scale(1.05);
}

/* F9 会话占槽时确认卡 note 转 warning 色 */
.confirm-note.warn {
  color: var(--accent-warning);
}
</style>
