import { useEffect, useRef } from 'react'

import { SPLASH_TOTAL_MS } from './splash-timings'

const REDUCED_SPLASH_MS = 1200

type SplashProgressOptions = {
  reduced?: boolean
}

export function useSplashProgress(onComplete: () => void, options?: SplashProgressOptions) {
  const onCompleteRef = useRef(onComplete)
  onCompleteRef.current = onComplete
  const durationMs = options?.reduced ? REDUCED_SPLASH_MS : SPLASH_TOTAL_MS

  useEffect(() => {
    const timer = window.setTimeout(() => {
      onCompleteRef.current()
    }, durationMs)

    return () => window.clearTimeout(timer)
  }, [durationMs])
}
