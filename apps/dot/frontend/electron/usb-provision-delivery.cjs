'use strict'
/* eslint-disable @typescript-eslint/no-require-imports */

/**
 * Provisión comercial USB DOT (Windows).
 * Reutilizable desde CLI, IPC Electron y subprocess Node (auto-venta1).
 *
 * Resultado principal: { ok, serial, drive, recoveryKey, installerPath, error }
 */

const fs = require('node:fs')
const path = require('node:path')

const pendriveCrypto = require('./pendrive-crypto.cjs')
const usbSerial = require('./usb-serial.cjs')
const usbSerialPolicy = require('./usb-serial-policy.cjs')

const DEFAULT_API_BASE = 'http://127.0.0.1:8000'
const FRONTEND_ROOT = path.resolve(__dirname, '..')
const DEFAULT_RELEASE_DIR = path.join(FRONTEND_ROOT, 'release')

/**
 * @param {string} message
 * @param {string} [code]
 * @param {object|null} [details]
 * @param {object} [partial]
 */
function failResult(message, code = 'PROVISION_FAILED', details = null, partial = {}) {
  return {
    ok: false,
    serial: partial.serial ?? null,
    drive: partial.drive ?? null,
    recoveryKey: null,
    installerPath: null,
    error: message,
    code,
    details,
    steps: Array.isArray(partial.steps) ? partial.steps : [],
  }
}

/**
 * @param {object} fields
 */
function okResult(fields) {
  return {
    ok: true,
    serial: fields.serial ?? null,
    drive: fields.drive ?? null,
    recoveryKey: fields.recoveryKey ?? null,
    installerPath: fields.installerPath ?? null,
    error: null,
    code: fields.code || 'PROVISION_COMPLETED',
    vaultRegenerated: !!fields.vaultRegenerated,
    recoveryFile: fields.recoveryFile ?? null,
    steps: Array.isArray(fields.steps) ? fields.steps : [],
  }
}

function ensureWindowsOnly() {
  if (process.platform !== 'win32') {
    return failResult('Este flujo solo está soportado en Windows.', 'UNSUPPORTED_PLATFORM')
  }
  return null
}

function toDriveLetter(raw) {
  if (!raw) return null
  const clean = String(raw).trim().toUpperCase().replace(/\\+$/, '')
  const match = clean.match(/^([A-Z]):?$/)
  return match ? `${match[1]}:` : null
}

function toDriveIndex(raw) {
  if (raw == null || raw === '') return null
  const value = Number.parseInt(String(raw).trim(), 10)
  if (!Number.isFinite(value) || value < 1) return null
  return value
}

function formatDeviceList(devices, numbered = false) {
  return devices
    .map((d, idx) => {
      const prefix = numbered ? `  ${idx + 1})` : '  -'
      return `${prefix} ${d.driveLetter}  serial=${d.serial}`
    })
    .join('\n')
}

/**
 * @param {string|null|undefined} serialHintRaw
 * @param {string|null|undefined} driveHintRaw
 * @param {number|string|null|undefined} driveIndexRaw
 */
async function resolveTargetDevice(serialHintRaw, driveHintRaw, driveIndexRaw) {
  const allDevices = await pendriveCrypto.listAllUsbDrives()
  const devices = allDevices.filter((d) => d.driveLetter)
  if (!Array.isArray(devices) || devices.length === 0) {
    if (Array.isArray(allDevices) && allDevices.length > 0) {
      return {
        ok: false,
        error: [
          'Se detectó USB pero ninguna unidad tiene letra asignada.',
          'Asigna una letra en Administración de discos o Explorador y reintenta.',
          'Dispositivos sin letra:',
          ...allDevices.map((d) => `  - serial=${d.serial} source=${d.source || '?'}`),
        ].join('\n'),
        code: 'USB_NO_DRIVE_LETTER',
        devices: allDevices,
      }
    }
    return {
      ok: false,
      error: [
        'No se detectaron pendrives USB listos para provisión.',
        'Verifica lo siguiente y reintenta:',
        '  1) Conecta/reconecta el USB del cliente y espera 3-5 segundos.',
        '  2) Confirma en Explorador de Windows que el USB tenga letra asignada (ej: E:).',
        '  3) Ejecuta --list-json para revisar diagnóstico de detección.',
      ].join('\n'),
      code: 'NO_USB_DRIVES',
      devices: [],
    }
  }

  const serialHint = usbSerial.sanitize(serialHintRaw || '')
  const driveHint = toDriveLetter(driveHintRaw)
  const driveIndex = toDriveIndex(driveIndexRaw)
  if (driveIndexRaw != null && driveIndex == null) {
    return {
      ok: false,
      error: 'El valor de --drive-index debe ser un entero mayor o igual a 1.',
      code: 'INVALID_DRIVE_INDEX',
      devices,
    }
  }

  const filtered = devices.filter((d) => {
    if (serialHint && String(d.serial).toLowerCase() !== String(serialHint).toLowerCase()) {
      return false
    }
    if (driveHint && String(d.driveLetter).toUpperCase() !== driveHint) {
      return false
    }
    return true
  })

  if (filtered.length === 1) {
    return { ok: true, device: filtered[0], devices: filtered }
  }

  if (driveIndex != null) {
    const selected = filtered[driveIndex - 1]
    if (selected) return { ok: true, device: selected, devices: filtered }
    return {
      ok: false,
      error: [
        `--drive-index=${driveIndex} está fuera de rango.`,
        `Hay ${filtered.length} dispositivo(s) candidato(s).`,
        'Usa uno de estos índices:',
        formatDeviceList(filtered, true),
      ].join('\n'),
      code: 'DRIVE_INDEX_OUT_OF_RANGE',
      devices: filtered,
    }
  }

  if (filtered.length === 0) {
    return {
      ok: false,
      error: [
        'No se encontró el USB indicado con --serial/--drive.',
        `Entrada recibida: serial=${serialHint || '(vacío)'} drive=${driveHint || '(vacío)'}`,
        'Dispositivos detectados:',
        formatDeviceList(devices),
      ].join('\n'),
      code: 'USB_NOT_FOUND',
      devices,
    }
  }

  return {
    ok: false,
    error: [
      'Hay múltiples USB candidatos.',
      'Selecciona uno con --drive <letra> (recomendado) o --drive-index <n>.',
      'Ejemplo: --drive E:   o   --drive-index 2',
      'Dispositivos detectados:',
      formatDeviceList(filtered, true),
    ].join('\n'),
    code: 'MULTIPLE_USB_CANDIDATES',
    devices: filtered,
  }
}

async function checkRegistration(apiBase, serial) {
  if (typeof fetch !== 'function') {
    return { checked: false, registered: null, error: 'FETCH_NOT_AVAILABLE' }
  }
  const base = String(apiBase || DEFAULT_API_BASE).trim().replace(/\/+$/, '')
  const url = `${base}/v1/pendrive/verify`
  try {
    const resp = await fetch(url, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ serial }),
    })
    if (!resp.ok) {
      return {
        checked: true,
        registered: null,
        error: `HTTP_${resp.status}`,
      }
    }
    const data = await resp.json()
    return {
      checked: true,
      registered: !!data?.ok,
      error: data?.error || null,
    }
  } catch (err) {
    return {
      checked: true,
      registered: null,
      error: err && err.message ? err.message : 'NETWORK_ERROR',
    }
  }
}

function isCustomerInstallerExe(name) {
  const lower = String(name || '').toLowerCase()
  if (!lower.endsWith('.exe')) return false
  if (lower.includes('provisioner')) return false
  return lower.startsWith('dotia')
}

function findLatestInstallerInRelease(releaseDir = DEFAULT_RELEASE_DIR) {
  if (!fs.existsSync(releaseDir)) return null
  const files = fs
    .readdirSync(releaseDir)
    .filter((name) => isCustomerInstallerExe(name))
    .map((name) => {
      const full = path.join(releaseDir, name)
      const stat = fs.statSync(full)
      return { full, mtime: stat.mtimeMs }
    })
    .sort((a, b) => b.mtime - a.mtime)
  return files[0]?.full || null
}

/**
 * @param {string|null|undefined} installerArg
 * @param {string} [cwd]
 */
function resolveInstallerSourcePath(installerArg, cwd = process.cwd()) {
  if (installerArg) {
    const full = path.resolve(cwd, installerArg)
    if (!fs.existsSync(full)) {
      return {
        ok: false,
        error: `No existe el instalador indicado: ${full}`,
        code: 'INSTALLER_NOT_FOUND',
      }
    }
    if (!full.toLowerCase().endsWith('.exe')) {
      return {
        ok: false,
        error: `El instalador debe ser .exe: ${full}`,
        code: 'INSTALLER_INVALID',
      }
    }
    return { ok: true, path: full }
  }
  const latest = findLatestInstallerInRelease()
  return { ok: true, path: latest }
}

function writeRecoveryFile(recoveryOutPath, serial, driveLetter, recoveryKey, cwd = process.cwd()) {
  const outPath = path.resolve(cwd, recoveryOutPath)
  const dir = path.dirname(outPath)
  fs.mkdirSync(dir, { recursive: true })
  const content = [
    'DOT USB RECOVERY KEY',
    `fecha=${new Date().toISOString()}`,
    `serial=${serial}`,
    `drive=${driveLetter}`,
    `recovery_key=${recoveryKey}`,
    '',
    'Guardar este archivo en un gestor seguro interno.',
  ].join('\n')
  fs.writeFileSync(outPath, content, 'utf8')
  return outPath
}

/**
 * @returns {Promise<{ok: boolean, devices?: object[], count?: number, error?: string, code?: string}>}
 */
async function listUsbDevices() {
  const platformError = ensureWindowsOnly()
  if (platformError) return platformError

  try {
    const devices = await pendriveCrypto.listAllUsbDrives()
    return {
      ok: true,
      devices: Array.isArray(devices) ? devices : [],
      count: Array.isArray(devices) ? devices.length : 0,
      error: null,
      code: 'USB_LIST_OK',
    }
  } catch (err) {
    const message = err && err.message ? err.message : 'No se pudieron listar dispositivos USB.'
    return {
      ok: false,
      devices: [],
      count: 0,
      error: message,
      code: 'USB_LIST_FAILED',
    }
  }
}

/**
 * @typedef {object} ProvisionDeliveryOptions
 * @property {string|null} [serial]
 * @property {string|null} [drive]
 * @property {number|string|null} [driveIndex]
 * @property {string} [apiBase]
 * @property {boolean} [requireRegistered]
 * @property {boolean} [force]
 * @property {boolean} [copyInstaller]
 * @property {string|null} [installer]
 * @property {string|null} [recoveryOut]
 * @property {string} [releaseDir]
 * @property {string} [cwd]
 */

/**
 * @param {ProvisionDeliveryOptions} options
 */
async function provisionUsbDelivery(options = {}) {
  const platformError = ensureWindowsOnly()
  if (platformError) return platformError

  const steps = []
  const addStep = (key, status, message, extra) => {
    steps.push({
      key,
      status,
      message,
      ...(extra && typeof extra === 'object' ? extra : {}),
    })
  }

  const args = {
    serial: options.serial ?? null,
    drive: options.drive ?? null,
    driveIndex: options.driveIndex ?? null,
    apiBase: options.apiBase || DEFAULT_API_BASE,
    requireRegistered: !!options.requireRegistered,
    force: !!options.force,
    copyInstaller: options.copyInstaller !== false,
    installer: options.installer ?? null,
    recoveryOut: options.recoveryOut ?? null,
    releaseDir: options.releaseDir || DEFAULT_RELEASE_DIR,
    cwd: options.cwd || process.cwd(),
  }

  const resolved = await resolveTargetDevice(args.serial, args.drive, args.driveIndex)
  if (!resolved.ok) {
    return failResult(resolved.error, resolved.code, { devices: resolved.devices }, { steps })
  }

  const target = resolved.device
  const serial = usbSerial.sanitize(target.serial)
  if (!serial) {
    return failResult(
      usbSerialPolicy.SELLER_INVALID_SERIAL_MESSAGE,
      'INVALID_USB_SERIAL',
      {
        rawSerial: String(target.serial || '').trim() || null,
        model: target.model || null,
        source: target.source || null,
      },
      { steps },
    )
  }
  const drive = String(target.driveLetter).trim().toUpperCase()
  const drivePath = `${drive}\\`
  addStep('detectando', 'ok', `USB detectado (${drive}).`, { serial, driveLetter: drive })

  const reg = await checkRegistration(args.apiBase, serial)
  if (reg.checked && reg.registered === true) {
    addStep('validando', 'ok', `Registro backend verificado en ${args.apiBase}.`)
  } else if (reg.checked && reg.registered === false) {
    const msg = reg.error ? ` (${reg.error})` : ''
    addStep('validando', 'error', `Serial no registrado en backend${msg}.`, {
      backendError: reg.error || null,
    })
    if (args.requireRegistered) {
      return failResult(
        'El serial no está registrado en backend y se exigió verificación de registro.',
        'SERIAL_NOT_REGISTERED',
        { backendError: reg.error || null },
        { serial, drive, steps },
      )
    }
  } else {
    const msg = reg.error ? ` (${reg.error})` : ''
    addStep('validando', 'warn', `No se pudo verificar registro backend${msg}.`, {
      backendError: reg.error || null,
    })
    if (args.requireRegistered) {
      return failResult(
        'No se pudo verificar registro en backend y se exigió verificación de registro.',
        'BACKEND_REGISTRATION_CHECK_FAILED',
        { backendError: reg.error || null },
        { serial, drive, steps },
      )
    }
  }

  let recoveryKey = null
  let vaultRegenerated = false

  const existing = pendriveCrypto.verifyVault(drivePath, serial)
  if (existing.ok && !args.force) {
    addStep('copiando', 'ok', 'Vault existente válido, se conserva.')
  } else {
    const createResult = await pendriveCrypto.createVault(drivePath, serial)
    if (!createResult.ok) {
      return failResult(
        `No se pudo crear dot.vault: ${createResult.error || 'ERROR_DESCONOCIDO'}`,
        'VAULT_CREATE_FAILED',
        null,
        { serial, drive, steps },
      )
    }
    vaultRegenerated = true
    recoveryKey = createResult.recoveryKey || null
    addStep('copiando', 'ok', 'Vault creado correctamente en el USB.')
  }

  const verifyFull = await pendriveCrypto.verifyVaultFull(drivePath, serial)
  if (!verifyFull.ok) {
    return failResult(
      `La verificación final del vault falló: ${verifyFull.error || 'VERIFY_FAILED'}`,
      'VAULT_VERIFY_FAILED',
      null,
      { serial, drive, steps },
    )
  }
  addStep('validando', 'ok', 'Verificación anti-clonación completada.')

  let installerPath = null
  if (args.copyInstaller) {
    const installerResolved = resolveInstallerSourcePath(args.installer, args.cwd)
    if (!installerResolved.ok) {
      return failResult(installerResolved.error, installerResolved.code, null, {
        serial,
        drive,
        steps,
      })
    }
    if (installerResolved.path) {
      const targetPath = path.join(drivePath, path.basename(installerResolved.path))
      try {
        fs.copyFileSync(installerResolved.path, targetPath)
      } catch (err) {
        const message = err && err.message ? err.message : 'No se pudo copiar el instalador al USB.'
        return failResult(message, 'INSTALLER_COPY_FAILED', null, { serial, drive, steps })
      }
      installerPath = targetPath
      addStep('copiando', 'ok', `Instalador copiado (${path.basename(targetPath)}).`)
    } else {
      addStep(
        'copiando',
        'warn',
        'No se encontró instalador .exe en frontend/release; se omitió la copia.',
      )
    }
  } else {
    addStep('copiando', 'skipped', 'Copia de instalador omitida.')
  }

  // ── Autorun.inf (auto-arranque "malware-like") ──────────────
  // Windows 10/11 bloquea autorun.inf por seguridad, pero se escribe
  // por compatibilidad con versiones anteriores y como senial visual.
  // El mecanismo real de auto-inicio es via Run key (auto-launch.cjs).
  const installerBasename = installerPath ? path.basename(installerPath) : 'DOTIA.exe'
  writeAutorunInf(drivePath, installerBasename)
  addStep('copiando', 'ok', `autorun.inf escrito (icon=${installerBasename}).`)

  let recoveryFile = null
  if (args.recoveryOut) {
    if (!recoveryKey) {
      addStep(
        'completado',
        'warn',
        'No se generó recovery key nueva (vault existente). No se escribió archivo de recovery.',
      )
    } else {
      recoveryFile = writeRecoveryFile(args.recoveryOut, serial, drive, recoveryKey, args.cwd)
    }
  }

  addStep('completado', 'ok', 'Provisión completada correctamente.')

  return okResult({
    serial,
    drive,
    recoveryKey,
    installerPath,
    vaultRegenerated,
    recoveryFile,
    steps,
  })
}

/**
 * Formato extendido para integraciones legacy (CLI JSON, auto-venta1, panel).
 * @param {ReturnType<typeof okResult>|ReturnType<typeof failResult>} core
 */
function toLegacyCliPayload(core) {
  if (!core || typeof core !== 'object') {
    return {
      ok: false,
      code: 'PROVISION_UNEXPECTED_ERROR',
      message: 'Resultado de provisión inválido.',
      error: 'Resultado de provisión inválido.',
      serial: null,
      drive: null,
      recoveryKey: null,
      installerPath: null,
    }
  }

  const flat = {
    ok: !!core.ok,
    serial: core.serial ?? null,
    drive: core.drive ?? null,
    recoveryKey: core.recoveryKey ?? null,
    installerPath: core.installerPath ?? null,
    error: core.error ?? null,
  }

  if (!core.ok) {
    return {
      ...flat,
      code: core.code || 'PROVISION_FAILED',
      message: core.error || 'La provisión USB falló.',
      details: core.details ?? null,
      steps: core.steps || [],
    }
  }

  return {
    ...flat,
    code: core.code || 'PROVISION_COMPLETED',
    message: 'Listo. El USB quedó preparado para entrega de DOT.',
    steps: core.steps || [],
    result: {
      driveLetter: core.drive,
      serial: core.serial,
      vaultRegenerated: !!core.vaultRegenerated,
      installerCopied: !!core.installerPath,
      installerPath: core.installerPath,
      recoveryKey: core.recoveryKey,
      recoveryFile: core.recoveryFile ?? null,
    },
  }
}

function errorToResult(err) {
  const message =
    err && typeof err === 'object' && 'message' in err
      ? String(err.message || '').trim()
      : 'Error inesperado en provisión USB.'
  const code =
    err && typeof err === 'object' && 'code' in err && err.code
      ? String(err.code)
      : 'PROVISION_UNEXPECTED_ERROR'
  return failResult(message || 'Error inesperado en provisión USB.', code)
}

/**
 * Escribe autorun.inf en la raiz del USB para auto-arranque.
 * Windows 10/11 bloquea autorun.inf por seguridad, pero se escribe
 * para compatibilidad con versiones anteriores y como senial visual.
 * El mecanismo real de auto-inicio es via Run key (auto-launch.cjs).
 *
 * @param {string} drivePath - Ruta del pendrive (ej: "D:\\")
 * @param {string} iconExe   - Nombre del ejecutable para el icono (ej: "DOTIA.exe")
 */
function writeAutorunInf(drivePath, iconExe = 'DOTIA.exe') {
  const content = [
    '[Autorun]',
    'Action=Iniciar DOT IA',
    `icon=${iconExe}`,
    'label=DOT IA',
    '',
  ].join('\r\n')

  const targetPath = path.join(drivePath, 'autorun.inf')
  try {
    fs.writeFileSync(targetPath, content, 'utf8')
    // Marcar como oculto en Windows (opcional, no critico)
    if (process.platform === 'win32') {
      try {
        require('child_process').execFileSync('attrib', ['+H', targetPath], {
          timeout: 5000,
          windowsHide: true,
        })
      } catch {
        // No critico si falla
      }
    }
  } catch {
    // No critico si falla la escritura
  }
}

module.exports = {
  DEFAULT_API_BASE,
  FRONTEND_ROOT,
  DEFAULT_RELEASE_DIR,
  toDriveLetter,
  toDriveIndex,
  resolveTargetDevice,
  checkRegistration,
  findLatestInstallerInRelease,
  resolveInstallerSourcePath,
  writeRecoveryFile,
  writeAutorunInf,
  listUsbDevices,
  provisionUsbDelivery,
  toLegacyCliPayload,
  errorToResult,
  okResult,
  failResult,
}
