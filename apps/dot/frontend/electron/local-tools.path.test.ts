import { createRequire } from 'node:module'
import path from 'node:path'
import os from 'node:os'
import { describe, expect, it } from 'vitest'

const require = createRequire(import.meta.url)
const localTools = require('./local-tools.cjs')

describe('local-tools path sandbox (F3)', () => {
  it('bloquea path traversal con ../', () => {
    const result = localTools.writeFile('../../../Windows/Temp/dot-pwn.txt', 'x')
    expect(result.ok).toBe(false)
    expect(String(result.error || '')).toMatch(/sandbox/i)
  })

  it('bloquea ruta absoluta fuera de allowlist', () => {
    const outside = path.join(os.tmpdir(), 'dot-pwn-outside.txt')
    const result = localTools.writeFile(outside, 'x')
    expect(result.ok).toBe(false)
    expect(String(result.error || '')).toMatch(/sandbox/i)
  })

  it('bloquea ~/ fuera de Desktop/Documents/Downloads', () => {
    const result = localTools.readFile('~/AppData/Local/dot-secret.txt')
    expect(result.ok).toBe(false)
    expect(String(result.error || '')).toMatch(/sandbox/i)
  })

  it('permite escritura relativa dentro del sandbox DOT', () => {
    const name = `dot-f3-test-${Date.now()}.txt`
    const written = localTools.writeFile(name, `ok-${Date.now()}`)
    expect(written.ok).toBe(true)
    expect(String(written.path || '')).toContain(path.join('Documents', 'DOT'))

    const read = localTools.readFile(name)
    expect(read.ok).toBe(true)

    const deleted = localTools.deleteFile(name)
    expect(deleted.ok).toBe(true)
  })

  it('permite escritura en ~/Desktop (no descarta la raíz por path.join)', () => {
    const name = `dot-desktop-test-${Date.now()}.txt`
    const written = localTools.writeFile(`~/Desktop/${name}`, 'hola-escritorio')
    expect(written.ok).toBe(true)
    expect(String(written.path || '').toLowerCase()).toMatch(/desktop|escritorio/)
    expect(String(written.path || '')).toContain(name)

    const deleted = localTools.deleteFile(`~/Desktop/${name}`)
    expect(deleted.ok).toBe(true)
  })

  it('bloquea download file://', async () => {
    const result = await localTools.downloadUrlToDesktop('file:///C:/Windows/win.ini', '')
    expect(result.ok).toBe(false)
    expect(String(result.error || '').toLowerCase()).toMatch(/http|file/)
  })

  it('bloquea download a localhost', async () => {
    const result = await localTools.downloadUrlToDesktop('http://127.0.0.1:8080/x', '')
    expect(result.ok).toBe(false)
    expect(String(result.error || '').toLowerCase()).toMatch(/host|interno|local/)
  })
})
