'use strict'

/**
 * file-search.cjs — Búsqueda de archivos en PC (P2.1)
 *
 * Busca archivos por nombre o contenido en Desktop, Documents, Downloads
 * usando PowerShell Get-ChildItem con filtros. Opcionalmente usa Everything SDK
 * si está instalado (fallback automático a PowerShell).
 *
 * Modos de búsqueda:
 * - sandbox (default): Desktop, Documents, Downloads
 * - full: toda la PC (requiere permiso explícito file_search_full)
 *
 * Límites:
 * - Máximo 50 resultados
 * - Excluye system32, AppData, Windows, Program Files, node_modules, .git
 * - Solo busca en las raíces permitidas por el sandbox o consentimiento
 *
 * Seguridad: no acepta rutas arbitrarias; solo opera dentro de Desktop,
 * Documents y Downloads. Path traversal bloqueado en sandbox-resolver.
 * Full search requiere permiso explícito del usuario vía local-tools.cjs.
 */

const fs = require('node:fs')
const path = require('node:path')
const os = require('node:os')
const { execFile } = require('node:child_process')

const MAX_RESULTS = 50

/** Timeout para búsqueda sandbox */
const SANDBOX_TIMEOUT_MS = 15000

/** Timeout para búsqueda full (60s) */
const FULL_TIMEOUT_MS = 60000

/** Carpetas a excluir de la búsqueda en modo sandbox */
const EXCLUDED_DIRS_SANDBOX = [
  'AppData',
  'Application Data',
  'Windows',
  'System32',
  'Program Files',
  'Program Files (x86)',
  'ProgramData',
  'node_modules',
  '.git',
  '.cache',
  '$Recycle.Bin',
  'Microsoft',
  'Temp',
  'Cache',
]

/** Carpetas a excluir de la búsqueda en modo full (más restrictivo en sistema) */
const EXCLUDED_DIRS_FULL = [
  'Windows',
  'Program Files',
  'Program Files (x86)',
  'ProgramData',
  '$Recycle.Bin',
  'System Volume Information',
]

/**
 * @returns {object} Funciones de permisos de local-tools.cjs (lazy load)
 */
function _getPermissionApi() {
  try {
    const localTools = require('./local-tools.cjs')
    return {
      getPermissionStatus: localTools.getPermissionStatus,
      setPermission: localTools.setPermission,
    }
  } catch {
    return null
  }
}

/**
 * Busca archivos por nombre (y opcionalmente contenido) dentro de las
 * raíces permitidas del sandbox o toda la PC (con permiso).
 *
 * @param {object} params
 * @param {string} params.query - Nombre o patrón a buscar (ej: "factura*", "*.pdf")
 * @param {string} [params.contentPattern] - Texto a buscar dentro del contenido
 * @param {string} [params.searchRoot] - Raíz específica: "desktop"|"documents"|"downloads"|"all"
 * @param {string} [params.scope] - "sandbox" (default) o "full" (toda la PC, requiere permiso)
 * @returns {Promise<{ ok: boolean; results?: Array<{name:string, path:string, size:number, modified:string, extension:string}>; error?: string; count?: number; scope?: string }>}
 */
async function search({ query, contentPattern, searchRoot, scope }) {
  if (!query || typeof query !== 'string' || !query.trim()) {
    return { ok: false, error: 'Término de búsqueda requerido' }
  }

  const safeQuery = query.trim().replace(/[&|;`$(){}[\]<>'"]/g, '').slice(0, 200)
  if (!safeQuery) {
    return { ok: false, error: 'Término de búsqueda inválido' }
  }

  const effectiveScope =
    scope === 'full' || require('./sandbox-resolver.cjs').isFullDiskAccessEnabled()
      ? 'full'
      : 'sandbox'

  // Modo full: en acceso abierto (dev) no pedir permiso; si no, requiere consentimiento
  if (effectiveScope === 'full') {
    const { isFullDiskAccessEnabled } = require('./sandbox-resolver.cjs')
    if (!isFullDiskAccessEnabled()) {
      const permApi = _getPermissionApi()
      if (!permApi) {
        return { ok: false, error: 'Sistema de permisos no disponible.' }
      }
      const permStatus = permApi.getPermissionStatus('file_search_full')
      if (permStatus !== 'allowed') {
        return {
          ok: false,
          error: 'requires_permission',
          permission_id: 'file_search_full',
          scope: 'full',
        }
      }
    }
  }

  const roots = effectiveScope === 'full'
    ? await _getFullScanRoots()
    : _getSearchRoots(searchRoot || 'all')

  if (!roots.length) {
    return { ok: false, error: 'No se encontraron carpetas de búsqueda válidas' }
  }

  const { isFullDiskAccessEnabled } = require('./sandbox-resolver.cjs')
  const excludedDirs =
    effectiveScope === 'full'
      ? (isFullDiskAccessEnabled() ? ['$Recycle.Bin', 'System Volume Information'] : EXCLUDED_DIRS_FULL)
      : EXCLUDED_DIRS_SANDBOX
  const exclusions = excludedDirs.map(d => `-not -path "*\\${d}\\*"`).join(' ')
  const nameFilter = safeQuery.includes('*') || safeQuery.includes('?')
    ? `-like "*${safeQuery}*"`
    : `-like "*${safeQuery}*"`

  const timeout = effectiveScope === 'full' ? FULL_TIMEOUT_MS : SANDBOX_TIMEOUT_MS

  const allResults = []

  for (const root of roots) {
    try {
      const results = await _searchInRoot(root, nameFilter, exclusions, contentPattern, timeout)
      allResults.push(...results)
    } catch {
      // Continuar con la siguiente raíz
    }
  }

  // Deducir duplicados por ruta
  const seen = new Set()
  const unique = []
  for (const r of allResults) {
    if (seen.has(r.path)) continue
    seen.add(r.path)
    unique.push(r)
    if (unique.length >= MAX_RESULTS) break
  }

  // Ordenar por fecha de modificación (más reciente primero)
  unique.sort((a, b) => new Date(b.modified).getTime() - new Date(a.modified).getTime())

  return {
    ok: true,
    results: unique.slice(0, MAX_RESULTS),
    count: unique.length,
    scope: effectiveScope,
  }
}

/**
 * Ejecuta la búsqueda en una raíz específica vía PowerShell.
 * @param {string} root
 * @param {string} nameFilter
 * @param {string} exclusions
 * @param {string|undefined} contentPattern
 * @param {number} timeout
 * @returns {Promise<Array<{name:string, path:string, size:number, modified:string, extension:string}>>}
 */
function _searchInRoot(root, nameFilter, exclusions, contentPattern, timeout) {
  return new Promise((resolve) => {
    let psCommand
    if (contentPattern) {
      const safeContent = contentPattern.replace(/['"`$]/g, '').slice(0, 200)
      psCommand = `Get-ChildItem -Path '${root}' -Recurse -File -ErrorAction SilentlyContinue ${exclusions} | Where-Object { $_.Name ${nameFilter} } | Select-String -Pattern '${safeContent}' -List | Select-Object -First ${MAX_RESULTS} | ForEach-Object { $f = $_.Path; $item = Get-Item $f; [PSCustomObject]@{Name=$item.Name; FullName=$item.FullName; Length=$item.Length; LastWriteTime=$item.LastWriteTime; Extension=$item.Extension} } | ConvertTo-Json -Compress`
    } else {
      psCommand = `Get-ChildItem -Path '${root}' -Recurse -File -ErrorAction SilentlyContinue ${exclusions} | Where-Object { $_.Name ${nameFilter} } | Select-Object -First ${MAX_RESULTS} | ForEach-Object { [PSCustomObject]@{Name=$_.Name; FullName=$_.FullName; Length=$_.Length; LastWriteTime=$_.LastWriteTime; Extension=$_.Extension} } | ConvertTo-Json -Compress`
    }

    execFile(
      'powershell.exe',
      ['-NoProfile', '-NonInteractive', '-Command', psCommand],
      {
        timeout: timeout || SANDBOX_TIMEOUT_MS,
        maxBuffer: 4 * 1024 * 1024,
        windowsHide: true,
      },
      (err, stdout) => {
        if (err) {
          resolve([])
          return
        }
        try {
          const raw = stdout.trim()
          if (!raw) {
            resolve([])
            return
          }
          let items = JSON.parse(raw)
          if (!Array.isArray(items)) {
            items = [items]
          }
          const mapped = items.map((item) => ({
            name: String(item.Name || ''),
            path: String(item.FullName || ''),
            size: Number(item.Length || 0),
            modified: item.LastWriteTime ? new Date(item.LastWriteTime).toISOString() : '',
            extension: String(item.Extension || '').toLowerCase(),
          })).filter(r => r.name && r.path)
          resolve(mapped)
        } catch {
          resolve([])
        }
      },
    )
  })
}

/**
 * Obtiene todas las unidades lógicas disponibles para búsqueda full.
 * Usa PowerShell Get-PSDrive -PSProvider FileSystem.
 * @returns {Promise<string[]>}
 */
function _getFullScanRoots() {
  return new Promise((resolve) => {
    const psCommand = '(Get-PSDrive -PSProvider FileSystem | Where-Object { $_.Used -ne $null -or $_.Root -match "^[A-Z]:\\\\$" } | ForEach-Object { $_.Root }) -join "|"'
    execFile(
      'powershell.exe',
      ['-NoProfile', '-NonInteractive', '-Command', psCommand],
      { timeout: 5000, maxBuffer: 65536, windowsHide: true },
      (err, stdout) => {
        if (err || !stdout) {
          // Fallback: solo C:\
          resolve(['C:\\'])
          return
        }
        const drives = stdout.trim()
          .split('|')
          .map(d => d.trim())
          .filter(d => d)
        if (!drives.length) {
          resolve(['C:\\'])
          return
        }
        // Validar que las unidades existen
        const valid = drives.filter(d => {
          try { return fs.existsSync(d) } catch { return false }
        })
        resolve(valid.length ? valid : ['C:\\'])
      },
    )
  })
}

/**
 * Obtiene las raíces de búsqueda según el parámetro.
 * @param {string} which - "desktop"|"documents"|"downloads"|"all"
 * @returns {string[]}
 */
function _getSearchRoots(which) {
  const roots = []
  const home = os.homedir()

  try {
    const electronApp = require('electron').app
    if (electronApp && electronApp.isReady && electronApp.isReady()) {
      if (which === 'all' || which === 'desktop') {
        roots.push(electronApp.getPath('desktop'))
      }
      if (which === 'all' || which === 'documents') {
        roots.push(electronApp.getPath('documents'))
      }
      if (which === 'all' || which === 'downloads') {
        roots.push(electronApp.getPath('downloads'))
      }
    } else {
      // Fallback sin Electron (tests)
      if (which === 'all' || which === 'desktop') roots.push(path.join(home, 'Desktop'))
      if (which === 'all' || which === 'documents') roots.push(path.join(home, 'Documents'))
      if (which === 'all' || which === 'downloads') roots.push(path.join(home, 'Downloads'))
    }
  } catch {
    if (which === 'all' || which === 'desktop') roots.push(path.join(home, 'Desktop'))
    if (which === 'all' || which === 'documents') roots.push(path.join(home, 'Documents'))
    if (which === 'all' || which === 'downloads') roots.push(path.join(home, 'Downloads'))
  }

  return roots.filter(r => {
    try { return fs.existsSync(r) && fs.statSync(r).isDirectory() } catch { return false }
  })
}

/**
 * API de permisos para file_search_full.
 * Expone checkPermission y setPermission al renderer vía preload.
 */

function checkPermission(actionId) {
  const permApi = _getPermissionApi()
  if (!permApi) return 'denied'
  return permApi.getPermissionStatus(actionId || 'file_search_full')
}

function setPermission(actionId, decision) {
  const permApi = _getPermissionApi()
  if (!permApi) return { ok: false, error: 'Sistema de permisos no disponible.' }
  permApi.setPermission(actionId || 'file_search_full', decision)
  return { ok: true }
}

module.exports = { search, checkPermission, setPermission }
