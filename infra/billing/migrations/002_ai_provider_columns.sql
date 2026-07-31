-- Aplicar en Postgres existente (no en primer init si ya usás schema.sql actualizado).
ALTER TABLE clientes_suscripcion
  ADD COLUMN IF NOT EXISTS ai_provider_id VARCHAR(20) NOT NULL DEFAULT 'deepseek'
    CHECK (ai_provider_id IN ('deepseek', 'gemini', 'chatgpt'));

ALTER TABLE clientes_suscripcion
  ADD COLUMN IF NOT EXISTS ai_billing_mode VARCHAR(20) NOT NULL DEFAULT 'mensual'
    CHECK (ai_billing_mode IN ('mensual', 'trimestral', 'anual'));
