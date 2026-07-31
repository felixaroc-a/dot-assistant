/**
 * API client para generacion de documentos.
 */
import { apiFetchAuthed } from '@/lib/api/client'
import type { GetAccessToken } from '@/lib/api/client'

/** Tipos aceptados por POST /v1/documents/generate (backend). */
export type GenerateDocumentType = 'docx' | 'xlsx' | 'txt' | 'pdf'

/** Tipos aceptados por plantillas (backend: docx, xlsx, txt). */
export type TemplateDocumentType = 'docx' | 'xlsx' | 'txt'

export type DocumentType = GenerateDocumentType | TemplateDocumentType

export type GenerateRequest = {
  document_type: GenerateDocumentType
  title: string
  content: string
  folder?: string
}

export type GenerateResponse = {
  ok: boolean
  filename: string
  path: string
  document_type: string
  size_bytes: number
}

export type DocumentTemplate = {
  id: string
  name: string
  document_type: DocumentType
  structure: string
  created_at?: string | null
  updated_at?: string | null
}

export type DocumentTemplateListResponse = {
  templates: DocumentTemplate[]
}

export type CreateDocumentTemplateRequest = {
  name: string
  document_type: TemplateDocumentType
  structure: string
}

export type RenderTemplateRequest = {
  user_input: string
  provider?: string | null
}

export type RenderTemplateResponse = {
  template_id: string
  template_name: string
  document_type: DocumentType
  title: string
  content: string
}

export async function generateDocument(
  req: GenerateRequest,
  getAccessToken: GetAccessToken,
): Promise<GenerateResponse> {
  return apiFetchAuthed<GenerateResponse>(
    '/v1/documents/generate',
    {
      method: 'POST',
      body: JSON.stringify(req),
    },
    getAccessToken,
  )
}

export async function listDocumentTemplates(
  getAccessToken: GetAccessToken,
): Promise<DocumentTemplateListResponse> {
  return apiFetchAuthed<DocumentTemplateListResponse>(
    '/v1/templates',
    { method: 'GET' },
    getAccessToken,
  )
}

export async function createDocumentTemplate(
  req: CreateDocumentTemplateRequest,
  getAccessToken: GetAccessToken,
): Promise<DocumentTemplate> {
  return apiFetchAuthed<DocumentTemplate>(
    '/v1/templates',
    {
      method: 'POST',
      body: JSON.stringify(req),
    },
    getAccessToken,
  )
}

export async function deleteDocumentTemplate(
  templateId: string,
  getAccessToken: GetAccessToken,
): Promise<{ ok: boolean }> {
  return apiFetchAuthed<{ ok: boolean }>(
    `/v1/templates/${encodeURIComponent(templateId)}`,
    { method: 'DELETE' },
    getAccessToken,
  )
}

export async function renderDocumentTemplate(
  templateId: string,
  req: RenderTemplateRequest,
  getAccessToken: GetAccessToken,
): Promise<RenderTemplateResponse> {
  return apiFetchAuthed<RenderTemplateResponse>(
    `/v1/templates/${encodeURIComponent(templateId)}/render`,
    {
      method: 'POST',
      body: JSON.stringify(req),
    },
    getAccessToken,
  )
}
