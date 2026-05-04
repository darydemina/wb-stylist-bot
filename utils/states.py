"""
Состояния для ConversationHandler-ов.
"""
from enum import IntEnum, auto


class OnboardingState(IntEnum):
    WAITING_PHOTOS = auto()
    PROCESSING = auto()


class TryonState(IntEnum):
    WAITING_LOOK_LINKS = auto()
    WAITING_ITEM_LINK = auto()
    CONFIRMING = auto()


class UpdatePhotoState(IntEnum):
    WAITING_PAYMENT = auto()
    WAITING_NEW_PHOTOS = auto()
