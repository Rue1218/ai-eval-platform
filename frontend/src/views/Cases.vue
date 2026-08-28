<template>
  <div class="cases-workbench" @keydown="onWorkbenchKeydown">
    <div class="nordic-layout" :style="{ '--tree-w': treeWidth + 'px' }">
      <!-- ─── 左侧：用例集目录侧边栏 ─── -->
      <aside class="nordic-sidebar">
        <!-- 侧边栏头部 -->
        <div class="sidebar-header">
          <div class="sidebar-title-row">
            <div class="sidebar-title">
              <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="title-icon">
                <path d="M16 4h2a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2h2" />
                <rect x="8" y="2" width="8" height="4" rx="1" ry="1" />
                <path d="M9 14l2 2 4-4" />
              </svg>
              <span>用例集目录</span>
            </div>
            <!-- 新建用例集下拉触发器 -->
            <n-dropdown trigger="click" :options="createSetMenuOptions" @select="handleCreateSetMenu">
              <button class="btn btn-ghost-subtle btn-xs" aria-label="新建用例集菜单">
                + 新建集 ▾
              </button>
            </n-dropdown>
          </div>

          <!-- 搜索输入框 -->
          <div class="search-box">
            <svg class="search-icon" width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
              <circle cx="11" cy="11" r="8" />
              <line x1="21" y1="21" x2="16.65" y2="16.65" />
            </svg>
            <input v-model="treeSearch" class="search-input" placeholder="搜索用例集..." aria-label="搜索用例集" />
            <button v-if="treeSearch" class="clear-search-btn" aria-label="清空搜索" @click="treeSearch = ''">✕</button>
          </div>
        </div>

        <!-- 目录树内容区 -->
        <div class="tree-content custom-scroll">
          <div v-for="folder in filteredFolders" :key="folder.id" class="folder-group">
            <!-- 文件夹节点 -->
            <div
              class="tree-node folder-node"
              :class="{ open: folder.open }"
              @click="folder.open = !folder.open"
              @contextmenu.prevent.stop="onFolderContextMenu($event, folder.id)"
            >
              <span class="chevron-icon" :class="{ rotated: folder.open }">
                <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round">
                  <polyline points="9 18 15 12 9 6" />
                </svg>
              </span>
              <svg class="folder-icon" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">
                <path v-if="folder.open" d="m6 14 1.5-2.9A2 2 0 0 1 9.24 10H20a2 2 0 0 1 1.94 2.5l-1.54 6a2 2 0 0 1-1.95 1.5H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h3.9a2 2 0 0 1 1.69.9l.81 1.2a2 2 0 0 0 1.67.9H18a2 2 0 0 1 2 2v2" />
                <path v-else d="M20 20a2 2 0 0 0 2-2V8a2 2 0 0 0-2-2h-7.9a2 2 0 0 1-1.69-.9L9.6 3.9A2 2 0 0 0 7.93 3H4a2 2 0 0 0-2 2v13a2 2 0 0 0 2 2Z" />
              </svg>
              <span class="node-name">{{ folder.name }}</span>
              <span class="node-badge">{{ folder.items.length }}</span>
            </div>

            <!-- 用例集节点 -->
            <div v-if="folder.open" class="folder-children">
              <div
                v-for="item in folder.items"
                :key="item.id"
                class="tree-node file-node"
                :class="{ active: activeSetId === item.id }"
                :title="`${item.name} · ${item.status === 'confirmed' ? '已入库' : item.status === 'cancelled' ? '已废弃' : '待确认'}`"
                @click="requestSelectCaseSet(item.id)"
                @contextmenu.prevent.stop="onSetContextMenu($event, item.id)"
              >
                <svg class="file-icon case-icon" width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                  <path d="M16 4h2a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2h2" />
                  <rect x="8" y="2" width="8" height="4" rx="1" ry="1" />
                </svg>
                <span class="node-name">{{ item.name }}</span>
                <span
                  class="status-micro-tag"
                  :class="item.status === 'confirmed' ? 'status-confirmed' : item.status === 'cancelled' ? 'status-cancelled' : 'status-pending'"
                >
                  {{ item.status === 'confirmed' ? '已入库' : item.status === 'cancelled' ? '已废弃' : '待确认' }}
                </span>
              </div>
            </div>
          </div>

          <!-- 目录树空态 -->
          <div v-if="!filteredFolders.length" class="tree-empty">
            <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" class="empty-icon">
              <circle cx="11" cy="11" r="8" />
              <line x1="21" y1="21" x2="16.65" y2="16.65" />
            </svg>
            <p>{{ treeSearch.trim() ? `无匹配结果「${treeSearch.trim()}」` : '暂无用例集，点击上方「+ 新建集」开始' }}</p>
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

      <!-- ─── 右侧：主用例工作台 ─── -->
      <main v-if="currentSet" class="nordic-main">
        <!-- 1. 顶栏：就地批量操作置换 (In-Toolbar Transition) -->
        <div class="main-toolbar" :class="{ 'in-batch-mode': selectedCaseIds.length > 0 }">
          <!-- 默认模式顶栏 -->
          <div v-if="selectedCaseIds.length === 0" class="toolbar-default">
            <div class="toolbar-title-group">
              <div class="title-row">
                <span class="main-dataset-title">{{ currentSet.name }}</span>
                <span class="version-tag">共 {{ currentSet.generated_count }} 条</span>
                <span
                  class="status-header-badge"
                  :class="currentSet.status === 'confirmed' ? 'chip-confirmed' : currentSet.status === 'cancelled' ? 'chip-cancelled' : 'chip-countdown'"
                >
                  {{ currentSet.status === 'confirmed' ? '已入库' : currentSet.status === 'cancelled' ? '已废弃' : expiresLabel(currentSet) }}
                </span>
                <span class="asset-type-badge type-dataset">{{ modeMappingLabel }}</span>
              </div>
              <div class="breadcrumb-row">
                <span>测试用例资产</span>
                <span class="sep">/</span>
                <span class="cur">{{ currentSet.name }}</span>
              </div>
            </div>

            <!-- 表格内即时搜索过滤框 (Instant Grid Filter) -->
            <div class="table-search-box">
              <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" class="table-search-icon">
                <circle cx="11" cy="11" r="8" /><line x1="21" y1="21" x2="16.65" y2="16.65" />
              </svg>
              <input v-model="gridSearch" class="table-search-input" placeholder="在用例集中极速筛选 (⌘F)..." aria-label="在用例集中极速筛选" />
              <span v-if="gridSearch" class="grid-search-count mono">{{ displayedCases.length }}/{{ cases.length }}</span>
              <button v-if="gridSearch" class="clear-search-btn" aria-label="清空搜索" @click="gridSearch = ''">✕</button>
            </div>

            <div class="grow"></div>

            <!-- 右侧操作组 -->
            <div class="toolbar-action-group">
              <div class="action-btn-group">
                <button class="btn btn-secondary btn-sm" :disabled="currentSet.status === 'confirmed'" aria-label="新增测试用例" @click="addCase">
                  <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="12" y1="5" x2="12" y2="19" /><line x1="5" y1="12" x2="19" y2="12" /></svg>
                  新增用例
                </button>
                <button class="btn btn-secondary btn-sm" :disabled="currentSet.status === 'confirmed'" aria-label="新增自定义字段列" @click="openAddColModal">
                  <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="12" y1="5" x2="12" y2="19" /><line x1="5" y1="12" x2="19" y2="12" /></svg>
                  新增列
                </button>
              </div>

              <!-- PRD 推导与断言补全 -->
              <div class="action-btn-group">
                <button class="btn btn-secondary btn-sm" aria-label="打开 PRD 用例推导抽屉" @click="openAiGenDrawer">
                  PRD 用例推导向导
                </button>
                <button class="btn btn-secondary btn-sm" :disabled="aiFilling || currentSet.status === 'confirmed'" aria-label="自动补全断言" @click="handleAiFillCase">
                  {{ aiFilling ? '补全中…' : '补全断言与前置' }}
                </button>
              </div>

              <!-- 导入/导出与保存 -->
              <div class="action-btn-group">
                <button class="btn btn-secondary btn-sm" aria-label="导入 Excel 用例" @click="openImportModal()">
                  <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" /><polyline points="17 8 12 3 7 8" /><line x1="12" y1="3" x2="12" y2="15" /></svg>
                  导入 Excel
                </button>
                <n-dropdown trigger="click" :options="exportOptions" @select="handleExportSelect">
                  <button class="btn btn-secondary btn-sm" aria-label="导出用例集菜单">
                    导出 ▾
                  </button>
                </n-dropdown>
                <button
                  class="btn btn-save btn-sm"
                  :class="{ dirty: hasUnsavedChanges, saved: justSaved }"
                  :disabled="!hasUnsavedChanges || savingCases || currentSet.status === 'confirmed'"
                  title="快捷键 Ctrl/⌘ + S"
                  aria-label="保存用例集修改"
                  @click="persistCases"
                >
                  <span v-if="justSaved" class="saved-icon">✓</span>
                  {{ savingCases ? '保存中…' : justSaved ? '已保存' : '保存修改' }}
                  <kbd class="shortcut-key">⌘S</kbd>
                </button>
              </div>

              <!-- 核心入库操作 -->
              <button
                v-if="currentSet.status === 'generated'"
                class="btn btn-primary btn-sm"
                title="确认此用例集入库并执行映射"
                aria-label="确认用例集入库"
                @click="confirmAllCases"
              >
                <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                  <polyline points="20 6 9 17 4 12" />
                </svg>
                确认入库
              </button>
            </div>
          </div>

          <!-- 批量操作置换模式顶栏 (In-Toolbar Transition) -->
          <div v-else class="toolbar-batch">
            <div class="batch-info">
              <span class="batch-count">已选择 <b>{{ selectedCaseIds.length }}</b> / {{ cases.length }} 条用例</span>
            </div>

            <div class="grow"></div>

            <div class="batch-actions">
              <!-- 批量删除 -->
              <button
                v-if="currentSet.status !== 'confirmed'"
                class="btn btn-danger btn-sm"
                aria-label="批量删除勾选用例"
                @click="batchDeleteCases"
              >
                批量删除 ({{ selectedCaseIds.length }})
              </button>

              <!-- 批量映射目标 -->
              <div class="map-select-group">
                <span class="map-label">{{ modeMappingLabel }}:</span>
                <select v-model="mapTargetId" class="map-select" :disabled="mappingTargets.length === 0" aria-label="选择映射目标">
                  <option value="">选择目标数据集/QA</option>
                  <option v-for="target in mappingTargets" :key="target.id" :value="target.id">{{ target.name }}</option>
                </select>
                <button class="btn btn-primary btn-sm" :disabled="!mapTargetId" aria-label="执行批量映射" @click="handleBatchMap">
                  执行映射
                </button>
              </div>

              <button class="btn btn-ghost btn-sm" aria-label="取消选择" @click="selectedCaseIds = []">
                取消选择
              </button>
            </div>
          </div>
        </div>

        <!-- 2. 六大策略分布与自检状态条 -->
        <div class="strategy-strip">
          <div class="strip-left">
            <span class="strip-label">策略覆盖:</span>
            <!-- 策略过滤胶囊 -->
            <div class="strategy-pills-row">
              <span
                class="strategy-pill all-pill"
                :class="{ active: selectedStrategyFilter === '' }"
                @click="selectedStrategyFilter = ''"
              >
                全部 <b class="mono">{{ cases.length }}</b>
              </span>
              <span
                v-for="st in strategyCounts"
                :key="st.name"
                class="strategy-pill"
                :class="[getStrategyTagClass(st.name), { active: selectedStrategyFilter === st.name }]"
                :title="`筛选 ${st.name} 策略`"
                @click="toggleStrategyFilter(st.name)"
              >
                {{ st.name }} <b class="mono">{{ st.count }}</b>
              </span>
            </div>
          </div>

          <div class="grow"></div>

          <!-- 键盘流导航提示 -->
          <div class="keyboard-flow-hint">
            <span class="kbd-hint"><kbd>↑↓←→</kbd> 移动光标</span>
            <span class="kbd-hint"><kbd>Enter</kbd> 就地编辑</span>
            <span class="kbd-hint"><kbd>Space</kbd> 勾选</span>
          </div>

          <span class="strip-divider"></span>

          <div class="strip-right">
            <span v-if="currentSet.checks?.length" class="status-warning-text small">
              自检: {{ currentSet.checks.map(c => c.message).join('; ') }}
            </span>
            <span v-else-if="allStrategiesCovered" class="status-success-text small">
              ✓ 6 大策略完备覆盖
            </span>
            <span v-else class="status-neutral-text small">
              ✓ 策略自检通过
            </span>
            <span class="strip-divider"></span>
            <span class="adoption-rate-text">
              勾选采纳率: <b class="mono">{{ adoptionRate }}%</b>
            </span>
          </div>
        </div>

        <!-- 3. 用例数据表格：高性能虚拟网格 + 键盘流 (Hyper-Speed Virtual Grid) -->
        <div ref="tableContainerRef" class="table-container custom-scroll" tabindex="0" @scroll="onTableScroll">
          <!-- 顶部虚拟占位 -->
          <div v-if="virtualTopPad > 0" :style="{ height: virtualTopPad + 'px' }"></div>

          <table class="nordic-table">
            <thead>
              <tr>
                <th class="th-chk" style="width: 40px">
                  <input v-model="allCasesChecked" type="checkbox" class="clean-checkbox" aria-label="全选所有测试用例" />
                </th>
                <th style="width: 76px">策略</th>
                <th style="width: 68px">级别</th>
                <th style="min-width: 95px">业务模块</th>
                <th style="min-width: 90px">子模块</th>
                <th style="min-width: 100px">功能点</th>
                <th style="min-width: 220px">测试点 / 用例名称 <span class="req-star">*</span></th>
                <th style="min-width: 260px">预期结果 / 断言标准 <span class="req-star">*</span></th>
                <th style="min-width: 140px">前置条件</th>
                <!-- 自定义扩展列 -->
                <th v-for="col in customCols" :key="col.key" class="custom-th" style="min-width: 110px">
                  <div class="th-flex">
                    <span>{{ col.name }}</span>
                    <button class="th-del-btn" title="删除扩展列" :aria-label="`删除扩展列 ${col.name}`" @click.stop="removeCustomCol(col.key)">✕</button>
                  </div>
                </th>
                <th style="width: 80px">映射</th>
                <th style="width: 76px; text-align: right">操作</th>
              </tr>
            </thead>

            <tbody>
              <tr
                v-for="(c, virtualIdx) in virtualRenderRows"
                :key="c.id"
                class="data-row"
                :class="{
                  'row-checked': selectedCaseIds.includes(c.id),
                  'row-incomplete': !c.name.trim() || !c.expected.trim(),
                  'row-focused': focusedCell?.rowIdx === getDisplayedIndex(c)
                }"
                @contextmenu.prevent="onRowContextMenu($event, getOriginalCaseIndex(c))"
                @dblclick="openCaseEditModal(getOriginalCaseIndex(c))"
              >
                <!-- 勾选列 -->
                <td class="td-chk" :class="{ 'cell-cursor': isCellCursor(c, 'chk') }" @click="setCellCursor(c, 'chk')">
                  <input v-model="selectedCaseIds" type="checkbox" :value="c.id" class="clean-checkbox" :aria-label="`勾选用例 ${c.name || c.id}`" />
                </td>

                <!-- 策略列 -->
                <td class="cell-edit" :class="{ 'cell-cursor': isCellCursor(c, 'strategy') }" @click="handleCellClick(c, 'strategy')">
                  <n-select
                    v-if="editingCell?.row === c && editingCell?.field === 'strategy'"
                    v-model:value="c.strategy"
                    :options="strategyOptions"
                    size="small"
                    autofocus
                    @update:value="finishEditing"
                    @blur="finishEditing"
                    @click.stop
                  />
                  <span v-else class="strategy-badge" :class="getStrategyTagClass(c.strategy)">{{ c.strategy }}</span>
                </td>

                <!-- 级别列 -->
                <td class="cell-edit" :class="{ 'cell-cursor': isCellCursor(c, 'priority') }" @click="handleCellClick(c, 'priority')">
                  <n-select
                    v-if="editingCell?.row === c && editingCell?.field === 'priority'"
                    v-model:value="c.priority"
                    :options="priorityOptions"
                    size="small"
                    autofocus
                    @update:value="finishEditing"
                    @blur="finishEditing"
                    @click.stop
                  />
                  <span v-else class="prio-tag" :class="`prio-${c.priority}`">{{ c.priority }}</span>
                </td>

                <!-- 模块 -->
                <td class="cell-edit" :class="{ 'cell-cursor': isCellCursor(c, 'module') }" @click="handleCellClick(c, 'module')">
                  <input
                    v-if="editingCell?.row === c && editingCell?.field === 'module'"
                    v-model="c.module"
                    class="inline-input"
                    placeholder="业务模块..."
                    :aria-label="`编辑用例 ${c.id} 业务模块`"
                    autofocus
                    @blur="finishEditing"
                    @keyup.enter="finishEditing"
                    @keyup.esc="cancelEditing"
                  />
                  <div v-else class="cell-content font-medium" v-html="highlightMatch(c.module)"></div>
                </td>

                <!-- 子模块 -->
                <td class="cell-edit" :class="{ 'cell-cursor': isCellCursor(c, 'submodule') }" @click="handleCellClick(c, 'submodule')">
                  <input
                    v-if="editingCell?.row === c && editingCell?.field === 'submodule'"
                    v-model="c.submodule"
                    class="inline-input"
                    placeholder="子模块..."
                    :aria-label="`编辑用例 ${c.id} 子模块`"
                    autofocus
                    @blur="finishEditing"
                    @keyup.enter="finishEditing"
                    @keyup.esc="cancelEditing"
                  />
                  <div v-else class="cell-content" :class="{ placeholder: !c.submodule }" v-html="highlightMatch(c.submodule || '—')"></div>
                </td>

                <!-- 功能点 -->
                <td class="cell-edit" :class="{ 'cell-cursor': isCellCursor(c, 'feature_point') }" @click="handleCellClick(c, 'feature_point')">
                  <input
                    v-if="editingCell?.row === c && editingCell?.field === 'feature_point'"
                    v-model="c.feature_point"
                    class="inline-input"
                    placeholder="功能点..."
                    :aria-label="`编辑用例 ${c.id} 功能点`"
                    autofocus
                    @blur="finishEditing"
                    @keyup.enter="finishEditing"
                    @keyup.esc="cancelEditing"
                  />
                  <div v-else class="cell-content" :class="{ placeholder: !c.feature_point }" v-html="highlightMatch(c.feature_point || '—')"></div>
                </td>

                <!-- 用例名称 -->
                <td class="cell-edit" :class="{ 'cell-invalid': !c.name.trim(), 'cell-cursor': isCellCursor(c, 'name') }" @click="handleCellClick(c, 'name')">
                  <input
                    v-if="editingCell?.row === c && editingCell?.field === 'name'"
                    v-model="c.name"
                    class="inline-input"
                    placeholder="输入用例名称..."
                    :aria-label="`编辑用例 ${c.id} 名称`"
                    autofocus
                    @blur="finishEditing"
                    @keyup.enter="finishEditing"
                    @keyup.esc="cancelEditing"
                  />
                  <div v-else class="cell-content bold-text" :class="{ placeholder: !c.name.trim() }" v-html="highlightMatch(c.name || '（未命名的测试点）')"></div>
                </td>

                <!-- 预期结果 -->
                <td class="cell-edit" :class="{ 'cell-invalid': !c.expected.trim(), 'cell-cursor': isCellCursor(c, 'expected') }" @click="handleCellClick(c, 'expected')">
                  <input
                    v-if="editingCell?.row === c && editingCell?.field === 'expected'"
                    v-model="c.expected"
                    class="inline-input"
                    placeholder="预期校验结果..."
                    :aria-label="`编辑用例 ${c.id} 预期结果`"
                    autofocus
                    @blur="finishEditing"
                    @keyup.enter="finishEditing"
                    @keyup.esc="cancelEditing"
                  />
                  <div v-else class="cell-content" :class="{ placeholder: !c.expected.trim() }" v-html="highlightMatch(c.expected || '（待输入预期结果）')"></div>
                </td>

                <!-- 前置条件 -->
                <td class="cell-edit" :class="{ 'cell-cursor': isCellCursor(c, 'precondition') }" @click="handleCellClick(c, 'precondition')">
                  <input
                    v-if="editingCell?.row === c && editingCell?.field === 'precondition'"
                    v-model="c.precondition"
                    class="inline-input"
                    placeholder="前置条件..."
                    :aria-label="`编辑用例 ${c.id} 前置条件`"
                    autofocus
                    @blur="finishEditing"
                    @keyup.enter="finishEditing"
                    @keyup.esc="cancelEditing"
                  />
                  <div v-else class="cell-content subtle-text" v-html="highlightMatch(c.precondition || '无')"></div>
                </td>

                <!-- 自定义扩展列 -->
                <td v-for="col in customCols" :key="col.key" class="cell-edit" :class="{ 'cell-cursor': isCellCursor(c, col.key) }" @click="handleExtraClick(c, col.key)">
                  <input
                    v-if="editingExtraCell?.row === c && editingExtraCell?.key === col.key"
                    :value="getCaseExtra(c, col.key)"
                    class="inline-input"
                    :placeholder="col.name"
                    :aria-label="`编辑用例 ${c.id} ${col.name}`"
                    autofocus
                    @input="setCaseExtra(c, col.key, ($event.target as HTMLInputElement).value)"
                    @blur="finishExtraEditing"
                    @keyup.enter="finishExtraEditing"
                    @keyup.esc="cancelExtraEditing"
                  />
                  <div v-else class="cell-content" :class="{ placeholder: !getCaseExtra(c, col.key) }" v-html="highlightMatch(getCaseExtra(c, col.key) || '—')"></div>
                </td>

                <!-- 映射状态 -->
                <td>
                  <span v-if="c.mapped" class="status-tag-green">已映射</span>
                  <span v-else class="status-tag-amber">待补全</span>
                </td>

                <!-- 操作区 -->
                <td class="td-actions">
                  <div class="action-links">
                    <button class="icon-link" title="详细编辑" :aria-label="`详细弹窗编辑用例 ${c.id}`" @click.stop="openCaseEditModal(getOriginalCaseIndex(c))">
                      <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7" /><path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z" /></svg>
                    </button>
                    <button v-if="currentSet.status !== 'confirmed'" class="icon-link danger" title="删除用例" :aria-label="`删除用例 ${c.id}`" @click.stop="deleteCase(getOriginalCaseIndex(c))">
                      <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="3 6 5 6 21 6" /><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2" /></svg>
                    </button>
                  </div>
                </td>
              </tr>

              <!-- 空列表提示 -->
              <tr v-if="!displayedCases.length">
                <td :colspan="11 + customCols.length" class="empty-cell">
                  <div class="empty-message">
                    <span v-if="gridSearch.trim()">未找到匹配「{{ gridSearch.trim() }}」的测试用例。</span>
                    <span v-else-if="selectedStrategyFilter">当前策略「{{ selectedStrategyFilter }}」暂无用例，点击上方「全部」查看所有。</span>
                    <span v-else>当前用例集暂无用例，点击上方「新增用例」或「PRD 用例推导向导」开始录入。</span>
                  </div>
                </td>
              </tr>
            </tbody>
          </table>

          <!-- 底部虚拟占位 -->
          <div v-if="virtualBottomPad > 0" :style="{ height: virtualBottomPad + 'px' }"></div>
        </div>
      </main>

      <!-- ─── 空态页面引导 ─── -->
      <main v-else class="nordic-main empty-main">
        <div class="empty-box">
          <div class="empty-icon-wrapper">
            <svg width="36" height="36" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round">
              <path d="M16 4h2a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2h2" />
              <rect x="8" y="2" width="8" height="4" rx="1" ry="1" />
            </svg>
          </div>
          <h3>尚未选择或创建测试用例集</h3>
          <p>你可以粘贴 PRD 文本由系统按六大策略推导候选用例，或导入已有 Excel 文件进行管理。</p>
          <div class="empty-buttons">
            <button class="btn btn-primary" @click="openAiGenDrawer">
              PRD 用例推导向导
            </button>
            <button class="btn btn-secondary" @click="openImportModal()">
              导入 Excel 用例
            </button>
            <button class="btn btn-ghost" @click="handleCreateCaseSet()">
              + 新建空用例集
            </button>
          </div>
        </div>
      </main>
    </div>

    <!-- ─── 右侧滑出抽屉：PRD 用例推导向导 ─── -->
    <n-drawer v-model:show="showAiGenDrawer" :width="drawerWidth" placement="right">
      <n-drawer-content title="PRD 测试用例推导向导" closable>
        <!-- 步骤指示 -->
        <div class="drawer-step-bar">
          <div class="step-badge" :class="{ active: aiStep === 'config', done: aiStep === 'preview' }">
            <span class="step-idx">1</span>
            <span>需求与策略配置</span>
          </div>
          <span class="step-divider-line"></span>
          <div class="step-badge" :class="{ active: aiStep === 'preview' }">
            <span class="step-idx">2</span>
            <span>候选用例审核与采纳</span>
          </div>
        </div>

        <!-- Step 1：配置与需求输入 -->
        <div v-show="aiStep === 'config'" class="drawer-body">
          <div class="field">
            <label class="field-label">预设 PRD 模板</label>
            <n-select v-model:value="aiPresetIdx" :options="aiPresetOptions" />
          </div>
          <div class="field">
            <label class="field-label">PRD 需求文本 / OpenAPI 接口定义 <span class="req">*</span></label>
            <n-input v-model:value="aiSource" type="textarea" :autosize="{ minRows: 4, maxRows: 8 }" placeholder="支持粘贴 Markdown 文本、接口列表或业务规则描述..." />
          </div>

          <div class="divider-title">六大测试策略配比与生成规模</div>
          <div class="strategy-weights-grid">
            <div v-for="s in STRATEGY_LIST" :key="s" class="weight-item">
              <span class="weight-label">{{ s }}</span>
              <n-input-number v-model:value="aiWeights[s]" :min="0" :max="100" size="small">
                <template #suffix>%</template>
              </n-input-number>
            </div>
          </div>

          <div class="form-row" style="margin-top: 10px">
            <div class="field">
              <label class="field-label">目标生成规模 (<b class="mono">{{ aiCount }}</b> 条)</label>
              <n-slider v-model:value="aiCount" :min="6" :max="45" :step="1" style="margin-top: 6px" />
              <span v-if="aiCount > 30" class="field-hint" style="color: #B45309">单次建议 ≤30 条以保证准确度</span>
              <span v-else class="field-hint">单次上限 45 条</span>
            </div>
            <div class="field">
              <label class="field-label">结构属性自动推导</label>
              <div class="row wrap" style="gap: 14px; font-size: 13px; margin-top: 6px">
                <n-checkbox v-model:checked="aiStruct.precondition">前置条件</n-checkbox>
                <n-checkbox v-model:checked="aiStruct.steps">执行步骤</n-checkbox>
                <n-checkbox v-model:checked="aiStruct.expected">预期断言</n-checkbox>
                <n-checkbox v-model:checked="aiStruct.autoPriority">HX/FHX 定级</n-checkbox>
              </div>
            </div>
          </div>
        </div>

        <!-- Step 2：候选用例审核 -->
        <div v-show="aiStep === 'preview'" class="drawer-body">
          <div class="strategy-strip-mini mb8">
            <span class="small" style="color: #71717A; font-weight: 500">策略分布:</span>
            <div class="row wrap" style="gap: 6px">
              <span v-for="st in aiStrategyCounts" :key="st.name" class="strategy-badge" :class="getStrategyTagClass(st.name)">
                {{ st.name }} <b class="mono">{{ st.count }}</b>
              </span>
            </div>
            <span class="grow"></span>
            <span class="status-success-text small">✓ 6 大策略覆盖</span>
          </div>
          <div class="row-between mb8">
            <span class="bold small">候选用例列表 (已推导 {{ aiCandidates.length }} 条，可修改)</span>
            <button class="link-btn" @click="toggleAllCandidates(!allCandidatesChecked)">全选 / 全不选</button>
          </div>
          <div class="preview-box custom-scroll">
            <table class="nordic-table preview-table">
              <thead>
                <tr>
                  <th style="width: 32px"><input v-model="allCandidatesChecked" type="checkbox" aria-label="全选候选列表" /></th>
                  <th style="width: 60px">策略</th>
                  <th style="width: 55px">级别</th>
                  <th style="width: 80px">模块</th>
                  <th>用例名称</th>
                  <th>预期结果</th>
                  <th style="width: 50px">操作</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="(cand, ci) in aiCandidates" :key="cand.id">
                  <td><input v-model="cand.selected" type="checkbox" :aria-label="`选择候选 ${cand.name}`" /></td>
                  <td><span class="strategy-badge" :class="getStrategyTagClass(cand.strategy)">{{ cand.strategy }}</span></td>
                  <td><span class="prio-tag" :class="`prio-${cand.priority}`">{{ cand.priority }}</span></td>
                  <td><input v-model="cand.module" class="inline-input-clean" aria-label="编辑候选模块" /></td>
                  <td><input v-model="cand.name" class="inline-input-clean" aria-label="编辑候选名称" /></td>
                  <td><input v-model="cand.expected" class="inline-input-clean" aria-label="编辑候选预期" /></td>
                  <td><button class="link-btn danger" aria-label="移除此条候选" @click="removeCandidate(ci)">移除</button></td>
                </tr>
              </tbody>
            </table>
          </div>
        </div>

        <template #footer>
          <div class="drawer-footer-row">
            <n-button v-show="aiStep === 'preview'" @click="aiStep = 'config'">← 返回调整策略</n-button>
            <span class="grow"></span>
            <n-button @click="showAiGenDrawer = false">取消</n-button>
            <n-button v-if="aiStep === 'config'" type="primary" :loading="generatingCases" @click="generateAiCandidates">
              {{ generatingCases ? '正在推导用例…' : '开始用例推导 →' }}
            </n-button>
            <n-button v-else type="primary" :disabled="aiSelectedCount === 0" :loading="committingAi" @click="commitAiCaseSet">
              采纳创建用例集 ({{ aiSelectedCount }} 条)
            </n-button>
          </div>
        </template>
      </n-drawer-content>
    </n-drawer>

    <!-- ─── 弹窗组件 ─── -->
    <!-- 新建用例集弹窗 -->
    <n-modal v-model:show="showCreateSetModal" preset="card" title="新建测试用例集" style="width: 420px; max-width: calc(100vw - 24px)">
      <div class="field">
        <label class="field-label">用例集名称 <span class="req">*</span></label>
        <n-input v-model:value="newSetName" placeholder="例如：支付结算回归用例" autofocus @keyup.enter="createCaseSet" />
      </div>
      <template #footer>
        <div style="display: flex; justify-content: flex-end; gap: 8px">
          <n-button @click="showCreateSetModal = false">取消</n-button>
          <n-button type="primary" :loading="creatingSet" @click="createCaseSet">立即创建</n-button>
        </div>
      </template>
    </n-modal>

    <!-- Excel 导入弹窗 -->
    <ImportCasesExcelModal
      v-model:show="showImportModal"
      :current-set="currentSet"
      :folder-id="importFolderId"
      @imported="onExcelImported"
    />

    <!-- 用例结构化编辑弹窗 -->
    <n-modal v-model:show="showEditCaseModal" preset="card" :title="`编辑用例 · ${editDraft.id || '新用例'}`" style="width: 620px; max-width: calc(100vw - 24px)">
      <div class="form-row">
        <div class="field">
          <label class="field-label">测试策略 <span class="req">*</span></label>
          <n-select v-model:value="editDraft.strategy" :options="strategyOptions" />
        </div>
        <div class="field">
          <label class="field-label">优先级 <span class="req">*</span></label>
          <n-select v-model:value="editDraft.priority" :options="priorityOptions" />
        </div>
      </div>
      <div class="form-row">
        <div class="field">
          <label class="field-label">业务模块 <span class="req">*</span></label>
          <n-input v-model:value="editDraft.module" placeholder="如 登录 / 支付" />
        </div>
        <div class="field">
          <label class="field-label">子模块</label>
          <n-input v-model:value="editDraft.submodule" placeholder="可选，如 结算" />
        </div>
      </div>
      <div class="form-row">
        <div class="field">
          <label class="field-label">功能点</label>
          <n-input v-model:value="editDraft.feature_point" placeholder="可选" />
        </div>
        <div class="field">
          <label class="field-label">用例名称 / 测试点 <span class="req">*</span></label>
          <n-input v-model:value="editDraft.name" placeholder="一句话描述被测目标" />
        </div>
      </div>
      <div class="field">
        <label class="field-label">预期结果 / 断言标准 <span class="req">*</span></label>
        <n-input v-model:value="editDraft.expected" type="textarea" :autosize="{ minRows: 3, maxRows: 6 }" placeholder="可校验的预期行为..." />
      </div>
      <div class="field">
        <label class="field-label">前置条件</label>
        <n-input v-model:value="editDraft.precondition" placeholder="可选" />
      </div>
      <template v-if="customCols.length">
        <div class="divider-title">自定义属性</div>
        <div class="form-row">
          <div v-for="col in customCols" :key="col.key" class="field">
            <label class="field-label">{{ col.name }} ({{ col.key }})</label>
            <n-input :value="String(editDraft[col.key] ?? '')" @update:value="editDraft[col.key] = $event" />
          </div>
        </div>
      </template>
      <template #footer>
        <div style="display: flex; justify-content: flex-end; gap: 8px">
          <n-button @click="showEditCaseModal = false">取消</n-button>
          <n-button type="primary" @click="saveCaseEdit">保存修改</n-button>
        </div>
      </template>
    </n-modal>

    <!-- 新增扩展字段弹窗 -->
    <n-modal v-model:show="showAddColModal" preset="card" title="新增用例字段" style="width: 420px; max-width: calc(100vw - 24px)">
      <div class="field">
        <label class="field-label">字段 Key (英文字母/下划线) <span class="req">*</span></label>
        <n-input v-model:value="newColKey" class="mono" placeholder="如 assert_type" />
      </div>
      <div class="field">
        <label class="field-label">显示名称 <span class="req">*</span></label>
        <n-input v-model:value="newColName" placeholder="如 断言方式" />
      </div>
      <template #footer>
        <div style="display: flex; justify-content: flex-end; gap: 8px">
          <n-button @click="showAddColModal = false">取消</n-button>
          <n-button type="primary" :loading="addingCol" @click="addCustomCol">确认添加</n-button>
        </div>
      </template>
    </n-modal>

    <!-- 通用输入弹窗 -->
    <n-modal v-model:show="promptState.show" preset="card" :title="promptState.title" style="width: 400px; max-width: calc(100vw - 24px)">
      <div class="field">
        <n-input v-model:value="promptState.value" :placeholder="promptState.placeholder" autofocus @keyup.enter="submitPrompt" />
      </div>
      <template #footer>
        <div style="display: flex; justify-content: flex-end; gap: 8px">
          <n-button @click="promptState.show = false">取消</n-button>
          <n-button type="primary" @click="submitPrompt">确定</n-button>
        </div>
      </template>
    </n-modal>

    <!-- 右键上下文菜单 -->
    <n-dropdown
      placement="bottom-start"
      trigger="manual"
      :x="ctxSet.x"
      :y="ctxSet.y"
      :options="ctxSetOptions"
      :show="ctxSet.show"
      @select="handleSetMenuSelect"
      @clickoutside="ctxSet.show = false"
    />
    <n-dropdown
      placement="bottom-start"
      trigger="manual"
      :x="ctxFolder.x"
      :y="ctxFolder.y"
      :options="ctxFolderOptions"
      :show="ctxFolder.show"
      @select="handleFolderMenuSelect"
      @clickoutside="ctxFolder.show = false"
    />
    <n-dropdown
      placement="bottom-start"
      trigger="manual"
      :x="ctxRow.x"
      :y="ctxRow.y"
      :options="ctxRowOptions"
      :show="ctxRow.show"
      @select="handleRowMenuSelect"
      @clickoutside="ctxRow.show = false"
    />
  </div>
</template>

<script setup lang="ts">
import { ref, reactive, computed, onMounted, onUnmounted, watch } from 'vue'
import { useMessage, useDialog, type DropdownOption } from 'naive-ui'
import { api } from '../api/http'
import type { CaseFolder, CaseSet, KnowledgeBase, TestCase } from '../api/types'
import { useModeStore } from '../stores/mode'
import ImportCasesExcelModal from '../components/modals/ImportCasesExcelModal.vue'

interface MappingTarget {
  id: string
  name: string
}

interface CustomCol {
  key: string
  name: string
}

type AiCandidate = TestCase & { selected: boolean }

const STRATEGY_LIST: Array<TestCase['strategy']> = ['正向', '反向', '边界', '等价', '状态', '场景']
const PRIORITY_LIST: Array<TestCase['priority']> = ['HX', 'FHX', 'BJ', 'YC', 'ZD', 'BL']
const PRIORITY_LABELS: Record<string, string> = { HX: '核心', FHX: '非核心', BJ: '边界', YC: '异常', ZD: '中断', BL: '遍历' }
const strategyOptions = STRATEGY_LIST.map(s => ({ label: s, value: s }))
const priorityOptions = PRIORITY_LIST.map(p => ({ label: `${p} ${PRIORITY_LABELS[p]}`, value: p }))

const message = useMessage()
const dialog = useDialog()
const modeStore = useModeStore()
const treeSearch = ref('')
const gridSearch = ref('')
const activeSetId = ref('')
const mapTargetId = ref('')
const mappingTargets = ref<MappingTarget[]>([])
const caseSets = ref<CaseSet[]>([])
const cases = ref<TestCase[]>([])
const selectedCaseIds = ref<string[]>([])
const savingCases = ref(false)
const justSaved = ref(false)
const hasUnsavedChanges = ref(false)
const editingCell = ref<{ row: TestCase; field: keyof TestCase; original: string } | null>(null)
const focusedCell = ref<{ rowIdx: number; field: string } | null>(null)
const tableContainerRef = ref<HTMLElement | null>(null)
const showCreateSetModal = ref(false)
const showImportModal = ref(false)
const importFolderId = ref('')
const newSetName = ref('')
const creatingSet = ref(false)
const createTargetFolderId = ref('')
const generatingCases = ref(false)
const ROOT_FOLDER_ID = 'case-sets'
type TreeFolder = { id: string; name: string; open: boolean; items: Array<{ id: string; name: string; status: CaseSet['status'] }> }
const folders = ref<TreeFolder[]>([{ id: ROOT_FOLDER_ID, name: '用例集', open: true, items: [] }])
const folderRecords = ref<CaseFolder[]>([])
const selectedStrategyFilter = ref<string>('')

// ─── 侧边栏宽度拖拽调整 ───
const TREE_W_KEY = 'ae_ft_w_cases_nordic'
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

const drawerWidth = computed(() => (typeof window !== 'undefined' && window.innerWidth <= 720 ? '100%' : 620))

// ─── 自定义扩展列 ───
const customColsMap = ref<Record<string, CustomCol[]>>({})
const editingExtraCell = ref<{ row: TestCase; key: string; original: string } | null>(null)

// ─── 弹窗状态 ───
const showEditCaseModal = ref(false)
const editCaseIdx = ref(-1)
const editDraft = ref<TestCase & Record<string, unknown>>({ id: '', strategy: '正向', priority: 'FHX', module: '', name: '', expected: '', precondition: '' })

const showAddColModal = ref(false)
const newColKey = ref('')
const newColName = ref('')
const addingCol = ref(false)

const promptState = reactive({ show: false, title: '', value: '', placeholder: '' })
let promptSubmit: ((val: string) => void | Promise<void>) | null = null

const ctxSet = reactive({ show: false, x: 0, y: 0, setId: '' })
const ctxFolder = reactive({ show: false, x: 0, y: 0, folderId: '' })
const ctxRow = reactive({ show: false, x: 0, y: 0, idx: -1 })

// ─── PRD 推导抽屉 ───
const PRD_PRESETS = [
  { name: '收银台与快捷退款业务规范', text: '收银台支持余额、银行卡快捷支付与企业对公转账。单笔提现上限 5 万元，单日上限 20 万元。连续输错密码 5 次锁定 2 小时，人脸解锁。退款 1-3 工作日原路退回。' },
  { name: '用户中心与双因子认证 (2FA)', text: '支持账密、短信验证码及扫码登录。登录失败 3 次出图形验证码，失败 5 次锁定 15 分钟。敏感操作需二次验证短信验证码。' },
  { name: '营销满减优惠券结算规则', text: '支持满减券、折扣券及免邮券。一笔订单仅能使用一张主券。发生部分退款时按商品实付比例分摊券金额。' },
]
const showAiGenDrawer = ref(false)
const aiStep = ref<'config' | 'preview'>('config')
const aiPresetIdx = ref(0)
const aiSource = ref(PRD_PRESETS[0].text)
const aiWeights = reactive<Record<TestCase['strategy'], number>>({ 正向: 40, 反向: 25, 边界: 15, 等价: 10, 状态: 5, 场景: 5 })
const aiCount = ref(12)
const aiStruct = reactive({ precondition: true, steps: true, expected: true, autoPriority: true })
const aiCandidates = ref<AiCandidate[]>([])
const committingAi = ref(false)

const currentSet = computed(() => caseSets.value.find(item => item.id === activeSetId.value) || caseSets.value[0])
const filteredFolders = computed(() => {
  const keyword = treeSearch.value.trim().toLowerCase()
  if (!keyword) return folders.value
  return folders.value.map(folder => ({
    ...folder,
    items: folder.items.filter(item => item.name.toLowerCase().includes(keyword)),
  })).filter(folder => folder.items.length > 0)
})

const strategyCounts = computed(() => {
  return STRATEGY_LIST.map(strategy => ({ name: strategy, count: cases.value.filter(item => item.strategy === strategy).length }))
})

const allStrategiesCovered = computed(() => {
  return strategyCounts.value.every(s => s.count > 0)
})

function toggleStrategyFilter(strategy: string) {
  if (selectedStrategyFilter.value === strategy) {
    selectedStrategyFilter.value = ''
  } else {
    selectedStrategyFilter.value = strategy
  }
}

// ─── 即时搜索过滤 + 虚拟滚动 (Instant Filter & Virtual Scrolling) ───
const displayedCases = computed(() => {
  let list = cases.value
  if (selectedStrategyFilter.value) {
    list = list.filter(c => c.strategy === selectedStrategyFilter.value)
  }
  const q = gridSearch.value.trim().toLowerCase()
  if (q) {
    list = list.filter(c =>
      c.name.toLowerCase().includes(q) ||
      c.expected.toLowerCase().includes(q) ||
      c.module.toLowerCase().includes(q) ||
      (c.submodule && c.submodule.toLowerCase().includes(q)) ||
      (c.feature_point && c.feature_point.toLowerCase().includes(q)) ||
      (c.precondition && c.precondition.toLowerCase().includes(q)) ||
      c.strategy.toLowerCase().includes(q),
    )
  }
  return list
})

function getOriginalCaseIndex(caseItem: TestCase): number {
  return cases.value.findIndex(c => c.id === caseItem.id)
}
function getDisplayedIndex(caseItem: TestCase): number {
  return displayedCases.value.findIndex(c => c.id === caseItem.id)
}

// 虚拟滚动状态
const ROW_HEIGHT = 41
const scrollTop = ref(0)
const viewportHeight = ref(600)
const BUFFER_SIZE = 8

const startIndex = computed(() => Math.max(0, Math.floor(scrollTop.value / ROW_HEIGHT) - BUFFER_SIZE))
const endIndex = computed(() => Math.min(displayedCases.value.length, Math.ceil((scrollTop.value + viewportHeight.value) / ROW_HEIGHT) + BUFFER_SIZE))

const virtualTopPad = computed(() => startIndex.value * ROW_HEIGHT)
const virtualBottomPad = computed(() => Math.max(0, (displayedCases.value.length - endIndex.value) * ROW_HEIGHT))

const virtualRenderRows = computed(() => {
  if (displayedCases.value.length < 40) return displayedCases.value
  return displayedCases.value.slice(startIndex.value, endIndex.value)
})

function onTableScroll(e: Event) {
  const target = e.target as HTMLElement
  scrollTop.value = target.scrollTop
  viewportHeight.value = target.clientHeight || 600
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
  const base = ['chk', 'strategy', 'priority', 'module', 'submodule', 'feature_point', 'name', 'expected', 'precondition']
  const extras = customCols.value.map(c => c.key)
  return [...base, ...extras]
})

function isCellCursor(row: TestCase, field: string): boolean {
  if (!focusedCell.value) return false
  const idx = getDisplayedIndex(row)
  return focusedCell.value.rowIdx === idx && focusedCell.value.field === field
}

function setCellCursor(row: TestCase, field: string) {
  const idx = getDisplayedIndex(row)
  focusedCell.value = { rowIdx: idx, field }
}

function handleCellClick(row: TestCase, field: keyof TestCase) {
  setCellCursor(row, String(field))
  editCell(row, field)
}

function handleExtraClick(row: TestCase, key: string) {
  setCellCursor(row, key)
  editExtraCell(row, key)
}

function onWorkbenchKeydown(e: KeyboardEvent) {
  if (editingCell.value || editingExtraCell.value) {
    if (e.key === 'Escape') {
      cancelEditing()
      cancelExtraEditing()
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
    if (['ArrowDown', 'ArrowUp', 'ArrowLeft', 'ArrowRight'].includes(e.key) && displayedCases.value.length) {
      focusedCell.value = { rowIdx: 0, field: 'name' }
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
        focusedCell.value = { rowIdx: rowIdx - 1, field }
        scrollToFocusedRow(rowIdx - 1)
        e.preventDefault()
      }
      break
    case 'ArrowDown':
      if (rowIdx < displayedCases.value.length - 1) {
        focusedCell.value = { rowIdx: rowIdx + 1, field }
        scrollToFocusedRow(rowIdx + 1)
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
        else if (rowIdx > 0) focusedCell.value = { rowIdx: rowIdx - 1, field: fields[fields.length - 1] }
      } else {
        if (fIdx < fields.length - 1) focusedCell.value = { rowIdx, field: fields[fIdx + 1] }
        else if (rowIdx < displayedCases.value.length - 1) focusedCell.value = { rowIdx: rowIdx + 1, field: fields[0] }
      }
      break
    case ' ':
      e.preventDefault()
      if (displayedCases.value[rowIdx]) {
        toggleCaseChecked(displayedCases.value[rowIdx])
      }
      break
    case 'Enter':
      e.preventDefault()
      if (displayedCases.value[rowIdx] && field !== 'chk') {
        const row = displayedCases.value[rowIdx]
        if (customCols.value.some(c => c.key === field)) {
          editExtraCell(row, field)
        } else {
          editCell(row, field as keyof TestCase)
        }
      }
      break
  }
}

function scrollToFocusedRow(idx: number) {
  const container = tableContainerRef.value
  if (!container) return
  const targetTop = idx * ROW_HEIGHT
  if (targetTop < container.scrollTop) {
    container.scrollTop = targetTop
  } else if (targetTop + ROW_HEIGHT > container.scrollTop + container.clientHeight) {
    container.scrollTop = targetTop - container.clientHeight + ROW_HEIGHT + 40
  }
}

const adoptionRate = computed(() => Math.round((selectedCaseIds.value.length / (cases.value.length || 1)) * 100))
const mapTarget = computed<'dataset' | 'gold_qa'>(() => modeStore.mode === 'rag' ? 'gold_qa' : 'dataset')
const modeMappingLabel = computed(() => modeStore.mode === 'rag' ? '映射至黄金 QA' : '映射至基准数据集')

const customCols = computed<CustomCol[]>(() => (currentSet.value ? customColsMap.value[currentSet.value.id] ?? [] : []))

const allCasesChecked = computed({
  get: () => cases.value.length > 0 && selectedCaseIds.value.length === cases.value.length,
  set: (val: boolean) => { selectedCaseIds.value = val ? cases.value.map(c => c.id) : [] },
})

const createSetMenuOptions: DropdownOption[] = [
  { label: 'PRD 用例推导向导', key: 'ai' },
  { label: '导入 Excel 用例', key: 'import' },
  { label: '下载 Excel 模板', key: 'template' },
  { label: '新建空用例集', key: 'empty' },
]

const exportOptions: DropdownOption[] = [
  { label: '导出 Excel (.xlsx)', key: 'xlsx' },
  { label: '导出 XMind (.xmind)', key: 'xmind' },
]

function handleExportSelect(key: string | number) {
  if (key === 'xlsx') exportXlsx()
  else if (key === 'xmind') exportXmind()
}

const ctxSetOptions = computed<DropdownOption[]>(() => {
  const set = caseSets.value.find(s => s.id === ctxSet.setId)
  const opts: DropdownOption[] = []
  if (set?.status === 'generated') opts.push({ label: '确认入库此用例集', key: 'confirm' })
  opts.push(
    { label: '批量映射到评测集', key: 'map' },
    { label: '导入 Excel (.xlsx)', key: 'import' },
    { label: '导出 Excel (.xlsx)', key: 'export' },
    { label: '导出 XMind (.xmind)', key: 'export-xmind' },
    { label: '复制用例集 ID', key: 'copy-id' },
    { type: 'divider', key: 'd1' },
    { label: '重命名', key: 'rename' },
    { label: '废弃用例集', key: 'cancel', props: { style: 'color: #DC2626' } },
  )
  return opts
})

const ctxFolderOptions: DropdownOption[] = [
  { label: '在此新建用例集', key: 'new-set' },
  { label: '新建子目录', key: 'new-folder' },
  { label: '导入 Excel 到此目录', key: 'import' },
  { type: 'divider', key: 'd1' },
  { label: '重命名目录', key: 'rename' },
  { label: '删除目录', key: 'delete', props: { style: 'color: #DC2626' } },
]

const ctxRowOptions = computed<DropdownOption[]>(() => {
  const row = cases.value[ctxRow.idx]
  const checked = row ? selectedCaseIds.value.includes(row.id) : false
  const readonly = currentSet.value?.status === 'confirmed'
  const opts: DropdownOption[] = [
    { label: checked ? '取消勾选' : '勾选本行', key: 'toggle-check' },
    { label: '详细编辑', key: 'edit' },
  ]
  if (!readonly) opts.push({ label: '补全属性', key: 'ai-fill' })
  opts.push({ label: '复制为 JSON', key: 'copy' })
  if (!readonly) {
    opts.push(
      { type: 'divider', key: 'd1' },
      { label: '上方插入新用例', key: 'insert-above' },
      { label: '下方插入新用例', key: 'insert' },
      { label: '创建用例副本', key: 'duplicate' },
      { label: '删除本用例', key: 'delete', props: { style: 'color: #DC2626' } },
    )
  }
  return opts
})

const aiPresetOptions = PRD_PRESETS.map((p, i) => ({ label: p.name, value: i }))
const aiWeightTotal = computed(() => STRATEGY_LIST.reduce((sum, s) => sum + (Number(aiWeights[s]) || 0), 0))
const aiSelectedCount = computed(() => aiCandidates.value.filter(c => c.selected).length)
const aiStrategyCounts = computed(() => STRATEGY_LIST.map(s => ({ name: s, count: aiCandidates.value.filter(c => c.strategy === s).length })))
const allCandidatesChecked = computed({
  get: () => aiCandidates.value.length > 0 && aiCandidates.value.every(c => c.selected),
  set: (val: boolean) => { aiCandidates.value.forEach(c => { c.selected = val }) },
})

function persistFolderId(folderId: string): string | null {
  return folderId && folderId !== ROOT_FOLDER_ID ? folderId : null
}

function expiresLabel(set: CaseSet): string {
  if (!set.expires_at) return '待确认'
  const ms = new Date(set.expires_at).getTime() - Date.now()
  if (Number.isNaN(ms)) return '待确认'
  if (ms <= 0) return '确认窗口已过期'
  const hours = Math.floor(ms / 3_600_000)
  return `剩余 ${hours}h 确认`
}

function normalizeStrategy(raw: string | undefined): TestCase['strategy'] {
  if (raw === '等价类' || raw === '等价') return '等价'
  if (raw === '状态迁移' || raw === '状态') return '状态'
  if (raw === '正向' || raw === '反向' || raw === '边界' || raw === '场景') return raw
  return '正向'
}

function normalizeLoadedCases(rows: TestCase[]): TestCase[] {
  return rows.map(row => ({
    ...row,
    strategy: normalizeStrategy(row.strategy),
    pending: row.pending ?? Boolean(row.pending_complete),
  }))
}

function syncCaseSetTree(list: CaseSet[]) {
  const mapped = list.map(item => ({ id: item.id, name: item.name, status: item.status, folder_id: item.folder_id || null }))
  const openState = new Map(folders.value.map(folder => [folder.id, folder.open]))
  const next: TreeFolder[] = [
    {
      id: ROOT_FOLDER_ID,
      name: '用例集',
      open: openState.get(ROOT_FOLDER_ID) ?? true,
      items: mapped.filter(item => !item.folder_id).map(({ id, name, status }) => ({ id, name, status })),
    },
  ]
  for (const folder of folderRecords.value) {
    next.push({
      id: folder.id,
      name: folder.name,
      open: openState.get(folder.id) ?? true,
      items: mapped.filter(item => item.folder_id === folder.id).map(({ id, name, status }) => ({ id, name, status })),
    })
  }
  folders.value = next
}

function normalizeColumnSchema(schema: unknown): CustomCol[] {
  if (!Array.isArray(schema)) return []
  return schema
    .filter((c: any) => c && typeof c.key === 'string' && c.key)
    .map((c: any) => ({ key: String(c.key), name: String(c.name || c.key) }))
}

function getCaseExtra(row: TestCase, key: string): string {
  return String((row as unknown as Record<string, unknown>)[key] ?? '')
}
function setCaseExtra(row: TestCase, key: string, val: string) {
  ;(row as unknown as Record<string, unknown>)[key] = val
}

function editExtraCell(row: TestCase, key: string) {
  if (currentSet.value?.status === 'confirmed') return
  editingExtraCell.value = { row, key, original: getCaseExtra(row, key) }
}
function finishExtraEditing() {
  editingExtraCell.value = null
  hasUnsavedChanges.value = true
}
function cancelExtraEditing() {
  const cell = editingExtraCell.value
  if (cell) setCaseExtra(cell.row, cell.key, cell.original)
  editingExtraCell.value = null
}

function editCell(row: TestCase, field: keyof TestCase) {
  if (currentSet.value?.status === 'confirmed') return
  editingCell.value = { row, field, original: String(row[field] ?? '') }
}

function finishEditing() {
  editingCell.value = null
  hasUnsavedChanges.value = true
}

function cancelEditing() {
  const cell = editingCell.value
  if (cell) {
    ;(cell.row as unknown as Record<string, unknown>)[cell.field] = cell.original
  }
  editingCell.value = null
}

async function selectCaseSet(id: string) {
  activeSetId.value = id
  try {
    const detail = await api.cases.getSet(id)
    const index = caseSets.value.findIndex(item => item.id === id)
    if (index !== -1) caseSets.value[index] = { ...caseSets.value[index], ...detail }
    cases.value = normalizeLoadedCases(detail.cases || [])
    customColsMap.value[id] = normalizeColumnSchema((detail as CaseSet & Record<string, unknown>).column_schema)
    selectedCaseIds.value = cases.value.filter(item => item.selected || !item.pending).map(item => item.id)
    hasUnsavedChanges.value = false
  } catch (err: any) {
    cases.value = []
    selectedCaseIds.value = []
    message.error(err.message || '加载用例集失败')
  }
}

function requestSelectCaseSet(id: string): Promise<boolean> {
  if (!id || id === activeSetId.value) return Promise.resolve(false)
  if (!hasUnsavedChanges.value) {
    return selectCaseSet(id).then(() => true)
  }
  return new Promise(resolve => {
    dialog.warning({
      title: '未保存的修改',
      content: '当前用例集有未保存的编辑，是否保存后切换？',
      positiveText: '保存并切换',
      negativeText: '放弃修改',
      onPositiveClick: async () => {
        const ok = await persistCases()
        if (ok) {
          await selectCaseSet(id)
          resolve(true)
        } else {
          resolve(false)
        }
      },
      onNegativeClick: async () => {
        await selectCaseSet(id)
        resolve(true)
      },
      onClose: () => resolve(false),
      onMaskClick: () => resolve(false),
    })
  })
}

function getStrategyTagClass(strategy: TestCase['strategy']) {
  switch (strategy) {
    case '正向': return 'st-positive'
    case '反向': return 'st-negative'
    case '边界': return 'st-boundary'
    case '等价': return 'st-equivalence'
    case '状态': return 'st-state'
    default: return 'st-scenario'
  }
}

function addCase() {
  if (!currentSet.value || currentSet.value.status === 'confirmed') return
  const item: TestCase = {
    id: `c-${Date.now()}`,
    strategy: '正向',
    priority: 'FHX',
    module: '通用',
    name: '',
    expected: '',
    precondition: '',
    mapped: false,
    pending: false,
  }
  cases.value.push(item)
  selectedCaseIds.value.push(item.id)
  hasUnsavedChanges.value = true
  message.info('已新增用例，填写后点击“保存修改”落库')
}

function deleteCase(index: number) {
  if (currentSet.value?.status === 'confirmed') return
  const [removed] = cases.value.splice(index, 1)
  if (removed) selectedCaseIds.value = selectedCaseIds.value.filter(id => id !== removed.id)
  hasUnsavedChanges.value = true
  message.info('已删除用例，保存后生效')
}

async function persistCases(): Promise<boolean> {
  if (!currentSet.value || savingCases.value) return false
  savingCases.value = true
  try {
    const saved = await api.cases.saveCases(currentSet.value.id, cases.value)
    cases.value = saved
    const set = caseSets.value.find(item => item.id === currentSet.value!.id)
    if (set) set.generated_count = saved.length
    hasUnsavedChanges.value = false
    justSaved.value = true
    setTimeout(() => { justSaved.value = false }, 1800)
    message.success('已保存用例集修改')
    return true
  } catch (err: any) {
    message.error(err.message || '保存用例失败')
    return false
  } finally {
    savingCases.value = false
  }
}

function handleCreateCaseSet(folderId = '') {
  createTargetFolderId.value = folderId
  newSetName.value = ''
  showCreateSetModal.value = true
}

async function createCaseSet() {
  const name = newSetName.value.trim()
  if (!name) {
    message.warning('请输入用例集名称')
    return
  }
  creatingSet.value = true
  try {
    const created = await api.cases.createSet({ name, folder_id: persistFolderId(createTargetFolderId.value) })
    caseSets.value.unshift(created)
    syncCaseSetTree(caseSets.value)
    showCreateSetModal.value = false
    await selectCaseSet(created.id)
    message.success('用例集创建成功')
  } catch (err: any) {
    message.error(err.message || '创建失败')
  } finally {
    creatingSet.value = false
  }
}

function openAiGenDrawer() {
  aiStep.value = 'config'
  aiPresetIdx.value = 0
  aiSource.value = PRD_PRESETS[0].text
  aiCandidates.value = []
  showAiGenDrawer.value = true
}

watch(aiPresetIdx, (idx) => {
  aiSource.value = PRD_PRESETS[idx]?.text || ''
})

const STRATEGY_CASE_HINTS: Record<TestCase['strategy'], { name: string; expected: string }> = {
  正向: { name: '主链路正常流程验证', expected: '业务处理成功并返回预期结果' },
  反向: { name: '非法输入与异常操作拦截', expected: '系统拒绝并返回明确错误提示' },
  边界: { name: '临界值与极限条件校验', expected: '按限额/边界规则正确处理' },
  等价: { name: '等价类代表性输入覆盖', expected: '同类输入得到一致处理结果' },
  状态: { name: '状态机迁移与幂等验证', expected: '状态流转正确且重复请求幂等' },
  场景: { name: '端到端业务场景串联', expected: '全链路最终状态一致' },
}
const MODULE_POOL = ['收银台', '退款中心', '通用']

function buildLocalCandidates(count: number): AiCandidate[] {
  const total = aiWeightTotal.value || 100
  const quotas = STRATEGY_LIST.map(s => ((aiWeights[s] || 0) / total) * count)
  const base = quotas.map(q => Math.floor(q))
  let remain = count - base.reduce((a, b) => a + b, 0)
  const byRemainder = quotas.map((q, i) => ({ i, r: q - Math.floor(q) })).sort((a, b) => b.r - a.r)
  for (const item of byRemainder) {
    if (remain <= 0) break
    base[item.i] += 1
    remain -= 1
  }
  const result: AiCandidate[] = []
  let seq = 0
  STRATEGY_LIST.forEach((s, i) => {
    for (let k = 0; k < base[i]; k++) {
      seq += 1
      const hint = STRATEGY_CASE_HINTS[s]
      result.push({
        id: `c-ai-${Date.now()}-${seq}`,
        strategy: s,
        priority: aiStruct.autoPriority ? (seq <= Math.ceil(count * 0.25) ? 'HX' : 'FHX') : 'FHX',
        module: MODULE_POOL[seq % MODULE_POOL.length],
        name: `${s}用例 #${seq}：${hint.name}`,
        expected: aiStruct.expected ? hint.expected : '',
        precondition: aiStruct.precondition ? '系统处于就绪状态' : '',
        steps: aiStruct.steps ? '1. 准备测试数据；2. 执行被测操作；3. 校验结果与副作用' : '',
        mapped: false,
        pending: false,
        selected: true,
      })
    }
  })
  return result
}

async function generateAiCandidates() {
  const source = aiSource.value.trim()
  if (!source) {
    message.warning('请填写 PRD / OpenAPI 内容')
    return
  }
  if (aiWeightTotal.value <= 0) {
    message.warning('策略配比之和需大于 0')
    return
  }
  generatingCases.value = true
  try {
    let items: AiCandidate[]
    if (api.isMock()) {
      await new Promise(resolve => setTimeout(resolve, 400))
      items = buildLocalCandidates(aiCount.value)
    } else {
      const raw = await api.cases.generateCases({
        source_text: source,
        strategy_weights: {
          positive: aiWeights['正向'],
          negative: aiWeights['反向'],
          boundary: aiWeights['边界'],
          equivalence: aiWeights['等价'],
          state: aiWeights['状态'],
          scenario: aiWeights['场景'],
        },
        complexity: aiCount.value > 30 ? 'high' : 'medium',
        max_count: aiCount.value,
      })
      items = raw.map((item, index) => ({
        ...item,
        id: item.id || `c-ai-${Date.now()}-${index + 1}`,
        strategy: item.strategy || '正向',
        priority: item.priority || 'FHX',
        module: item.module || '未分类',
        name: item.name || `候选用例 #${index + 1}`,
        expected: item.expected || '',
        selected: true,
      }))
      if (!items.length) throw new Error('未返回候选用例')
    }
    aiCandidates.value = items
    aiStep.value = 'preview'
  } catch (err: any) {
    message.error(err.message || '推导用例失败')
  } finally {
    generatingCases.value = false
  }
}

function removeCandidate(idx: number) {
  aiCandidates.value.splice(idx, 1)
}

function toggleAllCandidates(checked: boolean) {
  aiCandidates.value.forEach(c => { c.selected = checked })
}

async function commitAiCaseSet() {
  const selected = aiCandidates.value.filter(c => c.selected)
  if (!selected.length) return
  committingAi.value = true
  try {
    const presetName = PRD_PRESETS[aiPresetIdx.value]?.name || 'PRD 推导'
    const created = await api.cases.createSet({ name: `${presetName}`.slice(0, 30) })
    const payload: TestCase[] = selected.map(({ selected: _sel, ...rest }) => rest)
    try {
      await api.cases.saveCases(created.id, payload)
    } catch (saveErr) {
      try {
        await api.cases.cancelSet(created.id, '用例写入失败，自动回滚')
      } catch {}
      throw saveErr
    }
    created.generated_count = payload.length
    caseSets.value.unshift(created)
    syncCaseSetTree(caseSets.value)
    showAiGenDrawer.value = false
    await selectCaseSet(created.id)
    message.success(`已创建用例集「${created.name}」（${selected.length} 条用例）`)
  } catch (err: any) {
    message.error(err.message || '创建用例集失败')
  } finally {
    committingAi.value = false
  }
}

const aiFilling = ref(false)

function applyFillCandidates(candidates: Array<Partial<TestCase> & { id: string }>): number {
  let applied = 0
  candidates.forEach(candidate => {
    const row = cases.value.find(item => item.id === candidate.id)
    if (!row) return
    const target = row as TestCase & Record<string, unknown>
    Object.entries(candidate).forEach(([key, value]) => {
      if (key === 'id' || value == null) return
      const current = target[key]
      if (current == null || current === '') {
        target[key] = value
      }
    })
    applied += 1
  })
  if (applied > 0) hasUnsavedChanges.value = true
  return applied
}

async function requestAiFill(ids: string[]): Promise<number> {
  if (!currentSet.value) return 0
  aiFilling.value = true
  try {
    const candidates = await api.cases.aiFillCases(currentSet.value.id, { case_ids: ids })
    return applyFillCandidates(candidates)
  } catch (err: any) {
    message.error(err.message || '补全失败')
    return 0
  } finally {
    aiFilling.value = false
  }
}

async function handleAiFillCase() {
  if (currentSet.value?.status === 'confirmed') {
    message.warning('已确认入库的用例集不可修改')
    return
  }
  if (!currentSet.value) return
  const ids = selectedCaseIds.value.filter(id => cases.value.some(item => item.id === id))
  if (!ids.length) {
    message.warning('请先勾选需要补全的用例行')
    return
  }
  const applied = await requestAiFill(ids)
  if (applied > 0) message.success(`已生成 ${applied} 条补全候选，点击“保存修改”落库`)
}

async function confirmAllCases() {
  if (!currentSet.value) return
  if (hasUnsavedChanges.value && !await persistCases()) return
  try {
    await api.cases.confirmSet(currentSet.value.id, {
      ok: true,
      edits: cases.value,
      mapping_target: mapTargetId.value ? mapTarget.value : undefined,
      target_id: mapTargetId.value || undefined,
    })
    const ids = selectedCaseIds.value.length ? selectedCaseIds.value : cases.value.map(item => item.id)
    if (mapTargetId.value && ids.length && mapTarget.value === 'dataset') {
      await api.cases.mapCases(currentSet.value.id, {
        target: 'dataset',
        target_id: mapTargetId.value,
        case_ids: ids,
      })
      message.success('用例集已确认入库，并完成映射')
    } else if (mapTargetId.value && mapTarget.value === 'gold_qa') {
      message.warning('用例集已入库；黄金 QA 映射请在知识库阶段操作')
    } else {
      message.success('用例集已确认入库')
    }
    await selectCaseSet(currentSet.value.id)
  } catch (err: any) {
    message.error(err.message || '确认用例集失败')
  }
}

async function handleBatchMap() {
  if (!currentSet.value) return
  if (!mapTargetId.value) {
    message.warning('请选择映射目标')
    return
  }
  if (!selectedCaseIds.value.length) {
    message.warning('请至少选择一条用例')
    return
  }
  try {
    await api.cases.mapCases(currentSet.value.id, {
      target: mapTarget.value,
      target_id: mapTargetId.value,
      case_ids: selectedCaseIds.value,
    })
    await selectCaseSet(currentSet.value.id)
    message.success(`已映射 ${selectedCaseIds.value.length} 条用例`)
  } catch (err: any) {
    message.error(err.message || '批量映射失败')
  }
}

async function loadMappingTargets() {
  mapTargetId.value = ''
  try {
    if (mapTarget.value === 'dataset') {
      mappingTargets.value = (await api.datasets.list()).map(item => ({ id: item.id, name: `${item.name} · v${item.version}` }))
      return
    }
    const kbs: KnowledgeBase[] = await api.kb.list()
    const qaLists = await Promise.all(kbs.map(async kb => api.kb.getGoldQA(kb.id)))
    mappingTargets.value = qaLists.flat().map(item => ({ id: item.id, name: `${item.name} · v${item.version}` }))
  } catch (err: any) {
    mappingTargets.value = []
    message.error(err.message || '加载映射目标失败')
  }
}

async function downloadCaseSet(fmt: 'xlsx' | 'xmind', setId?: string, setName?: string) {
  const id = setId || currentSet.value?.id
  if (!id) return
  const name = setName || currentSet.value?.name || 'case-set'
  try {
    const blob = await api.cases.exportSet(id, fmt)
    const url = URL.createObjectURL(blob)
    const anchor = document.createElement('a')
    anchor.href = url
    anchor.download = `${name}.${fmt}`
    anchor.click()
    URL.revokeObjectURL(url)
    message.success(`用例集已导出为 ${fmt}`)
  } catch (err: any) {
    message.error(err.message || '导出用例集失败')
  }
}

function exportXlsx() { void downloadCaseSet('xlsx') }
function exportXmind() { void downloadCaseSet('xmind') }

function onSetContextMenu(e: MouseEvent, setId: string) {
  ctxSet.setId = setId
  ctxSet.x = e.clientX
  ctxSet.y = e.clientY
  ctxSet.show = true
}

function onFolderContextMenu(e: MouseEvent, folderId: string) {
  ctxFolder.folderId = folderId
  ctxFolder.x = e.clientX
  ctxFolder.y = e.clientY
  ctxFolder.show = true
}

function onRowContextMenu(e: MouseEvent, idx: number) {
  ctxRow.idx = idx
  ctxRow.x = e.clientX
  ctxRow.y = e.clientY
  ctxRow.show = true
}

function confirmCancelSet(set: CaseSet) {
  dialog.warning({
    title: '废弃用例集',
    content: `确认废弃「${set.name}」？此操作不可逆。`,
    positiveText: '确认废弃',
    negativeText: '取消',
    onPositiveClick: async () => {
      try {
        await api.cases.cancelSet(set.id, '用户在目录树右键废弃')
        set.status = 'cancelled'
        syncCaseSetTree(caseSets.value)
        message.info('已废弃用例集')
      } catch (err: any) {
        message.error(err.message || '废弃失败')
      }
    },
  })
}

async function renameCaseSet(id: string, name: string) {
  try {
    const updated = await api.cases.updateSet(id, { name })
    const target = caseSets.value.find(s => s.id === id)
    if (target) target.name = updated.name || name
    syncCaseSetTree(caseSets.value)
    message.success('重命名成功')
  } catch (err: any) {
    message.error(err.message || '重命名失败')
  }
}

async function handleSetMenuSelect(key: string | number) {
  ctxSet.show = false
  const set = caseSets.value.find(s => s.id === ctxSet.setId)
  if (!set) return
  switch (String(key)) {
    case 'confirm':
      if (await requestSelectCaseSet(set.id)) await confirmAllCases()
      break
    case 'map':
      if (await requestSelectCaseSet(set.id)) await handleBatchMap()
      break
    case 'import':
      if (await requestSelectCaseSet(set.id)) openImportModal()
      break
    case 'export':
      await downloadCaseSet('xlsx', set.id, set.name)
      break
    case 'export-xmind':
      await downloadCaseSet('xmind', set.id, set.name)
      break
    case 'copy-id':
      await copyText(set.id, '已复制用例集 ID')
      break
    case 'rename':
      openPrompt('重命名用例集', set.name, async (val) => { await renameCaseSet(set.id, val) })
      break
    case 'cancel':
      confirmCancelSet(set)
      break
  }
}

function handleFolderMenuSelect(key: string | number) {
  ctxFolder.show = false
  const folder = folders.value.find(f => f.id === ctxFolder.folderId)
  if (!folder) return
  switch (String(key)) {
    case 'new-set':
      handleCreateCaseSet(folder.id === ROOT_FOLDER_ID ? '' : folder.id)
      break
    case 'import':
      openImportModal(folder.id === ROOT_FOLDER_ID ? '' : folder.id)
      break
    case 'new-folder':
      openPrompt('新建子目录', '新目录', async (val) => {
        try {
          const created = await api.cases.createFolder({ name: val })
          folderRecords.value = [...folderRecords.value, created]
          syncCaseSetTree(caseSets.value)
          message.success('目录已创建')
        } catch (err: any) {
          message.error(err.message || '创建失败')
        }
      })
      break
    case 'rename':
      if (folder.id === ROOT_FOLDER_ID) {
        message.warning('主目录不可重命名')
        break
      }
      openPrompt('重命名目录', folder.name, async (val) => {
        try {
          const updated = await api.cases.updateFolder(folder.id, { name: val })
          folderRecords.value = folderRecords.value.map(item => item.id === folder.id ? updated : item)
          syncCaseSetTree(caseSets.value)
          message.success('已更新目录名')
        } catch (err: any) {
          message.error(err.message || '重命名失败')
        }
      })
      break
    case 'delete':
      if (folder.id === ROOT_FOLDER_ID) {
        message.warning('主目录不可删除')
        break
      }
      dialog.warning({
        title: '删除目录',
        content: `确认删除「${folder.name}」？目录必须为空。`,
        positiveText: '确认删除',
        negativeText: '取消',
        onPositiveClick: async () => {
          try {
            await api.cases.deleteFolder(folder.id)
            folderRecords.value = folderRecords.value.filter(item => item.id !== folder.id)
            syncCaseSetTree(caseSets.value)
            message.success('目录已删除')
          } catch (err: any) {
            message.error(err.message || '删除失败')
          }
        },
      })
      break
  }
}

async function handleRowMenuSelect(key: string | number) {
  const idx = ctxRow.idx
  ctxRow.show = false
  const row = cases.value[idx]
  if (!row) return
  switch (String(key)) {
    case 'toggle-check':
      toggleCaseChecked(row)
      break
    case 'edit':
      openCaseEditModal(idx)
      break
    case 'ai-fill':
      aiFillCaseRow(row)
      break
    case 'copy':
      await copyCaseJson(row)
      break
    case 'insert-above':
      insertCaseAt(idx)
      break
    case 'insert':
      insertCaseAt(idx + 1)
      break
    case 'duplicate':
      duplicateCase(idx)
      break
    case 'delete':
      deleteCase(idx)
      break
  }
}

function toggleCaseChecked(row: TestCase) {
  const i = selectedCaseIds.value.indexOf(row.id)
  if (i >= 0) selectedCaseIds.value.splice(i, 1)
  else selectedCaseIds.value.push(row.id)
}

async function aiFillCaseRow(row: TestCase) {
  if (currentSet.value?.status === 'confirmed') return
  if (!api.isMock()) {
    const applied = await requestAiFill([row.id])
    if (applied > 0) message.success('已补全属性，保存后生效')
    return
  }
  if (!row.precondition) row.precondition = '前置服务就绪，测试数据已插桩'
  if (!row.test_type) row.test_type = '自动化回归'
  hasUnsavedChanges.value = true
  message.success('已补全属性，保存后生效')
}

async function copyCaseJson(row: TestCase) {
  try {
    await navigator.clipboard.writeText(JSON.stringify(row, null, 2))
    message.success('已复制用例 JSON')
  } catch {
    message.error('复制失败')
  }
}

function insertCaseAt(at: number) {
  if (currentSet.value?.status === 'confirmed') return
  const neighbor = cases.value[Math.min(at, cases.value.length - 1)]
  const item: TestCase = {
    id: `c-${Date.now()}`,
    strategy: '正向',
    priority: 'FHX',
    module: neighbor?.module || '通用',
    name: '',
    expected: '',
    precondition: '',
    mapped: false,
    pending: false,
  }
  cases.value.splice(at, 0, item)
  selectedCaseIds.value.push(item.id)
  hasUnsavedChanges.value = true
  message.info('已插入新用例，保存后生效')
}

function duplicateCase(idx: number) {
  if (currentSet.value?.status === 'confirmed') return
  const src = cases.value[idx]
  if (!src) return
  const copy: TestCase = { ...src, id: `c-${Date.now()}`, name: `${src.name}（副本）`, mapped: false, pending: false }
  cases.value.splice(idx + 1, 0, copy)
  selectedCaseIds.value.push(copy.id)
  hasUnsavedChanges.value = true
  message.info('已创建用例副本，保存后生效')
}

function batchDeleteCases() {
  if (currentSet.value?.status === 'confirmed') return
  const ids = selectedCaseIds.value.filter(id => cases.value.some(item => item.id === id))
  if (!ids.length) return
  dialog.warning({
    title: '批量删除确认',
    content: `确认删除已选的 ${ids.length} 条用例？保存后将同步至数据库。`,
    positiveText: '确认删除',
    negativeText: '取消',
    onPositiveClick: () => {
      const idSet = new Set(ids)
      cases.value = cases.value.filter(item => !idSet.has(item.id))
      selectedCaseIds.value = []
      hasUnsavedChanges.value = true
      message.info(`已删除 ${ids.length} 条用例，点击“保存修改”落库`)
    },
  })
}

async function copyText(text: string, tip: string) {
  try {
    await navigator.clipboard.writeText(text)
    message.success(tip)
  } catch {
    message.error('复制失败')
  }
}

function openPrompt(title: string, defaultValue: string, onSubmit: (val: string) => void | Promise<void>) {
  promptState.title = title
  promptState.value = defaultValue
  promptState.placeholder = '请输入'
  promptState.show = true
  promptSubmit = onSubmit
}

async function submitPrompt() {
  const val = promptState.value.trim()
  if (!val) {
    message.warning('请输入内容')
    return
  }
  const cb = promptSubmit
  promptState.show = false
  promptSubmit = null
  if (cb) await cb(val)
}

function handleCreateSetMenu(key: string | number) {
  const action = String(key)
  if (action === 'ai') openAiGenDrawer()
  else if (action === 'import') openImportModal()
  else if (action === 'template') void downloadImportTemplate()
  else handleCreateCaseSet()
}

function openImportModal(folderId = '') {
  importFolderId.value = folderId
  showImportModal.value = true
}

async function downloadImportTemplate() {
  try {
    const blob = await api.cases.downloadImportTemplate()
    const url = URL.createObjectURL(blob)
    const anchor = document.createElement('a')
    anchor.href = url
    anchor.download = '用例导入模板.xlsx'
    anchor.click()
    URL.revokeObjectURL(url)
    message.success('已下载模板')
  } catch (err: any) {
    message.error(err.message || '下载模板失败')
  }
}

async function onExcelImported(setId: string) {
  await loadCaseSets()
  await selectCaseSet(setId)
}

function openCaseEditModal(idx: number) {
  const row = cases.value[idx]
  if (!row) return
  editingCell.value = null
  editingExtraCell.value = null
  editCaseIdx.value = idx
  editDraft.value = { ...row }
  showEditCaseModal.value = true
}

function saveCaseEdit() {
  const row = cases.value[editCaseIdx.value]
  if (!row) {
    showEditCaseModal.value = false
    return
  }
  if (!String(editDraft.value.name || '').trim()) {
    message.warning('用例名称不能为空')
    return
  }
  if (!String(editDraft.value.expected || '').trim()) {
    message.warning('预期结果不能为空')
    return
  }
  Object.assign(row, editDraft.value)
  hasUnsavedChanges.value = true
  showEditCaseModal.value = false
  message.success(`已更新「${row.name}」，保存后落库`)
}

function openAddColModal() {
  if (!currentSet.value) return
  newColKey.value = ''
  newColName.value = ''
  showAddColModal.value = true
}

async function addCustomCol() {
  if (!currentSet.value) return
  const key = newColKey.value.trim().toLowerCase()
  const name = newColName.value.trim()
  if (!/^[a-z][a-z0-9_]*$/.test(key)) {
    message.warning('字段 Key 需以小写字母开头')
    return
  }
  if (!name) {
    message.warning('请填写显示名称')
    return
  }
  const reserved = ['id', 'strategy', 'priority', 'module', 'name', 'expected', 'precondition', 'steps', 'test_type', 'mapped', 'pending', 'selected']
  if (reserved.includes(key) || customCols.value.some(c => c.key === key)) {
    message.warning(`字段 Key「${key}」已存在`)
    return
  }
  addingCol.value = true
  try {
    const nextCols = [...customCols.value, { key, name }]
    await api.cases.updateSet(currentSet.value.id, { column_schema: nextCols })
    customColsMap.value[currentSet.value.id] = nextCols
    showAddColModal.value = false
    message.success(`已添加扩展字段「${name}」`)
  } catch (err: any) {
    message.error(err.message || '新增字段失败')
  } finally {
    addingCol.value = false
  }
}

async function removeCustomCol(key: string) {
  if (!currentSet.value) return
  try {
    const nextCols = customCols.value.filter(c => c.key !== key)
    await api.cases.updateSet(currentSet.value.id, { column_schema: nextCols })
    customColsMap.value[currentSet.value.id] = nextCols
    message.info(`已移除字段 ${key}`)
  } catch (err: any) {
    message.error(err.message || '移除失败')
  }
}

async function loadCaseSets() {
  try {
    const [list, folderList] = await Promise.all([api.cases.listSets(), api.cases.listFolders()])
    folderRecords.value = folderList
    caseSets.value = list
    syncCaseSetTree(list)
    const selected = list.find(item => item.id === activeSetId.value) || list[0]
    if (selected) await selectCaseSet(selected.id)
    else cases.value = []
  } catch (err: any) {
    caseSets.value = []
    cases.value = []
    folderRecords.value = []
    syncCaseSetTree([])
    message.error(err.message || '加载用例集失败')
  }
}

function onGlobalKeydown(e: KeyboardEvent) {
  if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 's') {
    if (hasUnsavedChanges.value && currentSet.value && currentSet.value.status !== 'confirmed') {
      e.preventDefault()
      void persistCases()
    }
  }
}

onMounted(() => {
  void loadCaseSets()
  void loadMappingTargets()
  window.addEventListener('keydown', onGlobalKeydown)
})

onUnmounted(() => {
  window.removeEventListener('keydown', onGlobalKeydown)
})

watch(() => modeStore.mode, () => {
  void loadMappingTargets()
})
</script>

<style scoped>
/* ─── 全局北欧极简浅色工作台 (Nordic Minimalist / Stripe 质感) ─── */
.cases-workbench {
  height: calc(100vh - var(--topbar-h) - 20px);
  min-height: 0;
  display: flex;
  flex-direction: column;
  outline: none;
}

/* ─── 布局骨架 ─── */
.nordic-layout {
  display: grid;
  grid-template-columns: var(--tree-w, 280px) minmax(0, 1fr);
  height: 100%;
  min-width: 0;
  background: #FCFCFA;
  border-radius: 10px;
  overflow: hidden;
  border: 1px solid #E7E7E2;
}

/* ─── 侧边栏 ─── */
.nordic-sidebar {
  border-right: 1px solid #E7E7E2;
  background: #F8F8F5;
  display: flex;
  flex-direction: column;
  height: 100%;
  position: relative;
  user-select: none;
}

.sidebar-header {
  padding: 12px 14px;
  border-bottom: 1px solid #E7E7E2;
}
.sidebar-title-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 8px;
}
.sidebar-title {
  display: flex;
  align-items: center;
  gap: 6px;
  font-weight: 600;
  font-size: 12.5px;
  color: #18181B;
}
.title-icon {
  color: #0F766E;
}

.btn-xs {
  min-height: 24px;
  padding: 1px 7px;
  font-size: 11px;
  border-radius: 4px;
}
.btn-ghost-subtle {
  background: transparent;
  border: 1px solid transparent;
  color: #52525B;
}
.btn-ghost-subtle:hover {
  background: #EFEFEA;
  color: #18181B;
}

.search-box {
  position: relative;
  display: flex;
  align-items: center;
}
.search-icon {
  position: absolute;
  left: 8px;
  color: #A1A1AA;
  pointer-events: none;
}
.search-input {
  width: 100%;
  height: 28px;
  padding-left: 26px;
  padding-right: 22px;
  font-size: 12px;
  border-radius: 6px;
  border: 1px solid #E2E2DC;
  background: #FFFFFF;
  color: #18181B;
  outline: none;
  transition: border-color 0.12s ease;
}
.search-input:focus {
  border-color: #1E293B;
}
.clear-search-btn {
  position: absolute;
  right: 6px;
  background: none;
  border: none;
  color: #A1A1AA;
  font-size: 11px;
  cursor: pointer;
  padding: 2px;
}
.clear-search-btn:hover {
  color: #18181B;
}

.tree-content {
  flex: 1;
  overflow-y: auto;
  padding: 6px;
  display: flex;
  flex-direction: column;
  gap: 1px;
}

.tree-node {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 5px 8px;
  border-radius: 6px;
  font-size: 12.5px;
  cursor: pointer;
  color: #52525B;
  transition: background-color 0.1s ease, color 0.1s ease;
}
.tree-node:hover {
  background: #EFEFEA;
  color: #18181B;
}
.tree-node.active {
  background: #FFFFFF;
  color: #1E293B;
  font-weight: 600;
  border: 1px solid #E2E2DC;
  box-shadow: 0 1px 2px rgba(0, 0, 0, 0.03);
}

.folder-node {
  font-weight: 600;
  color: #27272A;
}
.folder-children {
  padding-left: 14px;
  display: flex;
  flex-direction: column;
  gap: 1px;
}

.chevron-icon {
  display: grid;
  place-items: center;
  color: #A1A1AA;
  transition: transform 0.15s ease;
}
.chevron-icon.rotated {
  transform: rotate(90deg);
}

.folder-icon {
  color: #71717A;
  flex-shrink: 0;
}
.case-icon {
  color: #0F766E;
  flex-shrink: 0;
}
.node-name {
  flex: 1;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.status-micro-tag {
  font-size: 10px;
  padding: 0 5px;
  border-radius: 3px;
  margin-left: auto;
  font-weight: 500;
}
.status-confirmed { background: #F0FDF4; color: #166534; }
.status-pending { background: #FEFCE8; color: #854D0E; }
.status-cancelled { background: #F4F4F5; color: #71717A; }

.node-badge {
  margin-left: auto;
  font-family: var(--font-mono);
  font-size: 11px;
  color: #A1A1AA;
}

.tree-empty {
  padding: 32px 14px;
  text-align: center;
  color: #A1A1AA;
  font-size: 11.5px;
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
  height: 20px;
  border-radius: 1px;
  background: transparent;
}
.sidebar-resizer:hover .resizer-bar,
.sidebar-resizer.active .resizer-bar {
  background: #1E293B;
}

/* ─── 主工作区 ─── */
.nordic-main {
  display: flex;
  flex-direction: column;
  height: 100%;
  min-width: 0;
  min-height: 0;
  background: #FCFCFA;
  position: relative;
}

/* 顶栏与就地置换 */
.main-toolbar {
  padding: 10px 18px;
  border-bottom: 1px solid #E7E7E2;
  background: #FFFFFF;
  min-height: 54px;
  display: flex;
  align-items: center;
  transition: background-color 0.15s ease;
}
.main-toolbar.in-batch-mode {
  background: #F4F4F0;
}

.toolbar-default,
.toolbar-batch {
  display: flex;
  align-items: center;
  width: 100%;
  gap: 12px;
  flex-wrap: wrap;
}

.toolbar-title-group {
  display: flex;
  flex-direction: column;
  gap: 1px;
}
.title-row {
  display: flex;
  align-items: center;
  gap: 7px;
}
.main-dataset-title {
  font-size: 15px;
  font-weight: 600;
  color: #18181B;
}
.version-tag {
  font-family: var(--font-mono);
  font-size: 10.5px;
  font-weight: 500;
  padding: 1px 6px;
  border-radius: 4px;
  background: #F4F4F0;
  border: 1px solid #E7E7E2;
  color: #52525B;
}

.status-header-badge {
  font-size: 10.5px;
  font-weight: 500;
  padding: 1px 6px;
  border-radius: 4px;
}
.chip-confirmed { background: #F0FDF4; color: #166534; border: 1px solid #DCFCE7; }
.chip-countdown { background: #FEFCE8; color: #854D0E; border: 1px solid #FEF08A; }
.chip-cancelled { background: #F4F4F5; color: #71717A; border: 1px solid #E4E4E7; }

.asset-type-badge {
  font-size: 10.5px;
  font-weight: 500;
  padding: 1px 6px;
  border-radius: 4px;
}
.type-dataset { background: #F0FDF4; color: #166534; border: 1px solid #DCFCE7; }

.breadcrumb-row {
  font-size: 11px;
  color: #A1A1AA;
  display: flex;
  align-items: center;
  gap: 4px;
}
.breadcrumb-row .cur {
  color: #71717A;
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
  left: 7px;
  color: #A1A1AA;
  pointer-events: none;
}
.table-search-input {
  width: 190px;
  height: 26px;
  padding-left: 24px;
  padding-right: 48px;
  font-size: 11.5px;
  border-radius: 4px;
  border: 1px solid #E2E2DC;
  background: #F8F8F5;
  color: #18181B;
  outline: none;
  transition: all 0.12s ease;
}
.table-search-input:focus {
  width: 240px;
  background: #FFFFFF;
  border-color: #1E293B;
}
.grid-search-count {
  position: absolute;
  right: 18px;
  font-size: 10px;
  color: #A1A1AA;
}

.toolbar-action-group {
  display: flex;
  align-items: center;
  gap: 6px;
  flex-wrap: wrap;
}
.action-btn-group {
  display: flex;
  align-items: center;
  gap: 4px;
}

/* 按钮 */
.btn {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  font-size: 12px;
  font-weight: 500;
  border-radius: 5px;
  cursor: pointer;
  transition: all 0.12s ease;
}
.btn-sm {
  min-height: 28px;
  padding: 2px 10px;
}
.btn-primary {
  background: #1E293B;
  color: #FFFFFF;
  border: 1px solid #1E293B;
}
.btn-primary:hover {
  background: #0F172A;
}
.btn-secondary {
  background: #FFFFFF;
  color: #3F3F46;
  border: 1px solid #D4D4D8;
}
.btn-secondary:hover {
  background: #F4F4F0;
  color: #18181B;
}
.btn-ghost {
  background: transparent;
  color: #52525B;
  border: 1px solid transparent;
}
.btn-ghost:hover {
  background: #EFEFEA;
  color: #18181B;
}
.btn-danger {
  background: #DC2626;
  color: #FFFFFF;
  border: 1px solid #DC2626;
}
.btn-danger:hover {
  background: #B91C1C;
}

.btn-save {
  background: #FFFFFF;
  color: #3F3F46;
  border: 1px solid #D4D4D8;
}
.btn-save.dirty {
  background: #1E293B;
  color: #FFFFFF;
  border-color: #1E293B;
}
.btn-save.saved {
  background: #15803D !important;
  color: #FFFFFF !important;
  border-color: #15803D !important;
}
.saved-icon {
  font-weight: 700;
}
.shortcut-key {
  font-size: 9.5px;
  font-family: var(--font-mono);
  padding: 0 3px;
  border-radius: 2px;
  background: rgba(0, 0, 0, 0.08);
  color: inherit;
}
.btn-save.dirty .shortcut-key {
  background: rgba(255, 255, 255, 0.2);
}

/* 批量操作置换 */
.batch-info {
  display: flex;
  align-items: center;
}
.batch-count {
  font-size: 13px;
  color: #18181B;
}
.batch-actions {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}
.map-select-group {
  display: flex;
  align-items: center;
  gap: 6px;
}
.map-label {
  font-size: 11.5px;
  color: #71717A;
}
.map-select {
  height: 28px;
  font-size: 11.5px;
  padding: 1px 6px;
  border-radius: 4px;
  border: 1px solid #D4D4D8;
  background: #FFFFFF;
  color: #18181B;
}

/* ─── 策略分布条 ─── */
.strategy-strip {
  padding: 6px 18px;
  background: #F8F8F5;
  border-bottom: 1px solid #E7E7E2;
  display: flex;
  align-items: center;
  gap: 10px;
  font-size: 12px;
}
.strip-left {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}
.strip-label {
  color: #71717A;
}
.strategy-pills-row {
  display: flex;
  align-items: center;
  gap: 4px;
  flex-wrap: wrap;
}
.strategy-pill {
  display: inline-flex;
  align-items: center;
  gap: 3px;
  padding: 1px 6px;
  border-radius: 4px;
  font-size: 11px;
  cursor: pointer;
  border: 1px solid #E2E2DC;
  background: #FFFFFF;
  color: #52525B;
  transition: all 0.1s ease;
}
.strategy-pill:hover {
  background: #F4F4F0;
  color: #18181B;
}
.strategy-pill.active {
  border-color: #1E293B;
  color: #1E293B;
  font-weight: 600;
}
.strategy-pill.all-pill.active {
  background: #1E293B;
  color: #FFFFFF;
  border-color: #1E293B;
}

.keyboard-flow-hint {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 11px;
  color: #71717A;
}
.kbd-hint kbd {
  font-family: var(--font-mono);
  font-size: 10px;
  padding: 0 3px;
  border-radius: 3px;
  background: #EFEFEA;
  color: #3F3F46;
  border: 1px solid #E2E2DC;
}

.strip-right {
  display: flex;
  align-items: center;
  gap: 8px;
}
.status-warning-text { color: #B45309; }
.status-success-text { color: #15803D; font-weight: 500; }
.status-neutral-text { color: #52525B; }
.strip-divider {
  width: 1px;
  height: 12px;
  background: #D4D4D8;
}
.adoption-rate-text {
  color: #71717A;
  font-size: 11.5px;
}

/* 策略微标 */
.strategy-badge {
  display: inline-block;
  padding: 0 5px;
  border-radius: 3px;
  font-size: 10.5px;
  font-weight: 500;
}
.st-positive { background: #F0FDF4; color: #166534; }
.st-negative { background: #FEF2F2; color: #991B1B; }
.st-boundary { background: #FEFCE8; color: #854D0E; }
.st-equivalence { background: #EFF6FF; color: #1D4ED8; }
.st-state { background: #FAF5FF; color: #6B21A8; }
.st-scenario { background: #F0FDFA; color: #0F766E; }

/* 优先级微标 */
.prio-tag {
  font-family: var(--font-mono);
  font-weight: 600;
  font-size: 10.5px;
  padding: 0 4px;
  border-radius: 3px;
}
.prio-HX { background: #FEF2F2; color: #991B1B; }
.prio-FHX { background: #FEFCE8; color: #854D0E; }
.prio-BJ { background: #EFF6FF; color: #1D4ED8; }
.prio-YC { background: #FDF2F8; color: #9D174D; }
.prio-ZD { background: #FAF5FF; color: #6B21A8; }
.prio-BL { background: #F0FDF4; color: #166534; }

/* ─── 表格：优雅行级横线流 + 键盘光标 ─── */
.table-container {
  flex: 1;
  min-width: 0;
  overflow: auto;
  outline: none;
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
  background: #FFFFFF;
  padding: 8px 10px;
  font-size: 11.5px;
  font-weight: 600;
  color: #71717A;
  text-align: left;
  border-bottom: 1px solid #E7E7E2;
}
.nordic-table td {
  padding: 8px 10px;
  font-size: 12.5px;
  color: #18181B;
  vertical-align: middle;
  border-bottom: 1px solid #EFEFEA;
}

.th-chk, .td-chk {
  text-align: center !important;
}
.clean-checkbox {
  width: 14px;
  height: 14px;
  accent-color: #1E293B;
  cursor: pointer;
}
.req-star {
  color: #DC2626;
}

.custom-th {
  background: #F8F8F5 !important;
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
  color: #A1A1AA;
  font-size: 10px;
  cursor: pointer;
  padding: 1px;
}
.th-del-btn:hover { color: #DC2626; }

.data-row {
  transition: background-color 0.08s ease;
}
.data-row:hover {
  background: #F8F8F5;
}
.data-row.row-checked {
  background: #F4F4F0;
}
.data-row.row-incomplete {
  background: #FFFDF5;
}
.data-row.row-focused {
  background: #F8F8F5;
}

/* 键盘流高亮光标单元格 */
.cell-cursor {
  box-shadow: inset 0 0 0 1.5px #1E293B;
  background: rgba(30, 41, 59, 0.03);
}

.cell-edit {
  cursor: text;
}
.cell-content {
  min-height: 22px;
  display: flex;
  align-items: center;
  word-break: break-word;
  line-height: 1.45;
}
.cell-content.bold-text {
  font-weight: 600;
}
.cell-content.font-medium {
  font-weight: 500;
}
.cell-content.subtle-text {
  color: #71717A;
  font-size: 11.5px;
}
.cell-content.placeholder {
  color: #A1A1AA;
}

:deep(.highlight-match) {
  background: #FEF08A;
  color: #854D0E;
  padding: 0 1px;
  border-radius: 2px;
}

.inline-input {
  width: 100%;
  padding: 4px 6px;
  font: inherit;
  font-size: 12.5px;
  background: #FFFFFF;
  border: 1px solid #1E293B;
  border-radius: 4px;
  outline: none;
}
.cell-invalid {
  border-bottom: 1px dashed #DC2626 !important;
}

.status-tag-green {
  font-size: 10.5px;
  color: #15803D;
  font-weight: 500;
}
.status-tag-amber {
  font-size: 10.5px;
  color: #B45309;
  font-weight: 500;
}

.td-actions {
  text-align: right;
  white-space: nowrap;
}
.action-links {
  display: inline-flex;
  gap: 2px;
  opacity: 0.3;
  transition: opacity 0.1s ease;
}
.data-row:hover .action-links {
  opacity: 1;
}
.icon-link {
  background: none;
  border: none;
  padding: 3px;
  border-radius: 3px;
  color: #71717A;
  cursor: pointer;
  display: grid;
  place-items: center;
}
.icon-link:hover {
  background: #EFEFEA;
  color: #18181B;
}
.icon-link.danger:hover {
  background: #FEF2F2;
  color: #DC2626;
}

.empty-cell {
  padding: 48px 16px;
  text-align: center;
  color: #A1A1AA;
}
.empty-message {
  font-size: 13px;
}

/* ─── 空态 ─── */
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
  gap: 12px;
}
.empty-icon-wrapper {
  width: 64px;
  height: 64px;
  border-radius: 12px;
  background: #F4F4F0;
  border: 1px solid #E7E7E2;
  color: #71717A;
  display: grid;
  place-items: center;
}
.empty-box h3 {
  font-size: 16px;
  font-weight: 600;
  color: #18181B;
}
.empty-box p {
  font-size: 13px;
  color: #71717A;
  line-height: 1.5;
}
.empty-buttons {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
  justify-content: center;
  margin-top: 6px;
}

/* ─── 抽屉内样式 ─── */
.drawer-step-bar {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 20px;
  padding-bottom: 14px;
  border-bottom: 1px solid #E7E7E2;
}
.step-badge {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 12.5px;
  color: #A1A1AA;
}
.step-badge.active {
  color: #1E293B;
  font-weight: 600;
}
.step-badge.done {
  color: #15803D;
}
.step-idx {
  width: 18px;
  height: 18px;
  border-radius: 50%;
  background: #F4F4F0;
  display: grid;
  place-items: center;
  font-size: 10.5px;
  font-family: var(--font-mono);
}
.step-badge.active .step-idx {
  background: #1E293B;
  color: #FFFFFF;
}
.step-badge.done .step-idx {
  background: #15803D;
  color: #FFFFFF;
}
.step-divider-line {
  flex: 1;
  height: 1px;
  background: #E7E7E2;
}

.drawer-body {
  display: flex;
  flex-direction: column;
  gap: 14px;
}

.strategy-weights-grid {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 8px;
}
.weight-item {
  padding: 6px 8px;
  border-radius: 6px;
  background: #F8F8F5;
  border: 1px solid #E7E7E2;
}
.weight-label {
  font-size: 11px;
  font-weight: 600;
  color: #52525B;
  margin-bottom: 3px;
  display: block;
}

.divider-title {
  font-size: 12px;
  font-weight: 600;
  color: #71717A;
  margin: 6px 0 2px;
}

.strategy-strip-mini {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 6px 10px;
  background: #F8F8F5;
  border-radius: 6px;
  border: 1px solid #E7E7E2;
}

.preview-box {
  max-height: 400px;
  overflow-y: auto;
  border: 1px solid #E7E7E2;
  border-radius: 6px;
}
.preview-table td {
  padding: 6px 8px;
}
.inline-input-clean {
  width: 100%;
  padding: 2px 4px;
  border: 1px solid transparent;
  background: transparent;
  font-size: 12px;
}
.inline-input-clean:focus {
  border-color: #1E293B;
  background: #FFFFFF;
  border-radius: 3px;
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
  width: 5px;
  height: 5px;
}
.custom-scroll::-webkit-scrollbar-track {
  background: transparent;
}
.custom-scroll::-webkit-scrollbar-thumb {
  background: rgba(0, 0, 0, 0.12);
  border-radius: 3px;
}
.custom-scroll::-webkit-scrollbar-thumb:hover {
  background: rgba(0, 0, 0, 0.22);
}

/* ─── 响应式 ─── */
@media (max-width: 900px) {
  .cases-workbench {
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
    border-bottom: 1px solid #E7E7E2;
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
