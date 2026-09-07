<template>
  <div class="user-workspaces-page">
    <!-- 顶部：说明条 + 新建操作 -->
    <div class="info-strip" style="margin: 0 0 14px; padding: 6px 14px; border-radius: 8px">
      工作区是你在沙箱中的自管数据域（<span class="mono">data/workspaces/&lt;id&gt;</span>）。
      会话工具产出的文件落在绑定工作区；未绑定会话使用各自的临时工作区。
    </div>

    <!-- 列表视图 -->
    <div v-if="!browseWs" class="panel glow" style="--glow-c: var(--c-workspaces)">
      <div class="panel-title workspace-panel-title">
        <div class="row">
          <span>{{ showDeleted ? '已注销工作区' : '我的工作区' }}</span>
          <span class="mono" style="font-size: 12px; color: var(--text-tertiary)">({{ total }})</span>
        </div>
        <div class="row workspace-panel-actions">
          <button class="btn btn-sm" :disabled="loading" @click="toggleDeleted">
            {{ showDeleted ? '返回活跃' : '查看已注销' }}
          </button>
          <button class="btn btn-sm" :disabled="loading" @click="load">刷新</button>
        </div>
      </div>

      <!-- 新建工作区 -->
      <div class="row" style="gap: 8px; margin-bottom: 12px">
        <input
          v-model="newName"
          class="input"
          style="flex: 1; max-width: 320px"
          placeholder="新工作区名称"
          :disabled="busy"
          @keyup.enter="createWorkspace"
        />
        <button class="btn btn-primary btn-sm" :disabled="busy || !newName.trim()" @click="createWorkspace">
          新建工作区
        </button>
      </div>

      <div v-if="error" class="error-strip">{{ error }}</div>
      <table v-if="items.length" class="ws-table">
        <thead>
          <tr>
            <th>名称</th>
            <th>文件</th>
            <th>占用</th>
            <th>最近活动</th>
            <th style="width: 240px">操作</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="item in items" :key="item.id">
            <td>
              <span class="mono" style="color: var(--text-primary)">{{ item.name }}</span>
              <span v-if="item.deleted" class="badge-deleted">已注销</span>
            </td>
            <td>{{ item.folder?.file_count ?? 0 }}</td>
            <td class="mono">{{ formatBytes(item.folder?.total_bytes ?? 0) }}</td>
            <td class="tertiary small">{{ formatDate(item.folder?.updated_at || item.updated_at) }}</td>
            <td>
              <template v-if="item.deleted">
                <button class="btn btn-sm" :disabled="busy" @click="reviveHint(item)">查看目录</button>
                <button class="link-btn danger" :disabled="busy" @click="confirmPurge(item)">清空并删除</button>
              </template>
              <template v-else>
                <button class="btn btn-sm" :disabled="busy" @click="openBrowse(item)">浏览</button>
                <button class="link-btn" :disabled="busy || renamingId === item.id" @click="startRename(item)">改名</button>
                <button class="link-btn danger" :disabled="busy" @click="confirmDelete(item)">注销</button>
              </template>
            </td>
          </tr>
        </tbody>
      </table>
      <div v-else class="empty-strip">{{ loading ? '加载中…' : '暂无工作区，先在上方新建一个。' }}</div>

      <!-- 行内改名 -->
      <div v-if="renamingId" class="row" style="gap: 8px; margin-top: 10px">
        <input v-model="renameValue" class="input" style="flex: 1; max-width: 320px" @keyup.enter="submitRename" />
        <button class="btn btn-sm btn-primary" :disabled="busy" @click="submitRename">保存</button>
        <button class="btn btn-sm" :disabled="busy" @click="renamingId = null">取消</button>
      </div>
    </div>

    <!-- 目录浏览视图（一层 + 父链） -->
    <div v-else class="panel glow" style="--glow-c: var(--c-workspaces)">
      <div class="panel-title workspace-panel-title">
        <div class="row">
          <button class="btn btn-sm" :disabled="busy" @click="closeBrowse">← 返回工作区</button>
          <span class="mono" style="margin-left: 10px">{{ browseWs.name }}</span>
          <span class="mono tertiary small">/{{ browsePath }}</span>
        </div>
        <div class="row workspace-panel-actions">
          <input
            v-model="folderName"
            class="input"
            style="width: 180px"
            placeholder="新建文件夹名"
            :disabled="busy"
            @keyup.enter="createFolder"
          />
          <button class="btn btn-sm btn-primary" :disabled="busy || !folderName.trim()" @click="createFolder">新建文件夹</button>
        </div>
      </div>

      <div v-if="browseError" class="error-strip">{{ browseError }}</div>
      <div class="breadcrumb mono small">
        <span class="crumb" @click="goLevel('')">根</span>
        <template v-for="(seg, idx) in breadcrumb" :key="idx">
          <span style="color: var(--text-tertiary)">/</span>
          <span class="crumb" @click="goLevel(segments.slice(0, idx + 1).join('/'))">{{ seg }}</span>
        </template>
      </div>

      <table v-if="entries.length" class="ws-table">
        <thead>
          <tr>
            <th>名称</th>
            <th>类型</th>
            <th>大小</th>
            <th>修改时间</th>
          </tr>
        </thead>
        <tbody>
          <tr
            v-for="entry in entries"
            :key="entry.kind + '/' + entry.name"
            :class="{ 'row-clickable': entry.kind === 'dir' }"
            @dblclick="entry.kind === 'dir' ? enterDir(entry.name) : null"
          >
            <td>
              <span v-if="entry.kind === 'dir'" class="folder-ico">📁</span>
              <span v-else-if="entry.kind === 'link'" class="folder-ico">🔗</span>
              <span v-else class="folder-ico">📄</span>
              <span class="mono">{{ entry.name }}</span>
            </td>
            <td class="tertiary small">{{ entry.kind }}</td>
            <td class="mono">{{ entry.kind === 'file' ? formatBytes(entry.size) : '—' }}</td>
            <td class="tertiary small">{{ formatDate(entry.updated_at) }}</td>
          </tr>
        </tbody>
      </table>
      <div v-else class="empty-strip">空目录。</div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useDialog, useMessage } from 'naive-ui'
import { api } from '../api/http'
import type { UserWorkspace } from '../api/types'

const message = useMessage()
const dialog = useDialog()

const items = ref<UserWorkspace[]>([])
const total = ref(0)
const loading = ref(false)
const busy = ref(false)
const error = ref('')
const showDeleted = ref(false)
const newName = ref('')
const renamingId = ref<string | null>(null)
const renameValue = ref('')

// 目录浏览状态
const browseWs = ref<UserWorkspace | null>(null)
const browsePath = ref('')
const entries = ref<{ name: string; kind: 'dir' | 'file' | 'link'; size: number; updated_at?: string | null }[]>([])
const browseError = ref('')
const folderName = ref('')

const segments = computed(() => browsePath.value.split('/').filter(Boolean))
const breadcrumb = computed(() => segments.value)

function formatBytes(bytes: number): string {
  if (!bytes) return '0 B'
  const units = ['B', 'KB', 'MB', 'GB']
  let value = bytes
  let unit = 0
  while (value >= 1024 && unit < units.length - 1) {
    value /= 1024
    unit += 1
  }
  return `${value.toFixed(value >= 10 || unit === 0 ? 0 : 1)} ${units[unit]}`
}

function formatDate(value?: string | null): string {
  if (!value) return '—'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return '—'
  return date.toLocaleString('zh-CN', { hour12: false })
}

async function load(): Promise<void> {
  loading.value = true
  error.value = ''
  try {
    const data = await api.workspaces.list({ include_deleted: showDeleted.value })
    items.value = data.items
    total.value = data.total
  } catch (e) {
    error.value = e instanceof Error ? e.message : '工作区加载失败'
  } finally {
    loading.value = false
  }
}

function toggleDeleted(): void {
  showDeleted.value = !showDeleted.value
  void load()
}

async function createWorkspace(): Promise<void> {
  const name = newName.value.trim()
  if (!name) return
  busy.value = true
  try {
    await api.workspaces.create(name)
    newName.value = ''
    message.success('工作区已创建')
    await load()
  } catch (e) {
    message.error(e instanceof Error ? e.message : '创建失败')
  } finally {
    busy.value = false
  }
}

function startRename(item: UserWorkspace): void {
  renamingId.value = item.id
  renameValue.value = item.name
}

async function submitRename(): Promise<void> {
  if (!renamingId.value) return
  const name = renameValue.value.trim()
  if (!name) return
  busy.value = true
  try {
    await api.workspaces.rename(renamingId.value, name)
    message.success('已改名')
    renamingId.value = null
    await load()
  } catch (e) {
    message.error(e instanceof Error ? e.message : '改名失败')
  } finally {
    busy.value = false
  }
}

function confirmDelete(item: UserWorkspace): void {
  dialog.warning({
    title: `注销工作区「${item.name}」？`,
    content: '注销后文件与目录保留（可经「查看已注销」清空或待 F3 复活挂接），绑定会话将停止访问该数据域。',
    positiveText: '注销',
    negativeText: '取消',
    onPositiveClick: async () => {
      try {
        await api.workspaces.remove(item.id, false)
        message.success('已注销（软删）')
        await load()
      } catch (e) {
        message.error(e instanceof Error ? e.message : '注销失败')
      }
    },
  })
}

function confirmPurge(item: UserWorkspace): void {
  dialog.warning({
    title: `清空并删除「${item.name}」？`,
    content: '将解绑全部会话引用并物理删除目录树与记录，不可恢复。',
    positiveText: '清空并删除',
    negativeText: '取消',
    onPositiveClick: async () => {
      try {
        await api.workspaces.remove(item.id, true)
        message.success('已清空并删除')
        await load()
      } catch (e) {
        message.error(e instanceof Error ? e.message : '删除失败')
      }
    },
  })
}

function reviveHint(item: UserWorkspace): void {
  // 已注销工作区的目录浏览保留（软删后数据仍在卷内）
  void openBrowse(item)
}

async function openBrowse(item: UserWorkspace): Promise<void> {
  browseWs.value = item
  browsePath.value = ''
  await loadLevel()
}

async function closeBrowse(): Promise<void> {
  browseWs.value = null
  browsePath.value = ''
  entries.value = []
}

async function loadLevel(): Promise<void> {
  if (!browseWs.value) return
  browseError.value = ''
  try {
    const data = await api.workspaces.listFiles(browseWs.value.id, browsePath.value)
    entries.value = data.entries
  } catch (e) {
    browseError.value = e instanceof Error ? e.message : '目录读取失败'
  }
}

function enterDir(name: string): void {
  browsePath.value = segments.value.length ? `${segments.value.join('/')}/${name}` : name
  void loadLevel()
}

function goLevel(rel: string): void {
  browsePath.value = rel
  void loadLevel()
}

async function createFolder(): Promise<void> {
  if (!browseWs.value) return
  const name = folderName.value.trim()
  if (!name) return
  busy.value = true
  try {
    await api.workspaces.createFolder(browseWs.value.id, browsePath.value, name)
    folderName.value = ''
    message.success('文件夹已创建')
    await loadLevel()
  } catch (e) {
    message.error(e instanceof Error ? e.message : '创建失败')
  } finally {
    busy.value = false
  }
}

onMounted(() => {
  void load()
})
</script>

<style scoped>
.ws-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 13px;
}
.ws-table th,
.ws-table td {
  text-align: left;
  padding: 8px 10px;
  border-bottom: 1px solid var(--border-color, rgba(128, 128, 128, 0.18));
}
.ws-table th {
  color: var(--text-tertiary);
  font-weight: 500;
}
.row-clickable {
  cursor: pointer;
}
.row-clickable:hover {
  background: rgba(128, 128, 128, 0.08);
}
.badge-deleted {
  margin-left: 8px;
  padding: 1px 8px;
  border-radius: 999px;
  font-size: 12px;
  color: var(--accent-warning);
  border: 1px solid var(--accent-warning);
}
.breadcrumb {
  margin: 6px 0 10px;
}
.crumb {
  cursor: pointer;
  color: var(--c-workspaces);
}
.crumb:hover {
  text-decoration: underline;
}
.folder-ico {
  margin-right: 6px;
}
.error-strip,
.empty-strip {
  padding: 10px 14px;
  border-radius: 8px;
  font-size: 13px;
  margin-bottom: 8px;
}
.error-strip {
  color: var(--accent-danger);
  background: color-mix(in srgb, var(--accent-danger) 10%, transparent);
}
.empty-strip {
  color: var(--text-tertiary);
}
</style>
