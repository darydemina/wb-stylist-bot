"""
Тексты стилиста через OpenAI GPT-4o-mini.
1) stylist_summary — после онбординга
2) tryon_verdict — после каждой примерки
"""
import asyncio
import json
import logging
from typing import Optional

from openai import AsyncOpenAI

from utils import config

log = logging.getLogger(__name__)

MODEL = "gpt-4o-mini"

_client: Optional[AsyncOpenAI] = None


def get_client() -> AsyncOpenAI:
    global _client
    if _client is None:
        _client = AsyncOpenAI(api_key=config.OPENAI_API_KEY)
    return _client


# =====================================================
# 1. STYLIST SUMMARY (после онбординга)
# =====================================================

SUMMARY_SYSTEM = (
    "Ты профессиональный стилист и колорист. Пишешь дружелюбно, экспертно, без воды, "
    "по-русски. Используешь эмодзи умеренно (1-3 на ответ)."
)

SUMMARY_USER_TEMPLATE = """На основе профиля человека напиши персональный вывод в формате 4-6 коротких пунктов:

🎨 <b>Цветотип:</b> {colortype} — 1 фраза что это значит для подбора цвета.
👗 <b>Фигура:</b> {body_type} ({body_letter}-type) — что подчёркивать, чего избегать.
✨ <b>Сильные стороны:</b> 1 предложение.
💼 <b>Для офиса:</b> 1 конкретная рекомендация (силуэт + цвет).
🌃 <b>Для вечера:</b> 1 конкретная рекомендация (силуэт + цвет).

Профиль:
{profile_json}

Используй HTML-теги <b> для выделения. Не больше 600 символов всего."""


async def generate_stylist_summary(profile_json: dict) -> str:
    """Генерирует персональный вывод стилиста после онбординга."""
    client = get_client()

    user_prompt = SUMMARY_USER_TEMPLATE.format(
        colortype=profile_json.get("colortype", "не определён"),
        body_type=profile_json.get("body_type", "не определён"),
        body_letter=profile_json.get("body_type_letter", "?"),
        profile_json=json.dumps(profile_json, ensure_ascii=False, indent=2),
    )

    try:
        response = await client.chat.completions.create(
            model=MODEL,
            messages=[
                {"role": "system", "content": SUMMARY_SYSTEM},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.7,
            max_tokens=500,
        )
        text = response.choices[0].message.content.strip()
        log.info(f"Generated stylist summary: {len(text)} chars")
        return text
    except Exception as e:
        log.error(f"Stylist summary generation failed: {e}")
        # Fallback
        return _fallback_summary(profile_json)


def _fallback_summary(profile_json: dict) -> str:
    ct = profile_json.get("colortype", "не определён")
    bt = profile_json.get("body_type", "не определён")
    return (
        f"🎨 <b>Цветотип:</b> {ct}\n"
        f"👗 <b>Фигура:</b> {bt}\n\n"
        f"Я готов примерить на тебя одежду с Wildberries и дать оценку!"
    )


# =====================================================
# 2. TRYON VERDICT
# =====================================================

VERDICT_SYSTEM = (
    "Ты профессиональный стилист. Даёшь честный, конкретный вердикт по примерке. "
    "Пишешь по-русски, кратко, без воды."
)

VERDICT_USER_TEMPLATE = """Юзер примерил {what}. Оцени, как это смотрится.

Профиль юзера:
- Цветотип: {colortype}
- Фигура: {body_type} ({body_letter}-type)
- Гендер: {gender}
- Возраст: {age_group}
- Текущий стиль: {current_style}

{items_block}

Дай вердикт СТРОГО в формате (используй HTML-теги <b>):

🎯 <b>Оценка: X/10</b>
🎨 <b>По цвету:</b> [✅/⚠️/❌] [1 короткая фраза почему]
👗 <b>По фигуре:</b> [✅/⚠️/❌] [1 короткая фраза почему]
✨ <b>Стиль:</b> [1 фраза]
💡 <b>Совет:</b> [1 конкретная рекомендация — с чем носить или куда надеть]

Не больше 500 символов всего. Будь честным: если не подходит — скажи прямо."""


def _format_items_block(items: list[dict], focus_item: Optional[dict] = None) -> str:
    """Формирует блок описания вещей для промпта."""
    lines = ["Вещи в примерке:"]
    for item in items:
        marker = "⭐ " if focus_item and item == focus_item else "• "
        lines.append(
            f"{marker}{item.get('name', 'без названия')} "
            f"({item.get('raw_subject', '')}, {item.get('brand', '')})"
        )
    if focus_item:
        lines.append("\nФокус оценки — на отмеченной ⭐ вещи (остальные — дополнения для контекста).")
    return "\n".join(lines)


async def generate_tryon_verdict(
    profile_json: dict,
    items: list[dict],
    tryon_type: str,
    focus_item: Optional[dict] = None,
) -> str:
    """
    Генерирует вердикт после примерки.
    
    Args:
        profile_json: профиль юзера
        items: список всех вещей (включая филлеры)
        tryon_type: 'look' | 'item'
        focus_item: для type='item' — основная вещь юзера (остальные — филлеры)
    """
    client = get_client()

    what = "целый образ из нескольких вещей" if tryon_type == "look" else "отдельную вещь с дополнениями"

    user_prompt = VERDICT_USER_TEMPLATE.format(
        what=what,
        colortype=profile_json.get("colortype", "не определён"),
        body_type=profile_json.get("body_type", "не определён"),
        body_letter=profile_json.get("body_type_letter", "?"),
        gender=profile_json.get("gender", ""),
        age_group=profile_json.get("age_group", ""),
        current_style=profile_json.get("current_style", "не определён"),
        items_block=_format_items_block(items, focus_item),
    )

    try:
        response = await client.chat.completions.create(
            model=MODEL,
            messages=[
                {"role": "system", "content": VERDICT_SYSTEM},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.6,
            max_tokens=400,
        )
        text = response.choices[0].message.content.strip()
        log.info(f"Generated verdict: {len(text)} chars")
        return text
    except Exception as e:
        log.error(f"Verdict generation failed: {e}")
        return (
            "🎯 <b>Оценка: 7/10</b>\n"
            "Образ собран, но я не смог дать развёрнутый комментарий — попробуй ещё раз."
        )
