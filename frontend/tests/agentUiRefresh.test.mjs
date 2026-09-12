import test from 'node:test'
import assert from 'node:assert/strict'
import { createAgentUiRefresh } from '../src/agent/loop/uiRefresh.ts'

/** 受控网络允许模拟取消后仍到达的响应，不依赖计时等待。 */
function setup() {
  const loads = [], applied = [], failures = []
  const refresh = createAgentUiRefresh((sid, signal) => new Promise((resolve, reject) => {
    loads.push({ sid, signal, resolve, reject })
  }), data => applied.push(data), () => failures.push(true))
  return { refresh, loads, applied, failures }
}

test('首个请求立即开始，聚焦与定时重叠复用同一在途请求', async () => {
  const { refresh, loads, applied } = setup()
  const first = refresh.refresh('u', 's')
  for (let i = 0; i < 20; i++) assert.equal(refresh.refresh('u', 's', true), first)
  assert.equal(loads.length, 1)
  loads[0].resolve({ version: 1 })
  await first
  assert.equal(applied.length, 1)
  await refresh.refresh('u', 's', true)
  assert.equal(loads.length, 1)
  const timer = refresh.refresh('u', 's')
  assert.equal(loads.length, 2, '定时刷新不能被聚焦节流抑制')
  loads[1].resolve({ version: 2 })
  await timer
})

test('切换会话或账号取消旧请求，乱序响应不覆盖新权限', async () => {
  const { refresh, loads, applied, failures } = setup()
  const a = refresh.refresh('u', 'a')
  const b = refresh.refresh('u', 'b')
  assert.equal(loads[0].signal.aborted, true)
  const c = refresh.refresh('other', 'b')
  assert.equal(loads[1].signal.aborted, true)
  loads[2].resolve({ owner: 'other' })
  await c
  loads[0].resolve({ owner: 'u' })
  loads[1].reject(new Error('旧请求失败'))
  await Promise.all([a, b])
  assert.deepEqual(applied, [{ owner: 'other' }])
  assert.equal(failures.length, 0)
})

test('失败可立即重试；卸载后取消请求且不再更新视图', async () => {
  const { refresh, loads, applied, failures } = setup()
  const first = refresh.refresh('u', '')
  loads[0].reject(new Error('网络错误'))
  await first
  assert.equal(failures.length, 1)
  const retry = refresh.refresh('u', '', true)
  assert.equal(loads.length, 2)
  refresh.cancel()
  assert.equal(loads[1].signal.aborted, true)
  loads[1].resolve({ version: 1 })
  await retry
  assert.equal(applied.length, 0)
})
