import { motion, useReducedMotion } from 'framer-motion'
import { useCallback, useEffect, useRef, useState } from 'react'

import './completion-splash.css'

const AUTO_ADVANCE_MS = 3200
const SKIP_VISIBLE_MS = 600

type TutorialCard = {
  title: string
  description: string
  icon: string
}

const TUTORIAL_CARDS: TutorialCard[] = [
  {
    icon: '📋',
    title: 'Di "plan: hacer X"',
    description: 'para que DOT planifique por ti paso a paso.',
  },
  {
    icon: '🎤',
    title: 'Modo escucha',
    description: 'para hablar con DOT sin escribir. Pulsa el botón de ondas en el chat.',
  },
  {
    icon: '🧠',
    title: 'DOT recuerda lo que le dices',
    description: 'Prueba decirle tu nombre o datos importantes.',
  },
  {
    icon: '🔔',
    title: 'Di «avísame cuando…»',
    description: 'DOT vigila tus mandatos. Actívalo o apágalo en Configuración → Notificaciones.',
  },
  {
    icon: '📅',
    title: 'Conecta tu calendario de Google',
    description: 'para que DOT te recuerde tus citas y eventos.',
  },
  {
    icon: '💬',
    title: 'WhatsApp: grupo «DOT»',
    description:
      'Tras vincular, crea un grupo llamado «DOT» (solo tú) y menciona @DOT. No responde en chats 1:1.',
  },
]

export type CompletionSplashProps = {
  onComplete: () => void
}

export function CompletionSplash({ onComplete }: CompletionSplashProps) {
  const reduceMotion = useReducedMotion()
  const easing = reduceMotion ? 'linear' : ([0.16, 1, 0.3, 1] as const)
  const onCompleteRef = useRef(onComplete)
  const timerRef = useRef<number | null>(null)
  onCompleteRef.current = onComplete
  const [skipVisible, setSkipVisible] = useState(false)

  const advance = useCallback(() => {
    if (timerRef.current !== null) {
      window.clearTimeout(timerRef.current)
      timerRef.current = null
    }
    onCompleteRef.current()
  }, [])

  useEffect(() => {
    const skipTimer = window.setTimeout(() => setSkipVisible(true), SKIP_VISIBLE_MS)
    const delay = reduceMotion ? 1200 : AUTO_ADVANCE_MS
    timerRef.current = window.setTimeout(advance, delay)
    return () => {
      window.clearTimeout(skipTimer)
      if (timerRef.current !== null) window.clearTimeout(timerRef.current)
    }
  }, [reduceMotion, advance])

  return (
    <motion.div
      className="completion-splash"
      initial={{ opacity: 0, filter: reduceMotion ? 'blur(0px)' : 'blur(10px)' }}
      animate={{ opacity: 1, filter: 'blur(0px)' }}
      exit={{ opacity: 0, filter: reduceMotion ? 'blur(0px)' : 'blur(8px)' }}
      transition={{ duration: reduceMotion ? 0.2 : 0.9, ease: easing }}
    >
      <div className="completion-splash__grain" aria-hidden />
      <div className="completion-splash__glow completion-splash__glow--a" aria-hidden />
      <div className="completion-splash__glow completion-splash__glow--b" aria-hidden />

      {/* Checkmark animado */}
      <motion.svg
        className="completion-splash__checkmark"
        viewBox="0 0 52 52"
        xmlns="http://www.w3.org/2000/svg"
        initial={{ opacity: 0, scale: reduceMotion ? 1 : 0.6 }}
        animate={{ opacity: 1, scale: 1 }}
        transition={{ duration: reduceMotion ? 0.1 : 0.55, delay: 0.05, ease: easing }}
      >
        <motion.circle
          cx="26" cy="26" r="25"
          fill="none"
          stroke="rgba(255,255,255,0.14)"
          strokeWidth="2"
          initial={{ pathLength: 0 }}
          animate={{ pathLength: 1 }}
          transition={{ duration: reduceMotion ? 0.05 : 0.6, delay: 0.1, ease: 'easeOut' }}
        />
        <motion.path
          d="M14 27l7 7 16-16"
          fill="none"
          stroke="var(--accent-color, #6c8cff)"
          strokeWidth="2.5"
          strokeLinecap="round"
          strokeLinejoin="round"
          initial={{ pathLength: 0, opacity: 0 }}
          animate={{ pathLength: 1, opacity: 1 }}
          transition={{ duration: reduceMotion ? 0.05 : 0.55, delay: 0.35, ease: 'easeOut' }}
        />
      </motion.svg>

      <motion.div
        className="completion-splash__content"
        initial={{ opacity: 0, y: reduceMotion ? 0 : 14 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: reduceMotion ? 0.12 : 0.75, delay: reduceMotion ? 0 : 0.2, ease: easing }}
      >
        <h1 className="completion-splash__title">¡Listo! DOT está configurado</h1>
        <p className="completion-splash__subtitle">Consejos rápidos para comenzar</p>
      </motion.div>

      {/* Tutorial cards */}
      <motion.div
        className="completion-splash__cards"
        initial={{ opacity: 0, y: reduceMotion ? 0 : 10 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.55, delay: reduceMotion ? 0 : 0.4, ease: easing }}
      >
        {TUTORIAL_CARDS.map((card, i) => (
          <div key={i} className="completion-splash__card">
            <span className="completion-splash__card-icon" aria-hidden>{card.icon}</span>
            <div className="completion-splash__card-body">
              <p className="completion-splash__card-title">{card.title}</p>
              <p className="completion-splash__card-desc">{card.description}</p>
            </div>
          </div>
        ))}
      </motion.div>

      <motion.button
        type="button"
        className="completion-splash__skip"
        onClick={advance}
        aria-label="Ir al chat"
        initial={{ opacity: 0, y: reduceMotion ? 0 : 8 }}
        animate={{ opacity: skipVisible ? 1 : 0, y: 0 }}
        transition={{ duration: 0.3, ease: 'easeOut' }}
        tabIndex={skipVisible ? 0 : -1}
      >
        Ir al chat →
      </motion.button>
    </motion.div>
  )
}
