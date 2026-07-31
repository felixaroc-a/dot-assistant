'use strict'

/**
 * BaileysEngine — Motor WhatsApp independiente para Electron (M1S1-A).
 *
 * Engine autónomo para pruebas. NO reemplaza openclaw; funciona en paralelo.
 * Conecta directamente a WhatsApp vía @whiskeysockets/baileys.
 *
 * API:
 *   const engine = require('./baileys-engine.cjs')
 *   await engine.start(authDir)        // conecta, emite QR si necesario
 *   engine.stop()                      // cierra conexión
 *   await engine.sendMessage(jid, text)// envía mensaje
 *   engine.onMessage(callback)         // registra callback para mensajes entrantes
 *   engine.getStatus()                 // 'disconnected' | 'connecting' | 'connected'
 *   engine.onStatusChange(callback)    // registra callback para cambios de estado
 *   engine.onQR(callback)              // registra callback para código QR
 *
 * Persistencia: sesión guardada en authDir vía useMultiFileAuthState.
 * Reconexión: automática con keepAliveIntervalMs: 30000.
 */

const EventEmitter = require('node:events')
const fs = require('node:fs')
const path = require('node:path')
const os = require('node:os')

// ─── Dependencias ──────────────────────────────────────────────
let baileys
try {
  baileys = require('@whiskeysockets/baileys')
} catch (err) {
  throw new Error(
    `@whiskeysockets/baileys no está instalado. Ejecuta: npm install @whiskeysockets/baileys\n` +
      `Error: ${err instanceof Error ? err.message : String(err)}`,
  )
}

const makeWASocket = baileys.default?.makeWASocket || baileys.makeWASocket
const {
  useMultiFileAuthState,
  DisconnectReason,
  fetchLatestBaileysVersion,
  Browsers,
  jidNormalizedUser,
  makeCacheableSignalKeyStore,
} = baileys

// ─── Logger silencioso (pino) ─────────────────────────────────
let pino
try {
  pino = require('pino')
} catch {
  pino = {
    default: () => ({
      child: () => pino.default(),
      info: () => {},
      error: () => {},
      warn: () => {},
      debug: () => {},
      trace: () => {},
      silent: () => {},
      level: 'silent',
    }),
  }
}

// ─── Motor ────────────────────────────────────────────────────

/** @type {import('@whiskeysockets/baileys').WASocket | null} */
let sock = null

/** @type {'disconnected' | 'connecting' | 'connected'} */
let status = 'disconnected'

/** @type {string} */
let ownPhone = ''

/** @type {string} */
let ownJid = ''

/** @type {boolean} */
let shuttingDown = false

/** @type {number} */
let reconnectAttempts = 0

/** @type {ReturnType<typeof setTimeout> | null} */
let reconnectTimer = null

/** @type {string} */
let authDir = path.join(os.homedir(), '.dot', 'whatsapp-baileys-engine')

/** @type {Function | null} */
let credsSaveFn = null

// Event emitters
const engineEvents = new EventEmitter()
engineEvents.setMaxListeners(50)

// ─── Funciones auxiliares ─────────────────────────────────────

/**
 * Normaliza un número a formato E.164 (+58..., sin espacios).
 * Usa la utilidad compartida si existe.
 */
function normalizePhoneE164(raw) {
  try {
    const phoneUtils = require('./phone-utils.cjs')
    return phoneUtils.normalizePhoneE164(raw) || null
  } catch {
    // Fallback básico
    const digits = String(raw || '').replace(/\D/g, '')
    if (!digits) return null
    // Asume +58 si empieza con 0 o tiene < 10 dígitos
    if (digits.startsWith('0')) return `+58${digits.slice(1)}`
    if (digits.length <= 10) return `+58${digits}`
    return `+${digits}`
  }
}

/**
 * Extrae el teléfono de un JID de WhatsApp.
 */
function phoneFromJid(jid) {
  const raw = String(jid || '').trim()
  if (!raw || raw === 'status@broadcast') return null
  if (raw.includes('@lid') || raw.endsWith('@lid')) return null
  const user = (raw.split('@')[0] || '').split(':')[0]
  return normalizePhoneE164(user)
}

/**
 * Convierte un destino (número o JID) a JID válido para Baileys.
 */
function toJid(to) {
  const raw = String(to || '').trim()
  if (!raw) return null
  if (raw.includes('@')) return jidNormalizedUser(raw)
  const e164 = normalizePhoneE164(raw)
  const digits = String(e164 || raw).replace(/\D/g, '')
  if (!digits) return null
  return `${digits}@s.whatsapp.net`
}

/**
 * Extrae texto de un mensaje de WhatsApp.
 */
function extractText(message) {
  if (!message || typeof message !== 'object') return ''
  if (typeof message.conversation === 'string') return message.conversation
  if (message.extendedTextMessage?.text) return String(message.extendedTextMessage.text)
  if (message.imageMessage?.caption) return String(message.imageMessage.caption)
  if (message.videoMessage?.caption) return String(message.videoMessage.caption)
  if (message.documentMessage?.caption) return String(message.documentMessage.caption)
  if (message.buttonsResponseMessage?.selectedDisplayText) {
    return String(message.buttonsResponseMessage.selectedDisplayText)
  }
  if (message.listResponseMessage?.title) return String(message.listResponseMessage.title)
  return ''
}

// ─── Core: start / stop ───────────────────────────────────────

/**
 * Inicia la conexión a WhatsApp.
 *
 * @param {string} [customAuthDir] - Directorio para persistir la sesión.
 *   Por defecto: ~/.dot/whatsapp-baileys-engine
 * @returns {Promise<{ ok: boolean; status: string; qr?: string; phone?: string; error?: string }>}
 */
async function start(customAuthDir) {
  if (sock) {
    return { ok: true, status, phone: ownPhone || undefined, message: 'already_running' }
  }

  // Configurar authDir
  if (customAuthDir) {
    authDir = String(customAuthDir).trim()
  }
  fs.mkdirSync(authDir, { recursive: true })

  shuttingDown = false
  setStatus('connecting')

  try {
    // ─── Auth state ──────────────────────────────────────────
    const { state, saveCreds } = await useMultiFileAuthState(authDir)
    credsSaveFn = saveCreds

    // ─── Versión de Baileys ─────────────────────────────────
    let version
    try {
      const latest = await fetchLatestBaileysVersion()
      version = latest.version
    } catch {
      version = undefined
    }

    // ─── Browser fingerprint ────────────────────────────────
    const browser =
      typeof Browsers.appropriate === 'function'
        ? Browsers.appropriate('Chrome')
        : Browsers.windows('Chrome')

    // ─── Crear socket ───────────────────────────────────────
    sock = makeWASocket({
      version,
      auth: {
        creds: state.creds,
        keys: makeCacheableSignalKeyStore(state.keys, pino.default?.({ level: 'silent' }) || pino),
      },
      logger: pino.default?.({ level: 'silent' }) || pino,
      browser,
      syncFullHistory: false,
      markOnlineOnConnect: false,
      printQRInTerminal: false,
      keepAliveIntervalMs: 30_000,
      getMessage: async () => undefined,
    })

    // ─── Eventos ─────────────────────────────────────────────
    setupEvents()

    return { ok: true, status: 'connecting' }
  } catch (err) {
    const message = err instanceof Error ? err.message : String(err)
    setStatus('disconnected')
    sock = null
    return { ok: false, error: message, status: 'disconnected' }
  }
}

/**
 * Configura los event handlers del socket Baileys.
 */
function setupEvents() {
  if (!sock) return

  // Credenciales
  sock.ev.on('creds.update', (creds) => {
    if (credsSaveFn) {
      try {
        credsSaveFn()
      } catch {
        // ignore
      }
    }
  })

  // Conexión
  sock.ev.on('connection.update', (update) => {
    const { connection, lastDisconnect, qr } = update

    // ─── QR ─────────────────────────────────────────────────
    if (qr) {
      engineEvents.emit('qr', String(qr))
      setStatus('connecting')
    }

    // ─── Conectando ─────────────────────────────────────────
    if (connection === 'connecting') {
      setStatus('connecting')
    }

    // ─── Abierto ────────────────────────────────────────────
    if (connection === 'open') {
      reconnectAttempts = 0
      const meId = sock?.user?.id || ''
      ownJid = meId
      ownPhone = phoneFromJid(meId) || ''
      setStatus('connected')
      engineEvents.emit('ready', { phone: ownPhone, jid: ownJid })
    }

    // ─── Cerrado ────────────────────────────────────────────
    if (connection === 'close') {
      const statusCode =
        lastDisconnect?.error instanceof Error && 'output' in lastDisconnect.error
          ? /** @type {{ output?: { statusCode?: number } }} */ (lastDisconnect.error).output
              ?.statusCode
          : undefined

      const loggedOut = statusCode === DisconnectReason.loggedOut

      if (loggedOut) {
        // Sesión cerrada por WhatsApp
        cleanAuthDir()
        setStatus('disconnected')
        engineEvents.emit('logged_out')
        sock = null
        return
      }

      if (shuttingDown) {
        setStatus('disconnected')
        sock = null
        return
      }

      // Reconexión automática
      setStatus('connecting')
      reconnectAttempts += 1

      if (reconnectAttempts > 12) {
        setStatus('disconnected')
        engineEvents.emit('error', new Error('Reintentos de reconexión agotados'))
        sock = null
        return
      }

      const delay = Math.min(30_000, 1_500 * reconnectAttempts)
      if (reconnectTimer) clearTimeout(reconnectTimer)
      reconnectTimer = setTimeout(() => {
        reconnectTimer = null
        void attemptReconnect()
      }, delay)
    }
  })

  // Mensajes entrantes
  sock.ev.on('messages.upsert', ({ messages, type }) => {
    if (type !== 'notify') return

    for (const msg of messages || []) {
      try {
        if (!msg?.message) continue

        const remoteJid = String(msg.key?.remoteJid || '')
        if (!remoteJid || remoteJid === 'status@broadcast') continue

        const fromMe = Boolean(msg.key?.fromMe)
        const isGroup = remoteJid.endsWith('@g.us')

        // Enviar evento con el mensaje parseado
        engineEvents.emit('message', {
          message_id: String(msg.key?.id || ''),
          from_phone: fromMe ? ownPhone : phoneFromJid(msg.key?.remoteJid || '') || '',
          to_phone: ownPhone,
          text: extractText(msg.message),
          timestamp: new Date(
            Number(msg.messageTimestamp || 0) * 1000 || Date.now(),
          ).toISOString(),
          is_group: isGroup,
          chat_jid: remoteJid,
          from_me: fromMe,
          raw: msg,
        })
      } catch (err) {
        // Ignorar errores de parseo individual
      }
    }
  })
}

/**
 * Intenta reconectar el socket.
 */
async function attemptReconnect() {
  if (shuttingDown || sock) return

  try {
    await start(authDir)
  } catch {
    // La reconexión se maneja en connection.update
  }
}

// ─── Core: stop ───────────────────────────────────────────────

/**
 * Cierra la conexión a WhatsApp.
 */
function stop() {
  shuttingDown = true

  if (reconnectTimer) {
    clearTimeout(reconnectTimer)
    reconnectTimer = null
  }

  reconnectAttempts = 0

  if (sock) {
    try {
      sock.end?.(undefined)
    } catch {
      // ignore
    }
    sock = null
  }

  setStatus('disconnected')
}

/**
 * Logout completo: cierra conexión y borra credenciales.
 */
async function logout() {
  shuttingDown = true

  if (reconnectTimer) {
    clearTimeout(reconnectTimer)
    reconnectTimer = null
  }

  reconnectAttempts = 0

  if (sock) {
    try {
      await sock.logout?.()
    } catch {
      // ignore
    }
    sock = null
  }

  cleanAuthDir()
  ownPhone = ''
  ownJid = ''
  setStatus('disconnected')
}

// ─── Core: sendMessage ────────────────────────────────────────

/**
 * Envía un mensaje de texto a un número o JID.
 *
 * @param {string} to - Número de teléfono (E.164 o local) o JID completo.
 * @param {string} text - Texto del mensaje.
 * @returns {Promise<{ ok: boolean; message_id?: string; error?: string }>}
 */
async function sendMessage(to, text) {
  if (!sock) {
    start(authDir)
    return { ok: false, error: 'socket_not_connected' }
  }

  const jid = toJid(to)
  const cleanText = String(text || '').trim()

  if (!jid) {
    return { ok: false, error: 'invalid_destination' }
  }

  if (!cleanText) {
    return { ok: false, error: 'empty_text' }
  }

  try {
    const result = await sock.sendMessage(jid, { text: cleanText })
    const messageId = result?.key?.id ? String(result.key.id) : undefined

    return {
      ok: true,
      message_id: messageId || undefined,
    }
  } catch (err) {
    return {
      ok: false,
      error: err instanceof Error ? err.message : String(err),
    }
  }
}

// ─── Core: getStatus ──────────────────────────────────────────

/**
 * Devuelve el estado actual de la conexión.
 *
 * @returns {'disconnected' | 'connecting' | 'connected'}
 */
function getStatus() {
  return status
}

/**
 * Devuelve información extendida del estado.
 *
 * @returns {{
 *   status: 'disconnected' | 'connecting' | 'connected',
 *   phone: string,
 *   jid: string,
 *   reconnectAttempts: number,
 *   shuttingDown: boolean,
 * }}
 */
function getStatusExtended() {
  return {
    status,
    phone: ownPhone,
    jid: ownJid,
    reconnectAttempts,
    shuttingDown,
  }
}

// ─── Core: eventos ────────────────────────────────────────────

/**
 * Registra un callback para mensajes entrantes.
 *
 * @param {(msg: {
 *   message_id: string,
 *   from_phone: string,
 *   to_phone: string,
 *   text: string,
 *   timestamp: string,
 *   is_group: boolean,
 *   chat_jid: string,
 *   from_me: boolean,
 *   raw: import('@whiskeysockets/baileys').WAMessage
 * }) => void} callback
 * @returns {() => void} Función para remover el listener.
 */
function onMessage(callback) {
  engineEvents.on('message', callback)
  return () => engineEvents.off('message', callback)
}

/**
 * Registra un callback para cambios de estado de conexión.
 *
 * @param {(newStatus: 'disconnected' | 'connecting' | 'connected') => void} callback
 * @returns {() => void} Función para remover el listener.
 */
function onStatusChange(callback) {
  engineEvents.on('status_change', callback)
  return () => engineEvents.off('status_change', callback)
}

/**
 * Registra un callback para recibir el código QR.
 *
 * @param {(qr: string) => void} callback
 * @returns {() => void} Función para remover el listener.
 */
function onQR(callback) {
  engineEvents.on('qr', callback)
  return () => engineEvents.off('qr', callback)
}

/**
 * Registra un callback para cuando el socket está listo (conectado).
 *
 * @param {(info: { phone: string; jid: string }) => void} callback
 * @returns {() => void} Función para remover el listener.
 */
function onReady(callback) {
  engineEvents.on('ready', callback)
  return () => engineEvents.off('ready', callback)
}

/**
 * Registra un callback para cuando la sesión es cerrada por WhatsApp (logged out).
 *
 * @param {() => void} callback
 * @returns {() => void} Función para remover el listener.
 */
function onLoggedOut(callback) {
  engineEvents.on('logged_out', callback)
  return () => engineEvents.off('logged_out', callback)
}

/**
 * Registra un callback para errores del engine.
 *
 * @param {(err: Error) => void} callback
 * @returns {() => void} Función para remover el listener.
 */
function onError(callback) {
  engineEvents.on('error', callback)
  return () => engineEvents.off('error', callback)
}

// ─── Utilidades ───────────────────────────────────────────────

/**
 * Actualiza el estado y emite evento.
 */
function setStatus(newStatus) {
  if (status !== newStatus) {
    status = newStatus
    engineEvents.emit('status_change', newStatus)
  }
}

/**
 * Limpia el directorio de credenciales (para logout).
 */
function cleanAuthDir() {
  try {
    if (!fs.existsSync(authDir)) return
    for (const name of fs.readdirSync(authDir)) {
      try {
        fs.rmSync(path.join(authDir, name), { recursive: true, force: true })
      } catch {
        // ignore archivo individual
      }
    }
  } catch {
    // ignore
  }
}

/**
 * Verifica si hay credenciales guardadas en disco.
 *
 * @returns {boolean}
 */
function hasSavedSession() {
  try {
    const credsPath = path.join(authDir, 'creds.json')
    if (!fs.existsSync(credsPath)) return false
    const raw = fs.readFileSync(credsPath, 'utf8')
    if (!raw || !raw.trim() || raw.charCodeAt(0) === 0) return false
    const parsed = JSON.parse(raw)
    return Boolean(parsed?.me?.id || parsed?.registered)
  } catch {
    return false
  }
}

// ─── Export ───────────────────────────────────────────────────

module.exports = {
  start,
  stop,
  logout,
  sendMessage,
  getStatus,
  getStatusExtended,
  onMessage,
  onStatusChange,
  onQR,
  onReady,
  onLoggedOut,
  onError,
  hasSavedSession,
  cleanAuthDir,
}
