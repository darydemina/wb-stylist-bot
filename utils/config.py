"""
Загрузка переменных окружения и конфигурация.
Работает и с .env (локально) и с Replit Secrets (в проде).
"""
import os
import logging
from dotenv import load_dotenv

load_dotenv()


def _get_required(key: str) -> str:
    """Получить обязательную переменную окружения, иначе упасть."""
    value = os.getenv(key)
    if not value:
        raise RuntimeError(
            f"❌ Переменная окружения {key} не задана. "
            f"Добавь её в .env (локально) или в Replit Secrets."
        )
    return value


def _get_int(key: str, default: int) -> int:
    raw = os.getenv(key)
    if raw is None:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


# === Telegram ===
BOT_TOKEN = _get_required("BOT_TOKEN")
OWNER_TELEGRAM_ID = _get_int("OWNER_TELEGRAM_ID", 0)

# === Supabase ===
SUPABASE_URL = _get_required("SUPABASE_URL")
SUPABASE_KEY = _get_required("SUPABASE_KEY")

# Buckets
BUCKET_USER_PHOTOS = "user-photos"
BUCKET_AVATARS = "avatars"
BUCKET_TRYON_RESULTS = "tryon-results"

# === AI APIs ===
GEMINI_API_KEY = _get_required("GEMINI_API_KEY")
FASHN_API_KEY = _get_required("FASHN_API_KEY")
OPENAI_API_KEY = _get_required("OPENAI_API_KEY")

# === Бизнес-параметры ===
FREE_TRYON_LIMIT = _get_int("FREE_TRYON_LIMIT", 3)
UPDATE_PHOTO_PRICE_STARS = _get_int("UPDATE_PHOTO_PRICE_STARS", 99)

# === Фото-онбординг ===
MIN_ONBOARDING_PHOTOS = 2
MAX_ONBOARDING_PHOTOS = 4

# === Логирование ===
DEBUG = os.getenv("DEBUG", "false").lower() == "true"
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()


def setup_logging() -> None:
    """Настройка логирования."""
    logging.basicConfig(
        format="%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
        level=LOG_LEVEL,
    )
    # Заглушаем шумные библиотеки
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.getLogger("telegram").setLevel(logging.INFO)
print(f"DEBUG: SUPABASE_URL = {SUPABASE_URL}")
print(f"DEBUG: SUPABASE_KEY = {SUPABASE_KEY[:20]}...")  # первые 20 символов
