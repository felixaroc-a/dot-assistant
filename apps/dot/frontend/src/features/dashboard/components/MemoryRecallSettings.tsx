import { useCallback, useEffect, useState } from 'react'

import { apiFetchAuthed } from '@/lib/api/client'
import type { GetAccessToken } from '@/lib/api/client'

type MemoryFact = {
  fact_id: string
  type?: string | null
  key?: string | null
  value?: string | null
  confidence?: number | null
  updated_at?: string | null
}

type MemoryOverview = {
  summary: string
  facts: MemoryFact[]
  total: number
}

export type MemoryRecallSettingsProps = {
  getAccessToken: GetAccessToken
}

function formatFactLabel(fact: MemoryFact): string {
  const value = (fact.value || '').trim()
  if (value) return value
  const key = (fact.key || '').trim()
  if (key) return key
  return 'Dato guardado'
}

function formatFactMeta(fact: MemoryFact): string | null {
  const parts: string[] = []
  const key = (fact.key || '').trim()
  const value = (fact.value || '').trim()
  if (key && value && key.toLowerCase() !== value.toLowerCase()) {
    parts.push(key.replace(/_/g, ' '))
  }
  if (fact.updated_at) {
    try {
      parts.push(
        new Date(fact.updated_at).toLocaleDateString('es', {
          day: 'numeric',
          month: 'short',
          year: 'numeric',
        }),
      )
    } catch {
      // ignore invalid dates
    }
  }
  return parts.length > 0 ? parts.join(' · ') : null
}

export function MemoryRecallSettings({ getAccessToken }: MemoryRecallSettingsProps) {
  const [overview, setOverview] = useState<MemoryOverview | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [forgettingId, setForgettingId] = useState<string | null>(null)

  const load = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const data = await apiFetchAuthed<MemoryOverview>(
        '/v1/memory',
        { method: 'GET' },
        getAccessToken,
      )
      setOverview(data)
    } catch {
      setError('No se pudo cargar lo que recuerdo de ti.')
    } finally {
      setLoading(false)
    }
  }, [getAccessToken])

  useEffect(() => {
    void load()
  }, [load])

  const forgetFact = useCallback(
    async (factId: string) => {
      setForgettingId(factId)
      setError(null)
      try {
        await apiFetchAuthed<{ ok: boolean }>(
          `/v1/memory/facts/${encodeURIComponent(factId)}`,
          { method: 'DELETE' },
          getAccessToken,
        )
        setOverview((prev) => {
          if (!prev) return prev
          const facts = prev.facts.filter((fact) => fact.fact_id !== factId)
          return { ...prev, facts, total: facts.length }
        })
      } catch {
        setError('No se pudo olvidar ese dato. Intenta de nuevo.')
      } finally {
        setForgettingId(null)
      }
    },
    [getAccessToken],
  )

  if (loading) {
    return <p className="settings-section__desc">Cargando memoria…</p>
  }

  if (!overview) {
    return <p className="settings-section__desc">{error || 'Memoria no disponible.'}</p>
  }

  const summary = overview.summary.trim()
  const hasFacts = overview.facts.length > 0
  const isEmpty = !summary && !hasFacts

  return (
    <div className="memory-recall">
      <p className="settings-section__desc">
        Estos son los datos personales que DOT guarda para personalizar tus conversaciones.
        Puedes olvidar cualquier dato cuando quieras.
      </p>

      {error ? <p className="memory-recall__error" role="alert">{error}</p> : null}

      {summary ? (
        <div className="settings-section__card memory-recall__summary">
          <h4 className="settings-section__subtitle">Resumen</h4>
          <p className="memory-recall__summary-text">{summary}</p>
        </div>
      ) : null}

      {hasFacts ? (
        <ul className="memory-recall__list" aria-label="Hechos recordados">
          {overview.facts.map((fact) => {
            const meta = formatFactMeta(fact)
            const busy = forgettingId === fact.fact_id
            return (
              <li key={fact.fact_id} className="memory-recall__item">
                <div className="memory-recall__item-body">
                  <p className="memory-recall__item-text">{formatFactLabel(fact)}</p>
                  {meta ? <p className="memory-recall__item-meta">{meta}</p> : null}
                </div>
                <button
                  type="button"
                  className="memory-recall__forget-btn"
                  onClick={() => void forgetFact(fact.fact_id)}
                  disabled={busy}
                  aria-label={`Olvidar: ${formatFactLabel(fact)}`}
                >
                  {busy ? '…' : 'Olvidar'}
                </button>
              </li>
            )
          })}
        </ul>
      ) : null}

      {isEmpty ? (
        <div className="settings-section__card memory-recall__empty">
          <p className="settings-section__desc">
            Aún no guardo datos personales tuyos. Cuando me cuentes algo relevante en el chat,
            aparecerá aquí.
          </p>
        </div>
      ) : null}
    </div>
  )
}
