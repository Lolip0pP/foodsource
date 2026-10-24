"""HTTP-слой.

Переменные окружения: YANDEX_API_KEY, YANDEX_FOLDER_ID, (опц.) YANDEX_SEARCH_API_KEY, YANDEX_MODEL.
"""

import asyncio
import os

import httpx
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from .config import Settings
from .extract import llm_extract, make_llm_client
from .fetch import Fetcher
from .jobs import JobStore
from .models import JobStatus, SearchRequest, SupplierFacts
from .pipeline import Deps
from .search import make_search_client, yandex_search

app = FastAPI(title="FoodSource API", version="0.3.0")
cors_origins = [
    origin.strip()
    for origin in os.getenv(
        "CORS_ORIGINS",
        "http://localhost:5500,http://127.0.0.1:5500",
    ).split(",")
    if origin.strip()
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins,
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type"],
)
app.state.deps = None
app.state.jobs = JobStore()


def build_deps(settings: Settings) -> Deps:
    http = httpx.AsyncClient()
    fetcher = Fetcher(http)
    search_sdk = make_search_client(settings.folder_id, settings.search_api_key)
    llm = make_llm_client(settings.folder_id, settings.api_key)
    sem = asyncio.Semaphore(settings.max_parallel_llm)
    search_sem = asyncio.Semaphore(1)

    async def search(q: str, n: int):
        return await yandex_search(search_sdk, q, n, poll_timeout=int(settings.search_timeout), create_sem=search_sem)

    async def fetch(url: str):
        return await fetcher.fetch_site(url)

    async def extract(text: str, query: str) -> SupplierFacts | None:
        return await llm_extract(
            llm,
            settings.folder_id,
            settings.model,
            text,
            query,
            poll_interval=settings.llm_poll_interval,
            timeout=settings.llm_timeout,
            sem=sem,
        )

    return Deps(search=search, fetch=fetch, extract=extract)


def get_deps() -> Deps:
    if app.state.deps is None:
        settings = Settings.from_env()
        missing = settings.missing()
        if missing:
            raise HTTPException(503, "Не заданы переменные окружения: " + ", ".join(missing))
        app.state.deps = build_deps(settings)
    return app.state.deps


@app.get("/health")
async def health():
    s = Settings.from_env()
    return {"ok": True, "configured": not s.missing(), "missing": s.missing()}


@app.post("/search", response_model=JobStatus, status_code=202)
async def create_search(req: SearchRequest):
    return app.state.jobs.submit(req, get_deps())


@app.get("/search/{job_id}", response_model=JobStatus)
async def get_search(job_id: str):
    job = app.state.jobs.get(job_id)
    if job is None:
        raise HTTPException(404, "Задача не найдена или уже удалена из памяти.")
    return job
