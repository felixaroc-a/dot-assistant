import { useTranslation } from 'react-i18next'
import { motion, useReducedMotion } from 'framer-motion'

import './login-gate.css'

export type SubscriptionExpiredScreenProps = {
  fechaVencimiento: string | null
  onLogout: () => void
}

function formatDate(dateStr: string | null): string {
  if (!dateStr) return '—'
  try {
    const d = new Date(dateStr)
    return d.toLocaleDateString('es-VE', {
      year: 'numeric',
      month: 'long',
      day: 'numeric',
    })
  } catch {
    console.warn('[SubscriptionExpiredScreen] No se pudo formatear la fecha:', dateStr)
    return dateStr
  }
}

export function SubscriptionExpiredScreen({
  fechaVencimiento,
  onLogout,
}: SubscriptionExpiredScreenProps) {
  const { t } = useTranslation()
  const reduceMotion = useReducedMotion()
  const easing = reduceMotion ? 'linear' : ([0.16, 1, 0.3, 1] as const)

  return (
    <div className="login-gate">
      <div className="login-gate__grain" aria-hidden />
      <div className="login-gate__glow login-gate__glow--a" aria-hidden />
      <div className="login-gate__glow login-gate__glow--b" aria-hidden />

      <motion.div
        className="login-gate__card"
        initial={{ opacity: 0, y: reduceMotion ? 0 : 12 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: reduceMotion ? 0.12 : 0.55, ease: easing }}
      >
        <div className="login-gate__expired-icon" aria-hidden>
          <svg width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
            <circle cx="12" cy="12" r="10" />
            <line x1="12" y1="8" x2="12" y2="12" />
            <line x1="12" y1="16" x2="12.01" y2="16" />
          </svg>
        </div>

        <h1 className="login-gate__title">{t('auth.subscription_expired_title')}</h1>

        <p className="login-gate__lead">
          {t('auth.subscription_expired_lead', {
            date: <strong style={{ color: 'rgba(235, 235, 245, 0.92)' }}>{formatDate(fechaVencimiento)}</strong>,
          })}
        </p>

        <p className="login-gate__text" style={{ marginBottom: '1.25rem' }}>
          {t('auth.subscription_expired_message')}
        </p>

        <div className="login-gate__row" style={{ flexDirection: 'column', gap: '0.65rem' }}>
          <a
            href="mailto:soporte@dot.ai?subject=Renovación%20de%20suscripción"
            className="login-gate__primary"
            style={{ textAlign: 'center', textDecoration: 'none', display: 'block' }}
          >
            {t('auth.contact_support')}
          </a>
          <button
            type="button"
            className="login-gate__secondary"
            onClick={onLogout}
          >
            {t('auth.logout')}
          </button>
        </div>
      </motion.div>
    </div>
  )
}
