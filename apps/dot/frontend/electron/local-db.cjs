// local-db.cjs — Base de datos SQLite local para DOT (M1S1-B)
// Almacena perfil, automatizaciones, tokens OAuth y KV genérico.
//
// Schema: kv_store | profile | automations | oauth_tokens
// DB path: userData/dot-local.db (Electron) o ./data/dot-local.db (fallback)

const path = require('path');
const fs = require('fs');

// ─── Resolución dinámica de Electron (app puede no estar disponible en tests) ───
let electronApp = null;
try {
  electronApp = require('electron').app;
} catch (_) {
  // Electron no disponible, se usará fallback
}

// ─── Carga de better-sqlite3 ───────────────────────────────
var Database = null;
try {
  Database = require('better-sqlite3');
} catch (e) {
  console.warn('[local-db] better-sqlite3 no disponible:', e.message);
  console.warn('[local-db] Ejecuta: npx @electron/rebuild -f -w better-sqlite3');
}

// ─── Singleton ─────────────────────────────────────────────
/** @type {import('better-sqlite3').Database | null} */
let db = null;

/** @type {Record<string, import('better-sqlite3').Statement>} */
const stmts = {};

// ═══════════════════════════════════════════════════════════
//  SCHEMA SQL (M1S1-B)
// ═══════════════════════════════════════════════════════════

const SCHEMA_SQL = [
  `CREATE TABLE IF NOT EXISTS kv_store (
    key TEXT PRIMARY KEY,
    value TEXT,
    updated_at TEXT
  )`,

  `CREATE TABLE IF NOT EXISTS profile (
    uid TEXT PRIMARY KEY,
    data TEXT,
    onboarding_completed INTEGER DEFAULT 0,
    briefing_skill_installed INTEGER DEFAULT 0,
    updated_at TEXT
  )`,

  `CREATE TABLE IF NOT EXISTS automations (
    id TEXT PRIMARY KEY,
    name TEXT,
    instruction TEXT,
    schedule TEXT DEFAULT 'manual',
    integration_id TEXT DEFAULT 'third-option',
    output_type TEXT DEFAULT 'notify',
    active INTEGER DEFAULT 1,
    source TEXT DEFAULT 'manual',
    created_at TEXT,
    updated_at TEXT
  )`,

  `CREATE TABLE IF NOT EXISTS oauth_tokens (
    provider TEXT PRIMARY KEY,
    access_token TEXT,
    refresh_token TEXT,
    expiry TEXT,
    encrypted INTEGER DEFAULT 1
  )`,
];

// ═══════════════════════════════════════════════════════════
//  RESOLUCIÓN DE RUTA
// ═══════════════════════════════════════════════════════════

/**
 * Resuelve la ruta de la base de datos.
 * Usa `app.getPath('userData')` si Electron está disponible,
 * o `./data/dot-local.db` como fallback.
 * @returns {string}
 */
function resolveDbPath(dbPath) {
  if (dbPath) return dbPath;

  if (electronApp && typeof electronApp.getPath === 'function') {
    try {
      return path.join(electronApp.getPath('userData'), 'dot-local.db');
    } catch (_) {
      // Si getPath falla, usar fallback
    }
  }

  // Fallback: crear directorio data/ si no existe
  const fallbackDir = path.join(__dirname, '..', 'data');
  if (!fs.existsSync(fallbackDir)) {
    fs.mkdirSync(fallbackDir, { recursive: true });
  }
  return path.join(fallbackDir, 'dot-local.db');
}

// ═══════════════════════════════════════════════════════════
//  HELPERS INTERNOS
// ═══════════════════════════════════════════════════════════

/**
 * Asegura que la DB esté inicializada.
 * @returns {import('better-sqlite3').Database | null}
 */
function ensureDb() {
  if (db) return db;
  return init();
}

/**
 * Obtiene o crea una sentencia preparada.
 * Si la DB no está disponible, retorna un mock inofensivo.
 * @param {string} key
 * @param {string} sql
 * @returns {object}
 */
function prepare(key, sql) {
  if (stmts[key]) return stmts[key];

  const d = ensureDb();
  if (!d) {
    const mock = {
      get: () => null,
      all: () => [],
      run: () => ({ changes: 0 }),
    };
    stmts[key] = mock;
    return mock;
  }

  stmts[key] = d.prepare(sql);
  return stmts[key];
}

// ═══════════════════════════════════════════════════════════
//  INICIALIZACIÓN
// ═══════════════════════════════════════════════════════════

/**
 * Inicializa la base de datos SQLite local.
 * Crea el archivo en la ruta resuelta, activa WAL y ejecuta el schema.
 *
 * @param {string} [dbPath] — Ruta opcional al archivo .db.
 *   Si no se provee, se resuelve automáticamente (userData o fallback).
 * @returns {import('better-sqlite3').Database | null} Instancia de la DB o null si falló.
 */
function init(dbPath) {
  if (db) return db;

  if (!Database) {
    console.error('[local-db] better-sqlite3 no disponible.');
    console.error('[local-db] Ejecuta: npm install better-sqlite3 && npx @electron/rebuild -f -w better-sqlite3');
    return null;
  }

  const resolvedPath = resolveDbPath(dbPath);

  try {
    db = new Database(resolvedPath);

    // WAL mode para mejor concurrencia y rendimiento de lectura
    db.pragma('journal_mode = WAL');
    db.pragma('foreign_keys = ON');

    // Ejecutar schema en una transacción
    const runSchema = db.transaction(() => {
      for (const sql of SCHEMA_SQL) {
        db.exec(sql);
      }
    });
    runSchema();

    console.log('[local-db] Base de datos inicializada:', resolvedPath);
    return db;
  } catch (err) {
    console.error('[local-db] Error al inicializar la base de datos:', err.message);
    console.error('[local-db] Verifica que better-sqlite3 esté compilado: npx @electron/rebuild -f -w better-sqlite3');
    db = null;
    return null;
  }
}

// ═══════════════════════════════════════════════════════════
//  KV STORE (genérico key-value)
// ═══════════════════════════════════════════════════════════

/**
 * Lee un valor del almacén clave-valor.
 * @param {string} key — Clave a leer.
 * @returns {string | null} Valor almacenado o null si no existe.
 */
function get(key) {
  try {
    const row = prepare('kv_get', 'SELECT value FROM kv_store WHERE key = ?').get(key);
    return row ? row.value : null;
  } catch (err) {
    console.error('[local-db] get error:', err);
    return null;
  }
}

/**
 * Escribe un valor en el almacén clave-valor (INSERT OR REPLACE).
 * @param {string} key — Clave.
 * @param {string} value — Valor a guardar.
 */
function set(key, value) {
  try {
    prepare('kv_set', `
      INSERT INTO kv_store (key, value, updated_at)
      VALUES (?, ?, datetime('now'))
      ON CONFLICT(key) DO UPDATE SET
        value = excluded.value,
        updated_at = datetime('now')
    `).run(key, value);
  } catch (err) {
    console.error('[local-db] set error:', err);
  }
}

// ═══════════════════════════════════════════════════════════
//  PROFILE
// ═══════════════════════════════════════════════════════════

/**
 * Lee el perfil del usuario.
 * @returns {object | null} Objeto con los campos del perfil o null si no existe.
 */
function getProfile() {
  try {
    const row = prepare('profile_get', 'SELECT * FROM profile LIMIT 1').get();
    if (!row) return null;
    return {
      uid: row.uid,
      data: row.data,
      onboarding_completed: row.onboarding_completed === 1,
      briefing_skill_installed: row.briefing_skill_installed === 1,
      updated_at: row.updated_at,
    };
  } catch (err) {
    console.error('[local-db] getProfile error:', err);
    return null;
  }
}

/**
 * Guarda o actualiza el perfil del usuario (INSERT OR REPLACE sobre uid).
 *
 * @param {object} data — Datos del perfil.
 * @param {string} data.uid — Identificador único del usuario (requerido).
 * @param {string} [data.data] — Datos adicionales del perfil (JSON string o texto).
 * @param {boolean} [data.onboarding_completed] — Si el onboarding fue completado.
 * @param {boolean} [data.briefing_skill_installed] — Si el skill de briefing fue instalado.
 */
function setProfile(data) {
  try {
    if (!data || !data.uid) {
      console.error('[local-db] setProfile: uid es requerido');
      return;
    }

    prepare('profile_upsert', `
      INSERT INTO profile (uid, data, onboarding_completed, briefing_skill_installed, updated_at)
      VALUES (?, ?, ?, ?, datetime('now'))
      ON CONFLICT(uid) DO UPDATE SET
        data = excluded.data,
        onboarding_completed = excluded.onboarding_completed,
        briefing_skill_installed = excluded.briefing_skill_installed,
        updated_at = datetime('now')
    `).run(
      data.uid,
      data.data !== undefined ? data.data : null,
      data.onboarding_completed !== undefined ? (data.onboarding_completed ? 1 : 0) : 0,
      data.briefing_skill_installed !== undefined ? (data.briefing_skill_installed ? 1 : 0) : 0,
    );
  } catch (err) {
    console.error('[local-db] setProfile error:', err);
  }
}

// ═══════════════════════════════════════════════════════════
//  AUTOMATIONS
// ═══════════════════════════════════════════════════════════

/**
 * Lista todas las automatizaciones activas (active = 1).
 * @returns {Array<object>} Array de objetos de automatización.
 */
function listAutomations() {
  try {
    return prepare('automations_list', `
      SELECT * FROM automations
      WHERE active = 1
      ORDER BY created_at DESC
    `).all();
  } catch (err) {
    console.error('[local-db] listAutomations error:', err);
    return [];
  }
}

/**
 * Guarda o actualiza una automatización (INSERT OR REPLACE).
 *
 * @param {object} auto — Objeto de automatización.
 * @param {string} auto.id — ID único de la automatización (requerido).
 * @param {string} [auto.name] — Nombre descriptivo.
 * @param {string} [auto.instruction] — Instrucción de la automatización.
 * @param {string} [auto.schedule='manual'] — Cronograma (ej. 'manual', 'daily', 'cron:...').
 * @param {string} [auto.integration_id='third-option'] — ID de la integración asociada.
 * @param {string} [auto.output_type='notify'] — Tipo de salida (ej. 'notify', 'email').
 * @param {boolean|number} [auto.active=1] — Si está activa.
 * @param {string} [auto.source='manual'] — Origen de la automatización.
 */
function saveAutomation(auto) {
  try {
    if (!auto || !auto.id) {
      console.error('[local-db] saveAutomation: id es requerido');
      return;
    }

    prepare('automation_upsert', `
      INSERT INTO automations (id, name, instruction, schedule, integration_id, output_type, active, source, created_at, updated_at)
      VALUES (?, ?, ?, ?, ?, ?, ?, ?, datetime('now'), datetime('now'))
      ON CONFLICT(id) DO UPDATE SET
        name = excluded.name,
        instruction = excluded.instruction,
        schedule = excluded.schedule,
        integration_id = excluded.integration_id,
        output_type = excluded.output_type,
        active = excluded.active,
        source = excluded.source,
        updated_at = datetime('now')
    `).run(
      auto.id,
      auto.name || null,
      auto.instruction || null,
      auto.schedule || 'manual',
      auto.integration_id || 'third-option',
      auto.output_type || 'notify',
      auto.active !== undefined ? (auto.active ? 1 : 0) : 1,
      auto.source || 'manual',
    );
  } catch (err) {
    console.error('[local-db] saveAutomation error:', err);
  }
}

/**
 * Elimina una automatización por su ID.
 * @param {string} id — ID de la automatización a eliminar.
 */
function deleteAutomation(id) {
  try {
    prepare('automation_delete', 'DELETE FROM automations WHERE id = ?').run(id);
  } catch (err) {
    console.error('[local-db] deleteAutomation error:', err);
  }
}

// ═══════════════════════════════════════════════════════════
//  OAUTH TOKENS
// ═══════════════════════════════════════════════════════════

/**
 * Lee el token OAuth de un proveedor.
 * @param {string} provider — Identificador del proveedor (ej. 'google').
 * @returns {object | null} Objeto con los datos del token o null si no existe.
 */
function getOAuthToken(provider) {
  try {
    const row = prepare('oauth_get', 'SELECT * FROM oauth_tokens WHERE provider = ?').get(provider);
    if (!row) return null;
    return {
      provider: row.provider,
      access_token: row.access_token,
      refresh_token: row.refresh_token,
      expiry: row.expiry,
      encrypted: row.encrypted === 1,
    };
  } catch (err) {
    console.error('[local-db] getOAuthToken error:', err);
    return null;
  }
}

/**
 * Guarda o actualiza un token OAuth para un proveedor (INSERT OR REPLACE).
 *
 * @param {string} provider — Identificador del proveedor (ej. 'google').
 * @param {object} tokenData — Datos del token.
 * @param {string} [tokenData.access_token] — Token de acceso.
 * @param {string} [tokenData.refresh_token] — Token de refresco.
 * @param {string} [tokenData.expiry] — Fecha de expiración.
 * @param {boolean|number} [tokenData.encrypted=1] — Si el token está cifrado.
 */
function setOAuthToken(provider, tokenData) {
  try {
    if (!provider) {
      console.error('[local-db] setOAuthToken: provider es requerido');
      return;
    }

    prepare('oauth_upsert', `
      INSERT INTO oauth_tokens (provider, access_token, refresh_token, expiry, encrypted)
      VALUES (?, ?, ?, ?, ?)
      ON CONFLICT(provider) DO UPDATE SET
        access_token = excluded.access_token,
        refresh_token = excluded.refresh_token,
        expiry = excluded.expiry,
        encrypted = excluded.encrypted
    `).run(
      provider,
      (tokenData && tokenData.access_token) || null,
      (tokenData && tokenData.refresh_token) || null,
      (tokenData && tokenData.expiry) || null,
      (tokenData && tokenData.encrypted !== undefined) ? (tokenData.encrypted ? 1 : 0) : 1,
    );
  } catch (err) {
    console.error('[local-db] setOAuthToken error:', err);
  }
}

// ═══════════════════════════════════════════════════════════
//  CIERRE LIMPIO
// ═══════════════════════════════════════════════════════════

/**
 * Cierra la conexión a la base de datos limpiamente.
 * Debe llamarse durante el shutdown de la app (evento 'before-quit' de Electron).
 */
function close() {
  if (db) {
    try {
      // Invalidar cache de statements preparados
      for (const key of Object.keys(stmts)) {
        delete stmts[key];
      }
      db.close();
      console.log('[local-db] Conexión cerrada limpiamente.');
    } catch (err) {
      console.error('[local-db] Error al cerrar la base de datos:', err);
    } finally {
      db = null;
    }
  }
}

// ═══════════════════════════════════════════════════════════
//  EXPORTACIONES (M1S1-B)
// ═══════════════════════════════════════════════════════════

module.exports = {
  init,
  get,
  set,
  getProfile,
  setProfile,
  listAutomations,
  saveAutomation,
  deleteAutomation,
  getOAuthToken,
  setOAuthToken,
  close,
};
