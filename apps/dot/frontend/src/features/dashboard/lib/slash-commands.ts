/** Comandos /doc, /recordar, /buscar, /traducir, /resumir, /analizar y /agenda del asistente personal. */

export type SlashCommandResult =
  | { handled: false }
  | {
      handled: true
      reply: string
      documentRequest?: { title: string; content: string; documentType?: string }
      webSearchQuery?: string
      agendaRequest?: 'today'
      reminderRequest?: { text: string; dueAtIso: string }
      translationRequest?: { text: string; targetLanguage: string }
      summaryRequest?: { source: string }
      /** Si se debe enviar texto al chat real para que el IA lo procese */
      sendToChat?: string
    }

export type AssistantDocumentAction = {
  documentType: string
  title: string
  content: string
}

/** Extensiones de documento soportadas y su tipo */
const DOC_EXTENSION_MAP: Record<string, string> = {
  docx: 'docx',
  doc: 'docx',
  xlsx: 'xlsx',
  xls: 'xlsx',
  txt: 'txt',
  pdf: 'pdf',
}

function detectExtension(title: string): string | null {
  const dot = title.lastIndexOf('.')
  if (dot === -1) return null
  const ext = title.slice(dot + 1).toLowerCase()
  return DOC_EXTENSION_MAP[ext] ?? null
}

function formatDocExtensionLabel(ext: string | null): string {
  if (!ext) return '.docx'
  const labelMap: Record<string, string> = {
    docx: '.docx',
    xlsx: '.xlsx',
    txt: '.txt',
    pdf: '.pdf',
  }
  return labelMap[ext] ?? `.${ext}`
}

export function parseSlashCommand(text: string): SlashCommandResult {
  const trimmed = text.trim()

  // ── /buscar ──────────────────────────────────────────────────

  if (trimmed.startsWith('/buscar ')) {
    const query = trimmed.slice(8).trim()
    if (!query) {
      return {
        handled: true,
        reply: 'Uso: `/buscar texto` — buscaré información en internet sobre el tema que indiques.',
      }
    }
    return {
      handled: true,
      reply: `Buscando en internet: «${query}»…`,
      webSearchQuery: query,
    }
  }

  // ── /agenda ──────────────────────────────────────────────────

  if (trimmed === '/agenda' || trimmed === '/agenda hoy') {
    return {
      handled: true,
      reply: 'Consultando tu agenda de hoy…',
      agendaRequest: 'today',
    }
  }

  if (trimmed.startsWith('/agenda ')) {
    return {
      handled: true,
      reply: 'Uso: `/agenda` o `/agenda hoy` para ver tus eventos del día en Google Calendar.',
    }
  }

  // ── /recordar ────────────────────────────────────────────────

  if (trimmed.startsWith('/recordar ')) {
    const body = trimmed.slice(10).trim()
    const parsedReminder = parseReminderBody(body)
    if (!parsedReminder) {
      return {
        handled: true,
        reply:
          'Uso: `/recordar "texto" en X minutos/horas/días` o `/recordar "texto" a las HH:MM`.',
      }
    }
    return {
      handled: true,
      reply: 'Guardando recordatorio…',
      reminderRequest: {
        text: parsedReminder.text,
        dueAtIso: parsedReminder.dueAt.toISOString(),
      },
    }
  }

  // ── /traducir ────────────────────────────────────────────────

  if (trimmed.startsWith('/traducir ')) {
    const body = trimmed.slice(10).trim()
    if (!body) {
      return {
        handled: true,
        reply:
          'Uso: `/traducir "texto" al idioma` — por ejemplo: `/traducir "Hello world" al español`',
      }
    }

    const parsedTranslation = parseTranslateBody(body)
    if (!parsedTranslation) {
      return {
        handled: true,
        reply:
          'Uso: `/traducir "texto" al idioma` — por ejemplo: `/traducir "Hello world" al español`',
      }
    }

    return {
      handled: true,
      reply: `Traduciendo al ${parsedTranslation.targetLanguage}…`,
      translationRequest: parsedTranslation,
    }
  }

  // ── /resumir ─────────────────────────────────────────────────

  if (trimmed === '/resumir' || trimmed.startsWith('/resumir ')) {
    const body = trimmed.length === 8 ? '' : trimmed.slice(9).trim()
    if (!body) {
      return {
        handled: true,
        reply:
          'Uso: `/resumir texto` — el asistente resumirá el texto que le indiques.\n\nEjemplo: /resumir [texto largo aquí]',
      }
    }
    return {
      handled: true,
      reply: 'Resumiendo…',
      summaryRequest: { source: body },
    }
  }

  // ── /doc ─────────────────────────────────────────────────────

  if (trimmed.startsWith('/doc ')) {
    const body = trimmed.slice(5).trim()
    if (!body) {
      return {
        handled: true,
        reply:
          'Uso: `/doc Título | contenido` o `/doc Título.ext | contenido`.\n\n' +
          'Extensiones detectadas automáticamente:\n' +
          '  • .docx — Documento Word\n' +
          '  • .xlsx — Hoja de cálculo\n' +
          '  • .txt  — Texto plano\n' +
          '  • .pdf  — PDF\n\n' +
          'Ejemplo: `/doc Reporte mensual.xlsx | Enero: $12,500 | Febrero: $14,200`',
      }
    }
    const pipe = body.indexOf('|')
    const rawTitle = (pipe >= 0 ? body.slice(0, pipe) : body.split('\n')[0] ?? body).trim()
    const content = (pipe >= 0 ? body.slice(pipe + 1) : body.slice(rawTitle.length)).trim() || rawTitle

    if (!rawTitle) {
      return { handled: true, reply: 'Indica un título para el documento.' }
    }

    // Detectar tipo por extensión en el título
    const detectedExt = detectExtension(rawTitle)
    const docType = detectedExt ?? 'docx'
    const extLabel = formatDocExtensionLabel(detectedExt)

    // Limpiar la extensión del título visible
    const cleanTitle = detectedExt
      ? rawTitle.replace(/\.[^.]+$/, '')
      : rawTitle

    return {
      handled: true,
      reply: `Generando documento «${cleanTitle}» (${extLabel}) en tu carpeta DOT Trabajos…`,
      documentRequest: {
        title: cleanTitle,
        content,
        documentType: docType,
      },
    }
  }

  // ── /analizar ────────────────────────────────────────────────

  if (trimmed === '/analizar' || trimmed.startsWith('/analizar ')) {
    const path = trimmed.length <= 9 ? '' : trimmed.slice(10).trim()
    if (!path) {
      return {
        handled: true,
        reply:
          'Uso: `/analizar ruta/archivo.xlsx` — analizaré hojas, columnas, muestra y estadísticas básicas.\n\n' +
          'Ejemplo: `/analizar ~/Desktop/ventas.xlsx`',
      }
    }
    return {
      handled: true,
      reply: `Analizando «${path}»…`,
      sendToChat: `Analiza el archivo Excel "${path}" de mi PC con read_spreadsheet: hojas, columnas, muestra de datos y estadísticas básicas.`,
    }
  }

  // ── /leer ────────────────────────────────────────────────────

  if (trimmed.startsWith('/leer ')) {
    const path = trimmed.slice(6).trim()
    if (!path) {
      return {
        handled: true,
        reply: 'Uso: `/leer ruta/archivo.txt` — leeré el contenido del archivo en tu carpeta DOT.',
      }
    }
    return {
      handled: true,
      reply: `Leyendo «${path}»…`,
      sendToChat: `Lee el archivo "${path}" de mi carpeta de documentos`,
    }
  }

  // ── /escribir ────────────────────────────────────────────────

  if (trimmed.startsWith('/escribir ')) {
    const pipe = trimmed.indexOf('|', 10)
    if (pipe === -1) {
      return {
        handled: true,
        reply: 'Uso: `/escribir ruta/archivo.txt | contenido` — guardaré el contenido en el archivo.',
      }
    }
    const path = trimmed.slice(10, pipe).trim()
    const content = trimmed.slice(pipe + 1).trim()
    if (!path || !content) {
      return {
        handled: true,
        reply: 'Uso: `/escribir ruta/archivo.txt | contenido` — necesito ruta y contenido.',
      }
    }
    return {
      handled: true,
      reply: `Guardando «${path}»…`,
      sendToChat: `Escribe el archivo "${path}" con el siguiente contenido en mi carpeta de documentos:\n\n${content}`,
    }
  }

  // ── /listar ──────────────────────────────────────────────────

  if (trimmed.startsWith('/listar')) {
    const subpath = trimmed.length > 7 ? trimmed.slice(8).trim() : ''
    return {
      handled: true,
      reply: subpath ? `Listando archivos en «${subpath}»…` : 'Listando archivos en tu carpeta DOT…',
      sendToChat: subpath
        ? `Lista los archivos en la carpeta "${subpath}" de mi carpeta de documentos`
        : 'Lista los archivos en mi carpeta de documentos',
    }
  }

  // ── /correo ──────────────────────────────────────────────────

  if (trimmed === '/correo' || trimmed === '/inbox') {
    return {
      handled: true,
      reply: 'Revisando tus correos sin leer…',
      sendToChat:
        'Lista mis correos sin leer de Gmail con gmail_list_unread. Muestra remitente, asunto e ID de cada uno.',
    }
  }

  if (trimmed.startsWith('/correo ')) {
    const query = trimmed.slice(8).trim()
    if (!query) {
      return {
        handled: true,
        reply: 'Uso: `/correo` (sin leer) o `/correo filtro` — p. ej. `/correo from:juan@empresa.com`',
      }
    }
    return {
      handled: true,
      reply: `Buscando correos: «${query}»…`,
      sendToChat: `Busca en Gmail con gmail_search la query «${query}» y lista remitente, asunto e ID.`,
    }
  }

  // ── /responder ───────────────────────────────────────────────

  if (trimmed.startsWith('/responder ')) {
    const body = trimmed.slice(11).trim()
    if (!body) {
      return {
        handled: true,
        reply:
          'Uso: `/responder texto de la respuesta` — responde al último correo sin leer.\n\n' +
          'Ejemplo: `/responder Gracias, recibido. Te confirmo mañana.`',
      }
    }
    return {
      handled: true,
      reply: 'Preparando respuesta al correo…',
      sendToChat:
        `Responde al último correo sin leer de Gmail: primero gmail_list_unread, ` +
        `toma el message_id del primero y usa gmail_auto_reply con body: «${body}». ` +
        `Pide confirmación antes de enviar.`,
    }
  }

  // ── /archivar ────────────────────────────────────────────────

  if (trimmed.startsWith('/archivar ')) {
    const target = trimmed.slice(10).trim()
    if (!target) {
      return {
        handled: true,
        reply:
          'Uso: `/archivar filtro` — archiva correos que coincidan.\n\n' +
          'Ejemplos:\n' +
          '  `/archivar spam`\n' +
          '  `/archivar category:promotions`\n' +
          '  `/archivar from:newsletter@ejemplo.com`',
      }
    }
    const queryMap: Record<string, string> = {
      spam: 'label:spam',
      promociones: 'category:promotions',
      promos: 'category:promotions',
      publicidad: 'category:promotions',
    }
    const normalized = target.toLowerCase()
    const gmailQuery = queryMap[normalized] ?? target
    return {
      handled: true,
      reply: `Archivando correos: «${target}»…`,
      sendToChat:
        `Archiva correos de Gmail: gmail_search con query «${gmailQuery}», resume cuántos hay, ` +
        `pide confirmación y luego gmail_archive por cada message_id con confirm:true.`,
    }
  }

  if (trimmed === '/archivar') {
    return {
      handled: true,
      reply: 'Uso: `/archivar spam` o `/archivar from:remitente@…`',
    }
  }

  // ── /adjuntos ──────────────────────────────────────────────────

  if (trimmed.startsWith('/adjuntos')) {
    const rest = trimmed.length > 9 ? trimmed.slice(10).trim() : ''
    const folder = rest || '~/Desktop'
    return {
      handled: true,
      reply: 'Descargando adjuntos del correo…',
      sendToChat:
        `Descarga adjuntos de Gmail al Escritorio: gmail_list_unread o gmail_search, ` +
        `toma message_id del correo pedido (o el primero con adjuntos) y usa ` +
        `gmail_get_attachments con folder «${folder}».`,
    }
  }

  return { handled: false }
}

export function parseAssistantDocumentAction(text: string): AssistantDocumentAction | null {
  const parsed = parseFirstJsonObject(text)
  if (!parsed || typeof parsed !== 'object') return null
  const data = parsed as Record<string, unknown>
  if (String(data.action || '').toLowerCase() !== 'create_document') return null

  const mappedType = normalizeDocumentType(String(data.type || ''))
  const title = String(data.title || '').trim()
  const content = String(data.content || '').trim()
  if (!mappedType || !title || !content) return null

  return {
    documentType: mappedType,
    title,
    content,
  }
}

function parseFirstJsonObject(raw: string): unknown {
  const text = raw.trim()
  if (!text) return null

  const fenced = text.match(/```(?:json)?\s*([\s\S]*?)```/i)
  if (fenced?.[1]) {
    try {
      return JSON.parse(fenced[1].trim())
    } catch {
      // continua con fallback
    }
  }

  try {
    return JSON.parse(text)
  } catch {
    // fallback: extraer bloque entre primer { y último }
  }

  const start = text.indexOf('{')
  const end = text.lastIndexOf('}')
  if (start < 0 || end <= start) return null
  const candidate = text.slice(start, end + 1)
  try {
    return JSON.parse(candidate)
  } catch {
    return null
  }
}

function normalizeDocumentType(rawType: string): string | null {
  const clean = rawType.trim().toLowerCase().replace(/^\./, '')
  if (!clean) return null
  if (clean === 'doc') return 'docx'
  if (clean === 'xls') return 'xlsx'
  if (clean === 'markdown') return 'txt'
  if (clean === 'text') return 'txt'
  if (clean === 'word') return 'docx'
  if (clean === 'excel') return 'xlsx'
  return DOC_EXTENSION_MAP[clean] ?? null
}

function parseTranslateBody(raw: string): { text: string; targetLanguage: string } | null {
  const input = raw.trim()
  if (!input) return null

  const quotedMatch = input.match(/^(?:"([^"]+)"|'([^']+)'|“([^”]+)”)\s+al\s+(.+)$/i)
  if (quotedMatch) {
    const text = (quotedMatch[1] ?? quotedMatch[2] ?? quotedMatch[3] ?? '').trim()
    const targetLanguage = quotedMatch[4]?.trim() ?? ''
    if (!text || !targetLanguage) return null
    return { text, targetLanguage }
  }

  const splitByLanguage = input.split(/\s+al\s+/i)
  if (splitByLanguage.length >= 2) {
    const targetLanguage = splitByLanguage.pop()?.trim() ?? ''
    const text = splitByLanguage.join(' al ').trim()
    if (!text || !targetLanguage) return null
    return { text, targetLanguage }
  }

  if (/\s+al\s*$/i.test(input)) {
    return null
  }

  return {
    text: input,
    targetLanguage: 'español',
  }
}

function parseReminderBody(
  raw: string,
  now: Date = new Date(),
): { text: string; dueAt: Date } | null {
  const input = raw.trim()
  if (!input) return null

  // /recordar "mensaje" en 30 minutos
  const relativeMatch = input.match(
    /^["“]?([^"”]+)["”]?\s+en\s+(\d+)\s*(minuto|minutos|min|hora|horas|h|dia|dias|días|d)$/i,
  )
  if (relativeMatch) {
    const reminderText = relativeMatch[1].trim()
    const amount = Number.parseInt(relativeMatch[2], 10)
    const unit = relativeMatch[3].toLowerCase()
    if (!reminderText || Number.isNaN(amount) || amount <= 0) return null
    const minutesMultiplier = unit.startsWith('h')
      ? 60
      : unit.startsWith('d')
        ? 60 * 24
        : 1
    const dueAt = new Date(now.getTime() + amount * minutesMultiplier * 60_000)
    return { text: reminderText, dueAt }
  }

  // /recordar "mensaje" a las 14:30
  const atTimeMatch = input.match(/^["“]?([^"”]+)["”]?\s+a\s+las\s+(\d{1,2}):(\d{2})$/i)
  if (atTimeMatch) {
    const reminderText = atTimeMatch[1].trim()
    const hour = Number.parseInt(atTimeMatch[2], 10)
    const minute = Number.parseInt(atTimeMatch[3], 10)
    if (!reminderText || hour < 0 || hour > 23 || minute < 0 || minute > 59) return null

    const dueAt = new Date(now)
    dueAt.setHours(hour, minute, 0, 0)
    if (dueAt.getTime() <= now.getTime()) {
      dueAt.setDate(dueAt.getDate() + 1)
    }
    return { text: reminderText, dueAt }
  }

  return null
}
