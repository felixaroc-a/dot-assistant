import { useCallback, useEffect, useRef, useState } from 'react'

/**
 * Modo escucha — detección local de actividad de voz (VAD por RMS).
 *
 * No reconoce palabras clave ("Hey DOT" / "Hola DOT"); detecta voz sostenida
 * y dispara el flujo de Talk Mode. El audio no sale del dispositivo hasta
 * que se inicia la grabación para STT.
 */

export type WakeWordState = 'idle' | 'listening' | 'detected' | 'speaking' | 'denied' | 'error'

export interface UseWakeWordOptions {
  /** Callback cuando se detecta actividad de voz suficiente */
  onWakeWord: () => void
  /** Callback cuando se recibe audio hablado (para pasar al STT) */
  onSpeech: (audio: Blob) => void
  /** Umbral RMS para detección de voz (0-1, default: 0.02) */
  rmsThreshold?: number
  /** Callback para obtener access token (necesario para STT) */
  getAccessToken?: () => Promise<string | null>
}

export interface UseWakeWordResult {
  state: WakeWordState
  /** Inicia el modo escucha (VAD local) */
  startWakeWord: () => Promise<void>
  /** Detiene el modo escucha */
  stopWakeWord: () => void
  /** Dispara manualmente la detección de voz */
  triggerWakeWord: () => void
}

const MIC_TIMEOUT_MS = 5000

function stopMediaStream(stream: MediaStream | null) {
  if (!stream) return
  for (const track of stream.getTracks()) {
    track.stop()
  }
}

async function requestMicPermission(): Promise<
  { ok: true; stream: MediaStream } | { ok: false; reason: string }
> {
  if (!navigator.mediaDevices?.getUserMedia) {
    return { ok: false, reason: 'unavailable' }
  }
  try {
    const stream = await Promise.race([
      navigator.mediaDevices.getUserMedia({ audio: true }),
      new Promise<never>((_, reject) => {
        setTimeout(() => reject(new Error('mic_timeout')), MIC_TIMEOUT_MS)
      }),
    ])
    return { ok: true, stream }
  } catch (err) {
    const msg = err instanceof Error ? err.message : String(err)
    return { ok: false, reason: msg === 'mic_timeout' ? 'timeout' : 'denied' }
  }
}

/**
 * Calcula RMS (Root Mean Square) de un buffer de audio PCM 16-bit mono.
 * Devuelve un valor normalizado entre 0 y 1.
 */
function calculateRMS(buffer: Float32Array): number {
  let sum = 0
  for (let i = 0; i < buffer.length; i++) {
    sum += buffer[i] * buffer[i]
  }
  return Math.sqrt(sum / buffer.length)
}

/** Reproduce un sonido de reconocimiento usando Web Audio API (beep corto). */
function playAcknowledgmentSound(ctx: AudioContext) {
  const osc = ctx.createOscillator()
  const gain = ctx.createGain()
  osc.connect(gain)
  gain.connect(ctx.destination)
  osc.frequency.value = 880
  osc.type = 'sine'
  gain.gain.setValueAtTime(0.3, ctx.currentTime)
  gain.gain.exponentialRampToValueAtTime(0.01, ctx.currentTime + 0.15)
  osc.start(ctx.currentTime)
  osc.stop(ctx.currentTime + 0.15)
}

export function useWakeWord(options: UseWakeWordOptions): UseWakeWordResult {
  const {
    onWakeWord,
    rmsThreshold = 0.02,
  } = options

  const [state, setState] = useState<WakeWordState>('idle')
  const stateRef = useRef<WakeWordState>('idle')
  const mediaStreamRef = useRef<MediaStream | null>(null)
  const audioCtxRef = useRef<AudioContext | null>(null)
  const analyserRef = useRef<AnalyserNode | null>(null)
  const rafIdRef = useRef<number | null>(null)
  const activeRef = useRef(false)
  const onWakeWordRef = useRef(onWakeWord)
  onWakeWordRef.current = onWakeWord

  // Keep state ref in sync
  useEffect(() => {
    stateRef.current = state
  }, [state])

  const stopAudioLoop = useCallback(() => {
    if (rafIdRef.current !== null) {
      cancelAnimationFrame(rafIdRef.current)
      rafIdRef.current = null
    }
  }, [])

  const cleanup = useCallback(() => {
    activeRef.current = false
    stopAudioLoop()
    if (audioCtxRef.current) {
      try { audioCtxRef.current.close() } catch { /* ignore */ }
      audioCtxRef.current = null
      analyserRef.current = null
    }
    stopMediaStream(mediaStreamRef.current)
    mediaStreamRef.current = null
  }, [stopAudioLoop])

  const stopWakeWord = useCallback(() => {
    cleanup()
    setState('idle')
  }, [cleanup])

  const triggerWakeWord = useCallback(() => {
    setState('detected')
    if (audioCtxRef.current) {
      playAcknowledgmentSound(audioCtxRef.current)
    }
    onWakeWordRef.current()
    // Vuelve a escuchar después de procesar
    setTimeout(() => {
      if (stateRef.current === 'detected') {
        setState('listening')
      }
    }, 1500)
  }, [])

  const startWakeWord = useCallback(async () => {
    if (activeRef.current) return

    setState('listening')
    activeRef.current = true

    const mic = await requestMicPermission()
    if (!mic.ok) {
      activeRef.current = false
      setState(mic.reason === 'denied' || mic.reason === 'timeout' ? 'denied' : 'error')
      return
    }

    mediaStreamRef.current = mic.stream

    try {
      const ctx = new AudioContext()
      audioCtxRef.current = ctx
      const source = ctx.createMediaStreamSource(mic.stream)
      const analyser = ctx.createAnalyser()
      analyser.fftSize = 2048
      analyser.smoothingTimeConstant = 0.8
      source.connect(analyser)
      analyserRef.current = analyser

      const timeData = new Float32Array(analyser.fftSize)
      let consecutiveVoiceFrames = 0
      const VOICE_FRAMES_NEEDED = 15 // ~1.5 segundos de voz continua
      let wasSpeaking = false

      const loop = () => {
        if (!activeRef.current) return
        rafIdRef.current = requestAnimationFrame(loop)

        if (!analyserRef.current) return
        analyserRef.current.getFloatTimeDomainData(timeData)
        const rms = calculateRMS(timeData)
        const isVoice = rms > rmsThreshold

        if (isVoice) {
          consecutiveVoiceFrames++
          if (consecutiveVoiceFrames >= VOICE_FRAMES_NEEDED && !wasSpeaking) {
            wasSpeaking = true
            setState('speaking')
            // VAD por RMS: voz sostenida dispara Talk Mode (sin keyword spotting).
            triggerWakeWord()
          }
        } else {
          consecutiveVoiceFrames = 0
          wasSpeaking = false
          if (stateRef.current === 'speaking') {
            setState('listening')
          }
        }
      }

      rafIdRef.current = requestAnimationFrame(loop)
    } catch (err) {
      console.error('Wake word audio setup failed:', err)
      cleanup()
      setState('error')
    }
  }, [cleanup, rmsThreshold, triggerWakeWord])

  // Cleanup on unmount
  useEffect(() => {
    return () => cleanup()
  }, [cleanup])

  return {
    state,
    startWakeWord,
    stopWakeWord,
    triggerWakeWord,
  }
}
