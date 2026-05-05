"""
Обработка платежей через Telegram Stars.
"""
import logging

from telegram import Update
from telegram.ext import ContextTypes

from services import supabase_client
from utils import config, keyboards, messages as M

log = logging.getLogger(__name__)


async def precheckout(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Подтверждаем готовность принять платёж — всегда ОК."""
    query = update.pre_checkout_query
    try:
        await query.answer(ok=True)
    except Exception as e:
        log.exception(f"precheckout answer failed: {e}")


async def successful_payment(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Платёж прошёл — даём доступ к /update_photo."""
    user_id = update.effective_user.id
    payment = update.message.successful_payment

    log.info(
        f"[{user_id}] Payment received: {payment.total_amount} {payment.currency}, "
        f"payload={payment.invoice_payload}"
    )

    # Сохраняем платёж
    try:
        supabase_client.save_payment(
            telegram_id=user_id,
            amount_stars=payment.total_amount,
            purpose="update_photo",
            telegram_payment_id=payment.telegram_payment_charge_id,
            invoice_payload=payment.invoice_payload,
        )
    except Exception as e:
        log.exception(f"Failed to save payment: {e}")

    # Архивируем текущий профиль и сбрасываем onboarded
    try:
        supabase_client.archive_current_profile(user_id)
        supabase_client.deactivate_old_photos(user_id)
        supabase_client.update_user(user_id, onboarded=False)
    except Exception as e:
        log.exception(f"Failed to archive profile: {e}")

    # Чистим временные данные
    context.user_data["onboarding_photos"] = []

    # Просим новые фото
    await update.message.reply_text(
        M.UPDATE_PHOTO_PAID + "\n\n" + M.WELCOME_NEW,
        parse_mode="HTML",
        reply_markup=keyboards.remove_kb(),
    )
    # NB: после оплаты юзер шлёт фото — попадает в receive_photo через
    # отдельный fallback-MessageHandler в main.py (вне ConversationHandler онбординга).
    # См. main.py: глобальный фото-хэндлер для не-онбординг-юзеров.
