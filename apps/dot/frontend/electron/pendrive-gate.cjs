/**
 * Puerta de arranque y monitor de pendrive DOT (llave USB obligatoria).
 *
 * - En producción la app no abre la ventana principal hasta detectar un serial USB válido.
 * - Si el USB está detectado pero aún no tiene dot.vault, se deja entrar para guiar la provisión.
 * - Tras login, el renderer envía el serial enlazado; si se desconecta o cambia, se emite dot:usb-lost.
 * - La verificación del vault AES-256-GCM previene: clonación con dd, acceso sin llave física autorizada.
 *
 * Estrategia de autostart (T-USB-001):
 * Opción A (RECOMENDADA) — Watcher + tray:
 *   1. Escuchar eventos volumen removible vía WMI (Win32_VolumeChangeEvent) o polling periódico.
 *   2. Buscar archivo dot.vault en raíz del volumen detectado.
 *   3. Si existe, lanzar DOT.exe desde la ruta del pendrive ({drive}\DOT\DOT.exe)
 *      con argumento --usb-drive={drive}: (T-USB-003).
 *   4. No copiar binario a %TEMP%; ejecutar directamente desde USB.
 *   Pros: Funciona en Win10/11 sin GPO; control total sobre detección y lanzamiento.
 *   Contras: Requiere app/instalador en background (dot-tray.exe o servicio).
 *
 * Opción B — Scheduled Task + Event Viewer USB insert:
 *   Configurar tarea programada que se dispare al conectar USB vía Event ID 2003/2006/2100.
 *   Pros: Sin tray constante.
 *   Contras: Configuración GPO compleja; el usuario no ve estado.
 *
 * Opción C — Run key + detección vault al logon:
 *   Actual: autoLaunch.ensureAutoLaunch() registra DOT en HKCU\...\Run.
 *   Pros: Simple.
 *   Contras: Solo ejecuta al iniciar sesión Windows, no al insertar USB.
 *
 * Opción D — Instalador en USB + acceso directo:
 *   Shortcut visible "Iniciar DOT" en pendrive.
 *   Pros: Sin políticas bloqueadas.
 *   Contras: Requiere doble-clic manual.
 *
 * Implementación actual: polling periódico (Opción A simplificada).
 * Para autostart real al insertar USB, implementar watcher WMI (T-USB pendiente).
 * Ver sección 9 del Plan Maestro para detalles.
 *
 * Bypass solo en desarrollo: NORDIK_SKIP_USB_GATE=1 (no usar en builds empaquetados).
 */
const { app, BrowserWindow } = require('electron')
const path = require('node:path')
const usbSerial = require('./usb-serial.cjs')
const pendriveCrypto = require('./pendrive-crypto.cjs')

const POLL_MS = 2500
const USB_LOST_EVENT = 'dot:usb-lost'
const USB_WAIT_REASON = {
  READY: 'ready',
  NO_USB: 'no_usb',
  MULTIPLE_USB: 'multiple_usb',
  NO_VALID_VAULT: 'no_valid_vault',
  DRIVE_UNRESOLVED: 'drive_unresolved',
  VAULT_MISSING: 'vault_missing',
  VAULT_INVALID: 'vault_invalid',
}

/** @type {string | null} */
let boundSerial = null
/** @type {string | null} */
let boundDrivePath = null
/** @type {ReturnType<typeof setTimeout> | null} */
let monitorTimer = null

/**
 * Determina si el gate USB debe saltarse (modo demo).
 *
 * En builds empaquetados (app.isPackaged === true), NUNCA se salta el gate.
 * Solo se permite bypass en desarrollo con DOT_DEMO_MODE=1.
 *
 * @param {import('electron').App} _app
 * @returns {boolean}
 */
function shouldSkipGate(_app) {
  if (_app && _app.isPackaged) return false
  return process.env.DOT_DEMO_MODE === '1'
}

function isDevMode(_app) {
  return _app && !_app.isPackaged
}

function skipUsbGate(_app) {
  return shouldSkipGate(_app)
}

function isVentasBuild() {
  return false
}

/**
 * @param {string | null | undefined} serial
 */
function setBoundSerial(serial) {
  boundSerial = serial ? usbSerial.sanitize(serial) : null
}

function clearBoundSerial() {
  boundSerial = null
  boundDrivePath = null
}

function getBoundSerial() {
  return boundSerial
}

function getBoundDrivePath() {
  return boundDrivePath
}

/**
 * @param {{ reason: 'disconnected' | 'mismatch' }} payload
 */
function broadcastUsbLost(payload) {
  for (const win of BrowserWindow.getAllWindows()) {
    if (!win.isDestroyed()) {
      win.webContents.send(USB_LOST_EVENT, payload)
    }
  }
}

/**
 * Intenta obtener la letra de unidad del USB con el serial dado.
 * @param {string} serial
 * @returns {Promise<string | null>}
 */
async function resolveDrivePath(serial) {
  try {
    return await pendriveCrypto.getDrivePathForSerial(serial)
  } catch {
    return null
  }
}

/**
 * Verifica que el pendrive tenga un dot.vault válido.
 * Si el vault es válido, devuelve la ruta de la unidad y el token.
 * @param {string} serial
 * @param {string} drivePath
 * @returns {Promise<{ ok: boolean, token?: string, warning?: string, error?: string }>}
 */
async function verifyPendriveVault(serial, drivePath) {
  try {
    return await pendriveCrypto.verifyVaultFull(drivePath, serial)
  } catch (err) {
    return { ok: false, error: err.message || 'VAULT_VERIFY_ERROR' }
  }
}

function mapVaultErrorToReason(error) {
  if (error === 'VAULT_NOT_FOUND') return USB_WAIT_REASON.VAULT_MISSING
  if (error) return USB_WAIT_REASON.VAULT_INVALID
  return USB_WAIT_REASON.NO_VALID_VAULT
}

/**
 * Verifica un serial concreto (modo monitor de sesión).
 * @param {string} serial
 * @returns {Promise<{ serial: string | null, skipGate: boolean, vaultOk: boolean, drivePath: string | null, reason: string, error?: string }>}
 */
async function probeBoundSerial(serial) {
  const drivePath = await resolveDrivePath(serial)
  if (!drivePath) {
    return {
      serial,
      skipGate: false,
      vaultOk: false,
      drivePath: null,
      reason: USB_WAIT_REASON.DRIVE_UNRESOLVED,
      error: 'DRIVE_NOT_FOUND',
    }
  }
  const vaultResult = await verifyPendriveVault(serial, drivePath)
  return {
    serial,
    skipGate: false,
    vaultOk: vaultResult.ok,
    drivePath,
    reason: vaultResult.ok ? USB_WAIT_REASON.READY : mapVaultErrorToReason(vaultResult.error),
    error: vaultResult.error,
  }
}

function describeWaitReason(result) {
  if (result.reason === USB_WAIT_REASON.NO_USB) {
    return 'No hay pendrive USB conectado.'
  }
  if (result.reason === USB_WAIT_REASON.MULTIPLE_USB) {
    return 'Hay varios USB conectados. Deja solo la llave DOT o provisiona una llave válida.'
  }
  if (result.reason === USB_WAIT_REASON.DRIVE_UNRESOLVED) {
    return 'Se detectó USB pero no se pudo resolver su unidad.'
  }
  if (result.reason === USB_WAIT_REASON.VAULT_MISSING) {
    return 'El USB no está provisionado (falta dot.vault).'
  }
  if (result.reason === USB_WAIT_REASON.VAULT_INVALID) {
    return 'El USB tiene vault inválido o no autorizado.'
  }
  if (result.reason === USB_WAIT_REASON.NO_VALID_VAULT) {
    return 'No se encontró una llave DOT válida entre los USB conectados.'
  }
  return result.error || 'Esperando llave DOT...'
}

/**
 * Escanea todos los USB conectados buscando uno que tenga un vault válido.
 * @returns {Promise<{ ok: boolean, serial?: string, drivePath?: string, token?: string, warning?: string, error?: string }>}
 */
async function findValidPendrive() {
  try {
    return await pendriveCrypto.findValidVault()
  } catch (err) {
    return { ok: false, error: err.message || 'FIND_VAULT_ERROR' }
  }
}

/**
 * @param {import('electron').App} app
 * @returns {Promise<{ serial: string | null, skipGate: boolean, vaultOk?: boolean, drivePath?: string }>}
 */
async function probeUsb(app) {
  if (shouldSkipGate(app)) {
    return { serial: 'dev-bypass', skipGate: true, vaultOk: true, drivePath: null, reason: USB_WAIT_REASON.READY }
  }

  // Si ya hay sesión enlazada, validar exclusivamente el serial esperado.
  // Evita falsos "mismatch" cuando hay otros USB conectados.
  if (boundSerial) {
    return probeBoundSerial(boundSerial)
  }

  // En arranque, aceptar cualquier pendrive con vault válido aunque haya múltiples USB.
  const validVault = await findValidPendrive()
  if (validVault.ok && validVault.serial && validVault.drivePath) {
    return {
      serial: validVault.serial,
      skipGate: false,
      vaultOk: true,
      drivePath: validVault.drivePath,
      reason: USB_WAIT_REASON.READY,
    }
  }

  const result = await usbSerial.getUsbStorageSerial()
  if (!result.serial) {
    const multiUsb = typeof result.error === 'string' && result.error.includes('Conecte solo un pendrive')
    return {
      serial: null,
      skipGate: false,
      vaultOk: false,
      drivePath: null,
      reason: multiUsb ? USB_WAIT_REASON.MULTIPLE_USB : USB_WAIT_REASON.NO_USB,
      error: result.error,
    }
  }

  return probeBoundSerial(result.serial)
}

/**
 * Ventana mínima mientras no hay pendrive (solo arranque).
 * @param {import('electron').App} app
 */
function updateGateStatus(gateWin, result) {
  if (!gateWin || gateWin.isDestroyed()) return
  const detail = describeWaitReason(result)
  const js = `(function(){var el=document.getElementById('gate-status');if(el)el.textContent=${JSON.stringify(detail)};})()`
  gateWin.webContents.executeJavaScript(js).catch(() => {})
}

function createGateWindow(app) {
  const win = new BrowserWindow({
    width: 420,
    height: 280,
    resizable: false,
    maximizable: false,
    minimizable: true,
    fullscreenable: false,
    autoHideMenuBar: true,
    backgroundColor: '#0a0a0c',
    show: false,
    webPreferences: {
      nodeIntegration: false,
      contextIsolation: true,
      sandbox: true,
    },
  })
  win.once('ready-to-show', () => win.show())
  win.loadFile(path.join(__dirname, 'gate.html'))
  return win
}

/**
 * Espera la detección del pendrive antes de abrir la ventana principal.
 * Hace polling cada 1 segundo hasta encontrar un USB con vault válido
 * o hasta timeout de 60 segundos. Si timeout, muestra el gate.
 *
 * @param {import('electron').App} _app
 * @returns {Promise<{ serial: string | null, skipGate: boolean, vaultOk?: boolean, drivePath?: string }>}
 */
async function waitForPendriveAtStartup(_app) {
  if (shouldSkipGate(_app)) {
    return { serial: 'dev-bypass', skipGate: true, vaultOk: true, drivePath: null, reason: USB_WAIT_REASON.READY }
  }

  const STARTUP_TIMEOUT_MS = 60000
  const POLL_STARTUP_MS = 1000
  const startedAt = Date.now()
  let gateWin = null

  while (Date.now() - startedAt < STARTUP_TIMEOUT_MS) {
    const result = await probeUsb(_app)
    if (result.serial && result.vaultOk) {
      if (gateWin && !gateWin.isDestroyed()) gateWin.close()
      return result
    }
    if (!gateWin || gateWin.isDestroyed()) {
      gateWin = createGateWindow(_app)
    }
    updateGateStatus(gateWin, result)
    await new Promise((r) => setTimeout(r, POLL_STARTUP_MS))
  }

  return { serial: null, skipGate: false, vaultOk: false, drivePath: null, reason: USB_WAIT_REASON.NO_VALID_VAULT }
}

/**
 * Sondeo único del pendrive encadenado con setTimeout recursivo
 * para evitar race conditions por acumulación de setInterval.
 * @param {import('electron').App} app
 */
function scheduleProbe(app) {
  if (!boundSerial) return

  const startTime = Date.now()
  const promise = probeUsb(app)
  promise.then((result) => {
    const elapsed = Date.now() - startTime
    if (elapsed > POLL_MS) {
      console.warn(
        `[dot-gate] probeUsb tardó ${elapsed}ms (POLL_MS=${POLL_MS}ms) — ` +
        `el sistema está bajo carga y el sondeo se está acumulando`
      )
    }

    if (!result.serial) {
      clearBoundSerial()
      broadcastUsbLost({ reason: 'disconnected' })
    } else if (result.serial !== boundSerial) {
      clearBoundSerial()
      broadcastUsbLost({ reason: 'mismatch' })
    } else if (!result.vaultOk) {
      clearBoundSerial()
      const disconnectedLike =
        result.reason === USB_WAIT_REASON.DRIVE_UNRESOLVED ||
        result.reason === USB_WAIT_REASON.NO_USB
      broadcastUsbLost({ reason: disconnectedLike ? 'disconnected' : 'mismatch' })
    }
  })
  promise.finally(() => {
    monitorTimer = setTimeout(() => scheduleProbe(app), POLL_MS)
  })
}

/**
 * Inicia el monitor de pendrive (polling cada 5 segundos).
 * Si el pendrive se desconecta, pausa la app y muestra el gate.
 *
 * @param {import('electron').App} app
 */
function startPendriveMonitor(app) {
  if (shouldSkipGate(app)) return
  stopPendriveMonitor()
  monitorTimer = setInterval(() => {
    if (!boundSerial) {
      stopPendriveMonitor()
      return
    }
    probeUsb(app).then((result) => {
      if (!result.serial) {
        clearBoundSerial()
        broadcastUsbLost({ reason: 'disconnected' })
      } else if (result.serial !== boundSerial) {
        clearBoundSerial()
        broadcastUsbLost({ reason: 'mismatch' })
      } else if (!result.vaultOk) {
        clearBoundSerial()
        broadcastUsbLost({ reason: 'mismatch' })
      }
    })
  }, 5000)
}

function stopPendriveMonitor() {
  if (monitorTimer) {
    clearInterval(monitorTimer)
    monitorTimer = null
  }
}

function registerPendriveIpc(app, ipcMain) {
  // Handler real: verifica si hay USB presente con vault válido
  ipcMain.handle('dot:usb-present', async () => {
    if (shouldSkipGate(app)) {
      return { present: true, serial: 'dev-bypass', skipGate: true, vaultOk: true, drivePath: null, reason: 'ready', error: null }
    }
    const result = await probeUsb(app)
    return {
      present: result.serial !== null,
      serial: result.serial,
      skipGate: result.skipGate,
      vaultOk: result.vaultOk ?? false,
      drivePath: result.drivePath ?? null,
      reason: result.reason ?? 'unknown',
      error: result.error ?? null,
    }
  })

  // Handler real: enlaza sesión al serial actual del pendrive
  ipcMain.handle('dot:pendrive-bind', async (_event, serial) => {
    if (shouldSkipGate(app)) {
      setBoundSerial('dev-bypass')
      return { ok: true }
    }
    const cleanSerial = usbSerial.sanitize(serial)
    if (!cleanSerial) {
      return { ok: false, error: 'SERIAL_INVALIDO' }
    }
    const drivePath = await pendriveCrypto.getDrivePathForSerial(cleanSerial)
    if (!drivePath) {
      return { ok: false, error: 'DRIVE_NOT_FOUND' }
    }
    boundDrivePath = drivePath
    setBoundSerial(cleanSerial)
    startPendriveMonitor(app)
    return { ok: true }
  })

  ipcMain.handle('dot:pendrive-unbind', () => {
    clearBoundSerial()
    stopPendriveMonitor()
    return { ok: true }
  })

  // Handler real: verifica vault completo con fingerprint hardware
  ipcMain.handle('dot:vault-verify', async (_event, drivePath, serial) => {
    if (shouldSkipGate(app)) {
      return { ok: true, token: 'dev-token' }
    }
    return await pendriveCrypto.verifyVaultFull(drivePath, serial)
  })

  ipcMain.handle('dot:vault-create', async (_event, drivePath, serial) => {
    return await pendriveCrypto.createVault(drivePath, serial)
  })

  // Handler real: lista dispositivos USB
  ipcMain.handle('dot:vault-list-devices', async () => {
    if (shouldSkipGate(app)) {
      return { ok: true, devices: [] }
    }
    try {
      const devices = await pendriveCrypto.listAllUsbDrives()
      return { ok: true, devices }
    } catch (err) {
      return { ok: false, devices: [], error: err.message }
    }
  })

  // Handler real: busca vault válido en todos los USB
  ipcMain.handle('dot:vault-find-valid', async () => {
    if (shouldSkipGate(app)) {
      return { ok: false, error: 'NO_VALID_VAULT' }
    }
    return await pendriveCrypto.findValidVault()
  })
}

module.exports = {
  USB_LOST_EVENT,
  shouldSkipGate,
  waitForPendriveAtStartup,
  startPendriveMonitor,
  stopPendriveMonitor,
  registerPendriveIpc,
  setBoundSerial,
  clearBoundSerial,
  probeUsb,
  getBoundDrivePath,
}
