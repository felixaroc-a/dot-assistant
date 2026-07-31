import { fetchBrowserWebPolicy } from '@/lib/api/browser-web'
import { apiFetchAuthed } from '@/lib/api/client'
import type { GetAccessToken } from '@/lib/api/client'
import { fetchUserProfile, type UserProfileDto } from '@/lib/api/user-profile'

export const USER_DATA_EXPORT_VERSION = '1.0' as const

type MemoryFact = {
  fact_id: string
  type?: string | null
  key?: string | null
  value?: string | null
  confidence?: number | null
  updated_at?: string | null
}

type MemoryOverview = {
  summary: string
  facts: MemoryFact[]
  total: number
}

type BriefingSettings = {
  enabled: boolean
  hour: string
  timezone: string
  notify_app: boolean
  notify_whatsapp: boolean
}

type ProactiveSettings = {
  heartbeat_enabled: boolean
  wa_triggers_enabled: boolean
  calendar_triggers_enabled: boolean
  composite_enabled: boolean
}

type BrowserWebPolicy = {
  enabled: boolean
}

export type UserDataLocalPreferences = {
  theme: 'light' | 'dark'
  dot_speaks_enabled: boolean
  channel_label: string | null
  display_name: string
}

export type UserDataExportSectionError = {
  section: string
  message: string
}

export type UserDataExportPayload = {
  export_version: typeof USER_DATA_EXPORT_VERSION
  exported_at: string
  product: 'DOT'
  profile: UserProfileDto | null
  memory: MemoryOverview | null
  preferences: {
    briefing: BriefingSettings | null
    proactive: ProactiveSettings | null
    browser_web: BrowserWebPolicy | null
    local: UserDataLocalPreferences
  }
  fetch_errors: UserDataExportSectionError[]
}

type SectionResult<T> =
  | { ok: true; data: T }
  | { ok: false; section: string; message: string }

async function fetchSection<T>(
  section: string,
  label: string,
  fn: () => Promise<T>,
): Promise<SectionResult<T>> {
  try {
    const data = await fn()
    return { ok: true, data }
  } catch {
    return { ok: false, section, message: `No se pudo obtener ${label}.` }
  }
}

function formatExportDate(date: Date): string {
  const pad = (value: number) => String(value).padStart(2, '0')
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}`
}

export function buildUserDataExportFilename(date: Date = new Date()): string {
  return `dot-mis-datos-${formatExportDate(date)}.json`
}

export async function buildUserDataExport(
  getAccessToken: GetAccessToken,
  localPreferences: UserDataLocalPreferences,
): Promise<UserDataExportPayload> {
  const token = await getAccessToken()
  if (!token) {
    throw new Error('Sesión no disponible. Inicia sesión de nuevo.')
  }

  const [profileResult, memoryResult, briefingResult, proactiveResult, browserResult] =
    await Promise.all([
      fetchSection('profile', 'tu perfil', () => fetchUserProfile(token)),
      fetchSection('memory', 'tu memoria', () =>
        apiFetchAuthed<MemoryOverview>('/v1/memory', { method: 'GET' }, getAccessToken),
      ),
      fetchSection('briefing', 'el briefing matutino', () =>
        apiFetchAuthed<BriefingSettings>('/v1/briefing/settings', { method: 'GET' }, getAccessToken),
      ),
      fetchSection('proactive', 'tus avisos proactivos', () =>
        apiFetchAuthed<ProactiveSettings>(
          '/v1/automations/proactive/settings',
          { method: 'GET' },
          getAccessToken,
        ),
      ),
      fetchSection('browser_web', 'la política de navegación web', () =>
        fetchBrowserWebPolicy(getAccessToken),
      ),
    ])

  const fetchErrors: UserDataExportSectionError[] = []
  const allResults: SectionResult<unknown>[] = [
    profileResult,
    memoryResult,
    briefingResult,
    proactiveResult,
    browserResult,
  ]
  for (const result of allResults) {
    if (!result.ok) {
      fetchErrors.push({ section: result.section, message: result.message })
    }
  }

  if (
    !profileResult.ok &&
    !memoryResult.ok &&
    !briefingResult.ok &&
    !proactiveResult.ok &&
    !browserResult.ok
  ) {
    throw new Error('No se pudo obtener ningún dato para exportar. Revisa tu conexión e intenta de nuevo.')
  }

  return {
    export_version: USER_DATA_EXPORT_VERSION,
    exported_at: new Date().toISOString(),
    product: 'DOT',
    profile: profileResult.ok ? profileResult.data : null,
    memory: memoryResult.ok ? memoryResult.data : null,
    preferences: {
      briefing: briefingResult.ok ? briefingResult.data : null,
      proactive: proactiveResult.ok ? proactiveResult.data : null,
      browser_web: browserResult.ok ? browserResult.data : null,
      local: localPreferences,
    },
    fetch_errors: fetchErrors,
  }
}

export async function saveUserDataExportFile(payload: UserDataExportPayload): Promise<string> {
  const json = JSON.stringify(payload, null, 2)
  const filename = buildUserDataExportFilename(new Date(payload.exported_at))

  const writeFile = window.desktop?.localTools?.writeFile
  if (writeFile) {
    const path = `~/Downloads/${filename}`
    const result = await writeFile(path, json)
    if (!result.ok) {
      throw new Error(result.error || 'No se pudo guardar el archivo en Descargas.')
    }
    return result.path || path
  }

  if (typeof document === 'undefined' || typeof URL === 'undefined') {
    throw new Error('No se pudo iniciar la descarga en este entorno.')
  }

  const blob = new Blob([json], { type: 'application/json;charset=utf-8' })
  const url = URL.createObjectURL(blob)
  try {
    const anchor = document.createElement('a')
    anchor.href = url
    anchor.download = filename
    anchor.rel = 'noopener'
    anchor.click()
  } finally {
    URL.revokeObjectURL(url)
  }

  return filename
}

export async function exportUserData(
  getAccessToken: GetAccessToken,
  localPreferences: UserDataLocalPreferences,
): Promise<{ savedPath: string; partial: boolean }> {
  const payload = await buildUserDataExport(getAccessToken, localPreferences)
  const savedPath = await saveUserDataExportFile(payload)
  return { savedPath, partial: payload.fetch_errors.length > 0 }
}
