<template>
  <n-modal
    :show="show"
    preset="card"
    :title="isEdit ? '编辑模型协议档' : '新增模型协议档'"
    style="width: 580px"
    @update:show="$emit('update:show', $event)"
  >
    <div class="profile-form">
      <div class="field">
        <label class="field-label">协议档名称 <span class="req">*</span></label>
        <n-input v-model:value="form.name" placeholder="例如：OpenAI GPT-4o 或 Claude 3.5 Sonnet" />
      </div>

      <div class="form-row">
        <div class="field">
          <label class="field-label">协议类型 <span class="req">*</span></label>
          <n-select v-model:value="form.protocol" :options="protocolOptions" />
        </div>
        <div class="field">
          <label class="field-label">模型标识名 <span class="req">*</span></label>
          <n-input v-model:value="form.model" placeholder="例如：gpt-4o / claude-3-5-sonnet" />
        </div>
      </div>

      <div class="field">
        <label class="field-label">Base URL <span class="req">*</span></label>
        <!-- P3 厂商预设：按当前协议一键填充典型 base_url / model（对齐原型 admin-profiles.html 278） -->
        <div class="row" style="gap: 6px">
          <n-input
            v-model:value="form.base_url"
            class="grow"
            placeholder="https://api.openai.com/v1 或内网代理地址"
          />
          <button class="btn btn-ai btn-sm" type="button" style="flex: 0 0 auto" @click="applyVendorPreset">
            ✨ 厂商预设
          </button>
        </div>
      </div>

      <div class="field">
        <label class="field-label">
          API Key
          <span v-if="!isEdit" class="req">*</span>
          <span style="font-size: 11px; color: var(--text-tertiary); margin-left: 6px">(平台只写不回显，留空表示不修改)</span>
        </label>
        <n-input
          v-model:value="form.api_key"
          type="password"
          show-password-on="click"
          placeholder="输入 API Key"
        />
      </div>

      <div v-if="form.protocol === 'anthropic_messages'" class="field">
        <label class="field-label">Anthropic Version Header</label>
        <n-input v-model:value="form.anthropic_version" placeholder="2023-06-01 (默认)" />
      </div>

      <div class="field">
        <label class="field-label">用途标签</label>
        <n-checkbox-group v-model:value="form.usages">
          <n-space>
            <n-checkbox value="target" label="可作为被测目标" />
            <n-checkbox value="judge" label="可作为大模型裁判" />
            <n-checkbox value="agent" label="可作为智能体后台" />
          </n-space>
        </n-checkbox-group>
      </div>
    </div>

    <template #footer>
      <div style="display: flex; gap: 8px; justify-content: flex-end">
        <n-button @click="$emit('update:show', false)">取消</n-button>
        <n-button type="primary" :loading="saving" @click="handleSave">
          保存协议档
        </n-button>
      </div>
    </template>
  </n-modal>
</template>

<script setup lang="ts">
import { ref, computed, watch } from 'vue'
import { useMessage } from 'naive-ui'
import { api } from '../../api/http'
import type { Profile, ProtocolType, ProfileUsage } from '../../api/types'

const props = defineProps<{
  show: boolean
  profile?: Profile | null
}>()

const emit = defineEmits<{
  (e: 'update:show', val: boolean): void
  (e: 'success'): void
}>()

const message = useMessage()
const saving = ref(false)

const isEdit = computed(() => !!props.profile?.id)

const form = ref<{
  name: string
  protocol: ProtocolType
  base_url: string
  model: string
  api_key: string
  anthropic_version?: string
  usages: ProfileUsage[]
}>({
  name: '',
  protocol: 'openai_chat',
  base_url: 'https://api.openai.com/v1',
  model: '',
  api_key: '',
  anthropic_version: '2023-06-01',
  usages: ['target'],
})

const protocolOptions = [
  { label: 'OpenAI Chat (/chat/completions)', value: 'openai_chat' },
  { label: 'OpenAI Responses (/responses)', value: 'openai_responses' },
  { label: 'Anthropic Messages (/messages)', value: 'anthropic_messages' },
]
// 契约核对（API.md §枚举）：protocol 仅 openai_chat / openai_responses / anthropic_messages 三种，
// profile_usage 仅 target / agent / judge 三种；原型的 ollama_local、lightrag_native、external_chat
// 均不在契约内，按 AGENTS.md 红线保持现状不扩充。

/**
 * P3 厂商预设表（对齐原型 admin-profiles.html 303-316）：
 * 按当前所选协议自动填充典型 base_url 与 model，仅填充表单、不直接提交。
 * 注：原型中的 ollama_local 预设因契约无该协议枚举，此处不实现。
 */
const VENDOR_PRESETS: Record<ProtocolType, { base_url: string; model: string }> = {
  openai_chat: { base_url: 'https://api.openai.com/v1', model: 'gpt-4.1' },
  openai_responses: { base_url: 'https://api.openai.com/v1', model: 'gpt-4.1' },
  anthropic_messages: { base_url: 'https://api.anthropic.com', model: 'claude-3-7-sonnet-20250219' },
}

/** 应用厂商预设：覆盖 Base URL 与模型标识输入框 */
function applyVendorPreset() {
  const preset = VENDOR_PRESETS[form.value.protocol]
  if (!preset) return
  form.value.base_url = preset.base_url
  form.value.model = preset.model
  message.info('已填充典型厂商参数')
}

watch(
  () => props.show,
  (val) => {
    if (val) {
      if (props.profile) {
        form.value = {
          name: props.profile.name,
          protocol: props.profile.protocol,
          base_url: props.profile.base_url,
          model: props.profile.model,
          api_key: '',
          anthropic_version: props.profile.anthropic_version || '2023-06-01',
          usages: props.profile.usages ? [...props.profile.usages] : ['target'],
        }
      } else {
        form.value = {
          name: '',
          protocol: 'openai_chat',
          base_url: 'https://api.openai.com/v1',
          model: '',
          api_key: '',
          anthropic_version: '2023-06-01',
          usages: ['target'],
        }
      }
    }
  },
)

async function handleSave() {
  if (!form.value.name.trim()) {
    message.warning('请输入协议档名称')
    return
  }
  if (!form.value.model.trim()) {
    message.warning('请输入模型标识名')
    return
  }
  if (!form.value.base_url.trim()) {
    message.warning('请输入 Base URL')
    return
  }
  if (!isEdit.value && !form.value.api_key.trim()) {
    message.warning('请输入 API Key')
    return
  }

  saving.value = true
  try {
    if (isEdit.value && props.profile?.id) {
      const payload: any = {
        name: form.value.name,
        protocol: form.value.protocol,
        base_url: form.value.base_url,
        model: form.value.model,
        anthropic_version: form.value.anthropic_version,
        usages: form.value.usages,
      }
      if (form.value.api_key.trim()) {
        payload.api_key = form.value.api_key
      }
      await api.profiles.update(props.profile.id, payload)
      message.success('协议档已更新')
    } else {
      await api.profiles.create(form.value)
      message.success('协议档创建成功')
    }
    emit('update:show', false)
    emit('success')
  } catch (err: any) {
    message.error(err.message || '保存失败')
  } finally {
    saving.value = false
  }
}
</script>

<style scoped>
.profile-form {
  display: flex;
  flex-direction: column;
  gap: 12px;
}
.field {
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.field-label {
  font-size: 13px;
  font-weight: 500;
  color: var(--text-secondary);
}
.field-label .req {
  color: var(--accent-error);
}
.form-row {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 12px;
}
</style>
