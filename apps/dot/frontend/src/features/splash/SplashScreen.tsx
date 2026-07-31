import { useEffect } from 'react'
import { motion, useReducedMotion } from 'framer-motion'

import {
  APPLE_EASE,
  SPLASH_BOUNCE_UP_EASE,
  SPLASH_DROP_EASE,
  SPLASH_EXIT_START_S,
  SPLASH_FADE_S,
  SPLASH_FALL_BOUNCE_S,
  SPLASH_FALL_EASE,
  SPLASH_IA_IN_S,
  SPLASH_IA_START_S,
  SPLASH_LETTERS_IN_S,
  SPLASH_LOGO_START_S,
  SPLASH_SPHERE_DROP_SCALE,
  SPLASH_SPHERE_FINAL_SCALE,
  SPLASH_SPHERE_IMPACT_SCALE,
} from './splash-timings'
import { useSplashProgress } from './useSplashProgress'

import './splash.css'

export type SplashScreenProps = {
  onComplete: () => void
}

/** Caída → impacto → rebote → asentamiento (más puntos = interpolación más fluida). */
const BOUNCE_Y = [
  '-44vh',
  '-11vh',
  '2.2vh',
  '-14.5vh',
  '-4.2vh',
  '1.1vh',
  '-0.55vh',
  '0.22vh',
  '-0.08vh',
  '0',
  '0',
] as const
const BOUNCE_TIMES = [0, 0.14, 0.27, 0.4, 0.52, 0.64, 0.76, 0.86, 0.94, 0.98, 1] as const
const BOUNCE_EASE = [
  SPLASH_FALL_EASE,
  SPLASH_DROP_EASE,
  SPLASH_BOUNCE_UP_EASE,
  SPLASH_DROP_EASE,
  SPLASH_BOUNCE_UP_EASE,
  SPLASH_DROP_EASE,
  SPLASH_BOUNCE_UP_EASE,
  SPLASH_DROP_EASE,
  SPLASH_BOUNCE_UP_EASE,
  'linear',
] as const

/** Escala converge al tamaño wordmark (~0.9em) antes del asentamiento y de D/T. */
const SPHERE_SCALE_DURATION_S = SPLASH_FALL_BOUNCE_S
const SPHERE_SCALE_TIMES = [0, 0.18, 0.32, 0.44, 0.56, 1] as const
const SPHERE_SCALE_EASE = [
  SPLASH_FALL_EASE,
  SPLASH_DROP_EASE,
  APPLE_EASE,
  APPLE_EASE,
  'linear',
] as const

export function SplashScreen({ onComplete }: SplashScreenProps) {
  const reduceMotion = useReducedMotion()
  const isReduced = reduceMotion === true

  useSplashProgress(onComplete, { reduced: isReduced })

  useEffect(() => {
    document.title = 'DOT'
  }, [])

  if (isReduced) {
    return (
      <motion.div
        className="splash"
        initial={{ opacity: 1 }}
        animate={{ opacity: 0 }}
        transition={{ delay: 0.9, duration: 0.3, ease: 'easeInOut' }}
      >
        <div className="splash__grain" aria-hidden />
        <div className="splash__stage">
          <div className="splash__brand">
            <h1 className="splash__wordmark" aria-label="DOT">
              <span className="splash__letter">D</span>
              <span className="splash__letter-o-wrap">
                <span className="splash__sphere splash__sphere--static" aria-hidden />
              </span>
              <span className="splash__letter">T</span>
            </h1>
            <p className="splash__subline splash__ia" aria-hidden>
              IA
            </p>
          </div>
        </div>
      </motion.div>
    )
  }

  return (
    <motion.div
      className="splash"
      initial={{ opacity: 1 }}
      animate={{ opacity: 0 }}
      transition={{
        delay: SPLASH_EXIT_START_S,
        duration: SPLASH_FADE_S,
        ease: [0.4, 0, 0.2, 1],
      }}
    >
      <div className="splash__grain" aria-hidden />
      <div className="splash__vignette" aria-hidden />

      <div className="splash__stage">
        <div className="splash__brand">
          <h1 className="splash__wordmark" aria-label="DOT IA">
            <motion.span
              className="splash__letter splash__letter--d"
              initial={{ opacity: 0, x: -28, filter: 'blur(10px)' }}
              animate={{
                opacity: [0, 0, 1],
                x: [0, 0, 0],
                filter: ['blur(10px)', 'blur(10px)', 'blur(0px)'],
              }}
              transition={{
                type: 'tween',
                delay: SPLASH_LOGO_START_S,
                duration: SPLASH_LETTERS_IN_S,
                ease: APPLE_EASE,
                times: [0, 0.08, 1],
              }}
            >
              D
            </motion.span>

            <motion.span
              className="splash__letter-o-wrap"
              layout={false}
              initial={{ y: '-44vh' }}
              animate={{ y: [...BOUNCE_Y] }}
              transition={{
                type: 'tween',
                duration: SPLASH_FALL_BOUNCE_S,
                times: [...BOUNCE_TIMES],
                ease: [...BOUNCE_EASE],
              }}
            >
              <motion.span
                className="splash__sphere"
                layout={false}
                aria-hidden
                initial={{
                  opacity: 0,
                  scale: SPLASH_SPHERE_DROP_SCALE,
                  boxShadow: '0 0 0px rgba(255, 255, 255, 0)',
                }}
                animate={{
                  opacity: [0, 1, 1, 1, 1, 1],
                  scale: [
                    SPLASH_SPHERE_DROP_SCALE,
                    SPLASH_SPHERE_IMPACT_SCALE,
                    1.02,
                    SPLASH_SPHERE_FINAL_SCALE,
                    SPLASH_SPHERE_FINAL_SCALE,
                    SPLASH_SPHERE_FINAL_SCALE,
                  ],
                  boxShadow: [
                    '0 0 0px rgba(255, 255, 255, 0)',
                    '0 0 72px rgba(255, 255, 255, 0.48)',
                    '0 0 36px rgba(255, 255, 255, 0.28)',
                    '0 0 22px rgba(255, 255, 255, 0.16)',
                    '0 0 22px rgba(255, 255, 255, 0.16)',
                    '0 0 22px rgba(255, 255, 255, 0.16)',
                  ],
                }}
                transition={{
                  opacity: {
                    type: 'tween',
                    duration: SPLASH_FALL_BOUNCE_S * 0.14,
                    ease: 'easeOut',
                  },
                  scale: {
                    type: 'tween',
                    duration: SPHERE_SCALE_DURATION_S,
                    times: [...SPHERE_SCALE_TIMES],
                    ease: [...SPHERE_SCALE_EASE],
                  },
                  boxShadow: {
                    type: 'tween',
                    duration: SPHERE_SCALE_DURATION_S,
                    times: [...SPHERE_SCALE_TIMES],
                    ease: [...SPHERE_SCALE_EASE],
                  },
                }}
              />
            </motion.span>

            <motion.span
              className="splash__letter splash__letter--t"
              initial={{ opacity: 0, x: 28, filter: 'blur(10px)' }}
              animate={{
                opacity: [0, 0, 1],
                x: [0, 0, 0],
                filter: ['blur(10px)', 'blur(10px)', 'blur(0px)'],
              }}
              transition={{
                type: 'tween',
                delay: SPLASH_LOGO_START_S,
                duration: SPLASH_LETTERS_IN_S,
                ease: APPLE_EASE,
                times: [0, 0.08, 1],
              }}
            >
              T
            </motion.span>
          </h1>

          <motion.p
            className="splash__subline splash__ia"
            aria-hidden
            initial={{ opacity: 0, y: 18, filter: 'blur(10px)' }}
            animate={{
              opacity: [0, 0, 1],
              y: [18, 18, 0],
              filter: ['blur(10px)', 'blur(10px)', 'blur(0px)'],
            }}
            transition={{
              delay: SPLASH_IA_START_S,
              duration: SPLASH_IA_IN_S,
              ease: APPLE_EASE,
              times: [0, 0.12, 1],
            }}
          >
            IA
          </motion.p>
        </div>
      </div>
    </motion.div>
  )
}
