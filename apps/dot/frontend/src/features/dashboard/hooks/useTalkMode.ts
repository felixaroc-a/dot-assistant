import { useCallback, useEffect, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'

import {
  humanizeVoiceError,
  sendTalkTurn,
  startTalkSession,
  stopTalkSession,
} from '@/lib/api/voice'
import { useWakeWord, type WakeWordState } from './useWakeWord'

const UTTERANCE_MAX_MS = 15_000
const SILENCE_FRAMES_NEEDED = 20
const SILENCE_RMS_THRESHOLD = 0.015

type GetAccessToken = () => Promise<string | null>

function stopMediaStream(stream: MediaStream | null) {
  if (!stream) return
  for (const track of stream.getTracks()) {
    track.stop()
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

export type UseTalkModeOptions = {
  getAccessToken: GetAccessToken
  onExchange?: (userText: string, assistantText: string) => void
  onError?: (message: string) => void
  onSpeakingChange?: (speaking: boolean) => void
  stopOtherAudio?: () => void
  disabled?: boolean
}

export type UseTalkModeResult = {
  talkMode: boolean
  wakeWordState: WakeWordState
  toggleTalkMode: () => void
  startWakeWord: () => Promise<void>
  stopWakeWord: () => void
}

export function useTalkMode({
  getAccessToken,
  onExchange,
  onError,
  onSpeakingChange,
  stopOtherAudio,
  disabled = false,
}: UseTalkModeOptions): UseTalkModeResult {
  const { i18n, t } = useTranslation()
  const [talkMode, setTalkMode] = useState(false)
  const talkModeRef = useRef(false)
  const processingRef = useRef(false)
  const audioRef = useRef<HTMLAudioElement | null>(null)
  const recorderRef = useRef<MediaRecorder | null>(null)
  const streamRef = useRef<MediaStream | null>(null)
  const rafRef = useRef<number | null>(null)
  const onExchangeRef = useRef(onExchange)
  onExchangeRef.current = onExchange

  const [speakingOverride, setSpeakingOverride] = useState(false)

  const stopAudio = useCallback(() => {
    if (audioRef.current) {
      audioRef.current.pause()
      audioRef.current.src = ''
      audioRef.current = null
    }
    setSpeakingOverride(false)
    onSpeakingChange?.(false)
  }, [onSpeakingChange])

  const cleanupRecording = useCallback(() => {
    if (rafRef.current !== null) {
      cancelAnimationFrame(rafRef.current)
      rafRef.current = null
    }
    const rec = recorderRef.current
    recorderRef.current = null
    if (rec && rec.state !== 'inactive') {
      try {
        rec.stop()
      } catch {
        // ignore
      }
    }
    stopMediaStream(streamRef.current)
    streamRef.current = null
  }, [])

  const playResponseAudio = useCallback(
    async (audioBase64: string, format: string) => {
      stopOtherAudio?.()
      stopAudio()

      const audio = new Audio(`data:audio/${format};base64,${audioBase64}`)
      audioRef.current = audio
      setSpeakingOverride(true)
      onSpeakingChange?.(true)

      audio.onended = () => {
        audioRef.current = null
        setSpeakingOverride(false)
        onSpeakingChange?.(false)
      }
      audio.onerror = () => {
        audioRef.current = null
        setSpeakingOverride(false)
        onSpeakingChange?.(false)
        onError?.(t('voice.speak_error'))
      }

      try {
        await audio.play()
      } catch {
        audioRef.current = null
        setSpeakingOverride(false)
        onSpeakingChange?.(false)
        onError?.(t('voice.speak_error'))
      }
    },
    [onError, onSpeakingChange, stopAudio, stopOtherAudio, t],
  )

  const processUtterance = useCallback(
    async (blob: Blob) => {
      if (!talkModeRef.current || blob.size < 200) return

      processingRef.current = true
      try {
        const token = await getAccessToken()
        const lang = (i18n.language || 'es').split('-')[0] || 'es'
        const result = await sendTalkTurn(blob, token, { language: lang })

        const transcript = (result.transcript || '').trim()
        const responseText = (result.response_text || '').trim()

        if (transcript || responseText) {
          onExchangeRef.current?.(transcript, responseText)
        }

        if (result.audio_base64) {
          await playResponseAudio(result.audio_base64, result.audio_format || 'mp3')
        }
      } catch (err) {
        const msg = err instanceof Error ? err.message : String(err)
        onError?.(humanizeVoiceError(msg, t))
      } finally {
        processingRef.current = false
      }
    },
    [getAccessToken, i18n.language, onError, playResponseAudio, t],
  )

  const recordUtterance = useCallback(async () => {
    if (processingRef.current || !talkModeRef.current) return
    if (typeof MediaRecorder === 'undefined') {
      onError?.(t('voice.unsupported'))
      return
    }

    cleanupRecording()

    let stream: MediaStream
    try {
      stream = await navigator.mediaDevices.getUserMedia({ audio: true })
    } catch {
      onError?.(t('voice.denied'))
      return
    }

    streamRef.current = stream
    const mime = pickRecorderMime()
    let recorder: MediaRecorder
    try {
      recorder = mime
        ? new MediaRecorder(stream, { mimeType: mime })
        : new MediaRecorder(stream)
    } catch {
      cleanupRecording()
      onError?.(t('voice.start_failed'))
      return
    }

    const chunks: BlobPart[] = []
    recorderRef.current = recorder

    recorder.ondataavailable = (ev) => {
      if (ev.data?.size) chunks.push(ev.data)
    }

    const finish = () => {
      if (rafRef.current !== null) {
        cancelAnimationFrame(rafRef.current)
        rafRef.current = null
      }
      const type = recorder.mimeType || mime || 'audio/webm'
      const blob = new Blob(chunks, { type })
      cleanupRecording()
      void processUtterance(blob)
    }

    recorder.onstop = finish
    recorder.onerror = () => {
      cleanupRecording()
      onError?.(t('voice.start_failed'))
    }

    try {
      recorder.start(250)
    } catch {
      cleanupRecording()
      onError?.(t('voice.start_failed'))
      return
    }

    const analyserCtx = new AudioContext()
    const source = analyserCtx.createMediaStreamSource(stream)
    const analyser = analyserCtx.createAnalyser()
    analyser.fftSize = 2048
    source.connect(analyser)
    const timeData = new Float32Array(analyser.fftSize)

    let silentFrames = 0
    let voiceDetected = false
    const startedAt = Date.now()

    const loop = () => {
      if (!recorderRef.current || recorderRef.current.state === 'inactive') {
        void analyserCtx.close()
        return
      }

      if (Date.now() - startedAt >= UTTERANCE_MAX_MS) {
        try {
          recorderRef.current.stop()
        } catch {
          finish()
        }
        void analyserCtx.close()
        return
      }

      analyser.getFloatTimeDomainData(timeData)
      let sum = 0
      for (let i = 0; i < timeData.length; i += 1) {
        sum += timeData[i] * timeData[i]
      }
      const rms = Math.sqrt(sum / timeData.length)
      const isVoice = rms > SILENCE_RMS_THRESHOLD

      if (isVoice) {
        voiceDetected = true
        silentFrames = 0
      } else if (voiceDetected) {
        silentFrames += 1
        if (silentFrames >= SILENCE_FRAMES_NEEDED) {
          try {
            recorderRef.current.stop()
          } catch {
            finish()
          }
          void analyserCtx.close()
          return
        }
      }

      rafRef.current = requestAnimationFrame(loop)
    }

    rafRef.current = requestAnimationFrame(loop)
  }, [cleanupRecording, onError, processUtterance, t])

  const handleWakeWord = useCallback(() => {
    if (!talkModeRef.current || processingRef.current) return
    stopAudio()
    void recordUtterance()
  }, [recordUtterance, stopAudio])

  const wakeWord = useWakeWord({
    onWakeWord: handleWakeWord,
    onSpeech: () => {},
    getAccessToken,
  })

  const wakeWordState: WakeWordState = speakingOverride ? 'speaking' : wakeWord.state

  const startWakeWord = useCallback(async () => {
    if (disabled) return
    await wakeWord.startWakeWord()
  }, [disabled, wakeWord])

  const stopWakeWord = useCallback(() => {
    wakeWord.stopWakeWord()
    cleanupRecording()
    stopAudio()
  }, [cleanupRecording, stopAudio, wakeWord])

  const enableTalkMode = useCallback(async () => {
    if (disabled) {
      onError?.(t('voice.talk_unavailable'))
      return
    }
    talkModeRef.current = true
    setTalkMode(true)
    try {
      const token = await getAccessToken()
      await startTalkSession(token)
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err)
      onError?.(humanizeVoiceError(msg, t))
    }
  }, [disabled, getAccessToken, onError, t])

  const disableTalkMode = useCallback(() => {
    talkModeRef.current = false
    setTalkMode(false)
    stopWakeWord()
    void (async () => {
      try {
        const token = await getAccessToken()
        await stopTalkSession(token)
      } catch {
        // sesión ya cerrada o sin red
      }
    })()
  }, [getAccessToken, stopWakeWord])

  const toggleTalkMode = useCallback(() => {
    if (talkModeRef.current) {
      disableTalkMode()
    } else {
      void enableTalkMode()
    }
  }, [disableTalkMode, enableTalkMode])

  useEffect(() => {
    talkModeRef.current = talkMode
  }, [talkMode])

  useEffect(() => {
    return () => {
      talkModeRef.current = false
      stopWakeWord()
      void (async () => {
        try {
          const token = await getAccessToken()
          await stopTalkSession(token)
        } catch {
          // ignore
        }
      })()
    }
  }, [getAccessToken, stopWakeWord])

  useEffect(() => {
    if (disabled && talkModeRef.current) {
      disableTalkMode()
    }
  }, [disabled, disableTalkMode])

  return {
    talkMode,
    wakeWordState,
    toggleTalkMode,
    startWakeWord,
    stopWakeWord,
  }
}
