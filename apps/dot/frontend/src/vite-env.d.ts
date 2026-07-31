/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_API_BASE_URL?: string
  readonly VITE_FIREBASE_API_KEY?: string
  readonly VITE_FIREBASE_AUTH_DOMAIN?: string
  readonly VITE_FIREBASE_PROJECT_ID?: string
  readonly VITE_FIREBASE_APP_ID?: string
  /** Solo dev en navegador (sin Electron): omitir puerta USB en el renderer. */
  readonly VITE_SKIP_USB_GATE?: string
  /** `1`: oculta acceso dev a `#/provisioner` en login (ventas usan solo panel :8001). */
  readonly VITE_PANEL_ONLY_USB?: string
  readonly VITE_DOT_PROVISIONER?: string
  readonly VITE_DOT_VENTAS?: string
  /** Mismo valor que ADMIN_API_KEY del backend; solo app Provisioner (soporte interno). */
  readonly VITE_ADMIN_API_KEY?: string
}

declare global {
  interface Window {
    desktop?: {
      platform: string
      setNativeTheme: (theme: 'dark' | 'light') => Promise<{ ok: boolean; error?: string }>
      openUrl: (url: string) => Promise<{ ok?: boolean }>
      openPath?: (filePath: string) => Promise<{ ok: boolean; error?: string }>
      openMicSettings?: () => Promise<{ ok: boolean; error?: string }>
      micStatus?: () => Promise<{ ok: boolean; status: string }>
      systemNotify?: (title: string, body: string) => Promise<{ ok: boolean; error?: string }>
      notifyAutomationResult?: (payload: {
        title?: string
        body?: string
        autoId?: string
        autoName?: string
        executedAt?: string
        preview?: string
      }) => Promise<{ ok: boolean; error?: string }>
      onAutomationNotificationClick?: (
        listener: (payload: {
          autoId?: string
          autoName?: string
          executedAt?: string
          preview?: string
        }) => void,
      ) => () => void
      createReminderTask?: (payload: {
        id: string
        text: string
        dueAtIso: string
      }) => Promise<{ ok: boolean; error?: string; detail?: string }>
      secureSession?: {
        save: (json: string) => Promise<{ ok: boolean; encrypted?: boolean; warning?: string; error?: string }>
        load: () => Promise<string | null>
        clear: () => Promise<{ ok: boolean }>
      }
      oauthSubject?: {
        save: (id: string) => Promise<{ ok: boolean }>
        load: () => Promise<string | null>
      }
      usbSerial?: {
        get: (hint?: string) => Promise<{
          serial: string | null
          devices: string[]
          error?: string
        }>
        isPresent: () => Promise<{
          present: boolean
          serial: string | null
          skipGate?: boolean
          boundSerial?: string | null
          vaultOk?: boolean
          drivePath?: string | null
          reason?: string
          error?: string
        }>
        bind: (serial: string, drivePath?: string) => Promise<{ ok: boolean }>
        unbind: () => Promise<{ ok: boolean }>
        getDrivePath: () => Promise<string | null | undefined>
        onLost: (
          listener: (payload: { reason: 'disconnected' | 'mismatch' }) => void,
        ) => () => void
      }
      hardwareBind?: {
        save: (fingerprint: string) => Promise<{ ok: boolean }>
        load: () => Promise<string | null>
        clear: () => Promise<{ ok: boolean }>
      }
      recoveryKey?: {
        save: (key: string) => Promise<{ ok: boolean; encrypted?: boolean; warning?: string; error?: string }>
        load: () => Promise<string | null>
      }
      renderWhatsappQrDataUrl?: (payload: string) => Promise<string | null>
      /**
       * Alias legacy: mismo objeto que `window.desktop.whatsapp`.
       * Mantenido solo para retrocompatibilidad; no usa OpenClaw.
       * @deprecated Usar `window.desktop.whatsapp` en su lugar.
       */
      openclaw?: Window['desktop']['whatsapp']
      /** Alias de whatsapp.logout (preload nuevo). */
      whatsappLogout?: () => Promise<{ ok: boolean; needs_qr?: boolean; error?: string }>
      whatsapp?: {
        getStatus: () => Promise<{
          state: 'idle' | 'logging_in' | 'starting' | 'connected' | 'disconnected' | 'restarting'
          linked: boolean
          daemonRunning: boolean
          loginRunning: boolean
          phone_number: string | null
          error: string | null
          restartAttempts: number
        }>
        startDaemon: () => Promise<{ ok: boolean; error?: string }>
        stopDaemon: () => Promise<{ ok: boolean }>
        sendMessage?: (payload: { to: string; text: string }) => Promise<{ ok: boolean; error?: string }>
        /** Cierra sesión local Baileys y notifica al backend (necesita QR de nuevo). */
        logout: () => Promise<{ ok: boolean; needs_qr?: boolean; error?: string }>
        /** Intenta restaurar credenciales guardadas sin escanear QR. */
        restoreSession: () => Promise<{
          ok: boolean
          needs_qr?: boolean
          linked?: boolean
          phone_number?: string | null
          error?: string
        }>
        onStatus: (
          listener: (payload: {
            state: 'idle' | 'logging_in' | 'starting' | 'connected' | 'disconnected' | 'restarting'
            linked: boolean
            daemonRunning: boolean
            loginRunning: boolean
            phone_number: string | null
            error: string | null
            restartAttempts: number
          }) => void,
        ) => () => void
        onInbound: (
          listener: (payload: {
            message_id?: string
            from_phone?: string
            to_phone?: string
            text?: string
            chat_jid?: string
            group_name?: string
            uid?: string | null
            stored?: boolean
            status?: string
          }) => void,
        ) => () => void
        onMediaDownloaded: (
          listener: (payload: {
            message_id: string
            ok: boolean
            file_path?: string
            mime_type?: string
            size?: number
            error?: string
          }) => void,
        ) => () => void
        /** Inicia el flujo de login QR (Baileys). Devuelve el resultado del arranque. */
        startWhatsAppLogin: (opts?: {
          onChunk?: (chunk: { stream: 'stdout' | 'stderr'; text: string }) => void
          onLinked?: (data: { linked: boolean; phone_number?: string }) => void
          onExit?: (info: { code: number | null; signal: string | null }) => void
        }) => Promise<{ ok: boolean; error?: string; needs_qr?: boolean }>
        /** Detiene el proceso de vinculación en curso. */
        stop: () => Promise<{ ok: boolean }>
        /** Stream de logs del transporte WhatsApp durante el login QR. */
        onData: (
          listener: (payload: { stream: string; text: string }) => void,
        ) => () => void
        /** Evento de salida del proceso de vinculación. */
        onExit: (
          listener: (info: { code: number | null; signal: string | null }) => void,
        ) => () => void
        /** Evento cuando la sesión WhatsApp quedó vinculada. */
        onLinked: (
          listener: (data: { linked: boolean; phone_number?: string }) => void,
        ) => () => void
      }
      // ========================================================
      // Pendrive setup (encriptación real del USB)
      // ========================================================
      pendriveSetup?: {
        setup: (serial: string, drivePath: string) => Promise<{ ok: boolean; token?: string; warning?: string; error?: string }>
        status: () => Promise<{ ok: boolean; devices?: PendriveDeviceInfo[]; error?: string }>
        verifyVault: (serial: string, drivePath: string) => Promise<{ ok: boolean; token?: string; warning?: string; error?: string }>
        createVault: (serial: string, drivePath: string) => Promise<{ ok: boolean; token?: string; warning?: string; error?: string }>
        listDevices: () => Promise<{ ok: boolean; devices?: PendriveDeviceInfo[]; error?: string }>
        findValid: () => Promise<{ ok: boolean; serial?: string; drivePath?: string; token?: string; warning?: string; error?: string }>
        getVaultInfo: () => Promise<{ ok: boolean; serial?: string; drivePath?: string; error?: string }>
      }
      // ========================================================
      // Local tools (Fase 3+)
      // ========================================================
      localTools?: {
        readFile: (relativePath: string) => Promise<LocalToolsFileResult>
        writeFile: (relativePath: string, content: string) => Promise<LocalToolsWriteResult>
        downloadUrlToDesktop: (
          url: string,
          relativePath?: string,
        ) => Promise<LocalToolsWriteResult & { bytes?: number }>
        listFiles: (relativePath?: string) => Promise<LocalToolsListResult>
        deleteFile: (relativePath: string) => Promise<LocalToolsDeleteResult>
        getAuditLog: (limit?: number) => Promise<LocalToolsAuditResult>
        getSandboxInfo: () => Promise<LocalToolsSandboxInfo>
        getPermissionStatus: (actionId: string) => Promise<string>
        setPermission: (actionId: string, decision: 'once' | 'always' | 'denied') => Promise<{ ok: boolean }>
        resetAllPermissions: () => Promise<{ ok: boolean }>
      }
      provisioner?: {
        getRuntimeFlags: () => Promise<{ provisionerMode?: boolean; ventasMode?: boolean }>
        getMachineSerial: () => Promise<string | null>
        listUsbDevices: () => Promise<ProvisionerUsbListResult>
        installOnUsb: (payload: ProvisionerInstallRequest) => Promise<ProvisionerInstallResult>
      }
      // ========================================================
      // Document parser (T10)
      // ========================================================
      documentParser?: {
        parse: (filePath: string, mimeType: string) => Promise<
          { ok: true; text: string } | { ok: false; error: string }
        >
        parseFromData: (base64Data: string, mimeType: string) => Promise<
          { ok: true; text: string } | { ok: false; error: string }
        >
      }
    }
  }
}

interface LocalToolsFileResult {
  ok: boolean
  content?: string
  path?: string
  error?: string
}

interface LocalToolsWriteResult {
  ok: boolean
  path?: string
  error?: string
}

interface LocalToolsListResult {
  ok: boolean
  files?: Array<{ name: string; isDirectory: boolean; path: string }>
  path?: string
  error?: string
}

interface LocalToolsDeleteResult {
  ok: boolean
  error?: string
}

interface LocalToolsAuditResult {
  ok: boolean
  entries?: Array<{ timestamp: string; action: string; details: unknown }>
  error?: string
}

interface LocalToolsSandboxInfo {
  homePath: string
  exists: boolean
  allowedRoots: string[]
  fileCount: number
  auditCount: number
}

interface PendriveDeviceInfo {
  serial: string
  driveLetter: string
  hasVault: boolean
  vaultOk?: boolean
  vaultPath?: string | null
}

interface ProvisionerInstallRequest {
  serial: string
  driveLetter: string
  force?: boolean
  copyInstaller?: boolean
  apiBase?: string
}

interface ProvisionerStep {
  key?: string
  status?: 'ok' | 'warn' | 'error' | 'skipped'
  message?: string
}

interface ProvisionerUsbDevice {
  serial: string
  driveLetter: string
}

interface ProvisionerUsbListResult {
  ok: boolean
  code?: string
  error?: string
  devices?: ProvisionerUsbDevice[]
}

interface ProvisionerInstallResult {
  ok: boolean
  code?: string
  message?: string
  error?: string
  steps?: ProvisionerStep[]
  result?: {
    driveLetter?: string
    serial?: string
    vaultRegenerated?: boolean
    installerCopied?: boolean
    installerPath?: string | null
    recoveryKey?: string | null
    recoveryFile?: string | null
  } | null
}

export {}

// ─── Web Speech API (M3.1 voz) ───────────────────────────
interface SpeechRecognitionEvent extends Event {
  readonly resultIndex: number
  readonly results: SpeechRecognitionResultList
}

interface SpeechRecognitionResultList {
  readonly length: number
  item(index: number): SpeechRecognitionResult
  [index: number]: SpeechRecognitionResult
}

interface SpeechRecognitionResult {
  readonly isFinal: boolean
  readonly length: number
  item(index: number): SpeechRecognitionAlternative
  [index: number]: SpeechRecognitionAlternative
}

interface SpeechRecognitionAlternative {
  readonly transcript: string
  readonly confidence: number
}

interface SpeechRecognitionErrorEvent extends Event {
  readonly error: string
  readonly message: string
}

interface SpeechRecognition extends EventTarget {
  continuous: boolean
  grammars: unknown
  interimResults: boolean
  lang: string
  maxAlternatives: number
  onaudioend: ((this: SpeechRecognition, ev: Event) => void) | null
  onaudiostart: ((this: SpeechRecognition, ev: Event) => void) | null
  onend: ((this: SpeechRecognition, ev: Event) => void) | null
  onerror: ((this: SpeechRecognition, ev: SpeechRecognitionErrorEvent) => void) | null
  onnomatch: ((this: SpeechRecognition, ev: SpeechRecognitionEvent) => void) | null
  onresult: ((this: SpeechRecognition, ev: SpeechRecognitionEvent) => void) | null
  onsoundend: ((this: SpeechRecognition, ev: Event) => void) | null
  onsoundstart: ((this: SpeechRecognition, ev: Event) => void) | null
  onspeechend: ((this: SpeechRecognition, ev: Event) => void) | null
  onspeechstart: ((this: SpeechRecognition, ev: Event) => void) | null
  onstart: ((this: SpeechRecognition, ev: Event) => void) | null
  abort(): void
  start(): void
  stop(): void
}

declare var SpeechRecognition: {
  prototype: SpeechRecognition
  new(): SpeechRecognition
}

declare var webkitSpeechRecognition: {
  prototype: SpeechRecognition
  new(): SpeechRecognition
}
