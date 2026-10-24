"""Загрузка страниц с учётом robots.txt и извлечение текста из HTML."""

import asyncio
import re
import urllib.robotparser
from html.parser import HTMLParser
from urllib.parse import urldefrag, urljoin, urlparse

import httpx

USER_AGENT = "FoodSourceBot/0.1 (prototype; contact: ops@example.com)"
MAX_TEXT_CHARS = 30_000
TOTAL_BUDGET = 12_000  # столько текста целиком уходит в LLM
EXTRA_PAGE_CHARS = 2_000
MAX_EXTRA_PAGES = 3

# Страницы, где обычно лежат условия, которых нет в каталоге. Порядок = приоритет.
LINK_GROUPS = (
    ("contacts", re.compile(r"contact|kontakt|контакт|связ|svyaz")),
    ("delivery", re.compile(r"deliver|dostav|доставк|oplat|оплат")),
    ("certs", re.compile(r"sertif|certif|сертиф|quality|kachestv|качеств|licen|лиценз|dokument|документ|deklar|деклар")),
)
SKIP_EXT = re.compile(r"\.(pdf|docx?|xlsx?|zip|rar|jpe?g|png|gif|webp|svg|mp4|css|js)(\?|$)", re.I)


class _TextExtractor(HTMLParser):
    SKIP = {"script", "style", "noscript", "svg"}

    def __init__(self):
        super().__init__()
        self.parts: list[str] = []
        self._skip = 0

    def handle_starttag(self, tag, attrs):
        if tag in self.SKIP:
            self._skip += 1

    def handle_endtag(self, tag):
        if tag in self.SKIP and self._skip:
            self._skip -= 1

    def handle_data(self, data):
        if not self._skip:
            self.parts.append(data)


class _LinkExtractor(HTMLParser):
    def __init__(self):
        super().__init__()
        self.links: list[tuple[str, str]] = []
        self._href: str | None = None
        self._text: list[str] = []

    def handle_starttag(self, tag, attrs):
        if tag == "a":
            self._href = dict(attrs).get("href")
            self._text = []

    def handle_data(self, data):
        if self._href is not None:
            self._text.append(data)

    def handle_endtag(self, tag):
        if tag == "a" and self._href is not None:
            self.links.append((self._href, " ".join(self._text).strip()))
            self._href = None


def _host(url: str) -> str:
    host = urlparse(url).netloc.lower()
    return host[4:] if host.startswith("www.") else host


def pick_links(html: str, base_url: str, limit: int = MAX_EXTRA_PAGES) -> list[str]:
    """Выбирает ссылки на контакты, доставку и сертификаты того же сайта (по одной на группу)."""
    parser = _LinkExtractor()
    try:
        parser.feed(html)
    except Exception:  # битая разметка не должна ронять обработку сайта
        return []
    base_clean = urldefrag(base_url)[0].rstrip("/")
    chosen: dict[str, str] = {}
    for href, text in parser.links:
        if not href or href.startswith(("#", "mailto:", "tel:", "javascript:")):
            continue
        url = urldefrag(urljoin(base_url, href))[0]
        parsed = urlparse(url)
        if parsed.scheme not in ("http", "https") or _host(url) != _host(base_url) or SKIP_EXT.search(url):
            continue
        if url.rstrip("/") == base_clean:
            continue
        haystack = f"{parsed.path} {text}".lower()
        for group, pattern in LINK_GROUPS:
            if group not in chosen and pattern.search(haystack):
                chosen[group] = url
                break
    return [chosen[g] for g, _ in LINK_GROUPS if g in chosen][:limit]


def html_to_text(html: str) -> str:
    parser = _TextExtractor()
    parser.feed(html)
    text = re.sub(r"\s+", " ", " ".join(parser.parts)).strip()
    return text[:MAX_TEXT_CHARS]


class Fetcher:
    def __init__(self, client: httpx.AsyncClient):
        self.client = client
        self._robots: dict[str, urllib.robotparser.RobotFileParser] = {}

    async def _allowed(self, url: str) -> bool:
        parsed = urlparse(url)
        origin = f"{parsed.scheme}://{parsed.netloc}"
        if origin not in self._robots:
            rp = urllib.robotparser.RobotFileParser()
            lines: list[str] = []
            try:
                r = await self.client.get(origin + "/robots.txt", timeout=5, follow_redirects=True)
                if r.status_code == 200:
                    lines = r.text.splitlines()
            except httpx.HTTPError:
                lines = []
            rp.parse(lines)
            self._robots[origin] = rp
        return self._robots[origin].can_fetch(USER_AGENT, url)

    async def _get_html(self, url: str) -> str | None:
        if not await self._allowed(url):
            return None
        try:
            r = await self.client.get(url, timeout=8, follow_redirects=True, headers={"User-Agent": USER_AGENT})
        except httpx.HTTPError:
            return None
        if r.status_code != 200 or "html" not in r.headers.get("content-type", "").lower():
            return None
        return r.text[:2_000_000]

    async def fetch_text(self, url: str) -> str | None:
        html = await self._get_html(url)
        return html_to_text(html) if html is not None else None

    async def fetch_site(self, url: str) -> str | None:
        """Главная страница плюс до 3 служебных (контакты, доставка, сертификаты) одним текстом.

        Служебные страницы нужны, потому что в каталоге обычно нет контактов и условий доставки.
        Лишние страницы не обязательны: при их недоступности остаётся текст первой страницы.
        """
        html = await self._get_html(url)
        if html is None:
            return None
        links = pick_links(html, url)

        async def safe(u: str) -> str | None:
            try:
                return await self.fetch_text(u)
            except Exception:
                return None

        extras = await asyncio.gather(*(safe(u) for u in links)) if links else []
        parts = [(u, t[:EXTRA_PAGE_CHARS]) for u, t in zip(links, extras) if t]
        main_budget = TOTAL_BUDGET - EXTRA_PAGE_CHARS * len(parts)
        text = html_to_text(html)[:main_budget]
        for u, t in parts:
            text += f"\n\n[страница: {u}]\n{t}"
        return text
