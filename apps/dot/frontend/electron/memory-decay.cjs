// memory-decay.cjs — Algoritmo de olvido progresivo de memorias
//
// Implementa decay exponencial sobre la tabla `memory` de local-db.
// Se integra con job-scheduler.cjs para ejecutar el decay diario a las 3AM.
//
// Diseñado según BIBLIA.md §18 (Hexagonal+DDD): esta capa de infraestructura
// opera sobre la tabla `memory` usando únicamente las funciones exportadas
// por local-db y consultas directas cuando es necesario.
//
// Reglas de decay (según M4S3-A):
//   1. Memorias > 30 días:  importance *= 0.5  (decaimiento inicial)
//   2. Memorias > 60 días:  importance *= 0.3  (decaimiento acelerado)
//   3. Memorias > 90 días:  decayed_at = now()  (archivado)
//   4. Memorias con importance < 0.1: DELETE    (olvido total)
//   5. Memorias con importance >= 0.9: NUNCA decaen (importantes)

// ─── Referencia al módulo local-db (inyectado en init) ─────
/** @type {object | null} */
let _localDb = null;

// ─── Conexión a la DB (singleton obtenido vía localDb.init) ─
/** @type {import('better-sqlite3').Database | null} */
let _db = null;

// ─── Referencia al módulo job-scheduler (inyectado en init) ─
/** @type {object | null} */
let _jobScheduler = null;

// ═══════════════════════════════════════════════════════════
//  CONSTANTES
// ═══════════════════════════════════════════════════════════

/** Umbral de importancia: memorias con valor >= IMPORTANT_THRESHOLD nunca decaen */
const IMPORTANT_THRESHOLD = 0.9;

/** Umbral de olvido: memorias con importance < FORGET_THRESHOLD se eliminan */
const FORGET_THRESHOLD = 0.1;

/** Días para el primer nivel de decay (importance *= 0.5) */
const DECAY_30_DAYS = 30;

/** Días para el segundo nivel de decay (importance *= 0.3) */
const DECAY_60_DAYS = 60;

/** Días para archivado (decayed_at = now()) */
const ARCHIVE_90_DAYS = 90;

/** ID del job de decay en el scheduler */
const DECAY_JOB_ID = 'memory_decay_daily';

/** Expresión cron: 3AM todos los días */
const DECAY_CRON = '0 3 * * *';

// ═══════════════════════════════════════════════════════════
//  HELPERS INTERNOS
// ═══════════════════════════════════════════════════════════

/**
 * Asegura que la DB esté inicializada antes de cualquier operación.
 * @returns {import('better-sqlite3').Database}
 */
function _ensureDb() {
  if (!_db) {
    if (!_localDb) throw new Error('[memory-decay] localDb no inicializado. Llama a init() primero.');
    _db = _localDb.init();
  }
  return _db;
}

/**
 * Ejecuta una consulta SQL de solo lectura con parámetros.
 * @param {string} sql — Consulta SQL.
 * @param {...any} params — Parámetros para la consulta.
 * @returns {Array<object>} Filas resultantes.
 */
function _queryAll(sql, ...params) {
  try {
    return _ensureDb().prepare(sql).all(...params);
  } catch (err) {
    console.error('[memory-decay] Error en consulta SQL:', err.message);
    return [];
  }
}

/**
 * Ejecuta una consulta SQL que devuelve una sola fila.
 * @param {string} sql — Consulta SQL.
 * @param {...any} params — Parámetros para la consulta.
 * @returns {object | undefined} Fila resultante o undefined.
 */
function _queryOne(sql, ...params) {
  try {
    return _ensureDb().prepare(sql).get(...params);
  } catch (err) {
    console.error('[memory-decay] Error en consulta SQL:', err.message);
    return undefined;
  }
}

/**
 * Ejecuta una sentencia SQL de escritura (INSERT/UPDATE/DELETE).
 * @param {string} sql — Sentencia SQL.
 * @param {...any} params — Parámetros para la sentencia.
 * @returns {import('better-sqlite3').RunResult}
 */
function _execute(sql, ...params) {
  try {
    return _ensureDb().prepare(sql).run(...params);
  } catch (err) {
    console.error('[memory-decay] Error en escritura SQL:', err.message);
    return { changes: 0 };
  }
}

// ═══════════════════════════════════════════════════════════
//  ALGORITMO DE DECAY
// ═══════════════════════════════════════════════════════════

/**
 * Ejecuta el algoritmo de decay exponencial sobre todas las memorias.
 *
 * Lógica de decay:
 *   1. Memorias con importance >= 0.9 → NO decaen (se omiten).
 *   2. Memorias > 90 días → se marcan como decayed_at = now() (archivado).
 *   3. Memorias > 60 días → importance se multiplica por 0.3.
 *   4. Memorias > 30 días → importance se multiplica por 0.5.
 *   5. Memorias con importance < 0.1 → se eliminan permanentemente.
 *
 * Las reglas se aplican en orden jerárquico (la más restrictiva primero).
 *
 * @param {number} [olderThanDays] — Si se provee, solo afecta memorias
 *   más viejas que este número de días. Útil para testing con forceDecay().
 * @returns {object} Estadísticas de la ejecución.
 */
function _runDecayAlgorithm(olderThanDays) {
  if (!_db && !_localDb) {
    console.warn('[memory-decay] runDecay: módulo no inicializado.');
    return { decayed: 0, archived: 0, deleted: 0, skipped: 0, error: 'not_initialized' };
  }

  const db = _ensureDb();
  let decayed = 0;
  let archived = 0;
  let deleted = 0;
  let skipped = 0;

  try {
    // ── 1. Obtener todas las memorias activas (no decayed_at, no importance >= 0.9) ──
    const ageFilter = olderThanDays
      ? `AND created_at <= datetime('now', '-${olderThanDays} days')`
      : '';

    const memories = _queryAll(`
      SELECT id, importance, created_at,
        CAST(julianday('now') - julianday(created_at) AS INTEGER) AS age_days
      FROM memory
      WHERE decayed_at IS NULL
        AND importance < ?
        ${ageFilter}
    `, IMPORTANT_THRESHOLD);

    if (memories.length === 0) {
      console.log('[memory-decay] No hay memorias que procesar.');
      return { decayed: 0, archived: 0, deleted: 0, skipped: 0 };
    }

    // ── Procesar cada memoria en una transacción ──────────
    const processAll = db.transaction(() => {
      for (const mem of memories) {
        const age = mem.age_days;

        // Regla 3: > 90 días → archivar (marcar decayed_at)
        if (age > ARCHIVE_90_DAYS) {
          _execute(
            `UPDATE memory SET decayed_at = datetime('now') WHERE id = ?`,
            mem.id,
          );
          archived++;
          continue;
        }

        // Regla 2: > 60 días → decay acelerado (importance *= 0.3)
        if (age > DECAY_60_DAYS) {
          const newImportance = mem.importance * 0.3;
          if (newImportance < FORGET_THRESHOLD) {
            // Si después del decay queda < 0.1 → eliminar
            _execute('DELETE FROM memory WHERE id = ?', mem.id);
            deleted++;
          } else {
            _execute(
              'UPDATE memory SET importance = ? WHERE id = ?',
              newImportance,
              mem.id,
            );
            decayed++;
          }
          continue;
        }

        // Regla 1: > 30 días → decay inicial (importance *= 0.5)
        if (age > DECAY_30_DAYS) {
          const newImportance = mem.importance * 0.5;
          if (newImportance < FORGET_THRESHOLD) {
            // Si después del decay queda < 0.1 → eliminar
            _execute('DELETE FROM memory WHERE id = ?', mem.id);
            deleted++;
          } else {
            _execute(
              'UPDATE memory SET importance = ? WHERE id = ?',
              newImportance,
              mem.id,
            );
            decayed++;
          }
          continue;
        }

        // No cumple ningún criterio de edad → se omite
        skipped++;
      }
    });

    processAll();

    console.log(
      '[memory-decay] Decay completado —',
      `decayed=${decayed}, archived=${archived}, deleted=${deleted}, skipped=${skipped}`,
    );

    return { decayed, archived, deleted, skipped };
  } catch (err) {
    console.error('[memory-decay] Error durante el algoritmo de decay:', err.message);
    return { decayed, archived, deleted, skipped, error: err.message };
  }
}

// ═══════════════════════════════════════════════════════════
//  API PÚBLICA
// ═══════════════════════════════════════════════════════════

/**
 * Inicializa el módulo de decay de memoria.
 * Registra un job diario en el scheduler para ejecutar el decay a las 3AM.
 *
 * @param {object} localDbModule — Módulo local-db (requiere local-db.cjs).
 * @param {object} jobSchedulerModule — Módulo job-scheduler (requiere job-scheduler.cjs).
 */
function init(localDbModule, jobSchedulerModule) {
  if (_localDb) {
    console.warn('[memory-decay] Ya inicializado. Se omite segunda llamada.');
    return;
  }

  _localDb = localDbModule;
  _db = localDbModule.init();
  _jobScheduler = jobSchedulerModule;

  // Programar job diario de decay a las 3AM
  const added = _jobScheduler.addJob(
    DECAY_JOB_ID,
    'Decaimiento progresivo de memorias',
    DECAY_CRON,
    'memory-decay: ejecutar algoritmo de olvido progresivo',
  );

  if (added) {
    console.log('[memory-decay] Job diario de decay programado:', DECAY_CRON);
  } else {
    console.warn('[memory-decay] No se pudo programar el job de decay. ¿job-scheduler inicializado?');
  }
}

/**
 * Ejecuta el algoritmo de decay manualmente.
 * Equivalente a lo que ejecuta el job diario de las 3AM.
 *
 * @returns {object} Estadísticas: {decayed, archived, deleted, skipped}.
 */
function runDecay() {
  console.log('[memory-decay] Ejecutando decay manual...');
  return _runDecayAlgorithm();
}

/**
 * Marca una memoria como importante (importance = 1.0).
 * Las memorias importantes nunca decaen (importance >= 0.9).
 *
 * @param {string} id — ID de la memoria.
 * @returns {boolean} true si se actualizó correctamente.
 */
function markImportant(id) {
  try {
    const result = _execute(
      'UPDATE memory SET importance = 1.0 WHERE id = ?',
      id,
    );
    if (result.changes > 0) {
      console.log('[memory-decay] Memoria marcada como importante:', id);
      return true;
    }
    console.warn('[memory-decay] Memoria no encontrada:', id);
    return false;
  } catch (err) {
    console.error('[memory-decay] Error en markImportant:', err.message);
    return false;
  }
}

/**
 * Desmarca una memoria como importante, devolviéndola a importance = 0.5.
 * A partir de este momento, la memoria vuelve a estar sujeta al decay normal.
 *
 * @param {string} id — ID de la memoria.
 * @returns {boolean} true si se actualizó correctamente.
 */
function unmarkImportant(id) {
  try {
    const result = _execute(
      'UPDATE memory SET importance = 0.5 WHERE id = ?',
      id,
    );
    if (result.changes > 0) {
      console.log('[memory-decay] Memoria desmarcada como importante:', id);
      return true;
    }
    console.warn('[memory-decay] Memoria no encontrada:', id);
    return false;
  } catch (err) {
    console.error('[memory-decay] Error en unmarkImportant:', err.message);
    return false;
  }
}

/**
 * Obtiene estadísticas globales de las memorias.
 *
 * @returns {object} {total, active, archived, avgImportance, oldestDate}
 *   - total: número total de memorias en la tabla.
 *   - active: memorias sin decayed_at (no archivadas).
 *   - archived: memorias con decayed_at (archivadas).
 *   - avgImportance: importancia promedio de las memorias activas.
 *   - oldestDate: fecha de la memoria más antigua (activa).
 */
function getMemoryAgeStats() {
  try {
    const total = _queryOne('SELECT COUNT(*) AS cnt FROM memory');
    const active = _queryOne(
      'SELECT COUNT(*) AS cnt FROM memory WHERE decayed_at IS NULL',
    );
    const archived = _queryOne(
      'SELECT COUNT(*) AS cnt FROM memory WHERE decayed_at IS NOT NULL',
    );
    const avgRow = _queryOne(
      'SELECT AVG(importance) AS avg FROM memory WHERE decayed_at IS NULL',
    );
    const oldest = _queryOne(
      'SELECT created_at FROM memory WHERE decayed_at IS NULL ORDER BY created_at ASC LIMIT 1',
    );

    return {
      total: total ? total.cnt : 0,
      active: active ? active.cnt : 0,
      archived: archived ? archived.cnt : 0,
      avgImportance: avgRow && avgRow.avg !== null ? Math.round(avgRow.avg * 1000) / 1000 : 0,
      oldestDate: oldest ? oldest.created_at : null,
    };
  } catch (err) {
    console.error('[memory-decay] Error en getMemoryAgeStats:', err.message);
    return { total: 0, active: 0, archived: 0, avgImportance: 0, oldestDate: null };
  }
}

/**
 * Fuerza la ejecución del algoritmo de decay sobre memorias más viejas
 * que el número de días especificado. Útil para testing.
 *
 * Ejemplo: forceDecay(1) → aplica decay a todas las memorias con más de 1 día.
 *
 * @param {number} olderThanDays — Afecta solo memorias con antigüedad > N días.
 * @returns {object} Estadísticas: {decayed, archived, deleted, skipped}.
 */
function forceDecay(olderThanDays) {
  if (typeof olderThanDays !== 'number' || olderThanDays < 1) {
    console.warn('[memory-decay] forceDecay: olderThanDays debe ser un número >= 1. Se recibió:', olderThanDays);
    return { decayed: 0, archived: 0, deleted: 0, skipped: 0, error: 'invalid_days' };
  }

  console.log('[memory-decay] Ejecutando forceDecay para memorias >', olderThanDays, 'días...');
  return _runDecayAlgorithm(olderThanDays);
}

// ═══════════════════════════════════════════════════════════
//  CIERRE LIMPIO
// ═══════════════════════════════════════════════════════════

/**
 * Libera referencias internas. No cierra la DB (eso lo hace localDb.close()).
 * Debe llamarse durante el shutdown de la app.
 */
function stop() {
  _localDb = null;
  _db = null;
  _jobScheduler = null;
  console.log('[memory-decay] Módulo detenido.');
}

// ═══════════════════════════════════════════════════════════
//  EXPORTACIONES
// ═══════════════════════════════════════════════════════════

module.exports = {
  init,
  runDecay,
  markImportant,
  unmarkImportant,
  getMemoryAgeStats,
  forceDecay,
  stop,
};
