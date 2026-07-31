const CACHE_PREFIX = 'dot-offline-'
const CACHE_TTL = 24 * 60 * 60 * 1000 // 24h

interface CacheEntry<T = unknown> {
  data: T
  timestamp: number
}

export async function cacheResponse<T = unknown>(key: string, data: T): Promise<void> {
  try {
    const entry: CacheEntry = { data, timestamp: Date.now() }
    localStorage.setItem(CACHE_PREFIX + key, JSON.stringify(entry))
  } catch {
    // localStorage lleno, ignorar
  }
}

export async function getCachedResponse<T = unknown>(key: string): Promise<T | null> {
  try {
    const raw = localStorage.getItem(CACHE_PREFIX + key)
    if (!raw) return null
    const entry: CacheEntry<T> = JSON.parse(raw)
    if (Date.now() - entry.timestamp > CACHE_TTL) {
      localStorage.removeItem(CACHE_PREFIX + key)
      return null
    }
    return entry.data
  } catch {
    return null
  }
}

export async function clearOfflineCache(): Promise<void> {
  const keys = Object.keys(localStorage).filter(k => k.startsWith(CACHE_PREFIX))
  keys.forEach(k => localStorage.removeItem(k))
}
