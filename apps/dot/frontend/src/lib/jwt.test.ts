import { describe, expect, it } from 'vitest'

import { readJwtExpMs, readJwtHardwareRequired } from './jwt'

function fakeToken(payload: object): string {
  const header = btoa(JSON.stringify({ alg: 'none', typ: 'JWT' }))
    .replace(/\+/g, '-')
    .replace(/\//g, '_')
    .replace(/=+$/g, '')
  const body = btoa(JSON.stringify(payload))
    .replace(/\+/g, '-')
    .replace(/\//g, '_')
    .replace(/=+$/g, '')
  return `${header}.${body}.signature`
}

describe('jwt helpers', () => {
  it('lee exp en milisegundos', () => {
    const token = fakeToken({ exp: 1700000000 })
    expect(readJwtExpMs(token)).toBe(1700000000 * 1000)
  })

  it('lee hardware_required cuando existe', () => {
    const token = fakeToken({ hardware_required: false })
    expect(readJwtHardwareRequired(token)).toBe(false)
  })

  it('retorna null con token inválido', () => {
    expect(readJwtExpMs('invalido')).toBeNull()
    expect(readJwtHardwareRequired('invalido')).toBeNull()
  })
})
