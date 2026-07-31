/**
 * Utilidades para reconexion automatica de WhatsApp con backoff exponencial.
 *
 * Estrategia:
 * - Intento inicial inmediato
 * - Backoff exponencial: 5s, 10s, 20s, 40s, 80s (max 2min entre intentos)
 * - Maximo 10 intentos antes de rendirse
 * - Reset del contador si hay actividad del usuario
 */
import { translateErrorMessage } from '@/lib/error-messages'

const BASE_DELAY_MS = 5_000
const MAX_DELAY_MS = 120_000
const MAX_RETRIES = 10

export type ReconnectState = {
  attempt: number
  nextAttemptAt: number | null
  isReconnecting: boolean
  lastError: string | null
}

export type ReconnectCallback = {
  onAttempt: (attempt: number) => Promise<boolean>
  onMaxRetriesReached: () => void
}

/**
 * Calcula el delay para el siguiente intento (backoff exponencial).
 */
export function calculateBackoff(attempt: number): number {
  const delay = BASE_DELAY_MS * Math.pow(2, attempt - 1)
  return Math.min(delay, MAX_DELAY_MS)
}

/**
 * Gestiona la reconexion automatica de WhatsApp.
 *
 * Uso:
 * ```ts
 * const reconnector = createReconnector({
 *   onAttempt: async (attempt) => {
 *     // intentar reconectar
 *     return true // o false si fallo
 *   },
 *   onMaxRetriesReached: () => {
 *     // notificar al usuario
 *   },
 * })
 * reconnector.start()
 * ```
 */
export function createReconnector(callbacks: ReconnectCallback) {
  let state: ReconnectState = {
    attempt: 0,
    nextAttemptAt: null,
    isReconnecting: false,
    lastError: null,
  }
  let timeoutId: ReturnType<typeof setTimeout> | null = null
  let cancelled = false

  function getState(): ReconnectState {
    return { ...state }
  }

  async function attempt() {
    if (cancelled || state.isReconnecting) return

    state.attempt++
    state.isReconnecting = true
    state.lastError = null

    const nextDelay = calculateBackoff(state.attempt)
    const now = Date.now()

    try {
      const success = await callbacks.onAttempt(state.attempt)

      if (cancelled) return

      if (success) {
        reset()
        return
      }

      // Fallo: programar siguiente intento
      state.nextAttemptAt = now + nextDelay
      state.lastError = `Intento ${state.attempt}/${MAX_RETRIES} fallo`

      if (state.attempt >= MAX_RETRIES) {
        state.isReconnecting = false
        state.lastError = `Se alcanzó el máximo de ${MAX_RETRIES} intentos de reconexión`
        callbacks.onMaxRetriesReached()
        return
      }

      state.isReconnecting = false
      // Usar setTimeout en vez de setInterval para backoff variable
      timeoutId = setTimeout(() => void attempt(), nextDelay)
    } catch (err) {
      if (cancelled) return
      state.lastError = translateErrorMessage(
        err instanceof Error ? err.message : 'Error desconocido en reconexión',
        'No pude reconectar WhatsApp. Escanea el código de nuevo.',
      )
      state.isReconnecting = false

      if (state.attempt < MAX_RETRIES) {
        state.nextAttemptAt = Date.now() + nextDelay
        timeoutId = setTimeout(() => void attempt(), nextDelay)
      } else {
        callbacks.onMaxRetriesReached()
      }
    }
  }

  function start() {
    reset()
    cancelled = false
    void attempt()
  }

  function reset() {
    if (timeoutId !== null) {
      clearTimeout(timeoutId)
      timeoutId = null
    }
    state = { attempt: 0, nextAttemptAt: null, isReconnecting: false, lastError: null }
  }

  function cancel() {
    cancelled = true
    reset()
  }

  return { start, reset, cancel, getState }
}

/**
 * Hook-friendly: crea callbacks para reconectar con el backend de DOT.
 */
export function createWhatsAppReconnector(
  reconnectFn: () => Promise<boolean>,
  onStatusChange: (state: ReconnectState) => void,
) {
  return createReconnector({
    onAttempt: async (attempt) => {
      console.info(`[WhatsApp] Intento de reconexion #${attempt}`)
      const success = await reconnectFn()
      onStatusChange({
        attempt,
        nextAttemptAt: success ? null : Date.now() + calculateBackoff(attempt),
        isReconnecting: !success,
        lastError: success ? null : `Reconexion fallida (intento ${attempt})`,
      })
      return success
    },
    onMaxRetriesReached: () => {
      console.warn('[WhatsApp] Maximos intentos de reconexion alcanzados')
      onStatusChange({
        attempt: MAX_RETRIES,
        nextAttemptAt: null,
        isReconnecting: false,
        lastError: 'No se pudo reconectar. Vuelve a escanear el código.',
      })
    },
  })
}
