<template>
  <div class="dispatch-page" data-od-id="dispatch-page">
    <!-- ═══ 1. 调度大盘 KPI 趋势带（数字滚动 + 迷你趋势线 + 发光描边） ═══ -->
    <div class="kpi-grid mb16" data-od-id="dispatch-kpis" style="--glow-c: var(--c-agent)">
      <div class="kpi kpi-glow">
        <div class="kpi-num num">{{ onlineDisplay }}<span class="unit">/ {{ totalWorkers }}</span></div>
        <div class="kpi-label">在线 Worker 节点</div>
      </div>
      <div class="kpi kpi-trend kpi-glow">
        <div class="kpi-num num">{{ queueDisplay }}</div>
        <div class="kpi-label">排队队列深度</div>
        <svg class="spark" viewBox="0 0 76 24" preserveAspectRatio="none"><polyline :points="sparkPoints(histQueue)" /></svg>
      </div>
      <div class="kpi kpi-trend kpi-glow">
        <div class="kpi-num num">{{ runningDisplay }}</div>
        <div class="kpi-label">运行中任务</div>
        <svg class="spark" viewBox="0 0 76 24" preserveAspectRatio="none"><polyline :points="sparkPoints(histRunning)" /></svg>
      </div>
      <div class="kpi kpi-trend kpi-glow">
        <div class="kpi-num num">{{ costDisplay }}<span class="unit">ms</span></div>
        <div class="kpi-label">平均分发调度延迟</div>
        <svg class="spark" viewBox="0 0 76 24" preserveAspectRatio="none"><polyline :points="sparkPoints(histCost)" /></svg>
      </div>
      <div class="kpi kpi-trend kpi-glow">
        <div class="kpi-num num">{{ assignedDisplay }}</div>
        <div class="kpi-label">今日已分配任务</div>
        <svg class="spark" viewBox="0 0 76 24" preserveAspectRatio="none"><polyline :points="sparkPoints(histAssigned)" /></svg>
      </div>
    </div>

    <!-- ═══ 0. 模式分段选择器（Dify 拖拽编排工作流 vs 实时调度星图监控） ═══ -->
    <div class="dispatch-view-tabs mb16">
      <div class="tab-pill-group">
        <button
          class="tab-pill-btn"
          :class="{ active: activeTab === 'designer' }"
          @click="activeTab = 'designer'"
        >
          <span class="tab-icon">🌐</span>
          <span>Dify 拖拽编排工作流</span>
          <span class="tab-badge">推荐</span>
        </button>
        <button
          class="tab-pill-btn"
          :class="{ active: activeTab === 'monitor' }"
          @click="activeTab = 'monitor'"
        >
          <span class="tab-icon">🛰</span>
          <span>实时调度星图与监控</span>
        </button>
      </div>

      <div class="row" style="gap: 8px; align-items: center">
        <span class="tag-soft" :style="modeTagStyle">{{ modeStore.mode === 'rag' ? 'RAG 模式' : '大模型模式' }}</span>
        <button class="btn btn-secondary btn-sm" style="font-size: 11px" @click="handleManualEnqueue">+ 快速插入任务</button>
      </div>
    </div>

    <!-- ═══ 1. 可视编排设计器（Dify 风格 DAG 拖拽工作流） ═══ -->
    <WorkflowDesigner
      v-show="activeTab === 'designer'"
      class="mb16"
      @task-dispatched="handleTaskDispatched"
    />

    <!-- ═══ 2. 沉浸式大星图与悬浮控制坞 (Immersive Star Constellation & Floating Glass Docks) ═══ -->
    <div
      v-show="activeTab === 'monitor'"
      class="panel glow immersive-monitor-panel mb16"
      data-od-id="dispatch-canvas"
      style="--glow-c: var(--c-agent)"
    >
      <!-- 顶栏快速操作与视口控制条 -->
      <div class="row-between mb12" style="flex-wrap: wrap; gap: 8px">
        <div class="panel-title" style="margin: 0">
          调度编排星图
          <span class="small tertiary mono" style="font-weight: 400">内核 → 技能 Agent → Worker · 实时拓扑</span>
        </div>
        <div class="row" style="gap: 6px; align-items: center">
          <span class="tag-soft" :style="modeTagStyle">{{ modeStore.mode === 'rag' ? 'RAG 模式' : '大模型模式' }}</span>
          <button class="btn btn-secondary btn-sm" style="font-size: 11px" @click="handleManualEnqueue">+ 插入任务</button>
          <span class="zoom-ctrl">
            <button class="zoom-btn" title="缩小" @click="zoomBy(0.85)">−</button>
            <button class="zoom-btn mono" title="重置视图（双击画布同效）" @click="resetView">{{ Math.round(view.k * 100) }}%</button>
            <button class="zoom-btn" title="放大" @click="zoomBy(1.18)">+</button>
          </span>
          <button class="btn btn-secondary btn-sm" style="font-size: 11px" @click="resetView">⊡ 居中</button>
        </div>
      </div>

      <!-- 全画幅主视口容器 -->
      <div ref="wrapRef" class="immersive-topo-wrap">
        <!-- SVG 大星图 -->
        <svg
          ref="svgRef"
          class="topo-svg"
          viewBox="0 0 1200 760"
          preserveAspectRatio="xMidYMid meet"
          @pointerdown="onPointerDown"
          @pointermove="onPointerMove"
          @pointerup="onPointerUp"
          @pointerleave="onPointerUp"
          @dblclick="resetView"
          @click="onBgClick"
        >
          <defs>
            <pattern id="topo-grid" width="28" height="28" patternUnits="userSpaceOnUse">
              <path d="M 28 0 L 0 0 0 28" class="grid-line" />
            </pattern>
            <radialGradient id="core-glow">
              <stop offset="0%" stop-color="var(--accent-ai)" stop-opacity="0.25" />
              <stop offset="100%" stop-color="var(--accent-ai)" stop-opacity="0" />
            </radialGradient>
            <linearGradient id="sweep-grad" x1="0" y1="0" x2="1" y2="0">
              <stop offset="0%" stop-color="var(--accent-ai)" stop-opacity="0.35" />
              <stop offset="100%" stop-color="var(--accent-ai)" stop-opacity="0" />
            </linearGradient>
          </defs>

          <!-- 可拖拽背景 -->
          <rect x="-2000" y="-2000" width="5200" height="5200" fill="url(#topo-grid)" class="topo-bg" />

          <g :transform="`translate(${view.x} ${view.y}) scale(${view.k})`">
            <!-- 业务扇区底色楔块 -->
            <path
              v-for="s in topo.sectors"
              :key="'wedge-' + s.kind"
              class="sector-wedge"
              :class="{ dim: focusedSkill && focusedSkill !== s.kind }"
              :d="s.wedge"
              :fill="s.color"
            />

            <!-- 轨道参考线 -->
            <circle :cx="CX" :cy="CY" :r="R_SKILL" class="orbit-guide" />
            <circle :cx="CX" :cy="CY" :r="R_WORKER" class="orbit-guide outer" />

            <!-- 常驻链路：内核 → 技能 -->
            <path
              v-for="s in topo.skills"
              :key="'core-' + s.kind"
              class="wire-core"
              :class="{ dim: focusedSkill && focusedSkill !== s.kind }"
              :d="`M ${CX} ${CY} L ${s.x} ${s.y}`"
            />

            <!-- 归属链路：技能 → Worker -->
            <path
              v-for="pw in topo.workers"
              :key="'mem-' + pw.w.id"
              class="wire-member"
              :class="{ dim: focusedSkill && focusedSkill !== pw.skillKind }"
              :d="`M ${pw.sx} ${pw.sy} L ${pw.x} ${pw.y}`"
            />

            <!-- 执行链路：高亮流动 + 粒子 -->
            <template v-for="w in topo.liveWires" :key="w.key">
              <path class="wire-live" :class="{ dim: focusedSkill && focusedSkill !== w.skillKind }" :d="w.d" />
              <circle class="particle" r="3">
                <animateMotion :path="w.d" dur="1.9s" repeatCount="indefinite" />
              </circle>
              <circle class="particle" r="2" opacity="0.55">
                <animateMotion :path="w.d" dur="1.9s" begin="-0.95s" repeatCount="indefinite" />
              </circle>
            </template>

            <!-- 任务完成涟漪 -->
            <circle v-for="r in ripples" :key="r.id" class="ripple-c" :cx="r.x" :cy="r.y" r="10" />

            <!-- 任务工单芯片 -->
            <g
              v-for="p in topo.tasks"
              :key="p.t.id"
              class="task-chip"
              :class="[p.t.status, { flash: flashTaskId === p.t.id || flashTaskId === p.t.shortId, dim: focusedSkill && focusedSkill !== p.t.kind, pinned: pinnedTask?.id === p.t.id }]"
              :style="{ transform: `translate(${p.x}px, ${p.y}px)` }"
              @mouseenter="showTaskTip($event, p.t)"
              @mouseleave="hideTip"
              @click="onNodeClick(() => pinTask(p.t))"
            >
              <rect x="-76" y="-19" width="152" height="38" rx="9" class="tc-box" />
              <rect x="-76" y="-19" width="3.5" height="38" class="tc-bar" :fill="kindColor(p.t.kind)" />
              <circle cx="-61" cy="-7" r="3" class="tc-dot" :class="p.t.status" />
              <text x="-52" y="-3.5" class="tc-id">{{ p.t.shortId }}</text>
              <text x="68" y="-3.5" class="tc-status" text-anchor="end">{{ statusLabel(p.t.status) }}</text>
              <text x="-66" y="10" class="tc-label">{{ trunc(p.t.label, 16) }}</text>
              <g v-if="p.t.status === 'running'">
                <rect x="-66" y="13.5" width="132" height="3" rx="1.5" class="tc-progress-bg" />
                <rect x="-66" y="13.5" :width="132 * (p.t.progress ?? 0) / 100" height="3" rx="1.5" class="tc-progress" />
              </g>
            </g>

            <!-- 技能 Agent 内环节点 -->
            <g
              v-for="s in topo.skills"
              :key="s.kind"
              class="skill-node"
              :class="{ on: s.runningCount > 0, dim: focusedSkill && focusedSkill !== s.kind }"
              :style="{ transform: `translate(${s.x}px, ${s.y}px)`, '--sk': s.color }"
              @mouseenter="showSkillTip($event, s)"
              @mouseleave="hideTip"
              @click="onNodeClick(() => toggleFocus(s.kind))"
            >
              <circle r="30" class="sn-halo" />
              <circle r="24" class="sn-core" />
              <text y="6" class="sn-ico" text-anchor="middle">{{ s.icon }}</text>
              <text y="45" class="sn-name" text-anchor="middle">{{ s.name }}</text>
              <text y="59" class="sn-count" text-anchor="middle">
                {{ s.activeCount > 0 ? `${s.runningCount} 运行 / ${s.activeCount} 活跃` : '待命' }}
              </text>
            </g>

            <!-- Worker 外环节点 -->
            <g
              v-for="pw in topo.workers"
              :key="pw.w.id"
              class="worker-node"
              :class="[pw.w.state, { dim: focusedSkill && focusedSkill !== pw.skillKind }]"
              :style="{ transform: `translate(${pw.x}px, ${pw.y}px)` }"
              @mouseenter="showWorkerTip($event, pw.w)"
              @mouseleave="hideTip"
              @click="onNodeClick(() => openWorkerModal(pw.w))"
            >
              <circle r="21" class="wn-ring-bg" />
              <circle
                r="21"
                class="wn-load"
                :class="{ hot: pw.w.load >= 80 }"
                :stroke-dasharray="`${(pw.w.load / 100) * 131.9} 131.9`"
                transform="rotate(-90)"
              />
              <circle r="15" class="wn-core" />
              <text y="3.5" class="wn-pct" text-anchor="middle">{{ pw.w.load }}</text>
              <text y="37" class="wn-id" text-anchor="middle">{{ pw.w.id }}</text>
              <circle cx="13" cy="-13" r="4" class="wn-dot" :class="pw.w.state" />
            </g>

            <!-- 中心调度内核 -->
            <g class="core" :style="{ transform: `translate(${CX}px, ${CY}px)` }">
              <circle r="88" fill="url(#core-glow)" />
              <g class="spin-a"><circle r="66" class="core-ring" /></g>
              <g class="spin-b"><circle r="53" class="core-ring2" /></g>
              <g v-if="isRunning" class="core-sweep">
                <path d="M 0 0 L 62 0 A 62 62 0 0 1 44 44 Z" fill="url(#sweep-grad)" />
              </g>
              <circle r="34" class="core-center" :class="{ halt: !isRunning }" />
              <text y="-1" class="core-ico" text-anchor="middle">🛰</text>
              <text y="14" class="core-status" text-anchor="middle">{{ isRunning ? 'LIVE' : 'HALT' }}</text>
              <text y="58" class="core-name" text-anchor="middle">调度内核</text>
            </g>
          </g>
        </svg>

        <!-- ═══ 左侧悬浮控制坞 (可收折) ═══ -->
        <div class="floating-dock dock-left" :class="{ collapsed: isLeftDockCollapsed }">
          <div class="dock-header">
            <div class="dock-header-title">
              <span class="dock-ico">🛰</span>
              <span v-show="!isLeftDockCollapsed" class="dock-title-text font-bold">调度内核与算力</span>
            </div>
            <button class="dock-toggle-btn" :title="isLeftDockCollapsed ? '展开左侧面板' : '收折左侧面板'" @click="isLeftDockCollapsed = !isLeftDockCollapsed">
              {{ isLeftDockCollapsed ? '⇥' : '⇤' }}
            </button>
          </div>

          <div v-show="!isLeftDockCollapsed" class="dock-scroll-content">
            <!-- 调度内核状态与指标 -->
            <div class="dock-card mb10">
              <div class="dock-card-title">
                <span>内核状态</span>
                <span class="badge" :class="isRunning ? 'badge-running' : 'badge-cancelled'">
                  <i class="bdot"></i>{{ isRunning ? '调度中' : '已暂停' }}
                </span>
              </div>
              <div class="kernel-metric-row mb8">
                <div class="k-stat">
                  <span class="k-label tertiary">健康度</span>
                  <span class="k-val font-bold" style="color: var(--accent-success)">99.4%</span>
                </div>
                <div class="k-stat">
                  <span class="k-label tertiary">活跃并发</span>
                  <span class="k-val font-bold mono" style="color: var(--accent-ai)">{{ runningDisplay }}/{{ capacity }}</span>
                </div>
                <div class="k-stat">
                  <span class="k-label tertiary">心跳</span>
                  <span class="k-val font-bold mono">{{ heartbeatMs }}ms</span>
                </div>
              </div>
              <div class="row" style="gap: 6px">
                <button class="btn btn-secondary btn-xs" style="flex: 1" @click="toggleScheduler">
                  {{ isRunning ? '⏸ 暂停' : '▶ 恢复' }}
                </button>
                <button class="btn btn-primary btn-xs" style="flex: 1" @click="showRegisterModal = true">
                  + 注册节点
                </button>
              </div>
            </div>

            <!-- 分发策略与并发滑块 -->
            <div class="dock-card mb10">
              <div class="dock-card-title">分发策略</div>
              <div class="chip-group mb8">
                <button
                  v-for="s in ['负载均衡', '优先级抢占', '亲和性']"
                  :key="s"
                  class="chip chip-xs"
                  :class="{ on: strategy === s }"
                  @click="handleStrategyChange(s)"
                >
                  {{ s }}
                </button>
              </div>
              <div class="field" style="margin: 6px 0 0">
                <div class="row-between">
                  <span class="field-label" style="margin: 0; font-size: 11px">并发容量</span>
                  <b class="num font-bold" style="color: var(--accent-ai); font-size: 13px">{{ capacity }}</b>
                </div>
                <input
                  v-model.number="capacity"
                  type="range"
                  class="cap-slider"
                  min="1"
                  max="8"
                  step="1"
                  style="margin-top: 4px"
                  @change="handleCapacityChange"
                />
              </div>
            </div>

            <!-- Worker 专精计算节点池 -->
            <div class="dock-card mb10">
              <div class="dock-card-title">
                <span>Worker 专精集群</span>
                <span class="small tertiary mono">{{ onlineCount }}/{{ totalWorkers }} 在线</span>
              </div>
              <div class="worker-card-list">
                <div
                  v-for="w in workerPool.slice(0, 4)"
                  :key="w.id"
                  class="worker-rich-card"
                  :class="w.state"
                  @click="openWorkerModal(w)"
                >
                  <div class="wrc-head">
                    <span class="wrc-dot" :class="w.state"></span>
                    <span class="wrc-name font-bold">{{ w.name }}</span>
                    <span class="wrc-state-tag" :class="w.state">{{ stateLabel(w.state) }}</span>
                  </div>
                  <div class="wrc-body">
                    <div class="wrc-caps">
                      <span v-for="c in w.caps" :key="c" class="cap-tag">{{ c }}</span>
                    </div>
                    <div class="wrc-load-wrap">
                      <span class="wrc-load-text mono small">{{ w.load }}%</span>
                      <div class="wrc-load-bar">
                        <div class="wrc-load-fill" :style="{ width: `${w.load}%`, background: w.load > 70 ? 'var(--accent-warning)' : 'var(--accent-ai)' }"></div>
                      </div>
                    </div>
                  </div>
                </div>
              </div>
            </div>

            <!-- AI 调度调优建议 -->
            <div class="dock-card ai-dock-card">
              <div class="dock-card-title">
                <span class="ai-badge"><i class="ai-dot"></i>AI 调度优化建议</span>
                <button class="link-btn" style="font-size: 11px" @click="nextAiAdvice">换一条</button>
              </div>
              <div class="small" style="line-height: 1.45; color: var(--text-secondary); margin-top: 4px">
                {{ currentAiAdvice }}
              </div>
              <div class="row mt6" style="justify-content: flex-end">
                <button class="btn btn-ai btn-xs" @click="applyAiAdvice">采纳建议</button>
              </div>
            </div>
          </div>
        </div>

        <!-- ═══ 右侧悬浮审计坞 (可收折) ═══ -->
        <div class="floating-dock dock-right" :class="{ collapsed: isRightDockCollapsed }">
          <div class="dock-header">
            <button class="dock-toggle-btn" :title="isRightDockCollapsed ? '展开审计面板' : '收折审计面板'" @click="isRightDockCollapsed = !isRightDockCollapsed">
              {{ isRightDockCollapsed ? '⇤' : '⇥' }}
            </button>
            <div class="dock-header-title">
              <span class="dock-ico">📋</span>
              <span v-show="!isRightDockCollapsed" class="dock-title-text font-bold">调度事件审计流</span>
            </div>
            <button v-show="!isRightDockCollapsed" class="link-btn" style="font-size: 10.5px; margin-left: auto" @click="logs = []">清空</button>
          </div>

          <div v-show="!isRightDockCollapsed" class="dock-scroll-content">
            <div class="chip-group mb8" style="gap: 4px">
              <button
                v-for="c in logCats"
                :key="c.key"
                class="chip chip-xs"
                :class="{ on: logCat === c.key }"
                @click="logCat = c.key"
              >
                {{ c.label }}
              </button>
            </div>

            <div class="log-stream">
              <div
                v-for="(l, idx) in filteredLogs"
                :key="idx"
                class="log-card-item"
                :class="[`cat-${l.cat}`, { clickable: !!l.tid }]"
                :title="l.tid ? '点击定位并高亮星图工单' : ''"
                @click="l.tid && flashTask(l.tid)"
              >
                <div class="lci-head">
                  <span class="lci-time mono">{{ l.time }}</span>
                  <span class="lci-tag" :class="l.cat">{{ l.kind }}</span>
                  <span v-if="l.tid" class="lci-tid mono">{{ l.tid.substring(0, 8) }}</span>
                </div>
                <div class="lci-body" v-html="l.html"></div>
              </div>
              <div v-if="!filteredLogs.length" class="empty" style="padding: 28px 10px">
                <div class="small tertiary">暂无调度事件流</div>
              </div>
            </div>
          </div>
        </div>

        <!-- ═══ 底部悬浮甘特图抽屉 (可展开/收起) ═══ -->
        <div class="floating-dock dock-bottom" :class="{ collapsed: isBottomDockCollapsed }">
          <div class="dock-header dock-bottom-header" @click="isBottomDockCollapsed = !isBottomDockCollapsed">
            <div class="dock-header-title">
              <span class="dock-ico">⏱</span>
              <span class="dock-title-text font-bold">先评后压全链路编排甘特图</span>
              <span class="dock-subtitle tertiary small">（多阶段流转与父子派生闭环）</span>
            </div>
            <div class="row" style="gap: 8px; font-size: 11px; margin-left: auto; margin-right: 12px">
              <span v-for="lg in ganttLegend" :key="lg.label" class="row" style="gap: 4px; align-items: center">
                <i class="gantt-dot" :style="{ background: lg.color }"></i>
                <span class="tertiary" style="font-size: 10px">{{ lg.label }}</span>
              </span>
            </div>
            <button class="dock-toggle-btn" :title="isBottomDockCollapsed ? '展开甘特抽屉' : '收折甘特抽屉'">
              {{ isBottomDockCollapsed ? '▲ 展开' : '▼ 收起' }}
            </button>
          </div>

          <div v-show="!isBottomDockCollapsed" class="dock-bottom-content">
            <div v-if="ganttRows.length" class="gantt">
              <div class="gantt-axis">
                <span v-for="(tick, i) in ganttTicks" :key="i" class="mono">{{ tick }}</span>
              </div>
              <div
                v-for="row in ganttRows"
                :key="row.id"
                class="gantt-row"
                :class="{ child: row.isChild }"
                :title="`${row.label}\n${statusLabel(row.status)} · ${fmtTime(row.start)} → ${fmtTime(row.end)}\n点击前往任务中心查看详情`"
                @click="goToTaskDetail(row.id)"
              >
                <div class="gantt-name">
                  <span v-if="row.isChild" class="tertiary" style="font-size: 10px">↳ 派生压测</span>
                  <KindTag :kind="row.kind" />
                  <span class="mono gantt-tid" style="font-size: 10.5px">{{ row.shortId }}</span>
                </div>
                <div class="gantt-track">
                  <div
                    class="gantt-bar"
                    :class="`st-${row.status}`"
                    :style="{ left: row.left + '%', width: Math.max(10, row.width) + '%' }"
                  >
                    <span class="gantt-bar-text">{{ statusLabel(row.status) }}</span>
                  </div>
                </div>
              </div>
            </div>
            <div v-else class="empty" style="padding: 16px 10px">
              <div class="small tertiary">暂无任务记录，发起评测任务后此处将展示完整阶段编排流转</div>
            </div>
          </div>
        </div>

        <!-- 悬停详情 tooltip -->
        <div v-if="tooltip" class="topo-tip" :style="{ left: tooltip.x + 'px', top: tooltip.y + 'px' }">
          <div class="tt-title">{{ tooltip.title }}</div>
          <div v-for="(ln, i) in tooltip.lines" :key="i" class="tt-line">
            <span class="tertiary">{{ ln[0] }}</span><span class="tt-val">{{ ln[1] }}</span>
          </div>
        </div>

        <!-- 工单锁定详情卡 -->
        <div v-if="pinnedTask && pinnedPos" class="pin-card" :style="{ left: pinnedPos.x + 'px', top: pinnedPos.y + 'px' }">
          <div class="pc-head">
            <i class="pc-bar" :style="{ background: kindColor(pinnedTask.kind) }"></i>
            <span class="mono pc-id">{{ pinnedTask.shortId }}</span>
            <span class="badge" :class="`badge-${pinnedTask.status}`">{{ statusLabel(pinnedTask.status) }}</span>
            <span class="grow"></span>
            <button class="pc-close" title="解锁（Esc）" @click="unpinTask">×</button>
          </div>
          <div class="pc-label">{{ pinnedTask.label }}</div>
          <div v-if="pinnedTask.status === 'running' && pinnedTask.progress != null" class="pc-progress">
            <i :style="{ width: `${pinnedTask.progress}%` }"></i>
          </div>
          <div class="pc-lines">
            <div class="tt-line"><span class="tertiary">执行节点</span><span class="tt-val mono">{{ pinnedTask.workerId || '排队待分发' }}</span></div>
            <div v-if="pinnedTask.progress != null" class="tt-line"><span class="tertiary">进度</span><span class="tt-val mono">{{ pinnedTask.progress }}%</span></div>
            <div v-if="pinnedTask.parentId" class="tt-line"><span class="tertiary">派生自</span><span class="tt-val mono">{{ pinnedTask.parentId.substring(0, 8) }}</span></div>
          </div>
          <div class="row" style="gap: 6px; margin-top: 8px">
            <button class="btn btn-secondary btn-sm grow" @click="goToTaskDetail(pinnedTask.id)">在任务中心查看 ↗</button>
            <button v-if="pinnedTask.status === 'succeeded'" class="btn btn-ai btn-sm" @click="goToReport(pinnedTask.id)">查看报告 📊</button>
          </div>
        </div>

        <!-- 扫描线装饰 -->
        <div class="scanline" aria-hidden="true"></div>
      </div>

      <!-- 图例 -->
      <div class="row mt12" style="gap: 14px; font-size: 11px; flex-wrap: wrap">
        <span class="row" style="gap: 5px; align-items: center"><i class="legend-line" style="background: repeating-linear-gradient(90deg, var(--text-tertiary) 0 3px, transparent 3px 7px)"></i><span class="tertiary">内核编排链路</span></span>
        <span class="row" style="gap: 5px; align-items: center"><i class="legend-line" style="background: var(--accent-ai)"></i><span class="tertiary">执行分发链路</span></span>
        <span class="row" style="gap: 5px; align-items: center"><i class="legend-dot" style="background: var(--accent-ai)"></i><span class="tertiary">数据流粒子</span></span>
        <span class="row" style="gap: 5px; align-items: center"><i class="legend-dot" style="background: var(--accent-success)"></i><span class="tertiary">完成涟漪</span></span>
        <span class="tertiary" style="margin-left: auto">滚轮缩放 · 拖拽平移 · 双击复位 · 浮窗面板可折叠</span>
      </div>
    </div>

    <!-- 节点治理弹窗 -->
    <n-modal
      v-model:show="showWorkerModal"
      preset="card"
      :title="`Worker 节点详情 · ${selectedWorker?.id} (${selectedWorker?.name || 'Worker Node'})`"
      style="width: 580px"
    >
      <div v-if="selectedWorker">
        <div class="form-row mb12">
          <div class="field">
            <span class="field-label">节点状态</span>
            <select v-model="selectedWorker.state" class="select">
              <option value="idle">在线空闲 (IDLE)</option>
              <option value="busy">执行中 (BUSY)</option>
              <option value="draining">排空下线 (DRAINING · 不接新单)</option>
              <option value="offline">离线维护 (OFFLINE)</option>
            </select>
          </div>
          <div class="field">
            <span class="field-label">调度权重 (Weight)</span>
            <input v-model.number="selectedWorker.weight" class="input num" type="number" min="10" max="500" />
          </div>
        </div>

        <div class="field">
          <span class="field-label">专精能力标签 (Capabilities，逗号分隔)</span>
          <input v-model="capsInput" class="input mono" />
          <span class="field-hint">可选能力: benchmark, judge, rag, vector, chunking, testcase, prd, openapi, stress, load, sse</span>
        </div>

        <div class="grid-2 mt12" style="gap: 8px; background: var(--bg-elevated); padding: 12px; border-radius: 8px">
          <div>
            <div class="small tertiary">当前执行任务</div>
            <div class="small font-bold" style="margin-top: 2px">{{ selectedWorker.task || '空闲待命中' }}</div>
          </div>
          <div>
            <div class="small tertiary">资源占用</div>
            <div class="small font-bold mono" style="margin-top: 2px">CPU {{ selectedWorker.load }}% · RAM {{ selectedWorker.ram }}</div>
          </div>
          <div style="margin-top: 6px">
            <div class="small tertiary">心跳周期</div>
            <div class="small font-bold" style="margin-top: 2px">
              <span v-if="selectedWorker.state === 'offline'" style="color: var(--accent-error)">丢失（心跳超时）</span>
              <span v-else style="color: var(--accent-success)">正常 · {{ heartbeatMs }}ms</span>
            </div>
          </div>
          <div style="margin-top: 6px">
            <div class="small tertiary">权重系数</div>
            <div class="small font-bold mono" style="margin-top: 2px">{{ selectedWorker.weight }}</div>
          </div>
        </div>
      </div>

      <template #footer>
        <div style="display: flex; justify-content: space-between; width: 100%">
          <button class="btn btn-secondary" @click="handleRebootWorker">重启节点</button>
          <div style="display: flex; gap: 8px">
            <button class="btn btn-secondary" @click="showWorkerModal = false">关闭</button>
            <button class="btn btn-sign" @click="handleSaveWorker">保存配置</button>
          </div>
        </div>
      </template>
    </n-modal>

    <!-- 注册 Worker 节点弹窗（对齐原型 dispatch.html：ID/名称/能力） -->
    <n-modal v-model:show="showRegisterModal" preset="card" title="注册 Worker 节点" style="width: 460px">
      <div class="field mb12">
        <span class="field-label">节点 ID <span style="color: var(--accent-error)">*</span></span>
        <input v-model="registerForm.id" class="input mono" placeholder="例如 worker-11" />
      </div>
      <div class="field mb12">
        <span class="field-label">节点名称</span>
        <input v-model="registerForm.name" class="input" placeholder="例如 GPU-Node-B1" />
      </div>
      <div class="field">
        <span class="field-label">专精能力标签（逗号分隔）</span>
        <input v-model="registerForm.caps" class="input mono" placeholder="benchmark, judge" />
        <span class="field-hint">可选能力: benchmark, judge, rag, vector, chunking, testcase, prd, openapi, stress, load, sse</span>
      </div>
      <template #footer>
        <div style="display: flex; gap: 8px; justify-content: flex-end">
          <button class="btn btn-secondary" @click="showRegisterModal = false">取消</button>
          <button class="btn btn-sign" @click="handleRegisterWorker">注册</button>
        </div>
      </template>
    </n-modal>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, onBeforeUnmount, watch } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { useMessage } from 'naive-ui'
import KindTag from '../components/common/KindTag.vue'
import WorkflowDesigner from '../components/workflow/WorkflowDesigner.vue'
import { api } from '../api/http'
import type { DispatchOverview, DispatchWorker, Task, TaskKind, TaskStatus } from '../api/types'
import { useModeStore } from '../stores/mode'

const message = useMessage()
const router = useRouter()
const route = useRoute()
const modeStore = useModeStore()
// live 模式接真实调度 API（§3.13）；mock 模式保留本地仿真演示
const liveMode = !api.isMock()

// 视图切换：'designer' (Dify 拖拽编排) vs 'monitor' (实时拓扑星图)
const activeTab = ref<'designer' | 'monitor'>('designer')

// 沉浸式大星图悬浮控制坞展开/收折状态
const isLeftDockCollapsed = ref(false)
const isRightDockCollapsed = ref(false)
const isBottomDockCollapsed = ref(false)

const isRunning = ref(true)
const strategy = ref('负载均衡')
const capacity = ref(4)
const assignedToday = ref(126)
const assignCosts = ref([72, 85, 94, 68, 88])
// live 模式大盘快照：KPI 与策略/容量以服务端返回为准
const overviewData = ref<DispatchOverview | null>(null)
const heartbeatMs = computed(() => overviewData.value?.heartbeat_interval_ms ?? 500)
const avgDispatchCost = computed(() => {
  if (liveMode) return overviewData.value?.avg_dispatch_cost_ms ?? 0
  if (!assignCosts.value.length) return 81
  return Math.round(assignCosts.value.reduce((a, b) => a + b, 0) / assignCosts.value.length)
})

// 顶栏模式标签配色（与全站双模式切换器联动展示）
const modeTagStyle = computed(() => ({
  color: modeStore.mode === 'rag' ? 'var(--c-kb)' : 'var(--c-datasets)',
  borderColor: modeStore.mode === 'rag' ? 'var(--t-kb)' : 'var(--t-datasets)',
}))

/* ─── KPI 数字滚动（count-up）与迷你趋势线 ─── */
function useCountUp(source: { value: number }) {
  const display = ref(source.value)
  let raf = 0
  watch(
    () => source.value,
    (to) => {
      const from = display.value
      const t0 = performance.now()
      cancelAnimationFrame(raf)
      const step = (t: number) => {
        const p = Math.min(1, (t - t0) / 350)
        display.value = Math.round(from + (to - from) * (1 - Math.pow(1 - p, 3)))
        if (p < 1) raf = requestAnimationFrame(step)
      }
      raf = requestAnimationFrame(step)
    },
  )
  return display
}

/** 迷你趋势线：历史序列 → polyline 坐标点（76×24 视窗） */
function sparkPoints(hist: number[]): string {
  if (hist.length < 2) return ''
  const max = Math.max(...hist, 1)
  const min = Math.min(...hist, 0)
  const span = Math.max(max - min, 1)
  return hist
    .map((v, i) => `${((i / (hist.length - 1)) * 74 + 1).toFixed(1)},${(22 - ((v - min) / span) * 20).toFixed(1)}`)
    .join(' ')
}

// 各 KPI 历史序列（每次全量刷新追加，保留最近 24 点）
const histQueue = ref<number[]>([])
const histRunning = ref<number[]>([])
const histCost = ref<number[]>([])
const histAssigned = ref<number[]>([])

function pushHist(hist: number[], v: number) {
  hist.push(v)
  if (hist.length > 24) hist.shift()
}

/* ─── 星图数据模型 ─── */
interface WorkerNode {
  id: string
  name: string
  caps: string[]
  state: 'idle' | 'busy' | 'offline' | 'draining'
  load: number
  ram: string
  task: string | null
  weight: number
}

const workerPool = ref<WorkerNode[]>([
  { id: 'worker-01', name: 'GPU-Node-A1', caps: ['benchmark', 'judge'], state: 'busy', load: 62, ram: '4.8GB/16GB', task: 'a1f3c2 · smoke-20 v3 (shard 2/5)', weight: 100 },
  { id: 'worker-02', name: 'Vec-Node-V1', caps: ['rag', 'vector'], state: 'idle', load: 8, ram: '2.1GB/16GB', task: null, weight: 100 },
  { id: 'worker-03', name: 'Gen-Node-G1', caps: ['testcase', 'prd'], state: 'busy', load: 45, ram: '3.4GB/16GB', task: 'd4c1a9 · PRD-支付 生成用例', weight: 80 },
  { id: 'worker-04', name: 'Stress-Node-S1', caps: ['stress', 'load'], state: 'idle', load: 12, ram: '1.8GB/16GB', task: null, weight: 120 },
  { id: 'worker-05', name: 'Judge-Node-J1', caps: ['benchmark', 'prompt'], state: 'offline', load: 0, ram: '0GB/16GB', task: null, weight: 100 },
  { id: 'worker-06', name: 'Chunk-Node-C1', caps: ['rag', 'chunking'], state: 'idle', load: 5, ram: '1.2GB/16GB', task: null, weight: 80 },
  { id: 'worker-07', name: 'Stress-Node-S2', caps: ['stress', 'sse'], state: 'busy', load: 88, ram: '7.2GB/16GB', task: 'g7b3d5 · 118 QPS 流式发压', weight: 150 },
  { id: 'worker-08', name: 'Eval-Node-E1', caps: ['benchmark', 'judge'], state: 'idle', load: 18, ram: '2.6GB/16GB', task: null, weight: 100 },
  { id: 'worker-09', name: 'RAG-Node-R1', caps: ['rag', 'lightrag'], state: 'offline', load: 0, ram: '0GB/16GB', task: null, weight: 100 },
  { id: 'worker-10', name: 'Case-Node-C2', caps: ['testcase', 'openapi'], state: 'idle', load: 9, ram: '1.5GB/16GB', task: null, weight: 90 },
])

// 任务工单：统一 mock 仿真项与 live 任务的星图展示模型
interface TaskNode {
  id: string
  shortId: string
  kind: TaskKind
  label: string
  status: TaskStatus
  progress: number | null
  workerId: string | null
  parentId: string | null
}

// mock 队列项扩展：分配后携带 workerId / 进度 / 开始时间，驱动飞行连线与甘特
interface QueueItem {
  qid: string
  kind: TaskKind
  label: string
  prio: string
  workerId?: string | null
  progress?: number
  startedAt?: number
  parentId?: string | null
}

const queue = ref<QueueItem[]>([
  { qid: 'q-101', kind: 'benchmark', label: '2 模型 × 数据集 smoke-20 v3 · shard 3/5', prio: 'P0' },
  { qid: 'q-102', kind: 'rag', label: '知识库 default · 黄金 QA qa-v1 · hybrid 回归', prio: 'P1' },
  { qid: 'q-103', kind: 'stress', label: '派生压测 · env=test · 10 QPS', prio: 'P2', parentId: 'q-101' },
])

// live 模式：活跃任务（queued/running/awaiting_case_confirm）与近期任务（甘特）
const liveActiveTasks = ref<Task[]>([])
const liveRecentTasks = ref<Task[]>([])
// live 模式任务→节点映射：由 assigned 事件维护，终态事件解除
const taskWorkerMap = ref<Record<string, string>>({})

/** 任务业务上下文标签：基准=模型×数据集；RAG=知识库×黄金QA×模式；用例=PRD 来源；压测=父任务+env/QPS */
function taskLabel(t: Task): string {
  const cfg = t.config || {}
  if (t.kind === 'benchmark') {
    const models = cfg.profile_ids?.length ? `${cfg.profile_ids.length} 模型` : ''
    const ds = cfg.dataset_id ? `数据集 ${cfg.dataset_id}` : ''
    return [models, ds].filter(Boolean).join(' × ') || 'Benchmark 基准评测'
  }
  if (t.kind === 'rag') {
    const kb = cfg.kb_id ? `知识库 ${cfg.kb_id}` : 'RAG 质量评测'
    const qa = cfg.gold_qa_id ? `黄金 QA ${cfg.gold_qa_id}` : ''
    const modes = cfg.rag_mode?.length ? cfg.rag_mode.join('/') : ''
    return [kb, qa, modes].filter(Boolean).join(' · ')
  }
  if (t.kind === 'testcase') {
    if (cfg.case_source?.text) return 'PRD 文本生成用例（6 大策略配比）'
    if (cfg.case_source?.file_id) return `文件 ${cfg.case_source.file_id} 生成用例`
    return 'PRD 用例生成'
  }
  const parent = cfg.parent_task_id || t.parent_task_id ? `派生自 ${String(cfg.parent_task_id || t.parent_task_id).substring(0, 8)}` : ''
  const env = cfg.stress?.env ? `env=${cfg.stress.env}` : ''
  const qps = cfg.stress?.qps ? `${cfg.stress.qps} QPS` : ''
  return [parent, env, qps].filter(Boolean).join(' · ') || '共享压测'
}

/** live 任务 → 星图工单；workerId 优先取事件映射，兜底用节点 current_task 短号前缀匹配 */
function mapLiveTask(t: Task): TaskNode {
  const short = t.id.substring(0, 6)
  let workerId = taskWorkerMap.value[t.id] || null
  if (!workerId && t.status === 'running') {
    const w = workerPool.value.find(x => x.task && x.task.includes(short))
    workerId = w?.id || null
  }
  const pct = t.progress
    ? Math.round(t.progress.percent ?? (t.progress.total ? (t.progress.done / t.progress.total) * 100 : 0))
    : null
  return {
    id: t.id,
    shortId: t.id.substring(0, 8),
    kind: t.kind,
    label: taskLabel(t),
    status: t.status,
    progress: pct,
    workerId,
    parentId: t.parent_task_id || t.config?.parent_task_id || null,
  }
}

// 统一任务工单：live 取服务端活跃任务；mock 由仿真队列合成
const taskNodes = computed<TaskNode[]>(() => {
  if (liveMode) return liveActiveTasks.value.map(mapLiveTask)
  return queue.value.map(q => ({
    id: q.qid,
    shortId: q.qid,
    kind: q.kind,
    label: q.label,
    status: q.workerId ? 'running' as TaskStatus : 'queued' as TaskStatus,
    progress: q.workerId ? Math.round(q.progress ?? 0) : null,
    workerId: q.workerId || null,
    parentId: q.parentId || null,
  }))
})

/* ─── 星图几何：中心内核 + 技能内环 + Worker 业务扇区外环 ─── */
const VB_W = 1200
const VB_H = 680
const CX = 600
const CY = 330
const R_QUEUE = 96    // 排队工单环绕内核的轨道半径
const R_SKILL = 152   // 技能 Agent 内环半径
const R_WORKER = 258  // Worker 外环半径
const MAX_QUEUE_CHIPS = 8 // 队列轨道最多平铺的工单数，溢出以 +N 提示

// 四大业务技能域（PRD §5.5.2）：角度采用屏幕坐标系（y 轴向下，90° 为正下方）
const SKILL_DEFS = [
  { kind: 'benchmark' as TaskKind, name: 'Benchmark', fullName: 'Benchmark 基准评测', icon: '📊', color: 'var(--c-datasets)', angle: -90, desc: '模型评测 · 数据集 · 先评后压' },
  { kind: 'rag' as TaskKind, name: 'RAG', fullName: 'RAG 质量评估', icon: '🔍', color: 'var(--c-kb)', angle: 0, desc: '知识库 · 黄金 QA · 4 模式检索' },
  { kind: 'stress' as TaskKind, name: 'Stress', fullName: '共享压测', icon: '⚡', color: 'var(--c-stress)', angle: 90, desc: '继承父任务 · SLA 拐点定位' },
  { kind: 'testcase' as TaskKind, name: 'Testcase', fullName: '用例生成', icon: '🧩', color: 'var(--c-cases)', angle: 180, desc: 'PRD/OpenAPI · 6 大策略配比' },
]

/** 极坐标 → 星图直角坐标（角度单位：度，0° 正右，90° 正下） */
function polar(angleDeg: number, r: number): { x: number; y: number } {
  const a = (angleDeg * Math.PI) / 180
  return { x: CX + r * Math.cos(a), y: CY + r * Math.sin(a) }
}

/** 业务扇区底色楔块路径：从内核出发的扇形（跨度 ±spread） */
function wedgePath(angle: number, spread: number, r: number): string {
  const p1 = polar(angle - spread, r)
  const p2 = polar(angle + spread, r)
  return `M ${CX} ${CY} L ${p1.x.toFixed(1)} ${p1.y.toFixed(1)} A ${r} ${r} 0 0 1 ${p2.x.toFixed(1)} ${p2.y.toFixed(1)} Z`
}

/** Worker 归属业务扇区：取能力标签中首个匹配的技能域，无匹配进通用扇区 */
function workerLane(w: WorkerNode): TaskKind | 'general' {
  const lane = SKILL_DEFS.find(l => w.caps.includes(l.kind))
  return lane ? lane.kind : 'general'
}

/** 业务标识色（工单芯片左侧色条） */
function kindColor(kind: TaskKind): string {
  const def = SKILL_DEFS.find(s => s.kind === kind)
  return def ? def.color : 'var(--text-tertiary)'
}

/** 文本截断：星图芯片宽度有限，超长标签省略号收尾 */
function trunc(s: string, n: number): string {
  return s.length > n ? s.slice(0, n - 1) + '…' : s
}

// 星图布局：技能节点坐标 / Worker 扇区坐标 / 工单芯片坐标 / 执行链路路径，全部由数据驱动
const topo = computed(() => {
  // 1) 技能 Agent 节点：固定角度布点 + 实时活跃统计
  const skills = SKILL_DEFS.map(d => {
    const p = polar(d.angle, R_SKILL)
    const tasks = taskNodes.value.filter(t => t.kind === d.kind)
    return {
      ...d, ...p,
      activeCount: tasks.length,
      runningCount: tasks.filter(t => t.status === 'running').length,
    }
  })
  const skillByKind = new Map(skills.map(s => [s.kind as string, s]))

  // 2) 扇区定义：四业务域 + 有未匹配节点时的通用扇区（压缩邻域跨度避免重叠）
  const hasGeneral = workerPool.value.some(w => workerLane(w) === 'general')
  const spread = hasGeneral ? 26 : 34
  const sectorDefs = SKILL_DEFS.map(d => ({ kind: d.kind as string, angle: d.angle, spread, color: d.color }))
  if (hasGeneral) sectorDefs.push({ kind: 'general', angle: 135, spread: 14, color: 'var(--text-tertiary)' })
  const sectors = sectorDefs.map(s => ({ ...s, wedge: wedgePath(s.angle, s.spread + 8, R_WORKER + 46) }))

  // 3) Worker 节点：按扇区角距均布，单环超过 5 个时外扩第二环
  const workers: { w: WorkerNode; x: number; y: number; sx: number; sy: number; skillKind: string }[] = []
  sectorDefs.forEach(sec => {
    const list = workerPool.value.filter(w => workerLane(w) === sec.kind)
    const skill = skillByKind.get(sec.kind)
    list.forEach((w, i) => {
      const ring = Math.floor(i / 5)
      const idxInRing = i % 5
      const inRing = Math.min(5, list.length - ring * 5)
      const offset = inRing === 1 ? 0 : -sec.spread + (2 * sec.spread * idxInRing) / (inRing - 1)
      const p = polar(sec.angle + offset, R_WORKER + ring * 58)
      workers.push({ w, x: p.x, y: p.y, sx: skill?.x ?? CX, sy: skill?.y ?? CY, skillKind: sec.kind })
    })
  })
  const workerById = new Map(workers.map(pw => [pw.w.id, pw]))

  // 4) 工单芯片：queued 在内环轨道均布；running 飞至 技能→Worker 链路中段（同节点多任务垂直偏移堆叠）
  const queued = taskNodes.value.filter(t => t.status !== 'running')
  const running = taskNodes.value.filter(t => t.status === 'running')
  const runStack = new Map<string, number>()
  const tasks: { t: TaskNode; x: number; y: number }[] = []
  queued.slice(0, MAX_QUEUE_CHIPS).forEach((t, i) => {
    const p = polar(105 + i * 30, R_QUEUE)
    tasks.push({ t, x: p.x, y: p.y })
  })
  running.forEach(t => {
    const skill = skillByKind.get(t.kind)
    const pw = t.workerId ? workerById.get(t.workerId) : undefined
    if (skill && pw) {
      // 链路中段定位：技能节点 → Worker 55% 处，按堆叠序号垂直偏移
      const mx = skill.x + (pw.x - skill.x) * 0.55
      const my = skill.y + (pw.y - skill.y) * 0.55
      const dx = pw.x - skill.x
      const dy = pw.y - skill.y
      const len = Math.max(Math.hypot(dx, dy), 1)
      const stackIdx = runStack.get(pw.w.id) || 0
      runStack.set(pw.w.id, stackIdx + 1)
      tasks.push({ t, x: mx + (-dy / len) * 30 * stackIdx, y: my + (dx / len) * 30 * stackIdx })
    } else if (skill) {
      // 运行中但尚未解析到节点：悬停于技能节点内侧等待连线
      const idx = running.indexOf(t)
      const p = polar(skill.angle + 24 + idx * 14, R_SKILL - 58)
      tasks.push({ t, x: p.x, y: p.y })
    }
  })

  // 5) 执行链路：内核 → 技能 → Worker 折线，粒子沿路径流动
  const liveWires = running
    .filter(t => t.workerId && workerById.has(t.workerId) && skillByKind.has(t.kind))
    .map(t => {
      const s = skillByKind.get(t.kind)!
      const pw = workerById.get(t.workerId!)!
      return { key: `live-${t.id}`, skillKind: t.kind as string, d: `M ${CX} ${CY} L ${s.x} ${s.y} L ${pw.x} ${pw.y}` }
    })

  return { skills, sectors, workers, tasks, liveWires, queueOverflow: Math.max(0, queued.length - MAX_QUEUE_CHIPS) }
})

const onlineCount = computed(() =>
  liveMode && overviewData.value
    ? overviewData.value.online_workers
    : workerPool.value.filter(w => w.state !== 'offline').length,
)
const totalWorkers = computed(() =>
  liveMode && overviewData.value ? overviewData.value.total_workers : workerPool.value.length,
)
const queueDepth = computed(() =>
  liveMode && overviewData.value ? overviewData.value.queue_depth : queue.value.filter(q => !q.workerId).length,
)
const runningCount = computed(() => taskNodes.value.filter(t => t.status === 'running').length)
const assignedTodayNum = computed(() =>
  liveMode && overviewData.value ? overviewData.value.assigned_today : assignedToday.value,
)

// KPI 数字滚动显示值
const onlineDisplay = useCountUp(onlineCount)
const queueDisplay = useCountUp(queueDepth)
const runningDisplay = useCountUp(runningCount)
const costDisplay = useCountUp(avgDispatchCost)
const assignedDisplay = useCountUp(assignedTodayNum)

/* ─── 星图视图变换：滚轮缩放（以光标为中心）+ 拖拽平移 + 双击复位 ─── */
const svgRef = ref<SVGSVGElement | null>(null)
const wrapRef = ref<HTMLDivElement | null>(null)
const view = ref({ x: 0, y: 0, k: 1 })

/** 屏幕坐标 → viewBox 坐标换算（依赖容器实际渲染尺寸） */
function toViewBox(e: { clientX: number; clientY: number }): { x: number; y: number } {
  const rect = svgRef.value?.getBoundingClientRect()
  if (!rect) return { x: 0, y: 0 }
  return { x: ((e.clientX - rect.left) / rect.width) * VB_W, y: ((e.clientY - rect.top) / rect.height) * VB_H }
}

function onWheel(e: WheelEvent) {
  e.preventDefault()
  const s = toViewBox(e)
  const k0 = view.value.k
  const k1 = Math.min(2.2, Math.max(0.55, k0 * (e.deltaY < 0 ? 1.12 : 0.89)))
  // 保持光标下的内容点不动：p = (s - view) / k0，缩放后 view' = s - k1 * p
  const px = (s.x - view.value.x) / k0
  const py = (s.y - view.value.y) / k0
  view.value = { k: k1, x: s.x - k1 * px, y: s.y - k1 * py }
}

/** 按钮缩放：以画布中心为基准点 */
function zoomBy(factor: number) {
  const k1 = Math.min(2.2, Math.max(0.55, view.value.k * factor))
  const px = (VB_W / 2 - view.value.x) / view.value.k
  const py = (VB_H / 2 - view.value.y) / view.value.k
  view.value = { k: k1, x: VB_W / 2 - k1 * px, y: VB_H / 2 - k1 * py }
}

/** 复位视图并清除扇区聚焦 */
function resetView() {
  view.value = { x: 0, y: 0, k: 1 }
  focusedSkill.value = null
}

// 拖拽平移：位移超过 4px 判定为平移，抑制节点 click 触发
let panning = false
let panMoved = false
let panStart = { x: 0, y: 0 }
let viewStart = { x: 0, y: 0, k: 1 }

function onPointerDown(e: PointerEvent) {
  if (e.button !== 0) return
  panning = true
  panMoved = false
  panStart = { x: e.clientX, y: e.clientY }
  viewStart = { ...view.value }
  hideTip()
}

function onPointerMove(e: PointerEvent) {
  if (!panning) return
  const dx = e.clientX - panStart.x
  const dy = e.clientY - panStart.y
  if (Math.abs(dx) + Math.abs(dy) > 4) panMoved = true
  const rect = svgRef.value?.getBoundingClientRect()
  if (!rect) return
  view.value = {
    k: viewStart.k,
    x: viewStart.x + dx * (VB_W / rect.width),
    y: viewStart.y + dy * (VB_H / rect.height),
  }
}

function onPointerUp() {
  panning = false
}

/** 节点点击守卫：拖拽平移后的抬起不触发节点动作 */
function onNodeClick(fn: () => void) {
  if (panMoved) return
  fn()
}

/* ─── 扇区聚焦：点击技能节点锁定查看本业务域，其余元素淡化为背景 ─── */
const focusedSkill = ref<string | null>(null)
function toggleFocus(kind: string) {
  focusedSkill.value = focusedSkill.value === kind ? null : kind
}

/* ─── 悬停 tooltip：Worker / 技能 / 工单 三类节点详情 ─── */
const tooltip = ref<{ x: number; y: number; title: string; lines: [string, string][] } | null>(null)

function placeTip(e: MouseEvent, title: string, lines: [string, string][]) {
  const wrap = wrapRef.value
  if (!wrap) return
  const r = wrap.getBoundingClientRect()
  tooltip.value = {
    x: Math.min(e.clientX - r.left + 14, r.width - 250),
    y: Math.max(e.clientY - r.top + 12, 8),
    title,
    lines,
  }
}

function hideTip() {
  tooltip.value = null
}

function stateLabel(s: string): string {
  const map: Record<string, string> = { idle: '在线空闲', busy: '执行中', draining: '排空下线', offline: '离线维护' }
  return map[s] || s
}

function showWorkerTip(e: MouseEvent, w: WorkerNode) {
  placeTip(e, `${w.id} · ${w.name}`, [
    ['状态', stateLabel(w.state)],
    ['负载', `CPU ${w.load}% · RAM ${w.ram}`],
    ['能力', w.caps.join(', ') || '—'],
    ['当前任务', w.task || '空闲待命中'],
    ['权重', String(w.weight)],
  ])
}

function showSkillTip(e: MouseEvent, s: { fullName: string; desc: string; runningCount: number; activeCount: number }) {
  placeTip(e, s.fullName, [
    ['职责', s.desc],
    ['运行中', `${s.runningCount} 个任务`],
    ['活跃工单', `${s.activeCount} 个`],
    ['操作', '点击聚焦 / 取消聚焦本业务扇区'],
  ])
}

function showTaskTip(e: MouseEvent, t: TaskNode) {
  placeTip(e, `工单 ${t.shortId}`, [
    ['业务', t.label],
    ['状态', statusLabel(t.status) + (t.progress != null ? ` · ${t.progress}%` : '')],
    ['执行节点', t.workerId || '排队待分发'],
    ['操作', '点击锁定详情卡'],
  ])
}

/* ─── 工单锁定详情卡：点击芯片驻留，跟随视图变换，Esc / 点击空白解锁 ─── */
const pinnedTask = ref<TaskNode | null>(null)
// 容器渲染尺寸：SVG 坐标 → 屏幕像素换算依赖实际宽高，随窗口 resize 更新
const wrapSize = ref({ w: 0, h: 0 })

function pinTask(t: TaskNode) {
  pinnedTask.value = t
  hideTip()
}

function unpinTask() {
  pinnedTask.value = null
}

/** 背景点击解锁：仅在命中网格背景（非任何节点）且非拖拽平移后触发 */
function onBgClick(e: MouseEvent) {
  if (panMoved) return
  if ((e.target as Element)?.classList?.contains('topo-bg')) unpinTask()
}

// 锁定卡屏幕坐标：星图 SVG 坐标经 view 变换后按容器比例换算，锚定在芯片右下方
const pinnedPos = computed(() => {
  const t = pinnedTask.value
  if (!t || !wrapSize.value.w) return null
  const p = topo.value.tasks.find(x => x.t.id === t.id)
  if (!p) return null
  const sx = (view.value.x + view.value.k * p.x) * (wrapSize.value.w / VB_W)
  const sy = (view.value.y + view.value.k * p.y) * (wrapSize.value.h / VB_H)
  return {
    x: Math.max(8, Math.min(sx + 88 * view.value.k, wrapSize.value.w - 240)),
    y: Math.max(8, Math.min(sy - 10, wrapSize.value.h - 190)),
  }
})

// 锁定的工单完成/消失（离开活跃列表）时自动解锁
watch(taskNodes, (list) => {
  if (pinnedTask.value && !list.some(t => t.id === pinnedTask.value!.id)) unpinTask()
})

/** Esc 解锁锁定卡 */
function onKeydown(e: KeyboardEvent) {
  if (e.key === 'Escape') unpinTask()
}

/* ─── 调度事件流（分类过滤 + 点击定位星图工单） ─── */
interface LogItem {
  time: string
  kind: string
  cat: 'assign' | 'done' | 'error' | 'node'
  html: string
  tid?: string
}

const logs = ref<LogItem[]>([
  { time: new Date().toTimeString().slice(0, 8), kind: 'ENQUEUE', cat: 'assign', html: '<span class="la">q-101</span> 2 模型 × smoke-20 v3 · shard 3/5 (P0)', tid: 'q-101' },
  { time: new Date().toTimeString().slice(0, 8), kind: 'ASSIGN', cat: 'assign', html: '<span class="la">q-100</span> → worker-01 · 耗时 82ms', tid: 'q-100' },
])

const logCat = ref<'all' | LogItem['cat']>('all')
const logCats = [
  { key: 'all' as const, label: '全部' },
  { key: 'assign' as const, label: '分配' },
  { key: 'done' as const, label: '完成' },
  { key: 'error' as const, label: '异常' },
  { key: 'node' as const, label: '节点' },
]
const filteredLogs = computed(() => (logCat.value === 'all' ? logs.value : logs.value.filter(l => l.cat === logCat.value)))

/** 事件类型归一化为展示分类 */
function eventCat(kind: string): LogItem['cat'] {
  const k = kind.toUpperCase()
  if (['ASSIGN', 'ENQUEUE', 'HOLD', 'START'].some(x => k.includes(x))) return 'assign'
  if (['DONE', 'SUCCEEDED', 'COMPLETE', 'FINISH'].some(x => k.includes(x))) return 'done'
  if (['FAIL', 'ERROR', 'TIMEOUT', 'CANCEL'].some(x => k.includes(x))) return 'error'
  return 'node'
}

/** 统一日志入口：prepend 并截断至 50 条，与原型 log() 语义一致。 */
function addLog(kind: string, html: string, tid?: string) {
  logs.value.unshift({ time: new Date().toTimeString().slice(0, 8), kind, cat: eventCat(kind), html, tid })
  if (logs.value.length > 50) logs.value.pop()
}

/** 接收 WorkflowDesigner 工作流执行派发的任务 */
function handleTaskDispatched(taskId: string) {
  assignedToday.value += 1
  pushHist(histAssigned.value, assignedToday.value)
  addLog('ENQUEUE', `<span class="la">${taskId.substring(0, 8)}</span> 工作流编排任务已推入执行队列`, taskId)
  if (liveMode) {
    loadLiveAll()
  }
}

// 点击日志定位：闪烁星图中对应任务工单
const flashTaskId = ref('')
let flashTimer = 0
function flashTask(tid: string) {
  flashTaskId.value = tid
  window.clearTimeout(flashTimer)
  flashTimer = window.setTimeout(() => { flashTaskId.value = '' }, 1600)
}

function goTasks() {
  router.push('/tasks')
}

/** 前往任务中心并自动打开指定任务详情抽屉 */
function goToTaskDetail(taskId?: string) {
  if (taskId) {
    router.push({ path: '/tasks', query: { id: taskId } })
  } else {
    router.push('/tasks')
  }
}

/** 前往报告中心查看评测结果 */
function goToReport(taskId?: string) {
  if (!taskId) {
    router.push('/reports')
    return
  }
  const fullTask = liveRecentTasks.value.find(t => t.id === taskId) || liveActiveTasks.value.find(t => t.id === taskId)
  if (fullTask?.report_id) {
    router.push(`/reports/${fullTask.report_id}`)
  } else {
    // 若尚未生成 report_id，先前往任务详情抽屉查看实时进展
    router.push({ path: '/tasks', query: { id: taskId } })
  }
}

/** 处理从外部（如任务中心）传入的任务高亮聚焦参数 */
function handleRouteTaskFocus() {
  const tid = (route.query.task_id || route.query.highlight_task) as string | undefined
  if (tid) {
    activeTab.value = 'monitor'
    const match = taskNodes.value.find(t => t.id === tid || t.shortId === tid || t.id.startsWith(tid))
    if (match) {
      pinTask(match)
      flashTask(match.id)
      focusedSkill.value = match.kind
      message.info(`已聚焦任务 ${match.shortId} 调度拓扑链路`)
    } else {
      flashTask(tid)
    }
  }
}

/* AI 建议结构化：携带建议动作（策略切换/容量调整），采纳时按内容生效（对齐原型 dispatch.html） */
interface AiAdvice {
  text: string
  strategy?: string
  cap?: number
}

const aiAdvices: AiAdvice[] = [
  { text: '当前 GPU-Node-A1 负载偏高（62%），建议切换「负载均衡」策略分流 judge 任务。', strategy: '负载均衡' },
  { text: '排队深度上升，建议将并发容量提升至 6 以消化积压任务。', cap: 6 },
  { text: '亲和性策略下 RAG 评测排队时间缩短 34%，建议持续保持该模式。', strategy: '亲和性' },
]
const aiAdviceIdx = ref(0)
const currentAiAdvice = computed(() => aiAdvices[aiAdviceIdx.value].text)

function nextAiAdvice() {
  aiAdviceIdx.value = (aiAdviceIdx.value + 1) % aiAdvices.length
}

/** 采纳建议：按建议内容切换策略/调整容量，并写入调度日志 */
function applyAiAdvice() {
  const advice = aiAdvices[aiAdviceIdx.value]
  const actions: string[] = []
  if (advice.strategy) {
    strategy.value = advice.strategy
    actions.push(`策略切换为「${advice.strategy}」`)
  }
  if (advice.cap) {
    capacity.value = advice.cap
    actions.push(`并发容量调整为 ${advice.cap}`)
  }
  if (!actions.length) actions.push('无参数变更')
  addLog('AI', `采纳调度建议：${actions.join('；')}`)
  message.success(`已采纳 AI 优化建议（${actions.join('；')}）`)
}

// 节点治理弹窗
const showWorkerModal = ref(false)
const selectedWorker = ref<WorkerNode | null>(null)
const capsInput = ref('')

function openWorkerModal(w: WorkerNode) {
  selectedWorker.value = { ...w }
  capsInput.value = (w.caps || []).join(', ')
  showWorkerModal.value = true
}

function handleRebootWorker() {
  if (!selectedWorker.value) return
  if (liveMode) {
    // 契约未定义节点重启接口，live 模式仅允许状态/权重/能力治理
    message.warning('节点重启接口尚未在 API 契约中定义，可在本弹窗调整节点状态进行治理')
    return
  }
  const target = workerPool.value.find(w => w.id === selectedWorker.value?.id)
  if (target) {
    target.state = 'idle'
    target.load = 4
    target.task = null
  }
  addLog('NODE', `管理员重启了节点 <span class="la">${selectedWorker.value.id}</span>`)
  message.success(`节点 ${selectedWorker.value.id} 已重启完毕`)
  showWorkerModal.value = false
}

async function handleSaveWorker() {
  if (!selectedWorker.value) return
  const caps = capsInput.value.split(',').map(s => s.trim()).filter(Boolean)
  if (liveMode) {
    try {
      await api.dispatch.updateWorker(selectedWorker.value.id, {
        state: selectedWorker.value.state,
        weight: selectedWorker.value.weight,
        caps,
      })
      message.success(`已保存 ${selectedWorker.value.id} 节点配置`)
      showWorkerModal.value = false
      await loadLiveAll()
    } catch (err: any) {
      message.error(err.message || '节点配置保存失败')
    }
    return
  }
  const target = workerPool.value.find(w => w.id === selectedWorker.value?.id)
  if (target) {
    target.state = selectedWorker.value.state
    target.weight = selectedWorker.value.weight
    target.caps = caps
  }
  addLog('CONFIG', `更新节点 <span class="la">${selectedWorker.value.id}</span> 配置 · 状态=${selectedWorker.value.state} · 权重=${selectedWorker.value.weight}`)
  message.success(`已保存 ${selectedWorker.value.id} 节点配置`)
  showWorkerModal.value = false
}

function handleManualEnqueue() {
  if (liveMode) {
    // 契约要求任务由智能体/表单真实创建，浏览器不得伪造入队
    message.warning('演示插单仅 mock 模式可用；请通过智能体对话或任务页「新建任务」创建真实任务')
    return
  }
  enqueueMockTask()
}

/* ─── 完成涟漪：任务终态时在 Worker 节点位置扩散一圈（SVG 坐标系直取布局坐标） ─── */
const ripples = ref<{ id: number; x: number; y: number }[]>([])
let rippleSeq = 0
function addRippleAtWorker(workerId: string | null | undefined) {
  if (!workerId) return
  const pw = topo.value.workers.find(x => x.w.id === workerId)
  if (!pw) return
  const id = ++rippleSeq
  ripples.value.push({ id, x: pw.x, y: pw.y })
  window.setTimeout(() => { ripples.value = ripples.value.filter(p => p.id !== id) }, 1200)
}

/* ─── mock 调度分发循环：按策略选节点 → 工单飞向节点 → 进度推进 → 完成涟漪 + 甘特沉淀 ─── */
let enqueueSeq = 200
const QUEUE_TPL: { kind: TaskKind; label: string; prio: string; parentId?: string }[] = [
  { kind: 'benchmark', label: '2 模型 × 数据集 smoke-20 v3 · 规则评分', prio: 'P1' },
  { kind: 'rag', label: '知识库 default · 黄金 QA qa-v1 · naive/local 对比', prio: 'P1' },
  { kind: 'testcase', label: 'PRD-支付链路 用例生成（40/25/15/10/5/5）', prio: 'P2' },
  { kind: 'stress', label: '派生压测 · env=test · 10 QPS', prio: 'P2', parentId: 'q-101' },
]

// mock 甘特历史：完成的编排段沉淀于此（最近 12 条）
interface GanttRow {
  id: string
  shortId: string
  kind: TaskKind
  label: string
  status: TaskStatus
  start: number
  end: number
  parentId: string | null
  isChild: boolean
  left: number
  width: number
}
const mockGanttDone = ref<GanttRow[]>([])
// 甘特「当前时刻」游标：运行中条形随时间延展
const nowTs = ref(Date.now())

/** 按当前策略挑选可接单节点：离线/排空节点与满载（≥92%）节点不参与。 */
function pickAgent(): WorkerNode | null {
  const candidates = workerPool.value.filter(w => w.state !== 'offline' && w.state !== 'draining' && w.state !== 'busy' && w.load < 92)
  if (!candidates.length) return null
  if (strategy.value === '负载均衡') return candidates.sort((x, y) => x.load - y.load)[0]
  if (strategy.value === '优先级抢占') return candidates[Math.floor(Math.random() * candidates.length)]
  return candidates.sort((x, y) => (y.caps.length - x.caps.length) || (x.load - y.load))[0] // 亲和性
}

function enqueueMockTask() {
  const tpl = QUEUE_TPL[Math.floor(Math.random() * QUEUE_TPL.length)]
  const q: QueueItem = { qid: 'q-' + enqueueSeq++, kind: tpl.kind, label: tpl.label, prio: tpl.prio, parentId: tpl.parentId || null }
  queue.value.push(q)
  addLog('ENQUEUE', `<span class="la">${q.qid}</span> ${tpl.label} (${q.prio})`, q.qid)
  const t = window.setTimeout(() => {
    assignTimers.delete(t)
    tryAssign()
  }, 600)
  assignTimers.add(t)
}

function tryAssign() {
  const waiting = queue.value.filter(q => !q.workerId)
  if (!waiting.length) return
  const busyCount = workerPool.value.filter(w => w.state === 'busy').length
  if (busyCount >= capacity.value) {
    if (Math.random() < 0.3) addLog('HOLD', `并发已满（${busyCount}/${capacity.value}），<span class="la">${waiting[0].qid}</span> 保持排队`, waiting[0].qid)
    return
  }
  const q = waiting[0]
  const agent = pickAgent()
  if (!agent) return
  const cost = 55 + Math.round(Math.random() * 70)
  assignCosts.value.push(cost)
  if (assignCosts.value.length > 12) assignCosts.value.shift()
  // 工单状态置为运行并绑定节点：星图位置由 computed 驱动，CSS transition 自动播放飞行动效
  q.workerId = agent.id
  q.progress = 0
  q.startedAt = Date.now()
  agent.state = 'busy'
  agent.load = Math.min(96, agent.load + 24 + Math.round(Math.random() * 22))
  agent.task = q.qid + ' · ' + q.label
  assignedToday.value++
  addLog('ASSIGN', `<span class="la">${q.qid}</span> → ${agent.id} · 策略=${strategy.value} · 耗时 ${cost}ms`, q.qid)

  // 执行 4~8.5s：期间按节拍推进进度，完成后释放槽位、触发涟漪并沉淀甘特历史
  const duration = 4000 + Math.random() * 4500
  const progressTimer = window.setInterval(() => {
    if (q.startedAt) q.progress = Math.min(99, ((Date.now() - q.startedAt) / duration) * 100)
  }, 400)
  assignTimers.add(progressTimer)
  const doneTimer = window.setTimeout(() => {
    assignTimers.delete(doneTimer)
    window.clearInterval(progressTimer)
    assignTimers.delete(progressTimer)
    queue.value = queue.value.filter(x => x.qid !== q.qid)
    agent.load = Math.max(4, agent.load - 32 - Math.round(Math.random() * 20))
    if (agent.load < 30) {
      agent.state = 'idle'
      agent.task = null
    }
    addRippleAtWorker(agent.id)
    mockGanttDone.value.unshift({
      id: q.qid, shortId: q.qid, kind: q.kind, label: q.label, status: 'succeeded',
      start: q.startedAt || Date.now() - duration, end: Date.now(),
      parentId: q.parentId || null, isChild: !!q.parentId, left: 0, width: 0,
    })
    if (mockGanttDone.value.length > 12) mockGanttDone.value.pop()
    addLog('DONE', `${agent.id} 执行完成 <span class="la">${q.qid}</span>，释放并发槽位 · 负载回落至 ${agent.load}%`, q.qid)
  }, duration)
  assignTimers.add(doneTimer)
}

/** 调度主循环节拍：45% 概率自动入队新任务，其余时间尝试分发。 */
function dispatchTick() {
  if (!isRunning.value) return
  nowTs.value = Date.now()
  pushHist(histQueue.value, queueDepth.value)
  pushHist(histRunning.value, runningCount.value)
  pushHist(histCost.value, avgDispatchCost.value)
  pushHist(histAssigned.value, assignedTodayNum.value)
  const r = Math.random()
  if (r < 0.45 && queue.value.length < 5) {
    enqueueMockTask()
  } else {
    tryAssign()
  }
}

/** 暂停/恢复调度：暂停后已有任务继续执行，仅停止新任务入队与分发；契约未定义暂停接口，live 模式提示能力未启用 */
function toggleScheduler() {
  if (liveMode) {
    message.warning('调度暂停/恢复接口尚未在 API 契约中定义，当前仅演示模式可用')
    return
  }
  isRunning.value = !isRunning.value
  addLog('CONFIG', isRunning.value ? '调度器已恢复运行' : '调度器已暂停（已有任务继续执行）')
  message.info(isRunning.value ? '调度器已恢复' : '调度器已暂停（已有任务继续执行）')
}

/** 切换分发策略：live 模式即写 PUT /api/dispatch/config */
async function handleStrategyChange(s: string) {
  strategy.value = s
  if (!liveMode) return
  try {
    await api.dispatch.updateConfig({ strategy: s as '负载均衡' | '优先级抢占' | '亲和性' })
    message.success(`分发策略已切换为「${s}」`)
  } catch (err: any) {
    message.error(err.message || '策略更新失败')
  }
}

/** 调整全局并发容量：live 模式在滑块释放时落库 */
async function handleCapacityChange() {
  if (!liveMode) return
  try {
    await api.dispatch.updateConfig({ max_running_tasks: capacity.value })
    message.success(`并发容量已调整为 ${capacity.value}`)
  } catch (err: any) {
    message.error(err.message || '并发容量更新失败')
  }
}

// 注册节点弹窗
const showRegisterModal = ref(false)
const registerForm = ref({ id: '', name: '', caps: '' })

/** 注册新 Worker 节点：live 模式走 POST /api/dispatch/workers，mock 本地入池 */
async function handleRegisterWorker() {
  const id = registerForm.value.id.trim()
  if (!id) {
    message.warning('请输入节点 ID')
    return
  }
  if (workerPool.value.some(w => w.id === id)) {
    message.error(`节点 ${id} 已存在`)
    return
  }
  const caps = registerForm.value.caps.split(',').map(s => s.trim()).filter(Boolean)
  if (liveMode) {
    try {
      await api.dispatch.createWorker({ id, name: registerForm.value.name.trim() || id, caps })
      message.success(`节点 ${id} 已注册，等待首次心跳上报`)
      registerForm.value = { id: '', name: '', caps: '' }
      showRegisterModal.value = false
      await loadLiveAll()
    } catch (err: any) {
      message.error(err.message || '节点注册失败')
    }
    return
  }
  workerPool.value.push({
    id,
    name: registerForm.value.name.trim() || id,
    caps,
    state: 'idle',
    load: 2,
    ram: '0.5GB/16GB',
    task: null,
    weight: 100,
  })
  addLog('NODE', `注册新节点 <span class="la">${id}</span>，状态 IDLE 待接单`)
  message.success(`节点 ${id} 已注册`)
  registerForm.value = { id: '', name: '', caps: '' }
  showRegisterModal.value = false
}

/* ─── live 模式数据接入：大盘/节点/任务周期拉取 + 调度事件增量轮询（§3.13） ─── */
let lastEventId = 0
let pollTimer: number | null = null
let pollRound = 0

/** 服务端 Worker 快照映射为星图节点模型；RAM 用量契约未提供时显示占位。 */
function mapWorker(w: DispatchWorker): WorkerNode {
  return {
    id: w.id,
    name: w.name,
    caps: w.caps || [],
    state: w.state,
    load: Math.round(w.load_percent ?? 0),
    ram: '—',
    task: w.current_task || null,
    weight: w.weight,
  }
}

function escapeHtml(s: string): string {
  return s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
}

/** 全量刷新大盘指标、节点池与任务域（活跃任务进星图，近期任务进甘特）。 */
async function loadLiveAll() {
  try {
    const [ov, workers, allTasks] = await Promise.all([
      api.dispatch.overview(),
      api.dispatch.workers(),
      api.tasks.list(),
    ])
    if (ov) {
      overviewData.value = ov
      strategy.value = ov.strategy
      capacity.value = ov.max_running_tasks
    }
    if (workers) workerPool.value = workers.map(mapWorker)
    const sorted = [...allTasks].sort((a, b) => +new Date(b.created_at) - +new Date(a.created_at))
    liveActiveTasks.value = sorted.filter(t => ['queued', 'running', 'awaiting_case_confirm'].includes(t.status))
    liveRecentTasks.value = sorted.slice(0, 12)
    nowTs.value = Date.now()
    pushHist(histQueue.value, queueDepth.value)
    pushHist(histRunning.value, runningCount.value)
    pushHist(histCost.value, avgDispatchCost.value)
    pushHist(histAssigned.value, assignedTodayNum.value)
  } catch (err: any) {
    message.error(err.message || '调度数据加载失败')
  }
}

/** 增量拉取调度事件流：维护任务→节点映射与终态涟漪；日志只能由调度器/Worker 写入，浏览器不生成不改写。 */
async function pollLiveEvents() {
  try {
    const page = await api.dispatch.events(lastEventId || undefined)
    if (!page) return
    if (page.items.length) {
      page.items.forEach(e => {
        const ev = e.event.toLowerCase()
        // assigned 事件建立任务→节点映射，终态事件解除并在节点上触发涟漪
        if (ev === 'assigned' && e.task_id && e.worker_id) taskWorkerMap.value[e.task_id] = e.worker_id
        if (['succeeded', 'failed', 'cancelled'].includes(ev) && e.task_id) {
          addRippleAtWorker(taskWorkerMap.value[e.task_id])
          delete taskWorkerMap.value[e.task_id]
        }
      })
      const mapped = page.items.map(e => ({
        time: new Date(e.ts).toTimeString().slice(0, 8),
        kind: e.event.toUpperCase(),
        cat: eventCat(e.event),
        html: escapeHtml(e.message),
        tid: e.task_id || undefined,
      }))
      logs.value = [...mapped.reverse(), ...logs.value].slice(0, 50)
    }
    lastEventId = page.next_after_id
  } catch {
    // 事件轮询失败不打断页面，等待下一轮
  }
}

async function liveTick() {
  pollRound++
  await pollLiveEvents()
  if (pollRound % 2 === 0) await loadLiveAll()
}

/* ─── 任务编排时间线（甘特）：先评后压父子关联、运行中条形随时间延展 ─── */
const ganttLegend = [
  { label: '排队', color: '#9CA3AF' },
  { label: '运行中', color: 'var(--accent-ai)' },
  { label: '待确认', color: 'var(--accent-warning)' },
  { label: '成功', color: 'var(--accent-success)' },
  { label: '失败/取消', color: 'var(--accent-error)' },
]

// 甘特行：live 取近期任务；mock 取运行中队列项 + 已完成历史
const ganttBase = computed<Omit<GanttRow, 'left' | 'width'>[]>(() => {
  if (liveMode) {
    return liveRecentTasks.value.map(t => {
      const active = ['queued', 'running', 'awaiting_case_confirm'].includes(t.status)
      return {
        id: t.id,
        shortId: t.id.substring(0, 8),
        kind: t.kind,
        label: taskLabel(t),
        status: t.status,
        start: +new Date(t.created_at),
        end: active ? nowTs.value : +new Date(t.updated_at || t.created_at),
        parentId: t.parent_task_id || t.config?.parent_task_id || null,
        isChild: !!(t.parent_task_id || t.config?.parent_task_id),
      }
    })
  }
  const running: Omit<GanttRow, 'left' | 'width'>[] = queue.value
    .filter(q => q.workerId && q.startedAt)
    .map(q => ({
      id: q.qid, shortId: q.qid, kind: q.kind, label: q.label, status: 'running' as TaskStatus,
      start: q.startedAt!, end: nowTs.value, parentId: q.parentId || null, isChild: !!q.parentId,
    }))
  return [...running, ...mockGanttDone.value].slice(0, 12)
})

// 父子分组排序：父任务在前，派生压测紧随其后
const ganttRows = computed<GanttRow[]>(() => {
  const rows = [...ganttBase.value]
  if (!rows.length) return []
  const minStart = Math.min(...rows.map(r => r.start))
  const maxEnd = Math.max(nowTs.value, ...rows.map(r => r.end))
  const span = Math.max(maxEnd - minStart, 60_000)
  const positioned = rows.map(r => ({
    ...r,
    left: Math.max(0, ((r.start - minStart) / span) * 100),
    width: Math.max(1.5, ((Math.max(r.end, r.start + 800) - r.start) / span) * 100),
  }))
  // 父任务（含派生子任务的）优先，子任务紧跟其父
  const ids = new Set(positioned.map(r => r.id))
  const parents = positioned.filter(r => !r.isChild || !ids.has(r.parentId || ''))
  const children = positioned.filter(r => r.isChild && ids.has(r.parentId || ''))
  const ordered: GanttRow[] = []
  parents.sort((a, b) => a.start - b.start).forEach(p => {
    ordered.push(p)
    children.filter(c => c.parentId === p.id).forEach(c => ordered.push(c))
  })
  return ordered
})

// 时间轴刻度（起止 + 两个中间点）
const ganttTicks = computed(() => {
  const rows = ganttRows.value
  if (!rows.length) return []
  const minStart = Math.min(...rows.map(r => r.start))
  const maxEnd = Math.max(nowTs.value, ...rows.map(r => r.end))
  return [0, 1 / 3, 2 / 3, 1].map(p => fmtTime(minStart + (maxEnd - minStart) * p))
})

function fmtTime(ts: number): string {
  const d = new Date(ts)
  return `${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}:${String(d.getSeconds()).padStart(2, '0')}`
}

function statusLabel(s: string): string {
  const map: Record<string, string> = {
    queued: '排队',
    running: '运行中',
    awaiting_case_confirm: '待确认',
    succeeded: '已成功',
    failed: '已失败',
    cancelled: '已取消',
  }
  return map[s] || s
}

// 调度心跳
let timer: any = null
let dispatchTimer: any = null
let nowTimer: any = null
/** 分发模拟的延时句柄登记：组件卸载时统一清理，避免回调写入已销毁状态 */
const assignTimers = new Set<number>()
/** 刷新容器尺寸缓存：锁定卡定位换算依据 */
function syncWrapSize() {
  const el = wrapRef.value
  if (el) wrapSize.value = { w: el.clientWidth, h: el.clientHeight }
}

onMounted(async () => {
  // 滚轮缩放需 preventDefault，必须以非 passive 方式注册
  svgRef.value?.addEventListener('wheel', onWheel, { passive: false })
  window.addEventListener('resize', syncWrapSize)
  window.addEventListener('keydown', onKeydown)
  syncWrapSize()
  // 甘特时间游标：运行中条形每秒延展
  nowTimer = window.setInterval(() => { nowTs.value = Date.now() }, 1000)
  if (liveMode) {
    // 真实模式：首屏全量加载后按 3s 节拍轮询事件，6s 全量刷新，不启动本地仿真
    await loadLiveAll()
    await pollLiveEvents()
    handleRouteTaskFocus()
    pollTimer = window.setInterval(liveTick, 3000)
    return
  }
  handleRouteTaskFocus()
  timer = setInterval(() => {
    if (!isRunning.value) return
    // 随机微调负载
    workerPool.value.forEach(w => {
      if (w.state === 'busy') {
        w.load = Math.max(10, Math.min(96, w.load + (Math.random() < 0.5 ? -2 : 2)))
      }
    })
  }, 2000)

  dispatchTimer = setInterval(dispatchTick, 2600)
})

// 监听路由参数变化（如由任务中心跳转过来时）
watch(() => route.query.task_id || route.query.highlight_task, () => {
  handleRouteTaskFocus()
})

onBeforeUnmount(() => {
  if (timer) clearInterval(timer)
  if (dispatchTimer) clearInterval(dispatchTimer)
  if (nowTimer) clearInterval(nowTimer)
  if (pollTimer !== null) window.clearInterval(pollTimer)
  assignTimers.forEach(id => { window.clearTimeout(id); window.clearInterval(id) })
  assignTimers.clear()
  window.clearTimeout(flashTimer)
  svgRef.value?.removeEventListener('wheel', onWheel)
  window.removeEventListener('resize', syncWrapSize)
  window.removeEventListener('keydown', onKeydown)
})
</script>

<style scoped>
/* ═══ 沉浸式调度星图画布与悬浮控制坞 ═══ */
.immersive-monitor-panel {
  overflow: hidden;
  border-radius: 14px;
}
.immersive-topo-wrap {
  position: relative;
  border: 1px solid var(--border-subtle);
  border-radius: 12px;
  overflow: hidden;
  height: calc(100vh - 270px);
  min-height: 740px;
  background:
    radial-gradient(60% 55% at 50% 48%, color-mix(in srgb, var(--accent-ai) 6%, transparent), transparent 70%),
    var(--bg-elevated);
}
.topo-svg {
  width: 100%;
  height: 100%;
  display: block;
  user-select: none;
  touch-action: none;
  cursor: grab;
}
.topo-svg:active {
  cursor: grabbing;
}
.topo-bg {
  fill: url(#topo-grid);
}
.grid-line {
  fill: none;
  stroke: var(--text-tertiary);
  stroke-width: 0.5;
  opacity: 0.14;
}

/* 扫描线装饰 */
.scanline {
  position: absolute;
  left: 0;
  right: 0;
  top: 0;
  height: 140px;
  pointer-events: none;
  background: linear-gradient(180deg, transparent, color-mix(in srgb, var(--accent-ai) 5%, transparent), transparent);
  animation: scan-sweep 8s linear infinite;
}
@keyframes scan-sweep {
  from { transform: translateY(-160px); }
  to { transform: translateY(1100px); }
}

/* 业务扇区底色楔块 */
.sector-wedge {
  opacity: 0.05;
  transition: opacity 0.3s ease;
}
.sector-wedge.dim {
  opacity: 0.015;
}

/* 轨道参考线 */
.orbit-guide {
  fill: none;
  stroke: var(--text-tertiary);
  stroke-width: 0.8;
  stroke-dasharray: 2 7;
  opacity: 0.28;
}
.orbit-guide.outer {
  opacity: 0.18;
}

/* 常驻链路：内核 → 技能 */
.wire-core {
  fill: none;
  stroke: var(--text-tertiary);
  stroke-width: 1.4;
  stroke-dasharray: 4 6;
  opacity: 0.5;
  animation: dash-flow 2.6s linear infinite;
  transition: opacity 0.3s ease;
}
/* 归属链路：技能 → Worker */
.wire-member {
  fill: none;
  stroke: var(--text-tertiary);
  stroke-width: 0.9;
  opacity: 0.3;
  transition: opacity 0.3s ease;
}
/* 执行链路：高亮流动 */
.wire-live {
  fill: none;
  stroke: var(--accent-ai);
  stroke-width: 1.8;
  stroke-dasharray: 6 5;
  opacity: 0.85;
  animation: dash-flow 0.9s linear infinite;
  filter: drop-shadow(0 0 3px color-mix(in srgb, var(--accent-ai) 55%, transparent));
  transition: opacity 0.3s ease;
}
.wire-core.dim,
.wire-member.dim,
.wire-live.dim {
  opacity: 0.08;
}
/* 数据流粒子 */
.particle {
  fill: var(--accent-ai);
  filter: drop-shadow(0 0 3px color-mix(in srgb, var(--accent-ai) 80%, transparent));
}

/* 悬浮控制坞通用体系 (Floating Glass Docks) */
.floating-dock {
  position: absolute;
  z-index: 20;
  background: rgba(var(--bg-main-rgb, 17, 24, 39), 0.92);
  backdrop-filter: blur(16px);
  -webkit-backdrop-filter: blur(16px);
  border: 1px solid var(--border-subtle);
  border-radius: 12px;
  box-shadow: 0 8px 32px rgba(0, 0, 0, 0.18);
  transition: all 0.28s cubic-bezier(0.4, 0, 0.2, 1);
  display: flex;
  flex-direction: column;
}

.dock-header {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 12px;
  border-bottom: 1px solid var(--border-subtle);
  user-select: none;
  flex-shrink: 0;
}

.dock-header-title {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 12px;
  color: var(--text-primary);
}

.dock-ico {
  font-size: 14px;
}

.dock-toggle-btn {
  border: none;
  background: var(--bg-elevated);
  color: var(--text-secondary);
  font-size: 11px;
  padding: 2px 6px;
  border-radius: 4px;
  cursor: pointer;
  transition: all 0.15s;
}
.dock-toggle-btn:hover {
  background: var(--accent-ai);
  color: #fff;
}

.dock-scroll-content {
  padding: 10px;
  overflow-y: auto;
  flex: 1;
  max-height: calc(100vh - 360px);
}

.dock-card {
  background: var(--bg-main);
  border: 1px solid var(--border-subtle);
  border-radius: 8px;
  padding: 8px 10px;
}

.dock-card-title {
  display: flex;
  align-items: center;
  justify-content: space-between;
  font-size: 11.5px;
  font-weight: 600;
  margin-bottom: 6px;
}

/* 左侧浮坞 (Dock Left) */
.dock-left {
  top: 14px;
  left: 14px;
  width: 290px;
}
.dock-left.collapsed {
  width: 44px;
  overflow: hidden;
}
.dock-left.collapsed .dock-header {
  padding: 8px 6px;
  justify-content: center;
}

/* 右侧浮坞 (Dock Right) */
.dock-right {
  top: 14px;
  right: 14px;
  width: 320px;
}
.dock-right.collapsed {
  width: 44px;
  overflow: hidden;
}
.dock-right.collapsed .dock-header {
  padding: 8px 6px;
  justify-content: center;
}

/* 底部甘特浮坞 (Dock Bottom) */
.dock-bottom {
  bottom: 14px;
  left: 14px;
  right: 14px;
  max-height: 240px;
}
.dock-bottom.collapsed {
  max-height: 38px;
  overflow: hidden;
}
.dock-bottom-header {
  cursor: pointer;
  padding: 6px 12px;
}
.dock-bottom-content {
  padding: 8px 12px;
  overflow-y: auto;
  max-height: 180px;
}

/* 调度内核核心指标快览 */
.kernel-metric-row {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 6px;
  background: var(--bg-elevated);
  padding: 6px 8px;
  border-radius: 6px;
  border: 1px solid var(--border-subtle);
}
.k-stat {
  display: flex;
  flex-direction: column;
  align-items: center;
  text-align: center;
  gap: 2px;
}
.k-label {
  font-size: 9.5px;
}
.k-val {
  font-size: 11.5px;
}

/* Worker 专精集群卡片列表 */
.worker-card-list {
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.worker-rich-card {
  background: var(--bg-elevated);
  border: 1px solid var(--border-subtle);
  border-radius: 6px;
  padding: 6px 8px;
  cursor: pointer;
  transition: all 0.15s ease;
}
.worker-rich-card:hover {
  border-color: var(--accent-ai);
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.06);
}
.worker-rich-card.busy {
  border-color: color-mix(in srgb, var(--accent-ai) 40%, var(--border-subtle));
}
.worker-rich-card.offline {
  opacity: 0.55;
}
.wrc-head {
  display: flex;
  align-items: center;
  gap: 5px;
  margin-bottom: 3px;
}
.wrc-dot {
  width: 5px;
  height: 5px;
  border-radius: 50%;
  background: var(--text-tertiary);
}
.wrc-dot.idle { background: var(--accent-success); }
.wrc-dot.busy { background: var(--accent-ai); animation: dot-breathe 1.4s ease-in-out infinite; }
.wrc-dot.draining { background: var(--accent-warning); }
.wrc-name {
  font-size: 11px;
  color: var(--text-primary);
}
.wrc-state-tag {
  margin-left: auto;
  font-size: 9px;
  padding: 0 4px;
  border-radius: 3px;
  background: var(--bg-main);
  border: 1px solid var(--border-subtle);
  color: var(--text-secondary);
}
.wrc-state-tag.idle { color: var(--accent-success); }
.wrc-state-tag.busy { color: var(--accent-ai); }
.wrc-body {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 6px;
}
.wrc-caps {
  display: flex;
  gap: 3px;
  flex-wrap: wrap;
}
.cap-tag {
  font-size: 8.5px;
  font-family: var(--font-mono);
  background: var(--bg-main);
  border: 1px solid var(--border-subtle);
  padding: 0 3px;
  border-radius: 2px;
  color: var(--text-tertiary);
}
.wrc-load-wrap {
  display: flex;
  align-items: center;
  gap: 4px;
  flex-shrink: 0;
}
.wrc-load-text {
  font-size: 9.5px;
  color: var(--text-secondary);
}
.wrc-load-bar {
  width: 32px;
  height: 3.5px;
  background: var(--bg-main);
  border-radius: 2px;
  overflow: hidden;
}
.wrc-load-fill {
  height: 100%;
  transition: width 0.3s;
}

/* 结构化日志卡片 */
.log-card-item {
  background: var(--bg-elevated);
  border: 1px solid var(--border-subtle);
  border-radius: 6px;
  padding: 6px 8px;
  margin-bottom: 5px;
  transition: background 0.15s ease;
}
.log-card-item.clickable {
  cursor: pointer;
}
.log-card-item.clickable:hover {
  border-color: var(--accent-ai);
  background: var(--row-hover);
}
.lci-head {
  display: flex;
  align-items: center;
  gap: 5px;
  margin-bottom: 2px;
}
.lci-time {
  font-size: 9.5px;
  color: var(--text-tertiary);
}
.lci-tag {
  font-size: 9px;
  padding: 0 4px;
  border-radius: 3px;
  font-weight: 600;
  background: var(--bg-main);
  border: 1px solid var(--border-subtle);
}
.lci-tag.done { color: var(--accent-success); border-color: color-mix(in srgb, var(--accent-success) 30%, transparent); }
.lci-tag.error { color: var(--accent-error); border-color: color-mix(in srgb, var(--accent-error) 30%, transparent); }
.lci-tag.node { color: var(--text-secondary); }
.lci-tid {
  font-size: 9px;
  color: var(--accent-ai);
  margin-left: auto;
}
.lci-body {
  font-size: 10.5px;
  line-height: 1.35;
  color: var(--text-primary);
}

/* ─── 星图节点体系 ─── */
.task-chip,
.skill-node,
.worker-node {
  transition: opacity 0.3s ease;
}
.task-chip.dim,
.skill-node.dim,
.worker-node.dim {
  opacity: 0.18;
}

.task-chip {
  cursor: pointer;
  transition:
    transform 0.75s cubic-bezier(0.2, 0.9, 0.3, 1),
    opacity 0.3s ease;
}
.tc-box {
  fill: var(--bg-main);
  stroke: var(--border-subtle);
  stroke-width: 1;
  filter: drop-shadow(0 2px 5px rgba(17, 24, 39, 0.10));
  transition: stroke 0.2s ease;
}
.task-chip:hover .tc-box {
  stroke: var(--accent-ai);
}
.task-chip.queued .tc-box {
  stroke-dasharray: 4 3;
}
.task-chip.running .tc-box {
  stroke: color-mix(in srgb, var(--accent-ai) 55%, var(--border-subtle));
  filter: drop-shadow(0 0 6px color-mix(in srgb, var(--accent-ai) 30%, transparent));
}
.task-chip.flash .tc-box {
  animation: chip-flash 0.8s ease-in-out 2;
}
@keyframes chip-flash {
  0%, 100% { stroke: var(--border-subtle); }
  50% { stroke: var(--accent-ai); stroke-width: 2.4; }
}
.task-chip.pinned .tc-box {
  stroke: var(--accent-ai);
  stroke-width: 2;
  stroke-dasharray: none;
  filter: drop-shadow(0 0 8px color-mix(in srgb, var(--accent-ai) 45%, transparent));
}
.tc-dot {
  fill: var(--text-tertiary);
}
.tc-dot.running {
  fill: var(--accent-ai);
  animation: dot-breathe 1.4s ease-in-out infinite;
}
.tc-dot.awaiting_case_confirm {
  fill: var(--accent-warning);
}
.tc-id {
  font-family: var(--font-mono);
  font-size: 10px;
  fill: var(--text-secondary);
}
.tc-status {
  font-size: 9px;
  fill: var(--text-tertiary);
}
.tc-label {
  font-size: 10.5px;
  font-weight: 500;
  fill: var(--text-primary);
}
.tc-progress-bg {
  fill: var(--bg-elevated);
}
.tc-progress {
  fill: var(--accent-ai);
  transition: width 0.4s ease;
}

/* 技能 Agent 内环节点 */
.skill-node {
  cursor: pointer;
}
.sn-halo {
  fill: var(--sk, var(--accent-ai));
  opacity: 0.10;
  transition: opacity 0.25s ease, r 0.25s ease;
}
.skill-node.on .sn-halo {
  opacity: 0.22;
  animation: halo-breathe 2.2s ease-in-out infinite;
}
@keyframes halo-breathe {
  0%, 100% { opacity: 0.14; }
  50% { opacity: 0.28; }
}
.sn-core {
  fill: var(--bg-main);
  stroke: var(--sk, var(--border-subtle));
  stroke-width: 1.6;
  filter: drop-shadow(0 2px 6px rgba(17, 24, 39, 0.10));
  transition: stroke-width 0.2s ease;
}
.skill-node:hover .sn-core,
.skill-node.on .sn-core {
  stroke-width: 2.4;
}
.sn-ico {
  font-size: 17px;
}
.sn-name {
  font-size: 11.5px;
  font-weight: 600;
  fill: var(--text-primary);
}
.sn-count {
  font-size: 9.5px;
  fill: var(--text-tertiary);
  font-family: var(--font-mono);
}

/* Worker 外环节点 */
.worker-node {
  cursor: pointer;
}
.wn-ring-bg {
  fill: none;
  stroke: var(--border-subtle);
  stroke-width: 3;
  opacity: 0.6;
}
.wn-load {
  fill: none;
  stroke: var(--accent-ai);
  stroke-width: 3;
  stroke-linecap: round;
  transition: stroke-dasharray 0.6s cubic-bezier(0.2, 0.9, 0.3, 1);
}
.wn-load.hot {
  stroke: var(--accent-warning);
}
.wn-core {
  fill: var(--bg-main);
  stroke: var(--border-subtle);
  stroke-width: 1;
  transition: stroke 0.2s ease;
}
.worker-node:hover .wn-core {
  stroke: var(--accent-ai);
}
.worker-node.busy .wn-core {
  stroke: color-mix(in srgb, var(--accent-ai) 55%, var(--border-subtle));
  filter: drop-shadow(0 0 5px color-mix(in srgb, var(--accent-ai) 35%, transparent));
}
.worker-node.offline {
  opacity: 0.4;
}
.wn-pct {
  font-size: 9.5px;
  font-weight: 600;
  fill: var(--text-primary);
  font-family: var(--font-mono);
}
.wn-id {
  font-size: 9.5px;
  fill: var(--text-secondary);
  font-family: var(--font-mono);
}
.wn-dot {
  fill: var(--text-tertiary);
  stroke: var(--bg-main);
  stroke-width: 1.4;
}
.wn-dot.idle { fill: var(--accent-success); }
.wn-dot.busy { fill: var(--accent-ai); animation: dot-breathe 1.4s ease-in-out infinite; }
.wn-dot.draining { fill: var(--accent-warning); }

/* 中心调度内核 */
.core-ring {
  fill: none;
  stroke: var(--accent-ai);
  stroke-width: 1.2;
  stroke-dasharray: 10 14;
  opacity: 0.55;
}
.core-ring2 {
  fill: none;
  stroke: var(--accent-ai);
  stroke-width: 1;
  stroke-dasharray: 3 9;
  opacity: 0.4;
}
.spin-a {
  animation: core-spin 26s linear infinite;
  transform-box: fill-box;
  transform-origin: center;
}
.spin-b {
  animation: core-spin 18s linear infinite reverse;
  transform-box: fill-box;
  transform-origin: center;
}
@keyframes core-spin {
  to { transform: rotate(360deg); }
}
.core-sweep {
  animation: core-spin 5s linear infinite;
  transform-box: fill-box;
  transform-origin: center;
}
.core-center {
  fill: var(--bg-main);
  stroke: var(--accent-ai);
  stroke-width: 1.8;
  filter: drop-shadow(0 0 10px color-mix(in srgb, var(--accent-ai) 40%, transparent));
}
.core-center.halt {
  stroke: var(--text-tertiary);
  filter: none;
}
.core-ico {
  font-size: 15px;
}
.core-status {
  font-size: 8.5px;
  font-weight: 700;
  letter-spacing: 0.12em;
  fill: var(--accent-ai);
  font-family: var(--font-mono);
}
.core-name {
  font-size: 12px;
  font-weight: 600;
  fill: var(--text-primary);
}

/* 完成涟漪 */
.ripple-c {
  fill: none;
  stroke: var(--accent-success);
  stroke-width: 2.5;
  pointer-events: none;
  animation: ripple-svg 1.1s ease-out forwards;
  transform-box: fill-box;
  transform-origin: center;
}
@keyframes ripple-svg {
  0% { transform: scale(0.6); opacity: 0.95; }
  100% { transform: scale(4.2); opacity: 0; }
}

/* 悬停 tooltip */
.topo-tip {
  position: absolute;
  z-index: 25;
  min-width: 180px;
  max-width: 250px;
  padding: 10px 12px;
  border-radius: 10px;
  border: 1px solid var(--border-subtle);
  background: var(--bg-main);
  box-shadow: 0 8px 24px rgba(17, 24, 39, 0.14);
  pointer-events: none;
  font-size: 11.5px;
}
.tt-title {
  font-weight: 600;
  font-size: 12px;
  margin-bottom: 6px;
}
.tt-line {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  line-height: 1.8;
}
.tt-val {
  text-align: right;
  word-break: break-all;
}

/* 工单锁定详情卡 */
.pin-card {
  position: absolute;
  z-index: 25;
  width: 228px;
  padding: 10px 12px;
  border-radius: 10px;
  border: 1px solid color-mix(in srgb, var(--accent-ai) 40%, var(--border-subtle));
  background: var(--bg-main);
  box-shadow: 0 10px 28px rgba(17, 24, 39, 0.18), 0 0 0 1px color-mix(in srgb, var(--accent-ai) 14%, transparent);
  font-size: 11.5px;
  animation: pin-in 0.18s ease;
}
@keyframes pin-in {
  from { opacity: 0; transform: translateY(4px) scale(0.97); }
  to { opacity: 1; transform: none; }
}
.pc-head {
  display: flex;
  align-items: center;
  gap: 6px;
}
.pc-bar {
  width: 3.5px;
  height: 14px;
  border-radius: 2px;
  flex: 0 0 3.5px;
}
.pc-id {
  font-weight: 700;
  font-size: 11.5px;
}
.pc-close {
  border: none;
  background: transparent;
  color: var(--text-tertiary);
  font-size: 14px;
  line-height: 1;
  cursor: pointer;
  padding: 2px 4px;
  border-radius: 4px;
}
.pc-close:hover {
  background: var(--row-hover);
  color: var(--text-primary);
}
.pc-label {
  margin-top: 6px;
  font-weight: 500;
  line-height: 1.45;
  word-break: break-all;
}
.pc-progress {
  margin-top: 6px;
  height: 4px;
  border-radius: 999px;
  background: var(--bg-elevated);
  overflow: hidden;
}
.pc-progress > i {
  display: block;
  height: 100%;
  border-radius: 999px;
  background: repeating-linear-gradient(45deg, var(--accent-ai) 0 8px, color-mix(in srgb, var(--accent-ai) 55%, #fff) 8px 16px);
  background-size: 23px 100%;
  animation: bar-stripes 0.9s linear infinite;
  transition: width 0.4s ease;
}
.pc-lines {
  margin-top: 6px;
}

/* 甘特图 */
.gantt {
  display: flex;
  flex-direction: column;
  gap: 5px;
}
.gantt-axis {
  display: flex;
  justify-content: space-between;
  font-size: 9.5px;
  color: var(--text-tertiary);
  padding: 0 4px 2px 160px;
}
.gantt-row {
  display: grid;
  grid-template-columns: 160px 1fr;
  align-items: center;
  gap: 8px;
  padding: 2px 4px;
  border-radius: 5px;
  cursor: pointer;
  transition: background 0.15s ease;
}
.gantt-row:hover {
  background: var(--row-hover);
}
.gantt-row.child .gantt-name {
  padding-left: 10px;
}
.gantt-name {
  display: flex;
  align-items: center;
  gap: 5px;
  min-width: 0;
  overflow: hidden;
  white-space: nowrap;
}
.gantt-tid {
  color: var(--text-secondary);
}
.gantt-track {
  position: relative;
  height: 16px;
  border-radius: 4px;
  background: var(--bg-elevated);
  overflow: hidden;
  border: 1px solid var(--border-subtle);
}
.gantt-bar {
  position: absolute;
  top: 1px;
  bottom: 1px;
  border-radius: 3px;
  display: flex;
  align-items: center;
  padding-left: 5px;
  transition: left 0.6s ease, width 0.6s ease;
}
.gantt-bar-text {
  font-size: 8.5px;
  font-weight: 600;
  color: #fff;
  white-space: nowrap;
  text-shadow: 0 1px 2px rgba(0, 0, 0, 0.4);
}
.gantt-bar.st-queued { background: #9ca3af; }
.gantt-bar.st-running {
  background: repeating-linear-gradient(45deg, var(--accent-ai) 0 8px, color-mix(in srgb, var(--accent-ai) 55%, #fff) 8px 16px);
  background-size: 23px 100%;
  animation: bar-stripes 0.9s linear infinite;
}
@keyframes bar-stripes {
  to { background-position: 23px 0; }
}
.gantt-bar.st-awaiting_case_confirm { background: var(--accent-warning); }
.gantt-bar.st-succeeded { background: var(--accent-success); }
.gantt-bar.st-failed,
.gantt-bar.st-cancelled { background: var(--accent-error); opacity: 0.75; }
.gantt-dot {
  display: inline-block;
  width: 7px;
  height: 7px;
  border-radius: 2px;
}

/* 图例 */
.legend-line {
  display: inline-block;
  width: 18px;
  height: 2px;
  border-radius: 2px;
}
.legend-dot {
  display: inline-block;
  width: 7px;
  height: 7px;
  border-radius: 50%;
}

/* 顶部模式分段选择器样式 */
.dispatch-view-tabs {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  flex-wrap: wrap;
}

.tab-pill-group {
  display: inline-flex;
  background: var(--bg-elevated);
  padding: 4px;
  border-radius: 10px;
  border: 1px solid var(--border-subtle);
  gap: 4px;
}

.tab-pill-btn {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 6px 14px;
  border-radius: 7px;
  border: none;
  background: transparent;
  font-size: 13px;
  font-weight: 500;
  color: var(--text-secondary);
  cursor: pointer;
  transition: all 0.18s cubic-bezier(0.4, 0, 0.2, 1);
}

.tab-pill-btn:hover {
  color: var(--text-primary);
}

.tab-pill-btn.active {
  background: var(--bg-main);
  color: var(--text-primary);
  font-weight: 600;
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.08);
}

.tab-icon {
  font-size: 14px;
}

.tab-badge {
  font-size: 10px;
  font-weight: 600;
  padding: 1px 5px;
  border-radius: 4px;
  background: var(--accent-ai);
  color: #ffffff;
  line-height: 1.3;
}
</style>
