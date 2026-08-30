<template>
  <n-modal
    :show="show"
    preset="card"
    :trap-focus="false"
    :auto-focus="false"
    :title="`Agent 提示词 · ${profileName || '协议档'}`"
    style="width: 900px; max-width: 96vw; border-radius: 14px"
    @update:show="emit('update:show', $event)"
  >
    <div class="agent-prompt-modal">
      <n-alert type="warning" :bordered="false">
        核心系统提示词仅供预览，无法在此覆盖。该协议档的补充提示词会在每个新回合注入，但核心安全、权限边界、错误契约与任务状态机始终优先。
      </n-alert>

      <div v-if="loading" class="prompt-state">正在读取提示词配置…</div>
      <template v-else-if="config">
        <div class="prompt-section">
          <div class="row-between">
            <span class="prompt-label">核心系统提示词（只读）</span>
            <span class="tag-soft">Harness 固定生成</span>
          </div>
          <n-input :value="config.base_prompt" type="textarea" readonly :autosize="{ minRows: 13, maxRows: 20 }" class="prompt-text mono" />
        </div>

        <div class="prompt-section">
          <div class="row-between">
            <span class="prompt-label">{{ profileName || '当前 Agent' }} 专属补充提示词</span>
            <span class="small tertiary">{{ overlay.length }} / 12000</span>
          </div>
          <n-input
            v-model:value="overlay"
            type="textarea"
            placeholder="例如：优先采用团队术语、输出模板或评测摘要口径。请勿填写 API Key、密码、Token、Cookie 等敏感信息。"
            :autosize="{ minRows: 8, maxRows: 14 }"
            :maxlength="12000"
            show-count
            class="prompt-text mono"
          />
        </div>
      </template>
      <div v-else class="prompt-state error">{{ loadError || '提示词配置不可用' }}</div>
    </div>

    <template #footer>
      <div class="row-between" style="width: 100%; gap: 12px">
        <span class="small tertiary">空文本会清除该协议档的补充提示词；保存不记录正文。</span>
        <div class="row" style="gap: 8px">
          <button class="btn btn-secondary btn-sm" :disabled="loading || saving" @click="loadConfig">刷新</button>
          <button class="btn btn-primary btn-sm" :disabled="!config || saving" @click="saveOverlay">{{ saving ? '保存中…' : '保存补充提示词' }}</button>
        </div>
      </div>
    </template>
  </n-modal>
</template>

<script setup lang="ts">
import { ref, watch } from 'vue'
import { NAlert, NInput, NModal, useMessage } from 'naive-ui'
import { api } from '../../api/http'
import type { AgentPromptConfig } from '../../api/types'

const props = defineProps<{
  show: boolean
  profileId: string | null
  profileName: string
}>()

const emit = defineEmits<{
  (event: 'update:show', value: boolean): void
  (event: 'saved', value: AgentPromptConfig): void
}>()

const message = useMessage()
const config = ref<AgentPromptConfig | null>(null)
const overlay = ref('')
const loading = ref(false)
const saving = ref(false)
const loadError = ref('')

/** 打开时重新读取指定 Agent 协议档的核心策略与补充层。 */
async function loadConfig() {
  if (!props.profileId) return
  loading.value = true
  loadError.value = ''
  try {
    const result = await api.admin.getAgentPrompt(props.profileId)
    config.value = result
    overlay.value = result.overlay
  } catch (error: any) {
    config.value = null
    loadError.value = error?.message || '提示词配置读取失败'
  } finally {
    loading.value = false
  }
}

/** 仅保存补充层，避免浏览器把核心策略作为可写配置提交。 */
async function saveOverlay() {
  if (!props.profileId || !config.value) return
  saving.value = true
  try {
    const result = await api.admin.updateAgentPrompt(props.profileId, { overlay: overlay.value })
    config.value = result
    overlay.value = result.overlay
    emit('saved', result)
    message.success('Agent 专属补充提示词已保存')
  } catch (error: any) {
    message.error(error?.message || '提示词保存失败')
  } finally {
    saving.value = false
  }
}

watch(
  () => [props.show, props.profileId] as const,
  ([visible, profileId]) => {
    if (visible && profileId) void loadConfig()
  },
)
</script>

<style scoped>
.agent-prompt-modal,
.prompt-section {
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.agent-prompt-modal {
  gap: 14px;
}
.prompt-label {
  font-size: 13px;
  font-weight: 700;
  color: var(--text-primary, #111827);
}
.prompt-text :deep(textarea) {
  font-family: var(--font-mono, ui-monospace, monospace);
  font-size: 12px;
  line-height: 1.65;
}
.prompt-state {
  padding: 28px 16px;
  text-align: center;
  color: var(--text-secondary, #6b7280);
}
.prompt-state.error {
  color: var(--accent-error, #dc2626);
}
</style>
