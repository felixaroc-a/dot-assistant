import { useCallback, useState } from 'react'
import { generateDocument, type GenerateRequest, type GenerateResponse } from '@/lib/api/documents'
import type { GetAccessToken } from '@/lib/api/client'

export type DocumentGeneratorState = {
  isGenerating: boolean
  lastResult: GenerateResponse | null
  error: string | null
}

export function useDocumentGenerator(getAccessToken: GetAccessToken) {
  const [state, setState] = useState<DocumentGeneratorState>({
    isGenerating: false,
    lastResult: null,
    error: null,
  })

  const generate = useCallback(
    async (req: GenerateRequest) => {
      setState({ isGenerating: true, lastResult: null, error: null })
      try {
        const result = await generateDocument(req, getAccessToken)
        setState({ isGenerating: false, lastResult: result, error: null })
        return result
      } catch (e) {
        const msg = e instanceof Error ? e.message : 'Error al generar documento'
        setState({ isGenerating: false, lastResult: null, error: msg })
        throw e
      }
    },
    [getAccessToken],
  )

  const reset = useCallback(() => {
    setState({ isGenerating: false, lastResult: null, error: null })
  }, [])

  return { ...state, generate, reset }
}
