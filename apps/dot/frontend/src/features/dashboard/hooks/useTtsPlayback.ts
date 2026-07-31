import { useCallback, useEffect, useRef, useState } from 'react'

import { ApiError } from '@/lib/api/http'
import { humanizeTtsError, synthesizeSpeech } from '@/lib/api/voice'
import { prepareTextForTts } from '@/features/dashboard/lib/ttsText'

export type UseTtsPlaybackOptions = {
  getAccessToken: () => Promise<string | null>
  onError?: (message: string) => void
  translate?: (key: string) => string
}

export function useTtsPlayback({
  getAccessToken,
  onError,
  translate,
}: UseTtsPlaybackOptions) {
  const [loadingMessageId, setLoadingMessageId] = useState<string | null>(null)
  const [isPlaying, setIsPlaying] = useState(false)
  const audioRef = useRef<HTMLAudioElement | null>(null)
  const requestIdRef = useRef(0)

  const t = useCallback(
    (key: string) => (translate ? translate(key) : key),
    [translate],
  )

  const stop = useCallback(() => {
    requestIdRef.current += 1
    if (audioRef.current) {
      audioRef.current.pause()
      audioRef.current.src = ''
      audioRef.current = null
    }
    setIsPlaying(false)
    setLoadingMessageId(null)
  }, [])

  useEffect(() => () => {
    stop()
  }, [stop])

  const speak = useCallback(
    async (text: string, messageId: string) => {
      const prepared = prepareTextForTts(text)
      if (!prepared) return

      const requestId = requestIdRef.current + 1
      requestIdRef.current = requestId

      if (audioRef.current) {
        audioRef.current.pause()
        audioRef.current.src = ''
        audioRef.current = null
      }

      setLoadingMessageId(messageId)
      setIsPlaying(false)

      try {
        const token = await getAccessToken()
        if (!token || requestId !== requestIdRef.current) return

        const result = await synthesizeSpeech(prepared, token)
        if (requestId !== requestIdRef.current) return

        const audio = new Audio(`data:audio/${result.format};base64,${result.audio_base64}`)
        audioRef.current = audio

        audio.onended = () => {
          if (requestId !== requestIdRef.current) return
          setIsPlaying(false)
          setLoadingMessageId(null)
          audioRef.current = null
        }

        audio.onerror = () => {
          if (requestId !== requestIdRef.current) return
          setIsPlaying(false)
          setLoadingMessageId(null)
          audioRef.current = null
          onError?.(t('voice.speak_error'))
        }

        setLoadingMessageId(null)
        setIsPlaying(true)
        await audio.play()
      } catch (err) {
        if (requestId !== requestIdRef.current) return
        const raw =
          err instanceof ApiError
            ? String(err.message || '')
            : err instanceof Error
              ? err.message
              : ''
        onError?.(humanizeTtsError(raw, t))
      } finally {
        if (requestId === requestIdRef.current && !audioRef.current) {
          setLoadingMessageId(null)
        }
      }
    },
    [getAccessToken, onError, t],
  )

  return {
    speak,
    stop,
    loadingMessageId,
    isPlaying,
  }
}
