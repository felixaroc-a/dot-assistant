import { ApiError, apiFetchJson } from '@/lib/api/http'

export type GetAccessToken = () => Promise<string | null>

/**
 * Tipo de error notificable a la UI.
 * Los handlers registrados reciben estos errores para mostrar toasts.
 */
export type NotifiableError = {
  message: string
  status?: number
  context?: string
  timestamp: number
}

type ErrorHandler = (error: NotifiableError) => void

/**
 * Cliente HTTP centralizado con soporte para:
 * - Autenticacion JWT con auto-refresh en 401
 * - Handler global de errores notificables
 * - Metodos tipados get, post, patch, del
 *
 * Single Responsibility: Gestiona la comunicacion HTTP autenticada
 * y la notificacion centralizada de errores.
 */
class ApiClient {
  private errorHandlers = new Set<ErrorHandler>()

  /**
   * Registra un handler que recibira errores notificables.
   * Retorna una funcion para darse de baja.
   */
  onError(handler: ErrorHandler): () => void {
    this.errorHandlers.add(handler)
    return () => {
      this.errorHandlers.delete(handler)
    }
  }

  /** Dispara un error a todos los handlers registrados */
  private notifyError(error: NotifiableError): void {
    for (const handler of this.errorHandlers) {
      try {
        handler(error)
      } catch {
        console.warn('[ApiClient] Error handler fallo:', error)
      }
    }
  }

  /**
   * Peticion GET tipada.
   */
  async get<T>(path: string, getAccessToken?: GetAccessToken): Promise<T> {
    return this.request<T>(path, { method: 'GET' }, getAccessToken)
  }

  /**
   * Peticion POST tipada.
   */
  async post<T>(path: string, body?: unknown, getAccessToken?: GetAccessToken): Promise<T> {
    return this.request<T>(
      path,
      {
        method: 'POST',
        body: body !== undefined ? JSON.stringify(body) : undefined,
      },
      getAccessToken,
    )
  }

  /**
   * Peticion PATCH tipada.
   */
  async patch<T>(path: string, body: unknown, getAccessToken?: GetAccessToken): Promise<T> {
    return this.request<T>(
      path,
      {
        method: 'PATCH',
        body: JSON.stringify(body),
      },
      getAccessToken,
    )
  }

  /**
   * Peticion DELETE tipada.
   */
  async del<T>(path: string, getAccessToken?: GetAccessToken): Promise<T> {
    return this.request<T>(path, { method: 'DELETE' }, getAccessToken)
  }

  /**
   * Ejecuta una peticion HTTP con soporte de:
   * - Inyeccion de token JWT
   * - Auto-refresh en 401 con reintento
   * - Notificacion de errores no recuperables
   *
   * @param path Ruta absoluta (empieza con /) o URL completa
   * @param init Opciones de fetch (method, headers, body)
   * @param getAccessToken Funcion para obtener el token JWT (opcional)
   * @param _retried Flag interno para evitar bucle infinito de refresh
   */
  async request<T>(
    path: string,
    init: RequestInit,
    getAccessToken?: GetAccessToken,
    _retried = false,
  ): Promise<T> {
    let token: string | null = null
    if (getAccessToken) {
      token = await getAccessToken()
    }

    try {
      return await apiFetchJson<T>(path, init, token)
    } catch (e) {
      // Auto-refresh en 401: solo un reintento
      if (e instanceof ApiError && e.status === 401 && token && getAccessToken && !_retried) {
        const retryToken = await getAccessToken()
        if (retryToken && retryToken !== token) {
          return this.request<T>(path, init, getAccessToken, true)
        }
      }

      // Notificar errores de servidor (5xx) o de autenticacion (401/403) no recuperables.
      // Los endpoints de canal WhatsApp manejan sus propios errores en onboarding.
      if (e instanceof ApiError && e.status >= 400) {
        const context = path.split('?')[0]
        const isWhatsAppChannel = context.includes('/whatsapp/channel')
        if (isWhatsAppChannel && (e.status === 401 || e.status === 403)) {
          throw e
        }
        this.notifyError({
          message: e.message || `Error HTTP ${e.status}`,
          status: e.status,
          context,
          timestamp: Date.now(),
        })
      }

      throw e
    }
  }
}

/** Instancia global unica del cliente API */
export const apiClient = new ApiClient()
