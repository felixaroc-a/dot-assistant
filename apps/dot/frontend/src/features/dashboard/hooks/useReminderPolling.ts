import { useEffect } from 'react'

export type UseReminderPollingOptions = {
  getAccessToken: () => Promise<string | null>
}

/**
 * Recordatorios de chat: el toast Windows lo emite el proceso principal
 * (`background-notify-poller.cjs`) para funcionar con DOT en bandeja.
 * Este hook se mantiene por compatibilidad con tests y futura sincronización UI.
 */
export function useReminderPolling(_options: UseReminderPollingOptions) {
  useEffect(() => {
    // Sin polling en renderer — ver electron/background-notify-poller.cjs
  }, [])
}
