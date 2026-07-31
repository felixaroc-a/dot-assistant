import { useTranslation } from 'react-i18next'
import { motion, AnimatePresence, useReducedMotion } from 'framer-motion'
import { createPortal } from 'react-dom'

import './login-gate.css'

export type LogoutConfirmModalProps = {
  open: boolean
  onCancel: () => void
  onConfirm: () => void
}

export function LogoutConfirmModal({
  open,
  onCancel,
  onConfirm,
}: LogoutConfirmModalProps) {
  const { t } = useTranslation()
  const reduceMotion = useReducedMotion()

  return createPortal(
    <AnimatePresence>
      {open ? (
        <motion.div
          key="logout-overlay"
          className="logout-modal__overlay"
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
          transition={{ duration: reduceMotion ? 0.08 : 0.2 }}
        >
          <motion.div
            key="logout-backdrop"
            className="logout-modal__backdrop"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            transition={{ duration: reduceMotion ? 0.08 : 0.2 }}
            onClick={onCancel}
            aria-hidden
          />
          <motion.div
            key="logout-modal"
            className="logout-modal"
            role="dialog"
            aria-modal="true"
            aria-labelledby="logout-modal-title"
            initial={{ opacity: 0, scale: reduceMotion ? 1 : 0.94 }}
            animate={{ opacity: 1, scale: 1 }}
            exit={{ opacity: 0, scale: reduceMotion ? 1 : 0.94 }}
            transition={{
              duration: reduceMotion ? 0.08 : 0.25,
              ease: reduceMotion ? 'linear' : ([0.16, 1, 0.3, 1] as const),
            }}
          >
            <div className="logout-modal__icon" aria-hidden>
              <svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
                <path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4" />
                <polyline points="16 17 21 12 16 7" />
                <line x1="21" y1="12" x2="9" y2="12" />
              </svg>
            </div>
            <h2 id="logout-modal-title" className="logout-modal__title">
              {t('auth.confirm_logout_title')}
            </h2>
            <p className="logout-modal__desc">
              {t('auth.confirm_logout_desc')}
            </p>
            <div className="logout-modal__actions">
              <button
                type="button"
                className="logout-modal__btn logout-modal__btn--cancel"
                onClick={onCancel}
              >
                {t('auth.cancel')}
              </button>
              <button
                type="button"
                className="logout-modal__btn logout-modal__btn--confirm"
                onClick={onConfirm}
              >
                {t('auth.confirm_logout')}
              </button>
            </div>
          </motion.div>
        </motion.div>
      ) : null}
    </AnimatePresence>,
    document.body,
  )
}
