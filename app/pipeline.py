"""Оркестрация: запрос → поиск → дедупликация → загрузка → извлечение → проверка → скоринг."""

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Awaitable, Callable
from urllib.parse import urlparse

from .cache import TTLCache
from .grounding import ground_facts
from .models import SearchRequest, SearchResponse, SupplierCard, SupplierFacts
from .scoring import pick_recommendation, score_cards, supports_city
from .search import SearchResult, is_blocked

log = logging.getLogger(__name__)

ProgressFn = Callable[[str, int, int], None]


@dataclass
class Deps:
    """Внешние зависимости передаются снаружи, поэтому пайплайн тестируется без сети."""

    search: Callable[[str, int], Awaitable[list[SearchResult]]]
    fetch: Callable[[str], Awaitable[str | None]]
    extract: Callable[[str, str], Awaitable[SupplierFacts | None]]
    cache: TTLCache = field(default_factory=TTLCache)


def domain_of(url: str) -> str:
    host = urlparse(url).netloc.lower()
    return host[4:] if host.startswith("www.") else host


def build_query(req: SearchRequest) -> str:
    parts = [req.query, "поставщики"]
    if req.city:
        parts.append(req.city)
    return " ".join(parts)


async def _process(
    deps: Deps, query: str, domain: str, result: SearchResult, usage: dict[str, int]
) -> SupplierCard | None:
    key = f"card:{result.url}:{query}"
    cached = deps.cache.get(key)
    if cached is not None:
        usage["cache_hits"] += 1
        reason = cached.get("reason", "ок" if cached["card"] is not None else "не похож на поставщика")
        log.info("Сайт %s: %s", result.url, reason)
        return cached["card"]

    card = None
    reason = "недоступен"
    text = await deps.fetch(result.url)
    if text:
        reason = "не похож на поставщика"
        usage["llm_requests"] += 1
        facts = await deps.extract(text, query)
        if facts is not None:
            facts = ground_facts(facts, text)
            if facts.products or facts.company_name or facts.phone or facts.email:
                card = SupplierCard(
                    domain=domain,
                    source_url=result.url,
                    title=result.title,
                    fetched_at=datetime.now(timezone.utc).isoformat(timespec="minutes"),
                    facts=facts,
                )
                reason = "ок"
    log.info("Сайт %s: %s", result.url, reason)
    deps.cache.set(key, {"card": card, "reason": reason})
    return card


async def run_search(req: SearchRequest, deps: Deps, progress: ProgressFn | None = None) -> SearchResponse:
    report = progress or (lambda stage, done, total: None)
    query = build_query(req)
    notes: list[str] = []
    usage = {"search_requests": 0, "llm_requests": 0, "cache_hits": 0}

    report("search", 0, 1)
    results = deps.cache.get(f"search:{query}")
    if results is None:
        results = await deps.search(query, 20)
        usage["search_requests"] += 1
        deps.cache.set(f"search:{query}", results)
    else:
        usage["cache_hits"] += 1

    # Одна страница на домен, без агрегаторов.
    seen: set[str] = set()
    candidates: list[tuple[str, SearchResult]] = []
    for r in results:
        d = domain_of(r.url)
        if not d or is_blocked(d) or d in seen:
            continue
        seen.add(d)
        candidates.append((d, r))
    candidates = candidates[: req.max_results]

    if not candidates:
        notes.append("Поиск не нашёл подходящих сайтов. Попробуйте более общий запрос.")
        return SearchResponse(
            query_used=query, candidates=0, parsed=0, results=[], recommendation=None, notes=notes, usage=usage
        )

    total = len(candidates)
    done = 0
    report("extract", 0, total)

    async def tracked(d: str, r: SearchResult):
        nonlocal done
        card = await _process(deps, req.query, d, r, usage)
        done += 1
        report("extract", done, total)
        return card

    outcomes = await asyncio.gather(*(tracked(d, r) for d, r in candidates))
    extracted_cards = [c for c in outcomes if c is not None]
    cards = [c for c in extracted_cards if supports_city(c.facts, req.city)]

    skipped = total - len(extracted_cards)
    if skipped:
        notes.append(
            f"Не удалось извлечь данные с {skipped} из {total} сайтов: "
            "они недоступны, закрыты robots.txt или не похожи на страницу поставщика."
        )
    excluded_by_region = len(extracted_cards) - len(cards)
    if excluded_by_region:
        notes.append(
            f"Исключено {excluded_by_region} сайтов с явно неподходящим регионом доставки "
            f"для города {req.city}."
        )

    report("scoring", total, total)
    scored = score_cards(cards, city=req.city, weights=req.weights)
    return SearchResponse(
        query_used=query,
        candidates=total,
        parsed=len(cards),
        results=scored,
        recommendation=pick_recommendation(scored),
        notes=notes,
        usage=usage,
    )
