// embeddings.cjs — Embeddings ONNX locales con @xenova/transformers
// Modelo: Xenova/all-MiniLM-L6-v2 (80MB, 384 dimensiones, multilingüe)
//
// Diseñado para correr en el proceso principal de Electron.
// El modelo se descarga una vez y se cachea en disco (~/.cache/huggingface/).
// Si no hay internet la primera vez, retorna null sin crashear.
//
// Según PLAN-DOT-2026-2027 §M4S1-A — Embeddings ONNX

const path = require('path');

// ═══════════════════════════════════════════════════════════
//  ESTADO DEL MODELO
// ═══════════════════════════════════════════════════════════

/** @type {import('@xenova/transformers').Pipeline | null} */
    20|let extractor = null;

/** Indica si el modelo está disponible y listo para usar */
let modelAvailable = false;

/** Indica si hay una carga en progreso */
let loading = false;

/** Promesa de carga activa para evitar carreras */
let loadPromise = null;

// ═══════════════════════════════════════════════════════════
//  CONFIGURACIÓN
// ═══════════════════════════════════════════════════════════

/** Tiempo máximo para generar un embedding (milisegundos) */
    40|const EMBED_TIMEOUT_MS = 5000;

/** Tamaño del lote para embedBatch */
const BATCH_SIZE = 32;

// ═══════════════════════════════════════════════════════════
//  CARGA LAZY DEL MODELO
// ═══════════════════════════════════════════════════════════

/**
 * Carga el modelo ONNX de forma lazy.
    50| * La primera llamada descarga el modelo (~80MB) y lo cachea en disco.
 * Llamadas subsecuentes retornan inmediatamente.
 *
 * @returns {Promise<boolean>} true si el modelo está disponible, false si falló.
 */
async function ensureModel() {
  // Ya cargado
  if (extractor) return true;

  // Carga en progreso — esperar la misma promesa
  if (loading) {
    60|    await loadPromise;
    return modelAvailable;
  }

  // Iniciar carga
  loading = true;
  loadPromise = (async () => {
    try {
      const { pipeline } = require('@xenova/transformers');
      extractor = await pipeline('feature-extraction', 'Xenova/all-MiniLM-L6-v2');
      modelAvailable = true;
    70|      console.log('[embeddings] Modelo Xenova/all-MiniLM-L6-v2 cargado exitosamente (384 dims)');
    } catch (err) {
      console.error('[embeddings] Error al cargar el modelo ONNX:', err.message);
      console.error('[embeddings] La búsqueda semántica no estará disponible hasta que el modelo se descargue.');
      modelAvailable = false;
      extractor = null;
    } finally {
      loading = false;
    }
  })();

  await loadPromise;
  return modelAvailable;
}

// ═══════════════════════════════════════════════════════════
//  EMBEDDING UNITARIO
// ═══════════════════════════════════════════════════════════

/**
 * Genera un embedding para un texto dado.
 * Si el modelo no está disponible, retorna null sin crashear.
 *
 * @param {string} text — Texto a embeber (puede ser multilenguaje).
 * @returns {Promise<Float32Array | null>} Vector de 384 dimensiones, o null si falla.
 */
async function embed(text) {
  if (!text || typeof text !== 'string' || text.trim().length === 0) {
    console.warn('[embeddings] embed() llamado con texto vacío');
    return null;
  }

  const ok = await ensureModel();
  if (!ok) return null;

  try {
    const result = await Promise.race([
      extractor(text, { pooling: 'mean', normalize: true }),
      new Promise((_, reject) =>
        setTimeout(
          () => reject(new Error(`Timeout de embedding (${EMBED_TIMEOUT_MS / 1000}s)`)),
          EMBED_TIMEOUT_MS
        )
      ),
    ]);

    // result.data es un Float32Array con 384 dimensiones normalizadas
    return new Float32Array(result.data);
  } catch (err) {
    console.error('[embeddings] Error al generar embedding:', err.message);
    return null;
  }
}

// ═══════════════════════════════════════════════════════════
//  SIMILITUD COSENO
// ═══════════════════════════════════════════════════════════

/**
 * Calcula la similitud coseno entre dos vectores de embedding.
 * Ambos vectores deben tener la misma longitud (384).
 *
 * @param {Float32Array} a — Vector A.
 * @param {Float32Array} b — Vector B.
 * @returns {number} Similitud en el rango [-1, 1]. 1 = idénticos, 0 = ortogonales.
 */
function cosineSimilarity(a, b) {
  if (!a || !b || a.length !== b.length) return 0;

  let dotProduct = 0;
  let normA = 0;
  let normB = 0;

  for (let i = 0; i < a.length; i++) {
    dotProduct += a[i] * b[i];
    normA += a[i] * a[i];
    normB += b[i] * b[i];
  }

  const denominator = Math.sqrt(normA) * Math.sqrt(normB);
  if (denominator === 0) return 0;

  return dotProduct / denominator;
}

// ═══════════════════════════════════════════════════════════
//  EMBEDDING POR LOTES
// ═══════════════════════════════════════════════════════════

/**
 * Genera embeddings para un lote de textos.
 * Procesa en sub-lotes de 32 para no saturar la memoria ni el runtime ONNX.
 *
 * @param {string[]} texts — Array de textos a embeber.
 * @returns {Promise<Float32Array[]>} Array de vectores de embedding (mismo orden).
 *   Los textos que fallen producen null en esa posición.
 */
async function embedBatch(texts) {
  if (!texts || texts.length === 0) return [];

  const results = [];

  for (let i = 0; i < texts.length; i += BATCH_SIZE) {
    const batch = texts.slice(i, i + BATCH_SIZE);
    const batchResults = await Promise.all(batch.map((t) => embed(t)));
    results.push(...batchResults);
  }

  return results;
}

// ═══════════════════════════════════════════════════════════
//  VERIFICACIÓN DE DISPONIBILIDAD
// ═══════════════════════════════════════════════════════════

/**
 * Indica si el modelo ONNX está disponible y listo para usar.
 * Útil para que el frontend sepa si mostrar opciones de búsqueda semántica.
 *
 * @returns {boolean} true si el modelo cargó correctamente.
 */
function isModelAvailable() {
  return modelAvailable;
}

// ═══════════════════════════════════════════════════════════
//  EXPORTACIONES
// ═══════════════════════════════════════════════════════════

module.exports = {
  // Carga del modelo
  ensureModel,
  isModelAvailable,

  // Embeddings
  embed,
  embedBatch,

  // Similitud
  cosineSimilarity,
};
