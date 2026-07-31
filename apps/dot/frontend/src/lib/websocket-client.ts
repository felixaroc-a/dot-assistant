type WsHandler = (data: unknown) => void

type WsStatus = 'connected' | 'connecting' | 'disconnected'

class WebSocketClient {
  private ws: WebSocket | null = null
  private handlers: Map<string, Set<WsHandler>> = new Map()
  private reconnectTimer: ReturnType<typeof setTimeout> | null = null
  private url: string = ''
  private _status: WsStatus = 'disconnected'
  private statusListeners: Set<(s: WsStatus) => void> = new Set()

  get status(): WsStatus {
    return this._status
  }

  private setStatus(s: WsStatus) {
    this._status = s
    this.statusListeners.forEach((fn) => fn(s))
  }

  onStatusChange(fn: (s: WsStatus) => void): () => void {
    this.statusListeners.add(fn)
    return () => this.statusListeners.delete(fn)
  }

  connect(token: string) {
    const base =
      (typeof import.meta !== 'undefined' &&
        import.meta.env?.VITE_WS_URL) ||
      'ws://127.0.0.1:8000'
    this.url = `${base}/ws/notifications?token=${token}`
    this._connect()
  }

  private _connect() {
    if (this.ws) this.ws.close()
    this.setStatus('connecting')
    try {
      this.ws = new WebSocket(this.url)
    } catch {
      this.setStatus('disconnected')
      this.scheduleReconnect()
      return
    }

    this.ws.onopen = () => {
      this.setStatus('connected')
    }

    this.ws.onmessage = (event: MessageEvent) => {
      try {
        const msg = JSON.parse(event.data) as { type: string; data: unknown }
        const typeHandlers = this.handlers.get(msg.type)
        if (typeHandlers) {
          typeHandlers.forEach((h) => h(msg.data))
        }
        const allHandlers = this.handlers.get('*')
        if (allHandlers) {
          allHandlers.forEach((h) => h(msg))
        }
      } catch {
        /* ignore parse errors */
      }
    }

    this.ws.onclose = () => {
      this.setStatus('disconnected')
      this.scheduleReconnect()
    }

    this.ws.onerror = () => {
      this.ws?.close()
    }
  }

  private scheduleReconnect() {
    if (this.reconnectTimer) clearTimeout(this.reconnectTimer)
    this.reconnectTimer = setTimeout(() => this._connect(), 5000)
  }

  on(eventType: string, handler: WsHandler) {
    if (!this.handlers.has(eventType)) {
      this.handlers.set(eventType, new Set())
    }
    this.handlers.get(eventType)!.add(handler)
    return () => this.handlers.get(eventType)?.delete(handler)
  }

  disconnect() {
    if (this.reconnectTimer) {
      clearTimeout(this.reconnectTimer)
      this.reconnectTimer = null
    }
    this.ws?.close()
    this.ws = null
    this.setStatus('disconnected')
  }
}

export const wsClient = new WebSocketClient()
