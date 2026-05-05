"""
Загрузка переменных окружения и конфигурация.
Работает и с .env (локально) и с Railway/Replit Secrets (в проде).
"""
import os
import logging
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()


def _get_required(key: str) -> str:
    """Получить обязательную переменную окружения, иначе упасть."""
    value = os.getenv(key)
    if not value:
        raise RuntimeError(
            f"❌ Переменная окружения {key} не задана. "
            f"Добавь её в .env (локально) или в Railway/Replit Secrets."
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

# === AI APIs (единственное, что нужно) ===
GEMINI_API_KEY = _get_required("GEMINI_API_KEY")
FASHN_API_KEY = _get_required("FASHN_API_KEY")
OPENAI_API_KEY = _get_required("OPENAI_API_KEY")

# === Локальное хранилище ===
DATA_DIR = Path("/data")
UPLOADS_DIR = DATA_DIR / "uploads"
AVATARS_DIR = DATA_DIR / "avatars"
TRYON_RESULTS_DIR = DATA_DIR / "tryon-results"

# Создаём папки при старте
for directory in [DATA_DIR, UPLOADS_DIR, AVATARS_DIR, TRYON_RESULTS_DIR]:
    directory.mkdir(parents=True, exist_ok=True)

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
