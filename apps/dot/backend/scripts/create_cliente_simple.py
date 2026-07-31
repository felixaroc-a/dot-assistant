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

cedula = "demo"
password = "demo123"
hashed = bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()
print(f"Cliente: {cedula} / {password}")

e = get_engine()
conn = e.connect()
conn.execute(
    text("""
        INSERT OR IGNORE INTO clientes_suscripcion
        (id, nombre, cedula, clave_acceso, correo, fecha_vencimiento, plan)
        VALUES (:id, :nombre, :cedula, :clave, :correo, :vencimiento, :plan)
    """),
    {
        "id": str(uuid.uuid4()),
        "nombre": "Usuario Demo",
        "cedula": cedula,
        "clave": hashed,
        "correo": "demo@dot.app",
        "vencimiento": "2027-12-31",
        "plan": "anual",
    },
)
conn.commit()
conn.close()
print("OK")
