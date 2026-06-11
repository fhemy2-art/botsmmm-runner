"""Balance recharge handlers: owner, Binance Pay, Telegram Stars."""
import logging
from decimal import Decimal

from aiogram import Router, F
from aiogram.types import (
    Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton,
    LabeledPrice, PreCheckoutQuery,
)
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

from config import SUPPORT_USERNAME, BINANCE_PAY_ID, BOT_NAME, ADMIN_IDS, OWNER_IDS
from config import (
    BINANCE_API_KEY,
    BINANCE_API_SECRET,
    BINANCE_PAY_MERCHANT_ENABLED,
)
from services.user_manager import get_or_create_user, add_balance
from services.notify import notify_activation
from i18n import t
from handlers.common import add_nav, nav_enter, register_screen, safe_edit
from ui import card

logger = logging.getLogger(__name__)
router = Router()


class RechargeStates(StatesGroup):
    waiting_binance_amount = State()
    waiting_binance_confirm = State()
    waiting_binance_order_id = State()


class CustomStarsStates(StatesGroup):
    waiting_stars_amount = State()


def _L(lang: str, ar: str, en: str) -> str:
    return ar if lang == "ar" else en


def _recharge_kb(lang: str = "ar") -> InlineKeyboardMarkup:
    """Premium recharge keyboard — all payment methods."""
    if lang == "ar":
        rows = [
            # Digital / Instant
            [InlineKeyboardButton(text="💰 ◈ شحن عبر Binance Pay ◈ 💰", callback_data="recharge_binance")],
            [InlineKeyboardButton(text="⭐ ◈ نجوم تيليجرام ◈ ⭐", callback_data="recharge_stars")],
            # Mobile cards (pairs)
            [
                InlineKeyboardButton(text="💳 بطايق سوا 💳", callback_data="recharge_method:sawa"),
                InlineKeyboardButton(text="📱 بطايق موبايلي 📱", callback_data="recharge_method:mobily"),
            ],
            [
                InlineKeyboardButton(text="📲 وحدات سبأفون 📲", callback_data="recharge_method:sabafon"),
                InlineKeyboardButton(text="💸 حوالات مالية 💸", callback_data="recharge_method:transfer"),
            ],
            # New payment methods
            [InlineKeyboardButton(text="🏦 ◈ كريمي — Krimmi ◈ 🏦", callback_data="recharge_method:krimmi")],
            [InlineKeyboardButton(text="👜 ◈ محفظة جيب — Jeeb ◈ 👜", callback_data="recharge_method:jeeb")],
        ]
    else:
        rows = [
            [InlineKeyboardButton(text="💰 ◈ Binance Pay ◈ 💰", callback_data="recharge_binance")],
            [InlineKeyboardButton(text="⭐ ◈ Telegram Stars ◈ ⭐", callback_data="recharge_stars")],
            [
                InlineKeyboardButton(text="💳 Sawa Cards 💳", callback_data="recharge_method:sawa"),
                InlineKeyboardButton(text="📱 Mobily Cards 📱", callback_data="recharge_method:mobily"),
            ],
            [
                InlineKeyboardButton(text="📲 SabaFon Units 📲", callback_data="recharge_method:sabafon"),
                InlineKeyboardButton(text="💸 Money Transfer 💸", callback_data="recharge_method:transfer"),
            ],
            [InlineKeyboardButton(text="🏦 ◈ Krimmi — كريمي ◈ 🏦", callback_data="recharge_method:krimmi")],
            [InlineKeyboardButton(text="👜 ◈ Jeeb Wallet — جيب ◈ 👜", callback_data="recharge_method:jeeb")],
        ]
    rows.extend(add_nav([], lang))
    return InlineKeyboardMarkup(inline_keyboard=rows)


@router.callback_query(F.data == "recharge")
async def recharge_menu(callback: CallbackQuery, db, screen: str = "recharge", from_back: bool = False):
    nav_enter(callback.from_user.id, "recharge", push=not from_back)
    user = await get_or_create_user(db, callback.from_user.id)
    lang = user.language or "ar"

    if lang == "ar":
        text = (
            "💠  <b>𝑲𝒊𝒓𝒂 · شحن الرصيد</b>  💠\n"
            "<i>◈  اختر طريقة الدفع المناسبة  ◈</i>\n"
            "\n"
            "▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬\n"
            "︾  <b>طرق الدفع المتاحة</b>  ︾\n"
            "\n"
            "💰 <b>Binance Pay</b>  •  <code>USDT فوري ⚡</code>\n"
            "⭐ <b>نجوم تيليجرام</b>  •  <code>100⭐ = $1</code>\n"
            "💳 <b>بطايق سوا</b>  •  <code>دول الخليج</code>\n"
            "📱 <b>بطايق موبايلي</b>  •  <code>دول الخليج</code>\n"
            "📲 <b>وحدات سبأفون</b>  •  <code>اليمن</code>\n"
            "💸 <b>حوالات مالية</b>  •  <code>للتواصل</code>\n"
            "🏦 <b>كريمي Krimmi</b>  •  <code>جديد ✦</code>\n"
            "👜 <b>محفظة جيب Jeeb</b>  •  <code>جديد ✦</code>\n"
            "\n"
            "<i>◇  𝑲𝒊𝒓𝒂 · كيرا  ◇</i>\n"
            "<i>✦  NEXUS SMM PANEL  ✦</i>"
        )
    else:
        text = (
            "💠  <b>𝑲𝒊𝒓𝒂 · شحن الرصيد</b>  💠\n"
            "<i>◈  اختر طريقة الدفع المناسبة  ◈</i>\n"
            "\n"
            "▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬\n"
            "︾  <b>طرق الدفع المتاحة</b>  ︾\n"
            "\n"
            "💰 <b>Binance Pay</b>  •  <code>USDT فوري ⚡</code>\n"
            "⭐ <b>نجوم تيليجرام</b>  •  <code>100⭐ = $1</code>\n"
            "💳 <b>بطايق سوا</b>  •  <code>دول الخليج</code>\n"
            "📱 <b>بطايق موبايلي</b>  •  <code>دول الخليج</code>\n"
            "📲 <b>وحدات سبأفون</b>  •  <code>اليمن</code>\n"
            "💸 <b>حوالات مالية</b>  •  <code>للتواصل</code>\n"
            "🏦 <b>كريمي Krimmi</b>  •  <code>جديد ✦</code>\n"
            "👜 <b>محفظة جيب Jeeb</b>  •  <code>جديد ✦</code>\n"
            "\n"
            "<i>◇  𝑲𝒊𝒓𝒂 · كيرا  ◇</i>\n"
            "<i>✦  NEXUS SMM PANEL  ✦</i>"
        )
    await safe_edit(callback, text, _recharge_kb(lang))
    await callback.answer()


# ── Payment method → Owner contact ──────────────────────────────────────────

_METHOD_NAMES = {
    "sawa":    {"ar": "💳 بطايق سوا",          "en": "💳 Sawa Cards"},
    "mobily":  {"ar": "📱 بطايق موبايلي",       "en": "📱 Mobily Cards"},
    "sabafon": {"ar": "📲 وحدات سبأفون",        "en": "📲 SabaFon Units"},
    "transfer":{"ar": "💸 حوالات مالية",         "en": "💸 Money Transfer"},
    "krimmi":  {"ar": "🏦 كريمي — Krimmi",      "en": "🏦 Krimmi"},
    "jeeb":    {"ar": "👜 محفظة جيب — Jeeb",    "en": "👜 Jeeb Wallet"},
}

@router.callback_query(F.data.startswith("recharge_method:"))
async def recharge_method_contact(callback: CallbackQuery, db, screen: str = "", from_back: bool = False):
    method = callback.data.split(":")[1]
    nav_enter(callback.from_user.id, f"recharge_method:{method}")
    user = await get_or_create_user(db, callback.from_user.id)
    lang = user.language or "ar"

    method_info = _METHOD_NAMES.get(method, {"ar": method, "en": method})
    method_name = method_info["ar"] if lang == "ar" else method_info["en"]

    rows: list[list[InlineKeyboardButton]] = []
    owner_lines = []

    for i, owner_id in enumerate(OWNER_IDS, 1):
        try:
            chat = await callback.bot.get_chat(owner_id)
            display_name = chat.first_name or ""
            if getattr(chat, "last_name", None):
                display_name = f"{display_name} {chat.last_name}".strip()
            display_name = display_name or (chat.username or str(owner_id))
            tag = f"@{chat.username}" if chat.username else f"#{owner_id}"
            link = f"https://t.me/{chat.username}" if chat.username else f"tg://user?id={owner_id}"
        except Exception:
            display_name = str(owner_id)
            tag = f"#{owner_id}"
            link = f"tg://user?id={owner_id}"

        icons = ["👑", "⚡", "💎", "🔥", "🌟"]
        icon = icons[(i - 1) % len(icons)]
        label_ar = f"{icon} {display_name}  ·  الأدمن {i}"
        label_en = f"{icon} {display_name}  ·  Admin {i}"
        rows.append([InlineKeyboardButton(
            text=label_ar if lang == "ar" else label_en,
            url=link,
        )])
        if lang == "ar":
            owner_lines.append(f"{icon} <b>{display_name}</b>\n   ◇ الأدمن {i}  ·  {tag}")
        else:
            owner_lines.append(f"{icon} <b>{display_name}</b>\n   ◇ Admin {i}  ·  {tag}")

    rows.extend(add_nav([], lang))

    from ui import account_to_email as _a2e
    raw_acc = user.account_number if user.account_number else (callback.from_user.id % 99999 + 10000)
    acc_email = _a2e(raw_acc)
    acc_id = str(callback.from_user.id)

    if lang == "ar":
        text = card(f"◈ {method_name}", [
            f"🔷  <b>طريقة الدفع:</b>  {method_name}",
            "---",
            f"🆔  معرّفك  •  <code>{acc_id}</code>",
            f"📧  حسابك  •  <code>{acc_email}</code>",
            "---",
            *owner_lines,
            None,
            "◇ أرسل معرّفك أو بريدك مع المبلغ للأدمن",
            "◇ ⏰ متاح 24/7",
        ])
    else:
        text = card(f"◈ {method_name}", [
            f"🔷  <b>Payment Method:</b>  {method_name}",
            "---",
            f"🆔  Your ID  •  <code>{acc_id}</code>",
            f"📧  Account  •  <code>{acc_email}</code>",
            "---",
            *owner_lines,
            None,
            "◇ Send your ID or account email with the amount",
            "◇ ⏰ Available 24/7",
        ])
    await safe_edit(callback, text, InlineKeyboardMarkup(inline_keyboard=rows))
    await callback.answer()


@router.callback_query(F.data == "recharge_owner")
async def recharge_owner(callback: CallbackQuery, db, screen: str = "recharge_owner", from_back: bool = False):
    nav_enter(callback.from_user.id, "recharge_owner")
    user = await get_or_create_user(db, callback.from_user.id)
    lang = user.language or "ar"
    rows: list[list[InlineKeyboardButton]] = []
    owner_lines = []

    for i, owner_id in enumerate(OWNER_IDS, 1):
        try:
            chat = await callback.bot.get_chat(owner_id)
            uname = f"@{chat.username}" if chat.username else (chat.first_name or str(owner_id))
            link = f"https://t.me/{chat.username}" if chat.username else f"tg://user?id={owner_id}"
        except Exception:
            uname = str(owner_id)
            link = f"tg://user?id={owner_id}"

        label = f"👨‍💻 المالك {i}: {uname}" if lang == "ar" else f"👨‍💻 Owner {i}: {uname}"
        rows.append([InlineKeyboardButton(text=label, url=link)])
        owner_lines.append(f"📱 المالك {i}: <b>{uname}</b>" if lang == "ar" else f"📱 Owner {i}: <b>{uname}</b>")

    rows.extend(add_nav([], lang))

    if lang == "ar":
        text = card("👨‍💻 شحن عبر المالك", [
            "تواصل مباشرة مع أحد المالكين لإتمام الشحن.",
            "---",
            *owner_lines,
            None,
            "💡 أرسل المبلغ المطلوب وطريقة الدفع للمالك",
        ])
    else:
        text = card("👨‍💻 Via Owner", [
            "Contact any owner to complete your recharge.",
            "---",
            *owner_lines,
            None,
            "💡 Send the amount and payment method to the owner",
        ])
    await safe_edit(callback, text, InlineKeyboardMarkup(inline_keyboard=rows))
    await callback.answer()


# ── Binance Pay (2-Step: like smmtarget.net) ──────────────────────────────

@router.callback_query(F.data == "recharge_binance")
async def start_binance(callback: CallbackQuery, state: FSMContext, db, screen: str = "recharge_binance", from_back: bool = False):
    nav_enter(callback.from_user.id, "recharge_binance")
    user = await get_or_create_user(db, callback.from_user.id)
    lang = user.language or "ar"
    await state.set_state(RechargeStates.waiting_binance_amount)
    await state.update_data(lang=lang, ui_chat_id=callback.message.chat.id, ui_message_id=callback.message.message_id)

    if lang == "ar":
        text = card("💰 Binance Pay — الخطوة 1", [
            "أرسل المبلغ بالدولار (USDT):",
            "مثال: <code>5</code> أو <code>10.5</code>",
        ])
    else:
        text = card("💰 Binance Pay — Step 1", [
            "Send the amount in USD (USDT):",
            "Example: <code>5</code> or <code>10.5</code>",
        ])
    await safe_edit(callback, text, InlineKeyboardMarkup(inline_keyboard=add_nav([
        [InlineKeyboardButton(text="❌ إلغاء" if lang == "ar" else "❌ Cancel", callback_data="binance_cancel")]
    ], lang)))
    await callback.answer()


@router.message(RechargeStates.waiting_binance_amount)
async def binance_amount(message: Message, state: FSMContext):
    """Step 1: User enters amount → Show Binance ID and instructions."""
    data = await state.get_data()
    lang = data.get("lang", "ar")

    if message.text and message.text.strip() == "/cancel":
        await state.clear()
        return

    try:
        amount = float((message.text or "").strip().replace(",", "."))
        if amount <= 0:
            raise ValueError
    except (ValueError, AttributeError):
        text = card("❌ مبلغ غير صحيح" if lang == "ar" else "❌ Invalid Amount",
                    ["أرسل مبلغاً صحيحاً." if lang == "ar" else "Please send a valid amount."])
        await _edit_ui_message(message, state, text, lang)
        return

    await state.update_data(amount=amount, merchant_mode=False)
    await state.set_state(RechargeStates.waiting_binance_confirm)

    # Preferred mode: create Binance Pay merchant order and verify by merchantTradeNo.
    if BINANCE_PAY_MERCHANT_ENABLED and BINANCE_API_KEY and BINANCE_API_SECRET:
        from services.binance_pay_merchant import create_merchant_order

        create_result = await create_merchant_order(
            BINANCE_API_KEY,
            BINANCE_API_SECRET,
            user_id=message.from_user.id,
            amount=Decimal(str(amount)),
            currency="USDT",
        )
        if create_result.get("created"):
            await state.update_data(
                merchant_mode=True,
                merchant_trade_no=create_result.get("merchant_trade_no", ""),
                merchant_prepay_id=create_result.get("prepay_id", ""),
            )

            if lang == "ar":
                text = card("🧾 Binance Pay - طلب دفع", [
                    f"المبلغ: <b>USDT {amount}</b>",
                    "---",
                    "1. اضغط زر <b>ادفع عبر Binance</b>",
                    "2. بعد الدفع اضغط <b>تحقق الدفع الآن</b>",
                    None,
                    f"رقم الطلب: <code>{create_result.get('merchant_trade_no', '')[:30]}</code>",
                ])
            else:
                text = card("🧾 Binance Pay - Payment Order", [
                    f"Amount: <b>USDT {amount}</b>",
                    "---",
                    "1. Tap <b>Pay via Binance</b>",
                    "2. After payment, tap <b>Check payment now</b>",
                    None,
                    f"Order ref: <code>{create_result.get('merchant_trade_no', '')[:30]}</code>",
                ])

            rows = []
            checkout_url = create_result.get("checkout_url") or create_result.get("deeplink")
            if checkout_url:
                rows.append([
                    InlineKeyboardButton(
                        text="💳 ادفع عبر Binance" if lang == "ar" else "💳 Pay via Binance",
                        url=checkout_url,
                    )
                ])
            rows.extend([
                [InlineKeyboardButton(
                    text="✅ تحقق الدفع الآن" if lang == "ar" else "✅ Check payment now",
                    callback_data="binance_confirm_paid",
                )],
                [InlineKeyboardButton(
                    text="✍️ إدخال Order ID يدويًا" if lang == "ar" else "✍️ Enter Order ID manually",
                    callback_data="binance_switch_manual",
                )],
                [InlineKeyboardButton(
                    text="❌ إلغاء" if lang == "ar" else "❌ Cancel",
                    callback_data="binance_cancel",
                )],
            ])
            kb = InlineKeyboardMarkup(inline_keyboard=rows)
            await _edit_ui_message(message, state, text, lang, kb)
            return

        logger.info(
            "Binance merchant create-order failed: %s",
            create_result.get("error", "unknown"),
        )

    pay_id = BINANCE_PAY_ID or "N/A"

    if lang == "ar":
        text = card("💳 الخطوة 1 — ادفع", [
            f"<b>USDT {amount}</b>",
            "---",
            "🔹 حوّل إلى Binance ID:",
            f"<code>{pay_id}</code>",
            None,
            "📋 <b>التعليمات:</b>",
            "1. افتح تطبيق Binance",
            f"2. أرسل <b>{amount} USDT</b> إلى ID أعلاه",
            "3. بعد الدفع اضغط <b>تأكيد الدفع</b> 👇",
        ])
    else:
        text = card("💳 Step 1 — Make Payment", [
            f"<b>USDT {amount}</b>",
            "---",
            "🔹 Send to Binance ID:",
            f"<code>{pay_id}</code>",
            None,
            "📋 <b>Instructions:</b>",
            "1. Open Binance app",
            f"2. Send <b>{amount} USDT</b> to the ID above",
            "3. After payment, tap <b>Confirm payment</b> 👇",
        ])

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text="✅ تأكيد الدفع" if lang == "ar" else "✅ Confirm payment",
            callback_data="binance_confirm_paid",
        )],
        [InlineKeyboardButton(
            text="❌ إلغاء" if lang == "ar" else "❌ Cancel",
            callback_data="binance_cancel",
        )],
    ])
    await _edit_ui_message(message, state, text, lang, kb)


@router.callback_query(F.data == "binance_confirm_paid")
async def binance_confirm_paid(callback: CallbackQuery, state: FSMContext, db):
    """Step 2: confirm payment and verify (merchant mode first, then manual fallback)."""
    data = await state.get_data()
    lang = data.get("lang", "ar")
    amount = float(data.get("amount", 0) or 0)

    if data.get("merchant_mode"):
        from services.binance_pay_merchant import query_merchant_order

        merchant_trade_no = data.get("merchant_trade_no", "")
        merchant_prepay_id = data.get("merchant_prepay_id", "")
        query_result = await query_merchant_order(
            BINANCE_API_KEY,
            BINANCE_API_SECRET,
            merchant_trade_no=merchant_trade_no,
            prepay_id=merchant_prepay_id,
        )
        if query_result.get("paid"):
            # Idempotency on the merchant trade number / prepay id.
            ref = (merchant_trade_no or merchant_prepay_id or "").strip()
            user = await add_balance(
                db,
                callback.from_user.id,
                Decimal(str(amount)),
                f"Binance Pay: {ref[:30]}",
                external_ref=f"binance_merchant:{ref}" if ref else None,
            )
            kb = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🚀 طلب جديد" if lang == "ar" else "🚀 New Order", callback_data="new_order")],
                [InlineKeyboardButton(text=t("main_menu", lang), callback_data="main_menu")],
            ])
            if lang == "ar":
                text = card("✅ تم الشحن بنجاح!", [
                    f"💰 المبلغ: <b>{amount} USDT</b>",
                    f"💳 رصيدك الجديد: <b>${float(user.balance):.2f}</b>",
                    f"🧾 المرجع: <code>{(merchant_trade_no or merchant_prepay_id)[:30]}</code>",
                ])
            else:
                text = card("✅ Payment Verified!", [
                    f"💰 Amount: <b>{amount} USDT</b>",
                    f"💳 New balance: <b>${float(user.balance):.2f}</b>",
                    f"🧾 Reference: <code>{(merchant_trade_no or merchant_prepay_id)[:30]}</code>",
                ])
            await safe_edit(callback, text, kb)
            await notify_activation(callback.bot, "recharge", amount=float(amount))
            await state.clear()
            await callback.answer()
            return

        status = query_result.get("order_status", "PENDING")
        error_detail = query_result.get("error")
        if lang == "ar":
            lines = [
                f"المبلغ: <b>{amount} USDT</b>",
                f"الحالة الحالية: <b>{status}</b>",
                "إذا أتممت الدفع قبل لحظات، اضغط تحقق مرة أخرى.",
            ]
            if error_detail:
                lines.append(f"تفاصيل: <code>{str(error_detail)[:120]}</code>")
            text = card("⌛ لم يصل الدفع بعد", lines)
        else:
            lines = [
                f"Amount: <b>{amount} USDT</b>",
                f"Current status: <b>{status}</b>",
                "If you just paid, tap check again.",
            ]
            if error_detail:
                lines.append(f"Details: <code>{str(error_detail)[:120]}</code>")
            text = card("⌛ Payment not confirmed yet", lines)

        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(
                text="✅ تحقق الدفع الآن" if lang == "ar" else "✅ Check payment now",
                callback_data="binance_confirm_paid",
            )],
            [InlineKeyboardButton(
                text="✍️ إدخال Order ID يدويًا" if lang == "ar" else "✍️ Enter Order ID manually",
                callback_data="binance_switch_manual",
            )],
            [InlineKeyboardButton(
                text="❌ إلغاء" if lang == "ar" else "❌ Cancel",
                callback_data="binance_cancel",
            )],
        ])
        await safe_edit(callback, text, kb)
        await callback.answer()
        return

    await _show_manual_order_id_prompt(callback, state, amount, lang)
    await callback.answer()


@router.callback_query(F.data == "binance_switch_manual")
async def binance_switch_manual(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    lang = data.get("lang", "ar")
    amount = float(data.get("amount", 0) or 0)
    await state.update_data(merchant_mode=False)
    await _show_manual_order_id_prompt(callback, state, amount, lang)
    await callback.answer()


async def _show_manual_order_id_prompt(
    callback: CallbackQuery,
    state: FSMContext,
    amount: float,
    lang: str,
) -> None:
    pay_id = BINANCE_PAY_ID or "N/A"
    await state.set_state(RechargeStates.waiting_binance_order_id)

    if lang == "ar":
        text = card("🔎 الخطوة 2 — تحقق من الدفع", [
            f"المبلغ: <b>USDT {amount}</b>  |  Binance ID: <b>{pay_id}</b>",
            "---",
            "أدخل <b>Order ID</b> من Binance 👇",
            None,
            "📋 <b>كيف تحصل عليه:</b>",
            "1. افتح تفاصيل الدفع في حسابك على Binance",
            "2. انسخ <b>Order ID</b>",
            "3. الصقه هنا ثم أرسل",
        ])
    else:
        text = card("🔎 Step 2 — Verify Payment", [
            f"Amount: <b>USDT {amount}</b>  |  Binance ID: <b>{pay_id}</b>",
            "---",
            "Enter your <b>Binance Order ID</b> 👇",
            None,
            "📋 <b>How to find it:</b>",
            "1. Open payment details in your Binance account",
            "2. Copy the <b>Order ID</b>",
            "3. Paste it here and send",
        ])

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text="❌ إلغاء" if lang == "ar" else "❌ Cancel",
            callback_data="binance_cancel",
        )],
    ])
    await safe_edit(callback, text, kb)


@router.message(RechargeStates.waiting_binance_order_id)
async def binance_order_id(message: Message, state: FSMContext, db):
    """Step 2 continued: Verify the Order ID and add balance."""
    data = await state.get_data()
    lang = data.get("lang", "ar")

    if message.text and message.text.strip() == "/cancel":
        await state.clear()
        return

    order_id = (message.text or "").strip()
    if not order_id:
        return

    amount = data.get("amount", 0)

    await _edit_ui_message(
        message, state,
        card("⏳ جاري التحقق..." if lang == "ar" else "⏳ Verifying...", [
            "يتم التحقق من الدفع، الرجاء الانتظار..." if lang == "ar" else "Verifying payment, please wait...",
        ]),
        lang,
    )

    error_detail = "auto_verify_disabled"

    # Try auto-verification
    if BINANCE_API_KEY and BINANCE_API_SECRET:
        from services.binance_verify import verify_binance_payment
        result = await verify_binance_payment(BINANCE_API_KEY, BINANCE_API_SECRET, order_id, amount)

        if result.get("verified"):
            # Success — add balance (idempotent on the Binance order id)
            tx_id = (result.get("details") or {}).get("transaction_id") or order_id
            user = await add_balance(
                db,
                message.from_user.id,
                Decimal(str(amount)),
                f"Binance Pay: {order_id[:30]}",
                external_ref=f"binance_manual:{tx_id}",
            )
            kb = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🚀 طلب جديد" if lang == "ar" else "🚀 New Order", callback_data="new_order")],
                [InlineKeyboardButton(text=t("main_menu", lang), callback_data="main_menu")],
            ])
            if lang == "ar":
                text = card("✅ تم الشحن بنجاح!", [
                    f"💰 المبلغ: <b>{amount} USDT</b>",
                    f"💳 رصيدك الجديد: <b>${float(user.balance):.2f}</b>",
                    f"🔗 Order ID: <code>{order_id[:30]}</code>",
                ])
            else:
                text = card("✅ Payment Verified!", [
                    f"💰 Amount: <b>{amount} USDT</b>",
                    f"💳 New balance: <b>${float(user.balance):.2f}</b>",
                    f"🔗 Order ID: <code>{order_id[:30]}</code>",
                ])
            await message.bot.edit_message_text(
                chat_id=data.get("ui_chat_id") or message.chat.id,
                message_id=data.get("ui_message_id"),
                text=text, reply_markup=kb, parse_mode="HTML",
            )
            await notify_activation(message.bot, "recharge", amount=float(amount))
            await state.clear()
            return

        error_detail = result.get("error", "unknown")
        logger.info("Binance auto-verify failed: order_id=%s error=%s", order_id, error_detail)

        retryable_errors = {
            "amount_not_matched",
            "no_transactions_found",
            "order_found_but_too_old",
            "order_found_amount_mismatch",
        }
        if error_detail in retryable_errors:
            if lang == "ar":
                if error_detail == "order_found_but_too_old":
                    lines = [
                        "تم العثور على هذه المعاملة لكنها قديمة (أكثر من 24 ساعة).",
                        "يجب أن تكون المعاملة حديثة (خلال آخر 24 ساعة).",
                        "ادفع الآن وأرسل Order ID الجديد.",
                    ]
                elif error_detail == "order_found_amount_mismatch":
                    lines = [
                        "تم العثور على رقم العملية لكن المبلغ لا يطابق قيمة الشحن المطلوبة.",
                        "تأكد أن المبلغ في Binance يساوي نفس المبلغ الذي أدخلته في البوت.",
                    ]
                elif error_detail == "no_transactions_found":
                    lines = [
                        "لم يتم العثور على معاملات حديثة حتى الآن.",
                        "إذا دفعت الآن انتظر قليلاً ثم أرسل Order ID مرة أخرى.",
                    ]
                else:
                    lines = [
                        "لم يتم العثور على معاملة بهذا الرقم أو بهذا المبلغ.",
                        "تأكد من Order ID الصحيح من تطبيق Binance وأن المبلغ يطابق ما أدخلته.",
                        "أرسل Order ID الصحيح للمحاولة مرة أخرى.",
                    ]
                text = card("❌ رقم العملية غير صحيح", lines)
            else:
                if error_detail == "order_found_but_too_old":
                    lines = [
                        "Order ID was found but it is older than 24 hours.",
                        "Send a fresh payment Order ID and try again.",
                    ]
                elif error_detail == "order_found_amount_mismatch":
                    lines = [
                        "Order ID was found but amount does not match requested recharge value.",
                        "Make sure Binance amount matches the same amount entered in bot.",
                    ]
                elif error_detail == "no_transactions_found":
                    lines = [
                        "No recent transactions found yet.",
                        "If you just paid, wait a bit and send Order ID again.",
                    ]
                else:
                    lines = [
                        "No transaction found with this Order ID or amount.",
                        "Check the Order ID from Binance app and make sure the amount matches.",
                        "Send the correct Order ID to try again.",
                    ]
                text = card("❌ Incorrect Order ID", lines)

            await message.bot.edit_message_text(
                chat_id=data.get("ui_chat_id") or message.chat.id,
                message_id=data.get("ui_message_id"),
                text=text,
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(
                        text="❌ إلغاء" if lang == "ar" else "❌ Cancel",
                        callback_data="binance_cancel",
                    )],
                ]),
                parse_mode="HTML",
            )
            # Keep state so user can resend a correct order id immediately.
            await state.set_state(RechargeStates.waiting_binance_order_id)
            return

    # Manual review fallback (no API keys or verification failed)
    for admin_id in ADMIN_IDS:
        try:
            await message.bot.send_message(
                admin_id,
                f"💰 <b>طلب شحن Binance</b>\n\n"
                f"👤 {message.from_user.id} (@{message.from_user.username or 'N/A'})\n"
                f"💵 <b>{amount} USDT</b>\n"
                f"🔗 Order ID: <code>{order_id}</code>\n"
                f"{'❌ التحقق التلقائي فشل: ' + error_detail if BINANCE_API_KEY else '⚠️ التحقق التلقائي غير مفعّل'}\n\n"
                f"للموافقة: /addbal {message.from_user.id} {amount}",
                parse_mode="HTML",
            )
        except Exception:
            pass

    if lang == "ar":
        text = card("📨 تم إرسال طلبك!", [
            f"💰 المبلغ: <b>{amount} USDT</b>",
            f"🔗 Order ID: <code>{order_id[:30]}</code>",
            None,
            "⏳ جاري المراجعة — سيتم إشعارك عند التأكيد.",
        ])
    else:
        text = card("📨 Request Sent!", [
            f"💰 Amount: <b>{amount} USDT</b>",
            f"🔗 Order ID: <code>{order_id[:30]}</code>",
            None,
            "⏳ Under review — you'll be notified upon confirmation.",
        ])
    await message.bot.edit_message_text(
        chat_id=data.get("ui_chat_id") or message.chat.id,
        message_id=data.get("ui_message_id"),
        text=text,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=t("main_menu", lang), callback_data="main_menu")]
        ]),
        parse_mode="HTML",
    )
    await state.clear()


@router.callback_query(F.data == "binance_cancel")
async def binance_cancel(callback: CallbackQuery, state: FSMContext, db):
    await state.clear()
    user = await get_or_create_user(db, callback.from_user.id)
    lang = user.language or "ar"
    kb = InlineKeyboardMarkup(inline_keyboard=add_nav([
        [InlineKeyboardButton(
            text="💵 شحن رصيد" if lang == "ar" else "💵 Add Funds",
            callback_data="recharge",
        )],
    ], lang))
    await safe_edit(callback, _L(lang, "❌ تم إلغاء عملية الشحن.", "❌ Payment cancelled."), kb)
    await callback.answer()


# ── Telegram Stars ─────────────────────────────────────────────────────────

@router.callback_query(F.data == "recharge_stars")
async def stars_menu(callback: CallbackQuery, db, screen: str = "recharge_stars", from_back: bool = False):
    nav_enter(callback.from_user.id, "recharge_stars")
    user = await get_or_create_user(db, callback.from_user.id)
    lang = user.language or "ar"
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="⭐ 50  ($0.50)", callback_data="stars:50"),
            InlineKeyboardButton(text="⭐ 100 ($1.00)", callback_data="stars:100"),
        ],
        [
            InlineKeyboardButton(text="⭐ 250 ($2.50)", callback_data="stars:250"),
            InlineKeyboardButton(text="⭐ 500 ($5.00)", callback_data="stars:500"),
        ],
        [InlineKeyboardButton(text="⭐ 1000 ($10.00)", callback_data="stars:1000")],
        [InlineKeyboardButton(
            text="✏️ مبلغ آخر" if lang == "ar" else "✏️ Custom amount",
            callback_data="stars_custom",
        )],
        *add_nav([], lang),
    ])
    if lang == "ar":
        text = card("⭐️ نجوم تيليجرام", [
            "100 نجمة = 1.00$",
            "---",
            "اختر عدد النجوم:",
        ])
    else:
        text = card("⭐️ Telegram Stars", [
            "100 stars = $1.00",
            "---",
            "Choose star amount:",
        ])
    await safe_edit(callback, text, kb)
    await callback.answer()


@router.callback_query(F.data == "stars_custom")
async def stars_custom(callback: CallbackQuery, state: FSMContext, db, screen: str = "stars_custom", from_back: bool = False):
    nav_enter(callback.from_user.id, "stars_custom")
    user = await get_or_create_user(db, callback.from_user.id)
    lang = user.language or "ar"
    await state.set_state(CustomStarsStates.waiting_stars_amount)
    await state.update_data(lang=lang, ui_chat_id=callback.message.chat.id, ui_message_id=callback.message.message_id)
    msg = _L(lang, "✏️ أرسل عدد النجوم المطلوب (الحد الأدنى: 1):", "✏️ Send the number of stars (min 1):")
    await safe_edit(callback, msg, InlineKeyboardMarkup(inline_keyboard=add_nav([], lang)))
    await callback.answer()


@router.message(CustomStarsStates.waiting_stars_amount)
async def custom_stars_amount(message: Message, state: FSMContext):
    data = await state.get_data()
    lang = data.get("lang", "ar")

    if message.text and message.text.strip() == "/cancel":
        await state.clear()
        return

    txt = (message.text or "").strip()
    if not txt.isdigit() or int(txt) < 1:
        await _edit_ui_message(message, state, _L(lang, "❌ يرجى إرسال رقم صحيح أكبر من 0", "❌ Invalid number"), lang)
        return

    stars = int(txt)
    await state.clear()
    await _send_stars_invoice(message, stars, lang)


@router.callback_query(F.data.startswith("stars:"))
async def send_stars_invoice(callback: CallbackQuery, db):
    user = await get_or_create_user(db, callback.from_user.id)
    lang = user.language or "ar"
    parts = callback.data.split(":")
    if len(parts) < 2 or not parts[1].isdigit():
        await callback.answer("❌")
        return
    stars = int(parts[1])
    await _send_stars_invoice(callback.message, stars, lang)
    await callback.answer()


async def _send_stars_invoice(target, stars: int, lang: str) -> None:
    amount_usd = stars / 100
    title = f"{'شحن' if lang == 'ar' else 'Recharge'} {stars} ⭐️"
    description = f"{'إضافة رصيد' if lang == 'ar' else 'Add balance'} ${amount_usd:.2f}"
    try:
        await target.answer_invoice(
            title=title,
            description=description,
            payload=f"stars_{stars}_{target.chat.id}",
            currency="XTR",
            prices=[LabeledPrice(label=f"{stars} Stars", amount=stars)],
        )
    except Exception as exc:
        await target.answer(f"❌ {'خطأ' if lang == 'ar' else 'Error'}: {exc}")


@router.pre_checkout_query()
async def process_pre_checkout(pre_checkout: PreCheckoutQuery):
    await pre_checkout.answer(ok=True)


@router.message(F.successful_payment)
async def process_payment(message: Message, db):
    payload = message.successful_payment.invoice_payload
    parts = payload.split("_")
    try:
        stars = int(parts[1])
    except (IndexError, ValueError):
        logger.error("Invalid stars payload: %s", payload)
        return

    amount = stars / 100
    # Idempotency: Telegram payment_charge_id is unique per successful payment.
    # Passing it as external_ref prevents duplicate balance credits if the same
    # successful_payment update is delivered twice (which Telegram does on retry).
    charge_id = (
        message.successful_payment.telegram_payment_charge_id
        or message.successful_payment.provider_payment_charge_id
        or f"stars_{message.from_user.id}_{message.message_id}"
    )
    external_ref = f"tg_stars:{charge_id}"
    user = await add_balance(
        db,
        message.from_user.id,
        Decimal(str(amount)),
        f"شحن نجوم: {stars} ⭐️",
        external_ref=external_ref,
    )
    lang = user.language or "ar"

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🚀 طلب جديد" if lang == "ar" else "🚀 New Order", callback_data="new_order")],
        [InlineKeyboardButton(text=t("main_menu", lang), callback_data="main_menu")],
    ])
    if lang == "ar":
        text = card("✅ تم شحن رصيدك!", [
            f"⭐️ النجوم: <b>{stars}</b>",
            f"💰 المبلغ: <b>${amount:.2f}</b>",
            f"💳 رصيدك الجديد: <b>${float(user.balance):.2f}</b>",
        ])
    else:
        text = card("✅ Balance Added!", [
            f"⭐️ Stars: <b>{stars}</b>",
            f"💰 Amount: <b>${amount:.2f}</b>",
            f"💳 New balance: <b>${float(user.balance):.2f}</b>",
        ])
    await message.answer(text, reply_markup=kb, parse_mode="HTML")
    await notify_activation(message.bot, "recharge", amount=float(amount))
    logger.info("Stars payment: user=%s stars=%s amount=%s", message.from_user.id, stars, amount)


async def _edit_ui_message(message: Message, state: FSMContext, text: str, lang: str, kb: InlineKeyboardMarkup | None = None) -> None:
    data = await state.get_data()
    try:
        await message.bot.edit_message_text(
            chat_id=data.get("ui_chat_id") or message.chat.id,
            message_id=data.get("ui_message_id"),
            text=text,
            reply_markup=kb or InlineKeyboardMarkup(inline_keyboard=add_nav([], lang)),
            parse_mode="HTML",
        )
    except Exception as exc:
        logger.debug("Recharge screen edit failed: %s", exc)
    try:
        await message.delete()
    except Exception:
        pass


register_screen("recharge", recharge_menu)
register_screen("recharge_owner", recharge_owner)
register_screen("recharge_stars", stars_menu)


