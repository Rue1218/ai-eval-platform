<template>
  <div class="workspaces-admin-page">
    <!-- 顶部：说明条 + 4 维 KPI 统计卡 -->
    <div class="row-between">
      <div class="info-strip" style="margin: 0; padding: 6px 14px; border-radius: 8px">
        工作区 = 每个会话独立对应的沙箱文件夹（<span class="mono">{{ root || 'data/workspaces' }}</span>）。
        会话内工具调用的落盘文件全部保存在该文件夹，会话间互不可见。
      </div>
    </div>

    <div class="kpi-grid" style="--glow-c: var(--c-workspaces)">
      <div class="kpi">
        <div class="kpi-num num">{{ stats.total_sessions }}</div>
        <div class="kpi-label">会话总数</div>
      </div>
      <div class="kpi">
        <div class="kpi-num num">{{ stats.with_folder }}</div>
        <div class="kpi-label">有工作区文件</div>
      </div>
      <div class="kpi">
        <div class="kpi-num num">{{ totalSizeText }}</div>
        <div class="kpi-label">工作区总大小</div>
      </div>
      <div class="kpi">
        <div class="kpi-num num" :style="stats.orphan_count ? 'color: var(--accent-warning)' : ''">{{ stats.orphan_count }}</div>
        <div class="kpi-label">孤立文件夹</div>
      </div>
    </div>

    <!-- 主面板：会话列表（每个会话对应一个沙箱文件夹，服务端分页） -->
    <div class="panel glow" style="--glow-c: var(--c-workspaces)">
      <div class="panel-title workspace-panel-title">
        <div class="row">
          <span>会话 · 沙箱文件夹</span>
          <span class="mono" style="font-size: 12px; color: var(--text-tertiary)">({{ total }} / {{ stats.total_sessions }} 个会话)</span>
        </div>

        <div class="row workspace-panel-actions">
          <label v-if="selectableWorkspaceCount" class="workspace-select-all">
            <input
              class="workspace-checkbox"
              type="checkbox"
              :checked="allSelectableWorkspacesSelected"
              :disabled="batchCleaning"
              aria-label="全选当前列表中的工作区"
              @change="toggleAllWorkspaces"
            />
            <span>全选当前列表</span>
          </label>
          <button
            v-if="selectedWorkspaceCount"
            class="btn btn-danger btn-sm"
            :disabled="batchCleaning"
            @click="confirmBatchCleanup"
          >
            清理选中（{{ selectedWorkspaceCount }}）
          </button>
          <input
            v-model="searchKeyword"
            class="input"
            style="width: 220px"
            placeholder="搜索会话标题 / 归属 / ID…"
          />
          <select v-model="folderFilter" class="select" style="width: 130px">
            <option value="all">全部文件夹</option>
            <option value="has">有工作区</option>
            <option value="none">无工作区</option>
          </select>
          <select v-model="deletedFilter" class="select" style="width: 110px">
            <option value="all">全部状态</option>
            <option value="active">正常</option>
            <option value="deleted">已删除</option>
          </select>
          <button class="btn btn-secondary btn-sm" :disabled="loading || batchCleaning" @click="refresh">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
              <polyline points="23 4 23 10 17 10"></polyline>
              <polyline points="1 20 1 14 7 14"></polyline>
              <path d="M3.51 9a9 9 0 0 1 14.85-3.36L23 10M1 14l4.64 4.36A9 9 0 0 0 20.49 15"></path>
            </svg>
            <span>刷新</span>
          </button>
        </div>
      </div>

      <table class="ds-table">
        <thead>
          <tr>
            <th class="workspace-check-cell" style="width: 44px">
              <input
                class="workspace-checkbox"
                type="checkbox"
                :checked="allSelectableSessionsSelected"
                :disabled="!selectableSessions.length || batchCleaning"
                aria-label="全选当前页有工作区的会话"
                @change="toggleAllSessions"
              />
            </th>
            <th>会话</th>
            <th style="width: 110px">归属</th>
            <th style="width: 90px">可见性</th>
            <th style="width: 80px">状态</th>
            <th style="width: 200px">沙箱文件夹</th>
            <th style="width: 130px">最近活动</th>
            <th style="width: 150px; text-align: right">操作</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="item in items" :key="item.session_id">
            <td class="workspace-check-cell">
              <input
                class="workspace-checkbox"
                type="checkbox"
                :checked="selectedSessionIds.includes(item.session_id)"
                :disabled="!item.folder || batchCleaning"
                :aria-label="`选择工作区：${item.title || item.session_id}`"
                @change="toggleSessionSelection(item.session_id)"
              />
            </td>
            <td>
              <div class="session-cell">
                <div class="folder-ico">
                  <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">
                    <path d="M4 20h16a2 2 0 0 0 2-2V8a2 2 0 0 0-2-2h-8l-2-2H4a2 2 0 0 0-2 2v12a2 2 0 0 0 2 2Z"></path>
                  </svg>
                </div>
                <div class="session-name-box">
                  <span class="session-title">{{ item.title || '未命名会话' }}</span>
                  <span class="session-id mono">{{ shortId(item.session_id) }}</span>
                </div>
              </div>
            </td>
            <td class="small">{{ item.owner || '—' }}</td>
            <td>
              <span class="tag-soft">{{ item.visibility === 'team' ? '团队共享' : '私有' }}</span>
            </td>
            <td>
              <span v-if="!item.deleted" class="badge badge-succeeded"><i class="bdot"></i>正常</span>
              <span v-else class="badge badge-cancelled"><i class="bdot"></i>已删除</span>
            </td>
            <td>
              <div v-if="item.folder" class="folder-summary">
                <span class="mono" style="font-size: 12px; color: var(--text-primary)">{{ item.folder.file_count }} 个文件</span>
                <span class="tertiary small">{{ formatBytes(item.folder.total_bytes) }}</span>
              </div>
              <span v-else class="tertiary small">— 无工作区 —</span>
            </td>
            <td class="small tertiary mono">
              {{ formatDate(item.folder?.updated_at || item.updated_at) }}
            </td>
            <td style="text-align: right">
              <div class="row" style="justify-content: flex-end; gap: 4px">
                <button class="link-btn" :disabled="!item.folder || batchCleaning" @click="openFiles(item)">查看文件</button>
                <button class="link-btn danger" :disabled="!item.folder || batchCleaning" @click="confirmCleanup(item)">清理</button>
              </div>
            </td>
          </tr>
          <tr v-if="!items.length">
            <td colspan="8" class="small tertiary" style="text-align: center; padding: 28px 0">
              {{ hasActiveFilter ? '未找到匹配的会话' : '暂无会话记录' }}
            </td>
          </tr>
        </tbody>
      </table>

      <!-- 分页：跟随服务端 total，切页 / 调整每页条数均回源查询 -->
      <div class="pager-row">
        <n-pagination
          v-model:page="page"
          v-model:page-size="pageSize"
          :item-count="total"
          :page-sizes="[20, 50, 100, 200]"
          show-size-picker
          @update:page="loadWorkspaces"
          @update:page-size="onPageSizeChange"
        />
      </div>
    </div>

    <!-- 孤立文件夹（磁盘存在但数据库无对应会话） -->
    <div v-if="orphans.length" class="panel glow" style="--glow-c: var(--c-workspaces)">
      <div class="panel-title workspace-panel-title">
        <div class="row">
          <span>孤立文件夹</span>
          <span class="mono" style="font-size: 12px; color: var(--text-tertiary)">磁盘上存在但无对应会话记录，可安全清理</span>
        </div>
        <label class="workspace-select-all">
          <input
            class="workspace-checkbox"
            type="checkbox"
            :checked="allOrphansSelected"
            :disabled="batchCleaning"
            aria-label="全选孤立文件夹"
            @change="toggleAllOrphans"
          />
          <span>全选孤立文件夹</span>
        </label>
      </div>
      <table class="ds-table">
        <thead>
          <tr>
            <th class="workspace-check-cell" style="width: 44px">
              <input
                class="workspace-checkbox"
                type="checkbox"
                :checked="allOrphansSelected"
                :disabled="batchCleaning"
                aria-label="全选孤立文件夹"
                @change="toggleAllOrphans"
              />
            </th>
            <th>文件夹</th>
            <th style="width: 160px">大小</th>
            <th style="width: 160px">最近活动</th>
            <th style="width: 120px; text-align: right">操作</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="folder in orphans" :key="folder.name">
            <td class="workspace-check-cell">
              <input
                class="workspace-checkbox"
                type="checkbox"
                :checked="selectedOrphanNames.includes(folder.name)"
                :disabled="batchCleaning"
                :aria-label="`选择孤立文件夹：${folder.name}`"
                @change="toggleOrphanSelection(folder.name)"
              />
            </td>
            <td>
              <div class="session-cell">
                <div class="folder-ico">
                  <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">
                    <path d="M4 20h16a2 2 0 0 0 2-2V8a2 2 0 0 0-2-2h-8l-2-2H4a2 2 0 0 0-2 2v12a2 2 0 0 0 2 2Z"></path>
                  </svg>
                </div>
                <div class="session-name-box">
                  <span class="session-id mono">{{ folder.name }}</span>
                  <span class="session-title">{{ folder.file_count }} 个文件</span>
                </div>
              </div>
            </td>
            <td class="small mono">{{ formatBytes(folder.total_bytes) }}</td>
            <td class="small tertiary mono">{{ formatDate(folder.updated_at) }}</td>
            <td style="text-align: right">
              <button class="link-btn danger" :disabled="batchCleaning" @click="confirmOrphanCleanup(folder)">清理</button>
            </td>
          </tr>
        </tbody>
      </table>
    </div>

    <!-- 会话工作区文件查看弹窗 -->
    <n-modal
      v-model:show="showFiles"
      preset="card"
      :title="`工作区文件 · ${currentSession?.title || ''}`"
      style="width: 640px"
    >
      <div class="small tertiary mono" style="margin-bottom: 10px">
        {{ currentFolderPath }}
      </div>
      <div v-if="fileLoading" class="small tertiary" style="padding: 20px 0; text-align: center">加载中…</div>
      <div v-else-if="!fileList.files.length" class="small tertiary" style="padding: 20px 0; text-align: center">
        该工作区为空（无落盘文件）
      </div>
      <table v-else class="ds-table">
        <thead>
          <tr>
            <th>文件名</th>
            <th style="width: 110px">大小</th>
            <th style="width: 160px">修改时间</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="f in fileList.files" :key="f.name">
            <td class="mono" style="font-size: 12px">{{ f.name }}</td>
            <td class="small mono">{{ formatBytes(f.size) }}</td>
            <td class="small tertiary mono">{{ formatDate(f.updated_at) }}</td>
          </tr>
        </tbody>
      </table>
      <div v-if="fileList.total >= 200" class="small tertiary" style="margin-top: 8px">
        仅显示前 {{ fileList.total }} 个文件。
      </div>
      <template #footer>
        <div style="display: flex; justify-content: flex-end; gap: 8px">
          <n-button @click="showFiles = false">关闭</n-button>
          <n-button
            v-if="currentSession?.folder"
            type="error"
            :loading="cleaning"
            @click="confirmCleanup(currentSession!)"
          >
            清理此工作区
          </n-button>
        </div>
      </template>
    </n-modal>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, watch } from 'vue'
import { useMessage, useDialog } from 'naive-ui'
import { api } from '../api/http'
import type { WorkspaceSession, WorkspaceFolder, WorkspaceFileList, WorkspaceStats } from '../api/types'

const message = useMessage()
const dialog = useDialog()

// 列表与聚合状态：服务端分页，items 仅当前页
const root = ref('')
const items = ref<WorkspaceSession[]>([])
const orphans = ref<WorkspaceFolder[]>([])
const total = ref(0)
const stats = ref<WorkspaceStats>({ total_sessions: 0, with_folder: 0, orphan_count: 0 })
const loading = ref(false)
const fileLoading = ref(false)
const cleaning = ref(false)
const batchCleaning = ref(false)

// 批量清理选择状态：会话工作区与孤立文件夹分开记录，避免不同清理接口混用。
const selectedSessionIds = ref<string[]>([])
const selectedOrphanNames = ref<string[]>([])
const selectableSessions = computed(() => items.value.filter((item) => Boolean(item.folder)))
const selectableWorkspaceCount = computed(() => selectableSessions.value.length + orphans.value.length)
const selectedWorkspaceCount = computed(() => selectedSessionIds.value.length + selectedOrphanNames.value.length)
const allSelectableSessionsSelected = computed(() => {
  const sessions = selectableSessions.value
  return sessions.length === 0 || sessions.every((item) => selectedSessionIds.value.includes(item.session_id))
})
const allOrphansSelected = computed(() => {
  return orphans.value.length === 0 || orphans.value.every((folder) => selectedOrphanNames.value.includes(folder.name))
})
const allSelectableWorkspacesSelected = computed(() => {
  return selectableWorkspaceCount.value > 0 && allSelectableSessionsSelected.value && allOrphansSelected.value
})

// 分页与筛选状态：筛选条件变化由服务端处理，并回到第 1 页
const page = ref(1)
const pageSize = ref(50)
const searchKeyword = ref('')
const folderFilter = ref<'all' | 'has' | 'none'>('all')
const deletedFilter = ref<'all' | 'active' | 'deleted'>('all')

const hasActiveFilter = computed(
  () => searchKeyword.value.trim() !== '' || folderFilter.value !== 'all' || deletedFilter.value !== 'all',
)

// 磁盘总大小 KPI：需遍历全部工作区文件，列表渲染后异步加载，不阻塞表格首屏
const totalSizeLoading = ref(true)
const totalBytes = ref<number | null>(null)
const totalSizeText = computed(() => {
  if (totalSizeLoading.value) return '…'
  if (totalBytes.value === null) return '—'
  return formatBytes(totalBytes.value)
})

// 文件查看弹窗状态
const showFiles = ref(false)
const currentSession = ref<WorkspaceSession | null>(null)
const fileList = ref<WorkspaceFileList>({ session_id: '', path: '', files: [], total: 0 })
const currentFolderPath = computed(() => currentSession.value?.folder?.path || fileList.value.path || '')

// 请求序号：丢弃过期响应，避免慢请求覆盖新筛选结果
let requestSeq = 0

async function loadWorkspaces() {
  const seq = ++requestSeq
  clearWorkspaceSelection()
  loading.value = true
  try {
    const data = await api.admin.listWorkspaces({
      offset: (page.value - 1) * pageSize.value,
      limit: pageSize.value,
      keyword: searchKeyword.value.trim(),
      folder: folderFilter.value,
      deleted: deletedFilter.value,
    })
    if (seq !== requestSeq) return
    root.value = data.root
    items.value = data.items
    orphans.value = data.orphans
    total.value = data.total
    stats.value = data.stats
  } catch (err: any) {
    message.error(err.message || '加载工作区失败')
  } finally {
    if (seq === requestSeq) loading.value = false
  }
}

async function loadTotalBytes() {
  totalSizeLoading.value = true
  try {
    const data = await api.admin.workspaceStats()
    totalBytes.value = data.total_bytes
  } catch {
    totalBytes.value = null // KPI 后台加载失败静默降级，不干扰列表
  } finally {
    totalSizeLoading.value = false
  }
}

function onPageSizeChange() {
  // 每页条数变化后回到第 1 页重新查询
  page.value = 1
  void loadWorkspaces()
}

/** 清空当前页和孤立文件夹的批量选择，筛选/刷新后重新选择更安全。 */
function clearWorkspaceSelection() {
  selectedSessionIds.value = []
  selectedOrphanNames.value = []
}

/** 切换单个有工作区会话的选择状态。 */
function toggleSessionSelection(sessionId: string) {
  if (!selectableSessions.value.some((item) => item.session_id === sessionId)) return
  selectedSessionIds.value = selectedSessionIds.value.includes(sessionId)
    ? selectedSessionIds.value.filter((id) => id !== sessionId)
    : [...selectedSessionIds.value, sessionId]
}

/** 切换单个孤立文件夹的选择状态。 */
function toggleOrphanSelection(folderName: string) {
  if (!orphans.value.some((folder) => folder.name === folderName)) return
  selectedOrphanNames.value = selectedOrphanNames.value.includes(folderName)
    ? selectedOrphanNames.value.filter((name) => name !== folderName)
    : [...selectedOrphanNames.value, folderName]
}

/** 全选或取消当前页中有工作区文件的会话。 */
function toggleAllSessions(event: Event) {
  const checked = (event.target as HTMLInputElement).checked
  const ids = selectableSessions.value.map((item) => item.session_id)
  selectedSessionIds.value = checked ? ids : selectedSessionIds.value.filter((id) => !ids.includes(id))
}

/** 全选或取消当前列表中的孤立文件夹。 */
function toggleAllOrphans(event: Event) {
  const checked = (event.target as HTMLInputElement).checked
  const names = orphans.value.map((folder) => folder.name)
  selectedOrphanNames.value = checked ? names : selectedOrphanNames.value.filter((name) => !names.includes(name))
}

/** 一键全选或取消当前列表中的会话工作区与孤立文件夹。 */
function toggleAllWorkspaces(event: Event) {
  const checked = (event.target as HTMLInputElement).checked
  if (checked) {
    selectedSessionIds.value = selectableSessions.value.map((item) => item.session_id)
    selectedOrphanNames.value = orphans.value.map((folder) => folder.name)
    return
  }
  clearWorkspaceSelection()
}

function refresh() {
  void loadWorkspaces()
  void loadTotalBytes()
}

// 关键词防抖：输入停顿 300ms 后回到第 1 页重新查询
let searchTimer: number | undefined
watch(searchKeyword, () => {
  window.clearTimeout(searchTimer)
  searchTimer = window.setTimeout(() => {
    page.value = 1
    void loadWorkspaces()
  }, 300)
})

// 下拉筛选立即生效并回到第 1 页
watch([folderFilter, deletedFilter], () => {
  page.value = 1
  void loadWorkspaces()
})

function shortId(id: string): string {
  return id.length > 10 ? `${id.slice(0, 8)}…` : id
}

function formatBytes(bytes?: number): string {
  if (bytes === undefined || bytes === null) return '0 B'
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / 1024 / 1024).toFixed(2)} MB`
}

function formatDate(value?: string | null): string {
  if (!value) return '—'
  return new Date(value).toLocaleString('zh-CN', { hour12: false })
}

async function openFiles(session: WorkspaceSession) {
  currentSession.value = session
  showFiles.value = true
  fileLoading.value = true
  fileList.value = { session_id: session.session_id, path: '', files: [], total: 0 }
  try {
    fileList.value = await api.admin.listWorkspaceFiles(session.session_id)
  } catch (err: any) {
    message.error(err.message || '加载工作区文件失败')
  } finally {
    fileLoading.value = false
  }
}

function doCleanup(sessionId: string, label: string, after: () => void) {
  dialog.warning({
    title: `清理工作区「${label}」？`,
    content: '将物理删除该沙箱文件夹下的全部文件，此操作不可恢复。',
    positiveText: '确认清理',
    negativeText: '取消',
    onPositiveClick: async () => {
      cleaning.value = true
      try {
        await api.admin.deleteWorkspace(sessionId)
        message.success('工作区已清理')
        showFiles.value = false
        after()
      } catch (err: any) {
        message.error(err.message || '清理失败')
      } finally {
        cleaning.value = false
      }
    },
  })
}

function confirmCleanup(session: WorkspaceSession) {
  doCleanup(session.session_id, session.title || session.session_id, refresh)
}

/** 批量清理已选工作区：复用现有单项接口，允许部分成功并在完成后刷新统计。 */
function confirmBatchCleanup() {
  const sessionIds = selectedSessionIds.value.filter((sessionId) =>
    selectableSessions.value.some((item) => item.session_id === sessionId),
  )
  const orphanNames = selectedOrphanNames.value.filter((folderName) =>
    orphans.value.some((folder) => folder.name === folderName),
  )
  const total = sessionIds.length + orphanNames.length
  if (!total) {
    clearWorkspaceSelection()
    return
  }

  dialog.warning({
    title: '清理选中的工作区？',
    content: `将物理删除选中的 ${total} 个沙箱文件夹，此操作不可恢复。会话工作区 ${sessionIds.length} 个，孤立文件夹 ${orphanNames.length} 个。`,
    positiveText: `确认清理 ${total} 项`,
    negativeText: '取消',
    positiveButtonProps: { type: 'error' },
    onPositiveClick: async () => {
      batchCleaning.value = true
      try {
        const jobs: Array<Promise<boolean>> = [
          ...sessionIds.map(async (sessionId) => (await api.admin.deleteWorkspace(sessionId)).ok),
          ...orphanNames.map(async (folderName) => (await api.admin.deleteOrphan(folderName)).ok),
        ]
        const results = await Promise.allSettled(jobs)
        const succeeded = results.filter((result) => result.status === 'fulfilled' && result.value).length
        const notCleaned = results.length - succeeded

        clearWorkspaceSelection()
        refresh()
        if (!notCleaned) {
          message.success(`已清理 ${succeeded} 个工作区`)
        } else if (succeeded) {
          message.warning(`已清理 ${succeeded} 个工作区，${notCleaned} 个未清理`)
        } else {
          message.error('批量清理失败，未清理任何工作区')
        }
      } finally {
        batchCleaning.value = false
      }
    },
  })
}

function confirmOrphanCleanup(folder: WorkspaceFolder) {
  dialog.warning({
    title: `清理孤立文件夹「${folder.name}」？`,
    content: '将物理删除该文件夹下的全部文件，此操作不可恢复。',
    positiveText: '确认清理',
    negativeText: '取消',
    onPositiveClick: async () => {
      cleaning.value = true
      try {
        await api.admin.deleteOrphan(folder.name)
        message.success('孤立文件夹已清理')
        refresh()
      } catch (err: any) {
        message.error(err.message || '清理失败')
      } finally {
        cleaning.value = false
      }
    },
  })
}

onMounted(refresh)
</script>

<style scoped>
.workspaces-admin-page {
  display: flex;
  flex-direction: column;
  gap: 16px;
}
.session-cell {
  display: flex;
  align-items: center;
  gap: 10px;
}
.folder-ico {
  width: 28px;
  height: 28px;
  border-radius: 7px;
  background: color-mix(in srgb, var(--c-workspaces) 14%, var(--bg-main));
  color: var(--c-workspaces);
  display: flex;
  align-items: center;
  justify-content: center;
  flex: 0 0 auto;
  border: 1px solid color-mix(in srgb, var(--c-workspaces) 30%, transparent);
}
.session-name-box {
  display: flex;
  flex-direction: column;
  min-width: 0;
}
.session-title {
  font-weight: 600;
  font-size: 13px;
  color: var(--text-primary);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  max-width: 220px;
}
.session-id {
  font-size: 11px;
  color: var(--text-tertiary);
}
.folder-summary {
  display: flex;
  flex-direction: column;
  gap: 2px;
}
.workspace-panel-title {
  align-items: flex-start;
  gap: 10px;
  flex-wrap: wrap;
}
.workspace-panel-actions {
  flex-wrap: wrap;
  justify-content: flex-end;
}
.workspace-select-all {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  color: var(--text-secondary);
  font-size: 12px;
  white-space: nowrap;
  cursor: pointer;
  user-select: none;
}
.workspace-checkbox {
  width: 15px;
  height: 15px;
  margin: 0;
  accent-color: var(--c-workspaces);
  cursor: pointer;
}
.workspace-checkbox:disabled {
  cursor: not-allowed;
  opacity: 0.55;
}
.workspace-check-cell {
  width: 44px;
  text-align: center !important;
}
@media (max-width: 900px) {
  .workspace-panel-title > .row:first-child,
  .workspace-panel-actions {
    width: 100%;
  }
  .workspace-panel-actions {
    justify-content: flex-start;
  }
  .workspace-panel-actions .input,
  .workspace-panel-actions .select {
    width: auto !important;
    flex: 1 1 130px;
  }
  .workspace-panel-actions .input {
    flex-basis: 200px;
  }
}
.pager-row {
  display: flex;
  justify-content: flex-end;
  margin-top: 12px;
}
</style>
