// memory-store.cjs — Memoria semántica del usuario con búsqueda por embeddings
//
// Capa sobre local-db.cjs que agrega búsqueda semántica usando cosine similarity
// sobre embeddings generados por embeddings.cjs (Xenova/all-MiniLM-L6-v2).
//
// Operaciones:
//   addMemory()         — Inserta recuerdo + embedding
//   searchSemantic()    — Búsqueda semántica ordenada por similitud coseno
//   searchByCategory()  — Filtro por categoría
//   decayMemories()     — Reduce importancia de recuerdos viejos
//   archiveMemories()   — Archiva recuerdos muy antiguos
//   getImportantMemories() — Recuerdos con importance > 0.8
//
// Según PLAN-DOT-2026-2027 §M4S1-B — Memoria semántica SQLite

const localDb = require('./local-db.cjs');
const embeddings = require('./embeddings.cjs');

// ═══════════════════════════════════════════════════════════
//  ESTADO INTERNO
// ═══════════════════════════════════════════════════════════

/** @type {import('better-sqlite3').Database | null} */
let db = null;

/** Indica si el esquema extendido ya fue aplicado */
let schemaEnsured = false;

// ═══════════════════════════════════════════════════════════
//  SERIALIZACIÓN DE EMBEDDINGS (Float32Array ↔ BLOB)
// ═══════════════════════════════════════════════════════════

/**
 * Convierte un Float32Array a Buffer para guardar en SQLite como BLOB.
 * @param {Float32Array | null} arr — Vector de embedding.
 * @returns {Buffer | null} Buffer binario o null.
 */
function float32ToBlob(arr) {
  if (!arr) return null;
  return Buffer.from(arr.buffer);
}

/**
 * Convierte un BLOB de SQLite de vuelta a Float32Array.
 * @param {Buffer | null} blob — Dato binario desde SQLite.
 * @returns {Float32Array | null} Vector de embedding o null.
 */
function blobToFloat32(blob) {
  if (!blob) return null;
  return new Float32Array(new Uint8Array(blob).buffer);
}

// ═══════════════════════════════════════════════════════════
//  INICIALIZACIÓN Y ESQUEMA EXTENDIDO
// ═══════════════════════════════════════════════════════════

/**
 * Obtiene la instancia de la base de datos, inicializándola si es necesario.
 * Aplica el esquema extendido (archived_at, memory_archive) la primera vez.
 *
 * @returns {import('better-sqlite3').Database} Instancia de SQLite.
 */
function ensureDb() {
  if (!db) {
    db = localDb.init();
  }
  if (!schemaEnsured) {
    ensureExtendedSchema(db);
    schemaEnsured = true;
  }
  return db;
}

/**
 * Aplica migraciones ligeras al esquema de memoria.
 * - Agrega columna archived_at a la tabla memory si no existe.
 * - Crea tabla memory_archive para almacenar recuerdos archivados.
 *
 * @param {import('better-sqlite3').Database} database — Instancia de SQLite.
 */
function ensureExtendedSchema(database) {
  // Agregar columna archived_at si no existe (SQLite no soporta IF NOT EXISTS en ALTER)
  try {
    database.exec('ALTER TABLE memory ADD COLUMN archived_at TEXT');
    console.log('[memory-store] Columna archived_at agregada a memory');
  } catch (_e) {
    // La columna ya existe — ignorar silenciosamente
  }

  // Crear tabla de archivo si no existe
  database.exec(`
    CREATE TABLE IF NOT EXISTS memory_archive (
      id TEXT PRIMARY KEY,
      content TEXT NOT NULL,
      embedding BLOB,
      category TEXT,
      importance REAL DEFAULT 0.5,
      created_at TEXT,
      decayed_at TEXT,
      archived_at TEXT DEFAULT (datetime('now'))
    )
  `);
}

// ═══════════════════════════════════════════════════════════
//  OPERACIONES DE MEMORIA
// ═══════════════════════════════════════════════════════════

/**
 * Agrega un nuevo recuerdo a la memoria semántica del usuario.
 * Genera un embedding del contenido y lo guarda junto al registro.
 *
 * @param {string} content — Contenido del recuerdo (puede ser multilenguaje).
 * @param {string} [category] — Categoría opcional (ej. 'trabajo', 'personal').
 * @param {number} [importance=0.5] — Importancia inicial (0.0 a 1.0).
 * @returns {Promise<string | null>} ID del recuerdo creado, o null si falla la inserción base.
 */
async function addMemory(content, category, importance) {
  // Insertar el registro base (sin embedding) usando la función simple de local-db
  const id = localDb.addMemory(content, category, importance);
  if (!id) return null;

  // Generar embedding de forma asíncrona y actualizar el registro
  const emb = await embeddings.embed(content);
  if (emb) {
    const database = ensureDb();
    const blob = float32ToBlob(emb);
    database.prepare('UPDATE memory SET embedding = ? WHERE id = ?').run(blob, id);
  }

  return id;
}

/**
 * Busca recuerdos semánticamente similares a la consulta.
 *
 * Algoritmo:
 *   1. Genera embedding de la consulta.
 *   2. Lee TODAS las memorias activas con embedding de SQLite.
 *   3. Calcula cosine_similarity(query_emb, mem_emb) para cada una.
 *   4. Ordena por similitud descendente y retorna el top-K.
 *
 * Target de rendimiento: <200ms para 10,000 memorias en CPU.
 *
 * Si el modelo ONNX no está disponible, degrada a búsqueda por LIKE simple.
 *
 * @param {string} query — Texto de consulta.
 * @param {number} [limit=10] — Máximo de resultados a retornar.
 * @returns {Promise<Array<object>>} Resultados ordenados por similitud (campo `similarity`).
 */
async function searchSemantic(query, limit = 10) {
  const queryEmb = await embeddings.embed(query);

  // Degradación graceful: si no hay modelo, usar búsqueda textual simple
  if (!queryEmb) {
    console.warn('[memory-store] Modelo ONNX no disponible — usando búsqueda textual');
    return localDb.searchMemory(query, limit);
  }

  const database = ensureDb();

  // Leer todas las memorias activas que tienen embedding
  /** @type {Array<{id:string, content:string, embedding:Buffer, category:string|null, importance:number, created_at:string, decayed_at:string|null, archived_at:string|null}>} */
  const rows = database
    .prepare(
      `SELECT * FROM memory
       WHERE embedding IS NOT NULL
         AND archived_at IS NULL`
    )
    .all();

  if (rows.length === 0) return [];

  // Calcular similitud coseno para cada memoria
  const scored = rows.map((row) => {
    const memEmb = blobToFloat32(row.embedding);
    const sim = memEmb ? embeddings.cosineSimilarity(queryEmb, memEmb) : 0;
    return { ...row, _similarity: sim };
  });

  // Ordenar por similitud descendente
  scored.sort((a, b) => b._similarity - a._similarity);

  // Retornar top-K, limpiando campos internos y redondeando similitud
  return scored.slice(0, limit).map(({ _similarity, embedding: _emb, ...rest }) => ({
    ...rest,
    similarity: Math.round(_similarity * 10000) / 10000,
  }));
}

/**
 * Busca recuerdos filtrados por categoría exacta.
 *
 * @param {string} category — Categoría a filtrar.
 * @param {number} [limit=20] — Máximo de resultados.
 * @returns {Array<object>} Recuerdos de la categoría, ordenados por importancia descendente.
 */
function searchByCategory(category, limit = 20) {
  const database = ensureDb();
  const rows = database
    .prepare(
      `SELECT id, content, category, importance, created_at, decayed_at
       FROM memory
       WHERE category = ? AND archived_at IS NULL
       ORDER BY importance DESC, created_at DESC
       LIMIT ?`
    )
    .all(category, limit);

  return rows;
}

/**
 * Reduce la importancia de recuerdos antiguos aplicando un factor de decaimiento.
 * Solo afecta memorias activas (no archivadas) con importancia > 0.01.
 *
 * @param {number} [olderThanDays=30] — Antigüedad mínima en días para aplicar decaimiento.
 * @param {number} [decayFactor=0.5] — Factor multiplicador (0.0–1.0). 0.5 = reduce a la mitad.
 * @returns {number} Cantidad de memorias afectadas.
 */
function decayMemories(olderThanDays = 30, decayFactor = 0.5) {
  const database = ensureDb();
  const result = database
    .prepare(
      `UPDATE memory
       SET importance = importance * ?,
           decayed_at = datetime('now')
       WHERE created_at < datetime('now', ?)
         AND archived_at IS NULL
         AND importance > 0.01`
    )
    .run(decayFactor, `-${olderThanDays} days`);

  console.log(
    `[memory-store] Decaimiento aplicado: ${result.changes} memorias (factor=${decayFactor}, >${olderThanDays}d)`
  );
  return result.changes;
}

/**
 * Archiva recuerdos muy antiguos moviéndolos a la tabla memory_archive.
 * Las memorias archivadas no aparecen en búsquedas ni en getImportantMemories.
 *
 * @param {number} [olderThanDays=90] — Antigüedad mínima en días para archivar.
 * @returns {number} Cantidad de memorias archivadas.
 */
function archiveMemories(olderThanDays = 90) {
  const database = ensureDb();

  const count = database.transaction(() => {
    // Copiar a la tabla de archivo
    database
      .prepare(
        `INSERT INTO memory_archive (id, content, embedding, category, importance, created_at, decayed_at, archived_at)
         SELECT id, content, embedding, category, importance, created_at, decayed_at, datetime('now')
         FROM memory
         WHERE created_at < datetime('now', ?)
           AND archived_at IS NULL`
      )
      .run(`-${olderThanDays} days`);

    // Marcar como archivadas en la tabla principal
    const markResult = database
      .prepare(
        `UPDATE memory
         SET archived_at = datetime('now')
         WHERE created_at < datetime('now', ?)
           AND archived_at IS NULL`
      )
      .run(`-${olderThanDays} days`);

    return markResult.changes;
  })();

  console.log(`[memory-store] ${count} memorias archivadas (antigüedad >${olderThanDays}d)`);
  return count;
}

/**
 * Obtiene los recuerdos con mayor importancia (importance > 0.8).
 * Útil para alimentar el contexto del agente con información crítica del usuario.
 *
 * @returns {Array<object>} Recuerdos importantes, ordenados por importancia descendente.
 */
function getImportantMemories() {
  const database = ensureDb();
  const rows = database
    .prepare(
      `SELECT id, content, category, importance, created_at, decayed_at
       FROM memory
       WHERE importance > 0.8 AND archived_at IS NULL
       ORDER BY importance DESC`
    )
    .all();

  return rows;
}

// ═══════════════════════════════════════════════════════════
//  INICIALIZACIÓN PÚBLICA
// ═══════════════════════════════════════════════════════════

/**
 * Inicializa el MemoryStore.
 * Debe llamarse una vez al arrancar la aplicación (después de local-db.init()).
 *
 * No bloquea: el modelo ONNX se carga de forma lazy en la primera llamada a addMemory o searchSemantic.
 *
 * @returns {void}
 */
function init() {
  ensureDb();
  console.log('[memory-store] MemoryStore inicializado');
}

// ═══════════════════════════════════════════════════════════
//  EXPORTACIONES
// ═══════════════════════════════════════════════════════════

module.exports = {
  init,

  // CRUD semántico
  addMemory,
  searchSemantic,
  searchByCategory,

  // Mantenimiento
  decayMemories,
  archiveMemories,

  // Consultas
  getImportantMemories,
};
