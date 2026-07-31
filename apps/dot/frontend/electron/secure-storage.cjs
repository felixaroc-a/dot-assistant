const { app, safeStorage } = require('electron')
const fs = require('node:fs')
const path = require('node:path')

const SESSION_FILE = 'dot_secure_session_v1.dat'
const OAUTH_SUBJECT_FILE = 'dot_oauth_subject_v1.dat'
/** Huella local del serial del pendrive usado en el último login (SHA-256 hex, no serial en claro). */
const HARDWARE_BIND_FILE = 'dot_hardware_bind_v1.dat'
const RECOVERY_KEY_FILE = 'dot_recovery_key_v1.dat'
/** A03: credenciales Baileys persistidas para sobrevivir reinicios de Electron sin re-escanear QR. */
const WHATSAPP_CREDS_FILE = 'whatsapp_creds_v1.dat'

function storageDir() {
  return path.join(app.getPath('userData'), 'secure')
}

function filePath(name) {
  return path.join(storageDir(), name)
}

function ensureDir() {
  const dir = storageDir()
  if (!fs.existsSync(dir)) {
    fs.mkdirSync(dir, { recursive: true })
  }
}

function canEncrypt() {
  try {
    return safeStorage.isEncryptionAvailable()
  } catch {
    return false
  }
}

function writeEncrypted(name, plainText) {
  ensureDir()
  const fp = filePath(name)
  if (!plainText) {
    if (fs.existsSync(fp)) fs.unlinkSync(fp)
    return { ok: true, encrypted: canEncrypt() }
  }
  if (canEncrypt()) {
    const buf = safeStorage.encryptString(plainText)
    fs.writeFileSync(fp, buf)
    return { ok: true, encrypted: true }
  }
  return {
    ok: false,
    encrypted: false,
    error: 'SAFE_STORAGE_UNAVAILABLE',
    warning: 'safeStorage no disponible; sesion bloqueada para evitar datos sin cifrar.',
  }
}

function readEncrypted(name) {
  const fp = filePath(name)
  if (!fs.existsSync(fp)) return null
  const buf = fs.readFileSync(fp)
  if (canEncrypt()) {
    try {
      return safeStorage.decryptString(buf)
    } catch {
      return null
    }
  }
  return null
}

function saveSession(json) {
  return writeEncrypted(SESSION_FILE, json)
}

function loadSession() {
  return readEncrypted(SESSION_FILE)
}

function clearSession() {
  return writeEncrypted(SESSION_FILE, '')
}

function saveOAuthSubject(id) {
  return writeEncrypted(OAUTH_SUBJECT_FILE, id)
}

function loadOAuthSubject() {
  return readEncrypted(OAUTH_SUBJECT_FILE)
}

function saveHardwareBind(fingerprintHex) {
  if (typeof fingerprintHex !== 'string' || !/^[a-f0-9]{64}$/i.test(fingerprintHex)) {
    return { ok: false }
  }
  return writeEncrypted(HARDWARE_BIND_FILE, fingerprintHex.toLowerCase())
}

function loadHardwareBind() {
  const raw = readEncrypted(HARDWARE_BIND_FILE)
  if (!raw) return null
  const trimmed = raw.trim().toLowerCase()
  return /^[a-f0-9]{64}$/.test(trimmed) ? trimmed : null
}

function clearHardwareBind() {
  return writeEncrypted(HARDWARE_BIND_FILE, '')
}

function saveRecoveryKey(recoveryKey) {
  return writeEncrypted(RECOVERY_KEY_FILE, recoveryKey)
}

function loadRecoveryKey() {
  return readEncrypted(RECOVERY_KEY_FILE)
}

// ─── A03: WhatsApp credential persistence ──────────────────
function saveWhatsAppCreds(credsJson) {
  return writeEncrypted(WHATSAPP_CREDS_FILE, credsJson)
}

function loadWhatsAppCreds() {
  return readEncrypted(WHATSAPP_CREDS_FILE)
}

function clearWhatsAppCreds() {
  return writeEncrypted(WHATSAPP_CREDS_FILE, '')
}

module.exports = {
  saveSession,
  loadSession,
  clearSession,
  saveOAuthSubject,
  loadOAuthSubject,
  saveHardwareBind,
  loadHardwareBind,
  clearHardwareBind,
  saveRecoveryKey,
  loadRecoveryKey,
  canEncrypt,
  saveWhatsAppCreds,
  loadWhatsAppCreds,
  clearWhatsAppCreds,
}
