import { motion, useReducedMotion } from 'framer-motion'
import { useCallback, useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'

import { PRODUCT_NAME } from '@/shared/constants/brand'
import { ApiError } from '@/lib/api/http'
import { isDemoMode, isUsbGateSkipped } from '@/lib/desktop/usb-gate-dev'
import { readReadyDotUsbSerial } from '@/lib/desktop/usb-serial'
import { trackLoginFailure } from '@/lib/telemetry'

import { useAuth } from './auth-context'
import './login-screen.css'

type CedulaPrefix = 'E' | 'J' | 'V'

const USB_POLL_MS = 2500

function mapLoginError(e: unknown, t: (key: string, opts?: Record<string, unknown>) => string): string {
  if (!(e instanceof ApiError)) return e instanceof Error ? e.message : t('auth.auth_error')
  const detail =
    e.body && typeof e.body === 'object' && e.body !== null
      ? (e.body as { detail?: unknown }).detail
      : null
  if (e.status === 403 && detail === 'subscription_expired') return t('auth.subscription_expired')
  if (e.status === 400 && detail === 'pendrive_required') {
    return t('auth.pendrive_required', { productName: PRODUCT_NAME })
  }
  if (e.status === 401) return t('auth.login_failed')
  return e.message || t('auth.login_generic_error')
}

function PasswordToggleIcon({ visible }: { visible: boolean }) {
  if (visible) {
    return (
      <svg width="20" height="20" viewBox="0 0 24 24" fill="none" aria-hidden>
        <path d="M3 3l18 18M10.58 10.58A2 2 0 0 0 12 14a2 2 0 0 0 1.42-.58M9.88 5.09A10.94 10.94 0 0 1 12 5c5 0 9.27 3.11 11 7.5a11.8 11.8 0 0 1-1.67 2.86M6.61 6.61A11.8 11.8 0 0 0 1 12.5C2.73 16.89 7 20 12 20a10.94 10.94 0 0 0 4.91-1.09" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
      </svg>
    )
  }
  return (
    <svg width="20" height="20" viewBox="0 0 24 24" fill="none" aria-hidden>
      <path d="M2 12.5C3.73 8.11 8 5 13 5s9.27 3.11 11 7.5c-1.73 4.39-6 7.5-11 7.5S3.73 16.89 2 12.5Z" stroke="currentColor" strokeWidth="1.5" />
      <circle cx="13" cy="12.5" r="3" stroke="currentColor" strokeWidth="1.5" />
    </svg>
  )
}

export type LoginScreenProps = {
  onLostPendrive?: () => void
  /** Error al restaurar sesion guardada (timeout, IPC, etc.) */
  restoreError?: string | null
}

export function LoginScreen({ onLostPendrive, restoreError }: LoginScreenProps) {
  const { t } = useTranslation()
  const { login } = useAuth()
  const reduceMotion = useReducedMotion()
  const easing = reduceMotion ? 'linear' : ([0.16, 1, 0.3, 1] as const)

  const [cedulaPrefix, setCedulaPrefix] = useState<CedulaPrefix>('E')
  const [cedulaDigits, setCedulaDigits] = useState('')
  const [password, setPassword] = useState('')
  const [showPassword, setShowPassword] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [usbGateSkipped, setUsbGateSkipped] = useState(false)
  const [demoMode, setDemoMode] = useState(false)
  const [usbConnected, setUsbConnected] = useState(false)
  const [usbChecking, setUsbChecking] = useState(true)
  const [, setAttempts] = useState(0)
  const [blockedUntil, setBlockedUntil] = useState<number | null>(null)
  const [remainingSeconds, setRemainingSeconds] = useState(0)

  useEffect(() => {
    void isUsbGateSkipped().then(setUsbGateSkipped)
    void isDemoMode().then(setDemoMode)
  }, [])

  const probeUsb = useCallback(async () => {
    if (usbGateSkipped) return
    setUsbChecking(true)
    try {
      const usb = await readReadyDotUsbSerial()
      setUsbConnected(Boolean(usb.serial))
    } finally {
      setUsbChecking(false)
    }
  }, [usbGateSkipped])

  useEffect(() => {
    if (usbGateSkipped) return

    void probeUsb()
    const timer = setInterval(() => {
      void probeUsb()
    }, USB_POLL_MS)

    return () => clearInterval(timer)
  }, [probeUsb, usbGateSkipped])

  useEffect(() => {
    if (!blockedUntil) {
      setRemainingSeconds(0)
      return
    }

    const tick = () => {
      const remaining = Math.max(0, Math.floor((blockedUntil - Date.now()) / 1000))
      setRemainingSeconds(remaining)
      if (remaining <= 0) {
        setBlockedUntil(null)
        setAttempts(0)
      }
    }

    tick()
    const intervalId = setInterval(tick, 1000)
    return () => clearInterval(intervalId)
  }, [blockedUntil])

  const run = useCallback(async (fn: () => Promise<void>) => {
    setError(null)
    setBusy(true)
    try {
      await fn()
      setAttempts(0)
      setBlockedUntil(null)
    } catch (e) {
      const msg = mapLoginError(e, t)
      setError(msg)
      trackLoginFailure(msg)
      setAttempts((prev) => {
        const next = prev + 1
        if (next >= 5) {
          setBlockedUntil(Date.now() + 60_000)
        }
        return next
      })
    } finally {
      setBusy(false)
    }
  }, [t])

  const onSubmit = () => {
    void run(async () => {
      const fullCedula = `${cedulaPrefix}-${cedulaDigits}`
      if (usbGateSkipped) {
        await login(fullCedula, password, null)
        return
      }
      const usb = await readReadyDotUsbSerial()
      if (!usb.serial) {
        setError(
          usb.error ??
            t('auth.usb_not_found', { productName: PRODUCT_NAME }),
        )
        return
      }
      await login(fullCedula, password, usb.serial)
    })
  }

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !busy && !isBlocked) {
      onSubmit()
    }
  }

  const isBlocked = blockedUntil !== null && remainingSeconds > 0
  const canSubmit = Boolean(cedulaDigits.trim() && password && !busy && !isBlocked)
  const alertMsg = isBlocked
    ? t('auth.too_many_attempts', { seconds: remainingSeconds })
    : error ?? restoreError

  const usbStatusLabel = usbChecking
    ? t('auth.link_pendrive_detecting')
    : usbConnected
      ? PRODUCT_NAME
      : t('auth.usb_not_found', { productName: PRODUCT_NAME })

  return (
    <motion.section
      className="login-screen"
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      transition={{ duration: reduceMotion ? 0.12 : 0.28 }}
    >
      <motion.div
        className="login-screen__panel"
        initial={{ opacity: 0, y: reduceMotion ? 0 : 12 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: reduceMotion ? 0.12 : 0.32, delay: reduceMotion ? 0 : 0.04, ease: easing }}
      >
        <header className="login-screen__header">
          <p className="login-screen__brand">{PRODUCT_NAME}</p>
          <h1 className="login-screen__title">{t('auth.login_title')}</h1>
          <p className="login-screen__subtitle">
            {usbGateSkipped
              ? t('auth.dev_mode_hint')
              : t('auth.login_hint', { productName: PRODUCT_NAME })}
          </p>
        </header>

        {demoMode ? (
          <div className="login-screen__demo-banner" role="banner" aria-label="Modo demostración activo">
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" aria-hidden>
              <path d="M12 2L2 7l10 5 10-5-10-5zM2 17l10 5 10-5M2 12l10 5 10-5" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
            </svg>
            <span>MODO DEMO — Sin pendrive</span>
          </div>
        ) : null}

        {!usbGateSkipped ? (
          <div className="login-screen__usb" role="status" aria-live="polite" aria-label={usbStatusLabel}>
            <svg className="login-screen__usb-icon" width="18" height="18" viewBox="0 0 24 24" fill="none" aria-hidden>
              <path d="M12 3v10M8 7l4-4 4 4M6 21h12M8 21v-4a4 4 0 0 1 8 0v4" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
            </svg>
            <span className={`login-screen__usb-dot${usbConnected ? ' login-screen__usb-dot--on' : ''}`} aria-hidden />
            <span className={`login-screen__usb-label${!usbConnected && !usbChecking ? ' login-screen__usb-label--muted' : ''}`}>
              {usbStatusLabel}
            </span>
          </div>
        ) : null}

        <div className="login-screen__form">
          <label className="login-screen__field">
            <span className="login-screen__label">{t('auth.cedula')}</span>
            <div className="login-screen__cedula-row">
              <select
                className="login-screen__cedula-prefix"
                value={cedulaPrefix}
                onChange={(e) => setCedulaPrefix(e.target.value as CedulaPrefix)}
                disabled={busy}
                aria-label="Prefijo de cédula"
              >
                <option value="E">E</option>
                <option value="J">J</option>
                <option value="V">V</option>
              </select>
              <input
                className="login-screen__cedula-digits"
                type="text"
                inputMode="numeric"
                autoComplete="username"
                value={cedulaDigits}
                onChange={(e) => setCedulaDigits(e.target.value.replace(/\D/g, '').slice(0, 10))}
                placeholder="12345678"
                disabled={busy}
                onKeyDown={handleKeyDown}
              />
            </div>
          </label>

          <label className="login-screen__field">
            <span className="login-screen__label">{t('auth.password')}</span>
            <div className="login-screen__password-wrap">
              <input
                className="login-screen__password-input"
                type={showPassword ? 'text' : 'password'}
                autoComplete="current-password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                disabled={busy}
                onKeyDown={handleKeyDown}
                placeholder={t('auth.password_placeholder')}
              />
              <button
                type="button"
                className="login-screen__password-toggle"
                aria-label={showPassword ? t('auth.hide_password') : t('auth.show_password')}
                onClick={() => setShowPassword((prev) => !prev)}
                tabIndex={-1}
              >
                <PasswordToggleIcon visible={showPassword} />
              </button>
            </div>
          </label>

          {alertMsg ? (
            <p className="login-screen__error" role="alert">{alertMsg}</p>
          ) : null}

          <button
            type="button"
            className="login-screen__submit"
            disabled={!canSubmit}
            onClick={onSubmit}
          >
            {busy ? t('auth.validating') : t('auth.enter')}
          </button>

          {onLostPendrive ? (
            <button type="button" className="login-screen__lost-link" onClick={onLostPendrive}>
              {t('auth.lost_pendrive')}
            </button>
          ) : null}
        </div>
      </motion.div>
    </motion.section>
  )
}
