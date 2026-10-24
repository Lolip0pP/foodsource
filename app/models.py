from __future__ import annotations

from pydantic import BaseModel, Field


class SupplierFacts(BaseModel):
    """То, что удалось извлечь со страницы. Все поля необязательны: None = не найдено."""

    company_name: str | None = None
    products: list[str] = Field(default_factory=list)
    min_order_qty: float | None = None
    min_order_unit: str | None = None
    price_per_unit: float | None = None
    price_unit: str | None = None
    certificates: list[str] | None = None
    delivery_days: int | None = None
    delivery_text: str | None = None
    regions: list[str] | None = None
    phone: str | None = None
    email: str | None = None
    notes: str | None = None


class SupplierCard(BaseModel):
    domain: str
    source_url: str
    title: str = ""
    fetched_at: str
    facts: SupplierFacts


class ScoredSupplier(BaseModel):
    card: SupplierCard
    score: int
    confidence: float
    low_data: bool = False
    reasons: list[str]
    missing: list[str]
    breakdown: dict[str, float | None]


class SearchRequest(BaseModel):
    query: str = Field(min_length=3, max_length=300, examples=["мука пшеничная в/с"])
    city: str | None = Field(default=None, examples=["Казань"])
    category: str | None = Field(default=None, max_length=60, examples=["Ингредиенты"])
    max_results: int = Field(default=8, ge=1, le=15)
    weights: dict[str, float] | None = None


class SearchResponse(BaseModel):
    query_used: str
    candidates: int
    parsed: int
    results: list[ScoredSupplier]
    recommendation: str | None
    notes: list[str]
    usage: dict[str, int] = Field(default_factory=dict)


class JobStatus(BaseModel):
    job_id: str
    status: str  # queued | running | done | error
    stage: str = ""
    done: int = 0
    total: int = 0
    result: SearchResponse | None = None
    error: str | None = None
