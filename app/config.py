"""Настройки из переменных окружения.

Один ключ на всё: YANDEX_API_KEY. Если для Search API нужен отдельный ключ
(ключ с областью yc.search-api.execute), задайте YANDEX_SEARCH_API_KEY.
"""

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(_PROJECT_ROOT / ".env")


@dataclass(frozen=True)
class Settings:
    folder_id: str
    api_key: str
    search_api_key: str
    model: str
    llm_poll_interval: float
    llm_timeout: float
    search_timeout: float
    max_parallel_llm: int

    @classmethod
    def from_env(cls) -> "Settings":
        key = os.getenv("YANDEX_API_KEY", "")
        return cls(
            folder_id=os.getenv("YANDEX_FOLDER_ID", ""),
            api_key=key,
            search_api_key=os.getenv("YANDEX_SEARCH_API_KEY") or key,
            model=os.getenv("YANDEX_MODEL", "yandexgpt-5-lite/latest"),
            llm_poll_interval=float(os.getenv("LLM_POLL_INTERVAL", "3")),
            llm_timeout=float(os.getenv("LLM_TIMEOUT", "600")),
            search_timeout=float(os.getenv("SEARCH_TIMEOUT", "300")),
            max_parallel_llm=int(os.getenv("MAX_PARALLEL_LLM", "5")),
        )

    def missing(self) -> list[str]:
        out = []
        if not self.folder_id:
            out.append("YANDEX_FOLDER_ID")
        if not self.api_key:
            out.append("YANDEX_API_KEY")
        return out
