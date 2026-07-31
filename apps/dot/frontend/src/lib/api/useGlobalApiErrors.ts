import { useEffect } from 'react'

import { useToast } from '@/components/Toast'
import { ApiError } from '@/lib/api/http'
import { apiClient } from '@/lib/api/api-client'
import { translateApiError, translateErrorMessage } from '@/lib/error-messages'

/**
 * Hook que conecta el manejador global de errores HTTP del ApiClient
 * con el sistema de Toast de la UI.
 *
 * Colocar una vez en el componente raiz (App.tsx).
 */
export function useGlobalApiErrors(): void {
  const toast = useToast()

  useEffect(() => {
    const unsubscribe = apiClient.onError((error) => {
      const isServerError = error.status && error.status >= 500
      const isAuthError = error.status === 401 || error.status === 403

      const friendly = error.status
        ? translateApiError(new ApiError(error.message, error.status))
        : translateErrorMessage(error.message)

      if (isServerError) {
        toast.error(friendly)
      } else if (isAuthError) {
        toast.warning(friendly)
      } else if (error.status === 429) {
        toast.warning(friendly)
      } else if (error.status && error.status >= 400) {
        toast.error(friendly)
      }
    })

    return unsubscribe
  }, [toast])
}
