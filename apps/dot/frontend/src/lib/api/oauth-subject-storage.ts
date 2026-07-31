/** Identificador persistente para OAuth (cifrado OS en Electron). */

const LEGACY_KEY = 'dot_google_oauth_subject_v1'

function hasDesktopOAuth(): boolean {
  return typeof window !== 'undefined' && !!window.desktop?.oauthSubject
}

export async function getOrCreateLocalGoogleOAuthSubject(): Promise<string> {
  if (hasDesktopOAuth()) {
    const existing = (await window.desktop!.oauthSubject!.load())?.trim()
    if (existing) return existing
    const id =
      typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function'
        ? crypto.randomUUID()
        : `anon-${Math.random().toString(36).slice(2)}-${Date.now()}`
    await window.desktop!.oauthSubject!.save(id)
    return id
  }

  try {
    const legacy = localStorage.getItem(LEGACY_KEY)?.trim()
    if (legacy) {
      sessionStorage.setItem(LEGACY_KEY, legacy)
      localStorage.removeItem(LEGACY_KEY)
      return legacy
    }
    const existing = sessionStorage.getItem(LEGACY_KEY)?.trim()
    if (existing) return existing
    const id =
      typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function'
        ? crypto.randomUUID()
        : `anon-${Math.random().toString(36).slice(2)}-${Date.now()}`
    sessionStorage.setItem(LEGACY_KEY, id)
    return id
  } catch {
    return `anon-session-${Math.random().toString(36).slice(2)}`
  }
}
