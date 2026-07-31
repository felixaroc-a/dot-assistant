import { useCallback, useEffect, useRef, useState } from 'react'

import { getWhatsAppChannelStatus, toLinkStatus } from '@/lib/api/whatsapp'
import type { GetAccessToken } from '@/lib/api/client'
import type { WhatsAppLinkStatus } from '@/lib/api/whatsapp'
import {
  electronNeedsWhatsAppRescan,
  electronStatusToLinkStatus,
  type ElectronWhatsAppStatus,
} from '@/lib/whatsapp/localStatus'

export type UseDashboardWhatsAppOptions = {
  getAccessToken: GetAccessToken
  setWhatsappStatus: (status: WhatsAppLinkStatus) => void
  /** ID de la conversación activa actual */
  activeConversationId?: string | null
  /** Refresca la lista de conversaciones desde el backend */
  refreshConversations: () => Promise<void>
  /** Carga una conversación específica en el chat */
  loadConversation: (id: string) => Promise<unknown>
}

export type UseDashboardWhatsAppResult = {
  whatsappRefreshing: boolean
  /** Número de teléfono vinculado (para outbound A07) */
  phoneNumber: string | null
  refreshWhatsappStatus: () => Promise<void>
}

function mergeLinkStatus(
  backend: WhatsAppLinkStatus,
  local: WhatsAppLinkStatus | null,
): WhatsAppLinkStatus {
  if (!local) return backend
  // Local conectado gana sobre backend desfasado tras reinicio.
  if (local === 'linked') return 'linked'
  // Reconexión silenciosa en Electron: no mostrar desconectado si hay sesión.
  if (local === 'connecting' && backend === 'disconnected') return 'connecting'
  if (backend === 'linked') return 'linked'
  return backend
}

export function useDashboardWhatsApp({
  getAccessToken,
  setWhatsappStatus,
  activeConversationId,
  refreshConversations,
  loadConversation,
}: UseDashboardWhatsAppOptions): UseDashboardWhatsAppResult {
  const [whatsappRefreshing, setWhatsappRefreshing] = useState(false)
  const [phoneNumber, setPhoneNumber] = useState<string | null>(null)
  const localStatusRef = useRef<ElectronWhatsAppStatus | null>(null)
  const restoreAttemptedRef = useRef(false)

  const applyStatus = useCallback(
    (backendStatus: WhatsAppLinkStatus, phone: string | null) => {
      const localLink = electronStatusToLinkStatus(localStatusRef.current)
      setWhatsappStatus(mergeLinkStatus(backendStatus, localLink))
      if (phone) setPhoneNumber(phone)
      else if (localStatusRef.current?.phone_number) {
        setPhoneNumber(String(localStatusRef.current.phone_number))
      }
    },
    [setWhatsappStatus],
  )

  const refreshWhatsappStatus = useCallback(async () => {
    setWhatsappRefreshing(true)
    try {
      const status = await getWhatsAppChannelStatus(getAccessToken)
      applyStatus(toLinkStatus(status), status.phone_number ?? null)
    } catch (err) {
      console.warn('[Dashboard] No se pudo obtener estado de WhatsApp:', err)
      const localLink = electronStatusToLinkStatus(localStatusRef.current)
      if (localLink === 'linked' || localLink === 'connecting') {
        setWhatsappStatus(localLink)
      } else {
        setWhatsappStatus('disconnected')
      }
    } finally {
      setWhatsappRefreshing(false)
    }
  }, [applyStatus, getAccessToken])

  // Reconexión silenciosa al montar (Electron / bandeja tras reinicio).
  useEffect(() => {
    const wa = window.desktop?.whatsapp
    if (!wa?.restoreSession || restoreAttemptedRef.current) return
    restoreAttemptedRef.current = true

    void (async () => {
      try {
        const local = (await wa.getStatus?.()) as ElectronWhatsAppStatus | undefined
        if (local) localStatusRef.current = local
        if (local?.linked && local?.connectionState === 'connected') {
          applyStatus('linked', local.phone_number ?? null)
          return
        }
        if (electronNeedsWhatsAppRescan(local)) return

        const result = await wa.restoreSession()
        if (result?.ok && !result.needs_qr) {
          applyStatus('connecting', result.phone_number ?? null)
        }
      } catch (err) {
        console.warn('[Dashboard] restoreSession al arranque:', err)
      }
    })()
  }, [applyStatus])

  // Estado en tiempo real desde main (Baileys reconectando sin QR).
  useEffect(() => {
    const onStatus = window.desktop?.whatsapp?.onStatus
    if (!onStatus) return

    return onStatus((payload: ElectronWhatsAppStatus) => {
      localStatusRef.current = payload
      const localLink = electronStatusToLinkStatus(payload)
      if (!localLink) return

      setWhatsappStatus(localLink)

      if (payload.phone_number) {
        setPhoneNumber(String(payload.phone_number))
      }

      if (localLink === 'linked') {
        void refreshWhatsappStatus()
      }
    })
  }, [refreshWhatsappStatus, setWhatsappStatus])

  // Poll de estado del backend cada 15s
  useEffect(() => {
    void refreshWhatsappStatus()
    const interval = setInterval(() => {
      void refreshWhatsappStatus()
    }, 15_000)
    return () => clearInterval(interval)
  }, [refreshWhatsappStatus])

  // B3: cuando llega un mensaje WA por Electron, refrescar hilo "WhatsApp" en el chat PC.
  useEffect(() => {
    const onInbound = window.desktop?.whatsapp?.onInbound
    if (!onInbound) return

    const timers: number[] = []
    const reloadWhatsAppThread = async () => {
      try {
        await refreshConversations()
        const token = await getAccessToken()
        const { getConversations } = await import('@/lib/chat/client')
        const fresh = await getConversations(token)
        const wa = fresh.find((c) => (c.title || '').trim().toLowerCase() === 'whatsapp')
        if (!wa) return
        if (activeConversationId === wa.id) {
          await loadConversation(wa.id)
        }
      } catch (err) {
        console.warn('[Dashboard] B3 refresh WhatsApp thread failed:', err)
      }
    }

    const unsubscribe = onInbound(() => {
      void reloadWhatsAppThread()
      for (const ms of [2500, 7000]) {
        timers.push(
          window.setTimeout(() => {
            void reloadWhatsAppThread()
          }, ms),
        )
      }
    })

    return () => {
      unsubscribe()
      for (const t of timers) window.clearTimeout(t)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [getAccessToken, loadConversation, activeConversationId, refreshConversations])

  return { whatsappRefreshing, phoneNumber, refreshWhatsappStatus }
}
