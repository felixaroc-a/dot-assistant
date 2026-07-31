import { ApiError } from '@/lib/api/http'
import { GOOGLE_DRIVE_SCOPE_RECONNECT_MESSAGE } from '@/lib/api/google-oauth'
import { USAGE_LIMIT_BLOCKED_MESSAGE } from '@/lib/usage-messages'

const GENERIC = 'Algo salió mal. Intenta de nuevo en unos momentos.'

export const IMAGE_GENERATION_UNAVAILABLE_MESSAGE =
  'La generación de imágenes no está disponible ahora.'

const TECHNICAL_PATTERNS: RegExp[] = [
  /open\s*claw/i,
  /openclaw/i,
  /baileys/i,
  /\bnpm\b/i,
  /\bdocker\b/i,
  /sandbox\s*deny/i,
  /econnrefused/i,
  /econnreset/i,
  /enotfound/i,
  /traceback/i,
  /stack\s*trace/i,
  /\bat\s+[\w./\\]+:\d+/i,
  /node_modules/i,
  /\bhttp\s*\d{3}\b/i,
  /^error\s*\d{3}:/i,
  /\b(typeerror|referenceerror|syntaxerror|aborterror)\b/i,
  /bridge_unreachable/i,
  /bridge_secret/i,
  /bridge_unauthorized/i,
  /bridge_send_failed/i,
  /invalid_payload/i,
  /no_vault_found/i,
  /read_error/i,
  /failed to fetch/i,
  /networkerror/i,
  /load failed/i,
  /network request failed/i,
  /\bregex\b/i,
  /whitespace/i,
  /pydantic/i,
  /fastapi/i,
  /sqlalchemy/i,
  /httpx/i,
  /uncaught/i,
]

const ERROR_MAP: Record<string, string> = {
  'failed to fetch': 'Parece que no hay conexión a internet. DOT necesita internet para funcionar.',
  networkerror: 'Parece que no hay conexión a internet. DOT necesita internet para funcionar.',
  'load failed': 'Parece que no hay conexión a internet. DOT necesita internet para funcionar.',
  'connection refused': 'Parece que no hay conexión a internet. DOT necesita internet para funcionar.',
  econnrefused: 'Parece que no hay conexión a internet. DOT necesita internet para funcionar.',
  timeout: 'DOT está teniendo problemas para pensar. Intenta de nuevo en un momento.',
  'rate limit': 'Has enviado muchos mensajes. Espera unos segundos e inténtalo de nuevo.',
  '429': 'Demasiadas solicitudes. Espera un momento.',
  '402': USAGE_LIMIT_BLOCKED_MESSAGE,
  '403': 'Tu sesión expiró. Vuelve a iniciar sesión.',
  '401': 'No tienes acceso. Inicia sesión de nuevo.',
  'token expirado': 'Tu sesión expiró. Vuelve a iniciar sesión.',
  'invalid token': 'Tu sesión no es válida. Vuelve a iniciar sesión.',
  subscription_expired: 'Tu suscripción venció. Renueva en la tienda más cercana.',
  bridge_unreachable:
    'WhatsApp no está conectado. Ve a Configuración > WhatsApp para escanear el código QR.',
  bridge_secret_not_configured:
    'WhatsApp no está conectado. Ve a Configuración > WhatsApp para escanear el código QR.',
  bridge_unauthorized: 'WhatsApp no está conectado. Ve a Configuración > WhatsApp para escanear el código QR.',
  browser_permission_denied:
    'No tengo permiso para abrir páginas web. Actívalo en Configuración → Privacidad → "DOT puede usar webs".',
  browser_permission_required:
    'Para entrar en páginas web necesito tu permiso. Ve a Configuración → Privacidad y activa "DOT puede usar webs".',
  browser_web_disabled:
    'Para que DOT entre en páginas web, actívalo en Configuración → Privacidad → "DOT puede usar webs".',
  browser_timeout: 'La página tardó demasiado en cargar. Intenta con otra URL o más tarde.',
  browser_not_navigated: 'Primero necesito abrir la página web. Indica la URL o pide que entre al sitio.',
  host_blocked: 'Por seguridad no puedo abrir esa dirección.',
  invalid_url: 'La dirección web no es válida. Debe empezar con http:// o https://.',
  gmail_not_connected: 'Google no está conectado. Ve a Configuración > Google para vincular tu cuenta.',
  calendar_not_connected: 'Google no está conectado. Ve a Configuración > Google para vincular tu cuenta.',
  drive_scope_missing: GOOGLE_DRIVE_SCOPE_RECONNECT_MESSAGE,
  'permiso de drive': GOOGLE_DRIVE_SCOPE_RECONNECT_MESSAGE,
  'insufficient authentication scopes': GOOGLE_DRIVE_SCOPE_RECONNECT_MESSAGE,
  'whatsapp no esta vinculado': 'WhatsApp no está conectado. Ve a Configuración > WhatsApp para escanear el código QR.',
  'whatsapp no está vinculado': 'WhatsApp no está conectado. Ve a Configuración > WhatsApp para escanear el código QR.',
  'ya hay un proceso de vinculación': 'Ya hay una vinculación en curso. Espera unos segundos o reinicia la app.',
  multiple_usb: 'Hay varios USB conectados. Deja solo la llave DOT y reintenta.',
  no_vault_found: 'USB detectado pero no está preparado para DOT.',
  local_session_missing: 'La sesión de WhatsApp expiró. Ve a Configuración > WhatsApp para escanear el código QR.',
  credenciales_invalidas: 'Cédula, clave o llave DOT incorrectos.',
  'no response body': 'No hubo respuesta del servidor. Intenta de nuevo.',
  'error de conexión': 'Parece que no hay conexión a internet. DOT necesita internet para funcionar.',
  'error de red': 'Parece que no hay conexión a internet. DOT necesita internet para funcionar.',
  deepseek: 'DOT está teniendo problemas para pensar. Intenta de nuevo en un momento.',
  'model overloaded': 'DOT está teniendo problemas para pensar. Intenta de nuevo en un momento.',
  'service unavailable': 'DOT está teniendo problemas para pensar. Intenta de nuevo en un momento.',
  'internal server error': 'DOT está teniendo problemas para pensar. Intenta de nuevo en un momento.',
  'bad gateway': 'DOT está teniendo problemas para pensar. Intenta de nuevo en un momento.',
  'gateway timeout': 'DOT está teniendo problemas para pensar. Intenta de nuevo en un momento.',
  'insufficient balance': USAGE_LIMIT_BLOCKED_MESSAGE,
  'quota exceeded': USAGE_LIMIT_BLOCKED_MESSAGE,
  'usage limit': USAGE_LIMIT_BLOCKED_MESSAGE,
  ai_usage_limit_exceeded: USAGE_LIMIT_BLOCKED_MESSAGE,
  image_generation_unavailable: IMAGE_GENERATION_UNAVAILABLE_MESSAGE,
}

export const NETWORK_ERROR_MESSAGE =
  'No hay conexión a internet. Verifica tu conexión e intenta de nuevo.'

export const LOCAL_BACKEND_UNREACHABLE_MESSAGE =
  'No se pudo conectar con el servicio. Cierra DOT por completo, ábrelo de nuevo e intenta otra vez.'

export function isTechnicalMessage(message: string): boolean {
  const msg = message.trim()
  if (!msg) return false
  return TECHNICAL_PATTERNS.some((pattern) => pattern.test(msg))
}

function looksLikeFriendlySpanish(message: string): boolean {
  if (message.length > 240) return false
  if (isTechnicalMessage(message)) return false
  if (/[áéíóúñ¿¡]/i.test(message)) return true
  return /^(no se pudo|no pude|revisa|intenta|escanea|conecta|vuelve|espera|abre|cierra)/i.test(
    message,
  )
}

export function translateErrorMessage(raw: string, fallback = GENERIC): string {
  const msg = raw.trim()
  if (!msg) return fallback

  const lower = msg.toLowerCase()
  for (const [key, translation] of Object.entries(ERROR_MAP)) {
    if (lower.includes(key.toLowerCase())) {
      return translation
    }
  }

  if (looksLikeFriendlySpanish(msg)) {
    return msg
  }

  if (isTechnicalMessage(msg)) {
    return fallback
  }

  if (/^[a-z0-9_:\s.\-/\\()[\]{}'"]+$/i.test(msg) && !/[áéíóúñ]/i.test(msg)) {
    return fallback
  }

  return looksLikeFriendlySpanish(msg) ? msg : fallback
}

export function translateApiError(error: ApiError, fallback = GENERIC): string {
  if (error.status === 429) {
    const wait = error.retryAfterSeconds
    if (wait) {
      return `Demasiadas solicitudes. Espera ${wait} segundos e inténtalo de nuevo.`
    }
    return 'Demasiadas solicitudes. Espera un momento.'
  }
  if (error.status === 402) {
    return USAGE_LIMIT_BLOCKED_MESSAGE
  }
  if (error.status === 401 || error.status === 403) {
    return translateErrorMessage(error.message, 'Tu sesión expiró. Vuelve a iniciar sesión.')
  }
  if (error.status === 503) {
    const translated = translateErrorMessage(error.message, IMAGE_GENERATION_UNAVAILABLE_MESSAGE)
    if (
      translated === IMAGE_GENERATION_UNAVAILABLE_MESSAGE ||
      error.message.toLowerCase().includes('image_generation_unavailable')
    ) {
      return IMAGE_GENERATION_UNAVAILABLE_MESSAGE
    }
    return 'DOT está teniendo problemas para pensar. Intenta de nuevo en un momento.'
  }
  if (error.status >= 500) {
    return 'DOT está teniendo problemas para pensar. Intenta de nuevo en un momento.'
  }
  return translateErrorMessage(error.message, fallback)
}

export function translateError(error: unknown, fallback = GENERIC): string {
  if (error instanceof ApiError) {
    return translateApiError(error, fallback)
  }
  if (error instanceof Error) {
    return translateErrorMessage(error.message, fallback)
  }
  if (typeof error === 'string') {
    return translateErrorMessage(error, fallback)
  }
  return fallback
}

export function sanitizeWhatsAppUserError(message: string): string {
  const normalized = message
    .replace(/open\s*claw/gi, 'vinculación')
    .replace(/openclaw/gi, 'vinculación')
    .replace(/baileys/gi, 'WhatsApp')
    .replace(/\bnpm\b/gi, 'instalación')
    .replace(/\bgateway\b/gi, 'conexión')
    .replace(/node_modules/gi, 'módulo interno')

  return translateErrorMessage(
    normalized,
    'No pude conectar WhatsApp. Escanea el código de nuevo.',
  )
}
