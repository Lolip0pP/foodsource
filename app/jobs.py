"""Очередь задач в памяти.

Отложенные режимы поиска и LLM отвечают с задержкой, поэтому запрос пользователя
превращается в задачу: POST возвращает job_id сразу, результат забирается через GET.
В проде заменить на Redis/очередь и воркеры.
"""

import asyncio
import uuid
from collections import OrderedDict

from .models import JobStatus, SearchRequest
from .pipeline import Deps, run_search

MAX_JOBS = 200


class JobStore:
    def __init__(self) -> None:
        self._jobs: OrderedDict[str, JobStatus] = OrderedDict()
        self._tasks: set[asyncio.Task] = set()

    def get(self, job_id: str) -> JobStatus | None:
        return self._jobs.get(job_id)

    def submit(self, req: SearchRequest, deps: Deps) -> JobStatus:
        job = JobStatus(job_id=uuid.uuid4().hex[:12], status="queued")
        self._jobs[job.job_id] = job
        while len(self._jobs) > MAX_JOBS:
            self._jobs.popitem(last=False)
        task = asyncio.create_task(self._run(job, req, deps))
        self._tasks.add(task)  # держим ссылку, иначе задачу может собрать GC
        task.add_done_callback(self._tasks.discard)
        return job

    async def _run(self, job: JobStatus, req: SearchRequest, deps: Deps) -> None:
        job.status = "running"

        def progress(stage: str, done: int, total: int) -> None:
            job.stage, job.done, job.total = stage, done, total

        try:
            job.result = await run_search(req, deps, progress)
            job.status = "done"
        except Exception as exc:  # noqa: BLE001
            job.status = "error"
            job.error = f"{type(exc).__name__}: {exc}"
