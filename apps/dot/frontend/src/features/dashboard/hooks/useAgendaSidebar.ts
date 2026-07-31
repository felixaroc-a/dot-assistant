import { useCallback, useEffect, useRef, useState } from 'react'

import type { AgendaTodayResponse } from '@/features/dashboard/model/types'
import { apiFetchAuthed } from '@/lib/api/client'
import type { GetAccessToken } from '@/lib/api/api-client'

const DEFAULT_POLL_MS = 120_000

export type AgendaSidebarEvent = AgendaTodayResponse['events'][number]

export type UseAgendaSidebarOptions = {
  getAccessToken: GetAccessToken
  pollIntervalMs?: number
  enabled?: boolean
}

export type UseAgendaSidebarResult = {
  linked: boolean
  events: AgendaSidebarEvent[]
  message: string | null
  loading: boolean
  error: string | null
  refresh: () => Promise<void>
}

export function useAgendaSidebar({
  getAccessToken,
  pollIntervalMs = DEFAULT_POLL_MS,
  enabled = true,
}: UseAgendaSidebarOptions): UseAgendaSidebarResult {
  const [linked, setLinked] = useState(false)
  const [events, setEvents] = useState<AgendaSidebarEvent[]>([])
  const [message, setMessage] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const inFlightRef = useRef(false)

  const refresh = useCallback(async () => {
    if (!enabled || inFlightRef.current) return
    if (typeof navigator !== 'undefined' && navigator.onLine === false) return
    inFlightRef.current = true
    try {
      const data = await apiFetchAuthed<AgendaTodayResponse>(
        '/v1/chat/agenda/today',
        { method: 'GET' },
        getAccessToken,
      )
      setLinked(Boolean(data.linked))
      setEvents(data.events ?? [])
      setMessage(data.message?.trim() || null)
      setError(null)
    } catch (e) {
      const errMessage = e instanceof Error ? e.message : 'No se pudo cargar la agenda de hoy.'
      setError(errMessage)
      setLinked(false)
      setEvents([])
    } finally {
      inFlightRef.current = false
      setLoading(false)
    }
  }, [enabled, getAccessToken])

  useEffect(() => {
    if (!enabled) {
      setLoading(false)
      return
    }
    void refresh()
    const timer = window.setInterval(() => {
      void refresh()
    }, pollIntervalMs)
    return () => window.clearInterval(timer)
  }, [enabled, pollIntervalMs, refresh])

  return { linked, events, message, loading, error, refresh }
}
