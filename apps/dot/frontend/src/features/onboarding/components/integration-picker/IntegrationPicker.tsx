import { motion, useReducedMotion } from 'framer-motion'

import type { IntegrationId } from '@/features/integrations'
import { INTEGRATION_META } from '@/features/integrations'

import './integration-selector.css'

export type IntegrationPickerProps = {
  selected: IntegrationId[]
  onSelectedChange: (ids: IntegrationId[]) => void
  onBack?: () => void
  onSkip?: () => void
  onComplete?: (selected: IntegrationId[]) => void
}

export function IntegrationPicker({
  selected,
  onSelectedChange,
  onBack,
  onSkip,
  onComplete,
}: IntegrationPickerProps) {
  const reduceMotion = useReducedMotion()

  const easing = reduceMotion ? 'linear' : ([0.16, 1, 0.3, 1] as const)

  function toggle(id: IntegrationId) {
    onSelectedChange(
      selected.includes(id)
        ? selected.filter((x) => x !== id)
        : [...selected, id],
    )
  }

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
          <h2 className="integration-step__title">¿Qué quieres automatizar?</h2>
          <p className="integration-step__subtitle">
            Elige una o más automatizaciones.
          </p>
        </header>

        <div className="integration-step__grid" role="group" aria-label="Integraciones seleccionables">
          {INTEGRATION_META.map((integration, index) => {
            const active = selected.includes(integration.id)
            return (
              <motion.button
                key={integration.id}
                type="button"
                className={`integration-step__tile ${active ? 'integration-step__tile--active' : ''}`}
                role="checkbox"
                aria-checked={active}
                onClick={() => toggle(integration.id)}
                initial={{ opacity: 0, y: reduceMotion ? 0 : 10 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{
                  duration: reduceMotion ? 0.08 : 0.35,
                  delay: reduceMotion ? 0 : 0.15 + index * 0.05,
                  ease: easing,
                }}
              >
                <span className="integration-step__icon" aria-hidden>
                  {integration.logoSrc ? (
                    <img
                      src={integration.logoSrc}
                      alt=""
                      className="integration-step__img"
                      draggable={false}
                    />
                  ) : (
                    <span className="integration-step__placeholder">3</span>
                  )}
                </span>
                <span className="integration-step__label">{integration.label}</span>
              </motion.button>
            )
          })}
        </div>

        <footer
          className={
            onBack
              ? 'integration-step__footer'
              : 'integration-step__footer integration-step__footer--no-back'
          }
        >
          {onBack ? (
            <button type="button" className="integration-step__back" onClick={onBack}>
              ← Retroceder
            </button>
          ) : null}
          <div className="integration-step__footer-right">
            <button type="button" className="integration-step__omit" onClick={() => onSkip?.()}>
              Omitir (configurar más tarde) <span aria-hidden>→</span>
            </button>
            <button
              type="button"
              className="integration-step__continue"
              disabled={selected.length === 0}
              onClick={() => onComplete?.(selected)}
            >
              Continuar
            </button>
          </div>
        </footer>
      </motion.div>
    </motion.section>
  )
}
