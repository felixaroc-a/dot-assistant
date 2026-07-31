import { useCallback, useEffect, useRef, useState } from 'react'
import { ApiError } from '@/lib/api/http'
import { translateApiError, translateErrorMessage } from '@/lib/error-messages'
import { resolveGoogleOAuthStatus } from '@/lib/api/google-oauth'

const POLL_INTERVAL_MS = 3_000
const POLL_INTERVAL_AFTER_429_MS = 15_000
const TIMEOUT_MS = 180_000 // 3 minutos

export type UseGoogleOAuthPollingResult = {
  configured: boolean
  loading: boolean
  error: string | null
  timedOut: boolean
}

export function useGoogleOAuthPolling(
  active: boolean,
  getAccessToken: () => Promise<string | null>,
): UseGoogleOAuthPollingResult {
  const [configured, setConfigured] = useState(false)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [timedOut, setTimedOut] = useState(false)

  const startedAtRef = useRef<number | null>(null)
  const pollTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const timeoutTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const mountedRef = useRef(true)

  const stopPolling = useCallback(() => {
    if (pollTimerRef.current !== null) {
      clearTimeout(pollTimerRef.current)
      pollTimerRef.current = null
    }
    if (timeoutTimerRef.current !== null) {
      clearTimeout(timeoutTimerRef.current)
      timeoutTimerRef.current = null
    }
    startedAtRef.current = null
    setLoading(false)
  }, [])

  useEffect(() => {
    mountedRef.current = true
    return () => {
      mountedRef.current = false
    }
  }, [])

  useEffect(() => {
    if (!active) {
      stopPolling()
      return
    }

    setConfigured(false)
    setError(null)
    setTimedOut(false)
    setLoading(true)

    startedAtRef.current = Date.now()

    // Timeout global de 3 minutos
    timeoutTimerRef.current = setTimeout(() => {
      if (!mountedRef.current) return
      stopPolling()
      setTimedOut(true)
    }, TIMEOUT_MS)

    const poll = async () => {
      if (!mountedRef.current) return

      try {
        const status = await resolveGoogleOAuthStatus(getAccessToken)

        if (!mountedRef.current) return

        if (status.configured) {
          stopPolling()
          setConfigured(true)
          return
        }

        // Programar siguiente polling
        scheduleNext()
      } catch (e) {
        if (!mountedRef.current) return

        if (e instanceof ApiError && e.status === 429) {
          // Rate limit del backend: no alarmar al usuario, reintentar con backoff.
          scheduleNext(POLL_INTERVAL_AFTER_429_MS)
          return
        }

        const isTransientNetworkError =
          e instanceof TypeError ||
          (e instanceof Error && e.name === 'AbortError')

        if (!isTransientNetworkError) {
          const errorMsg =
            e instanceof ApiError
              ? translateApiError(e, 'No se pudo verificar la conexión con Google.')
              : translateErrorMessage(
                  e instanceof Error ? e.message : 'Error al verificar estado de Google.',
                  'No se pudo verificar la conexión con Google.',
                )
          setError(errorMsg)
        }

        scheduleNext()
      }
    }

    const scheduleNext = (delayMs: number = POLL_INTERVAL_MS) => {
      if (!mountedRef.current) return
      pollTimerRef.current = setTimeout(poll, delayMs)
    }

    // Primer poll inmediato (sin esperar 3s)
    poll()

    return () => {
      stopPolling()
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [active])

  return { configured, loading, error, timedOut }
}
