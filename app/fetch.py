"""Загрузка страниц с учётом robots.txt и извлечение текста из HTML."""

import re
import urllib.robotparser
from html.parser import HTMLParser
from urllib.parse import urlparse

import httpx

USER_AGENT = "FoodSourceBot/0.1 (prototype; contact: ops@example.com)"
MAX_TEXT_CHARS = 30_000


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

    async def fetch_text(self, url: str) -> str | None:
        if not await self._allowed(url):
            return None
        try:
            r = await self.client.get(url, timeout=8, follow_redirects=True, headers={"User-Agent": USER_AGENT})
        except httpx.HTTPError:
            return None
        if r.status_code != 200 or "html" not in r.headers.get("content-type", "").lower():
            return None
        return html_to_text(r.text[:2_000_000])
