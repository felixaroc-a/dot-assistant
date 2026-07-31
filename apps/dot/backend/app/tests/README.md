# Tests del backend DOT (`frontend/backend`)

## Base de datos en pytest

- **No uses** `dot_dev.sqlite` ni `DATABASE_URL` de desarrollo al correr tests.
- `conftest.py` fija `DATABASE_URL=sqlite+pysqlite:///:memory:` y el fixture autouse `_setup_db` crea el esquema **billing + chat** en SQLite en memoria, con `StaticPool`, **por cada test**.
- `ADMIN_API_KEY=test-admin-key` y la cabecera `X-Admin-Key` van alineadas via fixture `admin_api_headers`.
- Archivos SQLite de dev (`dot_dev.sqlite`, `test_dot.db`) están en `.gitignore`; no deben compartirse entre procesos de pytest.

### Paralelismo (`pytest-xdist`)

Con el conftest actual, cada test tiene su propia BD en memoria en el mismo worker. Si necesitas BD en disco (p. ej. health sin tablas chat), usa el fixture `billing_db_file` (directorio `tmp_path` único por test).

**No** ejecutes tests apuntando varios workers al mismo archivo SQLite (`dot_dev.sqlite` o `./test_dot.db`): provoca `database is locked`.

## Comandos

Desde `frontend/backend`:

```powershell
# Provisión USB + pendrive admin + verify
python -m pytest app/tests/test_usb_provisioning_api.py app/tests/test_pendrive_provisioning_admin.py -v

# Suite completa
python -m pytest app/tests -q
```

Variables relevantes (ya las define `conftest.py`; solo override si hace falta):

| Variable | Valor en tests |
|----------|----------------|
| `DOT_ENV` | `testing` |
| `TESTING` | `1` |
| `DATABASE_URL` | `sqlite+pysqlite:///:memory:` |
| `ADMIN_API_KEY` | `test-admin-key` |
| `HARDWARE_TOKEN_PEPPER` | pepper fijo de test |
