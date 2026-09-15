<template>
  <n-modal
    :show="show"
    preset="card"
    :trap-focus="false"
    :auto-focus="false"
    :title="isEdit ? '编辑模型协议档' : '新增模型协议档'"
    style="width: 620px; max-width: 95vw"
    @update:show="$emit('update:show', $event)"
  >
    <div class="profile-form">
      <div class="field">
        <label class="field-label">协议档名称 <span class="req">*</span></label>
        <n-input v-model:value="form.name" placeholder="例如：DeepSeek 日常助手" />
      </div>

      <!-- 供应商快捷分类预设选择 -->
      <div class="field">
        <label class="field-label">供应商快速填充</label>
        <div class="vendor-picker">
          <button v-for="vendor in PROFILE_VENDORS" :key="vendor.key" type="button" :class="{selected:selectedVendor === vendor.key}" :aria-pressed="selectedVendor === vendor.key" @click="selectedVendor = vendor.key; handleSelectVendor(vendor.key)">
            <ProviderLogo :provider="vendor.key"/><span>{{ vendor.name }}</span>
          </button>
        </div>
      </div>

      <div class="form-row">
        <div class="field">
          <label class="field-label">协议类型 <span class="req">*</span></label>
          <n-select v-model:value="form.protocol" :options="protocolOptions" />
        </div>
        <div class="field">
          <label class="field-label">
            <span>模型标识名 <span class="req">*</span></span>
            <ProviderLogo v-if="form.model.trim()" :provider="getModelLogoKey(form.model)" compact :size="16" />
          </label>
          <div class="row" style="gap: 6px">
            <n-input
              v-model:value="form.model"
              class="grow"
              placeholder="选择或输入供应商的模型 ID"
              @update:value="handleManualModelChange"
            />
            <n-button
              type="info"
              secondary
              size="small"
              :loading="fetchingModels"
              :disabled="form.full_url"
              style="flex: 0 0 auto"
              title="根据当前 Base URL 和 API Key 从服务端点拉取所有可用模型 ID"
              @click="handleFetchRemoteModels"
            >
              获取模型 (/models)
            </n-button>
          </div>
        </div>
      </div>

      <div v-if="modelParameterDefinitions.length" class="field">
        <label class="field-label">模型请求字段（由 /models 目录提供）</label>
        <div class="model-parameter-grid">
          <div v-for="parameter in modelParameterDefinitions" :key="parameter.id" class="field">
            <label class="small tertiary">{{ parameter.id }}</label>
            <n-select
              :value="modelParameterValues[parameter.id] || null"
              :options="modelParameterOptions(parameter)"
              clearable
              placeholder="保持端点默认值"
              @update:value="value => updateModelParameter(parameter.id, value)"
            />
          </div>
        </div>
        <span class="small tertiary">
          已保存为 <code>{{ form.model }}</code>，调用时作为模型标识原样传给端点。
        </span>
        <span v-if="selectedModelOwner === 'cursorapi'" class="small tertiary">
          CursorAPI 仅从模型标识读取这些字段；原生 Function Calling 可用，但它不会向 OpenAI 流回传可展示的思考过程。
        </span>
      </div>

      <div class="field">
        <div class="row-between">
          <label class="field-label">{{ form.full_url ? '完整请求 URL' : 'Base URL' }} <span class="req">*</span></label>
          <label class="url-mode"><span>完整 URL</span><n-switch v-model:value="form.full_url" size="small" aria-label="完整 URL" /></label>
        </div>
        <n-input
          v-model:value="form.base_url"
          :placeholder="form.full_url ? 'https://api.example.com/v1/chat/completions' : 'https://api.openai.com/v1'"
        />
      </div>

      <p class="field-hint">{{ form.full_url ? '原样使用此地址，不追加任何协议后缀。请手动填写模型标识。' : '自动补齐协议请求路径；已有的供应商版本路径会保留。' }}</p>

      <div class="field">
        <label class="field-label">思考模板 <span class="req">*</span></label>
        <n-select
          v-model:value="form.reasoning_template_id"
          :options="reasoningTemplateOptions"
          :loading="loadingTemplates"
          :disabled="!reasoningTemplates.length"
          placeholder="请先选择供应商以加载模板"
        />
        <span class="small tertiary">{{ selectedTemplate?.description || '模板会在保存前以真实请求验证，未通过不会保存模型。' }}</span>
        <span v-if="props.profile?.reasoning_probe_status" class="small tertiary">当前状态：{{ probeStatusText }}</span>
      </div>

      <div class="field">
        <div class="row-between">
          <label class="field-label">
            API Key
            <span style="font-size: 11.5px; color: var(--text-tertiary); margin-left: 6px">(平台受控加密存储不回显；编辑时留空保留原密钥)</span>
          </label>
          <span v-if="props.profile?.has_api_key" class="key-status-badge ok">
            ● 已配置密钥
          </span>
          <span v-else class="key-status-badge none">
            ○ 未配置密钥
          </span>
        </div>
        <n-input
          v-model:value="form.api_key"
          type="password"
          show-password-on="click"
          :placeholder="props.profile?.has_api_key ? '********* (已配置密钥，留空保留原密钥)' : '可选；私有端点或免密模型可留空'"
        />
      </div>

      <div v-if="form.protocol === 'anthropic_messages'" class="field">
        <label class="field-label">Anthropic Version Header</label>
        <n-input v-model:value="form.anthropic_version" placeholder="2023-06-01 (默认)" />
      </div>



      <div class="field">
        <label class="field-label">上下文窗口大小 (Context Window)</label>
        <n-input-number v-model:value="form.context_window" :min="1000" :max="10000000" :precision="0" :show-button="false" aria-label="上下文窗口大小" />
        <n-radio-group v-model:value="form.context_window" name="context_window_group" size="small">
          <n-space :size="8">
            <n-radio-button :value="200000">200k (默认)</n-radio-button>
            <n-radio-button :value="256000">256k</n-radio-button>
            <n-radio-button :value="500000">500k</n-radio-button>
            <n-radio-button :value="1000000">1M</n-radio-button>
          </n-space>
        </n-radio-group>
      </div>

      <div class="field">
        <label class="field-label">Agent 单回合输出上限 (Max Output Tokens)</label>
        <n-input-number
          v-model:value="form.max_output_tokens"
          :min="256"
          :max="131072"
          :step="1024"
          :precision="0"
          aria-label="输出上限"
          style="width: 220px"
        />
        <span class="small tertiary">模型单回合回答的最大输出 token 数（默认 8192）；长文档总结/导出类任务可调大，避免回答被截断。</span>
      </div>

      <div class="field">
        <label class="field-label">Agent 工具调用模式</label>
        <n-radio-group v-model:value="form.tool_call_mode" name="tool_call_mode_group" size="small">
          <n-space :size="8">
            <n-radio-button value="native">原生 ToolCall（默认）</n-radio-button>
            <n-radio-button value="legacy">兼容 JSON-ReAct</n-radio-button>
          </n-space>
        </n-radio-group>
        <span class="small tertiary">默认使用原生模式；仅在目标网关不支持 tools 字段时切换为兼容模式。已有协议档保持原设置。</span>
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
          {{ isEdit ? '测试并更新' : '测试并添加' }}
        </n-button>
      </div>
    </template>
  </n-modal>

  <FetchModelsModal
    v-model:show="showFetchModal"
    :models="fetchedModelList"
    @select="onModelSelect"
    @batch-create="onBatchCreate"
  />
</template>

<script setup lang="ts">
import { PROFILE_VENDORS } from '../../utils/profileVendors'
import { getModelLogoKey } from '../../utils/providerLogo'
import ProviderLogo from '../ProviderLogo.vue'

import { ref, computed, watch } from 'vue'
import {
  useMessage,
  NRadioGroup,
  NRadioButton,
  NSpace,
  NCheckboxGroup,
  NCheckbox,
  NSelect,
  NInput,
  NInputNumber,
  NButton,
  NModal,
  NSwitch,
} from 'naive-ui'
import { api } from '../../api/http'
import type {
  Profile,
  ProfileProbeCreateIn,
  ProfileProbeUpdateIn,
  ProtocolType,
  ProfileUsage,
  ReasoningTemplate,
  RemoteModel,
  RemoteModelParameter,
  ToolCallMode,
} from '../../api/types'
import FetchModelsModal from './FetchModelsModal.vue'

const props = defineProps<{
  show: boolean
  profile?: Profile | null
  initialData?: {
    vendorKey?: string
    base_url?: string
    full_url?: boolean
    protocol?: ProtocolType
    name?: string
  } | null
}>()

const emit = defineEmits<{
  (e: 'update:show', val: boolean): void
  (e: 'success'): void
}>()

const message = useMessage()
const saving = ref(false)
const fetchingModels = ref(false)
const showFetchModal = ref(false)
const fetchedModelList = ref<RemoteModel[]>([])
const selectedVendor = ref<string | null>(null)
const selectedModelId = ref('')
const selectedModelOwner = ref<string | undefined>()
const modelParameterDefinitions = ref<RemoteModelParameter[]>([])
const modelParameterValues = ref<Record<string, string>>({})
const reasoningTemplates = ref<ReasoningTemplate[]>([])
const loadingTemplates = ref(false)

const isEdit = computed(() => !!props.profile?.id)

const form = ref<{
  name: string
  protocol: ProtocolType
  base_url: string
  full_url: boolean
  model: string
  api_key: string
  anthropic_version?: string
  usages: ProfileUsage[]
  context_window: number
  max_output_tokens: number
  tool_call_mode: ToolCallMode
  reasoning_template_id: string
}>({
  name: '',
  protocol: 'openai_chat',
  base_url: 'https://api.openai.com/v1',
  model: '',
  api_key: '',
  anthropic_version: '2023-06-01',
  usages: ['target'],
  context_window: 200000,
  max_output_tokens: 8192,
  tool_call_mode: 'native',
  full_url: false,
  reasoning_template_id: '',
})

const protocolOptions = [
  { label: 'OpenAI Chat (/chat/completions)', value: 'openai_chat' },
  { label: 'Anthropic Messages (/messages)', value: 'anthropic_messages' },
]

const VENDOR_MAP = Object.fromEntries(PROFILE_VENDORS.map(v => [v.key, v]))
const TEMPLATE_PROVIDER: Record<string, string> = { gemini: 'google' }
const VENDOR_BY_PROVIDER: Record<string, string> = { google: 'gemini' }
const reasoningTemplateOptions = computed(() => reasoningTemplates.value.map(template => ({ label: template.name, value: template.id })))
const selectedTemplate = computed(() => reasoningTemplates.value.find(template => template.id === form.value.reasoning_template_id) || null)
const probeStatusText = computed(() => ({ legacy: '旧规则兼容', unverified: '待验证', passed: '已通过', partial: '部分通过', failed: '验证失败' }[props.profile?.reasoning_probe_status || 'legacy']))

function currentProvider() {
  const vendor = selectedVendor.value || VENDOR_BY_PROVIDER[props.profile?.provider || ''] || props.profile?.provider || ''
  return TEMPLATE_PROVIDER[vendor] || vendor
}

async function loadReasoningTemplates() {
  const provider = currentProvider()
  if (!provider) {
    reasoningTemplates.value = []
    form.value.reasoning_template_id = ''
    return
  }
  loadingTemplates.value = true
  try {
    const templates = await api.profiles.listReasoningTemplates(provider, form.value.protocol)
    reasoningTemplates.value = templates
    if (!templates.some(template => template.id === form.value.reasoning_template_id)) {
      form.value.reasoning_template_id = templates[0]?.id || ''
    }
  } catch (err: any) {
    reasoningTemplates.value = []
    form.value.reasoning_template_id = ''
    message.error(err.message || '获取思考模板失败')
  } finally {
    loadingTemplates.value = false
  }
}

async function handleSelectVendor(val: string | null) {
  if (!val || !VENDOR_MAP[val]) return
  clearModelParameters()
  const item = VENDOR_MAP[val]
  form.value.api_key = ''
  fetchedModelList.value = []
  form.value.full_url = false
  form.value.base_url = item.base_url
  form.value.protocol = item.protocol
  form.value.context_window = item.context_window || 200000
  form.value.model = item.model
  form.value.name = `${item.name} (${item.model})`
  await loadReasoningTemplates()
  message.info(`已快速填充 ${item.name} 厂商端点与协议配置`)
}

async function handleFetchRemoteModels() {
  if (!form.value.base_url.trim()) {
    message.warning('请先填写 Base URL')
    return
  }
  fetchingModels.value = true
  try {
    const res = await api.profiles.fetchModels({
      base_url: form.value.base_url.trim(),
      full_url: form.value.full_url,
      protocol: form.value.protocol,
      api_key: form.value.api_key.trim() || undefined,
      profile_id: props.profile?.id,
      anthropic_version: form.value.anthropic_version?.trim() || undefined,
    })
    const list = Array.isArray(res) ? res : res.models || []
    if (!list.length) {
      message.warning('服务端未返回可用模型列表，请手动输入模型标识名')
      return
    }
    fetchedModelList.value = list
    showFetchModal.value = true
  } catch (err: any) {
    message.error(err.message || '获取远程模型列表失败，请检查 Base URL 与 API Key')
  } finally {
    fetchingModels.value = false
  }
}

function clearModelParameters() {
  selectedModelId.value = ''
  selectedModelOwner.value = undefined
  modelParameterDefinitions.value = []
  modelParameterValues.value = {}
}

function configuredModelName() {
  const parameters = modelParameterDefinitions.value
    .map((parameter) => {
      const value = modelParameterValues.value[parameter.id]
      return value ? `${parameter.id}=${value}` : ''
    })
    .filter(Boolean)
  return parameters.length ? `${selectedModelId.value}[${parameters.join(',')}]` : selectedModelId.value
}

function modelParameterOptions(parameter: RemoteModelParameter) {
  return parameter.values.map((value) => ({ label: value, value }))
}

function updateModelParameter(parameterId: string, value: string | null) {
  if (value) {
    modelParameterValues.value[parameterId] = value
  } else {
    delete modelParameterValues.value[parameterId]
  }
  form.value.model = configuredModelName()
}

function handleManualModelChange(model: string) {
  if (selectedModelId.value && model !== configuredModelName()) {
    clearModelParameters()
  }
}

function onModelSelect(model: RemoteModel) {
  selectedModelId.value = model.id
  selectedModelOwner.value = model.owned_by?.toLowerCase()
  modelParameterDefinitions.value = model.parameters || []
  modelParameterValues.value = {}
  form.value.model = model.id
  if (!form.value.name || form.value.name.includes('(')) {
    const vendorName = selectedVendor.value ? VENDOR_MAP[selectedVendor.value]?.name : ''
    form.value.name = vendorName ? `${vendorName} (${model.id})` : model.id
  }
  message.info(`已选用模型: ${model.id}`)
}

async function onBatchCreate(modelIds: string[]) {
  if (!modelIds.length) return
  if (!form.value.reasoning_template_id) {
    message.warning('请选择思考模板后再批量测试')
    return
  }
  saving.value = true
  try {
    let count = 0
    for (const mId of modelIds) {
      const vendorName = selectedVendor.value ? VENDOR_MAP[selectedVendor.value]?.name : '模型'
      const result = await api.profiles.probeCreate({
        name: `${vendorName} ${mId}`,
        protocol: form.value.protocol,
        base_url: form.value.base_url.trim(),
        full_url: form.value.full_url,
        model: mId,
        api_key: form.value.api_key.trim(),
        anthropic_version: form.value.anthropic_version?.trim() || undefined,
        usages: form.value.usages,
        context_window: form.value.context_window,
        max_output_tokens: form.value.max_output_tokens,
        tool_call_mode: form.value.tool_call_mode,
        reasoning_template_id: form.value.reasoning_template_id,
      })
      if (!result.ok) {
        if (count) emit('success')
        message.error(`${mId}：${result.message}`)
        return
      }
      count++
    }
    message.success(`已批量创建 ${count} 个模型协议档！`)
    emit('update:show', false)
    emit('success')
  } catch (err: any) {
    message.error(err.message || '批量创建失败')
  } finally {
    saving.value = false
  }
}

watch(
  [() => props.show, () => props.profile],
  ([showVal, profileVal]) => {
    if (showVal) {
      selectedVendor.value = props.initialData?.vendorKey || null
      clearModelParameters()
      if (profileVal) {
        form.value = {
          name: profileVal.name || '',
          protocol: profileVal.protocol || 'openai_chat',
          base_url: profileVal.base_url || '',
          model: profileVal.model || '',
          api_key: '',
          anthropic_version: profileVal.anthropic_version || '2023-06-01',
          usages: profileVal.usages ? [...profileVal.usages] : ['target'],
          context_window: profileVal.context_window || 200000,
          max_output_tokens: profileVal.max_output_tokens || 8192,
          tool_call_mode: profileVal.tool_call_mode || 'native',
          full_url: profileVal.full_url ?? false,
          reasoning_template_id: profileVal.reasoning_template_id || '',
        }
      } else if (props.initialData) {
        form.value = {
          name: props.initialData.name ? `${props.initialData.name} 模型` : '',
          protocol: props.initialData.protocol || 'openai_chat',
          base_url: props.initialData.base_url || 'https://api.openai.com/v1',
          model: '',
          api_key: '',
          anthropic_version: '2023-06-01',
          usages: ['target'],
          context_window: 200000,
          max_output_tokens: 8192,
          tool_call_mode: 'native',
          full_url: props.initialData.full_url ?? false,
          reasoning_template_id: '',
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
          context_window: 200000,
          max_output_tokens: 8192,
          tool_call_mode: 'native',
          full_url: false,
          reasoning_template_id: '',
        }
      }
      void loadReasoningTemplates()
    }
  },
  { immediate: true },
)

watch(
  () => form.value.protocol,
  () => {
    if (props.show) void loadReasoningTemplates()
  },
)

async function handleSave() {
  const name = form.value.name.trim()
  const model = form.value.model.trim()
  const baseUrl = form.value.base_url.trim()

  if (!name || !model || !baseUrl) {
    message.warning('请确保名称、模型标识名及 Base URL 已填写')
    return
  }
  if (!form.value.reasoning_template_id) {
    message.warning('请选择思考模板后再测试')
    return
  }

  saving.value = true
  try {
    if (isEdit.value && props.profile?.id) {
      const payload: ProfileProbeUpdateIn = {
        name,
        protocol: form.value.protocol,
        base_url: baseUrl,
        full_url: form.value.full_url,
        model,
        api_key: form.value.api_key.trim(),
        anthropic_version: form.value.anthropic_version?.trim() || undefined,
        usages: form.value.usages,
        context_window: form.value.context_window,
        max_output_tokens: form.value.max_output_tokens,
        tool_call_mode: form.value.tool_call_mode,
        reasoning_template_id: form.value.reasoning_template_id,
      }
      if (form.value.api_key.trim()) {
        payload.api_key = form.value.api_key.trim()
      }
      const result = await api.profiles.probeUpdate(props.profile.id, payload)
      if (!result.ok) {
        message.error(result.message)
        return
      }
      message.success(result.message)
    } else {
      const payload: ProfileProbeCreateIn = {
        name,
        protocol: form.value.protocol,
        base_url: baseUrl,
        full_url: form.value.full_url,
        model,
        api_key: form.value.api_key.trim(),
        anthropic_version: form.value.anthropic_version?.trim() || undefined,
        usages: form.value.usages,
        context_window: form.value.context_window,
        max_output_tokens: form.value.max_output_tokens,
        tool_call_mode: form.value.tool_call_mode,
        reasoning_template_id: form.value.reasoning_template_id,
      }
      const result = await api.profiles.probeCreate(payload)
      if (!result.ok) {
        message.error(result.message)
        return
      }
      message.success(result.message)
    }
    emit('update:show', false)
    emit('success')
  } catch (err: any) {
    message.error(err.message || '保存失败，请检查配置')
  } finally {
    saving.value = false
  }
}
</script>

<style scoped>
.url-mode{display:flex;align-items:center;gap:8px;font-size:12px;color:var(--text-secondary)}
.vendor-picker{display:grid;grid-template-columns:repeat(5,minmax(0,1fr));gap:8px}.vendor-picker button{display:flex;min-width:0;flex-direction:column;align-items:center;gap:7px;border:1px solid var(--border-color,#e2e8f0);border-radius:12px;background:var(--bg-card,#fff);color:var(--text-secondary);padding:12px 3px;font:inherit;font-size:11px;cursor:pointer}.vendor-picker button:hover,.vendor-picker button.selected{border-color:#43876e;background:#edf7f1;color:#245f47}

.profile-form {
  max-height: calc(100dvh - 200px);
  overflow-y: auto;
  padding-right: 8px;
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
  display: flex;
  align-items: center;
  gap: 5px;
  font-size: 13px;
  font-weight: 500;
  color: var(--text-secondary);
}
.field-label .req {
  color: var(--accent-error);
}
.form-row {
  display: grid;
  grid-template-columns: 1fr 1.3fr;
  gap: 12px;
}
.model-parameter-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 10px;
}
.profile-tabs {
  margin-top: 4px;
}
.tab-pane-content {
  display: flex;
  flex-direction: column;
  gap: 12px;
  padding-top: 10px;
}
.tab-intro-card {
  display: flex;
  align-items: flex-start;
  gap: 10px;
  background: var(--bg-elevated, rgba(255, 255, 255, 0.03));
  border: 1px solid var(--border-subtle, rgba(255, 255, 255, 0.08));
  border-radius: 8px;
  padding: 10px 12px;
}
.tab-intro-icon {
  font-size: 18px;
  line-height: 1;
}
.tab-intro-text {
  display: flex;
  flex-direction: column;
  gap: 2px;
  font-size: 12px;
  color: var(--text-secondary);
}
.tab-intro-text b {
  color: var(--text-primary);
  font-size: 13px;
}
.key-status-badge {
  font-size: 11px;
  padding: 1px 6px;
  border-radius: 4px;
}
.key-status-badge.ok {
  color: #10b981;
  background: rgba(16, 185, 129, 0.1);
  border: 1px solid rgba(16, 185, 129, 0.2);
}
.key-status-badge.none {
  color: var(--text-tertiary);
  background: rgba(255, 255, 255, 0.04);
}
@media(max-width:560px){.form-row{grid-template-columns:1fr}.vendor-picker{grid-template-columns:repeat(3,minmax(0,1fr))}}
</style>
