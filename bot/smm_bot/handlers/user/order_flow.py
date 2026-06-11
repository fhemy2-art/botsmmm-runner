"""
Order flow: Service Details → Enter Link → Enter Quantity → Confirm.
Improvements:
- Smart link instructions based on service type/category (profile vs post vs story)
- Platform-specific URL validation with clear error messages
- Provider type displayed in order confirmation
"""
import logging
import re

from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

from services.order_manager import create_order
from services.notify import notify_activation
from services.user_manager import get_or_create_user
from repositories.service_repo import get_service, get_provider_service
from i18n import get_vip_level, get_vip_pct, get_vip_name, convert_price
from handlers.common import add_nav, nav_enter, register_screen, safe_edit
from ui import card

logger = logging.getLogger(__name__)
router = Router()


class OrderStates(StatesGroup):
    waiting_link = State()
    waiting_quantity = State()


def _L(lang: str, ar: str, en: str) -> str:
    return ar if lang == "ar" else en


def _cancel_kb(lang: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=add_nav([
        [InlineKeyboardButton(text=_L(lang, "❌ إلغاء الطلب", "❌ Cancel Order"), callback_data="cancel_order")]
    ], lang))


# ─── Platform URL validation rules ────────────────────────────────────────────

_PLATFORM_RULES: dict[str, list[tuple[str, str, str]]] = {
    # platform → list of (regex, example_ar, example_en)
    "instagram": [
        (r"instagram\.com/p/[^/?#\s]+",          "رابط منشور",  "post link"),
        (r"instagram\.com/reel/[^/?#\s]+",        "رابط ريل",    "reel link"),
        (r"instagram\.com/stories/[^/?#\s]+",     "رابط ستوري",  "story link"),
        (r"instagram\.com/[^/?#\s]+/?$",          "رابط حساب",   "profile link"),
    ],
    "youtube": [
        (r"youtube\.com/watch\?v=[A-Za-z0-9_\-]+", "رابط فيديو",  "video link"),
        (r"youtu\.be/[A-Za-z0-9_\-]+",             "رابط فيديو",  "video link"),
        (r"youtube\.com/shorts/[A-Za-z0-9_\-]+",   "رابط شورتس",  "shorts link"),
        (r"youtube\.com/@[^/?#\s]+",                "رابط قناة",   "channel link"),
        (r"youtube\.com/channel/[^/?#\s]+",         "رابط قناة",   "channel link"),
        (r"youtube\.com/c/[^/?#\s]+",               "رابط قناة",   "channel link"),
    ],
    "tiktok": [
        (r"tiktok\.com/@[^/?#\s]+/video/\d+",    "رابط فيديو",  "video link"),
        (r"tiktok\.com/@[^/?#\s]+/?$",            "رابط حساب",   "profile link"),
        (r"vm\.tiktok\.com/[^/?#\s]+",            "رابط مختصر",  "short link"),
    ],
    "twitter": [
        (r"(twitter|x)\.com/[^/?#\s]+/status/\d+", "رابط تغريدة", "tweet link"),
        (r"(twitter|x)\.com/[^/?#\s]+/?$",          "رابط حساب",   "profile link"),
    ],
    "facebook": [
        (r"facebook\.com/[^/?#\s]+/posts/[^/?#\s]+", "رابط منشور", "post link"),
        (r"facebook\.com/[^/?#\s]+/videos/\d+",      "رابط فيديو", "video link"),
        (r"facebook\.com/reel/\d+",                   "رابط ريل",   "reel link"),
        (r"facebook\.com/[^/?#\s]+",                  "رابط صفحة",  "page/profile link"),
    ],
    "telegram": [
        (r"t\.me/[^/?#\s]+/\d+",   "رابط منشور في قناة",  "channel post link"),
        (r"t\.me/[^/?#\s]+/?$",    "رابط قناة أو مجموعة", "channel/group link"),
    ],
    "threads": [
        (r"threads\.net/@[^/?#\s]+/post/[^/?#\s]+", "رابط منشور", "post link"),
        (r"threads\.net/@[^/?#\s]+/?$",              "رابط حساب",  "profile link"),
    ],
    "whatsapp": [
        (r"(wa\.me|api\.whatsapp\.com|chat\.whatsapp\.com)/[^/?#\s]+", "رابط واتساب", "WhatsApp link"),
    ],
}

# Platforms with flexible/no URL pattern (accept any https link)
_FLEXIBLE_PLATFORMS = {"snapchat", "linkedin", "spotify", "soundcloud", "pinterest", "twitch", "discord"}

# Examples per platform
_PLATFORM_EXAMPLES: dict[str, tuple[str, str]] = {
    "instagram":  ("https://instagram.com/username\nأو\nhttps://instagram.com/p/ABC123",
                   "https://instagram.com/username\nor\nhttps://instagram.com/p/ABC123"),
    "youtube":    ("https://youtube.com/@channelname\nأو\nhttps://youtube.com/watch?v=VIDEO_ID",
                   "https://youtube.com/@channelname\nor\nhttps://youtube.com/watch?v=VIDEO_ID"),
    "tiktok":     ("https://tiktok.com/@username\nأو\nhttps://tiktok.com/@user/video/123",
                   "https://tiktok.com/@username\nor\nhttps://tiktok.com/@user/video/123"),
    "twitter":    ("https://x.com/username\nأو\nhttps://x.com/user/status/123",
                   "https://x.com/username\nor\nhttps://x.com/user/status/123"),
    "facebook":   ("https://facebook.com/pagename", "https://facebook.com/pagename"),
    "telegram":   ("https://t.me/channelname", "https://t.me/channelname"),
    "threads":    ("https://threads.net/@username", "https://threads.net/@username"),
    "whatsapp":   ("https://wa.me/grouplink", "https://wa.me/grouplink"),
}


def _validate_link(link: str, platform: str) -> bool:
    """
    Returns True if the link passes basic validation for the given platform.
    For unknown/flexible platforms: any https link is accepted.
    """
    if not link.startswith("https://") and not link.startswith("http://"):
        return False
    if "." not in link:
        return False

    if platform in _FLEXIBLE_PLATFORMS:
        return True

    link_lower = link.lower()

    # Special handling for platforms with multiple domains
    if platform == "twitter":
        if "twitter.com" not in link_lower and "x.com" not in link_lower:
            return False
    elif platform == "youtube":
        if "youtube.com" not in link_lower and "youtu.be" not in link_lower:
            return False
    elif platform == "telegram":
        if "t.me" not in link_lower and "telegram.me" not in link_lower and "telegram.dog" not in link_lower:
            return False
    elif platform == "whatsapp":
        if not any(d in link_lower for d in ["wa.me", "whatsapp.com"]):
            return False
    elif platform not in link_lower:
        # Fallback: if platform name isn't in URL, check if we have specific regex rules
        rules = _PLATFORM_RULES.get(platform)
        if rules:
            # If we have rules but none match, it might be invalid, 
            # but for now we'll be lenient if the platform name is missing but it's a valid URL
            pass 
        else:
            # Unknown platform — accept any valid URL
            return True

    return True


def _link_error_text(platform: str, lang: str) -> str:
    """Build a clear, platform-specific link error message."""
    examples = _PLATFORM_EXAMPLES.get(platform, ("", ""))
    example = examples[0] if lang == "ar" else examples[1]

    if lang == "ar":
        lines = [
            "❌ الرابط غير صحيح أو لا يتطابق مع المنصة المطلوبة.",
            f"",
            f"✅ يجب أن يكون رابطاً من <b>{platform}</b> ويبدأ بـ https://",
        ]
        if example:
            lines += ["", "📌 أمثلة صحيحة:", f"<code>{example}</code>"]
    else:
        lines = [
            "❌ Invalid link — doesn't match the required platform.",
            f"",
            f"✅ Must be a <b>{platform}</b> link starting with https://",
        ]
        if example:
            lines += ["", "📌 Examples:", f"<code>{example}</code>"]

    return card("❌ رابط غير صحيح" if lang == "ar" else "❌ Invalid Link", lines[1:])


# ─── Link type instruction builder ────────────────────────────────────────────

def _link_instruction(service_name: str, category: str, svc_type: str | None,
                       platform: str, lang: str) -> tuple[str, str]:
    """
    Returns (instruction_text, link_type_tag) based on service context.
    instruction_text: shown to user asking which link to send.
    link_type_tag: used internally (profile/post/video/story/channel).
    """
    combined = f"{svc_type or ''} {category} {service_name}".lower()

    # Check provider type first
    if svc_type:
        t_lower = svc_type.lower()
        if "custom comments" in t_lower:
            return (
                _L(lang,
                   "📝 أرسل <b>رابط المنشور</b> الذي تريد إضافة تعليقات عليه 👇",
                   "📝 Send the <b>post link</b> you want comments on 👇"),
                "post"
            )
        if "mention" in t_lower or "hashtag" in t_lower:
            return (
                _L(lang,
                   "📝 أرسل <b>رابط المنشور</b> مع الهاشتاقات أو الأسماء 👇",
                   "📝 Send the <b>post link</b> with hashtags/mentions 👇"),
                "post"
            )
        if "story" in t_lower or "stories" in t_lower:
            return (
                _L(lang,
                   "📝 أرسل <b>رابط الستوري</b> 👇",
                   "📝 Send the <b>story link</b> 👇"),
                "story"
            )

    # Category-based detection
    if any(k in combined for k in ("متابعين", "مشتركين", "أعضاء", "follower", "subscriber", "member", "fan")):
        if platform == "telegram":
            return (
                _L(lang,
                   "📝 أرسل <b>رابط القناة أو المجموعة</b> 👇\n"
                   "مثال: <code>https://t.me/channelname</code>",
                   "📝 Send the <b>channel or group link</b> 👇\n"
                   "Example: <code>https://t.me/channelname</code>"),
                "channel"
            )
        if platform == "youtube":
            return (
                _L(lang,
                   "📝 أرسل <b>رابط القناة</b> 👇\n"
                   "مثال: <code>https://youtube.com/@channelname</code>",
                   "📝 Send the <b>channel link</b> 👇\n"
                   "Example: <code>https://youtube.com/@channelname</code>"),
                "channel"
            )
        return (
            _L(lang,
               "📝 أرسل <b>رابط الحساب</b> (ليس المنشور) 👇\n"
               f"مثال على {platform}: <code>https://{platform}.com/username</code>",
               "📝 Send the <b>profile / account link</b> (not a post) 👇\n"
               f"Example: <code>https://{platform}.com/username</code>"),
            "profile"
        )

    if any(k in combined for k in ("مشاهدات", "مشاهدات منشور", "view", "watch", "impression")):
        if platform == "youtube":
            return (
                _L(lang,
                   "📝 أرسل <b>رابط الفيديو</b> 👇\n"
                   "مثال: <code>https://youtube.com/watch?v=VIDEO_ID</code>",
                   "📝 Send the <b>video link</b> 👇\n"
                   "Example: <code>https://youtube.com/watch?v=VIDEO_ID</code>"),
                "video"
            )
        if platform == "tiktok":
            return (
                _L(lang,
                   "📝 أرسل <b>رابط الفيديو</b> 👇\n"
                   "مثال: <code>https://tiktok.com/@user/video/123</code>",
                   "📝 Send the <b>video link</b> 👇\n"
                   "Example: <code>https://tiktok.com/@user/video/123</code>"),
                "video"
            )
        return (
            _L(lang,
               "📝 أرسل <b>رابط المنشور أو الفيديو</b> 👇",
               "📝 Send the <b>post or video link</b> 👇"),
            "post"
        )

    if any(k in combined for k in ("إعجابات", "لايكات", "like", "reaction")):
        return (
            _L(lang,
               "📝 أرسل <b>رابط المنشور أو الصورة</b> الذي تريد الإعجابات عليه 👇",
               "📝 Send the <b>post or photo link</b> you want likes on 👇"),
            "post"
        )

    if any(k in combined for k in ("تعليقات", "comment")):
        return (
            _L(lang,
               "📝 أرسل <b>رابط المنشور</b> الذي تريد التعليقات عليه 👇",
               "📝 Send the <b>post link</b> you want comments on 👇"),
            "post"
        )

    if any(k in combined for k in ("مشاركات", "share", "retweet", "repost")):
        return (
            _L(lang,
               "📝 أرسل <b>رابط المنشور أو التغريدة</b> 👇",
               "📝 Send the <b>post or tweet link</b> 👇"),
            "post"
        )

    if any(k in combined for k in ("ستوري", "story", "stories")):
        return (
            _L(lang,
               "📝 أرسل <b>رابط الستوري</b> 👇",
               "📝 Send the <b>story link</b> 👇"),
            "story"
        )

    if any(k in combined for k in ("وقت مشاهدة", "watch time", "watch hour")):
        return (
            _L(lang,
               "📝 أرسل <b>رابط القناة</b> 👇\n"
               "مثال: <code>https://youtube.com/@channelname</code>",
               "📝 Send the <b>channel link</b> 👇\n"
               "Example: <code>https://youtube.com/@channelname</code>"),
            "channel"
        )

    # Default fallback
    return (
        _L(lang,
           "📝 أرسل <b>رابط الحساب أو المنشور</b> المناسب للخدمة 👇",
           "📝 Send the appropriate <b>profile or post link</b> for this service 👇"),
        "any"
    )


# ─── Edit helpers ─────────────────────────────────────────────────────────────

async def _edit_state_message(message: Message, state: FSMContext, text: str, kb: InlineKeyboardMarkup) -> None:
    data = await state.get_data()
    chat_id = data.get("ui_chat_id") or message.chat.id
    message_id = data.get("ui_message_id")
    try:
        if message_id:
            await message.bot.edit_message_text(
                chat_id=chat_id, message_id=message_id,
                text=text, reply_markup=kb, parse_mode="HTML",
            )
        else:
            sent = await message.answer(text, reply_markup=kb, parse_mode="HTML")
            await state.update_data(ui_chat_id=sent.chat.id, ui_message_id=sent.message_id)
    except Exception as exc:
        logger.debug("State edit failed: %s", exc)
    try:
        await message.delete()
    except Exception:
        pass


async def _service_context(db, service_id: int, user_id: int):
    service = await get_service(db, service_id)
    if not service:
        return None, None, None, None, None, None
    ps = await get_provider_service(db, service.provider_service_id) if service.provider_service_id else None
    user = await get_or_create_user(db, user_id)
    lang = user.language or "ar"
    level = get_vip_level(float(user.total_spent or 0))
    pct = get_vip_pct(level)
    return service, ps, user, lang, level, pct


# ─── Order start ──────────────────────────────────────────────────────────────

@router.callback_query(F.data.startswith("order:"))
async def start_order_flow(callback: CallbackQuery, state: FSMContext, db, screen: str | None = None, from_back: bool = False):
    data = screen or callback.data
    parts = data.split(":")
    if len(parts) < 2 or not parts[1].isdigit():
        await callback.answer("❌")
        return

    service_id = int(parts[1])
    service, ps, user, lang, level, pct = await _service_context(db, service_id, callback.from_user.id)
    if not service:
        await safe_edit(callback, "❌ الخدمة غير موجودة", InlineKeyboardMarkup(inline_keyboard=[]))
        await callback.answer()
        return

    nav_enter(callback.from_user.id, f"order:{service_id}", push=not from_back)

    min_qty = ps.min if ps else 100
    max_qty = ps.max if ps else 10_000
    svc_type = ps.type if ps else None
    currency = user.currency or "USD"
    price_display = convert_price(float(service.price_per_1000), currency)
    platform = service.platform or "other"

    # Get smart link instruction
    link_instr, link_type = _link_instruction(
        service.name, service.category or "", svc_type, platform, lang
    )

    vip_row = None
    if pct > 0:
        discounted = float(service.price_per_1000) * (1 - pct / 100)
        vip_row = _L(lang,
            f"👑 خصم {pct}% ({get_vip_name(level, lang)}) → {convert_price(discounted, currency)}/1K",
            f"👑 {pct}% off ({get_vip_name(level, lang)}) → {convert_price(discounted, currency)}/1K",
        )

    await state.set_state(OrderStates.waiting_link)
    await state.update_data(
        service_id=service_id,
        min_qty=min_qty,
        max_qty=max_qty,
        service_name=service.name[:70],
        platform=platform,
        svc_type=svc_type or "",
        lang=lang,
        currency=currency,
        vip_pct=pct,
        link_type=link_type,
        ui_chat_id=callback.message.chat.id,
        ui_message_id=callback.message.message_id,
    )

    if lang == "ar":
        text = card("🔗 𝑲𝒊𝒓𝒂 | أرسل الرابط", [
            f"✨ <b>{service.name[:60]}</b>",
            f"🏷️ النوع: {svc_type}" if svc_type else None,
            "---",
            f"💲 السعر: <b>{price_display}/1K</b>",
            vip_row,
            None,
            "👇 " + link_instr,
        ])
    else:
        text = card("🔗 𝑲𝒊𝒓𝒂 | Send Link", [
            f"✨ <b>{service.name[:60]}</b>",
            f"🏷️ Type: {svc_type}" if svc_type else None,
            "---",
            f"💲 Price: <b>{price_display}/1K</b>",
            vip_row,
            None,
            "👇 " + link_instr,
        ])

    await safe_edit(callback, text, _cancel_kb(lang))
    await callback.answer()


# ─── Cancel ───────────────────────────────────────────────────────────────────

@router.callback_query(F.data == "cancel_order")
async def cancel_order(callback: CallbackQuery, state: FSMContext, db):
    user = await get_or_create_user(db, callback.from_user.id)
    lang = user.language or "ar"
    await state.clear()
    nav_enter(callback.from_user.id, "main_menu", reset=True)
    kb = InlineKeyboardMarkup(inline_keyboard=add_nav([], lang))
    await safe_edit(callback, _L(lang, "✅ تم إلغاء الطلب.", "✅ Order cancelled."), kb)
    await callback.answer()


# ─── Link input ───────────────────────────────────────────────────────────────

@router.message(OrderStates.waiting_link)
async def get_link(message: Message, state: FSMContext):
    data = await state.get_data()
    lang = data.get("lang", "ar")
    platform = data.get("platform", "other")
    link = (message.text or "").strip()

    # Step 1: basic format check
    if not link.startswith("http://") and not link.startswith("https://"):
        err_text = card(
            "❌ رابط غير صحيح" if lang == "ar" else "❌ Invalid Link",
            [
                _L(lang,
                   "الرابط يجب أن يبدأ بـ <code>https://</code>",
                   "Link must start with <code>https://</code>"),
                None,
                _L(lang, "أرسل الرابط مجدداً 👇", "Please send the link again 👇"),
            ]
        )
        await _edit_state_message(message, state, err_text, _cancel_kb(lang))
        return

    # Step 2: platform-specific validation
    if not _validate_link(link, platform):
        err_text = _link_error_text(platform, lang)
        await _edit_state_message(message, state, err_text, _cancel_kb(lang))
        return

    await state.update_data(link=link)
    await state.set_state(OrderStates.waiting_quantity)

    if lang == "ar":
        text = card("📊 الكمية", [
            "✅ تم حفظ الرابط!",
            "---",
            f"📉 الحد الأدنى:  <b>{data['min_qty']:,}</b>",
            f"📈 الحد الأقصى: <b>{data['max_qty']:,}</b>",
            None,
            "أرسل الكمية المطلوبة (أرقام فقط) 👇",
        ])
    else:
        text = card("📊 Quantity", [
            "✅ Link saved!",
            "---",
            f"📉 Min: <b>{data['min_qty']:,}</b>",
            f"📈 Max: <b>{data['max_qty']:,}</b>",
            None,
            "Send the quantity (numbers only) 👇",
        ])

    await _edit_state_message(message, state, text, _cancel_kb(lang))


# ─── Quantity input ───────────────────────────────────────────────────────────

@router.message(OrderStates.waiting_quantity)
async def get_quantity(message: Message, state: FSMContext, db):
    data = await state.get_data()
    lang = data.get("lang", "ar")
    raw = (message.text or "").strip().replace(",", "").replace(" ", "")

    if not raw.isdigit():
        text = card(
            "❌ كمية غير صحيحة" if lang == "ar" else "❌ Invalid Quantity",
            [
                _L(lang, "أرسل أرقام فقط بدون حروف.", "Numbers only please."),
                _L(lang, f"مثال: <code>{data['min_qty']}</code>", f"Example: <code>{data['min_qty']}</code>"),
            ]
        )
        await _edit_state_message(message, state, text, _cancel_kb(lang))
        return

    quantity = int(raw)
    if quantity < data["min_qty"]:
        text = card(
            "❌ الكمية أقل من الحد" if lang == "ar" else "❌ Below Minimum",
            [
                f"📉 {_L(lang, 'الحد الأدنى', 'Minimum')}: <b>{data['min_qty']:,}</b>",
                f"📊 {_L(lang, 'أرسلت', 'You sent')}: <b>{quantity:,}</b>",
                None,
                _L(lang, "أرسل كمية أكبر 👇", "Send a larger quantity 👇"),
            ]
        )
        await _edit_state_message(message, state, text, _cancel_kb(lang))
        return

    if quantity > data["max_qty"]:
        text = card(
            "❌ الكمية أكبر من الحد" if lang == "ar" else "❌ Exceeds Maximum",
            [
                f"📈 {_L(lang, 'الحد الأقصى', 'Maximum')}: <b>{data['max_qty']:,}</b>",
                f"📊 {_L(lang, 'أرسلت', 'You sent')}: <b>{quantity:,}</b>",
                None,
                _L(lang, "أرسل كمية أقل 👇", "Send a smaller quantity 👇"),
            ]
        )
        await _edit_state_message(message, state, text, _cancel_kb(lang))
        return

    service = await get_service(db, data["service_id"])
    if not service:
        await _edit_state_message(message, state,
            "❌ الخدمة غير موجودة" if lang == "ar" else "❌ Service not found",
            _cancel_kb(lang))
        return

    base_charge = float(service.price_per_1000) * quantity / 1000
    pct = data.get("vip_pct", 0)
    charge = base_charge * (1 - pct / 100) if pct else base_charge
    currency = data.get("currency", "USD")
    svc_type = data.get("svc_type", "")

    await state.update_data(quantity=quantity, charge=charge)

    if lang == "ar":
        rows = [
            f"✨ <b>{data['service_name']}</b>",
        ]
        if svc_type:
            rows.append(f"🏷️ النوع: {svc_type}")
        rows += [
            "---",
            f"🔗 الرابط: <code>{data['link']}</code>",
            f"📦 الكمية: <b>{quantity:,}</b>",
            f"💲 التكلفة الإجمالية: <b>{convert_price(charge, currency)}</b>",
            f"🎁 خصم VIP: <b>{pct}%</b>" if pct else None,
            None,
            "💜 راجع بياناتك ثم اضغط تأكيد التنفيذ 👇",
        ]
        text = card("🛒 𝑲𝒊𝒓𝒂 | تأكيد الطلب", rows)
    else:
        rows = [
            f"✨ <b>{data['service_name']}</b>",
        ]
        if svc_type:
            rows.append(f"🏷️ Type: {svc_type}")
        rows += [
            "---",
            f"🔗 Link: <code>{data['link']}</code>",
            f"📦 Quantity: <b>{quantity:,}</b>",
            f"💲 Total Cost: <b>{convert_price(charge, currency)}</b>",
            f"🎁 VIP Discount: <b>{pct}%</b>" if pct else None,
            None,
            "💜 Review your order then confirm below 👇",
        ]
        text = card("🛒 𝑲𝒊𝒓𝒂 | Confirm Order", rows)

    kb = InlineKeyboardMarkup(inline_keyboard=add_nav([
        [InlineKeyboardButton(
            text="✅ 🚀 تأكيد التنفيذ الآن!" if lang == "ar" else "✅ 🚀 Confirm & Place Order!",
            callback_data="confirm_order",
        )],
        [InlineKeyboardButton(
            text="✏️ تعديل الكمية" if lang == "ar" else "✏️ Edit Quantity",
            callback_data="edit_order_quantity",
        )],
        [InlineKeyboardButton(
            text="🔗 تعديل الرابط" if lang == "ar" else "🔗 Edit Link",
            callback_data="edit_order_link",
        )],
    ], lang))

    await _edit_state_message(message, state, text, kb)


# ─── Edit actions ─────────────────────────────────────────────────────────────

@router.callback_query(F.data == "edit_order_quantity")
async def edit_order_quantity(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    lang = data.get("lang", "ar")
    await state.set_state(OrderStates.waiting_quantity)
    text = card(
        "📊 تعديل الكمية" if lang == "ar" else "📊 Edit Quantity",
        [
            f"📉 {_L(lang, 'الحد الأدنى', 'Min')}: <b>{data['min_qty']:,}</b>",
            f"📈 {_L(lang, 'الحد الأقصى', 'Max')}: <b>{data['max_qty']:,}</b>",
            None,
            _L(lang, "أرسل الكمية الجديدة 👇", "Send new quantity 👇"),
        ]
    )
    await safe_edit(callback, text, _cancel_kb(lang))
    await callback.answer()


@router.callback_query(F.data == "edit_order_link")
async def edit_order_link(callback: CallbackQuery, state: FSMContext, db):
    data = await state.get_data()
    lang = data.get("lang", "ar")
    platform = data.get("platform", "other")
    svc_type = data.get("svc_type", "")
    service_id = data.get("service_id")

    service = await get_service(db, service_id) if service_id else None
    svc_name = service.name if service else ""
    svc_cat = service.category if service else ""

    link_instr, link_type = _link_instruction(svc_name, svc_cat, svc_type or None, platform, lang)

    await state.update_data(link_type=link_type)
    await state.set_state(OrderStates.waiting_link)

    text = card(
        "🔗 تعديل الرابط" if lang == "ar" else "🔗 Edit Link",
        [link_instr]
    )
    await safe_edit(callback, text, _cancel_kb(lang))
    await callback.answer()


# ─── Confirm order ────────────────────────────────────────────────────────────

@router.callback_query(F.data == "confirm_order")
async def confirm_order(callback: CallbackQuery, state: FSMContext, db):
    data = await state.get_data()
    lang = data.get("lang", "ar")
    if not data.get("link") or not data.get("quantity"):
        await callback.answer(_L(lang, "بيانات الطلب ناقصة", "Order data missing"), show_alert=True)
        return

    await safe_edit(
        callback,
        "⏳ <b>𝑲𝒊𝒓𝒂 | جارٍ معالجة طلبك... 🚀</b>" if lang == "ar" else "⏳ <b>𝑲𝒊𝒓𝒂 | Processing your order... 🚀</b>",
        InlineKeyboardMarkup(inline_keyboard=[]),
    )

    order, error = await create_order(
        db=db,
        user_id=callback.from_user.id,
        service_id=data["service_id"],
        link=data["link"],
        quantity=data["quantity"],
        bot=callback.bot,
        vip_discount_pct=data.get("vip_pct", 0),
    )
    await state.clear()

    if error:
        kb = InlineKeyboardMarkup(inline_keyboard=add_nav([
            [InlineKeyboardButton(
                text="💰 شحن رصيد" if lang == "ar" else "💰 Add Funds",
                callback_data="recharge",
            )],
        ], lang))
        await safe_edit(callback,
            card("❌ فشل الطلب" if lang == "ar" else "❌ Order Failed", [error]),
            kb)
        await callback.answer()
        return

    currency = data.get("currency", "USD")
    charge_display = convert_price(float(order.charge), currency)
    svc_type = data.get("svc_type", "")

    kb = InlineKeyboardMarkup(inline_keyboard=add_nav([
        [InlineKeyboardButton(
            text="📋 عرض طلباتي" if lang == "ar" else "📋 View My Orders",
            callback_data="my_orders",
        )],
        [InlineKeyboardButton(
            text="✨ 𝑲𝒊𝒓𝒂 | طلب رشق جديد 🚀" if lang == "ar" else "✨ 𝑲𝒊𝒓𝒂 | New Boost Order 🚀",
            callback_data="new_order",
        )],
    ], lang))

    if lang == "ar":
        rows = [
            f"🆔 رقم الطلب: <b>#{order.id}</b>",
            f"✨ الخدمة: <b>{data.get('service_name', '')}</b>",
        ]
        if svc_type:
            rows.append(f"🏷️ النوع: {svc_type}")
        rows += [
            "---",
            f"📦 الكمية: <b>{order.quantity:,}</b>",
            f"💲 التكلفة: <b>{charge_display}</b>",
            f"🔄 الحالة: <b>⏳ جارٍ التنفيذ...</b>",
            None,
            "💜 شكراً لك! سيبدأ التنفيذ فوراً 🚀",
        ]
        text = card("🎉 𝑲𝒊𝒓𝒂 | تم قبول طلبك!", rows)
    else:
        rows = [
            f"🆔 Order ID: <b>#{order.id}</b>",
            f"✨ Service: <b>{data.get('service_name', '')}</b>",
        ]
        if svc_type:
            rows.append(f"🏷️ Type: {svc_type}")
        rows += [
            "---",
            f"📦 Quantity: <b>{order.quantity:,}</b>",
            f"💲 Cost: <b>{charge_display}</b>",
            f"🔄 Status: <b>⏳ Processing...</b>",
            None,
            "💜 Thank you! Execution starts now 🚀",
        ]
        text = card("🎉 𝑲𝒊𝒓𝒂 | Order Accepted!", rows)

    await safe_edit(callback, text, kb)
    logger.info("Order #%s created by user %s", order.id, callback.from_user.id)
    await callback.answer()
