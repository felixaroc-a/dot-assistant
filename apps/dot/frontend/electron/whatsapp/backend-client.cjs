'use strict'

/**
 * Cliente HTTP del bridge Electron hacia el backend DOT.
 */

/**
 * @returns {Promise<string>}
 */
async function loadAccessToken(loadSession) {
  const sessionStr = await loadSession()
  if (!sessionStr) return ''
  try {
    const session = JSON.parse(sessionStr)
    return (
      session?.accessToken ||
      session?.access_token ||
      session?.token ||
      ''
    )
  } catch {
    return sessionStr
  }
}

/**
 * @param {{
 *   loadSession: () => Promise<string | null>
 *   onRendererNotify?: (event: string, payload: Record<string, unknown>) => void
 * }} deps
 */
function createBackendInboundClient(deps) {
  const apiBase = (process.env.DOT_API_BASE_URL || 'http://127.0.0.1:8000')
    .trim()
    .replace(/\/+$/, '')
  const webhookSecret = String(process.env.WHATSAPP_WEBHOOK_SECRET || '').trim()

  /**
   * @param {Record<string, unknown>} payload
   */
  async function postInbound(payload) {
    const headers = {
      'Content-Type': 'application/json',
      'X-Channel-Source': 'electron-bridge',
    }
    if (webhookSecret) {
      headers['X-Webhook-Secret'] = webhookSecret
    }

    const body = {
      message_id: payload.message_id || '',
      from_phone: payload.from_phone || '',
      to_phone: payload.to_phone || '',
      text: payload.text || '',
      timestamp: payload.timestamp || new Date().toISOString(),
      source: payload.source || 'electron-baileys',
      is_group: Boolean(payload.is_group),
      chat_jid: payload.chat_jid || '',
      group_name: payload.group_name || payload.group_subject || '',
      group_subject: payload.group_subject || payload.group_name || '',
    }

    if (payload.has_media) {
      body.has_media = true
    }
    if (payload.has_audio) {
      body.has_audio = true
    }
    if (payload.has_image) {
      body.has_image = true
    }
    if (payload.has_document) {
      body.has_document = true
    }
    if (payload.media_mime_type) {
      body.media_mime_type = payload.media_mime_type
    }
    if (payload.media_data_base64) {
      body.media_data_base64 = payload.media_data_base64
    }
    if (payload.media_filename) {
      body.media_filename = payload.media_filename
    }
    if (payload.media_url) {
      body.media_url = payload.media_url
    }

    const response = await fetch(`${apiBase}/v1/whatsapp/inbound`, {
      method: 'POST',
      headers,
      body: JSON.stringify(body),
    })

    let data = {}
    try {
      data = await response.json()
    } catch {
      data = {}
    }

    if (!response.ok) {
      throw new Error(`backend inbound ${response.status}`)
    }

    deps.onRendererNotify?.('whatsapp:inbound', {
      ...body,
      uid: data.uid || null,
      stored: data.stored ?? false,
      status: data.status || 'ok',
    })

    return data
  }

  return { postInbound, loadAccessToken }
}

/**
 * A03: Cliente para eventos de ciclo de vida del canal WhatsApp.
 * Notifica al backend cambios de estado: linked, reconnecting, disconnected.
 *
 * @param {{
 *   loadSession: () => Promise<string | null>
 *   onRendererNotify?: (event: string, payload: Record<string, unknown>) => void
 * }} deps
 */
function createBackendChannelClient(deps) {
  const apiBase = (process.env.DOT_API_BASE_URL || 'http://127.0.0.1:8000')
    .trim()
    .replace(/\/+$/, '')

  /**
   * Obtiene el token JWT desde la sesión guardada.
   */
  async function _getToken() {
    const sessionStr = await deps.loadSession()
    if (!sessionStr) return ''
    try {
      const session = JSON.parse(sessionStr)
      return session?.accessToken || session?.access_token || session?.token || ''
    } catch {
      return sessionStr
    }
  }

  /**
   * POST /v1/whatsapp/channel/events
   * Notifica evento de ciclo de vida: linked, reconnecting, disconnected.
   *
   * @param {{
   *   event: 'linked' | 'reconnecting' | 'disconnected' | 'heartbeat'
   *   phone_number?: string | null
   *   error?: string | null
   *   source?: string
   * }} params
   */
  async function postChannelEvent(params) {
    const token = await _getToken()
    if (!token) {
      return { ok: false, reason: 'no_token' }
    }

    try {
      const response = await fetch(`${apiBase}/v1/whatsapp/channel/events`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          Authorization: `Bearer ${token}`,
        },
        body: JSON.stringify({
          event: params.event,
          phone_number: params.phone_number || null,
          error: params.error || null,
          source: params.source || 'electron-lifecycle',
        }),
      })

      if (!response.ok) {
        return { ok: false, status: response.status }
      }
      return { ok: true, event: params.event }
    } catch (err) {
      return { ok: false, error: String(err) }
    }
  }

  /**
   * POST /v1/whatsapp/channel/status
   * Sincroniza estado linked + phone_number con el backend.
   *
   * @param {{ linked: boolean; phone_number?: string | null; source?: string }} params
   */
  async function postChannelStatus(params) {
    const token = await _getToken()
    if (!token) {
      return { ok: false, reason: 'no_token' }
    }

    try {
      const response = await fetch(`${apiBase}/v1/whatsapp/channel/status`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          Authorization: `Bearer ${token}`,
        },
        body: JSON.stringify({
          linked: params.linked !== false,
          phone_number: params.phone_number || null,
          source: params.source || 'electron',
        }),
      })

      if (!response.ok) {
        return { ok: false, status: response.status }
      }
      return { ok: true, phone_number: params.phone_number || null }
    } catch (err) {
      return { ok: false, error: String(err) }
    }
  }

  return { postChannelEvent, postChannelStatus }
}

module.exports = {
  loadAccessToken,
  createBackendInboundClient,
  createBackendChannelClient,
}
