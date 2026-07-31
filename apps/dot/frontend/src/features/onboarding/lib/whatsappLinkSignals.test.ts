import { describe, expect, it } from 'vitest'

import { hasLinkedSignal, sanitizeWhatsAppUserError } from './whatsappLinkSignals'

describe('hasLinkedSignal', () => {
  it('no marca linked ante texto genérico de arranque', () => {
    expect(hasLinkedSignal('[DOT] Iniciando vinculación (openclaw channels login)…')).toBe(false)
    expect(hasLinkedSignal('plugin registered successfully in catalog')).toBe(false)
    expect(hasLinkedSignal('connection established to local browser')).toBe(false)
    expect(hasLinkedSignal('ready to receive qr events')).toBe(false)
  })

  it('detecta señales fuertes de sesión activa', () => {
    expect(hasLinkedSignal('WhatsApp connected — session active')).toBe(true)
    expect(hasLinkedSignal('WhatsApp pairing success for device')).toBe(true)
    expect(hasLinkedSignal('WhatsApp device linked and ready to receive messages')).toBe(true)
    expect(hasLinkedSignal('[DOT] WhatsApp vinculado exitosamente.')).toBe(true)
    expect(hasLinkedSignal('channel whatsapp is now connected')).toBe(true)
  })

  it('detecta mensajes de éxito de OpenClaw 2026.6.11', () => {
    expect(hasLinkedSignal('WhatsApp Web connected.')).toBe(true)
    expect(hasLinkedSignal('✅ Linked! Credentials saved for future sends.')).toBe(true)
    expect(hasLinkedSignal('Local login saved auth for whatsapp/default')).toBe(true)
  })
})

describe('sanitizeWhatsAppUserError', () => {
  it('oculta referencias a OpenClaw', () => {
    expect(sanitizeWhatsAppUserError('Ya hay un proceso de Open Claw en curso.')).toBe(
      'Ya hay una vinculación en curso. Espera unos segundos o reinicia la app.',
    )
  })
})
