<template>
  <div class="datasets-workbench">
    <div v-if="modeStore.mode === 'rag'" class="mode-context-panel panel">
      <span class="eyebrow">RAG 测试模式</span>
      <h2>RAG 评测使用知识库与黄金 QA</h2>
      <p>基准数据集只服务于大模型对比评测。当前模式下，请在知识库工作台管理文档、切块、检索与黄金 QA，再发起 RAG 评测。</p>
      <router-link to="/kb" class="btn btn-sign btn-sm">进入知识库工作台</router-link>
    </div>

    <div v-else class="ft-layout" :style="{ '--ft-w': treeWidth + 'px' }">
      <!-- 左侧：目录树侧边栏 -->
      <div class="ft-sidebar">
        <div class="ft-header">
          <div class="row-between mb8">
            <span style="font-weight: 600; font-size: 13px">资源目录树</span>
            <div class="row" style="gap: 6px">
              <!-- 对齐原型：「+ 新建」触发 AI 智能合成；「上传」走真实 JSONL/CSV 上传通道 -->
              <button class="btn btn-secondary btn-sm" style="font-size: 11px" @click="openAiGenModal">+ 新建</button>
              <button class="btn btn-ghost btn-sm" style="font-size: 11px" title="上传 JSONL / CSV 数据集" @click="openUploadModal(null)">上传</button>
            </div>
          </div>
          <input v-model="treeSearch" class="input" placeholder="搜索数据集 / 黄金 QA..." style="height: 30px; font-size: 12px" />
        </div>

        <div class="ft-tree">
          <div v-for="folder in filteredFolders" :key="folder.id" :data-fid="folder.id">
            <!-- 文件夹节点：右键唤起目录级菜单（新建数据集 / 子文件夹 / 重命名 / 删除） -->
            <div
              class="ft-node folder"
              @click="folder.open = !folder.open"
              @contextmenu.prevent.stop="openCtxMenu($event, 'folder', folder.id)"
            >
              <span class="ft-icon">{{ folder.open ? '▾' : '▸' }}</span>
              <span>📁 {{ folder.name }}</span>
              <span class="ft-badge">{{ folder.items.length }}</span>
            </div>

            <div v-if="folder.open" class="ft-folder-child">
              <!-- 文件节点：右键唤起文件级菜单（评测 / 覆盖上传 / AI 补全 / 重命名 / 导出 / 删除） -->
              <div
                v-for="item in folder.items"
                :key="item.id"
                class="ft-node"
                :class="{ active: activeDatasetId === item.id }"
                :title="`${item.name} · v${item.version}`"
                @click="requestSelectDataset(item.id)"
                @contextmenu.prevent.stop="openCtxMenu($event, 'file', item.id)"
              >
                <span class="ft-icon">{{ item.isGoldQa ? '⭐' : '📄' }}</span>
                <span style="overflow: hidden; text-overflow: ellipsis; white-space: nowrap">{{ item.name }}</span>
                <span class="tag-soft" style="font-size: 10px; padding: 1px 5px; margin-left: auto">v{{ item.version }}</span>
                <span v-if="item.pending_complete_count > 0" class="ft-status-dot" :title="`${item.pending_complete_count} 行待补全`"></span>
              </div>
            </div>
          </div>
          <!-- 目录树空态 / 搜索无结果提示 -->
          <div v-if="!filteredFolders.length" class="tertiary" style="padding: 14px 12px; font-size: 12px; line-height: 1.7">
            {{ treeSearch.trim() ? `未找到匹配「${treeSearch.trim()}」的数据集` : '暂无数据集，点击上方「+ 新建」或「上传」开始' }}
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

      <!-- 右侧：数据表格工作台 -->
      <div v-if="currentItem" class="workspace-main">
        <!-- 1. 顶部工具栏 -->
        <div class="ws-toolbar">
          <div class="row" style="gap: 8px; align-items: center">
            <span style="font-weight: 700; font-size: 15px">{{ currentItem.name }}</span>
            <span class="tag-soft" style="font-size: 11px">v{{ currentItem.version }}</span>
            <!-- 类型徽章：黄金 QA 用知识库青色，基准数据集用数据集色（对齐原型） -->
            <span
              class="tag-soft"
              :style="isGoldQaActive
                ? { color: 'var(--c-kb)', borderColor: 'var(--t-kb)' }
                : { color: 'var(--c-datasets)', borderColor: 'var(--t-datasets)' }"
            >{{ isGoldQaActive ? '黄金 QA' : '基准数据集' }}</span>
            <span v-if="!isGoldQaActive && currentDataset && currentDataset.pending_complete_count > 0" class="badge badge-awaiting_case_confirm">
              {{ currentDataset.pending_complete_count }} 条待补全
            </span>
          </div>

          <!-- 黄金 QA 视图：行编辑依赖 M3 行级接口，仅保留评测入口（对齐原型工具栏） -->
          <div v-if="isGoldQaActive" class="row" style="gap: 8px; align-items: center; margin-left: auto; flex-wrap: wrap; justify-content: flex-end">
            <button class="btn btn-sign btn-sm" @click="openRagDrawer">发起 RAG 评测</button>
          </div>
          <div v-else class="row" style="gap: 8px; align-items: center; margin-left: auto; flex-wrap: wrap; justify-content: flex-end">
            <button class="btn btn-secondary btn-sm" @click="addRow">+ 新增行</button>
            <button class="btn btn-secondary btn-sm" @click="openAddColModal">+ 新增列</button>
            <button class="btn btn-ai btn-sm" @click="openAiGenModal">✨ AI 合成新数据</button>
            <button class="btn btn-ai btn-sm" @click="openAiFillModal">AI 补全缺失行</button>
            <button class="btn btn-secondary btn-sm" :disabled="!hasUnsavedChanges || savingRows" title="快捷键 Ctrl/⌘ + S" @click="persistRows">
              {{ savingRows ? '保存中…' : '保存修改' }}
            </button>
            <button class="btn btn-secondary btn-sm" @click="exportJsonl">导出 JSONL</button>
            <button class="btn btn-sign btn-sm" @click="openLaunchDrawer">发起基准评测</button>
          </div>
        </div>

        <!-- 2. 表格数据网格 -->
        <div class="ws-grid-container">
          <table class="ds-table">
            <thead>
              <tr>
                <!-- 全选联动：勾选状态仅存于本地编辑态，对齐原型 chk-all 行为 -->
                <th style="width: 44px"><input type="checkbox" :checked="allRowsChecked" @change="toggleAllRows" /></th>
                <th style="width: 70px">行号</th>
                <th style="min-width: 220px">测试问句 (Question) <i class="req" style="color: var(--accent-error)">*</i></th>
                <th style="min-width: 260px">标准答案 (Reference) <i class="req" style="color: var(--accent-error)">*</i></th>
                <!-- 黄金 QA 第三列为预期召回文档，基准数据集为上下文（对齐原型表头切换） -->
                <th style="min-width: 140px">{{ isGoldQaActive ? '预期文档 expected_doc_ids' : '上下文 / 前置 (Context)' }}</th>
                <template v-if="!isGoldQaActive">
                  <th style="min-width: 110px">标签</th>
                  <th style="min-width: 90px">难度</th>
                </template>
                <!-- D3 自定义扩展列表头：薄荷绿底 + ✕ 删列入 -->
                <th v-for="col in customCols" :key="col.key" class="custom-col-th" style="min-width: 110px">
                  {{ col.name }}
                  <button class="link-btn danger" style="font-size: 10px; padding: 0 2px" title="删除该扩展列" @click="removeCustomCol(col.key)">✕</button>
                </th>
                <th style="width: 90px">校验状态</th>
                <th style="width: 110px; text-align: right">操作</th>
              </tr>
            </thead>
            <tbody>
              <!-- 黄金 QA 行级数据依赖 M3 接口，当前展示空态说明（不用静态数据顶替） -->
              <tr v-if="isGoldQaActive">
                <td :colspan="5 + customCols.length" style="text-align: center; padding: 40px 16px; color: var(--text-tertiary)">
                  黄金 QA「{{ currentItem?.name }}」共 {{ activeGoldQa?.row_count || 0 }} 行，行级查看与编辑将在 M3 知识库里程碑接入。
                </td>
              </tr>
              <!-- 表格行：双击打开弹窗编辑；右键唤起行级菜单（编辑 / 补全 / 复制 / 勾选 / 插入 / 副本 / 删除） -->
              <tr
                v-for="(r, idx) in sampleRows"
                v-else
                :key="idx"
                @contextmenu.prevent="openCtxMenu($event, 'row', '', idx)"
                @dblclick="openRowEditModal(idx)"
              >
                <td><input v-model="r.checked" type="checkbox" /></td>
                <td class="mono small">{{ r.row_no }}</td>
                <!-- cell-bad 作用于单元格本身：红字 + 红色虚线下划线，对齐原型 datasets.html。 -->
                <td class="cell-edit" :class="{ 'cell-bad': !r.q.trim() }" @click="editCell(r, 'q')">
                  <input
                    v-if="editingCell?.row === r && editingCell?.field === 'q'"
                    v-model="r.q"
                    class="cell-input"
                    autofocus
                    @blur="finishEditing"
                    @keyup.enter="finishEditing"
                    @keyup.esc="cancelEditing"
                  />
                  <span v-else>
                    {{ r.q || '（空问句 · 待补全）' }}
                  </span>
                </td>
                <td class="cell-edit" :class="{ 'cell-bad': !r.r.trim() }" @click="editCell(r, 'r')">
                  <input
                    v-if="editingCell?.row === r && editingCell?.field === 'r'"
                    v-model="r.r"
                    class="cell-input"
                    autofocus
                    @blur="finishEditing"
                    @keyup.enter="finishEditing"
                    @keyup.esc="cancelEditing"
                  />
                  <span v-else>
                    {{ r.r || '（空答案 · 待补全）' }}
                  </span>
                </td>
                <td class="cell-edit" @click="editCell(r, 'c')">
                  <input
                    v-if="editingCell?.row === r && editingCell?.field === 'c'"
                    v-model="r.c"
                    class="cell-input"
                    autofocus
                    @blur="finishEditing"
                    @keyup.enter="finishEditing"
                    @keyup.esc="cancelEditing"
                  />
                  <span v-else>{{ r.c || '—' }}</span>
                </td>
                <td class="cell-edit" @click="editCell(r, 'tags')">
                  <input
                    v-if="editingCell?.row === r && editingCell?.field === 'tags'"
                    v-model="r.tags"
                    class="cell-input"
                    autofocus
                    @blur="finishEditing"
                    @keyup.enter="finishEditing"
                    @keyup.esc="cancelEditing"
                  />
                  <span v-else class="tag-soft" style="font-size: 11px">{{ r.tags || '常规' }}</span>
                </td>
                <td class="cell-edit" @click="editCell(r, 'difficulty')">
                  <select
                    v-if="editingCell?.row === r && editingCell?.field === 'difficulty'"
                    v-model="r.difficulty"
                    class="select"
                    style="height: 28px; padding: 2px 20px 2px 6px; font-size: 11px"
                    autofocus
                    @blur="finishEditing"
                    @change="finishEditing"
                    @keyup.esc="cancelEditing"
                  >
                    <option>简单</option>
                    <option>中等</option>
                    <option>高</option>
                  </select>
                  <span v-else class="tag-soft" style="font-size: 11px">{{ r.difficulty || '简单' }}</span>
                </td>
                <!-- D3 自定义扩展列单元格：与内置列共用就地编辑交互，值存于 row.extras -->
                <td v-for="col in customCols" :key="col.key" class="cell-edit" @click="editCell(r, col.key)">
                  <input
                    v-if="editingCell?.row === r && editingCell?.field === col.key"
                    v-model="r.extras[col.key]"
                    class="cell-input"
                    autofocus
                    @blur="finishEditing"
                    @keyup.enter="finishEditing"
                    @keyup.esc="cancelEditing"
                  />
                  <span v-else>{{ r.extras[col.key] || '—' }}</span>
                </td>
                <!-- 行级校验状态：问句或标准答案缺失即为待补全。 -->
                <td>
                  <span v-if="!r.q.trim() || !r.r.trim()" class="badge badge-awaiting_case_confirm">⊘ 待补全</span>
                  <span v-else class="badge badge-succeeded">✓ 达标</span>
                </td>
                <td style="text-align: right; white-space: nowrap">
                  <button class="link-btn" @click="openRowEditModal(idx)">编辑</button>
                  <button class="link-btn danger" @click="deleteRow(idx)">删除</button>
                </td>
              </tr>
            </tbody>
          </table>
        </div>

        <!-- 3. 底部状态栏 -->
        <div class="ws-status-bar">
          <template v-if="isGoldQaActive">
            <span>共 <b class="num mono">{{ activeGoldQa?.row_count || 0 }}</b> 行</span>
            <span class="tertiary">黄金 QA 资产 · 行级编辑 M3 接入</span>
          </template>
          <template v-else>
            <span>共 <b class="num mono">{{ sampleRows.length }}</b> 行数据</span>
            <span v-if="pendingCount > 0" class="st-bad">
              ⚠ {{ pendingCount }} 行缺失测试句或参考答案
            </span>
            <span v-else class="st-ok">✓ 数据格式校验通过</span>
            <!-- D3 扩展列计数，对齐原型状态栏 -->
            <span>扩展列: <b class="num mono">{{ customCols.length }}</b></span>
            <!-- 批量操作条：勾选行后出现，支持批量删除与导出选中 -->
            <template v-if="selectedCount > 0">
              <span>已选 <b class="num mono">{{ selectedCount }}</b> 行</span>
              <button class="link-btn" @click="exportSelectedRows">导出选中</button>
              <button class="link-btn danger" @click="batchDeleteRows">批量删除</button>
            </template>
          </template>
          <span class="grow"></span>
          <!-- 主评测指标选择仅基准数据集展示（对齐原型：黄金 QA 视图无指标切换） -->
          <div v-if="!isGoldQaActive && currentDataset" class="row" style="gap: 6px; align-items: center">
            <span class="tertiary">主指标:</span>
            <select v-model="currentDataset.metric" class="select" style="height: 28px; padding: 2px 24px 2px 8px; font-size: 12px" @change="saveMetric">
              <option value="contain">Contain (包含匹配)</option>
              <option value="exact">Exact (完全一致)</option>
              <option value="regex">Regex (正则表达式)</option>
              <option value="rouge_l">ROUGE-L</option>
              <option value="bleu">BLEU</option>
            </select>
          </div>
        </div>
      </div>
      <!-- 空态仍保留完整工作台骨架：工具栏 + 表头 + 状态栏，空表格内嵌引导操作 -->
      <div v-else class="workspace-main">
        <div class="ws-toolbar">
          <div class="row" style="gap: 8px; align-items: center">
            <span style="font-weight: 700; font-size: 15px">数据集工作台</span>
            <span class="tag-soft" style="color: var(--c-datasets); border-color: var(--t-datasets)">基准数据集</span>
          </div>
          <div class="row" style="gap: 8px; align-items: center; margin-left: auto; flex-wrap: wrap; justify-content: flex-end">
            <button class="btn btn-secondary btn-sm" @click="openUploadModal(null)">⤴ 上传数据集</button>
            <button class="btn btn-ai btn-sm" @click="createEmptyDataset(() => openAiGenModal())">✨ AI 合成新数据</button>
            <button class="btn btn-sign btn-sm" @click="createEmptyDataset()">+ 新建空数据集</button>
          </div>
        </div>
        <div class="ws-grid-container">
          <table class="ds-table">
            <thead>
              <tr>
                <th style="width: 44px"><input type="checkbox" disabled /></th>
                <th style="width: 70px">行号</th>
                <th style="min-width: 220px">测试问句 (Question) <i class="req" style="color: var(--accent-error)">*</i></th>
                <th style="min-width: 260px">标准答案 (Reference) <i class="req" style="color: var(--accent-error)">*</i></th>
                <th style="min-width: 140px">上下文 / 前置 (Context)</th>
                <th style="min-width: 110px">标签</th>
                <th style="min-width: 90px">难度</th>
                <th style="width: 90px">校验状态</th>
                <th style="width: 110px; text-align: right">操作</th>
              </tr>
            </thead>
            <tbody>
              <tr>
                <td colspan="9" style="padding: 56px 16px; border-bottom: none">
                  <div style="display: flex; flex-direction: column; align-items: center; gap: 10px; color: var(--text-tertiary)">
                    <span style="font-size: 34px">🗂️</span>
                    <span style="font-size: 14px; font-weight: 600; color: var(--text-secondary)">暂无可用数据集</span>
                    <span class="small">上传 JSONL / CSV 文件，或先新建空集再由 AI 从场景描述合成评测数据</span>
                    <div class="row" style="gap: 8px; margin-top: 6px">
                      <button class="btn btn-secondary btn-sm" @click="openUploadModal(null)">⤴ 上传数据集</button>
                      <button class="btn btn-ai btn-sm" @click="createEmptyDataset(() => openAiGenModal())">✨ AI 合成</button>
                      <button class="btn btn-sign btn-sm" @click="createEmptyDataset()">+ 新建空数据集</button>
                    </div>
                  </div>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
        <div class="ws-status-bar">
          <span>共 <b class="num mono">0</b> 行数据</span>
          <span class="tertiary">尚未创建数据集</span>
          <span class="grow"></span>
        </div>
      </div>
    </div>

    <!-- 弹窗与抽屉 -->
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

    <!-- D1 右键上下文菜单：NDropdown manual 触发 + 坐标定位，点击外部关闭 -->
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

    <!-- D2 行结构化编辑弹窗：问题 / 答案 / 上下文 + 自定义扩展字段 -->
    <n-modal v-model:show="rowEdit.show" preset="card" :title="`编辑样本行 #${rowEdit.rowNo}`" style="width: 640px">
      <div class="field">
        <label class="field-label">问题 / 提示词 (Question / Prompt) <span class="req">*</span></label>
        <n-input v-model:value="rowEdit.q" type="textarea" :autosize="{ minRows: 3, maxRows: 6 }" placeholder="请输入测试问句" />
      </div>
      <div class="field">
        <label class="field-label">标准答案 / 预期输出 (Reference) <span class="req">*</span></label>
        <n-input v-model:value="rowEdit.r" type="textarea" :autosize="{ minRows: 3, maxRows: 6 }" placeholder="请输入标准答案" />
      </div>
      <div class="field">
        <label class="field-label">上下文注入 / Prompt Context (支持 Markdown / JSON)</label>
        <n-input v-model:value="rowEdit.c" class="mono" type="textarea" :autosize="{ minRows: 3, maxRows: 8 }" placeholder="可粘贴 Markdown 或 JSON 结构化上下文" />
      </div>
      <!-- 自定义扩展字段区：随扩展列动态生成输入框 -->
      <template v-if="customCols.length">
        <div class="rail-label" style="margin-bottom: 10px">自定义扩展字段</div>
        <div class="form-row">
          <div v-for="col in customCols" :key="col.key" class="field">
            <label class="field-label">{{ col.name }} ({{ col.key }})</label>
            <n-input v-model:value="rowEdit.extras[col.key]" :placeholder="col.type === 'json' ? '请输入 JSON 结构体文本' : col.type === 'number' ? '请输入数值' : '请输入文本'" />
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

    <!-- D3 新增自定义扩展列弹窗：Key / 名称 / 类型三要素 -->
    <n-modal v-model:show="addCol.show" preset="card" title="新增自定义数据列 (Custom Column)" style="width: 460px">
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

    <!-- D4 AI 合成新数据两步向导：Step1 参数配置 → Step2 候选预览导入 -->
    <n-modal v-model:show="aiGen.show" preset="card" title="✨ AI 智能生成评测数据集" style="width: 760px">
      <!-- Step 1: 合成模式与高级控制参数 -->
      <div v-show="aiGen.step === 1">
        <div class="row" style="gap: 8px; margin-bottom: 14px">
          <button class="chip" :class="{ on: aiGen.mode === 'scene' }" @click="aiGen.mode = 'scene'">🌟 场景定向合成</button>
          <button class="chip" :class="{ on: aiGen.mode === 'seed' }" @click="aiGen.mode = 'seed'">🌱 种子样本扩写</button>
          <button class="chip" :class="{ on: aiGen.mode === 'doc' }" @click="aiGen.mode = 'doc'">📄 需求文档/OpenAPI 提取</button>
        </div>

        <!-- 场景模式：预设业务模板 + 目标描述 -->
        <div v-show="aiGen.mode === 'scene'">
          <div class="field">
            <label class="field-label">预设业务场景模板</label>
            <n-select v-model:value="aiGen.preset" :options="presetOptions" @update:value="onPresetChange" />
          </div>
          <div class="field">
            <label class="field-label">场景与评估目标描述 (Prompt Instruction) <span class="req">*</span></label>
            <n-input v-model:value="aiGen.instruction" type="textarea" :autosize="{ minRows: 3, maxRows: 5 }" />
          </div>
        </div>

        <!-- 种子模式：种子样本下拉 + 扩写维度复选 -->
        <div v-show="aiGen.mode === 'seed'">
          <div class="field">
            <label class="field-label">选择种子样本（基于此样本扩写同义、长尾或边界题）</label>
            <n-select v-model:value="aiGen.seedSample" :options="seedOptions" placeholder="请选择一条已有样本作为种子" />
          </div>
          <div class="field">
            <label class="field-label">扩写维度</label>
            <n-checkbox-group v-model:value="aiGen.dims">
              <div class="row wrap" style="gap: 12px">
                <n-checkbox value="synonym">同义口语化改写</n-checkbox>
                <n-checkbox value="constraint">增加前置约束条件</n-checkbox>
                <n-checkbox value="boundary">衍生边界异常提问</n-checkbox>
              </div>
            </n-checkbox-group>
          </div>
        </div>

        <!-- 文档模式：粘贴 PRD / OpenAPI 文本 -->
        <div v-show="aiGen.mode === 'doc'">
          <div class="field">
            <label class="field-label">粘贴 PRD / OpenAPI 接口定义 / Markdown 需求文本</label>
            <n-input v-model:value="aiGen.docText" class="mono" type="textarea" :autosize="{ minRows: 4, maxRows: 8 }" placeholder="粘贴接口文档或需求描述，AI 将自动抽取问答对及对应上下文..." />
          </div>
        </div>

        <div class="rail-label" style="margin: 4px 0 10px">高级控制参数</div>
        <div class="form-row-3">
          <div class="field">
            <label class="field-label">生成行数 (<b class="num">{{ aiGen.rowCount }}</b> 行)</label>
            <n-slider v-model:value="aiGen.rowCount" :min="3" :max="25" :step="1" />
          </div>
          <div class="field">
            <label class="field-label">生成模型</label>
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
            <label class="field-label">难易度分布配比</label>
            <div class="row" style="gap: 8px; font-size: 12px">
              <span class="tag-soft">简单 40%</span>
              <span class="tag-soft">中等 40%</span>
              <span class="tag-soft">高难/陷阱 20%</span>
            </div>
          </div>
          <div class="field">
            <label class="field-label">自动生成字段</label>
            <div class="row wrap" style="gap: 10px; font-size: 12px">
              <n-checkbox v-model:checked="aiGen.genRef">标准答案</n-checkbox>
              <n-checkbox v-model:checked="aiGen.genCtx">上下文 Context</n-checkbox>
              <n-checkbox v-model:checked="aiGen.genTags">标签 Tags</n-checkbox>
            </div>
          </div>
        </div>
      </div>

      <!-- Step 2: 候选结果表格预览（勾选 / 行内编辑 / 剔除 / 全选） -->
      <div v-show="aiGen.step === 2">
        <div class="row-between" style="margin-bottom: 8px">
          <span style="font-weight: 600; font-size: 13px">AI 生成候选项（已生成 <b class="num">{{ aiGen.candidates.length }}</b> 条，可直接点击单元格微调）</span>
          <button class="link-btn" @click="toggleAllCandidates">全选 / 全不选</button>
        </div>
        <div style="max-height: 360px; overflow-y: auto; border: 1px solid var(--border-subtle); border-radius: 8px">
          <table class="ds-table">
            <thead>
              <tr>
                <th style="width: 36px"><input type="checkbox" :checked="aiAllSelected" @change="toggleAllCandidates" /></th>
                <th>问题 Question</th>
                <th>参考答案 Reference</th>
                <th style="width: 110px">难度 / 标签</th>
                <th style="width: 70px">操作</th>
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

    <!-- D5 AI 补全确认弹窗：待补全统计 + Prompt 引导 + 补全范围 + Few-Shot 说明 -->
    <n-modal v-model:show="aiFill.show" preset="card" :title="`✨ AI 智能补全缺失字段（共 ${pendingCount} 行待补全）`" style="width: 560px">
      <p class="small" style="margin: 0 0 12px; color: var(--text-secondary)">
        系统检测到以下样本行缺少核心字段（问句或标准答案）。AI 将结合已有业务上下文自动推导并补全，补全后将保持高亮以供复核。
      </p>
      <div class="field">
        <label class="field-label">业务提示词引导 (Prompt Instruction)</label>
        <n-input v-model:value="aiFill.instruction" type="textarea" :autosize="{ minRows: 2, maxRows: 4 }" />
      </div>
      <div class="form-row">
        <div class="field">
          <label class="field-label">补全范围</label>
          <div class="row" style="gap: 12px; font-size: 12px; margin-top: 4px">
            <n-checkbox v-model:checked="aiFill.scopeQ">自动填补缺失问句</n-checkbox>
            <n-checkbox v-model:checked="aiFill.scopeR">自动填补缺失参考答案</n-checkbox>
          </div>
        </div>
        <div class="field">
          <label class="field-label">参考上下文</label>
          <span class="small tertiary">自动关联数据集同组高质样本特征进行少样本学习 (Few-Shot)</span>
        </div>
      </div>
      <template #footer>
        <div style="display: flex; justify-content: flex-end; gap: 8px">
          <n-button @click="aiFill.show = false">取消</n-button>
          <n-button type="primary" :loading="aiFill.filling" @click="confirmAiFill">开始 AI 补全 ({{ pendingCount }} 行)</n-button>
        </div>
      </template>
    </n-modal>

    <!-- 通用命名弹窗：复用于 重命名数据集 / 新建空数据集 / 新建子文件夹 / 重命名目录 -->
    <n-modal v-model:show="nameDialog.show" preset="card" :title="nameDialog.title" style="width: 420px">
      <div class="field">
        <label class="field-label">{{ nameDialog.label }} <span class="req">*</span></label>
        <n-input v-model:value="nameDialog.value" placeholder="请输入名称" @keyup.enter="confirmNameDialog" />
      </div>
      <template #footer>
        <div style="display: flex; justify-content: flex-end; gap: 8px">
          <n-button @click="nameDialog.show = false">取消</n-button>
          <n-button type="primary" :loading="nameDialogBusy" @click="confirmNameDialog">确认</n-button>
        </div>
      </template>
    </n-modal>

    <!-- 黄金 QA「发起 RAG 评测」抽屉：字段对齐原型 openEvalDrawer 的 rag 分支（kb_id / gold_qa_id / rag_mode / 运行参数 / 先评后压） -->
    <n-drawer v-model:show="ragDrawer.show" :width="480">
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
  /** 行勾选态：仅本地编辑态使用（对齐原型 chk-all 全选联动），不随保存落库。 */
  checked: boolean
  /** 自定义扩展列的值集合：Key → 文本值，随行保存时一并持久化。 */
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
const hasUnsavedChanges = ref(false)
// field 为字符串以同时支持内置列（q/r/c/tags/difficulty）与自定义扩展列 Key；original 供 Escape 取消时还原。
const editingCell = ref<{ row: EditableDatasetRow; field: string; original: string } | null>(null)
const showUploadModal = ref(false)
const datasetForUpload = ref<Dataset | null>(null)
const showLaunchDrawer = ref(false)

// ─── 目录树面板自由伸缩（对齐原型 ft-resizer：拖拽 200–520px，双击复位 290px，localStorage 持久化） ───
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

// ─── 黄金 QA 资产：树内与数据集混排（⭐ 节点），行级数据依赖 M3 接口 ───
const goldQas = ref<GoldQA[]>([])
const activeGoldQa = computed(() => goldQas.value.find(g => g.id === activeDatasetId.value))
const isGoldQaActive = computed(() => !!activeGoldQa.value)

const currentDataset = computed(() =>
  datasets.value.find(dataset => dataset.id === activeDatasetId.value) || (isGoldQaActive.value ? undefined : datasets.value[0]),
)
// 当前选中项：数据集或黄金 QA（工具栏标题 / 版本号 / 状态栏共用）
const currentItem = computed(() => activeGoldQa.value || currentDataset.value)

/** 目录树节点统一结构：数据集与黄金 QA 混排展示。 */
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
// 黄金 QA 独立成组（对齐原型「客服与知识库 FAQ」目录），有资产时才展示
const goldQaFolder = ref<TreeFolder>({ id: 'gold-qa', name: '黄金 QA', open: true, items: [] })
const allFolders = computed<TreeFolder[]>(() =>
  goldQaFolder.value.items.length ? [...folders.value, goldQaFolder.value] : folders.value,
)
const pendingCount = computed(() => sampleRows.value.filter(row => !row.q.trim() || !row.r.trim()).length)
const filteredFolders = computed(() => {
  const keyword = treeSearch.value.trim().toLowerCase()
  if (!keyword) return allFolders.value
  return allFolders.value.map(folder => ({
    ...folder,
    items: folder.items.filter(item => item.name.toLowerCase().includes(keyword)),
  })).filter(folder => folder.items.length > 0)
})

// ─── D3 自定义扩展列状态：按数据集维度维护（对齐原型 CUSTOM_COLS），契约 column_schema 持久化 ───
const customColsMap = ref<Record<string, CustomColumn[]>>({})
const customCols = computed<CustomColumn[]>(() => {
  const ds = currentDataset.value
  return ds ? customColsMap.value[ds.id] || [] : []
})

// 契约 column_schema 与页面 CustomColumn 的互转（type 缺省按 text）
function fromColumnSchema(schema: Dataset['column_schema']): CustomColumn[] {
  return (schema || [])
    .filter(item => item && item.key)
    .map(item => ({ key: item.key, name: item.name || item.key, type: (item.type as CustomColumn['type']) || 'text' }))
}

/** 持久化扩展列定义（PUT /api/datasets/{id} 的 column_schema 字段），失败时回滚本地状态。 */
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

// 契约内已知行字段，其余动态字段统一归入 extras 扩展列值集。
const KNOWN_ROW_KEYS = new Set(['row_no', 'question', 'reference', 'context', 'q', 'r', 'c', 'tags', 'difficulty', 'source_case_id', 'is_pending'])

// 将接口行字段和页面可编辑字段归一化，兼容历史 q/r/c 与正式 question/reference/context 响应。
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

// 将页面编辑结果转换为接口约定的行载荷，并保留扩展字段。
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
    // 扩展列值随行一并持久化。
    ...row.extras,
  }))
}

// 让目录树始终使用当前接口返回的数据集，而不是原型中固定的示例名称。
function syncDatasetTree(list: Dataset[]) {
  // 根目录可能被本地删除，缺失时自动重建，保证数据集始终有挂载点。
  let root = folders.value.find(folder => folder.id === 'datasets')
  if (!root) {
    root = { id: 'datasets', name: '数据集', open: true, items: [] }
    folders.value.unshift(root)
  }
  root.items = list.map(dataset => ({
    id: dataset.id,
    name: dataset.name,
    version: dataset.version,
    isGoldQa: false,
    pending_complete_count: dataset.pending_complete_count,
  }))
}

// 黄金 QA 目录树节点由知识库资产接口组装（M3 前行级数据不可得，仅元信息入树）。
function syncGoldQaTree(list: GoldQA[]) {
  goldQaFolder.value.items = list.map(qa => ({
    id: qa.id,
    name: qa.name,
    version: qa.version,
    isGoldQa: true,
    pending_complete_count: 0,
  }))
}

// ─── 行勾选：对齐原型 chk-all 全选 / 全不选联动（仅本地编辑态），并驱动批量操作条 ───
const allRowsChecked = computed(() => sampleRows.value.length > 0 && sampleRows.value.every(row => row.checked))
const selectedCount = computed(() => sampleRows.value.filter(row => row.checked).length)

function toggleAllRows(e: Event) {
  const checked = (e.target as HTMLInputElement).checked
  sampleRows.value.forEach(row => {
    row.checked = checked
  })
}

/** 批量删除勾选行：二次确认后从本地编辑态移除，仍由「保存修改」统一落库。 */
function batchDeleteRows() {
  const count = selectedCount.value
  if (!count) return
  dialog.warning({
    title: '批量删除',
    content: `确认删除勾选的 ${count} 行？点击“保存修改”后同步服务端。`,
    positiveText: '删除',
    negativeText: '取消',
    onPositiveClick: () => {
      sampleRows.value = sampleRows.value.filter(row => !row.checked)
      hasUnsavedChanges.value = true
      message.info(`已删除 ${count} 行，点击“保存修改”后生效`)
    },
  })
}

/** 导出勾选行为 JSONL：便于把子集贴到外部工具或另存为新数据集。 */
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

// 读取单元格当前值（内置列或扩展列），供编辑取消时还原。
function cellValue(row: EditableDatasetRow, field: string): string {
  if (field === 'q' || field === 'r' || field === 'c' || field === 'tags' || field === 'difficulty') return row[field]
  return row.extras[field] || ''
}

function editCell(row: EditableDatasetRow, field: string) {
  // 记录当前编辑单元格与原始值，失焦提交、Escape 取消（对齐原型单元格编辑交互）。
  editingCell.value = { row, field, original: cellValue(row, field) }
}

function finishEditing() {
  // 统一结束单元格编辑并提示用户显式保存。
  editingCell.value = null
  hasUnsavedChanges.value = true
}

function cancelEditing() {
  // Escape 放弃本次编辑：还原原始值且不标记待保存。
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

// 切换树节点：数据集读取服务端行数据；黄金 QA 行级数据依赖 M3 接口，仅切换视图。
async function selectDataset(id: string) {
  activeDatasetId.value = id
  if (goldQas.value.some(g => g.id === id)) {
    sampleRows.value = []
    hasUnsavedChanges.value = false
    return
  }
  await loadRows(id)
}

/**
 * 带未保存守卫的切换入口：存在未落库编辑时先询问「保存并切换 / 放弃修改」，
 * 关闭对话框视为取消切换；after 回调在切换完成后执行（供右键菜单续接动作）。
 */
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
  // 传入空值创建数据集，传入已有数据集则覆盖上传新版本。
  datasetForUpload.value = dataset
  showUploadModal.value = true
}

/** 新建空数据集：创建后自动选中；after 回调用于空态「AI 合成」创建完毕直接进入向导。 */
function createEmptyDataset(after?: () => void) {
  openNameDialog('新建数据集（空集）', '数据集名称', 'new-dataset', async (val) => {
    const created = await api.datasets.create({ name: val })
    await loadDatasets()
    await selectDataset(created.id)
    message.success(`已创建空数据集「${created.name}」`)
    after?.()
  })
}

function openLaunchDrawer() {
  // 仅打开评测配置抽屉，任务创建仍由抽屉确认动作完成。
  showLaunchDrawer.value = true
}

/** 评测下单成功后跳转任务中心，与原型交互保持一致。 */
function handleLaunchSuccess() {
  router.push('/tasks')
}

/** 构造空白候选行，row_no 取当前最大值 +1。 */
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
  // 新增空白候选行，避免以示例文本伪造已验证数据。
  sampleRows.value.push(buildEmptyRow())
  hasUnsavedChanges.value = true
  message.info('已新增空白行，填写后点击“保存修改”落库')
}

function deleteRow(index: number) {
  // 删除先保留在本地编辑态，显式保存后才同步服务端。
  sampleRows.value.splice(index, 1)
  hasUnsavedChanges.value = true
  message.info('已删除该行，点击“保存修改”后生效')
}

// 保存所有可编辑行，服务端会统一校验并持久化扩展列。
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
    message.success('数据集行已保存')
  } catch (err: any) {
    message.error(err.message || '保存数据集行失败')
  } finally {
    savingRows.value = false
  }
}

function exportJsonl() {
  // 导出当前可见表格，便于在保存前人工复核候选内容。
  const content = sampleRows.value.map(row => JSON.stringify({ question: row.q, reference: row.r, context: row.c || null })).join('\n')
  const blob = new Blob([content], { type: 'application/jsonl' })
  const url = URL.createObjectURL(blob)
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = `${currentDataset.value?.name || 'dataset'}-v${currentDataset.value?.version || 1}.jsonl`
  anchor.click()
  URL.revokeObjectURL(url)
  message.success('当前表格内容已导出为 JSONL')
}

// 更新主评分指标并用接口响应替换本地数据，避免刷新后回退。
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
    // 扩展列定义由服务端 column_schema 下发，刷新后仍然保留（契约 §3.7）
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

// 加载黄金 QA 资产入树（M3 前 /api/kb 未实现时走前端降级，不阻塞数据集主流程）。
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

// ─── D1 右键上下文菜单（文件 / 文件夹 / 表格行 三组） ───
const ctxMenu = ref<{ show: boolean; x: number; y: number; type: CtxMenuType; targetId: string; rowIdx: number }>({
  show: false,
  x: 0,
  y: 0,
  type: 'file',
  targetId: '',
  rowIdx: -1,
})

/** 打开右键菜单：manual 触发模式下由 x/y 坐标定位。 */
function openCtxMenu(e: MouseEvent, type: CtxMenuType, targetId = '', rowIdx = -1) {
  ctxMenu.value = { show: true, x: e.clientX, y: e.clientY, type, targetId, rowIdx }
}

function closeCtxMenu() {
  ctxMenu.value.show = false
}

// 按菜单类型动态生成 NDropdown 选项（对齐原型 datasets.html 三组右键菜单）。
const ctxMenuOptions = computed<DropdownOption[]>(() => {
  if (ctxMenu.value.type === 'file') {
    // 黄金 QA 节点：覆盖上传 / AI 补全 / 重命名 / 删除均依赖 M3 接口，开放评测与 ID 复制
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
      { label: '✨ AI 补全', key: 'ai-fill' },
      { type: 'divider', key: 'd1' },
      { label: '✏ 重命名', key: 'rename' },
      { label: '📋 复制数据集 ID', key: 'copy-id' },
      { label: '⤓ 导出 JSONL', key: 'export' },
      { type: 'divider', key: 'd2' },
      { label: '🗑 删除数据集', key: 'delete' },
    ]
  }
  if (ctxMenu.value.type === 'folder') {
    return [
      { label: '📄 新建数据集（空集）', key: 'new-dataset' },
      { label: '📁 新建子文件夹', key: 'new-folder' },
      { type: 'divider', key: 'd1' },
      { label: '✏ 重命名目录', key: 'rename-folder' },
      { label: '🗑 删除目录', key: 'delete-folder' },
    ]
  }
  // 表格行菜单：编辑 / 补全 / 复制 / 勾选 / 插入 / 副本 / 删除
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
    { label: '🗑 删除本行', key: 'delete-row' },
  ]
})

/** 菜单点击统一分发：先关菜单再按目标类型执行动作。 */
function handleCtxSelect(key: string | number) {
  const { type, targetId, rowIdx } = ctxMenu.value
  closeCtxMenu()
  const action = String(key)
  if (type === 'file') void handleFileCtxAction(action, targetId)
  else if (type === 'folder') void handleFolderCtxAction(action, targetId)
  else void handleRowCtxAction(action, rowIdx)
}

/** 文件节点右键动作：评测 / 覆盖上传 / AI 补全 / 重命名 / 复制 ID / 导出 / 删除。 */
async function handleFileCtxAction(key: string, targetId: string) {
  // 黄金 QA 节点优先处理：不查数据集表，避免评测入口被空查找拦截。
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
      // 先切到目标数据集再开抽屉，确保 default-dataset-id 指向右键对象；未保存修改先经守卫确认。
      requestSelectDataset(targetId, () => openLaunchDrawer())
      break
    case 'upload':
      // 传入已有数据集，UploadDatasetModal 自动进入覆盖上传 (isOverride) 分支。
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
        message.success('已重命名')
      })
      break
    case 'copy-id':
      await navigator.clipboard.writeText(targetId)
      message.success('已复制数据集 ID 到剪贴板')
      break
    case 'export':
      // 导出以表格数据为准，先切换加载目标数据集的行。
      requestSelectDataset(targetId, () => exportJsonl())
      break
    case 'delete':
      confirmDeleteDataset(dataset)
      break
  }
}

/** 删除数据集为不可逆操作，需经确认对话框二次确认。 */
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

/** 文件夹右键动作：目录树为前端本地结构，除「新建数据集」走接口外均为本地 mock 操作。 */
async function handleFolderCtxAction(key: string, folderId: string) {
  const folder = folders.value.find(item => item.id === folderId)
  if (!folder) return
  switch (key) {
    case 'new-dataset':
      // D16 新建空数据集入口：只创建空集，行数据后续在表格中维护。
      createEmptyDataset()
      break
    case 'new-folder':
      openNameDialog('新建子文件夹', '文件夹名称', '新建文件夹', (val) => {
        folders.value.push({ id: `f-${Date.now()}`, name: val, open: true, items: [] })
        message.success('已创建子文件夹（本地目录）')
      })
      break
    case 'rename-folder':
      // 系统目录（数据集根目录 / 黄金 QA 目录）不可重命名，与删除校验保持一致。
      if (folder.id === 'datasets' || folder.id === 'gold-qa') {
        message.warning('系统目录不可重命名')
        return
      }
      openNameDialog('重命名目录', '目录名称', folder.name, (val) => {
        folder.name = val
        message.success('已更新目录名')
      })
      break
    case 'delete-folder':
      // 对齐原型：系统根目录不可删除；非空目录需先移出或删除其中的数据集。
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
        onPositiveClick: () => {
          folders.value = folders.value.filter(item => item.id !== folderId)
          message.success(`已删除目录「${folder.name}」`)
        },
      })
      break
  }
}

/** 表格行右键动作：弹窗编辑 / 单行 AI 补全 / 复制 JSON / 下方插入 / 删除。 */
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
      // 复制为契约 JSON 结构（含扩展列值），便于贴到外部工具调试。
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
      // 创建副本：内容全量拷贝，row_no 取最大值 +1，保存后落库。
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

// ─── 通用命名弹窗：复用于 重命名数据集 / 新建空数据集 / 新建子文件夹 / 重命名目录 ───
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

// ─── D2 行结构化编辑弹窗 ───
// 编辑副本避免直接改表格，确认后才写回行数据。
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
  // 双击行可能正处于单元格编辑态，先退出避免弹窗与就地编辑并存。
  editingCell.value = null
  const extras = { ...row.extras }
  // 补齐扩展列 Key，保证每列都有可编辑输入框。
  customCols.value.forEach(col => {
    if (!(col.key in extras)) extras[col.key] = ''
  })
  rowEdit.value = { show: true, idx, rowNo: row.row_no, q: row.q, r: row.r, c: row.c, extras }
}

/** 保存弹窗编辑：写回行数据并标记待保存，仍由「保存修改」统一落库。 */
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

// ─── D3 新增自定义扩展列弹窗 ───
const addCol = ref<{ show: boolean; key: string; name: string; type: CustomColumn['type'] }>({ show: false, key: '', name: '', type: 'text' })

// 内置列 Key 禁止占用，避免与契约字段冲突。
const RESERVED_COL_KEYS = ['row_no', 'question', 'reference', 'context', 'q', 'r', 'c', 'tags', 'difficulty']

function openAddColModal() {
  addCol.value = { show: true, key: '', name: '', type: 'text' }
}

/** 确认新增扩展列：校验 Key 格式与唯一性、为现有行初始化空值，并持久化列定义。 */
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
    message.success(`已添加自定义列「${name}」并持久化；行内取值点击“保存修改”后落库`)
  } catch {
    // 列定义保存失败已回滚并提示，行值保持原样
  }
}

/** 表头 ✕ 删除扩展列：同时清理各行中的列值，并持久化列定义。 */
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
    message.info(`已移除列 ${key} 并持久化；行值清理在“保存修改”后生效`)
  } catch {
    // 列定义保存失败已回滚并提示
  }
}

// ─── D4 AI 合成新数据两步向导 ───
// 预设业务场景模板（对齐原型 PRESETS），选中后自动填充场景描述。
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

/** 预设模板下拉选项：label 展示「名称 · 描述」，value 为描述文本。 */
const presetOptions = computed(() => AI_PRESETS.map(p => ({ label: `${p.name} · ${p.desc}`, value: p.desc })))

/** 种子样本下拉：取当前表格中问句完整的前 10 行。 */
const seedOptions = computed(() =>
  sampleRows.value
    .filter(row => row.q.trim())
    .slice(0, 10)
    .map(row => ({
      label: `${row.q} · ${row.r}`.slice(0, 60),
      value: `${row.q} => ${row.r}`,
    })),
)

/** 已勾选候选数：驱动「采纳并导入 (N 条)」按钮文案与禁用态。 */
const aiSelectedCount = computed(() => aiGen.value.candidates.filter(c => c.selected).length)

/** 候选全选态：有候选且全部勾选时为 true。 */
const aiAllSelected = computed(() => aiGen.value.candidates.length > 0 && aiSelectedCount.value === aiGen.value.candidates.length)

/** 打开 AI 合成向导：每次回到 Step1，并默认选中首条可用种子样本。黄金 QA 激活时回退到首个数据集；无数据集时先引导创建空集再自动进入向导。 */
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

/** 预设模板联动：选中后自动填充场景描述，仍可手动修改。 */
function onPresetChange(val: string) {
  aiGen.value.instruction = val
}

/** Step1「立即生成候选样本」：按表单参数走现有 ai-generate 通道；Mock 模式下本地造候选。 */
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
      // Mock 模式：本地按目标行数生成演示候选，便于走通两步向导交互。
      await new Promise(resolve => setTimeout(resolve, 500))
      // 「自动生成字段」复选框决定候选行是否带出答案 / 上下文 / 标签。
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

/** 候选预览表「全选 / 全不选」切换。 */
function toggleAllCandidates() {
  const target = aiSelectedCount.value < aiGen.value.candidates.length
  aiGen.value.candidates.forEach(c => {
    c.selected = target
  })
}

/** Step2「采纳并导入」：仅把勾选的候选追加进表格，仍由「保存修改」统一落库。 */
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

// ─── D5 AI 补全确认弹窗 ───
const aiFill = ref({
  show: false,
  // 默认引导词对齐原型，帮助 AI 推导含操作路径的完整答案。
  instruction: '基于已有业务上下文与同组高质样本，精准推导出前置问句与包含操作路径的完整标准答案。',
  scopeQ: true,
  scopeR: true,
  filling: false,
})

/** 打开 AI 补全弹窗：无缺失行时直接提示，不弹窗。 */
function openAiFillModal() {
  if (!currentDataset.value) return
  if (pendingCount.value === 0) {
    message.info('当前数据集所有样本均已完整，无缺失项')
    return
  }
  aiFill.value.show = true
}

/** 确认执行 AI 补全：仅提交缺失行，返回候选就地回填并等待用户显式保存。 */
async function confirmAiFill() {
  if (!currentDataset.value || aiFill.value.filling) return
  aiFill.value.filling = true
  try {
    if (api.isMock()) {
      // Mock 模式：本地按补全范围填充演示文案，走通确认弹窗交互。
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
        // 只回填补全返回的核心字段；扩展列做键级合并，避免接口未返回的自定义列被清空
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

/** 右键「AI 补全本行」：只把当前行提交给补全通道并就地回填。 */
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

// ─── 黄金 QA「发起 RAG 评测」抽屉（对齐原型 openEvalDrawer 的 rag 分支） ───
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

/** 提交 RAG 评测任务：契约 TaskSpec 直传 kb_id / gold_qa_id / rag_mode，成功后跳任务中心（对齐原型）。 */
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
    message.success('任务已创建（queued）')
    setTimeout(() => router.push('/tasks'), 650)
  } catch (err: any) {
    message.error(err.message || '创建任务失败')
  } finally {
    ragDrawer.value.submitting = false
  }
}

// Ctrl/Cmd + S 快捷保存：仅在存在未落库编辑时接管浏览器默认行为。
function onGlobalKeydown(e: KeyboardEvent) {
  if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 's') {
    if (hasUnsavedChanges.value && !isGoldQaActive.value) {
      e.preventDefault()
      void persistRows()
    }
  }
}

onMounted(() => {
  // 基准数据只在大模型模式加载，避免 RAG 模式访问后展示错误资产。
  if (modeStore.mode === 'llm') {
    void loadDatasets()
    void loadGoldQas()
  }
  window.addEventListener('keydown', onGlobalKeydown)
})

onUnmounted(() => {
  window.removeEventListener('keydown', onGlobalKeydown)
})

// 用户在当前页切回大模型模式时，按需读取基准数据资产。
watch(() => modeStore.mode, (mode) => {
  if (mode === 'llm' && !datasets.value.length) {
    void loadDatasets()
    void loadGoldQas()
  }
})
</script>

<style scoped>
.datasets-workbench {
  height: calc(100vh - var(--topbar-h) - 20px);
}
.mode-context-panel {
  max-width: 680px;
  margin: 48px auto;
  padding: 28px;
}
.mode-context-panel h2 {
  margin: 8px 0 10px;
  font-size: 20px;
}
.mode-context-panel p {
  max-width: 560px;
  margin: 0 0 20px;
  color: var(--text-secondary);
  line-height: 1.7;
}
.ft-layout {
  display: grid;
  /* 目录树宽度由 --ft-w 驱动（拖拽手柄 200–520px，默认 290px，对齐原型） */
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
/* 目录树面板拖拽调宽手柄（对齐原型 .ft-resizer） */
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
.ft-status-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: var(--accent-warning);
  margin-left: 4px;
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
.st-ok {
  color: var(--accent-success);
}
.st-bad {
  color: var(--accent-error);
}
/* D3 自定义扩展列表头：薄荷绿底（对齐原型 .custom-col-th），优先级需压过全局 .ds-table th。 */
.ds-table th.custom-col-th {
  background: color-mix(in srgb, var(--accent-ai) 6%, var(--bg-elevated));
  color: var(--accent-ai);
}
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
    max-height: 250px;
    border-right: 0;
    border-bottom: 1px solid var(--border-subtle);
  }
  .workspace-main {
    min-height: 620px;
  }
  .ws-toolbar .row:last-child {
    width: 100%;
    margin-left: 0 !important;
    justify-content: flex-start !important;
  }
  .ws-status-bar {
    flex-wrap: wrap;
    gap: 8px;
  }
}
</style>
