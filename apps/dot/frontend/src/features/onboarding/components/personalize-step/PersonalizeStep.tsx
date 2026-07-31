import { motion, useReducedMotion } from 'framer-motion'
import { useState } from 'react'
import { useTranslation } from 'react-i18next'

import './personalize-step.css'

type PersonalizeStepProps = {
  initialName?: string
  initialLanguage?: string
  initialWakeWord?: boolean
  onComplete: (opts: { displayName: string; language: string; wakeWord: boolean }) => void | Promise<void>
  onBack?: () => void
}

const LANGUAGES = [
  { value: 'es', label: 'Español' },
  { value: 'en', label: 'English' },
  { value: 'pt', label: 'Português' },
]

export function PersonalizeStep({
  initialName = '',
  initialLanguage = 'es',
  initialWakeWord = true,
  onComplete,
  onBack,
}: PersonalizeStepProps) {
  const reduceMotion = useReducedMotion()
  const easing = reduceMotion ? 'linear' : ([0.16, 1, 0.3, 1] as const)

  const [name, setName] = useState(initialName)
  const [language, setLanguage] = useState(initialLanguage)
  const [wakeWord, setWakeWord] = useState(initialWakeWord)
  const [legalAccepted, setLegalAccepted] = useState(false)
  const [saving, setSaving] = useState(false)
  const [saveError, setSaveError] = useState<string | null>(null)

  async function handleContinue() {
    const trimmed = name.trim()
    if (!trimmed || !legalAccepted || saving) return
    setSaving(true)
    setSaveError(null)
    try {
      await Promise.resolve(
        onComplete({ displayName: trimmed, language, wakeWord }),
      )
    } catch (e) {
      setSaveError(e instanceof Error ? e.message : 'No se pudo completar este paso.')
    } finally {
      setSaving(false)
    }
  }

  return (
    <motion.section
      className="personalize-step"
      initial={{ opacity: 0, filter: reduceMotion ? 'blur(0px)' : 'blur(8px)' }}
      animate={{ opacity: 1, filter: 'blur(0px)' }}
      exit={{ opacity: 0, filter: reduceMotion ? 'blur(0px)' : 'blur(8px)' }}
      transition={{ duration: reduceMotion ? 0.12 : 0.55, ease: easing }}
    >
      <div className="personalize-step__grain" aria-hidden />
      <div className="personalize-step__glow personalize-step__glow--a" aria-hidden />
      <div className="personalize-step__glow personalize-step__glow--b" aria-hidden />

      <motion.div
        className="personalize-step__card"
        initial={{ opacity: 0, y: reduceMotion ? 0 : 12 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: reduceMotion ? 0.12 : 0.55, delay: reduceMotion ? 0 : 0.06 }}
      >
        <h2 className="personalize-step__title">Personaliza tu DOT</h2>

        {/* ── Nombre ── */}
        <div className="personalize-step__field-group">
          <label className="personalize-step__label" htmlFor="personalize-display-name">
            ¿Cómo te llamas?
          </label>
          <input
            id="personalize-display-name"
            type="text"
            className="personalize-step__input"
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="Tu nombre"
            autoComplete="name"
          />
        </div>

        {/* ── Idioma ── */}
        <div className="personalize-step__field-group">
          <label className="personalize-step__label">Idioma preferido</label>
          <div className="personalize-step__lang-options">
            {LANGUAGES.map((lang) => (
              <button
                key={lang.value}
                type="button"
                className={`personalize-step__lang-btn ${language === lang.value ? 'personalize-step__lang-btn--active' : ''}`}
                onClick={() => setLanguage(lang.value)}
              >
                {lang.label}
              </button>
            ))}
          </div>
        </div>

        {/* ── Modo escucha ── */}
        <div className="personalize-step__field-group">
          <label className="personalize-step__label">Modo escucha</label>
          <label className="personalize-step__toggle-label">
            <input
              type="checkbox"
              className="personalize-step__toggle"
              checked={wakeWord}
              onChange={(e) => setWakeWord(e.target.checked)}
            />
            <span className="personalize-step__toggle-track">
              <span className="personalize-step__toggle-knob" />
            </span>
            <span className="personalize-step__toggle-text">
              {wakeWord
                ? 'Iniciar con modo escucha en el chat (habla cuando quieras)'
                : 'Escribe en el chat para comunicarte'}
            </span>
          </label>
        </div>

        {/* ── Legal ── */}
        <div className="personalize-step__field-group">
          <div className="personalize-step__legal-links">
            <a
              href="#"
              className="personalize-step__legal-link"
              onClick={(e) => {
                e.preventDefault()
                window.desktop?.openUrl?.(
                  'https://raw.githubusercontent.com/nordik-ia/dot/main/docs/legal/TERMS-OF-SERVICE.md',
                )
              }}
            >
              Términos de Servicio
              <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round">
                <path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6" />
                <polyline points="15 3 21 3 21 9" />
                <line x1="10" y1="14" x2="21" y2="3" />
              </svg>
            </a>
            <a
              href="#"
              className="personalize-step__legal-link"
              onClick={(e) => {
                e.preventDefault()
                window.desktop?.openUrl?.(
                  'https://raw.githubusercontent.com/nordik-ia/dot/main/docs/legal/PRIVACY-POLICY.md',
                )
              }}
            >
              Política de Privacidad
              <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round">
                <path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6" />
                <polyline points="15 3 21 3 21 9" />
                <line x1="10" y1="14" x2="21" y2="3" />
              </svg>
            </a>
          </div>
          <label className="personalize-step__checkbox-label">
            <input
              type="checkbox"
              className="personalize-step__checkbox"
              checked={legalAccepted}
              onChange={(e) => setLegalAccepted(e.target.checked)}
            />
            <span className="personalize-step__checkbox-text">
              Acepto los Términos de Servicio y la Política de Privacidad
            </span>
          </label>
        </div>

        {saveError ? (
          <p className="personalize-step__error" role="alert">
            {saveError}
          </p>
        ) : null}

        <div
          className={
            onBack
              ? 'personalize-step__footer'
              : 'personalize-step__footer personalize-step__footer--no-back'
          }
        >
          {onBack ? (
            <button type="button" className="personalize-step__back" onClick={onBack}>
              ← Retroceder
            </button>
          ) : null}
          <button
            type="button"
            className="personalize-step__continue"
            disabled={name.trim().length === 0 || !legalAccepted || saving}
            onClick={() => void handleContinue()}
          >
            {saving ? 'Guardando…' : 'Continuar'}
          </button>
        </div>
      </motion.div>
    </motion.section>
  )
}
