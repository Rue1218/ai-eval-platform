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
        <!-- 1. 顶栏：层级分明的操作区与检索 -->
        <div class="main-toolbar">
          <div class="toolbar-default">
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

            <!-- 右侧操作组（操作金字塔） -->
            <div class="toolbar-action-group">
              <template v-if="currentSet.status !== 'confirmed'">
                <!-- 中频操作组 -->
                <div class="action-btn-group">
                  <button class="btn btn-secondary btn-md" aria-label="新增测试用例" @click="addCase">
                    <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="12" y1="5" x2="12" y2="19" /><line x1="5" y1="12" x2="19" y2="12" /></svg>
                    新增用例
                  </button>
                  <button class="btn btn-secondary btn-md" aria-label="新增扩展属性列" @click="openAddColModal">
                    <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="12" y1="5" x2="12" y2="19" /><line x1="5" y1="12" x2="19" y2="12" /></svg>
                    新增列
                  </button>
                  <button class="btn btn-secondary btn-md" aria-label="打开 PRD 用例推导向导" @click="openAiGenDrawer">
                    PRD 推导向导
                  </button>
                </div>

                <!-- 保存修改按钮 -->
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

                <!-- 主操作 CTA：确认入库 -->
                <button class="btn btn-primary btn-md primary-cta btn-success-solid" :loading="confirmingSet" aria-label="确认入库用例集" @click="confirmCaseSet">
                  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                    <polyline points="20 6 9 17 4 12" />
                  </svg>
                  确认入库
                </button>

                <!-- 更多操作下拉 -->
                <n-dropdown :options="moreMenuOptions" trigger="click" @select="handleMoreMenuSelect">
                  <button class="btn btn-ghost-subtle btn-md btn-icon-only" title="更多用例操作" aria-label="更多操作">
                    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                      <circle cx="12" cy="12" r="1"></circle>
                      <circle cx="19" cy="12" r="1"></circle>
                      <circle cx="5" cy="12" r="1"></circle>
                    </svg>
                  </button>
                </n-dropdown>
              </template>

              <!-- 已确认入库状态下 -->
              <template v-else>
                <div class="action-btn-group">
                  <button class="btn btn-secondary btn-md" aria-label="新增测试用例" @click="addCase">
                    <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="12" y1="5" x2="12" y2="19" /><line x1="5" y1="12" x2="19" y2="12" /></svg>
                    新增用例
                  </button>
                  <button class="btn btn-secondary btn-md" @click="exportExcel">
                    导出 Excel
                  </button>
                </div>

                <!-- 主操作 CTA：发起基准评测 -->
                <button class="btn btn-primary btn-md primary-cta" @click="openLaunchDrawer">
                  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                    <polygon points="5 3 19 12 5 21 5 3" />
                  </svg>
                  发起基准评测
                </button>

                <!-- 更多操作下拉 -->
                <n-dropdown :options="moreMenuOptions" trigger="click" @select="handleMoreMenuSelect">
                  <button class="btn btn-ghost-subtle btn-md btn-icon-only" title="更多用例操作" aria-label="更多操作">
                    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                      <circle cx="12" cy="12" r="1"></circle>
                      <circle cx="19" cy="12" r="1"></circle>
                      <circle cx="5" cy="12" r="1"></circle>
                    </svg>
                  </button>
                </n-dropdown>
              </template>
            </div>
          </div>
        </div>

        <!-- 2. 六大策略分布可交互胶囊筛选条 -->
        <div class="metrics-strip">
          <div class="strip-left">
            <span class="strip-label">策略筛选:</span>
            <div class="strategy-pills-bar">
              <button
                class="strategy-pill"
                :class="{ active: filterStrategy === '' }"
                @click="filterStrategy = ''"
              >
                全部 <b class="pill-num">{{ cases.length }}</b>
              </button>
              <button
                v-for="(count, st) in strategyDistribution"
                :key="st"
                class="strategy-pill"
                :class="[`pill-${st}`, { active: filterStrategy === st }]"
                @click="filterStrategy = filterStrategy === st ? '' : st"
              >
                {{ st }} <b class="pill-num">{{ count }}</b>
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

          <!-- 键盘流提示 (可悬停查看) -->
          <div class="keyboard-flow-hint" title="支持键盘方向键与快捷键无障碍操作">
            <span class="kbd-hint"><kbd>↑↓←→</kbd> 移动</span>
            <span class="kbd-hint"><kbd>Enter</kbd> 编辑</span>
            <span class="kbd-hint"><kbd>Space</kbd> 勾选</span>
          </div>
        </div>

        <!-- 3. 用例表格：分页网格 + 居中自定义多选框 -->
        <div ref="tableContainerRef" class="table-container custom-scroll" tabindex="0">
          <table class="nordic-table">
            <thead>
              <tr>
                <th class="th-chk" style="width: 48px" title="全选当前页用例" @click.stop="toggleCurrentPageCasesDirect">
                  <div class="clean-chk-box" :class="{ checked: isCurrentPageAllChecked }" role="checkbox" :aria-checked="isCurrentPageAllChecked">
                    <svg v-if="isCurrentPageAllChecked" class="chk-icon" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="#FFFFFF" stroke-width="3.2" stroke-linecap="round" stroke-linejoin="round">
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
              <!-- 当前页切片用例行 -->
              <tr
                v-for="(c, pageIdx) in pagedCases"
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
                  {{ (page - 1) * pageSize + pageIdx + 1 }}
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
                    <template v-if="gridSearch.trim() || filterStrategy">
                      <p style="margin-bottom: 8px;">未找到符合条件的测试用例（当前检索：{{ gridSearch.trim() ? `「${gridSearch.trim()}」` : '' }}{{ filterStrategy ? ` [${filterStrategy}策略]` : '' }}）。</p>
                      <button class="btn btn-secondary btn-sm" @click="clearAllFilters">
                        清空搜索与筛选条件
                      </button>
                    </template>
                    <span v-else>当前用例集暂无用例，点击上方「新增用例」或「PRD 推导向导」开始录入。</span>
                  </div>
                </td>
              </tr>
            </tbody>
          </table>
        </div>

        <!-- 4. 底部固定分页工具栏 (Table Pagination Bar) -->
        <div v-if="cases.length > 0" class="table-pagination-bar">
          <div class="pagination-info">
            <span class="pagination-total">
              共 <strong class="mono">{{ displayedCases.length }}</strong> 条用例
              <span class="pagination-pages mono">（第 {{ page }} / {{ totalPages }} 页）</span>
            </span>
            <span v-if="gridSearch.trim() || filterStrategy !== ''" class="pagination-filter-tag">
              已从全部 {{ cases.length }} 条中过滤
            </span>
            <span v-if="selectedCaseIds.length > 0" class="pagination-selection-tag">
              已勾选 {{ selectedCaseIds.length }} 条
            </span>
          </div>
          <div class="pagination-controls">
            <n-pagination
              v-model:page="page"
              v-model:page-size="pageSize"
              :item-count="displayedCases.length"
              :page-sizes="[10, 20, 50, 100]"
              show-size-picker
              show-quick-jumper
            />
          </div>
        </div>

        <!-- 5. 底部浮动批量操作栏 (Floating Action Dock) -->
        <transition name="slide-up">
          <div v-if="selectedCaseIds.length > 0" class="floating-batch-dock">
            <div class="batch-dock-info">
              <span class="batch-dock-badge">{{ selectedCaseIds.length }}</span>
              <span class="batch-dock-text">已选择 / 筛选共 {{ displayedCases.length }} 条</span>
            </div>
            <div class="batch-dock-actions">
              <button
                v-if="selectedCaseIds.length < displayedCases.length"
                class="btn btn-ghost btn-sm"
                @click="checkAllDisplayedCases"
              >
                全选所有筛选用例 ({{ displayedCases.length }})
              </button>
              <button class="btn btn-secondary btn-sm" @click="openBatchMapModal">
                批量映射至数据集
              </button>
              <button class="btn btn-danger btn-sm" @click="batchDeleteCases">
                批量删除 ({{ selectedCaseIds.length }})
              </button>
              <button class="btn btn-ghost btn-sm" @click="uncheckAllCases">
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
              <line x1="16" y1="13" x2="8" y2="13" />
              <line x1="16" y1="17" x2="8" y2="17" />
              <polyline points="10 9 9 9 8 9" />
            </svg>
          </div>
          <h3>尚未选择或创建用例集</h3>
          <p class="empty-desc">您可以基于 PRD 或接口需求文档一键自动推导六大策略测试用例，或新建空集手动录入。</p>
          <div class="empty-buttons">
            <button class="btn btn-primary btn-md primary-cta" @click="openAiGenDrawer">
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 2v4M12 18v4M4.93 4.93l2.83 2.83M16.24 16.24l2.83 2.83M2 12h4M18 12h4M4.93 19.07l2.83-2.83M16.24 7.76l2.83-2.83"/></svg>
              PRD 用例推导向导
            </button>
            <button class="btn btn-secondary btn-md" @click="createEmptyCaseSet">
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
      <p class="small" style="margin: 0 0 12px; color: var(--text-secondary); font-size: 13px">
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
import { ref, computed, onMounted, onUnmounted, watch, nextTick, h } from 'vue'
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

// ─── 更多操作下拉菜单配置 ───
const moreMenuOptions = computed<DropdownOption[]>(() => [
  {
    label: '导出为 Excel (XLSX)',
    key: 'export-excel',
    icon: renderIcon(['M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z', 'M14 2v6h6']),
  },
  {
    label: '导出为 XMind 脑图',
    key: 'export-xmind',
    icon: renderIcon(['M18 6L6 18', 'M6 6l12 12']),
  },
  {
    type: 'divider',
    key: 'd1',
  },
  {
    label: '批量映射至基准数据集',
    key: 'batch-map',
    disabled: cases.value.length === 0,
    icon: renderIcon(['M16 4h2a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2h2', 'M15 2H9a1 1 0 0 0-1 1v2a1 1 0 0 0 1 1h6a1 1 0 0 0 1-1V3a1 1 0 0 0-1-1z']),
  },
])

function handleMoreMenuSelect(key: string) {
  if (key === 'export-excel') exportExcel()
  else if (key === 'export-xmind') exportXMind()
  else if (key === 'batch-map') openBatchMapModal()
}

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

// ─── 分页与即时搜索过滤 (Pagination & Instant Filter) ───
const page = ref(1)
const pageSize = ref(20)

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

// 监听搜索或策略筛选变化，自动重置页码为 1
watch([gridSearch, filterStrategy], () => {
  page.value = 1
})

const totalPages = computed(() => Math.max(1, Math.ceil(displayedCases.value.length / pageSize.value)))

// 当前页切片
const pagedCases = computed(() => {
  const start = (page.value - 1) * pageSize.value
  return displayedCases.value.slice(start, start + pageSize.value)
})

function getOriginalCaseIndex(c: ExtendedTestCase): number {
  return cases.value.findIndex(item => item.id === c.id || item.code === c.code)
}
function getDisplayedIndex(c: ExtendedTestCase): number {
  return displayedCases.value.findIndex(item => item.id === c.id || item.code === c.code)
}

function clearAllFilters() {
  gridSearch.value = ''
  filterStrategy.value = ''
  page.value = 1
}

function checkAllDisplayedCases() {
  selectedCaseIds.value = displayedCases.value.map(c => c.id || c.code)
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
        const nextIdx = rowIdx - 1
        focusedCell.value = { rowIdx: nextIdx, field }
        const targetPage = Math.floor(nextIdx / pageSize.value) + 1
        if (targetPage !== page.value) page.value = targetPage
        scrollToFocusedRow(nextIdx)
        e.preventDefault()
      }
      break
    case 'ArrowDown':
      if (rowIdx < displayedCases.value.length - 1) {
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
        else if (rowIdx < displayedCases.value.length - 1) {
          const nextIdx = rowIdx + 1
          focusedCell.value = { rowIdx: nextIdx, field: fields[0] }
          const targetPage = Math.floor(nextIdx / pageSize.value) + 1
          if (targetPage !== page.value) page.value = targetPage
        }
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
const isCurrentPageAllChecked = computed(() => pagedCases.value.length > 0 && pagedCases.value.every(c => isCaseChecked(c)))
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

function toggleCurrentPageCasesDirect() {
  const target = !isCurrentPageAllChecked.value
  pagedCases.value.forEach(c => {
    const id = c.id || c.code
    const idx = selectedCaseIds.value.indexOf(id)
    if (target && idx < 0) selectedCaseIds.value.push(id)
    else if (!target && idx >= 0) selectedCaseIds.value.splice(idx, 1)
  })
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
      const maxPage = Math.max(1, Math.ceil(displayedCases.value.length / pageSize.value))
      if (page.value > maxPage) {
        page.value = maxPage
      }
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
  page.value = 1
  gridSearch.value = ''
  filterStrategy.value = ''
  focusedCell.value = null
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
  const newCase = buildEmptyCase()
  cases.value.push(newCase)
  hasUnsavedChanges.value = true
  const newPage = Math.ceil(displayedCases.value.length / pageSize.value)
  page.value = Math.max(1, newPage)
  nextTick(() => {
    editCell(newCase, 'name')
  })
  message.info('已新增用例行，填写后点击“保存修改”落库')
}

function deleteCase(idx: number) {
  cases.value.splice(idx, 1)
  hasUnsavedChanges.value = true
  const maxPage = Math.max(1, Math.ceil(displayedCases.value.length / pageSize.value))
  if (page.value > maxPage) {
    page.value = maxPage
  }
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
/* ─── 用例集工作台核心布局 ─── */
.cases-workbench {
  height: calc(100vh - var(--topbar-h) - 20px);
  min-height: 0;
  display: flex;
  flex-direction: column;
  outline: none;
  font-size: 13.5px;
  color: var(--text-primary);
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
  color: var(--c-cases);
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
  background: var(--t-cases);
  color: var(--c-cases);
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
.file-icon.case-set { color: var(--c-cases); }

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
  color: var(--c-cases);
}
.badge-confirmed { background: var(--t-cases); color: var(--c-cases); }
.badge-draft { background: var(--t-profiles); color: var(--c-profiles); }

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
.status-badge {
  font-size: 11.5px;
  font-weight: 500;
  padding: 1px 7px;
  border-radius: 4px;
}
.status-confirmed { background: var(--t-cases); color: var(--c-cases); border: 1px solid rgba(5, 150, 105, 0.2); }
.status-draft { background: var(--t-profiles); color: var(--c-profiles); border: 1px solid rgba(217, 119, 6, 0.2); }
.status-generated { background: var(--t-profiles); color: var(--c-profiles); border: 1px solid rgba(217, 119, 6, 0.2); }

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
.btn-success-solid {
  background: var(--accent-success) !important;
  border-color: var(--accent-success) !important;
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

/* ─── 策略分布胶囊条 ─── */
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
.strip-divider {
  width: 1px;
  height: 14px;
  background: var(--border-subtle);
}

.strategy-pills-bar {
  display: flex;
  align-items: center;
  gap: 6px;
  flex-wrap: wrap;
}
.strategy-pill {
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
.strategy-pill:hover {
  border-color: var(--accent-ai);
  color: var(--text-primary);
}
.strategy-pill.active {
  background: var(--text-primary);
  color: var(--bg-main);
  border-color: var(--text-primary);
  font-weight: 600;
}
.strategy-pill.pill-正向.active { background: var(--accent-success); border-color: var(--accent-success); color: #FFFFFF; }
.strategy-pill.pill-反向.active { background: var(--accent-error); border-color: var(--accent-error); color: #FFFFFF; }
.strategy-pill.pill-边界.active { background: var(--accent-warning); border-color: var(--accent-warning); color: #FFFFFF; }
.strategy-pill.pill-等价.active { background: var(--accent-info); border-color: var(--accent-info); color: #FFFFFF; }
.strategy-pill.pill-状态.active { background: var(--c-agent); border-color: var(--c-agent); color: #FFFFFF; }
.strategy-pill.pill-场景.active { background: var(--c-kb); border-color: var(--c-kb); color: #FFFFFF; }

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
  background: var(--t-cases);
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
.mono-bold {
  font-family: var(--font-mono);
  font-weight: 600;
  font-size: 12.5px;
  color: var(--text-primary);
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

.strategy-badge {
  display: inline-block;
  padding: 2px 7px;
  border-radius: 4px;
  font-size: 11.5px;
  font-weight: 500;
}
.badge-正向 { background: var(--t-cases); color: var(--c-cases); }
.badge-反向 { background: var(--t-stress); color: var(--c-stress); }
.badge-边界 { background: var(--t-profiles); color: var(--c-profiles); }
.badge-等价 { background: var(--t-datasets); color: var(--c-datasets); }
.badge-状态 { background: var(--t-agent); color: var(--c-agent); }
.badge-场景 { background: var(--t-kb); color: var(--c-kb); }

.priority-badge {
  display: inline-block;
  padding: 1px 6px;
  border-radius: 3px;
  font-family: var(--font-mono);
  font-size: 11px;
  font-weight: 600;
}
.prio-HX { background: var(--t-stress); color: var(--c-stress); }
.prio-FHX { background: var(--t-profiles); color: var(--c-profiles); }
.prio-BJ { background: var(--t-cases); color: var(--c-cases); }
.prio-YC { background: var(--t-agent); color: var(--c-agent); }
.prio-ZD { background: var(--bg-elevated); color: var(--text-secondary); border: 1px solid var(--border-subtle); }
.prio-BL { background: var(--bg-elevated); color: var(--text-tertiary); }

.status-tag-green {
  font-size: 12px;
  color: var(--accent-success);
  font-weight: 500;
}
.status-tag-clean {
  font-size: 12px;
  color: var(--text-tertiary);
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
  color: var(--c-cases);
  background: var(--t-cases);
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
