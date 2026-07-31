// parallel-agents.cjs — Sistema de sub-agentes paralelos para DOT
// M5S3-B: Permite lanzar múltiples agentes en paralelo para tareas independientes,
// controlar concurrencia vía semáforo y unificar resultados.
//
// Ejemplo:
//   const runner = new ParallelAgentRunner();
//   runner.init(factory, { maxConcurrent: 3, timeout: 30_000 });
//   const { results } = await runner.executeParallel([
//     { id: 'vuelos', instruction: 'Busca vuelos a Madrid la próxima semana' },
//     { id: 'hoteles', instruction: 'Busca hoteles céntricos en Madrid' },
//     { id: 'clima', instruction: 'Revisa el clima en Madrid para la próxima semana' },
//   ]);
//
//   // O con unificación automática:
//   const { mergedResponse } = await runner.executeWithMerge(tasks, 'Resume estas opciones de viaje');
//
// Diseñado según BIBLIA.md §18 (Hexagonal+DDD):
// capa de infraestructura, orquestación de agentes independientes.

const https = require('https');
const http = require('http');

// ═══════════════════════════════════════════════════════════
//  CLASE Semaphore
// ═══════════════════════════════════════════════════════════

/**
 * Semáforo simple para control de concurrencia.
 *
 * Permite limitar cuántas operaciones asíncronas se ejecutan simultáneamente.
 * Las tareas que exceden el límite se encolan y se despachan cuando se libera un slot.
 *
 * @example
 *   const sem = new Semaphore(3);
 *   await sem.acquire();
 *   // ... trabajo ...
 *   sem.release();
 */
class Semaphore {
  /**
   * Crea un semáforo con un máximo de operaciones concurrentes.
   *
   * @param {number} maxConcurrent - Número máximo de operaciones simultáneas permitidas.
   */
  constructor(maxConcurrent) {
    /** @type {number} */
    this._max = Math.max(1, maxConcurrent | 0);
    /** @type {number} */
    this._current = 0;
    /** @type {Array<function(): void>} */
    this._queue = [];
  }

  /**
   * Adquiere un slot del semáforo.
   *
   * Si hay slots disponibles, resuelve inmediatamente.
   * Si no, encola la promesa hasta que se libere un slot.
   *
   * @returns {Promise<void>}
   */
  acquire() {
    if (this._current < this._max) {
      this._current++;
      return Promise.resolve();
    }
    return new Promise((resolve) => {
      this._queue.push(resolve);
    });
  }

  /**
   * Libera un slot del semáforo.
   *
   * Si hay tareas en cola, despacha la siguiente inmediatamente.
   * Si no, decrementa el contador de slots ocupados.
   */
  release() {
    if (this._queue.length > 0) {
      const next = this._queue.shift();
      next();
    } else {
      this._current = Math.max(0, this._current - 1);
    }
  }
}

// ═══════════════════════════════════════════════════════════
//  createSubAgent
// ═══════════════════════════════════════════════════════════

/**
 * Crea y ejecuta un sub-agente independiente para una tarea específica.
 *
 * Cada llamada crea su propia instancia de AgentLoop vía la factory,
 * por lo que los sub-agentes no comparten estado entre sí.
 *
 * @param {function(object): object} agentLoopFactory - Función que recibe la task y retorna
 *   una instancia de AgentLoop configurada. Debe exponer el método `run(message, options)`.
 * @param {{id: string, instruction: string, tools?: object, context?: string}} task
 *   - id: identificador único de la tarea (se refleja en el resultado).
 *   - instruction: mensaje/instrucción que se pasa como userMessage al AgentLoop.
 *   - tools: (opcional) registry de herramientas específico para este sub-agente.
 *   - context: (opcional) historial o contexto previo para este sub-agente.
 * @param {number} [timeout=60000] - Tiempo máximo en ms para este sub-agente.
 *
 * @returns {Promise<{id: string, success: boolean, response: string, steps: number, durationMs: number, error?: string}>}
 *   Resultado estandarizado del sub-agente:
 *   - id: mismo id de la tarea de entrada.
 *   - success: true si el agente terminó sin errores.
 *   - response: texto de respuesta del agente (vacío si falló).
 *   - steps: número de pasos ejecutados (0 si falló sin ejecutar).
 *   - durationMs: duración total en milisegundos.
 *   - error: mensaje de error (solo si success=false).
 */
async function createSubAgent(agentLoopFactory, task, timeout = 60_000) {
  const start = Date.now();
  /** @type {object | null} */
  let agentLoop = null;

  try {
    // ── Crear AgentLoop independiente para esta tarea ──
    agentLoop = agentLoopFactory(task);

    // ── Construir opciones de ejecución ──
    const runOptions = {};
    if (task.context) {
      runOptions.history = task.context;
    }

    // ── Ejecutar con timeout opcional ──
    const runPromise = agentLoop.run(task.instruction, runOptions);

    /** @type {{response: string, steps: number}} */
    let result;
    if (timeout && timeout > 0) {
      const timeoutPromise = new Promise((_, reject) => {
        setTimeout(() => {
          reject(new Error(`Timeout: sub-agente "${task.id}" excedió ${timeout}ms`));
        }, timeout);
      });
      result = await Promise.race([runPromise, timeoutPromise]);
    } else {
      result = await runPromise;
    }

    const durationMs = Date.now() - start;

    return {
      id: task.id,
      success: true,
      response: result.response || '',
      steps: result.steps || 0,
      durationMs,
    };
  } catch (err) {
    // ── Limpiar agente si es necesario ──
    if (agentLoop && typeof agentLoop.cancel === 'function') {
      try { agentLoop.cancel(); } catch { /* ya cancelado */ }
    }

    const durationMs = Date.now() - start;

    return {
      id: task.id,
      success: false,
      response: '',
      steps: 0,
      error: err.message || String(err),
      durationMs,
    };
  }
}

// ═══════════════════════════════════════════════════════════
//  CLASE ParallelAgentRunner
// ═══════════════════════════════════════════════════════════

/**
 * Orquestador de sub-agentes paralelos.
 *
 * Permite ejecutar múltiples tareas de agente en paralelo con control
 * de concurrencia vía semáforo, timeout por tarea y unificación de resultados
 * vía un merge prompt enviado a DeepSeek.
 *
 * Cada sub-agente es completamente independiente: no comparten estado,
 * memoria ni contexto. La comunicación entre ellos solo ocurre durante
 * la fase de merge (executeWithMerge).
 *
 * @example
 *   const runner = new ParallelAgentRunner();
 *   runner.init((task) => createAgentLoop(deps, { tools: task.tools }), {
 *     maxConcurrent: 3,
 *     timeout: 30_000,
 *   });
 *
 *   // Paralelo simple
 *   const { results, totalDurationMs } = await runner.executeParallel([
 *     { id: 't1', instruction: 'Busca vuelos' },
 *     { id: 't2', instruction: 'Busca hoteles' },
 *   ]);
 *
 *   // Con unificación
 *   const { mergedResponse } = await runner.executeWithMerge(tasks, 'Resume para un viaje');
 */
class ParallelAgentRunner {
  /**
   * Inicializa el runner con una factory de agentes y opciones de concurrencia.
   *
   * @param {function(object): object} agentLoopFactory - Función que recibe una task
   *   y retorna una instancia de AgentLoop. Se llama una vez por cada sub-agente,
   *   garantizando independencia total entre ellos.
   * @param {object} [options]
   * @param {number} [options.maxConcurrent=5] - Máximo de sub-agentes ejecutándose simultáneamente.
   * @param {number} [options.timeout=60000] - Timeout en ms por sub-agente individual.
   * @param {string} [options.deepseekUrl] - URL del backend para chat completions
   *   (usado solo en executeWithMerge). Default: http://127.0.0.1:8000/v1/chat/completions
   * @param {string} [options.jwt] - Token JWT para autenticación (usado solo en executeWithMerge).
   */
  init(agentLoopFactory, options = {}) {
    /** @type {function(object): object} */
    this._agentLoopFactory = agentLoopFactory;

    /** @type {number} */
    this._maxConcurrent = options.maxConcurrent || 5;

    /** @type {number} */
    this._timeout = options.timeout || 60_000;

    /** @type {string} */
    this._deepseekUrl = options.deepseekUrl || 'http://127.0.0.1:8000/v1/chat/completions';

    /** @type {string} */
    this._jwt = options.jwt || '';
  }

  /**
   * Ejecuta múltiples tareas en paralelo con control de concurrencia.
   *
   * Cada tarea crea su propio AgentLoop independiente. Se usa Promise.allSettled()
   * para que el fallo de una tarea no afecte a las demás. El semáforo interno
   * limita cuántas tareas se ejecutan simultáneamente (maxConcurrent).
   *
   * @param {Array<{id: string, instruction: string, tools?: object, context?: string}>} tasks
   *   Lista de tareas a ejecutar. Cada tarea debe tener al menos id e instruction.
   *
   * @returns {Promise<{results: Array<{id: string, success: boolean, response: string, steps: number, durationMs: number, error?: string}>, totalDurationMs: number}>}
   *   - results: resultados de cada tarea en el mismo orden de entrada.
   *   - totalDurationMs: duración total de la ejecución paralela en ms.
   */
  async executeParallel(tasks) {
    if (!tasks || tasks.length === 0) {
      return { results: [], totalDurationMs: 0 };
    }

    const start = Date.now();
    const semaphore = new Semaphore(this._maxConcurrent);

    // ── Lanzar todas las tareas con semáforo ──────────
    const promises = tasks.map(async (task) => {
      await semaphore.acquire();
      try {
        return await createSubAgent(this._agentLoopFactory, task, this._timeout);
      } finally {
        semaphore.release();
      }
    });

    // ── Esperar todas con allSettled (fallos no bloquean) ──
    const settled = await Promise.allSettled(promises);

    // ── Normalizar resultados ──
    const results = settled.map((s) => {
      if (s.status === 'fulfilled') {
        return s.value;
      }
      // Normalizar rechazos inesperados (no deberían ocurrir porque createSubAgent atrapa errores)
      return {
        id: 'unknown',
        success: false,
        response: '',
        steps: 0,
        error: s.reason?.message || String(s.reason || 'Error desconocido'),
        durationMs: 0,
      };
    });

    return {
      results,
      totalDurationMs: Date.now() - start,
    };
  }

  /**
   * Ejecuta tareas de forma secuencial, una después de otra.
   *
   * Útil como fallback cuando las tareas tienen dependencias entre sí
   * o cuando se necesita preservar el orden estricto de ejecución.
   *
   * @param {Array<{id: string, instruction: string, tools?: object, context?: string}>} tasks
   *   Lista de tareas a ejecutar secuencialmente.
   *
   * @returns {Promise<{results: Array<{id: string, success: boolean, response: string, steps: number, durationMs: number, error?: string}>, totalDurationMs: number}>}
   *   Misma estructura que executeParallel.
   */
  async executeSequential(tasks) {
    if (!tasks || tasks.length === 0) {
      return { results: [], totalDurationMs: 0 };
    }

    const start = Date.now();
    const results = [];

    for (const task of tasks) {
      const result = await createSubAgent(this._agentLoopFactory, task, this._timeout);
      results.push(result);
    }

    return {
      results,
      totalDurationMs: Date.now() - start,
    };
  }

  /**
   * Ejecuta todas las tareas en paralelo y luego unifica los resultados
   * enviándolos a DeepSeek con un prompt de merge personalizado.
   *
   * Flujo:
   *   1. Ejecuta todas las tareas en paralelo (usa executeParallel internamente).
   *   2. Toma los resultados de cada sub-agente y los formatea.
   *   3. Envía los resultados + mergePrompt a DeepSeek vía el backend.
   *   4. Retorna la respuesta unificada junto con los resultados individuales.
   *
   * @param {Array<{id: string, instruction: string, tools?: object, context?: string}>} tasks
   *   Lista de tareas a ejecutar en paralelo.
   * @param {string} [mergePrompt] - Prompt para guiar la unificación de resultados.
   *   Default: "Unifica los siguientes resultados en una sola respuesta coherente
   *   y útil para el usuario, en español."
   *
   * @returns {Promise<{mergedResponse: string, subResults: Array, totalDurationMs: number}>}
   *   - mergedResponse: respuesta unificada generada por DeepSeek.
   *   - subResults: resultados individuales de cada sub-agente.
   *   - totalDurationMs: duración total de la operación en ms.
   */
  async executeWithMerge(tasks, mergePrompt) {
    if (!tasks || tasks.length === 0) {
      return {
        mergedResponse: 'No hay tareas para ejecutar.',
        subResults: [],
        totalDurationMs: 0,
      };
    }

    const start = Date.now();

    // ── 1. Ejecutar todas en paralelo ─────────────────
    const { results: subResults } = await this.executeParallel(tasks);

    // ── 2. Formatear resultados para el merge ─────────
    const resultsText = subResults.map((r) => {
      const statusIcon = r.success ? '✓' : '✗';
      const body = r.success ? r.response : (r.error || 'Sin respuesta');
      return `[${statusIcon}] Agente "${r.id}":\n${body}`;
    }).join('\n\n---\n\n');

    // ── 3. Enviar a DeepSeek para unificar ────────────
    const effectivePrompt = mergePrompt ||
      'Unifica los siguientes resultados en una sola respuesta coherente y útil para el usuario, en español.';

    let mergedResponse;
    try {
      mergedResponse = await this._callMerge(resultsText, effectivePrompt);
    } catch (err) {
      // Si falla el merge, devolver concatenación simple
      mergedResponse = subResults
        .filter((r) => r.success)
        .map((r) => `**${r.id}**: ${r.response}`)
        .join('\n\n');
    }

    return {
      mergedResponse,
      subResults,
      totalDurationMs: Date.now() - start,
    };
  }

  /**
   * Llama al backend (DeepSeek) para unificar resultados de sub-agentes.
   *
   * Realiza una petición HTTP POST no-streaming al endpoint de chat completions.
   * Usa la misma URL y JWT configurados en init().
   *
   * @param {string} resultsText - Texto formateado con los resultados de los sub-agentes.
   * @param {string} mergePrompt - Instrucción de unificación.
   * @returns {Promise<string>} Respuesta unificada generada por el modelo.
   * @private
   */
  _callMerge(resultsText, mergePrompt) {
    const messages = [
      {
        role: 'system',
        content: 'Eres DOT, un asistente IA de escritorio para Windows. Tu tarea es unificar resultados de múltiples sub-agentes en una respuesta clara, coherente y útil. Responde siempre en español.',
      },
      {
        role: 'user',
        content: `${mergePrompt}\n\nResultados de los sub-agentes:\n\n${resultsText}`,
      },
    ];

    return new Promise((resolve, reject) => {
      const url = new URL(this._deepseekUrl);
      const isHttps = url.protocol === 'https:';
      const transport = isHttps ? https : http;

      const body = JSON.stringify({
        model: 'deepseek-chat',
        messages,
        stream: false,
        temperature: 0.7,
        max_tokens: 4096,
      });

      const reqOptions = {
        hostname: url.hostname,
        port: url.port || (isHttps ? 443 : 80),
        path: url.pathname + url.search,
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Authorization': this._jwt ? `Bearer ${this._jwt}` : '',
          'Accept': 'application/json',
        },
      };

      const req = transport.request(reqOptions, (res) => {
        let data = '';
        res.on('data', (chunk) => { data += chunk; });
        res.on('end', () => {
          if (res.statusCode && res.statusCode >= 400) {
            reject(new Error(`Backend merge error ${res.statusCode}: ${data.slice(0, 300)}`));
            return;
          }
          try {
            const json = JSON.parse(data);
            const content = json.choices?.[0]?.message?.content || data;
            resolve(content);
          } catch {
            resolve(data);
          }
        });
      });

      req.on('error', (err) => {
        reject(new Error(`Error de red en merge: ${err.message}`));
      });

      req.setTimeout(30_000, () => {
        req.destroy();
        reject(new Error('Timeout en merge con DeepSeek'));
      });

      req.write(body);
      req.end();
    });
  }
}

// ═══════════════════════════════════════════════════════════
//  EXPORTACIONES
// ═══════════════════════════════════════════════════════════

module.exports = {
  Semaphore,
  ParallelAgentRunner,
  createSubAgent,
};
