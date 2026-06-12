"""
Owner-only control panel — master panel with full bot management.
Only accessible by the owner (OWNER_ID from config).
"""
import logging
from decimal import Decimal

from aiogram import Router, F
from aiogram.types import CallbackQuery, Message, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from sqlalchemy import select, func as sa_func

from config import OWNER_IDS, ADMIN_IDS, SUPPORT_USERNAME, BOT_CHANNEL, BOT_NAME
from models.user import User
from models.order import Order
from models.service import Service
from repositories.user_repo import count_users
from repositories.order_repo import count_orders, total_revenue
from ui import card

logger = logging.getLogger(__name__)
router = Router()

# --- PLACEHOLDER: FSM States ---
class OwnerBroadcastStates(StatesGroup):
    waiting_message = State()

class OwnerUserSearchStates(StatesGroup):
    waiting_user_id = State()

class OwnerBalanceStates(StatesGroup):
    waiting_amount = State()

class OwnerMarkupStates(StatesGroup):
    waiting_markup = State()

class OwnerSettingsStates(StatesGroup):
    waiting_value = State()

class OwnerAgentStates(StatesGroup):
    waiting_user_id   = State()
    waiting_discount  = State()
    waiting_remove_id = State()

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

# --- Main Owner Panel ---
@router.callback_query(F.data == "owner:panel")
async def owner_panel(callback: CallbackQuery, db):
    if not _owner_only(callback):
        await callback.answer("⛔ غير مصرح لك", show_alert=True)
        return

    text = card("👑 لوحة المالك", [
        "مرحباً بك في لوحة التحكم الرئيسية",
        "---",
        "🔧 تحكم كامل بجميع إعدادات البوت",
        "👥 إدارة المستخدمين والمشرفين",
        "💰 الإدارة المالية والخدمات",
        "🛒 إدارة الحسابات الجاهزة",
        "🤝 نظام الوكلاء",
        "📊 إحصائيات تفصيلية",
    ])

    kb = InlineKeyboardMarkup(inline_keyboard=[
        # --- الإعدادات ---
        [InlineKeyboardButton(text="⚙️ إعدادات البوت", callback_data="owner:bot_edit")],
        # --- المالية والخدمات ---
        [
            InlineKeyboardButton(text="💰 الإدارة المالية", callback_data="owner:finance"),
            InlineKeyboardButton(text="🛠 إدارة الخدمات", callback_data="owner:services"),
        ],
        [InlineKeyboardButton(text="📋 إدارة الطلبات", callback_data="owner:orders")],
        # --- الحسابات الجاهزة ---
        [InlineKeyboardButton(text="🛒 إدارة الحسابات الجاهزة", callback_data="owner:ready_accounts")],
        # --- المزودون ---
        [
            InlineKeyboardButton(text="🔌 إدارة المزودين", callback_data="owner:providers"),
            InlineKeyboardButton(text="🔄 مزامنة المزودين", callback_data="owner:sync_providers"),
        ],
        # --- المستخدمون والمشرفون ---
        [
            InlineKeyboardButton(text="👥 إدارة المستخدمين", callback_data="owner:users"),
            InlineKeyboardButton(text="👮 إدارة المشرفين", callback_data="owner:moderators"),
        ],
        [
            InlineKeyboardButton(text="➕ إضافة مشرف", callback_data="owner:add_admin"),
            InlineKeyboardButton(text="📢 إرسال جماعي", callback_data="owner:broadcast"),
        ],
        # --- الوكلاء ---
        [InlineKeyboardButton(text="🤝 إدارة الوكلاء", callback_data="owner:agents")],
        # --- أدوات ---
        [
            InlineKeyboardButton(text="💹 نسبة الربح", callback_data="owner:markup"),
            InlineKeyboardButton(text="📊 الإحصائيات", callback_data="owner:stats"),
        ],
        [
            InlineKeyboardButton(text="🔧 وضع الصيانة", callback_data="owner:maintenance"),
            InlineKeyboardButton(text="💾 النسخ الاحتياطي", callback_data="owner:backup"),
        ],
        [InlineKeyboardButton(text="🏠 الرئيسية", callback_data="main_menu")],
    ])

    await _safe_edit(callback, text, kb)
    await callback.answer()

# --- Bot Settings ---
@router.callback_query(F.data == "owner:bot_settings")
async def owner_bot_settings(callback: CallbackQuery, db):
    if not _owner_only(callback):
        await callback.answer("⛔ غير مصرح لك", show_alert=True)
        return

    owner_list = []
    for i, oid in enumerate(OWNER_IDS, 1):
        try:
            chat = await callback.bot.get_chat(oid)
            name = f"@{chat.username}" if chat.username else (chat.first_name or str(oid))
        except Exception:
            name = str(oid)
        owner_list.append(f"  👑 المالك {i}: <b>{name}</b> ({oid})")

    owners_text = "\n".join(owner_list)

    text = card("⚙️ إعدادات البوت", [
        f"📛 اسم البوت: <b>{BOT_NAME}</b>",
        f"👨‍💻 الدعم: <b>{SUPPORT_USERNAME}</b>",
        f"📢 القناة: <b>{BOT_CHANNEL or 'غير محدد'}</b>",
        "---",
        "👑 المالكون:",
        owners_text,
        "---",
        "يمكنك تعديل الإعدادات من ملف .env",
        "وإعادة تشغيل البوت لتفعيل التغييرات",
    ])

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⚙️ تعديل الإعدادات", callback_data="owner:bot_edit")],
        *_back_to_owner(),
    ])
    await _safe_edit(callback, text, kb)
    await callback.answer()

# --- Financial Management ---
@router.callback_query(F.data == "owner:finance")
async def owner_finance(callback: CallbackQuery, db):
    if not _owner_only(callback):
        await callback.answer("⛔ غير مصرح لك", show_alert=True)
        return

    total_balance = await db.scalar(
        select(sa_func.sum(User.balance)).select_from(User)
    ) or 0
    revenue = await total_revenue(db)
    user_count = await count_users(db)
    order_count = await count_orders(db)

    text = card("💰 الإدارة المالية", [
        "📊 ملخص مالي",
        "---",
        f"💵 إجمالي الأرصدة: <b>${float(total_balance):.2f}</b>",
        f"💸 إجمالي الإيرادات: <b>${revenue:.2f}</b>",
        f"👤 عدد المستخدمين: <b>{user_count:,}</b>",
        f"📦 عدد الطلبات: <b>{order_count:,}</b>",
        None,
        f"💰 متوسط رصيد المستخدم: <b>${float(total_balance) / max(user_count, 1):.2f}</b>",
        f"📈 متوسط الإيراد/طلب: <b>${revenue / max(order_count, 1):.2f}</b>",
    ])

    kb = InlineKeyboardMarkup(inline_keyboard=_back_to_owner())
    await _safe_edit(callback, text, kb)
    await callback.answer()

# --- Service Control ---
@router.callback_query(F.data == "owner:services")
async def owner_services(callback: CallbackQuery, db):
    if not _owner_only(callback):
        await callback.answer("⛔ غير مصرح لك", show_alert=True)
        return

    total = await db.scalar(select(sa_func.count()).select_from(Service)) or 0
    active = await db.scalar(
        select(sa_func.count()).select_from(Service).where(Service.is_active == True)
    ) or 0
    inactive = total - active

    text = card("🛠 إدارة الخدمات", [
        "📊 ملخص الخدمات",
        "---",
        f"📦 إجمالي الخدمات: <b>{total}</b>",
        f"✅ نشطة: <b>{active}</b>",
        f"❌ معطلة: <b>{inactive}</b>",
        None,
        "💡 استخدم لوحة الإدارة لتعديل الخدمات",
    ])

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ تفعيل الكل", callback_data="owner:svc_enable_all")],
        [InlineKeyboardButton(text="❌ تعطيل الكل", callback_data="owner:svc_disable_all")],
        *_back_to_owner(),
    ])
    await _safe_edit(callback, text, kb)
    await callback.answer()

@router.callback_query(F.data == "owner:svc_enable_all")
async def owner_enable_all_services(callback: CallbackQuery, db):
    if not _owner_only(callback):
        await callback.answer("⛔", show_alert=True)
        return
    result = await db.execute(select(Service).where(Service.is_active == False))
    services = result.scalars().all()
    for s in services:
        s.is_active = True
    await db.commit()
    await callback.answer(f"✅ تم تفعيل {len(services)} خدمة", show_alert=True)
    await owner_services(callback, db)

@router.callback_query(F.data == "owner:svc_disable_all")
async def owner_disable_all_services(callback: CallbackQuery, db):
    if not _owner_only(callback):
        await callback.answer("⛔", show_alert=True)
        return
    result = await db.execute(select(Service).where(Service.is_active == True))
    services = result.scalars().all()
    for s in services:
        s.is_active = False
    await db.commit()
    await callback.answer(f"❌ تم تعطيل {len(services)} خدمة", show_alert=True)
    await owner_services(callback, db)

# --- Provider Management ---
@router.callback_query(F.data == "owner:providers")
async def owner_providers(callback: CallbackQuery, db):
    if not _owner_only(callback):
        await callback.answer("⛔ غير مصرح لك", show_alert=True)
        return

    from repositories.provider_repo import count_all_provider_services, get_active_providers
    providers = await get_active_providers(db)
    ps_count = await count_all_provider_services(db)

    rows = [
        "📊 ملخص المزودين",
        "---",
        f"🔌 المزودون النشطون: <b>{len(providers)}</b>",
        f"📦 خدمات المزودين: <b>{ps_count:,}</b>",
        None,
    ]
    for p in providers[:10]:
        rows.append(f"  • <b>{p.name}</b> — {p.api_url[:30]}...")

    text = card("🔌 إدارة المزودين", rows)
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔄 مزامنة جميع المزودين", callback_data="owner:sync_providers")],
        *_back_to_owner(),
    ])
    await _safe_edit(callback, text, kb)
    await callback.answer()

@router.callback_query(F.data == "owner:sync_providers")
async def owner_sync_providers(callback: CallbackQuery, db):
    if not _owner_only(callback):
        await callback.answer("⛔", show_alert=True)
        return
    await callback.answer("🔄 جاري المزامنة...", show_alert=False)
    from services.provider_manager import sync_all_providers
    count = await sync_all_providers(db)
    await callback.answer(f"✅ تمت المزامنة — {count or 0} خدمة جديدة", show_alert=True)

# --- User Management ---
@router.callback_query(F.data == "owner:users")
async def owner_users(callback: CallbackQuery, db):
    if not _owner_only(callback):
        await callback.answer("⛔ غير مصرح لك", show_alert=True)
        return

    total = await count_users(db)
    top_result = await db.execute(
        select(User).order_by(User.total_spent.desc()).limit(5)
    )
    top_users = top_result.scalars().all()

    rows = [
        "📊 ملخص المستخدمين",
        "---",
        f"👤 إجمالي المستخدمين: <b>{total:,}</b>",
        None,
        "🏆 أعلى 5 إنفاقاً:",
        "---",
    ]
    for i, u in enumerate(top_users, 1):
        name = u.username or u.first_name or str(u.id)
        rows.append(f"  {i}. @{name} — ${float(u.total_spent or 0):.2f}")

    text = card("👥 إدارة المستخدمين", rows)
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔍 بحث عن مستخدم", callback_data="owner:user_search")],
        *_back_to_owner(),
    ])
    await _safe_edit(callback, text, kb)
    await callback.answer()

@router.callback_query(F.data == "owner:user_search")
async def owner_user_search_prompt(callback: CallbackQuery, db, state: FSMContext):
    if not _owner_only(callback):
        await callback.answer("⛔", show_alert=True)
        return

    text = card("🔍 بحث عن مستخدم", [
        "أرسل أحد المعرفات التالية للبحث:",
        None,
        "🎭 رقم الحساب: <code>01001</code>",
        "📿 معرف تليجرام: <code>123456789</code>",
        "👤 يوزرنيم: <code>@username</code>",
        None,
        "💡 يمكنك البحث بأي منها",
    ])
    kb = InlineKeyboardMarkup(inline_keyboard=_back_to_owner())
    await _safe_edit(callback, text, kb)
    await state.set_state(OwnerUserSearchStates.waiting_user_id)
    await callback.answer()

@router.message(OwnerUserSearchStates.waiting_user_id)
async def owner_user_search_handler(message: Message, db, state: FSMContext):
    if not _is_owner(message.from_user.id):
        return
    await state.clear()

    from repositories.user_repo import get_user_by_account_number, get_user_by_username
    raw = (message.text or "").strip()
    user = None
    search_method = ""

    # ── username search ──────────────────────────────────────────────────
    if raw.startswith("@") or (not raw.lstrip("-").isdigit()):
        user = await get_user_by_username(db, raw)
        search_method = "يوزرنيم"
    else:
        search_id = int(raw)
        # account numbers are ≤ 6 digits, Telegram IDs are much larger
        if search_id < 1_000_000:
            user = await get_user_by_account_number(db, search_id)
            search_method = "رقم الحساب"
        if not user:
            user = await db.get(User, search_id)
            if user:
                search_method = "معرف تليجرام"

    if not user:
        await message.answer(f"❌ لم يتم العثور على مستخدم بـ «{raw}».")
        return

    acct_num = user.account_number or "—"
    text = card("👤 ملف المستخدم", [
        f"🔍 طريقة البحث: <b>{search_method}</b>",
        "---",
        f"🎭 رقم الحساب: <b>#{acct_num}</b>",
        f"🆔 معرف تليجرام: <b>{user.id}</b>",
        f"👤 الاسم: <b>{user.username or user.first_name or '-'}</b>",
        "---",
        f"💰 الرصيد: <b>${float(user.balance):.4f}</b>",
        f"💸 المصروف: <b>${float(user.total_spent or 0):.2f}</b>",
        f"👑 VIP: <b>{user.vip_level}</b>",
        f"🌐 اللغة: <b>{user.language}</b>",
        f"💵 العملة: <b>{user.currency}</b>",
        f"📅 التسجيل: <b>{user.created_at.strftime('%Y-%m-%d') if user.created_at else '-'}</b>",
    ])

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="➕ إضافة رصيد", callback_data=f"owner:add_bal:{user.id}"),
            InlineKeyboardButton(text="➖ خصم رصيد", callback_data=f"owner:sub_bal:{user.id}"),
        ],
        [InlineKeyboardButton(text="🔍 بحث آخر", callback_data="owner:user_search")],
        *_back_to_owner(),
    ])
    await message.answer(text, reply_markup=kb, parse_mode="HTML")

@router.callback_query(F.data.startswith("owner:add_bal:"))
async def owner_add_balance_prompt(callback: CallbackQuery, db, state: FSMContext):
    if not _owner_only(callback):
        await callback.answer("⛔", show_alert=True)
        return

    target_id = int(callback.data.split(":")[2])
    await state.update_data(target_id=target_id, action="add")
    await state.set_state(OwnerBalanceStates.waiting_amount)

    text = card("➕ إضافة رصيد", [
        f"🆔 المستخدم: <b>{target_id}</b>",
        None,
        "أرسل المبلغ بالدولار:",
        "مثال: <code>10.50</code>",
    ])
    kb = InlineKeyboardMarkup(inline_keyboard=_back_to_owner())
    await _safe_edit(callback, text, kb)
    await callback.answer()

@router.callback_query(F.data.startswith("owner:sub_bal:"))
async def owner_sub_balance_prompt(callback: CallbackQuery, db, state: FSMContext):
    if not _owner_only(callback):
        await callback.answer("⛔", show_alert=True)
        return

    target_id = int(callback.data.split(":")[2])
    await state.update_data(target_id=target_id, action="sub")
    await state.set_state(OwnerBalanceStates.waiting_amount)

    text = card("➖ خصم رصيد", [
        f"🆔 المستخدم: <b>{target_id}</b>",
        None,
        "أرسل المبلغ بالدولار:",
        "مثال: <code>5.00</code>",
    ])
    kb = InlineKeyboardMarkup(inline_keyboard=_back_to_owner())
    await _safe_edit(callback, text, kb)
    await callback.answer()

@router.message(OwnerBalanceStates.waiting_amount)
async def owner_balance_handler(message: Message, db, state: FSMContext):
    if not _is_owner(message.from_user.id):
        return

    data = await state.get_data()
    await state.clear()
    target_id = data.get("target_id")
    action = data.get("action", "add")

    try:
        amount = Decimal(message.text.strip())
        if amount <= 0:
            raise ValueError
    except (ValueError, Exception):
        await message.answer("❌ مبلغ غير صالح.")
        return

    user = await db.get(User, target_id)
    if not user:
        await message.answer(f"❌ المستخدم {target_id} غير موجود.")
        return

    from repositories.user_repo import add_balance as _repo_add_bal, invalidate_user_cache as _inv_cache
    from sqlalchemy import select as _owner_sel
    if action == "add":
        # add_balance now uses FOR UPDATE (fresh session object) — safe to call
        user = await _repo_add_bal(db, target_id, amount, "شحن من المالك")
        emoji = "➕"
    else:
        from decimal import Decimal as _D
        # Deduct: fresh SELECT to avoid detached-object bug
        _res = await db.execute(_owner_sel(User).where(User.id == target_id).with_for_update())
        user = _res.scalar_one_or_none()
        if not user:
            await message.answer(f"❌ المستخدم {target_id} غير موجود.")
            return
        user.balance = max((_D(str(user.balance or 0)) - amount), _D("0"))
        # Create debit transaction record
        from models.transaction import Transaction as _Tx
        db.add(_Tx(user_id=target_id, amount=-amount, description="خصم من المالك"))
        await db.commit()
        await db.refresh(user)
        _inv_cache(target_id)
        emoji = "➖"

    text = card(f"{emoji} تم تعديل الرصيد", [
        f"🆔 المستخدم: <b>{target_id}</b>",
        f"💵 المبلغ: <b>${float(amount):.4f}</b>",
        f"💰 الرصيد الجديد: <b>${float(user.balance):.4f}</b>",
    ])
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔍 بحث آخر", callback_data="owner:user_search")],
        *_back_to_owner(),
    ])
    await message.answer(text, reply_markup=kb, parse_mode="HTML")

# --- Moderator Management ---
@router.callback_query(F.data == "owner:moderators")
async def owner_moderators(callback: CallbackQuery, db):
    if not _owner_only(callback):
        await callback.answer("⛔ غير مصرح لك", show_alert=True)
        return

    text = card("👮 إدارة المشرفين", [
        "يمكنك إدارة المشرفين من لوحة الإدارة",
        "---",
        "💡 المشرفون يحصلون على صلاحيات الإدارة",
        "   بدون صلاحية إضافة/حذف مشرفين آخرين",
    ])

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="👮 إدارة المشرفين", callback_data="adm:moderators")],
        *_back_to_owner(),
    ])
    await _safe_edit(callback, text, kb)
    await callback.answer()

# --- Broadcast ---
@router.callback_query(F.data == "owner:broadcast")
async def owner_broadcast_prompt(callback: CallbackQuery, db, state: FSMContext):
    if not _owner_only(callback):
        await callback.answer("⛔ غير مصرح لك", show_alert=True)
        return

    total = await count_users(db)
    text = card("📢 إرسال جماعي", [
        f"👤 عدد المستخدمين: <b>{total:,}</b>",
        "---",
        "أرسل الرسالة التي تريد إرسالها لجميع المستخدمين:",
        None,
        "⚠️ سيتم إرسالها لجميع المستخدمين",
        "💡 يدعم HTML للتنسيق",
    ])

    kb = InlineKeyboardMarkup(inline_keyboard=_back_to_owner())
    await _safe_edit(callback, text, kb)
    await state.set_state(OwnerBroadcastStates.waiting_message)
    await callback.answer()

@router.message(OwnerBroadcastStates.waiting_message)
async def owner_broadcast_handler(message: Message, db, state: FSMContext):
    if not _is_owner(message.from_user.id):
        return
    await state.clear()

    broadcast_text = message.text or message.caption or ""
    if not broadcast_text.strip():
        await message.answer("❌ الرسالة فارغة.")
        return

    result = await db.execute(select(User.id))
    user_ids = [row[0] for row in result.all()]

    sent = 0
    failed = 0
    status_msg = await message.answer(f"📢 جاري الإرسال لـ {len(user_ids)} مستخدم...")

    import asyncio as _asyncio
    for uid in user_ids:
        try:
            await message.bot.send_message(uid, broadcast_text, parse_mode="HTML")
            sent += 1
        except Exception:
            failed += 1
        await _asyncio.sleep(0.05)  # Stay under Telegram's 30 msg/sec limit

    text = card("📢 نتائج الإرسال الجماعي", [
        f"✅ تم الإرسال: <b>{sent}</b>",
        f"❌ فشل: <b>{failed}</b>",
        f"📊 الإجمالي: <b>{len(user_ids)}</b>",
    ])
    kb = InlineKeyboardMarkup(inline_keyboard=_back_to_owner())
    await status_msg.edit_text(text, reply_markup=kb, parse_mode="HTML")

# --- Markup Control ---
@router.callback_query(F.data == "owner:markup")
async def owner_markup(callback: CallbackQuery, db, state: FSMContext):
    if not _owner_only(callback):
        await callback.answer("⛔ غير مصرح لك", show_alert=True)
        return

    from services import settings_manager
    current = settings_manager.get_markup_pct()

    text = card("💹 نسبة الربح (Markup)", [
        f"📊 النسبة الحالية: <b>{current}%</b>",
        "---",
        "أرسل النسبة الجديدة (رقم فقط):",
        "مثال: <code>25</code> لتعيين 25%",
    ])

    kb = InlineKeyboardMarkup(inline_keyboard=_back_to_owner())
    await _safe_edit(callback, text, kb)
    await state.set_state(OwnerMarkupStates.waiting_markup)
    await callback.answer()

@router.message(OwnerMarkupStates.waiting_markup)
async def owner_markup_handler(message: Message, db, state: FSMContext):
    if not _is_owner(message.from_user.id):
        return
    await state.clear()

    try:
        pct = float(message.text.strip())
        if pct < 0 or pct > 500:
            raise ValueError
    except (ValueError, Exception):
        await message.answer("❌ نسبة غير صالحة. أدخل رقماً بين 0 و 500.")
        return

    from services import settings_manager
    settings_manager.set_setting("markup_pct", pct)

    text = card("✅ تم تحديث نسبة الربح", [
        f"📊 النسبة الجديدة: <b>{pct}%</b>",
    ])
    kb = InlineKeyboardMarkup(inline_keyboard=_back_to_owner())
    await message.answer(text, reply_markup=kb, parse_mode="HTML")

# --- Statistics ---
@router.callback_query(F.data == "owner:stats")
async def owner_stats(callback: CallbackQuery, db):
    if not _owner_only(callback):
        await callback.answer("⛔ غير مصرح لك", show_alert=True)
        return

    total_users = await count_users(db)
    total_orders_count = await count_orders(db)
    revenue = await total_revenue(db)
    total_balance = await db.scalar(
        select(sa_func.sum(User.balance)).select_from(User)
    ) or 0
    total_services = await db.scalar(select(sa_func.count()).select_from(Service)) or 0

    text = card("📊 إحصائيات تفصيلية", [
        "👥 المستخدمون",
        "---",
        f"  👤 إجمالي: <b>{total_users:,}</b>",
        None,
        "💰 المالية",
        "---",
        f"  💵 إجمالي الأرصدة: <b>${float(total_balance):.2f}</b>",
        f"  💸 إجمالي الإيرادات: <b>${revenue:.2f}</b>",
        f"  📈 متوسط/مستخدم: <b>${revenue / max(total_users, 1):.2f}</b>",
        None,
        "📦 الطلبات والخدمات",
        "---",
        f"  🛍 الطلبات: <b>{total_orders_count:,}</b>",
        f"  📋 الخدمات: <b>{total_services}</b>",
    ])

    kb = InlineKeyboardMarkup(inline_keyboard=_back_to_owner())
    await _safe_edit(callback, text, kb)
    await callback.answer()

# --- Maintenance Mode ---
@router.callback_query(F.data == "owner:maintenance")
async def owner_maintenance(callback: CallbackQuery, db):
    if not _owner_only(callback):
        await callback.answer("⛔ غير مصرح لك", show_alert=True)
        return

    from services import settings_manager
    is_maint = settings_manager.get("maintenance_mode", False)

    status = "🟢 البوت يعمل" if not is_maint else "🔴 وضع الصيانة مفعّل"
    text = card("🔧 وضع الصيانة", [
        f"الحالة: <b>{status}</b>",
        "---",
        "عند تفعيل وضع الصيانة:",
        "• لن يتمكن المستخدمون من تقديم طلبات جديدة",
        "• سيظهر لهم رسالة صيانة",
        "• المالك والمشرفون يبقون متصلين",
    ])

    toggle_text = "🔴 تفعيل الصيانة" if not is_maint else "🟢 إلغاء الصيانة"
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=toggle_text, callback_data="owner:toggle_maintenance")],
        *_back_to_owner(),
    ])
    await _safe_edit(callback, text, kb)
    await callback.answer()

@router.callback_query(F.data == "owner:toggle_maintenance")
async def owner_toggle_maintenance(callback: CallbackQuery, db):
    if not _owner_only(callback):
        await callback.answer("⛔", show_alert=True)
        return

    from services import settings_manager
    current = settings_manager.get("maintenance_mode", False)
    settings_manager.set_setting("maintenance_mode", not current)

    new_status = "مفعّل 🔴" if not current else "معطّل 🟢"
    await callback.answer(f"وضع الصيانة: {new_status}", show_alert=True)
    await owner_maintenance(callback, db)

# --- Backup ---
@router.callback_query(F.data == "owner:backup")
async def owner_backup(callback: CallbackQuery, db):
    if not _owner_only(callback):
        await callback.answer("⛔ غير مصرح لك", show_alert=True)
        return

    import os
    db_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "smm_bot.db")
    db_exists = os.path.exists(db_path)
    db_size = os.path.getsize(db_path) / 1024 if db_exists else 0

    text = card("💾 النسخ الاحتياطي", [
        "📂 معلومات قاعدة البيانات",
        "---",
        f"💾 الحجم: <b>{db_size:.1f} KB</b>",
        f"📍 الموقع: <code>{db_path}</code>",
        None,
        "💡 اضغط الزر لإرسال نسخة احتياطية",
    ])

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📤 إرسال نسخة احتياطية", callback_data="owner:send_backup")],
        *_back_to_owner(),
    ])
    await _safe_edit(callback, text, kb)
    await callback.answer()

@router.callback_query(F.data == "owner:orders")
async def owner_orders(callback: CallbackQuery, db):
    if not _owner_only(callback):
        await callback.answer("⛔ غير مصرح لك", show_alert=True)
        return

    total = await db.scalar(select(sa_func.count()).select_from(Order)) or 0

    # Get recent 10 orders
    result = await db.execute(
        select(Order).order_by(Order.created_at.desc()).limit(10)
    )
    recent = result.scalars().all()

    rows = [
        "📊 ملخص الطلبات",
        "---",
        f"📦 إجمالي الطلبات: <b>{total:,}</b>",
        None,
        "📋 آخر 10 طلبات:",
        "---",
    ]
    for o in recent:
        status_ico = {"pending": "⏳", "processing": "🔄", "completed": "✅", "partial": "⚠️", "canceled": "❌"}.get(o.status or "", "❓")
        charge = float(o.charge) if o.charge else 0
        rows.append(f"  #{o.id} {status_ico} | 👤 {o.user_id} | 💰 ${charge:.2f}")

    text = card("📋 إدارة الطلبات", rows)
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔄 تحديث", callback_data="owner:orders")],
        *_back_to_owner(),
    ])
    await _safe_edit(callback, text, kb)
    await callback.answer()


@router.callback_query(F.data == "owner:bot_edit")
async def owner_bot_edit(callback: CallbackQuery, db):
    if not _owner_only(callback):
        await callback.answer("⛔ غير مصرح لك", show_alert=True)
        return

    from services import settings_manager
    markup = settings_manager.get("markup_pct", 30)
    min_order = settings_manager.get("min_order", 0)
    ref_reward = settings_manager.get("referral_reward", 0.1)
    stars_rate = settings_manager.get("stars_rate", 100)
    maint = settings_manager.get("maintenance_mode", False)

    text = card("⚙️ إعدادات البوت المباشرة", [
        f"💹 نسبة الربح: <b>{markup}%</b>",
        f"📉 حد أدنى للطلب: <b>${min_order}</b>",
        f"🎁 مكافأة الإحالة: <b>${ref_reward}</b>",
        f"⭐ سعر النجوم: <b>{stars_rate} = $1</b>",
        f"🔧 وضع الصيانة: <b>{'مفعّل 🔴' if maint else 'معطّل 🟢'}</b>",
    ])

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💹 تعديل نسبة الربح", callback_data="owner:markup")],
        [InlineKeyboardButton(text="🔧 وضع الصيانة", callback_data="owner:toggle_maintenance")],
        *_back_to_owner(),
    ])
    await _safe_edit(callback, text, kb)
    await callback.answer()


@router.callback_query(F.data == "owner:send_backup")
async def owner_send_backup(callback: CallbackQuery, db):
    if not _owner_only(callback):
        await callback.answer("⛔", show_alert=True)
        return

    import os
    from aiogram.types import FSInputFile

    db_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "smm_bot.db")
    if not os.path.exists(db_path):
        await callback.answer("❌ ملف قاعدة البيانات غير موجود", show_alert=True)
        return

    try:
        doc = FSInputFile(db_path, filename="smm_bot_backup.db")
        await callback.message.answer_document(doc, caption="💾 نسخة احتياطية لقاعدة البيانات")
        await callback.answer("✅ تم إرسال النسخة الاحتياطية", show_alert=True)
    except Exception as exc:
        logger.error("Backup send failed: %s", exc)
        await callback.answer(f"❌ فشل: {exc}", show_alert=True)


# --- Add Admin ---
@router.callback_query(F.data == "owner:add_admin")
async def owner_add_admin(callback: CallbackQuery, db):
    if not _owner_only(callback):
        await callback.answer("⛔ غير مصرح لك", show_alert=True)
        return

    admin_ids_str = ", ".join(str(a) for a in ADMIN_IDS) if ADMIN_IDS else "لا يوجد"

    text = card("➕ إضافة مشرف", [
        "👮 المشرفون الحاليون:",
        f"  <code>{admin_ids_str}</code>",
        "---",
        "لإضافة مشرف جديد:",
        "  1. افتح ملف <code>.env</code> على السيرفر",
        "  2. أضف معرف المستخدم إلى <code>ADMIN_IDS</code>",
        "  3. أعد تشغيل البوت",
        None,
        "💡 يمكنك أيضاً إدارة المشرفين من لوحة الإدارة:",
    ])

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="👮 لوحة المشرفين", callback_data="adm:moderators")],
        *_back_to_owner(),
    ])
    await _safe_edit(callback, text, kb)
    await callback.answer()


# ═══════════════════════════════════════════════════════════════
#  AGENTS (RESELLERS) SYSTEM
# ═══════════════════════════════════════════════════════════════

def _agents_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ إضافة وكيل",   callback_data="owner:agents:add")],
        [InlineKeyboardButton(text="🗑 حذف وكيل",     callback_data="owner:agents:remove")],
        [InlineKeyboardButton(text="✏️ تعديل خصم",    callback_data="owner:agents:edit")],
        [InlineKeyboardButton(text="📋 قائمة الوكلاء", callback_data="owner:agents:list")],
        *_back_to_owner(),
    ])


def _agents_panel_text() -> str:
    from services import settings_manager as sm
    agents = sm.get_agents()
    count  = len(agents)
    lines  = [f"🤝 <b>نظام الوكلاء</b>  —  إجمالي: <b>{count}</b>", "---"]
    if agents:
        for uid, disc in list(agents.items())[:10]:
            lines.append(f"👤 <code>{uid}</code>  —  خصم: <b>{disc:.1f}%</b>")
        if count > 10:
            lines.append(f"  … و {count - 10} آخرين")
    else:
        lines.append("لا يوجد وكلاء حالياً.")
    return card("🤝 إدارة الوكلاء", lines)


@router.callback_query(F.data == "owner:agents")
async def owner_agents(callback: CallbackQuery, state: FSMContext):
    if not _owner_only(callback):
        await callback.answer("⛔ غير مصرح لك", show_alert=True)
        return
    await state.clear()
    await _safe_edit(callback, _agents_panel_text(), _agents_kb())
    await callback.answer()


# ── قائمة تفصيلية ────────────────────────────────────────────────────────────
@router.callback_query(F.data == "owner:agents:list")
async def owner_agents_list(callback: CallbackQuery, db):
    if not _owner_only(callback):
        await callback.answer("⛔ غير مصرح لك", show_alert=True)
        return
    from services import settings_manager as sm
    agents = sm.get_agents()
    if not agents:
        await callback.answer("لا يوجد وكلاء مسجلون.", show_alert=True)
        return

    lines = ["📋 <b>قائمة الوكلاء:</b>", "---"]
    for uid, disc in agents.items():
        user = None
        try:
            from repositories.user_repo import get_user
            user = await get_user(db, int(uid))
        except Exception:
            pass
        name = (user.first_name or user.username or f"#{uid}") if user else f"#{uid}"
        lines.append(f"👤 {name}  —  ID: <code>{uid}</code>  —  خصم: <b>{disc:.1f}%</b>")

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔙 رجوع", callback_data="owner:agents")],
    ])
    await _safe_edit(callback, card("📋 الوكلاء", lines), kb)
    await callback.answer()


# ── إضافة وكيل — الخطوة 1: أدخل معرف المستخدم ────────────────────────────────
@router.callback_query(F.data.in_({"owner:agents:add", "owner:agents:edit"}))
async def owner_agents_add_start(callback: CallbackQuery, state: FSMContext):
    if not _owner_only(callback):
        await callback.answer("⛔ غير مصرح لك", show_alert=True)
        return
    is_edit = callback.data == "owner:agents:edit"
    await state.update_data(agent_edit_mode=is_edit)
    await state.set_state(OwnerAgentStates.waiting_user_id)
    verb = "تعديل خصم" if is_edit else "إضافة"
    text = card(f"{'✏️' if is_edit else '➕'} {verb} وكيل", [
        "أرسل <b>معرف المستخدم (User ID)</b> للوكيل:",
        "مثال: <code>123456789</code>",
        None,
        "يمكنك الحصول على المعرف من لوحة إدارة المستخدمين.",
    ])
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="❌ إلغاء", callback_data="owner:agents")],
    ])
    await _safe_edit(callback, text, kb)
    await callback.answer()


@router.message(OwnerAgentStates.waiting_user_id)
async def owner_agents_add_uid(message: Message, state: FSMContext):
    if not _is_owner(message.from_user.id):
        return
    raw = message.text.strip() if message.text else ""
    if not raw.lstrip("-").isdigit():
        await message.answer("❌ معرف غير صالح، أرسل رقماً فقط.")
        return
    uid = int(raw)
    await state.update_data(agent_target_uid=uid)
    await state.set_state(OwnerAgentStates.waiting_discount)

    data = await state.get_data()
    is_edit = data.get("agent_edit_mode", False)
    from services import settings_manager as sm
    current = sm.get_agent_discount(uid)
    hint    = f" (الحالي: {current:.1f}%)" if is_edit and sm.is_agent(uid) else ""

    text = card("💸 نسبة الخصم", [
        f"الوكيل: <code>{uid}</code>",
        f"أرسل نسبة الخصم{hint} (0 - 100):",
        "مثال: <code>15</code>  →  خصم 15%",
    ])
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="❌ إلغاء", callback_data="owner:agents")],
    ])
    await message.answer(text, reply_markup=kb, parse_mode="HTML")


@router.message(OwnerAgentStates.waiting_discount)
async def owner_agents_add_discount(message: Message, state: FSMContext):
    if not _is_owner(message.from_user.id):
        return
    raw = message.text.strip().replace("%", "") if message.text else ""
    try:
        pct = float(raw)
        if not (0 <= pct <= 100):
            raise ValueError
    except ValueError:
        await message.answer("❌ نسبة غير صالحة، أدخل رقماً بين 0 و 100.")
        return

    data = await state.get_data()
    uid  = data.get("agent_target_uid")
    await state.clear()

    from services import settings_manager as sm
    sm.set_agent(uid, pct)

    is_new = not sm.is_agent(uid)  # actually we just set it, check count
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🤝 لوحة الوكلاء", callback_data="owner:agents")],
        [InlineKeyboardButton(text="🏠 الرئيسية",       callback_data="main_menu")],
    ])
    await message.answer(
        card("✅ تم الحفظ", [
            f"👤 الوكيل: <code>{uid}</code>",
            f"💸 نسبة الخصم: <b>{pct:.1f}%</b>",
            "---",
            "✅ تم تسجيل الوكيل بنجاح.",
        ]),
        reply_markup=kb,
        parse_mode="HTML",
    )


# ── حذف وكيل ─────────────────────────────────────────────────────────────────
@router.callback_query(F.data == "owner:agents:remove")
async def owner_agents_remove_start(callback: CallbackQuery, state: FSMContext):
    if not _owner_only(callback):
        await callback.answer("⛔ غير مصرح لك", show_alert=True)
        return
    from services import settings_manager as sm
    agents = sm.get_agents()
    if not agents:
        await callback.answer("لا يوجد وكلاء لحذفهم.", show_alert=True)
        return

    rows: list[list[InlineKeyboardButton]] = []
    for uid, disc in agents.items():
        rows.append([
            InlineKeyboardButton(
                text=f"🗑 ID {uid}  —  {disc:.1f}%",
                callback_data=f"owner:agents:del:{uid}",
            )
        ])
    rows.extend([
        [InlineKeyboardButton(text="❌ إلغاء", callback_data="owner:agents")],
    ])

    await _safe_edit(
        callback,
        card("🗑 حذف وكيل", ["اختر الوكيل الذي تريد حذفه:"]),
        InlineKeyboardMarkup(inline_keyboard=rows),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("owner:agents:del:"))
async def owner_agents_delete(callback: CallbackQuery, state: FSMContext):
    if not _owner_only(callback):
        await callback.answer("⛔ غير مصرح لك", show_alert=True)
        return
    uid_str = callback.data.split(":")[-1]
    try:
        uid = int(uid_str)
    except ValueError:
        await callback.answer("معرف غير صالح.", show_alert=True)
        return

    from services import settings_manager as sm
    removed = sm.remove_agent(uid)
    if removed:
        await callback.answer(f"✅ تم حذف الوكيل {uid} بنجاح.", show_alert=True)
    else:
        await callback.answer("⚠️ الوكيل غير موجود.", show_alert=True)

    await _safe_edit(callback, _agents_panel_text(), _agents_kb())
