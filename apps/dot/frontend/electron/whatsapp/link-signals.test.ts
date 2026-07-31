import { createRequire } from 'node:module'
import { describe, expect, it } from 'vitest'

const require = createRequire(import.meta.url)
const { detectLinkedEvent, hasDisconnectedSignal } = require('./link-signals.cjs')

describe('whatsapp link-signals (electron)', () => {
  it('no marca linked ante texto genérico de arranque', () => {
    expect(detectLinkedEvent('[DOT] Iniciando vinculación (openclaw channels login)…')).toBeNull()
    expect(detectLinkedEvent('plugin registered successfully in catalog')).toBeNull()
    expect(detectLinkedEvent('ready to receive qr events')).toBeNull()
  })

  it('detecta señales fuertes de sesión activa', () => {
    expect(detectLinkedEvent('WhatsApp connected — session active')).toEqual({
      linked: true,
      phone_number: undefined,
    })
    expect(detectLinkedEvent('[DOT] WhatsApp vinculado exitosamente.')).toEqual({
      linked: true,
      phone_number: undefined,
    })
    expect(detectLinkedEvent('channel whatsapp is now connected')).toEqual({
      linked: true,
      phone_number: undefined,
    })
  })

  it('detecta desconexión en logs del daemon', () => {
    expect(hasDisconnectedSignal('WhatsApp session expired, reconnect required')).toBe(true)
    expect(hasDisconnectedSignal('gateway closed (1006 abnormal closure)')).toBe(true)
    expect(hasDisconnectedSignal('channel whatsapp is now connected')).toBe(false)
  })
})
