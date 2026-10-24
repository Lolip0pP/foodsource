"""Размеченные примеры страниц для оценки извлечения.

ВАЖНО: тексты синтетические (написаны вручную по типичным страницам поставщиков), домены и телефоны
вымышленные. Набор нужен для проверки логики и сравнения версий, а не как оценка качества на реальных
сайтах: для неё нужно разметить настоящие страницы.

expected: поля, которые человек видит на странице. None / [] означает «на странице этого нет».
"""

DATASET = [
    {
        "id": "flour-full",
        "text": (
            "ООО «Альфа Мука». Мука пшеничная в/с и 1 сорт. Цена от 38 руб/кг. Минимальный заказ 500 кг. "
            "Доставка по России за 3 дня. Сертификаты ХАССП и ISO 22000. "
            "Тел. +7 (843) 123-45-67, e-mail: opt@alfamuka.example"
        ),
        "expected": {
            "company_name": "Альфа Мука",
            "phone": "8431234567",
            "email": "opt@alfamuka.example",
            "certificates": ["ХАССП", "ISO 22000"],
            "min_order_qty": 500,
            "min_order_unit": "кг",
            "price_per_unit": 38,
            "price_unit": "кг",
            "delivery_days": 3,
        },
    },
    {
        "id": "milk-halal",
        "text": (
            "Молочная ферма «Татарстан Молоко». Молоко 3,2%, цена 78 рублей за литр, заказ от 300 литров. "
            "Привезём в течение 2 дней. Продукция с сертификатом Меркурий, халяльная продукция сертифицирована. "
            "Звоните: 8 (800) 555-35-35"
        ),
        "expected": {
            "company_name": "Татарстан Молоко",
            "phone": "8005553535",
            "email": None,
            "certificates": ["Меркурий", "Халяль"],
            "min_order_qty": 300,
            "min_order_unit": "л",
            "price_per_unit": 78,
            "price_unit": "л",
            "delivery_days": 2,
        },
    },
    {
        "id": "bakery-no-certs",
        "text": (
            "Пекарня «Тёплый хлеб» печёт булочки и багеты для кафе. Булочка — 65 руб/шт, минимальный заказ 100 шт. "
            "Свяжитесь с нами: +7 495 000-11-01, zakaz@teplyhleb.example"
        ),
        "expected": {
            "company_name": "Тёплый хлеб",
            "phone": "4950001101",
            "email": "zakaz@teplyhleb.example",
            "certificates": [],
            "min_order_qty": 100,
            "min_order_unit": "шт",
            "price_per_unit": 65,
            "price_unit": "шт",
            "delivery_days": None,
        },
    },
    {
        "id": "packaging",
        "text": (
            "ПакПро — пластиковые контейнеры ПЭТ для еды. Цена 7,5 руб/шт, минимальная партия 5000 шт. "
            "Сертификат ISO 9001. Срок доставки 5 дней. +7 495 000-22-02 info@pakpro.example"
        ),
        "expected": {
            "company_name": "ПакПро",
            "phone": "4950002202",
            "email": "info@pakpro.example",
            "certificates": ["ISO 9001"],
            "min_order_qty": 5000,
            "min_order_unit": "шт",
            "price_per_unit": 7.5,
            "price_unit": "шт",
            "delivery_days": 5,
        },
    },
    {
        "id": "veg-organic",
        "text": (
            "Агрохозяйство «Кубань Органик». Овощи: картофель, морковь, свёкла. Органик-сертификат на всю продукцию. "
            "Цена картофеля 46 руб/кг, от 800 кг. Телефон 8 861 000-33-03."
        ),
        "expected": {
            "company_name": "Кубань Органик",
            "phone": "8610003303",
            "email": None,
            "certificates": ["Органик"],
            "min_order_qty": 800,
            "min_order_unit": "кг",
            "price_per_unit": 46,
            "price_unit": "кг",
            "delivery_days": None,
        },
    },
    {
        "id": "blog-not-supplier",
        "text": (
            "Как выбрать муку для пиццы: 5 советов. Многие мельницы внедряют ХАССП, но на это не стоит "
            "полагаться слепо. Читайте также статьи про закваску и дрожжи. © 2026 Кулинарный блог."
        ),
        "expected": {
            "company_name": None,
            "phone": None,
            "email": None,
            "certificates": [],
            "min_order_qty": None,
            "min_order_unit": None,
            "price_per_unit": None,
            "price_unit": None,
            "delivery_days": None,
        },
    },
    {
        "id": "contacts-only",
        "text": (
            "ООО «Хлебный Дом». Мы производим хлеб и выпечку. Контакты: +7 495 223-18-14, post@hlebdom.example. "
            "Склад 1500 м², работаем с 2005 года. ИНН 7701234567."
        ),
        "expected": {
            "company_name": "Хлебный Дом",
            "phone": "4952231814",
            "email": "post@hlebdom.example",
            "certificates": [],
            "min_order_qty": None,
            "min_order_unit": None,
            "price_per_unit": None,
            "price_unit": None,
            "delivery_days": None,
        },
    },
    {
        "id": "two-phones",
        "text": (
            "Крупяной двор: гречка, рис, пшено. Телефоны: +7 843 111-22-33 и 8 800 100-10-10. "
            "Почта sales@krupa.example. Цена гречки 90 руб/кг, заказ от 1000 кг."
        ),
        "expected": {
            "company_name": "Крупяной двор",
            "phone": "8431112233",
            "email": "sales@krupa.example",
            "certificates": [],
            "min_order_qty": 1000,
            "min_order_unit": "кг",
            "price_per_unit": 90,
            "price_unit": "кг",
            "delivery_days": None,
        },
    },
    {
        "id": "sugar-tons",
        "text": (
            "СахарЮг: сахар-песок. Цена 52 ₽/кг при заказе от 2 тонн. Сертификаты ХАССП, FSSC 22000. "
            "Доставка до 7 дней. Тел. +7 861 000-44-04"
        ),
        "expected": {
            "company_name": "СахарЮг",
            "phone": "8610004404",
            "email": None,
            "certificates": ["ХАССП", "FSSC 22000"],
            "min_order_qty": 2,
            "min_order_unit": "т",
            "price_per_unit": 52,
            "price_unit": "кг",
            "delivery_days": 7,
        },
    },
    {
        "id": "price-on-request",
        "text": (
            "Масложировой комбинат «Подсолнух». Масло подсолнечное рафинированное, цена по запросу. "
            "Сертификаты ISO 22000, Честный знак. Отдел продаж: sales@podsolnuh.example, +7 473 000-55-05."
        ),
        "expected": {
            "company_name": "Подсолнух",
            "phone": "4730005505",
            "email": "sales@podsolnuh.example",
            "certificates": ["ISO 22000", "Честный знак"],
            "min_order_qty": None,
            "min_order_unit": None,
            "price_per_unit": None,
            "price_unit": None,
            "delivery_days": None,
        },
    },
    {
        "id": "fake-lookalike-words",
        "text": (
            "Студия дизайна упаковки. Делаем gifs и motifs для этикеток, консультируем по брендингу. "
            "Почта hello@studio.example"
        ),
        "expected": {
            "company_name": None,
            "phone": None,
            "email": "hello@studio.example",
            "certificates": [],
            "min_order_qty": None,
            "min_order_unit": None,
            "price_per_unit": None,
            "price_unit": None,
            "delivery_days": None,
        },
    },
    {
        "id": "meat-regions",
        "text": (
            "Птицефабрика «Заря». Филе куриное охлаждённое 210 руб/кг, минимальный заказ 1000 кг. "
            "Доставка только по Новосибирской области, на следующий день (1 день). "
            "Сертификаты ХАССП, Меркурий. +7 383 000-77-07"
        ),
        "expected": {
            "company_name": "Заря",
            "phone": "3830007707",
            "email": None,
            "certificates": ["ХАССП", "Меркурий"],
            "min_order_qty": 1000,
            "min_order_unit": "кг",
            "price_per_unit": 210,
            "price_unit": "кг",
            "delivery_days": 1,
        },
    },
]
