"""
Подбор filler-вещей для дополнения "примерки одной вещи".
Логика: если юзер прислал топ — добавляем низ + обувь (но обувь FASHN не умеет, скипаем).
"""
import logging
from services import file_storage as supabase_client

log = logging.getLogger(__name__)


# Что нужно добавить, если юзер прислал вещь данной категории.
# Только категории, которые поддерживает FASHN: top, bottom, dress, outer.
COMPLEMENT_RULES = {
    "top": ["bottom"],
    "bottom": ["top"],
    "outer": ["top", "bottom"],
    "dress": [],          # платье — самодостаточно, ничего не добавляем
    "shoes": ["top", "bottom"],   # обувь сама не примеряется, но образ соберём
    "other": ["top", "bottom"],
}


def get_complements_for_category(category: str, gender: str) -> list[dict]:
    """
    Возвращает filler-вещи для дополнения категории.
    Каждый item имеет: photo_url, category, subcategory, color, description, name.
    """
    needed_categories = COMPLEMENT_RULES.get(category, [])
    if not needed_categories:
        return []

    # Маппим male/female (другое — в female как fallback)
    norm_gender = gender if gender in ("male", "female") else "female"

    items = supabase_client.get_filler_items_by_categories(needed_categories, norm_gender)

    # Адаптируем структуру к формату, как у WB-вещей
    adapted = []
    for it in items:
        adapted.append({
            "name": it["description"],
            "brand": "Базовый гардероб",
            "price": 0,
            "photo_url": it["photo_url"],
            "category": it["category"],
            "raw_subject": it["subcategory"],
            "is_filler": True,
        })
    return adapted
