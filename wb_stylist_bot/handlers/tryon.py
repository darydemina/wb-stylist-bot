"""
Примерка лука (несколько вещей) и одной вещи (с филлерами).
"""
import logging
from typing import Optional

from telegram import Update, InputMediaPhoto
from telegram.constants import ChatAction, ParseMode
from telegram.ext import (
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    CallbackQueryHandler,
    CommandHandler,
    filters,
)

from services import supabase_client, wb_parser, tryon_api, stylist, filler_items
from utils import config, keyboards, messages as M
from utils.states import TryonState

log = logging.getLogger(__name__)


# =====================================================
# Утилиты
# =====================================================

def _get_user_or_warn_html(user_id: int) -> Optional[dict]:
    """Возвращает юзера, если он онбординг прошёл."""
    user = supabase_client.get_user(user_id)
    if not user or not user.get("onboarded"):
        return None
    return user


async def _check_limit(update: Update, user: dict) -> bool:
    """Проверка лимита бесплатных примерок. True — можно, False — отказ уже отправлен."""
    used = user.get("tryons_used") or 0
    if used >= config.FREE_TRYON_LIMIT:
        owner_username = update.get_bot().bot_data.get("owner_username", "owner")
        await update.effective_message.reply_text(
            M.LIMIT_REACHED.format(limit=config.FREE_TRYON_LIMIT, owner=owner_username),
            parse_mode=ParseMode.HTML,
        )
        return False
    return True


# =====================================================
# Поток "Примерить лук"
# =====================================================

async def start_tryon_look(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user_id = update.effective_user.id
    user = _get_user_or_warn_html(user_id)
    if not user:
        await update.message.reply_text(M.PROFILE_NOT_READY)
        return ConversationHandler.END

    if not await _check_limit(update, user):
        return ConversationHandler.END

    context.user_data["look_items"] = []
    await update.message.reply_text(M.TRYON_LOOK_START, parse_mode=ParseMode.HTML)
    return TryonState.WAITING_LOOK_LINKS


async def receive_look_links(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Принимает текст со ссылками WB, парсит, накапливает."""
    text = update.message.text or ""
    urls = wb_parser.extract_all_wb_urls(text)

    if not urls:
        await update.message.reply_text(M.LINK_NOT_WB)
        return TryonState.WAITING_LOOK_LINKS

    items: list = context.user_data.setdefault("look_items", [])

    for url in urls:
        if len(items) >= 4:
            await update.message.reply_text("Максимум 4 вещи в одном луке.")
            break
        try:
            await context.bot.send_chat_action(update.effective_chat.id, ChatAction.TYPING)
            item = await wb_parser.parse_wb(url)
            item["source_url"] = url
            items.append(item)

            await update.message.reply_text(
                M.ITEM_ADDED.format(
                    name=item["name"][:80],
                    brand=item["brand"] or "—",
                    price=item["price"],
                    category=item["raw_subject"] or item["category"],
                    total=len(items),
                ),
                parse_mode=ParseMode.HTML,
            )
        except ValueError as e:
            log.warning(f"Parse failed for {url}: {e}")
            await update.message.reply_text(M.LINK_PARSE_ERROR)
        except Exception as e:
            log.exception(f"Unexpected parse error: {e}")
            await update.message.reply_text(M.LINK_PARSE_ERROR)

    if items:
        await update.message.reply_text(
            M.LOOK_READY_PROMPT.format(n=len(items)),
            reply_markup=keyboards.confirm_tryon_kb(),
        )

    return TryonState.WAITING_LOOK_LINKS


# =====================================================
# Поток "Примерить вещь"
# =====================================================

async def start_tryon_item(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user_id = update.effective_user.id
    user = _get_user_or_warn_html(user_id)
    if not user:
        await update.message.reply_text(M.PROFILE_NOT_READY)
        return ConversationHandler.END

    if not await _check_limit(update, user):
        return ConversationHandler.END

    context.user_data["item_data"] = None
    await update.message.reply_text(M.TRYON_ITEM_START, parse_mode=ParseMode.HTML)
    return TryonState.WAITING_ITEM_LINK


async def receive_item_link(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    text = update.message.text or ""
    urls = wb_parser.extract_all_wb_urls(text)

    if not urls:
        await update.message.reply_text(M.LINK_NOT_WB)
        return TryonState.WAITING_ITEM_LINK

    user_id = update.effective_user.id
    user = supabase_client.get_user(user_id)
    if not user:
        return ConversationHandler.END
    profile = user.get("profile_json") or {}
    gender = profile.get("gender", "female")

    try:
        await context.bot.send_chat_action(update.effective_chat.id, ChatAction.TYPING)
        item = await wb_parser.parse_wb(urls[0])
        item["source_url"] = urls[0]
    except Exception as e:
        log.exception(f"Parse failed: {e}")
        await update.message.reply_text(M.LINK_PARSE_ERROR)
        return TryonState.WAITING_ITEM_LINK

    # Подбор филлеров
    fillers = filler_items.get_complements_for_category(item["category"], gender)
    context.user_data["item_data"] = {
        "main_item": item,
        "fillers": fillers,
    }

    fillers_list = "\n".join(f"• {f['name']}" for f in fillers) if fillers else "(без дополнений)"
    await update.message.reply_text(
        M.ITEM_FILLERS_PROMPT.format(name=item["name"][:80], fillers_list=fillers_list),
        parse_mode=ParseMode.HTML,
        reply_markup=keyboards.confirm_item_kb(),
    )
    return TryonState.CONFIRMING


# =====================================================
# Колбэки кнопок
# =====================================================

async def cb_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Юзер нажал «Примерить» — запускаем chain tryon."""
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id

    user = supabase_client.get_user(user_id)
    if not user:
        await query.edit_message_text("Что-то пошло не так. Начни с /start")
        return ConversationHandler.END

    # Определяем тип примерки и собираем items
    look_items = context.user_data.get("look_items") or []
    item_data = context.user_data.get("item_data")

    if look_items:
        tryon_type = "look"
        items = look_items
        focus_item = None
    elif item_data:
        tryon_type = "item"
        items = [item_data["main_item"]] + item_data["fillers"]
        focus_item = item_data["main_item"]
    else:
        await query.edit_message_text("Не вижу вещей для примерки. Начни заново.")
        return ConversationHandler.END

    # Фильтруем то, что FASHN может примерить (отсеиваем shoes/other)
    supported = [i for i in items if wb_parser.is_tryon_supported(i["category"])]
    skipped = [i for i in items if not wb_parser.is_tryon_supported(i["category"])]

    if not supported:
        await query.edit_message_text(
            "К сожалению, я пока не умею примерять обувь и аксессуары. "
            "Пришли вещь из категории топ/низ/платье/куртка."
        )
        return ConversationHandler.END

    # Сортируем по порядку одевания
    supported.sort(key=lambda x: wb_parser.get_clothing_order(x["category"]))
    # Готовим items для chain_tryon
    chain_items = [
        {
            "name": it["name"][:60],
            "photo_url": it["photo_url"],
            "fashn_category": wb_parser.category_to_fashn(it["category"]),
        }
        for it in supported
    ]

    await query.edit_message_text("🚀 Запускаю примерку!")

    # Прогресс-сообщение
    progress_msg = await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text=M.TRYON_STEP.format(name=chain_items[0]["name"], i=1, n=len(chain_items)),
        parse_mode=ParseMode.HTML,
    )

    async def progress(current: int, total: int, name: str):
        try:
            await context.bot.edit_message_text(
                chat_id=update.effective_chat.id,
                message_id=progress_msg.message_id,
                text=M.TRYON_STEP.format(name=name[:60], i=current, n=total),
                parse_mode=ParseMode.HTML,
            )
        except Exception:
            pass

    # Запускаем chain
    try:
        await context.bot.send_chat_action(update.effective_chat.id, ChatAction.UPLOAD_PHOTO)
        result_url = await tryon_api.chain_tryon(
            starting_model_url=user["canonical_photo_url"],
            items_in_order=chain_items,
            progress_callback=progress,
        )
    except Exception as e:
        log.exception(f"[{user_id}] Tryon crashed: {e}")
        result_url = None

    if not result_url:
        await context.bot.edit_message_text(
            chat_id=update.effective_chat.id,
            message_id=progress_msg.message_id,
            text=M.TRYON_ERROR.format(error="не удалось завершить примерку"),
        )
        # Сохраняем неудачную попытку (для аналитики), но не списываем лимит
        supabase_client.save_tryon(
            telegram_id=user_id,
            tryon_type=tryon_type,
            wb_urls=[i.get("source_url", "") for i in items],
            items_data=items,
            result_url=None,
            verdict=None,
            cost_estimate=0,
            success=False,
            error_message="tryon_failed",
        )
        _clear_state(context)
        return ConversationHandler.END

    # Стилист-вердикт
    profile = user.get("profile_json") or {}
    try:
        verdict = await stylist.generate_tryon_verdict(
            profile_json=profile,
            items=items,
            tryon_type=tryon_type,
            focus_item=focus_item,
        )
    except Exception as e:
        log.error(f"[{user_id}] Verdict failed: {e}")
        verdict = "Образ собран, но я не смог дать развёрнутый комментарий."

    # Удаляем сообщение прогресса
    try:
        await context.bot.delete_message(
            chat_id=update.effective_chat.id,
            message_id=progress_msg.message_id,
        )
    except Exception:
        pass

    # Если что-то пропустили — упомянем
    skipped_text = ""
    if skipped:
        names = ", ".join(s["raw_subject"] or s["category"] for s in skipped)
        skipped_text = f"\n\n<i>Пропустил (пока не умею): {names}</i>"

    final_caption = f"{M.TRYON_DONE}\n\n{verdict}{skipped_text}"

    # Шлём результат
    try:
        await context.bot.send_photo(
            chat_id=update.effective_chat.id,
            photo=result_url,
            caption=final_caption,
            parse_mode=ParseMode.HTML,
            reply_markup=keyboards.main_menu(),
        )
    except Exception as e:
        log.error(f"[{user_id}] Failed to send result photo: {e}")
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text=f"{M.TRYON_DONE}\n\nКартинка: {result_url}\n\n{verdict}",
            parse_mode=ParseMode.HTML,
            reply_markup=keyboards.main_menu(),
        )

    # Сохраняем + инкремент лимита
    supabase_client.save_tryon(
        telegram_id=user_id,
        tryon_type=tryon_type,
        wb_urls=[i.get("source_url", "") for i in items],
        items_data=items,
        result_url=result_url,
        verdict=verdict,
        cost_estimate=0.04 * len(chain_items) + 0.001,
        success=True,
    )
    new_used = supabase_client.increment_tryons(user_id)
    log.info(f"[{user_id}] Tryon done. Used: {new_used}/{config.FREE_TRYON_LIMIT}")

    _clear_state(context)
    return ConversationHandler.END


async def cb_add_more(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    await query.edit_message_text("Окей, жду ещё ссылок.")
    return TryonState.WAITING_LOOK_LINKS


async def cb_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    await query.edit_message_text("Отменил.")
    _clear_state(context)
    return ConversationHandler.END


def _clear_state(context: ContextTypes.DEFAULT_TYPE) -> None:
    context.user_data.pop("look_items", None)
    context.user_data.pop("item_data", None)


# =====================================================
# Отмена через команду
# =====================================================
async def cancel_tryon(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    _clear_state(context)
    await update.message.reply_text(
        "Отменил.", reply_markup=keyboards.main_menu()
    )
    return ConversationHandler.END


# =====================================================
# Builders
# =====================================================
def get_tryon_look_handler() -> ConversationHandler:
    return ConversationHandler(
        entry_points=[
            MessageHandler(filters.Regex(f"^{M.BTN_TRYON_LOOK}$"), start_tryon_look),
        ],
        states={
            TryonState.WAITING_LOOK_LINKS: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, receive_look_links),
                CallbackQueryHandler(cb_confirm, pattern="^tryon:confirm$"),
                CallbackQueryHandler(cb_add_more, pattern="^tryon:add_more$"),
                CallbackQueryHandler(cb_cancel, pattern="^tryon:cancel$"),
            ],
        },
        fallbacks=[CommandHandler("cancel", cancel_tryon)],
        allow_reentry=True,
    )


def get_tryon_item_handler() -> ConversationHandler:
    return ConversationHandler(
        entry_points=[
            MessageHandler(filters.Regex(f"^{M.BTN_TRYON_ITEM}$"), start_tryon_item),
        ],
        states={
            TryonState.WAITING_ITEM_LINK: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, receive_item_link),
            ],
            TryonState.CONFIRMING: [
                CallbackQueryHandler(cb_confirm, pattern="^tryon:confirm$"),
                CallbackQueryHandler(cb_cancel, pattern="^tryon:cancel$"),
            ],
        },
        fallbacks=[CommandHandler("cancel", cancel_tryon)],
        allow_reentry=True,
    )
