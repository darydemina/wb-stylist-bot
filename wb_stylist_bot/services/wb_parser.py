"""
Парсер товаров с Wildberries.
Использует внутренний API card.wb.ru (не требует ключа, но не публичный).

ВАЖНО: WB периодически меняет структуру URL картинок и шардинг basket-серверов.
Если перестало работать — обновить _get_basket_host() и логику URL.
"""
import re
import logging
from typing import Optional

import httpx

log = logging.getLogger(__name__)

# Регулярки для извлечения артикула
_ARTICLE_PATTERNS = [
    re.compile(r"/catalog/(\d+)/", re.IGNORECASE),
    re.compile(r"wildberries\.ru/.+?(\d{6,12})", re.IGNORECASE),
    re.compile(r"\bnm=(\d+)", re.IGNORECASE),
]


def extract_article(url: str) -> Optional[str]:
    """Извлекает артикул товара из любой ссылки WB."""
    url = url.strip()
    for pattern in _ARTICLE_PATTERNS:
        m = pattern.search(url)
        if m:
            return m.group(1)
    return None


def is_wb_url(text: str) -> bool:
    """Быстрая проверка, что текст содержит ссылку WB."""
    return "wildberries.ru" in text.lower() or "wb.ru" in text.lower()


def extract_all_wb_urls(text: str) -> list[str]:
    """Достаёт все WB-ссылки из текста."""
    pattern = re.compile(
        r"https?://[^\s]*(?:wildberries\.ru|wb\.ru)[^\s]*", re.IGNORECASE
    )
    return pattern.findall(text)


def _get_basket_host(article: str) -> str:
    """
    Возвращает номер basket-хоста для картинки товара.
    Логика основана на диапазонах артикулов (по состоянию на 2024-2025).
    Если WB добавит новые шарды — обновить таблицу.
    """
    short_id = int(article) // 100000
    ranges = [
        (143,    "01"), (287,    "02"), (431,    "03"), (719,    "04"),
        (1007,   "05"), (1061,   "06"), (1115,   "07"), (1169,   "08"),
        (1313,   "09"), (1601,   "10"), (1655,   "11"), (1919,   "12"),
        (2045,   "13"), (2189,   "14"), (2405,   "15"), (2621,   "16"),
        (2837,   "17"), (3053,   "18"), (3269,   "19"), (3485,   "20"),
        (3701,   "21"), (3917,   "22"), (4133,   "23"), (4349,   "24"),
        (4565,   "25"), (4877,   "26"),
    ]
    for limit, basket in ranges:
        if short_id <= limit:
            return basket
    # Fallback для новых артикулов — пробуем последний известный
    return "26"


def _build_image_url(article: str) -> str:
    """Формирует URL основной картинки товара."""
    article_int = int(article)
    basket = _get_basket_host(article)
    vol = article_int // 100000
    part = article_int // 1000
    return (
        f"https://basket-{basket}.wbbasket.ru/vol{vol}/part{part}/{article}"
        f"/images/big/1.webp"
    )


def _map_subject_to_category(subject_name: str, subject_id: int = 0) -> str:
    """
    Маппинг WB-категории в нашу: top/bottom/shoes/outer/dress/other.
    """
    s = (subject_name or "").lower()

    # Платья и комбинезоны — отдельная категория для FASHN
    if any(k in s for k in ["платье", "комбинезон", "сарафан"]):
        return "dress"

    # Обувь
    if any(k in s for k in [
        "ботинк", "сапог", "туфл", "кроссов", "кед", "босонож",
        "сандал", "обув", "слипон", "лоферы", "мокасин", "угги"
    ]):
        return "shoes"

    # Верхняя одежда
    if any(k in s for k in [
        "пальто", "куртк", "пуховик", "пиджак", "тренч", "шуб",
        "парк", "плащ", "бомбер", "жилет"
    ]):
        return "outer"

    # Низ
    if any(k in s for k in [
        "брюк", "джинс", "юбк", "шорты", "лосин", "леггинс", "штан"
    ]):
        return "bottom"

    # Верх (по умолчанию для одежды)
    if any(k in s for k in [
        "футболк", "топ", "блуз", "рубашк", "свитер", "худи", "лонгслив",
        "майк", "поло", "джемпер", "кардиган", "толстовк", "водолазк",
        "тунику", "боди"
    ]):
        return "top"

    return "other"


async def parse_wb(url: str, timeout: float = 10.0) -> dict:
    """
    Получить инфо о товаре с WB по URL.
    Возвращает: {article, name, brand, price, photo_url, category, raw_subject}
    Кидает ValueError если не получилось.
    """
    article = extract_article(url)
    if not article:
        raise ValueError("Не похоже на ссылку Wildberries — не нашёл артикул")

    api_url = (
        f"https://card.wb.ru/cards/v2/detail"
        f"?appType=1&curr=rub&dest=-1257786&spp=30&nm={article}"
    )

    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            r = await client.get(
                api_url,
                headers={
                    "User-Agent": (
                        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Safari/537.36"
                    ),
                    "Accept": "application/json",
                },
            )
            r.raise_for_status()
            data = r.json()
    except httpx.HTTPError as e:
        log.error(f"WB API request failed for article {article}: {e}")
        raise ValueError(f"Не удалось получить товар {article} с WB") from e

    products = (data.get("data") or {}).get("products") or []
    if not products:
        raise ValueError(f"Товар {article} не найден в WB")

    product = products[0]

    # Цена: пробуем разные поля (WB часто меняет структуру)
    price = 0
    for sizes in (product.get("sizes") or []):
        price_obj = sizes.get("price") or {}
        if "product" in price_obj:
            price = price_obj["product"] / 100
            break
    if not price:
        price = (product.get("salePriceU") or product.get("priceU") or 0) / 100

    photo_url = _build_image_url(article)

    subject_name = product.get("subjectName") or ""
    subject_id = product.get("subjectId") or 0
    category = _map_subject_to_category(subject_name, subject_id)

    result = {
        "article": article,
        "name": product.get("name") or "Без названия",
        "brand": product.get("brand") or "",
        "price": int(price),
        "photo_url": photo_url,
        "category": category,
        "raw_subject": subject_name,
    }

    log.info(
        f"Parsed WB {article}: {result['name'][:40]} "
        f"({result['brand']}, {result['price']}₽, cat={category})"
    )
    return result


def category_to_fashn(category: str) -> str:
    """Маппинг наших категорий в категории FASHN.AI."""
    mapping = {
        "top": "tops",
        "bottom": "bottoms",
        "outer": "tops",       # верхнюю одежду FASHN обрабатывает как top
        "dress": "one-pieces",
        "shoes": "tops",       # FASHN не умеет обувь — пометим как fallback
    }
    return mapping.get(category, "tops")


def is_tryon_supported(category: str) -> bool:
    """FASHN не поддерживает обувь и аксессуары."""
    return category in {"top", "bottom", "outer", "dress"}


def get_clothing_order(category: str) -> int:
    """
    Порядок одевания (для chain-примерки).
    Сначала низ, потом верх, потом верхняя одежда.
    """
    return {
        "bottom": 1,
        "dress": 1,
        "top": 2,
        "outer": 3,
        "shoes": 4,
        "other": 5,
    }.get(category, 99)
