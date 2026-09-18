import test from 'node:test'
import assert from 'node:assert/strict'
import { artifactLinks, finalResponseText, responseParts, writtenFiles } from '../src/agent/loop/responsePresentation.ts'
import { calculateTurnSummaries } from '../src/agent/loop/turnSummary.ts'
import { applyFrame, createLoopState } from '../src/agent/loop/reducer.ts'

const parts = [{output_index:0,phase:'commentary',text:'过程。'}, {output_index:1,phase:'final_answer',text:'答案。'}]
const row = {key:'a',role:'assistant',text:'过程。答案。',text_parts:parts,ended:true,correlation:{turn:1,turn_id:'s:1'},tool_calls:[]}

for (const protocol of ['openai_chat', 'openai_responses', 'anthropic_messages']) {
  test(`${protocol} 取消前缀实时与重连一致，下一轮不会继承旧阶段`, () => {
    const state = createLoopState('s')
    const replay = createLoopState('s')
    const correlation = {turn:1,turn_id:'s:1',attempt_id:'a'}
    const frame = {protocol_version:2,session_id:'s',ts:'',correlation}
    const textParts = protocol === 'openai_responses' ? [parts[0]] : null
    const metadata = textParts ? {output_index:0,phase:'commentary'} : {}
    applyFrame(state,{...frame,type:'assistant.text.delta',durability:'transient',data:{chunk_index:0,text:'过程。',...metadata}})
    const message = {...frame,type:'assistant.message',durability:'persistent',cursor:1,
      data:{content:'过程。',text_parts:textParts,interrupted:true}}
    applyFrame(state,message)
    applyFrame(replay,message)
    const live = Object.values(state.attempts)[0]
    const saved = Object.values(replay.attempts)[0]
    assert.deepEqual(responseParts(live),responseParts(saved))
    assert.equal(calculateTurnSummaries([live]).size,protocol === 'openai_responses' ? 0 : 1)
    assert.equal(calculateTurnSummaries([saved]).size,calculateTurnSummaries([live]).size)
    const next = {...frame,correlation:{turn:2,turn_id:'s:2',attempt_id:'b'}}
    applyFrame(state,{...next,type:'assistant.text.delta',durability:'transient',data:{chunk_index:0,text:'答案。'}})
    applyFrame(state,{...next,type:'assistant.message',durability:'persistent',cursor:2,data:{content:'答案。',text_parts:null}})
    const nextAttempt = Object.values(state.attempts)[1]
    assert.equal(finalResponseText(nextAttempt),'答案。')
    assert.equal(calculateTurnSummaries([nextAttempt]).size,1)
  })
}

test('阶段快照在实时与重连后相同，复制总结只包含最终答案', () => {
  const state = createLoopState('s')
  const replay = createLoopState('s')
  const correlation = {...row.correlation,attempt_id:'a'}
  const frame = {protocol_version:2,session_id:'s',ts:'',correlation}
  applyFrame(state, {...frame,type:'assistant.text.delta',durability:'transient',data:{chunk_index:0,text:row.text,text_parts:parts}})
  const message = {...frame,type:'assistant.message',durability:'persistent',cursor:1,data:{content:row.text,text_parts:parts}}
  applyFrame(state,message)
  applyFrame(replay,message)
  assert.deepEqual(Object.values(state.attempts)[0].text_parts,Object.values(replay.attempts)[0].text_parts)
  assert.equal(finalResponseText(row),'答案。')
  assert.equal(calculateTurnSummaries([row]).get('a').summaryText,'答案。')
  assert.equal(calculateTurnSummaries([{...row,text_parts:[parts[0]]}]).size,0)
  assert.equal(responseParts({...row,text_parts:undefined})[0].text,row.text)
})

function tool(path, extra = {}) {
  return {key:'t',correlation:row.correlation,status:'succeeded',display:{registry_name:'write',file_path:path},...extra}
}

test('下载映射包含绑定子目录，只匹配本轮实际成功文件，不做同名猜测', () => {
  const files = writtenFiles([tool('reports/计划.md'),tool('reports/计划.md')],row,'ws','scope')
  assert.equal(files.length,1)
  assert.equal(files[0].url,'/api/workspaces/ws/files/raw?path=scope%2Freports%2F%E8%AE%A1%E5%88%92.md&download=true')
  assert.equal(artifactLinks(files)['sandbox:/mnt/data/reports/计划.md'],files[0].url)
  assert.equal(artifactLinks(files)['sandbox:/mnt/data/计划.md'],undefined)
  assert.deepEqual(writtenFiles([tool('a')],row,null),[])
  assert.deepEqual(writtenFiles([tool('a')],row,'ws','../escape'),[])
  assert.match(writtenFiles([tool('a(1).md')],row,'ws')[0].url,/path=a%281%29.md/)
})

test('正文定位增量保持分段，最终快照可补报阶段而不重复文字', () => {
  const state = createLoopState('s')
  const base = {protocol_version:2,session_id:'s',durability:'transient',ts:'',type:'assistant.text.delta',correlation:{turn:1,turn_id:'s:1',attempt_id:'a'}}
  for (const [chunk_index,data] of [
    {output_index:0,phase:'commentary',text:'过程。'},
    {output_index:1,phase:null,text:'答'},
    {output_index:1,phase:null,text:'案。'},
    {text:'',text_parts:parts},
  ].entries()) applyFrame(state,{...base,data:{...data,chunk_index}})
  const attempt = Object.values(state.attempts)[0]
  assert.equal(attempt.text,'过程。答案。')
  assert.deepEqual(attempt.text_parts,parts)
})

for (const path of ['../secret','/etc/passwd','a/../../secret','%2e%2e/secret','a\\b','https://x','a\nb','a//b','a?b']) {
  test(`下载拒绝非法路径 ${JSON.stringify(path)}`, () => assert.deepEqual(writtenFiles([tool(path)],row,'ws'),[]))
}
for (const extra of [{status:'failed'},{status:'running'},{synthetic:true},{correlation:{turn:2,turn_id:'s:2'}},{display:{registry_name:'read',file_path:'a'}}]) {
  test(`不从失败/其他轮次/非写入回执生成链接 ${JSON.stringify(extra)}`, () => assert.deepEqual(writtenFiles([tool('a',extra)],row,'ws'),[]))
}
