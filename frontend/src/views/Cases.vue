<template>
  <div class="cases-workbench">
    <div class="ft-layout" :style="{ '--ft-w': treeWidth + 'px' }">
      <!-- 左侧：目录树侧边栏 -->
      <div class="ft-sidebar">
        <div class="ft-header">
          <div class="row-between mb8">
            <span style="font-weight: 600; font-size: 13px">用例集目录</span>
            <!-- C6/C14：对齐原型，「+ 新建集」主行为触发 AI 生成向导；空集创建保留下拉项 -->
            <n-dropdown trigger="click" :options="createSetMenuOptions" @select="handleCreateSetMenu">
              <button class="btn btn-secondary btn-sm" style="font-size: 11px">+ 新建集</button>
            </n-dropdown>
          </div>
          <input v-model="treeSearch" class="input" placeholder="搜索用例集..." style="height: 30px; font-size: 12px" />
        </div>

        <div class="ft-tree">
          <div v-for="folder in filteredFolders" :key="folder.id">
            <!-- C1：文件夹节点右键打开目录级上下文菜单 -->
            <div class="ft-node folder" @click="folder.open = !folder.open" @contextmenu.prevent.stop="onFolderContextMenu($event, folder.id)">
              <span class="ft-icon">{{ folder.open ? '▾' : '▸' }}</span>
              <span>📁 {{ folder.name }}</span>
              <span class="ft-badge">{{ folder.items.length }}</span>
            </div>

            <div v-if="folder.open" class="ft-folder-child">
              <!-- C1：用例集节点右键打开集级上下文菜单；点击切换带未保存守卫 -->
              <div
                v-for="item in folder.items"
                :key="item.id"
                class="ft-node"
                :class="{ active: activeSetId === item.id }"
                :title="`${item.name} · ${item.status === 'confirmed' ? '已入库' : item.status === 'cancelled' ? '已废弃' : '待确认'}`"
                @click="requestSelectCaseSet(item.id)"
                @contextmenu.prevent.stop="onSetContextMenu($event, item.id)"
              >
                <span class="ft-icon">📋</span>
                <span style="overflow: hidden; text-overflow: ellipsis; white-space: nowrap">{{ item.name }}</span>
                <span
                  class="badge"
                  :class="item.status === 'confirmed' ? 'badge-succeeded' : item.status === 'cancelled' ? 'badge-cancelled' : 'badge-awaiting_case_confirm'"
                  style="font-size: 10px; padding: 1px 5px; margin-left: auto"
                >
                  {{ item.status === 'confirmed' ? '已入库' : item.status === 'cancelled' ? '已废弃' : '待确认' }}
                </span>
              </div>
            </div>
          </div>
          <!-- 目录树空态 / 搜索无结果提示 -->
          <div v-if="!filteredFolders.length" class="tertiary" style="padding: 14px 12px; font-size: 12px; line-height: 1.7">
            {{ treeSearch.trim() ? `未找到匹配「${treeSearch.trim()}」的用例集` : '暂无用例集，点击上方「+ 新建集」开始' }}
          </div>
        </div>
        <!-- 目录树面板拖拽调宽手柄（200–520px，双击复位 290px，localStorage 持久化），对齐原型 ft-resizer -->
        <div
          class="ft-resizer"
          :class="{ on: treeResizing }"
          title="拖拽调整目录树宽度 · 双击复位"
          @mousedown="startTreeResize"
          @dblclick="resetTreeWidth"
        ></div>
      </div>

      <!-- 右侧：用例数据表格工作台 -->
      <div v-if="currentSet" class="workspace-main">
        <!-- 1. 顶部工具栏 -->
        <div class="ws-toolbar">
          <div class="row" style="gap: 8px; align-items: center">
            <span style="font-weight: 700; font-size: 15px">{{ currentSet.name }}</span>
            <span class="tag-soft">生成 <b class="num mono">{{ currentSet.generated_count }}</b> 条</span>
            <span class="tag-soft" style="color: var(--accent-warning); border-color: #FDE68A">
              {{ currentSet.status === 'confirmed' ? '✓ 已入库' : currentSet.status === 'cancelled' ? '已废弃' : expiresLabel(currentSet) }}
            </span>
            <span class="tag-soft" :style="modeTagStyle">{{ modeMappingLabel }}</span>
          </div>

          <div class="row" style="gap: 8px; align-items: center; margin-left: auto; flex-wrap: wrap; justify-content: flex-end">
            <button class="btn btn-secondary btn-sm" @click="addCase">+ 新增用例</button>
            <!-- C4：自定义扩展列入 -->
            <button class="btn btn-secondary btn-sm" @click="openAddColModal">+ 新增列</button>
            <button class="btn btn-ai btn-sm" @click="openAiGenWizard">✨ AI 生成用例集</button>
            <button class="btn btn-ai btn-sm" :disabled="aiFilling" @click="handleAiFillCase">{{ aiFilling ? '补全中…' : 'AI 补全断言' }}</button>
            <button class="btn btn-secondary btn-sm" :disabled="!hasUnsavedChanges || savingCases" title="快捷键 Ctrl/⌘ + S" @click="persistCases">
              {{ savingCases ? '保存中…' : '保存修改' }}
            </button>
            <button class="btn btn-secondary btn-sm" @click="openImportModal">导入 Excel</button>
            <button class="btn btn-secondary btn-sm" @click="exportXlsx">导出 xlsx</button>
            <button class="btn btn-secondary btn-sm" @click="exportXmind">导出 xmind</button>
            <button
              v-if="currentSet.status === 'generated'"
              class="btn btn-sign btn-sm"
              @click="confirmAllCases"
            >
              确认入库
            </button>
          </div>
        </div>

        <!-- 2. 策略分布与 AI 自检横幅 -->
        <div class="strategy-banner">
          <span class="tertiary" style="font-weight: 600">策略覆盖分布:</span>
          <div class="row wrap" style="gap: 6px">
            <span v-for="st in strategyCounts" :key="st.name" class="tag-soft" style="font-size: 11px">
              {{ st.name }} <b class="num mono">{{ st.count }}</b>
            </span>
          </div>
          <span class="grow"></span>
          <span v-if="currentSet.checks?.length" class="badge badge-failed" style="font-size: 11px">
            ⚠ 自检: {{ currentSet.checks.map(c => c.message).join('; ') }}
          </span>
          <span v-else class="st-ok small">✓ 策略自检通过</span>
        </div>

        <!-- 3. 用例表格数据网格 -->
        <div class="ws-grid-container">
          <table class="ds-table">
            <thead>
              <tr>
                <th style="width: 40px"><input v-model="allCasesChecked" type="checkbox" /></th>
                <th style="width: 75px">策略</th>
                <th style="width: 65px">级别</th>
                <th style="min-width: 90px">模块</th>
                <th style="min-width: 180px">用例名称 <i class="req" style="color: var(--accent-error)">*</i></th>
                <th style="min-width: 220px">预期结果 <i class="req" style="color: var(--accent-error)">*</i></th>
                <th style="min-width: 140px">前置条件</th>
                <!-- C4：自定义扩展列表头（.custom-col-th 样式见 base.css），✕ 删列 -->
                <th v-for="col in customCols" :key="col.key" class="custom-col-th" style="min-width: 110px">
                  {{ col.name }}
                  <button class="link-btn danger" style="font-size: 10px; padding: 0 2px" title="删除扩展列" @click.stop="removeCustomCol(col.key)">✕</button>
                </th>
                <th style="width: 90px">映射状态</th>
                <th style="width: 75px; text-align: right">操作</th>
              </tr>
            </thead>
            <tbody>
              <!-- C1：表格行右键打开行级上下文菜单；双击直达弹窗编辑 -->
              <tr
                v-for="(c, idx) in cases"
                :key="c.id"
                @contextmenu.prevent="onRowContextMenu($event, idx)"
                @dblclick="openCaseEditModal(idx)"
              >
                <td><input v-model="selectedCaseIds" type="checkbox" :value="c.id" /></td>
                <!-- C3：策略/级别行内可编辑，点击切换为下拉，选定或失焦后标记待保存 -->
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
                  <span v-else class="kind-tag" :class="getStrategyTagClass(c.strategy)">{{ c.strategy }}</span>
                </td>
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
                  <span v-else class="prio" :class="`prio-${c.priority}`">{{ c.priority }}</span>
                </td>
                <td class="cell-edit" @click="editCell(c, 'module')">
                  <input
                    v-if="editingCell?.row === c && editingCell?.field === 'module'"
                    v-model="c.module"
                    class="cell-input"
                    autofocus
                    @blur="finishEditing"
                    @keyup.enter="finishEditing"
                    @keyup.esc="cancelEditing"
                  />
                  <span v-else>{{ c.module }}</span>
                </td>
                <td class="cell-edit" @click="editCell(c, 'name')">
                  <input
                    v-if="editingCell?.row === c && editingCell?.field === 'name'"
                    v-model="c.name"
                    class="cell-input"
                    autofocus
                    @blur="finishEditing"
                    @keyup.enter="finishEditing"
                    @keyup.esc="cancelEditing"
                  />
                  <span v-else style="font-weight: 500">{{ c.name }}</span>
                </td>
                <td class="cell-edit" @click="editCell(c, 'expected')">
                  <input
                    v-if="editingCell?.row === c && editingCell?.field === 'expected'"
                    v-model="c.expected"
                    class="cell-input"
                    autofocus
                    @blur="finishEditing"
                    @keyup.enter="finishEditing"
                    @keyup.esc="cancelEditing"
                  />
                  <span v-else>{{ c.expected }}</span>
                </td>
                <td class="cell-edit" @click="editCell(c, 'precondition')">
                  <!-- 修复：前置条件编辑此前不标记待保存，导致修改无法落库 -->
                  <input
                    v-if="editingCell?.row === c && editingCell?.field === 'precondition'"
                    v-model="c.precondition"
                    class="cell-input"
                    autofocus
                    @blur="finishEditing"
                    @keyup.enter="finishEditing"
                    @keyup.esc="cancelEditing"
                  />
                  <span v-else class="small tertiary">{{ c.precondition || '无' }}</span>
                </td>
                <!-- C4：自定义扩展列单元格，行内即点即改 -->
                <td v-for="col in customCols" :key="col.key" class="cell-edit" @click="editExtraCell(c, col.key)">
                  <input
                    v-if="editingExtraCell?.row === c && editingExtraCell?.key === col.key"
                    :value="getCaseExtra(c, col.key)"
                    class="cell-input"
                    autofocus
                    @input="setCaseExtra(c, col.key, ($event.target as HTMLInputElement).value)"
                    @blur="finishExtraEditing"
                    @keyup.enter="finishExtraEditing"
                    @keyup.esc="cancelExtraEditing"
                  />
                  <span v-else class="small" :class="{ tertiary: !getCaseExtra(c, col.key) }">{{ getCaseExtra(c, col.key) || '—' }}</span>
                </td>
                <td>
                  <span v-if="c.mapped" class="badge badge-succeeded">✓ 已映射</span>
                  <span v-else class="badge badge-awaiting_case_confirm">待补全</span>
                </td>
                <!-- C2：恢复「编辑」弹窗入口（原型 cases.html:392），删除并入右键菜单 -->
                <td style="text-align: right">
                  <button class="link-btn" @click="openCaseEditModal(idx)">编辑</button>
                </td>
              </tr>
            </tbody>
          </table>
        </div>

        <!-- 4. 底部状态栏与批量映射 -->
        <div class="ws-status-bar">
          <span>已选 <b class="num mono">{{ selectedCaseIds.length }}</b> / {{ cases.length }} 条</span>
          <!-- 批量删除勾选用例（已确认集不可编辑，保存后落库） -->
          <button
            v-if="selectedCaseIds.length > 0 && currentSet.status !== 'confirmed'"
            class="link-btn danger"
            @click="batchDeleteCases"
          >批量删除</button>
          <span class="tag-soft" :style="modeTagStyle">{{ modeMappingLabel }}</span>
          <select v-model="mapTargetId" class="select" style="height: 28px; padding: 2px 24px 2px 8px; font-size: 12px" :disabled="mappingTargets.length === 0">
            <option value="">选择目标</option>
            <option v-for="target in mappingTargets" :key="target.id" :value="target.id">{{ target.name }}</option>
          </select>
          <button class="btn btn-secondary btn-sm" @click="handleBatchMap">批量执行映射</button>
          <span class="grow"></span>
          <span class="tertiary">采纳率: <b class="num mono">{{ adoptionRate }}%</b></span>
        </div>
      </div>

      <!-- 空态仍保留完整工作台骨架：工具栏 + 策略横幅 + 表头 + 状态栏，空表格内嵌引导操作 -->
      <div v-else class="workspace-main">
        <div class="ws-toolbar">
          <div class="row" style="gap: 8px; align-items: center">
            <span style="font-weight: 700; font-size: 15px">用例工作台</span>
            <span class="tag-soft" :style="modeTagStyle">{{ modeMappingLabel }}</span>
          </div>
          <div class="row" style="gap: 8px; align-items: center; margin-left: auto; flex-wrap: wrap; justify-content: flex-end">
            <button class="btn btn-ai btn-sm" @click="openAiGenWizard">✨ AI 生成用例集</button>
            <button class="btn btn-secondary btn-sm" @click="openImportModal">导入 Excel</button>
            <button class="btn btn-sign btn-sm" @click="handleCreateCaseSet()">+ 新建空用例集</button>
          </div>
        </div>
        <div class="strategy-banner">
          <span class="tertiary" style="font-weight: 600">策略覆盖分布:</span>
          <div class="row wrap" style="gap: 6px">
            <span v-for="st in STRATEGY_LIST" :key="st" class="tag-soft" style="font-size: 11px">{{ st }} <b class="num mono">0</b></span>
          </div>
          <span class="grow"></span>
          <span class="tertiary small">暂无用例集</span>
        </div>
        <div class="ws-grid-container">
          <table class="ds-table">
            <thead>
              <tr>
                <th style="width: 40px"><input type="checkbox" disabled /></th>
                <th style="width: 75px">策略</th>
                <th style="width: 65px">级别</th>
                <th style="min-width: 90px">模块</th>
                <th style="min-width: 180px">用例名称 <i class="req" style="color: var(--accent-error)">*</i></th>
                <th style="min-width: 220px">预期结果 <i class="req" style="color: var(--accent-error)">*</i></th>
                <th style="min-width: 140px">前置条件</th>
                <th style="width: 90px">映射状态</th>
                <th style="width: 75px; text-align: right">操作</th>
              </tr>
            </thead>
            <tbody>
              <tr>
                <td colspan="9" style="padding: 56px 16px; border-bottom: none">
                  <div style="display: flex; flex-direction: column; align-items: center; gap: 10px; color: var(--text-tertiary)">
                    <span style="font-size: 34px">📋</span>
                    <span style="font-size: 14px; font-weight: 600; color: var(--text-secondary)">暂无用例集</span>
                    <span class="small">粘贴 PRD / OpenAPI 文本由 AI 按六大策略生成候选用例，或先新建空集手工编写</span>
                    <div class="row" style="gap: 8px; margin-top: 6px">
                      <button class="btn btn-ai btn-sm" @click="openAiGenWizard">✨ AI 生成用例集</button>
                      <button class="btn btn-sign btn-sm" @click="handleCreateCaseSet()">+ 新建空用例集</button>
                    </div>
                  </div>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
        <div class="ws-status-bar">
          <span>已选 <b class="num mono">0</b> / 0 条</span>
          <span class="tertiary">尚未创建用例集</span>
          <span class="grow"></span>
        </div>
      </div>
    </div>

    <n-modal v-model:show="showCreateSetModal" preset="card" title="新建用例集" style="width: 440px; max-width: calc(100vw - 24px)">
      <div class="field">
        <label class="field-label">用例集名称 <span class="req">*</span></label>
        <n-input v-model:value="newSetName" placeholder="例如：支付模块回归用例" />
      </div>
      <template #footer>
        <div style="display: flex; justify-content: flex-end; gap: 8px">
          <n-button @click="showCreateSetModal = false">取消</n-button>
          <n-button type="primary" :loading="creatingSet" @click="createCaseSet">创建</n-button>
        </div>
      </template>
    </n-modal>

    <ImportCasesExcelModal
      v-model:show="showImportModal"
      :current-set="currentSet"
      :folder-id="importFolderId"
      @imported="onExcelImported"
    />

    <!-- C2：用例结构化编辑弹窗（原型 cases.html:537-601） -->
    <n-modal v-model:show="showEditCaseModal" preset="card" :title="`详细编辑用例 · ${editDraft.id || '新用例'}`" style="width: 640px; max-width: calc(100vw - 24px)">
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
          <label class="field-label">用例名称 / 测试目的 <span class="req">*</span></label>
          <n-input v-model:value="editDraft.name" placeholder="一句话描述被测目标" />
        </div>
      </div>
      <div class="field">
        <label class="field-label">预期结果 / 断言标准 (Expected Result) <span class="req">*</span></label>
        <n-input v-model:value="editDraft.expected" type="textarea" :autosize="{ minRows: 3, maxRows: 6 }" placeholder="可校验的预期行为或断言" />
      </div>
      <div class="field">
        <label class="field-label">前置条件</label>
        <n-input v-model:value="editDraft.precondition" placeholder="可选，如 账号状态正常" />
      </div>
      <!-- 自定义扩展属性区：与表格自定义列一一对应 -->
      <template v-if="customCols.length">
        <div class="rail-label mt8">自定义扩展属性</div>
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
          <n-button type="primary" @click="saveCaseEdit">保存用例</n-button>
        </div>
      </template>
    </n-modal>

    <!-- C4：新增自定义扩展列弹窗（原型 cases.html:913-940） -->
    <n-modal v-model:show="showAddColModal" preset="card" title="新增用例自定义字段 (Custom Field)" style="width: 440px; max-width: calc(100vw - 24px)">
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

    <!-- 通用单输入弹窗：重命名用例集 / 新建子目录 / 重命名目录共用 -->
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

    <!-- C5：AI 生成用例集两步向导（原型 cases.html:604-910） -->
    <n-modal v-model:show="showAiGenModal" preset="card" title="✨ AI 智能生成测试用例集" style="width: 760px; max-width: calc(100vw - 24px)" :mask-closable="false">
      <!-- Step 1：配置与需求输入 -->
      <div v-show="aiStep === 'config'">
        <div class="field">
          <label class="field-label">预设 PRD 业务需求模板</label>
          <n-select v-model:value="aiPresetIdx" :options="aiPresetOptions" />
        </div>
        <div class="field">
          <label class="field-label">PRD 业务需求描述 / 接口定义 (Source Material) <span class="req">*</span></label>
          <n-input v-model:value="aiSource" type="textarea" :autosize="{ minRows: 4, maxRows: 8 }" placeholder="支持粘贴 Markdown 文本、接口列表或业务规则描述" />
        </div>

        <div class="rail-label mt8">六大测试策略分布配比与规模控制</div>
        <div class="ai-weights-grid">
          <div v-for="s in STRATEGY_LIST" :key="s" class="field" style="margin-bottom: 0">
            <label class="field-label">{{ s }} {{ aiWeights[s] }}%</label>
            <n-input-number v-model:value="aiWeights[s]" :min="0" :max="100" size="small" />
          </div>
        </div>

        <div class="form-row">
          <div class="field">
            <label class="field-label">目标生成规模 (<b class="num">{{ aiCount }}</b> 条)</label>
            <n-slider v-model:value="aiCount" :min="6" :max="45" :step="1" style="margin-top: 8px" />
            <!-- 防爆提示：规模超过 30 时显式预警 -->
            <span v-if="aiCount > 30" class="field-hint" style="color: var(--accent-warning)">⚠ 大规模生成可能超时或触发防爆流保护，单次上限 45 条</span>
            <span v-else class="field-hint">防爆流保护：单次生成上限 45 条</span>
          </div>
          <div class="field">
            <label class="field-label">用例结构属性生成</label>
            <div class="row wrap" style="gap: 12px; font-size: 12px; margin-top: 6px">
              <n-checkbox v-model:checked="aiStruct.precondition">前置条件</n-checkbox>
              <n-checkbox v-model:checked="aiStruct.steps">测试执行步骤</n-checkbox>
              <n-checkbox v-model:checked="aiStruct.expected">预期断言</n-checkbox>
              <n-checkbox v-model:checked="aiStruct.autoPriority">P0-P3 自动定级</n-checkbox>
            </div>
          </div>
        </div>
      </div>

      <!-- Step 2：候选用例策略分布与交互式预览 -->
      <div v-show="aiStep === 'preview'">
        <div class="strategy-banner mb8" style="border-radius: 8px; border: 1px solid var(--border-subtle)">
          <span class="tertiary" style="font-weight: 600">策略分布:</span>
          <div class="row wrap" style="gap: 6px">
            <span v-for="st in aiStrategyCounts" :key="st.name" class="tag-soft" style="font-size: 11px">
              {{ st.name }} <b class="num mono">{{ st.count }}</b>
            </span>
          </div>
          <span class="grow"></span>
          <span class="st-ok small">✓ 6 大策略覆盖</span>
        </div>
        <div class="row-between mb8">
          <span style="font-weight: 600; font-size: 13px">候选用例列表（已生成 <b class="num">{{ aiCandidates.length }}</b> 条，可点击修改）</span>
          <button class="link-btn" @click="toggleAllCandidates(!allCandidatesChecked)">全选 / 全不选</button>
        </div>
        <div style="max-height: 360px; overflow-y: auto; border: 1px solid var(--border-subtle); border-radius: 8px">
          <table class="ds-table">
            <thead>
              <tr>
                <th style="width: 36px"><input v-model="allCandidatesChecked" type="checkbox" /></th>
                <th style="width: 65px">策略</th>
                <th style="width: 60px">级别</th>
                <th style="width: 90px">模块</th>
                <th>用例名称</th>
                <th>预期断言结果</th>
                <th style="width: 65px">操作</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="(cand, ci) in aiCandidates" :key="cand.id">
                <td><input v-model="cand.selected" type="checkbox" /></td>
                <td><span class="kind-tag" :class="getStrategyTagClass(cand.strategy)">{{ cand.strategy }}</span></td>
                <td><span class="prio" :class="`prio-${cand.priority}`">{{ cand.priority }}</span></td>
                <td><input v-model="cand.module" class="input" style="font-size: 12px; padding: 3px 6px" /></td>
                <td><input v-model="cand.name" class="input" style="font-size: 12px; padding: 3px 6px" /></td>
                <td><input v-model="cand.expected" class="input" style="font-size: 12px; padding: 3px 6px" /></td>
                <td><button class="link-btn danger" style="font-size: 11px" @click="removeCandidate(ci)">剔除</button></td>
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

    <!-- C1：三组右键上下文菜单（NDropdown 手动定位，自带弹出过渡） -->
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

// 自定义扩展列定义（契约 column_schema 的 key/name 子集）
interface CustomCol {
  key: string
  name: string
}

// AI 候选用例：在 TestCase 契约字段上叠加向导勾选态
type AiCandidate = TestCase & { selected: boolean }

// 契约冻结的 6 类用例策略与 P0-P3 优先级档位（以 types.ts TestCase 枚举为准）
const STRATEGY_LIST: Array<TestCase['strategy']> = ['正向', '反向', '边界', '等价', '状态', '场景']
const PRIORITY_LIST: Array<TestCase['priority']> = ['P0', 'P1', 'P2', 'P3']
const strategyOptions = STRATEGY_LIST.map(s => ({ label: s, value: s }))
const priorityOptions = PRIORITY_LIST.map(p => ({ label: p, value: p }))

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
const hasUnsavedChanges = ref(false)
// original 供 Escape 取消时还原（对齐原型单元格编辑交互）
const editingCell = ref<{ row: TestCase; field: keyof TestCase; original: string } | null>(null)
const showCreateSetModal = ref(false)
const showImportModal = ref(false)
const importFolderId = ref('')
const newSetName = ref('')
const creatingSet = ref(false)
// 记录触发「新建空集」的目录 id（空串为主目录），用于创建成功后挂到对应本地子目录
const createTargetFolderId = ref('')
const generatingCases = ref(false)
const ROOT_FOLDER_ID = 'case-sets'
type TreeFolder = { id: string; name: string; open: boolean; items: Array<{ id: string; name: string; status: CaseSet['status'] }> }
const folders = ref<TreeFolder[]>([{ id: ROOT_FOLDER_ID, name: '用例集', open: true, items: [] }])
const folderRecords = ref<CaseFolder[]>([])

// ─── 目录树面板自由伸缩（对齐原型 ft-resizer：拖拽 200–520px，双击复位 290px，localStorage 持久化） ───
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

// C4：每个用例集的自定义扩展列（契约 column_schema），由 getSet 详情加载、updateSet 持久化
const customColsMap = ref<Record<string, CustomCol[]>>({})
// 自定义列单元格行内编辑态（独立于内置字段的 editingCell）；original 供 Escape 还原
const editingExtraCell = ref<{ row: TestCase; key: string; original: string } | null>(null)

// C2：结构化编辑弹窗状态；草稿在打开时从行数据拷贝，保存时才写回表格
const showEditCaseModal = ref(false)
const editCaseIdx = ref(-1)
const editDraft = ref<TestCase & Record<string, unknown>>({ id: '', strategy: '正向', priority: 'P1', module: '', name: '', expected: '', precondition: '' })

// C4：新增扩展列弹窗状态
const showAddColModal = ref(false)
const newColKey = ref('')
const newColName = ref('')
const addingCol = ref(false)

// 通用单输入弹窗状态（重命名用例集 / 新建子目录 / 重命名目录共用）
const promptState = reactive({ show: false, title: '', value: '', placeholder: '' })
// 弹窗确认回调以普通变量保存，避免响应式包装丢失函数引用
let promptSubmit: ((val: string) => void | Promise<void>) | null = null

// C1：三组右键上下文菜单状态（NDropdown 手动定位坐标）
const ctxSet = reactive({ show: false, x: 0, y: 0, setId: '' })
const ctxFolder = reactive({ show: false, x: 0, y: 0, folderId: '' })
const ctxRow = reactive({ show: false, x: 0, y: 0, idx: -1 })

// ─── C5：AI 生成用例集两步向导状态 ───
// PRD 预设模板（对齐原型 cases.html:609-613）
const PRD_PRESETS = [
  { name: 'PRD-聚合收银台与快捷退款', text: '收银台支持余额、银行卡快捷支付与企业对公转账。单笔提现上限 5 万元，单日上限 20 万元。连续输错密码 5 次锁定 2 小时，人脸解锁。退款 1-3 工作日原路退回。' },
  { name: 'PRD-用户中心与双因子认证 (2FA)', text: '支持账密、短信验证码及扫码登录。登录失败 3 次出图形验证码，失败 5 次锁定 15 分钟。敏感操作需二次验证短信验证码。' },
  { name: 'PRD-营销中心满减优惠券结算', text: '支持满减券、折扣券及免邮券。一笔订单仅能使用一张主券。发生部分退款时按商品实付比例分摊券金额。' },
]
const showAiGenModal = ref(false)
const aiStep = ref<'config' | 'preview'>('config')
const aiPresetIdx = ref(0)
const aiSource = ref(PRD_PRESETS[0].text)
// 六大策略配比（契约默认值：正向40 / 反向25 / 边界15 / 等价10 / 状态5 / 场景5）
const aiWeights = reactive<Record<TestCase['strategy'], number>>({ 正向: 40, 反向: 25, 边界: 15, 等价: 10, 状态: 5, 场景: 5 })
const aiCount = ref(12)
// 结构属性生成开关：前置条件 / 测试步骤 / 预期断言 / P0-P3 自动定级
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
  // 策略分布统计覆盖契约全部 6 类策略（含「等价」）。
  return STRATEGY_LIST.map(strategy => ({ name: strategy, count: cases.value.filter(item => item.strategy === strategy).length }))
})
// 采纳率对齐原型语义：勾选采纳数 / 总条数（勾选 = 采纳，原型 cases.html 以非 pending 计）
const adoptionRate = computed(() => Math.round((selectedCaseIds.value.length / (cases.value.length || 1)) * 100))
// 映射目标由全局业务模式固定：大模型用例写入基准数据集，RAG 用例写入黄金 QA。
const mapTarget = computed<'dataset' | 'gold_qa'>(() => modeStore.mode === 'rag' ? 'gold_qa' : 'dataset')
const modeMappingLabel = computed(() => modeStore.mode === 'rag' ? '映射至黄金 QA' : '映射至基准数据集')
const modeTagStyle = computed(() => ({
  color: modeStore.mode === 'rag' ? 'var(--c-kb)' : 'var(--c-datasets)',
  borderColor: modeStore.mode === 'rag' ? 'var(--t-kb)' : 'var(--t-datasets)',
}))

// 当前用例集的自定义扩展列
const customCols = computed<CustomCol[]>(() => (currentSet.value ? customColsMap.value[currentSet.value.id] ?? [] : []))

// 主表全选/全不选（原型 chk-all-cases）
const allCasesChecked = computed({
  get: () => cases.value.length > 0 && selectedCaseIds.value.length === cases.value.length,
  set: (val: boolean) => { selectedCaseIds.value = val ? cases.value.map(c => c.id) : [] },
})

// C6/C14：「+ 新建集」入口选项——主行为 AI 生成向导，空集创建保留下拉
const createSetMenuOptions: DropdownOption[] = [
  { label: '✨ AI 生成用例集', key: 'ai' },
  { label: '导入 Excel 用例', key: 'import' },
  { label: '下载 Excel 模板', key: 'template' },
  { label: '新建空用例集', key: 'empty' },
]

// C1：用例集节点右键菜单项（确认入库仅对待确认集展示；补充复制 ID 与 xmind 导出）
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

// C1：文件夹节点右键菜单项（目录结构为前端本地组织）
const ctxFolderOptions: DropdownOption[] = [
  { label: '📋 在此目录下新建用例集', key: 'new-set' },
  { label: '📁 新建子目录', key: 'new-folder' },
  { label: '⤴ 导入 Excel 到此目录', key: 'import' },
  { type: 'divider', key: 'd1' },
  { label: '✏ 重命名目录', key: 'rename' },
  { label: '🗑 删除目录', key: 'delete', props: { style: 'color: var(--accent-error)' } },
]

// C1：表格行右键菜单项（勾选态随当前行动态切换；已确认集隐藏编辑类操作）
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

// ─── C5：向导派生状态 ───
const aiPresetOptions = PRD_PRESETS.map((p, i) => ({ label: p.name, value: i }))
// 策略配比合计（用于校验与按比例折算条数）
const aiWeightTotal = computed(() => STRATEGY_LIST.reduce((sum, s) => sum + (Number(aiWeights[s]) || 0), 0))
const aiSelectedCount = computed(() => aiCandidates.value.filter(c => c.selected).length)
const aiStrategyCounts = computed(() => STRATEGY_LIST.map(s => ({ name: s, count: aiCandidates.value.filter(c => c.strategy === s).length })))
// 候选表全选/全不选
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

// 目录树以服务端 folder_id 为准：根目录挂未分组集，其余按接口目录分组。
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

async function moveTreeItemToFolder(setId: string, folderId: string) {
  const folder = folders.value.find(f => f.id === folderId)
  const set = caseSets.value.find(s => s.id === setId)
  if (!folder || !set) return
  try {
    const updated = await api.cases.updateSet(setId, { folder_id: persistFolderId(folderId) })
    const index = caseSets.value.findIndex(item => item.id === setId)
    if (index !== -1) caseSets.value[index] = { ...caseSets.value[index], ...updated }
    syncCaseSetTree(caseSets.value)
  } catch (err: any) {
    message.error(err.message || '移动用例集失败')
  }
}

// 归一化契约 column_schema（[{key,name,type?,sort_order?}]），过滤缺 key 的脏数据
function normalizeColumnSchema(schema: unknown): CustomCol[] {
  if (!Array.isArray(schema)) return []
  return schema
    .filter((c: any) => c && typeof c.key === 'string' && c.key)
    .map((c: any) => ({ key: String(c.key), name: String(c.name || c.key) }))
}

// 自定义扩展字段读写：扩展键不在 TestCase 契约字段内，以宽松索引访问
function getCaseExtra(row: TestCase, key: string): string {
  return String((row as unknown as Record<string, unknown>)[key] ?? '')
}
function setCaseExtra(row: TestCase, key: string, val: string) {
  ;(row as unknown as Record<string, unknown>)[key] = val
}

// C4：自定义列单元格进入/结束行内编辑（已确认集不可编辑）
function editExtraCell(row: TestCase, key: string) {
  if (currentSet.value?.status === 'confirmed') return
  editingExtraCell.value = { row, key, original: getCaseExtra(row, key) }
}
function finishExtraEditing() {
  editingExtraCell.value = null
  hasUnsavedChanges.value = true
}
function cancelExtraEditing() {
  // Escape 放弃本次扩展列编辑：还原原始值且不标记待保存。
  const cell = editingExtraCell.value
  if (cell) setCaseExtra(cell.row, cell.key, cell.original)
  editingExtraCell.value = null
}

function editCell(row: TestCase, field: keyof TestCase) {
  // 已确认用例集不可编辑，浏览器侧提前阻止无效编辑操作。
  if (currentSet.value?.status === 'confirmed') return
  editingCell.value = { row, field, original: String(row[field] ?? '') }
}

function finishEditing() {
  // 失焦后只标记待保存，不在浏览器中假装已持久化。
  editingCell.value = null
  hasUnsavedChanges.value = true
}

function cancelEditing() {
  // Escape 放弃本次编辑：还原原始值且不标记待保存。
  const cell = editingCell.value
  if (cell) {
    ;(cell.row as unknown as Record<string, unknown>)[cell.field] = cell.original
  }
  editingCell.value = null
}

// 切换用例集时拉取详情与具体用例，不复用上一套的本地编辑内容。
async function selectCaseSet(id: string) {
  activeSetId.value = id
  try {
    const detail = await api.cases.getSet(id)
    const index = caseSets.value.findIndex(item => item.id === id)
    if (index !== -1) caseSets.value[index] = { ...caseSets.value[index], ...detail }
    cases.value = normalizeLoadedCases(detail.cases || [])
    // C4：从用例集详情读取契约 column_schema 作为自定义扩展列
    customColsMap.value[id] = normalizeColumnSchema((detail as CaseSet & Record<string, unknown>).column_schema)
    selectedCaseIds.value = cases.value.filter(item => item.selected || !item.pending).map(item => item.id)
    hasUnsavedChanges.value = false
  } catch (err: any) {
    cases.value = []
    selectedCaseIds.value = []
    message.error(err.message || '加载用例集详情失败')
  }
}

// 未保存守卫：切换用例集前若有未提交编辑，先询问保存/放弃/取消，防止误丢本地修改
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
  // 将既定六类策略映射到现有视觉令牌，「等价」与「场景」共用默认色。
  switch (strategy) {
    case '正向': return 'kind-testcase'
    case '反向': return 'kind-stress'
    case '边界': return 'kind-profiles'
    case '状态': return 'kind-benchmark'
    default: return 'kind-rag'
  }
}

function addCase() {
  // 新增空白用例，填写后需通过保存按钮提交。
  if (!currentSet.value || currentSet.value.status === 'confirmed') return
  const item: TestCase = {
    id: `c-${Date.now()}`,
    strategy: '正向',
    priority: 'P1',
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
  // 删除在保存前仅影响本地编辑态，避免误删服务端快照。
  if (currentSet.value?.status === 'confirmed') return
  const [removed] = cases.value.splice(index, 1)
  if (removed) selectedCaseIds.value = selectedCaseIds.value.filter(id => id !== removed.id)
  hasUnsavedChanges.value = true
  message.info('已删除用例，点击“保存修改”后生效')
}

// 保存全部编辑用例，已确认用例集的不可修改规则由后端作最终校验。
async function persistCases(): Promise<boolean> {
  if (!currentSet.value || savingCases.value) return false
  savingCases.value = true
  try {
    const saved = await api.cases.saveCases(currentSet.value.id, cases.value)
    cases.value = saved
    const set = caseSets.value.find(item => item.id === currentSet.value!.id)
    if (set) set.generated_count = saved.length
    hasUnsavedChanges.value = false
    message.success('用例修改已保存')
    return true
  } catch (err: any) {
    message.error(err.message || '保存用例失败')
    return false
  } finally {
    savingCases.value = false
  }
}

function handleCreateCaseSet(folderId = '') {
  // 记录触发创建的目录（空串为主目录），每次打开新建弹窗清空上一次未提交的名称。
  createTargetFolderId.value = folderId
  newSetName.value = ''
  showCreateSetModal.value = true
}

// 新建空用例集只在接口成功后更新目录树，避免“创建成功”假象。
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

// 打开 AI 生成两步向导并重置到配置步（原型：顶部「+ 新建集」与工具栏按钮均触发此弹窗）
function openAiGenWizard() {
  aiStep.value = 'config'
  aiPresetIdx.value = 0
  aiSource.value = PRD_PRESETS[0].text
  aiCandidates.value = []
  showAiGenModal.value = true
}

// 切换 PRD 预设模板时同步填充需求描述文本
watch(aiPresetIdx, (idx) => {
  aiSource.value = PRD_PRESETS[idx]?.text || ''
})

// 各策略本地候选文案模板池（mock 模式或接口无候选返回时的浏览器侧演示推导）
const STRATEGY_CASE_HINTS: Record<TestCase['strategy'], { name: string; expected: string }> = {
  正向: { name: '主链路正常流程验证', expected: '业务处理成功并返回预期结果' },
  反向: { name: '非法输入与异常操作拦截', expected: '系统拒绝并返回明确错误提示' },
  边界: { name: '临界值与极限条件校验', expected: '按限额/边界规则正确处理' },
  等价: { name: '等价类代表性输入覆盖', expected: '同类输入得到一致处理结果' },
  状态: { name: '状态机迁移与幂等验证', expected: '状态流转正确且重复请求幂等' },
  场景: { name: '端到端业务场景串联', expected: '全链路最终状态一致' },
}
const MODULE_POOL = ['收银台', '退款中心', '通用']

// 本地按配比推导候选用例：最大余数法分配各策略条数，保证总数等于目标规模
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
        // 自动定级开启时按序号梯度分配 P0/P1/P2，否则统一 P2
        priority: aiStruct.autoPriority ? (seq <= Math.ceil(count * 0.25) ? 'P0' : seq <= Math.ceil(count * 0.7) ? 'P1' : 'P2') : 'P2',
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

// Step1 → Step2：生成候选用例。live 模式调用契约 POST /api/case-sets/ai-generate（仅返回候选，不创建用例集）；
// mock 模式本地按配比生成演示候选。
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
      // 归一化接口候选字段，兼容契约外的命名差异
      items = raw.map((item, index) => ({
        ...item,
        id: item.id || `c-ai-${Date.now()}-${index + 1}`,
        strategy: item.strategy || '正向',
        priority: item.priority || 'P2',
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

// 剔除单条候选用例
function removeCandidate(idx: number) {
  aiCandidates.value.splice(idx, 1)
}

// 候选表「全选 / 全不选」开关
function toggleAllCandidates(checked: boolean) {
  aiCandidates.value.forEach(c => { c.selected = checked })
}

// 采纳候选：按契约 POST /api/case-sets → PUT /api/case-sets/{id}/cases 两步落库，任一步失败均不展示创建成功
async function commitAiCaseSet() {
  const selected = aiCandidates.value.filter(c => c.selected)
  if (!selected.length) return
  committingAi.value = true
  try {
    const presetName = PRD_PRESETS[aiPresetIdx.value]?.name || 'AI 生成'
    const created = await api.cases.createSet({ name: `AI-${presetName}`.slice(0, 30) })
    // 剥离向导勾选态，仅提交契约用例字段与扩展属性
    const payload: TestCase[] = selected.map(({ selected: _sel, ...rest }) => rest)
    try {
      await api.cases.saveCases(created.id, payload)
    } catch (saveErr) {
      // 用例落库失败时回滚刚创建的空集，避免服务端残留孤儿用例集
      try {
        await api.cases.cancelSet(created.id, '用例写入失败，自动回滚')
      } catch {}
      throw saveErr
    }
    // 本地先行展示条数，selectCaseSet 会以服务端详情为准
    created.generated_count = payload.length
    caseSets.value.unshift(created)
    syncCaseSetTree(caseSets.value)
    showAiGenModal.value = false
    await selectCaseSet(created.id)
    message.success(`已创建用例集「${created.name}」（${selected.length} 条用例，72h 内待确认入库）`)
  } catch (err: any) {
    message.error(err.message || '创建用例集失败')
  } finally {
    committingAi.value = false
  }
}

// ─── C5 行级 AI 补全（契约 POST /api/case-sets/{id}/ai-fill，返回未落库候选）───
const aiFilling = ref(false)

// 将补全候选应用到本地行（仅填充候选提供的字段），待“保存修改”统一落库。
function applyFillCandidates(candidates: Array<Partial<TestCase> & { id: string }>): number {
  let applied = 0
  candidates.forEach(candidate => {
    const row = cases.value.find(item => item.id === candidate.id)
    if (!row) return
    const target = row as TestCase & Record<string, unknown>
    Object.entries(candidate).forEach(([key, value]) => {
      if (key === 'id' || value == null) return
      // 固定字段只补空值，扩展列按 key 直接覆盖空值
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

/** 调契约 ai-fill 获取候选；限用例集与选中行校验前置完成。 */
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

// 「AI 补全断言」批量入口：对勾选行发起行级补全，候选由“保存修改”落库。
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

// 确认前先保存未提交编辑，再用实际映射目标完成确认入库。
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

// 批量映射严格提交选中用例与目标 ID，不再把全部本地行标记为已映射。
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

// 拉取当前映射类型的实际可选目标，防止使用原型中写死的目标标识。
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

// 服务端负责生成规范导出文件，页面只负责下载二进制结果；默认导出当前选中集，右键菜单可指定任意集。
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
  // 触发服务端 Excel 导出。
  void downloadCaseSet('xlsx')
}

function exportXmind() {
  // 触发服务端脑图导出。
  void downloadCaseSet('xmind')
}

// ─── C1：右键上下文菜单处理 ───
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

// 废弃用例集：Dialog 二次确认后调用 cancelSet（契约 POST /api/case-sets/{id}/cancel）
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

// 重命名用例集：契约 PUT /api/case-sets/{id} 更新 name
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

// 用例集右键菜单分发：确认入库/批量映射复用主工作台流程（先带守卫切到该集，由现有函数校验映射目标）
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

// 文件夹右键菜单分发：目录结构为前端本地组织（mock 模式允许本地修改）
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

// 表格行右键菜单分发
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

// 勾选/取消勾选单条用例（勾选 = 采纳，与原型 case-chk 语义一致）
function toggleCaseChecked(row: TestCase) {
  const i = selectedCaseIds.value.indexOf(row.id)
  if (i >= 0) selectedCaseIds.value.splice(i, 1)
  else selectedCaseIds.value.push(row.id)
}

// AI 补全单条用例属性：行级 ai-fill 契约（live）/ 本地候选（mock），均由「保存修改」落库
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

// 复制单条用例 JSON 到剪贴板，便于跨集搬运与排查
async function copyCaseJson(row: TestCase) {
  try {
    await navigator.clipboard.writeText(JSON.stringify(row, null, 2))
    message.success('已复制用例 JSON')
  } catch {
    message.error('复制失败：浏览器未授权剪贴板访问')
  }
}

// 在指定位置插入空白用例，继承相邻行模块便于连续编写；保存后才落库
function insertCaseAt(at: number) {
  if (currentSet.value?.status === 'confirmed') return
  const neighbor = cases.value[Math.min(at, cases.value.length - 1)]
  const item: TestCase = {
    id: `c-${Date.now()}`,
    strategy: '正向',
    priority: 'P1',
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

// 复制当前行创建副本（扩展属性一并拷贝），保存后才落库
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

// 批量删除勾选用例：Dialog 确认后仅影响本地编辑态，保存后落库
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

// 通用剪贴板复制（用例集 ID 等短文本场景）
async function copyText(text: string, tip: string) {
  try {
    await navigator.clipboard.writeText(text)
    message.success(tip)
  } catch {
    message.error('复制失败：浏览器未授权剪贴板访问')
  }
}

// ─── 通用单输入弹窗（重命名 / 新建目录等轻量输入场景）───
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

// C6/C14：「+ 新建集」下拉分发——AI 生成向导为原型主行为，空集创建保留
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

// ─── C2：用例结构化编辑弹窗 ───
function openCaseEditModal(idx: number) {
  const row = cases.value[idx]
  if (!row) return
  // 双击/右键进入弹窗前退出进行中的行内编辑，避免状态叠加
  editingCell.value = null
  editingExtraCell.value = null
  editCaseIdx.value = idx
  editDraft.value = { ...row }
  showEditCaseModal.value = true
}

// 保存弹窗编辑：仅写回本地表格并标记待保存，持久化仍走「保存修改」（C12 显式保存不回退）
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

// ─── C4：自定义扩展列管理 ───
function openAddColModal() {
  if (!currentSet.value) return
  newColKey.value = ''
  newColName.value = ''
  showAddColModal.value = true
}

// 新增自定义列：本地生效 + 通过 updateSet 持久化 column_schema（契约 PUT /api/case-sets/{id}）
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
  // 内置契约字段与已有扩展列均不允许重名
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

// 删除自定义列：同步持久化 column_schema；已填写的扩展数据仍随用例保存携带
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

// Ctrl/⌘+S 快捷保存：仅在有未保存修改且当前集可编辑时拦截默认行为
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

// 模式变化后强制清空原目标，并只加载当前业务链路允许映射的资产。
watch(() => modeStore.mode, () => {
  void loadMappingTargets()
})
</script>

<style scoped>
.cases-workbench {
  height: calc(100vh - var(--topbar-h) - 20px);
}
.ft-layout {
  display: grid;
  grid-template-columns: var(--ft-w, 290px) minmax(0, 1fr);
  height: 100%;
  min-width: 0;
  background: var(--bg-main);
  border-radius: 14px;
  overflow: hidden;
  border: 1px solid var(--border-subtle);
}
.ft-sidebar {
  border-right: 1px solid var(--border-subtle);
  background: var(--bg-elevated);
  display: flex;
  flex-direction: column;
  height: 100%;
  position: relative;
}
/* 目录树面板拖拽调宽手柄（对齐原型 ft-resizer） */
.ft-resizer {
  position: absolute;
  top: 0;
  right: -3px;
  width: 6px;
  height: 100%;
  cursor: col-resize;
  z-index: 5;
}
.ft-resizer:hover,
.ft-resizer.on {
  background: color-mix(in srgb, var(--accent-ai) 35%, transparent);
}
.ft-header {
  padding: 12px 14px;
  border-bottom: 1px solid var(--border-subtle);
}
.ft-tree {
  flex: 1;
  overflow-y: auto;
  padding: 10px 8px;
}
.ft-node {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 7px 10px;
  border-radius: 8px;
  font-size: 13px;
  cursor: pointer;
  transition: all 0.12s ease;
}
.ft-node:hover {
  background: rgba(17, 24, 39, 0.04);
}
.ft-node.active {
  background: color-mix(in srgb, var(--accent-ai) 12%, var(--bg-main));
  color: var(--accent-ai);
  font-weight: 600;
}
.ft-node.folder {
  font-weight: 600;
  color: var(--text-secondary);
}
.ft-folder-child {
  padding-left: 14px;
  display: flex;
  flex-direction: column;
  gap: 2px;
}
.ft-icon {
  width: 16px;
  height: 16px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  flex: 0 0 16px;
}
.ft-badge {
  margin-left: auto;
  font-family: var(--font-mono);
  font-size: 11px;
  color: var(--text-tertiary);
}
.workspace-main {
  display: flex;
  flex-direction: column;
  height: 100%;
  min-width: 0;
  min-height: 0;
  background: var(--bg-main);
}
.ws-toolbar {
  padding: 10px 16px;
  border-bottom: 1px solid var(--border-subtle);
  display: flex;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
}
.strategy-banner {
  padding: 8px 16px;
  background: color-mix(in srgb, var(--accent-ai) 4%, var(--bg-main));
  border-bottom: 1px solid var(--border-subtle);
  display: flex;
  align-items: center;
  gap: 16px;
  font-size: 12.5px;
}
.ws-grid-container {
  flex: 1;
  min-width: 0;
  overflow: auto;
}
.ws-status-bar {
  padding: 8px 16px;
  border-top: 1px solid var(--border-subtle);
  display: flex;
  align-items: center;
  gap: 16px;
  font-family: var(--font-mono);
  font-size: 12px;
  background: var(--bg-elevated);
  color: var(--text-secondary);
}
.prio {
  font-family: var(--font-mono);
  font-weight: 700;
  font-size: 11px;
  padding: 1px 6px;
  border-radius: 4px;
}
.prio-P0 { background: #FEE2E2; color: #DC2626; }
.prio-P1 { background: #FEF3C7; color: #D97706; }
.prio-P2 { background: #E0E7FF; color: #4F46E5; }
.prio-P3 { background: #F3F4F6; color: #6B7280; }
.st-ok {
  color: var(--accent-success);
}
/* C5：AI 生成向导六大策略配比网格 */
.ai-weights-grid {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 10px;
  margin-bottom: 12px;
}
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
    max-height: 250px;
    border-right: 0;
    border-bottom: 1px solid var(--border-subtle);
  }
  /* 窄屏单列布局下隐藏拖拽手柄 */
  .ft-resizer {
    display: none;
  }
  .workspace-main {
    min-height: 660px;
  }
  .ws-toolbar .row:last-child {
    width: 100%;
    margin-left: 0 !important;
    justify-content: flex-start !important;
  }
  .strategy-banner,
  .ws-status-bar {
    flex-wrap: wrap;
    gap: 8px;
  }
}

@media (max-width: 640px) {
  .ft-sidebar {
    max-height: 210px;
  }
  .ws-toolbar {
    padding: 8px 12px;
    gap: 8px;
  }
  .ws-toolbar .btn {
    font-size: 11px;
    padding: 4px 8px;
  }
  .strategy-banner {
    padding: 6px 12px;
    font-size: 11.5px;
  }
  .ai-weights-grid {
    grid-template-columns: repeat(2, 1fr);
  }
  .ws-status-bar {
    padding: 6px 12px;
    font-size: 11px;
  }
}

@media (max-width: 420px) {
  .ai-weights-grid {
    grid-template-columns: 1fr;
  }
}
</style>
