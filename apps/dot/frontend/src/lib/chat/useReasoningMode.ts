import { useCallback, useEffect, useState } from 'react'

import { patchUserProfile } from '@/lib/api/user-profile'

export type ReasoningLevel = 'low' | 'medium' | 'high' | 'auto'

const STORAGE_KEY = 'dot-reasoning-mode'

type StoredReasoning = {
  enabled: boolean
  level: ReasoningLevel
}

function readStored(): StoredReasoning {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    if (!raw) return { enabled: true, level: 'auto' }
    const parsed = JSON.parse(raw) as Partial<StoredReasoning>
    const level = parsed.level
    const validLevel: ReasoningLevel =
      level === 'low' || level === 'medium' || level === 'high' || level === 'auto'
        ? level
        : 'auto'
    return { enabled: Boolean(parsed.enabled), level: validLevel }
  } catch {
    return { enabled: false, level: 'auto' }
  }
}

function writeStored(data: StoredReasoning) {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(data))
  } catch {
    // localStorage no disponible
  }
}

export type UseReasoningModeOptions = {
  getAccessToken: () => Promise<string | null>
  profileEnabled?: boolean
  profileLevel?: ReasoningLevel
}

export function useReasoningMode({
  getAccessToken,
  profileEnabled,
  profileLevel,
}: UseReasoningModeOptions) {
  const [enabled, setEnabledState] = useState(false)
  const [level, setLevelState] = useState<ReasoningLevel>('auto')
  const [hydrated, setHydrated] = useState(false)

  useEffect(() => {
    const stored = readStored()
    if (profileEnabled !== undefined) {
      setEnabledState(profileEnabled)
    } else {
      setEnabledState(stored.enabled)
    }
    if (profileLevel) {
      setLevelState(profileLevel)
    } else {
      setLevelState(stored.level)
    }
    setHydrated(true)
  }, [profileEnabled, profileLevel])

  const persist = useCallback(
    async (next: StoredReasoning) => {
      writeStored(next)
      try {
        const token = await getAccessToken()
        if (!token) return
        await patchUserProfile(token, {
          reasoning_enabled: next.enabled,
          reasoning_level: next.level,
        })
      } catch {
        // best-effort: cache local ya aplicado
      }
    },
    [getAccessToken],
  )

  const setEnabled = useCallback(
    (value: boolean) => {
      setEnabledState(value)
      const next = { enabled: value, level }
      writeStored(next)
      void persist(next)
    },
    [level, persist],
  )

  const setLevel = useCallback(
    (value: ReasoningLevel) => {
      setLevelState(value)
      const next = { enabled, level: value }
      writeStored(next)
      void persist(next)
    },
    [enabled, persist],
  )

  return {
    enabled,
    level,
    setEnabled,
    setLevel,
    hydrated,
  }
}
