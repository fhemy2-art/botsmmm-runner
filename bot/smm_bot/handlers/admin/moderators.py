"""
Admin: Moderator management — add, remove, list moderators with permission control.
Only the main admin (from ADMIN_IDS) can manage moderators.
Moderators have customizable permissions set during addition.
"""
import logging

from aiogram import Router, F
from aiogram.types import CallbackQuery, Message, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from sqlalchemy import select

from models.moderator import Moderator
from config import ADMIN_IDS
from ui import card

logger = logging.getLogger(__name__)
router = Router()

# Permission definitions: (field_name, arabic_label, emoji)
PERMISSIONS = [
    ("can_services",  "إدارة الخدمات",      "📦"),
    ("can_users",     "إدارة المستخدمين",    "👥"),
    ("can_balance",   "شحن/خصم الرصيد",     "💳"),
    ("can_broadcast", "الإشعارات الجماعية",  "📢"),
    ("can_orders",    "إدارة الطلبات",       "📋"),
    ("can_providers", "إدارة المزودين",      "🔌"),
    ("can_stats",     "الإحصائيات",          "📊"),
    ("can_games",     "إدارة الألعاب",       "🎮"),
]


class AddModeratorStates(StatesGroup):
    waiting_user_id = State()
    selecting_permissions = State()


class RemoveModeratorStates(StatesGroup):
    waiting_user_id = State()


def is_main_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS


async def _safe_edit(callback: CallbackQuery, text: str, kb: InlineKeyboardMarkup) -> None:
    try:
        await callback.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
    except Exception as exc:
        if "message is not modified" not in str(exc).lower():
            try:
                await callback.message.answer(text, reply_markup=kb, parse_mode="HTML")
            except Exception:
                pass


async def get_all_moderators(db) -> list[Moderator]:
    result = await db.execute(select(Moderator).where(Moderator.is_active == True))
    return list(result.scalars().all())


async def get_moderator_ids(db) -> list[int]:
    mods = await get_all_moderators(db)
    return [m.user_id for m in mods]


def _refresh_moderator_cache(mod_ids: list[int]) -> None:
    try:
        from handlers.admin.services import set_moderator_ids
        set_moderator_ids(mod_ids)
    except Exception:
        pass


def _build_permissions_kb(perms: dict[str, bool]) -> InlineKeyboardMarkup:
    """Build inline keyboard for permission toggling."""
    buttons = []
    for field, label, emoji in PERMISSIONS:
        enabled = perms.get(field, False)
        status = "✅" if enabled else "❌"
        buttons.append([InlineKeyboardButton(
            text=f"{status} {emoji} {label}",
            callback_data=f"modperm:{field}",
        )])

    buttons.append([
        InlineKeyboardButton(text="🔓 تفعيل الكل", callback_data="modperm:all_on"),
        InlineKeyboardButton(text="🔒 تعطيل الكل", callback_data="modperm:all_off"),
    ])
    buttons.append([InlineKeyboardButton(
        text="✅ تأكيد وحفظ المشرف",
        callback_data="modperm:confirm",
    )])
    buttons.append([InlineKeyboardButton(text="❌ إلغاء", callback_data="adm:moderators")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def _get_mod_perms_display(mod: Moderator) -> list[str]:
    """Get list of permissions for display."""
    lines = []
    for field, label, emoji in PERMISSIONS:
        enabled = getattr(mod, field, False)
        status = "✅" if enabled else "❌"
        lines.append(f"  {status} {emoji} {label}")
    return lines


# ════════════════════════════════════════════════════════════════
#  MODERATORS PANEL
# ════════════════════════════════════════════════════════════════

@router.callback_query(F.data == "adm:moderators")
async def show_moderators_panel(callback: CallbackQuery, db, state: FSMContext):
    if not is_main_admin(callback.from_user.id):
        await callback.answer("❌ هذه الميزة للأدمن الرئيسي فقط", show_alert=True)
        return

    await state.clear()
    mods = await get_all_moderators(db)
    mod_count = len(mods)

    rows = [
        f"إجمالي المشرفين: <b>{mod_count}</b>",
        "---",
    ]
    if mods:
        for m in mods:
            name = m.first_name or "مجهول"
            username_str = f" @{m.username}" if m.username else ""
            perm_count = sum(1 for f, _, _ in PERMISSIONS if getattr(m, f, False))
            rows.append(f"👤 <b>{name}</b>{username_str}")
            rows.append(f"   🆔 <code>{m.user_id}</code> — {perm_count}/{len(PERMISSIONS)} صلاحية")
    else:
        rows.append("لا يوجد مشرفون حالياً")

    text = card("👮 إدارة المشرفين", rows)

    kb_buttons = []
    for m in mods:
        name = m.first_name or str(m.user_id)
        kb_buttons.append([InlineKeyboardButton(
            text=f"⚙️ صلاحيات {name}",
            callback_data=f"adm:editmod:{m.user_id}",
        )])

    kb_buttons.extend([
        [
            InlineKeyboardButton(text="➕ إضافة مشرف", callback_data="adm:addmod"),
            InlineKeyboardButton(text="➖ إزالة مشرف", callback_data="adm:removemod"),
        ],
        [
            InlineKeyboardButton(text="◀️ رجوع", callback_data="adm:back"),
            InlineKeyboardButton(text="🏠 الرئيسية", callback_data="adm:panel"),
        ],
    ])
    await _safe_edit(callback, text, InlineKeyboardMarkup(inline_keyboard=kb_buttons))
    await callback.answer()


# ════════════════════════════════════════════════════════════════
#  EDIT MODERATOR PERMISSIONS
# ════════════════════════════════════════════════════════════════

@router.callback_query(F.data.startswith("adm:editmod:"))
async def edit_moderator_perms(callback: CallbackQuery, db, state: FSMContext):
    if not is_main_admin(callback.from_user.id):
        await callback.answer("❌", show_alert=True)
        return

    mod_id = int(callback.data.split(":")[2])
    result = await db.execute(
        select(Moderator).where(Moderator.user_id == mod_id, Moderator.is_active == True)
    )
    mod = result.scalar_one_or_none()
    if not mod:
        await callback.answer("❌ المشرف غير موجود", show_alert=True)
        return

    perms = {f: bool(getattr(mod, f, False)) for f, _, _ in PERMISSIONS}
    await state.set_state(AddModeratorStates.selecting_permissions)
    await state.update_data(
        mod_user_id=mod_id,
        mod_username=mod.username,
        mod_first_name=mod.first_name,
        perms=perms,
        editing_existing=True,
        ui_chat_id=callback.message.chat.id,
        ui_message_id=callback.message.message_id,
    )

    name = mod.first_name or str(mod_id)
    perm_lines = _get_mod_perms_display(mod)
    text = card(f"⚙️ صلاحيات {name}", [
        f"🆔 المعرف: <code>{mod_id}</code>",
        "---",
        "اضغط على الصلاحية لتفعيلها/تعطيلها:",
        None,
        *perm_lines,
    ])

    await _safe_edit(callback, text, _build_permissions_kb(perms))
    await callback.answer()


# ════════════════════════════════════════════════════════════════
#  ADD MODERATOR
# ════════════════════════════════════════════════════════════════

@router.callback_query(F.data == "adm:addmod")
async def start_add_moderator(callback: CallbackQuery, state: FSMContext):
    if not is_main_admin(callback.from_user.id):
        await callback.answer("❌ هذه الميزة للأدمن الرئيسي فقط", show_alert=True)
        return

    await state.set_state(AddModeratorStates.waiting_user_id)
    await state.update_data(
        ui_chat_id=callback.message.chat.id,
        ui_message_id=callback.message.message_id,
    )

    text = card("➕ إضافة مشرف", [
        "أرسل <b>ID المستخدم</b> الذي تريد تعيينه كمشرف:",
        None,
        "💡 للحصول على ID المستخدم:",
        "  اطلب منه إرسال /start في البوت",
        "  ثم ابحث عنه في قسم المستخدمين",
        None,
        "/cancel للإلغاء",
    ])
    await _safe_edit(callback, text, InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="❌ إلغاء", callback_data="adm:moderators")],
    ]))
    await callback.answer()


@router.message(AddModeratorStates.waiting_user_id)
async def process_add_moderator_id(message: Message, state: FSMContext, db):
    if not is_main_admin(message.from_user.id):
        return

    if message.text and message.text.strip() == "/cancel":
        await state.clear()
        await message.answer("❌ تم الإلغاء")
        return

    if not (message.text or "").strip().isdigit():
        await message.answer("❌ أرسل رقم ID صحيح (أرقام فقط)")
        return

    data = await state.get_data()
    new_mod_id = int(message.text.strip())

    if new_mod_id in ADMIN_IDS:
        await state.clear()
        try:
            await message.bot.edit_message_text(
                chat_id=data["ui_chat_id"],
                message_id=data["ui_message_id"],
                text=card("⚠️ تنبيه", ["هذا المستخدم هو الأدمن الرئيسي بالفعل!"]),
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="◀️ رجوع", callback_data="adm:moderators")]
                ]),
                parse_mode="HTML",
            )
        except Exception:
            pass
        return

    existing = await db.execute(select(Moderator).where(Moderator.user_id == new_mod_id))
    existing_mod = existing.scalar_one_or_none()

    if existing_mod and existing_mod.is_active:
        await state.clear()
        try:
            await message.bot.edit_message_text(
                chat_id=data["ui_chat_id"],
                message_id=data["ui_message_id"],
                text=card("⚠️ موجود مسبقاً", [
                    f"المستخدم <code>{new_mod_id}</code> مشرف بالفعل!",
                    "يمكنك تعديل صلاحياته من قائمة المشرفين",
                ]),
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="◀️ رجوع", callback_data="adm:moderators")]
                ]),
                parse_mode="HTML",
            )
        except Exception:
            pass
        return

    try:
        await message.delete()
    except Exception:
        pass

    # Get user info
    try:
        mod_info = await message.bot.get_chat(new_mod_id)
        mod_username = mod_info.username
        mod_first_name = mod_info.first_name
    except Exception:
        mod_username = None
        mod_first_name = f"مستخدم {new_mod_id}"

    # Go to permission selection screen
    perms = {f: False for f, _, _ in PERMISSIONS}
    await state.set_state(AddModeratorStates.selecting_permissions)
    await state.update_data(
        mod_user_id=new_mod_id,
        mod_username=mod_username,
        mod_first_name=mod_first_name,
        perms=perms,
        editing_existing=bool(existing_mod),
    )

    name = mod_first_name or str(new_mod_id)
    text = card("🔐 تحديد صلاحيات المشرف", [
        f"👤 الاسم: <b>{name}</b>",
        f"🆔 المعرف: <code>{new_mod_id}</code>",
        "---",
        "حدد الصلاحيات التي تريد منحها لهذا المشرف:",
        "اضغط على كل صلاحية لتفعيلها/تعطيلها",
        None,
        "ثم اضغط ✅ تأكيد وحفظ المشرف",
    ])

    try:
        await message.bot.edit_message_text(
            chat_id=data["ui_chat_id"],
            message_id=data["ui_message_id"],
            text=text,
            reply_markup=_build_permissions_kb(perms),
            parse_mode="HTML",
        )
    except Exception:
        pass


# ════════════════════════════════════════════════════════════════
#  PERMISSION TOGGLE
# ════════════════════════════════════════════════════════════════

@router.callback_query(F.data.startswith("modperm:"), AddModeratorStates.selecting_permissions)
async def toggle_permission(callback: CallbackQuery, state: FSMContext, db):
    if not is_main_admin(callback.from_user.id):
        await callback.answer("❌", show_alert=True)
        return

    action = callback.data.split(":")[1]
    data = await state.get_data()
    perms = data.get("perms", {})
    mod_id = data.get("mod_user_id", 0)
    mod_name = data.get("mod_first_name", str(mod_id))
    editing_existing = data.get("editing_existing", False)

    if action == "confirm":
        # Save the moderator with permissions
        result = await db.execute(select(Moderator).where(Moderator.user_id == mod_id))
        existing_mod = result.scalar_one_or_none()

        if existing_mod:
            existing_mod.is_active = True
            existing_mod.username = data.get("mod_username")
            existing_mod.first_name = data.get("mod_first_name")
            existing_mod.added_by = callback.from_user.id
            for f, _, _ in PERMISSIONS:
                setattr(existing_mod, f, perms.get(f, False))
        else:
            new_mod = Moderator(
                user_id=mod_id,
                username=data.get("mod_username"),
                first_name=data.get("mod_first_name"),
                added_by=callback.from_user.id,
                is_active=True,
            )
            for f, _, _ in PERMISSIONS:
                setattr(new_mod, f, perms.get(f, False))
            db.add(new_mod)

        await db.commit()
        await state.clear()

        all_mods = await get_moderator_ids(db)
        _refresh_moderator_cache(all_mods)

        perm_count = sum(1 for v in perms.values() if v)
        enabled_perms = []
        for f, label, emoji in PERMISSIONS:
            if perms.get(f, False):
                enabled_perms.append(f"  ✅ {emoji} {label}")

        if not enabled_perms:
            enabled_perms = ["  ❌ لا توجد صلاحيات"]

        action_text = "تم تحديث صلاحيات" if editing_existing else "تم إضافة"

        text = card(f"✅ {action_text} المشرف", [
            f"👤 الاسم: <b>{mod_name}</b>",
            f"🆔 المعرف: <code>{mod_id}</code>",
            f"🔐 الصلاحيات: <b>{perm_count}/{len(PERMISSIONS)}</b>",
            "---",
            *enabled_perms,
        ])

        await _safe_edit(callback, text, InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="◀️ قائمة المشرفين", callback_data="adm:moderators")],
            [InlineKeyboardButton(text="🏠 الرئيسية", callback_data="adm:panel")],
        ]))

        if not editing_existing:
            try:
                await callback.bot.send_message(
                    mod_id,
                    card("🎉 تهانينا", [
                        "تم تعيينك مشرفاً في البوت!",
                        "يمكنك الآن الوصول للوحة الإدارة.",
                        "أرسل /start للبدء.",
                    ]),
                    parse_mode="HTML",
                )
            except Exception:
                pass

        logger.info("Moderator saved: mod_id=%s perms=%s by admin=%s", mod_id, perm_count, callback.from_user.id)
        await callback.answer("✅ تم الحفظ بنجاح", show_alert=True)
        return

    elif action == "all_on":
        for f, _, _ in PERMISSIONS:
            perms[f] = True
        await callback.answer("🔓 تم تفعيل جميع الصلاحيات")

    elif action == "all_off":
        for f, _, _ in PERMISSIONS:
            perms[f] = False
        await callback.answer("🔒 تم تعطيل جميع الصلاحيات")

    else:
        # Toggle individual permission
        if action in perms:
            perms[action] = not perms[action]
            for f, label, emoji in PERMISSIONS:
                if f == action:
                    status = "✅ مفعّلة" if perms[action] else "❌ معطّلة"
                    await callback.answer(f"{emoji} {label}: {status}")
                    break
        else:
            await callback.answer("❌")
            return

    await state.update_data(perms=perms)

    # Rebuild display
    perm_lines = []
    for f, label, emoji in PERMISSIONS:
        status = "✅" if perms.get(f, False) else "❌"
        perm_lines.append(f"  {status} {emoji} {label}")

    text = card("🔐 تحديد صلاحيات المشرف", [
        f"👤 الاسم: <b>{mod_name}</b>",
        f"🆔 المعرف: <code>{mod_id}</code>",
        "---",
        *perm_lines,
    ])

    await _safe_edit(callback, text, _build_permissions_kb(perms))


# ════════════════════════════════════════════════════════════════
#  REMOVE MODERATOR
# ════════════════════════════════════════════════════════════════

@router.callback_query(F.data == "adm:removemod")
async def start_remove_moderator(callback: CallbackQuery, state: FSMContext, db):
    if not is_main_admin(callback.from_user.id):
        await callback.answer("❌ هذه الميزة للأدمن الرئيسي فقط", show_alert=True)
        return

    mods = await get_all_moderators(db)
    if not mods:
        await callback.answer("لا يوجد مشرفون لإزالتهم", show_alert=True)
        return

    await state.set_state(RemoveModeratorStates.waiting_user_id)
    await state.update_data(
        ui_chat_id=callback.message.chat.id,
        ui_message_id=callback.message.message_id
    )

    buttons = []
    for mod in mods:
        name = mod.first_name or str(mod.user_id)
        username_str = f" @{mod.username}" if mod.username else ""
        buttons.append([InlineKeyboardButton(
            text=f"❌ {name}{username_str} ({mod.user_id})",
            callback_data=f"adm:removemod:{mod.user_id}",
        )])
    buttons.append([InlineKeyboardButton(text="◀️ رجوع", callback_data="adm:moderators")])

    text = card("➖ إزالة مشرف", ["اختر المشرف الذي تريد إزالته:"])
    await _safe_edit(callback, text, InlineKeyboardMarkup(inline_keyboard=buttons))
    await callback.answer()


@router.callback_query(F.data.startswith("adm:removemod:"))
async def confirm_remove_moderator(callback: CallbackQuery, state: FSMContext, db):
    if not is_main_admin(callback.from_user.id):
        await callback.answer("❌ هذه الميزة للأدمن الرئيسي فقط", show_alert=True)
        return

    await state.clear()
    parts = callback.data.split(":")
    mod_id = int(parts[2])

    result = await db.execute(
        select(Moderator).where(Moderator.user_id == mod_id, Moderator.is_active == True)
    )
    mod = result.scalar_one_or_none()

    if not mod:
        await callback.answer("المشرف غير موجود", show_alert=True)
        return

    mod.is_active = False
    await db.commit()

    all_mods = await get_moderator_ids(db)
    _refresh_moderator_cache(all_mods)

    name_display = mod.first_name or str(mod_id)

    text = card("✅ تمت الإزالة", [
        f"👤 الاسم: <b>{name_display}</b>",
        f"🆔 المعرف: <code>{mod_id}</code>",
        "✅ تم إلغاء صلاحيات المشرف!",
    ])

    await _safe_edit(callback, text, InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="◀️ قائمة المشرفين", callback_data="adm:moderators")],
        [InlineKeyboardButton(text="🏠 الرئيسية", callback_data="adm:panel")],
    ]))
    await callback.answer()

    try:
        await callback.bot.send_message(
            mod_id,
            card("ℹ️ إشعار", ["تم إلغاء صلاحيات المشرف الخاصة بك."]),
            parse_mode="HTML",
        )
    except Exception:
        pass

    logger.info("Admin removed moderator: mod_id=%s by admin=%s", mod_id, callback.from_user.id)
