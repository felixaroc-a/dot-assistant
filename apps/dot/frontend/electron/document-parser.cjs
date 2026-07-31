'use strict'

/**
 * document-parser.cjs — T10: Pipeline lectura PDF/CV + generación DOCX (P2.2)
 *
 * Extrae texto de archivos PDF, DOCX y TXT en el proceso principal de Electron.
 * Soporta tanto ruta de archivo como buffer de datos (base64).
 * El archivo NUNCA sale del PC (Manual Maestro §6.5).
 *
 * DOCX writing: mammoth solo lee. La generación de DOCX con imágenes se
 * delega al backend (python-docx) vía API REST. Esta función actúa como
 * fachada local para que el renderer no tenga que conocer la URL del backend.
 *
 * PDF: unpdf (build serverless de PDF.js) — sin @napi-rs/canvas ni DOMMatrix.
 * DOCX lectura: mammoth. DOCX escritura: delegado a backend python-docx.
 * Texto: fs.
 *
 * Seguridad: toda ruta de archivo se valida contra sandbox-resolver.cjs.
 * Solo se permite lectura de archivos dentro de Documents, Desktop,
 * Downloads y DOT sandbox. Path traversal (../../Windows/System32) es
 * bloqueado en la capa de validación.
 *
 * Límites:
 * - Tamaño máximo de archivo: 5 MB
 * - Texto extraído máximo: 50,000 caracteres (para no saturar el LLM)
 */

const fs = require('node:fs')
const path = require('node:path')
const { resolveSafePath } = require('./sandbox-resolver.cjs')

const MAX_FILE_SIZE = 5 * 1024 * 1024 // 5 MB
const MAX_TEXT_LENGTH = 50000 // caracteres

/**
 * Parsea un documento desde ruta de archivo.
 * @param {string} filePath
 * @param {string} mimeType
 * @returns {Promise<{ ok: true; text: string } | { ok: false; error: string }>}
 */
async function parse(filePath, mimeType) {
  if (!filePath || typeof filePath !== 'string') {
    return { ok: false, error: 'Ruta de archivo no proporcionada' }
  }

  // C1 (path traversal): validar que la ruta esté dentro del sandbox.
  // Sin esta validación, un renderer podría leer cualquier archivo del sistema
  // enviando ../../Windows/System32/SAM o ../../.ssh/id_rsa.
  const resolved = resolveSafePath(filePath)
  if (!resolved) {
    return { ok: false, error: 'Ruta de archivo no permitida o inválida.' }
  }

  if (!fs.existsSync(resolved)) {
    return { ok: false, error: 'El archivo no existe en disco' }
  }

  try {
    const stat = fs.statSync(resolved)
    if (stat.size > MAX_FILE_SIZE) {
      return { ok: false, error: `El archivo excede el límite de 5 MB (tamaño: ${(stat.size / (1024 * 1024)).toFixed(1)} MB)` }
    }
  } catch {
    return { ok: false, error: 'No se pudo leer la información del archivo' }
  }

  return extractTextFromSource({ filePath: resolved }, mimeType)
}

/**
 * Parsea un documento desde datos binarios (base64).
 * @param {string} base64Data - Datos del archivo en base64
 * @param {string} mimeType
 * @returns {Promise<{ ok: true; text: string } | { ok: false; error: string }>}
 */
async function parseFromData(base64Data, mimeType) {
  if (!base64Data || typeof base64Data !== 'string') {
    return { ok: false, error: 'Datos del archivo no proporcionados' }
  }

  const buffer = Buffer.from(base64Data, 'base64')
  if (buffer.length > MAX_FILE_SIZE) {
    return { ok: false, error: `El archivo excede el límite de 5 MB (tamaño: ${(buffer.length / (1024 * 1024)).toFixed(1)} MB)` }
  }

  return extractTextFromSource({ buffer }, mimeType)
}

/**
 * @param {{ filePath?: string; buffer?: Buffer }} source
 * @param {string} mimeType
 * @returns {Promise<{ ok: true; text: string } | { ok: false; error: string }>}
 */
async function extractTextFromSource(source, mimeType) {
  try {
    let text = ''

    if (mimeType === 'application/pdf') {
      const buffer = source.buffer ?? fs.readFileSync(source.filePath)
      text = await extractPdfText(buffer)
    } else if (mimeType === 'application/vnd.openxmlformats-officedocument.wordprocessingml.document') {
      text = await extractDocxText(source)
    } else if (mimeType === 'text/plain' || mimeType === 'text/csv') {
      text = source.buffer
        ? source.buffer.toString('utf-8')
        : fs.readFileSync(source.filePath, 'utf-8')
    } else {
      return { ok: false, error: `Tipo de archivo no soportado: ${mimeType}` }
    }

    if (!text || !text.trim()) {
      return { ok: false, error: 'No se pudo extraer texto del documento. El archivo podría estar vacío o protegido.' }
    }

    const truncated = text.length > MAX_TEXT_LENGTH
      ? text.slice(0, MAX_TEXT_LENGTH) + '\n\n[Texto truncado — primeros 50,000 caracteres]'
      : text

    return { ok: true, text: truncated }
  } catch (err) {
    const message = err && typeof err === 'object' && 'message' in err
      ? String(err.message).slice(0, 300)
      : 'Error al extraer texto'
    return { ok: false, error: message }
  }
}

/**
 * Extrae texto con unpdf (PDF.js serverless). No usa @napi-rs/canvas.
 * @param {Buffer} buffer
 * @returns {Promise<string>}
 */
async function extractPdfText(buffer) {
  const { extractText } = await import('unpdf')
  const { text } = await extractText(new Uint8Array(buffer), { mergePages: true })
  return typeof text === 'string' ? text : (text || []).join('\n')
}

/**
 * @param {{ filePath?: string; buffer?: Buffer }} source
 * @returns {Promise<string>}
 */
async function extractDocxText(source) {
  const mammoth = require('mammoth')
  if (source.buffer) {
    // mammoth acepta buffer; evita archivo temporal en drag-drop
    const result = await mammoth.extractRawText({ buffer: source.buffer })
    return result.value || ''
  }
  const result = await mammoth.extractRawText({ path: source.filePath })
  return result.value || ''
}

module.exports = { parse, parseFromData, generateDocx }

/**
 * Genera un DOCX con texto e imágenes vía el backend (python-docx).
 * Mammoth no soporta escritura; delegamos al backend que sí tiene python-docx.
 *
 * @param {object} params
 * @param {string} params.title - Nombre del documento
 * @param {string} params.content - Contenido markdown/texto
 * @param {string[]} [params.imagePaths] - Rutas de imágenes a incrustar
 * @param {string} [params.folder] - Subcarpeta opcional
 * @param {string} [params.authToken] - Token JWT para autenticar con el backend
 * @returns {Promise<{ok:boolean, filename?:string, path?:string, size_bytes?:number, image_count?:number, error?:string}>}
 */
async function generateDocx({ title, content, imagePaths, folder, authToken }) {
  try {
    const apiBase = (process.env.DOT_API_BASE_URL || 'http://127.0.0.1:8000').trim().replace(/\/+$/, '')
    const response = await fetch(`${apiBase}/v1/documents/generate-with-images`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        ...(authToken ? { Authorization: `Bearer ${authToken}` } : {}),
      },
      body: JSON.stringify({
        title: String(title || 'Documento DOT'),
        content: String(content || ''),
        image_paths: Array.isArray(imagePaths) ? imagePaths : [],
        folder: folder || null,
      }),
    })
    if (!response.ok) {
      const errBody = await response.text().catch(() => '')
      return { ok: false, error: `Backend error ${response.status}: ${errBody.slice(0, 200)}` }
    }
    return await response.json()
  } catch (err) {
    return { ok: false, error: String(err).slice(0, 300) }
  }
}
