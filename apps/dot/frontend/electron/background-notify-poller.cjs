'use strict'

/**
 * Polling en proceso principal: recordatorios, cron, briefing y avisos proactivos.
 * Sigue activo con DOT minimizado a la bandeja del sistema (Loop-12).
 */

const { loadAccessToken } = require('./whatsapp/backend-client.cjs')
const { createSystemNotifier } = require('./system-notify.cjs')

const POLL_INTERVAL_MS = 30_000
const KV_AUTO_FINGERPRINT = 'dot.notify.automation.fingerprint'

/**
 * @param {Record<string, unknown> | null | undefined} pending
 */
function automationToastTitle(pending) {
  const autoId = String(pending?.last_auto_id || '').trim()
  const autoName = String(pending?.last_auto_name || '').trim()

  if (autoId === 'morning-briefing-v1') return 'DOT — Tu día en 30s'
  if (autoId === 'cron_reminder') return 'DOT — Recordatorio programado'
  if (/proactiv/i.test(autoName) || autoId.startsWith('proactive')) {
    return 'DOT — Aviso proactivo'
  }
  if (autoName) return `DOT — ${autoName}`
  return 'DOT — Automatización'
}

/**
 * @param {{
 *   secureStorage: { loadSession: () => Promise<string | null> }
 *   localDb: { get: (key: string) => string | null, set: (key: string, value: string) => void }
 *   Notification: typeof import('electron').Notification
 *   sanitizeNotificationText: (text: string, max?: number) => string
 *   showMainWindow: () => void
 *   getMainWindow: () => import('electron').BrowserWindow | null
 * }} deps
 */
function createBackgroundNotifyPoller(deps) {
  const {
    secureStorage,
    localDb,
    Notification,
    sanitizeNotificationText,
    showMainWindow,
    getMainWindow,
  } = deps

  const apiBase = (process.env.DOT_API_BASE_URL || 'http://127.0.0.1:8000')
    .trim()
    .replace(/\/+$/, '')

  let timer = null
  let inFlight = false
  let cancelled = false
  /** @type {Set<string>} */
  const remindedInSession = new Set()

  const notifier = createSystemNotifier({
    Notification,
    sanitizeNotificationText,
    showMainWindow,
  })

  async function getToken() {
    return loadAccessToken(() => secureStorage.loadSession())
  }

  /**
   * @param {string} path
   * @param {RequestInit} [init]
   */
  async function apiFetch(path, init) {
    const token = await getToken()
    if (!token) return null

    const response = await fetch(`${apiBase}${path}`, {
      ...init,
      headers: {
        'Content-Type': 'application/json',
        Authorization: `Bearer ${token}`,
        ...(init?.headers || {}),
      },
    })

    if (!response.ok) return null

    try {
      return await response.json()
    } catch {
      return null
    }
  }

  async function pollReminders() {
    const data = await apiFetch('/v1/chat/reminders/pending', { method: 'GET' })
    if (!data?.reminders?.length) return

    /** @type {string[]} */
    const deliveredIds = []

    for (const reminder of data.reminders) {
      const id = String(reminder?.id || '').trim()
      const text = String(reminder?.text || '').trim()
      if (!id || !text) continue
      if (remindedInSession.has(id)) continue

      const shown = notifier.showSystemToast('DOT — Recordatorio', text)
      if (!shown) continue

      remindedInSession.add(id)
      deliveredIds.push(id)
    }

    if (deliveredIds.length > 0) {
      await apiFetch('/v1/chat/reminders/ack', {
        method: 'POST',
        body: JSON.stringify({ ids: deliveredIds }),
      })
    }
  }

  async function pollAutomationResults() {
    const pending = await apiFetch('/v1/automations/results/pending', { method: 'GET' })
    if (!pending?.has_new) return

    const fingerprint = `${pending.last_auto_id ?? ''}|${pending.last_executed_at ?? ''}`
    if (!fingerprint || fingerprint === '|') return

    const stored = localDb.get(KV_AUTO_FINGERPRINT)
    if (fingerprint === stored) return

    const title = automationToastTitle(pending)
    const autoName = String(pending.last_auto_name || 'Automatización').trim()
    const preview = String(
      pending.last_result_preview || 'Abre DOT para ver los detalles.',
    ).trim()
    const body = `${autoName}: ${preview}`.slice(0, 300)

    const eventPayload = {
      autoId: sanitizeNotificationText(String(pending.last_auto_id || ''), 80),
      autoName: sanitizeNotificationText(autoName, 120),
      executedAt: sanitizeNotificationText(String(pending.last_executed_at || ''), 64),
      preview: sanitizeNotificationText(preview, 280),
    }

    const clickNotifier = createSystemNotifier({
      Notification,
      sanitizeNotificationText,
      showMainWindow,
      onClick: () => {
        const win = getMainWindow()
        if (win && !win.isDestroyed()) {
          try {
            win.webContents.send('dot:automation-notification-clicked', eventPayload)
          } catch {
            /* silencioso */
          }
        }
      },
    })

    const shown = clickNotifier.showSystemToast(title, body)
    if (shown) {
      localDb.set(KV_AUTO_FINGERPRINT, fingerprint)
    }
  }

  async function tick() {
    if (cancelled || inFlight) return
    inFlight = true
    try {
      const token = await getToken()
      if (!token) return
      await pollReminders()
      await pollAutomationResults()
    } catch {
      /* errores de red — reintentar en el próximo ciclo */
    } finally {
      inFlight = false
    }
  }

  function start() {
    if (process.platform !== 'win32') return
    cancelled = false
    void tick()
    timer = setInterval(() => {
      void tick()
    }, POLL_INTERVAL_MS)
    console.info('[background-notify] Poller activo (recordatorios, cron, briefing, proactivos)')
  }

  function stop() {
    cancelled = true
    if (timer) {
      clearInterval(timer)
      timer = null
    }
  }

  return { start, stop, tick }
}

module.exports = { createBackgroundNotifyPoller, automationToastTitle }
