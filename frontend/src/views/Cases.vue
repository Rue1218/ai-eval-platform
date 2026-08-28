<template>
  <div class="cases-workbench">
    <div class="ft-layout" :style="{ '--ft-w': treeWidth + 'px' }">
      <!-- ─── 左侧：用例集目录侧边栏 ─── -->
      <div class="ft-sidebar">
        <!-- 侧边栏头部 -->
        <div class="ft-header">
          <div class="row-between mb8">
            <div class="ft-title">
              <svg class="ft-title-icon" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                <path d="M16 4h2a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2h2" />
                <rect x="8" y="2" width="8" height="4" rx="1" ry="1" />
                <path d="M9 14l2 2 4-4" />
              </svg>
              <span>用例集目录</span>
            </div>
            <!-- 新建用例集下拉触发器 -->
            <n-dropdown trigger="click" :options="createSetMenuOptions" @select="handleCreateSetMenu">
              <button class="btn btn-ai-soft btn-xs" aria-label="新建用例集菜单">
                <span class="sparkle">✨</span> + 新建集
              </button>
            </n-dropdown>
          </div>

          <!-- 搜索输入框 -->
          <div class="search-input-wrapper">
            <svg class="search-icon" width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
              <circle cx="11" cy="11" r="8" />
              <line x1="21" y1="21" x2="16.65" y2="16.65" />
            </svg>
            <input v-model="treeSearch" class="input tree-search-input" placeholder="搜索用例集..." aria-label="搜索用例集" />
            <button v-if="treeSearch" class="clear-search-btn" aria-label="清空搜索" @click="treeSearch = ''">✕</button>
          </div>
        </div>

        <!-- 目录树内容区 -->
        <div class="ft-tree custom-scroll">
          <div v-for="folder in filteredFolders" :key="folder.id" class="ft-folder-group">
            <!-- 文件夹节点 -->
            <div
              class="ft-node folder"
              :class="{ open: folder.open }"
              @click="folder.open = !folder.open"
              @contextmenu.prevent.stop="onFolderContextMenu($event, folder.id)"
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

            <!-- 用例集节点 -->
            <div v-if="folder.open" class="ft-folder-child">
              <div
                v-for="item in folder.items"
                :key="item.id"
                class="ft-node file"
                :class="{ active: activeSetId === item.id }"
                :title="`${item.name} · ${item.status === 'confirmed' ? '已入库' : item.status === 'cancelled' ? '已废弃' : '待确认'}`"
                @click="requestSelectCaseSet(item.id)"
                @contextmenu.prevent.stop="onSetContextMenu($event, item.id)"
              >
                <svg class="ft-file-icon case-icon" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                  <path d="M16 4h2a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2h2" />
                  <rect x="8" y="2" width="8" height="4" rx="1" ry="1" />
                </svg>
                <span class="ft-file-name">{{ item.name }}</span>
                <span
                  class="status-micro-pill"
                  :class="item.status === 'confirmed' ? 'status-confirmed' : item.status === 'cancelled' ? 'status-cancelled' : 'status-pending'"
                >
                  {{ item.status === 'confirmed' ? '已入库' : item.status === 'cancelled' ? '已废弃' : '待确认' }}
                </span>
              </div>
            </div>
          </div>

          <!-- 目录树空态 -->
          <div v-if="!filteredFolders.length" class="ft-empty-state">
            <svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" class="empty-icon">
              <circle cx="11" cy="11" r="8" />
              <line x1="21" y1="21" x2="16.65" y2="16.65" />
            </svg>
            <p>{{ treeSearch.trim() ? `未找到匹配「${treeSearch.trim()}」的用例集` : '暂无用例集，点击上方「+ 新建集」开始' }}</p>
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

      <!-- ─── 右侧：用例数据表格工作台 ─── -->
      <div v-if="currentSet" class="workspace-main">
        <!-- 1. 顶部工具栏 -->
        <div class="ws-toolbar">
          <div class="ws-title-group">
            <div class="ws-title-row">
              <span class="ws-dataset-title">{{ currentSet.name }}</span>
              <span class="version-pill">生成 <b class="num mono">{{ currentSet.generated_count }}</b> 条</span>
              <span
                class="status-header-chip"
                :class="currentSet.status === 'confirmed' ? 'chip-confirmed' : currentSet.status === 'cancelled' ? 'chip-cancelled' : 'chip-countdown'"
              >
                {{ currentSet.status === 'confirmed' ? '✓ 已确认入库' : currentSet.status === 'cancelled' ? '已废弃' : expiresLabel(currentSet) }}
              </span>
              <span class="kind-chip chip-cases" :style="modeTagStyle">{{ modeMappingLabel }}</span>
            </div>
            <!-- 面包屑路径提示 -->
            <div class="ws-breadcrumb">
              <span>测试用例资产</span>
              <span class="sep">/</span>
              <span class="cur">{{ currentSet.name }}</span>
            </div>
          </div>

          <!-- 右侧操作区 -->
          <div class="ws-action-group">
            <div class="action-btn-cluster">
              <button class="btn btn-secondary btn-sm" :disabled="currentSet.status === 'confirmed'" aria-label="新增测试用例" @click="addCase">
                <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="12" y1="5" x2="12" y2="19" /><line x1="5" y1="12" x2="19" y2="12" /></svg>
                新增用例
              </button>
              <button class="btn btn-secondary btn-sm" :disabled="currentSet.status === 'confirmed'" aria-label="新增自定义字段列" @click="openAddColModal">
                <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="12" y1="5" x2="12" y2="19" /><line x1="5" y1="12" x2="19" y2="12" /></svg>
                新增列
              </button>
            </div>

            <!-- AI 增强功能区 -->
            <div class="action-btn-cluster ai-cluster">
              <button class="btn btn-ai btn-sm" aria-label="打开 AI 用例生成向导" @click="openAiGenWizard">
                <span class="sparkle">✨</span> AI 生成用例集
              </button>
              <button class="btn btn-ai-soft btn-sm" :disabled="aiFilling || currentSet.status === 'confirmed'" aria-label="AI 智能补全断言" @click="handleAiFillCase">
                {{ aiFilling ? 'AI 补全中…' : 'AI 补全断言' }}
              </button>
            </div>

            <!-- 导入/导出与保存 -->
            <div class="action-btn-cluster">
              <button class="btn btn-secondary btn-sm" aria-label="导入 Excel 用例" @click="openImportModal()">
                <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" /><polyline points="17 8 12 3 7 8" /><line x1="12" y1="3" x2="12" y2="15" /></svg>
                导入 Excel
              </button>
              <n-dropdown trigger="click" :options="exportOptions" @select="handleExportSelect">
                <button class="btn btn-secondary btn-sm" aria-label="导出用例集菜单">
                  导出 ▾
                </button>
              </n-dropdown>
              <button
                class="btn btn-primary btn-sm save-btn"
                :class="{ dirty: hasUnsavedChanges, saved: justSaved }"
                :disabled="!hasUnsavedChanges || savingCases || currentSet.status === 'confirmed'"
                title="快捷键 Ctrl/⌘ + S"
                aria-label="保存用例集修改"
                @click="persistCases"
              >
                <span v-if="hasUnsavedChanges" class="dirty-indicator"></span>
                <span v-if="justSaved" class="saved-check-icon">✓</span>
                {{ savingCases ? '保存中…' : justSaved ? '已保存' : '保存修改' }}
                <kbd class="shortcut-pill">⌘S</kbd>
              </button>
            </div>

            <!-- 核心操作：确认入库 -->
            <button
              v-if="currentSet.status === 'generated'"
              class="btn btn-sign btn-sm launch-btn"
              title="确认此用例集入库并执行映射"
              aria-label="确认用例集入库"
              @click="confirmAllCases"
            >
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
                <polyline points="20 6 9 17 4 12" />
              </svg>
              确认入库
            </button>
          </div>
        </div>

        <!-- 2. 策略覆盖分布与自检全景概览栏 (Interactive Strategy Glance Bar) -->
        <div class="strategy-glance-bar">
          <div class="glance-strategy-left">
            <span class="glance-label">策略覆盖:</span>
            <!-- 策略过滤胶囊 -->
            <div class="strategy-pills-row">
              <span
                class="strategy-pill all-pill"
                :class="{ active: selectedStrategyFilter === '' }"
                @click="selectedStrategyFilter = ''"
              >
                全部 <b class="num mono">{{ cases.length }}</b>
              </span>
              <span
                v-for="st in strategyCounts"
                :key="st.name"
                class="strategy-pill"
                :class="[getStrategyTagClass(st.name), { active: selectedStrategyFilter === st.name }]"
                :title="`点击筛选 ${st.name} 策略用例`"
                @click="toggleStrategyFilter(st.name)"
              >
                {{ st.name }} <b class="num mono">{{ st.count }}</b>
              </span>
            </div>
          </div>

          <div class="grow"></div>

          <!-- 自检状态与采纳率提示 -->
          <div class="glance-strategy-right">
            <span v-if="currentSet.checks?.length" class="badge badge-failed" style="font-size: 11px">
              ⚠ 自检: {{ currentSet.checks.map(c => c.message).join('; ') }}
            </span>
            <span v-else-if="allStrategiesCovered" class="achievement-pill-case small">
              <span class="sparkle">✨</span> 六大策略完整覆盖 (100%)
            </span>
            <span v-else class="st-ok small">
              ✓ 策略自检通过
            </span>
            <span class="adoption-rate-pill">
              采纳率: <b class="num mono">{{ adoptionRate }}%</b>
            </span>
          </div>
        </div>

        <!-- 3. 用例表格数据网格 (Impeccable Cases Grid) -->
        <div class="ws-grid-container custom-scroll">
          <table class="ds-table impeccable-grid">
            <thead>
              <tr>
                <th class="th-chk" style="width: 40px">
                  <input v-model="allCasesChecked" type="checkbox" class="custom-checkbox" aria-label="全选所有测试用例" />
                </th>
                <th style="width: 80px">策略</th>
                <th style="width: 72px">级别</th>
                <th style="min-width: 95px">业务模块</th>
                <th style="min-width: 90px">子模块</th>
                <th style="min-width: 105px">功能点</th>
                <th style="min-width: 200px">
                  用例名称 / 测试点 <span class="req-star">*</span>
                </th>
                <th style="min-width: 260px">
                  预期结果 / 断言标准 <span class="req-star">*</span>
                </th>
                <th style="min-width: 140px">前置条件</th>
                <!-- 自定义扩展列表头 -->
                <th v-for="col in customCols" :key="col.key" class="custom-col-th" style="min-width: 120px">
                  <div class="custom-th-content">
                    <span class="custom-th-name">{{ col.name }}</span>
                    <span class="custom-th-key">({{ col.key }})</span>
                    <button class="custom-th-del" title="删除扩展列" :aria-label="`删除扩展列 ${col.name}`" @click.stop="removeCustomCol(col.key)">✕</button>
                  </div>
                </th>
                <th style="width: 90px">映射状态</th>
                <th style="width: 80px; text-align: right">操作</th>
              </tr>
            </thead>

            <tbody>
              <tr
                v-for="(c, idx) in displayedCases"
                :key="c.id"
                class="grid-row"
                :class="{ 'row-checked': selectedCaseIds.includes(c.id), 'row-incomplete': !c.name.trim() || !c.expected.trim() }"
                @contextmenu.prevent="onRowContextMenu($event, getOriginalCaseIndex(c))"
                @dblclick="openCaseEditModal(getOriginalCaseIndex(c))"
              >
                <!-- 勾选列 -->
                <td class="td-chk">
                  <input v-model="selectedCaseIds" type="checkbox" :value="c.id" class="custom-checkbox" :aria-label="`勾选用例 ${c.name || c.id}`" />
                </td>

                <!-- 策略列 (可切换下拉) -->
                <td class="cell-edit" @click="editCell(c, 'strategy')">
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

                <!-- 级别列 (可切换下拉) -->
                <td class="cell-edit" @click="editCell(c, 'priority')">
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
                  <span v-else class="prio-pill" :class="`prio-${c.priority}`">{{ c.priority }}</span>
                </td>

                <!-- 模块 -->
                <td class="cell-edit" @click="editCell(c, 'module')">
                  <input
                    v-if="editingCell?.row === c && editingCell?.field === 'module'"
                    v-model="c.module"
                    class="cell-input active"
                    placeholder="业务模块..."
                    :aria-label="`编辑用例 ${c.id} 业务模块`"
                    autofocus
                    @blur="finishEditing"
                    @keyup.enter="finishEditing"
                    @keyup.esc="cancelEditing"
                  />
                  <div v-else class="cell-text font-medium">{{ c.module }}</div>
                </td>

                <!-- 子模块 -->
                <td class="cell-edit" @click="editCell(c, 'submodule')">
                  <input
                    v-if="editingCell?.row === c && editingCell?.field === 'submodule'"
                    v-model="c.submodule"
                    class="cell-input active"
                    placeholder="子模块..."
                    :aria-label="`编辑用例 ${c.id} 子模块`"
                    autofocus
                    @blur="finishEditing"
                    @keyup.enter="finishEditing"
                    @keyup.esc="cancelEditing"
                  />
                  <div v-else class="cell-text" :class="{ empty: !c.submodule }">{{ c.submodule || '—' }}</div>
                </td>

                <!-- 功能点 -->
                <td class="cell-edit" @click="editCell(c, 'feature_point')">
                  <input
                    v-if="editingCell?.row === c && editingCell?.field === 'feature_point'"
                    v-model="c.feature_point"
                    class="cell-input active"
                    placeholder="功能点..."
                    :aria-label="`编辑用例 ${c.id} 功能点`"
                    autofocus
                    @blur="finishEditing"
                    @keyup.enter="finishEditing"
                    @keyup.esc="cancelEditing"
                  />
                  <div v-else class="cell-text" :class="{ empty: !c.feature_point }">{{ c.feature_point || '—' }}</div>
                </td>

                <!-- 用例名称 -->
                <td class="cell-edit" :class="{ 'cell-invalid': !c.name.trim() }" @click="editCell(c, 'name')">
                  <input
                    v-if="editingCell?.row === c && editingCell?.field === 'name'"
                    v-model="c.name"
                    class="cell-input active"
                    placeholder="输入用例名称..."
                    :aria-label="`编辑用例 ${c.id} 名称`"
                    autofocus
                    @blur="finishEditing"
                    @keyup.enter="finishEditing"
                    @keyup.esc="cancelEditing"
                  />
                  <div v-else class="cell-text font-semibold" :class="{ placeholder: !c.name.trim() }">
                    {{ c.name || '（未命名的测试点）' }}
                  </div>
                </td>

                <!-- 预期结果 -->
                <td class="cell-edit" :class="{ 'cell-invalid': !c.expected.trim() }" @click="editCell(c, 'expected')">
                  <input
                    v-if="editingCell?.row === c && editingCell?.field === 'expected'"
                    v-model="c.expected"
                    class="cell-input active"
                    placeholder="预期校验结果..."
                    :aria-label="`编辑用例 ${c.id} 预期结果`"
                    autofocus
                    @blur="finishEditing"
                    @keyup.enter="finishEditing"
                    @keyup.esc="cancelEditing"
                  />
                  <div v-else class="cell-text" :class="{ placeholder: !c.expected.trim() }">
                    {{ c.expected || '（待输入预期结果）' }}
                  </div>
                </td>

                <!-- 前置条件 -->
                <td class="cell-edit" @click="editCell(c, 'precondition')">
                  <input
                    v-if="editingCell?.row === c && editingCell?.field === 'precondition'"
                    v-model="c.precondition"
                    class="cell-input active"
                    placeholder="前置条件..."
                    :aria-label="`编辑用例 ${c.id} 前置条件`"
                    autofocus
                    @blur="finishEditing"
                    @keyup.enter="finishEditing"
                    @keyup.esc="cancelEditing"
                  />
                  <div v-else class="cell-text tertiary-text">{{ c.precondition || '无' }}</div>
                </td>

                <!-- 自定义扩展列 -->
                <td v-for="col in customCols" :key="col.key" class="cell-edit" @click="editExtraCell(c, col.key)">
                  <input
                    v-if="editingExtraCell?.row === c && editingExtraCell?.key === col.key"
                    :value="getCaseExtra(c, col.key)"
                    class="cell-input active"
                    :placeholder="col.name"
                    :aria-label="`编辑用例 ${c.id} ${col.name}`"
                    autofocus
                    @input="setCaseExtra(c, col.key, ($event.target as HTMLInputElement).value)"
                    @blur="finishExtraEditing"
                    @keyup.enter="finishExtraEditing"
                    @keyup.esc="cancelExtraEditing"
                  />
                  <div v-else class="cell-text" :class="{ empty: !getCaseExtra(c, col.key) }">
                    {{ getCaseExtra(c, col.key) || '—' }}
                  </div>
                </td>

                <!-- 映射状态 -->
                <td>
                  <span v-if="c.mapped" class="badge badge-succeeded">
                    <span class="bdot"></span> 已映射
                  </span>
                  <span v-else class="badge badge-awaiting_case_confirm">
                    <span class="bdot"></span> 待补全
                  </span>
                </td>

                <!-- 操作区 -->
                <td class="td-actions">
                  <div class="row-actions-cluster">
                    <button class="action-btn" title="详细弹窗编辑" :aria-label="`详细弹窗编辑用例 ${c.id}`" @click.stop="openCaseEditModal(getOriginalCaseIndex(c))">
                      <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7" /><path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z" /></svg>
                    </button>
                    <button v-if="currentSet.status !== 'confirmed'" class="action-btn danger" title="删除用例" :aria-label="`删除用例 ${c.id}`" @click.stop="deleteCase(getOriginalCaseIndex(c))">
                      <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="3 6 5 6 21 6" /><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2" /></svg>
                    </button>
                  </div>
                </td>
              </tr>

              <!-- 空态 -->
              <tr v-if="!displayedCases.length">
                <td :colspan="11 + customCols.length" class="empty-table-cell">
                  <div class="empty-table-notice">
                    <span v-if="selectedStrategyFilter">当前策略「{{ selectedStrategyFilter }}」暂无用例，点击上方「全部」查看所有。</span>
                    <span v-else>当前用例集暂无用例，点击上方「新增用例」或「✨ AI 生成用例集」开始生成。</span>
                  </div>
                </td>
              </tr>
            </tbody>
          </table>
        </div>

        <!-- 4. 浮动式批量操作与资产映射坞 (Floating Batch Action & Mapping Dock) -->
        <transition name="dock-slide">
          <div v-if="selectedCaseIds.length > 0" class="floating-batch-dock">
            <div class="dock-content">
              <span class="dock-count-badge">已选 <b class="num mono">{{ selectedCaseIds.length }}</b> / {{ cases.length }} 条</span>
              <div class="dock-divider"></div>

              <!-- 批量删除 -->
              <button
                v-if="currentSet.status !== 'confirmed'"
                class="btn btn-danger-soft btn-sm"
                aria-label="批量删除勾选用例"
                @click="batchDeleteCases"
              >
                批量删除 ({{ selectedCaseIds.length }})
              </button>

              <!-- 批量映射目标 -->
              <div class="dock-map-wrapper">
                <span class="dock-map-label">{{ modeMappingLabel }}:</span>
                <select v-model="mapTargetId" class="select dock-map-select" :disabled="mappingTargets.length === 0" aria-label="选择映射目标">
                  <option value="">选择目标数据集/QA</option>
                  <option v-for="target in mappingTargets" :key="target.id" :value="target.id">{{ target.name }}</option>
                </select>
                <button class="btn btn-primary btn-sm" :disabled="!mapTargetId" aria-label="执行批量映射" @click="handleBatchMap">
                  执行映射
                </button>
              </div>

              <div class="dock-divider"></div>
              <button class="dock-close-btn" title="取消全部勾选" aria-label="取消勾选全部用例" @click="selectedCaseIds = []">✕</button>
            </div>
          </div>
        </transition>
      </div>

      <!-- ─── 空态页面引导 ─── -->
      <div v-else class="workspace-main empty-workbench">
        <div class="empty-workbench-container">
          <div class="empty-workbench-icon">
            <svg width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">
              <path d="M16 4h2a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2h2" />
              <rect x="8" y="2" width="8" height="4" rx="1" ry="1" />
              <path d="M9 14l2 2 4-4" />
            </svg>
          </div>
          <h3>尚未选择或创建测试用例集</h3>
          <p class="empty-sub">你可以通过粘贴 PRD 文本由 AI 按六大策略生成候选用例，或导入已有 Excel 文件进行管理。</p>
          <div class="empty-actions-row">
            <button class="btn btn-ai" @click="openAiGenWizard">
              <span class="sparkle">✨</span> AI 智能生成用例集
            </button>
            <button class="btn btn-secondary" @click="openImportModal()">
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" /><polyline points="17 8 12 3 7 8" /><line x1="12" y1="3" x2="12" y2="15" /></svg>
              导入 Excel 用例
            </button>
            <button class="btn btn-sign" @click="handleCreateCaseSet()">
              + 新建空用例集
            </button>
          </div>
        </div>
      </div>
    </div>

    <!-- ─── 弹窗与抽屉 ─── -->
    <!-- 新建用例集弹窗 -->
    <n-modal v-model:show="showCreateSetModal" preset="card" title="新建测试用例集" style="width: 440px; max-width: calc(100vw - 24px)">
      <div class="field">
        <label class="field-label">用例集名称 <span class="req">*</span></label>
        <n-input v-model:value="newSetName" placeholder="例如：支付模块核心回归用例" autofocus @keyup.enter="createCaseSet" />
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
    <n-modal v-model:show="showEditCaseModal" preset="card" :title="`详细编辑用例 · ${editDraft.id || '新用例'}`" style="width: 660px; max-width: calc(100vw - 24px)">
      <div class="form-row">
        <div class="field">
          <label class="field-label">测试策略 (Strategy) <span class="req">*</span></label>
          <n-select v-model:value="editDraft.strategy" :options="strategyOptions" />
        </div>
        <div class="field">
          <label class="field-label">优先级 (Priority) <span class="req">*</span></label>
          <n-select v-model:value="editDraft.priority" :options="priorityOptions" />
        </div>
      </div>
      <div class="form-row">
        <div class="field">
          <label class="field-label">所属业务模块 <span class="req">*</span></label>
          <n-input v-model:value="editDraft.module" placeholder="如 登录 / 支付" />
        </div>
        <div class="field">
          <label class="field-label">子模块</label>
          <n-input v-model:value="editDraft.submodule" placeholder="可选，如 认证 / 结算" />
        </div>
      </div>
      <div class="form-row">
        <div class="field">
          <label class="field-label">功能点</label>
          <n-input v-model:value="editDraft.feature_point" placeholder="可选，如 验证码 / 余额扣减" />
        </div>
        <div class="field">
          <label class="field-label">用例名称 / 测试点 <span class="req">*</span></label>
          <n-input v-model:value="editDraft.name" placeholder="一句话描述被测目标" />
        </div>
      </div>
      <div class="field">
        <label class="field-label">预期结果 / 断言标准 (Expected Result) <span class="req">*</span></label>
        <n-input v-model:value="editDraft.expected" type="textarea" :autosize="{ minRows: 3, maxRows: 6 }" placeholder="可校验的预期行为或断言..." />
      </div>
      <div class="field">
        <label class="field-label">前置条件</label>
        <n-input v-model:value="editDraft.precondition" placeholder="可选，如 账号状态正常" />
      </div>
      <!-- 自定义扩展属性区 -->
      <template v-if="customCols.length">
        <div class="rail-label" style="margin: 12px 0 8px">自定义扩展属性</div>
        <div class="form-row">
          <div v-for="col in customCols" :key="col.key" class="field">
            <label class="field-label">{{ col.name }} ({{ col.key }})</label>
            <n-input
              :value="String(editDraft[col.key] ?? '')"
              @update:value="editDraft[col.key] = $event"
            />
          </div>
        </div>
      </template>
      <template #footer>
        <div style="display: flex; justify-content: flex-end; gap: 8px">
          <n-button @click="showEditCaseModal = false">取消</n-button>
          <n-button type="primary" @click="saveCaseEdit">保存用例修改</n-button>
        </div>
      </template>
    </n-modal>

    <!-- 新增扩展字段弹窗 -->
    <n-modal v-model:show="showAddColModal" preset="card" title="新增用例自定义字段 (Custom Field)" style="width: 460px; max-width: calc(100vw - 24px)">
      <div class="field">
        <label class="field-label">字段 Key (英文字母 / 下划线) <span class="req">*</span></label>
        <n-input v-model:value="newColKey" class="mono" placeholder="如 assert_type, env_tag" />
      </div>
      <div class="field">
        <label class="field-label">显示名称 <span class="req">*</span></label>
        <n-input v-model:value="newColName" placeholder="如 断言方式, 环境要求" />
      </div>
      <template #footer>
        <div style="display: flex; justify-content: flex-end; gap: 8px">
          <n-button @click="showAddColModal = false">取消</n-button>
          <n-button type="primary" :loading="addingCol" @click="addCustomCol">确认添加</n-button>
        </div>
      </template>
    </n-modal>

    <!-- 通用单输入弹窗 -->
    <n-modal v-model:show="promptState.show" preset="card" :title="promptState.title" style="width: 420px; max-width: calc(100vw - 24px)">
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

    <!-- AI 生成用例集两步向导 -->
    <n-modal v-model:show="showAiGenModal" preset="card" title="✨ AI 智能生成测试用例集" style="width: 780px; max-width: calc(100vw - 24px)" :mask-closable="false">
      <!-- 步骤指示器 -->
      <div class="wizard-steps-header">
        <div class="wizard-step-item" :class="{ active: aiStep === 'config', done: aiStep === 'preview' }">
          <span class="step-num">1</span>
          <span class="step-text">需求输入与六大策略配置</span>
        </div>
        <div class="step-line" :class="{ active: aiStep === 'preview' }"></div>
        <div class="wizard-step-item" :class="{ active: aiStep === 'preview' }">
          <span class="step-num">2</span>
          <span class="step-text">候选用例审核与采纳</span>
        </div>
      </div>

      <!-- Step 1：配置与需求输入 -->
      <div v-show="aiStep === 'config'" class="wizard-step-body">
        <div class="field">
          <label class="field-label">预设 PRD 业务需求模板</label>
          <n-select v-model:value="aiPresetIdx" :options="aiPresetOptions" />
        </div>
        <div class="field">
          <label class="field-label">PRD 业务需求描述 / 接口定义 (Source Material) <span class="req">*</span></label>
          <n-input v-model:value="aiSource" type="textarea" :autosize="{ minRows: 4, maxRows: 8 }" placeholder="支持粘贴 Markdown 文本、接口列表或业务规则描述..." />
        </div>

        <div class="rail-label" style="margin: 10px 0 8px">六大测试策略分布配比与规模控制</div>
        <div class="ai-weights-grid">
          <div v-for="s in STRATEGY_LIST" :key="s" class="weight-card">
            <div class="weight-title">{{ s }}</div>
            <n-input-number v-model:value="aiWeights[s]" :min="0" :max="100" size="small">
              <template #suffix>%</template>
            </n-input-number>
          </div>
        </div>

        <div class="form-row" style="margin-top: 10px">
          <div class="field">
            <label class="field-label">目标生成规模 (<b class="num mono">{{ aiCount }}</b> 条)</label>
            <n-slider v-model:value="aiCount" :min="6" :max="45" :step="1" style="margin-top: 8px" />
            <span v-if="aiCount > 30" class="field-hint" style="color: var(--accent-warning)">⚠ 大规模生成可能耗时较长，单次上限 45 条</span>
            <span v-else class="field-hint">防爆保护：单次生成上限 45 条</span>
          </div>
          <div class="field">
            <label class="field-label">用例结构属性生成</label>
            <div class="row wrap" style="gap: 12px; font-size: 12px; margin-top: 6px">
              <n-checkbox v-model:checked="aiStruct.precondition">前置条件</n-checkbox>
              <n-checkbox v-model:checked="aiStruct.steps">测试执行步骤</n-checkbox>
              <n-checkbox v-model:checked="aiStruct.expected">预期断言</n-checkbox>
              <n-checkbox v-model:checked="aiStruct.autoPriority">HX/FHX 自动定级</n-checkbox>
            </div>
          </div>
        </div>
      </div>

      <!-- Step 2：候选用例策略分布与交互式预览 -->
      <div v-show="aiStep === 'preview'" class="wizard-step-body">
        <div class="strategy-banner mb8" style="border-radius: 8px; border: 1px solid var(--border-subtle)">
          <span class="tertiary" style="font-weight: 600">策略分布:</span>
          <div class="row wrap" style="gap: 6px">
            <span v-for="st in aiStrategyCounts" :key="st.name" class="strategy-badge" :class="getStrategyTagClass(st.name)">
              {{ st.name }} <b class="num mono">{{ st.count }}</b>
            </span>
          </div>
          <span class="grow"></span>
          <span class="st-ok small">✓ 6 大策略覆盖</span>
        </div>
        <div class="row-between mb8">
          <span style="font-weight: 600; font-size: 13px">候选用例列表（已生成 <b class="num mono">{{ aiCandidates.length }}</b> 条，可点击修改）</span>
          <button class="link-btn" @click="toggleAllCandidates(!allCandidatesChecked)">全选 / 全不选</button>
        </div>
        <div class="preview-table-wrapper custom-scroll">
          <table class="ds-table">
            <thead>
              <tr>
                <th style="width: 36px"><input v-model="allCandidatesChecked" type="checkbox" aria-label="全选候选列表" /></th>
                <th style="width: 65px">策略</th>
                <th style="width: 60px">级别</th>
                <th style="width: 90px">模块</th>
                <th>用例名称</th>
                <th>预期断言结果</th>
                <th style="width: 60px">操作</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="(cand, ci) in aiCandidates" :key="cand.id">
                <td><input v-model="cand.selected" type="checkbox" :aria-label="`选择候选 ${cand.name}`" /></td>
                <td><span class="strategy-badge" :class="getStrategyTagClass(cand.strategy)">{{ cand.strategy }}</span></td>
                <td><span class="prio-pill" :class="`prio-${cand.priority}`">{{ cand.priority }}</span></td>
                <td><input v-model="cand.module" class="cell-input" style="font-size: 12px" aria-label="编辑候选模块" /></td>
                <td><input v-model="cand.name" class="cell-input" style="font-size: 12px" aria-label="编辑候选名称" /></td>
                <td><input v-model="cand.expected" class="cell-input" style="font-size: 12px" aria-label="编辑候选预期" /></td>
                <td><button class="link-btn danger" style="font-size: 11px" aria-label="剔除此条候选" @click="removeCandidate(ci)">剔除</button></td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>

      <template #footer>
        <div class="row-between" style="width: 100%">
          <n-button v-show="aiStep === 'preview'" @click="aiStep = 'config'">← 返回调整策略</n-button>
          <span class="grow"></span>
          <n-button @click="showAiGenModal = false">取消</n-button>
          <n-button v-if="aiStep === 'config'" type="primary" :loading="generatingCases" @click="generateAiCandidates">
            {{ generatingCases ? 'AI 正在分析 PRD 并推导用例…' : '立即开始 AI 生成 →' }}
          </n-button>
          <n-button v-else type="primary" :disabled="aiSelectedCount === 0" :loading="committingAi" @click="commitAiCaseSet">
            采纳并创建用例集 ({{ aiSelectedCount }} 条)
          </n-button>
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
const PRIORITY_LABELS: Record<string, string> = { HX: '核心', FHX: '非核心', BJ: '边界问题', YC: '异常', ZD: '中断', BL: '遍历' }
const strategyOptions = STRATEGY_LIST.map(s => ({ label: s, value: s }))
const priorityOptions = PRIORITY_LIST.map(p => ({ label: `${p} ${PRIORITY_LABELS[p]}`, value: p }))

const message = useMessage()
const dialog = useDialog()
const modeStore = useModeStore()
const treeSearch = ref('')
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
const TREE_W_KEY = 'ae_ft_w_cases'
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

// ─── AI 生成两步向导状态 ───
const PRD_PRESETS = [
  { name: 'PRD-聚合收银台与快捷退款', text: '收银台支持余额、银行卡快捷支付与企业对公转账。单笔提现上限 5 万元，单日上限 20 万元。连续输错密码 5 次锁定 2 小时，人脸解锁。退款 1-3 工作日原路退回。' },
  { name: 'PRD-用户中心与双因子认证 (2FA)', text: '支持账密、短信验证码及扫码登录。登录失败 3 次出图形验证码，失败 5 次锁定 15 分钟。敏感操作需二次验证短信验证码。' },
  { name: 'PRD-营销中心满减优惠券结算', text: '支持满减券、折扣券及免邮券。一笔订单仅能使用一张主券。发生部分退款时按商品实付比例分摊券金额。' },
]
const showAiGenModal = ref(false)
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

/** 切换策略标签筛选 */
function toggleStrategyFilter(strategy: string) {
  if (selectedStrategyFilter.value === strategy) {
    selectedStrategyFilter.value = ''
  } else {
    selectedStrategyFilter.value = strategy
  }
}

/** 经过策略筛选后展示的用例列表 */
const displayedCases = computed(() => {
  if (!selectedStrategyFilter.value) return cases.value
  return cases.value.filter(c => c.strategy === selectedStrategyFilter.value)
})

/** 获取展示用例在原 cases 列表中的索引 */
function getOriginalCaseIndex(caseItem: TestCase): number {
  return cases.value.findIndex(c => c.id === caseItem.id)
}

const adoptionRate = computed(() => Math.round((selectedCaseIds.value.length / (cases.value.length || 1)) * 100))
const mapTarget = computed<'dataset' | 'gold_qa'>(() => modeStore.mode === 'rag' ? 'gold_qa' : 'dataset')
const modeMappingLabel = computed(() => modeStore.mode === 'rag' ? '映射至黄金 QA' : '映射至基准数据集')
const modeTagStyle = computed(() => ({
  color: modeStore.mode === 'rag' ? 'var(--c-kb)' : 'var(--c-datasets)',
  borderColor: modeStore.mode === 'rag' ? 'var(--t-kb)' : 'var(--t-datasets)',
}))

const customCols = computed<CustomCol[]>(() => (currentSet.value ? customColsMap.value[currentSet.value.id] ?? [] : []))

const allCasesChecked = computed({
  get: () => cases.value.length > 0 && selectedCaseIds.value.length === cases.value.length,
  set: (val: boolean) => { selectedCaseIds.value = val ? cases.value.map(c => c.id) : [] },
})

const createSetMenuOptions: DropdownOption[] = [
  { label: '✨ AI 生成用例集', key: 'ai' },
  { label: '导入 Excel 用例', key: 'import' },
  { label: '下载 Excel 模板', key: 'template' },
  { label: '新建空用例集', key: 'empty' },
]

const exportOptions: DropdownOption[] = [
  { label: '⤓ 导出 Excel (.xlsx)', key: 'xlsx' },
  { label: '⤓ 导出 XMind (.xmind)', key: 'xmind' },
]

function handleExportSelect(key: string | number) {
  if (key === 'xlsx') exportXlsx()
  else if (key === 'xmind') exportXmind()
}

const ctxSetOptions = computed<DropdownOption[]>(() => {
  const set = caseSets.value.find(s => s.id === ctxSet.setId)
  const opts: DropdownOption[] = []
  if (set?.status === 'generated') opts.push({ label: '✓ 确认入库此用例集', key: 'confirm' })
  opts.push(
    { label: '⇄ 批量映射到评测集', key: 'map' },
    { label: '⤴ 导入 Excel (.xlsx)', key: 'import' },
    { label: '⤓ 导出 Excel (.xlsx)', key: 'export' },
    { label: '⤓ 导出 XMind (.xmind)', key: 'export-xmind' },
    { label: '📋 复制用例集 ID', key: 'copy-id' },
    { type: 'divider', key: 'd1' },
    { label: '✏ 重命名', key: 'rename' },
    { label: '🗑 废弃用例集', key: 'cancel', props: { style: 'color: var(--accent-error)' } },
  )
  return opts
})

const ctxFolderOptions: DropdownOption[] = [
  { label: '📋 在此目录下新建用例集', key: 'new-set' },
  { label: '📁 新建子目录', key: 'new-folder' },
  { label: '⤴ 导入 Excel 到此目录', key: 'import' },
  { type: 'divider', key: 'd1' },
  { label: '✏ 重命名目录', key: 'rename' },
  { label: '🗑 删除目录', key: 'delete', props: { style: 'color: var(--accent-error)' } },
]

const ctxRowOptions = computed<DropdownOption[]>(() => {
  const row = cases.value[ctxRow.idx]
  const checked = row ? selectedCaseIds.value.includes(row.id) : false
  const readonly = currentSet.value?.status === 'confirmed'
  const opts: DropdownOption[] = [
    { label: checked ? '☑ 取消勾选本行' : '☐ 勾选本行', key: 'toggle-check' },
    { label: '✏ 弹窗详细编辑', key: 'edit' },
  ]
  if (!readonly) opts.push({ label: '✨ AI 补全属性', key: 'ai-fill' })
  opts.push({ label: '📋 复制为 JSON', key: 'copy' })
  if (!readonly) {
    opts.push(
      { type: 'divider', key: 'd1' },
      { label: '⬆ 在上方插入新用例', key: 'insert-above' },
      { label: '＋ 在下方插入新用例', key: 'insert' },
      { label: '⧉ 创建本行副本', key: 'duplicate' },
      { label: '🗑 删除本用例', key: 'delete', props: { style: 'color: var(--accent-error)' } },
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
  if (ms <= 0) return '72h 确认窗口已过期'
  const hours = Math.floor(ms / 3_600_000)
  return `72h 倒计时: 剩 ${hours}h`
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
    message.error(err.message || '加载用例集详情失败')
  }
}

function requestSelectCaseSet(id: string): Promise<boolean> {
  if (!id || id === activeSetId.value) return Promise.resolve(false)
  if (!hasUnsavedChanges.value) {
    return selectCaseSet(id).then(() => true)
  }
  return new Promise(resolve => {
    dialog.warning({
      title: '存在未保存的修改',
      content: '当前用例集有未保存的编辑，切换后将丢失。是否保存后切换？',
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
  message.info('已新增空白用例，填写后点击“保存修改”落库')
}

function deleteCase(index: number) {
  if (currentSet.value?.status === 'confirmed') return
  const [removed] = cases.value.splice(index, 1)
  if (removed) selectedCaseIds.value = selectedCaseIds.value.filter(id => id !== removed.id)
  hasUnsavedChanges.value = true
  message.info('已删除用例，点击“保存修改”后生效')
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
    message.success('用例修改已成功保存')
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
    message.success('用例集已创建')
  } catch (err: any) {
    message.error(err.message || '创建用例集失败')
  } finally {
    creatingSet.value = false
  }
}

function openAiGenWizard() {
  aiStep.value = 'config'
  aiPresetIdx.value = 0
  aiSource.value = PRD_PRESETS[0].text
  aiCandidates.value = []
  showAiGenModal.value = true
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
      await new Promise(resolve => setTimeout(resolve, 500))
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
      if (!items.length) throw new Error('生成接口未返回候选用例')
    }
    aiCandidates.value = items
    aiStep.value = 'preview'
  } catch (err: any) {
    message.error(err.message || 'AI 生成候选失败')
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
    const presetName = PRD_PRESETS[aiPresetIdx.value]?.name || 'AI 生成'
    const created = await api.cases.createSet({ name: `AI-${presetName}`.slice(0, 30) })
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
    showAiGenModal.value = false
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
    message.error(err.message || 'AI 补全失败')
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
  if (applied > 0) message.success(`AI 已为 ${applied} 条用例生成补全候选，确认后点击“保存修改”落库`)
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
      message.success('用例集已确认入库，并完成数据集映射')
    } else if (mapTargetId.value && mapTarget.value === 'gold_qa') {
      message.warning('用例集已确认入库；黄金 QA 映射尚未启用，请稍后在知识库阶段映射')
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

function exportXlsx() {
  void downloadCaseSet('xlsx')
}
function exportXmind() {
  void downloadCaseSet('xmind')
}

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
    content: `确认废弃「${set.name}」？任务将置为 cancelled，该操作不可逆。`,
    positiveText: '确认废弃',
    negativeText: '取消',
    onPositiveClick: async () => {
      try {
        await api.cases.cancelSet(set.id, '用户在目录树右键废弃')
        set.status = 'cancelled'
        syncCaseSetTree(caseSets.value)
        message.info('已废弃用例集')
      } catch (err: any) {
        message.error(err.message || '废弃用例集失败')
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
    message.success('已重命名用例集')
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
          message.success('已创建目录')
        } catch (err: any) {
          message.error(err.message || '创建目录失败')
        }
      })
      break
    case 'rename':
      if (folder.id === ROOT_FOLDER_ID) {
        message.warning('主目录为系统挂载点，不可重命名')
        break
      }
      openPrompt('重命名目录', folder.name, async (val) => {
        try {
          const updated = await api.cases.updateFolder(folder.id, { name: val })
          folderRecords.value = folderRecords.value.map(item => item.id === folder.id ? updated : item)
          syncCaseSetTree(caseSets.value)
          message.success('已更新目录名')
        } catch (err: any) {
          message.error(err.message || '重命名目录失败')
        }
      })
      break
    case 'delete':
      if (folder.id === ROOT_FOLDER_ID) {
        message.warning('主目录为系统挂载点，不可删除')
        break
      }
      dialog.warning({
        title: '删除目录',
        content: `确认删除「${folder.name}」？目录必须为空。`,
        positiveText: '删除',
        negativeText: '取消',
        onPositiveClick: async () => {
          try {
            await api.cases.deleteFolder(folder.id)
            folderRecords.value = folderRecords.value.filter(item => item.id !== folder.id)
            syncCaseSetTree(caseSets.value)
            message.success('已删除目录')
          } catch (err: any) {
            message.error(err.message || '删除目录失败')
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
    if (applied > 0) message.success('AI 已生成补全候选，点击“保存修改”后生效')
    return
  }
  if (!row.precondition) row.precondition = '前置服务已启动，测试数据已插桩'
  if (!row.test_type) row.test_type = '自动化回归'
  hasUnsavedChanges.value = true
  message.success('AI 已补全前置条件与测试类型，点击“保存修改”后生效')
}

async function copyCaseJson(row: TestCase) {
  try {
    await navigator.clipboard.writeText(JSON.stringify(row, null, 2))
    message.success('已复制用例 JSON')
  } catch {
    message.error('复制失败：浏览器未授权剪贴板访问')
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
  message.info('已插入空白用例，点击“保存修改”后生效')
}

function duplicateCase(idx: number) {
  if (currentSet.value?.status === 'confirmed') return
  const src = cases.value[idx]
  if (!src) return
  const copy: TestCase = { ...src, id: `c-${Date.now()}`, name: `${src.name}（副本）`, mapped: false, pending: false }
  cases.value.splice(idx + 1, 0, copy)
  selectedCaseIds.value.push(copy.id)
  hasUnsavedChanges.value = true
  message.info('已创建用例副本，点击“保存修改”后生效')
}

function batchDeleteCases() {
  if (currentSet.value?.status === 'confirmed') return
  const ids = selectedCaseIds.value.filter(id => cases.value.some(item => item.id === id))
  if (!ids.length) return
  dialog.warning({
    title: '批量删除用例',
    content: `确认删除勾选的 ${ids.length} 条用例？删除后需点击“保存修改”才会落库。`,
    positiveText: '确认删除',
    negativeText: '取消',
    onPositiveClick: () => {
      const idSet = new Set(ids)
      cases.value = cases.value.filter(item => !idSet.has(item.id))
      selectedCaseIds.value = []
      hasUnsavedChanges.value = true
      message.info(`已删除 ${ids.length} 条用例，点击“保存修改”后生效`)
    },
  })
}

async function copyText(text: string, tip: string) {
  try {
    await navigator.clipboard.writeText(text)
    message.success(tip)
  } catch {
    message.error('复制失败：浏览器未授权剪贴板访问')
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
  if (action === 'ai') openAiGenWizard()
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
    message.success('已下载 Excel 模板')
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
  message.success(`已更新用例「${row.name}」，点击“保存修改”落库`)
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
    message.warning('字段 Key 需为小写字母开头的字母/数字/下划线组合')
    return
  }
  if (!name) {
    message.warning('请填写显示名称')
    return
  }
  const reserved = ['id', 'strategy', 'priority', 'module', 'name', 'expected', 'precondition', 'steps', 'test_type', 'mapped', 'pending', 'selected']
  if (reserved.includes(key) || customCols.value.some(c => c.key === key)) {
    message.warning(`字段 Key「${key}」已存在或为内置字段`)
    return
  }
  addingCol.value = true
  try {
    const nextCols = [...customCols.value, { key, name }]
    await api.cases.updateSet(currentSet.value.id, { column_schema: nextCols })
    customColsMap.value[currentSet.value.id] = nextCols
    showAddColModal.value = false
    message.success(`已添加扩展列「${name}」`)
  } catch (err: any) {
    message.error(err.message || '新增扩展列失败')
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
    message.info(`已移除扩展列 ${key}`)
  } catch (err: any) {
    message.error(err.message || '移除扩展列失败')
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
.cases-workbench {
  height: calc(100vh - var(--topbar-h) - 20px);
  min-height: 0;
  display: flex;
  flex-direction: column;
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
  color: var(--c-cases);
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
  background: var(--t-cases);
  color: var(--c-cases);
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

.case-icon {
  color: var(--c-cases);
  flex-shrink: 0;
}
.ft-file-name {
  flex: 1;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.status-micro-pill {
  font-size: 10px;
  padding: 1px 6px;
  border-radius: 4px;
  margin-left: auto;
  font-weight: 500;
}
.status-confirmed {
  background: #D1FAE5;
  color: #047857;
}
.status-pending {
  background: #FEF3C7;
  color: #B45309;
}
.status-cancelled {
  background: #F3F4F6;
  color: #6B7280;
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

.status-header-chip {
  font-size: 11px;
  font-weight: 600;
  padding: 1px 8px;
  border-radius: 999px;
}
.chip-confirmed {
  background: #D1FAE5;
  color: #047857;
}
.chip-countdown {
  background: #FEF3C7;
  color: #B45309;
}
.chip-cancelled {
  background: #F3F4F6;
  color: #6B7280;
}
.kind-chip {
  font-size: 11px;
  font-weight: 500;
  padding: 1px 8px;
  border-radius: 999px;
  border: 1px solid transparent;
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

/* ─── 策略分布全景概览栏 ─── */
.strategy-glance-bar {
  padding: 7px 20px;
  background: var(--bg-elevated);
  border-bottom: 1px solid var(--border-subtle);
  display: flex;
  align-items: center;
  gap: 12px;
  font-size: 12px;
}
.glance-strategy-left {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}
.glance-label {
  font-weight: 600;
  color: var(--text-secondary);
}
.strategy-pills-row {
  display: flex;
  align-items: center;
  gap: 6px;
  flex-wrap: wrap;
}
.strategy-pill {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 2px 8px;
  border-radius: 6px;
  font-size: 11px;
  font-weight: 500;
  cursor: pointer;
  transition: all 0.12s ease;
  border: 1px solid var(--border-subtle);
  background: var(--bg-main);
  color: var(--text-secondary);
}
.strategy-pill:hover {
  filter: brightness(0.96);
  transform: translateY(-1px);
}
.strategy-pill.active {
  box-shadow: 0 0 0 2px var(--accent-ai);
  font-weight: 700;
}
.strategy-pill.all-pill {
  background: var(--bg-main);
}
.strategy-pill.all-pill.active {
  background: var(--text-primary);
  color: var(--bg-main);
  border-color: var(--text-primary);
}

.st-positive { background: #D1FAE5; color: #047857; border-color: #A7F3D0; }
.st-negative { background: #FFE4E6; color: #E11D48; border-color: #FECDD3; }
.st-boundary { background: #FEF3C7; color: #D97706; border-color: #FDE68A; }
.st-equivalence { background: #E0E7FF; color: #4F46E5; border-color: #C7D2FE; }
.st-state { background: #EDE9FE; color: #7C3AED; border-color: #DDD6FE; }
.st-scenario { background: #CCFBF1; color: #0F766E; border-color: #99F6E4; }

.strategy-badge {
  display: inline-block;
  padding: 1px 7px;
  border-radius: 4px;
  font-size: 11px;
  font-weight: 600;
}
.strategy-badge.st-positive { background: #D1FAE5; color: #047857; }
.strategy-badge.st-negative { background: #FFE4E6; color: #E11D48; }
.strategy-badge.st-boundary { background: #FEF3C7; color: #D97706; }
.strategy-badge.st-equivalence { background: #E0E7FF; color: #4F46E5; }
.strategy-badge.st-state { background: #EDE9FE; color: #7C3AED; }
.strategy-badge.st-scenario { background: #CCFBF1; color: #0F766E; }

.glance-strategy-right {
  display: flex;
  align-items: center;
  gap: 10px;
}
.achievement-pill-case {
  background: #ECFDF5;
  border: 1px solid #A7F3D0;
  color: #047857;
  font-weight: 600;
  padding: 2px 8px;
  border-radius: 6px;
}
.adoption-rate-pill {
  color: var(--text-tertiary);
  font-size: 11.5px;
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
.cell-text.font-semibold {
  font-weight: 600;
}
.cell-text.font-medium {
  font-weight: 500;
}
.cell-text.placeholder {
  color: var(--accent-warning);
  font-style: italic;
}
.cell-text.empty {
  color: var(--text-tertiary);
}
.cell-text.tertiary-text {
  color: var(--text-secondary);
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

.cell-invalid {
  background: color-mix(in srgb, var(--accent-error) 4%, transparent);
  border-bottom-color: var(--accent-error) !important;
}

/* 优先级胶囊 */
.prio-pill {
  font-family: var(--font-mono);
  font-weight: 700;
  font-size: 11px;
  padding: 1px 6px;
  border-radius: 4px;
}
.prio-HX { background: #FEE2E2; color: #DC2626; }
.prio-FHX { background: #FEF3C7; color: #D97706; }
.prio-BJ { background: #E0E7FF; color: #4F46E5; }
.prio-YC { background: #FCE7F3; color: #C026D3; }
.prio-ZD { background: #EDE9FE; color: #7C3AED; }
.prio-BL { background: #D1FAE5; color: #059669; }

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

.empty-table-cell {
  padding: 48px 16px;
  text-align: center;
  color: var(--text-tertiary);
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
.dock-map-wrapper {
  display: flex;
  align-items: center;
  gap: 6px;
}
.dock-map-label {
  font-size: 11px;
  opacity: 0.75;
}
.dock-map-select {
  height: 28px;
  font-size: 11.5px;
  padding: 2px 22px 2px 8px;
  border-radius: 6px;
  background: rgba(255, 255, 255, 0.1);
  color: #fff;
  border-color: rgba(255, 255, 255, 0.2);
}
.dock-map-select option {
  color: var(--text-primary);
  background: var(--bg-main);
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
  color: var(--c-cases);
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

.ai-weights-grid {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 10px;
}
.weight-card {
  padding: 8px 10px;
  border-radius: 8px;
  background: var(--bg-elevated);
  border: 1px solid var(--border-subtle);
}
.weight-title {
  font-size: 12px;
  font-weight: 600;
  color: var(--text-secondary);
  margin-bottom: 4px;
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
  .btn-xs,
  .strategy-pill {
    transition: none;
  }
}

/* ─── 响应式 ─── */
@media (max-width: 900px) {
  .cases-workbench {
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
