import { reactive, markRaw } from 'vue'
import { AgentLoopWebSocket, type LoopTransportOptions } from '../../api/agentLoopWs.ts'
import type { LoopCommand, LoopUi } from '../../api/agentLoopTypes.ts'
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
  const capabilities = reactive<Record<string, LoopUi>>({})
  const drafts = reactive<Record<string, LoopDraft>>({})
  const clients = new Map<string, AgentLoopWebSocket>()
  /** 清理授权正文和诊断；恢复必须从 cursor=0 重建。 */
  function remove(id: string) { clients.get(id)?.close(); clients.delete(id); delete sessions[id]; delete traces[id]; delete capabilities[id]; for (const file of drafts[id]?.files || []) { file.removed = true; URL.revokeObjectURL(file.source) }; delete drafts[id] }
  function draft(id: string) { return drafts[id] ??= { content: '', files: [], submitting: false } }
  function open(id: string, preparedTicket?: Promise<string>): AgentLoopWebSocket {
    if (clients.has(id)) return clients.get(id)!
    sessions[id] = createLoopState(id); traces[id] = createTrace()
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
  function close() { for (const id of new Set([...clients.keys(), ...Object.keys(drafts)])) remove(id) }
  return { sessions, traces, capabilities, drafts, draft, clients, open, send, remove, close }
}
export type LoopStore = ReturnType<typeof createLoopStore>
