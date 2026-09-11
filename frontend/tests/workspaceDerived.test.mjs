import test from 'node:test'
import assert from 'node:assert/strict'
import {
  assistantKeysByTurn,
  conversationMetricsFrom,
  effortPreferenceKey,
  firstAssistantInTurn,
  latestRequestSummary,
  phaseStatusText,
  pickAgent,
  pickProfile,
  preferenceKey,
  taskForToolRow,
} from '../src/agent/loop/workspaceDerived.ts'

/** 构造会话记录：correlation 提供轮次标识，status+name 表示工具记录。 */
function row(key, { role = 'assistant', turn, turnId, status, name, usage, latency } = {}) {
  const r = { key, role, correlation: {}, usage, latency_ms: latency }
  if (turn !== undefined) r.correlation.turn = turn
  if (turnId !== undefined) r.correlation.turn_id = turnId
  if (status !== undefined) {
    r.status = status
    r.name = name || 'tool'
  }
  return r
}

test('assistantKeysByTurn：每轮首条助手记录，用户与工具记录不参与', () => {
  const rows = [
    row('u1', { role: 'user', turn: 1 }),
    row('a1', { turn: 1 }),
    row('a2', { turn: 1 }),
    row('t1', { turn: 1, status: 'succeeded', name: 'read' }),
    row('a3', { turn: 2 }),
    row('u2', { role: 'user', turn: 3 }),
    row('a4', { turn: 3 }),
  ]
  const map = assistantKeysByTurn(rows)
  assert.equal(map.get('turn:1'), 'a1')
  assert.equal(map.get('turn:2'), 'a3')
  assert.equal(map.get('turn:3'), 'a4')
  assert.equal(map.size, 3)
})

test('firstAssistantInTurn：首条 true，续写 false，无分组记录视为 true', () => {
  const rows = [row('a1', { turn: 1 }), row('a2', { turn: 1 })]
  const map = assistantKeysByTurn(rows)
  assert.equal(firstAssistantInTurn(rows[0], map), true)
  assert.equal(firstAssistantInTurn(rows[1], map), false)
  assert.equal(firstAssistantInTurn(row('x', { turn: 9 }), map), true)
})

test('轮次标识：turn_id 优先于 turn 编号，同轮多助手共用首条 key', () => {
  const rows = [row('a1', { turnId: 's:1', turn: 1 }), row('a2', { turnId: 's:1', turn: 1 })]
  const map = assistantKeysByTurn(rows)
  assert.equal(map.get('turn_id:s:1'), 'a1')
  assert.equal(firstAssistantInTurn(rows[1], map), false)
})

test('conversationMetricsFrom：空、缺 attempts、缺 usage 均不虚增', () => {
  const empty = { inputTokens: 0, outputTokens: 0, outputTokensPerSecond: null, cacheHitRate: null }
  assert.deepEqual(conversationMetricsFrom(undefined), empty)
  assert.deepEqual(conversationMetricsFrom({}), empty)
  assert.deepEqual(conversationMetricsFrom({ a1: { key: 'a1' } }), empty)
})

test('conversationMetricsFrom：吞吐仅在输入、输出、耗时齐备时计算', () => {
  const full = conversationMetricsFrom({
    a1: { key: 'a1', latency_ms: 1000, usage: { prompt_tokens: 100, completion_tokens: 300 } },
  })
  assert.equal(full.inputTokens, 100)
  assert.equal(full.outputTokens, 300)
  assert.equal(full.outputTokensPerSecond, 300)

  const noLatency = conversationMetricsFrom({
    a1: { key: 'a1', usage: { prompt_tokens: 100, completion_tokens: 300 } },
  })
  assert.equal(noLatency.outputTokensPerSecond, null)

  const noInput = conversationMetricsFrom({
    a1: { key: 'a1', latency_ms: 1000, usage: { completion_tokens: 300 } },
  })
  assert.equal(noInput.outputTokensPerSecond, null)
})

test('conversationMetricsFrom：缓存命中率仅在有缓存字段时给出，否则 null', () => {
  const cacheRead = conversationMetricsFrom({
    a1: { key: 'a1', usage: { prompt_tokens: 1000, completion_tokens: 10, cache_read_input_tokens: 400 } },
  })
  assert.equal(cacheRead.cacheHitRate, 40)

  const cachedTokens = conversationMetricsFrom({
    a1: { key: 'a1', usage: { prompt_tokens: 500, completion_tokens: 10, cached_tokens: 100 } },
  })
  assert.equal(cachedTokens.cacheHitRate, 20)

  const noCacheField = conversationMetricsFrom({
    a1: { key: 'a1', usage: { prompt_tokens: 1000, completion_tokens: 10 } },
  })
  assert.equal(noCacheField.cacheHitRate, null)

  // 缓存字段存在但值为 0：命中率 0（上游明确返回），不是 null
  const zeroCache = conversationMetricsFrom({
    a1: { key: 'a1', usage: { prompt_tokens: 1000, completion_tokens: 10, cache_read_input_tokens: 0 } },
  })
  assert.equal(zeroCache.cacheHitRate, 0)
})

test('conversationMetricsFrom：多轮累计，非法数值按 0 处理不污染合计', () => {
  const metrics = conversationMetricsFrom({
    a1: { key: 'a1', latency_ms: 1000, usage: { prompt_tokens: 100, completion_tokens: 200 } },
    a2: { key: 'a2', latency_ms: 1000, usage: { prompt_tokens: 'bad', completion_tokens: -5 } },
  })
  assert.equal(metrics.inputTokens, 100)
  assert.equal(metrics.outputTokens, 200)
})

test('pickProfile：优先草稿选择，未知 ID 回落平台默认', () => {
  const ui = { profiles: [{ id: 'p1' }, { id: 'p2' }], profile: { id: 'p-default' } }
  assert.equal(pickProfile(ui, 'p2').id, 'p2')
  assert.equal(pickProfile(ui, 'unknown').id, 'p-default')
  assert.equal(pickProfile(ui, '').id, 'p-default')
  assert.equal(pickProfile(null, 'p1'), null)
  assert.equal(pickProfile({ profiles: [] }, 'p1'), null)
})

test('pickAgent：未知 ID 回落 default 标记项，无默认时为 null', () => {
  const ui = { agents: [{ id: 'general', default: false }, { id: 'tc', default: true }] }
  assert.equal(pickAgent(ui, 'general').id, 'general')
  assert.equal(pickAgent(ui, 'unknown').id, 'tc')
  assert.equal(pickAgent({ agents: [{ id: 'a', default: false }] }, 'unknown'), null)
  assert.equal(pickAgent(undefined, 'a'), null)
})

test('latestRequestSummary：取 first_cursor 最大的 attempt，无 attempt 为 undefined', () => {
  const attempts = {
    a1: { key: 'a1', first_cursor: 3, request_summary: { profile: 'p-old' } },
    a2: { key: 'a2', first_cursor: 9, request_summary: { profile: 'p-new' } },
    a3: { key: 'a3', first_cursor: 5 },
  }
  assert.deepEqual(latestRequestSummary(attempts), { profile: 'p-new' })
  assert.equal(latestRequestSummary(undefined), undefined)
  assert.equal(latestRequestSummary({}), undefined)
})

test('taskForToolRow：task_id 解析优先级 事实 > 结果 > 参数，未关联为 null', () => {
  const tasks = { 'task-9': { key: 'task-9', status: 'running' } }
  const fromArgs = {
    key: 't1',
    name: 'task.create',
    display: { arguments_preview: JSON.stringify({ task_id: 'task-9' }) },
  }
  assert.equal(taskForToolRow(fromArgs, tasks).key, 'task-9')

  const bothPreviews = {
    key: 't2',
    name: 'task.status',
    display: {
      arguments_preview: JSON.stringify({ task_id: 'task-args' }),
      result_preview: JSON.stringify({ task_id: 'task-9' }),
    },
  }
  assert.equal(taskForToolRow(bothPreviews, tasks).key, 'task-9')

  assert.equal(taskForToolRow({ key: 't3', name: 'task.create', display: {} }, tasks), null)
  assert.equal(
    taskForToolRow({ key: 't4', name: 'task.create', display: { arguments_preview: 'not-json' } }, tasks),
    null,
  )
  assert.equal(taskForToolRow(fromArgs, undefined), null)
  assert.equal(taskForToolRow(fromArgs, {}), null)
})

test('phaseStatusText：取消中 > 连接待同步 > phase 映射 > 原始值 > 就绪', () => {
  assert.equal(phaseStatusText({ cancelling: true, connection: 'offline', phase: 'thinking' }), '取消中')
  assert.equal(phaseStatusText({ connection: 'connecting', phase: 'thinking' }), '连接待同步')
  assert.equal(phaseStatusText({ connection: 'online', phase: 'thinking' }), '正在思考')
  assert.equal(phaseStatusText({ connection: 'online', phase: 'max_tokens' }), '达到输出上限，本轮已结束')
  assert.equal(phaseStatusText({ connection: 'online', phase: 'custom_phase' }), 'custom_phase')
  assert.equal(phaseStatusText({ connection: 'online' }), '就绪')
  assert.equal(phaseStatusText(undefined), '就绪')
})

test('偏好 key：按用户与协议档版本隔离，升级版本后不沿用旧档位', () => {
  assert.equal(preferenceKey('agent-profile', 'u1'), 'agent-profile:u1')
  assert.equal(preferenceKey('agent-profile', undefined), 'agent-profile:undefined')
  assert.equal(effortPreferenceKey({ id: 'p1', version: 'v2' }, 'u1'), 'agent-effort:u1:p1:v2')
  assert.notEqual(
    effortPreferenceKey({ id: 'p1', version: 'v2' }, 'u1'),
    effortPreferenceKey({ id: 'p1', version: 'v3' }, 'u1'),
  )
})
