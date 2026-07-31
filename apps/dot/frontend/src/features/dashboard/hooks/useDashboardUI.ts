import { useState } from 'react'

export type UseDashboardUIResult = {
  drawerOpen: boolean
  setDrawerOpen: (open: boolean) => void
  docCreatorOpen: boolean
  setDocCreatorOpen: (open: boolean) => void
  chatExportFormat: 'docx' | 'pdf' | null
  setChatExportFormat: (format: 'docx' | 'pdf' | null) => void
}

export function useDashboardUI(): UseDashboardUIResult {
  const [drawerOpen, setDrawerOpen] = useState(false)
  const [docCreatorOpen, setDocCreatorOpen] = useState(false)
  const [chatExportFormat, setChatExportFormat] = useState<'docx' | 'pdf' | null>(null)

  return {
    drawerOpen,
    setDrawerOpen,
    docCreatorOpen,
    setDocCreatorOpen,
    chatExportFormat,
    setChatExportFormat,
  }
}
