<template>
  <n-modal
    :show="show"
    preset="card"
    :trap-focus="false"
    :auto-focus="false"
    :title="`SKILL.md · ${skillId || '技能文件'}`"
    style="width: 900px; max-width: 96vw; border-radius: 14px"
    @update:show="emit('update:show', $event)"
  >
    <div class="skill-file-modal">
      <n-alert type="info" :bordered="false">
        预览前服务端会确认此技能的 <code>SKILL.md</code> 存在并符合统一规格。目录阶段只读取头部；完整工作流仅在本页预览或 Agent 选中技能后按需加载。
      </n-alert>

      <div v-if="loading" class="skill-file-state">正在读取技能文件…</div>
      <div v-else-if="loadError" class="skill-file-state error">{{ loadError }}</div>
      <template v-else-if="document">
        <div class="skill-file-meta">
          <span class="tag-soft mono">{{ document.metadata.kind }}</span>
          <span class="tag-soft">v{{ document.metadata.version }}</span>
          <span class="tag-soft" :class="document.metadata.enabled ? 'enabled' : 'disabled'">
            {{ document.metadata.enabled ? '已启用' : '能力未启用' }}
          </span>
          <span class="small tertiary">修订 {{ document.revision }}</span>
        </div>

        <n-input
          v-if="editing"
          v-model:value="draft"
          type="textarea"
          :autosize="{ minRows: 22, maxRows: 30 }"
          class="skill-file-editor mono"
        />
        <pre v-else class="skill-file-preview">{{ document.content }}</pre>
      </template>
    </div>

    <template #footer>
      <div class="row-between" style="width: 100%; gap: 12px">
        <span class="small tertiary">固定头部 + <span class="mono">## 工作流</span>；保存采用修订指纹并发保护。</span>
        <div class="row" style="gap: 8px">
          <button class="btn btn-secondary btn-sm" :disabled="loading || saving" @click="loadDocument">刷新预览</button>
          <button v-if="!editing" class="btn btn-sign btn-sm" :disabled="!document || loading" @click="startEditing">编辑文件</button>
          <template v-else>
            <button class="btn btn-secondary btn-sm" :disabled="saving" @click="cancelEditing">取消编辑</button>
            <button class="btn btn-primary btn-sm" :disabled="saving" @click="saveDocument">{{ saving ? '保存中…' : '保存 SKILL.md' }}</button>
          </template>
        </div>
      </div>
    </template>
  </n-modal>
</template>

<script setup lang="ts">
import { ref, watch } from 'vue'
import { NAlert, NInput, NModal, useMessage } from 'naive-ui'
import { api } from '../../api/http'
import type { AgentSkillDocument } from '../../api/types'

const props = defineProps<{
  show: boolean
  skillId: string | null
}>()

const emit = defineEmits<{
  (event: 'update:show', value: boolean): void
  (event: 'saved', value: AgentSkillDocument): void
}>()

const message = useMessage()
const document = ref<AgentSkillDocument | null>(null)
const draft = ref('')
const loading = ref(false)
const saving = ref(false)
const editing = ref(false)
const loadError = ref('')

/** 每次打开或切换技能时重新读取真实文件，避免编辑过期副本。 */
async function loadDocument() {
  if (!props.skillId) return
  loading.value = true
  loadError.value = ''
  try {
    const result = await api.admin.getAgentSkill(props.skillId)
    document.value = result
    draft.value = result.content
    editing.value = false
  } catch (error: any) {
    document.value = null
    loadError.value = error?.message || '技能文件读取失败'
  } finally {
    loading.value = false
  }
}

/** 进入编辑前保留当前修订的完整文本，保存时由服务端执行并发校验。 */
function startEditing() {
  if (!document.value) return
  draft.value = document.value.content
  editing.value = true
}

function cancelEditing() {
  draft.value = document.value?.content || ''
  editing.value = false
}

/** 保存统一规格的 Skill 文件；冲突后要求刷新预览，不在浏览器强行覆盖。 */
async function saveDocument() {
  if (!props.skillId || !document.value) return
  saving.value = true
  try {
    const result = await api.admin.updateAgentSkill(props.skillId, {
      content: draft.value,
      expected_revision: document.value.revision,
    })
    document.value = result
    draft.value = result.content
    editing.value = false
    emit('saved', result)
    message.success('SKILL.md 已保存并写入审计记录')
  } catch (error: any) {
    message.error(error?.message || '技能文件保存失败，请刷新预览后重试')
  } finally {
    saving.value = false
  }
}

watch(
  () => [props.show, props.skillId] as const,
  ([visible, skillId]) => {
    if (visible && skillId) void loadDocument()
  },
)
</script>

<style scoped>
.skill-file-modal {
  display: flex;
  flex-direction: column;
  gap: 12px;
}
.skill-file-meta {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 6px;
}
.tag-soft.enabled {
  color: var(--accent-success, #10b981);
}
.tag-soft.disabled {
  color: var(--accent-warning, #d97706);
}
.skill-file-preview {
  margin: 0;
  padding: 14px;
  max-height: min(62vh, 680px);
  overflow: auto;
  white-space: pre-wrap;
  overflow-wrap: anywhere;
  border: 1px solid var(--border-subtle, #e5e7eb);
  border-radius: 8px;
  background: var(--bg-elevated, #f4f8f8);
  color: var(--text-primary, #111827);
  font: 12px/1.65 var(--font-mono, ui-monospace, monospace);
}
.skill-file-editor :deep(textarea) {
  font-family: var(--font-mono, ui-monospace, monospace);
  font-size: 12px;
  line-height: 1.65;
}
.skill-file-state {
  padding: 28px 16px;
  text-align: center;
  color: var(--text-secondary, #6b7280);
}
.skill-file-state.error {
  color: var(--accent-error, #dc2626);
}
</style>
