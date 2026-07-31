import { useEffect, useState, useCallback } from 'react'
import { motion, useReducedMotion } from 'framer-motion'
import { isUsbGateSkipped } from '@/lib/desktop/usb-gate-dev'
import { readReadyDotUsbSerial } from '@/lib/desktop/usb-serial'
import './pendrive-indicator.css'

const POLL_INTERVAL_MS = 30_000

export function PendriveIndicator() {
  const [connected, setConnected] = useState(true)
  const reduceMotion = useReducedMotion()

  const checkPendrive = useCallback(async () => {
    if (isUsbGateSkipped()) {
      setConnected(true)
      return
    }

    try {
      const result = await readReadyDotUsbSerial()
      if (result.serial) {
        setConnected(true)
      } else {
        setConnected(false)
      }
    } catch {
      setConnected(false)
    }
  }, [])

  useEffect(() => {
    void checkPendrive()
    const interval = setInterval(() => {
      void checkPendrive()
    }, POLL_INTERVAL_MS)
    return () => clearInterval(interval)
  }, [checkPendrive])

  if (isUsbGateSkipped()) {
    return (
      <div className="pendrive-indicator">
        <span className="pendrive-indicator__dot pendrive-indicator__dot--dev" aria-hidden />
        <span className="pendrive-indicator__label">Modo desarrollo</span>
      </div>
    )
  }

  return (
    <motion.div
      className="pendrive-indicator"
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      transition={{ duration: reduceMotion ? 0 : 0.3 }}
    >
      <motion.span
        className={`pendrive-indicator__dot ${connected ? 'pendrive-indicator__dot--connected' : 'pendrive-indicator__dot--disconnected'}`}
        animate={
          !connected && !reduceMotion
            ? { scale: [1, 1.3, 1], opacity: [1, 0.6, 1] }
            : connected && !reduceMotion
              ? { scale: [1, 1.15, 1] }
              : {}
        }
        transition={{
          duration: reduceMotion ? 0 : 2,
          repeat: Infinity,
          ease: 'easeInOut',
        }}
        aria-hidden
      />
      <span className="pendrive-indicator__label">
        {connected ? 'Pendrive conectado' : 'Pendrive no detectado'}
      </span>
      {!connected ? (
        <p className="pendrive-indicator__hint">
          Retira y vuelve a insertar tu llave DOT.
        </p>
      ) : null}
    </motion.div>
  )
}
