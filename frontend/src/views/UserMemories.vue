<template>
  <div class="memories-page">
    <header class="memories-header">
      <div>
        <div class="eyebrow">由你保存，由你管理</div>
        <h1>我的记忆</h1>
        <p>保存常用偏好和事实资料，让之后的私有对话少一些重复说明。</p>
      </div>
      <n-button type="primary" :disabled="busy" @click="openEditor()">新建记忆</n-button>
    </header>

    <div class="memory-guidance">
      <span class="privacy-label">仅本人私有对话使用</span>
      <span>只记录你主动保存的内容。请勿存放密码、API Key 等凭据。</span>
    </div>

    <section class="memories-panel" aria-label="记忆列表">
      <form class="memory-toolbar" @submit.prevent="search">
        <n-input v-model:value="query" clearable placeholder="搜索标题或内容" aria-label="搜索记忆" :maxlength="200" :disabled="busy" />
        <n-select v-model:value="workspaceFilter" :options="filterOptions" clearable placeholder="全部工作区与全局" aria-label="筛选工作区" :disabled="busy || workspacesLoading" />
        <n-button attr-type="submit" :disabled="busy" :loading="loading">搜索</n-button>
        <n-button :disabled="busy || loading" @click="refresh">刷新</n-button>
      </form>
      <n-alert v-if="listError" type="error" :show-icon="false" class="list-alert">{{ listError }}</n-alert>
      <n-alert v-if="workspaceError" type="warning" :show-icon="false" class="list-alert">{{ workspaceError }}</n-alert>
      <div class="list-caption">{{ total }} 条记忆 <span>常用偏好作为建议，事实资料按当前问题的关键词召回。</span></div>
      <n-spin :show="loading">
        <div v-if="!items.length" class="memory-empty">
          <n-empty :description="listError ? '暂时无法加载记忆' : appliedQuery || appliedWorkspace !== null ? '没有找到匹配的记忆' : '还没有保存记忆'" />
          <p v-if="!listError">例如：你希望的回答格式，或项目中经常需要引用的背景资料。</p>
        </div>
        <article v-for="item in items" :key="item.id" class="memory-item">
          <div class="memory-item-top">
            <div class="memory-heading">
              <h2>{{ item.title }}</h2>
              <span class="memory-category" :class="item.category">{{ categoryLabel(item.category) }}</span>
            </div>
            <div class="memory-actions">
              <n-button size="small" :disabled="busy" @click="openEditor(item)">查看 / 更正</n-button>
              <n-button size="small" quaternary type="error" :disabled="busy" @click="deleteTarget = item">删除</n-button>
            </div>
          </div>
          <p class="memory-content">{{ item.content }}</p>
          <div class="memory-meta">
            <span>{{ scopeLabel(item) }}</span>
            <span>更新于 {{ formatDate(item.updated_at) }}</span>
            <span class="memory-source">来源 {{ item.source_id }}</span>
          </div>
        </article>
      </n-spin>
      <div v-if="total > pageSize" class="memory-pagination">
        <n-pagination :page="page" :page-size="pageSize" :item-count="total" :page-slot="5" :disabled="loading || busy" @update:page="changePage" />
      </div>
    </section>

    <n-modal :show="editorOpen" preset="card" :title="editing ? '查看 / 更正记忆' : '新建记忆'" class="memory-modal" :mask-closable="!saving" :close-on-esc="!saving" :closable="!saving" @update:show="closeEditor">
      <n-alert v-if="conflicted" type="warning" :show-icon="false" class="editor-alert">
        这条记忆已被更新或删除，列表已刷新。当前草稿仍保留，请复制需要的内容，关闭后重新打开最新记忆再更正。
      </n-alert>
      <!-- 目录故障在当前弹窗内恢复，避免关闭重开时丢失未提交草稿。 -->
      <n-alert v-if="workspaceError" type="warning" :show-icon="false" class="editor-alert">
        {{ workspaceError }}
        <n-button size="small" :loading="workspacesLoading" :disabled="busy || workspacesLoading" @click="loadWorkspaces">重试加载工作区</n-button>
      </n-alert>
      <n-alert v-if="missingWorkspace" type="warning" :show-icon="false" class="editor-alert">
        原工作区已不可用。记忆仍保留原范围，不会自动转为全局；如需继续保存，请明确选择其他工作区或全局。
      </n-alert>
      <n-form :model="draft" label-placement="top" :disabled="saving">
        <n-form-item label="标题" required>
          <n-input v-model:value="draft.title" :maxlength="80" show-count placeholder="为这条记忆起一个清楚的名字" aria-label="记忆标题" />
        </n-form-item>
        <n-form-item label="内容" required>
          <n-input v-model:value="draft.content" type="textarea" :maxlength="2000" show-count :autosize="{ minRows: 5, maxRows: 12 }" placeholder="写下希望在以后对话中使用的偏好或事实" aria-label="记忆内容" />
        </n-form-item>
        <div class="editor-options">
          <n-form-item label="类型">
            <n-select v-model:value="draft.category" :options="categoryOptions" aria-label="记忆类型" />
          </n-form-item>
          <n-form-item label="使用范围">
            <n-select v-model:value="draftScope" :options="editorWorkspaceOptions" :disabled="saving || workspacesLoading || !!workspaceError" aria-label="记忆使用范围" />
          </n-form-item>
        </div>
      </n-form>
      <p class="editor-hint">{{ draft.category === 'preference' ? '常用偏好用于之后的私有对话，当前明确要求始终优先。' : '事实资料是你保存的内容，未经系统核实；按当前问题的关键词选择使用，不保证每次都会召回。' }}<br>绑定工作区后，仅在该工作区的本人私有对话中使用。</p>
      <template #footer>
        <div class="modal-actions">
          <n-button :disabled="saving" @click="closeEditor(false)">取消</n-button>
          <n-button type="primary" :loading="saving" :disabled="!canSave" @click="save">{{ editing ? '保存更正' : '保存记忆' }}</n-button>
        </div>
      </template>
    </n-modal>

    <n-modal :show="!!deleteTarget" preset="card" title="删除这条记忆？" class="memory-modal delete-modal" :mask-closable="!deleting" :close-on-esc="!deleting" :closable="!deleting" @update:show="closeDelete">
      <p class="delete-title">{{ deleteTarget?.title }}</p>
      <p>删除后停止后续召回，不会改写已有聊天记录。</p>
      <template #footer>
        <div class="modal-actions">
          <n-button :disabled="deleting" @click="closeDelete(false)">取消</n-button>
          <n-button type="error" :loading="deleting" :disabled="deleting" @click="remove">确认删除</n-button>
        </div>
      </template>
    </n-modal>
  </div>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { useMessage } from 'naive-ui'
import { api, ApiError } from '../api/http'
import { ErrorCode, type UserWorkspace } from '../api/types'
import { agentMemories, type AgentMemory, type MemoryCategory, type MemoryInput } from '../api/agentMemories'

const message = useMessage()
const items = ref<AgentMemory[]>([])
const total = ref(0)
const page = ref(1)
const pageSize = 50
const query = ref('')
const workspaceFilter = ref<string | null>(null)
const appliedQuery = ref('')
const appliedWorkspace = ref<string | null>(null)
const loading = ref(false)
const listError = ref('')
const workspaces = ref<UserWorkspace[]>([])
const workspacesLoading = ref(false)
const workspaceError = ref('')
const editorOpen = ref(false)
const editing = ref<AgentMemory | null>(null)
const draft = ref<MemoryInput>(emptyDraft())
const conflicted = ref(false)
const saving = ref(false)
const deleting = ref(false)
const deleteTarget = ref<AgentMemory | null>(null)
let listRequest = 0
let mounted = true

const categoryOptions = [{ label: '常用偏好', value: 'preference' }, { label: '事实资料', value: 'fact' }]
const busy = computed(() => saving.value || deleting.value)
const workspaceOptions = computed(() => workspaces.value.map(item => ({ label: item.name, value: item.id })))
const filterOptions = computed(() => [{ label: '仅全局记忆', value: '' }, ...workspaceOptions.value])
// Select 使用空串表示全局，写入接口时仍显式发送 null。
const draftScope = computed({ get: () => draft.value.workspace_id ?? '', set: (value: string) => { draft.value.workspace_id = value || null } })
const missingWorkspace = computed(() => !!draft.value.workspace_id && !workspacesLoading.value && !workspaceError.value && !workspaces.value.some(item => item.id === draft.value.workspace_id))
const editorWorkspaceOptions = computed(() => [
  { label: '全局 · 本人的私有对话', value: '' },
  ...workspaceOptions.value,
  ...(missingWorkspace.value ? [{ label: '原工作区（已不可用）', value: draft.value.workspace_id!, disabled: true }] : []),
])
const canSave = computed(() => !busy.value && !conflicted.value && !workspacesLoading.value && !missingWorkspace.value
  && !(draft.value.workspace_id && workspaceError.value) && !!draft.value.title.trim() && !!draft.value.content.trim())

/** 新建默认全局事实资料，不继承搜索筛选或上一次编辑的范围。 */
function emptyDraft(): MemoryInput { return { title: '', content: '', category: 'fact', workspace_id: null } }
/** 页面直接呈现服务端错误，不把失败伪装成空列表。 */
function errorText(error: unknown): string { return error instanceof Error ? error.message : '请求失败，请稍后重试' }
/** 版本冲突不能通过更换范围或自动重试绕过。 */
function isConflict(error: unknown): boolean { return error instanceof ApiError && (error.code === ErrorCode.CONCURRENCY || error.status === 409) }
/** 404 可能来自记忆或工作区，保存时需复验所选范围，不能匹配错误文案猜测。 */
function isNotFound(error: unknown): boolean { return error instanceof ApiError && (error.code === ErrorCode.NOT_FOUND || error.status === 404) }
/** 使用稳定中文名称解释类型，不暴露枚举内部值。 */
function categoryLabel(category: MemoryCategory): string { return category === 'preference' ? '常用偏好' : '事实资料' }
/** 已失效范围继续显示工作区归属，不显示为全局。 */
function scopeLabel(item: AgentMemory): string { return item.workspace_id ? `工作区：${item.workspace_name || '已不可用'}` : '全局 · 本人私有对话' }
/** 缺失或异常时间保留占位，不显示 Invalid Date。 */
function formatDate(value: string): string { const date = new Date(value); return Number.isNaN(date.getTime()) ? '—' : date.toLocaleString('zh-CN', { hour12: false }) }

/** 查询序号阻止旧搜索或旧页响应覆盖最新结果。 */
async function loadList() {
  const request = ++listRequest
  loading.value = true
  listError.value = ''
  try {
    const data = await agentMemories.list({ q: appliedQuery.value || undefined, workspace_id: appliedWorkspace.value ?? undefined, limit: pageSize, offset: (page.value - 1) * pageSize })
    if (!mounted || request !== listRequest) return
    items.value = data.items
    total.value = data.total
    const lastPage = Math.max(1, Math.ceil(data.total / pageSize))
    if (page.value > lastPage) { page.value = lastPage; await loadList() }
  } catch (error) {
    if (mounted && request === listRequest) listError.value = errorText(error)
  } finally {
    if (mounted && request === listRequest) loading.value = false
  }
}
/** 只加载本人活跃工作区；读取失败时不允许保存未知绑定。 */
async function loadWorkspaces() {
  workspacesLoading.value = true
  workspaceError.value = ''
  try {
    const data = await api.workspaces.list()
    if (mounted) workspaces.value = data.items.filter(item => !item.deleted)
  } catch (error) {
    if (mounted) workspaceError.value = `工作区加载失败：${errorText(error)}。请刷新后再管理绑定记忆。`
  } finally { if (mounted) workspacesLoading.value = false }
}
/** 搜索显式提交后回到第一页，翻页沿用已提交条件。 */
function search() { if (busy.value) return; appliedQuery.value = query.value.trim(); appliedWorkspace.value = workspaceFilter.value; page.value = 1; void loadList() }
/** 刷新列表和工作区目录，不清空正在编辑的草稿。 */
async function refresh() { if (!busy.value) await Promise.all([loadList(), loadWorkspaces()]) }
/** 由服务端分页读取，避免只在当前页过滤造成遗漏。 */
function changePage(value: number) { page.value = value; void loadList() }
/** 复制保存版本和正文，编辑不会提前改变列表中的记录。 */
function openEditor(item?: AgentMemory) {
  if (busy.value) return
  editing.value = item ? { ...item } : null
  draft.value = item ? { title: item.title, content: item.content, category: item.category, workspace_id: item.workspace_id } : emptyDraft()
  conflicted.value = false
  editorOpen.value = true
}
/** 请求未完成时禁止关闭或切换目标，避免重复提交。 */
function closeEditor(show: boolean) { if (!saving.value) editorOpen.value = show }
/** 删除确认始终绑定打开时的记录及版本。 */
function closeDelete(show: boolean) { if (!show && !deleting.value) deleteTarget.value = null }

/** 保存固定草稿快照；版本冲突保留输入，但必须重开新版本才能再次保存。 */
async function save() {
  if (!canSave.value) return
  saving.value = true
  const original = editing.value
  const input = { ...draft.value, title: draft.value.title.trim(), content: draft.value.content.trim() }
  try {
    if (original) await agentMemories.update(original.id, { ...input, version: original.version })
    else await agentMemories.create(input)
    editorOpen.value = false
    message.success(original ? '记忆已更正' : '记忆已保存')
    await loadList()
  } catch (error) {
    if (isNotFound(error) && input.workspace_id) {
      // 新建与更正都可能遇到目录在编辑中失效；只更新目录，保留草稿和用户原选范围。
      await loadWorkspaces()
      if (workspaceError.value) { message.error(workspaceError.value); return }
      if (!workspaces.value.some(item => item.id === input.workspace_id)) { await loadList(); return }
    }
    if (original && (isConflict(error) || isNotFound(error))) { conflicted.value = true; await loadList() }
    else message.error(errorText(error))
  } finally { saving.value = false }
}
/** 删除成功后刷新当前页；冲突则关闭旧确认框并要求重新查看最新记录。 */
async function remove() {
  if (!deleteTarget.value || busy.value) return
  const target = deleteTarget.value
  deleting.value = true
  try {
    await agentMemories.remove(target.id, target.version)
    deleteTarget.value = null
    message.success('记忆已删除，后续对话不再召回')
    await loadList()
  } catch (error) {
    if (isConflict(error) || isNotFound(error)) { deleteTarget.value = null; message.warning('记忆已更新或删除，请查看刷新后的列表再操作'); await loadList() }
    else message.error(errorText(error))
  } finally { deleting.value = false }
}

onMounted(refresh)
onBeforeUnmount(() => { mounted = false; listRequest += 1 })
</script>

<style scoped>
.memories-page { max-width: 1100px; margin: 0 auto; display: flex; flex-direction: column; gap: 20px; }
.memories-header { display: flex; justify-content: space-between; align-items: center; gap: 20px; }
.eyebrow { color: var(--text-tertiary); font-size: 12px; letter-spacing: .08em; }
h1 { margin: 5px 0 8px; font-size: 26px; font-weight: 650; color: var(--text-primary); }
.memories-header p { margin: 0; color: var(--text-secondary); font-size: 14px; }
.memory-guidance { display: flex; align-items: center; flex-wrap: wrap; gap: 8px 14px; padding: 13px 16px; border-radius: 10px; background: var(--bg-elevated); font-size: 13px; color: var(--text-secondary); }
.privacy-label { color: var(--c-workspaces); font-weight: 600; }
.memories-panel { background: var(--bg-card, var(--bg-main)); border: 1px solid var(--border-subtle); border-radius: 12px; overflow: hidden; }
.memory-toolbar { display: grid; grid-template-columns: minmax(180px, 1fr) minmax(180px, 250px) auto auto; gap: 10px; padding: 20px 20px 12px; }
.list-caption { color: var(--text-secondary); font-size: 13px; padding: 0 20px 16px; }
.list-caption span { color: var(--text-tertiary); margin-left: 12px; }
.list-alert { margin: 0 20px 12px; width: auto; }
.memory-empty { padding: 65px 20px; text-align: center; }
.memory-empty p { margin: 18px 0 0; font-size: 13px; color: var(--text-tertiary); }
.memory-item { padding: 20px; border-top: 1px solid var(--border-subtle); }
.memory-item-top, .memory-heading, .memory-actions { display: flex; align-items: center; gap: 10px; }
.memory-item-top { justify-content: space-between; align-items: flex-start; }
.memory-heading { flex-wrap: wrap; min-width: 0; }
.memory-heading h2 { margin: 0; font-size: 16px; font-weight: 600; color: var(--text-primary); overflow-wrap: anywhere; }
.memory-category { flex-shrink: 0; font-size: 11px; padding: 3px 7px; border-radius: 5px; background: var(--bg-elevated); color: var(--text-secondary); }
.memory-category.preference { background: var(--t-workspaces); color: var(--c-workspaces); }
.memory-actions { flex-shrink: 0; }
.memory-content { margin: 13px 0 14px; color: var(--text-secondary); line-height: 1.7; font-size: 14px; white-space: pre-wrap; overflow-wrap: anywhere; display: -webkit-box; -webkit-line-clamp: 3; -webkit-box-orient: vertical; overflow: hidden; }
.memory-meta { display: flex; flex-wrap: wrap; gap: 5px 18px; font-size: 12px; color: var(--text-tertiary); overflow-wrap: anywhere; }
.memory-source { font-family: var(--font-mono, monospace); }
.memory-pagination { padding: 18px 20px; display: flex; justify-content: flex-end; border-top: 1px solid var(--border-subtle); }
.memory-modal { width: min(600px, calc(100vw - 32px)); }
.delete-modal { max-width: 440px; }
.delete-title { font-weight: 600; overflow-wrap: anywhere; }
.editor-alert { margin-bottom: 16px; }
.editor-options { display: grid; grid-template-columns: 1fr 1.5fr; gap: 14px; }
.editor-hint { margin: 0; color: var(--text-tertiary); font-size: 12px; line-height: 1.7; }
.modal-actions { display: flex; justify-content: flex-end; gap: 10px; }
@media (max-width: 680px) {
  .memories-header { align-items: flex-start; }
  h1 { font-size: 23px; }
  .memories-header p { line-height: 1.7; }
  .memory-toolbar { grid-template-columns: 1fr auto auto; padding: 16px; }
  .memory-toolbar > :first-child { grid-column: 1 / -1; }
  .memory-item { padding: 16px; }
  .memory-item-top { flex-direction: column; }
  .memory-actions { width: 100%; justify-content: flex-end; }
  .list-caption { padding: 0 16px 16px; line-height: 1.7; }
  .list-caption span { display: block; margin-left: 0; }
  .editor-options { grid-template-columns: 1fr; gap: 0; }
}
</style>
