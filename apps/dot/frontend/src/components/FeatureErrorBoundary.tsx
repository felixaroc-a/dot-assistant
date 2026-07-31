import { Component, type ErrorInfo, type ReactNode } from 'react'

type FeatureErrorBoundaryProps = {
  children: ReactNode
  /** Nombre descriptivo de la caracteristica (ej: "Chat", "Automatizaciones", "Onboarding") */
  featureName: string
  /** Mensaje amigable para mostrar al usuario */
  fallbackMessage?: string
  /** Callback opcional cuando ocurre un error (para loggeo) */
  onError?: (error: Error, info: ErrorInfo) => void
}

type FeatureErrorBoundaryState = {
  hasError: boolean
  error: Error | null
}

/**
 * ErrorBoundary por caracteristica.
 * Aísla errores dentro de una feature especifica para que no rompan toda la app.
 * El usuario ve un mensaje contextual y puede reintentar solo esa seccion.
 *
 * Ejemplo de uso:
 * ```tsx
 * <FeatureErrorBoundary featureName="Chat">
 *   <DotChatPanel ... />
 * </FeatureErrorBoundary>
 * ```
 */
export class FeatureErrorBoundary extends Component<FeatureErrorBoundaryProps, FeatureErrorBoundaryState> {
  constructor(props: FeatureErrorBoundaryProps) {
    super(props)
    this.state = { hasError: false, error: null }
  }

  static getDerivedStateFromError(error: Error): FeatureErrorBoundaryState {
    return { hasError: true, error }
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error(`[FeatureErrorBoundary:${this.props.featureName}]`, error, info.componentStack)
    this.props.onError?.(error, info)
  }

  handleReset = () => {
    this.setState({ hasError: false, error: null })
  }

  render() {
    if (this.state.hasError) {
      return (
        <div
          role="alert"
          style={{
            padding: '1.5rem',
            margin: '1rem',
            borderRadius: '12px',
            background: 'rgba(233, 69, 96, 0.08)',
            border: '1px solid rgba(233, 69, 96, 0.2)',
            color: '#f5f5f7',
            textAlign: 'center',
            fontFamily: 'system-ui, sans-serif',
          }}
        >
          <p style={{ fontSize: '0.95rem', fontWeight: 500, margin: '0 0 0.5rem' }}>
            {this.props.fallbackMessage || `Error en ${this.props.featureName}`}
          </p>
          {import.meta.env.DEV && this.state.error ? (
            <pre style={{
              fontSize: '0.75rem', color: '#ffb4b4', maxWidth: '32rem',
              overflow: 'auto', margin: '0.5rem auto', padding: '0.5rem',
              border: '1px solid rgba(255,255,255,0.1)', borderRadius: '6px',
              textAlign: 'left',
            }}>
              {this.state.error.message}
            </pre>
          ) : null}
          <button
            type="button"
            onClick={this.handleReset}
            style={{
              marginTop: '0.75rem', padding: '0.5rem 1rem',
              borderRadius: '8px', border: '1px solid rgba(255,255,255,0.15)',
              background: 'rgba(255,255,255,0.05)', color: '#f5f5f7',
              cursor: 'pointer', fontSize: '0.85rem', fontFamily: 'inherit',
            }}
          >
            Reintentar
          </button>
        </div>
      )
    }

    return this.props.children
  }
}
