"""
Ready accounts browsing and purchase flow.
Flow: Category (WhatsApp/Telegram) → Account List (paginated) → Detail → Buy (redirect to owner).
"""
import logging

from aiogram import Router, F
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from sqlalchemy import select, func

from models.ready_account import ReadyAccount
from config import OWNER_IDS
from services.user_manager import get_or_create_user
from handlers.common import add_nav, nav_enter, register_screen, safe_edit
from ui import card

logger = logging.getLogger(__name__)
router = Router()

PAGE_SIZE = 5


# ─── Helpers ─────────────────────────────────────────────────────────────────

def _L(lang, ar, en):
    return ar if lang == "ar" else en


def _mask_phone(phone: str | None) -> str:
    """Partially mask a phone number for display."""
    if not phone:
        return "—"
    if len(phone) <= 6:
        return phone[:2] + "****"
    return phone[:3] + "****" + phone[-2:]


# ═════════════════════════════════════════════════════════════════════════════
#  1 · ENTRY — Category Selection
# ═════════════════════════════════════════════════════════════════════════════

@router.callback_query(F.data == "ready_accounts")
async def show_categories(cb: CallbackQuery, db, screen="ready_accounts", from_back=False):
    nav_enter(cb.from_user.id, "ready_accounts", push=not from_back)
    user = await get_or_create_user(db, cb.from_user.id)
    lang = user.language or "ar"

    text = card(
        _L(lang, "📱 حسابات جاهزة", "📱 Ready Accounts"),
        [
            _L(lang, "اختر نوع الحسابات من الأسفل", "Choose account type below"),
        ],
    )

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text=_L(lang, "📱 حسابات واتساب جاهزة", "📱 Ready WhatsApp Accounts"),
            callback_data="ra:whatsapp:0",
        )],
        [InlineKeyboardButton(
            text=_L(lang, "📱 حسابات تيليجرام جاهزة", "📱 Ready Telegram Accounts"),
            callback_data="ra:telegram:0",
        )],
        *add_nav([], lang),
    ])

    await safe_edit(cb, text, kb)
    await cb.answer()


# ═════════════════════════════════════════════════════════════════════════════
#  2 · ACCOUNT LIST — Paginated available accounts
# ═════════════════════════════════════════════════════════════════════════════

@router.callback_query(F.data.startswith("ra:"))
async def show_account_list(cb: CallbackQuery, db, screen=None, from_back=False):
    data = screen or cb.data
    parts = data.split(":")
    account_type = parts[1]
    page = int(parts[2]) if len(parts) > 2 and parts[2].isdigit() else 0

    nav_enter(cb.from_user.id, data, push=not from_back)
    user = await get_or_create_user(db, cb.from_user.id)
    lang = user.language or "ar"

    # Count total available
    total = await db.scalar(
        select(func.count(ReadyAccount.id)).where(
            ReadyAccount.account_type == account_type,
            ReadyAccount.is_sold == False,
        )
    ) or 0

    # Fetch page
    result = await db.execute(
        select(ReadyAccount)
        .where(
            ReadyAccount.account_type == account_type,
            ReadyAccount.is_sold == False,
        )
        .order_by(ReadyAccount.created_at.desc())
        .offset(page * PAGE_SIZE)
        .limit(PAGE_SIZE)
    )
    accounts = result.scalars().all()

    type_label = _L(lang,
        "واتساب" if account_type == "whatsapp" else "تيليجرام",
        "WhatsApp" if account_type == "whatsapp" else "Telegram",
    )

    if not accounts:
        text = card(
            _L(lang, f"📱 حسابات {type_label} جاهزة", f"📱 Ready {type_label} Accounts"),
            [
                _L(lang,
                   "ℹ️ لا توجد حسابات متاحة حالياً.",
                   "ℹ️ No accounts available at the moment."),
            ],
        )
        kb = InlineKeyboardMarkup(inline_keyboard=add_nav([], lang))
        await safe_edit(cb, text, kb)
        return await cb.answer()

    pages = (total + PAGE_SIZE - 1) // PAGE_SIZE

    text = card(
        _L(lang, f"📱 حسابات {type_label} جاهزة", f"📱 Ready {type_label} Accounts"),
        [
            _L(lang,
               f"📦 الحسابات المتاحة: <b>{total}</b>",
               f"📦 Available accounts: <b>{total}</b>"),
            _L(lang,
               "👇 اختر حساب لعرض التفاصيل",
               "👇 Choose an account to view details"),
        ],
    )

    kb: list[list[InlineKeyboardButton]] = []
    for acc in accounts:
        price_str = f"${float(acc.price):.2f}"
        btn_text = f"🔢 {acc.country} - {price_str}"
        kb.append([InlineKeyboardButton(
            text=btn_text,
            callback_data=f"ra_view:{acc.id}",
        )])

    # Pagination
    if pages > 1:
        nav_row: list[InlineKeyboardButton] = []
        if page > 0:
            nav_row.append(InlineKeyboardButton(
                text=_L(lang, "◀️ السابق", "◀️ Previous"),
                callback_data=f"ra:{account_type}:{page - 1}",
            ))
        nav_row.append(InlineKeyboardButton(
            text=f"📄 {page + 1}/{pages}",
            callback_data="noop",
        ))
        if page + 1 < pages:
            nav_row.append(InlineKeyboardButton(
                text=_L(lang, "التالي ▶️", "Next ▶️"),
                callback_data=f"ra:{account_type}:{page + 1}",
            ))
        kb.append(nav_row)

    kb = add_nav(kb, lang)
    await safe_edit(cb, text, InlineKeyboardMarkup(inline_keyboard=kb))
    await cb.answer()


# ═════════════════════════════════════════════════════════════════════════════
#  3 · ACCOUNT DETAIL — Full info with masked phone
# ═════════════════════════════════════════════════════════════════════════════

@router.callback_query(F.data.startswith("ra_view:"))
async def show_account_detail(cb: CallbackQuery, db, screen=None, from_back=False):
    data = screen or cb.data
    parts = data.split(":")
    account_id = int(parts[1])

    nav_enter(cb.from_user.id, data, push=not from_back)
    user = await get_or_create_user(db, cb.from_user.id)
    lang = user.language or "ar"

    result = await db.execute(
        select(ReadyAccount).where(ReadyAccount.id == account_id)
    )
    acc = result.scalar_one_or_none()

    if not acc or acc.is_sold:
        await cb.answer(
            _L(lang, "❌ الحساب غير متاح", "❌ Account not available"),
            show_alert=True,
        )
        return

    type_label = _L(lang,
        "واتساب" if acc.account_type == "whatsapp" else "تيليجرام",
        "WhatsApp" if acc.account_type == "whatsapp" else "Telegram",
    )
    price_str = f"${float(acc.price):.2f}"
    masked = _mask_phone(acc.phone_number)
    desc = acc.description or _L(lang, "—", "—")

    if lang == "ar":
        text = card(f"📱 تفاصيل حساب {type_label}", [
            f"🌍 الدولة: <b>{acc.country}</b>",
            f"📞 الرقم: <b>{masked}</b>",
            f"💰 السعر: <b>{price_str}</b>",
            None,
            f"📝 الوصف: {desc}",
        ])
    else:
        text = card(f"📱 {type_label} Account Details", [
            f"🌍 Country: <b>{acc.country}</b>",
            f"📞 Number: <b>{masked}</b>",
            f"💰 Price: <b>{price_str}</b>",
            None,
            f"📝 Description: {desc}",
        ])

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text=_L(lang, "🛒 شراء", "🛒 Buy"),
            callback_data=f"ra_buy:{acc.id}",
        )],
        *add_nav([], lang),
    ])

    await safe_edit(cb, text, kb)
    await cb.answer()


# ═════════════════════════════════════════════════════════════════════════════
#  4 · BUY — Redirect to owner contact
# ═════════════════════════════════════════════════════════════════════════════

@router.callback_query(F.data.startswith("ra_buy:"))
async def buy_account(cb: CallbackQuery, db, screen=None, from_back=False):
    data = screen or cb.data
    parts = data.split(":")
    account_id = int(parts[1])

    nav_enter(cb.from_user.id, data, push=not from_back)
    user = await get_or_create_user(db, cb.from_user.id)
    lang = user.language or "ar"

    # Verify account still available
    result = await db.execute(
        select(ReadyAccount).where(ReadyAccount.id == account_id)
    )
    acc = result.scalar_one_or_none()

    if not acc or acc.is_sold:
        await cb.answer(
            _L(lang, "❌ الحساب غير متاح أو تم بيعه", "❌ Account unavailable or already sold"),
            show_alert=True,
        )
        return

    # Build owner contact buttons (same pattern as support handler)
    owner_lines: list[str] = []
    rows: list[list[InlineKeyboardButton]] = []

    for i, owner_id in enumerate(OWNER_IDS, 1):
        try:
            chat = await cb.bot.get_chat(owner_id)
            uname = f"@{chat.username}" if chat.username else (chat.first_name or str(owner_id))
            link = f"https://t.me/{chat.username}" if chat.username else f"tg://user?id={owner_id}"
        except Exception:
            uname = str(owner_id)
            link = f"tg://user?id={owner_id}"

        if lang == "ar":
            owner_lines.append(f"👨‍💻 المالك {i}: <b>{uname}</b>")
            rows.append([InlineKeyboardButton(text=f"💬 تواصل مع المالك {i}: {uname}", url=link)])
        else:
            owner_lines.append(f"👨‍💻 Owner {i}: <b>{uname}</b>")
            rows.append([InlineKeyboardButton(text=f"💬 Contact Owner {i}: {uname}", url=link)])

    rows.extend(add_nav([], lang))

    if lang == "ar":
        text = card("🛒 شراء حساب جاهز", [
            "للإتمام عملية الشراء تواصل مع أحد المالكين",
            "---",
            *owner_lines,
            None,
            f"📱 الحساب: #{acc.id} — {acc.country}",
            f"💰 السعر: <b>${float(acc.price):.2f}</b>",
        ])
    else:
        text = card("🛒 Buy Ready Account", [
            "To complete the purchase, contact one of the owners",
            "---",
            *owner_lines,
            None,
            f"📱 Account: #{acc.id} — {acc.country}",
            f"💰 Price: <b>${float(acc.price):.2f}</b>",
        ])

    await safe_edit(cb, text, InlineKeyboardMarkup(inline_keyboard=rows))
    await cb.answer()


# ─── Screen Registration ────────────────────────────────────────────────────

def register_screens():
    register_screen("ready_accounts", show_categories)
    register_screen("ra:", show_account_list)
    register_screen("ra_view:", show_account_detail)
    register_screen("ra_buy:", buy_account)

register_screens()
