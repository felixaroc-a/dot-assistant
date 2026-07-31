/**
 * Tool Factory — M3S1-A
 *
 * Escanea el directorio `tools/` buscando archivos `*.tool.json`.
 * Cada archivo define una tool con su especificación completa.
 *
 * Una integración nueva = 1 archivo JSON. Sin 300 líneas de Python por tool.
 *
 * Capacidades:
 *   - loadTools(): carga y parsea todos los *.tool.json
 *   - getToolSpec(name): obtiene la especificación de una tool por nombre
 *   - listTools(): lista todas las tools cargadas con metadata básica
 *   - Hot-reload: cambios en JSON se reflejan sin reiniciar (vía fs.watch)
 *
 * Formato JSON esperado:
 * {
 *   "name": "twitter_post",
 *   "description": "Publica un tweet en X/Twitter",
 *   "category": "social",
 *   "capability": "B",
 *   "parameters": {
 *     "text": { "type": "string", "required": true, "maxLength": 280 },
 *     "reply_to": { "type": "string", "required": false }
 *   },
 *   "handler": "twitter.post",
 *   "rateLimit": { "maxPerHour": 100, "maxPerDay": 1500 },
 *   "timeout": 15000
 * }
 */

const fs = require('fs');
const path = require('path');

// ──────────────────────────────────────────────
//  Constantes
// ──────────────────────────────────────────────

/** Directorio donde se buscan los archivos *.tool.json */
const TOOLS_DIR = path.join(__dirname, 'tools');

/** Extensión que identifica un archivo de tool */
const TOOL_EXT = '.tool.json';

// ──────────────────────────────────────────────
//  Estado interno
// ──────────────────────────────────────────────

/** Mapa name → spec completa (parseada del JSON) */
let _tools = Object.create(null);

/** Marca de tiempo de última carga para hot-reload */
let _lastLoad = 0;

/** Watcher de sistema de archivos para hot-reload */
let _watcher = null;

/** Logger — usa console si no se inyecta */
let _log = console;

// ──────────────────────────────────────────────
//  Helpers
// ──────────────────────────────────────────────

/**
 * Convierte los parámetros declarados en el JSON al formato
 * parameters_schema que espera el Agent Runtime (JSON Schema).
 *
 * @param {object} params - Objeto de parámetros del JSON
 * @returns {object} Esquema JSON Schema para el Agent Runtime
 */
function _buildParametersSchema(params) {
  const properties = {};
  const required = [];

  for (const [key, def] of Object.entries(params || {})) {
    properties[key] = {
      type: def.type || 'string',
      description: def.description || '',
    };
    if (def.maxLength) {
      properties[key].maxLength = def.maxLength;
    }
    if (def.minLength) {
      properties[key].minLength = def.minLength;
    }
    if (def.enum) {
      properties[key].enum = def.enum;
    }
    if (def.default !== undefined) {
      properties[key].default = def.default;
    }
    if (def.required !== false) {
      required.push(key);
    }
  }

  const schema = {
    type: 'object',
    properties,
  };
  if (required.length > 0) {
    schema.required = required;
  }
  return schema;
}

/**
 * Valida que un objeto JSON tenga los campos mínimos para ser una tool.
 *
 * @param {object} tool - Objeto parseado del JSON
 * @returns {{ valid: boolean, errors: string[] }}
 */
function _validateTool(tool) {
  const errors = [];
  if (!tool.name || typeof tool.name !== 'string') {
    errors.push('Falta "name" (string)');
  }
  if (!tool.description || typeof tool.description !== 'string') {
    errors.push('Falta "description" (string)');
  }
  if (!tool.handler || typeof tool.handler !== 'string') {
    errors.push('Falta "handler" (string)');
  }
  return { valid: errors.length === 0, errors };
}

// ──────────────────────────────────────────────
//  Core: carga de tools desde JSON
// ──────────────────────────────────────────────

/**
 * Escanea el directorio `tools/`, lee y parsea todos los archivos `*.tool.json`,
 * y los carga en memoria.
 *
 * @param {object} [opts] - Opciones
 * @param {boolean} [opts.force=false] - Forzar recarga aunque no haya cambios
 * @returns {{ count: number, tools: string[], errors: object[] }}
 */
function loadTools(opts) {
  const force = !!(opts && opts.force);
  const now = Date.now();

  // Hot-reload: solo recargar si hubo cambios o se fuerza
  if (!force && _lastLoad > 0 && (now - _lastLoad) < 5000) {
    return { count: Object.keys(_tools).length, tools: Object.keys(_tools), errors: [] };
  }

  const newTools = Object.create(null);
  const errors = [];
  let loaded = [];

  // Asegurar que el directorio existe
  if (!fs.existsSync(TOOLS_DIR)) {
    try {
      fs.mkdirSync(TOOLS_DIR, { recursive: true });
      _log.info('[tool-factory] Directorio tools/ creado en', TOOLS_DIR);
    } catch (e) {
      _log.warn('[tool-factory] No se pudo crear tools/:', e.message);
      _tools = newTools;
      _lastLoad = now;
      return { count: 0, tools: [], errors: [{ error: 'tools_dir_missing', message: e.message }] };
    }
  }

  // Escanear archivos *.tool.json
  let files;
  try {
    files = fs.readdirSync(TOOLS_DIR).filter(f => f.endsWith(TOOL_EXT));
  } catch (e) {
    _log.warn('[tool-factory] Error al leer tools/:', e.message);
    _tools = newTools;
    _lastLoad = now;
    return { count: 0, tools: [], errors: [{ error: 'read_dir_failed', message: e.message }] };
  }

  for (const file of files) {
    const filePath = path.join(TOOLS_DIR, file);
    try {
      const raw = fs.readFileSync(filePath, 'utf-8');
      const tool = JSON.parse(raw);

      const validation = _validateTool(tool);
      if (!validation.valid) {
        errors.push({
          file,
          error: 'validation_failed',
          details: validation.errors,
        });
        _log.warn('[tool-factory] Tool inválida en', file, ':', validation.errors.join(', '));
        continue;
      }

      // Construir spec completa para el Agent Runtime
      const spec = {
        name: tool.name,
        description: tool.description,
        category: tool.category || 'misc',
        capability: tool.capability || 'B',
        handler: tool.handler,
        rateLimit: tool.rateLimit || null,
        timeout: tool.timeout || 30000,
        parameters_schema: _buildParametersSchema(tool.parameters),
        // Campos extra que pueden ser útiles
        requiresBrowser: tool.requiresBrowser || false,
        requiresAuth: tool.requiresAuth || false,
        authProvider: tool.authProvider || null,
        tags: tool.tags || [],
        sourceFile: file,
      };

      newTools[tool.name] = spec;
      loaded.push(tool.name);
    } catch (e) {
      if (e instanceof SyntaxError) {
        errors.push({
          file,
          error: 'json_parse_failed',
          message: e.message,
        });
        _log.warn('[tool-factory] JSON inválido en', file, ':', e.message);
      } else {
        errors.push({
          file,
          error: 'read_failed',
          message: e.message,
        });
        _log.warn('[tool-factory] Error al leer', file, ':', e.message);
      }
    }
  }

  _tools = newTools;
  _lastLoad = now;

  _log.info(`[tool-factory] Cargadas ${loaded.length} tools desde ${TOOLS_DIR}${errors.length ? ` (${errors.length} errores)` : ''}`);
  return { count: loaded.length, tools: loaded, errors };
}

// ──────────────────────────────────────────────
//  API pública
// ──────────────────────────────────────────────

/**
 * Obtiene la especificación completa de una tool por su nombre.
 *
 * @param {string} name - Nombre de la tool (ej: "twitter_post")
 * @returns {object|null} Spec de la tool o null si no existe
 */
function getToolSpec(name) {
  // Hot-reload automático antes de consultar
  loadTools();
  return _tools[name] || null;
}

/**
 * Lista todas las tools cargadas con metadata resumida.
 *
 * @returns {Array<{name: string, description: string, category: string, handler: string}>}
 */
function listTools() {
  loadTools();
  return Object.values(_tools).map(t => ({
    name: t.name,
    description: t.description,
    category: t.category,
    handler: t.handler,
    capability: t.capability,
    requiresBrowser: t.requiresBrowser,
  }));
}

/**
 * Obtiene todas las TOOL_SPECS en formato compatible con el Agent Runtime.
 *
 * @returns {object} Mapa name → spec (solo campos relevantes para registry)
 */
function getToolSpecsForRegistry() {
  loadTools();
  const result = Object.create(null);
  for (const [name, spec] of Object.entries(_tools)) {
    result[name] = {
      description: spec.description,
      category: spec.category,
      capability: spec.capability,
      parameters_schema: spec.parameters_schema,
      handler: spec.handler,
    };
  }
  return result;
}

/**
 * Busca tools por categoría.
 *
 * @param {string} category - Categoría a filtrar
 * @returns {Array<object>} Tools que coinciden con la categoría
 */
function getToolsByCategory(category) {
  loadTools();
  return Object.values(_tools).filter(t => t.category === category);
}

// ──────────────────────────────────────────────
//  Hot-reload: fs.watch
// ──────────────────────────────────────────────

/**
 * Activa el watcher de sistema de archivos para hot-reload.
 * Los cambios en archivos *.tool.json se reflejan automáticamente.
 *
 * @param {object} [opts] - Opciones
 * @param {function} [opts.onChange] - Callback cuando se detecta un cambio
 */
function enableHotReload(opts) {
  if (_watcher) {
    _log.info('[tool-factory] Hot-reload ya activo');
    return;
  }

  // Asegurar que el directorio existe
  if (!fs.existsSync(TOOLS_DIR)) {
    try {
      fs.mkdirSync(TOOLS_DIR, { recursive: true });
    } catch (e) {
      _log.warn('[tool-factory] No se pudo crear tools/ para hot-reload:', e.message);
      return;
    }
  }

  const onChange = (opts && opts.onChange) || null;

  try {
    _watcher = fs.watch(TOOLS_DIR, { persistent: false }, (eventType, filename) => {
      if (!filename || !filename.endsWith(TOOL_EXT)) return;

      _log.info(`[tool-factory] Hot-reload detectado: ${eventType} en ${filename}`);

      // Pequeño debounce para evitar múltiples eventos del SO
      setTimeout(() => {
        const result = loadTools({ force: true });
        if (onChange) {
          onChange({
            event: eventType,
            file: filename,
            count: result.count,
            tools: result.tools,
            errors: result.errors,
          });
        }
      }, 300);
    });

    _watcher.on('error', (err) => {
      _log.warn('[tool-factory] Error en watcher:', err.message);
    });

    _log.info('[tool-factory] Hot-reload activado en', TOOLS_DIR);
  } catch (e) {
    _log.warn('[tool-factory] No se pudo activar hot-reload:', e.message);
  }
}

/**
 * Desactiva el watcher de hot-reload.
 */
function disableHotReload() {
  if (_watcher) {
    _watcher.close();
    _watcher = null;
    _log.info('[tool-factory] Hot-reload desactivado');
  }
}

/**
 * Configura un logger personalizado.
 *
 * @param {object} logger - Objeto con métodos info, warn, error
 */
function setLogger(logger) {
  if (logger && typeof logger.info === 'function') {
    _log = logger;
  }
}

// ──────────────────────────────────────────────
//  Carga inicial al requerir el módulo
// ──────────────────────────────────────────────

loadTools();

// ──────────────────────────────────────────────
//  Exportaciones
// ──────────────────────────────────────────────

module.exports = {
  loadTools,
  getToolSpec,
  listTools,
  getToolSpecsForRegistry,
  getToolsByCategory,
  enableHotReload,
  disableHotReload,
  setLogger,
  TOOLS_DIR,
};
