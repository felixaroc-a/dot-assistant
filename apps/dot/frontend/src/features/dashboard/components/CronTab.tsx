import { useCallback, useEffect, useState } from 'react'
import { apiFetchAuthed } from '@/lib/api/client'
import type { GetAccessToken } from '@/lib/api/client'

// ─── Tipos ───────────────────────────────────────────────

type CronJob = {
  job_id: string
  name: string
  schedule_type: string
  schedule_value: string
  tool_name: string
  tool_args: Record<string, unknown>
  status: 'active' | 'paused' | 'error'
  last_run: string | null
  last_status: string | null
  last_error: string | null
  run_count: number
  next_run: string | null
  created_at: string | null
  updated_at: string | null
}

type CronTemplate = {
  name: string
  description: string
  schedule_type: string
  schedule_value: string
  tool_name: string
  tool_args: Record<string, unknown>
}

type ScheduleType = 'daily_at' | 'weekly_on' | 'every_n_minutes' | 'every_n_hours' | 'cron'

const SCHEDULE_LABELS: Record<ScheduleType, string> = {
  daily_at: 'Todos los días a una hora',
  weekly_on: 'Día de semana específico',
  every_n_minutes: 'Cada N minutos',
  every_n_hours: 'Cada N horas',
  cron: 'Expresión cron',
}

const SCHEDULE_PLACEHOLDERS: Record<ScheduleType, string> = {
  daily_at: 'HH:MM (ej. 08:00)',
  weekly_on: 'dia@HH:MM (ej. mon@18:00)',
  every_n_minutes: 'N minutos (ej. 30)',
  every_n_hours: 'N horas (ej. 6)',
  cron: 'min hora dia mes dia_sem (ej. 0 8 * * *)',
}

// ─── Props ────────────────────────────────────────────────

export type CronTabProps = {
  getAccessToken: GetAccessToken
}

// ─── Componente ───────────────────────────────────────────

export function CronTab({ getAccessToken }: CronTabProps) {
  const [jobs, setJobs] = useState<CronJob[]>([])
  const [templates, setTemplates] = useState<CronTemplate[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  // Form state
  const [showForm, setShowForm] = useState(false)
  const [formName, setFormName] = useState('')
  const [formScheduleType, setFormScheduleType] = useState<ScheduleType>('daily_at')
  const [formScheduleValue, setFormScheduleValue] = useState('')
  const [formToolName, setFormToolName] = useState('')
  const [formSaving, setFormSaving] = useState(false)
  const [formError, setFormError] = useState<string | null>(null)

  // ─── Fetch ──────────────────────────────────────────────

  const fetchJobs = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const data = await apiFetchAuthed<{ jobs: CronJob[]; total: number }>(
        '/v1/cron/jobs',
        { method: 'GET' },
        getAccessToken,
      )
      setJobs(data.jobs || [])
    } catch (e) {
      setError('No se pudieron cargar las tareas programadas.')
      console.warn('[CronTab] Error fetching jobs:', e)
    } finally {
      setLoading(false)
    }
  }, [getAccessToken])

  const fetchTemplates = useCallback(async () => {
    try {
      const data = await apiFetchAuthed<{ templates: CronTemplate[] }>(
        '/v1/cron/templates',
        { method: 'GET' },
        getAccessToken,
      )
      setTemplates(data.templates || [])
    } catch {
      // templates are optional
    }
  }, [getAccessToken])

  useEffect(() => {
    void fetchJobs()
    void fetchTemplates()
  }, [fetchJobs, fetchTemplates])

  // ─── Acciones ───────────────────────────────────────────

  const handleCreate = useCallback(async () => {
    if (!formName.trim() || !formScheduleValue.trim() || !formToolName.trim()) {
      setFormError('Completa todos los campos requeridos.')
      return
    }
    setFormSaving(true)
    setFormError(null)
    try {
      await apiFetchAuthed(
        '/v1/cron/jobs',
        {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            name: formName.trim(),
            schedule_type: formScheduleType,
            schedule_value: formScheduleValue.trim(),
            tool_name: formToolName.trim(),
            tool_args: {},
          }),
        },
        getAccessToken,
      )
      setShowForm(false)
      setFormName('')
      setFormScheduleType('daily_at')
      setFormScheduleValue('')
      setFormToolName('')
      await fetchJobs()
    } catch (e) {
      setFormError('Error al crear la tarea. Revisa los valores del schedule.')
      console.warn('[CronTab] Error creating job:', e)
    } finally {
      setFormSaving(false)
    }
  }, [formName, formScheduleType, formScheduleValue, formToolName, getAccessToken, fetchJobs])

  const handleDelete = useCallback(async (jobId: string) => {
    try {
      await apiFetchAuthed(
        `/v1/cron/jobs/${jobId}`,
        { method: 'DELETE' },
        getAccessToken,
      )
      await fetchJobs()
    } catch (e) {
      console.warn('[CronTab] Error deleting job:', e)
    }
  }, [getAccessToken, fetchJobs])

  const handlePause = useCallback(async (jobId: string) => {
    try {
      await apiFetchAuthed(
        `/v1/cron/jobs/${jobId}/pause`,
        { method: 'POST' },
        getAccessToken,
      )
      await fetchJobs()
    } catch (e) {
      console.warn('[CronTab] Error pausing job:', e)
    }
  }, [getAccessToken, fetchJobs])

  const handleResume = useCallback(async (jobId: string) => {
    try {
      await apiFetchAuthed(
        `/v1/cron/jobs/${jobId}/resume`,
        { method: 'POST' },
        getAccessToken,
      )
      await fetchJobs()
    } catch (e) {
      console.warn('[CronTab] Error resuming job:', e)
    }
  }, [getAccessToken, fetchJobs])

  const handleApplyTemplate = useCallback((tpl: CronTemplate) => {
    setFormName(tpl.name)
    setFormScheduleType(tpl.schedule_type as ScheduleType)
    setFormScheduleValue(tpl.schedule_value)
    setFormToolName(tpl.tool_name)
    setShowForm(true)
  }, [])

  // ─── Helpers ────────────────────────────────────────────

  function formatSchedule(job: CronJob): string {
    switch (job.schedule_type) {
      case 'daily_at':
        return `Todos los días a las ${job.schedule_value}`
      case 'weekly_on': {
        const [day, time] = job.schedule_value.split('@')
        const days: Record<string, string> = {
          mon: 'Lunes', tue: 'Martes', wed: 'Miércoles',
          thu: 'Jueves', fri: 'Viernes', sat: 'Sábado', sun: 'Domingo',
          monday: 'Lunes', tuesday: 'Martes', wednesday: 'Miércoles',
          thursday: 'Jueves', friday: 'Viernes', saturday: 'Sábado', sunday: 'Domingo',
        }
        return `${days[day?.toLowerCase()] || day} a las ${time}`
      }
      case 'every_n_minutes':
        return `Cada ${job.schedule_value} minutos`
      case 'every_n_hours':
        return `Cada ${job.schedule_value} horas`
      case 'interval':
        return `Cada ${job.schedule_value}`
      case 'cron':
        return `Cron: ${job.schedule_value}`
      default:
        return job.schedule_value
    }
  }

  function formatNextRun(nextRun: string | null): string {
    if (!nextRun) return '—'
    try {
      const d = new Date(nextRun)
      return d.toLocaleString('es-CO', {
        day: '2-digit',
        month: 'short',
        hour: '2-digit',
        minute: '2-digit',
      })
    } catch {
      return nextRun
    }
  }

  function statusBadge(status: string) {
    const map: Record<string, { label: string; cls: string }> = {
      active: { label: 'Activo', cls: 'cron-status--active' },
      paused: { label: 'Pausado', cls: 'cron-status--paused' },
      error: { label: 'Error', cls: 'cron-status--error' },
    }
    const s = map[status] || { label: status, cls: '' }
    return <span className={`cron-status ${s.cls}`}>{s.label}</span>
  }

  // ─── JSX ────────────────────────────────────────────────

  return (
    <div className="cron-tab">
      <div className="cron-tab__header">
        <h3 className="settings-section__title">Tareas programadas</h3>
        <button
          type="button"
          className="cron-tab__add-btn"
          onClick={() => { setShowForm(!showForm); setFormError(null) }}
        >
          {showForm ? 'Cancelar' : '+ Nueva tarea'}
        </button>
      </div>

      <p className="settings-section__desc" style={{ marginBottom: '0.5rem' }}>
        Programa tareas recurrentes que se ejecutarán automáticamente.
        Puedes pausar o eliminar tareas en cualquier momento.
      </p>

      {/* ─── Formulario ──────────────────────────── */}
      {showForm && (
        <div className="settings-section__card cron-form">
          <div className="cron-form__field">
            <label className="cron-form__label">Nombre</label>
            <input
              className="cron-form__input"
              type="text"
              value={formName}
              onChange={(e) => setFormName(e.target.value)}
              placeholder="Ej. Buenos días"
              maxLength={120}
            />
          </div>

          <div className="cron-form__field">
            <label className="cron-form__label">Tipo de schedule</label>
            <select
              className="cron-form__select"
              value={formScheduleType}
              onChange={(e) => setFormScheduleType(e.target.value as ScheduleType)}
            >
              {(Object.keys(SCHEDULE_LABELS) as ScheduleType[]).map((st) => (
                <option key={st} value={st}>{SCHEDULE_LABELS[st]}</option>
              ))}
            </select>
          </div>

          <div className="cron-form__field">
            <label className="cron-form__label">Valor</label>
            <input
              className="cron-form__input"
              type="text"
              value={formScheduleValue}
              onChange={(e) => setFormScheduleValue(e.target.value)}
              placeholder={SCHEDULE_PLACEHOLDERS[formScheduleType]}
            />
          </div>

          <div className="cron-form__field">
            <label className="cron-form__label">Tool</label>
            <input
              className="cron-form__input"
              type="text"
              value={formToolName}
              onChange={(e) => setFormToolName(e.target.value)}
              placeholder="Ej. send_whatsapp_daily_briefing"
            />
          </div>

          {formError && (
            <p className="cron-form__error">{formError}</p>
          )}

          <button
            type="button"
            className="cron-form__submit"
            onClick={handleCreate}
            disabled={formSaving}
          >
            {formSaving ? 'Guardando…' : 'Crear tarea'}
          </button>

          {/* Plantillas */}
          {templates.length > 0 && (
            <div className="cron-form__templates">
              <p className="cron-form__templates-label">Plantillas rápidas:</p>
              <div className="cron-form__templates-grid">
                {templates.map((tpl) => (
                  <button
                    key={tpl.name}
                    type="button"
                    className="cron-form__template-btn"
                    onClick={() => handleApplyTemplate(tpl)}
                    title={tpl.description}
                  >
                    {tpl.name}
                  </button>
                ))}
              </div>
            </div>
          )}
        </div>
      )}

      {/* ─── Lista de jobs ────────────────────────── */}
      {loading ? (
        <p className="settings-section__desc">Cargando tareas…</p>
      ) : error ? (
        <p className="settings-section__desc" style={{ color: 'var(--dash-error)' }}>{error}</p>
      ) : jobs.length === 0 ? (
        <div className="cron-empty">
          <p className="settings-section__desc">
            No tienes tareas programadas. Crea una nueva o usa una plantilla rápida.
          </p>
        </div>
      ) : (
        <div className="cron-job-list">
          {jobs.map((job) => (
            <div key={job.job_id} className="cron-job-card">
              <div className="cron-job-card__top">
                <div className="cron-job-card__info">
                  <span className="cron-job-card__name">{job.name}</span>
                  <span className="cron-job-card__schedule">{formatSchedule(job)}</span>
                  <span className="cron-job-card__tool">Tool: {job.tool_name}</span>
                </div>
                {statusBadge(job.status)}
              </div>

              <div className="cron-job-card__meta">
                <span>Próxima: {formatNextRun(job.next_run)}</span>
                <span>Ejecuciones: {job.run_count}</span>
                {job.last_run && (
                  <span>Última: {formatNextRun(job.last_run)}</span>
                )}
                {job.last_status === 'error' && job.last_error && (
                  <span className="cron-job-card__error-msg" title={job.last_error}>
                    ⚠️ Error en última ejecución
                  </span>
                )}
              </div>

              <div className="cron-job-card__actions">
                {job.status === 'active' ? (
                  <button
                    type="button"
                    className="cron-action-btn cron-action-btn--pause"
                    onClick={() => handlePause(job.job_id)}
                  >
                    Pausar
                  </button>
                ) : (
                  <button
                    type="button"
                    className="cron-action-btn cron-action-btn--resume"
                    onClick={() => handleResume(job.job_id)}
                  >
                    Reanudar
                  </button>
                )}
                <button
                  type="button"
                  className="cron-action-btn cron-action-btn--delete"
                  onClick={() => {
                    if (window.confirm(`¿Eliminar la tarea "${job.name}"?`)) {
                      void handleDelete(job.job_id)
                    }
                  }}
                >
                  Eliminar
                </button>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
