import { describe, expect, it } from 'vitest'

import { parseAssistantDocumentAction, parseSlashCommand } from './slash-commands'

describe('parseSlashCommand /agenda', () => {
  it('reconoce /agenda y dispara agenda diaria', () => {
    const result = parseSlashCommand('/agenda')
    expect(result.handled).toBe(true)
    if (!result.handled) return
    expect(result.agendaRequest).toBe('today')
    expect(result.reply).toContain('Consultando tu agenda')
  })

  it('muestra ayuda para subcomandos inválidos', () => {
    const result = parseSlashCommand('/agenda mañana')
    expect(result.handled).toBe(true)
    if (!result.handled) return
    expect(result.agendaRequest).toBeUndefined()
    expect(result.reply).toContain('/agenda')
  })
})

describe('parseSlashCommand /recordar', () => {
  it('parsea formato relativo y devuelve reminderRequest', () => {
    const result = parseSlashCommand('/recordar "Pagar licencia" en 2 horas')
    expect(result.handled).toBe(true)
    if (!result.handled) return
    expect(result.reminderRequest?.text).toBe('Pagar licencia')
    expect(result.reminderRequest?.dueAtIso).toBeTruthy()
    expect(result.reply).toContain('Guardando recordatorio')
  })

  it('devuelve ayuda cuando el formato es inválido', () => {
    const result = parseSlashCommand('/recordar mañana revisar facturas')
    expect(result.handled).toBe(true)
    if (!result.handled) return
    expect(result.reminderRequest).toBeUndefined()
    expect(result.reply).toContain('/recordar')
  })
})

describe('parseSlashCommand /traducir', () => {
  it('soporta texto entre comillas con "al" interno', () => {
    const result = parseSlashCommand('/traducir "Vamos al parque al mediodía" al inglés')
    expect(result.handled).toBe(true)
    if (!result.handled) return
    expect(result.translationRequest).toEqual({
      text: 'Vamos al parque al mediodía',
      targetLanguage: 'inglés',
    })
    expect(result.reply).toContain('Traduciendo al inglés')
  })

  it('usa la última ocurrencia de "al" en texto sin comillas', () => {
    const result = parseSlashCommand('/traducir vamos al parque al italiano')
    expect(result.handled).toBe(true)
    if (!result.handled) return
    expect(result.translationRequest).toEqual({
      text: 'vamos al parque',
      targetLanguage: 'italiano',
    })
  })

  it('muestra ayuda cuando falta el idioma destino', () => {
    const result = parseSlashCommand('/traducir "hola mundo" al')
    expect(result.handled).toBe(true)
    if (!result.handled) return
    expect(result.translationRequest).toBeUndefined()
    expect(result.reply).toContain('/traducir')
  })
})

describe('parseSlashCommand /resumir', () => {
  it('devuelve summaryRequest para texto libre', () => {
    const result = parseSlashCommand('/resumir Este es un texto largo para resumir')
    expect(result.handled).toBe(true)
    if (!result.handled) return
    expect(result.summaryRequest).toEqual({
      source: 'Este es un texto largo para resumir',
    })
    expect(result.reply).toContain('Resumiendo')
  })

  it('muestra ayuda cuando no recibe contenido', () => {
    const result = parseSlashCommand('/resumir ')
    expect(result.handled).toBe(true)
    if (!result.handled) return
    expect(result.summaryRequest).toBeUndefined()
    expect(result.reply).toContain('/resumir')
  })
})

describe('parseSlashCommand /analizar', () => {
  it('envía prompt de análisis Excel al chat', () => {
    const result = parseSlashCommand('/analizar ~/Desktop/ventas.xlsx')
    expect(result.handled).toBe(true)
    if (!result.handled) return
    expect(result.sendToChat).toContain('read_spreadsheet')
    expect(result.sendToChat).toContain('ventas.xlsx')
    expect(result.reply).toContain('Analizando')
  })

  it('muestra ayuda sin ruta', () => {
    const result = parseSlashCommand('/analizar ')
    expect(result.handled).toBe(true)
    if (!result.handled) return
    expect(result.sendToChat).toBeUndefined()
    expect(result.reply).toContain('/analizar')
  })
})

describe('parseSlashCommand /correo', () => {
  it('lista correos sin leer vía sendToChat', () => {
    const result = parseSlashCommand('/correo')
    expect(result.handled).toBe(true)
    if (!result.handled) return
    expect(result.sendToChat).toContain('gmail_list_unread')
    expect(result.reply).toContain('sin leer')
  })

  it('busca con filtro Gmail', () => {
    const result = parseSlashCommand('/correo from:juan@empresa.com')
    expect(result.handled).toBe(true)
    if (!result.handled) return
    expect(result.sendToChat).toContain('gmail_search')
    expect(result.sendToChat).toContain('from:juan@empresa.com')
  })
})

describe('parseSlashCommand /responder', () => {
  it('encadena respuesta al último correo', () => {
    const result = parseSlashCommand('/responder Gracias, recibido.')
    expect(result.handled).toBe(true)
    if (!result.handled) return
    expect(result.sendToChat).toContain('gmail_auto_reply')
    expect(result.sendToChat).toContain('Gracias, recibido.')
  })
})

describe('parseSlashCommand /archivar', () => {
  it('mapea spam a label:spam', () => {
    const result = parseSlashCommand('/archivar spam')
    expect(result.handled).toBe(true)
    if (!result.handled) return
    expect(result.sendToChat).toContain('label:spam')
    expect(result.sendToChat).toContain('gmail_archive')
  })
})

describe('parseSlashCommand /adjuntos', () => {
  it('descarga adjuntos al Escritorio', () => {
    const result = parseSlashCommand('/adjuntos')
    expect(result.handled).toBe(true)
    if (!result.handled) return
    expect(result.sendToChat).toContain('gmail_get_attachments')
    expect(result.sendToChat).toContain('~/Desktop')
  })
})

describe('parseAssistantDocumentAction', () => {
  it('parsea JSON directo de create_document', () => {
    const action = parseAssistantDocumentAction(
      '{"action":"create_document","type":"docx","title":"Acta","content":"Contenido base"}',
    )
    expect(action).toEqual({
      documentType: 'docx',
      title: 'Acta',
      content: 'Contenido base',
    })
  })

  it('parsea JSON en bloque markdown y normaliza tipo word', () => {
    const action = parseAssistantDocumentAction(
      '```json\n{"action":"create_document","type":"word","title":"Minuta","content":"Puntos de reunión"}\n```',
    )
    expect(action).toEqual({
      documentType: 'docx',
      title: 'Minuta',
      content: 'Puntos de reunión',
    })
  })

  it('retorna null cuando no es acción de documento', () => {
    const action = parseAssistantDocumentAction('{"action":"none","message":"ok"}')
    expect(action).toBeNull()
  })

  it('ignora tipos no soportados por el backend (csv, md)', () => {
    expect(
      parseAssistantDocumentAction(
        '{"action":"create_document","type":"csv","title":"Datos","content":"a,b"}',
      ),
    ).toBeNull()
    expect(
      parseAssistantDocumentAction(
        '{"action":"create_document","type":"md","title":"Notas","content":"# t"}',
      ),
    ).toBeNull()
  })

  it('normaliza markdown a txt', () => {
    const action = parseAssistantDocumentAction(
      '{"action":"create_document","type":"markdown","title":"Notas","content":"cuerpo"}',
    )
    expect(action?.documentType).toBe('txt')
  })
})
