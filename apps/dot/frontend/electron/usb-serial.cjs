/**
 * Lee el serial de hardware de pendrives USB en la PC local (sin letra de unidad).
 * Usado por DOT IA como llave física de acceso.
 */
const { execFile } = require('node:child_process')
const fs = require('node:fs')
const { promisify } = require('node:util')
const pendriveCrypto = require('./pendrive-crypto.cjs')
const usbSerialPolicy = require('./usb-serial-policy.cjs')

const execFileAsync = promisify(execFile)

function sanitize(raw) {
  return usbSerialPolicy.sanitizeUsbSerial(raw)
}

/**
 * Lista los seriales de todos los USB conectados en Windows.
 * @returns {Promise<string[]>}
 */
async function listWindows() {
  try {
    const devices = await pendriveCrypto.listAllUsbDrives()
    const serials = devices
      .map((d) => sanitize(d?.serial))
      .filter(Boolean)
    return [...new Set(serials)]
  } catch (err) {
    console.warn('[DOT USB-Serial] Error al listar dispositivos USB en Windows:', err.message)
    return []
  }
}

async function listLinux() {
  const byId = '/dev/disk/by-id'
  const out = []
  try {
    const names = fs.readdirSync(byId)
    for (const name of names) {
      if (!name.startsWith('usb-') || name.includes('-part')) continue
      const parts = name.slice(4).split('_')
      const serialRaw = parts.length >= 2 ? parts[parts.length - 1] : name.slice(4)
      const serial = sanitize(serialRaw)
      if (serial) out.push(serial)
    }
    if (out.length) return [...new Set(out)]
  } catch {
    /* fallback lsblk */
  }
  try {
    const { stdout } = await execFileAsync(
      'lsblk',
      ['-d', '-n', '-o', 'SERIAL,TRAN'],
      { timeout: 10000 },
    )
    for (const line of stdout.split(/\r?\n/)) {
      const parts = line.trim().split(/\s+/)
      if (parts.length < 2 || parts[1].toLowerCase() !== 'usb') continue
      const serial = sanitize(parts[0])
      if (serial) out.push(serial)
    }
  } catch {
    return []
  }
  return [...new Set(out)]
}

async function listDarwin() {
  try {
    const { stdout: listOut } = await execFileAsync('diskutil', ['list', 'external'], {
      timeout: 15000,
    })
    const disks = []
    for (const line of listOut.split(/\r?\n/)) {
      const m = line.match(/\/dev\/(disk\d+)/)
      if (m) disks.push(m[1])
    }
    const serials = []
    for (const disk of disks) {
      const { stdout: info } = await execFileAsync('diskutil', ['info', disk], {
        timeout: 10000,
      })
      const usb = info.match(/USB Serial Number:\s*(.+)/i)
      const media = info.match(/Device \/ Media Serial Number:\s*(.+)/i)
      const serial = sanitize(usb?.[1] || media?.[1])
      if (serial) serials.push(serial)
    }
    return [...new Set(serials)]
  } catch {
    return []
  }
}

/**
 * Obtiene el serial del USB conectado.
 *
 * Si hay exactamente un USB, lo retorna automáticamente.
 * Si hay múltiples USB, intenta detectar cuál tiene un dot.vault
 * válido y lo usa. Si ninguno tiene vault, retorna el primero con una
 * advertencia. Ya no rechaza el login por múltiples USB.
 *
 * @param {string} [hint] - Serial opcional para seleccionar un USB específico
 * @returns {Promise<{ serial: string | null, devices: string[], error?: string, warning?: string }>}
 */
async function getUsbStorageSerial(hint) {
  let devices = []
  if (process.platform === 'win32') devices = await listWindows()
  else if (process.platform === 'linux') devices = await listLinux()
  else if (process.platform === 'darwin') devices = await listDarwin()
  else {
    return { serial: null, devices: [], error: 'Plataforma no soportada' }
  }

  const cleanHint = hint ? sanitize(hint) : null
  if (cleanHint) {
    if (devices.includes(cleanHint)) return { serial: cleanHint, devices }
    return { serial: null, devices, error: 'Pendrive indicado no detectado' }
  }
  if (devices.length === 1) return { serial: devices[0], devices }
  if (devices.length === 0) {
    return { serial: null, devices: [], error: 'No hay pendrive USB conectado' }
  }

  // Múltiples USB: buscar el que tenga dot.vault válido
  try {
    const validVault = await pendriveCrypto.findValidVault()
    if (validVault.ok && validVault.serial && devices.includes(validVault.serial)) {
      return {
        serial: validVault.serial,
        devices,
        warning: `Se usó el pendrive con vault válido (${validVault.serial}). Había ${devices.length} USB conectados.`,
      }
    }
  } catch {
    // Si falla la verificación del vault, continuar con el primer USB
  }

  // Ninguno tiene vault válido: devolver el primero con advertencia
  return {
    serial: devices[0],
    devices,
    warning: `Hay ${devices.length} USB conectados y ninguno tiene vault válido. Se usó el primero (${devices[0]}). Conecta solo el pendrive DOT o provisiona uno.`,
  }
}

/**
 * Lista todos los seriales USB disponibles en el sistema.
 * No intenta seleccionar uno; solo enumera los detectados.
 * @returns {Promise<string[]>}
 */
async function listUsbSerials() {
  let devices = []
  if (process.platform === 'win32') devices = await listWindows()
  else if (process.platform === 'linux') devices = await listLinux()
  else if (process.platform === 'darwin') devices = await listDarwin()
  return devices
}

module.exports = { getUsbStorageSerial, listUsbSerials, sanitize }
