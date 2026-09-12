import { reactive, markRaw } from 'vue'
import { AgentLoopWebSocket, type LoopTransportOptions } from '../../api/agentLoopWs.ts'
import type { LoopCommand } from '../../api/agentLoopTypes.ts'
import { createLoopState } from './reducer.ts'
import { applyTrace, createTrace } from './trace.ts'

/** 每会话独立草稿与冻结提交；object URL 仅在当前页面内存中存在。 */
export interface DraftFile { key: string; id?: string; filename: string; size: number; content_type?: string; source: string; uploading: boolean; progress: number; error?: string; removed: boolean }
export interface LoopDraft { content: string; files: DraftFile[]; pending?: LoopCommand; pendingInteraction?: string; cancelRequestId?: string; submitting: boolean }

/** transport 工厂：默认创建真实 WebSocket 客户端；测试注入 fake 以驱动帧结算逻辑。 */
export type LoopClientFactory = (id: string, options: LoopTransportOptions) => AgentLoopWebSocket

/** 页面拥有连接池；切换视图不销毁正在执行的会话。 */
export function createLoopStore(
  onRevoke: (id: string) => void,
  createClient: LoopClientFactory = (id, options) => new AgentLoopWebSocket(id, options),
) {
  const sessions = reactive<Record<string, ReturnType<typeof createLoopState>>>({})
  const traces = reactive<Record<string, ReturnType<typeof createTrace>>>({})
  const drafts = reactive<Record<string, LoopDraft>>({})
  const clients = new Map<string, AgentLoopWebSocket>()
  // 已关闭连接的最多十份恢复状态；草稿独立保存，淘汰后由 cursor=0 重建。
  const cached = new Set<string>()
  const restoring = reactive(new Set<string>())
  const idleSince = new Map<string, number>()
  const taskHints = new Map<string, string>()
  let focused = ''
  /** 清理授权正文和诊断；恢复必须从 cursor=0 重建。 */
  function remove(id: string) { clients.get(id)?.close(); clients.delete(id); cached.delete(id); restoring.delete(id); idleSince.delete(id); taskHints.delete(id); delete sessions[id]; delete traces[id]; for (const file of drafts[id]?.files || []) { file.removed = true; URL.revokeObjectURL(file.source) }; delete drafts[id] }
  function draft(id: string) { return drafts[id] ??= { content: '', files: [], submitting: false } }
  /** 只回收后台且已同步的空闲连接，活动 Worker 与未确认提交不能误判为结束。 */
  function releaseIdle(now = Date.now()) {
    for (const [id, client] of clients) {
      const state = sessions[id], pending = drafts[id], taskId = taskHints.get(id)
      const protectedSession = id === focused || !state.ready || !!state.activeTurn || state.cancelling
        || !!pending?.pending || !!pending?.submitting
        || Object.values(state.interactions).some(item => !item.resolved)
        || Object.values(state.tasks).some(item => item.event !== 'task.end')
        || !!taskId && state.tasks[taskId]?.event !== 'task.end'
        || Object.values(state.executions).some(item => item.event === 'execution.quarantined')
      if (protectedSession) { idleSince.delete(id); continue }
      const since = idleSince.get(id)
      if (since === undefined) { idleSince.set(id, now); continue }
      if (now - since < 60000) continue
      client.close(); clients.delete(id); idleSince.delete(id)
      state.ready = false; state.controlled = false; state.connection = 'offline'
      // 诊断正文不跨连接复用；对话缓存只有重新授权并回放完成后才能显示。
      traces[id] = createTrace()
      cached.add(id)
    }
    while (cached.size > 10) {
      const id = cached.values().next().value!
      cached.delete(id); delete sessions[id]; delete traces[id]; taskHints.delete(id)
    }
  }
  /** 切换即建立或复用连接；快速往返不触发关闭/重建。 */
  function focus(id: string, activeTaskId?: string) {
    focused = id
    if (activeTaskId) taskHints.set(id, activeTaskId)
    else taskHints.delete(id)
    if (id) open(id)
    releaseIdle()
  }
  function open(id: string, preparedTicket?: Promise<string>): AgentLoopWebSocket {
    if (clients.has(id)) return clients.get(id)!
    if (sessions[id]) { restoring.add(id); sessions[id].ready = false; sessions[id].controlled = false }
    sessions[id] ??= createLoopState(id); traces[id] ??= createTrace()
    cached.delete(id)
    // 新建会话时短票可与 REST 建会并行；首次失败后的重连仍重新领取一次性短票。
    let firstTicket = preparedTicket
    const client = markRaw(createClient(id, {
      ticket: async () => {
        const ticket = firstTicket
        firstTicket = undefined
        if (ticket) return await ticket
        // 延迟导入：store 模块保持无 HTTP 依赖，单测无需浏览器 mock。
        const { api } = await import('../../api/http.ts')
        return (await api.auth.getWsTicket()).ticket
      },
      state: () => sessions[id], replace: value => { sessions[id] = value },
      onFrame: frame => {
        // 按已通过 transport 去重的业务事件重新计时，避免漏掉两次清理之间完成的短回合。
        // 心跳、订阅控制帧和诊断帧不续期，空闲连接仍能按时回收。
        if (id !== focused && (frame.durability === 'persistent'
          || frame.durability === 'transient' && frame.type.startsWith('assistant.'))) idleSince.set(id, Date.now())
        if (frame.type === 'replay.completed') restoring.delete(id)
        applyTrace(traces[id], frame)
        if (frame.type === 'command.rejected' && frame.request_id === drafts[id]?.cancelRequestId) {
          sessions[id].cancelling = false
          sessions[id].error = frame.data.message || '取消命令未接受'
          delete drafts[id].cancelRequestId
        }
        const pending = drafts[id]?.pending
        // 持久交互终态同样证明请求已处理；回执迟到/丢失时不继续显示“结果待同步”。
        const settledInteraction = pending?.type.endsWith('.respond')
          && frame.type === pending.type.replace('.respond', '.resolved')
          && frame.data.interaction_id === pending.data.interaction_id
          && (['turn_id', 'attempt_id', 'call_id'] as const).every(key => frame.correlation[key] === pending.data[key])
        if (pending && (settledInteraction || frame.request_id === pending.request_id || frame.type === 'user.message' && frame.data.client_message_id === pending.data.client_message_id)) {
          const d = drafts[id]
          if (settledInteraction || frame.type === 'command.accepted' || frame.type === 'user.message') {
            // 受理后仅清除原冻结内容，用户在运行中编辑的下一轮草稿保留。
            if (pending.type === 'turn.submit') {
              if (d.content === pending.data.content) d.content = ''
              for (const file of d.files) if (pending.data.attachment_refs.includes(file.id)) { file.removed = true; URL.revokeObjectURL(file.source) }
              d.files = d.files.filter(file => !file.removed)
              if (frame.type === 'command.accepted' && sessions[id].activeTurn !== null) sessions[id].controlled = true
            }
            delete d.pending; delete d.pendingInteraction; d.submitting = false
          } else if (frame.type === 'command.rejected') {
            sessions[id].error = frame.data.message || '命令未接受'
            if (d.pendingInteraction) { const interaction = sessions[id].interactions[d.pendingInteraction]; if (interaction) interaction.submitting = false }
            delete d.pending; d.submitting = false
          }
        }
      },
      onRevoke: () => { queueMicrotask(() => { remove(id); onRevoke(id) }) },
    }))
    clients.set(id, client); void client.connect(); return client
  }
  /** 回执不明确时允许用户以原 ID 重发冻结命令，禁止替换正文。 */
  function send(id: string, command: LoopCommand) { return open(id).send(command) }
  function close() { focused = ''; for (const id of new Set([...clients.keys(), ...Object.keys(sessions), ...Object.keys(drafts)])) remove(id) }
  return { sessions, traces, drafts, draft, clients, restoring, focus, releaseIdle, open, send, remove, close }
}
export type LoopStore = ReturnType<typeof createLoopStore>
