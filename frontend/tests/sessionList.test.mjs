import test from 'node:test'
import assert from 'node:assert/strict'
import {
  filterSessionsByStatus,
  loopSessionDot,
  loopSessionTooltip,
  sessionStatusFilterLabel,
} from '../src/agent/sessionList.ts'

test('loopSessionDot：无 store 状态时仅按快照 active_task（running/queued）', () => {
  assert.equal(loopSessionDot(undefined, 'running'), 'running')
  assert.equal(loopSessionDot(undefined, 'queued'), 'running')
  assert.equal(loopSessionDot(undefined, 'awaiting_case_confirm'), 'ready')
  assert.equal(loopSessionDot(undefined, undefined), 'ready')
})

test('loopSessionDot：连接非 online 优先 offline', () => {
  assert.equal(loopSessionDot({ connection: 'reconnecting', phase: 'completed' }), 'offline')
  assert.equal(loopSessionDot({ connection: 'online' }), 'ready')
})

test('loopSessionDot：活动回合或运行中任务（含等待用例确认）为 running', () => {
  assert.equal(loopSessionDot({ connection: 'online', activeTurn: { turn_id: 't' } }), 'running')
  assert.equal(loopSessionDot({ connection: 'online', tasks: { t1: { status: 'queued' } } }), 'running')
  assert.equal(loopSessionDot({ connection: 'online', tasks: { t1: { status: 'awaiting_case_confirm' } } }), 'running')
  assert.equal(loopSessionDot({ connection: 'online', tasks: { t1: { status: 'succeeded' } } }), 'ready')
})

test('loopSessionDot：phase 终态映射 failed/succeeded', () => {
  assert.equal(loopSessionDot({ connection: 'online', phase: 'error' }), 'failed')
  assert.equal(loopSessionDot({ connection: 'online', phase: 'completed' }), 'succeeded')
  assert.equal(loopSessionDot({ connection: 'online', phase: 'thinking' }), 'ready')
})

test('tooltip：loop 会话文案与状态点判定同源', () => {
  assert.equal(loopSessionTooltip(undefined), 'AgentLoop 会话')
  assert.equal(loopSessionTooltip({ connection: 'offline' }), '连接中断，状态待同步')
  assert.equal(loopSessionTooltip({ connection: 'online', activeTurn: {} }), 'Agent 回合进行中')
  assert.equal(loopSessionTooltip({ connection: 'online' }), 'Agent 回合已结束；Worker 状态独立')
})

test('sessionStatusFilterLabel：五档文案，未知回落“状态”', () => {
  assert.equal(sessionStatusFilterLabel('running'), '进行中')
  assert.equal(sessionStatusFilterLabel('ready'), '就绪')
  assert.equal(sessionStatusFilterLabel('succeeded'), '成功')
  assert.equal(sessionStatusFilterLabel('failed'), '失败')
  assert.equal(sessionStatusFilterLabel('all'), '状态')
  assert.equal(sessionStatusFilterLabel('unknown'), '状态')
})

test('filterSessionsByStatus：all 原样返回（不复制），其余按状态点过滤', () => {
  const list = [{ id: 'a' }, { id: 'b' }, { id: 'c' }]
  const dots = { a: 'running', b: 'ready', c: 'running' }
  const dotOf = session => dots[session.id]
  assert.equal(filterSessionsByStatus(list, 'all', dotOf), list)
  assert.deepEqual(filterSessionsByStatus(list, 'running', dotOf).map(s => s.id), ['a', 'c'])
  assert.deepEqual(filterSessionsByStatus(list, 'ready', dotOf).map(s => s.id), ['b'])
  assert.deepEqual(filterSessionsByStatus(list, 'failed', dotOf), [])
})
