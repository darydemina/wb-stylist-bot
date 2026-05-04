"""
/start, онбординг (приём фото, валидация, создание модели).
"""
import asyncio
import logging
from io import BytesIO

from telegram import Update
from telegram.constants import ChatAction, ParseMode
from telegram.ext import (
    ContextTypes,
    ConversationHandler,
    CommandHandler,
    MessageHandler,
    filters,
)

from services import supabase_client, vision, avatar, stylist
from utils import config, keyboards, messages as M
from utils.states import OnboardingState

log = logging.getLogger(__name__)


# =====================================================
# /start
# =====================================================
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user = update.effective_user
    db_user = supabase_client.get_or_create_user(user.id, user.username)

    # Если уже онбординг прошёл — главное меню
    if db_user.get("onboarded"):
        await update.message.reply_text(
            M.WELCOME_BACK,
            reply_markup=keyboards.main_menu(),
        )
        return ConversationHandler.END

    # Иначе — стартуем онбординг
    context.user_data["onboarding_photos"] = []
    await update.message.reply_text(
        M.WELCOME_NEW,
        parse_mode=ParseMode.HTML,
        reply_markup=keyboards.remove_kb(),
    )
    return OnboardingState.WAITING_PHOTOS


# =====================================================
# Приём фото при онбординге
# =====================================================
async def receive_photo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if not update.message or not update.message.photo:
        return OnboardingState.WAITING_PHOTOS

    user_id = update.effective_user.id
    photos: list = context.user_data.setdefault("onboarding_photos", [])

    if len(photos) >= config.MAX_ONBOARDING_PHOTOS:
        await update.message.reply_text(
            f"Достаточно фото (максимум {config.MAX_ONBOARDING_PHOTOS}). "
            f"Нажми «Готово»."
        )
        return OnboardingState.WAITING_PHOTOS

    # Берём самое большое фото
    tg_photo = update.message.photo[-1]
    try:
        file = await tg_photo.get_file()
        bio = BytesIO()
        await file.download_to_memory(bio)
        photo_bytes = bio.getvalue()
    except Exception as e:
        log.error(f"Failed to download photo from Telegram: {e}")
        await update.message.reply_text(
            "Не смог скачать фото из Telegram. Попробуй ещё раз."
        )
        return OnboardingState.WAITING_PHOTOS

    # Загружаем в Supabase
    try:
        photo_url = supabase_client.upload_user_photo(user_id, photo_bytes)
    except Exception as e:
        log.error(f"Failed to upload photo to Supabase: {e}")
        await update.message.reply_text(
            M.ERROR_GENERIC.format(owner=context.bot_data.get("owner_username", ""))
        )
        return OnboardingState.WAITING_PHOTOS

    photos.append(photo_url)
    n = len(photos)

    # Сохраняем в БД (привязка к юзеру)
    supabase_client.add_user_photo(user_id, photo_url)

    # Логика ответа
    if n >= config.MAX_ONBOARDING_PHOTOS:
        action = M.PHOTO_RECEIVED_MAX
    elif n >= config.MIN_ONBOARDING_PHOTOS:
        action = M.PHOTO_RECEIVED_ENOUGH.format(max=config.MAX_ONBOARDING_PHOTOS)
    else:
        action = M.PHOTO_RECEIVED_NEED_MORE

    await update.message.reply_text(
        M.PHOTO_RECEIVED.format(n=n, max=config.MAX_ONBOARDING_PHOTOS, action=action),
        parse_mode=ParseMode.HTML,
        reply_markup=keyboards.onboarding_done_kb(config.MIN_ONBOARDING_PHOTOS)
        if n >= config.MIN_ONBOARDING_PHOTOS
        else None,
    )

    # Если набрали максимум — автоматически запускаем обработку
    if n >= config.MAX_ONBOARDING_PHOTOS:
        return await _process_onboarding(update, context)

    return OnboardingState.WAITING_PHOTOS


# =====================================================
# Кнопка «Готово»
# =====================================================
async def done_button(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    photos = context.user_data.get("onboarding_photos", [])
    if len(photos) < config.MIN_ONBOARDING_PHOTOS:
        await update.message.reply_text(
            f"Минимум {config.MIN_ONBOARDING_PHOTOS} фото. Пришли ещё."
        )
        return OnboardingState.WAITING_PHOTOS

    return await _process_onboarding(update, context)


# =====================================================
# Обработка онбординга — главная магия
# =====================================================
async def _process_onboarding(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user_id = update.effective_user.id
    photos: list[str] = context.user_data.get("onboarding_photos", [])

    await update.message.reply_text(
        M.PROCESSING_START,
        reply_markup=keyboards.remove_kb(),
    )
    await context.bot.send_chat_action(update.effective_chat.id, ChatAction.UPLOAD_PHOTO)

    # 1. Валидация
    log.info(f"[{user_id}] Validating {len(photos)} photos")
    try:
        validations = await vision.validate_photos(photos)
    except Exception as e:
        log.exception(f"[{user_id}] Validation crashed: {e}")
        await update.message.reply_text(
            M.ERROR_GENERIC.format(owner=context.bot_data.get("owner_username", ""))
        )
        return ConversationHandler.END

    bad = [v for v in validations if not v["ok"]]
    has_full_body = any(v.get("is_full_body") for v in validations if v["ok"])

    if bad or not has_full_body:
        reasons = []
        for i, v in enumerate(validations):
            if not v["ok"]:
                reasons.append(f"• Фото {i+1}: {v.get('reason') or 'не подходит'}")
        if not has_full_body:
            reasons.append("• Ни одно фото не показывает тебя в полный рост")
        # Сбрасываем накопленные фото
        context.user_data["onboarding_photos"] = []
        await update.message.reply_text(
            M.VALIDATION_FAILED.format(reasons="\n".join(reasons)),
            parse_mode=ParseMode.HTML,
        )
        return OnboardingState.WAITING_PHOTOS

    # 2. Выбор лучшего фото
    log.info(f"[{user_id}] Selecting best photo")
    try:
        best_idx = await vision.select_best_photo(photos)
        canonical_url = photos[best_idx]
    except Exception as e:
        log.exception(f"[{user_id}] Best photo selection failed: {e}")
        canonical_url = photos[0]

    # 3, 4, 5. Параллельно: профиль + аватар
    log.info(f"[{user_id}] Analyzing profile and generating avatar in parallel")
    profile_task = asyncio.create_task(vision.analyze_profile(canonical_url))
    avatar_task = asyncio.create_task(avatar.generate_avatar(canonical_url))

    profile_json, avatar_bytes = await asyncio.gather(
        profile_task, avatar_task, return_exceptions=True
    )

    # Обработка ошибок
    if isinstance(profile_json, Exception) or not profile_json:
        log.error(f"[{user_id}] Profile analysis failed: {profile_json}")
        await update.message.reply_text(
            "Не получилось проанализировать твой профиль. Попробуй ещё раз с другими фото."
        )
        context.user_data["onboarding_photos"] = []
        return OnboardingState.WAITING_PHOTOS

    avatar_url = None
    if isinstance(avatar_bytes, Exception) or not avatar_bytes:
        log.warning(f"[{user_id}] Avatar generation failed, using canonical photo")
    else:
        try:
            avatar_url = supabase_client.upload_avatar(user_id, avatar_bytes)
        except Exception as e:
            log.error(f"[{user_id}] Avatar upload failed: {e}")

    # 6. Stylist summary
    log.info(f"[{user_id}] Generating stylist summary")
    try:
        summary = await stylist.generate_stylist_summary(profile_json)
    except Exception as e:
        log.exception(f"[{user_id}] Summary generation failed: {e}")
        summary = "Готов работать с тобой как с твоим стилистом!"

    # 7. Сохраняем юзера
    supabase_client.update_user(
        user_id,
        canonical_photo_url=canonical_url,
        avatar_url=avatar_url,
        profile_json=profile_json,
        stylist_summary=summary,
        onboarded=True,
    )
    log.info(f"[{user_id}] Onboarding complete!")

    # 8. Отправляем результат
    photo_to_send = avatar_url or canonical_url
    final_caption = M.ONBOARDING_DONE.format(summary=summary)

    try:
        await context.bot.send_photo(
            chat_id=update.effective_chat.id,
            photo=photo_to_send,
            caption=final_caption,
            parse_mode=ParseMode.HTML,
            reply_markup=keyboards.main_menu(),
        )
    except Exception as e:
        log.error(f"[{user_id}] Failed to send result photo: {e}")
        # Fallback: текст без картинки
        await update.message.reply_text(
            final_caption,
            parse_mode=ParseMode.HTML,
            reply_markup=keyboards.main_menu(),
        )

    # Сброс временных данных
    context.user_data.pop("onboarding_photos", None)
    return ConversationHandler.END


# =====================================================
# Отмена
# =====================================================
async def cancel_onboarding(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data.pop("onboarding_photos", None)
    await update.message.reply_text(
        "Отменил. Когда будешь готов — /start",
        reply_markup=keyboards.remove_kb(),
    )
    return ConversationHandler.END


# =====================================================
# Builder ConversationHandler
# =====================================================
def get_onboarding_handler() -> ConversationHandler:
    return ConversationHandler(
        entry_points=[CommandHandler("start", cmd_start)],
        states={
            OnboardingState.WAITING_PHOTOS: [
                MessageHandler(filters.PHOTO, receive_photo),
                MessageHandler(filters.Regex(f"^{M.BTN_DONE}$"), done_button),
            ],
        },
        fallbacks=[CommandHandler("cancel", cancel_onboarding)],
        allow_reentry=True,
    )


# =====================================================
# /help, /privacy
# =====================================================
async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(M.HELP, parse_mode=ParseMode.HTML)


async def cmd_privacy(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(M.PRIVACY, parse_mode=ParseMode.HTML)


# =====================================================
# /reset (только для OWNER)
# =====================================================
async def cmd_reset(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    if user_id != config.OWNER_TELEGRAM_ID:
        await update.message.reply_text(M.RESET_NOT_ALLOWED)
        return
    supabase_client.reset_user(user_id)
    await update.message.reply_text(
        M.RESET_DONE,
        reply_markup=keyboards.remove_kb(),
    )
