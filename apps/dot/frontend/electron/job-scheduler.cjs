// job-scheduler.cjs — Sistema de jobs persistente en SQLite con node-cron
//
// Corre en el main process de Electron. Los jobs sobreviven reinicios porque
// se persisten en la tabla `jobs` de local-db (SQLite). Usa node-cron para
// el scheduling y setInterval para el health check cada 30s.
//
// Diseñado según BIBLIA.md §18 (Hexagonal+DDD): esta capa de infraestructura
// solo habla con local-db y node-cron; el resto del sistema consulta a través
// de las funciones exportadas por este módulo.
//
// Schema de jobs (definido en local-db.cjs):
//   id TEXT PK, name TEXT, cron_expr TEXT, instruction TEXT,
//   last_run TEXT, next_run TEXT, status TEXT, error_log TEXT

const cron = require('node-cron');

// ─── Referencia al módulo local-db (inyectado en init) ─────
/** @type {object | null} */
let _localDb = null;

// ─── Conexión a la DB (singleton obtenido vía localDb.init) ─
/** @type {import('better-sqlite3').Database | null} */
let _db = null;

// ─── Tareas cron activas (id → ScheduledTask) ──────────────
/** @type {Map<string, import('node-cron').ScheduledTask>} */
const _tasks = new Map();

// ─── Estado de reintentos en memoria (id → {attempts, nextRetry}) ─
/** @type {Map<string, {attempts: number, nextRetry: number}>} */
const _retryState = new Map();

// ─── Intervalo del health check ─────────────────────────────
/** @type {ReturnType<typeof setInterval> | null} */
let _healthInterval = null;

// ═══════════════════════════════════════════════════════════
//  CONSTANTES
// ═══════════════════════════════════════════════════════════

/** Backoff exponencial en milisegundos: 1m, 2m, 4m, 8m, 16m */
const BACKOFF_DELAYS = [60_000, 120_000, 240_000, 480_000, 960_000];

/** Máximo de reintentos antes de abandonar */
const MAX_RETRIES = 5;

/** Intervalo del health check en milisegundos (30 segundos) */
const HEALTH_CHECK_INTERVAL_MS = 30_000;

/** Ventana de misfire: si last_run es anterior a esto, se considera misfire */
const MISFIRE_WINDOW_MS = 60_000; // 1 minuto de tolerancia

// ═══════════════════════════════════════════════════════════
//  HELPERS INTERNOS
// ═══════════════════════════════════════════════════════════

/**
 * Obtiene la instancia de la DB a través del singleton de local-db.
 * @returns {import('better-sqlite3').Database}
 */
function _ensureDb() {
  if (!_db) {
    if (!_localDb) throw new Error('[job-scheduler] localDb no inicializado. Llama a init() primero.');
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
    console.error('[job-scheduler] Error en consulta SQL:', err.message);
    return [];
  }
}

/**
 * Ejecuta una consulta SQL de solo lectura que devuelve una sola fila.
 * @param {string} sql — Consulta SQL.
 * @param {...any} params — Parámetros para la consulta.
 * @returns {object | undefined} Fila resultante o undefined.
 */
function _queryOne(sql, ...params) {
  try {
    return _ensureDb().prepare(sql).get(...params);
  } catch (err) {
    console.error('[job-scheduler] Error en consulta SQL:', err.message);
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
    console.error('[job-scheduler] Error en escritura SQL:', err.message);
    return { changes: 0 };
  }
}

/**
 * Actualiza el campo next_run de un job en SQLite.
 * Calcula la próxima ejecución sumando 1 minuto al now() actual como
 * estimación conservadora (node-cron maneja el scheduling exacto).
 * @param {string} jobId — ID del job.
 */
function _updateNextRun(jobId) {
  _execute(
    `UPDATE jobs SET next_run = datetime('now', '+1 minute') WHERE id = ?`,
    jobId,
  );
}

// ═══════════════════════════════════════════════════════════
//  EJECUCIÓN DE JOBS
// ═══════════════════════════════════════════════════════════

/**
 * Callback principal que se ejecuta cuando un job cron dispara.
 * Marca el job como 'running', ejecuta la instrucción, y guarda el resultado.
 * En caso de error, agenda reintentos con backoff exponencial.
 *
 * @param {object} job — Registro del job desde SQLite ({id, name, cron_expr, instruction, ...}).
 * @returns {Promise<void>}
 */
async function _executeJob(job) {
  const jobId = job.id;

  // Evitar ejecución duplicada si ya está corriendo
  const current = _queryOne('SELECT status FROM jobs WHERE id = ?', jobId);
  if (current && current.status === 'running') {
    console.warn('[job-scheduler] Job', jobId, 'ya está en ejecución. Se omite.');
    return;
  }

  _localDb.updateJobStatus(jobId, 'running', null);
  console.log('[job-scheduler] Ejecutando job:', jobId, `("${job.name}")`);

  try {
    // ── Ejecutar la instrucción ──────────────────────────
    // Por ahora, la ejecución es un placeholder. En fases posteriores,
    // aquí se invocará al executor de código o al agente IA para procesar
    // job.instruction.
    if (job.instruction) {
      // Placeholder: la instrucción se registra como ejecutada exitosamente.
      // En el futuro: codeExecutor.run(job.instruction) o similar.
      console.log('[job-scheduler] Instrucción ejecutada:', job.instruction.slice(0, 120));
    }

    // ── Marcar como completado ───────────────────────────
    _localDb.updateJobStatus(jobId, 'done', null);
    _updateNextRun(jobId);

    // Limpiar estado de reintentos
    _retryState.delete(jobId);

    console.log('[job-scheduler] Job completado:', jobId);
  } catch (err) {
    // ── Error: registrar y agendar reintento ─────────────
    const errorMsg = err.message || String(err);
    console.error('[job-scheduler] Job falló:', jobId, '-', errorMsg);

    _localDb.updateJobStatus(jobId, 'failed', errorMsg);
    _scheduleRetry(jobId);
  }
}

// ═══════════════════════════════════════════════════════════
//  REINTENTOS CON BACKOFF EXPONENCIAL
// ═══════════════════════════════════════════════════════════

/**
 * Agenda un reintento para un job fallido usando backoff exponencial.
 * Los delays son: 1m, 2m, 4m, 8m, 16m — máximo 5 intentos.
 * Si se alcanza el máximo, se abandona y el job queda en estado 'failed'.
 *
 * @param {string} jobId — ID del job a reintentar.
 */
function _scheduleRetry(jobId) {
  const state = _retryState.get(jobId) || { attempts: 0, nextRetry: 0 };

  if (state.attempts >= MAX_RETRIES) {
    console.error(
      '[job-scheduler] Job',
      jobId,
      `agotó los ${MAX_RETRIES} reintentos. Queda en estado "failed".`,
    );
    _retryState.delete(jobId);
    return;
  }

  const delay = BACKOFF_DELAYS[state.attempts] || BACKOFF_DELAYS[BACKOFF_DELAYS.length - 1];
  state.attempts += 1;
  state.nextRetry = Date.now() + delay;
  _retryState.set(jobId, state);

  console.log(
    '[job-scheduler] Reintento',
    state.attempts,
    'de',
    MAX_RETRIES,
    'para job',
    jobId,
    `en ${Math.round(delay / 1000)}s`,
  );
}

/**
 * Intenta reejecutar un job fallido si ya pasó su ventana de backoff.
 * Usado por el health check.
 *
 * @param {string} jobId — ID del job a reintentar.
 */
function _tryRetryJob(jobId) {
  const state = _retryState.get(jobId);
  if (!state) return;

  if (Date.now() < state.nextRetry) {
    // Aún no toca reintentar — el backoff sigue corriendo
    return;
  }

  const job = _queryOne('SELECT * FROM jobs WHERE id = ?', jobId);
  if (!job || job.status !== 'failed') {
    _retryState.delete(jobId);
    return;
  }

  console.log('[job-scheduler] Reintentando job:', jobId, `(intento ${state.attempts})`);
  _executeJob(job).catch((err) => {
    console.error('[job-scheduler] Error en reintento de job', jobId, ':', err.message);
  });
}

// ═══════════════════════════════════════════════════════════
//  PROGRAMACIÓN DE JOBS CON NODE-CRON
// ═══════════════════════════════════════════════════════════

/**
 * Crea y registra una tarea node-cron para un job.
 * Si ya existe una tarea para ese ID, la detiene antes de reemplazarla.
 *
 * @param {object} job — Registro del job desde SQLite.
 */
function _scheduleJob(job) {
  // Detener tarea existente si la hay
  const existing = _tasks.get(job.id);
  if (existing) {
    existing.stop();
    _tasks.delete(job.id);
  }

  try {
    const task = cron.schedule(job.cron_expr, () => {
      _executeJob(job).catch((err) => {
        console.error('[job-scheduler] Error no capturado en job', job.id, ':', err.message);
      });
    });

    _tasks.set(job.id, task);
    _updateNextRun(job.id);

    console.log('[job-scheduler] Job programado:', job.id, `("${job.name}") — ${job.cron_expr}`);
  } catch (err) {
    console.error(
      '[job-scheduler] Error al programar job',
      job.id,
      `(cron: "${job.cron_expr}"):`,
      err.message,
    );
    _localDb.updateJobStatus(job.id, 'failed', `Error de programación: ${err.message}`);
  }
}

// ═══════════════════════════════════════════════════════════
//  MISFIRE RECOVERY
// ═══════════════════════════════════════════════════════════

/**
 * Recupera jobs que debieron ejecutarse mientras Electron estaba cerrado.
 *
 * Lógica: si un job tiene status 'pending' y su last_run es NULL o
 * anterior a la ventana de misfire, se ejecuta inmediatamente.
 * Esto cubre el caso de reinicios del sistema o cierres de la app.
 */
function _recoverMisfires() {
  const now = Date.now();

  // Obtener todos los jobs (no solo pending) para evaluar misfire
  const allJobs = _queryAll('SELECT * FROM jobs');
  let recovered = 0;

  for (const job of allJobs) {
    // Solo recuperar jobs que no están ya corriendo o completados recientemente
    if (job.status === 'running' || job.status === 'done') continue;

    const lastRun = job.last_run ? new Date(job.last_run + 'Z').getTime() : 0;
    const nextRun = job.next_run ? new Date(job.next_run + 'Z').getTime() : 0;

    // Criterio de misfire: last_run es muy antiguo o next_run ya pasó
    const isMisfire =
      (lastRun === 0 && nextRun > 0 && nextRun < now - MISFIRE_WINDOW_MS) ||
      (lastRun > 0 && lastRun < now - MISFIRE_WINDOW_MS && nextRun > 0 && nextRun < now);

    if (isMisfire) {
      console.log('[job-scheduler] Misfire detectado para job:', job.id, `("${job.name}")`);
      _executeJob(job).catch((err) => {
        console.error('[job-scheduler] Error en misfire recovery de job', job.id, ':', err.message);
      });
      recovered++;
    }
  }

  if (recovered > 0) {
    console.log('[job-scheduler] Misfire recovery: se recuperaron', recovered, 'jobs');
  }
}

// ═══════════════════════════════════════════════════════════
//  API PÚBLICA
// ═══════════════════════════════════════════════════════════

/**
 * Inicializa el scheduler de jobs.
 * Carga todos los jobs pendientes desde SQLite, los programa con node-cron,
 * ejecuta misfire recovery y arranca el health check cada 30s.
 *
 * @param {object} localDbModule — Módulo local-db (requiere local-db.cjs).
 */
function init(localDbModule) {
  if (_localDb) {
    console.warn('[job-scheduler] Ya inicializado. Se omite segunda llamada.');
    return;
  }

  _localDb = localDbModule;
  _db = localDbModule.init(); // Obtener singleton de conexión

  // 1. Cargar y programar jobs pendientes desde SQLite
  const pendingJobs = _localDb.getPendingJobs();
  for (const job of pendingJobs) {
    _scheduleJob(job);
  }

  console.log('[job-scheduler] Inicializado con', pendingJobs.length, 'jobs pendientes.');

  // 2. Misfire recovery: ejecutar jobs que debieron correr mientras la app estaba cerrada
  _recoverMisfires();

  // 3. Health check cada 30s
  _healthInterval = setInterval(() => {
    healthCheck();
  }, HEALTH_CHECK_INTERVAL_MS);

  console.log('[job-scheduler] Health check activado cada', HEALTH_CHECK_INTERVAL_MS / 1000, 's.');
}

/**
 * Agrega un nuevo job programado.
 * Lo persiste en SQLite y arranca su tarea node-cron inmediatamente.
 *
 * @param {string} id — ID único del job.
 * @param {string} name — Nombre descriptivo.
 * @param {string} cronExpr — Expresión cron (ej. "*\/5 * * * *").
 * @param {string} [instruction] — Instrucción a ejecutar cuando el job dispare.
 * @returns {boolean} true si se agregó correctamente.
 */
function addJob(id, name, cronExpr, instruction) {
  if (!_localDb) {
    console.error('[job-scheduler] addJob: scheduler no inicializado.');
    return false;
  }

  // Validar expresión cron
  if (!cron.validate(cronExpr)) {
    console.error('[job-scheduler] addJob: expresión cron inválida:', cronExpr);
    return false;
  }

  // Persistir en SQLite
  _localDb.addJob(id, name, cronExpr, instruction || null);

  // Programar con node-cron
  const job = _queryOne('SELECT * FROM jobs WHERE id = ?', id);
  if (job) {
    _scheduleJob(job);
    console.log('[job-scheduler] Job agregado:', id, `("${name}")`);
    return true;
  }

  return false;
}

/**
 * Elimina un job programado.
 * Lo borra de SQLite y detiene su tarea node-cron.
 *
 * @param {string} id — ID del job a eliminar.
 * @returns {boolean} true si se eliminó correctamente.
 */
function removeJob(id) {
  if (!_localDb) {
    console.error('[job-scheduler] removeJob: scheduler no inicializado.');
    return false;
  }

  // Detener tarea cron
  const task = _tasks.get(id);
  if (task) {
    task.stop();
    _tasks.delete(id);
  }

  // Limpiar estado de reintentos
  _retryState.delete(id);

  // Eliminar de SQLite
  const result = _execute('DELETE FROM jobs WHERE id = ?', id);
  const deleted = result.changes > 0;

  if (deleted) {
    console.log('[job-scheduler] Job eliminado:', id);
  } else {
    console.warn('[job-scheduler] Job no encontrado para eliminar:', id);
  }

  return deleted;
}

/**
 * Lista todos los jobs almacenados en SQLite.
 *
 * @returns {Array<object>} Array de registros de jobs.
 */
function listJobs() {
  if (!_localDb) {
    console.error('[job-scheduler] listJobs: scheduler no inicializado.');
    return [];
  }
  return _queryAll('SELECT * FROM jobs ORDER BY created_at DESC');
}

/**
 * Obtiene el historial de ejecuciones de un job específico.
 * Devuelve el registro del job con last_run, status y error_log como historial.
 *
 * @param {string} id — ID del job.
 * @returns {object | null} Registro del job con datos de última ejecución, o null.
 */
function getJobHistory(id) {
  if (!_localDb) {
    console.error('[job-scheduler] getJobHistory: scheduler no inicializado.');
    return null;
  }

  const job = _queryOne('SELECT * FROM jobs WHERE id = ?', id);
  if (!job) {
    console.warn('[job-scheduler] Job no encontrado:', id);
    return null;
  }

  // Enriquecer con estado de reintentos en memoria
  const retry = _retryState.get(id);
  if (retry) {
    job._retryAttempts = retry.attempts;
    job._nextRetry = retry.nextRetry > 0 ? new Date(retry.nextRetry).toISOString() : null;
  } else {
    job._retryAttempts = 0;
    job._nextRetry = null;
  }

  return job;
}

/**
 * Detiene todos los cron tasks y el health check.
 * Debe llamarse durante el shutdown de la app (evento 'before-quit' de Electron).
 * No cierra la conexión a la DB (eso lo hace localDb.close()).
 */
function stop() {
  // 1. Detener health check
  if (_healthInterval) {
    clearInterval(_healthInterval);
    _healthInterval = null;
    console.log('[job-scheduler] Health check detenido.');
  }

  // 2. Detener todas las tareas cron
  for (const [id, task] of _tasks) {
    task.stop();
    console.log('[job-scheduler] Tarea detenida:', id);
  }
  _tasks.clear();

  // 3. Limpiar estado de reintentos
  _retryState.clear();

  // 4. Liberar referencias
  _localDb = null;
  _db = null;

  console.log('[job-scheduler] Scheduler detenido.');
}

/**
 * Health check: verifica el estado de todos los jobs.
 * - Reintenta jobs fallidos cuyo backoff ya expiró.
 * - Detecta jobs que no están programados pero deberían estarlo.
 * Se ejecuta automáticamente cada 30s vía setInterval.
 */
function healthCheck() {
  if (!_localDb || !_db) return;

  try {
    // 1. Reintentar jobs fallidos con backoff expirado
    const failedJobs = _queryAll("SELECT id FROM jobs WHERE status = 'failed'");
    for (const job of failedJobs) {
      _tryRetryJob(job.id);
    }

    // 2. Verificar que todos los jobs pending tengan tarea cron activa
    const pendingJobs = _localDb.getPendingJobs();
    for (const job of pendingJobs) {
      if (!_tasks.has(job.id)) {
        console.warn(
          '[job-scheduler] Health check: job pendiente sin tarea cron, reprogramando:',
          job.id,
        );
        _scheduleJob(job);
      }
    }

    // 3. Limpiar tareas huérfanas (en memoria pero no en DB)
    for (const [id] of _tasks) {
      const exists = _queryOne('SELECT id FROM jobs WHERE id = ?', id);
      if (!exists) {
        const task = _tasks.get(id);
        if (task) task.stop();
        _tasks.delete(id);
        console.log('[job-scheduler] Health check: tarea huérfana eliminada:', id);
      }
    }
  } catch (err) {
    console.error('[job-scheduler] Error en health check:', err.message);
  }
}

// ═══════════════════════════════════════════════════════════
//  EXPORTACIONES
// ═══════════════════════════════════════════════════════════

module.exports = {
  init,
  addJob,
  removeJob,
  listJobs,
  getJobHistory,
  stop,
  healthCheck,
};
