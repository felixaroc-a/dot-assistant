import { useEffect, useState } from 'react'

import type { ReasoningPlan } from '@/lib/chat/types'

type ReasoningPhaseIndicatorProps = {
  phase: 'analyzing' | 'planning' | 'executing'
  level?: string
}

const PHASE_LABELS: Record<ReasoningPhaseIndicatorProps['phase'], string> = {
  analyzing: 'Analizando tu petición',
  planning: 'Planificando pasos',
  executing: 'Ejecutando con tools',
}

export function ReasoningPhaseIndicator({ phase, level }: ReasoningPhaseIndicatorProps) {
  return (
    <div className="dot-chat__reasoning-phase" role="status" aria-live="polite">
      <span className="dot-chat__reasoning-phase-spinner" aria-hidden />
      <span className="dot-chat__reasoning-phase-text">{PHASE_LABELS[phase]}…</span>
      {level ? <span className="dot-chat__reasoning-phase-badge">{level}</span> : null}
    </div>
  )
}

type ReasoningPlanCardProps = {
  plan: ReasoningPlan
  /** Abrir automáticamente mientras llega la respuesta */
  live?: boolean
}

export function ReasoningPlanCard({ plan, live = false }: ReasoningPlanCardProps) {
  const [open, setOpen] = useState(() => live)
  const [userToggled, setUserToggled] = useState(false)

  useEffect(() => {
    if (live && !userToggled) setOpen(true)
  }, [live, plan.summary, userToggled])

  if (!plan.summary && !plan.steps.length) return null

  return (
    <div className={`dot-chat__reasoning-plan${live ? ' dot-chat__reasoning-plan--live' : ''}`}>
      <button
        type="button"
        className="dot-chat__reasoning-plan-toggle"
        onClick={() => {
          setUserToggled(true)
          setOpen((prev) => !prev)
        }}
        aria-expanded={open}
      >
        <span>Plan de DOT</span>
        <span className="dot-chat__reasoning-plan-badge">{plan.level}</span>
        <span aria-hidden>{open ? '▾' : '▸'}</span>
      </button>
      {!open && plan.summary ? (
        <p className="dot-chat__reasoning-plan-preview">{plan.summary}</p>
      ) : null}
      {open ? (
        <div className="dot-chat__reasoning-plan-body">
          {plan.summary ? <p>{plan.summary}</p> : null}
          {plan.steps.length ? (
            <ol>
              {plan.steps.map((step, index) => (
                <li key={`${index}-${step.slice(0, 24)}`}>{step}</li>
              ))}
            </ol>
          ) : null}
        </div>
      ) : null}
    </div>
  )
}
