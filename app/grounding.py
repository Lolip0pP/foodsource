"""Проверка того, что извлечённое действительно есть на странице.

LLM может выдумать email или сертификат. Поэтому контакты и сертификаты
принимаются только если их можно найти в исходном тексте. Если LLM ничего не
нашла, те же данные ищутся регулярными выражениями, это дешёвая вторая линия.
"""

import re

from .models import SupplierFacts

EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
PHONE_RE = re.compile(r"(?:\+7|\b8)[\s(\-]*\d{3}[\s)\-]*\d{3}[\s\-]*\d{2}[\s\-]*\d{2}")
KNOWN_CERTS = [
    "ХАССП",
    "ISO 22000",
    "ISO 9001",
    "FSSC 22000",
    "IFS",
    "BRC",
    "Халяль",
    "Halal",
    "Органик",
    "Organic",
    "Меркурий",
    "Честный знак",
]


def _digits(s: str) -> str:
    return re.sub(r"\D", "", s)


def ground_facts(facts: SupplierFacts, page_text: str) -> SupplierFacts:
    low = page_text.lower()

    # Email: оставляем только если строка встречается на странице.
    if facts.email and facts.email.lower() not in low:
        facts.email = None
    if not facts.email:
        emails = EMAIL_RE.findall(page_text)
        facts.email = emails[0] if emails else None

    # Телефон: сравниваем последние 10 цифр, чтобы не зависеть от форматирования.
    if facts.phone and _digits(facts.phone)[-10:] not in _digits(page_text):
        facts.phone = None
    if not facts.phone:
        phones = [m.group() for m in PHONE_RE.finditer(page_text)]
        facts.phone = phones[0] if phones else None

    # Сертификаты: объединяем подтверждённое LLM и найденное по словарю.
    certs = [c for c in (facts.certificates or []) if c.lower() in low]
    for known in KNOWN_CERTS:
        if known.lower() in low and known.lower() not in {c.lower() for c in certs}:
            certs.append(known)
    facts.certificates = certs if (certs or facts.certificates is not None) else None
    return facts
