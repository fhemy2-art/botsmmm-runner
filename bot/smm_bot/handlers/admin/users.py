"""
Admin: Full user management — search, profile view, balance management, broadcast.
"""
import logging
from decimal import Decimal

from aiogram import Router, F
from aiogram.types import CallbackQuery, Message, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from sqlalchemy import select, func

from models.user import User
from models.order import Order
from repositories.user_repo import (
    count_users, get_all_user_ids,
    add_balance as repo_add_balance,
    get_user, get_user_by_account_number, get_user_by_username,
)
from repositories.order_repo import count_orders, count_user_orders, total_revenue
from config import ADMIN_IDS
from handlers.admin.services import is_admin_or_mod

logger = logging.getLogger(__name__)
router = Router()


class AddBalanceStates(StatesGroup):
    waiting_user_id = State()
    waiting_amount = State()


class DeductBalanceStates(StatesGroup):
    waiting_user_id = State()
    waiting_amount = State()


class BroadcastStates(StatesGroup):
    waiting_message = State()
    waiting_confirm = State()


class SearchUserStates(StatesGroup):
    waiting_query = State()


def is_admin(user_id: int) -> bool:
    return is_admin_or_mod(user_id)


def _admin_kb(*rows, back: str = "adm:back") -> InlineKeyboardMarkup:
    btns = list(rows)
    btns.append([
        InlineKeyboardButton(text="◀️ رجوع", callback_data=back),
        InlineKeyboardButton(text="🏠 الرئيسية", callback_data="adm:panel"),
    ])
    return InlineKeyboardMarkup(inline_keyboard=btns)


async def _safe_edit(callback: CallbackQuery, text: str, kb: InlineKeyboardMarkup) -> None:
    try:
        await callback.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
    except Exception as exc:
        if "message is not modified" not in str(exc).lower():
            try:
                await callback.message.answer(text, reply_markup=kb, parse_mode="HTML")
            except Exception:
                pass


# ════════════════════════════════════════════════════════════════
#  USER MANAGEMENT PANEL
# ════════════════════════════════════════════════════════════════

@router.callback_query(F.data == "adm:users")
async def show_users_panel(callback: CallbackQuery, db):
    if not is_admin(callback.from_user.id):
        return

    user_count = await count_users(db)
    order_count = await count_orders(db)
    revenue = await total_revenue(db)

    total_bal = await db.scalar(select(func.sum(User.balance)).select_from(User)) or 0
    active_today = await db.scalar(
        select(func.count()).select_from(Order)
        .where(Order.status.in_(["pending", "processing"]))
    ) or 0

    text = (
        "🔷  <b>𝑲𝒊𝒓𝒂 · إدارة المستخدمين</b>  🔷\n"
        "<i>⟡  لوحة إحصائيات المستخدمين  ⟡</i>\n"
        "\n"
        "┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄\n"
        "  <b>◈ إحصائيات عامة ◈</b>\n"
        "\n"
        f"👤 إجمالي المستخدمين  •  <code>{user_count:,}</code>\n"
        f"📦 إجمالي الطلبات  •  <code>{order_count:,}</code>\n"
        f"🔄 نشطة الآن  •  <code>{active_today:,}</code>\n"
        f"💵 الإيرادات  •  <code>${revenue:.2f}</code>\n"
        f"💳 أرصدة المستخدمين  •  <code>${float(total_bal):.2f}</code>\n"
        "\n"
        "<i>◇  𝑲𝒊𝒓𝒂 · كيرا  ◇</i>\n"
        "<i>✦  NEXUS SMM PANEL  ✦</i>"
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="🔍 بحث عن مستخدم", callback_data="adm:searchuser"),
            InlineKeyboardButton(text="💳 شحن رصيد", callback_data="adm:addbal"),
        ],
        [
            InlineKeyboardButton(text="💸 خصم رصيد", callback_data="adm:deductbal"),
            InlineKeyboardButton(text="📢 إشعار جماعي", callback_data="adm:broadcast"),
        ],
        [
            InlineKeyboardButton(text="◀️ رجوع", callback_data="adm:back"),
            InlineKeyboardButton(text="🏠 الرئيسية", callback_data="adm:panel"),
        ],
    ])
    await _safe_edit(callback, text, kb)
    await callback.answer()


# ════════════════════════════════════════════════════════════════
#  USER SEARCH & PROFILE
# ════════════════════════════════════════════════════════════════

@router.callback_query(F.data == "adm:searchuser")
async def search_user_start(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        return
    await state.set_state(SearchUserStates.waiting_query)
    await state.update_data(ui_chat_id=callback.message.chat.id, ui_message_id=callback.message.message_id)
    await callback.message.edit_text(
        "🔷  <b>𝑲𝒊𝒓𝒂 · بحث عن مستخدم</b>  🔷\n"
        "<i>⟡  أدخل بيانات البحث  ⟡</i>\n"
        "\n"
        "┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄\n"
        "  <b>◈ طرق البحث ◈</b>\n"
        "\n"
        "🆔 ID المستخدم  •  <code>أرقام فقط</code>\n"
        "👤 اسم المستخدم  •  <code>@username</code>\n"
        "\n"
        "<i>أرسل /cancel للإلغاء</i>"
    )
    await callback.answer()


@router.message(SearchUserStates.waiting_query)
async def search_user_result(message: Message, state: FSMContext, db):
    if not is_admin(message.from_user.id):
        return
    if message.text and message.text.strip() == "/cancel":
        await state.clear()
        return

    data = await state.get_data()
    await state.clear()
    query = (message.text or "").strip().lstrip("@")
    user = None

    if query.isdigit():
        user = await get_user(db, int(query))
    else:
        result = await db.execute(
            select(User).where(User.username.ilike(f"%{query}%"))
        )
        user = result.scalar_one_or_none()

    try:
        await message.delete()
    except Exception:
        pass

    if not user:
        text = (
            "┌──── 🔍 بحث ────\n"
            "│  ❌ المستخدم غير موجود.\n"
            "└──────────────────────"
        )
        try:
            await message.bot.edit_message_text(
                chat_id=data["ui_chat_id"], message_id=data["ui_message_id"],
                text=text,
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="◀️ رجوع", callback_data="adm:users")]
                ])
            )
        except Exception:
            await message.answer(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="◀️ رجوع", callback_data="adm:users")]
            ]))
        return

    await _show_user_profile_msg(message, data, user, db)


async def _show_user_profile_msg(message: Message, state_data: dict, user: User, db) -> None:
    order_count = await count_user_orders(db, user.id)
    username_str = f"@{user.username}" if user.username else "—"
    vip_levels = {0: "🥉 برونزي", 1: "🥈 فضي", 2: "🥇 ذهبي", 3: "💎 بلاتيني"}
    vip = vip_levels.get(user.vip_level or 0, "🥉 برونزي")
    joined = user.created_at.strftime("%Y-%m-%d") if user.created_at else "—"

    text = (
        "🔷  <b>𝑲𝒊𝒓𝒂 · ملف المستخدم</b>  🔷\n"
        "<i>⟡  بيانات الحساب  ⟡</i>\n"
        "\n"
        "┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄\n"
        "  <b>◈ معلومات الحساب ◈</b>\n"
        "\n"
        f"🆔 ID  •  <code>{user.id}</code>\n"
        f"👤 المستخدم  •  <code>{username_str}</code>\n"
        f"📛 الاسم  •  <code>{user.first_name or '—'}</code>\n"
        "\n"
        "┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄\n"
        "  <b>◈ المحفظة والنشاط ◈</b>\n"
        "\n"
        f"💰 الرصيد  •  <code>${float(user.balance):.4f}</code>\n"
        f"💸 المصروف  •  <code>${float(user.total_spent or 0):.4f}</code>\n"
        f"📦 الطلبات  •  <code>{order_count:,}</code>\n"
        f"👑 العضوية  •  <code>{vip}</code>\n"
        f"📅 الانضمام  •  <code>{joined}</code>\n"
        "\n"
        "<i>◇  𝑲𝒊𝒓𝒂 · كيرا  ◇</i>\n"
        "<i>✦  NEXUS SMM PANEL  ✦</i>"
    )
    uid = user.id
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="➕ شحن رصيد", callback_data=f"adm:addbal:{uid}"),
            InlineKeyboardButton(text="➖ خصم رصيد", callback_data=f"adm:deductbal:{uid}"),
        ],
        [InlineKeyboardButton(text="📋 طلبات المستخدم", callback_data=f"adm:userorders:{uid}:0")],
        [InlineKeyboardButton(text="◀️ رجوع", callback_data="adm:users")],
    ])
    try:
        await message.bot.edit_message_text(
            chat_id=state_data["ui_chat_id"], message_id=state_data["ui_message_id"],
            text=text, reply_markup=kb, parse_mode="HTML",
        )
    except Exception:
        await message.answer(text, reply_markup=kb, parse_mode="HTML")


@router.callback_query(F.data.startswith("adm:userorders:"))
async def show_user_orders(callback: CallbackQuery, db):
    if not is_admin(callback.from_user.id):
        return
    from models.service import Service

    parts = callback.data.split(":")
    uid = int(parts[2])
    page = int(parts[3]) if len(parts) > 3 else 0
    per_page = 6

    user = await get_user(db, uid)
    if not user:
        await callback.answer("المستخدم غير موجود")
        return

    total = await count_user_orders(db, uid)
    total_pages = max(1, (total + per_page - 1) // per_page)

    result = await db.execute(
        select(Order, Service)
        .outerjoin(Service, Order.service_id == Service.id)
        .where(Order.user_id == uid)
        .order_by(Order.created_at.desc())
        .offset(page * per_page)
        .limit(per_page)
    )
    rows = result.all()

    username_str = f"@{user.username}" if user.username else str(uid)
    text = (
        f"┌──── 📋 طلبات {username_str} ────\n"
        f"│  إجمالي: <b>{total:,}</b>  |  صفحة {page+1}/{total_pages}\n"
        "└──────────────────────"
    )

    STATUS_ICONS = {"pending": "⏳", "processing": "🔄", "completed": "✅", "partial": "⚠️", "canceled": "❌"}
    buttons = []
    for order, service in rows:
        icon = STATUS_ICONS.get(order.status, "❓")
        svc_name = service.name[:20] if service else "—"
        date_str = order.created_at.strftime("%m/%d") if order.created_at else "—"
        buttons.append([InlineKeyboardButton(
            text=f"#{order.id} {icon} {svc_name}  💰${float(order.charge):.2f}  {date_str}",
            callback_data="noop",
        )])

    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton(text="◀️", callback_data=f"adm:userorders:{uid}:{page-1}"))
    nav.append(InlineKeyboardButton(text=f"{page+1}/{total_pages}", callback_data="noop"))
    if page < total_pages - 1:
        nav.append(InlineKeyboardButton(text="▶️", callback_data=f"adm:userorders:{uid}:{page+1}"))
    if nav:
        buttons.append(nav)
    buttons.append([InlineKeyboardButton(text="◀️ رجوع", callback_data="adm:users")])

    await _safe_edit(callback, text, InlineKeyboardMarkup(inline_keyboard=buttons))
    await callback.answer()


# ════════════════════════════════════════════════════════════════
#  ADD BALANCE
# ════════════════════════════════════════════════════════════════

@router.callback_query(F.data.startswith("adm:addbal"))
async def start_add_balance(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        return

    parts = callback.data.split(":")
    preset_uid = int(parts[2]) if len(parts) > 2 and parts[2].isdigit() else None

    if preset_uid:
        await state.set_state(AddBalanceStates.waiting_amount)
        await state.update_data(target_user_id=preset_uid)
        await callback.message.edit_text(
            f"┌──── 💳 شحن رصيد ────\n│  المستخدم: <code>{preset_uid}</code>\n│  أرسل المبلغ بالدولار:\n│  مثال: <code>5</code>\n│  /cancel للإلغاء\n└──────────────────────",
            parse_mode="HTML",
        )
    else:
        await state.set_state(AddBalanceStates.waiting_user_id)
        await callback.message.edit_text(
            "╔══════════════════════════╗\n"
            "║  ◈  <b>شحن رصيد مستخدم</b>  ◈    \n"
            "╠══════════════════════════╣\n"
            "  أرسل <b>أي من التالي:</b>\n"
            "  ◆ رقم التيليجرام: <code>5219348201</code>\n"
            "  ◆ رقم الحساب:    <code>01001</code>\n"
            "  ◆ البريد: <code>kira01001@kira-smm.com</code>\n"
            "  ◆ يوزرنيم: <code>@username</code>\n"
            "╠══════════════════════════╣\n"
            "  /cancel للإلغاء\n"
            "╚══════════════════════════╝",
            parse_mode="HTML",
        )
    await callback.answer()


async def _resolve_user_target(db, raw: str):
    """
    Resolve a user from any identifier:
    - @username or plain non-numeric text → username search
    - kira01001 / kira01001@kira-smm.com / kira01001@nexus.io → account number
    - pure number ≤ 999999 → account number; larger → Telegram ID
    Returns (user_id, found_user) or (None, None) if not found.
    """
    raw_lower = raw.lower().strip()

    # 1) Username (@username or non-numeric string)
    if raw.startswith("@") or (not raw.lstrip("-").isdigit() and not raw_lower.startswith("kira")):
        found = await get_user_by_username(db, raw)
        return (found.id if found else None, found)

    # 2) kira-style email/account: kira01001 or kira01001@kira-smm.com or kira01001@nexus.io
    if raw_lower.startswith("kira"):
        num_str = raw_lower.replace("kira", "", 1).split("@")[0].strip()
        if num_str.isdigit():
            found = await get_user_by_account_number(db, int(num_str))
            return (found.id if found else None, found)

    # 3) Pure number
    if raw.isdigit():
        num = int(raw)
        if num <= 999999:
            found = await get_user_by_account_number(db, num)
            if found:
                return (found.id, found)
        # Fall back to Telegram ID (even if not in DB yet — let add_balance create)
        return (num, None)

    return (None, None)


@router.message(AddBalanceStates.waiting_user_id)
async def get_user_id_for_balance(message: Message, state: FSMContext, db):
    """Accept Telegram ID, account number, kira email, or @username."""
    if not is_admin(message.from_user.id):
        return
    raw = (message.text or "").strip()
    if raw == "/cancel":
        await state.clear()
        await message.answer("↩️ تم الإلغاء")
        return

    target_uid, _ = await _resolve_user_target(db, raw)

    if target_uid is None:
        await message.answer(
            "╔══════════════════════════╗\n"
            "║  ✗ <b>معرّف غير صحيح</b>       \n"
            "╠══════════════════════════╣\n"
            "  أرسل أحد هذه الأشكال:\n"
            "  ◆ رقم التيليجرام: <code>5219348201</code>\n"
            "  ◆ رقم الحساب:    <code>01001</code>\n"
            "  ◆ البريد:  <code>kira01001@kira-smm.com</code>\n"
            "  ◆ يوزرنيم: <code>@username</code>\n"
            "╚══════════════════════════╝",
            parse_mode="HTML"
        )
        return

    await state.update_data(target_user_id=target_uid)
    await state.set_state(AddBalanceStates.waiting_amount)
    await message.answer(
        f"╔══════════════════════════╗\n"
        f"║  ✓ <b>تم تحديد المستخدم</b>      \n"
        f"╠══════════════════════════╣\n"
        f"  ◆ <b>الآيدي:</b>  <code>{target_uid}</code>\n"
        f"╠══════════════════════════╣\n"
        f"  أرسل <b>المبلغ بالدولار</b>:\n"
        f"  مثال: <code>5</code> أو <code>0.50</code>\n"
        f"  /cancel للإلغاء\n"
        f"╚══════════════════════════╝",
        parse_mode="HTML",
    )


@router.message(AddBalanceStates.waiting_amount)
async def add_balance_to_user(message: Message, state: FSMContext, db):
    if not is_admin(message.from_user.id):
        return
    if message.text and message.text.strip() == "/cancel":
        await state.clear()
        return

    try:
        amount = Decimal((message.text or "").strip())
        if amount <= 0:
            raise ValueError
    except Exception:
        await message.answer("❌ مبلغ غير صحيح")
        return

    data = await state.get_data()
    await state.clear()

    target_id = data["target_user_id"]
    user = await repo_add_balance(db, target_id, amount, "شحن من الإدارة")

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="◀️ لوحة الإدارة", callback_data="adm:panel")]
    ])
    await message.answer(
        f"┌──── ✅ تم الشحن ────\n"
        f"│  👤 <code>{target_id}</code>\n"
        f"│  ➕ المضاف: <b>${float(amount):.2f}</b>\n"
        f"│  💳 الرصيد الجديد: <b>${float(user.balance):.2f}</b>\n"
        "└──────────────────────",
        reply_markup=kb, parse_mode="HTML",
    )
    try:
        await message.bot.send_message(
            target_id,
            f"┌──── ✅ تم شحن رصيدك ────\n"
            f"│  ➕ المبلغ: <b>${float(amount):.2f}</b>\n"
            f"│  💳 رصيدك الجديد: <b>${float(user.balance):.2f}</b>\n"
            "└──────────────────────",
            parse_mode="HTML",
        )
    except Exception:
        pass
    logger.info("Admin added balance: user=%s amount=%s", target_id, amount)


# ════════════════════════════════════════════════════════════════
#  DEDUCT BALANCE
# ════════════════════════════════════════════════════════════════

@router.callback_query(F.data.startswith("adm:deductbal"))
async def start_deduct_balance(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        return

    parts = callback.data.split(":")
    preset_uid = int(parts[2]) if len(parts) > 2 and parts[2].isdigit() else None

    if preset_uid:
        await state.set_state(DeductBalanceStates.waiting_amount)
        await state.update_data(target_user_id=preset_uid)
        await callback.message.edit_text(
            f"┌──── 💸 خصم رصيد ────\n│  المستخدم: <code>{preset_uid}</code>\n│  أرسل المبلغ بالدولار:\n│  /cancel للإلغاء\n└──────────────────────",
            parse_mode="HTML",
        )
    else:
        await state.set_state(DeductBalanceStates.waiting_user_id)
        await callback.message.edit_text(
            "╔══════════════════════════╗\n"
            "║  ◈  <b>خصم رصيد مستخدم</b>  ◈    \n"
            "╠══════════════════════════╣\n"
            "  أرسل <b>أي من التالي:</b>\n"
            "  ◆ رقم التيليجرام: <code>5219348201</code>\n"
            "  ◆ رقم الحساب:    <code>01001</code>\n"
            "  ◆ البريد: <code>kira01001@kira-smm.com</code>\n"
            "  ◆ يوزرنيم: <code>@username</code>\n"
            "╠══════════════════════════╣\n"
            "  /cancel للإلغاء\n"
            "╚══════════════════════════╝",
            parse_mode="HTML",
        )
    await callback.answer()


@router.message(DeductBalanceStates.waiting_user_id)
async def get_user_id_for_deduct(message: Message, state: FSMContext, db):
    if not is_admin(message.from_user.id):
        return
    raw = (message.text or "").strip()
    if raw == "/cancel":
        await state.clear()
        return
    target_uid, _ = await _resolve_user_target(db, raw)
    if target_uid is None:
        await message.answer(
            "❌ لم يُعثر على مستخدم. أرسل:\n"
            "  ◆ رقم التيليجرام\n"
            "  ◆ رقم الحساب: <code>01001</code>\n"
            "  ◆ البريد: <code>kira01001@kira-smm.com</code>\n"
            "  ◆ يوزرنيم: <code>@username</code>",
            parse_mode="HTML"
        )
        return
    await state.update_data(target_user_id=target_uid)
    await state.set_state(DeductBalanceStates.waiting_amount)
    await message.answer(f"┌──── 💸 خصم رصيد ────\n│  المستخدم: <code>{target_uid}</code>\n│  أرسل المبلغ:\n│  /cancel للإلغاء\n└──────────────────────", parse_mode="HTML")


@router.message(DeductBalanceStates.waiting_amount)
async def deduct_balance_from_user(message: Message, state: FSMContext, db):
    if not is_admin(message.from_user.id):
        return
    if message.text and message.text.strip() == "/cancel":
        await state.clear()
        return

    try:
        amount = Decimal((message.text or "").strip())
        if amount <= 0:
            raise ValueError
    except Exception:
        await message.answer("❌ مبلغ غير صحيح")
        return

    data = await state.get_data()
    await state.clear()

    target_id = data["target_user_id"]
    user = await get_user(db, target_id)
    if not user:
        await message.answer("❌ المستخدم غير موجود")
        return

    user.balance = Decimal(str(user.balance)) - amount
    if user.balance < 0:
        user.balance = Decimal("0")
    await db.commit()

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="◀️ لوحة الإدارة", callback_data="adm:panel")]
    ])
    await message.answer(
        f"┌──── ✅ تم الخصم ────\n"
        f"│  👤 <code>{target_id}</code>\n"
        f"│  ➖ المخصوم: <b>${float(amount):.2f}</b>\n"
        f"│  💳 الرصيد الجديد: <b>${float(user.balance):.2f}</b>\n"
        "└──────────────────────",
        reply_markup=kb, parse_mode="HTML",
    )
    logger.info("Admin deducted balance: user=%s amount=%s", target_id, amount)


# ════════════════════════════════════════════════════════════════
#  BROADCAST
# ════════════════════════════════════════════════════════════════

@router.callback_query(F.data == "adm:broadcast")
async def start_broadcast(callback: CallbackQuery, state: FSMContext, db):
    if not is_admin(callback.from_user.id):
        return
    user_count = await count_users(db)
    await state.set_state(BroadcastStates.waiting_message)
    await callback.message.edit_text(
        f"┌──── 📢 إشعار جماعي ────\n"
        f"│  سيُرسل إلى <b>{user_count:,}</b> مستخدم\n"
        "│\n"
        "│  أرسل الرسالة الآن:\n"
        "│  (تدعم HTML مثل <b>بود</b> <i>مائل</i>)\n"
        "│\n"
        "│  /cancel للإلغاء\n"
        "└──────────────────────",
        parse_mode="HTML",
    )
    await callback.answer()


@router.message(BroadcastStates.waiting_message)
async def broadcast_preview(message: Message, state: FSMContext, db):
    if not is_admin(message.from_user.id):
        return
    if message.text and message.text.strip() == "/cancel":
        await state.clear()
        await message.answer("❌ تم الإلغاء")
        return

    text = message.text or message.caption or ""
    await state.update_data(broadcast_text=text)
    await state.set_state(BroadcastStates.waiting_confirm)

    user_count = await count_users(db)
    preview = (
        "┌──── 📢 تأكيد الإرسال ────\n"
        f"│  المستخدمون: <b>{user_count:,}</b>\n"
        "├──────────────────────\n"
        "│  معاينة الرسالة:\n"
        "├──────────────────────\n"
        f"│  {text[:200]}\n"
        "└──────────────────────"
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="✅ إرسال الآن", callback_data="adm:broadcast_confirm"),
            InlineKeyboardButton(text="❌ إلغاء", callback_data="adm:broadcast_cancel"),
        ]
    ])
    await message.answer(preview, reply_markup=kb, parse_mode="HTML")


@router.callback_query(F.data == "adm:broadcast_confirm")
async def send_broadcast_confirmed(callback: CallbackQuery, state: FSMContext, db):
    if not is_admin(callback.from_user.id):
        return
    data = await state.get_data()
    await state.clear()

    text = data.get("broadcast_text", "")
    user_ids = await get_all_user_ids(db)
    wait_msg = await callback.message.answer(f"⏳ جاري الإرسال إلى {len(user_ids):,} مستخدم...")

    success, failed = 0, 0
    for uid in user_ids:
        try:
            await callback.bot.send_message(uid, text, parse_mode="HTML")
            success += 1
        except Exception:
            failed += 1

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="◀️ لوحة الإدارة", callback_data="adm:panel")]
    ])
    await wait_msg.edit_text(
        f"┌──── ✅ تم الإرسال ────\n"
        f"│  ✅ نجح:  <b>{success:,}</b>\n"
        f"│  ❌ فشل:  <b>{failed:,}</b>\n"
        "└──────────────────────",
        reply_markup=kb, parse_mode="HTML",
    )
    await callback.answer()
    logger.info("Broadcast sent: success=%s failed=%s", success, failed)


@router.callback_query(F.data == "adm:broadcast_cancel")
async def broadcast_cancel(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        return
    await state.clear()
    await callback.message.edit_text(
        "❌ تم إلغاء الإشعار الجماعي.",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="◀️ لوحة الإدارة", callback_data="adm:panel")]
        ])
    )
    await callback.answer()
