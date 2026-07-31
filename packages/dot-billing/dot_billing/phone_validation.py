"""Validación de números de teléfono para Latinoamérica (enfoque Venezuela)."""
from __future__ import annotations

import re

# Prefijos de operadoras venezolanas
VE_OPERATOR_PREFIXES = {"412", "414", "416", "424", "426", "412"}

# Patrón Venezuela: +58 o 0058 o 58, seguido de 3 dígitos operadora + 7 dígitos
VE_PATTERN = re.compile(r"^(?:\+?58|0058)?(0)?(41[246]|42[46])\d{7}$")
# Normalizado: 58412XXXXXXX (sin +, sin 0)
VE_INTERNATIONAL_PATTERN = re.compile(r"^58(41[246]|42[46])\d{7}$")

# Patrón general para números que reconocemos
INTERNATIONAL_PHONE_PATTERN = re.compile(r"^\+?\d{7,15}$")


def normalize_phone(phone: str) -> str:
    """Normaliza un número de teléfono a formato internacional sin +.

    Ejemplos:
        "0412-1234567" -> "584121234567"
        "+584121234567" -> "584121234567"
        "584121234567" -> "584121234567"
    """
    clean = re.sub(r"[^\d+]", "", phone.strip())
    if clean.startswith("+"):
        return clean[1:]  # Quitar el +
    if clean.startswith("0058"):
        return "58" + clean[4:]
    if clean.startswith("0") and len(clean) == 11:
        return "58" + clean[1:]
    return clean


def is_valid_venezuelan_phone(phone: str) -> bool:
    """Valida que un número sea un teléfono venezolano válido."""
    normalized = normalize_phone(phone)
    return bool(VE_INTERNATIONAL_PATTERN.match(normalized))


def is_valid_phone(phone: str) -> bool:
    """Valida que un número de teléfono tenga formato aceptable."""
    if not phone or not phone.strip():
        return False
    clean = re.sub(r"[\s\-\(\)\.]", "", phone.strip())
    return bool(INTERNATIONAL_PHONE_PATTERN.match(clean))


def format_phone_venezuelan(phone: str) -> str:
    """Formatea un número venezolano para mostrar (0XXX-XXXXXXX)."""
    normalized = normalize_phone(phone)
    # normalized = 58412XXXXXXX
    if normalized.startswith("58") and len(normalized) == 12:
        operator = normalized[2:5]
        number = normalized[5:]
        return f"0{operator}-{number}"
    return phone
