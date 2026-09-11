import assert from 'node:assert/strict'
import test from 'node:test'
import { getModelLogoKey, getServiceLogoKey } from '../src/utils/providerLogo.ts'
import { PROFILE_VENDORS, getProfileVendor } from '../src/utils/profileVendors.ts'

test('新建供应商只保留指定十个品牌', () => {
  assert.deepEqual(PROFILE_VENDORS.map(v => v.key), ['zhipu', 'deepseek', 'qwen', 'moonshot', 'minimax', 'nvidia', 'volcengine', 'gemini', 'openai', 'anthropic'])
})

test('模型品牌与托管供应商严格分离', () => {
  const hosted = { base_url: 'https://integrate.api.nvidia.com/v1', provider: 'nvidia' }
  assert.equal(getModelLogoKey('z-ai/glm-4.7'), 'zhipu')
  assert.equal(getModelLogoKey('moonshotai/kimi-k2.5'), 'moonshot')
  assert.equal(getServiceLogoKey(hosted), 'nvidia')
  assert.equal(getProfileVendor(hosted), 'nvidia')
  assert.equal(getServiceLogoKey({ base_url: 'https://dashscope.aliyuncs.com/compatible-mode/v1', name: 'MaaS DeepSeek' }), 'qwen')
  assert.equal(getModelLogoKey('deepseek-v4-flash-0731'), 'deepseek')
})

test('供应商图标不受 OpenAI 兼容适配器和模型名称干扰', () => {
  const siliconFlow = {
    base_url: 'https://api.siliconflow.cn/v1',
    name: '硅基流动上的 DeepSeek',
    provider: 'openai',
  }
  assert.equal(getServiceLogoKey(siliconFlow), 'siliconflow')
  assert.equal(getProfileVendor(siliconFlow), 'siliconflow')
  assert.equal(getModelLogoKey('deepseek-v4-flash'), 'deepseek')
  assert.equal(getServiceLogoKey({ base_url: 'https://internal.example/v1', provider: 'qwen' }), 'qwen')
})

test('路径型模型 ID 仍按品牌显示，未知模型稳定兜底', () => {
  assert.equal(getModelLogoKey('openrouter/deepseek/deepseek-r1'), 'deepseek')
  assert.equal(getModelLogoKey('Qwen/Qwen3.5-Plus'), 'qwen')
  assert.equal(getModelLogoKey('unknown-private-model'), 'custom')
})
