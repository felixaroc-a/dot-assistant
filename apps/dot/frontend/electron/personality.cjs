// personality.cjs — Sistema de personalidad que aprende del usuario
//
// Implementa 4 estilos de personalidad para DOT y un sistema de aprendizaje
// que adapta tono y preferencias basándose en las interacciones del usuario.
//
// Diseñado según BIBLIA.md §18 (Hexagonal+DDD): esta capa de infraestructura
// persiste en kv_store de local-db con namespace 'personality'.
//
// Estilos disponibles (según M4S4-A):
//   - cercano:   tono cálido, amigable, con emojis ocasionales
//   - formal:    tono educado, respetuoso, sin emojis
//   - ejecutivo: tono directo, conciso, profesional
//   - creativo:  tono imaginativo, inspirador, flexible

// ─── Referencia al módulo local-db (inyectado en init) ─────
/** @type {object | null} */
let _localDb = null;

// ─── Conexión a la DB (singleton obtenido vía localDb.init) ─
/** @type {import('better-sqlite3').Database | null} */
let _db = null;

// ─── Namespace en kv_store para este módulo ────────────────
const KV_NAMESPACE = 'personality';

// ═══════════════════════════════════════════════════════════
//  CONSTANTES
// ═══════════════════════════════════════════════════════════

/** Estilos de personalidad disponibles */
const STYLES = ['cercano', 'formal', 'ejecutivo', 'creativo'];

/** Estilo por defecto si no hay ninguno configurado */
const DEFAULT_STYLE = 'cercano';

/** Preferencias por defecto */
const DEFAULT_PREFERENCES = {
  language: 'español',
  responseLength: 'media',    // 'corta' | 'media' | 'larga'
  emojiUsage: 0.5,            // 0.0 a 1.0 (probabilidad de usar emojis)
  formality: 0.5,             // 0.0 (muy casual) a 1.0 (muy formal)
};

/** Tono por defecto si no hay datos de aprendizaje */
const DEFAULT_TONE = 'casual';

/** Claves en kv_store */
const KV_KEYS = {
  STYLE: 'style',
  TONE: 'tone',
  PREFERENCES: 'preferences',
  LEARNED_AT: 'learned_at',
  INTERACTION_COUNT: 'interaction_count',
};

// ═══════════════════════════════════════════════════════════
//  HELPERS INTERNOS
// ═══════════════════════════════════════════════════════════

/**
 * Asegura que la DB esté inicializada antes de cualquier operación.
 * @returns {import('better-sqlite3').Database}
 */
function _ensureDb() {
  if (!_db) {
    if (!_localDb) throw new Error('[personality] localDb no inicializado. Llama a init() primero.');
    _db = _localDb.init();
  }
  return _db;
}

/**
 * Lee un valor desde kv_store en el namespace 'personality'.
 * @param {string} key — Clave a leer.
 * @returns {string | null} Valor almacenado o null.
 */
function _kvGet(key) {
  try {
    const row = _ensureDb()
      .prepare('SELECT value FROM kv_store WHERE key = ? AND namespace = ?')
      .get(key, KV_NAMESPACE);
    return row ? row.value : null;
  } catch (err) {
    console.error('[personality] Error en _kvGet:', err.message);
    return null;
  }
}

/**
 * Escribe un valor en kv_store en el namespace 'personality'.
 * @param {string} key — Clave a escribir.
 * @param {string} value — Valor a guardar.
 */
function _kvSet(key, value) {
  try {
    _ensureDb()
      .prepare(`
        INSERT INTO kv_store (key, value, namespace)
        VALUES (?, ?, ?)
        ON CONFLICT(key) DO UPDATE SET value = excluded.value, namespace = excluded.namespace
      `)
      .run(key, value, KV_NAMESPACE);
  } catch (err) {
    console.error('[personality] Error en _kvSet:', err.message);
  }
}

/**
 * Elimina una clave del kv_store en el namespace 'personality'.
 * @param {string} key — Clave a eliminar.
 */
function _kvDelete(key) {
  try {
    _ensureDb()
      .prepare('DELETE FROM kv_store WHERE key = ? AND namespace = ?')
      .run(key, KV_NAMESPACE);
  } catch (err) {
    console.error('[personality] Error en _kvDelete:', err.message);
  }
}

/**
 * Carga todas las preferencias desde kv_store, aplicando defaults donde falten.
 * @returns {object} Objeto de preferencias completo.
 */
function _loadPreferences() {
  const raw = _kvGet(KV_KEYS.PREFERENCES);
  if (raw) {
    try {
      const parsed = JSON.parse(raw);
      // Fusionar con defaults para cubrir campos nuevos que no existían antes
      return { ...DEFAULT_PREFERENCES, ...parsed };
    } catch {
      console.warn('[personality] Preferencias corruptas en kv_store. Usando defaults.');
    }
  }
  return { ...DEFAULT_PREFERENCES };
}

/**
 * Guarda las preferencias en kv_store como JSON.
 * @param {object} prefs — Objeto de preferencias.
 */
function _savePreferences(prefs) {
  _kvSet(KV_KEYS.PREFERENCES, JSON.stringify(prefs));
}

/**
 * Incrementa el contador de interacciones y actualiza learned_at.
 */
function _recordInteraction() {
  const raw = _kvGet(KV_KEYS.INTERACTION_COUNT);
  const count = raw ? parseInt(raw, 10) + 1 : 1;
  _kvSet(KV_KEYS.INTERACTION_COUNT, String(count));
  _kvSet(KV_KEYS.LEARNED_AT, new Date().toISOString());
}

// ═══════════════════════════════════════════════════════════
//  DETECCIÓN DE TONO Y ANÁLISIS DE MENSAJES
// ═══════════════════════════════════════════════════════════

/**
 * Analiza un mensaje de usuario para detectar patrones de tono y formalidad.
 *
 * @param {string} message — Mensaje del usuario.
 * @returns {object} Señales detectadas:
 *   {formalitySignals: number, emojiSignals: number, technicalSignals: number,
 *    emotionalSignals: number, slangSignals: number}
 */
function _analyzeMessage(message) {
  const text = message.toLowerCase();

  // ── Señales de formalidad (+1 por cada ocurrencia) ──
  const formalPatterns = [
    /\bpor favor\b/g, /\bgracias\b/g, /\bdisculpe\b/g,
    /\bpodría\b/g, /\bquisiera\b/g, /\busted\b/g,
    /\bsaludos cordiales\b/g, /\batentamente\b/g,
    /\bestimado\b/g, /\bdistinguido\b/g, /\bsolicitar\b/g,
  ];

  // ── Señales de jerga / informalidad ──
  const slangPatterns = [
    /\bwey\b/g, /\bweón\b/g, /\bjaja\b/g, /\bxd\b/g,
    /\bbro\b/g, /\btío\b/g, /\bparce\b/g, /\bchamo\b/g,
    /\bpana\b/g, /\bbacán\b/g, /\bchévere\b/g,
    /\bque onda\b/g, /\bqué más\b/g, /\bhágale\b/g,
  ];

  // ── Señales de lenguaje técnico ──
  const technicalPatterns = [
    /\bapi\b/g, /\bcódigo\b/g, /\bservidor\b/g, /\bbase de datos\b/g,
    /\bpython\b/g, /\bjavascript\b/g, /\breact\b/g, /\bdocker\b/g,
    /\bendpoint\b/g, /\bsql\b/g, /\bjson\b/g, /\bgit\b/g,
    /\bprogramar\b/g, /\bscript\b/g, /\bautomati[zc]ar\b/g, /\bdeploy\b/g,
    /\bfunción\b/g, /\balgoritmo\b/g, /\bconfigurar\b/g, /\bdebug\b/g,
  ];

  // ── Señales emocionales ──
  const emotionalPatterns = [
    /\bme siento\b/g, /\bestoy\s+(feliz|triste|enojad[oa]|cansad[oa]|emocionad[oa]|preocupad[oa])\b/g,
    /\bme alegra\b/g, /\bme duele\b/g, /\bme molesta\b/g, /\bme encanta\b/g,
    /\bte quiero\b/g, /\bte odio\b/g, /\badiós\b/g, /\bhasta luego\b/g,
  ];

  // ── Señales de emojis (unicode emoji ranges) ──
  const emojiRegex = /[\p{Emoji_Presentation}\p{Extended_Pictographic}]/gu;
  const emojiMatches = message.match(emojiRegex) || [];

  // Contar señales
  let formalitySignals = 0;
  for (const pattern of formalPatterns) {
    const matches = text.match(pattern);
    if (matches) formalitySignals += matches.length;
  }

  let slangSignals = 0;
  for (const pattern of slangPatterns) {
    const matches = text.match(pattern);
    if (matches) slangSignals += matches.length;
  }

  let technicalSignals = 0;
  for (const pattern of technicalPatterns) {
    const matches = text.match(pattern);
    if (matches) technicalSignals += matches.length;
  }

  let emotionalSignals = 0;
  for (const pattern of emotionalPatterns) {
    const matches = text.match(pattern);
    if (matches) emotionalSignals += matches.length;
  }

  return {
    formalitySignals,
    slangSignals,
    technicalSignals,
    emotionalSignals,
    emojiSignals: emojiMatches.length,
  };
}

// ═══════════════════════════════════════════════════════════
//  GENERACIÓN DE SYSTEM PROMPT
// ═══════════════════════════════════════════════════════════

/**
 * Plantillas de system prompt por estilo de personalidad.
 * Cada plantilla recibe las preferencias para ajustar el tono.
 *
 * @type {Record<string, function(object): string>}
 */
const PROMPT_TEMPLATES = {
  cercano(prefs) {
    const emojiNote = prefs.emojiUsage > 0.5
      ? 'Usa emojis frecuentemente para expresar calidez. 😊'
      : 'Usa emojis ocasionalmente para dar un toque personal.';
    const lengthNote = prefs.responseLength === 'corta'
      ? 'Responde de forma breve y directa, sin rodeos.'
      : prefs.responseLength === 'larga'
        ? 'Puedes desarrollar respuestas completas, con ejemplos cuando sea útil.'
        : 'Mantén respuestas equilibradas, ni muy cortas ni muy largas.';

    return [
      'Eres DOT, un asistente IA amigable y cercano.',
      'Habla en español con un tono cálido y natural, como si fueras un amigo de confianza.',
      emojiNote,
      lengthNote,
      'Tu objetivo es hacer que el usuario se sienta acompañado y comprendido.',
      'Muestra empatía, haz preguntas de seguimiento y celebra los logros del usuario.',
      `Nivel de formalidad: ${prefs.formality < 0.4 ? 'muy casual' : prefs.formality > 0.7 ? 'moderadamente formal' : 'equilibrado'}.`,
    ].join('\n');
  },

  formal(prefs) {
    const emojiNote = prefs.emojiUsage > 0.3
      ? 'Evita los emojis; prioriza un lenguaje claro y profesional.'
      : 'No uses emojis en absoluto.';
    const lengthNote = prefs.responseLength === 'corta'
      ? 'Responde con precisión y brevedad, sin divagaciones.'
      : prefs.responseLength === 'larga'
        ? 'Proporciona respuestas detalladas y estructuradas cuando sea apropiado.'
        : 'Mantén un equilibrio entre brevedad y completitud.';

    return [
      'Eres DOT, un asistente IA formal y profesional.',
      'Habla en español con corrección gramatical, usando "usted" como forma de tratamiento.',
      emojiNote,
      lengthNote,
      'Mantén siempre un tono respetuoso, educado y apropiado.',
      'Estructura tus respuestas con claridad, usando párrafos bien formados.',
      'Evita coloquialismos, jerga y expresiones demasiado informales.',
    ].join('\n');
  },

  ejecutivo(prefs) {
    return [
      'Eres DOT, un asistente IA ejecutivo y altamente eficiente.',
      'Habla en español. Responde de forma concisa, directa y sin rodeos.',
      'Ve al grano. No uses emojis ni adornos innecesarios.',
      'Prioriza la acción y los resultados. Cada palabra debe aportar valor.',
      'Si das opciones, preséntalas como lista numerada para decisión rápida.',
      'Tu tono es seguro, profesional y orientado a resolver.',
      prefs.responseLength === 'larga'
        ? 'Cuando el tema lo requiera, puedes profundizar, pero siempre estructurado.'
        : 'Sé breve incluso cuando expliques conceptos complejos.',
    ].join('\n');
  },

  creativo(prefs) {
    const emojiNote = prefs.emojiUsage > 0.3
      ? 'Los emojis son bienvenidos como herramienta expresiva. 🎨'
      : 'Usa recursos visuales como analogías y metáforas en lugar de emojis.';
    const lengthNote = prefs.responseLength === 'corta'
      ? 'Sé creativo incluso en la brevedad: ideas compactas pero inspiradoras.'
      : prefs.responseLength === 'larga'
        ? 'Explora ideas con profundidad, usando ejemplos y narrativa cuando enriquezca la respuesta.'
        : 'Equilibra creatividad con claridad, sin perder el foco.';

    return [
      'Eres DOT, un asistente IA creativo e inspirador.',
      'Habla en español con un tono imaginativo, fresco y motivador.',
      emojiNote,
      lengthNote,
      'Usa metáforas, analogías y ejemplos visuales para explicar conceptos.',
      'Propón ideas fuera de lo común y anima al usuario a explorar nuevas perspectivas.',
      'Tu misión es inspirar, no solo informar.',
    ].join('\n');
  },
};

// ═══════════════════════════════════════════════════════════
//  API PÚBLICA
// ═══════════════════════════════════════════════════════════

/**
 * Inicializa el módulo de personalidad.
 * Carga el estilo, tono y preferencias desde kv_store.
 * Si no existen datos previos, usa los valores por defecto.
 *
 * @param {object} localDbModule — Módulo local-db (requiere local-db.cjs).
 */
function init(localDbModule) {
  if (_localDb) {
    console.warn('[personality] Ya inicializado. Se omite segunda llamada.');
    return;
  }

  _localDb = localDbModule;
  _db = localDbModule.init();

  // Asegurar que existan valores por defecto en kv_store si no hay nada
  const existingStyle = _kvGet(KV_KEYS.STYLE);
  if (!existingStyle) {
    _kvSet(KV_KEYS.STYLE, DEFAULT_STYLE);
  }

  const existingPrefs = _kvGet(KV_KEYS.PREFERENCES);
  if (!existingPrefs) {
    _kvSet(KV_KEYS.PREFERENCES, JSON.stringify(DEFAULT_PREFERENCES));
  }

  const existingTone = _kvGet(KV_KEYS.TONE);
  if (!existingTone) {
    _kvSet(KV_KEYS.TONE, DEFAULT_TONE);
  }

  console.log('[personality] Módulo inicializado. Estilo:', existingStyle || DEFAULT_STYLE);
}

/**
 * Obtiene el estilo de personalidad actual.
 *
 * @returns {string} Estilo actual: 'cercano' | 'formal' | 'ejecutivo' | 'creativo'.
 */
function getStyle() {
  const style = _kvGet(KV_KEYS.STYLE);
  if (style && STYLES.includes(style)) {
    return style;
  }
  // Si el valor está corrupto o no existe, restaurar default
  _kvSet(KV_KEYS.STYLE, DEFAULT_STYLE);
  return DEFAULT_STYLE;
}

/**
 * Cambia el estilo de personalidad.
 * Solo acepta valores dentro de STYLES.
 *
 * @param {string} style — Nuevo estilo ('cercano' | 'formal' | 'ejecutivo' | 'creativo').
 * @returns {boolean} true si se cambió correctamente, false si el estilo es inválido.
 */
function setStyle(style) {
  if (!STYLES.includes(style)) {
    console.warn('[personality] Estilo inválido:', style, '— válidos:', STYLES.join(', '));
    return false;
  }

  _kvSet(KV_KEYS.STYLE, style);
  _kvSet(KV_KEYS.LEARNED_AT, new Date().toISOString());
  console.log('[personality] Estilo cambiado a:', style);
  return true;
}

/**
 * Obtiene el tono detectado del usuario basado en el aprendizaje.
 *
 * @returns {string} Tono detectado: 'formal' | 'casual' | 'tecnico' | 'emocional'.
 */
function getUserTone() {
  const tone = _kvGet(KV_KEYS.TONE);
  const validTones = ['formal', 'casual', 'tecnico', 'emocional'];
  if (tone && validTones.includes(tone)) {
    return tone;
  }
  return DEFAULT_TONE;
}

/**
 * Obtiene las preferencias actuales del usuario.
 *
 * @returns {object} {language, responseLength, emojiUsage, formality}
 */
function getPreferences() {
  return _loadPreferences();
}

/**
 * Genera un system prompt basado en el estilo actual y las preferencias del usuario.
 * Este prompt debe inyectarse al inicio de cada conversación para que el modelo
 * de IA adopte la personalidad configurada.
 *
 * @returns {string} System prompt completo para el modelo de IA.
 */
function generateSystemPrompt() {
  const style = getStyle();
  const prefs = getPreferences();
  const template = PROMPT_TEMPLATES[style];

  if (!template) {
    console.warn('[personality] Plantilla no encontrada para estilo:', style, '— usando cercano.');
    return PROMPT_TEMPLATES.cercano(prefs);
  }

  return template(prefs);
}

/**
 * Aprende de una interacción usuario-asistente, adaptando preferencias y tono.
 *
 * Analiza el mensaje del usuario en busca de señales de:
 *   - Formalidad (palabras como "por favor", "gracias", "usted")
 *   - Jerga / informalidad ("wey", "jaja", emojis)
 *   - Lenguaje técnico (API, código, programar)
 *   - Emocionalidad ("me siento", "estoy feliz")
 *
 * Las preferencias se ajustan gradualmente (factor de aprendizaje 0.1)
 * para cambios suaves y no bruscos.
 *
 * @param {string} userMessage — Mensaje enviado por el usuario.
 * @param {string} assistantResponse — Respuesta del asistente (para contexto,
 *   aunque el aprendizaje se basa principalmente en el mensaje del usuario).
 */
function learnFromInteraction(userMessage, assistantResponse) {
  if (!userMessage || typeof userMessage !== 'string') return;

  const signals = _analyzeMessage(userMessage);
  const prefs = _loadPreferences();

  // ── Factor de aprendizaje: qué tan rápido se adaptan las preferencias ──
  // Un valor bajo (0.1) significa cambios graduales; evita oscilaciones bruscas.
  const LEARNING_RATE = 0.1;

  // ── 1. Ajustar formalidad ──
  // Señales formales empujan formality hacia 1.0; slang la empuja hacia 0.0.
  const formalityDelta = (signals.formalitySignals * 0.05) - (signals.slangSignals * 0.05);
  prefs.formality = Math.max(0, Math.min(1, prefs.formality + formalityDelta * LEARNING_RATE));

  // ── 2. Ajustar uso de emojis ──
  // Si el usuario usa emojis, subimos emojiUsage; si no, baja lentamente.
  if (signals.emojiSignals > 0) {
    prefs.emojiUsage = Math.min(1, prefs.emojiUsage + 0.05 * LEARNING_RATE);
  } else {
    // Decaimiento muy lento de emojiUsage cuando el usuario no usa emojis
    prefs.emojiUsage = Math.max(0, prefs.emojiUsage - 0.01 * LEARNING_RATE);
  }

  // ── 3. Ajustar longitud de respuesta ──
  // Mensajes largos del usuario sugieren que prefiere respuestas más desarrolladas.
  const msgLength = userMessage.length;
  if (msgLength > 500) {
    prefs.responseLength = 'larga';
  } else if (msgLength < 50) {
    prefs.responseLength = 'corta';
  }
  // Si está entre 50-500, mantenemos el valor actual

  // ── 4. Detectar y actualizar tono del usuario ──
  // Se asigna el tono predominante según las señales detectadas.
  const toneScores = {
    formal: signals.formalitySignals,
    casual: signals.slangSignals + signals.emojiSignals,
    tecnico: signals.technicalSignals,
    emocional: signals.emotionalSignals,
  };

  // Solo cambiar el tono si hay al menos 2 señales en alguna categoría
  const maxScore = Math.max(...Object.values(toneScores));
  if (maxScore >= 2) {
    const dominantTone = Object.keys(toneScores).reduce((a, b) =>
      toneScores[a] > toneScores[b] ? a : b,
    );

    // Cambio gradual de tono: solo si la categoría dominante es consistente
    const currentTone = _kvGet(KV_KEYS.TONE) || DEFAULT_TONE;
    if (dominantTone !== currentTone && maxScore >= 3) {
      _kvSet(KV_KEYS.TONE, dominantTone);
      console.log('[personality] Tono actualizado a:', dominantTone);
    }
  }

  // ── 5. Persistir preferencias actualizadas ──
  _savePreferences(prefs);

  // ── 6. Registrar interacción ──
  _recordInteraction();

  console.log(
    '[personality] Aprendizaje registrado —',
    `formality=${prefs.formality.toFixed(2)}, emoji=${prefs.emojiUsage.toFixed(2)},`,
    `length=${prefs.responseLength}, signals:`,
    `formal=${signals.formalitySignals} slang=${signals.slangSignals}`,
    `tech=${signals.technicalSignals} emo=${signals.emotionalSignals} emoji=${signals.emojiSignals}`,
  );
}

/**
 * Obtiene el perfil completo de personalidad del usuario.
 * Útil para mostrarlo en la UI de configuración.
 *
 * @returns {object} {style, tone, preferences, learnedAt, interactionCount}
 */
function getUserProfile() {
  const style = getStyle();
  const tone = getUserTone();
  const prefs = getPreferences();
  const learnedAt = _kvGet(KV_KEYS.LEARNED_AT);
  const interactionCountRaw = _kvGet(KV_KEYS.INTERACTION_COUNT);
  const interactionCount = interactionCountRaw ? parseInt(interactionCountRaw, 10) : 0;

  return {
    style,
    tone,
    preferences: prefs,
    learnedAt: learnedAt || null,
    interactionCount,
  };
}

/**
 * Restaura la personalidad a sus valores por defecto.
 * Borra todo el aprendizaje acumulado y vuelve a los defaults.
 * El contador de interacciones también se reinicia.
 */
function resetToDefaults() {
  _kvSet(KV_KEYS.STYLE, DEFAULT_STYLE);
  _kvSet(KV_KEYS.TONE, DEFAULT_TONE);
  _kvSet(KV_KEYS.PREFERENCES, JSON.stringify(DEFAULT_PREFERENCES));
  _kvDelete(KV_KEYS.LEARNED_AT);
  _kvDelete(KV_KEYS.INTERACTION_COUNT);

  console.log('[personality] Personalidad restaurada a valores por defecto.');
}

// ═══════════════════════════════════════════════════════════
//  EXPORTACIONES
// ═══════════════════════════════════════════════════════════

module.exports = {
  // Constantes
  STYLES,

  // Inicialización
  init,

  // Estilo
  getStyle,
  setStyle,

  // Tono detectado
  getUserTone,

  // Preferencias
  getPreferences,

  // System prompt
  generateSystemPrompt,

  // Aprendizaje
  learnFromInteraction,

  // Perfil completo
  getUserProfile,

  // Reset
  resetToDefaults,
};
