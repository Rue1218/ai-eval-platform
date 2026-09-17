import assert from 'node:assert/strict'
import test from 'node:test'
import { getModelLogoKey, getServiceLogoKey } from '../src/utils/providerLogo.ts'
import {
  findPresetVendor,
  getProfileVendor,
  getVendorProtocolPreset,
  PROFILE_VENDORS,
} from '../src/utils/profileVendors.ts'

test('新建供应商包含 New API 与 Ollama', () => {
  assert.deepEqual(PROFILE_VENDORS.map(v => v.key), ['zhipu', 'deepseek', 'qwen', 'moonshot', 'minimax', 'nvidia', 'volcengine', 'gemini', 'openai', 'anthropic', 'newapi', 'ollama'])
})

test('供应商协议矩阵保存各自官方 Base URL', () => {
  const bothProtocols = ['zhipu', 'deepseek', 'qwen', 'moonshot', 'minimax', 'nvidia', 'volcengine']
  for (const key of bothProtocols) {
    assert.ok(getVendorProtocolPreset(key, 'openai_chat'), `${key} 缺少 OpenAI 预设`)
    assert.ok(getVendorProtocolPreset(key, 'anthropic_messages'), `${key} 缺少 Anthropic 预设`)
  }
  assert.equal(getVendorProtocolPreset('deepseek', 'openai_chat').base_url, 'https://api.deepseek.com')
  assert.equal(getVendorProtocolPreset('deepseek', 'anthropic_messages').base_url, 'https://api.deepseek.com/anthropic')
  assert.equal(getVendorProtocolPreset('deepseek', 'anthropic_messages').model, 'deepseek-flash')
  assert.equal(getVendorProtocolPreset('qwen', 'anthropic_messages').base_url, 'https://dashscope.aliyuncs.com/apps/anthropic')
  assert.equal(getVendorProtocolPreset('moonshot', 'anthropic_messages').base_url, 'https://api.moonshot.cn/anthropic')
  assert.equal(getVendorProtocolPreset('minimax', 'anthropic_messages').base_url, 'https://api.minimax.cn/anthropic')
  assert.equal(getVendorProtocolPreset('volcengine', 'anthropic_messages').base_url, 'https://ark.cn-beijing.volces.com/api/coding')
  assert.equal(getVendorProtocolPreset('nvidia', 'anthropic_messages').base_url, '')
})

test('没有官方兼容层的供应商不伪造协议入口', () => {
  assert.equal(getVendorProtocolPreset('gemini', 'anthropic_messages'), undefined)
  assert.equal(getVendorProtocolPreset('openai', 'anthropic_messages'), undefined)
  assert.equal(getVendorProtocolPreset('anthropic', 'openai_chat'), undefined)
})

test('编辑时只按已登记协议地址恢复供应商', () => {
  assert.equal(findPresetVendor('https://api.deepseek.com/anthropic/v1/messages', 'anthropic_messages'), 'deepseek')
  assert.equal(findPresetVendor('https://internal.example/v1', 'openai_chat'), null)
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


test('Responses 和自建服务预设不会伪造公网端点或模型', () => {
  assert.equal(getVendorProtocolPreset('openai', 'openai_responses').base_url, 'https://api.openai.com/v1')
  assert.equal(getVendorProtocolPreset('newapi', 'openai_responses').base_url, '')
  assert.equal(getVendorProtocolPreset('ollama', 'openai_chat').api_key, 'ollama')
  assert.equal(getVendorProtocolPreset('ollama', 'openai_responses').model, '')
  assert.equal(getServiceLogoKey({base_url: 'https://gateway.example/v1', name: 'New API (gpt-5.4)'}), 'newapi')
  assert.equal(findPresetVendor('https://gateway.example/v1', 'openai_chat', 'New API (gpt-5.4)'), 'newapi')
  assert.equal(findPresetVendor('http://private.example:8080/v1', 'openai_chat', 'Ollama (qwen3:8b)'), 'ollama')
})
