export type { GetAccessToken } from './api-client'
export { apiClient } from './api-client'

import { apiClient, type GetAccessToken } from './api-client'

/**
 * Peticion autenticada con un reintento tras refresh si el token expiró (401).
 * Mantiene compatibilidad hacia atras con codigo existente.
 */
export async function apiFetchAuthed<T>(
  path: string,
  init: RequestInit,
  getAccessToken: GetAccessToken,
): Promise<T> {
  return apiClient.request(path, init, getAccessToken, false)
}

// Re-exportar para que codigo existente pueda usar el cliente directamente
export { ApiError } from './http'
