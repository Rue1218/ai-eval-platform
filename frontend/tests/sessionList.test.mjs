import test from 'node:test'
import assert from 'node:assert/strict'
import {
  filterSessionsByStatus,
  legacySessionDot,
  legacySessionTooltip,
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

test('legacySessionDot：生成中 > 任务终态 > 会话状态 > 断线 > 就绪', () => {
  assert.equal(legacySessionDot({ generating: true }), 'running')
  assert.equal(legacySessionDot({ taskStatus: 'running' }), 'running')
  assert.equal(legacySessionDot({ taskStatus: 'queued' }), 'running')
  assert.equal(legacySessionDot({ taskStatus: 'failed' }), 'failed')
  assert.equal(legacySessionDot({ taskStatus: 'succeeded' }), 'succeeded')
  assert.equal(legacySessionDot({ taskStatus: 'cancelled' }), 'offline')
  assert.equal(legacySessionDot({ sessionStatus: 'running' }), 'running')
  assert.equal(legacySessionDot({ sessionStatus: 'failed' }), 'failed')
  assert.equal(legacySessionDot({ sessionStatus: 'succeeded' }), 'succeeded')
  assert.equal(legacySessionDot({ offline: true }), 'offline')
  assert.equal(legacySessionDot({}), 'ready')
  assert.equal(legacySessionDot({ generating: true, taskStatus: 'succeeded' }), 'running')
})

test('tooltip：loop 会话文案与状态点判定同源', () => {
  assert.equal(loopSessionTooltip(undefined), 'AgentLoop 会话')
  assert.equal(loopSessionTooltip({ connection: 'offline' }), '连接中断，状态待同步')
  assert.equal(loopSessionTooltip({ connection: 'online', activeTurn: {} }), 'Agent 回合进行中')
  assert.equal(loopSessionTooltip({ connection: 'online' }), 'Agent 回合已结束；Worker 状态独立')
})

test('tooltip：旧栈会话文案覆盖任务四态与断线', () => {
  assert.equal(legacySessionTooltip({ generating: true }), '智能体正在思考生成中…')
  assert.equal(legacySessionTooltip({ taskStatus: 'running' }), '评测任务进行中…')
  assert.equal(legacySessionTooltip({ taskStatus: 'failed' }), '任务执行失败 (failed)')
  assert.equal(legacySessionTooltip({ taskStatus: 'succeeded' }), '任务评测成功 (succeeded)')
  assert.equal(legacySessionTooltip({ taskStatus: 'cancelled' }), '任务已取消 (cancelled)')
  assert.equal(legacySessionTooltip({ offline: true }), 'WebSocket 已断开，正在重连…')
  assert.equal(legacySessionTooltip({}), '智能体就绪 (在线)')
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
