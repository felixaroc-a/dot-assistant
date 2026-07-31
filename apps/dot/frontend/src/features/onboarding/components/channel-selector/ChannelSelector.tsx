import { motion, useReducedMotion } from 'framer-motion'

import { CHANNEL_META } from '@/features/onboarding/model/channel.meta'
import type { ChannelId } from '@/features/onboarding/model/channel.types'

import './channel-selector.css'

export type ChannelSelectorProps = {
  selected: ChannelId | null
  onSelectedChange: (channel: ChannelId | null) => void
  onBack?: () => void
  onSkip: () => void
  onContinue: () => void
}

export function ChannelSelector({
  selected,
  onSelectedChange,
  onBack,
  onSkip,
  onContinue,
}: ChannelSelectorProps) {
  const reduceMotion = useReducedMotion()

  const easing = reduceMotion ? 'linear' : ([0.16, 1, 0.3, 1] as const)

  return (
    <motion.section
      className="channel"
      initial={{ opacity: 0, filter: reduceMotion ? 'blur(0px)' : 'blur(8px)' }}
      animate={{ opacity: 1, filter: 'blur(0px)' }}
      exit={{ opacity: 0, filter: reduceMotion ? 'blur(0px)' : 'blur(8px)' }}
      transition={{ duration: reduceMotion ? 0.12 : 0.55, ease: easing }}
    >
      <div className="channel__grain" aria-hidden />
      <div className="channel__glow channel__glow--a" aria-hidden />
      <div className="channel__glow channel__glow--b" aria-hidden />

      <motion.div
        className="channel__content"
        initial={{ opacity: 0, y: reduceMotion ? 0 : 14 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: reduceMotion ? 0.12 : 0.55, delay: reduceMotion ? 0 : 0.08 }}
      >
        <motion.h2
          className="channel__title"
          initial={{ opacity: 0, y: reduceMotion ? 0 : 10 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: reduceMotion ? 0.12 : 0.55, delay: reduceMotion ? 0 : 0.14 }}
        >
          ¿A través de cuál le gustaría comunicarse con la IA?
        </motion.h2>

        <div className="channel__grid channel__grid--single" role="radiogroup" aria-label="Canal de mensajería">
          {CHANNEL_META.filter((c) => c.id === 'whatsapp').map((channel, index) => {
            const isActive = selected === channel.id

            return (
              <motion.button
                key={channel.id}
                type="button"
                className={`channel-card ${isActive ? 'channel-card--active' : ''}`}
                role="radio"
                aria-checked={isActive}
                aria-label={`${channel.name}, vía mensajes`}
                onClick={() => onSelectedChange(channel.id)}
                initial={{ opacity: 0, y: reduceMotion ? 0 : 16 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{
                  duration: reduceMotion ? 0.12 : 0.45,
                  delay: reduceMotion ? 0 : 0.2 + index * 0.08,
                  ease: easing,
                }}
              >
                <span className="channel-card__badge" aria-hidden="true">
                  <img
                    src={channel.iconSrc}
                    alt=""
                    width={54}
                    height={54}
                    draggable={false}
                    className="channel-card__badge-img"
                  />
                </span>
                <span className="channel-card__name">{channel.name}</span>
                <span className="channel-card__helper">
                  Grupo «DOT» con @DOT (no chat 1:1)
                </span>
              </motion.button>
            )
          })}
        </div>

        {onBack ? (
          <motion.div
            className="channel__back-row"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            transition={{ duration: reduceMotion ? 0.12 : 0.45, delay: reduceMotion ? 0 : 0.3 }}
          >
            <button type="button" className="channel__back" onClick={onBack}>
              ← Retroceder
            </button>
          </motion.div>
        ) : null}

        <motion.div
          className="channel__actions"
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          transition={{ duration: reduceMotion ? 0.12 : 0.5, delay: reduceMotion ? 0 : 0.36 }}
        >
          <button type="button" className="channel__skip" onClick={onSkip}>
            Omitir (configurar más tarde)
          </button>
          <button
            type="button"
            className="channel__continue"
            disabled={selected === null}
            onClick={onContinue}
          >
            Continuar
          </button>
        </motion.div>
      </motion.div>
    </motion.section>
  )
}
