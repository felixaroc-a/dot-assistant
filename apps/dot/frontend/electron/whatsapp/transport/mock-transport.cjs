'use strict'

const { WhatsappTransport } = require('./whatsapp-transport.cjs')

let instanceCounter = 0

class MockTransport extends WhatsappTransport {
  constructor() {
    super()
    this._id = ++instanceCounter
    this._state = 'idle'
    this._linked = false
    this._phoneNumber = null
    this._daemonRunning = false
    this._loginRunning = false
    this._lastError = null
    this._statusListeners = new Set()
    this._inboundCallbacks = new Set()
    this._messagesSent = []
  }

  // ─── Ciclo de vida ─────────────────────────────────────

  async initialize() {
    this._state = 'idle'
    return { ok: true }
  }

  async startLogin(opts) {
    const { onChunk, onLinked, onExit } = opts
    this._loginRunning = true
    this._state = 'logging_in'
    this._emitStatus()

    if (onChunk) {
      onChunk({ stream: 'stdout', text: '[MOCK] Iniciando vinculación simulada…\n' })
    }

    await this._delay(500)

    if (onChunk) {
      onChunk({ stream: 'stdout', text: '\nDOT_WHATSAPP_QR:MOCK_QR_PAYLOAD_SIMULATED\n' })
    }

    await this._delay(1500)

    this._linked = true
    this._phoneNumber = '+584144001856'
    this._daemonRunning = true
    this._state = 'connected'
    this._emitStatus()

    if (onLinked) {
      onLinked({ linked: true, phone_number: this._phoneNumber })
    }
    if (onChunk) {
      onChunk({ stream: 'stdout', text: '\n[MOCK] WhatsApp vinculado exitosamente (simulado).\n' })
    }
    if (onExit) {
      onExit({ code: 0, signal: null })
    }

    this._loginRunning = false
    return { ok: true }
  }

  async startDaemon(reason) {
    this._daemonRunning = true
    this._state = 'connected'
    this._emitStatus()
    return { ok: true }
  }

  stopDaemon() {
    this._daemonRunning = false
    this._state = this._linked ? 'disconnected' : 'idle'
    this._emitStatus()
    return { ok: true }
  }

  stopLogin() {
    this._loginRunning = false
    this._state = this._linked ? 'connected' : 'idle'
    this._emitStatus()
    return { ok: true }
  }

  stopAll() {
    this.stopLogin()
    this.stopDaemon()
    return { ok: true }
  }

  shutdown() {
    this._loginRunning = false
    this._daemonRunning = false
    this._linked = false
    this._state = 'idle'
    this._statusListeners.clear()
    this._inboundCallbacks.clear()
    this._messagesSent = []
  }

  // ─── Estado ────────────────────────────────────────────

  getStatus() {
    return {
      state: this._state,
      linked: this._linked,
      daemonRunning: this._daemonRunning,
      loginRunning: this._loginRunning,
      phone_number: this._phoneNumber,
      error: this._lastError,
      restartAttempts: 0,
    }
  }

  onStatusChange(listener) {
    this._statusListeners.add(listener)
    return () => this._statusListeners.delete(listener)
  }

  isLoginRunning() {
    return this._loginRunning
  }

  isDaemonRunning() {
    return this._daemonRunning
  }

  // ─── Mensajería ────────────────────────────────────────

  async sendMessage(to, text) {
    const msg = {
      to: String(to || '').trim(),
      text: String(text || '').trim(),
      timestamp: new Date().toISOString(),
      transport: 'mock',
    }
    if (!msg.to || !msg.text) {
      return { ok: false, error: 'Destino y texto son obligatorios.' }
    }

    await this._delay(100)
    this._messagesSent.push(msg)

    const messageId = `mock_${Date.now()}_${Math.random().toString(36).slice(2, 10)}`
    return { ok: true, message_id: messageId }
  }

  async sendMedia(to, filePath, opts = {}) {
    const msg = {
      to: String(to || '').trim(),
      filePath: String(filePath || '').trim(),
      mediaType: String(opts.mediaType || 'document'),
      caption: String(opts.caption || ''),
      timestamp: new Date().toISOString(),
      transport: 'mock',
    }
    if (!msg.to || !msg.filePath) {
      return { ok: false, error: 'Destino y ruta de archivo son obligatorios.' }
    }

    await this._delay(100)
    this._messagesSent.push(msg)

    const messageId = `mock_media_${Date.now()}_${Math.random().toString(36).slice(2, 10)}`
    return { ok: true, message_id: messageId }
  }

  onInboundMessage(callback) {
    if (typeof callback === 'function') {
      this._inboundCallbacks.add(callback)
    }
    return () => this._inboundCallbacks.delete(callback)
  }

  // ─── Utilidad ──────────────────────────────────────────

  async probeConfigured() {
    return { configured: this._linked, raw: '{ "configuredChannels": ["whatsapp"] }' }
  }

  ensureOwnPhone(hint) {
    if (hint) {
      this._phoneNumber = String(hint)
    }
    if (!this._phoneNumber) {
      this._phoneNumber = '+584144001856'
    }
    return this._phoneNumber
  }

  applyPolicy(opts = {}) {
    return { ok: true, changed: false, mode: 'locked' }
  }

  warmup() {
    // Mock: no-op
  }

  // ─── Helpers de test ──────────────────────────────────

  getMessagesSent() {
    return [...this._messagesSent]
  }

  clearMessages() {
    this._messagesSent = []
  }

  simulateInbound(payload) {
    for (const cb of this._inboundCallbacks) {
      try {
        cb(payload)
      } catch {
        // ignore
      }
    }
  }

  setPhone(phone) {
    this._phoneNumber = phone
  }

  setLinked(linked) {
    this._linked = linked
    this._emitStatus()
  }

  // ─── Privados ─────────────────────────────────────────

  _emitStatus() {
    const snapshot = this.getStatus()
    for (const listener of this._statusListeners) {
      try {
        listener(snapshot)
      } catch {
        // ignore
      }
    }
  }

  _delay(ms) {
    return new Promise((resolve) => setTimeout(resolve, ms))
  }
}

module.exports = { MockTransport }
