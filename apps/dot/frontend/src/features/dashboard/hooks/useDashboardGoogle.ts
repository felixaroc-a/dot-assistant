import { useCallback, useEffect, useState } from 'react'

import { resolveGoogleOAuthStatus, revokeGoogleOAuth } from '@/lib/api/google-oauth'
import type { GetAccessToken } from '@/lib/api/client'

export type UseDashboardGoogleOptions = {
  getAccessToken: GetAccessToken
  /** Función para mostrar mensajes locales en el chat */
  pushLocalExchange: (role: string, text: string) => void
}

export type UseDashboardGoogleResult = {
  googleConnected: boolean
  googleRevoking: boolean
  handleRevokeGoogle: () => Promise<void>
  /** Fuerza reconsulta del estado OAuth (p. ej. tras conectar desde el panel). */
  refreshGoogleStatus: () => Promise<void>
  setGoogleConnected: (value: boolean) => void
}

export function useDashboardGoogle({
  getAccessToken,
  pushLocalExchange,
}: UseDashboardGoogleOptions): UseDashboardGoogleResult {
  const [googleConnected, setGoogleConnected] = useState(false)
  const [googleRevoking, setGoogleRevoking] = useState(false)

  const refreshGoogleStatus = useCallback(async () => {
    try {
      const status = await resolveGoogleOAuthStatus(getAccessToken)
      setGoogleConnected(status.configured)
    } catch (err) {
      console.warn('[Dashboard] No se pudo obtener estado de Google OAuth:', err)
      setGoogleConnected(false)
    }
  }, [getAccessToken])

  // Monitoreo de Google OAuth cada 30s
  useEffect(() => {
    void refreshGoogleStatus()
    const interval = setInterval(() => {
      void refreshGoogleStatus()
    }, 30_000)
    return () => clearInterval(interval)
  }, [refreshGoogleStatus])

  const handleRevokeGoogle = useCallback(async () => {
    if (googleRevoking) return
    setGoogleRevoking(true)
    try {
      const result = await revokeGoogleOAuth(getAccessToken)
      if (result.ok) {
        setGoogleConnected(false)
        pushLocalExchange('', '✅ Acceso a Google revocado exitosamente.')
      } else {
        pushLocalExchange('', `❌ Error al revocar acceso Google: ${result.message}`)
      }
    } catch (err) {
      console.warn('[Dashboard] Error al revocar acceso Google:', err)
      pushLocalExchange('', '❌ Error al revocar acceso Google. Revisa tu conexión.')
    } finally {
      setGoogleRevoking(false)
    }
  }, [getAccessToken, googleRevoking, pushLocalExchange])

  return {
    googleConnected,
    googleRevoking,
    handleRevokeGoogle,
    refreshGoogleStatus,
    setGoogleConnected,
  }
}
