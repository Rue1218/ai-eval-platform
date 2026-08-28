<template>
  <div class="datasets-workbench">
    <!-- RAG 模式提示面板（大模型模式专注基准数据集） -->
    <div v-if="modeStore.mode === 'rag'" class="mode-context-panel panel">
      <div class="mode-icon-wrapper">
        <svg width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
          <path d="M4 19.5v-15A2.5 2.5 0 0 1 6.5 2H20v20H6.5a2.5 2.5 0 0 1-2.5-2.5Z" />
          <path d="M6 6h10" />
          <path d="M6 10h10" />
        </svg>
      </div>
      <h2>RAG 评测请使用知识库与黄金 QA</h2>
      <p>基准数据集主要服务于大模型评测与对比。当前模式下，请前往知识库工作台管理文档切块、检索与黄金 QA 资产。</p>
      <router-link to="/kb" class="btn btn-sign btn-sm">进入知识库工作台 →</router-link>
    </div>

    <div v-else class="ft-layout" :style="{ '--ft-w': treeWidth + 'px' }">
      <!-- ─── 左侧：资源目录树侧边栏 ─── -->
      <div class="ft-sidebar">
        <!-- 侧边栏头部 -->
        <div class="ft-header">
          <div class="row-between mb8">
            <div class="ft-title">
              <svg class="ft-title-icon" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                <path d="M20 20a2 2 0 0 0 2-2V8a2 2 0 0 0-2-2h-7.9a2 2 0 0 1-1.69-.9L9.6 3.9A2 2 0 0 0 7.93 3H4a2 2 0 0 0-2 2v13a2 2 0 0 0 2 2Z" />
              </svg>
              <span>数据集资源</span>
            </div>
            <div class="row" style="gap: 6px">
              <button class="btn btn-ai-soft btn-xs" title="通过 AI 场景或种子样本合成数据" aria-label="AI 智能合成新数据集" @click="openAiGenModal">
                <span class="sparkle">✨</span> 新建
              </button>
              <button class="btn btn-ghost btn-xs" title="上传 JSONL / CSV 数据集文件" aria-label="上传数据集文件" @click="openUploadModal(null)">
                <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                  <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" />
                  <polyline points="17 8 12 3 7 8" />
                  <line x1="12" y1="3" x2="12" y2="15" />
                </svg>
                上传
              </button>
            </div>
          </div>
          <!-- 搜索输入框 -->
          <div class="search-input-wrapper">
            <svg class="search-icon" width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
              <circle cx="11" cy="11" r="8" />
              <line x1="21" y1="21" x2="16.65" y2="16.65" />
            </svg>
            <input v-model="treeSearch" class="input tree-search-input" placeholder="搜索数据集 / 黄金 QA..." aria-label="搜索数据集或黄金QA" />
            <button v-if="treeSearch" class="clear-search-btn" aria-label="清空搜索内容" @click="treeSearch = ''">✕</button>
          </div>
        </div>

        <!-- 目录树内容区 -->
        <div class="ft-tree custom-scroll">
          <div v-for="folder in filteredFolders" :key="folder.id" class="ft-folder-group" :data-fid="folder.id">
            <!-- 文件夹节点 -->
            <div
              class="ft-node folder"
              :class="{ open: folder.open }"
              @click="folder.open = !folder.open"
              @contextmenu.prevent.stop="openCtxMenu($event, 'folder', folder.id)"
            >
              <span class="ft-chevron" :class="{ rotated: folder.open }">
                <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
                  <polyline points="9 18 15 12 9 6" />
                </svg>
              </span>
              <svg class="ft-folder-icon" width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                <path v-if="folder.open" d="m6 14 1.5-2.9A2 2 0 0 1 9.24 10H20a2 2 0 0 1 1.94 2.5l-1.54 6a2 2 0 0 1-1.95 1.5H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h3.9a2 2 0 0 1 1.69.9l.81 1.2a2 2 0 0 0 1.67.9H18a2 2 0 0 1 2 2v2" />
                <path v-else d="M20 20a2 2 0 0 0 2-2V8a2 2 0 0 0-2-2h-7.9a2 2 0 0 1-1.69-.9L9.6 3.9A2 2 0 0 0 7.93 3H4a2 2 0 0 0-2 2v13a2 2 0 0 0 2 2Z" />
              </svg>
              <span class="ft-folder-name">{{ folder.name }}</span>
              <span class="ft-badge">{{ folder.items.length }}</span>
            </div>

            <!-- 文件夹内部项目 -->
            <div v-if="folder.open" class="ft-folder-child">
              <div
                v-for="item in folder.items"
                :key="item.id"
                class="ft-node file"
                :class="{ active: activeDatasetId === item.id }"
                :title="`${item.name} · v${item.version}`"
                @click="requestSelectDataset(item.id)"
                @contextmenu.prevent.stop="openCtxMenu($event, 'file', item.id)"
              >
                <!-- 图标区分黄金 QA 与常规数据集 -->
                <span v-if="item.isGoldQa" class="ft-file-icon gold-qa" title="黄金 QA 资产">
                  <svg width="14" height="14" viewBox="0 0 24 24" fill="currentColor" stroke="none">
                    <polygon points="12 2 15.09 8.26 22 9.27 17 14.14 18.18 21.02 12 17.77 5.82 21.02 7 14.14 2 9.27 8.91 8.26 12 2" />
                  </svg>
                </span>
                <span v-else class="ft-file-icon dataset" title="基准数据集">
                  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                    <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
                    <polyline points="14 2 14 8 20 8" />
                    <line x1="16" y1="13" x2="8" y2="13" />
                    <line x1="16" y1="17" x2="8" y2="17" />
                    <polyline points="10 9 9 9 8 9" />
                  </svg>
                </span>
                <span class="ft-file-name">{{ item.name }}</span>
                <span class="version-tag">v{{ item.version }}</span>
                <span v-if="item.pending_complete_count > 0" class="ft-status-dot" :title="`${item.pending_complete_count} 行待补全`"></span>
              </div>
            </div>
          </div>

          <!-- 目录树空态提示 -->
          <div v-if="!filteredFolders.length" class="ft-empty-state">
            <svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" class="empty-icon">
              <circle cx="11" cy="11" r="8" />
              <line x1="21" y1="21" x2="16.65" y2="16.65" />
            </svg>
            <p>{{ treeSearch.trim() ? `未找到匹配「${treeSearch.trim()}」的数据集` : '暂无数据集，点击上方「+ 新建」或「上传」开始' }}</p>
          </div>
        </div>

        <!-- 目录树调宽手柄 -->
        <div
          class="ft-resizer"
          :class="{ on: treeResizing }"
          title="拖拽调整侧边栏宽度 · 双击复位为 290px"
          @mousedown="startTreeResize"
          @dblclick="resetTreeWidth"
        >
          <div class="resizer-handle-line"></div>
        </div>
      </div>

      <!-- ─── 右侧：数据表格工作台 ─── -->
      <div v-if="currentItem" class="workspace-main">
        <!-- 1. 顶部工具栏 -->
        <div class="ws-toolbar">
          <div class="ws-title-group">
            <div class="ws-title-row">
              <span class="ws-dataset-title">{{ currentItem.name }}</span>
              <span class="version-pill">v{{ currentItem.version }}</span>
              <span
                class="kind-chip"
                :class="isGoldQaActive ? 'chip-gold-qa' : 'chip-dataset'"
              >
                {{ isGoldQaActive ? '黄金 QA' : '基准数据集' }}
              </span>
              <span v-if="!isGoldQaActive && currentDataset && currentDataset.pending_complete_count > 0" class="badge badge-awaiting_case_confirm">
                {{ currentDataset.pending_complete_count }} 行待补全
              </span>
            </div>
            <!-- 面包屑路径提示 -->
            <div class="ws-breadcrumb">
              <span>{{ isGoldQaActive ? '知识库资产' : '数据集资源' }}</span>
              <span class="sep">/</span>
              <span class="cur">{{ currentItem.name }}</span>
            </div>
          </div>

          <!-- 右侧操作按钮组 -->
          <div v-if="isGoldQaActive" class="ws-action-group">
            <button class="btn btn-sign btn-sm" @click="openRagDrawer">
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                <polygon points="5 3 19 12 5 21 5 3" />
              </svg>
              发起 RAG 评测
            </button>
          </div>

          <div v-else class="ws-action-group">
            <!-- 常规表格编辑与扩展 -->
            <div class="action-btn-cluster">
              <button class="btn btn-secondary btn-sm" aria-label="新增表格行" @click="addRow">
                <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="12" y1="5" x2="12" y2="19" /><line x1="5" y1="12" x2="19" y2="12" /></svg>
                新增行
              </button>
              <button class="btn btn-secondary btn-sm" aria-label="新增自定义扩展列" @click="openAddColModal">
                <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="12" y1="5" x2="12" y2="19" /><line x1="5" y1="12" x2="19" y2="12" /></svg>
                新增列
              </button>
            </div>

            <!-- AI 增强功能区 -->
            <div class="action-btn-cluster ai-cluster">
              <button class="btn btn-ai btn-sm" aria-label="AI 智能合成数据集向导" @click="openAiGenModal">
                <span class="sparkle">✨</span> AI 智能合成
              </button>
              <button class="btn btn-ai-soft btn-sm" :disabled="pendingCount === 0" title="为缺失问句或答案的行智能推导并补全" aria-label="AI 补全缺失行" @click="openAiFillModal">
                AI 补全缺失行
              </button>
            </div>

            <!-- 导出与保存 -->
            <div class="action-btn-cluster">
              <button class="btn btn-secondary btn-sm" title="导出当前表格为 JSONL 格式文件" aria-label="导出 JSONL 文件" @click="exportJsonl">
                <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" /><polyline points="7 10 12 15 17 10" /><line x1="12" y1="15" x2="12" y2="3" /></svg>
                导出 JSONL
              </button>
              <button
                class="btn btn-primary btn-sm save-btn"
                :class="{ dirty: hasUnsavedChanges, saved: justSaved }"
                :disabled="!hasUnsavedChanges || savingRows"
                title="快捷键 Ctrl/⌘ + S"
                aria-label="保存当前数据集修改"
                @click="persistRows"
              >
                <span v-if="hasUnsavedChanges" class="dirty-indicator"></span>
                <span v-if="justSaved" class="saved-check-icon">✓</span>
                {{ savingRows ? '保存中…' : justSaved ? '已保存' : '保存修改' }}
                <kbd class="shortcut-pill">⌘S</kbd>
              </button>
            </div>

            <!-- 核心主行动：发起评测 -->
            <button class="btn btn-sign btn-sm launch-btn" aria-label="发起基准评测任务" @click="openLaunchDrawer">
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round">
                <polygon points="5 3 19 12 5 21 5 3" />
              </svg>
              发起基准评测
            </button>
          </div>
        </div>

        <!-- 2. 数据质量与指标概览栏 (Quality & Metrics Glance Bar) -->
        <div class="quality-glance-bar">
          <div class="glance-metrics-left">
            <span class="glance-label">数据概览:</span>
            <span class="glance-pill">
              共 <b class="num mono">{{ isGoldQaActive ? (activeGoldQa?.row_count || 0) : sampleRows.length }}</b> 行
            </span>

            <template v-if="!isGoldQaActive">
              <span class="glance-pill success" :class="{ active: filterPendingOnly === false }" @click="filterPendingOnly = false">
                <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3"><polyline points="20 6 9 17 4 12" /></svg>
                达标 <b class="num mono">{{ sampleRows.length - pendingCount }}</b> 行
              </span>
              <span
                v-if="pendingCount > 0"
                class="glance-pill warning clickable"
                :class="{ active: filterPendingOnly === true }"
                title="点击切换仅看待补全行"
                @click="filterPendingOnly = !filterPendingOnly"
              >
                <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3"><circle cx="12" cy="12" r="10" /><line x1="12" y1="8" x2="12" y2="12" /><line x1="12" y1="16" x2="12.01" y2="16" /></svg>
                待补全 <b class="num mono">{{ pendingCount }}</b> 行
                <span class="filter-tag">{{ filterPendingOnly ? '✓ 已过滤' : '点击筛选' }}</span>
              </span>
              <span v-else class="glance-pill achievement-pill">
                <span class="sparkle">✨</span> 校验 100% 达标 · 就绪可评测
              </span>

              <span v-if="customCols.length" class="glance-pill">
                自定义扩展列: <b class="num mono">{{ customCols.length }}</b>
              </span>
            </template>
          </div>

          <div class="grow"></div>

          <!-- 主评测指标选择器 -->
          <div v-if="!isGoldQaActive && currentDataset" class="metric-selector-wrapper">
            <span class="metric-label">主评分指标:</span>
            <select v-model="currentDataset.metric" class="select metric-select" aria-label="选择主评分指标" @change="saveMetric">
              <option value="contain">Contain (包含匹配)</option>
              <option value="exact">Exact (完全一致)</option>
              <option value="regex">Regex (正则表达式)</option>
              <option value="rouge_l">ROUGE-L (最长公共子序列)</option>
              <option value="bleu">BLEU (自然语言平滑)</option>
            </select>
          </div>
        </div>

        <!-- 3. 数据表格网格 (Impeccable Grid Table) -->
        <div class="ws-grid-container custom-scroll">
          <table class="ds-table impeccable-grid">
            <thead>
              <tr>
                <th class="th-chk" style="width: 44px">
                  <input type="checkbox" :checked="allRowsChecked" class="custom-checkbox" aria-label="全选所有行" @change="toggleAllRows" />
                </th>
                <th style="width: 68px"># 行号</th>
                <th style="min-width: 240px">
                  测试问句 (Question) <span class="req-star">*</span>
                </th>
                <th style="min-width: 280px">
                  标准参考答案 (Reference) <span class="req-star">*</span>
                </th>
                <th style="min-width: 160px">
                  {{ isGoldQaActive ? '预期文档 expected_doc_ids' : '上下文注入 / Prompt Context' }}
                </th>
                <template v-if="!isGoldQaActive">
                  <th style="min-width: 110px">标签</th>
                  <th style="min-width: 90px">难度</th>
                </template>
                <!-- 自定义扩展列表头 -->
                <th v-for="col in customCols" :key="col.key" class="custom-col-th" style="min-width: 120px">
                  <div class="custom-th-content">
                    <span class="custom-th-name">{{ col.name }}</span>
                    <span class="custom-th-key">({{ col.key }})</span>
                    <button class="custom-th-del" title="删除该扩展列" :aria-label="`删除扩展列 ${col.name}`" @click.stop="removeCustomCol(col.key)">✕</button>
                  </div>
                </th>
                <th style="width: 96px">校验状态</th>
                <th style="width: 110px; text-align: right">操作</th>
              </tr>
            </thead>

            <tbody>
              <!-- 黄金 QA 提示说明 -->
              <tr v-if="isGoldQaActive">
                <td :colspan="(isGoldQaActive ? 7 : 9) + customCols.length" class="gold-qa-empty-cell">
                  <div class="gold-qa-notice">
                    <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                      <polygon points="12 2 15.09 8.26 22 9.27 17 14.14 18.18 21.02 12 17.77 5.82 21.02 7 14.14 2 9.27 8.91 8.26 12 2" />
                    </svg>
                    <span>黄金 QA「{{ currentItem?.name }}」共 {{ activeGoldQa?.row_count || 0 }} 行，行级查看与深度编辑将在 M3 知识库全面接入。</span>
                  </div>
                </td>
              </tr>

              <!-- 数据集行记录 -->
              <tr
                v-for="(r, idx) in displayedRows"
                v-else
                :key="r.row_no"
                class="grid-row"
                :class="{ 'row-checked': r.checked, 'row-incomplete': !r.q.trim() || !r.r.trim() }"
                @contextmenu.prevent="openCtxMenu($event, 'row', '', getOriginalRowIndex(r))"
                @dblclick="openRowEditModal(getOriginalRowIndex(r))"
              >
                <!-- 勾选列 -->
                <td class="td-chk">
                  <input v-model="r.checked" type="checkbox" class="custom-checkbox" :aria-label="`勾选第 ${r.row_no} 行`" />
                </td>

                <!-- 行号 -->
                <td class="mono small td-row-no">{{ r.row_no }}</td>

                <!-- 问题单元格 (就地编辑) -->
                <td class="cell-edit" :class="{ 'cell-invalid': !r.q.trim() }" @click="editCell(r, 'q')">
                  <input
                    v-if="editingCell?.row === r && editingCell?.field === 'q'"
                    v-model="r.q"
                    class="cell-input active"
                    placeholder="输入测试问题..."
                    :aria-label="`编辑第 ${r.row_no} 行测试问题`"
                    autofocus
                    @blur="finishEditing"
                    @keyup.enter="finishEditing"
                    @keyup.esc="cancelEditing"
                  />
                  <div v-else class="cell-text" :class="{ placeholder: !r.q.trim() }">
                    {{ r.q || '（空问句 · 点击补全）' }}
                  </div>
                </td>

                <!-- 参考答案单元格 (就地编辑) -->
                <td class="cell-edit" :class="{ 'cell-invalid': !r.r.trim() }" @click="editCell(r, 'r')">
                  <input
                    v-if="editingCell?.row === r && editingCell?.field === 'r'"
                    v-model="r.r"
                    class="cell-input active"
                    placeholder="输入标准答案..."
                    :aria-label="`编辑第 ${r.row_no} 行标准答案`"
                    autofocus
                    @blur="finishEditing"
                    @keyup.enter="finishEditing"
                    @keyup.esc="cancelEditing"
                  />
                  <div v-else class="cell-text" :class="{ placeholder: !r.r.trim() }">
                    {{ r.r || '（空答案 · 点击补全）' }}
                  </div>
                </td>

                <!-- 上下文注入单元格 (就地编辑) -->
                <td class="cell-edit" @click="editCell(r, 'c')">
                  <input
                    v-if="editingCell?.row === r && editingCell?.field === 'c'"
                    v-model="r.c"
                    class="cell-input active"
                    placeholder="上下文 Context..."
                    :aria-label="`编辑第 ${r.row_no} 行上下文`"
                    autofocus
                    @blur="finishEditing"
                    @keyup.enter="finishEditing"
                    @keyup.esc="cancelEditing"
                  />
                  <div v-else class="cell-text mono-text" :class="{ empty: !r.c }">
                    {{ r.c || '—' }}
                  </div>
                </td>

                <!-- 标签单元格 (就地编辑) -->
                <td class="cell-edit" @click="editCell(r, 'tags')">
                  <input
                    v-if="editingCell?.row === r && editingCell?.field === 'tags'"
                    v-model="r.tags"
                    class="cell-input active"
                    placeholder="标签，逗号分隔..."
                    :aria-label="`编辑第 ${r.row_no} 行标签`"
                    autofocus
                    @blur="finishEditing"
                    @keyup.enter="finishEditing"
                    @keyup.esc="cancelEditing"
                  />
                  <div v-else class="cell-text">
                    <span v-if="r.tags" class="tag-chip">{{ r.tags }}</span>
                    <span v-else class="empty-placeholder">常规</span>
                  </div>
                </td>

                <!-- 难度选择器单元格 -->
                <td class="cell-edit" @click="editCell(r, 'difficulty')">
                  <select
                    v-if="editingCell?.row === r && editingCell?.field === 'difficulty'"
                    v-model="r.difficulty"
                    class="select cell-select"
                    :aria-label="`选择第 ${r.row_no} 行难度`"
                    autofocus
                    @blur="finishEditing"
                    @change="finishEditing"
                    @keyup.esc="cancelEditing"
                  >
                    <option>简单</option>
                    <option>中等</option>
                    <option>高</option>
                  </select>
                  <div v-else class="cell-text">
                    <span class="difficulty-chip" :class="`diff-${r.difficulty}`">
                      {{ r.difficulty || '简单' }}
                    </span>
                  </div>
                </td>

                <!-- 自定义扩展列单元格 (就地编辑) -->
                <td v-for="col in customCols" :key="col.key" class="cell-edit" @click="editCell(r, col.key)">
                  <input
                    v-if="editingCell?.row === r && editingCell?.field === col.key"
                    v-model="r.extras[col.key]"
                    class="cell-input active"
                    :placeholder="`输入 ${col.name}...`"
                    :aria-label="`编辑第 ${r.row_no} 行 ${col.name}`"
                    autofocus
                    @blur="finishEditing"
                    @keyup.enter="finishEditing"
                    @keyup.esc="cancelEditing"
                  />
                  <div v-else class="cell-text" :class="{ empty: !r.extras[col.key] }">
                    {{ r.extras[col.key] || '—' }}
                  </div>
                </td>

                <!-- 校验状态指示 -->
                <td>
                  <span v-if="!r.q.trim() || !r.r.trim()" class="badge badge-awaiting_case_confirm" title="缺少测试句或参考答案">
                    <span class="bdot"></span> 待补全
                  </span>
                  <span v-else class="badge badge-succeeded" title="核心字段完整">
                    <span class="bdot"></span> 达标
                  </span>
                </td>

                <!-- 行内快捷操作 -->
                <td class="td-actions">
                  <div class="row-actions-cluster">
                    <button class="action-btn" title="详细弹窗编辑" :aria-label="`详细编辑第 ${r.row_no} 行`" @click.stop="openRowEditModal(getOriginalRowIndex(r))">
                      <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7" /><path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z" /></svg>
                    </button>
                    <button class="action-btn danger" title="删除本行" :aria-label="`删除第 ${r.row_no} 行`" @click.stop="deleteRow(getOriginalRowIndex(r))">
                      <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="3 6 5 6 21 6" /><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2" /></svg>
                    </button>
                  </div>
                </td>
              </tr>

              <!-- 空行/过滤无结果提示 -->
              <tr v-if="!displayedRows.length">
                <td :colspan="(isGoldQaActive ? 7 : 9) + customCols.length" class="empty-table-cell">
                  <div class="empty-table-notice">
                    <span v-if="filterPendingOnly">当前无待补全行，全部样本格式均已达标。</span>
                    <span v-else>当前数据集暂无样本行，点击上方「新增行」或「AI 智能合成」开始填充数据。</span>
                  </div>
                </td>
              </tr>
            </tbody>
          </table>
        </div>

        <!-- 4. 浮动式批量操作坞 (Floating Batch Action Dock) -->
        <transition name="dock-slide">
          <div v-if="selectedCount > 0" class="floating-batch-dock">
            <div class="dock-content">
              <span class="dock-count-badge">已勾选 <b class="num mono">{{ selectedCount }}</b> 行</span>
              <div class="dock-divider"></div>
              <button class="btn btn-ghost btn-sm" aria-label="导出选中行 JSONL" @click="exportSelectedRows">
                <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" /><polyline points="7 10 12 15 17 10" /><line x1="12" y1="15" x2="12" y2="3" /></svg>
                导出选中 JSONL
              </button>
              <button class="btn btn-danger-soft btn-sm" aria-label="批量删除勾选行" @click="batchDeleteRows">
                <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="3 6 5 6 21 6" /><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2" /></svg>
                批量删除 ({{ selectedCount }})
              </button>
              <div class="dock-divider"></div>
              <button class="dock-close-btn" title="取消全部勾选" aria-label="取消勾选所有行" @click="uncheckAllRows">✕</button>
            </div>
          </div>
        </transition>
      </div>

      <!-- ─── 空态页面引导 ─── -->
      <div v-else class="workspace-main empty-workbench">
        <div class="empty-workbench-container">
          <div class="empty-workbench-icon">
            <svg width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">
              <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
              <polyline points="14 2 14 8 20 8" />
              <line x1="16" y1="13" x2="8" y2="13" />
              <line x1="16" y1="17" x2="8" y2="17" />
              <polyline points="10 9 9 9 8 9" />
            </svg>
          </div>
          <h3>尚未选择或创建数据集</h3>
          <p class="empty-sub">你可以通过上传现有的 JSONL / CSV 评测集，或者由 AI 深度推理一键合成评测数据。</p>
          <div class="empty-actions-row">
            <button class="btn btn-secondary" @click="openUploadModal(null)">
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" /><polyline points="17 8 12 3 7 8" /><line x1="12" y1="3" x2="12" y2="15" /></svg>
              上传已有数据集
            </button>
            <button class="btn btn-ai" @click="createEmptyDataset(() => openAiGenModal())">
              <span class="sparkle">✨</span> AI 智能合成新数据
            </button>
            <button class="btn btn-sign" @click="createEmptyDataset()">
              + 新建空数据集
            </button>
          </div>
        </div>
      </div>
    </div>

    <!-- ─── 弹窗与抽屉组件 ─── -->
    <UploadDatasetModal
      v-model:show="showUploadModal"
      :dataset="datasetForUpload"
      @success="loadDatasets"
    />

    <BenchmarkLaunchDrawer
      v-model:show="showLaunchDrawer"
      :default-dataset-id="currentDataset?.id"
      @success="handleLaunchSuccess"
    />

    <!-- 右键上下文菜单 -->
    <n-dropdown
      trigger="manual"
      placement="bottom-start"
      :show="ctxMenu.show"
      :x="ctxMenu.x"
      :y="ctxMenu.y"
      :options="ctxMenuOptions"
      @select="handleCtxSelect"
      @clickoutside="closeCtxMenu"
    />

    <!-- 行结构化编辑弹窗 -->
    <n-modal v-model:show="rowEdit.show" preset="card" :title="`详细编辑样本行 #${rowEdit.rowNo}`" style="width: 660px; max-width: calc(100vw - 24px)">
      <div class="field">
        <label class="field-label">问题 / 提示词 (Question / Prompt) <span class="req">*</span></label>
        <n-input v-model:value="rowEdit.q" type="textarea" :autosize="{ minRows: 3, maxRows: 6 }" placeholder="请输入测试问句" />
      </div>
      <div class="field">
        <label class="field-label">标准答案 / 预期输出 (Reference) <span class="req">*</span></label>
        <n-input v-model:value="rowEdit.r" type="textarea" :autosize="{ minRows: 3, maxRows: 6 }" placeholder="请输入标准答案" />
      </div>
      <div class="field">
        <label class="field-label">上下文注入 / Prompt Context (支持 Markdown / JSON 结构体)</label>
        <n-input v-model:value="rowEdit.c" class="mono" type="textarea" :autosize="{ minRows: 3, maxRows: 8 }" placeholder="可粘贴结构化上下文或参考文档段落..." />
      </div>
      <!-- 自定义扩展字段区 -->
      <template v-if="customCols.length">
        <div class="rail-label" style="margin: 12px 0 8px">自定义扩展字段</div>
        <div class="form-row">
          <div v-for="col in customCols" :key="col.key" class="field">
            <label class="field-label">{{ col.name }} ({{ col.key }})</label>
            <n-input v-model:value="rowEdit.extras[col.key]" :placeholder="col.type === 'json' ? 'JSON 结构体' : col.type === 'number' ? '数值' : '文本'" />
          </div>
        </div>
      </template>
      <template #footer>
        <div style="display: flex; justify-content: flex-end; gap: 8px">
          <n-button @click="rowEdit.show = false">取消</n-button>
          <n-button type="primary" @click="saveRowEdit">保存修改</n-button>
        </div>
      </template>
    </n-modal>

    <!-- 新增自定义扩展列弹窗 -->
    <n-modal v-model:show="addCol.show" preset="card" title="新增自定义数据列 (Custom Column)" style="width: 480px; max-width: calc(100vw - 24px)">
      <div class="field">
        <label class="field-label">字段 Key (英文字母 / 下划线) <span class="req">*</span></label>
        <n-input v-model:value="addCol.key" class="mono" placeholder="如 category, meta_tags, prompt_type" />
      </div>
      <div class="field">
        <label class="field-label">列显示名称 <span class="req">*</span></label>
        <n-input v-model:value="addCol.name" placeholder="如 业务分类, 标签, 提示词类型" />
      </div>
      <div class="field">
        <label class="field-label">字段类型</label>
        <n-select
          v-model:value="addCol.type"
          :options="[
            { label: '纯文本 (Text)', value: 'text' },
            { label: 'JSON 结构体', value: 'json' },
            { label: '数值 (Number)', value: 'number' },
          ]"
        />
      </div>
      <template #footer>
        <div style="display: flex; justify-content: flex-end; gap: 8px">
          <n-button @click="addCol.show = false">取消</n-button>
          <n-button type="primary" @click="confirmAddCol">确认添加</n-button>
        </div>
      </template>
    </n-modal>

    <!-- AI 智能合成新数据两步向导 -->
    <n-modal v-model:show="aiGen.show" preset="card" title="✨ AI 智能生成评测数据集" style="width: 780px; max-width: calc(100vw - 24px)" :mask-closable="false">
      <!-- 步骤指示器 -->
      <div class="wizard-steps-header">
        <div class="wizard-step-item" :class="{ active: aiGen.step === 1, done: aiGen.step === 2 }">
          <span class="step-num">1</span>
          <span class="step-text">生成模式与参数配置</span>
        </div>
        <div class="step-line" :class="{ active: aiGen.step === 2 }"></div>
        <div class="wizard-step-item" :class="{ active: aiGen.step === 2 }">
          <span class="step-num">2</span>
          <span class="step-text">候选样本预览与导入</span>
        </div>
      </div>

      <!-- Step 1: 合成模式与高级控制参数 -->
      <div v-show="aiGen.step === 1" class="wizard-step-body">
        <div class="mode-chips-row">
          <button class="chip" :class="{ on: aiGen.mode === 'scene' }" @click="aiGen.mode = 'scene'">🌟 场景定向合成</button>
          <button class="chip" :class="{ on: aiGen.mode === 'seed' }" @click="aiGen.mode = 'seed'">🌱 种子样本扩写</button>
          <button class="chip" :class="{ on: aiGen.mode === 'doc' }" @click="aiGen.mode = 'doc'">📄 需求文档/OpenAPI 提取</button>
        </div>

        <!-- 场景模式 -->
        <div v-show="aiGen.mode === 'scene'">
          <div class="field">
            <label class="field-label">预设业务场景模板</label>
            <n-select v-model:value="aiGen.preset" :options="presetOptions" @update:value="onPresetChange" />
          </div>
          <div class="field">
            <label class="field-label">场景与评估目标描述 (Prompt Instruction) <span class="req">*</span></label>
            <n-input v-model:value="aiGen.instruction" type="textarea" :autosize="{ minRows: 3, maxRows: 5 }" placeholder="请详述被测场景、边界陷阱或关注的能力维度..." />
          </div>
        </div>

        <!-- 种子模式 -->
        <div v-show="aiGen.mode === 'seed'">
          <div class="field">
            <label class="field-label">选择种子样本（基于此样本扩写同义、长尾或边界题）</label>
            <n-select v-model:value="aiGen.seedSample" :options="seedOptions" placeholder="请选择一条已有样本作为种子" />
          </div>
          <div class="field">
            <label class="field-label">扩写维度</label>
            <n-checkbox-group v-model:value="aiGen.dims">
              <div class="row wrap" style="gap: 14px">
                <n-checkbox value="synonym">同义口语化改写</n-checkbox>
                <n-checkbox value="constraint">增加前置约束条件</n-checkbox>
                <n-checkbox value="boundary">衍生边界异常提问</n-checkbox>
              </div>
            </n-checkbox-group>
          </div>
        </div>

        <!-- 文档提取模式 -->
        <div v-show="aiGen.mode === 'doc'">
          <div class="field">
            <label class="field-label">粘贴 PRD / OpenAPI 接口定义 / Markdown 需求文本</label>
            <n-input v-model:value="aiGen.docText" class="mono" type="textarea" :autosize="{ minRows: 4, maxRows: 8 }" placeholder="粘贴接口文档或需求描述，AI 将自动抽取问答对及对应上下文..." />
          </div>
        </div>

        <div class="rail-label" style="margin: 8px 0 10px">高级控制参数</div>
        <div class="form-row-3">
          <div class="field">
            <label class="field-label">生成规模 (<b class="num mono">{{ aiGen.rowCount }}</b> 行)</label>
            <n-slider v-model:value="aiGen.rowCount" :min="3" :max="25" :step="1" />
          </div>
          <div class="field">
            <label class="field-label">生成推理模型</label>
            <n-select
              v-model:value="aiGen.model"
              :options="[
                { label: 'gpt-4.1 (高准确度)', value: 'gpt-4.1' },
                { label: 'claude-sonnet-4.5 (强逻辑推理)', value: 'claude-sonnet-4.5' },
                { label: 'o4 (复杂边界深度推理)', value: 'o4' },
              ]"
            />
          </div>
          <div class="field">
            <label class="field-label">发散度 Temperature</label>
            <n-select
              v-model:value="aiGen.temperature"
              :options="[
                { label: '0.2 (严谨收敛)', value: 0.2 },
                { label: '0.5 (标准平衡)', value: 0.5 },
                { label: '0.8 (发散多样)', value: 0.8 },
              ]"
            />
          </div>
        </div>

        <div class="form-row">
          <div class="field">
            <label class="field-label">难易度分布预设</label>
            <div class="row" style="gap: 8px; font-size: 12px">
              <span class="tag-soft">简单 40%</span>
              <span class="tag-soft">中等 40%</span>
              <span class="tag-soft">高难/陷阱 20%</span>
            </div>
          </div>
          <div class="field">
            <label class="field-label">自动生成目标字段</label>
            <div class="row wrap" style="gap: 12px; font-size: 12px">
              <n-checkbox v-model:checked="aiGen.genRef">标准答案 Reference</n-checkbox>
              <n-checkbox v-model:checked="aiGen.genCtx">注入上下文 Context</n-checkbox>
              <n-checkbox v-model:checked="aiGen.genTags">业务标签 Tags</n-checkbox>
            </div>
          </div>
        </div>
      </div>

      <!-- Step 2: 候选结果表格预览 -->
      <div v-show="aiGen.step === 2" class="wizard-step-body">
        <div class="row-between mb8">
          <span style="font-weight: 600; font-size: 13px">AI 生成候选项（已生成 <b class="num mono">{{ aiGen.candidates.length }}</b> 条，可点击单元格直接微调）</span>
          <button class="link-btn" @click="toggleAllCandidates">全选 / 全不选</button>
        </div>
        <div class="preview-table-wrapper custom-scroll">
          <table class="ds-table">
            <thead>
              <tr>
                <th style="width: 36px"><input type="checkbox" :checked="aiAllSelected" @change="toggleAllCandidates" /></th>
                <th style="min-width: 220px">测试问句 Question</th>
                <th style="min-width: 240px">参考答案 Reference</th>
                <th style="width: 100px">难度 / 标签</th>
                <th style="width: 60px">操作</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="(cand, ci) in aiGen.candidates" :key="ci">
                <td><input v-model="cand.selected" type="checkbox" /></td>
                <td><input v-model="cand.q" class="cell-input" /></td>
                <td><input v-model="cand.r" class="cell-input" /></td>
                <td><span class="tag-soft" style="font-size: 10px">{{ cand.difficulty }} · {{ cand.tags || '未标注' }}</span></td>
                <td><button class="link-btn danger" style="font-size: 11px" @click="aiGen.candidates.splice(ci, 1)">剔除</button></td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>

      <template #footer>
        <div class="row-between" style="width: 100%">
          <n-button v-if="aiGen.step === 2" @click="aiGen.step = 1">← 返回调整参数</n-button>
          <span v-else></span>
          <div class="row" style="gap: 8px">
            <n-button @click="aiGen.show = false">取消</n-button>
            <n-button v-if="aiGen.step === 1" type="primary" :loading="aiGen.generating" @click="runAiGenerate">
              {{ aiGen.generating ? 'AI 深度推理生成中…' : '立即生成候选样本 →' }}
            </n-button>
            <n-button v-else type="primary" :disabled="aiSelectedCount === 0" @click="commitAiCandidates">
              采纳并导入数据集 ({{ aiSelectedCount }} 条)
            </n-button>
          </div>
        </div>
      </template>
    </n-modal>

    <!-- AI 补全确认弹窗 -->
    <n-modal v-model:show="aiFill.show" preset="card" :title="`✨ AI 智能补全缺失字段（共 ${pendingCount} 行待补全）`" style="width: 560px; max-width: calc(100vw - 24px)">
      <p class="small" style="margin: 0 0 12px; color: var(--text-secondary)">
        系统检测到当前表格存在缺少问句或标准答案的样本行。AI 将结合已有业务上下文及同组高质特征自动推导补全。
      </p>
      <div class="field">
        <label class="field-label">业务提示词引导 (Prompt Instruction)</label>
        <n-input v-model:value="aiFill.instruction" type="textarea" :autosize="{ minRows: 2, maxRows: 4 }" />
      </div>
      <div class="form-row">
        <div class="field">
          <label class="field-label">补全范围</label>
          <div class="row" style="gap: 14px; font-size: 12px; margin-top: 4px">
            <n-checkbox v-model:checked="aiFill.scopeQ">填补缺失问句</n-checkbox>
            <n-checkbox v-model:checked="aiFill.scopeR">填补缺失标准答案</n-checkbox>
          </div>
        </div>
        <div class="field">
          <label class="field-label">少样本学习 (Few-Shot)</label>
          <span class="small tertiary">自动关联数据集同组高质样本特征进行少样本学习</span>
        </div>
      </div>
      <template #footer>
        <div style="display: flex; justify-content: flex-end; gap: 8px">
          <n-button @click="aiFill.show = false">取消</n-button>
          <n-button type="primary" :loading="aiFill.filling" @click="confirmAiFill">
            开始 AI 补全 ({{ pendingCount }} 行)
          </n-button>
        </div>
      </template>
    </n-modal>

    <!-- 通用命名弹窗 -->
    <n-modal v-model:show="nameDialog.show" preset="card" :title="nameDialog.title" style="width: 440px; max-width: calc(100vw - 24px)">
      <div class="field">
        <label class="field-label">{{ nameDialog.label }} <span class="req">*</span></label>
        <n-input v-model:value="nameDialog.value" placeholder="请输入名称" autofocus @keyup.enter="confirmNameDialog" />
      </div>
      <template #footer>
        <div style="display: flex; justify-content: flex-end; gap: 8px">
          <n-button @click="nameDialog.show = false">取消</n-button>
          <n-button type="primary" :loading="nameDialogBusy" @click="confirmNameDialog">确认</n-button>
        </div>
      </template>
    </n-modal>

    <!-- 黄金 QA 发起 RAG 评测抽屉 -->
    <n-drawer v-model:show="ragDrawer.show" :width="ragDrawerWidth">
      <n-drawer-content title="发起 RAG 评测任务" closable>
        <div class="field">
          <label class="field-label">kind</label>
          <div><span class="tag-soft" style="color: var(--c-kb); border-color: var(--t-kb)">RAG 检索质量评测</span></div>
        </div>
        <div class="form-row">
          <div class="field">
            <label class="field-label">kb_id</label>
            <n-input :value="ragDrawer.kbId" readonly />
          </div>
          <div class="field">
            <label class="field-label">gold_qa_id</label>
            <n-input :value="ragDrawer.goldQaLabel" readonly />
          </div>
        </div>
        <div class="field">
          <label class="field-label">rag_mode（1–4 个）</label>
          <div class="chip-group">
            <button
              v-for="m in RAG_MODES"
              :key="m"
              class="chip"
              :class="{ on: ragDrawer.modes.includes(m) }"
              @click="toggleRagMode(m)"
            >{{ m }}</button>
          </div>
        </div>
        <div class="rail-label" style="margin: 4px 0 10px">高级运行参数</div>
        <div class="form-row-3">
          <div class="field">
            <label class="field-label">召回数 k</label>
            <n-input-number v-model:value="ragDrawer.k" :min="1" :max="50" />
          </div>
          <div class="field">
            <label class="field-label">并发 concurrency</label>
            <n-input-number v-model:value="ragDrawer.concurrency" :min="1" :max="16" />
          </div>
          <div class="field">
            <label class="field-label">超时 timeout_s</label>
            <n-input-number v-model:value="ragDrawer.timeoutS" :min="5" :max="300" />
          </div>
        </div>
        <div class="field">
          <label class="field-label">先评后压（评测成功后自动派生共享压测）</label>
          <n-switch v-model:value="ragDrawer.withStress" />
        </div>
        <div v-if="ragDrawer.withStress" class="panel" style="margin-top: 12px; background: var(--bg-elevated)">
          <div class="panel-title" style="color: var(--c-stress)">压测参数</div>
          <div class="form-row-3" style="margin-top: 10px">
            <div class="field">
              <label class="field-label">环境 env</label>
              <n-select
                v-model:value="ragDrawer.stressEnv"
                :options="[
                  { label: 'dev', value: 'dev' },
                  { label: 'test', value: 'test' },
                  { label: 'staging', value: 'staging' },
                  { label: 'prod', value: 'prod' },
                ]"
              />
            </div>
            <div class="field">
              <label class="field-label">目标 QPS</label>
              <n-input-number v-model:value="ragDrawer.qps" :min="1" :max="1000" />
            </div>
            <div class="field">
              <label class="field-label">时长 duration_s</label>
              <n-input-number v-model:value="ragDrawer.durationS" :min="10" :max="3600" />
            </div>
          </div>
          <div class="field">
            <label class="field-label">SLA p99 (ms)</label>
            <n-input-number v-model:value="ragDrawer.slaP99Ms" :min="10" :max="60000" placeholder="例如 1500" />
          </div>
        </div>
        <template #footer>
          <div style="display: flex; justify-content: flex-end; gap: 8px">
            <n-button @click="ragDrawer.show = false">取消</n-button>
            <n-button type="primary" :loading="ragDrawer.submitting" @click="submitRagTask">创建评测任务</n-button>
          </div>
        </template>
      </n-drawer-content>
    </n-drawer>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted, watch } from 'vue'
import { useRouter } from 'vue-router'
import { useMessage, useDialog, type DropdownOption } from 'naive-ui'
import { api } from '../api/http'
import type { Dataset, DatasetRow, GoldQA, TaskSpec } from '../api/types'
import { useModeStore } from '../stores/mode'
import UploadDatasetModal from '../components/modals/UploadDatasetModal.vue'
import BenchmarkLaunchDrawer from '../components/drawers/BenchmarkLaunchDrawer.vue'

/** 数据集表格在契约行字段外保留可扩展的标签与难度列，extras 承载自定义扩展列的值。 */
interface EditableDatasetRow {
  row_no: number
  q: string
  r: string
  c: string
  tags: string
  difficulty: string
  checked: boolean
  extras: Record<string, string>
}

/** 自定义扩展列定义：字段 Key / 显示名 / 值类型。 */
interface CustomColumn {
  key: string
  name: string
  type: 'text' | 'json' | 'number'
}

/** 右键菜单目标类型：文件节点 / 文件夹 / 表格行。 */
type CtxMenuType = 'file' | 'folder' | 'row'

/** AI 合成的三种模式：场景定向 / 种子扩写 / 文档提取。 */
type AiGenMode = 'scene' | 'seed' | 'doc'

/** AI 合成候选行：在可编辑行字段外附带勾选态，供 Step2 预览表使用。 */
interface AiCandidate {
  selected: boolean
  q: string
  r: string
  c: string
  tags: string
  difficulty: string
}

const message = useMessage()
const dialog = useDialog()
const router = useRouter()
const modeStore = useModeStore()
const treeSearch = ref('')
const datasets = ref<Dataset[]>([])
const activeDatasetId = ref('')
const sampleRows = ref<EditableDatasetRow[]>([])
const savingRows = ref(false)
const justSaved = ref(false)
const hasUnsavedChanges = ref(false)
const editingCell = ref<{ row: EditableDatasetRow; field: string; original: string } | null>(null)
const showUploadModal = ref(false)
const datasetForUpload = ref<Dataset | null>(null)
const showLaunchDrawer = ref(false)
const filterPendingOnly = ref(false)

// ─── 目录树面板拖拽调宽（200–520px，双击复位 290px，localStorage 持久化） ───
const TREE_W_KEY = 'ae_ft_w_datasets'
const treeWidth = ref(Math.min(520, Math.max(200, +(localStorage.getItem(TREE_W_KEY) || 290))))
const treeResizing = ref(false)

function applyTreeWidth(w: number) {
  treeWidth.value = Math.min(520, Math.max(200, Math.round(w)))
}

function startTreeResize(e: MouseEvent) {
  e.preventDefault()
  treeResizing.value = true
  const startX = e.clientX
  const startW = treeWidth.value
  const move = (ev: MouseEvent) => applyTreeWidth(startW + ev.clientX - startX)
  const up = () => {
    treeResizing.value = false
    localStorage.setItem(TREE_W_KEY, String(treeWidth.value))
    window.removeEventListener('mousemove', move)
    window.removeEventListener('mouseup', up)
  }
  window.addEventListener('mousemove', move)
  window.addEventListener('mouseup', up)
}

function resetTreeWidth() {
  applyTreeWidth(290)
  localStorage.setItem(TREE_W_KEY, '290')
  message.info('目录树宽度已复位为 290px')
}

// ─── 黄金 QA 资产：树内混排展示 ───
const goldQas = ref<GoldQA[]>([])
const activeGoldQa = computed(() => goldQas.value.find(g => g.id === activeDatasetId.value))
const isGoldQaActive = computed(() => !!activeGoldQa.value)

const currentDataset = computed(() =>
  datasets.value.find(dataset => dataset.id === activeDatasetId.value) || (isGoldQaActive.value ? undefined : datasets.value[0]),
)
const currentItem = computed(() => activeGoldQa.value || currentDataset.value)

interface TreeNode {
  id: string
  name: string
  version: number
  isGoldQa: boolean
  pending_complete_count: number
}
interface TreeFolder {
  id: string
  name: string
  open: boolean
  items: TreeNode[]
}

const folders = ref<TreeFolder[]>([{ id: 'datasets', name: '数据集', open: true, items: [] }])
const goldQaFolder = ref<TreeFolder>({ id: 'gold-qa', name: '黄金 QA', open: true, items: [] })
const allFolders = computed<TreeFolder[]>(() =>
  goldQaFolder.value.items.length ? [...folders.value, goldQaFolder.value] : folders.value,
)

const pendingCount = computed(() => sampleRows.value.filter(row => !row.q.trim() || !row.r.trim()).length)

/** 根据是否勾选「仅看待补全」过滤显示的样本行 */
const displayedRows = computed(() => {
  if (filterPendingOnly.value) {
    return sampleRows.value.filter(row => !row.q.trim() || !row.r.trim())
  }
  return sampleRows.value
})

/** 获取当前过滤行在原始 sampleRows 中的索引 */
function getOriginalRowIndex(row: EditableDatasetRow): number {
  return sampleRows.value.findIndex(r => r.row_no === row.row_no)
}

const filteredFolders = computed(() => {
  const keyword = treeSearch.value.trim().toLowerCase()
  if (!keyword) return allFolders.value
  return allFolders.value.map(folder => ({
    ...folder,
    items: folder.items.filter(item => item.name.toLowerCase().includes(keyword)),
  })).filter(folder => folder.items.length > 0)
})

// ─── 自定义扩展列 ───
const customColsMap = ref<Record<string, CustomColumn[]>>({})
const customCols = computed<CustomColumn[]>(() => {
  const ds = currentDataset.value
  return ds ? customColsMap.value[ds.id] || [] : []
})

function fromColumnSchema(schema: Dataset['column_schema']): CustomColumn[] {
  return (schema || [])
    .filter(item => item && item.key)
    .map(item => ({ key: item.key, name: item.name || item.key, type: (item.type as CustomColumn['type']) || 'text' }))
}

async function persistCustomCols(datasetId: string, nextCols: CustomColumn[], prevCols: CustomColumn[]) {
  try {
    await api.datasets.update(datasetId, {
      column_schema: nextCols.map((col, idx) => ({ key: col.key, name: col.name, type: col.type, sort_order: idx + 1 })),
    })
    const ds = datasets.value.find(item => item.id === datasetId)
    if (ds) ds.column_schema = nextCols.map((col, idx) => ({ key: col.key, name: col.name, type: col.type, sort_order: idx + 1 }))
  } catch (err: any) {
    customColsMap.value[datasetId] = prevCols
    message.error(err.message || '扩展列定义保存失败，已回滚')
    throw err
  }
}

const KNOWN_ROW_KEYS = new Set(['row_no', 'question', 'reference', 'context', 'q', 'r', 'c', 'tags', 'difficulty', 'source_case_id', 'is_pending'])

function toEditableRow(row: DatasetRow): EditableDatasetRow {
  const extendedRow = row as DatasetRow & Record<string, unknown>
  const extras: Record<string, string> = {}
  Object.keys(extendedRow).forEach(key => {
    if (!KNOWN_ROW_KEYS.has(key) && extendedRow[key] != null) extras[key] = String(extendedRow[key])
  })
  return {
    row_no: row.row_no,
    q: String(row.question || extendedRow.q || ''),
    r: String(row.reference || extendedRow.r || ''),
    c: String(row.context || extendedRow.c || ''),
    tags: String(extendedRow.tags || ''),
    difficulty: String(extendedRow.difficulty || '简单'),
    checked: false,
    extras,
  }
}

function toApiRows(): Array<DatasetRow & Record<string, unknown>> {
  return sampleRows.value.map(row => ({
    row_no: row.row_no,
    question: row.q,
    reference: row.r,
    context: row.c || null,
    q: row.q,
    r: row.r,
    c: row.c,
    tags: row.tags,
    difficulty: row.difficulty,
    ...row.extras,
  }))
}

function syncDatasetTree(list: Dataset[]) {
  let root = folders.value.find(folder => folder.id === 'datasets')
  if (!root) {
    root = { id: 'datasets', name: '数据集', open: true, items: [] }
    folders.value.unshift(root)
  }
  const toNode = (dataset: Dataset) => ({
    id: dataset.id,
    name: dataset.name,
    version: dataset.version,
    isGoldQa: false,
    pending_complete_count: dataset.pending_complete_count,
  })
  root.items = []
  folders.value.forEach(folder => {
    if (folder.id !== 'datasets') folder.items = []
  })
  list.forEach(dataset => {
    const folder = dataset.folder_id ? folders.value.find(f => f.id === dataset.folder_id) : undefined
    if (folder && folder.id !== 'datasets') folder.items.push(toNode(dataset))
    else root!.items.push(toNode(dataset))
  })
}

async function loadFolders() {
  try {
    const folderList = await api.datasets.listFolders()
    const root = folders.value.find(folder => folder.id === 'datasets') || { id: 'datasets', name: '数据集', open: true, items: [] }
    folders.value = [
      root,
      ...folderList
        .slice()
        .sort((a, b) => (a.sort_order ?? 0) - (b.sort_order ?? 0))
        .map(folder => ({ id: folder.id, name: folder.name, open: true, items: [] })),
    ]
    if (datasets.value.length) syncDatasetTree(datasets.value)
  } catch {}
}

function syncGoldQaTree(list: GoldQA[]) {
  goldQaFolder.value.items = list.map(qa => ({
    id: qa.id,
    name: qa.name,
    version: qa.version,
    isGoldQa: true,
    pending_complete_count: 0,
  }))
}

// ─── 行勾选与批量操作 ───
const allRowsChecked = computed(() => sampleRows.value.length > 0 && sampleRows.value.every(row => row.checked))
const selectedCount = computed(() => sampleRows.value.filter(row => row.checked).length)

function toggleAllRows(e: Event) {
  const checked = (e.target as HTMLInputElement).checked
  sampleRows.value.forEach(row => {
    row.checked = checked
  })
}

function uncheckAllRows() {
  sampleRows.value.forEach(row => {
    row.checked = false
  })
}

function batchDeleteRows() {
  const count = selectedCount.value
  if (!count) return
  dialog.warning({
    title: '批量删除',
    content: `确认删除勾选的 ${count} 行？删除将在点击“保存修改”后同步服务端。`,
    positiveText: '删除',
    negativeText: '取消',
    onPositiveClick: () => {
      sampleRows.value = sampleRows.value.filter(row => !row.checked)
      hasUnsavedChanges.value = true
      message.info(`已删除 ${count} 行，点击“保存修改”后生效`)
    },
  })
}

function exportSelectedRows() {
  const selected = sampleRows.value.filter(row => row.checked)
  if (!selected.length) return
  const content = selected
    .map(row => JSON.stringify({ question: row.q, reference: row.r, context: row.c || null, tags: row.tags, difficulty: row.difficulty, ...row.extras }))
    .join('\n')
  const blob = new Blob([content], { type: 'application/jsonl' })
  const url = URL.createObjectURL(blob)
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = `${currentDataset.value?.name || 'dataset'}-selected-${selected.length}rows.jsonl`
  anchor.click()
  URL.revokeObjectURL(url)
  message.success(`已导出勾选的 ${selected.length} 行 JSONL`)
}

function cellValue(row: EditableDatasetRow, field: string): string {
  if (field === 'q' || field === 'r' || field === 'c' || field === 'tags' || field === 'difficulty') return row[field]
  return row.extras[field] || ''
}

function editCell(row: EditableDatasetRow, field: string) {
  editingCell.value = { row, field, original: cellValue(row, field) }
}

function finishEditing() {
  editingCell.value = null
  hasUnsavedChanges.value = true
}

function cancelEditing() {
  const cell = editingCell.value
  if (cell) {
    if (cell.field === 'q' || cell.field === 'r' || cell.field === 'c' || cell.field === 'tags' || cell.field === 'difficulty') {
      cell.row[cell.field] = cell.original
    } else {
      cell.row.extras[cell.field] = cell.original
    }
  }
  editingCell.value = null
}

async function selectDataset(id: string) {
  activeDatasetId.value = id
  if (goldQas.value.some(g => g.id === id)) {
    sampleRows.value = []
    hasUnsavedChanges.value = false
    return
  }
  await loadRows(id)
}

function requestSelectDataset(id: string, after?: () => void) {
  if (id === activeDatasetId.value) {
    after?.()
    return
  }
  if (!hasUnsavedChanges.value) {
    void selectDataset(id).then(() => after?.())
    return
  }
  dialog.warning({
    title: '有未保存的修改',
    content: '当前表格存在未落库的编辑，切换前请选择处理方式。',
    positiveText: '保存并切换',
    negativeText: '放弃修改',
    onPositiveClick: async () => {
      await persistRows()
      await selectDataset(id)
      after?.()
    },
    onNegativeClick: () => {
      void selectDataset(id).then(() => after?.())
    },
  })
}

function openUploadModal(dataset: Dataset | null) {
  datasetForUpload.value = dataset
  showUploadModal.value = true
}

function createEmptyDataset(after?: () => void) {
  openNameDialog('新建数据集（空集）', '数据集名称', '新数据集', async (val) => {
    const created = await api.datasets.create({ name: val })
    await loadDatasets()
    await selectDataset(created.id)
    message.success(`已创建空数据集「${created.name}」`)
    after?.()
  })
}

function openLaunchDrawer() {
  showLaunchDrawer.value = true
}

function handleLaunchSuccess() {
  router.push('/tasks')
}

function buildEmptyRow(): EditableDatasetRow {
  return {
    row_no: Math.max(0, ...sampleRows.value.map(row => row.row_no)) + 1,
    q: '',
    r: '',
    c: '',
    tags: '',
    difficulty: '简单',
    checked: false,
    extras: {},
  }
}

function addRow() {
  sampleRows.value.push(buildEmptyRow())
  hasUnsavedChanges.value = true
  message.info('已新增空白行，填写后点击“保存修改”落库')
}

function deleteRow(index: number) {
  sampleRows.value.splice(index, 1)
  hasUnsavedChanges.value = true
  message.info('已删除该行，点击“保存修改”后生效')
}

async function persistRows() {
  if (!currentDataset.value || savingRows.value) return
  savingRows.value = true
  try {
    await api.datasets.saveRows(currentDataset.value.id, toApiRows())
    const dataset = datasets.value.find(item => item.id === currentDataset.value!.id)
    if (dataset) {
      dataset.row_count = sampleRows.value.length
      dataset.pending_complete_count = pendingCount.value
    }
    syncDatasetTree(datasets.value)
    hasUnsavedChanges.value = false
    justSaved.value = true
    setTimeout(() => { justSaved.value = false }, 1800)
    message.success('数据集修改已成功保存')
  } catch (err: any) {
    message.error(err.message || '保存数据集行失败')
  } finally {
    savingRows.value = false
  }
}

function exportJsonl() {
  const content = sampleRows.value.map(row => JSON.stringify({ question: row.q, reference: row.r, context: row.c || null, tags: row.tags, difficulty: row.difficulty, ...row.extras })).join('\n')
  const blob = new Blob([content], { type: 'application/jsonl' })
  const url = URL.createObjectURL(blob)
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = `${currentDataset.value?.name || 'dataset'}-v${currentDataset.value?.version || 1}.jsonl`
  anchor.click()
  URL.revokeObjectURL(url)
  message.success('当前表格内容已导出为 JSONL 文件')
}

async function saveMetric() {
  if (!currentDataset.value) return
  try {
    const updated = await api.datasets.update(currentDataset.value.id, { metric: currentDataset.value.metric })
    const index = datasets.value.findIndex(item => item.id === updated.id)
    if (index !== -1) datasets.value[index] = updated
    syncDatasetTree(datasets.value)
    message.success('主评分指标已更新')
  } catch (err: any) {
    message.error(err.message || '更新主评分指标失败')
  }
}

async function loadRows(datasetId: string) {
  try {
    sampleRows.value = (await api.datasets.getRows(datasetId)).map(toEditableRow)
    hasUnsavedChanges.value = false
  } catch (err: any) {
    sampleRows.value = []
    message.error(err.message || '加载数据集行失败')
  }
}

async function loadDatasets() {
  try {
    const list = await api.datasets.list()
    datasets.value = list
    list.forEach(ds => {
      customColsMap.value[ds.id] = fromColumnSchema(ds.column_schema)
    })
    syncDatasetTree(list)
    const selected = list.find(dataset => dataset.id === activeDatasetId.value) || list[0]
    if (selected) await selectDataset(selected.id)
    else sampleRows.value = []
  } catch (err: any) {
    datasets.value = []
    syncDatasetTree([])
    sampleRows.value = []
    message.error(err.message || '加载数据集失败')
  }
}

async function loadGoldQas() {
  try {
    const kbs = await api.kb.list()
    const lists = await Promise.all(kbs.map(kb => api.kb.getGoldQA(kb.id).catch(() => [] as GoldQA[])))
    goldQas.value = lists.flat()
  } catch {
    goldQas.value = []
  }
  syncGoldQaTree(goldQas.value)
}

// ─── 右键上下文菜单 ───
const ctxMenu = ref<{ show: boolean; x: number; y: number; type: CtxMenuType; targetId: string; rowIdx: number }>({
  show: false,
  x: 0,
  y: 0,
  type: 'file',
  targetId: '',
  rowIdx: -1,
})

function openCtxMenu(e: MouseEvent, type: CtxMenuType, targetId = '', rowIdx = -1) {
  ctxMenu.value = { show: true, x: e.clientX, y: e.clientY, type, targetId, rowIdx }
}

function closeCtxMenu() {
  ctxMenu.value.show = false
}

const ctxMenuOptions = computed<DropdownOption[]>(() => {
  if (ctxMenu.value.type === 'file') {
    const isGoldQaNode = goldQas.value.some(g => g.id === ctxMenu.value.targetId)
    if (isGoldQaNode) {
      return [
        { label: '⚡ 发起 RAG 评测', key: 'eval' },
        { label: '📋 复制 gold_qa_id', key: 'copy-id' },
      ]
    }
    const ds = datasets.value.find(item => item.id === ctxMenu.value.targetId)
    return [
      { label: '⚡ 发起评测', key: 'eval' },
      { label: `⤴ 覆盖上传新版本 (v${(ds?.version || 1) + 1})`, key: 'upload' },
      { label: '✨ AI 补全缺失行', key: 'ai-fill' },
      { type: 'divider', key: 'd1' },
      { label: '✏ 重命名', key: 'rename' },
      { label: '📋 复制数据集 ID', key: 'copy-id' },
      { label: '⤓ 导出 JSONL', key: 'export' },
      { type: 'divider', key: 'd2' },
      { label: '🗑 删除数据集', key: 'delete', props: { style: 'color: var(--accent-error)' } },
    ]
  }
  if (ctxMenu.value.type === 'folder') {
    return [
      { label: '📄 新建数据集（空集）', key: 'new-dataset' },
      { label: '📁 新建子文件夹', key: 'new-folder' },
      { type: 'divider', key: 'd1' },
      { label: '✏ 重命名目录', key: 'rename-folder' },
      { label: '🗑 删除目录', key: 'delete-folder', props: { style: 'color: var(--accent-error)' } },
    ]
  }
  const row = sampleRows.value[ctxMenu.value.rowIdx]
  return [
    { label: '✏ 详细弹窗编辑', key: 'edit' },
    { label: '✨ AI 补全本行', key: 'ai-fill-row' },
    { label: '📋 复制为 JSON', key: 'copy-json' },
    { label: row?.checked ? '☑ 取消勾选本行' : '☐ 勾选本行', key: 'toggle-check' },
    { type: 'divider', key: 'd1' },
    { label: '⬆ 在上方插入新行', key: 'insert-above' },
    { label: '＋ 在下方插入新行', key: 'insert-below' },
    { label: '⧉ 创建本行副本', key: 'duplicate-row' },
    { type: 'divider', key: 'd2' },
    { label: '🗑 删除本行', key: 'delete-row', props: { style: 'color: var(--accent-error)' } },
  ]
})

function handleCtxSelect(key: string | number) {
  const { type, targetId, rowIdx } = ctxMenu.value
  closeCtxMenu()
  const action = String(key)
  if (type === 'file') void handleFileCtxAction(action, targetId)
  else if (type === 'folder') void handleFolderCtxAction(action, targetId)
  else void handleRowCtxAction(action, rowIdx)
}

async function handleFileCtxAction(key: string, targetId: string) {
  const goldQa = goldQas.value.find(g => g.id === targetId)
  if (goldQa) {
    if (key === 'eval') {
      await selectDataset(targetId)
      openRagDrawer()
    } else if (key === 'copy-id') {
      await navigator.clipboard.writeText(targetId)
      message.success('已复制 gold_qa_id 到剪贴板')
    }
    return
  }
  const dataset = datasets.value.find(item => item.id === targetId)
  if (!dataset) return
  switch (key) {
    case 'eval':
      requestSelectDataset(targetId, () => openLaunchDrawer())
      break
    case 'upload':
      openUploadModal(dataset)
      break
    case 'ai-fill':
      requestSelectDataset(targetId, () => openAiFillModal())
      break
    case 'rename':
      openNameDialog('重命名数据集', '数据集名称', dataset.name, async (val) => {
        const updated = await api.datasets.update(targetId, { name: val })
        const index = datasets.value.findIndex(item => item.id === targetId)
        if (index !== -1) datasets.value[index] = updated
        syncDatasetTree(datasets.value)
        message.success('已重命名数据集')
      })
      break
    case 'copy-id':
      await navigator.clipboard.writeText(targetId)
      message.success('已复制数据集 ID 到剪贴板')
      break
    case 'export':
      requestSelectDataset(targetId, () => exportJsonl())
      break
    case 'delete':
      confirmDeleteDataset(dataset)
      break
  }
}

function confirmDeleteDataset(dataset: Dataset) {
  dialog.warning({
    title: '删除数据集',
    content: `确认删除「${dataset.name}」(v${dataset.version})？已跑任务的历史快照不受影响，此操作不可恢复。`,
    positiveText: '删除',
    negativeText: '取消',
    onPositiveClick: async () => {
      try {
        await api.datasets.delete(dataset.id)
        if (activeDatasetId.value === dataset.id) activeDatasetId.value = ''
        await loadDatasets()
        message.success(`已删除「${dataset.name}」`)
      } catch (err: any) {
        message.error(err.message || '删除数据集失败')
      }
    },
  })
}

async function handleFolderCtxAction(key: string, folderId: string) {
  const folder = folders.value.find(item => item.id === folderId)
  if (!folder) return
  switch (key) {
    case 'new-dataset':
      createEmptyDataset()
      break
    case 'new-folder':
      openNameDialog('新建子文件夹', '文件夹名称', '新建文件夹', async (val) => {
        try {
          await api.datasets.createFolder({ name: val })
          await loadFolders()
          message.success(`已创建子文件夹「${val}」`)
        } catch (err: any) {
          message.error(err.message || '创建子文件夹失败')
        }
      })
      break
    case 'rename-folder':
      if (folder.id === 'datasets' || folder.id === 'gold-qa') {
        message.warning('系统目录不可重命名')
        return
      }
      openNameDialog('重命名目录', '目录名称', folder.name, async (val) => {
        try {
          await api.datasets.updateFolder(folderId, { name: val })
          await loadFolders()
          message.success(`已更新目录名「${val}」`)
        } catch (err: any) {
          message.error(err.message || '重命名失败')
        }
      })
      break
    case 'delete-folder':
      if (folder.id === 'datasets' || folder.id === 'gold-qa') {
        message.warning('系统目录不可删除')
        return
      }
      if (folder.items.length) {
        message.warning('目录非空，请先移出或删除其中的数据集')
        return
      }
      dialog.warning({
        title: '删除目录',
        content: `确认删除空目录「${folder.name}」？`,
        positiveText: '删除',
        negativeText: '取消',
        onPositiveClick: async () => {
          try {
            await api.datasets.deleteFolder(folderId)
            await loadFolders()
            message.success(`已删除目录「${folder.name}」`)
          } catch (err: any) {
            message.error(err.message || '删除目录失败')
          }
        },
      })
      break
  }
}

async function handleRowCtxAction(key: string, rowIdx: number) {
  const row = sampleRows.value[rowIdx]
  if (!row) return
  switch (key) {
    case 'edit':
      openRowEditModal(rowIdx)
      break
    case 'ai-fill-row':
      await aiFillRow(rowIdx)
      break
    case 'copy-json': {
      const payload = {
        row_no: row.row_no,
        question: row.q,
        reference: row.r,
        context: row.c || null,
        tags: row.tags,
        difficulty: row.difficulty,
        ...row.extras,
      }
      await navigator.clipboard.writeText(JSON.stringify(payload, null, 2))
      message.success('已复制样本行 JSON 到剪贴板')
      break
    }
    case 'toggle-check':
      row.checked = !row.checked
      break
    case 'insert-above':
      sampleRows.value.splice(rowIdx, 0, buildEmptyRow())
      hasUnsavedChanges.value = true
      message.info('已在上方插入新行，点击“保存修改”后生效')
      break
    case 'insert-below':
      sampleRows.value.splice(rowIdx + 1, 0, buildEmptyRow())
      hasUnsavedChanges.value = true
      message.info('已在下方插入新行，点击“保存修改”后生效')
      break
    case 'duplicate-row': {
      const copy: EditableDatasetRow = {
        ...buildEmptyRow(),
        q: row.q,
        r: row.r,
        c: row.c,
        tags: row.tags,
        difficulty: row.difficulty,
        extras: { ...row.extras },
      }
      sampleRows.value.splice(rowIdx + 1, 0, copy)
      hasUnsavedChanges.value = true
      message.success(`已创建第 ${row.row_no} 行副本，点击“保存修改”后生效`)
      break
    }
    case 'delete-row':
      deleteRow(rowIdx)
      break
  }
}

// ─── 通用单输入弹窗 ───
const nameDialog = ref<{
  show: boolean
  title: string
  label: string
  value: string
  action: ((val: string) => void | Promise<void>) | null
}>({ show: false, title: '', label: '', value: '', action: null })
const nameDialogBusy = ref(false)

function openNameDialog(title: string, label: string, initial: string, action: (val: string) => void | Promise<void>) {
  nameDialog.value = { show: true, title, label, value: initial, action }
}

async function confirmNameDialog() {
  const val = nameDialog.value.value.trim()
  if (!val) {
    message.warning('请输入名称')
    return
  }
  if (!nameDialog.value.action) return
  nameDialogBusy.value = true
  try {
    await nameDialog.value.action(val)
    nameDialog.value.show = false
  } catch (err: any) {
    message.error(err.message || '操作失败')
  } finally {
    nameDialogBusy.value = false
  }
}

// ─── 行结构化编辑弹窗 ───
const rowEdit = ref<{ show: boolean; idx: number; rowNo: number; q: string; r: string; c: string; extras: Record<string, string> }>({
  show: false,
  idx: -1,
  rowNo: 0,
  q: '',
  r: '',
  c: '',
  extras: {},
})

function openRowEditModal(idx: number) {
  const row = sampleRows.value[idx]
  if (!row) return
  editingCell.value = null
  const extras = { ...row.extras }
  customCols.value.forEach(col => {
    if (!(col.key in extras)) extras[col.key] = ''
  })
  rowEdit.value = { show: true, idx, rowNo: row.row_no, q: row.q, r: row.r, c: row.c, extras }
}

function saveRowEdit() {
  const row = sampleRows.value[rowEdit.value.idx]
  if (!row) {
    rowEdit.value.show = false
    return
  }
  row.q = rowEdit.value.q.trim()
  row.r = rowEdit.value.r.trim()
  row.c = rowEdit.value.c.trim()
  row.extras = { ...rowEdit.value.extras }
  hasUnsavedChanges.value = true
  rowEdit.value.show = false
  message.success(`已更新样本 #${row.row_no}，点击“保存修改”落库`)
}

// ─── 新增扩展列弹窗 ───
const addCol = ref<{ show: boolean; key: string; name: string; type: CustomColumn['type'] }>({ show: false, key: '', name: '', type: 'text' })
const RESERVED_COL_KEYS = ['row_no', 'question', 'reference', 'context', 'q', 'r', 'c', 'tags', 'difficulty']

function openAddColModal() {
  addCol.value = { show: true, key: '', name: '', type: 'text' }
}

async function confirmAddCol() {
  const ds = currentDataset.value
  if (!ds) return
  const key = addCol.value.key.trim().toLowerCase()
  const name = addCol.value.name.trim()
  if (!/^[a-z][a-z0-9_]*$/.test(key)) {
    message.warning('字段 Key 需以英文字母开头，仅含小写字母 / 数字 / 下划线')
    return
  }
  if (!name) {
    message.warning('请填写列显示名称')
    return
  }
  if (RESERVED_COL_KEYS.includes(key)) {
    message.warning('该字段 Key 与内置列冲突，请更换')
    return
  }
  const list = customColsMap.value[ds.id] || []
  if (list.some(col => col.key === key)) {
    message.warning('该字段 Key 已存在')
    return
  }
  const nextCols = [...list, { key, name, type: addCol.value.type }]
  customColsMap.value[ds.id] = nextCols
  sampleRows.value.forEach(row => {
    row.extras[key] = ''
  })
  hasUnsavedChanges.value = true
  addCol.value.show = false
  try {
    await persistCustomCols(ds.id, nextCols, list)
    message.success(`已添加自定义列「${name}」`)
  } catch {}
}

async function removeCustomCol(key: string) {
  const ds = currentDataset.value
  if (!ds) return
  const prevCols = customColsMap.value[ds.id] || []
  const nextCols = prevCols.filter(col => col.key !== key)
  customColsMap.value[ds.id] = nextCols
  sampleRows.value.forEach(row => {
    delete row.extras[key]
  })
  hasUnsavedChanges.value = true
  try {
    await persistCustomCols(ds.id, nextCols, prevCols)
    message.info(`已移除列 ${key}`)
  } catch {}
}

// ─── AI 合成向导 ───
const AI_PRESETS = [
  { name: '跨境收银与外币结算', desc: '涵盖外卡快捷支付、汇损换算、3DS 安全验证与跨境退款' },
  { name: '风控拦截与账户锁定', desc: '密码连续输错锁定、人脸识别解锁、高危 IP 拦截与大额转账审批' },
  { name: '退款售后与争议仲裁', desc: '退款时效 1-3 工作日、手续费返还规则、部分退款及银联争议处理' },
  { name: '发票与税务合规', desc: '增值税专用发票邮寄、电子发票 24h 发送、红字冲销及抬头修改' },
]

const aiGen = ref({
  show: false,
  step: 1 as 1 | 2,
  mode: 'scene' as AiGenMode,
  preset: AI_PRESETS[0].desc,
  instruction: AI_PRESETS[0].desc,
  seedSample: '',
  dims: ['synonym', 'constraint', 'boundary'] as string[],
  docText: '',
  rowCount: 8,
  model: 'gpt-4.1',
  temperature: 0.5,
  genRef: true,
  genCtx: true,
  genTags: true,
  generating: false,
  candidates: [] as AiCandidate[],
})

const presetOptions = computed(() => AI_PRESETS.map(p => ({ label: `${p.name} · ${p.desc}`, value: p.desc })))

const seedOptions = computed(() =>
  sampleRows.value
    .filter(row => row.q.trim())
    .slice(0, 10)
    .map(row => ({
      label: `${row.q} · ${row.r}`.slice(0, 60),
      value: `${row.q} => ${row.r}`,
    })),
)

const aiSelectedCount = computed(() => aiGen.value.candidates.filter(c => c.selected).length)
const aiAllSelected = computed(() => aiGen.value.candidates.length > 0 && aiSelectedCount.value === aiGen.value.candidates.length)

function openAiGenModal() {
  const target = currentDataset.value || datasets.value[0]
  if (!target) {
    createEmptyDataset(() => openAiGenModal())
    return
  }
  if (target.id !== activeDatasetId.value) void selectDataset(target.id)
  aiGen.value.show = true
  aiGen.value.step = 1
  if (!aiGen.value.seedSample && seedOptions.value.length) aiGen.value.seedSample = seedOptions.value[0].value
}

function onPresetChange(val: string) {
  aiGen.value.instruction = val
}

async function runAiGenerate() {
  if (!currentDataset.value || aiGen.value.generating) return
  const form = aiGen.value
  if (form.mode === 'scene' && !form.instruction.trim()) {
    message.warning('请填写场景与评估目标描述')
    return
  }
  if (form.mode === 'seed' && !form.seedSample) {
    message.warning('请选择种子样本')
    return
  }
  if (form.mode === 'doc' && !form.docText.trim()) {
    message.warning('请粘贴需求文档或接口定义文本')
    return
  }
  form.generating = true
  try {
    let candidates: AiCandidate[] = []
    if (api.isMock()) {
      await new Promise(resolve => setTimeout(resolve, 500))
      candidates = Array.from({ length: form.rowCount }, (_, i) => ({
        selected: true,
        q: `如何处理跨境交易退款中的汇损问题？（场景派生 #${i + 1}）`,
        r: form.genRef ? '根据平台协议，外币支付订单在退款时按原路退回，退款汇率以交易发起时汇率为准，手续费按比例全额返还。' : '',
        c: form.genCtx ? '跨境结算业务指引 v2.4' : '',
        tags: form.genTags ? '外汇,退款' : '',
        difficulty: i % 3 === 0 ? '高' : i % 3 === 1 ? '中等' : '简单',
      }))
    } else {
      const result = await api.datasets.generateRows({
        dataset_id: currentDataset.value.id,
        mode: form.mode,
        instruction: form.instruction.trim(),
        source_text: form.docText.trim(),
        seed: form.seedSample,
        max_count: form.rowCount,
        model: form.model,
        temperature: form.temperature,
      })
      candidates = result.map(row => {
        const editable = toEditableRow(row)
        return { selected: true, q: editable.q, r: editable.r, c: editable.c, tags: editable.tags, difficulty: editable.difficulty || '中等' }
      })
      if (!candidates.length) throw new Error('生成接口未返回候选数据行')
    }
    form.candidates = candidates
    form.step = 2
  } catch (err: any) {
    message.error(err.message || 'AI 生成候选失败')
  } finally {
    form.generating = false
  }
}

function toggleAllCandidates() {
  const target = aiSelectedCount.value < aiGen.value.candidates.length
  aiGen.value.candidates.forEach(c => {
    c.selected = target
  })
}

function commitAiCandidates() {
  const selected = aiGen.value.candidates.filter(c => c.selected)
  if (!selected.length) return
  let nextRowNo = Math.max(0, ...sampleRows.value.map(row => row.row_no)) + 1
  selected.forEach(c => {
    sampleRows.value.push({ row_no: nextRowNo++, q: c.q, r: c.r, c: c.c, tags: c.tags, difficulty: c.difficulty, checked: false, extras: {} })
  })
  hasUnsavedChanges.value = true
  aiGen.value.show = false
  message.success(`已采纳 ${selected.length} 条 AI 候选，请审核后点击“保存修改”落库`)
}

// ─── AI 补全 ───
const aiFill = ref({
  show: false,
  instruction: '基于已有业务上下文与同组高质样本，精准推导出前置问句与包含操作路径的完整标准答案。',
  scopeQ: true,
  scopeR: true,
  filling: false,
})

function openAiFillModal() {
  if (!currentDataset.value) return
  if (pendingCount.value === 0) {
    message.info('当前数据集所有样本均已完整，无缺失项')
    return
  }
  aiFill.value.show = true
}

async function confirmAiFill() {
  if (!currentDataset.value || aiFill.value.filling) return
  aiFill.value.filling = true
  try {
    if (api.isMock()) {
      await new Promise(resolve => setTimeout(resolve, 500))
      sampleRows.value.forEach((row, i) => {
        if (aiFill.value.scopeQ && !row.q.trim()) row.q = `AI 推导问句 #${i + 1}：如何申请退款与发票红冲？`
        if (aiFill.value.scopeR && !row.r.trim()) row.r = '在「账单详情-申请退款」提交凭证，财务核销后电子发票将自动冲红并在 1-3 工作日原路退回。'
      })
    } else {
      const candidates = await api.datasets.generateRows({
        dataset_id: currentDataset.value.id,
        mode: 'fill_missing',
        instruction: aiFill.value.instruction.trim(),
        rows: toApiRows().filter(row => !row.question || !row.reference),
        max_count: pendingCount.value,
      })
      candidates.map(toEditableRow).forEach(candidate => {
        const target = sampleRows.value.find(row => row.row_no === candidate.row_no)
        if (!target) return
        target.q = candidate.q
        target.r = candidate.r
        target.c = candidate.c
        if (candidate.tags) target.tags = candidate.tags
        if (candidate.difficulty) target.difficulty = candidate.difficulty
        target.extras = { ...(target.extras || {}), ...(candidate.extras || {}) }
      })
    }
    hasUnsavedChanges.value = true
    aiFill.value.show = false
    message.success('AI 补全候选已回填，请审核后点击“保存修改”落库')
  } catch (err: any) {
    message.error(err.message || 'AI 补全候选失败')
  } finally {
    aiFill.value.filling = false
  }
}

async function aiFillRow(idx: number) {
  const row = sampleRows.value[idx]
  if (!row || !currentDataset.value) return
  try {
    if (api.isMock()) {
      if (!row.q.trim()) row.q = 'AI 补全问句：如何查看账单扣款明细？'
      if (!row.r.trim()) row.r = '进入「财务中心-账单管理」查看扣费记录与电子凭证。'
    } else {
      const result = await api.datasets.generateRows({
        dataset_id: currentDataset.value.id,
        mode: 'fill_missing',
        rows: [{ row_no: row.row_no, question: row.q, reference: row.r, context: row.c || null }],
        max_count: 1,
      })
      const value = result[0] ? toEditableRow(result[0]) : null
      if (!value) throw new Error('补全接口未返回行数据')
      row.q = value.q || row.q
      row.r = value.r || row.r
      row.c = value.c || row.c
    }
    hasUnsavedChanges.value = true
    message.success(`已完成第 ${row.row_no} 行 AI 补全，保存后生效`)
  } catch (err: any) {
    message.error(err.message || 'AI 补全失败')
  }
}

// ─── 黄金 QA RAG 抽屉 ───
const RAG_MODES = ['naive', 'local', 'global', 'hybrid'] as const
type RagMode = (typeof RAG_MODES)[number]

const ragDrawer = ref({
  show: false,
  kbId: '',
  goldQaId: '',
  goldQaLabel: '',
  modes: ['hybrid'] as RagMode[],
  k: 8,
  concurrency: 4,
  timeoutS: 60,
  withStress: false,
  stressEnv: 'staging' as 'dev' | 'test' | 'staging' | 'prod',
  qps: 50,
  durationS: 60,
  slaP99Ms: undefined as number | undefined,
  submitting: false,
})

const ragDrawerWidth = computed(() => (typeof window !== 'undefined' && window.innerWidth <= 640 ? '100%' : 480))

function openRagDrawer() {
  const qa = activeGoldQa.value
  if (!qa) return
  ragDrawer.value.show = true
  ragDrawer.value.kbId = qa.kb_id || 'kb-default'
  ragDrawer.value.goldQaId = qa.id
  ragDrawer.value.goldQaLabel = `${qa.name} v${qa.version}`
}

function toggleRagMode(m: RagMode) {
  const modes = ragDrawer.value.modes
  const idx = modes.indexOf(m)
  if (idx >= 0) modes.splice(idx, 1)
  else modes.push(m)
}

async function submitRagTask() {
  if (ragDrawer.value.submitting) return
  if (!ragDrawer.value.modes.length) {
    message.warning('至少选择一个 rag_mode')
    return
  }
  ragDrawer.value.submitting = true
  try {
    const spec: TaskSpec = {
      kind: 'rag',
      kb_id: ragDrawer.value.kbId,
      gold_qa_id: ragDrawer.value.goldQaId,
      rag_mode: [...ragDrawer.value.modes],
      run: { k: ragDrawer.value.k, concurrency: ragDrawer.value.concurrency, timeout_s: ragDrawer.value.timeoutS },
      with_stress: ragDrawer.value.withStress,
    }
    if (ragDrawer.value.withStress) {
      spec.stress = {
        env: ragDrawer.value.stressEnv,
        qps: ragDrawer.value.qps,
        duration_s: ragDrawer.value.durationS,
        sla_p99_ms: ragDrawer.value.slaP99Ms,
      }
    }
    await api.tasks.create(spec)
    ragDrawer.value.show = false
    message.success('RAG 评测任务已创建（queued）')
    setTimeout(() => router.push('/tasks'), 650)
  } catch (err: any) {
    message.error(err.message || '创建任务失败')
  } finally {
    ragDrawer.value.submitting = false
  }
}

function onGlobalKeydown(e: KeyboardEvent) {
  if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 's') {
    if (hasUnsavedChanges.value && !isGoldQaActive.value) {
      e.preventDefault()
      void persistRows()
    }
  }
}

onMounted(() => {
  if (modeStore.mode === 'llm') {
    void loadDatasets()
    void loadFolders()
    void loadGoldQas()
  }
  window.addEventListener('keydown', onGlobalKeydown)
})

onUnmounted(() => {
  window.removeEventListener('keydown', onGlobalKeydown)
})

watch(() => modeStore.mode, (mode) => {
  if (mode === 'llm' && !datasets.value.length) {
    void loadDatasets()
    void loadFolders()
    void loadGoldQas()
  }
})
</script>

<style scoped>
.datasets-workbench {
  height: calc(100vh - var(--topbar-h) - 20px);
  min-height: 0;
  display: flex;
  flex-direction: column;
}

.mode-context-panel {
  max-width: 640px;
  margin: 64px auto;
  padding: 36px 32px;
  text-align: center;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 16px;
  border-radius: 20px;
}
.mode-icon-wrapper {
  width: 60px;
  height: 60px;
  border-radius: 16px;
  background: var(--t-kb);
  color: var(--c-kb);
  display: grid;
  place-items: center;
}
.mode-context-panel h2 {
  font-size: 20px;
  font-weight: 700;
  color: var(--text-primary);
}
.mode-context-panel p {
  font-size: 14px;
  color: var(--text-secondary);
  line-height: 1.7;
}

/* ─── IDE 工作台分栏骨架 ─── */
.ft-layout {
  display: grid;
  grid-template-columns: var(--ft-w, 290px) minmax(0, 1fr);
  height: 100%;
  min-width: 0;
  background: var(--bg-main);
  border-radius: 16px;
  overflow: hidden;
  border: 1px solid var(--border-subtle);
  box-shadow: 0 4px 20px rgba(17, 24, 39, 0.04);
}

.ft-sidebar {
  border-right: 1px solid var(--border-subtle);
  background: var(--bg-elevated);
  display: flex;
  flex-direction: column;
  height: 100%;
  position: relative;
  user-select: none;
}

.ft-header {
  padding: 12px 14px;
  border-bottom: 1px solid var(--border-subtle);
}
.ft-title {
  display: flex;
  align-items: center;
  gap: 6px;
  font-weight: 600;
  font-size: 13px;
  color: var(--text-primary);
}
.ft-title-icon {
  color: var(--c-datasets);
}

.btn-xs {
  min-height: 26px;
  padding: 2px 8px;
  font-size: 11px;
  border-radius: 6px;
  transition: transform 0.1s ease, filter 0.1s ease;
}
.btn-xs:active {
  transform: scale(0.96);
}
.btn-ai-soft {
  background: var(--t-agent);
  color: var(--c-agent);
  border: 1px solid transparent;
}
.btn-ai-soft:hover {
  filter: brightness(0.96);
}
.sparkle {
  font-size: 12px;
}

.search-input-wrapper {
  position: relative;
  display: flex;
  align-items: center;
}
.search-icon {
  position: absolute;
  left: 9px;
  color: var(--text-tertiary);
  pointer-events: none;
}
.tree-search-input {
  height: 30px;
  padding-left: 28px;
  padding-right: 24px;
  font-size: 12px;
  border-radius: 8px;
  background: var(--bg-main);
  transition: border-color 0.15s ease, box-shadow 0.15s ease;
}
.tree-search-input:focus {
  border-color: var(--accent-ai);
  box-shadow: 0 0 0 2px rgba(99, 102, 241, 0.15);
}
.clear-search-btn {
  position: absolute;
  right: 7px;
  background: none;
  border: none;
  color: var(--text-tertiary);
  font-size: 11px;
  cursor: pointer;
  padding: 3px;
  border-radius: 4px;
}
.clear-search-btn:hover {
  background: rgba(17, 24, 39, 0.08);
  color: var(--text-primary);
}

.ft-tree {
  flex: 1;
  overflow-y: auto;
  padding: 8px;
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.ft-node {
  display: flex;
  align-items: center;
  gap: 7px;
  padding: 6px 10px;
  border-radius: 8px;
  font-size: 13px;
  cursor: pointer;
  transition: background-color 0.12s cubic-bezier(0.16, 1, 0.3, 1), color 0.12s ease;
  color: var(--text-secondary);
}
.ft-node:hover {
  background: rgba(17, 24, 39, 0.04);
  color: var(--text-primary);
}
[data-theme='dark'] .ft-node:hover {
  background: rgba(255, 255, 255, 0.05);
}
.ft-node.active {
  background: var(--t-datasets);
  color: var(--c-datasets);
  font-weight: 600;
}
.ft-node.folder {
  font-weight: 600;
  color: var(--text-primary);
}

.ft-chevron {
  display: grid;
  place-items: center;
  color: var(--text-tertiary);
  transition: transform 0.18s cubic-bezier(0.16, 1, 0.3, 1);
}
.ft-chevron.rotated {
  transform: rotate(90deg);
}

.ft-folder-icon {
  color: var(--text-secondary);
  flex-shrink: 0;
}
.ft-folder-name {
  flex: 1;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.ft-folder-child {
  padding-left: 14px;
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.ft-file-icon {
  display: grid;
  place-items: center;
  flex-shrink: 0;
}
.ft-file-icon.gold-qa {
  color: #D97706;
}
.ft-file-icon.dataset {
  color: var(--c-datasets);
}

.ft-file-name {
  flex: 1;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.version-tag {
  font-family: var(--font-mono);
  font-size: 10px;
  padding: 1px 5px;
  border-radius: 4px;
  background: rgba(17, 24, 39, 0.05);
  color: var(--text-tertiary);
}
.ft-node.active .version-tag {
  background: color-mix(in srgb, var(--c-datasets) 15%, transparent);
  color: var(--c-datasets);
}

.ft-status-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: var(--accent-warning);
  flex-shrink: 0;
}

.ft-badge {
  margin-left: auto;
  font-family: var(--font-mono);
  font-size: 11px;
  color: var(--text-tertiary);
}

.ft-empty-state {
  padding: 32px 16px;
  text-align: center;
  color: var(--text-tertiary);
  font-size: 12px;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 8px;
}

/* 调宽手柄 */
.ft-resizer {
  position: absolute;
  top: 0;
  right: -3px;
  width: 6px;
  height: 100%;
  cursor: col-resize;
  z-index: 10;
  display: grid;
  place-items: center;
}
.resizer-handle-line {
  width: 2px;
  height: 24px;
  border-radius: 1px;
  background: transparent;
  transition: background 0.15s ease;
}
.ft-resizer:hover .resizer-handle-line,
.ft-resizer.on .resizer-handle-line {
  background: var(--accent-ai);
}

/* ─── 主工作区 ─── */
.workspace-main {
  display: flex;
  flex-direction: column;
  height: 100%;
  min-width: 0;
  min-height: 0;
  background: var(--bg-main);
  position: relative;
}

.ws-toolbar {
  padding: 12px 20px;
  border-bottom: 1px solid var(--border-subtle);
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 14px;
  flex-wrap: wrap;
  background: var(--bg-main);
}

.ws-title-group {
  display: flex;
  flex-direction: column;
  gap: 2px;
}
.ws-title-row {
  display: flex;
  align-items: center;
  gap: 8px;
}
.ws-dataset-title {
  font-size: 16px;
  font-weight: 700;
  color: var(--text-primary);
}
.version-pill {
  font-family: var(--font-mono);
  font-size: 11px;
  font-weight: 600;
  padding: 1px 7px;
  border-radius: 999px;
  background: var(--bg-elevated);
  border: 1px solid var(--border-subtle);
  color: var(--text-secondary);
}
.kind-chip {
  font-size: 11px;
  font-weight: 500;
  padding: 1px 8px;
  border-radius: 999px;
  border: 1px solid transparent;
}
.chip-dataset {
  background: var(--t-datasets);
  color: var(--c-datasets);
  border-color: color-mix(in srgb, var(--c-datasets) 25%, transparent);
}
.chip-gold-qa {
  background: var(--t-kb);
  color: var(--c-kb);
  border-color: color-mix(in srgb, var(--c-kb) 25%, transparent);
}

.ws-breadcrumb {
  font-size: 11px;
  color: var(--text-tertiary);
  display: flex;
  align-items: center;
  gap: 4px;
}
.ws-breadcrumb .cur {
  color: var(--text-secondary);
}

.ws-action-group {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}
.action-btn-cluster {
  display: flex;
  align-items: center;
  gap: 6px;
}
.ai-cluster {
  background: color-mix(in srgb, var(--c-agent) 6%, transparent);
  padding: 2px 4px;
  border-radius: 10px;
}

.save-btn {
  position: relative;
  display: inline-flex;
  align-items: center;
  gap: 5px;
  transition: transform 0.1s ease, box-shadow 0.2s ease, background-color 0.2s ease;
}
.save-btn:active {
  transform: scale(0.97);
}
.save-btn.dirty {
  background: var(--accent-ai);
  box-shadow: 0 0 12px rgba(99, 102, 241, 0.4);
}
.save-btn.saved {
  background: #059669 !important;
  color: #fff !important;
}
.saved-check-icon {
  font-weight: 700;
  font-size: 12px;
}
.dirty-indicator {
  display: inline-block;
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: #FBBF24;
  margin-right: 2px;
  animation: pulse-dot 1.4s infinite;
}
@keyframes pulse-dot {
  0%, 100% { transform: scale(1); opacity: 1; }
  50% { transform: scale(1.3); opacity: 0.6; }
}

.shortcut-pill {
  font-size: 9.5px;
  font-family: var(--font-mono);
  padding: 1px 4px;
  border-radius: 3px;
  background: rgba(255, 255, 255, 0.2);
  color: inherit;
  margin-left: 2px;
}

.launch-btn {
  box-shadow: 0 2px 8px rgba(17, 24, 39, 0.12);
  transition: transform 0.1s ease, box-shadow 0.15s ease;
}
.launch-btn:active {
  transform: scale(0.97);
}

/* ─── 概览栏 ─── */
.quality-glance-bar {
  padding: 7px 20px;
  background: var(--bg-elevated);
  border-bottom: 1px solid var(--border-subtle);
  display: flex;
  align-items: center;
  gap: 12px;
  font-size: 12px;
}
.glance-metrics-left {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}
.glance-label {
  font-weight: 600;
  color: var(--text-secondary);
}
.glance-pill {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  padding: 2px 8px;
  border-radius: 6px;
  background: var(--bg-main);
  border: 1px solid var(--border-subtle);
  color: var(--text-secondary);
}
.glance-pill.success {
  color: var(--accent-success);
}
.glance-pill.warning {
  color: var(--accent-warning);
  border-color: color-mix(in srgb, var(--accent-warning) 30%, transparent);
}
.glance-pill.clickable {
  cursor: pointer;
  transition: all 0.12s ease;
}
.glance-pill.clickable:hover {
  background: #FEF3C7;
}
.glance-pill.active {
  background: #FEF3C7;
  border-color: var(--accent-warning);
  font-weight: 600;
}
.filter-tag {
  font-size: 10px;
  opacity: 0.75;
  margin-left: 2px;
}
.achievement-pill {
  background: #ECFDF5;
  border-color: #A7F3D0;
  color: #047857;
  font-weight: 600;
}

.metric-selector-wrapper {
  display: flex;
  align-items: center;
  gap: 6px;
}
.metric-label {
  color: var(--text-tertiary);
  font-size: 12px;
}
.metric-select {
  height: 26px;
  padding: 2px 22px 2px 8px;
  font-size: 11px;
  border-radius: 6px;
}

/* ─── 数据表格 ─── */
.ws-grid-container {
  flex: 1;
  min-width: 0;
  overflow: auto;
  position: relative;
}

.impeccable-grid {
  border-collapse: separate;
  border-spacing: 0;
}
.impeccable-grid th {
  position: sticky;
  top: 0;
  z-index: 5;
  background: var(--bg-main);
  box-shadow: inset 0 -1px 0 var(--border-subtle);
}
.impeccable-grid td {
  vertical-align: middle;
}
.th-chk, .td-chk {
  text-align: center !important;
  vertical-align: middle;
}
.custom-checkbox {
  width: 15px;
  height: 15px;
  accent-color: var(--accent-ai);
  cursor: pointer;
}

.req-star {
  color: var(--accent-error);
  margin-left: 2px;
}

.custom-col-th {
  background: color-mix(in srgb, var(--accent-ai) 4%, var(--bg-elevated)) !important;
}
.custom-th-content {
  display: flex;
  align-items: center;
  gap: 4px;
}
.custom-th-name {
  color: var(--accent-ai);
  font-weight: 600;
}
.custom-th-key {
  font-size: 10px;
  opacity: 0.6;
}
.custom-th-del {
  background: none;
  border: none;
  color: var(--accent-error);
  font-size: 10px;
  cursor: pointer;
  padding: 0 3px;
  border-radius: 3px;
}
.custom-th-del:hover {
  background: rgba(239, 68, 68, 0.12);
}

.grid-row {
  transition: background-color 0.1s ease;
}
.grid-row:hover {
  background: var(--row-hover);
}
.grid-row.row-checked {
  background: color-mix(in srgb, var(--accent-ai) 4%, var(--bg-main));
}
.grid-row.row-incomplete {
  background: color-mix(in srgb, var(--accent-warning) 3%, transparent);
}

.td-row-no {
  color: var(--text-tertiary);
  font-weight: 500;
}

.cell-edit {
  cursor: text;
  position: relative;
}
.cell-text {
  min-height: 22px;
  display: flex;
  align-items: center;
  word-break: break-word;
}
.cell-text.placeholder {
  color: var(--accent-warning);
  font-style: italic;
}
.cell-text.empty {
  color: var(--text-tertiary);
}
.cell-text.mono-text {
  font-family: var(--font-mono);
  font-size: 12px;
}

.cell-input {
  width: 100%;
  padding: 5px 8px;
  font: inherit;
  font-size: 13px;
  background: var(--bg-main);
  border: 1px solid var(--accent-ai);
  border-radius: 6px;
  box-shadow: 0 0 0 2px rgba(99, 102, 241, 0.15);
  outline: none;
}
.cell-select {
  height: 26px;
  padding: 2px 20px 2px 6px;
  font-size: 11px;
}

.cell-invalid {
  background: color-mix(in srgb, var(--accent-error) 4%, transparent);
  border-bottom-color: var(--accent-error) !important;
}

.tag-chip {
  display: inline-block;
  padding: 1px 7px;
  border-radius: 999px;
  background: var(--bg-elevated);
  border: 1px solid var(--border-subtle);
  font-size: 11px;
  color: var(--text-secondary);
}
.difficulty-chip {
  display: inline-block;
  padding: 1px 7px;
  border-radius: 4px;
  font-size: 11px;
  font-weight: 500;
}
.diff-简单 { background: #D1FAE5; color: #047857; }
.diff-中等 { background: #FEF3C7; color: #B45309; }
.diff-高 { background: #FEE2E2; color: #B91C1C; }

.empty-placeholder {
  color: var(--text-tertiary);
  font-size: 12px;
}

.td-actions {
  text-align: right;
  white-space: nowrap;
}
.row-actions-cluster {
  display: inline-flex;
  gap: 4px;
  opacity: 0.35;
  transition: opacity 0.12s ease;
}
.grid-row:hover .row-actions-cluster {
  opacity: 1;
}
.action-btn {
  background: none;
  border: none;
  padding: 4px;
  border-radius: 6px;
  color: var(--text-secondary);
  cursor: pointer;
  display: grid;
  place-items: center;
  transition: background-color 0.12s ease, color 0.12s ease;
}
.action-btn:hover {
  background: var(--bg-elevated);
  color: var(--accent-ai);
}
.action-btn.danger:hover {
  background: #FEE2E2;
  color: var(--accent-error);
}

.gold-qa-empty-cell,
.empty-table-cell {
  padding: 48px 16px;
  text-align: center;
  color: var(--text-tertiary);
}
.gold-qa-notice {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 10px;
  color: var(--c-kb);
  font-size: 13px;
}
.empty-table-notice {
  font-size: 13px;
}

/* ─── 悬浮式批量操作坞 ─── */
.floating-batch-dock {
  position: absolute;
  bottom: 24px;
  left: 50%;
  transform: translateX(-50%);
  z-index: 20;
}
.dock-content {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 6px 14px;
  background: var(--text-primary);
  color: var(--bg-main);
  border-radius: 999px;
  box-shadow: 0 10px 30px rgba(0, 0, 0, 0.22);
}
.dock-count-badge {
  font-size: 12px;
  font-weight: 500;
  white-space: nowrap;
}
.dock-divider {
  width: 1px;
  height: 14px;
  background: rgba(255, 255, 255, 0.2);
}
.btn-danger-soft {
  background: rgba(239, 68, 68, 0.2);
  color: #F87171;
  border: none;
}
.btn-danger-soft:hover {
  background: rgba(239, 68, 68, 0.35);
}
.dock-close-btn {
  background: none;
  border: none;
  color: rgba(255, 255, 255, 0.5);
  font-size: 12px;
  cursor: pointer;
  padding: 2px 4px;
}
.dock-close-btn:hover {
  color: #fff;
}

.dock-slide-enter-active,
.dock-slide-leave-active {
  transition: transform 0.2s cubic-bezier(0.16, 1, 0.3, 1), opacity 0.2s cubic-bezier(0.16, 1, 0.3, 1);
}
.dock-slide-enter-from,
.dock-slide-leave-to {
  opacity: 0;
  transform: translate(-50%, 14px) scale(0.96);
}

/* ─── 空态引导 ─── */
.empty-workbench {
  display: grid;
  place-items: center;
  padding: 48px;
}
.empty-workbench-container {
  max-width: 520px;
  text-align: center;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 14px;
}
.empty-workbench-icon {
  width: 80px;
  height: 80px;
  border-radius: 24px;
  background: var(--bg-elevated);
  border: 1px solid var(--border-subtle);
  color: var(--c-datasets);
  display: grid;
  place-items: center;
}
.empty-workbench-container h3 {
  font-size: 18px;
  font-weight: 700;
}
.empty-sub {
  font-size: 13px;
  color: var(--text-secondary);
  line-height: 1.6;
}
.empty-actions-row {
  display: flex;
  gap: 10px;
  flex-wrap: wrap;
  justify-content: center;
  margin-top: 8px;
}

/* ─── 向导通用样式 ─── */
.wizard-steps-header {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 14px;
  margin-bottom: 20px;
  padding-bottom: 16px;
  border-bottom: 1px solid var(--border-subtle);
}
.wizard-step-item {
  display: flex;
  align-items: center;
  gap: 8px;
  color: var(--text-tertiary);
  font-size: 13px;
  font-weight: 500;
}
.wizard-step-item.active {
  color: var(--accent-ai);
  font-weight: 600;
}
.wizard-step-item.done {
  color: var(--accent-success);
}
.step-num {
  width: 22px;
  height: 22px;
  border-radius: 50%;
  background: var(--bg-elevated);
  display: grid;
  place-items: center;
  font-size: 11px;
  font-family: var(--font-mono);
}
.wizard-step-item.active .step-num {
  background: var(--accent-ai);
  color: #fff;
}
.wizard-step-item.done .step-num {
  background: var(--accent-success);
  color: #fff;
}
.step-line {
  width: 48px;
  height: 2px;
  background: var(--border-subtle);
}
.step-line.active {
  background: var(--accent-ai);
}

.mode-chips-row {
  display: flex;
  gap: 8px;
  margin-bottom: 16px;
}
.preview-table-wrapper {
  max-height: 380px;
  overflow-y: auto;
  border: 1px solid var(--border-subtle);
  border-radius: 10px;
}

/* ─── 精致自定义滚动条 ─── */
.custom-scroll::-webkit-scrollbar {
  width: 6px;
  height: 6px;
}
.custom-scroll::-webkit-scrollbar-track {
  background: transparent;
}
.custom-scroll::-webkit-scrollbar-thumb {
  background: rgba(17, 24, 39, 0.12);
  border-radius: 999px;
}
[data-theme='dark'] .custom-scroll::-webkit-scrollbar-thumb {
  background: rgba(255, 255, 255, 0.15);
}
.custom-scroll::-webkit-scrollbar-thumb:hover {
  background: rgba(17, 24, 39, 0.25);
}
[data-theme='dark'] .custom-scroll::-webkit-scrollbar-thumb:hover {
  background: rgba(255, 255, 255, 0.3);
}

/* ─── 减弱动效无障碍支持 (Reduced Motion) ─── */
@media (prefers-reduced-motion: reduce) {
  .dirty-indicator {
    animation: none;
  }
  .dock-slide-enter-active,
  .dock-slide-leave-active {
    transition: none;
  }
  .ft-node,
  .action-btn,
  .save-btn,
  .btn-xs {
    transition: none;
  }
}

/* ─── 响应式设计 ─── */
@media (max-width: 900px) {
  .datasets-workbench {
    height: auto;
    min-height: calc(100dvh - var(--topbar-h) - 24px);
  }
  .ft-layout {
    grid-template-columns: 1fr;
    height: auto;
    overflow: visible;
  }
  .ft-sidebar {
    max-height: 260px;
    border-right: 0;
    border-bottom: 1px solid var(--border-subtle);
  }
  .ft-resizer {
    display: none;
  }
  .workspace-main {
    min-height: 640px;
  }
  .action-btn {
    padding: 8px;
    min-width: 36px;
    min-height: 36px;
  }
}
</style>
