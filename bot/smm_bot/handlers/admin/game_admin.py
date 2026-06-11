import logging
import json
from aiogram import Router, F
from aiogram.types import CallbackQuery, Message, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from sqlalchemy import select, func, update
from sqlalchemy.ext.asyncio import AsyncSession

from models.game import Game, GameProduct, GameOrder
from models.provider import Provider
from services.game_services import game_api_get_products, _is_fazercards, get_validation_code
from services import fazercards_provider
from handlers.admin.services import is_admin_or_mod, _kb, _safe_edit
from config import FAZERCARDS_API_KEY
from ui import section_card, fmt_price
from services import settings_manager

logger = logging.getLogger(__name__)
router = Router()

FAZERCARDS_API_URL = "https://api.fazercards.com/api/v1"

# ── Arabic translation map for common game terms ──
_GAME_NAME_AR = {
    "free fire": "فري فاير",
    "pubg mobile": "ببجي موبايل",
    "pubg": "ببجي",
    "mobile legends": "موبايل ليجندز",
    "genshin impact": "جينشن إمباكت",
    "roblox": "روبلوكس",
    "fortnite": "فورتنايت",
    "call of duty": "كول أوف ديوتي",
    "clash of clans": "كلاش أوف كلانس",
    "clash royale": "كلاش رويال",
    "brawl stars": "براول ستارز",
    "valorant": "فالورانت",
    "league of legends": "ليغ أوف ليجندز",
    "minecraft": "ماين كرافت",
    "steam": "ستيم",
    "itunes": "آيتونز",
    "google play": "جوجل بلاي",
    "playstation": "بلاي ستيشن",
    "xbox": "إكس بوكس",
    "nintendo": "نينتندو",
    "telegram": "تيليجرام",
    "spotify": "سبوتيفاي",
    "netflix": "نتفلكس",
    "arena breakout": "أرينا بريك أوت",
    "honkai star rail": "هونكاي ستار ريل",
    "efootball": "إي فوتبول",
    "fifa": "فيفا",
    "ea fc": "إي أيه إف سي",
    "blood strike": "بلود سترايك",
    "honor of kings": "هونر أوف كينغز",
    "tower of fantasy": "تاور أوف فانتازي",
    "ragnarok": "راغناروك",
    "identity v": "آيدنتتي في",
    "lifeafter": "لايف أفتر",
    "stumble guys": "ستمبل غايز",
    "8 ball pool": "8 بول بول",
    "undawn": "أندون",
    "ace racer": "إيس ريسر",
    "dragon ball": "دراغون بول",
    "one punch man": "ون بنش مان",
    "naruto": "ناروتو",
    "super sus": "سوبر ساس",
    "standoff 2": "ستاند أوف 2",
    "among us": "أمونج أس",
}

_PRODUCT_TERMS_AR = {
    "diamonds": "ماسة",
    "diamond": "ماسة",
    "uc": "شدات",
    "unknown cash": "شدات",
    "weekly membership": "عضوية أسبوعية",
    "monthly membership": "عضوية شهرية",
    "weekly diamond pass": "بطاقة الماس الأسبوعية",
    "starlight membership": "عضوية ستارلايت",
    "twilight pass": "بطاقة الشفق",
    "v-bucks": "في-باكس",
    "robux": "روبوكس",
    "primogems": "بريموجيمز",
    "coins": "عملات",
    "gems": "جواهر",
    "tokens": "توكنز",
    "gift card": "بطاقة هدية",
    "top-up": "شحن",
    "topup": "شحن",
    "stars": "نجوم",
    "premium": "بريميوم",
    "pass": "بطاقة",
    "bundle": "حزمة",
    "pack": "حزمة",
    "special": "خاص",
    "bonus": "مكافأة",
    "first purchase": "أول شراء",
    "direct topup": "شحن مباشر",
    "auto": "تلقائي",
    "manual": "يدوي",
}


def _translate_game_name(name: str) -> str:
    """Attempt Arabic translation for a game name."""
    lower = name.lower().strip()
    # Direct match
    for en, ar in _GAME_NAME_AR.items():
        if en in lower:
            return ar
    return ""


def _translate_product_name(name: str) -> str:
    """Build Arabic product name: keep numbers + translate terms."""
    import re
    lower = name.lower().strip()

    # Extract numbers and quantity patterns (e.g. "100 + 10", "60", "1000")
    numbers = re.findall(r'[\d,]+(?:\s*\+\s*[\d,]+)*', name)
    num_part = " + ".join(numbers) if numbers else ""

    # Find matching Arabic terms (longest first to avoid partial matches)
    sorted_terms = sorted(_PRODUCT_TERMS_AR.items(), key=lambda x: -len(x[0]))
    matched_ar = []
    used = set()
    consumed = set()  # Track consumed English text to avoid overlaps
    for en, ar in sorted_terms:
        if en in lower and ar not in used:
            # Check this term isn't part of an already matched longer term
            overlap = False
            for prev_en in consumed:
                if en in prev_en:
                    overlap = True
                    break
            if overlap:
                continue
            # For short terms like 'uc', require word boundary
            if len(en) <= 2:
                if not re.search(r'\b' + re.escape(en) + r'\b', lower):
                    continue
            matched_ar.append(ar)
            used.add(ar)
            consumed.add(en)
            if len(matched_ar) >= 2:
                break

    if matched_ar:
        ar_terms = " ".join(matched_ar)
        if num_part:
            return f"{num_part} {ar_terms}"
        return ar_terms
    return ""


# ── States ─────────────────────────────────────────────────
class GameAdminStates(StatesGroup):
    waiting_game_name = State()
    # Add game provider
    gp_waiting_name = State()
    gp_waiting_url = State()
    gp_waiting_key = State()
    # Sync / markup
    waiting_markup = State()
    waiting_global_markup = State()
    # Edit Arabic name
    waiting_name_ar = State()
    waiting_product_name_ar = State()


# ── Helpers ────────────────────────────────────────────────
async def _count_game_products(db: AsyncSession, provider_id: int) -> int:
    stmt = select(func.count()).where(GameProduct.provider_id == provider_id)
    return (await db.execute(stmt)).scalar() or 0


async def _get_game_providers(db: AsyncSession, active_only: bool = False):
    stmt = select(Provider).where(Provider.provider_type == "game")
    if active_only:
        stmt = stmt.where(Provider.status == True)
    result = await db.execute(stmt)
    return result.scalars().all()


async def _get_or_create_fc_provider(db: AsyncSession) -> Provider:
    stmt = select(Provider).where(Provider.api_url.ilike("%fazercards%"))
    result = await db.execute(stmt)
    provider = result.scalars().first()
    if not provider:
        provider = Provider(
            name="FazerCards", api_url=FAZERCARDS_API_URL,
            api_key=FAZERCARDS_API_KEY or "env", status=True, provider_type="game",
        )
        db.add(provider)
        await db.flush()
    elif provider.provider_type != "game":
        provider.provider_type = "game"
        await db.flush()
    return provider


# ═══════════════════════════════════════════════════════════
#  MAIN GAME ADMIN PANEL
# ═══════════════════════════════════════════════════════════

@router.callback_query(F.data == "adm:games")
async def game_management_panel(callback: CallbackQuery, db: AsyncSession):
    if not is_admin_or_mod(callback.from_user.id): return

    # Stats
    game_count = (await db.execute(select(func.count()).select_from(Game))).scalar() or 0
    prod_count = (await db.execute(select(func.count()).select_from(GameProduct))).scalar() or 0
    active_count = (await db.execute(
        select(func.count()).where(GameProduct.active == True)
    )).scalar() or 0
    prov_count = len(await _get_game_providers(db))
    pending = (await db.execute(
        select(func.count()).where(GameOrder.status.in_(["pending", "processing"]))
    )).scalar() or 0

    text = (
        "┌──── 🎮 قسم الألعاب ────\n"
        "│\n"
        f"│  🎮 الألعاب: <b>{game_count}</b>\n"
        f"│  📦 الباقات: <b>{prod_count:,}</b> (مفعّل: {active_count:,})\n"
        f"│  🔌 المزودون: <b>{prov_count}</b>\n"
        f"│  ⏳ طلبات معلقة: <b>{pending}</b>\n"
        "│\n"
        "└──────────────────────"
    )

    kb = InlineKeyboardMarkup(inline_keyboard=[
        # Providers
        [InlineKeyboardButton(text="──── 🔌 المزودون ────", callback_data="noop")],
        [
            InlineKeyboardButton(text="🔌 قائمة المزودين", callback_data="adm:gp_list"),
            InlineKeyboardButton(text="➕ إضافة مزود", callback_data="adm:gp_add"),
        ],
        [InlineKeyboardButton(text="🔄 مزامنة جميع المزودين", callback_data="adm:gp_syncall")],
        # Products
        [InlineKeyboardButton(text="──── 📦 المنتجات ────", callback_data="noop")],
        [
            InlineKeyboardButton(text="🕹️ إدارة الألعاب", callback_data="adm:games_list"),
            InlineKeyboardButton(text="📦 كل الباقات", callback_data="adm:game_prods_list"),
        ],
        [
            InlineKeyboardButton(text="✅ المنتجات المفعّلة", callback_data="adm:active_prods"),
            InlineKeyboardButton(text="➕ إضافة من مزود", callback_data="adm:gfp_select"),
        ],
        # Pricing
        [InlineKeyboardButton(text="──── 💰 التسعير ────", callback_data="noop")],
        [InlineKeyboardButton(text="📈 نسبة ربح الألعاب", callback_data="adm:game_markup_set")],
        # Orders
        [InlineKeyboardButton(text="──── 📋 الطلبات ────", callback_data="noop")],
        [InlineKeyboardButton(text="📋 طلبات الألعاب", callback_data="adm:game_orders")],
        # FazerCards
        [InlineKeyboardButton(text="──── 🃏 FazerCards ────", callback_data="noop")],
        [
            InlineKeyboardButton(text="🃏 مزامنة FazerCards", callback_data="adm:fc_sync"),
            InlineKeyboardButton(text="💰 رصيد FazerCards", callback_data="adm:fc_balance"),
        ],
        # Back
        [
            InlineKeyboardButton(text="◀️ رجوع", callback_data="adm:panel"),
            InlineKeyboardButton(text="🏠 الرئيسية", callback_data="main_menu"),
        ],
    ])
    await _safe_edit(callback, text, kb)
    await callback.answer()


# ═══════════════════════════════════════════════════════════
#  GAME PROVIDER CRUD
# ═══════════════════════════════════════════════════════════

@router.callback_query(F.data == "adm:gp_list")
async def game_provider_list(callback: CallbackQuery, db: AsyncSession):
    if not is_admin_or_mod(callback.from_user.id): return

    providers = await _get_game_providers(db)
    if not providers:
        text = "┌──── 🔌 مزودو الألعاب ────\n│  لا يوجد مزودون.\n│  استخدم ➕ إضافة مزود.\n└──────────────────────"
        await _safe_edit(callback, text, _kb(
            [InlineKeyboardButton(text="➕ إضافة مزود", callback_data="adm:gp_add")],
            back="adm:games"
        ))
        await callback.answer()
        return

    text = (
        "┌──── 🔌 مزودو الألعاب ────\n"
        f"│  العدد: <b>{len(providers)}</b>\n"
        "│  اختر مزوداً لإدارته:\n"
        "└──────────────────────"
    )
    buttons = []
    for p in providers:
        count = await _count_game_products(db, p.id)
        icon = "🟢" if p.status else "🔴"
        buttons.append([InlineKeyboardButton(
            text=f"{icon} {p.name}  ({count:,} باقة)",
            callback_data=f"adm:gp_det:{p.id}",
        )])
    buttons.append([
        InlineKeyboardButton(text="➕ إضافة مزود", callback_data="adm:gp_add"),
        InlineKeyboardButton(text="◀️ رجوع", callback_data="adm:games"),
    ])
    await _safe_edit(callback, text, InlineKeyboardMarkup(inline_keyboard=buttons))
    await callback.answer()


@router.callback_query(F.data.startswith("adm:gp_det:"))
async def game_provider_detail(callback: CallbackQuery, db: AsyncSession):
    if not is_admin_or_mod(callback.from_user.id): return
    pid = int(callback.data.split(":")[2])
    p = await db.get(Provider, pid)
    if not p:
        await callback.answer("المزود غير موجود")
        return

    count = await _count_game_products(db, pid)
    status_icon = "🟢 نشط" if p.status else "🔴 معطّل"
    toggle_text = "🔴 تعطيل" if p.status else "🟢 تفعيل"

    text = (
        f"┌──── 🔌 {p.name} ────\n"
        f"│  🆔 #{p.id}\n"
        f"│  🔗 {p.api_url}\n"
        f"│  📦 الباقات: <b>{count:,}</b>\n"
        f"│  📊 الحالة: {status_icon}\n"
        "└──────────────────────"
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text=toggle_text, callback_data=f"adm:gp_tgl:{pid}"),
            InlineKeyboardButton(text="🔄 مزامنة", callback_data=f"adm:gp_syn:{pid}"),
        ],
        [InlineKeyboardButton(text="📦 تصفح المنتجات", callback_data=f"adm:gfp:{pid}")],
        [
            InlineKeyboardButton(text="🗑 حذف المزود", callback_data=f"adm:gp_del:{pid}"),
            InlineKeyboardButton(text="◀️ رجوع", callback_data="adm:gp_list"),
        ],
    ])
    await _safe_edit(callback, text, kb)
    await callback.answer()


@router.callback_query(F.data.startswith("adm:gp_tgl:"))
async def game_provider_toggle(callback: CallbackQuery, db: AsyncSession):
    if not is_admin_or_mod(callback.from_user.id): return
    pid = int(callback.data.split(":")[2])
    p = await db.get(Provider, pid)
    if p:
        p.status = not p.status
        await db.commit()
    await game_provider_detail(callback, db)


@router.callback_query(F.data.startswith("adm:gp_del:"))
async def game_provider_delete(callback: CallbackQuery, db: AsyncSession):
    if not is_admin_or_mod(callback.from_user.id): return
    pid = int(callback.data.split(":")[2])
    p = await db.get(Provider, pid)
    if p:
        await db.execute(
            GameProduct.__table__.delete().where(GameProduct.provider_id == pid)
        )
        await db.delete(p)
        await db.commit()
        await callback.answer(f"✅ تم حذف {p.name} وجميع باقاته", show_alert=True)
    await game_provider_list(callback, db)


# ── Add Game Provider (3 steps) ────────────────────────────

@router.callback_query(F.data == "adm:gp_add")
async def add_game_provider_start(callback: CallbackQuery, state: FSMContext):
    if not is_admin_or_mod(callback.from_user.id): return
    await state.set_state(GameAdminStates.gp_waiting_name)
    await state.update_data(ui_chat_id=callback.message.chat.id, ui_msg_id=callback.message.message_id)
    await callback.message.edit_text(
        "┌──── ➕ إضافة مزود ألعاب ────\n│  الخطوة 1/3\n│  أرسل اسم المزود:\n│  /cancel للإلغاء\n└──────────────────────"
    )
    await callback.answer()


@router.message(GameAdminStates.gp_waiting_name)
async def add_game_provider_name(message: Message, state: FSMContext):
    if not is_admin_or_mod(message.from_user.id): return
    if message.text and message.text.strip() == "/cancel":
        await state.clear(); return
    await state.update_data(name=(message.text or "").strip())
    await state.set_state(GameAdminStates.gp_waiting_url)
    data = await state.get_data()
    try:
        await message.bot.edit_message_text(
            chat_id=data["ui_chat_id"], message_id=data["ui_msg_id"],
            text="┌──── ➕ إضافة مزود ألعاب ────\n│  الخطوة 2/3\n│  أرسل رابط API:\n│  مثال: https://api.example.com/v1\n│  /cancel للإلغاء\n└──────────────────────"
        )
    except Exception: pass
    try: await message.delete()
    except Exception: pass


@router.message(GameAdminStates.gp_waiting_url)
async def add_game_provider_url(message: Message, state: FSMContext):
    if not is_admin_or_mod(message.from_user.id): return
    if message.text and message.text.strip() == "/cancel":
        await state.clear(); return
    url = (message.text or "").strip()
    if not url.startswith("http"):
        await message.answer("❌ رابط غير صحيح. يبدأ بـ http")
        return
    await state.update_data(api_url=url)
    await state.set_state(GameAdminStates.gp_waiting_key)
    data = await state.get_data()
    try:
        await message.bot.edit_message_text(
            chat_id=data["ui_chat_id"], message_id=data["ui_msg_id"],
            text="┌──── ➕ إضافة مزود ألعاب ────\n│  الخطوة 3/3\n│  أرسل مفتاح API:\n│  ⚠️ سيُحذف الرسالة فوراً\n│  /cancel للإلغاء\n└──────────────────────"
        )
    except Exception: pass
    try: await message.delete()
    except Exception: pass


@router.message(GameAdminStates.gp_waiting_key)
async def add_game_provider_key(message: Message, state: FSMContext, db: AsyncSession):
    if not is_admin_or_mod(message.from_user.id): return
    if message.text and message.text.strip() == "/cancel":
        await state.clear(); return

    data = await state.get_data()
    await state.clear()

    provider = Provider(
        name=data["name"], api_url=data["api_url"],
        api_key=(message.text or "").strip(), status=True,
        provider_type="game",
    )
    db.add(provider)
    await db.commit()

    try: await message.delete()
    except Exception: pass

    text = (
        "┌──── ✅ تمت الإضافة ────\n"
        f"│  الاسم: <b>{data['name']}</b>\n"
        f"│  الرابط: {data['api_url']}\n"
        "│  النوع: مزود ألعاب\n"
        "│\n"
        "│  يمكنك الآن مزامنة المنتجات.\n"
        "└──────────────────────"
    )
    try:
        await message.bot.edit_message_text(
            chat_id=data["ui_chat_id"], message_id=data["ui_msg_id"],
            text=text,
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🔄 مزامنة الآن", callback_data=f"adm:gp_syn:{provider.id}")],
                [InlineKeyboardButton(text="◀️ قسم الألعاب", callback_data="adm:games")],
            ]),
            parse_mode="HTML",
        )
    except Exception:
        await message.answer(text, parse_mode="HTML")
    logger.info("Game provider added: %s (%s)", data["name"], data["api_url"])


# ── Sync Game Provider ─────────────────────────────────────

@router.callback_query(F.data.startswith("adm:gp_syn:"))
async def sync_game_provider(callback: CallbackQuery, db: AsyncSession):
    """Auto-sync using saved markup — stores full product details."""
    if not is_admin_or_mod(callback.from_user.id): return
    pid = int(callback.data.split(":")[2])
    provider = await db.get(Provider, pid)
    if not provider:
        await callback.answer("المزود غير موجود")
        return

    await callback.answer("جاري جلب المنتجات...", show_alert=False)

    products = await game_api_get_products(provider.api_url, provider.api_key)
    if not products:
        await callback.answer("❌ فشل جلب المنتجات", show_alert=True)
        return

    markup_pct = settings_manager.get_game_markup_pct()
    markup = markup_pct / 100

    added, updated = 0, 0
    for p in products:
        game_name = p.get("game_name", "General")
        game_icon = p.get("game_icon", "")
        fc_game_id = p.get("game_id", "")

        stmt = select(Game).where(Game.name == game_name)
        res = await db.execute(stmt)
        game = res.scalars().first()
        if not game:
            auto_ar = _translate_game_name(game_name)
            game = Game(
                name=game_name, status=True,
                name_ar=auto_ar or None,
                icon_url=game_icon or None,
                fc_game_id=fc_game_id or None,
            )
            db.add(game)
            await db.flush()
        else:
            # Update icon and fc_game_id if not set
            if not game.icon_url and game_icon:
                game.icon_url = game_icon
            if not game.fc_game_id and fc_game_id:
                game.fc_game_id = fc_game_id

        api_id = str(p.get("service", p.get("id", "")))
        base_price = float(p.get("rate", 0))
        sell_price = round(base_price * (1 + markup), 4)
        prod_name = p.get("name", "Unknown")

        stmt2 = select(GameProduct).where(
            GameProduct.api_service_id == api_id,
            GameProduct.provider_id == pid,
        )
        res2 = await db.execute(stmt2)
        existing = res2.scalars().first()

        fields_data = p.get("fields")
        fields_json = json.dumps(fields_data) if fields_data else None

        if existing:
            existing.base_price = base_price
            existing.price = sell_price
            existing.name = prod_name
            existing.game_id = game.id
            existing.description = p.get("description") or existing.description
            existing.currency = p.get("currency", "USD")
            existing.fields_json = fields_json or existing.fields_json
            existing.min_quantity = p.get("min_quantity", 1)
            existing.max_quantity = p.get("max_quantity", 1)
            existing.region = p.get("region") or existing.region
            # Auto-translate if not already set
            if not existing.name_ar:
                auto_ar = _translate_product_name(prod_name)
                if auto_ar:
                    existing.name_ar = auto_ar
            updated += 1
        else:
            auto_ar = _translate_product_name(prod_name)
            db.add(GameProduct(
                game_id=game.id, name=prod_name,
                name_ar=auto_ar or None,
                description=p.get("description") or None,
                currency=p.get("currency", "USD"),
                base_price=base_price, price=sell_price,
                api_service_id=api_id, provider_id=pid,
                fields_json=fields_json,
                min_quantity=p.get("min_quantity", 1),
                max_quantity=p.get("max_quantity", 1),
                region=p.get("region") or None,
            ))
            added += 1

    await db.commit()

    text = section_card("✅", f"مزامنة {provider.name}", [
        f"جديد: <b>{added}</b>",
        f"محدّث: <b>{updated}</b>",
        f"ربح: <b>{markup_pct:.0f}%</b>",
        "",
        "⚠️ المنتجات الجديدة معطلة افتراضياً.",
        "فعّلها من إدارة الباقات.",
    ])
    await _safe_edit(callback, text, _kb(
        [InlineKeyboardButton(text="📦 تصفح المنتجات", callback_data=f"adm:gfp:{pid}")],
        back="adm:gp_list",
    ))


@router.callback_query(F.data == "adm:gp_syncall")
async def sync_all_game_providers(callback: CallbackQuery, db: AsyncSession):
    if not is_admin_or_mod(callback.from_user.id): return
    providers = await _get_game_providers(db, active_only=True)
    if not providers:
        await callback.answer("لا يوجد مزودون نشطون", show_alert=True)
        return

    text = section_card("🔄", "مزامنة جميع مزودي الألعاب", ["اختر المزود للمزامنة:"])
    kb = [[InlineKeyboardButton(text=f"🔄 {p.name}", callback_data=f"adm:gp_syn:{p.id}")] for p in providers]
    await _safe_edit(callback, text, _kb(*kb, back="adm:games"))


# ═══════════════════════════════════════════════════════════
#  BROWSE & ADD FROM PROVIDER
# ═══════════════════════════════════════════════════════════

@router.callback_query(F.data == "adm:gfp_select")
async def game_from_provider_select(callback: CallbackQuery, db: AsyncSession):
    if not is_admin_or_mod(callback.from_user.id): return
    providers = await _get_game_providers(db, active_only=True)
    if not providers:
        await callback.answer("لا يوجد مزودون. أضف مزود أولاً.", show_alert=True)
        return

    text = section_card("➕", "إضافة من مزود", ["اختر مزوداً لتصفح منتجاته:"])
    kb = []
    for p in providers:
        count = await _count_game_products(db, p.id)
        kb.append([InlineKeyboardButton(
            text=f"🔌 {p.name} ({count:,} باقة)",
            callback_data=f"adm:gfp:{p.id}",
        )])
    await _safe_edit(callback, text, _kb(*kb, back="adm:games"))


@router.callback_query(F.data.startswith("adm:gfp:"))
async def game_from_provider_browse(callback: CallbackQuery, db: AsyncSession):
    if not is_admin_or_mod(callback.from_user.id): return
    pid = int(callback.data.split(":")[2])
    provider = await db.get(Provider, pid)
    if not provider:
        await callback.answer("المزود غير موجود")
        return

    stmt = (
        select(Game)
        .join(GameProduct, Game.id == GameProduct.game_id)
        .where(GameProduct.provider_id == pid)
        .group_by(Game.id)
        .order_by(Game.sort_order.asc(), Game.name.asc())
    )
    result = await db.execute(stmt)
    games = result.scalars().all()

    if not games:
        await callback.answer("لا توجد منتجات. امزامن المزود أولاً.", show_alert=True)
        return

    rows = [f"<b>{provider.name}</b>", f"الألعاب المتاحة:"]
    kb = []
    for g in games:
        count_stmt = select(func.count()).where(
            GameProduct.game_id == g.id, GameProduct.provider_id == pid
        )
        count = (await db.execute(count_stmt)).scalar() or 0
        display = g.display_name
        kb.append([InlineKeyboardButton(
            text=f"🎮 {display} ({count} باقة)",
            callback_data=f"adm:gpr:{g.id}",
        )])

    text = section_card("📦", f"منتجات {provider.name}", rows)
    await _safe_edit(callback, text, _kb(*kb, back="adm:gfp_select"))


# ═══════════════════════════════════════════════════════════
#  GAMES CRUD
# ═══════════════════════════════════════════════════════════

@router.callback_query(F.data == "adm:games_list")
async def list_games_admin(callback: CallbackQuery, db: AsyncSession):
    if not is_admin_or_mod(callback.from_user.id): return
    result = await db.execute(select(Game).order_by(Game.sort_order.asc(), Game.name.asc()))
    games = result.scalars().all()

    text = section_card("🕹️", "قائمة الألعاب", ["اختر لعبة لتعديلها:"])
    kb = []
    for g in games:
        status = "✅" if g.status else "❌"
        ar_badge = " 🇸🇦" if g.name_ar else ""
        kb.append([InlineKeyboardButton(
            text=f"{status} {g.display_name}{ar_badge}",
            callback_data=f"adm:game_edit:{g.id}"
        )])
    kb.append([InlineKeyboardButton(text="➕ إضافة لعبة جديدة", callback_data="adm:game_add")])
    await _safe_edit(callback, text, _kb(*kb, back="adm:games"))


@router.callback_query(F.data.startswith("adm:game_edit:"))
async def edit_game_detail(callback: CallbackQuery, db: AsyncSession):
    """Show game details with edit options."""
    if not is_admin_or_mod(callback.from_user.id): return
    game_id = int(callback.data.split(":")[2])
    game = await db.get(Game, game_id)
    if not game:
        await callback.answer("اللعبة غير موجودة")
        return

    prod_count = (await db.execute(
        select(func.count()).where(GameProduct.game_id == game_id)
    )).scalar() or 0
    active_count = (await db.execute(
        select(func.count()).where(GameProduct.game_id == game_id, GameProduct.active == True)
    )).scalar() or 0

    status_icon = "🟢 مفعّلة" if game.status else "🔴 معطّلة"
    toggle_text = "🔴 تعطيل" if game.status else "🟢 تفعيل"

    text = section_card("🎮", game.display_name, [
        f"🆔 #{game.id}",
        f"📛 الاسم: {game.name}",
        f"🇸🇦 الاسم العربي: {game.name_ar or 'غير محدد'}",
        f"📊 الحالة: {status_icon}",
        f"📦 الباقات: {active_count}/{prod_count}",
        f"🔗 FC Game ID: {game.fc_game_id or 'غير محدد'}",
        f"📏 الترتيب: {game.sort_order}",
    ])
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text=toggle_text, callback_data=f"adm:game_tgl:{game_id}"),
            InlineKeyboardButton(text="🇸🇦 تعديل الاسم العربي", callback_data=f"adm:game_ar:{game_id}"),
        ],
        [
            InlineKeyboardButton(text="⬆️ رفع", callback_data=f"adm:game_sort:{game_id}:-1"),
            InlineKeyboardButton(text="⬇️ خفض", callback_data=f"adm:game_sort:{game_id}:1"),
        ],
        [InlineKeyboardButton(text="📦 إدارة الباقات", callback_data=f"adm:gpr:{game_id}")],
        [InlineKeyboardButton(text="◀️ رجوع", callback_data="adm:games_list")],
    ])
    await _safe_edit(callback, text, kb)
    await callback.answer()


@router.callback_query(F.data.startswith("adm:game_tgl:"))
async def toggle_game_status(callback: CallbackQuery, db: AsyncSession):
    if not is_admin_or_mod(callback.from_user.id): return
    game_id = int(callback.data.split(":")[2])
    game = await db.get(Game, game_id)
    if game:
        game.status = not game.status
        await db.commit()
    await edit_game_detail(callback, db)


@router.callback_query(F.data.startswith("adm:game_ar:"))
async def edit_game_arabic_name(callback: CallbackQuery, state: FSMContext):
    if not is_admin_or_mod(callback.from_user.id): return
    game_id = int(callback.data.split(":")[2])
    await state.set_state(GameAdminStates.waiting_name_ar)
    await state.update_data(edit_game_id=game_id, ui_chat_id=callback.message.chat.id, ui_msg_id=callback.message.message_id)
    await callback.message.edit_text(
        "┌──── 🇸🇦 تعديل الاسم العربي ────\n"
        "│  أرسل الاسم العربي للعبة:\n"
        "│  /cancel للإلغاء\n"
        "└──────────────────────"
    )
    await callback.answer()


@router.message(GameAdminStates.waiting_name_ar)
async def save_game_arabic_name(message: Message, db: AsyncSession, state: FSMContext):
    if not is_admin_or_mod(message.from_user.id): return
    if message.text and message.text.strip() == "/cancel":
        await state.clear(); return

    data = await state.get_data()
    game_id = data.get("edit_game_id")
    game = await db.get(Game, game_id)
    if game:
        game.name_ar = message.text.strip()
        await db.commit()

    await state.clear()
    try: await message.delete()
    except Exception: pass
    try:
        # Return to game detail
        await message.bot.edit_message_text(
            chat_id=data["ui_chat_id"], message_id=data["ui_msg_id"],
            text=f"✅ تم تحديث الاسم العربي: <b>{game.name_ar}</b>",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="◀️ رجوع للعبة", callback_data=f"adm:game_edit:{game_id}")],
            ])
        )
    except Exception:
        await message.answer(f"✅ تم تحديث الاسم العربي: {game.name_ar}")


@router.callback_query(F.data.startswith("adm:game_sort:"))
async def sort_game(callback: CallbackQuery, db: AsyncSession):
    if not is_admin_or_mod(callback.from_user.id): return
    parts = callback.data.split(":")
    game_id = int(parts[2])
    direction = int(parts[3])  # -1 = up, 1 = down
    game = await db.get(Game, game_id)
    if game:
        game.sort_order = max(0, game.sort_order + direction)
        await db.commit()
    await edit_game_detail(callback, db)


@router.callback_query(F.data == "adm:game_add")
async def add_game_start(callback: CallbackQuery, state: FSMContext):
    if not is_admin_or_mod(callback.from_user.id): return
    await state.set_state(GameAdminStates.waiting_game_name)
    await callback.message.answer("يرجى إدخال اسم اللعبة الجديدة:")
    await callback.answer()


@router.message(GameAdminStates.waiting_game_name)
async def add_game_finish(message: Message, db: AsyncSession, state: FSMContext):
    if not is_admin_or_mod(message.from_user.id): return
    name = message.text.strip()
    auto_ar = _translate_game_name(name)
    db.add(Game(name=name, name_ar=auto_ar or None, status=True))
    await db.commit()
    await state.clear()
    ar_msg = f" (الاسم العربي: {auto_ar})" if auto_ar else ""
    await message.answer(f"✅ تم إضافة اللعبة: {name}{ar_msg}")


# ═══════════════════════════════════════════════════════════
#  PRODUCTS LIST
# ═══════════════════════════════════════════════════════════

PER_PAGE_GAMES = 10  # games shown per page in any of the new browse views


async def _games_with_counts(db: AsyncSession, games: list) -> list:
    """Decorate games with (active, total) product counts for label rendering."""
    out = []
    for g in games:
        total = (await db.execute(
            select(func.count()).where(GameProduct.game_id == g.id)
        )).scalar() or 0
        active = (await db.execute(
            select(func.count()).where(GameProduct.game_id == g.id, GameProduct.active == True)
        )).scalar() or 0
        out.append((g, active, total))
    return out


def _games_kb(games_with_counts: list) -> list:
    return [
        [InlineKeyboardButton(
            text=f"🎮 {g.display_name} ({active}/{total})",
            callback_data=f"adm:gpr:{g.id}",
        )]
        for g, active, total in games_with_counts
    ]


@router.callback_query(F.data == "adm:game_prods_list")
async def list_game_products_root(callback: CallbackQuery, db: AsyncSession):
    """
    Top-level "all packages" hub — replaces the old flat 68-page list.

    Splits the catalog into:
      🔥 الأكثر طلباً  — top 20 by GameOrder count, falling back to name match
      📂 حسب التصنيف  — battle royale, MOBA, gift cards, …
      📜 كل الألعاب    — original paginated browser
    """
    if not is_admin_or_mod(callback.from_user.id):
        return
    from services.game_categorizer import CATEGORIES

    total_games = (await db.execute(select(func.count()).select_from(Game))).scalar() or 0
    total_active_games = (await db.execute(
        select(func.count()).select_from(Game).where(Game.status == True)
    )).scalar() or 0

    rows = [
        f"إجمالي الألعاب: <b>{total_games}</b>",
        f"المفعّلة: <b>{total_active_games}</b>",
        "",
        "اختر طريقة التصفح:",
    ]
    text = section_card("📦", "إدارة الباقات", rows)

    kb = [
        [InlineKeyboardButton(text="🔥 الأكثر طلباً", callback_data="adm:gpl:popular:0")],
        [InlineKeyboardButton(text="📂 حسب التصنيف",  callback_data="adm:gpl_cats")],
        [InlineKeyboardButton(text="📜 كل الألعاب",    callback_data="adm:gpl:all:0")],
    ]
    await _safe_edit(callback, text, _kb(*kb, back="adm:games"))


@router.callback_query(F.data == "adm:gpl_cats")
async def list_game_categories(callback: CallbackQuery, db: AsyncSession):
    """Show category groupings with live counts so admin sees what's where."""
    if not is_admin_or_mod(callback.from_user.id):
        return
    from services.game_categorizer import CATEGORIES, classify_game, all_category_keys

    # Pull every game once and bucket in memory — cheaper than 11 separate queries.
    games = (await db.execute(select(Game))).scalars().all()
    buckets: dict[str, int] = {k: 0 for k in all_category_keys()}
    for g in games:
        key = classify_game(g.name, getattr(g, "category_key", None))
        if key not in buckets:
            buckets[key] = 0
        buckets[key] += 1

    text = section_card("📂", "تصفح حسب التصنيف", [
        f"إجمالي الألعاب: <b>{len(games)}</b>",
        "",
        "اختر تصنيفاً:",
    ])
    kb = []
    for key in all_category_keys():
        info = CATEGORIES[key]
        count = buckets.get(key, 0)
        if count == 0:
            continue
        kb.append([InlineKeyboardButton(
            text=f"{info['icon']} {info['ar']} ({count})",
            callback_data=f"adm:gpl:cat_{key}:0",
        )])
    if not kb:
        kb.append([InlineKeyboardButton(text="لا توجد ألعاب مصنّفة", callback_data="noop")])

    await _safe_edit(callback, text, _kb(*kb, back="adm:game_prods_list"))


@router.callback_query(F.data.startswith("adm:gpl:"))
async def list_game_products_filtered(callback: CallbackQuery, db: AsyncSession):
    """
    Render the games list for one of the views: popular / cat_<key> / all.

    Callback format: adm:gpl:<view>:<page>
      view = "popular"  → top 20 popular games (ordered by GameOrder count)
      view = "cat_<k>" → games whose classifier resolves to category key <k>
      view = "all"      → flat list, sort_order asc then name asc
    """
    if not is_admin_or_mod(callback.from_user.id):
        return
    from services.game_categorizer import (
        CATEGORIES, POPULAR_GAMES, classify_game, is_popular,
    )
    from models.game import GameOrder

    parts = callback.data.split(":")
    view = parts[2]
    page = int(parts[3]) if len(parts) > 3 and parts[3].isdigit() else 0

    title = "📦 الباقات"
    icon = "📦"
    games: list = []

    if view == "popular":
        # Rank by real demand first; fall back to the hardcoded popular list
        # so brand-new bots without order history still get a reasonable view.
        order_counts = dict((await db.execute(
            select(GameOrder.game_id, func.count(GameOrder.id))
            .group_by(GameOrder.game_id)
        )).all())
        all_games = (await db.execute(select(Game).where(Game.status == True))).scalars().all()

        def pop_score(g) -> tuple:
            real = order_counts.get(g.id, 0)
            named = 1 if is_popular(g.name) else 0
            return (-real, -named, g.sort_order or 0, g.name.lower())

        all_games.sort(key=pop_score)
        games = all_games[:20]
        title = "🔥 الأكثر طلباً (Top 20)"
        icon = "🔥"

    elif view.startswith("cat_"):
        cat_key = view[4:]
        info = CATEGORIES.get(cat_key)
        if not info:
            await callback.answer("تصنيف غير معروف", show_alert=True)
            return
        all_games = (await db.execute(
            select(Game).order_by(Game.sort_order.asc(), Game.name.asc())
        )).scalars().all()
        games = [g for g in all_games if classify_game(g.name, getattr(g, "category_key", None)) == cat_key]
        title = f"{info['icon']} {info['ar']}"
        icon = info["icon"]

    else:  # "all" — original behaviour, paginated
        view = "all"
        all_games = (await db.execute(
            select(Game).order_by(Game.sort_order.asc(), Game.name.asc())
        )).scalars().all()
        games = all_games
        title = "📜 كل الألعاب"
        icon = "📜"

    total = len(games)
    pages = max(1, (total + PER_PAGE_GAMES - 1) // PER_PAGE_GAMES)
    if page >= pages:
        page = pages - 1
    page_games = games[page * PER_PAGE_GAMES:(page + 1) * PER_PAGE_GAMES]

    rows = [f"العدد: <b>{total}</b>", f"الصفحة {page+1}/{pages}"]
    text = section_card(icon, title, rows)

    kb = _games_kb(await _games_with_counts(db, page_games))

    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton(text="◀️ السابق", callback_data=f"adm:gpl:{view}:{page-1}"))
    if page + 1 < pages:
        nav.append(InlineKeyboardButton(text="التالي ▶️", callback_data=f"adm:gpl:{view}:{page+1}"))
    if nav:
        kb.append(nav)

    await _safe_edit(callback, text, _kb(*kb, back="adm:game_prods_list"))


@router.callback_query(F.data.startswith("adm:gpr:"))
async def show_game_products_admin(callback: CallbackQuery, db: AsyncSession):
    """Browse products for a game — paginated with toggle, sort, details."""
    if not is_admin_or_mod(callback.from_user.id): return

    parts = callback.data.split(":")
    game_id = int(parts[2])
    page = int(parts[3]) if len(parts) > 3 else 0
    PER_PAGE = 8

    game = await db.get(Game, game_id)
    if not game:
        await callback.answer("اللعبة غير موجودة")
        return

    total = (await db.execute(
        select(func.count()).where(GameProduct.game_id == game_id)
    )).scalar() or 0

    stmt = (
        select(GameProduct)
        .where(GameProduct.game_id == game_id)
        .order_by(GameProduct.sort_order.asc(), GameProduct.price.asc())
        .offset(page * PER_PAGE).limit(PER_PAGE)
    )
    result = await db.execute(stmt)
    products = result.scalars().all()

    active_count = (await db.execute(
        select(func.count()).where(GameProduct.game_id == game_id, GameProduct.active == True)
    )).scalar() or 0

    display = game.display_name
    rows = [
        f"<b>{display}</b>",
        f"المنتجات: {total} | المفعّلة: {active_count}",
        f"الصفحة {page+1}/{max(1, (total + PER_PAGE - 1) // PER_PAGE)}",
        "",
    ]

    kb = []
    for p in products:
        icon = "✅" if p.active else "❌"
        price_text = f"{fmt_price(p.price)}" if p.price else "N/A"
        p_display = p.display_name[:30]
        kb.append([InlineKeyboardButton(
            text=f"{icon} {p_display} — {price_text}",
            callback_data=f"adm:gpd:{p.id}",
        )])

    # Pagination
    nav_row = []
    if page > 0:
        nav_row.append(InlineKeyboardButton(text="◀️ السابق", callback_data=f"adm:gpr:{game_id}:{page-1}"))
    if (page + 1) * PER_PAGE < total:
        nav_row.append(InlineKeyboardButton(text="التالي ▶️", callback_data=f"adm:gpr:{game_id}:{page+1}"))
    if nav_row:
        kb.append(nav_row)

    # Enable/disable all
    kb.append([
        InlineKeyboardButton(text="✅ تفعيل الكل", callback_data=f"adm:gpa:{game_id}:1"),
        InlineKeyboardButton(text="❌ تعطيل الكل", callback_data=f"adm:gpa:{game_id}:0"),
    ])

    text = section_card("📦", f"منتجات {display}", rows)
    await _safe_edit(callback, text, _kb(*kb, back="adm:game_prods_list"))
    await callback.answer()


@router.callback_query(F.data.startswith("adm:gpd:"))
async def show_product_detail(callback: CallbackQuery, db: AsyncSession):
    """Show detailed product info with edit options."""
    if not is_admin_or_mod(callback.from_user.id): return
    prod_id = int(callback.data.split(":")[2])
    product = await db.get(GameProduct, prod_id)
    if not product:
        await callback.answer("المنتج غير موجود")
        return

    game = await db.get(Game, product.game_id)
    provider = await db.get(Provider, product.provider_id)

    status_icon = "🟢 مفعّل" if product.active else "🔴 معطّل"
    toggle_text = "🔴 تعطيل" if product.active else "🟢 تفعيل"

    rows = [
        f"🆔 #{product.id}",
        f"📛 الاسم: {product.name}",
        f"🇸🇦 العربي: {product.name_ar or 'غير محدد'}",
        f"📝 الوصف: {product.description or 'غير متوفر'}",
        f"💵 سعر التكلفة: {fmt_price(product.base_price)}",
        f"💰 سعر البيع: {fmt_price(product.price)}",
        f"💱 العملة: {product.currency or 'USD'}",
        f"📊 الحالة: {status_icon}",
        f"🔌 المزود: {provider.name if provider else 'N/A'}",
        f"🎮 اللعبة: {game.display_name if game else 'N/A'}",
        f"🌍 المنطقة: {product.region or 'عام'}",
        f"📏 الترتيب: {product.sort_order}",
    ]

    # Show required fields
    if product.fields_json:
        try:
            fields = json.loads(product.fields_json) if isinstance(product.fields_json, str) else product.fields_json
            if fields:
                field_names = [f.get("label", f.get("name", "")) for f in fields]
                rows.append(f"📋 الحقول المطلوبة: {', '.join(field_names)}")
        except Exception:
            pass

    text = section_card("📦", product.display_name, rows)
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text=toggle_text, callback_data=f"adm:gpt:{prod_id}"),
            InlineKeyboardButton(text="🇸🇦 اسم عربي", callback_data=f"adm:gp_ar:{prod_id}"),
        ],
        [
            InlineKeyboardButton(text="⬆️ رفع", callback_data=f"adm:gp_sort:{prod_id}:-1"),
            InlineKeyboardButton(text="⬇️ خفض", callback_data=f"adm:gp_sort:{prod_id}:1"),
        ],
        [InlineKeyboardButton(text="◀️ رجوع", callback_data=f"adm:gpr:{product.game_id}")],
    ])
    await _safe_edit(callback, text, kb)
    await callback.answer()


@router.callback_query(F.data.startswith("adm:gpt:"))
async def toggle_game_product(callback: CallbackQuery, db: AsyncSession):
    """Toggle a single product active/inactive."""
    if not is_admin_or_mod(callback.from_user.id): return
    prod_id = int(callback.data.split(":")[2])
    product = await db.get(GameProduct, prod_id)
    if product:
        product.active = not product.active
        await db.commit()
        status = "✅ مفعّل" if product.active else "❌ معطّل"
        await callback.answer(f"{product.display_name}: {status}", show_alert=False)
    # Return to product detail
    await show_product_detail(callback, db)


@router.callback_query(F.data.startswith("adm:gp_ar:"))
async def edit_product_arabic_name(callback: CallbackQuery, state: FSMContext):
    if not is_admin_or_mod(callback.from_user.id): return
    prod_id = int(callback.data.split(":")[2])
    await state.set_state(GameAdminStates.waiting_product_name_ar)
    await state.update_data(edit_prod_id=prod_id, ui_chat_id=callback.message.chat.id, ui_msg_id=callback.message.message_id)
    await callback.message.edit_text(
        "┌──── 🇸🇦 تعديل الاسم العربي ────\n"
        "│  أرسل الاسم العربي للمنتج:\n"
        "│  /cancel للإلغاء\n"
        "└──────────────────────"
    )
    await callback.answer()


@router.message(GameAdminStates.waiting_product_name_ar)
async def save_product_arabic_name(message: Message, db: AsyncSession, state: FSMContext):
    if not is_admin_or_mod(message.from_user.id): return
    if message.text and message.text.strip() == "/cancel":
        await state.clear(); return

    data = await state.get_data()
    prod_id = data.get("edit_prod_id")
    product = await db.get(GameProduct, prod_id)
    if product:
        product.name_ar = message.text.strip()
        await db.commit()

    await state.clear()
    try: await message.delete()
    except Exception: pass
    try:
        await message.bot.edit_message_text(
            chat_id=data["ui_chat_id"], message_id=data["ui_msg_id"],
            text=f"✅ تم تحديث الاسم العربي: <b>{product.name_ar}</b>",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="◀️ رجوع للمنتج", callback_data=f"adm:gpd:{prod_id}")],
            ])
        )
    except Exception:
        await message.answer(f"✅ تم: {product.name_ar}")


@router.callback_query(F.data.startswith("adm:gp_sort:"))
async def sort_product(callback: CallbackQuery, db: AsyncSession):
    if not is_admin_or_mod(callback.from_user.id): return
    parts = callback.data.split(":")
    prod_id = int(parts[2])
    direction = int(parts[3])
    product = await db.get(GameProduct, prod_id)
    if product:
        product.sort_order = max(0, product.sort_order + direction)
        await db.commit()
    await show_product_detail(callback, db)


@router.callback_query(F.data.startswith("adm:gpa:"))
async def toggle_all_game_products(callback: CallbackQuery, db: AsyncSession):
    """Enable/disable ALL products for a game."""
    if not is_admin_or_mod(callback.from_user.id): return
    parts = callback.data.split(":")
    game_id = int(parts[2])
    new_status = parts[3] == "1"

    await db.execute(
        update(GameProduct).where(GameProduct.game_id == game_id).values(active=new_status)
    )
    await db.commit()

    action = "تفعيل" if new_status else "تعطيل"
    await callback.answer(f"تم {action} جميع المنتجات", show_alert=True)

    # Return to products list — use proper callback data
    parts_new = callback.data.split(":")
    # We need to construct a proper callback for show_game_products_admin
    # Instead of mutating callback.data, call the function with reconstructed data
    callback_data_bak = callback.data
    try:
        callback.__dict__['_values']['data'] = f"adm:gpr:{game_id}"
    except Exception:
        pass
    try:
        object.__setattr__(callback, 'data', f"adm:gpr:{game_id}")
    except Exception:
        pass
    await show_game_products_admin(callback, db)


@router.callback_query(F.data == "adm:game_markup_set")
async def game_markup_prompt(callback: CallbackQuery, state: FSMContext):
    if not is_admin_or_mod(callback.from_user.id): return
    current = settings_manager.get_game_markup_pct()
    await state.set_state(GameAdminStates.waiting_global_markup)
    text = section_card("📈", "نسبة ربح الألعاب", [
        f"النسبة الحالية: <b>{current:.0f}%</b>",
        "سيتم إعادة حساب سعر البيع لجميع باقات الألعاب.",
        "أدخل النسبة (مثلاً 20 لـ 20% ربح):",
    ])
    await _safe_edit(callback, text, _kb(back="adm:games"))


@router.message(GameAdminStates.waiting_global_markup)
async def apply_global_game_markup(message: Message, db: AsyncSession, state: FSMContext):
    if not is_admin_or_mod(message.from_user.id): return
    try:
        pct = float(message.text.strip())
    except (ValueError, AttributeError):
        await message.answer("يرجى إدخال رقم (مثال: 20)")
        return

    settings_manager.set_game_markup_pct(pct)
    markup = pct / 100

    result = await db.execute(select(GameProduct))
    products = result.scalars().all()
    count = 0
    for p in products:
        new_price = round(float(p.base_price) * (1 + markup), 4)
        p.price = new_price
        count += 1

    await db.commit()
    await state.clear()
    await message.answer(
        f"✅ تم حفظ نسبة الربح: <b>{pct:.0f}%</b>\n"
        f"تم تحديث أسعار <b>{count}</b> باقة.\n\n"
        "سيتم تطبيقها تلقائياً على كل المزامنات.",
        parse_mode="HTML",
    )


# ═══════════════════════════════════════════════════════════
#  GAME ORDERS
# ═══════════════════════════════════════════════════════════

@router.callback_query(F.data == "adm:game_orders")
async def list_game_orders_admin(callback: CallbackQuery, db: AsyncSession):
    if not is_admin_or_mod(callback.from_user.id): return
    result = await db.execute(
        select(GameOrder).order_by(GameOrder.created_at.desc()).limit(20)
    )
    orders = result.scalars().all()

    text = "📋 <b>آخر 20 طلب شحن ألعاب:</b>\n\n"
    if not orders:
        text += "لا توجد طلبات حالياً."
    else:
        for o in orders:
            emoji = {"pending": "⏳", "processing": "🔄", "completed": "✅", "canceled": "❌"}.get(o.status, "❓")
            game = await db.get(Game, o.game_id) if o.game_id else None
            product = await db.get(GameProduct, o.product_id) if o.product_id else None
            game_name = game.display_name if game else "—"
            prod_name = product.display_name if product else "—"
            text += f"{emoji} ID: {o.id} | User: {o.user_id} | {fmt_price(o.price)}\n"
            text += f"└ 🎮 {game_name} — {prod_name}\n"
            text += f"└ Account: <code>{o.account_id}</code> | {o.status}\n\n"

    await _safe_edit(callback, text, _kb(back="adm:games"))


# ═══════════════════════════════════════════════════════════
#  FAZERCARDS SECTION
# ═══════════════════════════════════════════════════════════

@router.callback_query(F.data == "adm:fc_sync")
async def fazercards_sync_start(callback: CallbackQuery, db: AsyncSession):
    """Auto-sync FazerCards — full product details including fields, descriptions."""
    if not is_admin_or_mod(callback.from_user.id): return
    if not FAZERCARDS_API_KEY:
        await callback.answer("❌ FAZERCARDS_API_KEY غير مضبوط", show_alert=True)
        return

    await callback.answer("جاري جلب المنتجات من FazerCards...", show_alert=False)

    # Fetch ALL products in ONE call
    all_products = await fazercards_provider.get_topup_products("")
    if not all_products:
        await callback.answer("❌ فشل جلب المنتجات", show_alert=True)
        return

    # Also fetch games for name/icon mapping
    games_data = await fazercards_provider.get_games()
    game_map = {}
    if games_data:
        for g in games_data:
            gid = str(g.get("id", ""))
            game_map[gid] = {
                "name": g.get("name", "Unknown"),
                "icon_url": g.get("icon_url", ""),
            }

    markup_pct = settings_manager.get_game_markup_pct()
    markup = markup_pct / 100
    fc_provider = await _get_or_create_fc_provider(db)

    added, updated = 0, 0
    games_seen = set()

    for p in all_products:
        game_id = str(p.get("game_id", "general"))
        ginfo = game_map.get(game_id, {})
        game_name = ginfo.get("name", p.get("meta", {}).get("game_name", game_id.replace("_", " ").title()))
        game_icon = ginfo.get("icon_url", "")
        games_seen.add(game_name)

        # Get or create game
        stmt = select(Game).where(Game.name == game_name)
        res = await db.execute(stmt)
        game_row = res.scalars().first()
        if not game_row:
            auto_ar = _translate_game_name(game_name)
            game_row = Game(
                name=game_name, status=True,
                name_ar=auto_ar or None,
                icon_url=game_icon or None,
                fc_game_id=game_id,
            )
            db.add(game_row)
            await db.flush()
        else:
            if not game_row.icon_url and game_icon:
                game_row.icon_url = game_icon
            if not game_row.fc_game_id:
                game_row.fc_game_id = game_id

        api_id = str(p.get("id", ""))
        base = float(p.get("price", p.get("cost", p.get("amount", 0))))
        sell = round(base * (1 + markup), 4)
        name = p.get("display_name", p.get("name", "Unknown"))
        fields_data = p.get("fields")
        fields_json_val = json.dumps(fields_data) if fields_data else None

        stmt2 = select(GameProduct).where(
            GameProduct.api_service_id == api_id,
            GameProduct.provider_id == fc_provider.id,
        )
        res2 = await db.execute(stmt2)
        ex = res2.scalars().first()
        if ex:
            ex.base_price = base
            ex.price = sell
            ex.name = name
            ex.game_id = game_row.id
            ex.description = p.get("note") or ex.description
            ex.currency = p.get("currency", "USD")
            ex.fields_json = fields_json_val or ex.fields_json
            ex.min_quantity = p.get("min_quantity", 1)
            ex.max_quantity = p.get("max_quantity", 1)
            ex.region = p.get("region") or ex.region
            if not ex.name_ar:
                auto_ar = _translate_product_name(name)
                if auto_ar:
                    ex.name_ar = auto_ar
            updated += 1
        else:
            auto_ar = _translate_product_name(name)
            db.add(GameProduct(
                game_id=game_row.id, name=name,
                name_ar=auto_ar or None,
                description=p.get("note") or None,
                currency=p.get("currency", "USD"),
                base_price=base, price=sell,
                api_service_id=api_id, provider_id=fc_provider.id,
                fields_json=fields_json_val,
                min_quantity=p.get("min_quantity", 1),
                max_quantity=p.get("max_quantity", 1),
                region=p.get("region") or None,
            ))
            added += 1

    await db.commit()

    text = section_card("✅", "مزامنة FazerCards", [
        f"ألعاب: <b>{len(games_seen)}</b>",
        f"منتجات جديدة: <b>{added}</b>",
        f"محدّثة: <b>{updated}</b>",
        f"ربح: <b>{markup_pct:.0f}%</b>",
        "",
        "⚠️ المنتجات الجديدة معطلة افتراضياً.",
        "فعّلها من إدارة الباقات.",
    ])
    await _safe_edit(callback, text, _kb(
        [InlineKeyboardButton(text="📦 تصفح المنتجات", callback_data="adm:game_prods_list")],
        back="adm:games",
    ))


@router.callback_query(F.data == "adm:fc_balance")
async def fazercards_balance(callback: CallbackQuery):
    if not is_admin_or_mod(callback.from_user.id): return
    balance = await fazercards_provider.get_balance()
    if balance and isinstance(balance, dict):
        text = section_card("💰", "رصيد FazerCards", [
            f"العملة: <b>{balance.get('currency', 'USD')}</b>",
            f"الرصيد: <b>{balance.get('available', balance.get('balance', 'N/A'))}</b>",
        ])
    else:
        text = section_card("❌", "رصيد FazerCards", ["فشل جلب الرصيد."])
    await _safe_edit(callback, text, _kb(back="adm:games"))


# ═══════════════════════════════════════════════════════════
#  ACTIVE PRODUCTS VIEW (what the user will see)
# ═══════════════════════════════════════════════════════════

@router.callback_query(F.data.startswith("adm:active_prods"))
async def active_products_list(callback: CallbackQuery, db: AsyncSession):
    """Show only active (enabled) products grouped by game — what the user sees."""
    if not is_admin_or_mod(callback.from_user.id): return

    parts = callback.data.split(":")
    page = int(parts[2]) if len(parts) > 2 else 0
    PER_PAGE = 10

    # Only games with active products
    from sqlalchemy import exists
    has_active = exists().where(
        GameProduct.game_id == Game.id, GameProduct.active == True
    )
    total = (await db.execute(
        select(func.count()).select_from(Game).where(Game.status == True, has_active)
    )).scalar() or 0

    stmt = (
        select(Game)
        .where(Game.status == True, has_active)
        .order_by(Game.sort_order.asc(), Game.name.asc())
        .offset(page * PER_PAGE).limit(PER_PAGE)
    )
    result = await db.execute(stmt)
    games = result.scalars().all()

    total_active = (await db.execute(
        select(func.count()).where(GameProduct.active == True)
    )).scalar() or 0

    rows = [
        f"الألعاب المفعّلة: <b>{total}</b>",
        f"إجمالي المنتجات المفعّلة: <b>{total_active}</b>",
        f"الصفحة {page+1}/{max(1, (total + PER_PAGE - 1) // PER_PAGE)}",
        "",
        "هذا ما يراه المستخدم عند شحن الألعاب:",
    ]

    text = section_card("✅", "المنتجات المفعّلة (عرض المستخدم)", rows)
    kb = []
    for g in games:
        active = (await db.execute(
            select(func.count()).where(GameProduct.game_id == g.id, GameProduct.active == True)
        )).scalar() or 0
        # Show Arabic name if available
        display = g.display_name
        ar_badge = " 🇸🇦" if g.name_ar else ""
        kb.append([InlineKeyboardButton(
            text=f"🎮 {display}{ar_badge} ({active} باقة)",
            callback_data=f"adm:active_game:{g.id}",
        )])

    # Pagination
    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton(text="◀️ السابق", callback_data=f"adm:active_prods:{page-1}"))
    if (page + 1) * PER_PAGE < total:
        nav.append(InlineKeyboardButton(text="التالي ▶️", callback_data=f"adm:active_prods:{page+1}"))
    if nav:
        kb.append(nav)

    await _safe_edit(callback, text, _kb(*kb, back="adm:games"))
    await callback.answer()


@router.callback_query(F.data.startswith("adm:active_game:"))
async def active_game_products(callback: CallbackQuery, db: AsyncSession):
    """Show active products for a specific game — admin preview of what user sees."""
    if not is_admin_or_mod(callback.from_user.id): return

    parts = callback.data.split(":")
    game_id = int(parts[2])
    page = int(parts[3]) if len(parts) > 3 else 0
    PER_PAGE = 10

    game = await db.get(Game, game_id)
    if not game:
        await callback.answer("اللعبة غير موجودة")
        return

    total = (await db.execute(
        select(func.count()).where(GameProduct.game_id == game_id, GameProduct.active == True)
    )).scalar() or 0

    stmt = (
        select(GameProduct)
        .where(GameProduct.game_id == game_id, GameProduct.active == True)
        .order_by(GameProduct.sort_order.asc(), GameProduct.price.asc())
        .offset(page * PER_PAGE).limit(PER_PAGE)
    )
    result = await db.execute(stmt)
    products = result.scalars().all()

    display = game.display_name
    rows = [
        f"<b>{display}</b>",
        f"🇸🇦 العربي: {game.name_ar or 'غير محدد'}",
        f"✅ المنتجات المفعّلة: {total}",
        f"الصفحة {page+1}/{max(1, (total + PER_PAGE - 1) // PER_PAGE)}",
        "",
        "ما يراه المستخدم:",
    ]

    kb = []
    for p in products:
        p_display = p.display_name
        ar_badge = " 🇸🇦" if p.name_ar else ""
        kb.append([InlineKeyboardButton(
            text=f"✅ {p_display}{ar_badge} — {fmt_price(p.price)}",
            callback_data=f"adm:gpd:{p.id}",
        )])

    # Pagination
    nav_row = []
    if page > 0:
        nav_row.append(InlineKeyboardButton(text="◀️ السابق", callback_data=f"adm:active_game:{game_id}:{page-1}"))
    if (page + 1) * PER_PAGE < total:
        nav_row.append(InlineKeyboardButton(text="التالي ▶️", callback_data=f"adm:active_game:{game_id}:{page+1}"))
    if nav_row:
        kb.append(nav_row)

    # Quick actions
    kb.append([
        InlineKeyboardButton(text="🇸🇦 تعديل اسم اللعبة", callback_data=f"adm:game_ar:{game_id}"),
        InlineKeyboardButton(text="📦 كل الباقات", callback_data=f"adm:gpr:{game_id}"),
    ])

    text = section_card("✅", f"المفعّلة — {display}", rows)
    await _safe_edit(callback, text, _kb(*kb, back="adm:active_prods"))
    await callback.answer()


# ── noop ──
@router.callback_query(F.data == "noop")
async def noop_handler(callback: CallbackQuery):
    await callback.answer()
