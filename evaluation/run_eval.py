"""Оценка качества извлечения: точность и полнота по полям.

Без ключей работает базовый вариант (только проверка по тексту: email, телефон, словарь сертификатов).
С ключами (YANDEX_API_KEY, YANDEX_FOLDER_ID) извлечение выполняет YandexGPT, как в сервисе:

    python -m evaluation.run_eval
"""

import asyncio
import re
import sys

from app.grounding import ground_facts
from app.models import SupplierFacts

from .dataset import DATASET

SCALAR_FIELDS = (
    "company_name",
    "phone",
    "email",
    "min_order_qty",
    "min_order_unit",
    "price_per_unit",
    "price_unit",
    "delivery_days",
)
LIST_FIELDS = ("certificates",)
FIELDS = SCALAR_FIELDS + LIST_FIELDS


def _name(v: str | None) -> str:
    return re.sub(r"[«»\"'.,]|\b(ооо|оао|зао|ао|ип)\b", "", (v or "").lower()).replace("ё", "е").strip()


def _same(field: str, got, exp) -> bool:
    if field == "company_name":
        g, e = _name(got), _name(exp)
        return bool(g and e and (e in g or g in e))
    if field == "phone":
        return re.sub(r"\D", "", str(got))[-10:] == re.sub(r"\D", "", str(exp))[-10:]
    if field in ("email", "min_order_unit", "price_unit"):
        return str(got).strip().lower() == str(exp).strip().lower()
    return abs(float(got) - float(exp)) < 1e-6


def evaluate(samples: list[dict], predictions: list[SupplierFacts]) -> dict[str, dict[str, float]]:
    """Возвращает по каждому полю precision, recall, f1 и support (число ожидаемых значений)."""
    counts = {f: {"tp": 0, "fp": 0, "fn": 0, "support": 0} for f in FIELDS}
    for sample, pred in zip(samples, predictions):
        exp = sample["expected"]
        for f in SCALAR_FIELDS:
            e, g = exp.get(f), getattr(pred, f)
            c = counts[f]
            c["support"] += e is not None
            if g is not None and e is not None and _same(f, g, e):
                c["tp"] += 1
            else:
                c["fp"] += g is not None
                c["fn"] += e is not None
        for f in LIST_FIELDS:
            e = {x.lower() for x in exp.get(f) or []}
            g = {x.lower() for x in getattr(pred, f) or []}
            c = counts[f]
            c["support"] += len(e)
            c["tp"] += len(e & g)
            c["fp"] += len(g - e)
            c["fn"] += len(e - g)
    out = {}
    for f, c in counts.items():
        p = c["tp"] / (c["tp"] + c["fp"]) if c["tp"] + c["fp"] else 1.0
        r = c["tp"] / (c["tp"] + c["fn"]) if c["tp"] + c["fn"] else 1.0
        out[f] = {
            "precision": round(p, 2),
            "recall": round(r, 2),
            "f1": round(2 * p * r / (p + r), 2) if p + r else 0.0,
            "support": c["support"],
        }
    return out


async def predict(samples: list[dict], extract) -> list[SupplierFacts]:
    """extract(text, query) -> SupplierFacts | None; результат дополнительно проходит проверку по тексту."""
    sem = asyncio.Semaphore(5)

    async def one(sample):
        async with sem:
            facts = await extract(sample["text"], "поставщик") or SupplierFacts()
        return ground_facts(facts, sample["text"])

    return await asyncio.gather(*(one(s) for s in samples))


def format_table(metrics: dict[str, dict[str, float]]) -> str:
    lines = [f"{'поле':<16}{'precision':>10}{'recall':>8}{'f1':>6}{'n':>4}"]
    for f, m in metrics.items():
        lines.append(f"{f:<16}{m['precision']:>10.2f}{m['recall']:>8.2f}{m['f1']:>6.2f}{m['support']:>4}")
    return "\n".join(lines)


async def _main() -> None:
    from app.config import Settings
    from app.extract import llm_extract, make_llm_client

    settings = Settings.from_env()
    if settings.missing():
        print("Ключи не заданы: считаю базовый вариант (только проверка по тексту, без LLM).\n")

        async def extract(text, query):
            return SupplierFacts()

    else:
        print(f"Извлечение через {settings.model}\n")
        client = make_llm_client(settings.folder_id, settings.api_key)

        async def extract(text, query):
            return await llm_extract(
                client,
                settings.folder_id,
                settings.model,
                text,
                query,
                poll_interval=settings.llm_poll_interval,
                timeout=settings.llm_timeout,
            )

    preds = await predict(DATASET, extract)
    print(format_table(evaluate(DATASET, preds)))


if __name__ == "__main__":
    try:
        from dotenv import load_dotenv

        load_dotenv()
    except ImportError:
        pass
    asyncio.run(_main())
    sys.exit(0)
