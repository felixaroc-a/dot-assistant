'use strict'

/**
 * Proceso hijo Baileys (ELECTRON_RUN_AS_NODE).
 * Protocolo NDJSON por stdout; comandos por stdin.
 *
 * Eventos → padre:
 *   { type: 'ready' }
 *   { type: 'qr', qr: string }
 *   { type: 'status', state, detail? }
 *   { type: 'linked', phone_number }
 *   { type: 'message', ...inbound }
 *   { type: 'send_result', request_id, ok, message_id?, error? }
 *   { type: 'error', error }
 *   { type: 'log', message }
 *
 * Comandos ← padre:
 *   { cmd: 'ping' }
 *   { cmd: 'send', request_id, to, text }
 *   { cmd: 'send_media', request_id, to, file_path, media_type, caption?, mimetype?, file_name? }
 *   { cmd: 'stop' }
 *   { cmd: 'logout' }
 *
 * T13: mensajes con media llegan con has_media=true; download deferred.
 * W09: envío outbound de imagen/documento vía send_media.
 */

const fs = require('node:fs')
const path = require('node:path')

const baileys = require('@whiskeysockets/baileys')
const makeWASocket = baileys.default || baileys.makeWASocket
const {
  useMultiFileAuthState,
  DisconnectReason,
  fetchLatestBaileysVersion,
  Browsers,
  jidNormalizedUser,
  downloadMediaMessage,
} = baileys
const pino = require('pino')
const { normalizePhoneE164: normalizePhoneE164Shared } = require('../phone-utils.cjs')

const authDir = String(process.argv[2] || '').trim()
if (!authDir) {
  process.stderr.write('[baileys-worker] authDir requerido\n')
  process.exit(2)
}

fs.mkdirSync(authDir, { recursive: true })

/** @type {import('@whiskeysockets/baileys').WASocket | null} */
const { textMentionsDot } = require('../reply-policy.cjs')

let sock = null
let shuttingDown = false
let ownPhone = null
let reconnectAttempts = 0
/** Evita eco: outbound DOT (fromMe) no debe reentrar como inbound. */
const recentlySentIds = new Set()
const MAX_RECENT_SENT = 200
/** Mismo tope que local-tools sandbox (50 MB). */
const MAX_MEDIA_BYTES = 50 * 1024 * 1024

function rememberSentId(messageId) {
  const id = String(messageId || '').trim()
  if (!id) return
  recentlySentIds.add(id)
  if (recentlySentIds.size > MAX_RECENT_SENT) {
    const first = recentlySentIds.values().next().value
    if (first) recentlySentIds.delete(first)
  }
}

function emit(payload) {
  try {
    process.stdout.write(`${JSON.stringify(payload)}\n`)
  } catch {
    // ignore
  }
}

function normalizePhoneE164(raw) {
  return normalizePhoneE164Shared(raw) || null
}

function phoneFromJid(jid) {
  const raw = String(jid || '').trim()
  if (!raw || raw === 'status@broadcast') return null
  // Ignorar LIDs de WhatsApp (@lid): no son E.164.
  if (raw.includes('@lid') || raw.endsWith('@lid')) return null
  const user = (raw.split('@')[0] || '').split(':')[0]
  return normalizePhoneE164(user)
}

/**
 * Remitente real: Baileys a veces manda LID en participant y el PN en participantAlt/Pn.
 * @param {import('@whiskeysockets/baileys').WAMessage} msg
 * @param {boolean} isGroup
 */
function resolveSenderPhone(msg, isGroup) {
  const key = msg?.key || {}
  if (!isGroup) {
    return (
      phoneFromJid(key.remoteJidAlt || '') ||
      phoneFromJid(key.remoteJid || '') ||
      rawJidUser(key.remoteJid || '') ||
      null
    )
  }
  return (
    phoneFromJid(key.participantAlt || '') ||
    phoneFromJid(key.participantPn || '') ||
    phoneFromJid(key.participant || '') ||
    rawJidUser(key.participantAlt || key.participantPn || key.participant || '') ||
    null
  )
}

function rawJidUser(jid) {
  const raw = String(jid || '').trim()
  if (!raw) return null
  const user = (raw.split('@')[0] || '').split(':')[0].replace(/\D/g, '')
  return user || null
}

/** @type {Map<string, string>} */
const groupSubjectCache = new Map()

async function resolveGroupSubject(remoteJid) {
  const cached = groupSubjectCache.get(remoteJid)
  if (cached) return cached
  if (!sock) return ''
  try {
    const meta = await sock.groupMetadata(remoteJid)
    const subject = String(meta?.subject || '').trim()
    if (subject) groupSubjectCache.set(remoteJid, subject)
    return subject
  } catch (err) {
    emit({
      type: 'log',
      message: `groupMetadata fail: ${err instanceof Error ? err.message : String(err)}`,
    })
    return ''
  }
}

function toJid(to) {
  const raw = String(to || '').trim()
  if (!raw) return null
  if (raw.includes('@')) return jidNormalizedUser(raw)
  // 0412… / 412… → +58…; sin esto Baileys "envía" a un JID inválido y nadie recibe.
  const e164 = normalizePhoneE164(raw)
  const digits = String(e164 || raw).replace(/\D/g, '')
  if (!digits) return null
  return `${digits}@s.whatsapp.net`
}

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

function hasMediaPayload(message) {
  if (!message || typeof message !== 'object') return false
  return Boolean(
    message.imageMessage ||
      message.videoMessage ||
      message.audioMessage ||
      message.documentMessage ||
      message.stickerMessage,
  )
}

function isAudioMessage(message) {
  return Boolean(message && typeof message === 'object' && message.audioMessage)
}

function isImageMessage(message) {
  return Boolean(
    message &&
      typeof message === 'object' &&
      (message.imageMessage || message.stickerMessage),
  )
}

function isDocumentMessage(message) {
  return Boolean(message && typeof message === 'object' && message.documentMessage)
}

function isVideoMessage(message) {
  return Boolean(message && typeof message === 'object' && message.videoMessage)
}

/** Máximo inline base64 para notas de voz (5 MB). */
const MAX_VOICE_INLINE_BYTES = 5 * 1024 * 1024
/** Máximo inline base64 para imagen/documento (10 MB). */
const MAX_MEDIA_INLINE_BYTES = 10 * 1024 * 1024

// ─── T13: media download ──────────────────────────────────
function resolveMediaDir() {
  try {
    const { app } = require('electron')
    if (app && typeof app.getPath === 'function') {
      return path.join(app.getPath('downloads'), 'DOT-Media')
    }
  } catch {
    // fuera de Electron
  }
  return path.join(authDir, '..', 'DOT-Media')
}

/**
 * @param {string} mimeType
 * @returns {string} Extensión de archivo o '.bin'
 */
function mimeFromPath(filePath) {
  const ext = path.extname(String(filePath || '')).toLowerCase()
  const map = {
    '.jpg': 'image/jpeg',
    '.jpeg': 'image/jpeg',
    '.png': 'image/png',
    '.webp': 'image/webp',
    '.gif': 'image/gif',
    '.pdf': 'application/pdf',
    '.docx': 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
    '.xlsx': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
    '.zip': 'application/zip',
    '.txt': 'text/plain',
    '.mp4': 'video/mp4',
    '.mp3': 'audio/mpeg',
  }
  return map[ext] || 'application/octet-stream'
}

function extensionFromMime(mimeType) {
  const map = {
    'image/jpeg': '.jpg',
    'image/png': '.png',
    'image/webp': '.webp',
    'image/gif': '.gif',
    'video/mp4': '.mp4',
    'video/3gpp': '.3gp',
    'audio/ogg': '.opus',
    'audio/mpeg': '.mp3',
    'audio/mp4': '.m4a',
    'audio/aac': '.aac',
    'application/pdf': '.pdf',
    'application/vnd.openxmlformats-officedocument.wordprocessingml.document': '.docx',
    'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet': '.xlsx',
    'application/zip': '.zip',
    'text/plain': '.txt',
  }
  return map[mimeType] || '.bin'
}

/**
 * Descarga y guarda un mensaje con media en disco.
 * @param {import('@whiskeysockets/baileys').proto.IWebMessageInfo} msg
 * @returns {Promise<{ ok: boolean; filePath?: string; mimeType?: string; size?: number; error?: string }>}
 */
async function downloadAndSaveMedia(msg) {
  try {
    const buffer = await downloadMediaMessage(
      msg,
      'buffer',
      {},
      {
        logger: pino({ level: 'silent' }),
        reuploadRequest: sock?.updateMediaMessage
          ? (updatedMsg) => sock.updateMediaMessage(updatedMsg)
          : undefined,
      },
    )

    const mime = msg.message?.imageMessage?.mimetype ||
      msg.message?.videoMessage?.mimetype ||
      msg.message?.audioMessage?.mimetype ||
      msg.message?.documentMessage?.mimetype ||
      msg.message?.stickerMessage?.mimetype ||
      'application/octet-stream'

    const ext = extensionFromMime(String(mime || ''))
    const ts = new Date(Number(msg.messageTimestamp || 0) * 1000 || Date.now())
    const datePart = ts.toISOString().replace(/:/g, '-').replace(/\.\d+Z$/, '')
    const senderJid = String(msg.key?.remoteJid || 'unknown').split('@')[0]
    const fileName = `DOT-${datePart}_${senderJid.slice(0, 15)}${ext}`

    const dir = resolveMediaDir()
    fs.mkdirSync(dir, { recursive: true })
    const filePath = path.join(dir, fileName)
    fs.writeFileSync(filePath, buffer)

    return {
      ok: true,
      filePath,
      mimeType: String(mime),
      size: buffer.byteLength || buffer.length,
    }
  } catch (err) {
    return {
      ok: false,
      error: err instanceof Error ? err.message : String(err),
    }
  }
}
// ─── fin T13 ──────────────────────────────────────────────

async function startSocket() {
  const { state, saveCreds } = await useMultiFileAuthState(authDir)
  let version
  try {
    const latest = await fetchLatestBaileysVersion()
    version = latest.version
  } catch {
    version = undefined
  }

  // WhatsApp rechaza fingerprints custom (p.ej. 'DOT'): el teléfono muestra
  // "no se pueden vincular nuevos dispositivos" mientras web.whatsapp.com sí funciona.
  // Hay que presentarse como Chrome/WA Web oficial.
  const browser =
    typeof Browsers.appropriate === 'function'
      ? Browsers.appropriate('Chrome')
      : Browsers.windows('Chrome')

  sock = makeWASocket({
    version,
    auth: state,
    logger: pino({ level: 'silent' }),
    browser,
    syncFullHistory: false,
    markOnlineOnConnect: false,
    printQRInTerminal: false,
    getMessage: async () => undefined,
  })

  sock.ev.on('creds.update', saveCreds)

  sock.ev.on('connection.update', (update) => {
    const { connection, lastDisconnect, qr } = update

    if (qr) {
      emit({ type: 'qr', qr: String(qr) })
      emit({ type: 'status', state: 'logging_in', detail: 'qr' })
    }

    if (connection === 'connecting') {
      emit({ type: 'status', state: 'starting', detail: 'connecting' })
    }

    if (connection === 'open') {
      reconnectAttempts = 0
      const meId = sock?.user?.id || state.creds?.me?.id || ''
      ownPhone = phoneFromJid(meId)
      emit({ type: 'status', state: 'connected' })
      emit({
        type: 'linked',
        phone_number: ownPhone || undefined,
        jid: meId || undefined,
      })
      emit({ type: 'log', message: `sesion abierta phone=${ownPhone || '?'}` })
    }

    if (connection === 'close') {
      const statusCode =
        lastDisconnect?.error instanceof Error && 'output' in lastDisconnect.error
          ? /** @type {{ output?: { statusCode?: number } }} */ (lastDisconnect.error).output
              ?.statusCode
          : undefined
      const loggedOut = statusCode === DisconnectReason.loggedOut
      emit({
        type: 'status',
        state: 'disconnected',
        detail: loggedOut ? 'logged_out' : `close_${statusCode || 'unknown'}`,
      })

      if (shuttingDown || loggedOut) {
        emit({ type: 'log', message: loggedOut ? 'sesion cerrada (logout)' : 'worker detenido' })
        process.exit(loggedOut ? 0 : 0)
        return
      }

      reconnectAttempts += 1
      if (reconnectAttempts > 12) {
        emit({ type: 'error', error: 'Reintentos de reconexión agotados.' })
        process.exit(1)
        return
      }

      emit({ type: 'log', message: `reconectando intento=${reconnectAttempts}` })
      setTimeout(() => {
        void startSocket().catch((err) => {
          emit({ type: 'error', error: err instanceof Error ? err.message : String(err) })
          process.exit(1)
        })
      }, Math.min(30_000, 1_500 * reconnectAttempts))
    }
  })

  sock.ev.on('messages.upsert', async ({ messages }) => {
    for (const msg of messages || []) {
      try {
        const remoteJidEarly = String(msg.key?.remoteJid || '')
        const msgId = String(msg.key?.id || '')
        const fromMe = Boolean(msg.key?.fromMe)

        // fromMe: solo comandos del dueño en grupos (mención DOT).
        // Sin esto, escribir desde el mismo WhatsApp vinculado nunca llega al backend.
        // Las respuestas outbound de DOT se marcan en recentlySentIds → skip (anti-loop).
        if (fromMe) {
          if (msgId && recentlySentIds.has(msgId)) {
            emit({
              type: 'log',
              message: `inbound skip fromMe outbound-echo id=${msgId}`,
            })
            continue
          }
          if (!remoteJidEarly.endsWith('@g.us')) {
            emit({
              type: 'log',
              message: `inbound skip fromMe not_group jid=${remoteJidEarly}`,
            })
            continue
          }
        }

        if (!msg?.message) continue
        const remoteJid = remoteJidEarly
        if (!remoteJid || remoteJid === 'status@broadcast') continue

        const isGroup = remoteJid.endsWith('@g.us')
        let fromPhone = resolveSenderPhone(msg, isGroup) || ''
        if (fromMe && ownPhone) {
          fromPhone = ownPhone
        }
        const text = extractText(msg.message)
        const media = hasMediaPayload(msg.message)
        const isVoiceNote = isAudioMessage(msg.message)
        const isImage = isImageMessage(msg.message)
        const isDocument = isDocumentMessage(msg.message)
        const isVideo = isVideoMessage(msg.message)

        if (fromMe) {
          if (!textMentionsDot(text || '')) {
            emit({
              type: 'log',
              message: `inbound skip fromMe mention_missing jid=${remoteJid}`,
            })
            continue
          }
        }

        if (!text && !media) {
          emit({
            type: 'log',
            message: `inbound skip empty jid=${remoteJid} from=${fromPhone}`,
          })
          continue
        }

        let groupSubject = ''
        if (isGroup) {
          groupSubject = await resolveGroupSubject(remoteJid)
        }

        // B07/B08: descargar media inline antes de emitir (voz, imagen, documento)
        /** @type {Record<string, unknown>} */
        const mediaPayload = {}
        if (isVoiceNote || isImage || isDocument) {
          const mediaResult = await downloadAndSaveMedia(msg)
          emit({
            type: 'media_downloaded',
            message_id: String(msg.key?.id || ''),
            ok: mediaResult.ok,
            file_path: mediaResult.filePath || undefined,
            mime_type: mediaResult.mimeType || undefined,
            size: mediaResult.size || undefined,
            error: mediaResult.error || undefined,
          })
          if (mediaResult.ok && mediaResult.filePath) {
            try {
              const mediaBuffer = fs.readFileSync(mediaResult.filePath)
              const maxInline = isVoiceNote ? MAX_VOICE_INLINE_BYTES : MAX_MEDIA_INLINE_BYTES
              if (mediaBuffer.length >= 64 && mediaBuffer.length <= maxInline) {
                mediaPayload.media_mime_type = mediaResult.mimeType || 'application/octet-stream'
                mediaPayload.media_data_base64 = mediaBuffer.toString('base64')
                if (isVoiceNote) mediaPayload.has_audio = true
                if (isImage) mediaPayload.has_image = true
                if (isDocument) {
                  mediaPayload.has_document = true
                  const docName = msg.message?.documentMessage?.fileName
                  if (docName) mediaPayload.media_filename = String(docName)
                }
              } else {
                emit({
                  type: 'log',
                  message: `media skip inline kind=${isVoiceNote ? 'voice' : isImage ? 'image' : 'doc'} size=${mediaBuffer.length}`,
                })
              }
            } catch (readErr) {
              emit({
                type: 'log',
                message: `media read fail: ${readErr instanceof Error ? readErr.message : String(readErr)}`,
              })
            }
          }
        }

        emit({
          type: 'log',
          message: `inbound emit jid=${remoteJid} from=${fromPhone} chars=${(text || '').length} group=${groupSubject || ''} voice=${Boolean(mediaPayload.has_audio)} image=${Boolean(mediaPayload.has_image)} doc=${Boolean(mediaPayload.has_document)}`,
        })
        emit({
          type: 'message',
          message_id: String(msg.key?.id || ''),
          from_phone: fromPhone,
          to_phone: ownPhone || '',
          text: text || (media ? '[media]' : ''),
          timestamp: new Date(
            Number(msg.messageTimestamp || 0) * 1000 || Date.now(),
          ).toISOString(),
          is_group: isGroup,
          chat_jid: remoteJid,
          group_name: groupSubject || (isGroup ? remoteJid : ''),
          group_subject: groupSubject,
          has_media: media,
          ...mediaPayload,
        })

        // Video u otro media sin inline: guardar en DOT-Media en segundo plano.
        if (media && isVideo && !isVoiceNote && !isImage && !isDocument) {
          const result = await downloadAndSaveMedia(msg)
          emit({
            type: 'media_downloaded',
            message_id: String(msg.key?.id || ''),
            ok: result.ok,
            file_path: result.filePath || undefined,
            mime_type: result.mimeType || undefined,
            size: result.size || undefined,
            error: result.error || undefined,
          })
        }
      } catch (err) {
        emit({
          type: 'log',
          message: `inbound parse error: ${err instanceof Error ? err.message : String(err)}`,
        })
      }
    }
  })
}

async function handleSend(cmd) {
  const requestId = cmd.request_id
  try {
    if (!sock) throw new Error('Socket Baileys no iniciado')
    const jid = toJid(cmd.to)
    const text = String(cmd.text || '').trim()
    if (!jid || !text) throw new Error('Destino y texto son obligatorios.')
    const result = await sock.sendMessage(jid, { text })
    const sentId = result?.key?.id ? String(result.key.id) : undefined
    if (sentId) rememberSentId(sentId)
    emit({
      type: 'send_result',
      request_id: requestId,
      ok: true,
      message_id: sentId,
    })
  } catch (err) {
    emit({
      type: 'send_result',
      request_id: requestId,
      ok: false,
      error: err instanceof Error ? err.message : String(err),
    })
  }
}

async function handleSendMedia(cmd) {
  const requestId = cmd.request_id
  try {
    if (!sock) throw new Error('Socket Baileys no iniciado')
    const jid = toJid(cmd.to)
    const filePath = String(cmd.file_path || '').trim()
    const mediaType = String(cmd.media_type || 'document').trim().toLowerCase()
    const caption = String(cmd.caption || '').trim()
    if (!jid) throw new Error('Destino obligatorio.')
    if (!filePath) throw new Error('Ruta de archivo obligatoria.')
    if (!fs.existsSync(filePath)) throw new Error('Archivo no encontrado.')
    const stat = fs.statSync(filePath)
    if (!stat.isFile()) throw new Error('La ruta no es un archivo.')
    if (stat.size <= 0) throw new Error('El archivo está vacío.')
    if (stat.size > MAX_MEDIA_BYTES) {
      throw new Error('El archivo excede el tamaño máximo permitido (50 MB).')
    }

    const buffer = fs.readFileSync(filePath)
    const mimetype = String(cmd.mimetype || mimeFromPath(filePath))
    const fileName = String(cmd.file_name || path.basename(filePath))

    let payload
    if (mediaType === 'image') {
      payload = { image: buffer, mimetype }
      if (caption) payload.caption = caption
    } else if (mediaType === 'voice' || mediaType === 'voice_note' || mediaType === 'audio') {
      payload = {
        audio: buffer,
        mimetype: mimetype.startsWith('audio/') ? mimetype : 'audio/mpeg',
        ptt: true,
      }
    } else {
      payload = { document: buffer, mimetype, fileName }
      if (caption) payload.caption = caption
    }

    const result = await sock.sendMessage(jid, payload)
    const sentId = result?.key?.id ? String(result.key.id) : undefined
    if (sentId) rememberSentId(sentId)
    emit({
      type: 'send_result',
      request_id: requestId,
      ok: true,
      message_id: sentId,
    })
  } catch (err) {
    emit({
      type: 'send_result',
      request_id: requestId,
      ok: false,
      error: err instanceof Error ? err.message : String(err),
    })
  }
}

function handleLine(line) {
  const trimmed = String(line || '').trim()
  if (!trimmed) return
  let cmd
  try {
    cmd = JSON.parse(trimmed)
  } catch {
    emit({ type: 'error', error: 'comando JSON inválido' })
    return
  }

  const name = String(cmd.cmd || '')
  if (name === 'ping') {
    emit({ type: 'ready', pong: true })
    return
  }
  if (name === 'send') {
    void handleSend(cmd)
    return
  }
  if (name === 'send_media') {
    void handleSendMedia(cmd)
    return
  }
  if (name === 'stop') {
    shuttingDown = true
    try {
      sock?.end?.(undefined)
    } catch {
      // ignore
    }
    process.exit(0)
    return
  }
  if (name === 'logout') {
    shuttingDown = true
    void (async () => {
      try {
        await sock?.logout?.()
      } catch {
        // ignore
      }
      process.exit(0)
    })()
    return
  }
}

let stdinBuffer = ''
process.stdin.setEncoding('utf8')
process.stdin.on('data', (chunk) => {
  stdinBuffer += String(chunk)
  const parts = stdinBuffer.split(/\r?\n/)
  stdinBuffer = parts.pop() || ''
  for (const part of parts) handleLine(part)
})

process.on('SIGTERM', () => {
  shuttingDown = true
  try {
    sock?.end?.(undefined)
  } catch {
    // ignore
  }
  process.exit(0)
})

void startSocket()
  .then(() => emit({ type: 'ready' }))
  .catch((err) => {
    emit({ type: 'error', error: err instanceof Error ? err.message : String(err) })
    process.exit(1)
  })
