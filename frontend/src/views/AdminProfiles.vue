<template>
  <div class="profiles-page">
    <div class="tabs-nav-bar row" style="gap: 8px">
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
    <div class="panel">
      <div class="panel-title">Agent 默认模型</div>
      <div class="row wrap" style="gap: 16px">
        <div style="font-size: 13px; color: var(--text-secondary)">
          新对话默认使用的协议档：
        </div>
        <n-select
          v-model:value="selectedAgentProfileId"
          style="width: 260px"
          :options="agentProfileOptions"
          :loading="agentProfileSaving"
          :disabled="loading || agentProfileSaving"
          @update:value="handleUpdateAgentProfile"
        />
        <span class="mono" style="font-size: 12px; color: var(--text-tertiary)">
          (保存即刻全局生效)
        </span>
      </div>
      <div class="profile-default-summary" v-if="selectedAgentProfile">
        <ProviderLogo :provider="getProviderLogoKey(selectedAgentProfile)"/>
        <div><strong>{{ selectedAgentProfile.model }}</strong><p>{{ selectedAgentProfile.name }} · {{ selectedAgentProfile.full_url ? '完整 URL' : 'Base URL 自动补全' }}</p></div>
        <button class="btn btn-secondary btn-sm" @click="openModal(selectedAgentProfile)">配置模型</button>
      </div>
    </div>

    <!-- 协议档列表 -->
    <div class="panel">
      <div class="panel-title">
        <div class="row" style="gap: 12px">
          <span>模型协议档</span>
          <span class="mono" style="font-size: 12px; color: var(--text-tertiary)">({{ profiles.length }} 个模型)</span>

          <!-- 视图模式切换器 -->
          <div class="view-mode-toggle">
            <button
              class="toggle-btn"
              :class="{ active: viewMode === 'cards' }"
              @click="viewMode = 'cards'"
            >
              卡片
            </button>
            <button
              class="toggle-btn"
              :class="{ active: viewMode === 'table' }"
              @click="viewMode = 'table'"
            >
              表格
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

      <div class="profile-filters">
        <n-input v-model:value="profileSearch" clearable placeholder="搜索名称、模型或端点…" aria-label="搜索协议档"/>
        <n-select v-model:value="vendorFilter" :options="vendorFilters" clearable placeholder="全部供应商"/>
        <n-select v-model:value="usageFilter" :options="usageFilters" clearable placeholder="全部用途"/>
        <span>{{ filteredProfiles.length }} / {{ profiles.length }} 个协议档</span>
      </div>
      <!-- 模式 1：供应商分类多卡片视图 -->
      <p v-if="loading" role="status" class="small tertiary">正在加载协议档…</p>
      <div v-if="viewMode === 'cards'" class="vendor-cards-container">
        <div
          v-for="group in vendorGroups"
          :key="group.key"
          class="vendor-group-card"
        >
          <div class="vendor-group-header">
            <div class="vendor-info">
              <div class="vendor-title-row">
                <ProviderLogo :provider="group.logoKey" />
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
                + 添加模型
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
                <button
                  :disabled="pinging[p.id]"
                  v-if="pingStates[p.id]"
                  class="ping-badge"
                  :class="pingStates[p.id].ok ? 'ok' : 'err'"
                  title="点击重新探活"
                  @click="handlePing(p)"
                >
                  {{ pingStates[p.id].ok ? `● 正常 (${pingStates[p.id].latencyMs ?? '—'}ms)` : '✕ 连接失败' }}
                </button>
                <button v-else class="link-btn small" :disabled="pinging[p.id]" @click="handlePing(p)">
                  {{ pinging[p.id] ? '探活中…' : '探活' }}
                </button>
              </div>

              <div class="model-chip-meta">
                <span class="mono model-id-tag" :title="p.model">{{ p.model }}</span>
                <span class="mono protocol-tag">{{ p.protocol }}</span>
                <span v-if="p.full_url" class="url-mode-tag">完整 URL</span>
                <span class="mono window-tag" title="上下文窗口容量">{{ formatContextWindow(p.context_window) }}</span>
              </div>

              <div class="model-chip-bottom">
                <div class="row" style="gap: 4px; flex-wrap: wrap">
                  <span v-if="p.usages?.includes('target')" class="kind-tag kind-benchmark">被测</span>
                  <span v-if="p.usages?.includes('judge')" class="kind-tag kind-cases">裁判</span>
                  <span v-if="p.usages?.includes('agent')" class="kind-tag kind-rag">Agent</span>
                </div>
                <div class="row" style="gap: 6px">
                  <button v-if="p.usages?.includes('agent')" class="link-btn small" @click="handleOpenAgentPrompt(p)">提示词</button>
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

        <div v-if="!loading && filteredProfiles.length === 0" class="empty-state-wrap">
          <EmptyState title="暂无匹配的协议档" description="调整搜索条件，或新增供应商协议档。">
            <template #action>
              <button class="btn btn-primary btn-sm" @click="openModal(null)">新增协议档</button>
            </template>
          </EmptyState>
        </div>
      </div>

      <!-- 模式 2：详细表格视图 -->
      <div v-else class="profile-table-scroll"><table class="ds-table">
        <thead>
          <tr>
            <th>协议档名称</th>
            <th style="width: 160px">协议类型</th>
            <th style="width: 140px">模型标识</th>
            <th style="width: 100px">上下文窗口</th>
            <th>请求地址</th>
            <th style="width: 140px">用途标签</th>
            <!-- P2 连通性探活列（对齐原型 admin-profiles.html：行内 ping-badge） -->
            <th style="width: 130px">探活</th>
            <th style="width: 200px; text-align: right">操作</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="p in filteredProfiles" :key="p.id">
            <td style="font-weight: 600; font-size: 14px">
              <span class="row" style="gap: 6px">
                <ProviderLogo :provider="getProviderLogoKey(p)" compact :size="20" /><span>{{ p.name }}</span>
                <!-- P4 名称徽标对齐原型「★ Agent 核心驱动」 -->
                <span v-if="p.id === selectedAgentProfileId" class="tag-soft agent-core-tag">★ Agent 核心驱动</span>
              </span>
            </td>
            <td>
              <span class="mono" style="font-size: 12px">{{ p.protocol }}</span>
            </td>
            <td>
              <span class="mono" style="font-size: 12.5px; font-weight: 600">{{ p.model }}</span>
            </td>
            <td>
              <span class="mono window-tag">{{ formatContextWindow(p.context_window) }}</span>
            </td>
            <td>
              <span class="mono" style="font-size: 11.5px; color: var(--text-secondary)">{{ p.base_url }}</span>
              <span v-if="p.full_url" class="url-mode-tag">完整 URL</span>
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
              <button
                :disabled="pinging[p.id]"
                v-if="pingStates[p.id]"
                class="ping-badge"
                :class="pingStates[p.id].ok ? 'ok' : 'err'"
                title="点击重新探活"
                @click="handlePing(p)"
              >
                {{ pingStates[p.id].ok ? `● 正常 (${pingStates[p.id].latencyMs ?? '—'}ms)` : '✕ 连接失败' }}
              </button>
              <button v-else class="link-btn" :disabled="pinging[p.id]" @click="handlePing(p)">
                {{ pinging[p.id] ? '探活中…' : '探活' }}
              </button>
            </td>
            <td style="text-align: right">
              <div class="row" style="justify-content: flex-end; gap: 4px">
                <button class="link-btn" :disabled="checkingId === p.id" @click="handleCheck(p)">
                  {{ checkingId === p.id ? '检查中...' : '连通详情' }}
                </button>
                <button v-if="p.usages?.includes('agent')" class="link-btn" @click="handleOpenAgentPrompt(p)">提示词</button>
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

          <tr v-if="!loading && filteredProfiles.length === 0">
            <td colspan="8">
              <EmptyState title="暂无匹配的协议档" description="点击右上角新增 OpenAI / Anthropic 协议档">
                <template #action>
                  <button class="btn btn-primary btn-sm" @click="openModal(null)">新增协议档</button>
                </template>
              </EmptyState>
            </td>
          </tr>
        </tbody>
      </table></div>
    </div>

    </template>

    <!-- Tab 2：MCP 工具中心（V1.0 只读；外部 MCP Server 管理能力受控） -->
    <template v-else-if="activeTab === 'mcp'">
      <div class="mcp-center-container">
        <!-- 1. 顶部全景与健康自检操作栏 -->
        <div class="panel mb16">
          <div class="row-between mb8" style="flex-wrap: wrap; gap: 12px">
            <div class="mcp-hero-title-area">
              <div class="row" style="gap: 8px; align-items: center">
                <span class="mcp-main-title">🛠 MCP 服务器与工具中心 (Tools & MCP Hub)</span>
                <span class="tag-soft mcp-badge-host">Host 模式 · 受控沙箱</span>
                <span class="badge" :class="mcpBadgeClass">
                  {{ mcpBadgeText }}
                </span>
              </div>
              <div class="small tertiary mt4" style="line-height: 1.5">
                支持原生进程内 ToolCall（read/bash/write 等）与受控 MCP Server（platform.tasks 任务桥）；严格长短任务分离与沙箱隔离。
              </div>
            </div>

            <!-- 操作按钮组 -->
            <div class="row" style="gap: 8px; align-items: center">
              <button
                class="btn btn-secondary btn-sm"
                :disabled="mcpHealthChecking"
                title="全面测试原生沙箱与 MCP Server 连通性"
                @click="handleRunHealthCheck"
              >
                ⚡ {{ mcpHealthChecking ? '自检中…' : '全通道健康自检' }}
              </button>
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
                <span class="mcp-kpi-label">已装载工具全集</span>
                <span class="mcp-kpi-icon">🛠️</span>
              </div>
              <div class="mcp-kpi-val num">{{ mcpTools.length }} <span class="unit">个活跃工具</span></div>
              <div class="mcp-kpi-sub text-success">
                ● {{ nativeTools.length }} 原生 ToolCall + {{ mcpExtTools.length }} 内部 MCP 扩展
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
              <div class="mcp-kpi-sub">严格会话沙箱校验 · 免审批只读</div>
            </div>

            <div class="mcp-kpi-card">
              <div class="mcp-kpi-top">
                <span class="mcp-kpi-label">通道健康度自检</span>
                <span class="mcp-kpi-icon">⚡</span>
              </div>
              <div class="mcp-kpi-val mono" :class="mcpHealthResult?.ok ? 'text-success' : 'text-ai'">
                {{ mcpHealthResult ? `${mcpHealthResult.total_latency_ms}ms · 正常` : '就绪待检' }}
              </div>
              <div class="mcp-kpi-sub mono text-info">
                {{ mcpServerStatusText }}
              </div>
            </div>

            <div class="mcp-kpi-card">
              <div class="mcp-kpi-top">
                <span class="mcp-kpi-label">执行沙箱与隔离</span>
                <span class="mcp-kpi-icon">🔒</span>
              </div>
              <div class="mcp-kpi-val num" style="color: var(--accent-ai)">bwrap <span class="unit">沙箱</span></div>
              <div class="mcp-kpi-sub">无网络 · 只读根系统 · 15s超时</div>
            </div>
          </div>
        </div>

        <!-- 3. MCP 服务节点矩阵 (MCP Servers & Host Node Status) -->
        <div class="panel mb16">
          <div class="row-between mb12">
            <div class="row" style="gap: 8px; align-items: center">
              <span class="panel-title" style="margin: 0">工具通道架构（原生 ToolCall + 内部受控 MCP Server + 外部网关）</span>
              <span class="tag-soft">{{ mcpTools.length > 0 ? `已加载 ${mcpTools.length} 个工具` : '尚未加载' }}</span>
            </div>
            <div class="row" style="gap: 6px; align-items: center">
              <button
                class="btn btn-secondary btn-xs"
                :disabled="mcpHealthChecking"
                @click="handleRunHealthCheck"
              >
                {{ mcpHealthChecking ? '探活中…' : '▶ 通道探活' }}
              </button>
            </div>
          </div>

          <div class="mcp-servers-grid">
            <!-- ① platform.native：原生 ToolCall 基础工具（NativeToolExecutor 直连） -->
            <div class="mcp-server-card builtin-server">
              <div class="server-card-head">
                <div class="row" style="gap: 8px; align-items: center">
                  <span class="server-icon">⚡</span>
                  <div>
                    <div class="row" style="gap: 6px; align-items: center">
                      <span class="server-name">platform.native · 原生基础工具</span>
                      <span class="tag-soft" style="color: var(--accent-success)">已注册 · 当前纯对话 Agent 未接线</span>
                    </div>
                    <div class="mono small tertiary">transport=native · 供未来 ToolNode 启用 · 当前不注入模型</div>
                  </div>
                </div>

                <div class="row" style="gap: 8px; align-items: center">
                  <span class="ping-badge" :class="mcpRequestState === 'success' ? 'ok' : 'err'">
                    {{ mcpRequestState === 'success' ? `● 已注册 · ${nativeTools.length} 个工具` : '— 未加载' }}
                  </span>
                </div>
              </div>

              <div class="server-card-meta">
                <div class="server-meta-item">
                  <span class="meta-k">执行通道:</span>
                  <span class="meta-v mono">NativeToolExecutor（进程内毫秒级直连）</span>
                </div>
                <div class="server-meta-item">
                  <span class="meta-k">原生工具:</span>
                  <span class="meta-v mono font-bold text-success">
                    <span v-if="nativeTools.length > 0">
                      {{ nativeTools.map(t => t.display_name || t.name).join(' · ') }}
                    </span>
                    <span v-else>尚未加载</span>
                  </span>
                </div>
                <div class="server-meta-item">
                  <span class="meta-k">沙箱隔离:</span>
                  <span class="meta-v">bash → bwrap 进程隔离 · read/write/edit → 会话隔离工作区</span>
                </div>
                <div class="server-meta-item">
                  <span class="meta-k">通道自检:</span>
                  <span class="meta-v mono" style="color: var(--accent-success)">
                    {{ mcpHealthResult?.channels?.native?.message || '健康状态正常 · 读写正常' }}
                  </span>
                </div>
              </div>
            </div>

            <!-- ② platform.tasks：内部受控 MCP Server（MCPClientManager 调用） -->
            <div class="mcp-server-card" :class="mcpExtTools.length > 0 ? 'builtin-server' : 'external-server'">
              <div class="server-card-head">
                <div class="row" style="gap: 8px; align-items: center">
                  <span class="server-icon">🔗</span>
                  <div>
                    <div class="row" style="gap: 6px; align-items: center">
                      <span class="server-name">platform.tasks · 内部 MCP Server</span>
                      <span class="tag-soft" style="color: var(--accent-ai)">已注册 · 当前纯对话 Agent 未接线</span>
                    </div>
                    <div class="mono small tertiary">transport=mcp · 评测任务队列桥 · 供未来 ToolNode 启用</div>
                  </div>
                </div>

                <span class="ping-badge" :class="mcpExtTools.length > 0 ? 'ok' : 'err'">
                  {{ mcpExtTools.length > 0 ? `● 已注册 · ${mcpExtTools.length} 个工具` : '— 未加载' }}
                </span>
              </div>

              <div class="server-card-meta">
                <div class="server-meta-item" v-for="g in mcpServerGroups" :key="g.server_id">
                  <span class="meta-k mono">{{ g.server_id }}:</span>
                  <span class="meta-v mono font-bold" style="color: var(--accent-ai)">
                    {{ g.tools.map(t => t.display_name || t.name).join(' · ') }}
                  </span>
                </div>
                <div class="server-meta-item">
                  <span class="meta-k">MCP 协议:</span>
                  <span class="meta-v" style="color: var(--accent-ai)">✅ 受控 MCP Host 模式 · InProcessProvider 桥接</span>
                </div>
                <div class="server-meta-item">
                  <span class="meta-k">通道自检:</span>
                  <span class="meta-v mono" style="color: var(--accent-ai)">
                    {{ mcpHealthResult?.channels?.internal_mcp?.message || 'PostgreSQL tasks 状态机连通正常' }}
                  </span>
                </div>
              </div>
            </div>

            <!-- ③ External MCP Server Gateway (受控未启用) -->
            <div class="mcp-server-card external-server">
              <div class="server-card-head">
                <div class="row" style="gap: 8px; align-items: center">
                  <span class="server-icon">🌐</span>
                  <div>
                    <div class="row" style="gap: 6px; align-items: center">
                      <span class="server-name">External MCP Server Gateway</span>
                      <span class="tag-soft" style="color: var(--text-tertiary)">外部隔离保护中</span>
                    </div>
                    <div class="mono small tertiary">受控隔离网关 · 动态扩展槽位预留</div>
                  </div>
                </div>

                <span class="tag-soft" style="border-color: var(--border-subtle)">受控边界保护</span>
              </div>

              <div class="server-card-meta" style="margin-top: 10px">
                <div class="server-meta-item">
                  <span class="meta-k">网关状态:</span>
                  <span class="meta-v">受控 Standby 隔离运行 · 0 个外部挂载</span>
                </div>
                <div class="server-meta-item">
                  <span class="meta-k">安全防护:</span>
                  <span class="meta-v">防范外部不可控长延迟与越权代码注入</span>
                </div>
              </div>
            </div>
          </div>
        </div>

        <!-- 4. 工具清单与多维筛选 (Tools Manifest & Multi-Dimensional Filters) -->
        <div class="panel mb16">
          <div class="mcp-toolbar mb16">
            <div class="mcp-filter-group">
              <!-- 工具通道筛选（全部 / 原生 ToolCall / 内部 MCP / 第三方网关） -->
              <div class="pill-segmented">
                <button
                  class="pill-btn"
                  :class="{ active: mcpTransportFilter === 'all' }"
                  @click="mcpTransportFilter = 'all'"
                >
                  全部 ({{ mcpTools.length }})
                </button>
                <button
                  class="pill-btn"
                  :class="{ active: mcpTransportFilter === 'native' }"
                  @click="mcpTransportFilter = 'native'"
                >
                  ⚡ 原生 ToolCall ({{ nativeTools.length }})
                </button>
                <button
                  class="pill-btn"
                  :class="{ active: mcpTransportFilter === 'mcp' }"
                  @click="mcpTransportFilter = 'mcp'"
                >
                  🔗 内部 MCP Server ({{ mcpExtTools.length }})
                </button>
                <button
                  class="pill-btn"
                  :class="{ active: mcpTransportFilter === 'external' }"
                  @click="mcpTransportFilter = 'external'"
                >
                  🌐 第三方网关 (受控)
                </button>
              </div>

              <!-- 权限筛选 -->
              <div v-if="mcpTransportFilter !== 'external'" class="pill-segmented">
                <button
                  class="pill-btn"
                  :class="{ active: mcpPermFilter === 'all' }"
                  @click="mcpPermFilter = 'all'"
                >
                  全部权限
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
              <div v-if="mcpTransportFilter !== 'external'" style="width: 140px">
                <n-select
                  v-model:value="mcpDomainFilter"
                  size="small"
                  :options="domainFilterOptions"
                />
              </div>

              <!-- 搜索框 -->
              <div v-if="mcpTransportFilter !== 'external'" style="width: 220px">
                <n-input
                  v-model:value="mcpSearchKeyword"
                  size="small"
                  placeholder="搜索工具名、入参或说明…"
                  clearable
                >
                  <template #prefix>🔍</template>
                </n-input>
              </div>
            </div>

            <!-- 视图切换器 -->
            <div v-if="mcpTransportFilter !== 'external'" class="view-mode-toggle">
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

          <!-- ═════ 视图 1：第三方/外部 MCP 网关说明面板 ═════ -->
          <div v-if="mcpTransportFilter === 'external'" class="external-gateway-panel">
            <div class="ext-hero-box">
              <div class="ext-icon">🌐</div>
              <div style="flex: 1">
                <div class="ext-title">第三方与外部 MCP Server 接入规范 (External MCP Gateway)</div>
                <div class="ext-desc">
                  平台架构采用严格的长短任务分离与沙箱保护机制。当前外部 MCP 网关处于受控 Standby 状态，提供标准化的协议转换、安全拦截与预留扩展插槽。
                </div>
              </div>
              <button class="btn btn-sign btn-sm" @click="handleOpenAddExternalServer">
                + 申请接入外部 Server
              </button>
            </div>

            <div class="ext-grid mt16">
              <div class="ext-card">
                <div class="ext-card-title">🔒 传输与通信协议支持</div>
                <div class="ext-card-content">
                  • <strong>stdio / 管道隔离</strong>：在独立安全沙箱中启动子进程，通过标准输入输出传递 JSON-RPC 消息。<br>
                  • <strong>SSE (Server-Sent Events)</strong>：基于 HTTP 的单向流式事件传输，适用于远程微服务与集中式 Tool 服务。<br>
                  • <strong>HTTP Stream</strong>：支持长连接分块流式回传工具执行中间状态。
                </div>
              </div>

              <div class="ext-card">
                <div class="ext-card-title">🛡️ 安全门禁与风控策略</div>
                <div class="ext-card-content">
                  • <strong>执行超时熔断</strong>：单个外部工具调用严格限制在 30 秒以内，超长任务必须改走异步任务队列。<br>
                  • <strong>敏感凭据过滤</strong>：双向通信经由 <code>redact_secrets()</code> 引擎，严防 API Key、Token 泄漏到外部。<br>
                  • <strong>输入输出强校验</strong>：所有参数与返回体必须通过预注册的 JSON Schema 严格校验。
                </div>
              </div>

              <div class="ext-card">
                <div class="ext-card-title">🔌 动态扩展插槽与接入流程</div>
                <div class="ext-card-content">
                  1. 提交外部 MCP Server 配置（服务名称、传输协议、鉴权凭据、能力清单）。<br>
                  2. 平台执行自动连通性探活与 Schema 静态安全审计。<br>
                  3. 审核通过后注入 <code>MCPClientManager</code> 目录池，供 Agent 在对话中动态按需调用。
                </div>
              </div>
            </div>
          </div>

          <!-- ═════ 视图 2：模式 A - 现代卡片网格 ═════ -->
          <div v-else-if="mcpViewMode === 'cards'" class="mcp-cards-grid">
            <div
              v-for="t in filteredMcpTools"
              :key="t.name"
              class="mcp-card"
              :class="{ 'is-write': t.permission === 'write', 'is-disabled': t.enabled === false, 'is-native': t.transport === 'native' }"
            >
              <div class="mcp-card-top">
                <div class="row" style="gap: 8px; align-items: center">
                  <span class="tool-card-icon">{{ getToolDomain(t.name).icon }}</span>
                  <div>
                    <div class="mcp-tool-title">{{ t.display_name || t.name }}</div>
                    <div class="domain-tag mono" style="font-size: 11px; color: var(--text-tertiary)">{{ t.name }}</div>
                  </div>
                </div>

                <div class="row" style="gap: 4px; flex-direction: column; align-items: flex-end">
                  <!-- transport 标签：区分原生/MCP -->
                  <span
                    class="tag-soft"
                    :style="t.transport === 'native'
                      ? 'color: var(--accent-success); border-color: rgba(16,185,129,0.3)'
                      : 'color: var(--accent-ai); border-color: rgba(139,92,246,0.3)'"
                  >
                    {{ t.transport === 'native' ? '⚡ 原生' : '🔗 内部 MCP' }}
                  </span>
                  <!-- 权限/风险级别 -->
                  <span
                    class="tag-soft"
                    :class="getRiskBadge(t.risk_level).cls"
                  >
                    {{ getRiskBadge(t.risk_level).label }}
                  </span>
                </div>
              </div>

              <div class="mcp-tool-desc">{{ t.desc }}</div>

              <!-- 输入输出参数概要预览 -->
              <div class="tool-schema-brief">
                <div class="schema-brief-row">
                  <span class="brief-k">📥 入参:</span>
                  <span class="brief-v mono">{{ getToolParamsPreview(t) }}</span>
                </div>
                <div class="schema-brief-row">
                  <span class="brief-k">📤 出参:</span>
                  <span class="brief-v mono">{{ getToolOutputsPreview(t) }}</span>
                </div>
              </div>

              <div class="mcp-card-specs">
                <div class="spec-tag mono">{{ t.enabled === false ? '⏸ 未挂载' : `⚡ 超时: ${t.timeout_s ?? '?'}s` }}</div>
                <div class="spec-tag mono">{{ t.supports_streaming ? '📡 流式' : '📦 JSON' }}</div>
                <div class="spec-tag">{{ t.transport === 'native' ? '⚡ 进程直连' : '🛡️ MCP Host' }}</div>
              </div>

              <div class="mcp-card-bottom">
                <div class="row" style="gap: 6px; align-items: center">
                  <span class="status-dot" :class="{ 'is-disabled': t.enabled === false }"></span>
                  <span class="small tertiary">
                    {{ t.transport === 'native'
                      ? (t.risk_level === 'code' ? 'bwrap 沙箱 · 活跃' : '进程内直连 · 活跃')
                      : (t.enabled === false ? '独立 MCP · 能力未启用' : 'InProcess Host · 活跃')
                    }}
                  </span>
                </div>
                <button
                  class="btn btn-secondary btn-xs"
                  @click="handleOpenMcpModal(t)"
                >
                  💻 代码与契约
                </button>
              </div>
            </div>

            <div v-if="filteredMcpTools.length === 0" class="empty-state-wrap" style="grid-column: 1 / -1">
              <EmptyState :title="mcpEmptyTitle" :description="mcpEmptyDescription" />
            </div>
          </div>

          <!-- ═════ 视图 3：模式 B - 契约矩阵表格 ═════ -->
          <div v-else class="table-responsive">
            <table class="ds-table">
              <thead>
                <tr>
                  <th style="width: 180px">工具名称</th>
                  <th style="width: 90px">通道类型</th>
                  <th style="width: 110px">业务领域</th>
                  <th>职责说明</th>
                  <th style="width: 150px">输入参数概要</th>
                  <th style="width: 130px">输出结构</th>
                  <th style="width: 100px">风险级别</th>
                  <th style="width: 70px">超时</th>
                  <th style="width: 110px; text-align: right">操作</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="t in filteredMcpTools" :key="t.name">
                  <td>
                    <div class="row" style="gap: 6px; align-items: center">
                      <span>{{ getToolDomain(t.name).icon }}</span>
                      <div>
                        <div style="font-weight: 700; font-size: 13px">{{ t.display_name || t.name }}</div>
                        <div class="mono" style="font-size: 10.5px; color: var(--text-tertiary)">{{ t.name }}</div>
                      </div>
                    </div>
                  </td>
                  <td>
                    <span
                      class="tag-soft"
                      :style="t.transport === 'native'
                        ? 'color: var(--accent-success); border-color: rgba(16,185,129,0.3)'
                        : 'color: var(--accent-ai); border-color: rgba(139,92,246,0.3)'"
                    >
                      {{ t.transport === 'native' ? '⚡ 原生' : '🔗 内部 MCP' }}
                    </span>
                  </td>
                  <td>
                    <span class="tag-soft">{{ getToolDomain(t.name).label }}</span>
                  </td>
                  <td class="small" style="color: var(--text-primary)">{{ t.desc }}</td>
                  <td class="mono small" style="color: var(--c-profiles)">{{ getToolParamsPreview(t) }}</td>
                  <td class="mono small text-success">{{ getToolOutputsPreview(t) }}</td>
                  <td>
                    <span class="tag-soft" :class="getRiskBadge(t.risk_level).cls">
                      {{ getRiskBadge(t.risk_level).label }}
                    </span>
                  </td>
                  <td class="mono small text-success">{{ t.timeout_s ? `${t.timeout_s}s` : '—' }}</td>
                  <td style="text-align: right">
                    <button class="link-btn" @click="handleOpenMcpModal(t)">
                      💻 代码与契约
                    </button>
                  </td>
                </tr>

                <tr v-if="filteredMcpTools.length === 0">
                  <td colspan="9">
                    <EmptyState :title="mcpEmptyTitle" :description="mcpEmptyDescription" />
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

    <!-- Tab 3：Agent 技能编排（技能文件可受控编辑，核心提示词保持只读） -->
    <template v-else-if="activeTab === 'skills'">
      <div class="skills-center-container">
        <!-- 1. 顶部全景与操作栏 -->
        <div class="panel mb16">
          <div class="row-between mb8" style="flex-wrap: wrap; gap: 12px">
            <div class="skills-hero-title-area">
              <div class="row" style="gap: 8px; align-items: center">
                <span class="skills-main-title">🧠 Agent 技能编排 (Skills & Prompts)</span>
                <span class="tag-soft skills-badge-vault">统一 SKILL.md · 4 大内置场景</span>
                <span class="badge badge-succeeded">核心提示词受控</span>
              </div>
              <div class="small tertiary mt4" style="line-height: 1.5">
                技能目录只读取文件头部，完整工作流仅在预览或本轮选中后读取；每个 Agent 协议档均可维护受审计的补充提示词。
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
                :disabled="!selectedAgentProfile"
                :title="selectedAgentProfile ? `查看或编辑 ${selectedAgentProfile.name} 的补充提示词` : '请先在大模型协议档页指定 Agent 协议档'"
                @click="handleOpenAgentPrompt()"
              >
                查看 / 编辑当前 Agent 提示词
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
              <div class="skills-kpi-val mono" style="color: var(--accent-ai)">核心 + 补充层</div>
              <div class="skills-kpi-sub">核心只读 · 协议档补充层可审计</div>
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
                  <span class="small tertiary">📄 统一 SKILL.md · 按需加载</span>
                </div>
                <div class="row" style="gap: 6px">
                  <button class="btn btn-secondary btn-xs" @click="handleOpenSkillModal(s)">编排详情</button>
                  <button class="btn btn-sign btn-xs" @click="handleOpenSkillFile(s)">预览 / 编辑</button>
                </div>
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
                    <div class="row" style="justify-content: flex-end; gap: 6px">
                      <button class="link-btn" @click="handleOpenSkillModal(s)">编排详情</button>
                      <button class="link-btn" @click="handleOpenSkillFile(s)">预览 / 编辑</button>
                    </div>
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
                <span class="g-title">核心提示词与补充层分离</span>
              </div>
              <p class="g-text">
                核心系统提示词由 Harness 固定生成并可预览，<strong>不能被动态覆盖</strong>；协议档只能保存受审计的补充提示词，运行时核心规则始终优先。
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
                <span class="g-title">技能文件渐进式披露</span>
              </div>
              <p class="g-text">
                技能目录仅读取 <code>SKILL.md</code> 固定头部；仅在预览或计划选中后才加载完整工作流。编辑使用修订指纹防覆盖并写入审计记录。
              </p>
            </div>
          </div>
        </div>
      </div>
    </template>

    <!-- Tab: 全局向量与重排模型 (RAG) 独立专区 -->
    <template v-else-if="activeTab === 'rag_models'">
      <div class="panel mb16 rag-panel-container">
        <!-- 头部说明卡片 -->
        <div class="rag-intro-banner mb16">
          <div class="row-between wrap" style="gap: 12px">
            <div class="row" style="gap: 10px; align-items: flex-start">
              <div class="rag-badge-icon">🔤</div>
              <div>
                <div class="rag-intro-title">全局向量与重排模型体系 (Global RAG System Models)</div>
                <div class="rag-intro-desc">
                  全平台集中托管单一向量嵌入（Embedding）与交叉重排序（Reranker）模型。用于知识库切块向量化、语义混合检索与二次深度精排。配置保存后自动同步受控环境并实时对全平台任务生效。
                </div>
              </div>
            </div>
            <div class="rag-scope-tag">
              <span class="dot-live">●</span> 全局生效 · 零冗余配置
            </div>
          </div>
        </div>

        <div class="rag-models-grid">
          <!-- 1. 全局向量嵌入模型 -->
          <div class="card p16 rag-model-card rag-card-embedding">
            <div class="rag-card-header mb12">
              <div class="row" style="gap: 8px">
                <span class="rag-type-pill pill-embedding">🔤 向量嵌入 (Dense Embeddings)</span>
                <span class="rag-model-sub">知识库向量化 & 提问检索</span>
              </div>
              <span v-if="ragModelsForm.has_embedding_api_key" class="key-status-badge ok" title="受控环境文件已安全加密存储独立密钥">
                🔒 ● 已配置独立密钥
              </span>
              <span v-else class="key-status-badge none" title="未配置独立密钥时将使用免密或平台缺省">
                ○ 留空使用平台全局/免密
              </span>
            </div>

            <!-- 能力标签 -->
            <div class="rag-pills-row mb12">
              <span class="rag-feature-tag">✓ 知识库切块向量化</span>
              <span class="rag-feature-tag">✓ 提问语义混合检索</span>
              <span class="rag-feature-tag">✓ Cosine / Dot 相似度</span>
            </div>

            <div class="field mb12">
              <label class="field-label">常用 Embedding 预设一键填充</label>
              <n-select
                :options="embeddingPresetOptions"
                placeholder="⚡ 选择厂商常用向量模型预设..."
                @update:value="handleSelectEmbeddingPreset"
              />
            </div>

            <div class="field mb12">
              <label class="field-label">Embedding Base URL <span class="req">*</span></label>
              <n-input
                v-model:value="ragModelsForm.embedding_base_url"
                placeholder="例如：https://api.siliconflow.cn/v1 或 https://api.openai.com/v1"
              />
            </div>

            <div class="field mb12">
              <label class="field-label">Embedding 模型标识 (Model ID) <span class="req">*</span></label>
              <n-input
                v-model:value="ragModelsForm.embedding_model"
                placeholder="例如：BAAI/bge-large-zh-v1.5 或 text-embedding-3-large"
              />
            </div>

            <div class="field mb12">
              <label class="field-label">Embedding API Key (平台受控加密写入 .env，留空保留原密钥)</label>
              <n-input
                v-model:value="ragModelsForm.embedding_api_key"
                type="password"
                show-password-on="click"
                :placeholder="ragModelsForm.has_embedding_api_key ? '********* (已配置密钥，留空保留原密钥)' : '可选；私有端点或免密模型可留空'"
              />
            </div>

            <!-- 探活测试操作与状态 -->
            <div class="rag-check-row mt8">
              <button
                class="btn btn-secondary btn-xs"
                :disabled="checkingEmbedding || !ragModelsForm.embedding_base_url || !ragModelsForm.embedding_model"
                @click="handleCheckEmbedding"
              >
                {{ checkingEmbedding ? '探活中…' : '⚡ 端点探活测试' }}
              </button>
              <div v-if="embeddingCheckResult" class="rag-check-feedback" :class="embeddingCheckResult.ok ? 'success' : 'fail'">
                <span v-if="embeddingCheckResult.ok">✓ 连通正常 ({{ embeddingCheckResult.latency_ms }}ms)</span>
                <span v-else>✕ {{ embeddingCheckResult.message }}</span>
              </div>
            </div>
          </div>

          <!-- 2. 全局重排序模型 -->
          <div class="card p16 rag-model-card rag-card-reranker">
            <div class="rag-card-header mb12">
              <div class="row" style="gap: 8px">
                <span class="rag-type-pill pill-reranker">🎯 语义重排 (Cross-Encoder Rerank)</span>
                <span class="rag-model-sub">Top-K 降噪 & 精排打分</span>
              </div>
              <span v-if="ragModelsForm.has_reranker_api_key" class="key-status-badge ok" title="受控环境文件已安全加密存储独立密钥">
                🔒 ● 已配置独立密钥
              </span>
              <span v-else class="key-status-badge none" title="未配置独立密钥时将使用免密或平台缺省">
                ○ 留空使用平台全局/免密
              </span>
            </div>

            <!-- 能力标签 -->
            <div class="rag-pills-row mb12">
              <span class="rag-feature-tag">✓ 检索候选 Top-K 交叉打分</span>
              <span class="rag-feature-tag">✓ 过滤无关噪音段落</span>
              <span class="rag-feature-tag">✓ 显著提升黄金 QA 召回率</span>
            </div>

            <div class="field mb12">
              <label class="field-label">常用 Reranker 预设一键填充</label>
              <n-select
                :options="rerankerPresetOptions"
                placeholder="⚡ 选择厂商常用重排模型预设..."
                @update:value="handleSelectRerankerPreset"
              />
            </div>

            <div class="field mb12">
              <label class="field-label">Reranker Base URL <span class="req">*</span></label>
              <n-input
                v-model:value="ragModelsForm.reranker_base_url"
                placeholder="例如：https://api.siliconflow.cn/v1 或 https://api.jina.ai/v1"
              />
            </div>

            <div class="field mb12">
              <label class="field-label">Reranker 模型标识 (Model ID) <span class="req">*</span></label>
              <n-input
                v-model:value="ragModelsForm.reranker_model"
                placeholder="例如：BAAI/bge-reranker-v2-m3 或 jina-reranker-v2-base-multilingual"
              />
            </div>

            <div class="field mb12">
              <label class="field-label">Reranker API Key (平台受控加密写入 .env，留空保留原密钥)</label>
              <n-input
                v-model:value="ragModelsForm.reranker_api_key"
                type="password"
                show-password-on="click"
                :placeholder="ragModelsForm.has_reranker_api_key ? '********* (已配置密钥，留空保留原密钥)' : '可选；私有端点或免密模型可留空'"
              />
            </div>

            <!-- 探活测试操作与状态 -->
            <div class="rag-check-row mt8">
              <button
                class="btn btn-secondary btn-xs"
                :disabled="checkingReranker || !ragModelsForm.reranker_base_url || !ragModelsForm.reranker_model"
                @click="handleCheckReranker"
              >
                {{ checkingReranker ? '探活中…' : '⚡ 端点探活测试' }}
              </button>
              <div v-if="rerankerCheckResult" class="rag-check-feedback" :class="rerankerCheckResult.ok ? 'success' : 'fail'">
                <span v-if="rerankerCheckResult.ok">✓ 连通正常 ({{ rerankerCheckResult.latency_ms }}ms)</span>
                <span v-else>✕ {{ rerankerCheckResult.message }}</span>
              </div>
            </div>
          </div>
        </div>

        <!-- 底部操作与提示 -->
        <div class="rag-footer-bar mt16">
          <span class="rag-footer-tip">💡 修改完成后点击保存即可立即写入受控环境，并在全平台知识库切块与 RAG 任务中实时生效。</span>
          <div class="row" style="gap: 10px">
            <button class="btn btn-secondary btn-sm" :disabled="ragModelsLoading" @click="loadRagModels">
              重置 / 刷新
            </button>
            <button class="btn btn-primary btn-sm" :disabled="ragModelsSaving" @click="saveRagModels">
              {{ ragModelsSaving ? '保存中…' : '保存全局 RAG 模型配置' }}
            </button>
          </div>
        </div>
      </div>
    </template>

    <!-- Tab: Agent 运行时与主机治理（写入 /api/admin/settings.runtime，带审计） -->
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

        <div class="panel-title mb8">默认权限等级（全局默认，会话可覆盖）</div>
        <p class="small tertiary mb12">
          档1 请求批准：写文件/联网/bash 均需逐次批准；档2 帮我批准：工作区写入与联网自动，破坏性命令仍需批准；
          档3 完全访问：全部自动，但破坏性命令仍需批准、灾难性命令一律拒绝。
        </p>
        <div class="field mb16" style="width: 320px">
          <span class="field-label">全局默认档位</span>
          <n-select v-model:value="runtimeForm.permission_tier_default" :options="permissionTierOptions" style="width: 100%" />
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

    <AgentSkillFileModal
      v-model:show="showSkillFileModal"
      :skill-id="selectedSkillFileId"
    />

    <AgentPromptModal
      v-model:show="showAgentPromptModal"
      :profile-id="promptProfile?.id || null"
      :profile-name="promptProfile?.name || ''"
    />
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { useMessage, useDialog, NSelect, NInput, NInputNumber, NSwitch } from 'naive-ui'
import { api } from '../api/http'
import type { Profile, ProfileCheckOut, McpTool, McpHealthCheckResponse } from '../api/types'
import EmptyState from '../components/common/EmptyState.vue'
import ProviderLogo, { type ProviderLogoKey } from '../components/ProviderLogo.vue'
import { getProviderLogoKey } from '../utils/providerLogo'
import { PROFILE_VENDORS, getProfileVendor } from '../utils/profileVendors'
import ProfileModal from '../components/modals/ProfileModal.vue'
import CheckResultModal from '../components/modals/CheckResultModal.vue'
import McpToolModal from '../components/modals/McpToolModal.vue'
import SkillDetailModal, { type SkillDetail } from '../components/modals/SkillDetailModal.vue'
import AgentSkillFileModal from '../components/modals/AgentSkillFileModal.vue'
import AgentPromptModal from '../components/modals/AgentPromptModal.vue'

const message = useMessage()
const dialog = useDialog()

// 5 Tab 架构：profiles / rag_models / mcp / skills / runtime
type TabKey = 'profiles' | 'rag_models' | 'mcp' | 'skills' | 'runtime'
const tabs: { key: TabKey; label: string }[] = [
  { key: 'profiles', label: '💬 大模型协议档' },
  { key: 'rag_models', label: '🔤 向量与重排模型 (RAG)' },
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
  } else if (key === 'rag_models') {
    loadRagModels()
  }
}

// ═══════════════════════════════════════════════════════════════
// MCP 工具中心状态与交互管理
// ═══════════════════════════════════════════════════════════════
// 全量工具清单（来自 /api/mcp/all-tools；含原生 ToolCall + MCP 扩展）
const mcpTools = ref<McpTool[]>([])
const mcpViewMode = ref<'cards' | 'table'>('cards')
const mcpPermFilter = ref<'all' | 'read' | 'write'>('all')
// transport 过滤：all=全部; native=原生基础工具; mcp=内部MCP扩展; external=第三方网关
const mcpTransportFilter = ref<'all' | 'native' | 'mcp' | 'external'>('all')
const mcpDomainFilter = ref<string>('all')
const mcpSearchKeyword = ref('')
const mcpLoading = ref(false)
const mcpServerPingState = ref<{ ok: boolean; latencyMs: number | null } | null>(null)
const mcpServerPinging = ref(false)

// 全通道健康与连通性自检状态 (先检查 ToolCall 与 MCP)
const mcpHealthResult = ref<McpHealthCheckResponse | null>(null)
const mcpHealthChecking = ref(false)

type McpRequestState = 'idle' | 'loading' | 'success' | 'error'
const mcpRequestState = ref<McpRequestState>('idle')
const mcpRequestError = ref('')
const selectedMcpTool = ref<McpTool | null>(null)
const showMcpModal = ref(false)

/** 原生基础工具（transport=native），由 NativeToolExecutor 直连执行 */
const nativeTools = computed(() => mcpTools.value.filter((t) => t.transport === 'native'))
/** 内部 MCP 扩展工具（transport=mcp），通过 MCPClientManager 调用 */
const mcpExtTools = computed(() => mcpTools.value.filter((t) => t.transport === 'mcp'))
/** 按 server_id 分组的 MCP 扩展工具（用于 MCP Server 分组展示） */
const mcpServerGroups = computed(() => {
  const groups: Record<string, { server_id: string; tools: McpTool[] }> = {}
  for (const t of mcpExtTools.value) {
    const sid = t.server_id || 'platform.custom'
    if (!groups[sid]) groups[sid] = { server_id: sid, tools: [] }
    groups[sid].tools.push(t)
  }
  return Object.values(groups)
})

const domainFilterOptions = [
  { label: '全部领域', value: 'all' },
  { label: '📂 文件系统', value: 'file' },
  { label: '🌐 网络抓取', value: 'web' },
  { label: '💻 沙箱命令', value: 'bash' },
  { label: '📋 任务规划', value: 'plan' },
  { label: '🚀 任务调度', value: 'task' },
  { label: '🤖 模型资产', value: 'model' },
  { label: '📚 数据集', value: 'dataset' },
  { label: '🧠 知识库', value: 'kb' },
  { label: '📊 评测报告', value: 'report' },
  { label: '🖥️ 调度算力', value: 'dispatch' },
  { label: '🧪 用例管理', value: 'cases' },
  { label: '🔊 音色克隆', value: 'audio' },
  { label: '🖼️ 图像生成', value: 'image' },
]

/** 获取工具业务领域与图标映射（含原生工具识别） */
function getToolDomain(name: string): { label: string; icon: string; key: string } {
  // 原生基础工具（直接按短名匹配，transport=native 的工具名就是短名本身）
  if (name === 'read' || name === 'write' || name === 'edit') return { label: '文件系统', icon: '📂', key: 'file' }
  if (name === 'web_search' || name === 'web_fetch') return { label: '网络抓取', icon: '🌐', key: 'web' }
  if (name === 'bash') return { label: '沙箱命令', icon: '💻', key: 'bash' }
  if (name === 'task') return { label: '任务规划', icon: '📋', key: 'plan' }
  // MCP 扩展工具（按 tool_id 路径前缀匹配）
  if (name.includes('task.create') || name.includes('task.status') || name.includes('task.cancel')) return { label: '任务调度', icon: '🚀', key: 'task' }
  if (name.startsWith('model.')) return { label: '模型资产', icon: '🤖', key: 'model' }
  if (name.startsWith('dataset.')) return { label: '数据集', icon: '📚', key: 'dataset' }
  if (name.startsWith('kb.')) return { label: '知识库', icon: '🧠', key: 'kb' }
  if (name.startsWith('report.')) return { label: '评测报告', icon: '📊', key: 'report' }
  if (name.startsWith('dispatch.')) return { label: '调度大盘', icon: '🖥️', key: 'dispatch' }
  if (name.startsWith('testcase.')) return { label: '用例管理', icon: '🧪', key: 'cases' }
  if (name.startsWith('audio.')) return { label: '音色克隆', icon: '🔊', key: 'audio' }
  if (name.startsWith('image.')) return { label: '图像生成', icon: '🖼️', key: 'image' }
  return { label: '内置通用', icon: '🛠️', key: 'other' }
}

/** 获取风险等级徽标配置（用于前端展示） */
function getRiskBadge(risk?: string): { label: string; cls: string } {
  switch (risk) {
    case 'read': return { label: '📖 READ', cls: 'perm-badge-read' }
    case 'network': return { label: '🌐 NET', cls: 'perm-badge-network' }
    case 'modify': return { label: '✍️ MODIFY', cls: 'perm-badge-write' }
    case 'code': return { label: '💻 CODE', cls: 'perm-badge-code' }
    case 'long': return { label: '⏱️ LONG', cls: 'perm-badge-write' }
    default: return { label: '🛠️ WRITE', cls: 'perm-badge-write' }
  }
}

const readToolsCount = computed(() => mcpTools.value.filter((t) => t.permission === 'read').length)
const writeToolsCount = computed(() => mcpTools.value.filter((t) => t.permission === 'write').length)
const enabledMcpToolsCount = computed(() => mcpTools.value.filter((t) => t.enabled !== false).length)
const disabledMcpToolsCount = computed(() => mcpTools.value.filter((t) => t.enabled === false).length)

/** 根据真实接口状态生成页面状态徽标，避免空清单被误报为“全部就绪”。 */
const mcpBadgeClass = computed(() => {
  return mcpRequestState.value === 'success' && mcpTools.value.length > 0
    ? 'badge-succeeded'
    : 'badge-warning'
})

const mcpBadgeText = computed(() => {
  if (mcpRequestState.value === 'idle') return '尚未检查'
  if (mcpRequestState.value === 'loading') return '检查中…'
  if (mcpRequestState.value === 'error') return '清单接口不可用'
  if (mcpTools.value.length === 0) return '接口在线 · 清单为空'
  return disabledMcpToolsCount.value ? `${disabledMcpToolsCount.value} 项能力未挂载` : '清单已加载'
})

const mcpServerStatusText = computed(() => {
  if (mcpRequestState.value === 'loading') return '● 正在读取清单…'
  if (mcpRequestState.value === 'error') return '✕ 清单接口不可用'
  if (mcpRequestState.value === 'success') {
    return mcpTools.value.length > 0
      ? `● 清单可读 · ${mcpTools.value.length} 项 (${nativeTools.value.length} 原生 + ${mcpExtTools.value.length} MCP)`
      : '● 接口在线 · 0 项清单'
  }
  return '— 尚未检查'
})

const mcpEmptyTitle = computed(() => {
  if (mcpRequestState.value === 'loading') return '正在读取工具清单'
  if (mcpRequestState.value === 'error') return '工具清单接口调用失败'
  if (mcpRequestState.value === 'success' && mcpTools.value.length === 0) {
    return '接口已连通，暂无工具'
  }
  return '未找到匹配的工具'
})

const mcpEmptyDescription = computed(() => {
  if (mcpRequestState.value === 'loading') return '正在调用 GET /api/mcp/all-tools，请稍候…'
  if (mcpRequestState.value === 'error') return mcpRequestError.value || '请确认登录状态与 API 服务是否正常。'
  if (mcpRequestState.value === 'success' && mcpTools.value.length === 0) {
    return '请点击"刷新清单"重新加载全量工具列表。'
  }
  return '请尝试清空搜索条件或重置筛选器'
})

/** 获取工具输入参数简短概要（如: path*, offset, limit） */
function getToolParamsPreview(t: McpTool): string {
  const schema = t.parameters_schema
  if (!schema || !schema.properties) return '无参数'
  const req: string[] = Array.isArray(schema.required) ? schema.required : []
  const keys = Object.keys(schema.properties)
  if (keys.length === 0) return '无参数'
  return keys
    .slice(0, 3)
    .map((k) => (req.includes(k) ? `${k}*` : k))
    .join(', ') + (keys.length > 3 ? ` +${keys.length - 3}` : '')
}

/** 获取工具输出字段简短概要（如: summary, read.preview） */
function getToolOutputsPreview(t: McpTool): string {
  const schema = t.output_schema
  if (!schema || !schema.properties) return 'summary'
  const keys = Object.keys(schema.properties)
  if (keys.length === 0) return 'summary'
  return keys.slice(0, 2).join(', ') + (keys.length > 2 ? ` +${keys.length - 2}` : '')
}

/** 多维过滤后的工具清单（含原生 ToolCall + MCP 扩展，跨 transport 过滤） */
const filteredMcpTools = computed(() => {
  return mcpTools.value.filter((t) => {
    // transport 分类过滤
    if (mcpTransportFilter.value === 'native' && t.transport !== 'native') return false
    if (mcpTransportFilter.value === 'mcp' && t.transport !== 'mcp') return false
    if (mcpTransportFilter.value === 'external') return false // 外部网关通过独立面板展示
    // 权限过滤
    if (mcpPermFilter.value !== 'all' && t.permission !== mcpPermFilter.value) return false
    // 领域分类过滤
    if (mcpDomainFilter.value !== 'all') {
      const domain = getToolDomain(t.name)
      if (domain.key !== mcpDomainFilter.value) return false
    }
    // 关键字搜索过滤（支持 name/display_name/desc/domain）
    if (mcpSearchKeyword.value.trim()) {
      const kw = mcpSearchKeyword.value.toLowerCase().trim()
      const matchName = t.name.toLowerCase().includes(kw)
      const matchDisplayName = (t.display_name || '').toLowerCase().includes(kw)
      const matchDesc = t.desc.toLowerCase().includes(kw)
      const matchDomain = getToolDomain(t.name).label.toLowerCase().includes(kw)
      if (!matchName && !matchDisplayName && !matchDesc && !matchDomain) return false
    }
    return true
  })
})

/** 全通道健康与连通性自检（原生执行器 + 内部 MCP Host + 外部网关） */
async function handleRunHealthCheck() {
  mcpHealthChecking.value = true
  try {
    const res = await api.mcp.healthCheck()
    mcpHealthResult.value = res
    message.success(`全通道健康自检完成 · 耗时 ${res.total_latency_ms}ms · 原生通道(${res.summary.native_tools_count}) · MCP(${res.summary.internal_mcp_tools_count})`)
  } catch (err: any) {
    message.error(`健康自检失败: ${err.message || '网络连接异常'}`)
  } finally {
    mcpHealthChecking.value = false
  }
}

/** 刷新 MCP 工具清单与通道健康（真实调用 GET /api/mcp/all-tools 与 /api/mcp/health-check） */
async function handleRefreshMcpTools() {
  mcpLoading.value = true
  mcpRequestState.value = 'loading'
  mcpRequestError.value = ''
  const start = performance.now()
  try {
    const [res, healthRes] = await Promise.all([
      api.mcp.tools(),
      api.mcp.healthCheck().catch(() => null),
    ])
    if (!res || !Array.isArray(res.items)) {
      throw new Error('工具清单接口返回格式不正确')
    }
    const latency = Math.round(performance.now() - start)
    mcpTools.value = res.items
    mcpRequestState.value = 'success'
    mcpServerPingState.value = { ok: true, latencyMs: Math.max(1, latency) }
    if (healthRes) {
      mcpHealthResult.value = healthRes
    }
    if (mcpTools.value.length > 0) {
      message.success(`清单加载成功 · 已加载 ${mcpTools.value.length} 个工具 (${nativeTools.value.length} 原生 + ${mcpExtTools.value.length} MCP) · 耗时 ${mcpServerPingState.value.latencyMs}ms`)
    } else {
      message.warning('清单接口调用成功，但服务端返回 0 项；当前没有可供页面展示的工具')
    }
  } catch (err: any) {
    mcpRequestState.value = 'error'
    mcpRequestError.value = err.message || '调用 /api/mcp/all-tools 接口失败'
    mcpTools.value = []
    mcpServerPingState.value = { ok: false, latencyMs: null }
    message.error(mcpRequestError.value)
  } finally {
    mcpLoading.value = false
  }
}

/** 检查 Eval-Core 清单接口延迟（真实调用 GET /api/mcp/tools）。 */
async function handlePingMcpServer() {
  await handleRunHealthCheck()
}


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
const selectedSkillFileId = ref<string | null>(null)
const showSkillFileModal = ref(false)

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

/** 打开统一 Skill 文件的预览/编辑弹窗；真实文件存在性由服务端先校验。 */
function handleOpenSkillFile(skill: SkillDetail) {
  safeBlur()
  selectedSkillFileId.value = skill.id
  showSkillFileModal.value = true
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

// 运行时治理表单（settings.runtime + 全局权限档位）
const runtimeForm = ref({
  ws_ping_s: 15,
  ws_timeout_s: 45,
  strict_session_slot: true,
  permission_tier_default: 'tier1',
})
const runtimeSaving = ref(false)

// 三档权限等级选项（与后端 permission_tier.TIERS 一致）
const permissionTierOptions = [
  { label: '档1 请求批准（最保守）', value: 'tier1' },
  { label: '档2 帮我批准（推荐）', value: 'tier2' },
  { label: '档3 完全访问（危险）', value: 'tier3' },
]

// 视图模式：'cards' (供应商分类多卡片视图) | 'table' (详细表格视图)
const viewMode = ref<'cards' | 'table'>('cards')

const profiles = ref<Profile[]>([])
const profileSearch = ref('')
const vendorFilter = ref<string | null>(null)
const usageFilter = ref<string | null>(null)
/** 搜索、供应商与用途组合过滤，卡片和表格共用同一列表。 */
const filteredProfiles = computed(() => profiles.value.filter(p => {
  const text = profileSearch.value.trim().toLowerCase()
  return (!text || `${p.name} ${p.model} ${p.base_url}`.toLowerCase().includes(text))
    && (!vendorFilter.value || getProfileVendor(p) === vendorFilter.value)
    && (!usageFilter.value || p.usages?.includes(usageFilter.value as any))
}))
const vendorFilters = computed(() => [...PROFILE_VENDORS.map(v => ({label:v.name,value:v.key})), {label:'其它已有协议档',value:'custom'}])
const usageFilters = [{label:'Agent',value:'agent'},{label:'被测模型',value:'target'},{label:'裁判模型',value:'judge'}]

const loading = ref(false)
const selectedAgentProfileId = ref<string | null>(null)
// 最近一次成功保存的 Agent 协议档 ID，用于保存失败时回滚选择器
const lastSavedAgentProfileId = ref<string | null>(null)
const agentProfileSaving = ref(false)
const showAgentPromptModal = ref(false)
const promptProfile = ref<Profile | null>(null)
const selectedAgentProfile = computed(() => (
  profiles.value.find((profile) => profile.id === selectedAgentProfileId.value) || null
))

/** 每个 agent 用途协议档均可打开自己的补充提示词管理入口。 */
function handleOpenAgentPrompt(profile?: Profile) {
  const target = profile || selectedAgentProfile.value
  if (!target) {
    message.warning('请先指定 Agent 协议档')
    return
  }
  safeBlur()
  promptProfile.value = target
  showAgentPromptModal.value = true
}

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
const pinging = ref<Record<string, boolean>>({})

const agentProfileOptions = computed(() =>
  profiles.value.filter(p => p.usages?.includes('agent')).map((p) => ({ label: `${p.name} (${p.model})`, value: p.id })),
)

interface VendorGroup {
  key: string
  name: string
  logoKey: ProviderLogoKey
  base_url: string
  full_url: boolean
  protocol: any
  profiles: Profile[]
}

const VENDOR_NAMES: Record<ProviderLogoKey, string> = {
  gemini: 'Google Gemini',
  nvidia: 'NVIDIA NIM',
  mimo: 'Xiaomi Mimo',
  openai: 'OpenAI',
  anthropic: 'Anthropic Claude',
  deepseek: 'DeepSeek',
  stepfun: 'StepFun (阶跃星辰)',
  siliconflow: 'SiliconFlow (硅基流动)',
  qwen: '阿里百炼',
  volcengine: '火山引擎',
  qianfan: 'Baidu Qianfan (百度千帆)',
  hunyuan: 'Tencent Hunyuan (腾讯混元)',
  grok: 'xAI Grok',
  groq: 'Groq',
  ollama: 'Ollama (本地私有)',
  zhipu: 'GLM · 智谱',
  moonshot: 'Kimi · 月之暗面',
  minimax: 'MiniMax',
  mistral: 'Mistral AI',
  together: 'Together AI',
  custom: '自定义端点 / 内部代理',
}

/** 智能归类供应商分组 */
const vendorGroups = computed<VendorGroup[]>(() => {
  const groups: Record<string, VendorGroup> = {}

  for (const p of filteredProfiles.value) {
    const logoKey = getProfileVendor(p)
    const key = `${logoKey}:${p.base_url}:${p.protocol}:${p.full_url ?? false}`
    const vName = VENDOR_NAMES[logoKey] || '自定义端点 / 内部代理'

    if (!groups[key]) {
      groups[key] = {
        key,
        name: vName,
        logoKey,
        base_url: p.base_url,
        full_url: p.full_url ?? false,
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

const modalInitialData = ref<{ vendorKey?: string; base_url?: string; full_url?: boolean; protocol?: any; name?: string } | null>(null)

function openModal(profile: Profile | null) {
  safeBlur()
  selectedProfile.value = profile ? JSON.parse(JSON.stringify(profile)) : null
  modalInitialData.value = null
  showModal.value = true
}

function openModalWithVendor(group: VendorGroup) {
  safeBlur()
  selectedProfile.value = null
  modalInitialData.value = {
    vendorKey: group.logoKey !== 'custom' ? group.logoKey : undefined,
    base_url: group.base_url,
    full_url: group.full_url,
    protocol: group.protocol,
    name: group.name,
  }
  showModal.value = true
}

// ═══════════════════════════════════════════════════════════════
// 全局向量与重排模型 (RAG) 状态与交互管理
// ═══════════════════════════════════════════════════════════════
const ragModelsForm = ref<{
  embedding_base_url: string
  embedding_model: string
  embedding_api_key: string
  has_embedding_api_key?: boolean
  reranker_base_url: string
  reranker_model: string
  reranker_api_key: string
  has_reranker_api_key?: boolean
}>({
  embedding_base_url: '',
  embedding_model: '',
  embedding_api_key: '',
  reranker_base_url: '',
  reranker_model: '',
  reranker_api_key: '',
})
const ragModelsLoading = ref(false)
const ragModelsSaving = ref(false)

/** Embedding 常用预设 */
const embeddingPresetOptions = [
  { label: 'SiliconFlow (BAAI/bge-large-zh-v1.5)', value: 'sf-bge-large' },
  { label: 'SiliconFlow (BAAI/bge-m3)', value: 'sf-bge-m3' },
  { label: 'OpenAI (text-embedding-3-small)', value: 'openai-small' },
  { label: 'OpenAI (text-embedding-3-large)', value: 'openai-large' },
  { label: 'Alibaba DashScope (text-embedding-v3)', value: 'dashscope-v3' },
  { label: 'Zhipu AI (embedding-3)', value: 'zhipu-3' },
  { label: 'Ollama Local (nomic-embed-text)', value: 'ollama-nomic' },
]

const EMBEDDING_PRESET_MAP: Record<string, { base_url: string; model: string }> = {
  'sf-bge-large': { base_url: 'https://api.siliconflow.cn/v1', model: 'BAAI/bge-large-zh-v1.5' },
  'sf-bge-m3': { base_url: 'https://api.siliconflow.cn/v1', model: 'BAAI/bge-m3' },
  'openai-small': { base_url: 'https://api.openai.com/v1', model: 'text-embedding-3-small' },
  'openai-large': { base_url: 'https://api.openai.com/v1', model: 'text-embedding-3-large' },
  'dashscope-v3': { base_url: 'https://dashscope.aliyuncs.com/compatible-mode/v1', model: 'text-embedding-v3' },
  'zhipu-3': { base_url: 'https://open.bigmodel.cn/api/paas/v4', model: 'embedding-3' },
  'ollama-nomic': { base_url: 'http://localhost:11434/v1', model: 'nomic-embed-text' },
}

function handleSelectEmbeddingPreset(key: string) {
  const item = EMBEDDING_PRESET_MAP[key]
  if (!item) return
  ragModelsForm.value.embedding_base_url = item.base_url
  ragModelsForm.value.embedding_model = item.model
  message.info(`已填充 Embedding 预设: ${item.model}`)
}

/** Reranker 常用预设 */
const rerankerPresetOptions = [
  { label: 'SiliconFlow (BAAI/bge-reranker-v2-m3)', value: 'sf-rerank-v2-m3' },
  { label: 'SiliconFlow (BAAI/bge-reranker-large)', value: 'sf-rerank-large' },
  { label: 'Jina AI (jina-reranker-v2-base-multilingual)', value: 'jina-v2' },
  { label: 'Alibaba DashScope (gte-rerank)', value: 'dashscope-gte' },
  { label: 'Cohere (rerank-v3.5)', value: 'cohere-v3.5' },
]

const RERANKER_PRESET_MAP: Record<string, { base_url: string; model: string }> = {
  'sf-rerank-v2-m3': { base_url: 'https://api.siliconflow.cn/v1', model: 'BAAI/bge-reranker-v2-m3' },
  'sf-rerank-large': { base_url: 'https://api.siliconflow.cn/v1', model: 'BAAI/bge-reranker-large' },
  'jina-v2': { base_url: 'https://api.jina.ai/v1', model: 'jina-reranker-v2-base-multilingual' },
  'dashscope-gte': { base_url: 'https://dashscope.aliyuncs.com/compatible-mode/v1', model: 'gte-rerank' },
  'cohere-v3.5': { base_url: 'https://api.cohere.com/v2', model: 'rerank-v3.5' },
}

function handleSelectRerankerPreset(key: string) {
  const item = RERANKER_PRESET_MAP[key]
  if (!item) return
  ragModelsForm.value.reranker_base_url = item.base_url
  ragModelsForm.value.reranker_model = item.model
  message.info(`已填充 Reranker 预设: ${item.model}`)
}

const checkingEmbedding = ref(false)
const embeddingCheckResult = ref<{ ok: boolean; latency_ms?: number; message?: string } | null>(null)

async function handleCheckEmbedding() {
  if (!ragModelsForm.value.embedding_base_url.trim() || !ragModelsForm.value.embedding_model.trim()) {
    message.warning('请先填写 Embedding Base URL 与模型名称')
    return
  }
  checkingEmbedding.value = true
  embeddingCheckResult.value = null
  try {
    const res = await api.admin.checkRagModel({
      target: 'embedding',
      base_url: ragModelsForm.value.embedding_base_url.trim(),
      model: ragModelsForm.value.embedding_model.trim(),
      api_key: ragModelsForm.value.embedding_api_key?.trim() || undefined,
    })
    embeddingCheckResult.value = res
    if (res.ok) {
      message.success(`Embedding 端点连通正常！响应延迟: ${res.latency_ms}ms`)
    } else {
      message.error(res.message || 'Embedding 连通检测未通过')
    }
  } catch (err: any) {
    embeddingCheckResult.value = { ok: false, message: err.message || '请求异常' }
    message.error(err.message || '探活异常')
  } finally {
    checkingEmbedding.value = false
  }
}

const checkingReranker = ref(false)
const rerankerCheckResult = ref<{ ok: boolean; latency_ms?: number; message?: string } | null>(null)

async function handleCheckReranker() {
  if (!ragModelsForm.value.reranker_base_url.trim() || !ragModelsForm.value.reranker_model.trim()) {
    message.warning('请先填写 Reranker Base URL 与模型名称')
    return
  }
  checkingReranker.value = true
  rerankerCheckResult.value = null
  try {
    const res = await api.admin.checkRagModel({
      target: 'reranker',
      base_url: ragModelsForm.value.reranker_base_url.trim(),
      model: ragModelsForm.value.reranker_model.trim(),
      api_key: ragModelsForm.value.reranker_api_key?.trim() || undefined,
    })
    rerankerCheckResult.value = res
    if (res.ok) {
      message.success(`Reranker 端点连通正常！响应延迟: ${res.latency_ms}ms`)
    } else {
      message.error(res.message || 'Reranker 连通检测未通过')
    }
  } catch (err: any) {
    rerankerCheckResult.value = { ok: false, message: err.message || '请求异常' }
    message.error(err.message || '探活异常')
  } finally {
    checkingReranker.value = false
  }
}

async function loadRagModels() {
  ragModelsLoading.value = true
  try {
    const data = await api.admin.getRagModels()
    ragModelsForm.value = {
      embedding_base_url: data.embedding_base_url || '',
      embedding_model: data.embedding_model || '',
      embedding_api_key: '',
      has_embedding_api_key: data.has_embedding_api_key,
      reranker_base_url: data.reranker_base_url || '',
      reranker_model: data.reranker_model || '',
      reranker_api_key: '',
      has_reranker_api_key: data.has_reranker_api_key,
    }
  } catch (err: any) {
    message.error(err.message || '加载全局 RAG 模型配置失败')
  } finally {
    ragModelsLoading.value = false
  }
}

async function saveRagModels() {
  if (
    !ragModelsForm.value.embedding_base_url.trim() &&
    !ragModelsForm.value.embedding_model.trim() &&
    !ragModelsForm.value.reranker_base_url.trim() &&
    !ragModelsForm.value.reranker_model.trim()
  ) {
    message.warning('请至少填写 Embedding 或 Reranker 的基础配置')
    return
  }
  ragModelsSaving.value = true
  try {
    const payload: any = {
      embedding_base_url: ragModelsForm.value.embedding_base_url.trim() || undefined,
      embedding_model: ragModelsForm.value.embedding_model.trim() || undefined,
      reranker_base_url: ragModelsForm.value.reranker_base_url.trim() || undefined,
      reranker_model: ragModelsForm.value.reranker_model.trim() || undefined,
    }
    if (ragModelsForm.value.embedding_api_key?.trim()) {
      payload.embedding_api_key = ragModelsForm.value.embedding_api_key.trim()
    }
    if (ragModelsForm.value.reranker_api_key?.trim()) {
      payload.reranker_api_key = ragModelsForm.value.reranker_api_key.trim()
    }
    const res = await api.admin.updateRagModels(payload)
    ragModelsForm.value = {
      embedding_base_url: res.embedding_base_url || '',
      embedding_model: res.embedding_model || '',
      embedding_api_key: '',
      has_embedding_api_key: res.has_embedding_api_key,
      reranker_base_url: res.reranker_base_url || '',
      reranker_model: res.reranker_model || '',
      reranker_api_key: '',
      has_reranker_api_key: res.has_reranker_api_key,
    }
    message.success('全局 RAG 模型配置已成功保存并生效！')
  } catch (err: any) {
    message.error(err.message || '保存全局 RAG 模型配置失败')
  } finally {
    ragModelsSaving.value = false
  }
}

async function loadProfiles() {
  loading.value = true
  try {
    const [pListRes, settingsRes] = await Promise.allSettled([
      api.profiles.list(),
      api.admin.getSettings(),
    ])
    if (pListRes.status === 'fulfilled') {
      profiles.value = pListRes.value || []
    } else { message.error('协议档加载失败，请重试') }
    if (settingsRes.status === 'rejected') message.error('默认模型设置加载失败，请重试')
    if (settingsRes.status === 'fulfilled') {
      const settings = settingsRes.value
      selectedAgentProfileId.value = settings?.agent_profile_id || null
      lastSavedAgentProfileId.value = selectedAgentProfileId.value
      if (settings?.runtime) runtimeForm.value = { ...runtimeForm.value, ...settings.runtime }
      if (settings?.permission_tier_default) {
        runtimeForm.value.permission_tier_default = settings.permission_tier_default
      }
    }
  } catch (err: any) {
    message.error(err.message || '加载配置失败')
  } finally {
    loading.value = false
  }
}

/** 保存运行时治理参数（settings.runtime + 全局权限档位，后端写审计） */
async function saveRuntime() {
  runtimeSaving.value = true
  try {
    await api.admin.updateSettings({
      runtime: {
        ws_ping_s: runtimeForm.value.ws_ping_s,
        ws_timeout_s: runtimeForm.value.ws_timeout_s,
        strict_session_slot: runtimeForm.value.strict_session_slot,
      },
      permission_tier_default: runtimeForm.value.permission_tier_default,
    } as any)
    message.success('运行时参数已更新生效（写审计）')
  } catch (err: any) {
    message.error(err.message || '运行时参数保存失败')
  } finally {
    runtimeSaving.value = false
  }
}

async function handleUpdateAgentProfile(profileId: string) {
  agentProfileSaving.value = true
  try {
    await api.admin.updateSettings({ agent_profile_id: profileId })
    lastSavedAgentProfileId.value = profileId
    message.success('Agent 后端模型已指定')
  } catch (err: any) {
    // 保存失败时回滚选择器，保持 UI 与后端状态一致
    selectedAgentProfileId.value = lastSavedAgentProfileId.value
    message.error(err.message || '设置失败')
  } finally { agentProfileSaving.value = false }
}

/** P2 行内探活：原位刷新 ping-badge（复用 api.profiles.check，不泄露凭据） */
async function handlePing(p: Profile) {
  if (pinging.value[p.id]) return
  pinging.value[p.id] = true
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
    delete pinging.value[p.id]
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

onMounted(() => {
  loadProfiles()
  loadRagModels()
})
</script>

<style scoped>
.profile-default-summary{display:flex;align-items:center;gap:12px;margin-top:18px;padding:16px;border:1px solid var(--border-color,#dce8e1);border-radius:12px;background:var(--bg-secondary,#f5faf7)}.profile-default-summary>div{flex:1;min-width:0}.profile-default-summary strong{font-size:15px;overflow-wrap:anywhere}.profile-default-summary p{margin:5px 0 0;color:var(--text-tertiary);font-size:12px}.profile-default-summary b{font-weight:600;color:#367b5b}.profile-filters{display:grid;grid-template-columns:minmax(180px,1fr) 180px 150px auto;align-items:center;gap:12px;margin:6px 0 20px}.profile-filters>span{color:var(--text-tertiary);font-size:12px;white-space:nowrap}.url-mode-tag{border-radius:5px;background:#eaf5ee;color:#31744e;padding:3px 7px;font:11px ui-monospace,monospace}.profiles-page .panel-title{flex-wrap:wrap;gap:12px}.profiles-page .model-chip-name{overflow-wrap:anywhere}.profiles-page .vendor-url{overflow-wrap:anywhere}@media(max-width:760px){.profile-filters{grid-template-columns:1fr 1fr}.profile-filters>.n-input{grid-column:1/-1}.profile-default-summary{flex-wrap:wrap}.profile-default-summary button{margin-left:40px}}

.profile-table-scroll { overflow-x: auto; }
.profile-table-scroll table { min-width: 1050px; }
.profile-table-scroll td { overflow-wrap: anywhere; }
.vendor-info { min-width: 0; }
.vendor-group-header { gap: 12px; }
.vendor-actions { flex-shrink: 0; }
.vendor-title-row { flex-wrap: wrap; }
.empty-state-wrap { grid-column: 1 / -1; }
.ping-badge { font: inherit; font-size: 11px; cursor: pointer; }
@media(max-width: 560px) { .vendor-group-header, .model-chip-bottom { flex-wrap: wrap; gap: 10px; } .model-chip-title-wrap { flex-wrap: wrap; } }

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
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  align-items: start;
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
  grid-template-columns: minmax(0, 1fr);
  gap: 12px;
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
  border-color: #84b89c;
  background: var(--bg-card, #fff);
  box-shadow: inset 3px 0 #498467;
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
  gap: 8px;
  font-size: 11.5px;
  min-width: 0;
  flex-wrap: wrap;
}
.model-id-tag {
  background: rgba(15, 23, 42, 0.05);
  padding: 2px 8px;
  border-radius: 6px;
  font-weight: 600;
  color: var(--text-primary, #1e293b);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  max-width: 200px;
  display: inline-block;
}
.protocol-tag {
  color: var(--text-secondary, #64748b);
  font-weight: 500;
}
.window-tag {
  display: inline-block;
  padding: 2px 6px;
  background: var(--t-profiles, rgba(79, 70, 229, 0.08));
  color: var(--c-profiles, #4f46e5);
  border-radius: 4px;
  font-size: 11px;
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
/* 5 Tab 页签导航 */
.tabs-nav-bar {
  overflow-x: auto;
  white-space: nowrap;
  -webkit-overflow-scrolling: touch;
  padding-bottom: 4px;
}
.tabs-nav-bar::-webkit-scrollbar {
  height: 0;
}
.profile-tab-btn {
  flex-shrink: 0;
  padding: 8px 16px;
  border-radius: 8px;
  border: 1px solid var(--border-subtle);
  background: transparent;
  color: var(--text-secondary);
  font-size: 13px;
  font-weight: 600;
  cursor: pointer;
  transition: all 0.18s ease;
  user-select: none;
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
/* 网络工具风险标签 */
.perm-badge-network {
  color: #3b82f6;
  border-color: rgba(59, 130, 246, 0.3);
  font-size: 10.5px;
  font-weight: 600;
}
/* 沙箱代码执行风险标签 */
.perm-badge-code {
  color: #f59e0b;
  border-color: rgba(245, 158, 11, 0.4);
  font-size: 10.5px;
  font-weight: 600;
}
/* 原生工具卡片：绿色左边框，与 MCP 扩展工具（紫色）形成视觉区分 */
.mcp-card.is-native {
  border-left: 3px solid rgba(16, 185, 129, 0.5);
}
.mcp-tool-desc {
  font-size: 12px;
  color: var(--text-secondary);
  line-height: 1.45;
  min-height: 34px;
}

/* 卡片内输入输出概要 */
.tool-schema-brief {
  background: var(--bg-elevated, #f8fafc);
  border: 1px solid var(--border-subtle, #e2e8f0);
  border-radius: 6px;
  padding: 6px 8px;
  display: flex;
  flex-direction: column;
  gap: 3px;
}
.schema-brief-row {
  display: flex;
  gap: 6px;
  align-items: center;
  font-size: 11px;
}
.brief-k {
  color: var(--text-tertiary, #94a3b8);
  font-weight: 600;
  flex-shrink: 0;
}
.brief-v {
  color: var(--text-primary, #1e293b);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

/* 第三方 MCP 网关说明面板 */
.external-gateway-panel {
  display: flex;
  flex-direction: column;
  gap: 12px;
  padding: 8px 0;
}
.ext-hero-box {
  display: flex;
  gap: 14px;
  align-items: center;
  padding: 16px 18px;
  background: linear-gradient(135deg, rgba(99, 102, 241, 0.08) 0%, rgba(59, 130, 246, 0.04) 100%);
  border: 1px solid rgba(99, 102, 241, 0.2);
  border-radius: 12px;
}
.ext-icon {
  font-size: 32px;
}
.ext-title {
  font-size: 14px;
  font-weight: 700;
  color: var(--text-primary);
  margin-bottom: 3px;
}
.ext-desc {
  font-size: 12px;
  color: var(--text-secondary);
  line-height: 1.5;
}
.ext-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
  gap: 12px;
}
.ext-card {
  padding: 12px 14px;
  background: var(--bg-card, #ffffff);
  border: 1px solid var(--border-subtle);
  border-radius: 10px;
}
.ext-card-title {
  font-size: 12.5px;
  font-weight: 700;
  color: var(--text-primary);
  margin-bottom: 6px;
}
.ext-card-content {
  font-size: 11.5px;
  color: var(--text-secondary);
  line-height: 1.6;
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

/* ─── RAG 专属全局模型面板 ─── */
.rag-panel-container {
  padding: 18px 22px;
}
.rag-intro-banner {
  background: linear-gradient(135deg, rgba(16, 185, 129, 0.06), rgba(99, 102, 241, 0.06));
  border: 1px solid rgba(16, 185, 129, 0.18);
  border-radius: 12px;
  padding: 14px 18px;
}
.rag-badge-icon {
  width: 36px;
  height: 36px;
  border-radius: 10px;
  background: var(--bg-elevated, #ffffff);
  border: 1px solid var(--border-subtle);
  display: grid;
  place-items: center;
  font-size: 18px;
  flex-shrink: 0;
  box-shadow: 0 2px 6px rgba(0, 0, 0, 0.04);
}
.rag-intro-title {
  font-size: 14.5px;
  font-weight: 700;
  color: var(--text-primary);
  margin-bottom: 3px;
}
.rag-intro-desc {
  font-size: 12px;
  color: var(--text-secondary);
  line-height: 1.6;
  max-width: 900px;
}
.rag-scope-tag {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 4px 10px;
  border-radius: 20px;
  background: rgba(16, 185, 129, 0.1);
  border: 1px solid rgba(16, 185, 129, 0.25);
  color: #10b981;
  font-size: 11.5px;
  font-weight: 600;
  white-space: nowrap;
}
.dot-live {
  color: #10b981;
  animation: dot-breathe 2s ease-in-out infinite;
}

.rag-models-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 18px;
}
.rag-model-card {
  background: var(--bg-card, rgba(255, 255, 255, 0.02));
  border: 1px solid var(--border-subtle, rgba(255, 255, 255, 0.08));
  border-radius: 12px;
  display: flex;
  flex-direction: column;
  padding: 18px;
  transition: all 0.2s ease;
}
.rag-card-embedding {
  border-top: 3px solid #10b981;
}
.rag-card-reranker {
  border-top: 3px solid #8b5cf6;
}
.rag-card-embedding:hover {
  border-color: rgba(16, 185, 129, 0.4);
  box-shadow: 0 8px 24px rgba(16, 185, 129, 0.06);
}
.rag-card-reranker:hover {
  border-color: rgba(139, 92, 246, 0.4);
  box-shadow: 0 8px 24px rgba(139, 92, 246, 0.06);
}

.rag-card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  flex-wrap: wrap;
  gap: 8px;
}
.rag-type-pill {
  font-size: 13.5px;
  font-weight: 700;
  display: inline-flex;
  align-items: center;
  gap: 6px;
}
.pill-embedding {
  color: #10b981;
}
.pill-reranker {
  color: #8b5cf6;
}
.rag-model-sub {
  font-size: 11.5px;
  color: var(--text-tertiary);
  font-weight: normal;
}
.rag-pills-row {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}
.rag-feature-tag {
  font-size: 11px;
  padding: 2px 7px;
  border-radius: 5px;
  background: var(--bg-elevated, rgba(255, 255, 255, 0.04));
  border: 1px solid var(--border-subtle, rgba(255, 255, 255, 0.06));
  color: var(--text-secondary);
}

.rag-check-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  flex-wrap: wrap;
  gap: 8px;
  padding-top: 6px;
}
.btn-xs {
  height: 26px;
  padding: 0 10px;
  font-size: 11.5px;
}
.rag-check-feedback {
  font-size: 11.5px;
  display: inline-flex;
  align-items: center;
  gap: 4px;
}
.rag-check-feedback.success {
  color: #10b981;
  font-weight: 500;
}
.rag-check-feedback.fail {
  color: #ef4444;
}

.rag-footer-bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  flex-wrap: wrap;
  gap: 12px;
  padding-top: 12px;
  border-top: 1px solid var(--border-subtle);
}
.rag-footer-tip {
  font-size: 12px;
  color: var(--text-tertiary);
}

/* 移动端与平板端：栅格自适应 */
@media (max-width: 900px) {
  .rag-models-grid {
    grid-template-columns: 1fr;
  }
}

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
  .rag-panel-container {
    padding: 12px;
  }
}
@media(max-width: 920px) { .vendor-cards-container { grid-template-columns: minmax(0, 1fr); } }
</style>
