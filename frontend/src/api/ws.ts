/**
 * AI 测试与评估平台 — WebSocket 智能体客户端
 * 依据：docs/AI测试与评估平台-PRD.md (5.1.3) 与 API.md (V1.5)
 */
import { api } from './http'
import type { WsServerEvent } from './types'

export type WsEventHandler = (event: WsServerEvent) => void
export type WsStatusHandler = (connected: boolean) => void
export type WsCloseHandler = (code: number) => void

export class AgentWebSocket {
  private ws: WebSocket | null = null
  private reconnectTimer: number | null = null
  private eventHandlers: Set<WsEventHandler> = new Set()
  private statusHandlers: Set<WsStatusHandler> = new Set()
  private closeHandlers: Set<WsCloseHandler> = new Set()
  private isExplicitlyClosed = false
  // 静默判活：最近一次收到消息（含服务端 pong 心跳）的时间戳
  private lastReceiveAt = 0
  private silenceTimer: number | null = null
  // 服务端按 settings.runtime.ws_ping_s（默认 15s）周期发送应用层 pong；
  // 超过该窗口未收到任何消息即判定链路死亡，主动断开触发重连
  private readonly silenceTimeoutMs = 45_000
  public sessionId: string | null = null
  public lastEventId = 0
  public isConnected = false
  // 乱序重排缓冲：图内事件（Hub 即时广播）与 Worker 事件（0.4s 轮询转发）是
  // 两条通道，小号 Worker 事件可能晚于大号图内事件到达。event_id 按会话单调
  // 连续编号，故暂存「未来帧」等待缺失的小号帧；超过重排窗口说明小号帧
  // 永远不会来（编号空洞），按号序冲刷放行。
  // 窗口取值依据：服务端 Worker 转发轮询 0.4s，真实链路延迟 = 轮询间隔 + DB
  // 查询 + 事件桥 emit + 网络，负载下可超 1s；600ms 裕量不足会导致小号帧在
  // 窗口外到达时被重复检测永久丢弃（progress/report 静默丢失），故取 2s
  // （约 5 个轮询周期）作为最坏情况窗口；正常连续帧不启动计时器，不受窗口影响。
  private pendingEvents = new Map<number, WsServerEvent>()
  private flushTimer: number | null = null
  private readonly reorderWindowMs = 2_000

  constructor(sessionId?: string) {
    if (sessionId) this.sessionId = sessionId
  }

  public onEvent(handler: WsEventHandler) {
    this.eventHandlers.add(handler)
    return () => this.eventHandlers.delete(handler)
  }

  public onStatus(handler: WsStatusHandler) {
    this.statusHandlers.add(handler)
    handler(this.isConnected)
    return () => this.statusHandlers.delete(handler)
  }

  /** 透出服务端关闭码：4401 重新领票，4404 清理不可访问会话。 */
  public onClosed(handler: WsCloseHandler) {
    this.closeHandlers.add(handler)
    return () => this.closeHandlers.delete(handler)
  }

  private notifyEvent(event: WsServerEvent) {
    this.eventHandlers.forEach((h) => {
      try {
        h(event)
      } catch (err) {
        console.error('WS event handler error:', err)
      }
    })
  }

  private notifyStatus(connected: boolean) {
    this.isConnected = connected
    this.statusHandlers.forEach((h) => {
      try {
        h(connected)
      } catch (err) {
        console.error('WS status handler error:', err)
      }
    })
  }

  /** 通知连接关闭原因；关闭处理器错误不得影响重连策略。 */
  private notifyClosed(code: number) {
    this.closeHandlers.forEach((handler) => {
      try {
        handler(code)
      } catch (err) {
        console.error('WS close handler error:', err)
      }
    })
  }

  public async connect(): Promise<void> {
    this.isExplicitlyClosed = false
    this.cleanup()

    try {
      // 1. 获取短票（5 分钟有效）
      const { ticket } = await api.auth.getWsTicket()

      // 2. 构造连接 URL
      const proto = location.protocol === 'https:' ? 'wss:' : 'ws:'
      const host = location.host
      const params = new URLSearchParams({ ticket })
      if (this.sessionId) params.set('session_id', this.sessionId)
      if (this.lastEventId > 0) params.set('last_event_id', String(this.lastEventId))

      const url = `${proto}//${host}/ws/agent?${params.toString()}`
      this.ws = new WebSocket(url)

      this.ws.onopen = () => {
        this.lastReceiveAt = Date.now()
        this.startSilenceWatch()
        this.notifyStatus(true)
      }

      this.ws.onclose = (event) => {
        this.notifyStatus(false)
        this.notifyClosed(event.code)
        // 4401 短票过期：重新领票并重连（connect() 每次都会 POST /api/auth/ws-ticket）。
        // 4404 会话已删除或权限被收回：继续重连只会形成无效循环。
        if (event.code === 4404) {
          this.isExplicitlyClosed = true
          this.stopSilenceWatch()
          return
        }
        if (!this.isExplicitlyClosed) {
          this.scheduleReconnect()
        }
      }

      this.ws.onerror = (err) => {
        console.warn('WS error:', err)
        this.ws?.close()
      }

      this.ws.onmessage = (ev) => {
        // 任何消息（含 pong 心跳）都视为链路活跃，先于事件去重更新判活时间戳
        this.lastReceiveAt = Date.now()
        try {
          const data: WsServerEvent = JSON.parse(ev.data)
          // 瞬态帧（pong、assistant_delta）不占用单调事件号，其 event_id 仅复用
          // 连接游标满足公共头结构，必须跳过去重与重排，否则流式增量会因
          // event_id <= lastEventId 被整帧丢弃
          const transient =
            data.event === 'pong'
            || data.event === 'assistant_delta'
            || (data.payload && typeof data.payload.stream === 'string')
          let orderedPersistent = false
          if (!transient && 'event_id' in data && typeof data.event_id === 'number') {
            if (!this.acceptOrdered(data)) return
            orderedPersistent = true
          }
          if ('session_id' in data && data.session_id) {
            this.sessionId = data.session_id
          }
          this.notifyEvent(data)
          // 本帧派发后，缓冲中可能已有连续衔接的下一号帧，按序连带派发
          if (orderedPersistent) this.drainContiguous()
        } catch (e) {
          console.error('Failed to parse WS message:', ev.data, e)
        }
      }
    } catch (err) {
      console.warn('Failed to obtain WS ticket:', err)
      if (!this.isExplicitlyClosed) {
        this.scheduleReconnect()
      }
    }
  }

  public sendUserMessage(
    text: string,
    attachments?: Array<{ file_id: string }>,
    clientMessageId?: string,
  ): void {
    if (!this.ws || this.ws.readyState !== WebSocket.OPEN) {
      console.warn('WebSocket not open, cannot send message')
      return
    }
    const payload = {
      event: 'user_message',
      payload: {
        text,
        attachments: attachments || [],
        ...(clientMessageId ? { client_message_id: clientMessageId } : {}),
      },
    }
    this.ws.send(JSON.stringify(payload))
  }

  public sendCancelTask(taskId: string): boolean {
    if (!this.ws || this.ws.readyState !== WebSocket.OPEN) {
      console.warn('WebSocket not open, cannot send cancel_task')
      return false
    }
    const payload = {
      event: 'cancel_task',
      payload: { task_id: taskId },
    }
    this.ws.send(JSON.stringify(payload))
    return true
  }

  private scheduleReconnect(): void {
    if (this.reconnectTimer !== null) return
    this.reconnectTimer = window.setTimeout(() => {
      this.reconnectTimer = null
      this.connect()
    }, 3000)
  }

  /**
   * 持久化事件的保序入口：重复帧丢弃；下一号帧立即派发并连带冲刷缓冲；
   * 未来帧暂存并启动重排窗口。返回 true 表示本帧可立即派发。
   */
  private acceptOrdered(data: WsServerEvent): boolean {
    const id = data.event_id as number
    // 重复帧（重放补发与转发竞争）或已被更大号覆盖的迟到帧：丢弃
    if (id <= this.lastEventId || this.pendingEvents.has(id)) return false
    // lastEventId === 0 表示全新连接（未带 last_event_id 重放），服务端游标
    // 从当前最大号起步，首帧即基线，直接放行，避免首帧被误当未来帧缓冲
    if (this.lastEventId === 0 || id === this.lastEventId + 1) {
      this.lastEventId = id
      return true
    }
    // 未来帧：小号帧可能仍在服务端转发队列里，暂存等待；窗口到期按号序冲刷
    this.pendingEvents.set(id, data)
    this.startFlushTimer()
    return false
  }

  private startFlushTimer(): void {
    if (this.flushTimer !== null) return
    this.flushTimer = window.setTimeout(() => {
      this.flushTimer = null
      this.flushPending()
    }, this.reorderWindowMs)
  }

  /** 按 event_id 升序冲刷缓冲帧；编号空洞（服务端永不补发）由本函数兜底放行。 */
  private flushPending(): void {
    if (!this.pendingEvents.size) return
    // 窗口到期按序冲刷：若缓冲帧与 lastEventId 之间存在编号空洞，说明小号帧
    // 迟到超过窗口（服务端转发延迟异常或已永久缺失）。记可观测告警，供评估
    // 窗口取值是否仍不足；正常无乱序（不启动计时器）时不触发。
    console.warn(
      `WS reorder window expired: flushing ${this.pendingEvents.size} frame(s) with gap after event_id=${this.lastEventId}`,
    )
    const ordered = [...this.pendingEvents.entries()].sort((a, b) => a[0] - b[0])
    this.pendingEvents.clear()
    for (const [id, frame] of ordered) {
      if (id <= this.lastEventId) continue
      this.lastEventId = id
      if ('session_id' in frame && frame.session_id) {
        this.sessionId = frame.session_id
      }
      this.notifyEvent(frame)
    }
  }

  /** 在 lastEventId 推进后，把缓冲中已连续衔接的帧按序派发。 */
  private drainContiguous(): void {
    while (this.pendingEvents.has(this.lastEventId + 1)) {
      const nextId = this.lastEventId + 1
      const frame = this.pendingEvents.get(nextId)!
      this.pendingEvents.delete(nextId)
      this.lastEventId = nextId
      if ('session_id' in frame && frame.session_id) {
        this.sessionId = frame.session_id
      }
      this.notifyEvent(frame)
    }
    if (!this.pendingEvents.size && this.flushTimer !== null) {
      window.clearTimeout(this.flushTimer)
      this.flushTimer = null
    }
  }

  /** 启动静默判活：周期检查最近消息时间，超时未收到 pong 即断开重连 */
  private startSilenceWatch(): void {
    this.stopSilenceWatch()
    this.silenceTimer = window.setInterval(() => {
      if (this.ws?.readyState !== WebSocket.OPEN) return
      if (Date.now() - this.lastReceiveAt > this.silenceTimeoutMs) {
        console.warn('WS silence timeout, forcing reconnect')
        this.stopSilenceWatch()
        this.ws.close()
      }
    }, 10_000)
  }

  private stopSilenceWatch(): void {
    if (this.silenceTimer !== null) {
      clearInterval(this.silenceTimer)
      this.silenceTimer = null
    }
  }

  public close(): void {
    this.isExplicitlyClosed = true
    this.cleanup()
  }

  private cleanup(): void {
    this.stopSilenceWatch()
    // 重连后服务端会按 last_event_id 重放，缓冲中的旧帧一律作废（重放帧
    // 会经 acceptOrdered 的重复检测丢弃，不会造成二次渲染）
    this.pendingEvents.clear()
    if (this.flushTimer !== null) {
      window.clearTimeout(this.flushTimer)
      this.flushTimer = null
    }
    if (this.reconnectTimer !== null) {
      clearTimeout(this.reconnectTimer)
      this.reconnectTimer = null
    }
    if (this.ws) {
      this.ws.onopen = null
      this.ws.onclose = null
      this.ws.onerror = null
      this.ws.onmessage = null
      if (this.ws.readyState === WebSocket.OPEN || this.ws.readyState === WebSocket.CONNECTING) {
        this.ws.close()
      }
      this.ws = null
    }
  }
}
