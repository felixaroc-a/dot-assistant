import { useState, useEffect, useCallback } from 'react'
import { useTranslation } from 'react-i18next'
import { hasRecoveryKeyLocal, saveRecoveryKeyLocal } from '../../lib/recovery-key-storage'

interface SaveRecoveryKeyBannerProps {
  recoveryKey: string
  onDismiss?: () => void
}

export function SaveRecoveryKeyBanner({ recoveryKey, onDismiss }: SaveRecoveryKeyBannerProps) {
  const { t } = useTranslation()
  const [dismissed, setDismissed] = useState(false)
  const [saved, setSaved] = useState(false)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    hasRecoveryKeyLocal()
      .then((exists) => {
        if (exists) setDismissed(true)
      })
      .catch(() => {})
  }, [])

  const handleSave = useCallback(async () => {
    setSaving(true)
    try {
      const ok = await saveRecoveryKeyLocal(recoveryKey)
      if (ok) {
        setSaved(true)
        setTimeout(() => {
          setDismissed(true)
          onDismiss?.()
        }, 3000)
      } else {
        setSaving(false)
        setError(t('auth.recovery_save_error'))
      }
    } finally {
      setSaving(false)
    }
  }, [recoveryKey, onDismiss, t])

  if (dismissed) return null

  return (
    <div
      style={{
        background: 'var(--bg-secondary)',
        border: '1px solid var(--border-color)',
        borderRadius: '12px',
        padding: '1.5rem',
        marginBottom: '1.5rem',
        color: 'var(--text-primary)',
      }}
    >
      <h3 style={{ margin: '0 0 0.5rem', color: 'var(--text-primary)' }}>
        {saved ? t('auth.recovery_saved_title') : t('auth.recovery_save_title')}
      </h3>

      {saved ? (
        <p>
          {t('auth.recovery_saved_message')}
        </p>
      ) : (
        <>
          <p style={{ margin: '0 0 1rem', color: 'var(--text-secondary)', fontSize: '0.9rem' }}>
            {t('auth.recovery_save_message')}
          </p>
          <div
            style={{
              background: 'var(--bg-primary)',
              padding: '0.75rem 1rem',
              borderRadius: '8px',
              fontFamily: 'monospace',
              fontSize: '1.1rem',
              letterSpacing: '0.15em',
              textAlign: 'center',
              color: 'var(--text-primary)',
              marginBottom: '1rem',
              border: '1px solid var(--border-color)',
            }}
          >
            {recoveryKey}
          </div>
          {error ? (
            <p style={{ color: 'var(--danger)', fontSize: '0.85rem', marginBottom: '0.5rem' }}>{error}</p>
          ) : null}
          <div style={{ display: 'flex', gap: '0.75rem', justifyContent: 'flex-end' }}>
            <button
              onClick={() => setDismissed(true)}
              style={{
                padding: '0.5rem 1.25rem',
                borderRadius: '6px',
                border: '1px solid var(--border-color)',
                background: 'transparent',
                color: 'var(--text-secondary)',
                cursor: 'pointer',
                fontSize: '0.85rem',
              }}
            >
              {t('auth.recovery_not_now')}
            </button>
            <button
              onClick={handleSave}
              disabled={saving}
              style={{
                padding: '0.5rem 1.25rem',
                borderRadius: '6px',
                border: 'none',
                background: 'var(--accent)',
                color: 'var(--bg-primary)',
                cursor: saving ? 'wait' : 'pointer',
                fontSize: '0.85rem',
                opacity: saving ? 0.7 : 1,
              }}
            >
              {saving ? t('auth.recovery_saving') : t('auth.recovery_save_button')}
            </button>
          </div>
        </>
      )}
    </div>
  )
}
