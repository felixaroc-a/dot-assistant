/**
 * Persistencia de sesión: Electron safeStorage (preferido) o sessionStorage (web dev).
 */
const STORAGE_KEY = 'dot_session_v1'

function hasDesktopSecure(): boolean {
  return typeof window !== 'undefined' && !!window.desktop?.secureSession
}

export async function loadSecureJson(): Promise<string | null> {
  if (hasDesktopSecure()) {
    return window.desktop!.secureSession!.load()
  }
  try {
    return sessionStorage.getItem(STORAGE_KEY)
  } catch {
    return null
  }
}

export async function saveSecureJson(json: string): Promise<void> {
  if (hasDesktopSecure()) {
    const result = await window.desktop!.secureSession!.save(json)
    if (!result?.ok) {
      throw new Error(result?.error || 'No se pudo guardar la sesión de forma segura.')
    }
    return
  }
  try {
    sessionStorage.setItem(STORAGE_KEY, json)
  } catch {
    // ignore
  }
}

export async function clearSecureJson(): Promise<void> {
  if (hasDesktopSecure()) {
    await window.desktop!.secureSession!.clear()
    return
  }
  try {
    sessionStorage.removeItem(STORAGE_KEY)
  } catch {
    // ignore
  }
}

/** Migra sesión legacy en localStorage a almacenamiento seguro. */
export async function migrateLegacyLocalStorage(): Promise<void> {
  try {
    const legacy = localStorage.getItem(STORAGE_KEY)
    if (!legacy) return
    const current = await loadSecureJson()
    if (!current) {
      await saveSecureJson(legacy)
    }
    localStorage.removeItem(STORAGE_KEY)
  } catch {
    // ignore
  }
}
