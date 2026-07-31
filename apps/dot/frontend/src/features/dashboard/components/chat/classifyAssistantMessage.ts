/** Clasifica mensajes del asistente para cards estructuradas en el chat. */

export type ChatStructuredCard =
  | {
      kind: 'generated_files'
      title: string
      files: Array<{ name: string; path?: string }>
      body?: string
    }
  | {
      kind: 'error'
      title: string
      summary: string
      details?: string
    }

const DOC_GENERATED_RE =
  /Documento generado(?: automáticamente)?:\s*(.+?)\s+en\s+(.+)/i
const FILE_LINE_RE = /(?:^|\n)(?:📄|📎)?\s*([^\n]+\.(?:docx|pdf|txt|md|csv|xlsx|png|jpg|jpeg))\s*(?:\n|$)/gi

export function classifyAssistantMessage(text: string): ChatStructuredCard | null {
  const trimmed = text.trim()
  if (!trimmed) return null

  const isError =
    trimmed.startsWith('❌') ||
    /Error al ejecutar/i.test(trimmed) ||
    /No se pudo/i.test(trimmed)

  if (isError) {
    const withoutIcon = trimmed.replace(/^❌\s*/, '')
    const [firstLine, ...rest] = withoutIcon.split('\n')
    const details = rest.join('\n').trim()
    return {
      kind: 'error',
      title: 'Error de ejecución',
      summary: firstLine || 'Ocurrió un error.',
      details: details || undefined,
    }
  }

  const docMatch = trimmed.match(DOC_GENERATED_RE)
  if (docMatch) {
    return {
      kind: 'generated_files',
      title: 'Archivos generados',
      files: [{ name: docMatch[1].trim(), path: docMatch[2].trim() }],
    }
  }

  const exportMatch = trimmed.match(
    /Conversación exportada en \w+:\s*(.+?)\s+en\s+(.+)/i,
  )
  if (exportMatch) {
    return {
      kind: 'generated_files',
      title: 'Archivos generados',
      files: [{ name: exportMatch[1].trim(), path: exportMatch[2].trim() }],
    }
  }

  const listoMatch = trimmed.match(/Listo:\s*(.+?)\s+guardado en\s+(.+)/i)
  if (listoMatch) {
    return {
      kind: 'generated_files',
      title: 'Archivos generados',
      files: [{ name: listoMatch[1].trim(), path: listoMatch[2].trim() }],
    }
  }

  if (/Archivos generados|archivo generado|exportad/i.test(trimmed)) {
    const files: Array<{ name: string; path?: string }> = []
    let m: RegExpExecArray | null
    const re = new RegExp(FILE_LINE_RE.source, FILE_LINE_RE.flags)
    while ((m = re.exec(trimmed)) !== null) {
      files.push({ name: m[1].trim() })
    }
    if (files.length > 0) {
      return {
        kind: 'generated_files',
        title: 'Archivos generados',
        files,
        body: trimmed,
      }
    }
  }

  // Pipeline success with output that mentions a file path
  if (/Pipeline ejecutado/i.test(trimmed) && /\.(docx|pdf|txt|md)/i.test(trimmed)) {
    const files: Array<{ name: string; path?: string }> = []
    const pathMatch = trimmed.match(/([^\s]+\.(?:docx|pdf|txt|md))/i)
    if (pathMatch) {
      const full = pathMatch[1]
      const name = full.split(/[/\\]/).pop() || full
      files.push({ name, path: full })
      return {
        kind: 'generated_files',
        title: 'Archivos generados',
        files,
        body: trimmed.replace(/^✅\s*/, ''),
      }
    }
  }

  return null
}
