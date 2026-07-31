/**
 * Convierte lineas RAW del QR (con codigos ANSI) a una data URL via canvas.
 * Reemplaza dangerouslySetInnerHTML por <img> seguro.
 *
 * OpenClaw / Baileys dibujan el QR usando codigos SGR:
 * - ESC[47m = fondo blanco (celda clara)
 * - ESC[40m = fondo negro (celda oscura)
 * - ESC[0m  = reset
 */

const ANSI_ESCAPE = String.fromCharCode(27)
const ANSI_SPLIT_RE = new RegExp(`${ANSI_ESCAPE}\\[`, 'g')

type Cell = { bg: string; fg: string; char: string }

function parseAnsiToCells(rawLines: string[]): { cells: Cell[][]; cols: number; rows: number } {
  const rows: Cell[][] = []
  let maxCols = 0

  for (const raw of rawLines) {
    const parts = raw.split(ANSI_SPLIT_RE)
    if (parts.length === 1 && parts[0] === '') continue

    let currentBg = '#ffffff'
    let currentFg = '#000000'
    const row: Cell[] = []

    for (let i = 0; i < parts.length; i++) {
      const part = parts[i]
      if (i === 0 && part.length > 0) {
        for (const ch of part) row.push({ bg: currentBg, fg: currentFg, char: ch })
        continue
      }
      const sgrMatch = part.match(/^(\d+(?:;\d+)*)m/)
      if (sgrMatch) {
        const codes = sgrMatch[1].split(';').map(Number)
        const rest = part.slice(sgrMatch[0].length)
        for (const code of codes) {
          if (code === 0) {
            currentBg = '#ffffff'
            currentFg = '#000000'
          } else if (code >= 40 && code <= 49) {
            currentBg = code === 47 ? '#ffffff' : code === 40 ? '#000000' : '#888888'
            currentFg = code === 40 ? '#ffffff' : '#000000'
          }
        }
        for (const ch of rest) row.push({ bg: currentBg, fg: currentFg, char: ch })
      } else {
        for (const ch of part) row.push({ bg: currentBg, fg: currentFg, char: ch })
      }
    }
    if (row.length > 0) {
      maxCols = Math.max(maxCols, row.length)
      rows.push(row)
    }
  }
  return { cells: rows, cols: maxCols, rows: rows.length }
}

/**
 * Dibuja el QR ANSI en un canvas y retorna una data URL.
 * Cada celda se representa como un pixel escalado 4x.
 * Fallback: retorna string vacío si no hay canvas disponible (SSR/test).
 */
export function ansiQrToDataUrl(rawLines: string[], cellSize: number = 4): string {
  if (typeof document === 'undefined') return ''

  const { cells, cols, rows } = parseAnsiToCells(rawLines)
  if (rows === 0 || cols === 0) return ''

  const canvas = document.createElement('canvas')
  canvas.width = cols * cellSize
  canvas.height = rows * cellSize
  const ctx = canvas.getContext('2d')
  if (!ctx) return ''

  for (let y = 0; y < rows; y++) {
    const row = cells[y]
    for (let x = 0; x < cols; x++) {
      const cell = row[x]
      if (!cell) continue
      ctx.fillStyle = cell.bg || '#ffffff'
      ctx.fillRect(x * cellSize, y * cellSize, cellSize, cellSize)
    }
  }

  return canvas.toDataURL('image/png')
}

export { parseAnsiToCells }
