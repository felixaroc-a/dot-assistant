import { useEffect, useRef } from 'react'

import type { AutomationPendingResponse } from '@/features/dashboard/model/types'
import { apiFetchAuthed } from '@/lib/api/client'

function normalizePendingAutomation(raw: Partial<AutomationPendingResponse> | null | undefined): AutomationPendingResponse {
  return {
    has_new: Boolean(raw?.has_new),
    last_auto_id: raw?.last_auto_id?.trim() || null,
    last_auto_name: raw?.last_auto_name?.trim() || null,
    last_executed_at: raw?.last_executed_at?.trim() || null,
    last_result_preview: raw?.last_result_preview?.trim() || null,
  }
}

export type UseAutomationPollingOptions = {
  getAccessToken: () => Promise<string | null>
  onPendingResults: (pending: AutomationPendingResponse) => void
  onNoPendingResults: () => void
}

/**
 * Sincroniza el badge de resultados pendientes en el dashboard.
 * Los toasts Windows los emite el proceso principal (background-notify-poller.cjs).
 */
export function useAutomationPolling({
  getAccessToken,
  onPendingResults,
  onNoPendingResults,
}: UseAutomationPollingOptions) {
  const cancelledRef = useRef(false)
  const inFlightRef = useRef(false)

  useEffect(() => {
    cancelledRef.current = false

    const isOffline = () =>
      typeof navigator !== 'undefined' && navigator.onLine === false

    const pollPendingAutomationResults = async () => {
      if (cancelledRef.current || inFlightRef.current) return
      if (isOffline()) return
      inFlightRef.current = true
      try {
        const pendingRaw = await apiFetchAuthed<AutomationPendingResponse>(
          '/v1/automations/results/pending',
          { method: 'GET' },
          getAccessToken,
        )
        if (cancelledRef.current) return

        const pending = normalizePendingAutomation(pendingRaw)
        if (!pending.has_new) {
          onNoPendingResults()
          return
        }

        onPendingResults(pending)
      } catch (e) {
        if (e instanceof TypeError || (e instanceof Error && (e.message.includes('Failed to fetch') || e.message.includes('NetworkError')))) {
          return
        }
        console.warn('[useAutomationPolling] Error en polling de resultados de automatización')
      } finally {
        inFlightRef.current = false
      }
    }

    void pollPendingAutomationResults()
    const interval = window.setInterval(() => {
      void pollPendingAutomationResults()
    }, 30_000)

    return () => {
      cancelledRef.current = true
      window.clearInterval(interval)
    }
  }, [getAccessToken, onPendingResults, onNoPendingResults])
}
