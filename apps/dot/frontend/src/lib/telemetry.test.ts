import { afterEach, describe, expect, it, vi } from 'vitest'

import { resolveTelemetryEventUrl } from '@/lib/telemetry'

describe('telemetry URL resolution', () => {
  afterEach(() => {
    vi.unstubAllEnvs()
  })

  it('uses VITE_API_BASE_URL when set', () => {
    vi.stubEnv('VITE_API_BASE_URL', 'https://api.dot.example/')
    expect(resolveTelemetryEventUrl()).toBe('https://api.dot.example/v1/telemetry/event')
  })

  it('throws when VITE_API_BASE_URL is empty', () => {
    vi.stubEnv('VITE_API_BASE_URL', '')
    expect(() => resolveTelemetryEventUrl()).toThrow('VITE_API_BASE_URL')
  })
})
