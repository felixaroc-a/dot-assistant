import { useEffect, useMemo, useState } from 'react'

import type { ChatAttachment } from '@/lib/chat/types'

export function FileAttachment({
  attachment,
  isUser = false,
}: {
  attachment: ChatAttachment
  isUser?: boolean
}) {
  const isImage = attachment.type.startsWith('image/')
  const isPdf = attachment.type === 'application/pdf'
  const fileSize = formatSize(attachment.size)
  const [imageError, setImageError] = useState(false)
  useEffect(() => {
    setImageError(false)
  }, [attachment.data, isImage])
  const shouldShowImage = isImage && attachment.data && !imageError

  const handleImageError = () => {
    setImageError(true)
  }

  return (
    <div className={`dot-chat__file-attachment ${isUser ? 'dot-chat__file-attachment--user' : ''}`}>
      {shouldShowImage ? (
        <div className="dot-chat__file-attachment-image-wrap">
          <img
            className="dot-chat__file-attachment-image"
            src={attachment.data ?? ''}
            alt={attachment.name}
            loading="lazy"
            onError={handleImageError}
            onLoad={() => setImageError(false)}
          />
        </div>
      ) : (
        <div
          className={`dot-chat__file-attachment-icon ${
            isImage ? 'dot-chat__file-attachment-icon--placeholder' : ''
          }`}
        >
          {isPdf ? <PdfIcon /> : <GenericFileIcon />}
        </div>
      )}

      <div className="dot-chat__file-attachment-info">
        <span className="dot-chat__file-attachment-name" title={attachment.name}>
          {attachment.name}
        </span>
        {attachment.size > 0 ? (
          <span className="dot-chat__file-attachment-size">{fileSize}</span>
        ) : null}
      </div>

      {attachment.data && (
        <a
          className="dot-chat__file-attachment-download"
          href={attachment.data}
          download={attachment.name}
          title="Descargar archivo"
          target="_blank"
          rel="noopener noreferrer"
        >
          <DownloadIcon />
        </a>
      )}
    </div>
  )
}

export function AttachmentPreview({
  file,
  onRemove,
}: {
  file: File
  onRemove: () => void
}) {
  const isImage = file.type.startsWith('image/')
  const objectUrl = useMemo(() => {
    if (!isImage) return null
    if (typeof URL === 'undefined' || typeof URL.createObjectURL !== 'function') {
      return null
    }
    return URL.createObjectURL(file)
  }, [file, isImage])
  const [imageError, setImageError] = useState(false)

  useEffect(() => {
    return () => {
      if (
        objectUrl &&
        typeof URL !== 'undefined' &&
        typeof URL.revokeObjectURL === 'function'
      ) {
        URL.revokeObjectURL(objectUrl)
      }
    }
  }, [objectUrl])

  useEffect(() => {
    setImageError(false)
  }, [file])

  return (
    <div className="dot-chat__attachment-preview">
      {isImage && objectUrl && !imageError ? (
        <img
          className="dot-chat__attachment-preview-thumb"
          src={objectUrl}
          alt={file.name}
          onError={() => setImageError(true)}
          onLoad={() => setImageError(false)}
        />
      ) : (
        <div className="dot-chat__attachment-preview-thumb-placeholder">
          {file.type === 'application/pdf' ? <PdfIcon /> : <GenericFileIcon />}
        </div>
      )}

      <div className="dot-chat__attachment-preview-info">
        <span className="dot-chat__attachment-preview-name">{file.name}</span>
        <span className="dot-chat__attachment-preview-size">{formatSize(file.size)}</span>
      </div>

      <button
        type="button"
        className="dot-chat__attachment-preview-remove"
        onClick={onRemove}
        title="Quitar archivo"
      >
        <CloseIcon />
      </button>
    </div>
  )
}

function formatSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
}

function PdfIcon() {
  return (
    <svg width="28" height="28" viewBox="0 0 24 24" fill="none" aria-hidden>
      <rect x="3" y="2" width="18" height="20" rx="2" stroke="#f0625c" strokeWidth="1.5" fill="rgba(240,98,92,0.12)" />
      <path d="M7 7h10M7 12h10M7 17h6" stroke="#f0625c" strokeWidth="1.5" strokeLinecap="round" />
    </svg>
  )
}

function GenericFileIcon() {
  return (
    <svg width="28" height="28" viewBox="0 0 24 24" fill="none" aria-hidden>
      <rect x="3" y="2" width="18" height="20" rx="2" stroke="currentColor" strokeWidth="1.5" fill="rgba(255,255,255,0.06)" />
      <path d="M7 7h10M7 12h10M7 17h6" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
    </svg>
  )
}

function DownloadIcon() {
  return (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden>
      <path d="M21 15v4a2 2 0 01-2 2H5a2 2 0 01-2-2v-4" />
      <polyline points="7 10 12 15 17 10" />
      <line x1="12" y1="15" x2="12" y2="3" />
    </svg>
  )
}

function CloseIcon() {
  return (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden>
      <line x1="18" y1="6" x2="6" y2="18" />
      <line x1="6" y1="6" x2="18" y2="18" />
    </svg>
  )
}
