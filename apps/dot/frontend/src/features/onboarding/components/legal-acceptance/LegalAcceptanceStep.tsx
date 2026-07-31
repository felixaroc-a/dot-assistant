import { motion, useReducedMotion } from 'framer-motion'
import { useState } from 'react'

import './legal-acceptance-step.css'

export type LegalAcceptanceStepProps = {
  accepted: boolean
  onAccept: () => void
  onBack?: () => void
}

export function LegalAcceptanceStep({ accepted, onAccept, onBack }: LegalAcceptanceStepProps) {
  const reduceMotion = useReducedMotion()
  const easing = reduceMotion ? 'linear' : ([0.16, 1, 0.3, 1] as const)
  const [checked, setChecked] = useState(accepted)
  const [saving, setSaving] = useState(false)

  async function handleContinue() {
    if (!checked || saving) return
    setSaving(true)
    try {
      await Promise.resolve(onAccept())
    } finally {
      setSaving(false)
    }
  }

  return (
    <motion.section
      className="legal-acceptance"
      initial={{ opacity: 0, filter: reduceMotion ? 'blur(0px)' : 'blur(8px)' }}
      animate={{ opacity: 1, filter: 'blur(0px)' }}
      exit={{ opacity: 0, filter: reduceMotion ? 'blur(0px)' : 'blur(8px)' }}
      transition={{ duration: reduceMotion ? 0.12 : 0.55, ease: easing }}
    >
      <div className="legal-acceptance__grain" aria-hidden />
      <div className="legal-acceptance__glow legal-acceptance__glow--a" aria-hidden />
      <div className="legal-acceptance__glow legal-acceptance__glow--b" aria-hidden />

      <motion.div
        className="legal-acceptance__card"
        initial={{ opacity: 0, y: reduceMotion ? 0 : 12 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: reduceMotion ? 0.12 : 0.55, delay: reduceMotion ? 0 : 0.06 }}
      >
        <h2 className="legal-acceptance__title">Términos y Privacidad</h2>

        <p className="legal-acceptance__lead">
          Antes de continuar, revisa nuestros documentos legales. Marca la casilla para aceptar.
        </p>

        <div className="legal-acceptance__links">
          <a
            href="#"
            className="legal-acceptance__link"
            onClick={(e) => {
              e.preventDefault()
              window.desktop?.openUrl(
                'https://raw.githubusercontent.com/nordik-ia/dot/main/docs/legal/TERMS-OF-SERVICE.md',
              )
            }}
          >
            Términos de Servicio
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round">
              <path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6" />
              <polyline points="15 3 21 3 21 9" />
              <line x1="10" y1="14" x2="21" y2="3" />
            </svg>
          </a>
          <a
            href="#"
            className="legal-acceptance__link"
            onClick={(e) => {
              e.preventDefault()
              window.desktop?.openUrl(
                'https://raw.githubusercontent.com/nordik-ia/dot/main/docs/legal/PRIVACY-POLICY.md',
              )
            }}
          >
            Política de Privacidad
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round">
              <path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6" />
              <polyline points="15 3 21 3 21 9" />
              <line x1="10" y1="14" x2="21" y2="3" />
            </svg>
          </a>
        </div>

        <label className="legal-acceptance__checkbox-label">
          <input
            type="checkbox"
            className="legal-acceptance__checkbox"
            checked={checked}
            onChange={(e) => setChecked(e.target.checked)}
          />
          <span className="legal-acceptance__checkbox-text">
            Acepto los Términos de Servicio y la Política de Privacidad
          </span>
        </label>

        <div
          className={
            onBack
              ? 'legal-acceptance__footer'
              : 'legal-acceptance__footer legal-acceptance__footer--no-back'
          }
        >
          {onBack ? (
            <button type="button" className="legal-acceptance__back" onClick={onBack}>
              ← Retroceder
            </button>
          ) : null}
          <button
            type="button"
            className="legal-acceptance__continue"
            disabled={!checked || saving}
            onClick={() => void handleContinue()}
          >
            {saving ? 'Guardando…' : 'Continuar'}
          </button>
        </div>
      </motion.div>
    </motion.section>
  )
}
