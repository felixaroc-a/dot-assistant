import { GOOGLE_DRIVE_SCOPE_RECONNECT_MESSAGE } from '@/lib/api/google-oauth'

/** Detecta respuestas del agente que piden reconectar Google por falta de scope Drive. */
export function needsGoogleDriveReconnectNudge(text: string): boolean {
  const normalized = text.trim().toLowerCase()
  if (!normalized) return false
  const needle = GOOGLE_DRIVE_SCOPE_RECONNECT_MESSAGE.toLowerCase()
  return normalized.includes(needle) || normalized.includes('permiso de drive')
}
