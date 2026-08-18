<template>
  <div class="agent-layout" :class="{ 'with-rail': isRailOpen, 'no-list': isListCollapsed }">
    <!-- 左侧会话列表轨 (264px) -->
    <aside class="session-list" data-od-id="session-list">
      <div class="session-list-head">
        <button class="btn btn-secondary" style="width: 100%" @click="handleCreateSession">
          + 新建会话
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
            <span>{{ s.title || '新会话' }}</span>
            <i v-if="s.active_task" class="nav-dot running"></i>
          </div>
          <div class="row-between" style="margin-top: 2px">
            <span class="session-time">{{ s.time || formatRelativeTime(s.created_at) }}</span>
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
        <span class="chat-head-model">Agent · {{ agentModelName }}</span>
        <span v-if="isGenerating" class="gen-pill">
          <i class="bdot"></i>
          <span>生成中</span>
        </span>

        <span class="grow"></span>

        <!-- 调度视图切换按钮 -->
        <button
          class="btn btn-sm"
          :class="isRailOpen ? 'btn-secondary' : 'btn-ghost'"
          title="展开/折叠任务调度分配侧轨"
          @click="isRailOpen = !isRailOpen"
        >
          调度视图
        </button>

        <!-- 模拟失败与模拟断线按钮 -->
        <button class="btn btn-ghost btn-sm" @click="handleFailDemo">模拟失败</button>
        <button class="btn btn-ghost btn-sm" @click="handleWsToggle">
          {{ isWsOnline ? '模拟断线' : '恢复连接' }}
        </button>
      </div>

      <!-- 断线重连横幅提示 -->
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
            <h2 class="welcome-title">
              {{ isRagMode ? '知识库检索质量评估，全链路调优与召回分析。' : '说一句目标，拿回一份评测报告。' }}
            </h2>
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
            <!-- 2.1 用户气泡 -->
            <div v-if="item.type === 'user'" class="msg-user">
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

            <!-- 2.2 思考卡片 -->
            <div
              v-else-if="item.type === 'thought'"
              class="thought-card"
              :class="{ done: item.done, collapsed: item.collapsed }"
            >
              <div class="thought-head" @click="item.collapsed = !item.collapsed">
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round">
                  <path d="M12 3a7 7 0 0 1 4 12.7V17a2 2 0 0 1-2 2h-4a2 2 0 0 1-2-2v-1.3A7 7 0 0 1 12 3Z" />
                  <path d="M10 21h4" />
                </svg>
                <span>思考</span>
                <svg class="chev" width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round">
                  <path d="m6 9 6 6 6-6" />
                </svg>
              </div>
              <div class="thought-body">{{ item.text }}</div>
            </div>

            <!-- 2.3 短 MCP 工具调用卡 -->
            <div
              v-else-if="item.type === 'tool'"
              class="tool-card"
              :class="{ open: item.open }"
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
                <span class="tool-name">{{ getToolDisplayName(item.tool) }}</span>
                <span class="tool-state-text" :class="{ fail: item.status === 'fail' }">
                  {{ item.status === 'pending' ? '调用中' : item.status === 'ok' ? '完成' : '失败' }}
                </span>
                <svg class="chev" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round">
                  <path d="m6 9 6 6 6-6" />
                </svg>
              </div>
              <div v-show="item.open" class="tool-detail">
                <div class="td-label">输入</div>
                <pre class="code">{{ JSON.stringify(item.args || {}, null, 2) }}</pre>
                <div class="td-label">输出</div>
                <pre class="code">{{ typeof item.result === 'string' ? item.result : JSON.stringify(item.result || {}, null, 2) }}</pre>
              </div>
            </div>

            <!-- 2.4 任务确认卡 (Benchmark / RAG / TestCase) -->
            <div
              v-else-if="item.type === 'confirm' && item.card"
              class="confirm-card"
              :class="{ acked: item.isAcked, open: item.open }"
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
                        @click="toggleProfile(item.card, p.id)"
                      >
                        {{ p.name }} <span class="mono" style="opacity: 0.7">{{ p.model }}</span>
                      </button>
                    </div>
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
                      <select v-model="item.card.kb_id" class="select">
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

                  <div class="field">
                    <span class="field-label">rag_mode（1–4 个，默认 hybrid）</span>
                    <div class="chip-group">
                      <button
                        v-for="m in ['naive', 'local', 'global', 'hybrid']"
                        :key="m"
                        class="chip"
                        :class="{ on: item.card.rag_mode?.includes(m as any) }"
                        @click="toggleRagMode(item.card, m)"
                      >
                        {{ m }}
                      </button>
                    </div>
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
                      v-model="item.card.case_source_text"
                      class="textarea"
                      placeholder="粘贴 PRD / 接口描述文本（或用附件上传 OpenAPI / Excel）"
                    ></textarea>
                  </div>
                  <div class="field-hint">
                    规模参考上限：PRD 简单 / 中 / 复杂 → 20 / 45 / 80 条；超上限将停止并提示拆分。生成后需在 72h 内确认入库。
                  </div>
                </template>

                <!-- 高级运行参数折叠项 -->
                <div v-if="['benchmark', 'rag'].includes(item.card.kind)" class="fold-card" :class="{ open: item.showRunConfig }">
                  <div class="fold-head" @click="item.showRunConfig = !item.showRunConfig">
                    <span class="fold-title">高级运行参数</span>
                    <span class="small tertiary mono">concurrency / timeout / max_tokens / judge</span>
                    <svg class="chev" width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2">
                      <path d="m6 9 6 6 6-6" />
                    </svg>
                  </div>
                  <div v-show="item.showRunConfig" class="fold-body">
                    <div class="form-row">
                      <div class="field">
                        <span class="field-label">并发并发数 (concurrency)</span>
                        <input v-model.number="item.card.concurrency" type="number" class="input mono" placeholder="默认 5" />
                      </div>
                      <div class="field">
                        <span class="field-label">单次超时 (timeout_s)</span>
                        <input v-model.number="item.card.timeout_s" type="number" class="input mono" placeholder="默认 60s" />
                      </div>
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
                  <div v-show="item.card.with_stress" class="fold-body">
                    <div class="form-row">
                      <div class="field">
                        <span class="field-label">压测环境 (env)</span>
                        <select v-model="item.card.stress_env" class="select">
                          <option value="test">test · 测试环境（免会签）</option>
                          <option value="staging">staging · 预发环境</option>
                          <option value="prod">prod · 生产环境（需双人会签）</option>
                        </select>
                      </div>
                      <div class="field">
                        <span class="field-label">目标 QPS (qps)</span>
                        <input v-model.number="item.card.stress_qps" type="number" class="input mono" placeholder="例如 20" />
                      </div>
                    </div>
                    <div v-if="item.card.stress_env === 'prod'" class="badge badge-warning" style="margin-top: 6px">
                      ⚠ prod 生产压测：评测成功后子任务将处于待会签状态，会签完成后才开始发压。
                    </div>
                  </div>
                </div>
              </div>

              <!-- 卡片底部按钮与盖章状态 -->
              <div class="confirm-foot">
                <template v-if="!item.isAcked">
                  <span class="confirm-note">未确认不入队；确认前可修改字段</span>
                  <span class="spacer"></span>
                  <button class="btn btn-secondary" @click="handleConfirmAck(item, false)">取消</button>
                  <button class="btn btn-sign" @click="handleConfirmAck(item, true)">确认并开始</button>
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
                <router-link :to="`/reports/${item.reportId}`" class="btn btn-sign btn-sm">
                  查看报告
                </router-link>
                <button class="btn btn-secondary btn-sm" @click="handleInterpretReport(item.reportId || '')">
                  在对话中解读
                </button>
              </div>
            </div>

            <!-- 2.6 错误条 -->
            <div v-else-if="item.type === 'error'" class="error-strip">
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" style="flex: 0 0 16px; margin-top: 1px">
                <circle cx="12" cy="12" r="9" />
                <path d="M12 7.5v5.5" />
                <circle cx="12" cy="16.4" r=".4" fill="currentColor" />
              </svg>
              <div>
                <b>{{ item.code || 'ERROR' }}</b> · {{ item.message }}
              </div>
            </div>

            <!-- 2.7 Agent 文本回复 -->
            <div v-else-if="item.type === 'agent'" class="msg-agent" v-html="item.text"></div>
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

      <!-- 3. 吸附式进度坞 -->
      <div v-if="activeTask" class="progress-dock" data-od-id="progress-dock">
        <div class="progress-dock-inner" :class="{ stress: activeTask.kind === 'stress' }">
          <template v-if="activeTask.kind === 'stress'">
            <div class="dock-row">
              <KindTag kind="stress" />
              <svg class="spark" viewBox="0 0 180 36" preserveAspectRatio="none">
                <polygon class="a-qps" :points="sparkPolygonPoints" />
                <polyline class="l-qps" :points="sparkLinePoints" />
                <circle class="dot-end" :cx="sparkLastPoint.x" :cy="sparkLastPoint.y" r="2.4" />
              </svg>
              <span class="mini-series">
                <span class="ms ms-qps">QPS <b>{{ currentStressMetrics.qps }}</b></span>
                <span class="ms ms-rt">RT <b>{{ currentStressMetrics.rt }}ms</b></span>
                <span class="ms ms-err">错误率 <b>{{ currentStressMetrics.err }}%</b></span>
              </span>
              <span class="progress-msg">{{ activeTask.progress?.message || '压测执行中' }}</span>
              <button class="btn btn-ghost btn-sm" @click="handleCancelActiveTask(activeTask.id)">
                立即停止
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
            <button class="btn btn-ghost btn-sm" @click="handleCancelActiveTask(activeTask.id)">
              取消
            </button>
          </template>
        </div>
      </div>

      <!-- 4. 底部多功能输入区 -->
      <div class="composer" data-od-id="composer">
        <!-- 快捷 Prompt 芯片栏 -->
        <div class="quick-chips">
          <button
            v-for="chip in currentQuickChips"
            :key="chip"
            class="chip"
            @click="sendPredefined(chip)"
          >
            {{ chip }}
          </button>
        </div>

        <!-- 附件暂存架 -->
        <div v-if="stagedFiles.length" class="attach-stage" style="display: flex; gap: 8px; flex-wrap: wrap; margin-bottom: 8px">
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

        <div class="composer-inner">
          <button class="composer-btn" title="添加附件（≤20MB）" @click="triggerFileInput">
            <svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round">
              <path d="m21 11.5-8.2 8.2a5.5 5.5 0 0 1-7.8-7.8l8.5-8.5a3.7 3.7 0 0 1 5.2 5.2l-8.5 8.5a1.8 1.8 0 0 1-2.6-2.6l7.8-7.8" />
            </svg>
          </button>
          <input
            ref="fileInputRef"
            type="file"
            hidden
            accept=".md,.txt,.html,.pdf,.json,.yaml,.yml,.xlsx,.xls,.csv,.jsonl"
            @change="handleFileUpload"
          />

          <textarea
            ref="textareaRef"
            v-model="inputText"
            rows="1"
            placeholder="说明要评什么（模型 / RAG / 生成用例），我会澄清后给你确认卡。"
            @keydown.enter.prevent="handleEnterPress"
            @input="adjustTextareaHeight"
          ></textarea>

          <span class="composer-model">Agent · {{ agentModelName }}</span>

          <button
            class="send-btn"
            :class="{ ready: isGenerating || inputText.trim().length > 0 }"
            :disabled="!isGenerating && inputText.trim().length === 0"
            :title="isGenerating ? '暂停生成' : '发送'"
            @click="handleSendClick"
          >
            <svg v-if="isGenerating" width="14" height="14" viewBox="0 0 24 24" fill="currentColor">
              <rect x="6" y="6" width="12" height="12" rx="2" />
            </svg>
            <svg v-else width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
              <path d="M12 19V5M5 12l7-7 7 7" />
            </svg>
          </button>
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
import { ref, computed, onMounted, onBeforeUnmount, nextTick } from 'vue'
import { useMessage, useDialog } from 'naive-ui'
import { api } from '../api/http'
import { AgentWebSocket } from '../api/ws'
import type { Task, TaskSpec, WsServerEvent, Profile, Dataset, KnowledgeBase, GoldQA } from '../api/types'
import KindTag from '../components/common/KindTag.vue'

const message = useMessage()
const dialog = useDialog()
const chatScrollRef = ref<HTMLDivElement | null>(null)
const textareaRef = ref<HTMLTextAreaElement | null>(null)
const fileInputRef = ref<HTMLInputElement | null>(null)

const isListCollapsed = ref(false)
const isRailOpen = ref(false)
const isWsOnline = ref(true)
const isGenerating = ref(false)
const showJumpBottom = ref(false)
const agentModelName = ref('gpt-5-pro')

const sessions = ref<any[]>([
  { id: 's1', title: 'GPT-4o 与 Claude 3.5 对比评测', time: '刚刚', active_task: true, created_at: new Date().toISOString() },
  { id: 's2', title: '知识库 default 检索评测', time: '10分钟前', active_task: false, created_at: new Date(Date.now() - 600000).toISOString() },
])
const currentSessionId = ref<string>('s1')
const currentSession = computed(() => sessions.value.find(s => s.id === currentSessionId.value) || sessions.value[0])

const inputText = ref('')
const stagedFiles = ref<any[]>([])
const activeTask = ref<Task | null>(null)

const availableProfiles = ref<Profile[]>([
  { id: 'p-gpt', name: 'gpt-test', model: 'gpt-4o', protocol: 'openai_chat', base_url: 'https://api.openai.com/v1', usages: ['target'], created_at: new Date().toISOString() },
  { id: 'p-claude', name: 'claude-x', model: 'claude-3-5-sonnet-20241022', protocol: 'anthropic_messages', base_url: 'https://api.anthropic.com', usages: ['target'], created_at: new Date().toISOString() },
])
const availableDatasets = ref<Dataset[]>([
  { id: 'ds-smoke', name: 'smoke-20', version: 3, row_count: 20, pending_complete_count: 0, metric: 'contain', owner: 'admin', created_at: new Date().toISOString() },
])
const availableKbs = ref<KnowledgeBase[]>([
  { id: 'kb-default', name: 'default', kind: 'lightrag', doc_count: 12, is_core: true, owner: 'admin' },
  { id: 'kb-cs', name: '外挂客服', kind: 'external_chat', doc_count: null, is_core: false, owner: 'alice' },
])
const availableGoldQas = ref<GoldQA[]>([
  { id: 'gq-1', kb_id: 'kb-default', name: 'qa-v1', version: 2, row_count: 20, owner: 'admin', created_at: new Date().toISOString() },
])

const isRagMode = ref(false)

const LLM_CAPS = [
  { id: 'cap-benchmark', name: '多模型基准对比', desc: '1–5 个协议档并排测试，输出 contain / exact / Judge 打分', say: '对比一下 gpt-test 和 claude-x 在 smoke-20 上的表现', icoSvg: '<path d="M4 20V10M10 20V4M16 20v-8M3 20h18"/>' },
  { id: 'cap-prompt', name: 'Prompt 效果评测', desc: '评测不同系统提示词与上下文在同一数据集上的得分差异', say: '评测系统 Prompt 在支付链路问答上的准确率', icoSvg: '<rect x="4" y="4" width="16" height="16" rx="3"/><path d="M8 9h8M8 13h5"/>' },
  { id: 'cap-testcase', name: 'PRD 生成用例', desc: '附 PRD / OpenAPI，按 6 种策略生成，72h 内确认入库', say: '帮我把这份支付 PRD 生成测试用例', icoSvg: '<path d="M9 11.5 11 14l4.5-5"/><rect x="4" y="4" width="16" height="16" rx="3"/>' },
  { id: 'cap-stress', name: '先评后压', desc: '质量达标后自动压测同一 endpoint，实时监控 QPS / RT', say: '评测 gpt-test 质量达标后自动加压测 10 QPS', icoSvg: '<path d="M3 17l5-6 4 3 6-8"/><path d="M18 6h3v3"/>' }
]

const RAG_CAPS = [
  { id: 'cap-rag', name: 'RAG 检索评测', desc: '知识库 + 黄金 QA，输出 Hit Rate@5 / MRR / Recall', say: '评估 default 知识库的检索质量', icoSvg: '<path d="M5 5.5A2.5 2.5 0 0 1 7.5 3H19v15H7.5A2.5 2.5 0 0 0 5 20.5Z"/><path d="M5 18.5V5.5"/><path d="M9 7.5h6"/>' },
  { id: 'cap-modes', name: '4 模式横向对比', desc: '对比 LightRAG naive / local / global / hybrid 检索表现', say: '横向对比 LightRAG 四种模式在 qa-v1 上的表现', icoSvg: '<circle cx="12" cy="12" r="3"/><path d="M3 12h3M18 12h3M12 3v3M12 18v3"/>' },
  { id: 'cap-qa', name: '黄金 QA 检验', desc: '校验 expected_doc_ids 召回命中与相似度分布', say: '检验 default 知识库黄金 QA 覆盖度', icoSvg: '<path d="M9 11.5 11 14l4.5-5"/><circle cx="12" cy="12" r="9"/>' },
  { id: 'cap-rag-stress', name: 'RAG 接口加压', desc: '对 LightRAG query 或外部 RAG HTTP 服务发起高并发压测', say: '对 default 知识库 query 接口跑 20 QPS 压测', icoSvg: '<path d="M3 17l5-6 4 3 6-8"/><path d="M18 6h3v3"/>' }
]

const currentCaps = computed(() => isRagMode.value ? RAG_CAPS : LLM_CAPS)

const currentQuickChips = computed(() => {
  return isRagMode.value
    ? ['评估 default 知识库的检索质量', '横向对比 LightRAG 四种模式在 qa-v1 上的表现', '检验 default 知识库黄金 QA 覆盖度', '对 default 知识库 query 接口跑 20 QPS 压测']
    : ['对比一下 gpt-test 和 claude-x 在 smoke-20 上的表现', '帮我把这份 PRD 生成测试用例', '评估 default 知识库的检索质量', '跑完基准评测后自动加压测']
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
const sparkPointsData = [[12, 210], [38, 260], [64, 340], [92, 520], [118, 890], [118, 1200]]

const sparkLinePoints = computed(() => {
  const W = 180, H = 36, P = 3
  const maxQ = 120
  return sparkPointsData.map((p, i) => {
    const x = P + i * (W - 2 * P) / (sparkPointsData.length - 1)
    const y = H - P - (p[0] / maxQ) * (H - 2 * P)
    return `${x.toFixed(1)},${y.toFixed(1)}`
  }).join(' ')
})

const sparkPolygonPoints = computed(() => {
  const W = 180, H = 36, P = 3
  const firstX = P, lastX = W - P
  return `${firstX},${H - P} ${sparkLinePoints.value} ${lastX},${H - P}`
})

const sparkLastPoint = computed(() => {
  const W = 180, H = 36, P = 3
  const last = sparkPointsData[sparkPointsData.length - 1]
  return {
    x: W - P,
    y: H - P - (last[0] / 120) * (H - 2 * P),
  }
})

interface StreamItem {
  type: 'user' | 'agent' | 'thought' | 'tool' | 'confirm' | 'report' | 'error'
  text?: string
  done?: boolean
  collapsed?: boolean
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
}

const events = ref<StreamItem[]>([])
let agentWs: AgentWebSocket | null = null

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

function toggleProfile(card: any, pid: string) {
  if (!card.profile_ids) card.profile_ids = []
  const idx = card.profile_ids.indexOf(pid)
  if (idx >= 0) card.profile_ids.splice(idx, 1)
  else card.profile_ids.push(pid)
}

function toggleRagMode(card: any, mode: string) {
  if (!card.rag_mode) card.rag_mode = ['hybrid']
  const idx = card.rag_mode.indexOf(mode)
  if (idx >= 0) {
    if (card.rag_mode.length > 1) card.rag_mode.splice(idx, 1)
  } else {
    card.rag_mode.push(mode)
  }
}

function handleScroll() {
  if (!chatScrollRef.value) return
  const { scrollTop, scrollHeight, clientHeight } = chatScrollRef.value
  showJumpBottom.value = scrollHeight - scrollTop - clientHeight > 72
}

function scrollToBottom(force = false) {
  nextTick(() => {
    if (chatScrollRef.value) {
      chatScrollRef.value.scrollTop = chatScrollRef.value.scrollHeight
    }
  })
}

function adjustTextareaHeight() {
  if (!textareaRef.value) return
  textareaRef.value.style.height = 'auto'
  textareaRef.value.style.height = Math.min(160, textareaRef.value.scrollHeight) + 'px'
}

function triggerFileInput() {
  fileInputRef.value?.click()
}

function handleFileUpload(e: Event) {
  const target = e.target as HTMLInputElement
  const f = target.files?.[0]
  if (!f) return
  target.value = ''
  if (f.size > 20 * 1024 * 1024) {
    message.error('单文件不超过 20MB')
    return
  }
  stagedFiles.value.push({
    name: f.name,
    size: f.size > 1048576 ? `${(f.size / 1048576).toFixed(1)} MB` : `${Math.max(1, Math.round(f.size / 1024))} KB`,
    file: f,
  })
  message.success('附件已添加')
}

function handleEnterPress() {
  handleSendClick()
}

function handleSendClick() {
  if (isGenerating.value) {
    isGenerating.value = false
    events.value.push({
      type: 'agent',
      text: '<p class="muted">已暂停生成。已入队的任务不受影响。</p>',
    })
    scrollToBottom()
    return
  }
  const text = inputText.value.trim()
  if (!text && stagedFiles.value.length === 0) return

  const files = [...stagedFiles.value]
  stagedFiles.value = []
  inputText.value = ''
  adjustTextareaHeight()

  handleUserSend(text, files)
}

function sendPredefined(prompt: string) {
  handleUserSend(prompt, [])
}

function handleUserSend(text: string, files: any[] = []) {
  events.value.push({
    type: 'user',
    text,
    files,
  })
  isGenerating.value = true
  scrollToBottom(true)

  if (agentWs) {
    agentWs.sendUserMessage(text, files.map(f => f.name))
  } else {
    simulateAgentFlow(text, files)
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
    text: '正在梳理评测目标：对比被测协议档在同一数据集上的规则分。先列出可用协议档与数据集…',
    done: false,
    collapsed: false,
  }
  events.value.push(th)
  scrollToBottom()

  setTimeout(() => {
    th.done = true
    th.collapsed = true
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
      card: {
        kind: 'benchmark',
        profile_ids: ['p-gpt', 'p-claude'],
        dataset_id: 'ds-smoke',
        with_stress: withStress,
        stress_env: 'test',
        stress_qps: 20,
      },
      isAcked: false,
      summary: '',
      open: true,
    })
    isGenerating.value = false
    scrollToBottom()
  }, 900)
}

function runRagFlow() {
  const th: StreamItem = {
    type: 'thought',
    text: '目标是评估知识库检索质量。需要知识库与黄金 QA，先列出现有库…',
    done: false,
    collapsed: false,
  }
  events.value.push(th)
  scrollToBottom()

  setTimeout(() => {
    th.done = true
    th.collapsed = true
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
      card: {
        kind: 'rag',
        kb_id: 'kb-default',
        gold_qa_id: 'gq-1',
        rag_mode: ['hybrid'],
        with_stress: false,
        stress_env: 'test',
        stress_qps: 20,
      },
      isAcked: false,
      summary: '',
      open: true,
    })
    isGenerating.value = false
    scrollToBottom()
  }, 900)
}

function runTestCaseFlow(file?: any) {
  const th: StreamItem = {
    type: 'thought',
    text: '解析输入材料，按正向 / 反向 / 边界 / 等价 / 状态 / 场景策略生成用例，规模按 PRD 复杂度上限控制…',
    done: false,
    collapsed: false,
  }
  events.value.push(th)
  scrollToBottom()

  setTimeout(() => {
    th.done = true
    th.collapsed = true
    events.value.push({
      type: 'agent',
      text: '<p>将基于「支付」模块 PRD 生成用例，预计 40 条（中等复杂度上限 45）。生成后进入 <b>awaiting_case_confirm</b>，需你在 72h 内确认入库。请确认：</p>',
    })
    events.value.push({
      type: 'confirm',
      card: {
        kind: 'testcase',
        case_source_text: file ? `附件：${file.name}` : '',
      },
      isAcked: false,
      summary: file ? file.name : '粘贴文本输入',
      open: true,
    })
    isGenerating.value = false
    scrollToBottom()
  }, 1000)
}

function handleConfirmAck(item: StreamItem, confirmed: boolean) {
  item.isAcked = true
  item.ackResult = confirmed
  item.open = false

  if (item.card?.kind === 'benchmark') {
    item.summary = `${item.card.profile_ids?.length || 2} 个协议档 × smoke-20`
  } else if (item.card?.kind === 'rag') {
    item.summary = 'default · qa-v1 v2'
  }

  if (!confirmed) {
    events.value.push({
      type: 'agent',
      text: '<p>已取消，未创建任务。需要调整目标可以继续说。</p>',
    })
    scrollToBottom()
    return
  }

  // 模拟入队
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
  const timer = setInterval(() => {
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
      clearInterval(timer)
      setTimeout(() => {
        activeTask.value = null
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
      }, 600)
    }
  }, 1000)
}

function handleInterpretReport(reportId: string) {
  events.value.push({
    type: 'user',
    text: `解读报告 #${reportId}`,
  })
  isGenerating.value = true
  scrollToBottom(true)

  const th: StreamItem = {
    type: 'thought',
    text: `读取报告 ${reportId} 的指标摘要与失败样本，进行关键退化原因归因…`,
    done: false,
    collapsed: false,
  }
  events.value.push(th)

  setTimeout(() => {
    th.done = true
    th.collapsed = true
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
    isGenerating.value = false
    scrollToBottom()
  }, 1000)
}

function handleFailDemo() {
  events.value.push({
    type: 'user',
    text: '对比一下 gpt-test 和 claude-x 在 smoke-20 上的表现',
  })
  isGenerating.value = true
  const th: StreamItem = {
    type: 'thought',
    text: '目标明确：Benchmark 对比。准备创建任务并检查协议档连通性…',
    done: false,
  }
  events.value.push(th)
  scrollToBottom(true)

  setTimeout(() => {
    th.done = true
    th.collapsed = true
    const toolItem: StreamItem = {
      type: 'tool',
      tool: 'task.create',
      args: { kind: 'benchmark', profile_ids: ['p-gpt', 'p-claude'], dataset_id: 'ds-smoke' },
      status: 'pending',
    }
    events.value.push(toolItem)

    setTimeout(() => {
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
      isGenerating.value = false
      scrollToBottom()
    }, 800)
  }, 800)
}

function handleWsToggle() {
  isWsOnline.value = !isWsOnline.value
  if (!isWsOnline.value) {
    message.info('正在模拟断线状态…')
  } else {
    message.success('已恢复连接，已按 last_event_id 自动同步')
  }
}

function handleCancelActiveTask(taskId: string) {
  dialog.warning({
    title: '取消任务？',
    content: '将在当前样本推理完成后停止，已完成的评测得分与报文将完整保留。',
    positiveText: '确认取消',
    negativeText: '放弃',
    onPositiveClick: async () => {
      try {
        await api.tasks.cancel(taskId)
      } catch {}
      activeTask.value = null
      message.success('评测任务已取消（cancelled）')
    },
  })
}

async function loadSessions() {
  try {
    const list = await api.sessions.list()
    if (list && list.length > 0) {
      sessions.value = list
      if (!currentSessionId.value) currentSessionId.value = list[0].id
    }
  } catch {}
}

function selectSession(sid: string) {
  currentSessionId.value = sid
  events.value = []
  initWebSocket(sid)
}

async function handleCreateSession() {
  try {
    const newSession = await api.sessions.create('新会话')
    sessions.value.unshift(newSession)
    selectSession(newSession.id)
  } catch {
    const localS = { id: `s-${Date.now()}`, title: '新会话', time: '刚刚', created_at: new Date().toISOString() }
    sessions.value.unshift(localS)
    selectSession(localS.id)
  }
}

function initWebSocket(sessionId: string) {
  if (agentWs) {
    agentWs.close()
    agentWs = null
  }

  agentWs = new AgentWebSocket(sessionId)
  agentWs.onStatus((connected) => {
    isWsOnline.value = connected
  })
  agentWs.onEvent((ev: WsServerEvent) => {
    handleWsEvent(ev)
  })
  agentWs.connect()
}

function handleWsEvent(ev: WsServerEvent) {
  switch (ev.event) {
    case 'thought': {
      let last = events.value[events.value.length - 1]
      if (!last || last.type !== 'thought' || last.done) {
        events.value.push({ type: 'thought', text: ev.message || '', done: false, collapsed: false })
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
        open: false,
      })
      scrollToBottom()
      break
    }
    case 'tool_result': {
      const target = [...events.value].reverse().find(x => x.type === 'tool' && x.tool === ev.tool)
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
        summary: '',
        open: true,
      })
      scrollToBottom()
      break
    }
    case 'progress': {
      if (activeTask.value) {
        activeTask.value.progress = ev.progress
      }
      break
    }
    case 'report': {
      activeTask.value = null
      events.value.push({
        type: 'report',
        reportId: ev.report_id,
        kpis: defaultKpis,
      })
      scrollToBottom()
      break
    }
    case 'error': {
      events.value.push({
        type: 'error',
        code: ev.code,
        message: ev.message || '执行遇到错误',
      })
      isGenerating.value = false
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
  if (currentSessionId.value) {
    initWebSocket(currentSessionId.value)
  }
})

onBeforeUnmount(() => {
  if (agentWs) {
    agentWs.close()
  }
})
</script>

<style scoped>
.agent-layout {
  height: calc(100vh - var(--topbar-h) - 20px);
}
</style>
