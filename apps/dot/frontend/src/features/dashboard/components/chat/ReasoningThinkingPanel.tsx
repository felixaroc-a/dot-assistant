import { useEffect, useMemo, useState } from 'react'

import type { ReasoningPlan } from '@/lib/chat/types'

type ReasoningPhase = 'analyzing' | 'planning' | 'executing'

type ReasoningThinkingPanelProps = {
  phase?: ReasoningPhase
  level?: string
  plan?: ReasoningPlan
  toolActivity?: string
  live: boolean
}

type StepState = 'pending' | 'active' | 'done'

type TimelineStep = {
  id: string
  label: string
  state: StepState
}

const PHASE_RANK: Record<ReasoningPhase, number> = {
  analyzing: 0,
  planning: 1,
  executing: 2,
}

function maxPhase(a?: ReasoningPhase, b?: ReasoningPhase): ReasoningPhase | undefined {
  if (!a) return b
  if (!b) return a
  return PHASE_RANK[b] > PHASE_RANK[a] ? b : a
}

function buildTimeline(phase?: ReasoningPhase, hasPlan?: boolean, live?: boolean): TimelineStep[] {
  const labels = [
    'Entender tu petición',
    'Armar un plan de acción',
    'Ejecutar y verificar',
  ]

  let activeIndex = 0
  if (phase === 'planning') activeIndex = 1
  else if (phase === 'executing') activeIndex = 2
  else if (!phase && hasPlan && !live) activeIndex = 3
  else if (!phase && hasPlan) activeIndex = 2

  return labels.map((label, index) => {
    let state: StepState = 'pending'
    if (activeIndex >= 3 || index < activeIndex) state = 'done'
    else if (index === activeIndex) state = 'active'
    return { id: String(index), label, state }
  })
}

function levelLabel(level?: string): string {
  const map: Record<string, string> = {
    auto: 'Auto',
    low: 'Bajo',
    medium: 'Medio',
    high: 'Alto',
  }
  return map[level || ''] || level || 'DOT'
}

function useVisualPhase(
  serverPhase: ReasoningPhase | undefined,
  live: boolean,
  hasPlan: boolean,
): ReasoningPhase | undefined {
  const [visualPhase, setVisualPhase] = useState<ReasoningPhase | undefined>(
    live ? 'analyzing' : serverPhase,
  )

  useEffect(() => {
    if (serverPhase) {
      setVisualPhase((current) => maxPhase(current, serverPhase))
    }
  }, [serverPhase])

  useEffect(() => {
    if (hasPlan) {
      setVisualPhase((current) => maxPhase(current, 'executing'))
    }
  }, [hasPlan])

  useEffect(() => {
    if (!live) return

    const timers = [
      window.setTimeout(() => {
        setVisualPhase((current) => maxPhase(current, 'planning'))
      }, 900),
      window.setTimeout(() => {
        setVisualPhase((current) => maxPhase(current, 'executing'))
      }, 2200),
    ]

    return () => {
      timers.forEach((id) => window.clearTimeout(id))
    }
  }, [live])

  return visualPhase
}

export function ReasoningThinkingPanel({
  phase,
  level,
  plan,
  toolActivity,
  live,
}: ReasoningThinkingPanelProps) {
  const [open, setOpen] = useState(live)
  const [userToggled, setUserToggled] = useState(false)
  const hasPlan = Boolean(plan?.steps.length || plan?.summary)
  const displayPhase = useVisualPhase(
    toolActivity ? 'executing' : phase,
    live,
    hasPlan,
  )

  useEffect(() => {
    if (live && !userToggled) setOpen(true)
  }, [live, plan?.summary, userToggled])

  const timeline = useMemo(
    () => buildTimeline(displayPhase, hasPlan, live),
    [displayPhase, hasPlan, live],
  )

  const headerText = live
    ? displayPhase === 'planning'
      ? 'Planificando'
      : displayPhase === 'executing'
        ? plan
          ? 'Ejecutando el plan'
          : 'Ejecutando'
        : 'Pensando'
    : 'Pensamiento de DOT'

  if (!live && !plan && !phase) return null

  return (
    <div className={`dot-chat__thinking${live ? ' dot-chat__thinking--live' : ''}`}>
      <button
        type="button"
        className="dot-chat__thinking-header"
        onClick={() => {
          setUserToggled(true)
          setOpen((prev) => !prev)
        }}
        aria-expanded={open}
      >
        <span className="dot-chat__thinking-sparkle" aria-hidden>
          ✦
        </span>
        <span className={`dot-chat__thinking-title${live ? ' dot-chat__thinking-title--shimmer' : ''}`}>
          {headerText}
        </span>
        {level ? <span className="dot-chat__thinking-level">{levelLabel(level)}</span> : null}
        <span className="dot-chat__thinking-chevron" aria-hidden>
          {open ? '▾' : '▸'}
        </span>
      </button>

      {open ? (
        <div className="dot-chat__thinking-body">
          <ul className="dot-chat__thinking-timeline">
            {timeline.map((step) => (
              <li
                key={step.id}
                className={`dot-chat__thinking-step dot-chat__thinking-step--${step.state}`}
              >
                <span className="dot-chat__thinking-step-marker" aria-hidden>
                  {step.state === 'done' ? '✓' : step.state === 'active' ? '●' : '○'}
                </span>
                <span>{step.label}</span>
              </li>
            ))}
          </ul>

          {toolActivity && live ? (
            <p className="dot-chat__thinking-tool">
              <span className="dot-chat__thinking-tool-label">Tool</span>
              {toolActivity}
            </p>
          ) : null}

          {plan?.summary ? (
            <div className="dot-chat__thinking-plan">
              <p className="dot-chat__thinking-plan-summary">{plan.summary}</p>
              {plan.steps.length ? (
                <ol className="dot-chat__thinking-plan-steps">
                  {plan.steps.map((step, index) => (
                    <li key={`${index}-${step.slice(0, 20)}`}>{step}</li>
                  ))}
                </ol>
              ) : null}
            </div>
          ) : live && displayPhase === 'planning' ? (
            <p className="dot-chat__thinking-placeholder">
              Generando pasos antes de actuar…
            </p>
          ) : live && displayPhase === 'executing' && !plan ? (
            <p className="dot-chat__thinking-placeholder">
              Preparando herramientas y verificando resultado…
            </p>
          ) : null}
        </div>
      ) : plan?.summary ? (
        <p className="dot-chat__thinking-collapsed">{plan.summary}</p>
      ) : null}
    </div>
  )
}
