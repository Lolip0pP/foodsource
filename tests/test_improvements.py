import asyncio

import httpx

from app.extract import sanitize
from app.fetch import Fetcher, pick_links
from app.grounding import ground_facts
from app.models import SearchRequest, SupplierCard, SupplierFacts
from app.pipeline import build_query
from app.scoring import geo_factor, pick_recommendation, score_cards, supports_city
from evaluation.dataset import DATASET
from evaluation.run_eval import evaluate, predict


def _facts(**kw) -> SupplierFacts:
    return SupplierFacts(**kw)


def _card(domain="a.ru", **kw) -> SupplierCard:
    return SupplierCard(domain=domain, source_url="https://" + domain, fetched_at="t", facts=_facts(**kw))


# ---------- сопоставление городов ----------

def test_city_matching_does_not_match_inside_other_words():
    # «мо» лежит внутри «Смоленская», «нск» внутри «Брянск»: раньше это считалось совпадением
    assert not supports_city(_facts(regions=["Смоленская область"]), "Москва")
    assert not supports_city(_facts(regions=["Брянск"]), "Новосибирск")
    assert geo_factor(_facts(regions=["Смоленская область"]), "Москва") == 0.7


def test_city_matching_still_accepts_real_matches():
    assert supports_city(_facts(regions=["Московская область"]), "Москва")
    assert supports_city(_facts(regions=["Подмосковье", "МО"]), "Москва")
    assert supports_city(_facts(regions=["Ростов-на-Дону"]), "Ростов-на-Дону")
    assert supports_city(_facts(delivery_text="Доставляем по всей России"), "Томск")
    assert supports_city(_facts(delivery_text="Доставка по РФ"), "Томск")
    assert supports_city(_facts(), "Томск")  # неизвестное покрытие не исключаем
    assert geo_factor(_facts(regions=["Татарстан"]), "Казань") == 1.0


# ---------- осторожный балл ----------

def test_thin_data_card_gets_lower_score_and_flag():
    thin = _card("thin.ru", certificates=["ХАССП", "ISO 22000", "Халяль"])  # известен один критерий
    full = _card("full.ru", certificates=["ХАССП", "ISO 22000", "Халяль"], price_per_unit=40, price_unit="кг",
                 min_order_qty=100, min_order_unit="кг", delivery_days=1)
    scored = {s.card.domain: s for s in score_cards([thin, full])}
    assert scored["thin.ru"].low_data is True
    assert scored["full.ru"].low_data is False
    assert scored["thin.ru"].score < 70           # раньше было бы 100
    assert scored["full.ru"].score > scored["thin.ru"].score


def test_recommendation_mentions_low_data():
    text = pick_recommendation(score_cards([_card("thin.ru", certificates=["ХАССП"])]))
    assert "Данных мало" in text


# ---------- проверка сертификатов по границам слов ----------

def test_certificate_mentions_respect_word_boundaries():
    facts = ground_facts(_facts(), "Делаем gifs и motifs для этикеток. Халяльная продукция.")
    assert "IFS" not in (facts.certificates or [])      # IFS внутри gifs/motifs
    assert "Халяль" in facts.certificates               # основа слова «халяльная» засчитывается


# ---------- очистка полей ----------

def test_sanitize_dedupes_products_caps_them_and_normalizes_units():
    data = {"products": ["Мука 50 кг", "мука  50 кг", "Мука 25 кг", "а", "б", "в", "г", "д", "е"],
            "price_per_unit": "808", "price_unit": "₽/кг.", "min_order_unit": " КГ "}
    out = sanitize(data)
    assert out["products"][:2] == ["Мука 50 кг", "Мука 25 кг"]
    assert len(out["products"]) == 6
    assert out["price_unit"] == "кг" and out["min_order_unit"] == "кг"


# ---------- категория ----------

def test_category_is_added_to_search_query():
    q = build_query(SearchRequest(query="мука пшеничная", city="Казань", category="Ингредиенты"))
    assert q == "Ингредиенты мука пшеничная поставщики Казань"
    assert build_query(SearchRequest(query="мука пшеничная")) == "мука пшеничная поставщики"


# ---------- загрузка нескольких страниц ----------

MAIN = """<html><body><h1>Каталог муки</h1><p>Мука в/с</p>
<a href="/kontakty/">Контакты</a><a href="/dostavka">Доставка и оплата</a>
<a href="https://other.example/contacts">Чужой сайт</a><a href="/files/price.pdf">Прайс контакты</a>
<a href="#top">наверх</a><a href="mailto:x@y.example">почта</a></body></html>"""


def _handler(request: httpx.Request) -> httpx.Response:
    html = {"/": MAIN, "/kontakty/": "<p>Телефон +7 495 000-11-01</p>", "/dostavka": "<p>Доставка за 2 дня</p>"}
    if request.url.path in html and request.url.host == "shop.example":
        return httpx.Response(200, text=html[request.url.path], headers={"content-type": "text/html"})
    return httpx.Response(404)


def test_pick_links_keeps_same_site_service_pages_only():
    links = pick_links(MAIN, "https://shop.example/")
    assert links == ["https://shop.example/kontakty/", "https://shop.example/dostavka"]


def test_fetch_site_combines_main_and_service_pages():
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(_handler)) as client:
            return await Fetcher(client).fetch_site("https://shop.example/")

    text = asyncio.run(run())
    assert "Каталог муки" in text and "+7 495 000-11-01" in text and "Доставка за 2 дня" in text
    assert "[страница: https://shop.example/kontakty/]" in text
    assert "other.example" not in text
    assert len(text) <= 12_000


def test_fetch_site_survives_failing_service_page():
    def handler(request):
        if request.url.path == "/":
            return httpx.Response(200, text=MAIN, headers={"content-type": "text/html"})
        return httpx.Response(500)

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await Fetcher(client).fetch_site("https://shop.example/")

    text = asyncio.run(run())
    assert "Каталог муки" in text and "[страница:" not in text


# ---------- оценка извлечения ----------

def test_eval_baseline_contacts_are_exact_and_llm_fields_are_scored():
    async def no_llm(text, query):
        return SupplierFacts()

    preds = asyncio.run(predict(DATASET, no_llm))
    metrics = evaluate(DATASET, preds)
    assert metrics["email"]["precision"] == 1.0 and metrics["email"]["recall"] == 1.0
    assert metrics["phone"]["precision"] == 1.0 and metrics["phone"]["recall"] == 1.0
    assert metrics["price_per_unit"]["recall"] == 0.0     # без LLM цену не достать
    assert metrics["certificates"]["precision"] < 1.0     # упоминание ХАССП в блоге: известная слабость словаря


def test_eval_perfect_predictions_give_perfect_scores():
    preds = [SupplierFacts(**{k: v for k, v in s["expected"].items()}) for s in DATASET]
    metrics = evaluate(DATASET, preds)
    assert all(m["precision"] == 1.0 and m["recall"] == 1.0 for m in metrics.values())
