import { describe, expect, it } from 'vitest'

import {
  USER_DATA_EXPORT_VERSION,
  buildUserDataExportFilename,
  type UserDataExportPayload,
} from '@/features/dashboard/lib/user-data-export'

describe('user-data-export', () => {
  it('genera nombre de archivo con fecha ISO local', () => {
    const filename = buildUserDataExportFilename(new Date('2026-07-24T15:30:00'))
    expect(filename).toBe('dot-mis-datos-2026-07-24.json')
  })

  it('payload incluye versión y secciones esperadas', () => {
    const payload: UserDataExportPayload = {
      export_version: USER_DATA_EXPORT_VERSION,
      exported_at: '2026-07-24T12:00:00.000Z',
      product: 'DOT',
      profile: null,
      memory: null,
      preferences: {
        briefing: null,
        proactive: null,
        browser_web: null,
        local: {
          theme: 'dark',
          dot_speaks_enabled: false,
          channel_label: 'PC',
          display_name: 'Ana',
        },
      },
      fetch_errors: [],
    }

    expect(payload.export_version).toBe('1.0')
    expect(payload.preferences.local.display_name).toBe('Ana')
    expect(payload.fetch_errors).toEqual([])
  })
})
