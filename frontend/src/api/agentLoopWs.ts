import type { LoopCommand, LoopFrame } from './agentLoopTypes.ts'
import { applyFrame, restoreSnapshot, type LoopState } from '../agent/loop/reducer.ts'
import { createRequestId } from '../utils/requestId.ts'

/** 可注入短票与 socket 的独立 transport，测试不依赖浏览器或 legacy HTTP mock。 */
export interface LoopTransportOptions {
  ticket: () => Promise<string>; state: () => LoopState; replace: (state: LoopState) => void
  socket?: (url: string) => WebSocket; onFrame?: (frame: LoopFrame) => void; onRevoke?: () => void
}
export class AgentLoopWebSocket {
  private ws: WebSocket | null = null
  private timer?: ReturnType<typeof setTimeout>
  private heartbeat?: ReturnType<typeof setInterval>
  private stopped = false
  private epoch = 0
  private retries = 0
  private syncing = false
  private seenAt = 0
  private traceEnabled = false
  private traceSeq = -1
  private traceRequestId: string | null = null
  constructor(private sessionId: string, private options: LoopTransportOptions) {}
  /** 幂等请求由调用者保存；重连不会自动换 ID 或提交草稿。 */
  send(command: LoopCommand): boolean {
    if (!this.ws || this.ws.readyState !== 1) return false
    if (!this.options.state().ready && !['subscribe', 'ping'].includes(command.type)) return false
    try { this.ws.send(JSON.stringify(command)); return true }
    catch {
      // OPEN 检查与写入间也可能断线；交给连接恢复并保留调用方的冻结请求。
      this.options.state().ready = false
      this.options.state().connection = 'reconnecting'
      this.ws.close(); this.schedule(); return false
    }
  }
  command(type: string, data: Record<string, unknown> = {}): LoopCommand {
    return { protocol_version: 2, type, session_id: this.sessionId, request_id: createRequestId(), data }
  }
  /** 同连接重新订阅保留控制权，不发送会触发 detach 的 unsubscribe。 */
  resync(): void {
    if (this.syncing) return
    this.syncing = true; this.options.state().ready = false
    this.send(this.command('subscribe', { after_cursor: this.options.state().cursor }))
  }
  trace(enabled: boolean, afterSeq = -1): void {
    this.traceEnabled = enabled; this.traceSeq = afterSeq
    const command = this.command(enabled ? 'trace.subscribe' : 'trace.unsubscribe', enabled ? { after_seq: afterSeq } : {})
    this.traceRequestId = enabled ? command.request_id : null
    this.send(command)
  }
  async connect(): Promise<void> {
    const epoch = ++this.epoch
    clearTimeout(this.timer); clearInterval(this.heartbeat); this.ws?.close(); this.ws = null
    this.stopped = false
    const state = this.options.state()
    state.ready = false; state.connection = this.retries ? 'reconnecting' : 'connecting'
    try {
      const ticket = await this.options.ticket()
      if (epoch !== this.epoch || this.stopped) return
      const scheme = location.protocol === 'https:' ? 'wss:' : 'ws:'
      const ws = (this.options.socket ?? (url => new WebSocket(url)))(`${scheme}//${location.host}/ws/agent/v2?ticket=${encodeURIComponent(ticket)}`)
      this.ws = ws; this.seenAt = Date.now(); this.syncing = false
      ws.onmessage = event => {
        if (epoch !== this.epoch) return
        this.seenAt = Date.now()
        try {
          const frame = JSON.parse(event.data) as LoopFrame
          if (frame.protocol_version !== 2) throw new Error('不支持的 Agent 协议版本')
          if (frame.type === 'hello') return
          // 退订后丢弃在途诊断帧，不能重新填入已清理的授权记录。
          if (['trace.event', 'schema.catalog'].includes(frame.type) && !this.traceEnabled) return
          if (frame.type === 'command.rejected' && frame.request_id === this.traceRequestId) {
            this.traceEnabled = false
            this.traceRequestId = null
          }
          if (frame.type === 'capabilities') {
            if (frame.data.stream_schema_version !== 'agent-loop-stream.v2.1') throw new Error('不支持的事件 Schema 版本')
            this.resync(); return
          }
          if (frame.type === 'resync.required') {
            const next = restoreSnapshot(this.sessionId, frame.data.cursor, frame.data.snapshot)
            next.connection = 'online'; next.controlled = this.options.state().controlled
            this.options.replace(next); this.syncing = false; this.resync(); return
          }
          const outcome = applyFrame(this.options.state(), frame)
          if (outcome === 'gap') { this.syncing = false; this.resync(); return }
          if (frame.type === 'replay.completed') {
            this.syncing = false; this.retries = 0; this.options.state().connection = 'online'
            if (this.traceEnabled) this.trace(true, this.traceSeq)
          }
          if (frame.type === 'trace.event') this.traceSeq = Math.max(this.traceSeq, frame.data.event?.seq ?? -1)
          if (outcome !== 'duplicate') this.options.onFrame?.(frame)
        } catch {
          this.options.state().error = 'Agent 协议或快照无效，请重新打开会话'
          this.close()
        }
      }
      ws.onclose = event => {
        if (epoch !== this.epoch || this.stopped) return
        clearInterval(this.heartbeat)
        const s = this.options.state(); s.ready = false; s.controlled = false
        if (event.code === 4404) { s.connection = 'revoked'; this.options.onRevoke?.(); this.close(); return }
        s.connection = 'reconnecting'
        if (event.code === 1013) s.error = 'Agent 服务尚未就绪'
        this.schedule()
      }
      this.heartbeat = setInterval(() => {
        if (Date.now() - this.seenAt > 45000) { ws.close(); return }
        this.send(this.command('ping', { client_time: new Date().toISOString() }))
      }, 15000)
    } catch { if (epoch === this.epoch && !this.stopped) { this.options.state().connection = 'offline'; this.schedule() } }
  }
  private schedule(): void {
    clearTimeout(this.timer)
    this.timer = setTimeout(() => { void this.connect() }, Math.min(30000, 1000 * 2 ** Math.min(this.retries++, 5)))
  }
  /** 页面退出/注销才关闭活动控制连接；普通切会话保留 store 中的实例。 */
  close(): void {
    this.stopped = true; this.epoch++; clearTimeout(this.timer); clearInterval(this.heartbeat)
    this.ws?.close(); this.ws = null; this.options.state().ready = false
    if (this.options.state().connection !== 'revoked') this.options.state().connection = 'offline'
  }
}
