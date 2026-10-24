"""Извлечение структурированной карточки поставщика с помощью LLM."""

import asyncio
import json
import re
import time
import logging

from .models import SupplierFacts

SYSTEM_PROMPT = """Ты извлекаешь данные о поставщике продуктов питания из текста веб-страницы.
Верни ТОЛЬКО JSON-объект, без пояснений и без markdown. Ключи:
company_name, products (список строк), min_order_qty (число), min_order_unit,
price_per_unit (число), price_unit, certificates (список названий, как на странице),
delivery_days (целое число дней), delivery_text, regions (список), phone, email, notes.
Правила:
- Если значения нет на странице, ставь null (для списков — []). Не выдумывай и не оценивай.
- Бери только то, что написано в тексте.
- Если страница не похожа на страницу поставщика или производителя, верни
  {"company_name": null, "products": []}."""

NUMERIC = ("min_order_qty", "price_per_unit")

log = logging.getLogger(__name__)


def _first_number(value) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    m = re.search(r"\d+(?:[.,]\d+)?", str(value))
    return float(m.group().replace(",", ".")) if m else None


def sanitize(data: dict) -> dict:
    """Приводит типичные отклонения LLM ('от 500 кг', строка вместо списка) к схеме."""
    out = dict(data)
    for key in NUMERIC:
        out[key] = _first_number(out.get(key))
    days = _first_number(out.get("delivery_days"))
    out["delivery_days"] = int(round(days)) if days is not None else None
    for key in ("products", "certificates", "regions"):
        val = out.get(key)
        if isinstance(val, str):
            out[key] = [val]
        elif val is None and key != "certificates":
            out[key] = []
    return out


def parse_facts(text: str) -> SupplierFacts | None:
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end <= start:
        return None
    try:
        data = json.loads(text[start : end + 1])
        return SupplierFacts.model_validate(sanitize(data))
    except (ValueError, TypeError):
        return None


YANDEX_LLM_BASE_URL = "https://ai.api.cloud.yandex.net/v1"
PENDING = {"queued", "in_progress"}


def make_llm_client(folder_id: str, api_key: str):
    import openai

    return openai.AsyncOpenAI(api_key=api_key, base_url=YANDEX_LLM_BASE_URL, project=folder_id)


async def llm_extract(
    client,
    folder_id: str,
    model: str,
    page_text: str,
    query: str,
    *,
    poll_interval: float = 3.0,
    timeout: float = 600.0,
    sem: asyncio.Semaphore | None = None,
) -> SupplierFacts | None:
    """Асинхронный (background) запрос к YandexGPT: создаём задачу и опрашиваем статус.

    Фоновый режим дешевле синхронного, но ответ приходит дольше.
    """

    async def _run() -> SupplierFacts | None:
        resp = await client.responses.create(
            model=f"gpt://{folder_id}/{model}",
            temperature=0,
            instructions=SYSTEM_PROMPT,
            input=f"Запрос пользователя: {query}\n\nТекст страницы:\n{page_text[:12000]}",
            max_output_tokens=800,
            background=True,
        )
        deadline = time.monotonic() + timeout
        while resp.status in PENDING:
            if time.monotonic() > deadline:
                return None
            await asyncio.sleep(poll_interval)
            resp = await client.responses.retrieve(resp.id)
        if resp.status != "completed":
            return None
        return parse_facts(resp.output_text)

    try:
        if sem is None:
            return await _run()
        async with sem:
            return await _run()
    except Exception:
        log.exception("LLM-запрос не выполнен, сайт пропущен")
        return None
