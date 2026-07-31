/**
 * Hook para gestionar la conexion WhatsApp con reconexion automatica.
 *
 * Combina:
 * - Polling de estado del canal
 * - Reconexion automatica con backoff exponencial
 * - Heartbeat constante
 * - Deteccion de desconexion y recuperacion
 */
import { useCallback, useEffect, useRef, useState } from 'react'

import { getWhatsAppChannelStatus, requestWhatsAppReconnect, sendWhatsAppChannelEvent, toLinkStatus, type WhatsAppChannelStatus } from '@/lib/api/whatsapp'
import { createWhatsAppReconnector, type ReconnectState } from '@/lib/whatsapp-reconnect'

export type UseWhatsAppConnectionOptions = {
  getAccessToken: () => Promise<string | null>
  /** Intervalo de polling en ms (default: 15000) */
  pollIntervalMs?: number
  /** Auto-reconectar cuando se detecta desconexion */
  autoReconnect?: boolean
}

export type UseWhatsAppConnectionResult = {
  status: WhatsAppChannelStatus | null
  linkStatus: ReturnType<typeof toLinkStatus>
  reconnection: ReconnectState
  isOnline: boolean
  refresh: () => Promise<WhatsAppChannelStatus | null>
  reconnect: () => Promise<boolean>
  sendEvent: (event: string, extra?: { phone_number?: string | null; error?: string | null }) => Promise<void>
}

export function useWhatsAppConnection({
  getAccessToken,
  pollIntervalMs = 15_000,
  autoReconnect = true,
}: UseWhatsAppConnectionOptions): UseWhatsAppConnectionResult {
  const [status, setStatus] = useState<WhatsAppChannelStatus | null>(null)
  const [reconnection, setReconnection] = useState<ReconnectState>({
    attempt: 0, nextAttemptAt: null, isReconnecting: false, lastError: null,
  })
  const pollTimerRef = useRef<ReturnType<typeof setInterval> | null>(null)

  const refresh = useCallback(async () => {
    try {
      const s = await getWhatsAppChannelStatus(getAccessToken)
      setStatus(s)
      return s
    } catch {
      return null
    }
  }, [getAccessToken])

  const reconnect = useCallback(async () => {
    try {
      const s = await requestWhatsAppReconnect(getAccessToken)
      setStatus(s)
      await sendWhatsAppChannelEvent({ event: 'reconnecting', source: 'dot-desktop' }, getAccessToken)
      return true
    } catch {
      return false
    }
  }, [getAccessToken])

  const sendEvent = useCallback(async (
    event: string,
    extra?: { phone_number?: string | null; error?: string | null },
  ) => {
    try {
      const s = await sendWhatsAppChannelEvent(
        {
          event: event as any,
          phone_number: extra?.phone_number ?? null,
          error: extra?.error ?? null,
          channel_name: 'whatsapp',
          source: 'dot-desktop',
        },
        getAccessToken,
      )
      setStatus(s)
    } catch {
      console.warn('[WhatsApp] Error al enviar evento:', event)
    }
  }, [getAccessToken])

  // Iniciar polling
  useEffect(() => {
    void refresh()
    pollTimerRef.current = setInterval(() => { void refresh() }, pollIntervalMs)
    return () => {
      if (pollTimerRef.current) clearInterval(pollTimerRef.current)
    }
  }, [refresh, pollIntervalMs])

  // Auto-reconexion al detectar desconexion
  useEffect(() => {
    if (!autoReconnect || !status) return
    if (status.status === 'linked' || status.status === 'connecting') return
    if (reconnection.isReconnecting) return

    const reconnector = createWhatsAppReconnector(
      async () => {
        try {
          await requestWhatsAppReconnect(getAccessToken)
          const newStatus = await getWhatsAppChannelStatus(getAccessToken)
          setStatus(newStatus)
          return newStatus?.status === 'linked' || newStatus?.status === 'connecting'
        } catch {
          return false
        }
      },
      (newState) => setReconnection(newState),
    )

    reconnector.start()

    return () => reconnector.cancel()
  }, [autoReconnect, status?.status, getAccessToken])

  const linkStatus = toLinkStatus(status ?? { status: 'disconnected', linked: false, phone_number: null, channel_name: null, last_linked_at: null, last_disconnected_at: null, last_qr_at: null, last_heartbeat_at: null, last_error_at: null, reconnect_required: false, reconnect_attempts: 0, error: null })

  return {
    status,
    linkStatus,
    reconnection,
    isOnline: status?.status === 'linked',
    refresh,
    reconnect: async () => {
      const result = await reconnect()
      return result
    },
    sendEvent,
  }
}
