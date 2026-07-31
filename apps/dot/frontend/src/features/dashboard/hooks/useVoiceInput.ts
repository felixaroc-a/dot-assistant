import { useCallback, useEffect, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'

import { transcribeAudio, humanizeVoiceError } from '@/lib/api/voice'

export type VoiceState =
  | 'idle'
  | 'listening'
  | 'transcribing'
  | 'speaking'
  | 'unsupported'
  | 'denied'
  | 'error'

export interface UseVoiceInputResult {
  state: VoiceState
  interimText: string
  startListening: () => void
  stopListening: () => void
  toggleListening: () => void
  unsupportedReason: string | null
  openMicSettings: () => void
  /** True si el navegador soporta SpeechRecognition (Web Speech API) */
  webSpeechAvailable: boolean
}

const MIC_TIMEOUT_MS = 4000

type GetAccessToken = () => Promise<string | null>

function stopMediaStream(stream: MediaStream | null) {
  if (!stream) return
  for (const track of stream.getTracks()) {
    track.stop()
  }
}

async function requestMicPermission(): Promise<
  { ok: true; stream: MediaStream } | { ok: false; reason: 'denied' | 'timeout' | 'unavailable' }
> {
  if (!navigator.mediaDevices?.getUserMedia) {
    return { ok: false, reason: 'unavailable' }
  }
  let timer: ReturnType<typeof setTimeout> | null = null
  try {
    const stream = await Promise.race([
      navigator.mediaDevices.getUserMedia({ audio: true }),
      new Promise<never>((_, reject) => {
        timer = setTimeout(() => reject(new Error('mic_timeout')), MIC_TIMEOUT_MS)
      }),
    ])
    return { ok: true, stream }
  } catch (err) {
    const msg = err instanceof Error ? err.message : String(err)
    if (msg === 'mic_timeout') return { ok: false, reason: 'timeout' }
    return { ok: false, reason: 'denied' }
  } finally {
    if (timer) clearTimeout(timer)
  }
}

function pickRecorderMime(): string {
  const candidates = [
    'audio/webm;codecs=opus',
    'audio/webm',
    'audio/ogg;codecs=opus',
    'audio/mp4',
  ]
  for (const mime of candidates) {
    if (typeof MediaRecorder !== 'undefined' && MediaRecorder.isTypeSupported(mime)) {
      return mime
    }
  }
  return ''
}

export function useVoiceInput(options: {
  getAccessToken: GetAccessToken
  onTranscript: (text: string) => void
  /** Si false, bloquea grabación y muestra mensaje guiado (servicio STT no listo). */
  sttAvailable?: boolean
}): UseVoiceInputResult {
  const { getAccessToken, onTranscript, sttAvailable = true } = options
  const { i18n, t } = useTranslation()
  const [state, setState] = useState<VoiceState>('idle')
  const [interimText, setInterimText] = useState('')
  const [unsupportedReason, setUnsupportedReason] = useState<string | null>(null)

  const mediaStreamRef = useRef<MediaStream | null>(null)
  const recorderRef = useRef<MediaRecorder | null>(null)
  const chunksRef = useRef<BlobPart[]>([])
  const startingRef = useRef(false)
  const onTranscriptRef = useRef(onTranscript)
  onTranscriptRef.current = onTranscript

  const openMicSettings = useCallback(() => {
    const desktop = window.desktop as
      | (NonNullable<Window['desktop']> & {
          openMicSettings?: () => Promise<{ ok: boolean }>
        })
      | undefined
    if (desktop?.openMicSettings) {
      void desktop.openMicSettings()
      return
    }
    if (desktop?.openUrl) {
      void desktop.openUrl('ms-settings:privacy-microphone')
      return
    }
    window.open('ms-settings:privacy-microphone', '_blank')
  }, [])

  const cleanup = useCallback(() => {
    const rec = recorderRef.current
    recorderRef.current = null
    if (rec && rec.state !== 'inactive') {
      try {
        rec.stop()
      } catch {
        // ignore
      }
    }
    stopMediaStream(mediaStreamRef.current)
    mediaStreamRef.current = null
    chunksRef.current = []
  }, [])

  const markDenied = useCallback(
    (reason: 'denied' | 'timeout') => {
      startingRef.current = false
      cleanup()
      setState('denied')
      setUnsupportedReason(reason === 'timeout' ? t('voice.timeout') : t('voice.denied'))
      openMicSettings()
    },
    [cleanup, openMicSettings, t],
  )

  const finishAndTranscribe = useCallback(
    async (blob: Blob) => {
      setState('transcribing')
      setInterimText(t('voice.transcribing'))
      try {
        const token = await getAccessToken()
        const lang = (i18n.language || 'es').split('-')[0] || 'es'
        const result = await transcribeAudio(blob, token, lang)
        const text = (result.text || '').trim()
        if (!text) {
          setState('error')
          setUnsupportedReason(t('voice.empty'))
          setInterimText('')
          return
        }
        setInterimText(text)
        setState('idle')
        onTranscriptRef.current(text)
      } catch (err) {
        const msg = err instanceof Error ? err.message : String(err)
        setState('error')
        setUnsupportedReason(humanizeVoiceError(msg, t))
        setInterimText('')
      }
    },
    [getAccessToken, i18n.language, t],
  )

  const stopListening = useCallback(() => {
    const rec = recorderRef.current
    if (!rec || rec.state === 'inactive') {
      cleanup()
      setState('idle')
      return
    }
    // onstop handler will transcribe
    try {
      rec.stop()
    } catch {
      cleanup()
      setState('idle')
    }
  }, [cleanup])

  const startListening = useCallback(async () => {
    if (startingRef.current || state === 'listening' || state === 'transcribing') return
    if (!sttAvailable) {
      setState('error')
      setUnsupportedReason(t('voice.needs_key'))
      return
    }
    if (typeof MediaRecorder === 'undefined') {
      setState('unsupported')
      setUnsupportedReason(t('voice.unsupported'))
      return
    }

    startingRef.current = true
    setInterimText(t('voice.listening'))
    setUnsupportedReason(null)
    setState('listening')

    const mic = await requestMicPermission()
    if (!mic.ok) {
      if ((mic as { ok: false; reason: 'denied' | 'timeout' | 'unavailable' }).reason === 'unavailable') {
        startingRef.current = false
        setState('unsupported')
        setUnsupportedReason(t('voice.unsupported'))
        return
      }
      markDenied((mic as { ok: false; reason: 'denied' | 'timeout' | 'unavailable' }).reason === 'timeout' ? 'timeout' : 'denied')
      return
    }

    mediaStreamRef.current = mic.stream
    chunksRef.current = []
    const mime = pickRecorderMime()
    let recorder: MediaRecorder
    try {
      recorder = mime
        ? new MediaRecorder(mic.stream, { mimeType: mime })
        : new MediaRecorder(mic.stream)
    } catch {
      startingRef.current = false
      stopMediaStream(mic.stream)
      mediaStreamRef.current = null
      setState('unsupported')
      setUnsupportedReason(t('voice.start_failed'))
      return
    }

    recorderRef.current = recorder
    recorder.ondataavailable = (ev) => {
      if (ev.data && ev.data.size > 0) chunksRef.current.push(ev.data)
    }
    recorder.onerror = () => {
      startingRef.current = false
      cleanup()
      setState('error')
      setUnsupportedReason(t('voice.start_failed'))
    }
    recorder.onstop = () => {
      startingRef.current = false
      const type = recorder.mimeType || mime || 'audio/webm'
      const blob = new Blob(chunksRef.current, { type })
      stopMediaStream(mediaStreamRef.current)
      mediaStreamRef.current = null
      recorderRef.current = null
      chunksRef.current = []
      if (blob.size < 200) {
        setState('error')
        setUnsupportedReason(t('voice.empty'))
        return
      }
      void finishAndTranscribe(blob)
    }

    try {
      recorder.start(250)
      startingRef.current = false
      setState('listening')
    } catch {
      startingRef.current = false
      cleanup()
      setState('unsupported')
      setUnsupportedReason(t('voice.start_failed'))
    }
  }, [cleanup, finishAndTranscribe, markDenied, sttAvailable, state, t])

  const toggleListening = useCallback(() => {
    if (state === 'listening') {
      stopListening()
    } else if (state !== 'transcribing') {
      void startListening()
    }
  }, [state, startListening, stopListening])

  useEffect(() => {
    return () => {
      cleanup()
    }
  }, [cleanup])

  return {
    state,
    interimText,
    startListening,
    stopListening,
    toggleListening,
    unsupportedReason,
    openMicSettings,
    webSpeechAvailable: typeof window !== 'undefined' && (
      'SpeechRecognition' in window || 'webkitSpeechRecognition' in window
    ),
  }
}
