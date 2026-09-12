<template>
  <div class="profiles-page">
    <!-- 顶部 Tab 导航栏 -->
    <div class="tabs-nav-bar">
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

    <!-- ═══════════════════════════════════════════════════════════════
         Tab 1：大模型协议档 (Profiles)
         ═══════════════════════════════════════════════════════════════ -->
    <template v-if="activeTab === 'profiles'">
      <!-- 顶部 Agent 默认模型快速控制栏 -->
      <div class="panel agent-default-bar">
        <div class="agent-default-info">
          <div class="agent-default-badge">Agent 核心驱动</div>
          <div v-if="selectedAgentProfile" class="agent-default-content">
            <ProviderLogo :provider="getModelLogoKey(selectedAgentProfile.model)" :size="20" compact />
            <span class="agent-default-name">{{ selectedAgentProfile.name }}</span>
            <span class="mono agent-default-model">{{ selectedAgentProfile.model }}</span>
            <span class="agent-default-url-tag">{{ selectedAgentProfile.full_url ? '完整 URL' : 'Base URL' }}</span>
          </div>
          <div v-else class="agent-default-content empty">
            <span>未指定默认模型（新对话将使用系统默认配置）</span>
          </div>
        </div>

        <div class="agent-default-controls">
          <n-select
            v-model:value="selectedAgentProfileId"
            class="agent-select-input"
            placeholder="选择 Agent 默认协议档"
            :options="agentProfileOptions"
            :loading="agentProfileSaving"
            :disabled="loading || agentProfileSaving"
            @update:value="handleUpdateAgentProfile"
          />
          <button
            v-if="selectedAgentProfile"
            class="btn btn-secondary btn-sm"
            @click="openModal(selectedAgentProfile)"
          >
            配置模型
          </button>
        </div>
      </div>

      <!-- 协议档列表主面板 -->
      <div class="panel">
        <div class="panel-header-row">
          <div class="panel-title-area">
            <span class="panel-title-text">模型协议档</span>
            <span class="panel-count-pill">{{ filteredProfiles.length }} / {{ profiles.length }}</span>
          </div>

          <div class="panel-actions-area">
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

        <!-- 筛选栏 -->
        <div class="profile-filters-bar">
          <n-input
            v-model:value="profileSearch"
            clearable
            placeholder="搜索名称、模型标识或端点…"
            class="filter-search-input"
          />
          <n-select
            v-model:value="vendorFilter"
            :options="vendorFilters"
            clearable
            placeholder="全部供应商"
            class="filter-select"
          />
          <n-select
            v-model:value="usageFilter"
            :options="usageFilters"
            clearable
            placeholder="全部用途"
            class="filter-select"
          />
        </div>

        <!-- 加载中 -->
        <p v-if="loading" role="status" class="small tertiary">正在加载协议档…</p>

        <!-- 模式 1：供应商卡片网格 -->
        <div v-if="viewMode === 'cards'" class="vendor-cards-container">
          <div
            v-for="group in vendorGroups"
            :key="group.key"
            class="vendor-group-card"
          >
            <div class="vendor-group-header">
              <div class="vendor-info">
                <div class="vendor-title-row">
                  <ProviderLogo :provider="group.logoKey" :size="20" compact />
                  <span class="vendor-name">{{ group.name }}</span>
                  <span class="vendor-count-badge">{{ group.profiles.length }}</span>
                </div>
                <div class="vendor-url mono" :title="group.base_url">{{ group.base_url }}</div>
              </div>
              <button
                class="btn btn-secondary btn-xs"
                @click="openModalWithVendor(group)"
              >
                + 添加模型
              </button>
            </div>

            <!-- 模型项列表 -->
            <div class="vendor-models-grid">
              <div
                v-for="p in group.profiles"
                :key="p.id"
                class="model-chip-card"
                :class="{ 'is-agent-core': p.id === selectedAgentProfileId }"
              >
                <div class="model-chip-top">
                  <div class="model-chip-title-wrap">
                    <ProviderLogo class="model-chip-brand" :provider="getModelLogoKey(p.model)" compact :size="18" />
                    <span class="model-chip-name" :title="p.name">{{ p.name }}</span>
                    <span v-if="p.id === selectedAgentProfileId" class="tag-soft agent-core-tag">核心驱动</span>
                  </div>

                  <!-- 探活按钮 -->
                  <button
                    v-if="pingStates[p.id]"
                    class="ping-badge"
                    :class="pingStates[p.id].ok ? 'ok' : 'err'"
                    :disabled="pinging[p.id]"
                    title="点击重新测试连通性"
                    @click="handlePing(p)"
                  >
                    {{ pingStates[p.id].ok ? `${pingStates[p.id].latencyMs ?? '—'}ms` : '连接失败' }}
                  </button>
                  <button
                    v-else
                    class="link-btn small"
                    :disabled="pinging[p.id]"
                    @click="handlePing(p)"
                  >
                    {{ pinging[p.id] ? '探活中…' : '探活' }}
                  </button>
                </div>

                <div class="model-chip-meta">
                  <span class="mono model-id-tag" :title="p.model">{{ p.model }}</span>
                  <span class="mono protocol-tag">{{ p.protocol }}</span>
                  <span v-if="p.full_url" class="url-mode-tag">完整 URL</span>
                  <span class="mono window-tag" title="上下文容量">{{ formatContextWindow(p.context_window) }}</span>
                </div>

                <div class="model-chip-bottom">
                  <div class="row wrap" style="gap: 4px">
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
                      :title="p.id === selectedAgentProfileId ? '当前档已被指定为 Agent 默认后端，禁止删除' : ''"
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

        <!-- 模式 2：表格视图 -->
        <div v-else class="profile-table-scroll">
          <table class="ds-table">
            <thead>
              <tr>
                <th>协议档名称</th>
                <th style="width: 155px">供应商</th>
                <th style="width: 140px">协议类型</th>
                <th style="width: 160px">模型标识</th>
                <th style="width: 100px">上下文窗口</th>
                <th>请求地址</th>
                <th style="width: 130px">用途</th>
                <th style="width: 110px">连通性</th>
                <th style="width: 180px; text-align: right">操作</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="p in filteredProfiles" :key="p.id">
                <td style="font-weight: 600; font-size: 13.5px">
                  <span class="row" style="gap: 8px; align-items: center">
                    <span>{{ p.name }}</span>
                    <span v-if="p.id === selectedAgentProfileId" class="tag-soft agent-core-tag">核心驱动</span>
                  </span>
                </td>
                <td>
                  <span class="row" style="gap: 6px; align-items: center">
                    <ProviderLogo :provider="getProfileVendor(p)" compact :size="18" />
                    <span class="provider-cell-name">{{ VENDOR_NAMES[getProfileVendor(p)] }}</span>
                  </span>
                </td>
                <td>
                  <span class="mono" style="font-size: 12px">{{ p.protocol }}</span>
                </td>
                <td>
                  <span class="row model-id-cell">
                    <ProviderLogo :provider="getModelLogoKey(p.model)" compact :size="16" />
                    <span class="mono">{{ p.model }}</span>
                  </span>
                </td>
                <td>
                  <span class="mono window-tag">{{ formatContextWindow(p.context_window) }}</span>
                </td>
                <td>
                  <span class="mono" style="font-size: 11.5px; color: var(--text-secondary)">{{ p.base_url }}</span>
                  <span v-if="p.full_url" class="url-mode-tag">完整 URL</span>
                </td>
                <td>
                  <div class="row wrap" style="gap: 4px">
                    <span v-if="p.usages?.includes('target')" class="kind-tag kind-benchmark">被测</span>
                    <span v-if="p.usages?.includes('judge')" class="kind-tag kind-cases">裁判</span>
                    <span v-if="p.usages?.includes('agent')" class="kind-tag kind-rag">Agent</span>
                  </div>
                </td>
                <td>
                  <button
                    v-if="pingStates[p.id]"
                    class="ping-badge"
                    :class="pingStates[p.id].ok ? 'ok' : 'err'"
                    :disabled="pinging[p.id]"
                    title="点击重新探活"
                    @click="handlePing(p)"
                  >
                    {{ pingStates[p.id].ok ? `${pingStates[p.id].latencyMs ?? '—'}ms` : '失败' }}
                  </button>
                  <button v-else class="link-btn small" :disabled="pinging[p.id]" @click="handlePing(p)">
                    {{ pinging[p.id] ? '探活中…' : '探活' }}
                  </button>
                </td>
                <td style="text-align: right">
                  <div class="row" style="justify-content: flex-end; gap: 4px">
                    <button class="link-btn small" :disabled="checkingId === p.id" @click="handleCheck(p)">
                      {{ checkingId === p.id ? '检测中…' : '详情' }}
                    </button>
                    <button v-if="p.usages?.includes('agent')" class="link-btn small" @click="handleOpenAgentPrompt(p)">提示词</button>
                    <button class="link-btn small" @click="openModal(p)">编辑</button>
                    <button
                      class="link-btn danger small"
                      :disabled="p.id === selectedAgentProfileId"
                      :title="p.id === selectedAgentProfileId ? '当前档已被指定为 Agent 默认后端，禁止删除' : ''"
                      @click="handleDelete(p)"
                    >
                      删除
                    </button>
                  </div>
                </td>
              </tr>

              <tr v-if="!loading && filteredProfiles.length === 0">
                <td colspan="9">
                  <EmptyState title="暂无匹配的协议档" description="点击右上角新增 OpenAI / Anthropic 协议档">
                    <template #action>
                      <button class="btn btn-primary btn-sm" @click="openModal(null)">新增协议档</button>
                    </template>
                  </EmptyState>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>
    </template>

    <!-- ═══════════════════════════════════════════════════════════════
         Tab 2：向量与重排模型 (RAG)
         ═══════════════════════════════════════════════════════════════ -->
    <template v-else-if="activeTab === 'rag_models'">
      <div class="panel">
        <div class="panel-header-row">
          <div class="panel-title-area">
            <span class="panel-title-text">全局向量与重排模型</span>
            <span class="tag-soft">全局生效 · 实时生效</span>
          </div>
          <div class="panel-actions-area">
            <button class="btn btn-secondary btn-sm" :disabled="ragModelsLoading" @click="loadRagModels">
              重置
            </button>
            <button class="btn btn-primary btn-sm" :disabled="ragModelsSaving" @click="saveRagModels">
              {{ ragModelsSaving ? '保存中…' : '保存全局配置' }}
            </button>
          </div>
        </div>

        <div class="rag-models-grid mt16">
          <!-- 1. 全局向量嵌入模型 (Embedding) -->
          <div class="rag-model-card">
            <div class="rag-card-header">
              <div class="row" style="gap: 8px; align-items: center">
                <span class="rag-type-pill">向量嵌入 (Embedding)</span>
                <span class="rag-model-sub">知识库向量化与语义检索</span>
              </div>
              <span v-if="ragModelsForm.has_embedding_api_key" class="key-status-badge ok" title="已加密存储密钥">
                ● 已配置密钥
              </span>
              <span v-else class="key-status-badge none" title="未配置密钥时使用免密端点或平台默认">
                ○ 免密 / 全局
              </span>
            </div>

            <div class="field mt12">
              <label class="field-label">常用预设</label>
              <n-select
                :options="embeddingPresetOptions"
                placeholder="选择常用向量模型预设一键填充…"
                @update:value="handleSelectEmbeddingPreset"
              />
            </div>

            <div class="field mt12">
              <label class="field-label">Base URL <span class="req">*</span></label>
              <n-input
                v-model:value="ragModelsForm.embedding_base_url"
                placeholder="例如：https://api.siliconflow.cn/v1"
              />
            </div>

            <div class="field mt12">
              <label class="field-label">模型标识 (Model ID) <span class="req">*</span></label>
              <n-input
                v-model:value="ragModelsForm.embedding_model"
                placeholder="例如：BAAI/bge-large-zh-v1.5"
              />
            </div>

            <div class="field mt12">
              <label class="field-label">API Key</label>
              <n-input
                v-model:value="ragModelsForm.embedding_api_key"
                type="password"
                show-password-on="click"
                :placeholder="ragModelsForm.has_embedding_api_key ? '********* (已保存密钥，留空保持不变)' : '可选；私有端点或免密模型可留空'"
              />
            </div>

            <div class="rag-check-row mt16">
              <button
                class="btn btn-secondary btn-xs"
                :disabled="checkingEmbedding || !ragModelsForm.embedding_base_url || !ragModelsForm.embedding_model"
                @click="handleCheckEmbedding"
              >
                {{ checkingEmbedding ? '探活中…' : '端点连通测试' }}
              </button>
              <div v-if="embeddingCheckResult" class="rag-check-feedback" :class="embeddingCheckResult.ok ? 'success' : 'fail'">
                <span v-if="embeddingCheckResult.ok">✓ 连通正常 ({{ embeddingCheckResult.latency_ms }}ms)</span>
                <span v-else>✕ {{ embeddingCheckResult.message }}</span>
              </div>
            </div>
          </div>

          <!-- 2. 全局重排序模型 (Reranker) -->
          <div class="rag-model-card">
            <div class="rag-card-header">
              <div class="row" style="gap: 8px; align-items: center">
                <span class="rag-type-pill">语义重排 (Reranker)</span>
                <span class="rag-model-sub">Top-K 候选打分与二次降噪</span>
              </div>
              <span v-if="ragModelsForm.has_reranker_api_key" class="key-status-badge ok" title="已加密存储密钥">
                ● 已配置密钥
              </span>
              <span v-else class="key-status-badge none" title="未配置密钥时使用免密端点或平台默认">
                ○ 免密 / 全局
              </span>
            </div>

            <div class="field mt12">
              <label class="field-label">常用预设</label>
              <n-select
                :options="rerankerPresetOptions"
                placeholder="选择常用重排模型预设一键填充…"
                @update:value="handleSelectRerankerPreset"
              />
            </div>

            <div class="field mt12">
              <label class="field-label">Base URL <span class="req">*</span></label>
              <n-input
                v-model:value="ragModelsForm.reranker_base_url"
                placeholder="例如：https://api.siliconflow.cn/v1"
              />
            </div>

            <div class="field mt12">
              <label class="field-label">模型标识 (Model ID) <span class="req">*</span></label>
              <n-input
                v-model:value="ragModelsForm.reranker_model"
                placeholder="例如：BAAI/bge-reranker-v2-m3"
              />
            </div>

            <div class="field mt12">
              <label class="field-label">API Key</label>
              <n-input
                v-model:value="ragModelsForm.reranker_api_key"
                type="password"
                show-password-on="click"
                :placeholder="ragModelsForm.has_reranker_api_key ? '********* (已保存密钥，留空保持不变)' : '可选；私有端点或免密模型可留空'"
              />
            </div>

            <div class="rag-check-row mt16">
              <button
                class="btn btn-secondary btn-xs"
                :disabled="checkingReranker || !ragModelsForm.reranker_base_url || !ragModelsForm.reranker_model"
                @click="handleCheckReranker"
              >
                {{ checkingReranker ? '探活中…' : '端点连通测试' }}
              </button>
              <div v-if="rerankerCheckResult" class="rag-check-feedback" :class="rerankerCheckResult.ok ? 'success' : 'fail'">
                <span v-if="rerankerCheckResult.ok">✓ 连通正常 ({{ rerankerCheckResult.latency_ms }}ms)</span>
                <span v-else>✕ {{ rerankerCheckResult.message }}</span>
              </div>
            </div>
          </div>
        </div>
      </div>
    </template>

    <!-- ═══════════════════════════════════════════════════════════════
         Tab 3：MCP 服务器与工具清单 (MCP)
         ═══════════════════════════════════════════════════════════════ -->
    <template v-else-if="activeTab === 'mcp'">
      <div class="mcp-center-container">
        <!-- 顶部操作栏 -->
        <div class="panel">
          <div class="panel-header-row">
            <div class="panel-title-area">
              <span class="panel-title-text">MCP 服务器与工具清单</span>
              <span class="badge" :class="mcpBadgeClass">{{ mcpBadgeText }}</span>
            </div>

            <div class="panel-actions-area">
              <button
                class="btn btn-secondary btn-sm"
                :disabled="mcpHealthChecking"
                @click="handleRunHealthCheck"
              >
                {{ mcpHealthChecking ? '自检中…' : '健康自检' }}
              </button>
              <button
                class="btn btn-secondary btn-sm"
                @click="handleExportMcpJson"
              >
                导出契约 JSON
              </button>
              <button
                class="btn btn-secondary btn-sm"
                :disabled="mcpLoading"
                @click="handleRefreshMcpTools"
              >
                {{ mcpLoading ? '刷新中…' : '刷新清单' }}
              </button>
              <button
                class="btn btn-sign btn-sm"
                @click="handleOpenAddExternalServer"
              >
                媒体 MCP 说明
              </button>
            </div>
          </div>

          <!-- 通道状态指示横带 -->
          <div class="mcp-channels-strip mt14">
            <div class="channel-chip">
              <span class="status-dot"></span>
              <span class="channel-name">原生工具 (Native)</span>
              <span class="channel-meta mono">{{ nativeTools.length }} 个 · 进程直连</span>
            </div>
            <div class="channel-chip">
              <span class="status-dot" :class="{ 'is-disabled': internalMcpTools.length === 0 }"></span>
              <span class="channel-name">内部 MCP (Tasks)</span>
              <span class="channel-meta mono">{{ internalMcpTools.length }} 个 · 任务桥接</span>
            </div>
            <div class="channel-chip" :class="{ standby: !mediaMcpForm.enabled }">
              <span class="status-dot" :class="{ 'is-disabled': !mediaMcpForm.enabled }"></span>
              <span class="channel-name">媒体 MCP (Streamable HTTP)</span>
              <span class="channel-meta mono">{{ mediaMcpTools.length }} 个 · {{ mediaMcpForm.enabled ? '已启用' : '未启用' }}</span>
            </div>
          </div>

          <div class="media-mcp-config mt14">
            <div class="media-mcp-config-heading">
              <div>
                <div class="panel-section-title">生图与视频 MCP</div>
                <div class="small tertiary mt2">固定通过 Compose 内网 Streamable HTTP 调用；密钥仅在服务端保存，留空不会覆盖已保存密钥。</div>
              </div>
              <span class="badge" :class="mediaMcpForm.enabled ? 'badge-succeeded' : 'badge-warning'">
                {{ mediaMcpForm.enabled ? '已启用' : '未启用' }}
              </span>
            </div>
            <div class="media-mcp-form-grid mt12">
              <label class="runtime-field media-mcp-switch">
                <span class="field-label">启用媒体 MCP</span>
                <n-switch v-model:value="mediaMcpForm.enabled" />
              </label>
              <label class="runtime-field">
                <span class="field-label">兼容模式地址</span>
                <n-input v-model:value="mediaMcpForm.compatible_base_url" placeholder="https://…/compatible-mode/v1" />
              </label>
              <label class="runtime-field">
                <span class="field-label">API Key</span>
                <n-input v-model:value="mediaMcpForm.api_key" type="password" show-password-on="click" placeholder="留空保留已保存密钥" />
              </label>
              <label class="runtime-field">
                <span class="field-label">生图模型</span>
                <n-input v-model:value="mediaMcpForm.image_model" placeholder="qwen-image-3.0-pro" />
              </label>
              <label class="runtime-field">
                <span class="field-label">视频模型</span>
                <n-input v-model:value="mediaMcpForm.video_model" placeholder="happyhorse-1.1-i2v" />
              </label>
              <label class="runtime-field">
                <span class="field-label">MCP 调用超时（秒）</span>
                <n-input-number v-model:value="mediaMcpForm.request_timeout_s" :min="10" :max="600" style="width: 100%" />
              </label>
            </div>
            <div class="row mt12" style="justify-content: space-between; gap: 12px">
              <span class="small tertiary">{{ mediaMcpConfig?.has_api_key ? '已保存 API Key' : '尚未保存 API Key' }} · 视频使用首帧图生模式并异步返回任务 ID</span>
              <button class="btn btn-primary btn-sm" :disabled="mediaMcpSaving || mediaMcpConfigLoading" @click="saveMediaMcpConfig">
                {{ mediaMcpSaving ? '保存中…' : '保存媒体 MCP 配置' }}
              </button>
            </div>
          </div>
        </div>

        <!-- 工具清单过滤与呈现 -->
        <div class="panel">
          <div class="mcp-toolbar">
            <div class="mcp-filter-group">
              <!-- 通道分段器 -->
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
                  原生 ToolCall ({{ nativeTools.length }})
                </button>
                <button
                  class="pill-btn"
                  :class="{ active: mcpTransportFilter === 'mcp' }"
                  @click="mcpTransportFilter = 'mcp'"
                >
                  MCP 工具 ({{ mcpExtTools.length }})
                </button>
                <button
                  class="pill-btn"
                  :class="{ active: mcpTransportFilter === 'external' }"
                  @click="mcpTransportFilter = 'external'"
                >
                  接入说明
                </button>
              </div>

              <!-- 权限分段器 -->
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
                  只读 ({{ readToolsCount }})
                </button>
                <button
                  class="pill-btn"
                  :class="{ active: mcpPermFilter === 'write' }"
                  @click="mcpPermFilter = 'write'"
                >
                  写入 ({{ writeToolsCount }})
                </button>
              </div>

              <!-- 领域分类下拉 -->
              <div v-if="mcpTransportFilter !== 'external'" class="filter-dropdown-wrap">
                <n-select
                  v-model:value="mcpDomainFilter"
                  size="small"
                  :options="domainFilterOptions"
                />
              </div>

              <!-- 搜索框 -->
              <div v-if="mcpTransportFilter !== 'external'" class="filter-search-wrap">
                <n-input
                  v-model:value="mcpSearchKeyword"
                  size="small"
                  placeholder="搜索工具名或说明…"
                  clearable
                />
              </div>
            </div>

            <!-- 视图切换 -->
            <div v-if="mcpTransportFilter !== 'external'" class="view-mode-toggle">
              <button
                class="toggle-btn"
                :class="{ active: mcpViewMode === 'cards' }"
                @click="mcpViewMode = 'cards'"
              >
                卡片
              </button>
              <button
                class="toggle-btn"
                :class="{ active: mcpViewMode === 'table' }"
                @click="mcpViewMode = 'table'"
              >
                表格
              </button>
            </div>
          </div>

          <!-- 视图 1：外部网关技术规范说明 -->
          <div v-if="mcpTransportFilter === 'external'" class="external-gateway-panel mt16">
            <div class="ext-hero-box">
              <div style="flex: 1">
                <div class="ext-title">外部 MCP Server 接入规范与隔离说明</div>
                <div class="ext-desc">
                  媒体 MCP 使用标准 Streamable HTTP：API 先完成工具目录和权限裁决，再经 Compose 内网连接媒体服务。媒体服务独占上游凭据；生图同步返回临时地址，视频创建只返回异步任务 ID，须再查询状态。
                </div>
              </div>
              <button class="btn btn-sign btn-sm" @click="handleOpenAddExternalServer">
                查看接入边界
              </button>
            </div>

            <div class="ext-grid mt12">
              <div class="ext-card">
                <div class="ext-card-title">通信协议支持</div>
                <div class="ext-card-content">
                  • Streamable HTTP：initialize → tools/list → tools/call。<br>
                  • 服务发现固定为 Compose 私网 `media-mcp:8002/mcp`，不接受浏览器指定地址。
                </div>
              </div>
              <div class="ext-card">
                <div class="ext-card-title">安全风控门禁</div>
                <div class="ext-card-content">
                  • 目录、参数与权限在 API 内完成；媒体服务不向浏览器暴露上游密钥。<br>
                  • 视频创建不等待生成完成，查询结果中的临时视频地址需及时使用。
                </div>
              </div>
            </div>
          </div>

          <!-- 视图 2：卡片网格 -->
          <div v-else-if="mcpViewMode === 'cards'" class="mcp-cards-grid mt16">
            <div
              v-for="t in filteredMcpTools"
              :key="t.name"
              class="mcp-card"
              :class="{ 'is-disabled': t.enabled === false }"
            >
              <div class="mcp-card-top">
                <div class="mcp-tool-heading-wrap">
                  <div class="mcp-tool-icon-box" :class="`tool-icon-${getToolDomain(t.name).key}`">
                    <ToolIcon :name="t.name" :size="20" />
                  </div>
                  <div class="mcp-tool-heading">
                    <div class="mcp-tool-title">{{ t.display_name || t.name }}</div>
                    <div class="domain-tag mono">{{ t.name }}</div>
                  </div>
                </div>

                <div class="row" style="gap: 4px; flex-shrink: 0">
                  <span class="tag-soft">
                    {{ t.transport === 'native' ? '原生' : t.category === 'external_mcp' ? '媒体 MCP' : '内部 MCP' }}
                  </span>
                  <span class="tag-soft" :class="getRiskBadge(t.risk_level).cls">
                    {{ getRiskBadge(t.risk_level).label }}
                  </span>
                </div>
              </div>

              <div class="mcp-tool-desc">{{ t.desc }}</div>

              <div class="tool-schema-brief">
                <div class="schema-brief-row">
                  <span class="brief-k">入参:</span>
                  <span class="brief-v mono">{{ getToolParamsPreview(t) }}</span>
                </div>
                <div class="schema-brief-row">
                  <span class="brief-k">出参:</span>
                  <span class="brief-v mono">{{ getToolOutputsPreview(t) }}</span>
                </div>
              </div>

              <div class="mcp-card-bottom">
                <div class="row" style="gap: 6px; align-items: center">
                  <span class="status-dot" :class="{ 'is-disabled': t.enabled === false }"></span>
                  <span class="small tertiary">
                    {{ t.transport === 'native' ? '原生沙箱' : t.category === 'external_mcp' ? 'Streamable HTTP' : 'InProcess Host' }} · {{ t.timeout_s ?? '15' }}s
                  </span>
                </div>
                <button
                  class="btn btn-secondary btn-xs"
                  @click="handleOpenMcpModal(t)"
                >
                  契约详情
                </button>
              </div>
            </div>

            <div v-if="filteredMcpTools.length === 0" class="empty-state-wrap">
              <EmptyState :title="mcpEmptyTitle" :description="mcpEmptyDescription" />
            </div>
          </div>

          <!-- 视图 3：表格视图 -->
          <div v-else class="profile-table-scroll mt16">
            <table class="ds-table">
              <thead>
                <tr>
                  <th style="width: 170px">工具名称</th>
                  <th style="width: 100px">通道</th>
                  <th style="width: 100px">领域</th>
                  <th>说明</th>
                  <th style="width: 140px">入参概要</th>
                  <th style="width: 120px">出参概要</th>
                  <th style="width: 90px">权限</th>
                  <th style="width: 70px">超时</th>
                  <th style="width: 90px; text-align: right">操作</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="t in filteredMcpTools" :key="t.name">
                  <td>
                    <div class="mcp-table-tool-col">
                      <div class="mcp-table-tool-icon" :class="`tool-icon-${getToolDomain(t.name).key}`">
                        <ToolIcon :name="t.name" :size="15" />
                      </div>
                      <div class="mcp-table-tool-info">
                        <div style="font-weight: 600; font-size: 13px">{{ t.display_name || t.name }}</div>
                        <div class="mono small tertiary" style="font-size: 10.5px">{{ t.name }}</div>
                      </div>
                    </div>
                  </td>
                  <td>
                    <span class="tag-soft">
                      {{ t.transport === 'native' ? '原生' : t.category === 'external_mcp' ? '媒体 MCP' : '内部 MCP' }}
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
                  <td class="mono small">{{ t.timeout_s ? `${t.timeout_s}s` : '—' }}</td>
                  <td style="text-align: right">
                    <button class="link-btn small" @click="handleOpenMcpModal(t)">
                      详情
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
      </div>
    </template>

    <!-- ═══════════════════════════════════════════════════════════════
         Tab 4：Agent 技能编排 (Skills)
         ═══════════════════════════════════════════════════════════════ -->
    <template v-else-if="activeTab === 'skills'">
      <div class="skills-center-container">
        <!-- 顶部操作栏 -->
        <div class="panel">
          <div class="panel-header-row">
            <div class="panel-title-area">
              <span class="panel-title-text">Agent 技能编排</span>
              <span class="tag-soft">统一 SKILL.md · 4 大内置场景</span>
            </div>

            <div class="panel-actions-area">
              <button
                class="btn btn-secondary btn-sm"
                @click="handleExportSkillsJson"
              >
                导出配置
              </button>
              <button
                class="btn btn-sign btn-sm"
                :disabled="!selectedAgentProfile"
                :title="selectedAgentProfile ? `查看或编辑 ${selectedAgentProfile.name} 的补充提示词` : '请先在大模型协议档页指定 Agent 协议档'"
                @click="handleOpenAgentPrompt()"
              >
                Agent 提示词
              </button>
            </div>
          </div>
        </div>

        <!-- 技能列表 -->
        <div class="panel">
          <div class="skills-toolbar">
            <div class="skills-filter-group">
              <div class="pill-segmented">
                <button
                  class="pill-btn"
                  :class="{ active: skillCategoryFilter === 'all' }"
                  @click="skillCategoryFilter = 'all'"
                >
                  全部 ({{ builtinSkills.length }})
                </button>
                <button
                  class="pill-btn"
                  :class="{ active: skillCategoryFilter === 'benchmark' }"
                  @click="skillCategoryFilter = 'benchmark'"
                >
                  基准对比
                </button>
                <button
                  class="pill-btn"
                  :class="{ active: skillCategoryFilter === 'rag' }"
                  @click="skillCategoryFilter = 'rag'"
                >
                  RAG 评估
                </button>
                <button
                  class="pill-btn"
                  :class="{ active: skillCategoryFilter === 'testcase' }"
                  @click="skillCategoryFilter = 'testcase'"
                >
                  用例生成
                </button>
                <button
                  class="pill-btn"
                  :class="{ active: skillCategoryFilter === 'stress' }"
                  @click="skillCategoryFilter = 'stress'"
                >
                  容量压测
                </button>
              </div>

              <div class="filter-search-wrap">
                <n-input
                  v-model:value="skillSearchKeyword"
                  size="small"
                  placeholder="搜索技能名称或依赖工具…"
                  clearable
                />
              </div>
            </div>

            <div class="view-mode-toggle">
              <button
                class="toggle-btn"
                :class="{ active: skillViewMode === 'cards' }"
                @click="skillViewMode = 'cards'"
              >
                卡片
              </button>
              <button
                class="toggle-btn"
                :class="{ active: skillViewMode === 'table' }"
                @click="skillViewMode = 'table'"
              >
                表格
              </button>
            </div>
          </div>

          <!-- 卡片视图 -->
          <div v-if="skillViewMode === 'cards'" class="skills-cards-grid mt16">
            <div
              v-for="s in filteredSkills"
              :key="s.id"
              class="skill-card-v2"
            >
              <div class="skill-card-top">
                <div class="skill-card-heading">
                  <div class="skill-card-name">{{ s.name }}</div>
                  <div class="skill-scenario-tag">{{ s.scenario }}</div>
                </div>
                <span class="tag-soft">核心</span>
              </div>

              <div class="skill-card-desc">{{ s.desc }}</div>

              <!-- 调优参数 -->
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

              <!-- 斜杠命令 -->
              <div class="skill-cmds-row">
                <span class="cmd-label">命令:</span>
                <div class="row wrap" style="gap: 4px">
                  <span v-for="cmd in s.slashCommands" :key="cmd" class="cmd-tag mono">{{ cmd }}</span>
                </div>
              </div>

              <!-- 依赖工具 -->
              <div class="skill-tools-row">
                <span class="tools-label">工具:</span>
                <div class="row wrap" style="gap: 4px">
                  <span v-for="t in s.tools" :key="t" class="tool-tag mono">{{ t }}</span>
                </div>
              </div>

              <div class="skill-card-bottom">
                <span class="small tertiary mono">SKILL.md</span>
                <div class="row" style="gap: 6px">
                  <button class="btn btn-secondary btn-xs" @click="handleOpenSkillModal(s)">编排详情</button>
                  <button class="btn btn-sign btn-xs" @click="handleOpenSkillFile(s)">预览 / 编辑</button>
                </div>
              </div>
            </div>

            <div v-if="filteredSkills.length === 0" class="empty-state-wrap">
              <EmptyState title="未找到匹配的 Agent 技能" description="请尝试清空搜索条件或重置筛选器" />
            </div>
          </div>

          <!-- 表格视图 -->
          <div v-else class="profile-table-scroll mt16">
            <table class="ds-table">
              <thead>
                <tr>
                  <th style="width: 150px">技能名称</th>
                  <th style="width: 140px">适用场景</th>
                  <th>职责说明</th>
                  <th style="width: 160px">触发命令</th>
                  <th style="width: 180px">依赖短工具</th>
                  <th style="width: 130px">调优参数</th>
                  <th style="width: 80px">状态</th>
                  <th style="width: 120px; text-align: right">操作</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="s in filteredSkills" :key="s.id">
                  <td>
                    <div style="font-weight: 600; font-size: 13px">{{ s.name }}</div>
                    <div class="mono small tertiary" style="font-size: 10px">{{ s.id }}</div>
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
                    <div class="mono small" style="color: var(--c-profiles)">
                      T={{ s.temperature }} · {{ s.maxTokens }}t
                    </div>
                  </td>
                  <td>
                    <span class="badge badge-succeeded">活跃</span>
                  </td>
                  <td style="text-align: right">
                    <div class="row" style="justify-content: flex-end; gap: 4px">
                      <button class="link-btn small" @click="handleOpenSkillModal(s)">详情</button>
                      <button class="link-btn small" @click="handleOpenSkillFile(s)">编辑</button>
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
      </div>
    </template>

    <!-- ═══════════════════════════════════════════════════════════════
         Tab 5：运行时与主机治理 (Runtime)
         ═══════════════════════════════════════════════════════════════ -->
    <template v-else>
      <div class="panel runtime-governance-panel">
        <!-- 1. 会话与连接参数 -->
        <div class="runtime-section">
          <div class="panel-section-title">WebSocket 会话与连接参数</div>
          <div class="runtime-form-row mt10">
            <div class="runtime-field">
              <label class="field-label">心跳 Ping 间隔 (秒)</label>
              <n-input-number v-model:value="runtimeForm.ws_ping_s" :min="5" :max="300" style="width: 100%" />
            </div>
            <div class="runtime-field">
              <label class="field-label">连接超时断开 (秒)</label>
              <n-input-number v-model:value="runtimeForm.ws_timeout_s" :min="5" :max="300" style="width: 100%" />
            </div>
            <div class="runtime-field">
              <label class="field-label">WS Ticket 授权 TTL (秒)</label>
              <n-input-number :value="300" disabled style="width: 100%" />
              <span class="field-hint">一次性授权票据，固定 5 分钟 (PRD §5.1)</span>
            </div>
          </div>
        </div>

        <div class="runtime-divider"></div>

        <!-- 2. 会话互斥与长任务槽位 -->
        <div class="runtime-section">
          <div class="panel-section-title">会话占槽与并发互斥规则</div>
          <div class="small tertiary mt2 mb10">
            当前会话有进行中任务（含压测子任务）时，主按钮自动禁用，完成后方可开启新长任务 (PRD §3.4)。
          </div>
          <label class="row" style="gap: 10px; align-items: center; cursor: pointer">
            <n-switch v-model:value="runtimeForm.strict_session_slot" />
            <span style="font-weight: 600; font-size: 13.5px">严格会话占槽互斥：压测等长任务执行期间保持槽位独占</span>
          </label>
        </div>

        <div class="runtime-divider"></div>

        <!-- 3. 安全权限等级 -->
        <div class="runtime-section">
          <div class="panel-section-title">全局默认权限等级</div>
          <div class="small tertiary mt2 mb10">
            控制 Agent 会话执行写操作、联网与命令调用的授权策略；单会话可在此基础上自定义调整。
          </div>
          <div class="runtime-tier-select-wrap">
            <n-select
              v-model:value="runtimeForm.permission_tier_default"
              :options="permissionTierOptions"
              style="width: 380px; max-width: 100%;"
            />
          </div>
        </div>

        <div class="runtime-footer mt20">
          <button
            class="btn btn-primary btn-sm"
            :disabled="runtimeSaving"
            @click="saveRuntime"
          >
            {{ runtimeSaving ? '保存中…' : '保存运行时治理参数' }}
          </button>
        </div>
      </div>
    </template>

    <!-- 模态弹窗 -->
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
import type { MediaMcpConfig, Profile, ProfileCheckOut, McpTool, McpHealthCheckResponse } from '../api/types'
import EmptyState from '../components/common/EmptyState.vue'
import ProviderLogo, { type ProviderLogoKey } from '../components/ProviderLogo.vue'
import { getModelLogoKey } from '../utils/providerLogo'
import { PROFILE_VENDORS, getProfileVendor } from '../utils/profileVendors'
import ProfileModal from '../components/modals/ProfileModal.vue'
import CheckResultModal from '../components/modals/CheckResultModal.vue'
import McpToolModal from '../components/modals/McpToolModal.vue'
import SkillDetailModal, { type SkillDetail } from '../components/modals/SkillDetailModal.vue'
import AgentSkillFileModal from '../components/modals/AgentSkillFileModal.vue'
import AgentPromptModal from '../components/modals/AgentPromptModal.vue'
import ToolIcon from '../components/agent/loop/ToolIcon.vue'

const message = useMessage()
const dialog = useDialog()

// 5 Tab 架构：profiles / rag_models / mcp / skills / runtime
type TabKey = 'profiles' | 'rag_models' | 'mcp' | 'skills' | 'runtime'
const tabs: { key: TabKey; label: string }[] = [
  { key: 'profiles', label: '模型协议档' },
  { key: 'rag_models', label: '向量与重排 (RAG)' },
  { key: 'mcp', label: 'MCP 与工具' },
  { key: 'skills', label: 'Agent 技能' },
  { key: 'runtime', label: '运行时治理' },
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
const mcpTools = ref<McpTool[]>([])
const mcpViewMode = ref<'cards' | 'table'>('cards')
const mcpPermFilter = ref<'all' | 'read' | 'write'>('all')
const mcpTransportFilter = ref<'all' | 'native' | 'mcp' | 'external'>('all')
const mcpDomainFilter = ref<string>('all')
const mcpSearchKeyword = ref('')
const mcpLoading = ref(false)
const mcpServerPingState = ref<{ ok: boolean; latencyMs: number | null } | null>(null)

// 全通道健康与连通性自检状态
const mcpHealthResult = ref<McpHealthCheckResponse | null>(null)
const mcpHealthChecking = ref(false)

type McpRequestState = 'idle' | 'loading' | 'success' | 'error'
const mcpRequestState = ref<McpRequestState>('idle')
const mcpRequestError = ref('')
const selectedMcpTool = ref<McpTool | null>(null)
const showMcpModal = ref(false)
const mediaMcpConfig = ref<MediaMcpConfig | null>(null)
const mediaMcpConfigLoading = ref(false)
const mediaMcpSaving = ref(false)
const mediaMcpForm = ref({
  enabled: false,
  compatible_base_url: '',
  api_key: '',
  image_model: 'qwen-image-3.0-pro',
  video_model: 'happyhorse-1.1-i2v',
  request_timeout_s: 180,
})

/** 原生基础工具（transport=native），由 NativeToolExecutor 直连执行 */
const nativeTools = computed(() => mcpTools.value.filter((t) => t.transport === 'native'))
/** 内部 MCP 扩展工具（transport=mcp），通过 MCPClientManager 调用 */
const mcpExtTools = computed(() => mcpTools.value.filter((t) => t.transport === 'mcp'))
const internalMcpTools = computed(() => mcpExtTools.value.filter((t) => t.category !== 'external_mcp'))
const mediaMcpTools = computed(() => mcpExtTools.value.filter((t) => t.category === 'external_mcp'))

const domainFilterOptions = [
  { label: '全部领域', value: 'all' },
  { label: '文件系统', value: 'file' },
  { label: '网络抓取', value: 'web' },
  { label: '沙箱命令', value: 'bash' },
  { label: '任务规划', value: 'plan' },
  { label: '任务调度', value: 'task' },
  { label: '模型资产', value: 'model' },
  { label: '数据集', value: 'dataset' },
  { label: '知识库', value: 'kb' },
  { label: '评测报告', value: 'report' },
  { label: '调度算力', value: 'dispatch' },
  { label: '用例管理', value: 'cases' },
  { label: '音色克隆', value: 'audio' },
  { label: '图像生成', value: 'image' },
]

/** 获取工具业务领域与图标映射 */
function getToolDomain(name: string): { label: string; icon: string; key: string } {
  if (
    name === 'read' ||
    name === 'read_image' ||
    name === 'write' ||
    name === 'edit' ||
    name === 'glob' ||
    name === 'grep' ||
    name === 'list_dir' ||
    name === 'str_replace_editor'
  ) {
    return { label: '文件系统', icon: '', key: 'file' }
  }
  if (name === 'web_search' || name === 'web_fetch') return { label: '网络抓取', icon: '', key: 'web' }
  if (name === 'bash') return { label: '沙箱命令', icon: '', key: 'bash' }
  if (name === 'task' || name === 'ask_user_question') return { label: '任务规划', icon: '', key: 'plan' }
  if (
    name.includes('task.create') ||
    name.includes('task.status') ||
    name.includes('task.cancel') ||
    name.startsWith('Task')
  ) {
    return { label: '任务调度', icon: '', key: 'task' }
  }
  if (name.startsWith('model.')) return { label: '模型资产', icon: '', key: 'model' }
  if (name.startsWith('dataset.')) return { label: '数据集', icon: '', key: 'dataset' }
  if (name.startsWith('kb.')) return { label: '知识库', icon: '', key: 'kb' }
  if (name.startsWith('report.')) return { label: '评测报告', icon: '', key: 'report' }
  if (name.startsWith('dispatch.')) return { label: '调度大盘', icon: '', key: 'dispatch' }
  if (name.startsWith('testcase.')) return { label: '用例管理', icon: '', key: 'cases' }
  if (name.startsWith('audio.')) return { label: '音色克隆', icon: '', key: 'audio' }
  if (name.startsWith('image.') || name.startsWith('video.') || name.includes('.image.generate') || name.includes('.video.')) {
    return { label: '媒体生成', icon: '', key: 'image' }
  }
  return { label: '内置通用', icon: '', key: 'other' }
}

/** 获取风险等级徽标配置 */
function getRiskBadge(risk?: string): { label: string; cls: string } {
  switch (risk) {
    case 'read': return { label: 'READ', cls: 'perm-badge-read' }
    case 'network': return { label: 'NET', cls: 'perm-badge-network' }
    case 'modify': return { label: 'WRITE', cls: 'perm-badge-write' }
    case 'code': return { label: 'CODE', cls: 'perm-badge-code' }
    case 'long': return { label: 'LONG', cls: 'perm-badge-write' }
    default: return { label: 'WRITE', cls: 'perm-badge-write' }
  }
}

const readToolsCount = computed(() => mcpTools.value.filter((t) => t.permission === 'read').length)
const writeToolsCount = computed(() => mcpTools.value.filter((t) => t.permission === 'write').length)
const disabledMcpToolsCount = computed(() => mcpTools.value.filter((t) => t.enabled === false).length)

const mcpBadgeClass = computed(() => {
  return mcpRequestState.value === 'success' && mcpTools.value.length > 0
    ? 'badge-succeeded'
    : 'badge-warning'
})

const mcpBadgeText = computed(() => {
  if (mcpRequestState.value === 'idle') return '尚未检查'
  if (mcpRequestState.value === 'loading') return '检查中…'
  if (mcpRequestState.value === 'error') return '接口不可用'
  if (mcpTools.value.length === 0) return '清单为空'
  return disabledMcpToolsCount.value ? `${disabledMcpToolsCount.value} 项未挂载` : '清单正常'
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

function getToolOutputsPreview(t: McpTool): string {
  const schema = t.output_schema
  if (!schema || !schema.properties) return 'summary'
  const keys = Object.keys(schema.properties)
  if (keys.length === 0) return 'summary'
  return keys.slice(0, 2).join(', ') + (keys.length > 2 ? ` +${keys.length - 2}` : '')
}

const filteredMcpTools = computed(() => {
  return mcpTools.value.filter((t) => {
    if (mcpTransportFilter.value === 'native' && t.transport !== 'native') return false
    if (mcpTransportFilter.value === 'mcp' && t.transport !== 'mcp') return false
    if (mcpTransportFilter.value === 'external') return false
    if (mcpPermFilter.value !== 'all' && t.permission !== mcpPermFilter.value) return false
    if (mcpDomainFilter.value !== 'all') {
      const domain = getToolDomain(t.name)
      if (domain.key !== mcpDomainFilter.value) return false
    }
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

/** 将脱敏服务端配置投影到可编辑表单，Key 输入框始终保持空白。 */
function applyMediaMcpConfig(config: MediaMcpConfig) {
  mediaMcpConfig.value = config
  mediaMcpForm.value = {
    enabled: config.enabled,
    compatible_base_url: config.compatible_base_url,
    api_key: '',
    image_model: config.image_model,
    video_model: config.video_model,
    request_timeout_s: config.request_timeout_s,
  }
}

async function saveMediaMcpConfig() {
  mediaMcpSaving.value = true
  try {
    const saved = await api.mcp.updateMediaConfig({
      enabled: mediaMcpForm.value.enabled,
      compatible_base_url: mediaMcpForm.value.compatible_base_url.trim(),
      api_key: mediaMcpForm.value.api_key.trim() || undefined,
      image_model: mediaMcpForm.value.image_model.trim(),
      video_model: mediaMcpForm.value.video_model.trim(),
      request_timeout_s: mediaMcpForm.value.request_timeout_s,
    })
    applyMediaMcpConfig(saved)
    await handleRefreshMcpTools()
    message.success('媒体 MCP 配置已保存')
  } catch (err: any) {
    message.error(err.message || '媒体 MCP 配置保存失败')
  } finally {
    mediaMcpSaving.value = false
  }
}

async function handleRunHealthCheck() {
  mcpHealthChecking.value = true
  try {
    const res = await api.mcp.healthCheck()
    mcpHealthResult.value = res
    message.success(`自检完成 · 耗时 ${res.total_latency_ms}ms · 原生(${res.summary.native_tools_count}) · 内部 MCP(${res.summary.internal_mcp_tools_count}) · 媒体(${res.summary.external_mcp_servers_count})`)
  } catch (err: any) {
    message.error(`健康自检失败: ${err.message || '网络连接异常'}`)
  } finally {
    mcpHealthChecking.value = false
  }
}

async function handleRefreshMcpTools() {
  mcpLoading.value = true
  mediaMcpConfigLoading.value = true
  mcpRequestState.value = 'loading'
  mcpRequestError.value = ''
  const start = performance.now()
  try {
    const [res, healthRes, mediaConfig] = await Promise.all([
      api.mcp.tools(),
      api.mcp.healthCheck().catch(() => null),
      api.mcp.mediaConfig().catch(() => null),
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
    if (mediaConfig) {
      applyMediaMcpConfig(mediaConfig)
    }
    if (mcpTools.value.length > 0) {
      message.success(`已加载 ${mcpTools.value.length} 个工具 · ${mcpServerPingState.value.latencyMs}ms`)
    }
  } catch (err: any) {
    mcpRequestState.value = 'error'
    mcpRequestError.value = err.message || '调用 /api/mcp/all-tools 接口失败'
    mcpTools.value = []
    mcpServerPingState.value = { ok: false, latencyMs: null }
    message.error(mcpRequestError.value)
  } finally {
    mcpLoading.value = false
    mediaMcpConfigLoading.value = false
  }
}

function safeBlur() {
  if (typeof document !== 'undefined' && document.activeElement instanceof HTMLElement) {
    document.activeElement.blur()
  }
}

function handleOpenMcpModal(tool: McpTool) {
  safeBlur()
  selectedMcpTool.value = tool
  showMcpModal.value = true
}

function handleExportMcpJson() {
  safeBlur()
  try {
    const payload = JSON.stringify(mcpTools.value, null, 2)
    navigator.clipboard.writeText(payload)
    message.success('已复制 MCP 工具契约 JSON')
  } catch {
    message.info('请在安全上下文中复制契约')
  }
}

function handleOpenAddExternalServer() {
  safeBlur()
  dialog.info({
    title: '媒体 MCP · 架构边界说明',
    content:
      '当前仅接入平台部署的 media-mcp 服务。API 固定通过 Compose 私网地址建立 Streamable HTTP 会话，媒体服务独占上游凭据；浏览器无法添加任意第三方 Server 或直接调用模型端点。',
    positiveText: '了解边界',
  })
}

// ═══════════════════════════════════════════════════════════════
// Agent 技能编排 (Skills & Prompts)
// ═══════════════════════════════════════════════════════════════
const builtinSkills: SkillDetail[] = [
  {
    id: 'skill-benchmark',
    icon: '',
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
    icon: '',
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
    icon: '',
    name: 'PRD 用例生成',
    desc: '按 6 大策略精细配比提炼测试用例并支持确认转正。',
    scenario: 'AI 需求与用例生成',
    tools: ['dataset.list', 'task.create', 'testcase.confirm'],
    slashCommands: ['/case', '/generate', '/prd'],
    temperature: 0.3,
    maxTokens: 3072,
    topP: 0.95,
  },
  {
    id: 'skill-stress',
    icon: '',
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

function handleOpenSkillModal(skill: SkillDetail) {
  safeBlur()
  selectedSkill.value = skill
  showSkillModal.value = true
}

function handleOpenSkillFile(skill: SkillDetail) {
  safeBlur()
  selectedSkillFileId.value = skill.id
  showSkillFileModal.value = true
}

function handleExportSkillsJson() {
  safeBlur()
  try {
    const payload = JSON.stringify(builtinSkills, null, 2)
    navigator.clipboard.writeText(payload)
    message.success('已复制技能配置 JSON')
  } catch {
    message.info('请在安全上下文中复制配置')
  }
}

// ═══════════════════════════════════════════════════════════════
// 运行时治理
// ═══════════════════════════════════════════════════════════════
const runtimeForm = ref({
  ws_ping_s: 15,
  ws_timeout_s: 45,
  strict_session_slot: true,
  permission_tier_default: 'tier1',
})
const runtimeSaving = ref(false)

const permissionTierOptions = [
  { label: '档1 请求批准（每次写操作与命令需逐次确认）', value: 'tier1' },
  { label: '档2 帮我批准（工作区写入自动，破坏性命令需确认）', value: 'tier2' },
  { label: '档3 完全访问（全部自动，灾难性命令一律拦截）', value: 'tier3' },
]

// ═══════════════════════════════════════════════════════════════
// 大模型协议档 (Profiles)
// ═══════════════════════════════════════════════════════════════
const viewMode = ref<'cards' | 'table'>('cards')
const profiles = ref<Profile[]>([])
const profileSearch = ref('')
const vendorFilter = ref<string | null>(null)
const usageFilter = ref<string | null>(null)

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
const lastSavedAgentProfileId = ref<string | null>(null)
const agentProfileSaving = ref(false)
const showAgentPromptModal = ref(false)
const promptProfile = ref<Profile | null>(null)
const selectedAgentProfile = computed(() => (
  profiles.value.find((profile) => profile.id === selectedAgentProfileId.value) || null
))

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
// 全局向量与重排模型 (RAG)
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
  message.info(`已填充预设: ${item.model}`)
}

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
  message.info(`已填充预设: ${item.model}`)
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
      message.success(`Embedding 连通正常 (${res.latency_ms}ms)`)
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
      message.success(`Reranker 连通正常 (${res.latency_ms}ms)`)
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
    } else {
      message.error('协议档加载失败，请重试')
    }
    if (settingsRes.status === 'rejected') {
      message.error('默认模型设置加载失败，请重试')
    }
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
    message.success('运行时治理参数已更新')
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
    message.success('Agent 默认模型已指定')
  } catch (err: any) {
    selectedAgentProfileId.value = lastSavedAgentProfileId.value
    message.error(err.message || '设置失败')
  } finally {
    agentProfileSaving.value = false
  }
}

async function handlePing(p: Profile) {
  if (pinging.value[p.id]) return
  pinging.value[p.id] = true
  try {
    const res = await api.profiles.check(p.id)
    pingStates.value[p.id] = { ok: !!res.ok, latencyMs: res.latency_ms ?? null }
    if (res.ok) {
      message.success(`[${p.name}] 连通正常 · ${res.latency_ms ?? '—'}ms`)
    } else {
      message.error(`[${p.name}] 连通测试失败`)
    }
  } catch (err: any) {
    pingStates.value[p.id] = { ok: false, latencyMs: null }
    message.error(`[${p.name}] ${err.message || '连通测试失败'}`)
  } finally {
    delete pinging.value[p.id]
  }
}

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
/* ═══════════════════════════════════════════════════════════════
   全局页面骨架与自适应容器
   ═══════════════════════════════════════════════════════════════ */
.profiles-page {
  display: flex;
  flex-direction: column;
  gap: 16px;
  width: 100%;
  max-width: 100%;
  box-sizing: border-box;
}

/* 导航 Tabs */
.tabs-nav-bar {
  display: flex;
  align-items: center;
  gap: 6px;
  overflow-x: auto;
  white-space: nowrap;
  padding: 4px;
  background: var(--bg-card, #ffffff);
  border: 1px solid var(--border-subtle, rgba(0, 0, 0, 0.08));
  border-radius: 10px;
  box-sizing: border-box;
  -webkit-overflow-scrolling: touch;
}
.tabs-nav-bar::-webkit-scrollbar {
  height: 0;
}
.profile-tab-btn {
  padding: 8px 16px;
  border-radius: 7px;
  border: none;
  background: transparent;
  color: var(--text-secondary, #6b7280);
  font-size: 13.5px;
  font-weight: 500;
  cursor: pointer;
  transition: all 0.15s ease;
  user-select: none;
  white-space: nowrap;
}
.profile-tab-btn:hover {
  color: var(--text-primary, #111827);
  background: var(--bg-elevated, rgba(0, 0, 0, 0.03));
}
.profile-tab-btn.active {
  background: var(--t-profiles, rgba(22, 151, 122, 0.1));
  color: var(--c-profiles, #1f5947);
  font-weight: 600;
}

/* 通用面板标题与操作栏 */
.panel-header-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  flex-wrap: wrap;
  gap: 12px;
}
.panel-title-area {
  display: flex;
  align-items: center;
  gap: 10px;
  min-width: 0;
}
.panel-title-text {
  font-size: 15px;
  font-weight: 700;
  color: var(--text-primary, #111827);
  letter-spacing: -0.01em;
}
.panel-count-pill {
  font-size: 11.5px;
  font-family: var(--font-mono);
  color: var(--text-tertiary, #9ca3af);
  background: var(--bg-elevated, #f3f4f6);
  padding: 2px 8px;
  border-radius: 12px;
  border: 1px solid var(--border-subtle, rgba(0, 0, 0, 0.06));
}
.panel-actions-area {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

/* 视图切换按钮 */
.view-mode-toggle {
  display: inline-flex;
  background: var(--bg-elevated, #f3f4f6);
  padding: 3px;
  border-radius: 8px;
  border: 1px solid var(--border-subtle, rgba(0, 0, 0, 0.08));
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
  color: var(--c-profiles, #1f5947);
  font-weight: 600;
  box-shadow: 0 1px 2px rgba(0, 0, 0, 0.05);
}

/* ═══════════════════════════════════════════════════════════════
   Tab 1：大模型协议档
   ═══════════════════════════════════════════════════════════════ */
/* Agent 默认模型横向控制条 */
.agent-default-bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  flex-wrap: wrap;
  gap: 14px;
  padding: 12px 18px;
}
.agent-default-info {
  display: flex;
  align-items: center;
  gap: 12px;
  min-width: 0;
  flex: 1 1 320px;
}
.agent-default-badge {
  font-size: 11px;
  font-weight: 700;
  color: var(--c-profiles, #1f5947);
  background: var(--t-profiles, rgba(22, 151, 122, 0.1));
  border: 1px solid var(--c-profiles, rgba(22, 151, 122, 0.2));
  padding: 3px 8px;
  border-radius: 6px;
  white-space: nowrap;
}
.agent-default-content {
  display: flex;
  align-items: center;
  gap: 8px;
  min-width: 0;
  flex-wrap: wrap;
}
.agent-default-content.empty {
  color: var(--text-tertiary, #9ca3af);
  font-size: 12.5px;
}
.agent-default-name {
  font-size: 13.5px;
  font-weight: 600;
  color: var(--text-primary, #111827);
  white-space: nowrap;
}
.agent-default-model {
  font-size: 12px;
  color: var(--text-secondary, #4b5563);
  background: var(--bg-elevated, #f3f4f6);
  padding: 2px 7px;
  border-radius: 4px;
  white-space: nowrap;
}
.agent-default-url-tag {
  font-size: 10.5px;
  color: var(--text-tertiary, #9ca3af);
}
.agent-default-controls {
  display: flex;
  align-items: center;
  gap: 8px;
  flex: 0 0 auto;
}
.agent-select-input {
  width: 260px;
}
@media (max-width: 640px) {
  .agent-default-controls {
    width: 100%;
  }
  .agent-select-input {
    flex: 1;
    width: auto;
  }
  .vendor-models-grid {
    grid-template-columns: 1fr;
  }
}

/* 协议档筛选工具条 */
.profile-filters-bar {
  display: flex;
  align-items: center;
  gap: 10px;
  margin: 12px 0 16px;
  flex-wrap: wrap;
}
.filter-search-input {
  flex: 1 1 240px;
  min-width: 180px;
}
.filter-select {
  flex: 0 1 170px;
  min-width: 130px;
}

/* 供应商卡片容器与自适应网格 */
.vendor-cards-container {
  display: flex;
  flex-direction: column;
  gap: 16px;
}
.vendor-group-card {
  border: 1px solid var(--border-subtle, rgba(0, 0, 0, 0.08));
  border-radius: 14px;
  background: var(--bg-card, #ffffff);
  padding: 16px 18px;
  display: flex;
  flex-direction: column;
  gap: 12px;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.02);
  transition: border-color 0.2s ease, box-shadow 0.2s ease;
}
.vendor-group-card:hover {
  border-color: rgba(217, 119, 6, 0.3);
  box-shadow: 0 4px 14px rgba(0, 0, 0, 0.04);
}
.vendor-group-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  border-bottom: 1px solid var(--border-subtle, rgba(0, 0, 0, 0.06));
  padding-bottom: 10px;
}
.vendor-info {
  min-width: 0;
  flex: 1;
}
.vendor-title-row {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}
.vendor-name {
  font-size: 14.5px;
  font-weight: 700;
  color: var(--text-primary, #111827);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.vendor-count-badge {
  font-size: 11px;
  background: var(--t-profiles, #fef3c7);
  color: var(--c-profiles, #b45309);
  padding: 1.5px 7px;
  border-radius: 10px;
  font-weight: 600;
  border: 1px solid rgba(180, 83, 9, 0.15);
}
.vendor-url {
  font-size: 11px;
  color: var(--text-tertiary, #9ca3af);
  margin-top: 2px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

/* 内部模型芯片网格与动态流光动效 */
@keyframes pulse-border {
  0%, 100% {
    border-color: rgba(217, 119, 6, 0.65);
    box-shadow: 0 0 12px rgba(217, 119, 6, 0.15);
  }
  50% {
    border-color: rgba(245, 158, 11, 0.95);
    box-shadow: 0 0 20px rgba(245, 158, 11, 0.28);
  }
}

.vendor-models-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(320px, 1fr));
  gap: 12px;
  width: 100%;
}
.model-chip-card {
  background: var(--bg-card, #ffffff);
  border: 1px solid var(--border-subtle, rgba(0, 0, 0, 0.08));
  border-radius: 12px;
  padding: 14px 16px;
  display: flex;
  flex-direction: column;
  gap: 10px;
  position: relative;
  min-width: 0;
  box-sizing: border-box;
  transition: all 0.22s cubic-bezier(0.4, 0, 0.2, 1);
}
.model-chip-card:hover {
  transform: translateY(-2px);
  border-color: rgba(217, 119, 6, 0.45);
  box-shadow: 0 6px 20px -2px rgba(217, 119, 6, 0.12);
}
.model-chip-card.is-agent-core {
  background: #FEF3C7;
  border: 1.5px solid #d97706;
  border-radius: 12px;
  box-shadow: 0 4px 14px rgba(217, 119, 6, 0.15);
  animation: pulse-border 3.2s ease-in-out infinite;
}
.model-chip-card.is-agent-core:hover {
  transform: translateY(-2px);
  box-shadow: 0 8px 24px -2px rgba(217, 119, 6, 0.25);
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
  flex: 1;
}
.model-chip-brand {
  flex: 0 0 auto;
}
.model-chip-name {
  font-size: 13.5px;
  font-weight: 600;
  color: var(--text-primary, #111827);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.provider-cell-name {
  overflow: hidden;
  color: var(--text-secondary, #4b5563);
  font-size: 12px;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.model-id-cell {
  align-items: center;
  gap: 6px;
  min-width: 0;
}
.model-id-cell .mono {
  min-width: 0;
  overflow: hidden;
  font-size: 12px;
  font-weight: 600;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.agent-core-tag {
  background: #ffffff;
  color: #b45309;
  border: 1px solid #b45309;
  border-radius: 999px;
  padding: 1.5px 8px;
  font-size: 11px;
  font-weight: 600;
  white-space: nowrap;
}
.model-chip-meta {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 11px;
  flex-wrap: wrap;
}
.model-id-tag {
  background: var(--bg-elevated, #f3f4f6);
  padding: 2px 7px;
  border-radius: 5px;
  font-weight: 600;
  color: var(--text-secondary, #374151);
  border: 1px solid var(--border-subtle, rgba(0, 0, 0, 0.06));
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  max-width: 220px;
}
.model-chip-card.is-agent-core .model-id-tag {
  background: #ffffff;
  border-color: rgba(0, 0, 0, 0.08);
  color: #1e293b;
}
.protocol-tag {
  color: var(--text-tertiary, #9ca3af);
}
.model-chip-card.is-agent-core .protocol-tag {
  color: #6b7280;
}
.url-mode-tag {
  border-radius: 4px;
  background: var(--t-profiles, rgba(22, 151, 122, 0.1));
  color: var(--c-profiles, #1f5947);
  padding: 1px 5px;
  font-size: 10.5px;
  font-family: var(--font-mono);
}
.window-tag {
  padding: 1px 6px;
  background: var(--bg-elevated, #f3f4f6);
  color: var(--text-secondary, #4b5563);
  border-radius: 4px;
  font-size: 11px;
}
.model-chip-card.is-agent-core .window-tag {
  background: #ffffff;
  color: #4b5563;
  border: 1px solid rgba(0, 0, 0, 0.06);
}
.model-chip-bottom {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  padding-top: 8px;
  border-top: 1px solid var(--border-subtle, rgba(0, 0, 0, 0.04));
  margin-top: 4px;
}
.model-chip-card.is-agent-core .model-chip-bottom {
  border-top-color: rgba(217, 119, 6, 0.2);
}
.model-chip-bottom .link-btn {
  color: #047857;
  font-size: 12px;
  font-weight: 500;
  transition: color 0.15s ease;
}
.model-chip-bottom .link-btn:hover {
  color: #065f46;
}
.model-chip-bottom .link-btn.danger {
  color: #9ca3af;
}
.model-chip-bottom .link-btn.danger:hover {
  color: #ef4444;
}

/* 探活轻量化胶囊 */
.ping-badge {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  font-family: var(--font-mono);
  font-size: 11px;
  padding: 2px 7px;
  border-radius: 5px;
  cursor: pointer;
  white-space: nowrap;
  border: 1px solid transparent;
}
.ping-badge.ok {
  background: rgba(16, 185, 129, 0.1);
  color: var(--accent-success, #10b981);
  border-color: rgba(16, 185, 129, 0.25);
}
.ping-badge.err {
  background: rgba(239, 68, 68, 0.1);
  color: var(--accent-error, #ef4444);
  border-color: rgba(239, 68, 68, 0.25);
}

/* 表格响应式滚动 */
.profile-table-scroll {
  overflow-x: auto;
  width: 100%;
  -webkit-overflow-scrolling: touch;
}
.profile-table-scroll table {
  min-width: 900px;
  width: 100%;
}

/* ═══════════════════════════════════════════════════════════════
   Tab 2：向量与重排模型 (RAG)
   ═══════════════════════════════════════════════════════════════ */
.rag-models-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(380px, 1fr));
  gap: 16px;
}
.rag-model-card {
  background: var(--bg-elevated, #f9fafb);
  border: 1px solid var(--border-subtle, rgba(0, 0, 0, 0.08));
  border-radius: 12px;
  padding: 18px;
  display: flex;
  flex-direction: column;
  box-sizing: border-box;
}
.rag-card-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  padding-bottom: 12px;
  border-bottom: 1px solid var(--border-subtle, rgba(0, 0, 0, 0.06));
}
.rag-type-pill {
  font-size: 14px;
  font-weight: 700;
  color: var(--text-primary, #111827);
}
.rag-model-sub {
  font-size: 11.5px;
  color: var(--text-tertiary, #9ca3af);
}
.key-status-badge {
  font-size: 11px;
  padding: 2px 8px;
  border-radius: 6px;
  font-weight: 500;
}
.key-status-badge.ok {
  background: rgba(16, 185, 129, 0.1);
  color: var(--accent-success, #10b981);
}
.key-status-badge.none {
  background: var(--bg-card, #ffffff);
  color: var(--text-tertiary, #9ca3af);
  border: 1px solid var(--border-subtle, rgba(0, 0, 0, 0.08));
}
.rag-check-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  flex-wrap: wrap;
  padding-top: 8px;
  border-top: 1px solid var(--border-subtle, rgba(0, 0, 0, 0.06));
}
.rag-check-feedback {
  font-size: 11.5px;
}
.rag-check-feedback.success {
  color: var(--accent-success, #10b981);
  font-weight: 500;
}
.rag-check-feedback.fail {
  color: var(--accent-error, #ef4444);
}

/* ═══════════════════════════════════════════════════════════════
   Tab 3：MCP 服务器与工具清单
   ═══════════════════════════════════════════════════════════════ */
.mcp-center-container {
  display: flex;
  flex-direction: column;
  gap: 16px;
}
.mcp-channels-strip {
  display: flex;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
}
.channel-chip {
  display: flex;
  align-items: center;
  gap: 8px;
  background: var(--bg-elevated, #f9fafb);
  border: 1px solid var(--border-subtle, rgba(0, 0, 0, 0.08));
  padding: 8px 14px;
  border-radius: 8px;
  font-size: 12.5px;
  flex: 1 1 200px;
}
.channel-chip.standby {
  opacity: 0.8;
}
.channel-name {
  font-weight: 600;
  color: var(--text-primary, #111827);
}
.channel-meta {
  font-size: 11.5px;
  color: var(--text-tertiary, #9ca3af);
  margin-left: auto;
}
.media-mcp-config {
  padding: 14px;
  border: 1px solid var(--c-profiles, rgba(22, 151, 122, 0.2));
  border-radius: 10px;
  background: var(--t-profiles, rgba(22, 151, 122, 0.05));
}
.media-mcp-config-heading {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
}
.media-mcp-form-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(180px, 1fr));
  gap: 12px;
}
.media-mcp-form-grid .runtime-field {
  width: auto;
}
.media-mcp-switch {
  justify-content: center;
}
@media (max-width: 900px) {
  .media-mcp-form-grid {
    grid-template-columns: repeat(2, minmax(180px, 1fr));
  }
}
@media (max-width: 560px) {
  .media-mcp-form-grid {
    grid-template-columns: 1fr;
  }
}

.mcp-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  flex-wrap: wrap;
  gap: 12px;
}
.mcp-filter-group {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
  flex: 1;
}
.pill-segmented {
  display: inline-flex;
  background: var(--bg-elevated, #f3f4f6);
  padding: 3px;
  border-radius: 8px;
  border: 1px solid var(--border-subtle, rgba(0, 0, 0, 0.08));
}
.pill-btn {
  border: none;
  background: transparent;
  padding: 4px 10px;
  font-size: 12px;
  font-weight: 500;
  border-radius: 6px;
  cursor: pointer;
  color: var(--text-secondary, #6b7280);
  transition: all 0.15s ease;
  white-space: nowrap;
}
.pill-btn.active {
  background: var(--bg-card, #ffffff);
  color: var(--c-profiles, #1f5947);
  font-weight: 600;
  box-shadow: 0 1px 2px rgba(0, 0, 0, 0.05);
}
.filter-dropdown-wrap {
  width: 130px;
}
.filter-search-wrap {
  flex: 0 1 200px;
  min-width: 140px;
}

/* MCP 卡片网格 */
.mcp-cards-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(300px, 1fr));
  gap: 14px;
}
.mcp-card {
  border: 1px solid var(--border-subtle, rgba(0, 0, 0, 0.08));
  border-radius: 12px;
  padding: 14px 16px;
  background: var(--bg-card, #ffffff);
  display: flex;
  flex-direction: column;
  gap: 10px;
  transition: all 0.2s cubic-bezier(0.4, 0, 0.2, 1);
}
.mcp-card:hover {
  transform: translateY(-2px);
  border-color: var(--c-profiles, rgba(22, 151, 122, 0.45));
  box-shadow: 0 6px 18px rgba(0, 0, 0, 0.06);
}
.mcp-card.is-disabled {
  opacity: 0.7;
}
.mcp-card-top {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 8px;
}
.mcp-tool-heading-wrap {
  display: flex;
  align-items: center;
  gap: 10px;
  min-width: 0;
  flex: 1;
}
.mcp-tool-icon-box {
  width: 36px;
  height: 36px;
  border-radius: 9px;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
  background: var(--bg-elevated, #f3f4f6);
  border: 1px solid var(--border-subtle, rgba(0, 0, 0, 0.08));
  color: var(--c-profiles, #16977a);
  transition: all 0.2s cubic-bezier(0.4, 0, 0.2, 1);
}
.mcp-card:hover .mcp-tool-icon-box {
  transform: scale(1.05);
}

/* 领域/分类色彩徽标容器 */
.tool-icon-file {
  color: #10b981;
  background: rgba(16, 185, 129, 0.08);
  border-color: rgba(16, 185, 129, 0.22);
}
.tool-icon-web {
  color: #3b82f6;
  background: rgba(59, 130, 246, 0.08);
  border-color: rgba(59, 130, 246, 0.22);
}
.tool-icon-bash {
  color: #f59e0b;
  background: rgba(245, 158, 11, 0.08);
  border-color: rgba(245, 158, 11, 0.22);
}
.tool-icon-plan,
.tool-icon-task {
  color: #8b5cf6;
  background: rgba(139, 92, 246, 0.08);
  border-color: rgba(139, 92, 246, 0.22);
}
.tool-icon-model {
  color: #6366f1;
  background: rgba(99, 102, 241, 0.08);
  border-color: rgba(99, 102, 241, 0.22);
}
.tool-icon-dataset {
  color: #06b6d4;
  background: rgba(6, 182, 212, 0.08);
  border-color: rgba(6, 182, 212, 0.22);
}
.tool-icon-kb {
  color: #14b8a6;
  background: rgba(20, 184, 166, 0.08);
  border-color: rgba(20, 184, 166, 0.22);
}
.tool-icon-report {
  color: #ec4899;
  background: rgba(236, 72, 153, 0.08);
  border-color: rgba(236, 72, 153, 0.22);
}
.tool-icon-dispatch {
  color: #0ea5e9;
  background: rgba(14, 165, 233, 0.08);
  border-color: rgba(14, 165, 233, 0.22);
}
.tool-icon-cases {
  color: #84cc16;
  background: rgba(132, 204, 22, 0.08);
  border-color: rgba(132, 204, 22, 0.22);
}
.tool-icon-image {
  color: #a855f7;
  background: rgba(168, 85, 247, 0.08);
  border-color: rgba(168, 85, 247, 0.22);
}
.tool-icon-audio {
  color: #eab308;
  background: rgba(234, 179, 8, 0.08);
  border-color: rgba(234, 179, 8, 0.22);
}
.tool-icon-other {
  color: var(--c-profiles, #16977a);
  background: var(--t-profiles, rgba(22, 151, 122, 0.08));
  border-color: rgba(22, 151, 122, 0.22);
}

/* 表格列工具图标 */
.mcp-table-tool-col {
  display: flex;
  align-items: center;
  gap: 8px;
}
.mcp-table-tool-icon {
  width: 28px;
  height: 28px;
  border-radius: 6px;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
  border: 1px solid var(--border-subtle, rgba(0, 0, 0, 0.08));
}
.mcp-table-tool-info {
  min-width: 0;
}

.mcp-tool-heading {
  min-width: 0;
  flex: 1;
}
.mcp-tool-title {
  font-size: 13.5px;
  font-weight: 600;
  color: var(--text-primary, #111827);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.domain-tag {
  font-size: 11px;
  color: var(--text-tertiary, #9ca3af);
}
.mcp-tool-desc {
  font-size: 12px;
  color: var(--text-secondary, #4b5563);
  line-height: 1.5;
  min-height: 36px;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}
.tool-schema-brief {
  background: var(--bg-elevated, #f9fafb);
  border: 1px solid var(--border-subtle, rgba(0, 0, 0, 0.05));
  border-radius: 6px;
  padding: 6px 10px;
  display: flex;
  flex-direction: column;
  gap: 3px;
  font-size: 11px;
}
.schema-brief-row {
  display: flex;
  align-items: center;
  gap: 6px;
  min-width: 0;
}
.brief-k {
  color: var(--text-tertiary, #9ca3af);
  font-weight: 600;
  flex-shrink: 0;
}
.brief-v {
  color: var(--text-primary, #111827);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.mcp-card-bottom {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  padding-top: 8px;
  border-top: 1px solid var(--border-subtle, rgba(0, 0, 0, 0.06));
  margin-top: auto;
}

/* 权限与风险等级微标 */
.perm-badge-read {
  color: var(--accent-success, #10b981);
}
.perm-badge-write {
  color: var(--accent-warning, #f59e0b);
}
.perm-badge-network {
  color: #3b82f6;
}
.perm-badge-code {
  color: #f59e0b;
}

/* 外部网关规格卡片 */
.external-gateway-panel {
  display: flex;
  flex-direction: column;
  gap: 12px;
}
.ext-hero-box {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 14px;
  padding: 16px;
  background: var(--t-profiles, rgba(22, 151, 122, 0.06));
  border: 1px solid var(--c-profiles, rgba(22, 151, 122, 0.2));
  border-radius: 10px;
  flex-wrap: wrap;
}
.ext-title {
  font-size: 14px;
  font-weight: 700;
  color: var(--text-primary, #111827);
  margin-bottom: 4px;
}
.ext-desc {
  font-size: 12px;
  color: var(--text-secondary, #4b5563);
  line-height: 1.5;
  max-width: 800px;
}
.ext-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
  gap: 12px;
}
.ext-card {
  padding: 12px 14px;
  background: var(--bg-elevated, #f9fafb);
  border: 1px solid var(--border-subtle, rgba(0, 0, 0, 0.08));
  border-radius: 8px;
}
.ext-card-title {
  font-size: 12.5px;
  font-weight: 600;
  color: var(--text-primary, #111827);
  margin-bottom: 6px;
}
.ext-card-content {
  font-size: 11.5px;
  color: var(--text-secondary, #6b7280);
  line-height: 1.6;
}

/* ═══════════════════════════════════════════════════════════════
   Tab 4：Agent 技能编排
   ═══════════════════════════════════════════════════════════════ */
.skills-center-container {
  display: flex;
  flex-direction: column;
  gap: 16px;
}
.skills-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  flex-wrap: wrap;
  gap: 12px;
}
.skills-filter-group {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
  flex: 1;
}
.skills-cards-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(320px, 1fr));
  gap: 14px;
}
.skill-card-v2 {
  border: 1px solid var(--border-subtle, rgba(0, 0, 0, 0.08));
  border-radius: 12px;
  padding: 16px;
  background: var(--bg-card, #ffffff);
  display: flex;
  flex-direction: column;
  gap: 10px;
  transition: all 0.2s cubic-bezier(0.4, 0, 0.2, 1);
}
.skill-card-v2:hover {
  transform: translateY(-2px);
  border-color: var(--c-profiles, rgba(22, 151, 122, 0.45));
  box-shadow: 0 6px 18px rgba(0, 0, 0, 0.06);
}
.skill-card-top {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 8px;
}
.skill-card-heading {
  min-width: 0;
  flex: 1;
}
.skill-card-name {
  font-size: 14px;
  font-weight: 700;
  color: var(--text-primary, #111827);
}
.skill-scenario-tag {
  font-size: 11px;
  color: var(--text-tertiary, #9ca3af);
  margin-top: 2px;
}
.skill-card-desc {
  font-size: 12px;
  color: var(--text-secondary, #4b5563);
  line-height: 1.5;
  min-height: 36px;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}
.skill-tuning-chips {
  display: flex;
  align-items: center;
  gap: 6px;
  flex-wrap: wrap;
}
.tuning-chip {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 2px 6px;
  background: var(--bg-elevated, #f3f4f6);
  border-radius: 4px;
  font-size: 10.5px;
}
.tuning-k {
  color: var(--text-tertiary, #9ca3af);
}
.tuning-v {
  color: var(--c-profiles, #1f5947);
  font-weight: 600;
}
.skill-cmds-row,
.skill-tools-row {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 11px;
}
.cmd-label,
.tools-label {
  color: var(--text-tertiary, #9ca3af);
  flex-shrink: 0;
}
.cmd-tag {
  padding: 1px 5px;
  border-radius: 4px;
  background: var(--t-profiles, rgba(22, 151, 122, 0.08));
  color: var(--c-profiles, #1f5947);
}
.tool-tag {
  padding: 1px 5px;
  border-radius: 4px;
  background: var(--bg-elevated, #f3f4f6);
  color: var(--text-secondary, #4b5563);
}
.skill-card-bottom {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  padding-top: 8px;
  border-top: 1px solid var(--border-subtle, rgba(0, 0, 0, 0.06));
  margin-top: auto;
}

/* ═══════════════════════════════════════════════════════════════
   Tab 5：运行时治理
   ═══════════════════════════════════════════════════════════════ */
.runtime-governance-panel {
  padding: 22px 26px;
  display: flex;
  flex-direction: column;
}
.panel-section-title {
  font-size: 14.5px;
  font-weight: 700;
  color: var(--text-primary, #111827);
  margin-bottom: 4px;
}
.runtime-section {
  display: flex;
  flex-direction: column;
}
.runtime-divider {
  height: 1px;
  background: var(--border-subtle, rgba(0, 0, 0, 0.06));
  margin: 20px 0;
}
.runtime-form-row {
  display: flex;
  align-items: flex-start;
  gap: 24px;
  flex-wrap: wrap;
}
.runtime-field {
  width: 240px;
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.runtime-field .field-label {
  font-size: 12.5px;
  font-weight: 600;
  color: var(--text-primary, #111827);
}
.runtime-field .field-hint {
  font-size: 11px;
  color: var(--text-tertiary, #9ca3af);
  margin-top: 2px;
}
.runtime-tier-select-wrap {
  max-width: 380px;
}
.runtime-footer {
  padding-top: 16px;
  border-top: 1px solid var(--border-subtle, rgba(0, 0, 0, 0.06));
}

/* ═══════════════════════════════════════════════════════════════
   通用辅助类
   ═══════════════════════════════════════════════════════════════ */
.status-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: var(--accent-success, #10b981);
  display: inline-block;
  flex-shrink: 0;
}
.status-dot.is-disabled {
  background: var(--text-tertiary, #9ca3af);
}
.empty-state-wrap {
  grid-column: 1 / -1;
  width: 100%;
}
.btn-xs {
  font-size: 11.5px;
  padding: 3px 8px;
  border-radius: 5px;
}
.link-btn.small {
  font-size: 12px;
}
</style>
