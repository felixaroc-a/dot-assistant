'use strict'

/**
 * Registra todos los IPC handlers de DOT en el proceso principal.
 * Recibe las dependencias desde main.cjs para evitar acoplamiento.
 */
const { createBackendInboundClient, createBackendChannelClient } = require('./whatsapp/backend-client.cjs')
const { startLocalBridge } = require('./whatsapp/local-bridge.cjs')
const { getTransport } = require('./whatsapp/transport/index.cjs')
const { restoreFromSavedCreds } = require('./whatsapp/runtime.cjs')
const documentParser = require('./document-parser.cjs')
const fileSearch = require('./file-search.cjs')
const { createSystemNotifier } = require('./system-notify.cjs')
const memoryStore = require('./memory-store.cjs')
const { FileIndexer } = require('./file-indexer.cjs')

module.exports = function registerIpcHandlers({
  ipcMain,
  BrowserWindow,
  Notification,
  shell,
  nativeTheme,
  secureStorage,
  usbSerial,
  pendriveCrypto,
  pendriveGate,
  localTools,
  whatsappService,
  localDb,
  codeExecutor,
  // autoUpdater se carga bajo demanda (lazy)
  app,
  mainWindowRef,
  showMainWindow,
  sanitizeNotificationText,
  sanitizeTaskSegment,
  sanitizeReminderText,
  formatSchtasksDate,
  formatSchtasksTime,
}) {
  const getMainWindow = () =>
    typeof mainWindowRef === 'function' ? mainWindowRef() : mainWindowRef

  const revealMainWindow = () => {
    if (typeof showMainWindow === 'function') {
      showMainWindow()
      return
    }
    const win = getMainWindow()
    if (!win || win.isDestroyed()) return
    if (win.isMinimized()) win.restore()
    if (!win.isVisible()) win.show()
    win.focus()
  }

  const systemNotifier = createSystemNotifier({
    Notification,
    sanitizeNotificationText,
    showMainWindow: revealMainWindow,
  })

  const transport = getTransport()
  const backendInboundClient = createBackendInboundClient({
    loadSession: () => secureStorage.loadSession(),
    onRendererNotify: (event, payload) => {
      const win = getMainWindow()
      if (win && !win.isDestroyed()) {
        win.webContents.send(event, payload)
      }
    },
  })

  const backendChannelClient = createBackendChannelClient({
    loadSession: () => secureStorage.loadSession(),
    onRendererNotify: (event, payload) => {
      const win = getMainWindow()
      if (win && !win.isDestroyed()) {
        win.webContents.send(event, payload)
      }
    },
  })

  transport.onInboundMessage(async (payload) => {
    try {
      const data = await backendInboundClient.postInbound(payload)
      console.log(
        '[IPC] whatsapp inbound ok',
        `from=${payload.from_phone || ''}`,
        `group=${payload.group_name || payload.chat_jid || ''}`,
        `allow_auto_reply=${data?.allow_auto_reply ? 1 : 0}`,
        `chars=${String(payload.text || '').length}`,
      )
    } catch (err) {
      console.warn('[IPC] whatsapp inbound forward failed:', err)
    }
  })

  // T13: notificar descargas de media al frontend y al sistema.
  transport.onMediaDownloaded((payload) => {
    const win = getMainWindow()
    if (win && !win.isDestroyed()) {
      win.webContents.send('whatsapp:media-downloaded', payload)
    }
    if (payload.ok && payload.file_path) {
      try {
        if (process.platform === 'win32' && Notification.isSupported()) {
          const fileName = payload.file_path.split(/[\\/]/).pop() || 'archivo'
          const typeLabel = (payload.mime_type || '').startsWith('image/') ? 'Imagen' :
            (payload.mime_type || '').startsWith('video/') ? 'Video' :
            (payload.mime_type || '').startsWith('audio/') ? 'Audio' : 'Archivo'
          new Notification({
            title: `${typeLabel} de WhatsApp recibido`,
            body: `${fileName} guardado en DOT-Media.`,
            silent: true,
          }).show()
        }
      } catch {
        // ignore
      }
    }
    if (!payload.ok) {
      console.warn('[IPC] whatsapp media download failed:', payload.error)
    }
  })

  void startLocalBridge({
    port: Number(process.env.WHATSAPP_BRIDGE_PORT || 18790),
    secret: process.env.WHATSAPP_BRIDGE_SECRET || '',
    fileIndexer, // FASE 3.2: exponer file-indexer al bridge HTTP
  }).then((result) => {
    if (result.ok) {
      console.log(`[whatsapp] Local bridge activo en 127.0.0.1:${result.port}`)
    } else {
      console.warn('[whatsapp] No se pudo iniciar local bridge:', result.error)
    }
  })

  const broadcastWhatsAppStatus = () => {
    const win = getMainWindow()
    const status = transport.getStatus()
    if (win && !win.isDestroyed()) {
      win.webContents.send('whatsapp:status', status)
    }
  }

  /** Último evento de ciclo de vida enviado al backend (anti-spam). */
  let lastSyncedLifecycleEvent = ''
  /** Cola secuencial para evitar race conditions en syncLifecycleEventToBackend. */
  let lifecycleSyncQueue = Promise.resolve()

  /**
   * A3: sincroniza connectionState local → /v1/whatsapp/channel/events.
   * - restarting/starting con sesión → reconnecting (conserva linked)
   * - connected → linked/heartbeat
   * - disconnected + logged out → disconnected
   * - disconnected con creds (reintentos) → reconnecting + error
   */
  const syncLifecycleEventToBackend = async (status) => {
    try {
      const apiBase = (process.env.DOT_API_BASE_URL || 'http://127.0.0.1:8000').trim().replace(/\/+$/, '')
      const sessionStr = await secureStorage.loadSession()
      let token = ''
      if (sessionStr) {
        try {
          const session = JSON.parse(sessionStr)
          token =
            session?.accessToken ||
            session?.access_token ||
            session?.token ||
            ''
        } catch {
          token = sessionStr
        }
      }
      if (!token) return { ok: false, reason: 'no_token' }

      const connectionState = String(status?.state || status?.connectionState || '')
      const lastError = status?.error || status?.lastError ? String(status.error || status.lastError) : ''
      const loggedOut =
        /logged.?out/i.test(lastError) || Boolean(status?.needsFreshLogin)
      const phone =
        status?.phone_number ||
        transport.ensureOwnPhone(null) ||
        null

      /** @type {string | null} */
      let event = null
      /** @type {string | undefined} */
      let error

      if (connectionState === 'connected' && status?.linked) {
        event = lastSyncedLifecycleEvent === 'linked' || lastSyncedLifecycleEvent.startsWith('linked:')
          ? 'heartbeat'
          : 'linked'
      } else if (
        connectionState === 'restarting' ||
        connectionState === 'starting'
      ) {
        event = 'reconnecting'
        error = lastError || undefined
      } else if (connectionState === 'disconnected') {
        if (loggedOut || !status?.linked) {
          event = 'disconnected'
          error = lastError || 'disconnected'
        } else {
          // Sesión aún válida; socket caído — estado honesto sin forzar QR.
          event = 'reconnecting'
          error = lastError || 'disconnected'
        }
      }

      if (!event) return { ok: true, skipped: true }

      const dedupeKey = `${event}:${connectionState}:${error || ''}`
      if (dedupeKey === lastSyncedLifecycleEvent && event !== 'heartbeat') {
        return { ok: true, skipped: true, reason: 'dedupe' }
      }
      // Heartbeat: como máximo cada ciclo distinto de connected tras linked.
      if (event === 'heartbeat' && lastSyncedLifecycleEvent.startsWith('heartbeat:')) {
        return { ok: true, skipped: true, reason: 'heartbeat_throttle' }
      }

      const response = await fetch(`${apiBase}/v1/whatsapp/channel/events`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          Authorization: `Bearer ${token}`,
        },
        body: JSON.stringify({
          event,
          phone_number: phone,
          error: error || null,
          source: 'electron-lifecycle',
        }),
      })
      if (!response.ok) {
        console.warn('[IPC] syncLifecycleEventToBackend: backend %d', response.status)
        return { ok: false, status: response.status }
      }
      lastSyncedLifecycleEvent = event === 'heartbeat' ? `heartbeat:${Date.now()}` : dedupeKey
      console.log(
        '[IPC] syncLifecycleEventToBackend: event=%s state=%s',
        event,
        connectionState,
      )
      return { ok: true, event }
    } catch (err) {
      console.error('[IPC] syncLifecycleEventToBackend error:', err)
      return { ok: false, error: String(err) }
    }
  }

  transport.onStatusChange(() => {
    broadcastWhatsAppStatus()
    const status = transport.getStatus()
    // Encadenar promesas para evitar race conditions en syncLifecycleEventToBackend
    lifecycleSyncQueue = lifecycleSyncQueue.then(() =>
      syncLifecycleEventToBackend(status),
    )
  })

  /**
   * Notifica al backend el estado linked + phone_number (JWT desde sesión Electron).
   * @param {{ linked?: boolean; phone_number?: string | null; source?: string }} data
   */
  const syncLinkedStatusToBackend = async (data) => {
    try {
      const apiBase = (process.env.DOT_API_BASE_URL || 'http://127.0.0.1:8000').trim().replace(/\/+$/, '')
      const sessionStr = await secureStorage.loadSession()
      let token = ''
      if (sessionStr) {
        try {
          const session = JSON.parse(sessionStr)
          token =
            session?.accessToken ||
            session?.access_token ||
            session?.token ||
            ''
        } catch {
          token = sessionStr
        }
      }
      if (!token) {
        console.warn('[IPC] syncLinkedStatusToBackend: sin token JWT, omitiendo')
        return { ok: false, reason: 'no_token' }
      }
      const phone =
        data.phone_number ||
        transport.ensureOwnPhone(data.phone_number) ||
        transport.getStatus()?.phone_number ||
        null
      const response = await fetch(`${apiBase}/v1/whatsapp/channel/status`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          Authorization: `Bearer ${token}`,
        },
        body: JSON.stringify({
          linked: data.linked !== false,
          phone_number: phone,
          source: data.source || 'electron',
        }),
      })
      if (!response.ok) {
        console.warn('[IPC] syncLinkedStatusToBackend: backend %d', response.status)
        return { ok: false, status: response.status }
      }
      console.log('[IPC] syncLinkedStatusToBackend: ok phone=%s', phone || 'null')
      return { ok: true, phone_number: phone }
    } catch (err) {
      console.error('[IPC] syncLinkedStatusToBackend error:', err)
      return { ok: false, error: String(err) }
    }
  }

  // Tras arranque: sincronizar verdad local ↔ backend (sin forzar QR si hay creds).
  setTimeout(() => {
    void (async () => {
      const status = transport.getStatus()
      const phone = transport.ensureOwnPhone(null) || status.phone_number
      const connectionState = String(status.state || status.connectionState || '')

      if (status.configured && !status.needsFreshLogin) {
        if (connectionState === 'connected' && status.linked && phone) {
          await syncLinkedStatusToBackend({
            linked: true,
            phone_number: phone,
            source: 'electron-boot-sync',
          })
          return
        }
        // Sesión local presente; daemon reconectando — no marcar desvinculado.
        if (!status.daemonRunning || connectionState === 'starting' || connectionState === 'restarting') {
          await syncLifecycleEventToBackend({
            ...status,
            state: connectionState || 'starting',
            linked: true,
            needsFreshLogin: false,
            error: null,
          })
          return
        }
      }

      // Sin credenciales locales: no mentir linked=true en Firestore.
      if (!status.configured && !phone) {
        await syncLifecycleEventToBackend({
          ...status,
          state: 'disconnected',
          linked: false,
          needsFreshLogin: true,
          error: status.error || 'local_session_missing',
        })
      }
    })()
  }, 2500)

  // ─── Sesión segura ───────────────────────────────────
  ipcMain.handle('dot:secure-session-save', (_e, json) => {
    if (typeof json !== 'string') return { ok: false }
    return secureStorage.saveSession(json)
  })
  ipcMain.handle('dot:secure-session-load', () => secureStorage.loadSession())
  ipcMain.handle('dot:secure-session-clear', () => secureStorage.clearSession())

  ipcMain.handle('dot:oauth-subject-save', (_e, id) => {
    if (typeof id !== 'string' || !id.trim()) return { ok: false }
    return secureStorage.saveOAuthSubject(id.trim())
  })
  ipcMain.handle('dot:oauth-subject-load', () => secureStorage.loadOAuthSubject())

  // ─── USB Serial ──────────────────────────────────────
  ipcMain.handle('dot:usb-serial', async (_e, hint) => {
    try {
      const h = typeof hint === 'string' ? hint : undefined
      return await usbSerial.getUsbStorageSerial(h)
    } catch {
      return { serial: null, devices: [], error: 'No se pudo leer el pendrive' }
    }
  })

  // ─── Hardware bind ───────────────────────────────────
  ipcMain.handle('dot:hardware-bind-save', (_e, fingerprint) => {
    if (typeof fingerprint !== 'string') return { ok: false }
    return secureStorage.saveHardwareBind(fingerprint)
  })
  ipcMain.handle('dot:hardware-bind-load', () => secureStorage.loadHardwareBind())
  ipcMain.handle('dot:hardware-bind-clear', () => secureStorage.clearHardwareBind())

  // ─── Recovery key ────────────────────────────────────
  ipcMain.handle('dot:recovery-key-save', (_e, recoveryKey) => {
    if (typeof recoveryKey !== 'string' || !recoveryKey.trim()) return { ok: false }
    return secureStorage.saveRecoveryKey(recoveryKey.trim())
  })
  ipcMain.handle('dot:recovery-key-load', () => secureStorage.loadRecoveryKey())

  // ─── Pendrive gate ───────────────────────────────────
  pendriveGate.registerPendriveIpc(app, ipcMain)

  // ─── Pendrive vault ──────────────────────────────────
  ipcMain.handle('dot:pendrive-setup', async (_e, serial, drivePath) => {
    if (typeof serial !== 'string' || !serial.trim()) {
      return { ok: false, error: 'Serial requerido' }
    }
    if (typeof drivePath !== 'string' || !drivePath.trim()) {
      return { ok: false, error: 'Ruta de unidad requerida' }
    }
    try {
      const result = await pendriveCrypto.createVault(drivePath.trim(), serial.trim())
      return { ok: result.ok, token: result.token, error: result.error }
    } catch (err) {
      return { ok: false, error: err.message || 'Error al configurar pendrive' }
    }
  })

  ipcMain.handle('dot:pendrive-setup-status', async (_e) => {
    try {
      const devices = await pendriveCrypto.listAllUsbDrives()
      const mapped = []
      for (const dev of devices) {
        const dp = dev.driveLetter + '\\'
        const hasVault = pendriveCrypto.vaultExists(dp)
        const vaultOk = hasVault
          ? (await pendriveCrypto.verifyVaultFull(dp, dev.serial)).ok
          : false
        mapped.push({
          serial: dev.serial,
          driveLetter: dev.driveLetter,
          hasVault,
          vaultOk,
        })
      }
      return { ok: true, devices: mapped }
    } catch (err) {
      return { ok: false, devices: [], error: err.message }
    }
  })

  // ─── Recovery key backup ─────────────────────────────
  ipcMain.handle('dot:recovery-key-get', async () => {
    try {
      const drives = await pendriveCrypto.listAllUsbDrives()
      for (const { serial, driveLetter } of drives) {
        const dp = driveLetter + '\\'
        const raw = pendriveCrypto.readVaultRaw(dp)
        if (raw.ok) {
          return { ok: true, serial, drivePath: dp }
        }
      }
      return { ok: false, error: 'NO_VAULT_FOUND' }
    } catch (err) {
      return { ok: false, error: err.message || 'READ_ERROR' }
    }
  })

  // ─── Open URL ────────────────────────────────────────
  const ALLOWED_SYSTEM_PROTOCOLS = [
    'ms-settings:privacy-microphone',
    'x-apple.systempreferences:com.apple.preference.security?privacy_microphone',
  ]
  // ── Tema nativo (dark/light) ──────────────────────────
  ipcMain.handle('dot:set-native-theme', async (_e, theme) => {
    try {
      if (theme !== 'dark' && theme !== 'light') {
        return { ok: false, error: 'invalid_theme' }
      }
      nativeTheme.themeSource = theme
      return { ok: true }
    } catch (err) {
      return { ok: false, error: String(err) }
    }
  })

  ipcMain.handle('dot:open-path', async (_e, filePath) => {
    try {
      if (typeof filePath !== 'string') return { ok: false, error: 'invalid_path' }
      const trimmed = filePath.trim()
      if (!trimmed) return { ok: false, error: 'empty_path' }
      const result = await shell.openPath(trimmed)
      if (result) return { ok: false, error: result }
      return { ok: true }
    } catch (err) {
      return { ok: false, error: String(err) }
    }
  })

  ipcMain.handle('dot:open-url', async (_e, url) => {
    try {
      if (typeof url !== 'string') return { ok: false }
      const trimmed = url.trim()
      // Solo https/http y URIs de sistema permitidas explícitamente
      if (/^https?:\/\//i.test(trimmed)) {
        await shell.openExternal(trimmed)
        return { ok: true }
      }
      if (ALLOWED_SYSTEM_PROTOCOLS.some((u) => trimmed.toLowerCase() === u.toLowerCase())) {
        await shell.openExternal(trimmed)
        return { ok: true }
      }
      return { ok: false }
    } catch {
      return { ok: false }
    }
  })

  // M3.1: abrir configuración de micrófono del SO (cross-platform)
  ipcMain.handle('dot:open-mic-settings', async () => {
    try {
      if (process.platform === 'win32') {
        await shell.openExternal('ms-settings:privacy-microphone')
      } else if (process.platform === 'darwin') {
        await shell.openExternal('x-apple.systempreferences:com.apple.preference.security?Privacy_Microphone')
      } else {
        // Linux: abrir configuración de sonido del sistema
        try {
          await shell.openPath('/usr/bin/gnome-control-center')
        } catch {
          // fallback silencioso, GNOME Control Center puede no existir
        }
      }
      return { ok: true }
    } catch (err) {
      return { ok: false, error: String(err) }
    }
  })

  ipcMain.handle('dot:mic-status', async () => {
    try {
      const { systemPreferences } = require('electron')
      const status =
        typeof systemPreferences.getMediaAccessStatus === 'function'
          ? systemPreferences.getMediaAccessStatus('microphone')
          : 'unknown'
      return { ok: true, status }
    } catch {
      return { ok: true, status: 'unknown' }
    }
  })

  // ─── Notificaciones ──────────────────────────────────
  ipcMain.handle('dot:system-notify', (_e, title, body) => {
    try {
      const safeTitle = typeof title === 'string' ? title.trim().slice(0, 120) : ''
      const safeBody = typeof body === 'string' ? body.trim().slice(0, 300) : ''
      if (!safeTitle || !safeBody) {
        return { ok: false, error: 'invalid_payload' }
      }
      if (process.platform !== 'win32' || !Notification.isSupported()) {
        return { ok: false, error: 'unsupported_platform' }
      }

      const shown = systemNotifier.showSystemToast(safeTitle, safeBody)
      return shown ? { ok: true } : { ok: false, error: 'notification_failed' }
    } catch {
      return { ok: false, error: 'notification_failed' }
    }
  })

  ipcMain.handle('dot:automation-notify', (_e, payload) => {
    try {
      if (process.platform !== 'win32' || !Notification.isSupported()) {
        return { ok: false, error: 'unsupported_platform' }
      }
      if (!payload || typeof payload !== 'object') {
        return { ok: false, error: 'invalid_payload' }
      }

      const safeTitle = sanitizeNotificationText(
        payload.title || 'DOT - Resultado de automatización', 120,
      )
      const fallbackBody = `Tu automatización "${sanitizeNotificationText(payload.autoName || 'DOT', 90)}" tiene resultados nuevos.`
      const safeBody = sanitizeNotificationText(payload.body || fallbackBody, 300)
      if (!safeTitle || !safeBody) return { ok: false, error: 'invalid_payload' }

      const eventPayload = {
        autoId: sanitizeNotificationText(payload.autoId || '', 80),
        autoName: sanitizeNotificationText(payload.autoName || '', 120),
        executedAt: sanitizeNotificationText(payload.executedAt || '', 64),
        preview: sanitizeNotificationText(payload.preview || '', 280),
      }

      const clickNotifier = createSystemNotifier({
        Notification,
        sanitizeNotificationText,
        showMainWindow: revealMainWindow,
        onClick: () => {
          const win = getMainWindow()
          if (!win || win.isDestroyed()) return
          try {
            win.webContents.send('dot:automation-notification-clicked', eventPayload)
          } catch { /* silencioso */ }
        },
      })

      const shown = clickNotifier.showSystemToast(safeTitle, safeBody)
      return shown ? { ok: true } : { ok: false, error: 'notification_failed' }
    } catch {
      return { ok: false, error: 'notification_failed' }
    }
  })

  // ─── Recordatorios (schtasks) ────────────────────────
  ipcMain.handle('dot:reminder-task-create', async (_e, payload) => {
    try {
      if (process.platform !== 'win32') return { ok: false, error: 'unsupported_platform' }
      if (!payload || typeof payload !== 'object') return { ok: false, error: 'invalid_payload' }

      const id = sanitizeTaskSegment(payload.id, 'reminder')
      const text = sanitizeReminderText(payload.text)
      const dueAtIso = typeof payload.dueAtIso === 'string' ? payload.dueAtIso.trim() : ''
      if (!text || !dueAtIso) return { ok: false, error: 'invalid_payload' }

      const dueDate = new Date(dueAtIso)
      if (Number.isNaN(dueDate.getTime())) return { ok: false, error: 'invalid_due_at' }
      if (dueDate.getTime() <= Date.now()) return { ok: false, error: 'past_due_at' }

      const taskName = `DOT-Reminder-${id}`
      const { execFile } = require('node:child_process')
      await execFile('schtasks.exe', [
        '/Create', '/TN', taskName, '/TR', `msg * "${text}"`,
        '/SC', 'ONCE', '/ST', formatSchtasksTime(dueDate),
        '/SD', formatSchtasksDate(dueDate), '/F',
      ], { windowsHide: true })
      return { ok: true, taskName, dueAtIso }
    } catch (error) {
      const detail = error && typeof error === 'object' && 'stderr' in error
        ? String(error.stderr || '').trim().slice(0, 300) : ''
      return { ok: false, error: 'task_create_failed', detail }
    }
  })

  // ─── Notificaciones automatización (updates) ─────────
  ipcMain.handle('dot:updates-check-now', async () => {
    try {
      const au = require('electron-updater').autoUpdater;
      const result = await au.checkForUpdates()
      return { ok: true, updateInfo: result?.updateInfo || null }
    } catch (error) {
      const message = error && typeof error === 'object' && 'message' in error
        ? String(error.message || '').slice(0, 200) : 'update_check_failed'
      return { ok: false, error: message || 'update_check_failed' }
    }
  })

  ipcMain.handle('dot:updates-install-now', async () => {
    setImmediate(() => {
      try {
        const au = require('electron-updater').autoUpdater;
        au.quitAndInstall(false, true)
      } catch { /* silencioso */ }
    })
    return { ok: true }
  })

  // ─── File search (P2.1) ────────────────────────────────
  ipcMain.handle('dot:file-search', async (_e, params) => {
    if (!params || typeof params !== 'object') {
      return { ok: false, error: 'Parámetros inválidos: {query, contentPattern?, searchRoot?, scope?} requerido' }
    }
    if (typeof params.query !== 'string' || !params.query.trim()) {
      return { ok: false, error: 'query requerido' }
    }
    try {
      return await fileSearch.search({
        query: params.query,
        contentPattern: typeof params.contentPattern === 'string' ? params.contentPattern : undefined,
        searchRoot: typeof params.searchRoot === 'string' ? params.searchRoot : 'all',
        scope: typeof params.scope === 'string' ? params.scope : undefined,
      })
    } catch (err) {
      return { ok: false, error: String(err).slice(0, 300) }
    }
  })

  // ─── File search permissions ──────────────────────────
  ipcMain.handle('dot:file-search-permission-status', async () => {
    try {
      return fileSearch.checkPermission('file_search_full')
    } catch (err) {
      return 'denied'
    }
  })

  ipcMain.handle('dot:file-search-set-permission', async (_e, decision) => {
    const valid = ['once', 'always', 'denied']
    if (!valid.includes(decision)) {
      return { ok: false, error: `Decisión inválida. Usar: ${valid.join(', ')}` }
    }
    try {
      return fileSearch.setPermission('file_search_full', decision)
    } catch (err) {
      return { ok: false, error: String(err).slice(0, 300) }
    }
  })

  // ─── Document parser (T10) ───────────────────────────
  ipcMain.handle('dot:document-parse', async (_e, filePath, mimeType) => {
    if (typeof filePath !== 'string' || typeof mimeType !== 'string') {
      return { ok: false, error: 'Parámetros inválidos: filePath y mimeType requeridos' }
    }
    return documentParser.parse(filePath, mimeType)
  })

  // Document parser desde datos binarios (drag-drop, sin ruta de archivo)
  ipcMain.handle('dot:document-parse-data', async (_e, base64Data, mimeType) => {
    if (typeof base64Data !== 'string' || typeof mimeType !== 'string') {
      return { ok: false, error: 'Parámetros inválidos: base64Data y mimeType requeridos' }
    }
    return documentParser.parseFromData(base64Data, mimeType)
  })

  // Document generation with images (P2.2) — delega al backend python-docx
  ipcMain.handle('dot:document-generate-docx', async (_e, params) => {
    if (!params || typeof params !== 'object') {
      return { ok: false, error: 'Parámetros inválidos' }
    }
    try {
      const sessionStr = await secureStorage.loadSession()
      let token = ''
      if (sessionStr) {
        try {
          const session = JSON.parse(sessionStr)
          token = session?.accessToken || session?.access_token || session?.token || ''
        } catch {
          token = sessionStr
        }
      }
      return await documentParser.generateDocx({
        title: String(params.title || 'Documento DOT'),
        content: String(params.content || ''),
        imagePaths: Array.isArray(params.imagePaths) ? params.imagePaths : [],
        folder: params.folder || null,
        authToken: token || undefined,
      })
    } catch (err) {
      return { ok: false, error: String(err).slice(0, 300) }
    }
  })

  // ─── Local tools ─────────────────────────────────────
  ipcMain.handle('dot:tools-read-file', async (_e, relativePath) => localTools.readFile(relativePath))
  ipcMain.handle('dot:tools-write-file', async (_e, relativePath, content) => localTools.writeFile(relativePath, content))
  ipcMain.handle('dot:tools-download-url', async (_e, url, relativePath) =>
    localTools.downloadUrlToDesktop(url, relativePath || ''),
  )
  ipcMain.handle('dot:tools-list-files', async (_e, relativePath) => localTools.listFiles(relativePath))
  ipcMain.handle('dot:tools-delete-file', async (_e, relativePath) => localTools.deleteFile(relativePath))
  ipcMain.handle('dot:tools-audit-log', async (_e, limit) => localTools.getAuditLog(limit))
  ipcMain.handle('dot:tools-sandbox-info', async () => localTools.getSandboxInfo())
  ipcMain.handle('dot:tools-permission-status', async (_e, actionId) => localTools.getPermissionStatus(actionId))
  ipcMain.handle('dot:tools-set-permission', async (_e, actionId, decision) => localTools.setPermission(actionId, decision))
  ipcMain.handle('dot:tools-reset-permissions', async () => localTools.resetAllPermissions())

  // ─── WhatsApp (login QR + vinculación) ───────────────
  ipcMain.handle('openclaw:start-whatsapp-login', async (_e, opts = {}) => {
    const win = BrowserWindow.getFocusedWindow() || BrowserWindow.getAllWindows()[0]
    console.log('[IPC] openclaw:start-whatsapp-login llamado', opts && typeof opts === 'object' ? opts : {})

    // Siempre limpiar sesión previa al pedir QR (evita “vinculado” zombie y “Esperando mensaje”).
    // clearSession=false solo si se pide explícitamente conservar credenciales.
    const shouldClear = !(opts && typeof opts === 'object' && opts.clearSession === false)
    if (shouldClear) {
      try {
        const cleared = transport.clearSavedSession()
        console.log('[IPC] openclaw:start-whatsapp-login clearSavedSession ok=%s', cleared?.ok)
      } catch (err) {
        console.warn('[IPC] openclaw:start-whatsapp-login clearSavedSession error', err)
      }
    }

    const send = (payload) => {
      const text = typeof payload === 'object' ? JSON.stringify(payload) : String(payload)
      console.log('[IPC] openclaw:data -> renderer (length=' + text.length + ')')
      if (win && !win.isDestroyed()) win.webContents.send('openclaw:data', payload)
    }

    /** Flag para evitar doble arranque de daemon en onLinked. */
    let linkedSyncInProgress = false

    /**
     * Cuando se detecta vinculacion exitosa, emite evento al renderer
     * y notifica al backend para persistir el estado.
     * @param {{ linked: boolean; phone_number?: string }} data
     */
    const onLinked = async (data) => {
      if (linkedSyncInProgress) {
        console.log('[IPC] onLinked: ya en progreso, ignorando evento duplicado')
        return
      }
      linkedSyncInProgress = true
      const phone =
        data.phone_number ||
        transport.ensureOwnPhone(data.phone_number) ||
        null
      const payload = { linked: true, phone_number: phone || undefined }
      console.log('[IPC] openclaw:linked -> renderer', JSON.stringify(payload))
      if (win && !win.isDestroyed()) {
        win.webContents.send('openclaw:linked', payload)
      }

      void transport.startDaemon('ipc_linked')
      broadcastWhatsAppStatus()

      await syncLinkedStatusToBackend({
        linked: true,
        phone_number: phone,
        source: 'electron',
      })

      // Segunda pasada: credenciales Baileys a veces llegan justo después del login.
      if (!phone) {
        setTimeout(() => {
          void (async () => {
            const delayed = transport.ensureOwnPhone(null)
            if (!delayed) return
            broadcastWhatsAppStatus()
            if (win && !win.isDestroyed()) {
              win.webContents.send('openclaw:linked', { linked: true, phone_number: delayed })
            }
            await syncLinkedStatusToBackend({
              linked: true,
              phone_number: delayed,
              source: 'electron-phone-retry',
            })
          })()
        }, 2000)
      }
      linkedSyncInProgress = false
    }

    try {
      const result = await whatsappService.startWhatsAppLogin({
        onChunk: send,
        onLinked,
        onExit: (info) => {
          console.log('[IPC] openclaw:exit -> renderer', JSON.stringify(info))
          if (win && !win.isDestroyed()) win.webContents.send('openclaw:exit', info)
        },
      })
      console.log('[IPC] openclaw:start-whatsapp-login resultado:', JSON.stringify(result))
      return result
    } catch (err) {
      console.error('[IPC] openclaw:start-whatsapp-login error:', err)
      return { ok: false, error: String(err) }
    }
  })

  ipcMain.handle('openclaw:stop', async () => whatsappService.stop())

  ipcMain.handle('whatsapp:get-status', async () => transport.getStatus())

  ipcMain.handle('whatsapp:start-daemon', async () => transport.startDaemon('manual'))

  ipcMain.handle('whatsapp:stop-daemon', async () => transport.stopDaemon())

  // ─── A03: WhatsApp logout / restore session ──────────────────

  ipcMain.handle('whatsapp:logout', async () => {
    try {
      console.log('[IPC] whatsapp:logout — limpiando sesión WhatsApp')

      // 1. Limpiar credenciales locales y safeStorage + detener daemon
      const clearResult = transport.clearSavedSession()
      console.log('[IPC] whatsapp:logout: clearSavedSession ok=%s', clearResult.ok)

      // 2. Notificar al backend: evento disconnected
      const phone = transport.ensureOwnPhone(null) || transport.getStatus()?.phone_number
      void backendChannelClient.postChannelEvent({
        event: 'disconnected',
        phone_number: phone,
        error: 'user_logout',
        source: 'electron-logout',
      }).then((r) => {
        console.log('[IPC] whatsapp:logout: backend notified ok=%s', r.ok)
      }).catch((err) => {
        console.warn('[IPC] whatsapp:logout: backend notify error', err)
      })

      broadcastWhatsAppStatus()
      return { ok: true, needs_qr: true }
    } catch (err) {
      console.error('[IPC] whatsapp:logout error:', err)
      return { ok: false, error: String(err) }
    }
  })

  ipcMain.handle('whatsapp:restore-session', async () => {
    try {
      console.log('[IPC] whatsapp:restore-session — intentando restaurar sin QR')

      const result = await restoreFromSavedCreds({
        secureStorage,
        transport,
      })

      console.log(
        '[IPC] whatsapp:restore-session resultado: ok=%s needs_qr=%s linked=%s phone=%s',
        result.ok,
        result.needs_qr,
        result.linked,
        result.phone_number || 'null',
      )

      broadcastWhatsAppStatus()

      if (result.ok && result.linked) {
        // Notificar al backend: evento linked (reconexión exitosa sin QR)
        void backendChannelClient.postChannelEvent({
          event: 'linked',
          phone_number: result.phone_number || transport.ensureOwnPhone(null),
          source: 'electron-restore-session',
        }).then((r) => {
          console.log('[IPC] whatsapp:restore-session: backend linked ok=%s', r.ok)
        }).catch((err) => {
          console.warn('[IPC] whatsapp:restore-session: backend linked error', err)
        })
      } else if (result.needs_qr) {
        // Notificar al backend: necesita QR
        void backendChannelClient.postChannelEvent({
          event: 'disconnected',
          error: result.error || 'needs_qr',
          source: 'electron-restore-session',
        }).catch(() => {})
      }

      return result
    } catch (err) {
      console.error('[IPC] whatsapp:restore-session error:', err)
      return { ok: false, needs_qr: true, linked: false, error: String(err) }
    }
  })

  ipcMain.handle('whatsapp:send-message', async (_e, payload) => {
    if (!payload || typeof payload !== 'object') {
      return { ok: false, error: 'invalid_payload' }
    }
    return transport.sendMessage(
      payload.to,
      payload.text,
    )
  })

  ipcMain.handle('openclaw:install-automation-plugins', async (_e, packages) => {
    const win = BrowserWindow.getFocusedWindow() || BrowserWindow.getAllWindows()[0]
    const send = (payload) => {
      if (win && !win.isDestroyed()) win.webContents.send('openclaw:data', payload)
    }
    return whatsappService.installAutomationPlugins({ onChunk: send, packages })
  })

  ipcMain.handle('dot:whatsapp-qr-data-url', async (_e, payload) => {
    try {
      // Limitar payload a 4096 bytes para prevenir DoS por memoria
      if (typeof payload !== 'string' || payload.length > 4096) {
        return null
      }
      const QRCode = require('qrcode')
      return await QRCode.toDataURL(payload, { width: 520, margin: 2 })
    } catch {
      return null
    }
  })

  // Inicializar memory-store (memoria semántica local con embeddings ONNX)
  try {
    memoryStore.init()
    console.log('[IPC] MemoryStore inicializado con embeddings ONNX locales')
  } catch (err) {
    console.warn('[IPC] No se pudo inicializar MemoryStore:', err.message)
  }

  // FASE 3.2: Inicializar file-indexer (índice persistente de archivos del usuario)
  /** @type {import('./file-indexer.cjs').FileIndexer | null} */
  let fileIndexer = null
  try {
    const embeddings = require('./embeddings.cjs')
    fileIndexer = new FileIndexer()
    fileIndexer.init(localDb, embeddings, null /* jobScheduler opcional */)
    console.log('[IPC] FileIndexer inicializado con índice persistente de archivos')
  } catch (err) {
    console.warn('[IPC] No se pudo inicializar FileIndexer:', err.message)
  }

  // ─── Local SQLite DB ───────────────────────────────

  ipcMain.handle('dot:local-db:profile-get', async (_event, key) => {
    return localDb.getProfile(key);
  });

  ipcMain.handle('dot:local-db:profile-set', async (_event, key, value) => {
    localDb.setProfile(key, value);
  });

  ipcMain.handle('dot:local-db:profile-all', async () => {
    return localDb.getAllProfile();
  });

  ipcMain.handle('dot:local-db:automations-list', async () => {
    return localDb.getAutomations();
  });

  ipcMain.handle('dot:local-db:automation-save', async (_event, auto) => {
    localDb.saveAutomation(auto);
  });

  ipcMain.handle('dot:local-db:automation-delete', async (_event, id) => {
    localDb.deleteAutomation(id);
  });

  ipcMain.handle('dot:local-db:oauth-get', async (_event, provider) => {
    return localDb.getOAuthToken(provider);
  });

  ipcMain.handle('dot:local-db:oauth-save', async (_event, provider, tokenData) => {
    localDb.saveOAuthToken(provider, tokenData);
  });

  ipcMain.handle('dot:local-db:oauth-delete', async (_event, provider) => {
    localDb.deleteOAuthToken(provider);
  });

  ipcMain.handle('dot:local-db:memory-add', async (_event, content, category, importance) => {
    return localDb.addMemory(content, category, importance);
  });

  ipcMain.handle('dot:local-db:memory-search', async (_event, query, limit) => {
    return localDb.searchMemory(query, limit);
  });

  ipcMain.handle('dot:local-db:conversation-save', async (_event, id, title, channel) => {
    localDb.saveConversation(id, title, channel);
  });

  ipcMain.handle('dot:local-db:message-add', async (_event, id, convId, role, content, toolTrace) => {
    localDb.addMessage(id, convId, role, content, toolTrace);
  });

  ipcMain.handle('dot:local-db:messages-by-conv', async (_event, convId) => {
    return localDb.getConversationMessages(convId);
  });

  ipcMain.handle('dot:local-db:job-add', async (_event, id, name, cronExpr, instruction) => {
    localDb.addJob(id, name, cronExpr, instruction);
  });

  ipcMain.handle('dot:local-db:jobs-pending', async () => {
    return localDb.getPendingJobs();
  });

  ipcMain.handle('dot:local-db:job-status', async (_event, id, status, errorLog) => {
    localDb.updateJobStatus(id, status, errorLog);
  });

  ipcMain.handle('dot:local-db:kv-get', async (_event, key, namespace) => {
    return localDb.kvGet(key, namespace);
  });

  ipcMain.handle('dot:local-db:kv-set', async (_event, key, value, namespace) => {
    localDb.kvSet(key, value, namespace);
  });

  // ─── Memory: búsqueda semántica local con ONNX (Fase 1.3) ──
  ipcMain.handle('dot:memory:search-semantic', async (_e, query) => {
    if (typeof query !== 'string' || !query.trim()) {
      return { ok: false, error: 'query requerida' }
    }
    try {
      const results = await memoryStore.searchSemantic(query.trim(), 5)
      return { ok: true, results }
    } catch (err) {
      return { ok: false, error: String(err).slice(0, 300) }
    }
  })

  // FASE 3.2: búsqueda en índice persistente de archivos (file-indexer, no memory-store)
  ipcMain.handle('dot:memory:search-files', async (_e, query, limit) => {
    if (typeof query !== 'string' || !query.trim()) {
      return { ok: false, error: 'query requerida' }
    }
    if (!fileIndexer) {
      return { ok: false, error: 'file-indexer no disponible' }
    }
    try {
      const maxResults = typeof limit === 'number' && limit > 0 ? Math.min(limit, 50) : 20
      const results = await fileIndexer.searchFiles(query.trim(), maxResults)
      return { ok: true, results }
    } catch (err) {
      return { ok: false, error: String(err).slice(0, 300) }
    }
  })

  // ─── Sandbox de ejecución de código (M2S1-A) ─────────
  ipcMain.handle('dot:code-executor:execute', async (_event, code, inputData, timeoutMs) => {
    return codeExecutor.executeCode(code, inputData, timeoutMs);
  });
}
