import { useState, useEffect, useCallback } from 'react'
import './quick-tips.css'

type Tip = {
  id: string
  icon: string
  text: string
}

const ALL_TIPS: Tip[] = [
  {
    id: 'plan',
    icon: '📋',
    text: 'Di "plan: hacer X" para que DOT planifique por ti paso a paso.',
  },
  {
    id: 'voice',
    icon: '🎤',
    text: 'Activa el modo escucha en el chat para hablar con DOT sin escribir.',
  },
  {
    id: 'memory',
    icon: '🧠',
    text: 'DOT recuerda lo que le dices — prueba decirle tu nombre o preferencias.',
  },
  {
    id: 'calendar',
    icon: '📅',
    text: 'Conecta tu calendario de Google para que DOT te recuerde tus citas y eventos.',
  },
  {
    id: 'whatsapp',
    icon: '💬',
    text: 'Tras vincular WhatsApp, crea un grupo llamado «DOT» (solo tú) y menciona @DOT cuando quieras que responda. No responde en chats 1:1.',
  },
  {
    id: 'files',
    icon: '📎',
    text: 'Arrastra documentos, imágenes o PDFs al chat para que DOT los lea y analice.',
  },
  {
    id: 'briefing',
    icon: '🌅',
    text: 'Cada mañana a las 7:30 DOT te prepara un briefing con lo importante del día.',
  },
  {
    id: 'images',
    icon: '🎨',
    text: 'Pídele a DOT que genere imágenes — solo describe lo que imaginas.',
  },
]

const DISMISSED_KEY = 'dot_quick_tips_dismissed'
const TIPS_PER_PAGE = 3

export function QuickTips() {
  const [dismissed, setDismissed] = useState<Set<string>>(() => {
    try {
      const raw = localStorage.getItem(DISMISSED_KEY)
      if (raw) return new Set(JSON.parse(raw) as string[])
    } catch {
      /* ignore */
    }
    return new Set()
  })
  const [page, setPage] = useState(0)
  const [permanentlyHidden, setPermanentlyHidden] = useState(
    localStorage.getItem('dot_quick_tips_hidden') === '1',
  )

  const visibleTips = ALL_TIPS.filter((t) => !dismissed.has(t.id))

  const totalPages = Math.max(1, Math.ceil(visibleTips.length / TIPS_PER_PAGE))
  const currentPage = Math.min(page, totalPages - 1)
  const pageTips = visibleTips.slice(currentPage * TIPS_PER_PAGE, (currentPage + 1) * TIPS_PER_PAGE)

  // Persist dismissed tips
  useEffect(() => {
    try {
      localStorage.setItem(DISMISSED_KEY, JSON.stringify([...dismissed]))
    } catch {
      /* ignore */
    }
  }, [dismissed])

  const dismissTip = useCallback((tipId: string) => {
    setDismissed((prev) => {
      const next = new Set(prev)
      next.add(tipId)
      return next
    })
  }, [])

  const hidePermanently = useCallback(() => {
    setPermanentlyHidden(true)
    localStorage.setItem('dot_quick_tips_hidden', '1')
  }, [])

  const nextPage = useCallback(() => {
    setPage((p) => Math.min(p + 1, totalPages - 1))
  }, [totalPages])

  const prevPage = useCallback(() => {
    setPage((p) => Math.max(p - 1, 0))
  }, [])

  if (permanentlyHidden || pageTips.length === 0) return null

  return (
    <div className="quick-tips">
      <div className="quick-tips__header">
        <p className="quick-tips__header-text">Consejos para aprovechar DOT</p>
        <button
          type="button"
          className="quick-tips__hide-all"
          onClick={hidePermanently}
          title="No mostrar más consejos"
        >
          No mostrar más
        </button>
      </div>

      <div className="quick-tips__grid">
        {pageTips.map((tip) => (
          <div key={tip.id} className="quick-tips__card">
            <span className="quick-tips__icon" aria-hidden>{tip.icon}</span>
            <p className="quick-tips__text">{tip.text}</p>
            <button
              type="button"
              className="quick-tips__dismiss"
              onClick={() => dismissTip(tip.id)}
              aria-label="Descartar consejo"
              title="Descartar"
            >
              ×
            </button>
          </div>
        ))}
      </div>

      {totalPages > 1 ? (
        <div className="quick-tips__pagination">
          <button
            type="button"
            className="quick-tips__page-btn"
            disabled={currentPage === 0}
            onClick={prevPage}
          >
            ← Anterior
          </button>
          <span className="quick-tips__page-indicator">
            {currentPage + 1} de {totalPages}
          </span>
          <button
            type="button"
            className="quick-tips__page-btn"
            disabled={currentPage >= totalPages - 1}
            onClick={nextPage}
          >
            Siguiente →
          </button>
        </div>
      ) : null}
    </div>
  )
}
