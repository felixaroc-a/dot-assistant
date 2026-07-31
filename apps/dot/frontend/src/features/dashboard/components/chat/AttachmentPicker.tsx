import { useCallback, useRef } from 'react'

import { validateVisionImage, IMAGE_ACCEPTED_TYPES } from './visionImageValidation'

export type AttachmentPickerProps = {
  onFileSelected: (file: File) => void
  disabled?: boolean
}

const ACCEPTED_TYPES = [
  'image/jpeg',
  'image/png',
  'image/gif',
  'image/webp',
  'application/pdf',
  'text/plain',
  'text/csv',
  'application/json',
  'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
  'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
]

const MAX_FILE_SIZE = 20 * 1024 * 1024 // 20 MB

export function AttachmentPicker({ onFileSelected, disabled = false }: AttachmentPickerProps) {
  const inputRef = useRef<HTMLInputElement>(null)

  const handleClick = useCallback(() => {
    inputRef.current?.click()
  }, [])

  const handleChange = useCallback(
    (e: React.ChangeEvent<HTMLInputElement>) => {
      const file = e.target.files?.[0]
      if (!file) return

      if (file.size > MAX_FILE_SIZE) {
        alert(`El archivo es demasiado grande. Tamaño máximo: 20 MB`)
        e.target.value = ''
        return
      }

      if (!ACCEPTED_TYPES.includes(file.type)) {
        alert(`Tipo de archivo no soportado: ${file.type}`)
        e.target.value = ''
        return
      }

      onFileSelected(file)
      e.target.value = ''
    },
    [onFileSelected],
  )

  return (
    <>
      <button
        type="button"
        className="dot-chat__icon-btn dot-chat__icon-btn--attach"
        onClick={handleClick}
        disabled={disabled}
        title="Adjuntar archivo"
      >
        <svg width="20" height="20" viewBox="0 0 24 24" fill="none" aria-hidden>
          <path
            d="M17.35 5.65L8.4 14.6a3 3 0 104.24 4.24l8.2-8.2a4.5 4.5 0 10-6.36-6.36l-8.6 8.6"
            stroke="currentColor"
            strokeWidth="1.75"
            strokeLinecap="round"
            strokeLinejoin="round"
          />
        </svg>
      </button>
      <input
        ref={inputRef}
        type="file"
        className="dot-chat__file-input"
        accept={ACCEPTED_TYPES.join(',')}
        onChange={handleChange}
        aria-hidden="true"
        tabIndex={-1}
      />
    </>
  )
}

export function AttachmentImagePicker({
  onFileSelected,
  disabled = false,
}: AttachmentPickerProps) {
  const inputRef = useRef<HTMLInputElement>(null)

  const handleClick = useCallback(() => {
    inputRef.current?.click()
  }, [])

  const handleChange = useCallback(
    (e: React.ChangeEvent<HTMLInputElement>) => {
      const file = e.target.files?.[0]
      if (!file) return

      const validationError = validateVisionImage(file)
      if (validationError) {
        alert(validationError)
        e.target.value = ''
        return
      }

      onFileSelected(file)
      e.target.value = ''
    },
    [onFileSelected],
  )

  return (
    <>
      <button
        type="button"
        className="dot-chat__icon-btn dot-chat__icon-btn--attach"
        onClick={handleClick}
        disabled={disabled}
        title="Adjuntar imagen"
      >
        <svg width="20" height="20" viewBox="0 0 24 24" fill="none" aria-hidden>
          <rect x="3" y="5" width="18" height="14" rx="2.25" stroke="currentColor" strokeWidth="1.75" />
          <circle cx="8.25" cy="10" r="1.25" fill="currentColor" />
          <path
            d="M21 16l-4.8-4.8a1.2 1.2 0 00-1.7 0L8 18"
            stroke="currentColor"
            strokeWidth="1.75"
            strokeLinecap="round"
            strokeLinejoin="round"
          />
        </svg>
      </button>
      <input
        ref={inputRef}
        type="file"
        className="dot-chat__file-input"
        accept={IMAGE_ACCEPTED_TYPES.join(',')}
        onChange={handleChange}
        aria-hidden="true"
        tabIndex={-1}
      />
    </>
  )
}
