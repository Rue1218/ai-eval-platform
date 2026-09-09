import { test, expect, type Page } from '@playwright/test'

const deepseekProfile = { id:'p',name:'DeepSeek 协议档',version:'v1',model:'deepseek-chat',protocol:'openai_chat',allowed_efforts:['off','low','medium','high','max'],default_effort:'medium' }
const compatibleProfile = { id:'p2',name:'兼容协议档',version:'v2',model:'qwen-plus',protocol:'openai_chat',allowed_efforts:['off','low','high'],default_effort:'high' }
// 与服务器实际型号/协议相同的能力夹具，验证滑动值进入 WS；真实供应商另行验收。
const serverProfiles = [
  { id:'p3',name:'MaaS DeepSeek',version:'v3',model:'deepseek-v4-flash-0731',protocol:'anthropic_messages',allowed_efforts:['off','high','max'],default_effort:'off' },
  { id:'p4',name:'MaaS Qwen',version:'v3',model:'qwen3.6-flash',protocol:'anthropic_messages',allowed_efforts:['off','low','medium','high','xhigh','max'],default_effort:'off' },
  { id:'p5',name:'NIM StepFun',version:'v3',model:'stepfun-ai/step-3.7-flash',protocol:'openai_chat',allowed_efforts:['off'],default_effort:'off' },
]
const ui = { version:1,enabled:true,profile:deepseekProfile,profiles:[deepseekProfile,compatibleProfile,...serverProfiles],allowed_efforts:deepseekProfile.allowed_efforts,default_effort:deepseekProfile.default_effort,permissions:{write:true,trace:true,reasoning:true,interactions:true,settings:true},controller:{active:false,owned_by_actor:false},attachments:{upload_suffixes:['.txt'],inline_suffixes:['.txt'],image_suffixes:[],max_bytes:20971520,max_image_bytes:4194304,content_required:true} }

/** 真实页面与 WebSocket transport 使用协议夹具；不把夹具当供应商/沙箱闭环。 */
async function setup(page: Page, holdNewReplay = false) {
  // 契约回归使用系统字体，避免第三方字体 CDN 可达性影响页面就绪判定。
  await page.route('https://fonts.googleapis.com/**', route => route.fulfill({contentType:'text/css',body:''}))
  page.on('pageerror', error => console.log('页面异常：', error.message))
  page.on('console', message => { if (message.type() === 'error') console.log('浏览器错误：', message.text()) })
  const commands: any[] = [], sessionCreates: Record<string, unknown>[] = [], sockets = new Map<string, any>()
  let cursor=0, submit=0
  let releaseUpload: (()=>void) | undefined
  let releaseReplay: (()=>void) | undefined
  await page.route('**/api/**', async route => {
    const path=new URL(route.request().url()).pathname
    if (!path.startsWith('/api/')) { await route.continue(); return }
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
    const send=(type:string,data:any={},correlation:any={},persistent=false,sid='s')=>socket.send(JSON.stringify({protocol_version:2,type,durability:persistent?'persistent':'control',...(persistent?{cursor:++cursor}:{}),session_id:sid,ts:'2026-09-09T00:00:00Z',correlation,data}))
    socket.send(JSON.stringify({protocol_version:2,type:'hello',durability:'control',data:{protocol_version:2},correlation:{}}))
    socket.send(JSON.stringify({protocol_version:2,type:'capabilities',durability:'control',data:{stream_schema_version:'agent-loop-stream.v2.2'},correlation:{}}))
    socket.onMessage(raw=>{
      const cmd=JSON.parse(String(raw));commands.push(cmd);sockets.set(cmd.session_id,socket)
      const sid=cmd.session_id, c={turn:1,turn_id:`${sid}:1`,step:1,attempt_id:'a',call_id:'c'}
      if(cmd.type==='subscribe') {
        send('subscribed',{cursor:cmd.session_id==='s'?cursor:0},{},false,cmd.session_id)
        const replay=()=>send('replay.completed',{cursor:cmd.session_id==='s'?cursor:0},{},false,cmd.session_id)
        if(holdNewReplay && cmd.session_id==='s3') releaseReplay=replay
        else replay()
      }
      if(cmd.type==='turn.submit') {
        submit++
        send('user.message',{content:cmd.data.content,client_message_id:cmd.data.client_message_id},{turn:1,turn_id:`${sid}:1`},true,sid)
        send('turn.start',{},c,true,sid)
        socket.send(JSON.stringify({protocol_version:2,type:'command.accepted',durability:'control',session_id:sid,request_id:cmd.request_id,data:{accepted:true},correlation:c}))
        send('assistant.start',{request_summary:{model:'deepseek-chat',reasoning_effort:cmd.data.reasoning_effort,profile_version:'v1'}},c,true,sid)
        send('assistant.message',{content:'准备读取文件',reasoning_preview:'检查工作区',usage:{prompt_tokens:1500,completion_tokens:320,total_tokens:1820,cache_read_input_tokens:600},latency_ms:800},c,true,sid)
        send('assistant.end',{outcome:'committed'},c,true,sid)
        send('tool.call',{name:'read',display:{version:1,target:'test.txt',arguments_preview:'{"path":"test.txt"}'}},c,true,sid)
        send('approval.requested',{interaction_id:'i',nonce:'nonce-memory-only',expires_at:Date.now()/1000+300,name:'read'},c,true,sid)
      }
      if(cmd.type==='approval.respond') {
        send('approval.resolved',{interaction_id:'i',decision:cmd.data.decision},c,true,sid)
        send('tool.result',{name:'read',status:cmd.data.decision==='deny'?'denied':'succeeded',display:{version:1,result_preview:'实际输出夹具'}},c,true,sid)
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
  return {commands,sessionCreates,get submits(){return submit},get uploading(){return !!releaseUpload},release:()=>releaseUpload?.(),replay:()=>releaseReplay?.(),sockets}
}

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
  await page.getByRole('button', {name:'允许一次', exact:true}).click()
  await expect(page.locator('.tool-state').first()).toHaveText('已完成')
  await expect(page.getByRole('textbox', {name:'消息'})).toHaveValue('')
  await expect(page.getByText('草稿已保留', {exact:false})).toHaveCount(0)
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
    // 等待弹层缩放结束再取坐标；拖到轨道边缘，避免跨浏览器的滑块中心偏差。
    await slider.click({trial:true})
    const box = (await slider.boundingBox())!
    await page.mouse.move(box.x + 15, box.y + box.height / 2)
    await page.mouse.down()
    await page.mouse.move(box.x + box.width - 1, box.y + box.height / 2, {steps:8})
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
  await expect(page.getByLabel('复制回答')).toBeVisible()
  await expect(page.getByLabel('重新生成')).toBeDisabled()
  await expect(page.getByLabel('引用为参考记忆')).toBeVisible()
  await expect(page.locator('.assistant-metrics')).toContainText('1.8K token')
  await expect(page.locator('.assistant-metrics')).toContainText('800 ms')
  await expect(page.locator('.conversation-metrics')).toContainText('生成速度 400/s')
  await expect(page.locator('.conversation-metrics')).toContainText('缓存命中 40%')
  await expect(page.locator('.conversation-metrics')).toContainText('输入 1.5K · 输出 320')
  await page.getByLabel('引用为参考记忆').click()
  await expect(page.getByRole('textbox', {name:'消息'})).toHaveValue('[引用对话记忆]\n准备读取文件\n[/引用对话记忆]')
  await page.getByRole('button', {name:'允许一次', exact:true}).click()
  await expect(page.getByRole('button', {name:'重新生成'})).toBeEnabled()
  await page.getByRole('button', {name:'重新生成'}).click()
  await expect.poll(() => ctx.submits).toBe(2)
  expect(ctx.commands.filter(command => command.type === 'turn.submit')[1].data.content).toBe('读取测试文件')
})

test('多步工具内审批、attempt 结束不解锁发送、切会话不取消、轨迹可用',async({page})=>{
  const ctx=await setup(page)
  await page.getByRole('textbox',{name:'消息'}).fill('读取测试文件')
  await page.getByRole('button',{name:'发送'}).click()
  await expect(page.getByRole('button',{name:'允许一次',exact:true})).toBeVisible()
  await expect(page.getByRole('button',{name:'停止执行',exact:true})).toBeVisible()
  await page.locator('.session-title-text').filter({hasText:'另一个会话'}).click()
  await page.locator('.session-title-text').filter({hasText:'联调会话'}).click()
  expect(ctx.commands.some(c=>c.type==='unsubscribe')).toBe(false)
  await page.getByRole('button',{name:'允许一次',exact:true}).click()
  await expect(page.locator('.tool-state').first()).toHaveText('已完成')
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
  await expect(page.locator('.trace-row')).toHaveCount(2)
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
