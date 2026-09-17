export type ProviderLogoKey =
  | 'stepfun' | 'nvidia' | 'mimo' | 'openai' | 'anthropic' | 'gemini' | 'deepseek'
  | 'siliconflow' | 'qwen' | 'volcengine' | 'qianfan' | 'hunyuan'
  | 'newapi' | 'minimax' | 'grok' | 'groq' | 'ollama' | 'zhipu' | 'moonshot' | 'mistral' | 'together' | 'custom'

/** 仅按模型 ID 推断模型品牌图标，不能读取供应商名称或端点。 */
export function getModelLogoKey(modelId?: string | null): ProviderLogoKey {
  const model = (modelId || '').trim().toLowerCase()
  if (!model) return 'custom'

  // 路径型模型 ID（如 openrouter/deepseek/deepseek-r1）同样按模型品牌识别。
  if (model.includes('minimax')) return 'minimax'
  if (model.includes('deepseek')) return 'deepseek'
  if (model.includes('qwen') || /(^|[/:_.-])qwq(?:[/:_.-]|$)/.test(model)) return 'qwen'
  if (model.includes('claude')) return 'anthropic'
  if (model.includes('gemini')) return 'gemini'
  if (/(^|[/:_.-])glm(?:[/:_.-]|$)/.test(model) || model.includes('z-ai')) return 'zhipu'
  if (model.includes('kimi') || model.includes('moonshot')) return 'moonshot'
  // xAI 的 Grok 使用 OpenAI 兼容端点，须在 Groq 等相近名称前独立识别。
  if (model.includes('grok')) return 'grok'
  if (/(^|[/:_.-])gpt(?:[/:_.-]|$)/.test(model) || /(^|[/:_.-])o[134](?:[/:_.-]|$)/.test(model)) return 'openai'
  if (model.includes('stepfun') || /(^|[/:_.-])step(?:[/:_.-]|$)/.test(model)) return 'stepfun'
  if (model.includes('mistral')) return 'mistral'
  if (model.includes('doubao')) return 'volcengine'
  if (model.includes('ernie')) return 'qianfan'
  if (model.includes('hunyuan')) return 'hunyuan'
  if (model.includes('mimo')) return 'mimo'
  if (model.includes('nvidia') || model.includes('nemotron')) return 'nvidia'
  if (model.includes('ollama')) return 'ollama'
  return 'custom'
}

/**
 * 按协议档的显式网关模板、服务端点、展示名称识别供应商图标。
 *
 * provider 是后端的运行时适配器标识，可能为 openai 而非实际服务商，因此只在
 * 缺少可识别端点和名称时兜底使用。
 */
export function getServiceLogoKey(profile: { base_url?: string; name?: string; provider?: string; reasoning_template_id?: string | null }): ProviderLogoKey {
  // 显式网关模板优先于域名和展示名，协议档改名后仍保持服务商身份。
  if (profile.reasoning_template_id?.startsWith('newapi-')) return 'newapi'
  const url = (profile.base_url || '').toLowerCase()
  const name = (profile.name || '').toLowerCase()

  // 未选择显式网关模板时优先识别端点，模型 ID 不参与判断。
  if (url.includes('stepfun')) return 'stepfun'
  if (url.includes('nvidia')) return 'nvidia'
  if (url.includes('xiaomimimo')) return 'mimo'
  if (url.includes('openai.com')) return 'openai'
  if (url.includes('anthropic.com')) return 'anthropic'
  if (url.includes('googleapis.com') || url.includes('generativelanguage')) return 'gemini'
  if (url.includes('deepseek')) return 'deepseek'
  if (url.includes('siliconflow')) return 'siliconflow'
  if (url.includes('dashscope') || url.includes('aliyuncs')) return 'qwen'
  if (url.includes('volces.com')) return 'volcengine'
  if (url.includes('qianfan') || url.includes('baidubce')) return 'qianfan'
  if (url.includes('hunyuan')) return 'hunyuan'
  if (url.includes('minimax')) return 'minimax'
  if (url.includes('api.x.ai')) return 'grok'
  if (url.includes('groq')) return 'groq'
  if (url.includes('11434') || url.includes('ollama')) return 'ollama'
  if (url.includes('together')) return 'together'

  // 无法从端点判断时，才使用协议档名称的显式服务商信息。
  if (/new[ -]?api/.test(name)) return 'newapi'
  if (name.includes('ollama')) return 'ollama'
  if (name.includes('stepfun') || name.includes('阶跃')) return 'stepfun'
  if (name.includes('nvidia')) return 'nvidia'
  if (name.includes('mimo')) return 'mimo'
  if (name.includes('openai')) return 'openai'
  if (name.includes('anthropic')) return 'anthropic'
  if (name.includes('gemini') || name.includes('google')) return 'gemini'
  if (name.includes('deepseek')) return 'deepseek'
  if (name.includes('silicon') || name.includes('硅基')) return 'siliconflow'
  if (name.includes('qwen') || name.includes('通义') || name.includes('百炼')) return 'qwen'
  if (name.includes('glm') || name.includes('智谱')) return 'zhipu'
  if (name.includes('kimi') || name.includes('月之暗面') || name.includes('moonshot')) return 'moonshot'
  if (name.includes('mistral')) return 'mistral'
  if (name.includes('doubao') || name.includes('豆包') || name.includes('火山')) return 'volcengine'
  if (name.includes('ernie') || name.includes('文心') || name.includes('千帆')) return 'qianfan'
  if (name.includes('hunyuan') || name.includes('混元')) return 'hunyuan'
  if (name.includes('minimax')) return 'minimax'
  if (name.includes('grok') || name.includes('xai')) return 'grok'
  if (name.includes('groq')) return 'groq'
  if (name.includes('together')) return 'together'

  if (profile.provider === 'google') return 'gemini'
  if (profile.provider && isProviderLogoKey(profile.provider)) return profile.provider
  return 'custom'
}

/** 防止后端未知 provider 字符串被当作可渲染图标标识。 */
function isProviderLogoKey(value: string): value is ProviderLogoKey {
  return [
    'stepfun', 'nvidia', 'mimo', 'openai', 'anthropic', 'gemini', 'deepseek',
    'siliconflow', 'qwen', 'volcengine', 'qianfan', 'hunyuan', 'minimax', 'grok',
    'newapi', 'groq', 'ollama', 'zhipu', 'moonshot', 'mistral', 'together', 'custom',
  ].includes(value as ProviderLogoKey)
}
