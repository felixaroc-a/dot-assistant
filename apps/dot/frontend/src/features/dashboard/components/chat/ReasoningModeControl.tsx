import { useCallback, useEffect, useId, useRef, useState } from 'react'

import type { ReasoningLevel } from '@/lib/chat/useReasoningMode'

type ReasoningModeControlProps = {
  enabled: boolean
  level: ReasoningLevel
  onEnabledChange: (enabled: boolean) => void
  onLevelChange: (level: ReasoningLevel) => void
  disabled?: boolean
}

type ModeOption = {
  key: string
  label: string
  hint: string
  enabled: boolean
  level?: ReasoningLevel
}

const MODE_OPTIONS: ModeOption[] = [
  { key: 'off', label: 'Rápido', hint: 'Respuesta directa, sin plan extra', enabled: false },
  { key: 'auto', label: 'Auto', hint: 'Elige según la tarea · ~+30% tokens', enabled: true, level: 'auto' },
  { key: 'low', label: 'Bajo', hint: 'Checklist interna · ~+20% tokens', enabled: true, level: 'low' },
  { key: 'medium', label: 'Medio', hint: 'Plan antes de actuar · ~+80% tokens', enabled: true, level: 'medium' },
  { key: 'high', label: 'Alto', hint: 'Plan profundo · ~+3× tokens', enabled: true, level: 'high' },
]

function currentLabel(enabled: boolean, level: ReasoningLevel): string {
  if (!enabled) return 'Rápido'
  const match = MODE_OPTIONS.find((o) => o.enabled && o.level === level)
  return match?.label ?? 'Auto'
}

function isSelected(option: ModeOption, enabled: boolean, level: ReasoningLevel): boolean {
  if (!option.enabled) return !enabled
  return enabled && option.level === level
}

function IconBrain() {
  return (
    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.75" aria-hidden>
      <path d="M9.5 2A5.5 5.5 0 0 0 4 7.5c0 .9.2 1.75.58 2.5A4 4 0 0 0 6 18h12a4 4 0 0 0 1.42-7.5A5.5 5.5 0 0 0 14.5 2" strokeLinecap="round" strokeLinejoin="round" />
      <path d="M12 2v16M9 10h6M9 14h4" strokeLinecap="round" />
    </svg>
  )
}

export function ReasoningModeControl({
  enabled,
  level,
  onEnabledChange,
  onLevelChange,
  disabled = false,
}: ReasoningModeControlProps) {
  const [open, setOpen] = useState(false)
  const rootRef = useRef<HTMLDivElement>(null)
  const menuId = useId()
  const label = currentLabel(enabled, level)

  const close = useCallback(() => setOpen(false), [])

  useEffect(() => {
    if (!open) return
    const onPointerDown = (event: MouseEvent) => {
      if (!rootRef.current?.contains(event.target as Node)) close()
    }
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') close()
    }
    document.addEventListener('mousedown', onPointerDown)
    document.addEventListener('keydown', onKeyDown)
    return () => {
      document.removeEventListener('mousedown', onPointerDown)
      document.removeEventListener('keydown', onKeyDown)
    }
  }, [close, open])

  const handleSelect = (option: ModeOption) => {
    if (!option.enabled) {
      onEnabledChange(false)
    } else {
      onEnabledChange(true)
      if (option.level) onLevelChange(option.level)
    }
    close()
  }

  return (
    <div className="dot-chat__reasoning-picker" ref={rootRef}>
      <button
        type="button"
        className={`dot-chat__reasoning-trigger${enabled ? ' dot-chat__reasoning-trigger--on' : ''}${open ? ' dot-chat__reasoning-trigger--open' : ''}`}
        disabled={disabled}
        aria-haspopup="listbox"
        aria-expanded={open}
        aria-controls={menuId}
        title="Modo de razonamiento"
        onClick={() => setOpen((prev) => !prev)}
      >
        <span className="dot-chat__reasoning-trigger-icon">
          <IconBrain />
        </span>
        <span className="dot-chat__reasoning-trigger-label">{label}</span>
        <svg className="dot-chat__reasoning-trigger-chevron" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" aria-hidden>
          <path d="M6 9l6 6 6-6" strokeLinecap="round" strokeLinejoin="round" />
        </svg>
      </button>

      {open ? (
        <div className="dot-chat__reasoning-menu" id={menuId} role="listbox" aria-label="Modo de razonamiento">
          <p className="dot-chat__reasoning-menu-title">Razonamiento</p>
          {MODE_OPTIONS.map((option) => {
            const selected = isSelected(option, enabled, level)
            return (
              <button
                key={option.key}
                type="button"
                role="option"
                aria-selected={selected}
                className={`dot-chat__reasoning-option${selected ? ' dot-chat__reasoning-option--selected' : ''}`}
                onClick={() => handleSelect(option)}
              >
                <span className="dot-chat__reasoning-option-main">
                  <span className="dot-chat__reasoning-option-label">{option.label}</span>
                  <span className="dot-chat__reasoning-option-hint">{option.hint}</span>
                </span>
                {selected ? (
                  <svg className="dot-chat__reasoning-option-check" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" aria-hidden>
                    <path d="M20 6L9 17l-5-5" strokeLinecap="round" strokeLinejoin="round" />
                  </svg>
                ) : null}
              </button>
            )
          })}
        </div>
      ) : null}
    </div>
  )
}
