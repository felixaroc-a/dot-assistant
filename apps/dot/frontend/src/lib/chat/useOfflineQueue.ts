/**
 * Hook para gestionar la cola de mensajes offline.
 *
 * Cuando el usuario esta offline, los mensajes se guardan en IndexedDB.
 * Al recuperar conexion, se re-intentan automaticamente.
 */
import { useCallback, useEffect, useRef, useState } from 'react'

import {
  addPendingMessage,
  countPendingMessages,
  getPendingMessages,
  incrementRetryCount,
  removePendingMessage,
} from '@/lib/offline-db'
import { sendMessage, type SendMessageRequest } from '@/lib/chat/client'

export type UseOfflineQueueOptions = {
  getAccessToken: () => Promise<string | null>
  onMessageSent?: (text: string) => void
  onMessageFailed?: (text: string, error: string) => void
}

export type UseOfflineQueueResult = {
  pendingCount: number
  isFlushing: boolean
  /** Encola un mensaje para envio (online o offline) */
  enqueue: (text: string) => Promise<boolean>
  /** Fuerza el re-envio de mensajes pendientes */
  flush: () => Promise<void>
}

const MAX_RETRIES = 5

export function useOfflineQueue({
  getAccessToken,
  onMessageSent,
  onMessageFailed,
}: UseOfflineQueueOptions): UseOfflineQueueResult {
  const [pendingCount, setPendingCount] = useState(0)
  const [isFlushing, setIsFlushing] = useState(false)
  const flushingRef = useRef(false)
  const isOnline = useRef(navigator.onLine)

  // Escuchar cambios de conectividad
  useEffect(() => {
    const handleOnline = () => {
      isOnline.current = true
      // Al reconectar, intentar enviar pendientes
      flush()
    }
    const handleOffline = () => {
      isOnline.current = false
    }

    window.addEventListener('online', handleOnline)
    window.addEventListener('offline', handleOffline)
    return () => {
      window.removeEventListener('online', handleOnline)
      window.removeEventListener('offline', handleOffline)
    }
  }, [])

  // Actualizar contador periodicamente
  useEffect(() => {
    const updateCount = async () => {
      const count = await countPendingMessages()
      setPendingCount(count)
    }
    updateCount()
    const interval = setInterval(updateCount, 5000)
    return () => clearInterval(interval)
  }, [])

  const flush = useCallback(async () => {
    if (flushingRef.current) return
    if (!navigator.onLine) return

    flushingRef.current = true
    setIsFlushing(true)

    try {
      const pending = await getPendingMessages()
      for (const msg of pending) {
        if (msg.retryCount >= MAX_RETRIES) {
          onMessageFailed?.(msg.text, msg.lastError || 'Max retries exceeded')
          await removePendingMessage(msg.id)
          continue
        }

        try {
          const token = await getAccessToken()
          const req: SendMessageRequest = { text: msg.text }
          await sendMessage(req, token)
          await removePendingMessage(msg.id)
          onMessageSent?.(msg.text)
        } catch (err) {
          const errorMsg = err instanceof Error ? err.message : 'Error de red'
          await incrementRetryCount(msg.id, errorMsg)

          if (msg.retryCount + 1 >= MAX_RETRIES) {
            onMessageFailed?.(msg.text, errorMsg)
          }

          if (!navigator.onLine) break // Salir si perdimos conexion
        }
      }
    } finally {
      flushingRef.current = false
      setIsFlushing(false)
      const count = await countPendingMessages()
      setPendingCount(count)
    }
  }, [getAccessToken, onMessageSent, onMessageFailed])

  const enqueue = useCallback(async (text: string): Promise<boolean> => {
    if (!text.trim()) return false

    if (!navigator.onLine) {
      await addPendingMessage(text.trim())
      setPendingCount(await countPendingMessages())
      return false // No se envio, quedo en cola
    }

    // Online: intentar enviar directo
    try {
      const token = await getAccessToken()
      const req: SendMessageRequest = { text: text.trim() }
      await sendMessage(req, token)
      return true // Enviado exitosamente
    } catch {
      // Fallo el envio, guardar en cola
      await addPendingMessage(text.trim())
      setPendingCount(await countPendingMessages())
      return false
    }
  }, [getAccessToken])

  return { pendingCount, isFlushing, enqueue, flush }
}
