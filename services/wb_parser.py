"""
Парсер товаров с Wildberries.
Не использует никакое API — только:
1. Вытаскиваем артикул из ссылки
2. Строим URL фото по формуле
3. Gemini смотрит на фото и определяет категорию + название
"""
import re
import json
import logging
import asyncio
from typing import Optional

import httpx
from google import genai
from google.genai import types

from utils import config

log = logging.getLogger(__name__)

_ARTICLE_PATTERNS = [
    re.compile(r"/catalog/(\d+)/", re.IGNORECASE),
    re.compile(r"wildberries\.ru/.+?(\d{6,12})", re.IGNORECASE),
    re.compile(r"\bnm=(\d+)", re.IGNORECASE),
]

CATEGORY_PROMPT = """Посмотри на фото товара с маркетплейса.

Определи:
1. Категорию (одно слово из списка: top, bottom, dress, outer, shoes, other)
2. Краткое название на русском (3-5 слов)

Категории:
- top: футболка, топ, блузка, рубашка, свитер, худи, майка, кардиган, водолазка, боди
- bottom: брюки, джинсы, юбка, шорты, лосины
- dress: платье, комбинезон, сарафан
- outer: пальто, куртка, пуховик, пиджак, тренч, парка, бомбер
- shoes: ботинки, сапоги, туфли, кроссовки, кеды, босоножки
- other: аксессуар, сумка, шапка, шарф, украшение

Верни СТРОГО JSON без преамбулы:
{"category": "top", "name": "белая хлопковая футболка"}"""


def extract_article(url: str) -> Optional[str]:
    url = url.strip()
    for pattern in _ARTICLE_PATTERNS:
        m = pattern.search(url)
        if m:
            return m.group(1)
    return None


def is_wb_url(text: str) -> bool:
    return "wildberries.ru" in text.lower() or "wb.ru" in text.lower()


def extract_all_wb_urls(text: str) -> list[str]:
    pattern = re.compile(
        r"https?://[^\s]*(?:wildberries\.ru|wb\.ru)[^\s]*", re.IGNORECASE
    )
    return pattern.findall(text)


def _get_basket_host(article: str) -> str:
    short_id = int(article) // 100000
    ranges = [
        (143, "01"), (287, "02"), (431, "03"), (719, "04"),
        (1007, "05"), (1061, "06"), (1115, "07"), (1169, "08"),
        (1313, "09"), (1601, "10"), (1655, "11"), (1919, "12"),
        (2045, "13"), (2189, "14"), (2405, "15"), (2621, "16"),
        (2837, "17"), (3053, "18"), (3269, "19"), (3485, "20"),
        (3701, "21"), (3917, "22"), (4133, "23"), (4349, "24"),
        (4565, "25"), (4877, "26"), (5300, "27"), (6000, "28"),
        (7000, "29"), (8000, "30"), (9000, "31"), (10000, "32"),
    ]
    for limit, basket in ranges:
        if short_id <= limit:
            return basket
    return "32"


def _build_image_urls(article: str) -> list[str]:
    article_int = int(article)
    basket = _get_basket_host(article)
    vol = article_int // 100000
    part = article_int // 1000
    return [
        f"https://basket-{basket}.wbbasket.ru/vol{vol}/part{part}/{article}/images/big/1.webp",
        f"https://basket-{basket}.wbbasket.ru/vol{vol}/part{part}/{article}/images/big/1.jpg",
        f"https://basket-{basket}.wb.ru/vol{vol}/part{part}/{article}/images/big/1.webp",
        f"https://basket-{basket}.wb.ru/vol{vol}/part{part}/{article}/images/big/1.jpg",
    ]


async def _download_photo(article: str, timeout: float = 10.0) -> Optional[bytes]:
    urls = _build_image_urls(article)
    async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
        for url in urls:
            try:
                r = await client.get(url, headers={
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                    "Referer": "https://www.wildberries.ru/",
                })
                if r.status_code == 200 and len(r.content) > 1000:
                    log.info(f"Downloaded photo for {article} from {url}")
                    return r.content
            except Exception as e:
                log.debug(f"Failed {url}: {e}")
    return None


async def _classify_with_gemini(photo_bytes: bytes) -> dict:
    client = genai.Client(api_key=config.GEMINI_API_KEY)
    try:
        response = await asyncio.to_thread(
            client.models.generate_content,
            model="gemini-2.0-flash",
            contents=[
                CATEGORY_PROMPT,
                types.Part.from_bytes(data=photo_bytes, mime_type="image/webp"),
            ],
            config=types.GenerateContentConfig(
                temperature=0.1,
                response_mime_type="application/json",
            ),
        )
        raw = response.text.strip()
        if raw.startswith("```"):
            raw = re.sub(r"```[a-z]*\n?", "", raw).strip().rstrip("`").strip()
        parsed = json.loads(raw)
        return {
            "category": parsed.get("category", "top"),
            "name": parsed.get("name", "Товар"),
        }
    except Exception as e:
        log.error(f"Gemini classification failed: {e}")
        return {"category": "top", "name": "Товар с WB"}


async def parse_wb(url: str, timeout: float = 10.0) -> dict:
    """
    Парсинг товара WB без API.
    Возвращает: {article, name, brand, price, photo_url, photo_bytes, category}
    """
    article = extract_article(url)
    if not article:
        raise ValueError("Не похоже на ссылку Wildberries — не нашёл артикул")

    photo_bytes = await _download_photo(article, timeout=timeout)
    if not photo_bytes:
        raise ValueError(
            f"Не удалось скачать фото товара. "
            f"Убедись что товар доступен на WB и попробуй снова."
        )

    classified = await _classify_with_gemini(photo_bytes)

    article_int = int(article)
    basket = _get_basket_host(article)
    vol = article_int // 100000
    part = article_int // 1000
    photo_url = f"https://basket-{basket}.wbbasket.ru/vol{vol}/part{part}/{article}/images/big/1.webp"

    result = {
        "article": article,
        "name": classified["name"],
        "brand": "",
        "price": 0,
        "photo_url": photo_url,
        "photo_bytes": photo_bytes,
        "category": classified["category"],
        "raw_subject": classified["category"],
    }

    log.info(f"Parsed WB {article}: {result['name']} (cat={result['category']})")
    return result


def category_to_fashn(category: str) -> str:
    mapping = {
        "top": "tops",
        "bottom": "bottoms",
        "outer": "tops",
        "dress": "one-pieces",
        "shoes": "tops",
    }
    return mapping.get(category, "tops")


def is_tryon_supported(category: str) -> bool:
    return category in {"top", "bottom", "outer", "dress"}


def get_clothing_order(category: str) -> int:
    return {
        "bottom": 1,
        "dress": 1,
        "top": 2,
        "outer": 3,
        "shoes": 4,
        "other": 5,
    }.get(category, 99)
