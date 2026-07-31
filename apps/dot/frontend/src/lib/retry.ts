/**
 * Intenta ejecutar una función asíncrona con retry automático + backoff exponencial.
 */
export async function withRetry<T>(
  fn: () => Promise<T>,
  options: {
    maxRetries?: number
    baseDelayMs?: number
    maxDelayMs?: number
    onRetry?: (attempt: number, error: unknown) => void
  } = {},
): Promise<T> {
  const { maxRetries = 3, baseDelayMs = 1000, maxDelayMs = 10000, onRetry } = options

  let lastError: unknown

  for (let attempt = 0; attempt <= maxRetries; attempt++) {
    try {
      return await fn()
    } catch (error) {
      lastError = error
      if (attempt === maxRetries) break

      const delay = Math.min(baseDelayMs * 2 ** attempt, maxDelayMs)
      const jitter = delay * (0.5 + Math.random() * 0.5)
      onRetry?.(attempt + 1, error)

      await new Promise((resolve) => setTimeout(resolve, jitter))
    }
  }

  throw lastError
}

import { translateError } from '@/lib/error-messages'

/**
 * Mensajes de error amigables para el usuario.
 */
export function friendlyError(error: unknown): string {
  return translateError(error)
}
