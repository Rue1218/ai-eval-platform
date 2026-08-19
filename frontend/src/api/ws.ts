/**
 * AI 测试与评估平台 — WebSocket 智能体客户端
 * 依据：docs/AI测试与评估平台-PRD.md (5.1.3) 与 API.md (1.3)
 */
import { api } from './http'
import type { WsServerEvent } from './types'

export type WsEventHandler = (event: WsServerEvent) => void
export type WsStatusHandler = (connected: boolean) => void

export class AgentWebSocket {
  private ws: WebSocket | null = null
  private reconnectTimer: number | null = null
  private eventHandlers: Set<WsEventHandler> = new Set()
  private statusHandlers: Set<WsStatusHandler> = new Set()
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

      this.ws.onclose = () => {
        this.notifyStatus(false)
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
          // 瞬态帧（pong 心跳与 stream:chunk / stream:think 增量）不占用
          // 单调事件号，其 event_id 仅复用连接游标满足公共头结构，
          // 必须跳过去重，否则流式增量会因 event_id <= lastEventId 被整帧丢弃
          const transient =
            data.event === 'pong' || (data.payload && typeof data.payload.stream === 'string')
          if (!transient && 'event_id' in data && typeof data.event_id === 'number') {
            // 事件号单调递增：重放补发与服务端转发竞争可能产生重复事件，按 event_id 去重
            if (data.event_id <= this.lastEventId) return
            this.lastEventId = data.event_id
          }
          if ('session_id' in data && data.session_id) {
            this.sessionId = data.session_id
          }
          this.notifyEvent(data)
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

  public sendUserMessage(text: string, attachments?: Array<{ file_id: string }>): void {
    if (!this.ws || this.ws.readyState !== WebSocket.OPEN) {
      console.warn('WebSocket not open, cannot send message')
      return
    }
    const payload = {
      event: 'user_message',
      payload: { text, attachments: attachments || [] },
    }
    this.ws.send(JSON.stringify(payload))
  }

  public sendConfirmAck(ok: boolean, patch?: any): void {
    if (!this.ws || this.ws.readyState !== WebSocket.OPEN) {
      console.warn('WebSocket not open, cannot send confirm_ack')
      return
    }
    const payload = {
      event: 'confirm_ack',
      payload: { ok, patch },
    }
    this.ws.send(JSON.stringify(payload))
  }

  public sendCancelTask(taskId: string): void {
    if (!this.ws || this.ws.readyState !== WebSocket.OPEN) {
      console.warn('WebSocket not open, cannot send cancel_task')
      return
    }
    const payload = {
      event: 'cancel_task',
      payload: { task_id: taskId },
    }
    this.ws.send(JSON.stringify(payload))
  }

  private scheduleReconnect(): void {
    if (this.reconnectTimer !== null) return
    this.reconnectTimer = window.setTimeout(() => {
      this.reconnectTimer = null
      this.connect()
    }, 3000)
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
