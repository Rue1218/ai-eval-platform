export type ProviderLogoKey =
  | 'nvidia' | 'mimo' | 'openai' | 'anthropic' | 'gemini' | 'deepseek'
  | 'siliconflow' | 'qwen' | 'volcengine' | 'qianfan' | 'hunyuan'
  | 'groq' | 'ollama' | 'zhipu' | 'moonshot' | 'mistral' | 'together' | 'custom'

/** 根据协议档地址、名称和模型标识推断供应商 Logo。 */
export function getProviderLogoKey(profile: { base_url?: string; name?: string; model?: string }): ProviderLogoKey {
  const url = (profile.base_url || '').toLowerCase()
  const name = (profile.name || '').toLowerCase()
  const model = (profile.model || '').toLowerCase()

  if (url.includes('nvidia') || name.includes('nvidia') || model.includes('nvidia')) return 'nvidia'
  if (url.includes('xiaomimimo') || name.includes('mimo') || model.includes('mimo')) return 'mimo'
  if (url.includes('googleapis.com') || url.includes('generativelanguage') || name.includes('gemini') || model.startsWith('gemini-')) return 'gemini'
  if (url.includes('openai.com') || name.includes('openai') || model.startsWith('gpt-')) return 'openai'
  if (url.includes('anthropic.com') || name.includes('claude') || model.startsWith('claude-')) return 'anthropic'
  if (url.includes('deepseek') || name.includes('deepseek') || model.includes('deepseek')) return 'deepseek'
  if (url.includes('siliconflow') || name.includes('silicon') || name.includes('硅基')) return 'siliconflow'
  if (url.includes('aliyuncs') || url.includes('dashscope') || name.includes('qwen') || model.includes('qwen')) return 'qwen'
  if (url.includes('volces.com') || name.includes('doubao') || name.includes('火山') || name.includes('豆包')) return 'volcengine'
  if (url.includes('qianfan') || url.includes('baidubce') || name.includes('ernie') || name.includes('文心') || name.includes('千帆')) return 'qianfan'
  if (url.includes('hunyuan') || name.includes('混元')) return 'hunyuan'
  if (url.includes('groq') || name.includes('groq')) return 'groq'
  if (url.includes('11434') || url.includes('ollama') || name.includes('ollama')) return 'ollama'
  if (url.includes('bigmodel.cn') || name.includes('glm') || model.includes('glm') || name.includes('智谱')) return 'zhipu'
  if (url.includes('moonshot') || name.includes('kimi') || name.includes('moonshot') || name.includes('月之暗面')) return 'moonshot'
  if (url.includes('mistral') || name.includes('mistral')) return 'mistral'
  if (url.includes('together') || name.includes('together')) return 'together'
  return 'custom'
}
