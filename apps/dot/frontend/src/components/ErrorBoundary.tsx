import { Component, type ErrorInfo, type ReactNode } from 'react'

import { PRODUCT_NAME } from '@/shared/constants/brand'

type ErrorBoundaryProps = {
  children: ReactNode
}

type ErrorBoundaryState = {
  hasError: boolean
  error: Error | null
}

export class ErrorBoundary extends Component<ErrorBoundaryProps, ErrorBoundaryState> {
  constructor(props: ErrorBoundaryProps) {
    super(props)
    this.state = { hasError: false, error: null }
  }

  static getDerivedStateFromError(error: Error): ErrorBoundaryState {
    return { hasError: true, error }
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error('[ErrorBoundary] Error no recuperado:', error, info.componentStack)
  }

  handleReset = () => {
    this.setState({ hasError: false, error: null })
  }

  render() {
    if (this.state.hasError) {
      return (
        <div
          style={{
            minHeight: '100vh',
            display: 'flex',
            flexDirection: 'column',
            alignItems: 'center',
            justifyContent: 'center',
            padding: '2rem',
            background: '#050505',
            color: '#f5f5f7',
            textAlign: 'center',
            fontFamily: 'system-ui, sans-serif',
          }}
        >
          <h1 style={{ fontSize: '1.5rem', fontWeight: 600, margin: '0 0 0.75rem', letterSpacing: '-0.03em' }}>
            Algo salió mal
          </h1>
          <p style={{ fontSize: '0.95rem', color: 'rgba(235, 235, 245, 0.65)', maxWidth: '28rem', lineHeight: 1.5, margin: '0 0 1.25rem' }}>
            {PRODUCT_NAME} encontró un error inesperado. Puedes intentar recargar la aplicación.
          </p>
          {import.meta.env.DEV && this.state.error ? (
            <pre style={{ fontSize: '0.78rem', color: '#ffb4b4', maxWidth: '36rem', overflow: 'auto', margin: '0 0 1.25rem', padding: '0.75rem', border: '1px solid rgba(255,255,255,0.1)', borderRadius: '8px', textAlign: 'left' }}>
              {this.state.error.message}
              {'\n'}
              {this.state.error.stack}
            </pre>
          ) : null}
          <button
            type="button"
            onClick={this.handleReset}
            style={{
              padding: '0.65rem 1.25rem',
              borderRadius: '10px',
              border: '1px solid rgba(255,255,255,0.2)',
              background: 'transparent',
              color: 'rgba(235, 235, 245, 0.92)',
              cursor: 'pointer',
              fontSize: '0.9rem',
              fontFamily: 'inherit',
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
