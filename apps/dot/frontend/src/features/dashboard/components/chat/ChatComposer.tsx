import { useCallback, useEffect, useRef } from 'react'
import { useTranslation } from 'react-i18next'

import { useVoiceInput } from '../../hooks/useVoiceInput'
import type { WakeWordState } from '../../hooks/useWakeWord'
import { isVoiceServiceUnavailableMessage } from '@/lib/api/voice'
import { AttachmentImagePicker, AttachmentPicker } from './AttachmentPicker'
import { IconMic } from './ChatToolbarIcons'
import { ReasoningModeControl } from './ReasoningModeControl'
import type { ReasoningLevel } from '@/lib/chat/useReasoningMode'
import { UsageRechargeGuide } from '@/features/dashboard/components/UsageRechargeGuide'

type ChatComposerProps = {
  draft: string
  isSending: boolean
  textareaRef: React.RefObject<HTMLTextAreaElement | null>
  getAccessToken: () => Promise<string | null>
  onDraftChange: (value: string) => void
  onKeyDown: (e: React.KeyboardEvent<HTMLTextAreaElement>) => void
  onSend: (text: string) => void
  onImageSelected: (file: File) => void
  onDocumentSelected: (file: File) => void
  onGenerateImage: (text: string) => void
  onPrepareImageGeneration: () => void
  onPasteImage?: (event: React.ClipboardEvent<HTMLTextAreaElement>) => void
  hasImageSelected: boolean
  hasDocumentSelected?: boolean
  /** SP05: ocultar botón de generación de imágenes si feature flag=false */
  imageGenEnabled?: boolean
  /** A07: modo WhatsApp manual activado */
  whatsappMode?: boolean
  /** A07: toggle manual entre canal PC y WhatsApp */
  onToggleWhatsappMode?: () => void
  /** A07: si WhatsApp está vinculado (muestra/oculta el toggle) */
  whatsappModeAvailable?: boolean
  reasoningEnabled?: boolean
  reasoningLevel?: ReasoningLevel
  onReasoningEnabledChange?: (enabled: boolean) => void
  onReasoningLevelChange?: (level: ReasoningLevel) => void
  /** VOX: Talk Mode — conversación por voz activada */
  talkMode?: boolean
  /** VOX: toggle talk mode on/off */
  onToggleTalkMode?: () => void
  /** VOX: estado del modo escucha para feedback visual */
  wakeWordState?: WakeWordState
  /** VOX: activa detección de voz (modo escucha) */
  onStartWakeWord?: () => void
  /** VOX: desactiva detección de voz (modo escucha) */
  onStopWakeWord?: () => void
  /** TTS auto: DOT lee respuestas al terminar */
  dotSpeaksEnabled?: boolean
  /** TTS auto: toggle "DOT habla" */
  onToggleDotSpeaks?: () => void
  /** B06: TTS disponible en el servidor */
  voiceTtsAvailable?: boolean
  /** B06: STT disponible en el servidor */
  voiceSttAvailable?: boolean
  /** Abrir panel Configuración (cuando el servicio de voz no está listo) */
  onOpenAppSettings?: () => void
  /** TTS: reproduciendo audio ahora */
  ttsPlaying?: boolean
  /** Bloqueo IA al 100% — deshabilita el compositor */
  inputBlocked?: boolean
  inputBlockedMessage?: string
}

function MicStateIcon({ state }: { state: string }) {
  if (state === 'listening') {
    return (
      <span className="dot-chat__mic-pulse dot-chat__mic-pulse--red" aria-hidden>
        <svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor" aria-hidden>
          <path d="M12 14c1.66 0 3-1.34 3-3V5c0-1.66-1.34-3-3-3S9 3.34 9 5v6c0 1.66 1.34 3 3 3z" />
          <path d="M17 11c0 2.76-2.24 5-5 5s-5-2.24-5-5H5c0 3.53 2.61 6.43 6 6.92V21h2v-3.08c3.39-.49 6-3.39 6-6.92h-2z" />
        </svg>
      </span>
    )
  }
  if (state === 'transcribing') {
    return (
      <span className="dot-chat__mic-pulse dot-chat__mic-pulse--processing" aria-hidden>
        <svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor" aria-hidden>
          <path d="M12 14c1.66 0 3-1.34 3-3V5c0-1.66-1.34-3-3-3S9 3.34 9 5v6c0 1.66 1.34 3 3 3z" />
          <path d="M17 11c0 2.76-2.24 5-5 5s-5-2.24-5-5H5c0 3.53 2.61 6.43 6 6.92V21h2v-3.08c3.39-.49 6-3.39 6-6.92h-2z" />
        </svg>
      </span>
    )
  }
  if (state === 'speaking') {
    return (
      <span className="dot-chat__mic-pulse dot-chat__mic-pulse--blue" title="DOT está hablando...">
        <svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor" aria-hidden>
          <path d="M3 9v6h4l5 5V4L7 9H3zm13.5 3c0-1.77-1.02-3.29-2.5-4.03v8.05c1.48-.73 2.5-2.25 2.5-4.02zM14 3.23v2.06c2.89.86 5 3.54 5 6.71s-2.11 5.85-5 6.71v2.06c4.01-.91 7-4.49 7-8.77s-2.99-7.86-7-8.77z" />
        </svg>
      </span>
    )
  }
  return <IconMic />
}

export function ChatComposer({
  draft,
  isSending,
  textareaRef,
  getAccessToken,
  onDraftChange,
  onKeyDown,
  onSend,
  onImageSelected,
  onDocumentSelected,
  onGenerateImage,
  onPrepareImageGeneration,
  onPasteImage,
  hasImageSelected,
  hasDocumentSelected = false,
  whatsappMode = false,
  onToggleWhatsappMode,
  whatsappModeAvailable = false,
  imageGenEnabled = true,
  reasoningEnabled = false,
  reasoningLevel = 'auto',
  onReasoningEnabledChange,
  onReasoningLevelChange,
  talkMode = false,
  onToggleTalkMode,
  wakeWordState = 'idle',
  onStartWakeWord,
  onStopWakeWord,
  dotSpeaksEnabled = false,
  onToggleDotSpeaks,
  voiceTtsAvailable = false,
  voiceSttAvailable = true,
  onOpenAppSettings,
  ttsPlaying = false,
  inputBlocked = false,
  inputBlockedMessage,
}: ChatComposerProps) {
  const { t } = useTranslation()
  const draftWasEmptyRef = useRef(true)
  const isSendingRef = useRef(isSending)
  isSendingRef.current = isSending

  const handleTranscript = useCallback(
    (text: string) => {
      const trimmed = text.trim()
      if (!trimmed) return
      onDraftChange(trimmed)
      if (draftWasEmptyRef.current && !isSendingRef.current) {
        onSend(trimmed)
      }
    },
    [onDraftChange, onSend],
  )

  const voice = useVoiceInput({
    getAccessToken,
    onTranscript: handleTranscript,
    sttAvailable: voiceSttAvailable,
  })

  // Track if draft was empty when voice started
  useEffect(() => {
    if (voice.state === 'listening') {
      draftWasEmptyRef.current = draft.trim().length === 0
    }
  }, [voice.state, draft])

  // Show interim / transcribing status in draft while active
  useEffect(() => {
    if (
      voice.interimText &&
      (voice.state === 'listening' || voice.state === 'transcribing')
    ) {
      onDraftChange(voice.interimText)
    }
  }, [voice.interimText, voice.state, onDraftChange])

  const handleMicClick = useCallback(() => {
    if (isSending || voice.state === 'transcribing') return
    voice.toggleListening()
  }, [isSending, voice])

  // Auto-ajuste de altura del textarea según su contenido
  useEffect(() => {
    const el = textareaRef.current
    if (!el) return
    el.style.height = 'auto'
    const newHeight = Math.min(Math.max(el.scrollHeight, 50), 200)
    el.style.height = `${newHeight}px`
  }, [draft, textareaRef])

  const handleSendClick = useCallback(() => {
    const value = draft.trim()
    const canSend = Boolean(value) || hasImageSelected || hasDocumentSelected
    if (canSend && !isSending) {
      onSend(draft)
    }
  }, [draft, hasDocumentSelected, hasImageSelected, isSending, onSend])

  const micBusy = voice.state === 'listening' || voice.state === 'transcribing'

  // Determine visual state of mic button
  const micVisualState = talkMode
    ? wakeWordState === 'listening'
      ? 'listening'
      : wakeWordState === 'speaking' || wakeWordState === 'detected'
        ? 'speaking'
        : 'idle'
    : voice.state === 'listening'
      ? 'listening'
      : voice.state === 'transcribing'
        ? 'transcribing'
        : 'idle'

  const micClassName = [
    'dot-chat__icon-btn',
    micVisualState === 'listening'
      ? 'dot-chat__icon-btn--voice-listening'
      : micVisualState === 'transcribing'
        ? 'dot-chat__icon-btn--voice-transcribing'
        : micVisualState === 'speaking'
          ? 'dot-chat__icon-btn--voice-speaking'
          : 'dot-chat__icon-btn--voice',
  ]
    .filter(Boolean)
    .join(' ')

  const micTitleTalkMode =
    wakeWordState === 'listening'
      ? t('voice.talk_listening')
      : wakeWordState === 'speaking'
        ? t('voice.talk_speaking')
        : wakeWordState === 'detected'
          ? t('voice.talk_detected')
          : t('voice.talk_enable')

  const micTitle =
    talkMode
      ? micTitleTalkMode
      : voice.state === 'listening'
        ? t('voice.stop')
        : voice.state === 'transcribing'
          ? t('voice.transcribing')
          : voice.state === 'unsupported'
            ? t('voice.unsupported')
            : voice.state === 'denied'
              ? t('voice.denied')
              : voice.state === 'error'
                ? voice.unsupportedReason || t('voice.generic_error')
                : t('voice.start')

  const micDisabled =
    inputBlocked ||
    (talkMode
      ? false
      : isSending ||
        voice.state === 'unsupported' ||
        voice.state === 'transcribing')

  const showMicHelp = !talkMode && (voice.state === 'denied' || voice.state === 'error')
  const serviceUnavailableHelp =
    showMicHelp
    && Boolean(voice.unsupportedReason)
    && isVoiceServiceUnavailableMessage(voice.unsupportedReason!, t)
  const showMicStatus =
    !talkMode && (voice.state === 'listening' || voice.state === 'transcribing')

  const textareaValue =
    micBusy && voice.interimText ? voice.interimText : draft

  // Placeholder dinámico según modo
  const isImageGenMode = draft.trimStart().startsWith('Genera una imagen')
  const placeholder = inputBlocked
    ? (inputBlockedMessage ?? 'Has alcanzado tu límite de IA de este mes.')
    : talkMode
    ? t('voice.placeholder_talk')
    : whatsappMode
      ? 'Escribe un mensaje para WhatsApp…'
      : isImageGenMode
        ? 'Describe la imagen que quieres generar…'
        : 'Escribe un mensaje… (escribe / para comandos)'

  const composerDisabled = isSending || inputBlocked

  return (
    <div className="dot-chat__composer-wrap">
      {inputBlocked ? (
        <div className="dot-chat__usage-blocked" role="alert">
          <UsageRechargeGuide variant="composer" />
        </div>
      ) : null}
      {dotSpeaksEnabled && ttsPlaying ? (
        <div className="dot-chat__speak-status" role="status">
          <span className="dot-chat__speak-indicator dot-chat__speak-indicator--playing" />
          {t('voice.speak_playing')}
        </div>
      ) : null}
      {talkMode && (
        <div className="dot-chat__talk-status" role="status">
          <span className={`dot-chat__talk-indicator dot-chat__talk-indicator--${wakeWordState}`} />
          {wakeWordState === 'listening'
            ? t('voice.talk_listening')
            : wakeWordState === 'speaking'
              ? t('voice.talk_speaking')
              : wakeWordState === 'detected'
                ? t('voice.talk_detected')
                : t('voice.talk_active')}
        </div>
      )}
      {showMicStatus && (
        <div className="dot-chat__mic-status" role="status">
          <span className={`dot-chat__mic-status-indicator dot-chat__mic-status-indicator--${voice.state}`} />
          {voice.state === 'listening' ? t('voice.listening') : t('voice.transcribing')}
        </div>
      )}
      {showMicHelp && (
        <div className="dot-chat__mic-denied" role="alert">
          <span className="dot-chat__mic-denied-text">
            {voice.unsupportedReason || t('voice.denied')}
          </span>
          {serviceUnavailableHelp && onOpenAppSettings ? (
            <button
              type="button"
              className="dot-chat__mic-denied-link"
              onClick={onOpenAppSettings}
            >
              {t('voice.open_app_settings')}
            </button>
          ) : (
            <button
              type="button"
              className="dot-chat__mic-denied-link"
              onClick={voice.openMicSettings}
            >
              {t('voice.open_settings')}
            </button>
          )}
        </div>
      )}
      <div className="dot-chat__composer">
        <AttachmentPicker onFileSelected={onDocumentSelected} disabled={composerDisabled} />
        <AttachmentImagePicker onFileSelected={onImageSelected} disabled={composerDisabled} />
        {imageGenEnabled ? (
        <button
          type="button"
          className="dot-chat__icon-btn dot-chat__icon-btn--image-gen"
          title={t('imageGen.button')}
          disabled={composerDisabled}
          onClick={() => {
            const value = draft.trim()
            if (value) {
              onGenerateImage(value)
            } else {
              onPrepareImageGeneration()
            }
          }}
        >
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden>
            <path d="M12 19l7-7 3 3-7 7-3-3z" />
            <path d="M18 13l-1.5-7.5L2 2l3.5 14.5L13 18l5-5z" />
            <path d="M2 2l7.586 7.586" />
            <circle cx="11" cy="11" r="2" />
          </svg>
        </button>
        ) : null}
        <textarea
          ref={textareaRef}
          className="dot-chat__textarea"
          onKeyDown={onKeyDown}
          onPaste={onPasteImage}
          onChange={(e) => onDraftChange(e.target.value)}
          placeholder={placeholder}
          rows={1}
          value={textareaValue}
          disabled={composerDisabled || voice.state === 'transcribing'}
        />
        {onReasoningEnabledChange && onReasoningLevelChange ? (
          <ReasoningModeControl
            enabled={reasoningEnabled}
            level={reasoningLevel}
            onEnabledChange={onReasoningEnabledChange}
            onLevelChange={onReasoningLevelChange}
            disabled={composerDisabled}
          />
        ) : null}
        <button
          type="button"
          className={micClassName}
          title={micTitle}
          disabled={micDisabled}
          onClick={talkMode ? undefined : handleMicClick}
        >
          <MicStateIcon state={micVisualState} />
        </button>
        {onToggleDotSpeaks ? (
          <button
            type="button"
            className={`dot-chat__icon-btn dot-chat__icon-btn--dot-speaks${dotSpeaksEnabled ? ' dot-chat__icon-btn--dot-speaks-active' : ''}`}
            title={
              dotSpeaksEnabled
                ? t('voice.speak_disable')
                : voiceTtsAvailable
                  ? t('voice.speak_enable')
                  : t('voice.speak_unavailable')
            }
            aria-label={dotSpeaksEnabled ? t('voice.speak_disable') : t('voice.speak_enable')}
            aria-pressed={dotSpeaksEnabled}
            disabled={composerDisabled}
            onClick={onToggleDotSpeaks}
          >
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden>
              <polygon points="11 5 6 9 2 9 2 15 6 15 11 19 11 5" />
              <path d="M15.54 8.46a5 5 0 0 1 0 7.07" />
              <path d="M19.07 4.93a10 10 0 0 1 0 14.14" />
            </svg>
          </button>
        ) : null}
        {/* Talk Mode Toggle */}
        {onToggleTalkMode ? (
          <button
            type="button"
            className={`dot-chat__icon-btn dot-chat__icon-btn--talk-mode${talkMode ? ' dot-chat__icon-btn--talk-active' : ''}`}
            title={talkMode ? t('voice.talk_disable') : t('voice.talk_enable')}
            disabled={composerDisabled}
            onClick={() => {
              if (!talkMode && onStartWakeWord) {
                onStartWakeWord()
              } else if (talkMode && onStopWakeWord) {
                onStopWakeWord()
              }
              onToggleTalkMode()
            }}
          >
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden>
              <path d="M2 10v3" />
              <path d="M6 6v11" />
              <path d="M10 3v18" />
              <path d="M14 8v7" />
              <path d="M18 5v13" />
              <path d="M22 10v3" />
            </svg>
          </button>
        ) : null}
        <button
          type="button"
          className="dot-chat__icon-btn dot-chat__icon-btn--web-search"
          title="Buscar en internet"
          onClick={() => onSend('/buscar ')}
        >
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden>
            <circle cx="12" cy="12" r="10" />
            <line x1="2" y1="12" x2="22" y2="12" />
            <path d="M12 2a15.3 15.3 0 0 1 4 10 15.3 15.3 0 0 1-4 10 15.3 15.3 0 0 1-4-10 15.3 15.3 0 0 1 4-10z" />
          </svg>
        </button>
        {whatsappModeAvailable ? (
          <button
            type="button"
            className={`dot-chat__icon-btn dot-chat__icon-btn--whatsapp-toggle${whatsappMode ? ' dot-chat__icon-btn--whatsapp-active' : ''}`}
            title={whatsappMode ? 'WhatsApp activado — clic para volver a chat PC' : 'Enviar por WhatsApp'}
            disabled={composerDisabled}
            onClick={onToggleWhatsappMode}
          >
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden>
              <path d="M21 11.5a8.38 8.38 0 0 1-.9 3.8 8.5 8.5 0 0 1-7.6 4.7 8.38 8.38 0 0 1-3.8-.9L3 21l1.9-5.7a8.38 8.38 0 0 1-.9-3.8 8.5 8.5 0 0 1 4.7-7.6 8.38 8.38 0 0 1 3.8-.9h.5a8.48 8.48 0 0 1 8 8v.5z" />
            </svg>
          </button>
        ) : null}
        <button
          type="button"
          className="dot-chat__send-btn"
          onClick={handleSendClick}
          disabled={
            inputBlocked ||
            (!draft.trim() && !hasImageSelected && !hasDocumentSelected) ||
            isSending ||
            micBusy
          }
          aria-label="Enviar mensaje"
          title="Enviar"
        >
          <svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor" aria-hidden>
            <path d="M3.4 20.6 22 12 3.4 3.4l2.8 7.2L17 12l-10.8 1.4-2.8 7.2z" />
          </svg>
        </button>
      </div>
    </div>
  )
}
