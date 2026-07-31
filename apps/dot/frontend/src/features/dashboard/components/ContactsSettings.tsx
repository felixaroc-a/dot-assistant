import { useCallback, useEffect, useState } from 'react'

import type { GetAccessToken } from '@/lib/api/client'
import {
  createContact,
  deleteContact,
  fetchContacts,
  importGmailContacts,
  importWhatsappContacts,
  type ContactRecord,
} from '@/lib/api/contacts'

export type ContactsSettingsProps = {
  getAccessToken: GetAccessToken
}

export function ContactsSettings({ getAccessToken }: ContactsSettingsProps) {
  const [contacts, setContacts] = useState<ContactRecord[]>([])
  const [loading, setLoading] = useState(true)
  const [busy, setBusy] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [message, setMessage] = useState<string | null>(null)
  const [name, setName] = useState('')
  const [phone, setPhone] = useState('')
  const [email, setEmail] = useState('')

  const load = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const data = await fetchContacts(getAccessToken)
      setContacts(data.contacts || [])
    } catch {
      setError('No se pudo cargar tu agenda de contactos.')
    } finally {
      setLoading(false)
    }
  }, [getAccessToken])

  useEffect(() => {
    void load()
  }, [load])

  const runAction = useCallback(
    async (label: string, action: () => Promise<{ message?: string }>) => {
      setBusy(label)
      setMessage(null)
      setError(null)
      try {
        const result = await action()
        setMessage(result.message || 'Listo.')
        await load()
      } catch {
        setError(`No se pudo completar: ${label}.`)
      } finally {
        setBusy(null)
      }
    },
    [load],
  )

  const handleCreate = useCallback(async () => {
    const trimmed = name.trim()
    if (!trimmed) {
      setError('Escribe al menos el nombre del contacto.')
      return
    }
    await runAction('guardar', async () => {
      const result = await createContact(getAccessToken, {
        name: trimmed,
        phone: phone.trim(),
        email: email.trim(),
      })
      setName('')
      setPhone('')
      setEmail('')
      return result
    })
  }, [email, getAccessToken, name, phone, runAction])

  return (
    <div className="settings-section">
      <p className="settings-section__desc">
        Agenda local para que DOT resuelva «escríbele a María» y envíe WhatsApp con el teléfono correcto.
        Se guarda en tu Escritorio (DOT Trabajos/CRM).
      </p>

      <div className="settings-section__card">
        <div className="settings-field settings-field--group">
          <span className="settings-field__label">Importar contactos</span>
          <div className="settings-field__row settings-field__row--wrap">
            <button
              type="button"
              className="settings-section__secondary-btn"
              disabled={!!busy}
              onClick={() => void runAction('Gmail', () => importGmailContacts(getAccessToken))}
            >
              {busy === 'Gmail' ? 'Importando…' : 'Desde Gmail'}
            </button>
            <button
              type="button"
              className="settings-section__secondary-btn"
              disabled={!!busy}
              onClick={() => void runAction('WhatsApp', () => importWhatsappContacts(getAccessToken))}
            >
              {busy === 'WhatsApp' ? 'Importando…' : 'Desde WhatsApp'}
            </button>
          </div>
          <span className="settings-field__help">
            Gmail aporta nombres y correos; WhatsApp aporta números de conversaciones recientes.
          </span>
        </div>
      </div>

      <div className="settings-section__card">
        <div className="settings-field settings-field--group">
          <span className="settings-field__label">Añadir contacto</span>
          <input
            className="settings-field__input"
            placeholder="Nombre (ej. María González)"
            value={name}
            onChange={(e) => setName(e.target.value)}
          />
          <input
            className="settings-field__input"
            placeholder="Teléfono WhatsApp (0414… o +58…)"
            value={phone}
            onChange={(e) => setPhone(e.target.value)}
          />
          <input
            className="settings-field__input"
            placeholder="Correo (opcional)"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
          />
          <button
            type="button"
            className="settings-section__secondary-btn"
            disabled={!!busy}
            onClick={() => void handleCreate()}
          >
            {busy === 'guardar' ? 'Guardando…' : 'Guardar contacto'}
          </button>
        </div>
      </div>

      {message ? <p className="settings-section__desc settings-section__desc--ok">{message}</p> : null}
      {error ? <p className="settings-section__desc settings-section__desc--error">{error}</p> : null}

      <div className="settings-section__card">
        <div className="settings-field settings-field--group">
          <span className="settings-field__label">
            {loading ? 'Cargando contactos…' : `Contactos (${contacts.length})`}
          </span>
          {!loading && contacts.length === 0 ? (
            <p className="settings-field__help">Aún no hay contactos. Importa o añade uno manualmente.</p>
          ) : null}
          <ul className="settings-contacts-list">
            {contacts.map((contact) => (
              <li key={contact.id} className="settings-contacts-list__item">
                <div>
                  <strong>{contact.name}</strong>
                  <div className="settings-field__help">
                    {[contact.phone, contact.email].filter(Boolean).join(' · ') || 'Sin teléfono ni correo'}
                  </div>
                </div>
                <button
                  type="button"
                  className="settings-section__danger-btn settings-section__danger-btn--inline"
                  disabled={!!busy}
                  onClick={() =>
                    void runAction('eliminar', async () => {
                      await deleteContact(getAccessToken, contact.id)
                      return { message: `Contacto «${contact.name}» eliminado.` }
                    })
                  }
                >
                  Eliminar
                </button>
              </li>
            ))}
          </ul>
        </div>
      </div>
    </div>
  )
}
