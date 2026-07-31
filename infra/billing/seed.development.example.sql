-- ⚠️ DEV-ONLY: Este seed crea datos de ejemplo. NO ejecutar en producción.
-- Copia opcional tras levantar Docker: psql desde el contenedor o cliente local.
-- Ajustá UUID, contraseña y fechas antes de ejecutar.

-- INSERT INTO clientes_suscripcion (
--   id, nombre, cedula, clave_acceso, correo, telefono, fecha_vencimiento, plan
-- ) VALUES (
--   gen_random_uuid(),
--   'Cliente prueba Nordik',
--   '0999999999',
--   'clave_temporal_demo',
--   'demo@ejemplo.invalid',
--   '+593991234567',
--   CURRENT_DATE + interval '365 days',
--   'mensual'
-- );

SELECT 'Define un INSERT real y ejecutá con cuidado; no uses datos de producción.' AS nota;
