import type { IntegrationId } from '@/features/integrations'
import { INTEGRATION_META } from '@/features/integrations'
import type { AutomationOutputType, PopularAutomationTemplate } from '@/features/dashboard/model/types'
import { useState, useEffect } from 'react'

export type AutomationDrawerProps = {
  draftIntegration: IntegrationId
  onDraftIntegration: (id: IntegrationId) => void
  draftName: string
  onDraftName: (value: string) => void
  draftInstruction: string
  onDraftInstruction: (value: string) => void
  draftOutputType: AutomationOutputType
  onDraftOutputType: (value: AutomationOutputType) => void
  draftSchedule: string
  onDraftSchedule: (value: string) => void
  draftDescription: string
  onDraftDescription: (value: string) => void
  onSave: () => void
  saveDisabled: boolean
  saveLabel?: string
  // C03: Plantillas populares
  templates: PopularAutomationTemplate[]
  templatesLoading: boolean
  onTemplateSelect: (template: PopularAutomationTemplate) => void
}

const SCHEDULE_PRESETS = [
  { value: 'manual', label: 'Manual (solo al ejecutar)' },
  { value: 'daily:09:00', label: 'Diaria 09:00' },
  { value: 'daily:18:00', label: 'Diaria 18:00' },
  { value: 'weekly:mon:09:00', label: 'Semanal (lunes 09:00)' },
  { value: 'weekly:mon:18:00', label: 'Semanal (lunes 18:00)' },
  { value: 'weekly:fri:09:00', label: 'Semanal (viernes 09:00)' },
  { value: 'custom_daily', label: 'Hora específica (diaria)' },
  { value: 'custom_weekly', label: 'Día y hora específicos (semanal)' },
]

const DAY_OPTIONS = [
  { value: 'mon', label: 'Lunes' },
  { value: 'tue', label: 'Martes' },
  { value: 'wed', label: 'Miércoles' },
  { value: 'thu', label: 'Jueves' },
  { value: 'fri', label: 'Viernes' },
  { value: 'sat', label: 'Sábado' },
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

export function AutomationDrawerFields({
  draftIntegration,
  onDraftIntegration,
  draftName,
  onDraftName,
  draftInstruction,
  onDraftInstruction,
  draftOutputType,
  onDraftOutputType,
  draftSchedule,
  onDraftSchedule,
  draftDescription,
  onDraftDescription,
  onSave,
  saveDisabled,
  saveLabel = 'Guardar',
  templates,
  templatesLoading,
  onTemplateSelect,
}: AutomationDrawerProps) {
  const parsed = parseCustomSchedule(draftSchedule)
  const [schedulePreset, setSchedulePreset] = useState(
    parsed.mode === 'preset' ? draftSchedule :
    parsed.mode === 'custom_daily' ? 'custom_daily' : 'custom_weekly'
  )
  const [customHour, setCustomHour] = useState(parsed.timeHour)
  const [customMinute, setCustomMinute] = useState(parsed.timeMinute)
  const [customDay, setCustomDay] = useState(parsed.day)

  // Sincronizar cuando cambia draftSchedule externamente
  useEffect(() => {
    const p = parseCustomSchedule(draftSchedule)
    if (p.mode === 'preset') {
      setSchedulePreset(draftSchedule)
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
  }, [draftSchedule])

  const handleScheduleChange = (value: string) => {
    if (value === 'custom_daily') {
      setSchedulePreset('custom_daily')
      onDraftSchedule(`daily:${customHour}:${customMinute}`)
    } else if (value === 'custom_weekly') {
      setSchedulePreset('custom_weekly')
      onDraftSchedule(`weekly:${customDay}:${customHour}:${customMinute}`)
    } else {
      setSchedulePreset(value)
      onDraftSchedule(value)
    }
  }

  const handleCustomHourChange = (hour: string) => {
    setCustomHour(hour)
    if (schedulePreset === 'custom_daily') {
      onDraftSchedule(`daily:${hour}:${customMinute}`)
    } else {
      onDraftSchedule(`weekly:${customDay}:${hour}:${customMinute}`)
    }
  }

  const handleCustomMinuteChange = (min: string) => {
    setCustomMinute(min)
    if (schedulePreset === 'custom_daily') {
      onDraftSchedule(`daily:${customHour}:${min}`)
    } else {
      onDraftSchedule(`weekly:${customDay}:${customHour}:${min}`)
    }
  }

  const handleCustomDayChange = (day: string) => {
    setCustomDay(day)
    onDraftSchedule(`weekly:${day}:${customHour}:${customMinute}`)
  }
  return (
    <>
      <div className="main-dashboard__drawer-grid" role="group" aria-label="Tipo de integración">
        {INTEGRATION_META.map((meta) => {
          const active = draftIntegration === meta.id
          return (
            <button
              key={meta.id}
              type="button"
              className={`main-dashboard__drawer-tile ${active ? 'main-dashboard__drawer-tile--active' : ''}`}
              onClick={() => onDraftIntegration(meta.id)}
            >
              <span className="main-dashboard__drawer-icon" aria-hidden>
                {meta.logoSrc ? (
                  <img src={meta.logoSrc} alt="" draggable={false} />
                ) : (
                  <span className="main-dashboard__drawer-placeholder">3</span>
                )}
              </span>
              {meta.label}
            </button>
          )
        })}
      </div>

      {/* C03: Plantillas populares */}
      {templates.length > 0 && (
        <div>
          <label className="main-dashboard__field-label">Plantillas</label>
          <div className="main-dashboard__drawer-grid" role="group" aria-label="Plantillas de automatización" style={{ marginBottom: '1rem' }}>
            {templatesLoading ? (
              <span style={{ fontSize: '0.8125rem', color: 'var(--text-secondary, #888)', padding: '0.5rem 0' }}>
                Cargando plantillas...
              </span>
            ) : (
              templates.map((tpl) => (
                <button
                  key={tpl.id}
                  type="button"
                  className="main-dashboard__drawer-tile"
                  style={{
                    flexDirection: 'column',
                    alignItems: 'flex-start',
                    padding: '0.625rem 0.75rem',
                    height: 'auto',
                    textAlign: 'left',
                  }}
                  onClick={() => onTemplateSelect(tpl)}
                  title={tpl.description}
                >
                  <span style={{ fontWeight: 600, fontSize: '0.8125rem', marginBottom: '0.25rem' }}>
                    {tpl.name}
                  </span>
                  <span style={{ fontSize: '0.6875rem', color: 'var(--text-secondary, #888)', lineHeight: 1.3 }}>
                    {tpl.description.length > 80
                      ? tpl.description.slice(0, 80) + '...'
                      : tpl.description}
                  </span>
                </button>
              ))
            )}
          </div>
        </div>
      )}

      <div>
        <label className="main-dashboard__field-label" htmlFor="automation-name">
          Nombre de la automatización
        </label>
        <input
          id="automation-name"
          type="text"
          className="main-dashboard__input"
          value={draftName}
          onChange={(e) => onDraftName(e.target.value)}
          placeholder="Ej. Resumen semanal del calendario"
          autoComplete="off"
        />
      </div>

      <div className="main-dashboard__drawer-row">
        <div>
          <label className="main-dashboard__field-label" htmlFor="automation-output">
            Salida
          </label>
          <select
            id="automation-output"
            className="main-dashboard__input"
            value={draftOutputType}
            onChange={(e) => onDraftOutputType(e.target.value as AutomationOutputType)}
          >
            <option value="notify">Notificación en app</option>
            <option value="email">Correo (cuando esté disponible)</option>
            <option value="file">Archivo en DOT Trabajos</option>
          </select>
        </div>
        <div>
          <label className="main-dashboard__field-label" htmlFor="automation-schedule">
            Programación
          </label>
          <select
            id="automation-schedule"
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
                <label className="main-dashboard__field-label" htmlFor="custom-time">
                  Hora (HH:MM)
                </label>
                <input
                  id="custom-time"
                  type="time"
                  className="main-dashboard__input"
                  value={`${customHour}:${customMinute}`}
                  onChange={(e) => {
                    const [h, m] = (e.target.value || '09:00').split(':')
                    handleCustomHourChange(h)
                    handleCustomMinuteChange(m)
                  }}
                />
              </div>
            </div>
          )}
          {schedulePreset === 'custom_weekly' && (
            <div className="main-dashboard__drawer-row" style={{ marginTop: '0.5rem' }}>
              <div>
                <label className="main-dashboard__field-label" htmlFor="custom-day">
                  Día
                </label>
                <select
                  id="custom-day"
                  className="main-dashboard__input"
                  value={customDay}
                  onChange={(e) => handleCustomDayChange(e.target.value)}
                >
                  {DAY_OPTIONS.map((opt) => (
                    <option key={opt.value} value={opt.value}>{opt.label}</option>
                  ))}
                </select>
              </div>
              <div>
                <label className="main-dashboard__field-label" htmlFor="custom-time-weekly">
                  Hora (HH:MM)
                </label>
                <input
                  id="custom-time-weekly"
                  type="time"
                  className="main-dashboard__input"
                  value={`${customHour}:${customMinute}`}
                  onChange={(e) => {
                    const [h, m] = (e.target.value || '09:00').split(':')
                    handleCustomHourChange(h)
                    handleCustomMinuteChange(m)
                  }}
                />
              </div>
            </div>
          )}
      </div>
    </div>

      {/* T-ML-014: Campo «De qué trata esta automatización» */}
      <div>
        <label className="main-dashboard__field-label" htmlFor="automation-description">
          De qué trata esta automatización
        </label>
        <input
          id="automation-description"
          type="text"
          className="main-dashboard__input"
          value={draftDescription}
          onChange={(e) => onDraftDescription(e.target.value)}
          placeholder="Ej. Resumen semanal del calendario para planificar la semana."
          autoComplete="off"
        />
      </div>

      <div>
        <label className="main-dashboard__field-label" htmlFor="automation-instruction">
          Instrucción
        </label>
        <textarea
          id="automation-instruction"
          className="main-dashboard__textarea"
          value={draftInstruction}
          onChange={(e) => onDraftInstruction(e.target.value)}
          placeholder="Ej. Cada lunes resume mis eventos de Google Calendar y envíame un recordatorio."
        />
      </div>

      <div className="main-dashboard__drawer-actions">
        <button type="button" className="main-dashboard__drawer-save" disabled={saveDisabled} onClick={onSave}>
          {saveLabel}
        </button>
      </div>
    </>
  )
}
