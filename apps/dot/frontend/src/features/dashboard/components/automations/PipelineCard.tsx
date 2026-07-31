import { motion, useReducedMotion } from 'framer-motion'
import type { PipelineDef } from '@/features/dashboard/model/types'

type PipelineCardProps = {
  pipeline: PipelineDef
  selected?: boolean
  onSelect?: (id: string) => void
  onExecuteNow?: (id: string) => void
  onToggleActive?: (id: string) => void
  onEdit?: (id: string) => void
  onDelete?: (id: string) => void
  onSaveAsTemplate?: (pipeline: PipelineDef) => void
  savingTemplate?: boolean
}

function formatLastRun(dateStr: string | null): string {
  if (!dateStr) return 'Nunca'
  const date = new Date(dateStr)
  const now = new Date()
  const diffMin = Math.floor((now.getTime() - date.getTime()) / 60000)
  if (diffMin < 1) return 'Ahora'
  if (diffMin < 60) return `Hace ${diffMin} min`
  const diffHour = Math.floor(diffMin / 60)
  if (diffHour < 24) return `Hace ${diffHour}h`
  return date.toLocaleDateString('es-ES', { day: 'numeric', month: 'short' })
}

function getScheduleLabel(schedule: string): string {
  if (schedule === 'manual') return 'Manual'
  if (schedule.startsWith('daily:')) {
    const parts = schedule.split(':')
    return `Diario ${parts[1]}:${parts[2] || '00'}`
  }
  if (schedule.startsWith('weekly:')) {
    const parts = schedule.split(':')
    const days: Record<string, string> = {
      mon: 'Lun', tue: 'Mar', wed: 'Mie', thu: 'Jue', fri: 'Vie', sat: 'Sab', sun: 'Dom',
    }
    return `Semanal ${days[parts[1]] || parts[1]} ${parts[2]}:${parts[3] || '00'}`
  }
  return schedule
}

function getStepIcon(integration: string): string {
  const icons: Record<string, string> = {
    gmail: '\u2709',
    'google-calendar': '\u{1F4C5}',
    chat: '\u{1F916}',
    whatsapp: '\u{1F4AC}',
    web_search: '\u{1F50D}',
    file: '\u{1F4C4}',
    condition: '\u{1F500}',
    output: '\u{1F514}',
  }
  return icons[integration] || '\u25CF'
}

export function PipelineCard({
  pipeline,
  selected = false,
  onSelect,
  onExecuteNow,
  onToggleActive,
  onEdit,
  onDelete,
  onSaveAsTemplate,
  savingTemplate,
}: PipelineCardProps) {
  const reduceMotion = useReducedMotion()

  return (
    <motion.li
      className={`main-dashboard__list-item main-dashboard__list-item--pipeline${selected ? ' main-dashboard__list-item--selected' : ''}`}
      initial={reduceMotion ? false : { opacity: 0, x: -8 }}
      animate={{ opacity: 1, x: 0 }}
      transition={{ duration: 0.22 }}
      layout
      onClick={() => onSelect?.(pipeline.id)}
      onKeyDown={(e) => {
        if (e.key === 'Enter' || e.key === ' ') {
          e.preventDefault()
          onSelect?.(pipeline.id)
        }
      }}
      role={onSelect ? 'button' : undefined}
      tabIndex={onSelect ? 0 : undefined}
      aria-pressed={onSelect ? selected : undefined}
    >
      <div className="main-dashboard__pipeline-info">
        <div className="main-dashboard__pipeline-header">
          <span className="main-dashboard__pipeline-icon" aria-hidden>{'\u{1F3C3}'}</span>
          <div className="main-dashboard__list-text-group">
            <p className="main-dashboard__list-text">{pipeline.name}</p>
            <div className="main-dashboard__pipeline-badges">
              <span className={`main-dashboard__auto-badge ${pipeline.active ? 'main-dashboard__auto-badge--active' : 'main-dashboard__auto-badge--inactive'}`}>
                {pipeline.active ? 'Activo' : 'Inactivo'}
              </span>
              {selected ? (
                <span className="main-dashboard__auto-badge main-dashboard__auto-badge--watching">
                  En panel
                </span>
              ) : null}
            </div>
          </div>
        </div>

        <div className="main-dashboard__pipeline-meta">
          <span className="main-dashboard__pipeline-schedule">{getScheduleLabel(pipeline.schedule)}</span>
          <span className="main-dashboard__pipeline-steps">{pipeline.steps.length} pasos</span>
          <span className="main-dashboard__pipeline-lastrun">Ultima: {formatLastRun(pipeline.last_run)}</span>
        </div>

        <div className="main-dashboard__pipeline-chain">
          {pipeline.steps.map((step, i) => (
            <span key={step.id} className="main-dashboard__pipeline-step-icon" title={step.instruction}>
              {getStepIcon(step.integration)}
              {i < pipeline.steps.length - 1 && (
                <span className="main-dashboard__pipeline-arrow">{'\u2192'}</span>
              )}
            </span>
          ))}
        </div>
      </div>

      <div className="main-dashboard__list-actions">
        {pipeline.active && (
          <button
            type="button"
            className="main-dashboard__list-action-btn"
            onClick={(e) => { e.stopPropagation(); onExecuteNow?.(pipeline.id) }}
            title="Ejecutar ahora"
            aria-label={`Ejecutar ${pipeline.name}`}
          >
            {'\u25B6'}
          </button>
        )}
        <button
          type="button"
          className="main-dashboard__list-action-btn"
          onClick={(e) => { e.stopPropagation(); onToggleActive?.(pipeline.id) }}
          aria-label={pipeline.active ? 'Pausar pipeline' : 'Activar pipeline'}
        >
          {pipeline.active ? '\u23F8' : '\u25B6'}
        </button>
        {onEdit && (
          <button
            type="button"
            className="main-dashboard__list-action-btn"
            onClick={(e) => { e.stopPropagation(); onEdit(pipeline.id) }}
            title="Editar"
            aria-label={`Editar ${pipeline.name}`}
          >
            {'\u270E'}
          </button>
        )}
        {onDelete && (
          <button
            type="button"
            className="main-dashboard__list-action-btn main-dashboard__list-action-btn--danger"
            onClick={(e) => { e.stopPropagation(); onDelete(pipeline.id) }}
            title="Eliminar"
            aria-label={`Eliminar ${pipeline.name}`}
          >
            {'\u2715'}
          </button>
        )}
        {onSaveAsTemplate && (
          <button
            type="button"
            className="main-dashboard__list-action-btn main-dashboard__list-action-btn--template"
            onClick={(e) => { e.stopPropagation(); onSaveAsTemplate(pipeline) }}
            disabled={savingTemplate}
            title="Guardar como plantilla"
            aria-label={`Guardar ${pipeline.name} como plantilla`}
          >
            {savingTemplate ? '...' : '\u{1F4CB}'}
          </button>
        )}
      </div>
    </motion.li>
  )
}
