import { useCallback, useEffect, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'

import { LoadingScreen } from '@/components/LoadingScreen'
import { LoginScreen, PendriveAppGate, PendriveLostFlow, SubscriptionExpiredScreen, useAuth } from '@/features/auth'
import { OnboardingFlow } from '@/features/onboarding'

const LOADING_TIMEOUT_MS = 5_000

/**
 * Componente raiz de la aplicacion protegida.
 * Integra la logica de autenticacion (sesion, suscripcion, pendrive)
 * con el flujo de onboarding/dashboard.
 *
 * Este componente reemplaza AuthenticatedRoot de App.tsx pero
 * ahora forma parte del sistema de rutas de React Router.
 */
export function AuthenticatedApp() {
  const { t } = useTranslation()
  const {
    session,
    loading,
    sessionRestoreError,
    isSubscriptionExpired,
    subscriptionExpiryDate,
    logout,
  } = useAuth()
  const [showLostFlow, setShowLostFlow] = useState(false)
  const [loadingTimedOut, setLoadingTimedOut] = useState(false)
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  const handleLostPendrive = useCallback(() => {
    setShowLostFlow(true)
  }, [])

  const handleBackToLogin = useCallback(() => {
    setShowLostFlow(false)
    logout()
  }, [logout])

  // Timeout: after 5 seconds of loading, show "Crear cuenta nueva"
  useEffect(() => {
    if (loading) {
      setLoadingTimedOut(false)
      timerRef.current = setTimeout(() => {
        setLoadingTimedOut(true)
      }, LOADING_TIMEOUT_MS)
      return () => {
        if (timerRef.current) {
          clearTimeout(timerRef.current)
          timerRef.current = null
        }
      }
    } else {
      setLoadingTimedOut(false)
    }
  }, [loading])

  if (loading) {
    return (
      <LoadingScreen message={t('loading.loading_session')}>
        {loadingTimedOut ? (
          <div style={{ marginTop: '1.25rem', textAlign: 'center' }}>
            <p style={{
              fontSize: '0.85rem',
              color: 'rgba(235, 235, 245, 0.55)',
              margin: '0 0 0.85rem',
              lineHeight: 1.45,
            }}>
              La verificación está tardando más de lo esperado.{' '}
              ¿Es tu primera vez?
            </p>
            <button
              type="button"
              onClick={() => {
                setLoadingTimedOut(false)
                logout()
              }}
              style={{
                padding: '0.6rem 1.4rem',
                borderRadius: '10px',
                border: '1px solid rgba(255, 255, 255, 0.2)',
                background: 'rgba(255, 255, 255, 0.06)',
                color: 'rgba(249, 249, 251, 0.92)',
                fontSize: '0.88rem',
                fontWeight: 500,
                cursor: 'pointer',
                fontFamily: 'inherit',
              }}
            >
              Crear cuenta nueva
            </button>
          </div>
        ) : null}
      </LoadingScreen>
    )
  }

  if (showLostFlow) {
    return <PendriveLostFlow onBackToLogin={handleBackToLogin} />
  }

  if (!session) {
    return (
      <LoginScreen
        onLostPendrive={handleLostPendrive}
        restoreError={sessionRestoreError}
      />
    )
  }

  if (isSubscriptionExpired) {
    return (
      <SubscriptionExpiredScreen
        fechaVencimiento={subscriptionExpiryDate}
        onLogout={logout}
      />
    )
  }

  return (
    <PendriveAppGate>
      <OnboardingFlow onLostPendrive={handleLostPendrive} />
    </PendriveAppGate>
  )
}
