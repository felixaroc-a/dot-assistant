import { useCallback, useEffect, useRef, useState } from 'react'

import type { PendingReminderResponse } from '@/features/dashboard/model/types'
import { apiFetchAuthed } from '@/lib/api/client'
import type { GetAccessToken } from '@/lib/api/api-client'

const DEFAULT_POLL_MS = 30_000

export type ReminderItem = PendingReminderResponse['reminders'][number]

export type UseRemindersPanelOptions = {
  getAccessToken: GetAccessToken
  pollIntervalMs?: number
  enabled?: boolean
}

export type UseRemindersPanelResult = {
  reminders: ReminderItem[]
  loading: boolean
  error: string | null
  dismiss: (id: string) => Promise<void>
  snooze: (id: string, text: string, minutes: number) => Promise<void>
  refresh: () => Promise<void>
}

export function useRemindersPanel({
  getAccessToken,
  pollIntervalMs = DEFAULT_POLL_MS,
  enabled = true,
}: UseRemindersPanelOptions): UseRemindersPanelResult {
  const [reminders, setReminders] = useState<ReminderItem[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const inFlightRef = useRef(false)

  const refresh = useCallback(async () => {
    if (!enabled || inFlightRef.current) return
    if (typeof navigator !== 'undefined' && navigator.onLine === false) return
    inFlightRef.current = true
    try {
      const data = await apiFetchAuthed<PendingReminderResponse>(
        '/v1/chat/reminders/pending',
        { method: 'GET' },
        getAccessToken,
      )
      setReminders(data.reminders ?? [])
      setError(null)
    } catch (e) {
      const message = e instanceof Error ? e.message : 'No se pudieron cargar los recordatorios.'
      setError(message)
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

  const dismiss = useCallback(
    async (id: string) => {
      const cleanId = id.trim()
      if (!cleanId) return
      await apiFetchAuthed(
        '/v1/chat/reminders/ack',
        {
          method: 'POST',
          body: JSON.stringify({ ids: [cleanId] }),
        },
        getAccessToken,
      )
      setReminders((prev) => prev.filter((item) => item.id !== cleanId))
    },
    [getAccessToken],
  )

  const snooze = useCallback(
    async (id: string, text: string, minutes: number) => {
      const cleanId = id.trim()
      const cleanText = text.trim()
      if (!cleanId || !cleanText || minutes <= 0) return

      const dueAt = new Date(Date.now() + minutes * 60_000).toISOString()
      await apiFetchAuthed(
        '/v1/chat/reminders',
        {
          method: 'POST',
          body: JSON.stringify({ text: cleanText, due_at: dueAt }),
        },
        getAccessToken,
      )
      await dismiss(cleanId)
    },
    [dismiss, getAccessToken],
  )

  return { reminders, loading, error, dismiss, snooze, refresh }
}
