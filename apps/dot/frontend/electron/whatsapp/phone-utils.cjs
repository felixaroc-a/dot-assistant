'use strict'

/**
 * Normaliza un número telefónico al formato E.164 (+CCXXXXXXXX).
 *
 * @param {string|number} phone - número crudo (con o sin +, con o sin guiones)
 * @param {{ defaultRegion?: string }} [opts] - región por defecto (default: 'VE')
 * @returns {string | undefined} número E.164 o undefined si no se puede normalizar
 */
function normalizePhoneE164(phone, opts = {}) {
  const defaultRegion = (opts.defaultRegion || 'VE').toUpperCase()
  const raw = String(phone || '').trim()
  if (!raw) return undefined

  const digits = raw.replace(/\D/g, '')
  if (!digits) return undefined

  if (raw.startsWith('+') && digits.length >= 8 && digits.length <= 15) {
    return `+${digits}`
  }
  if (digits.startsWith('00') && digits.length > 2) {
    return `+${digits.slice(2)}`
  }

  if (defaultRegion === 'VE') {
    if (digits.startsWith('0') && digits.length === 11) {
      return `+58${digits.slice(1)}`
    }
    if (digits.startsWith('58') && digits.length >= 11 && digits.length <= 15) {
      return `+${digits}`
    }
    if (digits.length === 10 && digits.startsWith('4')) {
      return `+58${digits}`
    }
  }

  if (digits.length >= 8 && digits.length <= 15) {
    return `+${digits}`
  }
  return undefined
}

module.exports = { normalizePhoneE164 }
