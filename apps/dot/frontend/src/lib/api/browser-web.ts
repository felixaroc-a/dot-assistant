import { apiFetchAuthed } from '@/lib/api/client'
import type { GetAccessToken } from '@/lib/api/client'

/** Etiqueta única del toggle en Configuración → Privacidad. */
export const BROWSER_WEB_TOGGLE_LABEL = 'DOT puede usar webs'

export const BROWSER_WEB_SETTINGS_PATH = 'Configuración → Privacidad'

export type BrowserWebPolicy = {
  enabled: boolean
}

export async function fetchBrowserWebPolicy(getAccessToken: GetAccessToken): Promise<BrowserWebPolicy> {
  return apiFetchAuthed<BrowserWebPolicy>('/v1/tools/policies/browser-web', { method: 'GET' }, getAccessToken)
}

export async function saveBrowserWebPolicy(
  enabled: boolean,
  getAccessToken: GetAccessToken,
): Promise<BrowserWebPolicy> {
  return apiFetchAuthed<BrowserWebPolicy>(
    '/v1/tools/policies/browser-web',
    { method: 'PUT', body: JSON.stringify({ enabled }) },
    getAccessToken,
  )
}

export async function readLocalBrowserPermission(): Promise<'allowed' | 'denied' | 'requires_confirmation'> {
  try {
    const status = await window.desktop?.localTools?.getPermissionStatus?.('browser')
    if (status === 'allowed' || status === 'denied' || status === 'requires_confirmation') {
      return status
    }
  } catch {
    // ignore
  }
  return 'requires_confirmation'
}

export async function setLocalBrowserPermission(enabled: boolean): Promise<boolean> {
  try {
    const res = await window.desktop?.localTools?.setPermission?.('browser', enabled ? 'always' : 'denied')
    return Boolean(res?.ok)
  } catch {
    return false
  }
}

export function isDesktopApp(): boolean {
  return Boolean(window.desktop?.localTools?.setPermission)
}
