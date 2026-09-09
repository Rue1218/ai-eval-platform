import test from 'node:test'
import assert from 'node:assert/strict'
import { createLoopState, applyFrame, conversationRows, restoreSnapshot } from '../src/agent/loop/reducer.ts'
import { createTrace, applyTrace, safePacket, schemaRef, semanticTraceRows, category } from '../src/agent/loop/trace.ts'
import { safeLink } from '../src/agent/loop/toolPresentation.ts'

/** 夹具遵循生产信封，持久 cursor 与 source seq 从各自起点计数。 */
function fixture() {
  let cursor = 0
  return (type, data = {}, correlation = {}, durability = 'persistent') => ({ protocol_version: 2, type, durability,
    session_id: 's', ...(durability === 'persistent' ? { cursor: ++cursor } : {}), ts: '2026-09-09T00:00:00Z',
    correlation: { turn: 1, turn_id: 's:1', ...correlation }, data })
}

test('快照允许保留窗口缺号，但拒绝倒序、重复和超出 H 的事实', () => {
  const f = fixture(), first = f('user.message', {content:'保留历史'}), second = f('turn.start')
  assert.equal(restoreSnapshot('s', 2, {timeline:[second]}).cursor, 2)
  for (const timeline of [[second, first], [first, first], [{...second,cursor:3}]]) {
    assert.throws(() => restoreSnapshot('s', 2, {timeline}))
  }
  assert.throws(() => restoreSnapshot('s', 2, {timeline:[{...first,session_id:'other'}]}))
})

test('轨迹工具合并保留首个 cursor、全部来源与独立 attempt', () => {
  const f = fixture(), c = {attempt_id:'a',call_id:'same'}
  const facts = [f('tool.call',{display:{args_preview:'输入'}},c),f('tool.dispatch',{},c),
    f('tool.result',{display:{result_preview:'输出'},status:'succeeded'},c),
    f('tool.call',{}, {...c,attempt_id:'b'})]
  const rows = semanticTraceRows(facts)
  assert.equal(rows.length,2); assert.equal(rows[0].cursor,1); assert.equal(rows[0].layers.length,3)
  assert.equal(rows[0].data.display.args_preview,'输入');assert.equal(rows[0].data.display.result_preview,'输出')
  assert.equal(facts[0].data.display.result_preview,undefined)
})
test('严格游标：重复丢弃，缺口停住，受限占位仍消费序号', () => {
  const s = createLoopState('s'), f = fixture()
  const first = f('user.message', { content: '你好', client_message_id: 'u1' })
  assert.equal(applyFrame(s, first), 'applied')
  assert.equal(applyFrame(s, first), 'duplicate')
  const missing = f('turn.start'), future = f('approval.requested', { restricted: true }, { attempt_id: 'a', call_id: 'c' })
  assert.equal(applyFrame(s, future), 'gap'); assert.equal(s.cursor, 1)
  applyFrame(s, missing); applyFrame(s, future)
  assert.equal(s.cursor, 3); assert.equal(Object.keys(s.messages).length, 1)
  assert.throws(() => applyFrame(s, { ...first, protocol_version: 3 }))
})
test('四步模型、三个同名工具与下一回合：顺序和调用身份保持独立', () => {
  const s = createLoopState('s'), f = fixture()
  applyFrame(s, f('user.message', { content: '编辑文件' })); applyFrame(s, f('turn.start'))
  for (let step = 1; step <= 4; step++) {
    const c = { attempt_id: `a${step}`, step }
    applyFrame(s, f('assistant.start', {}, c)); applyFrame(s, f('assistant.message', { content: `第${step}步` }, c))
    applyFrame(s, f('assistant.end', {}, c)); assert.equal(s.activeTurn, 's:1')
    if (step < 4) { applyFrame(s, f('tool.call', { name: 'read' }, { ...c, call_id: 'same' })); applyFrame(s, f('tool.result', { name: 'read', status: 'succeeded' }, { ...c, call_id: 'same' })) }
  }
  assert.equal(Object.keys(s.tools).length, 3)
  assert.deepEqual(conversationRows(s).map(r => r.role || (r.name ? 'tool' : 'assistant')), ['user','assistant','tool','assistant','tool','assistant','tool','assistant'])
  applyFrame(s, f('turn.end', { reason: 'completed' })); assert.equal(s.activeTurn, null)
  applyFrame(s, f('turn.start', {}, { turn: 2, turn_id: 's:2' }))
  applyFrame(s, f('tool.result', { name:'read', status:'outcome_unknown' }, { turn:2,turn_id:'s:2',attempt_id:'a1',call_id:'same' }))
  assert.equal(Object.keys(s.tools).length, 4)
})

test('模型开始帧迟于文本或思考增量到达时，不倒退显示状态', () => {
  for (const [kind, phase] of [['assistant.text.delta', 'answering'], ['assistant.reasoning.delta', 'thinking']]) {
    const state = createLoopState('s'), f = fixture(), c = { attempt_id: 'a' }
    applyFrame(state, f('turn.start'))
    applyFrame(state, f(kind, { text: '已收到的片段', chunk_index: 0 }, c, 'transient'))
    applyFrame(state, f('assistant.start', { request_summary: { model: 'test' } }, c))
    assert.equal(state.phase, phase)
    assert.equal(Object.values(state.attempts).length, 1)
  }
})

test('轨迹每次模型请求合为一行，重试独立并保留最终正文和来源', () => {
  assert.equal(category('approval.requested'), 'approval')
  assert.equal(category('question.requested'), 'question')
  assert.equal(category('task_confirmation.requested'), 'approval')
  const f = fixture(), c = { attempt_id: 'a' }
  const facts = [f('assistant.start', {request_summary: {model: 'test'}}, c),
    f('assistant.message', {content: '完整回答'}, {...c, source_seq: 3}),
    f('assistant.end', {outcome: 'committed'}, c), f('assistant.start', {}, {attempt_id: 'b'})]
  const rows = semanticTraceRows(facts)
  assert.equal(rows.length, 2)
  assert.equal(rows[0].layers.length, 3)
  assert.equal(rows[0].data.content, '完整回答')
  assert.equal(rows[0].data.request_summary.model, 'test')
  const trace = createTrace(); trace.denied = true
  applyTrace(trace, f('trace.event', {event: {seq: 0}}, {}, 'control'))
  applyTrace(trace, f('schema.catalog', {secret: 'old'}, {}, 'control'))
  assert.equal(trace.events.length, 0); assert.equal(trace.catalog, null)
})
test('重连回放 interrupted 收尾后，旧 active turn 不再阻塞下一条输入', () => {
  const s = createLoopState('s'), f = fixture()
  applyFrame(s, f('turn.start'))
  assert.equal(s.activeTurn, 's:1')
  applyFrame(s, f('turn.end', { reason: 'interrupted' }))
  assert.equal(s.activeTurn, null)
  assert.equal(s.phase, 'interrupted')
})
test('1000 chunks、450 条历史、最终校正和迟到片段不回写终态', () => {
  const s = createLoopState('s'), f = fixture()
  for (let i = 0; i < 450; i++) applyFrame(s, f('user.message', { client_message_id:`u${i}`,content:String(i) }))
  applyFrame(s, f('assistant.start', {}, { attempt_id:'a' }))
  for(let i=0;i<1000;i++){const chunk=f('assistant.text.delta',{text:'x',chunk_index:i},{attempt_id:'a'},'transient');applyFrame(s,chunk);applyFrame(s,chunk)}
  const a=Object.values(s.attempts)[0]; assert.equal(a.text.length,1000)
  applyFrame(s,f('assistant.message',{content:'最终正文',reasoning_preview:'授权思考'},{attempt_id:'a'}))
  applyFrame(s,f('assistant.text.delta',{text:'迟到',chunk_index:1001},{attempt_id:'a'},'transient'))
  assert.equal(a.text,'最终正文');assert.equal(Object.keys(s.messages).length,450)
  const restored=restoreSnapshot('s',s.cursor,{timeline:s.facts})
  assert.equal(conversationRows(restored).length,451)
  assert.equal(Object.values(restored.attempts)[0].reasoning,'授权思考')
})
test('六态、恢复补偿与兄弟调用互不覆盖',()=>{
  const s=createLoopState('s'),f=fixture()
  const states=['succeeded','failed','denied','cancelled','not_started','outcome_unknown']
  states.forEach((status,index)=>applyFrame(s,f('tool.result',{name:'read',status,synthetic:index===5},{attempt_id:'a',call_id:`c${index}`})))
  assert.deepEqual(Object.values(s.tools).map(t=>t.status),states)
  applyFrame(s,f('runtime.error',{code:'INTERNAL',message:'失败'}));applyFrame(s,f('turn.end',{reason:'error'}))
  assert.equal(Object.values(s.tools)[5].status,'outcome_unknown')
})
test('Worker 的 report 和百分比不代表任务结束',()=>{
  const s=createLoopState('s'),f=fixture(),c={task_id:'task'}
  applyFrame(s,f('task.queued',{status:'queued'},c));applyFrame(s,f('task.progress',{progress:{percent:100}},c));applyFrame(s,f('task.report',{report_id:'r'},c))
  assert.equal(s.tasks.task.status,'queued')
  applyFrame(s,f('task.end',{status:'failed'},c));applyFrame(s,f('task.progress',{status:'running'},c));assert.equal(s.tasks.task.status,'failed')
})
test('trace seq=0 独立去重，复制脱敏及安全链接',()=>{
  const s=createTrace(),f=fixture();const event=f('trace.event',{event:{seq:0,type:'tool/call',data:{}}},{},'control')
  applyTrace(s,event);applyTrace(s,event);assert.equal(s.events.length,1);assert.equal(s.seq,0)
  const safe=safePacket({nonce:'private',spec_hash:'private',headers:{Authorization:'private'},deep:{api_key:'private',prompt_tokens:12},value:'Bearer abcdefgh123'})
  assert.ok(!JSON.stringify(safe).includes('private'));assert.equal(safe.deep.prompt_tokens,12)
  assert.equal(safeLink('javascript:alert(1)'),null);assert.equal(safeLink('//evil.test'),null);assert.equal(safeLink('/tasks'),'/tasks')
  assert.deepEqual(schemaRef({$defs:{'a/b':{type:'string'}}},'#/$defs/a~1b'),{type:'string'})
})
