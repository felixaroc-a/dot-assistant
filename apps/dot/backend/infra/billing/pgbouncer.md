# PgBouncer — Connection Pool para DOT en producción

PgBouncer es un pool de conexiones ligero que actúa como proxy entre DOT y Postgres. Reduce la latencia de conexión y permite manejar cientos de clientes concurrentes con pocas conexiones a Postgres.

## ¿Por qué PgBouncer?

- **Sin PgBouncer**: cada request de DOT abre/cierra una conexión TCP a Postgres (~5-10ms). Con 100 requests/segundo, Postgres puede saturarse con 100 conexiones activas.
- **Con PgBouncer**: DOT se conecta a PgBouncer (localhost:6432), que mantiene un pool de ~20 conexiones a Postgres. 1000 clientes concurrentes usan las mismas 20 conexiones.

## Instalación

```bash
# Ubuntu/Debian
sudo apt install -y pgbouncer

# Verificar versión
pgbouncer --version
```

## Configuración

### 1. Copiar archivo de configuración

```bash
sudo cp infra/billing/pgbouncer.ini /etc/pgbouncer/pgbouncer.ini
```

### 2. Crear archivo de usuarios

```bash
# Generar hash de contraseña
echo -n "tu_passwordnordik_user" | md5sum

# Crear /etc/pgbouncer/userlist.txt
sudo tee /etc/pgbouncer/userlist.txt <<EOF
"nordik_user" "md5hash_generado"
EOF

sudo chmod 600 /etc/pgbouncer/userlist.txt
```

### 3. Iniciar PgBouncer

```bash
sudo systemctl enable pgbouncer
sudo systemctl start pgbouncer
sudo systemctl status pgbouncer
```

### 4. Actualizar DATABASE_URL en DOT

```env
# Sin PgBouncer (conexión directa a Postgres)
DATABASE_URL=postgresql+psycopg://user:pass@localhost:5432/nordik_billing

# Con PgBouncer (conexión via pool, puerto 6432)
DATABASE_URL=postgresql+psycopg://user:pass@localhost:6432/nordik_billing
```

## Verificación

```bash
# ¿PgBouncer está escuchando?
ss -tlnp | grep 6432

# Estadísticas del pool
psql -h 127.0.0.1 -p 6432 -U pgbouncer pgbouncer
# Dentro de psql:
SHOW POOLS;
SHOW STATS;
SHOW CLIENTS;
SHOW SERVERS;
```

## PgBouncer + SQLAlchemy

DOT usa SQLAlchemy con las siguientes configuraciones compatibles con PgBouncer:

```python
# apps/dot/backend/app/billing_db.py
create_engine(
    url,
    pool_pre_ping=True,      # Verifica conexión antes de usarla
    pool_recycle=3600,        # Recicla conexiones cada 1h (menor que server_lifetime de PgBouncer)
    max_overflow=10,          # Conexiones extra bajo carga pico
    pool_size=5,              # Tamaño base del pool local (default SQLAlchemy)
)
```

**Pool modes compatibles:**

| Pool mode | Compatible con DOT? | Rendimiento |
|-----------|-------------------|-------------|
| `session` | Si (usar este) | Bueno |
| `transaction` | No (DOT usa session identity map) | Mejor |
| `statement` | No (DOT necesita sesiones) | Máximo |

**Regla de oro**: `pool_recycle` de SQLAlchemy DEBE ser menor que `server_lifetime` de PgBouncer. Si PgBouncer cierra una conexión antes de que SQLAlchemy la recicle, habrá errores `OperationalError: server closed the connection unexpectedly`.

- `pool_recycle=3600` (1h) < `server_lifetime=7200` (2h) ✓

## Troubleshooting

### Error: "no more connections allowed"
Aumentar `default_pool_size` y `max_db_connections` en `pgbouncer.ini`.

### Error: "server closed the connection unexpectedly"
- Verificar que `pool_recycle` < `server_lifetime`.
- Activar `pool_pre_ping=True` en SQLAlchemy.
- Aumentar `server_idle_timeout` en PgBouncer.

### PgBouncer no inicia
```bash
# Ver logs
sudo tail -f /var/log/pgbouncer/pgbouncer.log

# Test de configuración
pgbouncer -d /etc/pgbouncer/pgbouncer.ini
```

## Monitoreo (Grafana)

PgBouncer expone métricas via `SHOW STATS` que pueden scraperse con un exporter o script cron:

```bash
# Métricas clave cada 60s
psql -h 127.0.0.1 -p 6432 -U pgbouncer pgbouncer -c "SHOW POOLS;" --csv
```

Dashboard incluido en `infra/grafana/dashboards/dot-system.json` (métricas de DB).

## Docker (alternativa)

```bash
docker run -d \
  --name pgbouncer \
  -p 6432:6432 \
  -v $(pwd)/infra/billing/pgbouncer.ini:/etc/pgbouncer/pgbouncer.ini \
  -v $(pwd)/infra/billing/userlist.txt:/etc/pgbouncer/userlist.txt \
  edoburu/pgbouncer
```

## Desarrollo local

En desarrollo (SQLite), PgBouncer no es necesario. Solo aplica cuando `DATABASE_URL` apunta a Postgres (`postgresql+psycopg://...`).
