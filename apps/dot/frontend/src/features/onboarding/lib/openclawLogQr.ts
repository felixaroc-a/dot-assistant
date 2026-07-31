/** Quita secuencias ANSI (incl. colores de fondo del QR de Open Claw). */
const ANSI_ESCAPE = String.fromCharCode(27)

export function stripAnsi(text: string): string {
  const esc = ANSI_ESCAPE
  const bel = String.fromCharCode(7)
  const csi = String.fromCharCode(155)
  return text
    .replace(new RegExp(`${esc}\\[[0-9;?]*[A-Za-z]`, 'g'), '')
    .replace(new RegExp(`${csi}\\[[0-9;?]*[A-Za-z]`, 'g'), '')
    .replace(new RegExp(`${esc}\\][\\s\\S]*?${bel}`, 'g'), '')
}

export type OpenClawQrVisual =
  | { kind: 'image-data-url'; src: string }
  | { kind: 'ascii'; lines: string[] }

const DATA_IMAGE_RE = /data:image\/(?:png|jpeg|gif|webp);base64,[A-Za-z0-9+/=]+/

/**
 * Detecta si una linea forma parte del QR de OpenClaw.
 *
 * OpenClaw 2026.6.11 dibuja el QR de DOS formas:
 * 1. Con caracteres de bloque Unicode (▄▀█)  -> versiones anteriores
 * 2. Con ANSI background-color + espacios    -> version nueva
 *
 * Para el caso 2, detectamos lineas largas (>55 chars) que:
 * - Contienen secuencias ANSI SGR \x1b[NNm
 * - Despues de stripAnsi, son solo espacios o tienen pocos caracteres visibles
 */
function isQrLine(line: string): boolean {
  const t = line.replace(/\r$/, '')

  // Caso 1: caracteres de bloque Unicode
  let blockCharCount = 0
  for (let i = 0; i < t.length; i++) {
    const ch = t[i]!
    if (
      ch === ' ' ||
      ch === '▄' ||
      ch === '▀' ||
      ch === '█' ||
      ch === '·' ||
      ch === '.' ||
      ch === '#' ||
      (ch >= '\u2580' && ch <= '\u259F')
    ) {
      blockCharCount += 1
    }
  }
  if (t.length >= 10 && blockCharCount / t.length >= 0.78) {
    return true
  }

  // Caso 2: ANSI background-color QR (OpenClaw 2026.6.11+)
  // Lineas tipicas: ESC[47mESC[30m (muchos espacios) ESC[0m
  // Despues de stripAnsi son espacios con longitud > 55
  const stripped = stripAnsi(t)
  if (stripped.length >= 55) {
    // Verificar que tenga secuencias SGR de color de fondo
    // Busca patrones como ESC[4Xm o ESC[10Xm
    const sgrPattern = new RegExp(`${ANSI_ESCAPE}\\[[0-9;]*m`, 'g')
    const sgrMatches = t.match(sgrPattern)
    if (sgrMatches && sgrMatches.length >= 2) {
      // Debe tener al menos algunos codigos de color de fondo (40-49)
      const bgColorCodes = sgrMatches.filter((m) => /4\d+m?$/.test(m.replace(`${ANSI_ESCAPE}[`, '')))
      if (bgColorCodes.length >= 1) {
        return true
      }
    }
  }

  return false
}

/** Detecta el bloque más largo de líneas del QR que Open Claw imprime en consola. */
export function extractAsciiQrBlock(text: string): string[] | null {
  const lines = text.split(/\r?\n/)
  let best: string[] | null = null
  let current: string[] = []

  const flush = () => {
    if (current.length >= 5) {
      if (!best || current.length > best.length) best = [...current]
    }
    current = []
  }

  for (const line of lines) {
    const trimmedEnd = line.replace(/\s+$/, '')
    if (trimmedEnd === '' && current.length > 0) {
      current.push(line)
      continue
    }
    if (isQrLine(line)) {
      current.push(line)
    } else {
      flush()
    }
  }
  flush()
  return best
}

function extractDataImageUrl(text: string): string | null {
  const m = text.match(DATA_IMAGE_RE)
  return m?.[0] ?? null
}

export function extractBestQrFromLog(raw: string): OpenClawQrVisual | null {
  const clean = stripAnsi(raw)
  const dataUrl = extractDataImageUrl(clean)
  if (dataUrl) return { kind: 'image-data-url', src: dataUrl }

  const ascii = extractAsciiQrBlock(raw)
  if (ascii) {
    const normalized = ascii.map((ln) => stripAnsi(ln).replace(/\s+$/, ''))
    return { kind: 'ascii', lines: normalized }
  }

  return null
}
