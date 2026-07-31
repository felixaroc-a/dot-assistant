import { useCallback, useEffect, useRef, useState } from 'react'

import { fetchUsageDaily, fetchUsageSummary, type UsageDailyItem, type UsageSummary } from '@/lib/api/usage'
import type { GetAccessToken } from '@/lib/api/api-client'

const DEFAULT_POLL_MS = 60_000

export type UseUsageSummaryOptions = {
  getAccessToken: GetAccessToken
  pollIntervalMs?: number
  enabled?: boolean
}

export type UseUsageSummaryResult = {
  summary: UsageSummary | null
  loading: boolean
  error: string | null
  dailyHistory: UsageDailyItem[] | null
  refresh: () => Promise<void>
  refreshNow: () => Promise<void>
}

export function useUsageSummary({
  getAccessToken,
  pollIntervalMs = DEFAULT_POLL_MS,
  enabled = true,
}: UseUsageSummaryOptions): UseUsageSummaryResult {
  const [summary, setSummary] = useState<UsageSummary | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [dailyHistory, setDailyHistory] = useState<UsageDailyItem[] | null>(null)
  const inFlightRef = useRef(false)

  const refresh = useCallback(async () => {
    if (!enabled || inFlightRef.current) return
    if (typeof navigator !== 'undefined' && navigator.onLine === false) return
    inFlightRef.current = true
    try {
      const data = await fetchUsageSummary(getAccessToken)
      setSummary(data)
      setError(null)
      // OB04: Cargar historial diario en paralelo
      try {
        const daily = await fetchUsageDaily(getAccessToken)
        setDailyHistory(daily.days)
      } catch {
        // Silencio: el historial diario es opcional
      }
    } catch (e) {
      const message = e instanceof Error ? e.message : 'No se pudo cargar el consumo de IA.'
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

  const refreshNow = useCallback(async () => {
    if (!enabled) return
    if (typeof navigator !== 'undefined' && navigator.onLine === false) return
    try {
      const data = await fetchUsageSummary(getAccessToken)
      setSummary(data)
      setError(null)
      try {
        const daily = await fetchUsageDaily(getAccessToken)
        setDailyHistory(daily.days)
      } catch { /* opcional */ }
    } catch (e) {
      const message = e instanceof Error ? e.message : 'No se pudo cargar el consumo de IA.'
      setError(message)
    } finally {
      setLoading(false)
    }
  }, [enabled, getAccessToken])

  return { summary, loading, error, dailyHistory, refresh, refreshNow }
}
