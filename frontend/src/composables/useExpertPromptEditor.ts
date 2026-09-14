import { computed, ref } from 'vue'
import type { AgentExpertPromptDocument } from '../api/types'

/** 编辑器只依赖提示词读写接口，方便独立验证乱序请求与草稿保护。 */
interface ExpertPromptApi {
  getAgentExpertPrompt(id: string): Promise<AgentExpertPromptDocument>
  updateAgentExpertPrompt(id: string, payload: { content: string; expected_revision: string }): Promise<AgentExpertPromptDocument>
}

/** 以请求代次隔离专家切换；保存仅使用已加载文档的 ID 和修订。 */
export function useExpertPromptEditor(api: ExpertPromptApi) {
  const document = ref<AgentExpertPromptDocument | null>(null)
  const draft = ref('')
  const loading = ref(false)
  const saving = ref(false)
  const loadError = ref('')
  let generation = 0
  const normalized = computed(() => draft.value.replace(/\r\n/g, '\n').trim())
  const dirty = computed(() => !!document.value && normalized.value !== document.value.content)
  // 发布基线恰好追平旧覆盖时，仍允许保存相同文本以清除冗余覆盖层。
  const canSave = computed(() => (
    dirty.value || (!!document.value?.overridden && normalized.value === document.value.builtin_content)
  ) && !!normalized.value && !loading.value && !saving.value)

  /** 关闭或切换专家后让所有旧读取失效，不能继续使用上一份修订提交。 */
  function reset() {
    generation += 1
    document.value = null
    draft.value = ''
    loading.value = false
    loadError.value = ''
  }

  /** 刷新立即清除旧文档，只有最新请求可以更新界面或错误状态。 */
  async function load(id: string) {
    reset()
    const request = generation
    loading.value = true
    try {
      const result = await api.getAgentExpertPrompt(id)
      if (request !== generation) return
      document.value = result
      draft.value = result.content
    } catch (error: unknown) {
      if (request === generation) loadError.value = error instanceof Error ? error.message : '专家提示词读取失败'
    } finally {
      if (request === generation) loading.value = false
    }
  }

  /** 捕获本次提交快照，拒绝重复保存；失败保留原草稿与修订供用户处理冲突。 */
  async function save(): Promise<AgentExpertPromptDocument | null> {
    const current = document.value
    if (!current || !canSave.value) return null
    const request = generation
    const submittedDraft = draft.value
    saving.value = true
    try {
      const result = await api.updateAgentExpertPrompt(current.expert_id, {
        content: submittedDraft,
        expected_revision: current.revision,
      })
      if (request === generation) {
        document.value = result
        // 即使未来允许保存期间编辑，也不得用服务器响应覆盖新输入。
        if (draft.value === submittedDraft) draft.value = result.content
      }
      return result
    } finally {
      saving.value = false
    }
  }

  /** 恢复操作只替换草稿，沿用明确的保存动作提交到服务端。 */
  function restoreBuiltin() {
    if (document.value && !loading.value && !saving.value) draft.value = document.value.builtin_content
  }

  return { document, draft, loading, saving, loadError, dirty, canSave, reset, load, save, restoreBuiltin }
}
