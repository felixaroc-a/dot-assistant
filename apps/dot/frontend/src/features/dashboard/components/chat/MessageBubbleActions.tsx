import { MIN_SUMMARIZE_LENGTH } from './messageActionText'

type MessageBubbleActionsProps = {
  text: string
  loading?: boolean
  onTranslate?: (text: string) => void
  onSummarize?: (text: string) => void
}

export function MessageBubbleActions({
  text,
  loading = false,
  onTranslate,
  onSummarize,
}: MessageBubbleActionsProps) {
  if (!onTranslate && !onSummarize) return null

  const canSummarize = Boolean(onSummarize && text.length >= MIN_SUMMARIZE_LENGTH)
  if (!onTranslate && !canSummarize) return null

  return (
    <div className="dot-chat__bubble-actions" role="group" aria-label="Acciones del mensaje">
      {onTranslate ? (
        <button
          type="button"
          className="dot-chat__bubble-action-btn"
          disabled={loading}
          onClick={() => onTranslate(text)}
        >
          {loading ? '…' : 'Traducir'}
        </button>
      ) : null}
      {canSummarize ? (
        <button
          type="button"
          className="dot-chat__bubble-action-btn"
          disabled={loading}
          onClick={() => onSummarize?.(text)}
        >
          {loading ? '…' : 'Resumir'}
        </button>
      ) : null}
    </div>
  )
}
