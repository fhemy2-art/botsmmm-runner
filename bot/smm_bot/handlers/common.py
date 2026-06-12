"""
Common handlers: /start, main menu, settings, referral, stats.
All DB work goes through services/repositories — no raw SQL here.
Inline-only UI: all screens use edit_message_text to keep the chat clean.
"""
import logging
import random
from collections import defaultdict
from typing import Awaitable, Callable

from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.filters import CommandStart, Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from sqlalchemy import select, func

from services.user_manager import get_or_create_user, process_referral, sync_vip_level
from repositories.user_repo import (
    count_users, invalidate_user_cache,
    get_user_by_account_number, get_user_by_username, get_user, add_balance,
)
from decimal import Decimal
from repositories.order_repo import count_orders, count_user_orders, total_revenue
from models.user import User
from models.order import Order
from config import ADMIN_IDS, BOT_NAME, BOT_CHANNEL, SUPPORT_USERNAME, OWNER_IDS, BOT_CHANNEL_URL, ACTIVATIONS_CHANNEL_URL
from handlers.admin.services import is_admin_or_mod
from i18n import t, get_vip_level, get_vip_name, get_vip_pct, convert_price, get_currency_name
from ui import card

logger = logging.getLogger(__name__)
router = Router()

ScreenRenderer = Callable[[CallbackQuery, object, str, bool], Awaitable[None]]
NAV_STACKS: dict[int, list[str]] = defaultdict(list)


class TransferStates(StatesGroup):
    waiting_recipient = State()
    waiting_amount    = State()
    waiting_confirm   = State()


NAV_CURRENT: dict[int, str] = {}
SCREEN_RENDERERS: list[tuple[str, ScreenRenderer]] = []

# In-memory captcha store: user_id -> (correct_answer, expires_at_unix, attempts_left)
# Auto-expires after CAPTCHA_TTL seconds. Limited attempts prevent brute-force.
import time as _time

_CAPTCHA_TTL = 120          # seconds the captcha remains valid
_CAPTCHA_MAX_ATTEMPTS = 3   # wrong-answer attempts before regeneration is required
_CAPTCHA_STORE: dict[int, tuple[int, float, int]] = {}


def _captcha_cleanup() -> None:
    """Drop expired entries — keeps the store from leaking memory unboundedly."""
    now = _time.time()
    expired = [uid for uid, (_, exp, _) in _CAPTCHA_STORE.items() if exp < now]
    for uid in expired:
        _CAPTCHA_STORE.pop(uid, None)


def _captcha_get(user_id: int) -> int | None:
    """Return the correct answer if still valid, else None."""
    entry = _CAPTCHA_STORE.get(user_id)
    if not entry:
        return None
    correct, exp, attempts = entry
    if exp < _time.time() or attempts <= 0:
        _CAPTCHA_STORE.pop(user_id, None)
        return None
    return correct


def _captcha_consume_attempt(user_id: int) -> int:
    """Decrement attempts. Returns remaining attempts (may be 0)."""
    entry = _CAPTCHA_STORE.get(user_id)
    if not entry:
        return 0
    correct, exp, attempts = entry
    attempts -= 1
    if attempts <= 0:
        _CAPTCHA_STORE.pop(user_id, None)
        return 0
    _CAPTCHA_STORE[user_id] = (correct, exp, attempts)
    return attempts


def register_screen(prefix: str, renderer: ScreenRenderer) -> None:
    SCREEN_RENDERERS.append((prefix, renderer))


_NAV_MAX_STACK = 20          # حد أقصى لعمق التاريخ لكل مستخدم
_NAV_MAX_USERS = 5000        # حد أقصى لعدد المستخدمين في الذاكرة
_NAV_CLEANUP_EVERY = 2000    # تنظيف كل N عملية

_nav_op_counter = 0


def _nav_cleanup() -> None:
    """احذف المستخدمين القدامى إذا تجاوز عدد المستخدمين الحد الأقصى."""
    if len(NAV_STACKS) <= _NAV_MAX_USERS:
        return
    # احتفظ بآخر _NAV_MAX_USERS مستخدم (FIFO approximation)
    to_remove = list(NAV_STACKS.keys())[: len(NAV_STACKS) - _NAV_MAX_USERS]
    for uid in to_remove:
        NAV_STACKS.pop(uid, None)
        NAV_CURRENT.pop(uid, None)


def nav_enter(user_id: int, screen: str, *, push: bool = True, reset: bool = False) -> None:
    global _nav_op_counter
    if reset:
        NAV_STACKS[user_id].clear()
        NAV_CURRENT[user_id] = screen
        return
    current = NAV_CURRENT.get(user_id)
    if push and current and current != screen and (not NAV_STACKS[user_id] or NAV_STACKS[user_id][-1] != current):
        NAV_STACKS[user_id].append(current)
        # حد أقصى لعمق المكدس لمنع استهلاك الذاكرة
        if len(NAV_STACKS[user_id]) > _NAV_MAX_STACK:
            NAV_STACKS[user_id] = NAV_STACKS[user_id][-_NAV_MAX_STACK:]
    NAV_CURRENT[user_id] = screen
    # تنظيف دوري
    _nav_op_counter += 1
    if _nav_op_counter >= _NAV_CLEANUP_EVERY:
        _nav_op_counter = 0
        _nav_cleanup()


def nav_back_target(user_id: int) -> str:
    if NAV_STACKS[user_id]:
        previous = NAV_STACKS[user_id].pop()
        NAV_CURRENT[user_id] = previous
        return previous
    NAV_CURRENT[user_id] = "main_menu"
    return "main_menu"


def nav_row(lang: str = "ar") -> list[InlineKeyboardButton]:
    return [
        InlineKeyboardButton(text="◀ رجوع" if lang == "ar" else "◀ Back", callback_data="nav:back"),
        InlineKeyboardButton(text="⌂ الرئيسية" if lang == "ar" else "⌂ Home", callback_data="main_menu"),
    ]


def add_nav(rows: list[list[InlineKeyboardButton]], lang: str = "ar") -> list[list[InlineKeyboardButton]]:
    return rows + [nav_row(lang)]


def _sanitize_kb(kb: InlineKeyboardMarkup | None) -> InlineKeyboardMarkup | None:
    """Defensive: ensure every InlineKeyboardButton has non-empty text and a
    valid action. Telegram rejects the whole keyboard if any button has empty
    text or is missing all of (callback_data / url / web_app / login_url /
    switch_inline_query / ...). This patch replaces empty text with a single
    middle-dot and drops fully-broken buttons rather than failing the edit."""
    if kb is None or not getattr(kb, "inline_keyboard", None):
        return kb
    cleaned_rows: list[list[InlineKeyboardButton]] = []
    for row in kb.inline_keyboard:
        cleaned_row: list[InlineKeyboardButton] = []
        for btn in row:
            txt = (getattr(btn, "text", None) or "").strip()
            if not txt:
                txt = "·"
            # Confirm the button has at least one valid action.
            has_action = any([
                getattr(btn, "callback_data", None),
                getattr(btn, "url", None),
                getattr(btn, "web_app", None),
                getattr(btn, "login_url", None),
                getattr(btn, "switch_inline_query", None),
                getattr(btn, "switch_inline_query_current_chat", None),
                getattr(btn, "callback_game", None),
                getattr(btn, "pay", None),
                getattr(btn, "copy_text", None),
            ])
            if not has_action:
                # Make it a noop callback so Telegram accepts it.
                btn = InlineKeyboardButton(text=txt, callback_data="noop")
            elif txt != (btn.text or ""):
                # Rebuild with the cleaned text but keep the existing action.
                kwargs = {"text": txt}
                for attr in (
                    "callback_data", "url", "web_app", "login_url",
                    "switch_inline_query", "switch_inline_query_current_chat",
                    "callback_game", "pay", "copy_text",
                ):
                    val = getattr(btn, attr, None)
                    if val is not None:
                        kwargs[attr] = val
                btn = InlineKeyboardButton(**kwargs)
            cleaned_row.append(btn)
        if cleaned_row:
            cleaned_rows.append(cleaned_row)
    if not cleaned_rows:
        return kb
    return InlineKeyboardMarkup(inline_keyboard=cleaned_rows)


async def safe_edit(callback: CallbackQuery, text: str, kb: InlineKeyboardMarkup, parse_mode: str = "HTML") -> None:
    """Edit message text or caption. For photo messages: edit_caption only (max 950 chars)."""
    try:
        kb = _sanitize_kb(kb)
        msg = callback.message
        is_photo = bool(getattr(msg, "photo", None))
        if is_photo:
            # Photo message — only edit caption (Telegram caption limit ≈ 1024 chars)
            if len(text) <= 950:
                await msg.edit_caption(caption=text, reply_markup=kb, parse_mode=parse_mode)
            else:
                # Caption too long for this photo — edit just the keyboard
                try:
                    await msg.edit_reply_markup(reply_markup=kb)
                except Exception:
                    pass
        else:
            await msg.edit_text(text, reply_markup=kb, parse_mode=parse_mode)
    except Exception as exc:
        err = str(exc).lower()
        if "message is not modified" in err:
            return
        if "can't parse inline keyboard button" in err or "text buttons are unallowed" in err:
            try:
                await callback.message.edit_text(text, parse_mode=parse_mode)
                logger.warning("safe_edit: keyboard rejected, text-only fallback (%s)", exc)
                return
            except Exception:
                pass
        logger.error("safe_edit failed: %s", exc)


async def render_registered_screen(callback: CallbackQuery, db, screen: str, *, from_back: bool = False) -> None:
    for prefix, renderer in reversed(SCREEN_RENDERERS):
        if screen == prefix or screen.startswith(prefix):
            await renderer(callback, db, screen, from_back)
            return
    await _render_main_menu(callback, db, push=False)


# ─── Keyboard builders ────────────────────────────────────────────────────────

def build_welcome_kb(lang: str = "ar") -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = [
        [InlineKeyboardButton(text="◈ انطلق وابدأ الآن ◈" if lang=="ar" else "◈ Launch Now ◈", callback_data="main_menu")],
        [InlineKeyboardButton(text=t("instructions_btn", lang), callback_data="instructions")],
    ]
    if SUPPORT_USERNAME:
        rows.append([InlineKeyboardButton(
            text=t("support_btn", lang),
            url=f"https://t.me/{SUPPORT_USERNAME.lstrip('@')}",
        )])
    if BOT_CHANNEL:
        rows.append([InlineKeyboardButton(
            text=t("channel_btn", lang),
            url=f"https://t.me/{BOT_CHANNEL.lstrip('@')}",
        )])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def build_main_menu_kb(user_id: int, lang: str = "ar") -> InlineKeyboardMarkup:
    if lang == "ar":
        rows: list[list[InlineKeyboardButton]] = [
            # ── الخدمات الرئيسية ─────────────────────────────────────────
            [InlineKeyboardButton(text="⚡️ ❰  ابدأ طلبية الرشق الآن  ❱ ⚡️", callback_data="new_order")],
            # ── المالية ──────────────────────────────────────────────────
            [
                InlineKeyboardButton(text="💎 شحن الرصيد", callback_data="recharge"),
                InlineKeyboardButton(text="💸 تحويل الرصيد", callback_data="transfer_balance"),
            ],
            [
                InlineKeyboardButton(text="🎁 رصيد مجاني", callback_data="free_balance"),
                InlineKeyboardButton(text="📊 إحصائياتي", callback_data="my_stats"),
            ],
            # ── الألعاب ───────────────────────────────────────────────────
            [
                InlineKeyboardButton(text="🎮 شحن الألعاب", callback_data="game_topup"),
                InlineKeyboardButton(text="🏆 طلبات الألعاب", callback_data="my_game_orders"),
            ],
            # ── متجر الحسابات (فوق القنوات) ───────────────────────────────
            [InlineKeyboardButton(text="🛍️ ✦ متجر الحسابات الجاهزة ✦ 🛍️", callback_data="ready_accounts")],
            # ── إعدادات ───────────────────────────────────────────────────
            [
                InlineKeyboardButton(text="👑 عضوية VIP الذهبية", callback_data="my_vip"),
                InlineKeyboardButton(text="⚙️ إعدادات الحساب", callback_data="settings"),
            ],
            [
                InlineKeyboardButton(text="📋 الشروط والسياسات", callback_data="disclaimer"),
                InlineKeyboardButton(text="🌐 English 🇺🇸", callback_data="switch_lang"),
            ],
            [InlineKeyboardButton(text="🎧 ✦ تواصل مع الدعم الفني ✦ 🎧", callback_data="support")],
        ]
    else:
        rows = [
            # ── Main services ──────────────────────────────────────────────
            [InlineKeyboardButton(text="⚡️ ❰  Place Your Boost Order Now  ❱ ⚡️", callback_data="new_order")],
            # ── Finance ────────────────────────────────────────────────────
            [
                InlineKeyboardButton(text="💎 Add Funds", callback_data="recharge"),
                InlineKeyboardButton(text="💸 Transfer Balance", callback_data="transfer_balance"),
            ],
            [
                InlineKeyboardButton(text="🎁 Free Balance", callback_data="free_balance"),
                InlineKeyboardButton(text="📊 My Statistics", callback_data="my_stats"),
            ],
            # ── Games ──────────────────────────────────────────────────────
            [
                InlineKeyboardButton(text="🎮 Game Top-Up", callback_data="game_topup"),
                InlineKeyboardButton(text="🏆 Game Orders", callback_data="my_game_orders"),
            ],
            # ── Ready Accounts Store (above channels) ──────────────────────
            [InlineKeyboardButton(text="🛍️ ✦ Ready Accounts Store ✦ 🛍️", callback_data="ready_accounts")],
            # ── Settings ───────────────────────────────────────────────────
            [
                InlineKeyboardButton(text="👑 VIP Gold Membership", callback_data="my_vip"),
                InlineKeyboardButton(text="⚙️ Account Settings", callback_data="settings"),
            ],
            [
                InlineKeyboardButton(text="📋 Terms & Policies", callback_data="disclaimer"),
                InlineKeyboardButton(text="🌐 العربية 🇸🇦", callback_data="switch_lang"),
            ],
            [InlineKeyboardButton(text="🎧 ✦ Contact Live Support ✦ 🎧", callback_data="support")],
        ]

    # ── روابط القنوات — بعد متجر الحسابات مباشرةً (index 6) ──────────────────
    channel_row: list[InlineKeyboardButton] = []
    if BOT_CHANNEL_URL:
        channel_row.append(InlineKeyboardButton(
            text="📢 قناة البوت الرسمية" if lang == "ar" else "📢 Official Bot Channel",
            url=BOT_CHANNEL_URL,
        ))
    if ACTIVATIONS_CHANNEL_URL:
        channel_row.append(InlineKeyboardButton(
            text="⚡ قناة التفعيلات" if lang == "ar" else "⚡ Activations Channel",
            url=ACTIVATIONS_CHANNEL_URL,
        ))
    if channel_row:
        rows.insert(6, channel_row)

    if is_admin_or_mod(user_id):
        rows.append([InlineKeyboardButton(
            text="🔐 ✦ لوحة التحكم الإدارية ✦ 🔐" if lang == "ar" else "🔐 ✦ Admin Control Panel ✦ 🔐",
            callback_data="adm:panel")])

    if user_id in OWNER_IDS:
        rows.append([InlineKeyboardButton(
            text="👁 ✦ لوحة صلاحيات المالك ✦ 👁" if lang == "ar" else "👁 ✦ Owner Control Panel ✦ 👁",
            callback_data="owner:panel")])

    return InlineKeyboardMarkup(inline_keyboard=rows)


# ─── Captcha helpers ───────────────────────────────────────────────────────

def _generate_captcha(user_id: int, lang: str = "ar") -> tuple[str, InlineKeyboardMarkup]:
    """Generate a math captcha question with inline answer buttons.
    Stores the answer with a 2-minute TTL and a 3-attempt limit, and prunes
    any expired entries to bound memory usage.
    """
    _captcha_cleanup()
    a = random.randint(1, 15)
    b = random.randint(1, 15)
    correct = a + b
    _CAPTCHA_STORE[user_id] = (correct, _time.time() + _CAPTCHA_TTL, _CAPTCHA_MAX_ATTEMPTS)

    # Generate 3 wrong answers that are close to the correct one
    wrong = set()
    while len(wrong) < 3:
        w = correct + random.choice([-3, -2, -1, 1, 2, 3])
        if w != correct and w > 0:
            wrong.add(w)

    options = list(wrong) + [correct]
    random.shuffle(options)

    if lang == "ar":
        text = card("🔐 التحقق من الهوية", [
            "مرحباً بك! يرجى إثبات أنك إنسان",
            "---",
            f"❓ ما ناتج:  <b>{a} + {b} = ؟</b>",
            None,
            "اختر الإجابة الصحيحة من الأزرار أدناه:",
        ])
    else:
        text = card("🔐 Human Verification", [
            "Welcome! Please verify you are human",
            "---",
            f"❓ What is:  <b>{a} + {b} = ?</b>",
            None,
            "Choose the correct answer below:",
        ])

    buttons = [
        InlineKeyboardButton(text=str(opt), callback_data=f"captcha:{opt}")
        for opt in options
    ]
    kb = InlineKeyboardMarkup(inline_keyboard=[buttons])
    return text, kb


# ─── /start ───────────────────────────────────────────────────────────────────

@router.message(CommandStart())
async def cmd_start(message: Message, db):
    args = message.text.split()
    ref_id: int | None = None
    if len(args) > 1 and args[1].startswith("ref_"):
        try:
            ref_id = int(args[1].replace("ref_", ""))
        except ValueError:
            pass

    user = await get_or_create_user(
        db, message.from_user.id,
        username=message.from_user.username,
        first_name=message.from_user.first_name,
    )

    if ref_id:
        await process_referral(db, user, ref_id)

    lang = user.language or "ar"

    # Check if user needs captcha verification
    if not user.is_verified:
        text, kb = _generate_captcha(message.from_user.id, lang)
        await message.answer(text, reply_markup=kb, parse_mode="HTML")
        return

    # Handle Deep Links (svc_ID or game_ID)
    if len(args) > 1:
        deep_arg = args[1]
        from handlers.common import render_registered_screen

        # Send a placeholder message so we can edit it later (like a real callback)
        placeholder = await message.answer(
            "⏳ <b>جاري التحميل...</b>",
            parse_mode="HTML",
        )

        class MockCallback:
            def __init__(self, placeholder_msg, user):
                self.message = placeholder_msg
                self.from_user = user
                self.bot = placeholder_msg.bot
            async def answer(self, *args, **kwargs): pass

        mock_cb = MockCallback(placeholder, message.from_user)

        if deep_arg.startswith("svc_"):
            svc_id = deep_arg.replace("svc_", "")
            await render_registered_screen(mock_cb, db, f"sd:{svc_id}")
            return
        elif deep_arg.startswith("game_"):
            game_id = deep_arg.replace("game_", "")
            await render_registered_screen(mock_cb, db, f"gp:{game_id}")
            return

    username = message.from_user.username or message.from_user.first_name
    await message.answer(
        t("welcome", lang, name=username, bot_name=BOT_NAME),
        reply_markup=build_welcome_kb(lang),
        parse_mode="HTML",
    )


@router.callback_query(F.data.startswith("captcha:"))
async def handle_captcha(callback: CallbackQuery, db):
    user = await get_or_create_user(
        db, callback.from_user.id,
        username=callback.from_user.username,
        first_name=callback.from_user.first_name,
    )
    lang = user.language or "ar"
    answer = int(callback.data.split(":")[1])
    correct = _captcha_get(callback.from_user.id)

    if correct is None:
        # Expired or no captcha pending — regenerate.
        text, kb = _generate_captcha(callback.from_user.id, lang)
        await safe_edit(callback, text, kb)
        await callback.answer(
            "⏱ انتهت صلاحية التحقق، حاول من جديد" if lang == "ar"
            else "⏱ Captcha expired, please try again",
            show_alert=True,
        )
        return

    if answer == correct:
        # Verified successfully
        user.is_verified = True
        await db.commit()
        _CAPTCHA_STORE.pop(callback.from_user.id, None)

        if lang == "ar":
            text = card("✅ تم التحقق بنجاح", [
                "مرحباً بك في البوت!",
                "---",
                "🎉 تم التحقق من هويتك بنجاح",
                "اضغط الزر أدناه للمتابعة",
            ])
        else:
            text = card("✅ Verification Successful", [
                "Welcome to the bot!",
                "---",
                "🎉 Your identity has been verified",
                "Press the button below to continue",
            ])

        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(
                text="🏠 الدخول للبوت" if lang == "ar" else "🏠 Enter Bot",
                callback_data="main_menu",
            )]
        ])
        await safe_edit(callback, text, kb)
    else:
        # Wrong answer — consume an attempt before regenerating.
        remaining = _captcha_consume_attempt(callback.from_user.id)
        if remaining > 0:
            await callback.answer(
                f"❌ إجابة خاطئة! المحاولات المتبقية: {remaining}" if lang == "ar"
                else f"❌ Wrong answer! Attempts left: {remaining}",
                show_alert=True,
            )
            # Keep the same question — user can pick another option.
            return

        await callback.answer(
            "🔄 تم إنشاء سؤال جديد" if lang == "ar"
            else "🔄 New question generated",
            show_alert=True,
        )
        text, kb = _generate_captcha(callback.from_user.id, lang)
        await safe_edit(callback, text, kb)

    await callback.answer()


# ─── Main menu ────────────────────────────────────────────────────────────────

async def _render_main_menu(callback: CallbackQuery, db, screen: str = "main_menu", from_back: bool = False, push: bool = True) -> None:
    nav_enter(callback.from_user.id, "main_menu", reset=True)
    user = await get_or_create_user(
        db, callback.from_user.id,
        username=callback.from_user.username,
        first_name=callback.from_user.first_name,
    )
    lang = user.language or "ar"
    await sync_vip_level(db, user)

    balance = float(user.balance)
    spent = float(user.total_spent or 0)
    currency = user.currency or "USD"
    username = callback.from_user.first_name or callback.from_user.username

    level = get_vip_level(spent)
    pct = get_vip_pct(level)
    tier = get_vip_name(level, lang)

    vip_line = t("vip_line", lang, tier=tier, pct=pct) if pct > 0 else ""
    balance_str = convert_price(balance, currency)
    spent_str = convert_price(spent, currency)
    currency_name = get_currency_name(currency, lang)

    from ui import account_to_email
    raw_acc = user.account_number if user.account_number else (callback.from_user.id % 99999 + 10000)
    account_email = account_to_email(raw_acc)
    text = t(
        "menu_text", lang,
        username=username, bot_name=BOT_NAME,
        uid=callback.from_user.id,
        account_number=str(raw_acc).zfill(5),
        account_email=account_email,
        tier=tier,
        balance=balance_str, spent=spent_str,
        currency_name=currency_name,
        vip_line=vip_line,
    )
    kb = build_main_menu_kb(callback.from_user.id, lang)

    # Main menu = plain text only — if current message is a photo, delete it & send fresh text
    if getattr(callback.message, "photo", None):
        try:
            await callback.message.delete()
        except Exception:
            pass
        await callback.message.answer(text, reply_markup=kb, parse_mode="HTML")
        return

    await safe_edit(callback, text, kb)


@router.callback_query(F.data == "main_menu")
async def show_main_menu(callback: CallbackQuery, db):
    await _render_main_menu(callback, db)
    await callback.answer()


@router.callback_query(F.data == "switch_lang")
async def switch_language(callback: CallbackQuery, db):
    # 1. Answer FIRST — removes Telegram spinner immediately
    await callback.answer()

    uid = callback.from_user.id

    # 2. Read current lang directly from DB (bypass cache)
    from sqlalchemy import update as _sa_update, select as _sa_select
    result = await db.execute(_sa_select(User).where(User.id == uid))
    user = result.scalar_one_or_none()
    if not user:
        user = await get_or_create_user(db, uid)

    cur_lang = user.language or "ar"
    new_lang = "en" if cur_lang == "ar" else "ar"

    # 3. Write new lang directly via UPDATE — no ORM state issues
    await db.execute(
        _sa_update(User).where(User.id == uid).values(language=new_lang)
    )
    await db.commit()

    # 4. Nuke cache so next read gets fresh data
    invalidate_user_cache(uid)

    # 5. Build menu directly with new_lang — no DB read needed
    from services.user_manager import sync_vip_level
    # Re-fetch fresh user after commit
    result2 = await db.execute(_sa_select(User).where(User.id == uid))
    fresh_user = result2.scalar_one_or_none()
    if not fresh_user:
        await _render_main_menu(callback, db, push=False)
        return

    lang = new_lang
    balance = float(fresh_user.balance or 0)
    spent = float(fresh_user.total_spent or 0)
    currency = fresh_user.currency or "USD"
    username = callback.from_user.first_name or callback.from_user.username or "User"

    level = get_vip_level(spent)
    pct = get_vip_pct(level)
    tier = get_vip_name(level, lang)
    vip_line = t("vip_line", lang, tier=tier, pct=pct) if pct > 0 else ""
    balance_str = convert_price(balance, currency)
    spent_str = convert_price(spent, currency)
    currency_name = get_currency_name(currency, lang)

    from ui import account_to_email
    raw_acc = fresh_user.account_number if fresh_user.account_number else (uid % 99999 + 10000)
    account_email = account_to_email(raw_acc)

    text = t(
        "menu_text", lang,
        username=username, bot_name=BOT_NAME,
        uid=uid,
        account_number=str(raw_acc).zfill(5),
        account_email=account_email,
        tier=tier,
        balance=balance_str, spent=spent_str,
        currency_name=currency_name,
        vip_line=vip_line,
    )
    kb = build_main_menu_kb(uid, lang)

    # 6. Edit message — if photo delete+resend, else edit_text
    try:
        if getattr(callback.message, "photo", None):
            try:
                await callback.message.delete()
            except Exception:
                pass
            await callback.message.answer(text, reply_markup=kb, parse_mode="HTML")
        else:
            await callback.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
    except Exception as exc:
        if "message is not modified" not in str(exc).lower():
            # fallback — send new message
            try:
                await callback.message.answer(text, reply_markup=kb, parse_mode="HTML")
            except Exception:
                pass



@router.message(Command("menu"))
async def cmd_menu(message: Message, db):
    user = await get_or_create_user(db, message.from_user.id, username=message.from_user.username, first_name=message.from_user.first_name)
    lang = user.language or "ar"
    await sync_vip_level(db, user)
    vip_lvl = get_vip_level(float(user.total_spent or 0))
    tier = get_vip_name(vip_lvl, lang)
    currency = getattr(user, "currency", "USD") or "USD"
    vip_pct = get_vip_pct(vip_lvl)
    vip_line = t("vip_line", lang, tier=tier, pct=vip_pct) if vip_pct > 0 else ""
    account_number = str(user.account_number or "").zfill(5) if user.account_number else f"{message.from_user.id % 99999 + 10000:05d}"
    from ui import account_to_email as _a2e
    _raw_acc = user.account_number if user.account_number else (message.from_user.id % 99999 + 10000)
    text = t("menu_text", lang, username=message.from_user.first_name or "مستخدم", bot_name=BOT_NAME, uid=message.from_user.id, account_number=str(_raw_acc).zfill(5), account_email=_a2e(_raw_acc), tier=tier, balance=convert_price(float(user.balance or 0), currency), spent=convert_price(float(user.total_spent or 0), currency), currency_name=get_currency_name(currency, lang), vip_line=vip_line)
    await message.answer(text, reply_markup=build_main_menu_kb(message.from_user.id, lang), parse_mode="HTML")

@router.callback_query(F.data == "nav:back")
async def navigate_back(callback: CallbackQuery, db):
    screen = nav_back_target(callback.from_user.id)
    await render_registered_screen(callback, db, screen, from_back=True)
    await callback.answer()


# ─── Instructions / Disclaimer / Support ─────────────────────────────────────

@router.callback_query(F.data == "instructions")
async def show_instructions(callback: CallbackQuery, db, screen: str = "instructions", from_back: bool = False):
    nav_enter(callback.from_user.id, "instructions")
    user = await get_or_create_user(db, callback.from_user.id)
    lang = user.language or "ar"
    kb = InlineKeyboardMarkup(inline_keyboard=add_nav([], lang))
    await safe_edit(callback, t("instructions", lang), kb)
    await callback.answer()


@router.callback_query(F.data == "disclaimer")
async def show_disclaimer(callback: CallbackQuery, db, screen: str = "disclaimer", from_back: bool = False):
    nav_enter(callback.from_user.id, "disclaimer")
    user = await get_or_create_user(db, callback.from_user.id)
    lang = user.language or "ar"
    kb = InlineKeyboardMarkup(inline_keyboard=add_nav([], lang))
    await safe_edit(callback, t("disclaimer", lang), kb)
    await callback.answer()


@router.callback_query(F.data == "support")
async def show_support(callback: CallbackQuery, db, screen: str = "support", from_back: bool = False):
    nav_enter(callback.from_user.id, "support")
    # Answer immediately so button stops spinning regardless of how long get_chat takes
    await callback.answer()
    user = await get_or_create_user(db, callback.from_user.id)
    lang = user.language or "ar"

    # Fetch all owner profiles in PARALLEL with 3-second timeout each
    import asyncio as _asyncio

    async def _get_owner(owner_id):
        try:
            return await _asyncio.wait_for(callback.bot.get_chat(owner_id), timeout=3.0)
        except Exception:
            return None

    chats = await _asyncio.gather(*[_get_owner(oid) for oid in OWNER_IDS])

    owner_lines = []
    rows: list[list[InlineKeyboardButton]] = []

    for i, (owner_id, chat) in enumerate(zip(OWNER_IDS, chats), 1):
        if chat:
            display_name = chat.first_name or ""
            if getattr(chat, "last_name", None):
                display_name = f"{display_name} {chat.last_name}".strip()
            display_name = display_name or (chat.username or str(owner_id))
            tag = f"@{chat.username}" if chat.username else f"#{owner_id}"
            link = f"https://t.me/{chat.username}" if chat.username else f"tg://user?id={owner_id}"
        else:
            display_name = SUPPORT_USERNAME.lstrip("@") if SUPPORT_USERNAME else str(owner_id)
            tag = SUPPORT_USERNAME if SUPPORT_USERNAME else f"#{owner_id}"
            link = f"https://t.me/{SUPPORT_USERNAME.lstrip('@')}" if SUPPORT_USERNAME else f"tg://user?id={owner_id}"

        icons = ["👑", "⚡", "💎", "🔥", "🌟"]
        icon = icons[(i - 1) % len(icons)]

        if lang == "ar":
            owner_lines.append(
                f"{icon} <b>{display_name}</b>\n"
                f"   ◇ الأدمن {i}  ·  {tag}"
            )
            rows.append([InlineKeyboardButton(
                text=f"{icon} {display_name}  ·  الأدمن {i}",
                url=link,
            )])
        else:
            owner_lines.append(
                f"{icon} <b>{display_name}</b>\n"
                f"   ◇ Admin {i}  ·  {tag}"
            )
            rows.append([InlineKeyboardButton(
                text=f"{icon} {display_name}  ·  Admin {i}",
                url=link,
            )])

    # Fallback to SUPPORT_USERNAME if no owners resolved
    if not owner_lines and SUPPORT_USERNAME:
        support_url = f"https://t.me/{SUPPORT_USERNAME.lstrip('@')}"
        if lang == "ar":
            owner_lines.append(f"◆ <b>الأدمن</b> · {SUPPORT_USERNAME}")
            rows.append([InlineKeyboardButton(text="💬 تواصل مع الأدمن", url=support_url)])
        else:
            owner_lines.append(f"◆ <b>Admin</b> · {SUPPORT_USERNAME}")
            rows.append([InlineKeyboardButton(text="💬 Contact Admin", url=support_url)])

    rows.extend(add_nav([], lang))

    if lang == "ar":
        text = card("🎧 تواصل مع الأدمن", [
            "◆ <b>فريق الدعم والإدارة</b>",
            "---",
            *owner_lines,
            None,
            "◇ ⏰ متاح على مدار الساعة · 24/7",
            "◇ 💡 تواصل مع أي أدمن للمساعدة",
        ])
    else:
        text = card("🎧 Contact Admin", [
            "◆ <b>Support & Admin Team</b>",
            "---",
            *owner_lines,
            None,
            "◇ ⏰ Available 24/7",
            "◇ 💡 Contact any admin for help",
        ])

    await safe_edit(callback, text, InlineKeyboardMarkup(inline_keyboard=rows))
    # callback.answer() already called at the top of this handler


# ─── Free balance / Referral ──────────────────────────────────────────────────

@router.callback_query(F.data == "free_balance")
async def show_free_balance(callback: CallbackQuery, db, screen: str = "free_balance", from_back: bool = False):
    nav_enter(callback.from_user.id, "free_balance")
    user = await get_or_create_user(db, callback.from_user.id)
    lang = user.language or "ar"
    bot_info = await callback.bot.get_me()
    ref_link = f"https://t.me/{bot_info.username}?start=ref_{callback.from_user.id}"

    earned = float(user.referral_earnings or 0)
    count = user.referral_count or 0

    if lang == "ar":
        text = card("🎁 نظام الإحالات", [
            "🏆 اكسب رصيداً مجاناً!",
            "---",
            f"✅ الإحالات الناجحة: <b>{count}</b>",
            f"💵 إجمالي المكافآت: <b>{earned:.4f}$</b>",
            None,
            "🔗 رابط الإحالة:",
            f"<code>{ref_link}</code>",
            None,
            "💡 كل إحالة = رصيد مجاني! 🚀",
        ])
    else:
        text = card("🎁 Referral System", [
            "🏆 Earn free balance!",
            "---",
            f"✅ Successful referrals: <b>{count}</b>",
            f"💵 Total earned: <b>{earned:.4f}$</b>",
            None,
            "🔗 Your referral link:",
            f"<code>{ref_link}</code>",
            None,
            "💡 Each referral = free balance! 🚀",
        ])

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text="📤 مشاركة الرابط" if lang == "ar" else "📤 Share Link",
            switch_inline_query=f"{'انضم لبوت' if lang == 'ar' else 'Join'} {BOT_NAME}!\n{ref_link}",
        )],
        [InlineKeyboardButton(
            text="🚀 تجهيز إعلان" if lang == "ar" else "🚀 Prepare Ad",
            callback_data="prepare_ad",
        )],
        *add_nav([], lang),
    ])
    await safe_edit(callback, text, kb)
    await callback.answer()


@router.callback_query(F.data == "prepare_ad")
async def prepare_ad(callback: CallbackQuery, db, screen: str = "prepare_ad", from_back: bool = False):
    nav_enter(callback.from_user.id, "prepare_ad")
    user = await get_or_create_user(db, callback.from_user.id)
    lang = user.language or "ar"
    bot_info = await callback.bot.get_me()
    ref_link = f"https://t.me/{bot_info.username}?start=ref_{callback.from_user.id}"
    if lang == "ar":
        text = (
            f"🚀 <b>بوت {BOT_NAME}</b> - أفضل بوت لزيادة المتابعين!\n\n"
            "✅ زيادة متابعين انستقرام، تيكتوك، تليجرام، يوتيوب والمزيد!\n"
            f"⚡ تنفيذ تلقائي وسريع\n♻️ ضمان على جميع الخدمات\n💰 أسعار منافسة\n\n"
            f"🔗 ابدأ الآن:\n{ref_link}"
        )
    else:
        text = (
            f"🚀 <b>{BOT_NAME} Bot</b> - Best follower boost bot!\n\n"
            f"✅ Instagram, TikTok, Telegram, YouTube and more!\n"
            f"⚡ Fast & automatic\n♻️ Guaranteed\n💰 Competitive prices\n\n"
            f"🔗 Start now:\n{ref_link}"
        )
    kb = InlineKeyboardMarkup(inline_keyboard=add_nav([], lang))
    await safe_edit(callback, text, kb)
    await callback.answer()


# ─── My Stats ─────────────────────────────────────────────────────────────────

@router.callback_query(F.data == "my_stats")
async def show_user_stats(callback: CallbackQuery, db, screen: str = "my_stats", from_back: bool = False):
    nav_enter(callback.from_user.id, "my_stats")
    user = await get_or_create_user(db, callback.from_user.id)
    lang = user.language or "ar"

    user_order_count = await count_user_orders(db, callback.from_user.id)

    level = get_vip_level(float(user.total_spent or 0))
    tier = get_vip_name(level, lang)
    date_str = user.created_at.strftime("%Y-%m-%d") if user.created_at else "-"

    # Build account email from account_number
    acc_num = str(user.account_number or "").zfill(5) if user.account_number else f"{callback.from_user.id % 99999 + 10000:05d}"
    acc_email = f"kira{acc_num}@nexus.io"

    if lang == "ar":
        text = card("◈ ملف إحصائيات الحساب", [
            f"◇ 🆔 <b>المعرّف</b>    ·  <code>{callback.from_user.id}</code>",
            f"◇ 📧 <b>البريد</b>     ·  <code>{acc_email}</code>",
            "---",
            f"◆ <b>الرصيد</b>       ·  <b>{float(user.balance):.4f}$</b>",
            f"◆ <b>المصروف</b>      ·  <b>{float(user.total_spent or 0):.4f}$</b>",
            f"◆ <b>عضويتك</b>       ·  <b>{tier}</b>",
            f"◆ <b>طلباتك</b>       ·  <b>{user_order_count}</b>",
            f"◆ <b>تاريخ الانضمام</b>·  <b>{date_str}</b>",
        ])
    else:
        text = card("◈ Account Statistics", [
            f"◇ 🆔 <b>ID</b>         ·  <code>{callback.from_user.id}</code>",
            f"◇ 📧 <b>Email</b>      ·  <code>{acc_email}</code>",
            "---",
            f"◆ <b>Balance</b>       ·  <b>{float(user.balance):.4f}$</b>",
            f"◆ <b>Spent</b>         ·  <b>{float(user.total_spent or 0):.4f}$</b>",
            f"◆ <b>Level</b>         ·  <b>{tier}</b>",
            f"◆ <b>Orders</b>        ·  <b>{user_order_count}</b>",
            f"◆ <b>Joined</b>        ·  <b>{date_str}</b>",
        ])

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text="🔄 طلب تعويض" if lang == "ar" else "🔄 Request Refund",
            callback_data="request_refund",
        )],
        *add_nav([], lang),
    ])
    await safe_edit(callback, text, kb)
    await callback.answer()


# ─── Settings ─────────────────────────────────────────────────────────────────

@router.callback_query(F.data == "settings")
async def show_settings(callback: CallbackQuery, db, screen: str = "settings", from_back: bool = False):
    nav_enter(callback.from_user.id, "settings")
    user = await get_or_create_user(db, callback.from_user.id)
    lang = user.language or "ar"

    title = card("🔧 ضبط إعدادات الحساب 🔧" if lang == "ar" else "🔧 My Account Settings 🔧", [
        "اختر الإعداد الذي تريد تغييره" if lang == "ar" else "Choose a setting to change",
    ])

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text="💰 تغيير العملة" if lang == "ar" else "💰 Change Currency",
            callback_data="change_currency",
        )],
        [InlineKeyboardButton(
            text="💸 أرسل رصيدك لآخر 💸" if lang == "ar" else "💸 Transfer Balance",
            callback_data="transfer_balance",
        )],
        [InlineKeyboardButton(
            text="🔄 طلب تعويض" if lang == "ar" else "🔄 Request Refund",
            callback_data="request_refund",
        )],
        [InlineKeyboardButton(
            text="🌐 Switch to English 🇺🇸" if lang == "ar" else "🌐 التبديل للعربية 🇸🇦",
            callback_data="switch_lang",
        )],
        [InlineKeyboardButton(
            text="📊 استعلام عن طلب" if lang == "ar" else "📊 Query Order",
            callback_data="query_order",
        )],
        *add_nav([], lang),
    ])
    await safe_edit(callback, title, kb)
    await callback.answer()


@router.callback_query(F.data == "change_currency")
async def change_currency(callback: CallbackQuery, db, screen: str = "change_currency", from_back: bool = False):
    nav_enter(callback.from_user.id, "change_currency")
    user = await get_or_create_user(db, callback.from_user.id)
    lang = user.language or "ar"
    title = card(
        "💰 العملة" if lang == "ar" else "💰 Currency",
        ["اختر العملة المفضلة:" if lang == "ar" else "Choose your preferred currency:"]
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=t("currency_usd", lang), callback_data="setcur:USD")],
        [InlineKeyboardButton(text=t("currency_yer", lang), callback_data="setcur:YER")],
        [InlineKeyboardButton(text=t("currency_sar", lang), callback_data="setcur:SAR")],
        *add_nav([], lang),
    ])
    await safe_edit(callback, title, kb)
    await callback.answer()


@router.callback_query(F.data.startswith("setcur:"))
async def set_currency(callback: CallbackQuery, db):
    currency = callback.data.split(":")[1]
    if currency not in ("USD", "YER", "SAR"):
        await callback.answer("❌ عملة غير صحيحة")
        return
    user = await get_or_create_user(db, callback.from_user.id)
    lang = user.language or "ar"
    user.currency = currency
    await db.commit()
    kb = InlineKeyboardMarkup(inline_keyboard=add_nav([], lang))
    await safe_edit(callback, t("currency_changed", lang, cur=currency), kb)
    await callback.answer()


@router.callback_query(F.data == "transfer_balance")
async def transfer_balance_cb(callback: CallbackQuery, db, state: FSMContext, screen: str = "transfer_balance", from_back: bool = False):
    nav_enter(callback.from_user.id, "transfer_balance")
    user = await get_or_create_user(db, callback.from_user.id)
    lang = user.language or "ar"

    from ui import account_to_email as _a2e
    raw_acc = user.account_number if user.account_number else (callback.from_user.id % 99999 + 10000)
    acc_email = _a2e(raw_acc)
    balance = float(user.balance or 0)

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text="💸 تحويل لمستخدم آخر" if lang == "ar" else "💸 Transfer to User",
            callback_data="transfer_start",
        )],
        *add_nav([], lang),
    ])
    if lang == "ar":
        msg = card("◈ تحويل الرصيد", [
            f"💳 <b>رصيدك الحالي:</b>  <code>${balance:.4f}</code>",
            f"📧 <b>حسابك:</b>  <code>{acc_email}</code>",
            "---",
            "◆ يمكنك تحويل رصيد لأي مستخدم داخل البوت",
            "◇ أدخل رقم حساب المستقبل أو معرّفه",
            "◇ سيُخصم المبلغ من رصيدك فوراً",
        ])
    else:
        msg = card("◈ Transfer Balance", [
            f"💳 <b>Your balance:</b>  <code>${balance:.4f}</code>",
            f"📧 <b>Your account:</b>  <code>{acc_email}</code>",
            "---",
            "◆ Transfer balance to any bot user",
            "◇ Enter the recipient's account number or Telegram ID",
            "◇ Amount will be deducted from your balance immediately",
        ])
    await safe_edit(callback, msg, kb)
    await callback.answer()


@router.callback_query(F.data == "transfer_start")
async def transfer_start_cb(callback: CallbackQuery, db, state: FSMContext):
    user = await get_or_create_user(db, callback.from_user.id)
    lang = user.language or "ar"

    await state.set_state(TransferStates.waiting_recipient)
    await state.update_data(lang=lang, sender_id=callback.from_user.id)

    kb = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="❌ إلغاء" if lang == "ar" else "❌ Cancel", callback_data="transfer_cancel")
    ]])
    msg = card(
        "💸 تحويل الرصيد — الخطوة 1" if lang == "ar" else "💸 Transfer — Step 1",
        [
            "أرسل <b>رقم حساب</b> المستقبل أو <b>معرّفه</b> أو <b>يوزرنيمه</b>:" if lang == "ar"
            else "Send the recipient's <b>account number</b>, <b>Telegram ID</b>, or <b>@username</b>:",
            None,
            "مثال: <code>01001</code>  أو  <code>123456789</code>  أو  <code>@username</code>" if lang == "ar"
            else "Example: <code>01001</code>  or  <code>123456789</code>  or  <code>@username</code>",
        ]
    )
    await safe_edit(callback, msg, kb)
    await callback.answer()


@router.message(TransferStates.waiting_recipient)
async def transfer_recipient_msg(message: Message, db, state: FSMContext):
    data = await state.get_data()
    lang = data.get("lang", "ar")
    text = (message.text or "").strip()

    recipient = None
    if text.startswith("@") or (not text.lstrip("-").isdigit()):
        recipient = await get_user_by_username(db, text)
    else:
        num = int(text.lstrip("0") or "0")
        if 1000 <= num <= 99999:
            recipient = await get_user_by_account_number(db, num)
        if not recipient:
            try:
                recipient = await get_user(db, int(text))
            except (ValueError, Exception):
                pass

    if not recipient:
        kb = InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text="❌ إلغاء" if lang == "ar" else "❌ Cancel", callback_data="transfer_cancel")
        ]])
        err = card(
            "❌ لم يُعثر على مستخدم" if lang == "ar" else "❌ User Not Found",
            ["تحقق من رقم الحساب أو المعرف أو اليوزرنيم وأعد المحاولة." if lang == "ar"
             else "Check the account number, ID, or username and try again."]
        )
        await message.answer(err, reply_markup=kb, parse_mode="HTML")
        return

    if recipient.id == message.from_user.id:
        kb = InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text="❌ إلغاء" if lang == "ar" else "❌ Cancel", callback_data="transfer_cancel")
        ]])
        err = card(
            "❌ خطأ" if lang == "ar" else "❌ Error",
            ["لا يمكنك التحويل لنفسك." if lang == "ar" else "You cannot transfer to yourself."]
        )
        await message.answer(err, reply_markup=kb, parse_mode="HTML")
        return

    from ui import account_to_email as _a2e
    r_acc = _a2e(recipient.account_number) if recipient.account_number else str(recipient.id)
    r_name = recipient.first_name or recipient.username or str(recipient.id)

    await state.update_data(recipient_id=recipient.id, recipient_display=r_name, recipient_acc=r_acc)
    await state.set_state(TransferStates.waiting_amount)

    kb = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="❌ إلغاء" if lang == "ar" else "❌ Cancel", callback_data="transfer_cancel")
    ]])
    msg = card(
        "💸 تحويل — الخطوة 2" if lang == "ar" else "💸 Transfer — Step 2",
        [
            f"✅ <b>المستقبل:</b>  {r_name}" if lang == "ar" else f"✅ <b>Recipient:</b>  {r_name}",
            f"📧 <code>{r_acc}</code>",
            "---",
            "أرسل <b>المبلغ</b> بالدولار للتحويل:" if lang == "ar" else "Send the <b>amount</b> in USD to transfer:",
            "مثال: <code>5</code> أو <code>2.50</code>" if lang == "ar" else "Example: <code>5</code> or <code>2.50</code>",
        ]
    )
    await message.answer(msg, reply_markup=kb, parse_mode="HTML")


@router.message(TransferStates.waiting_amount)
async def transfer_amount_msg(message: Message, db, state: FSMContext):
    data = await state.get_data()
    lang = data.get("lang", "ar")

    try:
        amount = Decimal((message.text or "").strip().replace(",", "."))
        if amount <= 0:
            raise ValueError
    except (ValueError, Exception):
        kb = InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text="❌ إلغاء" if lang == "ar" else "❌ Cancel", callback_data="transfer_cancel")
        ]])
        err = card(
            "❌ مبلغ غير صحيح" if lang == "ar" else "❌ Invalid Amount",
            ["أرسل مبلغاً صحيحاً أكبر من صفر." if lang == "ar" else "Send a valid amount greater than zero."]
        )
        await message.answer(err, reply_markup=kb, parse_mode="HTML")
        return

    sender = await get_or_create_user(db, message.from_user.id)
    if Decimal(str(sender.balance or 0)) < amount:
        kb = InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text="❌ إلغاء" if lang == "ar" else "❌ Cancel", callback_data="transfer_cancel")
        ]])
        err = card(
            "❌ رصيد غير كافٍ" if lang == "ar" else "❌ Insufficient Balance",
            [
                f"رصيدك: <code>${float(sender.balance):.4f}</code>" if lang == "ar"
                else f"Your balance: <code>${float(sender.balance):.4f}</code>",
                f"المطلوب: <code>${float(amount):.4f}</code>" if lang == "ar"
                else f"Required: <code>${float(amount):.4f}</code>",
            ]
        )
        await message.answer(err, reply_markup=kb, parse_mode="HTML")
        return

    await state.update_data(amount=str(amount))
    await state.set_state(TransferStates.waiting_confirm)

    r_name = data.get("recipient_display", "")
    r_acc  = data.get("recipient_acc", "")
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="✅ تأكيد التحويل" if lang == "ar" else "✅ Confirm Transfer", callback_data="transfer_confirm"),
            InlineKeyboardButton(text="❌ إلغاء" if lang == "ar" else "❌ Cancel", callback_data="transfer_cancel"),
        ]
    ])
    msg = card(
        "💸 تأكيد التحويل" if lang == "ar" else "💸 Confirm Transfer",
        [
            f"👤 <b>إلى:</b>  {r_name}  ·  <code>{r_acc}</code>" if lang == "ar"
            else f"👤 <b>To:</b>  {r_name}  ·  <code>{r_acc}</code>",
            f"💵 <b>المبلغ:</b>  <code>${float(amount):.4f}</code>" if lang == "ar"
            else f"💵 <b>Amount:</b>  <code>${float(amount):.4f}</code>",
            f"💳 <b>رصيدك بعد التحويل:</b>  <code>${float(Decimal(str(sender.balance)) - amount):.4f}</code>" if lang == "ar"
            else f"💳 <b>Your balance after:</b>  <code>${float(Decimal(str(sender.balance)) - amount):.4f}</code>",
            "---",
            "⚠️ التحويل فوري وغير قابل للاسترداد." if lang == "ar"
            else "⚠️ Transfer is instant and non-refundable.",
        ]
    )
    await message.answer(msg, reply_markup=kb, parse_mode="HTML")


@router.callback_query(F.data == "transfer_confirm")
async def transfer_confirm_cb(callback: CallbackQuery, db, state: FSMContext):
    # Answer IMMEDIATELY — removes button spinner before DB work
    try:
        await callback.answer()
    except Exception:
        pass

    data = await state.get_data()
    lang         = data.get("lang", "ar")
    sender_id    = data.get("sender_id") or callback.from_user.id
    recipient_id = data.get("recipient_id")
    r_name       = data.get("recipient_display", str(recipient_id))

    try:
        amount_str = data.get("amount", "0") or "0"
        amount = Decimal(str(amount_str))
    except Exception:
        amount = Decimal("0")

    # ── Validation ────────────────────────────────────────────────────────────
    if not recipient_id or amount <= 0:
        await state.clear()
        await callback.answer(
            "❌ بيانات التحويل غير مكتملة، ابدأ من جديد." if lang == "ar"
            else "❌ Transfer data incomplete. Please start over.",
            show_alert=True,
        )
        return

    # Show processing message immediately
    try:
        await callback.message.edit_text(
            "⏳ <b>جارٍ تنفيذ التحويل...</b>" if lang == "ar" else "⏳ <b>Processing transfer...</b>",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[]),
            parse_mode="HTML",
        )
    except Exception:
        pass

    try:
        from sqlalchemy import select as _sel_tr
        # Fresh balance check — bypass cache, use current session
        _br = await db.execute(_sel_tr(User).where(User.id == sender_id))
        sender = _br.scalar_one_or_none()
        if not sender or Decimal(str(sender.balance or 0)) < amount:
            await state.clear()
            _ikb = InlineKeyboardMarkup(inline_keyboard=add_nav([], lang))
            _bal = float(sender.balance) if sender else 0.0
            _msg = card("❌ رصيد غير كافٍ" if lang == "ar" else "❌ Insufficient Balance", [
                f"رصيدك: <code>${_bal:.4f}</code>" if lang == "ar" else f"Balance: <code>${_bal:.4f}</code>",
            ])
            try:
                await callback.message.edit_text(_msg, reply_markup=_ikb, parse_mode="HTML")
            except Exception:
                await callback.message.answer(_msg, reply_markup=_ikb, parse_mode="HTML")
            return

        import uuid
        ref = f"transfer:{sender_id}:{recipient_id}:{uuid.uuid4().hex[:12]}"

        await add_balance(db, sender_id, -amount, f"تحويل إلى {r_name}", external_ref=None)
        await add_balance(
            db, recipient_id, amount,
            f"تحويل من {callback.from_user.first_name or sender_id}",
            external_ref=ref,
        )

        sender_after = await get_or_create_user(db, sender_id)

        try:
            r_lang = (await get_or_create_user(db, recipient_id)).language or "ar"
            notify_msg = (
                f"💸 <b>وصل تحويل رصيد!</b>\n"
                f"👤 من: <b>{callback.from_user.first_name or sender_id}</b>\n"
                f"💵 المبلغ: <b>${float(amount):.4f}</b>"
            ) if r_lang == "ar" else (
                f"💸 <b>Balance Transfer Received!</b>\n"
                f"👤 From: <b>{callback.from_user.first_name or sender_id}</b>\n"
                f"💵 Amount: <b>${float(amount):.4f}</b>"
            )
            await callback.bot.send_message(recipient_id, notify_msg, parse_mode="HTML")
        except Exception:
            pass

        await state.clear()

        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(
                text="🏠 القائمة الرئيسية" if lang == "ar" else "🏠 Main Menu",
                callback_data="main_menu",
            )]
        ])
        msg = card(
            "✅ تم التحويل بنجاح!" if lang == "ar" else "✅ Transfer Successful!",
            [
                f"👤 <b>إلى:</b>  {r_name}" if lang == "ar" else f"👤 <b>To:</b>  {r_name}",
                f"💵 <b>المحوَّل:</b>  <code>${float(amount):.4f}</code>" if lang == "ar" else f"💵 <b>Transferred:</b>  <code>${float(amount):.4f}</code>",
                f"💳 <b>رصيدك الجديد:</b>  <code>${float(sender_after.balance):.4f}</code>" if lang == "ar" else f"💳 <b>New balance:</b>  <code>${float(sender_after.balance):.4f}</code>",
            ]
        )
        try:
            await callback.message.edit_text(msg, reply_markup=kb, parse_mode="HTML")
        except Exception:
            try:
                await callback.message.answer(msg, reply_markup=kb, parse_mode="HTML")
            except Exception:
                pass

    except Exception as exc:
        logger.error("transfer_confirm error: %s", exc, exc_info=True)
        await state.clear()
        _err_kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(
                text="🏠 القائمة الرئيسية" if lang == "ar" else "🏠 Main Menu",
                callback_data="main_menu",
            )]
        ])
        _err_txt = (
            "❌ حدث خطأ أثناء التحويل، حاول مجدداً." if lang == "ar"
            else "❌ Transfer failed, please try again."
        )
        try:
            await callback.message.edit_text(_err_txt, reply_markup=_err_kb, parse_mode="HTML")
        except Exception:
            try:
                await callback.message.answer(_err_txt, reply_markup=_err_kb, parse_mode="HTML")
            except Exception:
                pass
    finally:
        pass  # callback.answer() already called at top of handler


@router.callback_query(F.data == "transfer_cancel")
async def transfer_cancel_cb(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    lang = data.get("lang", "ar")
    await state.clear()
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🏠 القائمة الرئيسية" if lang == "ar" else "🏠 Main Menu", callback_data="main_menu")]
    ])
    msg = "❌ تم إلغاء التحويل." if lang == "ar" else "❌ Transfer cancelled."
    await safe_edit(callback, msg, kb)
    await callback.answer()


@router.callback_query(F.data == "request_refund")
async def request_refund(callback: CallbackQuery, db, screen: str = "request_refund", from_back: bool = False):
    nav_enter(callback.from_user.id, "request_refund")
    await callback.answer()  # Answer immediately to stop spinner
    user = await get_or_create_user(db, callback.from_user.id)
    lang = user.language or "ar"
    rows: list[list[InlineKeyboardButton]] = []

    import asyncio as _asyncio2
    async def _gc2(oid):
        try:
            return await _asyncio2.wait_for(callback.bot.get_chat(oid), timeout=3.0)
        except Exception:
            return None
    _chats2 = await _asyncio2.gather(*[_gc2(oid) for oid in OWNER_IDS])

    for i, (owner_id, chat) in enumerate(zip(OWNER_IDS, _chats2), 1):
        try:
            if not chat:
                raise Exception("no chat")
            uname = f"@{chat.username}" if chat.username else (chat.first_name or str(owner_id))
            link = f"https://t.me/{chat.username}" if chat.username else f"tg://user?id={owner_id}"
        except Exception:
            uname = str(owner_id)
            link = f"tg://user?id={owner_id}"
        rows.append([InlineKeyboardButton(
            text=f"◆ {'الأدمن' if lang == 'ar' else 'Admin'} {i} · {uname}",
            url=link,
        )])

    if not rows and SUPPORT_USERNAME:
        rows.append([InlineKeyboardButton(
            text="◆ تواصل مع الأدمن" if lang == "ar" else "◆ Contact Admin",
            url=f"https://t.me/{SUPPORT_USERNAME.lstrip('@')}",
        )])

    rows.extend(add_nav([], lang))
    msg = card(
        "🔄 طلب تعويض" if lang == "ar" else "🔄 Request Refund",
        [
            "لطلب تعويض، تواصل مع أحد المالكين." if lang == "ar" else "Contact any owner to request a refund.",
        ]
    )
    await safe_edit(callback, msg, InlineKeyboardMarkup(inline_keyboard=rows))
    await callback.answer()


@router.callback_query(F.data == "query_order")
async def query_order(callback: CallbackQuery, db, screen: str = "query_order", from_back: bool = False):
    nav_enter(callback.from_user.id, "query_order")
    user = await get_or_create_user(db, callback.from_user.id)
    lang = user.language or "ar"
    kb = InlineKeyboardMarkup(inline_keyboard=add_nav([], lang))
    msg = card(
        "📊 استعلام طلب" if lang == "ar" else "📊 Query Order",
        [
            "أرسل رقم الطلب للاستعلام." if lang == "ar" else "Send the order number to query it.",
            None,
            "مثال: #123" if lang == "ar" else "Example: #123",
        ]
    )
    await safe_edit(callback, msg, kb)
    await callback.answer()


@router.callback_query(F.data == "noop")
async def noop(callback: CallbackQuery):
    await callback.answer()


register_screen("main_menu", _render_main_menu)
register_screen("instructions", show_instructions)
register_screen("disclaimer", show_disclaimer)
register_screen("support", show_support)
register_screen("free_balance", show_free_balance)
register_screen("prepare_ad", prepare_ad)
register_screen("my_stats", show_user_stats)
register_screen("settings", show_settings)
register_screen("change_currency", change_currency)
register_screen("transfer_balance", transfer_balance_cb)
register_screen("request_refund", request_refund)
register_screen("query_order", query_order)


# ─── Slash command shortcuts ──────────────────────────────────────────────────

async def _send_menu_prompt(message: Message, db) -> None:
    """Send a prompt message with the main inline menu button."""
    user = await get_or_create_user(
        db, message.from_user.id,
        username=message.from_user.username,
        first_name=message.from_user.first_name,
    )
    lang = user.language or "ar"
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text="🏠 القائمة الرئيسية" if lang == "ar" else "🏠 Main Menu",
            callback_data="main_menu",
        )]
    ])
    await message.answer(
        "👇 اضغط لفتح القائمة" if lang == "ar" else "👇 Tap to open the menu",
        reply_markup=kb,
        parse_mode="HTML",
    )


@router.message(Command("orders"))
async def cmd_orders(message: Message, db):
    user = await get_or_create_user(db, message.from_user.id,
        username=message.from_user.username, first_name=message.from_user.first_name)
    lang = user.language or "ar"
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text="📋 طلباتي" if lang == "ar" else "📋 My Orders",
            callback_data="my_orders",
        )],
        [InlineKeyboardButton(
            text="🏠 القائمة الرئيسية" if lang == "ar" else "🏠 Main Menu",
            callback_data="main_menu",
        )],
    ])
    await message.answer(
        "📋 <b>طلباتي</b>\n\nاضغط الزر أدناه لعرض طلباتك." if lang == "ar"
        else "📋 <b>My Orders</b>\n\nPress the button below to view your orders.",
        reply_markup=kb, parse_mode="HTML",
    )


@router.message(Command("recharge"))
async def cmd_recharge(message: Message, db):
    user = await get_or_create_user(db, message.from_user.id,
        username=message.from_user.username, first_name=message.from_user.first_name)
    lang = user.language or "ar"
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text="💰 شحن الرصيد" if lang == "ar" else "💰 Add Funds",
            callback_data="recharge",
        )],
        [InlineKeyboardButton(
            text="🏠 القائمة الرئيسية" if lang == "ar" else "🏠 Main Menu",
            callback_data="main_menu",
        )],
    ])
    await message.answer(
        "💰 <b>شحن الرصيد</b>\n\nاضغط الزر أدناه لشحن رصيدك." if lang == "ar"
        else "💰 <b>Add Funds</b>\n\nPress the button below to top up your balance.",
        reply_markup=kb, parse_mode="HTML",
    )


@router.message(Command("support"))
async def cmd_support(message: Message, db):
    user = await get_or_create_user(db, message.from_user.id,
        username=message.from_user.username, first_name=message.from_user.first_name)
    lang = user.language or "ar"
    rows: list[list[InlineKeyboardButton]] = []
    owner_lines = []

    for i, owner_id in enumerate(OWNER_IDS, 1):
        try:
            chat = await message.bot.get_chat(owner_id)
            uname = f"@{chat.username}" if chat.username else (chat.first_name or str(owner_id))
            link = f"https://t.me/{chat.username}" if chat.username else f"tg://user?id={owner_id}"
        except Exception:
            uname = str(owner_id)
            link = f"tg://user?id={owner_id}"

        if lang == "ar":
            owner_lines.append(f"👨‍💻 المالك {i}: {uname}")
            rows.append([InlineKeyboardButton(text=f"💬 المالك {i}: {uname}", url=link)])
        else:
            owner_lines.append(f"👨‍💻 Owner {i}: {uname}")
            rows.append([InlineKeyboardButton(text=f"💬 Owner {i}: {uname}", url=link)])

    if not owner_lines and SUPPORT_USERNAME:
        owner_lines.append(f"👨‍💻 {SUPPORT_USERNAME}")
        rows.append([InlineKeyboardButton(
            text="💬 تواصل مع الدعم" if lang == "ar" else "💬 Contact Support",
            url=f"https://t.me/{SUPPORT_USERNAME.lstrip('@')}",
        )])

    rows.append([InlineKeyboardButton(
        text="🏠 القائمة الرئيسية" if lang == "ar" else "🏠 Main Menu",
        callback_data="main_menu",
    )])

    contacts = "\n".join(owner_lines) if owner_lines else ("لا يوجد دعم متاح" if lang == "ar" else "No support available")
    await message.answer(
        f"💬 <b>{'الدعم الفني' if lang == 'ar' else 'Support'}</b>\n\n"
        f"{contacts}\n⏰ {'متاح 24/7' if lang == 'ar' else 'Available 24/7'}",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=rows),
        parse_mode="HTML",
    )


@router.message(Command("stats"))
async def cmd_stats(message: Message, db):
    user = await get_or_create_user(db, message.from_user.id,
        username=message.from_user.username, first_name=message.from_user.first_name)
    lang = user.language or "ar"
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text="📊 ملف إحصائي 📊" if lang == "ar" else "📊 My Stats",
            callback_data="my_stats",
        )],
        [InlineKeyboardButton(
            text="🏠 القائمة الرئيسية" if lang == "ar" else "🏠 Main Menu",
            callback_data="main_menu",
        )],
    ])
    await message.answer(
        "📊 <b>إحصائياتي</b>\n\nاضغط الزر لعرض إحصائيات حسابك." if lang == "ar"
        else "📊 <b>My Stats</b>\n\nPress the button to view your account stats.",
        reply_markup=kb, parse_mode="HTML",
    )


@router.message(Command("vip"))
async def cmd_vip(message: Message, db):
    user = await get_or_create_user(db, message.from_user.id,
        username=message.from_user.username, first_name=message.from_user.first_name)
    lang = user.language or "ar"
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text="👑 عضويتي VIP" if lang == "ar" else "👑 My VIP",
            callback_data="my_vip",
        )],
        [InlineKeyboardButton(
            text="🏠 القائمة الرئيسية" if lang == "ar" else "🏠 Main Menu",
            callback_data="main_menu",
        )],
    ])
    await message.answer(
        "👑 <b>عضويتي VIP</b>\n\nاضغط الزر لعرض مستوى عضويتك وخصوماتك." if lang == "ar"
        else "👑 <b>My VIP</b>\n\nPress the button to view your VIP level and discounts.",
        reply_markup=kb, parse_mode="HTML",
    )


@router.message(Command("neworder"))
async def cmd_neworder(message: Message, db):
    user = await get_or_create_user(db, message.from_user.id,
        username=message.from_user.username, first_name=message.from_user.first_name)
    lang = user.language or "ar"
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text="🚀 طلب جديد" if lang == "ar" else "🚀 New Order",
            callback_data="new_order",
        )],
        [InlineKeyboardButton(
            text="🏠 القائمة الرئيسية" if lang == "ar" else "🏠 Main Menu",
            callback_data="main_menu",
        )],
    ])
    await message.answer(
        "🚀 <b>طلب جديد</b>\n\nاضغط الزر لبدء طلب خدمة جديدة." if lang == "ar"
        else "🚀 <b>New Order</b>\n\nPress the button to start a new service order.",
        reply_markup=kb, parse_mode="HTML",
    )


@router.message(Command("balance"))
async def cmd_balance(message: Message, db):
    user = await get_or_create_user(db, message.from_user.id,
        username=message.from_user.username, first_name=message.from_user.first_name)
    lang = user.language or "ar"
    currency = user.currency or "USD"
    balance_str = convert_price(float(user.balance), currency)
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text="💰 شحن الرصيد" if lang == "ar" else "💰 Add Funds",
            callback_data="recharge",
        )],
        [InlineKeyboardButton(
            text="🏠 القائمة الرئيسية" if lang == "ar" else "🏠 Main Menu",
            callback_data="main_menu",
        )],
    ])
    text = (
        f"💳 <b>رصيدك الحالي</b>\n\n"
        f"💵 الرصيد: <b>{balance_str}</b>\n"
        f"💸 المصروف: <b>{convert_price(float(user.total_spent or 0), currency)}</b>"
    ) if lang == "ar" else (
        f"💳 <b>Your Balance</b>\n\n"
        f"💵 Balance: <b>{balance_str}</b>\n"
        f"💸 Total spent: <b>{convert_price(float(user.total_spent or 0), currency)}</b>"
    )
    await message.answer(text, reply_markup=kb, parse_mode="HTML")

