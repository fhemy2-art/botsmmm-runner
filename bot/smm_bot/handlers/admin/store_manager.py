"""
Admin: Store layout management — platforms, categories, services.
Controls display order, naming, layout (columns), visibility.
"""
import logging
from aiogram import Router, F
from aiogram.types import CallbackQuery, Message, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from sqlalchemy import select, func as sa_func

from models.service import Service
from repositories.service_repo import get_active_platforms, get_categories_for_platform, get_service
from services.service_manager import PLATFORM_MAP
from services import settings_manager
from config import ADMIN_IDS

logger = logging.getLogger(__name__)
router = Router()

# ── Category callback mapping (to avoid 64-byte callback_data limit) ──────
_STORE_CAT_MAP: dict[str, str] = {}  # short_key → full category name


def _scat_key(category: str) -> str:
    """Return a short key for store callback_data. If short enough, use as-is."""
    if len(category.encode('utf-8')) <= 20:
        return category
    import hashlib
    h = hashlib.md5(category.encode()).hexdigest()[:8]
    key = f"sc{h}"
    _STORE_CAT_MAP[key] = category
    return key


def _scat_resolve(key: str) -> str:
    """Resolve a short key back to full category name."""
    return _STORE_CAT_MAP.get(key, key)


_moderator_ids_cache: list[int] = []

def _set_mod_cache(ids: list[int]) -> None:
    global _moderator_ids_cache
    _moderator_ids_cache = ids

def _is_admin(uid: int) -> bool:
    return uid in ADMIN_IDS or uid in _moderator_ids_cache


def _kb(*rows, back: str = "adm:panel") -> InlineKeyboardMarkup:
    btns = list(rows)
    btns.append([
        InlineKeyboardButton(text="◀️ رجوع", callback_data=back),
        InlineKeyboardButton(text="🏠 الرئيسية", callback_data="adm:panel"),
    ])
    return InlineKeyboardMarkup(inline_keyboard=btns)


async def _safe_edit(cb: CallbackQuery, text: str, kb: InlineKeyboardMarkup) -> None:
    try:
        await cb.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
    except Exception as exc:
        if "message is not modified" not in str(exc).lower():
            try:
                await cb.message.answer(text, reply_markup=kb, parse_mode="HTML")
            except Exception:
                pass


# ═══════════════════════════════════════════════════════════════
#  STORE MANAGEMENT — MAIN MENU
# ═══════════════════════════════════════════════════════════════

@router.callback_query(F.data == "adm:store")
async def store_menu(cb: CallbackQuery, db):
    if not _is_admin(cb.from_user.id):
        return

    plat_count = len(await get_active_platforms(db))
    cat_count = await db.scalar(
        select(sa_func.count(sa_func.distinct(Service.category))).select_from(Service).where(Service.is_active)
    ) or 0
    svc_count = await db.scalar(
        select(sa_func.count()).select_from(Service).where(Service.is_active)
    ) or 0

    cols_p = settings_manager.get_platform_columns()
    cols_c = settings_manager.get_category_columns()

    text = (
        "┌──── 🏪 إدارة المتجر ────\n"
        "│\n"
        f"│  📱 المنصات النشطة: <b>{plat_count}</b>\n"
        f"│  📂 الأقسام: <b>{cat_count}</b>\n"
        f"│  📦 الخدمات: <b>{svc_count}</b>\n"
        "│\n"
        f"│  📱 عرض المنصات: <b>{cols_p} بالصف</b>\n"
        f"│  📂 عرض الأقسام: <b>{cols_c} بالصف</b>\n"
        "│\n"
        "└──────────────────────"
    )

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📱 إدارة المنصات (الأقسام)", callback_data="adm:store:platforms")],
        [InlineKeyboardButton(text="📂 إدارة الفئات", callback_data="adm:store:cats")],
        [InlineKeyboardButton(text="📦 إدارة أسماء الخدمات", callback_data="adm:store:svcnames")],
        [
            InlineKeyboardButton(text=f"📱 عرض: {cols_p} بالصف", callback_data="adm:store:togglepcol"),
            InlineKeyboardButton(text=f"📂 عرض: {cols_c} بالصف", callback_data="adm:store:toggleccol"),
        ],
        [
            InlineKeyboardButton(text="◀️ رجوع", callback_data="adm:panel"),
            InlineKeyboardButton(text="🏠 الرئيسية", callback_data="adm:panel"),
        ],
    ])
    await _safe_edit(cb, text, kb)
    await cb.answer()


@router.callback_query(F.data == "adm:store:togglepcol")
async def toggle_platform_columns(cb: CallbackQuery, db):
    if not _is_admin(cb.from_user.id):
        return
    current = settings_manager.get_platform_columns()
    new_val = 2 if current == 1 else 1
    settings_manager.set_platform_columns(new_val)
    await cb.answer(f"✅ عرض المنصات: {new_val} بالصف", show_alert=True)
    await store_menu(cb, db)


@router.callback_query(F.data == "adm:store:toggleccol")
async def toggle_category_columns(cb: CallbackQuery, db):
    if not _is_admin(cb.from_user.id):
        return
    current = settings_manager.get_category_columns()
    new_val = 2 if current == 1 else 1
    settings_manager.set_category_columns(new_val)
    await cb.answer(f"✅ عرض الأقسام: {new_val} بالصف", show_alert=True)
    await store_menu(cb, db)


# ═══════════════════════════════════════════════════════════════
#  PLATFORM MANAGEMENT
# ═══════════════════════════════════════════════════════════════

@router.callback_query(F.data == "adm:store:platforms")
async def platforms_list(cb: CallbackQuery, db):
    if not _is_admin(cb.from_user.id):
        return

    active = await get_active_platforms(db)
    hidden = settings_manager.get_hidden_platforms()
    custom_order = settings_manager.get_platform_order()

    # Build ordered list: custom order first, then remaining
    all_plats = list(PLATFORM_MAP.keys())
    ordered = [p for p in custom_order if p in all_plats]
    for p in all_plats:
        if p not in ordered:
            ordered.append(p)

    text = (
        "┌──── 📱 إدارة المنصات ────\n"
        "│\n"
        "│  اضغط منصة لتعديلها\n"
        "│  🟢 = ظاهرة  🔴 = مخفية  ⚪ = بدون خدمات\n"
        "│\n"
        "│  استخدم ⬆️⬇️ لتغيير الترتيب\n"
        "│\n"
        "└──────────────────────"
    )

    buttons = []
    for i, plat in enumerate(ordered):
        info = PLATFORM_MAP.get(plat, {"ar": plat, "emoji": "📱"})
        custom_name = settings_manager.get_platform_custom_name(plat)
        display_name = custom_name or info["ar"]

        if plat in hidden:
            status = "🔴"
        elif plat in active:
            status = "🟢"
        else:
            status = "⚪"

        row = [InlineKeyboardButton(
            text=f"{status} {info['emoji']} {display_name}",
            callback_data=f"adm:store:pedit:{plat}",
        )]
        # Move buttons
        move_btns = []
        if i > 0:
            move_btns.append(InlineKeyboardButton(text="⬆️", callback_data=f"adm:store:pmove:{plat}:up"))
        if i < len(ordered) - 1:
            move_btns.append(InlineKeyboardButton(text="⬇️", callback_data=f"adm:store:pmove:{plat}:down"))
        if move_btns:
            row.extend(move_btns)

        buttons.append(row)

    buttons.append([
        InlineKeyboardButton(text="◀️ رجوع", callback_data="adm:store"),
        InlineKeyboardButton(text="🏠 الرئيسية", callback_data="adm:panel"),
    ])
    await _safe_edit(cb, text, InlineKeyboardMarkup(inline_keyboard=buttons))
    await cb.answer()


@router.callback_query(F.data.startswith("adm:store:pmove:"))
async def move_platform(cb: CallbackQuery, db):
    if not _is_admin(cb.from_user.id):
        return
    parts = cb.data.split(":")
    plat = parts[3]
    direction = parts[4]

    # Get current order
    custom_order = settings_manager.get_platform_order()
    all_plats = list(PLATFORM_MAP.keys())
    ordered = [p for p in custom_order if p in all_plats]
    for p in all_plats:
        if p not in ordered:
            ordered.append(p)

    if plat in ordered:
        idx = ordered.index(plat)
        if direction == "up" and idx > 0:
            ordered[idx], ordered[idx - 1] = ordered[idx - 1], ordered[idx]
        elif direction == "down" and idx < len(ordered) - 1:
            ordered[idx], ordered[idx + 1] = ordered[idx + 1], ordered[idx]

    settings_manager.set_platform_order(ordered)
    await cb.answer("✅ تم تحديث الترتيب")
    await platforms_list(cb, db)


@router.callback_query(F.data.startswith("adm:store:pedit:"))
async def edit_platform(cb: CallbackQuery, db):
    if not _is_admin(cb.from_user.id):
        return
    plat = cb.data.split(":")[3]
    info = PLATFORM_MAP.get(plat, {"ar": plat, "emoji": "📱"})
    custom_name = settings_manager.get_platform_custom_name(plat)
    display_name = custom_name or info["ar"]
    hidden = plat in settings_manager.get_hidden_platforms()

    # Count services
    svc_count = await db.scalar(
        select(sa_func.count()).select_from(Service).where(
            Service.platform == plat, Service.is_active
        )
    ) or 0

    cat_result = await db.execute(
        select(Service.category, sa_func.count().label("cnt"))
        .where(Service.platform == plat, Service.is_active)
        .group_by(Service.category)
        .order_by(sa_func.count().desc())
    )
    cats = cat_result.all()

    status = "🔴 مخفية" if hidden else "🟢 ظاهرة"
    toggle_text = "🟢 إظهار" if hidden else "🔴 إخفاء"

    lines = [
        f"┌──── {info['emoji']} تعديل المنصة ────\n"
        f"│\n"
        f"│  📱 الاسم الأصلي: <b>{info['ar']}</b>\n"
        f"│  ✏️ الاسم المعروض: <b>{display_name}</b>\n"
        f"│  📊 الحالة: {status}\n"
        f"│  📦 الخدمات: <b>{svc_count}</b>\n"
        f"│  📂 الفئات: <b>{len(cats)}</b>\n"
    ]
    if cats:
        lines.append("│\n│  📂 الفئات:")
        for cat, cnt in cats[:10]:
            lines.append(f"│    • {cat or '(بدون)'}: {cnt}")
    lines.append("│\n└──────────────────────")

    text = "\n".join(lines)

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✏️ تغيير الاسم المعروض", callback_data=f"adm:store:prename:{plat}")],
        [InlineKeyboardButton(text="🔄 إعادة الاسم الأصلي", callback_data=f"adm:store:preset:{plat}")],
        [InlineKeyboardButton(text=toggle_text, callback_data=f"adm:store:ptoggle:{plat}")],
        [InlineKeyboardButton(text="📂 إدارة فئات هذه المنصة", callback_data=f"adm:store:pcats:{plat}")],
        [
            InlineKeyboardButton(text="◀️ رجوع", callback_data="adm:store:platforms"),
            InlineKeyboardButton(text="🏠 الرئيسية", callback_data="adm:panel"),
        ],
    ])
    await _safe_edit(cb, text, kb)
    await cb.answer()


@router.callback_query(F.data.startswith("adm:store:ptoggle:"))
async def toggle_platform_visibility(cb: CallbackQuery, db):
    if not _is_admin(cb.from_user.id):
        return
    plat = cb.data.split(":")[3]
    hidden = settings_manager.get_hidden_platforms()
    if plat in hidden:
        hidden.remove(plat)
        settings_manager.set_hidden_platforms(hidden)
        await cb.answer("🟢 تم إظهار المنصة", show_alert=True)
    else:
        hidden.append(plat)
        settings_manager.set_hidden_platforms(hidden)
        await cb.answer("🔴 تم إخفاء المنصة", show_alert=True)
    await edit_platform(cb, db)


@router.callback_query(F.data.startswith("adm:store:preset:"))
async def reset_platform_name(cb: CallbackQuery, db):
    if not _is_admin(cb.from_user.id):
        return
    plat = cb.data.split(":")[3]
    settings_manager.remove_platform_custom_name(plat)
    await cb.answer("✅ تم إعادة الاسم الأصلي", show_alert=True)
    await edit_platform(cb, db)


class RenamePlatformStates(StatesGroup):
    waiting_name = State()

@router.callback_query(F.data.startswith("adm:store:prename:"))
async def rename_platform_start(cb: CallbackQuery, state: FSMContext):
    if not _is_admin(cb.from_user.id):
        return
    plat = cb.data.split(":")[3]
    info = PLATFORM_MAP.get(plat, {"ar": plat, "emoji": "📱"})
    await state.set_state(RenamePlatformStates.waiting_name)
    await state.update_data(rename_platform=plat)
    await cb.message.edit_text(
        f"┌──── ✏️ تغيير اسم {info['emoji']} {info['ar']} ────\n"
        "│\n"
        "│  أرسل الاسم الجديد للمنصة:\n"
        "│  (هذا الاسم يظهر للمستخدمين)\n"
        "│\n"
        "│  /cancel للإلغاء\n"
        "└──────────────────────",
        parse_mode="HTML",
    )
    await cb.answer()


@router.message(RenamePlatformStates.waiting_name)
async def rename_platform_apply(msg: Message, state: FSMContext):
    if not _is_admin(msg.from_user.id):
        return
    if msg.text and msg.text.strip() == "/cancel":
        await state.clear()
        await msg.answer("❌ تم الإلغاء", reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="📱 المنصات", callback_data="adm:store:platforms")],
        ]))
        return
    data = await state.get_data()
    await state.clear()
    plat = data["rename_platform"]
    new_name = (msg.text or "").strip()[:50]
    settings_manager.set_platform_custom_name(plat, new_name)

    text = (
        f"┌──── ✅ تم التحديث ────\n"
        f"│  الاسم الجديد: <b>{new_name}</b>\n"
        "└──────────────────────"
    )
    await msg.answer(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📱 المنصات", callback_data="adm:store:platforms")],
        [InlineKeyboardButton(text="◀️ لوحة الإدارة", callback_data="adm:panel")],
    ]), parse_mode="HTML")


# ═══════════════════════════════════════════════════════════════
#  CATEGORY MANAGEMENT (PER PLATFORM)
# ═══════════════════════════════════════════════════════════════

@router.callback_query(F.data == "adm:store:cats")
async def categories_select_platform(cb: CallbackQuery, db):
    if not _is_admin(cb.from_user.id):
        return

    active = await get_active_platforms(db)
    text = (
        "┌──── 📂 إدارة الفئات ────\n"
        "│\n"
        "│  اختر المنصة لإدارة فئاتها:\n"
        "│\n"
        "└──────────────────────"
    )

    buttons = []
    for plat in active:
        info = PLATFORM_MAP.get(plat, {"ar": plat, "emoji": "📱"})
        custom_name = settings_manager.get_platform_custom_name(plat)
        display = custom_name or info["ar"]
        buttons.append([InlineKeyboardButton(
            text=f"{info['emoji']} {display}",
            callback_data=f"adm:store:pcats:{plat}",
        )])

    buttons.append([
        InlineKeyboardButton(text="◀️ رجوع", callback_data="adm:store"),
        InlineKeyboardButton(text="🏠 الرئيسية", callback_data="adm:panel"),
    ])
    await _safe_edit(cb, text, InlineKeyboardMarkup(inline_keyboard=buttons))
    await cb.answer()


@router.callback_query(F.data.startswith("adm:store:pcats:"))
async def platform_categories(cb: CallbackQuery, db):
    if not _is_admin(cb.from_user.id):
        return
    plat = cb.data.split(":")[3]
    info = PLATFORM_MAP.get(plat, {"ar": plat, "emoji": "📱"})

    result = await db.execute(
        select(Service.category, sa_func.count().label("cnt"))
        .where(Service.platform == plat)
        .group_by(Service.category)
        .order_by(sa_func.count().desc())
    )
    cats = result.all()

    hidden_cats = settings_manager.get_hidden_categories(plat)
    custom_order = settings_manager.get_category_order(plat)

    # Sort by custom order
    if custom_order:
        ordered_cats = []
        for c in custom_order:
            for cat, cnt in cats:
                if cat == c:
                    ordered_cats.append((cat, cnt))
                    break
        for cat, cnt in cats:
            if cat not in custom_order:
                ordered_cats.append((cat, cnt))
        cats = ordered_cats

    text = (
        f"┌──── {info['emoji']} فئات {info['ar']} ────\n"
        "│\n"
        "│  اضغط فئة لتعديلها\n"
        "│  🟢 = ظاهرة  🔴 = مخفية\n"
        "│  ⬆️⬇️ لتغيير الترتيب\n"
        "│\n"
        "└──────────────────────"
    )

    buttons = []
    cat_list = [(c, n) for c, n in cats]
    for i, (cat, cnt) in enumerate(cat_list):
        cat_name = cat or "(بدون قسم)"
        custom_name = settings_manager.get_category_custom_name(cat_name)
        display = custom_name or cat_name
        is_hidden = cat_name in hidden_cats
        status = "🔴" if is_hidden else "🟢"
        safe_cat = _scat_key(cat_name)

        row = [InlineKeyboardButton(
            text=f"{status} {display} ({cnt})",
            callback_data=f"adm:store:cedit:{plat}:{safe_cat}",
        )]
        move_btns = []
        if i > 0:
            move_btns.append(InlineKeyboardButton(text="⬆️", callback_data=f"adm:store:cmove:{plat}:{safe_cat}:up"))
        if i < len(cat_list) - 1:
            move_btns.append(InlineKeyboardButton(text="⬇️", callback_data=f"adm:store:cmove:{plat}:{safe_cat}:dn"))
        if move_btns:
            row.extend(move_btns)
        buttons.append(row)

    buttons.append([InlineKeyboardButton(text="➕ إضافة فئة جديدة", callback_data=f"adm:store:catadd:{plat}")])
    buttons.append([
        InlineKeyboardButton(text="◀️ رجوع", callback_data="adm:store:cats"),
        InlineKeyboardButton(text="🏠 الرئيسية", callback_data="adm:panel"),
    ])
    await _safe_edit(cb, text, InlineKeyboardMarkup(inline_keyboard=buttons))
    await cb.answer()


@router.callback_query(F.data.startswith("adm:store:cmove:"))
async def move_category(cb: CallbackQuery, db):
    if not _is_admin(cb.from_user.id):
        return
    parts = cb.data.split(":")
    plat = parts[3]
    cat_key = parts[4]
    cat = _scat_resolve(cat_key)
    direction = parts[5]

    # Get current categories for this platform
    result = await db.execute(
        select(Service.category).where(Service.platform == plat)
        .group_by(Service.category).order_by(sa_func.count().desc())
    )
    db_cats = [r[0] or "(بدون قسم)" for r in result.all()]

    custom_order = settings_manager.get_category_order(plat)
    if custom_order:
        ordered = [c for c in custom_order if c in db_cats]
        for c in db_cats:
            if c not in ordered:
                ordered.append(c)
    else:
        ordered = db_cats

    if cat in ordered:
        idx = ordered.index(cat)
        if direction == "up" and idx > 0:
            ordered[idx], ordered[idx - 1] = ordered[idx - 1], ordered[idx]
        elif direction == "down" and idx < len(ordered) - 1:
            ordered[idx], ordered[idx + 1] = ordered[idx + 1], ordered[idx]

    settings_manager.set_category_order(plat, ordered)
    await cb.answer("✅ تم تحديث الترتيب")

    # Re-render platform categories (cannot mutate cb.data — frozen model)
    class _Proxy:
        def __init__(self, original, new_data):
            self._orig = original
            self.data = new_data
        def __getattr__(self, name):
            return getattr(self._orig, name)
    proxy = _Proxy(cb, f"adm:store:pcats:{plat}")
    await platform_categories(proxy, db)


@router.callback_query(F.data.startswith("adm:store:cedit:"))
async def edit_category(cb: CallbackQuery, db):
    if not _is_admin(cb.from_user.id):
        return
    parts = cb.data.split(":")
    plat = parts[3]
    cat_key = parts[4]
    cat = _scat_resolve(cat_key)
    info = PLATFORM_MAP.get(plat, {"ar": plat, "emoji": "📱"})

    hidden_cats = settings_manager.get_hidden_categories(plat)
    is_hidden = cat in hidden_cats
    custom_name = settings_manager.get_category_custom_name(cat)

    svc_count = await db.scalar(
        select(sa_func.count()).select_from(Service).where(
            Service.platform == plat, Service.category == cat
        )
    ) or 0

    status = "🔴 مخفية" if is_hidden else "🟢 ظاهرة"
    toggle_text = "🟢 إظهار" if is_hidden else "🔴 إخفاء"
    safe_cat = _scat_key(cat)

    text = (
        f"┌──── 📂 تعديل فئة ────\n"
        "│\n"
        f"│  📱 المنصة: {info['emoji']} {info['ar']}\n"
        f"│  📂 الفئة: <b>{cat}</b>\n"
    )
    if custom_name:
        text += f"│  ✏️ الاسم المعروض: <b>{custom_name}</b>\n"
    text += (
        f"│  📊 الحالة: {status}\n"
        f"│  📦 الخدمات: <b>{svc_count}</b>\n"
        "│\n"
        "└──────────────────────"
    )

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✏️ تغيير الاسم", callback_data=f"adm:store:crename:{plat}:{safe_cat}")],
        [InlineKeyboardButton(text=toggle_text, callback_data=f"adm:store:ctoggle:{plat}:{safe_cat}")],
        [InlineKeyboardButton(text="📛 إعادة تسمية بالداتابيس", callback_data=f"adm:store:cdbren:{plat}:{safe_cat}")],
        [InlineKeyboardButton(text="🗑 حذف (تعطيل الخدمات)", callback_data=f"adm:store:cdel:{plat}:{safe_cat}")],
        [
            InlineKeyboardButton(text="◀️ رجوع", callback_data=f"adm:store:pcats:{plat}"),
            InlineKeyboardButton(text="🏠 الرئيسية", callback_data="adm:panel"),
        ],
    ])
    await _safe_edit(cb, text, kb)
    await cb.answer()


@router.callback_query(F.data.startswith("adm:store:ctoggle:"))
async def toggle_category(cb: CallbackQuery, db):
    if not _is_admin(cb.from_user.id):
        return
    parts = cb.data.split(":")
    plat = parts[3]
    cat_key = parts[4]
    cat = _scat_resolve(cat_key)
    hidden_cats = settings_manager.get_hidden_categories(plat)
    is_hidden = cat in hidden_cats
    settings_manager.set_hidden_category(plat, cat, not is_hidden)
    msg = "🟢 تم إظهار الفئة" if is_hidden else "🔴 تم إخفاء الفئة"
    await cb.answer(msg, show_alert=True)

    safe_cat = _scat_key(cat)
    # Re-render edit_category by calling it with overridden parts
    # (cannot mutate cb.data — aiogram 3.x freezes pydantic models)
    class _Proxy:
        def __init__(self, original, new_data):
            self._orig = original
            self.data = new_data
        def __getattr__(self, name):
            return getattr(self._orig, name)
    proxy = _Proxy(cb, f"adm:store:cedit:{plat}:{safe_cat}")
    await edit_category(proxy, db)


@router.callback_query(F.data.startswith("adm:store:cdel:"))
async def delete_category(cb: CallbackQuery, db):
    if not _is_admin(cb.from_user.id):
        return
    parts = cb.data.split(":")
    plat = parts[3]
    cat_key = parts[4]
    cat = _scat_resolve(cat_key)

    result = await db.execute(
        select(Service).where(Service.platform == plat, Service.category == cat)
    )
    services = result.scalars().all()
    count = 0
    for svc in services:
        svc.is_active = False
        count += 1
    await db.commit()

    text = (
        "┌──── ✅ تم تعطيل الفئة ────\n"
        f"│  📂 الفئة: <b>{cat}</b>\n"
        f"│  ❌ الخدمات المعطّلة: <b>{count}</b>\n"
        "│\n"
        "│  💡 يمكنك إعادة تفعيلها من إدارة الخدمات\n"
        "└──────────────────────"
    )
    await _safe_edit(cb, text, InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📂 الفئات", callback_data=f"adm:store:pcats:{plat}")],
        [InlineKeyboardButton(text="◀️ لوحة الإدارة", callback_data="adm:panel")],
    ]))
    await cb.answer()


# ── Rename category (display name only) ────
class RenameCatDisplayStates(StatesGroup):
    waiting_name = State()

@router.callback_query(F.data.startswith("adm:store:crename:"))
async def rename_cat_display_start(cb: CallbackQuery, state: FSMContext):
    if not _is_admin(cb.from_user.id):
        return
    parts = cb.data.split(":")
    plat = parts[3]
    cat_key = parts[4]
    cat = _scat_resolve(cat_key)
    await state.set_state(RenameCatDisplayStates.waiting_name)
    await state.update_data(rename_plat=plat, rename_cat=cat)
    await cb.message.edit_text(
        f"┌──── ✏️ تغيير اسم الفئة ────\n"
        f"│  الفئة الحالية: <b>{cat}</b>\n"
        "│\n"
        "│  أرسل الاسم الجديد (يظهر للمستخدمين):\n"
        "│  /cancel للإلغاء\n"
        "└──────────────────────",
        parse_mode="HTML",
    )
    await cb.answer()

@router.message(RenameCatDisplayStates.waiting_name)
async def rename_cat_display_apply(msg: Message, state: FSMContext):
    if not _is_admin(msg.from_user.id):
        return
    if msg.text and msg.text.strip() == "/cancel":
        await state.clear()
        await msg.answer("❌ تم الإلغاء", reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="◀️ لوحة الإدارة", callback_data="adm:panel")],
        ]))
        return
    data = await state.get_data()
    await state.clear()
    cat = data["rename_cat"]
    plat = data["rename_plat"]
    new_name = (msg.text or "").strip()[:50]
    settings_manager.set_category_custom_name(cat, new_name)

    await msg.answer(
        f"┌──── ✅ تم التحديث ────\n│  الاسم الجديد: <b>{new_name}</b>\n└──────────────────────",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="📂 الفئات", callback_data=f"adm:store:pcats:{plat}")],
            [InlineKeyboardButton(text="◀️ لوحة الإدارة", callback_data="adm:panel")],
        ]), parse_mode="HTML")


# ── Rename category in DB (updates all services) ────
class RenameCatDbStates(StatesGroup):
    waiting_name = State()

@router.callback_query(F.data.startswith("adm:store:cdbren:"))
async def rename_cat_db_start(cb: CallbackQuery, state: FSMContext):
    if not _is_admin(cb.from_user.id):
        return
    parts = cb.data.split(":")
    plat = parts[3]
    cat_key = parts[4]
    cat = _scat_resolve(cat_key)
    await state.set_state(RenameCatDbStates.waiting_name)
    await state.update_data(rename_plat=plat, rename_cat=cat)
    await cb.message.edit_text(
        f"┌──── 📛 إعادة تسمية بالداتابيس ────\n"
        f"│  الفئة الحالية: <b>{cat}</b>\n"
        "│\n"
        "│  ⚠️ هذا يغيّر اسم الفئة في جميع\n"
        "│  الخدمات بالداتابيس (تغيير دائم).\n"
        "│\n"
        "│  أرسل الاسم الجديد:\n"
        "│  /cancel للإلغاء\n"
        "└──────────────────────",
        parse_mode="HTML",
    )
    await cb.answer()

@router.message(RenameCatDbStates.waiting_name)
async def rename_cat_db_apply(msg: Message, state: FSMContext, db):
    if not _is_admin(msg.from_user.id):
        return
    if msg.text and msg.text.strip() == "/cancel":
        await state.clear()
        await msg.answer("❌ تم الإلغاء", reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="◀️ لوحة الإدارة", callback_data="adm:panel")],
        ]))
        return
    data = await state.get_data()
    await state.clear()
    cat = data["rename_cat"]
    plat = data["rename_plat"]
    new_name = (msg.text or "").strip()[:50]

    result = await db.execute(
        select(Service).where(Service.platform == plat, Service.category == cat)
    )
    services = result.scalars().all()
    count = 0
    for svc in services:
        svc.category = new_name
        count += 1
    await db.commit()

    await msg.answer(
        f"┌──── ✅ تم التحديث ────\n"
        f"│  القديم: {cat}\n"
        f"│  الجديد: <b>{new_name}</b>\n"
        f"│  الخدمات المحدّثة: <b>{count}</b>\n"
        "└──────────────────────",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="📂 الفئات", callback_data=f"adm:store:pcats:{plat}")],
            [InlineKeyboardButton(text="◀️ لوحة الإدارة", callback_data="adm:panel")],
        ]), parse_mode="HTML")


# ── Add new category ────
class AddNewCatStates(StatesGroup):
    waiting_name = State()

@router.callback_query(F.data.startswith("adm:store:catadd:"))
async def add_category_start(cb: CallbackQuery, state: FSMContext):
    if not _is_admin(cb.from_user.id):
        return
    plat = cb.data.split(":")[3]
    await state.set_state(AddNewCatStates.waiting_name)
    await state.update_data(add_cat_plat=plat)
    await cb.message.edit_text(
        "┌──── ➕ إضافة فئة جديدة ────\n"
        "│\n"
        "│  أرسل اسم الفئة الجديدة:\n"
        "│  (مثال: متابعين، لايكات، مشاهدات)\n"
        "│\n"
        "│  /cancel للإلغاء\n"
        "└──────────────────────",
        parse_mode="HTML",
    )
    await cb.answer()

@router.message(AddNewCatStates.waiting_name)
async def add_category_apply(msg: Message, state: FSMContext, db):
    if not _is_admin(msg.from_user.id):
        return
    if msg.text and msg.text.strip() == "/cancel":
        await state.clear()
        await msg.answer("❌ تم الإلغاء", reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="◀️ لوحة الإدارة", callback_data="adm:panel")],
        ]))
        return
    data = await state.get_data()
    await state.clear()
    plat = data["add_cat_plat"]
    new_cat = (msg.text or "").strip()[:50]

    existing = await db.scalar(
        select(sa_func.count()).select_from(Service).where(
            Service.platform == plat, Service.category == new_cat
        )
    )

    if existing:
        text = f"┌──── ⚠️ الفئة موجودة ────\n│  📂 {new_cat}: {existing} خدمة\n└──────────────────────"
    else:
        text = (
            f"┌──── ✅ تم إنشاء الفئة ────\n"
            f"│  📂 الفئة: <b>{new_cat}</b>\n"
            "│\n"
            "│  💡 الفئة فارغة حالياً.\n"
            "│  أضف خدمات إليها من 'إضافة خدمة يدوية'\n"
            "└──────────────────────"
        )

    await msg.answer(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📂 الفئات", callback_data=f"adm:store:pcats:{plat}")],
        [InlineKeyboardButton(text="➕ إضافة خدمة يدوية", callback_data="adm:add_service")],
        [InlineKeyboardButton(text="◀️ لوحة الإدارة", callback_data="adm:panel")],
    ]), parse_mode="HTML")


# ═══════════════════════════════════════════════════════════════
#  SERVICE NAMES MANAGEMENT
# ═══════════════════════════════════════════════════════════════

@router.callback_query(F.data == "adm:store:svcnames")
async def svcnames_select_platform(cb: CallbackQuery, db):
    if not _is_admin(cb.from_user.id):
        return
    active = await get_active_platforms(db)

    text = (
        "┌──── 📦 إدارة أسماء الخدمات ────\n"
        "│\n"
        "│  اختر المنصة ثم الفئة لتعديل\n"
        "│  أسماء الخدمات:\n"
        "│\n"
        "└──────────────────────"
    )

    buttons = []
    for plat in active:
        info = PLATFORM_MAP.get(plat, {"ar": plat, "emoji": "📱"})
        buttons.append([InlineKeyboardButton(
            text=f"{info['emoji']} {info['ar']}",
            callback_data=f"adm:store:svcplat:{plat}",
        )])
    buttons.append([
        InlineKeyboardButton(text="◀️ رجوع", callback_data="adm:store"),
        InlineKeyboardButton(text="🏠 الرئيسية", callback_data="adm:panel"),
    ])
    await _safe_edit(cb, text, InlineKeyboardMarkup(inline_keyboard=buttons))
    await cb.answer()


@router.callback_query(F.data.startswith("adm:store:svcplat:"))
async def svcnames_select_category(cb: CallbackQuery, db):
    if not _is_admin(cb.from_user.id):
        return
    plat = cb.data.split(":")[3]
    info = PLATFORM_MAP.get(plat, {"ar": plat, "emoji": "📱"})

    result = await db.execute(
        select(Service.category, sa_func.count().label("cnt"))
        .where(Service.platform == plat)
        .group_by(Service.category)
        .order_by(sa_func.count().desc())
    )
    cats = result.all()

    text = (
        f"┌──── {info['emoji']} {info['ar']} — الفئات ────\n"
        "│\n"
        "│  اختر فئة لتعديل أسماء خدماتها:\n"
        "│\n"
        "└──────────────────────"
    )

    buttons = []
    for cat, cnt in cats:
        cat_name = cat or "(بدون)"
        safe_cat = _scat_key(cat_name)
        buttons.append([InlineKeyboardButton(
            text=f"📂 {cat_name} ({cnt})",
            callback_data=f"adm:store:svclist:{plat}:{safe_cat}:0",
        )])
    buttons.append([
        InlineKeyboardButton(text="◀️ رجوع", callback_data="adm:store:svcnames"),
        InlineKeyboardButton(text="🏠 الرئيسية", callback_data="adm:panel"),
    ])
    await _safe_edit(cb, text, InlineKeyboardMarkup(inline_keyboard=buttons))
    await cb.answer()


@router.callback_query(F.data.startswith("adm:store:svclist:"))
async def svcnames_list(cb: CallbackQuery, db):
    if not _is_admin(cb.from_user.id):
        return
    parts = cb.data.split(":")
    plat = parts[3]
    cat_key = parts[4]
    cat = _scat_resolve(cat_key)
    page = int(parts[5]) if len(parts) > 5 else 0
    per_page = 8

    total = await db.scalar(
        select(sa_func.count()).select_from(Service).where(
            Service.platform == plat, Service.category == cat
        )
    ) or 0
    total_pages = max(1, (total + per_page - 1) // per_page)

    result = await db.execute(
        select(Service).where(Service.platform == plat, Service.category == cat)
        .order_by(Service.sort_order, Service.id)
        .offset(page * per_page).limit(per_page)
    )
    services = result.scalars().all()

    info = PLATFORM_MAP.get(plat, {"ar": plat, "emoji": "📱"})
    text = (
        f"┌──── {info['emoji']} {cat} — الخدمات ────\n"
        f"│  صفحة {page + 1}/{total_pages} | إجمالي: {total}\n"
        "│  اضغط خدمة لتعديل اسمها:\n"
        "└──────────────────────"
    )

    buttons = []
    for svc in services:
        status = "🟢" if svc.is_active else "🔴"
        buttons.append([InlineKeyboardButton(
            text=f"{status} {svc.name[:40]}",
            callback_data=f"adm:store:svcren:{svc.id}",
        )])

    nav = []
    safe_cat = _scat_key(cat)
    if page > 0:
        nav.append(InlineKeyboardButton(text="◀️", callback_data=f"adm:store:svclist:{plat}:{safe_cat}:{page-1}"))
    nav.append(InlineKeyboardButton(text=f"{page+1}/{total_pages}", callback_data="noop"))
    if page < total_pages - 1:
        nav.append(InlineKeyboardButton(text="▶️", callback_data=f"adm:store:svclist:{plat}:{safe_cat}:{page+1}"))
    if nav:
        buttons.append(nav)

    buttons.append([
        InlineKeyboardButton(text="◀️ رجوع", callback_data=f"adm:store:svcplat:{plat}"),
        InlineKeyboardButton(text="🏠 الرئيسية", callback_data="adm:panel"),
    ])
    await _safe_edit(cb, text, InlineKeyboardMarkup(inline_keyboard=buttons))
    await cb.answer()


class RenameServiceStates(StatesGroup):
    waiting_name = State()

@router.callback_query(F.data.startswith("adm:store:svcren:"))
async def rename_service_start(cb: CallbackQuery, state: FSMContext, db):
    if not _is_admin(cb.from_user.id):
        return
    sid = int(cb.data.split(":")[3])
    svc = await get_service(db, sid)
    if not svc:
        await cb.answer("الخدمة غير موجودة")
        return

    await state.set_state(RenameServiceStates.waiting_name)
    await state.update_data(rename_svc_id=sid, rename_svc_plat=svc.platform, rename_svc_cat=svc.category)

    await cb.message.edit_text(
        f"┌──── ✏️ تعديل اسم الخدمة ────\n"
        "│\n"
        f"│  الاسم الحالي:\n"
        f"│  <b>{svc.name}</b>\n"
        "│\n"
        "│  أرسل الاسم الجديد:\n"
        "│  /cancel للإلغاء\n"
        "└──────────────────────",
        parse_mode="HTML",
    )
    await cb.answer()


@router.message(RenameServiceStates.waiting_name)
async def rename_service_apply(msg: Message, state: FSMContext, db):
    if not _is_admin(msg.from_user.id):
        return
    if msg.text and msg.text.strip() == "/cancel":
        await state.clear()
        await msg.answer("❌ تم الإلغاء", reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="◀️ لوحة الإدارة", callback_data="adm:panel")],
        ]))
        return
    data = await state.get_data()
    await state.clear()
    sid = data["rename_svc_id"]
    plat = data["rename_svc_plat"]
    cat = data["rename_svc_cat"]
    new_name = (msg.text or "").strip()[:100]

    svc = await get_service(db, sid)
    if svc:
        svc.name = new_name
        await db.commit()

    await msg.answer(
        f"┌──── ✅ تم التحديث ────\n│  الاسم الجديد: <b>{new_name}</b>\n└──────────────────────",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="📦 الخدمات", callback_data=f"adm:store:svclist:{plat}:{_scat_key(cat)}:0")],
            [InlineKeyboardButton(text="◀️ لوحة الإدارة", callback_data="adm:panel")],
        ]), parse_mode="HTML")
