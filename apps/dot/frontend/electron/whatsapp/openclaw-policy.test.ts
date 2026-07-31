import { createRequire } from 'node:module'
import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'
import { afterEach, describe, expect, it } from 'vitest'

const require = createRequire(import.meta.url)
const {
  hardenOpenClawWhatsAppPolicy,
  findDotGroupJid,
  isExactDotGroupSubject,
  DOT_MENTION_PATTERNS,
} = require('./openclaw-policy.cjs')

const temps: string[] = []

function makeHome(opts?: { withDotGroup?: boolean; subject?: string }) {
  const home = fs.mkdtempSync(path.join(os.tmpdir(), 'dot-oc-policy-'))
  temps.push(home)
  fs.mkdirSync(path.join(home, 'credentials', 'whatsapp', 'default'), { recursive: true })
  fs.writeFileSync(
    path.join(home, 'credentials', 'whatsapp', 'default', 'creds.json'),
    JSON.stringify({ me: { id: '584144001856:69@s.whatsapp.net' } }),
    'utf8',
  )
  fs.writeFileSync(
    path.join(home, 'openclaw.json'),
    JSON.stringify(
      {
        channels: {
          whatsapp: {
            enabled: true,
            dmPolicy: 'open',
            allowFrom: ['*'],
            groupPolicy: 'open',
          },
        },
        agents: { list: [{ id: 'main' }] },
      },
      null,
      2,
    ),
    'utf8',
  )

  if (opts?.withDotGroup) {
    const sessionsDir = path.join(home, 'agents', 'main', 'sessions')
    fs.mkdirSync(sessionsDir, { recursive: true })
    const jid = '120363999999999999@g.us'
    const subject = opts.subject ?? 'DOT'
    fs.writeFileSync(
      path.join(sessionsDir, 'sessions.json'),
      JSON.stringify({
        [`agent:main:whatsapp:group:${jid}`]: { subject, displayName: 'whatsapp:g-dot' },
        'agent:main:whatsapp:group:120363000000000000@g.us': {
          subject: 'Novios chat',
          displayName: 'whatsapp:g-novios',
        },
      }),
      'utf8',
    )
    return { home, jid }
  }

  return { home, jid: undefined }
}

afterEach(() => {
  for (const dir of temps.splice(0)) {
    try {
      fs.rmSync(dir, { recursive: true, force: true })
    } catch {
      // ignore
    }
  }
})

describe('openclaw-policy', () => {
  it('match exacto de subject DOT', () => {
    expect(isExactDotGroupSubject('DOT')).toBe(true)
    expect(isExactDotGroupSubject('dot')).toBe(true)
    expect(isExactDotGroupSubject('DOT Novios')).toBe(false)
  })

  it('mentionPatterns matchean "DOT HOLA"', () => {
    const re = new RegExp(DOT_MENTION_PATTERNS[0], 'i')
    expect(re.test('DOT HOLA')).toBe(true)
  })

  it('modo discovery si no hay grupo DOT (no disabled)', () => {
    const { home } = makeHome()
    const result = hardenOpenClawWhatsAppPolicy({ openclawHome: home })
    expect(result.ok).toBe(true)
    expect(result.mode).toBe('discovery')
    expect(result.dotGroupJid).toBeUndefined()

    const cfg = JSON.parse(fs.readFileSync(path.join(home, 'openclaw.json'), 'utf8'))
    expect(cfg.channels.whatsapp.dmPolicy).toBe('disabled')
    expect(cfg.channels.whatsapp.groupPolicy).toBe('allowlist')
    expect(cfg.channels.whatsapp.groupPolicy).not.toBe('disabled')
    expect(cfg.channels.whatsapp.groups['*'].requireMention).toBe(true)
    expect(cfg.agents.list[0].groupChat.mentionPatterns).toEqual(DOT_MENTION_PATTERNS)
  })

  it('modo locked si subject exacto DOT existe', () => {
    const { home, jid } = makeHome({ withDotGroup: true, subject: 'DOT' })
    expect(findDotGroupJid(home)).toBe(jid)

    const result = hardenOpenClawWhatsAppPolicy({ openclawHome: home })
    expect(result.ok).toBe(true)
    expect(result.mode).toBe('locked')
    expect(result.dotGroupJid).toBe(jid)

    const cfg = JSON.parse(fs.readFileSync(path.join(home, 'openclaw.json'), 'utf8'))
    expect(cfg.channels.whatsapp.groups[jid].requireMention).toBe(true)
    expect(cfg.channels.whatsapp.groups['*']).toBeUndefined()
  })

  it('no lockea grupo con otro nombre aunque digan DOT', () => {
    const { home } = makeHome({ withDotGroup: true, subject: 'Novios' })
    expect(findDotGroupJid(home)).toBeUndefined()
    const result = hardenOpenClawWhatsAppPolicy({ openclawHome: home })
    expect(result.mode).toBe('discovery')
  })
})
