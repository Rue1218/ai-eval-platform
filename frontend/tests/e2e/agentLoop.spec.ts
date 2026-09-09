import { test, expect, type Page } from '@playwright/test'

const deepseekProfile = { id:'p',name:'DeepSeek 协议档',version:'v1',model:'deepseek-chat',protocol:'openai_chat',allowed_efforts:['off','low','medium','high','max'],default_effort:'medium' }
const compatibleProfile = { id:'p2',name:'兼容协议档',version:'v2',model:'qwen-plus',protocol:'openai_chat',allowed_efforts:['off','low','high'],default_effort:'high' }
const ui = { version:1,enabled:true,profile:deepseekProfile,profiles:[deepseekProfile,compatibleProfile],allowed_efforts:deepseekProfile.allowed_efforts,default_effort:deepseekProfile.default_effort,permissions:{write:true,trace:true,reasoning:true,interactions:true,settings:true},controller:{active:false,owned_by_actor:false},attachments:{upload_suffixes:['.txt'],inline_suffixes:['.txt'],image_suffixes:[],max_bytes:20971520,max_image_bytes:4194304,content_required:true} }

/** 真实页面与 WebSocket transport 使用协议夹具；不把夹具当供应商/沙箱闭环。 */
async function setup(page: Page) {
  // 契约回归使用系统字体，避免第三方字体 CDN 可达性影响页面就绪判定。
  await page.route('https://fonts.googleapis.com/**', route => route.fulfill({contentType:'text/css',body:''}))
  page.on('pageerror', error => console.log('页面异常：', error.message))
  page.on('console', message => { if (message.type() === 'error') console.log('浏览器错误：', message.text()) })
  const commands: any[] = [], sessionCreates: Record<string, unknown>[] = [], sockets = new Map<string, any>()
  let cursor=0, submit=0
  let releaseUpload: (()=>void) | undefined
  await page.route('**/api/**', async route => {
    const path=new URL(route.request().url()).pathname
    if (!path.startsWith('/api/')) { await route.continue(); return }
    let body: any={}
    if(path==='/api/auth/me') body={id:'u',username:'tester',role:'admin',must_change_password:false}
    else if(path==='/api/auth/ws-ticket') body={ticket:'ticket',expires_in:300}
    else if(path==='/api/sessions' && route.request().method()==='GET') body=[{id:'s',title:'联调会话',owner_id:'u',visibility:'private',can_manage:true,can_delete:true,engine_version:'agent_loop_v2',created_at:'2026-09-09T00:00:00Z'},{id:'s2',title:'另一个会话',owner_id:'u',visibility:'private',can_manage:true,can_delete:true,engine_version:'agent_loop_v2',created_at:'2026-09-09T00:00:00Z'},{id:'legacy',title:'历史旧会话',owner_id:'u',visibility:'private',can_manage:true,can_delete:true,engine_version:'legacy',created_at:'2026-09-09T00:00:00Z'}]
    else if(path==='/api/sessions' && route.request().method()==='POST') { const payload=route.request().postDataJSON() as Record<string, unknown>;sessionCreates.push(payload);body={id:'s3',title:payload.title || '新会话',owner_id:'u',visibility:'private',can_manage:true,can_delete:true,engine_version:'agent_loop_v2',created_at:'2026-09-09T00:00:00Z'} }
    else if(path.endsWith('/agent-ui')) body=ui
    else if(path==='/api/profiles') body=[{id:'p',name:'测试模型',model:'deepseek-chat',usages:['agent'],protocol:'openai_chat'}]
    else if(path==='/api/admin/settings') body={agent_profile_id:'p'}
    else if(['/api/datasets','/api/kb','/api/tasks'].includes(path)) body=[]
    else if(path==='/api/files' && route.request().method()==='POST') { await new Promise<void>(resolve=>{releaseUpload=resolve});body={id:'f',filename:'draft.txt',size:5,content_type:'text/plain'} }
    await route.fulfill({json:body})
  })
  await page.routeWebSocket('**/ws/agent/v2?*', socket => {
    const send=(type:string,data:any={},correlation:any={},persistent=false,sid='s')=>socket.send(JSON.stringify({protocol_version:2,type,durability:persistent?'persistent':'control',...(persistent?{cursor:++cursor}:{}),session_id:sid,ts:'2026-09-09T00:00:00Z',correlation,data}))
    socket.send(JSON.stringify({protocol_version:2,type:'hello',durability:'control',data:{protocol_version:2},correlation:{}}))
    socket.send(JSON.stringify({protocol_version:2,type:'capabilities',durability:'control',data:{stream_schema_version:'agent-loop-stream.v2.1'},correlation:{}}))
    socket.onMessage(raw=>{
      const cmd=JSON.parse(String(raw));commands.push(cmd);sockets.set(cmd.session_id,socket)
      const sid=cmd.session_id, c={turn:1,turn_id:`${sid}:1`,step:1,attempt_id:'a',call_id:'c'}
      if(cmd.type==='subscribe') { send('subscribed',{cursor:cmd.session_id==='s'?cursor:0},{},false,cmd.session_id);send('replay.completed',{cursor:cmd.session_id==='s'?cursor:0},{},false,cmd.session_id) }
      if(cmd.type==='turn.submit') {
        submit++
        send('user.message',{content:cmd.data.content,client_message_id:cmd.data.client_message_id},{turn:1,turn_id:`${sid}:1`},true,sid)
        send('turn.start',{},c,true,sid)
        socket.send(JSON.stringify({protocol_version:2,type:'command.accepted',durability:'control',session_id:sid,request_id:cmd.request_id,data:{accepted:true},correlation:c}))
        send('assistant.start',{request_summary:{model:'deepseek-chat',reasoning_effort:cmd.data.reasoning_effort,profile_version:'v1'}},c,true,sid)
        send('assistant.message',{content:'准备读取文件',reasoning_preview:'检查工作区'},c,true,sid)
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
  await expect(page.locator('.loop-status')).toContainText('就绪')
  return {commands,sessionCreates,get submits(){return submit},release:()=>releaseUpload?.(),sockets}
}

test('新建会话固定采用 AgentLoop transport',async({page})=>{
  const ctx=await setup(page)
  await page.getByRole('button',{name:/新建会话/}).click()
  await page.getByRole('textbox',{name:'消息'}).fill('创建 AgentLoop 会话')
  await page.getByRole('button',{name:'发送'}).click()
  await expect.poll(()=>ctx.sessionCreates.length).toBe(1)
  expect(ctx.sessionCreates[0].engine_version).toBe('agent_loop_v2')
  await expect.poll(()=>ctx.commands.some(command=>command.type==='subscribe' && command.session_id==='s3')).toBe(true)
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
  await page.getByRole('textbox',{name:'搜索轨迹'}).fill('')
  await page.locator('.trace-filters').getByRole('button',{name:'模型',exact:true}).click()
  await expect(page.locator('.trace-row')).toHaveCount(1)
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
