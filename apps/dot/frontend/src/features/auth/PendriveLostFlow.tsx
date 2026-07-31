import { useCallback, useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'

import { linkNewPendrive } from '@/lib/api/auth-login'
import { readLocalUsbSerial } from '@/lib/desktop/usb-serial'
import { ApiError } from '@/lib/api/http'

import { useAuth } from './auth-context'
import './login-gate.css'

type LostPhase = 'recovery-key' | 'instructions' | 'linking' | 'success'

type PendriveLostFlowProps = {
  /** Cuando se renderiza desde AuthenticatedRoot tras recovery JWT */
  onBackToLogin?: () => void
}

type LinkingStep =
  | 'detecting'
  | 'preparing'
  | 'binding'
  | 'done'
  | 'error'

function formatRecoveryKey(raw: string): string {
  const cleaned = raw.replace(/[^A-Za-z0-9]/g, '').toUpperCase()
  const groups: string[] = []
  for (let i = 0; i < cleaned.length && groups.length < 4; i += 12) {
    groups.push(cleaned.slice(i, i + 12))
  }
  return groups.join('-')
}

function mapRecoveryError(e: unknown, t: (key: string) => string): string {
  if (e instanceof ApiError) {
    if (e.status === 403 && e.body && typeof e.body === 'object' && e.body !== null) {
      const detail = (e.body as { detail?: unknown }).detail
      if (detail === 'subscription_expired') {
        return t('auth.subscription_expired')
      }
    }
    if (e.status === 401) {
      const detail =
        e.body && typeof e.body === 'object'
          ? (e.body as { detail?: string }).detail
          : undefined
      if (detail === 'recovery_key_invalida') {
        return t('auth.recovery_key_incorrect')
      }
      return t('auth.recovery_credentials_incorrect')
    }
    return e.message || t('auth.recovery_error')
  }
  return e instanceof Error ? e.message : t('auth.recovery_error_unexpected')
}

export function PendriveLostFlow({ onBackToLogin }: PendriveLostFlowProps) {
  const { t } = useTranslation()
  const { session, recoveryLogin, logout } = useAuth()
  const [phase, setPhase] = useState<LostPhase>(
    session?.hardwareRequired === false ? 'instructions' : 'recovery-key',
  )

  // ─── Recovery key form ────────────────────────────────────────────────────
  const [cedula, setCedula] = useState('')
  const [password, setPassword] = useState('')
  const [recoveryKey, setRecoveryKey] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  // ─── Linking state ────────────────────────────────────────────────────────
  const [linkError, setLinkError] = useState<string | null>(null)
  const [linking, setLinking] = useState(false)
  const [linkingStep, setLinkingStep] = useState<LinkingStep>('detecting')

  // Sincronizar fase cuando cambia la sesión
  useEffect(() => {
    if (session?.hardwareRequired === false && phase === 'recovery-key') {
      setPhase('instructions')
    }
    if (!session && phase !== 'recovery-key') {
      setPhase('recovery-key')
    }
  }, [session, phase])

  const handleRecoverySubmit = useCallback(async () => {
    if (!cedula.trim() || !password || !recoveryKey.trim()) {
      setError(t('auth.complete_all_fields'))
      return
    }
    setError(null)
    setBusy(true)
    try {
      await recoveryLogin(cedula.trim(), password, recoveryKey.trim())
      // session se actualiza via AuthProvider → fase cambia a 'instructions' via useEffect
    } catch (e) {
      setError(mapRecoveryError(e, t))
    } finally {
      setBusy(false)
    }
  }, [cedula, password, recoveryKey, recoveryLogin, t])

  const handleLinkNewPendrive = useCallback(async () => {
    setLinkError(null)
    setLinking(true)
    setLinkingStep('detecting')

    try {
      // Paso 1: Detectar pendrive
      let serial: string | null = null
      let drivePath: string | null = null

      const desktopApi = (window as unknown as Record<string, unknown>).desktop as
        | {
            pendriveSetup?: {
              listDevices?: () => Promise<{
                ok: boolean
                devices?: Array<{ serial: string; driveLetter: string; hasVault?: boolean; model?: string; interfaceType?: string }>
                error?: string
              }>
              createVault?: (serial: string, drivePath: string) => Promise<{ ok: boolean; token?: string; recoveryKey?: string; error?: string }>
              verifyVault?: (serial: string, drivePath: string) => Promise<{ ok: boolean; token?: string; error?: string }>
              findValid?: () => Promise<{ ok: boolean; serial?: string; drivePath?: string; token?: string; error?: string }>
            }
          }
        | undefined

      const setupApi = desktopApi?.pendriveSetup
      if (setupApi?.listDevices) {
        const listed = await setupApi.listDevices()
        const devices = listed.ok ? listed.devices ?? [] : []
        if (devices.length === 0) {
          setLinkError(t('auth.link_error_no_device'))
          setLinkingStep('error')
          setLinking(false)
          return
        }
        if (devices.length > 1) {
          setLinkError(t('auth.link_error_multiple'))
          setLinkingStep('error')
          setLinking(false)
          return
        }

        const device = devices[0]
        serial = device.serial
        drivePath = device.driveLetter.endsWith('\\')
          ? device.driveLetter
          : device.driveLetter + '\\'

        setLinkingStep('preparing')

        // Si el pendrive no tiene vault, crearlo
        if (!device.hasVault) {
          if (!setupApi.createVault) {
            setLinkError(t('auth.link_error_no_vault'))
            setLinkingStep('error')
            setLinking(false)
            return
          }
          const created = await setupApi.createVault(device.serial, drivePath)
          if (!created.ok) {
            const errMsg = created.error || ''
            if (errMsg.toLowerCase().includes('espacio') || errMsg.toLowerCase().includes('space')) {
              setLinkError(t('auth.link_error_no_space', { error: errMsg }) || `Espacio insuficiente en el USB. Se requieren al menos 200MB libres. Error: ${errMsg}`)
            } else {
              setLinkError(
                created.error
                  ? `${t('auth.link_error_prepare')}: ${created.error}`
                  : t('auth.link_error_prepare'),
              )
            }
            setLinkingStep('error')
            setLinking(false)
            return
          }
        }
      } else {
        // Fallback a readLocalUsbSerial
        const usb = await readLocalUsbSerial()
        serial = usb.serial
      }

      if (!serial) {
        setLinkError(t('auth.link_error_no_device'))
        setLinkingStep('error')
        setLinking(false)
        return
      }

      setLinkingStep('binding')
      setPhase('linking')

      // Vincular el nuevo serial en el servidor
      const token = session?.accessToken
      if (!token) {
        setLinkError(t('auth.link_error_no_session'))
        setLinkingStep('error')
        setLinking(false)
        return
      }

      await linkNewPendrive(serial, token)
      setLinkingStep('done')
      setPhase('success')
    } catch (e) {
      setLinkingStep('error')
      setLinkError(
        e instanceof ApiError
          ? e.message || t('auth.link_error_prepare')
          : t('auth.recovery_error_unexpected'),
      )
    } finally {
      setLinking(false)
    }
  }, [session, t])

  // ─── Pantalla: Recovery key ──────────────────────────────────────────────

  if (phase === 'recovery-key') {
    return (
      <div className="login-gate">
        <div className="login-gate__card">
          <div className="login-gate__expired-icon" aria-hidden="true">
            <svg width="40" height="40" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
              <rect x="3" y="11" width="18" height="11" rx="2" ry="2" />
              <path d="M7 11V7a5 5 0 0 1 10 0v4" />
            </svg>
          </div>

          <h1 className="login-gate__title">{t('auth.recover_account')}</h1>
          <p className="login-gate__lead">
            {t('auth.recover_lead')}
          </p>

          <label className="login-gate__label">
            {t('auth.cedula')}
            <input
              className="login-gate__input"
              type="text"
              autoComplete="username"
              value={cedula}
              onChange={(e) => setCedula(e.target.value)}
            />
          </label>

          <label className="login-gate__label">
            {t('auth.password')}
            <input
              className="login-gate__input"
              type="password"
              autoComplete="current-password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
            />
          </label>

          <label className="login-gate__label">
            {t('auth.recovery_key_label')}
            <input
              className="login-gate__input"
              type="text"
              inputMode="text"
              autoComplete="off"
              placeholder={t('auth.recovery_key_placeholder')}
              value={recoveryKey}
              onChange={(e) => {
                const formatted = formatRecoveryKey(e.target.value)
                if (formatted.length <= 51) setRecoveryKey(formatted)
              }}
            />
          </label>

          {error ? (
            <p className="login-gate__error" role="alert">
              {error}
            </p>
          ) : null}

          <div className="login-gate__row">
            <button
              type="button"
              className="login-gate__primary"
              disabled={busy}
              onClick={handleRecoverySubmit}
            >
              {busy ? t('auth.verify_recovery_busy') : t('auth.verify_recovery')}
            </button>
          </div>

          <div className="login-gate__divider">{t('auth.or')}</div>

          <div className="login-gate__row">
            <button
              type="button"
              className="login-gate__secondary"
              onClick={onBackToLogin ?? logout}
            >
              {t('auth.back_to_login')}
            </button>
          </div>
        </div>
      </div>
    )
  }

  // ─── Pantalla: Instrucciones para vincular nuevo pendrive ────────────────

  if (phase === 'instructions') {
    return (
      <div className="login-gate login-gate--error">
        <div className="login-gate__expired-icon" aria-hidden="true">
          <svg width="40" height="40" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
            <path d="M15 7h1a2 2 0 0 1 2 2v6a2 2 0 0 1-2 2h-2" />
            <path d="M6 7H4a2 2 0 0 0-2 2v6a2 2 0 0 0 2 2h1" />
            <path d="M11 16h2" />
            <path d="M12 14V8" />
          </svg>
        </div>

        <h1 className="login-gate__title">{t('auth.link_pendrive_title')}</h1>
        <p className="login-gate__text">
          {t('auth.link_pendrive_lead')}
        </p>
        <p className="login-gate__text" style={{ marginTop: '0.75rem' }}>
          {t('auth.link_pendrive_instructions')}
        </p>

        {linkError ? (
          <p className="login-gate__error" role="alert">
            {linkError}
          </p>
        ) : null}

        <div className="login-gate__row" style={{ marginTop: '1rem' }}>
          <button
            type="button"
            className="login-gate__primary"
            disabled={linking}
            onClick={handleLinkNewPendrive}
          >
            {linking ? t('auth.link_pendrive_detecting') : t('auth.link_pendrive_button')}
          </button>
        </div>
      </div>
    )
  }

  // ─── Pantalla: Vinculando ────────────────────────────────────────────────

  if (phase === 'linking') {
    const stepLabels: Record<LinkingStep, string> = {
      detecting: t('auth.linking_step_detect', 'Detectando pendrive USB…'),
      preparing: t('auth.linking_step_prepare', 'Preparando vault DOT en el pendrive…'),
      binding: t('auth.linking_step_bind', 'Vinculando al servidor…'),
      done: t('auth.linking_step_done', 'Vinculación completada.'),
      error: t('auth.linking_step_error', 'Error en la vinculación.'),
    }

    return (
      <div className="login-gate login-gate--error" role="status">
        <h1 className="login-gate__title">{t('auth.linking_title')}</h1>
        <p className="login-gate__text">
          {stepLabels[linkingStep] || t('auth.linking_lead')}
        </p>
        {linkingStep === 'error' && linkError ? (
          <p className="login-gate__error" role="alert">
            {linkError}
          </p>
        ) : null}
        {linkingStep !== 'error' && linkingStep !== 'done' ? (
          <div className="login-gate__spinner" style={{ margin: '1rem auto', width: 24, height: 24, border: '2px solid rgba(255,255,255,0.2)', borderTopColor: '#8b5cf6', borderRadius: '50%', animation: 'spin 0.8s linear infinite' }} aria-hidden="true" />
        ) : null}
      </div>
    )
  }

  // ─── Pantalla: Éxito ─────────────────────────────────────────────────────

  return (
    <div className="login-gate login-gate--error">
      <div className="login-gate__expired-icon" aria-hidden="true" style={{ color: 'rgba(80, 220, 140, 0.9)' }}>
        <svg width="44" height="44" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
          <path d="M22 11.08V12a10 10 0 1 1-5.93-9.14" />
          <polyline points="22 4 12 14.01 9 11.01" />
        </svg>
      </div>

      <h1 className="login-gate__title">{t('auth.link_success_title')}</h1>
      <p className="login-gate__text">
        {t('auth.link_success_lead')}
      </p>

      <div className="login-gate__row" style={{ marginTop: '1rem' }}>
        <button
          type="button"
          className="login-gate__primary"
          onClick={onBackToLogin ?? logout}
        >
          {t('auth.go_to_login')}
        </button>
      </div>
    </div>
  )
}
