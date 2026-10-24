"""Веб-поиск через Yandex Search API в отложенном (deferred) режиме.

Отложенный режим тарифицируется заметно дешевле синхронного, но результат
приходит не сразу: операция создаётся, затем опрашивается до готовности.
"""

import asyncio
import logging
from collections.abc import Awaitable, Callable
from typing import TypeVar

from pydantic import BaseModel

log = logging.getLogger(__name__)

# Маркетплейсы, справочники, агрегаторы и соцсети: их карточки не являются страницами поставщика.
BLOCKED_DOMAINS = {
    "avito.ru",
    "yandex.ru",
    "2gis.ru",
    "wikipedia.org",
    "youtube.com",
    "vk.com",
    "ozon.ru",
    "wildberries.ru",
    "zoon.ru",
    "yell.ru",
    "pinterest.com",
    "tiu.ru",
    "hh.ru",
    "rusprofile.ru",
    "list-org.com",
    "dzen.ru",
    "market.yandex.ru",
    "regtorg.ru",
    "tradedir.ru",
    "supl.biz",
    "postavshikov.net",
    "alligator.market",
    "optlist.ru",
    "agroserver.ru",
}

RATE_LIMIT_MARKERS = ("resource_exhausted", "rate limit")
T = TypeVar("T")


class SearchResult(BaseModel):
    title: str
    url: str
    snippet: str = ""


def is_blocked(domain: str) -> bool:
    return any(domain == b or domain.endswith("." + b) for b in BLOCKED_DOMAINS)


def make_search_client(folder_id: str, api_key: str):
    from yandex_ai_studio_sdk import AsyncAIStudio

    sdk = AsyncAIStudio(folder_id=folder_id, auth=api_key)
    sdk.setup_default_logging("error")
    return sdk


def is_rate_limit(exc: Exception) -> bool:
    text = f"{type(exc).__name__} {exc}".lower()
    return any(marker in text for marker in RATE_LIMIT_MARKERS)


async def _create_with_retry(make_op: Callable[[], Awaitable[T]], attempts: int = 5) -> T:
    for attempt in range(1, attempts + 1):
        try:
            return await make_op()
        except Exception as exc:
            if not is_rate_limit(exc) or attempt == attempts:
                raise
            delay = 30 * 2 ** (attempt - 1)
            log.warning("Лимит частоты создания поисковой операции, повтор через %d с", delay)
            await asyncio.sleep(delay)
    raise RuntimeError("Создание поисковой операции завершилось без результата")


async def yandex_search(
    sdk,
    query: str,
    count: int = 20,
    *,
    poll_interval: float = 2.0,
    poll_timeout: int = 300,
    create_sem: asyncio.Semaphore | None = None,
) -> list[SearchResult]:
    search = sdk.search_api.web("SEARCH_TYPE_RU").configure(
        family_mode="FAMILY_MODE_MODERATE",
        fix_typo_mode="FIX_TYPO_MODE_ON",
        sort_mode="SORT_MODE_BY_RELEVANCE",
        sort_order="SORT_ORDER_DESC",
        groups_on_page=count,
        group_mode="GROUP_MODE_DEEP",
        docs_in_group=1,
        max_passages=4,
        localization="LOCALIZATION_RU",
    )
    if create_sem is None:
        operation = await _create_with_retry(lambda: search.run_deferred(query, format="parsed"))
    else:
        async with create_sem:
            operation = await _create_with_retry(lambda: search.run_deferred(query, format="parsed"))
    result = await operation.wait(poll_interval=poll_interval, poll_timeout=poll_timeout)

    out: list[SearchResult] = []
    for group in result.groups:
        for doc in group.documents:
            if doc.url:
                out.append(SearchResult(title=doc.title or "", url=doc.url, snippet=" ".join(doc.passages)))
    return out
