// agent-loop.cjs — Agent loop local en Electron
// Planifica → ejecuta tools → verifica → responde
//
// Diseñado según PLAN-DOT-2026-2027 M2S1-B: Agent loop MVP local.
// El loop envía mensajes a DeepSeek vía backend (POST /v1/chat/completions),
// ejecuta herramientas locales directamente y delega herramientas remotas al backend.
//
// Sin límite artificial de pasos (default 100, configurable).
// Soporta streaming vía onStream callback y cancelación vía cancel().

const https = require('https');
const http = require('http');

// ─── Constantes ──────────────────────────────────────────

const DEFAULT_MAX_STEPS = 100;
const DEFAULT_DEEPSEEK_URL = 'http://127.0.0.1:8000/v1/chat/completions';
const DEFAULT_MODEL = 'deepseek-chat';

/**
 * Obtiene el modelo por defecto desde la configuración o localStorage.
 * Prioridad: option del constructor > localStorage 'dot_preferred_model' > DEFAULT_MODEL.
 * @returns {string}
 */
function getDefaultModel() {
  try {
    if (typeof localStorage !== 'undefined') {
      const stored = localStorage.getItem('dot_preferred_model');
      if (stored && typeof stored === 'string' && stored.length > 0 && stored.length < 80) {
        return stored;
      }
    }
  } catch {
    // localStorage no disponible (ej. en tests)
  }
  return DEFAULT_MODEL;
}

// Herramientas que se ejecutan localmente en Electron (no en backend)
// Espejo de runtime.py — browser_* va al backend vía bridge CDP, no IPC directo.
const LOCAL_TOOL_PREFIXES = [
  'gmail_',
  'calendar_',
  'whatsapp_',
];

const LOCAL_TOOL_EXACT = new Set([
  'readFile',
  'writeFile',
  'listFiles',
  'deleteFile',
  'downloadUrl',
  'download_url_to_desktop',
  'searchFiles',
  'parseDocument',
]);

// ─── Plantillas de prompt ────────────────────────────────

const TOOLS_SYSTEM_HINT = [
  'Tienes acceso a las siguientes herramientas:',
  '',
  '{tools}',
  '',
  'Cuando necesites usar una herramienta, responde ÚNICAMENTE con un bloque JSON en este formato:',
  '```json',
  '{',
  '  "tool_calls": [',
  '    {"name": "nombre_herramienta", "arguments": {"param1": "valor1"}}',
  '  ]',
  '}',
  '```',
  '',
  'Si no necesitas herramientas, responde directamente al usuario en español claro y útil.',
  'NUNCA inventes resultados de herramientas. Solo responde con tool_calls cuando realmente necesites usar una herramienta.',
].join('\n');

const CONTINUE_AFTER_TOOLS = (
  'Continúa la misión hasta terminarla del todo. ' +
  'Si falta trabajo, emite más tool_calls. ' +
  'Si ya terminaste, escribe la respuesta FINAL completa y útil al usuario ' +
  '(hallazgos, rutas, resumen extendido). ' +
  'Prohibido cortar con "voy a…" o pedir que reintente.'
);

// ─── Helpers ─────────────────────────────────────────────

/**
 * Determina si una herramienta debe ejecutarse localmente en Electron.
 * Espejo de runtime.py:_is_local_tool().
 * @param {string} toolName - Nombre de la herramienta
 * @returns {boolean}
 */
function isLocalTool(toolName) {
  if (toolName.startsWith('browser_')) return false;
  if (LOCAL_TOOL_EXACT.has(toolName)) return true;
  return LOCAL_TOOL_PREFIXES.some(prefix => toolName.startsWith(prefix));
}

/**
 * Formatea una observación de herramienta para el modelo.
 * Espejo de runtime.py:format_observation().
 * @param {string} toolName - Nombre de la herramienta
 * @param {boolean} ok - Si la ejecución fue exitosa
 * @param {string} [output] - Salida de la herramienta
 * @param {string} [error] - Error si falló
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

/**
 * Parsea tool_calls del contenido de respuesta del modelo.
 * Soporta formato JSON en bloque de código y JSON crudo.
 * Espejo de runtime.py:parse_tool_calls().
 * @param {string} content - Contenido de la respuesta
 * @returns {Array<{name: string, arguments: object}>}
 */
function parseToolCalls(content) {
  if (!content) return [];

  // Buscar bloque JSON con tool_calls (```json ... ```)
  const jsonBlockMatch = content.match(/```json\s*([\s\S]*?)```/);
  let jsonStr = jsonBlockMatch ? jsonBlockMatch[1].trim() : content.trim();

  try {
    const parsed = JSON.parse(jsonStr);
    if (parsed && Array.isArray(parsed.tool_calls)) {
      return parsed.tool_calls.filter(tc => tc.name && typeof tc.name === 'string');
    }
  } catch {
    // Intentar parsear como array directo de tool_calls
    try {
      const parsed = JSON.parse(jsonStr);
      if (Array.isArray(parsed)) {
        return parsed.filter(tc => tc.name && typeof tc.name === 'string');
      }
    } catch {
      // No es JSON de tool_calls
    }
  }

  return [];
}

/**
 * Elimina el bloque JSON de tool_calls del contenido para mostrar solo el texto al usuario.
 * Espejo de runtime.py:strip_tool_calls_json().
 * @param {string} content - Contenido completo
 * @returns {string}
 */
function stripToolCallsJson(content) {
  return (content || '')
    .replace(/```json\s*[\s\S]*?```/g, '')
    .replace(/\{\s*"tool_calls"\s*:\s*\[[\s\S]*?\]\s*\}/g, '')
    .trim();
}

// ═══════════════════════════════════════════════════════════
//  CLASE AgentLoop
// ═══════════════════════════════════════════════════════════

class AgentLoop {
  /**
   * Crea una instancia del agent loop.
   *
   * @param {object} options
   * @param {number} [options.maxSteps=100] - Máximo de pasos del loop (sin límite artificial)
   * @param {string} [options.deepseekUrl] - URL del backend para chat completions
   * @param {string} [options.model] - Modelo IA a usar (default: deepseek-chat o de config)
   * @param {string} [options.jwt] - Token JWT para autenticación Bearer
   * @param {object} [options.tools] - Registry de herramientas: { nombre: {name, description, handler} }
   * @param {function} [options.onStep] - Callback por paso: ({step, tool, status, preview?}) => void
   * @param {function} [options.onStream] - Callback de streaming: (chunk: string) => void
   * @param {string} [options.systemPrompt] - System prompt base (se añade el hint de tools automáticamente)
   */
  constructor(options = {}) {
    this.maxSteps = options.maxSteps || DEFAULT_MAX_STEPS;
    this.deepseekUrl = options.deepseekUrl || DEFAULT_DEEPSEEK_URL;
    this.model = options.model || getDefaultModel();
    this.jwt = options.jwt || '';
    this.tools = options.tools || {};
    this.onStep = options.onStep || (() => {});
    this.onStream = options.onStream || (() => {});
    this.systemPrompt = options.systemPrompt ||
      'Eres DOT, un asistente IA de escritorio para Windows. Responde siempre en español claro y útil.';
    this.cancelled = false;
    /** @type {AbortController | null} */
    this._abortController = null;
    /** @type {{resolve: function, reject: function} | null} */
    this._pendingResolver = null;
  }

  /**
   * Detiene el loop en ejecución de forma segura.
   * Puede llamarse desde cualquier hilo/contexto.
   */
  cancel() {
    this.cancelled = true;
    if (this._abortController) {
      try {
        this._abortController.abort();
      } catch {
        // Ignorar errores de abort (ya cancelado)
      }
    }
    if (this._pendingResolver) {
      this._pendingResolver.reject(new Error('Cancelado por el usuario.'));
      this._pendingResolver = null;
    }
  }

  /**
   * Construye el system prompt con el hint de herramientas disponibles.
   * @returns {string}
   */
  _buildSystemPrompt() {
    const toolNames = Object.keys(this.tools);
    if (toolNames.length === 0) {
      return this.systemPrompt;
    }
    const toolsList = toolNames
      .map(name => {
        const desc = this.tools[name].description || '';
        return `- ${name}: ${desc}`;
      })
      .join('\n');
    return this.systemPrompt + '\n\n' + TOOLS_SYSTEM_HINT.replace('{tools}', toolsList);
  }

  /**
   * Realiza una petición HTTP al backend para chat completions con streaming SSE.
   *
   * El backend (FastAPI en puerto 8000) expone /v1/chat/completions compatible
   * con OpenAI. Las respuestas vienen como Server-Sent Events (SSE).
   *
   * @param {Array<{role: string, content: string}>} messages - Historial de mensajes
   * @returns {Promise<{content: string, usage: object | null, model: string | null}>}
   */
  async _callModel(messages) {
    return new Promise((resolve, reject) => {
      const url = new URL(this.deepseekUrl);
      const isHttps = url.protocol === 'https:';
      const transport = isHttps ? https : http;

      const body = JSON.stringify({
        model: this.model,
        preferred_model: this.model,
        messages,
        stream: true,
        temperature: 0.7,
        max_tokens: 4096,
      });

      this._abortController = new AbortController();
      this._pendingResolver = { resolve, reject };

      const options = {
        hostname: url.hostname,
        port: url.port || (isHttps ? 443 : 80),
        path: url.pathname + url.search,
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Authorization': `Bearer ${this.jwt}`,
          'Accept': 'text/event-stream',
        },
        signal: this._abortController.signal,
      };

      const req = transport.request(options, (res) => {
        if (res.statusCode && res.statusCode >= 400) {
          let errBody = '';
          res.on('data', (chunk) => { errBody += chunk; });
          res.on('end', () => {
            this._pendingResolver = null;
            reject(new Error(`Backend error ${res.statusCode}: ${errBody.slice(0, 300)}`));
          });
          return;
        }

        let fullContent = '';
        let usage = null;
        let model = null;
        let buffer = '';

        res.on('data', (chunk) => {
          if (this.cancelled) {
            try { req.destroy(); } catch { /* ya destruido */ }
            return;
          }

          const text = chunk.toString();
          buffer += text;

          // Procesar líneas SSE completas
          const lines = buffer.split('\n');
          buffer = lines.pop() || ''; // Última línea puede estar incompleta

          for (const line of lines) {
            const trimmed = line.trim();
            if (!trimmed || trimmed === 'data: [DONE]') continue;
            if (!trimmed.startsWith('data: ')) continue;

            try {
              const json = JSON.parse(trimmed.slice(6));
              const delta = json.choices?.[0]?.delta;
              if (delta?.content) {
                fullContent += delta.content;
                this.onStream(delta.content);
              }
              if (json.usage) usage = json.usage;
              if (json.model) model = json.model;
            } catch {
              // Ignorar líneas no parseables (keep-alive, comentarios, etc.)
            }
          }
        });

        res.on('end', () => {
          this._pendingResolver = null;

          // Procesar buffer restante
          if (buffer.trim()) {
            const trimmed = buffer.trim();
            if (trimmed.startsWith('data: ') && trimmed !== 'data: [DONE]') {
              try {
                const json = JSON.parse(trimmed.slice(6));
                const delta = json.choices?.[0]?.delta;
                if (delta?.content) {
                  fullContent += delta.content;
                  this.onStream(delta.content);
                }
                if (json.usage) usage = json.usage;
                if (json.model) model = json.model;
              } catch { /* ignorar */ }
            }
          }

          resolve({ content: fullContent, usage, model });
        });

        res.on('error', (err) => {
          this._pendingResolver = null;
          if (err.name === 'AbortError') {
            resolve({ content: '(Cancelado por el usuario.)', usage: null, model: null });
          } else {
            reject(err);
          }
        });
      });

      req.on('error', (err) => {
        this._pendingResolver = null;
        if (err.name === 'AbortError') {
          resolve({ content: '(Cancelado por el usuario.)', usage: null, model: null });
        } else {
          reject(err);
        }
      });

      req.write(body);
      req.end();
    });
  }

  /**
   * Ejecuta una herramienta (local o remota).
   *
   * - Herramientas locales (browser, archivos, WA, Gmail, Calendar):
   *   se ejecutan directamente llamando a tool.handler(args).
   * - Herramientas remotas (web_search, APIs externas):
   *   se delegan al backend vía POST /v1/tools/{nombre}.
   *
   * @param {string} toolName - Nombre de la herramienta
   * @param {object} args - Argumentos de la herramienta
   * @returns {Promise<{ok: boolean, output: string, error: string | null}>}
   */
  async _executeTool(toolName, args) {
    const tool = this.tools[toolName];
    if (!tool) {
      return { ok: false, output: '', error: `Herramienta desconocida: ${toolName}` };
    }

    if (isLocalTool(toolName)) {
      // ── Ejecución local en Electron ───────────────────
      try {
        const result = await tool.handler(args);
        return {
          ok: true,
          output: typeof result === 'string' ? result : JSON.stringify(result),
          error: null,
        };
      } catch (err) {
        return {
          ok: false,
          output: '',
          error: err.message || String(err),
        };
      }
    } else {
      // ── Delegación al backend ─────────────────────────
      return this._delegateToBackend(toolName, args);
    }
  }

  /**
   * Delega la ejecución de una herramienta remota al backend vía API REST.
   * Endpoint: POST /v1/tools/{toolName}
   *
   * @param {string} toolName - Nombre de la herramienta
   * @param {object} args - Argumentos
   * @returns {Promise<{ok: boolean, output: string, error: string | null}>}
   */
  async _delegateToBackend(toolName, args) {
    return new Promise((resolve) => {
      const url = new URL(this.deepseekUrl);
      const toolUrl = `${url.protocol}//${url.host}/v1/tools/${encodeURIComponent(toolName)}`;
      const parsedToolUrl = new URL(toolUrl);
      const isHttps = parsedToolUrl.protocol === 'https:';
      const transport = isHttps ? https : http;

      const body = JSON.stringify(args);

      const options = {
        hostname: parsedToolUrl.hostname,
        port: parsedToolUrl.port || (isHttps ? 443 : 80),
        path: parsedToolUrl.pathname,
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Authorization': `Bearer ${this.jwt}`,
        },
        timeout: 30000,
      };

      const req = transport.request(options, (res) => {
        let data = '';
        res.on('data', (chunk) => { data += chunk; });
        res.on('end', () => {
          try {
            const result = JSON.parse(data);
            resolve({
              ok: result.ok !== false,
              output: result.output || result.result || data,
              error: result.error || null,
            });
          } catch {
            resolve({ ok: true, output: data, error: null });
          }
        });
      });

      req.on('error', (err) => {
        resolve({ ok: false, output: '', error: `Error de red: ${err.message}` });
      });

      req.on('timeout', () => {
        req.destroy();
        resolve({ ok: false, output: '', error: 'Timeout al contactar el backend' });
      });

      req.write(body);
      req.end();
    });
  }

  /**
   * Ejecuta el loop completo para un mensaje del usuario.
   *
   * Flujo:
   *   1. Envía userMessage a DeepSeek vía backend
   *   2. Si DeepSeek responde con tool_calls → ejecuta cada tool
   *   3. Tools locales se ejecutan directo (browser, archivos, WA, code)
   *   4. Tools remotas se delegan al backend (web_search, APIs externas)
   *   5. Después de ejecutar tools, envía resultados a DeepSeek de nuevo
   *   6. Repite hasta que DeepSeek responda sin tool_calls O se alcance maxSteps
   *   7. Cada paso llama a this.onStep({step, tool, status})
   *   8. Streaming: llama a this.onStream(chunk) por cada fragmento
   *
   * @param {string} userMessage - Mensaje del usuario
   * @param {object} [options]
   * @param {string} [options.history] - Historial previo de la conversación
   * @returns {Promise<{response: string, steps: number, toolCalls: Array, usage: object | null, model: string | null}>}
   */
  async run(userMessage, options = {}) {
    if (!userMessage || !userMessage.trim()) {
      return { response: '', steps: 0, toolCalls: [], usage: null, model: null };
    }

    // Reiniciar estado de cancelación
    this.cancelled = false;
    this._abortController = null;
    this._pendingResolver = null;

    const sysPrompt = this._buildSystemPrompt();
    const history = options.history || '';

    let workingText = history
      ? `${history.trim()}\n\nNuevo mensaje del usuario:\n${userMessage.trim()}`
      : userMessage.trim();

    /** @type {Array<{step: number, tool: string, status: string, ok: boolean, ms: number}>} */
    const toolTrace = [];
    let lastUsage = null;
    let lastModel = null;
    const stepsCap = Math.max(1, this.maxSteps || DEFAULT_MAX_STEPS);

    // ── Bucle principal ──────────────────────────────────
    for (let step = 1; step <= stepsCap; step++) {
      // Verificar cancelación antes de cada paso
      if (this.cancelled) {
        return {
          response: 'Tarea cancelada por el usuario.',
          steps: step - 1,
          toolCalls: toolTrace,
          usage: lastUsage,
          model: lastModel,
        };
      }

      // Construir mensajes para el modelo
      const messages = [
        { role: 'system', content: sysPrompt },
        { role: 'user', content: workingText },
      ];

      // Notificar: pensando
      this.onStep({ step, tool: null, status: 'thinking' });
      console.log(`[agent-loop] Paso ${step}/${stepsCap} — consultando modelo…`);

      let content;
      try {
        const result = await this._callModel(messages);
        content = result.content || '';
        if (result.usage) lastUsage = result.usage;
        if (result.model) lastModel = result.model;
      } catch (err) {
        console.error(`[agent-loop] Error en paso ${step}:`, err.message);
        return {
          response: `Error al comunicarse con la IA: ${err.message}`,
          steps: step,
          toolCalls: toolTrace,
          usage: lastUsage,
          model: lastModel,
        };
      }

      // Verificar cancelación tras llamada al modelo
      if (this.cancelled) {
        return {
          response: 'Tarea cancelada por el usuario.',
          steps: step,
          toolCalls: toolTrace,
          usage: lastUsage,
          model: lastModel,
        };
      }

      const toolNames = Object.keys(this.tools);

      // ── Sin herramientas: devolver respuesta directa ────
      if (toolNames.length === 0) {
        const spoken = stripToolCallsJson(content) || content;
        console.log(`[agent-loop] Paso ${step} — sin herramientas, respuesta final.`);
        return {
          response: spoken,
          steps: step,
          toolCalls: toolTrace,
          usage: lastUsage,
          model: lastModel,
        };
      }

      // ── Parsear tool_calls de la respuesta ──────────────
      const calls = parseToolCalls(content);

      // Sin tool_calls: respuesta final del modelo
      if (calls.length === 0) {
        const spoken = stripToolCallsJson(content) || content;
        console.log(`[agent-loop] Paso ${step} — respuesta final (${spoken.length} chars).`);
        return {
          response: spoken,
          steps: step,
          toolCalls: toolTrace,
          usage: lastUsage,
          model: lastModel,
        };
      }

      console.log(`[agent-loop] Paso ${step} — ${calls.length} tool_calls detectados: ${calls.map(c => c.name).join(', ')}`);

      // ── Ejecutar herramientas ─────────────────────────
      /** @type {string[]} */
      const observations = [];

      for (const call of calls) {
        if (this.cancelled) break;

        const execType = isLocalTool(call.name) ? 'LOCAL' : 'REMOTO';
        console.log(`[agent-loop]   → ${call.name} [${execType}]`);

        this.onStep({ step, tool: call.name, status: 'executing' });

        const toolStartMs = Date.now();
        const result = await this._executeTool(call.name, call.arguments || {});
        const execMs = Date.now() - toolStartMs;

        const traceEntry = {
          step,
          tool: call.name,
          status: result.ok ? 'ok' : 'error',
          ok: result.ok,
          ms: execMs,
        };
        toolTrace.push(traceEntry);

        this.onStep({
          step,
          tool: call.name,
          status: result.ok ? 'ok' : 'error',
          preview: (result.output || result.error || '').slice(0, 200),
        });

        observations.push(
          formatObservation(call.name, result.ok, result.output, result.error)
        );

        if (!result.ok) {
          console.warn(`[agent-loop]   ✗ ${call.name} falló: ${result.error?.slice(0, 120)}`);
        }
      }

      if (this.cancelled) {
        return {
          response: 'Tarea cancelada por el usuario.',
          steps: step,
          toolCalls: toolTrace,
          usage: lastUsage,
          model: lastModel,
        };
      }

      // ── Preparar siguiente iteración ───────────────────
      const spoken = stripToolCallsJson(content);
      const obsBlock = observations.join('\n\n');
      workingText = [
        userMessage.trim(),
        '',
        `(Paso ${step} del agente)`,
        spoken ? `Respuesta parcial: ${spoken}` : '',
        '',
        'Resultados de herramientas:',
        obsBlock,
        '',
        CONTINUE_AFTER_TOOLS,
      ].filter(Boolean).join('\n');
    }

    // ── Límite de pasos alcanzado ────────────────────────
    console.warn(`[agent-loop] Límite de ${stepsCap} pasos alcanzado.`);
    return {
      response: 'Llegué al límite de pasos de esta tarea. Puedes pedirme que continúe desde donde quedé.',
      steps: stepsCap,
      toolCalls: toolTrace,
      usage: lastUsage,
      model: lastModel,
    };
  }
}

// ═══════════════════════════════════════════════════════════
//  FÁBRICA createAgentLoop
// ═══════════════════════════════════════════════════════════

/**
 * Crea una instancia de AgentLoop con el registry de herramientas construido
 * automáticamente a partir de las dependencias disponibles.
 *
 * Cada dependencia se inspecciona y sus métodos disponibles se registran como
 * herramientas con nombre, descripción y handler.
 *
 * @param {object} deps - Dependencias disponibles en Electron
 * @param {object} [deps.localDb] - Base de datos local (perfil, memoria, KV)
 * @param {object} [deps.browser] - Herramientas de automatización de navegador
 * @param {object} [deps.codeExecutor] - Ejecutor de código en sandbox
 * @param {object} [deps.transport] - Transporte de WhatsApp (sendMessage, getStatus, etc.)
 * @param {object} [deps.secureStorage] - Almacenamiento seguro (para cargar JWT)
 * @param {object} [deps.fileTools] - Herramientas de archivos (read, write, list, etc.)
 * @param {object} [deps.gmailTools] - Herramientas de Gmail (read, send, search, draft)
 * @param {object} [deps.calendarTools] - Herramientas de calendario (list, create, delete, findSlot)
 * @param {object} [deps.whatsAppTools] - Herramientas adicionales de WhatsApp
 * @param {object} [options] - Opciones adicionales para AgentLoop
 * @param {number} [options.maxSteps] - Máximo de pasos (default 100)
 * @param {string} [options.deepseekUrl] - URL del backend para chat completions
 * @param {string} [options.model] - Modelo IA preferido (default: de config o deepseek-chat)
 * @param {string} [options.jwt] - Token JWT (si no se provee, se carga de secureStorage)
 * @param {function} [options.onStep] - Callback por paso: ({step, tool, status, preview?}) => void
 * @param {function} [options.onStream] - Callback de streaming: (chunk: string) => void
 * @param {string} [options.systemPrompt] - System prompt personalizado
 * @returns {AgentLoop} Instancia configurada y lista para usar
 */
function createAgentLoop(deps = {}, options = {}) {
  /** @type {Object<string, {name: string, description: string, handler: function}>} */
  const tools = {};

  // ── Herramientas de archivos ──────────────────────────
  if (deps.fileTools) {
    const ft = deps.fileTools;
    if (ft.readFile) {
      tools['readFile'] = {
        name: 'readFile',
        description: 'Lee el contenido de un archivo del sistema de archivos local.',
        handler: async (args) => ft.readFile(args.path || args.relativePath || ''),
      };
    }
    if (ft.writeFile) {
      tools['writeFile'] = {
        name: 'writeFile',
        description: 'Escribe contenido en un archivo del sistema local.',
        handler: async (args) => ft.writeFile(args.path || args.relativePath || '', args.content || ''),
      };
    }
    if (ft.listFiles) {
      tools['listFiles'] = {
        name: 'listFiles',
        description: 'Lista archivos en un directorio del sistema local.',
        handler: async (args) => ft.listFiles(args.path || args.relativePath || ''),
      };
    }
    if (ft.deleteFile) {
      tools['deleteFile'] = {
        name: 'deleteFile',
        description: 'Elimina un archivo del sistema local.',
        handler: async (args) => ft.deleteFile(args.path || args.relativePath || ''),
      };
    }
    if (ft.downloadUrlToDesktop || ft.downloadUrl) {
      tools['download_url_to_desktop'] = {
        name: 'download_url_to_desktop',
        description: 'Descarga un archivo desde una URL al Escritorio del usuario.',
        handler: async (args) => {
          const fn = ft.downloadUrlToDesktop || ft.downloadUrl;
          return fn(args.url, args.path || '');
        },
      };
    }
    if (ft.searchFiles) {
      tools['searchFiles'] = {
        name: 'searchFiles',
        description: 'Busca archivos en el sistema local por nombre o contenido.',
        handler: async (args) => ft.searchFiles(args.query || '', args.searchRoot || undefined),
      };
    }
    if (ft.parseDocument) {
      tools['parseDocument'] = {
        name: 'parseDocument',
        description: 'Extrae texto de un documento (PDF, DOCX, etc.).',
        handler: async (args) => ft.parseDocument(args.filePath || '', args.mimeType || ''),
      };
    }
  }

  // ── Herramientas de navegador (CDP vía browser-automation.cjs) ──
  const localToolsMod = require('./local-tools.cjs');
  const browserMod = require('./browser-automation.cjs');

  function browserFail(raw, fallback) {
    const msg = (raw && (raw.message || raw.error)) || fallback;
    throw new Error(String(msg));
  }

  tools['browser_navigate'] = {
    name: 'browser_navigate',
    description: 'Entra a una URL http/https y abre la página para leerla.',
    handler: async (args) => {
      const raw = await browserMod.navigate({ url: String(args.url || '') }, localToolsMod);
      if (!raw.ok) browserFail(raw, 'No pude abrir esa página.');
      return `Navegué a ${raw.url}. Título: ${raw.title || 'N/A'}`;
    },
  };
  tools['browser_extract'] = {
    name: 'browser_extract',
    description: 'Lee el texto visible de la página web abierta.',
    handler: async (args) => {
      const raw = await browserMod.extract(
        { selector: String(args.selector || 'body') },
        localToolsMod,
      );
      if (!raw.ok) browserFail(raw, 'No pude leer la página.');
      const title = raw.title ? `Título: ${raw.title}\n` : '';
      return `${title}URL: ${raw.url}\n---\n${raw.text || ''}`;
    },
  };
  tools['browser_get_price'] = {
    name: 'browser_get_price',
    description: 'Extrae el precio de la página abierta (Amazon, MercadoLibre, etc.).',
    handler: async () => {
      const raw = await browserMod.extractPrice({}, localToolsMod);
      if (!raw.ok) browserFail(raw, 'No pude detectar el precio.');
      if (!raw.price) {
        return `No detecté un precio claro en ${raw.url}. Título: ${raw.title || 'N/A'}.`;
      }
      return `Precio: ${raw.price}\nTítulo: ${raw.title || 'N/A'}\nURL: ${raw.url}`;
    },
  };
  tools['browser_click'] = {
    name: 'browser_click',
    description: 'Hace clic en un elemento del navegador por selector CSS.',
    handler: async (args) => {
      const raw = await browserMod.click({ selector: String(args.selector || '') }, localToolsMod);
      if (!raw.ok) browserFail(raw, 'No pude hacer clic.');
      return `Click en ${args.selector} (url=${raw.url})`;
    },
  };
  tools['browser_type'] = {
    name: 'browser_type',
    description: 'Escribe texto en un campo del navegador.',
    handler: async (args) => {
      const raw = await browserMod.type(
        {
          selector: String(args.selector || ''),
          text: String(args.text || args.value || ''),
        },
        localToolsMod,
      );
      if (!raw.ok) browserFail(raw, 'No pude escribir en el campo.');
      return `Escribí en ${args.selector}`;
    },
  };
  tools['browser_screenshot'] = {
    name: 'browser_screenshot',
    description:
      'Toma una captura de la página web abierta y la guarda en el Escritorio (dot-captura-*.png).',
    handler: async (args) => {
      const raw = await browserMod.screenshot(
        {
          format: args.format || 'png',
          fullPage: args.full_page ?? args.fullPage ?? false,
          filepath: args.filepath || args.filename || args.path || '',
        },
        localToolsMod,
      );
      if (!raw.ok) browserFail(raw, 'No pude guardar la captura en el Escritorio.');
      return `Captura guardada en: ${raw.saved_to || raw.relative_path || '~/Desktop'}`;
    },
  };
  tools['browser_pdf'] = {
    name: 'browser_pdf',
    description:
      'Genera un PDF de la página web abierta y lo guarda en el Escritorio (dot-pdf-*.pdf).',
    handler: async (args) => {
      if (args.url) {
        const nav = await browserMod.navigate({ url: String(args.url) }, localToolsMod);
        if (!nav.ok) browserFail(nav, 'No pude abrir esa página.');
      }
      const raw = await browserMod.pdf(
        {
          filepath: args.filepath || args.filename || args.path || '',
          landscape: args.landscape === true,
        },
        localToolsMod,
      );
      if (!raw.ok) browserFail(raw, 'No pude guardar el PDF en el Escritorio.');
      return `PDF guardado en: ${raw.saved_to || raw.relative_path || '~/Desktop'}`;
    },
  };

  // ── Herramientas de Gmail ─────────────────────────────
  if (deps.gmailTools) {
    const gm = deps.gmailTools;
    if (gm.readInbox || gm.listEmails) {
      tools['gmail_read'] = {
        name: 'gmail_read',
        description: 'Lee correos recientes de Gmail.',
        handler: async (args) => {
          const fn = gm.readInbox || gm.listEmails;
          return fn(args.maxResults || 10, args.query || '');
        },
      };
    }
    if (gm.sendEmail) {
      tools['gmail_send'] = {
        name: 'gmail_send',
        description: 'Envía un correo electrónico vía Gmail.',
        handler: async (args) => gm.sendEmail(args.to || '', args.subject || '', args.body || ''),
      };
    }
    if (gm.searchEmails) {
      tools['gmail_search'] = {
        name: 'gmail_search',
        description: 'Busca correos en Gmail por criterios.',
        handler: async (args) => gm.searchEmails(args.query || '', args.maxResults || 20),
      };
    }
    if (gm.draftEmail) {
      tools['gmail_draft'] = {
        name: 'gmail_draft',
        description: 'Crea un borrador de correo en Gmail.',
        handler: async (args) => gm.draftEmail(args.to || '', args.subject || '', args.body || ''),
      };
    }
  }

  // ── Herramientas de Calendario ────────────────────────
  if (deps.calendarTools) {
    const cal = deps.calendarTools;
    if (cal.listEvents) {
      tools['calendar_list'] = {
        name: 'calendar_list',
        description: 'Lista eventos del calendario de Google.',
        handler: async (args) => cal.listEvents(
          args.timeMin || undefined,
          args.timeMax || undefined,
          args.maxResults || 20,
        ),
      };
    }
    if (cal.createEvent) {
      tools['calendar_create'] = {
        name: 'calendar_create',
        description: 'Crea un evento en Google Calendar.',
        handler: async (args) => cal.createEvent(
          args.summary || '',
          args.start || '',
          args.end || '',
          args.description || '',
        ),
      };
    }
    if (cal.deleteEvent) {
      tools['calendar_delete'] = {
        name: 'calendar_delete',
        description: 'Elimina un evento de Google Calendar.',
        handler: async (args) => cal.deleteEvent(args.eventId || ''),
      };
    }
    if (cal.findSlot) {
      tools['calendar_find_slot'] = {
        name: 'calendar_find_slot',
        description: 'Busca espacios libres en Google Calendar.',
        handler: async (args) => cal.findSlot(
          args.durationMinutes || 30,
          args.timeMin || undefined,
          args.timeMax || undefined,
        ),
      };
    }
  }

  // ── Herramientas de WhatsApp ──────────────────────────
  if (deps.whatsAppTools || deps.transport) {
    const wa = deps.whatsAppTools || deps.transport;
    if (wa.sendMessage) {
      tools['whatsapp_send'] = {
        name: 'whatsapp_send',
        description: 'Envía un mensaje de WhatsApp a un contacto o grupo.',
        handler: async (args) => wa.sendMessage(args.to || '', args.text || ''),
      };
    }
    if (wa.getStatus) {
      tools['whatsapp_status'] = {
        name: 'whatsapp_status',
        description: 'Obtiene el estado de conexión de WhatsApp.',
        handler: async () => wa.getStatus(),
      };
    }
    if (wa.getContacts) {
      tools['whatsapp_contacts'] = {
        name: 'whatsapp_contacts',
        description: 'Obtiene la lista de contactos de WhatsApp.',
        handler: async () => wa.getContacts(),
      };
    }
  }

  // ── Herramientas de ejecución de código ───────────────
  if (deps.codeExecutor) {
    const ce = deps.codeExecutor;
    if (ce.runPython) {
      tools['code_python'] = {
        name: 'code_python',
        description: 'Ejecuta código Python en un sandbox local.',
        handler: async (args) => ce.runPython(args.code || ''),
      };
    }
    if (ce.runJavaScript) {
      tools['code_javascript'] = {
        name: 'code_javascript',
        description: 'Ejecuta código JavaScript en un sandbox local.',
        handler: async (args) => ce.runJavaScript(args.code || ''),
      };
    }
    if (ce.runShell) {
      tools['code_shell'] = {
        name: 'code_shell',
        description: 'Ejecuta un comando de shell en un sandbox local.',
        handler: async (args) => ce.runShell(args.command || ''),
      };
    }
  }

  // ── Herramientas de base de datos local ───────────────
  if (deps.localDb) {
    const db = deps.localDb;
    if (db.getProfile) {
      tools['profile_get'] = {
        name: 'profile_get',
        description: 'Obtiene un valor del perfil local del usuario.',
        handler: async (args) => db.getProfile(args.key || ''),
      };
    }
    if (db.searchMemory) {
      tools['memory_search'] = {
        name: 'memory_search',
        description: 'Busca en la memoria local del usuario (recuerdos).',
        handler: async (args) => {
          const results = db.searchMemory(args.query || '', args.limit || 10);
          return JSON.stringify(results);
        },
      };
    }
    if (db.addMemory) {
      tools['memory_add'] = {
        name: 'memory_add',
        description: 'Agrega un recuerdo a la memoria local del usuario.',
        handler: async (args) => db.addMemory(
          args.content || '',
          args.category || null,
          args.importance || 0.5,
        ),
      };
    }
    if (db.kvGet && db.kvSet) {
      tools['kv_get'] = {
        name: 'kv_get',
        description: 'Obtiene un valor del almacén clave-valor local.',
        handler: async (args) => db.kvGet(args.key || '', args.namespace || 'default'),
      };
      tools['kv_set'] = {
        name: 'kv_set',
        description: 'Guarda un valor en el almacén clave-valor local.',
        handler: async (args) => {
          db.kvSet(args.key || '', args.value || '', args.namespace || 'default');
          return 'OK';
        },
      };
    }
    if (db.getAutomations) {
      tools['automations_list'] = {
        name: 'automations_list',
        description: 'Lista las automatizaciones del usuario.',
        handler: async () => {
          const autos = db.getAutomations();
          return JSON.stringify(autos);
        },
      };
    }
  }

  // ── Cargar JWT de secureStorage si no se proveyó ──────
  let jwt = options.jwt || '';
  if (!jwt && deps.secureStorage && typeof deps.secureStorage.loadSession === 'function') {
    try {
      const sessionStr = deps.secureStorage.loadSession();
      if (sessionStr) {
        const session = JSON.parse(sessionStr);
        jwt = session?.accessToken || session?.access_token || session?.token || '';
      }
    } catch {
      // secureStorage no disponible o sesión no cargada — se usará jwt vacío
      console.warn('[agent-loop] No se pudo cargar JWT de secureStorage.');
    }
  }

  return new AgentLoop({
    maxSteps: options.maxSteps,
    deepseekUrl: options.deepseekUrl,
    model: options.model,
    jwt,
    tools,
    onStep: options.onStep,
    onStream: options.onStream,
    systemPrompt: options.systemPrompt,
  });
}

// ═══════════════════════════════════════════════════════════
//  EXPORTACIONES
// ═══════════════════════════════════════════════════════════

module.exports = {
  AgentLoop,
  createAgentLoop,
  getDefaultModel,
};
