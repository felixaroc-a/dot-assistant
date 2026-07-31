import { createContext, useContext } from 'react'

import type { AuthContextValue } from './types'

export const AuthReactContext = createContext<AuthContextValue | null>(null)

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthReactContext)
  if (!ctx) {
    throw new Error('useAuth debe usarse dentro de AuthProvider.')
  }
  return ctx
}
