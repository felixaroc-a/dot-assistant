import { describe, expect, it } from 'vitest'

import type {
  GenerateDocumentType,
  GenerateRequest,
  TemplateDocumentType,
} from '@/lib/api/documents'

/** Tipos soportados por POST /v1/documents/generate (backend DOCUMENT_TYPES). */
export const BACKEND_GENERATE_DOCUMENT_TYPES = [
  'docx',
  'xlsx',
  'txt',
  'pdf',
] as const satisfies readonly GenerateDocumentType[]

/** Tipos de plantilla: POST /v1/templates (sin pdf). */
export const BACKEND_TEMPLATE_DOCUMENT_TYPES = [
  'docx',
  'xlsx',
  'txt',
] as const satisfies readonly TemplateDocumentType[]

describe('DocumentType', () => {
  it('GenerateDocumentType coincide con el backend', () => {
    expect(BACKEND_GENERATE_DOCUMENT_TYPES).toEqual(['docx', 'xlsx', 'txt', 'pdf'])
  })

  it('TemplateDocumentType coincide con plantillas del backend', () => {
    expect(BACKEND_TEMPLATE_DOCUMENT_TYPES).toEqual(['docx', 'xlsx', 'txt'])
  })

  it('GenerateRequest exige document_type, title y content', () => {
    const req: GenerateRequest = {
      document_type: 'pdf',
      title: 'Informe',
      content: 'Cuerpo del documento',
      folder: 'Documentos',
    }
    expect(req.document_type).toBe('pdf')
    expect(typeof req.title).toBe('string')
    expect(typeof req.content).toBe('string')
  })
})
