import logging
import json
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from sqlalchemy import select, text as sa_text
from sqlalchemy.ext.asyncio import AsyncSession

from models.game import Game, GameProduct, GameOrder
from services.user_manager import get_or_create_user
from services.game_services import game_api_place_order, validate_player_id, get_validation_code, needs_server_id
from services.game_name_translator import translate_game_name, translate_product_name
from services.notify import notify_activation
from handlers.common import add_nav, nav_enter, register_screen, safe_edit
from ui import section_card, fmt_price, status_label_ar, status_label_en

logger = logging.getLogger(__name__)
router = Router()


class GameOrderStates(StatesGroup):
    waiting_account_id = State()
    waiting_server_id = State()       # For games that need server_id (MLBB, Genshin)
    confirm_order = State()


def _L(lang: str, ar: str, en: str) -> str:
    return ar if lang == "ar" else en


def _game_display(game: Game, lang: str) -> str:
    """Get proper display name based on language.

    Priority for Arabic:
      1. Admin-set game.name_ar
      2. Auto-translation from curated dictionary (PUBG → ببجي, etc.)
      3. Original English name as last resort
    """
    if lang == "ar":
        if game.name_ar:
            return game.name_ar
        return translate_game_name(game.name, "ar")
    return game.name


def _prod_display(product: GameProduct, lang: str) -> str:
    """Get proper display name based on language.

    Priority for Arabic:
      1. Admin-set product.name_ar
      2. Auto-translation of common keywords (UC → شدة, Diamonds → جواهر)
      3. Original English name as last resort
    """
    if lang == "ar":
        if product.name_ar:
            return product.name_ar
        return translate_product_name(product.name, "ar")
    return product.name


def _get_field_labels(product: GameProduct) -> list[dict]:
    """Parse field requirements from product.fields_json."""
    if not product.fields_json:
        return []
    try:
        fields = json.loads(product.fields_json) if isinstance(product.fields_json, str) else product.fields_json
        return fields if isinstance(fields, list) else []
    except Exception:
        return []


# --- User Flow Handlers ---

@router.callback_query(F.data == "game_topup")
async def show_games_list(callback: CallbackQuery, db: AsyncSession):
    user = await get_or_create_user(db, callback.from_user.id)
    lang = user.language or "ar"
    from sqlalchemy import exists
    has_active = exists().where(
        GameProduct.game_id == Game.id, GameProduct.active == True
    )
    stmt = select(Game).where(Game.status == True, has_active).order_by(Game.sort_order.asc(), Game.name.asc())
    result = await db.execute(stmt)
    games = result.scalars().all()

    if not games:
        await callback.answer(_L(lang, "لا توجد ألعاب متاحة حالياً", "No games available currently"), show_alert=True)
        return

    kb = []
    for game in games:
        kb.append([InlineKeyboardButton(
            text=_game_display(game, lang),
            callback_data=f"game_select:{game.id}"
        )])

    kb = add_nav(kb, lang)
    text = section_card("🎮", _L(lang, "شحن الألعاب", "Game Top-up"), [
        _L(lang, "اختر اللعبة التي تريد شحنها:", "Select the game you want to top-up:")
    ])

    nav_enter(callback.from_user.id, "game_topup")
    await safe_edit(callback, text, InlineKeyboardMarkup(inline_keyboard=kb))
    await callback.answer()


@router.callback_query(F.data.startswith("game_select:"))
async def show_game_products(callback: CallbackQuery, db: AsyncSession):
    user = await get_or_create_user(db, callback.from_user.id)
    lang = user.language or "ar"
    game_id = int(callback.data.split(":")[1])

    game = await db.get(Game, game_id)
    if not game:
        await callback.answer(_L(lang, "اللعبة غير موجودة", "Game not found"), show_alert=True)
        return

    stmt = (
        select(GameProduct)
        .where(GameProduct.game_id == game_id, GameProduct.active == True)
        .order_by(GameProduct.sort_order.asc(), GameProduct.price.asc())
    )
    result = await db.execute(stmt)
    products = result.scalars().all()

    if not products:
        await callback.answer(_L(lang, "لا توجد باقات متاحة لهذه اللعبة", "No packages available for this game"), show_alert=True)
        return

    kb = []
    for prod in products:
        kb.append([InlineKeyboardButton(
            text=f"{_prod_display(prod, lang)} - {fmt_price(prod.price)}",
            callback_data=f"game_prod:{prod.id}"
        )])

    kb = add_nav(kb, lang)
    text = section_card("🎁", _game_display(game, lang), [
        _L(lang, "اختر الباقة المناسبة:", "Select the suitable package:")
    ])

    nav_enter(callback.from_user.id, f"game_select:{game_id}")
    await safe_edit(callback, text, InlineKeyboardMarkup(inline_keyboard=kb))
    await callback.answer()


@router.callback_query(F.data.startswith("game_prod:"))
async def ask_account_id(callback: CallbackQuery, db: AsyncSession, state: FSMContext):
    user = await get_or_create_user(db, callback.from_user.id)
    lang = user.language or "ar"
    product_id = int(callback.data.split(":")[1])

    product = await db.get(GameProduct, product_id)
    if not product:
        await callback.answer(_L(lang, "المنتج غير موجود", "Product not found"), show_alert=True)
        return

    game = await db.get(Game, product.game_id)
    if not game:
        await callback.answer(_L(lang, "اللعبة غير موجودة", "Game not found"), show_alert=True)
        return

    await state.update_data(product_id=product_id, game_id=product.game_id)
    await state.set_state(GameOrderStates.waiting_account_id)

    lines = [
        _L(lang, f"🎮 اللعبة: {_game_display(game, lang)}", f"🎮 Game: {game.name}"),
        _L(lang, f"📦 المنتج: {_prod_display(product, lang)}", f"📦 Product: {product.name}"),
        _L(lang, f"💰 السعر: {fmt_price(product.price)}", f"💰 Price: {fmt_price(product.price)}"),
    ]

    # Show description if available
    if product.description:
        lines.append("")
        lines.append(f"📝 {product.description}")

    # Show what fields are required
    fields = _get_field_labels(product)
    lines.append("")
    if fields and len(fields) > 1:
        # Multiple fields — first ask for player ID
        field_names = [f.get("label", f.get("name", "")) for f in fields]
        lines.append(_L(lang,
            f"📋 الحقول المطلوبة: {' + '.join(field_names)}",
            f"📋 Required fields: {' + '.join(field_names)}"))
        lines.append("")

    lines.append(_L(lang,
        "⬇️ أرسل معرف اللاعب (Player ID):",
        "⬇️ Send your Player ID:"))

    text = section_card("🆔", _L(lang, "معرف اللاعب", "Player ID"), lines)

    kb = add_nav([], lang)
    nav_enter(callback.from_user.id, f"game_prod:{product_id}")
    await safe_edit(callback, text, InlineKeyboardMarkup(inline_keyboard=kb))
    await callback.answer()


@router.message(GameOrderStates.waiting_account_id)
async def receive_account_id(message: Message, db: AsyncSession, state: FSMContext):
    user = await get_or_create_user(db, message.from_user.id)
    lang = user.language or "ar"
    account_id = message.text.strip() if message.text else ""

    if not account_id:
        await message.answer(_L(lang,
            "❌ معرف اللاعب لا يمكن أن يكون فارغاً. أعد الإدخال:",
            "❌ Player ID cannot be empty. Please re-enter:"))
        return

    data = await state.get_data()
    product_id = data['product_id']

    product = await db.get(GameProduct, product_id)
    if not product:
        await message.answer(_L(lang, "❌ المنتج غير موجود.", "❌ Product not found."))
        await state.clear()
        return

    game = await db.get(Game, product.game_id)
    if not game:
        await message.answer(_L(lang, "❌ اللعبة غير موجودة.", "❌ Game not found."))
        await state.clear()
        return

    await state.update_data(account_id=account_id)

    # Check if this game needs server_id
    v_code = get_validation_code(game.fc_game_id) if game.fc_game_id else None
    if v_code and needs_server_id(v_code):
        # Ask for server ID
        await state.set_state(GameOrderStates.waiting_server_id)
        await message.answer(section_card("🌐", _L(lang, "معرف السيرفر", "Server ID"), [
            _L(lang, f"✅ معرف اللاعب: {account_id}", f"✅ Player ID: {account_id}"),
            "",
            _L(lang,
                "هذه اللعبة تتطلب معرف السيرفر (Server ID / Zone ID).",
                "This game requires a Server ID / Zone ID."),
            _L(lang, "⬇️ أرسل معرف السيرفر:", "⬇️ Send the Server ID:"),
        ]), parse_mode="HTML")
        return

    # No server_id needed — proceed to validation & confirmation
    await _validate_and_confirm(message, db, state, user, lang, game, product, account_id, "")


@router.message(GameOrderStates.waiting_server_id)
async def receive_server_id(message: Message, db: AsyncSession, state: FSMContext):
    user = await get_or_create_user(db, message.from_user.id)
    lang = user.language or "ar"
    server_id = message.text.strip() if message.text else ""

    if not server_id:
        await message.answer(_L(lang,
            "❌ معرف السيرفر لا يمكن أن يكون فارغاً.",
            "❌ Server ID cannot be empty."))
        return

    data = await state.get_data()
    product_id = data['product_id']
    account_id = data['account_id']

    product = await db.get(GameProduct, product_id)
    game = await db.get(Game, product.game_id) if product else None

    if not product or not game:
        await message.answer(_L(lang, "❌ خطأ في البيانات.", "❌ Data error."))
        await state.clear()
        return

    await state.update_data(server_id=server_id)
    await _validate_and_confirm(message, db, state, user, lang, game, product, account_id, server_id)


async def _validate_and_confirm(message, db, state, user, lang, game, product, account_id, server_id):
    """Validate player ID and show confirmation screen."""
    validation_msg = None

    if game.fc_game_id:
        try:
            result = await validate_player_id(game.fc_game_id, account_id, server_id)
            if result and isinstance(result, dict):
                if result.get("valid") is False:
                    error_text = result.get("error", "")
                    await message.answer(_L(lang,
                        f"❌ معرف اللاعب غير صالح!\n{error_text}\n\nتحقق من المعرف وأعد الإدخال:",
                        f"❌ Invalid Player ID!\n{error_text}\n\nVerify and re-enter:"))
                    # Go back to waiting_account_id
                    await state.set_state(GameOrderStates.waiting_account_id)
                    return
                if result.get("valid") is True:
                    player_name = result.get("name", "")
                    if player_name:
                        validation_msg = _L(lang,
                            f"✅ تم التحقق — اسم اللاعب: <b>{player_name}</b>",
                            f"✅ Verified — Player name: <b>{player_name}</b>")
        except Exception as e:
            logger.warning(f"Player ID validation failed (non-blocking): {e}")

    await state.set_state(GameOrderStates.confirm_order)

    g_display = _game_display(game, lang)
    p_display = _prod_display(product, lang)

    lines = [
        _L(lang, f"🎮 اللعبة: {g_display}", f"🎮 Game: {g_display}"),
        _L(lang, f"📦 المنتج: {p_display}", f"📦 Product: {p_display}"),
        _L(lang, f"🆔 معرف اللاعب: <code>{account_id}</code>", f"🆔 Player ID: <code>{account_id}</code>"),
    ]
    if server_id:
        lines.append(_L(lang, f"🌐 السيرفر: <code>{server_id}</code>", f"🌐 Server: <code>{server_id}</code>"))
    if validation_msg:
        lines.append(validation_msg)
    lines.extend([
        _L(lang, f"💰 السعر: {fmt_price(product.price)}", f"💰 Price: {fmt_price(product.price)}"),
        "",
        _L(lang, "هل تريد تأكيد الطلب؟ سيتم خصم المبلغ من رصيدك.",
           "Confirm order? Amount will be deducted from your balance.")
    ])

    text = section_card("🛒", _L(lang, "تأكيد الطلب", "Confirm Order"), lines)

    kb = [
        [InlineKeyboardButton(text=_L(lang, "✅ تأكيد وشحن", "✅ Confirm & Top-up"), callback_data="game_confirm")],
        [InlineKeyboardButton(text=_L(lang, "❌ إلغاء", "❌ Cancel"), callback_data="game_topup")]
    ]

    await message.answer(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=kb), parse_mode="HTML")


@router.callback_query(F.data == "game_confirm")
async def process_game_order(callback: CallbackQuery, db: AsyncSession, state: FSMContext):
    user = await get_or_create_user(db, callback.from_user.id)
    lang = user.language or "ar"
    data = await state.get_data()
    product_id = data.get('product_id')
    account_id = data.get('account_id')
    server_id = data.get('server_id', '')

    if not product_id or not account_id:
        await callback.answer(_L(lang, "خطأ: الجلسة انتهت", "Error: Session expired"), show_alert=True)
        return

    # ── Lock user row to prevent race condition ──
    try:
        lock_result = await db.execute(
            sa_text("SELECT balance FROM users WHERE id = :uid FOR UPDATE"),
            {"uid": user.id}
        )
        locked_row = lock_result.fetchone()
        current_balance = locked_row[0] if locked_row else user.balance
    except Exception:
        await db.refresh(user)
        current_balance = user.balance

    product = await db.get(GameProduct, product_id)
    if not product:
        await callback.answer(_L(lang, "❌ المنتج غير متوفر", "❌ Product not available"), show_alert=True)
        await state.clear()
        return

    if current_balance < product.price:
        await callback.answer(_L(lang, "عذراً، رصيدك غير كافٍ", "Sorry, insufficient balance"), show_alert=True)
        return

    # Deduct balance
    user.balance = current_balance - product.price

    from models.provider import Provider
    provider = await db.get(Provider, product.provider_id)

    # Build extra_data with server_id if present
    extra_data = None
    if server_id:
        extra_data = {"server_id": server_id}

    new_order = GameOrder(
        user_id=user.id,
        game_id=product.game_id,
        product_id=product.id,
        account_id=account_id,
        extra_data=extra_data,
        price=product.price,
        status="processing"
    )
    db.add(new_order)
    await db.flush()

    # Send notification
    try:
        game = await db.get(Game, product.game_id)
        await notify_activation(
            callback.bot, "game_order",
            amount=float(product.price),
            service=f"{_game_display(game, lang)} - {_prod_display(product, lang)}",
            order_id=new_order.id,
            user_id=user.id,
            service_id=game.id
        )
    except Exception as e:
        logger.error(f"Failed to send game order notification: {e}")

    # Place order via API
    api_result = await game_api_place_order(
        api_url=provider.api_url,
        api_key=provider.api_key,
        service_id=product.api_service_id,
        account_id=account_id,
        extra_data=extra_data
    )

    game = await db.get(Game, product.game_id)

    if "order" in api_result:
        new_order.external_order_id = str(api_result["order"])
        new_order.status = "processing"
        msg = _L(lang, "✅ تم استلام طلبك وهو قيد التنفيذ حالياً.",
                 "✅ Your order has been received and is currently being processed.")
    elif "error" in api_result:
        user.balance += product.price
        new_order.status = "canceled"
        msg = _L(lang,
            "❌ فشل تنفيذ الطلب وتم إعادة المبلغ لرصيدك.",
            "❌ Order failed. Amount refunded to your balance.")
        logger.error(f"Game API Error: {api_result['error']}")
    else:
        new_order.status = "pending"
        msg = _L(lang, "⏳ تم استلام طلبك وهو بانتظار المراجعة.",
                 "⏳ Your order has been received and is awaiting review.")

    await db.commit()
    await state.clear()

    g_disp = _game_display(game, lang) if game else "—"
    p_disp = _prod_display(product, lang)

    await safe_edit(callback, section_card("✅", _L(lang, "تم الطلب", "Order Placed"), [
        msg,
        _L(lang, f"📝 رقم الطلب: {new_order.id}", f"📝 Order ID: {new_order.id}"),
        _L(lang, f"🎮 اللعبة: {g_disp}", f"🎮 Game: {g_disp}"),
        _L(lang, f"📦 المنتج: {p_disp}", f"📦 Product: {p_disp}"),
        _L(lang, f"💰 الرصيد المتبقي: {fmt_price(user.balance)}", f"💰 Remaining: {fmt_price(user.balance)}")
    ]), InlineKeyboardMarkup(inline_keyboard=add_nav([], lang)))
    await callback.answer()


@router.callback_query(F.data == "my_game_orders")
async def show_my_game_orders(callback: CallbackQuery, db: AsyncSession):
    user = await get_or_create_user(db, callback.from_user.id)
    lang = user.language or "ar"
    stmt = select(GameOrder).where(GameOrder.user_id == user.id).order_by(GameOrder.created_at.desc()).limit(10)
    result = await db.execute(stmt)
    orders = result.scalars().all()

    rows = []
    if not orders:
        rows.append(_L(lang, "لا توجد طلبات سابقة.", "No previous orders."))
    else:
        for o in orders:
            status_lbl = status_label_ar(o.status) if lang == "ar" else status_label_en(o.status)
            game = await db.get(Game, o.game_id) if o.game_id else None
            product = await db.get(GameProduct, o.product_id) if o.product_id else None
            g_name = _game_display(game, lang) if game else _L(lang, "غير معروف", "Unknown")
            p_name = _prod_display(product, lang) if product else ""
            rows.append(f"ID: {o.id} | {status_lbl}")
            rows.append(f"└ 🎮 {g_name}")
            if p_name:
                rows.append(f"└ 📦 {p_name}")
            rows.append(f"└ {fmt_price(o.price)} | 🆔 {o.account_id}")
            rows.append("")

    kb = add_nav([], lang)
    nav_enter(callback.from_user.id, "my_game_orders")
    await safe_edit(callback, section_card("📋", _L(lang, "طلبات الألعاب", "Game Orders"), rows), InlineKeyboardMarkup(inline_keyboard=kb))
    await callback.answer()
