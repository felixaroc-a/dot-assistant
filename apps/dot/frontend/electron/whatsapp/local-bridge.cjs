'use strict'

const http = require('node:http')
const fs = require('node:fs')
const path = require('node:path')
const { getTransport } = require('./transport/index.cjs')
const localTools = require('../local-tools.cjs')
const browserAutomation = require('../browser-automation.cjs')
const fileSearch = require('../file-search.cjs')
const documentParser = require('../document-parser.cjs')
const { resolveSafePath } = require('../sandbox-resolver.cjs')

/** @type {import('node:http').Server | null} */
let server = null
let listeningPort = 0

const MAX_MEDIA_BYTES = 50 * 1024 * 1024
const IMAGE_EXTENSIONS = new Set(['.jpg', '.jpeg', '.png', '.webp', '.gif'])
const AUDIO_EXTENSIONS = new Set(['.mp3', '.ogg', '.opus', '.m4a', '.aac', '.webm'])

const ALLOWED_TOOL_OPS = new Set([
  'readFile',
  'readFileBytes',
  'writeFile',
  'writeFileBytes',
  'listFiles',
  'deleteFile',
  'downloadUrl',
  'searchFiles',
  'parseDocument',
  'browserNavigate',
  'browserExtract',
  'browserClick',
  'browserType',
  'browserWait',
  'browserGetPrice',
  'browserScreenshot',
  'browserClose',
  'browserPdf',
  'browserGetCookies',
  'browserSetCookies',
  'browserScroll',
  'browserNetworkIntercept',
  'browserExecuteJS',
  'browserFillForm',
  'browserWaitForNavigation',
  'browserGetPageTitle',
  'browserGetPageURL',
  'browserSelectOption',
  'browserHover',
  'browserPressKey',
  'browserUploadFile',
  'browserStealth',
  'browserScreenshotElement',
  'browserFillFormAdvanced',
  'browserFill',
  'browserOpenSession',
  'browserDoAction',
  'browserCloseSessionExtract',
])

const BROWSER_ERROR_MESSAGES = {
  url_required: 'Falta la URL. Debe empezar con http:// o https://.',
  invalid_url: 'La dirección web no es válida. Debe empezar con http:// o https://.',
  only_http_https: 'Solo se permiten URLs http:// o https://.',
  host_blocked: 'Por seguridad no puedo abrir esa dirección.',
  browser_permission_denied:
    'No tengo permiso para abrir páginas web. Actívalo en Configuración → Privacidad → "DOT puede usar webs".',
  browser_permission_required:
    'Para entrar en páginas web necesito tu permiso. Ve a Configuración → Privacidad y activa "DOT puede usar webs".',
  browser_not_navigated:
    'Primero necesito abrir la página web. Indica la URL o pide que entre al sitio.',
  browser_timeout: 'La página tardó demasiado en cargar. Intenta con otra URL o más tarde.',
  selector_required: 'Falta el selector del elemento en la página.',
  wait_timeout: 'La página no mostró el contenido a tiempo. Intenta de nuevo.',
  element_not_found: 'No encontré ese elemento en la página.',
  click_failed: 'No pude hacer clic en ese elemento.',
  type_failed: 'No pude escribir en ese campo.',
  price_failed: 'No pude detectar un precio en esa página.',
}

/**
 * @param {Record<string, unknown>} result
 */
function humanizeBrowserResult(result) {
  if (!result || result.ok !== false) return result
  const code = String(result.error || '').trim()
  const friendly = BROWSER_ERROR_MESSAGES[code] || result.message
  if (!friendly) return result
  return { ...result, error: friendly, message: friendly }
}

/**
 * @param {import('node:http').IncomingMessage} req
 * @param {number} [maxBytes]
 * @returns {Promise<Record<string, unknown>>}
 */
function readJsonBody(req, maxBytes = 512_000) {
  return new Promise((resolve, reject) => {
    let raw = ''
    req.on('data', (chunk) => {
      raw += String(chunk)
      if (raw.length > maxBytes) {
        reject(new Error('payload_too_large'))
        req.destroy()
      }
    })
    req.on('end', () => {
      if (!raw.trim()) {
        resolve({})
        return
      }
      try {
        resolve(JSON.parse(raw))
      } catch {
        reject(new Error('invalid_json'))
      }
    })
    req.on('error', reject)
  })
}

/**
 * @param {import('node:http').ServerResponse} res
 * @param {number} status
 * @param {Record<string, unknown>} body
 */
function writeJson(res, status, body) {
  const payload = JSON.stringify(body)
  res.writeHead(status, {
    'Content-Type': 'application/json; charset=utf-8',
    'Content-Length': Buffer.byteLength(payload),
  })
  res.end(payload)
}

/**
 * @param {string} secret
 * @param {import('node:http').IncomingMessage} req
 * @param {import('node:http').ServerResponse} res
 */
function requireBridgeSecret(secret, req, res) {
  if (!secret) {
    writeJson(res, 503, { ok: false, error: 'bridge_secret_not_configured' })
    return false
  }
  const received = String(req.headers['x-bridge-secret'] || '')
  if (received !== secret) {
    writeJson(res, 401, { ok: false, error: 'unauthorized' })
    return false
  }
  return true
}

/**
 * Valida ruta de media dentro del sandbox y devuelve metadatos.
 * @param {string} rawPath
 * @returns {{ ok: true; absolutePath: string; mediaType: 'image' | 'document' | 'voice'; fileName: string } | { ok: false; error: string }}
 */
function resolveMediaSendPath(rawPath) {
  const trimmed = String(rawPath || '').trim()
  if (!trimmed) {
    return { ok: false, error: 'path_required' }
  }

  const safePath = resolveSafePath(trimmed)
  if (!safePath) {
    return { ok: false, error: 'path_outside_sandbox' }
  }
  if (!fs.existsSync(safePath)) {
    return { ok: false, error: 'file_not_found' }
  }

  let stat
  try {
    stat = fs.statSync(safePath)
  } catch (err) {
    return { ok: false, error: err instanceof Error ? err.message : String(err) }
  }
  if (!stat.isFile()) {
    return { ok: false, error: 'not_a_file' }
  }
  if (stat.size <= 0) {
    return { ok: false, error: 'file_empty' }
  }
  if (stat.size > MAX_MEDIA_BYTES) {
    return { ok: false, error: 'file_too_large' }
  }

  const ext = path.extname(safePath).toLowerCase()
  let mediaType = 'document'
  if (IMAGE_EXTENSIONS.has(ext)) {
    mediaType = 'image'
  } else if (AUDIO_EXTENSIONS.has(ext)) {
    mediaType = 'voice'
  }
  return {
    ok: true,
    absolutePath: safePath,
    mediaType,
    fileName: path.basename(safePath),
  }
}

/**
 * @param {Record<string, unknown>} body
 */
async function executeLocalTool(body) {
  const operation = String(body.operation || '').trim()
  if (!ALLOWED_TOOL_OPS.has(operation)) {
    return { ok: false, error: `operation_not_allowed:${operation || 'empty'}` }
  }
  const relativePath = String(body.path ?? '')
  if (operation === 'writeFile') {
    return localTools.writeFile(relativePath, String(body.content ?? ''))
  }
  if (operation === 'writeFileBytes') {
    return localTools.writeFileBytes(relativePath, String(body.content ?? ''))
  }
  if (operation === 'readFile') {
    return localTools.readFile(relativePath)
  }
  if (operation === 'readFileBytes') {
    return localTools.readFileBytes(relativePath)
  }
  if (operation === 'listFiles') {
    return localTools.listFiles(relativePath)
  }
  if (operation === 'downloadUrl') {
    return localTools.downloadUrlToDesktop(String(body.url ?? ''), relativePath)
  }
  if (operation === 'deleteFile') {
    return localTools.deleteFile(relativePath)
  }
  if (operation === 'searchFiles') {
    const query = String(body.query || '').trim()
    if (!query) return { ok: false, error: 'query_required' }
    return fileSearch.search({
      query,
      contentPattern: body.contentPattern ? String(body.contentPattern) : undefined,
      searchRoot: body.searchRoot ? String(body.searchRoot) : 'all',
      scope: body.scope ? String(body.scope) : undefined,
    })
  }
  if (operation === 'parseDocument') {
    const filePath = String(body.path || '').trim()
    const mimeType = String(body.content || 'application/octet-stream').trim()
    if (!filePath) return { ok: false, error: 'path_required' }
    return documentParser.parse(filePath, mimeType)
  }
  if (operation === 'browserNavigate') {
    return humanizeBrowserResult(
      await browserAutomation.navigate(
        { url: String(body.url || ''), timeoutMs: body.timeoutMs ? Number(body.timeoutMs) : undefined },
        localTools,
      ),
    )
  }
  if (operation === 'browserExtract') {
    return humanizeBrowserResult(
      await browserAutomation.extract(
        { selector: body.selector ? String(body.selector) : 'body' },
        localTools,
      ),
    )
  }
  if (operation === 'browserClick') {
    return humanizeBrowserResult(
      await browserAutomation.click({ selector: String(body.selector || '') }, localTools),
    )
  }
  if (operation === 'browserType') {
    return humanizeBrowserResult(
      await browserAutomation.type(
        {
          selector: String(body.selector || ''),
          text: String(body.text ?? ''),
          clear: body.clear !== false,
        },
        localTools,
      ),
    )
  }
  if (operation === 'browserWait') {
    return humanizeBrowserResult(
      await browserAutomation.waitFor(
        {
          selector: body.selector ? String(body.selector) : '',
          textContains: body.textContains ? String(body.textContains) : '',
          timeoutMs: body.timeoutMs ? Number(body.timeoutMs) : undefined,
        },
        localTools,
      ),
    )
  }
  if (operation === 'browserGetPrice') {
    return humanizeBrowserResult(await browserAutomation.extractPrice({}, localTools))
  }
  if (operation === 'browserScreenshot') {
    return browserAutomation.screenshot(body.params || body, localTools)
  }
  if (operation === 'browserClose') {
    return browserAutomation.closeBrowser()
  }
  if (operation === 'browserPdf') {
    return browserAutomation.pdf(body.params || body, localTools)
  }
  if (operation === 'browserGetCookies') {
    return browserAutomation.getCookies(body.params || body, localTools)
  }
  if (operation === 'browserSetCookies') {
    return browserAutomation.setCookies(body.params || body, localTools)
  }
  if (operation === 'browserScroll') {
    return browserAutomation.scroll(body.params || body, localTools)
  }
  if (operation === 'browserNetworkIntercept') {
    return browserAutomation.networkIntercept(body.params || body, localTools)
  }
  if (operation === 'browserExecuteJS') {
    return browserAutomation.executeJS(body.params || body, localTools)
  }
  if (operation === 'browserFillForm') {
    return browserAutomation.fillForm(body.params || body, localTools)
  }
  if (operation === 'browserWaitForNavigation') {
    return browserAutomation.waitForNavigation(body.params || body, localTools)
  }
  if (operation === 'browserGetPageTitle') {
    return browserAutomation.getPageTitle(body.params || body, localTools)
  }
  if (operation === 'browserGetPageURL') {
    return browserAutomation.getPageURL(body.params || body, localTools)
  }
  if (operation === 'browserSelectOption') {
    return browserAutomation.selectOption(body.params || body, localTools)
  }
  if (operation === 'browserHover') {
    return browserAutomation.hover(body.params || body, localTools)
  }
  if (operation === 'browserPressKey') {
    return browserAutomation.pressKey(body.params || body, localTools)
  }
  if (operation === 'browserUploadFile') {
    return browserAutomation.uploadFile(body.params || body, localTools)
  }
  if (operation === 'browserStealth') {
    return browserAutomation.stealth(body.params || body, localTools)
  }
  if (operation === 'browserScreenshotElement') {
    return browserAutomation.screenshotElement(body.params || body, localTools)
  }
  if (operation === 'browserFillFormAdvanced') {
    return browserAutomation.fillFormAdvanced(body.params || body, localTools)
  }
  if (operation === 'browserFill') {
    return browserAutomation.fill(body.params || body, localTools)
  }
  if (operation === 'browserOpenSession') {
    return browserAutomation.openSession(body.params || body, localTools)
  }
  if (operation === 'browserDoAction') {
    return browserAutomation.doAction(body.params || body, localTools)
  }
  if (operation === 'browserCloseSessionExtract') {
    return browserAutomation.closeSessionExtract(body.params || body, localTools)
  }
  return { ok: false, error: `operation_not_handled:${operation}` }
}

/**
 * @param {{ port?: number; secret?: string; onInboundNotification?: (payload: Record<string, unknown>) => void; fileIndexer?: import('../file-indexer.cjs').FileIndexer }} opts
 */
function startLocalBridge(opts = {}) {
  if (server) {
    return { ok: true, port: listeningPort, started: false }
  }

  const configuredPort = Number(opts.port || process.env.WHATSAPP_BRIDGE_PORT || 18790)
  const secret = String(opts.secret || process.env.WHATSAPP_BRIDGE_SECRET || '').trim()
  const fileIndexer = opts.fileIndexer || null

  server = http.createServer(async (req, res) => {
    try {
      if (req.method === 'GET' && req.url === '/health') {
        writeJson(res, 200, { ok: true, service: 'dot-whatsapp-bridge' })
        return
      }

      if (req.method === 'POST' && req.url === '/v1/send') {
        if (!requireBridgeSecret(secret, req, res)) return
        const body = await readJsonBody(req, 64_000)
        const result = await getTransport().sendMessage(
          String(body.to || ''),
          String(body.text || ''),
        )
        if (!result.ok) {
          writeJson(res, 502, { ok: false, error: result.error || 'send_failed' })
          return
        }
        writeJson(res, 200, { ok: true, message_id: result.message_id || null })
        return
      }

      if (req.method === 'POST' && req.url === '/v1/send-media') {
        if (!requireBridgeSecret(secret, req, res)) return
        const body = await readJsonBody(req, 64_000)
        const resolved = resolveMediaSendPath(String(body.path || body.file || ''))
        if (!resolved.ok) {
          writeJson(res, 400, { ok: false, error: resolved.error })
          return
        }

        const transport = getTransport()
        if (typeof transport.sendMedia !== 'function') {
          writeJson(res, 501, { ok: false, error: 'media_send_not_supported' })
          return
        }

        const requestedType = String(body.media_type || body.type || '').trim().toLowerCase()
        const normalizedType =
          requestedType === 'audio' || requestedType === 'voice_note'
            ? 'voice'
            : requestedType
        const mediaType =
          normalizedType === 'image' || normalizedType === 'document' || normalizedType === 'voice'
            ? normalizedType
            : resolved.mediaType

        const result = await transport.sendMedia(String(body.to || ''), resolved.absolutePath, {
          mediaType,
          caption: String(body.caption || ''),
          fileName: resolved.fileName,
        })
        if (!result.ok) {
          writeJson(res, 502, { ok: false, error: result.error || 'send_media_failed' })
          return
        }
        writeJson(res, 200, {
          ok: true,
          message_id: result.message_id || null,
          media_type: mediaType,
        })
        return
      }

      // C2: tools locales vía bridge autenticado (mismo sandbox que IPC).
      if (req.method === 'POST' && req.url === '/v1/tools/execute') {
        if (!requireBridgeSecret(secret, req, res)) return
        const body = await readJsonBody(req)
        const result = await executeLocalTool(body)
        writeJson(res, result.ok ? 200 : 400, result)
        return
      }

      // FASE 3.2: búsqueda en índice persistente de archivos vía file-indexer
      if (req.method === 'POST' && req.url === '/v1/memory/search-files') {
        if (!requireBridgeSecret(secret, req, res)) return
        if (!fileIndexer) {
          writeJson(res, 503, { ok: false, error: 'file_indexer_not_available' })
          return
        }
        const body = await readJsonBody(req)
        const query = String(body.query || '').trim()
        if (!query) {
          writeJson(res, 400, { ok: false, error: 'query_required' })
          return
        }
        const limit = typeof body.limit === 'number' && body.limit > 0 ? Math.min(body.limit, 50) : 20
        const results = await fileIndexer.searchFiles(query, limit)
        writeJson(res, 200, { ok: true, results })
        return
      }

      writeJson(res, 404, { ok: false, error: 'not_found' })
    } catch (err) {
      const message = err instanceof Error ? err.message : String(err)
      writeJson(res, 400, { ok: false, error: message })
    }
  })

  return new Promise((resolve) => {
    server.listen(configuredPort, '127.0.0.1', () => {
      const address = server.address()
      listeningPort = typeof address === 'object' && address ? address.port : configuredPort
      resolve({ ok: true, port: listeningPort, started: true })
    })
    server.on('error', (err) => {
      resolve({ ok: false, error: err.message })
    })
  })
}

function stopLocalBridge() {
  if (!server) return { ok: true }
  const current = server
  server = null
  listeningPort = 0
  return new Promise((resolve) => {
    current.close(() => resolve({ ok: true }))
  })
}

function getBridgePort() {
  return listeningPort
}

module.exports = {
  startLocalBridge,
  stopLocalBridge,
  getBridgePort,
  executeLocalTool,
  ALLOWED_TOOL_OPS,
}
