import { motion, useReducedMotion } from 'framer-motion'
import { useCallback, useEffect, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'

import type { IntegrationId } from '@/features/integrations'
import { getIntegrationById } from '@/features/integrations'
import { ApiError } from '@/lib/api/http'
import { translateApiError, translateError } from '@/lib/error-messages'
import { requestGoogleOAuthStart } from '@/lib/api/google-oauth'
import { getOrCreateLocalGoogleOAuthSubject } from '@/lib/api/oauth-subject-storage'

import { useGoogleOAuthPolling } from './useGoogleOAuthPolling'

import '../integration-picker/integration-selector.css'
import './google-automation-oauth.css'

function formatOAuthStartError(error: unknown): string {
  if (error instanceof ApiError) {
    return translateApiError(error, 'No se pudo iniciar la conexión con Google. Intenta de nuevo.')
  }
  return translateError(error, 'No se pudo iniciar la conexión con Google. Intenta de nuevo.')
}

export type GoogleAutomationOAuthStepProps = {
  googleIntegrations: readonly IntegrationId[]
  getAccessToken: () => Promise<string | null>
  onBack: () => void
  onSkip: () => void
  onContinueToSummary: () => void
}

async function openAuthorizationUrl(url: string): Promise<void> {
  if (window.desktop?.openUrl) {
    const r = await window.desktop.openUrl(url)
    if (r && typeof r === 'object' && 'ok' in r && r.ok === false) {
      window.open(url, '_blank', 'noopener,noreferrer')
    }
    return
  }
  window.open(url, '_blank', 'noopener,noreferrer')
}

export function GoogleAutomationOAuthStep({
  googleIntegrations,
  getAccessToken,
  onBack,
  onSkip,
  onContinueToSummary,
}: GoogleAutomationOAuthStepProps) {
  const { t } = useTranslation()
  const reduceMotion = useReducedMotion()
  const easing = reduceMotion ? 'linear' : ([0.16, 1, 0.3, 1] as const)
  const [error, setError] = useState<string | null>(null)
  const [busyOAuth, setBusyOAuth] = useState(false)
  const [openedBrowser, setOpenedBrowser] = useState(false)
  const [cooldownUntil, setCooldownUntil] = useState<number | null>(null)

  const autoContinuedRef = useRef(false)
  const oauthStartInFlightRef = useRef(false)

  const {
    configured: pollConfigured,
    loading: pollLoading,
    error: pollError,
    timedOut: pollTimedOut,
  } = useGoogleOAuthPolling(openedBrowser, getAccessToken)

  // Auto-avance al detectar que el OAuth se completó
  useEffect(() => {
    if (pollConfigured && !autoContinuedRef.current) {
      autoContinuedRef.current = true
      onContinueToSummary()
    }
  }, [pollConfigured, onContinueToSummary])

  // Mostrar error del polling si no hay error local
  const displayError = error || pollError

  const cooldownSeconds =
    cooldownUntil !== null ? Math.max(0, Math.ceil((cooldownUntil - Date.now()) / 1000)) : 0
  const inCooldown = cooldownSeconds > 0

  useEffect(() => {
    if (!cooldownUntil) return
    const timer = setInterval(() => {
      if (Date.now() >= cooldownUntil) {
        setCooldownUntil(null)
      }
    }, 500)
    return () => clearInterval(timer)
  }, [cooldownUntil])

  const onContinueWithGoogle = useCallback(async () => {
    if (oauthStartInFlightRef.current || inCooldown) return

    setError(null)
    setBusyOAuth(true)
    oauthStartInFlightRef.current = true
    autoContinuedRef.current = false
    try {
      const tok = await getAccessToken()
      const bearer = tok?.trim() || null

      const res = await requestGoogleOAuthStart({
        bearerAccessToken: bearer,
        devUserIdWhenNoJwt: bearer ? undefined : await getOrCreateLocalGoogleOAuthSubject(),
        integrations: googleIntegrations.filter((id) => id === 'gmail' || id === 'google-calendar'),
      })
      await openAuthorizationUrl(res.authorization_url)
      setOpenedBrowser(true)
    } catch (e) {
      const errorMsg = formatOAuthStartError(e)
      console.error('[GoogleOAuth] Fallo al iniciar:', errorMsg, e)
      setError(errorMsg)
      if (e instanceof ApiError && e.status === 429) {
        const waitSeconds = e.retryAfterSeconds ?? 60
        setCooldownUntil(Date.now() + waitSeconds * 1000)
      }
    } finally {
      oauthStartInFlightRef.current = false
      setBusyOAuth(false)
    }
  }, [getAccessToken, googleIntegrations, inCooldown])

  return (
    <motion.section
      className="integration-step"
      initial={{ opacity: 0, filter: reduceMotion ? 'blur(0px)' : 'blur(8px)' }}
      animate={{ opacity: 1, filter: 'blur(0px)' }}
      exit={{ opacity: 0, filter: reduceMotion ? 'blur(0px)' : 'blur(8px)' }}
      transition={{ duration: reduceMotion ? 0.12 : 0.55, ease: easing }}
    >
      <div className="integration-step__grain" aria-hidden />
      <div className="integration-step__glow integration-step__glow--a" aria-hidden />
      <div className="integration-step__glow integration-step__glow--b" aria-hidden />

      <motion.div
        className="integration-step__card"
        initial={{ opacity: 0, y: reduceMotion ? 0 : 12 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: reduceMotion ? 0.12 : 0.55, delay: reduceMotion ? 0 : 0.06 }}
      >
        <header className="integration-step__header">
          <h2 className="integration-step__title">Acceso a tus automatizaciones Google</h2>
          <p className="integration-step__subtitle">
            {googleIntegrations.length === 1
              ? `Solo ${getIntegrationById(googleIntegrations[0]).label} — no es el inicio de sesión del producto.`
              : 'Gmail y Calendar solo aquí — no es el inicio de sesión del producto.'}
          </p>
        </header>

        <p className="integration-step__google-lead">
          Abrimos Google en el navegador para conceder permisos de la automatización que elegiste.
        </p>

        {openedBrowser && !pollConfigured ? (
          <div className="integration-step__polling-area" role="status" aria-live="polite">
            {pollTimedOut ? (
              <div>
                <p className="integration-step__google-timeout">
                  {t('google.timeout', 'La autorización tomó demasiado tiempo. Puedes intentar de nuevo.')}
                </p>
                <button
                  type="button"
                  className="integration-step__continue"
                  onClick={onContinueToSummary}
                  style={{ marginTop: '0.75rem' }}
                >
                  {t('google.continue_manual', 'Continuar manualmente →')}
                </button>
              </div>
            ) : (
              <div>
                <div className="integration-step__spinner" aria-hidden="true">
                  <span className="integration-step__spinner-dot" />
                  <span className="integration-step__spinner-dot" />
                  <span className="integration-step__spinner-dot" />
                </div>
                <p className="integration-step__google-polling">
                  {t('google.connecting', 'Esperando autorización de Google...')}
                </p>
              </div>
            )}
          </div>
        ) : null}

        {displayError ? (
          <p className="integration-step__error" role="alert">
            {displayError}
          </p>
        ) : null}

        <footer className="integration-step__footer">
          <button type="button" className="integration-step__back" onClick={onBack}>
            ← Retroceder
          </button>
          <div className="integration-step__footer-right integration-step__google-actions">
            <button type="button" className="integration-step__omit" onClick={onSkip}>
              Omitir vincular Google <span aria-hidden>→</span>
            </button>
            <div
              style={{
                display: 'flex',
                flexWrap: 'wrap',
                gap: '0.65rem',
                justifyContent: 'flex-end',
              }}
            >
              <button
                type="button"
                className="integration-step__continue integration-step__continue--google"
                disabled={busyOAuth || pollLoading || inCooldown}
                onClick={() => void onContinueWithGoogle()}
              >
                {inCooldown
                  ? `Espera ${cooldownSeconds}s…`
                  : busyOAuth
                    ? 'Abriendo…'
                    : pollLoading
                      ? t('google.connecting', 'Esperando autorización de Google...')
                      : openedBrowser
                        ? 'Reabrir Google'
                        : 'Continuar con Google'}
              </button>
            </div>
          </div>
        </footer>
      </motion.div>
    </motion.section>
  )
}
