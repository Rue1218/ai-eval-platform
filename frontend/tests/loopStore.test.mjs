import test from 'node:test'
import assert from 'node:assert/strict'
import { createLoopStore } from '../src/agent/loop/store.ts'
import { applyFrame } from '../src/agent/loop/reducer.ts'

// Node 环境没有 object URL 回收；stub 以观测附件释放。
const revoked = []
globalThis.URL.revokeObjectURL = source => revoked.push(source)

/** fake transport：记录选项并暴露触发入口，不产生任何网络行为。 */
function fakeTransport() {
  const created = []
  const factory = (id, options) => {
    const client = {
      id,
      options,
      sent: [],
      closed: false,
      connect: async () => {},
      send(command) { client.sent.push(command); return true },
      close() { client.closed = true },
    }
    created.push(client)
    return client
  }
  return { factory, created }
}

let cursor = 0
function frame(type, data = {}, correlation = {}, extra = {}) {
  return { protocol_version: 2, type, cursor: ++cursor, data, correlation, ...extra }
}

/** 打开会话并返回 store / fake client / 该会话草稿。 */
function setup() {
  const { factory, created } = fakeTransport()
  const store = createLoopStore(() => {}, factory)
  const client = store.open('s1')
  return { store, client, draft: store.draft('s1') }
}

test('draft：惰性初始化，同会话复用，不同会话隔离', () => {
  const { factory } = fakeTransport()
  const store = createLoopStore(() => {}, factory)
  const first = store.draft('s1')
  assert.deepEqual({ ...first }, { content: '', files: [], submitting: false })
  first.content = '输入'
  assert.equal(store.draft('s1').content, '输入')
  assert.notEqual(store.draft('s1'), store.draft('s2'))
})

test('open：同会话复用连接，不重复创建；新会话各自建连', () => {
  const { factory, created } = fakeTransport()
  const store = createLoopStore(() => {}, factory)
  const a = store.open('s1')
  const b = store.open('s1')
  assert.equal(a, b)
  assert.equal(created.length, 1)
  store.open('s2')
  assert.equal(created.length, 2)
})

test('turn.submit 受理：清冻结内容与附件、解锁提交，并撤销 object URL', () => {
  const { client, draft } = setup()
  const file = {
    key: 'f1', id: 'att-1', filename: 'a.txt', size: 3,
    source: 'blob:1', uploading: false, progress: 100, removed: false,
  }
  draft.files = [file]
  draft.content = '第一轮'
  draft.pending = {
    type: 'turn.submit',
    request_id: 'req-1',
    data: { content: '第一轮', attachment_refs: ['att-1'], client_message_id: 'cm-1' },
  }
  draft.submitting = true
  client.options.onFrame(frame('command.accepted', {}, {}, { request_id: 'req-1' }))
  assert.equal(draft.content, '')
  assert.deepEqual(draft.files, [])
  assert.equal(file.removed, true)
  assert.ok(revoked.includes('blob:1'))
  assert.equal(draft.pending, undefined)
  assert.equal(draft.submitting, false)
})

test('turn.submit 受理：用户已编辑下一轮内容时保留编辑', () => {
  const { client, draft } = setup()
  draft.content = '第二轮草稿'
  draft.pending = {
    type: 'turn.submit',
    request_id: 'req-2',
    data: { content: '第一轮', attachment_refs: [], client_message_id: 'cm-2' },
  }
  client.options.onFrame(frame('command.accepted', {}, {}, { request_id: 'req-2' }))
  assert.equal(draft.content, '第二轮草稿')
  assert.equal(draft.pending, undefined)
})

test('turn.submit 受理且存在活动回合：标记 controlled', () => {
  const { store, client, draft } = setup()
  store.sessions.s1.activeTurn = { turn_id: 't1' }
  draft.pending = {
    type: 'turn.submit',
    request_id: 'req-3',
    data: { content: '', attachment_refs: [], client_message_id: 'cm-3' },
  }
  client.options.onFrame(frame('command.accepted', {}, {}, { request_id: 'req-3' }))
  assert.equal(store.sessions.s1.controlled, true)
})

test('command.rejected：记录错误、保留草稿内容、解锁提交与交互', () => {
  const { store, client, draft } = setup()
  store.sessions.s1.interactions = { i1: { submitting: true } }
  draft.pending = { type: 'approval.respond', request_id: 'req-4', data: { interaction_id: 'i1' } }
  draft.pendingInteraction = 'i1'
  draft.submitting = true
  client.options.onFrame(frame('command.rejected', { message: '交互已过期' }, {}, { request_id: 'req-4' }))
  assert.equal(store.sessions.s1.error, '交互已过期')
  assert.equal(draft.pending, undefined)
  assert.equal(draft.submitting, false)
  assert.equal(store.sessions.s1.interactions.i1.submitting, false)
})

test('交互 respond 持久终态：resolved 匹配（interaction_id + 三 correlation）后结算', () => {
  const { store, client, draft } = setup()
  store.sessions.s1.interactions = {
    i1: { interaction_id: 'i1', kind: 'approval', resolved: false, submitting: true, correlation: {} },
  }
  draft.pending = {
    type: 'approval.respond',
    request_id: 'req-5',
    data: { interaction_id: 'i1', turn_id: 't1', attempt_id: 'a1', call_id: 'c1' },
  }
  draft.pendingInteraction = 'i1'
  draft.submitting = true
  // 模拟真实流程：reducer 先消费持久帧（严格游标 1），transport 再回调 store。
  const resolved = {
    protocol_version: 2,
    type: 'approval.resolved',
    cursor: 1,
    data: { interaction_id: 'i1' },
    correlation: { turn_id: 't1', attempt_id: 'a1', call_id: 'c1' },
  }
  assert.equal(applyFrame(store.sessions.s1, resolved), 'applied')
  client.options.onFrame(resolved)
  assert.equal(draft.pending, undefined)
  assert.equal(draft.pendingInteraction, undefined)
  assert.equal(draft.submitting, false)
  assert.equal(store.sessions.s1.interactions.i1.submitting, false)
  assert.equal(store.sessions.s1.interactions.i1.resolved, true)
})

test('交互 resolved 但 correlation 不匹配：不结算（迟到/串轮防护）', () => {
  const { client, draft } = setup()
  draft.pending = {
    type: 'approval.respond',
    request_id: 'req-6',
    data: { interaction_id: 'i1', turn_id: 't1', attempt_id: 'a1', call_id: 'c1' },
  }
  draft.submitting = true
  client.options.onFrame(
    frame('approval.resolved', { interaction_id: 'i1' }, { turn_id: 't1', attempt_id: 'a1', call_id: 'OTHER' }),
  )
  assert.equal(draft.pending.request_id, 'req-6')
  assert.equal(draft.submitting, true)
})

test('user.message 回显：按 client_message_id 匹配结算并清冻结内容', () => {
  const { client, draft } = setup()
  draft.content = '回显内容'
  draft.pending = {
    type: 'turn.submit',
    request_id: 'req-7',
    data: { content: '回显内容', attachment_refs: [], client_message_id: 'cm-7' },
  }
  draft.submitting = true
  client.options.onFrame(frame('user.message', { client_message_id: 'cm-7' }))
  assert.equal(draft.content, '')
  assert.equal(draft.pending, undefined)
  assert.equal(draft.submitting, false)
})

test('cancelRequestId 匹配的 command.rejected：清除取消中并记录错误', () => {
  const { store, client, draft } = setup()
  store.sessions.s1.cancelling = true
  draft.cancelRequestId = 'cancel-1'
  client.options.onFrame(frame('command.rejected', { message: '无活动回合' }, {}, { request_id: 'cancel-1' }))
  assert.equal(store.sessions.s1.cancelling, false)
  assert.equal(store.sessions.s1.error, '无活动回合')
  assert.equal(draft.cancelRequestId, undefined)
})

test('无关帧：不清除 pending，不产生副作用', () => {
  const { client, draft } = setup()
  draft.pending = {
    type: 'turn.submit',
    request_id: 'req-8',
    data: { content: '冻结', attachment_refs: [], client_message_id: 'cm-8' },
  }
  draft.submitting = true
  client.options.onFrame(frame('turn.start', {}, { turn: 1 }))
  assert.equal(draft.pending.request_id, 'req-8')
  assert.equal(draft.submitting, true)
})

test('remove：关闭连接、撤销附件并清理会话数据', () => {
  const { store, client, draft } = setup()
  draft.files = [{
    key: 'f1', id: 'att-2', filename: 'b.txt', size: 1,
    source: 'blob:2', uploading: false, progress: 0, removed: false,
  }]
  store.remove('s1')
  assert.equal(client.closed, true)
  assert.equal(store.sessions.s1, undefined)
  assert.equal(store.drafts.s1, undefined)
  assert.ok(revoked.includes('blob:2'))
})

test('close：清理全部会话与仅有草稿的会话', () => {
  const { factory, created } = fakeTransport()
  const store = createLoopStore(() => {}, factory)
  store.open('s1')
  store.open('s2')
  store.draft('s3')
  store.close()
  assert.equal(created.every(client => client.closed), true)
  assert.deepEqual(Object.keys(store.sessions), [])
  assert.deepEqual(Object.keys(store.drafts), [])
})

test('onRevoke：微任务后移除会话并回调页面（服务端已判定不可访问）', async () => {
  const { factory } = fakeTransport()
  const revokedIds = []
  const store = createLoopStore(id => revokedIds.push(id), factory)
  const client = store.open('s1')
  client.options.onRevoke()
  await new Promise(resolve => queueMicrotask(resolve))
  assert.deepEqual(revokedIds, ['s1'])
  assert.equal(store.sessions.s1, undefined)
})

test('send：委托给已建连接并透传命令', () => {
  const { store, client } = setup()
  const command = { protocol_version: 2, type: 'ping', data: {} }
  assert.equal(store.send('s1', command), true)
  assert.deepEqual(client.sent, [command])
})

test('快速切回不重建，后台空闲满一分钟释放连接并保留草稿及完整游标状态', t => {
  let now = 1000
  t.mock.method(Date, 'now', () => now)
  const { factory, created } = fakeTransport()
  const store = createLoopStore(() => {}, factory)
  store.focus('s1')
  store.sessions.s1.ready = true
  store.sessions.s1.cursor = 42
  store.sessions.s1.messages.m = { content: '已授权历史' }
  store.draft('s1').content = '未发送草稿'
  store.focus('s2')
  const original = created[0]
  now += 30000
  store.focus('s1')
  assert.equal(store.clients.get('s1'), original)
  assert.equal(created.length, 2)
  store.focus('s2')
  now += 60000
  store.releaseIdle()
  assert.equal(original.closed, true)
  assert.equal(store.clients.has('s1'), false)
  assert.equal(store.draft('s1').content, '未发送草稿')
  store.focus('s1')
  assert.equal(created.length, 3)
  assert.equal(store.sessions.s1.cursor, 42)
  assert.equal(store.sessions.s1.messages.m.content, '已授权历史')
  assert.equal(store.restoring.has('s1'), true, '授权回放完成前禁止显示缓存')
  created[2].options.onFrame(frame('replay.completed'))
  assert.equal(store.restoring.has('s1'), false)
  store.close()
})

test('活动回合、交互、未确认请求、隔离执行和 Worker 任务不被回收', t => {
  t.mock.method(Date, 'now', () => 1000)
  const { factory } = fakeTransport()
  const store = createLoopStore(() => {}, factory)
  const ids = ['turn', 'interaction', 'pending', 'worker', 'hint', 'quarantine', 'unsynced', 'cancel', 'submit']
  for (const id of ids) {
    store.focus(id, id === 'hint' ? 'worker-1' : undefined)
    store.sessions[id].ready = id !== 'unsynced'
  }
  store.sessions.turn.activeTurn = 'turn:1'
  store.sessions.interaction.interactions.i = { resolved: false }
  store.draft('pending').pending = { type: 'turn.submit' }
  store.sessions.worker.tasks.t = { event: 'task.progress', status: 'running' }
  store.sessions.quarantine.executions.e = { event: 'execution.quarantined' }
  store.sessions.cancel.cancelling = true
  store.draft('submit').submitting = true
  store.focus('current')
  store.releaseIdle(100000)
  store.releaseIdle(200000)
  for (const id of ids) assert.equal(store.clients.has(id), true, id)
  // Agent 回合已结束仍保留 Worker；只有任务的持久终态才开启空闲宽限期。
  store.sessions.worker.tasks.t = { event: 'task.end', status: 'succeeded' }
  store.releaseIdle(200001)
  store.releaseIdle(260001)
  assert.equal(store.clients.has('worker'), false)
  store.close()
})

test('恢复状态最多保留十份，淘汰后从零回放但不删除草稿，注销清空所有缓存', t => {
  t.mock.method(Date, 'now', () => 1000)
  const { factory } = fakeTransport()
  const store = createLoopStore(() => {}, factory)
  for (let i = 0; i < 20; i++) {
    const id = 's' + i
    store.focus(id)
    store.sessions[id].ready = true
    store.sessions[id].cursor = i + 1
    store.draft(id).content = id
  }
  store.releaseIdle(61000)
  assert.deepEqual([...store.clients.keys()], ['s19'])
  assert.equal(Object.keys(store.sessions).length, 11)
  assert.equal(store.sessions.s0, undefined)
  assert.equal(store.draft('s0').content, 's0')
  store.focus('s0')
  assert.equal(store.sessions.s0.cursor, 0)
  store.close()
  assert.equal(Object.keys(store.sessions).length, 0)
  assert.equal(Object.keys(store.drafts).length, 0)
  assert.equal(store.restoring.size, 0)
})

for (const kind of ['turn', 'task']) test(`${kind} 在两次清理之间开始并结束后，重新等待完整空闲宽限期`, t => {
  let now = 0, sequence = 0
  t.mock.method(Date, 'now', () => now)
  const { factory, created } = fakeTransport()
  const store = createLoopStore(() => {}, factory)
  t.after(() => store.close())
  store.focus('background'); store.sessions.background.ready = true
  store.focus('current'); store.sessions.current.ready = true
  for (const time of [15000, 30000, 45000]) { now = time; store.releaseIdle() }
  // 模拟另一连接发起短回合，或 Worker 在两次扫描之间完成任务。
  const correlation = kind === 'turn' ? { turn: 1, turn_id: 'background:1' } : { task_id: 'worker-1' }
  const emit = (type, data) => {
    const event = frame(type, data, correlation, { session_id: 'background', durability: 'persistent', cursor: ++sequence })
    assert.equal(applyFrame(store.sessions.background, event), 'applied')
    created[0].options.onFrame(event)
  }
  now = 50000; emit(kind === 'turn' ? 'turn.start' : 'task.queued', {})
  now = 58000; emit(`${kind}.end`, kind === 'turn' ? { reason: 'completed' } : { status: 'succeeded' })
  now = 60000; store.releaseIdle()
  assert.equal(created[0].closed, false, '最后业务活动后仅 2 秒，不能沿用旧空闲时间关闭')
  now = 117999; store.releaseIdle()
  assert.equal(created[0].closed, false)
  now = 118000; store.releaseIdle()
  assert.equal(created[0].closed, true, '重新空闲满 60 秒后仍可正常回收')
})

test('有效模型增量重置空闲时间，心跳不会无限续期', t => {
  let now = 0
  t.mock.method(Date, 'now', () => now)
  const { factory, created } = fakeTransport()
  const store = createLoopStore(() => {}, factory)
  t.after(() => store.close())
  store.focus('background'); store.sessions.background.ready = true
  store.focus('current'); store.sessions.current.ready = true
  now = 50000
  const delta = frame('assistant.text.delta', { text: '片段', chunk_index: 0 },
    { turn: 1, turn_id: 'background:1', attempt_id: 'a' }, { session_id: 'background', durability: 'transient' })
  assert.equal(applyFrame(store.sessions.background, delta), 'applied')
  created[0].options.onFrame(delta)
  now = 60000; store.releaseIdle()
  assert.equal(created[0].closed, false)
  for (const time of [75000, 90000, 105000]) {
    now = time
    created[0].options.onFrame(frame('pong', {}, {}, { durability: 'control' }))
    store.releaseIdle()
  }
  now = 110000; store.releaseIdle()
  assert.equal(created[0].closed, true, '持续心跳不应推迟最后业务事件后的回收')
})
