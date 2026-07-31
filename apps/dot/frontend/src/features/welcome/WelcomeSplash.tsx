import { motion, useReducedMotion } from 'framer-motion'

import { PRODUCT_NAME } from '@/shared/constants/brand'

import './welcome.css'

export function WelcomeSplash() {
  const reduceMotion = useReducedMotion()

  const easing = reduceMotion ? 'linear' : ([0.16, 1, 0.3, 1] as const)
  const stagger = reduceMotion ? 0 : 0.045
  const blurReveal = reduceMotion ? 'blur(0px)' : 'blur(10px)'

  return (
    <div className="welcome">
      <div className="welcome__grain" aria-hidden />
      <div className="welcome__glow welcome__glow--a" aria-hidden />
      <div className="welcome__glow welcome__glow--b" aria-hidden />

      <motion.div
        className="welcome__pulse welcome__pulse--backdrop"
        animate={
          reduceMotion
            ? { opacity: 0.06 }
            : { opacity: [0.03, 0.09, 0.035, 0.08, 0.04] }
        }
        transition={
          reduceMotion
            ? { duration: 0 }
            : { duration: 6.5, repeat: Infinity, ease: 'easeInOut' }
        }
        aria-hidden
      />

      <motion.div
        initial={{ opacity: 0 }}
        animate={{ opacity: 1 }}
        exit={{ opacity: 0, filter: reduceMotion ? 'blur(0px)' : 'blur(6px)' }}
        transition={{ duration: reduceMotion ? 0.2 : 0.9, ease: easing }}
        className="welcome__content"
      >
        <motion.div
          className="welcome__rule welcome__rule--accent"
          initial={{ scaleX: 0 }}
          animate={{ scaleX: 1 }}
          transition={{
            duration: reduceMotion ? 0.05 : 1.15,
            delay: reduceMotion ? 0 : 0.15,
            ease: easing,
          }}
        />

        {import.meta.env.DEV ? (
          <motion.span
            className="welcome__eyebrow"
            initial={{ opacity: 0, y: reduceMotion ? 0 : 6 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.6, delay: reduceMotion ? 0 : 0.35, ease: easing }}
          >
            Mesa de trabajo · build local
          </motion.span>
        ) : null}

        <motion.h1 className="welcome__title" aria-label={PRODUCT_NAME}>
          {PRODUCT_NAME.split('').map((char, i) => (
            <motion.span
              key={`${char}-${i}`}
              className="welcome__char"
              initial={{
                opacity: 0,
                y: reduceMotion ? 0 : 22,
                filter: blurReveal,
              }}
              animate={{
                opacity: 1,
                y: 0,
                filter: 'blur(0px)',
              }}
              transition={{
                duration: reduceMotion ? 0.08 : 0.78,
                delay: reduceMotion ? 0 : 0.45 + i * stagger,
                ease: easing,
              }}
            >
              {char === ' ' ? '\u00A0' : char}
            </motion.span>
          ))}
        </motion.h1>

        <motion.p
          className="welcome__subtitle"
          initial={{ opacity: 0, y: reduceMotion ? 0 : 10 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.85, delay: reduceMotion ? 0 : 0.95, ease: easing }}
        >
          Oscuro minimal, alto contraste, sin ruido. Empezamos por aquí.
        </motion.p>

        <motion.div
          className="welcome__rule welcome__rule--wide"
          initial={{ scaleX: 0 }}
          animate={{ scaleX: 1 }}
          transition={{
            duration: reduceMotion ? 0.08 : 1.25,
            delay: reduceMotion ? 0 : 1.05,
            ease: easing,
          }}
        />

        <motion.footer
          className="welcome__footer"
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          transition={{
            duration: reduceMotion ? 0.05 : 0.85,
            delay: reduceMotion ? 0 : 1.65,
          }}
        >
          <span className="welcome__pulse-dot" aria-hidden />
          <span>Listo cuando tú lo estés</span>
        </motion.footer>
      </motion.div>
    </div>
  )
}
