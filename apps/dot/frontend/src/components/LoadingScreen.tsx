import { useTranslation } from 'react-i18next'
import type { CSSProperties, ReactNode } from 'react'

import './loading-screen.css'

export type LoadingScreenProps = {
  message?: string
  className?: string
  children?: ReactNode
}

export function LoadingScreen({ message, className, children }: LoadingScreenProps) {
  useTranslation()
  const rootClass = ['loading-screen', className].filter(Boolean).join(' ')

  return (
    <div className={rootClass} role="status" aria-live="polite">
      <div className="loading-screen__orbit" aria-hidden="true">
        {Array.from({ length: 8 }, (_, index) => (
          <span key={index} className="loading-screen__dot" style={{ '--i': index } as CSSProperties} />
        ))}
      </div>
      {message ? <p className="loading-screen__text">{message}</p> : null}
      {children}
    </div>
  )
}
