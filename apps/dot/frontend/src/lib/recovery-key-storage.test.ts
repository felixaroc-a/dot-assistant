import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import {
  hasRecoveryKeyLocal,
  loadRecoveryKeyLocal,
  saveRecoveryKeyLocal,
} from './recovery-key-storage'

const STORAGE_KEY = 'dot_recovery_key_backup'

function createMockStorage() {
  const store: Record<string, string> = {}
  return {
    getItem: vi.fn((key: string) => store[key] ?? null),
    setItem: vi.fn((key: string, value: string) => {
      store[key] = value
    }),
    removeItem: vi.fn((key: string) => {
      delete store[key]
    }),
    clear: vi.fn(() => {
      Object.keys(store).forEach((k) => delete store[k])
    }),
    get length() {
      return Object.keys(store).length
    },
    key: vi.fn((i: number) => Object.keys(store)[i] ?? null),
  }
}

describe('recovery-key-storage', () => {
  let mockStorage: ReturnType<typeof createMockStorage>

  beforeEach(() => {
    mockStorage = createMockStorage()
    vi.stubGlobal('localStorage', mockStorage)
    // Ensure desktop API is not available so tests use localStorage fallback
    delete (window as { desktop?: unknown }).desktop
  })

  afterEach(() => {
    vi.restoreAllMocks()
    vi.unstubAllGlobals()
  })

  describe('saveRecoveryKeyLocal', () => {
    it('guarda la key en localStorage y retorna true', async () => {
      const result = await saveRecoveryKeyLocal('test-recovery-key-123')
      expect(result).toBe(true)
      expect(mockStorage.setItem).toHaveBeenCalledWith(
        STORAGE_KEY,
        'test-recovery-key-123',
      )
      const saved = await loadRecoveryKeyLocal()
      expect(saved).toBe('test-recovery-key-123')
    })

    it('retorna false si localStorage falla', async () => {
      mockStorage.setItem.mockImplementationOnce(() => {
        throw new Error('Storage full')
      })
      const result = await saveRecoveryKeyLocal('key')
      expect(result).toBe(false)
    })
  })

  describe('loadRecoveryKeyLocal', () => {
    it('recupera el valor previamente guardado', async () => {
      await saveRecoveryKeyLocal('my-saved-key')
      const result = await loadRecoveryKeyLocal()
      expect(result).toBe('my-saved-key')
    })

    it('retorna null si no hay key guardada', async () => {
      const result = await loadRecoveryKeyLocal()
      expect(result).toBeNull()
    })

    it('retorna null si localStorage falla', async () => {
      mockStorage.getItem.mockImplementationOnce(() => {
        throw new Error('Access denied')
      })
      const result = await loadRecoveryKeyLocal()
      expect(result).toBeNull()
    })
  })

  describe('hasRecoveryKeyLocal', () => {
    it('retorna true cuando existe una key guardada', async () => {
      await saveRecoveryKeyLocal('some-key')
      const result = await hasRecoveryKeyLocal()
      expect(result).toBe(true)
    })

    it('retorna false cuando no hay key guardada', async () => {
      const result = await hasRecoveryKeyLocal()
      expect(result).toBe(false)
    })

    it('retorna false cuando la key guardada es un string vacío', async () => {
      // Pre-populate localStorage with empty string
      mockStorage.getItem.mockReturnValue('')
      const result = await hasRecoveryKeyLocal()
      expect(result).toBe(false)
    })
  })
})
