import { afterEach, describe, expect, it } from 'vitest'
import { createRequire } from 'node:module'

const require = createRequire(import.meta.url)
const { getTransport, resetTransport } = require('./index.cjs')

describe('WhatsappTransport factory (T12)', () => {
  afterEach(() => {
    resetTransport()
    delete process.env.WHATSAPP_TRANSPORT
  })

  it('usa Baileys por defecto', () => {
    resetTransport()
    delete process.env.WHATSAPP_TRANSPORT
    const t = getTransport()
    expect(t.constructor.name).toBe('BaileysTransport')
    expect(t.getStatus().transport).toBe('baileys')
  })

  it('permite fallback OpenClaw vía env', () => {
    resetTransport()
    process.env.WHATSAPP_TRANSPORT = 'openclaw'
    const t = getTransport()
    expect(t.constructor.name).toBe('OpenClawTransport')
  })

  it('permite mock', () => {
    resetTransport()
    process.env.WHATSAPP_TRANSPORT = 'mock'
    const t = getTransport()
    expect(t.constructor.name).toBe('MockTransport')
  })
})
