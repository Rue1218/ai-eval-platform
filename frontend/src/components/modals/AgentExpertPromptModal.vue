<template>
  <n-modal
    :show="show"
    preset="card"
    :trap-focus="false"
    :auto-focus="false"
    :closable="!saving"
    :mask-closable="!saving"
    :close-on-esc="!saving"
    :title="`专家提示词 · ${expertName || '专家'}`"
    style="width: 900px; max-width: 96vw; border-radius: 14px"
    @update:show="handleVisibility"
  >
    <div class="expert-prompt-modal">
      <n-alert type="info" :bordered="false">
        此配置仅补充当前专家的工作方法与领域流程。核心安全、权限边界、错误契约和任务状态机始终优先；审计记录不包含提示词正文。
      </n-alert>

      <div v-if="loading" class="expert-prompt-state">正在读取专家提示词…</div>
      <template v-else-if="document">
        <div class="expert-prompt-meta">
          <span class="tag-soft">{{ document.overridden ? '已定制' : '内置基线' }}</span>
          <span class="small tertiary">修订 {{ document.revision }}</span>
          <span class="small tertiary">{{ draft.length }} / 30000</span>
        </div>

        <div class="expert-prompt-section">
          <div class="row-between">
            <span class="expert-prompt-label">{{ expertName || document.name }} 的有效提示词</span>
            <span class="small tertiary">下一个回合生效</span>
          </div>
          <n-input
            v-model:value="draft"
            type="textarea"
            :autosize="{ minRows: 18, maxRows: 30 }"
            :maxlength="30000"
            :disabled="saving"
            show-count
            class="expert-prompt-text mono"
          />
        </div>
      </template>
      <div v-else class="expert-prompt-state error">{{ loadError || '专家提示词不可用' }}</div>
    </div>

    <template #footer>
      <div class="row-between" style="width: 100%; gap: 12px">
        <span class="small tertiary">恢复内置仅替换草稿，保存后才生效。{{ dirty ? '有未保存修改。' : '' }}</span>
        <div class="row" style="gap: 8px">
          <button class="btn btn-secondary btn-sm" :disabled="loading || saving" @click="refreshDocument">刷新</button>
          <button
            v-if="document && (document.overridden || draft !== document.builtin_content)"
            class="btn btn-secondary btn-sm"
            :disabled="loading || saving"
            @click="restoreBuiltin"
          >
            恢复内置
          </button>
          <button class="btn btn-primary btn-sm" :disabled="!canSave" @click="saveDocument">
            {{ saving ? '保存中…' : '保存专家提示词' }}
          </button>
        </div>
      </div>
    </template>
  </n-modal>
</template>

<script setup lang="ts">
import { onBeforeUnmount, watch } from 'vue'
import { NAlert, NInput, NModal, useDialog, useMessage } from 'naive-ui'
import { api } from '../../api/http'
import type { AgentExpertPromptDocument } from '../../api/types'
import { useExpertPromptEditor } from '../../composables/useExpertPromptEditor'

const props = defineProps<{
  show: boolean
  expertId: string | null
  expertName: string
}>()

const emit = defineEmits<{
  (event: 'update:show', value: boolean): void
  (event: 'saved', value: AgentExpertPromptDocument): void
}>()

const message = useMessage()
const dialog = useDialog()
const editor = useExpertPromptEditor(api.admin)
const { document, draft, loading, saving, loadError, dirty, canSave, restoreBuiltin } = editor

/** 打开时读取专家当前生效的提示词，避免以旧修订直接覆盖其他成员的更改。 */
async function loadDocument() {
  if (props.show && props.expertId) await editor.load(props.expertId)
}

/** 刷新和关闭均先确认丢弃草稿，取消操作时完整保留编辑内容。 */
function confirmDiscard(action: () => void) {
  if (!dirty.value) return action()
  dialog.warning({
    title: '放弃未保存的修改？',
    content: '当前专家提示词有未保存的草稿，继续将丢弃这些修改。',
    positiveText: '放弃修改',
    negativeText: '继续编辑',
    onPositiveClick: action,
  })
}

/** 保存期间不能关闭弹窗，避免用户无法判断请求是否已生效。 */
function handleVisibility(visible: boolean) {
  if (!visible && !saving.value) confirmDiscard(() => emit('update:show', false))
}

/** 主动刷新可能丢弃草稿，需与首次加载区分。 */
function refreshDocument() {
  if (!loading.value && !saving.value) confirmDiscard(() => { void loadDocument() })
}

/** 保存当前有效文本；服务端验证安全边界并用修订指纹拒绝并发覆盖。 */
async function saveDocument() {
  try {
    const result = await editor.save()
    if (!result) return
    emit('saved', result)
    message.success('专家提示词已保存，下一个回合生效')
  } catch (error: any) {
    message.error(error?.message || '专家提示词保存失败，请刷新后重试')
  }
}

watch(
  () => [props.show, props.expertId] as const,
  ([visible, expertId]) => {
    if (visible && expertId) void loadDocument()
    else editor.reset()
  },
  { immediate: true },
)
onBeforeUnmount(editor.reset)
</script>

<style scoped>
.expert-prompt-modal,
.expert-prompt-section {
  display: flex;
  flex-direction: column;
  gap: 10px;
}
.expert-prompt-modal {
  gap: 14px;
}
.expert-prompt-meta {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 8px;
}
.expert-prompt-label {
  font-size: 13px;
  font-weight: 700;
  color: var(--text-primary, #111827);
}
.expert-prompt-text :deep(textarea) {
  font-family: var(--font-mono, ui-monospace, monospace);
  font-size: 12px;
  line-height: 1.65;
}
.expert-prompt-state {
  padding: 28px 16px;
  text-align: center;
  color: var(--text-secondary, #6b7280);
}
.expert-prompt-state.error {
  color: var(--accent-error, #dc2626);
}
</style>
