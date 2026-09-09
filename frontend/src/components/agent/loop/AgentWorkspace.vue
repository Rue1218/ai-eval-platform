<template>
  <div class="loop-workspace">
    <div class="loop-tabs"><button :class="{active:tab==='chat'}" @click="tab='chat'">对话</button><button :class="{active:tab==='trace'}" :disabled="!state" @click="tab='trace'">轨迹 <small>{{ state?.cursor || '' }}</small></button><span class="loop-status"><i :class="{running:busy}"/>{{ status }}</span><button @click="runtimeOpen=!runtimeOpen">运行信息</button></div>
    <p v-if="state && state.connection !== 'online'" class="loop-notice" role="status">{{ state.connection === 'connecting' ? '正在同步会话…' : '连接中断，状态待同步。' }}<button @click="store.clients.get(sessionId)?.connect()">重新连接</button></p>
    <p v-if="state?.error || error" class="loop-notice error" role="alert">{{ state?.error || error }}</p>
    <p v-if="!sessionId && ui && !ui.enabled" class="loop-notice">服务器尚未开启 AgentLoop 新会话灰度，已有 v2 会话仍可阅读。</p>
    <div class="loop-content">
      <div class="loop-center">
        <div v-if="tab==='chat'" ref="scroller" class="loop-conversation" @scroll="trackScroll">
          <div v-if="!rows.length" class="loop-welcome"><span>AI EVAL · AGENT LOOP</span><h2>从一个目标开始，<br>让每一步都有依据。</h2><p>在工作区处理文件、查找资料，或创建评测任务。</p><div><button v-for="prompt in prompts" :key="prompt" @click="fill(prompt)">{{ prompt }} ↗</button></div></div>
          <button v-if="shown < rows.length" class="history-more" @click="shown+=80">显示更早的 {{ Math.min(80, rows.length-shown) }} 条记录</button>
          <template v-for="row in visibleRows" :key="row.key">
            <article v-if="row.role==='user'" class="loop-message user"><header>你</header><div class="history-files"><AttachmentPreview v-for="file in attachments[row.key] || []" :key="file.file_id" :attachment="file"/></div><p>{{ row.content }}</p></article>
            <ToolRunCard v-else-if="'status' in row && 'name' in row" :tool="row as ToolRun" :interactions="interactions(row)" :can-control="canControl" :online="!!state?.ready" @respond="respond"/>
            <article v-else class="loop-message assistant"><header><ProviderLogo v-if="row.request_summary?.model" :provider="getProviderLogoKey({model:row.request_summary.model})" :size="18"/>{{ row.request_summary?.model || '助手' }}<small v-if="row.request_summary">{{ row.request_summary.reasoning_effort }} · step {{ row.correlation.step }}</small><button v-if="row.text" @click="copy(row.text)">复制</button></header><ReasoningBlock v-if="row.reasoning && ui?.permissions.reasoning" :content="row.reasoning" :ended="row.ended" :interrupted="row.interrupted"/><MarkdownView v-if="row.text" :content="row.text"/><p v-else-if="!row.ended" class="muted">正在响应…</p><small v-if="row.interrupted || row.error_code">{{ row.interrupted ? '本次输出已中断' : row.error_code }}</small></article>
          </template>
          <p v-if="!busy && state?.phase && ['max_tokens','max_steps','cancelled','interrupted','error'].includes(state.phase)" class="loop-notice">{{ finishLabels[state.phase] }}</p>
        </div>
        <TraceWorkspace v-else-if="state && trace" :state="state" :trace="trace"/>
        <button v-if="!atBottom && tab==='chat'" class="jump-bottom" @click="scrollBottom">↓ 回到最新</button>
      </div>
      <aside v-if="runtimeOpen" class="loop-runtime"><button class="runtime-close" @click="runtimeOpen=false">关闭</button><h3>当前运行</h3><p>{{ status }}</p><dl><dt>会话</dt><dd>{{ sessionId || '未发送的草稿' }}</dd><dt>实际模型</dt><dd>{{ summary?.model || '尚无实际请求' }}</dd><dt>思考档位</dt><dd>{{ summary?.reasoning_effort || '未知' }}</dd><dt>协议档版本</dt><dd>{{ summary?.profile_version || '未知' }}</dd><dt>最近活动</dt><dd v-for="event in state?.facts.slice(-5) || []" :key="event.cursor">{{ event.type }}</dd></dl><h4 v-if="tasks.length">Worker 任务</h4><div v-for="task in tasks" :key="task.key"><router-link :to="'/tasks'">{{ task.key }}</router-link><p>{{ task.status || '等待状态' }}</p><p v-if="task.progress">{{ JSON.stringify(task.progress) }}</p><router-link v-if="task.report_id" :to="`/reports/${task.report_id}`">查看报告</router-link></div><p v-for="execution in quarantined" :key="execution.key" class="loop-notice">执行范围受限 · {{ execution.reason || '等待对账' }}</p></aside>
    </div>
    <div class="loop-composer-wrap"><AgentComposer ref="composer" :draft="draft" :ui="ui" :effort="effort" :profiles="profiles" :meter="summary?.context_meter" :busy="busy" :cancelling="!!state?.cancelling" :can-stop="canControl && !!state?.ready && !state?.cancelling" :ready="ready" @effort="setEffort" @submit="submit" @stop="stop" @retry="retry" @model="changeModel"/></div>
  </div>
</template>
<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, ref, watch } from 'vue'
import http, { api } from '../../../api/http'
import type { AttachmentReference, Profile } from '../../../api/types'
import type { Data, Effort, InteractionRecord, LoopRecord, LoopUi, ToolRun } from '../../../api/agentLoopTypes'
import { conversationRows, identity } from '../../../agent/loop/reducer'
import type { LoopStore } from '../../../agent/loop/store'
import { useAuthStore } from '../../../stores/auth'
import { getProviderLogoKey } from '../../../utils/providerLogo'
import ProviderLogo from '../../ProviderLogo.vue'
import MarkdownView from '../MarkdownView.vue'
import AttachmentPreview from '../AttachmentPreview.vue'
import AgentComposer from './AgentComposer.vue'
import ToolRunCard from './ToolRunCard.vue'
import ReasoningBlock from './ReasoningBlock.vue'
import TraceWorkspace from './TraceWorkspace.vue'
const props = defineProps<{ sessionId: string; store: LoopStore; createSession: () => Promise<string> }>()
const auth = useAuthStore(), tab = ref('chat'), runtimeOpen = ref(false), error = ref(''), effort = ref<Effort | null>(null)
const ui = ref<LoopUi | null>(null), profiles = ref<Profile[]>([]), shown = ref(80), attachments = ref<Record<string, AttachmentReference[]>>({})
const composer = ref<InstanceType<typeof AgentComposer>>(), scroller = ref<HTMLElement>(), atBottom = ref(true)
const state = computed(() => props.store.sessions[props.sessionId]), trace = computed(() => props.store.traces[props.sessionId])
const draft = computed(() => props.store.draft(props.sessionId || 'draft'))
const rows = computed(() => state.value ? conversationRows(state.value) : [])
const visibleRows = computed(() => rows.value.slice(-shown.value))
const busy = computed(() => !!state.value?.activeTurn)
const ready = computed(() => !!ui.value?.profile && !!effort.value && (props.sessionId ? !!state.value?.ready : !!ui.value?.enabled))
const canControl = computed(() => !!state.value?.controlled && !!ui.value?.permissions.interactions)
const summary = computed(() => Object.values(state.value?.attempts || {}).sort((a,b)=>b.first_cursor-a.first_cursor)[0]?.request_summary)
const tasks = computed(() => Object.values(state.value?.tasks || {}))
const quarantined = computed(() => Object.values(state.value?.executions || {}).filter(e => e.event === 'execution.quarantined'))
const finishLabels: Record<string,string> = { max_tokens:'达到输出上限，本轮已结束', max_steps:'达到步骤上限，本轮已结束', cancelled:'本轮已取消', interrupted:'本轮已中断', error:'本轮失败，请查看错误信息' }
const phaseLabels: Record<string,string> = { idle:'就绪',model:'模型处理中',thinking:'正在思考',answering:'正在回答',tools:'工具执行中',waiting_interaction:'等待交互',retry_wait:'等待重试',completed:'已完成',...finishLabels }
const status = computed(() => state.value?.cancelling ? '取消中' : state.value && state.value.connection !== 'online' ? '连接待同步' : phaseLabels[state.value?.phase || 'idle'] || state.value?.phase || '就绪')
const prompts = ['查看工作区文件，说明可以如何处理', '帮我准备一次模型基准评测', '查询资料并给出可核对的来源']
let epoch = 0
/** 能力随会话/窗口聚焦刷新；活动请求显示自己的持久配置版本。 */
async function refreshUi() {
  const current = ++epoch, sid = props.sessionId
  try {
    const { data } = await http.get<LoopUi>(sid ? `/api/sessions/${sid}/agent-ui` : '/api/sessions/agent-ui')
    if (current !== epoch) return
    ui.value = data
    const key = preferenceKey(data)
    let saved: string | null = null
    try { saved = localStorage.getItem(key) } catch { /* 隐私模式下保留内存偏好。 */ }
    const previous = saved || effort.value
    effort.value = previous && data.allowed_efforts.includes(previous as Effort) ? previous as Effort : data.default_effort
    if (previous && previous !== effort.value) error.value = '当前模型不支持原思考档位，已恢复服务端默认值'
    if (!data.permissions.reasoning && state.value) { for (const a of Object.values(state.value.attempts)) { a.reasoning = ''; delete a.reasoning_preview }; for (const event of state.value.facts) delete event.data.reasoning_preview }
    if (!data.permissions.trace && trace.value) { trace.value.events = []; trace.value.seen.clear(); trace.value.catalog = null; trace.value.denied = true }
    if (!data.permissions.interactions && state.value) for (const i of Object.values(state.value.interactions)) { delete i.nonce; delete i.spec_hash; i.restricted = true }
    if (data.permissions.settings) profiles.value = (await api.profiles.list()).filter(p => p.usages?.includes('agent'))
  } catch { if (current === epoch) { ui.value = null; error.value = '读取会话能力失败，请确认权限和服务状态' } }
}
function preferenceKey(value: LoopUi) { return `agent-effort:${auth.user?.id}:${value.profile?.id}:${value.profile?.version}` }
function setEffort(value: Effort) { effort.value = value; if (ui.value) try { localStorage.setItem(preferenceKey(ui.value), value) } catch { /* 本地存储不可用不影响发送。 */ } }
watch(() => props.sessionId, () => { ui.value = null; attachments.value = {}; shown.value = 80; tab.value='chat'; if (props.sessionId) props.store.open(props.sessionId); void refreshUi() }, { immediate: true })
watch(tab, value => { if (props.sessionId) { props.store.clients.get(props.sessionId)?.trace(value === 'trace', trace.value?.seq ?? -1); if (trace.value) trace.value.denied = !ui.value?.permissions.trace } })
watch(() => state.value?.cursor, () => { if (atBottom.value) void nextTick(scrollBottom); void hydrateAttachments() })
const refreshTimer = setInterval(() => { if (document.visibilityState === 'visible') void refreshUi() }, 30000)
window.addEventListener('focus', refreshUi)
onBeforeUnmount(() => { epoch++; clearInterval(refreshTimer); window.removeEventListener('focus', refreshUi) })
function interactions(row: LoopRecord) { return Object.values(state.value?.interactions || {}).filter(i => identity({session_id:props.sessionId,correlation:i.correlation},true) === row.key) }
function fill(text: string) { draft.value.content = text; composer.value?.focus() }
function trackScroll() { const el=scroller.value; if(el) atBottom.value=el.scrollHeight-el.scrollTop-el.clientHeight<100 }
function scrollBottom() { const el=scroller.value; if(el) el.scrollTop=el.scrollHeight; atBottom.value=true }
async function copy(text: string) { try { await navigator.clipboard.writeText(text) } catch { error.value='复制失败' } }
/** 冻结输入/附件/effort 与幂等 ID；未受理时保留可恢复草稿。 */
async function submit() {
  if (!ready.value || busy.value || draft.value.submitting) return
  const source = draft.value, selectedEffort=effort.value
  source.submitting = true
  const content=source.content, refs=source.files.filter(f=>!f.removed && f.id).map(f=>f.id!)
  try {
    let sid=props.sessionId
    if(!sid) { sid=await props.createSession(); if(!sid) throw new Error(); props.store.drafts[sid]=source; delete props.store.drafts.draft }
    const client=props.store.open(sid)
    source.pending=client.command('turn.submit',{client_message_id:crypto.randomUUID(),content,attachment_refs:refs,reasoning_effort:selectedEffort})
    // 新建会话首次订阅完成后才发；原请求不自动跨断线重试。
    if(props.store.sessions[sid].ready) { client.send(source.pending); props.store.sessions[sid].controlled=true }
    else { const unwatch=watch(()=>props.store.sessions[sid]?.ready, ok=>{ if(ok){unwatch();if(source.pending){client.send(source.pending);props.store.sessions[sid].controlled=true}} }); setTimeout(unwatch,15000) }
  } catch { source.submitting=false; error.value='无法创建或发送会话，草稿已保留' }
}
function retry() { if(draft.value.pending && state.value?.ready) props.store.send(props.sessionId,draft.value.pending) }
function stop() { if(!canControl.value || !state.value?.activeTurn) return; const client=props.store.clients.get(props.sessionId)!; const command=client.command('turn.cancel',{turn_id:state.value.activeTurn}); if(client.send(command)) { state.value.cancelling=true; draft.value.cancelRequestId=command.request_id } }
function respond(interaction: InteractionRecord, values: Data) {
  if(!canControl.value || !state.value?.ready || interaction.submitting) return
  const c=interaction.correlation
  const data={interaction_id:interaction.interaction_id,turn_id:c.turn_id,turn:c.turn,attempt_id:c.attempt_id,call_id:c.call_id,nonce:interaction.nonce,...values,...(interaction.kind==='task_confirmation'?{spec_hash:interaction.spec_hash}:{})}
  const client=props.store.clients.get(props.sessionId)!, command=client.command(`${interaction.kind}.respond`,data)
  if(client.send(command)){interaction.submitting=true;draft.value.pending=command;draft.value.pendingInteraction=interaction.key}
}
async function changeModel(id:string) { try{await api.admin.updateSettings({agent_profile_id:id});await refreshUi()}catch{error.value='切换模型失败，仍使用服务端当前配置'} }
/** 文件元数据只取授权接口，不信任历史里的任意 URL。 */
async function hydrateAttachments() {
  const sid=props.sessionId
  for(const row of rows.value.filter(r=>r.role==='user' && r.attachment_refs?.length)){
    if(attachments.value[row.key])continue
    attachments.value[row.key]=[]
    const values=await Promise.all((row.attachment_refs as any[]).map(async item=>{const id=typeof item==='string'?item:item.file_id;try{const {data}=await http.get(`/api/files/${encodeURIComponent(id)}`);return {file_id:id,filename:data.filename,size:data.size,content_type:data.content_type,content_url:`/api/files/${encodeURIComponent(id)}/content`} as AttachmentReference}catch{return null}}))
    if(sid===props.sessionId)attachments.value[row.key]=values.filter((v):v is AttachmentReference=>v!==null)
  }
}
</script>
<style>
.loop-control{background:transparent;color:inherit;border:1px solid transparent;border-radius:7px;padding:7px 9px;font-size:12px;cursor:pointer}.loop-control:hover{background:#eaf3ee}.loop-primary{background:#174a3a!important;color:#fff!important}.loop-workspace button:focus-visible,.loop-workspace input:focus-visible,.loop-workspace summary:focus-visible{outline:2px solid #16977a;outline-offset:2px}
</style>
<style scoped>
.loop-workspace{display:flex;flex:1;flex-direction:column;min-height:0;min-width:0;background:var(--bg-main,#f8faf8)}.loop-tabs{display:flex;align-items:center;gap:8px;padding:8px 20px;border-bottom:1px solid #e0e8e2}.loop-tabs button{padding:7px 12px;border:0;border-radius:7px;background:transparent;color:#61776a;cursor:pointer}.loop-tabs .active{background:#e2eee6;color:#154834}.loop-status{margin-left:auto;font-size:12px;display:flex;align-items:center;gap:6px}.loop-status i{width:7px;height:7px;border-radius:50%;background:#93a99c}.loop-status .running{background:#21a37e;animation:pulse 1.5s ease-in-out infinite}.loop-content{display:flex;flex:1;min-height:0;position:relative}.loop-center{display:flex;flex-direction:column;flex:1;min-width:0;position:relative;min-height:0}.loop-conversation{overflow:auto;flex:1;padding:24px max(20px,calc((100% - 800px)/2));scrollbar-gutter:stable}.loop-message{margin:0 0 22px;min-width:0;overflow-wrap:anywhere}.loop-message header{display:flex;gap:8px;align-items:center;font-size:13px;font-weight:600;margin-bottom:8px}.loop-message header small{font-weight:400;color:#7b8e82}.loop-message header button{margin-left:auto;border:0;background:transparent;color:#728777;cursor:pointer}.loop-message.user{background:#eaf3ed;padding:16px 20px;border-radius:12px}.loop-message.user p{white-space:pre-wrap;margin:0;line-height:1.7}.history-files{display:flex;gap:8px;flex-wrap:wrap}.loop-welcome{max-width:750px;margin:6vh auto 24px}.loop-welcome>span{letter-spacing:.16em;color:#5c8c75;font-size:11px}.loop-welcome h2{font-size:32px;line-height:1.4;font-weight:600;color:#173f30;margin:16px 0}.loop-welcome p{color:#7d8b82}.loop-welcome>div{display:flex;gap:10px;margin-top:25px}.loop-welcome button{flex:1;text-align:left;border:1px solid #d8e4dc;border-radius:10px;padding:18px;background:#fff;color:#4d6858;line-height:1.7;cursor:pointer}.loop-composer-wrap{padding:12px 24px 18px;max-width:950px;width:100%;box-sizing:border-box;margin:0 auto}.loop-runtime{width:240px;overflow:auto;padding:18px;border-left:1px solid #e0e8e2;font-size:12px;background:#f5f8f5}.loop-runtime dd{margin:5px 0 14px;overflow-wrap:anywhere}.loop-runtime dt{color:#7d9081}.runtime-close{float:right;border:0;background:transparent;cursor:pointer}.loop-notice{padding:8px 16px;margin:4px 10px;background:#f6f0e2;color:#866934;font-size:12px}.loop-notice.error{color:#a24d43}.loop-notice button,.history-more{border:0;background:transparent;text-decoration:underline;cursor:pointer}.jump-bottom{position:absolute;bottom:10px;right:20px;border:1px solid #caddcf;background:#fff;border-radius:20px;padding:8px 15px;cursor:pointer}.muted{color:#86968b}@keyframes pulse{50%{opacity:.35}}@media(prefers-reduced-motion:reduce){*{animation:none!important;transition:none!important}}@media(max-width:768px){.loop-runtime{position:absolute;inset:0 0 0 auto;max-width:calc(100% - 35px);z-index:30;box-shadow:-20px 0 50px #173e2520}.loop-composer-wrap{padding:8px}.loop-conversation{padding:16px 12px}.loop-welcome h2{font-size:25px}.loop-welcome>div{flex-direction:column}.loop-welcome button{padding:12px}.loop-tabs{padding:6px;gap:0}.loop-tabs button{padding:7px}.loop-status{font-size:11px}.loop-message header{flex-wrap:wrap}}
</style>
