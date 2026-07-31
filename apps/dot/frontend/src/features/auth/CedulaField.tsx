import { useCallback, useEffect, useRef, useState } from 'react'

const PREFIX_OPTIONS = ['E', 'J', 'V'] as const
type CedulaPrefix = (typeof PREFIX_OPTIONS)[number]

const DIGITS_REGEX = /^\d{6,10}$/

interface CedulaFieldProps {
  /** Se dispara con el valor combinado (ej: "E12345678") */
  onChange: (value: string) => void
  /** Se dispara cuando la validez del formato cambia */
  onValidityChange: (valid: boolean) => void
  disabled?: boolean
}

export function CedulaField({ onChange, onValidityChange, disabled }: CedulaFieldProps) {
  const [prefix, setPrefix] = useState<CedulaPrefix>('E')
  const [digits, setDigits] = useState('')
  const prevCombinedRef = useRef('')

  const combined = `${prefix}${digits}`
  const digitsValid = DIGITS_REGEX.test(digits)
  const valid = digitsValid

  // Notificar al padre cuando cambia el valor combinado
  useEffect(() => {
    if (prevCombinedRef.current !== combined) {
      prevCombinedRef.current = combined
      onChange(combined)
    }
  }, [combined, onChange])

  // Notificar al padre cuando cambia la validez
  useEffect(() => {
    onValidityChange(valid)
  }, [valid, onValidityChange])

  // Solo permitir dígitos, máximo 10
  const handleDigitsChange = useCallback((e: React.ChangeEvent<HTMLInputElement>) => {
    const raw = e.target.value.replace(/\D/g, '')
    setDigits(raw.slice(0, 10))
  }, [])

  const showError = digits.length > 0 && !digitsValid

  return (
    <label className="login-gate__label">
      Cédula
      <div className="cedula-field">
        <select
          className="cedula-field__prefix"
          value={prefix}
          onChange={(e) => setPrefix(e.target.value as CedulaPrefix)}
          disabled={disabled}
          aria-label="Prefijo de cédula"
        >
          {PREFIX_OPTIONS.map((p) => (
            <option key={p} value={p}>
              {p}
            </option>
          ))}
        </select>
        <input
          className="cedula-field__input"
          type="text"
          inputMode="numeric"
          autoComplete="username"
          value={digits}
          onChange={handleDigitsChange}
          disabled={disabled}
          placeholder="12345678"
          maxLength={10}
        />
      </div>
      {showError ? (
        <p className="cedula-field__error" role="alert">
          La cédula debe tener entre 6 y 10 dígitos numéricos.
        </p>
      ) : null}
    </label>
  )
}
