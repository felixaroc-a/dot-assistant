import { motion, useReducedMotion } from 'framer-motion'
import type { PipelineTemplate } from '@/features/dashboard/model/types'

type PipelineTemplateCardProps = {
  template: PipelineTemplate
  onClone: (id: string) => void
  cloning: boolean
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

export function PipelineTemplateCard({
  template,
  onClone,
  cloning,
}: PipelineTemplateCardProps) {
  const reduceMotion = useReducedMotion()

  return (
    <motion.li
      className="main-dashboard__list-item main-dashboard__list-item--template"
      initial={reduceMotion ? false : { opacity: 0, x: -8 }}
      animate={{ opacity: 1, x: 0 }}
      transition={{ duration: 0.22 }}
      layout
    >
      <div className="main-dashboard__template-info">
        <div className="main-dashboard__template-header">
          <span className="main-dashboard__template-icon" aria-hidden>{'\u{1F4CB}'}</span>
          <div className="main-dashboard__list-text-group">
            <p className="main-dashboard__list-text">{template.name}</p>
            <span className="main-dashboard__auto-badge main-dashboard__auto-badge--category">
              {template.category}
            </span>
          </div>
        </div>

        <p className="main-dashboard__template-desc">{template.description}</p>

        <div className="main-dashboard__template-meta">
          <span className="main-dashboard__pipeline-schedule">{getScheduleLabel(template.schedule)}</span>
          <span className="main-dashboard__pipeline-steps">
            {template.usage_count > 0 ? `${template.usage_count} usos` : 'Nuevo'}
          </span>
        </div>
      </div>

      <div className="main-dashboard__list-actions">
        <button
          type="button"
          className="main-dashboard__list-action-btn main-dashboard__list-action-btn--clone"
          onClick={(e) => { e.stopPropagation(); onClone(template.id) }}
          disabled={cloning}
          title="Usar plantilla"
          aria-label={`Usar plantilla ${template.name}`}
        >
          {cloning ? '...' : 'Usar plantilla'}
        </button>
      </div>
    </motion.li>
  )
}
