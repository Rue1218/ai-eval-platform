<template>
  <n-modal
    :show="show"
    preset="card"
    :title="isEdit ? '编辑模型协议档' : '新增模型协议档'"
    style="width: 620px; max-width: 95vw"
    @update:show="$emit('update:show', $event)"
  >
    <div class="profile-form">
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

      <div class="field">
        <label class="field-label">协议档名称 <span class="req">*</span></label>
        <n-input v-model:value="form.name" placeholder="例如：Xiaomi Mimo v2.5 或 OpenAI GPT-4o" />
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
          placeholder="https://api.openai.com/v1 或 https://token-plan-cn.xiaomimimo.com"
        />
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

  <!-- 远程拉取模型选择弹窗 -->
  <FetchModelsModal
    v-model:show="showFetchModal"
    :models="fetchedModelList"
    @select="onModelSelect"
    @batch-create="onBatchCreate"
  />
</template>

<script setup lang="ts">
import { ref, computed, watch } from 'vue'
import { useMessage, NRadioGroup, NRadioButton, NSpace, NCheckboxGroup, NCheckbox, NSelect, NInput, NButton, NModal } from 'naive-ui'
import { api } from '../../api/http'
import type { Profile, ProtocolType, ProfileUsage } from '../../api/types'
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
}>({
  name: '',
  protocol: 'openai_chat',
  base_url: 'https://api.openai.com/v1',
  model: '',
  api_key: '',
  anthropic_version: '2023-06-01',
  usages: ['target'],
  context_window: 200000,
})

const protocolOptions = [
  { label: 'OpenAI Chat (/chat/completions)', value: 'openai_chat' },
  { label: 'OpenAI Responses (/responses)', value: 'openai_responses' },
  { label: 'Anthropic Messages (/messages)', value: 'anthropic_messages' },
]

/** 主流供应商预设选项 */
const vendorOptions = [
  { label: 'NVIDIA NIM (英伟达推理云)', value: 'nvidia' },
  { label: 'Xiaomi Mimo (小米 Mimo 端点)', value: 'mimo' },
  { label: 'OpenAI (官方端点)', value: 'openai' },
  { label: 'Anthropic Claude (官方端点)', value: 'anthropic' },
  { label: 'DeepSeek (深度求索)', value: 'deepseek' },
  { label: 'SiliconFlow (硅基流动)', value: 'siliconflow' },
  { label: 'Alibaba Qwen (通义千问 / 阿里云百炼)', value: 'qwen' },
  { label: 'ByteDance Doubao (火山引擎豆包)', value: 'volcengine' },
  { label: 'Baidu Qianfan (百度文心千帆)', value: 'qianfan' },
  { label: 'Tencent Hunyuan (腾讯混元)', value: 'hunyuan' },
  { label: 'Groq (LPU 极速推理)', value: 'groq' },
  { label: 'Ollama (本地私有端点)', value: 'ollama' },
  { label: 'Zhipu GLM (智谱清言)', value: 'zhipu' },
  { label: 'Moonshot AI (月之暗面 Kimi)', value: 'moonshot' },
  { label: 'Mistral AI', value: 'mistral' },
  { label: 'Together AI', value: 'together' },
  { label: '01.AI (零一万物)', value: 'lingyi' },
  { label: 'Baichuan (百川智能)', value: 'baichuan' },
]

const VENDOR_MAP: Record<string, { name: string; base_url: string; protocol: ProtocolType; model: string }> = {
  nvidia: { name: 'NVIDIA NIM', base_url: 'https://integrate.api.nvidia.com/v1', protocol: 'openai_chat', model: 'meta/llama-3.3-70b-instruct' },
  mimo: { name: 'Xiaomi Mimo', base_url: 'https://token-plan-cn.xiaomimimo.com', protocol: 'openai_chat', model: 'mimo-v2.5-pro' },
  openai: { name: 'OpenAI', base_url: 'https://api.openai.com/v1', protocol: 'openai_chat', model: 'gpt-4o' },
  anthropic: { name: 'Anthropic Claude', base_url: 'https://api.anthropic.com', protocol: 'anthropic_messages', model: 'claude-3-7-sonnet-20250219' },
  deepseek: { name: 'DeepSeek', base_url: 'https://api.deepseek.com/v1', protocol: 'openai_chat', model: 'deepseek-chat' },
  siliconflow: { name: 'SiliconFlow', base_url: 'https://api.siliconflow.cn/v1', protocol: 'openai_chat', model: 'deepseek-ai/DeepSeek-V3' },
  qwen: { name: 'Alibaba Qwen', base_url: 'https://dashscope.aliyuncs.com/compatible-mode/v1', protocol: 'openai_chat', model: 'qwen-plus' },
  volcengine: { name: 'ByteDance Doubao', base_url: 'https://ark.cn-beijing.volces.com/api/v3', protocol: 'openai_chat', model: 'doubao-pro-32k' },
  qianfan: { name: 'Baidu Qianfan', base_url: 'https://qianfan.baidubce.com/v2', protocol: 'openai_chat', model: 'ernie-4.0-8k-latest' },
  hunyuan: { name: 'Tencent Hunyuan', base_url: 'https://api.hunyuan.cloud.tencent.com/v1', protocol: 'openai_chat', model: 'hunyuan-standard' },
  groq: { name: 'Groq', base_url: 'https://api.groq.com/openai/v1', protocol: 'openai_chat', model: 'llama-3.3-70b-versatile' },
  ollama: { name: 'Ollama Local', base_url: 'http://localhost:11434', protocol: 'openai_chat', model: 'llama3:latest' },
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

/** 触发 /models 远程模型列表获取 */
async function handleFetchRemoteModels() {
  if (!form.value.base_url.trim()) {
    message.warning('请先输入 Base URL')
    return
  }
  if (!isEdit.value && !form.value.api_key.trim() && !form.value.base_url.includes('localhost') && !form.value.base_url.includes('11434')) {
    message.warning('请先输入 API Key，以便向上游端点发送认证请求')
    return
  }

  fetchingModels.value = true
  try {
    const res = await api.profiles.fetchModels({
      protocol: form.value.protocol,
      base_url: form.value.base_url,
      api_key: form.value.api_key || undefined,
      profile_id: props.profile?.id || undefined,
      anthropic_version: form.value.anthropic_version || undefined,
    })
    if (res.ok && res.models?.length) {
      fetchedModelList.value = res.models
      showFetchModal.value = true
      message.success(`成功获取到 ${res.models.length} 个可用模型`)
    } else {
      message.warning('端点未返回模型列表，请手动输入模型标识名')
    }
  } catch (err: any) {
    message.error(err.message || '获取模型列表失败，请检查 Base URL 与 API Key')
  } finally {
    fetchingModels.value = false
  }
}

/** 弹窗中选择单个模型回填 */
function onModelSelect(modelId: string) {
  form.value.model = modelId
  if (!form.value.name || form.value.name.includes('(')) {
    const vendorPrefix = selectedVendor.value ? VENDOR_MAP[selectedVendor.value]?.name : (props.profile?.name.split(' ')[0] || '大模型')
    form.value.name = `${vendorPrefix} ${modelId}`
  }
  message.info(`已选用模型: ${modelId}`)
}

/** 批量添加所选模型为独立协议档 */
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
        base_url: form.value.base_url,
        model: mId,
        api_key: form.value.api_key,
        anthropic_version: form.value.anthropic_version,
        usages: form.value.usages,
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
  () => props.show,
  (val) => {
    if (val) {
      selectedVendor.value = props.initialData?.vendorKey || null
      if (props.profile) {
        form.value = {
          name: props.profile.name,
          protocol: props.profile.protocol,
          base_url: props.profile.base_url,
          model: props.profile.model,
          api_key: '',
          anthropic_version: props.profile.anthropic_version || '2023-06-01',
          usages: props.profile.usages ? [...props.profile.usages] : ['target'],
          context_window: props.profile.context_window || 200000,
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
        context_window: form.value.context_window,
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
  grid-template-columns: 1fr 1.3fr;
  gap: 12px;
}
</style>
