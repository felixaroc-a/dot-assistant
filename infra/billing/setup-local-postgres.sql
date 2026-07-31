-- Ejecutar una vez como superusuario postgres (setup local Windows).
DO $$
BEGIN
  IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'nordik') THEN
    CREATE ROLE nordik WITH LOGIN PASSWORD 'TuPasswordFuerte123!';
  ELSE
    ALTER ROLE nordik WITH LOGIN PASSWORD 'TuPasswordFuerte123!';
  END IF;
END
$$;

SELECT 'CREATE DATABASE nordik_billing OWNER nordik'
WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = 'nordik_billing')\gexec

GRANT ALL PRIVILEGES ON DATABASE nordik_billing TO nordik;
