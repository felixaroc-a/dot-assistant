import { describe, expect, it } from 'vitest'

import { useAutomationStore } from './useAutomationStore'
import { useUIStore } from './useUIStore'

describe('useUIStore', () => {
  it('comienza con estado inicial', () => {
    const state = useUIStore.getState()
    expect(state.drawerOpen).toBe(false)
    expect(state.docCreatorOpen).toBe(false)
    expect(state.chatExportFormat).toBeNull()
  })

  it('openDrawer / closeDrawer funcionan', () => {
    const store = useUIStore.getState()
    store.openDrawer()
    expect(useUIStore.getState().drawerOpen).toBe(true)
    store.closeDrawer()
    expect(useUIStore.getState().drawerOpen).toBe(false)
  })

  it('toggleDrawer alterna el estado', () => {
    useUIStore.getState().toggleDrawer()
    expect(useUIStore.getState().drawerOpen).toBe(true)
    useUIStore.getState().toggleDrawer()
    expect(useUIStore.getState().drawerOpen).toBe(false)
  })

  it('openDocCreator / closeDocCreator funcionan', () => {
    useUIStore.getState().openDocCreator()
    expect(useUIStore.getState().docCreatorOpen).toBe(true)
    useUIStore.getState().closeDocCreator()
    expect(useUIStore.getState().docCreatorOpen).toBe(false)
  })

  it('setChatExportFormat actualiza el formato', () => {
    useUIStore.getState().setChatExportFormat('pdf')
    expect(useUIStore.getState().chatExportFormat).toBe('pdf')
    useUIStore.getState().setChatExportFormat(null)
    expect(useUIStore.getState().chatExportFormat).toBeNull()
  })
})

describe('useAutomationStore', () => {
  it('comienza con estado inicial vacio', () => {
    const state = useAutomationStore.getState()
    expect(state.automations).toEqual([])
    expect(state.hasPendingResults).toBe(false)
    expect(state.pendingAutomation).toBeNull()
    expect(state.whatsappStatus).toBe('disconnected')
  })

  it('setAutomations reemplaza la lista', () => {
    const auto = { id: '1', name: 'Test', integrationId: 'gmail' as const, instruction: 'test', active: true }
    useAutomationStore.getState().setAutomations([auto])
    expect(useAutomationStore.getState().automations).toHaveLength(1)
    expect(useAutomationStore.getState().automations[0].name).toBe('Test')
  })

  it('addAutomation agrega sin duplicar', () => {
    useAutomationStore.getState().setAutomations([])
    const auto = { id: '2', name: 'Auto 2', integrationId: 'gmail' as const, instruction: 'test', active: true }
    useAutomationStore.getState().addAutomation(auto)
    expect(useAutomationStore.getState().automations).toHaveLength(1)
  })

  it('updateAutomation modifica parcialmente', () => {
    useAutomationStore.getState().setAutomations([
      { id: '3', name: 'Original', integrationId: 'gmail' as const, instruction: 'test', active: true },
    ])
    useAutomationStore.getState().updateAutomation('3', { name: 'Updated', active: false })
    const updated = useAutomationStore.getState().automations[0]
    expect(updated.name).toBe('Updated')
    expect(updated.active).toBe(false)
  })

  it('clearPendingResults resetea ambos campos', () => {
    useAutomationStore.getState().setHasPendingResults(true)
    useAutomationStore.getState().setPendingAutomation({ has_new: true, last_auto_id: '1', last_auto_name: 'test', last_executed_at: null, last_result_preview: null })
    useAutomationStore.getState().clearPendingResults()
    expect(useAutomationStore.getState().hasPendingResults).toBe(false)
    expect(useAutomationStore.getState().pendingAutomation).toBeNull()
  })
})
