"""
Admin: Provider management via commands (legacy — inline panel in admin/services.py).
Commands /addprovider and /providers still work as shortcuts.
"""
import logging

from aiogram import Router, F
from aiogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.filters import Command

from repositories.provider_repo import get_all_providers
from config import ADMIN_IDS
from handlers.admin.services import is_admin_or_mod

logger = logging.getLogger(__name__)
router = Router()


def is_admin(user_id: int) -> bool:
    return is_admin_or_mod(user_id)


@router.message(Command("addprovider"))
async def cmd_add_provider(message: Message):
    if not is_admin(message.from_user.id):
        return
    await message.answer(
        "استخدم لوحة الإدارة لإضافة المزودين 👇",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔌 إضافة مزود", callback_data="adm:add_provider")],
            [InlineKeyboardButton(text="🛡️ لوحة الإدارة", callback_data="adm:panel")],
        ])
    )


@router.message(Command("providers"))
async def cmd_list_providers(message: Message, db):
    if not is_admin(message.from_user.id):
        return
    providers = await get_all_providers(db)
    if not providers:
        await message.answer(
            "❌ لا يوجد مزودين.",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="➕ إضافة مزود", callback_data="adm:add_provider")],
            ])
        )
        return

    lines = ["🔌 <b>المزودين:</b>\n"]
    for p in providers:
        icon = "🟢" if p.status else "🔴"
        lines.append(f"{icon} #{p.id} | {p.name}\n🔗 {p.api_url}\n{'─'*20}")
    await message.answer(
        "\n".join(lines),
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔌 إدارة المزودين", callback_data="adm:providers_list")],
        ])
    )
