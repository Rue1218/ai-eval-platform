<template>
  <div class="user-workspaces-page" @keydown="handleGlobalKeydown">
    <!-- 顶部状态栏：工作区切换 + 容量水位 + 工作区管理 -->
    <div class="workspace-header-bar">
      <div class="header-left">
        <div class="workspace-selector-group">
          <label class="selector-label">当前工作区</label>
          <select
            :value="selectedWorkspaceId"
            class="workspace-select"
            :disabled="busy || loading || saving || uploading"
            @change="handleWorkspaceChange"
          >
            <option v-for="ws in items" :key="ws.id" :value="ws.id">
              {{ ws.name }} {{ ws.deleted ? '(已注销)' : '' }}
            </option>
          </select>
          <span v-if="currentWorkspace" :class="['status-pill', currentWorkspace.deleted ? 'pill-deleted' : 'pill-active']">
            {{ currentWorkspace.deleted ? '已注销' : '活跃' }}
          </span>
        </div>

        <!-- 存储容量水位指示 -->
        <div v-if="currentWorkspace?.folder" class="storage-meter">
          <div class="meter-info">
            <span class="meter-title">容量用量:</span>
            <span class="mono meter-value">{{ formatBytes(currentWorkspace.folder.total_bytes) }}<template v-if="currentWorkspace.quota_bytes != null"> / {{ currentWorkspace.quota_bytes > 0 ? formatBytes(currentWorkspace.quota_bytes) : '不限' }}</template></span>
            <span class="meter-count">({{ currentWorkspace.folder.file_count }} 个文件)</span>
          </div>
          <div v-if="(currentWorkspace.quota_bytes ?? 0) > 0" class="meter-track">
            <div
              class="meter-fill"
              :style="{ width: `${storagePercent}%` }"
              :class="{ 'meter-warning': storagePercent > 80, 'meter-danger': storagePercent > 95 }"
            />
          </div>
        </div>
      </div>

      <div class="header-right">
        <button class="btn btn-sm btn-primary" :disabled="busy" @click="openCreateModal">
          <svg viewBox="0 0 24 24" width="13" height="13" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round">
            <line x1="12" y1="5" x2="12" y2="19" />
            <line x1="5" y1="12" x2="19" y2="12" />
          </svg>
          <span>新建工作区</span>
        </button>
        <template v-if="currentWorkspace && !currentWorkspace.deleted">
          <button class="btn btn-sm" :disabled="busy" @click="openRenameModal(currentWorkspace)">
            工作区改名
          </button>
          <button class="btn btn-sm btn-danger-soft" :disabled="busy" @click="confirmDelete(currentWorkspace)">
            注销
          </button>
        </template>
        <template v-else-if="currentWorkspace && currentWorkspace.deleted">
          <button class="btn btn-sm btn-danger-soft" :disabled="busy" @click="confirmPurge(currentWorkspace)">
            清空并删除
          </button>
        </template>
        <button class="btn btn-sm" :disabled="loading || busy" @click="toggleDeleted">
          {{ showDeleted ? '返回活跃' : '查看已注销' }}
        </button>
        <button class="btn btn-sm" :disabled="loading || busy" title="刷新工作区" @click="refreshAll">
          刷新
        </button>
      </div>
    </div>

    <!-- IDE 主工作台：左侧文件资源管理器 + 右侧多模画布 -->
    <div class="workspace-studio-container">
      <!-- 左侧：文件资源管理器 -->
      <div class="explorer-panel">
        <div class="explorer-header">
          <div class="explorer-title">
            <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2">
              <path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z" />
            </svg>
            <span>文件资源管理器</span>
          </div>
          <div class="explorer-actions">
            <button class="icon-btn" title="新建文件" :disabled="!currentWorkspace || currentWorkspace.deleted" @click="promptCreate('file')">
              <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2">
                <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
                <polyline points="14 2 14 8 20 8" />
                <line x1="12" y1="18" x2="12" y2="12" />
                <line x1="9" y1="15" x2="15" y2="15" />
              </svg>
            </button>
            <button class="icon-btn" title="新建文件夹" :disabled="!currentWorkspace || currentWorkspace.deleted" @click="promptCreate('dir')">
              <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2">
                <path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z" />
                <line x1="12" y1="11" x2="12" y2="17" />
                <line x1="9" y1="14" x2="15" y2="14" />
              </svg>
            </button>
            <button
              class="icon-btn"
              title="上传文件 (支持音视频/图片/文档，可拖拽放入)"
              :disabled="!currentWorkspace || currentWorkspace.deleted || uploading"
              @click="triggerUpload"
            >
              <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" />
                <polyline points="17 8 12 3 7 8" />
                <line x1="12" y1="3" x2="12" y2="15" />
              </svg>
            </button>
            <input
              ref="fileUploadInputRef"
              type="file"
              style="display: none"
              multiple
              @change="handleFileInputChange"
            />
            <button class="icon-btn" title="刷新文件树" :disabled="treeLoading" @click="loadTree">
              <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2">
                <polyline points="23 4 23 10 17 10" />
                <polyline points="1 20 1 14 7 14" />
                <path d="M3.51 9a9 9 0 0 1 14.85-3.36L23 10M1 14l4.64 4.36A9 9 0 0 0 20.49 15" />
              </svg>
            </button>
            <button class="icon-btn" :title="allExpanded ? '全部折叠' : '全部展开'" @click="toggleExpandAll">
              <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2">
                <g v-if="allExpanded">
                  <polyline points="4 14 10 14 10 20" />
                  <polyline points="20 10 14 10 14 4" />
                </g>
                <g v-else>
                  <polyline points="15 3 21 3 21 9" />
                  <polyline points="9 21 3 21 3 15" />
                </g>
              </svg>
            </button>
          </div>
        </div>

        <!-- 快速过滤搜索 -->
        <div class="explorer-filter">
          <input
            v-model="searchKeyword"
            type="text"
            class="filter-input"
            placeholder="过滤文件..."
          />
          <span v-if="searchKeyword" class="clear-search" @click="searchKeyword = ''">✕</span>
        </div>

        <!-- 树形节点列表（支持直接拖拽文件上传） -->
        <div
          class="tree-container"
          :class="{ 'is-dragging-over': isDraggingOver }"
          @dragover.prevent="isDraggingOver = true"
          @dragleave.prevent="isDraggingOver = false"
          @drop.prevent="handleDropUpload"
        >
          <div v-if="uploading" class="tree-loading">正在上传文件…</div>
          <div v-else-if="treeLoading" class="tree-loading">加载文件树…</div>
          <div v-else-if="!fileTree.length" class="tree-empty">暂无文件，点击上方新建或拖拽文件上传。</div>
          <div v-else class="tree-nodes">
            <template v-for="node in filteredTree" :key="node.path">
              <div
                class="tree-node-row"
                :class="{
                  'is-active': activeFile?.path === node.path,
                  'is-dir': node.kind === 'dir',
                }"
                :style="{ paddingLeft: `${node._depth * 16 + 8}px` }"
                @click="handleNodeClick(node)"
              >
                <!-- 目录折叠箭头 -->
                <span
                  v-if="node.kind === 'dir'"
                  class="expand-arrow"
                  :class="{ 'arrow-open': expandedKeys.has(node.path) }"
                  @click.stop="toggleExpand(node.path)"
                >
                  ▶
                </span>
                <span v-else class="arrow-placeholder" />

                <!-- 文件/目录语义化图标 -->
                <span class="file-icon">{{ getFileIcon(node) }}</span>

                <!-- 文件名 -->
                <span class="node-name" :title="node.path">{{ node.name }}</span>

                <!-- 悬浮快捷操作 -->
                <div class="node-hover-actions">
                  <button
                    class="node-act-btn"
                    title="重命名"
                    :disabled="!currentWorkspace || currentWorkspace.deleted"
                    @click.stop="openRenamePathModal(node)"
                  >
                    <svg viewBox="0 0 24 24" width="12" height="12" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                      <path d="M17 3a2.828 2.828 0 1 1 4 4L7.5 20.5 2 22l1.5-5.5L17 3z" />
                    </svg>
                  </button>
                  <button
                    class="node-act-btn btn-del"
                    title="删除"
                    :disabled="!currentWorkspace || currentWorkspace.deleted"
                    @click.stop="confirmDeletePath(node)"
                  >
                    <svg viewBox="0 0 24 24" width="12" height="12" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                      <polyline points="3 6 5 6 21 6" />
                      <path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2" />
                    </svg>
                  </button>
                </div>
              </div>
            </template>
          </div>
        </div>
      </div>

      <!-- 右侧：多模编辑与预览画布 -->
      <div class="canvas-panel">
        <!-- 未打开任何文件时的欢迎空态 -->
        <div v-if="!activeFile" class="canvas-empty-state">
          <div class="empty-hero">
            <div class="hero-logo">
              <svg viewBox="0 0 24 24" width="48" height="48" fill="none" stroke="currentColor" stroke-width="1.5">
                <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
                <polyline points="14 2 14 8 20 8" />
                <line x1="16" y1="13" x2="8" y2="13" />
                <line x1="16" y1="17" x2="8" y2="17" />
                <polyline points="10 9 9 9 8 9" />
              </svg>
            </div>
            <h2 class="hero-title">{{ currentWorkspace?.name || '我的工作区' }}</h2>
            <p class="hero-desc">从左侧文件资源管理器中选择文件进行预览、代码编辑或 Markdown 渲染。</p>

            <div class="hero-shortcuts">
              <div class="shortcut-card">
                <span class="shortcut-key">Ctrl + S</span>
                <span class="shortcut-desc">快捷保存当前修改</span>
              </div>
              <div class="shortcut-card">
                <span class="shortcut-key">媒体预览</span>
                <span class="shortcut-desc">视频倍速播放与原图画廊</span>
              </div>
              <div class="shortcut-card">
                <span class="shortcut-key">分屏对照</span>
                <span class="shortcut-desc">Markdown 实时渲染</span>
              </div>
            </div>

            <div class="quick-create-strip">
              <button class="btn btn-sm" :disabled="!currentWorkspace || currentWorkspace.deleted" @click="quickCreateCode">
                <svg viewBox="0 0 24 24" width="13" height="13" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                  <line x1="12" y1="5" x2="12" y2="19" />
                  <line x1="5" y1="12" x2="19" y2="12" />
                </svg>
                <span>新建 Python 脚本</span>
              </button>
              <button class="btn btn-sm" :disabled="!currentWorkspace || currentWorkspace.deleted" @click="quickCreateMarkdown">
                <svg viewBox="0 0 24 24" width="13" height="13" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                  <line x1="12" y1="5" x2="12" y2="19" />
                  <line x1="5" y1="12" x2="19" y2="12" />
                </svg>
                <span>新建 Markdown 报告</span>
              </button>
            </div>
          </div>
        </div>

        <!-- 已打开文件：顶部工具条 + 专属视图 -->
        <div v-else class="active-file-workspace">
          <!-- 画布顶栏 -->
          <div class="canvas-topbar">
            <div class="topbar-left">
              <span class="file-top-icon">{{ getFileIcon(activeFile) }}</span>
              <span class="file-top-path mono">{{ activeFile.path }}</span>
              <span v-if="isVideo" class="media-badge">视频</span>
              <span v-else-if="isAudio" class="media-badge">音频</span>
              <span v-else-if="isImage" class="media-badge">图片</span>
              <span v-if="isDirty" class="dirty-badge" title="有未保存修改">● 未保存</span>
              <span class="file-size-tag">{{ formatBytes(activeFile.size) }}</span>
            </div>

            <div class="topbar-right">
              <!-- Markdown 专属模式切换 -->
              <div v-if="isMarkdown" class="md-mode-switch">
                <button
                  class="mode-btn"
                  :class="{ 'is-active': mdViewMode === 'split' }"
                  title="分屏对照模式"
                  @click="mdViewMode = 'split'"
                >
                  分屏对照
                </button>
                <button
                  class="mode-btn"
                  :class="{ 'is-active': mdViewMode === 'preview' }"
                  title="纯预览模式"
                  @click="mdViewMode = 'preview'"
                >
                  仅预览
                </button>
                <button
                  class="mode-btn"
                  :class="{ 'is-active': mdViewMode === 'edit' }"
                  title="纯源码编辑"
                  @click="mdViewMode = 'edit'"
                >
                  仅源码
                </button>
              </div>

              <!-- 保存按钮（带 Ctrl+S 提示） -->
              <button
                v-if="!activeFile.is_binary && !isImage && !isVideo && !isAudio"
                class="btn btn-sm"
                :class="isDirty ? 'btn-primary' : ''"
                :disabled="saving || !isDirty || currentWorkspace?.deleted"
                @click="saveCurrentFile"
              >
                <svg v-if="!saving" viewBox="0 0 24 24" width="13" height="13" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                  <path d="M19 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11l5 5v11a2 2 0 0 1-2 2z" />
                  <polyline points="17 21 17 13 7 13 7 21" />
                  <polyline points="7 3 7 8 15 8" />
                </svg>
                <span>{{ saving ? '保存中…' : '保存 (Ctrl+S)' }}</span>
              </button>

              <!-- 下载文件按钮 -->
              <button class="btn btn-sm" title="下载原文件" @click="downloadActiveFile">
                下载
              </button>

              <!-- 关闭按钮 -->
              <button class="close-file-btn" title="关闭" @click="() => closeActiveFile(false)">
                ✕
              </button>
            </div>
          </div>

          <!-- 画布内容区 -->
          <div class="canvas-content-area">
            <div v-if="contentLoading" class="content-loading-mask">加载文件内容…</div>

            <!-- 1. Markdown 视图（支持分屏对照 / 纯预览 / 纯编辑） -->
            <template v-else-if="isMarkdown">
              <div class="markdown-split-layout" :class="`layout-${mdViewMode}`">
                <!-- 左列：源码编辑器 -->
                <div v-show="mdViewMode !== 'preview'" class="md-editor-col">
                  <WorkspaceCodeEditor
                    v-model="editorContent"
                    language="Markdown"
                    :readonly="currentWorkspace?.deleted"
                    @save="saveCurrentFile"
                  />
                </div>
                <!-- 右列：富文本渲染器 -->
                <div v-show="mdViewMode !== 'edit'" class="md-preview-col">
                  <div class="preview-scroll-wrapper">
                    <MarkdownView :content="editorContent || '*(暂无内容)*'" />
                  </div>
                </div>
              </div>
            </template>

            <!-- 2. 视频播放器视图 -->
            <template v-else-if="isVideo">
              <WorkspaceVideoViewer
                v-if="videoStreamUrl"
                :src="videoStreamUrl"
                :file-name="activeFile.name"
                :file-size="activeFile.size"
                :fallback-blob-url="videoBlobUrl"
                @download="downloadActiveFile"
              />
            </template>

            <!-- 3. 图片画廊视图 -->
            <template v-else-if="isImage">
              <WorkspaceImageViewer
                v-if="imageBlobUrl"
                :src="imageBlobUrl"
                :alt="activeFile.name"
                :file-size="activeFile.size"
              />
            </template>

            <!-- 4. 代码/普通文本编辑器 -->
            <template v-else-if="!activeFile.is_binary && !activeFile.is_large">
              <WorkspaceCodeEditor
                v-model="editorContent"
                :language="detectLanguage(activeFile.name)"
                :readonly="currentWorkspace?.deleted"
                @save="saveCurrentFile"
              />
            </template>

            <!-- 4. 二进制或超大文件 -->
            <template v-else>
              <div class="binary-file-card">
                <div class="binary-icon">📦</div>
                <h3>{{ activeFile.name }}</h3>
                <p class="binary-tip">
                  {{ activeFile.is_large ? '该文件大小超出 5MB 在线编辑上限' : '该文件为二进制格式，不支持在线文本编辑' }}
                </p>
                <div class="binary-meta">
                  <span>文件大小: {{ formatBytes(activeFile.size) }}</span>
                  <span v-if="activeFile.updated_at">修改时间: {{ formatDateTime(activeFile.updated_at, '—') }}</span>
                </div>
                <button class="btn btn-primary" @click="downloadActiveFile">下载到本地查看</button>
              </div>
            </template>
          </div>
        </div>
      </div>
    </div>

    <!-- 弹窗 1：新建工作区 -->
    <div v-if="showCreateWsModal" class="modal-backdrop" @click.self="showCreateWsModal = false">
      <div class="modal-card">
        <h3 class="modal-title">新建工作区</h3>
        <p class="modal-subtitle">创建新的自管沙箱数据目录，支持会话独立绑定与读写。</p>
        <div class="form-group">
          <label>工作区名称</label>
          <input
            v-model="newWsName"
            class="input modal-input"
            placeholder="例如：大模型评测主库"
            autofocus
            @keyup.enter="submitCreateWorkspace"
          />
        </div>
        <div class="modal-actions">
          <button class="btn" :disabled="busy" @click="showCreateWsModal = false">取消</button>
          <button class="btn btn-primary" :disabled="busy || !newWsName.trim()" @click="submitCreateWorkspace">
            立即创建
          </button>
        </div>
      </div>
    </div>

    <!-- 弹窗 2：重命名工作区 -->
    <div v-if="showRenameWsModal" class="modal-backdrop" @click.self="showRenameWsModal = false">
      <div class="modal-card">
        <h3 class="modal-title">重命名工作区</h3>
        <div class="form-group">
          <label>新名称</label>
          <input
            v-model="renameWsValue"
            class="input modal-input"
            autofocus
            @keyup.enter="submitRenameWorkspace"
          />
        </div>
        <div class="modal-actions">
          <button class="btn" :disabled="busy" @click="showRenameWsModal = false">取消</button>
          <button class="btn btn-primary" :disabled="busy || !renameWsValue.trim()" @click="submitRenameWorkspace">
            保存
          </button>
        </div>
      </div>
    </div>

    <!-- 弹窗 3：新建文件 / 文件夹 -->
    <div v-if="showCreateItemModal" class="modal-backdrop" @click.self="showCreateItemModal = false">
      <div class="modal-card">
        <h3 class="modal-title">{{ createItemType === 'file' ? '新建文件' : '新建文件夹' }}</h3>
        <p class="modal-subtitle">所在父目录: /{{ createItemParentPath || '(根目录)' }}</p>
        <div class="form-group">
          <label>{{ createItemType === 'file' ? '文件名 (可包含后缀，如 report.md)' : '文件夹名' }}</label>
          <input
            v-model="createItemName"
            class="input modal-input"
            :placeholder="createItemType === 'file' ? 'main.py / README.md' : 'assets / docs'"
            autofocus
            @keyup.enter="submitCreateItem"
          />
        </div>
        <div class="modal-actions">
          <button class="btn" :disabled="busy" @click="showCreateItemModal = false">取消</button>
          <button class="btn btn-primary" :disabled="busy || !createItemName.trim()" @click="submitCreateItem">
            确定创建
          </button>
        </div>
      </div>
    </div>

    <!-- 弹窗 4：重命名路径（文件/文件夹） -->
    <div v-if="showRenamePathModal" class="modal-backdrop" @click.self="showRenamePathModal = false">
      <div class="modal-card">
        <h3 class="modal-title">重命名 {{ renamingTargetNode?.kind === 'dir' ? '文件夹' : '文件' }}</h3>
        <div class="form-group">
          <label>新名称</label>
          <input
            v-model="renamePathValue"
            class="input modal-input"
            autofocus
            @keyup.enter="submitRenamePath"
          />
        </div>
        <div class="modal-actions">
          <button class="btn" :disabled="busy" @click="showRenamePathModal = false">取消</button>
          <button class="btn btn-primary" :disabled="busy || !renamePathValue.trim()" @click="submitRenamePath">
            确认修改
          </button>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, onBeforeUnmount, ref } from 'vue'
import { useDialog, useMessage } from 'naive-ui'
import { api } from '../api/http'
import type {
  UserWorkspace,
  UserWorkspaceTreeNode,
  UserWorkspaceFileContent,
} from '../api/types'
import MarkdownView from '../components/agent/MarkdownView.vue'
import WorkspaceCodeEditor from '../components/workspace/WorkspaceCodeEditor.vue'
import WorkspaceImageViewer from '../components/workspace/WorkspaceImageViewer.vue'
import WorkspaceVideoViewer from '../components/workspace/WorkspaceVideoViewer.vue'
import { formatBytes, formatDateTime } from '../utils/format'

interface FlattenedNode extends UserWorkspaceTreeNode {
  _depth: number
}

const message = useMessage()
const dialog = useDialog()

// 状态：工作区
const items = ref<UserWorkspace[]>([])
const selectedWorkspaceId = ref<string>('')
const loading = ref(false)
const busy = ref(false)
const showDeleted = ref(false)

// 文件上传相关状态
const fileUploadInputRef = ref<HTMLInputElement | null>(null)
const uploading = ref(false)
const isDraggingOver = ref(false)

// 工作区弹窗
const showCreateWsModal = ref(false)
const newWsName = ref('')
const showRenameWsModal = ref(false)
const renameWsValue = ref('')
const wsToRename = ref<UserWorkspace | null>(null)

// 状态：文件树
const rawTree = ref<UserWorkspaceTreeNode[]>([])
const treeLoading = ref(false)
const expandedKeys = ref<Set<string>>(new Set())
const searchKeyword = ref('')
const allExpanded = ref(false)

// 新建/重命名文件弹窗
const showCreateItemModal = ref(false)
const createItemType = ref<'file' | 'dir'>('file')
const createItemParentPath = ref('')
const createItemName = ref('')

const showRenamePathModal = ref(false)
const renamingTargetNode = ref<UserWorkspaceTreeNode | null>(null)
const renamePathValue = ref('')

// 状态：右侧活动文件
const activeFile = ref<UserWorkspaceFileContent | null>(null)
const editorContent = ref('')
const initialContent = ref('')
const contentLoading = ref(false)
const saving = ref(false)
const imageBlobUrl = ref<string | null>(null)
const videoStreamUrl = ref<string | null>(null)
const videoBlobUrl = ref<string | null>(null)
const mdViewMode = ref<'split' | 'preview' | 'edit'>('split')
// 请求序号在切换、关闭和卸载时失效，迟到响应不得恢复旧文件或 Blob。
let fileRequestId = 0
let treeRequestId = 0

const currentWorkspace = computed(() => {
  return items.value.find((w) => w.id === selectedWorkspaceId.value) || items.value[0] || null
})

const storagePercent = computed(() => {
  const bytes = currentWorkspace.value?.folder?.total_bytes ?? 0
  const maxBytes = currentWorkspace.value?.quota_bytes ?? 0
  return maxBytes > 0 ? Math.min(100, Math.round((bytes / maxBytes) * 100)) : 0
})

const isDirty = computed(() => {
  if (!activeFile.value || activeFile.value.is_binary || isImage.value || isVideo.value || isAudio.value) return false
  return editorContent.value !== initialContent.value
})

const isMarkdown = computed(() => {
  if (!activeFile.value) return false
  return activeFile.value.name.toLowerCase().endsWith('.md')
})

const isImage = computed(() => {
  if (!activeFile.value) return false
  const ext = activeFile.value.name.toLowerCase().split('.').pop() || ''
  return ['png', 'jpg', 'jpeg', 'svg', 'gif', 'webp', 'ico'].includes(ext)
})

const isVideo = computed(() => {
  if (!activeFile.value) return false
  const ext = activeFile.value.name.toLowerCase().split('.').pop() || ''
  return ['mp4', 'webm', 'ogg', 'mov', 'm4v', 'mkv', 'avi', 'flv', 'wmv'].includes(ext)
})

const isAudio = computed(() => {
  if (!activeFile.value) return false
  const ext = activeFile.value.name.toLowerCase().split('.').pop() || ''
  return ['mp3', 'wav', 'aac', 'flac', 'm4a', 'weba'].includes(ext)
})

// 平铺展开后的树节点，支持折叠控制与关键字检索
const fileTree = computed(() => rawTree.value)

const filteredTree = computed<FlattenedNode[]>(() => {
  const result: FlattenedNode[] = []
  const kw = searchKeyword.value.trim().toLowerCase()

  function traverse(nodes: UserWorkspaceTreeNode[], depth = 0): void {
    for (const node of nodes) {
      const matchName = !kw || node.name.toLowerCase().includes(kw)
      if (matchName || node.kind === 'dir') {
        result.push({ ...node, _depth: depth })
      }
      if (node.kind === 'dir' && node.children && (expandedKeys.value.has(node.path) || kw)) {
        traverse(node.children, depth + 1)
      }
    }
  }

  traverse(rawTree.value, 0)
  return result
})

function getFileIcon(node: { name: string; kind?: 'dir' | 'file' | 'link' }): string {
  if (node.kind === 'dir') {
    return '📁'
  }
  if (node.kind === 'link') {
    return '🔗'
  }
  const name = node.name.toLowerCase()
  if (name.endsWith('.md')) return '📝'
  if (name.endsWith('.py')) return '🐍'
  if (name.endsWith('.ts') || name.endsWith('.js')) return '📜'
  if (name.endsWith('.vue')) return '🟩'
  if (name.endsWith('.json')) return '📦'
  if (name.endsWith('.html')) return '🌐'
  if (name.endsWith('.css') || name.endsWith('.scss')) return '🎨'
  if (name.endsWith('.sh') || name.endsWith('.bash')) return '🐚'
  if (name.endsWith('.yaml') || name.endsWith('.yml') || name.endsWith('.toml')) return '⚙️'
  if (['png', 'jpg', 'jpeg', 'gif', 'svg', 'webp', 'ico'].some((ext) => name.endsWith('.' + ext))) return '🖼️'
  if (['mp4', 'webm', 'ogg', 'mov', 'm4v', 'mkv', 'avi', 'flv', 'wmv'].some((ext) => name.endsWith('.' + ext))) return '🎬'
  if (['mp3', 'wav', 'aac', 'flac', 'm4a', 'weba'].some((ext) => name.endsWith('.' + ext))) return '🎵'
  if (['zip', 'tar', 'gz', '7z', 'rar'].some((ext) => name.endsWith('.' + ext))) return '🗜️'
  if (['csv', 'tsv', 'xlsx', 'xls'].some((ext) => name.endsWith('.' + ext))) return '📊'
  if (name.endsWith('.pdf')) return '📕'
  return '📄'
}

function detectLanguage(name: string): string {
  const ext = name.toLowerCase().split('.').pop() || ''
  const map: Record<string, string> = {
    py: 'Python',
    ts: 'TypeScript',
    js: 'JavaScript',
    vue: 'Vue',
    json: 'JSON',
    html: 'HTML',
    css: 'CSS',
    md: 'Markdown',
    sh: 'Shell',
    bash: 'Shell',
    yml: 'YAML',
    yaml: 'YAML',
    sql: 'SQL',
    txt: 'Plain Text',
  }
  return map[ext] || 'Text'
}

// 加载工作区列表
async function loadWorkspaces(preferredId?: string): Promise<void> {
  loading.value = true
  try {
    const data = await api.workspaces.list({ include_deleted: showDeleted.value })
    items.value = data.items
    if (items.value.length > 0) {
      if (preferredId && items.value.some((w) => w.id === preferredId)) {
        if (preferredId !== selectedWorkspaceId.value) closeActiveFile(true)
        selectedWorkspaceId.value = preferredId
      } else if (!items.value.some((w) => w.id === selectedWorkspaceId.value)) {
        closeActiveFile(true)
        selectedWorkspaceId.value = items.value[0].id
      }
      await loadTree()
    } else {
      selectedWorkspaceId.value = ''
      rawTree.value = []
      closeActiveFile(true)
    }
  } catch (e) {
    message.error(e instanceof Error ? e.message : '工作区加载失败')
  } finally {
    loading.value = false
  }
}

async function handleWorkspaceChange(event: Event): Promise<void> {
  // 原生 select 先改变 DOM 值；确认前立即还原，模型和文件归属保持一致。
  const select = event.target as HTMLSelectElement
  const nextId = select.value
  select.value = selectedWorkspaceId.value
  if (nextId === selectedWorkspaceId.value) return
  const applyChange = async () => {
    closeActiveFile(true)
    selectedWorkspaceId.value = nextId
    rawTree.value = []
    expandedKeys.value.clear()
    await loadTree()
  }
  if (isDirty.value) {
    dialog.warning({
      title: '未保存修改',
      content: '当前文件尚未保存，切换工作区将放弃修改，是否继续？',
      positiveText: '放弃修改并切换',
      negativeText: '留在当前',
      onPositiveClick: applyChange,
    })
    return
  }
  await applyChange()
}

// 加载文件树
async function loadTree(): Promise<void> {
  if (!selectedWorkspaceId.value) return
  const workspaceId = selectedWorkspaceId.value
  const requestId = ++treeRequestId
  treeLoading.value = true
  try {
    const res = await api.workspaces.getTree(workspaceId)
    if (requestId !== treeRequestId || workspaceId !== selectedWorkspaceId.value) return
    rawTree.value = res.tree || []
    // 默认展开一级目录
    for (const node of rawTree.value) {
      if (node.kind === 'dir') {
        expandedKeys.value.add(node.path)
      }
    }
  } catch (e) {
    if (requestId === treeRequestId && workspaceId === selectedWorkspaceId.value) {
      message.error(e instanceof Error ? e.message : '获取文件目录树失败')
    }
  } finally {
    if (requestId === treeRequestId) treeLoading.value = false
  }
}

function toggleExpand(path: string): void {
  if (expandedKeys.value.has(path)) {
    expandedKeys.value.delete(path)
  } else {
    expandedKeys.value.add(path)
  }
}

function toggleExpandAll(): void {
  if (allExpanded.value) {
    expandedKeys.value.clear()
    allExpanded.value = false
  } else {
    function addAll(nodes: UserWorkspaceTreeNode[]): void {
      for (const n of nodes) {
        if (n.kind === 'dir') {
          expandedKeys.value.add(n.path)
          if (n.children) addAll(n.children)
        }
      }
    }
    addAll(rawTree.value)
    allExpanded.value = true
  }
}

// 点击文件/目录
async function handleNodeClick(node: UserWorkspaceTreeNode): Promise<void> {
  if (node.kind === 'dir') {
    toggleExpand(node.path)
    return
  }

  if (activeFile.value?.path === node.path) return

  if (isDirty.value) {
    dialog.warning({
      title: '未保存修改',
      content: '当前文件尚未保存，切换文件将放弃修改，是否继续？',
      positiveText: '放弃并打开新文件',
      negativeText: '取消',
      onPositiveClick: async () => {
        await openFile(node.path)
      },
    })
    return
  }

  await openFile(node.path)
}

// 打开文件
async function openFile(relPath: string): Promise<void> {
  if (!selectedWorkspaceId.value) return
  const workspaceId = selectedWorkspaceId.value
  const requestId = ++fileRequestId
  const isCurrent = () => requestId === fileRequestId && workspaceId === selectedWorkspaceId.value
  contentLoading.value = true
  // 清理之前的图片与视频 blob 资源
  if (imageBlobUrl.value) {
    URL.revokeObjectURL(imageBlobUrl.value)
    imageBlobUrl.value = null
  }
  if (videoBlobUrl.value) {
    URL.revokeObjectURL(videoBlobUrl.value)
    videoBlobUrl.value = null
  }
  videoStreamUrl.value = null

  try {
    const data = await api.workspaces.getFileContent(workspaceId, relPath)
    if (!isCurrent()) return
    activeFile.value = data
    editorContent.value = data.content || ''
    initialContent.value = data.content || ''

    const ext = data.name.toLowerCase().split('.').pop() || ''
    // 如果是图片，加载二进制 blob
    if (['png', 'jpg', 'jpeg', 'svg', 'gif', 'webp', 'ico'].includes(ext)) {
      try {
        const blob = await api.workspaces.getRawBlob(workspaceId, relPath)
        if (!isCurrent()) return
        imageBlobUrl.value = URL.createObjectURL(blob)
      } catch {
        if (isCurrent()) message.warning('图片流加载失败')
      }
    } else if (['mp4', 'webm', 'ogg', 'mov', 'm4v', 'mkv', 'avi', 'flv', 'wmv'].includes(ext)) {
      // 视频文件：直接使用后端流 URL，利用 HTTP 206 Range 支持分段秒开
      videoStreamUrl.value = api.workspaces.getRawFileUrl(workspaceId, relPath, false)
      // 如果视频小于 50MB，后台预取 Blob 作为兼容容错备用
      if (data.size && data.size <= 50 * 1024 * 1024) {
        api.workspaces.getRawBlob(workspaceId, relPath).then((blob) => {
          if (!isCurrent()) return
          videoBlobUrl.value = URL.createObjectURL(blob)
        }).catch(() => {
          // 忽略预取失败
        })
      }
    }
  } catch (e) {
    if (isCurrent()) message.error(e instanceof Error ? e.message : '打开文件失败')
  } finally {
    if (isCurrent()) contentLoading.value = false
  }
}

// 保存当前文件
async function saveCurrentFile(): Promise<void> {
  if (!selectedWorkspaceId.value || !activeFile.value) return
  if (!isDirty.value || saving.value) return
  const workspaceId = selectedWorkspaceId.value
  const file = activeFile.value
  const content = editorContent.value
  saving.value = true
  try {
    await api.workspaces.saveFileContent(workspaceId, file.path, content)
    // 只确认实际提交的快照，保存期间继续输入的内容仍保持未保存状态。
    if (workspaceId === selectedWorkspaceId.value && activeFile.value === file) {
      initialContent.value = content
      file.size = new Blob([content]).size
    }
    message.success('已保存')
  } catch (e) {
    message.error(e instanceof Error ? e.message : '保存失败')
  } finally {
    saving.value = false
  }
}

// 关闭当前文件
function closeActiveFile(force = false): void {
  if (!force && isDirty.value) {
    dialog.warning({
      title: '未保存修改',
      content: '当前文件存在未保存的修改，关闭将丢失内容，是否继续？',
      positiveText: '放弃修改并关闭',
      negativeText: '取消',
      onPositiveClick: () => {
        closeActiveFile(true)
      },
    })
    return
  }
  ++fileRequestId
  contentLoading.value = false
  if (imageBlobUrl.value) {
    URL.revokeObjectURL(imageBlobUrl.value)
    imageBlobUrl.value = null
  }
  if (videoBlobUrl.value) {
    URL.revokeObjectURL(videoBlobUrl.value)
    videoBlobUrl.value = null
  }
  videoStreamUrl.value = null
  activeFile.value = null
  editorContent.value = ''
  initialContent.value = ''
}

// 下载当前文件
async function downloadActiveFile(): Promise<void> {
  if (!selectedWorkspaceId.value || !activeFile.value) return
  // 交给浏览器流式下载，避免大视频在前端重复占用整个文件大小的内存。
  const link = document.createElement('a')
  link.href = api.workspaces.getRawFileUrl(selectedWorkspaceId.value, activeFile.value.path, true)
  link.download = activeFile.value.name
  link.click()
}

// 快捷键监听
function handleGlobalKeydown(e: KeyboardEvent): void {
  if ((e.ctrlKey || e.metaKey) && (e.key === 's' || e.key === 'S')) {
    e.preventDefault()
    if (activeFile.value && !activeFile.value.is_binary && !isImage.value && !isVideo.value) {
      void saveCurrentFile()
    }
  }
}

// 文件上传
function triggerUpload(): void {
  if (fileUploadInputRef.value) {
    fileUploadInputRef.value.value = ''
    fileUploadInputRef.value.click()
  }
}

async function handleFileInputChange(e: Event): Promise<void> {
  const input = e.target as HTMLInputElement
  if (!input.files || input.files.length === 0 || !selectedWorkspaceId.value) return
  await uploadFilesList(Array.from(input.files))
}

async function handleDropUpload(e: DragEvent): Promise<void> {
  isDraggingOver.value = false
  if (!selectedWorkspaceId.value || !e.dataTransfer?.files?.length) return
  await uploadFilesList(Array.from(e.dataTransfer.files))
}

async function uploadFilesList(files: File[]): Promise<void> {
  if (!selectedWorkspaceId.value || files.length === 0 || uploading.value || currentWorkspace.value?.deleted) return
  const workspaceId = selectedWorkspaceId.value
  uploading.value = true
  let successCount = 0
  try {
    for (const file of files) {
      try {
        await api.workspaces.uploadFile(workspaceId, '', file)
        successCount++
      } catch (err: any) {
        message.error(`文件 ${file.name} 上传失败: ${err.message || '未知错误'}`)
      }
    }
    if (successCount > 0) {
      message.success(`成功上传 ${successCount} 个文件`)
      if (selectedWorkspaceId.value !== workspaceId) return
      await loadWorkspaces(workspaceId)
      if (selectedWorkspaceId.value === workspaceId && files.length === 1 && successCount === 1 && !isDirty.value) {
        await openFile(files[0].name)
      }
    }
  } finally {
    uploading.value = false
  }
}

// 新建文件/文件夹
function promptCreate(type: 'file' | 'dir'): void {
  createItemType.value = type
  createItemParentPath.value = ''
  createItemName.value = ''
  showCreateItemModal.value = true
}

async function submitCreateItem(): Promise<void> {
  const name = createItemName.value.trim()
  if (!name || !selectedWorkspaceId.value) return
  busy.value = true
  try {
    if (createItemType.value === 'file') {
      const res = await api.workspaces.createFile(selectedWorkspaceId.value, createItemParentPath.value, name, '')
      message.success(`文件 ${res.name} 已创建`)
      showCreateItemModal.value = false
      await loadTree()
      await openFile(res.path)
    } else {
      await api.workspaces.createFolder(selectedWorkspaceId.value, createItemParentPath.value, name)
      message.success('文件夹已创建')
      showCreateItemModal.value = false
      await loadTree()
    }
  } catch (e) {
    message.error(e instanceof Error ? e.message : '创建失败')
  } finally {
    busy.value = false
  }
}

function quickCreateCode(): void {
  createItemType.value = 'file'
  createItemParentPath.value = ''
  createItemName.value = 'script.py'
  showCreateItemModal.value = true
}

function quickCreateMarkdown(): void {
  createItemType.value = 'file'
  createItemParentPath.value = ''
  createItemName.value = 'report.md'
  showCreateItemModal.value = true
}

// 重命名文件/目录
function openRenamePathModal(node: UserWorkspaceTreeNode): void {
  renamingTargetNode.value = node
  renamePathValue.value = node.name
  showRenamePathModal.value = true
}

async function submitRenamePath(): Promise<void> {
  const newName = renamePathValue.value.trim()
  if (!newName || !renamingTargetNode.value || !selectedWorkspaceId.value) return
  busy.value = true
  try {
    const res = await api.workspaces.renamePath(selectedWorkspaceId.value, renamingTargetNode.value.path, newName)
    message.success('已重命名')
    showRenamePathModal.value = false
    // 若当前正在查看该文件，更新路径
    if (activeFile.value?.path === renamingTargetNode.value.path) {
      activeFile.value.path = res.new_path
      activeFile.value.name = res.name
    }
    await loadTree()
  } catch (e) {
    message.error(e instanceof Error ? e.message : '重命名失败')
  } finally {
    busy.value = false
  }
}

// 删除文件/目录
function confirmDeletePath(node: UserWorkspaceTreeNode): void {
  const isDir = node.kind === 'dir'
  dialog.warning({
    title: `确认删除「${node.name}」？`,
    content: isDir
      ? '此操作将递归删除该文件夹下所有文件，数据不可恢复！'
      : '删除后文件将无法恢复，是否确定删除？',
    positiveText: '确定删除',
    negativeText: '取消',
    onPositiveClick: async () => {
      try {
        await api.workspaces.deletePath(selectedWorkspaceId.value, node.path)
        message.success('已删除')
        if (activeFile.value?.path === node.path) {
          closeActiveFile(true)
        }
        await loadTree()
      } catch (e) {
        message.error(e instanceof Error ? e.message : '删除失败')
      }
    },
  })
}

// 工作区管理
function openCreateModal(): void {
  newWsName.value = ''
  showCreateWsModal.value = true
}

async function submitCreateWorkspace(): Promise<void> {
  const name = newWsName.value.trim()
  if (!name) return
  busy.value = true
  try {
    const created = await api.workspaces.create(name)
    message.success('工作区已创建')
    showCreateWsModal.value = false
    await loadWorkspaces(created.id)
  } catch (e) {
    message.error(e instanceof Error ? e.message : '创建工作区失败')
  } finally {
    busy.value = false
  }
}

function openRenameModal(ws: UserWorkspace): void {
  wsToRename.value = ws
  renameWsValue.value = ws.name
  showRenameWsModal.value = true
}

async function submitRenameWorkspace(): Promise<void> {
  const name = renameWsValue.value.trim()
  if (!name || !wsToRename.value) return
  busy.value = true
  try {
    await api.workspaces.rename(wsToRename.value.id, name)
    message.success('工作区名称已修改')
    showRenameWsModal.value = false
    await loadWorkspaces(wsToRename.value.id)
  } catch (e) {
    message.error(e instanceof Error ? e.message : '修改失败')
  } finally {
    busy.value = false
  }
}

function confirmDelete(ws: UserWorkspace): void {
  dialog.warning({
    title: `注销工作区「${ws.name}」？`,
    content: '注销后工作区文件安全保留在存储卷中，绑定会话将停止访问该数据域。',
    positiveText: '注销',
    negativeText: '取消',
    onPositiveClick: async () => {
      try {
        await api.workspaces.remove(ws.id, false)
        message.success('工作区已注销')
        await loadWorkspaces()
      } catch (e) {
        message.error(e instanceof Error ? e.message : '注销失败')
      }
    },
  })
}

function confirmPurge(ws: UserWorkspace): void {
  dialog.warning({
    title: `清空并删除「${ws.name}」？`,
    content: '将解除全部会话绑定并永久物理删除文件目录，数据不可恢复！',
    positiveText: '永久删除',
    negativeText: '取消',
    onPositiveClick: async () => {
      try {
        await api.workspaces.remove(ws.id, true)
        message.success('已清空并物理删除')
        await loadWorkspaces()
      } catch (e) {
        message.error(e instanceof Error ? e.message : '删除失败')
      }
    },
  })
}

function toggleDeleted(): void {
  showDeleted.value = !showDeleted.value
  void loadWorkspaces()
}

async function refreshAll(): Promise<void> {
  await loadWorkspaces(selectedWorkspaceId.value)
  if (activeFile.value) {
    await openFile(activeFile.value.path)
  }
}

onMounted(() => {
  void loadWorkspaces()
})

onBeforeUnmount(() => {
  ++treeRequestId
  closeActiveFile(true)
})
</script>

<style scoped>
.user-workspaces-page {
  display: flex;
  flex-direction: column;
  height: 100%;
  min-height: 0;
  gap: 12px;
  box-sizing: border-box;
}

/* 按钮基础风格 */
.btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  border-radius: 8px;
  font-size: 13px;
  font-weight: 500;
  cursor: pointer;
  transition: all 0.15s ease;
  border: 1px solid var(--border-subtle, #e5e7eb);
  background: var(--bg-main, #ffffff);
  color: var(--text-primary, #111827);
  padding: 5px 12px;
  white-space: nowrap;
}

.btn:hover:not(:disabled) {
  background: var(--row-hover, rgba(17, 24, 39, 0.04));
  border-color: var(--text-tertiary, #9ca3af);
  color: var(--text-primary, #111827);
}

.btn:disabled {
  opacity: 0.45;
  cursor: not-allowed;
}

.btn-primary {
  background: #1f5947;
  color: #ffffff;
  border-color: #1f5947;
}

.btn-primary:hover:not(:disabled) {
  background: #174a3a;
  border-color: #174a3a;
  color: #ffffff;
}

[data-theme='dark'] .btn-primary {
  background: #16977a;
  border-color: #16977a;
  color: #ffffff;
}

[data-theme='dark'] .btn-primary:hover:not(:disabled) {
  background: #148369;
  border-color: #148369;
}

.btn-danger-soft {
  background: rgba(239, 68, 68, 0.06);
  color: var(--accent-error, #ef4444);
  border-color: rgba(239, 68, 68, 0.25);
}

.btn-danger-soft:hover:not(:disabled) {
  background: rgba(239, 68, 68, 0.12);
  border-color: var(--accent-error, #ef4444);
}

.btn-icon {
  font-weight: 700;
  margin-right: 2px;
}

/* 顶部状态与控制栏 */
.workspace-header-bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 8px 16px;
  background: var(--bg-main, #ffffff);
  border: 1px solid var(--border-subtle, #e5e7eb);
  border-radius: 12px;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.03);
  gap: 16px;
  flex-wrap: wrap;
}

.header-left {
  display: flex;
  align-items: center;
  gap: 20px;
  flex-wrap: wrap;
}

.workspace-selector-group {
  display: flex;
  align-items: center;
  gap: 8px;
}

.selector-label {
  font-size: 13px;
  font-weight: 500;
  color: var(--text-secondary, #4b5563);
}

.workspace-select {
  padding: 5px 12px;
  border-radius: 8px;
  background: var(--bg-elevated, #f4f8f8);
  border: 1px solid var(--border-subtle, #e5e7eb);
  color: var(--text-primary, #111827);
  font-size: 13px;
  font-weight: 500;
  outline: none;
  cursor: pointer;
  transition: border-color 0.15s ease, box-shadow 0.15s ease;
}

.workspace-select:focus {
  border-color: #1f5947;
  box-shadow: 0 0 0 2.5px rgba(31, 89, 71, 0.16);
}

[data-theme='dark'] .workspace-select:focus {
  border-color: #16977a;
  box-shadow: 0 0 0 2.5px rgba(22, 151, 122, 0.25);
}

.status-pill {
  padding: 2px 8px;
  border-radius: 999px;
  font-size: 11px;
  font-weight: 600;
}

.pill-active {
  background: var(--t-cases, #d1fae5);
  color: var(--c-cases, #047857);
  border: 1px solid rgba(16, 185, 129, 0.25);
}

.pill-deleted {
  background: #fef3c7;
  color: #b45309;
  border: 1px solid rgba(245, 158, 11, 0.3);
}

.storage-meter {
  display: flex;
  flex-direction: column;
  gap: 4px;
  min-width: 200px;
}

.meter-info {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 12px;
}

.meter-title {
  color: var(--text-tertiary, #9ca3af);
}

.meter-value {
  color: var(--text-primary, #111827);
  font-weight: 600;
}

.meter-count {
  color: var(--text-tertiary, #9ca3af);
  font-size: 11px;
}

.meter-track {
  width: 100%;
  height: 6px;
  background: var(--border-subtle, #e5e7eb);
  border-radius: 999px;
  overflow: hidden;
}

.meter-fill {
  height: 100%;
  background: var(--accent-success, #10b981);
  border-radius: 999px;
  transition: width 0.3s ease;
}

.meter-warning {
  background: var(--accent-warning, #f59e0b);
}

.meter-danger {
  background: var(--accent-error, #ef4444);
}

.header-right {
  display: flex;
  align-items: center;
  gap: 8px;
}

/* IDE 主工作台 */
.workspace-studio-container {
  display: flex;
  flex: 1;
  gap: 12px;
  min-height: 0;
  overflow: hidden;
}

/* 左侧文件管理器 */
.explorer-panel {
  width: 280px;
  min-width: 240px;
  display: flex;
  flex-direction: column;
  background: var(--bg-elevated, #f4f8f8);
  border: 1px solid var(--border-subtle, #e5e7eb);
  border-radius: 12px;
  overflow: hidden;
}

.explorer-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 10px 14px;
  background: var(--bg-main, #ffffff);
  border-bottom: 1px solid var(--border-subtle, #e5e7eb);
  user-select: none;
}

.explorer-title {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 13.5px;
  font-weight: 600;
  color: var(--text-primary, #111827);
}

.explorer-title svg {
  color: #1f5947;
}

[data-theme='dark'] .explorer-title svg {
  color: #34d399;
}

.explorer-actions {
  display: flex;
  align-items: center;
  gap: 4px;
}

.icon-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 26px;
  height: 26px;
  border-radius: 6px;
  border: none;
  background: transparent;
  color: var(--text-secondary, #4b5563);
  cursor: pointer;
  transition: all 0.15s ease;
}

.icon-btn:hover:not(:disabled) {
  background: var(--row-hover, rgba(17, 24, 39, 0.05));
  color: #1f5947;
}

[data-theme='dark'] .icon-btn:hover:not(:disabled) {
  color: #34d399;
}

.icon-btn:disabled {
  opacity: 0.35;
  cursor: not-allowed;
}

.explorer-filter {
  position: relative;
  padding: 8px 12px;
  background: var(--bg-elevated, #f4f8f8);
  border-bottom: 1px solid var(--border-subtle, #e5e7eb);
}

.filter-input {
  width: 100%;
  padding: 6px 10px;
  border-radius: 6px;
  background: var(--bg-main, #ffffff);
  border: 1px solid var(--border-subtle, #e5e7eb);
  color: var(--text-primary, #111827);
  font-size: 12.5px;
  outline: none;
  box-sizing: border-box;
  transition: border-color 0.15s ease, box-shadow 0.15s ease;
}

.filter-input:focus {
  border-color: #1f5947;
  box-shadow: 0 0 0 2px rgba(31, 89, 71, 0.16);
}

[data-theme='dark'] .filter-input:focus {
  border-color: #16977a;
  box-shadow: 0 0 0 2px rgba(22, 151, 122, 0.25);
}

.filter-input::placeholder {
  color: var(--text-tertiary, #9ca3af);
}

.clear-search {
  position: absolute;
  right: 20px;
  top: 13px;
  cursor: pointer;
  font-size: 12px;
  color: var(--text-tertiary, #9ca3af);
}

.clear-search:hover {
  color: var(--text-primary, #111827);
}

.tree-container {
  flex: 1;
  overflow-y: auto;
  padding: 6px 0;
  transition: background 0.15s ease, box-shadow 0.15s ease;
}

.tree-container.is-dragging-over {
  background: rgba(31, 89, 71, 0.08);
  box-shadow: inset 0 0 0 2px #1f5947;
}

[data-theme='dark'] .tree-container.is-dragging-over {
  background: rgba(16, 185, 129, 0.12);
  box-shadow: inset 0 0 0 2px #10b981;
}

.tree-loading,
.tree-empty {
  padding: 32px 16px;
  text-align: center;
  color: var(--text-tertiary, #9ca3af);
  font-size: 13px;
}

.tree-node-row {
  display: flex;
  align-items: center;
  height: 30px;
  cursor: pointer;
  font-size: 13px;
  color: var(--text-secondary, #4b5563);
  user-select: none;
  position: relative;
  transition: background 0.12s ease, color 0.12s ease;
}

.tree-node-row:hover {
  background: var(--row-hover, rgba(17, 24, 39, 0.04));
  color: var(--text-primary, #111827);
}

.tree-node-row.is-active {
  background: #e6f1ec;
  color: #1f5947;
  font-weight: 600;
  box-shadow: inset 3px 0 0 #1f5947;
}

[data-theme='dark'] .tree-node-row.is-active {
  background: rgba(22, 151, 122, 0.16);
  color: #34d399;
  box-shadow: inset 3px 0 0 #34d399;
}

.expand-arrow {
  width: 16px;
  height: 16px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  font-size: 9px;
  color: var(--text-tertiary, #9ca3af);
  transition: transform 0.15s ease;
}

.arrow-open {
  transform: rotate(90deg);
}

.arrow-placeholder {
  width: 16px;
}

.file-icon {
  margin: 0 6px 0 2px;
  font-size: 14px;
}

.node-name {
  flex: 1;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  font-family: var(--font-mono, monospace);
  font-size: 12.5px;
}

.node-hover-actions {
  display: none;
  align-items: center;
  gap: 2px;
  padding-right: 8px;
}

.tree-node-row:hover .node-hover-actions {
  display: flex;
}

.node-act-btn {
  background: transparent;
  border: none;
  cursor: pointer;
  font-size: 12px;
  padding: 2px 4px;
  border-radius: 4px;
  opacity: 0.75;
  transition: all 0.12s ease;
}

.node-act-btn:hover {
  opacity: 1;
  background: rgba(17, 24, 39, 0.08);
}

.btn-del:hover {
  background: rgba(239, 68, 68, 0.12);
}

/* 右侧画布 */
.canvas-panel {
  flex: 1;
  display: flex;
  flex-direction: column;
  background: var(--bg-main, #ffffff);
  border: 1px solid var(--border-subtle, #e5e7eb);
  border-radius: 12px;
  overflow: hidden;
  min-width: 0;
}

/* 欢迎空态 */
.canvas-empty-state {
  flex: 1;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 40px 20px;
}

.empty-hero {
  max-width: 560px;
  text-align: center;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 16px;
}

.hero-logo {
  color: #1f5947;
  background: #e6f1ec;
  padding: 18px;
  border-radius: 20px;
  display: inline-flex;
}

[data-theme='dark'] .hero-logo {
  color: #34d399;
  background: rgba(22, 151, 122, 0.16);
}

.hero-title {
  margin: 0;
  font-size: 22px;
  color: var(--text-primary, #111827);
  font-weight: 600;
}

.hero-desc {
  margin: 0;
  color: var(--text-secondary, #4b5563);
  font-size: 14px;
  line-height: 1.6;
}

.hero-shortcuts {
  display: flex;
  gap: 12px;
  margin-top: 12px;
  width: 100%;
}

.shortcut-card {
  flex: 1;
  padding: 14px;
  background: var(--bg-elevated, #f4f8f8);
  border: 1px solid var(--border-subtle, #e5e7eb);
  border-radius: 10px;
  display: flex;
  flex-direction: column;
  gap: 6px;
  transition: all 0.15s ease;
}

.shortcut-card:hover {
  border-color: #1f5947;
  transform: translateY(-1px);
}

[data-theme='dark'] .shortcut-card:hover {
  border-color: #16977a;
}

.shortcut-key {
  font-family: var(--font-mono, monospace);
  font-size: 13.5px;
  font-weight: 600;
  color: #1f5947;
}

[data-theme='dark'] .shortcut-key {
  color: #34d399;
}

.shortcut-desc {
  font-size: 12px;
  color: var(--text-secondary, #4b5563);
}

.quick-create-strip {
  display: flex;
  gap: 12px;
  margin-top: 8px;
}

/* 激活文件视图 */
.active-file-workspace {
  flex: 1;
  display: flex;
  flex-direction: column;
  height: 100%;
  overflow: hidden;
}

.canvas-topbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 8px 16px;
  background: var(--bg-elevated, #f4f8f8);
  border-bottom: 1px solid var(--border-subtle, #e5e7eb);
  user-select: none;
}

.topbar-left {
  display: flex;
  align-items: center;
  gap: 8px;
  min-width: 0;
}

.file-top-icon {
  font-size: 16px;
}

.file-top-path {
  font-size: 13px;
  color: var(--text-primary, #111827);
  font-weight: 600;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.dirty-badge {
  color: var(--accent-warning, #f59e0b);
  font-size: 11px;
  font-weight: 600;
  margin-left: 4px;
  white-space: nowrap;
}

.media-badge {
  font-size: 11px;
  font-weight: 600;
  color: #10b981;
  background: rgba(16, 185, 129, 0.12);
  border: 1px solid rgba(16, 185, 129, 0.25);
  padding: 1px 6px;
  border-radius: 4px;
  white-space: nowrap;
}

.file-size-tag {
  font-size: 11px;
  color: var(--text-secondary, #4b5563);
  padding: 1px 6px;
  background: var(--bg-main, #ffffff);
  border: 1px solid var(--border-subtle, #e5e7eb);
  border-radius: 4px;
  white-space: nowrap;
}

.topbar-right {
  display: flex;
  align-items: center;
  gap: 10px;
}

.md-mode-switch {
  display: flex;
  background: var(--bg-main, #ffffff);
  border-radius: 6px;
  padding: 2px;
  border: 1px solid var(--border-subtle, #e5e7eb);
}

.mode-btn {
  padding: 3px 10px;
  border: none;
  background: transparent;
  color: var(--text-secondary, #4b5563);
  font-size: 12px;
  border-radius: 4px;
  cursor: pointer;
  transition: all 0.15s ease;
}

.mode-btn:hover:not(.is-active) {
  color: var(--text-primary, #111827);
}

.mode-btn.is-active {
  background: #1f5947;
  color: #ffffff;
  font-weight: 500;
}

[data-theme='dark'] .mode-btn.is-active {
  background: #16977a;
  color: #ffffff;
}

.close-file-btn {
  width: 26px;
  height: 26px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  border: none;
  background: transparent;
  color: var(--text-tertiary, #9ca3af);
  border-radius: 6px;
  cursor: pointer;
  font-size: 13px;
  transition: all 0.15s ease;
}

.close-file-btn:hover {
  background: rgba(239, 68, 68, 0.08);
  color: var(--accent-error, #ef4444);
}

.canvas-content-area {
  flex: 1;
  position: relative;
  overflow: hidden;
  display: flex;
  flex-direction: column;
  background: var(--bg-main, #ffffff);
}

.content-loading-mask {
  position: absolute;
  inset: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  background: rgba(255, 255, 255, 0.75);
  backdrop-filter: blur(2px);
  color: var(--text-secondary, #4b5563);
  font-size: 13px;
  z-index: 10;
}

[data-theme='dark'] .content-loading-mask {
  background: rgba(11, 15, 25, 0.75);
}

/* Markdown 分屏布局 */
.markdown-split-layout {
  display: flex;
  flex: 1;
  height: 100%;
  overflow: hidden;
}

.layout-split .md-editor-col {
  flex: 1;
  border-right: 1px solid var(--border-subtle, #e5e7eb);
  min-width: 0;
}

.layout-split .md-preview-col {
  flex: 1;
  min-width: 0;
}

.layout-preview .md-preview-col {
  flex: 1;
  min-width: 0;
}

.layout-edit .md-editor-col {
  flex: 1;
  min-width: 0;
}

.md-editor-col,
.md-preview-col {
  height: 100%;
  overflow: hidden;
  display: flex;
  flex-direction: column;
}

.preview-scroll-wrapper {
  flex: 1;
  overflow-y: auto;
  padding: 20px 24px;
  box-sizing: border-box;
  background: var(--bg-main, #ffffff);
}

/* 二进制文件提示 */
.binary-file-card {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 14px;
  padding: 40px;
  color: var(--text-secondary, #4b5563);
  text-align: center;
}

.binary-file-card h3 {
  color: var(--text-primary, #111827);
  margin: 0;
}

.binary-icon {
  font-size: 48px;
}

.binary-tip {
  color: var(--text-secondary, #4b5563);
  font-size: 14px;
  max-width: 400px;
  margin: 0;
}

.binary-meta {
  display: flex;
  gap: 16px;
  font-size: 12px;
  color: var(--text-tertiary, #9ca3af);
}

/* 模态弹窗 */
.modal-backdrop {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.45);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 999;
  backdrop-filter: blur(4px);
}

.modal-card {
  width: 440px;
  background: var(--bg-main, #ffffff);
  border: 1px solid var(--border-subtle, #e5e7eb);
  border-radius: 12px;
  padding: 24px;
  box-shadow: 0 20px 25px -5px rgba(0, 0, 0, 0.1), 0 10px 10px -5px rgba(0, 0, 0, 0.04);
  display: flex;
  flex-direction: column;
  gap: 14px;
}

.modal-title {
  margin: 0;
  font-size: 16px;
  color: var(--text-primary, #111827);
  font-weight: 600;
}

.modal-subtitle {
  margin: 0;
  font-size: 13px;
  color: var(--text-secondary, #4b5563);
  line-height: 1.5;
}

.form-group {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.form-group label {
  font-size: 12px;
  font-weight: 500;
  color: var(--text-secondary, #4b5563);
}

.modal-input {
  width: 100%;
  padding: 8px 12px;
  border-radius: 6px;
  background: var(--bg-main, #ffffff);
  border: 1px solid var(--border-subtle, #e5e7eb);
  color: var(--text-primary, #111827);
  font-size: 13px;
  outline: none;
  box-sizing: border-box;
  transition: border-color 0.15s ease, box-shadow 0.15s ease;
}

.modal-input:focus {
  border-color: #1f5947;
  box-shadow: 0 0 0 3px rgba(31, 89, 71, 0.16);
}

[data-theme='dark'] .modal-input:focus {
  border-color: #16977a;
  box-shadow: 0 0 0 3px rgba(22, 151, 122, 0.25);
}

.modal-actions {
  display: flex;
  justify-content: flex-end;
  gap: 10px;
  margin-top: 8px;
}
</style>
