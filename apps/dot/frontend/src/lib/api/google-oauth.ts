import { apiFetchJson } from '@/lib/api/http'
import { getOrCreateLocalGoogleOAuthSubject } from '@/lib/api/oauth-subject-storage'

/** Ruta legible para reconectar Google (drawer de integraciones). */
export const GOOGLE_INTEGRATIONS_PATH = 'Configuración → Google'

/** Mensaje one-shot cuando falta scope drive.readonly. */
export const GOOGLE_DRIVE_SCOPE_RECONNECT_MESSAGE =
  'Ve a Configuración → Google, desvincula y vuelve a conectar.'

export type GoogleOAuthStartResponse = {
  authorization_url: string
  state: string
}

export type GoogleOAuthStatusResponse = {
  configured: boolean
  integrations: string[]
  expires_at: string | null
  scopes_ok: boolean
}

/**
 * Si hay JWT de producto, va en Authorization (recomendado en producción).
 * Sin JWT: el backend solo acepta cuerpo con `dev_user_id` cuando
 * ALLOW_OAUTH_DEV_WITHOUT_FIREBASE_AUTH=1 (`getOrCreateLocalGoogleOAuthSubject`).
 */
export async function requestGoogleOAuthStart(params: {
  bearerAccessToken: string | null
  devUserIdWhenNoJwt?: string
  /** Solo scopes de las integraciones elegidas: gmail | google-calendar */
  integrations?: readonly string[]
}): Promise<GoogleOAuthStartResponse> {
  const bearer =
    typeof params.bearerAccessToken === 'string' ? params.bearerAccessToken.trim() || null : null
  const body: { dev_user_id?: string; integrations?: string[] } = {}
  if (params.integrations?.length) {
    body.integrations = [...params.integrations]
  }
  if (!bearer && params.devUserIdWhenNoJwt?.trim()) {
    body.dev_user_id = params.devUserIdWhenNoJwt.trim()
  }
  return apiFetchJson<GoogleOAuthStartResponse>(
    '/oauth/google/start',
    { method: 'POST', body: JSON.stringify(body) },
    bearer,
  )
}

/** Consulta el estado de la vinculación OAuth Google para el usuario autenticado. */
export async function getGoogleOAuthStatus(
  bearerAccessToken: string | null,
  devUserId?: string | null,
): Promise<GoogleOAuthStatusResponse> {
  const bearer =
    typeof bearerAccessToken === 'string' ? bearerAccessToken.trim() || null : null
  const devId = devUserId?.trim() || null
  const query = !bearer && devId ? `?dev_user_id=${encodeURIComponent(devId)}` : ''
  return apiFetchJson<GoogleOAuthStatusResponse>(
    `/oauth/google/status${query}`,
    { method: 'GET' },
    bearer,
  )
}

/**
 * Resuelve el estado OAuth usando JWT cuando existe; en dev, cae al subject local
 * (tokens guardados sin JWT durante pruebas de onboarding).
 */
export async function resolveGoogleOAuthStatus(
  getAccessToken: () => Promise<string | null>,
): Promise<GoogleOAuthStatusResponse> {
  const token = await getAccessToken()
  const bearer = token?.trim() || null

  if (bearer) {
    try {
      const status = await getGoogleOAuthStatus(bearer)
      if (status.configured) return status
    } catch {
      // Continuar con fallback dev si aplica
    }
  }

  if (!import.meta.env.PROD) {
    const devId = await getOrCreateLocalGoogleOAuthSubject()
    return getGoogleOAuthStatus(null, devId)
  }

  if (bearer) {
    return getGoogleOAuthStatus(bearer)
  }

  return {
    configured: false,
    integrations: [],
    expires_at: null,
    scopes_ok: false,
  }
}

export type GoogleOAuthRevokeResponse = {
  ok: boolean
  message: string
  revoked_remotely?: boolean
}

/** Revoca la vinculación OAuth Google del usuario autenticado. */
export async function revokeGoogleOAuth(
  getAccessToken: () => Promise<string | null>,
): Promise<GoogleOAuthRevokeResponse> {
  const token = await getAccessToken()
  return apiFetchJson<GoogleOAuthRevokeResponse>(
    '/oauth/google/revoke',
    { method: 'POST' },
    token,
  )
}
