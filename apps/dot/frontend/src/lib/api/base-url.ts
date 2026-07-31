/**
 * URL base de la API del backend DOT.
 * Se configura via VITE_API_BASE_URL en .env (ej: http://127.0.0.1:8000)
 * En producción debe apuntar a la URL real del servidor.
 * NO tiene fallback silencioso — si no está configurada, lanza error.
 */
export function getApiBaseUrl(): string {
  const raw = import.meta.env.VITE_API_BASE_URL?.trim()
  if (!raw) {
    throw new Error(
      '[DOT] VITE_API_BASE_URL no está configurada. ' +
      'Establece esta variable de entorno en tu archivo .env con la URL del servidor backend.'
    )
  }
  const base = raw.replace(/\/$/, '')
  if (import.meta.env.PROD && base.startsWith('http://') && !base.includes('127.0.0.1') && !base.includes('localhost')) {
    console.warn('[DOT] API en HTTP no cifrado en build de producción; use HTTPS.')
  }
  return base
}
