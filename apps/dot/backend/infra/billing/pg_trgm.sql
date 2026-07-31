-- ============================================================
-- pg_trgm extension + índices para búsqueda full-text
-- ============================================================
-- Ejecutar UNA vez en Postgres de producción:
--   psql -U postgres -d nordik_billing -f infra/billing/pg_trgm.sql
--
-- En SQLite (dev), el sistema usa ILIKE como fallback automático
-- sin necesidad de extensiones.
-- ============================================================

-- 1. Habilitar extensión pg_trgm
CREATE EXTENSION IF NOT EXISTS pg_trgm;

-- 2. Índice GIN para búsqueda por similitud en títulos de conversaciones
--    Permite queries tipo: SELECT * FROM chat_conversations WHERE title % 'término';
--    Y ranking por similarity: ORDER BY similarity(title, 'término') DESC;
--    Nota: pg_trgm trabaja con strings. Si el título puede ser muy largo,
--    usar GiST en vez de GIN (GIN es más rápido para búsqueda, GiST para indexado).
CREATE INDEX IF NOT EXISTS idx_chat_conversations_title_trgm
    ON chat_conversations USING GIN (title gin_trgm_ops);

-- 3. (Opcional) Índice GiST para búsqueda con ranking más preciso
--    Descomentar si GIN resulta muy lento en writes.
-- CREATE INDEX IF NOT EXISTS idx_chat_conversations_title_trgm_gist
--     ON chat_conversations USING GiST (title gist_trgm_ops);

-- 4. Verificar que los índices se crearon
-- SELECT indexname, indexdef FROM pg_indexes WHERE tablename = 'chat_conversations';
