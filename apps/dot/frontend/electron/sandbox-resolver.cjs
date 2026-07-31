/**
 * sandbox-resolver.cjs — Resolvedor de rutas con sandbox multi-raíz.
 *
 * Por defecto (producción / sin flag): solo
 *   - ~/Documents/DOT/
 *   - ~/Documents/
 *   - ~/Desktop/ (Escritorio)
 *   - ~/Downloads/ (Descargas)
 *
 * Modo abierto (DEV): DOT_FULL_DISK_ACCESS=1 o DOT_DEMO_MODE=1
 *   → cualquier ruta absoluta del PC (perfil + unidades).
 *   Ignorado si Electron está empaquetado (app.isPackaged).
 */
'use strict'

const fs = require('node:fs')
const path = require('node:path')
const os = require('node:os')

/** Ruta base del sandbox DOT (~/Documents/DOT) */
const SANDBOX_HOME = path.join(os.homedir(), 'Documents', 'DOT')

let _allowedRoots = null

/**
 * Acceso completo al disco solo en desarrollo (nunca empaquetado)
 * O cuando el usuario activa Privileged Mode desde la GUI (actionId=privileged).
 * @returns {boolean}
 */
function isFullDiskAccessEnabled() {
  try {
    const electronApp = require('electron').app
    if (electronApp && electronApp.isPackaged) return false
  } catch {
    // tests / fuera de Electron: respetar env
  }
  const v = String(process.env.DOT_FULL_DISK_ACCESS || '').trim()
  const demo = String(process.env.DOT_DEMO_MODE || '').trim()
  if (v === '1' || demo === '1') return true
  
  // B6: Privileged Mode ON → acceso ampliado al disco
  try {
    const permFile = path.join(SANDBOX_HOME, '.permissions.json')
    if (fs.existsSync(permFile)) {
      const perms = JSON.parse(fs.readFileSync(permFile, 'utf-8'))
      if (perms.privileged === 'always') return true
    }
  } catch {
    // Si falla la lectura de permisos, mantener restricción
  }
  return false
}

function _initAllowedRoots() {
  try {
    const electronApp = require('electron').app
    if (electronApp.isReady()) {
      const electronRoots = [
        SANDBOX_HOME,
        electronApp.getPath('documents'),
        electronApp.getPath('desktop'),
        electronApp.getPath('downloads'),
        electronApp.getPath('pictures'),
        electronApp.getPath('music'),
        electronApp.getPath('videos'),
      ]
      const same =
        Array.isArray(_allowedRoots) &&
        _allowedRoots.length === electronRoots.length &&
        _allowedRoots.every((root, idx) => root === electronRoots[idx])
      if (!same) {
        _allowedRoots = electronRoots
      }
      return
    }
  } catch {
    // No estamos en Electron (tests) o aún no ready
  }

  if (_allowedRoots) return

  const oneDrive = process.env.OneDrive || process.env.OneDriveConsumer || ''
  let desktop = path.join(os.homedir(), 'Desktop')
  let documents = path.join(os.homedir(), 'Documents')
  let downloads = path.join(os.homedir(), 'Downloads')

  // ─── Linux: respetar XDG directorios de usuario ─────────
  if (process.platform === 'linux') {
    const xdgDesktop = process.env.XDG_DESKTOP_DIR
    const xdgDocuments = process.env.XDG_DOCUMENTS_DIR
    const xdgDownloads = process.env.XDG_DOWNLOAD_DIR
    if (xdgDesktop && fs.existsSync(xdgDesktop)) desktop = xdgDesktop
    if (xdgDocuments && fs.existsSync(xdgDocuments)) documents = xdgDocuments
    if (xdgDownloads && fs.existsSync(xdgDownloads)) downloads = xdgDownloads
  }

  try {
    const candidates = {
      desktop: [
        oneDrive ? path.join(oneDrive, 'Escritorio') : null,
        oneDrive ? path.join(oneDrive, 'Desktop') : null,
        path.join(os.homedir(), 'Escritorio'),
        path.join(os.homedir(), 'Desktop'),
      ],
      documents: [
        oneDrive ? path.join(oneDrive, 'Documentos') : null,
        oneDrive ? path.join(oneDrive, 'Documents') : null,
        path.join(os.homedir(), 'Documentos'),
        path.join(os.homedir(), 'Documents'),
      ],
      downloads: [
        oneDrive ? path.join(oneDrive, 'Descargas') : null,
        oneDrive ? path.join(oneDrive, 'Downloads') : null,
        path.join(os.homedir(), 'Descargas'),
        path.join(os.homedir(), 'Downloads'),
      ],
    }
    for (const candidate of candidates.desktop) {
      if (candidate && fs.existsSync(candidate)) {
        desktop = candidate
        break
      }
    }
    for (const candidate of candidates.documents) {
      if (candidate && fs.existsSync(candidate)) {
        documents = candidate
        break
      }
    }
    for (const candidate of candidates.downloads) {
      if (candidate && fs.existsSync(candidate)) {
        downloads = candidate
        break
      }
    }
  } catch {
    // mantener fallback inglés
  }

  _allowedRoots = [SANDBOX_HOME, documents, desktop, downloads]
}

/**
 * @param {string} relativePath
 * @returns {string | null}
 */
function resolveSafePath(relativePath) {
  if (typeof relativePath !== 'string') {
    return null
  }
  if (relativePath.includes('\0')) {
    return null
  }

  _initAllowedRoots()

  const trimmed = relativePath.trim()
  const fullDisk = isFullDiskAccessEnabled()

  if (!trimmed) {
    return SANDBOX_HOME
  }

  let resolved

  if (trimmed.startsWith('~/') || trimmed === '~') {
    const homeRelative = trimmed.slice(2)
    const normalizedHome = homeRelative.replace(/\\/g, '/')

    const firstSlash = normalizedHome.indexOf('/')
    const firstSegmentRaw = firstSlash >= 0 ? normalizedHome.slice(0, firstSlash) : normalizedHome
    const firstSegment = firstSegmentRaw.toLowerCase()
    const restParts = firstSlash >= 0 ? normalizedHome.slice(firstSlash + 1) : ''

    const desktopRoot = _allowedRoots[2]
    const documentsRoot = _allowedRoots[1]
    const downloadsRoot = _allowedRoots[3]

    if (firstSegment === 'desktop' || firstSegment === 'escritorio') {
      resolved = restParts ? path.join(desktopRoot, restParts) : desktopRoot
    } else if (firstSegment === 'downloads' || firstSegment === 'descargas') {
      resolved = restParts ? path.join(downloadsRoot, restParts) : downloadsRoot
    } else if (firstSegment === 'documents' || firstSegment === 'documentos') {
      resolved = restParts ? path.join(documentsRoot, restParts) : documentsRoot
    } else {
      resolved = path.resolve(os.homedir(), normalizedHome.split('/').join(path.sep))
    }
  } else if (path.isAbsolute(trimmed)) {
    resolved = path.resolve(trimmed)
  } else {
    // Relativos siempre bajo Documentos/DOT (comportamiento histórico)
    resolved = path.resolve(SANDBOX_HOME, trimmed)
  }

  resolved = path.normalize(resolved)

  if (fullDisk) {
    // Cualquier ruta absoluta válida en el sistema (dev / demo).
    // Tras path.resolve no hay ".." pendientes.
    return resolved
  }

  const isAllowed = _allowedRoots.some((root) => {
    const normalizedRoot = path.resolve(root)
    return resolved === normalizedRoot || resolved.startsWith(normalizedRoot + path.sep)
  })

  if (!isAllowed) {
    return null
  }

  return resolved
}

function getAllowedRoots() {
  _initAllowedRoots()
  if (isFullDiskAccessEnabled()) {
    return ['*FULL_DISK*', ..._allowedRoots]
  }
  return [..._allowedRoots]
}

module.exports = {
  resolveSafePath,
  getAllowedRoots,
  isFullDiskAccessEnabled,
  SANDBOX_HOME,
}
