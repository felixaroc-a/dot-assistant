"""Corregir formato de cédula para que coincida con el frontend."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from dotenv import load_dotenv
load_dotenv()

from app.billing_db import get_engine
from sqlalchemy import text

e = get_engine()
with e.connect() as conn:
    # Ver qué cédulas hay
    rows = conn.execute(text("SELECT id, cedula FROM clientes_suscripcion")).fetchall()
    print(f"[OK] {len(rows)} usuario(s) en BD:")
    for row in rows:
        print(f"      ID: {row[0][:8]}... Cedula: '{row[1]}'")

    # Actualizar formato
    conn.execute(
        text("UPDATE clientes_suscripcion SET cedula = :nueva WHERE cedula = :vieja"),
        {"nueva": "V-12345678", "vieja": "v12345678"},
    )
    conn.commit()

    # Verificar
    r = conn.execute(
        text("SELECT cedula FROM clientes_suscripcion WHERE cedula = :c"),
        {"c": "V-12345678"},
    ).fetchone()
    if r:
        print(f"[OK] Cedula actualizada a: '{r[0]}'")
    else:
        print("[ERROR] No se pudo actualizar la cedula")
