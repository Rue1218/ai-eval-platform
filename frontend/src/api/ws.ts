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
        try {
          const data: WsServerEvent = JSON.parse(ev.data)
          if ('event_id' in data && typeof data.event_id === 'number') {
            if (data.event_id > this.lastEventId) {
              this.lastEventId = data.event_id
            }
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

  public close(): void {
    this.isExplicitlyClosed = true
    this.cleanup()
  }

  private cleanup(): void {
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
