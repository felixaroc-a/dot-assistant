import type { WhatsAppLinkStatus } from '@/lib/api/whatsapp'

/** Snapshot de estado emitido por Electron (Baileys transport). */
export type ElectronWhatsAppStatus = {
  state?: string
  connectionState?: string
  linked?: boolean
  configured?: boolean
  daemonRunning?: boolean
  needsFreshLogin?: boolean
  error?: string | null
  lastError?: string | null
  phone_number?: string | null
}

const RESCAN_HINT =
  /logged.?out|sesión cerrada|escanea un qr|vuelve a escanear|needs_qr|no_saved_creds|local_session_missing/i

/** true cuando la sesión murió y hace falta QR nuevo (no un blip de red). */
export function electronNeedsWhatsAppRescan(status: ElectronWhatsAppStatus | null | undefined): boolean {
  if (!status) return false
  if (status.needsFreshLogin) return true
  if (status.configured === false) return true
  const err = String(status.error || status.lastError || '')
  return RESCAN_HINT.test(err)
}

/** Mapea estado local Baileys → etiqueta UI del dashboard. */
export function electronStatusToLinkStatus(
  status: ElectronWhatsAppStatus | null | undefined,
): WhatsAppLinkStatus | null {
  if (!status) return null

  const state = String(status.connectionState || status.state || '').trim()
  const needsQr = electronNeedsWhatsAppRescan(status)

  if (state === 'connected' && status.linked) return 'linked'
  if (state === 'starting' || state === 'restarting') return 'connecting'
  if (state === 'logging_in') return needsQr ? 'connecting' : 'connecting'
  if (state === 'disconnected') {
    if (needsQr) return 'disconnected'
    if (status.configured || status.linked) return 'connecting'
    return 'disconnected'
  }
  if (state === 'connected') return status.linked ? 'linked' : 'connecting'
  return null
}

/** Mensaje humano en español según estado local (tray / reconexión). */
export function electronWhatsAppHumanStatus(status: ElectronWhatsAppStatus | null | undefined): string | null {
  if (!status) return null
  const state = String(status.connectionState || status.state || '').trim()

  if (state === 'connected' && status.linked) return 'WhatsApp conectado.'
  if (electronNeedsWhatsAppRescan(status)) return 'Vuelve a escanear el código.'
  if (state === 'starting' || state === 'restarting' || state === 'disconnected') {
    if (status.configured || status.linked) return 'Reconectando WhatsApp…'
  }
  if (state === 'logging_in') return 'Generando código QR…'
  return null
}
