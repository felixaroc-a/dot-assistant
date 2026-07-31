'use strict'

/**
 * Política única de seriales USB (Windows provisión + gate).
 * Mantener alineado con packages/nordik-billing/nordik_billing/hardware_token.py
 */

const INVALID_SERIALS = new Set([
  '',
  'none',
  'null',
  '00000000',
  '000000000000',
  '0000000001',
  '0000000005',
  'ffffffff',
  'n/a',
  'not available',
  'default string',
  '12345678',
  '0123456789',
])

const SERIAL_MIN_LEN = 4
const SERIAL_MAX_LEN = 128
const SERIAL_PATTERN = /^[A-Za-z0-9_.\-&]+$/

/** Mensaje para vendedor cuando WMI/PNP solo devuelve serial genérico. */
const SELLER_INVALID_SERIAL_MESSAGE =
  'Este pendrive no tiene un número de serie único válido (reporta un serial genérico de fábrica). ' +
  'Usa otro modelo de USB o contacta a soporte técnico; no se puede entregar DOT en este dispositivo.'

/**
 * @param {unknown} raw
 * @returns {string | null}
 */
function sanitizeUsbSerial(raw) {
  if (raw == null) return null
  let cleaned = String(raw)
    .trim()
    .replace(/\x00/g, '')
    .replace(/[^\x20-\x7E]/g, '')
  // Eliminar sufijo de instancia del SO (&0, &1, etc.) para obtener serial base estable
  cleaned = cleaned.replace(/&[0-9]+$/, '')
  if (!cleaned || INVALID_SERIALS.has(cleaned.toLowerCase())) return null
  if (cleaned.length < SERIAL_MIN_LEN || cleaned.length > SERIAL_MAX_LEN) return null
  if (!SERIAL_PATTERN.test(cleaned)) return null
  if (/^0+$/.test(cleaned)) return null
  return cleaned
}

/**
 * @param {unknown} pnpDeviceId
 * @returns {string | null}
 */
function serialFromPnpDeviceId(pnpDeviceId) {
  if (!pnpDeviceId) return null
  const parts = String(pnpDeviceId).split('\\')
  if (parts.length < 3) return null
  let tail = parts[parts.length - 1].trim()
  // Eliminar sufijo de instancia del SO (&0, &1, etc.) para obtener serial base estable
  tail = tail.replace(/&[0-9]+$/, '')
  return sanitizeUsbSerial(tail)
}

module.exports = {
  INVALID_SERIALS,
  SERIAL_MIN_LEN,
  SERIAL_MAX_LEN,
  SELLER_INVALID_SERIAL_MESSAGE,
  sanitizeUsbSerial,
  serialFromPnpDeviceId,
}
