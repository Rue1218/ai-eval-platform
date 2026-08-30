export type ProviderLogoKey =
  | 'stepfun' | 'nvidia' | 'mimo' | 'openai' | 'anthropic' | 'gemini' | 'deepseek'
  | 'siliconflow' | 'qwen' | 'volcengine' | 'qianfan' | 'hunyuan'
  | 'grok' | 'groq' | 'ollama' | 'zhipu' | 'moonshot' | 'mistral' | 'together' | 'custom'

/** 根据协议档地址、名称和模型标识推断供应商 Logo。 */
export function getProviderLogoKey(profile: { base_url?: string; name?: string; model?: string }): ProviderLogoKey {
  const url = (profile.base_url || '').toLowerCase()
  const name = (profile.name || '').toLowerCase()
  const model = (profile.model || '').toLowerCase()

  // 1. 优先匹配模型名中的品牌归属（支持托管在 NVIDIA NIM / 硅基流动等聚合平台的特定模型）
  if (model.includes('stepfun') || model.includes('step-') || name.includes('stepfun') || name.includes('阶跃') || url.includes('stepfun')) return 'stepfun'
  if (model.includes('deepseek') || name.includes('deepseek') || url.includes('deepseek')) return 'deepseek'
  if (model.includes('qwen') || name.includes('qwen') || name.includes('通义') || url.includes('dashscope') || url.includes('aliyuncs')) return 'qwen'
  // xAI 的 Grok 使用 OpenAI 兼容端点，须在 Groq 等相近名称前独立识别。
  if (model.includes('grok') || name.includes('grok') || name.includes('xai') || url.includes('api.x.ai')) return 'grok'
  if (model.startsWith('claude-') || model.includes('claude') || name.includes('claude') || url.includes('anthropic.com')) return 'anthropic'
  if (model.startsWith('gpt-') || model.startsWith('o1-') || model.startsWith('o3-') || model.startsWith('o4-') || name.includes('openai') || url.includes('openai.com')) return 'openai'
  if (model.startsWith('gemini-') || model.includes('gemini') || name.includes('gemini') || url.includes('googleapis.com') || url.includes('generativelanguage')) return 'gemini'
  if (model.includes('glm') || name.includes('glm') || name.includes('智谱') || url.includes('bigmodel.cn')) return 'zhipu'
  if (model.includes('kimi') || model.includes('moonshot') || name.includes('kimi') || name.includes('月之暗面') || url.includes('moonshot')) return 'moonshot'
  if (model.includes('mistral') || name.includes('mistral') || url.includes('mistral')) return 'mistral'
  if (model.includes('doubao') || name.includes('doubao') || name.includes('豆包') || name.includes('火山') || url.includes('volces.com')) return 'volcengine'
  if (model.includes('ernie') || name.includes('ernie') || name.includes('文心') || name.includes('千帆') || url.includes('qianfan') || url.includes('baidubce')) return 'qianfan'
  if (model.includes('hunyuan') || name.includes('hunyuan') || name.includes('混元')) return 'hunyuan'

  // 2. 匹配托管供应商服务与端点平台
  if (url.includes('nvidia') || name.includes('nvidia') || model.includes('nvidia')) return 'nvidia'
  if (url.includes('xiaomimimo') || name.includes('mimo') || model.includes('mimo')) return 'mimo'
  if (url.includes('siliconflow') || name.includes('silicon') || name.includes('硅基')) return 'siliconflow'
  if (url.includes('groq') || name.includes('groq')) return 'groq'
  if (url.includes('11434') || url.includes('ollama') || name.includes('ollama')) return 'ollama'
  if (url.includes('together') || name.includes('together')) return 'together'
  return 'custom'
}
