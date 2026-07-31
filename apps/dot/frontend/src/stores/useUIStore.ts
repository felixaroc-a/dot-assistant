import { create } from 'zustand'

export type ChatExportFormat = 'docx' | 'pdf' | null

export type UIState = {
  /** Drawer lateral de automatizaciones abierto/cerrado */
  drawerOpen: boolean
  /** Modal de creador de documentos abierto/cerrado */
  docCreatorOpen: boolean
  /** Formato de exportacion de chat seleccionado */
  chatExportFormat: ChatExportFormat
}

export type UIActions = {
  openDrawer: () => void
  closeDrawer: () => void
  toggleDrawer: () => void
  openDocCreator: () => void
  closeDocCreator: () => void
  setChatExportFormat: (format: ChatExportFormat) => void
}

export type UIStore = UIState & UIActions

export const useUIStore = create<UIStore>((set) => ({
  drawerOpen: false,
  docCreatorOpen: false,
  chatExportFormat: null,

  openDrawer: () => set({ drawerOpen: true }),
  closeDrawer: () => set({ drawerOpen: false }),
  toggleDrawer: () => set((s) => ({ drawerOpen: !s.drawerOpen })),
  openDocCreator: () => set({ docCreatorOpen: true }),
  closeDocCreator: () => set({ docCreatorOpen: false }),
  setChatExportFormat: (format) => set({ chatExportFormat: format }),
}))
