import { stripAnsi } from '@/features/onboarding/lib/openclawLogQr'

/** Línea opcional que un adaptador externo podría inyectar (extensible). */
const SENTINEL_RE = /DOT_WHATSAPP_QR:\s*([^\n\r]+)/
const JSON_QR_RE = /"qr"\s*:\s*"((?:[^"\\]|\\.)*)"/g

function unescapeLooseJsonQrValue(s: string): string {
  return s.replace(/\\n/g, '\n').replace(/\\r/g, '\r').replace(/\\"/g, '"').replace(/\\\\/g, '\\')
}

/**
 * Intenta obtener el string de pairing que Baileys usa para el QR.
 * Open Claw solo imprime arte ASCII en consola; con `--verbose` a veces aparece JSON con `"qr"`.
 */
export function tryExtractRawWhatsAppQr(raw: string): string | null {
  const text = stripAnsi(raw)

  const sentinel = SENTINEL_RE.exec(text)
  if (sentinel?.[1]) {
    const v = sentinel[1].trim()
    if (v.length >= 32) return v
  }

  // WA-10: fallback robusto sobre todo el buffer acumulado.
  for (const match of text.matchAll(JSON_QR_RE)) {
    const candidate = unescapeLooseJsonQrValue(match[1] ?? "").trim()
    if (candidate.length >= 32) return candidate
  }

  const lines = text.split(/\r?\n/)

  for (const line of lines) {
    const t = line.trim()
    if (!t.includes('"qr"')) continue

    const objStart = t.indexOf('{')
    if (objStart >= 0) {
      try {
        const o = JSON.parse(t.slice(objStart)) as { qr?: unknown }
        if (typeof o.qr === 'string' && o.qr.length >= 32) return o.qr
      } catch {
        /* continuar */
      }
    }

    const m = t.match(/"qr"\s*:\s*"((?:[^"\\]|\\.)*)"/)
    if (m?.[1]) {
      const inner = unescapeLooseJsonQrValue(m[1])
      if (inner.length >= 32) return inner
    }
  }

  const anchorIdx = Math.max(
    text.lastIndexOf('Waiting for WhatsApp'),
    text.lastIndexOf('WhatsApp QR received'),
    text.lastIndexOf('Linked Devices'),
  )
  const window = anchorIdx >= 0 ? text.slice(anchorIdx) : text

  let best: string | null = null

  for (const line of window.split(/\r?\n/)) {
    const t = line.trim()
    if (t.length < 100 || t.length > 12000) continue
    if (!/^[\x20-\x7E]+$/.test(t)) continue
    const spaces = (t.match(/\s/g) ?? []).length
    if (spaces / t.length > 0.04) continue
    const tokenish = (t.match(/[A-Za-z0-9+/=_-]/g) ?? []).length
    const ratio = tokenish / t.length
    if (ratio < 0.72) continue
    if (t.includes('http:') || t.includes('https:')) continue
    if (!best || t.length > best.length) best = t
  }

  return best
}
