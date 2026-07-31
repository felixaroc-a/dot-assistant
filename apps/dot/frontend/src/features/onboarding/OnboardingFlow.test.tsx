import { cleanup, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import type { AuthContextValue } from '@/features/auth/types'
import { AuthReactContext } from '@/features/auth/auth-context'
import { OnboardingFlow } from './OnboardingFlow'

const apiFetchAuthedMock = vi.fn()

vi.mock('@/lib/api/client', () => ({
  apiFetchAuthed: (...args: unknown[]) => apiFetchAuthedMock(...args),
}))

vi.mock('framer-motion', () => ({
  motion: {
    section: 'section',
    div: 'div',
    h1: 'h1',
    h2: 'h2',
    button: 'button',
    p: 'p',
    span: 'span',
    svg: 'svg',
    path: 'path',
    circle: 'circle',
    footer: 'footer',
  },
  AnimatePresence: ({ children }: { children: React.ReactNode }) => <>{children}</>,
  useReducedMotion: () => true,
}))

vi.mock('@/features/dashboard', () => ({
  DashboardShell: ({ userDisplayName }: { userDisplayName: string }) => (
    <div data-testid="dashboard-shell">Dashboard de {userDisplayName}</div>
  ),
}))

vi.mock('@/features/auth/LoginScreen', () => ({
  LoginScreen: () => <div data-testid="login-screen">Pantalla de login</div>,
}))

vi.mock('@/components/LoadingScreen', () => ({
  LoadingScreen: ({ message }: { message: string }) => (
    <div data-testid="loading-screen">{message}</div>
  ),
}))

function renderWithAuth(value: AuthContextValue) {
  return render(
    <AuthReactContext.Provider value={value}>
      <OnboardingFlow />
    </AuthReactContext.Provider>,
  )
}

const session = {
  accessToken: 'access',
  refreshToken: 'refresh',
  cliente: {
    cliente_id: 'cliente-1',
    cedula: 'V12345678',
    nombre: 'Usuario Test',
    plan: 'mensual',
    fecha_vencimiento: '2027-01-01',
  },
  expiresAtMs: Date.now() + 60_000,
  hardwareRequired: true,
}

const authBase: AuthContextValue = {
  session,
  loading: false,
  sessionRestoreError: null,
  getAccessToken: vi.fn().mockResolvedValue('mock-token'),
  login: vi.fn(),
  recoveryLogin: vi.fn(),
  logout: vi.fn(),
  isSubscriptionExpired: false,
  subscriptionExpiryDate: '2027-01-01',
}

describe('OnboardingFlow', () => {
  afterEach(() => {
    cleanup()
    vi.clearAllMocks()
  })

  beforeEach(() => {
    apiFetchAuthedMock.mockReset()
  })

  it('muestra login cuando no hay sesión', () => {
    renderWithAuth({ ...authBase, session: null })
    expect(screen.getByTestId('login-screen')).toBeInTheDocument()
  })

  it('muestra carga de perfil mientras bootstrapea', () => {
    apiFetchAuthedMock.mockReturnValue(new Promise(() => undefined))
    renderWithAuth(authBase)
    expect(screen.getByTestId('loading-screen')).toHaveTextContent('Cargando perfil')
  })

  it('sincroniza perfil vacío aunque sessionStorage tenga datos previos', async () => {
    sessionStorage.setItem('dot_onboarding_channel', JSON.stringify('whatsapp'))
    sessionStorage.setItem('dot_onboarding_integrations', JSON.stringify(['gmail']))
    sessionStorage.setItem('dot_onboarding_step', JSON.stringify('integrations'))

    apiFetchAuthedMock.mockResolvedValue({
      display_name: null,
      channel_id: null,
      ai_provider_id: null,
      integrations: [],
      automation_summary: null,
      onboarding_completed: false,
      saved_automations: [],
    })

    renderWithAuth(authBase)

    // La API devuelve onboarding_completed=false → step='welcome'
    // El welcome step debe mostrarse, ignorando sessionStorage obsoleto
    await waitFor(() => {
      expect(
        screen.getByText('Tu asistente de IA en Windows'),
      ).toBeInTheDocument()
    })
  })

  it('avanza al selector de canal si el onboarding no está completo', async () => {
    apiFetchAuthedMock.mockResolvedValue({
      display_name: null,
      channel_id: null,
      ai_provider_id: null,
      integrations: [],
      automation_summary: null,
      onboarding_completed: false,
      saved_automations: [],
    })

    renderWithAuth(authBase)

    // El paso inicial es welcome — hacer clic en "Comenzar" para avanzar
    await waitFor(() => {
      expect(screen.getByText('Comenzar')).toBeInTheDocument()
    })
    await userEvent.setup().click(screen.getByText('Comenzar'))

    await waitFor(() => {
      expect(
        screen.getByText('¿A través de cuál le gustaría comunicarse con la IA?'),
      ).toBeInTheDocument()
    })
  })

  it('salta al dashboard si el perfil ya completó onboarding', async () => {
    apiFetchAuthedMock.mockResolvedValue({
      display_name: 'Ana',
      channel_id: 'whatsapp',
      ai_provider_id: 'deepseek',
      integrations: ['gmail'],
      automation_summary: 'Gmail',
      onboarding_completed: true,
      saved_automations: [],
    })

    renderWithAuth(authBase)

    await waitFor(() => {
      expect(screen.getByTestId('dashboard-shell')).toHaveTextContent('Dashboard de Ana')
    })
  })
})
