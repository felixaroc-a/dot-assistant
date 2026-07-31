import { describe, expect, it } from 'vitest'

import {
  humanizeLocalToolJsonIfPresent,
  parseLocalToolAction,
} from './parse-local-tool-action'

describe('parse-local-tool-action (FASE2 hotfix UI)', () => {
  it('parsea writeFile completo', () => {
    const action = parseLocalToolAction(
      '{"action":"local_tool","operation":"writeFile","path":"~/Desktop/prueba-dot.txt","content":"hola"}',
    )
    expect(action?.operation).toBe('writeFile')
    expect(action?.path).toBe('~/Desktop/prueba-dot.txt')
    expect(action?.content).toBe('hola')
  })

  it('repara JSON truncado sin } final', () => {
    const action = parseLocalToolAction(
      '{"action":"local_tool","operation":"writeFile","path":"~/Desktop/prueba-dot.txt","content":"hola"',
    )
    expect(action?.operation).toBe('writeFile')
    expect(action?.content).toBe('hola')
  })

  it('deja JSON local_tool intacto para el fallback IPC', () => {
    const raw =
      '{"action":"local_tool","operation":"writeFile","path":"~/Desktop/x.txt","content":"hola"}'
    expect(humanizeLocalToolJsonIfPresent(raw)).toBe(raw)
  })

  it('deja texto normal intacto', () => {
    expect(humanizeLocalToolJsonIfPresent('Hola, ¿en qué te ayudo?')).toBe(
      'Hola, ¿en qué te ayudo?',
    )
  })

  it('parsea downloadUrl y tool_calls de descarga', () => {
    const a = parseLocalToolAction(
      '{"action":"local_tool","operation":"downloadUrl","path":"~/Desktop/dummy.pdf","url":"https://example.com/dummy.pdf"}',
    )
    expect(a?.operation).toBe('downloadUrl')
    expect(a?.url).toBe('https://example.com/dummy.pdf')

    const b = parseLocalToolAction(
      '{"tool_calls":[{"name":"download_url_to_desktop","arguments":{"url":"https://a.com/x.pdf","path":"~/Desktop/x.pdf"}}]}',
    )
    expect(b?.operation).toBe('downloadUrl')
    expect(b?.url).toBe('https://a.com/x.pdf')
  })
})
