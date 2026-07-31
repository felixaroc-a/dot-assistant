// file-indexer.cjs — Indexación de archivos del usuario para búsqueda semántica
//
// DOT indexa los archivos del usuario (con permiso) para búsqueda semántica.
// El usuario puede preguntar "encuentra el PDF del contrato" y DOT busca en
// sus archivos indexados combinando búsqueda por nombre y similitud semántica
// vía embeddings ONNX locales.
//
// Diseñado según BIBLIA.md §18 (Hexagonal+DDD): esta capa de infraestructura
// solo habla con local-db (kv_store + memory) y embeddings; el resto del sistema
// consulta a través de las funciones exportadas por este módulo.
//
// Según PLAN-DOT-2026-2027 §M4S3-B — Indexación de archivos del usuario

    10|const fs = require('fs');
const path = require('path');
const crypto = require('crypto');
const os = require('os');

// ═══════════════════════════════════════════════════════════
//  CONSTANTES
// ═══════════════════════════════════════════════════════════

    20|/** Namespace en kv_store para metadatos de archivos indexados */
const KV_NAMESPACE = 'file_index';

/** Clave especial en kv_store que guarda la configuración (indexPaths, stats, lastScan) */
const KV_CONFIG_KEY = '__config__';

/** Clave especial que guarda la lista maestra de rutas indexadas */
const KV_KEYS_KEY = '__keys__';

    30|/** Máximo de archivos indexados (límite de seguridad) */
const MAX_INDEXED_FILES = 100000;

/** Tiempo máximo por directorio al escanear (milisegundos) */
const SCAN_TIMEOUT_MS = 30000;

/** Tamaño máximo de archivo a indexar en bytes (default 50 MB) */
const DEFAULT_MAX_FILE_SIZE = 50 * 1024 * 1024;

/** Caracteres máximos de contenido a extraer para embedding */
    40|const MAX_CONTENT_CHARS = 500;

/** Extensiones de archivo tratables como texto plano */
const TEXT_EXTENSIONS = new Set([
  '.txt', '.md',  '.csv', '.json', '.xml',  '.html', '.htm',
  '.css', '.js',  '.ts',  '.jsx',  '.tsx',  '.cjs',  '.mjs',
  '.py', '.rb',  '.go',  '.rs',   '.java', '.c',    '.cpp',
  '.h',  '.hpp', '.sh',  '.bat',  '.ps1',  '.yaml', '.yml',
  '.toml','.ini', '.cfg', '.log',  '.sql',  '.env',
    50|]);

/** Patrones de exclusión por defecto — no se indexan estas rutas */
const DEFAULT_EXCLUDE_PATTERNS = [
  'node_modules',
  '.git',
  '.svn',
  '.hg',
  'dist',
  'build',
  '.next',
  '.cache',
    60|  '__pycache__',
  '.venv',
  'venv',
  '.env',
  'AppData',
  'Application Data',
  'Microsoft',
  'Windows',
  'Program Files',
  'Program Files (x86)',
    70|  'ProgramData',
  '$Recycle.Bin',
  'System Volume Information',
  'Temp',
  'tmp',
  '.vscode',
];

/** Rutas del sistema Windows que NUNCA se indexan (bloqueo duro) */
const SYSTEM_FORBIDDEN_PREFIXES = [
  'C:\\Windows',
    80|  'C:\\Program Files',
  'C:\\Program Files (x86)',
  'C:\\ProgramData',
  'C:\\$Recycle.Bin',
];

/** Rutas por defecto a indexar (si options.indexPaths no se especifica) */
const DEFAULT_INDEX_PATHS = (() => {
  const home = os.homedir();
  const candidates = [
    90|    path.join(home, 'Desktop'),
    path.join(home, 'Documents'),
    path.join(home, 'Downloads'),
  ];
  return candidates.filter((p) => fs.existsSync(p));
})();

// ═══════════════════════════════════════════════════════════
//  CLASE PRINCIPAL
// ═══════════════════════════════════════════════════════════

   100|class FileIndexer {
  constructor() {
    /** @type {object | null} Módulo local-db inyectado */
    this._localDb = null;

    /** @type {object | null} Módulo embeddings inyectado */
    this._embeddings = null;

    /** @type {object | null} Módulo job-scheduler inyectado (opcional) */
    this._jobScheduler = null;
   110|
    /** @type {boolean} */
    this._initialized = false;

    /** @type {string[]} Rutas configuradas para indexar */
    this._indexPaths = [];

    /** @type {string[]} Patrones de exclusión activos */
    this._excludePatterns = [];

    /** @type {number} Tamaño máximo de archivo en bytes */
   120|    this._maxFileSize = DEFAULT_MAX_FILE_SIZE;

    /** @type {string | null} Expresión cron para re-indexado programado */
    this._schedule = null;

    /** @type {{ totalFiles: number, totalSize: number, lastScan: string | null }} */
    this._stats = {
      totalFiles: 0,
      totalSize: 0,
      lastScan: null,
    };
   130|
    /** @type {Map<string, object>} Caché en memoria de metadatos de archivos indexados */
    this._metadataCache = new Map();
  }

  // ═════════════════════════════════════════════════════════
  //  INICIALIZACIÓN
  // ═════════════════════════════════════════════════════════

  /**
   * Inicializa el indexador de archivos.
   * Carga la configuración desde kv_store, restaura la lista de rutas indexadas,
   140|   * y si está disponible, programa el job de re-indexado periódico.
   *
   * @param {object} localDb — Módulo local-db (requiere local-db.cjs).
   * @param {object} embeddings — Módulo embeddings (requiere embeddings.cjs).
   * @param {object} [jobScheduler] — Módulo job-scheduler (opcional).
   * @param {object} [options] — Opciones de configuración.
   * @param {string[]} [options.indexPaths] — Rutas a indexar. Default: Desktop, Documents, Downloads.
   * @param {string[]} [options.excludePatterns] — Patrones adicionales a excluir.
   * @param {number} [options.maxFileSizeMB] — Tamaño máximo de archivo en MB (default: 50).
   * @param {string} [options.schedule] — Expresión cron para re-indexado (default: cada 6 horas).
   150|   * @returns {boolean} true si se inicializó correctamente.
   */
  init(localDb, embeddings, jobScheduler, options = {}) {
    if (this._initialized) {
      console.warn('[file-indexer] Ya inicializado. Se omite segunda llamada.');
      return true;
    }

    if (!localDb) {
      console.error('[file-indexer] init: localDb es requerido.');
      return false;
   160|    }
    if (!embeddings) {
      console.error('[file-indexer] init: embeddings es requerido.');
      return false;
    }

    this._localDb = localDb;
    this._embeddings = embeddings;
    this._jobScheduler = jobScheduler || null;

    // ── Opciones ─────────────────────────────────────────
   170|    this._indexPaths = options.indexPaths || DEFAULT_INDEX_PATHS;
    this._excludePatterns = [
      ...DEFAULT_EXCLUDE_PATTERNS,
      ...(options.excludePatterns || []),
    ];
    this._maxFileSize = (options.maxFileSizeMB || 50) * 1024 * 1024;
    this._schedule = options.schedule || '0 */6 * * *'; // cada 6 horas

    // ── Restaurar configuración persistida (pisa defaults si existe) ──
    this._loadConfig();

   180|    // ── Restaurar caché de metadatos desde kv_store ─────────
    this._restoreMetadataCache();

    // ── Programar re-indexado periódico si job-scheduler está disponible ──
    if (this._jobScheduler && this._schedule) {
      this.scheduleReindex(this._schedule);
    }

    this._initialized = true;
    console.log(
      '[file-indexer] Inicializado con',
   190|      this._indexPaths.length, 'ruta(s) de índice,',
      this._stats.totalFiles, 'archivos indexados previamente.',
    );
    return true;
  }

  // ═════════════════════════════════════════════════════════
  //  ESCANEO DE DIRECTORIOS
  // ═════════════════════════════════════════════════════════

  /**
   * Escanea un directorio recursivamente, indexando cada archivo encontrado.
   200|   * Solo indexa rutas que estén dentro de la whitelist (indexPaths).
   * Respeta exclusiones, tamaño máximo, y límite de 100,000 archivos.
   *
   * @param {string} dirPath — Ruta del directorio a escanear.
   * @param {boolean} [recursive=true] — Si debe escanear subdirectorios recursivamente.
   * @returns {Promise<{ indexed: number, skipped: number, errors: number }>}
   */
  async scanDirectory(dirPath, recursive = true) {
    if (!this._initialized) {
      console.error('[file-indexer] scanDirectory: no inicializado.');
      return { indexed: 0, skipped: 0, errors: 0 };
   210|    }

    // Verificar que la ruta está en la whitelist
    if (!this._isAllowed(dirPath)) {
      console.warn('[file-indexer] scanDirectory: ruta no permitida:', dirPath);
      return { indexed: 0, skipped: 0, errors: 0 };
    }

    let indexed = 0;
    let skipped = 0;
    let errors = 0;
   220|
    const startTime = Date.now();

    try {
      const entries = await this._readdirWithTimeout(dirPath);
      if (!entries) {
        console.warn('[file-indexer] No se pudo leer el directorio:', dirPath);
        return { indexed, skipped, errors: 1 };
      }

      for (const entry of entries) {
        // ── Verificar límite de archivos ─────────────────
   230|        if (this._stats.totalFiles >= MAX_INDEXED_FILES) {
          console.warn(
            '[file-indexer] Límite de',
            MAX_INDEXED_FILES,
            'archivos alcanzado. Se detiene el escaneo.',
          );
          break;
        }

        // ── Timeout por directorio ───────────────────────
        if (Date.now() - startTime > SCAN_TIMEOUT_MS) {
   240|          console.warn('[file-indexer] Timeout de escaneo alcanzado en:', dirPath);
          skipped++;
          break;
        }

        const fullPath = path.join(dirPath, entry.name);

        try {
          const stat = fs.statSync(fullPath);

          // ── Directorios: recursión ─────────────────────
   250|          if (stat.isDirectory() && recursive) {
            if (this._isExcluded(fullPath)) {
              skipped++;
              continue;
            }

            // Indexar el directorio como entrada de metadatos
            await this._indexFile(fullPath, stat);
            indexed++;

            // Recursión en subdirectorio
   260|            const subResult = await this.scanDirectory(fullPath, recursive);
            indexed += subResult.indexed;
            skipped += subResult.skipped;
            errors += subResult.errors;
            continue;
          }

          // ── Archivos regulares ─────────────────────────
          if (stat.isFile()) {
            if (this._isExcluded(fullPath)) {
   270|              skipped++;
              continue;
            }

            if (stat.size > this._maxFileSize) {
              skipped++;
              continue;
            }

            await this._indexFile(fullPath, stat);
            indexed++;
   280|            continue;
          }

          // ── Otros tipos (symlinks, sockets, etc.): omitir ──
          skipped++;
        } catch (fileErr) {
          console.error(
            '[file-indexer] Error al procesar archivo:',
            fullPath,
            '-',
            fileErr.message,
          );
   290|          errors++;
        }
      }
    } catch (dirErr) {
      console.error('[file-indexer] Error al escanear directorio:', dirPath, '-', dirErr.message);
      errors++;
    }

    return { indexed, skipped, errors };
  }

   300|  /**
   * Indexa un archivo individual: guarda metadata en kv_store y genera embedding.
   *
   * @param {string} filePath — Ruta absoluta del archivo.
   * @param {import('fs').Stats} stat — Estadísticas del archivo.
   * @returns {Promise<boolean>} true si se indexó exitosamente.
   */
  async _indexFile(filePath, stat) {
    const normalizedPath = this._normalizePath(filePath);
    const ext = path.extname(filePath).toLowerCase();
    const name = path.basename(filePath);

   310|    // ── Calcular hash rápido del contenido (últimos bytes + tamaño) ──
    const contentHash = this._quickHash(filePath, stat);

    // ── Construir metadata ─────────────────────────────────
    const metadata = {
      name,
      ext,
      size: stat.size,
      modifiedAt: stat.mtime.toISOString(),
      isDirectory: stat.isDirectory(),
      indexedAt: new Date().toISOString(),
      contentHash,
   320|    };

    // ── Extraer texto y generar embedding (solo archivos no-directorio) ──
    if (!stat.isDirectory()) {
      try {
        const extractedText = await this._extractText(filePath, ext);
        if (extractedText && extractedText.trim().length > 0) {
          // Combinar nombre + contenido para embedding semántico
          const embeddingText = `${name}\n${extractedText.slice(0, MAX_CONTENT_CHARS)}`;
          const embedding = await this._embeddings.embed(embeddingText);

   330|          if (embedding) {
            // Guardar embedding como array de números en la metadata
            metadata.embedding = Array.from(embedding);
          }

          // Guardar en tabla memory para búsqueda por contenido
          this._localDb.addMemory(
            `[${name}] ${extractedText.slice(0, 300)}`,
            'file',
            0.3,
          );
   340|        }
      } catch (extractErr) {
        // Error no fatal: guardamos metadata sin embedding
        console.warn(
          '[file-indexer] No se pudo extraer texto de:',
          filePath,
          '-',
          extractErr.message,
        );
      }
    }

   350|    // ── Persistir metadata en kv_store ────────────────────
    this._localDb.kvSet(normalizedPath, JSON.stringify(metadata), KV_NAMESPACE);

    // ── Actualizar caché en memoria ────────────────────────
    this._metadataCache.set(normalizedPath, metadata);

    // ── Registrar en lista maestra de keys ─────────────────
    this._addToMasterKeyList(normalizedPath);

    // ── Actualizar estadísticas ────────────────────────────
    if (!stat.isDirectory()) {
   360|      this._stats.totalFiles++;
      this._stats.totalSize += stat.size;
    }

    return true;
  }

  /**
   * Extrae texto de un archivo según su extensión.
   * Usa librerías opcionales: mammoth para .docx, pdf-parse para .pdf.
   * Si la librería no está disponible, retorna null (no es error fatal).
   *
   * @param {string} filePath — Ruta absoluta del archivo.
   * @param {string} ext — Extensión del archivo (con punto, minúscula).
   * @returns {Promise<string | null>} Texto extraído o null si no se pudo.
   */
  async _extractText(filePath, ext) {
    // ── Texto plano ───────────────────────────────────────
    if (TEXT_EXTENSIONS.has(ext)) {
      try {
       380|        return fs.readFileSync(filePath, 'utf-8').slice(0, MAX_CONTENT_CHARS * 2);
      } catch {
        return null;
      }
    }

    // ── PDF ───────────────────────────────────────────────
    if (ext === '.pdf') {
      try {
        const pdfParse = require('pdf-parse');
        const dataBuffer = fs.readFileSync(filePath);
   390|        const data = await pdfParse(dataBuffer);
        return data.text ? data.text.slice(0, MAX_CONTENT_CHARS * 2) : null;
      } catch {
        // pdf-parse es opcional — si no está instalado, se omite contenido
        return null;
      }
    }

    // ── DOCX ──────────────────────────────────────────────
    if (ext === '.docx') {
      try {
   400|        const mammoth = require('mammoth');
        const result = await mammoth.extractRawText({ path: filePath });
        return result.value ? result.value.slice(0, MAX_CONTENT_CHARS * 2) : null;
      } catch {
        // mammoth es opcional — si no está instalado, se omite contenido
        return null;
      }
    }

    // ── Otros formatos: sin soporte de extracción ─────────
    return null;
   410|  }

  // ═════════════════════════════════════════════════════════
  //  SEGURIDAD: PERMISOS Y EXCLUSIONES
  // ═════════════════════════════════════════════════════════

  /**
   * Verifica que una ruta esté dentro de la whitelist de indexPaths.
   * Bloquea rutas del sistema aunque estuvieran en la whitelist por error.
   *
   * @param {string} dirPath — Ruta a verificar.
   * @returns {boolean} true si la ruta está permitida.
   420|   */
  _isAllowed(dirPath) {
    if (!dirPath) return false;

    const normalized = this._normalizePath(dirPath);

    // ── Bloqueo duro: rutas del sistema ───────────────────
    for (const forbidden of SYSTEM_FORBIDDEN_PREFIXES) {
      if (normalized.startsWith(this._normalizePath(forbidden))) {
        return false;
      }
    }
   430|
    // ── Bloqueo: solo discos locales (C:, D:, etc.) ───────
    // No indexar rutas de red (\\server\...) por seguridad
    if (normalized.startsWith('\\\\')) {
      return false;
    }

    // ── Whitelist: debe estar dentro de alguna ruta indexada ──
    for (const indexPath of this._indexPaths) {
      const normalizedIndex = this._normalizePath(indexPath);
      if (normalized === normalizedIndex || normalized.startsWith(normalizedIndex + '\\')) {
   440|        return true;
      }
    }

    return false;
  }

  /**
   * Verifica si un archivo o directorio debe ser excluido del índice.
   * Revisa patrones de exclusión, archivos ocultos, y extensiones de sistema.
   *
   * @param {string} filePath — Ruta a verificar.
   450|   * @returns {boolean} true si debe ser excluido.
   */
  _isExcluded(filePath) {
    if (!filePath) return true;

    const normalized = this._normalizePath(filePath);
    const segments = normalized.split('\\');
    const name = segments[segments.length - 1];

    // ── Archivos y carpetas ocultos (empiezan con .) ──────
    if (name.startsWith('.') && name !== '.') {
      return true;
   460|    }

    // ── Patrones de exclusión por segmento ────────────────
    for (const pattern of this._excludePatterns) {
      for (const segment of segments) {
        if (segment.toLowerCase() === pattern.toLowerCase()) {
          return true;
        }
      }
    }

    // ── Extensiones de sistema / binarios no indexables ───
   470|    const ext = path.extname(name).toLowerCase();
    const SKIP_EXTENSIONS = new Set([
      '.exe', '.dll',  '.sys', '.msi', '.bin', '.iso',
      '.zip', '.rar',  '.7z',  '.tar', '.gz',  '.bz2',
      '.mp4', '.avi',  '.mkv', '.mov', '.mp3', '.wav',
      '.png', '.jpg',  '.jpeg','.gif', '.bmp', '.ico',
      '.ttf', '.woff', '.woff2','.eot','.db',  '.sqlite',
    ]);
    if (SKIP_EXTENSIONS.has(ext)) {
      return true;
    }
   480|
    return false;
  }

  // ═════════════════════════════════════════════════════════
  //  BÚSQUEDA DE ARCHIVOS
  // ═════════════════════════════════════════════════════════

  /**
   * Busca archivos indexados combinando búsqueda por nombre y semántica.
   * Primero busca coincidencias textuales en el nombre, luego calcula
   * similitud coseno con el embedding de la query si el modelo está disponible.
   490|   *
   * @param {string} query — Texto de búsqueda del usuario.
   * @param {number} [limit=20] — Máximo de resultados a retornar.
   * @returns {Promise<Array<{path: string, name: string, ext: string, size: number, modifiedAt: string, relevance: number}>>}
   */
  async searchFiles(query, limit = 20) {
    if (!this._initialized) {
      console.error('[file-indexer] searchFiles: no inicializado.');
      return [];
    }
   500|
    if (!query || typeof query !== 'string' || query.trim().length === 0) {
      return [];
    }

    const q = query.toLowerCase().trim();
    const maxResults = Math.min(limit, MAX_INDEXED_FILES);

    // ── Obtener todas las claves indexadas ────────────────
    const keys = this._getMasterKeyList();
    if (keys.length === 0) {
      return [];
   510|    }

    // ── Fase 1: Búsqueda por nombre (rápida) ─────────────
    const nameMatches = [];
    const allEntries = [];

    for (const key of keys) {
      const raw = this._localDb.kvGet(key, KV_NAMESPACE);
      if (!raw) continue;

      let meta;
      try {
       520|        meta = JSON.parse(raw);
      } catch {
        continue;
      }

      const nameLower = (meta.name || '').toLowerCase();

      // Coincidencia exacta o parcial en nombre
      const exactMatch = nameLower === q;
      const containsMatch = nameLower.includes(q);
      const wordMatch = q.split(/\s+/).some((word) => nameLower.includes(word));

      if (exactMatch || containsMatch || wordMatch) {
   530|        let relevance = 0.5;
        if (exactMatch) relevance = 1.0;
        else if (containsMatch) relevance = 0.8;
        else if (wordMatch) relevance = 0.6;

        nameMatches.push({
          path: key,
          name: meta.name,
          ext: meta.ext,
          size: meta.size,
          modifiedAt: meta.modifiedAt,
          relevance,
   540|        });
      }

      // Guardar todas las entradas con embedding para fase semántica
      if (meta.embedding && Array.isArray(meta.embedding) && meta.embedding.length > 0) {
        allEntries.push({ key, meta, nameLower });
      }
    }

    // ── Fase 2: Búsqueda semántica (si hay modelo y entradas con embedding) ──
    const semanticMatches = [];
    if (allEntries.length > 0 && this._embeddings.isModelAvailable()) {
   550|      const queryEmbedding = await this._embeddings.embed(q);

      if (queryEmbedding) {
        for (const entry of allEntries) {
          const storedEmbedding = new Float32Array(entry.meta.embedding);
          const similarity = this._embeddings.cosineSimilarity(queryEmbedding, storedEmbedding);

          // Solo incluir si hay similitud significativa (> 0.2)
          if (similarity > 0.2) {
            semanticMatches.push({
              path: entry.key,
   560|              name: entry.meta.name,
              ext: entry.meta.ext,
              size: entry.meta.size,
              modifiedAt: entry.meta.modifiedAt,
              relevance: similarity * 0.7, // peso 0.7 para semántica
              _source: 'semantic',
            });
          }
        }
      }
    }

   570|    // ── Fase 3: Combinar y ordenar resultados ────────────
    const merged = new Map();

    // Agregar matches por nombre (prioridad alta)
    for (const match of nameMatches) {
      merged.set(match.path, match);
    }

    // Agregar matches semánticos (si no están ya por nombre, o con mayor score)
    for (const match of semanticMatches) {
      const existing = merged.get(match.path);
   580|      if (!existing || match.relevance > existing.relevance) {
        merged.set(match.path, match);
      }
    }

    // Ordenar por relevancia descendente
    const results = Array.from(merged.values())
      .sort((a, b) => b.relevance - a.relevance)
      .slice(0, maxResults);

    return results;
   590|  }

  // ═════════════════════════════════════════════════════════
  //  GESTIÓN DE RUTAS DE ÍNDICE
  // ═════════════════════════════════════════════════════════

  /**
   * Obtiene la lista de rutas configuradas para indexar.
   *
   * @returns {string[]} Array de rutas de índice.
   */
  getIndexedPaths() {
   600|    if (!this._initialized) {
      console.error('[file-indexer] getIndexedPaths: no inicializado.');
      return [];
    }
    return [...this._indexPaths];
  }

  /**
   * Obtiene estadísticas del índice: total de archivos, tamaño, último escaneo.
   *
   * @returns {{ totalFiles: number, totalSize: number, lastScan: string | null, indexedPaths: string[] }}
   610|   */
  getIndexStats() {
    if (!this._initialized) {
      console.error('[file-indexer] getIndexStats: no inicializado.');
      return { totalFiles: 0, totalSize: 0, lastScan: null, indexedPaths: [] };
    }

    return {
      totalFiles: this._stats.totalFiles,
      totalSize: this._stats.totalSize,
      lastScan: this._stats.lastScan,
      indexedPaths: [...this._indexPaths],
   620|    };
  }

  /**
   * Agrega una nueva ruta a la whitelist de indexación.
   * La ruta debe existir en disco y no ser una ruta del sistema.
   *
   * @param {string} dirPath — Ruta absoluta del directorio a agregar.
   * @returns {boolean} true si se agregó correctamente.
   */
  addIndexPath(dirPath) {
    if (!this._initialized) {
   630|      console.error('[file-indexer] addIndexPath: no inicializado.');
      return false;
    }

    if (!dirPath || typeof dirPath !== 'string') {
      console.error('[file-indexer] addIndexPath: ruta inválida.');
      return false;
    }

    const normalized = this._normalizePath(dirPath);

   640|    // Verificar que no es ruta del sistema
    for (const forbidden of SYSTEM_FORBIDDEN_PREFIXES) {
      if (normalized.startsWith(this._normalizePath(forbidden))) {
        console.error('[file-indexer] addIndexPath: no se permite indexar rutas del sistema:', dirPath);
        return false;
      }
    }

    // Verificar que existe
    if (!fs.existsSync(dirPath)) {
      console.error('[file-indexer] addIndexPath: la ruta no existe:', dirPath);
   650|      return false;
    }

    // Verificar que no es duplicado
    if (this._indexPaths.some((p) => this._normalizePath(p) === normalized)) {
      console.warn('[file-indexer] addIndexPath: la ruta ya está en la lista:', dirPath);
      return false;
    }

    this._indexPaths.push(dirPath);
    this._saveConfig();
   660|
    console.log('[file-indexer] Ruta agregada al índice:', dirPath);
    return true;
  }

  /**
   * Remueve una ruta de la whitelist de indexación.
   * No elimina los metadatos ya indexados de esa ruta.
   *
   * @param {string} dirPath — Ruta absoluta a remover.
   * @returns {boolean} true si se removió correctamente.
   670|   */
  removeIndexPath(dirPath) {
    if (!this._initialized) {
      console.error('[file-indexer] removeIndexPath: no inicializado.');
      return false;
    }

    const normalized = this._normalizePath(dirPath);
    const idx = this._indexPaths.findIndex((p) => this._normalizePath(p) === normalized);

    if (idx === -1) {
      console.warn('[file-indexer] removeIndexPath: ruta no encontrada en la lista:', dirPath);
   680|      return false;
    }

    this._indexPaths.splice(idx, 1);
    this._saveConfig();

    console.log('[file-indexer] Ruta removida del índice:', dirPath);
    return true;
  }

  // ═════════════════════════════════════════════════════════
  //  RE-INDEXADO Y LIMPIEZA
   690|  // ═════════════════════════════════════════════════════════

  /**
   * Fuerza un re-indexado completo de todas las rutas configuradas.
   * Primero limpia el índice existente, luego escanea todo desde cero.
   *
   * @returns {Promise<{ indexed: number, skipped: number, errors: number }>}
   */
  async forceReindex() {
    if (!this._initialized) {
      console.error('[file-indexer] forceReindex: no inicializado.');
      return { indexed: 0, skipped: 0, errors: 0 };
   700|    }

    console.log('[file-indexer] Iniciando re-indexado completo...');
    const startTime = Date.now();

    // ── Limpiar índice existente ──────────────────────────
    this.clearIndex();

    // ── Re-escanear todas las rutas ───────────────────────
    let totalIndexed = 0;
    let totalSkipped = 0;
    let totalErrors = 0;
   710|
    for (const dirPath of this._indexPaths) {
      if (!fs.existsSync(dirPath)) {
        console.warn('[file-indexer] Ruta de índice no existe, se omite:', dirPath);
        continue;
      }

      const result = await this.scanDirectory(dirPath, true);
      totalIndexed += result.indexed;
      totalSkipped += result.skipped;
      totalErrors += result.errors;
   720|    }

    // ── Actualizar timestamp de último escaneo ────────────
    this._stats.lastScan = new Date().toISOString();
    this._saveConfig();

    const elapsed = ((Date.now() - startTime) / 1000).toFixed(1);
    console.log(
      '[file-indexer] Re-indexado completado en', elapsed + 's:',
      totalIndexed, 'indexados,',
      totalSkipped, 'omitidos,',
   730|      totalErrors, 'errores.',
    );

    return { indexed: totalIndexed, skipped: totalSkipped, errors: totalErrors };
  }

  /**
   * Programa el re-indexado periódico usando el job-scheduler.
   * Crea o actualiza el job 'file_indexer_rescan' con la expresión cron dada.
   *
   * @param {string} cronExpr — Expresión cron (ej. '0 *\/6 * * *').
   * @returns {boolean} true si se programó correctamente.
   740|   */
  scheduleReindex(cronExpr) {
    if (!this._initialized) {
      console.error('[file-indexer] scheduleReindex: no inicializado.');
      return false;
    }

    if (!this._jobScheduler) {
      console.warn(
        '[file-indexer] scheduleReindex: job-scheduler no disponible.',
        'El re-indexado será solo manual (llamar forceReindex()).',
   750|      );
      return false;
    }

    this._schedule = cronExpr;
    this._saveConfig();

    const ok = this._jobScheduler.addJob(
      'file_indexer_rescan',
      'Re-indexado periódico de archivos del usuario',
      cronExpr,
      'Re-indexar archivos del usuario para búsqueda semántica (file-indexer)',
   760|    );

    if (ok) {
      console.log('[file-indexer] Job de re-indexado programado:', cronExpr);
    } else {
      console.error('[file-indexer] No se pudo programar el job de re-indexado.');
    }

    return ok;
  }

  /**
   * Limpia completamente el índice: borra todos los metadatos de kv_store,
   * reinicia estadísticas y vacía la caché en memoria.
   770|   */
  clearIndex() {
    if (!this._initialized) {
      console.error('[file-indexer] clearIndex: no inicializado.');
      return;
    }

    // ── Limpiar cada entrada individual en kv_store ───────
    const keys = this._getMasterKeyList();
    for (const key of keys) {
      // Sobrescribir con valor vacío (no hay kvDelete en local-db)
      this._localDb.kvSet(key, '', KV_NAMESPACE);
    }
   780|
    // ── Limpiar lista maestra ─────────────────────────────
    this._localDb.kvSet(KV_KEYS_KEY, '[]', KV_NAMESPACE);

    // ── Reiniciar estadísticas ────────────────────────────
    this._stats.totalFiles = 0;
    this._stats.totalSize = 0;
    this._stats.lastScan = null;

    // ── Vaciar caché en memoria ───────────────────────────
    this._metadataCache.clear();
   790|
    // ── Persistir configuración limpia ────────────────────
    this._saveConfig();

    console.log('[file-indexer] Índice limpiado completamente.');
  }

  // ═════════════════════════════════════════════════════════
  //  HELPERS INTERNOS
  // ═════════════════════════════════════════════════════════

  /**
   * Normaliza una ruta de archivo: resuelve a absoluta, normaliza separadores
   800|   * a backslash (Windows) y convierte a minúsculas para comparaciones.
   *
   * @param {string} filePath — Ruta a normalizar.
   * @returns {string} Ruta normalizada.
   */
  _normalizePath(filePath) {
    try {
      return path.resolve(filePath).replace(/\//g, '\\').toLowerCase();
    } catch {
      return filePath.replace(/\//g, '\\').toLowerCase();
    }
  }
   810|
  /**
   * Calcula un hash rápido del contenido del archivo para detectar cambios.
   * Lee los primeros 4KB + últimos 4KB y combina con el tamaño.
   *
   * @param {string} filePath — Ruta del archivo.
   * @param {import('fs').Stats} stat — Estadísticas del archivo.
   * @returns {string} Hash hexadecimal.
   */
  _quickHash(filePath, stat) {
    try {
      const hash = crypto.createHash('md5');
   820|      hash.update(String(stat.size));
      hash.update(String(stat.mtimeMs));

      const fd = fs.openSync(filePath, 'r');
      try {
        const buf = Buffer.alloc(4096);
        // Primeros 4KB
        const bytesRead = fs.readSync(fd, buf, 0, 4096, 0);
        if (bytesRead > 0) hash.update(buf.slice(0, bytesRead));

        // Últimos 4KB (si el archivo es suficientemente grande)
        if (stat.size > 8192) {
   830|          const tailPos = Math.max(0, stat.size - 4096);
          const tailBytes = fs.readSync(fd, buf, 0, 4096, tailPos);
          if (tailBytes > 0) hash.update(buf.slice(0, tailBytes));
        }
      } finally {
        fs.closeSync(fd);
      }

      return hash.digest('hex');
    } catch {
      // Si no se puede leer, usar solo stats como hash
   840|      return crypto.createHash('md5')
        .update(String(stat.size))
        .update(String(stat.mtimeMs))
        .digest('hex');
    }
  }

  /**
   * Lee un directorio con timeout de seguridad.
   *
   * @param {string} dirPath — Ruta del directorio.
   * @returns {Promise<fs.Dirent[] | null>} Entradas del directorio o null si falla.
   850|   */
  async _readdirWithTimeout(dirPath) {
    try {
      const result = await Promise.race([
        fs.promises.readdir(dirPath, { withFileTypes: true }),
        new Promise((_, reject) =>
          setTimeout(
            () => reject(new Error(`Timeout al leer directorio: ${dirPath}`)),
            SCAN_TIMEOUT_MS,
          ),
        ),
   860|      ]);
      return result;
    } catch (err) {
      console.warn('[file-indexer] Error al leer directorio:', dirPath, '-', err.message);
      return null;
    }
  }

  /**
   * Obtiene la lista maestra de claves indexadas desde kv_store.
   *
   * @returns {string[]} Array de rutas normalizadas.
   870|   */
  _getMasterKeyList() {
    try {
      const raw = this._localDb.kvGet(KV_KEYS_KEY, KV_NAMESPACE);
      if (!raw) return [];
      const list = JSON.parse(raw);
      return Array.isArray(list) ? list : [];
    } catch {
      return [];
    }
  }
   880|
  /**
   * Agrega una clave a la lista maestra en kv_store.
   *
   * @param {string} key — Ruta normalizada del archivo.
   */
  _addToMasterKeyList(key) {
    const keys = this._getMasterKeyList();
    if (!keys.includes(key)) {
      keys.push(key);
      this._localDb.kvSet(KV_KEYS_KEY, JSON.stringify(keys), KV_NAMESPACE);
    }
   890|  }

  /**
   * Carga la configuración persistida desde kv_store.
   * Restaura indexPaths, stats y schedule si existen.
   */
  _loadConfig() {
    try {
      const raw = this._localDb.kvGet(KV_CONFIG_KEY, KV_NAMESPACE);
      if (!raw) return;

      const config = JSON.parse(raw);
   900|
      if (config.indexPaths && Array.isArray(config.indexPaths) && config.indexPaths.length > 0) {
        // Solo restaurar rutas que aún existen en disco
        this._indexPaths = config.indexPaths.filter((p) => {
          const exists = fs.existsSync(p);
          if (!exists) {
            console.warn('[file-indexer] Ruta de índice obsoleta (no existe):', p);
          }
          return exists;
        });
      }
   910|
      if (config.stats) {
        this._stats.totalFiles = config.stats.totalFiles || 0;
        this._stats.totalSize = config.stats.totalSize || 0;
        this._stats.lastScan = config.stats.lastScan || null;
      }

      if (config.schedule) {
        this._schedule = config.schedule;
      }
    } catch (err) {
      console.warn('[file-indexer] Error al cargar configuración persistida:', err.message);
   920|    }
  }

  /**
   * Persiste la configuración actual en kv_store.
   */
  _saveConfig() {
    try {
      const config = {
        indexPaths: this._indexPaths,
        stats: {
          totalFiles: this._stats.totalFiles,
   930|          totalSize: this._stats.totalSize,
          lastScan: this._stats.lastScan,
        },
        schedule: this._schedule,
      };
      this._localDb.kvSet(KV_CONFIG_KEY, JSON.stringify(config), KV_NAMESPACE);
    } catch (err) {
      console.warn('[file-indexer] Error al guardar configuración:', err.message);
    }
  }
   940|
  /**
   * Restaura la caché de metadatos desde kv_store al iniciar.
   * Carga todas las entradas indexadas previamente en memoria.
   */
  _restoreMetadataCache() {
    const keys = this._getMasterKeyList();
    let loaded = 0;

    for (const key of keys) {
      try {
        const raw = this._localDb.kvGet(key, KV_NAMESPACE);
   950|        if (raw && raw.length > 0) {
          const meta = JSON.parse(raw);
          this._metadataCache.set(key, meta);
          loaded++;
        }
      } catch {
        // Entrada corrupta, se omite
      }
    }

    if (loaded > 0) {
   960|      console.log('[file-indexer] Caché de metadatos restaurada:', loaded, 'entradas.');
    }
  }
}

// ═══════════════════════════════════════════════════════════
//  EXPORTACIONES
// ═══════════════════════════════════════════════════════════

module.exports = { FileIndexer };
