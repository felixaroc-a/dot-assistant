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
  if (typeof data === 'object' && data !== null && 'message' in data) {
    return String((data as { message: unknown }).message)
  }
  if (typeof data === 'string') return data
  return ''
}

const VISION_ANALYZE_PATH = '/v1/vision/analyze'

export type VisionAnalyzeResponse = {
  result: string
}

export async function analyzeImage(
  file: File,
  prompt: string,
  token: string | null,
): Promise<VisionAnalyzeResponse> {
  const formData = new FormData()
  formData.append('file', file)
  formData.append('prompt', prompt)

  const url = `${getApiBaseUrl()}${VISION_ANALYZE_PATH}`
  const headers = new Headers()
  if (token) {
    headers.set('Authorization', `Bearer ${token}`)
  }

  const res = await fetch(url, {
    method: 'POST',
    headers,
    body: formData,
  })

  const text = await res.text()
  let data: unknown
  if (text) {
    try {
      data = JSON.parse(text)
    } catch {
      data = text
    }
  }

  if (!res.ok) {
    const message = formatErrorDetail(data) || res.statusText || `HTTP ${res.status}`
    throw new ApiError(message, res.status, data)
  }

  if (typeof data === 'object' && data !== null && 'result' in data) {
    return { result: String((data as { result: unknown }).result ?? '') }
  }

  return { result: typeof data === 'string' ? data : '' }
}
