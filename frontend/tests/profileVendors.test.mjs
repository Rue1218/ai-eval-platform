import assert from 'node:assert/strict'
import test from 'node:test'
import { getProviderLogoKey } from '../src/utils/providerLogo.ts'
import { PROFILE_VENDORS, getProfileVendor } from '../src/utils/profileVendors.ts'

test('新建供应商只保留指定十个品牌', () => {
  assert.deepEqual(PROFILE_VENDORS.map(v => v.key), ['zhipu', 'deepseek', 'qwen', 'moonshot', 'minimax', 'nvidia', 'volcengine', 'gemini', 'openai', 'anthropic'])
})

test('GLM 和 Kimi 图标按模型识别，托管供应商单独分组', () => {
  const hosted = { base_url: 'https://integrate.api.nvidia.com/v1', provider: 'nvidia' }
  assert.equal(getProviderLogoKey({ ...hosted, model: 'z-ai/glm-4.7' }), 'zhipu')
  assert.equal(getProviderLogoKey({ ...hosted, model: 'moonshotai/kimi-k2.5' }), 'moonshot')
  assert.equal(getProfileVendor(hosted), 'nvidia')
  assert.equal(getProviderLogoKey({ provider: 'qwen', base_url: 'https://proxy.aliyuncs.com', model: 'gpt-5.4' }), 'openai')
})
