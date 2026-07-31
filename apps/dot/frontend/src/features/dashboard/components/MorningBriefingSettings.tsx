import { useCallback, useEffect, useState } from 'react'
import { apiFetchAuthed } from '@/lib/api/client'
import type { GetAccessToken } from '@/lib/api/client'

type BriefingSettings = {
  enabled: boolean
  hour: string
  timezone: string
  notify_app: boolean
  notify_whatsapp: boolean
}

export type MorningBriefingSettingsProps = {
  getAccessToken: GetAccessToken
}

export function MorningBriefingSettings({ getAccessToken }: MorningBriefingSettingsProps) {
  const [settings, setSettings] = useState<BriefingSettings | null>(null)
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const load = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const data = await apiFetchAuthed<BriefingSettings>(
        '/v1/briefing/settings',
        { method: 'GET' },
        getAccessToken,
      )
      setSettings(data)
    } catch {
      setError('No se pudo cargar el briefing matutino.')
    } finally {
      setLoading(false)
    }
  }, [getAccessToken])

  useEffect(() => {
    void load()
  }, [load])

  const patchSettings = useCallback(
    async (patch: Partial<BriefingSettings>) => {
      if (!settings) return
      setSaving(true)
      setError(null)
      const optimistic = { ...settings, ...patch }
      setSettings(optimistic)
      try {
        const data = await apiFetchAuthed<BriefingSettings>(
          '/v1/briefing/settings',
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
    return <p className="settings-section__desc">Cargando briefing matutino…</p>
  }

  if (!settings) {
    return <p className="settings-section__desc">{error || 'Briefing no disponible.'}</p>
  }

  return (
    <div className="settings-section__card">
      <div className="settings-field settings-field--toggle">
        <div>
          <label className="settings-field__label">Briefing matutino</label>
          <span className="settings-field__help">
            Cada mañana DOT te saluda con «Tu día en 30s»: correos y citas (sin gastar cuota de IA).
          </span>
        </div>
        <button
          type="button"
          className={`settings-toggle${settings.enabled ? ' settings-toggle--active' : ''}`}
          onClick={() => void patchSettings({ enabled: !settings.enabled })}
          disabled={saving}
          aria-label={settings.enabled ? 'Desactivar briefing matutino' : 'Activar briefing matutino'}
          role="switch"
          aria-checked={settings.enabled}
        >
          <span className="settings-toggle__thumb" />
        </button>
      </div>

      {settings.enabled ? (
        <>
          <div className="settings-field">
            <label className="settings-field__label" htmlFor="briefing-hour">
              Hora (tu zona)
            </label>
            <input
              id="briefing-hour"
              className="settings-field__input"
              type="time"
              value={settings.hour}
              disabled={saving}
              onChange={(e) => {
                const value = e.target.value
                if (value) void patchSettings({ hour: value })
              }}
            />
          </div>

          <div className="settings-field settings-field--toggle">
            <div>
              <label className="settings-field__label">Aviso en la app</label>
              <span className="settings-field__help">Notificación dentro de DOT</span>
            </div>
            <button
              type="button"
              className={`settings-toggle${settings.notify_app ? ' settings-toggle--active' : ''}`}
              onClick={() => void patchSettings({ notify_app: !settings.notify_app })}
              disabled={saving}
              role="switch"
              aria-checked={settings.notify_app}
            >
              <span className="settings-toggle__thumb" />
            </button>
          </div>

          <div className="settings-field settings-field--toggle">
            <div>
              <label className="settings-field__label">También por WhatsApp</label>
              <span className="settings-field__help">Si tienes WhatsApp vinculado</span>
            </div>
            <button
              type="button"
              className={`settings-toggle${settings.notify_whatsapp ? ' settings-toggle--active' : ''}`}
              onClick={() => void patchSettings({ notify_whatsapp: !settings.notify_whatsapp })}
              disabled={saving}
              role="switch"
              aria-checked={settings.notify_whatsapp}
            >
              <span className="settings-toggle__thumb" />
            </button>
          </div>
        </>
      ) : null}

      {error ? <p className="settings-section__desc settings-section__desc--error">{error}</p> : null}
    </div>
  )
}
