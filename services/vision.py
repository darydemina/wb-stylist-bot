"""
Vision-сервис на Gemini 2.5 Flash:
1) Валидация фото при онбординге (пригодны ли для модели)
2) Выбор лучшего фото для use as canonical
3) Анализ профиля (цветотип, фигура, гендер и т.д.)
"""
import json
import logging
import re
from typing import Optional

import httpx
from google import genai
from google.genai import types

from utils import config

log = logging.getLogger(__name__)

_client: Optional[genai.Client] = None

MODEL_TEXT = "gemini-2.5-flash"


def get_client() -> genai.Client:
    global _client
    if _client is None:
        _client = genai.Client(api_key=config.GEMINI_API_KEY)
    return _client


async def _download_image(url: str) -> bytes:
    """Скачать картинку как bytes."""
    async with httpx.AsyncClient(timeout=30) as client:
        r = await client.get(url)
        r.raise_for_status()
        return r.content


def _extract_json(text: str) -> Optional[dict | list]:
    """Извлечь JSON из ответа модели (она любит обёртывать в ```json)."""
    if not text:
        return None
    # Убираем markdown-обёртку
    text = text.strip()
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        # Пробуем найти JSON-объект или массив внутри текста
        for pattern in [r"\{[\s\S]*\}", r"\[[\s\S]*\]"]:
            m = re.search(pattern, text)
            if m:
                try:
                    return json.loads(m.group(0))
                except json.JSONDecodeError:
                    continue
        log.warning(f"Failed to parse JSON from: {text[:300]}")
        return None


# =====================================================
# 1. ВАЛИДАЦИЯ ФОТО
# =====================================================

VALIDATION_PROMPT = """Ты ассистент, который оценивает пригодность фото человека для виртуальной примерки одежды.

Тебе дают {n} фото. Для КАЖДОГО фото оцени по критериям:

ОК (ok=true):
- Виден человек (хотя бы частично)
- Освещение нормальное (не полная темнота)
- Один реальный человек на фото
- Не сильно размыто

НЕ ОК (ok=false):
- Совсем чёрный экран или пусто
- Только лицо крупным планом БЕЗ тела на ВСЕХ фото
- Явно не человек (мем, рисунок, животное)
- Очень сильная размытость

Верни СТРОГО JSON-массив длиной {n}, без преамбулы, без markdown:
[
  {{"index": 0, "ok": true, "reason": null, "is_full_body": false}},
  {{"index": 1, "ok": false, "reason": "слишком темно", "is_full_body": false}}
]

Поле reason на русском, краткое (если не ok). is_full_body = true только если виден человек ОТ головы ДО ног."""


async def validate_photos(photo_urls: list[str]) -> list[dict]:
    """
    Валидирует список фото. На MVP - принимаем почти все фото.
    Гарантирует, что результат имеет ту же длину, что входной список.
    """
    if not photo_urls:
        return []

    # На MVP просто принимаем все фото без строгой валидации
    # Это ускорит онбординг и не будет отклонять нормальные фото
    return [
        {
            "index": i,
            "ok": True,
            "reason": None,
            "is_full_body": True,
        }
        for i in range(len(photo_urls))
    ]


# =====================================================
# 2. ВЫБОР ЛУЧШЕГО ФОТО
# =====================================================

BEST_PHOTO_PROMPT = """Тебе даны {n} фото одного человека. Выбери ОДНО лучшее для виртуальной примерки одежды.

Критерии лучшего фото (по приоритету):
1. Человек виден В ПОЛНЫЙ РОСТ или хотя бы по середину бедра
2. Стоит фронтально к камере (не сильный поворот)
3. Поза нейтральная (руки опущены или слегка в стороны)
4. Хорошее освещение, чёткость
5. Однотонный/нейтральный фон

Верни СТРОГО JSON: {{"best_index": N}}, где N — индекс выбранного фото (от 0 до {max})."""


async def select_best_photo(photo_urls: list[str]) -> int:
    """Выбирает индекс лучшего фото для canonical. По умолчанию — 0."""
    if len(photo_urls) <= 1:
        return 0

    client = get_client()

    import asyncio
    image_bytes_list = await asyncio.gather(
        *[_download_image(url) for url in photo_urls],
        return_exceptions=True,
    )

    parts = [BEST_PHOTO_PROMPT.format(n=len(photo_urls), max=len(photo_urls) - 1)]
    for img_bytes in image_bytes_list:
        if isinstance(img_bytes, Exception):
            continue
        parts.append(types.Part.from_bytes(data=img_bytes, mime_type="image/jpeg"))

    try:
        response = await asyncio.to_thread(
            client.models.generate_content,
            model=MODEL_TEXT,
            contents=parts,
            config=types.GenerateContentConfig(
                temperature=0.1,
                response_mime_type="application/json",
            ),
        )
        parsed = _extract_json(response.text)
        if isinstance(parsed, dict):
            idx = parsed.get("best_index", 0)
            if isinstance(idx, int) and 0 <= idx < len(photo_urls):
                return idx
    except Exception as e:
        log.error(f"Best photo selection failed: {e}")

    return 0  # fallback на первое


# =====================================================
# 3. АНАЛИЗ ПРОФИЛЯ
# =====================================================

PROFILE_ANALYSIS_PROMPT = """Ты опытный fashion-стилист и колорист. Проанализируй человека на фото.

Верни СТРОГО JSON со всеми полями:
{
  "gender": "male" | "female",
  "age_group": "teen" | "young_adult" | "adult" | "mature",
  "colortype": "spring" | "summer" | "autumn" | "winter",
  "colortype_subtype": "warm_spring" | "cool_summer" | "warm_autumn" | "cool_winter" | "soft_summer" | "deep_winter" | "light_spring" | "bright_spring",
  "body_type": "hourglass" | "pear" | "rectangle" | "inverted_triangle" | "apple",
  "body_type_letter": "X" | "A" | "H" | "V" | "O",
  "height_estimate": "short" | "average" | "tall",
  "current_style": "краткое описание стиля на фото на русском (10-20 слов)",
  "skin_tone": "fair" | "light" | "medium" | "tan" | "deep",
  "hair_color": "описание цвета волос на русском (2-4 слова)",
  "eye_color": "описание цвета глаз на русском или 'не видно'"
}

Без преамбулы, без markdown, только JSON."""


async def analyze_profile(canonical_photo_url: str) -> Optional[dict]:
    """Анализирует фото и возвращает профиль или None при ошибке."""
    client = get_client()

    try:
        # Если это локальный путь - читаем файл напрямую
        if canonical_photo_url.startswith("/tmp"):
            with open(canonical_photo_url, "rb") as f:
                img_bytes = f.read()
        else:
            img_bytes = await _download_image(canonical_photo_url)
    except Exception as e:
        log.error(f"Cannot read photo: {e}")
        return None

    import asyncio
    try:
        response = await asyncio.to_thread(
            client.models.generate_content,
            model=MODEL_TEXT,
            contents=[
                PROFILE_ANALYSIS_PROMPT,
                types.Part.from_bytes(data=img_bytes, mime_type="image/jpeg"),
            ],
            config=types.GenerateContentConfig(
                temperature=0.2,
                response_mime_type="application/json",
            ),
        )
    except Exception as e:
        log.error(f"Profile analysis failed: {e}")
        return None

    parsed = _extract_json(response.text)
    if not isinstance(parsed, dict):
        log.warning(f"Profile analysis returned non-dict: {response.text[:200]}")
        return None

    # Минимально нормализуем гендер на случай мусора
    gender = parsed.get("gender", "").lower()
    if gender not in ("male", "female"):
        parsed["gender"] = "female"  # fallback

    log.info(
        f"Profile: {parsed.get('gender')}/{parsed.get('age_group')}, "
        f"{parsed.get('colortype')}, {parsed.get('body_type')}"
    )
    return parsed
