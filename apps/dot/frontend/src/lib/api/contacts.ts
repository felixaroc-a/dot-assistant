import { apiFetchAuthed } from '@/lib/api/client'
import type { GetAccessToken } from '@/lib/api/client'

export type ContactRecord = {
  id: string
  name: string
  phone: string
  email: string
  tags: string[]
  notes: string
  source: string
  updated_at?: string | null
}

export type ContactsOverview = {
  total: number
  contacts: ContactRecord[]
}

export async function fetchContacts(getAccessToken: GetAccessToken): Promise<ContactsOverview> {
  return apiFetchAuthed<ContactsOverview>('/v1/contacts', { method: 'GET' }, getAccessToken)
}

export async function createContact(
  getAccessToken: GetAccessToken,
  payload: { name: string; phone?: string; email?: string; notes?: string },
): Promise<{ ok: boolean; message: string }> {
  return apiFetchAuthed('/v1/contacts', { method: 'POST', body: JSON.stringify(payload) }, getAccessToken)
}

export async function deleteContact(
  getAccessToken: GetAccessToken,
  contactId: string,
): Promise<{ ok: boolean; message: string }> {
  return apiFetchAuthed(`/v1/contacts/${encodeURIComponent(contactId)}`, { method: 'DELETE' }, getAccessToken)
}

export async function importGmailContacts(
  getAccessToken: GetAccessToken,
): Promise<{ ok: boolean; message: string; total: number }> {
  return apiFetchAuthed('/v1/contacts/import/gmail', { method: 'POST' }, getAccessToken)
}

export async function importWhatsappContacts(
  getAccessToken: GetAccessToken,
): Promise<{ ok: boolean; message: string; total: number }> {
  return apiFetchAuthed('/v1/contacts/import/whatsapp', { method: 'POST' }, getAccessToken)
}
