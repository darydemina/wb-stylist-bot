"""
Клавиатуры (reply и inline).
"""
from telegram import (
    ReplyKeyboardMarkup,
    KeyboardButton,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    ReplyKeyboardRemove,
)

from utils import messages as M


def main_menu() -> ReplyKeyboardMarkup:
    """Главное меню — постоянное."""
    return ReplyKeyboardMarkup(
        [
            [KeyboardButton(M.BTN_TRYON_LOOK), KeyboardButton(M.BTN_TRYON_ITEM)],
            [KeyboardButton(M.BTN_PROFILE), KeyboardButton(M.BTN_UPDATE_PHOTO)],
            [KeyboardButton(M.BTN_HELP)],
        ],
        resize_keyboard=True,
    )


def onboarding_done_kb(min_photos: int) -> ReplyKeyboardMarkup:
    """Кнопка «Готово» при онбординге."""
    return ReplyKeyboardMarkup(
        [[KeyboardButton(M.BTN_DONE)]],
        resize_keyboard=True,
        one_time_keyboard=False,
        input_field_placeholder=f"Можно прислать ещё или нажать «Готово»",
    )


def remove_kb() -> ReplyKeyboardRemove:
    return ReplyKeyboardRemove()


def confirm_tryon_kb() -> InlineKeyboardMarkup:
    """Кнопки на этапе сбора ссылок для лука."""
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton(M.BTN_CONFIRM_TRYON, callback_data="tryon:confirm")],
            [
                InlineKeyboardButton(M.BTN_ADD_MORE, callback_data="tryon:add_more"),
                InlineKeyboardButton(M.BTN_CANCEL, callback_data="tryon:cancel"),
            ],
        ]
    )


def confirm_item_kb() -> InlineKeyboardMarkup:
    """Кнопки на подтверждение примерки одной вещи + филлеров."""
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton(M.BTN_CONFIRM_TRYON, callback_data="tryon:confirm")],
            [InlineKeyboardButton(M.BTN_CANCEL, callback_data="tryon:cancel")],
        ]
    )


def pay_update_kb(price: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton(M.BTN_PAY.format(price=price), callback_data="pay:update_photo")],
            [InlineKeyboardButton(M.BTN_CANCEL, callback_data="pay:cancel")],
        ]
    )
