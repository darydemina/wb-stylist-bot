"""
/profile, /update_photo (платная функция через Telegram Stars).
"""
import logging

from telegram import Update, LabeledPrice
from telegram.constants import ParseMode
from telegram.ext import (
    ContextTypes,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    filters,
)

from services import file_storage as supabase_client
from utils import config, keyboards, messages as M

log = logging.getLogger(__name__)


# =====================================================
# /profile или кнопка
# =====================================================
async def show_profile(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    user = supabase_client.get_user(user_id)

    if not user or not user.get("onboarded"):
        await update.message.reply_text(M.PROFILE_NOT_READY)
        return

    summary = user.get("stylist_summary") or "Профиль не сформирован"
    used = user.get("tryons_used") or 0
    text = M.PROFILE_VIEW.format(
        summary=summary,
        used=used,
        limit=config.FREE_TRYON_LIMIT,
    )

    photo = user.get("avatar_url") or user.get("canonical_photo_url")
    if photo:
        try:
            await update.message.reply_photo(
                photo=photo,
                caption=text,
                parse_mode=ParseMode.HTML,
                reply_markup=keyboards.main_menu(),
            )
            return
        except Exception as e:
            log.error(f"Failed to send profile photo: {e}")

    await update.message.reply_text(
        text,
        parse_mode=ParseMode.HTML,
        reply_markup=keyboards.main_menu(),
    )


# =====================================================
# /update_photo
# =====================================================
async def update_photo_intro(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    user = supabase_client.get_user(user_id)
    if not user or not user.get("onboarded"):
        await update.message.reply_text(
            "Сначала пройди /start — нужно создать модель."
        )
        return

    await update.message.reply_text(
        M.UPDATE_PHOTO_INTRO.format(price=config.UPDATE_PHOTO_PRICE_STARS),
        parse_mode=ParseMode.HTML,
        reply_markup=keyboards.pay_update_kb(config.UPDATE_PHOTO_PRICE_STARS),
    )


# =====================================================
# Кнопка оплаты
# =====================================================
async def cb_pay_update(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id

    # Шлём Telegram Stars invoice
    try:
        await context.bot.send_invoice(
            chat_id=update.effective_chat.id,
            title="Обновление AI-модели",
            description="Пересоздание модели на основе новых фото",
            payload=f"update_photo:{user_id}",
            provider_token="",  # для Stars пустой
            currency="XTR",
            prices=[LabeledPrice(label="Update", amount=config.UPDATE_PHOTO_PRICE_STARS)],
        )
    except Exception as e:
        log.exception(f"[{user_id}] send_invoice failed: {e}")
        await context.bot.send_message(
            update.effective_chat.id,
            "Не удалось создать счёт. Попробуй позже.",
        )


async def cb_pay_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    await query.edit_message_text("Отменил.")
