const { contextBridge, ipcRenderer } = require('electron')

// ═══════════════════════════════════════════════════════════
// WhatsApp API compartida entre namespaces "whatsapp" y "openclaw" (alias legacy IPC)
// ═══════════════════════════════════════════════════════════
const whatsappApi = {
  getStatus: () => ipcRenderer.invoke('whatsapp:get-status'),
  startDaemon: () => ipcRenderer.invoke('whatsapp:start-daemon'),
  stopDaemon: () => ipcRenderer.invoke('whatsapp:stop-daemon'),
  sendMessage: (payload) => ipcRenderer.invoke('whatsapp:send-message', payload),
  logout: () => ipcRenderer.invoke('whatsapp:logout'),
  restoreSession: () => ipcRenderer.invoke('whatsapp:restore-session'),
  // ── Login QR + plugins (IPC legacy openclaw:*; transporte real vía Baileys) ──
  startWhatsAppLogin: (opts) => ipcRenderer.invoke('openclaw:start-whatsapp-login', opts || {}),
  stop: () => ipcRenderer.invoke('openclaw:stop'),
  installAutomationPlugins: (packages) =>
    ipcRenderer.invoke('openclaw:install-automation-plugins', packages),
  /** Alias: limpia sesión WA (mismo IPC que .logout). */
  logoutWhatsApp: () => ipcRenderer.invoke('whatsapp:logout'),
  qrDataUrl: (text) => ipcRenderer.invoke('dot:whatsapp-qr-data-url', text),
  onData: (listener) => {
    const handler = (_e, payload) => listener(payload)
    ipcRenderer.on('openclaw:data', handler)
    return () => ipcRenderer.removeListener('openclaw:data', handler)
  },
  onExit: (listener) => {
    const handler = (_e, payload) => listener(payload)
    ipcRenderer.on('openclaw:exit', handler)
    return () => ipcRenderer.removeListener('openclaw:exit', handler)
  },
  onLinked: (listener) => {
    const handler = (_e, payload) => listener(payload)
    ipcRenderer.on('openclaw:linked', handler)
    return () => ipcRenderer.removeListener('openclaw:linked', handler)
  },
  onStatus: (listener) => {
    const handler = (_e, payload) => listener(payload)
    ipcRenderer.on('whatsapp:status', handler)
    return () => ipcRenderer.removeListener('whatsapp:status', handler)
  },
  onInbound: (listener) => {
    const handler = (_e, payload) => listener(payload)
    ipcRenderer.on('whatsapp:inbound', handler)
    return () => ipcRenderer.removeListener('whatsapp:inbound', handler)
  },
  onMediaDownloaded: (listener) => {
    const handler = (_e, payload) => listener(payload)
    ipcRenderer.on('whatsapp:media-downloaded', handler)
    return () => ipcRenderer.removeListener('whatsapp:media-downloaded', handler)
  },
}

contextBridge.exposeInMainWorld('desktop', {
  platform: process.platform,
  setNativeTheme: (theme) => ipcRenderer.invoke('dot:set-native-theme', theme),
  openUrl: (url) => ipcRenderer.invoke('dot:open-url', url),
  openPath: (filePath) => ipcRenderer.invoke('dot:open-path', filePath),
  openMicSettings: () => ipcRenderer.invoke('dot:open-mic-settings'),
  micStatus: () => ipcRenderer.invoke('dot:mic-status'),
  systemNotify: (title, body) => ipcRenderer.invoke('dot:system-notify', title, body),
  notifyAutomationResult: (payload) => ipcRenderer.invoke('dot:automation-notify', payload),
  onAutomationNotificationClick: (listener) => {
    const handler = (_event, payload) => listener(payload)
    ipcRenderer.on('dot:automation-notification-clicked', handler)
    return () => ipcRenderer.removeListener('dot:automation-notification-clicked', handler)
  },
  createReminderTask: (payload) => ipcRenderer.invoke('dot:reminder-task-create', payload),
  secureSession: {
    save: (json) => ipcRenderer.invoke('dot:secure-session-save', json),
    load: () => ipcRenderer.invoke('dot:secure-session-load'),
    clear: () => ipcRenderer.invoke('dot:secure-session-clear'),
  },
  oauthSubject: {
    save: (id) => ipcRenderer.invoke('dot:oauth-subject-save', id),
    load: () => ipcRenderer.invoke('dot:oauth-subject-load'),
  },
  usbSerial: {
    /** Serial de fabrica del pendrive (opcional hint si hay varios). */
    get: (hint) => ipcRenderer.invoke('dot:usb-serial', hint),
    /** Hay pendrive detectado? (respeta bypass dev NORDIK_SKIP_USB_GATE=1). */
    isPresent: () => ipcRenderer.invoke('dot:usb-present'),
    getDrivePath: () => ipcRenderer.invoke('dot:usb-present').then(r => r.drivePath),
    bind: (serial, drivePath) => ipcRenderer.invoke('dot:pendrive-bind', serial, drivePath),
    unbind: () => ipcRenderer.invoke('dot:pendrive-unbind'),
    onLost: (listener) => {
      const handler = (_event, payload) => listener(payload)
      ipcRenderer.on('dot:usb-lost', handler)
      return () => ipcRenderer.removeListener('dot:usb-lost', handler)
    },
  },
  hardwareBind: {
    save: (fingerprint) => ipcRenderer.invoke('dot:hardware-bind-save', fingerprint),
    load: () => ipcRenderer.invoke('dot:hardware-bind-load'),
    clear: () => ipcRenderer.invoke('dot:hardware-bind-clear'),
  },
  recoveryKey: {
    save: (key) => ipcRenderer.invoke('dot:recovery-key-save', key),
    load: () => ipcRenderer.invoke('dot:recovery-key-load'),
  },
  // ========================================================
  // Pendrive setup (encriptacion real del USB)
  // ========================================================
  pendriveSetup: {
    setup: (serial, drivePath) => ipcRenderer.invoke('dot:pendrive-setup', serial, drivePath),
    status: () => ipcRenderer.invoke('dot:pendrive-setup-status'),
    verifyVault: (serial, drivePath) => ipcRenderer.invoke('dot:vault-verify', serial, drivePath),
    createVault: (serial, drivePath) => ipcRenderer.invoke('dot:vault-create', serial, drivePath),
    listDevices: () => ipcRenderer.invoke('dot:vault-list-devices'),
    findValid: () => ipcRenderer.invoke('dot:vault-find-valid'),
    getVaultInfo: () => ipcRenderer.invoke('dot:recovery-key-get'),
  },
  // ========================================================
  // Local tools (Fase 3+)
  // ========================================================
  localTools: {
    readFile: (relativePath) => ipcRenderer.invoke('dot:tools-read-file', relativePath),
    writeFile: (relativePath, content) => ipcRenderer.invoke('dot:tools-write-file', relativePath, content),
    downloadUrlToDesktop: (url, relativePath) =>
      ipcRenderer.invoke('dot:tools-download-url', url, relativePath || ''),
    listFiles: (relativePath) => ipcRenderer.invoke('dot:tools-list-files', relativePath),
    deleteFile: (relativePath) => ipcRenderer.invoke('dot:tools-delete-file', relativePath),
    getAuditLog: (limit) => ipcRenderer.invoke('dot:tools-audit-log', limit),
    getSandboxInfo: () => ipcRenderer.invoke('dot:tools-sandbox-info'),
    getPermissionStatus: (actionId) => ipcRenderer.invoke('dot:tools-permission-status', actionId),
    setPermission: (actionId, decision) => ipcRenderer.invoke('dot:tools-set-permission', actionId, decision),
    resetAllPermissions: () => ipcRenderer.invoke('dot:tools-reset-permissions'),
  },
  // ========================================================
  // WhatsApp login bridge (alias legacy openclaw → whatsapp)
  // ========================================================
  openclaw: whatsappApi,
  whatsapp: whatsappApi,
  /** Acceso directo por si el preload viejo no tenía whatsapp.logout */
  whatsappLogout: () => ipcRenderer.invoke('whatsapp:logout'),
  // ========================================================
  // WhatsApp QR data URL generation
  // ========================================================
  renderWhatsappQrDataUrl: (payload) =>
    ipcRenderer.invoke('dot:whatsapp-qr-data-url', payload),
  // ========================================================
  // File search (P2.1) — soporta scope: "sandbox"|"full"
  // ========================================================
  fileSearch: {
    search: (params) =>
      ipcRenderer.invoke('dot:file-search', params),
    checkPermission: () =>
      ipcRenderer.invoke('dot:file-search-permission-status'),
    setPermission: (decision) =>
      ipcRenderer.invoke('dot:file-search-set-permission', decision),
  },
  // ========================================================
  // Document parser (T10)
  // ========================================================
  documentParser: {
    parse: (filePath, mimeType) =>
      ipcRenderer.invoke('dot:document-parse', filePath, mimeType),
    parseFromData: (base64Data, mimeType) =>
      ipcRenderer.invoke('dot:document-parse-data', base64Data, mimeType),
    generateDocx: (params) =>
      ipcRenderer.invoke('dot:document-generate-docx', params),
  },
  // ========================================================
  // SQLite local DB (M1S1-B) — perfil, automatizaciones, tokens, memoria, KV
  // ========================================================
  localDb: {
    getProfile: (key) => ipcRenderer.invoke('dot:local-db:profile-get', key),
    setProfile: (key, value) => ipcRenderer.invoke('dot:local-db:profile-set', key, value),
    getAllProfile: () => ipcRenderer.invoke('dot:local-db:profile-all'),
    getAutomations: () => ipcRenderer.invoke('dot:local-db:automations-list'),
    saveAutomation: (auto) => ipcRenderer.invoke('dot:local-db:automation-save', auto),
    deleteAutomation: (id) => ipcRenderer.invoke('dot:local-db:automation-delete', id),
    getOAuthToken: (provider) => ipcRenderer.invoke('dot:local-db:oauth-get', provider),
    saveOAuthToken: (provider, tokenData) => ipcRenderer.invoke('dot:local-db:oauth-save', provider, tokenData),
    deleteOAuthToken: (provider) => ipcRenderer.invoke('dot:local-db:oauth-delete', provider),
    addMemory: (content, category, importance) => ipcRenderer.invoke('dot:local-db:memory-add', content, category, importance),
    searchMemory: (query, limit) => ipcRenderer.invoke('dot:local-db:memory-search', query, limit),
    saveConversation: (id, title, channel) => ipcRenderer.invoke('dot:local-db:conversation-save', id, title, channel),
    addMessage: (id, convId, role, content, toolTrace) => ipcRenderer.invoke('dot:local-db:message-add', id, convId, role, content, toolTrace),
    getConversationMessages: (convId) => ipcRenderer.invoke('dot:local-db:messages-by-conv', convId),
    addJob: (id, name, cronExpr, instruction) => ipcRenderer.invoke('dot:local-db:job-add', id, name, cronExpr, instruction),
    getPendingJobs: () => ipcRenderer.invoke('dot:local-db:jobs-pending'),
    updateJobStatus: (id, status, errorLog) => ipcRenderer.invoke('dot:local-db:job-status', id, status, errorLog),
    kvGet: (key, namespace) => ipcRenderer.invoke('dot:local-db:kv-get', key, namespace),
    kvSet: (key, value, namespace) => ipcRenderer.invoke('dot:local-db:kv-set', key, value, namespace),
  },
  // ========================================================
  // Sandbox de ejecución de código (M2S1-A) — isolated-vm
  // ========================================================
  executeCode: (code, inputData, timeoutMs) =>
    ipcRenderer.invoke('dot:code-executor:execute', code, inputData, timeoutMs),
})
