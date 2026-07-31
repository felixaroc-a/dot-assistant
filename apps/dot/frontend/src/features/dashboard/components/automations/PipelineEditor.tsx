import { useState, useCallback, useEffect } from 'react'
import type { PipelineDef, PipelineStep } from '@/features/dashboard/model/types'
import {
  PipelineVisualEditor,
  visualBlocksToNaturalLanguage,
  visualBlocksToSteps,
  type VisualBlock,
} from './PipelineVisualEditor'

type PipelineEditorProps = {
  pipeline?: PipelineDef | null
  onSave: (
    name: string,
    description: string,
    naturalLanguage: string,
    schedule: string,
    steps?: PipelineStep[],
  ) => void
  onCancel: () => void
  saving: boolean
}

const INTEGRATION_OPTIONS = [
  { value: 'gmail', label: 'Gmail' },
  { value: 'google-calendar', label: 'Google Calendar' },
  { value: 'chat', label: 'IA / Chat' },
  { value: 'whatsapp', label: 'WhatsApp' },
  { value: 'web_search', label: 'Busqueda Web' },
  { value: 'file', label: 'Archivos Locales' },
  { value: 'condition', label: 'Condicion' },
]

const SCHEDULE_PRESETS = [
  { value: 'manual', label: 'Manual (solo al ejecutar)' },
  { value: 'daily:09:00', label: 'Diaria 09:00' },
  { value: 'daily:18:00', label: 'Diaria 18:00' },
  { value: 'weekly:mon:09:00', label: 'Semanal (lunes 09:00)' },
  { value: 'weekly:mon:18:00', label: 'Semanal (lunes 18:00)' },
  { value: 'weekly:fri:09:00', label: 'Semanal (viernes 09:00)' },
  { value: 'custom_daily', label: 'Hora especifica (diaria)' },
  { value: 'custom_weekly', label: 'Dia y hora especificos (semanal)' },
]

const DAY_OPTIONS = [
  { value: 'mon', label: 'Lunes' },
  { value: 'tue', label: 'Martes' },
  { value: 'wed', label: 'Miercoles' },
  { value: 'thu', label: 'Jueves' },
  { value: 'fri', label: 'Viernes' },
  { value: 'sat', label: 'Sabado' },
  { value: 'sun', label: 'Domingo' },
]

function parseCustomSchedule(schedule: string): {
  mode: 'preset' | 'custom_daily' | 'custom_weekly'
  timeHour: string
  timeMinute: string
  day: string
} {
  if (schedule.startsWith('daily:') && schedule.split(':').length === 3) {
    const parts = schedule.split(':')
    const isPreset = ['09:00', '18:00'].includes(`${parts[1]}:${parts[2]}`)
    if (isPreset) {
      return { mode: 'preset', timeHour: parts[1], timeMinute: parts[2], day: 'mon' }
    }
    return { mode: 'custom_daily', timeHour: parts[1], timeMinute: parts[2], day: 'mon' }
  }
  if (schedule.startsWith('weekly:') && schedule.split(':').length === 4) {
    const parts = schedule.split(':')
    const isPreset = (
      (parts[1] === 'mon' && ['09:00', '18:00'].includes(`${parts[2]}:${parts[3]}`)) ||
      (parts[1] === 'fri' && `${parts[2]}:${parts[3]}` === '09:00')
    )
    if (isPreset) {
      return { mode: 'preset', timeHour: parts[2], timeMinute: parts[3], day: parts[1] }
    }
    return { mode: 'custom_weekly', timeHour: parts[2], timeMinute: parts[3], day: parts[1] }
  }
  return { mode: 'preset', timeHour: '09', timeMinute: '00', day: 'mon' }
}

export function PipelineEditor({ pipeline, onSave, onCancel, saving }: PipelineEditorProps) {
  const isEditing = !!pipeline
  const [name, setName] = useState(pipeline?.name || '')
  const [description, setDescription] = useState(pipeline?.description || '')
  const [naturalLanguage, setNaturalLanguage] = useState(pipeline?.source_nl || '')
  const [schedule, setSchedule] = useState(pipeline?.schedule || 'manual')
  const [visualBlocks, setVisualBlocks] = useState<VisualBlock[]>([])
  const [editorMode, setEditorMode] = useState<'text' | 'visual'>('text')

  const parsed = parseCustomSchedule(schedule)
  const [schedulePreset, setSchedulePreset] = useState(
    parsed.mode === 'preset' ? schedule :
    parsed.mode === 'custom_daily' ? 'custom_daily' : 'custom_weekly'
  )
  const [customHour, setCustomHour] = useState(parsed.timeHour)
  const [customMinute, setCustomMinute] = useState(parsed.timeMinute)
  const [customDay, setCustomDay] = useState(parsed.day)

  useEffect(() => {
    const p = parseCustomSchedule(schedule)
    if (p.mode === 'preset') {
      setSchedulePreset(schedule)
    } else if (p.mode === 'custom_daily') {
      setSchedulePreset('custom_daily')
      setCustomHour(p.timeHour)
      setCustomMinute(p.timeMinute)
    } else {
      setSchedulePreset('custom_weekly')
      setCustomHour(p.timeHour)
      setCustomMinute(p.timeMinute)
      setCustomDay(p.day)
    }
  }, [schedule])

  const handleScheduleChange = (value: string) => {
    if (value === 'custom_daily') {
      setSchedulePreset('custom_daily')
      setSchedule(`daily:${customHour}:${customMinute}`)
    } else if (value === 'custom_weekly') {
      setSchedulePreset('custom_weekly')
      setSchedule(`weekly:${customDay}:${customHour}:${customMinute}`)
    } else {
      setSchedulePreset(value)
      setSchedule(value)
    }
  }

  const saveDisabled =
    saving ||
    (editorMode === 'visual' ? visualBlocks.length === 0 : !naturalLanguage.trim())

  const handleSave = useCallback(() => {
    const useVisual = editorMode === 'visual' && visualBlocks.length > 0
    const stepsFromVisual = useVisual ? visualBlocksToSteps(visualBlocks) : undefined
    const nl =
      naturalLanguage.trim() ||
      (useVisual ? visualBlocksToNaturalLanguage(visualBlocks) : '')

    // Si hay Trigger: Hora/Día y la programación sigue en manual, usar la del bloque
    let effectiveSchedule = schedule
    if (useVisual && (schedule === 'manual' || !schedule)) {
      const timeTrigger = visualBlocks.find((b) => b.type === 'trigger_time')
      if (timeTrigger) {
        const day = timeTrigger.config.day || 'mon'
        const time = timeTrigger.config.time || '09:00'
        const [hh, mm] = time.split(':')
        effectiveSchedule = `weekly:${day}:${hh || '09'}:${mm || '00'}`
      }
    }

    onSave(name, description, nl, effectiveSchedule, stepsFromVisual)
  }, [name, description, naturalLanguage, schedule, visualBlocks, editorMode, onSave])

  return (
    <div className="main-dashboard__pipeline-editor">
      <h3 className="main-dashboard__pipeline-editor-title">
        {isEditing ? 'Editar Pipeline' : 'Nuevo Pipeline Multi-paso'}
      </h3>

      <PipelineVisualEditor
        naturalLanguage={naturalLanguage}
        onNaturalLanguageChange={setNaturalLanguage}
        onVisualBlocksChange={setVisualBlocks}
        onModeChange={setEditorMode}
      />

      <div className="main-dashboard__field-group">
        <label className="main-dashboard__field-label" htmlFor="pipeline-name">
          Nombre del pipeline
        </label>
        <input
          id="pipeline-name"
          type="text"
          className="main-dashboard__input"
          value={name}
          onChange={(e) => setName(e.target.value)}
          placeholder="Ej. Revisar PDFs y notificar"
          autoComplete="off"
        />
      </div>

      <div className="main-dashboard__field-group">
        <label className="main-dashboard__field-label" htmlFor="pipeline-desc">
          Descripcion breve
        </label>
        <input
          id="pipeline-desc"
          type="text"
          className="main-dashboard__input"
          value={description}
          onChange={(e) => setDescription(e.target.value)}
          placeholder="Que hace este pipeline"
          autoComplete="off"
        />
      </div>

      <div className="main-dashboard__field-group">
        <label className="main-dashboard__field-label" htmlFor="pipeline-schedule">
          Programacion
        </label>
        <select
          id="pipeline-schedule"
          className="main-dashboard__input"
          value={schedulePreset}
          onChange={(e) => handleScheduleChange(e.target.value)}
        >
          {SCHEDULE_PRESETS.map((opt) => (
            <option key={opt.value} value={opt.value}>{opt.label}</option>
          ))}
        </select>
        {schedulePreset === 'custom_daily' && (
          <div className="main-dashboard__drawer-row" style={{ marginTop: '0.5rem' }}>
            <div>
              <label className="main-dashboard__field-label" htmlFor="pipeline-custom-time">
                Hora (HH:MM)
              </label>
              <input
                id="pipeline-custom-time"
                type="time"
                className="main-dashboard__input"
                value={`${customHour}:${customMinute}`}
                onChange={(e) => {
                  const [h, m] = (e.target.value || '09:00').split(':')
                  setCustomHour(h)
                  setCustomMinute(m)
                  setSchedule(`daily:${h}:${m}`)
                }}
              />
            </div>
          </div>
        )}
        {schedulePreset === 'custom_weekly' && (
          <div className="main-dashboard__drawer-row" style={{ marginTop: '0.5rem' }}>
            <div>
              <label className="main-dashboard__field-label" htmlFor="pipeline-custom-day">
                Dia
              </label>
              <select
                id="pipeline-custom-day"
                className="main-dashboard__input"
                value={customDay}
                onChange={(e) => {
                  setCustomDay(e.target.value)
                  setSchedule(`weekly:${e.target.value}:${customHour}:${customMinute}`)
                }}
              >
                {DAY_OPTIONS.map((opt) => (
                  <option key={opt.value} value={opt.value}>{opt.label}</option>
                ))}
              </select>
            </div>
            <div>
              <label className="main-dashboard__field-label" htmlFor="pipeline-custom-time-weekly">
                Hora (HH:MM)
              </label>
              <input
                id="pipeline-custom-time-weekly"
                type="time"
                className="main-dashboard__input"
                value={`${customHour}:${customMinute}`}
                onChange={(e) => {
                  const [h, m] = (e.target.value || '09:00').split(':')
                  setCustomHour(h)
                  setCustomMinute(m)
                  setSchedule(`weekly:${customDay}:${h}:${m}`)
                }}
              />
            </div>
          </div>
        )}
      </div>

      {pipeline && pipeline.steps.length > 0 && (
        <div className="main-dashboard__pipeline-steps-preview">
          <h4 className="main-dashboard__pipeline-steps-title">
            Pasos detectados ({pipeline.steps.length})
          </h4>
          <div className="main-dashboard__pipeline-steps-list">
            {pipeline.steps.map((step, i) => (
              <div key={step.id} className="main-dashboard__pipeline-step-row">
                <span className="main-dashboard__pipeline-step-num">{i + 1}</span>
                <span className="main-dashboard__pipeline-step-type" data-type={step.type}>
                  {step.type}
                </span>
                <span className="main-dashboard__pipeline-step-integration">
                  {INTEGRATION_OPTIONS.find((o) => o.value === step.integration)?.label || step.integration}
                </span>
                <span className="main-dashboard__pipeline-step-instruction">{step.instruction}</span>
              </div>
            ))}
          </div>
        </div>
      )}

      <div className="main-dashboard__drawer-actions">
        <button type="button" className="main-dashboard__drawer-cancel" onClick={onCancel}>
          Cancelar
        </button>
        <button
          type="button"
          className="main-dashboard__drawer-save"
          disabled={saveDisabled}
          onClick={handleSave}
        >
          {saving ? 'Creando...' : isEditing ? 'Actualizar' : 'Crear Pipeline'}
        </button>
      </div>
    </div>
  )
}
