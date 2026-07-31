/**
 * LocalToolsBridge — puente seguro para acciones locales en Windows.
 *
 * Proposito:
 * - Ejecutar operaciones de archivos, creacion de documentos y descargas
 *   desde la IA, con un modelo de permisos explicito.
 * - Sandbox con allowlist: Documents, Desktop, Downloads (rutas reales del SO, localizadas).
 * - Auditoria local de cada accion ejecutada.
 * - Sin ejecucion de comandos arbitrarios ni terminal.
 */
'use strict'

const fs = require('node:fs')
const path = require('node:path')
const os = require('node:os')
const { resolveSafePath: _sharedResolveSafePath, SANDBOX_HOME: SHARED_SANDBOX_HOME } = require('./sandbox-resolver.cjs')

// ============================================================
// Configuracion
// ============================================================

/** Ruta base del sandbox DOT (~/Documents/DOT): auditoria, permisos y directorio de trabajo por defecto */
const SANDBOX_HOME = SHARED_SANDBOX_HOME

/** Archivos de auditoria */
const AUDIT_LOG_PATH = path.join(SANDBOX_HOME, '.audit.jsonl')

/** Permisos persistidos */
const PERMISSIONS_PATH = path.join(SANDBOX_HOME, '.permissions.json')

const MAX_FILE_SIZE_BYTES = 50 * 1024 * 1024 // 50 MB
const MAX_FILES_PER_OPERATION = 10

// ============================================================
// Estado de permisos
// ============================================================

/** @type {Record<string, 'once' | 'always' | 'denied'>} */
let _permissions = {}

function _loadPermissions() {
  try {
    if (fs.existsSync(PERMISSIONS_PATH)) {
      _permissions = JSON.parse(fs.readFileSync(PERMISSIONS_PATH, 'utf-8'))
    }
  } catch {
    _permissions = {}
  }
}

function _savePermissions() {
  try {
    _ensureSandboxExists()
    fs.writeFileSync(PERMISSIONS_PATH, JSON.stringify(_permissions, null, 2), 'utf-8')
  } catch {
    // Si falla, mantener en memoria
  }
}

function _ensureSandboxExists() {
  if (!fs.existsSync(SANDBOX_HOME)) {
    fs.mkdirSync(SANDBOX_HOME, { recursive: true })
  }
}

_loadPermissions()

// ============================================================
// Validacion de rutas (sandbox multi-raíz, localizado al SO)
// ============================================================

/**
 * Verifica que la ruta solicitada esté dentro de alguna raíz permitida.
 * Delega en sandbox-resolver.cjs (módulo compartido con document-parser.cjs).
 *
 * @param {string} relativePath - Ruta a validar
 * @returns {string | null} Ruta absoluta normalizada, o null si no es segura
 */
function _resolveSafePath(relativePath) {
  return _sharedResolveSafePath(relativePath)
}

// ============================================================
// Modelo de permisos
// ============================================================

/**
 * Verifica si una accion esta permitida.
 * Si no hay decision previa, la accion requiere confirmacion UI.
 */
function _checkPermission(actionId) {
  const status = _permissions[actionId]
  if (status === 'always') return 'allowed'
  if (status === 'denied') return 'denied'
  if (status === 'once') {
    delete _permissions[actionId]
    _savePermissions()
    return 'allowed'
  }
  return 'requires_confirmation'
}

/**
 * Guarda una decision de permiso.
 */
function _setPermission(actionId, decision) {
  if (!['once', 'always', 'denied'].includes(decision)) return
  _permissions[actionId] = decision
  _savePermissions()
}

// ============================================================
// Auditoria
// ============================================================

function _audit(action, details) {
  try {
    _ensureSandboxExists()
    const entry = JSON.stringify({
      timestamp: new Date().toISOString(),
      action,
      details,
    })
    fs.appendFileSync(AUDIT_LOG_PATH, entry + '\n', 'utf-8')
  } catch {
    // Auditoria silenciosa
  }
}

// ============================================================
// Acciones de herramientas locales
// ============================================================

/**
 * Lee el contenido de un archivo dentro del sandbox.
 */
function readFile(relativePath) {
  const safePath = _resolveSafePath(relativePath)
  if (!safePath) {
    return { ok: false, error: 'Ruta fuera del sandbox permitido.' }
  }

  try {
    if (!fs.existsSync(safePath)) {
      return { ok: false, error: 'El archivo no existe.' }
    }
    const stat = fs.statSync(safePath)
    if (stat.size > MAX_FILE_SIZE_BYTES) {
      return { ok: false, error: 'El archivo excede el tamano maximo permitido (50 MB).' }
    }
    const content = fs.readFileSync(safePath, 'utf-8')
    _audit('read_file', { path: relativePath, size: stat.size })
    return { ok: true, content, path: safePath }
  } catch (err) {
    return { ok: false, error: err.message }
  }
}

/**
 * Lee bytes de un archivo dentro del sandbox (base64) para adjuntos binarios.
 */
function readFileBytes(relativePath) {
  const safePath = _resolveSafePath(relativePath)
  if (!safePath) {
    return { ok: false, error: 'Ruta fuera del sandbox permitido.' }
  }

  try {
    if (!fs.existsSync(safePath)) {
      return { ok: false, error: 'El archivo no existe.' }
    }
    const stat = fs.statSync(safePath)
    if (stat.size > MAX_FILE_SIZE_BYTES) {
      return { ok: false, error: 'El archivo excede el tamano maximo permitido (50 MB).' }
    }
    const buffer = fs.readFileSync(safePath)
    _audit('read_file_bytes', { path: relativePath, size: stat.size })
    return {
      ok: true,
      content_base64: buffer.toString('base64'),
      path: safePath,
      bytes: stat.size,
    }
  } catch (err) {
    return { ok: false, error: err.message }
  }
}

function writeFileBytes(relativePath, contentBase64) {
  const safePath = _resolveSafePath(relativePath)
  if (!safePath) {
    return { ok: false, error: 'Ruta fuera del sandbox permitido.' }
  }

  const rawB64 = String(contentBase64 || '').trim()
  if (!rawB64) {
    return { ok: false, error: 'Contenido base64 vacío.' }
  }

  let buffer
  try {
    buffer = Buffer.from(rawB64, 'base64')
  } catch {
    return { ok: false, error: 'Base64 inválido.' }
  }
  if (!buffer.length) {
    return { ok: false, error: 'Archivo vacío.' }
  }
  if (buffer.length > MAX_FILE_SIZE_BYTES) {
    return { ok: false, error: 'El archivo excede el tamano maximo permitido (50 MB).' }
  }

  try {
    const dir = path.dirname(safePath)
    if (!fs.existsSync(dir)) {
      fs.mkdirSync(dir, { recursive: true })
    }
    fs.writeFileSync(safePath, buffer)
    _audit('write_file_bytes', { path: relativePath, size: buffer.length })
    return { ok: true, path: safePath, bytes: buffer.length }
  } catch (err) {
    return { ok: false, error: err.message }
  }
}

/**
 * Escribe contenido en un archivo dentro del sandbox.
 * Crea directorios intermedios si no existen.
 */
const BINARY_WRITE_EXTS = new Set([
  '.pdf',
  '.png',
  '.jpg',
  '.jpeg',
  '.gif',
  '.webp',
  '.zip',
  '.exe',
  '.docx',
  '.xlsx',
  '.pptx',
])

function writeFile(relativePath, content) {
  const safePath = _resolveSafePath(relativePath)
  if (!safePath) {
    return { ok: false, error: 'Ruta fuera del sandbox permitido.' }
  }

  if (typeof content !== 'string') {
    return { ok: false, error: 'Contenido invalido.' }
  }

  const { isFullDiskAccessEnabled } = require('./sandbox-resolver.cjs')
  if (!isFullDiskAccessEnabled()) {
    const lower = String(relativePath || '').toLowerCase()
    for (const ext of BINARY_WRITE_EXTS) {
      if (lower.endsWith(ext)) {
        return {
          ok: false,
          error:
            'No uses writeFile para PDF/imágenes/binarios. Usa downloadUrlToDesktop con la URL http/https.',
        }
      }
    }
  }

  if (Buffer.byteLength(content, 'utf-8') > MAX_FILE_SIZE_BYTES) {
    return { ok: false, error: 'El contenido excede el tamano maximo permitido (50 MB).' }
  }

  try {
    const dir = path.dirname(safePath)
    if (!fs.existsSync(dir)) {
      fs.mkdirSync(dir, { recursive: true })
    }
    fs.writeFileSync(safePath, content, 'utf-8')
    _audit('write_file', { path: relativePath, size: Buffer.byteLength(content, 'utf-8') })
    return { ok: true, path: safePath }
  } catch (err) {
    return { ok: false, error: err.message }
  }
}

/**
 * Lista archivos en un directorio dentro del sandbox.
 */
function listFiles(relativePath) {
  const safePath = _resolveSafePath(relativePath || '')
  if (!safePath) {
    return { ok: false, error: 'Ruta fuera del sandbox permitido.' }
  }

  try {
    if (!fs.existsSync(safePath)) {
      return { ok: true, files: [], path: safePath }
    }
    const entries = fs.readdirSync(safePath, { withFileTypes: true })
    const files = entries.map((entry) => ({
      name: entry.name,
      isDirectory: entry.isDirectory(),
      path: entry.name,
    }))
    _audit('list_files', { path: relativePath, count: files.length })
    return { ok: true, files, path: safePath }
  } catch (err) {
    return { ok: false, error: err.message }
  }
}

/**
 * Elimina un archivo dentro del sandbox.
 */
function deleteFile(relativePath) {
  const safePath = _resolveSafePath(relativePath)
  if (!safePath) {
    return { ok: false, error: 'Ruta fuera del sandbox permitido.' }
  }

  try {
    if (!fs.existsSync(safePath)) {
      return { ok: false, error: 'El archivo no existe.' }
    }
    const stat = fs.statSync(safePath)
    if (stat.isDirectory()) {
      return { ok: false, error: 'No se puede eliminar directorios con esta operacion.' }
    }
    fs.unlinkSync(safePath)
    _audit('delete_file', { path: relativePath })
    return { ok: true }
  } catch (err) {
    return { ok: false, error: err.message }
  }
}

// ============================================================
// Utilidades de informacion
// ============================================================

/**
 * Obtiene el historial de auditoria.
 */
function getAuditLog(limit = 50) {
  try {
    if (!fs.existsSync(AUDIT_LOG_PATH)) {
      return { ok: true, entries: [] }
    }
    const lines = fs.readFileSync(AUDIT_LOG_PATH, 'utf-8').split('\n').filter(Boolean)
    const entries = lines.slice(-limit).map((line) => {
      try {
        return JSON.parse(line)
      } catch {
        return null
      }
    }).filter(Boolean)
    return { ok: true, entries }
  } catch (err) {
    return { ok: false, error: err.message }
  }
}

/**
 * Obtiene el estado del sandbox.
 */
function getSandboxInfo() {
  const { getAllowedRoots } = require('./sandbox-resolver.cjs')
  return {
    homePath: SANDBOX_HOME,
    exists: fs.existsSync(SANDBOX_HOME),
    allowedRoots: getAllowedRoots(),
    fileCount: _countFiles(),
    auditCount: _countAuditEntries(),
  }
}

function _countFiles() {
  try {
    if (!fs.existsSync(SANDBOX_HOME)) return 0
    let count = 0
    function walk(dir) {
      const entries = fs.readdirSync(dir, { withFileTypes: true })
      for (const entry of entries) {
        const full = path.join(dir, entry.name)
        if (entry.isDirectory()) {
          walk(full)
        } else {
          count++
        }
      }
    }
    walk(SANDBOX_HOME)
    return count
  } catch {
    return 0
  }
}

function _countAuditEntries() {
  try {
    if (!fs.existsSync(AUDIT_LOG_PATH)) return 0
    const content = fs.readFileSync(AUDIT_LOG_PATH, 'utf-8')
    return content.split('\n').filter(Boolean).length
  } catch {
    return 0
  }
}

// ============================================================
// API de permisos
// ============================================================

function getPermissionStatus(actionId) {
  return _checkPermission(actionId)
}

function setPermission(actionId, decision) {
  _setPermission(actionId, decision)
  _audit('permission_set', { actionId, decision })
  return { ok: true }
}

function resetAllPermissions() {
  _permissions = {}
  _savePermissions()
  return { ok: true }
}

/**
 * Modo privilegiado (BIBLIA §20): potencia extendida capa B con consentimiento GUI.
 * Nunca habilita shell / capa C.
 */
function isPrivilegedMode() {
  return _checkPermission('privileged') === 'allowed'
}

/**
 * Navegador web (capa B): solo con permiso explícito «DOT puede usar webs».
 * El Modo privilegiado no sustituye este permiso (solo amplía acceso a disco).
 */
function canUseBrowserTools() {
  return _checkPermission('browser') === 'allowed'
}

/**
 * Descarga una URL http(s) al Escritorio/Descargas dentro del sandbox.
 * Bloquea file://, hosts locales y tamaño excesivo.
 */
function downloadUrlToDesktop(url, destRelativePath) {
  const MAX_DOWNLOAD_BYTES = 25 * 1024 * 1024 // 25 MB
  const rawUrl = String(url || '').trim()
  if (!rawUrl) {
    return { ok: false, error: 'URL vacía.' }
  }

  let parsed
  try {
    parsed = new URL(rawUrl)
  } catch {
    return { ok: false, error: 'URL inválida.' }
  }

  if (parsed.protocol !== 'http:' && parsed.protocol !== 'https:') {
    return { ok: false, error: 'Solo se permiten URLs http/https (no file://).' }
  }

  const host = (parsed.hostname || '').toLowerCase()
  if (
    host === 'localhost' ||
    host === '127.0.0.1' ||
    host === '::1' ||
    host.endsWith('.local') ||
    host.startsWith('10.') ||
    host.startsWith('192.168.') ||
    /^172\.(1[6-9]|2\d|3[0-1])\./.test(host) ||
    host === '0.0.0.0' ||
    host === 'metadata.google.internal'
  ) {
    return { ok: false, error: 'Host no permitido (red interna/local).' }
  }

  let dest = String(destRelativePath || '').trim()
  if (!dest) {
    const base = path.basename(parsed.pathname || '') || `dot-download-${Date.now()}.bin`
    const safeName = base.replace(/[<>:"|?*\x00-\x1f]/g, '_').slice(0, 120)
    dest = `~/Desktop/${safeName}`
  }

  const safePath = _resolveSafePath(dest)
  if (!safePath) {
    return { ok: false, error: 'Ruta destino fuera del sandbox permitido.' }
  }

  const lib = parsed.protocol === 'https:' ? require('node:https') : require('node:http')

  return new Promise((resolve) => {
    const req = lib.get(rawUrl, { timeout: 60000 }, (res) => {
      if (res.statusCode && res.statusCode >= 300 && res.statusCode < 400 && res.headers.location) {
        res.resume()
        downloadUrlToDesktop(res.headers.location, dest).then(resolve)
        return
      }
      if (!res.statusCode || res.statusCode < 200 || res.statusCode >= 300) {
        res.resume()
        resolve({ ok: false, error: `HTTP ${res.statusCode || 'error'}` })
        return
      }

      const chunks = []
      let total = 0
      res.on('data', (chunk) => {
        total += chunk.length
        if (total > MAX_DOWNLOAD_BYTES) {
          req.destroy()
          resolve({ ok: false, error: 'Archivo demasiado grande (máx. 25 MB).' })
          return
        }
        chunks.push(chunk)
      })
      res.on('end', () => {
        try {
          const dir = path.dirname(safePath)
          if (!fs.existsSync(dir)) {
            fs.mkdirSync(dir, { recursive: true })
          }
          const buf = Buffer.concat(chunks)
          const destLower = safePath.toLowerCase()
          if (destLower.endsWith('.pdf') && !buf.slice(0, 5).toString('latin1').startsWith('%PDF')) {
            resolve({
              ok: false,
              error: 'La URL no devolvió un PDF válido (falta cabecera %PDF).',
            })
            return
          }
          fs.writeFileSync(safePath, buf)
          _audit('download_url', { url: rawUrl, path: dest, size: buf.length })
          resolve({ ok: true, path: safePath, bytes: buf.length })
        } catch (err) {
          resolve({ ok: false, error: err.message })
        }
      })
    })
    req.on('timeout', () => {
      req.destroy()
      resolve({ ok: false, error: 'Timeout al descargar.' })
    })
    req.on('error', (err) => {
      resolve({ ok: false, error: err.message })
    })
  })
}

// ============================================================
// Export
// ============================================================

module.exports = {
  readFile,
  readFileBytes,
  writeFile,
  writeFileBytes,
  listFiles,
  deleteFile,
  downloadUrlToDesktop,
  getAuditLog,
  getSandboxInfo,
  getPermissionStatus,
  setPermission,
  resetAllPermissions,
  isPrivilegedMode,
  canUseBrowserTools,
  SANDBOX_HOME,
}
