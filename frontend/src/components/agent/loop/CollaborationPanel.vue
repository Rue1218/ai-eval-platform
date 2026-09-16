<template>
  <section v-if="current" class="collaboration-panel" aria-label="专家协作">
    <button class="collaboration-header" type="button" :aria-expanded="open" @click="open = !open">
      <span class="collaboration-title"><i :class="current.status"/>专家协作</span>
      <span class="collaboration-summary">第 {{ current.root_turn }} 轮 · {{ statusLabel(current.status) }} · {{ current.runs.length }} 位专家</span>
      <span class="collaboration-budget">调用 {{ current.budget.calls || 0 }}/{{ current.budget.max_calls || 80 }}</span>
      <span aria-hidden="true">{{ open ? '⌃' : '⌄' }}</span>
    </button>
    <div v-if="open" class="collaboration-body">
      <div class="collaboration-goal">
        <div><strong>协作目标</strong><p>{{ current.goal }}</p></div>
        <button v-if="canControl && current.status === 'running'" type="button" class="stop-all" :disabled="stopping === current.id" @click="cancelAll">停止全部</button>
      </div>
      <div v-if="current.runs.length" class="agent-runs">
        <article v-for="run in current.runs" :key="run.run_id" class="agent-run">
          <header>
            <div><strong>{{ run.expert.name }}</strong><span>{{ run.model || '默认模型' }}</span></div>
            <span class="run-status" :class="run.status">{{ statusLabel(run.status) }}</span>
          </header>
          <p class="run-goal">{{ run.goal }}</p>
          <p class="run-contract">交付：{{ run.output_contract }}</p>
          <footer>
            <button v-if="run.result_available" type="button" @click="toggleResult(run.run_id)">{{ expanded.has(run.run_id) ? '收起成果' : '查看成果' }}</button>
            <button v-if="canControl && ['queued','running'].includes(run.status)" type="button" class="stop-run" :disabled="stopping === run.run_id" @click="cancelRun(run.run_id)">停止</button>
          </footer>
          <div v-if="expanded.has(run.run_id)" class="run-result">
            <p v-if="run.result?.content">{{ run.result.content }}</p>
            <p v-else class="muted">{{ run.error_code ? `运行失败：${run.error_code}` : '没有可展示的成果正文。' }}</p>
          </div>
        </article>
      </div>
      <p v-else class="muted">协调器正在创建专家实例…</p>
      <p v-if="loadError" class="panel-error">{{ loadError }}</p>
    </div>
  </section>
</template>

<script setup lang="ts">
import { onBeforeUnmount, ref, watch } from 'vue'
import { api } from '../../../api/http'
import type { AgentCollaborationDetail, AgentCollaborationStatus, AgentRunStatus } from '../../../api/types'

const props = defineProps<{ sessionId: string; canControl: boolean }>()
const current = ref<AgentCollaborationDetail | null>(null)
const open = ref(true)
const stopping = ref('')
const loadError = ref('')
const expanded = ref(new Set<string>())
let timer: ReturnType<typeof setTimeout> | null = null
let generation = 0

// 将持久运行状态转换为界面文案。
function statusLabel(status: AgentCollaborationStatus | AgentRunStatus): string {
  return { queued: '排队中', running: '执行中', succeeded: '已完成', failed: '失败', cancelled: '已停止' }[status]
}

// 后台页跳过请求但保留下一次调度，返回页面后自动恢复刷新。
function schedule(active: boolean) {
  if (timer) clearTimeout(timer)
  timer = setTimeout(() => {
    if (document.visibilityState === 'visible') void load()
    else schedule(active)
  }, active ? 1500 : 8000)
}

// 会话切换或重新加载后丢弃旧请求结果，避免跨会话显示专家成果。
async function load() {
  const token = ++generation
  if (!props.sessionId) { current.value = null; return }
  try {
    const list = await api.collaborations.list(props.sessionId)
    if (token !== generation) return
    const latest = list[0]
    const detail = latest ? await api.collaborations.get(latest.id) : null
    if (token !== generation) return
    current.value = detail
    loadError.value = ''
  } catch (error: any) {
    if (token === generation) loadError.value = error?.message || '专家协作状态读取失败'
  } finally {
    if (token === generation) schedule(current.value?.status === 'running')
  }
}

// 停止整组后重新读取服务端事实状态。
async function cancelAll() {
  if (!current.value || stopping.value) return
  stopping.value = current.value.id
  try { await api.collaborations.cancel(current.value.id); await load() }
  catch (error: any) { loadError.value = error?.message || '停止专家协作失败' }
  finally { stopping.value = '' }
}

// 停止单个专家，其余专家仍按原计划运行。
async function cancelRun(runId: string) {
  if (stopping.value) return
  stopping.value = runId
  try { await api.collaborations.cancelRun(runId); await load() }
  catch (error: any) { loadError.value = error?.message || '停止专家失败' }
  finally { stopping.value = '' }
}

// 独立展开每位专家的成果。
function toggleResult(runId: string) {
  const next = new Set(expanded.value)
  next.has(runId) ? next.delete(runId) : next.add(runId)
  expanded.value = next
}

watch(() => props.sessionId, () => {
  generation++
  if (timer) clearTimeout(timer)
  current.value = null
  expanded.value = new Set()
  loadError.value = ''
  void load()
}, { immediate: true })
onBeforeUnmount(() => { generation++; if (timer) clearTimeout(timer) })
</script>

<style scoped>
.collaboration-panel{margin:10px 18px 0;border:1px solid #dbe6de;border-radius:12px;background:#fbfdfb;overflow:hidden}.collaboration-header{width:100%;display:flex;align-items:center;gap:12px;padding:11px 14px;border:0;background:#f4f8f5;color:#294438;cursor:pointer;text-align:left}.collaboration-title{display:flex;align-items:center;gap:7px;font-weight:650}.collaboration-title i{width:8px;height:8px;border-radius:50%;background:#90a49a}.collaboration-title i.running{background:#20a47b;animation:collab-pulse 1.5s ease-in-out infinite}.collaboration-title i.failed{background:#d66b5f}.collaboration-title i.cancelled{background:#99a29c}.collaboration-title i.succeeded{background:#3c8b67}.collaboration-summary{font-size:12px;color:#6d8075;flex:1}.collaboration-budget{font-size:11px;color:#61776a}.collaboration-body{padding:13px}.collaboration-goal{display:flex;gap:16px;align-items:flex-start;margin-bottom:10px}.collaboration-goal>div{flex:1;min-width:0}.collaboration-goal strong{font-size:12px}.collaboration-goal p{margin:5px 0;color:#52665b;font-size:12px;white-space:pre-wrap}.stop-all,.stop-run{color:#a34f46!important}.agent-runs{display:grid;grid-template-columns:repeat(auto-fit,minmax(240px,1fr));gap:9px}.agent-run{border:1px solid #e1e9e3;border-radius:9px;background:#fff;padding:11px;min-width:0}.agent-run header{display:flex;justify-content:space-between;gap:8px}.agent-run header div{display:flex;flex-direction:column;min-width:0}.agent-run header span{font-size:11px;color:#7a8b80;overflow:hidden;text-overflow:ellipsis}.run-status{padding:2px 7px;border-radius:10px;background:#eef3ef;height:fit-content}.run-status.running{color:#147456;background:#e4f4ed}.run-status.failed{color:#a2473e;background:#faecea}.run-goal{font-size:12px;line-height:1.5;margin:8px 0;display:-webkit-box;-webkit-line-clamp:3;-webkit-box-orient:vertical;overflow:hidden}.run-contract{font-size:11px;color:#718278}.agent-run footer{display:flex;gap:10px}.agent-run button,.stop-all{border:0;background:transparent;text-decoration:underline;cursor:pointer;font-size:12px}.agent-run button:disabled,.stop-all:disabled{opacity:.5;cursor:not-allowed}.run-result{margin-top:9px;padding:9px;border-radius:7px;background:#f5f8f5;font-size:12px;line-height:1.55;white-space:pre-wrap;max-height:240px;overflow:auto}.run-result p{margin:0}.muted{color:#819087;font-size:12px}.panel-error{color:#a24d43;font-size:12px;margin:9px 0 0}@keyframes collab-pulse{50%{opacity:.35}}@media(prefers-reduced-motion:reduce){.collaboration-title i{animation:none!important}}@media(max-width:768px){.collaboration-panel{margin:8px}.collaboration-header{flex-wrap:wrap}.collaboration-summary{order:3;flex-basis:100%}}
</style>
