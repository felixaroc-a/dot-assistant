import { motion, useReducedMotion } from 'framer-motion'
import { useCallback, useEffect, useState } from 'react'

import type { IntegrationId } from '@/features/integrations'
import { INTEGRATION_META, getIntegrationById } from '@/features/integrations'
import { getChannelMeta } from '@/features/onboarding/model/channel.meta'
import type { ChannelId } from '@/features/onboarding/model/channel.types'
import { useAuth } from '@/features/auth'
import { getWhatsAppChannelStatus } from '@/lib/api/whatsapp'
import type { WhatsAppChannelStatus } from '@/lib/api/whatsapp'
import { getGoogleOAuthStatus } from '@/lib/api/google-oauth'
import type { GoogleOAuthStatusResponse } from '@/lib/api/google-oauth'
import { isPendingVerificationStatus } from '@/lib/whatsapp/status'

import './integration-summary-step.css'

export type IntegrationSummaryProps = {
  channelId: ChannelId | null
  selectedIds: IntegrationId[]
  onBack: () => void
  onConfirm: () => void
}

type ConfirmGuard = 'none' | 'checking_whatsapp' | 'whatsapp_unlinked'

type SummaryItemStatus = 'configured' | 'pending' | 'skipped' | 'failed'

function StatusIcon({ status }: { status: SummaryItemStatus }) {
  if (status === 'configured') {
    return (
      <span className="integration-summary__status-icon integration-summary__status-icon--ok" aria-hidden>
        ✓
      </span>
    )
  }
  if (status === 'pending') {
    return (
      <span className="integration-summary__status-icon integration-summary__status-icon--pending" aria-hidden>
        ○
      </span>
    )
  }
  if (status === 'skipped') {
    return (
      <span className="integration-summary__status-icon integration-summary__status-icon--skipped" aria-hidden>
        —
      </span>
    )
  }
  return (
    <span className="integration-summary__status-icon integration-summary__status-icon--failed" aria-hidden>
      ✗
    </span>
  )
}

function StatusLabel({ status }: { status: SummaryItemStatus }) {
  if (status === 'pending') {
    return (
      <span className="integration-summary__status-label integration-summary__status-label--pending">
        Pendiente
      </span>
    )
  }
  if (status === 'skipped') {
    return (
      <span className="integration-summary__status-label integration-summary__status-label--skipped">
        Omitido
      </span>
    )
  }
  if (status === 'failed') {
    return (
      <span className="integration-summary__status-label integration-summary__status-label--failed">
        Error
      </span>
    )
  }
  return null
}

export function IntegrationSummary({
  channelId,
  selectedIds,
  onBack,
  onConfirm,
}: IntegrationSummaryProps) {
  const { getAccessToken } = useAuth()
  const reduceMotion = useReducedMotion()
  const easing = reduceMotion ? 'linear' : ([0.16, 1, 0.3, 1] as const)

  const [confirmGuard, setConfirmGuard] = useState<ConfirmGuard>('none')
  const [whatsappStatus, setWhatsappStatus] = useState<WhatsAppChannelStatus | null>(null)
  const [oauthStatus, setOauthStatus] = useState<GoogleOAuthStatusResponse | null>(null)

  const orderedIds = INTEGRATION_META.map((m) => m.id).filter((id) => selectedIds.includes(id))

  /* ── Fetch estados reales al montar ── */
  useEffect(() => {
    void (async () => {
      try {
        const status = await getWhatsAppChannelStatus(getAccessToken)
        setWhatsappStatus(status)
      } catch {
        setWhatsappStatus(null)
      }
    })()
    void (async () => {
      try {
        const token = await getAccessToken()
        const status = await getGoogleOAuthStatus(token)
        setOauthStatus(status)
      } catch {
        setOauthStatus(null)
      }
    })()
  }, [getAccessToken])

  /* ── Derivación de estado para cada fila ── */
  function deriveChannelStatus(): SummaryItemStatus {
    if (channelId === null) return 'skipped'
    if (!whatsappStatus) return 'pending'
    if (whatsappStatus.linked) return 'configured'
    if (whatsappStatus.error) return 'failed'
    return 'pending'
  }

  function deriveIntegrationStatus(id: IntegrationId): SummaryItemStatus {
    if (id === 'third-option') return 'configured'
    if (!oauthStatus) return 'pending'
    if (oauthStatus.configured && oauthStatus.integrations.includes(id)) return 'configured'
    return 'pending'
  }

  const channelStatus = deriveChannelStatus()
  const channelErrorDetail =
    channelStatus === 'failed' && whatsappStatus?.error ? whatsappStatus.error : undefined
  const pendingVerificationDetail =
    whatsappStatus && isPendingVerificationStatus(whatsappStatus)
      ? 'WhatsApp pendiente de verificación; se confirmará al primer mensaje o conexión.'
      : undefined

  /* ── Lógica de confirmación (sin cambios) ── */
  useEffect(() => {
    if (confirmGuard !== 'checking_whatsapp') return
    let cancelled = false
    void (async () => {
      try {
        const status = await getWhatsAppChannelStatus(getAccessToken)
        if (cancelled) return
        if (status.linked || isPendingVerificationStatus(status)) {
          onConfirm()
        } else {
          setConfirmGuard('whatsapp_unlinked')
        }
      } catch {
        if (!cancelled) {
          onConfirm()
        }
      }
    })()
    return () => {
      cancelled = true
    }
  }, [confirmGuard, getAccessToken, onConfirm])

  const handleConfirm = useCallback(() => {
    if (channelId === 'whatsapp') {
      setConfirmGuard('checking_whatsapp')
    } else {
      onConfirm()
    }
  }, [channelId, onConfirm])

  const handleDismissWarning = useCallback(() => {
    setConfirmGuard('none')
  }, [])

  const handleConfirmAnyway = useCallback(() => {
    setConfirmGuard('none')
    onConfirm()
  }, [onConfirm])

  return (
    <motion.section
      className="integration-summary"
      initial={{ opacity: 0, filter: reduceMotion ? 'blur(0px)' : 'blur(8px)' }}
      animate={{ opacity: 1, filter: 'blur(0px)' }}
      exit={{ opacity: 0, filter: reduceMotion ? 'blur(0px)' : 'blur(8px)' }}
      transition={{ duration: reduceMotion ? 0.12 : 0.55, ease: easing }}
    >
      <div className="integration-summary__grain" aria-hidden />
      <div className="integration-summary__glow integration-summary__glow--a" aria-hidden />
      <div className="integration-summary__glow integration-summary__glow--b" aria-hidden />

      <motion.div
        className="integration-summary__card"
        initial={{ opacity: 0, y: reduceMotion ? 0 : 12 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: reduceMotion ? 0.12 : 0.55, delay: reduceMotion ? 0 : 0.06 }}
      >
        <aside className="integration-summary__aside">
          <p className="integration-summary__eyebrow">Resumen de lo seleccionado</p>
          <ul className="integration-summary__list">
            {/* ── Fila del canal ── */}
            <li className="integration-summary__item">
              <StatusIcon status={channelStatus} />
              <StatusLabel status={channelStatus} />
              {channelId !== null ? (
                <span className="integration-summary__thumb" aria-hidden>
                  <img src={getChannelMeta(channelId).iconSrc} alt="" draggable={false} />
                </span>
              ) : null}
              <p className="integration-summary__item-label">
                Canal ·{' '}
                {channelId !== null ? getChannelMeta(channelId).name : 'Omitido (configurar más tarde)'}
              </p>
              {pendingVerificationDetail ? (
                <span className="integration-summary__item-detail">{pendingVerificationDetail}</span>
              ) : channelErrorDetail ? (
                <span className="integration-summary__item-detail">{channelErrorDetail}</span>
              ) : null}
            </li>

            {/* ── Filas de integraciones ── */}
            {orderedIds.map((id) => {
              const meta = getIntegrationById(id)
              const intStatus = deriveIntegrationStatus(id)
              return (
                <li key={id} className="integration-summary__item">
                  <StatusIcon status={intStatus} />
                  <StatusLabel status={intStatus} />
                  {meta.logoSrc ? (
                    <span className="integration-summary__thumb" aria-hidden>
                      <img src={meta.logoSrc} alt="" draggable={false} />
                    </span>
                  ) : (
                    <span className="integration-summary__thumb integration-summary__thumb--num" aria-hidden>
                      3
                    </span>
                  )}
                  <p className="integration-summary__item-label">{meta.label}</p>
                </li>
              )
            })}
          </ul>
        </aside>

        <div className="integration-summary__main">
          <h2 className="integration-summary__title">¿Todo correcto?</h2>
          <p className="integration-summary__hint">
            Puede retroceder para cambiar sus opciones o confirmar para continuar con la configuración.
          </p>
          <div className="integration-summary__actions">
            <button type="button" className="integration-summary__back" onClick={onBack}>
              ← Retroceder
            </button>
            <button
              type="button"
              className="integration-summary__confirm"
              onClick={handleConfirm}
              disabled={confirmGuard === 'checking_whatsapp'}
            >
              {confirmGuard === 'checking_whatsapp' ? 'Verificando…' : 'Confirmar'}
            </button>
          </div>
        </div>
      </motion.div>

      {confirmGuard === 'whatsapp_unlinked' && (
        <div className="integration-summary__overlay" role="dialog" aria-modal="true" aria-labelledby="wa-warning-title">
          <motion.div
            className="integration-summary__modal"
            initial={{ opacity: 0, scale: 0.95 }}
            animate={{ opacity: 1, scale: 1 }}
            transition={{ duration: 0.3, ease: [0.16, 1, 0.3, 1] }}
          >
            <h3 id="wa-warning-title" className="integration-summary__modal-title">
              WhatsApp no vinculado
            </h3>
            <p className="integration-summary__modal-text">
              WhatsApp no vinculado. ¿Continuar igual?
            </p>
            <div className="integration-summary__modal-actions">
              <button
                type="button"
                className="integration-summary__modal-back"
                onClick={handleDismissWarning}
              >
                Esperar
              </button>
              <button
                type="button"
                className="integration-summary__modal-confirm"
                onClick={handleConfirmAnyway}
              >
                Continuar sin WhatsApp
              </button>
            </div>
          </motion.div>
        </div>
      )}
    </motion.section>
  )
}
