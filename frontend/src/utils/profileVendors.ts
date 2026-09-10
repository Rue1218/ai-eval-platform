import type { ProtocolType } from '../api/types'
import type { ProviderLogoKey } from './providerLogo'

/** 新建入口的十个供应商；真实模型可通过 /models 获取，旧协议档仍可编辑。 */
export const PROFILE_VENDORS: Array<{ key: ProviderLogoKey; name: string; base_url: string; protocol: ProtocolType; model: string; context_window: number }> = [
  { key: 'zhipu', name: 'GLM · 智谱', base_url: 'https://open.bigmodel.cn/api/paas/v4', protocol: 'openai_chat', model: 'glm-4.7', context_window: 200000 },
  { key: 'deepseek', name: 'DeepSeek', base_url: 'https://api.deepseek.com/v1', protocol: 'openai_chat', model: 'deepseek-v4-flash', context_window: 1000000 },
  { key: 'qwen', name: '阿里百炼', base_url: 'https://dashscope.aliyuncs.com/compatible-mode/v1', protocol: 'openai_chat', model: 'qwen-plus', context_window: 128000 },
  { key: 'moonshot', name: 'Kimi · 月之暗面', base_url: 'https://api.moonshot.cn/v1', protocol: 'openai_chat', model: 'kimi-k2.5', context_window: 256000 },
  { key: 'minimax', name: 'MiniMax', base_url: 'https://api.minimaxi.com/anthropic', protocol: 'anthropic_messages', model: 'MiniMax-M2.5', context_window: 204800 },
  { key: 'nvidia', name: 'NVIDIA NIM', base_url: 'https://integrate.api.nvidia.com/v1', protocol: 'openai_chat', model: 'nvidia/nemotron-3-super-120b-a12b', context_window: 1000000 },
  { key: 'volcengine', name: '火山引擎', base_url: 'https://ark.cn-beijing.volces.com/api/v3', protocol: 'openai_chat', model: 'doubao-seed-1-8-251228', context_window: 256000 },
  { key: 'gemini', name: 'Google Gemini', base_url: 'https://generativelanguage.googleapis.com/v1beta/openai/', protocol: 'openai_chat', model: 'gemini-2.5-flash', context_window: 1048576 },
  { key: 'openai', name: 'OpenAI', base_url: 'https://api.openai.com/v1', protocol: 'openai_chat', model: 'gpt-5.4', context_window: 1050000 },
  { key: 'anthropic', name: 'Anthropic', base_url: 'https://api.anthropic.com', protocol: 'anthropic_messages', model: 'claude-sonnet-4-6', context_window: 200000 },
]

/** 管理页按服务供应商分组，Agent 按模型品牌展示，两者不混用。 */
export function getProfileVendor(profile: { provider?: string; base_url?: string }): ProviderLogoKey {
  if (profile.provider === 'google') return 'gemini'
  if (PROFILE_VENDORS.some(v => v.key === profile.provider)) return profile.provider as ProviderLogoKey
  try {
    const host = new URL(profile.base_url || '').hostname
    return PROFILE_VENDORS.find(v => new URL(v.base_url).hostname === host)?.key || 'custom'
  } catch { return 'custom' }
}
