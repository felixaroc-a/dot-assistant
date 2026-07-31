import { useState, useCallback } from 'react'

import type { IntegrationId } from '@/features/integrations'
import type { AutomationOutputType } from '@/features/dashboard/model/types'

export type UseAutomationDraftResult = {
  draftIntegration: IntegrationId
  setDraftIntegration: (id: IntegrationId) => void
  draftName: string
  setDraftName: (name: string) => void
  draftInstruction: string
  setDraftInstruction: (instruction: string) => void
  draftOutputType: AutomationOutputType
  setDraftOutputType: (type: AutomationOutputType) => void
  draftSchedule: string
  setDraftSchedule: (schedule: string) => void
  draftDescription: string
  setDraftDescription: (description: string) => void
  resetDraft: () => void
}

const DEFAULT_INTEGRATION: IntegrationId = 'google-calendar'
const DEFAULT_OUTPUT_TYPE: AutomationOutputType = 'notify'
const DEFAULT_SCHEDULE = 'manual'

export function useAutomationDraft(): UseAutomationDraftResult {
  const [draftIntegration, setDraftIntegration] = useState<IntegrationId>(DEFAULT_INTEGRATION)
  const [draftName, setDraftName] = useState('')
  const [draftInstruction, setDraftInstruction] = useState('')
  const [draftOutputType, setDraftOutputType] = useState<AutomationOutputType>(DEFAULT_OUTPUT_TYPE)
  const [draftSchedule, setDraftSchedule] = useState(DEFAULT_SCHEDULE)
  const [draftDescription, setDraftDescription] = useState('')

  const resetDraft = useCallback(() => {
    setDraftIntegration(DEFAULT_INTEGRATION)
    setDraftName('')
    setDraftInstruction('')
    setDraftOutputType(DEFAULT_OUTPUT_TYPE)
    setDraftSchedule(DEFAULT_SCHEDULE)
    setDraftDescription('')
  }, [])

  return {
    draftIntegration,
    setDraftIntegration,
    draftName,
    setDraftName,
    draftInstruction,
    setDraftInstruction,
    draftOutputType,
    setDraftOutputType,
    draftSchedule,
    setDraftSchedule,
    draftDescription,
    setDraftDescription,
    resetDraft,
  }
}
