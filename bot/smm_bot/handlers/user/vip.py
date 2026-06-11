"""VIP membership handler."""
import logging

from aiogram import Router, F
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton

from services.user_manager import get_or_create_user, sync_vip_level
from i18n import t, get_vip_level, get_vip_name, get_vip_pct
from handlers.common import add_nav, nav_enter, register_screen, safe_edit

logger = logging.getLogger(__name__)
router = Router()


@router.callback_query(F.data == "my_vip")
async def show_vip(callback: CallbackQuery, db, screen: str = "my_vip", from_back: bool = False):
    nav_enter(callback.from_user.id, "my_vip", push=not from_back)
    user = await get_or_create_user(db, callback.from_user.id)
    lang = user.language or "ar"
    spent = float(user.total_spent or 0)
    await sync_vip_level(db, user)

    level = get_vip_level(spent)
    tier_name = get_vip_name(level, lang)
    pct = get_vip_pct(level)

    text = t("vip_info", lang, tier=tier_name, spent=spent, pct=pct)
    kb = InlineKeyboardMarkup(inline_keyboard=add_nav([], lang))
    await safe_edit(callback, text, kb)
    await callback.answer()


register_screen("my_vip", show_vip)
