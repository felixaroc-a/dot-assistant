import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { DotChatPanel } from './DotChatPanel'

function renderChatPanel({
  onSend = vi.fn(),
  onExportConversation = vi.fn(),
  onSendImage = vi.fn(() => Promise.resolve()),
  onGenerateImage = vi.fn(() => Promise.resolve()),
  canExportConversation = false,
  messages = [],
}: {
  onSend?: (text: string, options?: { displayText?: string; attachment?: { name: string; type: string; size: number } }) => void
  onSendImage?: (file: File, prompt: string) => Promise<void>
  onGenerateImage?: (text: string) => Promise<void>
  onExportConversation?: (format: 'docx' | 'pdf') => void
  canExportConversation?: boolean
  messages?: Array<{
    id: string
    role: 'user' | 'assistant'
    text: string
    createdAt: string
    status?: 'sending' | 'sent' | 'error'
  }>
} = {}) {
  const renderResult = render(
    <DotChatPanel
      messages={messages}
      isSending={false}
      canExportConversation={canExportConversation}
      isExportingConversation={false}
      lastError={null}
      getAccessToken={async () => 'test-token'}
      onClearError={vi.fn()}
      onSend={onSend}
      onSendImage={onSendImage}
      onGenerateImage={onGenerateImage}
      onExportConversation={onExportConversation}
    />,
  )
  return { ...renderResult, onSend, onExportConversation }
}

describe('DotChatPanel command suggestions', () => {
  afterEach(() => {
    cleanup()
  })

  it('oculta sugerencias al borrar el slash', () => {
    renderChatPanel()
    const textarea = screen.getByPlaceholderText('Escribe un mensaje… (escribe / para comandos)')

    fireEvent.change(textarea, { target: { value: '/' } })
    expect(screen.getByText('Comandos disponibles')).toBeInTheDocument()

    fireEvent.change(textarea, { target: { value: '' } })
    expect(screen.queryByText('Comandos disponibles')).not.toBeInTheDocument()
  })

  it('filtra sugerencias por texto parcial', () => {
    renderChatPanel()
    const textarea = screen.getByPlaceholderText('Escribe un mensaje… (escribe / para comandos)')

    fireEvent.change(textarea, { target: { value: '/tra' } })

    expect(screen.getByText('/traducir — Traducir texto')).toBeInTheDocument()
    expect(screen.queryByText('/buscar — Buscar en internet')).not.toBeInTheDocument()
  })

  it('permite navegar con flechas y seleccionar con Enter', () => {
    renderChatPanel()
    const textarea = screen.getByPlaceholderText(
      'Escribe un mensaje… (escribe / para comandos)',
    ) as HTMLTextAreaElement

    fireEvent.change(textarea, { target: { value: '/' } })
    fireEvent.keyDown(textarea, { key: 'ArrowDown' })
    fireEvent.keyDown(textarea, { key: 'Enter' })

    expect(textarea.value).toBe('/agenda ')
    expect(screen.queryByText('Comandos disponibles')).not.toBeInTheDocument()
  })

  it('envia mensaje al presionar Enter cuando el comando es exacto', () => {
    const { onSend } = renderChatPanel()
    const textarea = screen.getByPlaceholderText(
      'Escribe un mensaje… (escribe / para comandos)',
    ) as HTMLTextAreaElement

    fireEvent.change(textarea, { target: { value: '/agenda' } })
    fireEvent.keyDown(textarea, { key: 'Enter' })

    expect(onSend).toHaveBeenCalledWith('/agenda')
    expect(textarea.value).toBe('')
  })

  it('deshabilita exportación si no hay conversación', () => {
    renderChatPanel()
    expect(screen.getByRole('button', { name: 'Exportar Word' })).toBeDisabled()
    expect(screen.getByRole('button', { name: 'Exportar PDF' })).toBeDisabled()
  })

  it('dispara exportación en Word y PDF cuando hay mensajes', () => {
    const { onExportConversation } = renderChatPanel({
      canExportConversation: true,
      messages: [
        {
          id: 'm1',
          role: 'user',
          text: 'Hola',
          createdAt: new Date().toISOString(),
          status: 'sent',
        },
      ],
    })
    fireEvent.click(screen.getByRole('button', { name: 'Exportar Word' }))
    fireEvent.click(screen.getByRole('button', { name: 'Exportar PDF' }))
    expect(onExportConversation).toHaveBeenNthCalledWith(1, 'docx')
    expect(onExportConversation).toHaveBeenNthCalledWith(2, 'pdf')
  })

  it('permite enviar imagen adjunta sin texto', async () => {
    const onSendImage = vi.fn(() => Promise.resolve())
    const { container } = renderChatPanel({ onSendImage })

    const file = new File(['photo'], 'photo.png', { type: 'image/png' })
    const input = container.querySelector('input[type="file"]') as HTMLInputElement
    fireEvent.change(input, { target: { files: [file] } })

    expect(await screen.findByText('photo.png')).toBeInTheDocument()

    const sendButton = screen.getByRole('button', { name: 'Enviar mensaje' })
    expect(sendButton).toBeEnabled()

    fireEvent.click(sendButton)

    await waitFor(() => {
      expect(onSendImage).toHaveBeenCalledWith(file, '')
    })
  })

  it('responde al arraste de imagen y muestra overlay', async () => {
    const { container } = renderChatPanel()
    const file = new File(['drag'], 'drag.png', { type: 'image/png' })

    const dataTransfer = {
      files: [file],
      types: ['Files'],
      items: [
        {
          kind: 'file',
          type: file.type,
          getAsFile: () => file,
        },
      ],
    } as unknown as DataTransfer

    const chat = container.querySelector('.dot-chat') as HTMLDivElement
    fireEvent.dragEnter(chat, { dataTransfer })

    expect(screen.getByText('Suelta la imagen o documento aquí')).toBeInTheDocument()

    fireEvent.drop(chat, { dataTransfer })

    expect(await screen.findByText('drag.png')).toBeInTheDocument()
  })

  it('permite pegar imagen desde el portapapeles', async () => {
    renderChatPanel()
    const textarea = screen.getByPlaceholderText('Escribe un mensaje… (escribe / para comandos)') as HTMLTextAreaElement
    const file = new File(['clipboard'], 'clip.png', { type: 'image/png' })

    const clipboardData = {
      items: [
        {
          kind: 'file',
          type: file.type,
          getAsFile: () => file,
        },
      ],
      files: [],
    } as unknown as DataTransfer

    fireEvent.paste(textarea, { clipboardData } as unknown as ClipboardEvent)

    expect(await screen.findByText('clip.png')).toBeInTheDocument()
  })
})

describe('DotChatPanel multi-chat', () => {
  afterEach(() => {
    cleanup()
  })

  it('muestra botón Nuevo chat y llama onNewChat', () => {
    const onNewChat = vi.fn()
    render(
      <DotChatPanel
        messages={[]}
        isSending={false}
        lastError={null}
        getAccessToken={async () => 'test-token'}
        onClearError={vi.fn()}
        onSend={vi.fn()}
        onSendImage={vi.fn(() => Promise.resolve())}
        onGenerateImage={vi.fn(() => Promise.resolve())}
        onNewChat={onNewChat}
      />,
    )

    fireEvent.click(screen.getByRole('button', { name: /Nuevo chat/i }))
    expect(onNewChat).toHaveBeenCalledTimes(1)
  })
})
