import { useState, useCallback } from 'react'
import { useTranslation } from 'react-i18next'
import { useKeyboardShortcuts } from './use-keyboard-shortcuts'

interface ShortcutEntry {
  key: string
  ctrl?: boolean
  alt?: boolean
  shift?: boolean
  description: string
}

interface KeyboardShortcutsHelpProps {
  shortcuts: ShortcutEntry[]
}

export function KeyboardShortcutsHelp({ shortcuts }: KeyboardShortcutsHelpProps) {
  const { t } = useTranslation()
  const [open, setOpen] = useState(false)

  const toggle = useCallback(() => setOpen(v => !v), [])

  useKeyboardShortcuts([
    { key: '/', ctrl: true, handler: toggle, description: t('shortcuts.help_trigger_1') },
    { key: 'h', ctrl: true, handler: toggle, description: t('shortcuts.help_trigger_2') },
  ])

  const formatKey = (s: ShortcutEntry) => {
    const parts: string[] = []
    if (s.ctrl) parts.push('Ctrl')
    if (s.alt) parts.push('Alt')
    if (s.shift) parts.push('Shift')
    parts.push(s.key.toUpperCase())
    return parts.join(' + ')
  }

  if (!open) return null

  return (
    <div
      onClick={() => setOpen(false)}
      style={{
        position: 'fixed', inset: 0, zIndex: 9999,
        background: 'rgba(0,0,0,0.6)',
        display: 'flex', alignItems: 'center', justifyContent: 'center',
      }}
    >
      <div
        onClick={e => e.stopPropagation()}
        style={{
          background: 'var(--bg-secondary, #1c1c1e)',
          color: 'var(--text-primary, #eee)',
          borderRadius: '12px', padding: '2rem',
          maxWidth: '500px', width: '90%',
          maxHeight: '80vh', overflowY: 'auto',
        }}
      >
        <h2 style={{ margin: '0 0 1.5rem', color: 'var(--text-primary)' }}>{t('shortcuts.title')}</h2>
        {shortcuts.map((s, i) => (
          <div
            key={i}
            style={{
              display: 'flex',
              justifyContent: 'space-between',
              padding: '0.5rem 0',
              borderBottom: '1px solid var(--border-color, #333)',
            }}
          >
            <span>{s.description}</span>
            <kbd style={{
              background: 'var(--bg-card)',
              padding: '0.2rem 0.5rem', borderRadius: '4px',
              fontFamily: 'monospace', fontSize: '0.85rem',
              color: 'var(--text-primary)',
              border: '1px solid var(--border-color)',
            }}>
              {formatKey(s)}
            </kbd>
          </div>
        ))}
        <p style={{ marginTop: '1.5rem', textAlign: 'center', color: 'var(--text-muted, #666)', fontSize: '0.85rem' }}>
          {t('shortcuts.help_hint')}
        </p>
        <button
          onClick={() => setOpen(false)}
          style={{
            display: 'block', margin: '1rem auto 0',
            padding: '0.5rem 2rem', background: 'var(--accent)',
            color: 'var(--bg-primary)', border: 'none', borderRadius: '6px',
            cursor: 'pointer',
          }}
        >
          {t('shortcuts.close_button')}
        </button>
      </div>
    </div>
  )
}
