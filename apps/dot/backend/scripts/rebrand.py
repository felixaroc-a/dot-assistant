"""Script de rebranding: Nordik/Nórdika/Nordika -> DOT en archivos .py del backend."""
import glob
import os
import re

BACKEND_APP = os.path.join(os.path.dirname(__file__), "..", "app")


def rebrand_file(filepath: str) -> bool:
    with open(filepath, "r", encoding="utf-8") as f:
        content = f.read()

    original = content
    basename = os.path.basename(filepath)

    # ---- Grupo 1: Logger names "nordik. -> "dot. ----
    content = content.replace('"nordik.', '"dot.')
    content = content.replace("'nordik.", "'dot.")

    # ---- Grupo 2: Logger names "nordik_ -> "dot_ ----
    content = content.replace('"nordik_', '"dot_')
    content = content.replace("'nordik_", "'dot_")

    # ---- Grupo 3: "nordik- ids -> "dot- ids ----
    content = content.replace('"nordik-', '"dot-')
    content = content.replace("'nordik-", "'dot-")

    # ---- Grupo 4: Variable/field name nordik_env -> dot_env ----
    content = re.sub(r'\bnordik_env\b', 'dot_env', content)

    # ---- Grupo 5: Function name _get_nordik_work_dir -> _get_dot_work_dir ----
    content = content.replace('_get_nordik_work_dir', '_get_dot_work_dir')

    # ---- Grupo 6: Product name Nórdika -> DOT ----
    content = content.replace('Nórdika', 'DOT')

    # ---- Grupo 7: Product name Nordika -> DOT ----
    content = content.replace('Nordika', 'DOT')

    # ---- Grupo 8: Product name "Nordik" -> "DOT" in string literals ----
    # These handle "Nordik API", "Nordik IA", etc.
    content = content.replace('"Nordik API"', '"DOT API"')
    content = content.replace("'Nordik API'", "'DOT API'")
    content = content.replace('"nordik.api"', '"dot.api"')
    content = content.replace("'nordik.api'", "'dot.api'")

    # "Nordik" as standalone word in strings
    content = content.replace('"Nordik ' , '"DOT ')
    content = content.replace("'Nordik ", "'DOT ")

    # "Nordik." at end of string
    content = content.replace('"Nordik."', '"DOT."')
    content = content.replace("'Nordik.'", "'DOT.'")
    content = content.replace('"Nordik"', '"DOT"')
    content = content.replace("'Nordik'", "'DOT'")

    # "Nordik Trabajos" -> "DOT Trabajos" (every form)
    content = content.replace('"Nordik Trabajos"', '"DOT Trabajos"')
    content = content.replace("'Nordik Trabajos'", "'DOT Trabajos'")
    content = content.replace('/ "Nordik Trabajos"', '/ "DOT Trabajos"')

    # "Nordik IA" -> "DOT"
    content = content.replace('"Nordik IA"', '"DOT"')
    content = content.replace("'Nordik IA'", "'DOT'")
    content = content.replace('"Nordik IA', '"DOT')
    content = content.replace("'Nordik IA", "'DOT")
    # Non-string references to Nordik IA
    content = content.replace('Nordik IA - ', 'DOT - ')
    content = content.replace('por Nordik IA', 'por DOT')
    content = content.replace('por Nordik IA ', 'por DOT ')

    # "Nordik no fusiona" -> "DOT no fusiona"
    content = content.replace('Nordik no fusiona', 'DOT no fusiona')

    # ---- Grupo 9: Specific file-only replacements ----
    # services/openclaw_adapter.py
    content = content.replace(
        'puente entre Nordik y las capacidades',
        'puente entre DOT y las capacidades'
    )
    # services/ai_provider.py
    content = content.replace(
        'Proveedor de IA para Nordik',
        'Proveedor de IA para DOT'
    )
    # services/automation_scheduler.py
    content = content.replace(
        'motor de automatizaciones de Nordik',
        'motor de automatizaciones de DOT'
    )
    content = content.replace(
        'Mensaje desde Nordik',
        'Mensaje desde DOT'
    )
    content = content.replace(
        'Automatizacion ejecutada desde Nordik',
        'Automatizacion ejecutada desde DOT'
    )
    content = content.replace(
        'Evento Nordik',
        'Evento DOT'
    )
    # services/pendrive_service.py
    content = content.replace(
        'verificacion server-side de pendrives Nordik',
        'verificacion server-side de pendrives DOT'
    )
    # routers/pendrive.py
    content = content.replace(
        'Router de verificacion server-side de pendrives Nordik',
        'Router de verificacion server-side de pendrives DOT'
    )
    # services/whatsapp_link.py
    content = content.replace(
        'Servicio de vinculacion WhatsApp para el cliente Nordik',
        'Servicio de vinculacion WhatsApp para el cliente DOT'
    )
    content = content.replace(
        'Canal WhatsApp cliente (Nordik)',
        'Canal WhatsApp cliente (DOT)'
    )
    # services/web_search.py
    content = content.replace(
        'para Nordik IA usando DuckDuckGo',
        'para DOT usando DuckDuckGo'
    )
    # services/gmail_service.py
    content = content.replace(
        'para automatizaciones de Nordik',
        'para automatizaciones de DOT'
    )
    # services/whatsapp_intent.py
    content = content.replace(
        'mensajes de WhatsApp para Nordik',
        'mensajes de WhatsApp para DOT'
    )
    # routers/whatsapp_channel.py
    content = content.replace(
        'canal WhatsApp del cliente Nordik',
        'canal WhatsApp del cliente DOT'
    )

    # ---- Grupo 10: Error message with NORDIK_ENV=production -> DOT_ENV=production ----
    content = content.replace(
        'NORDIK_ENV=production.',
        'DOT_ENV=production.'
    )

    # ---- Grupo 11: Meta/config keys ----
    content = content.replace('"nordik_env":', '"dot_env":')
    content = content.replace("'nordik_env':", "'dot_env':")

    # ---- Grupo 12: env var key in get() calls ----
    content = content.replace('get("NORDIK_ENV")', 'get("DOT_ENV")')
    content = content.replace("get('NORDIK_ENV')", "get('DOT_ENV')")

    # ---- Grupo 13: os.environ references ----
    content = content.replace('os.environ["NORDIK_ENV"]', 'os.environ["DOT_ENV"]')
    content = content.replace("os.environ['NORDIK_ENV']", "os.environ['DOT_ENV']")

    # ---- Grupo 14: .env.example comment in tests/README.md style ----
    content = content.replace('`NORDIK_ENV`', '`DOT_ENV`')

    # ---- Grupo 15: Test data display name ----
    content = content.replace('"Ana Nordik"', '"Ana DOT"')
    content = content.replace("'Ana Nordik'", "'Ana DOT'")

    if content != original:
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(content)
        print(f"  OK {basename}")
        return True
    return False


def main():
    py_files = glob.glob(os.path.join(BACKEND_APP, "**/*.py"), recursive=True)
    changed = 0
    for fp in sorted(py_files):
        if rebrand_file(fp):
            changed += 1
    print(f"\nArchivos modificados: {changed}")


if __name__ == "__main__":
    main()
