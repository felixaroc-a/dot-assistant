import { describe, expect, it } from 'vitest'

import { WHATSAPP_LINK_UI, resolveWhatsAppQrUiPhase } from './whatsappLinkUi'

describe('whatsappLinkUi', () => {
  it('no expone términos internos en textos visibles', () => {
    for (const text of Object.values(WHATSAPP_LINK_UI)) {
      expect(text.toLowerCase()).not.toMatch(/openclaw/)
      expect(text.toLowerCase()).not.toMatch(/\bnpm\b/)
      expect(text.toLowerCase()).not.toMatch(/\bgateway\b/)
      expect(text.toLowerCase()).not.toMatch(/baileys/)
    }
  })

  it('resuelve fases del flujo QR', () => {
    expect(
      resolveWhatsAppQrUiPhase({
        isDesktop: true,
        linkedOk: false,
        hasQrImage: false,
        runState: 'running',
        qrTimeout: false,
        startError: null,
        showEndedError: false,
      }),
    ).toBe('generating')

    expect(
      resolveWhatsAppQrUiPhase({
        isDesktop: true,
        linkedOk: false,
        hasQrImage: true,
        runState: 'running',
        qrTimeout: false,
        startError: null,
        showEndedError: false,
      }),
    ).toBe('scan')

    expect(
      resolveWhatsAppQrUiPhase({
        isDesktop: true,
        linkedOk: true,
        hasQrImage: true,
        runState: 'running',
        qrTimeout: false,
        startError: null,
        showEndedError: false,
      }),
    ).toBe('connected')
  })
})
