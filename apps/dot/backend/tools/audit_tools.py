"""Auditoria de tools: clasifica reales vs fake."""
from app.application.agent.tools import build_default_registry

REAL_PREFIXES = [
    'gmail_', 'calendar_', 'whatsapp_', 'send_whatsapp',
    'browser_', 'twitter_', 'ml_', 'drive_', 'scraper_',
    'slack_', 'notion_', 'telegram_', 'discord_', 'github_',
    'web_get_weather', 'web_get_news', 'web_currency_convert', 'web_get_stock', 'web_geocode',
    'research_academic_papers', 'monitor_flight_price', 'monitor_job_opening',
    'monitor_news_keyword', 'finance_parse_invoice', 'car_route_optimizer',
    'readFile', 'writeFile', 'listFiles', 'deleteFile',
    'download_url_to_desktop', 'file_search',
    'generate_document', 'generate_spreadsheet', 'read_document', 'read_spreadsheet',
    'translate', 'summarize',
    'data_', 'clipboard_', 'screenshot_', 'system_', 'doc_',
    'web_search', 'web_fetch_page', 'web_translate', 'web_extract_article',
    'web_calculate', 'web_validate_url', 'web_check_website',
    'web_search_images', 'web_url_shorten', 'web_get_timezone',
    'web_reverse_geocode', 'web_get_definitions',
    'auto_create', 'auto_list_active', 'auto_pause', 'auto_resume',
    'auto_get_stats', 'auto_clone', 'auto_suggest_improvement',
    'schedule_', 'monitor_', 'remind_', 'notify_', 'alert_',
    'billing_', 'contact_', 'comm_', 'productivity_',
    'finance_', 'content_', 'security_', 'health_',
    'entertainment_', 'util_',
]

FAKE_MODULE_PREFIXES = [
    'misc_', 'life_', 'legal_', 'travel_', 'home_', 'vehicle_',
    'event_', 'migration_', 'logistics_', 'office_', 'car_',
    'sales_', 'ecom_', 'job_', 'edu_', 'biz_',
]

r = build_default_registry()
specs = list(r.list_specs())
total = len(specs)
real = []
fake = []
unknown = []

for s in specs:
    name = s.name
    is_real = any(name.startswith(p) or name == p for p in REAL_PREFIXES)
    if is_real:
        real.append(name)
        continue
    is_fake = any(name.startswith(p) or name == p for p in FAKE_MODULE_PREFIXES)
    if is_fake:
        fake.append(name)
        continue
    unknown.append(name)

real_pct = round(len(real) / total * 100, 1)
fake_pct = round(len(fake) / total * 100, 1)
unk_pct = round(len(unknown) / total * 100, 1)

print("=" * 60)
print("AUDITORIA DE TOOLS DOT v2")
print("=" * 60)
print()
print(f"TOTAL: {total}")
print(f"REALES (APIs/acciones/bridge): {len(real)} ({real_pct}%)")
print(f"FAKE (texto generado por LLM): {len(fake)} ({fake_pct}%)")
print(f"DESCONOCIDAS:                {len(unknown)} ({unk_pct}%)")
print()

meta = 85
if real_pct >= meta:
    print(f"META {meta}%: CUMPLIDA")
else:
    falta = round(meta - real_pct, 1)
    tools_faltan = round((meta/100 * total) - len(real))
    print(f"META {meta}%: FALTA {falta}% ({tools_faltan} tools)")

print()
print("TOP 20 DESCONOCIDAS:")
for n in unknown[:20]:
    print(f"  - {n}")
