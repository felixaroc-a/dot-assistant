import { motion, useReducedMotion } from 'framer-motion'
import { useState } from 'react'

import './preferred-name-step.css'

export type PreferredNameStepProps = {
  initialName?: string
  onComplete: (displayName: string) => void | Promise<void>
  onBack?: () => void
}

export function PreferredNameStep({ initialName = '', onComplete, onBack }: PreferredNameStepProps) {
  const reduceMotion = useReducedMotion()
  const easing = reduceMotion ? 'linear' : ([0.16, 1, 0.3, 1] as const)
  const [value, setValue] = useState(initialName)
  const [saving, setSaving] = useState(false)
  const [saveError, setSaveError] = useState<string | null>(null)

  async function handleContinue() {
    const name = value.trim()
    if (!name || saving) return
    setSaving(true)
    setSaveError(null)
    try {
      await Promise.resolve(onComplete(name))
    } catch (e) {
      setSaveError(e instanceof Error ? e.message : 'No se pudo completar el paso.')
    } finally {
      setSaving(false)
    }
  }

  return (
    <motion.section
      className="preferred-name"
      initial={{ opacity: 0, filter: reduceMotion ? 'blur(0px)' : 'blur(8px)' }}
      animate={{ opacity: 1, filter: 'blur(0px)' }}
      exit={{ opacity: 0, filter: reduceMotion ? 'blur(0px)' : 'blur(8px)' }}
      transition={{ duration: reduceMotion ? 0.12 : 0.55, ease: easing }}
    >
      <div className="preferred-name__grain" aria-hidden />
      <div className="preferred-name__glow preferred-name__glow--a" aria-hidden />
      <div className="preferred-name__glow preferred-name__glow--b" aria-hidden />

      <motion.div
        className="preferred-name__card"
        initial={{ opacity: 0, y: reduceMotion ? 0 : 12 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: reduceMotion ? 0.12 : 0.55, delay: reduceMotion ? 0 : 0.06 }}
      >
        <h2 className="preferred-name__title">¿Cómo te gustaría ser llamado?</h2>
        <label className="preferred-name__visually-hidden" htmlFor="preferred-display-name">
          Nombre preferido
        </label>
        <input
          id="preferred-display-name"
          type="text"
          className="preferred-name__field"
          value={value}
          onChange={(e) => setValue(e.target.value)}
          placeholder="Tu nombre"
          autoComplete="name"
        />
        {saveError ? (
          <p className="preferred-name__error" role="alert">
            {saveError}
          </p>
        ) : null}
        <div
          className={
            onBack
              ? 'preferred-name__footer'
              : 'preferred-name__footer preferred-name__footer--no-back'
          }
        >
          {onBack ? (
            <button type="button" className="preferred-name__back" onClick={onBack}>
              ← Retroceder
            </button>
          ) : null}
          <button
            type="button"
            className="preferred-name__continue"
            disabled={value.trim().length === 0 || saving}
            onClick={() => void handleContinue()}
          >
            {saving ? 'Guardando…' : 'Continuar'}
          </button>
        </div>
      </motion.div>
    </motion.section>
  )
}
