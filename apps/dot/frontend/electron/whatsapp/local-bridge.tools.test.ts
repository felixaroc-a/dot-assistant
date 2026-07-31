import { createRequire } from 'node:module'
import { describe, expect, it } from 'vitest'

const require = createRequire(import.meta.url)
const { executeLocalTool } = require('./local-bridge.cjs')

describe('local-bridge tools allowlist (C2/F4)', () => {
  it('deniega operaciones fuera de allowlist', () => {
    const result = executeLocalTool({ operation: 'shell', path: 'x', content: 'rm -rf' })
    expect(result.ok).toBe(false)
    expect(String(result.error)).toMatch(/not_allowed/)
  })

  it('permite writeFile dentro del sandbox', () => {
    const name = `bridge-tool-${Date.now()}.txt`
    const result = executeLocalTool({
      operation: 'writeFile',
      path: name,
      content: 'desde-bridge',
    })
    expect(result.ok).toBe(true)
    const deleted = executeLocalTool({ operation: 'deleteFile', path: name })
    expect(deleted.ok).toBe(true)
  })
})
