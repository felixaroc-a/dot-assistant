import { useEffect, useRef } from 'react'

import { apiFetchAuthed } from '@/lib/api/client'

type MorningBriefingBootResponse = {
  ran: boolean
  reason?: string | null
  preview?: string | null
}

export type UseMorningBriefingBootOptions = {
  getAccessToken: () => Promise<string | null>
  onBriefingReady?: (preview: string) => void
}

/**
 * Al abrir el dashboard, pide al backend el briefing matutino si ya pasó la hora
 * configurada y aún no se entregó hoy (catch-up estilo heartbeat OpenClaw).
 */
export function useMorningBriefingBoot({
  getAccessToken,
  onBriefingReady,
}: UseMorningBriefingBootOptions) {
  const ranRef = useRef(false)

  useEffect(() => {
    if (ranRef.current) return
    ranRef.current = true

    void (async () => {
      try {
        const result = await apiFetchAuthed<MorningBriefingBootResponse>(
          '/v1/briefing/maybe-run-on-boot',
          { method: 'POST' },
          getAccessToken,
        )
        if (result.ran && result.preview?.trim()) {
          onBriefingReady?.(result.preview.trim())
        }
      } catch {
        /* silencioso — el cron o el poller cubren el caso */
      }
    })()
  }, [getAccessToken, onBriefingReady])
}
