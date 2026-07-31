// summarizer.cjs — Resumen nocturno automático y compactación de conversaciones
//
// Implementa el pipeline de resumen diario (M4S2-B del PLAN-DOT-2026-2027):
//   1. nightlySummarize: busca conversaciones activas del día anterior,
//      genera resúmenes vía DeepSeek y los guarda en la memoria del usuario.
//   2. compactOldMessages: compacta mensajes antiguos (>7 días) reemplazándolos
//      con un resumen y liberando espacio en SQLite.
//
// Diseñado según BIBLIA.md §18 (Hexagonal+DDD): esta capa de aplicación
// coordina la lógica de resumen delegando en local-db.cjs y conversation-manager.cjs.
//
// Consumo IA: cada llamada a DeepSeek cuenta contra el límite unificado de $7.50/mes
// (ver BIBLIA.md §18.12 y AI_USAGE_LIMIT_ENABLED).

// ═══════════════════════════════════════════════════════════
//  SUMMARIZER
// ═══════════════════════════════════════════════════════════

class Summarizer {
  constructor() {
    /** @type {boolean} */
    this.initialized = false;

    /** @type {object | null} — Módulo local-db.cjs */
    this.localDb = null;

    /** @type {object | null} — Instancia de ConversationManager */
    this.convManager = null;

    /** @type {string | null} — URL base de la API de DeepSeek */
    this.deepseekUrl = null;

    /** @type {string | null} — JWT de autenticación para el backend */
    this.jwt = null;
  }

  // ─── Inicialización ──────────────────────────────────

  /**
   * Inicializa el summarizer con las dependencias necesarias.
   *
   * @param {object} localDb — Módulo local-db.cjs ya inicializado.
   * @param {object} convManager — Instancia de ConversationManager ya inicializada.
   * @param {string} deepseekUrl — URL base del endpoint DeepSeek en el backend.
   * @param {string} jwt — Token JWT vigente del usuario.
   */
  init(localDb, convManager, deepseekUrl, jwt) {
    this.localDb = localDb;
    this.convManager = convManager;
    this.deepseekUrl = deepseekUrl;
    this.jwt = jwt;
    this.initialized = true;

    console.log('[summarizer] Inicializado correctamente.');
  }

  /**
   * Lanza error si el módulo no fue inicializado.
   * @private
   */
  _assertReady() {
    if (!this.initialized) {
      throw new Error(
        '[summarizer] No inicializado. Llama a .init(localDb, convManager, deepseekUrl, jwt) primero.',
      );
    }
  }

  // ─── Helpers de fechas ───────────────────────────────

  /**
   * Calcula el rango de ayer (00:00:00 a 00:00:00 de hoy) en formato ISO local.
   * @returns {{ from: string, to: string }} Fechas ISO para filtrar conversaciones.
   */
  _yesterdayRange() {
    const now = new Date();

    // Hoy a las 00:00:00 (límite superior)
    const todayMidnight = new Date(
      now.getFullYear(),
      now.getMonth(),
      now.getDate(),
      0, 0, 0,
    );

    // Ayer a las 00:00:00 (límite inferior)
    const yesterdayMidnight = new Date(todayMidnight);
    yesterdayMidnight.setDate(yesterdayMidnight.getDate() - 1);

    // Formatear como ISO local (YYYY-MM-DDTHH:MM:SS) compatible con SQLite datetime()
    const pad = (n) => String(n).padStart(2, '0');
    const fmt = (d) =>
      `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`;

    return {
      from: fmt(yesterdayMidnight),
      to: fmt(todayMidnight),
    };
  }

  /**
   * Devuelve una fecha ISO de hace N días atrás desde ahora.
   * @param {number} days — Días hacia atrás.
   * @returns {string} Fecha en formato ISO local.
   */
  _daysAgoISO(days) {
    const d = new Date();
    d.setDate(d.getDate() - days);
    const pad = (n) => String(n).padStart(2, '0');
    return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`;
  }

  // ─── Llamada a DeepSeek ──────────────────────────────

  /**
   * Envía mensajes a DeepSeek para generar un resumen.
   * Usa fetch nativo de Node 18+ (disponible en Electron 28+).
   *
   * @param {Array<{role: string, content: string}>} messages — Mensajes a resumir.
   * @param {string} deepseekUrl — URL del endpoint.
   * @param {string} jwt — Token JWT.
   * @returns {Promise<string>} Texto del resumen.
   */
  async generateConversationSummary(messages, deepseekUrl, jwt) {
    if (!messages || messages.length === 0) {
      return '(Conversación sin mensajes)';
    }

    // Formatear mensajes para el prompt de resumen
    const transcript = messages
      .map((m) => `[${m.role}]: ${m.content}`)
      .join('\n');

    const prompt = [
      {
        role: 'system',
        content:
          'Eres un asistente que resume conversaciones. Resume en 2-3 frases en español. ' +
          'Incluye: decisiones clave tomadas, tareas pendientes y preferencias expresadas por el usuario. ' +
          'Sé conciso. No añadas introducción ni despedida.',
      },
      {
        role: 'user',
        content: `Resume esta conversación:\n\n${transcript}`,
      },
    ];

    try {
      const response = await fetch(deepseekUrl, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          Authorization: `Bearer ${jwt}`,
        },
        body: JSON.stringify({
          model: 'deepseek-chat',
          messages: prompt,
          max_tokens: 300,
          temperature: 0.3,
        }),
      });

      if (!response.ok) {
        const errText = await response.text().catch(() => '');
        throw new Error(
          `DeepSeek respondió con ${response.status}: ${errText.slice(0, 200)}`,
        );
      }

      const data = await response.json();
      const summary =
        data?.choices?.[0]?.message?.content || '(Sin respuesta del modelo)';

      return summary.trim();
    } catch (err) {
      console.error('[summarizer] Error al llamar a DeepSeek:', err.message);
      // Fallback: devolver primeras líneas como pseudo-resumen
      const fallback = messages
        .slice(0, 3)
        .map((m) => m.content.slice(0, 100))
        .join(' | ');
      return `[Error resumen: ${err.message.slice(0, 80)}] ${fallback}`;
    }
  }

  // ─── Resumen nocturno ────────────────────────────────

  /**
   * Ejecuta el resumen nocturno de todas las conversaciones activas del día anterior.
   *
   * Flujo:
   *   1. Busca conversaciones con updated_at entre ayer 00:00 y hoy 00:00.
   *   2. Para cada conversación, extrae sus mensajes.
   *   3. Envía a DeepSeek para generar un resumen en 2-3 frases.
   *   4. Guarda el resumen en la tabla memory (category='daily_summary', importance=0.7).
   *   5. Compacta mensajes con más de 7 días de antigüedad.
   *
   * @returns {Promise<{summarized: number, compacted: number, errors: string[]}>}
   *   Resultado de la operación.
   */
  async nightlySummarize() {
    this._assertReady();

    const result = { summarized: 0, compacted: 0, errors: [] };
    const { from, to } = this._yesterdayRange();

    console.log(
      `[summarizer] Iniciando resumen nocturno: rango ${from} → ${to}`,
    );

    // Paso 1: obtener conversaciones del día anterior
    const conversations = this.convManager.getConversationsInRange(from, to);

    if (conversations.length === 0) {
      console.log('[summarizer] No hay conversaciones para resumir hoy.');
      // Compactar de todas formas
      const compactResult = await this.compactOldMessages(this.localDb, 7);
      result.compacted = compactResult.compacted;
      return result;
    }

    console.log(
      `[summarizer] ${conversations.length} conversaciones encontradas para resumir.`,
    );

    // Paso 2-4: resumir cada conversación
    const todayISO = new Date().toISOString().slice(0, 10);

    for (const conv of conversations) {
      try {
        const messages = this.convManager.getMessages(conv.id, 200);

        if (messages.length === 0) continue;

        const summaryText = await this.generateConversationSummary(
          messages.map((m) => ({ role: m.role, content: m.content })),
          this.deepseekUrl,
          this.jwt,
        );

        // Guardar en memoria del usuario
        const memoryContent = [
          `[Resumen diario — ${todayISO}]`,
          `Conversación: "${conv.title || 'Sin título'}" (${conv.id})`,
          `Canal: ${conv.channel || 'desktop'}`,
          `Mensajes: ${messages.length}`,
          ``,
          summaryText,
        ].join('\n');

        this.localDb.addMemory(memoryContent, 'daily_summary', 0.7);
        result.summarized++;

        console.log(
          `[summarizer] Resumen guardado para conversación: ${conv.id}`,
        );
      } catch (err) {
        const msg = `Error resumiendo conversación ${conv.id}: ${err.message}`;
        console.error(`[summarizer] ${msg}`);
        result.errors.push(msg);
      }
    }

    // Paso 5: compactar mensajes viejos
    try {
      const compactResult = await this.compactOldMessages(this.localDb, 7);
      result.compacted = compactResult.compacted;
      if (compactResult.errors.length > 0) {
        result.errors.push(...compactResult.errors);
      }
    } catch (err) {
      const msg = `Error en compactación: ${err.message}`;
      console.error(`[summarizer] ${msg}`);
      result.errors.push(msg);
    }

    console.log(
      `[summarizer] Resumen nocturno completado: ${result.summarized} resúmenes, ${result.compacted} conversaciones compactadas, ${result.errors.length} errores.`,
    );

    return result;
  }

  // ─── Compactación de mensajes antiguos ───────────────

  /**
   * Compacta mensajes con más de N días de antigüedad en todas las conversaciones.
   *
   * Estrategia:
   *   1. Para cada conversación, identifica mensajes anteriores al umbral.
   *   2. Genera un resumen de esos mensajes vía DeepSeek.
   *   3. Inserta un mensaje 'system' con el resumen compactado.
   *   4. Elimina los mensajes originales de SQLite.
   *
   * @param {object} localDb — Módulo local-db.cjs.
   * @param {number} [olderThanDays=7] — Días de antigüedad para compactar.
   * @returns {Promise<{compacted: number, errors: string[]}>} Resultado.
   */
  async compactOldMessages(localDb, olderThanDays) {
    const days = olderThanDays || 7;
    const beforeISO = this._daysAgoISO(days);
    const result = { compacted: 0, errors: [] };

    console.log(
      `[summarizer] Compactando mensajes anteriores a: ${beforeISO} (${days} días)`,
    );

    // Obtener todas las conversaciones no archivadas
    const conversations = this.convManager.listConversations(9999);

    for (const conv of conversations) {
      try {
        const oldMessages = this.convManager.getMessagesBefore(
          conv.id,
          beforeISO,
        );

        // Solo compactar si hay al menos 5 mensajes antiguos (evitar compactar muy poco)
        if (oldMessages.length < 5) continue;

        // Generar resumen de los mensajes antiguos
        const summaryText = await this.generateConversationSummary(
          oldMessages.map((m) => ({ role: m.role, content: m.content })),
          this.deepseekUrl,
          this.jwt,
        );

        // Insertar mensaje de sistema con el resumen compactado
        const compactMsg = `[Historial compactado — ${oldMessages.length} mensajes anteriores al ${beforeISO.slice(0, 10)}]\n\n${summaryText}`;
        this.convManager.addMessage(conv.id, 'system', compactMsg, null);

        // Eliminar los mensajes originales
        const idsToDelete = oldMessages.map((m) => m.id);
        this.convManager.deleteMessages(idsToDelete);

        result.compacted++;
        console.log(
          `[summarizer] Compactados ${oldMessages.length} mensajes de conversación ${conv.id}`,
        );
      } catch (err) {
        const msg = `Error compactando conversación ${conv.id}: ${err.message}`;
        console.error(`[summarizer] ${msg}`);
        result.errors.push(msg);
      }
    }

    console.log(
      `[summarizer] Compactación finalizada: ${result.compacted} conversaciones compactadas.`,
    );

    return result;
  }

  // ─── Actualización de resumen parcial ────────────────

  /**
   * Actualiza un resumen existente con nuevos mensajes de una conversación.
   *
   * Útil cuando una conversación larga ya fue resumida parcialmente y
   * se quieren incorporar los mensajes nuevos sin re-procesar todo.
   *
   * @param {string} convId — ID de la conversación.
   * @param {Array<{role: string, content: string}>} newMessages — Nuevos mensajes a incorporar.
   * @returns {Promise<string>} Texto del resumen actualizado.
   */
  async updatePartialSummary(convId, newMessages) {
    this._assertReady();

    if (!newMessages || newMessages.length === 0) {
      return '(Sin mensajes nuevos para actualizar)';
    }

    // Buscar resumen previo en memoria
    const existingMemories = this.localDb.searchMemory(convId, 5);
    const prevSummary = existingMemories.find(
      (m) => m.category === 'daily_summary' && m.content.includes(convId),
    );

    const newTranscript = newMessages
      .map((m) => `[${m.role}]: ${m.content}`)
      .join('\n');

    const prompt = [
      {
        role: 'system',
        content:
          'Eres un asistente que actualiza resúmenes de conversaciones. ' +
          'Recibirás un resumen previo y nuevos mensajes. ' +
          'Produce un resumen actualizado en 2-3 frases en español que integre ambos. ' +
          'Incluye: decisiones clave, tareas pendientes y preferencias del usuario. ' +
          'Sé conciso. No añadas introducción ni despedida.',
      },
      {
        role: 'user',
        content:
          `Resumen previo:\n${prevSummary?.content || '(No hay resumen previo)'}\n\n` +
          `Nuevos mensajes:\n${newTranscript}\n\n` +
          'Genera el resumen actualizado:',
      },
    ];

    try {
      const response = await fetch(this.deepseekUrl, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          Authorization: `Bearer ${this.jwt}`,
        },
        body: JSON.stringify({
          model: 'deepseek-chat',
          messages: prompt,
          max_tokens: 300,
          temperature: 0.3,
        }),
      });

      if (!response.ok) {
        throw new Error(`DeepSeek respondió con ${response.status}`);
      }

      const data = await response.json();
      const summary =
        data?.choices?.[0]?.message?.content || '(Sin respuesta del modelo)';
      const trimmed = summary.trim();

      // Guardar el resumen actualizado en memoria
      const todayISO = new Date().toISOString().slice(0, 10);
      const conversation = this.convManager.getConversation(convId);

      const memoryContent = [
        `[Resumen actualizado — ${todayISO}]`,
        `Conversación: "${conversation?.title || 'Sin título'}" (${convId})`,
        `Canal: ${conversation?.channel || 'desktop'}`,
        ``,
        trimmed,
      ].join('\n');

      this.localDb.addMemory(memoryContent, 'daily_summary', 0.7);

      console.log(
        `[summarizer] Resumen parcial actualizado para conversación: ${convId}`,
      );

      return trimmed;
    } catch (err) {
      console.error(
        '[summarizer] Error en updatePartialSummary:',
        err.message,
      );
      return `[Error actualizando resumen: ${err.message.slice(0, 80)}]`;
    }
  }

  /**
   * Genera un resumen para una conversación específica (on-demand, no nocturno).
   * Útil para cuando el usuario pide explícitamente resumir una conversación.
   *
   * @param {string} convId — ID de la conversación.
   * @returns {Promise<string>} Texto del resumen.
   */
  async summarizeConversation(convId) {
    this._assertReady();

    const messages = this.convManager.getMessages(convId, 500);
    if (messages.length === 0) {
      return '(Conversación sin mensajes)';
    }

    const summary = await this.generateConversationSummary(
      messages.map((m) => ({ role: m.role, content: m.content })),
      this.deepseekUrl,
      this.jwt,
    );

    // Guardar en memoria
    const todayISO = new Date().toISOString().slice(0, 10);
    const conversation = this.convManager.getConversation(convId);

    const memoryContent = [
      `[Resumen bajo demanda — ${todayISO}]`,
      `Conversación: "${conversation?.title || 'Sin título'}" (${convId})`,
      `Canal: ${conversation?.channel || 'desktop'}`,
      `Mensajes: ${messages.length}`,
      ``,
      summary,
    ].join('\n');

    this.localDb.addMemory(memoryContent, 'daily_summary', 0.7);

    return summary;
  }
}

// ═══════════════════════════════════════════════════════════
//  EXPORTACIONES
// ═══════════════════════════════════════════════════════════

module.exports = { Summarizer };
