'use strict'

/**
 * BaileysTransport — WhatsApp propio detrás de WhatsappTransport (happy path DOT).
 *
 * Fallback legacy OpenClaw disponible solo con WHATSAPP_TRANSPORT=openclaw.
 *
 * QR se emite con sentinel DOT_WHATSAPP_QR (mismo contrato UI).
 * Auth persistida en userData/whatsapp-baileys (o DOT_BAILEYS_AUTH_DIR).
 */

const { spawn } = require('node:child_process')
const fs = require('node:fs')
const os = require('node:os')
const path = require('node:path')

const { WhatsappTransport } = require('./whatsapp-transport.cjs')
const { normalizePhoneE164 } = require('../phone-utils.cjs')
const secureStorage = require('../../secure-storage.cjs')

const debugLogPath = path.join(os.tmpdir(), 'dot-whatsapp-baileys.log')

function resolveAuthDir() {
  const fromEnv = String(process.env.DOT_BAILEYS_AUTH_DIR || '').trim()
  if (fromEnv) return fromEnv
  try {
    const { app } = require('electron')
    if (app && typeof app.getPath === 'function') {
      return path.join(app.getPath('userData'), 'whatsapp-baileys')
    }
  } catch {
    // fuera de Electron
  }
  return path.join(os.homedir(), '.dot', 'whatsapp-baileys')
}

function resolveWorkerPath() {
  return path.join(__dirname, '..', 'baileys', 'baileys-worker.cjs')
}

class BaileysTransport extends WhatsappTransport {
  constructor() {
    super()
    this._authDir = resolveAuthDir()
    this._worker = null
    this._connectionState = 'idle'
    this._linked = false
    this._phoneNumber = null
    this._lastError = null
    this._restartAttempts = 0
    this._restartTimer = null
    this._intentionalStop = false
    /** Tras loggedOut de WhatsApp: no reiniciar daemon hasta un login QR limpio. */
    this._needsFreshLogin = false
    /** Durante login: si WhatsApp rechaza creds viejas, reintentar worker una vez con auth limpia. */
    this._respawnForFreshQr = false
    this._loginPhase = false
    this._loginCallbacks = null
    this._statusListeners = new Set()
    this._inboundForwarder = async () => {}
    this._mediaDownloadedForwarder = () => {}
    this._stdoutBuffer = ''
    this._pendingSends = new Map()
    this._sendSeq = 0
    this._startPromise = null
  }

  /**
   * Borra credenciales/sesión Baileys locales.
   * Necesario tras loggedOut: WhatsApp rechaza creds viejas sin emitir QR.
   */
  _clearAuthDir() {
    try {
      if (!fs.existsSync(this._authDir)) return
      for (const name of fs.readdirSync(this._authDir)) {
        try {
          fs.rmSync(path.join(this._authDir, name), { recursive: true, force: true })
        } catch {
          // ignore archivo individual
        }
      }
      this._debugLog(`authDir limpiado: ${this._authDir}`)
    } catch (err) {
      this._debugLog(`authDir clear error: ${err instanceof Error ? err.message : String(err)}`)
    }
  }

  // ─── A03: Persistencia de credenciales en safeStorage ──────────────────

  /**
   * Guarda las credenciales Baileys en safeStorage del SO.
   * Se llama tras vinculación exitosa (QR → linked) para sobrevivir reinicios.
   */
  _persistCredsToSafeStorage() {
    try {
      const credsPath = path.join(this._authDir, 'creds.json')
      if (!fs.existsSync(credsPath)) {
        this._debugLog('_persistCredsToSafeStorage: creds.json no encontrado aún')
        return false
      }
      const raw = fs.readFileSync(credsPath, 'utf8')
      if (!raw || !raw.trim()) return false
      // Validar que sea JSON parseable antes de guardar
      JSON.parse(raw)
      const result = secureStorage.saveWhatsAppCreds(raw)
      this._debugLog(`_persistCredsToSafeStorage: ok=${result.ok} encrypted=${result.encrypted}`)
      return result.ok
    } catch (err) {
      this._debugLog(`_persistCredsToSafeStorage error: ${err instanceof Error ? err.message : String(err)}`)
      return false
    }
  }

  /**
   * Intenta restaurar credenciales desde safeStorage al authDir.
   * @returns {boolean} true si se restauraron credenciales
   */
  _restoreCredsFromSafeStorage() {
    try {
      const raw = secureStorage.loadWhatsAppCreds()
      if (!raw || !raw.trim()) {
        this._debugLog('_restoreCredsFromSafeStorage: sin credenciales en safeStorage')
        return false
      }
      // Validar que sea JSON antes de escribir a disco
      JSON.parse(raw)
      fs.mkdirSync(this._authDir, { recursive: true })
      fs.writeFileSync(path.join(this._authDir, 'creds.json'), raw, 'utf8')
      this._debugLog('_restoreCredsFromSafeStorage: credenciales restauradas a authDir')
      return true
    } catch (err) {
      this._debugLog(`_restoreCredsFromSafeStorage error: ${err instanceof Error ? err.message : String(err)}`)
      // Credenciales corruptas en safeStorage: limpiarlas
      secureStorage.clearWhatsAppCreds()
      return false
    }
  }

  /**
   * Borra las credenciales persistidas en safeStorage (logout / sesión expirada).
   */
  _clearPersistedCreds() {
    try {
      secureStorage.clearWhatsAppCreds()
      this._debugLog('_clearPersistedCreds: credenciales safeStorage limpiadas')
    } catch (err) {
      this._debugLog(`_clearPersistedCreds error: ${err instanceof Error ? err.message : String(err)}`)
    }
  }

  _markLoggedOut(detail = 'logged_out') {
    this._linked = false
    this._phoneNumber = null
    this._needsFreshLogin = true
    this._lastError = detail
    this._connectionState = 'disconnected'
    this._clearAuthDir()
    this._clearPersistedCreds()
    this._emitStatus()
  }

  _debugLog(msg) {
    try {
      fs.appendFileSync(debugLogPath, `[${new Date().toISOString()}] ${msg}\n`)
    } catch {
      // ignore
    }
  }

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

  _setConnectionState(state) {
    this._connectionState = state
    this._emitStatus()
  }

  _markLinked(data = {}) {
    this._linked = true
    this._needsFreshLogin = false
    this._respawnForFreshQr = false
    const phone =
      normalizePhoneE164(data.phone_number || '') ||
      data.phone_number ||
      this._phoneNumber ||
      this._readPhoneFromCreds()
    if (phone) this._phoneNumber = phone
    this._lastError = null
    this._restartAttempts = 0
    this._connectionState = 'connected'
    this._emitStatus()
    // A03: persistir credenciales en safeStorage para sobrevivir reinicios
    // Pequeña demora para asegurar que Baileys terminó de escribir creds.json
    setTimeout(() => { this._persistCredsToSafeStorage() }, 1500)
    return { linked: true, phone_number: this._phoneNumber || undefined }
  }

  _readPhoneFromCreds() {
    try {
      const credsPath = path.join(this._authDir, 'creds.json')
      if (!fs.existsSync(credsPath)) return null
      const parsed = JSON.parse(fs.readFileSync(credsPath, 'utf8'))
      const meId = parsed?.me?.id
      if (!meId) return null
      const user = String(meId).split('@')[0].split(':')[0]
      return normalizePhoneE164(user) || null
    } catch {
      return null
    }
  }

  _hasLocalCreds() {
    try {
      const credsPath = path.join(this._authDir, 'creds.json')
      if (!fs.existsSync(credsPath)) return false
      const raw = fs.readFileSync(credsPath, 'utf8')
      // Creds a medio escribir / corruptas: NO borrar aquí (Baileys puede estar
      // escribiendo). Solo reportar "sin sesión" y dejar limpia en login/bootstrap.
      if (!raw || !raw.trim() || raw.charCodeAt(0) === 0) {
        this._debugLog('creds.json ilegible o vacío (no se borra en probe)')
        return false
      }
      const parsed = JSON.parse(raw)
      return Boolean(parsed?.me?.id || parsed?.registered)
    } catch (err) {
      this._debugLog(`creds.json ilegible: ${err instanceof Error ? err.message : String(err)}`)
      return false
    }
  }

  _sendWorkerCmd(cmd) {
    if (!this._worker || this._worker.killed || this._worker.exitCode !== null) {
      return false
    }
    try {
      this._worker.stdin.write(`${JSON.stringify(cmd)}\n`)
      return true
    } catch {
      return false
    }
  }

  _handleWorkerEvents(line) {
    let event
    try {
      event = JSON.parse(line)
    } catch {
      return
    }

    const type = String(event.type || '')

    if (type === 'qr' && event.qr) {
      const qr = String(event.qr)
      // Reconexión silenciosa: QR fuera de login = sesión muerta; no inundar UI.
      if (!this._loginPhase && this._hasLocalCreds()) {
        this._debugLog('QR inesperado fuera de login; sesión local inválida')
        this._intentionalStop = true
        try {
          this._sendWorkerCmd({ cmd: 'stop' })
          this._worker?.kill('SIGTERM')
        } catch {
          // ignore
        }
        this._worker = null
        this._markLoggedOut('logged_out')
        this._lastError = 'Vuelve a escanear el código.'
        this._emitStatus()
        return
      }
      this._connectionState = 'logging_in'
      this._emitStatus()
      if (this._loginCallbacks?.onChunk) {
        this._loginCallbacks.onChunk({
          stream: 'stdout',
          text: `\nDOT_WHATSAPP_QR:${qr}\n`,
        })
        this._loginCallbacks.onChunk({
          stream: 'stderr',
          text: '[DOT] Código QR listo — escanea con WhatsApp.\n',
        })
      }
      return
    }

    if (type === 'linked') {
      const enriched = this._markLinked({ phone_number: event.phone_number })
      if (this._loginCallbacks?.onChunk) {
        this._loginCallbacks.onChunk({
          stream: 'stdout',
          text: `\n[DOT] WhatsApp vinculado exitosamente.\nphone_number=${enriched.phone_number || ''}\n`,
        })
      }
      if (this._loginPhase) {
        this._loginPhase = false
        this._loginCallbacks?.onLinked?.(enriched)
        this._loginCallbacks?.onExit?.({ code: 0, signal: null })
        this._loginCallbacks = null
      }
      return
    }

    if (type === 'status') {
      const state = String(event.state || '')
      const detail = event.detail ? String(event.detail) : ''
      if (state === 'connected') {
        this._connectionState = 'connected'
        this._lastError = null
        this._needsFreshLogin = false
      } else if (state === 'disconnected') {
        if (detail === 'logged_out' || /logged.?out/i.test(detail)) {
          const wasLogin = this._loginPhase
          this._markLoggedOut(detail || 'logged_out')
          if (this._loginCallbacks?.onChunk) {
            this._loginCallbacks.onChunk({
              stream: 'stderr',
              text: wasLogin
                ? '[DOT] Sesión previa inválida. Regenerando código QR…\n'
                : '[DOT] Sesión WhatsApp cerrada. Necesitas vincular de nuevo con QR.\n',
            })
          }
          // En fase de login: ya limpiamos auth; el worker va a salir — reabrir limpio para emitir QR.
          if (wasLogin && !this._respawnForFreshQr) {
            this._respawnForFreshQr = true
            this._needsFreshLogin = false
            this._intentionalStop = true
          }
          return
        }
        this._connectionState = 'disconnected'
        this._lastError = detail || 'disconnected'
      } else if (state === 'logging_in') {
        this._connectionState = 'logging_in'
      } else if (state === 'starting') {
        this._connectionState = this._restartAttempts > 0 ? 'restarting' : 'starting'
        if (this._restartAttempts > 0 || this._hasLocalCreds()) {
          this._lastError = null
        }
      }
      this._emitStatus()
      return
    }

    if (type === 'message') {
      const payload = {
        message_id: event.message_id || '',
        from_phone: event.from_phone || '',
        to_phone: event.to_phone || this._phoneNumber || '',
        text: event.text || '',
        timestamp: event.timestamp || new Date().toISOString(),
        is_group: Boolean(event.is_group),
        chat_jid: event.chat_jid || '',
        group_name: event.group_name || '',
        group_subject: event.group_subject || '',
        has_media: Boolean(event.has_media),
        has_audio: Boolean(event.has_audio),
        has_image: Boolean(event.has_image),
        has_document: Boolean(event.has_document),
        media_mime_type: event.media_mime_type || undefined,
        media_data_base64: event.media_data_base64 || undefined,
        media_filename: event.media_filename || undefined,
        source: 'electron-baileys',
      }
      void Promise.resolve(this._inboundForwarder(payload)).catch((err) => {
        this._debugLog(`inbound forward error: ${err instanceof Error ? err.message : String(err)}`)
      })
      return
    }

    if (type === 'send_result') {
      const pending = this._pendingSends.get(event.request_id)
      if (!pending) return
      this._pendingSends.delete(event.request_id)
      if (event.ok) {
        pending.resolve({ ok: true, message_id: event.message_id })
      } else {
        pending.resolve({ ok: false, error: event.error || 'send_failed' })
      }
      return
    }

    if (type === 'media_downloaded') {
      const payload = {
        message_id: event.message_id || '',
        ok: Boolean(event.ok),
        file_path: event.file_path || undefined,
        mime_type: event.mime_type || undefined,
        size: event.size || undefined,
        error: event.error || undefined,
      }
      try {
        this._mediaDownloadedForwarder(payload)
      } catch (err) {
        this._debugLog(`media_downloaded forward error: ${err instanceof Error ? err.message : String(err)}`)
      }
      return
    }

    if (type === 'error') {
      const msg = String(event.error || 'error baileys')
      this._lastError = msg
      this._emitStatus()
      if (this._loginCallbacks?.onChunk) {
        const userMsg = /baileys|worker|node_modules|openclaw|npm|gateway/i.test(msg)
          ? 'No se pudo completar la vinculación de WhatsApp.'
          : msg
        this._loginCallbacks.onChunk({ stream: 'stderr', text: `[DOT] ${userMsg}\n` })
      }
      this._debugLog(`worker error: ${msg}`)
      return
    }

    if (type === 'log') {
      this._debugLog(String(event.message || ''))
    }
  }

  _attachWorker(child) {
    this._worker = child
    this._stdoutBuffer = ''
    child.stdout.setEncoding('utf8')
    child.stderr.setEncoding('utf8')

    child.stdout.on('data', (chunk) => {
      this._stdoutBuffer += String(chunk)
      const parts = this._stdoutBuffer.split(/\r?\n/)
      this._stdoutBuffer = parts.pop() || ''
      for (const line of parts) {
        if (line.trim()) this._handleWorkerEvents(line)
      }
    })

    child.stderr.on('data', (chunk) => {
      this._debugLog(`worker stderr: ${String(chunk).slice(0, 500)}`)
      if (this._loginCallbacks?.onChunk) {
        this._loginCallbacks.onChunk({ stream: 'stderr', text: String(chunk) })
      }
    })

    child.on('error', (err) => {
      this._debugLog(`worker spawn error: ${err.message}`)
      this._worker = null
      this._lastError = err.message
      this._connectionState = 'disconnected'
      this._emitStatus()
      if (this._loginPhase) {
        this._loginPhase = false
        const userMsg = /baileys|worker|node_modules|openclaw|npm|gateway/i.test(err.message)
          ? 'No se pudo completar la vinculación de WhatsApp.'
          : err.message
        this._loginCallbacks?.onChunk?.({
          stream: 'stderr',
          text: `[DOT] ${userMsg}\n`,
        })
        this._loginCallbacks?.onExit?.({ code: 1, signal: null })
        this._loginCallbacks = null
      }
      if (!this._intentionalStop) this._scheduleRestart(err.message)
    })

    child.on('close', (code, signal) => {
      this._debugLog(`worker closed code=${code} signal=${signal}`)
      this._worker = null
      for (const [, pending] of this._pendingSends) {
        pending.resolve({ ok: false, error: 'worker_closed' })
      }
      this._pendingSends.clear()

      if (this._loginPhase && this._respawnForFreshQr) {
        this._respawnForFreshQr = false
        this._intentionalStop = false
        this._debugLog('respawn worker para QR fresco tras loggedOut')
        void this._ensureWorker().then((started) => {
          if (!started.ok && this._loginPhase) {
            this._loginPhase = false
            this._loginCallbacks?.onChunk?.({
              stream: 'stderr',
              text: `[DOT] ${started.error || 'No se pudo reiniciar el worker WhatsApp'}\n`,
            })
            this._loginCallbacks?.onExit?.({ code: 1, signal: null })
            this._loginCallbacks = null
          }
        })
        return
      }

      if (this._loginPhase) {
        this._loginPhase = false
        this._loginCallbacks?.onExit?.({ code: code ?? 1, signal: signal ?? null })
        this._loginCallbacks = null
      }

      if (this._intentionalStop) {
        this._connectionState = this._linked ? 'disconnected' : 'idle'
        this._emitStatus()
        return
      }

      this._connectionState = 'disconnected'
      this._emitStatus()
      this._scheduleRestart(`worker_exit_${code}`)
    })
  }

  _scheduleRestart(reason) {
    if (this._intentionalStop) return
    // Sin sesión válida no tiene sentido reiniciar: hay que pedir QR de nuevo.
    if (this._needsFreshLogin || /logged.?out/i.test(String(reason || ''))) {
      this._debugLog(`scheduleRestart omitido (${reason}) — hace falta login QR fresco`)
      this._lastError = 'Vuelve a escanear el código.'
      this._connectionState = 'disconnected'
      this._emitStatus()
      return
    }
    if (this._restartAttempts >= 8) {
      this._lastError = 'No se pudo reconectar WhatsApp. Vuelve a escanear el código.'
      this._emitStatus()
      return
    }
    this._restartAttempts += 1
    const delay = Math.min(30_000, 2_000 * 2 ** (this._restartAttempts - 1))
    this._connectionState = 'restarting'
    this._lastError = null
    this._emitStatus()
    this._debugLog(`scheduleRestart attempt=${this._restartAttempts} delay=${delay}`)
    clearTimeout(this._restartTimer)
    this._restartTimer = setTimeout(() => {
      this._restartTimer = null
      void this.startDaemon('auto_restart')
    }, delay)
  }

  async _ensureWorker() {
    if (this.isDaemonRunning()) return { ok: true }
    if (this._startPromise) return this._startPromise

    this._startPromise = (async () => {
      fs.mkdirSync(this._authDir, { recursive: true })
      const workerPath = resolveWorkerPath()
      if (!fs.existsSync(workerPath)) {
        return { ok: false, error: 'No se pudo iniciar la vinculación de WhatsApp. Intenta de nuevo.' }
      }

      this._intentionalStop = false
      this._setConnectionState(this._restartAttempts > 0 ? 'restarting' : 'starting')

      const child = spawn(process.execPath, [workerPath, this._authDir], {
        env: {
          ...process.env,
          ELECTRON_RUN_AS_NODE: '1',
          FORCE_COLOR: '0',
          NO_COLOR: '1',
        },
        stdio: ['pipe', 'pipe', 'pipe'],
        windowsHide: true,
        shell: false,
      })

      this._attachWorker(child)
      this._debugLog(`worker spawned pid=${child.pid} authDir=${this._authDir}`)
      return { ok: true }
    })()

    try {
      return await this._startPromise
    } finally {
      this._startPromise = null
    }
  }

  // ─── WhatsappTransport ─────────────────────────────────

  async initialize() {
    this._debugLog('BaileysTransport: initialize')
    fs.mkdirSync(this._authDir, { recursive: true })
    return { ok: true }
  }

  async startLogin(opts) {
    const { onChunk, onLinked, onExit } = opts || {}
    if (this._loginPhase) {
      return { ok: false, error: 'Ya hay una vinculación en curso. Espera unos segundos o reinicia la app.' }
    }

    this._loginPhase = true
    this._loginCallbacks = { onChunk, onLinked, onExit }
    onChunk?.({ stream: 'stderr', text: '[DOT] Iniciando vinculación WhatsApp…\n' })
    this._setConnectionState('logging_in')

    // Ya vinculado y daemon vivo con sesión sana: no reinstanciar QR.
    if (
      this._linked &&
      !this._needsFreshLogin &&
      this.isDaemonRunning() &&
      this._connectionState === 'connected'
    ) {
      const enriched = this._markLinked({ phone_number: this._phoneNumber })
      onChunk?.({
        stream: 'stdout',
        text: `\n[DOT] WhatsApp ya vinculado.\nphone_number=${enriched.phone_number || ''}\n`,
      })
      onLinked?.(enriched)
      onExit?.({ code: 0, signal: null })
      this._loginPhase = false
      this._loginCallbacks = null
      return { ok: true }
    }

    // Login QR limpio: detener worker y borrar creds.
    // Credenciales post-logout hacen que Baileys cierre con loggedOut SIN emitir QR.
    clearTimeout(this._restartTimer)
    this._restartTimer = null
    this._restartAttempts = 0
    this.stopDaemon()
    this._clearAuthDir()
    this._clearPersistedCreds()
    this._linked = false
    this._phoneNumber = null
    this._needsFreshLogin = false
    this._intentionalStop = false
    this._lastError = null
    onChunk?.({
      stream: 'stderr',
      text: '[DOT] Generando código QR…\n',
    })

    const started = await this._ensureWorker()
    if (!started.ok) {
      this._loginPhase = false
      this._loginCallbacks = null
      onChunk?.({ stream: 'stderr', text: `[DOT] ${started.error}\n` })
      this._setConnectionState('idle')
      return started
    }

    return { ok: true }
  }

  async startDaemon(reasonOrOpts = 'manual') {
    const reason =
      typeof reasonOrOpts === 'object' ? reasonOrOpts.reason || 'manual' : reasonOrOpts
    this._debugLog(`startDaemon reason=${reason}`)

    // A03: si no hay credenciales locales, intentar restaurar desde safeStorage
    if (!this._hasLocalCreds()) {
      const restored = this._restoreCredsFromSafeStorage()
      if (restored) {
        this._debugLog(`startDaemon: credenciales restauradas desde safeStorage (reason=${reason})`)
        // Si se restauraron, ya no necesita login fresco — reiniciar el flag
        if (this._needsFreshLogin) {
          this._needsFreshLogin = false
        }
      }
    }

    if (this._needsFreshLogin && !this._hasLocalCreds()) {
      this._debugLog(`startDaemon omitido (${reason}) — sin credenciales, hace falta QR`)
      this._lastError = 'Vuelve a escanear el código.'
      this._setConnectionState('disconnected')
      return { ok: false, error: this._lastError }
    }

    if (this.isDaemonRunning()) {
      this._setConnectionState('connected')
      return { ok: true }
    }

    const started = await this._ensureWorker()
    if (!started.ok) {
      this._lastError = started.error || 'start_failed'
      this._setConnectionState('disconnected')
      return started
    }
    return { ok: true }
  }

  stopLogin() {
    // Tras QR exitoso el worker ES el daemon — no matarlo.
    if (this._linked && this.isDaemonRunning()) {
      this._loginPhase = false
      this._loginCallbacks = null
      this._setConnectionState('connected')
      return { ok: true }
    }

    this._loginPhase = false
    const cbs = this._loginCallbacks
    this._loginCallbacks = null

    if (!this._linked) {
      this._intentionalStop = true
      clearTimeout(this._restartTimer)
      this._restartTimer = null
      try {
        this._sendWorkerCmd({ cmd: 'stop' })
        this._worker?.kill('SIGTERM')
      } catch {
        // ignore
      }
      this._worker = null
      this._setConnectionState('idle')
    }

    cbs?.onExit?.({ code: 0, signal: null })
    return { ok: true }
  }

  stopDaemon() {
    this._intentionalStop = true
    clearTimeout(this._restartTimer)
    this._restartTimer = null
    this._restartAttempts = 0
    try {
      this._sendWorkerCmd({ cmd: 'stop' })
      this._worker?.kill('SIGTERM')
    } catch {
      // ignore
    }
    this._worker = null
    this._setConnectionState(this._linked ? 'disconnected' : 'idle')
    return { ok: true }
  }

  stopAll() {
    this.stopLogin()
    this.stopDaemon()
    return { ok: true }
  }

  /**
   * A03: Logout completo — detiene daemon, limpia authDir y safeStorage.
   * Deja el transport listo para un nuevo escaneo QR.
   */
  clearSavedSession() {
    this._intentionalStop = true
    clearTimeout(this._restartTimer)
    this._restartTimer = null
    this._restartAttempts = 0
    this._needsFreshLogin = true
    this._linked = false
    this._phoneNumber = null
    try {
      this._sendWorkerCmd({ cmd: 'stop' })
      this._worker?.kill('SIGTERM')
    } catch {
      // ignore
    }
    this._worker = null
    this._clearAuthDir()
    this._clearPersistedCreds()
    this._connectionState = 'idle'
    this._lastError = 'Vuelve a escanear el código.'
    this._emitStatus()
    this._debugLog('clearSavedSession: sesión WhatsApp completamente limpiada')
    return { ok: true }
  }

  /**
   * A03: Intenta restaurar sesión WhatsApp desde safeStorage sin pasar por QR.
   * @returns {{ ok: boolean; needs_qr?: boolean; linked?: boolean; phone_number?: string | null; error?: string }}
   */
  async restoreSession() {
    this._debugLog('restoreSession: intentando restaurar desde safeStorage')

    if (this.isDaemonRunning() && this._linked) {
      return { ok: true, needs_qr: false, linked: true, phone_number: this._phoneNumber }
    }

    // Si ya hay credenciales locales, solo arrancar el daemon
    if (!this._hasLocalCreds()) {
      const restored = this._restoreCredsFromSafeStorage()
      if (!restored) {
        this._needsFreshLogin = true
        this._linked = false
        this._connectionState = 'disconnected'
        this._lastError = 'Vuelve a escanear el código.'
        this._emitStatus()
        return { ok: false, needs_qr: true, linked: false, error: 'no_saved_creds' }
      }
    }

    // Credenciales presentes (locales o restauradas): arrancar daemon
    this._needsFreshLogin = false
    this._linked = true
    this._intentionalStop = false
    this.ensureOwnPhone(null)

    const result = await this.startDaemon('restore_session')
    if (!result.ok) {
      this._connectionState = 'disconnected'
      this._lastError = result.error || 'restore_start_failed'
      this._emitStatus()
      return {
        ok: false,
        needs_qr: true,
        linked: false,
        phone_number: this._phoneNumber,
        error: result.error || 'daemon_start_failed',
      }
    }

    return { ok: true, needs_qr: false, linked: true, phone_number: this._phoneNumber }
  }

  shutdown() {
    this._intentionalStop = true
    clearTimeout(this._restartTimer)
    this._restartTimer = null
    this.stopAll()
  }

  getStatus() {
    const configured = this._hasLocalCreds()
    return {
      state: this._connectionState,
      connectionState: this._connectionState,
      linked: this._linked,
      configured,
      daemonRunning: this.isDaemonRunning(),
      loginRunning: this.isLoginRunning(),
      phone_number: this._phoneNumber,
      error: this._lastError,
      lastError: this._lastError,
      needsFreshLogin: this._needsFreshLogin || !configured,
      restartAttempts: this._restartAttempts,
      transport: 'baileys',
    }
  }

  onStatusChange(listener) {
    this._statusListeners.add(listener)
    return () => this._statusListeners.delete(listener)
  }

  isLoginRunning() {
    return this._loginPhase
  }

  isDaemonRunning() {
    return this._worker !== null && this._worker.exitCode === null && !this._worker.killed
  }

  async sendMessage(to, text) {
    if (!this.isDaemonRunning()) {
      const started = await this.startDaemon('send')
      if (!started.ok) return { ok: false, error: started.error || 'daemon_not_running' }
    }

    const requestId = `s${++this._sendSeq}`
    return new Promise((resolve) => {
      const timer = setTimeout(() => {
        this._pendingSends.delete(requestId)
        resolve({ ok: false, error: 'send_timeout' })
      }, 45_000)

      this._pendingSends.set(requestId, {
        resolve: (result) => {
          clearTimeout(timer)
          resolve(result)
        },
      })

      const ok = this._sendWorkerCmd({
        cmd: 'send',
        request_id: requestId,
        to: String(to || ''),
        text: String(text || ''),
      })
      if (!ok) {
        clearTimeout(timer)
        this._pendingSends.delete(requestId)
        resolve({ ok: false, error: 'worker_not_ready' })
      }
    })
  }

  /**
   * Envía imagen o documento por WhatsApp (W09).
   * @param {string} to
   * @param {string} filePath - Ruta absoluta ya validada en sandbox
   * @param {{ mediaType?: 'image' | 'document'; caption?: string; mimetype?: string; fileName?: string }} [opts]
   * @returns {Promise<{ ok: boolean; message_id?: string; error?: string }>}
   */
  async sendMedia(to, filePath, opts = {}) {
    if (!this.isDaemonRunning()) {
      const started = await this.startDaemon('send_media')
      if (!started.ok) return { ok: false, error: started.error || 'daemon_not_running' }
    }

    const requestId = `m${++this._sendSeq}`
    return new Promise((resolve) => {
      const timer = setTimeout(() => {
        this._pendingSends.delete(requestId)
        resolve({ ok: false, error: 'send_timeout' })
      }, 90_000)

      this._pendingSends.set(requestId, {
        resolve: (result) => {
          clearTimeout(timer)
          resolve(result)
        },
      })

      const ok = this._sendWorkerCmd({
        cmd: 'send_media',
        request_id: requestId,
        to: String(to || ''),
        file_path: String(filePath || ''),
        media_type: String(opts.mediaType || 'document'),
        caption: String(opts.caption || ''),
        mimetype: opts.mimetype ? String(opts.mimetype) : undefined,
        file_name: opts.fileName ? String(opts.fileName) : undefined,
      })
      if (!ok) {
        clearTimeout(timer)
        this._pendingSends.delete(requestId)
        resolve({ ok: false, error: 'worker_not_ready' })
      }
    })
  }

  onInboundMessage(callback) {
    this._inboundForwarder = typeof callback === 'function' ? callback : async () => {}
  }

  onMediaDownloaded(callback) {
    this._mediaDownloadedForwarder = typeof callback === 'function' ? callback : () => {}
    return () => {
      this._mediaDownloadedForwarder = () => {}
    }
  }

  async bootstrap(opts = {}) {
    if (this.isDaemonRunning()) {
      return {
        ok: true,
        started: false,
        configured: true,
        linked: this._linked,
        phone_number: this._phoneNumber,
      }
    }

    // A03: si no hay credenciales locales, intentar restaurar desde safeStorage
    if (!this._hasLocalCreds()) {
      const restored = this._restoreCredsFromSafeStorage()
      if (restored) {
        this._debugLog('bootstrap: credenciales restauradas desde safeStorage')
      }
    }

    const probe = await this.probeConfigured()
    if (!probe.configured && !opts.force) {
      this._debugLog('bootstrap: sin credenciales Baileys locales')
      this._linked = false
      this._phoneNumber = null
      this._needsFreshLogin = true
      this._setConnectionState('disconnected')
      this._lastError = 'Vuelve a escanear el código.'
      return {
        ok: true,
        started: false,
        configured: false,
        linked: false,
        phone_number: null,
        needsFreshLogin: true,
      }
    }
    // Creds locales ⇒ sesión emparejada; el socket aún no está vivo hasta startDaemon OK.
    this._linked = true
    this.ensureOwnPhone(null)
    const result = await this.startDaemon('boot')
    if (!result.ok) {
      // A3: no reportar "linked feliz" si el daemon no arrancó.
      this._setConnectionState('disconnected')
      this._lastError = result.error || 'bootstrap_start_failed'
      return {
        ...result,
        started: false,
        configured: true,
        linked: true,
        phone_number: this._phoneNumber,
        connectionState: this._connectionState,
      }
    }
    return {
      ...result,
      started: true,
      configured: true,
      linked: true,
      phone_number: this._phoneNumber,
      connectionState: this._connectionState,
    }
  }

  async probeConfigured() {
    const configured = this._hasLocalCreds()
    return {
      configured,
      raw: configured ? '{"provider":"baileys","configured":true}' : undefined,
    }
  }

  ensureOwnPhone(hint) {
    const fromHint = normalizePhoneE164(hint || '') || (hint ? String(hint) : null)
    if (fromHint) this._phoneNumber = fromHint
    if (!this._phoneNumber) {
      this._phoneNumber = this._readPhoneFromCreds()
    }
    return this._phoneNumber
  }

  applyPolicy() {
    // Política DOT/grupo: OpenClaw-specific; Baileys usa reply-policy en capas superiores.
    return { ok: true, changed: false, mode: 'baileys' }
  }

  warmup() {
    // Baileys no necesita pre-calentar OpenClaw CLI.
  }
}

module.exports = { BaileysTransport, resolveAuthDir }
