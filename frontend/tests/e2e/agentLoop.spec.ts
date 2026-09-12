import { test, expect, type Page } from '@playwright/test'

const deepseekProfile = { id:'p',name:'DeepSeek 协议档',version:'v1',model:'deepseek-chat',protocol:'openai_chat',allowed_efforts:['off','low','medium','high','max'],default_effort:'medium' }
const compatibleProfile = { id:'p2',name:'兼容协议档',version:'v2',model:'qwen-plus',protocol:'openai_chat',allowed_efforts:['off','low','high'],default_effort:'high' }
// 与服务器实际型号/协议相同的能力夹具，验证滑动值进入 WS；真实供应商另行验收。
const serverProfiles = [
  { id:'p3',name:'MaaS DeepSeek',version:'v3',model:'deepseek-v4-flash-0731',protocol:'anthropic_messages',allowed_efforts:['off','high','max'],default_effort:'off' },
  { id:'p4',name:'MaaS Qwen',version:'v3',model:'qwen3.6-flash',protocol:'anthropic_messages',allowed_efforts:['off','low','medium','high','xhigh','max'],default_effort:'off' },
  { id:'p5',name:'NIM StepFun',version:'v3',model:'stepfun-ai/step-3.7-flash',protocol:'openai_chat',allowed_efforts:['off'],default_effort:'off' },
]
// 专家目录夹具：与后端 /agent-ui 的 agents 投影同形（只含展示字段，不含提示词与工具视野）。
const experts = [
  { id:'general',name:'通用助手',description:'平台默认助手：对话、工作区文件、评测任务入队与查询。',badge:'通用',default:true },
  { id:'testcase-agent',name:'测试用例设计专家',description:'从需求文档生成测试用例：需求解析 → 功能点/测试点拆分 → 六类用例 → CSV 交付。',badge:'用例设计',default:false },
]
const ui = { version:1,enabled:true,profile:deepseekProfile,profiles:[deepseekProfile,compatibleProfile,...serverProfiles],agent:'general',agents:experts,allowed_efforts:deepseekProfile.allowed_efforts,default_effort:deepseekProfile.default_effort,permissions:{write:true,trace:true,reasoning:true,interactions:true,settings:true},controller:{active:false,owned_by_actor:false},attachments:{upload_suffixes:['.txt'],inline_suffixes:['.txt'],image_suffixes:[],max_bytes:20971520,max_image_bytes:4194304,content_required:true} }

/** 真实页面与 WebSocket transport 使用协议夹具；不把夹具当供应商/沙箱闭环。 */
async function setup(page: Page, holdNewReplay = false) {
  // 契约回归使用系统字体，避免第三方字体 CDN 可达性影响页面就绪判定。
  await page.route('https://fonts.googleapis.com/**', route => route.fulfill({contentType:'text/css',body:''}))
  page.on('pageerror', error => console.log('页面异常：', error.message))
  page.on('console', message => { if (message.type() === 'error') console.log('浏览器错误：', message.text()) })
  const commands: any[] = [], sessionCreates: Record<string, unknown>[] = [], sockets = new Map<string, any>(), closed: string[] = []
  const requests: string[] = []
  let cursor=0, submit=0
  let releaseUpload: (()=>void) | undefined
  let releaseReplay: (()=>void) | undefined
  let holdReplay = false
  await page.route('**/api/**', async route => {
    const path=new URL(route.request().url()).pathname
    if (!path.startsWith('/api/')) { await route.continue(); return }
    requests.push(path)
    let body: any={}
    if(path==='/api/auth/me') body={id:'u',username:'tester',role:'admin',must_change_password:false}
    else if(path==='/api/auth/ws-ticket') body={ticket:'ticket',expires_in:300}
    else if(path==='/api/sessions' && route.request().method()==='GET') body=[{id:'s',title:'联调会话',owner_id:'u',visibility:'private',can_manage:true,can_delete:true,engine_version:'agent_loop_v2',workspace_id:'ws-default',workspace_name:'默认工作区',created_at:'2026-09-09T00:00:00Z'},{id:'s2',title:'另一个会话',owner_id:'u',visibility:'private',can_manage:true,can_delete:true,engine_version:'agent_loop_v2',workspace_id:'ws-default',workspace_name:'默认工作区',created_at:'2026-09-09T00:00:00Z'},{id:'legacy',title:'历史旧会话',owner_id:'u',visibility:'private',can_manage:true,can_delete:true,engine_version:'legacy',created_at:'2026-09-09T00:00:00Z'}]
    else if(path==='/api/sessions' && route.request().method()==='POST') { const payload=route.request().postDataJSON() as Record<string, unknown>;sessionCreates.push(payload);body={id:'s3',title:payload.title || '新会话',owner_id:'u',visibility:'private',can_manage:true,can_delete:true,engine_version:'agent_loop_v2',workspace_id:payload.workspace_id,created_at:'2026-09-09T00:00:00Z'} }
    else if(path.endsWith('/agent-ui')) body=ui
    else if(path==='/api/profiles') body=[{id:'p',name:'测试模型',model:'deepseek-chat',usages:['agent'],protocol:'openai_chat'}]
    else if(path==='/api/admin/settings') body={agent_profile_id:'p'}
    else if(['/api/datasets','/api/kb','/api/tasks'].includes(path)) body=[]
    else if(path==='/api/workspaces') body=[{id:'ws-default',name:'默认工作区'}]
    else if(path==='/api/files' && route.request().method()==='POST') { await new Promise<void>(resolve=>{releaseUpload=resolve});body={id:'f',filename:'draft.txt',size:5,content_type:'text/plain'} }
    await route.fulfill({json:body})
  })
  await page.routeWebSocket('**/ws/agent/v2?*', socket => {
    let socketSession = ''
    socket.onClose(() => { closed.push(socketSession) })
    const send=(type:string,data:any={},correlation:any={},persistent=false,sid='s')=>socket.send(JSON.stringify({protocol_version:2,type,durability:persistent?'persistent':'control',...(persistent?{cursor:++cursor}:{}),session_id:sid,ts:'2026-09-09T00:00:00Z',correlation,data}))
    socket.send(JSON.stringify({protocol_version:2,type:'hello',durability:'control',data:{protocol_version:2},correlation:{}}))
    socket.send(JSON.stringify({protocol_version:2,type:'capabilities',durability:'control',data:{stream_schema_version:'agent-loop-stream.v2.2'},correlation:{}}))
    socket.onMessage(raw=>{
      const cmd=JSON.parse(String(raw));commands.push(cmd);sockets.set(cmd.session_id,socket)
      socketSession = cmd.session_id
      const sid=cmd.session_id, c={turn:1,turn_id:`${sid}:1`,step:1,attempt_id:'a',call_id:'c'}
      if(cmd.type==='ping') send('pong',cmd.data,{},false,sid)
      if(cmd.type==='subscribe') {
        send('subscribed',{cursor:cmd.session_id==='s'?cursor:0},{},false,cmd.session_id)
        const replay=()=>send('replay.completed',{cursor:cmd.session_id==='s'?cursor:0},{},false,cmd.session_id)
        if(holdReplay || holdNewReplay && cmd.session_id==='s3') releaseReplay=replay
        else replay()
      }
      if(cmd.type==='turn.submit') {
        submit++
        send('user.message',{content:cmd.data.content,client_message_id:cmd.data.client_message_id},{turn:1,turn_id:`${sid}:1`},true,sid)
        send('turn.start',{},c,true,sid)
        socket.send(JSON.stringify({protocol_version:2,type:'command.accepted',durability:'control',session_id:sid,request_id:cmd.request_id,data:{accepted:true},correlation:c}))
        send('assistant.start',{request_summary:{model:'deepseek-chat',reasoning_effort:cmd.data.reasoning_effort,profile_version:'v1'}},c,true,sid)
        // 第一步明确携带工具调用身份，是 ReAct 执行过程而不是可操作的本轮总结。
        const processTool = cmd.data.content === '创建评测任务' ? 'platform.tasks.task.create' : 'read'
        const processCallId = cmd.data.content === '创建评测任务' ? 'task-create' : 'c'
        send('assistant.message',{content:'准备读取文件',reasoning_preview:'检查工作区',tool_calls:[{id:processCallId,name:processTool}],usage:{prompt_tokens:1500,completion_tokens:320,total_tokens:1820,cache_read_input_tokens:600},latency_ms:800},c,true,sid)
        send('assistant.end',{outcome:'committed'},c,true,sid)
        if (cmd.data.content === '创建评测任务') {
          // 夹具直接采用后端允许的 MCP 全名，验证前端不依赖某一种模型 wire 名。
          const taskCorrelation = {turn:1,turn_id:`${sid}:1`,step:1,attempt_id:'a',call_id:'task-create'}
          send('tool.call',{name:'platform.tasks.task.create',display:{version:1,registry_name:'task.create',wire_name:'platform.tasks.task.create',arguments_preview:'{"kind":"benchmark"}'}},taskCorrelation,true,sid)
          send('tool.dispatch',{name:'platform.tasks.task.create',registry_name:'task.create',wire_name:'platform.tasks.task.create'},taskCorrelation,true,sid)
          send('tool.result',{name:'platform.tasks.task.create',status:'succeeded',display:{version:1,registry_name:'task.create',wire_name:'platform.tasks.task.create',format:'json',result_preview:'{"task_id":"task-1","kind":"benchmark","status":"queued"}'}},taskCorrelation,true,sid)
          send('task.queued',{status:'queued'}, {task_id:'task-1'},true,sid)
          send('task.progress',{status:'running',progress:{percent:42,message:'正在执行第 42 项'}}, {task_id:'task-1'},true,sid)
          send('turn.end',{reason:'completed'},c,true,sid)
        } else {
          send('tool.call',{name:'read',display:{version:1,target:'test.txt',arguments_preview:'{"path":"test.txt"}'}},c,true,sid)
          if (cmd.data.content === '补充执行信息') {
            send('question.requested',{interaction_id:'question-i',nonce:'question-nonce-memory-only',expires_at:Date.now()/1000+300,questions:[
              {id:'mode',question:'选择评测方式',type:'radio',required:true,options:[{label:'标准评测',description:'使用默认基准配置'},{label:'快速验证',description:'使用最小样本验证'}]},
              {id:'sources',question:'选择资料来源',type:'checkbox',required:true,options:[{label:'本地检索'},{label:'联网检索'}]},
              {id:'note',question:'补充执行说明',type:'text',required:true},
            ]},c,true,sid)
          } else send('approval.requested',{interaction_id:'i',nonce:'nonce-memory-only',expires_at:Date.now()/1000+300,name:'read'},c,true,sid)
        }
      }
      if(cmd.type==='approval.respond') {
        send('approval.resolved',{interaction_id:'i',decision:cmd.data.decision},c,true,sid)
        send('tool.result',{name:'read',status:cmd.data.decision==='deny'?'denied':'succeeded',display:{version:1,result_preview:'实际输出夹具'}},c,true,sid)
        // 工具结算后第二次模型输出才是总结；未返回 usage 时聚合指标保持第一步的真实字段。
        const summaryCorrelation = {...c,step:2,attempt_id:'a2'}
        send('assistant.start',{request_summary:{model:'deepseek-chat',reasoning_effort:'high',profile_version:'v1'}},summaryCorrelation,true,sid)
        send('assistant.message',{content:'文件已读取完成。',reasoning_preview:'根据工具结果总结。'},summaryCorrelation,true,sid)
        send('assistant.end',{outcome:'committed'},summaryCorrelation,true,sid)
        send('turn.end',{reason:'completed'},summaryCorrelation,true,sid)
      }
      if(cmd.type==='question.respond') {
        send('question.resolved',{interaction_id:'question-i',outcome:'answered',answers:cmd.data.answers},c,true,sid)
        send('tool.result',{name:'read',status:'succeeded',display:{version:1,result_preview:'已采用补充信息'}},c,true,sid)
        send('turn.end',{reason:'completed'},c,true,sid)
      }
      if(cmd.type==='trace.subscribe') { send('schema.catalog',{stream:{types:{'tool.call':{fields:['name','display']}}},facts:{events:{}}});send('trace.event',{event:{seq:0,type:'tool/call',data:{name:'read'},correlation:c}}) }
    })
  })
  await page.goto('/agent', {waitUntil:'domcontentloaded'})
  if ((page.viewportSize()?.width || 1440) <= 768) await page.getByTitle('折叠/展开会话列表').click()
  await expect(page.getByLabel('会话引擎')).toHaveCount(0)
  await expect(page.getByText('历史旧会话',{exact:true})).toHaveCount(0)
  await page.locator('.session-title-text').filter({hasText:'联调会话'}).click()
  await expect(page.getByRole('textbox',{name:'消息'})).toBeVisible()
  // 空会话按当前产品约定隐藏“就绪”状态，运行信息入口仍应可见。
  await expect(page.locator('.loop-runtime-btn')).toBeVisible()
  return {commands,sessionCreates,get submits(){return submit},get uploading(){return !!releaseUpload},release:()=>releaseUpload?.(),replay:()=>releaseReplay?.(),holdReplay:()=>{holdReplay=true},sockets,closed,requests}
}

test('工作台初始化不再预加载旧栈偏好、模型和确认卡选项', async ({page}) => {
  const ctx = await setup(page)
  await page.getByRole('textbox',{name:'消息'}).fill('初始化后可发送')
  await expect(page.getByRole('button',{name:'发送',exact:true})).toBeEnabled()
  const legacyPaths = ['/api/agent/prefs', '/api/profiles', '/api/admin/settings', '/api/datasets', '/api/kb']
  expect(ctx.requests.filter(path => legacyPaths.includes(path))).toEqual([])
  expect(ctx.requests).toContain('/api/sessions')
  expect(ctx.requests).toContain('/api/sessions/s/agent-ui')
})

for (const [status, label] of Object.entries({failed:'失败',denied:'已拒绝',cancelled:'已取消',not_started:'未启动',outcome_unknown:'结果未知'})) test(`任务规划 ${status} 可见且保留最后成功计划`, async ({page}) => {
  const ctx = await setup(page)
  await expect.poll(() => ctx.sockets.has('s')).toBe(true)
  let cursor = 0
  const correlation = {turn:1,turn_id:'s:1',step:1,attempt_id:'plan-attempt',call_id:'plan-ok'}
  // 先建立成功看板，再注入失败更新，避免失败记录覆盖当前计划或生成助手占位。
  const send = (type: string, data: Record<string, unknown> = {}) => ctx.sockets.get('s').send(JSON.stringify({
    protocol_version:2,type,durability:'persistent',cursor:++cursor,session_id:'s',
    ts:'2026-09-12T00:00:00Z',correlation,data,
  }))
  send('turn.start')
  send('tool.call', {name:'task'})
  send('tool.result', {name:'task',status:'succeeded'})
  send('task_plan.updated', {plan:{goal:'最后成功的计划',description:'最后成功的计划',
    steps:[{title:'已完成步骤',status:'completed'}],counts:{pending:0,in_progress:0,completed:1}}})
  correlation.call_id = 'plan-failed'
  send('tool.call', {name:'task'})
  send('tool.result', {name:'task',status,display:{version:1,result_preview:'本次任务规划更新未成功'}})
  send('turn.end', {reason:'completed'})
  const card = page.locator('.tool-run')
  await expect(card).toHaveCount(1)
  await expect(card.locator('.tool-state')).toHaveText(label)
  await card.locator('summary').first().click()
  await expect(card.getByText('本次任务规划更新未成功', {exact:true})).toBeVisible()
  await expect(page.locator('.task-goal')).toHaveText('最后成功的计划')
  await expect(page.locator('.task-progress')).toHaveText('1/1')
  await expect(page.locator('.loop-message.assistant')).toHaveCount(0)
  await expect(page.getByText('正在响应…', {exact:true})).toHaveCount(0)
  await page.getByRole('textbox', {name:'消息'}).fill('继续')
  await expect(page.getByRole('button', {name:'发送',exact:true})).toBeEnabled()
})

for (const reason of ['completed', 'max_steps']) test(`任务规划更新后不产生助手占位，${reason} 收尾允许继续发送`, async ({page}) => {
  const ctx = await setup(page)
  await expect.poll(() => ctx.sockets.has('s')).toBe(true)
  let cursor = 0
  const correlation = {turn:1,turn_id:'s:1',step:16,attempt_id:'final-step',call_id:'plan-update'}
  // 复现最后一步更新任务清单后结束；不调用供应商，也不额外生成总结。
  const send = (type: string, data: Record<string, unknown> = {}) => ctx.sockets.get('s').send(JSON.stringify({
    protocol_version:2,type,durability:'persistent',cursor:++cursor,session_id:'s',
    ts:'2026-09-12T00:00:00Z',correlation,data,
  }))
  send('turn.start')
  send('assistant.start')
  send('assistant.message', {content:'文件内容完整，更新任务清单为完成状态',tool_calls:[{id:'plan-update',name:'task'}]})
  send('assistant.end', {outcome:'committed'})
  send('tool.call', {name:'task'})
  send('tool.result', {name:'task',status:'succeeded'})
  send('task_plan.updated', {plan:{goal:'完成成都家庭游计划',description:'完成成都家庭游计划',
    steps:Array.from({length:5}, (_, index) => ({title:`完成第 ${index + 1} 项`,status:'completed'})),
    counts:{pending:0,in_progress:0,completed:5}}})
  await expect(page.getByText('完成成都家庭游计划', {exact:true})).toBeVisible()
  await expect(page.getByText('5/5', {exact:true})).toBeVisible()
  const taskDrawer = page.locator('.task-state-drawer')
  const taskDrawerHeader = taskDrawer.getByRole('button', {name:/任务规划/})
  const taskSteps = taskDrawer.locator('.task-step-title')
  await expect(taskDrawerHeader).toHaveAttribute('aria-expanded', 'false')
  await expect(taskSteps).toHaveCount(0)
  await taskDrawerHeader.click()
  await expect(taskSteps.first()).toHaveText('task 1 ：完成第 1 项')
  await expect(page.getByText('正在响应…', {exact:true})).toHaveCount(0)
  await expect(page.locator('.loop-message.assistant')).toHaveCount(1)
  send('turn.end', {reason})
  if (reason === 'max_steps') await expect(page.locator('.loop-conversation > .loop-notice')).toContainText('达到步骤上限')
  await page.getByRole('textbox', {name:'消息'}).fill('继续')
  await expect(page.getByRole('button', {name:'发送',exact:true})).toBeEnabled()
  await expect(page.getByText('正在响应…', {exact:true})).toHaveCount(0)
})

test('重复聚焦合并能力请求，刷新期间可发送，切会话拒绝旧响应', async ({page}) => {
  await page.clock.install()
  await setup(page)
  await page.clock.runFor(1100)
  let requests = 0, release!: () => void
  const held = new Promise<void>(resolve => { release = resolve })
  await page.route('**/api/sessions/s/agent-ui', async route => {
    requests++
    await held
    // 模拟取消后仍可能完成的旧作用域响应，不能覆盖新会话的模型候选。
    await route.fulfill({json:{...ui, profiles:[], profile:null}}).catch(() => {})
  })
  await page.evaluate(() => { for(let i=0;i<20;i++) window.dispatchEvent(new Event('focus')) })
  await expect.poll(() => requests).toBe(1)
  await page.getByRole('textbox',{name:'消息'}).fill('刷新期间仍可发送')
  await expect(page.getByRole('button',{name:'发送',exact:true})).toBeEnabled()
  await page.locator('.session-title-text').filter({hasText:'另一个会话'}).click()
  release()
  await page.getByRole('textbox',{name:'消息'}).fill('新会话继续发送')
  await expect(page.getByRole('button',{name:'发送',exact:true})).toBeEnabled()
  expect(requests).toBe(1)
})

test('后台空闲释放后使用原游标恢复，快速切回复用原连接', async ({page}) => {
  await page.clock.install()
  const ctx = await setup(page)
  await page.getByRole('textbox',{name:'消息'}).fill('检查恢复状态')
  await page.getByRole('button',{name:'发送',exact:true}).click()
  await page.getByRole('button',{name:'允许一次',exact:true}).click()
  await expect(page.getByText('文件已读取完成。',{exact:true})).toBeVisible()
  const select = (title: string) => page.locator('.session-title-text').filter({hasText:title}).click()
  await select('另一个会话')
  await select('联调会话')
  expect(ctx.commands.filter(c=>c.type==='subscribe' && c.session_id==='s')).toHaveLength(1)
  await select('另一个会话')
  await page.clock.runFor(75000)
  await expect.poll(()=>ctx.closed.includes('s')).toBe(true)
  ctx.holdReplay()
  await select('联调会话')
  await expect.poll(()=>ctx.commands.filter(c=>c.type==='subscribe' && c.session_id==='s').length).toBe(2)
  const resumed = ctx.commands.filter(c=>c.type==='subscribe' && c.session_id==='s')[1]
  expect(resumed.data.after_cursor).toBeGreaterThan(0)
  // 缓存只用于增量恢复，服务端尚未完成授权回放时不能闪现旧正文。
  await expect(page.getByText('文件已读取完成。',{exact:true})).toHaveCount(0)
  ctx.replay()
  await expect(page.getByText('文件已读取完成。',{exact:true})).toBeVisible()
})

test('新建会话固定采用 AgentLoop transport',async({page})=>{
  const ctx=await setup(page)
  await page.getByRole('button',{name:/新建会话/}).click()
  await page.getByRole('textbox',{name:'消息'}).fill('创建 AgentLoop 会话')
  await page.getByRole('button',{name:'发送'}).click()
  await expect.poll(()=>ctx.sessionCreates.length).toBe(1)
  expect(ctx.sessionCreates[0].engine_version).toBe('agent_loop_v2')
  await expect.poll(()=>ctx.commands.some(command=>command.type==='subscribe' && command.session_id==='s3')).toBe(true)
  await expect.poll(()=>ctx.commands.some(command=>command.type==='turn.submit' && command.session_id==='s3')).toBe(true)
})

test('HTTP 缺少 randomUUID 时新建会话、附件、发送和工具结果回流完整可用', async ({page}) => {
  await page.addInitScript(() => Object.defineProperty(Crypto.prototype, 'randomUUID', {value:undefined, configurable:true}))
  const ctx = await setup(page)
  await page.getByRole('button', {name:/新建会话/}).click()
  await expect(page.getByRole('button', {name:'添加附件'})).toBeEnabled()
  await page.locator('.loop-composer input[type=file]').setInputFiles({name:'draft.txt', mimeType:'text/plain', buffer:Buffer.from('hello')})
  await expect(page.locator('.draft-files')).toContainText('draft.txt')
  await expect.poll(() => ctx.uploading).toBe(true)
  ctx.release()
  await page.getByRole('textbox', {name:'消息'}).fill('验证 HTTP 全链路')
  await page.getByRole('button', {name:'发送', exact:true}).click()
  await expect.poll(() => ctx.submits).toBe(1)
  const submit = ctx.commands.find(command => command.type === 'turn.submit')
  expect(submit.session_id).toBe('s3')
  expect(submit.data.attachment_refs).toEqual(['f'])
  expect(submit.request_id).toMatch(/^[0-9a-f-]{36}$/)
  expect(submit.data.client_message_id).not.toBe(submit.request_id)
  const approvalDrawer = page.locator('.composer-interaction-drawer')
  await expect(approvalDrawer).toContainText('工具权限请求')
  await expect(page.locator('.tool-run .interaction')).toHaveCount(0)
  await approvalDrawer.getByRole('button', {name:'允许一次', exact:true}).click()
  await expect(page.locator('.tool-state').first()).toHaveText('已完成')
  await expect(page.getByRole('textbox', {name:'消息'})).toHaveValue('')
  await expect(page.getByText('草稿已保留', {exact:false})).toHaveCount(0)
})

test('工具审批和 ask_user_question 在输入框上方抽屉处理，题型与自定义答案完整回传', async ({page}) => {
  const ctx = await setup(page)
  await page.getByRole('textbox', {name:'消息'}).fill('补充执行信息')
  await page.getByRole('button', {name:'发送', exact:true}).click()

  const drawer = page.locator('.composer-interaction-drawer')
  await expect(drawer).toBeVisible()
  await expect(drawer).toContainText('请补充执行所需信息')
  await expect(drawer).toContainText('问题 1 / 3')
  await expect(drawer).toContainText('单择题')
  await expect(drawer.getByText('选择资料来源', {exact:true})).toHaveCount(0)
  await expect(drawer.getByText('补充执行说明', {exact:true})).toHaveCount(0)
  // 待处理表单不再嵌入工具时间线，避免工具详情撑高对话区。
  await expect(page.locator('.tool-run .interaction')).toHaveCount(0)

  const drawerBox = (await drawer.boundingBox())!
  const composerBox = (await page.locator('.loop-composer').boundingBox())!
  expect(composerBox.y - (drawerBox.y + drawerBox.height)).toBeGreaterThanOrEqual(0)
  expect(composerBox.y - (drawerBox.y + drawerBox.height)).toBeLessThanOrEqual(16)

  const radioOptions = drawer.locator('input[type=radio]')
  await radioOptions.last().check()
  await drawer.getByLabel('选择评测方式的自定义回答').fill('混合模式')
  await drawer.getByRole('button', {name:'下一题', exact:true}).click()
  await expect(drawer).toContainText('问题 2 / 3')
  await expect(drawer).toContainText('多选题')
  const checkboxes = drawer.locator('input[type=checkbox]')
  await checkboxes.first().check()
  await checkboxes.last().check()
  await drawer.getByLabel('选择资料来源的自定义回答').fill('离线缓存')
  await drawer.getByRole('button', {name:'下一题', exact:true}).click()
  await expect(drawer).toContainText('问题 3 / 3')
  await expect(drawer).toContainText('简答题')
  await drawer.getByRole('button', {name:'上一题', exact:true}).click()
  await expect(drawer).toContainText('问题 2 / 3')
  await expect(checkboxes.first()).toBeChecked()
  await expect(drawer.getByLabel('选择资料来源的自定义回答')).toHaveValue('离线缓存')
  await drawer.getByRole('button', {name:'下一题', exact:true}).click()
  await drawer.getByLabel('补充执行说明').fill('保留数据来源')
  await drawer.getByRole('button', {name:'提交回答', exact:true}).click()

  await expect.poll(() => ctx.commands.find(command => command.type === 'question.respond')?.data.answers).toEqual([
    {question_id:'mode',answer:'',custom:'混合模式'},
    {question_id:'sources',answer:['本地检索'],custom:'离线缓存'},
    {question_id:'note',answer:'',custom:'保留数据来源'},
  ])
  await expect(drawer).toHaveCount(0)
  await expect(page.locator('.tool-state').first()).toHaveText('已完成')
})

test('窄屏交互抽屉保持在输入框上方且不产生横向溢出', async ({page}) => {
  await page.setViewportSize({width:390,height:844})
  await setup(page)
  await page.getByRole('textbox', {name:'消息'}).fill('补充执行信息')
  await page.getByRole('button', {name:'发送', exact:true}).click()

  const drawer = page.locator('.composer-interaction-drawer')
  await expect(drawer).toBeVisible()
  const drawerBox = (await drawer.boundingBox())!
  const composerBox = (await page.locator('.loop-composer').boundingBox())!
  expect(drawerBox.x).toBeGreaterThanOrEqual(0)
  expect(drawerBox.x + drawerBox.width).toBeLessThanOrEqual(390)
  expect(composerBox.y - (drawerBox.y + drawerBox.height)).toBeGreaterThanOrEqual(0)
  expect(composerBox.y - (drawerBox.y + drawerBox.height)).toBeLessThanOrEqual(16)
  await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(390)
})

test('草稿工作区浮层不扩张空状态布局，Task 卡片接收 MCP 名与 Worker 实时事件', async ({page}) => {
  await setup(page)
  await page.getByRole('button', {name:'新建会话'}).click()
  const workspaceButton = page.locator('.composer-ws-btn').first()
  const messageInput = page.getByRole('textbox', {name:'消息'})
  await workspaceButton.click()
  await expect(workspaceButton).toHaveClass(/is-open/)
  const workspacePopover = page.locator('.ws-popover-card')
  await expect(workspacePopover).toBeVisible()
  // Vue scoped 样式会为 keyframes 追加哈希，保留名称前缀即可验证入场动画实际生效。
  await expect.poll(() => workspacePopover.evaluate(element => getComputedStyle(element).animationName)).toMatch(/^workspace-popover-enter/)
  // 浮层保留自身高度加间距，不能留下旧固定 356px 的多余空白。
  await expect.poll(async () => {
    const popoverBox = (await workspacePopover.boundingBox())!
    const inputBox = (await messageInput.boundingBox())!
    return inputBox.y - (popoverBox.y + popoverBox.height)
  }).toBeGreaterThanOrEqual(-2)
  await expect.poll(async () => {
    const popoverBox = (await workspacePopover.boundingBox())!
    const inputBox = (await messageInput.boundingBox())!
    return inputBox.y - (popoverBox.y + popoverBox.height)
  }).toBeLessThanOrEqual(24)
  // 保留真实浏览器快照，供工作区弹层的视觉回归核验。
  await page.screenshot({path:'test-results/workspace-popover-task-card-ux.png'})
  await workspaceButton.click()
  await expect(workspacePopover).toHaveCount(0)

  await page.getByRole('textbox',{name:'消息'}).fill('创建评测任务')
  await page.getByRole('button',{name:'发送',exact:true}).click()
  const taskCard = page.locator('[data-task-tool="task.create"]')
  await expect(taskCard).toBeVisible()
  await expect(taskCard).toHaveAttribute('data-task-id','task-1')
  await expect(taskCard).toContainText('正在执行第 42 项')
  await expect(taskCard.getByRole('progressbar')).toHaveAttribute('aria-valuenow','42')
  await expect(taskCard).toContainText('执行中')
  // Task 卡由 MCP 规范名称与 Worker 事件共同驱动，快照用于联调回归。
  await page.screenshot({path:'test-results/task-run-card-task-card-ux.png'})
})

test('专家选择写入本轮 turn.submit 的 agent_id',async({page})=>{
  const ctx=await setup(page)
  // 默认专家在触发按钮上可见；选择器列出全部专家并可切换。
  await expect(page.locator('.agent-trigger')).toContainText('通用助手')
  await page.locator('.agent-trigger').click()
  await page.locator('.model-option').filter({hasText:'测试用例设计专家'}).click()
  await expect(page.locator('.agent-trigger')).toContainText('测试用例设计专家')
  await page.getByRole('textbox',{name:'消息'}).fill('生成用例')
  await page.getByRole('button',{name:'发送',exact:true}).click()
  await expect.poll(()=>ctx.commands.find(command=>command.type==='turn.submit')?.data.agent_id).toBe('testcase-agent')
})

test('协议档选择会同步收窄思考强度并冻结到本轮请求',async({page})=>{
  const ctx=await setup(page)
  await page.getByRole('button',{name:/deepseek-chat/}).click()
  await page.locator('.model-option').filter({hasText:'兼容协议档'}).click()
  await expect(page.getByRole('button',{name:/思考.*高强度/})).toBeVisible()
  await page.getByRole('textbox',{name:'消息'}).fill('使用兼容协议档')
  await page.getByRole('button',{name:'发送'}).click()
  await expect.poll(()=>ctx.commands.find(command=>command.type==='turn.submit')?.data.profile_id).toBe('p2')
  expect(ctx.commands.find(command=>command.type==='turn.submit')?.data.reasoning_effort).toBe('high')
})

for (const profile of serverProfiles.slice(0, 2)) {
  test(`${profile.model} 思考滑块拖动、方向键与 WS 请求一致`, async ({page}) => {
    const ctx = await setup(page)
    await page.getByRole('button', {name:/deepseek-chat/}).click()
    await page.locator('.model-option').filter({hasText:profile.name}).click()
    await page.getByRole('button', {name:/^思考强度：/}).click()
    const slider = page.getByRole('slider', {name:'思考强度', exact:true})
    await expect(slider).toBeEnabled()
    await expect(slider).toHaveAttribute('max', String(profile.allowed_efforts.length - 1))
    // 切换模型会保留仍受支持的偏好；先归零，再验证真实指针拖动。
    await slider.press('Home')
    await expect(slider).toHaveValue('0')
    // 等待弹层缩放结束再取坐标；按下后越过可视轨道右侧，触发原生 range 对最大值的钳制，避免各浏览器在最后 1px 的落点差异。
    await slider.click({trial:true})
    const box = (await slider.boundingBox())!
    await page.mouse.move(box.x + 15, box.y + box.height / 2)
    await page.mouse.down()
    await page.mouse.move(box.x + box.width + 15, box.y + box.height / 2, {steps:8})
    await page.mouse.up()
    await expect(slider).toHaveAttribute('aria-valuetext', '最高强度')
    await slider.press('Home')
    await expect(slider).toHaveAttribute('aria-valuetext', '关闭')
    await slider.press('End')
    await slider.press('Escape')
    await page.getByRole('textbox', {name:'消息'}).fill('验证滑动档位')
    await page.getByRole('button', {name:'发送', exact:true}).click()
    await expect.poll(() => ctx.submits).toBe(1)
    const command = ctx.commands.find(item => item.type === 'turn.submit')
    expect(command.data.profile_id).toBe(profile.id)
    expect(command.data.reasoning_effort).toBe('max')
  })
}

test('仅支持关闭的模型明确说明不可调节', async ({page}) => {
  await setup(page)
  await page.getByRole('button', {name:/deepseek-chat/}).click()
  await page.locator('.model-option').filter({hasText:'NIM StepFun'}).click()
  await page.getByRole('button', {name:'思考强度：关闭', exact:true}).click()
  await expect(page.getByRole('slider', {name:'思考强度', exact:true})).toBeDisabled()
  await expect(page.getByText('当前模型配置仅支持“关闭”，无法调节思考强度。')).toBeVisible()
})

test('首次订阅超时保留草稿，迟到回放不自动发送，原请求可手动重试', async ({page}) => {
  const ctx = await setup(page, true)
  await page.clock.install()
  await page.getByRole('button', {name:/新建会话/}).click()
  await page.getByRole('textbox', {name:'消息'}).fill('超时后保留的消息')
  await page.getByRole('button', {name:'发送', exact:true}).click()
  await expect.poll(() => ctx.commands.some(command => command.type === 'subscribe' && command.session_id === 's3')).toBe(true)
  await page.clock.fastForward(16000)
  await expect(page.getByRole('alert')).toContainText('消息尚未确认发送')
  await expect(page.getByRole('textbox', {name:'消息'})).toHaveValue('超时后保留的消息')
  expect(ctx.submits).toBe(0)
  ctx.replay()
  await expect(page.getByRole('button', {name:'使用原请求 ID 重发'})).toBeEnabled()
  expect(ctx.submits).toBe(0)
  await page.getByRole('button', {name:'使用原请求 ID 重发'}).click()
  await expect.poll(() => ctx.submits).toBe(1)
  await expect(page.getByRole('alert')).toHaveCount(0)
})

test('消息操作和真实模型指标遵循持久事件字段', async ({page}) => {
  const ctx = await setup(page)
  await page.getByRole('textbox', {name:'消息'}).fill('读取测试文件')
  await page.getByRole('button', {name:'发送'}).click()
  await expect(page.locator('.assistant-identity time')).toContainText('2026')
  await expect(page.locator('.loop-bottom-metrics')).toContainText('生成token速度 400/s')
  await expect(page.locator('.loop-bottom-metrics')).toContainText('缓存命中率 40%')
  await expect(page.locator('.loop-bottom-metrics')).toContainText('输入 1.5K · 输出 320')
  await page.getByRole('button', {name:'允许一次', exact:true}).click()
  await expect(page.getByLabel('复制回答')).toBeVisible()
  await expect(page.getByLabel('引用为参考记忆')).toBeVisible()
  await expect(page.getByText('执行过程 · step 1', {exact:true})).toBeVisible()
  await expect(page.getByText('执行过程 · 工具调用', {exact:true})).toBeVisible()
  await expect(page.getByText('本轮总结', {exact:true})).toBeVisible()
  await expect(page.locator('.assistant-metrics')).toContainText('1.8K token')
  await expect(page.locator('.assistant-metrics')).toContainText('800 ms')
  await page.getByLabel('引用为参考记忆').click()
  await expect(page.getByRole('textbox', {name:'消息'})).toHaveValue('[引用对话记忆]\n文件已读取完成。\n[/引用对话记忆]')
  await expect(page.getByRole('button', {name:'重新生成'})).toBeEnabled()
  await page.getByRole('button', {name:'重新生成'}).click()
  await expect.poll(() => ctx.submits).toBe(2)
  expect(ctx.commands.filter(command => command.type === 'turn.submit')[1].data.content).toBe('读取测试文件')
})

test('多步工具内审批、attempt 结束不解锁发送、切会话不取消、轨迹可用',async({page})=>{
  const ctx=await setup(page)
  await page.getByRole('textbox',{name:'消息'}).fill('读取测试文件')
  await page.getByRole('button',{name:'发送'}).click()
  await expect(page.locator('.loop-composer')).toHaveClass(/is-busy/)
  await expect(page.locator('.composer-border-beam')).toBeVisible()
  await expect(page.getByRole('button',{name:'允许一次',exact:true})).toBeVisible()
  await expect(page.getByRole('button',{name:'停止执行',exact:true})).toBeVisible()
  await page.locator('.session-title-text').filter({hasText:'另一个会话'}).click()
  await page.locator('.session-title-text').filter({hasText:'联调会话'}).click()
  expect(ctx.commands.some(c=>c.type==='unsubscribe')).toBe(false)
  await page.getByRole('button',{name:'允许一次',exact:true}).click()
  await expect(page.locator('.tool-state').first()).toHaveText('已完成')
  await expect(page.locator('.loop-composer')).not.toHaveClass(/is-busy/)
  await expect(page.locator('.composer-border-beam')).toHaveCount(0)
  await expect(page.getByText('提交结果待同步。',{exact:false})).toHaveCount(0)
  await page.locator('.tool-run>summary').click()
  await expect(page.getByText('实际输出夹具',{exact:true})).toBeVisible()
  await page.getByRole('button',{name:/^轨迹/}).click()
  await expect(page.getByRole('textbox',{name:'搜索轨迹'})).toBeVisible()
  await page.getByRole('textbox',{name:'搜索轨迹'}).fill('tool.call')
  await page.locator('.trace-row').first().click()
  await expect(page.locator('.trace-inspector')).toBeVisible()
  await expect(page.locator('.trace-lanes')).toContainText('模型')
  await expect(page.locator('.trace-detail-tabs')).toContainText('参数')
  await expect(page.locator('.trace-detail-tabs')).toContainText('结果')
  await expect(page.locator('.trace-detail-tabs')).toContainText('Schema')
  await page.getByRole('textbox',{name:'搜索轨迹'}).fill('')
  await page.locator('.trace-filters').getByRole('button',{name:'模型',exact:true}).click()
  // 工具过程与最终总结各自对应一次模型请求/提交，因此模型轨迹为四条。
  await expect(page.locator('.trace-row')).toHaveCount(4)
  await expect(page.locator('.trace-filters').getByRole('button',{name:'授权',exact:true})).toBeVisible()
  await expect(page.locator('.trace-filters').getByRole('button',{name:'问答',exact:true})).toHaveCount(0)
  await page.locator('.trace-row').first().click()
  await expect(page.locator('.trace-detail-title')).toHaveText('模型请求快照')
  await expect(page.locator('.trace-detail-tabs')).toContainText('原始内容')
  await expect(page.locator('.trace-detail-tabs')).toContainText('数据包')
  await page.locator('.trace-filters').getByRole('button',{name:'全部',exact:true}).click()
  // 拖选允许经过泳道空白，详情定位到松手的事件且不丢失选区。
  const axis = page.locator('.trace-axis'), box = (await axis.boundingBox())!
  await page.mouse.move(box.x + 3, box.y + 44); await page.mouse.down()
  await page.mouse.move(box.x + box.width - 3, box.y + 44); await page.mouse.up()
  await expect(page.locator('.trace-range')).toBeVisible()
  await page.screenshot({path:'test-results/agentloop-trace.png',fullPage:true,animations:'disabled'})
  await axis.focus(); await axis.press('Escape')
  await expect(page.locator('.trace-inspector')).toHaveCount(0)
  await page.locator('.session-title-text').filter({hasText:'另一个会话'}).click()
  await expect.poll(()=>ctx.commands.some(c=>c.type==='trace.unsubscribe' && c.session_id==='s')).toBe(true)
  expect(ctx.submits).toBe(1)
})

for(const width of [375,768,1440]) test(`宽度 ${width}：思考键盘、IME、上传移除不复活`,async({page})=>{
  await page.setViewportSize({width,height:900})
  const ctx=await setup(page)
  await page.getByRole('button',{name:/思考/}).click()
  const slider=page.getByRole('slider',{name:'思考强度'})
  await expect(slider).toBeVisible()
  const sliderBox = (await slider.boundingBox())!
  await page.mouse.click(sliderBox.x + sliderBox.width / 2, sliderBox.y + sliderBox.height / 2)
  await expect(slider).toHaveAttribute('aria-valuetext','中强度')
  await slider.dispatchEvent('wheel',{deltaY:100})
  await expect(slider).toHaveAttribute('aria-valuetext','高强度')
  await slider.focus();await slider.press('End')
  await expect(slider).toHaveAttribute('aria-valuetext','最高强度')
  await page.screenshot({path:`test-results/agentloop-slider-${width}.png`,fullPage:true,animations:'disabled'})
  await slider.press('Escape')
  await expect(page.getByRole('button',{name:/思考.*最高强度/})).toBeFocused()
  const input=page.getByRole('textbox',{name:'消息'})
  await input.fill('中文输入')
  await input.dispatchEvent('keydown',{key:'Enter',code:'Enter',isComposing:true})
  expect(ctx.submits).toBe(0)
  await page.locator('.loop-composer input[type=file]').setInputFiles({name:'draft.txt',mimeType:'text/plain',buffer:Buffer.from('hello')})
  await expect(page.getByRole('button',{name:'移除附件'})).toBeVisible()
  await page.getByRole('button',{name:'移除附件'}).click();ctx.release()
  await expect(page.locator('.draft-files .attachment-preview-card')).toHaveCount(0)
  await page.getByRole('button',{name:'发送',exact:true}).click()
  await expect.poll(()=>ctx.commands.find(command=>command.type==='turn.submit')?.data.reasoning_effort).toBe('max')
  expect(await page.evaluate(()=>document.documentElement.scrollWidth<=window.innerWidth)).toBe(true)
  await page.screenshot({path:`test-results/agentloop-${width}.png`,fullPage:true})
})
