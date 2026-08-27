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
        <n-input v-model:value="form.name" placeholder="例如：Xiaomi Mimo v2.5 或 OpenAI GPT-4o" />
      </div>

      <!-- 供应商快捷分类预设选择 -->
      <div class="field">
        <label class="field-label">主流供应商快速填充</label>
        <n-select
          v-model:value="selectedVendor"
          :options="vendorOptions"
          placeholder="选择供应商可一键填入典型 Base URL 与协议"
          @update:value="handleSelectVendor"
        />
      </div>

      <div class="form-row">
        <div class="field">
          <label class="field-label">协议类型 <span class="req">*</span></label>
          <n-select v-model:value="form.protocol" :options="protocolOptions" />
        </div>
        <div class="field">
          <label class="field-label">
            模型标识名 <span class="req">*</span>
          </label>
          <div class="row" style="gap: 6px">
            <n-input
              v-model:value="form.model"
              class="grow"
              placeholder="例如：mimo-v2.5-pro / gpt-4o"
            />
            <n-button
              type="info"
              secondary
              size="small"
              :loading="fetchingModels"
              style="flex: 0 0 auto"
              title="根据当前 Base URL 和 API Key 从服务端点拉取所有可用模型 ID"
              @click="handleFetchRemoteModels"
            >
              🔍 获取模型 (/models)
            </n-button>
          </div>
        </div>
      </div>

      <div class="field">
        <label class="field-label">Base URL <span class="req">*</span></label>
        <n-input
          v-model:value="form.base_url"
          placeholder="https://api.openai.com/v1 或 http://localhost:11434/v1"
        />
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
          style="width: 220px"
        />
        <span class="small tertiary">模型单回合回答的最大输出 token 数（默认 8192）；长文档总结/导出类任务可调大，避免回答被截断。</span>
      </div>

      <div class="field">
        <label class="field-label">Agent 工具调用模式</label>
        <n-radio-group v-model:value="form.tool_call_mode" name="tool_call_mode_group" size="small">
          <n-space :size="8">
            <n-radio-button value="native">原生 ToolCall（已验证）</n-radio-button>
            <n-radio-button value="legacy">兼容 JSON-ReAct（默认）</n-radio-button>
          </n-space>
        </n-radio-group>
        <span class="small tertiary">仅当目标网关已验证支持 tools 字段时使用原生模式；兼容模式不会向上游发送 tools。</span>
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

  <FetchModelsModal
    v-model:show="showFetchModal"
    :models="fetchedModelList"
    @select="onModelSelect"
    @batch-create="onBatchCreate"
  />
</template>

<script setup lang="ts">
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
  NButton,
  NModal,
} from 'naive-ui'
import { api } from '../../api/http'
import type { Profile, ProfileCreateIn, ProfileUpdateIn, ProtocolType, ProfileUsage, ToolCallMode } from '../../api/types'
import FetchModelsModal from './FetchModelsModal.vue'

const props = defineProps<{
  show: boolean
  profile?: Profile | null
  initialData?: {
    vendorKey?: string
    base_url?: string
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
const fetchedModelList = ref<Array<{ id: string; name: string; owned_by?: string }>>([])
const selectedVendor = ref<string | null>(null)

const isEdit = computed(() => !!props.profile?.id)

const form = ref<{
  name: string
  protocol: ProtocolType
  base_url: string
  model: string
  api_key: string
  anthropic_version?: string
  usages: ProfileUsage[]
  context_window: number
  max_output_tokens: number
  tool_call_mode: ToolCallMode
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
  tool_call_mode: 'legacy',
})

const protocolOptions = [
  { label: 'OpenAI Chat (/chat/completions)', value: 'openai_chat' },
  { label: 'OpenAI Responses (/responses)', value: 'openai_responses' },
  { label: 'Anthropic Messages (/messages)', value: 'anthropic_messages' },
]

const vendorOptions = [
  { label: 'Google Gemini (官方端点 / OpenAI 兼容)', value: 'gemini' },
  { label: 'NVIDIA NIM (英伟达推理云)', value: 'nvidia' },
  { label: 'Xiaomi Mimo (小米 Mimo 端点)', value: 'mimo' },
  { label: 'OpenAI (官方端点)', value: 'openai' },
  { label: 'Anthropic Claude (官方端点)', value: 'anthropic' },
  { label: 'DeepSeek (深度求索)', value: 'deepseek' },
  { label: 'DeepSeek Anthropic 兼容 (官方 /anthropic 端点)', value: 'deepseek_anthropic' },
  { label: 'StepFun (阶跃星辰)', value: 'stepfun' },
  { label: 'SiliconFlow (硅基流动)', value: 'siliconflow' },
  { label: 'Alibaba Qwen (通义千问 / 阿里云百炼)', value: 'qwen' },
  { label: 'ByteDance Doubao (火山引擎豆包)', value: 'volcengine' },
  { label: 'Baidu Qianfan (百度文心千帆)', value: 'qianfan' },
  { label: 'Tencent Hunyuan (腾讯混元)', value: 'hunyuan' },
  { label: 'Groq (LPU 极速推理)', value: 'groq' },
  { label: 'Ollama (本地私有端点)', value: 'ollama' },
  { label: 'Zhipu GLM (智谱清言)', value: 'zhipu' },
  { label: 'Moonshot AI (月之暗面 Kimi)', value: 'moonshot' },
  { label: 'Mistral AI (Mistral AI)', value: 'mistral' },
  { label: 'Together AI', value: 'together' },
  { label: '01.AI (零一万物)', value: 'lingyi' },
  { label: 'Baichuan (百川智能)', value: 'baichuan' },
]

const VENDOR_MAP: Record<string, { name: string; base_url: string; protocol: ProtocolType; model: string }> = {
  gemini: { name: 'Google Gemini', base_url: 'https://generativelanguage.googleapis.com/v1beta/openai/', protocol: 'openai_chat', model: 'gemini-2.5-flash' },
  nvidia: { name: 'NVIDIA NIM', base_url: 'https://integrate.api.nvidia.com/v1', protocol: 'openai_chat', model: 'meta/llama-3.3-70b-instruct' },
  mimo: { name: 'Xiaomi Mimo', base_url: 'https://token-plan-cn.xiaomimimo.com', protocol: 'openai_chat', model: 'mimo-v2.5-pro' },
  openai: { name: 'OpenAI', base_url: 'https://api.openai.com/v1', protocol: 'openai_chat', model: 'gpt-4o' },
  anthropic: { name: 'Anthropic Claude', base_url: 'https://api.anthropic.com', protocol: 'anthropic_messages', model: 'claude-3-7-sonnet-20250219' },
  deepseek: { name: 'DeepSeek', base_url: 'https://api.deepseek.com/v1', protocol: 'openai_chat', model: 'deepseek-chat' },
  // DeepSeek 官方 Anthropic 兼容端点：SDK 自动追加 /v1/messages，x-api-key 完全支持
  deepseek_anthropic: {
    name: 'DeepSeek (Anthropic 兼容)',
    base_url: 'https://api.deepseek.com/anthropic',
    protocol: 'anthropic_messages',
    model: 'deepseek-chat',
  },
  stepfun: { name: 'StepFun 阶跃星辰', base_url: 'https://api.stepfun.com/v1', protocol: 'openai_chat', model: 'step-2-16k' },
  siliconflow: { name: 'SiliconFlow', base_url: 'https://api.siliconflow.cn/v1', protocol: 'openai_chat', model: 'deepseek-ai/DeepSeek-V3' },
  qwen: { name: 'Alibaba Qwen', base_url: 'https://dashscope.aliyuncs.com/compatible-mode/v1', protocol: 'openai_chat', model: 'qwen-plus' },
  volcengine: { name: 'ByteDance Doubao', base_url: 'https://ark.cn-beijing.volces.com/api/v3', protocol: 'openai_chat', model: 'doubao-pro-32k' },
  qianfan: { name: 'Baidu Qianfan', base_url: 'https://qianfan.baidubce.com/v2', protocol: 'openai_chat', model: 'ernie-4.0-8k-latest' },
  hunyuan: { name: 'Tencent Hunyuan', base_url: 'https://api.hunyuan.cloud.tencent.com/v1', protocol: 'openai_chat', model: 'hunyuan-standard' },
  groq: { name: 'Groq', base_url: 'https://api.groq.com/openai/v1', protocol: 'openai_chat', model: 'llama-3.3-70b-versatile' },
  ollama: { name: 'Ollama Local', base_url: 'http://localhost:11434/v1', protocol: 'openai_chat', model: 'llama3:latest' },
  zhipu: { name: 'Zhipu GLM', base_url: 'https://open.bigmodel.cn/api/paas/v4', protocol: 'openai_chat', model: 'glm-4-plus' },
  moonshot: { name: 'Moonshot AI', base_url: 'https://api.moonshot.cn/v1', protocol: 'openai_chat', model: 'moonshot-v1-8k' },
  mistral: { name: 'Mistral AI', base_url: 'https://api.mistral.ai/v1', protocol: 'openai_chat', model: 'mistral-large-latest' },
  together: { name: 'Together AI', base_url: 'https://api.together.xyz/v1', protocol: 'openai_chat', model: 'meta-llama/Llama-3.3-70B-Instruct-Turbo' },
  lingyi: { name: '01.AI', base_url: 'https://api.lingyiwanwu.com/v1', protocol: 'openai_chat', model: 'yi-large' },
  baichuan: { name: 'Baichuan AI', base_url: 'https://api.baichuan-ai.com/v1', protocol: 'openai_chat', model: 'Baichuan4' },
}

function handleSelectVendor(val: string | null) {
  if (!val || !VENDOR_MAP[val]) return
  const item = VENDOR_MAP[val]
  form.value.base_url = item.base_url
  form.value.protocol = item.protocol
  if (!form.value.model) form.value.model = item.model
  if (!form.value.name || form.value.name.startsWith('新协议档')) {
    form.value.name = `${item.name} (${item.model})`
  }
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

function onModelSelect(modelId: string) {
  form.value.model = modelId
  if (!form.value.name || form.value.name.includes('(')) {
    const vendorName = selectedVendor.value ? VENDOR_MAP[selectedVendor.value]?.name : ''
    form.value.name = vendorName ? `${vendorName} (${modelId})` : modelId
  }
  message.info(`已选用模型: ${modelId}`)
}

async function onBatchCreate(modelIds: string[]) {
  if (!modelIds.length) return
  saving.value = true
  try {
    let count = 0
    for (const mId of modelIds) {
      const vendorName = selectedVendor.value ? VENDOR_MAP[selectedVendor.value]?.name : '模型'
      await api.profiles.create({
        name: `${vendorName} ${mId}`,
        protocol: form.value.protocol,
        base_url: form.value.base_url.trim(),
        model: mId,
        api_key: form.value.api_key.trim(),
        anthropic_version: form.value.anthropic_version?.trim() || undefined,
        usages: form.value.usages,
        context_window: form.value.context_window,
        max_output_tokens: form.value.max_output_tokens,
        tool_call_mode: form.value.tool_call_mode,
      })
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
          tool_call_mode: profileVal.tool_call_mode || 'legacy',
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
          tool_call_mode: 'legacy',
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
          tool_call_mode: 'legacy',
        }
      }
    }
  },
  { immediate: true },
)

async function handleSave() {
  const name = form.value.name.trim()
  const model = form.value.model.trim()
  const baseUrl = form.value.base_url.trim()

  if (!name || !model || !baseUrl) {
    message.warning('请确保名称、模型标识名及 Base URL 已填写')
    return
  }

  saving.value = true
  try {
    if (isEdit.value && props.profile?.id) {
      const payload: ProfileUpdateIn = {
        name,
        protocol: form.value.protocol,
        base_url: baseUrl,
        model,
        anthropic_version: form.value.anthropic_version?.trim() || undefined,
        usages: form.value.usages,
        context_window: form.value.context_window,
        max_output_tokens: form.value.max_output_tokens,
        tool_call_mode: form.value.tool_call_mode,
      }
      if (form.value.api_key.trim()) {
        payload.api_key = form.value.api_key.trim()
      }
      await api.profiles.update(props.profile.id, payload)
      message.success('协议档已更新')
    } else {
      const payload: ProfileCreateIn = {
        name,
        protocol: form.value.protocol,
        base_url: baseUrl,
        model,
        api_key: form.value.api_key.trim(),
        anthropic_version: form.value.anthropic_version?.trim() || undefined,
        usages: form.value.usages,
        context_window: form.value.context_window,
        max_output_tokens: form.value.max_output_tokens,
        tool_call_mode: form.value.tool_call_mode,
      }
      await api.profiles.create(payload)
      message.success('协议档创建成功')
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
  grid-template-columns: 1fr 1.3fr;
  gap: 12px;
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
</style>
