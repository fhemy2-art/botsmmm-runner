"""
Ready-accounts admin panel — manage pre-made WhatsApp / Telegram accounts.
Only accessible by the owner (OWNER_IDS from config).
"""
import logging
from datetime import datetime
from decimal import Decimal, InvalidOperation

from aiogram import Router, F
from aiogram.types import CallbackQuery, Message, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from sqlalchemy import select, func as sa_func

from config import OWNER_IDS
from models.ready_account import ReadyAccount
from ui import card

logger = logging.getLogger(__name__)
router = Router()

ITEMS_PER_PAGE = 5


# --- FSM States ---
class AddAccountStates(StatesGroup):
    waiting_type = State()
    waiting_country = State()
    waiting_phone = State()
    waiting_price = State()
    waiting_desc = State()


# --- Helpers ---
def _is_owner(user_id: int) -> bool:
    return user_id in OWNER_IDS


def _owner_only(callback: CallbackQuery) -> bool:
    return _is_owner(callback.from_user.id)


async def _safe_edit(callback: CallbackQuery, text: str, kb: InlineKeyboardMarkup) -> None:
    try:
        await callback.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
    except Exception as exc:
        if "message is not modified" not in str(exc).lower():
            logger.debug("edit failed: %s", exc)


def _back_to_owner() -> list[list[InlineKeyboardButton]]:
    return [
        [InlineKeyboardButton(text="🔙 رجوع للوحة المالك", callback_data="owner:panel")],
        [InlineKeyboardButton(text="🏠 الرئيسية", callback_data="main_menu")],
    ]


def _back_to_ra() -> list[list[InlineKeyboardButton]]:
    return [
        [InlineKeyboardButton(text="🔙 رجوع لإدارة الحسابات", callback_data="owner:ready_accounts")],
        *_back_to_owner(),
    ]


def _account_status_icon(account: ReadyAccount) -> str:
    return "🔴 مباع" if account.is_sold else "🟢 متاح"


def _account_type_icon(account_type: str) -> str:
    return "📱" if account_type == "whatsapp" else "✈️"


# --- Main Ready-Accounts Panel ---
@router.callback_query(F.data == "owner:ready_accounts")
async def ready_accounts_panel(callback: CallbackQuery, db, state: FSMContext):
    if not _owner_only(callback):
        await callback.answer("⛔ غير مصرح لك", show_alert=True)
        return

    await state.clear()

    total = await db.scalar(
        select(sa_func.count()).select_from(ReadyAccount)
    ) or 0
    available = await db.scalar(
        select(sa_func.count()).select_from(ReadyAccount).where(ReadyAccount.is_sold == False)
    ) or 0
    sold = total - available

    text = card("📦 إدارة الحسابات الجاهزة", [
        "📊 ملخص الحسابات",
        "---",
        f"📦 الإجمالي: <b>{total}</b>",
        f"🟢 متاح: <b>{available}</b>",
        f"🔴 مباع: <b>{sold}</b>",
        None,
        "💡 يمكنك إضافة وإدارة الحسابات الجاهزة من هنا",
    ])

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📋 عرض الحسابات", callback_data="owner:ra_list:0")],
        [InlineKeyboardButton(text="➕ إضافة حساب", callback_data="owner:ra_add")],
        *_back_to_owner(),
    ])
    await _safe_edit(callback, text, kb)
    await callback.answer()


# --- List Accounts (paginated) ---
@router.callback_query(F.data.startswith("owner:ra_list"))
async def ra_list(callback: CallbackQuery, db):
    if not _owner_only(callback):
        await callback.answer("⛔ غير مصرح لك", show_alert=True)
        return

    parts = callback.data.split(":")
    page = int(parts[2]) if len(parts) > 2 else 0

    total = await db.scalar(
        select(sa_func.count()).select_from(ReadyAccount)
    ) or 0

    result = await db.execute(
        select(ReadyAccount)
        .order_by(ReadyAccount.created_at.desc())
        .offset(page * ITEMS_PER_PAGE)
        .limit(ITEMS_PER_PAGE)
    )
    accounts = result.scalars().all()

    if not accounts and page == 0:
        text = card("📋 قائمة الحسابات", [
            "لا توجد حسابات حالياً.",
            None,
            "💡 اضغط ➕ لإضافة حساب جديد",
        ])
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="➕ إضافة حساب", callback_data="owner:ra_add")],
            *_back_to_ra(),
        ])
        await _safe_edit(callback, text, kb)
        await callback.answer()
        return

    rows = [
        f"📊 الصفحة {page + 1} — إجمالي: {total}",
        "---",
    ]
    for acc in accounts:
        icon = _account_type_icon(acc.account_type)
        status = _account_status_icon(acc)
        rows.append(
            f"  {icon} #{acc.id} | {acc.account_type} | {acc.country} | "
            f"${float(acc.price):.2f} | {status}"
        )

    text = card("📋 قائمة الحسابات", rows)

    buttons: list[list[InlineKeyboardButton]] = []

    # Account detail buttons
    for acc in accounts:
        icon = _account_type_icon(acc.account_type)
        sold_tag = " [مباع]" if acc.is_sold else ""
        buttons.append([
            InlineKeyboardButton(
                text=f"{icon} #{acc.id} — {acc.phone_number}{sold_tag}",
                callback_data=f"owner:ra_edit:{acc.id}",
            )
        ])

    # Pagination row
    nav_row: list[InlineKeyboardButton] = []
    if page > 0:
        nav_row.append(InlineKeyboardButton(text="◀️ السابق", callback_data=f"owner:ra_list:{page - 1}"))
    if (page + 1) * ITEMS_PER_PAGE < total:
        nav_row.append(InlineKeyboardButton(text="▶️ التالي", callback_data=f"owner:ra_list:{page + 1}"))
    if nav_row:
        buttons.append(nav_row)

    buttons.extend(_back_to_ra())

    kb = InlineKeyboardMarkup(inline_keyboard=buttons)
    await _safe_edit(callback, text, kb)
    await callback.answer()


# --- Add Account: step 1 — choose type ---
@router.callback_query(F.data == "owner:ra_add")
async def ra_add_start(callback: CallbackQuery, db, state: FSMContext):
    if not _owner_only(callback):
        await callback.answer("⛔ غير مصرح لك", show_alert=True)
        return

    await state.clear()

    text = card("➕ إضافة حساب جاهز", [
        "الخطوة 1 من 5",
        "---",
        "اختر نوع الحساب:",
    ])

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="📱 WhatsApp", callback_data="owner:ra_type:whatsapp"),
            InlineKeyboardButton(text="✈️ Telegram", callback_data="owner:ra_type:telegram"),
        ],
        [InlineKeyboardButton(text="❌ إلغاء", callback_data="owner:ready_accounts")],
    ])
    await _safe_edit(callback, text, kb)
    await callback.answer()


@router.callback_query(F.data.startswith("owner:ra_type:"))
async def ra_add_type(callback: CallbackQuery, db, state: FSMContext):
    if not _owner_only(callback):
        await callback.answer("⛔", show_alert=True)
        return

    account_type = callback.data.split(":")[2]  # whatsapp or telegram
    await state.update_data(account_type=account_type)
    await state.set_state(AddAccountStates.waiting_country)

    icon = _account_type_icon(account_type)
    text = card("➕ إضافة حساب جاهز", [
        "الخطوة 2 من 5",
        "---",
        f"النوع: <b>{icon} {account_type}</b>",
        None,
        "أرسل اسم الدولة:",
        "مثال: <code>السعودية</code>",
    ])

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="❌ إلغاء", callback_data="owner:ready_accounts")],
    ])
    await _safe_edit(callback, text, kb)
    await callback.answer()


# --- Add Account: step 2 — country ---
@router.message(AddAccountStates.waiting_country)
async def ra_add_country(message: Message, db, state: FSMContext):
    if not _is_owner(message.from_user.id):
        return

    country = (message.text or "").strip()
    if not country:
        await message.answer("❌ يرجى إرسال اسم الدولة.")
        return

    await state.update_data(country=country)
    await state.set_state(AddAccountStates.waiting_phone)

    data = await state.get_data()
    icon = _account_type_icon(data["account_type"])

    text = card("➕ إضافة حساب جاهز", [
        "الخطوة 3 من 5",
        "---",
        f"النوع: <b>{icon} {data['account_type']}</b>",
        f"الدولة: <b>{country}</b>",
        None,
        "أرسل رقم الهاتف:",
        "مثال: <code>+966501234567</code>",
    ])

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="❌ إلغاء", callback_data="owner:ready_accounts")],
    ])
    await message.answer(text, reply_markup=kb, parse_mode="HTML")


# --- Add Account: step 3 — phone ---
@router.message(AddAccountStates.waiting_phone)
async def ra_add_phone(message: Message, db, state: FSMContext):
    if not _is_owner(message.from_user.id):
        return

    phone = (message.text or "").strip()
    if not phone:
        await message.answer("❌ يرجى إرسال رقم الهاتف.")
        return

    await state.update_data(phone_number=phone)
    await state.set_state(AddAccountStates.waiting_price)

    data = await state.get_data()
    icon = _account_type_icon(data["account_type"])

    text = card("➕ إضافة حساب جاهز", [
        "الخطوة 4 من 5",
        "---",
        f"النوع: <b>{icon} {data['account_type']}</b>",
        f"الدولة: <b>{data['country']}</b>",
        f"الرقم: <b>{phone}</b>",
        None,
        "أرسل السعر بالدولار:",
        "مثال: <code>15.00</code>",
    ])

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="❌ إلغاء", callback_data="owner:ready_accounts")],
    ])
    await message.answer(text, reply_markup=kb, parse_mode="HTML")


# --- Add Account: step 4 — price ---
@router.message(AddAccountStates.waiting_price)
async def ra_add_price(message: Message, db, state: FSMContext):
    if not _is_owner(message.from_user.id):
        return

    try:
        price = Decimal(message.text.strip())
        if price <= 0:
            raise ValueError
    except (InvalidOperation, ValueError, AttributeError):
        await message.answer("❌ سعر غير صالح. أرسل رقماً موجباً.")
        return

    await state.update_data(price=str(price))
    await state.set_state(AddAccountStates.waiting_desc)

    data = await state.get_data()
    icon = _account_type_icon(data["account_type"])

    text = card("➕ إضافة حساب جاهز", [
        "الخطوة 5 من 5",
        "---",
        f"النوع: <b>{icon} {data['account_type']}</b>",
        f"الدولة: <b>{data['country']}</b>",
        f"الرقم: <b>{data['phone_number']}</b>",
        f"السعر: <b>${float(price):.2f}</b>",
        None,
        "أرسل وصف الحساب:",
        "مثال: <code>حساب واتساب جاهز مع OTP</code>",
    ])

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="❌ إلغاء", callback_data="owner:ready_accounts")],
    ])
    await message.answer(text, reply_markup=kb, parse_mode="HTML")


# --- Add Account: step 5 — description & save ---
@router.message(AddAccountStates.waiting_desc)
async def ra_add_desc(message: Message, db, state: FSMContext):
    if not _is_owner(message.from_user.id):
        return

    description = (message.text or "").strip()
    if not description:
        await message.answer("❌ يرجى إرسال وصف الحساب.")
        return

    data = await state.get_data()
    await state.clear()

    account = ReadyAccount(
        account_type=data["account_type"],
        country=data["country"],
        phone_number=data["phone_number"],
        description=description,
        price=Decimal(data["price"]),
        is_sold=False,
    )
    db.add(account)
    await db.commit()
    await db.refresh(account)

    icon = _account_type_icon(account.account_type)
    text = card("✅ تم إضافة الحساب بنجاح", [
        f"🆔 المعرف: <b>#{account.id}</b>",
        f"النوع: <b>{icon} {account.account_type}</b>",
        f"الدولة: <b>{account.country}</b>",
        f"الرقم: <b>{account.phone_number}</b>",
        f"السعر: <b>${float(account.price):.2f}</b>",
        f"الوصف: <b>{account.description}</b>",
    ])

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ إضافة حساب آخر", callback_data="owner:ra_add")],
        [InlineKeyboardButton(text="📋 عرض الحسابات", callback_data="owner:ra_list:0")],
        *_back_to_ra(),
    ])
    await message.answer(text, reply_markup=kb, parse_mode="HTML")


# --- View / Edit Account ---
@router.callback_query(F.data.startswith("owner:ra_edit:"))
async def ra_view_account(callback: CallbackQuery, db):
    if not _owner_only(callback):
        await callback.answer("⛔ غير مصرح لك", show_alert=True)
        return

    account_id = int(callback.data.split(":")[2])
    account = await db.get(ReadyAccount, account_id)

    if not account:
        await callback.answer("❌ الحساب غير موجود", show_alert=True)
        return

    icon = _account_type_icon(account.account_type)
    status = _account_status_icon(account)

    rows = [
        f"🆔 المعرف: <b>#{account.id}</b>",
        f"النوع: <b>{icon} {account.account_type}</b>",
        f"الدولة: <b>{account.country}</b>",
        f"الرقم: <b>{account.phone_number}</b>",
        f"السعر: <b>${float(account.price):.2f}</b>",
        f"الحالة: <b>{status}</b>",
        "---",
        f"الوصف: <b>{account.description}</b>",
        f"📅 تاريخ الإضافة: <b>{account.created_at.strftime('%Y-%m-%d %H:%M') if account.created_at else '-'}</b>",
    ]

    if account.is_sold:
        rows.append(f"👤 المشتري: <b>{account.buyer_id or '-'}</b>")
        rows.append(
            f"📅 تاريخ البيع: <b>"
            f"{account.sold_at.strftime('%Y-%m-%d %H:%M') if account.sold_at else '-'}</b>"
        )

    text = card("📦 تفاصيل الحساب", rows)

    toggle_text = "🟢 تعيين كمتاح" if account.is_sold else "🔴 تعيين كمباع"
    toggle_cb = f"owner:ra_toggle:{account.id}"

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=toggle_text, callback_data=toggle_cb)],
        [InlineKeyboardButton(text="🗑 حذف الحساب", callback_data=f"owner:ra_del:{account.id}")],
        *_back_to_ra(),
    ])
    await _safe_edit(callback, text, kb)
    await callback.answer()


# --- Toggle Sold / Unsold ---
@router.callback_query(F.data.startswith("owner:ra_toggle:"))
async def ra_toggle_sold(callback: CallbackQuery, db):
    if not _owner_only(callback):
        await callback.answer("⛔", show_alert=True)
        return

    account_id = int(callback.data.split(":")[2])
    account = await db.get(ReadyAccount, account_id)

    if not account:
        await callback.answer("❌ الحساب غير موجود", show_alert=True)
        return

    if account.is_sold:
        account.is_sold = False
        account.buyer_id = None
        account.sold_at = None
        await callback.answer("🟢 تم تعيين الحساب كمتاح", show_alert=True)
    else:
        account.is_sold = True
        account.sold_at = datetime.utcnow()
        await callback.answer("🔴 تم تعيين الحساب كمباع", show_alert=True)

    await db.commit()
    # Refresh the detail view
    await ra_view_account(callback, db)


# --- Delete Account (confirmation) ---
@router.callback_query(F.data.startswith("owner:ra_del:"))
async def ra_delete_confirm(callback: CallbackQuery, db):
    if not _owner_only(callback):
        await callback.answer("⛔", show_alert=True)
        return

    account_id = int(callback.data.split(":")[2])
    account = await db.get(ReadyAccount, account_id)

    if not account:
        await callback.answer("❌ الحساب غير موجود", show_alert=True)
        return

    icon = _account_type_icon(account.account_type)
    text = card("⚠️ تأكيد الحذف", [
        "هل أنت متأكد من حذف هذا الحساب؟",
        "---",
        f"🆔 المعرف: <b>#{account.id}</b>",
        f"النوع: <b>{icon} {account.account_type}</b>",
        f"الرقم: <b>{account.phone_number}</b>",
        f"السعر: <b>${float(account.price):.2f}</b>",
        None,
        "⚠️ لا يمكن التراجع عن هذا الإجراء!",
    ])

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="✅ نعم، احذف", callback_data=f"owner:ra_del_yes:{account.id}"),
            InlineKeyboardButton(text="❌ لا، تراجع", callback_data=f"owner:ra_edit:{account.id}"),
        ],
        *_back_to_ra(),
    ])
    await _safe_edit(callback, text, kb)
    await callback.answer()


@router.callback_query(F.data.startswith("owner:ra_del_yes:"))
async def ra_delete_execute(callback: CallbackQuery, db):
    if not _owner_only(callback):
        await callback.answer("⛔", show_alert=True)
        return

    account_id = int(callback.data.split(":")[2])
    account = await db.get(ReadyAccount, account_id)

    if not account:
        await callback.answer("❌ الحساب غير موجود", show_alert=True)
        return

    await db.delete(account)
    await db.commit()

    text = card("🗑 تم حذف الحساب", [
        f"تم حذف الحساب <b>#{account_id}</b> بنجاح.",
    ])

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📋 عرض الحسابات", callback_data="owner:ra_list:0")],
        *_back_to_ra(),
    ])
    await _safe_edit(callback, text, kb)
    await callback.answer("🗑 تم الحذف", show_alert=True)
