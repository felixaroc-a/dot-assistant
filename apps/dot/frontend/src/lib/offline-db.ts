/**
 * Almacenamiento offline basado en IndexedDB.
 *
 * Reemplaza el cache en localStorage (limite ~5MB) con IndexedDB (limite ~50MB+).
 * Almacena:
 * - Respuestas API cacheadas con TTL
 * - Mensajes de chat pendientes de envio
 * - Perfil de usuario para visualizacion offline
 */
import { openDB, type IDBPDatabase } from 'idb'

const DB_NAME = 'dot-offline'
const DB_VERSION = 1

interface ApiCacheEntry {
  key: string
  data: unknown
  cachedAt: number
  ttlMs: number
}

interface PendingMessage {
  id: string
  text: string
  createdAt: string
  retryCount: number
  lastError?: string
}

interface UserProfileEntry {
  key: string
  data: unknown
}

let dbPromise: Promise<IDBPDatabase> | null = null

function getDb(): Promise<IDBPDatabase> {
  if (!dbPromise) {
    dbPromise = openDB(DB_NAME, DB_VERSION, {
      upgrade(db) {
        if (!db.objectStoreNames.contains('api-cache')) {
          const store = db.createObjectStore('api-cache', { keyPath: 'key' })
          store.createIndex('expiry', ['cachedAt', 'ttlMs'])
        }
        if (!db.objectStoreNames.contains('pending-messages')) {
          db.createObjectStore('pending-messages', { keyPath: 'id' })
        }
        if (!db.objectStoreNames.contains('user-profile')) {
          db.createObjectStore('user-profile', { keyPath: 'key' })
        }
      },
    })
  }
  return dbPromise
}

// ─── API Cache ─────────────────────────────────────────

const DEFAULT_TTL = 24 * 60 * 60 * 1000 // 24 horas

export async function cacheApiData<T>(key: string, data: T, ttlMs = DEFAULT_TTL): Promise<void> {
  try {
    const db = await getDb()
    await db.put('api-cache', { key, data, cachedAt: Date.now(), ttlMs })
  } catch {
    console.warn('[OfflineDB] Error al cachear:', key)
  }
}

export async function getCachedApiData<T>(key: string): Promise<T | null> {
  try {
    const db = await getDb()
    const entry = await db.get('api-cache', key) as ApiCacheEntry | undefined
    if (!entry) return null

    if (Date.now() - entry.cachedAt > entry.ttlMs) {
      await db.delete('api-cache', key)
      return null
    }
    return entry.data as T
  } catch {
    return null
  }
}

export async function clearApiCache(): Promise<void> {
  try {
    const db = await getDb()
    await db.clear('api-cache')
  } catch {
    console.warn('[OfflineDB] Error al limpiar cache')
  }
}

// ─── Pending Messages (cola de mensajes offline) ───────

export async function addPendingMessage(text: string): Promise<string> {
  const id = crypto.randomUUID()
  const msg: PendingMessage = {
    id,
    text,
    createdAt: new Date().toISOString(),
    retryCount: 0,
  }
  try {
    const db = await getDb()
    await db.add('pending-messages', msg)
  } catch {
    console.warn('[OfflineDB] Error al guardar mensaje pendiente')
  }
  return id
}

export async function getPendingMessages(): Promise<PendingMessage[]> {
  try {
    const db = await getDb()
    return await db.getAll('pending-messages')
  } catch {
    return []
  }
}

export async function removePendingMessage(id: string): Promise<void> {
  try {
    const db = await getDb()
    await db.delete('pending-messages', id)
  } catch {
    console.warn('[OfflineDB] Error al eliminar mensaje pendiente')
  }
}

export async function incrementRetryCount(id: string, error?: string): Promise<void> {
  try {
    const db = await getDb()
    const msg = await db.get('pending-messages', id) as PendingMessage | undefined
    if (msg) {
      msg.retryCount++
      msg.lastError = error
      await db.put('pending-messages', msg)
    }
  } catch {
    console.warn('[OfflineDB] Error al incrementar retry')
  }
}

export async function countPendingMessages(): Promise<number> {
  try {
    const db = await getDb()
    return await db.count('pending-messages')
  } catch {
    return 0
  }
}

// ─── User Profile (lectura offline) ────────────────────

export async function saveProfileOffline(key: string, data: unknown): Promise<void> {
  try {
    const db = await getDb()
    await db.put('user-profile', { key, data })
  } catch {
    console.warn('[OfflineDB] Error al guardar perfil offline')
  }
}

export async function getProfileOffline<T>(key: string): Promise<T | null> {
  try {
    const db = await getDb()
    const entry = await db.get('user-profile', key) as UserProfileEntry | undefined
    if (!entry) return null
    return entry.data as T
  } catch {
    return null
  }
}
