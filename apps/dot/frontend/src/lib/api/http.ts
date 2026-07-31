import { getApiBaseUrl } from './base-url'
import { cacheApiData, getCachedApiData } from '../offline-db'

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
    readonly body?: unknown,
    readonly retryAfterSeconds?: number,
  ) {
    super(message)
    this.name = 'ApiError'
  }
}

function parseRetryAfterSeconds(response: Response): number | undefined {
  const raw = response.headers.get('Retry-After')?.trim()
  if (!raw) return undefined
  const seconds = Number.parseInt(raw, 10)
  if (Number.isFinite(seconds) && seconds > 0) return seconds
  const retryAt = Date.parse(raw)
  if (!Number.isFinite(retryAt)) return undefined
  const delta = Math.ceil((retryAt - Date.now()) / 1000)
  return delta > 0 ? delta : undefined
}

function formatFastApiDetail(data: unknown): string {
  if (typeof data !== 'object' || data === null || !('detail' in data)) {
    return ''
  }
  const d = (data as { detail: unknown }).detail
  if (typeof d === 'string') return d
  if (typeof d === 'object' && d !== null) {
    if ('message' in d && typeof (d as { message: unknown }).message === 'string') {
      return String((d as { message: string }).message)
    }
    if ('code' in d && typeof (d as { code: unknown }).code === 'string') {
      const code = String((d as { code: string }).code)
      if ('message' in d && typeof (d as { message: unknown }).message === 'string') {
        return String((d as { message: string }).message)
      }
      return code
    }
  }
  if (Array.isArray(d))
    return d
      .map((item) => {
        if (typeof item !== 'object' || item === null) return JSON.stringify(item)
        const msg = 'msg' in item ? String(item.msg) : ''
        const loc =
          'loc' in item && Array.isArray(item.loc)
            ? item.loc.filter((x) => x !== 'body').join('.')
            : ''
        if (loc && msg) return `${loc}: ${msg}`
        return msg || JSON.stringify(item)
      })
      .join('; ')
  return JSON.stringify(d)
}

/**
 * Realiza una llamada fetch con timeout, retry en errores de red/timeout,
 * y parsing tipado de la respuesta JSON.
 *
 * @param path Ruta absoluta (empieza con /) o URL completa
 * @param init Opciones de fetch (method, headers, body)
 * @param bearerToken Token JWT o null
 * @param retries Numero de reintentos en caso de error de red/timeout (default 2)
 * @param timeoutMs Timeout en milisegundos (default 15000)
 */
export async function apiFetchJson<T>(
  path: string,
  init: RequestInit,
  bearerToken: string | null,
  retries: number = 2,
  timeoutMs: number = 15000,
): Promise<T> {
  const base = getApiBaseUrl()
  const url = path.startsWith('http') ? path : `${base}${path.startsWith('/') ? path : `/${path}`}`
  const headers = new Headers(init.headers)
  if (bearerToken) headers.set('Authorization', `Bearer ${bearerToken}`)
  if (!headers.has('Content-Type') && init.body !== undefined) {
    headers.set('Content-Type', 'application/json')
  }

  const method = (init.method ?? 'GET').toUpperCase()

  let lastError: Error | null = null

  for (let attempt = 0; attempt <= retries; attempt++) {
    const controller = new AbortController()
    const timeout = setTimeout(() => controller.abort(), timeoutMs)

    try {
      const res = await fetch(url, {
        ...init,
        headers,
        signal: controller.signal,
      })

      const text = await res.text()
      let data: unknown = undefined
      if (text) {
        try {
          data = JSON.parse(text) as unknown
        } catch {
          data = text
        }
      }

      if (!res.ok) {
        const fromDetail = typeof data === 'object' ? formatFastApiDetail(data) : ''
        const msg =
          fromDetail ||
          (typeof data === 'object' && data !== null && 'message' in data
            ? String((data as { message: unknown }).message)
            : res.statusText)
        throw new ApiError(
          msg || `HTTP ${res.status}`,
          res.status,
          data,
          res.status === 429 ? parseRetryAfterSeconds(res) : undefined,
        )
      }

      // Cachear respuestas GET para modo offline
      if (method === 'GET') {
        cacheApiData(url, data, 24 * 60 * 60 * 1000)
      }

      return data as T
    } catch (e) {
      lastError = e instanceof Error ? e : new Error(String(e))

      // En errores de red, intentar usar cache offline
      if (method === 'GET') {
        const cached = await getCachedApiData<T>(url)
        if (cached !== null) return cached
      }

      // No reintentar en errores HTTP 4xx (excepto 429 rate limit)
      if (e instanceof ApiError) {
        if (e.status !== 429) throw e
        // Para 429, reintentar solo si quedan intentos
        if (attempt >= retries) throw e
      }

      // Reintentar solo en errores de red o timeout
      const isRetryable =
        e instanceof TypeError ||
        (e instanceof Error && e.name === 'AbortError')

      if (isRetryable && attempt < retries) {
        // Espera exponencial: 500ms, 1000ms, 2000ms...
        const delay = 500 * Math.pow(2, attempt)
        await new Promise((resolve) => setTimeout(resolve, delay))
        continue
      }

      throw lastError
    } finally {
      clearTimeout(timeout)
    }
  }

  throw lastError ?? new Error('Unknown error')
}
