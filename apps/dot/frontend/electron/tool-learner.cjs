// tool-learner.cjs — Aprendizaje de errores de herramientas para DOT
// M5S3-A: Si una tool falla 3 veces en el mismo contexto, DOT aprende a
// no usarla y sugiere una alternativa.
//
// Diseñado según PLAN-DOT-2026-2027 M5S3-A.
// Persiste el historial en kv_store con namespace 'tool_learner'.
//
// Integración con AgentLoop:
//   const learner = new ToolLearner();
//   learner.init(localDb);
//   // En _executeTool, después de cada llamada:
//   learner.recordToolCall(toolName, context, result.ok, result.error, execMs);
//   // Antes de ejecutar, verificar bloqueos:
//   const blocked = learner.getBlockedTools(context);
//   if (blocked.includes(toolName)) {
//     const alt = learner.getAlternativeSuggestion(toolName, context);
//     // sugerir alt.alternative o devolver alt.reason
//   }

const crypto = require('crypto');

// ═══════════════════════════════════════════════════════════
//  CONSTANTES
// ═══════════════════════════════════════════════════════════

/** Namespace en kv_store para los datos de ToolLearner. */
const NAMESPACE = 'tool_learner';

/** Clave especial para el índice de herramientas con historial. */
const META_INDEX_KEY = '_index';

/** Umbral de fallos consecutivos para considerar una tool bloqueada. */
const FAILURE_THRESHOLD = 3;

/** Score por debajo del cual una tool se considera bloqueada en el contexto. */
const BLOCK_THRESHOLD = 0.2;

/** Score neutral cuando no hay historial previo. */
const NEUTRAL_SCORE = 0.5;

/** Score máximo (tool funciona perfectamente en el contexto). */
const MAX_SCORE = 1.0;

/** Score mínimo (tool completamente bloqueada en el contexto). */
const MIN_SCORE = 0.0;

// ═══════════════════════════════════════════════════════════
//  MAPA DE ALTERNATIVAS
// ═══════════════════════════════════════════════════════════

/**
 * Mapa de herramientas bloqueadas → alternativa sugerida.
 * Cada entrada tiene `alternative` (nombre de la tool alternativa) y
 * `reason` (explicación en español de por qué se sugiere).
 * @type {Object<string, {alternative: string, reason: string}>}
 */
const ALTERNATIVES = {
  browser_navigate: {
    alternative: 'web_search',
    reason: 'Usa búsqueda web vía API en lugar de navegación por navegador.',
  },
  browser_click: {
    alternative: 'browser_extract',
    reason: 'Intenta extraer directamente el contenido sin interactuar con la página.',
  },
  browser_fill_form: {
    alternative: 'web_search',
    reason: 'Busca la información vía API web en lugar de rellenar formularios.',
  },
  twitter_search: {
    alternative: 'google_news',
    reason: 'Usa Google News como fuente alternativa de noticias y tendencias.',
  },
  ml_search: {
    alternative: 'amazon_scraper',
    reason: 'Usa scraper de Amazon en lugar de búsqueda en Mercado Libre.',
  },
  drive_download: {
    alternative: 'download_url_to_desktop',
    reason: 'Descarga directa vía URL si el archivo tiene enlace público.',
  },
  gmail_send: {
    alternative: 'whatsapp_send',
    reason: 'Envía el mensaje por WhatsApp como canal alternativo.',
  },
  gmail_read: {
    alternative: 'gmail_search',
    reason: 'Usa búsqueda de Gmail con criterios más específicos.',
  },
  calendar_create: {
    alternative: 'calendar_find_slot',
    reason: 'Primero busca un espacio libre antes de intentar crear el evento.',
  },
  calendar_list: {
    alternative: 'calendar_find_slot',
    reason: 'Busca disponibilidad directamente en lugar de listar todos los eventos.',
  },
  code_python: {
    alternative: 'code_javascript',
    reason: 'Intenta resolver el problema con JavaScript en lugar de Python.',
  },
  code_javascript: {
    alternative: 'code_shell',
    reason: 'Ejecuta un comando de shell como alternativa a JavaScript.',
  },
  code_shell: {
    alternative: 'code_python',
    reason: 'Intenta resolverlo con un script de Python en lugar de shell.',
  },
  whatsapp_send: {
    alternative: 'gmail_send',
    reason: 'Envía la información por correo electrónico como alternativa a WhatsApp.',
  },
};

/** Mensaje cuando no hay alternativa disponible. */
const NO_ALTERNATIVE_MSG = 'Sin alternativa disponible. Intenta reformular tu petición.';

// ═══════════════════════════════════════════════════════════
//  HELPERS
// ═══════════════════════════════════════════════════════════

/**
 * Calcula un hash determinístico de una cadena de texto.
 * Usa SHA-256 truncado a 12 caracteres hexadecimales para evitar colisiones
 * y mantener claves compactas en kv_store.
 *
 * @param {string} str — Cadena a hashear.
 * @returns {string} Hash hexadecimal de 12 caracteres.
 */
function hashString(str) {
  if (!str) return '000000000000';
  return crypto.createHash('sha256').update(String(str)).digest('hex').slice(0, 12);
}

/**
 * Construye la clave KV para el historial de una tool en un contexto dado.
 *
 * @param {string} toolName — Nombre de la herramienta.
 * @param {string} contextHash — Hash del contexto.
 * @returns {string} Clave formateada para kv_store.
 */
function historyKey(toolName, contextHash) {
  return `history:${toolName}:${contextHash}`;
}

/**
 * Serializa un objeto a JSON de forma segura.
 *
 * @param {*} obj — Objeto a serializar.
 * @returns {string} Representación JSON o '{}' si falla.
 */
function safeJson(obj) {
  try {
    return JSON.stringify(obj);
  } catch {
    return '{}';
  }
}

/**
 * Parsea una cadena JSON de forma segura.
 *
 * @param {string} str — Cadena JSON.
 * @param {*} fallback — Valor por defecto si el parseo falla.
 * @returns {*} Objeto parseado o fallback.
 */
function safeParse(str, fallback) {
  if (!str) return fallback;
  try {
    return JSON.parse(str);
  } catch {
    return fallback;
  }
}

// ═══════════════════════════════════════════════════════════
//  CLASE ToolLearner
// ═══════════════════════════════════════════════════════════

class ToolLearner {
  constructor() {
    /** @type {import('./local-db.cjs').kvGet | null} */
    this._kvGet = null;
    /** @type {import('./local-db.cjs').kvSet | null} */
    this._kvSet = null;
    /** @type {Set<string>} Índice en memoria de herramientas con historial. */
    this._toolIndex = new Set();
    /** @type {boolean} Si init() fue llamado exitosamente. */
    this._initialized = false;
  }

  // ── Inicialización ────────────────────────────────────

  /**
   * Inicializa el ToolLearner vinculándolo a la base de datos local.
   * Carga el índice de herramientas desde kv_store si existe.
   *
   * Debe llamarse una sola vez después de que localDb.init() haya completado.
   *
   * @param {object} localDb — Módulo local-db.cjs exportado (requiere kvGet y kvSet).
   * @returns {boolean} true si se inicializó correctamente.
   */
  init(localDb) {
    if (!localDb || typeof localDb.kvGet !== 'function' || typeof localDb.kvSet !== 'function') {
      console.error('[tool-learner] init: localDb debe exportar kvGet y kvSet.');
      return false;
    }

    this._kvGet = localDb.kvGet;
    this._kvSet = localDb.kvSet;

    // Cargar índice de herramientas desde kv_store
    try {
      const raw = this._kvGet(META_INDEX_KEY, NAMESPACE);
      if (raw) {
        const parsed = safeParse(raw, []);
        this._toolIndex = new Set(Array.isArray(parsed) ? parsed : []);
      }
    } catch (err) {
      console.warn('[tool-learner] No se pudo cargar el índice, se usará uno vacío.', err.message);
      this._toolIndex = new Set();
    }

    this._initialized = true;
    console.log(`[tool-learner] Inicializado. ${this._toolIndex.size} herramientas con historial.`);
    return true;
  }

  /**
   * Verifica que el learner esté inicializado. Lanza si no.
   * @throws {Error} Si init() no fue llamado.
   */
  _requireInit() {
    if (!this._initialized || !this._kvGet || !this._kvSet) {
      throw new Error('ToolLearner no inicializado. Llama a init(localDb) primero.');
    }
  }

  // ── Persistencia del índice ───────────────────────────

  /**
   * Persiste el índice de herramientas en kv_store.
   * @private
   */
  _saveIndex() {
    if (!this._kvSet) return;
    try {
      this._kvSet(META_INDEX_KEY, safeJson([...this._toolIndex]), NAMESPACE);
    } catch (err) {
      console.error('[tool-learner] Error al guardar índice:', err.message);
    }
  }

  /**
   * Registra una herramienta en el índice si no estaba ya.
   * @private
   * @param {string} toolName — Nombre de la herramienta.
   */
  _registerTool(toolName) {
    if (!this._toolIndex.has(toolName)) {
      this._toolIndex.add(toolName);
      this._saveIndex();
    }
  }

  // ── Persistencia de lista de contextos ────────────────

  /**
   * Añade un hash de contexto a la lista de contextos de una herramienta.
   * Esto permite que getFailureReport() recorra todos los contextos
   * conocidos para cada herramienta.
   *
   * @param {string} toolName — Nombre de la herramienta.
   * @param {string} ctxHash — Hash del contexto.
   * @private
   */
  _addContextToTool(toolName, ctxHash) {
    if (!this._kvGet || !this._kvSet) return;

    const ctxListKey = `_ctxlist:${toolName}`;
    const raw = this._kvGet(ctxListKey, NAMESPACE);
    const ctxList = safeParse(raw, []);

    if (!ctxList.includes(ctxHash)) {
      ctxList.push(ctxHash);
      // Limitar a 50 contextos por herramienta para evitar crecimiento ilimitado
      while (ctxList.length > 50) ctxList.shift();
      try {
        this._kvSet(ctxListKey, safeJson(ctxList), NAMESPACE);
      } catch { /* ignorar */ }
    }
  }

  // ── Registro de llamadas ──────────────────────────────

  /**
   * Registra una llamada a una herramienta con su resultado.
   *
   * Actualiza el historial en kv_store para la combinación tool+contexto.
   * Si la tool falla 3+ veces en el mismo contexto, su score bajará de 0.2
   * y getBlockedTools() la reportará como bloqueada.
   *
   * @param {string} toolName — Nombre de la herramienta ejecutada.
   * @param {string} context — Descripción del contexto/tarea (ej. "búsqueda de vuelos").
   * @param {boolean} success — true si la ejecución fue exitosa.
   * @param {string} [errorMsg=''] — Mensaje de error si falló.
   * @param {number} [durationMs=0] — Duración de la ejecución en milisegundos.
   * @returns {{score: number, blocked: boolean}} Score actual y si está bloqueada.
   */
  recordToolCall(toolName, context, success, errorMsg, durationMs) {
    this._requireInit();

    const ctxHash = hashString(context || '');
    const key = historyKey(toolName, ctxHash);
    const now = new Date().toISOString();

    // Registrar tool en el índice
    this._registerTool(toolName);

    // Cargar historial existente para tool+contexto
    const raw = this._kvGet(key, NAMESPACE);
    const history = safeParse(raw, {
      successes: 0,
      failures: 0,
      lastError: null,
      lastSuccessAt: null,
      lastFailureAt: null,
      context: context || '',
    });

    // Actualizar contadores
    if (success) {
      history.successes += 1;
      history.lastSuccessAt = now;
    } else {
      history.failures += 1;
      history.lastError = errorMsg || 'Error desconocido';
      history.lastFailureAt = now;
    }
    history.context = context || '';

    // Persistir historial
    try {
      this._kvSet(key, safeJson(history), NAMESPACE);
    } catch (err) {
      console.error('[tool-learner] Error al persistir historial:', err.message);
    }

    // Registrar el contexto para que getFailureReport() pueda recorrerlo
    this._addContextToTool(toolName, ctxHash);

    // Calcular score actual
    const score = this._computeScore(history.successes, history.failures);
    const blocked = score < BLOCK_THRESHOLD;

    if (blocked) {
      console.warn(
        `[tool-learner] ⚠ ${toolName} BLOQUEADA en contexto "${context}". ` +
        `Score: ${score.toFixed(2)} (${history.successes} éxitos, ${history.failures} fallos)`
      );
    }

    return { score, blocked };
  }

  /**
   * Calcula el score de una herramienta a partir de sus contadores.
   * Fórmula: successes / (successes + failures * 2)
   *
   * - Sin historial → 0.5 (neutral)
   * - Solo éxitos → 1.0 (confiable)
   * - 3+ fallos sin éxitos → < 0.2 (bloqueada)
   *
   * @param {number} successes — Número de ejecuciones exitosas.
   * @param {number} failures — Número de ejecuciones fallidas.
   * @returns {number} Score entre 0.0 y 1.0.
   * @private
   */
  _computeScore(successes, failures) {
    const total = successes + failures;
    if (total === 0) return NEUTRAL_SCORE;

    const raw = successes / (successes + failures * 2);
    return Math.max(MIN_SCORE, Math.min(MAX_SCORE, raw));
  }

  // ── Consulta de score ─────────────────────────────────

  /**
   * Obtiene el score de confiabilidad de una herramienta en un contexto dado.
   *
   * - 1.0 = la herramienta funciona bien en este contexto.
   * - 0.5 = sin historial (neutral).
   * - 0.0 = falló 3+ veces, debe evitarse.
   *
   * @param {string} toolName — Nombre de la herramienta.
   * @param {string} context — Descripción del contexto/tarea.
   * @returns {number} Score entre 0.0 y 1.0.
   */
  getToolScore(toolName, context) {
    this._requireInit();

    const ctxHash = hashString(context || '');
    const key = historyKey(toolName, ctxHash);
    const raw = this._kvGet(key, NAMESPACE);

    if (!raw) return NEUTRAL_SCORE;

    const history = safeParse(raw, null);
    if (!history) return NEUTRAL_SCORE;

    return this._computeScore(history.successes || 0, history.failures || 0);
  }

  // ── Herramientas bloqueadas ───────────────────────────

  /**
   * Devuelve los nombres de las herramientas bloqueadas en el contexto dado.
   * Una herramienta está bloqueada si su score es < 0.2 en ese contexto.
   *
   * @param {string} context — Descripción del contexto/tarea.
   * @returns {string[]} Array de nombres de herramientas bloqueadas.
   */
  getBlockedTools(context) {
    this._requireInit();

    const ctxHash = hashString(context || '');
    const blocked = [];

    for (const toolName of this._toolIndex) {
      const key = historyKey(toolName, ctxHash);
      const raw = this._kvGet(key, NAMESPACE);

      if (!raw) continue; // Sin historial en este contexto → no bloqueada

      const history = safeParse(raw, null);
      if (!history) continue;

      const score = this._computeScore(history.successes || 0, history.failures || 0);
      if (score < BLOCK_THRESHOLD) {
        blocked.push(toolName);
      }
    }

    return blocked;
  }

  // ── Sugerencia de alternativa ─────────────────────────

  /**
   * Sugiere una herramienta alternativa cuando la original está bloqueada.
   *
   * Usa el mapa ALTERNATIVES para herramientas conocidas. Si la herramienta
   * no tiene una entrada en el mapa, devuelve un mensaje genérico.
   *
   * @param {string} blockedTool — Nombre de la herramienta bloqueada.
   * @param {string} context — Descripción del contexto/tarea (para logging).
   * @returns {{alternative: string | null, reason: string}} Sugerencia con nombre y razón.
   */
  getAlternativeSuggestion(blockedTool, context) {
    const entry = ALTERNATIVES[blockedTool];

    if (entry) {
      console.log(
        `[tool-learner] Alternativa para ${blockedTool} en "${context}": ` +
        `${entry.alternative} — ${entry.reason}`
      );
      return { alternative: entry.alternative, reason: entry.reason };
    }

    console.log(
      `[tool-learner] Sin alternativa definida para ${blockedTool} en "${context}".`
    );
    return { alternative: null, reason: NO_ALTERNATIVE_MSG };
  }

  // ── Reporte de fallos ─────────────────────────────────

  /**
   * Genera un reporte agregado del aprendizaje de herramientas.
   *
   * Recorre todas las herramientas con historial y calcula métricas globales:
   * total de llamadas, tasa de éxito, top herramientas bloqueadas y confiables.
   *
   * @returns {{
   *   totalCalls: number,
   *   successRate: number,
   *   topBlockedTools: Array<{tool: string, failures: number, lastError: string | null}>,
   *   topReliableTools: Array<{tool: string, successes: number}>
   * }} Reporte de fallos agregado.
   */
  getFailureReport() {
    this._requireInit();

    const allTools = [];
    let totalSuccesses = 0;
    let totalFailures = 0;

    // Recorrer todas las herramientas del índice y agregar sus historiales
    for (const toolName of this._toolIndex) {
      let toolSuccesses = 0;
      let toolFailures = 0;
      let lastError = null;

      // Recorrer todos los contextos conocidos para esta herramienta
      const ctxListKey = `_ctxlist:${toolName}`;
      const ctxListRaw = this._kvGet(ctxListKey, NAMESPACE);
      const ctxList = safeParse(ctxListRaw, []);

      for (const ctxHash of ctxList) {
        const key = historyKey(toolName, ctxHash);
        const raw = this._kvGet(key, NAMESPACE);
        if (!raw) continue;
        const h = safeParse(raw, null);
        if (!h) continue;
        toolSuccesses += h.successes || 0;
        toolFailures += h.failures || 0;
        if (h.lastError) lastError = h.lastError;
      }

      totalSuccesses += toolSuccesses;
      totalFailures += toolFailures;

      allTools.push({
        tool: toolName,
        successes: toolSuccesses,
        failures: toolFailures,
        lastError,
      });
    }

    const totalCalls = totalSuccesses + totalFailures;
    const successRate = totalCalls > 0 ? totalSuccesses / totalCalls : 0;

    // Top bloqueadas: más fallos primero
    const topBlockedTools = allTools
      .filter(t => t.failures >= FAILURE_THRESHOLD)
      .sort((a, b) => b.failures - a.failures)
      .slice(0, 10)
      .map(t => ({ tool: t.tool, failures: t.failures, lastError: t.lastError }));

    // Top confiables: más éxitos primero
    const topReliableTools = allTools
      .filter(t => t.successes > 0)
      .sort((a, b) => b.successes - a.successes)
      .slice(0, 10)
      .map(t => ({ tool: t.tool, successes: t.successes }));

    return {
      totalCalls,
      successRate: Math.round(successRate * 1000) / 1000,
      topBlockedTools,
      topReliableTools,
    };
  }

  // ── Reinicio ──────────────────────────────────────────

  /**
   * Borra todo el historial de aprendizaje y reinicia el estado.
   *
   * Elimina todas las claves del namespace 'tool_learner' en kv_store
   * y vacía el índice en memoria.
   *
   * ADVERTENCIA: Esta operación es irreversible. Todo el conocimiento
   * aprendido sobre fallos de herramientas se perderá.
   */
  resetLearning() {
    this._requireInit();

    // Borrar historial de cada tool+contexto conocido
    for (const toolName of this._toolIndex) {
      const ctxListKey = `_ctxlist:${toolName}`;
      const ctxListRaw = this._kvGet(ctxListKey, NAMESPACE);
      const ctxList = safeParse(ctxListRaw, []);

      for (const ctxHash of ctxList) {
        const key = historyKey(toolName, ctxHash);
        try {
          this._kvSet(key, '', NAMESPACE);
        } catch { /* ignorar errores de borrado */ }
      }

      // Borrar lista de contextos de la herramienta
      try {
        this._kvSet(ctxListKey, '', NAMESPACE);
      } catch { /* ignorar */ }
    }

    // Borrar índice
    try {
      this._kvSet(META_INDEX_KEY, '', NAMESPACE);
    } catch { /* ignorar */ }

    this._toolIndex.clear();
    console.log('[tool-learner] Historial de aprendizaje reiniciado completamente.');
  }
}

// ═══════════════════════════════════════════════════════════
//  EXPORTACIONES
// ═══════════════════════════════════════════════════════════

module.exports = {
  ToolLearner,
  ALTERNATIVES,
  NAMESPACE,
  BLOCK_THRESHOLD,
  NEUTRAL_SCORE,
  FAILURE_THRESHOLD,
};
