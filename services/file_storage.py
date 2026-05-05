"""Простое хранилище вместо Supabase."""
import json
import logging
from pathlib import Path
from typing import Optional, Any
from datetime import datetime
import uuid

from utils import config

log = logging.getLogger(__name__)

USERS_FILE = config.DATA_DIR / "users.json"
TRYONS_FILE = config.DATA_DIR / "tryons.json"
PAYMENTS_FILE = config.DATA_DIR / "payments.json"


def _load_json(filepath: Path) -> dict | list:
    if not filepath.exists():
        return {} if "users" in filepath.name or "payments" in filepath.name else []
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            return json.load(f)
    except:
        return {} if "users" in filepath.name else []


def _save_json(filepath: Path, data: dict | list) -> None:
    try:
        filepath.parent.mkdir(parents=True, exist_ok=True)
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        log.error(f"Save failed: {e}")


def upload_bytes(folder: Path, filename: str, data: bytes) -> str:
    folder.mkdir(parents=True, exist_ok=True)
    filepath = folder / filename
    try:
        with open(filepath, "wb") as f:
            f.write(data)
        return str(filepath)
    except Exception as e:
        log.error(f"Upload failed: {e}")
        raise


def upload_user_photo(telegram_id: int, photo_bytes: bytes) -> str:
    filename = f"{telegram_id}_{uuid.uuid4().hex[:8]}.jpg"
    return upload_bytes(config.UPLOADS_DIR, filename, photo_bytes)


def upload_avatar(telegram_id: int, avatar_bytes: bytes) -> str:
    filename = f"{telegram_id}_avatar.png"
    return upload_bytes(config.AVATARS_DIR, filename, avatar_bytes)


def upload_tryon_result(telegram_id: int, result_bytes: bytes) -> str:
    filename = f"{telegram_id}_tryon_{int(datetime.now().timestamp())}_{uuid.uuid4().hex[:4]}.png"
    return upload_bytes(config.TRYON_RESULTS_DIR, filename, result_bytes)


def get_or_create_user(telegram_id: int, username: Optional[str] = None) -> dict:
    users = _load_json(USERS_FILE)
    user_id_str = str(telegram_id)

    if user_id_str in users:
        users[user_id_str]["last_active_at"] = datetime.utcnow().isoformat()
        _save_json(USERS_FILE, users)
        return users[user_id_str]

    new_user = {
        "telegram_id": telegram_id,
        "username": username,
        "onboarded": False,
        "tryons_used": 0,
        "avatar_url": None,
        "canonical_photo_url": None,
        "profile_json": None,
        "stylist_summary": None,
        "created_at": datetime.utcnow().isoformat(),
        "last_active_at": datetime.utcnow().isoformat(),
    }
    users[user_id_str] = new_user
    _save_json(USERS_FILE, users)
    log.info(f"Created user {telegram_id}")
    return new_user


def get_user(telegram_id: int) -> Optional[dict]:
    users = _load_json(USERS_FILE)
    return users.get(str(telegram_id))


def update_user(telegram_id: int, **fields: Any) -> None:
    users = _load_json(USERS_FILE)
    user_id_str = str(telegram_id)
    if user_id_str in users:
        users[user_id_str].update(fields)
        _save_json(USERS_FILE, users)


def increment_tryons(telegram_id: int) -> int:
    user = get_user(telegram_id)
    if not user:
        return 0
    new_value = (user.get("tryons_used") or 0) + 1
    update_user(telegram_id, tryons_used=new_value)
    return new_value


def reset_user(telegram_id: int) -> None:
    users = _load_json(USERS_FILE)
    if str(telegram_id) in users:
        del users[str(telegram_id)]
        _save_json(USERS_FILE, users)


def add_user_photo(telegram_id: int, photo_url: str) -> None:
    user = get_user(telegram_id)
    if not user:
        return
    if "photos" not in user:
        user["photos"] = []
    user["photos"].append({"url": photo_url, "created_at": datetime.utcnow().isoformat(), "is_active": True})
    update_user(telegram_id, photos=user["photos"])


def get_active_user_photos(telegram_id: int) -> list[str]:
    user = get_user(telegram_id)
    if not user:
        return []
    photos = user.get("photos", [])
    return [p["url"] for p in photos if p.get("is_active")]


def deactivate_old_photos(telegram_id: int) -> None:
    user = get_user(telegram_id)
    if not user:
        return
    photos = user.get("photos", [])
    for p in photos:
        p["is_active"] = False
    update_user(telegram_id, photos=photos)


def archive_current_profile(telegram_id: int) -> None:
    user = get_user(telegram_id)
    if not user:
        return
    users = _load_json(USERS_FILE)
    user_id_str = str(telegram_id)
    if "profile_history" not in users[user_id_str]:
        users[user_id_str]["profile_history"] = []
    users[user_id_str]["profile_history"].append({
        "avatar_url": user.get("avatar_url"),
        "profile_json": user.get("profile_json"),
        "canonical_photo_url": user.get("canonical_photo_url"),
        "stylist_summary": user.get("stylist_summary"),
        "archived_at": datetime.utcnow().isoformat(),
    })
    _save_json(USERS_FILE, users)


def save_tryon(telegram_id: int, tryon_type: str, wb_urls: list[str], items_data: list[dict],
               result_url: Optional[str], verdict: Optional[str], cost_estimate: float,
               success: bool, error_message: Optional[str] = None) -> None:
    tryons = _load_json(TRYONS_FILE)
    if not isinstance(tryons, list):
        tryons = []
    tryons.append({
        "id": str(uuid.uuid4()),
        "telegram_id": telegram_id,
        "type": tryon_type,
        "wb_urls": wb_urls,
        "items_data": items_data,
        "result_url": result_url,
        "verdict": verdict,
        "cost_estimate": cost_estimate,
        "success": success,
        "error_message": error_message,
        "created_at": datetime.utcnow().isoformat(),
    })
    _save_json(TRYONS_FILE, tryons)


def get_filler_items_by_categories(categories: list[str], gender: str) -> list[dict]:
    return []


def save_payment(telegram_id: int, amount_stars: int, purpose: str,
                telegram_payment_id: Optional[str] = None, invoice_payload: Optional[str] = None) -> None:
    payments = _load_json(PAYMENTS_FILE)
    if not isinstance(payments, list):
        payments = []
    payments.append({
        "id": str(uuid.uuid4()),
        "telegram_id": telegram_id,
        "amount_stars": amount_stars,
        "purpose": purpose,
        "telegram_payment_id": telegram_payment_id,
        "invoice_payload": invoice_payload,
        "created_at": datetime.utcnow().isoformat(),
    })
    _save_json(PAYMENTS_FILE, payments)
