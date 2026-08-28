<template>
  <div class="cases-workbench" @keydown="onWorkbenchKeydown">
    <div class="nordic-layout" :style="{ '--tree-w': treeWidth + 'px' }">
      <!-- ─── 左侧：用例集资源树侧边栏 ─── -->
      <aside class="nordic-sidebar">
        <div class="sidebar-header">
          <div class="sidebar-title-row">
            <div class="sidebar-title">
              <svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="title-icon">
                <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
                <polyline points="14 2 14 8 20 8" />
                <line x1="16" y1="13" x2="8" y2="13" />
                <line x1="16" y1="17" x2="8" y2="17" />
                <polyline points="10 9 9 9 8 9" />
              </svg>
              <span>用例集资源</span>
            </div>
            <div class="sidebar-actions">
              <button class="btn btn-ghost-subtle btn-xs" title="通过 PRD 或接口需求自动推导用例集" aria-label="PRD 用例推导向导" @click="openAiGenDrawer">
                + PRD 推导
              </button>
              <button class="btn btn-ghost-subtle btn-xs" title="新建空用例集" aria-label="新建空用例集" @click="createEmptyCaseSet">
                + 新建
              </button>
            </div>
          </div>

          <!-- 搜索输入框 -->
          <div class="search-box">
            <svg class="search-icon" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
              <circle cx="11" cy="11" r="8" />
              <line x1="21" y1="21" x2="16.65" y2="16.65" />
            </svg>
            <input v-model="treeSearch" class="search-input" placeholder="搜索用例集..." aria-label="搜索用例集" />
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

            <!-- 用例集子项目 -->
            <div v-if="folder.open" class="folder-children">
              <div
                v-for="item in folder.items"
                :key="item.id"
                class="tree-node file-node"
                :class="{ active: activeSetId === item.id }"
                :title="`${item.name} · ${item.status === 'confirmed' ? '已入库' : '草稿'}`"
                @click="requestSelectCaseSet(item.id)"
                @contextmenu.prevent.stop="openCtxMenu($event, 'file', item.id)"
              >
                <span class="file-icon case-set" :class="`status-${item.status}`">
                  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                    <polyline points="9 11 12 14 22 4" />
                    <path d="M21 12v7a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11" />
                  </svg>
                </span>
                <span class="node-name">{{ item.name }}</span>
                <span class="version-badge" :class="`badge-${item.status}`">
                  {{ item.status === 'confirmed' ? '已入库' : '草稿' }}
                </span>
                <span v-if="item.status === 'generated'" class="pending-dot" title="AI 自动生成草稿，待确认"></span>
              </div>
            </div>
          </div>

          <div v-if="!filteredFolders.length" class="tree-empty">
            <svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" class="empty-icon">
              <circle cx="11" cy="11" r="8" />
              <line x1="21" y1="21" x2="16.65" y2="16.65" />
            </svg>
            <p>{{ treeSearch.trim() ? `无匹配结果「${treeSearch.trim()}」` : '暂无用例集，点击上方「+ PRD 推导」或「+ 新建」' }}</p>
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
                <span class="status-badge" :class="`status-${currentSet.status}`">
                  {{ currentSet.status === 'confirmed' ? '已确认入库' : '草稿待审' }}
                </span>
                <span v-if="currentSet.status === 'generated' && countdownHours !== null" class="status-badge-amber">
                  剩余 {{ countdownHours }}h 确认
                </span>
              </div>
              <div class="breadcrumb-row">
                <span>用例库</span>
                <span class="sep">/</span>
                <span class="cur">{{ currentSet.name }}</span>
              </div>
            </div>

            <!-- 表格内即时搜索过滤框 (Instant Grid Filter) -->
            <div class="table-search-box">
              <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" class="table-search-icon">
                <circle cx="11" cy="11" r="8" /><line x1="21" y1="21" x2="16.65" y2="16.65" />
              </svg>
              <input v-model="gridSearch" class="table-search-input" placeholder="在当前用例集中极速筛选 (⌘F)..." aria-label="在当前用例集中极速筛选" />
              <span v-if="gridSearch" class="grid-search-count mono">{{ displayedCases.length }}/{{ cases.length }}</span>
              <button v-if="gridSearch" class="clear-search-btn" aria-label="清空表内搜索" @click="gridSearch = ''">✕</button>
            </div>

            <div class="grow"></div>

            <!-- 右侧操作组 -->
            <div class="toolbar-action-group">
              <template v-if="currentSet.status !== 'confirmed'">
                <div class="action-btn-group">
                  <button class="btn btn-secondary btn-md" aria-label="新增测试用例" @click="addCase">
                    <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="12" y1="5" x2="12" y2="19" /><line x1="5" y1="12" x2="19" y2="12" /></svg>
                    新增用例
                  </button>
                  <button class="btn btn-secondary btn-md" aria-label="新增扩展属性列" @click="openAddColModal">
                    <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="12" y1="5" x2="12" y2="19" /><line x1="5" y1="12" x2="19" y2="12" /></svg>
                    新增列
                  </button>
                </div>

                <div class="action-btn-group">
                  <button class="btn btn-secondary btn-md" aria-label="打开 PRD 用例推导向导" @click="openAiGenDrawer">
                    PRD 推导向导
                  </button>
                  <button class="btn btn-secondary btn-md" title="导出为 Excel 格式" aria-label="导出 Excel" @click="exportExcel">
                    导出 Excel
                  </button>
                  <button
                    class="btn btn-save btn-md"
                    :class="{ dirty: hasUnsavedChanges, saved: justSaved }"
                    :disabled="!hasUnsavedChanges || savingCases"
                    title="快捷键 Ctrl/⌘ + S"
                    aria-label="保存用例修改"
                    @click="persistCases"
                  >
                    <span v-if="justSaved" class="saved-icon">✓</span>
                    {{ savingCases ? '保存中…' : justSaved ? '已保存' : '保存修改' }}
                    <kbd class="shortcut-key">⌘S</kbd>
                  </button>
                </div>

                <button class="btn btn-primary btn-md" :loading="confirmingSet" aria-label="确认入库用例集" @click="confirmCaseSet">
                  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                    <polyline points="20 6 9 17 4 12" />
                  </svg>
                  确认入库
                </button>
              </template>

              <!-- 已确认入库状态下 -->
              <template v-else>
                <button class="btn btn-secondary btn-md" @click="exportExcel">
                  导出 Excel
                </button>
                <button class="btn btn-secondary btn-md" @click="exportXMind">
                  导出 XMind
                </button>
                <button class="btn btn-primary btn-md" @click="openLaunchDrawer">
                  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                    <polygon points="5 3 19 12 5 21 5 3" />
                  </svg>
                  发起基准评测
                </button>
              </template>
            </div>
          </div>

          <!-- 批量操作置换模式顶栏 (In-Toolbar Transition) -->
          <div v-else class="toolbar-batch">
            <div class="batch-info">
              <span class="batch-count">已选择 <b>{{ selectedCaseIds.length }}</b> / {{ cases.length }} 条用例</span>
            </div>

            <div class="grow"></div>

            <div class="batch-actions">
              <button class="btn btn-secondary btn-md" aria-label="批量映射到基准数据集" @click="openBatchMapModal">
                批量映射到数据集 ({{ selectedCaseIds.length }})
              </button>
              <button class="btn btn-danger btn-md" aria-label="批量删除勾选用例" @click="batchDeleteCases">
                批量删除 ({{ selectedCaseIds.length }})
              </button>
              <button class="btn btn-ghost btn-md" aria-label="取消选择" @click="uncheckAllCases">
                取消选择
              </button>
            </div>
          </div>
        </div>

        <!-- 2. 六大策略分布胶囊与状态条 -->
        <div class="metrics-strip">
          <div class="strip-left">
            <span class="strip-label">策略分布:</span>
            <div class="strategy-pills-bar">
              <button
                v-for="(count, st) in strategyDistribution"
                :key="st"
                class="strategy-pill"
                :class="[`pill-${st}`, { active: filterStrategy === st }]"
                @click="filterStrategy = filterStrategy === st ? '' : st"
              >
                {{ st }}: <b>{{ count }}</b>
              </button>
            </div>

            <span class="strip-divider"></span>
            <span v-if="isSixStrategyCovered" class="status-indicator-success">
              ✓ 6 大策略完备覆盖
            </span>
            <span v-else class="status-indicator-warning">
              缺失个别策略覆盖
            </span>
          </div>

          <div class="grow"></div>

          <!-- 键盘流提示 -->
          <div class="keyboard-flow-hint">
            <span class="kbd-hint"><kbd>↑↓←→</kbd> 移动光标</span>
            <span class="kbd-hint"><kbd>Enter</kbd> 就地编辑</span>
            <span class="kbd-hint"><kbd>Space</kbd> 勾选</span>
          </div>
        </div>

        <!-- 3. 用例表格：高性能虚拟网格 + 居中自定义多选框 (Hyper-Speed Virtual Grid) -->
        <div ref="tableContainerRef" class="table-container custom-scroll" tabindex="0" @scroll="onTableScroll">
          <!-- 顶部虚拟占位 -->
          <div v-if="virtualTopPad > 0" :style="{ height: virtualTopPad + 'px' }"></div>

          <table class="nordic-table">
            <thead>
              <tr>
                <th class="th-chk" style="width: 48px" title="全选用例" @click.stop="toggleAllCasesDirect">
                  <div class="clean-chk-box" :class="{ checked: allCasesChecked }" role="checkbox" :aria-checked="allCasesChecked">
                    <svg v-if="allCasesChecked" class="chk-icon" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="#FFFFFF" stroke-width="3.2" stroke-linecap="round" stroke-linejoin="round">
                      <polyline points="20 6 9 17 4 12" />
                    </svg>
                  </div>
                </th>
                <th style="width: 64px">#</th>
                <th style="width: 100px">用例编码</th>
                <th style="min-width: 220px">用例名称 / 测试问句 <span class="req-star">*</span></th>
                <th style="width: 120px">所属模块</th>
                <th style="width: 90px">测试策略</th>
                <th style="width: 80px">优先级</th>
                <th style="min-width: 220px">前置条件 / 输入数据</th>
                <th style="min-width: 240px">预期断言 (Reference) <span class="req-star">*</span></th>
                <th v-for="col in customCols" :key="col.key" class="custom-th" style="min-width: 120px">
                  <div class="th-flex">
                    <span>{{ col.name }}</span>
                    <button class="th-del-btn" title="删除该列" :aria-label="`删除扩展列 ${col.name}`" @click.stop="removeCustomCol(col.key)">✕</button>
                  </div>
                </th>
                <th style="width: 92px">映射状态</th>
                <th style="width: 80px; text-align: right">操作</th>
              </tr>
            </thead>

            <tbody>
              <!-- 虚拟切片用例行 (50px 舒适大行高) -->
              <tr
                v-for="(c, virtualIdx) in virtualRenderCases"
                :key="c.id || c.code"
                class="data-row"
                :class="{
                  'row-checked': isCaseChecked(c),
                  'row-incomplete': !c.name.trim() || !c.expected_result.trim(),
                  'row-focused': focusedCell?.rowIdx === getDisplayedIndex(c)
                }"
                @contextmenu.prevent="openCtxMenu($event, 'row', '', getOriginalCaseIndex(c))"
                @dblclick="openCaseEditModal(getOriginalCaseIndex(c))"
              >
                <!-- 居中自定义多选框列 (支持直击与 Shift 连选) -->
                <td class="td-chk" :class="{ 'cell-cursor': isCellCursor(c, 'chk') }" @click.stop="handleCaseCheckClick(c, $event)">
                  <div class="clean-chk-box" :class="{ checked: isCaseChecked(c) }" :title="`勾选用例 ${c.code}（支持 Shift 连选）`" role="checkbox" :aria-checked="isCaseChecked(c)">
                    <svg v-if="isCaseChecked(c)" class="chk-icon" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="#FFFFFF" stroke-width="3.2" stroke-linecap="round" stroke-linejoin="round">
                      <polyline points="20 6 9 17 4 12" />
                    </svg>
                  </div>
                </td>

                <!-- 行号 -->
                <td class="mono td-num" :class="{ 'cell-cursor': isCellCursor(c, 'row_no') }" @click="setCellCursor(c, 'row_no')">
                  {{ getDisplayedIndex(c) + 1 }}
                </td>

                <!-- 用例编码 (Mono) -->
                <td class="mono-bold" :class="{ 'cell-cursor': isCellCursor(c, 'code') }" @click="setCellCursor(c, 'code')">
                  {{ c.code }}
                </td>

                <!-- 用例名称 / 问句 (14px 舒适字阶) -->
                <td class="cell-edit" :class="{ 'cell-invalid': !c.name.trim(), 'cell-cursor': isCellCursor(c, 'name') }" @click="handleCellClick(c, 'name')">
                  <input
                    v-if="editingCell?.row === c && editingCell?.field === 'name'"
                    v-model="c.name"
                    class="inline-input"
                    placeholder="输入用例名称..."
                    :aria-label="`编辑用例 ${c.code} 名称`"
                    autofocus
                    @blur="finishEditing"
                    @keyup.enter="finishEditing"
                    @keyup.esc="cancelEditing"
                  />
                  <div v-else class="cell-content primary-text" :class="{ empty: !c.name.trim() }" v-html="highlightMatch(c.name || '（空用例名称 · 点击录入）')"></div>
                </td>

                <!-- 所属模块 -->
                <td class="cell-edit" :class="{ 'cell-cursor': isCellCursor(c, 'module') }" @click="handleCellClick(c, 'module')">
                  <input
                    v-if="editingCell?.row === c && editingCell?.field === 'module'"
                    v-model="c.module"
                    class="inline-input"
                    placeholder="所属模块..."
                    :aria-label="`编辑用例 ${c.code} 模块`"
                    autofocus
                    @blur="finishEditing"
                    @keyup.enter="finishEditing"
                    @keyup.esc="cancelEditing"
                  />
                  <div v-else class="cell-content" v-html="highlightMatch(c.module || '通用')"></div>
                </td>

                <!-- 测试策略徽标 -->
                <td class="cell-edit" :class="{ 'cell-cursor': isCellCursor(c, 'strategy') }" @click="handleCellClick(c, 'strategy')">
                  <select
                    v-if="editingCell?.row === c && editingCell?.field === 'strategy'"
                    v-model="c.strategy"
                    class="inline-select"
                    :aria-label="`选择用例 ${c.code} 策略`"
                    autofocus
                    @blur="finishEditing"
                    @change="finishEditing"
                    @keyup.esc="cancelEditing"
                  >
                    <option v-for="s in STRATEGIES" :key="s" :value="s">{{ s }}</option>
                  </select>
                  <div v-else class="cell-content">
                    <span class="strategy-badge" :class="`badge-${c.strategy}`">{{ c.strategy }}</span>
                  </div>
                </td>

                <!-- 优先级 -->
                <td class="cell-edit" :class="{ 'cell-cursor': isCellCursor(c, 'priority') }" @click="handleCellClick(c, 'priority')">
                  <select
                    v-if="editingCell?.row === c && editingCell?.field === 'priority'"
                    v-model="c.priority"
                    class="inline-select"
                    :aria-label="`选择用例 ${c.code} 优先级`"
                    autofocus
                    @blur="finishEditing"
                    @change="finishEditing"
                    @keyup.esc="cancelEditing"
                  >
                    <option v-for="p in PRIORITIES" :key="p" :value="p">{{ p }}</option>
                  </select>
                  <div v-else class="cell-content">
                    <span class="priority-badge" :class="`prio-${c.priority}`">{{ c.priority }}</span>
                  </div>
                </td>

                <!-- 前置条件 / 输入数据 -->
                <td class="cell-edit" :class="{ 'cell-cursor': isCellCursor(c, 'preconditions') }" @click="handleCellClick(c, 'preconditions')">
                  <input
                    v-if="editingCell?.row === c && editingCell?.field === 'preconditions'"
                    v-model="c.preconditions"
                    class="inline-input"
                    placeholder="输入前置条件..."
                    :aria-label="`编辑用例 ${c.code} 前置条件`"
                    autofocus
                    @blur="finishEditing"
                    @keyup.enter="finishEditing"
                    @keyup.esc="cancelEditing"
                  />
                  <div v-else class="cell-content mono-sm" :class="{ placeholder: !c.preconditions }" v-html="highlightMatch(c.preconditions || '—')"></div>
                </td>

                <!-- 预期断言 (14px 舒适字阶) -->
                <td class="cell-edit" :class="{ 'cell-invalid': !c.expected_result.trim(), 'cell-cursor': isCellCursor(c, 'expected_result') }" @click="handleCellClick(c, 'expected_result')">
                  <input
                    v-if="editingCell?.row === c && editingCell?.field === 'expected_result'"
                    v-model="c.expected_result"
                    class="inline-input"
                    placeholder="输入预期断言..."
                    :aria-label="`编辑用例 ${c.code} 预期断言`"
                    autofocus
                    @blur="finishEditing"
                    @keyup.enter="finishEditing"
                    @keyup.esc="cancelEditing"
                  />
                  <div v-else class="cell-content" :class="{ empty: !c.expected_result.trim() }" v-html="highlightMatch(c.expected_result || '（空预期断言 · 点击录入）')"></div>
                </td>

                <!-- 自定义扩展列 -->
                <td v-for="col in customCols" :key="col.key" class="cell-edit" :class="{ 'cell-cursor': isCellCursor(c, col.key) }" @click="handleCellClick(c, col.key)">
                  <input
                    v-if="editingCell?.row === c && editingCell?.field === col.key && c.extras"
                    v-model="c.extras[col.key]"
                    class="inline-input"
                    :placeholder="`输入 ${col.name}...`"
                    :aria-label="`编辑用例 ${c.code} ${col.name}`"
                    autofocus
                    @blur="finishEditing"
                    @keyup.enter="finishEditing"
                    @keyup.esc="cancelEditing"
                  />
                  <div v-else class="cell-content" :class="{ placeholder: !getCaseExtra(c, col.key) }">
                    {{ getCaseExtra(c, col.key) || '—' }}
                  </div>
                </td>

                <!-- 映射状态 -->
                <td>
                  <span v-if="c.target_dataset_id" class="status-tag-green" title="已映射至数据集">已映射</span>
                  <span v-else class="status-tag-clean" title="未映射">未映射</span>
                </td>

                <!-- 操作区 -->
                <td class="td-actions">
                  <div class="action-links">
                    <button class="icon-link" title="详细编辑" :aria-label="`详细编辑用例 ${c.code}`" @click.stop="openCaseEditModal(getOriginalCaseIndex(c))">
                      <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7" /><path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z" /></svg>
                    </button>
                    <button class="icon-link danger" title="删除用例" :aria-label="`删除用例 ${c.code}`" @click.stop="deleteCase(getOriginalCaseIndex(c))">
                      <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="3 6 5 6 21 6" /><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2" /></svg>
                    </button>
                  </div>
                </td>
              </tr>

              <!-- 空列表提示 -->
              <tr v-if="!displayedCases.length">
                <td :colspan="11 + customCols.length" class="empty-cell">
                  <div class="empty-message">
                    <span v-if="gridSearch.trim()">未找到匹配「{{ gridSearch.trim() }}」的测试用例。</span>
                    <span v-else-if="filterStrategy">当前策略「{{ filterStrategy }}」下暂无用例。</span>
                    <span v-else>当前用例集暂无用例，点击上方「新增用例」或「PRD 推导向导」开始录入。</span>
                  </div>
                </td>
              </tr>
            </tbody>
          </table>

          <!-- 底部虚拟占位 -->
          <div v-if="virtualBottomPad > 0" :style="{ height: virtualBottomPad + 'px' }"></div>
        </div>
      </main>

      <!-- 空态页面 -->
      <main v-else class="nordic-main empty-main">
        <div class="empty-box">
          <div class="empty-icon-wrapper">
            <svg width="40" height="40" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round">
              <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
              <polyline points="14 2 14 8 20 8" />
            </svg>
          </div>
          <h3>尚未选择或创建用例集</h3>
          <p>你可以基于 PRD / 接口需求文档一键推导六大策略测试用例，或新建空集手动设计用例。</p>
          <div class="empty-buttons">
            <button class="btn btn-primary btn-md" @click="openAiGenDrawer">
              PRD 用例推导向导
            </button>
            <button class="btn btn-ghost btn-md" @click="createEmptyCaseSet">
              + 新建空用例集
            </button>
          </div>
        </div>
      </main>
    </div>

    <!-- ─── 右侧滑出抽屉：PRD 用例推导向导 ─── -->
    <n-drawer v-model:show="aiGen.show" :width="drawerWidth" placement="right">
      <n-drawer-content title="PRD 用例智能推导向导" closable>
        <div class="drawer-step-bar">
          <div class="step-badge" :class="{ active: aiGen.step === 1, done: aiGen.step === 2 }">
            <span class="step-idx">1</span>
            <span>PRD 需求与策略配置</span>
          </div>
          <span class="step-divider-line"></span>
          <div class="step-badge" :class="{ active: aiGen.step === 2 }">
            <span class="step-idx">2</span>
            <span>候选用例审核与采纳</span>
          </div>
        </div>

        <div v-show="aiGen.step === 1" class="drawer-body">
          <div class="field">
            <label class="field-label">PRD 需求预设模板</label>
            <n-select v-model:value="aiGen.preset" :options="presetOptions" @update:value="onPresetChange" />
          </div>

          <div class="field">
            <label class="field-label">PRD 需求描述 / 业务规则 / 接口规范 <span class="req">*</span></label>
            <n-input v-model:value="aiGen.prdText" class="mono" type="textarea" :autosize="{ minRows: 4, maxRows: 8 }" placeholder="粘贴需求文档段落、状态转移逻辑或 OpenAPI 规范..." />
          </div>

          <div class="divider-title">推导策略覆盖</div>
          <div class="field">
            <div class="row wrap" style="gap: 12px; font-size: 13.5px">
              <n-checkbox v-for="s in STRATEGIES" :key="s" :checked="aiGen.strategies.includes(s)" @update:checked="toggleStrategy(s)">
                {{ s }}策略
              </n-checkbox>
            </div>
          </div>

          <div class="divider-title">生成参数</div>
          <div class="form-row-3">
            <div class="field">
              <label class="field-label">用例规模 (<b class="mono">{{ aiGen.count }}</b> 条)</label>
              <n-slider v-model:value="aiGen.count" :min="4" :max="30" :step="1" />
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
        </div>

        <div v-show="aiGen.step === 2" class="drawer-body">
          <div class="row-between mb8">
            <span class="bold" style="font-size: 13.5px">候选用例列表 (共 {{ aiGen.candidates.length }} 条)</span>
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
                  <th style="width: 90px">策略</th>
                  <th style="min-width: 160px">用例名称</th>
                  <th style="min-width: 180px">预期断言</th>
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
                  <td><span class="strategy-badge" :class="`badge-${cand.strategy}`">{{ cand.strategy }}</span></td>
                  <td><input v-model="cand.name" class="inline-input-clean" /></td>
                  <td><input v-model="cand.expected_result" class="inline-input-clean" /></td>
                  <td><button class="link-btn danger" @click="aiGen.candidates.splice(ci, 1)">移除</button></td>
                </tr>
              </tbody>
            </table>
          </div>
        </div>

        <template #footer>
          <div class="drawer-footer-row">
            <n-button v-if="aiGen.step === 2" @click="aiGen.step = 1">← 返回调整 PRD</n-button>
            <span v-else></span>
            <div class="row" style="gap: 8px">
              <n-button @click="aiGen.show = false">取消</n-button>
              <n-button v-if="aiGen.step === 1" type="primary" :loading="aiGen.generating" @click="runAiGenerateCases">
                {{ aiGen.generating ? '正在推导用例中…' : '推导候选用例 →' }}
              </n-button>
              <n-button v-else type="primary" :disabled="aiSelectedCount === 0" @click="commitAiCandidates">
                采纳导入用例集 ({{ aiSelectedCount }} 条)
              </n-button>
            </div>
          </div>
        </template>
      </n-drawer-content>
    </n-drawer>

    <!-- 弹窗与抽屉组件 (全居中显示) -->
    <BenchmarkLaunchDrawer
      v-model:show="showLaunchDrawer"
      :default-dataset-id="(currentSet as any)?.target_dataset_id"
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

    <n-modal v-model:show="caseEdit.show" preset="card" :title="`编辑用例 ${caseEdit.code}`" class="center-dialog-card" style="width: 660px; max-width: calc(100vw - 32px)">
      <div class="form-row">
        <div class="field">
          <label class="field-label">用例编码</label>
          <n-input v-model:value="caseEdit.code" class="mono" readonly />
        </div>
        <div class="field">
          <label class="field-label">所属模块</label>
          <n-input v-model:value="caseEdit.module" placeholder="所属业务模块" />
        </div>
      </div>
      <div class="field">
        <label class="field-label">用例名称 / 问句 <span class="req">*</span></label>
        <n-input v-model:value="caseEdit.name" type="textarea" :autosize="{ minRows: 2, maxRows: 4 }" placeholder="输入用例标题或测试问句..." />
      </div>
      <div class="form-row">
        <div class="field">
          <label class="field-label">测试策略</label>
          <n-select v-model:value="caseEdit.strategy" :options="STRATEGIES.map(s => ({ label: s, value: s }))" />
        </div>
        <div class="field">
          <label class="field-label">优先级</label>
          <n-select v-model:value="caseEdit.priority" :options="PRIORITIES.map(p => ({ label: p, value: p }))" />
        </div>
      </div>
      <div class="field">
        <label class="field-label">前置条件 / 输入数据</label>
        <n-input v-model:value="caseEdit.preconditions" class="mono" type="textarea" :autosize="{ minRows: 2, maxRows: 4 }" placeholder="可选输入测试前置条件或变量注入..." />
      </div>
      <div class="field">
        <label class="field-label">预期断言 (Expected Result) <span class="req">*</span></label>
        <n-input v-model:value="caseEdit.expected_result" type="textarea" :autosize="{ minRows: 2, maxRows: 4 }" placeholder="输入预期返回、校验规则或标准答案..." />
      </div>
      <template #footer>
        <div style="display: flex; justify-content: flex-end; gap: 8px">
          <n-button @click="caseEdit.show = false">取消</n-button>
          <n-button type="primary" @click="saveCaseEdit">保存修改</n-button>
        </div>
      </template>
    </n-modal>

    <n-modal v-model:show="batchMap.show" preset="card" title="批量映射至基准数据集" class="center-dialog-card" style="width: 500px; max-width: calc(100vw - 32px)">
      <p class="small" style="margin: 0 0 12px; color: #52525B; font-size: 13px">
        将选中的 {{ selectedCaseIds.length }} 条用例同步导入至指定的数据集，自动映射问句与标准参考答案。
      </p>
      <div class="field">
        <label class="field-label">目标数据集 <span class="req">*</span></label>
        <n-select v-model:value="batchMap.targetDatasetId" :options="datasetOptions" placeholder="选择目标基准数据集" />
      </div>
      <template #footer>
        <div style="display: flex; justify-content: flex-end; gap: 8px">
          <n-button @click="batchMap.show = false">取消</n-button>
          <n-button type="primary" :disabled="!batchMap.targetDatasetId" @click="confirmBatchMap">确认映射导入</n-button>
        </div>
      </template>
    </n-modal>

    <n-modal v-model:show="addCol.show" preset="card" title="新增用例扩展属性列" class="center-dialog-card" style="width: 440px; max-width: calc(100vw - 32px)">
      <div class="field">
        <label class="field-label">字段 Key (英文字母/下划线) <span class="req">*</span></label>
        <n-input v-model:value="addCol.key" class="mono" placeholder="如 env, api_path" />
      </div>
      <div class="field">
        <label class="field-label">列显示名称 <span class="req">*</span></label>
        <n-input v-model:value="addCol.name" placeholder="如 运行环境, 接口路径" />
      </div>
      <template #footer>
        <div style="display: flex; justify-content: flex-end; gap: 8px">
          <n-button @click="addCol.show = false">取消</n-button>
          <n-button type="primary" @click="confirmAddCol">确认添加</n-button>
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
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted, h } from 'vue'
import { useRouter } from 'vue-router'
import { useMessage, useDialog, type DropdownOption } from 'naive-ui'
import { api } from '../api/http'
import type { CaseSet, TestCase, Dataset } from '../api/types'
import BenchmarkLaunchDrawer from '../components/drawers/BenchmarkLaunchDrawer.vue'

type CaseStrategy = '正向' | '反向' | '边界' | '状态' | '场景' | '等价'
type CasePriority = 'HX' | 'FHX' | 'BJ' | 'YC' | 'ZD' | 'BL'

interface ExtendedTestCase {
  id: string
  set_id?: string
  code: string
  name: string
  module: string
  strategy: CaseStrategy
  priority: CasePriority
  preconditions: string
  expected_result: string
  steps?: string[]
  target_dataset_id?: string
  checked?: boolean
  extras?: Record<string, string>
}

interface CustomColumn {
  key: string
  name: string
  type: 'text' | 'number'
}

type CtxMenuType = 'file' | 'folder' | 'row'

const STRATEGIES: CaseStrategy[] = ['正向', '反向', '边界', '等价', '状态', '场景']
const PRIORITIES: CasePriority[] = ['HX', 'FHX', 'BJ', 'YC', 'ZD', 'BL']

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

const treeSearch = ref('')
const gridSearch = ref('')
const caseSets = ref<CaseSet[]>([])
const activeSetId = ref('')
const cases = ref<ExtendedTestCase[]>([])
const savingCases = ref(false)
const justSaved = ref(false)
const hasUnsavedChanges = ref(false)
const confirmingSet = ref(false)
const showLaunchDrawer = ref(false)
const filterStrategy = ref('')
const selectedCaseIds = ref<string[]>([])
const editingCell = ref<{ row: ExtendedTestCase; field: string; original: string } | null>(null)
const focusedCell = ref<{ rowIdx: number; field: string } | null>(null)
const tableContainerRef = ref<HTMLElement | null>(null)

// ─── 侧边栏拖拽调宽 ───
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

const drawerWidth = computed(() => (typeof window !== 'undefined' && window.innerWidth <= 720 ? '100%' : 640))

interface TreeFolder {
  id: string
  name: string
  open: boolean
  items: CaseSet[]
}
const folders = ref<TreeFolder[]>([{ id: 'cases', name: '用例集目录', open: true, items: [] }])

const currentSet = computed<CaseSet | undefined>(() => caseSets.value.find((s: CaseSet) => s.id === activeSetId.value))

const countdownHours = computed(() => {
  const expires = currentSet.value?.expires_at || (currentSet.value as any)?.confirm_deadline
  if (!expires) return null
  const deadline = new Date(expires).getTime()
  const now = Date.now()
  const diff = deadline - now
  if (diff <= 0) return 0
  return Math.max(1, Math.round(diff / 3600000))
})

// 六大策略分布
const strategyDistribution = computed(() => {
  const map: Record<string, number> = {}
  STRATEGIES.forEach(s => { map[s] = 0 })
  cases.value.forEach(c => {
    if (map[c.strategy] !== undefined) map[c.strategy]++
  })
  return map
})
const isSixStrategyCovered = computed(() => STRATEGIES.every(s => (strategyDistribution.value[s] || 0) > 0))

// ─── 50px 舒适大行高虚拟滚动 + 过滤 (Instant Filter & 50px Virtual Scrolling) ───
const displayedCases = computed(() => {
  let list = cases.value
  if (filterStrategy.value) {
    list = list.filter(c => c.strategy === filterStrategy.value)
  }
  const q = gridSearch.value.trim().toLowerCase()
  if (q) {
    list = list.filter(c =>
      c.code.toLowerCase().includes(q) ||
      c.name.toLowerCase().includes(q) ||
      c.module.toLowerCase().includes(q) ||
      c.strategy.toLowerCase().includes(q) ||
      c.priority.toLowerCase().includes(q) ||
      c.preconditions.toLowerCase().includes(q) ||
      c.expected_result.toLowerCase().includes(q) ||
      (c.extras && Object.values(c.extras).some(v => String(v).toLowerCase().includes(q))),
    )
  }
  return list
})

function getOriginalCaseIndex(c: ExtendedTestCase): number {
  return cases.value.findIndex(item => item.id === c.id || item.code === c.code)
}
function getDisplayedIndex(c: ExtendedTestCase): number {
  return displayedCases.value.findIndex(item => item.id === c.id || item.code === c.code)
}

const ROW_HEIGHT = 50
const scrollTop = ref(0)
const viewportHeight = ref(650)
const BUFFER_SIZE = 8

const startIndex = computed(() => Math.max(0, Math.floor(scrollTop.value / ROW_HEIGHT) - BUFFER_SIZE))
const endIndex = computed(() => Math.min(displayedCases.value.length, Math.ceil((scrollTop.value + viewportHeight.value) / ROW_HEIGHT) + BUFFER_SIZE))

const virtualTopPad = computed(() => startIndex.value * ROW_HEIGHT)
const virtualBottomPad = computed(() => Math.max(0, (displayedCases.value.length - endIndex.value) * ROW_HEIGHT))

const virtualRenderCases = computed(() => {
  if (displayedCases.value.length < 30) return displayedCases.value
  return displayedCases.value.slice(startIndex.value, endIndex.value)
})

function onTableScroll(e: Event) {
  const target = e.target as HTMLElement
  scrollTop.value = target.scrollTop
  viewportHeight.value = target.clientHeight || 650
}

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
  const base = ['chk', 'row_no', 'code', 'name', 'module', 'strategy', 'priority', 'preconditions', 'expected_result']
  const extras = customCols.value.map(c => c.key)
  return [...base, ...extras]
})

function isCellCursor(c: ExtendedTestCase, field: string): boolean {
  if (!focusedCell.value) return false
  const idx = getDisplayedIndex(c)
  return focusedCell.value.rowIdx === idx && focusedCell.value.field === field
}

function setCellCursor(c: ExtendedTestCase, field: string) {
  const idx = getDisplayedIndex(c)
  focusedCell.value = { rowIdx: idx, field }
}

function handleCellClick(c: ExtendedTestCase, field: string) {
  setCellCursor(c, field)
  editCell(c, field)
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
      if (displayedCases.value[rowIdx] && !['chk', 'row_no', 'code'].includes(field)) {
        editCell(displayedCases.value[rowIdx], field)
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

const filteredFolders = computed(() => {
  const keyword = treeSearch.value.trim().toLowerCase()
  if (!keyword) return folders.value
  return folders.value.map(folder => ({
    ...folder,
    items: folder.items.filter((item: CaseSet) => item.name.toLowerCase().includes(keyword)),
  })).filter(folder => folder.items.length > 0)
})

// 自定义列
const customColsMap = ref<Record<string, CustomColumn[]>>({})
const customCols = computed<CustomColumn[]>(() => {
  const s = currentSet.value
  return s ? customColsMap.value[s.id] || [] : []
})

function getCaseExtra(c: ExtendedTestCase, key: string): string {
  return c.extras ? c.extras[key] || '' : ''
}

// 批量勾选
const allCasesChecked = computed(() => displayedCases.value.length > 0 && displayedCases.value.every(c => isCaseChecked(c)))
const lastCheckedCaseIdx = ref<number>(-1)

function isCaseChecked(c: ExtendedTestCase): boolean {
  const id = c.id || c.code
  return selectedCaseIds.value.includes(id)
}

function toggleCaseChecked(c: ExtendedTestCase) {
  const id = c.id || c.code
  const idx = selectedCaseIds.value.indexOf(id)
  if (idx >= 0) selectedCaseIds.value.splice(idx, 1)
  else selectedCaseIds.value.push(id)
}

function toggleAllCasesDirect() {
  if (allCasesChecked.value) {
    selectedCaseIds.value = []
  } else {
    selectedCaseIds.value = displayedCases.value.map(c => c.id || c.code)
  }
}

function handleCaseCheckClick(c: ExtendedTestCase, e: MouseEvent) {
  const currentIdx = getDisplayedIndex(c)
  const isCurrentlyChecked = isCaseChecked(c)
  if (e.shiftKey && lastCheckedCaseIdx.value !== -1 && lastCheckedCaseIdx.value !== currentIdx) {
    const start = Math.min(lastCheckedCaseIdx.value, currentIdx)
    const end = Math.max(lastCheckedCaseIdx.value, currentIdx)
    const targetChecked = !isCurrentlyChecked
    for (let i = start; i <= end; i++) {
      const item = displayedCases.value[i]
      if (item) {
        const id = item.id || item.code
        const existIdx = selectedCaseIds.value.indexOf(id)
        if (targetChecked && existIdx < 0) selectedCaseIds.value.push(id)
        else if (!targetChecked && existIdx >= 0) selectedCaseIds.value.splice(existIdx, 1)
      }
    }
  } else {
    toggleCaseChecked(c)
    lastCheckedCaseIdx.value = currentIdx
  }
}

function uncheckAllCases() {
  selectedCaseIds.value = []
  lastCheckedCaseIdx.value = -1
}

function batchDeleteCases() {
  const count = selectedCaseIds.value.length
  if (!count) return
  dialog.warning({
    title: '批量删除用例确认',
    content: `确认删除已选的 ${count} 条用例？保存后将同步生效。`,
    positiveText: '确认删除',
    negativeText: '取消',
    onPositiveClick: () => {
      cases.value = cases.value.filter(c => !selectedCaseIds.value.includes(c.id || c.code))
      selectedCaseIds.value = []
      hasUnsavedChanges.value = true
      message.info(`已删除 ${count} 条用例，点击“保存修改”后落库`)
    },
  })
}

// 单元格即时编辑
function editCell(row: ExtendedTestCase, field: string) {
  if (currentSet.value?.status === 'confirmed') return
  const original = String((row as any)[field] ?? (row.extras ? row.extras[field] : '') ?? '')
  editingCell.value = { row, field, original }
}

function finishEditing() {
  editingCell.value = null
  hasUnsavedChanges.value = true
}

function cancelEditing() {
  const cell = editingCell.value
  if (cell) {
    if (cell.field in cell.row) {
      (cell.row as any)[cell.field] = cell.original
    } else if (cell.row.extras) {
      cell.row.extras[cell.field] = cell.original
    }
  }
  editingCell.value = null
}

async function selectCaseSet(id: string) {
  activeSetId.value = id
  selectedCaseIds.value = []
  await loadCases(id)
}

function requestSelectCaseSet(id: string, after?: () => void) {
  if (id === activeSetId.value) {
    after?.()
    return
  }
  if (!hasUnsavedChanges.value) {
    void selectCaseSet(id).then(() => after?.())
    return
  }
  dialog.warning({
    title: '存在未保存的用例修改',
    content: '当前用例集有未落库的编辑，切换前请选择处理方式。',
    positiveText: '保存并切换',
    negativeText: '放弃修改',
    onPositiveClick: async () => {
      await persistCases()
      await selectCaseSet(id)
      after?.()
    },
    onNegativeClick: () => {
      void selectCaseSet(id).then(() => after?.())
    },
  })
}

function createEmptyCaseSet() {
  openNameDialog('新建空用例集', '用例集名称', '新用例集', async (val) => {
    try {
      const created = await api.cases.createSet({ name: val })
      await loadCaseSets()
      await selectCaseSet(created.id)
      message.success(`已创建「${created.name}」`)
    } catch (err: any) {
      message.error(err.message || '创建用例集失败')
    }
  })
}

function buildEmptyCase(): ExtendedTestCase {
  const nextNum = cases.value.length + 1
  const code = `TC-${String(nextNum).padStart(3, '0')}`
  return {
    id: `temp-${Date.now()}-${Math.random().toString(36).slice(2, 6)}`,
    set_id: activeSetId.value,
    code,
    name: '',
    module: '通用',
    strategy: '正向',
    priority: 'HX',
    preconditions: '',
    steps: ['1. 执行标准输入'],
    expected_result: '',
    target_dataset_id: undefined,
    extras: {},
  }
}

function addCase() {
  cases.value.push(buildEmptyCase())
  hasUnsavedChanges.value = true
  message.info('已新增用例行，填写后点击“保存修改”落库')
}

function deleteCase(idx: number) {
  cases.value.splice(idx, 1)
  hasUnsavedChanges.value = true
  message.info('已删除用例行，保存后生效')
}

async function persistCases() {
  if (!currentSet.value || savingCases.value) return
  savingCases.value = true
  try {
    const payload = cases.value.map((c, i) => ({
      code: c.code || `TC-${String(i + 1).padStart(3, '0')}`,
      name: c.name,
      module: c.module || '通用',
      strategy: c.strategy,
      priority: c.priority,
      preconditions: c.preconditions,
      steps: c.steps ? (Array.isArray(c.steps) ? c.steps.join('\n') : c.steps) : '',
      expected: c.expected_result,
      target_dataset_id: c.target_dataset_id,
      ...c.extras,
    }))
    await api.cases.saveCases(currentSet.value.id, payload as any)
    hasUnsavedChanges.value = false
    justSaved.value = true
    setTimeout(() => { justSaved.value = false }, 1800)
    message.success('已保存用例集修改')
  } catch (err: any) {
    message.error(err.message || '保存用例集失败')
  } finally {
    savingCases.value = false
  }
}

async function confirmCaseSet() {
  if (!currentSet.value || confirmingSet.value) return
  if (hasUnsavedChanges.value) {
    await persistCases()
  }
  confirmingSet.value = true
  try {
    await api.cases.confirmSet(currentSet.value.id, { ok: true })
    currentSet.value.status = 'confirmed'
    message.success('用例集已确认入库，当前版本已锁定')
    await loadCaseSets()
  } catch (err: any) {
    message.error(err.message || '确认入库失败')
  } finally {
    confirmingSet.value = false
  }
}

function openLaunchDrawer() {
  showLaunchDrawer.value = true
}
function handleLaunchSuccess() {
  router.push('/tasks')
}

function exportExcel() {
  message.success(`已导出「${currentSet.value?.name || '用例集'}」Excel 格式文件`)
}
function exportXMind() {
  message.success(`已导出「${currentSet.value?.name || '用例集'}」XMind 脑图文件`)
}

async function loadCases(setId: string) {
  try {
    const setObj = await api.cases.getSet(setId)
    const list = (setObj as any).cases || []
    cases.value = list.map((c: any, i: number) => ({
      id: c.id || `c-${i}`,
      set_id: setId,
      code: c.code || `TC-${String(i + 1).padStart(3, '0')}`,
      name: c.name || c.question || '',
      module: c.module || '通用',
      strategy: (c.strategy as CaseStrategy) || '正向',
      priority: (c.priority as CasePriority) || 'HX',
      preconditions: c.preconditions || c.precondition || '',
      expected_result: c.expected_result || c.expected || c.reference || '',
      steps: Array.isArray(c.steps) ? c.steps : typeof c.steps === 'string' ? [c.steps] : ['1. 执行标准输入'],
      target_dataset_id: c.target_dataset_id,
      checked: false,
      extras: {},
    }))
    hasUnsavedChanges.value = false
  } catch (err: any) {
    cases.value = []
    message.error(err.message || '加载用例列表失败')
  }
}

async function loadCaseSets() {
  try {
    const list = await api.cases.listSets()
    caseSets.value = list
    let root = folders.value.find(f => f.id === 'cases')
    if (!root) {
      root = { id: 'cases', name: '用例集目录', open: true, items: [] }
      folders.value = [root]
    }
    root.items = list
    const selected = list.find((s: any) => s.id === activeSetId.value) || list[0]
    if (selected) await selectCaseSet(selected.id)
    else cases.value = []
  } catch (err: any) {
    caseSets.value = []
    message.error(err.message || '加载用例集失败')
  }
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
    const s = caseSets.value.find((item: any) => item.id === ctxMenu.value.targetId)
    return [
      { label: '发起基准评测', key: 'eval', icon: renderIcon('M5 3l14 9-14 9V3z', '#0F766E') },
      { label: '确认入库', key: 'confirm-set', disabled: s?.status === 'confirmed', icon: renderIcon('M20 6L9 17l-5-5', '#15803D') },
      { type: 'divider', key: 'd1' },
      { label: '导出 Excel', key: 'export-excel', icon: renderIcon(['M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4', 'M7 10l5 5 5-5', 'M12 15V3']) },
      { label: '导出 XMind', key: 'export-xmind', icon: renderIcon(['M18 8A6 6 0 0 0 6 8c0 7-3 9-3 9h18s-3-2-3-9', 'M13.73 21a2 2 0 0 1-3.46 0']) },
      { label: '重命名', key: 'rename', icon: renderIcon('M17 3a2.828 2.828 0 1 1 4 4L7.5 20.5 2 22l1.5-5.5L17 3z') },
      { label: '复制用例集 ID', key: 'copy-id', icon: renderIcon(['M8 4v12a2 2 0 0 0 2 2h8a2 2 0 0 0 2-2V7.242a2 2 0 0 0-.602-1.43L16.083 2.57A2 2 0 0 0 14.685 2H10a2 2 0 0 0-2 2z', 'M16 18v2a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V9a2 2 0 0 1 2-2h2']) },
      { type: 'divider', key: 'd2' },
      { label: '删除用例集', key: 'delete-set', props: { style: 'color: #DC2626' }, icon: renderIcon(['M3 6h18', 'M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2'], '#DC2626') },
    ]
  }
  if (ctxMenu.value.type === 'folder') {
    return [
      { label: '新建空用例集', key: 'new-set', icon: renderIcon(['M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z', 'M12 11v6', 'M9 14h6']) },
      { label: '新建子目录', key: 'new-folder', icon: renderIcon('M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z') },
    ]
  }
  const c = cases.value[ctxMenu.value.rowIdx]
  return [
    { label: '详细编辑', key: 'edit', icon: renderIcon(['M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7', 'M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z']) },
    { label: '复制为 JSON', key: 'copy-json', icon: renderIcon(['M8 4v12a2 2 0 0 0 2 2h8a2 2 0 0 0 2-2V7.242a2 2 0 0 0-.602-1.43L16.083 2.57A2 2 0 0 0 14.685 2H10a2 2 0 0 0-2 2z', 'M16 18v2a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V9a2 2 0 0 1 2-2h2']) },
    { label: isCaseChecked(c) ? '取消勾选' : '勾选本行', key: 'toggle-check', icon: renderIcon(['M9 11l3 3L22 4', 'M21 12v7a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11']) },
    { type: 'divider', key: 'd1' },
    { label: '上方插入用例', key: 'insert-above', icon: renderIcon(['M12 19V5', 'M5 12l7-7 7 7']) },
    { label: '下方插入用例', key: 'insert-below', icon: renderIcon(['M12 5v14', 'M19 12l-7 7-7-7']) },
    { label: '创建用例副本', key: 'duplicate-case', icon: renderIcon(['M16 4h2a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2h2', 'M9 14l2 2 4-4']) },
    { type: 'divider', key: 'd2' },
    { label: '删除本用例', key: 'delete-case', props: { style: 'color: #DC2626' }, icon: renderIcon(['M3 6h18', 'M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2'], '#DC2626') },
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
  const s = caseSets.value.find((item: any) => item.id === targetId)
  if (!s) return
  switch (key) {
    case 'eval':
      requestSelectCaseSet(targetId, () => openLaunchDrawer())
      break
    case 'confirm-set':
      await confirmCaseSet()
      break
    case 'export-excel':
      exportExcel()
      break
    case 'export-xmind':
      exportXMind()
      break
    case 'rename':
      openNameDialog('重命名用例集', '用例集名称', s.name, async (val) => {
        const updated = await api.cases.updateSet(targetId, { name: val })
        const idx = caseSets.value.findIndex((item: any) => item.id === targetId)
        if (idx !== -1) caseSets.value[idx] = updated
        await loadCaseSets()
        message.success('重命名成功')
      })
      break
    case 'copy-id':
      await navigator.clipboard.writeText(targetId)
      message.success('已复制用例集 ID')
      break
    case 'delete-set':
      confirmDeleteCaseSet(s)
      break
  }
}

function confirmDeleteCaseSet(s: CaseSet) {
  dialog.warning({
    title: '删除用例集确认',
    content: `确认删除「${s.name}」？关联的历史评测任务不受影响。`,
    positiveText: '确认删除',
    negativeText: '取消',
    onPositiveClick: async () => {
      try {
        await api.cases.cancelSet(s.id, '用户删除用例集')
        if (activeSetId.value === s.id) activeSetId.value = ''
        await loadCaseSets()
        message.success(`已删除「${s.name}」`)
      } catch (err: any) {
        message.error(err.message || '删除失败')
      }
    },
  })
}

async function handleFolderCtxAction(key: string, folderId: string) {
  if (key === 'new-set') createEmptyCaseSet()
}

async function handleRowCtxAction(key: string, rowIdx: number) {
  const c = cases.value[rowIdx]
  if (!c) return
  switch (key) {
    case 'edit':
      openCaseEditModal(rowIdx)
      break
    case 'copy-json':
      await navigator.clipboard.writeText(JSON.stringify(c, null, 2))
      message.success('已复制用例 JSON')
      break
    case 'toggle-check':
      toggleCaseChecked(c)
      break
    case 'insert-above':
      cases.value.splice(rowIdx, 0, buildEmptyCase())
      hasUnsavedChanges.value = true
      message.info('已在上方插入用例')
      break
    case 'insert-below':
      cases.value.splice(rowIdx + 1, 0, buildEmptyCase())
      hasUnsavedChanges.value = true
      message.info('已在下方插入用例')
      break
    case 'duplicate-case': {
      const copy: ExtendedTestCase = {
        ...c,
        id: `temp-${Date.now()}-${Math.random().toString(36).slice(2, 6)}`,
        code: `TC-${String(cases.value.length + 1).padStart(3, '0')}`,
        extras: { ...c.extras },
      }
      cases.value.splice(rowIdx + 1, 0, copy)
      hasUnsavedChanges.value = true
      message.success(`已复制用例 ${c.code}`)
      break
    }
    case 'delete-case':
      deleteCase(rowIdx)
      break
  }
}

// 弹窗状态
const nameDialog = ref<{ show: boolean; title: string; label: string; value: string; action: ((val: string) => void | Promise<void>) | null }>({
  show: false,
  title: '',
  label: '',
  value: '',
  action: null,
})
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

// 用例结构化编辑弹窗
const caseEdit = ref<{
  show: boolean
  idx: number
  code: string
  name: string
  module: string
  strategy: CaseStrategy
  priority: CasePriority
  preconditions: string
  expected_result: string
}>({
  show: false,
  idx: -1,
  code: '',
  name: '',
  module: '',
  strategy: '正向',
  priority: 'HX',
  preconditions: '',
  expected_result: '',
})

function openCaseEditModal(idx: number) {
  const c = cases.value[idx]
  if (!c) return
  caseEdit.value = {
    show: true,
    idx,
    code: c.code,
    name: c.name,
    module: c.module || '通用',
    strategy: c.strategy || '正向',
    priority: c.priority || 'HX',
    preconditions: c.preconditions || '',
    expected_result: c.expected_result || '',
  }
}

function saveCaseEdit() {
  const c = cases.value[caseEdit.value.idx]
  if (!c) return
  c.name = caseEdit.value.name.trim()
  c.module = caseEdit.value.module.trim()
  c.strategy = caseEdit.value.strategy
  c.priority = caseEdit.value.priority
  c.preconditions = caseEdit.value.preconditions.trim()
  c.expected_result = caseEdit.value.expected_result.trim()
  hasUnsavedChanges.value = true
  caseEdit.value.show = false
  message.success(`已更新用例 ${c.code}，保存后生效`)
}

// 批量映射至数据集弹窗
const batchMap = ref({ show: false, targetDatasetId: '' })
const datasetsList = ref<Dataset[]>([])
const datasetOptions = computed(() => datasetsList.value.map(d => ({ label: `${d.name} (v${d.version})`, value: d.id })))

async function openBatchMapModal() {
  try {
    datasetsList.value = await api.datasets.list()
    batchMap.value = { show: true, targetDatasetId: datasetsList.value[0]?.id || '' }
  } catch {
    message.error('加载数据集失败')
  }
}

async function confirmBatchMap() {
  const dsId = batchMap.value.targetDatasetId
  if (!dsId) return
  const selected = cases.value.filter(c => selectedCaseIds.value.includes(c.id || c.code))
  if (!selected.length) return
  try {
    const rows = ((await api.datasets.getRows(dsId)) || []).slice()
    let maxRowNo = Math.max(0, ...rows.map(r => r.row_no || 0))
    selected.forEach(c => {
      rows.push({
        row_no: ++maxRowNo,
        question: c.name,
        reference: c.expected_result,
        context: c.preconditions || null,
        tags: `${c.strategy},${c.priority}`,
        difficulty: c.priority === 'HX' ? '高' : '中等',
      } as any)
      c.target_dataset_id = dsId
    })
    await api.datasets.saveRows(dsId, rows as any)
    hasUnsavedChanges.value = true
    batchMap.value.show = false
    selectedCaseIds.value = []
    message.success(`已将 ${selected.length} 条用例映射导入指定数据集`)
  } catch (err: any) {
    message.error(err.message || '映射失败')
  }
}

// 自定义扩展列
const addCol = ref({ show: false, key: '', name: '' })
function openAddColModal() {
  addCol.value = { show: true, key: '', name: '' }
}
function confirmAddCol() {
  const s = currentSet.value
  if (!s) return
  const key = addCol.value.key.trim().toLowerCase()
  const name = addCol.value.name.trim()
  if (!/^[a-z][a-z0-9_]*$/.test(key)) {
    message.warning('字段 Key 需以字母开头，仅含小写字母/数字/下划线')
    return
  }
  if (!name) {
    message.warning('请填写列显示名称')
    return
  }
  const list = customColsMap.value[s.id] || []
  if (list.some(col => col.key === key)) {
    message.warning('该字段 Key 已存在')
    return
  }
  const nextCols: CustomColumn[] = [...list, { key, name, type: 'text' }]
  customColsMap.value[s.id] = nextCols
  cases.value.forEach(c => {
    if (!c.extras) c.extras = {}
    c.extras[key] = ''
  })
  hasUnsavedChanges.value = true
  addCol.value.show = false
  message.success(`已添加用例属性列「${name}」`)
}

function removeCustomCol(key: string) {
  const s = currentSet.value
  if (!s) return
  const prevCols = customColsMap.value[s.id] || []
  customColsMap.value[s.id] = prevCols.filter(col => col.key !== key)
  cases.value.forEach(c => {
    if (c.extras) delete c.extras[key]
  })
  hasUnsavedChanges.value = true
  message.info(`已移除列 ${key}`)
}

// 抽屉式 PRD 用例推导向导
const PRD_PRESETS = [
  { name: '收银台跨境支付与结算', desc: '用户在跨境电商结算时选用 Visa/MasterCard 外币快捷支付，涉及 3DS 认证、汇率换算与扣款回调。' },
  { name: '账户风控防刷与封禁', desc: '同一 IP 短时间内频繁注册或登录密码连续输错 5 次，系统触发图形验证码或人脸核身并临时冻结 30 分钟。' },
  { name: '全额退款与售后逆向', desc: '未发货订单申请全额退款原路退回；已发货订单需商家收货质检无误后 1-3 工作日释放资金。' },
]

interface AiCaseCandidate {
  selected: boolean
  code: string
  name: string
  module: string
  strategy: CaseStrategy
  priority: CasePriority
  preconditions: string
  steps: string[]
  expected_result: string
}

const aiGen = ref({
  show: false,
  step: 1 as 1 | 2,
  preset: PRD_PRESETS[0].desc,
  prdText: PRD_PRESETS[0].desc,
  strategies: [...STRATEGIES],
  count: 10,
  model: 'gpt-4.1',
  temperature: 0.5,
  generating: false,
  candidates: [] as AiCaseCandidate[],
})

const presetOptions = computed(() => PRD_PRESETS.map(p => ({ label: `${p.name} · ${p.desc.slice(0, 30)}...`, value: p.desc })))
const aiSelectedCount = computed(() => aiGen.value.candidates.filter(c => c.selected).length)
const aiAllSelected = computed(() => aiGen.value.candidates.length > 0 && aiSelectedCount.value === aiGen.value.candidates.length)

function openAiGenDrawer() {
  aiGen.value.show = true
  aiGen.value.step = 1
}
function onPresetChange(val: string) {
  aiGen.value.prdText = val
}
function toggleStrategy(s: CaseStrategy) {
  const idx = aiGen.value.strategies.indexOf(s)
  if (idx >= 0) aiGen.value.strategies.splice(idx, 1)
  else aiGen.value.strategies.push(s)
}

async function runAiGenerateCases() {
  if (!aiGen.value.prdText.trim()) {
    message.warning('请填写 PRD 需求描述')
    return
  }
  if (!aiGen.value.strategies.length) {
    message.warning('请至少选择一个测试策略')
    return
  }
  aiGen.value.generating = true
  try {
    let candidates: AiCaseCandidate[] = []
    if (api.isMock()) {
      await new Promise(resolve => setTimeout(resolve, 500))
      const strats = aiGen.value.strategies
      candidates = Array.from({ length: aiGen.value.count }, (_, i) => ({
        selected: true,
        code: `TC-${String(i + 1).padStart(3, '0')}`,
        name: `验证跨境交易场景下的测试用例 #${i + 1}`,
        module: '收银支付',
        strategy: strats[i % strats.length],
        priority: (i === 0 ? 'HX' : i % 2 === 0 ? 'FHX' : 'BJ') as CasePriority,
        preconditions: '账户处于正常状态，绑卡成功',
        steps: ['1. 唤起收银台', '2. 选择外卡支付', '3. 完成 3DS 校验'],
        expected_result: '返回扣款成功回调并在 100ms 内推送账单流水。',
      }))
    } else {
      const generated = await api.cases.generateCases({
        prd_text: aiGen.value.prdText.trim(),
        strategies: aiGen.value.strategies,
        count: aiGen.value.count,
        model: aiGen.value.model,
        temperature: aiGen.value.temperature,
      })
      candidates = (generated as any[]).map((c, i) => ({
        selected: true,
        code: c.code || `TC-${String(i + 1).padStart(3, '0')}`,
        name: c.name || c.question || '',
        module: c.module || '通用',
        strategy: (c.strategy as CaseStrategy) || '正向',
        priority: (c.priority as CasePriority) || 'HX',
        preconditions: c.preconditions || c.precondition || '',
        steps: Array.isArray(c.steps) ? c.steps : typeof c.steps === 'string' ? [c.steps] : [],
        expected_result: c.expected_result || c.expected || c.reference || '',
      }))
    }
    aiGen.value.candidates = candidates
    aiGen.value.step = 2
  } catch (err: any) {
    message.error(err.message || '推导用例失败')
  } finally {
    aiGen.value.generating = false
  }
}

function toggleAllCandidates() {
  const target = aiSelectedCount.value < aiGen.value.candidates.length
  aiGen.value.candidates.forEach(c => { c.selected = target })
}

async function commitAiCandidates() {
  const selected = aiGen.value.candidates.filter(c => c.selected)
  if (!selected.length) return
  if (!currentSet.value) {
    try {
      const created = await api.cases.createSet({ name: `PRD推导-${new Date().toLocaleDateString()}` })
      await loadCaseSets()
      await selectCaseSet(created.id)
    } catch {
      message.error('创建用例集失败')
      return
    }
  }
  let baseNum = cases.value.length
  selected.forEach(cand => {
    cases.value.push({
      id: `temp-${Date.now()}-${Math.random().toString(36).slice(2, 6)}`,
      set_id: activeSetId.value,
      code: `TC-${String(++baseNum).padStart(3, '0')}`,
      name: cand.name,
      module: cand.module,
      strategy: cand.strategy,
      priority: cand.priority,
      preconditions: cand.preconditions,
      steps: cand.steps,
      expected_result: cand.expected_result,
      checked: false,
      extras: {},
    })
  })
  hasUnsavedChanges.value = true
  aiGen.value.show = false
  message.success(`已导入 ${selected.length} 条用例，点击“保存修改”落库`)
}

function onGlobalKeydown(e: KeyboardEvent) {
  if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 's') {
    if (hasUnsavedChanges.value && currentSet.value?.status !== 'confirmed') {
      e.preventDefault()
      void persistCases()
    }
  }
}

onMounted(() => {
  void loadCaseSets()
  window.addEventListener('keydown', onGlobalKeydown)
})

onUnmounted(() => {
  window.removeEventListener('keydown', onGlobalKeydown)
})
</script>

<style scoped>
/* ─── 全局北欧极简浅色用例工作台 (Nordic Minimalist / Stripe 质感) ─── */
.cases-workbench {
  height: calc(100vh - var(--topbar-h) - 20px);
  min-height: 0;
  display: flex;
  flex-direction: column;
  outline: none;
  font-size: 14px;
}

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
  padding: 14px 16px;
  border-bottom: 1px solid #E7E7E2;
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
  gap: 7px;
  font-weight: 600;
  font-size: 14px;
  color: #18181B;
}
.title-icon {
  color: #0F766E;
}
.sidebar-actions {
  display: flex;
  gap: 5px;
}

.btn-xs {
  min-height: 25px;
  padding: 2px 8px;
  font-size: 12px;
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
  left: 9px;
  color: #A1A1AA;
  pointer-events: none;
}
.search-input {
  width: 100%;
  height: 30px;
  padding-left: 28px;
  padding-right: 24px;
  font-size: 13px;
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
  right: 7px;
  background: none;
  border: none;
  color: #A1A1AA;
  font-size: 12px;
  cursor: pointer;
  padding: 2px;
}
.clear-search-btn:hover {
  color: #18181B;
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
  font-size: 13.5px;
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
  font-size: 14px;
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
.file-icon {
  display: grid;
  place-items: center;
  flex-shrink: 0;
}
.file-icon.status-confirmed { color: #15803D; }
.file-icon.status-draft { color: #71717A; }
.file-icon.status-generated { color: #B45309; }

.node-name {
  flex: 1;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.version-badge {
  font-size: 11px;
  padding: 1px 5px;
  border-radius: 3px;
  background: #EFEFEA;
  color: #71717A;
}
.badge-confirmed { background: #F0FDF4; color: #15803D; }
.badge-draft { background: #F4F4F5; color: #71717A; }
.badge-generated { background: #FEF3C7; color: #92400E; }

.pending-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: #D97706;
}
.node-badge {
  margin-left: auto;
  font-family: var(--font-mono);
  font-size: 12px;
  color: #A1A1AA;
}

.tree-empty {
  padding: 36px 16px;
  text-align: center;
  color: #A1A1AA;
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
  padding: 12px 20px;
  border-bottom: 1px solid #E7E7E2;
  background: #FFFFFF;
  min-height: 58px;
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
  gap: 14px;
  flex-wrap: wrap;
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
  font-size: 17px;
  font-weight: 600;
  color: #18181B;
}
.status-badge {
  font-size: 11.5px;
  font-weight: 500;
  padding: 1px 7px;
  border-radius: 4px;
}
.status-confirmed { background: #F0FDF4; color: #166534; border: 1px solid #DCFCE7; }
.status-draft { background: #F4F4F5; color: #52525B; border: 1px solid #E4E4E7; }
.status-generated { background: #FEFCE8; color: #854D0E; border: 1px solid #FEF08A; }

.status-badge-amber {
  font-size: 11.5px;
  padding: 1px 7px;
  border-radius: 4px;
  background: #FEF3C7;
  color: #92400E;
}

.breadcrumb-row {
  font-size: 12px;
  color: #A1A1AA;
  display: flex;
  align-items: center;
  gap: 5px;
}
.breadcrumb-row .cur {
  color: #71717A;
}

/* 极速表内筛选框 */
.table-search-box {
  position: relative;
  display: flex;
  align-items: center;
  margin-left: 10px;
}
.table-search-icon {
  position: absolute;
  left: 8px;
  color: #A1A1AA;
  pointer-events: none;
}
.table-search-input {
  width: 210px;
  height: 28px;
  padding-left: 26px;
  padding-right: 52px;
  font-size: 12.5px;
  border-radius: 5px;
  border: 1px solid #E2E2DC;
  background: #F8F8F5;
  color: #18181B;
  outline: none;
  transition: all 0.12s ease;
}
.table-search-input:focus {
  width: 260px;
  background: #FFFFFF;
  border-color: #1E293B;
}
.grid-search-count {
  position: absolute;
  right: 18px;
  font-size: 11px;
  color: #A1A1AA;
}

.toolbar-action-group {
  display: flex;
  align-items: center;
  gap: 7px;
  flex-wrap: wrap;
}
.action-btn-group {
  display: flex;
  align-items: center;
  gap: 5px;
}

/* 按钮通用 (字号 13px) */
.btn {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-size: 13px;
  font-weight: 500;
  border-radius: 6px;
  cursor: pointer;
  transition: all 0.12s ease;
}
.btn-md {
  min-height: 30px;
  padding: 3px 12px;
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
  font-size: 10px;
  font-family: var(--font-mono);
  padding: 0 4px;
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
  font-size: 14px;
  color: #18181B;
}
.batch-actions {
  display: flex;
  align-items: center;
  gap: 8px;
}

/* ─── 指标与策略分布条 ─── */
.metrics-strip {
  padding: 8px 20px;
  background: #F8F8F5;
  border-bottom: 1px solid #E7E7E2;
  display: flex;
  align-items: center;
  gap: 12px;
  font-size: 13px;
}
.strip-left {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
}
.strip-label {
  color: #71717A;
}
.strip-divider {
  width: 1px;
  height: 14px;
  background: #D4D4D8;
}

.strategy-pills-bar {
  display: flex;
  gap: 5px;
}
.strategy-pill {
  border: 1px solid transparent;
  padding: 2px 8px;
  border-radius: 4px;
  font-size: 12.5px;
  cursor: pointer;
  background: #FFFFFF;
  color: #52525B;
  transition: all 0.1s ease;
}
.strategy-pill:hover {
  border-color: #D4D4D8;
}
.strategy-pill.active {
  font-weight: 600;
  border-color: #1E293B;
  background: #1E293B;
  color: #FFFFFF;
}

.status-indicator-warning {
  color: #B45309;
  display: flex;
  align-items: center;
  gap: 4px;
}
.status-indicator-success {
  color: #15803D;
  font-weight: 500;
}

.keyboard-flow-hint {
  display: flex;
  align-items: center;
  gap: 10px;
  font-size: 12px;
  color: #71717A;
}
.kbd-hint kbd {
  font-family: var(--font-mono);
  font-size: 11px;
  padding: 1px 4px;
  border-radius: 3px;
  background: #EFEFEA;
  color: #3F3F46;
  border: 1px solid #E2E2DC;
}

/* ─── 表格：50px 舒适大行高 + 14px 字体 + 居中自定义多选框 ─── */
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
  padding: 10px 12px;
  font-size: 13px;
  font-weight: 600;
  color: #71717A;
  text-align: left;
  border-bottom: 1px solid #E7E7E2;
}
.nordic-table td {
  padding: 10px 12px;
  font-size: 14px;
  color: #18181B;
  vertical-align: middle;
  border-bottom: 1px solid #EFEFEA;
  height: 50px;
}

.th-chk, .td-chk {
  text-align: center !important;
  vertical-align: middle !important;
}

/* ─── 居中自定义多选框 (Custom Styled Centered Checkbox) ─── */
.clean-chk-wrap {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  cursor: pointer;
  width: 22px;
  height: 22px;
  position: relative;
  user-select: none;
  vertical-align: middle;
}
.clean-chk-native {
  position: absolute;
  opacity: 0;
  width: 0;
  height: 0;
  pointer-events: none;
}
.clean-chk-box {
  width: 18px;
  height: 18px;
  border-radius: 4px;
  border: 1.5px solid #D4D4D8;
  background: #FFFFFF;
  display: grid;
  place-items: center;
  transition: all 0.12s cubic-bezier(0.4, 0, 0.2, 1);
  color: transparent;
}
.clean-chk-wrap:hover .clean-chk-box {
  border-color: #1E293B;
  background: #F8F8F5;
}
.clean-chk-native:checked + .clean-chk-box {
  background: #1E293B;
  border-color: #1E293B;
  color: #FFFFFF;
}
.clean-chk-native:focus-visible + .clean-chk-box {
  box-shadow: 0 0 0 2px rgba(30, 41, 59, 0.2);
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
  font-size: 11px;
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

.td-num {
  font-size: 12px;
  color: #A1A1AA;
}
.mono-bold {
  font-family: var(--font-mono);
  font-weight: 600;
  font-size: 12.5px;
  color: #27272A;
}

.cell-edit {
  cursor: text;
}
.cell-content {
  min-height: 24px;
  display: flex;
  align-items: center;
  word-break: break-word;
  line-height: 1.5;
  font-size: 14px;
}
.cell-content.primary-text {
  font-weight: 500;
  color: #18181B;
}
.cell-content.empty {
  color: #B45309;
  font-style: italic;
  font-size: 13px;
}
.cell-content.placeholder {
  color: #A1A1AA;
}
.cell-content.mono-sm {
  font-family: var(--font-mono);
  font-size: 12.5px;
}

:deep(.highlight-match) {
  background: #FEF08A;
  color: #854D0E;
  padding: 0 2px;
  border-radius: 2px;
}

.inline-input {
  width: 100%;
  padding: 5px 8px;
  font: inherit;
  font-size: 13.5px;
  background: #FFFFFF;
  border: 1.5px solid #1E293B;
  border-radius: 4px;
  outline: none;
}
.inline-select {
  height: 28px;
  font-size: 12.5px;
  padding: 1px 6px;
  border-radius: 4px;
  border: 1px solid #1E293B;
  background: #FFFFFF;
}

.cell-invalid {
  border-bottom: 1px dashed #DC2626 !important;
}

.strategy-badge {
  display: inline-block;
  padding: 2px 7px;
  border-radius: 4px;
  font-size: 11.5px;
  font-weight: 500;
}
.badge-正向 { background: #F0FDF4; color: #166534; }
.badge-反向 { background: #FEF2F2; color: #991B1B; }
.badge-边界 { background: #FEFCE8; color: #854D0E; }
.badge-等价 { background: #EFF6FF; color: #1D4ED8; }
.badge-状态 { background: #FAF5FF; color: #6B21A8; }
.badge-场景 { background: #F0FDFA; color: #0F766E; }

.priority-badge {
  display: inline-block;
  padding: 1px 6px;
  border-radius: 3px;
  font-family: var(--font-mono);
  font-size: 11px;
  font-weight: 600;
}
.prio-HX { background: #FEF2F2; color: #DC2626; }
.prio-FHX { background: #FEF3C7; color: #D97706; }
.prio-BJ { background: #F0FDF4; color: #15803D; }
.prio-YC { background: #EFF6FF; color: #2563EB; }
.prio-ZD { background: #F4F4F5; color: #52525B; }
.prio-BL { background: #FAFAFA; color: #A1A1AA; }

.status-tag-green {
  font-size: 12px;
  color: #15803D;
  font-weight: 500;
}
.status-tag-clean {
  font-size: 12px;
  color: #A1A1AA;
}

.td-actions {
  text-align: right;
  white-space: nowrap;
}
.action-links {
  display: inline-flex;
  gap: 3px;
  opacity: 0.35;
  transition: opacity 0.1s ease;
}
.data-row:hover .action-links {
  opacity: 1;
}
.icon-link {
  background: none;
  border: none;
  padding: 4px;
  border-radius: 4px;
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
  padding: 56px 20px;
  text-align: center;
  color: #A1A1AA;
}
.empty-message {
  font-size: 14px;
}

/* ─── 空态 ─── */
.empty-main {
  display: grid;
  place-items: center;
  padding: 48px;
}
.empty-box {
  max-width: 480px;
  text-align: center;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 14px;
}
.empty-icon-wrapper {
  width: 68px;
  height: 68px;
  border-radius: 14px;
  background: #F4F4F0;
  border: 1px solid #E7E7E2;
  color: #71717A;
  display: grid;
  place-items: center;
}
.empty-box h3 {
  font-size: 17px;
  font-weight: 600;
  color: #18181B;
}
.empty-box p {
  font-size: 14px;
  color: #71717A;
  line-height: 1.5;
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
  margin-bottom: 22px;
  padding-bottom: 16px;
  border-bottom: 1px solid #E7E7E2;
}
.step-badge {
  display: flex;
  align-items: center;
  gap: 7px;
  font-size: 13.5px;
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
  width: 20px;
  height: 20px;
  border-radius: 50%;
  background: #F4F4F0;
  display: grid;
  place-items: center;
  font-size: 11px;
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
  gap: 16px;
}

.divider-title {
  font-size: 13px;
  font-weight: 600;
  color: #71717A;
  margin: 8px 0 3px;
}

.preview-box {
  max-height: 420px;
  overflow-y: auto;
  border: 1px solid #E7E7E2;
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
  width: 6px;
  height: 6px;
}
.custom-scroll::-webkit-scrollbar-track {
  background: transparent;
}
.custom-scroll::-webkit-scrollbar-thumb {
  background: rgba(0, 0, 0, 0.14);
  border-radius: 3px;
}
.custom-scroll::-webkit-scrollbar-thumb:hover {
  background: rgba(0, 0, 0, 0.24);
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
