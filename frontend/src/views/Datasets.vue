<template>
  <div class="datasets-workbench" @keydown="onWorkbenchKeydown">
    <!-- RAG 模式提示面板 -->
    <div v-if="modeStore.mode === 'rag'" class="mode-context-panel">
      <div class="mode-icon-wrapper">
        <svg width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">
          <path d="M4 19.5v-15A2.5 2.5 0 0 1 6.5 2H20v20H6.5a2.5 2.5 0 0 1-2.5-2.5Z" />
          <path d="M6 6h10" />
          <path d="M6 10h10" />
        </svg>
      </div>
      <h2>RAG 评测请使用知识库与黄金 QA</h2>
      <p>基准数据集主要服务于大模型通用能力评测与对比。当前模式下，请前往知识库工作台管理文档分块、检索配置与黄金 QA 资产。</p>
      <router-link to="/kb" class="btn btn-primary btn-md">进入知识库工作台 →</router-link>
    </div>

    <div v-else class="nordic-layout" :style="{ '--tree-w': treeWidth + 'px' }">
      <!-- ─── 左侧：资源目录树侧边栏 ─── -->
      <aside class="nordic-sidebar">
        <div class="sidebar-header">
          <div class="sidebar-title-row">
            <div class="sidebar-title">
              <svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="title-icon">
                <path d="M20 20a2 2 0 0 0 2-2V8a2 2 0 0 0-2-2h-7.9a2 2 0 0 1-1.69-.9L9.6 3.9A2 2 0 0 0 7.93 3H4a2 2 0 0 0-2 2v13a2 2 0 0 0 2 2Z" />
              </svg>
              <span>数据集资源</span>
            </div>
            <div class="sidebar-actions">
              <button class="btn btn-ghost-subtle btn-xs" title="通过场景或模板自动合成数据集" aria-label="自动合成新数据集" @click="openAiGenDrawer">
                + 合成
              </button>
              <button class="btn btn-ghost-subtle btn-xs" title="上传 JSONL / CSV 数据集文件" aria-label="上传数据集文件" @click="openUploadModal(null)">
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
          <div class="search-box">
            <svg class="search-icon" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
              <circle cx="11" cy="11" r="8" />
              <line x1="21" y1="21" x2="16.65" y2="16.65" />
            </svg>
            <input v-model="treeSearch" class="search-input" placeholder="搜索数据集 / 黄金 QA..." aria-label="搜索数据集或黄金QA" />
            <button v-if="treeSearch" class="clear-search-btn" aria-label="清空搜索" @click="treeSearch = ''">✕</button>
          </div>
        </div>

        <!-- 目录树内容区 -->
        <div class="tree-content custom-scroll">
          <div v-for="folder in filteredFolders" :key="folder.id" class="folder-group" :data-fid="folder.id">
            <!-- 文件夹节点 -->
            <div
              class="tree-node folder-node"
              :class="{ open: folder.open }"
              @click="folder.open = !folder.open"
              @contextmenu.prevent.stop="openCtxMenu($event, 'folder', folder.id)"
            >
              <span class="chevron-icon" :class="{ rotated: folder.open }">
                <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round">
                  <polyline points="9 18 15 12 9 6" />
                </svg>
              </span>
              <svg class="folder-icon" width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">
                <path v-if="folder.open" d="m6 14 1.5-2.9A2 2 0 0 1 9.24 10H20a2 2 0 0 1 1.94 2.5l-1.54 6a2 2 0 0 1-1.95 1.5H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h3.9a2 2 0 0 1 1.69.9l.81 1.2a2 2 0 0 0 1.67.9H18a2 2 0 0 1 2 2v2" />
                <path v-else d="M20 20a2 2 0 0 0 2-2V8a2 2 0 0 0-2-2h-7.9a2 2 0 0 1-1.69-.9L9.6 3.9A2 2 0 0 0 7.93 3H4a2 2 0 0 0-2 2v13a2 2 0 0 0 2 2Z" />
              </svg>
              <span class="node-name">{{ folder.name }}</span>
              <span class="node-badge">{{ folder.items.length }}</span>
            </div>

            <!-- 文件夹子项目 -->
            <div v-if="folder.open" class="folder-children">
              <div
                v-for="item in folder.items"
                :key="item.id"
                class="tree-node file-node"
                :class="{ active: activeDatasetId === item.id }"
                :title="`${item.name} · v${item.version}`"
                @click="requestSelectDataset(item.id)"
                @contextmenu.prevent.stop="openCtxMenu($event, 'file', item.id)"
              >
                <span v-if="item.isGoldQa" class="file-icon gold-qa" title="黄金 QA">
                  <svg width="14" height="14" viewBox="0 0 24 24" fill="currentColor">
                    <polygon points="12 2 15.09 8.26 22 9.27 17 14.14 18.18 21.02 12 17.77 5.82 21.02 7 14.14 2 9.27 8.91 8.26 12 2" />
                  </svg>
                </span>
                <span v-else class="file-icon dataset" title="基准数据集">
                  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                    <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
                    <polyline points="14 2 14 8 20 8" />
                  </svg>
                </span>
                <span class="node-name">{{ item.name }}</span>
                <span class="version-badge">v{{ item.version }}</span>
                <span v-if="item.pending_complete_count > 0" class="pending-dot" :title="`${item.pending_complete_count} 行待补全`"></span>
              </div>
            </div>
          </div>

          <div v-if="!filteredFolders.length" class="tree-empty">
            <svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" class="empty-icon">
              <circle cx="11" cy="11" r="8" />
              <line x1="21" y1="21" x2="16.65" y2="16.65" />
            </svg>
            <p>{{ treeSearch.trim() ? `无匹配结果「${treeSearch.trim()}」` : '暂无数据集，点击上方「+ 合成」或「上传」开始' }}</p>
          </div>
        </div>

        <!-- 调宽手柄 -->
        <div
          class="sidebar-resizer"
          :class="{ active: treeResizing }"
          title="拖拽调整侧栏宽度 · 双击复位为 280px"
          @mousedown="startTreeResize"
          @dblclick="resetTreeWidth"
        >
          <div class="resizer-bar"></div>
        </div>
      </aside>

      <!-- ─── 右侧：主数据工作台 ─── -->
      <main v-if="currentItem" class="nordic-main">
        <!-- 1. 顶栏：层级分明的操作区与检索 -->
        <div class="main-toolbar">
          <div class="toolbar-default">
            <div class="toolbar-title-group">
              <div class="title-row">
                <span class="main-dataset-title">{{ currentItem.name }}</span>
                <span class="version-tag">v{{ currentItem.version }}</span>
                <span class="asset-type-badge" :class="isGoldQaActive ? 'type-gold' : 'type-dataset'">
                  {{ isGoldQaActive ? '黄金 QA' : '基准数据集' }}
                </span>
                <span v-if="!isGoldQaActive && currentDataset && currentDataset.pending_complete_count > 0" class="status-badge-amber">
                  {{ currentDataset.pending_complete_count }} 行待补全
                </span>
              </div>
              <div class="breadcrumb-row">
                <span>{{ isGoldQaActive ? '知识库资产' : '数据集资源' }}</span>
                <span class="sep">/</span>
                <span class="cur">{{ currentItem.name }}</span>
              </div>
            </div>

            <!-- 表格内即时搜索过滤框 (Instant Grid Filter) -->
            <div v-if="!isGoldQaActive" class="table-search-box">
              <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" class="table-search-icon">
                <circle cx="11" cy="11" r="8" /><line x1="21" y1="21" x2="16.65" y2="16.65" />
              </svg>
              <input v-model="gridSearch" class="table-search-input" placeholder="在当前表中极速筛选 (⌘F)..." aria-label="在当前表中极速筛选" />
              <span v-if="gridSearch" class="grid-search-count mono">{{ displayedRows.length }}/{{ sampleRows.length }}</span>
              <button v-if="gridSearch" class="clear-search-btn" aria-label="清空表内搜索" @click="gridSearch = ''">✕</button>
            </div>

            <div class="grow"></div>

            <!-- 右侧操作组（操作金字塔：高频主操作 -> 中频操作 -> 保存 -> 更多收纳） -->
            <div v-if="isGoldQaActive" class="toolbar-action-group">
              <button class="btn btn-primary btn-md" @click="openRagDrawer">
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                  <polygon points="5 3 19 12 5 21 5 3" />
                </svg>
                发起 RAG 评测
              </button>
            </div>

            <div v-else class="toolbar-action-group">
              <!-- 中频操作组 -->
              <div class="action-btn-group">
                <button class="btn btn-secondary btn-md" aria-label="新增表格行" @click="addRow">
                  <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="12" y1="5" x2="12" y2="19" /><line x1="5" y1="12" x2="19" y2="12" /></svg>
                  新增行
                </button>
                <button class="btn btn-secondary btn-md" aria-label="新增自定义扩展列" @click="openAddColModal">
                  <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="12" y1="5" x2="12" y2="19" /><line x1="5" y1="12" x2="19" y2="12" /></svg>
                  新增列
                </button>
                <button class="btn btn-secondary btn-md" aria-label="打开数据自动合成抽屉" @click="openAiGenDrawer">
                  数据合成向导
                </button>
              </div>

              <!-- 保存修改按钮 -->
              <button
                class="btn btn-save btn-md"
                :class="{ dirty: hasUnsavedChanges, saved: justSaved }"
                :disabled="!hasUnsavedChanges || savingRows"
                title="快捷键 Ctrl/⌘ + S"
                aria-label="保存当前修改"
                @click="persistRows"
              >
                <span v-if="justSaved" class="saved-icon">✓</span>
                {{ savingRows ? '保存中…' : justSaved ? '已保存' : '保存修改' }}
                <kbd class="shortcut-key">⌘S</kbd>
              </button>

              <!-- 高频主操作 CTA -->
              <button class="btn btn-primary btn-md primary-cta" aria-label="发起基准评测任务" @click="openLaunchDrawer">
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                  <polygon points="5 3 19 12 5 21 5 3" />
                </svg>
                发起基准评测
              </button>

              <!-- 更多低频操作收纳至下拉 -->
              <n-dropdown :options="moreMenuOptions" trigger="click" @select="handleMoreMenuSelect">
                <button class="btn btn-ghost-subtle btn-md btn-icon-only" title="更多数据操作" aria-label="更多操作">
                  <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                    <circle cx="12" cy="12" r="1"></circle>
                    <circle cx="19" cy="12" r="1"></circle>
                    <circle cx="5" cy="12" r="1"></circle>
                  </svg>
                </button>
              </n-dropdown>
            </div>
          </div>
        </div>

        <!-- 2. 数据指标与交互式胶囊筛选条 -->
        <div class="metrics-strip">
          <div class="strip-left">
            <span class="strip-label">样本筛选:</span>
            <div class="filter-pills-bar" v-if="!isGoldQaActive">
              <button
                class="filter-pill"
                :class="{ active: filterPendingMode === 'all' }"
                @click="filterPendingMode = 'all'"
              >
                全部 <b class="pill-num">{{ sampleRows.length }}</b>
              </button>
              <button
                class="filter-pill pill-clean"
                :class="{ active: filterPendingMode === 'clean' }"
                @click="filterPendingMode = 'clean'"
              >
                达标 <b class="pill-num">{{ sampleRows.length - pendingCount }}</b>
              </button>
              <button
                v-if="pendingCount > 0"
                class="filter-pill pill-amber"
                :class="{ active: filterPendingMode === 'pending' }"
                @click="filterPendingMode = filterPendingMode === 'pending' ? 'all' : 'pending'"
              >
                待补全 <b class="pill-num">{{ pendingCount }}</b>
              </button>
            </div>
            <span v-else class="strip-text mono">{{ activeGoldQa?.row_count || 0 }} 行</span>

            <template v-if="!isGoldQaActive">
              <span class="strip-divider"></span>
              <span v-if="pendingCount === 0" class="status-indicator-success">
                ✓ 100% 格式达标
              </span>
              <span v-else class="status-indicator-warning">
                需补全 {{ pendingCount }} 行样本
              </span>

              <template v-if="customCols.length">
                <span class="strip-divider"></span>
                <span class="strip-text">扩展列: {{ customCols.length }}</span>
              </template>
            </template>
          </div>

          <div class="grow"></div>

          <!-- 键盘流提示 (可悬停查看) -->
          <div class="keyboard-flow-hint" title="支持键盘方向键与快捷键无障碍操作">
            <span class="kbd-hint"><kbd>↑↓←→</kbd> 移动</span>
            <span class="kbd-hint"><kbd>Enter</kbd> 编辑</span>
            <span class="kbd-hint"><kbd>Space</kbd> 勾选</span>
          </div>

          <span class="strip-divider"></span>

          <!-- 主评分指标选择器 -->
          <div v-if="!isGoldQaActive && currentDataset" class="metric-control">
            <span class="metric-label">主评分指标:</span>
            <select v-model="currentDataset.metric" class="metric-select" aria-label="选择主评分指标" @change="saveMetric">
              <option value="contain">Contain (包含匹配)</option>
              <option value="exact">Exact (完全一致)</option>
              <option value="regex">Regex (正则表达式)</option>
              <option value="rouge_l">ROUGE-L (最长公共子序列)</option>
              <option value="bleu">BLEU (自然语言平滑)</option>
            </select>
          </div>
        </div>

        <!-- 3. 数据表格：分页网格 + 居中自定义多选框 -->
        <div ref="tableContainerRef" class="table-container custom-scroll" tabindex="0">
          <table class="nordic-table">
            <thead>
              <tr>
                <th class="th-chk" style="width: 48px" title="全选当前页所有行" @click.stop="toggleCurrentPageRowsDirect">
                  <div class="clean-chk-box" :class="{ checked: isCurrentPageAllChecked }" role="checkbox" :aria-checked="isCurrentPageAllChecked">
                    <svg v-if="isCurrentPageAllChecked" class="chk-icon" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="#FFFFFF" stroke-width="3.2" stroke-linecap="round" stroke-linejoin="round">
                      <polyline points="20 6 9 17 4 12" />
                    </svg>
                  </div>
                </th>
                <th style="width: 64px">#</th>
                <th style="min-width: 260px">测试问句 (Question) <span class="req-star">*</span></th>
                <th style="min-width: 290px">标准参考答案 (Reference) <span class="req-star">*</span></th>
                <th style="min-width: 180px">{{ isGoldQaActive ? '预期文档 IDs' : '上下文 (Context)' }}</th>
                <template v-if="!isGoldQaActive">
                  <th style="min-width: 120px">业务标签</th>
                  <th style="min-width: 90px">难度</th>
                </template>
                <th v-for="col in customCols" :key="col.key" class="custom-th" style="min-width: 120px">
                  <div class="th-flex">
                    <span>{{ col.name }}</span>
                    <button class="th-del-btn" title="删除该列" :aria-label="`删除扩展列 ${col.name}`" @click.stop="removeCustomCol(col.key)">✕</button>
                  </div>
                </th>
                <th style="width: 92px">状态</th>
                <th style="width: 80px; text-align: right">操作</th>
              </tr>
            </thead>

            <tbody>
              <!-- 黄金 QA 提示说明 -->
              <tr v-if="isGoldQaActive">
                <td :colspan="(isGoldQaActive ? 7 : 9) + customCols.length" class="empty-cell">
                  <div class="empty-message">
                    <span>黄金 QA「{{ currentItem?.name }}」共 {{ activeGoldQa?.row_count || 0 }} 行，可在知识库工作台进行管理。</span>
                  </div>
                </td>
              </tr>

              <!-- 当前页切片数据行 -->
              <tr
                v-for="(r, pageIdx) in pagedRows"
                v-else
                :key="r.row_no"
                class="data-row"
                :class="{
                  'row-checked': r.checked,
                  'row-incomplete': !r.q.trim() || !r.r.trim(),
                  'row-focused': focusedCell?.rowIdx === getDisplayedIndex(r)
                }"
                @contextmenu.prevent="openCtxMenu($event, 'row', '', getOriginalRowIndex(r))"
                @dblclick="openRowEditModal(getOriginalRowIndex(r))"
              >
                <!-- 居中自定义多选框列 (支持直接点击与 Shift 连选) -->
                <td class="td-chk" :class="{ 'cell-cursor': isCellCursor(r, 'chk') }" @click.stop="handleRowCheckClick(r, $event)">
                  <div class="clean-chk-box" :class="{ checked: r.checked }" :title="`勾选第 ${r.row_no} 行（支持 Shift 连选）`" role="checkbox" :aria-checked="r.checked">
                    <svg v-if="r.checked" class="chk-icon" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="#FFFFFF" stroke-width="3.2" stroke-linecap="round" stroke-linejoin="round">
                      <polyline points="20 6 9 17 4 12" />
                    </svg>
                  </div>
                </td>

                <!-- 行号 -->
                <td class="mono td-num" :class="{ 'cell-cursor': isCellCursor(r, 'row_no') }" @click="setCellCursor(r, 'row_no')">
                  {{ r.row_no }}
                </td>

                <!-- 测试问句 (14px 舒适字阶) -->
                <td class="cell-edit" :class="{ 'cell-invalid': !r.q.trim(), 'cell-cursor': isCellCursor(r, 'q') }" @click="handleCellClick(r, 'q')">
                  <input
                    v-if="editingCell?.row === r && editingCell?.field === 'q'"
                    v-model="r.q"
                    class="inline-input"
                    placeholder="输入测试问题..."
                    :aria-label="`编辑第 ${r.row_no} 行测试问题`"
                    autofocus
                    @blur="finishEditing"
                    @keyup.enter="finishEditing"
                    @keyup.esc="cancelEditing"
                  />
                  <div v-else class="cell-content primary-text" :class="{ empty: !r.q.trim() }" v-html="highlightMatch(r.q || '（空问句 · 点击录入）')"></div>
                </td>

                <!-- 参考答案 (14px 舒适字阶) -->
                <td class="cell-edit" :class="{ 'cell-invalid': !r.r.trim(), 'cell-cursor': isCellCursor(r, 'r') }" @click="handleCellClick(r, 'r')">
                  <input
                    v-if="editingCell?.row === r && editingCell?.field === 'r'"
                    v-model="r.r"
                    class="inline-input"
                    placeholder="输入标准答案..."
                    :aria-label="`编辑第 ${r.row_no} 行标准答案`"
                    autofocus
                    @blur="finishEditing"
                    @keyup.enter="finishEditing"
                    @keyup.esc="cancelEditing"
                  />
                  <div v-else class="cell-content" :class="{ empty: !r.r.trim() }" v-html="highlightMatch(r.r || '（空答案 · 点击录入）')"></div>
                </td>

                <!-- 上下文注入 -->
                <td class="cell-edit" :class="{ 'cell-cursor': isCellCursor(r, 'c') }" @click="handleCellClick(r, 'c')">
                  <input
                    v-if="editingCell?.row === r && editingCell?.field === 'c'"
                    v-model="r.c"
                    class="inline-input"
                    placeholder="注入 Context..."
                    :aria-label="`编辑第 ${r.row_no} 行上下文`"
                    autofocus
                    @blur="finishEditing"
                    @keyup.enter="finishEditing"
                    @keyup.esc="cancelEditing"
                  />
                  <div v-else class="cell-content mono-sm" :class="{ placeholder: !r.c }" v-html="highlightMatch(r.c || '—')"></div>
                </td>

                <!-- 标签 -->
                <td class="cell-edit" :class="{ 'cell-cursor': isCellCursor(r, 'tags') }" @click="handleCellClick(r, 'tags')">
                  <input
                    v-if="editingCell?.row === r && editingCell?.field === 'tags'"
                    v-model="r.tags"
                    class="inline-input"
                    placeholder="业务标签..."
                    :aria-label="`编辑第 ${r.row_no} 行标签`"
                    autofocus
                    @blur="finishEditing"
                    @keyup.enter="finishEditing"
                    @keyup.esc="cancelEditing"
                  />
                  <div v-else class="cell-content">
                    <span v-if="r.tags" class="tag-pill" v-html="highlightMatch(r.tags)"></span>
                    <span v-else class="placeholder">常规</span>
                  </div>
                </td>

                <!-- 难度 -->
                <td class="cell-edit" :class="{ 'cell-cursor': isCellCursor(r, 'difficulty') }" @click="handleCellClick(r, 'difficulty')">
                  <select
                    v-if="editingCell?.row === r && editingCell?.field === 'difficulty'"
                    v-model="r.difficulty"
                    class="inline-select"
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
                  <div v-else class="cell-content">
                    <span class="diff-badge" :class="`diff-${r.difficulty}`">
                      {{ r.difficulty || '简单' }}
                    </span>
                  </div>
                </td>

                <!-- 自定义扩展列 -->
                <td v-for="col in customCols" :key="col.key" class="cell-edit" :class="{ 'cell-cursor': isCellCursor(r, col.key) }" @click="handleCellClick(r, col.key)">
                  <input
                    v-if="editingCell?.row === r && editingCell?.field === col.key"
                    v-model="r.extras[col.key]"
                    class="inline-input"
                    :placeholder="`输入 ${col.name}...`"
                    :aria-label="`编辑第 ${r.row_no} 行 ${col.name}`"
                    autofocus
                    @blur="finishEditing"
                    @keyup.enter="finishEditing"
                    @keyup.esc="cancelEditing"
                  />
                  <div v-else class="cell-content" :class="{ placeholder: !r.extras[col.key] }">
                    {{ r.extras[col.key] || '—' }}
                  </div>
                </td>

                <!-- 校验状态 -->
                <td>
                  <span v-if="!r.q.trim() || !r.r.trim()" class="status-tag-amber" title="缺少问句或答案">待补全</span>
                  <span v-else class="status-tag-green">达标</span>
                </td>

                <!-- 操作区 -->
                <td class="td-actions">
                  <div class="action-links">
                    <button class="icon-link" title="详细编辑" :aria-label="`详细编辑第 ${r.row_no} 行`" @click.stop="openRowEditModal(getOriginalRowIndex(r))">
                      <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7" /><path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z" /></svg>
                    </button>
                    <button class="icon-link danger" title="删除行" :aria-label="`删除第 ${r.row_no} 行`" @click.stop="deleteRow(getOriginalRowIndex(r))">
                      <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="3 6 5 6 21 6" /><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2" /></svg>
                    </button>
                  </div>
                </td>
              </tr>

              <!-- 空列表提示 -->
              <tr v-if="!displayedRows.length">
                <td :colspan="(isGoldQaActive ? 7 : 9) + customCols.length" class="empty-cell">
                  <div class="empty-message">
                    <template v-if="gridSearch.trim() || filterPendingMode !== 'all'">
                      <p style="margin-bottom: 8px;">未找到符合条件的样本行（当前检索：{{ gridSearch.trim() ? `「${gridSearch.trim()}」` : '' }}{{ filterPendingMode !== 'all' ? ` [${filterPendingMode === 'pending' ? '仅看待补全' : '仅看达标'}]` : '' }}）。</p>
                      <button class="btn btn-secondary btn-sm" @click="clearAllFilters">
                        清空搜索与筛选条件
                      </button>
                    </template>
                    <span v-else>当前数据集暂无样本行，点击上方「新增行」或「数据合成向导」开始录入。</span>
                  </div>
                </td>
              </tr>
            </tbody>
          </table>
        </div>

        <!-- 4. 底部固定分页工具栏 (Table Pagination Bar) -->
        <div v-if="!isGoldQaActive && sampleRows.length > 0" class="table-pagination-bar">
          <div class="pagination-info">
            <span class="pagination-total">
              共 <strong class="mono">{{ displayedRows.length }}</strong> 条样本
              <span class="pagination-pages mono">（第 {{ page }} / {{ totalPages }} 页）</span>
            </span>
            <span v-if="gridSearch.trim() || filterPendingMode !== 'all'" class="pagination-filter-tag">
              已从全部 {{ sampleRows.length }} 条中过滤
            </span>
            <span v-if="selectedCount > 0" class="pagination-selection-tag">
              已勾选 {{ selectedCount }} 条
            </span>
          </div>
          <div class="pagination-controls">
            <n-pagination
              v-model:page="page"
              v-model:page-size="pageSize"
              :item-count="displayedRows.length"
              :page-sizes="[10, 20, 50, 100]"
              show-size-picker
              show-quick-jumper
            />
          </div>
        </div>

        <!-- 5. 底部浮动批量操作栏 (Floating Action Dock) -->
        <transition name="slide-up">
          <div v-if="selectedCount > 0" class="floating-batch-dock">
            <div class="batch-dock-info">
              <span class="batch-dock-badge">{{ selectedCount }}</span>
              <span class="batch-dock-text">已选择 / 筛选共 {{ displayedRows.length }} 行</span>
            </div>
            <div class="batch-dock-actions">
              <button
                v-if="selectedCount < displayedRows.length"
                class="btn btn-ghost btn-sm"
                @click="checkAllDisplayedRows"
              >
                全选所有筛选行 ({{ displayedRows.length }})
              </button>
              <button class="btn btn-secondary btn-sm" @click="exportSelectedRows">
                <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" /><polyline points="7 10 12 15 17 10" /><line x1="12" y1="15" x2="12" y2="3" /></svg>
                导出选中 JSONL
              </button>
              <button class="btn btn-danger btn-sm" @click="batchDeleteRows">
                批量删除 ({{ selectedCount }})
              </button>
              <button class="btn btn-ghost btn-sm" @click="uncheckAllRows">
                取消选择
              </button>
            </div>
          </div>
        </transition>
      </main>

      <!-- 空态页面 (精致矢量引导态) -->
      <main v-else class="nordic-main empty-main">
        <div class="empty-box">
          <div class="empty-icon-wrapper">
            <svg width="44" height="44" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">
              <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
              <polyline points="14 2 14 8 20 8" />
              <line x1="12" y1="18" x2="12" y2="12" />
              <line x1="9" y1="15" x2="15" y2="15" />
            </svg>
          </div>
          <h3>尚未选择或创建数据集</h3>
          <p class="empty-desc">您可以上传现有的 JSONL / CSV 评测样本，或使用 AI 数据合成向导智能拓展测试问答。</p>
          <div class="empty-buttons">
            <button class="btn btn-primary btn-md primary-cta" @click="createEmptyDataset(() => openAiGenDrawer())">
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 2v4M12 18v4M4.93 4.93l2.83 2.83M16.24 16.24l2.83 2.83M2 12h4M18 12h4M4.93 19.07l2.83-2.83M16.24 7.76l2.83-2.83"/></svg>
              AI 数据合成向导
            </button>
            <button class="btn btn-secondary btn-md" @click="openUploadModal(null)">
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" /><polyline points="17 8 12 3 7 8" /><line x1="12" y1="3" x2="12" y2="15" /></svg>
              上传已有文件
            </button>
            <button class="btn btn-ghost btn-md" @click="createEmptyDataset()">
              + 新建空数据集
            </button>
          </div>
        </div>
      </main>
    </div>

    <!-- ─── 右侧滑出抽屉：数据自动合成向导 ─── -->
    <n-drawer v-model:show="aiGen.show" :width="drawerWidth" placement="right">
      <n-drawer-content title="数据集自动合成向导" closable>
        <div class="drawer-step-bar">
          <div class="step-badge" :class="{ active: aiGen.step === 1, done: aiGen.step === 2 }">
            <span class="step-idx">1</span>
            <span>合成模式与参数配置</span>
          </div>
          <span class="step-divider-line"></span>
          <div class="step-badge" :class="{ active: aiGen.step === 2 }">
            <span class="step-idx">2</span>
            <span>候选样本审核与导入</span>
          </div>
        </div>

        <div v-show="aiGen.step === 1" class="drawer-body">
          <div class="field">
            <label class="field-label">合成模式</label>
            <div class="tab-pill-group">
              <button class="tab-pill" :class="{ active: aiGen.mode === 'scene' }" @click="aiGen.mode = 'scene'">业务场景定向合成</button>
              <button class="tab-pill" :class="{ active: aiGen.mode === 'seed' }" @click="aiGen.mode = 'seed'">已有样本扩写</button>
              <button class="tab-pill" :class="{ active: aiGen.mode === 'doc' }" @click="aiGen.mode = 'doc'">需求文档/OpenAPI 提取</button>
            </div>
          </div>

          <div v-show="aiGen.mode === 'scene'">
            <div class="field">
              <label class="field-label">业务场景预设</label>
              <n-select v-model:value="aiGen.preset" :options="presetOptions" @update:value="onPresetChange" />
            </div>
            <div class="field">
              <label class="field-label">评估目标与边界描述 (Instruction) <span class="req">*</span></label>
              <n-input v-model:value="aiGen.instruction" type="textarea" :autosize="{ minRows: 3, maxRows: 5 }" placeholder="详述测试重点、边界限制或关注的能力维度..." />
            </div>
          </div>

          <div v-show="aiGen.mode === 'seed'">
            <div class="field">
              <label class="field-label">选择种子样本</label>
              <n-select v-model:value="aiGen.seedSample" :options="seedOptions" placeholder="选择一条已有样本作为扩展基准" />
            </div>
            <div class="field">
              <label class="field-label">扩写维度</label>
              <n-checkbox-group v-model:value="aiGen.dims">
                <div class="row wrap" style="gap: 16px">
                  <n-checkbox value="synonym">同义改写</n-checkbox>
                  <n-checkbox value="constraint">前置约束增加</n-checkbox>
                  <n-checkbox value="boundary">边界异常提问</n-checkbox>
                </div>
              </n-checkbox-group>
            </div>
          </div>

          <div v-show="aiGen.mode === 'doc'">
            <div class="field">
              <label class="field-label">需求文档 / OpenAPI 接口定义</label>
              <n-input v-model:value="aiGen.docText" class="mono" type="textarea" :autosize="{ minRows: 4, maxRows: 8 }" placeholder="粘贴接口定义或需求文本，系统将自动抽取测试问答对及上下文..." />
            </div>
          </div>

          <div class="divider-title">运行参数与生成规模</div>
          <div class="form-row-3">
            <div class="field">
              <label class="field-label">生成规模 (<b class="mono">{{ aiGen.rowCount }}</b> 行)</label>
              <n-slider v-model:value="aiGen.rowCount" :min="3" :max="25" :step="1" />
            </div>
            <div class="field">
              <label class="field-label">推理模型</label>
              <n-select
                v-model:value="aiGen.model"
                :options="[
                  { label: 'gpt-4.1 (推荐)', value: 'gpt-4.1' },
                  { label: 'claude-sonnet-4.5', value: 'claude-sonnet-4.5' },
                  { label: 'o4 (深度推理)', value: 'o4' },
                ]"
              />
            </div>
            <div class="field">
              <label class="field-label">发散度 Temperature</label>
              <n-select
                v-model:value="aiGen.temperature"
                :options="[
                  { label: '0.2 (严谨收敛)', value: 0.2 },
                  { label: '0.5 (标准)', value: 0.5 },
                  { label: '0.8 (发散)', value: 0.8 },
                ]"
              />
            </div>
          </div>

          <div class="field">
            <label class="field-label">生成字段目标</label>
            <div class="row wrap" style="gap: 16px; font-size: 13.5px">
              <n-checkbox v-model:checked="aiGen.genRef">标准答案 Reference</n-checkbox>
              <n-checkbox v-model:checked="aiGen.genCtx">注入上下文 Context</n-checkbox>
              <n-checkbox v-model:checked="aiGen.genTags">业务标签 Tags</n-checkbox>
            </div>
          </div>
        </div>

        <div v-show="aiGen.step === 2" class="drawer-body">
          <div class="row-between mb8">
            <span class="bold" style="font-size: 13.5px">候选项列表 (共 {{ aiGen.candidates.length }} 条，可就地微调)</span>
            <button class="link-btn" @click="toggleAllCandidates">全选 / 全不选</button>
          </div>
          <div class="preview-box custom-scroll">
            <table class="nordic-table preview-table">
              <thead>
                <tr>
                  <th class="th-chk" style="width: 40px" title="全选 / 全不选" @click.stop="toggleAllCandidates">
                    <div class="clean-chk-box" :class="{ checked: aiAllSelected }">
                      <svg v-if="aiAllSelected" class="chk-icon" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="#FFFFFF" stroke-width="3.2" stroke-linecap="round" stroke-linejoin="round">
                        <polyline points="20 6 9 17 4 12" />
                      </svg>
                    </div>
                  </th>
                  <th style="min-width: 180px">测试问句</th>
                  <th style="min-width: 200px">标准参考答案</th>
                  <th style="width: 80px">难度</th>
                  <th style="width: 50px">操作</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="(cand, ci) in aiGen.candidates" :key="ci">
                  <td class="td-chk" @click.stop="cand.selected = !cand.selected">
                    <div class="clean-chk-box" :class="{ checked: cand.selected }">
                      <svg v-if="cand.selected" class="chk-icon" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="#FFFFFF" stroke-width="3.2" stroke-linecap="round" stroke-linejoin="round">
                        <polyline points="20 6 9 17 4 12" />
                      </svg>
                    </div>
                  </td>
                  <td><input v-model="cand.q" class="inline-input-clean" /></td>
                  <td><input v-model="cand.r" class="inline-input-clean" /></td>
                  <td><span class="diff-badge diff-中等">{{ cand.difficulty }}</span></td>
                  <td><button class="link-btn danger" @click="aiGen.candidates.splice(ci, 1)">移除</button></td>
                </tr>
              </tbody>
            </table>
          </div>
        </div>

        <template #footer>
          <div class="drawer-footer-row">
            <n-button v-if="aiGen.step === 2" @click="aiGen.step = 1">← 返回调整参数</n-button>
            <span v-else></span>
            <div class="row" style="gap: 8px">
              <n-button @click="aiGen.show = false">取消</n-button>
              <n-button v-if="aiGen.step === 1" type="primary" :loading="aiGen.generating" @click="runAiGenerate">
                {{ aiGen.generating ? '正在推理合成中…' : '生成候选样本 →' }}
              </n-button>
              <n-button v-else type="primary" :disabled="aiSelectedCount === 0" @click="commitAiCandidates">
                采纳导入数据集 ({{ aiSelectedCount }} 条)
              </n-button>
            </div>
          </div>
        </template>
      </n-drawer-content>
    </n-drawer>

    <!-- 弹窗与抽屉组件 (全居中显示) -->
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

    <n-modal v-model:show="rowEdit.show" preset="card" :title="`编辑样本 #${rowEdit.rowNo}`" class="center-dialog-card" style="width: 660px; max-width: calc(100vw - 32px)">
      <div class="field">
        <label class="field-label">测试问句 (Question) <span class="req">*</span></label>
        <n-input v-model:value="rowEdit.q" type="textarea" :autosize="{ minRows: 3, maxRows: 6 }" placeholder="请输入测试问句" />
      </div>
      <div class="field">
        <label class="field-label">标准参考答案 (Reference) <span class="req">*</span></label>
        <n-input v-model:value="rowEdit.r" type="textarea" :autosize="{ minRows: 3, maxRows: 6 }" placeholder="请输入标准参考答案" />
      </div>
      <div class="field">
        <label class="field-label">上下文注入 (Context)</label>
        <n-input v-model:value="rowEdit.c" class="mono" type="textarea" :autosize="{ minRows: 3, maxRows: 6 }" placeholder="可选粘贴上下文或背景资料..." />
      </div>
      <template v-if="customCols.length">
        <div class="divider-title">自定义扩展字段</div>
        <div class="form-row">
          <div v-for="col in customCols" :key="col.key" class="field">
            <label class="field-label">{{ col.name }} ({{ col.key }})</label>
            <n-input v-model:value="rowEdit.extras[col.key]" />
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

    <n-modal v-model:show="addCol.show" preset="card" title="新增数据扩展列" class="center-dialog-card" style="width: 440px; max-width: calc(100vw - 32px)">
      <div class="field">
        <label class="field-label">字段 Key (英文字母/下划线) <span class="req">*</span></label>
        <n-input v-model:value="addCol.key" class="mono" placeholder="如 category, topic" />
      </div>
      <div class="field">
        <label class="field-label">列显示名称 <span class="req">*</span></label>
        <n-input v-model:value="addCol.name" placeholder="如 业务分类, 主题" />
      </div>
      <template #footer>
        <div style="display: flex; justify-content: flex-end; gap: 8px">
          <n-button @click="addCol.show = false">取消</n-button>
          <n-button type="primary" @click="confirmAddCol">确认添加</n-button>
        </div>
      </template>
    </n-modal>

    <n-modal v-model:show="aiFill.show" preset="card" :title="`自动补全缺失字段 (${pendingCount} 行)`" class="center-dialog-card" style="width: 540px; max-width: calc(100vw - 32px)">
      <p class="small" style="margin: 0 0 12px; color: var(--text-secondary); font-size: 13px">
        系统将结合已有上下文及同数据集样本规律自动推导补全缺失的问句或标准答案。
      </p>
      <div class="field">
        <label class="field-label">补全提示词引导 (Instruction)</label>
        <n-input v-model:value="aiFill.instruction" type="textarea" :autosize="{ minRows: 2, maxRows: 4 }" />
      </div>
      <div class="form-row">
        <div class="field">
          <label class="field-label">补全范围</label>
          <div class="row" style="gap: 14px; font-size: 13.5px; margin-top: 4px">
            <n-checkbox v-model:checked="aiFill.scopeQ">填补缺失问句</n-checkbox>
            <n-checkbox v-model:checked="aiFill.scopeR">填补缺失答案</n-checkbox>
          </div>
        </div>
      </div>
      <template #footer>
        <div style="display: flex; justify-content: flex-end; gap: 8px">
          <n-button @click="aiFill.show = false">取消</n-button>
          <n-button type="primary" :loading="aiFill.filling" @click="confirmAiFill">
            开始补全 ({{ pendingCount }} 行)
          </n-button>
        </div>
      </template>
    </n-modal>

    <n-modal v-model:show="nameDialog.show" preset="card" :title="nameDialog.title" class="center-dialog-card" style="width: 440px; max-width: calc(100vw - 32px)">
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

    <n-drawer v-model:show="ragDrawer.show" :width="drawerWidth">
      <n-drawer-content title="发起 RAG 检索评测" closable>
        <div class="field">
          <label class="field-label">评测类型</label>
          <span class="status-tag-clean">RAG 知识库检索评测</span>
        </div>
        <div class="form-row">
          <div class="field">
            <label class="field-label">知识库 ID</label>
            <n-input :value="ragDrawer.kbId" readonly />
          </div>
          <div class="field">
            <label class="field-label">黄金 QA 资产</label>
            <n-input :value="ragDrawer.goldQaLabel" readonly />
          </div>
        </div>
        <div class="field">
          <label class="field-label">检索模式 (rag_mode)</label>
          <div class="tab-pill-group">
            <button
              v-for="m in RAG_MODES"
              :key="m"
              class="tab-pill"
              :class="{ active: ragDrawer.modes.includes(m) }"
              @click="toggleRagMode(m)"
            >{{ m }}</button>
          </div>
        </div>
        <div class="divider-title">运行参数</div>
        <div class="form-row-3">
          <div class="field">
            <label class="field-label">召回数 k</label>
            <n-input-number v-model:value="ragDrawer.k" :min="1" :max="50" />
          </div>
          <div class="field">
            <label class="field-label">并发数</label>
            <n-input-number v-model:value="ragDrawer.concurrency" :min="1" :max="16" />
          </div>
          <div class="field">
            <label class="field-label">超时 (秒)</label>
            <n-input-number v-model:value="ragDrawer.timeoutS" :min="5" :max="300" />
          </div>
        </div>
        <div class="field" style="margin-top: 10px">
          <label class="field-label">先评后压（成功后派生共享压测）</label>
          <n-switch v-model:value="ragDrawer.withStress" />
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
import { ref, computed, onMounted, onUnmounted, watch, h, nextTick } from 'vue'
import { useRouter } from 'vue-router'
import { useMessage, useDialog, type DropdownOption } from 'naive-ui'
import { api } from '../api/http'
import type { Dataset, DatasetRow, GoldQA, TaskSpec } from '../api/types'
import { useModeStore } from '../stores/mode'
import UploadDatasetModal from '../components/modals/UploadDatasetModal.vue'
import BenchmarkLaunchDrawer from '../components/drawers/BenchmarkLaunchDrawer.vue'

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

interface CustomColumn {
  key: string
  name: string
  type: 'text' | 'json' | 'number'
}

type CtxMenuType = 'file' | 'folder' | 'row'
type AiGenMode = 'scene' | 'seed' | 'doc'

interface AiCandidate {
  selected: boolean
  q: string
  r: string
  c: string
  tags: string
  difficulty: string
}

// ─── 右键菜单 SVG 图标辅助渲染 ───
function renderIcon(pathD: string | string[], strokeColor?: string) {
  return () =>
    h(
      'svg',
      {
        width: 14,
        height: 14,
        viewBox: '0 0 24 24',
        fill: 'none',
        stroke: strokeColor || 'currentColor',
        strokeWidth: 2,
        strokeLinecap: 'round',
        strokeLinejoin: 'round',
        style: { display: 'inline-block', verticalAlign: '-2px', marginRight: '6px' },
      },
      Array.isArray(pathD) ? pathD.map(p => h('path', { d: p })) : [h('path', { d: pathD })],
    )
}

const message = useMessage()
const dialog = useDialog()
const router = useRouter()
const modeStore = useModeStore()
const treeSearch = ref('')
const gridSearch = ref('')
const datasets = ref<Dataset[]>([])
const activeDatasetId = ref('')
const sampleRows = ref<EditableDatasetRow[]>([])
const savingRows = ref(false)
const justSaved = ref(false)
const hasUnsavedChanges = ref(false)
const editingCell = ref<{ row: EditableDatasetRow; field: string; original: string } | null>(null)
const focusedCell = ref<{ rowIdx: number; field: string } | null>(null)
const showUploadModal = ref(false)
const datasetForUpload = ref<Dataset | null>(null)
const showLaunchDrawer = ref(false)
const filterPendingMode = ref<'all' | 'clean' | 'pending'>('all')
const filterPendingOnly = computed({
  get: () => filterPendingMode.value === 'pending',
  set: (val: boolean) => {
    filterPendingMode.value = val ? 'pending' : 'all'
  },
})
const tableContainerRef = ref<HTMLElement | null>(null)

// ─── 更多操作下拉菜单配置 ───
const moreMenuOptions = computed<DropdownOption[]>(() => [
  {
    label: '批量补全缺失行',
    key: 'ai-fill',
    disabled: pendingCount.value === 0,
    icon: renderIcon(['M12 2v4M12 18v4', 'M4.93 4.93l2.83 2.83M16.24 16.24l2.83 2.83', 'M2 12h4M18 12h4', 'M4.93 19.07l2.83-2.83M16.24 7.76l2.83-2.83']),
  },
  {
    label: '导出为 JSONL 文件',
    key: 'export-jsonl',
    icon: renderIcon(['M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4', 'M7 10l5 5 5-5', 'M12 15V3']),
  },
  {
    label: '覆盖上传新版本 (v+1)',
    key: 'upload-ver',
    icon: renderIcon(['M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4', 'M17 8l-5-5-5 5', 'M12 3v12']),
  },
  {
    type: 'divider',
    key: 'd1',
  },
  {
    label: '清空当前表格数据',
    key: 'clear-all',
    icon: renderIcon(['M3 6h18', 'M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2']),
  },
])

function handleMoreMenuSelect(key: string) {
  if (key === 'ai-fill') openAiFillModal()
  else if (key === 'export-jsonl') exportJsonl()
  else if (key === 'upload-ver') openUploadModal(currentDataset.value || null)
  else if (key === 'clear-all') {
    dialog.warning({
      title: '清空样本数据？',
      content: '此操作将清空当前数据集所有样本行，未保存前可刷新页面撤销。',
      positiveText: '确认清空',
      negativeText: '取消',
      onPositiveClick: () => {
        sampleRows.value = []
        hasUnsavedChanges.value = true
        message.info('已清空样本行，请记得点击保存修改。')
      },
    })
  }
}

// ─── 侧边栏拖拽调宽 ───
const TREE_W_KEY = 'ae_ft_w_datasets_nordic'
const treeWidth = ref(Math.min(500, Math.max(200, +(localStorage.getItem(TREE_W_KEY) || 280))))
const treeResizing = ref(false)

function applyTreeWidth(w: number) {
  treeWidth.value = Math.min(500, Math.max(200, Math.round(w)))
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
  applyTreeWidth(280)
  localStorage.setItem(TREE_W_KEY, '280')
  message.info('侧栏宽度已复位为 280px')
}

const drawerWidth = computed(() => (typeof window !== 'undefined' && window.innerWidth <= 720 ? '100%' : 640))

// ─── 黄金 QA 资产 ───
const goldQas = ref<GoldQA[]>([])
const activeGoldQa = computed(() => goldQas.value.find(g => g.id === activeDatasetId.value))
const isGoldQaActive = computed(() => !activeGoldQa.value)

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

const folders = ref<TreeFolder[]>([{ id: 'datasets', name: '基准数据集', open: true, items: [] }])
const goldQaFolder = ref<TreeFolder>({ id: 'gold-qa', name: '黄金 QA 资产', open: true, items: [] })
const allFolders = computed<TreeFolder[]>(() =>
  goldQaFolder.value.items.length ? [...folders.value, goldQaFolder.value] : folders.value,
)

const pendingCount = computed(() => sampleRows.value.filter(row => !row.q.trim() || !row.r.trim()).length)

// ─── 分页与即时搜索过滤 (Pagination & Instant Filter) ───
const page = ref(1)
const pageSize = ref(20)

const displayedRows = computed(() => {
  let list = sampleRows.value
  if (filterPendingMode.value === 'pending') {
    list = list.filter(row => !row.q.trim() || !row.r.trim())
  } else if (filterPendingMode.value === 'clean') {
    list = list.filter(row => row.q.trim() && row.r.trim())
  }
  const q = gridSearch.value.trim().toLowerCase()
  if (q) {
    list = list.filter(row =>
      row.q.toLowerCase().includes(q) ||
      row.r.toLowerCase().includes(q) ||
      row.c.toLowerCase().includes(q) ||
      row.tags.toLowerCase().includes(q) ||
      Object.values(row.extras).some(v => String(v).toLowerCase().includes(q)),
    )
  }
  return list
})

// 监听搜索或筛选条件变化，自动重置页码为 1
watch([gridSearch, filterPendingMode], () => {
  page.value = 1
})

const totalPages = computed(() => Math.max(1, Math.ceil(displayedRows.value.length / pageSize.value)))

// 当前页数据切片
const pagedRows = computed(() => {
  const start = (page.value - 1) * pageSize.value
  return displayedRows.value.slice(start, start + pageSize.value)
})

function getOriginalRowIndex(row: EditableDatasetRow): number {
  return sampleRows.value.findIndex(r => r.row_no === row.row_no)
}
function getDisplayedIndex(row: EditableDatasetRow): number {
  return displayedRows.value.findIndex(r => r.row_no === row.row_no)
}

function clearAllFilters() {
  gridSearch.value = ''
  filterPendingMode.value = 'all'
  page.value = 1
}

function checkAllDisplayedRows() {
  displayedRows.value.forEach(r => { r.checked = true })
}

// 关键词高亮
function highlightMatch(text: string): string {
  const q = gridSearch.value.trim()
  if (!q || !text) return escapeHtml(text)
  const regex = new RegExp(`(${escapeRegex(q)})`, 'gi')
  return escapeHtml(text).replace(regex, '<mark class="highlight-match">$1</mark>')
}

function escapeHtml(str: string): string {
  return str.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;')
}
function escapeRegex(str: string): string {
  return str.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
}

// ─── 键盘流网格导航 (Keyboard Flow) ───
const NAV_FIELDS = computed(() => {
  const base = ['chk', 'row_no', 'q', 'r', 'c', 'tags', 'difficulty']
  const extras = customCols.value.map(c => c.key)
  return [...base, ...extras]
})

function isCellCursor(row: EditableDatasetRow, field: string): boolean {
  if (!focusedCell.value) return false
  const idx = getDisplayedIndex(row)
  return focusedCell.value.rowIdx === idx && focusedCell.value.field === field
}

function setCellCursor(row: EditableDatasetRow, field: string) {
  const idx = getDisplayedIndex(row)
  focusedCell.value = { rowIdx: idx, field }
}

function handleCellClick(row: EditableDatasetRow, field: string) {
  setCellCursor(row, field)
  editCell(row, field)
}

function onWorkbenchKeydown(e: KeyboardEvent) {
  if (editingCell.value) {
    if (e.key === 'Escape') {
      cancelEditing()
      e.preventDefault()
    }
    return
  }

  // 快捷键 ⌘F 聚焦表内搜索
  if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'f') {
    e.preventDefault()
    const input = document.querySelector('.table-search-input') as HTMLInputElement
    input?.focus()
    input?.select()
    return
  }

  if (!focusedCell.value) {
    if (['ArrowDown', 'ArrowUp', 'ArrowLeft', 'ArrowRight'].includes(e.key) && displayedRows.value.length) {
      focusedCell.value = { rowIdx: 0, field: 'q' }
      e.preventDefault()
    }
    return
  }

  const { rowIdx, field } = focusedCell.value
  const fields = NAV_FIELDS.value
  const fIdx = fields.indexOf(field)

  switch (e.key) {
    case 'ArrowUp':
      if (rowIdx > 0) {
        const nextIdx = rowIdx - 1
        focusedCell.value = { rowIdx: nextIdx, field }
        const targetPage = Math.floor(nextIdx / pageSize.value) + 1
        if (targetPage !== page.value) page.value = targetPage
        scrollToFocusedRow(nextIdx)
        e.preventDefault()
      }
      break
    case 'ArrowDown':
      if (rowIdx < displayedRows.value.length - 1) {
        const nextIdx = rowIdx + 1
        focusedCell.value = { rowIdx: nextIdx, field }
        const targetPage = Math.floor(nextIdx / pageSize.value) + 1
        if (targetPage !== page.value) page.value = targetPage
        scrollToFocusedRow(nextIdx)
        e.preventDefault()
      }
      break
    case 'ArrowLeft':
      if (fIdx > 0) {
        focusedCell.value = { rowIdx, field: fields[fIdx - 1] }
        e.preventDefault()
      }
      break
    case 'ArrowRight':
      if (fIdx < fields.length - 1) {
        focusedCell.value = { rowIdx, field: fields[fIdx + 1] }
        e.preventDefault()
      }
      break
    case 'Tab':
      e.preventDefault()
      if (e.shiftKey) {
        if (fIdx > 0) focusedCell.value = { rowIdx, field: fields[fIdx - 1] }
        else if (rowIdx > 0) {
          const nextIdx = rowIdx - 1
          focusedCell.value = { rowIdx: nextIdx, field: fields[fields.length - 1] }
          const targetPage = Math.floor(nextIdx / pageSize.value) + 1
          if (targetPage !== page.value) page.value = targetPage
        }
      } else {
        if (fIdx < fields.length - 1) focusedCell.value = { rowIdx, field: fields[fIdx + 1] }
        else if (rowIdx < displayedRows.value.length - 1) {
          const nextIdx = rowIdx + 1
          focusedCell.value = { rowIdx: nextIdx, field: fields[0] }
          const targetPage = Math.floor(nextIdx / pageSize.value) + 1
          if (targetPage !== page.value) page.value = targetPage
        }
      }
      break
    case ' ':
      e.preventDefault()
      if (displayedRows.value[rowIdx]) {
        displayedRows.value[rowIdx].checked = !displayedRows.value[rowIdx].checked
      }
      break
    case 'Enter':
      e.preventDefault()
      if (displayedRows.value[rowIdx] && !['chk', 'row_no'].includes(field)) {
        editCell(displayedRows.value[rowIdx], field)
      }
      break
  }
}

function scrollToFocusedRow(idx: number) {
  const container = tableContainerRef.value
  if (!container) return
  const rowInPage = idx % pageSize.value
  const targetTop = rowInPage * 48
  if (targetTop < container.scrollTop) {
    container.scrollTop = targetTop
  } else if (targetTop + 48 > container.scrollTop + container.clientHeight) {
    container.scrollTop = targetTop - container.clientHeight + 48 + 20
  }
}

const filteredFolders = computed(() => {
  const keyword = treeSearch.value.trim().toLowerCase()
  if (!keyword) return allFolders.value
  return allFolders.value.map(folder => ({
    ...folder,
    items: folder.items.filter(item => item.name.toLowerCase().includes(keyword)),
  })).filter(folder => folder.items.length > 0)
})

// 自定义扩展列
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
    message.error(err.message || '扩展列保存失败')
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
    root = { id: 'datasets', name: '基准数据集', open: true, items: [] }
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
    const root = folders.value.find(folder => folder.id === 'datasets') || { id: 'datasets', name: '基准数据集', open: true, items: [] }
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

// 批量选择
const isCurrentPageAllChecked = computed(() => pagedRows.value.length > 0 && pagedRows.value.every(row => row.checked))
const allRowsChecked = computed(() => sampleRows.value.length > 0 && sampleRows.value.every(row => row.checked))
const selectedCount = computed(() => sampleRows.value.filter(row => row.checked).length)

const lastCheckedIdx = ref<number>(-1)

function toggleCurrentPageRowsDirect() {
  const nextState = !isCurrentPageAllChecked.value
  pagedRows.value.forEach(row => { row.checked = nextState })
}

function toggleAllRowsDirect() {
  const nextState = !allRowsChecked.value
  sampleRows.value.forEach(row => { row.checked = nextState })
}

function handleRowCheckClick(r: EditableDatasetRow, e: MouseEvent) {
  const currentIdx = getDisplayedIndex(r)
  if (e.shiftKey && lastCheckedIdx.value !== -1 && lastCheckedIdx.value !== currentIdx) {
    const start = Math.min(lastCheckedIdx.value, currentIdx)
    const end = Math.max(lastCheckedIdx.value, currentIdx)
    const targetState = !r.checked
    for (let i = start; i <= end; i++) {
      if (displayedRows.value[i]) {
        displayedRows.value[i].checked = targetState
      }
    }
  } else {
    r.checked = !r.checked
    lastCheckedIdx.value = currentIdx
  }
}

function uncheckAllRows() {
  sampleRows.value.forEach(row => { row.checked = false })
  lastCheckedIdx.value = -1
}

function batchDeleteRows() {
  const count = selectedCount.value
  if (!count) return
  dialog.warning({
    title: '批量删除确认',
    content: `确认删除已选的 ${count} 行？保存后将同步至数据库。`,
    positiveText: '确认删除',
    negativeText: '取消',
    onPositiveClick: () => {
      sampleRows.value = sampleRows.value.filter(row => !row.checked)
      sampleRows.value.forEach((r, i) => { r.row_no = i + 1 })
      hasUnsavedChanges.value = true
      const maxPage = Math.max(1, Math.ceil(displayedRows.value.length / pageSize.value))
      if (page.value > maxPage) {
        page.value = maxPage
      }
      message.info(`已删除 ${count} 行，点击“保存修改”后落库`)
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
  message.success(`已导出 ${selected.length} 行 JSONL`)
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
  page.value = 1
  gridSearch.value = ''
  filterPendingMode.value = 'all'
  focusedCell.value = null
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
    title: '存在未保存的修改',
    content: '当前表格有未落库的编辑，切换前请选择处理方式。',
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
  openNameDialog('新建空数据集', '数据集名称', '新数据集', async (val) => {
    const created = await api.datasets.create({ name: val })
    await loadDatasets()
    await selectDataset(created.id)
    message.success(`已创建「${created.name}」`)
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
  const newRow = buildEmptyRow()
  sampleRows.value.push(newRow)
  hasUnsavedChanges.value = true
  const newPage = Math.ceil(displayedRows.value.length / pageSize.value)
  page.value = Math.max(1, newPage)
  nextTick(() => {
    editCell(newRow, 'q')
  })
  message.info('已新增行，填写后点击“保存修改”落库')
}

function deleteRow(index: number) {
  sampleRows.value.splice(index, 1)
  sampleRows.value.forEach((r, i) => { r.row_no = i + 1 })
  hasUnsavedChanges.value = true
  const maxPage = Math.max(1, Math.ceil(displayedRows.value.length / pageSize.value))
  if (page.value > maxPage) {
    page.value = maxPage
  }
  message.info('已删除行，保存后生效')
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
    message.success('已保存数据集修改')
  } catch (err: any) {
    message.error(err.message || '保存数据集失败')
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
  message.success('已导出 JSONL 文件')
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
    message.error(err.message || '更新指标失败')
  }
}

async function loadRows(datasetId: string) {
  try {
    sampleRows.value = (await api.datasets.getRows(datasetId)).map(toEditableRow)
    hasUnsavedChanges.value = false
  } catch (err: any) {
    sampleRows.value = []
    message.error(err.message || '加载行数据失败')
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
    message.error(err.message || '加载数据集列表失败')
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

// 右键上下文菜单
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

// ─── 右键菜单配齐 SVG 图标 ───
const ctxMenuOptions = computed<DropdownOption[]>(() => {
  if (ctxMenu.value.type === 'file') {
    const isGoldQaNode = goldQas.value.some(g => g.id === ctxMenu.value.targetId)
    if (isGoldQaNode) {
      return [
        { label: '发起 RAG 评测', key: 'eval', icon: renderIcon('M5 3l14 9-14 9V3z', '#0F766E') },
        { label: '复制 gold_qa_id', key: 'copy-id', icon: renderIcon(['M8 4v12a2 2 0 0 0 2 2h8a2 2 0 0 0 2-2V7.242a2 2 0 0 0-.602-1.43L16.083 2.57A2 2 0 0 0 14.685 2H10a2 2 0 0 0-2 2z', 'M16 18v2a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V9a2 2 0 0 1 2-2h2']) },
      ]
    }
    const ds = datasets.value.find(item => item.id === ctxMenu.value.targetId)
    return [
      { label: '发起评测', key: 'eval', icon: renderIcon('M5 3l14 9-14 9V3z', '#0F766E') },
      { label: `上传新版本 (v${(ds?.version || 1) + 1})`, key: 'upload', icon: renderIcon(['M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4', 'M17 8l-5-5-5 5', 'M12 3v12']) },
      { label: '补全缺失行', key: 'ai-fill', icon: renderIcon(['M12 2v4', 'M12 18v4', 'M4.93 4.93l2.83 2.83', 'M16.24 16.24l2.83 2.83', 'M2 12h4', 'M18 12h4']) },
      { type: 'divider', key: 'd1' },
      { label: '重命名', key: 'rename', icon: renderIcon('M17 3a2.828 2.828 0 1 1 4 4L7.5 20.5 2 22l1.5-5.5L17 3z') },
      { label: '复制数据集 ID', key: 'copy-id', icon: renderIcon(['M8 4v12a2 2 0 0 0 2 2h8a2 2 0 0 0 2-2V7.242a2 2 0 0 0-.602-1.43L16.083 2.57A2 2 0 0 0 14.685 2H10a2 2 0 0 0-2 2z', 'M16 18v2a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V9a2 2 0 0 1 2-2h2']) },
      { label: '导出 JSONL', key: 'export', icon: renderIcon(['M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4', 'M7 10l5 5 5-5', 'M12 15V3']) },
      { type: 'divider', key: 'd2' },
      { label: '删除数据集', key: 'delete', props: { style: 'color: #DC2626' }, icon: renderIcon(['M3 6h18', 'M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2'], '#DC2626') },
    ]
  }
  if (ctxMenu.value.type === 'folder') {
    return [
      { label: '新建空数据集', key: 'new-dataset', icon: renderIcon(['M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z', 'M12 11v6', 'M9 14h6']) },
      { label: '新建子目录', key: 'new-folder', icon: renderIcon('M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z') },
      { type: 'divider', key: 'd1' },
      { label: '重命名目录', key: 'rename-folder', icon: renderIcon('M17 3a2.828 2.828 0 1 1 4 4L7.5 20.5 2 22l1.5-5.5L17 3z') },
      { label: '删除目录', key: 'delete-folder', props: { style: 'color: #DC2626' }, icon: renderIcon(['M3 6h18', 'M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2'], '#DC2626') },
    ]
  }
  const row = sampleRows.value[ctxMenu.value.rowIdx]
  return [
    { label: '详细编辑', key: 'edit', icon: renderIcon(['M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7', 'M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z']) },
    { label: '补全本行', key: 'ai-fill-row', icon: renderIcon(['M12 2v4', 'M12 18v4', 'M4.93 4.93l2.83 2.83', 'M16.24 16.24l2.83 2.83']) },
    { label: '复制为 JSON', key: 'copy-json', icon: renderIcon(['M8 4v12a2 2 0 0 0 2 2h8a2 2 0 0 0 2-2V7.242a2 2 0 0 0-.602-1.43L16.083 2.57A2 2 0 0 0 14.685 2H10a2 2 0 0 0-2 2z', 'M16 18v2a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V9a2 2 0 0 1 2-2h2']) },
    { label: row?.checked ? '取消勾选' : '勾选本行', key: 'toggle-check', icon: renderIcon(['M9 11l3 3L22 4', 'M21 12v7a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11']) },
    { type: 'divider', key: 'd1' },
    { label: '上方插入行', key: 'insert-above', icon: renderIcon(['M12 19V5', 'M5 12l7-7 7 7']) },
    { label: '下方插入行', key: 'insert-below', icon: renderIcon(['M12 5v14', 'M19 12l-7 7-7-7']) },
    { label: '创建副本', key: 'duplicate-row', icon: renderIcon(['M16 4h2a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2h2', 'M9 14l2 2 4-4']) },
    { type: 'divider', key: 'd2' },
    { label: '删除本行', key: 'delete-row', props: { style: 'color: #DC2626' }, icon: renderIcon(['M3 6h18', 'M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2'], '#DC2626') },
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
      message.success('已复制 gold_qa_id')
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
        message.success('重命名成功')
      })
      break
    case 'copy-id':
      await navigator.clipboard.writeText(targetId)
      message.success('已复制数据集 ID')
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
    title: '删除确认',
    content: `确认删除「${dataset.name}」(v${dataset.version})？已跑任务的历史快照不受影响。`,
    positiveText: '确认删除',
    negativeText: '取消',
    onPositiveClick: async () => {
      try {
        await api.datasets.delete(dataset.id)
        if (activeDatasetId.value === dataset.id) activeDatasetId.value = ''
        await loadDatasets()
        message.success(`已删除「${dataset.name}」`)
      } catch (err: any) {
        message.error(err.message || '删除失败')
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
      openNameDialog('新建子目录', '目录名称', '新建目录', async (val) => {
        try {
          await api.datasets.createFolder({ name: val })
          await loadFolders()
          message.success(`已创建目录「${val}」`)
        } catch (err: any) {
          message.error(err.message || '创建目录失败')
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
          message.success('目录重命名成功')
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
            message.success('目录已删除')
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
      message.success('已复制样本行 JSON')
      break
    }
    case 'toggle-check':
      row.checked = !row.checked
      break
    case 'insert-above':
      sampleRows.value.splice(rowIdx, 0, buildEmptyRow())
      hasUnsavedChanges.value = true
      message.info('已在上方插入行，保存后落库')
      break
    case 'insert-below':
      sampleRows.value.splice(rowIdx + 1, 0, buildEmptyRow())
      hasUnsavedChanges.value = true
      message.info('已在下方插入行，保存后落库')
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
      message.success(`已复制第 ${row.row_no} 行`)
      break
    }
    case 'delete-row':
      deleteRow(rowIdx)
      break
  }
}

// 通用命名弹窗
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

// 行结构化编辑
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
  message.success(`已更新样本 #${row.row_no}，保存后生效`)
}

// 扩展列
const addCol = ref<{ show: boolean; key: string; name: string }>({ show: false, key: '', name: '' })
const RESERVED_COL_KEYS = ['row_no', 'question', 'reference', 'context', 'q', 'r', 'c', 'tags', 'difficulty']

function openAddColModal() {
  addCol.value = { show: true, key: '', name: '' }
}

async function confirmAddCol() {
  const ds = currentDataset.value
  if (!ds) return
  const key = addCol.value.key.trim().toLowerCase()
  const name = addCol.value.name.trim()
  if (!/^[a-z][a-z0-9_]*$/.test(key)) {
    message.warning('字段 Key 需以字母开头，仅含字母/数字/下划线')
    return
  }
  if (!name) {
    message.warning('请填写列显示名称')
    return
  }
  if (RESERVED_COL_KEYS.includes(key)) {
    message.warning('该 Key 与内置列冲突')
    return
  }
  const list = customColsMap.value[ds.id] || []
  if (list.some(col => col.key === key)) {
    message.warning('该字段 Key 已存在')
    return
  }
  const nextCols: CustomColumn[] = [...list, { key, name, type: 'text' }]
  customColsMap.value[ds.id] = nextCols
  sampleRows.value.forEach(row => {
    row.extras[key] = ''
  })
  hasUnsavedChanges.value = true
  addCol.value.show = false
  try {
    await persistCustomCols(ds.id, nextCols, list)
    message.success(`已添加列「${name}」`)
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

// 抽屉式数据合成向导
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
      label: `${row.q} => ${row.r}`.slice(0, 60),
      value: `${row.q} => ${row.r}`,
    })),
)

const aiSelectedCount = computed(() => aiGen.value.candidates.filter(c => c.selected).length)
const aiAllSelected = computed(() => aiGen.value.candidates.length > 0 && aiSelectedCount.value === aiGen.value.candidates.length)

function openAiGenDrawer() {
  const target = currentDataset.value || datasets.value[0]
  if (!target) {
    createEmptyDataset(() => openAiGenDrawer())
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
    message.warning('请填写场景描述')
    return
  }
  if (form.mode === 'seed' && !form.seedSample) {
    message.warning('请选择种子样本')
    return
  }
  if (form.mode === 'doc' && !form.docText.trim()) {
    message.warning('请粘贴需求文档文本')
    return
  }
  form.generating = true
  try {
    let candidates: AiCandidate[] = []
    if (api.isMock()) {
      await new Promise(resolve => setTimeout(resolve, 400))
      candidates = Array.from({ length: form.rowCount }, (_, i) => ({
        selected: true,
        q: `如何处理跨境交易退款中的汇损问题？（样本 #${i + 1}）`,
        r: form.genRef ? '根据平台协议，外币订单按原路退回，退款汇率以交易发起时汇率为准。' : '',
        c: form.genCtx ? '跨境结算指引' : '',
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
      if (!candidates.length) throw new Error('未返回候选数据')
    }
    form.candidates = candidates
    form.step = 2
  } catch (err: any) {
    message.error(err.message || '数据合成失败')
  } finally {
    form.generating = false
  }
}

function toggleAllCandidates() {
  const target = aiSelectedCount.value < aiGen.value.candidates.length
  aiGen.value.candidates.forEach(c => { c.selected = target })
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
  message.success(`已导入 ${selected.length} 条样本，点击“保存修改”落库`)
}

// 补全弹窗
const aiFill = ref({
  show: false,
  instruction: '结合已有业务上下文及同组样本特征，推导问句与标准答案。',
  scopeQ: true,
  scopeR: true,
  filling: false,
})

function openAiFillModal() {
  if (!currentDataset.value) return
  if (pendingCount.value === 0) {
    message.info('当前数据集样本格式完整，无需补全')
    return
  }
  aiFill.value.show = true
}

async function confirmAiFill() {
  if (!currentDataset.value || aiFill.value.filling) return
  aiFill.value.filling = true
  try {
    if (api.isMock()) {
      await new Promise(resolve => setTimeout(resolve, 400))
      sampleRows.value.forEach((row, i) => {
        if (aiFill.value.scopeQ && !row.q.trim()) row.q = `补全问句 #${i + 1}：如何申请退款？`
        if (aiFill.value.scopeR && !row.r.trim()) row.r = '在「账单详情」提交退款申请，审核后 1-3 工作日原路退回。'
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
    message.success('已补全缺失字段，点击“保存修改”落库')
  } catch (err: any) {
    message.error(err.message || '补全失败')
  } finally {
    aiFill.value.filling = false
  }
}

async function aiFillRow(idx: number) {
  const row = sampleRows.value[idx]
  if (!row || !currentDataset.value) return
  try {
    if (api.isMock()) {
      if (!row.q.trim()) row.q = '补全问句：如何查看扣款明细？'
      if (!row.r.trim()) row.r = '进入「财务中心-账单管理」查看。'
    } else {
      const result = await api.datasets.generateRows({
        dataset_id: currentDataset.value.id,
        mode: 'fill_missing',
        rows: [{ row_no: row.row_no, question: row.q, reference: row.r, context: row.c || null }],
        max_count: 1,
      })
      const value = result[0] ? toEditableRow(result[0]) : null
      if (!value) throw new Error('未返回补全数据')
      row.q = value.q || row.q
      row.r = value.r || row.r
      row.c = value.c || row.c
    }
    hasUnsavedChanges.value = true
    message.success(`已补全第 ${row.row_no} 行，保存后生效`)
  } catch (err: any) {
    message.error(err.message || '补全失败')
  }
}

// 黄金 QA RAG 抽屉
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
    message.success('RAG 评测任务已入队')
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
/* ─── 数据集工作台核心布局 ─── */
.datasets-workbench {
  height: calc(100vh - var(--topbar-h) - 20px);
  min-height: 0;
  display: flex;
  flex-direction: column;
  outline: none;
  font-size: 13.5px;
  color: var(--text-primary);
}

.mode-context-panel {
  max-width: 620px;
  margin: 64px auto;
  padding: 40px 36px;
  text-align: center;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 16px;
  background: var(--bg-main);
  border: 1px solid var(--border-subtle);
  border-radius: 14px;
  box-shadow: 0 4px 16px rgba(0, 0, 0, 0.04);
}
.mode-icon-wrapper {
  width: 56px;
  height: 56px;
  border-radius: 14px;
  background: var(--t-kb);
  color: var(--c-kb);
  display: grid;
  place-items: center;
}
.mode-context-panel h2 {
  font-size: 18px;
  font-weight: 600;
  color: var(--text-primary);
}
.mode-context-panel p {
  font-size: 13.5px;
  color: var(--text-secondary);
  line-height: 1.6;
}

/* ─── 布局骨架 ─── */
.nordic-layout {
  display: grid;
  grid-template-columns: var(--tree-w, 280px) minmax(0, 1fr);
  height: 100%;
  min-width: 0;
  background: var(--bg-main);
  border-radius: 12px;
  overflow: hidden;
  border: 1px solid var(--border-subtle);
}

/* ─── 侧边栏 ─── */
.nordic-sidebar {
  border-right: 1px solid var(--border-subtle);
  background: var(--bg-elevated);
  display: flex;
  flex-direction: column;
  height: 100%;
  position: relative;
  user-select: none;
}

.sidebar-header {
  padding: 12px 14px;
  border-bottom: 1px solid var(--border-subtle);
}
.sidebar-title-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 10px;
}
.sidebar-title {
  display: flex;
  align-items: center;
  gap: 6px;
  font-weight: 600;
  font-size: 13.5px;
  color: var(--text-primary);
}
.title-icon {
  color: var(--c-datasets);
}
.sidebar-actions {
  display: flex;
  gap: 4px;
}

.btn-xs {
  min-height: 24px;
  padding: 2px 7px;
  font-size: 12px;
  border-radius: 4px;
}
.btn-ghost-subtle {
  background: transparent;
  border: 1px solid transparent;
  color: var(--text-secondary);
}
.btn-ghost-subtle:hover {
  background: var(--row-hover);
  color: var(--text-primary);
}

.search-box {
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
.search-input {
  width: 100%;
  height: 30px;
  padding-left: 28px;
  padding-right: 24px;
  font-size: 12.5px;
  border-radius: 6px;
  border: 1px solid var(--border-subtle);
  background: var(--bg-main);
  color: var(--text-primary);
  outline: none;
  transition: border-color 0.15s ease;
}
.search-input:focus {
  border-color: var(--accent-ai);
  box-shadow: var(--focus-ring);
}
.clear-search-btn {
  position: absolute;
  right: 7px;
  background: none;
  border: none;
  color: var(--text-tertiary);
  font-size: 12px;
  cursor: pointer;
  padding: 2px;
}
.clear-search-btn:hover {
  color: var(--text-primary);
}

.tree-content {
  flex: 1;
  overflow-y: auto;
  padding: 8px;
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.tree-node {
  display: flex;
  align-items: center;
  gap: 7px;
  padding: 6px 10px;
  border-radius: 6px;
  font-size: 13px;
  cursor: pointer;
  color: var(--text-secondary);
  transition: background-color 0.12s ease, color 0.12s ease;
}
.tree-node:hover {
  background: var(--row-hover);
  color: var(--text-primary);
}
.tree-node.active {
  background: var(--t-datasets);
  color: var(--c-datasets);
  font-weight: 600;
  border: 1px solid transparent;
}

.folder-node {
  font-weight: 600;
  color: var(--text-primary);
  font-size: 13.5px;
}
.folder-children {
  padding-left: 16px;
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.chevron-icon {
  display: grid;
  place-items: center;
  color: var(--text-tertiary);
  transition: transform 0.15s ease;
}
.chevron-icon.rotated {
  transform: rotate(90deg);
}

.folder-icon {
  color: var(--text-tertiary);
  flex-shrink: 0;
}
.file-icon {
  display: grid;
  place-items: center;
  flex-shrink: 0;
}
.file-icon.gold-qa { color: var(--c-profiles); }
.file-icon.dataset { color: var(--c-datasets); }

.node-name {
  flex: 1;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.version-badge {
  font-family: var(--font-mono);
  font-size: 11px;
  padding: 1px 5px;
  border-radius: 3px;
  background: var(--bg-elevated);
  color: var(--text-tertiary);
  border: 1px solid var(--border-subtle);
}
.tree-node.active .version-badge {
  background: rgba(255, 255, 255, 0.6);
  color: var(--c-datasets);
}
.pending-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: var(--accent-warning);
}
.node-badge {
  margin-left: auto;
  font-family: var(--font-mono);
  font-size: 11px;
  color: var(--text-tertiary);
}

.tree-empty {
  padding: 36px 16px;
  text-align: center;
  color: var(--text-tertiary);
  font-size: 12.5px;
}

.sidebar-resizer {
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
.resizer-bar {
  width: 2px;
  height: 24px;
  border-radius: 1px;
  background: transparent;
}
.sidebar-resizer:hover .resizer-bar,
.sidebar-resizer.active .resizer-bar {
  background: var(--accent-ai);
}

/* ─── 主工作区 ─── */
.nordic-main {
  display: flex;
  flex-direction: column;
  height: 100%;
  min-width: 0;
  min-height: 0;
  background: var(--bg-main);
  position: relative;
}

/* 顶栏 */
.main-toolbar {
  padding: 10px 18px;
  border-bottom: 1px solid var(--border-subtle);
  background: var(--bg-main);
  min-height: 56px;
  display: flex;
  align-items: center;
}

.toolbar-default {
  display: flex;
  align-items: center;
  width: 100%;
  gap: 12px;
}

.toolbar-title-group {
  display: flex;
  flex-direction: column;
  gap: 2px;
}
.title-row {
  display: flex;
  align-items: center;
  gap: 8px;
}
.main-dataset-title {
  font-size: 16.5px;
  font-weight: 600;
  color: var(--text-primary);
}
.version-tag {
  font-family: var(--font-mono);
  font-size: 11.5px;
  font-weight: 500;
  padding: 1px 7px;
  border-radius: 4px;
  background: var(--bg-elevated);
  border: 1px solid var(--border-subtle);
  color: var(--text-secondary);
}
.asset-type-badge {
  font-size: 11.5px;
  font-weight: 500;
  padding: 1px 7px;
  border-radius: 4px;
}
.type-dataset { background: var(--t-datasets); color: var(--c-datasets); }
.type-gold { background: var(--t-profiles); color: var(--c-profiles); }

.status-badge-amber {
  font-size: 11.5px;
  padding: 1px 7px;
  border-radius: 4px;
  background: var(--t-profiles);
  color: var(--c-profiles);
}

.breadcrumb-row {
  font-size: 12px;
  color: var(--text-tertiary);
  display: flex;
  align-items: center;
  gap: 5px;
}
.breadcrumb-row .cur {
  color: var(--text-secondary);
}

/* 极速表内筛选框 */
.table-search-box {
  position: relative;
  display: flex;
  align-items: center;
  margin-left: 8px;
}
.table-search-icon {
  position: absolute;
  left: 8px;
  color: var(--text-tertiary);
  pointer-events: none;
}
.table-search-input {
  width: 200px;
  height: 28px;
  padding-left: 26px;
  padding-right: 50px;
  font-size: 12.5px;
  border-radius: 6px;
  border: 1px solid var(--border-subtle);
  background: var(--bg-elevated);
  color: var(--text-primary);
  outline: none;
  transition: all 0.15s ease;
}
.table-search-input:focus {
  width: 250px;
  background: var(--bg-main);
  border-color: var(--accent-ai);
  box-shadow: var(--focus-ring);
}
.grid-search-count {
  position: absolute;
  right: 18px;
  font-size: 11px;
  color: var(--text-tertiary);
}

.toolbar-action-group {
  display: flex;
  align-items: center;
  gap: 8px;
}
.action-btn-group {
  display: flex;
  align-items: center;
  gap: 5px;
}

/* 按钮通用 */
.btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  font-size: 13px;
  font-weight: 500;
  border-radius: 6px;
  cursor: pointer;
  transition: all 0.12s ease;
  white-space: nowrap;
}
.btn-md {
  min-height: 30px;
  padding: 4px 12px;
}
.btn-sm {
  min-height: 26px;
  padding: 3px 10px;
  font-size: 12.5px;
}
.btn-primary {
  background: var(--accent-ai);
  color: #FFFFFF;
  border: 1px solid var(--accent-ai);
}
.btn-primary:hover {
  opacity: 0.92;
}
.btn-secondary {
  background: var(--bg-main);
  color: var(--text-primary);
  border: 1px solid var(--border-subtle);
}
.btn-secondary:hover {
  background: var(--row-hover);
  border-color: var(--border-subtle);
}
.btn-ghost {
  background: transparent;
  color: var(--text-secondary);
  border: 1px solid transparent;
}
.btn-ghost:hover {
  background: var(--row-hover);
  color: var(--text-primary);
}
.btn-danger {
  background: var(--accent-error);
  color: #FFFFFF;
  border: 1px solid var(--accent-error);
}
.btn-danger:hover {
  opacity: 0.9;
}
.btn-icon-only {
  padding: 5px;
  border-radius: 6px;
  color: var(--text-secondary);
}
.btn-icon-only:hover {
  background: var(--row-hover);
  color: var(--text-primary);
}

.btn-save {
  background: var(--bg-main);
  color: var(--text-secondary);
  border: 1px solid var(--border-subtle);
}
.btn-save.dirty {
  background: var(--accent-warning);
  color: #FFFFFF;
  border-color: var(--accent-warning);
}
.btn-save.saved {
  background: var(--accent-success) !important;
  color: #FFFFFF !important;
  border-color: var(--accent-success) !important;
}
.saved-icon {
  font-weight: 700;
}
.shortcut-key {
  font-size: 10px;
  font-family: var(--font-mono);
  padding: 0 4px;
  border-radius: 2px;
  background: rgba(0, 0, 0, 0.08);
  color: inherit;
}
.btn-save.dirty .shortcut-key {
  background: rgba(255, 255, 255, 0.25);
}

/* ─── 指标与胶囊筛选条 ─── */
.metrics-strip {
  padding: 8px 18px;
  background: var(--bg-elevated);
  border-bottom: 1px solid var(--border-subtle);
  display: flex;
  align-items: center;
  gap: 12px;
  font-size: 12.5px;
}
.strip-left {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
}
.strip-label {
  color: var(--text-tertiary);
}
.strip-text {
  color: var(--text-primary);
  font-weight: 500;
}
.strip-divider {
  width: 1px;
  height: 14px;
  background: var(--border-subtle);
}

.filter-pills-bar {
  display: flex;
  align-items: center;
  gap: 6px;
}
.filter-pill {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  padding: 2px 9px;
  font-size: 12px;
  border-radius: 14px;
  border: 1px solid var(--border-subtle);
  background: var(--bg-main);
  color: var(--text-secondary);
  cursor: pointer;
  transition: all 0.12s ease;
}
.filter-pill:hover {
  border-color: var(--accent-ai);
  color: var(--text-primary);
}
.filter-pill.active {
  background: var(--text-primary);
  color: var(--bg-main);
  border-color: var(--text-primary);
  font-weight: 600;
}
.filter-pill.pill-clean.active {
  background: var(--accent-success);
  border-color: var(--accent-success);
  color: #FFFFFF;
}
.filter-pill.pill-amber.active {
  background: var(--accent-warning);
  border-color: var(--accent-warning);
  color: #FFFFFF;
}
.pill-num {
  font-family: var(--font-mono);
  font-size: 11px;
}

.status-indicator-warning {
  color: var(--accent-warning);
  font-weight: 500;
}
.status-indicator-success {
  color: var(--accent-success);
  font-weight: 500;
}

.keyboard-flow-hint {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 11.5px;
  color: var(--text-tertiary);
}
.kbd-hint kbd {
  font-family: var(--font-mono);
  font-size: 10.5px;
  padding: 1px 4px;
  border-radius: 3px;
  background: var(--bg-main);
  color: var(--text-secondary);
  border: 1px solid var(--border-subtle);
}

.metric-control {
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
  font-size: 12px;
  padding: 1px 6px;
  border-radius: 4px;
  border: 1px solid var(--border-subtle);
  background: var(--bg-main);
  color: var(--text-primary);
  outline: none;
}
.metric-select:focus {
  border-color: var(--accent-ai);
}

/* ─── 表格与固定列 ─── */
.table-container {
  flex: 1;
  min-width: 0;
  overflow: auto;
  outline: none;
  position: relative;
}

.nordic-table {
  width: 100%;
  border-collapse: separate;
  border-spacing: 0;
}
.nordic-table th {
  position: sticky;
  top: 0;
  z-index: 5;
  background: var(--bg-elevated);
  padding: 10px 12px;
  font-size: 12px;
  font-weight: 600;
  color: var(--text-secondary);
  text-align: left;
  border-bottom: 1px solid var(--border-subtle);
  letter-spacing: 0.01em;
}
.nordic-table td {
  padding: 8px 12px;
  font-size: 13.5px;
  color: var(--text-primary);
  vertical-align: middle;
  border-bottom: 1px solid var(--border-subtle);
  height: 48px;
  background: var(--bg-main);
}

.th-chk, .td-chk {
  text-align: center !important;
  vertical-align: middle !important;
}

.clean-chk-box {
  width: 17px;
  height: 17px;
  border-radius: 4px;
  border: 1.5px solid var(--border-subtle);
  background: var(--bg-main);
  display: grid;
  place-items: center;
  cursor: pointer;
  transition: all 0.12s ease;
}
.clean-chk-box:hover {
  border-color: var(--accent-ai);
}
.clean-chk-box.checked {
  background: var(--accent-ai);
  border-color: var(--accent-ai);
}

.req-star {
  color: var(--accent-error);
}

.custom-th {
  background: var(--bg-elevated) !important;
}
.th-flex {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 4px;
}
.th-del-btn {
  background: none;
  border: none;
  color: var(--text-tertiary);
  font-size: 11px;
  cursor: pointer;
  padding: 1px;
}
.th-del-btn:hover { color: var(--accent-error); }

.data-row {
  transition: background-color 0.08s ease;
}
.data-row:hover td {
  background: var(--row-hover);
}
.data-row.row-checked td {
  background: var(--t-datasets);
}
.data-row.row-incomplete td {
  background: rgba(245, 158, 11, 0.04);
}

.cell-cursor {
  box-shadow: inset 0 0 0 1.5px var(--accent-ai);
}

.td-num {
  font-size: 12px;
  color: var(--text-tertiary);
}

.cell-edit {
  cursor: text;
  transition: background-color 0.1s ease;
  position: relative;
}
.cell-edit:hover {
  outline: 1px dashed var(--accent-ai);
  outline-offset: -2px;
  border-radius: 4px;
}

.cell-content {
  min-height: 24px;
  display: flex;
  align-items: center;
  word-break: break-word;
  line-height: 1.5;
  font-size: 13.5px;
}
.cell-content.primary-text {
  font-weight: 500;
  color: var(--text-primary);
}
.cell-content.empty {
  color: var(--accent-warning);
  font-style: italic;
  font-size: 12.5px;
}
.cell-content.placeholder {
  color: var(--text-tertiary);
}
.cell-content.mono-sm {
  font-family: var(--font-mono);
  font-size: 12px;
}

:deep(.highlight-match) {
  background: #FEF08A;
  color: #854D0E;
  padding: 0 2px;
  border-radius: 2px;
}

.inline-input {
  width: 100%;
  padding: 4px 7px;
  font: inherit;
  font-size: 13px;
  background: var(--bg-main);
  border: 1.5px solid var(--accent-ai);
  border-radius: 4px;
  outline: none;
  color: var(--text-primary);
  box-shadow: var(--focus-ring);
}
.inline-select {
  height: 28px;
  font-size: 12.5px;
  padding: 1px 6px;
  border-radius: 4px;
  border: 1px solid var(--accent-ai);
  background: var(--bg-main);
  color: var(--text-primary);
}

.cell-invalid {
  border-bottom: 1px dashed var(--accent-error) !important;
}

.tag-pill {
  display: inline-block;
  padding: 1px 7px;
  border-radius: 4px;
  background: var(--bg-elevated);
  color: var(--text-secondary);
  border: 1px solid var(--border-subtle);
  font-size: 11.5px;
}
.diff-badge {
  display: inline-block;
  padding: 1px 6px;
  border-radius: 4px;
  font-size: 11.5px;
  font-weight: 500;
}
.diff-简单 { background: var(--t-cases); color: var(--c-cases); }
.diff-中等 { background: var(--t-profiles); color: var(--c-profiles); }
.diff-高 { background: var(--t-stress); color: var(--c-stress); }

.status-tag-green {
  font-size: 12px;
  color: var(--accent-success);
  font-weight: 500;
}
.status-tag-amber {
  font-size: 12px;
  color: var(--accent-warning);
  font-weight: 500;
}
.status-tag-clean {
  display: inline-block;
  padding: 2px 8px;
  border-radius: 4px;
  background: var(--t-cases);
  color: var(--c-cases);
  font-size: 12px;
  font-weight: 500;
}

.td-actions {
  text-align: right;
  white-space: nowrap;
}
.action-links {
  display: inline-flex;
  gap: 3px;
  opacity: 0.4;
  transition: opacity 0.12s ease;
}
.data-row:hover .action-links {
  opacity: 1;
}
.icon-link {
  background: none;
  border: none;
  padding: 4px;
  border-radius: 4px;
  color: var(--text-tertiary);
  cursor: pointer;
  display: grid;
  place-items: center;
}
.icon-link:hover {
  background: var(--row-hover);
  color: var(--text-primary);
}
.icon-link.danger:hover {
  background: rgba(239, 68, 68, 0.1);
  color: var(--accent-error);
}

.empty-cell {
  padding: 56px 20px;
  text-align: center;
  color: var(--text-tertiary);
}
.empty-message {
  font-size: 13.5px;
}

/* ─── 底部固定分页工具栏 (Table Pagination Bar) ─── */
.table-pagination-bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 8px 18px;
  background: var(--bg-elevated);
  border-top: 1px solid var(--border-subtle);
  min-height: 46px;
  flex-shrink: 0;
  gap: 16px;
  z-index: 10;
}
.pagination-info {
  display: flex;
  align-items: center;
  gap: 10px;
  font-size: 12.5px;
  color: var(--text-secondary);
  flex-wrap: wrap;
}
.pagination-total strong {
  color: var(--text-primary);
}
.pagination-pages {
  color: var(--text-tertiary);
  font-size: 11.5px;
  margin-left: 4px;
}
.pagination-filter-tag {
  font-size: 11.5px;
  color: var(--accent-ai);
  background: color-mix(in srgb, var(--accent-ai) 10%, transparent);
  padding: 1px 7px;
  border-radius: 4px;
  border: 1px solid color-mix(in srgb, var(--accent-ai) 22%, transparent);
}
.pagination-selection-tag {
  font-size: 11.5px;
  color: var(--c-datasets);
  background: var(--t-datasets);
  padding: 1px 7px;
  border-radius: 4px;
  font-weight: 500;
}
.pagination-controls {
  display: flex;
  align-items: center;
}

/* ─── 底部浮动批量操作栏 (Floating Action Dock) ─── */
.floating-batch-dock {
  position: absolute;
  bottom: 60px;
  left: 50%;
  transform: translateX(-50%);
  z-index: 100;
  display: flex;
  align-items: center;
  gap: 16px;
  padding: 8px 18px;
  border-radius: 24px;
  background: rgba(17, 24, 39, 0.92);
  color: #FFFFFF;
  backdrop-filter: blur(12px);
  box-shadow: 0 10px 25px -5px rgba(0, 0, 0, 0.3), 0 8px 10px -6px rgba(0, 0, 0, 0.2);
  border: 1px solid rgba(255, 255, 255, 0.15);
}
.batch-dock-info {
  display: flex;
  align-items: center;
  gap: 8px;
}
.batch-dock-badge {
  background: var(--accent-ai);
  color: #FFFFFF;
  font-family: var(--font-mono);
  font-size: 12px;
  font-weight: 700;
  padding: 1px 8px;
  border-radius: 12px;
}
.batch-dock-text {
  font-size: 13px;
  color: rgba(255, 255, 255, 0.85);
}
.batch-dock-actions {
  display: flex;
  align-items: center;
  gap: 8px;
}
.floating-batch-dock .btn-secondary {
  background: rgba(255, 255, 255, 0.12);
  color: #FFFFFF;
  border: 1px solid rgba(255, 255, 255, 0.2);
}
.floating-batch-dock .btn-secondary:hover {
  background: rgba(255, 255, 255, 0.2);
}
.floating-batch-dock .btn-ghost {
  color: rgba(255, 255, 255, 0.7);
}
.floating-batch-dock .btn-ghost:hover {
  color: #FFFFFF;
  background: rgba(255, 255, 255, 0.1);
}

.slide-up-enter-active,
.slide-up-leave-active {
  transition: all 0.24s cubic-bezier(0.4, 0, 0.2, 1);
}
.slide-up-enter-from,
.slide-up-leave-to {
  opacity: 0;
  transform: translate(-50%, 20px);
}

/* ─── 空态页面 ─── */
.empty-main {
  display: grid;
  place-items: center;
  padding: 48px;
}
.empty-box {
  max-width: 460px;
  text-align: center;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 14px;
}
.empty-icon-wrapper {
  width: 72px;
  height: 72px;
  border-radius: 18px;
  background: var(--t-datasets);
  color: var(--c-datasets);
  display: grid;
  place-items: center;
}
.empty-box h3 {
  font-size: 17px;
  font-weight: 600;
  color: var(--text-primary);
}
.empty-desc {
  font-size: 13.5px;
  color: var(--text-secondary);
  line-height: 1.6;
}
.empty-buttons {
  display: flex;
  gap: 10px;
  flex-wrap: wrap;
  justify-content: center;
  margin-top: 8px;
}

/* ─── 抽屉内样式 ─── */
.drawer-step-bar {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 20px;
  padding-bottom: 14px;
  border-bottom: 1px solid var(--border-subtle);
}
.step-badge {
  display: flex;
  align-items: center;
  gap: 7px;
  font-size: 13px;
  color: var(--text-tertiary);
}
.step-badge.active {
  color: var(--accent-ai);
  font-weight: 600;
}
.step-badge.done {
  color: var(--accent-success);
}
.step-idx {
  width: 20px;
  height: 20px;
  border-radius: 50%;
  background: var(--bg-elevated);
  border: 1px solid var(--border-subtle);
  display: grid;
  place-items: center;
  font-size: 11px;
  font-family: var(--font-mono);
}
.step-badge.active .step-idx {
  background: var(--accent-ai);
  color: #FFFFFF;
  border-color: var(--accent-ai);
}
.step-badge.done .step-idx {
  background: var(--accent-success);
  color: #FFFFFF;
  border-color: var(--accent-success);
}
.step-divider-line {
  flex: 1;
  height: 1px;
  background: var(--border-subtle);
}

.drawer-body {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.tab-pill-group {
  display: flex;
  gap: 6px;
  background: var(--bg-elevated);
  padding: 4px;
  border-radius: 6px;
  border: 1px solid var(--border-subtle);
}
.tab-pill {
  flex: 1;
  padding: 5px 10px;
  font-size: 13px;
  border: none;
  background: transparent;
  color: var(--text-secondary);
  border-radius: 4px;
  cursor: pointer;
  transition: all 0.1s ease;
}
.tab-pill.active {
  background: var(--bg-main);
  color: var(--text-primary);
  font-weight: 600;
  box-shadow: 0 1px 2px rgba(0, 0, 0, 0.04);
}

.divider-title {
  font-size: 13px;
  font-weight: 600;
  color: var(--text-secondary);
  margin: 8px 0 3px;
}

.preview-box {
  max-height: 420px;
  overflow-y: auto;
  border: 1px solid var(--border-subtle);
  border-radius: 6px;
}
.preview-table td {
  padding: 8px 10px;
}
.inline-input-clean {
  width: 100%;
  padding: 3px 6px;
  border: 1px solid transparent;
  background: transparent;
  font-size: 13px;
  color: var(--text-primary);
}
.inline-input-clean:focus {
  border-color: var(--accent-ai);
  background: var(--bg-main);
  border-radius: 4px;
  outline: none;
}

.drawer-footer-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  width: 100%;
}

/* ─── 滚动条 ─── */
.custom-scroll::-webkit-scrollbar {
  width: 6px;
  height: 6px;
}
.custom-scroll::-webkit-scrollbar-track {
  background: transparent;
}
.custom-scroll::-webkit-scrollbar-thumb {
  background: rgba(150, 150, 150, 0.2);
  border-radius: 3px;
}
.custom-scroll::-webkit-scrollbar-thumb:hover {
  background: rgba(150, 150, 150, 0.35);
}

/* ─── 响应式 ─── */
@media (max-width: 900px) {
  .datasets-workbench {
    height: auto;
    min-height: calc(100dvh - var(--topbar-h) - 20px);
  }
  .nordic-layout {
    grid-template-columns: 1fr;
    height: auto;
  }
  .nordic-sidebar {
    max-height: 240px;
    border-right: 0;
    border-bottom: 1px solid var(--border-subtle);
  }
  .sidebar-resizer {
    display: none;
  }
  .nordic-main {
    min-height: 600px;
  }
  .keyboard-flow-hint {
    display: none;
  }
}
</style>
