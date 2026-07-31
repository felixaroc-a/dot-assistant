import { useState } from 'react'
import { Navigate, Route, Routes } from 'react-router-dom'

import { AuthProvider } from '@/features/auth'
import { SplashScreen } from '@/features/splash'
import { AuthenticatedApp } from '@/lib/router/AuthenticatedApp'

function SplashPage() {
  const [done, setDone] = useState(false)

  if (done) {
    return <Navigate to="/app" replace />
  }

  return <SplashScreen onComplete={() => setDone(true)} />
}

/**
 * Componente raiz de la aplicacion con React Router v7.
 *
 * Estructura de rutas:
 * - `/` → SplashScreen, redirige a /app al terminar
 * - `/app/*` → Zona protegida: AuthProvider + PendriveAppGate + OnboardingFlow/Dashboard
 * - Cualquier otra ruta → redirige a /
 */
export default function App() {
  return (
    <Routes>
      <Route path="/" element={<SplashPage />} />
      <Route
        path="/app/*"
        element={
          <AuthProvider>
            <AuthenticatedApp />
          </AuthProvider>
        }
      />
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  )
}
