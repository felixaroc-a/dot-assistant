'use strict'

const { BaileysTransport } = require('./baileys-transport.cjs')
const { MockTransport } = require('./mock-transport.cjs')

/** @type {import('./whatsapp-transport.cjs').WhatsappTransport | null} */
let _singletonInstance = null

/**
 * Modo de transporte WhatsApp activo (default: baileys).
 * @returns {'baileys' | 'mock' | string}
 */
function getTransportMode() {
  return (process.env.WHATSAPP_TRANSPORT || 'baileys').trim().toLowerCase()
}

/**
 * Fábrica que devuelve la implementación de WhatsappTransport según
 * la variable de entorno WHATSAPP_TRANSPORT.
 *
 * Valores (DOT FASE 1.1 / BIBLIA §20):
 *   - 'baileys' (default) → BaileysTransport — único transport WhatsApp
 *   - 'mock'              → MockTransport (tests/desarrollo)
 *
 * @returns {import('./whatsapp-transport.cjs').WhatsappTransport}
 */
function getTransport() {
  if (_singletonInstance) {
    return _singletonInstance
  }

  const mode = getTransportMode()

  switch (mode) {
    case 'mock':
      _singletonInstance = new MockTransport()
      break
    case 'baileys':
    default:
      _singletonInstance = new BaileysTransport()
      break
  }

  return _singletonInstance
}

/**
 * Reinicia el singleton (útil en tests).
 */
function resetTransport() {
  if (_singletonInstance) {
    try {
      _singletonInstance.shutdown()
    } catch {
      // ignore
    }
  }
  _singletonInstance = null
}

module.exports = { getTransport, getTransportMode, resetTransport }
