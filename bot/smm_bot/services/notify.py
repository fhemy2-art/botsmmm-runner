"""
╔══════════════════════════╗
║  NEXUS Notify Engine     ║
║  Elite channel alerts    ║
╚══════════════════════════╝
Activation notifications — NEXUS-styled alerts to the activations channel.
"""
import logging
from datetime import datetime, timezone, timedelta
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from config import ACTIVATIONS_CHANNEL, BOT_CHANNEL_URL

logger = logging.getLogger(__name__)

_BAGHDAD_TZ = timezone(timedelta(hours=3))

_VIP_LABELS = {
    0: "◇ عادي",
    1: "◈ فضي",
    2: "◆ ذهبي",
    3: "◆◆ بلاتيني",
}

_PLATFORM_EMOJIS = {
    "instagram":  "📸", "youtube":  "🎬", "tiktok":    "🎵",
    "twitter":    "💙", "facebook": "📘", "telegram":  "🤖",
    "threads":    "🔗", "snapchat": "👻", "whatsapp":  "💚",
    "spotify":    "🎧", "linkedin": "💼", "discord":   "🎮",
    "twitch":     "📺", "pinterest":"📌",
}

_PLATFORM_NAMES = {
    "instagram":  "إنستقرام",  "youtube":   "يوتيوب",
    "tiktok":     "تيك توك",   "twitter":   "تويتر X",
    "facebook":   "فيسبوك",    "telegram":  "تيليجرام",
    "threads":    "ثريدز",     "snapchat":  "سناب شات",
    "whatsapp":   "واتساب",    "spotify":   "سبوتيفاي",
    "linkedin":   "لينكدإن",   "discord":   "ديسكورد",
    "twitch":     "تويتش",     "pinterest": "بنترست",
}


def mask_user_id(uid: int | None) -> str:
    if not uid:
        return "●●●●●●"
    s = str(uid)
    if len(s) <= 4:
        return s[:1] + "●●●●" + s[-1:]
    return s[:2] + "●●●●" + s[-2:]


def mask_link(link: str | None) -> str:
    if not link:
        return "●●●●"
    clean = link
    for prefix in ("https://", "http://", "www."):
        if clean.lower().startswith(prefix):
            clean = clean[len(prefix):]
    visible = min(18, len(clean))
    if visible >= len(clean):
        visible = max(6, len(clean) - 4)
    return clean[:visible] + "●●●●"


def _detect_service_type(service_name: str, category: str) -> str:
    combined = f"{service_name} {category}".lower()
    if any(k in combined for k in ("متابع", "follower", "member", "أعضاء", "subscriber")):
        return "👥 متابعين"
    if any(k in combined for k in ("لايك", "like", "إعجاب", "reaction")):
        return "❤️ لايكات"
    if any(k in combined for k in ("مشاهد", "view", "watch", "impression")):
        return "👁 مشاهدات"
    if any(k in combined for k in ("تعليق", "comment")):
        return "💬 تعليقات"
    if any(k in combined for k in ("مشارك", "share", "retweet", "repost")):
        return "📤 مشاركات"
    if any(k in combined for k in ("ستوري", "story", "stories")):
        return "⭐ مشاهدات ستوري"
    if any(k in combined for k in ("save", "حفظ", "bookmark")):
        return "🔖 حفظ"
    return "◆ خدمة SMM"


def _smart_price(amount: float | None) -> str:
    if amount is None:
        return "$—"
    if amount == 0:
        return "$0.00"
    if amount >= 1:
        return f"${amount:.2f}"
    if amount >= 0.01:
        return f"${amount:.4f}".rstrip('0').rstrip('.')
    return f"${amount:.6f}".rstrip('0').rstrip('.')


async def notify_activation(
    bot,
    event_type: str,
    amount: float | None = None,
    service: str | None = None,
    order_id: int | str | None = None,
    user_id: int | None = None,
    service_id: int | None = None,
    quantity: int | None = None,
    link: str | None = None,
    platform: str | None = None,
    category: str | None = None,
    vip_level: int = 0,
) -> None:
    channel = f"@{(ACTIVATIONS_CHANNEL or 'TBEKTK').lstrip('@')}"
    bot_info = await bot.get_me()
    bot_username = bot_info.username
    now = datetime.now(_BAGHDAD_TZ).strftime("%Y/%m/%d  %I:%M %p")

    if event_type == "order_received":
        service_name = service or "خدمة SMM"
        plat = (platform or "").lower()
        cat = category or ""
        svc_type = _detect_service_type(service_name, cat)
        plat_name = _PLATFORM_NAMES.get(plat, plat.capitalize() if plat else "غير محدد")
        plat_emoji = _PLATFORM_EMOJIS.get(plat, "🌐")
        m_uid = mask_user_id(user_id)
        m_link = mask_link(link)
        qty_display = f"{quantity:,}" if quantity else "—"
        price_display = _smart_price(amount)
        vip_tag = _VIP_LABELS.get(vip_level, "◇ عادي")
        order_url = f"https://t.me/{bot_username}?start=svc_{service_id}" if service_id else BOT_CHANNEL_URL

        text = (
            "╔══════════════════════════╗\n"
            "║  ◈  <b>𝑲𝒊𝒓𝒂 · طلب جديد</b>  ◈  \n"
            "╠══════════════════════════╣\n"
            f"  ◇ 🆔 <b>المعرّف</b>   ·  <code>{m_uid}</code>\n"
            f"  ◇ <b>المستوى</b>  ·  {vip_tag}\n"
            "╠══════════════════════════╣\n"
            f"  ◆ {plat_emoji} <b>{plat_name}</b>  ·  {svc_type}\n"
            f"  ◆ <b>الكمية</b>  ·  <code>{qty_display}</code>\n"
            f"  ◆ <b>السعر</b>   ·  <b>{price_display}</b>\n"
            "╠══════════════════════════╣\n"
            f"  ◇ 🔗 <code>{m_link}</code>\n"
            "╠══════════════════════════╣\n"
            f"  ◇ 🕐 <b>{now}</b>\n"
            "╚══════════════════════════╝"
        )

        kb = InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(text="◈ اطلب نفس الخدمة", url=order_url),
                InlineKeyboardButton(text="◆ قناة البوت", url=BOT_CHANNEL_URL),
            ],
        ])

    elif event_type == "game_order":
        service_name = service or "خدمة ألعاب"
        price_display = _smart_price(amount)
        m_uid = mask_user_id(user_id)
        vip_tag = _VIP_LABELS.get(vip_level, "◇ عادي")
        order_url = f"https://t.me/{bot_username}?start=game_{service_id}" if service_id else BOT_CHANNEL_URL

        text = (
            "╔══════════════════════════╗\n"
            "║  ◈  <b>𝑲𝒊𝒓𝒂 · شحن ألعاب</b>  ◈  \n"
            "╠══════════════════════════╣\n"
            f"  ◇ 🆔 <b>المعرّف</b>   ·  <code>{m_uid}</code>\n"
            f"  ◇ <b>المستوى</b>  ·  {vip_tag}\n"
            "╠══════════════════════════╣\n"
            f"  ◆ 🎮 <b>اللعبة</b>   ·  {service_name}\n"
            f"  ◆ <b>السعر</b>    ·  <b>{price_display}</b>\n"
            "╠══════════════════════════╣\n"
            f"  ◇ 🕐 <b>{now}</b>\n"
            "╚══════════════════════════╝"
        )

        kb = InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(text="◈ اطلب الآن", url=order_url),
                InlineKeyboardButton(text="◆ قناة البوت", url=BOT_CHANNEL_URL),
            ],
        ])

    elif event_type == "recharge":
        price_display = _smart_price(amount)
        m_uid = mask_user_id(user_id)

        text = (
            "╔══════════════════════════╗\n"
            "║  ◈  <b>𝑲𝒊𝒓𝒂 · إيداع رصيد</b>  ◈  \n"
            "╠══════════════════════════╣\n"
            f"  ◇ 🆔 <b>المعرّف</b>   ·  <code>{m_uid}</code>\n"
            "╠══════════════════════════╣\n"
            f"  ◆ 💳 <b>المبلغ</b>   ·  <b>{price_display}</b>\n"
            "  ◆ ✓  <b>الحالة</b>   ·  تم بنجاح\n"
            "╠══════════════════════════╣\n"
            f"  ◇ 🕐 <b>{now}</b>\n"
            "╚══════════════════════════╝"
        )

        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="◆ قناة البوت", url=BOT_CHANNEL_URL)],
        ])

    elif event_type == "order":
        service_name = service or "خدمة SMM"
        price_display = _smart_price(amount)
        qty_display = f"{quantity:,}" if quantity else "—"
        m_link = mask_link(link)
        plat = (platform or "").lower()
        plat_name = _PLATFORM_NAMES.get(plat, plat.capitalize() if plat else "غير محدد")
        plat_emoji = _PLATFORM_EMOJIS.get(plat, "🌐")
        svc_type = _detect_service_type(service_name, category or "")

        text = (
            "╔══════════════════════════╗\n"
            "║  ◈  <b>𝑲𝒊𝒓𝒂 · طلب</b>  ◈  \n"
            "╠══════════════════════════╣\n"
            f"  ◆ {plat_emoji} <b>{plat_name}</b>  ·  {svc_type}\n"
            f"  ◆ <b>الكمية</b>  ·  <code>{qty_display}</code>\n"
            f"  ◆ <b>السعر</b>   ·  <b>{price_display}</b>\n"
            "╠══════════════════════════╣\n"
            f"  ◇ 🔗 <code>{m_link}</code>\n"
            "╠══════════════════════════╣\n"
            f"  ◇ 🕐 <b>{now}</b>\n"
            "╚══════════════════════════╝"
        )

        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="◆ قناة البوت", url=BOT_CHANNEL_URL)],
        ])
    else:
        return

    # Filter empty/invalid buttons
    if kb is not None:
        clean_rows = []
        for row in kb.inline_keyboard:
            clean_row = [
                btn for btn in row
                if (getattr(btn, "url", None) or getattr(btn, "callback_data", None)
                    or getattr(btn, "switch_inline_query", None) is not None
                    or getattr(btn, "switch_inline_query_current_chat", None) is not None
                    or getattr(btn, "web_app", None) is not None
                    or getattr(btn, "login_url", None) is not None
                    or getattr(btn, "pay", None))
            ]
            if clean_row:
                clean_rows.append(clean_row)
        kb = InlineKeyboardMarkup(inline_keyboard=clean_rows) if clean_rows else None

    try:
        await bot.send_message(channel, text, parse_mode="HTML", reply_markup=kb)
    except Exception as exc:
        logger.error("Activation notify failed (%s): %s", channel, exc)
