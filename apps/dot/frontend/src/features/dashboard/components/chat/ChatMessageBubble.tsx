import { useCallback, useState } from 'react'
import { motion, useReducedMotion } from 'framer-motion'
import { useTranslation } from 'react-i18next'

import dotAvatar from '@/assets/dot-avatar.svg'
import type { ChatMessage } from '@/lib/chat/types'
import { needsGoogleDriveReconnectNudge } from '@/lib/chat-nudges'
import { GOOGLE_INTEGRATIONS_PATH } from '@/lib/api/google-oauth'
import { classifyAssistantMessage } from './classifyAssistantMessage'
import { resolveUserMessageDisplay } from './documentMessageDisplay'
import { FileAttachment } from './FileAttachment'
import { GeneratedImagesGrid } from './GeneratedImagesGrid'
import { StructuredMessageCard } from './StructuredMessageCard'
import { MessageBubbleActions } from './MessageBubbleActions'
import { ReasoningThinkingPanel } from './ReasoningThinkingPanel'
import { extractMessageActionText } from './messageActionText'

type ChatMessageBubbleProps = {
  message: ChatMessage
  voiceTtsAvailable?: boolean
  ttsLoading?: boolean
  onTextToSpeech?: (text: string, messageId: string) => void
  onOpenGoogleIntegrations?: () => void
  onTranslateText?: (text: string) => Promise<void>
  onSummarizeText?: (text: string) => Promise<void>
}

export function ChatMessageBubble({
  message,
  voiceTtsAvailable = false,
  ttsLoading = false,
  onTextToSpeech,
  onOpenGoogleIntegrations,
  onTranslateText,
  onSummarizeText,
}: ChatMessageBubbleProps) {
  const { t } = useTranslation()
  const reduceMotion = useReducedMotion()
  const [textActionLoading, setTextActionLoading] = useState(false)
  const isStreaming = message.role === 'assistant' && message.status === 'sending'
  const isUser = message.role === 'user'
  const isThinking = message.role === 'assistant' && message.text.startsWith('⏳')

  const userDisplay = isUser ? resolveUserMessageDisplay(message) : null
  // Última capa de defensa: limpiar cualquier resto de MEMORY_UPDATE
  const displayText = isUser
    ? (userDisplay?.text ?? '')
    : message.text.replace(/--MEMORY[\s\S]*?(?:\}--|$)/g, '')
  const displayAttachment = isUser ? userDisplay?.attachment : message.attachment
  const structured = !isUser && !isStreaming && !isThinking
    ? classifyAssistantMessage(displayText)
    : null
  const showGoogleReconnectNudge =
    !isUser &&
    !isStreaming &&
    !isThinking &&
    Boolean(onOpenGoogleIntegrations) &&
    needsGoogleDriveReconnectNudge(displayText)

  const actionText =
    !isStreaming && !isThinking ? extractMessageActionText(message) : null

  const runTextAction = useCallback(
    async (fn: ((text: string) => Promise<void>) | undefined, text: string) => {
      if (!fn) return
      setTextActionLoading(true)
      try {
        await fn(text)
      } finally {
        setTextActionLoading(false)
      }
    },
    [],
  )

  const textActions =
    actionText && (onTranslateText || onSummarizeText) ? (
      <MessageBubbleActions
        text={actionText}
        loading={textActionLoading}
        onTranslate={
          onTranslateText
            ? (text) => {
                void runTextAction(onTranslateText, text)
              }
            : undefined
        }
        onSummarize={
          onSummarizeText
            ? (text) => {
                void runTextAction(onSummarizeText, text)
              }
            : undefined
        }
      />
    ) : null

  const bubble = structured ? (
    <StructuredMessageCard card={structured} fallbackText={displayText} />
  ) : (
    <p
      className={`dot-chat__bubble dot-chat__bubble--${isUser ? 'user' : 'agent'}${isStreaming && message.text ? ' dot-chat__bubble--streaming' : ''}`}
      data-thinking={isThinking ? 'true' : undefined}
    >
      {displayText || (isStreaming ? ' ' : '')}
    </p>
  )

  if (isUser) {
    return (
      <motion.div
        className={`dot-chat__row dot-chat__row--user${message.status === 'error' ? ' dot-chat__row--error' : ''}`}
        initial={reduceMotion ? false : { opacity: 0, y: 8, scale: 0.98 }}
        animate={{ opacity: 1, y: 0, scale: 1 }}
        transition={{ duration: 0.22, ease: [0.25, 0.1, 0.25, 1] }}
      >
        <>
          {bubble}
          {displayAttachment ? <FileAttachment attachment={displayAttachment} isUser /> : null}
          {textActions}
        </>
        {message.status === 'error' ? (
          <span className="dot-chat__status-badge">No enviado</span>
        ) : null}
      </motion.div>
    )
  }

  return (
    <motion.div
      className="dot-chat__row dot-chat__row--agent"
      initial={reduceMotion ? false : { opacity: 0, y: 8, scale: 0.98 }}
      animate={{ opacity: 1, y: 0, scale: 1 }}
      transition={{ duration: 0.22, ease: [0.25, 0.1, 0.25, 1] }}
    >
      <div className="dot-chat__agent-block">
        {message.reasoningActive || message.reasoningPlan ? (
          <ReasoningThinkingPanel
            phase={message.reasoningPhase}
            level={message.reasoningLevel || message.reasoningPlan?.level}
            plan={message.reasoningPlan}
            toolActivity={message.reasoningToolActivity}
            live={isStreaming}
          />
        ) : null}
        <div className="dot-chat__agent-meta">
          <img className="dot-chat__avatar" src={dotAvatar} alt="" width={24} height={24} />
          <span className="dot-chat__agent-name">DOT</span>
          {voiceTtsAvailable && onTextToSpeech && !isStreaming && !isThinking && displayText ? (
            <button
              type="button"
              className="dot-chat__tts-btn"
              title={t('voice.speak_listen')}
              aria-label={t('voice.speak_listen')}
              disabled={ttsLoading}
              onClick={() => onTextToSpeech(displayText, message.id)}
            >
              {ttsLoading ? '⏳' : '🔊'}
            </button>
          ) : null}
        </div>
        <>
          {message.text ? (
            bubble
          ) : isStreaming && !message.reasoningActive ? (
            <div className="dot-chat__typing-indicator" aria-label="DOT está escribiendo">
              <span className="dot-chat__dot" />
              <span className="dot-chat__dot" />
              <span className="dot-chat__dot" />
            </div>
          ) : null}
          {displayAttachment ? <FileAttachment attachment={displayAttachment} /> : null}
          {message.generatedImages?.length ? (
            <GeneratedImagesGrid images={message.generatedImages} />
          ) : null}
          {showGoogleReconnectNudge ? (
            <button
              type="button"
              className="dot-chat__struct-card-details-btn"
              onClick={onOpenGoogleIntegrations}
            >
              Abrir {GOOGLE_INTEGRATIONS_PATH}
            </button>
          ) : null}
          {textActions}
          {message.memoryRecall ? (
            <p className="dot-chat__memory-recall" aria-label="Memoria usada">
              {message.memoryRecall}
            </p>
          ) : null}
        </>
      </div>
    </motion.div>
  )
}
