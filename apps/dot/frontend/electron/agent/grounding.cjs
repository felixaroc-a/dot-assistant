// grounding.cjs — Anclaje a evidencia de tools: evita informes con rutas inventadas.
//
// Portado de grounding.py + runtime.py (Fase 2.1 M2S4-A).
// Contiene las heurísticas de grounding/truth-check que el agent-loop.cjs
// necesita para detectar alucinaciones y forzar acciones faltantes.
//
// Uso: const grounding = require('./grounding.cjs');
//
// ─── Funciones portadas ───────────────────────────────────
// Desde runtime.py:
//   _detect_fabricated_data(), _FABRICATION_PATTERNS
//   _looks_incomplete_final(), _INCOMPLETE_FINAL_RE
//   _wants_url_download, _wants_gmail_reply, _wants_gmail_bulk_archive
//   _wants_gmail_inbox, _wants_read_and_wa (whatsapp_notify intent)
//   _maybe_force_download()
//   _ensure_whatsapp_notify(), _ensure_calendar_notify()
//
// Desde grounding.py:
//   looks_ungrounded_final, _detect_general_fabrication, _UNGOUNDED_EXTRAS
//   evidence_blob_from_trace, extract_claimed_paths, ungrounded_paths
//   path_supported_by_evidence, is_analysis_mission, wrote_ok, read_ok
//   extract_saved_path_from_trace, repair_saved_path_claim
//
// Dependencias de soporte:
//   _wants_desktop_save, _wants_desktop_pdf_read
//   _wants_generate_and_wa_doc, _wants_smart_calendar
//   _GMAIL_REPLY_INTENT_RE, _GMAIL_ARCHIVE_INTENT_RE, _GMAIL_INBOX_INTENT_RE
//   _WA_NOTIFY_INTENT_RE, _READ_DOC_INTENT_RE, _SAVE_INTENT_RE, _DESKTOP_RE
//   _DOWNLOAD_VERB_RE, _url_re, _PDF_RE, _FILENAME_RE, _FILENAME_BARE_RE
//   _CON_CONTENT_RE, _GENERATE_DOC_INTENT_RE, _REPORT_DOC_INTENT_RE
//   _GMAIL_ATTACH_INTENT_RE, _SEARCH_INTENT_RE
//   _CALENDAR_CREATE_INTENT_RE, _CALENDAR_REMIND_INTENT_RE
//   _wrote_ok_fn, _read_doc_ok_fn, _wa_sent_ok_fn, _generated_doc_ok_fn
//   _wa_doc_sent_ok_fn, _calendar_event_created_ok_fn, _calendar_notify_done_fn
//   _gmail_listed_or_searched_ok_fn, _gmail_read_ok_fn, _gmail_replied_ok_fn
//   _gmail_archived_ok_fn, _gmail_tool_used_fn
//   _extract_download_url, _desktop_path_for_url, _latest_user_utterance
//   _extract_desktop_filename, _extract_inline_content, _clean_summary_for_file
//   _extract_read_preview, _summary_for_wa, _extract_calendar_event_from_trace
//   _calendar_confirmation_message
//

'use strict';

// ═══════════════════════════════════════════════════════════
//  IMPORTACIONES
// ═══════════════════════════════════════════════════════════

const { URL } = require('url');

// ═══════════════════════════════════════════════════════════
//  HELPERS COMPARTIDOS (local, sin depender de agent-loop.cjs)
// ═══════════════════════════════════════════════════════════

/**
 * Elimina el bloque JSON de tool_calls del contenido.
 * Espejo de stripToolCallsJson en agent-loop.cjs.
 * @param {string} content
 * @returns {string}
 */
function stripToolCallsJson(content) {
  return (content || '')
    .replace(/```json\s*[\s\S]*?```/g, '')
    .replace(/\{\s*"tool_calls"\s*:\s*\[[\s\S]*?\]\s*\}/g, '')
    .trim();
}

/**
 * Formatea una observación de herramienta.
 * Espejo de formatObservation en agent-loop.cjs.
 * @param {string} toolName
 * @param {boolean} ok
 * @param {string} [output]
 * @param {string} [error]
 * @returns {string}
 */
function formatObservation(toolName, ok, output, error) {
  if (ok) {
    const out = output || 'OK';
    const truncated = out.length > 2500 ? out.slice(0, 2500) + '…' : out;
    return `[${toolName}] ✓ ${truncated}`;
  }
  return `[${toolName}] ✗ ERROR: ${error || 'desconocido'}`;
}

// ═══════════════════════════════════════════════════════════
//  REGEX — Patrones de alucinación (desde runtime.py)
// ═══════════════════════════════════════════════════════════

// Archivos/carpetas inventados
const _FABRICATED_FILE_RE = new RegExp(
  '(?:archivo|archivos|file|files|documento|documentos|carpeta|carpetas)\\s+' +
  '(?:que|en|con|llamado|llamada|como|titulado)[\\s\\S]{0,200}' +
  '(?:\\.pdf|\\.txt|\\.xlsx|\\.docx|\\.py|\\.js|\\.csv|\\.json|\\.html|\\.md)',
  'i'
);

// "Encontré / veo / hallé" sin haber ejecutado tools
const _FABRICATED_FOUND_RE = new RegExp(
  '(?:encontr[éeó]|halle|hall[éeó]|veo|observo|detect[éeó]|localic[éeó])\\s+' +
  '(?:que|un|una|varios|varias|los|las|el|la)\\s',
  'i'
);

// Precios inventados
const _FABRICATED_PRICE_RE = new RegExp(
  '(?:precio|precios|cuesta|cuestan|vale|valen|monto|total)\\s+' +
  '(?:aproximadamente|alrededor|unos|unas|de|es)?\\s*\\$?\\s?\\d[\\d,.]*',
  'i'
);

// "Tienes / hay / existen" + archivos
const _FABRICATED_HAVE_RE = new RegExp(
  '(?:tienes|tiene|hay|existen|cuentas\\s+con)\\s+(?:un|una|varios|varias|los|las|el|la)\\s+' +
  '(?:archivo|archivos|carpeta|carpetas|documento|documentos)',
  'i'
);

// Datos climáticos inventados
const _FABRICATED_WEATHER_RE = new RegExp(
  '(?:clima|temperatura|pron[oó]stico|humedad|viento)\\s+' +
  '(?:actual|hoy|ahora|en\\s+\\w+)\\s+(?:es|est[aá]|de|hay)',
  'i'
);

// "Aquí está tu X" sin haber generado nada
const _FABRICATED_HERE_RE = new RegExp(
  '(?:aqu[ií]\\s+(?:est[aá]|tienes)|te\\s+(?:muestro|presento|comparto|env[ií]o))\\s+(?:tu|el|la|los|las)\\s',
  'i'
);

/** Lista de patrones de alucinación. Espejo de _FABRICATION_PATTERNS en runtime.py. */
const FABRICATION_PATTERNS = [
  _FABRICATED_FILE_RE,
  _FABRICATED_FOUND_RE,
  _FABRICATED_PRICE_RE,
  _FABRICATED_HAVE_RE,
  _FABRICATED_WEATHER_RE,
  _FABRICATED_HERE_RE,
];

// ═══════════════════════════════════════════════════════════
//  REGEX — Patrones de respuesta incompleta (desde runtime.py)
// ═══════════════════════════════════════════════════════════

const INCOMPLETE_FINAL_RE = new RegExp(
  '\\b(' +
  'voy a (usar|listar|leer|analizar|crear|guardar|generar|buscar|enviar|escribir)|' +
  'ahora (voy|procedo|paso|empiezo)|' +
  'siguiente paso|' +
  'todav[ií]a no (pude|puedo|logr[eé])|' +
  'reintent[aá]|' +
  'en el pr[oó]ximo|' +
  'continuar[eé]|' +
  'dame un momento|' +
  'empezar[eé]|' +
  'proceder[eé]|' +
  'enseguida (lo |te )?(hago|analizo|genero)|' +
  'd[eé]jame (revisar|analizar|listar)' +
  ')\\b',
  'i'
);

// ═══════════════════════════════════════════════════════════
//  REGEX — Detección de intención (desde runtime.py)
// ═══════════════════════════════════════════════════════════

const _URL_RE = /https?:\/\/[^\s<>"')\]]+/i;
const _DOWNLOAD_VERB_RE = /\b(descarga|descargar|download|baj[aá]|bajar)\b/i;
const _SAVE_INTENT_RE = /\b(guarda|guardar|crea|crear|escribe|escribir|salv[ae]|save)\b/i;
const _DESKTOP_RE = /\b(escritorio|desktop)\b/i;
const _SEARCH_INTENT_RE = /\b(busca|buscar|noticias|web|internet)\b/i;
const _READ_DOC_INTENT_RE = /\b(lee|leer|l[eé]eme|abre|analiz|revisa|resume|resumir|pdf|documento|docx|excel|xlsx|xls|hoja de c[aá]lculo|curr[ií]culum|cv\b)\b/i;
const _WA_NOTIFY_INTENT_RE = /\b(m[aá]ndame|env[ií]ame|av[ií]same|notif[ií]came|whats?app|wa\b|por\s+whatsapp)\b/i;
const _PDF_RE = /\b(pdf|\.pdf)\b/i;
const _FILENAME_RE = /(?:como|named?|llamad[oa]|archivo\s+)\s*[«"']?([A-Za-z0-9_\-]+\.(?:txt|md|csv))[»"']?/i;
const _FILENAME_BARE_RE = /\b([A-Za-z0-9_\-]{3,80}\.(?:txt|md|csv))\b/i;
const _CON_CONTENT_RE = /\bcon\s+(.+?)\s*$/is;
const _GENERATE_DOC_INTENT_RE = /\b(genera|generar|crea|crear|elabora|elaborar|prepara|preparar|redacta|haz|hacer)\b/i;
const _REPORT_DOC_INTENT_RE = /\b(informe|reporte|documento|docx|pdf|pptx|presentaci[oó]n|excel|xlsx|hoja)\b/i;
const _GMAIL_ATTACH_INTENT_RE = /\b(adjunt|adjunta|adjunto|attachment)\b/i;

const _CALENDAR_CREATE_INTENT_RE = new RegExp(
  '\\b(' +
  'agenda|agendar|agend[aá]|programa|programar|crea|crear|pon|poner|' +
  'marc[aá]|reserva|reservar|aparta|apartar|bloquea|bloquear' +
  ')\\b.*\\b(' +
  'reuni[oó]n|cita|evento|compromiso|call|llamada|calendario' +
  ')\\b|' +
  '\\b(reuni[oó]n|cita|evento)\\b.*\\b(' +
  'agenda|agendar|programa|programar|ma[nñ]ana|pasado\\s+ma[nñ]ana|' +
  'lunes|martes|mi[eé]rcoles|jueves|viernes|s[aá]bado|domingo|' +
  'a\\s+las\\s+\\d|@\\d' +
  ')\\b',
  'i'
);

const _CALENDAR_REMIND_INTENT_RE = /\b(recu[eé]rdame|recordatorio|recuerdo|av[ií]same|notif[ií]came|av[ií]so|alerta)\b/i;

const _GMAIL_REPLY_INTENT_RE = new RegExp(
  '\\b(responde|responder|contesta|contestar|replica|replicar|reply)\\b' +
  '.*\\b(correo|correos|email|mail|mensaje)\\b|' +
  '\\b(correo|email|mail)\\b.*\\b(responde|responder|contesta|contestar)\\b',
  'i'
);

const _GMAIL_ARCHIVE_INTENT_RE = new RegExp(
  '\\b(archiva|archivar|limpia|limpiar|mueve|mover|saca|sacar)\\b' +
  '.*\\b(correo|correos|email|spam|promoc|basura|newsletter|publicidad|bandeja)\\b|' +
  '\\b(spam|promociones|newsletters?|publicidad)\\b.*\\b(archiva|archivar|elimina|borra|limpia|limpiar)\\b',
  'i'
);

const _GMAIL_INBOX_INTENT_RE = new RegExp(
  '\\b(correo|correos|email|emails|gmail|bandeja|inbox)\\b.*\\b(' +
  'no\\s+le[ií]d|sin\\s+leer|nuevos?|pendientes?|tengo|importantes?' +
  ')\\b|' +
  '\\b(qu[eé]\\s+tengo|revisa|revisar|mu[eé]strame|lista|listar)\\b.*\\b(' +
  'correo|correos|email|gmail|bandeja' +
  ')\\b|' +
  '\\b(correos?\\s+sin\\s+leer|bandeja\\s+de\\s+entrada)\\b',
  'i'
);

const GENERATED_DOC_TOOLS = new Set([
  'generate_document',
  'pptx_generate',
  'generate_spreadsheet',
]);

const CONTINUE_AFTER_TOOLS =
  'Continúa la misión hasta terminarla del todo. ' +
  'Si falta trabajo, emite más tool_calls. ' +
  'Si ya terminaste, escribe la respuesta FINAL completa y útil al usuario ' +
  '(hallazgos, rutas, resumen extendido). ' +
  'Prohibido cortar con "voy a…" o pedir que reintente.';

const NUDGE_INCOMPLETE =
  'Tu respuesta anterior quedó incompleta o aplazó el trabajo. ' +
  'NO digas qué vas a hacer: hazlo ahora con tools si hace falta, ' +
  'y luego entrega el resultado FINAL completo en español.';

// ═══════════════════════════════════════════════════════════
//  REGEX — Patrones de grounding (desde grounding.py)
// ═══════════════════════════════════════════════════════════

const _ANALYSIS_INTENT = /\b(analiz|informe|reporte|auditor[ií]a|mejorar[ií]as?|code\s*review|revis(a|ar)\s+(el\s+)?(c[oó]digo|proyecto|carpeta)|qu[eé]\s+mejorar[ií]as)\b/i;

const _CLAIMED_PATH_RE = new RegExp(
  '(?:' +
  '`([^`\\n]{3,180}\\.(?:py|ts|tsx|js|cjs|mjs|md|yml|yaml|toml|json|css|html))`' +
  '|' +
  '((?:apps|docs|services|frontend|packages|infra|auto-venta1|' +
  'Chatbot-Cobro|graphify-out)[/\\\\][A-Za-z0-9_.\\\\/-]{2,160}\\.' +
  '(?:py|ts|tsx|js|cjs|mjs|md|yml|yaml|toml|json|css))' +
  '|' +
  '((?:[A-Za-z]:)?[/\\\\]Users[/\\\\][^\\s|*]{5,200}\\.' +
  '(?:py|ts|tsx|js|cjs|md|docx|pdf|yml|yaml|toml|json))' +
  ')',
  'i'
);

const _DOCX_CLAIM_RE = /(?:\.docx\b|documento creado|informe completo se encuentra|guardado en|ruta:\s*|se encuentra en)/i;

const _SAVE_PATH_FROM_TOOL = /^(?:Ruta|Archivo guardado en|Documento creado)[:\s]+(.+)$/im;

// Patrones adicionales de alucinación en respuestas finales (desde grounding.py)
const _UNGROUNDED_EXTRAS = [
  { pattern: /(?:cuesta|vale|precio|monto|total)\s+(?:aproximadamente|alrededor|de|es)?\s*\$?\s?\d[\d,.]*(?:\s*(?:USD|EUR|bs|bol[ií]vares|d[oó]lares))?/i, label: 'precio sin fuente' },
  { pattern: /el\s+archivo\s+["']?[\w\-]+\.(?:pdf|txt|xlsx|docx|py|js|csv|json)["']?/i, label: 'archivo mencionado sin evidencia de lectura' },
  { pattern: /(?:visita|revisa|mira|consulta)\s+(?:https?:\/\/[^\s]+|el\s+sitio\s+web)/i, label: 'URL sugerida sin fetch' },
  { pattern: /(?:clima|temperatura|pron[oó]stico)\s+(?:actual|hoy|ahora|en\s+\w+)\s+(?:es|est[aá]|de)\s+\d+/i, label: 'clima sin consultar API' },
  { pattern: /(?:escane[éeé]|analic[éeé]|revis[éeé])\s+(?:tu|el|la)\s+(?:PC|computador|escritorio|disco)/i, label: 'escaneo inventado sin herramientas' },
];

// ═══════════════════════════════════════════════════════════
//  HELPERS DE TEXTO
// ═══════════════════════════════════════════════════════════

/**
 * Evita que el historial dispare force_download / bloquee write.
 * Espejo de _latest_user_utterance() en runtime.py.
 * @param {string} text
 * @returns {string}
 */
function latestUserUtterance(text) {
  const raw = (text || '').trim();
  const marker = 'Nuevo mensaje del usuario:';
  const idx = raw.lastIndexOf(marker);
  if (idx !== -1) {
    return raw.slice(idx + marker.length).trim();
  }
  return raw;
}

/**
 * Extrae la primera URL del texto.
 * Espejo de _extract_download_url() en runtime.py.
 * @param {string} text
 * @returns {string|null}
 */
function extractDownloadUrl(text) {
  const m = _URL_RE.exec(text || '');
  if (!m) return null;
  return m[0].replace(/[.,;:)]+$/, '');
}

/**
 * Genera ruta en ~/Desktop para una URL.
 * Espejo de _desktop_path_for_url() en runtime.py.
 * @param {string} url
 * @returns {string}
 */
function desktopPathForUrl(url) {
  let path;
  try {
    path = decodeURIComponent(new URL(url).pathname || '');
  } catch {
    path = '';
  }
  let base = path.split('/').pop() || '';
  if (!base || !base.includes('.')) {
    base = `dot-download-${Date.now()}.bin`;
  }
  const safe = base.replace(/[<>:"|?*\\]/g, '_').slice(0, 120);
  return `~/Desktop/${safe}`;
}

/**
 * Extrae nombre de archivo para guardar en Escritorio.
 * Espejo de _extract_desktop_filename() en runtime.py.
 * @param {string} text
 * @returns {string}
 */
function extractDesktopFilename(text) {
  const t = latestUserUtterance(text);
  const m = _FILENAME_RE.exec(t);
  if (m) return m[1].trim();
  const m2 = _FILENAME_BARE_RE.exec(t);
  if (m2) return m2[1].trim();
  return `dot-nota-${Date.now()}.txt`;
}

/**
 * Extrae contenido inline: "crea X en Escritorio con hola" → "hola".
 * Espejo de _extract_inline_content() en runtime.py.
 * @param {string} text
 * @returns {string|null}
 */
function extractInlineContent(text) {
  const t = latestUserUtterance(text);
  if (_SEARCH_INTENT_RE.test(t)) return null;
  const m = _CON_CONTENT_RE.exec(t);
  if (!m) return null;
  const content = m[1].trim().replace(/[«»"']/g, '');
  if (content.length < 1 || content.length > 4000) return null;
  if (/\b(escritorio|desktop|archivo)\b/i.test(content)) return null;
  return content;
}

/**
 * Limpia el texto final quitando restos de JSON tool_calls y frases vacías.
 * Espejo de _clean_summary_for_file() en runtime.py.
 * @param {string} text
 * @returns {string}
 */
function cleanSummaryForFile(text) {
  let raw = stripToolCallsJson(text || '') || (text || '');
  raw = raw.replace(
    /\{[\s\S]*"action"\s*:\s*"(?:local_tool|gmail_send|create_document)"[\s\S]*\}/gi,
    ''
  ).trim();
  const lines = raw.split('\n').filter(line =>
    !/(?:voy a (usar|guardar|crear)|ejecut[eé] writeFile|tool_calls)/i.test(line)
  );
  return lines.join('\n').trim();
}

// ═══════════════════════════════════════════════════════════
//  HELPERS DE TOOL TRACE (check status de tools ejecutadas)
// ═══════════════════════════════════════════════════════════

/**
 * Verifica si alguna tool de escritura OK está en el trace.
 * Espejo de _wrote_ok() en runtime.py.
 * @param {Array<object>} toolTrace
 * @returns {boolean}
 */
function wroteOkFn(toolTrace) {
  const saveTools = new Set([
    'writeFile',
    'download_url_to_desktop',
    'generate_document',
    'generate_spreadsheet',
    'pptx_generate',
  ]);
  return (toolTrace || []).some(t =>
    t.ok && saveTools.has(String(t.tool || ''))
  );
}

/**
 * Verifica si web_search OK está en el trace.
 * Espejo de _searched_ok() en runtime.py.
 * @param {Array<object>} toolTrace
 * @returns {boolean}
 */
function searchedOkFn(toolTrace) {
  return (toolTrace || []).some(t => t.ok && String(t.tool || '') === 'web_search');
}

/**
 * Verifica si alguna tool de lectura OK está en el trace.
 * Espejo de _read_doc_ok() en runtime.py.
 * @param {Array<object>} toolTrace
 * @returns {boolean}
 */
function readDocOkFn(toolTrace) {
  const readTools = new Set([
    'read_document',
    'read_spreadsheet',
    'analyze_cv',
    'readFile',
    'parseDocument',
    'gmail_read_message',
  ]);
  return (toolTrace || []).some(t =>
    t.ok && readTools.has(String(t.tool || ''))
  );
}

/**
 * Verifica si alguna tool de envío WA OK está en el trace.
 * Espejo de _wa_sent_ok() en runtime.py.
 * @param {Array<object>} toolTrace
 * @returns {boolean}
 */
function waSentOkFn(toolTrace) {
  const waTools = new Set(['send_whatsapp_message', 'notify_whatsapp_owner', 'send_whatsapp_document']);
  return (toolTrace || []).some(t =>
    t.ok && waTools.has(String(t.tool || ''))
  );
}

/**
 * Verifica si alguna tool de generación de documentos OK está en el trace.
 * Espejo de _generated_doc_ok() en runtime.py.
 * @param {Array<object>} toolTrace
 * @returns {boolean}
 */
function generatedDocOkFn(toolTrace) {
  return (toolTrace || []).some(t =>
    t.ok && GENERATED_DOC_TOOLS.has(String(t.tool || ''))
  );
}

/**
 * Verifica si send_whatsapp_document OK está en el trace.
 * Espejo de _wa_doc_sent_ok() en runtime.py.
 * @param {Array<object>} toolTrace
 * @returns {boolean}
 */
function waDocSentOkFn(toolTrace) {
  return (toolTrace || []).some(t =>
    t.ok && String(t.tool || '') === 'send_whatsapp_document'
  );
}

/**
 * Verifica si alguna tool de listado/búsqueda Gmail OK está en el trace.
 * Espejo de _gmail_listed_or_searched_ok() en runtime.py.
 * @param {Array<object>} toolTrace
 * @returns {boolean}
 */
function gmailListedOrSearchedOkFn(toolTrace) {
  const gmailListTools = new Set(['gmail_list_unread', 'gmail_search', 'gmail_summarize_unread']);
  return (toolTrace || []).some(t =>
    t.ok && gmailListTools.has(String(t.tool || ''))
  );
}

/**
 * Verifica si gmail_read_message OK está en el trace.
 * Espejo de _gmail_read_ok() en runtime.py.
 * @param {Array<object>} toolTrace
 * @returns {boolean}
 */
function gmailReadOkFn(toolTrace) {
  return (toolTrace || []).some(t =>
    t.ok && String(t.tool || '') === 'gmail_read_message'
  );
}

/**
 * Verifica si gmail_auto_reply o gmail_send OK están en el trace.
 * Espejo de _gmail_replied_ok() en runtime.py.
 * @param {Array<object>} toolTrace
 * @returns {boolean}
 */
function gmailRepliedOkFn(toolTrace) {
  const replyTools = new Set(['gmail_auto_reply', 'gmail_send']);
  return (toolTrace || []).some(t =>
    t.ok && replyTools.has(String(t.tool || ''))
  );
}

/**
 * Verifica si gmail_archive OK está en el trace.
 * Espejo de _gmail_archived_ok() en runtime.py.
 * @param {Array<object>} toolTrace
 * @returns {boolean}
 */
function gmailArchivedOkFn(toolTrace) {
  return (toolTrace || []).some(t =>
    t.ok && String(t.tool || '') === 'gmail_archive'
  );
}

/**
 * Verifica si alguna tool gmail_* fue usada en el trace.
 * Espejo de _gmail_tool_used() en runtime.py.
 * @param {Array<object>} toolTrace
 * @returns {boolean}
 */
function gmailToolUsedFn(toolTrace) {
  return (toolTrace || []).some(t =>
    String(t.tool || '').startsWith('gmail_')
  );
}

/**
 * Verifica si calendar_create_event OK está en el trace.
 * Espejo de _calendar_event_created_ok() en runtime.py.
 * @param {Array<object>} toolTrace
 * @returns {boolean}
 */
function calendarEventCreatedOkFn(toolTrace) {
  return (toolTrace || []).some(t =>
    t.ok && String(t.tool || '') === 'calendar_create_event'
  );
}

/**
 * Verifica si notify_whatsapp_owner o schedule_reminder OK están en el trace.
 * Espejo de _calendar_notify_done() en runtime.py.
 * @param {Array<object>} toolTrace
 * @returns {boolean}
 */
function calendarNotifyDoneFn(toolTrace) {
  const notifyTools = new Set(['notify_whatsapp_owner', 'schedule_reminder']);
  return (toolTrace || []).some(t =>
    t.ok && notifyTools.has(String(t.tool || ''))
  );
}

// ═══════════════════════════════════════════════════════════
//  FUNCIONES DE INTENCIÓN (wants_*)
// ═══════════════════════════════════════════════════════════

/**
 * Detecta si el usuario pide descargar una URL.
 * Espejo de _wants_url_download() en runtime.py.
 * @param {string} text
 * @returns {boolean}
 */
function wantsUrlDownload(text) {
  const t = latestUserUtterance(text);
  if (!extractDownloadUrl(t)) return false;
  if (_DOWNLOAD_VERB_RE.test(t)) return true;
  const lower = t.toLowerCase();
  return ['.pdf', '.zip', '.png', '.jpg', '.jpeg', '.docx'].some(ext => lower.includes(ext));
}

/**
 * Detecta si el usuario pide guardar en Escritorio.
 * Espejo de _wants_desktop_save() en runtime.py.
 * @param {string} text
 * @returns {boolean}
 */
function wantsDesktopSave(text) {
  const t = latestUserUtterance(text);
  if (!_SAVE_INTENT_RE.test(t)) return false;
  return _DESKTOP_RE.test(t) || _FILENAME_BARE_RE.test(t);
}

/**
 * Detecta si el usuario pide leer un PDF del Escritorio.
 * Espejo de _wants_desktop_pdf_read() en runtime.py.
 * @param {string} text
 * @returns {boolean}
 */
function wantsDesktopPdfRead(text) {
  const t = latestUserUtterance(text);
  if (!_DESKTOP_RE.test(t)) return false;
  return _PDF_RE.test(t) || _READ_DOC_INTENT_RE.test(t);
}

/**
 * Detecta si el usuario pide responder un correo.
 * Espejo de _wants_gmail_reply() en runtime.py.
 * @param {string} text
 * @returns {boolean}
 */
function wantsGmailReply(text) {
  return _GMAIL_REPLY_INTENT_RE.test(latestUserUtterance(text));
}

/**
 * Detecta si el usuario pide archivar correos en lote.
 * Espejo de _wants_gmail_bulk_archive() en runtime.py.
 * @param {string} text
 * @returns {boolean}
 */
function wantsGmailBulkArchive(text) {
  return _GMAIL_ARCHIVE_INTENT_RE.test(latestUserUtterance(text));
}

/**
 * Detecta si el usuario pide ver su bandeja de entrada.
 * Espejo de _wants_gmail_inbox() en runtime.py.
 * @param {string} text
 * @returns {boolean}
 */
function wantsGmailInbox(text) {
  return _GMAIL_INBOX_INTENT_RE.test(latestUserUtterance(text));
}

/**
 * Detecta si el usuario pide generar documento y enviarlo por WA.
 * Espejo de _wants_generate_and_wa_doc() en runtime.py.
 * @param {string} text
 * @returns {boolean}
 */
function wantsGenerateAndWaDoc(text) {
  const t = latestUserUtterance(text);
  return Boolean(
    _GENERATE_DOC_INTENT_RE.test(t) &&
    _REPORT_DOC_INTENT_RE.test(t) &&
    _WA_NOTIFY_INTENT_RE.test(t)
  );
}

/**
 * Detecta si el usuario pide leer un documento y enviarlo por WhatsApp.
 * Espejo de _wants_read_and_wa() en runtime.py.
 * @param {string} text
 * @returns {boolean}
 */
function wantsReadAndWa(text) {
  const t = latestUserUtterance(text);
  return Boolean(_READ_DOC_INTENT_RE.test(t) && _WA_NOTIFY_INTENT_RE.test(t));
}

/**
 * Detecta si el usuario pide agendar un evento + notificación.
 * Espejo de _wants_smart_calendar() en runtime.py.
 * @param {string} text
 * @returns {boolean}
 */
function wantsSmartCalendar(text) {
  const t = latestUserUtterance(text);
  const hasCreate = _CALENDAR_CREATE_INTENT_RE.test(t);
  const hasNotify = _WA_NOTIFY_INTENT_RE.test(t) || _CALENDAR_REMIND_INTENT_RE.test(t);
  return hasCreate && hasNotify;
}

// ═══════════════════════════════════════════════════════════
//  HELPERS DE EXTRACCIÓN
// ═══════════════════════════════════════════════════════════

/**
 * Extrae preview de lectura del tool trace.
 * Espejo de _extract_read_preview() en runtime.py.
 * @param {Array<object>} toolTrace
 * @returns {string}
 */
function extractReadPreview(toolTrace) {
  const readTools = new Set([
    'read_document',
    'read_spreadsheet',
    'analyze_cv',
    'readFile',
    'parseDocument',
    'gmail_read_message',
  ]);
  for (let i = (toolTrace || []).length - 1; i >= 0; i--) {
    const t = toolTrace[i];
    if (!t.ok) continue;
    if (!readTools.has(String(t.tool || ''))) continue;
    const preview = String(t.preview || t.output || '').trim();
    if (preview) return preview.slice(0, 4000);
  }
  return '';
}

/**
 * Construye resumen para enviar por WhatsApp.
 * Espejo de _summary_for_wa() en runtime.py.
 * @param {string} finalText
 * @param {Array<object>} toolTrace
 * @returns {string}
 */
function summaryForWa(finalText, toolTrace) {
  const spoken = stripToolCallsJson(finalText || '') || (finalText || '');
  const trimmed = spoken.trim();
  if (trimmed.length >= 40) return trimmed.slice(0, 1500);
  const preview = extractReadPreview(toolTrace);
  if (preview) return preview.slice(0, 1500);
  return trimmed || 'Resumen del documento solicitado.';
}

/**
 * Extrae la información del evento de calendario desde el tool trace.
 * Espejo de _extract_calendar_event_from_trace() en runtime.py.
 * @param {Array<object>} toolTrace
 * @returns {{summary: string, whenHuman: string, startIso: string, preview: string}|null}
 */
function extractCalendarEventFromTrace(toolTrace) {
  for (let i = (toolTrace || []).length - 1; i >= 0; i--) {
    const t = toolTrace[i];
    if (!t.ok || String(t.tool || '') !== 'calendar_create_event') continue;
    const preview = String(t.preview || t.output || '').trim();
    const m1 = preview.match(/Evento creado:\s*[«"']?(.+?)[»"']?\s+el\s+(.+?)\s+\(ISO:/i);
    if (m1) {
      return {
        summary: m1[1].trim(),
        whenHuman: m1[2].trim(),
        startIso: '',
        preview,
      };
    }
    const m2 = preview.match(/Evento creado:\s*(.+?)\s*\(([^)]+)\)/i);
    if (m2) {
      return {
        summary: m2[1].trim().replace(/[«»"']/g, ''),
        whenHuman: m2[2].trim(),
        startIso: m2[2].trim(),
        preview,
      };
    }
    return { summary: 'Evento', whenHuman: '', startIso: '', preview };
  }
  return null;
}

/**
 * Genera el mensaje de confirmación de calendario.
 * Espejo de _calendar_confirmation_message() en runtime.py.
 * @param {{summary: string, whenHuman: string, startIso: string}} event
 * @param {object} [opts]
 * @param {boolean} [opts.forReminder=false]
 * @returns {string}
 */
function calendarConfirmationMessage(event, opts = {}) {
  const title = event.summary || 'Evento';
  const when = event.whenHuman || event.startIso || 'la hora acordada';
  if (opts.forReminder) {
    return `Recordatorio: ${title} — ${when}`;
  }
  return `✅ Reunión agendada: «${title}» el ${when}.`;
}

// ═══════════════════════════════════════════════════════════
//  FUNCIONES PRINCIPALES — Detectores (portadas de runtime.py)
// ═══════════════════════════════════════════════════════════

/**
 * Detecta si el modelo está inventando datos sin haber ejecutado herramientas.
 * Espejo de _detect_fabricated_data() en runtime.py.
 * @param {string} content
 * @param {Array<object>} toolTrace
 * @returns {boolean}
 */
function detectFabricatedData(content, toolTrace) {
  if (!content) return false;
  if (toolTrace && toolTrace.length > 0) return false;
  for (const pattern of FABRICATION_PATTERNS) {
    if (pattern.test(content)) return true;
  }
  return false;
}

/**
 * Detecta si el modelo cortó a medias y se le puede empujar a seguir.
 * Espejo de _looks_incomplete_final() en runtime.py.
 * @param {string} text
 * @param {object} [opts]
 * @param {boolean} [opts.hadTools=false]
 * @param {number} [opts.step=0]
 * @param {number} [opts.stepsCap=100]
 * @returns {boolean}
 */
function looksIncompleteFinal(text, opts = {}) {
  const { hadTools = false, step = 0, stepsCap = 100 } = opts;
  if (step >= stepsCap) return false;
  const t = (text || '').trim();
  if (!t) return Boolean(hadTools);
  if (INCOMPLETE_FINAL_RE.test(t)) return true;
  // Tras tools: stub corto no es entregable (salvo confirmaciones/negativas claras)
  if (hadTools && t.length < 120) {
    const lower = t.toLowerCase();
    const completeMarkers = [
      'listo', 'guardé', 'guarde', 'enviado', 'descargué', 'descargue',
      '✅', 'creado', 'documento', 'no puedo', 'no puedo usar',
      'no disponible', 'no tengo', 'error', 'falló', 'fallo',
    ];
    if (completeMarkers.some(m => lower.includes(m))) return false;
    return true;
  }
  return false;
}

// ═══════════════════════════════════════════════════════════
//  FUNCIONES PRINCIPALES — Grounding (portadas de grounding.py)
// ═══════════════════════════════════════════════════════════

/**
 * True si la misión es de análisis (revisar carpetas, código, proyecto).
 * Espejo de is_analysis_mission() en grounding.py.
 * @param {string} userText
 * @returns {boolean}
 */
function isAnalysisMission(userText) {
  return _ANALYSIS_INTENT.test(userText || '');
}

/**
 * Extrae rutas citadas en el texto de la respuesta.
 * Espejo de extract_claimed_paths() en grounding.py.
 * @param {string} text
 * @returns {string[]}
 */
function extractClaimedPaths(text) {
  const found = [];
  const seen = new Set();
  const matches = (text || '').matchAll(_CLAIMED_PATH_RE);
  for (const m of matches) {
    const raw = m.slice(1).find(g => g) || '';
    const path = raw.trim().replace(/^["']|["']$/g, '');
    if (!path) continue;
    const key = path.replace(/\\/g, '/').toLowerCase();
    if (seen.has(key)) continue;
    seen.add(key);
    found.push(path);
  }
  return found;
}

/**
 * Arma un blob de evidencia desde el tool trace.
 * Espejo de evidence_blob_from_trace() en grounding.py.
 * @param {Array<object>|null} toolTrace
 * @returns {string}
 */
function evidenceBlobFromTrace(toolTrace) {
  const parts = [];
  for (const t of (toolTrace || [])) {
    if (!t.ok) continue;
    const preview = String(t.preview || t.output || '');
    const tool = String(t.tool || '');
    if (preview) {
      parts.push(`${tool}\n${preview}`);
    }
  }
  return parts.join('\n');
}

/**
 * Verifica si una ruta está respaldada por evidencia.
 * Espejo de path_supported_by_evidence() en grounding.py.
 * @param {string} path
 * @param {string} evidence
 * @returns {boolean}
 */
function pathSupportedByEvidence(path, evidence) {
  if (!path || !evidence) return false;
  const ev = evidence.replace(/\\/g, '/').toLowerCase();
  const norm = path.replace(/\\/g, '/').toLowerCase();
  if (ev.includes(norm)) return true;
  const base = path.replace(/\\/g, '/').split('/').pop().toLowerCase();
  if (base.length >= 4 && ev.includes(base)) return true;
  const parts = norm.replace(/^\.\/?/, '').split('/').filter(Boolean);
  if (parts.length >= 2) {
    const tail = parts.slice(-2).join('/');
    if (ev.includes(tail)) return true;
  }
  return false;
}

/**
 * Filtra rutas no respaldadas por evidencia.
 * Espejo de ungrounded_paths() en grounding.py.
 * @param {string[]} claimed
 * @param {string} evidence
 * @returns {string[]}
 */
function ungroundedPaths(claimed, evidence) {
  return claimed.filter(p => !pathSupportedByEvidence(p, evidence));
}

/**
 * Verifica si alguna tool de escritura OK está en el trace (versión grounding.py).
 * Espejo de wrote_ok() en grounding.py.
 * @param {Array<object>|null} toolTrace
 * @returns {boolean}
 */
function wroteOkGrounding(toolTrace) {
  const saveTools = new Set([
    'writeFile', 'generate_document', 'generate_spreadsheet',
    'pptx_generate', 'download_url_to_desktop', 'downloadUrl',
    'browser_screenshot', 'browser_pdf',
  ]);
  return (toolTrace || []).some(t =>
    t.ok && saveTools.has(String(t.tool || ''))
  );
}

/**
 * Verifica si alguna tool de lectura OK está en el trace (versión grounding.py).
 * Espejo de read_ok() en grounding.py.
 * @param {Array<object>|null} toolTrace
 * @returns {boolean}
 */
function readOkGrounding(toolTrace) {
  const readTools = new Set([
    'listFiles', 'readFile', 'file_search', 'searchFiles',
    'read_document', 'read_spreadsheet', 'analyze_cv',
  ]);
  return (toolTrace || []).some(t =>
    t.ok && readTools.has(String(t.tool || ''))
  );
}

/**
 * Extrae la ruta guardada del tool trace (para reemplazar rutas inventadas).
 * Espejo de extract_saved_path_from_trace() en grounding.py.
 * @param {Array<object>|null} toolTrace
 * @returns {string|null}
 */
function extractSavedPathFromTrace(toolTrace) {
  const saveTools = new Set([
    'writeFile', 'generate_document', 'generate_spreadsheet',
    'pptx_generate', 'download_url_to_desktop', 'downloadUrl',
    'browser_screenshot', 'browser_pdf',
  ]);
  for (let i = (toolTrace || []).length - 1; i >= 0; i--) {
    const t = toolTrace[i];
    if (!t.ok) continue;
    if (!saveTools.has(String(t.tool || ''))) continue;
    const preview = String(t.preview || t.output || '');
    // Preferir línea "Ruta:" (absoluta) sobre "Documento creado: nombre.docx"
    for (const line of preview.split('\n')) {
      const mRoute = line.trim().match(/^Ruta:\s*(.+)$/i);
      if (mRoute) return mRoute[1].trim();
    }
    const mSave = preview.match(/^Archivo guardado en:\s*(.+)$/im);
    if (mSave) return mSave[1].trim();
    for (const line of preview.split('\n')) {
      if (/\.(docx|txt|md|xlsx|pptx|pdf|png|jpe?g)\b/i.test(line) &&
          (line.includes(':\\') || line.includes('/'))) {
        if (/creado:/i.test(line) && !line.includes(':\\') && !line.trim().startsWith('/')) continue;
        if (line.toLowerCase().startsWith('ruta')) return line.split(':').slice(1).join(':').trim();
        return line.trim();
      }
    }
  }
  return null;
}

/**
 * Detecta alucinaciones generales en respuestas finales.
 * Espejo de _detect_general_fabrication() en grounding.py.
 * @param {string} finalText
 * @param {Array<object>|null} toolTrace
 * @returns {boolean}
 */
function detectGeneralFabrication(finalText, toolTrace) {
  if (!finalText) return false;
  if (toolTrace && toolTrace.length > 0) return false;
  for (const { pattern } of _UNGROUNDED_EXTRAS) {
    if (pattern.test(finalText)) return true;
  }
  return false;
}

/**
 * True si el informe cita demasiado material no visto en tools.
 * Espejo de looks_ungrounded_final() en grounding.py.
 * @param {object} opts
 * @param {string} opts.userText
 * @param {string} opts.finalText
 * @param {Array<object>|null} opts.toolTrace
 * @returns {boolean}
 */
function looksUngroundedFinal({ userText, finalText, toolTrace }) {
  if (!isAnalysisMission(userText)) {
    if (detectGeneralFabrication(finalText, toolTrace)) return true;
    return false;
  }
  const evidence = evidenceBlobFromTrace(toolTrace);
  const claimed = extractClaimedPaths(finalText);
  const bad = ungroundedPaths(claimed, evidence);

  // Inventó muchas rutas concretas sin evidencia
  if (bad.length >= 3) return true;
  if (claimed.length >= 4 && bad.length >= Math.max(2, Math.floor(claimed.length / 2))) return true;

  // Afirma docx/guardado sin tool de escritura OK
  if (_DOCX_CLAIM_RE.test(finalText || '')) {
    const lowerFText = (finalText || '').toLowerCase();
    if (lowerFText.includes('.docx') || lowerFText.includes('guardado')) {
      if (!wroteOkGrounding(toolTrace)) return true;
    }
  }

  // Análisis profundo sin haber listado/leído nada
  if ((finalText || '').length > 800 && !readOkGrounding(toolTrace)) return true;

  return false;
}

/**
 * Genera mensaje de nudge para grounding.
 * Espejo de grounding_nudge_message() en grounding.py.
 * @param {object} opts
 * @param {string} opts.userText
 * @param {string} opts.finalText
 * @param {Array<object>|null} opts.toolTrace
 * @returns {string}
 */
function groundingNudgeMessage({ userText, finalText, toolTrace }) {
  const evidence = evidenceBlobFromTrace(toolTrace);
  const claimed = extractClaimedPaths(finalText);
  const bad = ungroundedPaths(claimed, evidence).slice(0, 8);
  const lines = [
    'Tu borrador NO está anclado a evidencia de tools.',
    'REGLAS OBLIGATORIAS:',
    '1. Solo cita rutas/archivos que aparecieron en [tool_result] (listFiles/readFile/file_search).',
    '2. Si no leíste un archivo, NO inventes su contenido ni hallazgos sobre él.',
    '3. Si falta evidencia, usa más listFiles/readFile en subcarpetas reales (apps/, docs/, packages/).',
    '4. Si generas DOCX, usa generate_document o writeFile y copia la Ruta exacta que devolvió la tool.',
    '5. Reescribe el informe completo solo con hechos verificados.',
  ];
  if (bad.length > 0) {
    lines.push('Rutas citadas sin evidencia (eliminar o verificar leyéndolas):');
    bad.forEach(p => lines.push(`  - ${p}`));
  }
  if (!readOkGrounding(toolTrace)) {
    lines.push('Aún no hay listFiles/readFile OK: empieza listando la carpeta pedida.');
  }
  const lowerFT = (finalText || '').toLowerCase();
  if (_DOCX_CLAIM_RE.test(finalText || '') && (lowerFT.includes('.docx') || lowerFT.includes('guardado')) && !wroteOkGrounding(toolTrace)) {
    lines.push('Afirmaste un documento guardado pero no hay generate_document/writeFile OK.');
  }
  return lines.join('\n');
}

/**
 * Corrige rutas inventadas en la respuesta final usando el tool trace real.
 * Espejo de repair_saved_path_claim() en grounding.py.
 * @param {string} finalText
 * @param {Array<object>|null} toolTrace
 * @returns {string}
 */
function repairSavedPathClaim(finalText, toolTrace) {
  const text = finalText || '';
  const real = extractSavedPathFromTrace(toolTrace);
  if (!real || !wroteOkGrounding(toolTrace)) return text;
  const fakeDocx = [];
  const docxRe = /[A-Za-z]:\\[^\s|*]+\.docx|\/[^\s|*]+\.docx|`[^`]+\.docx`/gi;
  let dm;
  while ((dm = docxRe.exec(text)) !== null) {
    fakeDocx.push(dm[0]);
  }
  let out = text;
  for (const fake of fakeDocx) {
    const clean = fake.replace(/`/g, '');
    if (clean.replace(/\\/g, '/').toLowerCase() !== real.replace(/\\/g, '/').toLowerCase()) {
      out = out.replace(fake, fake.startsWith('`') ? `\`${real}\`` : real);
    }
  }
  const lowerOut = out.toLowerCase();
  const lowerReal = real.toLowerCase();
  if (!lowerOut.includes(lowerReal) &&
      (lowerOut.includes('.docx') || lowerOut.includes('documento'))) {
    out = `${out.trimEnd()}\n\n— Documento real generado por DOT: \`${real}\``;
  }
  return out;
}

// ═══════════════════════════════════════════════════════════
//  FUNCIONES PRINCIPALES — Forzado de acciones
// ═══════════════════════════════════════════════════════════

/**
 * OpenClaw-style: intención clara de descarga → ejecutar sin esperar al modelo.
 * Espejo de _maybe_force_download() en runtime.py.
 *
 * @param {object} opts
 * @param {string} opts.uid - ID de usuario
 * @param {string} opts.text - Mensaje del usuario (con historial)
 * @param {function} opts.executeTool - Async function (toolName, args) => {ok, output, error}
 * @param {string[]} opts.toolNames - Lista de nombres de herramientas disponibles
 * @returns {Promise<{trace: Array<object>, follow: string}|null>}
 */
async function maybeForceDownload({ uid, text, executeTool, toolNames }) {
  if (!toolNames.includes('download_url_to_desktop')) return null;
  if (!wantsUrlDownload(text)) return null;
  const url = extractDownloadUrl(text);
  if (!url) return null;

  const dest = desktopPathForUrl(url);
  const toolStartMs = Date.now();
  const result = await executeTool('download_url_to_desktop', { url, path: dest });
  const ms = Date.now() - toolStartMs;
  const trace = [{
    tool: 'download_url_to_desktop',
    ok: result.ok,
    ms,
    step: 0,
    channel: 'forced',
  }];
  const obs = formatObservation('download_url_to_desktop', result.ok, result.output, result.error);
  const follow =
    `Resultado de descarga automática:\n${obs}\n\n` +
    'Confirma al usuario en español claro (ruta/bytes si ok). ' +
    'NUNCA digas que no puedes descargar PDFs o binarios.';

  return { trace, follow };
}

/**
 * Si el usuario pidió guardar en Escritorio y no hubo writeFile OK, forzarlo.
 * Espejo de _ensure_desktop_save() en runtime.py.
 *
 * @param {object} opts
 * @param {string} [opts.uid]
 * @param {string} opts.userText
 * @param {string} opts.finalText
 * @param {function} opts.executeTool
 * @param {string[]} opts.toolNames
 * @param {Array<object>} opts.toolTrace
 * @param {string} opts.channel
 * @returns {Promise<{finalText: string, toolTrace: Array<object>}>}
 */
async function ensureDesktopSave({ uid, userText, finalText, executeTool, toolNames, toolTrace, channel }) {
  if (!toolNames.includes('writeFile')) {
    return { finalText, toolTrace };
  }
  if (!wantsDesktopSave(userText)) {
    return { finalText, toolTrace };
  }
  if (wroteOkFn(toolTrace)) {
    return { finalText, toolTrace };
  }
  if (wantsUrlDownload(userText)) {
    return { finalText, toolTrace };
  }

  const intent = latestUserUtterance(userText);
  const filename = extractDesktopFilename(intent);
  const path = `~/Desktop/${filename}`;
  let content = extractInlineContent(intent);
  if (!content) {
    content = cleanSummaryForFile(finalText);
  }

  // Buscar+guardar: si el modelo ya buscó pero solo dijo "listo",
  // re-ejecutar web_search para armar el archivo
  let searchOutput = '';
  const wantsSearch = _SEARCH_INTENT_RE.test(intent);
  const contentWeak = (
    !content ||
    content.trim().length < 40 ||
    /no (pude|hay|encontr)|ya lo guard|listo[,.]?\s*$|voy a /i.test(content || '')
  );
  if (wantsSearch && contentWeak && toolNames.includes('web_search')) {
    const q = intent.replace(
      /\b(guarda|guardar|crea|crear|escribe|en mi escritorio|como\s+\S+\.txt).*$/i,
      ''
    ).trim() || intent;
    const toolStartMs = Date.now();
    const sres = await executeTool('web_search', { query: q.slice(0, 200) });
    const ms = Date.now() - toolStartMs;
    toolTrace.push({
      tool: 'web_search',
      ok: sres.ok,
      ms,
      step: 0,
      channel: `${channel}:forced`,
    });
    if (sres.ok) {
      searchOutput = sres.output || '';
    }
  }

  if (searchOutput && (
    !content ||
    content.length < 40 ||
    /no (pude|hay|encontr)|ya lo guard|listo/i.test(content)
  )) {
    content = searchOutput;
  }
  if (!content || content.trim().length < 1) {
    return {
      finalText: 'No pude armar el contenido para guardar. Prueba: «crea nota.txt en Escritorio con hola».',
      toolTrace,
    };
  }

  const toolStartMs = Date.now();
  const result = await executeTool('writeFile', { path, content, confirm: true });
  const ms = Date.now() - toolStartMs;
  toolTrace.push({
    tool: 'writeFile',
    ok: result.ok,
    ms,
    step: 0,
    channel: `${channel}:forced`,
  });

  if (result.ok) {
    const absPath = (result.output || '').replace(/^Archivo guardado en: /, '').trim() || path;
    const preview = content.length <= 600 ? content : content.slice(0, 600) + '…';
    return {
      finalText: `${preview}\n\n✅ Archivo guardado en tu Escritorio (${filename}).\nRuta: ${absPath}`,
      toolTrace,
    };
  }

  const err = result.error || 'error';
  if (err.includes('bridge_unreachable') || err.includes('bridge_secret')) {
    return {
      finalText: 'Intenté guardar el archivo pero el puente local no respondió. Dejá la app DOT abierta en el PC e intentá de nuevo.',
      toolTrace,
    };
  }
  return {
    finalText: `Intenté guardar ${filename} en tu Escritorio pero falló (${err}).`,
    toolTrace,
  };
}

/**
 * Si el usuario pidió leer PDF del Escritorio sin ruta, buscar antes.
 * Espejo de _maybe_force_desktop_pdf_read() en runtime.py.
 *
 * @param {object} opts
 * @param {string} [opts.uid]
 * @param {string} opts.text
 * @param {function} opts.executeTool
 * @param {string[]} opts.toolNames
 * @returns {Promise<{trace: Array<object>, follow: string}|null>}
 */
async function maybeForceDesktopPdfRead({ uid, text, executeTool, toolNames }) {
  if (!toolNames.includes('file_search')) return null;
  if (!wantsDesktopPdfRead(text)) return null;

  const toolStartMs = Date.now();
  const result = await executeTool('file_search', { query: 'pdf', searchRoot: 'desktop' });
  const ms = Date.now() - toolStartMs;
  const trace = [{
    tool: 'file_search',
    ok: result.ok,
    ms,
    step: 0,
    channel: 'forced',
    preview: (result.output || result.error || '').slice(0, 2500),
  }];
  const obs = formatObservation('file_search', result.ok, result.output, result.error);
  const follow =
    `Búsqueda automática de PDF en Escritorio:\n${obs}\n\n` +
    'Continúa la misión: lee el PDF encontrado con read_document, ' +
    'resume en el formato pedido y envía con notify_whatsapp_owner si lo pidió. ' +
    'No inventes rutas ni contenido.';

  return { trace, follow };
}

/**
 * Si leyó documento y pidió WA pero no notificó, forzar notify_whatsapp_owner.
 * Espejo de _ensure_whatsapp_notify() en runtime.py.
 *
 * @param {object} opts
 * @param {string} [opts.uid]
 * @param {string} opts.userText
 * @param {string} opts.finalText
 * @param {function} opts.executeTool
 * @param {string[]} opts.toolNames
 * @param {Array<object>} opts.toolTrace
 * @param {string} opts.channel
 * @returns {Promise<{finalText: string, toolTrace: Array<object>}>}
 */
async function ensureWhatsappNotify({ uid, userText, finalText, executeTool, toolNames, toolTrace, channel }) {
  if (!toolNames.includes('notify_whatsapp_owner')) {
    return { finalText, toolTrace };
  }
  if (wantsGenerateAndWaDoc(userText)) {
    return { finalText, toolTrace };
  }
  if (!_WA_NOTIFY_INTENT_RE.test(latestUserUtterance(userText))) {
    return { finalText, toolTrace };
  }
  if (waSentOkFn(toolTrace)) {
    return { finalText, toolTrace };
  }
  if (!readDocOkFn(toolTrace)) {
    return { finalText, toolTrace };
  }

  const message = summaryForWa(finalText, toolTrace);
  if (message.trim().length < 10) {
    return { finalText, toolTrace };
  }

  const toolStartMs = Date.now();
  const result = await executeTool('notify_whatsapp_owner', { message, confirm: true });
  const ms = Date.now() - toolStartMs;
  toolTrace.push({
    tool: 'notify_whatsapp_owner',
    ok: result.ok,
    ms,
    step: 0,
    channel: `${channel}:forced`,
    preview: (result.output || result.error || '').slice(0, 500),
  });

  if (result.ok) {
    const spoken = stripToolCallsJson(finalText || '') || (finalText || '');
    return {
      finalText: `${spoken.trimEnd()}\n\n✅ Te envié el resumen por WhatsApp al número vinculado.`.trim(),
      toolTrace,
    };
  }

  const err = result.error || 'error desconocido';
  if (err.toLowerCase().includes('no vinculado') || err.toLowerCase().includes('not linked')) {
    return {
      finalText: 'Leí el documento y preparé el resumen, pero WhatsApp no está vinculado. Vinculá tu número en Configuración → WhatsApp e intentá de nuevo.',
      toolTrace,
    };
  }
  return {
    finalText: `Leí el documento pero no pude enviarte el WhatsApp: ${err}`,
    toolTrace,
  };
}

/**
 * Si creó evento y pidió aviso pero no notificó, forzar WA o recordatorio.
 * Espejo de _ensure_calendar_notify() en runtime.py.
 *
 * @param {object} opts
 * @param {string} [opts.uid]
 * @param {string} opts.userText
 * @param {string} opts.finalText
 * @param {function} opts.executeTool
 * @param {string[]} opts.toolNames
 * @param {Array<object>} opts.toolTrace
 * @param {string} opts.channel
 * @returns {Promise<{finalText: string, toolTrace: Array<object>}>}
 */
async function ensureCalendarNotify({ uid, userText, finalText, executeTool, toolNames, toolTrace, channel }) {
  if (!wantsSmartCalendar(userText)) {
    return { finalText, toolTrace };
  }
  if (!calendarEventCreatedOkFn(toolTrace)) {
    return { finalText, toolTrace };
  }
  if (calendarNotifyDoneFn(toolTrace)) {
    return { finalText, toolTrace };
  }

  const event = extractCalendarEventFromTrace(toolTrace);
  if (!event) {
    return { finalText, toolTrace };
  }

  const utterance = latestUserUtterance(userText);
  const wantsWa = _WA_NOTIFY_INTENT_RE.test(utterance);
  const explicitReminder = /\b(recu[eé]rdame|recordatorio)\b/i.test(utterance);
  const spoken = stripToolCallsJson(finalText || '') || (finalText || '');
  const extras = [];

  if (wantsWa && toolNames.includes('notify_whatsapp_owner')) {
    const message = calendarConfirmationMessage(event);
    const toolStartMs = Date.now();
    const result = await executeTool('notify_whatsapp_owner', { message, confirm: true });
    const ms = Date.now() - toolStartMs;
    toolTrace.push({
      tool: 'notify_whatsapp_owner',
      ok: result.ok,
      ms,
      step: 0,
      channel: `${channel}:calendar_forced`,
      preview: (result.output || result.error || '').slice(0, 500),
    });
    if (result.ok) {
      extras.push('✅ Te envié la confirmación por WhatsApp al número vinculado.');
    } else {
      extras.push(`No pude enviarte el WhatsApp: ${result.error || 'error desconocido'}`);
    }
  }

  if (explicitReminder && toolNames.includes('schedule_reminder')) {
    const when = event.startIso || event.whenHuman || utterance;
    const remindMsg = calendarConfirmationMessage(event, { forReminder: true });
    const channelRem = wantsWa ? 'whatsapp' : 'notify';
    const toolStartMs = Date.now();
    const result = await executeTool('schedule_reminder', {
      message: remindMsg,
      when,
      channel: channelRem,
    });
    const ms = Date.now() - toolStartMs;
    toolTrace.push({
      tool: 'schedule_reminder',
      ok: result.ok,
      ms,
      step: 0,
      channel: `${channel}:calendar_forced`,
      preview: (result.output || result.error || '').slice(0, 500),
    });
    if (result.ok) {
      extras.push(result.output || 'Recordatorio programado.');
    } else if (!wantsWa) {
      extras.push(`No pude programar el recordatorio: ${result.error || 'error'}`);
    }
  }

  if (!extras.length && !wantsWa && !explicitReminder) {
    return { finalText, toolTrace };
  }
  if (!extras.length && wantsWa && !toolNames.includes('notify_whatsapp_owner')) {
    return { finalText, toolTrace };
  }

  let msg = spoken.trimEnd();
  if (extras.length > 0) {
    msg = msg ? `${msg}\n\n${extras.join('\n')}` : extras.join('\n');
  }
  return { finalText: msg.trim(), toolTrace };
}

/**
 * Si generó documento y pidió WA como archivo, forzar send_whatsapp_document.
 * Espejo de _ensure_whatsapp_document_send() en runtime.py.
 *
 * @param {object} opts
 * @param {string} [opts.uid]
 * @param {string} opts.userText
 * @param {string} opts.finalText
 * @param {function} opts.executeTool
 * @param {string[]} opts.toolNames
 * @param {Array<object>} opts.toolTrace
 * @param {string} opts.channel
 * @returns {Promise<{finalText: string, toolTrace: Array<object>}>}
 */
async function ensureWhatsappDocumentSend({ uid, userText, finalText, executeTool, toolNames, toolTrace, channel }) {
  if (!toolNames.includes('send_whatsapp_document')) {
    return { finalText, toolTrace };
  }
  if (!wantsGenerateAndWaDoc(userText)) {
    return { finalText, toolTrace };
  }
  if (waDocSentOkFn(toolTrace)) {
    return { finalText, toolTrace };
  }
  if (!generatedDocOkFn(toolTrace)) {
    return { finalText, toolTrace };
  }

  const rawPath = extractSavedPathFromTrace(toolTrace);
  if (!rawPath) {
    return { finalText, toolTrace };
  }

  // En Electron: el path es directamente usable (no hay resolve_document_path_for_send)
  const absPath = rawPath;

  const toolStartMs = Date.now();
  const result = await executeTool('send_whatsapp_document', { path: absPath, confirm: true });
  const ms = Date.now() - toolStartMs;
  toolTrace.push({
    tool: 'send_whatsapp_document',
    ok: result.ok,
    ms,
    step: 0,
    channel: `${channel}:forced`,
    preview: (result.output || result.error || '').slice(0, 500),
  });

  if (result.ok) {
    const spoken = stripToolCallsJson(finalText || '') || (finalText || '');
    return {
      finalText: `${spoken.trimEnd()}\n\n${result.output || '✅ Te envié el documento por WhatsApp.'}`.trim(),
      toolTrace,
    };
  }

  const err = result.error || 'error desconocido';
  if (err.toLowerCase().includes('no vinculado') || err.toLowerCase().includes('not linked')) {
    return {
      finalText: `Generé el informe en tu Escritorio, pero WhatsApp no está vinculado.\nRuta: ${absPath}\nVinculá tu número en Configuración → WhatsApp e intentá de nuevo.`,
      toolTrace,
    };
  }
  return {
    finalText: `Generé el documento en ${absPath}, pero no pude enviarlo por WhatsApp: ${err}`,
    toolTrace,
  };
}

// ═══════════════════════════════════════════════════════════
//  EXPORTACIONES
// ═══════════════════════════════════════════════════════════

module.exports = {
  // Constantes
  FABRICATION_PATTERNS,
  INCOMPLETE_FINAL_RE,
  GENERATED_DOC_TOOLS,
  CONTINUE_AFTER_TOOLS,
  NUDGE_INCOMPLETE,

  // Helpers de texto
  stripToolCallsJson,
  formatObservation,
  latestUserUtterance,
  extractDownloadUrl,
  desktopPathForUrl,
  extractDesktopFilename,
  extractInlineContent,
  cleanSummaryForFile,

  // Helpers de tool trace (check status)
  wroteOkFn,
  searchedOkFn,
  readDocOkFn,
  waSentOkFn,
  generatedDocOkFn,
  waDocSentOkFn,
  gmailListedOrSearchedOkFn,
  gmailReadOkFn,
  gmailRepliedOkFn,
  gmailArchivedOkFn,
  gmailToolUsedFn,
  calendarEventCreatedOkFn,
  calendarNotifyDoneFn,

  // Helpers de extracción
  extractReadPreview,
  summaryForWa,
  extractCalendarEventFromTrace,
  calendarConfirmationMessage,

  // Detección de intención
  wantsUrlDownload,
  wantsDesktopSave,
  wantsDesktopPdfRead,
  wantsGmailReply,
  wantsGmailBulkArchive,
  wantsGmailInbox,
  wantsGenerateAndWaDoc,
  wantsReadAndWa,
  wantsSmartCalendar,

  // Detectores principales
  detectFabricatedData,
  looksIncompleteFinal,

  // Grounding (portado de grounding.py)
  isAnalysisMission,
  extractClaimedPaths,
  evidenceBlobFromTrace,
  pathSupportedByEvidence,
  ungroundedPaths,
  wroteOkGrounding,
  readOkGrounding,
  extractSavedPathFromTrace,
  detectGeneralFabrication,
  looksUngroundedFinal,
  groundingNudgeMessage,
  repairSavedPathClaim,

  // Forzado de acciones
  maybeForceDownload,
  maybeForceDesktopPdfRead,
  ensureDesktopSave,
  ensureWhatsappNotify,
  ensureCalendarNotify,
  ensureWhatsappDocumentSend,
};
