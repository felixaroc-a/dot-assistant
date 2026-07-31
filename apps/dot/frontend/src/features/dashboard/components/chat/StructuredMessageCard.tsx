import { useState } from 'react'

import type { ChatStructuredCard } from './classifyAssistantMessage'

type StructuredMessageCardProps = {
  card: ChatStructuredCard
  fallbackText: string
}

function fileExt(name: string): string {
  const parts = name.split('.')
  return parts.length > 1 ? (parts.pop() || 'FILE').toUpperCase() : 'FILE'
}

export function StructuredMessageCard({ card, fallbackText }: StructuredMessageCardProps) {
  const [expanded, setExpanded] = useState(false)

  if (card.kind === 'generated_files') {
    return (
      <div className="dot-chat__struct-card dot-chat__struct-card--files" role="status">
        <div className="dot-chat__struct-card-head">
          <span className="dot-chat__struct-card-eyebrow">Archivos generados</span>
          <h4 className="dot-chat__struct-card-title">{card.title}</h4>
        </div>
        <ul className="dot-chat__struct-file-list">
          {card.files.map((file) => (
            <li key={`${file.name}-${file.path ?? ''}`} className="dot-chat__struct-file">
              <span className="dot-chat__struct-file-thumb" aria-hidden>
                {fileExt(file.name)}
              </span>
              <div className="dot-chat__struct-file-meta">
                <span className="dot-chat__struct-file-name">{file.name}</span>
                {file.path ? (
                  <span className="dot-chat__struct-file-path" title={file.path}>
                    {file.path}
                  </span>
                ) : null}
              </div>
            </li>
          ))}
        </ul>
        {card.body ? (
          <p className="dot-chat__struct-card-body">{card.body}</p>
        ) : null}
      </div>
    )
  }

  return (
    <div className="dot-chat__struct-card dot-chat__struct-card--error" role="alert">
      <div className="dot-chat__struct-card-head dot-chat__struct-card-head--error">
        <span className="dot-chat__struct-error-icon" aria-hidden>
          !
        </span>
        <div className="dot-chat__struct-card-head-text">
          <span className="dot-chat__struct-card-eyebrow">Error de ejecución</span>
          <h4 className="dot-chat__struct-card-title">{card.summary}</h4>
        </div>
      </div>
      {(card.details || fallbackText.length > card.summary.length) ? (
        <div className="dot-chat__struct-card-actions">
          <button
            type="button"
            className="dot-chat__struct-card-details-btn"
            onClick={() => setExpanded((v) => !v)}
            aria-expanded={expanded}
          >
            {expanded ? 'Ocultar detalles' : 'Ver detalles'}
          </button>
          {expanded ? (
            <pre className="dot-chat__struct-card-details">
              {card.details || fallbackText}
            </pre>
          ) : null}
        </div>
      ) : null}
    </div>
  )
}
