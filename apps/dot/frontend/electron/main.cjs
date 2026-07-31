require('./load-backend-env.cjs')

const fs = require('node:fs')
const path = require('node:path')
const { app, BrowserWindow, Notification, dialog, ipcMain, nativeTheme, shell, session, Tray, Menu, nativeImage } = require('electron')
// autoUpdater se carga bajo demanda en configureAutoUpdater (evita crash con ESM)

/** Detección de plataforma para gating de features específicas del SO */
const PLATFORM = process.platform
const IS_MAC = PLATFORM === 'darwin'
const IS_WIN = PLATFORM === 'win32'
const IS_LINUX = PLATFORM === 'linux'

const secureStorage = require('./secure-storage.cjs')
const localTools = require('./local-tools.cjs')
const { attachDevToolsProtection } = require('./security.cjs')
const usbSerial = require('./usb-serial.cjs')
const pendriveGate = require('./pendrive-gate.cjs')
const pendriveCrypto = require('./pendrive-crypto.cjs')
// auto-launch: solo Windows (registro HKCU\Run)
const autoLaunch = IS_WIN ? require('./auto-launch.cjs') : null
const whatsappService = require('./api/whatsapp-service.cjs')
const { getTransport } = require('./whatsapp/transport/index.cjs')
const localDb = require('./local-db.cjs')
const jobScheduler = require('./job-scheduler.cjs')
const codeExecutor = require('./code-executor.cjs')
const registerIpcHandlers = require('./ipc-handlers.cjs')
const { createBackgroundNotifyPoller } = require('./background-notify-poller.cjs')

/** Dev mode: true solo si no hay archivos compilados localmente */
const distIndex = path.join(__dirname, '..', 'dist', 'index.html')
const hasLocalBuild = fs.existsSync(distIndex)
// Priorizar NODE_ENV para que el comando npm run desktop:* funcione correctamente
const isDev = process.env.NODE_ENV === 'development' || (!hasLocalBuild && !app.isPackaged)

/** @type {BrowserWindow | null} */
let mainWindow = null
/** @type {Tray | null} */
let tray = null
/** @type {{ stop?: () => void } | null} */
let backgroundNotifyPoller = null
let isQuitting = false
function getMainWindow() { return mainWindow }

function showMainWindow() {
  if (!mainWindow || mainWindow.isDestroyed()) {
    createWindow()
    return
  }
  if (mainWindow.isMinimized()) mainWindow.restore()
  if (!mainWindow.isVisible()) mainWindow.show()
  mainWindow.focus()
}

function createTray() {
  if (!IS_WIN || tray) return
  const iconPath = resolveAppIcon()
  if (!iconPath) {
    console.warn('[tray] Sin icono; bandeja del sistema no disponible.')
    return
  }
  const trayIcon = nativeImage.createFromPath(iconPath)
  tray = new Tray(trayIcon.resize({ width: 16, height: 16 }))
  tray.setToolTip('DOT sigue activo')
  const contextMenu = Menu.buildFromTemplate([
    { label: 'Abrir DOT', click: () => showMainWindow() },
    { type: 'separator' },
    {
      label: 'Salir',
      click: () => {
        isQuitting = true
        app.quit()
      },
    },
  ])
  tray.setContextMenu(contextMenu)
  tray.on('double-click', () => showMainWindow())
}

function attachCloseToTray(win) {
  if (!IS_WIN) return
  win.on('close', (event) => {
    if (isQuitting) return
    event.preventDefault()
    win.hide()
  })
}

function resolveAppIcon() {
  const candidates = [path.join(__dirname, 'icon.ico'), path.join(__dirname, 'icon.png')]
  for (const c of candidates) { if (fs.existsSync(c)) return c }
  return undefined
}

function buildDesktopCsp() {
  // En renderer, 'self' es el origen de Vite (5173) o file:// — NO el API.
  // Sin :8000 en connect-src, login/fetch falla con "Failed to fetch".
  const apiBase = (
    process.env.DOT_API_BASE_URL ||
    process.env.VITE_API_BASE_URL ||
    'http://127.0.0.1:8000'
  ).trim().replace(/\/$/, '')
  const connect = new Set(["'self'", apiBase])
  if (apiBase.includes('127.0.0.1')) {
    connect.add(apiBase.replace('127.0.0.1', 'localhost'))
  } else if (apiBase.includes('localhost')) {
    connect.add(apiBase.replace('localhost', '127.0.0.1'))
  }
  const wsApi = apiBase.replace(/^http/, 'ws')
  connect.add(wsApi)
  // Vite HMR / React Fast Refresh necesitan scripts inline + eval SOLO en desarrollo.
  // En producción el CSP queda estricto (script-src 'self').
  const scriptSrc = isDev
    ? "script-src 'self' 'unsafe-inline' 'unsafe-eval' http://127.0.0.1:5173 http://localhost:5173"
    : "script-src 'self'"
  if (isDev) {
    connect.add('http://127.0.0.1:5173')
    connect.add('ws://127.0.0.1:5173')
    connect.add('http://localhost:5173')
    connect.add('ws://localhost:5173')
  }
  return [
    "default-src 'self'", scriptSrc, "style-src 'self' 'unsafe-inline'",
    "img-src 'self' data: blob:", "font-src 'self' data:",
    `connect-src ${Array.from(connect).join(' ')}`,
    "form-action 'self'", "frame-ancestors 'none'", "base-uri 'self'",
    "object-src 'none'", "worker-src 'self'", "media-src 'self'",
  ].join('; ')
}

function configureSessionSecurity() {
  // Ya no se usa; permisos se aplican por ventana en createWindow
}

function attachDevToolsShortcuts(win) {
  if (!isDev || !win?.webContents) return
  const wc = win.webContents
  wc.on('before-input-event', (_event, input) => {
    if (input.type !== 'keyDown') return
    const toggle =
      input.key === 'F12' ||
      (input.control && input.shift && (input.key === 'I' || input.key === 'i'))
    if (!toggle) return
    if (wc.isDevToolsOpened()) wc.closeDevTools()
    else wc.openDevTools({ mode: 'detach' })
  })
}

function createWindow() {
  const demoMode = process.env.DOT_DEMO_MODE === '1' || process.env.VITE_DOT_DEMO_MODE === '1'
  // En demo/dev siempre mostrar la ventana de inmediato (evita "pantalla negra" por ready-to-show).
  const showImmediately = isDev || demoMode
  // macOS: no ocultar menu bar nativa (está separada de la ventana)
  const hideMenuBar = !IS_MAC
  const win = new BrowserWindow({
    width: 1280, height: 800, minWidth: 960, minHeight: 640,
    title: 'DOT', icon: resolveAppIcon(), backgroundColor: '#0f172a',
    show: showImmediately, autoHideMenuBar: hideMenuBar,
    webPreferences: {
      preload: path.join(__dirname, 'preload.cjs'),
      contextIsolation: true, nodeIntegration: false,
      sandbox: true, webSecurity: true, allowRunningInsecureContent: false,
    },
  })
  win.once('ready-to-show', () => {
    if (!isDev) win.maximize()
    win.show()
    // DevTools en desarrollo o demo para diagnosticar UI
    if (isDev || demoMode) {
      win.webContents.openDevTools({ mode: 'bottom' })
    }
  })
  // Fallback: si ready-to-show no dispara en 3s, mostrar igual
  setTimeout(() => {
    if (!win.isDestroyed() && !win.isVisible()) win.show()
  }, 3000)
  mainWindow = win
  // Limpiar permisos cacheados y auto-conceder micrófono (M3.1 voz)
  const ses = win.webContents.session
  ses.clearHostResolverCache().catch(() => {})

  // CSP: en file:// (build dist) 'self' a veces no cubre ./assets/*.js → pantalla negra.
  // En Vite http:// sí aplica CSP completo. En dist usamos política permisiva local.
  const cspValue = isDev
    ? buildDesktopCsp()
    : [
        "default-src 'self' file:",
        "script-src 'self' 'unsafe-inline' file: blob:",
        "style-src 'self' 'unsafe-inline' file:",
        "img-src 'self' data: blob: file:",
        "font-src 'self' data: file:",
        `connect-src 'self' ${
          (process.env.DOT_API_BASE_URL || process.env.VITE_API_BASE_URL || 'http://127.0.0.1:8000')
            .trim()
            .replace(/\/$/, '')
        } ws://127.0.0.1:8000 http://127.0.0.1:8000 http://localhost:8000 ws://localhost:8000`,
        "object-src 'none'",
        "base-uri 'self'",
      ].join('; ')
  if (cspValue) {
    ses.webRequest.onHeadersReceived((details, callback) => {
      callback({
        responseHeaders: {
          ...details.responseHeaders,
          'Content-Security-Policy': [cspValue],
        },
      })
    })
  }

  // C3: Micrófono con consentimiento real del usuario.
  // Antes se auto-concedía sin diálogo (violación de privacidad). Ahora:
  // 1. Se verifica si el SO ya concedió el permiso a nivel sistema.
  // 2. Si no, se pide explícitamente via systemPreferences.askForMediaAccess.
  // 3. Solo entonces se concede en Chromium. Sin permiso del SO → denegado.
  const { systemPreferences } = require('electron')
  const micGranted =
    systemPreferences.getMediaAccessStatus('microphone') === 'granted'
  if (micGranted) {
    const allowMic = (permission) =>
      permission === 'media' ||
      permission === 'microphone' ||
      permission === 'mediaKeySystem'
    ses.setPermissionRequestHandler((_webContents, permission, callback) => {
      callback(allowMic(permission))
    })
    ses.setPermissionCheckHandler((_webContents, permission) => allowMic(permission))
    // También en defaultSession (Vite carga desde http://127.0.0.1:5173)
    session.defaultSession.setPermissionRequestHandler((_webContents, permission, callback) => {
      callback(allowMic(permission))
    })
    session.defaultSession.setPermissionCheckHandler((_webContents, permission) =>
      allowMic(permission),
    )
  } else {
    // Micrófono no concedido a nivel SO: denegar en Chromium y ofrecer
    // al frontend la opción de abrir Configuración > Privacidad > Micrófono.
    ses.setPermissionRequestHandler((_webContents, permission, callback) => {
      callback(permission !== 'microphone' && permission !== 'media')
    })
    session.defaultSession.setPermissionRequestHandler((_webContents, permission, callback) => {
      callback(permission !== 'microphone' && permission !== 'media')
    })
  }

  // C9: Prevenir navegación a URLs externas (phishing, redirecciones maliciosas).
  // Sin estos handlers, si un atacante logra redirigir la ventana a
  // https://phishing.com, Electron lo seguiría sin rechistar.
  const allowedOrigins = isDev
    ? ['http://127.0.0.1:5173', 'http://localhost:5173']
    : ['file://']
  win.webContents.on('will-navigate', (event, url) => {
    const isAllowed = allowedOrigins.some((origin) => url.startsWith(origin))
    if (!isAllowed) {
      event.preventDefault()
      console.warn('[main] Navegación bloqueada:', url)
    }
  })
  win.webContents.on('will-frame-navigate', (event, url) => {
    const isAllowed = allowedOrigins.some((origin) => url.startsWith(origin))
    if (!isAllowed) {
      event.preventDefault()
      console.warn('[main] Navegación de frame bloqueada:', url)
    }
  })
  win.webContents.setWindowOpenHandler(({ url }) => {
    const isAllowed = allowedOrigins.some((origin) => url.startsWith(origin))
    if (!isAllowed) {
      console.warn('[main] Apertura de ventana bloqueada:', url)
      return { action: 'deny' }
    }
    try {
      shell.openExternal(url)
    } catch { /* silencioso */ }
    return { action: 'deny' }
  })

  attachDevToolsProtection(win)
  attachDevToolsShortcuts(win)
  attachCloseToTray(win)
  win.on('closed', () => { if (mainWindow === win) mainWindow = null })

  // Electron 40+: console-message pasa Event con { level, message, lineNumber, sourceId }
  win.webContents.on('console-message', (event, level, message, line, sourceId) => {
    let lvl = level
    let msg = message
    let ln = line
    let src = sourceId
    if (event && typeof event === 'object' && 'message' in event) {
      const e = event
      lvl = e.level
      msg = e.message
      ln = e.lineNumber
      src = e.sourceId
    }
    if (typeof lvl === 'string') {
      lvl = lvl === 'error' ? 3 : lvl === 'warning' ? 2 : 1
    }
    if (lvl < 2 && !demoMode && !isDev) return
    const prefix = lvl === 3 ? 'RENDERER ERROR' : lvl === 2 ? 'RENDERER WARN' : 'RENDERER LOG'
    console.log(`[${prefix}] ${msg}${src ? ` (${src}:${ln})` : ''}`)
  })
  win.webContents.on('did-fail-load', (_e, code, desc, url) => {
    console.error('[main] did-fail-load', { code, desc, url })
  })
  win.webContents.on('render-process-gone', (_e, details) => {
    console.error('[main] render-process-gone', details)
  })
  win.webContents.on('did-finish-load', () => {
    win.webContents
      .executeJavaScript(
        `(() => {
          const root = document.getElementById('root');
          return {
            href: location.href,
            rootChildren: root ? root.children.length : -1,
            rootText: root ? (root.innerText || '').slice(0, 200) : null,
            bodyClass: document.body.className,
          };
        })()`,
      )
      .then((info) => console.log('[main] renderer DOM:', JSON.stringify(info)))
      .catch((err) => console.error('[main] DOM probe failed:', err))
  })

  const loadApp = () => {
    if (isDev) {
      win.loadURL('http://127.0.0.1:5173/').catch((err) => {
        console.error('[main] loadURL failed:', err)
      })
      return
    }
    const indexPath = path.join(__dirname, '..', 'dist', 'index.html')
    if (!fs.existsSync(indexPath)) {
      console.error('[main] dist/index.html no existe. Ejecuta: npx vite build --config config/vite.config.ts')
      return
    }
    console.log('[main] Cargando build local:', indexPath)
    win.loadFile(indexPath).catch((err) => {
      console.error('[main] loadFile failed:', err)
    })
  }

  // Limpiar SW/cache antes de cargar (SW viejo = pantalla negra)
  void session.defaultSession
    .clearStorageData({ storages: ['serviceworkers', 'cachestorage'] })
    .catch(() => {})
    .finally(loadApp)
}

function ensureSecureStorageAvailability() {
  // C7: Verificación real de safeStorage. Antes era un no-op.
  // Si el keychain del SO no está disponible, las sesiones no persisten
  // y el usuario debe ser informado.
  try {
    const { safeStorage } = require('electron')
    if (safeStorage && safeStorage.isEncryptionAvailable()) {
      return true
    }
    console.warn('[main] safeStorage no disponible: las sesiones no persistirán tras reinicio.')
    return false
  } catch {
    console.warn('[main] No se pudo verificar safeStorage.')
    return false
  }
}

function sanitizeTaskSegment(value, fallback = 'item') {
  const raw = typeof value === 'string' ? value : ''
  return raw.replace(/[^a-zA-Z0-9_-]/g, '').slice(0, 40) || fallback
}

function sanitizeReminderText(text) {
  const raw = typeof text === 'string' ? text : ''
  return raw.replace(/[\r\n\t]+/g, ' ').replace(/"/g, "'").trim().slice(0, 180)
}

function sanitizeNotificationText(text, max = 220) {
  const raw = typeof text === 'string' ? text : ''
  return raw.replace(/[\r\n\t]+/g, ' ').trim().slice(0, max)
}

function formatSchtasksDate(value) {
  const yyyy = value.getFullYear()
  const mm = String(value.getMonth() + 1).padStart(2, '0')
  const dd = String(value.getDate()).padStart(2, '0')
  return `${yyyy}/${mm}/${dd}`
}

function formatSchtasksTime(value) {
  const hh = String(value.getHours()).padStart(2, '0')
  const mm = String(value.getMinutes()).padStart(2, '0')
  return `${hh}:${mm}`
}

function parseBooleanEnv(value, fallback = false) {
  if (typeof value !== 'string') return fallback
  const n = value.trim().toLowerCase()
  if (!n) return fallback
  if (['1', 'true', 'yes', 'on'].includes(n)) return true
  if (['0', 'false', 'no', 'off'].includes(n)) return false
  return fallback
}

function buildUpdaterFeedConfig() {
  const genericUrl = (process.env.DOT_UPDATER_URL || '').trim()
  if (genericUrl) {
    return { provider: 'generic', url: genericUrl,
      channel: (process.env.DOT_UPDATER_CHANNEL || 'latest').trim() || 'latest',
      useMultipleRangeRequest: false }
  }
  const owner = (process.env.DOT_UPDATER_GH_OWNER || '').trim()
  const repo = (process.env.DOT_UPDATER_GH_REPO || '').trim()
  if (!owner || !repo) return null
  const isPrivate = parseBooleanEnv(process.env.DOT_UPDATER_GH_PRIVATE, false)
  const token = (process.env.DOT_UPDATER_GH_TOKEN || process.env.GH_TOKEN || '').trim()
  return { provider: 'github', owner, repo, private: isPrivate, releaseType: 'release', ...(token ? { token } : {}) }
}

function configureAutoUpdater() {
  if (!IS_WIN || !app.isPackaged) return
  if (!parseBooleanEnv(process.env.DOT_AUTO_UPDATE_ENABLED, true)) return

  // Carga diferida para evitar crash con ESM loader (Electron 42)
  let autoUpdater;
  try {
    autoUpdater = require('electron-updater').autoUpdater;
  } catch (err) {
    console.warn('[updater] No se pudo cargar electron-updater:', err.message);
    return;
  }

  const feedConfig = buildUpdaterFeedConfig()
  if (!feedConfig) { console.info('[updater] Desactivado: falta configurar feed.'); return }

  try { autoUpdater.setFeedURL(feedConfig) } catch (error) { console.error('[updater] Error feed:', error); return }

  autoUpdater.autoDownload = true
  autoUpdater.autoInstallOnAppQuit = true
  autoUpdater.allowPrerelease = parseBooleanEnv(process.env.DOT_UPDATER_ALLOW_PRERELEASE, false)

  let hasDownloadedUpdate = false

  autoUpdater.on('update-available', (info) => {
    try {
      if (!Notification.isSupported()) return
      const version = sanitizeNotificationText(info?.version || '', 30)
      new Notification({ title: 'Actualización disponible',
        body: version ? `Descargando en segundo plano la versión ${version}.` : 'Descargando una actualización en segundo plano.',
        silent: true }).show()
    } catch { /* silencioso */ }
  })

  autoUpdater.on('update-downloaded', (info) => {
    hasDownloadedUpdate = true
    try {
      if (!Notification.isSupported()) return
      const version = sanitizeNotificationText(info?.version || '', 30)
      const body = version ? `La versión ${version} se instalará al reiniciar DOT. Haz clic para reiniciar ahora.` : 'La actualización se instalará al reiniciar DOT. Haz clic para reiniciar ahora.'
      const toast = new Notification({ title: 'Actualización lista para instalar', body, silent: false })
      toast.on('click', () => { try { autoUpdater.quitAndInstall(false, true) } catch { /* silencioso */ } })
      toast.show()
    } catch { /* silencioso */ }
  })

  autoUpdater.on('error', (error) => console.error('[updater] Error:', error))

  void autoUpdater.checkForUpdates().catch((error) => console.error('[updater] Error check:', error))
}

if (IS_WIN) {
  app.setAppUserModelId('com.dotia.dotdesktop')
}

const gotLock = app.requestSingleInstanceLock()
if (!gotLock) {
  app.quit()
} else {
  app.on('second-instance', () => {
    showMainWindow()
  })

  app.whenReady().then(() => {
    if (!ensureSecureStorageAvailability()) return
    configureSessionSecurity()

    // ─── macOS: configurar Dock ─────────────────────────────────
    if (IS_MAC && app.dock) {
      app.dock.setIcon(resolveAppIcon() || path.join(__dirname, 'icon.icns'))
      app.dock.show()
    }

    localDb.init();

    // M2S2-A: Sistema de jobs persistente con node-cron + SQLite
    // Solo si localDb se inicializo correctamente
    if (localDb.db || localDb.getAllProfile) {
      jobScheduler.init(localDb);
    }

    registerIpcHandlers({
      ipcMain, BrowserWindow, Notification, shell, nativeTheme, secureStorage, usbSerial,
      pendriveCrypto, pendriveGate, localTools, whatsappService, app,
      localDb,
      codeExecutor,
      mainWindowRef: getMainWindow,
      showMainWindow,
      sanitizeNotificationText, sanitizeTaskSegment, sanitizeReminderText,
      formatSchtasksDate, formatSchtasksTime,
    })

    if (IS_WIN) {
      backgroundNotifyPoller = createBackgroundNotifyPoller({
        secureStorage,
        localDb,
        Notification,
        sanitizeNotificationText,
        showMainWindow,
        getMainWindow,
      })
      backgroundNotifyPoller.start()
    }

    configureAutoUpdater()

    // E05: Modo Demo — advertir si se intenta usar en producción
  if (process.env.DOT_DEMO_MODE === '1' && app.isPackaged) {
    console.warn('[main] DEMO_MODE ignorado en producción — la verificación USB está activa')
  }

  try {
    const { isFullDiskAccessEnabled } = require('./sandbox-resolver.cjs')
    if (isFullDiskAccessEnabled()) {
      console.warn(
        '[main] ACCESO COMPLETO AL DISCO activo (DOT_FULL_DISK_ACCESS / DOT_DEMO_MODE). Solo desarrollo.',
      )
    }
  } catch (e) {
    console.warn('[main] No se pudo evaluar full-disk access:', e)
  }

    // Always-alive: restaurar sesión Baileys al arranque (PC / bandeja) sin QR si hay creds.
    void (async () => {
      const transport = getTransport()
      try {
        if (typeof transport.restoreSession === 'function') {
          const result = await transport.restoreSession()
          if (result.ok) {
            console.info('[whatsapp] Sesión restaurada al arranque (phone=%s)', result.phone_number || '?')
          } else if (result.needs_qr) {
            console.info('[whatsapp] Sin sesión guardada; QR solo cuando el usuario vincule')
          } else {
            console.warn('[whatsapp] restoreSession falló:', result.error || 'unknown')
          }
          return
        }
        const boot = await transport.bootstrap()
        if (boot.started) {
          console.info('[whatsapp] Daemon restaurado al arranque (bootstrap)')
        }
      } catch (err) {
        console.warn('[whatsapp] Error restaurando sesión al arranque:', err)
      }
    })()

    // [DEV] Sin espera de pendrive, sin auto-launch, sin monitor USB
    createWindow()
    createTray()

    app.on('activate', () => {
      if (BrowserWindow.getAllWindows().length === 0) {
        createWindow()
      }
    })
  })

  app.on('window-all-closed', () => {
    // Windows: la app sigue en bandeja (WhatsApp/Baileys activo); salir solo desde menú tray.
    if (IS_WIN) return
    if (process.platform !== 'darwin') app.quit()
  })

  // ─── macOS / Linux: abrir archivos asociados ──────────
  app.on('open-file', (_event, filePath) => {
    // El archivo se pasa al renderer vía IPC cuando esté listo
    console.log('[main] open-file:', filePath)
  })

  app.on('open-url', (_event, url) => {
    // Protocolo dot:// manejado desde el renderer
    console.log('[main] open-url:', url)
  })

  app.on('before-quit', () => {
    isQuitting = true
    backgroundNotifyPoller?.stop?.()
    backgroundNotifyPoller = null
    if (tray && !tray.isDestroyed()) {
      tray.destroy()
      tray = null
    }
    try {
      const { stopLocalBridge } = require('./whatsapp/local-bridge.cjs')
      void stopLocalBridge()
    } catch {
      // ignore
    }
    getTransport().shutdown()
    jobScheduler.stop()
    localDb.close()
  })
  // [DEV] Sin limpieza de monitor USB
}
