import test from 'node:test'
import assert from 'node:assert/strict'
import {
  calculateTurnSummaries,
  formatDuration,
  formatTokens,
  getTurnIdentifier,
} from '../src/agent/loop/turnSummary.ts'

test('formatTokens: 准确格式化各区间 Token 数值', () => {
  assert.equal(formatTokens(null), '—')
  assert.equal(formatTokens(undefined), '—')
  assert.equal(formatTokens(0), '0')
  assert.equal(formatTokens(520), '520')
  assert.equal(formatTokens(3140), '3.1K')
  assert.equal(formatTokens(11000), '11K')
  assert.equal(formatTokens(1500000), '1.5M')
  assert.equal(formatTokens(12000000), '12M')
})

test('formatDuration: 准确格式化毫秒与秒数', () => {
  assert.equal(formatDuration(null), '—')
  assert.equal(formatDuration(undefined), '—')
  assert.equal(formatDuration(0), '0 ms')
  assert.equal(formatDuration(450), '450 ms')
  assert.equal(formatDuration(1800), '1.8 s')
  assert.equal(formatDuration(26000), '26 s')
})

test('calculateTurnSummaries: 单轮多次 ReAct 步骤正确累加 Token 与用时，并在轮次结尾输出', () => {
  const rows = [
    { key: 'u1', role: 'user', content: '查看工作区文件', correlation: { turn: 1 } },
    {
      key: 'a1',
      role: 'assistant',
      text: '',
      reasoning: '思考步骤 1',
      ended: true,
      correlation: { turn: 1, step: 1 },
      usage: { prompt_tokens: 3000, completion_tokens: 100, total_tokens: 3100 },
      latency_ms: 4900,
    },
    {
      key: 't1',
      name: 'bash',
      status: 'succeeded',
      display: {},
      correlation: { turn: 1, call_id: 'c1' },
    },
    {
      key: 'a2',
      role: 'assistant',
      text: '',
      reasoning: '思考步骤 2',
      ended: true,
      correlation: { turn: 1, step: 2 },
      usage: { total_tokens: 3300 },
      latency_ms: 1800,
    },
    {
      key: 't2',
      name: 'read',
      status: 'succeeded',
      display: {},
      correlation: { turn: 1, call_id: 'c2' },
    },
    {
      key: 'a3',
      role: 'assistant',
      text: '已查看工作区，目前只有一个文件。',
      reasoning: '思考步骤 3',
      ended: true,
      correlation: { turn: 1, step: 3 },
      usage: { total_tokens: 11000 },
      latency_ms: 14000,
    },
  ]

  // 1. 活跃运行中（activeTurnId 为本轮），不输出结尾总结
  const activeSummaries = calculateTurnSummaries(rows, {
    activeTurnId: 's:1',
    sessionId: 's',
    isBusy: true,
  })
  assert.equal(activeSummaries.size, 0)

  // 2. 本轮结束，成功挂载在最后一行（a3）
  const endedSummaries = calculateTurnSummaries(rows, {
    activeTurnId: null,
    sessionId: 's',
    isBusy: false,
  })
  assert.equal(endedSummaries.size, 1)
  assert.ok(endedSummaries.has('a3'))
  const summary = endedSummaries.get('a3')
  assert.equal(summary.turnKey, 'turn:1')
  // 3100 + 3300 + 11000 = 17400
  assert.equal(summary.totalTokens, 17400)
  // 4900 + 1800 + 14000 = 20700
  assert.equal(summary.totalLatencyMs, 20700)
  assert.equal(summary.text, '已查看工作区，目前只有一个文件。')
  assert.equal(summary.representativeRow.key, 'a3')
})

test('calculateTurnSummaries: 工具处于运行状态时不输出结尾总结', () => {
  const rows = [
    { key: 'u1', role: 'user', content: '测试', correlation: { turn: 1 } },
    {
      key: 'a1',
      role: 'assistant',
      text: '',
      ended: true,
      correlation: { turn: 1 },
      usage: { total_tokens: 100 },
      latency_ms: 500,
    },
    {
      key: 't1',
      name: 'bash',
      status: 'running',
      display: {},
      correlation: { turn: 1 },
    },
  ]
  const summaries = calculateTurnSummaries(rows, { activeTurnId: null, isBusy: false })
  assert.equal(summaries.size, 0)
})

test('calculateTurnSummaries: 仅有用户消息时不输出总结', () => {
  const rows = [
    { key: 'u1', role: 'user', content: '刚发送的消息', correlation: { turn: 1 } },
  ]
  const summaries = calculateTurnSummaries(rows, { activeTurnId: null, isBusy: false })
  assert.equal(summaries.size, 0)
})

test('calculateTurnSummaries: 多轮对话分别在各轮结尾输出', () => {
  const rows = [
    // Turn 1
    { key: 'u1', role: 'user', content: '第一轮', correlation: { turn: 1 } },
    { key: 'a1', role: 'assistant', text: '回答 1', ended: true, correlation: { turn: 1 }, usage: { total_tokens: 500 }, latency_ms: 1000 },
    // Turn 2
    { key: 'u2', role: 'user', content: '第二轮', correlation: { turn: 2 } },
    { key: 'a2', role: 'assistant', text: '回答 2', ended: true, correlation: { turn: 2 }, usage: { total_tokens: 800 }, latency_ms: 1500 },
  ]
  const summaries = calculateTurnSummaries(rows, { activeTurnId: null, isBusy: false })
  assert.equal(summaries.size, 2)
  assert.ok(summaries.has('a1'))
  assert.ok(summaries.has('a2'))
  assert.equal(summaries.get('a1').totalTokens, 500)
  assert.equal(summaries.get('a2').totalTokens, 800)
})
