"""Lee la clave de un cliente."""
from app.billing_db import get_engine
from sqlalchemy import text

cedula = input("Cedula: ").strip()
e = get_engine()
conn = e.connect()
r = conn.execute(
    text("SELECT cedula, clave_acceso FROM clientes_suscripcion WHERE cedula = :c"),
    {"c": cedula},
)
row = r.one()
print(f"Cedula: {row[0]}")
print(f"Clave: {row[1]}")
conn.close()
