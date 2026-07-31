import { useCallback, useEffect, useState } from 'react'

const STORAGE_KEY = 'dot-speaks-enabled'

function readStored(): boolean {
  try {
    return localStorage.getItem(STORAGE_KEY) === '1'
  } catch {
    return false
  }
}

function writeStored(enabled: boolean) {
  try {
    localStorage.setItem(STORAGE_KEY, enabled ? '1' : '0')
  } catch {
    // localStorage no disponible
  }
}

export function useDotSpeaks() {
  const [enabled, setEnabledState] = useState(false)
  const [hydrated, setHydrated] = useState(false)

  useEffect(() => {
    setEnabledState(readStored())
    setHydrated(true)
  }, [])

  const setEnabled = useCallback((value: boolean) => {
    setEnabledState(value)
    writeStored(value)
  }, [])

  const toggle = useCallback(() => {
    setEnabledState((prev) => {
      const next = !prev
      writeStored(next)
      return next
    })
  }, [])

  return { enabled, setEnabled, toggle, hydrated }
}
