"""
Все операции с Supabase: БД и Storage.
"""
import logging
import uuid
from typing import Optional, Any
from datetime import datetime

from supabase import create_client, Client

from utils import config

log = logging.getLogger(__name__)

_client: Optional[Client] = None


def get_client() -> Client:
    """Singleton клиент Supabase."""
    global _client
    if _client is None:
        _client = create_client(config.SUPABASE_URL, config.SUPABASE_KEY)
    return _client


# =====================================================
# STORAGE
# =====================================================

def upload_bytes(bucket: str, path: str, data: bytes, content_type: str = "image/jpeg") -> str:
    """
    Загрузить байты в Storage и вернуть public URL.
    """
    client = get_client()
    try:
        client.storage.from_(bucket).upload(
            path=path,
            file=data,
            file_options={"content-type": content_type, "upsert": "true"},
        )
    except Exception as e:
        log.error(f"Storage upload failed for {bucket}/{path}: {e}")
        raise

    public_url = client.storage.from_(bucket).get_public_url(path)
    return public_url


def upload_user_photo(telegram_id: int, photo_bytes: bytes) -> str:
    """Загрузить фото юзера. Возвращает public URL."""
    filename = f"{telegram_id}/{uuid.uuid4().hex}.jpg"
    return upload_bytes(config.BUCKET_USER_PHOTOS, filename, photo_bytes)


def upload_avatar(telegram_id: int, avatar_bytes: bytes) -> str:
    """Загрузить сгенерированный аватар."""
    filename = f"{telegram_id}/avatar_{int(datetime.now().timestamp())}.png"
    return upload_bytes(config.BUCKET_AVATARS, filename, avatar_bytes, "image/png")


def upload_tryon_result(telegram_id: int, result_bytes: bytes) -> str:
    """Загрузить результат примерки."""
    filename = f"{telegram_id}/tryon_{int(datetime.now().timestamp())}_{uuid.uuid4().hex[:6]}.png"
    return upload_bytes(config.BUCKET_TRYON_RESULTS, filename, result_bytes, "image/png")


# =====================================================
# USERS
# =====================================================

def get_or_create_user(telegram_id: int, username: Optional[str] = None) -> dict:
    """Получить или создать юзера."""
    client = get_client()
    res = client.table("users").select("*").eq("telegram_id", telegram_id).execute()

    if res.data:
        # Обновляем last_active
        client.table("users").update(
            {"last_active_at": datetime.utcnow().isoformat()}
        ).eq("telegram_id", telegram_id).execute()
        return res.data[0]

    new_user = {
        "telegram_id": telegram_id,
        "username": username,
        "onboarded": False,
        "tryons_used": 0,
    }
    res = client.table("users").insert(new_user).execute()
    log.info(f"Created new user {telegram_id} (@{username})")
    return res.data[0]


def get_user(telegram_id: int) -> Optional[dict]:
    client = get_client()
    res = client.table("users").select("*").eq("telegram_id", telegram_id).execute()
    return res.data[0] if res.data else None


def update_user(telegram_id: int, **fields: Any) -> None:
    """Обновить произвольные поля юзера."""
    client = get_client()
    client.table("users").update(fields).eq("telegram_id", telegram_id).execute()


def increment_tryons(telegram_id: int) -> int:
    """Инкремент счётчика примерок. Возвращает новое значение."""
    user = get_user(telegram_id)
    if not user:
        return 0
    new_value = (user.get("tryons_used") or 0) + 1
    update_user(telegram_id, tryons_used=new_value)
    return new_value


def reset_user(telegram_id: int) -> None:
    """Полный сброс юзера (для /reset)."""
    client = get_client()
    client.table("user_photos").delete().eq("telegram_id", telegram_id).execute()
    client.table("tryons").delete().eq("telegram_id", telegram_id).execute()
    client.table("profile_history").delete().eq("telegram_id", telegram_id).execute()
    client.table("payments").delete().eq("telegram_id", telegram_id).execute()
    client.table("users").delete().eq("telegram_id", telegram_id).execute()
    log.info(f"Reset user {telegram_id}")


# =====================================================
# USER PHOTOS
# =====================================================

def add_user_photo(telegram_id: int, photo_url: str) -> None:
    client = get_client()
    client.table("user_photos").insert(
        {"telegram_id": telegram_id, "photo_url": photo_url}
    ).execute()


def get_active_user_photos(telegram_id: int) -> list[str]:
    client = get_client()
    res = (
        client.table("user_photos")
        .select("photo_url")
        .eq("telegram_id", telegram_id)
        .eq("is_active", True)
        .order("created_at", desc=False)
        .execute()
    )
    return [row["photo_url"] for row in res.data]


def deactivate_old_photos(telegram_id: int) -> None:
    """Используется при /update_photo — старые фото уходят в неактив."""
    client = get_client()
    client.table("user_photos").update({"is_active": False}).eq(
        "telegram_id", telegram_id
    ).execute()


# =====================================================
# PROFILE HISTORY
# =====================================================

def archive_current_profile(telegram_id: int) -> None:
    """Архивирует текущий профиль перед обновлением."""
    user = get_user(telegram_id)
    if not user:
        return
    client = get_client()
    client.table("profile_history").insert(
        {
            "telegram_id": telegram_id,
            "old_avatar_url": user.get("avatar_url"),
            "old_profile_json": user.get("profile_json"),
            "old_canonical_photo_url": user.get("canonical_photo_url"),
            "old_stylist_summary": user.get("stylist_summary"),
        }
    ).execute()
    log.info(f"Archived profile for {telegram_id}")


# =====================================================
# TRYONS
# =====================================================

def save_tryon(
    telegram_id: int,
    tryon_type: str,
    wb_urls: list[str],
    items_data: list[dict],
    result_url: Optional[str],
    verdict: Optional[str],
    cost_estimate: float,
    success: bool,
    error_message: Optional[str] = None,
) -> None:
    client = get_client()
    client.table("tryons").insert(
        {
            "telegram_id": telegram_id,
            "type": tryon_type,
            "wb_urls": wb_urls,
            "items_data": items_data,
            "result_url": result_url,
            "verdict": verdict,
            "cost_estimate": cost_estimate,
            "success": success,
            "error_message": error_message,
        }
    ).execute()


# =====================================================
# FILLER ITEMS
# =====================================================

def get_filler_items_by_categories(
    categories: list[str], gender: str
) -> list[dict]:
    """
    Возвращает по одному filler-item на каждую категорию из списка.
    Берём для гендера юзера ИЛИ unisex.
    """
    client = get_client()
    result = []
    for cat in categories:
        res = (
            client.table("filler_items")
            .select("*")
            .eq("category", cat)
            .eq("is_active", True)
            .in_("gender", [gender, "unisex"])
            .limit(10)
            .execute()
        )
        if res.data:
            # На MVP — берём первый. На v2 — матчинг по цвету юзеровой вещи.
            result.append(res.data[0])
    return result


def seed_filler_items(items: list[dict]) -> int:
    """Заливка стартовых вещей. Возвращает количество вставленных."""
    client = get_client()
    # Чистим существующие
    client.table("filler_items").delete().neq("id", 0).execute()
    res = client.table("filler_items").insert(items).execute()
    return len(res.data)


# =====================================================
# PAYMENTS
# =====================================================

def save_payment(
    telegram_id: int,
    amount_stars: int,
    purpose: str,
    telegram_payment_id: Optional[str] = None,
    invoice_payload: Optional[str] = None,
) -> None:
    client = get_client()
    client.table("payments").insert(
        {
            "telegram_id": telegram_id,
            "amount_stars": amount_stars,
            "purpose": purpose,
            "telegram_payment_id": telegram_payment_id,
            "invoice_payload": invoice_payload,
        }
    ).execute()
