import { useCallback, useEffect, useState } from 'react'
import { apiFetchAuthed } from '@/lib/api/client'
import type { GetAccessToken } from '@/lib/api/client'

type ProactiveSettings = {
  heartbeat_enabled: boolean
  wa_triggers_enabled: boolean
  calendar_triggers_enabled: boolean
  composite_enabled: boolean
}

export type ProactiveTriggersSettingsProps = {
  getAccessToken: GetAccessToken
}

export function ProactiveTriggersSettings({ getAccessToken }: ProactiveTriggersSettingsProps) {
  const [settings, setSettings] = useState<ProactiveSettings | null>(null)
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const load = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const data = await apiFetchAuthed<ProactiveSettings>(
        '/v1/automations/proactive/settings',
        { method: 'GET' },
        getAccessToken,
      )
      setSettings(data)
    } catch {
      setError('No se pudo cargar «avísame cuando…».')
    } finally {
      setLoading(false)
    }
  }, [getAccessToken])

  useEffect(() => {
    void load()
  }, [load])

  const patchSettings = useCallback(
    async (patch: Partial<ProactiveSettings>) => {
      if (!settings) return
      setSaving(true)
      setError(null)
      const optimistic = { ...settings, ...patch }
      setSettings(optimistic)
      try {
        const data = await apiFetchAuthed<ProactiveSettings>(
          '/v1/automations/proactive/settings',
          { method: 'PATCH', body: JSON.stringify(patch) },
          getAccessToken,
        )
        setSettings(data)
      } catch {
        setSettings(settings)
        setError('No se pudo guardar. Intenta de nuevo.')
      } finally {
        setSaving(false)
      }
    },
    [getAccessToken, settings],
  )

  if (loading) {
    return <p className="settings-section__desc">Cargando «avísame cuando…»…</p>
  }

  if (!settings) {
    return <p className="settings-section__desc">{error || 'Opciones no disponibles.'}</p>
  }

  return (
    <div className="settings-section__card">
      <p className="settings-section__desc">
        Aquí controlas cuándo DOT actúa solo con tus mandatos «avísame cuando…».
        Al terminar la configuración inicial activamos lo esencial; puedes apagar
        cualquier canal cuando quieras. DOT no te spamea: hay límites de frecuencia
        (p. ej. una evaluación IA cada 30 min en vigilancia).
      </p>

      <div className="settings-field settings-field--toggle">
        <div>
          <label className="settings-field__label">Automatizaciones en cadena</label>
          <span className="settings-field__help">
            Permite pipelines de varios pasos (herramientas encadenadas). Sin esto,
            las automatizaciones compuestas no se ejecutan aunque las tengas guardadas.
          </span>
        </div>
        <button
          type="button"
          className={`settings-toggle${settings.composite_enabled ? ' settings-toggle--active' : ''}`}
          onClick={() => void patchSettings({ composite_enabled: !settings.composite_enabled })}
          disabled={saving}
          aria-label={
            settings.composite_enabled
              ? 'Desactivar automatizaciones en cadena'
              : 'Activar automatizaciones en cadena'
          }
          role="switch"
          aria-checked={settings.composite_enabled}
        >
          <span className="settings-toggle__thumb" />
        </button>
      </div>

      <div className="settings-field settings-field--toggle">
        <div>
          <label className="settings-field__label">Vigilancia de mandatos</label>
          <span className="settings-field__help">
            Cada ~5 min revisa tus automatizaciones manuales y actúa si algo está pendiente
            (máx. una evaluación IA cada 30 min).
          </span>
        </div>
        <button
          type="button"
          className={`settings-toggle${settings.heartbeat_enabled ? ' settings-toggle--active' : ''}`}
          onClick={() => void patchSettings({ heartbeat_enabled: !settings.heartbeat_enabled })}
          disabled={saving}
          aria-label={
            settings.heartbeat_enabled
              ? 'Desactivar vigilancia de mandatos'
              : 'Activar vigilancia de mandatos'
          }
          role="switch"
          aria-checked={settings.heartbeat_enabled}
        >
          <span className="settings-toggle__thumb" />
        </button>
      </div>

      <div className="settings-field settings-field--toggle">
        <div>
          <label className="settings-field__label">Disparadores por WhatsApp</label>
          <span className="settings-field__help">
            Evalúa mandatos cuando llega un mensaje a tu WhatsApp vinculado.
          </span>
        </div>
        <button
          type="button"
          className={`settings-toggle${settings.wa_triggers_enabled ? ' settings-toggle--active' : ''}`}
          onClick={() => void patchSettings({ wa_triggers_enabled: !settings.wa_triggers_enabled })}
          disabled={saving}
          aria-label={
            settings.wa_triggers_enabled
              ? 'Desactivar disparadores por WhatsApp'
              : 'Activar disparadores por WhatsApp'
          }
          role="switch"
          aria-checked={settings.wa_triggers_enabled}
        >
          <span className="settings-toggle__thumb" />
        </button>
      </div>

      <div className="settings-field settings-field--toggle">
        <div>
          <label className="settings-field__label">Disparadores por calendario</label>
          <span className="settings-field__help">
            Cada ~10 min contrasta tus citas próximas con mandatos relacionados al calendario.
          </span>
        </div>
        <button
          type="button"
          className={`settings-toggle${settings.calendar_triggers_enabled ? ' settings-toggle--active' : ''}`}
          onClick={() =>
            void patchSettings({ calendar_triggers_enabled: !settings.calendar_triggers_enabled })
          }
          disabled={saving}
          aria-label={
            settings.calendar_triggers_enabled
              ? 'Desactivar disparadores por calendario'
              : 'Activar disparadores por calendario'
          }
          role="switch"
          aria-checked={settings.calendar_triggers_enabled}
        >
          <span className="settings-toggle__thumb" />
        </button>
      </div>

      {error ? <p className="settings-section__desc settings-section__desc--error">{error}</p> : null}
    </div>
  )
}
