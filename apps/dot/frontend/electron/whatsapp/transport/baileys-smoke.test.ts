/**
 * F3: smoke Baileys path — factory default + mock send/receive (sin QR humano).
 */
import { afterEach, describe, expect, it } from 'vitest'
import { createRequire } from 'node:module'

const require = createRequire(import.meta.url)
const { getTransport, resetTransport } = require('./index.cjs')

describe('WhatsApp Baileys / Mock transport smoke (F3)', () => {
  afterEach(() => {
    resetTransport()
    delete process.env.WHATSAPP_TRANSPORT
  })

  it('happy path mensajería no usa OpenClaw (default baileys)', () => {
    resetTransport()
    delete process.env.WHATSAPP_TRANSPORT
    const t = getTransport()
    expect(t.constructor.name).toBe('BaileysTransport')
  })

  it('mock sendMessage + inbound callback (bridge propio)', async () => {
    resetTransport()
    process.env.WHATSAPP_TRANSPORT = 'mock'
    const t = getTransport()
    await t.initialize()
    await t.startDaemon('test')

    const inbound: Array<Record<string, unknown>> = []
    t.onInboundMessage((msg: Record<string, unknown>) => inbound.push(msg))

    const sent = await t.sendMessage('+580000000000', 'hola DOT')
    expect(sent.ok).toBe(true)

    t.simulateInbound({ from: '+580000000001', text: 'cita confirmada mañana 10am', id: 'm1' })
    expect(inbound.length).toBeGreaterThanOrEqual(1)
  })
})
