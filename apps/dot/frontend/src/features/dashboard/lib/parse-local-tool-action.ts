/**
 * Parser de acciones local-tool desde respuestas del asistente.
 *   {"action":"local_tool","operation":"readFile","path":"notas.txt"}
 *   {"action":"local_tool","operation":"writeFile","path":"notas.txt","content":"texto"}
 *   {"action":"local_tool","operation":"downloadUrl","path":"~/Desktop/x.pdf","url":"https://..."}
 *   {"action":"local_tool","operation":"listFiles","path":""}
 *   {"action":"local_tool","operation":"deleteFile","path":"temporal.txt"}
 */

import { translateErrorMessage } from '@/lib/error-messages'

export type LocalToolOperation =
  | 'readFile'
  | 'writeFile'
  | 'listFiles'
  | 'deleteFile'
  | 'downloadUrl'

export type LocalToolAction = {
  operation: LocalToolOperation
  path: string
  content?: string
  url?: string
}

/** Operaciones que requieren contenido */
const OPERATIONS_WITH_CONTENT: ReadonlySet<LocalToolOperation> = new Set(['writeFile'])

/** Operaciones válidas */
const VALID_OPERATIONS: ReadonlySet<string> = new Set([
  'readFile',
  'writeFile',
  'listFiles',
  'deleteFile',
  'downloadUrl',
  'downloadUrlToDesktop',
  'download_url_to_desktop',
])

const BINARY_WRITE_EXTS = [
  '.pdf',
  '.png',
  '.jpg',
  '.jpeg',
  '.gif',
  '.webp',
  '.zip',
  '.exe',
  '.docx',
  '.xlsx',
  '.pptx',
] as const

const HTTP_URL_RE = /https?:\/\/[^\s<>"')\]]+/i

export function isBinaryLocalPath(path: string): boolean {
  const lower = (path || '').toLowerCase()
  return BINARY_WRITE_EXTS.some((ext) => lower.endsWith(ext))
}

export function extractHttpUrl(text: string): string | null {
  const m = HTTP_URL_RE.exec(text || '')
  if (!m) return null
  return m[0].replace(/[.,;:)]+$/, '')
}

/**
 * Extrae la primera acción local_tool de un texto del asistente.
 * Retorna null si no encuentra ninguna acción válida.
 */
export function parseLocalToolAction(text: string): LocalToolAction | null {
  const fromToolCalls = parseDownloadFromToolCalls(text)
  if (fromToolCalls) return fromToolCalls

  const parsed = extractFirstJsonObject(text)
  if (!parsed || typeof parsed !== 'object') return null

  const data = parsed as Record<string, unknown>

  // Validar que sea una acción local_tool
  if (String(data.action ?? '').toLowerCase() !== 'local_tool') return null

  const rawOperation = String(data.operation ?? '').trim()
  if (!rawOperation || !VALID_OPERATIONS.has(rawOperation)) return null

  const operation = normalizeOperation(rawOperation)
  const rawPath = String(data.path ?? '').trim()
  const content = typeof data.content === 'string' ? data.content : undefined
  const url = typeof data.url === 'string' ? data.url.trim() : undefined

  if (operation === 'downloadUrl') {
    if (!url) return null
    return { operation, path: rawPath, url }
  }

  // writeFile necesita contenido
  if (OPERATIONS_WITH_CONTENT.has(operation) && (content === undefined || content === '')) {
    return null
  }

  return { operation, path: rawPath, content, url }
}

function normalizeOperation(raw: string): LocalToolOperation {
  if (
    raw === 'downloadUrl' ||
    raw === 'downloadUrlToDesktop' ||
    raw === 'download_url_to_desktop'
  ) {
    return 'downloadUrl'
  }
  return raw as LocalToolOperation
}

function parseDownloadFromToolCalls(text: string): LocalToolAction | null {
  const parsed = extractFirstJsonObject(text)
  if (!parsed || typeof parsed !== 'object') return null
  const data = parsed as Record<string, unknown>
  const calls = data.tool_calls
  if (!Array.isArray(calls)) return null
  for (const raw of calls) {
    if (!raw || typeof raw !== 'object') continue
    const call = raw as Record<string, unknown>
    const name = String(call.name ?? '').trim()
    if (
      name !== 'download_url_to_desktop' &&
      name !== 'downloadUrl' &&
      name !== 'downloadUrlToDesktop'
    ) {
      continue
    }
    const args =
      typeof call.arguments === 'object' && call.arguments
        ? (call.arguments as Record<string, unknown>)
        : {}
    const url = String(args.url ?? '').trim()
    if (!url) continue
    const path = String(args.path ?? '').trim()
    return { operation: 'downloadUrl', path, url }
  }
  return null
}

/**
 * Extrae el primer objeto JSON de un texto, manejando bloques de código y texto suelto.
 */
function extractFirstJsonObject(raw: string): unknown {
  const text = raw.trim()
  if (!text) return null

  // Intentar extraer de bloque de código ```json ... ```
  const fenced = text.match(/```(?:json)?\s*([\s\S]*?)```/i)
  if (fenced?.[1]) {
    try {
      return JSON.parse(fenced[1].trim())
    } catch {
      // Continúa con fallback
    }
  }

  // Intentar parsear el texto completo
  try {
    return JSON.parse(text)
  } catch {
    // Fallback: extraer bloque entre primer { y último }
  }

  const start = text.indexOf('{')
  if (start < 0) return null
  const end = text.lastIndexOf('}')
  if (end > start) {
    try {
      return JSON.parse(text.slice(start, end + 1))
    } catch {
      // continuar a repair
    }
  }
  // JSON truncado (sin `}` final) — cerrar lo mínimo
  return repairTruncatedJsonObject(text.slice(start))
}

function repairTruncatedJsonObject(chunk: string): unknown {
  if (!/"action"/i.test(chunk) && !/"tool_calls"/i.test(chunk)) return null
  let candidate = chunk.trimEnd()
  let inStr = false
  let escape = false
  let depth = 0
  for (const ch of candidate) {
    if (inStr) {
      if (escape) escape = false
      else if (ch === '\\') escape = true
      else if (ch === '"') inStr = false
      continue
    }
    if (ch === '"') inStr = true
    else if (ch === '{') depth += 1
    else if (ch === '}') depth -= 1
  }
  if (inStr) candidate += '"'
  if (depth > 0) candidate += '}'.repeat(depth)
  try {
    return JSON.parse(candidate)
  } catch {
    return null
  }
}

/**
 * No alterar JSON local_tool aquí: DashboardShell (o el backend) debe ejecutarlo.
 * Solo suavizar create_document crudo para no dejar action JSON ilegible.
 */
export function humanizeLocalToolJsonIfPresent(text: string): string {
  // local_tool: dejar intacto para que el fallback IPC escriba el archivo
  if (parseLocalToolAction(text)) {
    return text
  }

  // create_document crudo: mostrar contenido mientras backend/fallback guarda
  if (/"action"\s*:\s*"create_document"/i.test(text)) {
    try {
      const start = text.indexOf('{')
      const end = text.lastIndexOf('}')
      if (start >= 0 && end > start) {
        const data = JSON.parse(text.slice(start, end + 1)) as {
          content?: string
        }
        const content = typeof data.content === 'string' ? data.content.trim() : ''
        if (content) {
          const preview = content.length > 2500 ? `${content.slice(0, 2500)}…` : content
          return `${preview}\n\n⏳ Guardando archivo en tu Escritorio…`
        }
      }
    } catch {
      // fallthrough
    }
  }

  return text
}
function _friendlyPath(path: string): string {
  if (!path) return 'tu carpeta DOT'
  if (path === '~') return 'tu carpeta de inicio'
  if (path === '~/Desktop') return 'tu Escritorio'
  if (path === '~/Downloads') return 'tus Descargas'
  if (path === '~/Documents') return 'tus Documentos'
  if (path.startsWith('~/Desktop/')) return 'tu Escritorio (' + path.slice(10) + ')'
  if (path.startsWith('~/Downloads/')) return 'tus Descargas (' + path.slice(12) + ')'
  if (path.startsWith('~/Documents/')) return 'tus Documentos (' + path.slice(12) + ')'
  if (path.startsWith('~/')) return path.slice(2)
  return path
}

/**
 * Traduce una operación local-tool a un mensaje legible para mostrar al usuario.
 */
export function formatLocalToolResult(
  operation: LocalToolOperation,
  path: string,
  result: {
    ok: boolean
    content?: string
    error?: string
    files?: Array<{ name: string; isDirectory: boolean }>
    bytes?: number
  },
): string {
  if (!result.ok) {
    const friendly = translateErrorMessage(
      result.error ?? 'Error desconocido',
      `No pude ${operationLabel(operation)}. Intenta de nuevo.`,
    )
    return `❌ ${friendly}`
  }

  switch (operation) {
    case 'readFile': {
      const friendlyName = _friendlyPath(path)
      return `📄 Contenido de ${friendlyName}:\n\n\`\`\`\n${result.content ?? ''}\n\`\`\``
    }
    case 'writeFile': {
      const friendlyName = _friendlyPath(path)
      return `✅ Archivo guardado en ${friendlyName}.`
    }
    case 'downloadUrl': {
      const friendlyName = _friendlyPath(path || '~/Desktop')
      const size =
        typeof result.bytes === 'number' && result.bytes > 0
          ? ` (${result.bytes} bytes)`
          : ''
      return `✅ Descarga lista en ${friendlyName}${size}.`
    }
    case 'listFiles': {
      const items = result.files ?? []
      const friendlyName = _friendlyPath(path)
      if (items.length === 0) {
        return `📁 ${friendlyName} está vacío.`
      }
      const listing = items
        .map((f) => (f.isDirectory ? `📁 ${f.name}/` : `📄 ${f.name}`))
        .join('\n')
      return `📁 ${friendlyName}:\n\n${listing}`
    }
    case 'deleteFile': {
      const friendlyName = _friendlyPath(path)
      return `🗑️ Archivo eliminado: ${friendlyName}.`
    }
    default:
      return `✅ Operación completada.`
  }
}

function operationLabel(op: LocalToolOperation): string {
  const labels: Record<LocalToolOperation, string> = {
    readFile: 'leer archivo',
    writeFile: 'escribir archivo',
    listFiles: 'listar archivos',
    deleteFile: 'eliminar archivo',
    downloadUrl: 'descargar archivo',
  }
  return labels[op] ?? 'ejecutar operación'
}
