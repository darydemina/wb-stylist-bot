"""
Генерация стилизованного аватара пользователя через Gemini 2.5 Flash Image.
Берём canonical фото → выдаём fashion-illustration портрет.
"""
import asyncio
import logging
from typing import Optional

import httpx
from google import genai
from google.genai import types

from services import vision  # переиспользуем _download_image и client
from utils import config

log = logging.getLogger(__name__)

MODEL_IMAGE = "gemini-2.5-flash-image"

AVATAR_PROMPT = (
    "Create a stylized fashion illustration portrait of this person in full height. "
    "Clean studio background (light grey or white), neutral standing pose with arms slightly away from body, "
    "facing camera, soft even lighting. Preserve the person's face, body proportions, "
    "hair, skin tone and gender. Make it look like a high-quality editorial fashion illustration "
    "while keeping it photorealistic enough to be recognizable. Full body must be visible from head to feet."
)


async def generate_avatar(canonical_photo_url: str) -> Optional[bytes]:
    """
    Генерирует стилизованный аватар. Возвращает bytes (PNG) или None при ошибке.
    """
    client = vision.get_client()

    try:
        # Если это локальный путь - читаем файл напрямую
        if canonical_photo_url.startswith("/tmp"):
            with open(canonical_photo_url, "rb") as f:
                img_bytes = f.read()
        else:
            img_bytes = await vision._download_image(canonical_photo_url)
    except Exception as e:
        log.error(f"Cannot read photo for avatar: {e}")
        return None

    try:
        response = await asyncio.to_thread(
            client.models.generate_content,
            model=MODEL_IMAGE,
            contents=[
                AVATAR_PROMPT,
                types.Part.from_bytes(data=img_bytes, mime_type="image/jpeg"),
            ],
        )
    except Exception as e:
        log.error(f"Avatar generation failed: {e}")
        return None

    # Извлекаем сгенерированную картинку
    try:
        for candidate in response.candidates or []:
            for part in (candidate.content.parts if candidate.content else []) or []:
                if hasattr(part, "inline_data") and part.inline_data and part.inline_data.data:
                    log.info("Avatar generated successfully")
                    return part.inline_data.data
    except Exception as e:
        log.error(f"Failed to extract avatar bytes: {e}")

    log.warning("Avatar generation returned no image part")
    return None
