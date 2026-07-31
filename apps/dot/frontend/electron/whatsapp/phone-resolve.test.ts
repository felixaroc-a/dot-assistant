import { createRequire } from 'node:module'
import { mkdtempSync, mkdirSync, writeFileSync, rmSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { afterEach, describe, expect, it } from 'vitest'

const require = createRequire(import.meta.url)
const {
  normalizePhoneE164,
  phoneFromJid,
  resolveOwnWhatsAppPhone,
} = require('./phone-resolve.cjs')
const { extractPhoneNumber, detectLinkedEvent } = require('./link-signals.cjs')

describe('whatsapp phone-resolve', () => {
  const temps: string[] = []

  afterEach(() => {
    for (const dir of temps.splice(0)) {
      rmSync(dir, { recursive: true, force: true })
    }
  })

  it('normaliza locales VE a E.164', () => {
    expect(normalizePhoneE164('04141234567')).toBe('+584141234567')
    expect(normalizePhoneE164('4141234567')).toBe('+584141234567')
    expect(normalizePhoneE164('584141234567')).toBe('+584141234567')
  })

  it('extrae teléfono desde JID Baileys', () => {
    expect(phoneFromJid('580000000111:69@s.whatsapp.net')).toBe('+580000000111')
  })

  it('resuelve número propio desde creds.json fake', () => {
    const home = mkdtempSync(join(tmpdir(), 'dot-wa-phone-'))
    temps.push(home)
    const credsDir = join(home, 'credentials', 'whatsapp', 'default')
    mkdirSync(credsDir, { recursive: true })
    writeFileSync(
      join(credsDir, 'creds.json'),
      JSON.stringify({ me: { id: '580000000222:1@s.whatsapp.net', name: 'Test' } }),
      'utf8',
    )
    expect(resolveOwnWhatsAppPhone({ openclawHome: home })).toBe('+580000000222')
  })

  it('detectLinkedEvent incluye phone cuando el log trae JID', () => {
    const text = 'WhatsApp connected — session active\n{"id":"580000000333:2@s.whatsapp.net"}'
    expect(detectLinkedEvent(text)).toEqual({
      linked: true,
      phone_number: '+580000000333',
    })
    expect(extractPhoneNumber('"phone_number":"+580000000444"')).toBe('+580000000444')
  })
})
