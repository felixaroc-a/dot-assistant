// conversation-manager.cjs — Gestor de historial de conversaciones para DOT
//
// Proporciona creación, búsqueda, archivado y consulta de conversaciones
// usando SQLite local como fuente de verdad.
//
// Diseñado según BIBLIA.md §18 (Hexagonal+DDD): esta capa de aplicación
// coordina las operaciones delegando en local-db.cjs (infraestructura).
//
// Schema: conversations(id, title, channel, created_at, updated_at, archived_at)
//         messages(id, conversation_id, role, content, tool_trace, created_at)

// ═══════════════════════════════════════════════════════════
//  CONVERSATION MANAGER
// ═══════════════════════════════════════════════════════════

class ConversationManager {
  constructor() {
    /** @type {boolean} */
    this.initialized = false;

    /** @type {import('better-sqlite3').Database | null} */
    this.db = null;

    /** @type {object | null} — Referencia al módulo local-db.cjs */
    this.localDb = null;

    /** @type {Map<string, import('better-sqlite3').Statement>} */
    this._stmts = new Map();
  }

  // ─── Inicialización ──────────────────────────────────

  /**
   * Inicializa el gestor de conversaciones vinculándolo a la base local.
   * Debe llamarse una sola vez durante el arranque del proceso principal.
   *
   * @param {object} localDb — Módulo local-db.cjs ya inicializado.
   */
  init(localDb) {
    if (this.initialized) return;

    this.localDb = localDb;
    this.db = localDb.init(); // Obtiene la instancia singleton de better-sqlite3
    this.initialized = true;

    console.log('[conversation-manager] Inicializado correctamente.');
  }

  /**
   * Obtiene (o prepara y cachea) una sentencia SQL.
   * @param {string} key — Clave única para la sentencia.
   * @param {string} sql — SQL a preparar.
   * @returns {import('better-sqlite3').Statement}
   */
  _prepare(key, sql) {
    if (!this._stmts.has(key)) {
      this._assertReady();
      this._stmts.set(key, this.db.prepare(sql));
    }
    return this._stmts.get(key);
  }

  /**
   * Lanza error si el módulo no fue inicializado.
   * @private
   */
  _assertReady() {
    if (!this.initialized || !this.db || !this.localDb) {
      throw new Error(
        '[conversation-manager] No inicializado. Llama a .init(localDb) primero.',
      );
    }
  }

  /**
   * Genera un ID único con prefijo + timestamp + fragmento aleatorio.
   * @param {string} prefix — Prefijo del ID (ej. 'conv', 'msg').
   * @returns {string} ID único.
   */
  _makeId(prefix) {
    const rand = Math.random().toString(36).slice(2, 9);
    return `${prefix}_${Date.now()}_${rand}`;
  }

  // ─── CRUD de conversaciones ──────────────────────────

  /**
   * Crea una nueva conversación y la persiste en SQLite.
   *
   * @param {string} title — Título descriptivo de la conversación.
   * @param {string} [channel='desktop'] — Canal de origen (desktop, whatsapp, etc.).
   * @returns {string} ID de la conversación creada.
   */
  createConversation(title, channel) {
    this._assertReady();
    const id = this._makeId('conv');
    this.localDb.saveConversation(id, title, channel || 'desktop');
    console.log(`[conversation-manager] Conversación creada: ${id} — "${title}"`);
    return id;
  }

  /**
   * Agrega un mensaje a una conversación existente.
   *
   * @param {string} convId — ID de la conversación padre.
   * @param {string} role — Rol del mensaje ('user', 'assistant', 'system', 'tool').
   * @param {string} content — Contenido del mensaje.
   * @param {string | null} [toolTrace] — Traza JSON de herramientas usadas (opcional).
   * @returns {string} ID del mensaje creado.
   */
  addMessage(convId, role, content, toolTrace) {
    this._assertReady();
    const id = this._makeId('msg');
    this.localDb.addMessage(id, convId, role, content, toolTrace || null);
    return id;
  }

  /**
   * Obtiene los mensajes de una conversación, ordenados cronológicamente.
   *
   * @param {string} convId — ID de la conversación.
   * @param {number} [limit=100] — Máximo de mensajes a devolver.
   * @returns {Array<object>} Array de mensajes.
   */
  getMessages(convId, limit) {
    this._assertReady();
    const maxResults = limit || 100;
    const messages = this.localDb.getConversationMessages(convId);
    // getConversationMessages ya ordena ASC; tomamos los últimos N
    return messages.slice(-maxResults);
  }

  /**
   * Busca conversaciones cuyo título o contenido de mensajes coincida con la consulta.
   * Búsqueda con LIKE (case-insensitive en SQLite por defecto para ASCII).
   *
   * @param {string} query — Texto a buscar.
   * @param {number} [limit=10] — Máximo de resultados.
   * @returns {Array<object>} Conversaciones que coinciden, con su último mensaje.
   */
  searchConversations(query, limit) {
    this._assertReady();
    const maxResults = limit || 10;
    const likePattern = `%${query}%`;

    try {
      const stmt = this._prepare(
        'search_conv',
        `SELECT c.*, m.content AS last_message_content, m.role AS last_message_role
         FROM conversations c
         LEFT JOIN (
           SELECT conversation_id, role, content,
                  ROW_NUMBER() OVER (PARTITION BY conversation_id ORDER BY created_at DESC) AS rn
           FROM messages
         ) m ON c.id = m.conversation_id AND m.rn = 1
         WHERE c.id IN (
           SELECT DISTINCT c2.id
           FROM conversations c2
           LEFT JOIN messages m2 ON c2.id = m2.conversation_id
           WHERE c2.title LIKE ? OR m2.content LIKE ?
         )
         ORDER BY c.updated_at DESC
         LIMIT ?`,
      );

      return stmt.all(likePattern, likePattern, maxResults);
    } catch (err) {
      console.error('[conversation-manager] searchConversations error:', err);
      return [];
    }
  }

  /**
   * Lista todas las conversaciones no archivadas, ordenadas por última actualización.
   *
   * @param {number} [limit=50] — Máximo de resultados.
   * @returns {Array<object>} Array de conversaciones.
   */
  listConversations(limit) {
    this._assertReady();
    const maxResults = limit || 50;

    try {
      const stmt = this._prepare(
        'list_conv',
        `SELECT * FROM conversations
         WHERE archived_at IS NULL
         ORDER BY updated_at DESC
         LIMIT ?`,
      );
      return stmt.all(maxResults);
    } catch (err) {
      console.error('[conversation-manager] listConversations error:', err);
      return [];
    }
  }

  /**
   * Archiva una conversación (soft-delete: marca archived_at).
   *
   * @param {string} id — ID de la conversación a archivar.
   * @returns {boolean} true si se actualizó al menos una fila.
   */
  archiveConversation(id) {
    this._assertReady();

    try {
      const stmt = this._prepare(
        'archive_conv',
        `UPDATE conversations SET archived_at = datetime('now') WHERE id = ? AND archived_at IS NULL`,
      );
      const result = stmt.run(id);
      if (result.changes > 0) {
        console.log(`[conversation-manager] Conversación archivada: ${id}`);
      }
      return result.changes > 0;
    } catch (err) {
      console.error('[conversation-manager] archiveConversation error:', err);
      return false;
    }
  }

  /**
   * Elimina definitivamente una conversación y todos sus mensajes.
   * Operación en transacción para garantizar atomicidad.
   *
   * @param {string} id — ID de la conversación a eliminar.
   * @returns {boolean} true si se eliminó correctamente.
   */
  deleteConversation(id) {
    this._assertReady();

    try {
      const deleteTransaction = this.db.transaction(() => {
        // Primero eliminar mensajes asociados
        this._prepare(
          'delete_conv_msgs',
          'DELETE FROM messages WHERE conversation_id = ?',
        ).run(id);

        // Luego eliminar la conversación
        const result = this._prepare(
          'delete_conv',
          'DELETE FROM conversations WHERE id = ?',
        ).run(id);

        return result.changes;
      });

      const deleted = deleteTransaction();
      if (deleted > 0) {
        console.log(`[conversation-manager] Conversación y mensajes eliminados: ${id}`);
      }
      return deleted > 0;
    } catch (err) {
      console.error('[conversation-manager] deleteConversation error:', err);
      return false;
    }
  }

  /**
   * Obtiene los últimos mensajes de una conversación formateados para contexto de LLM.
   * Devuelve un array [{role, content}] listo para inyectar en prompts.
   *
   * @param {string} convId — ID de la conversación.
   * @param {number} [maxTokens=4000] — Límite aproximado de tokens (4 chars ≈ 1 token).
   * @returns {Array<{role: string, content: string}>} Contexto recortado para el LLM.
   */
  getConversationContext(convId, maxTokens) {
    this._assertReady();
    const maxToks = maxTokens || 4000;
    const messages = this.localDb.getConversationMessages(convId);

    // Recorremos de atrás hacia adelante hasta alcanzar el límite de tokens
    const context = [];
    let charCount = 0;
    const maxChars = maxToks * 4; // Estimación: ~4 caracteres por token

    for (let i = messages.length - 1; i >= 0; i--) {
      const msg = messages[i];
      const text = msg.content || '';
      const role = msg.role || 'assistant';

      if (charCount + text.length > maxChars) {
        // Insertar marcador de truncamiento si aún quedan mensajes atrás
        if (i > 0) {
          context.unshift({
            role: 'system',
            content:
              '[Historial truncado por límite de tokens. Los mensajes más antiguos fueron omitidos.]',
          });
        }
        break;
      }

      context.unshift({ role, content: text });
      charCount += text.length;
    }

    return context;
  }

  /**
   * Obtiene una conversación por su ID.
   *
   * @param {string} id — ID de la conversación.
   * @returns {object | null} Objeto de conversación o null si no existe.
   */
  getConversation(id) {
    this._assertReady();

    try {
      const stmt = this._prepare(
        'get_conv',
        'SELECT * FROM conversations WHERE id = ?',
      );
      return stmt.get(id) || null;
    } catch (err) {
      console.error('[conversation-manager] getConversation error:', err);
      return null;
    }
  }

  /**
   * Obtiene las conversaciones actualizadas en un rango de fechas.
   * Útil para el resumen nocturno (conversaciones del día anterior).
   *
   * @param {string} fromISO — Fecha inicio en formato ISO (YYYY-MM-DDTHH:MM:SS).
   * @param {string} toISO — Fecha fin en formato ISO (YYYY-MM-DDTHH:MM:SS).
   * @returns {Array<object>} Conversaciones en el rango.
   */
  getConversationsInRange(fromISO, toISO) {
    this._assertReady();

    try {
      const stmt = this._prepare(
        'conv_range',
        `SELECT * FROM conversations
         WHERE updated_at >= ? AND updated_at < ?
           AND archived_at IS NULL
         ORDER BY updated_at DESC`,
      );
      return stmt.all(fromISO, toISO);
    } catch (err) {
      console.error('[conversation-manager] getConversationsInRange error:', err);
      return [];
    }
  }

  /**
   * Devuelve el conteo total de mensajes en una conversación.
   *
   * @param {string} convId — ID de la conversación.
   * @returns {number} Número de mensajes.
   */
  countMessages(convId) {
    this._assertReady();

    try {
      const stmt = this._prepare(
        'count_msgs',
        'SELECT COUNT(*) AS cnt FROM messages WHERE conversation_id = ?',
      );
      const row = stmt.get(convId);
      return row ? row.cnt : 0;
    } catch (err) {
      console.error('[conversation-manager] countMessages error:', err);
      return 0;
    }
  }

  /**
   * Elimina mensajes individuales por sus IDs. Usado en compactación.
   *
   * @param {string[]} messageIds — Array de IDs de mensajes a eliminar.
   * @returns {number} Cantidad de mensajes eliminados.
   */
  deleteMessages(messageIds) {
    this._assertReady();

    if (!messageIds || messageIds.length === 0) return 0;

    try {
      const placeholders = messageIds.map(() => '?').join(',');
      const stmt = this._prepare(
        'delete_msgs_batch',
        `DELETE FROM messages WHERE id IN (${placeholders})`,
      );
      const result = stmt.run(...messageIds);
      console.log(
        `[conversation-manager] ${result.changes} mensajes eliminados en batch.`,
      );
      return result.changes;
    } catch (err) {
      console.error('[conversation-manager] deleteMessages error:', err);
      return 0;
    }
  }

  /**
   * Obtiene todos los mensajes de una conversación creados antes de una fecha dada.
   * Usado para identificar mensajes a compactar.
   *
   * @param {string} convId — ID de la conversación.
   * @param {string} beforeISO — Fecha límite en formato ISO.
   * @returns {Array<object>} Mensajes anteriores a la fecha.
   */
  getMessagesBefore(convId, beforeISO) {
    this._assertReady();

    try {
      const stmt = this._prepare(
        'msgs_before',
        `SELECT * FROM messages
         WHERE conversation_id = ? AND created_at < ?
         ORDER BY created_at ASC`,
      );
      return stmt.all(convId, beforeISO);
    } catch (err) {
      console.error('[conversation-manager] getMessagesBefore error:', err);
      return [];
    }
  }
}

// ═══════════════════════════════════════════════════════════
//  EXPORTACIONES
// ═══════════════════════════════════════════════════════════

module.exports = { ConversationManager };
