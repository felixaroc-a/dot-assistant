import { motion, useReducedMotion } from 'framer-motion'

import { PRODUCT_NAME } from '@/shared/constants/brand'

import './welcome-step.css'

export type WelcomeStepProps = {
  onContinue: () => void
}

export function WelcomeStep({ onContinue }: WelcomeStepProps) {
  const reduceMotion = useReducedMotion()
  const easing = reduceMotion ? 'linear' : ([0.16, 1, 0.3, 1] as const)
  const stagger = reduceMotion ? 0 : 0.04
  const blurReveal = reduceMotion ? 'blur(0px)' : 'blur(10px)'

  return (
    <motion.div
      className="welcome-step"
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      exit={{ opacity: 0, filter: reduceMotion ? 'blur(0px)' : 'blur(6px)' }}
      transition={{ duration: reduceMotion ? 0.15 : 0.55, ease: easing }}
    >
      <div className="welcome-step__grain" aria-hidden />
      <div className="welcome-step__glow welcome-step__glow--a" aria-hidden />
      <div className="welcome-step__glow welcome-step__glow--b" aria-hidden />

      <motion.div
        className="welcome-step__pulse welcome-step__pulse--backdrop"
        animate={
          reduceMotion
            ? { opacity: 0.04 }
            : { opacity: [0.02, 0.07, 0.03, 0.06, 0.02] }
        }
        transition={
          reduceMotion
            ? { duration: 0 }
            : { duration: 6.5, repeat: Infinity, ease: 'easeInOut' }
        }
        aria-hidden
      />

      <motion.div
        className="welcome-step__content"
        initial={{ opacity: 0, y: reduceMotion ? 0 : 16 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: reduceMotion ? 0.12 : 0.7, delay: 0.1, ease: easing }}
      >
        {/* DOT Icon / Illustration */}
        <motion.div
          className="welcome-step__icon"
          initial={{ opacity: 0, scale: reduceMotion ? 1 : 0.7 }}
          animate={{ opacity: 1, scale: 1 }}
          transition={{ duration: reduceMotion ? 0.12 : 0.7, delay: 0.05, ease: easing }}
          aria-hidden
        >
          <svg viewBox="0 0 80 80" fill="none" xmlns="http://www.w3.org/2000/svg">
            <circle cx="40" cy="40" r="38" stroke="rgba(255,255,255,0.12)" strokeWidth="2" fill="none" />
            <circle cx="40" cy="40" r="38" stroke="var(--accent-color, #6c8cff)" strokeWidth="2" fill="none" strokeDasharray="239" strokeDashoffset="0" opacity="0.6" />
            <text x="40" y="48" textAnchor="middle" fill="var(--welcome-fg)" fontSize="28" fontWeight="700" letterSpacing="-0.04em" fontFamily="system-ui, sans-serif">.</text>
          </svg>
        </motion.div>

        <motion.h1 className="welcome-step__logo" aria-label={PRODUCT_NAME}>
          {PRODUCT_NAME.split('').map((char, i) => (
            <motion.span
              key={`${char}-${i}`}
              className="welcome-step__char"
              initial={{
                opacity: 0,
                y: reduceMotion ? 0 : 18,
                filter: blurReveal,
              }}
              animate={{
                opacity: 1,
                y: 0,
                filter: 'blur(0px)',
              }}
              transition={{
                duration: reduceMotion ? 0.06 : 0.65,
                delay: reduceMotion ? 0 : 0.3 + i * stagger,
                ease: easing,
              }}
            >
              {char === ' ' ? '\u00A0' : char}
            </motion.span>
          ))}
        </motion.h1>

        <motion.p
          className="welcome-step__tagline"
          initial={{ opacity: 0, y: reduceMotion ? 0 : 8 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.7, delay: reduceMotion ? 0 : 0.8, ease: easing }}
        >
          ¡Bienvenido a DOT! Tu asistente personal
        </motion.p>

        <motion.p
          className="welcome-step__description"
          initial={{ opacity: 0, y: reduceMotion ? 0 : 6 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.65, delay: reduceMotion ? 0 : 1.05, ease: easing }}
        >
          Chat · WhatsApp · Gmail · Automatizaciones · Archivos
        </motion.p>

        <motion.button
          type="button"
          className="welcome-step__cta"
          onClick={onContinue}
          initial={{ opacity: 0, y: reduceMotion ? 0 : 12 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.55, delay: reduceMotion ? 0 : 1.4, ease: easing }}
        >
          Comenzar
          <span className="welcome-step__cta-arrow" aria-hidden>→</span>
        </motion.button>

        <motion.p
          className="welcome-step__step-indicator"
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          transition={{ duration: 0.4, delay: reduceMotion ? 0 : 1.7 }}
        >
          Paso 1 de 4
        </motion.p>
      </motion.div>
    </motion.div>
  )
}
