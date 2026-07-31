"""CLI para validar configuración mínima de producción."""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

BACKEND_ROOT = Path(__file__).resolve().parent.parent
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.services.config_preflight import format_preflight_report, run_config_preflight


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Preflight de configuración de DOT backend."
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Falla también cuando hay warnings.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Imprime resultado en JSON.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    load_dotenv(BACKEND_ROOT / ".env", override=False)
    report = run_config_preflight(os.environ)

    if args.json:
        print(json.dumps(report, indent=2, ensure_ascii=False))
    else:
        print(format_preflight_report(report), end="")

    has_errors = bool(report.get("errors"))
    has_warnings = bool(report.get("warnings"))
    if has_errors:
        return 1
    if args.strict and has_warnings:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
