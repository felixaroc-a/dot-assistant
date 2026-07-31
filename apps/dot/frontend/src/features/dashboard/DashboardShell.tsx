import { AnimatePresence, motion, useReducedMotion } from 'framer-motion'
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'

import { wsClient } from '@/lib/websocket-client'
import { useOnlineStatus } from '@/lib/use-online-status'
import { useTheme } from '@/shared/theme-context'
import { useKeyboardShortcuts, KeyboardShortcutsHelp } from '@/shared'
import { SaveRecoveryKeyBanner, useAuth } from '@/features/auth'
import { AutomationDrawerFields } from '@/features/dashboard/components/automation-drawer/AutomationDrawerFields'
import { AutomationSidebar } from '@/features/dashboard/components/AutomationSidebar'
import { ConversationList } from '@/features/dashboard/components/ConversationList'
import { DashboardBanners } from '@/features/dashboard/components/DashboardBanners'
import { DashboardNotifications, MORNING_BRIEFING_AUTO_ID } from '@/features/dashboard/components/DashboardNotifications'
import { DotChatPanel } from '@/features/dashboard/components/chat/DotChatPanel'
import { WorkspaceHeader } from '@/features/dashboard/components/WorkspaceHeader'
import { StatusSidebar } from '@/features/dashboard/components/StatusSidebar'
import {
  IntegrationsSessionsDrawer,
  type IntegrationsFocus,
} from '@/features/dashboard/components/IntegrationsSessionsDrawer'
import { FeatureErrorBoundary } from '@/components/FeatureErrorBoundary'
import { useToast } from '@/components/Toast'
import {
  useAutomationDraft,
  useAutomationPolling,
  useMorningBriefingBoot,
  useConversations,
  useDashboardGoogle,
  useDashboardPipelines,
  useDashboardState,
  useDashboardUI,
  useDashboardWhatsApp,
  useDocumentExport,
  useReminderPolling,
  useRemindersPanel,
  useAgendaSidebar,
  useSlashCommands,
  useUsageSummary,
} from '@/features/dashboard/hooks'
import { parseAssistantDocumentAction } from '@/features/dashboard/lib/slash-commands'
import { parseLocalToolAction, formatLocalToolResult, extractHttpUrl, isBinaryLocalPath } from '@/features/dashboard/lib/parse-local-tool-action'
import { PipelineEditor } from '@/features/dashboard/components/automations/PipelineEditor'
import { StorePanel, type StoreSkill } from '@/features/dashboard/components/StorePanel'
import { SettingsPanel } from '@/features/dashboard/components/SettingsPanel'
import { usePipelines } from '@/features/dashboard/hooks/usePipelines'
import type {
  AutomationOutputType,
  AutomationPendingResponse,
  GeneratedDocPreview,
  PipelineDef,
  PipelineStepRunStatus,
  PipelineTemplate,
  PopularAutomationTemplate,
  PopularAutomationTemplatesResponse,
  SavedAutomation,
  TemplateCloneResponse,
  TemplateSaveRequest,
} from '@/features/dashboard/model/types'
import type { DocumentType } from '@/lib/api/documents'
import { apiFetchAuthed } from '@/lib/api/client'
import { translateError, translateErrorMessage } from '@/lib/error-messages'
import { USAGE_LIMIT_BLOCKED_MESSAGE } from '@/lib/usage-messages'
import { UsageRechargeGuide } from '@/features/dashboard/components/UsageRechargeGuide'
import type { UserProfileDto } from '@/lib/api/user-profile'
import type { ConversationSummary } from '@/lib/chat/client'
import { useChat } from '@/lib/chat/useChat'
import { useReasoningMode, type ReasoningLevel } from '@/lib/chat/useReasoningMode'
import type { SendMessageOptions } from '@/lib/chat/types'
import { DocumentCreatorModal } from '@/features/dashboard/components/document-creator/DocumentCreatorModal'
import { useDocumentGenerator } from '@/lib/documents/useDocumentGenerator'
import { buildSubscriptionReminder } from '@/features/dashboard/lib/subscription-reminder'
import type { IntegrationId } from '@/features/integrations'
import { shouldRedirectToWhatsApp } from '@/lib/chat/whatsappRedirect'
import { sendWhatsAppOutbound } from '@/lib/api/whatsapp'
import { getVoiceStatus } from '@/lib/api/voice'
import { useDotSpeaks } from '@/features/dashboard/hooks/useDotSpeaks'
import { useTalkMode } from '@/features/dashboard/hooks/useTalkMode'
import { useTtsPlayback } from '@/features/dashboard/hooks/useTtsPlayback'

import './main-dashboard.css'
import './settings-panel.css'

export type DashboardShellProps = {
  userDisplayName: string
  channelLabel: string | null
  profileSyncWarning?: string | null
}

export function DashboardShell({
  userDisplayName,
  channelLabel,
  profileSyncWarning,
}: DashboardShellProps) {
  const { getAccessToken, logout, isSubscriptionExpired, subscriptionExpiryDate, session } = useAuth()
  const { toast, success: toastSuccess } = useToast()
  const { t } = useTranslation()
  const { theme, toggleTheme } = useTheme()
  const isOnline = useOnlineStatus()
  const reduceMotion = useReducedMotion()
  const {
    summary: usageSummary,
    loading: usageLoading,
    error: usageError,
    dailyHistory: usageDailyHistory,
    refreshNow: refreshUsageNow,
  } = useUsageSummary({ getAccessToken, pollIntervalMs: 30_000 })

  const [wsConnected, setWsConnected] = useState(false)
  const [whatsappUnreadCount, setWhatsappUnreadCount] = useState(0)
  const [whatsappMode, setWhatsappMode] = useState(false)
  const [usageBlockDismissed, setUsageBlockDismissed] = useState(false)
  const [showingArchived, setShowingArchived] = useState(false)
  const [archivedConversations, setArchivedConversations] = useState<ConversationSummary[]>([])
  const [archivedSearchSnippets, setArchivedSearchSnippets] = useState<Record<string, string>>({})
  const [archivedSearching, setArchivedSearching] = useState(false)
  const [automationFailures, setAutomationFailures] = useState<Array<{id: string; auto_name: string; error: string; failed_at: string}>>([])

  // B06: TTS — estado de voz
  const [voiceStatusLoaded, setVoiceStatusLoaded] = useState(false)
  const [voiceSttAvailable, setVoiceSttAvailable] = useState(false)
  const [voiceTtsAvailable, setVoiceTtsAvailable] = useState(false)
  const [drawerMode, setDrawerMode] = useState<'automation' | 'pipeline'>('automation')
  const [editingPipeline, setEditingPipeline] = useState<PipelineDef | null>(null)
  const [editingAutomation, setEditingAutomation] = useState<SavedAutomation | null>(null)
  const [focusPipelinesNonce, setFocusPipelinesNonce] = useState(0)
  const [docPreview, setDocPreview] = useState<GeneratedDocPreview | null>(null)
  const [storeOpen, setStoreOpen] = useState(false)
  const [settingsOpen, setSettingsOpen] = useState(false)
  const [installedSkillIds, setInstalledSkillIds] = useState<Set<string>>(new Set())
  const [profileReasoningEnabled, setProfileReasoningEnabled] = useState<boolean | undefined>(undefined)
  const [profileReasoningLevel, setProfileReasoningLevel] = useState<ReasoningLevel | undefined>(undefined)
  const [integrationsOpen, setIntegrationsOpen] = useState(false)
  const [integrationsFocus, setIntegrationsFocus] = useState<IntegrationsFocus>(null)
  const [templates, setTemplates] = useState<PipelineTemplate[]>([])
  const [templatesLoading, setTemplatesLoading] = useState(false)
  const [cloningTemplateId, setCloningTemplateId] = useState<string | null>(null)
  const [popularTemplates, setPopularTemplates] = useState<PopularAutomationTemplate[]>([])
  const [popularTemplatesLoading, setPopularTemplatesLoading] = useState(false)
  const [showSyncToast, setShowSyncToast] = useState(false)
  const dotSpeaks = useDotSpeaks()
  const ttsPlayback = useTtsPlayback({
    getAccessToken,
    translate: t,
    onError: (message) => toast(message, 'error'),
  })
  const lastAutoSpokenIdRef = useRef<string | null>(null)

  // Resetear dismiss si el estado de bloqueo cambia (vuelve a bloquear tras recarga)
  useEffect(() => {
    if (usageSummary?.blocked) {
      setUsageBlockDismissed(false)
    }
  }, [usageSummary?.blocked])

  const state = useDashboardState({ session })
  const draft = useAutomationDraft()
  const ui = useDashboardUI()
  const convs = useConversations({ getAccessToken })
  const imageGenEnabled = state.capabilities?.includes('image_generation') ?? false
  const convsRef = useRef(convs)
  convsRef.current = convs

  const handleConversationIdChange = useCallback((id: string) => {
    if (convsRef.current.activeId !== id) {
      void convsRef.current.selectConversation(id)
    }
  }, [])

  const handleExchangeComplete = useCallback(() => {
    void convsRef.current.refresh()
  }, [])

  const handleConversationSearch = useCallback(
    async (query: string) => {
      if (showingArchived) {
        setArchivedSearching(true)
        try {
          const token = await getAccessToken()
          const { getArchivedConversations, searchMessages } = await import('@/lib/chat/client')
          const trimmed = query.trim()
          if (!trimmed) {
            const archived = await getArchivedConversations(token)
            setArchivedConversations(archived)
            setArchivedSearchSnippets({})
            return
          }
          const [list, hits] = await Promise.all([
            getArchivedConversations(token, trimmed),
            trimmed.length >= 2 ? searchMessages(trimmed, token) : Promise.resolve(null),
          ])
          setArchivedConversations(list)
          const snippets: Record<string, string> = {}
          if (hits?.results) {
            for (const hit of hits.results) {
              if (!snippets[hit.conversation_id]) {
                snippets[hit.conversation_id] = hit.snippet
              }
            }
          }
          setArchivedSearchSnippets(snippets)
        } catch {
          // ignorar errores de búsqueda en archivadas
        } finally {
          setArchivedSearching(false)
        }
        return
      }
      await convsRef.current.searchConversations(query)
    },
    [getAccessToken, showingArchived],
  )

  const reasoningMode = useReasoningMode({
    getAccessToken,
    profileEnabled: profileReasoningEnabled,
    profileLevel: profileReasoningLevel,
  })
  const {
    pipelines,
    loading: pipelinesLoading,
    fetchPipelines,
    createPipeline,
    updatePipeline,
    deletePipeline,
    executePipeline,
  } = usePipelines({ getAccessToken })

  const chat = useChat({
    getAccessToken,
    initialConversationId: convs.activeId ?? undefined,
    defaultReasoningEnabled: reasoningMode.enabled,
    defaultReasoningLevel: reasoningMode.level,
    onAiActivityComplete: () => {
      void refreshUsageNow()
    },
    onConversationIdChange: handleConversationIdChange,
    onExchangeComplete: handleExchangeComplete,
  })
  const loadConversationRef = useRef(chat.loadConversation)
  loadConversationRef.current = chat.loadConversation
  const docGen = useDocumentGenerator(getAccessToken)
  const { handleSend, translateText, summarizeText } = useSlashCommands({ getAccessToken, chat, docGen })

  const { whatsappRefreshing, phoneNumber: whatsappPhone, refreshWhatsappStatus } = useDashboardWhatsApp({
    getAccessToken,
    setWhatsappStatus: state.setWhatsappStatus,
    activeConversationId: convs.activeId,
    refreshConversations: convs.refresh,
    loadConversation: chat.loadConversation,
  })

  // ─── A07: WhatsApp redirect ─────────────────────────────

  const handleToggleWhatsappMode = useCallback(() => {
    setWhatsappMode((prev) => !prev)
  }, [])

  const handleSendWithWhatsAppRedirect = useCallback(
    (text: string, options?: SendMessageOptions) => {
      const trimmed = text.trim()
      if (!trimmed) return

      const redirectByKeywords = shouldRedirectToWhatsApp(trimmed)
      const shouldRedirect = whatsappMode || redirectByKeywords
      const waLinked = state.whatsappStatus === 'linked'
      const hasPhone = typeof whatsappPhone === 'string' && whatsappPhone.length > 0

      if (shouldRedirect && waLinked && hasPhone) {
        // Resetear toggle manual después de enviar
        setWhatsappMode(false)

        // Enviar por WhatsApp
        void sendWhatsAppOutbound(
          { to: whatsappPhone!, text: trimmed },
          getAccessToken,
        ).then((result) => {
          if (result.success) {
            toastSuccess('Enviado por WhatsApp')
          } else {
            toast(translateErrorMessage(result.error, 'No se pudo enviar por WhatsApp. Intenta de nuevo.'), 'error')
          }
        }).catch(() => {
          toast('No se pudo enviar por WhatsApp. Revisa tu conexión.', 'error')
        })
        return
      }

      // Si hay intención de WhatsApp pero no está vinculado, avisar
      if (shouldRedirect && !waLinked) {
        toast('WhatsApp no está vinculado. Escanea el QR para vincularlo.', 'warning')
        setWhatsappMode(false)
        return
      }

      // Si hay intención de WhatsApp pero no hay número de teléfono, avisar
      if (shouldRedirect && !hasPhone) {
        toast('No se pudo obtener el número de WhatsApp. Reintenta en unos segundos.', 'warning')
        setWhatsappMode(false)
        return
      }

      // Flujo normal: enviar por chat PC
      handleSend(text, options)
    },
    [whatsappMode, state.whatsappStatus, whatsappPhone, getAccessToken, toast, toastSuccess, handleSend],
  )

  // ─── B06: TTS handler ───────────────────────────────────

  const handleTextToSpeech = useCallback(
    (text: string, messageId: string) => {
      void ttsPlayback.speak(text, messageId)
    },
    [ttsPlayback],
  )

  const handleDotSpeaksChange = useCallback(
    (enabled: boolean) => {
      if (!voiceTtsAvailable && enabled) {
        toast(t('voice.speak_unavailable'), 'warning')
        return
      }
      if (enabled) {
        const lastAssistant = [...chat.messages]
          .reverse()
          .find((m) => m.role === 'assistant' && m.status === 'sent' && m.text.trim())
        if (lastAssistant) {
          lastAutoSpokenIdRef.current = lastAssistant.id
        }
      } else {
        ttsPlayback.stop()
      }
      dotSpeaks.setEnabled(enabled)
    },
    [chat.messages, dotSpeaks, voiceTtsAvailable, toast, t, ttsPlayback],
  )

  const handleToggleDotSpeaks = useCallback(() => {
    handleDotSpeaksChange(!dotSpeaks.enabled)
  }, [dotSpeaks.enabled, handleDotSpeaksChange])

  const talk = useTalkMode({
    getAccessToken,
    disabled:
      Boolean(usageSummary?.blocked)
      || (voiceStatusLoaded && (!voiceSttAvailable || !voiceTtsAvailable)),
    stopOtherAudio: ttsPlayback.stop,
    onError: (message) => toast(message, 'error'),
    onExchange: (userText) => {
      if (userText.trim()) {
        handleSendWithWhatsAppRedirect(userText.trim())
      }
    },
  })

  // ─── Hooks extraídos ────────────────────────────────────

  const pipelinesCtx = useDashboardPipelines({
    pipelines,
    executePipeline,
    fetchPipelines,
    pushLocalExchange: chat.pushLocalExchange,
  })

  const { googleConnected, handleRevokeGoogle, refreshGoogleStatus } = useDashboardGoogle({
    getAccessToken,
    pushLocalExchange: chat.pushLocalExchange,
  })

  const openIntegrations = useCallback((focus?: 'whatsapp' | 'google') => {
    setIntegrationsFocus(focus ?? null)
    setIntegrationsOpen(true)
  }, [])

  const closeIntegrations = useCallback(() => {
    setIntegrationsOpen(false)
    setIntegrationsFocus(null)
  }, [])

  // ─── Estado WebSocket ───────────────────────────────────

  useEffect(() => {
    wsClient.onStatusChange((status) => {
      setWsConnected(status === 'connected')
    })
  }, [])

  const openSettings = useCallback(() => {
    setSettingsOpen(true)
  }, [])

  // ─── B06: Estado de voz (TTS/STT) ───────────────────────

  useEffect(() => {
    let cancelled = false
    void (async () => {
      try {
        const token = await getAccessToken()
        if (!token || cancelled) return
        const status = await getVoiceStatus(token)
        if (!cancelled) {
          setVoiceSttAvailable(status.stt === 'ready')
          setVoiceTtsAvailable(status.tts === 'ready')
          setVoiceStatusLoaded(true)
        }
      } catch {
        if (!cancelled) {
          setVoiceStatusLoaded(true)
        }
      }
    })()
    return () => { cancelled = true }
  }, [getAccessToken])

  // Auto-TTS: leer respuestas del asistente cuando "DOT habla" está activo
  useEffect(() => {
    if (!dotSpeaks.hydrated) return
    if (lastAutoSpokenIdRef.current !== null) return

    const lastAssistant = [...chat.messages]
      .reverse()
      .find((m) => m.role === 'assistant' && m.status === 'sent' && m.text.trim())
    if (lastAssistant) {
      lastAutoSpokenIdRef.current = lastAssistant.id
    }
  }, [dotSpeaks.hydrated, chat.messages])

  useEffect(() => {
    if (!dotSpeaks.hydrated || !dotSpeaks.enabled || !voiceTtsAvailable) return

    const lastAssistant = [...chat.messages]
      .reverse()
      .find((m) => m.role === 'assistant' && m.status === 'sent' && m.text.trim())

    if (!lastAssistant || lastAssistant.id === lastAutoSpokenIdRef.current) return

    lastAutoSpokenIdRef.current = lastAssistant.id
    void ttsPlayback.speak(lastAssistant.text, lastAssistant.id)
  }, [chat.messages, dotSpeaks.enabled, dotSpeaks.hydrated, voiceTtsAvailable, ttsPlayback.speak])

  useEffect(() => {
    if (!dotSpeaks.enabled) {
      lastAutoSpokenIdRef.current = null
      ttsPlayback.stop()
    }
  }, [dotSpeaks.enabled, ttsPlayback.stop])

  // B3: Escuchar mensajes WhatsApp inbound via WebSocket
  useEffect(() => {
    wsClient.on('whatsapp:inbound', (data?: { conversation_id?: string }) => {
      void (async () => {
        await convsRef.current.refresh()
        const waConvId =
          data?.conversation_id ??
          convsRef.current.conversations.find((c) => c.channel === 'whatsapp')?.id
        if (waConvId && convsRef.current.activeId === waConvId) {
          await loadConversationRef.current(waConvId)
        } else if (waConvId) {
          setWhatsappUnreadCount((prev) => prev + 1)
        }
      })()
    })
  }, [])

  // ─── Plantillas ─────────────────────────────────────────

  const fetchTemplates = useCallback(async () => {
    setTemplatesLoading(true)
    try {
      const data = await apiFetchAuthed<{ templates: PipelineTemplate[] }>(
        '/v1/templates/automation',
        { method: 'GET' },
        getAccessToken,
      )
      setTemplates(data.templates || [])
    } catch (err) {
      console.warn('[Dashboard] No se pudieron cargar plantillas:', err)
      setTemplates([])
    } finally {
      setTemplatesLoading(false)
    }
  }, [getAccessToken])

  const handleCloneTemplate = useCallback(async (templateId: string) => {
    setCloningTemplateId(templateId)
    try {
      const result = await apiFetchAuthed<TemplateCloneResponse>(
        `/v1/templates/automation/${templateId}/clone`,
        { method: 'POST' },
        getAccessToken,
      )
      const wf = result.workflow_def
      const created = await createPipeline({
        name: result.template_name,
        description: wf.description || '',
        schedule: result.schedule,
        steps: wf.steps || [],
      })
      if (!created) {
        chat.pushLocalExchange('', '❌ Error al crear el pipeline desde la plantilla. Intenta de nuevo.')
        return
      }
      pipelinesCtx.setPipelineFeedback(`Plantilla "${result.template_name}" clonada. Ya está en Pipelines.`)
      chat.pushLocalExchange(
        '',
        `✅ Plantilla "${result.template_name}" clonada. Revisa la sección Pipelines en el panel izquierdo.`,
      )
      void fetchTemplates()
    } catch (err) {
      console.warn('[Dashboard] Error al clonar plantilla:', err)
      pipelinesCtx.setPipelineFeedback('Error al clonar la plantilla. Intenta de nuevo.')
      chat.pushLocalExchange('', '❌ Error al clonar la plantilla. Intenta de nuevo.')
    } finally {
      setCloningTemplateId(null)
    }
  }, [getAccessToken, chat, fetchTemplates, createPipeline, pipelinesCtx])

  const handleSavePipelineAsTemplate = useCallback(async (pipeline: PipelineDef) => {
    try {
      const req: TemplateSaveRequest = {
        name: pipeline.name,
        description: pipeline.description,
        category: 'Pipeline',
        workflow_def: pipeline,
        schedule: pipeline.schedule,
      }
      await apiFetchAuthed('/v1/templates/automation', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(req),
      }, getAccessToken)
      pipelinesCtx.setPipelineFeedback(`Pipeline "${pipeline.name}" guardado como plantilla.`)
      chat.pushLocalExchange('', `✅ Pipeline "${pipeline.name}" guardado como plantilla pública.`)
      void fetchTemplates()
    } catch (err) {
      console.warn('[Dashboard] Error al guardar plantilla:', err)
      pipelinesCtx.setPipelineFeedback('Error al guardar como plantilla.')
      chat.pushLocalExchange('', '❌ Error al guardar como plantilla. Intenta de nuevo.')
    }
  }, [getAccessToken, chat, fetchTemplates, pipelinesCtx])

  useEffect(() => { void fetchTemplates() }, [fetchTemplates])
  useEffect(() => { void fetchPipelines() }, [fetchPipelines])

  // ─── C03: Plantillas populares para automatizaciones ──

  const fetchPopularTemplates = useCallback(async () => {
    setPopularTemplatesLoading(true)
    try {
      const data = await apiFetchAuthed<PopularAutomationTemplatesResponse>(
        '/v1/automations/templates/popular',
        { method: 'GET' },
        getAccessToken,
      )
      setPopularTemplates(data.templates || [])
    } catch (err) {
      console.warn('[Dashboard] No se pudieron cargar plantillas populares:', err)
      setPopularTemplates([])
    } finally {
      setPopularTemplatesLoading(false)
    }
  }, [getAccessToken])

  const handlePopularTemplateSelect = useCallback(
    (template: PopularAutomationTemplate) => {
      // Pre-llenar los campos del formulario de automatización
      draft.setDraftName(template.suggested_name)
      draft.setDraftInstruction(template.suggested_instruction)
      draft.setDraftSchedule(template.schedule)
      draft.setDraftDescription(template.description)
      draft.setDraftOutputType(
        template.suggested_output_type === 'file' ? 'file' :
        template.suggested_output_type === 'email' ? 'email' : 'notify',
      )
      if (
        template.suggested_integration === 'gmail' ||
        template.suggested_integration === 'google-calendar' ||
        template.suggested_integration === 'third-option'
      ) {
        draft.setDraftIntegration(template.suggested_integration)
      }
      toastSuccess(`Plantilla "${template.name}" aplicada. Revisa los campos antes de guardar.`)
    },
    [draft],
  )

  useEffect(() => {
    if (ui.drawerOpen && drawerMode === 'automation') {
      void fetchPopularTemplates()
    }
  }, [ui.drawerOpen, drawerMode, fetchPopularTemplates])

  // ─── Drawer ─────────────────────────────────────────────

  const openAutomationDrawer = useCallback(() => {
    setDrawerMode('automation')
    setEditingPipeline(null)
    setEditingAutomation(null)
    draft.resetDraft()
    ui.setDrawerOpen(true)
  }, [ui, draft.resetDraft])

  const handleAutomationEdit = useCallback((id: string) => {
    const found = state.automations.find((a) => a.id === id)
    if (!found) return
    setDrawerMode('automation')
    setEditingPipeline(null)
    setEditingAutomation(found)
    draft.setDraftIntegration(found.integrationId)
    draft.setDraftName(found.name)
    draft.setDraftInstruction(found.instruction)
    draft.setDraftOutputType(found.outputType ?? 'notify')
    draft.setDraftSchedule(found.schedule ?? 'manual')
    draft.setDraftDescription(found.description ?? '')
    ui.setDrawerOpen(true)
  }, [
    state.automations,
    draft.setDraftIntegration,
    draft.setDraftName,
    draft.setDraftInstruction,
    draft.setDraftOutputType,
    draft.setDraftSchedule,
    draft.setDraftDescription,
    ui,
  ])

  const openPipelineEditor = useCallback((pipeline?: PipelineDef | null) => {
    setDrawerMode('pipeline')
    setEditingPipeline(pipeline ?? null)
    setEditingAutomation(null)
    ui.setDrawerOpen(true)
  }, [ui])

  const handlePipelineEdit = useCallback((id: string) => {
    const found = pipelines.find((p) => p.id === id) ?? null
    openPipelineEditor(found)
  }, [pipelines, openPipelineEditor])

  const handlePipelineDelete = useCallback(async (id: string) => {
    const ok = await deletePipeline(id)
    if (ok) {
      pipelinesCtx.setPipelineFeedback('Pipeline eliminado.')
      if (pipelinesCtx.selectedPipelineId === id) {
        pipelinesCtx.setSelectedPipelineId(null)
        pipelinesCtx.setPipelineRunView(null)
      }
    } else {
      pipelinesCtx.setPipelineFeedback('No se pudo eliminar el pipeline.')
    }
  }, [deletePipeline, pipelinesCtx])

  const handlePipelineToggleActive = useCallback(async (id: string) => {
    const current = pipelines.find((p) => p.id === id)
    if (!current) return
    const updated = await updatePipeline(id, { active: !current.active })
    if (updated) {
      pipelinesCtx.setPipelineFeedback(
        updated.active
          ? `Pipeline "${updated.name}" activado.`
          : `Pipeline "${updated.name}" pausado.`,
      )
    }
  }, [pipelines, updatePipeline, pipelinesCtx])

  const handlePipelineSave = useCallback(async (
    name: string,
    description: string,
    naturalLanguage: string,
    schedule: string,
    steps?: import('@/features/dashboard/model/types').PipelineStep[],
  ) => {
    if (editingPipeline) {
      const updated = await updatePipeline(editingPipeline.id, {
        name: name.trim() || editingPipeline.name,
        description: description.trim(),
        schedule,
        ...(steps && steps.length > 0 ? { steps } : {}),
      })
      if (updated) {
        pipelinesCtx.setPipelineFeedback(`Pipeline "${updated.name}" actualizado.`)
        pipelinesCtx.setSelectedPipelineId(updated.id)
        chat.pushLocalExchange('', `✅ Pipeline "${updated.name}" actualizado.`)
        ui.setDrawerOpen(false)
        setEditingPipeline(null)
      } else {
        pipelinesCtx.setPipelineFeedback('No se pudo actualizar el pipeline.')
      }
      return
    }
    const created = await createPipeline({
      name: name.trim() || undefined,
      description: description.trim() || undefined,
      natural_language: steps && steps.length > 0 ? (naturalLanguage || undefined) : naturalLanguage,
      schedule,
      ...(steps && steps.length > 0 ? { steps } : {}),
    })
    if (created) {
      pipelinesCtx.setPipelineFeedback(`Pipeline "${created.name}" creado. Ya aparece en Pipelines.`)
      pipelinesCtx.setSelectedPipelineId(created.id)
      const stepStatuses: Record<string, PipelineStepRunStatus> = {}
      created.steps.forEach((step, i) => {
        stepStatuses[step.id] = i === 0 ? 'waiting' : 'idle'
      })
      pipelinesCtx.setPipelineRunView({
        pipelineId: created.id,
        runStatus: 'idle',
        stepStatuses,
      })
      chat.pushLocalExchange(
        '',
        `✅ Pipeline "${created.name}" creado con ${created.steps.length} pasos. Revisa el panel Previsualización y Estado.`,
      )
      ui.setDrawerOpen(false)
      setEditingPipeline(null)
    } else {
      pipelinesCtx.setPipelineFeedback('No se pudo crear el pipeline. Revisa la descripción e intenta de nuevo.')
    }
  }, [editingPipeline, updatePipeline, createPipeline, chat, ui, pipelinesCtx])

  // C05: DOT Store handlers
  const openStore = useCallback(() => {
    setStoreOpen(true)
  }, [])

  const handleSkillInstalled = useCallback((skill: StoreSkill) => {
    setInstalledSkillIds((prev) => new Set(prev).add(skill.id))
    toastSuccess(`"${skill.name}" agregada. Ya está disponible en Automatizaciones.`)
  }, [toastSuccess])

  const handleSkillUninstalled = useCallback((skillId: string) => {
    setInstalledSkillIds((prev) => {
      const next = new Set(prev)
      next.delete(skillId)
      return next
    })
    toastSuccess('Skill quitada.')
  }, [toastSuccess])

  // ─── Documentos y herramientas locales ──────────────────

  const processedAssistantActionsRef = useRef<Set<string>>(new Set())
  const processedLocalToolActionsRef = useRef<Set<string>>(new Set())
  const prevConvRef = useRef<string | undefined>(undefined)

  useEffect(() => {
    if (prevConvRef.current !== chat.conversationId) {
      prevConvRef.current = chat.conversationId
      processedLocalToolActionsRef.current = new Set()
      processedAssistantActionsRef.current = new Set()
    }
  }, [chat.conversationId])

  const subscriptionReminder = useMemo(
    () => buildSubscriptionReminder(subscriptionExpiryDate),
    [subscriptionExpiryDate],
  )

  const activeConversationTitle = useMemo(() => {
    if (!convs.activeId) return undefined
    const found = convs.conversations.find((c) => c.id === convs.activeId)
    return found?.title || undefined
  }, [convs.activeId, convs.conversations])

  const activeConversationChannel = useMemo(() => {
    if (!convs.activeId) return undefined
    const found = convs.conversations.find((c) => c.id === convs.activeId)
    return found?.channel || undefined
  }, [convs.activeId, convs.conversations])

  // B3: Limpiar badge al abrir la conversacion WhatsApp
  useEffect(() => {
    if (activeConversationChannel === 'whatsapp') {
      setWhatsappUnreadCount(0)
    }
  }, [activeConversationChannel])

  const cleanMessages = useMemo(
    () => chat.messages.map((m) => ({
      ...m,
      text: m.text.replace(/--MEMORY_UPDATE[\s\S]*?\}--/g, ''),
    })),
    [chat.messages],
  )

  // Sync doc preview desde mensajes del chat
  useEffect(() => {
    for (let i = chat.messages.length - 1; i >= 0; i -= 1) {
      const m = chat.messages[i]
      if (m.role !== 'assistant') continue
      const match =
        m.text.match(/Documento generado(?: automáticamente)?:\s*(.+?)\s+en\s+(.+)/i) ||
        m.text.match(/Conversación exportada en \w+:\s*(.+?)\s+en\s+(.+)/i) ||
        m.text.match(/Listo:\s*(.+?)\s+guardado en\s+(.+)/i)
      if (match) {
        const next = { filename: match[1].trim(), path: match[2].trim() }
        setDocPreview((prev) =>
          prev?.filename === next.filename && prev?.path === next.path ? prev : next,
        )
        break
      }
    }
  }, [chat.messages])

  // Suscripción vencida
  useEffect(() => {
    if (isSubscriptionExpired) {
      console.info('[Dashboard] Suscripción vencida detectada durante la sesión.')
    }
  }, [isSubscriptionExpired])

  // Notificación de renovación
  useEffect(() => {
    if (!subscriptionReminder || !subscriptionExpiryDate) return
    const notify = window.desktop?.systemNotify
    if (typeof notify !== 'function') return
    const today = new Date()
    const dayKey = `${today.getFullYear()}-${String(today.getMonth() + 1).padStart(2, '0')}-${String(
      today.getDate(),
    ).padStart(2, '0')}`
    const storageKey = 'dot.subscription.reminder.notified'
    const fingerprint = `${subscriptionExpiryDate}|${subscriptionReminder.daysRemaining}|${dayKey}`
    try {
      if (window.localStorage.getItem(storageKey) === fingerprint) return
    } catch {
      console.warn('[Dashboard] No se pudo leer fingerprint de recordatorio de localStorage')
    }
    void notify(subscriptionReminder.notificationTitle, subscriptionReminder.notificationBody).finally(() => {
      try {
        window.localStorage.setItem(storageKey, fingerprint)
      } catch {
        console.warn('[Dashboard] No se pudo guardar fingerprint de recordatorio en localStorage')
      }
    })
  }, [subscriptionReminder, subscriptionExpiryDate])

  // Cargar automatizaciones del perfil
  useEffect(() => {
    void (async () => {
      try {
        const profile = await apiFetchAuthed<UserProfileDto>(
          '/users/me/profile',
          { method: 'GET' },
          getAccessToken,
        )
        const raw = profile.saved_automations
        if (raw?.length) {
          state.setAutomations(
            raw.map((a) => ({
              id: a.id,
              name: a.name,
              integrationId: a.integration_id as IntegrationId,
              instruction: a.instruction,
              active: a.active ?? true,
              outputType: (a.output_type as AutomationOutputType | undefined) ?? undefined,
              schedule: a.schedule ?? undefined,
            })),
          )
          const storeIds = raw
            .map((a) => (a as { source_skill_id?: string | null }).source_skill_id)
            .filter((id): id is string => typeof id === 'string' && id.length > 0)
          if (storeIds.length > 0) {
            setInstalledSkillIds(new Set(storeIds))
          }
        }
        const pending = normalizePendingAutomation(profile.pending_automation_results ?? null)
        if (pending.has_new) {
          state.setHasPendingResults(true)
          state.setPendingAutomation(pending)
        }
        const profileRecord = profile as UserProfileDto & {
          reasoning_enabled?: boolean
          reasoning_level?: ReasoningLevel
        }
        if (typeof profileRecord.reasoning_enabled === 'boolean') {
          setProfileReasoningEnabled(profileRecord.reasoning_enabled)
        }
        if (
          profileRecord.reasoning_level === 'low'
          || profileRecord.reasoning_level === 'medium'
          || profileRecord.reasoning_level === 'high'
          || profileRecord.reasoning_level === 'auto'
        ) {
          setProfileReasoningLevel(profileRecord.reasoning_level)
        }
      } catch (err) {
        console.warn('[Dashboard] No se pudo cargar perfil de usuario:', err)
      }
    })()
  }, [getAccessToken])

  // Procesar acciones de documentos desde el asistente
  useEffect(() => {
    for (const message of chat.messages) {
      if (message.role !== 'assistant' || message.status !== 'sent') continue
      if (processedAssistantActionsRef.current.has(message.id)) continue
      processedAssistantActionsRef.current.add(message.id)
      const action = parseAssistantDocumentAction(message.text)
      if (!action) continue
      void docGen
        .generate({
          document_type: action.documentType as DocumentType,
          title: action.title,
          content: action.content,
        })
        .then((res) => {
          setDocPreview({ filename: res.filename, path: res.path })
          chat.pushLocalExchange(
            '',
            `Documento generado automáticamente: ${res.filename} en ${res.path}`,
          )
        })
        .catch((err) => {
          console.warn('[Dashboard] Error al generar documento automático:', err)
          chat.pushLocalExchange(
            '',
            'Detecté una instrucción de documento, pero no pude generarlo. Revisa backend o permisos.',
          )
        })
    }
  }, [chat, docGen])

  // Fallback: local_tool JSON → ejecutar en Electron (IPC)
  useEffect(() => {
    if (!window.desktop?.localTools) return
    for (const message of chat.messages) {
      if (message.role !== 'assistant' || message.status !== 'sent') continue
      if (processedLocalToolActionsRef.current.has(message.id)) continue
      const action = parseLocalToolAction(message.text)
      if (!action) continue
      processedLocalToolActionsRef.current.add(message.id)
      chat.updateMessage(message.id, {
        text: '⏳ DOT está guardando el archivo en tu PC…',
      })
      void (async () => {
        try {
          let result: {
            ok: boolean
            content?: string
            error?: string
            path?: string
            bytes?: number
            files?: Array<{ name: string; isDirectory: boolean }>
          }
          let op = action.operation
          let path = action.path
          let url = action.url
          if (op === 'writeFile' && isBinaryLocalPath(path)) {
            const fromUser = [...chat.messages]
              .reverse()
              .find((m) => m.role === 'user' && extractHttpUrl(m.text))
            url = url || extractHttpUrl(fromUser?.text || '') || extractHttpUrl(message.text) || undefined
            if (url) {
              op = 'downloadUrl'
              if (!path || !path.includes('.')) {
                path = `~/Desktop/${url.split('/').pop()?.split('?')[0] || 'download.bin'}`
              }
            }
          }
          switch (op) {
            case 'readFile':
              result = await window.desktop!.localTools!.readFile(path)
              break
            case 'writeFile':
              result = await window.desktop!.localTools!.writeFile(path, action.content ?? '')
              break
            case 'downloadUrl': {
              if (!url) {
                result = { ok: false, error: 'Falta la URL para descargar el archivo.' }
                break
              }
              if (!window.desktop!.localTools!.downloadUrlToDesktop) {
                result = { ok: false, error: 'Reinicia DOT para habilitar descargas (IPC nuevo).' }
                break
              }
              result = await window.desktop!.localTools!.downloadUrlToDesktop(url, path || '')
              break
            }
            case 'listFiles':
              result = await window.desktop!.localTools!.listFiles(path)
              break
            case 'deleteFile':
              result = await window.desktop!.localTools!.deleteFile(path)
              break
            default:
              result = { ok: false, error: 'Operación desconocida' }
          }
          const formatted = formatLocalToolResult(op, path, result)
          const withPath =
            result.ok && result.path
              ? `${formatted}\n\nRuta: ${result.path}`
              : formatted
          chat.updateMessage(message.id, { text: withPath })
        } catch (err) {
          const errorMsg = translateError(err, 'No pude completar la acción en tu PC. Intenta de nuevo.')
          console.warn('[Dashboard] Error ejecutando local-tool:', err)
          chat.updateMessage(message.id, {
            text: `❌ ${errorMsg}`,
          })
        }
      })()
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [chat.conversationId, chat.messages, processedLocalToolActionsRef])

  // Toast de sincronización de perfil
  useEffect(() => {
    if (profileSyncWarning) {
      setShowSyncToast(true)
      const timer = setTimeout(() => setShowSyncToast(false), 8000)
      return () => clearTimeout(timer)
    }
    setShowSyncToast(false)
  }, [profileSyncWarning])

  // ─── Automatizaciones ───────────────────────────────────

  useReminderPolling({ getAccessToken })

  const {
    reminders: pendingReminders,
    loading: remindersLoading,
    error: remindersError,
    dismiss: dismissReminder,
    snooze: snoozeReminder,
  } = useRemindersPanel({ getAccessToken, pollIntervalMs: 30_000 })

  const {
    linked: agendaLinked,
    events: agendaEvents,
    loading: agendaLoading,
    error: agendaError,
    message: agendaMessage,
  } = useAgendaSidebar({ getAccessToken, pollIntervalMs: 120_000 })

  // Gap #3 — Poll de fallos de automatizaciones
  useEffect(() => {
    const check = () => {
      void (async () => {
        try {
          const token = await getAccessToken()
          if (!token) return
          const data = await apiFetchAuthed<{ failures: Array<{id: string; auto_name: string; error: string; failed_at: string}>; total: number }>(
            '/v1/automations/failures',
            { method: 'GET' },
            getAccessToken,
          )
          setAutomationFailures(data.failures || [])
        } catch { /* silencio */ }
      })()
    }
    check()
    const interval = setInterval(check, 120000) // cada 2 min
    return () => clearInterval(interval)
  }, [getAccessToken])

  // Gap #3 — Acknowledger de fallos
  const acknowledgeFailures = useCallback(() => {
    void (async () => {
      for (const f of automationFailures) {
        try {
          await apiFetchAuthed(`/v1/automations/failures/${f.id}/acknowledge`, { method: 'POST' }, getAccessToken)
        } catch { /* silencio */ }
      }
      setAutomationFailures([])
    })()
  }, [automationFailures, getAccessToken])

  const handlePendingResults = useCallback((pending: AutomationPendingResponse) => {
    state.setHasPendingResults(true)
    state.setPendingAutomation(pending)
  }, [])

  const handleNoPendingResults = useCallback(() => {
    state.setHasPendingResults(false)
    state.setPendingAutomation(null)
  }, [])

  useAutomationPolling({
    getAccessToken,
    onPendingResults: handlePendingResults,
    onNoPendingResults: handleNoPendingResults,
  })

  useMorningBriefingBoot({ getAccessToken })

  const handleToggleActive = useCallback(
    (id: string) => {
      state.setAutomations((prev) => {
        const updated = prev.map((a) =>
          a.id === id ? { ...a, active: !a.active } : a,
        )
        apiFetchAuthed('/users/me/profile', {
          method: 'PATCH',
          body: JSON.stringify({
            saved_automations: updated.map((a) => ({
              id: a.id,
              name: a.name,
              integration_id: a.integrationId,
              instruction: a.instruction,
              active: a.active,
              output_type: a.outputType ?? null,
              schedule: a.schedule ?? null,
              description: a.description ?? null,
            })),
          }),
        }, getAccessToken).catch((err) => {
          console.warn('[Dashboard] Error al actualizar toggle de automatización en el servidor:', err)
        })
        return updated
      })
    },
    [getAccessToken],
  )

  const handleExecuteNow = useCallback(
    (id: string) => {
      const auto = state.automations.find((a) => a.id === id)
      if (!auto) return
      chat.pushLocalExchange('', `⏳ Ejecutando "${auto.name}"…`)
      void apiFetchAuthed<{ success: boolean; result: string; executed_at: string }>(
        `/v1/automations/${id}/execute`,
        { method: 'POST' },
        getAccessToken,
      )
        .then((res) => {
          if (res.success) {
            chat.pushLocalExchange('', `✅ "${auto.name}" ejecutada:\n\n${res.result}`)
          } else {
            chat.pushLocalExchange('', `❌ Error al ejecutar "${auto.name}".`)
          }
        })
        .catch((err) => {
          console.warn('[Dashboard] Error al ejecutar automatización:', err)
          chat.pushLocalExchange('', `❌ Error al ejecutar "${auto.name}". Revisa tu conexión o el backend.`)
        })
    },
    [state.automations, chat, getAccessToken],
  )

  const handleViewResults = useCallback(() => {
    const autoId = state.pendingAutomation?.last_auto_id?.trim()
    const autoName = state.pendingAutomation?.last_auto_name?.trim()
    const preview = state.pendingAutomation?.last_result_preview?.trim()
    const isBriefing = autoId === MORNING_BRIEFING_AUTO_ID

    if (autoName || preview) {
      const header = isBriefing
        ? `☀️ ${autoName || 'Tu día en 30s'}`
        : `${autoName ? `📋 Resultado de "${autoName}"` : '📋 Resultado pendiente de automatización'}`
      chat.pushLocalExchange('', `${header}\n\n${preview || 'Hay resultados nuevos listos para revisar.'}`)
    } else {
      chat.pushLocalExchange('', '📋 Revisando resultados pendientes de automatizaciones…')
    }
    state.setHasPendingResults(false)
    state.setPendingAutomation(null)
    void apiFetchAuthed('/v1/automations/results/ack', { method: 'POST' }, getAccessToken).catch((err) => {
      console.warn('[Dashboard] No se pudo confirmar lectura de resultados:', err)
    })
  }, [chat, getAccessToken, state.pendingAutomation])

  const handleDismissResults = useCallback(() => {
    state.setHasPendingResults(false)
    state.setPendingAutomation(null)
  }, [])

  useEffect(() => {
    const subscribe = window.desktop?.onAutomationNotificationClick
    if (typeof subscribe !== 'function') return
    return subscribe(() => { handleViewResults() })
  }, [handleViewResults])

  const handleNewChat = useCallback(() => {
    if (chat.isSending) return
    chat.clear()
    void convs.createConversation().then((id) => { convs.selectConversation(id) })
  }, [chat, convs])

  const handleSelectConversation = useCallback(
    async (id: string) => {
      if (chat.isSending || convs.activeId === id) return
      await convs.selectConversation(id)
    },
    [chat.isSending, convs],
  )

  // ─── Selección de conversación al cargar ────────────────

  const LAST_CONVERSATION_KEY = 'dot.lastConversationId'
  const hasSelectedDefaultRef = useRef(false)
  useEffect(() => {
    if (convs.isLoading || hasSelectedDefaultRef.current) return
    if (convs.conversations.length > 0) {
      hasSelectedDefaultRef.current = true
      let savedId: string | null = null
      try { savedId = window.localStorage.getItem(LAST_CONVERSATION_KEY) } catch { /* no disponible */ }
      const found = savedId ? convs.conversations.find((c) => c.id === savedId) : null
      if (found) {
        convs.selectConversation(found.id)
      } else {
        const mostRecent = convs.conversations.reduce((prev, curr) =>
          new Date(prev.updated_at) > new Date(curr.updated_at) ? prev : curr,
        )
        convs.selectConversation(mostRecent.id)
      }
    }
  }, [convs.isLoading, convs.conversations, convs])

  useEffect(() => {
    if (convs.activeId) {
      if (chat.conversationId === convs.activeId && chat.messages.length > 0) {
        return
      }
      void (async () => {
        const loaded = await loadConversationRef.current(convs.activeId!)
        if (loaded) {
          for (const m of loaded) {
            if (m.role === 'assistant' && parseLocalToolAction(m.text)) {
              processedLocalToolActionsRef.current.add(m.id)
            }
          }
        }
      })()
    } else {
      chat.clear()
      if (convs.conversations.length > 0) {
        const mostRecent = convs.conversations.reduce((prev, curr) =>
          new Date(prev.updated_at) > new Date(curr.updated_at) ? prev : curr,
        )
        convs.selectConversation(mostRecent.id)
      }
    }
  }, [convs.activeId, chat.conversationId, chat.messages.length])

  // ─── Export ─────────────────────────────────────────────

  const { handleExportConversation } = useDocumentExport({
    chat,
    docGen,
    userDisplayName,
    onExportStart: (format) => ui.setChatExportFormat(format),
    onExportEnd: () => ui.setChatExportFormat(null),
    onExported: (file) => setDocPreview(file),
  })

  // ─── Atajos de teclado ──────────────────────────────────

  const dashboardShortcuts = useMemo(() => [
    { key: 'n', ctrl: true, handler: handleNewChat, description: 'Nuevo chat' },
    {
      key: 'Enter', ctrl: true,
      handler: () => { document.querySelector<HTMLTextAreaElement>('.dot-chat__textarea')?.focus() },
      description: 'Enviar mensaje (enfocar campo de texto)',
    },
    {
      key: 'l', ctrl: true,
      handler: () => { document.querySelector<HTMLTextAreaElement>('.dot-chat__textarea')?.focus() },
      description: 'Enfocar campo de texto',
    },
    {
      key: 'Escape',
      handler: () => {
        if (ui.drawerOpen) { closeDrawer() }
        else if (ui.docCreatorOpen) { ui.setDocCreatorOpen(false) }
      },
      description: 'Cerrar modales/paneles',
    },
  ], [handleNewChat, ui.drawerOpen, ui.docCreatorOpen])

  useKeyboardShortcuts(dashboardShortcuts)

  // ─── Animación del drawer ───────────────────────────────

  const drawerTransition = reduceMotion
    ? { duration: 0.12 }
    : { type: 'spring' as const, stiffness: 420, damping: 38 }

  function closeDrawer() {
    ui.setDrawerOpen(false)
    setDrawerMode('automation')
    setEditingPipeline(null)
    setEditingAutomation(null)
  }

  function saveAutomation() {
    const name = draft.draftName.trim()
    const instruction = draft.draftInstruction.trim()
    const description = draft.draftDescription.trim() || undefined
    if (!name || !instruction) return

    const next: SavedAutomation[] = editingAutomation
      ? state.automations.map((a) =>
          a.id === editingAutomation.id
            ? {
                ...a,
                name,
                integrationId: draft.draftIntegration,
                instruction,
                outputType: draft.draftOutputType,
                schedule: draft.draftSchedule,
                description,
              }
            : a,
        )
      : [
          ...state.automations,
          {
            id: crypto.randomUUID(),
            name,
            integrationId: draft.draftIntegration,
            instruction,
            active: true,
            outputType: draft.draftOutputType,
            schedule: draft.draftSchedule,
            description,
          },
        ]

    state.setAutomations(next)
    apiFetchAuthed('/users/me/profile', {
      method: 'PATCH',
      body: JSON.stringify({
        saved_automations: next.map((a) => ({
          id: a.id,
          name: a.name,
          integration_id: a.integrationId,
          instruction: a.instruction,
          active: a.active,
          output_type: a.outputType ?? null,
          schedule: a.schedule ?? null,
          description: a.description ?? null,
        })),
      }),
    }, getAccessToken).catch((err) => {
      console.warn('[Dashboard] Error al guardar automatización en el servidor:', err)
    })
    draft.resetDraft()
    setEditingAutomation(null)
    ui.setDrawerOpen(false)
  }

  // ══════════════════════════════════════════════════════════
  //  JSX
  // ══════════════════════════════════════════════════════════

  return (
    <div className="main-dashboard">
      {!isOnline && (
        <div className="main-dashboard__offline-banner" role="alert">
          <span className="main-dashboard__offline-banner-icon">&#9889;</span>
          <span>Sin conexión a internet. Se reconectará automáticamente cuando vuelva la señal.</span>
        </div>
      )}
      {showSyncToast && profileSyncWarning ? (
        <div className="main-dashboard__sync-toast" role="alert">
          <span className="main-dashboard__sync-toast-icon">⚠️</span>
          <span className="main-dashboard__sync-toast-text">{profileSyncWarning}</span>
          <button type="button" className="main-dashboard__sync-toast-close" onClick={() => setShowSyncToast(false)} aria-label="Cerrar">×</button>
        </div>
      ) : null}

      {pipelinesCtx.pipelineFeedback ? (
        <div className="main-dashboard__sync-toast" role="status">
          <span className="main-dashboard__sync-toast-text">{pipelinesCtx.pipelineFeedback}</span>
          <button type="button" className="main-dashboard__sync-toast-close" onClick={() => pipelinesCtx.setPipelineFeedback(null)} aria-label="Cerrar">×</button>
        </div>
      ) : null}

      <WorkspaceHeader
        selectedAgent={state.agent}
        onAgentChange={state.setAgent}
        userDisplayName={userDisplayName}
        channelLabel={channelLabel}
        profileSyncWarning={profileSyncWarning}
        onLogout={logout}
        whatsappStatus={state.whatsappStatus}
        whatsappRefreshing={whatsappRefreshing}
        onRefreshWhatsapp={refreshWhatsappStatus}
        googleConnected={googleConnected}
        onRevokeGoogle={handleRevokeGoogle}
        wsConnected={wsConnected}
        theme={theme}
        onToggleTheme={toggleTheme}
        onOpenSettings={() => setSettingsOpen(true)}
        usageSummary={usageSummary}
        usageLoading={usageLoading}
      />

      <div className="main-dashboard__left-panel">
        <ConversationList
          conversations={showingArchived ? archivedConversations : convs.conversations}
          activeId={convs.activeId}
          isLoading={convs.isLoading}
          isSearching={showingArchived ? archivedSearching : convs.isSearching}
          searchSnippets={showingArchived ? archivedSearchSnippets : convs.searchSnippets}
          onSearchChange={handleConversationSearch}
          onSelect={handleSelectConversation}
          onNew={handleNewChat}
          onRename={convs.renameConversation}
          onDelete={convs.deleteConversation}
          onUnarchive={async (id: string) => {
            const token = await getAccessToken()
            const { unarchiveConversation } = await import('@/lib/chat/client')
            await unarchiveConversation(id, token)
            setArchivedConversations((prev) => prev.filter((c) => c.id !== id))
            void convs.refresh()
          }}
          onToggleArchived={() => {
            setShowingArchived((prev) => !prev)
            if (!showingArchived) {
              void (async () => {
                const token = await getAccessToken()
                const { getArchivedConversations } = await import('@/lib/chat/client')
                try {
                  const archived = await getArchivedConversations(token)
                  setArchivedConversations(archived)
                  setArchivedSearchSnippets({})
                } catch {
                  // ignorar
                }
              })()
            } else {
              setArchivedSearchSnippets({})
              void convs.refresh()
            }
          }}
          showingArchived={showingArchived}
          whatsappUnreadCount={whatsappUnreadCount}
        />
        <AutomationSidebar
          automations={state.automations}
          onOpenDrawer={openAutomationDrawer}
          onOpenDocumentCreator={() => ui.setDocCreatorOpen(true)}
          onOpenStore={openStore}
          onToggleActive={handleToggleActive}
          onExecuteNow={handleExecuteNow}
          onEdit={handleAutomationEdit}
          hasPendingResults={state.hasPendingResults}
          onViewResults={handleViewResults}
          pipelines={pipelines}
          selectedPipelineId={pipelinesCtx.selectedPipelineId}
          onSelectPipeline={pipelinesCtx.handleSelectPipeline}
          onOpenPipelineEditor={() => openPipelineEditor(null)}
          onPipelineExecute={pipelinesCtx.handlePipelineExecute}
          onPipelineToggleActive={handlePipelineToggleActive}
          onPipelineEdit={handlePipelineEdit}
          onPipelineDelete={handlePipelineDelete}
          onPipelineSaveAsTemplate={handleSavePipelineAsTemplate}
          templates={templates}
          onCloneTemplate={handleCloneTemplate}
          cloningTemplateId={cloningTemplateId}
          loadingTemplates={templatesLoading || pipelinesLoading}
          focusPipelinesNonce={focusPipelinesNonce}
        />
      </div>

      <main className="main-dashboard__main">
        <DashboardBanners
          planLabel={state.planLabel}
          subscriptionReminder={subscriptionReminder}
          profileSyncWarning={profileSyncWarning}
          whatsappStatus={state.whatsappStatus}
          channelLabel={channelLabel}
          onOpenIntegrations={() => openIntegrations('whatsapp')}
        />
        {session?.recoveryKey ? (
          <SaveRecoveryKeyBanner recoveryKey={session.recoveryKey} />
        ) : null}
        <DashboardNotifications
          hasPendingResults={state.hasPendingResults}
          pendingAutomation={state.pendingAutomation}
          onViewResults={handleViewResults}
          onDismissResults={handleDismissResults}
        />
        {/* Gap #3 — Banner de fallos de automatizaciones */}
        {automationFailures.length > 0 && (
          <div className="automation-failure-banner" role="alert">
            <span>⚠️ {automationFailures.length} automatización(es) fallaron.</span>
            <button type="button" onClick={acknowledgeFailures}>
              Entendido
            </button>
          </div>
        )}
        <FeatureErrorBoundary featureName="Chat" fallbackMessage="Error al cargar el chat. Reintenta o crea un nuevo chat.">
          <DotChatPanel
            messages={cleanMessages}
            isSending={chat.isSending}
            canExportConversation={chat.messages.length > 0}
            isExportingConversation={docGen.isGenerating}
            exportingFormat={ui.chatExportFormat}
            lastError={chat.lastError}
            conversationId={convs.activeId}
            conversationTitle={activeConversationTitle}
            conversationChannel={activeConversationChannel}
            onRenameConversation={async (title: string) => { await convs.renameConversation(convs.activeId!, title) }}
            onNewChat={handleNewChat}
            getAccessToken={getAccessToken}
            onClearError={chat.clearError}
            onSend={handleSendWithWhatsAppRedirect}
            onSendImage={chat.sendVisionImage}
            onGenerateImage={chat.sendImageGeneration}
            onExportConversation={handleExportConversation}
            whatsappMode={whatsappMode}
            onToggleWhatsappMode={handleToggleWhatsappMode}
            whatsappModeAvailable={state.whatsappStatus === 'linked'}
            imageGenEnabled={imageGenEnabled}
            voiceTtsAvailable={voiceTtsAvailable}
            voiceSttAvailable={!voiceStatusLoaded || voiceSttAvailable}
            onOpenAppSettings={openSettings}
            onOpenGoogleIntegrations={() => openIntegrations('google')}
            onTranslateText={translateText}
            onSummarizeText={summarizeText}
            ttsLoadingMessageId={ttsPlayback.loadingMessageId}
            onTextToSpeech={handleTextToSpeech}
            dotSpeaksEnabled={dotSpeaks.enabled}
            onToggleDotSpeaks={handleToggleDotSpeaks}
            ttsPlaying={ttsPlayback.isPlaying}
            talkMode={talk.talkMode}
            onToggleTalkMode={talk.toggleTalkMode}
            wakeWordState={talk.wakeWordState}
            onStartWakeWord={talk.startWakeWord}
            onStopWakeWord={talk.stopWakeWord}
            reasoningEnabled={reasoningMode.enabled}
            reasoningLevel={reasoningMode.level}
            onReasoningEnabledChange={reasoningMode.setEnabled}
            onReasoningLevelChange={reasoningMode.setLevel}
            usageBlocked={Boolean(usageSummary?.blocked)}
            usageBlockedMessage={USAGE_LIMIT_BLOCKED_MESSAGE}
          />
        </FeatureErrorBoundary>

        {/* Overlay de bloqueo IA al 100% */}
        {usageSummary?.blocked && !usageBlockDismissed && (
          <div className="usage-block-overlay" role="alertdialog" aria-modal="true" aria-label="Límite de IA alcanzado">
            <div className="usage-block-overlay__card">
              <div className="usage-block-overlay__icon">&#9888;</div>
              <UsageRechargeGuide variant="overlay" />
              <button
                type="button"
                className="usage-block-overlay__btn"
                onClick={() => setUsageBlockDismissed(true)}
              >
                Entendido
              </button>
            </div>
          </div>
        )}
      </main>

      <StatusSidebar
        selectedPipeline={pipelinesCtx.selectedPipeline}
        activeView={pipelinesCtx.pipelineRunView}
        docPreview={docPreview}
        whatsappStatus={state.whatsappStatus}
        whatsappPhone={whatsappPhone}
        googleConnected={googleConnected}
        pipelineCount={pipelines.length}
        usageSummary={usageSummary}
        usageLoading={usageLoading}
        usageError={usageError}
        usageDailyHistory={usageDailyHistory}
        onSelectPipelineHint={() => setFocusPipelinesNonce((n) => n + 1)}
        onCreatePipelineHint={() => {
          setFocusPipelinesNonce((n) => n + 1)
          openPipelineEditor(null)
        }}
        onOpenIntegrations={openIntegrations}
        reminders={pendingReminders}
        remindersLoading={remindersLoading}
        remindersError={remindersError}
        onDismissReminder={dismissReminder}
        onSnoozeReminder={snoozeReminder}
        agendaLinked={agendaLinked}
        agendaEvents={agendaEvents}
        agendaLoading={agendaLoading}
        agendaError={agendaError}
        agendaMessage={agendaMessage}
      />

      <IntegrationsSessionsDrawer
        open={integrationsOpen}
        focus={integrationsFocus}
        onClose={closeIntegrations}
        onOpenSettings={openSettings}
        whatsappStatus={state.whatsappStatus}
        whatsappPhone={whatsappPhone}
        googleConnected={googleConnected}
        getAccessToken={getAccessToken}
        onWhatsAppChanged={refreshWhatsappStatus}
        onGoogleChanged={refreshGoogleStatus}
      />

      <AnimatePresence>
        {ui.drawerOpen ? (
          <>
            <motion.button
              key="auto-backdrop"
              type="button"
              className="main-dashboard__drawer-backdrop"
              aria-label="Cerrar panel"
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0 }}
              transition={{ duration: reduceMotion ? 0.08 : 0.22 }}
              onClick={closeDrawer}
            />
            <motion.aside
              key="drawer"
              className={`main-dashboard__drawer${drawerMode === 'pipeline' ? ' main-dashboard__drawer--wide' : ''}`}
              role="dialog"
              aria-modal="true"
              aria-labelledby="automation-drawer-title"
              initial={{ x: reduceMotion ? 0 : '100%' }}
              animate={{ x: 0 }}
              exit={{ x: reduceMotion ? 0 : '100%' }}
              transition={drawerTransition}
            >
              <div className="main-dashboard__drawer-head">
                <h2 id="automation-drawer-title" className="main-dashboard__drawer-title">
                  {drawerMode === 'pipeline'
                    ? (editingPipeline ? 'Editar pipeline' : 'Nuevo pipeline multi-paso')
                    : (editingAutomation ? 'Editar automatización' : 'Nueva automatización')}
                </h2>
                <button type="button" className="main-dashboard__drawer-close" onClick={closeDrawer}>×</button>
              </div>
              <FeatureErrorBoundary featureName="Automatizaciones" fallbackMessage="Error en el formulario de automatizacion. Reintenta o cierra el panel.">
                {drawerMode === 'pipeline' ? (
                  <PipelineEditor
                    key={editingPipeline?.id ?? 'new-pipeline'}
                    pipeline={editingPipeline}
                    onSave={handlePipelineSave}
                    onCancel={closeDrawer}
                    saving={pipelinesLoading}
                  />
                ) : (
                  <AutomationDrawerFields
                    key={editingAutomation?.id ?? 'new-automation'}
                    draftIntegration={draft.draftIntegration}
                    onDraftIntegration={draft.setDraftIntegration}
                    draftName={draft.draftName}
                    onDraftName={draft.setDraftName}
                    draftInstruction={draft.draftInstruction}
                    onDraftInstruction={draft.setDraftInstruction}
                    draftOutputType={draft.draftOutputType}
                    onDraftOutputType={draft.setDraftOutputType}
                    draftSchedule={draft.draftSchedule}
                    onDraftSchedule={draft.setDraftSchedule}
                    draftDescription={draft.draftDescription}
                    onDraftDescription={draft.setDraftDescription}
                    onSave={saveAutomation}
                    saveDisabled={draft.draftName.trim().length === 0 || draft.draftInstruction.trim().length === 0}
                    saveLabel={editingAutomation ? 'Guardar cambios' : 'Guardar'}
                    templates={popularTemplates}
                    templatesLoading={popularTemplatesLoading}
                    onTemplateSelect={handlePopularTemplateSelect}
                  />
                )}
              </FeatureErrorBoundary>
            </motion.aside>
          </>
        ) : null}
      </AnimatePresence>

      <DocumentCreatorModal
        open={ui.docCreatorOpen}
        onClose={() => ui.setDocCreatorOpen(false)}
        getAccessToken={getAccessToken}
      />

      <KeyboardShortcutsHelp shortcuts={dashboardShortcuts} />

      {/* C05: DOT Store */}
      <StorePanel
        open={storeOpen}
        onClose={() => setStoreOpen(false)}
        getAccessToken={getAccessToken}
        installedSkillIds={installedSkillIds}
        onInstalled={handleSkillInstalled}
        onUninstalled={handleSkillUninstalled}
      />

      {/* Settings */}
      <SettingsPanel
        open={settingsOpen}
        onClose={() => setSettingsOpen(false)}
        userDisplayName={userDisplayName}
        channelLabel={channelLabel}
        onLogout={logout}
        getAccessToken={getAccessToken}
        dotSpeaksEnabled={dotSpeaks.enabled}
        onDotSpeaksChange={handleDotSpeaksChange}
        voiceSttAvailable={voiceSttAvailable}
        voiceStatusLoaded={voiceStatusLoaded}
        voiceTtsAvailable={voiceTtsAvailable}
      />
    </div>
  )
}

function normalizePendingAutomation(raw: Partial<AutomationPendingResponse> | null | undefined): AutomationPendingResponse {
  return {
    has_new: Boolean(raw?.has_new),
    last_auto_id: raw?.last_auto_id?.trim() || null,
    last_auto_name: raw?.last_auto_name?.trim() || null,
    last_executed_at: raw?.last_executed_at?.trim() || null,
    last_result_preview: raw?.last_result_preview?.trim() || null,
  }
}
