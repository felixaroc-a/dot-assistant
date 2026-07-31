import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { BrowserRouter, HashRouter } from 'react-router-dom'

import './lib/i18n/config'
import App from '@/app/App'
import { ErrorBoundary } from '@/components/ErrorBoundary'
import { ToastProvider } from '@/components/Toast'
import { ThemeProvider } from '@/shared/theme-context'
import { useGlobalApiErrors } from '@/lib/api/useGlobalApiErrors'
import '@/shared/styles/globals.css'
import '@/shared/styles/motion.css'

/** Inicializa el manejador global de errores HTTP dentro del arbol React */
function AppWithGlobalErrors() {
  useGlobalApiErrors()
  return <App />
}

// Electron carga file:// o custom protocol — BrowserRouter rompe y deja pantalla negra.
// HashRouter funciona en ambos (Vite http:// y Electron file://).
const isElectronShell =
  typeof window !== 'undefined' &&
  (Boolean((window as Window & { desktop?: unknown }).desktop) ||
    window.location.protocol === 'file:')
const Router = isElectronShell ? HashRouter : BrowserRouter

// Capturar errores no manejados de promesas
window.addEventListener('unhandledrejection', (event) => {
  console.error('[Global] Promesa no manejada:', event.reason)
  event.preventDefault()
})

// Service Worker: NUNCA en Electron (file:// + SW = UI rota / pantalla negra).
// Solo en web build empaquetado vía HTTP.
const isElectronRuntime =
  typeof window !== 'undefined' &&
  Boolean((window as Window & { desktop?: unknown }).desktop)

if ('serviceWorker' in navigator && import.meta.env.PROD && !isElectronRuntime) {
  window.addEventListener('load', () => {
    navigator.serviceWorker.register('/service-worker.js').catch((err) => {
      console.warn('[SW] No se pudo registrar el Service Worker:', err)
    })
  })
} else if ('serviceWorker' in navigator) {
  void navigator.serviceWorker.getRegistrations().then((regs) => {
    for (const reg of regs) void reg.unregister()
  })
}

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <Router>
      <ErrorBoundary>
        <ThemeProvider>
          <ToastProvider>
            <AppWithGlobalErrors />
          </ToastProvider>
        </ThemeProvider>
      </ErrorBoundary>
    </Router>
  </StrictMode>,
)
