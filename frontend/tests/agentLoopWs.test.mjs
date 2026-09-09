import test from 'node:test'
import assert from 'node:assert/strict'
import { AgentLoopWebSocket } from '../src/api/agentLoopWs.ts'
import { createLoopState } from '../src/agent/loop/reducer.ts'

globalThis.location = { protocol:'http:',host:'localhost' }
/** 可控 socket 模拟网络事件，不模拟业务副作用。 */
class Socket {
  readyState=1; sent=[]
  send(value){this.sent.push(JSON.parse(value))}
  close(){this.readyState=3}
  frame(type,data={},extra={}) { this.onmessage({data:JSON.stringify({protocol_version:2,type,data,durability:'control',correlation:{},ts:'2026-09-09T00:00:00Z',...extra})}) }
}
test('首次协商、缺口原连接恢复，快照在 H 后继续',async()=>{
  let state=createLoopState('s');const socket=new Socket()
  const client=new AgentLoopWebSocket('s',{ticket:async()=>'ticket',state:()=>state,replace:value=>state=value,socket:()=>socket})
  try {
    await client.connect();socket.frame('hello');socket.frame('capabilities',{stream_schema_version:'agent-loop-stream.v2.1'})
    assert.equal(socket.sent[0].data.after_cursor,0)
    socket.frame('replay.completed',{cursor:0},{session_id:'s'});assert.equal(state.ready,true)
    socket.frame('user.message',{content:'missed first'},{session_id:'s',durability:'persistent',cursor:2})
    assert.equal(state.cursor,0);assert.equal(socket.sent.at(-1).type,'subscribe')
    assert.ok(!socket.sent.some(c=>c.type==='unsubscribe'))
    socket.frame('resync.required',{cursor:2,snapshot:{timeline:[]}}, {session_id:'s'})
    assert.equal(state.cursor,2);assert.equal(socket.sent.at(-1).data.after_cursor,2)
  } finally { client.close() }
})
test('同一冻结命令重复发送保持 ID 和负载，错误版本关闭',async()=>{
  const state=createLoopState('s'),socket=new Socket()
  const client=new AgentLoopWebSocket('s',{ticket:async()=>'ticket',state:()=>state,replace:()=>{},socket:()=>socket})
  try {
    await client.connect();state.ready=true
    const cmd=client.command('turn.submit',{content:'hi',client_message_id:'m',attachment_refs:[],reasoning_effort:'off'})
    client.send(cmd);client.send(cmd);assert.deepEqual(socket.sent[0],socket.sent[1])
    socket.frame('capabilities',{stream_schema_version:'unknown'});assert.equal(socket.readyState,3);assert.match(state.error,/协议/)
  } finally { client.close() }
})

test('轨迹退订丢弃在途帧，重连按轨迹序号恢复且不自动重试拒绝的订阅', async () => {
  const state = createLoopState('s'), socket = new Socket(), frames = []
  const client = new AgentLoopWebSocket('s', {ticket:async()=>'ticket',state:()=>state,replace:()=>{},socket:()=>socket,onFrame:frame=>frames.push(frame)})
  try {
    await client.connect(); state.ready = true
    client.trace(true, -1)
    socket.frame('trace.event', {event:{seq:0}})
    client.trace(false)
    socket.frame('trace.event', {event:{seq:1}})
    socket.frame('schema.catalog', {etag:'late'})
    assert.equal(frames.length, 1)
    client.trace(true, 0)
    socket.frame('trace.event', {event:{seq:1}})
    socket.frame('replay.completed', {cursor:0})
    assert.equal(socket.sent.at(-1).data.after_seq, 1)
    const request = socket.sent.at(-1)
    socket.frame('command.rejected', {code:'UNAUTHORIZED'}, {request_id:request.request_id})
    const count = socket.sent.length
    socket.frame('replay.completed', {cursor:0})
    assert.equal(socket.sent.length, count)
  } finally { client.close() }
})
