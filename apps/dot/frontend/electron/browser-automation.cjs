'use strict'

/**
 * Browser automation potente (BIBLIA §20 capa B).
 * Electron Chromium — sin shell; allowlist + timeout + permiso GUI.
 * M1S2-A: expandido a 23 operaciones (8 base + 15 CDP reales).
 */

const { URL } = require('node:url')
const path = require('node:path')
const fs = require('node:fs')

/** @type {import('electron').BrowserWindow | null} */
let _win = null
let _BrowserWindow = null

const DEFAULT_TIMEOUT_MS = 30_000
const MAX_EXTRACT_CHARS = 16_000

const BLOCKED_HOST_RE =
  /^(localhost|127\.|0\.|10\.|192\.168\.|169\.254\.|::1|\[::1\])/i

function getBrowserWindow() {
  if (_BrowserWindow) return _BrowserWindow
  // eslint-disable-next-line global-require
  const electron = require('electron')
  _BrowserWindow = electron.BrowserWindow
  return _BrowserWindow
}

function validateUrl(rawUrl) {
  const raw = String(rawUrl || '').trim()
  if (!raw) return { ok: false, error: 'url_required' }
  let parsed
  try {
    parsed = new URL(raw)
  } catch {
    return { ok: false, error: 'invalid_url' }
  }
  if (parsed.protocol !== 'http:' && parsed.protocol !== 'https:') {
    return { ok: false, error: 'only_http_https' }
  }
  const host = parsed.hostname || ''
  if (BLOCKED_HOST_RE.test(host) || host === '0.0.0.0') {
    return { ok: false, error: 'host_blocked' }
  }
  return { ok: true, url: parsed.toString(), host }
}

function ensureBrowserPermission(localTools) {
  if (typeof localTools.canUseBrowserTools === 'function') {
    if (localTools.canUseBrowserTools()) return 'allowed'
    const status = localTools.getPermissionStatus('browser')
    if (status === 'denied') return 'denied'
    if (process.env.DOT_DEMO_MODE === '1' || process.env.TESTING === '1') {
      localTools.setPermission('browser', 'always')
      return 'allowed'
    }
    return 'requires_confirmation'
  }
  const status = localTools.getPermissionStatus('browser')
  if (status === 'allowed') return 'allowed'
  if (status === 'denied') return 'denied'
  if (process.env.DOT_DEMO_MODE === '1' || process.env.TESTING === '1') {
    localTools.setPermission('browser', 'always')
    return 'allowed'
  }
  return 'requires_confirmation'
}

function permGate(localTools) {
  const perm = ensureBrowserPermission(localTools)
  if (perm === 'denied') return { ok: false, error: 'browser_permission_denied' }
  if (perm === 'requires_confirmation') {
    return {
      ok: false,
      error: 'browser_permission_required',
      message:
        'Para entrar en páginas web necesito tu permiso. Ve a Configuración → Privacidad y activa "DOT puede usar webs".',
    }
  }
  return { ok: true }
}

async function getOrCreateWindow() {
  const BrowserWindow = getBrowserWindow()
  if (_win && !_win.isDestroyed()) return _win
  _win = new BrowserWindow({
    show: false,
    width: 1366,
    height: 900,
    webPreferences: {
      nodeIntegration: false,
      contextIsolation: true,
      sandbox: true,
      javascript: true,
      // M1S2-A: persistencia de sesion (cookies, localStorage, etc.)
      partition: 'persist:dot-browser',
    },
  })
  _win.on('closed', () => {
    _win = null
  })
  return _win
}

function requireWindow() {
  if (!_win || _win.isDestroyed()) {
    return { ok: false, error: 'browser_not_navigated' }
  }
  return { ok: true, win: _win }
}

// ---------------------------------------------------------------
// OPERACIONES EXISTENTES (M1S1)
// ---------------------------------------------------------------

async function navigate(opts, localTools) {
  const gate = permGate(localTools)
  if (!gate.ok) return gate

  const v = validateUrl(opts.url)
  if (!v.ok) return v

  const timeoutMs = Math.min(Number(opts.timeoutMs) || DEFAULT_TIMEOUT_MS, 90_000)
  try {
    const win = await getOrCreateWindow()
    const loadPromise = win.loadURL(v.url, {
      userAgent:
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36',
    })
    const timer = new Promise((_, reject) =>
      setTimeout(() => reject(new Error('timeout')), timeoutMs),
    )
    await Promise.race([loadPromise, timer])
    // Espera breve a JS inicial
    await new Promise((r) => setTimeout(r, 800))
    const title = win.webContents.getTitle() || ''
    return { ok: true, url: win.webContents.getURL() || v.url, host: v.host, title }
  } catch (err) {
    const message = err instanceof Error ? err.message : String(err)
    return { ok: false, error: message === 'timeout' ? 'browser_timeout' : message }
  }
}

async function extract(opts, localTools) {
  const gate = permGate(localTools)
  if (!gate.ok) return gate
  const w = requireWindow()
  if (!w.ok) return w

  const selector = String(opts.selector || 'body').trim() || 'body'
  const maxChars = Math.min(Number(opts.maxChars) || MAX_EXTRACT_CHARS, 40_000)
  try {
    _cdpAttach(w.win)
    const safeSel = JSON.stringify(selector)
    const expression =
      `(() => { const el = document.querySelector(${safeSel}) || document.body; const t = (el && (el.innerText || el.textContent) || '').replace(/\\s+/g, ' ').trim(); return t.slice(0, ${maxChars}); })()`
    const result = await _cdpSend(w.win, 'Runtime.evaluate', {
      expression,
      returnByValue: true,
    })
    _cdpDetach(w.win)

    const text = (result && result.result && result.result.value) || ''
    const title = w.win.webContents.getTitle() || ''
    return {
      ok: true,
      url: w.win.webContents.getURL(),
      title,
      selector,
      text: String(text || ''),
      chars: String(text || '').length,
    }
  } catch (err) {
    try { _cdpDetach(w.win) } catch (_) { /* ignore */ }
    return { ok: false, error: err instanceof Error ? err.message : String(err) }
  }
}

async function click(opts, localTools) {
  const gate = permGate(localTools)
  if (!gate.ok) return gate
  const w = requireWindow()
  if (!w.ok) return w
  const selector = String(opts.selector || '').trim()
  if (!selector) return { ok: false, error: 'selector_required' }
  try {
    const result = await w.win.webContents.executeJavaScript(
      `(() => {
        const el = document.querySelector(${JSON.stringify(selector)});
        if (!el) return { ok: false, error: 'element_not_found' };
        el.scrollIntoView({ block: 'center', inline: 'center' });
        el.click();
        return { ok: true, tag: el.tagName, text: (el.innerText || '').slice(0, 80) };
      })()`,
      true,
    )
    if (!result || !result.ok) {
      return { ok: false, error: (result && result.error) || 'click_failed' }
    }
    await new Promise((r) => setTimeout(r, 400))
    return {
      ok: true,
      selector,
      url: w.win.webContents.getURL(),
      clicked: result.text || result.tag,
    }
  } catch (err) {
    return { ok: false, error: err instanceof Error ? err.message : String(err) }
  }
}

async function type(opts, localTools) {
  const gate = permGate(localTools)
  if (!gate.ok) return gate
  const w = requireWindow()
  if (!w.ok) return w
  const selector = String(opts.selector || '').trim()
  const text = String(opts.text ?? '')
  if (!selector) return { ok: false, error: 'selector_required' }
  const clear = opts.clear !== false
  try {
    const result = await w.win.webContents.executeJavaScript(
      `(() => {
        const el = document.querySelector(${JSON.stringify(selector)});
        if (!el) return { ok: false, error: 'element_not_found' };
        el.focus();
        if (${clear ? 'true' : 'false'}) {
          if ('value' in el) el.value = '';
          else el.textContent = '';
        }
        if ('value' in el) {
          el.value = ${JSON.stringify(text)};
          el.dispatchEvent(new Event('input', { bubbles: true }));
          el.dispatchEvent(new Event('change', { bubbles: true }));
        } else {
          el.textContent = ${JSON.stringify(text)};
        }
        return { ok: true };
      })()`,
      true,
    )
    if (!result || !result.ok) {
      return { ok: false, error: (result && result.error) || 'type_failed' }
    }
    return { ok: true, selector, chars: text.length, url: w.win.webContents.getURL() }
  } catch (err) {
    return { ok: false, error: err instanceof Error ? err.message : String(err) }
  }
}

async function waitFor(opts, localTools) {
  const gate = permGate(localTools)
  if (!gate.ok) return gate
  const w = requireWindow()
  if (!w.ok) return w
  const selector = String(opts.selector || '').trim()
  const textContains = String(opts.textContains || '').trim()
  const timeoutMs = Math.min(Number(opts.timeoutMs) || 15_000, 60_000)
  const started = Date.now()
  while (Date.now() - started < timeoutMs) {
    try {
      const found = await w.win.webContents.executeJavaScript(
        `(() => {
          const sel = ${JSON.stringify(selector)};
          const needle = ${JSON.stringify(textContains)};
          if (sel) {
            const el = document.querySelector(sel);
            if (!el) return false;
            if (!needle) return true;
            const t = (el.innerText || el.textContent || '');
            return t.toLowerCase().includes(needle.toLowerCase());
          }
          if (needle) {
            const t = (document.body && (document.body.innerText || document.body.textContent) || '');
            return t.toLowerCase().includes(needle.toLowerCase());
          }
          return false;
        })()`,
        true,
      )
      if (found) {
        return {
          ok: true,
          waited_ms: Date.now() - started,
          url: w.win.webContents.getURL(),
        }
      }
    } catch {
      // retry
    }
    await new Promise((r) => setTimeout(r, 350))
  }
  return { ok: false, error: 'wait_timeout' }
}

/**
 * Heurística de precio en páginas de e-commerce (Amazon, ML, etc.).
 */
async function extractPrice(opts, localTools) {
  const gate = permGate(localTools)
  if (!gate.ok) return gate
  const w = requireWindow()
  if (!w.ok) return w
  try {
    const data = await w.win.webContents.executeJavaScript(
      `(() => {
        const selectors = [
          '#priceblock_ourprice', '#priceblock_dealprice', '#priceblock_saleprice',
          '.a-price .a-offscreen', '#corePrice_feature_div .a-offscreen',
          '[data-testid="price-amount"]', '.ui-pdp-price__second-line .andes-money-amount__fraction',
          '.price-tag-fraction', '[itemprop="price"]', 'meta[itemprop="price"]',
          '.product-price', '.price', '#price',
        ];
        const hits = [];
        for (const sel of selectors) {
          const nodes = document.querySelectorAll(sel);
          for (const n of nodes) {
            let raw = '';
            if (n.tagName === 'META') raw = n.getAttribute('content') || '';
            else raw = n.getAttribute('content') || n.innerText || n.textContent || '';
            raw = String(raw).replace(/\\s+/g, ' ').trim();
            if (raw && /[0-9]/.test(raw)) hits.push({ sel, raw: raw.slice(0, 80) });
          }
        }
        const body = (document.body && document.body.innerText || '').replace(/\\s+/g, ' ');
        const moneyRe = /(?:US\\$|USD|\\$|Bs\\.?|VES)\\s?[0-9]{1,3}(?:[.,][0-9]{3})*(?:[.,][0-9]{2})?/gi;
        const fromBody = (body.match(moneyRe) || []).slice(0, 8);
        return {
          title: document.title || '',
          hits: hits.slice(0, 12),
          fromBody,
        };
      })()`,
      true,
    )
    const primary =
      (data.hits && data.hits[0] && data.hits[0].raw) ||
      (data.fromBody && data.fromBody[0]) ||
      null
    return {
      ok: true,
      url: w.win.webContents.getURL(),
      title: data.title || '',
      price: primary,
      candidates: data.hits || [],
      money_in_page: data.fromBody || [],
    }
  } catch (err) {
    return { ok: false, error: err instanceof Error ? err.message : String(err) }
  }
}

function _slugFromUrl(url) {
  try {
    const host = new URL(String(url || '')).hostname || 'pagina'
    return host
      .replace(/^www\./i, '')
      .replace(/[^a-z0-9]+/gi, '-')
      .replace(/^-|-$/g, '')
      .slice(0, 40) || 'pagina'
  } catch {
    return 'pagina'
  }
}

function _resolveScreenshotDest(opts, url, format) {
  const fmt = String(format || 'png').trim().toLowerCase()
  const ext = fmt === 'jpeg' || fmt === 'jpg' ? 'jpg' : 'png'
  const raw = String(
    opts.filepath || opts.filename || opts.path || opts.filePath || '',
  ).trim()

  if (raw) {
    let normalized = raw.replace(/\\/g, '/')
    if (/^(escritorio|desktop)(\/|$)/i.test(normalized)) {
      normalized = `~/Desktop/${normalized.replace(/^(escritorio|desktop)\/?/i, '')}`
    } else if (!normalized.startsWith('~/') && !path.isAbsolute(normalized)) {
      normalized = `~/Desktop/${normalized}`
    }
    if (!/\.(png|jpe?g)$/i.test(normalized)) {
      normalized += `.${ext}`
    }
    return normalized
  }

  const slug = _slugFromUrl(url)
  const ts = new Date().toISOString().replace(/[:.]/g, '-').slice(0, 19)
  return `~/Desktop/dot-captura-${slug}-${ts}.${ext}`
}

function _persistScreenshotBase64(result, opts, url, format, localTools) {
  if (!result?.data) {
    return { ok: false, error: 'screenshot_empty' }
  }
  if (!localTools?.writeFileBytes) {
    return { ok: false, error: 'writeFileBytes_unavailable' }
  }

  const destPath = _resolveScreenshotDest(opts, url, format)
  const saved = localTools.writeFileBytes(destPath, result.data)
  if (!saved.ok) {
    return {
      ok: false,
      error: saved.error || 'screenshot_save_failed',
      dest_path: destPath,
    }
  }
  return {
    ok: true,
    saved_to: saved.path,
    relative_path: destPath,
    size_bytes: saved.bytes,
  }
}

async function screenshot(opts, localTools) {
  const gate = permGate(localTools)
  if (!gate.ok) return gate
  const w = requireWindow()
  if (!w.ok) return w

  try {
    _cdpAttach(w.win)
    const result = await _cdpSend(w.win, 'Page.captureScreenshot', {
      format: String(opts.format || 'png'),
      quality: opts.quality !== undefined ? Number(opts.quality) : undefined,
      clip: opts.clip || undefined,
      captureBeyondViewport: opts.fullPage === true,
    })
    _cdpDetach(w.win)

    if (result && result.data) {
      const format = opts.format || 'png'
      const url = w.win.webContents.getURL()
      const title = w.win.webContents.getTitle() || ''
      const saved = _persistScreenshotBase64(result, opts, url, format, localTools)
      if (!saved.ok) {
        return {
          ok: false,
          error: saved.error || 'screenshot_save_failed',
          dest_path: saved.dest_path,
        }
      }
      return {
        ok: true,
        screenshot_base64: result.data,
        format,
        url,
        title,
        saved_to: saved.saved_to,
        relative_path: saved.relative_path,
        size_bytes: saved.size_bytes,
      }
    }
    return { ok: false, error: 'screenshot_failed' }
  } catch (err) {
    try { _cdpDetach(w.win) } catch (_) { /* ignore */ }
    return { ok: false, error: err instanceof Error ? err.message : String(err) }
  }
}

function closeBrowser() {
  if (_win && !_win.isDestroyed()) {
    _win.destroy()
  }
  _win = null
  return { ok: true }
}

// BR04 — browserFill: single-field set value + dispatch input/change events
async function fill(opts, localTools) {
  const gate = permGate(localTools)
  if (!gate.ok) return gate
  const w = requireWindow()
  if (!w.ok) return w
  const selector = String(opts.selector || '').trim()
  const value = String(opts.value ?? opts.text ?? '')
  if (!selector) return { ok: false, error: 'selector_required' }
  if (!value) return { ok: false, error: 'value_required' }
  try {
    const safeSel = JSON.stringify(selector)
    const safeVal = JSON.stringify(value)
    const result = await w.win.webContents.executeJavaScript(
      `(() => {
        const el = document.querySelector(${safeSel});
        if (!el) return { ok: false, error: 'element_not_found' };
        el.focus();
        if ('value' in el && el.tagName !== 'SELECT') {
          el.value = ${safeVal};
          el.dispatchEvent(new Event('input', { bubbles: true }));
          el.dispatchEvent(new Event('change', { bubbles: true }));
        } else if ('value' in el && el.tagName === 'SELECT') {
          el.value = ${safeVal};
          el.dispatchEvent(new Event('change', { bubbles: true }));
        } else {
          el.textContent = ${safeVal};
        }
        return { ok: true, tag: el.tagName };
      })()`,
      true,
    )
    if (!result || !result.ok) {
      return { ok: false, error: (result && result.error) || 'fill_failed' }
    }
    return {
      ok: true,
      selector,
      value,
      tag: result.tag,
      url: w.win.webContents.getURL(),
    }
  } catch (err) {
    return { ok: false, error: err instanceof Error ? err.message : String(err) }
  }
}

// -------------------------------------------------------------------
// BR05 — SESSION MANAGEMENT (multi-step)
// -------------------------------------------------------------------

/** @type {Map<string, { openedAt: number; url: string }>} */
const _sessions = new Map()

async function openSession(opts, localTools) {
  // reutiliza navigate con timeout ajustable
  const result = await navigate(
    { url: opts.url, timeoutMs: opts.timeoutMs },
    localTools,
  )
  if (!result.ok) return result

  const uid = String(opts.uid || 'default')
  _sessions.set(uid, {
    openedAt: Date.now(),
    url: result.url,
  })

  return {
    ...result,
    uid,
    session_active: _sessions.size,
  }
}

async function doAction(opts, localTools) {
  const gate = permGate(localTools)
  if (!gate.ok) return gate
  const w = requireWindow()
  if (!w.ok) return w

  const jsCode = String(opts.js_code || opts.code || '').trim()
  if (!jsCode) return { ok: false, error: 'js_code_required' }

  const uid = String(opts.uid || 'default')
  if (!_sessions.has(uid)) {
    return { ok: false, error: 'session_not_found', hint: 'Usa browser_open primero.' }
  }

  try {
    _cdpAttach(w.win)
    const result = await _cdpSend(
      w.win,
      'Runtime.evaluate',
      { expression: jsCode, returnByValue: true },
      Number(opts.timeoutMs) || DEFAULT_TIMEOUT_MS,
    )
    _cdpDetach(w.win)

    if (result && result.exceptionDetails) {
      return {
        ok: false,
        error: result.exceptionDetails.text || 'js_exception',
      }
    }
    return {
      ok: true,
      result: (result && result.result) || null,
      uid,
      url: w.win.webContents.getURL(),
    }
  } catch (err) {
    try { _cdpDetach(w.win) } catch (_) { /* ignore */ }
    return { ok: false, error: err instanceof Error ? err.message : String(err) }
  }
}

// BR06 — Structured extract on close
async function closeSessionExtract(opts, localTools) {
  const uid = String(opts.uid || 'default')
  const session = _sessions.get(uid)
  if (!session) {
    return { ok: false, error: 'session_not_found', hint: 'No hay sesión activa para este uid.' }
  }

  let extract = { title: '', text_preview: '', links_count: 0, screenshot_base64: null }
  const w = requireWindow()

  if (w.ok) {
    try {
      // Screenshot via CDP
      _cdpAttach(w.win)
      const shot = await _cdpSend(w.win, 'Page.captureScreenshot', {
        format: 'png',
      }).catch(() => null)
      _cdpDetach(w.win)

      extract.screenshot_base64 = (shot && shot.data) || null
      extract.title = w.win.webContents.getTitle() || ''

      // Text preview via JS
      try {
        const txt = await w.win.webContents.executeJavaScript(
          `(() => {
            const t = (document.body && (document.body.innerText || document.body.textContent) || '').replace(/\\s+/g, ' ').trim();
            return t.slice(0, 2000);
          })()`,
          true,
        )
        extract.text_preview = String(txt || '')
      } catch (_) { /* ignore */ }

      // Links count
      try {
        const links = await w.win.webContents.executeJavaScript(
          `document.querySelectorAll('a[href]').length`,
          true,
        )
        extract.links_count = Number(links) || 0
      } catch (_) { /* ignore */ }
    } catch (_) { /* ignore */ }
  }

  // Cerrar ventana
  closeBrowser()
  _sessions.delete(uid)

  return {
    ok: true,
    uid,
    session_duration_ms: Date.now() - session.openedAt,
    extract,
  }
}

// ---------------------------------------------------------------
// CDP HELPERS (M1S2-A)
// ---------------------------------------------------------------

/**
 * Adjunta el debugger CDP al webContents de la ventana.
 * Protocolo 1.3 compatible con Chromium de Electron.
 */
function _cdpAttach(win) {
  try {
    if (!win.webContents.debugger.isAttached()) {
      win.webContents.debugger.attach('1.3')
    }
    return true
  } catch (_) {
    // ya estaba adjunto → ignorar
    return false
  }
}

/**
 * Desadjunta el debugger CDP.
 */
function _cdpDetach(win) {
  try {
    if (win.webContents.debugger.isAttached()) {
      win.webContents.debugger.detach()
    }
  } catch (_) {
    // ignorar
  }
}

/**
 * Envia un comando CDP y espera la respuesta con timeout.
 * @param {import('electron').BrowserWindow} win
 * @param {string} method - metodo CDP (ej: 'Page.printToPDF')
 * @param {object} [params={}] - parametros del metodo
 * @param {number} [timeoutMs=30000]
 * @returns {Promise<object>}
 */
function _cdpSend(win, method, params = {}, timeoutMs = DEFAULT_TIMEOUT_MS) {
  return new Promise((resolve, reject) => {
    const timer = setTimeout(() => {
      reject(new Error('cdp_timeout'))
    }, timeoutMs)
    try {
      win.webContents.debugger
        .sendCommand(method, params)
        .then((result) => {
          clearTimeout(timer)
          resolve(result)
        })
        .catch((err) => {
          clearTimeout(timer)
          reject(err)
        })
    } catch (err) {
      clearTimeout(timer)
      reject(err)
    }
  })
}

// ---------------------------------------------------------------
// NUEVAS OPERACIONES CDP (M1S2-A)
// ---------------------------------------------------------------

function _resolvePdfDest(opts, url) {
  const raw = String(
    opts.filepath || opts.filename || opts.path || opts.filePath || '',
  ).trim()

  if (raw) {
    let normalized = raw.replace(/\\/g, '/')
    if (/^(escritorio|desktop)(\/|$)/i.test(normalized)) {
      normalized = `~/Desktop/${normalized.replace(/^(escritorio|desktop)\/?/i, '')}`
    } else if (!normalized.startsWith('~/') && !path.isAbsolute(normalized)) {
      normalized = `~/Desktop/${normalized}`
    }
    if (!/\.pdf$/i.test(normalized)) {
      normalized += '.pdf'
    }
    return normalized
  }

  const slug = _slugFromUrl(url)
  const ts = new Date().toISOString().replace(/[:.]/g, '-').slice(0, 19)
  return `~/Desktop/dot-pdf-${slug}-${ts}.pdf`
}

function _persistPdfBase64(result, opts, url, localTools) {
  if (!result?.data) {
    return { ok: false, error: 'pdf_empty' }
  }
  if (!localTools?.writeFileBytes) {
    return { ok: false, error: 'writeFileBytes_unavailable' }
  }

  const destPath = _resolvePdfDest(opts, url)
  const saved = localTools.writeFileBytes(destPath, result.data)
  if (!saved.ok) {
    return {
      ok: false,
      error: saved.error || 'pdf_save_failed',
      dest_path: destPath,
    }
  }
  return {
    ok: true,
    saved_to: saved.path,
    relative_path: destPath,
    size_bytes: saved.bytes,
  }
}

// 1. pdf — Page.printToPDF
async function pdf(opts, localTools) {
  const gate = permGate(localTools)
  if (!gate.ok) return gate
  const w = requireWindow()
  if (!w.ok) return w
  try {
    _cdpAttach(w.win)
    const result = await _cdpSend(
      w.win,
      'Page.printToPDF',
      {
        landscape: opts.landscape === true,
        displayHeaderFooter: opts.headerFooter === true,
        printBackground: opts.printBackground !== false,
        scale: Number(opts.scale) || 1,
        paperWidth: Number(opts.paperWidth) || 8.27,
        paperHeight: Number(opts.paperHeight) || 11.69,
        marginTop: Number(opts.marginTop) || 0.39,
        marginBottom: Number(opts.marginBottom) || 0.39,
        marginLeft: Number(opts.marginLeft) || 0.39,
        marginRight: Number(opts.marginRight) || 0.39,
        preferCSSPageSize: opts.preferCSSPageSize === true,
      },
      Number(opts.timeoutMs) || 30_000,
    )
    _cdpDetach(w.win)

    if (result && result.data) {
      const url = w.win.webContents.getURL()
      const title = w.win.webContents.getTitle() || ''
      const saved = _persistPdfBase64(result, opts, url, localTools)
      if (!saved.ok) {
        return {
          ok: false,
          error: saved.error || 'pdf_save_failed',
          dest_path: saved.dest_path,
        }
      }
      return {
        ok: true,
        saved_to: saved.saved_to,
        relative_path: saved.relative_path,
        size_bytes: saved.size_bytes,
        url,
        title,
      }
    }
    return { ok: false, error: 'pdf_generation_failed' }
  } catch (err) {
    try { _cdpDetach(w.win) } catch (_) { /* ignore */ }
    return { ok: false, error: err instanceof Error ? err.message : String(err) }
  }
}

// 2. getCookies — Network.getCookies
async function getCookies(opts, localTools) {
  const gate = permGate(localTools)
  if (!gate.ok) return gate
  const w = requireWindow()
  if (!w.ok) return w
  try {
    _cdpAttach(w.win)
    const urls = opts.urls
      ? (Array.isArray(opts.urls) ? opts.urls : [opts.urls])
      : [w.win.webContents.getURL()]
    const result = await _cdpSend(w.win, 'Network.getCookies', { urls })
    _cdpDetach(w.win)
    const cookies = (result && result.cookies) || []
    return {
      ok: true,
      cookies,
      count: cookies.length,
      url: w.win.webContents.getURL(),
    }
  } catch (err) {
    try { _cdpDetach(w.win) } catch (_) { /* ignore */ }
    return { ok: false, error: err instanceof Error ? err.message : String(err) }
  }
}

// 3. setCookies — Network.setCookie (una por cookie)
async function setCookies(opts, localTools) {
  const gate = permGate(localTools)
  if (!gate.ok) return gate
  const w = requireWindow()
  if (!w.ok) return w
  const cookies = opts.cookies
  if (!cookies || !Array.isArray(cookies) || cookies.length === 0) {
    return { ok: false, error: 'cookies_array_required' }
  }
  try {
    _cdpAttach(w.win)
    const currentUrl = w.win.webContents.getURL()
    let set = 0
    const failures = []
    for (let i = 0; i < cookies.length; i++) {
      const c = { ...cookies[i] }
      if (!c.url) c.url = currentUrl || 'https://example.com'
      if (!c.domain && currentUrl) {
        try { c.domain = new URL(currentUrl).hostname } catch (_) { /* ignore */ }
      }
      try {
        await _cdpSend(w.win, 'Network.setCookie', c, 5000)
        set++
      } catch (e) {
        failures.push({ index: i, error: e instanceof Error ? e.message : String(e) })
      }
    }
    _cdpDetach(w.win)
    return {
      ok: true,
      set,
      total: cookies.length,
      failures: failures.length > 0 ? failures : undefined,
      url: currentUrl,
    }
  } catch (err) {
    try { _cdpDetach(w.win) } catch (_) { /* ignore */ }
    return { ok: false, error: err instanceof Error ? err.message : String(err) }
  }
}

// 4. scroll — Input.dispatchMouseEvent mouseWheel
async function scroll(opts, localTools) {
  const gate = permGate(localTools)
  if (!gate.ok) return gate
  const w = requireWindow()
  if (!w.ok) return w
  const deltaY = Number(opts.deltaY || opts.delta_y || 0)
  const deltaX = Number(opts.deltaX || opts.delta_x || 0)
  // si no se especifica delta, scroll hacia abajo por defecto
  const effectiveDeltaY = deltaY !== 0 || deltaX !== 0 ? deltaY : 500
  const repeat = Math.max(1, Math.min(Number(opts.repeat) || 1, 30))
  const x = Number(opts.x) || 400
  const y = Number(opts.y) || 300
  const delayMs = Number(opts.delayMs) || 100
  try {
    _cdpAttach(w.win)
    for (let i = 0; i < repeat; i++) {
      await _cdpSend(w.win, 'Input.dispatchMouseEvent', {
        type: 'mouseWheel',
        x,
        y,
        deltaX,
        deltaY: effectiveDeltaY,
        modifiers: 0,
      })
      if (repeat > 1 && i < repeat - 1) {
        await new Promise((r) => setTimeout(r, delayMs))
      }
    }
    _cdpDetach(w.win)
    return {
      ok: true,
      deltaX,
      deltaY: effectiveDeltaY,
      repeat,
      url: w.win.webContents.getURL(),
    }
  } catch (err) {
    try { _cdpDetach(w.win) } catch (_) { /* ignore */ }
    return { ok: false, error: err instanceof Error ? err.message : String(err) }
  }
}

// 5. networkIntercept — Network.enable + requestWillBeSent
let _networkCaptures = []
let _networkListenerActive = false

async function networkIntercept(opts, localTools) {
  const gate = permGate(localTools)
  if (!gate.ok) return gate
  const w = requireWindow()
  if (!w.ok) return w
  const action = String(opts.action || 'start').trim().toLowerCase()
  const maxCaptures = Math.min(Number(opts.maxCaptures) || 200, 500)

  try {
    if (action === 'start') {
      _networkCaptures = []
      _cdpAttach(w.win)
      await _cdpSend(w.win, 'Network.enable', {}, 10_000)

      if (!_networkListenerActive) {
        _networkListenerActive = true
        w.win.webContents.debugger.on('message', (_event, method, params) => {
          if (method === 'Network.requestWillBeSent') {
            _networkCaptures.push({
              requestId: params.requestId,
              url: (params.request && params.request.url) || '',
              method: (params.request && params.request.method) || '',
              timestamp: params.timestamp,
              type: params.type || '',
            })
            if (_networkCaptures.length > maxCaptures) {
              _networkCaptures = _networkCaptures.slice(-maxCaptures)
            }
          }
        })
      }
      // no detach — mantener escuchando
      return { ok: true, action: 'started', url: w.win.webContents.getURL() }
    }

    if (action === 'snapshot') {
      const captured = [..._networkCaptures]
      return {
        ok: true,
        action: 'snapshot',
        captured,
        count: captured.length,
        url: w.win.webContents.getURL(),
      }
    }

    if (action === 'stop') {
      _networkListenerActive = false
      const captured = [..._networkCaptures]
      _networkCaptures = []
      _cdpDetach(w.win)
      return {
        ok: true,
        action: 'stopped',
        captured,
        count: captured.length,
        url: w.win.webContents.getURL(),
      }
    }

    return { ok: false, error: `invalid_action:${action}. Use: start, snapshot, stop` }
  } catch (err) {
    try { _networkListenerActive = false; _cdpDetach(w.win) } catch (_) { /* ignore */ }
    return { ok: false, error: err instanceof Error ? err.message : String(err) }
  }
}

// 6. executeJS — Runtime.evaluate via CDP
async function executeJS(opts, localTools) {
  const gate = permGate(localTools)
  if (!gate.ok) return gate
  const w = requireWindow()
  if (!w.ok) return w
  const code = String(opts.code || '').trim()
  if (!code) return { ok: false, error: 'code_required' }
  const timeoutMs = Number(opts.timeoutMs) || 15_000
  try {
    _cdpAttach(w.win)
    const result = await _cdpSend(
      w.win,
      'Runtime.evaluate',
      {
        expression: code,
        returnByValue: true,
        awaitPromise: opts.awaitPromise === true,
      },
      timeoutMs + 5_000,
    )
    _cdpDetach(w.win)

    if (result && result.exceptionDetails) {
      return {
        ok: false,
        error: result.exceptionDetails.text || 'js_exception',
        details: result.exceptionDetails,
      }
    }
    return {
      ok: true,
      result: (result && result.result) || null,
      url: w.win.webContents.getURL(),
    }
  } catch (err) {
    try { _cdpDetach(w.win) } catch (_) { /* ignore */ }
    return { ok: false, error: err instanceof Error ? err.message : String(err) }
  }
}

// 7. fillForm — combina type + select para multiples campos
async function fillForm(opts, localTools) {
  const gate = permGate(localTools)
  if (!gate.ok) return gate
  const w = requireWindow()
  if (!w.ok) return w
  const fields = opts.fields
  if (!fields || typeof fields !== 'object' || Array.isArray(fields)) {
    return { ok: false, error: 'fields_object_required_ej: {"#name": "Juan", "#email": "a@b.com"}' }
  }
  const entries = Object.entries(fields)
  if (entries.length === 0) return { ok: false, error: 'fields_empty' }
  const submitSelector = String(opts.submit || '').trim()
  try {
    const results = []
    for (const [selector, value] of entries) {
      const result = await w.win.webContents.executeJavaScript(
        `(() => {
          const el = document.querySelector(${JSON.stringify(selector)});
          if (!el) return { ok: false, error: 'element_not_found', selector: ${JSON.stringify(selector)} };
          const strVal = ${JSON.stringify(String(value))};
          el.focus();
          if ('value' in el && el.tagName !== 'SELECT') {
            el.value = '';
            el.value = strVal;
            el.dispatchEvent(new Event('input', { bubbles: true }));
            el.dispatchEvent(new Event('change', { bubbles: true }));
          } else if (el.tagName === 'SELECT') {
            let found = false;
            for (let i = 0; i < el.options.length; i++) {
              if (el.options[i].text === strVal || el.options[i].value === strVal) {
                el.selectedIndex = i;
                el.dispatchEvent(new Event('change', { bubbles: true }));
                found = true;
                break;
              }
            }
            if (!found) return { ok: false, error: 'option_not_found', selector: ${JSON.stringify(selector)} };
          } else {
            el.textContent = strVal;
          }
          return { ok: true, selector: ${JSON.stringify(selector)}, tag: el.tagName };
        })()`,
        true,
      )
      results.push({
        selector,
        value: String(value),
        ok: !!(result && result.ok),
        error: (result && result.error) || undefined,
      })
      await new Promise((r) => setTimeout(r, 150))
    }

    let submitted = false
    if (submitSelector) {
      const clickResult = await w.win.webContents.executeJavaScript(
        `(() => {
          const el = document.querySelector(${JSON.stringify(submitSelector)});
          if (el) { el.click(); return true; }
          return false;
        })()`,
        true,
      )
      submitted = !!clickResult
      if (submitted) await new Promise((r) => setTimeout(r, 800))
    }

    return {
      ok: true,
      filled: results,
      submitted,
      submitSelector: submitSelector || null,
      url: w.win.webContents.getURL(),
    }
  } catch (err) {
    return { ok: false, error: err instanceof Error ? err.message : String(err) }
  }
}

// 8. waitForNavigation — espera Page.frameStoppedLoading via CDP
async function waitForNavigation(opts, localTools) {
  const gate = permGate(localTools)
  if (!gate.ok) return gate
  const w = requireWindow()
  if (!w.ok) return w
  const timeoutMs = Math.min(Number(opts.timeoutMs) || 30_000, 90_000)
  try {
    _cdpAttach(w.win)
    await _cdpSend(w.win, 'Page.enable', {}, 5_000)

    await new Promise((resolve, reject) => {
      const timer = setTimeout(() => {
        reject(new Error('navigation_timeout'))
      }, timeoutMs)

      const handler = (_event, method) => {
        if (method === 'Page.frameStoppedLoading') {
          clearTimeout(timer)
          w.win.webContents.debugger.removeListener('message', handler)
          resolve()
        }
      }
      w.win.webContents.debugger.on('message', handler)
    })

    _cdpDetach(w.win)
    // breve espera post-navegacion para JS
    await new Promise((r) => setTimeout(r, 500))
    return {
      ok: true,
      url: w.win.webContents.getURL(),
      title: w.win.webContents.getTitle() || '',
    }
  } catch (err) {
    try { _cdpDetach(w.win) } catch (_) { /* ignore */ }
    const msg = err instanceof Error ? err.message : String(err)
    if (msg === 'navigation_timeout') {
      return { ok: false, error: 'navigation_timeout', url: w.win.webContents.getURL() }
    }
    return { ok: false, error: msg }
  }
}

// 9. getPageTitle — Runtime.evaluate document.title
async function getPageTitle(opts, localTools) {
  const gate = permGate(localTools)
  if (!gate.ok) return gate
  const w = requireWindow()
  if (!w.ok) return w
  try {
    _cdpAttach(w.win)
    const result = await _cdpSend(w.win, 'Runtime.evaluate', {
      expression: 'document.title',
      returnByValue: true,
    })
    _cdpDetach(w.win)
    const title =
      (result && result.result && result.result.value) ||
      w.win.webContents.getTitle() ||
      ''
    return { ok: true, title, url: w.win.webContents.getURL() }
  } catch (err) {
    try { _cdpDetach(w.win) } catch (_) { /* ignore */ }
    // fallback no-CDP
    return {
      ok: true,
      title: w.win.webContents.getTitle() || '',
      url: w.win.webContents.getURL(),
    }
  }
}

// 10. getPageURL — Runtime.evaluate window.location.href
async function getPageURL(opts, localTools) {
  const gate = permGate(localTools)
  if (!gate.ok) return gate
  const w = requireWindow()
  if (!w.ok) return w
  try {
    _cdpAttach(w.win)
    const result = await _cdpSend(w.win, 'Runtime.evaluate', {
      expression: 'window.location.href',
      returnByValue: true,
    })
    _cdpDetach(w.win)
    const url =
      (result && result.result && result.result.value) ||
      w.win.webContents.getURL() ||
      ''
    return { ok: true, url }
  } catch (err) {
    try { _cdpDetach(w.win) } catch (_) { /* ignore */ }
    return { ok: true, url: w.win.webContents.getURL() || '' }
  }
}

// 11. selectOption — selecciona opcion en <select> vía CDP Runtime.evaluate
async function selectOption(opts, localTools) {
  const gate = permGate(localTools)
  if (!gate.ok) return gate
  const w = requireWindow()
  if (!w.ok) return w
  const selector = String(opts.selector || '').trim()
  const value = String(opts.value ?? opts.text ?? '')
  if (!selector) return { ok: false, error: 'selector_required' }
  if (!value) return { ok: false, error: 'value_required' }
  try {
    _cdpAttach(w.win)
    const safeSel = JSON.stringify(selector)
    const safeVal = JSON.stringify(value)
    const result = await _cdpSend(
      w.win,
      'Runtime.evaluate',
      {
        expression:
          `(() => { const el = document.querySelector(${safeSel}); if (!el) return { ok: false, error: 'element_not_found' }; if (el.tagName !== 'SELECT') return { ok: false, error: 'not_a_select_element', tag: el.tagName }; const val = ${safeVal}; for (let i = 0; i < el.options.length; i++) { if (el.options[i].value === val || el.options[i].text === val) { el.selectedIndex = i; el.dispatchEvent(new Event('change', { bubbles: true })); return { ok: true, selected: el.options[i].text, index: i }; } } return { ok: false, error: 'option_not_found' }; })()`,
        returnByValue: true,
      },
    )
    _cdpDetach(w.win)

    if (result && result.exceptionDetails) {
      return { ok: false, error: result.exceptionDetails.text || 'select_exception' }
    }
    const outcome = (result && result.result && result.result.value) || null
    if (!outcome || !outcome.ok) {
      return { ok: false, error: (outcome && outcome.error) || 'select_failed' }
    }
    return {
      ok: true,
      selector,
      selected: outcome.selected,
      index: outcome.index,
      url: w.win.webContents.getURL(),
    }
  } catch (err) {
    try { _cdpDetach(w.win) } catch (_) { /* ignore */ }
    return { ok: false, error: err instanceof Error ? err.message : String(err) }
  }
}

// 12. hover — DOM.getBoxModel + Input.dispatchMouseEvent mouseMoved
async function hover(opts, localTools) {
  const gate = permGate(localTools)
  if (!gate.ok) return gate
  const w = requireWindow()
  if (!w.ok) return w
  const selector = String(opts.selector || '').trim()
  if (!selector) return { ok: false, error: 'selector_required' }
  try {
    _cdpAttach(w.win)

    // obtener nodeId via DOM.querySelector
    const doc = await _cdpSend(w.win, 'DOM.getDocument', { depth: 0 })
    if (!doc || !doc.root) {
      _cdpDetach(w.win)
      return { ok: false, error: 'dom_getDocument_failed' }
    }
    const qs = await _cdpSend(w.win, 'DOM.querySelector', {
      nodeId: doc.root.nodeId,
      selector,
    })
    if (!qs || !qs.nodeId) {
      _cdpDetach(w.win)
      return { ok: false, error: 'element_not_found' }
    }

    // obtener coordenadas via getBoxModel
    let cx
    let cy
    try {
      const box = await _cdpSend(w.win, 'DOM.getBoxModel', { nodeId: qs.nodeId })
      if (box && box.model && box.model.content) {
        const [x1, y1, x2, y2, , , ,] = box.model.content
        cx = Math.round((x1 + x2) / 2)
        cy = Math.round((y1 + y2) / 2)
      }
    } catch (_) {
      // getBoxModel falló, usar fallback
    }

    if (cx !== undefined && cy !== undefined) {
      // hover via CDP mouse event
      await _cdpSend(w.win, 'Input.dispatchMouseEvent', {
        type: 'mouseMoved',
        x: cx,
        y: cy,
        modifiers: 0,
      })
      _cdpDetach(w.win)
      return { ok: true, selector, position: { x: cx, y: cy }, url: w.win.webContents.getURL() }
    }

    _cdpDetach(w.win)

    // fallback via executeJavaScript (DOM events)
    const result = await w.win.webContents.executeJavaScript(
      `(() => {
        const el = document.querySelector(${JSON.stringify(selector)});
        if (!el) return { ok: false, error: 'element_not_found' };
        el.scrollIntoView({ block: 'center', inline: 'center' });
        el.dispatchEvent(new MouseEvent('mouseover', { bubbles: true, cancelable: true }));
        el.dispatchEvent(new MouseEvent('mouseenter', { bubbles: false, cancelable: true }));
        return { ok: true };
      })()`,
      true,
    )
    if (!result || !result.ok) {
      return { ok: false, error: (result && result.error) || 'hover_failed' }
    }
    return { ok: true, selector, via: 'dom_events', url: w.win.webContents.getURL() }
  } catch (err) {
    try { _cdpDetach(w.win) } catch (_) { /* ignore */ }
    return { ok: false, error: err instanceof Error ? err.message : String(err) }
  }
}

// 13. pressKey — Input.dispatchKeyEvent para teclas especiales
async function pressKey(opts, localTools) {
  const gate = permGate(localTools)
  if (!gate.ok) return gate
  const w = requireWindow()
  if (!w.ok) return w
  const key = String(opts.key || '').trim().toLowerCase()
  if (!key) return { ok: false, error: 'key_required' }

  // Mapa de teclas comunes → CDP key codes (Windows)
  const KEY_MAP = {
    enter: { windowsVirtualKeyCode: 13, code: 'Enter', key: 'Enter', text: '\r' },
    tab: { windowsVirtualKeyCode: 9, code: 'Tab', key: 'Tab' },
    escape: { windowsVirtualKeyCode: 27, code: 'Escape', key: 'Escape' },
    esc: { windowsVirtualKeyCode: 27, code: 'Escape', key: 'Escape' },
    backspace: { windowsVirtualKeyCode: 8, code: 'Backspace', key: 'Backspace' },
    delete: { windowsVirtualKeyCode: 46, code: 'Delete', key: 'Delete' },
    del: { windowsVirtualKeyCode: 46, code: 'Delete', key: 'Delete' },
    arrowup: { windowsVirtualKeyCode: 38, code: 'ArrowUp', key: 'ArrowUp' },
    arrowdown: { windowsVirtualKeyCode: 40, code: 'ArrowDown', key: 'ArrowDown' },
    arrowleft: { windowsVirtualKeyCode: 37, code: 'ArrowLeft', key: 'ArrowLeft' },
    arrowright: { windowsVirtualKeyCode: 39, code: 'ArrowRight', key: 'ArrowRight' },
    up: { windowsVirtualKeyCode: 38, code: 'ArrowUp', key: 'ArrowUp' },
    down: { windowsVirtualKeyCode: 40, code: 'ArrowDown', key: 'ArrowDown' },
    left: { windowsVirtualKeyCode: 37, code: 'ArrowLeft', key: 'ArrowLeft' },
    right: { windowsVirtualKeyCode: 39, code: 'ArrowRight', key: 'ArrowRight' },
    space: { windowsVirtualKeyCode: 32, code: 'Space', key: ' ' },
    home: { windowsVirtualKeyCode: 36, code: 'Home', key: 'Home' },
    end: { windowsVirtualKeyCode: 35, code: 'End', key: 'End' },
    pageup: { windowsVirtualKeyCode: 33, code: 'PageUp', key: 'PageUp' },
    pagedown: { windowsVirtualKeyCode: 34, code: 'PageDown', key: 'PageDown' },
    f5: { windowsVirtualKeyCode: 116, code: 'F5', key: 'F5' },
    'ctrl+a': { windowsVirtualKeyCode: 65, code: 'KeyA', key: 'a', modifiers: 2 },
    'ctrl+c': { windowsVirtualKeyCode: 67, code: 'KeyC', key: 'c', modifiers: 2 },
    'ctrl+v': { windowsVirtualKeyCode: 86, code: 'KeyV', key: 'v', modifiers: 2 },
    'ctrl+x': { windowsVirtualKeyCode: 88, code: 'KeyX', key: 'x', modifiers: 2 },
    'ctrl+z': { windowsVirtualKeyCode: 90, code: 'KeyZ', key: 'z', modifiers: 2 },
  }

  const keyDef = KEY_MAP[key]
  if (!keyDef) {
    const supported = Object.keys(KEY_MAP).join(', ')
    return { ok: false, error: `unsupported_key:${key}. Soportadas: ${supported}` }
  }

  try {
    _cdpAttach(w.win)
    const modifiers = keyDef.modifiers || 0
    // keyDown
    await _cdpSend(w.win, 'Input.dispatchKeyEvent', {
      type: 'keyDown',
      windowsVirtualKeyCode: keyDef.windowsVirtualKeyCode,
      code: keyDef.code,
      key: keyDef.key,
      modifiers,
      text: keyDef.text,
    })
    // keyUp
    await _cdpSend(w.win, 'Input.dispatchKeyEvent', {
      type: 'keyUp',
      windowsVirtualKeyCode: keyDef.windowsVirtualKeyCode,
      code: keyDef.code,
      key: keyDef.key,
      modifiers,
    })
    _cdpDetach(w.win)
    return { ok: true, key, code: keyDef.code, modifiers, url: w.win.webContents.getURL() }
  } catch (err) {
    try { _cdpDetach(w.win) } catch (_) { /* ignore */ }
    return { ok: false, error: err instanceof Error ? err.message : String(err) }
  }
}

// 14. uploadFile — DOM.setFileInputFiles + DOM.querySelector
async function uploadFile(opts, localTools) {
  const gate = permGate(localTools)
  if (!gate.ok) return gate
  const w = requireWindow()
  if (!w.ok) return w
  const selector = String(opts.selector || 'input[type="file"]').trim()
  const filePath = String(opts.filepath || opts.file_path || '').trim()
  if (!filePath) return { ok: false, error: 'filepath_required' }

  // resolver ruta absoluta
  const absolutePath = path.isAbsolute(filePath)
    ? filePath
    : path.join(localTools.getDesktopPath ? localTools.getDesktopPath() : process.cwd(), filePath)

  if (!fs.existsSync(absolutePath)) {
    return { ok: false, error: 'file_not_found', path: absolutePath }
  }

  try {
    _cdpAttach(w.win)

    const doc = await _cdpSend(w.win, 'DOM.getDocument', { depth: 0 })
    if (!doc || !doc.root) {
      _cdpDetach(w.win)
      return { ok: false, error: 'dom_getDocument_failed' }
    }

    const qs = await _cdpSend(w.win, 'DOM.querySelector', {
      nodeId: doc.root.nodeId,
      selector,
    })

    if (!qs || !qs.nodeId) {
      _cdpDetach(w.win)
      return { ok: false, error: 'file_input_not_found', selector }
    }

    await _cdpSend(w.win, 'DOM.setFileInputFiles', {
      files: [absolutePath],
      nodeId: qs.nodeId,
    })

    _cdpDetach(w.win)
    return {
      ok: true,
      selector,
      file: absolutePath,
      url: w.win.webContents.getURL(),
    }
  } catch (err) {
    try { _cdpDetach(w.win) } catch (_) { /* ignore */ }
    return { ok: false, error: err instanceof Error ? err.message : String(err) }
  }
}

// 15. stealth — Page.addScriptToEvaluateOnNewDocument + inyeccion inmediata
async function stealth(opts, localTools) {
  const gate = permGate(localTools)
  if (!gate.ok) return gate
  const w = requireWindow()
  if (!w.ok) return w

  const script = `
(() => {
  // Oculta webdriver
  Object.defineProperty(navigator, 'webdriver', { get: () => false });

  // Simula plugins
  Object.defineProperty(navigator, 'plugins', {
    get: () => {
      return {
        0: { name: 'Chrome PDF Plugin', filename: 'internal-pdf-viewer', description: 'Portable Document Format' },
        1: { name: 'Chrome PDF Viewer', filename: 'mhjfbmdgcfjbbpaeojofohoefgiehjai', description: '' },
        2: { name: 'Native Client', filename: 'internal-nacl-plugin', description: '' },
        length: 3,
        item: function(i) { return this[i]; },
        namedItem: function(name) { return null; },
        refresh: function() {}
      };
    }
  });

  // Simula languages
  Object.defineProperty(navigator, 'languages', { get: () => ['es-VE', 'es', 'en-US', 'en'] });
  Object.defineProperty(navigator, 'language', { get: () => 'es-VE' });

  // Simula chrome object
  window.chrome = {
    runtime: {},
    loadTimes: function() {},
    csi: function() {},
    app: {}
  };

  // Simula permissions.query
  const origQuery = window.navigator.permissions.query;
  window.navigator.permissions.query = (parameters) => (
    parameters && parameters.name === 'notifications'
      ? Promise.resolve({ state: Notification.permission, onchange: null })
      : origQuery(parameters)
  );

  // Simula hardwareConcurrency
  Object.defineProperty(navigator, 'hardwareConcurrency', { get: () => 8 });

  // Simula deviceMemory
  Object.defineProperty(navigator, 'deviceMemory', { get: () => 8 });

  // Simula platform
  Object.defineProperty(navigator, 'platform', { get: () => 'Win32' });

  // Simula vendor
  Object.defineProperty(navigator, 'vendor', { get: () => 'Google Inc.' });

  // Pasa pruebas de bot comunes
  if (window.Notification && window.Notification.permission === 'default') {
    Object.defineProperty(Notification, 'permission', { get: () => 'default' });
  }

  // Elimina trazas de Electron
  delete window.__ELECTRON__;
  delete window.process;
})()
  `.trim()

  try {
    // Inyeccion para TODAS las paginas futuras (CDP)
    _cdpAttach(w.win)
    await _cdpSend(w.win, 'Page.addScriptToEvaluateOnNewDocument', {
      source: script,
    })
    // Tambien inyectar en la pagina actual si ya hay una abierta
    try {
      await w.win.webContents.executeJavaScript(script, true)
    } catch (_) {
      // la pagina puede no tener contenido aun — ignorar
    }
    _cdpDetach(w.win)

    return {
      ok: true,
      message: 'Modo stealth activado — navegador parece Chrome real (no Electron)',
      injected: [
        'navigator.webdriver=false',
        'plugins simulados',
        'languages: es-VE',
        'chrome.runtime presente',
        'permissions.query normalizado',
        'hardwareConcurrency=8',
        'Sin trazas Electron',
      ],
      url: w.win.webContents.getURL(),
    }
  } catch (err) {
    try { _cdpDetach(w.win) } catch (_) { /* ignore */ }
    return { ok: false, error: err instanceof Error ? err.message : String(err) }
  }
}

// 16. screenshotElement — captura CDP de un elemento especifico (DOM.getDocument + DOM.querySelector + DOM.getBoxModel + Page.captureScreenshot clip)
async function screenshotElement(opts, localTools) {
  const gate = permGate(localTools)
  if (!gate.ok) return gate
  const w = requireWindow()
  if (!w.ok) return w
  const selector = String(opts.selector || '').trim()
  if (!selector) return { ok: false, error: 'selector_required' }

  try {
    _cdpAttach(w.win)

    // 1. Obtener documento raiz
    const doc = await _cdpSend(w.win, 'DOM.getDocument', { depth: 0 })
    if (!doc || !doc.root) {
      _cdpDetach(w.win)
      return { ok: false, error: 'dom_getDocument_failed' }
    }

    // 2. Buscar elemento por selector
    const qs = await _cdpSend(w.win, 'DOM.querySelector', {
      nodeId: doc.root.nodeId,
      selector,
    })
    if (!qs || !qs.nodeId) {
      _cdpDetach(w.win)
      return { ok: false, error: 'element_not_found' }
    }

    // 3. Obtener coordenadas del elemento
    const box = await _cdpSend(w.win, 'DOM.getBoxModel', { nodeId: qs.nodeId })
    if (!box || !box.model) {
      _cdpDetach(w.win)
      return { ok: false, error: 'box_model_not_available' }
    }

    // 4. Extraer rect del content quad
    const [x1, y1, x2, y2, x3, y3, x4, y4] = box.model.content
    const top = Math.round(Math.min(y1, y3))
    const left = Math.round(Math.min(x1, x3))
    const width = Math.round(Math.max(x2, x4) - left)
    const height = Math.round(Math.max(y2, y4) - top)

    // 5. Screenshot con clip exacto del elemento
    const result = await _cdpSend(w.win, 'Page.captureScreenshot', {
      format: String(opts.format || 'png'),
      clip: {
        x: left,
        y: top,
        width: Math.max(width, 1),
        height: Math.max(height, 1),
        scale: Number(opts.scale) || 1,
      },
    })
    _cdpDetach(w.win)

    if (result && result.data) {
      return {
        ok: true,
        screenshot_base64: result.data,
        format: opts.format || 'png',
        selector,
        dimensions: { x: left, y: top, width, height },
        url: w.win.webContents.getURL(),
      }
    }
    return { ok: false, error: 'screenshot_element_failed' }
  } catch (err) {
    try { _cdpDetach(w.win) } catch (_) { /* ignore */ }
    return { ok: false, error: err instanceof Error ? err.message : String(err) }
  }
}

// 17. fillFormAdvanced — rellena formulario via CDP por campo (DOM.querySelector + Runtime.evaluate con input/change events)
async function fillFormAdvanced(opts, localTools) {
  const gate = permGate(localTools)
  if (!gate.ok) return gate
  const w = requireWindow()
  if (!w.ok) return w
  const fields = opts.fields
  if (!fields || !Array.isArray(fields) || fields.length === 0) {
    return { ok: false, error: 'fields_array_required_ej: [{"selector":"#name","value":"Juan"}]' }
  }
  try {
    _cdpAttach(w.win)
    let filled = 0
    const results = []
    for (const field of fields) {
      const selector = String(field.selector || '').trim()
      const value = String(field.value ?? '')
      if (!selector) {
        results.push({ selector: '', value, ok: false, error: 'selector_required' })
        continue
      }
      try {
        // Verificar que el elemento existe via CDP DOM
        const doc = await _cdpSend(w.win, 'DOM.getDocument', { depth: 0 })
        if (!doc || !doc.root) {
          results.push({ selector, value, ok: false, error: 'dom_getDocument_failed' })
          continue
        }
        const qs = await _cdpSend(w.win, 'DOM.querySelector', {
          nodeId: doc.root.nodeId,
          selector,
        })
        if (!qs || !qs.nodeId) {
          results.push({ selector, value, ok: false, error: 'element_not_found' })
          continue
        }
        // Asignar valor + disparar eventos via Runtime.evaluate
        const safeSel = JSON.stringify(selector)
        const safeVal = JSON.stringify(value)
        const evalResult = await _cdpSend(w.win, 'Runtime.evaluate', {
          expression:
            `(() => { const el=document.querySelector(${safeSel}); if(!el) return {ok:false,error:'element_not_found'}; el.focus(); ` +
            `if('value' in el && el.tagName!=='SELECT') { el.value=${safeVal}; el.dispatchEvent(new Event('input',{bubbles:true})); el.dispatchEvent(new Event('change',{bubbles:true})); } ` +
            `else if(el.tagName==='SELECT') { el.value=${safeVal}; el.dispatchEvent(new Event('change',{bubbles:true})); } ` +
            `else { el.textContent=${safeVal}; } return {ok:true,tag:el.tagName}; })()`,
          returnByValue: true,
        })
        const outcome = (evalResult && evalResult.result && evalResult.result.value) || null
        if (outcome && outcome.ok) {
          filled++
          results.push({ selector, value, ok: true, tag: outcome.tag })
        } else {
          results.push({ selector, value, ok: false, error: (outcome && outcome.error) || 'fill_field_failed' })
        }
      } catch (e) {
        results.push({ selector, value, ok: false, error: e instanceof Error ? e.message : String(e) })
      }
    }
    _cdpDetach(w.win)
    return {
      ok: true,
      filled,
      total: fields.length,
      results,
      url: w.win.webContents.getURL(),
    }
  } catch (err) {
    try { _cdpDetach(w.win) } catch (_) { /* ignore */ }
    return { ok: false, error: err instanceof Error ? err.message : String(err) }
  }
}

// ---------------------------------------------------------------
// EXPORTS
// ---------------------------------------------------------------

module.exports = {
  // utilidades
  validateUrl,
  getBrowserWindow,
  ensureBrowserPermission,
  getOrCreateWindow,
  closeBrowser,

  // M1S1 — operaciones base (8)
  navigate,
  extract,
  click,
  type,
  waitFor,
  extractPrice,
  screenshot,
  close: closeBrowser,

  // BR04 — single-field fill
  fill,

  // BR05/BR06 — session management
  openSession,
  doAction,
  closeSessionExtract,

  // M1S2-A — nuevas operaciones CDP (15)
  pdf,
  getCookies,
  setCookies,
  scroll,
  networkIntercept,
  executeJS,
  fillForm,
  waitForNavigation,
  getPageTitle,
  getPageURL,
  selectOption,
  hover,
  pressKey,
  uploadFile,
  stealth,

  // M1S2-B — operaciones CDP adicionales (2)
  screenshotElement,
  fillFormAdvanced,
}
