-- =====================================================================
-- Nordik — DDL canónico de billing / suscripción (Postgres ≥ 14)
--
-- Consumido por:
--   • docker-entrypoint-initdb.d en docker-compose.yml (solo 1.er arranque)
--   • `npm run backend:db-init` (SQLAlchemy create_all, mismos tipos que ORMs)
--
-- Alta de filas: app interna auto-venta1. Login producto: frontend/backend.
-- =====================================================================

CREATE TABLE IF NOT EXISTS clientes_suscripcion (
  id UUID PRIMARY KEY,
  nombre VARCHAR(200) NOT NULL,
  cedula VARCHAR(32) NOT NULL UNIQUE,
  clave_acceso VARCHAR(128) NOT NULL,
  correo VARCHAR(320) NOT NULL,
  telefono VARCHAR(32),
  fecha_vencimiento DATE NOT NULL,
  plan VARCHAR(20) NOT NULL CHECK (plan IN ('mensual', 'trimestral', 'anual')),
  creado_en TIMESTAMPTZ NOT NULL DEFAULT now(),
  recordatorio_7d_enviado_en TIMESTAMPTZ,
  notas TEXT,
  hardware_token_hash VARCHAR(128) UNIQUE,
  ai_provider_id VARCHAR(20) NOT NULL DEFAULT 'deepseek'
    CHECK (ai_provider_id IN ('deepseek', 'gemini', 'chatgpt')),
  ai_billing_mode VARCHAR(20) NOT NULL DEFAULT 'mensual'
    CHECK (ai_billing_mode IN ('mensual', 'trimestral', 'anual')),
  pendrive_status VARCHAR(20) NOT NULL DEFAULT 'active'
    CHECK (pendrive_status IN ('active', 'revoked', 'blocked'))
);

CREATE INDEX IF NOT EXISTS idx_clientes_hardware_token
  ON clientes_suscripcion (hardware_token_hash)
  WHERE hardware_token_hash IS NOT NULL;

COMMENT ON COLUMN clientes_suscripcion.hardware_token_hash IS
  'SHA-256(serial USB + pepper). Nunca guardar el serial en claro. Alta con pendrive en auto-venta1.';

COMMENT ON COLUMN clientes_suscripcion.ai_provider_id IS
  'Proveedor de IA asignado en alta (auto-venta1). deepseek = único operativo hoy; gemini/chatgpt roadmap.';

COMMENT ON COLUMN clientes_suscripcion.ai_billing_mode IS
  'Ciclo de facturación del uso del modelo (mensual/trimestral/anual), independiente del plan Nordik.';

CREATE INDEX IF NOT EXISTS idx_clientes_vencimiento ON clientes_suscripcion (fecha_vencimiento);
CREATE INDEX IF NOT EXISTS idx_clientes_correo ON clientes_suscripcion (correo);
CREATE INDEX IF NOT EXISTS idx_clientes_telefono ON clientes_suscripcion (telefono);

COMMENT ON TABLE clientes_suscripcion IS
  'Suscripciones: alta desde auto-venta1; JWT y lecturas desde frontend/backend; bots/servicios de cobro externos.';

COMMENT ON COLUMN clientes_suscripcion.clave_acceso IS
  'Hash bcrypt ($2b$...). Legacy texto plano: migrar con scripts/migrate_clave_acceso_hash.py';

-- Ledger idempotente para Chatbot-Cobro (recordatorios Meta)
CREATE TABLE IF NOT EXISTS subscription_reminder_outbox (
  dedupe_key TEXT PRIMARY KEY,
  subscription_id TEXT NOT NULL,
  expiry_window_start_utc TIMESTAMPTZ NOT NULL,
  expiry_window_end_utc_excl TIMESTAMPTZ NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
