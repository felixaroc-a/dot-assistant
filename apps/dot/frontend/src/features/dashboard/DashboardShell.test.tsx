import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { cleanup, render, screen } from '@testing-library/react'

import { DashboardShell } from './DashboardShell'
import type { DashboardShellProps } from './DashboardShell'

vi.mock('@/features/auth', () => ({
  useAuth: () => ({
    getAccessToken: vi.fn().mockResolvedValue('mock-token'),
    logout: vi.fn(),
    isSubscriptionExpired: false,
    subscriptionExpiryDate: null,
    session: {},
  }),
}))

vi.mock('@/features/dashboard/hooks', () => ({
  useDashboardState: () => ({
    agent: 'dot',
    setAgent: vi.fn(),
    automations: [],
    setAutomations: vi.fn(),
    hasAutomations: true,
    planLabel: 'Mensual',
    whatsappStatus: 'disconnected',
    setWhatsappStatus: vi.fn(),
    hasPendingResults: false,
    pendingAutomation: null,
    setHasPendingResults: vi.fn(),
    setPendingAutomation: vi.fn(),
  }),
  useAutomationDraft: () => ({
    draftIntegration: 'none',
    setDraftIntegration: vi.fn(),
    draftName: '',
    setDraftName: vi.fn(),
    draftInstruction: '',
    setDraftInstruction: vi.fn(),
    draftOutputType: 'notify',
    setDraftOutputType: vi.fn(),
    draftSchedule: 'manual',
    setDraftSchedule: vi.fn(),
    draftDescription: '',
    setDraftDescription: vi.fn(),
    resetDraft: vi.fn(),
  }),
  useDashboardUI: () => ({
    drawerOpen: false,
    setDrawerOpen: vi.fn(),
    docCreatorOpen: false,
    setDocCreatorOpen: vi.fn(),
    chatExportFormat: null,
    setChatExportFormat: vi.fn(),
  }),
  useAutomationPolling: vi.fn(),
  useReminderPolling: vi.fn(),
  useRemindersPanel: () => ({
    reminders: [],
    loading: false,
    error: null,
    dismiss: vi.fn(),
    snooze: vi.fn(),
    refresh: vi.fn(),
  }),
  useAgendaSidebar: () => ({
    linked: false,
    events: [],
    message: null,
    loading: false,
    error: null,
    refresh: vi.fn(),
  }),
  useMorningBriefingBoot: vi.fn(),
  useSlashCommands: () => ({
    handleSend: vi.fn(),
    translateText: vi.fn(),
    summarizeText: vi.fn(),
  }),
  useDocumentExport: () => ({
    handleExportConversation: vi.fn(),
  }),
  useConversations: () => ({
    conversations: [],
    activeId: null,
    isLoading: false,
    isSearching: false,
    searchQuery: '',
    searchSnippets: {},
    selectConversation: vi.fn(),
    createConversation: vi.fn().mockResolvedValue('conv-1'),
    renameConversation: vi.fn(),
    deleteConversation: vi.fn(),
    refresh: vi.fn().mockResolvedValue(undefined),
    searchConversations: vi.fn().mockResolvedValue(undefined),
  }),
  useUsageSummary: () => ({
    summary: null,
    loading: false,
    refresh: vi.fn(),
    refreshNow: vi.fn(),
  }),
  useDashboardWhatsApp: () => ({
    whatsappRefreshing: false,
    refreshWhatsappStatus: vi.fn(),
  }),
  useDashboardGoogle: () => ({
    googleConnected: false,
    googleRevoking: false,
    handleRevokeGoogle: vi.fn(),
  }),
  useDashboardPipelines: () => ({
    pipelineFeedback: null,
    setPipelineFeedback: vi.fn(),
    pipelineRunView: null,
    setPipelineRunView: vi.fn(),
    selectedPipelineId: null,
    setSelectedPipelineId: vi.fn(),
    selectedPipeline: null,
    buildStepStatuses: vi.fn().mockReturnValue({}),
    handlePipelineExecute: vi.fn(),
    handleSelectPipeline: vi.fn(),
  }),
}))

vi.mock('@/features/dashboard/hooks/usePipelines', () => ({
  usePipelines: () => ({
    pipelines: [],
    loading: false,
    fetchPipelines: vi.fn().mockResolvedValue(undefined),
    createPipeline: vi.fn().mockResolvedValue(null),
    updatePipeline: vi.fn().mockResolvedValue(null),
    deletePipeline: vi.fn().mockResolvedValue(false),
    executePipeline: vi.fn().mockResolvedValue(null),
  }),
}))

vi.mock('@/lib/chat/useChat', () => ({
  useChat: () => ({
    messages: [],
    isSending: false,
    lastError: null,
    clearError: vi.fn(),
    clear: vi.fn(),
    pushLocalExchange: vi.fn(),
    loadConversation: vi.fn().mockResolvedValue([]),
    conversationId: undefined,
  }),
}))

vi.mock('@/lib/documents/useDocumentGenerator', () => ({
  useDocumentGenerator: () => ({
    isGenerating: false,
    generate: vi.fn().mockResolvedValue({ filename: 'test.docx', path: '/tmp' }),
  }),
}))

vi.mock('@/lib/api/client', () => ({
  apiFetchAuthed: vi.fn().mockResolvedValue({ saved_automations: [] }),
}))

vi.mock('@/lib/api/whatsapp', () => ({
  getWhatsAppChannelStatus: vi.fn().mockResolvedValue('disconnected'),
  toLinkStatus: vi.fn().mockReturnValue('disconnected'),
}))

vi.mock('@/lib/websocket-client', () => ({
  wsClient: {
    onStatusChange: vi.fn(() => vi.fn()),
    on: vi.fn(() => vi.fn()),
  },
}))

vi.mock('framer-motion', () => ({
  motion: {
    button: 'button',
    aside: 'aside',
    div: 'div',
    li: 'li',
  },
  AnimatePresence: ({ children }: { children: React.ReactNode }) => <>{children}</>,
  useReducedMotion: () => false,
}))

vi.mock('@/shared/theme-context', () => ({
  useTheme: () => ({ theme: 'dark', toggleTheme: vi.fn() }),
  ThemeProvider: ({ children }: { children: React.ReactNode }) => <>{children}</>,
}))

vi.mock('@/shared', () => ({
  useKeyboardShortcuts: () => {},
  KeyboardShortcutsHelp: () => null,
}))

describe('DashboardShell', () => {
  const defaultProps: DashboardShellProps = {
    userDisplayName: 'Test User',
    channelLabel: null,
    profileSyncWarning: null,
  }

  afterEach(() => {
    cleanup()
  })

  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('renderiza el nombre de usuario', () => {
    render(<DashboardShell {...defaultProps} />)
    expect(screen.getByText('Test User')).toBeInTheDocument()
  })

  it('renderiza sin errores', () => {
    const { container } = render(<DashboardShell {...defaultProps} />)
    expect(container.querySelector('.main-dashboard')).toBeTruthy()
  })

  it('muestra el flujo principal: agentes, chat y estado WhatsApp', () => {
    render(<DashboardShell {...defaultProps} channelLabel="WhatsApp" />)
    expect(screen.getByRole('list', { name: 'Agente' })).toBeInTheDocument()
    expect(screen.getByText('Test User')).toBeInTheDocument()
    expect(screen.getAllByText('Canal: WhatsApp').length).toBeGreaterThanOrEqual(1)
    expect(screen.getByText('WhatsApp desconectado')).toBeInTheDocument()
    expect(
      screen.getByPlaceholderText('Escribe un mensaje… (escribe / para comandos)'),
    ).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Exportar Word' })).toBeDisabled()
  })

  it('muestra alerta de sincronización cuando hay profileSyncWarning', () => {
    render(
      <DashboardShell
        {...defaultProps}
        profileSyncWarning="No se pudo guardar el perfil"
      />,
    )
    expect(screen.getAllByRole('alert').length).toBeGreaterThanOrEqual(1)
    expect(screen.getAllByText('No se pudo guardar el perfil').length).toBeGreaterThanOrEqual(1)
  })
})
