'use strict'

/**
 * Filtro estricto Fase A: solo auto-reply en grupo "DOT" con mención "DOT".
 * Sin hardcode de número: usa teléfono vinculado resuelto en runtime.
 */

/**
 * @param {string} name
 * @param {string} [expected]
 * @returns {boolean}
 */
function isDotGroupName(name, expected = 'DOT') {
  // Producto: el grupo debe llamarse exactamente "DOT" (case-insensitive).
  const needle = String(expected || 'DOT').trim().toLowerCase()
  if (!needle) return false
  const hay = String(name || '').trim().toLowerCase()
  return Boolean(hay) && hay === needle
}

/**
 * @param {string} value
 * @returns {string}
 */
function escapeRegex(value) {
  return String(value).replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
}

/**
 * @param {string} text
 * @param {string} [token]
 * @returns {boolean}
 */
function textMentionsDot(text, token = 'DOT') {
  const needle = String(token || 'DOT').trim()
  if (!needle) return false
  const body = String(text || '')
  if (!body) return false
  // "DOT", "@DOT", "hola DOT", "DOT:" — case-insensitive, word-ish boundary
  const re = new RegExp(`(?:^|[^a-z0-9_])@?${escapeRegex(needle)}(?:[^a-z0-9_]|$)`, 'i')
  return re.test(body)
}

/**
 * @param {{
 *   is_group?: boolean
 *   group_name?: string | null
 *   group_subject?: string | null
 *   text?: string
 *   from_phone?: string
 *   linked_phone?: string | null
 *   require_self?: boolean
 *   group_filter?: string
 *   mention_token?: string
 * }} input
 * @returns {{ allow: boolean; reason: string }}
 */
function shouldAllowDotGroupReply(input = {}) {
  const groupFilter = String(input.group_filter || process.env.WHATSAPP_REPLY_GROUP_NAME || 'DOT').trim() || 'DOT'
  const mentionToken = String(input.mention_token || process.env.WHATSAPP_REPLY_MENTION_TOKEN || 'DOT').trim() || 'DOT'
  const requireSelf = input.require_self !== false

  if (!input.is_group) {
    return { allow: false, reason: 'not_group' }
  }

  const groupName = input.group_name || input.group_subject || ''
  if (!isDotGroupName(groupName, groupFilter)) {
    return { allow: false, reason: 'group_name_mismatch' }
  }

  if (!textMentionsDot(input.text || '', mentionToken)) {
    return { allow: false, reason: 'mention_missing' }
  }

  if (requireSelf) {
    const from = String(input.from_phone || '').replace(/\D/g, '')
    const linked = String(input.linked_phone || '').replace(/\D/g, '')
    const fromTail = from.slice(-10)
    const linkedTail = linked.slice(-10)
    if (!fromTail || !linkedTail || fromTail !== linkedTail) {
      return { allow: false, reason: 'sender_not_owner' }
    }
  }

  return { allow: true, reason: 'dot_group_mention_ok' }
}

module.exports = {
  isDotGroupName,
  textMentionsDot,
  shouldAllowDotGroupReply,
}
