import { useEffect } from 'react'

import type { AutomationPendingResponse } from '@/features/dashboard/model/types'

export const MORNING_BRIEFING_AUTO_ID = 'morning-briefing-v1'

export type DashboardNotificationsProps = {
  hasPendingResults: boolean
  pendingAutomation: AutomationPendingResponse | null
  onViewResults: () => void
  onDismissResults: () => void
}

export function DashboardNotifications({
  hasPendingResults,
  pendingAutomation,
  onViewResults,
  onDismissResults,
}: DashboardNotificationsProps) {
  const isMorningBriefing =
    pendingAutomation?.last_auto_id === MORNING_BRIEFING_AUTO_ID

  useEffect(() => {
    if (!hasPendingResults || !pendingAutomation) return
    const timer = setTimeout(() => {
      onDismissResults()
    }, 30_000)
    return () => clearTimeout(timer)
  }, [hasPendingResults, pendingAutomation, onDismissResults])

  if (!hasPendingResults || !pendingAutomation) return null

  const title = isMorningBriefing
    ? pendingAutomation.last_auto_name || 'Tu día en 30s'
    : 'Resultado de automatización'

  const preview =
    pendingAutomation.last_result_preview ||
    (isMorningBriefing
      ? 'Tu resumen de correos y citas está listo.'
      : 'Hay resultados nuevos listos para revisar.')

  return (
    <div
      className={`main-dashboard__notification${isMorningBriefing ? ' main-dashboard__notification--briefing' : ''}`}
      role="alert"
      aria-live="polite"
    >
      <div className="main-dashboard__notification-body">
        <strong>{title}</strong>
        {!isMorningBriefing && pendingAutomation.last_auto_name ? (
          <p>{pendingAutomation.last_auto_name}</p>
        ) : null}
        <p className="main-dashboard__notification-preview">{preview}</p>
      </div>
      <div className="main-dashboard__notification-actions">
        <button
          type="button"
          className="main-dashboard__notification-btn"
          onClick={onViewResults}
        >
          {isMorningBriefing ? 'Ver mi día' : 'Ver resultado'}
        </button>
        <button
          type="button"
          className="main-dashboard__notification-close"
          onClick={onDismissResults}
          aria-label="Cerrar notificación"
        >
          ×
        </button>
      </div>
    </div>
  )
}
