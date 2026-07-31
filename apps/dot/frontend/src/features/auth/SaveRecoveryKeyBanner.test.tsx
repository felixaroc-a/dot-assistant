import { act, cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { SaveRecoveryKeyBanner } from './SaveRecoveryKeyBanner'

const mockHasRecoveryKeyLocal = vi.hoisted(() => vi.fn())
const mockSaveRecoveryKeyLocal = vi.hoisted(() => vi.fn())

vi.mock('../../lib/recovery-key-storage', () => ({
  hasRecoveryKeyLocal: (...args: unknown[]) => mockHasRecoveryKeyLocal(...args),
  saveRecoveryKeyLocal: (...args: unknown[]) => mockSaveRecoveryKeyLocal(...args),
}))

describe('SaveRecoveryKeyBanner', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mockHasRecoveryKeyLocal.mockResolvedValue(false)
  })

  afterEach(() => {
    cleanup()
    vi.useRealTimers()
  })

  it('se muestra cuando recoveryKey está presente y no hay key guardada', async () => {
    render(<SaveRecoveryKeyBanner recoveryKey="abc-123-def" />)

    expect(await screen.findByText('Guarda tu Recovery Key')).toBeInTheDocument()
    expect(screen.getByText('abc-123-def')).toBeInTheDocument()
    expect(screen.getByText('Guardar en mi PC')).toBeInTheDocument()
    expect(screen.getByText('Ahora no')).toBeInTheDocument()
  })

  it('se oculta si ya existe recovery key guardada', async () => {
    mockHasRecoveryKeyLocal.mockResolvedValue(true)

    render(<SaveRecoveryKeyBanner recoveryKey="abc-123-def" />)

    await vi.waitFor(() => {
      expect(screen.queryByText('Guarda tu Recovery Key')).not.toBeInTheDocument()
    })
  })

  it('al hacer clic en "Guardar en mi PC" llama a saveRecoveryKeyLocal', async () => {
    mockSaveRecoveryKeyLocal.mockResolvedValue(true)

    render(<SaveRecoveryKeyBanner recoveryKey="abc-123-def" />)

    expect(await screen.findByText('Guardar en mi PC')).toBeInTheDocument()
    fireEvent.click(screen.getByText('Guardar en mi PC'))

    await vi.waitFor(() => {
      expect(mockSaveRecoveryKeyLocal).toHaveBeenCalledWith('abc-123-def')
    })
  })

  it('al hacer clic en "Ahora no" se oculta', async () => {
    render(<SaveRecoveryKeyBanner recoveryKey="abc-123-def" />)

    expect(await screen.findByText('Ahora no')).toBeInTheDocument()
    fireEvent.click(screen.getByText('Ahora no'))

    await vi.waitFor(() => {
      expect(screen.queryByText('Guarda tu Recovery Key')).not.toBeInTheDocument()
    })
  })

  it('muestra mensaje de confirmación después de guardar', async () => {
    mockSaveRecoveryKeyLocal.mockResolvedValue(true)

    render(<SaveRecoveryKeyBanner recoveryKey="abc-123-def" />)

    expect(await screen.findByText('Guardar en mi PC')).toBeInTheDocument()
    fireEvent.click(screen.getByText('Guardar en mi PC'))

    expect(await screen.findByText('Recovery Key guardada')).toBeInTheDocument()
    expect(
      screen.getByText(/tu recovery key fue guardada de forma segura/i),
    ).toBeInTheDocument()
  })

  it('desaparece automáticamente tras 3 segundos después de guardar', async () => {
    mockSaveRecoveryKeyLocal.mockResolvedValue(true)
    const onDismiss = vi.fn()

    render(<SaveRecoveryKeyBanner recoveryKey="abc-123-def" onDismiss={onDismiss} />)

    // Wait for initial render with real timers
    expect(await screen.findByText('Guardar en mi PC')).toBeInTheDocument()

    // Fake timers before click so the component's setTimeout is controlled
    vi.useFakeTimers()
    await act(async () => {
      fireEvent.click(screen.getByText('Guardar en mi PC'))
    })

    // Clicking inside act should flush microtasks and process state updates
    expect(screen.getByText('Recovery Key guardada')).toBeInTheDocument()
    expect(screen.queryByText('Guardar en mi PC')).not.toBeInTheDocument()

    // Advance the 3s setTimeout
    act(() => {
      vi.advanceTimersByTime(3000)
    })

    expect(screen.queryByText('Recovery Key guardada')).not.toBeInTheDocument()
    expect(onDismiss).toHaveBeenCalled()
  })

  it('no llama a onDismiss al hacer clic en "Ahora no"', async () => {
    const onDismiss = vi.fn()

    render(<SaveRecoveryKeyBanner recoveryKey="abc-123-def" onDismiss={onDismiss} />)

    expect(await screen.findByText('Ahora no')).toBeInTheDocument()
    fireEvent.click(screen.getByText('Ahora no'))

    await vi.waitFor(() => {
      expect(screen.queryByText('Guarda tu Recovery Key')).not.toBeInTheDocument()
    })
    expect(onDismiss).not.toHaveBeenCalled()
  })
})
