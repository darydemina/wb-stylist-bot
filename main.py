"""
WB Stylist Bot — точка входа.
Регистрирует все хэндлеры и запускает бота в режиме polling.
"""
import logging
from io import BytesIO

from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import (
    Application,
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    PreCheckoutQueryHandler,
    ContextTypes,
    filters,
)

from handlers import start as h_start
from handlers import tryon as h_tryon
from handlers import profile as h_profile
from handlers import payments as h_payments
from services import file_storage as subabase_client
from utils import config, keyboards, messages as M

log = logging.getLogger(__name__)


# =====================================================
# Глобальный фото-хэндлер для пост-оплатного re-онбординга.
# Если юзер прошёл оплату /update_photo, у него onboarded=False, но он не
# в ConversationHandler. Этот хэндлер ловит фото и обрабатывает их через
# ту же логику, что и онбординг.
# =====================================================
async def post_payment_photo_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    user = supabase_client.get_user(user_id)

    # Если юзер уже онбординг прошёл — игнорим (фото вне контекста)
    if user and user.get("onboarded"):
        await update.message.reply_text(
            "Я получил фото, но не знаю, что с ним делать. "
            "Используй меню или /help.",
            reply_markup=keyboards.main_menu(),
        )
        return

    # Если юзер не онбординг (новый или после оплаты) — гоним через onboarding flow
    # вручную, т.к. ConversationHandler уже завершён
    if not user:
        # Совсем новый — попросим /start
        await update.message.reply_text("Начни с /start, пожалуйста.")
        return

    # Это после оплаты — собираем фото в user_data и дублируем логику receive_photo
    photos: list = context.user_data.setdefault("onboarding_photos", [])

    if len(photos) >= config.MAX_ONBOARDING_PHOTOS:
        await update.message.reply_text(
            f"Достаточно фото. Нажми «Готово» или подожди — обработка запустится."
        )
        return

    tg_photo = update.message.photo[-1]
    try:
        file = await tg_photo.get_file()
        bio = BytesIO()
        await file.download_to_memory(bio)
        photo_bytes = bio.getvalue()
        photo_url = supabase_client.upload_user_photo(user_id, photo_bytes)
    except Exception as e:
        log.error(f"[{user_id}] post-payment photo failed: {e}")
        await update.message.reply_text("Не смог обработать фото, попробуй ещё.")
        return

    photos.append(photo_url)
    supabase_client.add_user_photo(user_id, photo_url)
    n = len(photos)

    if n >= config.MAX_ONBOARDING_PHOTOS:
        await update.message.reply_text(M.PHOTO_RECEIVED.format(
            n=n, max=config.MAX_ONBOARDING_PHOTOS, action=M.PHOTO_RECEIVED_MAX,
        ), parse_mode=ParseMode.HTML)
        await h_start._process_onboarding(update, context)
    elif n >= config.MIN_ONBOARDING_PHOTOS:
        await update.message.reply_text(
            M.PHOTO_RECEIVED.format(
                n=n, max=config.MAX_ONBOARDING_PHOTOS,
                action=M.PHOTO_RECEIVED_ENOUGH.format(max=config.MAX_ONBOARDING_PHOTOS),
            ),
            parse_mode=ParseMode.HTML,
            reply_markup=keyboards.onboarding_done_kb(config.MIN_ONBOARDING_PHOTOS),
        )
    else:
        await update.message.reply_text(M.PHOTO_RECEIVED.format(
            n=n, max=config.MAX_ONBOARDING_PHOTOS, action=M.PHOTO_RECEIVED_NEED_MORE,
        ), parse_mode=ParseMode.HTML)


# =====================================================
# «Готово» вне ConversationHandler — для пост-оплатного потока
# =====================================================
async def post_payment_done_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    user = supabase_client.get_user(user_id)
    if user and user.get("onboarded"):
        # Всё ок, проигнорируем
        return
    photos = context.user_data.get("onboarding_photos", [])
    if len(photos) < config.MIN_ONBOARDING_PHOTOS:
        await update.message.reply_text(
            f"Минимум {config.MIN_ONBOARDING_PHOTOS} фото."
        )
        return
    await h_start._process_onboarding(update, context)


# =====================================================
# Глобальный обработчик ошибок
# =====================================================
async def global_error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    log.exception(f"Unhandled exception: {context.error}")
    if isinstance(update, Update) and update.effective_message:
        try:
            await update.effective_message.reply_text(
                M.ERROR_GENERIC.format(owner=context.bot_data.get("owner_username", "owner")),
            )
        except Exception:
            pass


# =====================================================
# Хук на старт
# =====================================================
async def post_init(application: Application) -> None:
    """Подгрузка owner_username для упоминаний в ошибках."""
    try:
        if config.OWNER_TELEGRAM_ID:
            chat = await application.bot.get_chat(config.OWNER_TELEGRAM_ID)
            application.bot_data["owner_username"] = chat.username or "owner"
        else:
            application.bot_data["owner_username"] = "owner"
    except Exception as e:
        log.warning(f"Could not fetch owner username: {e}")
        application.bot_data["owner_username"] = "owner"

    # Установим команды бота в Telegram-меню
    from telegram import BotCommand
    await application.bot.set_my_commands([
        BotCommand("start", "Запустить / создать модель"),
        BotCommand("profile", "Моя AI-модель"),
        BotCommand("update_photo", "Обновить фото (платно)"),
        BotCommand("help", "Помощь"),
        BotCommand("privacy", "Приватность"),
    ])
    log.info("Bot started, commands set.")


# =====================================================
# main
# =====================================================
def main() -> None:
    config.setup_logging()

    app = (
        ApplicationBuilder()
        .token(config.BOT_TOKEN)
        .post_init(post_init)
        .build()
    )

    # 1. Онбординг (ConversationHandler)
    app.add_handler(h_start.get_onboarding_handler())

    # 2. Try-on Conversation handlers
    app.add_handler(h_tryon.get_tryon_look_handler())
    app.add_handler(h_tryon.get_tryon_item_handler())

    # 3. Команды
    app.add_handler(CommandHandler("help", h_start.cmd_help))
    app.add_handler(CommandHandler("privacy", h_start.cmd_privacy))
    app.add_handler(CommandHandler("reset", h_start.cmd_reset))
    app.add_handler(CommandHandler("profile", h_profile.show_profile))
    app.add_handler(CommandHandler("update_photo", h_profile.update_photo_intro))

    # Кнопки главного меню (которые НЕ entry_points conversation-ов)
    app.add_handler(MessageHandler(filters.Regex(f"^{M.BTN_PROFILE}$"), h_profile.show_profile))
    app.add_handler(MessageHandler(filters.Regex(f"^{M.BTN_UPDATE_PHOTO}$"), h_profile.update_photo_intro))
    app.add_handler(MessageHandler(filters.Regex(f"^{M.BTN_HELP}$"), h_start.cmd_help))

    # 4. Колбэки оплаты
    app.add_handler(CallbackQueryHandler(h_profile.cb_pay_update, pattern="^pay:update_photo$"))
    app.add_handler(CallbackQueryHandler(h_profile.cb_pay_cancel, pattern="^pay:cancel$"))

    # 5. Telegram Payments
    app.add_handler(PreCheckoutQueryHandler(h_payments.precheckout))
    app.add_handler(MessageHandler(filters.SUCCESSFUL_PAYMENT, h_payments.successful_payment))

    # 6. Глобальные fallback-хэндлеры — в самом конце
    # Ловим фото вне ConversationHandler (пост-оплатный re-онбординг)
    app.add_handler(MessageHandler(filters.PHOTO, post_payment_photo_handler))
    app.add_handler(MessageHandler(filters.Regex(f"^{M.BTN_DONE}$"), post_payment_done_handler))

    # 7. Обработчик ошибок
    app.add_error_handler(global_error_handler)

    log.info("🚀 Bot starting (polling)...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
