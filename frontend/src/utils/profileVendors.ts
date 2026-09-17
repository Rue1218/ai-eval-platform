import type { ProtocolType } from '../api/types'
import { getServiceLogoKey, type ProviderLogoKey } from './providerLogo.ts'

/** 单个供应商在指定协议下的官方快速填充配置。 */
export interface VendorProtocolPreset {
  base_url: string
  model: string
  note?: string
  /** 无认证本地服务使用 SDK 所需的占位 Key；不会替换已有密钥。 */
  api_key?: string
}

/** 供应商与协议是二维能力；不能用一个 URL 同时拼接两种协议路径。 */
export interface ProfileVendor {
  key: ProviderLogoKey
  name: string
  default_protocol: ProtocolType
  context_window: number
  protocols: Partial<Record<ProtocolType, VendorProtocolPreset>>
}

/** 新建入口的供应商；真实模型可通过 /models 获取，旧协议档仍可编辑。 */
export const PROFILE_VENDORS: ProfileVendor[] = [
  {
    key: 'zhipu', name: 'GLM · 智谱', default_protocol: 'openai_chat', context_window: 200000,
    protocols: {
      openai_chat: { base_url: 'https://open.bigmodel.cn/api/paas/v4', model: 'glm-5.3' },
      anthropic_messages: { base_url: 'https://open.bigmodel.cn/api/anthropic', model: 'glm-5.3' },
    },
  },
  {
    key: 'deepseek', name: 'DeepSeek', default_protocol: 'openai_chat', context_window: 1000000,
    protocols: {
      openai_chat: { base_url: 'https://api.deepseek.com', model: 'deepseek-flash' },
      anthropic_messages: { base_url: 'https://api.deepseek.com/anthropic', model: 'deepseek-flash' },
    },
  },
  {
    key: 'qwen', name: '阿里百炼', default_protocol: 'openai_chat', context_window: 128000,
    protocols: {
      openai_chat: {
        base_url: 'https://dashscope.aliyuncs.com/compatible-mode/v1', model: 'qwen-plus',
        note: '华北 2（北京）按量付费共享域名；API Key 必须与地域及计费方案一致。',
      },
      anthropic_messages: {
        base_url: 'https://dashscope.aliyuncs.com/apps/anthropic', model: 'qwen-plus',
        note: '华北 2（北京）按量付费共享域名；API Key 必须与地域及计费方案一致。',
      },
    },
  },
  {
    key: 'moonshot', name: 'Kimi · 月之暗面', default_protocol: 'openai_chat', context_window: 256000,
    protocols: {
      openai_chat: { base_url: 'https://api.moonshot.cn/v1', model: 'kimi-k2.5' },
      anthropic_messages: { base_url: 'https://api.moonshot.cn/anthropic', model: 'kimi-k3' },
    },
  },
  {
    key: 'minimax', name: 'MiniMax', default_protocol: 'anthropic_messages', context_window: 204800,
    protocols: {
      openai_chat: { base_url: 'https://api.minimax.cn/v1', model: 'MiniMax-M3' },
      anthropic_messages: { base_url: 'https://api.minimax.cn/anthropic', model: 'MiniMax-M3' },
    },
  },
  {
    key: 'nvidia', name: 'NVIDIA NIM', default_protocol: 'openai_chat', context_window: 1000000,
    protocols: {
      openai_chat: { base_url: 'https://integrate.api.nvidia.com/v1', model: 'nvidia/nemotron-3-super-120b-a12b' },
      anthropic_messages: {
        base_url: '', model: 'nvidia/nemotron-3-super-120b-a12b',
        note: 'NIM 2.x 在部署地址提供 /v1/messages，但没有统一公网 Base URL；请填写实际 NIM 地址，扩展思考能力以真实探测为准。',
      },
    },
  },
  {
    key: 'volcengine', name: '火山引擎', default_protocol: 'openai_chat', context_window: 256000,
    protocols: {
      openai_chat: { base_url: 'https://ark.cn-beijing.volces.com/api/v3', model: 'doubao-seed-1-8-251228' },
      anthropic_messages: {
        base_url: 'https://ark.cn-beijing.volces.com/api/coding', model: 'ark-code-latest',
        note: 'Anthropic 兼容入口仅用于方舟 Coding Plan，必须使用对应套餐的 API Key。',
      },
    },
  },
  {
    key: 'gemini', name: 'Google Gemini', default_protocol: 'openai_chat', context_window: 1048576,
    protocols: {
      openai_chat: { base_url: 'https://generativelanguage.googleapis.com/v1beta/openai/', model: 'gemini-2.5-flash' },
    },
  },
  {
    key: 'openai', name: 'OpenAI', default_protocol: 'openai_chat', context_window: 1050000,
    protocols: {
      openai_chat: { base_url: 'https://api.openai.com/v1', model: 'gpt-5.4' },
      openai_responses: { base_url: 'https://api.openai.com/v1', model: 'gpt-5.4' },
    },
  },
  {
    key: 'anthropic', name: 'Anthropic', default_protocol: 'anthropic_messages', context_window: 200000,
    protocols: {
      anthropic_messages: { base_url: 'https://api.anthropic.com', model: 'claude-sonnet-4-6' },
    },
  },
  {
    key: 'newapi', name: 'New API', default_protocol: 'openai_chat', context_window: 128000,
    protocols: {
      openai_chat: { base_url: '', model: '', note: '填写你的 New API 网关地址和模型 ID；协议支持由上游通道决定。' },
      openai_responses: { base_url: '', model: '', note: '填写你的 New API 网关地址；Responses 能力以通道配置和真实验证为准。' },
      anthropic_messages: { base_url: '', model: '', note: '填写你的 New API 网关地址；Messages 能力以通道配置和真实验证为准。' },
    },
  },
  {
    key: 'ollama', name: 'Ollama', default_protocol: 'openai_chat', context_window: 32768,
    protocols: {
      openai_chat: { base_url: 'http://localhost:11434/v1', model: '', api_key: 'ollama', note: '请改为 API/Worker 可访问的地址；容器内 localhost 指容器自身。无认证服务可用占位 Key ollama，认证代理须填写真实 Key。上下文应与已部署模型一致。' },
      openai_responses: { base_url: 'http://localhost:11434/v1', model: '', api_key: 'ollama', note: '需要 Ollama 0.13.3+；使用无状态 Responses。请填写 API/Worker 可访问的地址和已部署模型；认证代理须填写真实 Key。' },
    },
  },
]

/** 按供应商和协议读取官方预设；未登记表示快速填充不宣称支持该组合。 */
export function getVendorProtocolPreset(vendorKey: string | null, protocol: ProtocolType): VendorProtocolPreset | undefined {
  return PROFILE_VENDORS.find(vendor => vendor.key === vendorKey)?.protocols[protocol]
}

/** 仅当已保存地址命中官方预设时恢复供应商选择，避免把自建兼容网关误锁为原厂。 */
export function findPresetVendor(baseUrl: string | undefined, protocol: ProtocolType, name?: string): ProviderLogoKey | null {
  const normalized = (baseUrl || '').trim().replace(/\/+$/, '').toLowerCase()
  if (!normalized) return null
  const matched = PROFILE_VENDORS.find((vendor) => {
    const preset = vendor.protocols[protocol]
    if (!preset?.base_url) return false
    const expected = preset.base_url.replace(/\/+$/, '').toLowerCase()
    return normalized === expected || normalized.startsWith(`${expected}/`)
  })
  if (matched) return matched.key
  // 自建服务没有固定域名，按现有协议档名称恢复显式供应商，保留其模板选择。
  const service = getServiceLogoKey({ base_url: baseUrl, name })
  return service === 'newapi' || service === 'ollama' ? service : null
}

/** 管理页的分组供应商只读取服务端点与协议档名称，不读取模型 ID。 */
export function getProfileVendor(profile: { provider?: string; base_url?: string; name?: string }): ProviderLogoKey {
  return getServiceLogoKey(profile)
}
