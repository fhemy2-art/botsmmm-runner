"""
Admin: Full-featured service management + admin dashboard.
Features:
- Dashboard with real-time stats
- Markup/profit system (global %)
- Service management with bulk actions
- Provider management (inline)
- Bot settings panel
"""
import logging

from aiogram import Router, F
from aiogram.types import CallbackQuery, Message, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from sqlalchemy import select, func as sa_func

from models.service import Service
from models.provider_service import ProviderService
from repositories.service_repo import (
    get_admin_services_page,
    get_platform_service_counts,
    get_service,
    count_services,
)
from repositories.provider_repo import count_all_provider_services
from repositories.order_repo import count_orders, total_revenue
from repositories.user_repo import count_users
from services.service_manager import auto_add_services, PLATFORM_MAP
from services.provider_manager import sync_all_providers
from services import settings_manager
from config import ADMIN_IDS, ADMIN_PER_PAGE

logger = logging.getLogger(__name__)
router = Router()

# ── Category callback mapping (to avoid 64-byte callback_data limit) ──────
# Telegram limits callback_data to 64 bytes. Arabic category names with emojis
# can exceed this. We map long categories to short hashed keys.
_ADM_CAT_MAP: dict[str, str] = {}  # short_key → full category name


def _acat_key(category: str) -> str:
    """Return a short key for admin callback_data. If short enough, use as-is."""
    if len(category.encode('utf-8')) <= 20:
        return category
    import hashlib
    h = hashlib.md5(category.encode()).hexdigest()[:8]
    key = f"ac{h}"
    _ADM_CAT_MAP[key] = category
    return key


def _acat_resolve(key: str) -> str:
    """Resolve a short key back to full category name."""
    return _ADM_CAT_MAP.get(key, key)


class EditServiceStates(StatesGroup):
    waiting_new_price = State()
    waiting_new_name = State()


class MarkupStates(StatesGroup):
    waiting_markup_pct = State()


class BulkPriceStates(StatesGroup):
    waiting_bulk_pct = State()
    waiting_platform = State()


class AddServiceStates(StatesGroup):
    waiting_name = State()
    waiting_platform = State()
    waiting_category = State()
    waiting_price = State()
    waiting_description = State()


class EditCategoryStates(StatesGroup):
    waiting_new_category = State()


class EditDescStates(StatesGroup):
    waiting_new_desc = State()


class EditPlatformStates(StatesGroup):
    waiting_new_platform = State()


def is_admin(uid: int) -> bool:
    return uid in ADMIN_IDS


_moderator_ids_cache: list[int] = []


def set_moderator_ids(ids: list[int]) -> None:
    global _moderator_ids_cache
    _moderator_ids_cache = ids


def is_admin_or_mod(uid: int) -> bool:
    return uid in ADMIN_IDS or uid in _moderator_ids_cache


def _admin_only(callback: CallbackQuery) -> bool:
    return is_admin_or_mod(callback.from_user.id)


def _kb(*rows, back: str = "adm:back") -> InlineKeyboardMarkup:
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
#  ADMIN PANEL — MAIN DASHBOARD
# ════════════════════════════════════════════════════════════════

@router.callback_query(F.data == "adm:panel")
async def admin_panel(callback: CallbackQuery, db):
    if not _admin_only(callback):
        return

    user_count = await count_users(db)
    order_count = await count_orders(db)
    revenue = await total_revenue(db)
    svc_count = await count_services(db)
    markup = settings_manager.get_markup_pct()

    text = (
        "┌──── 🛡️ لوحة تحكم الإدارة ────\n"
        "│\n"
        f"│  👥 المستخدمون:  <b>{user_count:,}</b>\n"
        f"│  📦 الطلبات:    <b>{order_count:,}</b>\n"
        f"│  💵 الإيرادات:  <b>${revenue:.2f}</b>\n"
        f"│  🗂 الخدمات:    <b>{svc_count:,}</b>\n"
        f"│  📈 هامش الربح: <b>{markup:.0f}%</b>\n"
        "│\n"
        "└──────────────────────"
    )

    kb = InlineKeyboardMarkup(inline_keyboard=[
        # ── الإحصائيات والإعدادات ──
        [
            InlineKeyboardButton(text="📊 الإحصائيات", callback_data="adm:stats"),
            InlineKeyboardButton(text="⚙️ إعدادات البوت", callback_data="adm:settings"),
        ],
        # ── الأقسام الرئيسية ──
        [InlineKeyboardButton(text="──── 📋 الأقسام الرئيسية ────", callback_data="noop")],
        [
            InlineKeyboardButton(text="🚀 قسم الرشق (SMM)", callback_data="adm:smm"),
            InlineKeyboardButton(text="🎮 قسم الألعاب", callback_data="adm:games"),
        ],
        # ── إدارة المستخدمين ──
        [InlineKeyboardButton(text="──── 👥 المستخدمون ────", callback_data="noop")],
        [
            InlineKeyboardButton(text="👥 المستخدمون", callback_data="adm:users"),
            InlineKeyboardButton(text="💳 شحن رصيد", callback_data="adm:addbal"),
        ],
        [
            InlineKeyboardButton(text="💸 خصم رصيد", callback_data="adm:deductbal"),
            InlineKeyboardButton(text="📢 إشعار جماعي", callback_data="adm:broadcast"),
        ],
        # ── أدوات عامة ──
        [InlineKeyboardButton(text="──── 🛠 أدوات عامة ────", callback_data="noop")],
        [
            InlineKeyboardButton(text="🏪 إدارة المتجر", callback_data="adm:store"),
            InlineKeyboardButton(text="👮 إدارة المشرفين", callback_data="adm:moderators"),
        ],
        [InlineKeyboardButton(text="🏠 القائمة الرئيسية", callback_data="main_menu")],
    ])
    await _safe_edit(callback, text, kb)
    await callback.answer()




# ════════════════════════════════════════════════════════════════
#  SMM SECTION — قسم الرشق
# ════════════════════════════════════════════════════════════════

@router.callback_query(F.data == "adm:smm")
async def smm_section_panel(callback: CallbackQuery, db):
    if not _admin_only(callback):
        return

    text = (
        "┌──── 🚀 قسم الرشق (SMM) ────\n"
        "│\n"
        "│  إدارة خدمات الرشق والمزودين\n"
        "│\n"
        "└──────────────────────"
    )

    kb = InlineKeyboardMarkup(inline_keyboard=[
        # ── المزودين ──
        [InlineKeyboardButton(text="──── 🔌 المزودين ────", callback_data="noop")],
        [
            InlineKeyboardButton(text="🔌 قائمة المزودين", callback_data="adm:providers_list"),
            InlineKeyboardButton(text="➕ إضافة مزود", callback_data="adm:add_provider"),
        ],
        [
            InlineKeyboardButton(text="🔄 مزامنة جميع المزودين", callback_data="adm:sync"),
        ],
        # ── الخدمات ──
        [InlineKeyboardButton(text="──── 📦 الخدمات ────", callback_data="noop")],
        [
            InlineKeyboardButton(text="📦 خدماتي", callback_data="adm:my_services"),
            InlineKeyboardButton(text="📂 إدارة الأقسام", callback_data="adm:categories"),
        ],
        [
            InlineKeyboardButton(text="🤖 إضافة تلقائية", callback_data="adm:auto_add"),
            InlineKeyboardButton(text="➕ من مزود", callback_data="adm:add_from_provider"),
        ],
        [
            InlineKeyboardButton(text="➕ إضافة خدمة يدوية", callback_data="adm:add_service"),
        ],
        # ── التسعير ──
        [InlineKeyboardButton(text="──── 💰 التسعير ────", callback_data="noop")],
        [
            InlineKeyboardButton(text="📈 هامش الربح", callback_data="adm:markup"),
            InlineKeyboardButton(text="💰 تسعير جماعي", callback_data="adm:bulk_price"),
        ],
        # ── الطلبات والحذف ──
        [InlineKeyboardButton(text="──── 📋 الطلبات ────", callback_data="noop")],
        [
            InlineKeyboardButton(text="📋 إدارة الطلبات", callback_data="adm:orders_mgmt"),
        ],
        [
            InlineKeyboardButton(text="🗑 حذف جميع الخدمات", callback_data="adm:wipe_all"),
        ],
        [
            InlineKeyboardButton(text="◀️ رجوع", callback_data="adm:panel"),
            InlineKeyboardButton(text="🏠 الرئيسية", callback_data="main_menu"),
        ],
    ])
    await _safe_edit(callback, text, kb)
    await callback.answer()



@router.callback_query(F.data == "noop")
async def noop_handler_main(callback: CallbackQuery):
    await callback.answer()

@router.callback_query(F.data == "adm:back")
async def back_to_admin(callback: CallbackQuery, db):
    if not _admin_only(callback):
        return
    await admin_panel(callback, db)


# ════════════════════════════════════════════════════════════════
#  WIPE ALL SERVICES
# ════════════════════════════════════════════════════════════════

@router.callback_query(F.data == "adm:wipe_all")
async def wipe_all_confirm(callback: CallbackQuery, db):
    """Show confirmation before deleting all services."""
    if not _admin_only(callback):
        return

    svc_count = await count_services(db)
    ps_count = await db.scalar(
        select(sa_func.count()).select_from(ProviderService)
    ) or 0

    text = (
        "┌──── 🗑 حذف جميع الخدمات ────\n"
        "│\n"
        f"│  📦 خدمات المتجر: <b>{svc_count:,}</b>\n"
        f"│  🔌 خدمات المزودين: <b>{ps_count:,}</b>\n"
        "│\n"
        "│  ⚠️ <b>تحذير:</b> سيتم حذف جميع الخدمات\n"
        "│  وخدمات المزودين نهائياً!\n"
        "│  الطلبات السابقة لن تتأثر.\n"
        "│\n"
        "└──────────────────────"
    )

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text="✅ نعم، احذف الكل",
            callback_data="adm:wipe_all_yes",
        )],
        [InlineKeyboardButton(
            text="🗑 حذف خدمات المتجر فقط",
            callback_data="adm:wipe_svc_only",
        )],
        [InlineKeyboardButton(
            text="🗑 حذف خدمات المزودين فقط",
            callback_data="adm:wipe_ps_only",
        )],
        [
            InlineKeyboardButton(text="◀️ رجوع", callback_data="adm:panel"),
        ],
    ])
    await _safe_edit(callback, text, kb)
    await callback.answer()


@router.callback_query(F.data == "adm:wipe_all_yes")
async def wipe_all_execute(callback: CallbackQuery, db):
    """Delete ALL services and provider_services."""
    if not _admin_only(callback):
        return
    from sqlalchemy import delete as sa_delete

    del_svc = await db.execute(sa_delete(Service))
    del_ps = await db.execute(sa_delete(ProviderService))
    await db.commit()

    text = (
        "┌──── ✅ تم الحذف ────\n"
        f"│  🗑 خدمات المتجر: <b>{del_svc.rowcount:,}</b> محذوفة\n"
        f"│  🗑 خدمات المزودين: <b>{del_ps.rowcount:,}</b> محذوفة\n"
        "│\n"
        "│  💡 أضف مزود جديد ثم استخدم الإضافة التلقائية\n"
        "└──────────────────────"
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="◀️ لوحة الإدارة", callback_data="adm:panel")],
    ])
    await _safe_edit(callback, text, kb)
    await callback.answer("✅ تم حذف جميع الخدمات", show_alert=True)


@router.callback_query(F.data == "adm:wipe_svc_only")
async def wipe_services_only(callback: CallbackQuery, db):
    """Delete services (store) only, keep provider_services."""
    if not _admin_only(callback):
        return
    from sqlalchemy import delete as sa_delete

    del_svc = await db.execute(sa_delete(Service))
    await db.commit()

    text = (
        "┌──── ✅ تم الحذف ────\n"
        f"│  🗑 خدمات المتجر: <b>{del_svc.rowcount:,}</b> محذوفة\n"
        "│  🔌 خدمات المزودين: لم تُحذف\n"
        "│\n"
        "│  💡 استخدم الإضافة التلقائية لإعادة الإضافة\n"
        "└──────────────────────"
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="◀️ لوحة الإدارة", callback_data="adm:panel")],
    ])
    await _safe_edit(callback, text, kb)
    await callback.answer("✅ تم حذف خدمات المتجر", show_alert=True)


@router.callback_query(F.data == "adm:wipe_ps_only")
async def wipe_provider_services_only(callback: CallbackQuery, db):
    """Delete provider_services only, keep store services."""
    if not _admin_only(callback):
        return
    from sqlalchemy import delete as sa_delete

    del_ps = await db.execute(sa_delete(ProviderService))
    await db.commit()

    text = (
        "┌──── ✅ تم الحذف ────\n"
        "│  📦 خدمات المتجر: لم تُحذف\n"
        f"│  🗑 خدمات المزودين: <b>{del_ps.rowcount:,}</b> محذوفة\n"
        "│\n"
        "│  💡 استخدم المزامنة لإعادة جلب خدمات المزودين\n"
        "└──────────────────────"
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="◀️ لوحة الإدارة", callback_data="adm:panel")],
    ])
    await _safe_edit(callback, text, kb)
    await callback.answer("✅ تم حذف خدمات المزودين", show_alert=True)


# ════════════════════════════════════════════════════════════════
#  STATS
# ════════════════════════════════════════════════════════════════

@router.callback_query(F.data == "adm:stats")
async def admin_stats(callback: CallbackQuery, db):
    if not _admin_only(callback):
        return
    from sqlalchemy import select as sql_select
    from models.user import User
    from models.order import Order

    user_count = await count_users(db)
    order_count = await count_orders(db)
    revenue = await total_revenue(db)
    svc_count = await count_services(db)
    prov_svc_count = await count_all_provider_services(db)

    total_bal = await db.scalar(sql_select(sa_func.sum(User.balance)).select_from(User)) or 0
    completed = await db.scalar(
        sql_select(sa_func.count()).select_from(Order).where(Order.status == "completed")
    ) or 0
    pending = await db.scalar(
        sql_select(sa_func.count()).select_from(Order).where(Order.status.in_(["pending", "processing"]))
    ) or 0

    markup = settings_manager.get_markup_pct()

    text = (
        "┌──── 📊 إحصائيات البوت ────\n"
        "│\n"
        "│  👤 المستخدمون\n"
        f"│  ┗━ إجمالي: <b>{user_count:,}</b>\n"
        f"│  ┗━ أرصدتهم: <b>${float(total_bal):.2f}</b>\n"
        "│\n"
        "│  📦 الطلبات\n"
        f"│  ┗━ إجمالي: <b>{order_count:,}</b>\n"
        f"│  ┗━ مكتملة: <b>{completed:,}</b>\n"
        f"│  ┗━ نشطة:   <b>{pending:,}</b>\n"
        "│\n"
        "│  💵 الإيرادات\n"
        f"│  ┗━ إجمالي: <b>${revenue:.2f}</b>\n"
        f"│  ┗━ هامش:   <b>{markup:.0f}%</b>\n"
        "│\n"
        "│  🗂 الخدمات\n"
        f"│  ┗━ المضافة:   <b>{svc_count:,}</b>\n"
        f"│  ┗━ من مزودين: <b>{prov_svc_count:,}</b>\n"
        "│\n"
        "└──────────────────────"
    )
    await _safe_edit(callback, text, _kb())
    await callback.answer()


# ════════════════════════════════════════════════════════════════
#  BOT SETTINGS
# ════════════════════════════════════════════════════════════════

@router.callback_query(F.data == "adm:settings")
async def bot_settings(callback: CallbackQuery):
    if not _admin_only(callback):
        return
    s = settings_manager.get_all()
    maintenance_icon = "🔴" if s.get("maintenance") else "🟢"
    maintenance_text = "تشغيل" if s.get("maintenance") else "إيقاف"

    text = (
        "┌──── ⚙️ إعدادات البوت ────\n"
        "│\n"
        f"│  📈 هامش الربح:  <b>{s.get('markup_pct', 30):.0f}%</b>\n"
        f"│  💵 حد الطلب:    <b>${s.get('min_order_usd', 0.01):.4f}</b>\n"
        f"│  🎁 مكافأة الإحالة: <b>${s.get('referral_reward', 0.1):.2f}</b>\n"
        f"│  ⭐ نجوم/$1:     <b>{s.get('stars_per_usd', 100)}</b>\n"
        f"│  {maintenance_icon} الصيانة:   <b>{maintenance_text}</b>\n"
        "│\n"
        "└──────────────────────"
    )
    maint_toggle = "adm:maint:on" if not s.get("maintenance") else "adm:maint:off"
    maint_btn_text = "🔴 تفعيل الصيانة" if not s.get("maintenance") else "🟢 إيقاف الصيانة"

    kb = _kb(
        [InlineKeyboardButton(text="📈 تغيير هامش الربح", callback_data="adm:markup")],
        [InlineKeyboardButton(text=maint_btn_text, callback_data=maint_toggle)],
    )
    await _safe_edit(callback, text, kb)
    await callback.answer()


@router.callback_query(F.data.startswith("adm:maint:"))
async def toggle_maintenance(callback: CallbackQuery):
    if not _admin_only(callback):
        return
    state_val = callback.data.split(":")[2]
    settings_manager.set_setting("maintenance", state_val == "on")
    status = "🔴 الصيانة مفعّلة" if state_val == "on" else "🟢 الصيانة معطّلة"
    await callback.answer(status, show_alert=True)
    await bot_settings(callback)


# ════════════════════════════════════════════════════════════════
#  MARKUP / PROFIT SYSTEM
# ════════════════════════════════════════════════════════════════

@router.callback_query(F.data == "adm:markup")
async def show_markup(callback: CallbackQuery, state: FSMContext):
    if not _admin_only(callback):
        return
    current = settings_manager.get_markup_pct()
    text = (
        "┌──── 📈 هامش الربح ────\n"
        "│\n"
        f"│  الحالي: <b>{current:.0f}%</b>\n"
        "│\n"
        "│  هذه النسبة تُضاف على سعر المزود\n"
        "│  تلقائياً عند إضافة الخدمات.\n"
        "│\n"
        "│  مثال: المزود بـ $1 → أنت تبيع بـ\n"
        f"│  <b>${1 * (1 + current/100):.4f}</b> (ربح {current:.0f}%)\n"
        "│\n"
        "│  أرسل النسبة الجديدة (مثال: <code>25</code>)\n"
        "│  للإلغاء أرسل /cancel\n"
        "│\n"
        "└──────────────────────"
    )
    await state.set_state(MarkupStates.waiting_markup_pct)
    await _safe_edit(callback, text, InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="◀️ رجوع", callback_data="adm:panel")]
    ]))
    await callback.answer()


@router.message(MarkupStates.waiting_markup_pct)
async def set_markup_pct(message: Message, state: FSMContext):
    if not is_admin_or_mod(message.from_user.id):
        return
    if message.text and message.text.strip() == "/cancel":
        await state.clear()
        return

    try:
        pct = float((message.text or "").strip())
        if pct < 0 or pct > 10000:
            raise ValueError
    except ValueError:
        await message.answer("❌ رقم غير صحيح. أرسل نسبة مثل <code>25</code>", parse_mode="HTML")
        return

    await state.clear()
    settings_manager.set_setting("markup_pct", pct)
    text = (
        "┌──── ✅ تم التحديث ────\n"
        f"│  هامش الربح الجديد: <b>{pct:.0f}%</b>\n"
        "│\n"
        "│  ⚠️ ملاحظة: يؤثر على الخدمات الجديدة\n"
        "│  فقط. لتحديث الأسعار القديمة استخدم\n"
        "│  'تسعير جماعي'.\n"
        "└──────────────────────"
    )
    await message.answer(text, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💰 تسعير جماعي", callback_data="adm:bulk_price")],
        [InlineKeyboardButton(text="◀️ لوحة الإدارة", callback_data="adm:panel")],
    ]))


# ════════════════════════════════════════════════════════════════
#  BULK PRICE UPDATE
# ════════════════════════════════════════════════════════════════

@router.callback_query(F.data == "adm:bulk_price")
async def bulk_price_menu(callback: CallbackQuery, db):
    if not _admin_only(callback):
        return
    rows = await get_platform_service_counts(db)
    markup = settings_manager.get_markup_pct()

    text = (
        "┌──── 💰 تسعير جماعي ────\n"
        "│\n"
        "│  تحديث أسعار خدمات بناءً على\n"
        f"│  سعر المزود + هامش الربح (<b>{markup:.0f}%</b>)\n"
        "│\n"
        "│  اختر المنصة أو حدّث الكل:\n"
        "│\n"
        "└──────────────────────"
    )

    buttons = []
    for plat, cnt in rows:
        info = PLATFORM_MAP.get(plat, {"ar": plat, "emoji": "📱"})
        buttons.append([InlineKeyboardButton(
            text=f"{info['emoji']} {info['ar']} ({cnt})",
            callback_data=f"adm:bulkupd:{plat}",
        )])
    buttons.append([InlineKeyboardButton(text="🔄 تحديث الكل", callback_data="adm:bulkupd:ALL")])
    buttons.append([
        InlineKeyboardButton(text="◀️ رجوع", callback_data="adm:back"),
        InlineKeyboardButton(text="🏠 الرئيسية", callback_data="adm:panel"),
    ])
    await _safe_edit(callback, text, InlineKeyboardMarkup(inline_keyboard=buttons))
    await callback.answer()


@router.callback_query(F.data.startswith("adm:bulkupd:"))
async def bulk_update_prices(callback: CallbackQuery, db):
    if not _admin_only(callback):
        return
    from models.provider_service import ProviderService

    platform = callback.data.split(":")[2]
    markup = settings_manager.get_markup_multiplier()

    await _safe_edit(callback, f"⏳ جاري تحديث الأسعار ({platform})...", InlineKeyboardMarkup(inline_keyboard=[]))
    await callback.answer()

    query = select(Service).where(Service.provider_service_id.isnot(None))
    if platform != "ALL":
        query = query.where(Service.platform == platform)

    result = await db.execute(query)
    services = result.scalars().all()

    updated = 0
    for svc in services:
        ps_result = await db.execute(
            select(ProviderService).where(ProviderService.id == svc.provider_service_id)
        )
        ps = ps_result.scalar_one_or_none()
        if ps and ps.rate and float(ps.rate) > 0:
            svc.price_per_1000 = round(float(ps.rate) * markup, 6)
            updated += 1

    await db.commit()

    plat_label = "جميع المنصات" if platform == "ALL" else PLATFORM_MAP.get(platform, {}).get("ar", platform)
    text = (
        "┌──── ✅ تم التحديث ────\n"
        f"│  المنصة:    <b>{plat_label}</b>\n"
        f"│  محدّث:     <b>{updated:,}</b> خدمة\n"
        f"│  الهامش:    <b>{settings_manager.get_markup_pct():.0f}%</b>\n"
        "└──────────────────────"
    )
    kb = _kb(
        [InlineKeyboardButton(text="📦 عرض الخدمات", callback_data="adm:my_services")],
    )
    await _safe_edit(callback, text, kb)


# ════════════════════════════════════════════════════════════════
#  MY SERVICES — PLATFORM LIST
# ════════════════════════════════════════════════════════════════

@router.callback_query(F.data == "adm:my_services")
async def my_services(callback: CallbackQuery, db):
    if not _admin_only(callback):
        return
    rows = await get_platform_service_counts(db)

    if not rows:
        text = (
            "┌──── 📦 الخدمات ────\n"
            "│  لا توجد خدمات مضافة بعد.\n"
            "│  استخدم 🤖 الإضافة التلقائية.\n"
            "└──────────────────────"
        )
        await _safe_edit(callback, text, _kb())
        await callback.answer()
        return

    total = sum(r[1] for r in rows)
    text = (
        "┌──── 📦 الخدمات المضافة ────\n"
        f"│  إجمالي: <b>{total:,} خدمة</b>\n"
        "│  اختر منصة لإدارة خدماتها:\n"
        "└──────────────────────"
    )
    buttons = []
    for plat, cnt in rows:
        info = PLATFORM_MAP.get(plat, {"ar": plat, "emoji": "📱"})
        active_icon = "🟢" if cnt > 0 else "🔴"
        buttons.append([InlineKeyboardButton(
            text=f"{info['emoji']} {info['ar']}  {active_icon} {cnt}",
            callback_data=f"adm:myplt:{plat}:0",
        )])
    buttons.append([
        InlineKeyboardButton(text="◀️ رجوع", callback_data="adm:back"),
        InlineKeyboardButton(text="🏠 الرئيسية", callback_data="adm:panel"),
    ])
    await _safe_edit(callback, text, InlineKeyboardMarkup(inline_keyboard=buttons))
    await callback.answer()


@router.callback_query(F.data.startswith("adm:myplt:"))
async def my_services_by_platform(callback: CallbackQuery, db):
    if not _admin_only(callback):
        return
    parts = callback.data.split(":")
    platform = parts[2]
    page = int(parts[3]) if len(parts) > 3 else 0

    services, total = await get_admin_services_page(db, platform, page, ADMIN_PER_PAGE)
    total_pages = max(1, (total + ADMIN_PER_PAGE - 1) // ADMIN_PER_PAGE)
    info = PLATFORM_MAP.get(platform, {"ar": platform, "emoji": "📱"})

    text = (
        f"┌──── {info['emoji']} {info['ar']} ────\n"
        f"│  الخدمات: <b>{total:,}</b>  |  صفحة {page + 1}/{total_pages}\n"
        "│  اضغط خدمة للتعديل:\n"
        "└──────────────────────"
    )
    buttons = []
    for s in services:
        status_icon = "🟢" if s.is_active else "🔴"
        price_str = f"${float(s.price_per_1000):.4f}"
        name_short = s.name[:32]
        buttons.append([InlineKeyboardButton(
            text=f"{status_icon} {name_short}",
            callback_data=f"adm:editsvc:{s.id}",
        )])
        buttons.append([InlineKeyboardButton(
            text=f"     💰 {price_str}/1K  |  📂 {(s.category or '')[:18]}",
            callback_data=f"adm:editsvc:{s.id}",
        )])

    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton(text="◀️", callback_data=f"adm:myplt:{platform}:{page-1}"))
    nav.append(InlineKeyboardButton(text=f"{page+1}/{total_pages}", callback_data="noop"))
    if page < total_pages - 1:
        nav.append(InlineKeyboardButton(text="▶️", callback_data=f"adm:myplt:{platform}:{page+1}"))
    if nav:
        buttons.append(nav)

    buttons.append([
        InlineKeyboardButton(text="🔴 تعطيل الكل", callback_data=f"adm:toggleall:{platform}:0"),
        InlineKeyboardButton(text="🟢 تفعيل الكل", callback_data=f"adm:toggleall:{platform}:1"),
    ])
    buttons.append([InlineKeyboardButton(text="◀️ رجوع", callback_data="adm:my_services")])

    await _safe_edit(callback, text, InlineKeyboardMarkup(inline_keyboard=buttons))
    await callback.answer()


@router.callback_query(F.data.startswith("adm:toggleall:"))
async def toggle_all_platform(callback: CallbackQuery, db):
    if not _admin_only(callback):
        return
    parts = callback.data.split(":")
    platform, activate = parts[2], int(parts[3]) == 1

    result = await db.execute(select(Service).where(Service.platform == platform))
    services = result.scalars().all()
    for s in services:
        s.is_active = activate
    await db.commit()

    count = len(services)
    status_text = "تفعيل" if activate else "تعطيل"
    await callback.answer(f"✅ تم {status_text} {count} خدمة", show_alert=True)
    await my_services_by_platform(callback, db)


async def _show_edit_service(callback: CallbackQuery, db, sid: int) -> None:
    s = await get_service(db, sid)
    if not s:
        await callback.answer("الخدمة غير موجودة")
        return

    status_icon = "🟢 مفعّلة" if s.is_active else "🔴 معطّلة"
    toggle_text = "🔴 تعطيل" if s.is_active else "🟢 تفعيل"
    plat_info = PLATFORM_MAP.get(s.platform, {"ar": s.platform, "emoji": "📱"})

    from models.provider_service import ProviderService
    ps_result = await db.execute(
        select(ProviderService).where(ProviderService.id == s.provider_service_id)
    ) if s.provider_service_id else None
    ps = ps_result.scalar_one_or_none() if ps_result else None
    provider_price = f"${float(ps.rate):.6f}" if ps and ps.rate else "غير متاح"
    markup_pct = ""
    if ps and ps.rate and float(ps.rate) > 0:
        m = (float(s.price_per_1000) / float(ps.rate) - 1) * 100
        markup_pct = f"  (ربح {m:.0f}%)"

    text = (
        f"┌──── 📦 خدمة #{s.id} ────\n"
        f"│  📛 {s.name[:50]}\n"
        "├──────────────────────\n"
        f"│  📱 {plat_info['emoji']} {plat_info['ar']}\n"
        f"│  📂 {s.category}\n"
        f"│  💰 سعرنا:  <b>${float(s.price_per_1000):.6f}/1K</b>{markup_pct}\n"
        f"│  🏭 المزود: <b>{provider_price}/1K</b>\n"
        f"│  ⚡ السرعة: {s.speed or 'سريع'}\n"
        f"│  🏆 الجودة: {s.quality or 'عالية'}\n"
        f"│  ♻️ الضمان: {s.guarantee_days or 0} يوم\n"
        f"│  📝 الوصف: {(s.description or 'بدون وصف')[:40]}\n"
        f"│  📊 الحالة: {status_icon}\n"
        "└──────────────────────"
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="💰 تغيير السعر", callback_data=f"adm:chprice:{sid}"),
            InlineKeyboardButton(text="📛 تغيير الاسم", callback_data=f"adm:chname:{sid}"),
        ],
        [
            InlineKeyboardButton(text="✏️ تعديل القسم", callback_data=f"adm:editcat:{sid}"),
            InlineKeyboardButton(text="✏️ تعديل الوصف", callback_data=f"adm:editdesc:{sid}"),
        ],
        [
            InlineKeyboardButton(text="✏️ تعديل المنصة", callback_data=f"adm:editplat:{sid}"),
        ],
        [
            InlineKeyboardButton(text=toggle_text, callback_data=f"adm:toggle:{sid}"),
            InlineKeyboardButton(text="🗑 حذف", callback_data=f"adm:delsvc:{sid}:confirm"),
        ],
        [InlineKeyboardButton(text="◀️ رجوع", callback_data=f"adm:myplt:{s.platform}:0")],
    ])
    await callback.message.edit_text(text, reply_markup=kb, parse_mode="HTML")


@router.callback_query(F.data.startswith("adm:editsvc:"))
async def edit_service(callback: CallbackQuery, db):
    if not _admin_only(callback):
        return
    sid = int(callback.data.split(":")[2])
    await _show_edit_service(callback, db, sid)
    await callback.answer()


@router.callback_query(F.data.startswith("adm:toggle:"))
async def toggle_service(callback: CallbackQuery, db):
    if not _admin_only(callback):
        return
    sid = int(callback.data.split(":")[2])
    s = await get_service(db, sid)
    if s:
        s.is_active = not s.is_active
        await db.commit()
        await callback.answer("✅ تم التفعيل" if s.is_active else "🔴 تم التعطيل")
        await _show_edit_service(callback, db, sid)


@router.callback_query(F.data.startswith("adm:delsvc:"))
async def delete_service_confirm(callback: CallbackQuery, db):
    if not _admin_only(callback):
        return
    parts = callback.data.split(":")
    sid = int(parts[2])
    action = parts[3] if len(parts) > 3 else ""

    if action != "confirm":
        await callback.answer()
        return

    s = await get_service(db, sid)
    platform = s.platform if s else "other"
    if s:
        await db.delete(s)
        await db.commit()
        await callback.answer("🗑 تم الحذف", show_alert=True)

    text = "┌──── 🗑 تم الحذف ────\n│  تم حذف الخدمة بنجاح.\n└──────────────────────"
    await _safe_edit(callback, text, _kb(back=f"adm:myplt:{platform}:0"))


@router.callback_query(F.data.startswith("adm:chprice:"))
async def change_price(callback: CallbackQuery, state: FSMContext):
    if not _admin_only(callback):
        return
    sid = int(callback.data.split(":")[2])
    await state.set_state(EditServiceStates.waiting_new_price)
    await state.update_data(edit_service_id=sid)
    await callback.message.edit_text(
        "┌──── 💰 تغيير السعر ────\n"
        "│  أرسل السعر الجديد لكل 1000:\n"
        "│  مثال: <code>0.5</code>\n"
        "│\n"
        "│  /cancel للإلغاء\n"
        "└──────────────────────",
        parse_mode="HTML",
    )
    await callback.answer()


@router.message(EditServiceStates.waiting_new_price)
async def set_new_price(message: Message, state: FSMContext, db):
    if not is_admin_or_mod(message.from_user.id):
        return
    if message.text and message.text.strip() == "/cancel":
        await state.clear()
        await message.answer("❌ تم الإلغاء", reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="◀️ لوحة الإدارة", callback_data="adm:panel")]
        ]))
        return
    try:
        price = float((message.text or "").strip())
        if price <= 0:
            raise ValueError
    except ValueError:
        await message.answer("❌ رقم غير صحيح. مثال: <code>0.5</code>", parse_mode="HTML")
        return

    data = await state.get_data()
    await state.clear()
    s = await get_service(db, data["edit_service_id"])
    if s:
        s.price_per_1000 = price
        await db.commit()
    text = f"┌──── ✅ تم التحديث ────\n│  السعر الجديد: <b>${price:.6f}/1K</b>\n└──────────────────────"
    await message.answer(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="◀️ لوحة الإدارة", callback_data="adm:panel")]
    ]), parse_mode="HTML")


@router.callback_query(F.data.startswith("adm:chname:"))
async def change_name(callback: CallbackQuery, state: FSMContext):
    if not _admin_only(callback):
        return
    sid = int(callback.data.split(":")[2])
    await state.set_state(EditServiceStates.waiting_new_name)
    await state.update_data(edit_service_id=sid)
    await callback.message.edit_text(
        "┌──── 📛 تغيير الاسم ────\n│  أرسل الاسم الجديد:\n│  /cancel للإلغاء\n└──────────────────────"
    )
    await callback.answer()


@router.message(EditServiceStates.waiting_new_name)
async def set_new_name(message: Message, state: FSMContext, db):
    if not is_admin_or_mod(message.from_user.id):
        return
    if message.text and message.text.strip() == "/cancel":
        await state.clear()
        await message.answer("❌ تم الإلغاء", reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="◀️ لوحة الإدارة", callback_data="adm:panel")]
        ]))
        return
    data = await state.get_data()
    await state.clear()
    s = await get_service(db, data["edit_service_id"])
    new_name = (message.text or "").strip()[:100]
    if s:
        s.name = new_name
        await db.commit()
    text = f"┌──── ✅ تم التحديث ────\n│  الاسم الجديد: {new_name}\n└──────────────────────"
    await message.answer(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="◀️ لوحة الإدارة", callback_data="adm:panel")]
    ]), parse_mode="HTML")


# ════════════════════════════════════════════════════════════════
#  AUTO ADD
# ════════════════════════════════════════════════════════════════

@router.callback_query(F.data == "adm:auto_add")
async def auto_add(callback: CallbackQuery, db):
    if not _admin_only(callback):
        return
    await _safe_edit(callback, "⏳ جاري الإضافة التلقائية...", InlineKeyboardMarkup(inline_keyboard=[]))
    await callback.answer()

    added, skipped, summary = await auto_add_services(db)

    summary_lines = [f"│  {k}: {v} خدمة" for k, v in sorted(summary.items())] or ["│  لا شيء جديد"]
    text = (
        "┌──── 🤖 الإضافة التلقائية ────\n"
        f"│  ➕ خدمات جديدة: <b>{added}</b>\n"
        f"│  ⏭️ مضافة مسبقاً: <b>{skipped}</b>\n"
        "├──────────────────────\n"
        "│  📊 حسب المنصة:\n" +
        "\n".join(summary_lines) + "\n"
        "└──────────────────────"
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📦 عرض الخدمات", callback_data="adm:my_services")],
        [InlineKeyboardButton(text="◀️ لوحة الإدارة", callback_data="adm:back")],
    ])
    await _safe_edit(callback, text, kb)


# ════════════════════════════════════════════════════════════════
#  ADD FROM PROVIDER
# ════════════════════════════════════════════════════════════════

@router.callback_query(F.data == "adm:add_from_provider")
async def add_from_provider_select(callback: CallbackQuery, db):
    """Step 1: Choose provider."""
    if not _admin_only(callback):
        return
    from repositories.provider_repo import get_active_providers, count_provider_services

    providers = await get_active_providers(db)
    if not providers:
        text = "┌──── ❌ لا يوجد مزودين ────\n│  استخدم 'إضافة مزود' أولاً.\n└──────────────────────"
        await _safe_edit(callback, text, _kb())
        await callback.answer()
        return

    buttons = []
    for p in providers:
        svc_count = await count_provider_services(db, p.id)
        status_icon = "🟢" if p.status else "🔴"
        buttons.append([InlineKeyboardButton(
            text=f"{status_icon} {p.name}  ({svc_count:,} خدمة)",
            callback_data=f"adm:pfp:{p.id}",
        )])
    buttons.append([
        InlineKeyboardButton(text="◀️ رجوع", callback_data="adm:back"),
        InlineKeyboardButton(text="🏠 الرئيسية", callback_data="adm:panel"),
    ])

    text = (
        "┌──── ➕ إضافة من مزود ────\n"
        f"│  المزودون: <b>{len(providers)}</b>\n"
        "│  اختر مزوداً لتصفح خدماته:\n"
        "└──────────────────────"
    )
    await _safe_edit(callback, text, InlineKeyboardMarkup(inline_keyboard=buttons))
    await callback.answer()


# ── Provider category hash for callback_data ──────────────────────────────
_PROV_CAT_MAP: dict[str, str] = {}


def _pcat_key(category: str) -> str:
    if len(category.encode('utf-8')) <= 20:
        return category
    import hashlib
    h = hashlib.md5(category.encode()).hexdigest()[:8]
    key = f"pc{h}"
    _PROV_CAT_MAP[key] = category
    return key


def _pcat_resolve(key: str) -> str:
    return _PROV_CAT_MAP.get(key, key)


@router.callback_query(F.data.startswith("adm:pfp:"))
async def provider_platforms(callback: CallbackQuery, db):
    """Step 2: Show detected platforms from provider's services."""
    if not _admin_only(callback):
        return
    from models.provider_service import ProviderService
    from repositories.provider_repo import get_provider
    from services.service_manager import detect_platform

    provider_id = int(callback.data.split(":")[2])
    provider = await get_provider(db, provider_id)
    if not provider:
        await callback.answer("المزود غير موجود")
        return

    # Get all unique categories from provider, then group by detected platform
    result = await db.execute(
        select(
            ProviderService.category,
            sa_func.count().label("cnt"),
        )
        .where(ProviderService.provider_id == provider_id)
        .group_by(ProviderService.category)
    )
    cat_rows = result.all()

    # Group by detected platform
    platform_counts: dict[str, int] = {}
    for cat, cnt in cat_rows:
        plat = detect_platform(cat or "")
        platform_counts[plat] = platform_counts.get(plat, 0) + cnt

    # Sort: known platforms first, then "other"
    plat_order = list(PLATFORM_MAP.keys()) + ["other"]
    sorted_plats = sorted(
        platform_counts.items(),
        key=lambda x: plat_order.index(x[0]) if x[0] in plat_order else 999,
    )

    text = (
        f"┌──── 📦 {provider.name} ────\n"
        f"│  إجمالي الخدمات: <b>{sum(c for _, c in sorted_plats):,}</b>\n"
        "│  اختر منصة لتصفح فئاتها:\n"
        "└──────────────────────"
    )

    buttons = []
    for plat, cnt in sorted_plats:
        info = PLATFORM_MAP.get(plat, {"ar": plat.capitalize(), "emoji": "📱"})
        cb_data = f"adm:pfc:{provider_id}:{plat}"
        buttons.append([InlineKeyboardButton(
            text=f"{info['emoji']} {info['ar']}  ({cnt:,})",
            callback_data=cb_data,
        )])

    buttons.append([InlineKeyboardButton(
        text="🤖 إضافة جميع خدمات المزود",
        callback_data=f"adm:addall:{provider_id}",
    )])
    buttons.append([
        InlineKeyboardButton(text="◀️ رجوع", callback_data="adm:add_from_provider"),
        InlineKeyboardButton(text="🏠 الرئيسية", callback_data="adm:panel"),
    ])
    await _safe_edit(callback, text, InlineKeyboardMarkup(inline_keyboard=buttons))
    await callback.answer()


@router.callback_query(F.data.startswith("adm:pfc:"))
async def provider_categories(callback: CallbackQuery, db):
    """Step 3: Show categories for a platform from this provider (paginated)."""
    if not _admin_only(callback):
        return
    try:
        from models.provider_service import ProviderService
        from repositories.provider_repo import get_provider
        from services.service_manager import detect_platform

        parts = callback.data.split(":")
        provider_id = int(parts[2])
        target_plat = parts[3]
        page = int(parts[4]) if len(parts) > 4 else 0
        per_page = 30  # Max categories per page to stay under Telegram button limit

        provider = await get_provider(db, provider_id)
        if not provider:
            await callback.answer("المزود غير موجود")
            return

        info = PLATFORM_MAP.get(target_plat, {"ar": target_plat.capitalize(), "emoji": "📱"})

        # Get all categories, filter by matching platform
        result = await db.execute(
            select(
                ProviderService.category,
                sa_func.count().label("cnt"),
            )
            .where(ProviderService.provider_id == provider_id)
            .group_by(ProviderService.category)
            .order_by(sa_func.count().desc())
        )
        all_cats = result.all()

        # Filter categories whose detected platform matches
        matching_cats = []
        for cat, cnt in all_cats:
            plat = detect_platform(cat or "")
            if plat == target_plat:
                matching_cats.append((cat or "(بدون)", cnt))

        logger.info("provider_categories: plat=%s cats=%d", target_plat, len(matching_cats))

        if not matching_cats:
            await callback.answer("لا توجد فئات لهذه المنصة")
            return

        total_cats = len(matching_cats)
        total_pages = max(1, (total_cats + per_page - 1) // per_page)
        page = min(page, total_pages - 1)
        page_cats = matching_cats[page * per_page : (page + 1) * per_page]

        text = (
            f"┌──── {info['emoji']} {info['ar']} — {provider.name} ────\n"
            f"│  الفئات: <b>{total_cats}</b>  |  صفحة {page + 1}/{total_pages}\n"
            "│  اختر فئة لتصفح خدماتها:\n"
            "└──────────────────────"
        )

        buttons = []
        for cat, cnt in page_cats:
            safe_cat = _pcat_key(cat)
            # Check how many are already added
            already = await db.scalar(
                select(sa_func.count()).select_from(Service)
                .where(Service.provider_service_id.in_(
                    select(ProviderService.id)
                    .where(
                        ProviderService.provider_id == provider_id,
                        ProviderService.category == cat,
                    )
                ))
            ) or 0
            added_tag = f" ✅{already}" if already > 0 else ""
            buttons.append([InlineKeyboardButton(
                text=f"📂 {cat[:35]} ({cnt}){added_tag}",
                callback_data=f"adm:pfs:{provider_id}:{target_plat}:{safe_cat}:0",
            )])

        # Pagination nav
        if total_pages > 1:
            nav = []
            if page > 0:
                nav.append(InlineKeyboardButton(text="◀️ السابق", callback_data=f"adm:pfc:{provider_id}:{target_plat}:{page-1}"))
            nav.append(InlineKeyboardButton(text=f"{page+1}/{total_pages}", callback_data="noop"))
            if page + 1 < total_pages:
                nav.append(InlineKeyboardButton(text="التالي ▶️", callback_data=f"adm:pfc:{provider_id}:{target_plat}:{page+1}"))
            buttons.append(nav)

        # Add all for this platform
        buttons.append([InlineKeyboardButton(
            text=f"🤖 إضافة كل خدمات {info['ar']}",
            callback_data=f"adm:addplat:{provider_id}:{target_plat}",
        )])
        buttons.append([
            InlineKeyboardButton(text="◀️ رجوع", callback_data=f"adm:pfp:{provider_id}"),
            InlineKeyboardButton(text="🏠 الرئيسية", callback_data="adm:panel"),
        ])
        await _safe_edit(callback, text, InlineKeyboardMarkup(inline_keyboard=buttons))
        await callback.answer()
    except Exception as exc:
        logger.error("provider_categories FAILED: %s", exc, exc_info=True)
        await callback.answer(f"خطأ: {exc}"[:200], show_alert=True)


@router.callback_query(F.data.startswith("adm:pfs:"))
async def provider_services_list(callback: CallbackQuery, db):
    """Step 4: Show services in a specific provider category (paginated)."""
    if not _admin_only(callback):
        return
    from models.provider_service import ProviderService
    from repositories.provider_repo import get_provider

    parts = callback.data.split(":")
    provider_id = int(parts[2])
    target_plat = parts[3]
    cat_key = parts[4]
    cat = _pcat_resolve(cat_key)
    page = int(parts[5]) if len(parts) > 5 else 0
    per_page = 8

    provider = await get_provider(db, provider_id)
    if not provider:
        await callback.answer("المزود غير موجود")
        return

    total = await db.scalar(
        select(sa_func.count()).select_from(ProviderService)
        .where(
            ProviderService.provider_id == provider_id,
            ProviderService.category == cat,
        )
    ) or 0
    total_pages = max(1, (total + per_page - 1) // per_page)

    result = await db.execute(
        select(ProviderService)
        .where(
            ProviderService.provider_id == provider_id,
            ProviderService.category == cat,
        )
        .order_by(ProviderService.rate)
        .offset(page * per_page)
        .limit(per_page)
    )
    svcs = result.scalars().all()

    markup = settings_manager.get_markup_pct()
    safe_cat = _pcat_key(cat)
    text = (
        f"┌──── 📂 {cat[:40]} ────\n"
        f"│  المزود: <b>{provider.name}</b>\n"
        f"│  الخدمات: <b>{total}</b>  |  صفحة {page + 1}/{total_pages}\n"
        f"│  هامش الربح: <b>{markup:.0f}%</b>\n"
        "│  اضغط ➕ لمعاينة وإضافة خدمة:\n"
        "└──────────────────────"
    )

    buttons = []
    for ps in svcs:
        # Check if already added
        already = await db.scalar(
            select(sa_func.count()).select_from(Service)
            .where(Service.provider_service_id == ps.id)
        ) or 0
        status = "✅" if already else "➕"

        price = f"${float(ps.rate):.4f}" if ps.rate else "N/A"
        name_short = (ps.name or "")[:30]
        buttons.append([InlineKeyboardButton(
            text=f"{status} {name_short}  💰{price}",
            callback_data=f"adm:pfv:{ps.id}:{provider_id}:{target_plat}:{safe_cat}:{page}",
        )])

    # Pagination
    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton(text="◀️", callback_data=f"adm:pfs:{provider_id}:{target_plat}:{safe_cat}:{page-1}"))
    nav.append(InlineKeyboardButton(text=f"{page+1}/{total_pages}", callback_data="noop"))
    if page + 1 < total_pages:
        nav.append(InlineKeyboardButton(text="▶️", callback_data=f"adm:pfs:{provider_id}:{target_plat}:{safe_cat}:{page+1}"))
    if nav:
        buttons.append(nav)

    # Add all in this category
    buttons.append([InlineKeyboardButton(
        text=f"🤖 إضافة كل خدمات هذه الفئة ({total})",
        callback_data=f"adm:addcat2:{provider_id}:{safe_cat}",
    )])
    buttons.append([
        InlineKeyboardButton(text="◀️ رجوع", callback_data=f"adm:pfc:{provider_id}:{target_plat}"),
        InlineKeyboardButton(text="🏠 الرئيسية", callback_data="adm:panel"),
    ])
    await _safe_edit(callback, text, InlineKeyboardMarkup(inline_keyboard=buttons))
    await callback.answer()


class ConfirmAddServiceStates(StatesGroup):
    waiting_custom_name = State()


@router.callback_query(F.data.startswith("adm:pfv:"))
async def provider_service_preview(callback: CallbackQuery, db):
    """Step 5: Preview a single provider service before adding."""
    if not _admin_only(callback):
        return
    from repositories.provider_repo import get_provider_service as get_ps, get_provider
    from services.service_manager import build_service_name, detect_platform, detect_category_ar, extract_service_attributes

    parts = callback.data.split(":")
    ps_id = int(parts[2])
    provider_id = int(parts[3])
    target_plat = parts[4]
    safe_cat = parts[5]
    page = parts[6] if len(parts) > 6 else "0"

    ps = await get_ps(db, ps_id)
    if not ps:
        await callback.answer("❌ الخدمة غير موجودة")
        return

    provider = await get_provider(db, provider_id)
    prov_name = provider.name if provider else "—"

    # Check if already added
    already = await db.scalar(
        select(sa_func.count()).select_from(Service)
        .where(Service.provider_service_id == ps_id)
    ) or 0

    # Auto-detect values
    full_text = (ps.name or "") + " " + (ps.category or "")
    auto_plat = detect_platform(full_text)
    auto_cat = detect_category_ar(full_text)
    auto_name = build_service_name(ps.name or "", ps.category or "")
    attrs = extract_service_attributes(ps.name or "", ps.category or "")
    markup_rate = round(float(ps.rate or 0) * settings_manager.get_markup_multiplier(), 6)

    plat_info = PLATFORM_MAP.get(auto_plat, {"ar": auto_plat, "emoji": "📱"})
    min_q = f"{int(ps.min):,}" if ps.min else "—"
    max_q = f"{int(ps.max):,}" if ps.max else "—"
    refill_str = "✅ نعم" if ps.refill else "❌ لا"
    cancel_str = "✅ نعم" if ps.cancel else "❌ لا"

    text = (
        f"┌──── 🔍 معاينة خدمة ────\n"
        f"│  🏭 المزود: <b>{prov_name}</b>\n"
        f"│\n"
        f"│  📝 الاسم الأصلي:\n"
        f"│  <code>{(ps.name or '')[:80]}</code>\n"
        f"│  📂 فئة المزود: {ps.category or '—'}\n"
        f"│\n"
        f"│  ✨ الاسم المقترح:\n"
        f"│  <b>{auto_name[:60]}</b>\n"
        f"│\n"
        f"│  {plat_info['emoji']} المنصة: <b>{plat_info['ar']}</b>\n"
        f"│  📂 الفئة: <b>{auto_cat}</b>\n"
        f"│  💰 سعر المزود/1K: <b>${float(ps.rate or 0):.4f}</b>\n"
        f"│  💵 سعر البيع/1K: <b>${markup_rate:.4f}</b>\n"
        f"│  📊 الكمية: {min_q} — {max_q}\n"
        f"│  🚀 السرعة: {attrs.get('speed', '—')}\n"
        f"│  🏆 الجودة: {attrs.get('quality', '—')}\n"
        f"│  ♻️ التعويض: {refill_str}\n"
        f"│  ❌ الإلغاء: {cancel_str}\n"
        f"│\n"
    )

    if already:
        text += "│  ⚠️ <b>تمت إضافتها مسبقاً</b>\n"
    text += "└──────────────────────"

    back_cb = f"adm:pfs:{provider_id}:{target_plat}:{safe_cat}:{page}"
    buttons = []
    if not already:
        buttons.append([InlineKeyboardButton(
            text="✅ إضافة بالاسم المقترح",
            callback_data=f"adm:pfadd:{ps_id}:{provider_id}:{target_plat}:{safe_cat}:{page}",
        )])
        buttons.append([InlineKeyboardButton(
            text="✏️ إضافة بإسم مخصص",
            callback_data=f"adm:pfcust:{ps_id}:{provider_id}:{target_plat}:{safe_cat}:{page}",
        )])
    else:
        buttons.append([InlineKeyboardButton(
            text="⚠️ مضافة مسبقاً",
            callback_data="noop",
        )])
    buttons.append([
        InlineKeyboardButton(text="◀️ رجوع", callback_data=back_cb),
        InlineKeyboardButton(text="🏠 الرئيسية", callback_data="adm:panel"),
    ])
    await _safe_edit(callback, text, InlineKeyboardMarkup(inline_keyboard=buttons))
    await callback.answer()


@router.callback_query(F.data.startswith("adm:pfadd:"))
async def provider_add_confirmed(callback: CallbackQuery, db):
    """Add service with auto-generated name."""
    if not _admin_only(callback):
        return
    from repositories.provider_repo import get_provider_service as get_ps
    from services.service_manager import build_service_name, detect_platform, detect_category_ar, extract_service_attributes

    parts = callback.data.split(":")
    ps_id = int(parts[2])
    provider_id = int(parts[3])
    target_plat = parts[4]
    safe_cat = parts[5]
    page = parts[6] if len(parts) > 6 else "0"

    ps = await get_ps(db, ps_id)
    if not ps:
        await callback.answer("❌ الخدمة غير موجودة")
        return

    already = await db.scalar(
        select(sa_func.count()).select_from(Service)
        .where(Service.provider_service_id == ps_id)
    ) or 0
    if already:
        await callback.answer("⏭️ تمت الإضافة مسبقاً")
        return

    if not ps.rate or float(ps.rate) <= 0:
        await callback.answer("❌ السعر غير متاح")
        return

    full_text = (ps.name or "") + " " + (ps.category or "")
    plat = detect_platform(full_text)
    cat_ar = detect_category_ar(full_text)
    svc_name = build_service_name(ps.name or "", ps.category or "")
    attrs = extract_service_attributes(ps.name or "", ps.category or "")
    markup_rate = round(float(ps.rate) * settings_manager.get_markup_multiplier(), 6)

    svc = Service(
        name=svc_name, platform=plat, category=cat_ar,
        description=attrs["description"], price_per_1000=markup_rate,
        provider_service_id=ps.id, speed=attrs["speed"],
        quality=attrs["quality"], guarantee_days=attrs["guarantee_days"],
        is_active=True,
    )
    db.add(svc)
    await db.commit()

    text = (
        f"┌──── ✅ تمت الإضافة ────\n"
        f"│  📦 {svc_name[:50]}\n"
        f"│  📱 المنصة: {plat}\n"
        f"│  📂 الفئة: {cat_ar}\n"
        f"│  💰 السعر: ${markup_rate:.4f}/1K\n"
        "└──────────────────────"
    )
    back_cb = f"adm:pfs:{provider_id}:{target_plat}:{safe_cat}:{page}"
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="◀️ رجوع للقائمة", callback_data=back_cb)],
        [InlineKeyboardButton(text="📦 خدماتي", callback_data="adm:my_services")],
        [InlineKeyboardButton(text="🏠 الرئيسية", callback_data="adm:panel")],
    ])
    await _safe_edit(callback, text, kb)
    await callback.answer()


@router.callback_query(F.data.startswith("adm:pfcust:"))
async def provider_add_custom_name(callback: CallbackQuery, state: FSMContext, db):
    """Ask admin for a custom name before adding."""
    if not _admin_only(callback):
        return
    from repositories.provider_repo import get_provider_service as get_ps

    parts = callback.data.split(":")
    ps_id = int(parts[2])
    provider_id = int(parts[3])
    target_plat = parts[4]
    safe_cat = parts[5]
    page = parts[6] if len(parts) > 6 else "0"

    ps = await get_ps(db, ps_id)
    if not ps:
        await callback.answer("❌ الخدمة غير موجودة")
        return

    await state.set_state(ConfirmAddServiceStates.waiting_custom_name)
    await state.update_data(
        custom_ps_id=ps_id,
        custom_provider_id=provider_id,
        custom_target_plat=target_plat,
        custom_safe_cat=safe_cat,
        custom_page=page,
    )

    text = (
        f"┌──── ✏️ اسم مخصص ────\n"
        f"│  الاسم الأصلي:\n"
        f"│  <code>{(ps.name or '')[:80]}</code>\n"
        "│\n"
        "│  أرسل الاسم الذي تريده للخدمة:\n"
        "│  /cancel للإلغاء\n"
        "└──────────────────────"
    )
    await _safe_edit(callback, text, InlineKeyboardMarkup(inline_keyboard=[]))
    await callback.answer()


@router.message(ConfirmAddServiceStates.waiting_custom_name)
async def provider_add_custom_apply(message: Message, state: FSMContext, db):
    if not is_admin_or_mod(message.from_user.id):
        return
    if message.text and message.text.strip() == "/cancel":
        await state.clear()
        await message.answer("❌ تم الإلغاء", reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="◀️ لوحة الإدارة", callback_data="adm:panel")],
        ]))
        return

    data = await state.get_data()
    await state.clear()

    from repositories.provider_repo import get_provider_service as get_ps
    from services.service_manager import detect_platform, detect_category_ar, extract_service_attributes

    ps_id = data["custom_ps_id"]
    provider_id = data["custom_provider_id"]
    target_plat = data["custom_target_plat"]
    safe_cat = data["custom_safe_cat"]
    page = data["custom_page"]

    ps = await get_ps(db, ps_id)
    if not ps:
        await message.answer("❌ الخدمة غير موجودة")
        return

    custom_name = (message.text or "").strip()[:100]
    full_text = (ps.name or "") + " " + (ps.category or "")
    plat = detect_platform(full_text)
    cat_ar = detect_category_ar(full_text)
    attrs = extract_service_attributes(ps.name or "", ps.category or "")
    markup_rate = round(float(ps.rate or 0) * settings_manager.get_markup_multiplier(), 6)

    svc = Service(
        name=custom_name, platform=plat, category=cat_ar,
        description=attrs["description"], price_per_1000=markup_rate,
        provider_service_id=ps.id, speed=attrs["speed"],
        quality=attrs["quality"], guarantee_days=attrs["guarantee_days"],
        is_active=True,
    )
    db.add(svc)
    await db.commit()

    back_cb = f"adm:pfs:{provider_id}:{target_plat}:{safe_cat}:{page}"
    await message.answer(
        f"┌──── ✅ تمت الإضافة ────\n"
        f"│  📦 {custom_name[:50]}\n"
        f"│  📱 المنصة: {plat}\n"
        f"│  📂 الفئة: {cat_ar}\n"
        f"│  💰 السعر: ${markup_rate:.4f}/1K\n"
        "└──────────────────────",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="◀️ رجوع للقائمة", callback_data=back_cb)],
            [InlineKeyboardButton(text="📦 خدماتي", callback_data="adm:my_services")],
            [InlineKeyboardButton(text="🏠 الرئيسية", callback_data="adm:panel")],
        ]),
        parse_mode="HTML",
    )


# ── Bulk add helpers ──────────────────────────────────────────────────────

async def _bulk_add_provider_services(db, ps_list, callback=None):
    """Shared bulk add logic. Returns (added, skipped)."""
    from services.service_manager import build_service_name, detect_platform, detect_category_ar, extract_service_attributes

    added = 0
    skipped = 0
    batch: list[Service] = []
    markup = settings_manager.get_markup_multiplier()

    for ps in ps_list:
        if not ps.rate or float(ps.rate) <= 0:
            skipped += 1
            continue
        exists = await db.scalar(
            select(sa_func.count()).select_from(Service)
            .where(Service.provider_service_id == ps.id)
        ) or 0
        if exists:
            skipped += 1
            continue

        full = (ps.name or "") + " " + (ps.category or "")
        plat = detect_platform(full)
        cat_ar = detect_category_ar(full)
        svc_name = build_service_name(ps.name or "", ps.category or "")
        attrs = extract_service_attributes(ps.name or "", ps.category or "")
        markup_rate = round(float(ps.rate) * markup, 6)

        batch.append(Service(
            name=svc_name, platform=plat, category=cat_ar,
            description=attrs["description"], price_per_1000=markup_rate,
            provider_service_id=ps.id, speed=attrs["speed"],
            quality=attrs["quality"], guarantee_days=attrs["guarantee_days"],
            is_active=True,
        ))
        added += 1

        if len(batch) >= 50:
            db.add_all(batch)
            await db.commit()
            batch.clear()

    if batch:
        db.add_all(batch)
        await db.commit()

    return added, skipped


@router.callback_query(F.data.startswith("adm:addall:"))
async def add_all_from_provider(callback: CallbackQuery, db):
    """Bulk add ALL services from a provider."""
    if not _admin_only(callback):
        return
    from repositories.provider_repo import get_provider
    from models.provider_service import ProviderService

    provider_id = int(callback.data.split(":")[2])
    provider = await get_provider(db, provider_id)
    if not provider:
        await callback.answer("المزود غير موجود")
        return

    await _safe_edit(callback, f"⏳ جاري إضافة كل خدمات {provider.name}...", InlineKeyboardMarkup(inline_keyboard=[]))
    await callback.answer()

    result = await db.execute(
        select(ProviderService).where(ProviderService.provider_id == provider_id)
    )
    all_ps = result.scalars().all()
    added, skipped = await _bulk_add_provider_services(db, all_ps)

    text = (
        f"┌──── ✅ إضافة جماعية ────\n"
        f"│  المزود: <b>{provider.name}</b>\n"
        f"│  ➕ مضاف: <b>{added}</b>\n"
        f"│  ⏭️ تكرار/بدون سعر: <b>{skipped}</b>\n"
        "└──────────────────────"
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📦 عرض الخدمات", callback_data="adm:my_services")],
        [InlineKeyboardButton(text="◀️ رجوع", callback_data=f"adm:pfp:{provider_id}")],
        [InlineKeyboardButton(text="🏠 الرئيسية", callback_data="adm:panel")],
    ])
    await _safe_edit(callback, text, kb)


@router.callback_query(F.data.startswith("adm:addplat:"))
async def add_all_platform_services(callback: CallbackQuery, db):
    """Bulk add all services for a specific platform from a provider."""
    if not _admin_only(callback):
        return
    from repositories.provider_repo import get_provider
    from models.provider_service import ProviderService
    from services.service_manager import detect_platform

    parts = callback.data.split(":")
    provider_id = int(parts[2])
    target_plat = parts[3]

    provider = await get_provider(db, provider_id)
    if not provider:
        await callback.answer("المزود غير موجود")
        return

    plat_info = PLATFORM_MAP.get(target_plat, {"ar": target_plat, "emoji": "📱"})
    await _safe_edit(
        callback,
        f"⏳ جاري إضافة خدمات {plat_info['ar']}...",
        InlineKeyboardMarkup(inline_keyboard=[]),
    )
    await callback.answer()

    # Get all provider services, filter by detected platform
    result = await db.execute(
        select(ProviderService).where(ProviderService.provider_id == provider_id)
    )
    all_ps = result.scalars().all()
    filtered = [ps for ps in all_ps if detect_platform((ps.name or "") + " " + (ps.category or "")) == target_plat]

    added, skipped = await _bulk_add_provider_services(db, filtered)

    text = (
        f"┌──── ✅ إضافة جماعية ────\n"
        f"│  المزود: <b>{provider.name}</b>\n"
        f"│  المنصة: {plat_info['emoji']} <b>{plat_info['ar']}</b>\n"
        f"│  ➕ مضاف: <b>{added}</b>\n"
        f"│  ⏭️ تكرار/بدون سعر: <b>{skipped}</b>\n"
        "└──────────────────────"
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📦 عرض الخدمات", callback_data="adm:my_services")],
        [InlineKeyboardButton(text="◀️ رجوع", callback_data=f"adm:pfc:{provider_id}:{target_plat}")],
        [InlineKeyboardButton(text="🏠 الرئيسية", callback_data="adm:panel")],
    ])
    await _safe_edit(callback, text, kb)


@router.callback_query(F.data.startswith("adm:addcat2:"))
async def add_all_category_services(callback: CallbackQuery, db):
    """Bulk add all services in a specific provider category."""
    if not _admin_only(callback):
        return
    from repositories.provider_repo import get_provider
    from models.provider_service import ProviderService

    parts = callback.data.split(":")
    provider_id = int(parts[2])
    cat_key = parts[3]
    cat = _pcat_resolve(cat_key)

    provider = await get_provider(db, provider_id)
    if not provider:
        await callback.answer("المزود غير موجود")
        return

    await _safe_edit(callback, f"⏳ جاري إضافة خدمات الفئة...", InlineKeyboardMarkup(inline_keyboard=[]))
    await callback.answer()

    result = await db.execute(
        select(ProviderService).where(
            ProviderService.provider_id == provider_id,
            ProviderService.category == cat,
        )
    )
    cat_ps = result.scalars().all()
    added, skipped = await _bulk_add_provider_services(db, cat_ps)

    text = (
        f"┌──── ✅ إضافة جماعية ────\n"
        f"│  المزود: <b>{provider.name}</b>\n"
        f"│  📂 الفئة: <b>{cat[:40]}</b>\n"
        f"│  ➕ مضاف: <b>{added}</b>\n"
        f"│  ⏭️ تكرار/بدون سعر: <b>{skipped}</b>\n"
        "└──────────────────────"
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📦 عرض الخدمات", callback_data="adm:my_services")],
        [InlineKeyboardButton(text="◀️ رجوع", callback_data=f"adm:pfp:{provider_id}")],
        [InlineKeyboardButton(text="🏠 الرئيسية", callback_data="adm:panel")],
    ])
    await _safe_edit(callback, text, kb)


# Legacy: keep old callback working (redirect to new flow)
@router.callback_query(F.data.startswith("adm:provsvcs:"))
async def legacy_provsvcs(callback: CallbackQuery, db):
    parts = callback.data.split(":")
    provider_id = parts[2]
    class _Proxy:
        def __init__(self, orig, new_data):
            self._orig = orig
            self.data = new_data
        def __getattr__(self, name):
            return getattr(self._orig, name)
    proxy = _Proxy(callback, f"adm:pfp:{provider_id}")
    await provider_platforms(proxy, db)


# ════════════════════════════════════════════════════════════════
#  SYNC
# ════════════════════════════════════════════════════════════════

@router.callback_query(F.data == "adm:sync")
async def sync_providers_btn(callback: CallbackQuery, db):
    if not _admin_only(callback):
        return
    await _safe_edit(callback, "⏳ جاري المزامنة مع المزودين...", InlineKeyboardMarkup(inline_keyboard=[]))
    await callback.answer()

    total_new = await sync_all_providers(db)
    from repositories.provider_repo import get_all_providers
    providers = await get_all_providers(db)

    text = (
        "┌──── ✅ تمت المزامنة ────\n"
        f"│  المزودون:    <b>{len(providers)}</b>\n"
        f"│  خدمات جديدة: <b>{total_new:,}</b>\n"
        "│\n"
        "│  💡 استخدم 🤖 الإضافة التلقائية\n"
        "│  لإضافة الخدمات الجديدة.\n"
        "└──────────────────────"
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🤖 إضافة تلقائية", callback_data="adm:auto_add")],
        [InlineKeyboardButton(text="◀️ لوحة الإدارة", callback_data="adm:back")],
    ])
    await _safe_edit(callback, text, kb)


# ════════════════════════════════════════════════════════════════
#  PROVIDER MANAGEMENT (INLINE)
# ════════════════════════════════════════════════════════════════

@router.callback_query(F.data == "adm:providers_list")
async def providers_list(callback: CallbackQuery, db):
    if not _admin_only(callback):
        return
    from repositories.provider_repo import get_all_providers, count_provider_services

    providers = await get_all_providers(db)
    if not providers:
        text = "┌──── 🔌 المزودون ────\n│  لا يوجد مزودين.\n│  استخدم ➕ إضافة مزود.\n└──────────────────────"
        await _safe_edit(callback, text, _kb())
        await callback.answer()
        return

    text = (
        "┌──── 🔌 المزودون ────\n"
        f"│  العدد: <b>{len(providers)}</b>\n"
        "│  اختر مزوداً لإدارته:\n"
        "└──────────────────────"
    )
    buttons = []
    for p in providers:
        svc_count = await count_provider_services(db, p.id)
        status_icon = "🟢" if p.status else "🔴"
        buttons.append([InlineKeyboardButton(
            text=f"{status_icon} {p.name}  ({svc_count:,})",
            callback_data=f"adm:provedит:{p.id}",
        )])
    buttons.append([
        InlineKeyboardButton(text="➕ إضافة مزود", callback_data="adm:add_provider"),
        InlineKeyboardButton(text="◀️ رجوع", callback_data="adm:back"),
    ])
    await _safe_edit(callback, text, InlineKeyboardMarkup(inline_keyboard=buttons))
    await callback.answer()


@router.callback_query(F.data.startswith("adm:provedит:"))
async def provider_detail(callback: CallbackQuery, db):
    if not _admin_only(callback):
        return
    from repositories.provider_repo import get_provider, count_provider_services

    pid = int(callback.data.split(":")[2])
    p = await get_provider(db, pid)
    if not p:
        await callback.answer("المزود غير موجود")
        return

    svc_count = await count_provider_services(db, pid)
    status_icon = "🟢 نشط" if p.status else "🔴 معطّل"
    toggle_text = "🔴 تعطيل" if p.status else "🟢 تفعيل"

    text = (
        f"┌──── 🔌 {p.name} ────\n"
        f"│  🆔 #{p.id}\n"
        f"│  🔗 {p.api_url}\n"
        f"│  📦 الخدمات: <b>{svc_count:,}</b>\n"
        f"│  📊 الحالة: {status_icon}\n"
        "└──────────────────────"
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text=toggle_text, callback_data=f"adm:provtoggle:{pid}"),
            InlineKeyboardButton(text="🔄 مزامنة", callback_data=f"adm:provsync:{pid}"),
        ],
        [InlineKeyboardButton(text="📦 تصفح الخدمات", callback_data=f"adm:provsvcs:{pid}:0")],
        [
            InlineKeyboardButton(text="🗑 حذف المزود", callback_data=f"adm:provdel:{pid}"),
            InlineKeyboardButton(text="◀️ رجوع", callback_data="adm:providers_list"),
        ],
    ])
    await _safe_edit(callback, text, kb)
    await callback.answer()


@router.callback_query(F.data.startswith("adm:provtoggle:"))
async def toggle_provider(callback: CallbackQuery, db):
    if not _admin_only(callback):
        return
    from repositories.provider_repo import get_provider
    pid = int(callback.data.split(":")[2])
    p = await get_provider(db, pid)
    if p:
        p.status = not p.status
        await db.commit()
        await callback.answer("🟢 تم التفعيل" if p.status else "🔴 تم التعطيل")
    await provider_detail(callback, db)


@router.callback_query(F.data.startswith("adm:provsync:"))
async def sync_one_provider(callback: CallbackQuery, db):
    if not _admin_only(callback):
        return
    from repositories.provider_repo import get_provider
    from services.provider_manager import sync_provider_services

    pid = int(callback.data.split(":")[2])
    p = await get_provider(db, pid)
    if not p:
        await callback.answer("المزود غير موجود")
        return

    await _safe_edit(callback, f"⏳ مزامنة {p.name}...", InlineKeyboardMarkup(inline_keyboard=[]))
    await callback.answer()

    try:
        new_count = await sync_provider_services(db, p)
    except Exception as exc:
        new_count = 0
        logger.error("sync_provider error: %s", exc)

    text = (
        f"┌──── ✅ مزامنة {p.name} ────\n"
        f"│  خدمات جديدة: <b>{new_count:,}</b>\n"
        "└──────────────────────"
    )
    await _safe_edit(callback, text, _kb(back=f"adm:provedит:{pid}"))


@router.callback_query(F.data.startswith("adm:provdel:"))
async def delete_provider(callback: CallbackQuery, db):
    if not _admin_only(callback):
        return
    from repositories.provider_repo import get_provider
    from sqlalchemy import delete as sa_delete
    pid = int(callback.data.split(":")[2])
    p = await get_provider(db, pid)
    if p:
        # Cascade delete: services → provider_services → provider
        # 1. Get all provider_service IDs for this provider
        ps_ids_result = await db.execute(
            select(ProviderService.id).where(ProviderService.provider_id == pid)
        )
        ps_ids = [r[0] for r in ps_ids_result.all()]
        
        # 2. Delete store services that reference these provider_services
        if ps_ids:
            await db.execute(
                sa_delete(Service).where(Service.provider_service_id.in_(ps_ids))
            )
        
        # 3. Delete provider_services
        await db.execute(
            sa_delete(ProviderService).where(ProviderService.provider_id == pid)
        )
        
        # 4. Delete the provider itself
        await db.delete(p)
        await db.commit()
        await callback.answer("🗑 تم حذف المزود وخدماته", show_alert=True)
    await providers_list(callback, db)


# ════════════════════════════════════════════════════════════════
#  ADD PROVIDER (INLINE)
# ════════════════════════════════════════════════════════════════

class AddProviderInlineStates(StatesGroup):
    waiting_name = State()
    waiting_url = State()
    waiting_key = State()


@router.callback_query(F.data == "adm:add_provider")
async def add_provider_start(callback: CallbackQuery, state: FSMContext):
    if not _admin_only(callback):
        return
    await state.set_state(AddProviderInlineStates.waiting_name)
    await state.update_data(ui_chat_id=callback.message.chat.id, ui_message_id=callback.message.message_id)
    await callback.message.edit_text(
        "┌──── ➕ إضافة مزود ────\n│  الخطوة 1/3\n│  أرسل اسم المزود:\n│  /cancel للإلغاء\n└──────────────────────"
    )
    await callback.answer()


@router.message(AddProviderInlineStates.waiting_name)
async def add_provider_name(message: Message, state: FSMContext):
    if not is_admin_or_mod(message.from_user.id):
        return
    if message.text and message.text.strip() == "/cancel":
        await state.clear()
        return
    await state.update_data(name=(message.text or "").strip())
    await state.set_state(AddProviderInlineStates.waiting_url)
    data = await state.get_data()
    try:
        await message.bot.edit_message_text(
            chat_id=data["ui_chat_id"], message_id=data["ui_message_id"],
            text="┌──── ➕ إضافة مزود ────\n│  الخطوة 2/3\n│  أرسل رابط API:\n│  مثال: https://smm.example.com/api/v2\n│  /cancel للإلغاء\n└──────────────────────"
        )
    except Exception:
        pass
    try:
        await message.delete()
    except Exception:
        pass


@router.message(AddProviderInlineStates.waiting_url)
async def add_provider_url(message: Message, state: FSMContext):
    if not is_admin_or_mod(message.from_user.id):
        return
    if message.text and message.text.strip() == "/cancel":
        await state.clear()
        return
    url = (message.text or "").strip()
    if not url.startswith("http"):
        await message.answer("❌ رابط غير صحيح. يبدأ بـ http")
        return
    await state.update_data(api_url=url)
    await state.set_state(AddProviderInlineStates.waiting_key)
    data = await state.get_data()
    try:
        await message.bot.edit_message_text(
            chat_id=data["ui_chat_id"], message_id=data["ui_message_id"],
            text="┌──── ➕ إضافة مزود ────\n│  الخطوة 3/3\n│  أرسل مفتاح API:\n│  ⚠️ سيُحذف الرسالة فوراً\n│  /cancel للإلغاء\n└──────────────────────"
        )
    except Exception:
        pass
    try:
        await message.delete()
    except Exception:
        pass


@router.message(AddProviderInlineStates.waiting_key)
async def add_provider_key(message: Message, state: FSMContext, db):
    if not is_admin_or_mod(message.from_user.id):
        return
    if message.text and message.text.strip() == "/cancel":
        await state.clear()
        return

    data = await state.get_data()
    await state.clear()

    from models.provider import Provider
    provider = Provider(
        name=data["name"],
        api_url=data["api_url"],
        api_key=(message.text or "").strip(),
        status=True,
    )
    db.add(provider)
    await db.commit()

    try:
        await message.delete()
    except Exception:
        pass

    text = (
        "┌──── ✅ تمت الإضافة ────\n"
        f"│  الاسم: <b>{data['name']}</b>\n"
        f"│  الرابط: {data['api_url']}\n"
        "│\n"
        "│  يمكنك الآن مزامنة الخدمات.\n"
        "└──────────────────────"
    )
    try:
        await message.bot.edit_message_text(
            chat_id=data["ui_chat_id"], message_id=data["ui_message_id"],
            text=text,
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🔄 مزامنة الآن", callback_data="adm:sync")],
                [InlineKeyboardButton(text="◀️ لوحة الإدارة", callback_data="adm:panel")],
            ]),
            parse_mode="HTML",
        )
    except Exception:
        await message.answer(text, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="◀️ لوحة الإدارة", callback_data="adm:panel")],
        ]))
    logger.info("Provider added: %s (%s)", data["name"], data["api_url"])


# ════════════════════════════════════════════════════════════════
#  MANUAL ADD SERVICE
# ════════════════════════════════════════════════════════════════

@router.callback_query(F.data == "adm:add_service")
async def add_service_start(callback: CallbackQuery, state: FSMContext):
    if not _admin_only(callback):
        return
    await state.set_state(AddServiceStates.waiting_name)
    await state.update_data(ui_chat_id=callback.message.chat.id, ui_message_id=callback.message.message_id)
    await callback.message.edit_text(
        "┌──── ➕ إضافة خدمة يدوية ────\n"
        "│  الخطوة 1/5\n"
        "│  أرسل اسم الخدمة:\n"
        "│  /cancel للإلغاء\n"
        "└──────────────────────"
    )
    await callback.answer()


@router.message(AddServiceStates.waiting_name)
async def add_service_name(message: Message, state: FSMContext):
    if not is_admin_or_mod(message.from_user.id):
        return
    if message.text and message.text.strip() == "/cancel":
        await state.clear()
        await message.answer("❌ تم الإلغاء", reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="◀️ لوحة الإدارة", callback_data="adm:panel")]
        ]))
        return
    await state.update_data(svc_name=(message.text or "").strip()[:100])
    await state.set_state(AddServiceStates.waiting_platform)
    data = await state.get_data()
    buttons = []
    for key, info in PLATFORM_MAP.items():
        buttons.append([InlineKeyboardButton(
            text=f"{info['emoji']} {info['ar']}",
            callback_data=f"adm:addsvc_plat:{key}",
        )])
    try:
        await message.bot.edit_message_text(
            chat_id=data["ui_chat_id"], message_id=data["ui_message_id"],
            text=(
                "┌──── ➕ إضافة خدمة يدوية ────\n"
                "│  الخطوة 2/5\n"
                "│  اختر المنصة:\n"
                "└──────────────────────"
            ),
            reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons),
        )
    except Exception:
        await message.answer(
            "┌──── ➕ إضافة خدمة يدوية ────\n│  الخطوة 2/5\n│  أرسل اسم المنصة (مثال: instagram):\n│  /cancel للإلغاء\n└──────────────────────"
        )
    try:
        await message.delete()
    except Exception:
        pass


@router.callback_query(F.data.startswith("adm:addsvc_plat:"))
async def add_service_platform_cb(callback: CallbackQuery, state: FSMContext):
    if not _admin_only(callback):
        return
    current = await state.get_state()
    if current != AddServiceStates.waiting_platform.state:
        await callback.answer()
        return
    platform = callback.data.split(":")[2]
    await state.update_data(svc_platform=platform)
    await state.set_state(AddServiceStates.waiting_category)
    await callback.message.edit_text(
        "┌──── ➕ إضافة خدمة يدوية ────\n"
        "│  الخطوة 3/5\n"
        "│  أرسل اسم القسم (مثال: متابعين):\n"
        "│  /cancel للإلغاء\n"
        "└──────────────────────"
    )
    await callback.answer()


@router.message(AddServiceStates.waiting_platform)
async def add_service_platform_text(message: Message, state: FSMContext):
    if not is_admin_or_mod(message.from_user.id):
        return
    if message.text and message.text.strip() == "/cancel":
        await state.clear()
        await message.answer("❌ تم الإلغاء", reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="◀️ لوحة الإدارة", callback_data="adm:panel")]
        ]))
        return
    platform = (message.text or "").strip().lower()
    await state.update_data(svc_platform=platform)
    await state.set_state(AddServiceStates.waiting_category)
    data = await state.get_data()
    try:
        await message.bot.edit_message_text(
            chat_id=data["ui_chat_id"], message_id=data["ui_message_id"],
            text=(
                "┌──── ➕ إضافة خدمة يدوية ────\n"
                "│  الخطوة 3/5\n"
                "│  أرسل اسم القسم (مثال: متابعين):\n"
                "│  /cancel للإلغاء\n"
                "└──────────────────────"
            ),
        )
    except Exception:
        pass
    try:
        await message.delete()
    except Exception:
        pass


@router.message(AddServiceStates.waiting_category)
async def add_service_category(message: Message, state: FSMContext):
    if not is_admin_or_mod(message.from_user.id):
        return
    if message.text and message.text.strip() == "/cancel":
        await state.clear()
        await message.answer("❌ تم الإلغاء", reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="◀️ لوحة الإدارة", callback_data="adm:panel")]
        ]))
        return
    await state.update_data(svc_category=(message.text or "").strip()[:50])
    await state.set_state(AddServiceStates.waiting_price)
    data = await state.get_data()
    try:
        await message.bot.edit_message_text(
            chat_id=data["ui_chat_id"], message_id=data["ui_message_id"],
            text=(
                "┌──── ➕ إضافة خدمة يدوية ────\n"
                "│  الخطوة 4/5\n"
                "│  أرسل السعر لكل 1000:\n"
                "│  مثال: <code>0.5</code>\n"
                "│  /cancel للإلغاء\n"
                "└──────────────────────"
            ),
            parse_mode="HTML",
        )
    except Exception:
        pass
    try:
        await message.delete()
    except Exception:
        pass


@router.message(AddServiceStates.waiting_price)
async def add_service_price(message: Message, state: FSMContext):
    if not is_admin_or_mod(message.from_user.id):
        return
    if message.text and message.text.strip() == "/cancel":
        await state.clear()
        await message.answer("❌ تم الإلغاء", reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="◀️ لوحة الإدارة", callback_data="adm:panel")]
        ]))
        return
    try:
        price = float((message.text or "").strip())
        if price <= 0:
            raise ValueError
    except ValueError:
        await message.answer("❌ رقم غير صحيح. مثال: <code>0.5</code>", parse_mode="HTML")
        return
    await state.update_data(svc_price=price)
    await state.set_state(AddServiceStates.waiting_description)
    data = await state.get_data()
    try:
        await message.bot.edit_message_text(
            chat_id=data["ui_chat_id"], message_id=data["ui_message_id"],
            text=(
                "┌──── ➕ إضافة خدمة يدوية ────\n"
                "│  الخطوة 5/5\n"
                "│  أرسل وصف الخدمة (اختياري):\n"
                "│  أو أرسل /skip لتخطي\n"
                "│  /cancel للإلغاء\n"
                "└──────────────────────"
            ),
        )
    except Exception:
        pass
    try:
        await message.delete()
    except Exception:
        pass


@router.message(AddServiceStates.waiting_description)
async def add_service_description(message: Message, state: FSMContext, db):
    if not is_admin_or_mod(message.from_user.id):
        return
    if message.text and message.text.strip() == "/cancel":
        await state.clear()
        await message.answer("❌ تم الإلغاء", reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="◀️ لوحة الإدارة", callback_data="adm:panel")]
        ]))
        return

    data = await state.get_data()
    await state.clear()

    desc = None
    if message.text and message.text.strip() != "/skip":
        desc = (message.text or "").strip()[:500]

    svc = Service(
        name=data["svc_name"],
        platform=data["svc_platform"],
        category=data["svc_category"],
        description=desc,
        price_per_1000=data["svc_price"],
        is_active=True,
    )
    db.add(svc)
    await db.commit()
    await db.refresh(svc)

    text = (
        "┌──── ✅ تمت الإضافة ────\n"
        f"│  🆔 #{svc.id}\n"
        f"│  📛 {svc.name}\n"
        f"│  📱 {svc.platform}\n"
        f"│  📂 {svc.category}\n"
        f"│  💰 ${float(svc.price_per_1000):.6f}/1K\n"
        "└──────────────────────"
    )
    try:
        await message.bot.edit_message_text(
            chat_id=data["ui_chat_id"], message_id=data["ui_message_id"],
            text=text,
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="📦 عرض الخدمات", callback_data="adm:my_services")],
                [InlineKeyboardButton(text="➕ إضافة أخرى", callback_data="adm:add_service")],
                [InlineKeyboardButton(text="◀️ لوحة الإدارة", callback_data="adm:panel")],
            ]),
            parse_mode="HTML",
        )
    except Exception:
        await message.answer(text, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="◀️ لوحة الإدارة", callback_data="adm:panel")],
        ]))
    try:
        await message.delete()
    except Exception:
        pass
    logger.info("Manual service added: #%s %s", svc.id, svc.name)


# ════════════════════════════════════════════════════════════════
#  EDIT CATEGORY
# ════════════════════════════════════════════════════════════════

@router.callback_query(F.data.startswith("adm:editcat:"))
async def edit_category_start(callback: CallbackQuery, state: FSMContext):
    if not _admin_only(callback):
        return
    sid = int(callback.data.split(":")[2])
    await state.set_state(EditCategoryStates.waiting_new_category)
    await state.update_data(edit_service_id=sid)
    await callback.message.edit_text(
        "┌──── ✏️ تعديل القسم ────\n"
        "│  أرسل اسم القسم الجديد:\n"
        "│  /cancel للإلغاء\n"
        "└──────────────────────"
    )
    await callback.answer()


@router.message(EditCategoryStates.waiting_new_category)
async def set_new_category(message: Message, state: FSMContext, db):
    if not is_admin_or_mod(message.from_user.id):
        return
    if message.text and message.text.strip() == "/cancel":
        await state.clear()
        await message.answer("❌ تم الإلغاء", reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="◀️ لوحة الإدارة", callback_data="adm:panel")]
        ]))
        return
    data = await state.get_data()
    await state.clear()
    s = await get_service(db, data["edit_service_id"])
    new_cat = (message.text or "").strip()[:50]
    if s:
        s.category = new_cat
        await db.commit()
    text = f"┌──── ✅ تم التحديث ────\n│  القسم الجديد: {new_cat}\n└──────────────────────"
    await message.answer(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📦 عرض الخدمة", callback_data=f"adm:editsvc:{data['edit_service_id']}")],
        [InlineKeyboardButton(text="◀️ لوحة الإدارة", callback_data="adm:panel")],
    ]), parse_mode="HTML")


# ════════════════════════════════════════════════════════════════
#  EDIT DESCRIPTION
# ════════════════════════════════════════════════════════════════

@router.callback_query(F.data.startswith("adm:editdesc:"))
async def edit_desc_start(callback: CallbackQuery, state: FSMContext):
    if not _admin_only(callback):
        return
    sid = int(callback.data.split(":")[2])
    await state.set_state(EditDescStates.waiting_new_desc)
    await state.update_data(edit_service_id=sid)
    await callback.message.edit_text(
        "┌──── ✏️ تعديل الوصف ────\n"
        "│  أرسل الوصف الجديد:\n"
        "│  أو /skip لإزالة الوصف\n"
        "│  /cancel للإلغاء\n"
        "└──────────────────────"
    )
    await callback.answer()


@router.message(EditDescStates.waiting_new_desc)
async def set_new_desc(message: Message, state: FSMContext, db):
    if not is_admin_or_mod(message.from_user.id):
        return
    if message.text and message.text.strip() == "/cancel":
        await state.clear()
        await message.answer("❌ تم الإلغاء", reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="◀️ لوحة الإدارة", callback_data="adm:panel")]
        ]))
        return
    data = await state.get_data()
    await state.clear()
    s = await get_service(db, data["edit_service_id"])
    if message.text and message.text.strip() == "/skip":
        new_desc = None
        desc_display = "(تم الإزالة)"
    else:
        new_desc = (message.text or "").strip()[:500]
        desc_display = new_desc
    if s:
        s.description = new_desc
        await db.commit()
    text = f"┌──── ✅ تم التحديث ────\n│  الوصف: {desc_display}\n└──────────────────────"
    await message.answer(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📦 عرض الخدمة", callback_data=f"adm:editsvc:{data['edit_service_id']}")],
        [InlineKeyboardButton(text="◀️ لوحة الإدارة", callback_data="adm:panel")],
    ]), parse_mode="HTML")


# ════════════════════════════════════════════════════════════════
#  EDIT PLATFORM
# ════════════════════════════════════════════════════════════════

@router.callback_query(F.data.startswith("adm:editplat:"))
async def edit_platform_start(callback: CallbackQuery, state: FSMContext):
    if not _admin_only(callback):
        return
    sid = int(callback.data.split(":")[2])
    await state.set_state(EditPlatformStates.waiting_new_platform)
    await state.update_data(edit_service_id=sid)

    buttons = []
    for key, info in PLATFORM_MAP.items():
        buttons.append([InlineKeyboardButton(
            text=f"{info['emoji']} {info['ar']}",
            callback_data=f"adm:setplat:{sid}:{key}",
        )])
    buttons.append([InlineKeyboardButton(text="◀️ رجوع", callback_data=f"adm:editsvc:{sid}")])

    await callback.message.edit_text(
        "┌──── ✏️ تعديل المنصة ────\n"
        "│  اختر المنصة الجديدة:\n"
        "└──────────────────────",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("adm:setplat:"))
async def set_platform(callback: CallbackQuery, state: FSMContext, db):
    if not _admin_only(callback):
        return
    parts = callback.data.split(":")
    sid = int(parts[2])
    new_plat = parts[3]
    await state.clear()

    s = await get_service(db, sid)
    if s:
        s.platform = new_plat
        await db.commit()

    plat_info = PLATFORM_MAP.get(new_plat, {"ar": new_plat, "emoji": "📱"})
    await callback.answer(f"✅ تم تغيير المنصة إلى {plat_info['ar']}", show_alert=True)
    await _show_edit_service(callback, db, sid)


# ════════════════════════════════════════════════════════════════
#  CATEGORIES MANAGEMENT
# ════════════════════════════════════════════════════════════════

@router.callback_query(F.data == "adm:categories")
async def categories_list(callback: CallbackQuery, db):
    if not _admin_only(callback):
        return

    result = await db.execute(
        select(Service.platform, Service.category, sa_func.count().label("cnt"))
        .group_by(Service.platform, Service.category)
        .order_by(Service.platform, sa_func.count().desc())
    )
    rows = result.all()

    if not rows:
        text = (
            "┌──── 📂 الأقسام ────\n"
            "│  لا توجد أقسام بعد.\n"
            "└──────────────────────"
        )
        await _safe_edit(callback, text, _kb())
        await callback.answer()
        return

    # Group by platform
    from collections import OrderedDict
    grouped: dict[str, list[tuple[str, int]]] = OrderedDict()
    for plat, cat, cnt in rows:
        grouped.setdefault(plat or "other", []).append((cat or "(بدون قسم)", cnt))

    lines = []
    buttons = []
    for plat, cats in grouped.items():
        info = PLATFORM_MAP.get(plat, {"ar": plat, "emoji": "📱"})
        lines.append(f"│  {info['emoji']} <b>{info['ar']}</b>:")
        for cat, cnt in cats[:8]:
            lines.append(f"│    📂 {cat}: <b>{cnt}</b>")
        if len(cats) > 8:
            lines.append(f"│    ... و {len(cats) - 8} أقسام أخرى")
        lines.append("│")

    # Build buttons: each category gets rename + delete
    unique_cats = {}
    for plat, cat, cnt in rows:
        cat_name = cat or ""
        if cat_name not in unique_cats:
            unique_cats[cat_name] = cnt
        else:
            unique_cats[cat_name] += cnt

    for cat_name, cnt in list(unique_cats.items())[:15]:
        cat_display = cat_name or "(بدون قسم)"
        safe_cat = _acat_key(cat_name)
        buttons.append([
            InlineKeyboardButton(
                text=f"✏️ {cat_display} ({cnt})",
                callback_data=f"adm:renamecat:{safe_cat}",
            ),
            InlineKeyboardButton(
                text=f"🗑",
                callback_data=f"adm:delcat:{safe_cat}",
            ),
        ])

    total_cats = len(unique_cats)
    text = (
        "┌──── 📂 إدارة الأقسام ────\n"
        f"│  الأقسام: <b>{total_cats}</b>\n"
        "├──────────────────────\n"
        + "\n".join(lines) +
        "│  ✏️ اضغط على قسم لإعادة تسميته\n"
        "│  🗑 لحذف (تعطيل) جميع خدماته\n"
        "└──────────────────────"
    )
    buttons.append([InlineKeyboardButton(text="➕ إضافة قسم جديد", callback_data="adm:addcat")])
    buttons.append([
        InlineKeyboardButton(text="◀️ رجوع", callback_data="adm:back"),
        InlineKeyboardButton(text="🏠 الرئيسية", callback_data="adm:panel"),
    ])
    await _safe_edit(callback, text, InlineKeyboardMarkup(inline_keyboard=buttons))
    await callback.answer()


class RenameCategoryStates(StatesGroup):
    waiting_new_name = State()


class AddCategoryStates(StatesGroup):
    waiting_cat_name = State()


@router.callback_query(F.data.startswith("adm:delcat:"))
async def delete_category(callback: CallbackQuery, db):
    if not _admin_only(callback):
        return
    cat_key = callback.data.split(":", 2)[2]
    cat = _acat_resolve(cat_key)
    cat_display = cat or "(بدون قسم)"

    result = await db.execute(select(Service).where(Service.category == cat))
    services = result.scalars().all()
    count = 0
    for svc in services:
        svc.is_active = False
        count += 1
    await db.commit()

    text = (
        "┌──── ✅ تم تعطيل القسم ────\n"
        f"│  📂 القسم: <b>{cat_display}</b>\n"
        f"│  ❌ الخدمات المعطّلة: <b>{count}</b>\n"
        "│\n"
        "│  💡 يمكنك إعادة تفعيلها من إدارة الخدمات\n"
        "└──────────────────────"
    )
    await _safe_edit(callback, text, InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📂 الأقسام", callback_data="adm:categories")],
        [InlineKeyboardButton(text="◀️ لوحة الإدارة", callback_data="adm:panel")],
    ]))
    await callback.answer()


@router.callback_query(F.data == "adm:addcat")
async def add_category_start(callback: CallbackQuery, state: FSMContext):
    if not _admin_only(callback):
        return
    await state.set_state(AddCategoryStates.waiting_cat_name)
    await callback.message.edit_text(
        "┌──── ➕ إضافة قسم جديد ────\n"
        "│\n"
        "│  أرسل اسم القسم الجديد:\n"
        "│  (سيتم إنشاؤه فارغاً، أضف خدمات إليه لاحقاً)\n"
        "│\n"
        "│  /cancel للإلغاء\n"
        "└──────────────────────",
        parse_mode="HTML",
    )
    await callback.answer()


@router.message(AddCategoryStates.waiting_cat_name)
async def add_category_apply(message: Message, state: FSMContext, db):
    if not is_admin_or_mod(message.from_user.id):
        return
    if message.text and message.text.strip() == "/cancel":
        await state.clear()
        await message.answer("❌ تم الإلغاء", reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="📂 الأقسام", callback_data="adm:categories")],
            [InlineKeyboardButton(text="◀️ لوحة الإدارة", callback_data="adm:panel")],
        ]))
        return

    await state.clear()
    new_cat = (message.text or "").strip()[:50]

    # Check if category already exists
    existing = await db.scalar(
        select(sa_func.count()).select_from(Service).where(Service.category == new_cat)
    )
    if existing:
        text = (
            "┌──── ⚠️ القسم موجود ────\n"
            f"│  📂 القسم: <b>{new_cat}</b>\n"
            f"│  📦 يحتوي على <b>{existing}</b> خدمة\n"
            "└──────────────────────"
        )
    else:
        text = (
            "┌──── ✅ تم إنشاء القسم ────\n"
            f"│  📂 القسم: <b>{new_cat}</b>\n"
            "│\n"
            "│  💡 القسم فارغ حالياً.\n"
            "│  أضف خدمات إليه من 'إضافة خدمة يدوية'\n"
            "│  أو عدّل قسم خدمة موجودة.\n"
            "└──────────────────────"
        )

    await message.answer(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📂 الأقسام", callback_data="adm:categories")],
        [InlineKeyboardButton(text="➕ إضافة خدمة يدوية", callback_data="adm:add_service")],
        [InlineKeyboardButton(text="◀️ لوحة الإدارة", callback_data="adm:panel")],
    ]), parse_mode="HTML")


@router.callback_query(F.data.startswith("adm:renamecat:"))
async def rename_category_start(callback: CallbackQuery, state: FSMContext):
    if not _admin_only(callback):
        return
    cat_key = callback.data.split(":", 2)[2]
    old_cat = _acat_resolve(cat_key)
    await state.set_state(RenameCategoryStates.waiting_new_name)
    await state.update_data(old_category=old_cat)
    cat_display = old_cat or "(بدون قسم)"
    await callback.message.edit_text(
        f"┌──── ✏️ إعادة تسمية القسم ────\n"
        f"│  القسم الحالي: <b>{cat_display}</b>\n"
        "│\n"
        "│  أرسل الاسم الجديد للقسم:\n"
        "│  سيتم تغييره في جميع الخدمات.\n"
        "│  /cancel للإلغاء\n"
        "└──────────────────────",
        parse_mode="HTML",
    )
    await callback.answer()


@router.message(RenameCategoryStates.waiting_new_name)
async def rename_category_apply(message: Message, state: FSMContext, db):
    if not is_admin_or_mod(message.from_user.id):
        return
    if message.text and message.text.strip() == "/cancel":
        await state.clear()
        await message.answer("❌ تم الإلغاء", reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="📂 الأقسام", callback_data="adm:categories")],
            [InlineKeyboardButton(text="◀️ لوحة الإدارة", callback_data="adm:panel")],
        ]))
        return
    data = await state.get_data()
    await state.clear()
    old_cat = data["old_category"]
    new_cat = (message.text or "").strip()[:50]

    result = await db.execute(select(Service).where(Service.category == old_cat))
    services = result.scalars().all()
    count = 0
    for svc in services:
        svc.category = new_cat
        count += 1
    await db.commit()

    text = (
        "┌──── ✅ تم التحديث ────\n"
        f"│  القسم القديم: {old_cat or '(بدون)'}\n"
        f"│  القسم الجديد: {new_cat}\n"
        f"│  الخدمات المحدّثة: <b>{count}</b>\n"
        "└──────────────────────"
    )
    await message.answer(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📂 الأقسام", callback_data="adm:categories")],
        [InlineKeyboardButton(text="◀️ لوحة الإدارة", callback_data="adm:panel")],
    ]), parse_mode="HTML")


# ════════════════════════════════════════════════════════════════
#  ORDERS MANAGEMENT
# ════════════════════════════════════════════════════════════════

@router.callback_query(F.data.startswith("adm:orders_mgmt"))
async def orders_management(callback: CallbackQuery, db):
    if not _admin_only(callback):
        return
    from models.order import Order

    parts = callback.data.split(":")
    page = int(parts[2]) if len(parts) > 2 and parts[2].isdigit() else 0
    per_page = 10

    total = await db.scalar(
        select(sa_func.count()).select_from(Order)
    ) or 0
    total_pages = max(1, (total + per_page - 1) // per_page)

    result = await db.execute(
        select(Order)
        .order_by(Order.created_at.desc())
        .offset(page * per_page)
        .limit(per_page)
    )
    orders = result.scalars().all()

    if not orders:
        text = (
            "┌──── 📋 إدارة الطلبات ────\n"
            "│  لا توجد طلبات بعد.\n"
            "└──────────────────────"
        )
        await _safe_edit(callback, text, _kb())
        await callback.answer()
        return

    status_map = {
        "pending": "⏳",
        "processing": "🔄",
        "completed": "✅",
        "canceled": "❌",
        "partial": "⚠️",
        "error": "💥",
    }

    lines = []
    buttons = []
    for o in orders:
        s_icon = status_map.get(o.status, "❓")
        lines.append(
            f"│  {s_icon} #{o.id}  💰${float(o.charge):.4f}  👤{o.user_id}"
        )
        buttons.append([InlineKeyboardButton(
            text=f"{s_icon} طلب #{o.id} — ${float(o.charge):.4f}",
            callback_data=f"adm:orderdet:{o.id}",
        )])

    text = (
        "┌──── 📋 إدارة الطلبات ────\n"
        f"│  الإجمالي: <b>{total:,}</b>  |  صفحة {page + 1}/{total_pages}\n"
        "├──────────────────────\n"
        + "\n".join(lines) + "\n"
        "└──────────────────────"
    )

    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton(text="◀️", callback_data=f"adm:orders_mgmt:{page-1}"))
    nav.append(InlineKeyboardButton(text=f"{page+1}/{total_pages}", callback_data="noop"))
    if page < total_pages - 1:
        nav.append(InlineKeyboardButton(text="▶️", callback_data=f"adm:orders_mgmt:{page+1}"))
    if nav:
        buttons.append(nav)

    buttons.append([
        InlineKeyboardButton(text="◀️ رجوع", callback_data="adm:back"),
        InlineKeyboardButton(text="🏠 الرئيسية", callback_data="adm:panel"),
    ])
    await _safe_edit(callback, text, InlineKeyboardMarkup(inline_keyboard=buttons))
    await callback.answer()


@router.callback_query(F.data.startswith("adm:orderdet:"))
async def order_detail(callback: CallbackQuery, db):
    if not _admin_only(callback):
        return
    from models.order import Order

    oid = int(callback.data.split(":")[2])
    result = await db.execute(select(Order).where(Order.id == oid))
    o = result.scalar_one_or_none()
    if not o:
        await callback.answer("الطلب غير موجود")
        return

    svc = await get_service(db, o.service_id)
    svc_name = svc.name[:40] if svc else "(محذوفة)"

    status_map = {
        "pending": "⏳ قيد الانتظار",
        "processing": "🔄 قيد التنفيذ",
        "completed": "✅ مكتمل",
        "canceled": "❌ ملغي",
        "partial": "⚠️ جزئي",
        "error": "💥 خطأ",
    }
    status_text = status_map.get(o.status, o.status)
    created = o.created_at.strftime("%Y-%m-%d %H:%M") if o.created_at else "غير معروف"

    text = (
        f"┌──── 📋 طلب #{o.id} ────\n"
        f"│  👤 المستخدم: <code>{o.user_id}</code>\n"
        f"│  📦 الخدمة: {svc_name}\n"
        f"│  🔗 الرابط: {o.link[:40]}\n"
        f"│  📊 الكمية: <b>{o.quantity:,}</b>\n"
        f"│  💰 المبلغ: <b>${float(o.charge):.6f}</b>\n"
        f"│  📊 الحالة: {status_text}\n"
        f"│  📅 التاريخ: {created}\n"
    )
    if o.external_order_id:
        text += f"│  🆔 طلب خارجي: {o.external_order_id}\n"
    text += "└──────────────────────"

    kb = _kb(back="adm:orders_mgmt")
    await _safe_edit(callback, text, kb)
    await callback.answer()
