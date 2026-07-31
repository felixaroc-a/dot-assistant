"""DEV-ONLY: Este script crea datos de prueba. No ejecutar en producción."""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

# ── Guarda de producción ──────────────────────────────────────────────
if os.environ.get("DOT_ENV", "development") == "production":
    print("ERROR: Este script es solo para desarrollo. DOT_ENV=production detectado. No se puede ejecutar en producción.", file=sys.stderr)
    sys.exit(1)
# ───────────────────────────────────────────────────────────────────────

import bcrypt
import uuid
from app.billing_db import get_engine
from sqlalchemy import text

password = "test"
hashed = bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()
print(f"Hash generado: {hashed}")

e = get_engine()
conn = e.connect()
result = conn.execute(
    text("SELECT id FROM clientes_suscripcion WHERE cedula = :cedula"),
    {"cedula": "test"},
)
existing = result.fetchone()
if existing:
    conn.execute(
        text("UPDATE clientes_suscripcion SET clave_acceso = :clave WHERE cedula = :cedula"),
        {"clave": hashed, "cedula": "test"},
    )
    print("Usuario actualizado")
else:
    conn.execute(
        text(
            "INSERT INTO clientes_suscripcion "
            "(id, nombre, cedula, clave_acceso, correo, fecha_vencimiento, plan) "
            "VALUES (:id, :nombre, :cedula, :clave, :correo, :vencimiento, :plan)"
        ),
        {
            "id": str(uuid.uuid4()),
            "nombre": "Usuario Test",
            "cedula": "test123",
            "clave": hashed,
            "correo": "test@test.com",
            "vencimiento": "2027-12-31",
            "plan": "anual",
        },
    )
    print("Usuario creado")

conn.commit()
conn.close()
print("OK")
