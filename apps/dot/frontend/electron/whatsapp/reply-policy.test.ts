import { createRequire } from 'node:module'
import { describe, expect, it } from 'vitest'

const require = createRequire(import.meta.url)
const { shouldAllowDotGroupReply, textMentionsDot, isDotGroupName } = require('./reply-policy.cjs')

describe('whatsapp reply-policy (electron)', () => {
  it('reconoce grupo DOT exacto y mención', () => {
    expect(isDotGroupName('DOT')).toBe(true)
    expect(isDotGroupName('dot')).toBe(true)
    expect(isDotGroupName(' mi grupo DOT ')).toBe(false)
    expect(isDotGroupName('playa')).toBe(false)
    expect(textMentionsDot('Hola DOT')).toBe(true)
    expect(textMentionsDot('DOT HOLA')).toBe(true)
    expect(textMentionsDot('@DOT ayuda')).toBe(true)
    expect(textMentionsDot('hola')).toBe(false)
  })

  it('bloquea chats 1:1 y grupos ajenos', () => {
    expect(
      shouldAllowDotGroupReply({
        is_group: false,
        text: 'DOT hola',
        from_phone: '+580000000001',
        linked_phone: '+580000000001',
      }).allow,
    ).toBe(false)

    expect(
      shouldAllowDotGroupReply({
        is_group: true,
        group_name: 'Counter Strike',
        text: 'DOT hola',
        from_phone: '+580000000001',
        linked_phone: '+580000000001',
      }).reason,
    ).toBe('group_name_mismatch')
  })

  it('permite solo dueño en grupo DOT con mención', () => {
    const ok = shouldAllowDotGroupReply({
      is_group: true,
      group_name: 'DOT',
      text: 'DOT resume',
      from_phone: '+580000000001',
      linked_phone: '+580000000001',
    })
    expect(ok).toEqual({ allow: true, reason: 'dot_group_mention_ok' })

    const stranger = shouldAllowDotGroupReply({
      is_group: true,
      group_name: 'DOT',
      text: 'DOT resume',
      from_phone: '+580000000099',
      linked_phone: '+580000000001',
    })
    expect(stranger.allow).toBe(false)
    expect(stranger.reason).toBe('sender_not_owner')
  })
})
