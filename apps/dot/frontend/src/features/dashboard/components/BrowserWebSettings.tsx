import { useCallback, useEffect, useState } from 'react'

import {
  BROWSER_WEB_TOGGLE_LABEL,
  fetchBrowserWebPolicy,
  isDesktopApp,
  readLocalBrowserPermission,
  saveBrowserWebPolicy,
  setLocalBrowserPermission,
} from '@/lib/api/browser-web'
import type { GetAccessToken } from '@/lib/api/client'

export type BrowserWebSettingsProps = {
  getAccessToken: GetAccessToken
}

export function BrowserWebSettings({ getAccessToken }: BrowserWebSettingsProps) {
  const [enabled, setEnabled] = useState(false)
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const desktop = isDesktopApp()

  const load = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const policy = await fetchBrowserWebPolicy(getAccessToken)
      let nextEnabled = policy.enabled
      if (desktop) {
        const local = await readLocalBrowserPermission()
        nextEnabled = policy.enabled && local === 'allowed'
      }
      setEnabled(nextEnabled)
    } catch {
      setError('No se pudo cargar el permiso de webs.')
    } finally {
      setLoading(false)
    }
  }, [desktop, getAccessToken])

  useEffect(() => {
    void load()
  }, [load])

  const toggle = useCallback(async () => {
    const next = !enabled
    setSaving(true)
    setError(null)
    const previous = enabled
    setEnabled(next)
    try {
      if (desktop) {
        const localOk = await setLocalBrowserPermission(next)
        if (!localOk) {
          throw new Error('local_permission_failed')
        }
      }
      await saveBrowserWebPolicy(next, getAccessToken)
    } catch {
      setEnabled(previous)
      setError(
        desktop
          ? 'No se pudo guardar. Intenta de nuevo.'
          : 'Este permiso solo se puede activar en la app de escritorio DOT.',
      )
    } finally {
      setSaving(false)
    }
  }, [desktop, enabled, getAccessToken])

  if (loading) {
    return <p className="settings-section__desc">Cargando permiso de webs…</p>
  }

  return (
    <div className="settings-section__card">
      <div className="settings-field settings-field--toggle">
        <div>
          <label className="settings-field__label">{BROWSER_WEB_TOGGLE_LABEL}</label>
          <span className="settings-field__help">
            {enabled
              ? 'Activado — DOT puede entrar a sitios, leer textos, ver precios, hacer clic y rellenar formularios cuando se lo pidas.'
              : 'Desactivado — DOT no visitará páginas web por ti. Modo seguro por defecto.'}
          </span>
          <span className="settings-field__help">
            {enabled
              ? 'Desactívalo si no quieres que DOT abra sitios (por ejemplo, en cuentas compartidas).'
              : 'Actívalo cuando quieras pedirle cosas como «entra a esta página» o «¿cuánto cuesta en Amazon?». No necesitas el Modo privilegiado para webs.'}
          </span>
          {!desktop ? (
            <span className="settings-field__help">
              Instala y abre la app de escritorio DOT para usar esta opción.
            </span>
          ) : null}
        </div>
        <button
          type="button"
          className={`settings-toggle${enabled ? ' settings-toggle--active' : ''}`}
          onClick={() => void toggle()}
          disabled={saving || !desktop}
          aria-label={enabled ? `Desactivar ${BROWSER_WEB_TOGGLE_LABEL}` : BROWSER_WEB_TOGGLE_LABEL}
          role="switch"
          aria-checked={enabled}
        >
          <span className="settings-toggle__thumb" />
        </button>
      </div>
      {error ? <p className="settings-section__desc settings-section__desc--error">{error}</p> : null}
    </div>
  )
}
