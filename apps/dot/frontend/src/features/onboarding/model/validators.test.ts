import { describe, expect, it } from 'vitest'

import { filterIntegrationIds, isChannelId, isIntegrationId } from './validators'

describe('isChannelId', () => {
  it('acepta "whatsapp" como canal valido', () => {
    expect(isChannelId('whatsapp')).toBe(true)
  })

  it('rechaza canales desconocidos', () => {
    expect(isChannelId('telegram')).toBe(false)
    expect(isChannelId('email')).toBe(false)
    expect(isChannelId('')).toBe(false)
  })

  it('es case-sensitive (minusculas requeridas)', () => {
    expect(isChannelId('WhatsApp')).toBe(false)
    expect(isChannelId('WHATSAPP')).toBe(false)
  })
})

describe('isIntegrationId', () => {
  it('acepta integraciones conocidas', () => {
    expect(isIntegrationId('gmail')).toBe(true)
    expect(isIntegrationId('google-calendar')).toBe(true)
    expect(isIntegrationId('third-option')).toBe(true)
  })

  it('rechaza integraciones desconocidas', () => {
    expect(isIntegrationId('outlook')).toBe(false)
    expect(isIntegrationId('slack')).toBe(false)
    expect(isIntegrationId('')).toBe(false)
  })

  it('NO acepta "whatsapp" (no es integracion)', () => {
    expect(isIntegrationId('whatsapp')).toBe(false)
  })
})

describe('filterIntegrationIds', () => {
  it('filtra solo las integraciones validas del arreglo', () => {
    const result = filterIntegrationIds(['gmail', 'outlook', 'google-calendar', 'slack', 'third-option'])
    expect(result).toEqual(['gmail', 'google-calendar', 'third-option'])
  })

  it('retorna arreglo vacio si ninguna es valida', () => {
    expect(filterIntegrationIds(['outlook', 'slack'])).toEqual([])
  })

  it('retorna arreglo vacio si recibe arreglo vacio', () => {
    expect(filterIntegrationIds([])).toEqual([])
  })

  it('no modifica el arreglo original', () => {
    const input = ['gmail', 'invalid']
    const inputCopy = [...input]
    filterIntegrationIds(input)
    expect(input).toEqual(inputCopy)
  })
})
