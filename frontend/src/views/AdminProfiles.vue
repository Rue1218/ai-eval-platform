<template>
  <div class="profiles-page">
    <!-- 4 Tab 架构（API V1.3 §3.6：协议档 / MCP 工具只读 / 技能受控说明 / 运行时治理） -->
    <div class="row" style="gap: 8px">
      <button
        v-for="t in tabs"
        :key="t.key"
        class="profile-tab-btn"
        :class="{ active: activeTab === t.key }"
        @click="switchTab(t.key)"
      >
        {{ t.label }}
      </button>
    </div>

    <template v-if="activeTab === 'profiles'">
    <!-- 顶部指定 Agent 后端设置 -->
    <div class="panel mb16">
      <div class="panel-title">智能体后台模型配置 (Agent Backend)</div>
      <div class="row" style="gap: 16px">
        <div style="font-size: 13px; color: var(--text-secondary)">
          指定系统唯一的 Agent 决策后台协议档：
        </div>
        <n-select
          v-model:value="selectedAgentProfileId"
          style="width: 260px"
          :options="agentProfileOptions"
          @update:value="handleUpdateAgentProfile"
        />
        <span class="mono" style="font-size: 12px; color: var(--text-tertiary)">
          (保存即刻全局生效)
        </span>
      </div>
    </div>

    <!-- 协议档列表 -->
    <div class="panel">
      <div class="panel-title">
        <div class="row" style="gap: 12px">
          <span>大模型协议档与供应商管理</span>
          <span class="mono" style="font-size: 12px; color: var(--text-tertiary)">({{ profiles.length }} 个模型)</span>

          <!-- 视图模式切换器 -->
          <div class="view-mode-toggle">
            <button
              class="toggle-btn"
              :class="{ active: viewMode === 'cards' }"
              @click="viewMode = 'cards'"
            >
              📇 供应商卡片视图
            </button>
            <button
              class="toggle-btn"
              :class="{ active: viewMode === 'table' }"
              @click="viewMode = 'table'"
            >
              📑 详细表格视图
            </button>
          </div>
        </div>

        <div class="row">
          <button class="btn btn-primary btn-sm" @click="openModal(null)">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
              <line x1="12" y1="5" x2="12" y2="19"></line>
              <line x1="5" y1="12" x2="19" y2="12"></line>
            </svg>
            <span>新增协议档</span>
          </button>

          <button class="btn btn-secondary btn-sm" :disabled="loading" @click="loadProfiles">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
              <polyline points="23 4 23 10 17 10"></polyline>
              <polyline points="1 20 1 14 7 14"></polyline>
              <path d="M3.51 9a9 9 0 0 1 14.85-3.36L23 10M1 14l4.64 4.36A9 9 0 0 0 20.49 15"></path>
            </svg>
            <span>刷新</span>
          </button>
        </div>
      </div>

      <!-- 模式 1：供应商分类多卡片视图 -->
      <div v-if="viewMode === 'cards'" class="vendor-cards-container">
        <div
          v-for="group in vendorGroups"
          :key="group.key"
          class="vendor-group-card"
        >
          <div class="vendor-group-header">
            <div class="vendor-info">
              <div class="vendor-title-row">
                <span class="vendor-badge">{{ group.icon }}</span>
                <span class="vendor-name">{{ group.name }}</span>
                <span class="vendor-count-badge">{{ group.profiles.length }} 个模型</span>
              </div>
              <div class="vendor-url mono">{{ group.base_url }}</div>
            </div>
            <div class="vendor-actions">
              <button
                class="btn btn-secondary btn-xs"
                @click="openModalWithVendor(group)"
              >
                + 添加此供应商模型
              </button>
            </div>
          </div>

          <!-- 模型卡片列表 -->
          <div class="vendor-models-grid">
            <div
              v-for="p in group.profiles"
              :key="p.id"
              class="model-chip-card"
              :class="{ 'is-agent-core': p.id === selectedAgentProfileId }"
            >
              <div class="model-chip-top">
                <div class="model-chip-title-wrap">
                  <span class="model-chip-name">{{ p.name }}</span>
                  <span v-if="p.id === selectedAgentProfileId" class="tag-soft agent-core-tag">★ Agent 核心</span>
                </div>
                <!-- 探活胶囊 -->
                <span
                  v-if="pingStates[p.id]"
                  class="ping-badge"
                  :class="pingStates[p.id].ok ? 'ok' : 'err'"
                  title="点击重新探活"
                  @click="handlePing(p)"
                >
                  {{ pingStates[p.id].ok ? `● 正常 (${pingStates[p.id].latencyMs ?? '—'}ms)` : '✕ 连接失败' }}
                </span>
                <button v-else class="link-btn small" :disabled="pingingId === p.id" @click="handlePing(p)">
                  {{ pingingId === p.id ? '探活中…' : '探活' }}
                </button>
              </div>

              <div class="model-chip-meta">
                <span class="mono model-id-tag">{{ p.model }}</span>
                <span
                  v-if="p.embedding_model"
                  class="mono model-id-tag tag-embed tag-clickable"
                  title="点击查看/配置 Embedding 向量模型"
                  @click.stop="openModal(p, 'embedding')"
                >
                  🔤 E: {{ p.embedding_model }}
                </span>
                <span
                  v-if="p.reranker_model"
                  class="mono model-id-tag tag-rerank tag-clickable"
                  title="点击查看/配置 Reranker 重排模型"
                  @click.stop="openModal(p, 'reranker')"
                >
                  🎯 R: {{ p.reranker_model }}
                </span>
                <span class="mono protocol-tag">{{ p.protocol }}</span>
                <span class="mono window-tag" title="上下文窗口容量">{{ formatContextWindow(p.context_window) }}</span>
              </div>

              <div class="model-chip-bottom">
                <div class="row" style="gap: 4px; flex-wrap: wrap">
                  <span v-if="p.usages?.includes('target')" class="kind-tag kind-benchmark">被测</span>
                  <span v-if="p.usages?.includes('judge')" class="kind-tag kind-cases">裁判</span>
                  <span v-if="p.usages?.includes('agent')" class="kind-tag kind-rag">Agent</span>
                </div>
                <div class="row" style="gap: 6px">
                  <button class="link-btn small" @click="openModal(p)">编辑</button>
                  <button
                    class="link-btn danger small"
                    :disabled="p.id === selectedAgentProfileId"
                    :title="p.id === selectedAgentProfileId ? '当前档已被指定为 Agent 后端，禁止删除' : ''"
                    @click="handleDelete(p)"
                  >
                    删除
                  </button>
                </div>
              </div>
            </div>
          </div>
        </div>

        <div v-if="profiles.length === 0" class="empty-state-wrap">
          <EmptyState title="暂无模型协议档" description="点击右上角新增 OpenAI / Anthropic / Xiaomi Mimo 协议档">
            <template #action>
              <button class="btn btn-primary btn-sm" @click="openModal(null)">新增协议档</button>
            </template>
          </EmptyState>
        </div>
      </div>

      <!-- 模式 2：详细表格视图 -->
      <table v-else class="ds-table">
        <thead>
          <tr>
            <th>协议档名称</th>
            <th style="width: 160px">协议类型</th>
            <th style="width: 140px">模型标识</th>
            <th style="width: 100px">上下文窗口</th>
            <th>Base URL</th>
            <th style="width: 140px">用途标签</th>
            <!-- P2 连通性探活列（对齐原型 admin-profiles.html：行内 ping-badge） -->
            <th style="width: 130px">探活</th>
            <th style="width: 200px; text-align: right">操作</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="p in profiles" :key="p.id">
            <td style="font-weight: 600; font-size: 14px">
              <span class="row" style="gap: 6px">
                <span>{{ p.name }}</span>
                <!-- P4 名称徽标对齐原型「★ Agent 核心驱动」 -->
                <span v-if="p.id === selectedAgentProfileId" class="tag-soft agent-core-tag">★ Agent 核心驱动</span>
              </span>
            </td>
            <td>
              <span class="mono" style="font-size: 12px">{{ p.protocol }}</span>
            </td>
            <td>
              <div class="row" style="gap: 4px; flex-wrap: wrap">
                <span class="mono" style="font-size: 12px; font-weight: 500">{{ p.model }}</span>
                <span
                  v-if="p.embedding_model"
                  class="mono model-id-tag tag-embed tag-clickable"
                  style="font-size: 11px"
                  title="点击查看/配置 Embedding 向量模型"
                  @click.stop="openModal(p, 'embedding')"
                >
                  🔤 E: {{ p.embedding_model }}
                </span>
                <span
                  v-if="p.reranker_model"
                  class="mono model-id-tag tag-rerank tag-clickable"
                  style="font-size: 11px"
                  title="点击查看/配置 Reranker 重排模型"
                  @click.stop="openModal(p, 'reranker')"
                >
                  🎯 R: {{ p.reranker_model }}
                </span>
              </div>
            </td>
            <td>
              <span class="mono window-tag">{{ formatContextWindow(p.context_window) }}</span>
            </td>
            <td>
              <span class="mono" style="font-size: 11.5px; color: var(--text-secondary)">{{ p.base_url }}</span>
            </td>
            <td>
              <div class="row" style="gap: 4px; flex-wrap: wrap">
                <span v-if="p.usages?.includes('target')" class="kind-tag kind-benchmark">被测</span>
                <span v-if="p.usages?.includes('judge')" class="kind-tag kind-cases">裁判</span>
                <span v-if="p.usages?.includes('agent')" class="kind-tag kind-rag">Agent</span>
              </div>
            </td>
            <td>
              <!-- P2 探活胶囊：点击原位刷新（复用 api.profiles.check），不弹窗 -->
              <span
                v-if="pingStates[p.id]"
                class="ping-badge"
                :class="pingStates[p.id].ok ? 'ok' : 'err'"
                title="点击重新探活"
                @click="handlePing(p)"
              >
                {{ pingStates[p.id].ok ? `● 正常 (${pingStates[p.id].latencyMs ?? '—'}ms)` : '✕ 连接失败' }}
              </span>
              <button v-else class="link-btn" :disabled="pingingId === p.id" @click="handlePing(p)">
                {{ pingingId === p.id ? '探活中…' : '探活' }}
              </button>
            </td>
            <td style="text-align: right">
              <div class="row" style="justify-content: flex-end; gap: 4px">
                <button class="link-btn" :disabled="checkingId === p.id" @click="handleCheck(p)">
                  {{ checkingId === p.id ? '检查中...' : '连通详情' }}
                </button>
                <button class="link-btn" @click="openModal(p)">编辑</button>
                <button
                  class="link-btn danger"
                  :disabled="p.id === selectedAgentProfileId"
                  :title="p.id === selectedAgentProfileId ? '当前档已被指定为 Agent 后端，禁止删除' : ''"
                  @click="handleDelete(p)"
                >
                  删除
                </button>
              </div>
            </td>
          </tr>

          <tr v-if="profiles.length === 0">
            <td colspan="7">
              <EmptyState title="暂无模型协议档" description="点击右上角新增 OpenAI / Anthropic 协议档">
                <template #action>
                  <button class="btn btn-primary btn-sm" @click="openModal(null)">新增协议档</button>
                </template>
              </EmptyState>
            </td>
          </tr>
        </tbody>
      </table>
    </div>

    </template>

    <!-- Tab 2：MCP 工具中心（V1.0 只读；外部 MCP Server 管理能力受控） -->
    <template v-else-if="activeTab === 'mcp'">
      <div class="mcp-center-container">
        <!-- 1. 顶部全景与操作栏 -->
        <div class="panel mb16">
          <div class="row-between mb8" style="flex-wrap: wrap; gap: 12px">
            <div class="mcp-hero-title-area">
              <div class="row" style="gap: 8px; align-items: center">
                <span class="mcp-main-title">🛠 MCP (Model Context Protocol) 工具中心</span>
                <span class="tag-soft mcp-badge-host">Host 模式 · V1.0 受控沙箱</span>
                <span class="badge" :class="disabledMcpToolsCount ? 'badge-warning' : 'badge-succeeded'">
                  {{ disabledMcpToolsCount ? `${disabledMcpToolsCount} 项能力未挂载` : '全短工具就绪' }}
                </span>
              </div>
              <div class="small tertiary mt4" style="line-height: 1.5">
                Agent 作为 MCP Host 运行时，通过短工具完成资产发现与建单；禁止挂载长耗时阻塞工具。
              </div>
            </div>

            <!-- 操作按钮组 -->
            <div class="row" style="gap: 8px; align-items: center">
              <button
                class="btn btn-secondary btn-sm"
                title="导出短工具 JSON Schema 契约"
                @click="handleExportMcpJson"
              >
                📋 导出契约 JSON
              </button>
              <button
                class="btn btn-secondary btn-sm"
                :disabled="mcpLoading"
                title="刷新工具清单与健康状态"
                @click="handleRefreshMcpTools"
              >
                🔄 {{ mcpLoading ? '加载中…' : '刷新清单' }}
              </button>
              <button
                class="btn btn-sign btn-sm"
                @click="handleOpenAddExternalServer"
              >
                + 接入外部 MCP Server
              </button>
            </div>
          </div>

          <!-- 2. KPI 核心指标微光带 -->
          <div class="mcp-kpi-grid">
            <div class="mcp-kpi-card">
              <div class="mcp-kpi-top">
                <span class="mcp-kpi-label">已挂载受控短工具</span>
                <span class="mcp-kpi-icon">🛠️</span>
              </div>
              <div class="mcp-kpi-val num">{{ enabledMcpToolsCount }} <span class="unit">个已挂载短工具</span></div>
              <div class="mcp-kpi-sub text-success">
                ● {{ mcpTools.length }} 项清单 · {{ disabledMcpToolsCount }} 项未挂载
              </div>
            </div>

            <div class="mcp-kpi-card">
              <div class="mcp-kpi-top">
                <span class="mcp-kpi-label">权限策略分布</span>
                <span class="mcp-kpi-icon">🛡️</span>
              </div>
              <div class="mcp-kpi-val num">
                <span style="color: var(--accent-success)">{{ readToolsCount }}</span>
                <span class="unit" style="margin: 0 4px">READ /</span>
                <span style="color: var(--accent-warning)">{{ writeToolsCount }}</span>
                <span class="unit">WRITE</span>
              </div>
              <div class="mcp-kpi-sub">严格沙箱校验 · 免审批只读</div>
            </div>

            <div class="mcp-kpi-card">
              <div class="mcp-kpi-top">
                <span class="mcp-kpi-label">MCP Host 宿主状态</span>
                <span class="mcp-kpi-icon">⚡</span>
              </div>
              <div class="mcp-kpi-val mono">Eval-Core <span class="unit">Host</span></div>
              <div class="mcp-kpi-sub mono text-info">
                {{ mcpServerPingState?.latencyMs !== null && mcpServerPingState?.latencyMs !== undefined ? `● 探活 ${mcpServerPingState.latencyMs}ms (在线)` : '● 内存直连 / 0ms (在线)' }}
              </div>
            </div>

            <div class="mcp-kpi-card">
              <div class="mcp-kpi-top">
                <span class="mcp-kpi-label">长任务阻塞门禁</span>
                <span class="mcp-kpi-icon">🔒</span>
              </div>
              <div class="mcp-kpi-val num" style="color: var(--accent-ai)">L1 沙箱 <span class="unit">门禁</span></div>
              <div class="mcp-kpi-sub">耗时任务转 Worker 异步派生</div>
            </div>
          </div>
        </div>

        <!-- 3. MCP 服务节点矩阵 (MCP Servers & Host Node Status) -->
        <div class="panel mb16">
          <div class="row-between mb12">
            <div class="row" style="gap: 8px; align-items: center">
              <span class="panel-title" style="margin: 0">已挂载 MCP 服务节点 (MCP Servers)</span>
              <span class="tag-soft">1 个内置宿主 · 0 个外部扩展</span>
            </div>
            <span class="small tertiary">智能体环境运行时直连</span>
          </div>

          <div class="mcp-servers-grid">
            <!-- Eval-Core MCP Server (内置) -->
            <div class="mcp-server-card builtin-server">
              <div class="server-card-head">
                <div class="row" style="gap: 8px; align-items: center">
                  <span class="server-icon">🏛️</span>
                  <div>
                    <div class="row" style="gap: 6px; align-items: center">
                      <span class="server-name">Eval-Core MCP Server</span>
                      <span class="tag-soft" style="color: var(--accent-ai)">内置系统服务</span>
                    </div>
                    <div class="mono small tertiary">http://api:8000/api/mcp/tools (v1)</div>
                  </div>
                </div>

                <div class="row" style="gap: 8px; align-items: center">
                  <span
                    class="ping-badge"
                    :class="mcpServerPingState?.ok !== false ? 'ok' : 'err'"
                    title="点击重新探活"
                    @click="handlePingMcpServer"
                  >
                    {{ mcpServerPingState ? (mcpServerPingState.ok ? `● 在线 (${mcpServerPingState.latencyMs}ms)` : '✕ 连接异常') : '● 在线 (直连)' }}
                  </span>
                  <button
                    class="btn btn-secondary btn-xs"
                    :disabled="mcpServerPinging"
                    @click="handlePingMcpServer"
                  >
                    {{ mcpServerPinging ? '探活中…' : '探活 Ping' }}
                  </button>
                </div>
              </div>

              <div class="server-card-meta">
                <div class="server-meta-item">
                  <span class="meta-k">传输协议:</span>
                  <span class="meta-v mono">Streamable HTTP / In-Process</span>
                </div>
                <div class="server-meta-item">
                  <span class="meta-k">挂载短工具:</span>
                  <span class="meta-v mono font-bold text-success">{{ mcpTools.length }} 个受控短工具</span>
                </div>
                <div class="server-meta-item">
                  <span class="meta-k">鉴权模式:</span>
                  <span class="meta-v">短票 ws-ticket + JWT 校验</span>
                </div>
                <div class="server-meta-item">
                  <span class="meta-k">隔离等级:</span>
                  <span class="meta-v">严格只读/受控建单沙箱</span>
                </div>
              </div>
            </div>

            <!-- External MCP Server Gateway (受控状态) -->
            <div class="mcp-server-card external-server">
              <div class="server-card-head">
                <div class="row" style="gap: 8px; align-items: center">
                  <span class="server-icon">🌐</span>
                  <div>
                    <div class="row" style="gap: 6px; align-items: center">
                      <span class="server-name">External MCP Server Gateway</span>
                      <span class="tag-soft" style="color: var(--text-tertiary)">未挂载外部节点</span>
                    </div>
                    <div class="mono small tertiary">受控隔离网关 · 动态扩展槽位预留</div>
                  </div>
                </div>

                <span class="tag-soft" style="border-color: var(--border-subtle)">受控边界保护</span>
              </div>

              <div class="server-card-meta" style="margin-top: 10px">
                <div class="small tertiary" style="line-height: 1.5">
                  V1.0 架构严格限制外部 MCP Server 接入（API §3.6.1），防范外部不可控长延迟与越权代码注入。如需扩展需经工程审批后另立版本。
                </div>
              </div>
            </div>
          </div>
        </div>

        <!-- 4. 工具清单与权限策略 (Tools Manifest) -->
        <div class="panel mb16">
          <div class="mcp-toolbar mb16">
            <div class="mcp-filter-group">
              <!-- 权限筛选 -->
              <div class="pill-segmented">
                <button
                  class="pill-btn"
                  :class="{ active: mcpPermFilter === 'all' }"
                  @click="mcpPermFilter = 'all'"
                >
                  全部权限 ({{ mcpTools.length }})
                </button>
                <button
                  class="pill-btn"
                  :class="{ active: mcpPermFilter === 'read' }"
                  @click="mcpPermFilter = 'read'"
                >
                  📖 只读 READ ({{ readToolsCount }})
                </button>
                <button
                  class="pill-btn"
                  :class="{ active: mcpPermFilter === 'write' }"
                  @click="mcpPermFilter = 'write'"
                >
                  ✍️ 写入 WRITE ({{ writeToolsCount }})
                </button>
              </div>

              <!-- 领域分类下拉 -->
              <div style="width: 140px">
                <n-select
                  v-model:value="mcpDomainFilter"
                  size="small"
                  :options="domainFilterOptions"
                />
              </div>

              <!-- 搜索框 -->
              <div style="width: 220px">
                <n-input
                  v-model:value="mcpSearchKeyword"
                  size="small"
                  placeholder="搜索工具名或说明…"
                  clearable
                >
                  <template #prefix>🔍</template>
                </n-input>
              </div>
            </div>

            <!-- 视图切换器 -->
            <div class="view-mode-toggle">
              <button
                class="toggle-btn"
                :class="{ active: mcpViewMode === 'cards' }"
                @click="mcpViewMode = 'cards'"
              >
                🎴 现代卡片
              </button>
              <button
                class="toggle-btn"
                :class="{ active: mcpViewMode === 'table' }"
                @click="mcpViewMode = 'table'"
              >
                📑 契约表格
              </button>
            </div>
          </div>

          <!-- 模式 A：现代卡片网格 -->
          <div v-if="mcpViewMode === 'cards'" class="mcp-cards-grid">
            <div
              v-for="t in filteredMcpTools"
              :key="t.name"
              class="mcp-card"
              :class="{ 'is-write': t.permission === 'write', 'is-disabled': t.enabled === false }"
            >
              <div class="mcp-card-top">
                <div class="row" style="gap: 8px; align-items: center">
                  <span class="tool-card-icon">{{ getToolDomain(t.name).icon }}</span>
                  <div>
                    <div class="mcp-tool-title mono">{{ t.name }}</div>
                    <div class="domain-tag">{{ getToolDomain(t.name).label }}</div>
                  </div>
                </div>

                <span
                  class="tag-soft"
                  :class="t.permission === 'write' ? 'perm-badge-write' : 'perm-badge-read'"
                >
                  {{ t.permission === 'write' ? 'WRITE' : 'READ' }}
                </span>
              </div>

              <div class="mcp-tool-desc">{{ t.desc }}</div>

              <div class="mcp-card-specs">
                <div class="spec-tag mono">{{ t.enabled === false ? '⏸ 未挂载' : '⚡ 耗时: <50ms' }}</div>
                <div class="spec-tag mono">📦 JSON Schema</div>
                <div class="spec-tag">🔒 受控沙箱</div>
              </div>

              <div class="mcp-card-bottom">
                <div class="row" style="gap: 6px; align-items: center">
                  <span class="status-dot" :class="{ 'is-disabled': t.enabled === false }"></span>
                  <span class="small tertiary">
                    {{ t.enabled === false ? '独立 MCP · 能力未启用' : '内置直连 · 活跃' }}
                  </span>
                </div>
                <button
                  class="btn btn-secondary btn-xs"
                  @click="handleOpenMcpModal(t)"
                >
                  查看契约 (Schema)
                </button>
              </div>
            </div>

            <div v-if="filteredMcpTools.length === 0" class="empty-state-wrap" style="grid-column: 1 / -1">
              <EmptyState title="未找到匹配的 MCP 工具" description="请尝试清空搜索条件或重置筛选器" />
            </div>
          </div>

          <!-- 模式 B：契约矩阵表格 -->
          <div v-else class="table-responsive">
            <table class="ds-table">
              <thead>
                <tr>
                  <th style="width: 190px">工具标识</th>
                  <th style="width: 120px">业务领域</th>
                  <th>职责说明与执行契约</th>
                  <th style="width: 110px">权限级别</th>
                  <th style="width: 110px">预估延迟</th>
                  <th style="width: 100px">传输格式</th>
                  <th style="width: 90px">状态</th>
                  <th style="width: 120px; text-align: right">操作</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="t in filteredMcpTools" :key="t.name">
                  <td class="mono font-bold" style="color: var(--c-profiles)">
                    <div class="row" style="gap: 6px; align-items: center">
                      <span>{{ getToolDomain(t.name).icon }}</span>
                      <span>{{ t.name }}</span>
                    </div>
                  </td>
                  <td>
                    <span class="tag-soft">{{ getToolDomain(t.name).label }}</span>
                  </td>
                  <td class="small" style="color: var(--text-primary)">{{ t.desc }}</td>
                  <td>
                    <span
                      class="tag-soft"
                      :class="t.permission === 'write' ? 'perm-badge-write' : 'perm-badge-read'"
                    >
                      {{ t.permission === 'write' ? 'WRITE · 写入' : 'READ · 只读' }}
                    </span>
                  </td>
                  <td class="mono small" :class="t.enabled === false ? 'tertiary' : 'text-success'">
                    {{ t.enabled === false ? '未接入' : '< 30ms' }}
                  </td>
                  <td class="mono small tertiary">JSON Schema</td>
                  <td>
                    <span class="badge" :class="t.enabled === false ? 'badge-warning' : 'badge-succeeded'">
                      {{ t.enabled === false ? '能力未启用' : '已启用' }}
                    </span>
                  </td>
                  <td style="text-align: right">
                    <button class="link-btn" @click="handleOpenMcpModal(t)">
                      查看契约
                    </button>
                  </td>
                </tr>

                <tr v-if="filteredMcpTools.length === 0">
                  <td colspan="8">
                    <EmptyState title="未找到匹配的 MCP 工具" description="请尝试清空搜索条件或重置筛选器" />
                  </td>
                </tr>
              </tbody>
            </table>
          </div>
        </div>

        <!-- 5. 架构边界与安全控制规范 (Architecture & Security Guardrails) -->
        <div class="panel mb16">
          <div class="panel-title mb12">
            🛡️ MCP Host 架构边界与安全准则 (Architecture Guardrails)
          </div>
          <div class="guardrails-grid">
            <div class="guardrail-card">
              <div class="guardrail-head">
                <span class="g-icon">⚡</span>
                <span class="g-title">毫秒级短工具契约</span>
              </div>
              <p class="g-text">
                Agent 作为 MCP Host 仅允许毫秒级资产读取与 TaskSpec 提交，<strong>禁止挂载长时间阻塞评测循环</strong>，保障 WS 心跳与交互极速响应。
              </p>
            </div>

            <div class="guardrail-card">
              <div class="guardrail-head">
                <span class="g-icon">🛡️</span>
                <span class="g-title">单向受控安全沙箱</span>
              </div>
              <p class="g-text">
                所有短工具均通过单次 <code>ws-ticket</code> 与 JWT 鉴权，入参由 Pydantic 强类型过滤，隔离未授权访问与越权注入。
              </p>
            </div>

            <div class="guardrail-card">
              <div class="guardrail-head">
                <span class="g-icon">🔄</span>
                <span class="g-title">先评后压派生原则</span>
              </div>
              <p class="g-text">
                质量评测成功 (`succeeded`) 且勾选压测后，由 Python Worker 异步派生执行 go-stress-testing，<strong>MCP 宿主绝不直接发压</strong>。
              </p>
            </div>

            <div class="guardrail-card">
              <div class="guardrail-head">
                <span class="g-icon">🔒</span>
                <span class="g-title">V1.0 架构边界冻结</span>
              </div>
              <p class="g-text">
                外部 MCP Server 的接入、探活、解绑与动态发现在 V1.0 保持受控未启用（API §3.6.1），平台使用严格冻结的内置短工具矩阵。
              </p>
            </div>
          </div>
        </div>
      </div>
    </template>

    <!-- Tab 3：Agent 技能编排（V1.0 受控边界：固定系统提示词，不回显、不可自定义） -->
    <template v-else-if="activeTab === 'skills'">
      <div class="skills-center-container">
        <!-- 1. 顶部全景与操作栏 -->
        <div class="panel mb16">
          <div class="row-between mb8" style="flex-wrap: wrap; gap: 12px">
            <div class="skills-hero-title-area">
              <div class="row" style="gap: 8px; align-items: center">
                <span class="skills-main-title">🧠 Agent 技能编排 (Skills & Prompts)</span>
                <span class="tag-soft skills-badge-vault">PRD 5.5.2 受控编排 · 4大内置场景</span>
                <span class="badge badge-succeeded">Prompt 沙箱托管</span>
              </div>
              <div class="small tertiary mt4" style="line-height: 1.5">
                智能体在基准对比、RAG 评估、用例生成与压测场景下的 4 大核心内置技能；System Prompt 由服务端安全沙箱托管。
              </div>
            </div>

            <!-- 操作按钮组 -->
            <div class="row" style="gap: 8px; align-items: center">
              <button
                class="btn btn-secondary btn-sm"
                title="导出技能编排配置清单"
                @click="handleExportSkillsJson"
              >
                📋 导出技能配置
              </button>
              <button
                class="btn btn-sign btn-sm"
                @click="handleOpenAddSkillNotice"
              >
                + 创建自定义技能
              </button>
            </div>
          </div>

          <!-- 2. KPI 核心指标微光带 -->
          <div class="skills-kpi-grid">
            <div class="skills-kpi-card">
              <div class="skills-kpi-top">
                <span class="skills-kpi-label">核心内置技能</span>
                <span class="skills-kpi-icon">🧠</span>
              </div>
              <div class="skills-kpi-val num">{{ builtinSkills.length }} <span class="unit">大核心技能</span></div>
              <div class="skills-kpi-sub text-success">● 100% 架构受控冻结</div>
            </div>

            <div class="skills-kpi-card">
              <div class="skills-kpi-top">
                <span class="skills-kpi-label">提示词托管模式</span>
                <span class="skills-kpi-icon">🔒</span>
              </div>
              <div class="skills-kpi-val mono" style="color: var(--accent-ai)">服务端托管</div>
              <div class="skills-kpi-sub">代码级硬编码 · 沙箱防注入</div>
            </div>

            <div class="skills-kpi-card">
              <div class="skills-kpi-top">
                <span class="skills-kpi-label">绑定短工具矩阵</span>
                <span class="skills-kpi-icon">🛠️</span>
              </div>
              <div class="skills-kpi-val num">
                <span style="color: var(--accent-success)">{{ mcpTools.length || 9 }}</span>
                <span class="unit">个受控短工具</span>
              </div>
              <div class="skills-kpi-sub mono text-info">毫秒级非阻塞 · 极速执行</div>
            </div>

            <div class="skills-kpi-card">
              <div class="skills-kpi-top">
                <span class="skills-kpi-label">快捷斜杠命令</span>
                <span class="skills-kpi-icon">⚡</span>
              </div>
              <div class="skills-kpi-val num" style="color: var(--accent-warning)">15 <span class="unit">条内置指令</span></div>
              <div class="skills-kpi-sub">支持自然语言与快捷命令分发</div>
            </div>
          </div>
        </div>

        <!-- 3. 技能编排矩阵与工具条 -->
        <div class="panel mb16">
          <div class="skills-toolbar mb16">
            <div class="skills-filter-group">
              <!-- 场景分类分段器 -->
              <div class="pill-segmented">
                <button
                  class="pill-btn"
                  :class="{ active: skillCategoryFilter === 'all' }"
                  @click="skillCategoryFilter = 'all'"
                >
                  全部场景 ({{ builtinSkills.length }})
                </button>
                <button
                  class="pill-btn"
                  :class="{ active: skillCategoryFilter === 'benchmark' }"
                  @click="skillCategoryFilter = 'benchmark'"
                >
                  📊 基准对比
                </button>
                <button
                  class="pill-btn"
                  :class="{ active: skillCategoryFilter === 'rag' }"
                  @click="skillCategoryFilter = 'rag'"
                >
                  🔍 RAG 评估
                </button>
                <button
                  class="pill-btn"
                  :class="{ active: skillCategoryFilter === 'testcase' }"
                  @click="skillCategoryFilter = 'testcase'"
                >
                  🧪 用例生成
                </button>
                <button
                  class="pill-btn"
                  :class="{ active: skillCategoryFilter === 'stress' }"
                  @click="skillCategoryFilter = 'stress'"
                >
                  🚀 容量压测
                </button>
              </div>

              <!-- 搜索框 -->
              <div style="width: 220px">
                <n-input
                  v-model:value="skillSearchKeyword"
                  size="small"
                  placeholder="搜索技能名称或依赖工具…"
                  clearable
                >
                  <template #prefix>🔍</template>
                </n-input>
              </div>
            </div>

            <!-- 视图切换器 -->
            <div class="view-mode-toggle">
              <button
                class="toggle-btn"
                :class="{ active: skillViewMode === 'cards' }"
                @click="skillViewMode = 'cards'"
              >
                🎴 现代卡片
              </button>
              <button
                class="toggle-btn"
                :class="{ active: skillViewMode === 'table' }"
                @click="skillViewMode = 'table'"
              >
                📑 规格表格
              </button>
            </div>
          </div>

          <!-- 模式 A：现代卡片网格 -->
          <div v-if="skillViewMode === 'cards'" class="skills-cards-grid">
            <div
              v-for="s in filteredSkills"
              :key="s.id"
              class="skill-card-v2"
            >
              <div class="skill-card-top">
                <div class="row" style="gap: 10px; align-items: flex-start">
                  <span class="skill-main-icon">{{ s.icon }}</span>
                  <div>
                    <div class="row" style="gap: 6px; align-items: center">
                      <span class="skill-card-name">{{ s.name }}</span>
                      <span class="tag-soft mono" style="font-size: 10px">{{ s.id }}</span>
                    </div>
                    <div class="skill-scenario-tag">{{ s.scenario }}</div>
                  </div>
                </div>

                <div class="row" style="gap: 6px; align-items: center">
                  <span class="tag-soft skill-builtin-chip">内置核心</span>
                  <span class="status-dot"></span>
                </div>
              </div>

              <div class="skill-card-desc">{{ s.desc }}</div>

              <!-- 调优参数微型芯片 -->
              <div class="skill-tuning-chips">
                <div class="tuning-chip">
                  <span class="tuning-k">Temp</span>
                  <span class="tuning-v mono">{{ s.temperature }}</span>
                </div>
                <div class="tuning-chip">
                  <span class="tuning-k">MaxTokens</span>
                  <span class="tuning-v mono">{{ s.maxTokens }}</span>
                </div>
                <div class="tuning-chip">
                  <span class="tuning-k">TopP</span>
                  <span class="tuning-v mono">{{ s.topP }}</span>
                </div>
              </div>

              <!-- 触发斜杠命令 -->
              <div class="skill-cmds-row">
                <span class="cmd-label">触发命令:</span>
                <span v-for="cmd in s.slashCommands" :key="cmd" class="cmd-tag mono">{{ cmd }}</span>
              </div>

              <!-- 依赖工具 -->
              <div class="skill-tools-row">
                <span class="tools-label">依赖短工具:</span>
                <div class="row wrap" style="gap: 4px">
                  <span v-for="t in s.tools" :key="t" class="tool-tag mono">{{ t }}</span>
                </div>
              </div>

              <div class="skill-card-bottom">
                <div class="row" style="gap: 6px; align-items: center">
                  <span class="small tertiary">🔒 System Prompt 安全沙箱托管</span>
                </div>
                <button
                  class="btn btn-secondary btn-xs"
                  @click="handleOpenSkillModal(s)"
                >
                  编排详情
                </button>
              </div>
            </div>

            <div v-if="filteredSkills.length === 0" class="empty-state-wrap" style="grid-column: 1 / -1">
              <EmptyState title="未找到匹配的 Agent 技能" description="请尝试清空搜索条件或重置筛选器" />
            </div>
          </div>

          <!-- 模式 B：规格矩阵表格 -->
          <div v-else class="table-responsive">
            <table class="ds-table">
              <thead>
                <tr>
                  <th style="width: 170px">技能名称 / ID</th>
                  <th style="width: 140px">适用场景</th>
                  <th>职责说明与编排策略</th>
                  <th style="width: 170px">触发斜杠命令</th>
                  <th style="width: 200px">依赖短工具</th>
                  <th style="width: 140px">调优参数</th>
                  <th style="width: 90px">状态</th>
                  <th style="width: 100px; text-align: right">操作</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="s in filteredSkills" :key="s.id">
                  <td>
                    <div class="row" style="gap: 6px; align-items: center">
                      <span style="font-size: 18px">{{ s.icon }}</span>
                      <div>
                        <div style="font-weight: 700; font-size: 13.5px">{{ s.name }}</div>
                        <div class="mono small tertiary" style="font-size: 10px">{{ s.id }}</div>
                      </div>
                    </div>
                  </td>
                  <td><span class="tag-soft">{{ s.scenario }}</span></td>
                  <td class="small" style="color: var(--text-primary)">{{ s.desc }}</td>
                  <td>
                    <div class="row wrap" style="gap: 4px">
                      <span v-for="cmd in s.slashCommands" :key="cmd" class="cmd-tag mono">{{ cmd }}</span>
                    </div>
                  </td>
                  <td>
                    <div class="row wrap" style="gap: 4px">
                      <span v-for="t in s.tools" :key="t" class="tool-tag mono">{{ t }}</span>
                    </div>
                  </td>
                  <td>
                    <div class="mono small" style="color: var(--accent-ai)">
                      T={{ s.temperature }} · {{ s.maxTokens }}t
                    </div>
                  </td>
                  <td>
                    <span class="badge badge-succeeded">已启用</span>
                  </td>
                  <td style="text-align: right">
                    <button class="link-btn" @click="handleOpenSkillModal(s)">
                      编排详情
                    </button>
                  </td>
                </tr>

                <tr v-if="filteredSkills.length === 0">
                  <td colspan="8">
                    <EmptyState title="未找到匹配的 Agent 技能" description="请尝试清空搜索条件或重置筛选器" />
                  </td>
                </tr>
              </tbody>
            </table>
          </div>
        </div>

        <!-- 4. 技能安全与编排边界准则 (Architecture Guardrails) -->
        <div class="panel mb16">
          <div class="panel-title mb12">
            🛡️ Agent 技能安全与编排边界准则 (Skills Guardrails)
          </div>
          <div class="guardrails-grid">
            <div class="guardrail-card">
              <div class="guardrail-head">
                <span class="g-icon">🔒</span>
                <span class="g-title">固定提示词安全托管</span>
              </div>
              <p class="g-text">
                采用服务端代码级固定系统提示词（System Prompt），<strong>严禁外部明文读取或动态覆盖</strong>，严格防范 Prompt 越权注入与越狱。
              </p>
            </div>

            <div class="guardrail-card">
              <div class="guardrail-head">
                <span class="g-icon">⚡</span>
                <span class="g-title">ReAct 单步受控调度</span>
              </div>
              <p class="g-text">
                智能体通过 ReAct 循环分解意图并调用受控短工具，<strong>严格限制思考轮次与上下文窗口</strong>，保障快速确定性响应。
              </p>
            </div>

            <div class="guardrail-card">
              <div class="guardrail-head">
                <span class="g-icon">🔄</span>
                <span class="g-title">先评后压自动派生</span>
              </div>
              <p class="g-text">
                基准评测质量任务成功 (`succeeded`) 后自动派生 go-stress-testing 压测，<strong>技能间遵循严格状态机流转</strong>。
              </p>
            </div>

            <div class="guardrail-card">
              <div class="guardrail-head">
                <span class="g-icon">🏛️</span>
                <span class="g-title">V1.0 架构冻结准则</span>
              </div>
              <p class="g-text">
                自定义技能创建与 Prompt 编辑在 V1.0 处于受控未开放状态（API §3.6.2），后续版本将另立 API 并补齐安全审计与回滚机制。
              </p>
            </div>
          </div>
        </div>
      </div>
    </template>

    <!-- Tab 4：Agent 运行时与主机治理（写入 /api/admin/settings.runtime，带审计） -->
    <template v-else>
      <div class="panel mb16" style="padding: 16px 20px">
        <div class="panel-title mb8">WebSocket 智能体会话与连接参数</div>
        <div class="row wrap mb16" style="gap: 16px">
          <div class="field" style="width: 220px">
            <span class="field-label">心跳 Ping 间隔 (秒)</span>
            <n-input-number v-model:value="runtimeForm.ws_ping_s" :min="5" :max="300" style="width: 100%" />
          </div>
          <div class="field" style="width: 220px">
            <span class="field-label">连接超时断开 (秒)</span>
            <n-input-number v-model:value="runtimeForm.ws_timeout_s" :min="5" :max="300" style="width: 100%" />
          </div>
          <div class="field" style="width: 220px">
            <span class="field-label">WS Ticket 授权 TTL (秒)</span>
            <n-input-number :value="300" disabled style="width: 100%" />
            <span class="field-hint">一次性授权票据，固定 5 分钟（PRD 5.1）</span>
          </div>
        </div>

        <div class="panel-title mb8">会话占槽与并发互斥规则</div>
        <p class="small tertiary mb12">
          当前会话有进行中任务（含压测子任务）时，主按钮自动禁用，完成后方可开启新长任务（PRD 3.4）。
        </p>
        <div class="field mb16">
          <label class="row" style="gap: 8px; cursor: pointer">
            <n-switch v-model:value="runtimeForm.strict_session_slot" />
            <span style="font-weight: 600">严格会话占槽互斥：压测子任务执行期间保持槽位独占</span>
          </label>
        </div>

        <button class="btn btn-sign btn-sm" :disabled="runtimeSaving" @click="saveRuntime">
          {{ runtimeSaving ? '保存中…' : '保存运行时参数' }}
        </button>
      </div>
    </template>

    <!-- 弹窗 -->
    <ProfileModal
      v-model:show="showModal"
      :profile="selectedProfile"
      :initial-data="modalInitialData"
      :initial-tab="modalInitialTab"
      @success="loadProfiles"
    />

    <CheckResultModal
      v-model:show="showCheckModal"
      :result="checkResult"
    />

    <McpToolModal
      v-model:show="showMcpModal"
      :tool="selectedMcpTool"
    />

    <SkillDetailModal
      v-model:show="showSkillModal"
      :skill="selectedSkill"
    />
  </div>
</template>

<script setup lang="ts">
import { ref, computed, watch, onMounted } from 'vue'
import { useMessage, useDialog, NSelect, NInput, NInputNumber, NSwitch } from 'naive-ui'
import { api } from '../api/http'
import type { Profile, ProfileCheckOut, McpTool } from '../api/types'
import EmptyState from '../components/common/EmptyState.vue'
import ProfileModal from '../components/modals/ProfileModal.vue'
import CheckResultModal from '../components/modals/CheckResultModal.vue'
import McpToolModal from '../components/modals/McpToolModal.vue'
import SkillDetailModal, { type SkillDetail } from '../components/modals/SkillDetailModal.vue'

const message = useMessage()
const dialog = useDialog()

// 4 Tab 架构（API V1.3 §3.6）：profiles / mcp / skills / runtime
type TabKey = 'profiles' | 'mcp' | 'skills' | 'runtime'
const tabs: { key: TabKey; label: string }[] = [
  { key: 'profiles', label: '协议档治理' },
  { key: 'mcp', label: '🛠 MCP 服务器与工具清单' },
  { key: 'skills', label: '🧠 Agent 技能与 Prompt 编排' },
  { key: 'runtime', label: '⚙ 运行时与主机治理' },
]
const activeTab = ref<TabKey>('profiles')

/** 切换 Tab 时触发对应真实后端接口加载 */
function switchTab(key: TabKey) {
  activeTab.value = key
  if (key === 'mcp') {
    handleRefreshMcpTools()
  } else if (key === 'profiles') {
    loadProfiles()
  }
}

// ═══════════════════════════════════════════════════════════════
// MCP 工具中心状态与交互管理
// ═══════════════════════════════════════════════════════════════
// MCP 内置短工具清单（只读，来自 /api/mcp/tools）
const mcpTools = ref<McpTool[]>([])
const mcpViewMode = ref<'cards' | 'table'>('cards')
const mcpPermFilter = ref<'all' | 'read' | 'write'>('all')
const mcpDomainFilter = ref<string>('all')
const mcpSearchKeyword = ref('')
const mcpLoading = ref(false)
const mcpServerPingState = ref<{ ok: boolean; latencyMs: number | null } | null>(null)
const mcpServerPinging = ref(false)
const selectedMcpTool = ref<McpTool | null>(null)
const showMcpModal = ref(false)

const domainFilterOptions = [
  { label: '全部领域', value: 'all' },
  { label: '🤖 模型资产', value: 'model' },
  { label: '📚 数据集', value: 'dataset' },
  { label: '🧠 知识库', value: 'kb' },
  { label: '📊 评测报告', value: 'report' },
  { label: '🚀 任务调度', value: 'task' },
  { label: '🖥️ 调度算力', value: 'dispatch' },
  { label: '🧪 用例管理', value: 'cases' },
  { label: '🔊 音色克隆', value: 'audio' },
  { label: '🖼️ 图像生成', value: 'image' },
]

/** 获取工具业务领域与图标映射 */
function getToolDomain(name: string): { label: string; icon: string; key: string } {
  if (name.startsWith('model.')) return { label: '模型资产', icon: '🤖', key: 'model' }
  if (name.startsWith('dataset.')) return { label: '数据集', icon: '📚', key: 'dataset' }
  if (name.startsWith('kb.')) return { label: '知识库', icon: '🧠', key: 'kb' }
  if (name.startsWith('report.')) return { label: '评测报告', icon: '📊', key: 'report' }
  if (name.startsWith('task.')) return { label: '任务调度', icon: '🚀', key: 'task' }
  if (name.startsWith('dispatch.')) return { label: '调度大盘', icon: '🖥️', key: 'dispatch' }
  if (name.startsWith('testcase.')) return { label: '用例管理', icon: '🧪', key: 'cases' }
  if (name.startsWith('audio.')) return { label: '音色克隆', icon: '🔊', key: 'audio' }
  if (name.startsWith('image.')) return { label: '图像生成', icon: '🖼️', key: 'image' }
  return { label: '内置通用', icon: '🛠️', key: 'other' }
}

const readToolsCount = computed(() => mcpTools.value.filter((t) => t.permission === 'read').length)
const writeToolsCount = computed(() => mcpTools.value.filter((t) => t.permission === 'write').length)
const enabledMcpToolsCount = computed(() => mcpTools.value.filter((t) => t.enabled !== false).length)
const disabledMcpToolsCount = computed(() => mcpTools.value.filter((t) => t.enabled === false).length)

/** 多维过滤后的 MCP 工具清单 */
const filteredMcpTools = computed(() => {
  return mcpTools.value.filter((t) => {
    // 权限过滤
    if (mcpPermFilter.value !== 'all' && t.permission !== mcpPermFilter.value) return false
    // 领域分类过滤
    if (mcpDomainFilter.value !== 'all') {
      const domain = getToolDomain(t.name)
      if (domain.key !== mcpDomainFilter.value) return false
    }
    // 关键字搜索过滤
    if (mcpSearchKeyword.value.trim()) {
      const kw = mcpSearchKeyword.value.toLowerCase().trim()
      const matchName = t.name.toLowerCase().includes(kw)
      const matchDesc = t.desc.toLowerCase().includes(kw)
      const matchDomain = getToolDomain(t.name).label.toLowerCase().includes(kw)
      if (!matchName && !matchDesc && !matchDomain) return false
    }
    return true
  })
})

/** 刷新 MCP 工具清单（真实调用 GET /api/mcp/tools） */
async function handleRefreshMcpTools() {
  mcpLoading.value = true
  const start = performance.now()
  try {
    const res = await api.mcp.tools()
    const latency = Math.round(performance.now() - start)
    mcpTools.value = res.items || []
    mcpServerPingState.value = { ok: true, latencyMs: Math.max(1, latency) }
    message.success(`已从服务端加载 ${enabledMcpToolsCount.value} 个已挂载短工具（共 ${mcpTools.value.length} 项清单，耗时 ${mcpServerPingState.value.latencyMs}ms）`)
  } catch (err: any) {
    mcpServerPingState.value = { ok: false, latencyMs: null }
    message.error(err.message || '调用 /api/mcp/tools 接口失败')
  } finally {
    mcpLoading.value = false
  }
}

/** 探活 Eval-Core MCP Host 宿主直连延迟（真实调用 GET /api/mcp/tools） */
async function handlePingMcpServer() {
  mcpServerPinging.value = true
  const start = performance.now()
  try {
    const res = await api.mcp.tools()
    const latency = Math.round(performance.now() - start)
    mcpTools.value = res.items || []
    mcpServerPingState.value = { ok: true, latencyMs: Math.max(1, latency) }
    message.success(`[Eval-Core MCP Server] 探活成功 · 延迟 ${mcpServerPingState.value.latencyMs}ms · 挂载 ${enabledMcpToolsCount.value} 个短工具`)
  } catch (err: any) {
    mcpServerPingState.value = { ok: false, latencyMs: null }
    message.error(`[Eval-Core MCP Server] 探活失败: ${err.message || '网络连接异常'}`)
  } finally {
    mcpServerPinging.value = false
  }
}

/** 监听 activeTab 变化以保证 MCP Tab 即刻调用真实后端 API */
watch(
  () => activeTab.value,
  (newTab) => {
    if (newTab === 'mcp' && mcpTools.value.length === 0) {
      handleRefreshMcpTools()
    }
  },
)

/** 安全失焦辅助函数，避免弹窗在 aria-hidden 生效时子元素保留 focus 产生警告 */
function safeBlur() {
  if (typeof document !== 'undefined' && document.activeElement instanceof HTMLElement) {
    document.activeElement.blur()
  }
}

/** 打开短工具契约 Schema 详情弹窗 */
function handleOpenMcpModal(tool: McpTool) {
  safeBlur()
  selectedMcpTool.value = tool
  showMcpModal.value = true
}

/** 导出/复制 MCP 工具 JSON 契约 */
function handleExportMcpJson() {
  safeBlur()
  try {
    const payload = JSON.stringify(mcpTools.value, null, 2)
    navigator.clipboard.writeText(payload)
    message.success('已复制全部 MCP 工具 JSON 契约至剪贴板')
  } catch {
    message.info('请在安全上下文中复制契约')
  }
}

/** 接入外部 MCP Server 受控说明 */
function handleOpenAddExternalServer() {
  safeBlur()
  dialog.info({
    title: '接入外部 MCP Server · 架构受控说明',
    content:
      '依据系统架构契约（PRD §5.5 与 API §3.6.1），V1.0 智能体环境采用严格的单一 Eval-Core 内置受控 Host 模式，暂不开放外部第三方 MCP Server 接入、探活与动态解绑，以确保基准测试与 RAG 评测的高可用与任务确定性。',
    positiveText: '了解规范',
  })
}

// ═══════════════════════════════════════════════════════════════
// Agent 技能编排 (Skills & Prompts) 状态与交互管理
// ═══════════════════════════════════════════════════════════════
// PRD 5.5.2 的 4 大核心内置技能（V1.0 受控展示，不回显 System Prompt）
const builtinSkills: SkillDetail[] = [
  {
    id: 'skill-benchmark',
    icon: '📊',
    name: '基准对比',
    desc: '自动识别被测模型数量、推荐标准评测集并构建先评后压 TaskSpec。',
    scenario: '大模型质量基准评测',
    tools: ['model.list', 'dataset.list', 'task.create', 'task.get'],
    slashCommands: ['/compare', '/benchmark', '/eval'],
    temperature: 0.2,
    maxTokens: 2048,
    topP: 0.9,
  },
  {
    id: 'skill-rag',
    icon: '🔍',
    name: 'RAG 质量评估',
    desc: '自动装载知识库切块与黄金 QA，评测 LightRAG 4 模式检索表现。',
    scenario: '知识库与切块检索评估',
    tools: ['kb.list', 'task.create', 'report.get'],
    slashCommands: ['/rag', '/kb', '/retrieval'],
    temperature: 0.1,
    maxTokens: 2048,
    topP: 0.85,
  },
  {
    id: 'skill-testcase',
    icon: '🧪',
    name: 'PRD 用例生成',
    desc: '按 6 大策略精细配比（40/25/15/10/5/5）提炼测试用例并支持确认转正。',
    scenario: 'AI 需求与用例生成',
    tools: ['dataset.list', 'task.create', 'testcase.confirm'],
    slashCommands: ['/case', '/generate', '/prd'],
    temperature: 0.3,
    maxTokens: 3072,
    topP: 0.95,
  },
  {
    id: 'skill-stress',
    icon: '🚀',
    name: '共享容量压测',
    desc: '继承父任务 endpoint 与抽样问答，定位 SLA 拐点与成本开销。',
    scenario: '高并发容量与吞吐压测',
    tools: ['dispatch.overview', 'task.create', 'task.cancel'],
    slashCommands: ['/stress', '/capacity', '/load'],
    temperature: 0.0,
    maxTokens: 1024,
    topP: 1.0,
  },
]

const skillViewMode = ref<'cards' | 'table'>('cards')
const skillCategoryFilter = ref<'all' | 'benchmark' | 'rag' | 'testcase' | 'stress'>('all')
const skillSearchKeyword = ref('')
const selectedSkill = ref<SkillDetail | null>(null)
const showSkillModal = ref(false)

/** 多维过滤后的技能清单 */
const filteredSkills = computed(() => {
  return builtinSkills.filter((s) => {
    if (skillCategoryFilter.value !== 'all') {
      if (skillCategoryFilter.value === 'benchmark' && s.id !== 'skill-benchmark') return false
      if (skillCategoryFilter.value === 'rag' && s.id !== 'skill-rag') return false
      if (skillCategoryFilter.value === 'testcase' && s.id !== 'skill-testcase') return false
      if (skillCategoryFilter.value === 'stress' && s.id !== 'skill-stress') return false
    }
    if (skillSearchKeyword.value.trim()) {
      const kw = skillSearchKeyword.value.toLowerCase().trim()
      const matchName = s.name.toLowerCase().includes(kw)
      const matchId = s.id.toLowerCase().includes(kw)
      const matchDesc = s.desc.toLowerCase().includes(kw)
      const matchScenario = s.scenario.toLowerCase().includes(kw)
      const matchTools = s.tools.some((t) => t.toLowerCase().includes(kw))
      if (!matchName && !matchId && !matchDesc && !matchScenario && !matchTools) return false
    }
    return true
  })
})

/** 打开技能编排详情弹窗 */
function handleOpenSkillModal(skill: SkillDetail) {
  safeBlur()
  selectedSkill.value = skill
  showSkillModal.value = true
}

/** 导出/复制技能清单配置 JSON */
function handleExportSkillsJson() {
  safeBlur()
  try {
    const payload = JSON.stringify(builtinSkills, null, 2)
    navigator.clipboard.writeText(payload)
    message.success('已复制全部技能编排配置 JSON 至剪贴板')
  } catch {
    message.info('请在安全上下文中复制配置')
  }
}

/** 创建自定义技能受控说明 */
function handleOpenAddSkillNotice() {
  safeBlur()
  dialog.info({
    title: '创建自定义技能 · 架构受控说明',
    content:
      '依据系统安全与评测确定性契约（PRD §5.5.2 与 API §3.6.2），V1.0 使用服务端固定的高安全性系统提示词（System Prompt）与短工具绑定，暂不开放自定义技能创建与外部提示词篡改，防范 Prompt 越权注入。如后续版本开放将补齐安全审计与版本回滚机制。',
    positiveText: '了解规范',
  })
}

// 运行时治理表单（settings.runtime）
const runtimeForm = ref({ ws_ping_s: 15, ws_timeout_s: 45, strict_session_slot: true })
const runtimeSaving = ref(false)

// 视图模式：'cards' (供应商分类多卡片视图) | 'table' (详细表格视图)
const viewMode = ref<'cards' | 'table'>('cards')

const profiles = ref<Profile[]>([])
const loading = ref(false)
const selectedAgentProfileId = ref<string | null>(null)
// 最近一次成功保存的 Agent 协议档 ID，用于保存失败时回滚选择器
const lastSavedAgentProfileId = ref<string | null>(null)

const showModal = ref(false)
const selectedProfile = ref<Profile | null>(null)

const showCheckModal = ref(false)
const checkResult = ref<ProfileCheckOut | null>(null)
const checkingId = ref<string | null>(null)

// P2 行内探活状态：按协议档 id 记录最近一次探活结果（仅前端会话内缓存，不落库）
interface PingState {
  ok: boolean
  latencyMs: number | null
}
const pingStates = ref<Record<string, PingState>>({})
const pingingId = ref<string | null>(null)

const agentProfileOptions = computed(() =>
  profiles.value.map((p) => ({ label: `${p.name} (${p.model})`, value: p.id })),
)

interface VendorGroup {
  key: string
  name: string
  icon: string
  base_url: string
  protocol: any
  profiles: Profile[]
}

/** 智能归类供应商分组 */
const vendorGroups = computed<VendorGroup[]>(() => {
  const groups: Record<string, VendorGroup> = {}

  for (const p of profiles.value) {
    const url = (p.base_url || '').toLowerCase()
    const name = (p.name || '').toLowerCase()
    const model = (p.model || '').toLowerCase()

    let key = 'custom'
    let vName = '自定义端点 / 内部代理'
    let icon = '🌐'

    if (url.includes('nvidia') || name.includes('nvidia') || model.includes('nvidia')) {
      key = 'nvidia'
      vName = 'NVIDIA NIM'
      icon = '🟢'
    } else if (url.includes('xiaomimimo') || name.includes('mimo') || model.includes('mimo')) {
      key = 'mimo'
      vName = 'Xiaomi Mimo'
      icon = '⚡'
    } else if (url.includes('openai.com') || name.includes('openai') || model.startsWith('gpt-')) {
      key = 'openai'
      vName = 'OpenAI'
      icon = '🤖'
    } else if (url.includes('anthropic.com') || name.includes('claude') || model.startsWith('claude-')) {
      key = 'anthropic'
      vName = 'Anthropic Claude'
      icon = '🔮'
    } else if (url.includes('deepseek') || name.includes('deepseek') || model.includes('deepseek')) {
      key = 'deepseek'
      vName = 'DeepSeek'
      icon = '🐋'
    } else if (url.includes('siliconflow') || name.includes('silicon') || name.includes('硅基')) {
      key = 'siliconflow'
      vName = 'SiliconFlow (硅基流动)'
      icon = '⚡'
    } else if (url.includes('aliyuncs') || url.includes('dashscope') || name.includes('qwen') || model.includes('qwen')) {
      key = 'qwen'
      vName = 'Alibaba Qwen (通义千问)'
      icon = '☁️'
    } else if (url.includes('volces.com') || name.includes('doubao') || name.includes('火山') || name.includes('豆包')) {
      key = 'volcengine'
      vName = 'ByteDance Doubao (火山引擎)'
      icon = '🌋'
    } else if (url.includes('qianfan') || url.includes('baidubce') || name.includes('ernie') || name.includes('文心') || name.includes('千帆')) {
      key = 'qianfan'
      vName = 'Baidu Qianfan (百度千帆)'
      icon = '🐻'
    } else if (url.includes('hunyuan') || name.includes('混元')) {
      key = 'hunyuan'
      vName = 'Tencent Hunyuan (腾讯混元)'
      icon = '🐧'
    } else if (url.includes('groq') || name.includes('groq')) {
      key = 'groq'
      vName = 'Groq'
      icon = '⚡'
    } else if (url.includes('11434') || url.includes('ollama') || name.includes('ollama')) {
      key = 'ollama'
      vName = 'Ollama (本地私有)'
      icon = '🦙'
    } else if (url.includes('bigmodel.cn') || name.includes('glm') || model.includes('glm') || name.includes('智谱')) {
      key = 'zhipu'
      vName = 'Zhipu GLM (智谱清言)'
      icon = '🌟'
    } else if (url.includes('moonshot') || name.includes('kimi') || name.includes('moonshot') || name.includes('月之暗面')) {
      key = 'moonshot'
      vName = 'Moonshot (月之暗面)'
      icon = '🌙'
    } else if (url.includes('mistral') || name.includes('mistral')) {
      key = 'mistral'
      vName = 'Mistral AI'
      icon = '🌪️'
    } else if (url.includes('together') || name.includes('together')) {
      key = 'together'
      vName = 'Together AI'
      icon = '🤝'
    }

    if (!groups[key]) {
      groups[key] = {
        key,
        name: vName,
        icon,
        base_url: p.base_url,
        protocol: p.protocol,
        profiles: [],
      }
    }
    groups[key].profiles.push(p)
  }

  return Object.values(groups)
})

function formatContextWindow(tokens?: number): string {
  if (!tokens || tokens === 200000) return '200k'
  if (tokens >= 1000000) return `${(tokens / 1000000).toFixed(0)}M`
  return `${(tokens / 1000).toFixed(0)}k`
}

const modalInitialData = ref<{ vendorKey?: string; base_url?: string; protocol?: any; name?: string } | null>(null)
const modalInitialTab = ref<'llm' | 'embedding' | 'reranker'>('llm')

function openModal(profile: Profile | null, tab: 'llm' | 'embedding' | 'reranker' = 'llm') {
  safeBlur()
  selectedProfile.value = profile
  modalInitialData.value = null
  modalInitialTab.value = tab
  showModal.value = true
}

function openModalWithVendor(group: VendorGroup) {
  safeBlur()
  selectedProfile.value = null
  modalInitialTab.value = 'llm'
  modalInitialData.value = {
    vendorKey: group.key !== 'custom' ? group.key : undefined,
    base_url: group.base_url,
    protocol: group.protocol,
    name: group.name,
  }
  showModal.value = true
}

async function loadProfiles() {
  loading.value = true
  try {
    const [pListRes, settingsRes, toolsRes] = await Promise.allSettled([
      api.profiles.list(),
      api.admin.getSettings(),
      api.mcp.tools(),
    ])
    if (pListRes.status === 'fulfilled') {
      profiles.value = pListRes.value || []
    }
    if (settingsRes.status === 'fulfilled') {
      const settings = settingsRes.value
      selectedAgentProfileId.value = settings?.agent_profile_id || null
      lastSavedAgentProfileId.value = selectedAgentProfileId.value
      if (settings?.runtime) runtimeForm.value = { ...settings.runtime }
    }
    if (toolsRes.status === 'fulfilled') {
      mcpTools.value = toolsRes.value?.items || []
    }
  } catch (err: any) {
    message.error(err.message || '加载配置失败')
  } finally {
    loading.value = false
  }
}

/** 保存运行时治理参数（settings.runtime，后端写审计） */
async function saveRuntime() {
  runtimeSaving.value = true
  try {
    await api.admin.updateSettings({ runtime: { ...runtimeForm.value } } as any)
    message.success('运行时参数已更新生效（写审计）')
  } catch (err: any) {
    message.error(err.message || '运行时参数保存失败')
  } finally {
    runtimeSaving.value = false
  }
}

async function handleUpdateAgentProfile(profileId: string) {
  try {
    await api.admin.updateSettings({ agent_profile_id: profileId })
    lastSavedAgentProfileId.value = profileId
    message.success('Agent 后端模型已指定')
  } catch (err: any) {
    // 保存失败时回滚选择器，保持 UI 与后端状态一致
    selectedAgentProfileId.value = lastSavedAgentProfileId.value
    message.error(err.message || '设置失败')
  }
}

/** P2 行内探活：原位刷新 ping-badge（复用 api.profiles.check，不泄露凭据） */
async function handlePing(p: Profile) {
  pingingId.value = p.id
  try {
    const res = await api.profiles.check(p.id)
    pingStates.value[p.id] = { ok: !!res.ok, latencyMs: res.latency_ms ?? null }
    if (res.ok) {
      message.success(`[${p.name}] 连通性正常 · 延迟 ${res.latency_ms ?? '—'}ms`)
    } else {
      message.error(`[${p.name}] 连通性测试失败`)
    }
  } catch (err: any) {
    pingStates.value[p.id] = { ok: false, latencyMs: null }
    message.error(`[${p.name}] ${err.message || '连通性测试失败'}`)
  } finally {
    pingingId.value = null
  }
}

/** 连通详情：保留原有 CheckResultModal 弹窗（展示完整检查结果/错误信息） */
async function handleCheck(p: Profile) {
  safeBlur()
  checkingId.value = p.id
  try {
    const res = await api.profiles.check(p.id)
    checkResult.value = res
    showCheckModal.value = true
  } catch (err: any) {
    checkResult.value = { ok: false, error: err.message || '连接失败' }
    showCheckModal.value = true
  } finally {
    checkingId.value = null
  }
}

function handleDelete(p: Profile) {
  dialog.warning({
    title: `删除协议档「${p.name}」？`,
    content: '删除后，依赖此协议档的评测任务将无法再次发起。',
    positiveText: '确认删除',
    negativeText: '取消',
    onPositiveClick: async () => {
      try {
        await api.profiles.delete(p.id)
        message.success('协议档已删除')
        loadProfiles()
      } catch (err: any) {
        message.error(err.message || '删除失败')
      }
    },
  })
}

onMounted(loadProfiles)
</script>

<style scoped>
.profiles-page {
  display: flex;
  flex-direction: column;
  gap: 16px;
}
/* 视图切换按钮组 */
.view-mode-toggle {
  display: inline-flex;
  background: var(--bg-elevated, rgba(243, 244, 246, 1));
  padding: 3px;
  border-radius: 8px;
  border: 1px solid var(--border-subtle, rgba(229, 231, 235, 1));
}
.toggle-btn {
  border: none;
  background: transparent;
  padding: 4px 10px;
  font-size: 12px;
  font-weight: 500;
  border-radius: 6px;
  cursor: pointer;
  color: var(--text-secondary, #6b7280);
  transition: all 0.15s ease;
}
.toggle-btn.active {
  background: var(--bg-card, #ffffff);
  color: var(--c-profiles, #4f46e5);
  font-weight: 600;
  box-shadow: 0 1px 2px rgba(0, 0, 0, 0.06);
}

/* 供应商多卡片容器 */
.vendor-cards-container {
  display: flex;
  flex-direction: column;
  gap: 16px;
}
.vendor-group-card {
  border: 1px solid var(--border-subtle, rgba(229, 231, 235, 1));
  border-radius: 14px;
  background: linear-gradient(180deg, var(--bg-surface, #fafafa) 0%, rgba(255, 255, 255, 0.6) 100%);
  padding: 16px 18px;
  display: flex;
  flex-direction: column;
  gap: 14px;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.02);
  transition: all 0.2s ease;
}
.vendor-group-card:hover {
  border-color: rgba(99, 102, 241, 0.25);
  box-shadow: 0 4px 16px rgba(0, 0, 0, 0.03);
}
.vendor-group-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  border-bottom: 1px solid var(--border-subtle, rgba(229, 231, 235, 0.6));
  padding-bottom: 12px;
}
.vendor-title-row {
  display: flex;
  align-items: center;
  gap: 8px;
}
.vendor-badge {
  font-size: 20px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
}
.vendor-name {
  font-size: 15px;
  font-weight: 700;
  color: var(--text-primary, #111827);
  letter-spacing: -0.01em;
}
.vendor-count-badge {
  font-size: 11px;
  background: rgba(79, 70, 229, 0.1);
  color: var(--c-profiles, #4f46e5);
  padding: 2px 8px;
  border-radius: 999px;
  font-weight: 600;
  border: 1px solid rgba(79, 70, 229, 0.15);
}
.vendor-url {
  font-size: 11.5px;
  color: var(--text-secondary, #6b7280);
  margin-top: 2px;
}
.vendor-models-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
  gap: 12px;
}

/* 模型芯片卡片与流光动效 */
@keyframes core-mesh {
  0% { background-position: 0% 50%; }
  50% { background-position: 100% 50%; }
  100% { background-position: 0% 50%; }
}
@keyframes pulse-border {
  0%, 100% { border-color: rgba(99, 102, 241, 0.55); box-shadow: 0 0 12px rgba(99, 102, 241, 0.12); }
  50% { border-color: rgba(56, 189, 248, 0.85); box-shadow: 0 0 20px rgba(56, 189, 248, 0.22); }
}

.model-chip-card {
  background: var(--bg-card, #ffffff);
  border: 1px solid var(--border-subtle, rgba(229, 231, 235, 1));
  border-radius: 12px;
  padding: 14px;
  display: flex;
  flex-direction: column;
  gap: 10px;
  position: relative;
  transition: all 0.22s cubic-bezier(0.4, 0, 0.2, 1);
}
.model-chip-card:hover {
  transform: translateY(-2px);
  border-color: rgba(99, 102, 241, 0.45);
  box-shadow: 0 6px 20px -2px rgba(99, 102, 241, 0.1);
}
.model-chip-card.is-agent-core {
  border-width: 1.5px;
  background: linear-gradient(135deg, rgba(99, 102, 241, 0.07), rgba(56, 189, 248, 0.08), rgba(168, 85, 247, 0.06), rgba(99, 102, 241, 0.07));
  background-size: 300% 300%;
  animation: core-mesh 6s ease infinite, pulse-border 3.2s ease-in-out infinite;
  box-shadow: 0 4px 14px rgba(99, 102, 241, 0.15);
}
.model-chip-top {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
}
.model-chip-title-wrap {
  display: flex;
  align-items: center;
  gap: 6px;
  min-width: 0;
}
.model-chip-name {
  font-size: 13.5px;
  font-weight: 600;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.model-chip-meta {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 11px;
}
.model-id-tag {
  background: rgba(15, 23, 42, 0.06);
  padding: 2px 7px;
  border-radius: 5px;
  font-weight: 500;
  color: var(--text-primary, #1e293b);
}
.protocol-tag {
  color: var(--text-tertiary, #9ca3af);
}
.window-tag {
  display: inline-block;
  padding: 1px 5px;
  background: var(--t-profiles, rgba(79, 70, 229, 0.08));
  color: var(--c-profiles, #4f46e5);
  border-radius: 4px;
  font-size: 10.5px;
  font-weight: 600;
}
.model-chip-bottom {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-top: 4px;
  padding-top: 8px;
  border-top: 1px solid rgba(229, 231, 235, 0.5);
}
.btn-xs {
  font-size: 12px;
  padding: 4px 10px;
  border-radius: 6px;
}
.link-btn.small {
  font-size: 12px;
}

/* P2 连通性探活胶囊 */
.ping-badge {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  font-family: var(--font-mono);
  font-size: 11px;
  padding: 2px 6px;
  border-radius: 4px;
  cursor: pointer;
  white-space: nowrap;
}
.ping-badge.ok {
  background: rgba(16, 185, 129, 0.12);
  color: var(--accent-success);
  border: 1px solid rgba(16, 185, 129, 0.3);
}
.ping-badge.err {
  background: rgba(239, 68, 68, 0.12);
  color: var(--accent-error);
  border: 1px solid rgba(239, 68, 68, 0.3);
}
/* P4 Agent 核心驱动徽标 */
.agent-core-tag {
  border-color: #c7d2fe;
  color: var(--c-tasks);
  font-weight: 700;
  font-size: 11px;
}
/* 4 Tab 页签 */
.profile-tab-btn {
  padding: 8px 16px;
  border-radius: 8px;
  border: 1px solid var(--border-subtle);
  background: transparent;
  color: var(--text-secondary);
  font-size: 13px;
  font-weight: 600;
  cursor: pointer;
  transition: all 0.18s ease;
}
.profile-tab-btn:hover {
  color: var(--text-primary);
  border-color: var(--c-profiles);
}
.profile-tab-btn.active {
  background: var(--t-profiles, rgba(79, 70, 229, 0.1));
  color: var(--c-profiles);
  border-color: var(--c-profiles);
}
/* 技能卡片网格 */
.skill-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(300px, 1fr));
  gap: 14px;
}
.skill-card {
  display: flex;
  flex-direction: column;
  gap: 10px;
  padding: 14px 16px;
  border: 1px solid var(--border-subtle);
  border-radius: 10px;
  background: var(--bg-elevated);
}
.skill-head {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
}
.skill-title {
  font-weight: 700;
  font-size: 14px;
}

/* ═══════════════════════════════════════════════════════════════
   MCP 工具中心排版与微光视觉样式
   ═══════════════════════════════════════════════════════════════ */
.mcp-center-container {
  display: flex;
  flex-direction: column;
  gap: 16px;
}
.mcp-hero-title-area {
  display: flex;
  flex-direction: column;
  gap: 2px;
}
.mcp-main-title {
  font-size: 15.5px;
  font-weight: 700;
  color: var(--text-primary);
}
.mcp-badge-host {
  font-size: 11px;
  font-weight: 600;
  background: rgba(99, 102, 241, 0.1);
  color: var(--accent-ai);
  border: 1px solid rgba(99, 102, 241, 0.2);
}

/* MCP KPI 核心微光指标带 */
.mcp-kpi-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
  gap: 12px;
  margin-top: 14px;
  padding-top: 14px;
  border-top: 1px solid var(--border-subtle);
}
.mcp-kpi-card {
  padding: 12px 14px;
  background: var(--bg-elevated);
  border: 1px solid var(--border-subtle);
  border-radius: 10px;
  display: flex;
  flex-direction: column;
  gap: 4px;
  transition: all 0.2s ease;
}
.mcp-kpi-card:hover {
  border-color: rgba(99, 102, 241, 0.3);
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.03);
}
.mcp-kpi-top {
  display: flex;
  justify-content: space-between;
  align-items: center;
}
.mcp-kpi-label {
  font-size: 11.5px;
  color: var(--text-tertiary);
}
.mcp-kpi-icon {
  font-size: 16px;
}
.mcp-kpi-val {
  font-size: 18px;
  font-weight: 700;
  color: var(--text-primary);
  line-height: 1.2;
}
.mcp-kpi-val .unit {
  font-size: 11.5px;
  font-weight: 400;
  color: var(--text-tertiary);
}
.mcp-kpi-sub {
  font-size: 11px;
  color: var(--text-secondary);
}

/* MCP 服务节点矩阵 */
.mcp-servers-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(340px, 1fr));
  gap: 12px;
}
.mcp-server-card {
  padding: 14px 16px;
  border-radius: 12px;
  display: flex;
  flex-direction: column;
  gap: 8px;
  border: 1px solid var(--border-subtle);
  background: var(--bg-card, #ffffff);
  transition: all 0.2s ease;
}
.mcp-server-card.builtin-server {
  background: linear-gradient(180deg, var(--bg-elevated, #f4f8f8) 0%, rgba(255, 255, 255, 0.8) 100%);
  border-color: rgba(99, 102, 241, 0.25);
}
.mcp-server-card.external-server {
  background: var(--bg-elevated);
  border-style: dashed;
  opacity: 0.85;
}
.server-card-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
}
.server-icon {
  font-size: 24px;
}
.server-name {
  font-size: 13.5px;
  font-weight: 700;
  color: var(--text-primary);
}
.server-card-meta {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 6px 12px;
  padding-top: 8px;
  border-top: 1px solid rgba(229, 231, 235, 0.6);
}
.server-meta-item {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 11.5px;
}
.meta-k {
  color: var(--text-tertiary);
}
.meta-v {
  color: var(--text-primary);
}

/* MCP 检索工具条 */
.mcp-toolbar {
  display: flex;
  justify-content: space-between;
  align-items: center;
  flex-wrap: wrap;
  gap: 12px;
}
.mcp-filter-group {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 10px;
}
.pill-segmented {
  display: inline-flex;
  background: var(--bg-elevated);
  padding: 3px;
  border-radius: 8px;
  border: 1px solid var(--border-subtle);
}
.pill-btn {
  border: none;
  background: transparent;
  padding: 4px 10px;
  font-size: 12px;
  font-weight: 500;
  border-radius: 6px;
  cursor: pointer;
  color: var(--text-secondary);
  transition: all 0.15s ease;
  white-space: nowrap;
}
.pill-btn.active {
  background: var(--bg-card, #ffffff);
  color: var(--accent-ai, #6366f1);
  font-weight: 600;
  box-shadow: 0 1px 2px rgba(0, 0, 0, 0.06);
}

/* MCP 卡片网格 */
.mcp-cards-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(310px, 1fr));
  gap: 14px;
}
.mcp-card {
  border: 1px solid var(--border-subtle);
  border-radius: 12px;
  padding: 14px 16px;
  background: var(--bg-card, #ffffff);
  display: flex;
  flex-direction: column;
  gap: 8px;
  transition: all 0.2s cubic-bezier(0.4, 0, 0.2, 1);
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.02);
}
.mcp-card:hover {
  transform: translateY(-2px);
  border-color: rgba(99, 102, 241, 0.4);
  box-shadow: 0 6px 16px -2px rgba(99, 102, 241, 0.1);
}
.mcp-card.is-write {
  border-left: 3.5px solid var(--accent-warning);
}
.mcp-card.is-disabled {
  opacity: 0.72;
  border-left-color: var(--text-tertiary);
}
.mcp-card-top {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
}
.tool-card-icon {
  font-size: 20px;
}
.mcp-tool-title {
  font-size: 13.5px;
  font-weight: 700;
  color: var(--c-profiles);
}
.domain-tag {
  font-size: 10.5px;
  color: var(--text-tertiary);
}
.perm-badge-read {
  color: var(--accent-success);
  border-color: rgba(16, 185, 129, 0.3);
  font-size: 10.5px;
  font-weight: 600;
}
.perm-badge-write {
  color: var(--accent-warning);
  border-color: rgba(245, 158, 11, 0.3);
  font-size: 10.5px;
  font-weight: 600;
}
.mcp-tool-desc {
  font-size: 12.5px;
  color: var(--text-secondary);
  line-height: 1.5;
  min-height: 38px;
}
.mcp-card-specs {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin-top: auto;
}
.spec-tag {
  font-size: 10.5px;
  padding: 2px 6px;
  border-radius: 4px;
  background: rgba(15, 23, 42, 0.04);
  color: var(--text-secondary);
}
.mcp-card-bottom {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding-top: 10px;
  border-top: 1px solid var(--border-subtle);
}
.status-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: var(--accent-success);
  display: inline-block;
}
.status-dot.is-disabled {
  background: var(--text-tertiary);
}

/* 契约安全准则卡片网格 */
.guardrails-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(240px, 1fr));
  gap: 12px;
}
.guardrail-card {
  padding: 12px 14px;
  background: var(--bg-elevated);
  border: 1px solid var(--border-subtle);
  border-radius: 10px;
}
.guardrail-head {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 6px;
}
.g-icon {
  font-size: 16px;
}
.g-title {
  font-size: 13px;
  font-weight: 700;
  color: var(--text-primary);
}
.g-text {
  font-size: 12px;
  color: var(--text-secondary);
  line-height: 1.5;
  margin: 0;
}

/* ═══════════════════════════════════════════════════════════════
   Agent 技能编排 (Skills & Prompts) 专属排版与微光设计
   ═══════════════════════════════════════════════════════════════ */
.skills-center-container {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.skills-hero-title-area {
  display: flex;
  flex-direction: column;
}

.skills-main-title {
  font-size: 15.5px;
  font-weight: 700;
  color: var(--text-primary);
}

.skills-badge-vault {
  background: rgba(99, 102, 241, 0.1);
  color: var(--accent-ai, #6366f1);
  border-color: rgba(99, 102, 241, 0.25);
  font-size: 11px;
}

/* 4 项 KPI 微光带 */
.skills-kpi-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(210px, 1fr));
  gap: 12px;
  margin-top: 14px;
}

.skills-kpi-card {
  padding: 12px 14px;
  background: var(--bg-elevated, #f8fafc);
  border: 1px solid var(--border-subtle, #e2e8f0);
  border-radius: 10px;
  display: flex;
  flex-direction: column;
  gap: 4px;
  transition: all 0.2s cubic-bezier(0.4, 0, 0.2, 1);
}

.skills-kpi-card:hover {
  transform: translateY(-2px);
  border-color: rgba(99, 102, 241, 0.35);
  box-shadow: 0 4px 12px -2px rgba(99, 102, 241, 0.08);
}

.skills-kpi-top {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.skills-kpi-label {
  font-size: 11.5px;
  color: var(--text-tertiary, #9ca3af);
  font-weight: 500;
}

.skills-kpi-icon {
  font-size: 15px;
}

.skills-kpi-val {
  font-size: 18px;
  font-weight: 700;
  color: var(--text-primary, #0f172a);
}

.skills-kpi-sub {
  font-size: 11px;
  color: var(--text-secondary, #64748b);
}

/* 技能工具条与分段器 */
.skills-toolbar {
  display: flex;
  justify-content: space-between;
  align-items: center;
  flex-wrap: wrap;
  gap: 12px;
}

.skills-filter-group {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 10px;
}

/* 技能卡片网格 */
.skills-cards-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(320px, 1fr));
  gap: 14px;
}

.skill-card-v2 {
  border: 1px solid var(--border-subtle, #e2e8f0);
  border-radius: 12px;
  padding: 16px;
  background: var(--bg-card, #ffffff);
  display: flex;
  flex-direction: column;
  gap: 10px;
  transition: all 0.2s cubic-bezier(0.4, 0, 0.2, 1);
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.02);
}

.skill-card-v2:hover {
  transform: translateY(-2px);
  border-color: rgba(99, 102, 241, 0.4);
  box-shadow: 0 6px 18px -2px rgba(99, 102, 241, 0.1);
}

.skill-card-top {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
}

.skill-main-icon {
  font-size: 26px;
  line-height: 1;
}

.skill-card-name {
  font-size: 14.5px;
  font-weight: 700;
  color: var(--text-primary, #0f172a);
}

.skill-scenario-tag {
  font-size: 11px;
  color: var(--text-tertiary, #94a3b8);
  margin-top: 2px;
}

.skill-builtin-chip {
  font-size: 10.5px;
  background: rgba(99, 102, 241, 0.08);
  color: var(--accent-ai, #6366f1);
  border-color: rgba(99, 102, 241, 0.2);
  font-weight: 600;
}

.skill-card-desc {
  font-size: 12.5px;
  color: var(--text-secondary, #475569);
  line-height: 1.5;
  min-height: 38px;
}

/* 调优参数微型芯片 */
.skill-tuning-chips {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

.tuning-chip {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 2px 7px;
  background: rgba(15, 23, 42, 0.04);
  border-radius: 5px;
  font-size: 10.5px;
  border: 1px solid rgba(226, 232, 240, 0.6);
}

.tuning-k {
  color: var(--text-tertiary, #94a3b8);
}

.tuning-v {
  color: var(--accent-ai, #6366f1);
  font-weight: 700;
}

/* 触发命令与依赖工具行 */
.skill-cmds-row,
.skill-tools-row {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 11.5px;
}

.cmd-label,
.tools-label {
  font-size: 11px;
  color: var(--text-tertiary, #94a3b8);
  white-space: nowrap;
}

.cmd-tag {
  padding: 1px 6px;
  border-radius: 4px;
  background: rgba(56, 189, 248, 0.1);
  color: #0284c7;
  font-size: 11px;
  font-weight: 600;
}

.tool-tag {
  padding: 1px 6px;
  border-radius: 4px;
  background: rgba(15, 23, 42, 0.04);
  color: var(--c-profiles, #b45309);
  font-size: 10.5px;
  border: 1px solid rgba(226, 232, 240, 0.6);
}

.skill-card-bottom {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding-top: 10px;
  margin-top: auto;
  border-top: 1px solid var(--border-subtle, #f1f5f9);
}

.tag-clickable {
  cursor: pointer;
  user-select: none;
  transition: all 0.15s ease;
}
.tag-clickable:hover {
  transform: translateY(-1px);
  filter: brightness(1.15);
}
.tag-embed {
  background: rgba(16, 185, 129, 0.12) !important;
  color: #10b981 !important;
  border: 1px solid rgba(16, 185, 129, 0.28) !important;
}
.tag-rerank {
  background: rgba(139, 92, 246, 0.12) !important;
  color: #a78bfa !important;
  border: 1px solid rgba(139, 92, 246, 0.28) !important;
}

/* 移动端：卡片栅格最小宽度超过视口，统一折为单列 */
@media (max-width: 700px) {
  .vendor-models-grid,
  .skill-grid,
  .mcp-kpi-grid,
  .mcp-servers-grid,
  .mcp-cards-grid,
  .guardrails-grid,
  .skills-kpi-grid,
  .skills-cards-grid {
    grid-template-columns: 1fr;
  }
  .server-card-meta {
    grid-template-columns: 1fr;
  }
}
</style>
