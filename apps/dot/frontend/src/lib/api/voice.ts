import { ApiError } from './http'
import { getApiBaseUrl } from './base-url'

function formatErrorDetail(data: unknown): string {
  if (typeof data === 'object' && data !== null && 'detail' in data) {
    const detail = (data as { detail: unknown }).detail
    if (typeof detail === 'string') return detail
    if (Array.isArray(detail)) {
      return detail
        .map((item) =>
          typeof item === 'object' && item !== null && 'msg' in item
            ? String(item.msg)
            : JSON.stringify(item),
        )
        .join('; ')
    }
    if (detail != null) return JSON.stringify(detail)
  }
  return ''
}

export type ProviderInfo = {
  name: string
  available: boolean
  voices?: string[]
}

export type VoiceStatus = {
  ok: boolean
  stt: 'ready' | 'needs_api_key' | 'needs_gemini_api_key'
  tts: 'ready' | 'needs_api_key' | 'needs_gemini_api_key'
  providers?: {
    stt: ProviderInfo[]
    tts: ProviderInfo[]
  }
  detail: string | null
}

export type VoiceTranscribeResponse = {
  text: string
  ok: boolean
  provider?: string
}

export type VoiceSynthesizeResponse = {
  audio_base64: string
  format: string
  provider?: string
}

export type TalkTurnResponse = {
  state: string
  transcript: string
  response_text: string
  audio_base64: string
  audio_format: string
  tts_provider: string
  history_length: number
}

export type TalkStatus = {
  active: boolean
  state: string
  transcript: string
  history_length: number
}

export async function getVoiceStatus(token: string | null): Promise<VoiceStatus> {
  const url = `${getApiBaseUrl()}/v1/voice/status`
  const headers = new Headers()
  if (token) headers.set('Authorization', `Bearer ${token}`)

  const res = await fetch(url, { method: 'GET', headers })
  const raw = await res.text()
  let data: unknown = raw
  if (raw) {
    try { data = JSON.parse(raw) } catch { data = raw }
  }

  if (!res.ok) {
    throw new ApiError(
      formatErrorDetail(data) || res.statusText || `HTTP ${res.status}`,
      res.status,
      data,
    )
  }

  return data as VoiceStatus
}

export async function synthesizeSpeech(
  text: string,
  token: string | null,
  voice = 'auto',
  provider = 'auto',
): Promise<VoiceSynthesizeResponse> {
  const url = `${getApiBaseUrl()}/v1/voice/synthesize`
  const headers = new Headers()
  headers.set('Content-Type', 'application/json')
  if (token) headers.set('Authorization', `Bearer ${token}`)

  const res = await fetch(url, {
    method: 'POST',
    headers,
    body: JSON.stringify({ text, voice, provider }),
  })

  const raw = await res.text()
  let data: unknown = raw
  if (raw) {
    try { data = JSON.parse(raw) } catch { data = raw }
  }

  if (!res.ok) {
    throw new ApiError(
      formatErrorDetail(data) || res.statusText || `HTTP ${res.status}`,
      res.status,
      data,
    )
  }

  return data as VoiceSynthesizeResponse
}

export async function transcribeAudio(
  blob: Blob,
  token: string | null,
  language = 'es',
  provider = 'auto',
): Promise<VoiceTranscribeResponse> {
  const formData = new FormData()
  const ext = blob.type.includes('ogg') ? 'ogg' : blob.type.includes('mp4') ? 'm4a' : 'webm'
  formData.append('file', blob, `voice.${ext}`)
  formData.append('language', language)
  formData.append('provider', provider)

  const url = `${getApiBaseUrl()}/v1/voice/transcribe`
  const headers = new Headers()
  if (token) headers.set('Authorization', `Bearer ${token}`)

  const res = await fetch(url, { method: 'POST', headers, body: formData })
  const raw = await res.text()
  let data: unknown = raw
  if (raw) {
    try {
      data = JSON.parse(raw)
    } catch {
      data = raw
    }
  }

  if (!res.ok) {
    throw new ApiError(
      formatErrorDetail(data) || res.statusText || `HTTP ${res.status}`,
      res.status,
      data,
    )
  }

  if (typeof data === 'object' && data !== null && 'text' in data) {
    const text = String((data as { text: unknown }).text ?? '')
    return { text, ok: Boolean(text.trim()), provider: (data as { provider?: string }).provider }
  }
  return { text: '', ok: false }
}

export type VoiceCapability = 'stt' | 'tts'

const SERVICE_UNAVAILABLE_PATTERNS =
  /api_key|needs_api_key|needs_gemini|no configurad|proveedor|ning[uú]n proveedor|servicio de voz|la voz no est[aá]|transcripci[oó]n por voz no est[aá]|s[ií]ntesis|sintesis|edge tts|elevenlabs|whisper|gemini|openai/i

/** True si el mensaje traducido corresponde a servicio de voz no disponible (no permisos de mic). */
export function isVoiceServiceUnavailableMessage(
  message: string,
  t: (key: string) => string,
): boolean {
  const trimmed = (message || '').trim()
  if (!trimmed) return false
  return (
    trimmed === t('voice.needs_key')
    || trimmed === t('voice.speak_unavailable')
    || trimmed === t('voice.talk_unavailable')
  )
}

/** Etiqueta y ayuda legibles para Configuración según estado del backend. */
export function describeVoiceCapability(
  status: VoiceStatus['stt'] | VoiceStatus['tts'],
  capability: VoiceCapability,
  t: (key: string) => string,
): { ready: boolean; label: string; help: string } {
  const ready = status === 'ready'
  if (capability === 'stt') {
    return {
      ready,
      label: ready ? t('voice.settings_stt_ready') : t('voice.settings_stt_unavailable'),
      help: ready ? t('voice.settings_stt_help') : t('voice.needs_key'),
    }
  }
  return {
    ready,
    label: ready ? t('voice.settings_tts_ready') : t('voice.settings_tts_unavailable'),
    help: ready ? t('voice.settings_speak_help') : t('voice.speak_unavailable'),
  }
}

/** Convierte errores técnicos del backend en mensajes humanos para la UI. */
export function humanizeVoiceError(raw: string, t: (key: string) => string): string {
  const msg = (raw || '').trim()
  const lower = msg.toLowerCase()

  if (
    !msg
    || SERVICE_UNAVAILABLE_PATTERNS.test(msg)
    || lower.includes('503')
    || lower.includes('502')
  ) {
    return t('voice.needs_key')
  }
  if (lower.includes('cuota') || lower.includes('429') || lower.includes('quota') || lower.includes('límite de transcripción')) {
    return t('voice.quota')
  }
  if (
    lower.includes('network')
    || lower.includes('fetch')
    || lower.includes('conectar')
    || lower.includes('internet')
  ) {
    return t('voice.network')
  }
  if (lower.includes('demasiado corto') || lower.includes('sin audio') || lower.includes('empty')) {
    return t('voice.empty')
  }
  if (
    /gemini|openai|whisper|edge-tts|elevenlabs|httpx|fastapi|pydantic/i.test(msg)
    || /\bhttp\s*\d{3}\b/i.test(msg)
    || /[A-Z_]{4,}/.test(msg)
  ) {
    return t('voice.generic_error')
  }
  return msg.length <= 180 ? msg : t('voice.generic_error')
}

/** Convierte errores técnicos de TTS en mensajes humanos para la UI. */
export function humanizeTtsError(raw: string, t: (key: string) => string): string {
  const msg = (raw || '').trim()
  const lower = msg.toLowerCase()

  if (
    !msg
    || SERVICE_UNAVAILABLE_PATTERNS.test(msg)
    || lower.includes('503')
    || lower.includes('502')
  ) {
    return t('voice.speak_unavailable')
  }
  if (lower.includes('cuota') || lower.includes('429') || lower.includes('quota') || lower.includes('límite')) {
    return t('voice.quota')
  }
  if (
    lower.includes('network')
    || lower.includes('fetch')
    || lower.includes('conectar')
    || lower.includes('internet')
  ) {
    return t('voice.network')
  }
  if (
    /gemini|openai|whisper|edge-tts|elevenlabs|httpx|fastapi|pydantic/i.test(msg)
    || /\bhttp\s*\d{3}\b/i.test(msg)
    || /[A-Z_]{4,}/.test(msg)
  ) {
    return t('voice.speak_error')
  }
  return msg.length <= 180 ? msg : t('voice.speak_error')
}

// ─── Talk Mode API ─────────────────────────────────────────────────────

export async function startTalkSession(token: string | null): Promise<{ state: string }> {
  const url = `${getApiBaseUrl()}/v1/voice/talk/start`
  const headers = new Headers()
  if (token) headers.set('Authorization', `Bearer ${token}`)

  const res = await fetch(url, { method: 'POST', headers })
  const raw = await res.text()
  let data: unknown = raw
  if (raw) {
    try { data = JSON.parse(raw) } catch { data = raw }
  }

  if (!res.ok) {
    throw new ApiError(formatErrorDetail(data) || `HTTP ${res.status}`, res.status, data)
  }

  return data as { state: string }
}

export async function sendTalkTurn(
  blob: Blob,
  token: string | null,
  options: {
    language?: string
    stt_provider?: string
    tts_provider?: string
    tts_voice?: string
    interruption?: boolean
  } = {},
): Promise<TalkTurnResponse> {
  const formData = new FormData()
  const ext = blob.type.includes('ogg') ? 'ogg' : blob.type.includes('mp4') ? 'm4a' : 'webm'
  formData.append('file', blob, `voice.${ext}`)
  formData.append('options_json', JSON.stringify(options))

  const url = `${getApiBaseUrl()}/v1/voice/talk/turn`
  const headers = new Headers()
  if (token) headers.set('Authorization', `Bearer ${token}`)

  const res = await fetch(url, { method: 'POST', headers, body: formData })
  const raw = await res.text()
  let data: unknown = raw
  if (raw) {
    try { data = JSON.parse(raw) } catch { data = raw }
  }

  if (!res.ok) {
    throw new ApiError(formatErrorDetail(data) || `HTTP ${res.status}`, res.status, data)
  }

  return data as TalkTurnResponse
}

export async function getTalkStatus(token: string | null): Promise<TalkStatus> {
  const url = `${getApiBaseUrl()}/v1/voice/talk/status`
  const headers = new Headers()
  if (token) headers.set('Authorization', `Bearer ${token}`)

  const res = await fetch(url, { method: 'GET', headers })
  const raw = await res.text()
  let data: unknown = raw
  if (raw) {
    try { data = JSON.parse(raw) } catch { data = raw }
  }

  if (!res.ok) {
    throw new ApiError(formatErrorDetail(data) || `HTTP ${res.status}`, res.status, data)
  }

  return data as TalkStatus
}

export async function stopTalkSession(
  token: string | null,
): Promise<{ stopped: boolean; total_turns?: number }> {
  const url = `${getApiBaseUrl()}/v1/voice/talk/stop`
  const headers = new Headers()
  if (token) headers.set('Authorization', `Bearer ${token}`)

  const res = await fetch(url, { method: 'POST', headers })
  const raw = await res.text()
  let data: unknown = raw
  if (raw) {
    try { data = JSON.parse(raw) } catch { data = raw }
  }

  if (!res.ok) {
    throw new ApiError(formatErrorDetail(data) || `HTTP ${res.status}`, res.status, data)
  }

  return data as { stopped: boolean; total_turns?: number }
}
