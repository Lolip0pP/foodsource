import asyncio
import time
from types import SimpleNamespace

from fastapi.testclient import TestClient

from app.extract import llm_extract, parse_facts
from app.fetch import html_to_text
from app.grounding import ground_facts
from app.main import app
from app.models import SearchRequest, SupplierCard, SupplierFacts
from app.pipeline import Deps, run_search
from app.scoring import score_cards, supports_city
from app.search import SearchResult, is_blocked, yandex_search

ALPHA_HTML = """<html><head><script>var x="ISO 9001";</script></head><body>
<h1>Альфа Фуд</h1><p>Мука пшеничная в/с оптом. Сертификат ХАССП.</p>
<p>Минимальный заказ 500 кг. Доставка по РФ за 2 дня.</p>
<p>Тел. +7 (843) 123-45-67, info@alpha-food.ru</p></body></html>"""

BETA_HTML = "<html><body><h1>Бета Мельница</h1><p>Контакты: +7 495 000-00-00</p></body></html>"

PAGES = {
    "https://www.alpha-food.ru/catalog": ALPHA_HTML,
    "https://alpha-food.ru/contacts": ALPHA_HTML,
    "https://beta-mill.ru/": BETA_HTML,
}


async def fake_search(q, n):
    return [
        SearchResult(title="Альфа", url="https://www.alpha-food.ru/catalog"),
        SearchResult(title="Альфа контакты", url="https://alpha-food.ru/contacts"),
        SearchResult(title="Авито", url="https://www.avito.ru/moka"),
        SearchResult(title="Бета", url="https://beta-mill.ru/"),
    ]


async def fake_fetch(url):
    return html_to_text(PAGES[url]) if url in PAGES else None


async def fake_extract(text, query):
    if "Альфа" in text:
        # LLM «выдумала» email и ISO 9001, которых на странице нет.
        return SupplierFacts(
            company_name="Альфа Фуд",
            products=["мука"],
            min_order_qty=500,
            min_order_unit="кг",
            price_per_unit=40,
            price_unit="кг",
            certificates=["ХАССП", "ISO 9001"],
            delivery_days=2,
            regions=["Татарстан", "РФ"],
            email="sales@fake.example",
        )
    return None  # Бета: не похоже на данные поставщика


def make_deps():
    return Deps(search=fake_search, fetch=fake_fetch, extract=fake_extract)


def test_blocklist_and_dedupe():
    req = SearchRequest(query="мука пшеничная", city="Казань", max_results=8)
    res = asyncio.run(run_search(req, make_deps()))
    assert res.candidates == 2  # авито отфильтрован, второй url альфы схлопнут
    assert res.parsed == 1
    assert res.results[0].card.domain == "alpha-food.ru"
    assert any("Не удалось извлечь" in n for n in res.notes)


def test_blocked_domain_includes_subdomains():
    assert is_blocked("kazan.regtorg.ru")


def test_grounding_drops_hallucinations_and_uses_regex():
    text = html_to_text(ALPHA_HTML)
    facts = ground_facts(fake_extract_sync(), text)
    assert facts.email == "info@alpha-food.ru"  # выдуманный email заменён найденным
    assert "ISO 9001" not in facts.certificates  # выдуманный сертификат удалён
    assert "ХАССП" in facts.certificates
    assert facts.phone and "843" in facts.phone


def fake_extract_sync():
    return asyncio.run(fake_extract("Альфа", ""))


def test_missing_data_lowers_confidence_not_score():
    full = SupplierCard(
        domain="a.ru",
        source_url="u",
        fetched_at="t",
        facts=SupplierFacts(
            min_order_qty=100,
            min_order_unit="кг",
            price_per_unit=40,
            price_unit="кг",
            certificates=["ХАССП", "ISO 22000", "Халяль"],
            delivery_days=1,
            regions=["Москва"],
        ),
    )
    empty = SupplierCard(domain="b.ru", source_url="u", fetched_at="t", facts=SupplierFacts(company_name="Б"))
    scored = score_cards([full, empty])
    assert scored[0].card.domain == "a.ru"
    b = next(s for s in scored if s.card.domain == "b.ru")
    assert b.confidence == 0.0 and b.score == 0
    assert "цена" in b.missing and len(b.missing) == 4


def test_city_factor_ranks_local_supplier_higher():
    local = SupplierCard(
        domain="local.ru",
        source_url="u",
        fetched_at="t",
        facts=SupplierFacts(price_per_unit=40, price_unit="кг", regions=["Казань"], delivery_days=2),
    )
    far = SupplierCard(
        domain="far.ru",
        source_url="u",
        fetched_at="t",
        facts=SupplierFacts(price_per_unit=40, price_unit="кг", regions=["Москва"], delivery_days=2),
    )
    scored = score_cards([far, local], city="Казань")
    assert scored[0].card.domain == "local.ru"
    assert scored[0].score > scored[1].score


def test_city_filter_accepts_city_region_and_nationwide_coverage():
    assert supports_city(SupplierFacts(regions=["Казань"]), "Казань")
    assert supports_city(SupplierFacts(regions=["Республика Татарстан"]), "Казань")
    assert supports_city(SupplierFacts(delivery_text="Доставка по всей России"), "Казань")
    assert supports_city(SupplierFacts(), "Казань")
    assert not supports_city(SupplierFacts(regions=["Москва"]), "Казань")


def test_search_excludes_explicitly_wrong_region():
    async def search(q, n):
        return [
            SearchResult(title="Казань", url="https://kazan-supplier.ru/"),
            SearchResult(title="Москва", url="https://moscow-supplier.ru/"),
        ]

    async def fetch(url):
        return url

    async def extract(text, query):
        region = ["Татарстан"] if "kazan" in text else ["Москва"]
        return SupplierFacts(company_name="Поставщик", products=["мука"], regions=region)

    deps = Deps(search=search, fetch=fetch, extract=extract)
    result = asyncio.run(run_search(SearchRequest(query="мука", city="Казань"), deps))
    assert [item.card.domain for item in result.results] == ["kazan-supplier.ru"]
    assert any("Исключено 1 сайтов" in note for note in result.notes)


def test_parse_facts_tolerates_llm_formatting():
    raw = (
        'Вот результат: {"company_name": "X", "products": "мука", "min_order_qty": "от 500 кг", '
        '"delivery_days": "2", "certificates": null}'
    )
    f = parse_facts(raw)
    assert f is not None
    assert f.min_order_qty == 500.0 and f.delivery_days == 2
    assert f.products == ["мука"] and f.certificates is None


def test_parse_facts_rejects_garbage():
    assert parse_facts("не JSON вообще") is None


def test_endpoint_returns_503_without_keys(monkeypatch):
    for k in ("YANDEX_API_KEY", "YANDEX_FOLDER_ID", "YANDEX_SEARCH_API_KEY"):
        monkeypatch.setenv(k, "")
    app.state.deps = None
    client = TestClient(app)
    r = client.post("/search", json={"query": "мука"})
    assert r.status_code == 503 and "YANDEX_API_KEY" in r.json()["detail"]
    h = client.get("/health").json()
    assert h["ok"] is True and h["configured"] is False


def test_job_lifecycle_and_usage_counters():
    app.state.deps = make_deps()
    with TestClient(app) as client:
        r = client.post("/search", json={"query": "мука пшеничная", "city": "Казань"})
        assert r.status_code == 202
        job_id = r.json()["job_id"]
        for _ in range(50):
            job = client.get(f"/search/{job_id}").json()
            if job["status"] in ("done", "error"):
                break
            time.sleep(0.05)
        assert job["status"] == "done", job
        res = job["result"]
        assert res["parsed"] == 1
        assert res["usage"]["search_requests"] == 1  # один отложенный поисковый запрос
        assert res["usage"]["llm_requests"] == 2  # по одному на каждый непустой сайт
        assert client.get("/search/unknown").status_code == 404
    app.state.deps = None


def test_second_identical_search_uses_cache():
    deps = make_deps()
    req = SearchRequest(query="мука пшеничная", city="Казань")
    asyncio.run(run_search(req, deps))
    second = asyncio.run(run_search(req, deps))
    assert second.usage["search_requests"] == 0 and second.usage["llm_requests"] == 0
    assert second.usage["cache_hits"] >= 2


class _Resp(SimpleNamespace):
    pass


class FakeResponses:
    """Имитирует background-режим: сначала queued, потом in_progress, потом completed."""

    def __init__(self, final_status="completed", text='{"company_name": "X", "products": ["мука"]}'):
        self.polls = 0
        self.final_status = final_status
        self.text = text
        self.created_kwargs = None

    async def create(self, **kwargs):
        self.created_kwargs = kwargs
        return _Resp(id="r1", status="queued", output_text="")

    async def retrieve(self, rid):
        self.polls += 1
        status = "in_progress" if self.polls < 2 else self.final_status
        return _Resp(id=rid, status=status, output_text=self.text if status == "completed" else "")


def test_llm_extract_polls_background_response():
    client = SimpleNamespace(responses=FakeResponses())
    facts = asyncio.run(
        llm_extract(client, "b1gf", "yandexgpt-5-lite/latest", "текст", "мука", poll_interval=0.01, timeout=5)
    )
    assert facts is not None and facts.company_name == "X"
    kw = client.responses.created_kwargs
    assert kw["background"] is True
    assert kw["model"] == "gpt://b1gf/yandexgpt-5-lite/latest"
    assert client.responses.polls == 2


def test_llm_extract_returns_none_on_failed_or_timeout():
    failed = SimpleNamespace(responses=FakeResponses(final_status="failed"))
    assert asyncio.run(llm_extract(failed, "f", "m", "t", "q", poll_interval=0.01, timeout=5)) is None

    class Stuck(FakeResponses):
        async def retrieve(self, rid):
            return _Resp(id=rid, status="in_progress", output_text="")

    stuck = SimpleNamespace(responses=Stuck())
    assert asyncio.run(llm_extract(stuck, "f", "m", "t", "q", poll_interval=0.01, timeout=0.05)) is None


def test_llm_extract_swallows_api_errors():
    class Boom:
        async def create(self, **kw):
            raise RuntimeError("quota")

    assert asyncio.run(llm_extract(SimpleNamespace(responses=Boom()), "f", "m", "t", "q")) is None


def test_yandex_search_maps_deferred_result():
    doc = SimpleNamespace(url="https://alpha-food.ru/", title="Альфа", passages=("мука", "оптом"))
    nourl = SimpleNamespace(url=None, title="x", passages=())
    result = SimpleNamespace(groups=[SimpleNamespace(documents=[doc]), SimpleNamespace(documents=[nourl])])

    class Op:
        async def wait(self, **kw):
            Op.kw = kw
            return result

    class Search:
        def configure(self, **kw):
            Search.cfg = kw
            return self

        async def run_deferred(self, q, format):
            Search.q, Search.fmt = q, format
            return Op()

    sdk = SimpleNamespace(search_api=SimpleNamespace(web=lambda t: Search()))
    out = asyncio.run(yandex_search(sdk, "мука", 10, poll_interval=0.1, poll_timeout=30))
    assert [r.url for r in out] == ["https://alpha-food.ru/"] and out[0].snippet == "мука оптом"
    assert Search.fmt == "parsed" and Search.cfg["groups_on_page"] == 10
    assert Search.cfg["sort_order"] == "SORT_ORDER_DESC"
    assert Search.cfg["max_passages"] == 4
    assert Op.kw == {"poll_interval": 0.1, "poll_timeout": 30}


def test_yandex_search_retries_rate_limit(monkeypatch):
    class Op:
        async def wait(self, **kw):
            return SimpleNamespace(groups=[])

    class Search:
        attempts = 0

        def configure(self, **kw):
            return self

        async def run_deferred(self, q, format):
            self.attempts += 1
            if self.attempts == 1:
                raise RuntimeError("RESOURCE_EXHAUSTED")
            return Op()

    async def no_sleep(_delay):
        return None

    monkeypatch.setattr("app.search.asyncio.sleep", no_sleep)
    search = Search()
    sdk = SimpleNamespace(search_api=SimpleNamespace(web=lambda _: search))
    out = asyncio.run(yandex_search(sdk, "мука"))

    assert out == []
    assert search.attempts == 2
