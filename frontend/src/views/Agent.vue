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
            <span class="session-title-text">{{ s.title || '新会话' }}</span>
            <button
              class="session-del"
              title="删除会话"
              @click.stop="handleDeleteSession(s.id)"
            >
              <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round">
                <path d="M3 6h18M8 6V4h8v2M19 6l-1 14H6L5 6" />
              </svg>
            </button>
            <!-- D5 会话状态点多态：running / succeeded / failed -->
            <i v-if="sessionDotClass(s)" class="nav-dot" :class="sessionDotClass(s)"></i>
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
        <n-dropdown
          trigger="click"
          :options="agentProfileDropdownOptions"
          @select="handleSelectAgentModel"
        >
          <button class="chat-head-model-btn" title="点击切换 Agent 驱动模型（来自协议档接入池）">
            <span class="head-model-dot"></span>
            <span class="mono">Agent · {{ agentModelName || '选择模型' }}</span>
            <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
              <path d="m6 9 6 6 6-6"/>
            </svg>
          </button>
        </n-dropdown>
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
            <div v-if="item.type === 'user'" class="msg-user" :class="{ 'no-anim': item.noAnim }">
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

            <!-- 2.2 思考卡：推理模型思考链流式展示，完成后自动折叠，可展开/收起 -->
            <div v-else-if="item.type === 'thought'" class="think-card" :class="{ done: item.done }">
              <button class="think-head" type="button" @click="item.collapsed = !item.collapsed">
                <span class="think-dot" v-if="!item.done"></span>
                <span class="think-label">{{ item.done ? '已深度思考' : '深度思考中' }}</span>
                <span class="think-meta">{{ (item.text || '').length }} 字</span>
                <svg class="think-caret" :class="{ open: !item.collapsed }" viewBox="0 0 12 12" width="12" height="12">
                  <path d="M2 4l4 4 4-4" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" />
                </svg>
              </button>
              <div v-show="!item.collapsed" class="think-body">
                <span>{{ item.text }}</span><span v-if="!item.done" class="think-cursor">▍</span>
              </div>
            </div>

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
                    {{ activeTask ? '当前会话已有任务进行中（槽位含压测子任务），完成后才能再开新长任务' : '未确认不入队；确认前可修改字段' }}
                  </span>
                  <span class="spacer"></span>
                  <button class="btn btn-secondary" @click="handleConfirmAck(item, false)">取消</button>
                  <button class="btn btn-sign" :disabled="!!activeTask" @click="handleConfirmAck(item, true)">确认并开始</button>
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

            <!-- 2.7 Agent 文本回复（streaming 时为流式气泡，带打字光标） -->
            <div
              v-else-if="item.type === 'agent'"
              class="msg-agent"
              :class="{ 'no-anim': item.noAnim, 'streaming-bubble': item.streaming }"
              v-html="item.text"
            ></div>
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

        <div class="composer-card">
          <!-- 上半区：全宽自适应多行文本域 -->
          <textarea
            ref="textareaRef"
            v-model="inputText"
            class="composer-textarea"
            rows="1"
            placeholder="输入任何评测问题或需求，Shift + Enter 换行，Enter 发送"
            @keydown="handleKeydown"
            @input="adjustTextareaHeight"
          ></textarea>

          <!-- 下半区：操作底栏（附件 + 模型选择 + 发送按钮） -->
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

              <!-- 接入模型选择下拉胶囊 -->
              <n-dropdown
                trigger="click"
                :options="agentProfileDropdownOptions"
                @select="handleSelectAgentModel"
              >
                <button class="composer-model-dropdown-btn" title="点击切换当前 Agent 驱动模型（来自协议档接入池）">
                  <span class="model-name">{{ agentModelName || '选择模型' }}</span>
                  <svg class="chevron-icon" width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round">
                    <path d="m18 15-6-6-6 6"/>
                  </svg>
                </button>
              </n-dropdown>
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
import { ref, computed, onMounted, onBeforeUnmount, nextTick, watch, h } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useMessage, useDialog, NDropdown } from 'naive-ui'
import { api } from '../api/http'
import { AgentWebSocket } from '../api/ws'
import type { Task, TaskSpec, WsServerEvent, Profile, Dataset, KnowledgeBase, GoldQA } from '../api/types'
import { getDefaultRunConfig, getDefaultStressConfig } from '../schemas/confirmCard'
import { useModeStore } from '../stores/mode'
import KindTag from '../components/common/KindTag.vue'

const message = useMessage()
const dialog = useDialog()
const route = useRoute()
const router = useRouter()
const modeStore = useModeStore()
const chatScrollRef = ref<HTMLDivElement | null>(null)
const textareaRef = ref<HTMLTextAreaElement | null>(null)
const fileInputRef = ref<HTMLInputElement | null>(null)

const isListCollapsed = ref(false)
const isRailOpen = ref(false)
const isWsOnline = ref(true)
const isGenerating = ref(false)
const showJumpBottom = ref(false)
const agentModelName = ref('')
const currentAgentProfileId = ref<string>('')
const allProfiles = ref<Profile[]>([])

/** 模型选择下拉菜单项（对齐 /admin/profiles 接入池） */
const agentProfileDropdownOptions = computed(() => {
  if (!allProfiles.value.length) {
    return [
      { label: '暂无接入模型协议档', key: '__none__', disabled: true },
      { type: 'divider', key: 'd1' },
      { label: '⚙ 前往接入协议档 ↗', key: '__goto_profiles__' },
    ]
  }
  const activeId = currentAgentProfileId.value || allProfiles.value[0]?.id
  const list = allProfiles.value.map((p) => {
    const isCurrent = p.id === activeId
    return {
      label: () =>
        h('div', {
          style: {
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            gap: '16px',
            minWidth: '260px',
            padding: '3px 0',
            lineHeight: '1.4',
          }
        }, [
          h('div', { style: { display: 'flex', flexDirection: 'column', gap: '2px', flex: '1', minWidth: '0' } }, [
            h('span', {
              style: {
                fontWeight: isCurrent ? '700' : '500',
                fontSize: '13px',
                color: isCurrent ? 'var(--accent-ai)' : 'inherit',
                overflow: 'hidden',
                textOverflow: 'ellipsis',
                whiteSpace: 'nowrap',
              }
            }, p.name),
            h('span', {
              style: {
                fontSize: '11px',
                opacity: '0.65',
                fontFamily: 'var(--font-mono)',
                overflow: 'hidden',
                textOverflow: 'ellipsis',
                whiteSpace: 'nowrap',
              }
            }, `${p.model || p.protocol} · ${p.protocol}`),
          ]),
          isCurrent
            ? h('span', {
                style: {
                  color: 'var(--accent-ai)',
                  fontSize: '11px',
                  fontWeight: '700',
                  background: 'var(--t-agent)',
                  padding: '2px 8px',
                  borderRadius: '6px',
                  flexShrink: '0',
                }
              }, '当前驱动')
            : null,
        ]),
      key: p.id,
    }
  })
  return [
    ...list,
    { type: 'divider', key: 'd1' },
    { label: '⚙ 管理模型接入协议档 ↗', key: '__goto_profiles__' },
  ]
})

const sessions = ref<any[]>([])
const currentSessionId = ref<string>('')
const currentSession = computed(() => sessions.value.find(s => s.id === currentSessionId.value) || sessions.value[0] || null)

const inputText = ref('')
const stagedFiles = ref<any[]>([])
const activeTask = ref<Task | null>(null)

// 资产列表种子数据供 mock 演示；实时模式下由服务端短工具（model.list / dataset.list / kb.list）动态回填
const availableProfiles = ref<Profile[]>([
  { id: 'p-gpt', name: 'gpt-test', model: 'gpt-4o', protocol: 'openai_chat', base_url: 'https://api.openai.com/v1', usages: ['target'], created_at: new Date().toISOString() },
  { id: 'p-claude', name: 'claude-x', model: 'claude-3-5-sonnet-20241022', protocol: 'anthropic_messages', base_url: 'https://api.anthropic.com', usages: ['target'], created_at: new Date().toISOString() },
  // F10 外部 RAG 服务档（external_chat 库确认卡单选选项）
  { id: 'p-ragsvc', name: 'rag-客服外挂', model: 'rag-chat-v2', protocol: 'openai_chat', base_url: 'https://rag.internal.example.com/v1', usages: ['target'], created_at: new Date().toISOString() },
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

// 智能体能力卡与顶栏共用同一模式状态，避免出现页面内外不一致的评测上下文。
const isRagMode = computed(() => modeStore.mode === 'rag')

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
  // F4 历史回放标记：跳过入场动画（对齐原型 no-anim）
  noAnim?: boolean
  // S3 思考卡流式打字：fullText 为应显示全文，streaming 表示打字机进行中
  fullText?: string
  streaming?: boolean
  // F8 确认卡内联校验错误（字段名 → 红字文案）
  fieldErrors?: Record<string, string>
}

const events = ref<StreamItem[]>([])
let agentWs: AgentWebSocket | null = null
let lastConfirmKind = 'benchmark'

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

/** D5 会话列表状态点多态：按 status / active_task 映射 nav-dot 样式。 */
function sessionDotClass(s: any): string | null {
  if (s.active_task || s.status === 'running' || s.status === 'queued') return 'running'
  if (s.status === 'succeeded') return 'succeeded'
  if (s.status === 'failed') return 'failed'
  return null
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
  dockClosingNote.value = note
  trackTimeout(() => { dockClosingNote.value = '' }, 2600)
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

/** 自适应调整多行输入框高度（最小 40px，最大 200px 限制，超高自动滚动） */
function adjustTextareaHeight() {
  if (!textareaRef.value) return
  textareaRef.value.style.height = 'auto'
  const scrollH = textareaRef.value.scrollHeight
  const targetH = Math.min(200, Math.max(40, scrollH))
  textareaRef.value.style.height = `${targetH}px`
  textareaRef.value.style.overflowY = scrollH > 200 ? 'auto' : 'hidden'
}

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

/** 键盘事件监听：Enter 发送，Shift + Enter 换行并自适应扩展高度 */
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

function handleEnterPress() {
  handleSendClick()
}

function handleSendClick() {
  if (isGenerating.value) {
    // F19 暂停生成：清理全部生成流定时器真正停止模拟流（保留 WS 连接与页面级心跳），
    // 未完成的思考卡直接收尾；恢复时发送新消息即可继续。
    flowTimers.forEach(id => clearTracked(id))
    events.value.forEach(ev => { if (ev.type === 'thought' && !ev.done) finishThought(ev) })
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

/** 快捷芯片/能力卡点击仅填入输入框并聚焦，由用户确认后再发送（对齐原型行为）。 */
function sendPredefined(prompt: string) {
  inputText.value = prompt
  nextTick(() => {
    adjustTextareaHeight()
    textareaRef.value?.focus()
  })
}

function handleUserSend(text: string, files: any[] = []) {
  events.value.push({
    type: 'user',
    text,
    files,
  })
  isGenerating.value = true
  scrollToBottom(true)

  // 首发消息后以首条消息截断更新会话标题
  const session = sessions.value.find(s => s.id === currentSessionId.value)
  if (session && session.title === '新会话' && text) {
    session.title = text.slice(0, 18)
  }

  if (agentWs?.isConnected) {
    // 打字占位气泡：服务端 LLM 意图识别期间给用户即时反馈，收到任意事件后移除
    events.value.push({ type: 'typing' })
    scrollToBottom()
    // 契约：attachments = [{ file_id }]，仅回传上传成功的附件，失败附件按提示忽略
    agentWs.sendUserMessage(text, files.filter(f => f.id).map(f => ({ file_id: f.id })))
  } else if (agentWs) {
    // 实时模式但连接未就绪：给出错误反馈并走本地模拟，避免消息静默丢失
    events.value.push({ type: 'error', code: 'NETWORK', message: '连接未就绪，消息将在本地模拟流程中演示' })
    simulateAgentFlow(text, files)
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
    isGenerating.value = false
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
    isGenerating.value = false
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
    isGenerating.value = false
    scrollToBottom()
  }, 1000, true)
}

function handleConfirmAck(item: StreamItem, confirmed: boolean) {
  // F8 确认前卡内校验：不通过则留卡内显示红字，不盖章、不 Toast
  if (confirmed && !validateConfirmCard(item)) return

  item.isAcked = true
  item.ackResult = confirmed
  item.open = false

  const useLive = !!(agentWs && agentWs.isConnected)

  if (item.card?.kind === 'benchmark') {
    item.summary = `${item.card.profile_ids?.length || 0} 个协议档 · 待入队`
  } else if (item.card?.kind === 'rag') {
    item.summary = 'RAG 评测 · 待入队'
  } else if (item.card?.kind === 'testcase') {
    item.summary = '用例生成 · 待入队'
  }

  // 真实链路：把确认回执（含整卡 patch）发回服务端，由服务端校验并入队
  if (useLive) {
    agentWs!.sendConfirmAck(confirmed, item.card)
    if (!confirmed) {
      events.value.push({ type: 'agent', text: '<p>已取消，未创建任务。需要调整目标可以继续说。</p>' })
      scrollToBottom()
    }
    return
  }

  // Mock 模式（无 WS 连接）：本地演示入队与进度
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
  events.value.push({
    type: 'user',
    text: `解读报告 #${reportId}`,
  })
  isGenerating.value = true
  scrollToBottom(true)

  // 实时模式交由服务端智能体解读，结果经 WS 事件回流。
  if (agentWs?.isConnected) {
    agentWs.sendUserMessage(`解读报告 #${reportId}`)
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
    isGenerating.value = false
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
  isGenerating.value = true
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
      isGenerating.value = false
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
      try {
        // 契约：Agent 页取消走 WS 上行 cancel_task（上行仅三类消息）；连接不可用时回退 REST
        if (agentWs?.isConnected) agentWs.sendCancelTask(taskId)
        else await api.tasks.cancel(taskId)
      } catch {}
      // 对齐原型 hideDock：先展示「已提交取消请求」note，2.6s 后隐藏进度坞
      finishDock('已提交取消请求')
      message.success(isStress ? '已提交停止发压请求' : '评测任务已取消（cancelled）')
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
    } else if (profiles && profiles.length > 0) {
      agentModelName.value = profiles[0].model || profiles[0].name
      currentAgentProfileId.value = profiles[0].id
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

/** F4 会话历史回放：拉取历史 user/assistant 消息渲染进事件流（no-anim 跳过入场动画），
 *  并回传最大 event_id 供 WS 断点续传对齐 lastEventId；失败静默降级按全新会话处理。 */
async function loadSessionHistory(sid: string): Promise<number> {
  try {
    const history = await api.sessions.getMessages(sid)
    const replay: StreamItem[] = []
    for (const m of history.messages || []) {
      if (m.role === 'user') {
        replay.push({ type: 'user', text: m.content || '', files: m.attachments || [], noAnim: true })
      } else if (m.role === 'assistant') {
        replay.push({ type: 'agent', text: `<p>${escapeHtml(m.content || '')}</p>`, noAnim: true })
      }
    }
    if (replay.length) {
      events.value = replay
      scrollToBottom(true)
    }
    // 对齐 lastEventId：取历史事件流与消息中的最大 event_id
    const eventIds = [
      ...(history.events || []).map((e: any) => Number(e?.event_id) || 0),
      ...(history.messages || []).map((m: any) => Number(m?.event_id) || 0),
    ]
    return eventIds.length ? Math.max(0, ...eventIds) : 0
  } catch {
    return 0
  }
}

async function selectSession(sid: string) {
  currentSessionId.value = sid
  events.value = []
  activeTask.value = null
  dockClosingNote.value = ''
  isGenerating.value = false
  // F17 会话含进行中任务时默认展开调度侧轨
  const sess = sessions.value.find(s => s.id === sid)
  isRailOpen.value = !!sess?.active_task
  // F4 先回放历史消息并对齐 lastEventId，再建立 WS（带 last_event_id 断点续传）
  const lastEventId = await loadSessionHistory(sid)
  initWebSocket(sid, lastEventId)
}

async function handleCreateSession() {
  try {
    const newSession = await api.sessions.create('新会话')
    sessions.value.unshift(newSession)
    selectSession(newSession.id)
  } catch {
    const localS = { id: `s-${Date.now()}`, title: '新会话', created_at: new Date().toISOString() }
    sessions.value.unshift(localS)
    selectSession(localS.id)
  }
}

function handleDeleteSession(_sid: string) {
  // API.md §3.4/§9：V1 不提供「删除会话」接口；会话为审计留存资产，
  // 此处按设计规范以提示替代假删除，不向服务端发送请求。
  message.info('当前版本暂不支持删除会话，对话记录将长期保留以便回溯')
}

function initWebSocket(sessionId: string, lastEventId = 0) {
  if (agentWs) {
    agentWs.close()
    agentWs = null
  }

  agentWs = new AgentWebSocket(sessionId)
  // F4 历史回放对齐断点：连接时带 last_event_id，服务端据此补发遗漏事件
  if (lastEventId > 0) agentWs.lastEventId = lastEventId
  agentWs.onStatus((connected) => {
    isWsOnline.value = connected
  })
  agentWs.onEvent((ev: WsServerEvent) => {
    handleWsEvent(ev)
  })
  agentWs.connect()
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

/* ─── 打字机渲染：终帧权威全文逐字补齐 ───
   无论是真流式增量、网关不支持 SSE 的单块兜底、还是降级规则版的整段回复，
   终帧到达后都从已显示长度逐字推进到全文，保证任何链路下用户都看到
   「一个字一个字弹出」的效果。定时器登记进 flowTimers，「暂停生成」可中断。 */
function typewriteTo(item: StreamItem, fullText: string) {
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
  if (ev.event !== 'pong') dismissTyping()
  const p = ev.payload || {}
  switch (ev.event) {
    case 'thought': {
      // 思考链增量帧（瞬态）：追加到可展开/收起的思考卡，无则新建
      if (p.stream === 'think') {
        const delta = String(p.text || '')
        if (delta) {
          const target = [...events.value].reverse().find(e => e.type === 'thought' && !e.done)
          if (target) target.text = (target.text || '') + delta
          else events.value.push({ type: 'thought', text: delta, done: false, collapsed: false })
          scrollToBottom()
        }
        break
      }
      // 流式增量帧（瞬态，服务端不落库）：追加到当前流式气泡，无则新建
      if (p.stream === 'chunk') {
        const delta = String(p.text || '')
        if (delta) {
          let target = [...events.value].reverse().find(e => e.type === 'agent' && e.streaming)
          if (!target) {
            target = { type: 'agent', raw: '', text: '', streaming: true }
            events.value.push(target)
          }
          target.raw = (target.raw || '') + delta
          target.text = renderBubbleHtml(target.raw)
          scrollToBottom()
        }
        break
      }
      // 完整回复（终帧或非流式）：先收尾思考卡（完成并折叠），再打字机渲染权威全文
      const text = String(p.text || '').trim()
      const think = [...events.value].reverse().find(e => e.type === 'thought' && !e.done)
      if (think) {
        think.done = true
        think.collapsed = true
      }
      if (text) {
        const streaming = [...events.value].reverse().find(e => e.type === 'agent' && e.streaming)
        if (streaming) {
          // 真流式已有前缀：从已显示长度打字机续播到权威全文
          typewriteTo(streaming, text)
        } else {
          // 单块兜底 / 降级规则版：新建气泡打字机渲染全文
          const item: StreamItem = { type: 'agent', raw: '', text: '', streaming: true }
          events.value.push(item)
          typewriteTo(item, text)
        }
      } else {
        const orphan = [...events.value].reverse().find(e => e.type === 'agent' && e.streaming)
        if (orphan) orphan.streaming = false
      }
      if (text) scrollToBottom()
      // 纯对话轮次（如闲聊）以 thought 收尾：结束「生成中」状态；
      // 若后续仍有 tool_call / confirm，UI 会随事件自然继续更新。
      isGenerating.value = false
      break
    }
    case 'tool_call': {
      finishLiveThought()
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
      const target = [...events.value].reverse().find(x => x.type === 'tool' && x.tool === p.name)
      if (target) {
        target.result = p.ok ? p.data : p.error
        target.status = p.ok ? 'ok' : 'fail'
      }
      // 把短工具发现结果回填到确认卡可选项
      if (p.ok) {
        if (p.name === 'model.list') availableProfiles.value = p.data?.items || []
        if (p.name === 'dataset.list') availableDatasets.value = p.data?.items || []
        if (p.name === 'kb.list') availableKbs.value = p.data?.items || []
      }
      scrollToBottom()
      break
    }
    case 'confirm': {
      lastConfirmKind = p.kind || 'benchmark'
      finishLiveThought()
      isGenerating.value = false
      events.value.push({
        type: 'confirm',
        // 契约：确认卡 TaskSpec 在 payload；规范化补齐 run / stress 默认值，折叠区绑定路径始终有效
        card: normalizeConfirmCard(p),
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
      isGenerating.value = false
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
      events.value.push({
        type: 'error',
        code: p.code,
        message: p.message || '执行遇到错误',
      })
      // 内联错误条之外同步弹出 Toast，避免用户错过失败反馈
      message.error(p.message || '执行遇到错误')
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
      // 实时模式需等待 WS 建立连接后再发送解读请求；5s 超时兜底走本地演示流程。
      // 兜底定时器与 watch 均登记在册，组件卸载时统一清理。
      const fallbackTimer = trackTimeout(() => {
        interpretStopWatch?.()
        interpretStopWatch = null
        handleInterpretReport(interpretId)
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
  if (agentWs) {
    agentWs.close()
  }
})
</script>

<style scoped>
.agent-layout {
  height: calc(100vh - var(--topbar-h) - 20px);
}

/* 顶部模型切换下拉按钮 */
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
  transition: all 0.15s ease;
  user-select: none;
}
.chat-head-model-btn:hover {
  border-color: var(--accent-ai);
  color: var(--text-primary);
  background: var(--bg-main);
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

/* 多行文本域自适应高度（最小 38px，最大 200px 限制） */
.composer-textarea {
  width: 100%;
  border: 0;
  outline: none;
  resize: none;
  font-family: var(--font-chat, inherit);
  font-size: 14.5px;
  line-height: 1.55;
  min-height: 38px;
  max-height: 200px;
  padding: 4px 6px;
  background: transparent;
  color: var(--text-primary);
  box-sizing: border-box;
  overflow-y: hidden;
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
