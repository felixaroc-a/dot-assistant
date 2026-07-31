import { createRequire } from 'node:module'
import { describe, expect, it } from 'vitest'

const require = createRequire(import.meta.url)
const { parseInboundFromLogLine, buildDedupeKey } = require('./message-signals.cjs')

describe('whatsapp message-signals (electron)', () => {
  it('parsea payload web-inbound con body real', () => {
    const line = JSON.stringify({
      '0': '{"module":"web-inbound"}',
      '1': {
        from: '+584244142959',
        to: '+584144001856',
        body: 'Hola DOT',
        timestamp: 1783959004000,
      },
      '2': 'inbound message',
    })

    expect(parseInboundFromLogLine(line)).toEqual({
      from_phone: '+584244142959',
      to_phone: '+584144001856',
      text: 'Hola DOT',
      timestamp: new Date(1783959004000).toISOString(),
      is_group: false,
      group_name: undefined,
      message_id: undefined,
    })
  })

  it('parsea resumen inbound cuando no hay body', () => {
    const line = JSON.stringify({
      time: '2026-07-13T12:09:44.200-04:00',
      message:
        '{"subsystem":"gateway/channels/whatsapp/inbound"} Inbound message +584244142959 -> +584144001856 (direct, 80 chars)',
    })

    const parsed = parseInboundFromLogLine(line)
    expect(parsed?.from_phone).toBe('+584244142959')
    expect(parsed?.to_phone).toBe('+584144001856')
    expect(parsed?.text).toContain('80 caracteres')
  })


  it('marca is_group cuando from es JID de grupo @g.us', () => {
    const line = JSON.stringify({
      '0': '{"module":"web-inbound"}',
      '1': {
        from: '120363411787591349@g.us',
        to: '+584144001856',
        body: 'DOT HOLA',
        timestamp: 1783994479000,
      },
      '2': 'inbound message',
    })
    const parsed = parseInboundFromLogLine(line)
    expect(parsed?.is_group).toBe(true)
    expect(parsed?.text).toBe('DOT HOLA')
  })

  it('genera clave de deduplicación estable', () => {
    const key = buildDedupeKey({
      message_id: 'abc',
      from_phone: '+1',
      to_phone: '+2',
      timestamp: 't',
      text: 'hola',
    })
    expect(key).toBe('abc|+1|+2|t|hola')
  })
})
