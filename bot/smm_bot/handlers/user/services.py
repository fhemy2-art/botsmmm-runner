"""
Service browsing — Kira | كيرا style UI.
Flow: Store → Platform → Category → Service List → Product Detail → Order.
"""
import re
import logging
from aiogram import Router, F
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton

from repositories.service_repo import (
    get_active_platforms,
    get_categories_for_platform,
    get_services_page,
    get_service,
    get_provider_service,
    get_service_stats,
    get_free_services_by_platform,
)
from config import SERVICES_PER_PAGE, BOT_NAME
from i18n import get_vip_level, get_vip_pct, get_vip_name, convert_price, price_in_currency
from services.user_manager import get_or_create_user
from services.settings_manager import get_markup_multiplier
from services import settings_manager
from handlers.common import add_nav, nav_enter, register_screen, safe_edit
from services.name_translator import format_service_name, short_service_label

logger = logging.getLogger(__name__)
router = Router()

# ─── Bot branding ────────────────────────────────────────────────────────────
KIRA = "𝑲𝒊𝒓𝒂 | كيرا"

# ─── Platform config ─────────────────────────────────────────────────────────
PLATFORMS = {
    "telegram":   {"ar": "تيليجرام",    "en": "Telegram",    "ico": "🤖💬"},
    "instagram":  {"ar": "إنستقرام",    "en": "Instagram",   "ico": "📸✨"},
    "youtube":    {"ar": "يوتيوب",      "en": "YouTube",     "ico": "🎬🔥"},
    "twitter":    {"ar": "تويتر X",     "en": "Twitter X",   "ico": "💙⚡"},
    "facebook":   {"ar": "فيسبوك",      "en": "Facebook",    "ico": "📘💎"},
    "tiktok":     {"ar": "تيك توك",     "en": "TikTok",      "ico": "🎵🌟"},
    "threads":    {"ar": "ثريدز",       "en": "Threads",     "ico": "🔗🌐"},
    "whatsapp":   {"ar": "واتساب",      "en": "WhatsApp",    "ico": "💚📱"},
    "spotify":    {"ar": "سبوتيفاي",    "en": "Spotify",     "ico": "🎧🎵"},
    "twitch":     {"ar": "تويتش",       "en": "Twitch",      "ico": "🎮📺"},
    "discord":    {"ar": "ديسكورد",     "en": "Discord",     "ico": "🎮💬"},
    "snapchat":   {"ar": "سناب شات",    "en": "Snapchat",    "ico": "👻📸"},
    "pinterest":  {"ar": "بنترست",      "en": "Pinterest",   "ico": "📌🎨"},
    "linkedin":   {"ar": "لينكدإن",     "en": "LinkedIn",    "ico": "💼🔗"},
    "soundcloud": {"ar": "ساوند كلاود", "en": "SoundCloud",  "ico": "🎵☁️"},
    "other":      {"ar": "خدمات أخرى",  "en": "Other",       "ico": "📦✨"},
}

# ─── Free platform emoji map ────────────────────────────────────────────────
_PLAT_EMOJI = {
    "instagram": "📸", "tiktok": "🎵", "telegram": "💬", "youtube": "▶️",
    "twitter": "🐦",  "facebook": "📘","whatsapp": "💚",  "threads": "🔗",
    "snapchat": "👻",  "linkedin": "💼","spotify": "🎧",  "discord": "🎮",
    "other": "📦",
}



# ─── Unicode bold text helper (makes Latin chars bold in Telegram buttons) ────
_BOLD_UPPER = "𝗔𝗕𝗖𝗗𝗘𝗙𝗚𝗛𝗜𝗝𝗞𝗟𝗠𝗡𝗢𝗣𝗤𝗥𝗦𝗧𝗨𝗩𝗪𝗫𝗬𝗭"
_BOLD_LOWER = "𝗮𝗯𝗰𝗱𝗲𝗳𝗴𝗵𝗶𝗷𝗸𝗹𝗺𝗻𝗼𝗽𝗾𝗿𝘀𝘁𝘂𝘃𝘄𝘅𝘆𝘇"

def _bold(text: str) -> str:
    """Convert ASCII letters to Unicode Mathematical Bold (renders BOLD in Telegram buttons)."""
    out = []
    for ch in text:
        if "A" <= ch <= "Z":
            out.append(_BOLD_UPPER[ord(ch) - ord("A")])
        elif "a" <= ch <= "z":
            out.append(_BOLD_LOWER[ord(ch) - ord("a")])
        else:
            out.append(ch)
    return "".join(out)

# ─── Platform welcome/description messages ───────────────────────────────────
PLATFORM_WELCOME = {
    "telegram": {
        "ar": (
            "╔══════════════════════════╗\n"
            "║  🤖 <b>Telegram · تيليجرام</b>  \n"
            "╠══════════════════════════╣\n"
            "  ① <b>أعضاء حقيقيين</b> ونشطين\n"
            "  ② <b>مشاهدات</b> منشورات فورية\n"
            "  ③ <b>تفاعلات</b> ولايكات\n"
            "  ④ <b>ردود فعل</b> ورياكشنات\n"
            "╠══════════════════════════╣\n"
            "◆ <b>اختر نوع الخدمة:</b>"
        ),
        "en": (
            "╔══════════════════════════╗\n"
            "║  🤖 <b>Telegram · تيليجرام</b>  \n"
            "╠══════════════════════════╣\n"
            "  ① <b>Real active</b> members\n"
            "  ② <b>Instant</b> post views\n"
            "  ③ <b>Reactions</b> & shares\n"
            "  ④ <b>Likes</b> & reactions\n"
            "╠══════════════════════════╣\n"
            "◆ <b>Choose a service category:</b>"
        )
    },
    "instagram": {
        "ar": (
            "╔══════════════════════════╗\n"
            "║  📸 <b>Instagram · إنستقرام</b>  \n"
            "╠══════════════════════════╣\n"
            "  ① <b>متابعين</b> عرب وعالميين\n"
            "  ② <b>مشاهدات</b> ريلز وستوري\n"
            "  ③ <b>إعجابات</b> وتعليقات\n"
            "  ④ <b>حفظ</b> ومشاركات\n"
            "╠══════════════════════════╣\n"
            "◆ <b>اختر نوع الخدمة:</b>"
        ),
        "en": (
            "╔══════════════════════════╗\n"
            "║  📸 <b>Instagram · إنستقرام</b>  \n"
            "╠══════════════════════════╣\n"
            "  ① <b>Followers</b> · Arab & worldwide\n"
            "  ② <b>Reels</b> & story views\n"
            "  ③ <b>Likes</b> & comments\n"
            "  ④ <b>Saves</b> & shares\n"
            "╠══════════════════════════╣\n"
            "◆ <b>Choose a service category:</b>""╔══════════════════════════╗\n"
            "║  📸 <b>Instagram · إنستقرام</b>  \n"
            "╠══════════════════════════╣\n"
            "  ① <b>Followers</b> · Arab & worldwide\n"
            "  ② <b>Reels</b> & story views\n"
            "  ③ <b>Likes</b> & comments\n"
            "╠══════════════════════════╣\n"
            "◆ <b>Choose a service category:</b>"
        )
    },
    "youtube": {
        "ar": (
            "╔══════════════════════════╗\n"
            "║  🎬 <b>YouTube · يوتيوب</b>  \n"
            "╠══════════════════════════╣\n"
            "  ① <b>مشاهدات</b> عالية الاحتفاظ\n"
            "  ② <b>مشتركين</b> حقيقيين\n"
            "  ③ <b>ساعات مشاهدة</b> للتفعيل\n"
            "  ④ <b>إعجابات</b> وتعليقات\n"
            "╠══════════════════════════╣\n"
            "◆ <b>اختر نوع الخدمة:</b>"
        ),
        "en": (
            "╔══════════════════════════╗\n"
            "║  🎬 <b>YouTube · يوتيوب</b>  \n"
            "╠══════════════════════════╣\n"
            "  ① <b>High retention</b> views\n"
            "  ② <b>Real subscribers</b>\n"
            "  ③ <b>Watch hours</b> for monetization\n"
            "  ④ <b>Likes</b> & comments\n"
            "╠══════════════════════════╣\n"
            "◆ <b>Choose a service category:</b>"
        )
    },
    "tiktok": {
        "ar": (
            "╔══════════════════════════╗\n"
            "║  🎵 <b>TikTok · تيك توك</b>  \n"
            "╠══════════════════════════╣\n"
            "  ① <b>متابعين</b> نشطين\n"
            "  ② <b>مشاهدات</b> فيديو فورية\n"
            "  ③ <b>إعجابات</b> ومشاركات\n"
            "  ④ <b>تعليقات</b> حقيقية\n"
            "╠══════════════════════════╣\n"
            "◆ <b>اختر نوع الخدمة:</b>"
        ),
        "en": (
            "╔══════════════════════════╗\n"
            "║  🎵 <b>TikTok · تيك توك</b>  \n"
            "╠══════════════════════════╣\n"
            "  ① <b>Active followers</b>\n"
            "  ② <b>Instant</b> video views\n"
            "  ③ <b>Likes</b> & shares\n"
            "  ④ <b>Real comments</b>\n"
            "╠══════════════════════════╣\n"
            "◆ <b>Choose a service category:</b>"
        )
    },
    "twitter": {
        "ar": (
            "╔══════════════════════════╗\n"
            "║  💙 <b>Twitter X · تويتر X</b>  \n"
            "╠══════════════════════════╣\n"
            "  ① <b>متابعين</b> حقيقيين\n"
            "  ② <b>إعجابات</b> وريتويت\n"
            "  ③ <b>مشاهدات</b> تغريدات\n"
            "╠══════════════════════════╣\n"
            "◆ <b>اختر نوع الخدمة:</b>"
        ),
        "en": (
            "╔══════════════════════════╗\n"
            "║  💙 <b>Twitter X · تويتر X</b>  \n"
            "╠══════════════════════════╣\n"
            "  ① <b>Real followers</b>\n"
            "  ② <b>Likes</b> & retweets\n"
            "  ③ <b>Tweet views</b>\n"
            "╠══════════════════════════╣\n"
            "◆ <b>Choose a service category:</b>"
        )
    },
    "facebook": {
        "ar": (
            "╔══════════════════════════╗\n"
            "║  📘 <b>Facebook · فيسبوك</b>  \n"
            "╠══════════════════════════╣\n"
            "  ① <b>متابعين</b> وإعجابات صفحة\n"
            "  ② <b>مشاهدات</b> فيديو\n"
            "  ③ <b>أعضاء</b> مجموعات\n"
            "╠══════════════════════════╣\n"
            "◆ <b>اختر نوع الخدمة:</b>"
        ),
        "en": (
            "╔══════════════════════════╗\n"
            "║  📘 <b>Facebook · فيسبوك</b>  \n"
            "╠══════════════════════════╣\n"
            "  ① <b>Page followers</b> & likes\n"
            "  ② <b>Video views</b>\n"
            "  ③ <b>Group members</b>\n"
            "╠══════════════════════════╣\n"
            "◆ <b>Choose a service category:</b>"
        )
    },
}

# ─── Category icons & descriptions ──────────────────────────────────────────
CAT_ICO = {
    "followers":          "👥✨",
    "views":              "👁‍🗨🔥",
    "likes":              "❤️💫",
    "comments":           "💬⭐",
    "reactions":          "🎉🚀",
    "stories":            "⭐🌟",
    "shares":             "📤💥",
    "subscribers":        "👥🔔",
    "members":            "👥💎",
    "متابعين":            "👥✨",
    "مشاهدات":            "👁‍🗨🔥",
    "إعجابات":            "❤️💫",
    "لايكات":             "❤️💫",
    "تعليقات":            "💬⭐",
    "تفاعلات":            "🎉🚀",
    "ستوري":              "⭐🌟",
    "مشاركات":            "📤💥",
    "مشتركين":            "👥🔔",
    "أعضاء":              "👥💎",
    "ردود فعل":           "🎉🚀",
    "رياكشنات":           "🔥💥",
    "استفتاءات":          "📊💬",
    "مشاهدات منشور":      "👁‍🗨📄",
    "خدمات أخرى":         "📦✨",
    "تشغيل بوت":          "🤖⚡",
    "مشاهدات ستوري":      "⭐👁‍🗨",
    "تصويت":              "🗳️✅",
}

LIST_SIZE = 10

_CAT_MAP: dict[str, str] = {}


def _cat_key(category: str) -> str:
    if len(category.encode('utf-8')) <= 30:
        return category
    import hashlib
    h = hashlib.md5(category.encode()).hexdigest()[:8]
    key = f"c{h}"
    _CAT_MAP[key] = category
    return key


def _cat_resolve(key: str) -> str:
    return _CAT_MAP.get(key, key)


def _L(lang, ar, en):
    return ar if lang == "ar" else en


def _ico(cat: str) -> str:
    c = cat.lower().strip()
    for k, v in CAT_ICO.items():
        if k in c or c in k:
            return v
    return "📦✨"


def _price(ps, user):
    m = get_markup_multiplier()
    r = float(ps.rate or 0) * m
    lvl = get_vip_level(float(user.total_spent or 0))
    p = get_vip_pct(lvl)
    return r * (1 - p / 100) if p > 0 else r


def _price_display(usd_amount: float, currency: str) -> str:
    return price_in_currency(usd_amount, currency)


def _trim(name: str, n: int = 32) -> str:
    return name if len(name) <= n else name[:n-1].rstrip() + "…"


def _back_btn(lang):
    return InlineKeyboardButton(
        text=_L(lang, "↩️ رجوع", "↩️ Back"),
        callback_data="nav:back")


def _footer(lang):
    return [_back_btn(lang)]


def _extract_speed(name: str, desc: str = "") -> str | None:
    combined = f"{name} {desc}"
    m = re.search(r'[Ss]peed[:\s]*([0-9,.]+[-–]?[0-9,.]*[KMkm]?/?[Dd]ay)', combined)
    if m:
        return m.group(1).replace("Day", "يومياً").replace("day", "يومياً")
    m = re.search(r'(\d+[-–]\d+[KMkm])/[Dd]ay', combined)
    if m:
        return m.group(1) + " / يوم"
    m = re.search(r'(\d+[KMkm])/[Dd]ay', combined)
    if m:
        return m.group(1) + " / يوم"
    return None


def _extract_quality(name: str) -> str:
    n = name.lower()
    if "premium" in n or "مميز" in n:
        return "بريميوم 🏆"
    if "uhq" in n or "ultra high quality" in n:
        return "جودة فائقة 💎"
    if "shq" in n or "super high" in n:
        return "جودة ممتازة 🌟"
    if "high quality" in n or "hq" in n or "جودة عالية" in n:
        return "جودة عالية ⭐"
    if "real" in n or "حقيقي" in n or "حقيقيين" in n:
        return "حقيقيين ✅"
    if "arab" in n or "عرب" in n or "عربي" in n:
        return "عرب 🌍"
    return "جيدة ✅"


def _extract_drop(name: str) -> str:
    n = name.lower()
    if "no drop" in n or "بدون انخفاض" in n:
        return "بدون نزول ✅"
    if "low drop" in n or "نسبة قليلة" in n:
        return "نزول قليل ⚠️"
    if "stable" in n or "مستقر" in n:
        return "مستقر 🟢"
    if "no refill" in n or "بدون ضمان" in n:
        return "محتمل النزول ⚠️"
    return "طبيعي 🔄"


def _extract_guarantee(name: str, ps=None) -> str:
    n = name.lower()
    if "lifetime" in n or "مدى الحياة" in n:
        return "ضمان مدى الحياة ♾️"
    m = re.search(r'(\d+)\s*day[s]?\s*refill', n)
    if m:
        days = m.group(1)
        return f"تعويض {days} يوم ♻️"
    if "365" in n:
        return "تعويض سنة كاملة ♻️"
    if "90" in n and ("refill" in n or "ضمان" in n):
        return "تعويض 90 يوم ♻️"
    if "60" in n and ("refill" in n or "ضمان" in n):
        return "تعويض 60 يوم ♻️"
    if "30" in n and ("refill" in n or "ضمان" in n):
        return "تعويض 30 يوم ♻️"
    if "no refill" in n or "بدون ضمان" in n:
        return "بدون ضمان ❌"
    if "refill" in n or "ضمان" in n:
        return "بضمان ♻️"
    return "لا يوجد ❌"


def _rating_stars(rating: float | None, orders: int) -> str:
    if not rating:
        return "جديدة ✨"
    stars = min(5, max(1, round(rating)))
    return "⭐" * stars + f" ({orders} طلب)"


def _fancy_service_name(name: str, lang: str) -> str:
    """Return a NEXUS-decorated, styled service name for buttons."""
    translated = format_service_name(name, lang)
    n = name.lower()
    # Quality tiers
    if any(q in n for q in ["premium", "vip", "diamond", "elite", "ultimate", "exclusive"]):
        return f"◆◆ {translated}"
    if any(q in n for q in ["gold", "pro", "plus", "مميز", "بريميوم"]):
        return f"◆ {translated}"
    if any(q in n for q in ["instant", "fast", "سريع", "فوري", "express"]):
        return f"⚡ {translated}"
    if any(q in n for q in ["real", "organic", "حقيقي", "حقيقيين", "عضوي"]):
        return f"◈ {translated}"
    if any(q in n for q in ["arab", "عربي", "عرب", "arabic"]):
        return f"◇ {translated}"
    return f"◇ {translated}"


# Platform-specific mirror emoji pairs
_PLT_FRAMES = {
    "telegram":   ("🤖💬", "💬🤖"),
    "instagram":  ("📸👑", "👑📸"),
    "youtube":    ("🎬📢", "📢🎬"),
    "tiktok":     ("🎵⚡", "⚡🎵"),
    "twitter":    ("💙🐦", "🐦💙"),
    "facebook":   ("📘🏆", "🏆📘"),
    "threads":    ("🔗🌐", "🌐🔗"),
    "whatsapp":   ("💚📱", "📱💚"),
    "spotify":    ("🎧🎵", "🎵🎧"),
    "snapchat":   ("👻📸", "📸👻"),
    "other":      ("📦✨", "✨📦"),
}


def _platform_btn_text(lang: str, platform_key: str, ico: str, ar_name: str, en_name: str) -> str:
    """NEXUS Bilingual platform button with Unicode bold: 🤖💬 𝗘𝗻𝗴𝗹𝗶𝘀𝗵 · عربي 💬🤖"""
    l, r = _PLT_FRAMES.get(platform_key, (ico, ico))
    bold_en = _bold(en_name)
    return f"{l} {bold_en} · {ar_name} {r}"


# ─── Category button styles: keyword → (emoji, ar_display, en_label) ──────────
# Format: >> emoji ‖ اسم عربي ‖ ENGLISH <<
_BTN_STYLES: list[tuple[str, str, str, str]] = [
    # (keyword_match,      emoji,  ar_display,              en_label)
    ("أعضاء",              "💎",   "أعـضـاء",               "MEMBERS"),
    ("members",            "💎",   "أعـضـاء",               "MEMBERS"),
    ("ستوري",              "🌙",   "سـتـوري",               "STORY"),
    ("stories",            "🌙",   "سـتـوري",               "STORY"),
    ("رياكشن",             "✨",   "ريـاكـشـن",             "REACT"),
    ("رياكشنات",           "✨",   "ريـاكـشـن",             "REACT"),
    ("ردود فعل",           "✨",   "ريـاكـشـن",             "REACT"),
    ("reactions",          "✨",   "ريـاكـشـن",             "REACT"),
    ("نخبة",               "👑",   "نُخبـة البـريميوم",      "VIP"),
    ("بريميوم",            "👑",   "نُخبـة البـريميوم",      "VIP"),
    ("premium",            "👑",   "نُخبـة البـريميوم",      "VIP"),
    ("vip",                "👑",   "نُخبـة البـريميوم",      "VIP"),
    ("تصويت",              "✅",   "تـصـويـت",              "VOTE"),
    ("poll",               "✅",   "تـصـويـت",              "VOTE"),
    ("vote",               "✅",   "تـصـويـت",              "VOTE"),
    ("استفتاء",            "✅",   "تـصـويـت",              "VOTE"),
    ("تعليقات",            "💬",   "تـعـلـيـقـات",          "TEXT"),
    ("comments",           "💬",   "تـعـلـيـقـات",          "TEXT"),
    ("تشغيل بوت",          "⚙️",   "تـشـغـيـل بـوت",        "BOTS"),
    ("تفاعل",              "🔥",   "تـفـاعـــل",             "HOT"),
    ("تفاعلات",            "🔥",   "تـفـاعـــل",             "HOT"),
    ("مشاركات",            "🚀",   "مُـشـاركـات",            "SHARE"),
    ("shares",             "🚀",   "مُـشـاركـات",            "SHARE"),
    ("مشاهدات",            "👁",   "مُـشـاهـدات",            "VIEWS"),
    ("views",              "👁",   "مُـشـاهـدات",            "VIEWS"),
    ("متابعين",            "🌟",   "مـتـابـعـيـن",           "FOLLOWERS"),
    ("followers",          "🌟",   "مـتـابـعـيـن",           "FOLLOWERS"),
    ("مشتركين",            "🔔",   "مُـشـتـركـيـن",          "SUBS"),
    ("subscribers",        "🔔",   "مُـشـتـركـيـن",          "SUBS"),
    ("إعجابات",            "❤️",   "إعـجـابـات",            "LIKES"),
    ("لايكات",             "❤️",   "إعـجـابـات",            "LIKES"),
    ("likes",              "❤️",   "إعـجـابـات",            "LIKES"),
    ("ريلز",               "🎬",   "ريـلـز",                "REELS"),
    ("reels",              "🎬",   "ريـلـز",                "REELS"),
    ("بث مباشر",           "📡",   "بـث مـبـاشـر",           "LIVE"),
    ("live",               "📡",   "بـث مـبـاشـر",           "LIVE"),
    ("حفظ",                "🔖",   "حـفـظ",                 "SAVES"),
    ("saves",              "🔖",   "حـفـظ",                 "SAVES"),
    ("زيارات",             "🔍",   "زيـارات",               "VISITS"),
    ("مشاهدات منشور",      "📄",   "مُـشـاهـدات مـنـشـور",   "POST VIEWS"),
    ("مشاهدات ستوري",      "⭐",   "مُـشـاهـدات سـتـوري",    "STORY VIEWS"),
    ("خدمات أخرى",         "📦",   "خـدمـات أخـرى",         "OTHER"),
    ("other",              "📦",   "خـدمـات أخـرى",         "OTHER"),
    ("انطباعات",           "💡",   "انـطـبـاعـات",           "IMPRESSIONS"),
]

# Legacy _CAT_FRAMES kept for safety
_CAT_FRAMES: dict[str, tuple[str, str]] = {}


def _category_btn_text(lang: str, display_name: str, ico: str) -> str:
    """
    Premium category button — KIRA style:
    << emoji ‖ اسم عربي ‖ 𝗘𝗡𝗚𝗟𝗜𝗦𝗛 >>
    All buttons same width appearance via spaced Arabic letters.
    """
    name_lower = display_name.lower().strip()
    emoji = "✦"
    ar_label = display_name
    en_label = ""

    for keyword, emo, ar_disp, en_disp in _BTN_STYLES:
        if keyword in display_name or keyword in name_lower:
            emoji = emo
            ar_label = ar_disp
            en_label = en_disp
            break

    if en_label:
        bold_en = _bold(en_label)
        return f"<< {emoji} ‖ {ar_label} ‖ {bold_en} >>"
    else:
        return f"<< {emoji} ‖ {ar_label} >>"


def _service_btn_text(short_label: str, is_hot: bool = False) -> str:
    """Premium service button with Mirror Emoji: ✨👥 label 👥✨"""
    lbl = short_label
    if "متابعين" in lbl or "followers" in lbl.lower():
        ico = "👥"
    elif "مشاهدات" in lbl or "views" in lbl.lower():
        ico = "👁"
    elif "إعجابات" in lbl or "لايكات" in lbl or "likes" in lbl.lower():
        ico = "❤️"
    elif "تعليقات" in lbl or "comments" in lbl.lower():
        ico = "✍️"
    elif "أعضاء" in lbl or "members" in lbl.lower():
        ico = "💎"
    elif "مشتركين" in lbl or "subscribers" in lbl.lower():
        ico = "🔔"
    elif "تفاعلات" in lbl or "reactions" in lbl.lower():
        ico = "⚡"
    elif "مشاركات" in lbl or "shares" in lbl.lower():
        ico = "📤"
    elif "ستوري" in lbl or "stories" in lbl.lower():
        ico = "🌙"
    elif "ريلز" in lbl or "reel" in lbl.lower():
        ico = "🎬"
    elif "تصويت" in lbl or "poll" in lbl.lower():
        ico = "🗳️"
    else:
        ico = "✦"
    if is_hot:
        return f"🔥{ico} {lbl} {ico}🔥"
    return f"✨{ico} {lbl} {ico}✨"


# ─── Sort labels ─────────────────────────────────────────────────────────────
_SORT_LABELS = {
    "best":      ("🏆 الأفضل",   "🏆 Best"),
    "cheap":     ("⚡ الأرخص",  "⚡ Cheapest"),
    "fast":      ("🚀 الأسرع",  "🚀 Fastest"),
    "guarantee": ("♻️ ضمان",    "♻️ Guaranteed"),
}
_VALID_SORTS = ("best", "cheap", "fast", "guarantee")




# ═════════════════════════════════════════════════════════════════════════════
#  🎁 FREE SERVICES — plt:free
# ═════════════════════════════════════════════════════════════════════════════

@router.callback_query(F.data == "plt:free")
async def show_free_services(cb: CallbackQuery, db, screen=None, from_back=False):
    """Show all free ($0) services grouped by platform."""
    nav_enter(cb.from_user.id, "plt:free", push=not from_back)
    user = await get_or_create_user(db, cb.from_user.id)
    lang = user.language or "ar"

    grouped = await get_free_services_by_platform(db)
    total_count = sum(len(v) for v in grouped.values())

    if not grouped:
        txt = _L(lang,
            "🎁 <b>الخدمات المجانية</b>\n\nلا توجد خدمات مجانية بعد.\nاطلب من الأدمن تفعيلها.",
            "🎁 <b>Free Services</b>\n\nNo free services yet.\nAsk admin to activate them.")
        await safe_edit(cb, txt, InlineKeyboardMarkup(inline_keyboard=[_footer(lang)]))
        return await cb.answer()

    header = _L(lang,
        "\u256d\u2500\u2500\u2500\u2500 \U0001f381 <b>\u0627\u0644\u062e\u062f\u0645\u0627\u062a \u0627\u0644\u0645\u062c\u0627\u0646\u064a\u0629</b> \u2500\u2500\u2500\u2500\n"
        f"\u2502  \u2705 <b>{total_count}</b> \u062e\u062f\u0645\u0629 \u0645\u062c\u0627\u0646\u064a\u0629 \u0645\u062a\u0627\u062d\u0629\n"
        "\u2502  \U0001f552 \u0648\u0642\u062a \u0627\u0644\u062a\u0633\u0644\u064a\u0645: 1\u201324 \u0633\u0627\u0639\u0629\n"
        "\u2502  \u26a0\ufe0f \u0645\u0631\u0629 \u0648\u0627\u062d\u062f\u0629 \u0644\u0643\u0644 \u062e\u062f\u0645\u0629 \u0644\u0643\u0644 \u0645\u0633\u062a\u062e\u062f\u0645\n"
        "\u251c\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\n"
        "\u25c6 <b>\u0627\u062e\u062a\u0631 \u0627\u0644\u0645\u0646\u0635\u0629:</b>",
        "\u256d\u2500\u2500\u2500\u2500 \U0001f381 <b>Free Services</b> \u2500\u2500\u2500\u2500\n"
        f"\u2502  \u2705 <b>{total_count}</b> free services available\n"
        "\u2502  \U0001f552 Delivery: 1\u201324 hours\n"
        "\u2502  \u26a0\ufe0f Once per service per user\n"
        "\u251c\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\n"
        "\u25c6 <b>Choose a platform:</b>")

    _ORDER = ["instagram", "tiktok", "telegram", "youtube", "twitter",
              "facebook", "snapchat", "whatsapp", "threads", "spotify",
              "linkedin", "discord", "other"]

    kb = []
    row = []
    for plat in _ORDER:
        svcs = grouped.get(plat)
        if not svcs:
            continue
        ico = _PLAT_EMOJI.get(plat, "\U0001f4e6")
        plat_info = PLATFORMS.get(plat, {"ar": plat, "en": plat})
        label = _L(lang,
            f"{ico} {plat_info['ar']} ({len(svcs)})",
            f"{ico} {plat_info['en']} ({len(svcs)})")
        row.append(InlineKeyboardButton(text=label, callback_data=f"free_plat:{plat}:0"))
        if len(row) >= 2:
            kb.append(row)
            row = []
    if row:
        kb.append(row)
    kb.append(_footer(lang))
    await safe_edit(cb, header, InlineKeyboardMarkup(inline_keyboard=kb))
    await cb.answer()


@router.callback_query(F.data.startswith("free_plat:"))
async def show_free_platform(cb: CallbackQuery, db, screen=None, from_back=False):
    """List free services for a specific platform."""
    parts = cb.data.split(":")
    plat = parts[1]
    page = int(parts[2]) if len(parts) > 2 and parts[2].isdigit() else 0
    PER_PAGE = 10
    nav_enter(cb.from_user.id, cb.data, push=not from_back)
    user = await get_or_create_user(db, cb.from_user.id)
    lang = user.language or "ar"
    grouped = await get_free_services_by_platform(db)
    all_svcs = grouped.get(plat, [])
    if not all_svcs:
        await cb.answer(_L(lang, "لا توجد خدمات مجانية", "No free services"), show_alert=True)
        return
    total = len(all_svcs)
    pages = max(1, (total + PER_PAGE - 1) // PER_PAGE)
    page_svcs = all_svcs[page * PER_PAGE:(page + 1) * PER_PAGE]
    ico = _PLAT_EMOJI.get(plat, "\U0001f4e6")
    plat_info = PLATFORMS.get(plat, {"ar": plat, "en": plat})
    header = _L(lang,
        f"\U0001f381 <b>\u062e\u062f\u0645\u0627\u062a \u0645\u062c\u0627\u0646\u064a\u0629</b> \u2014 {ico} <b>{plat_info['ar']}</b>\n"
        "\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\n"
        f"\U0001f4c4 \u0627\u0644\u0635\u0641\u062d\u0629 {page+1}/{pages}\n"
        "\u2193 <b>\u0627\u062e\u062a\u0631 \u062e\u062f\u0645\u0629:</b>",
        f"\U0001f381 <b>Free Services</b> \u2014 {ico} <b>{plat_info['en']}</b>\n"
        "\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\n"
        f"\U0001f4c4 Page {page+1}/{pages}\n"
        "\u2193 <b>Tap a service to order:</b>")
    kb = []
    for svc in page_svcs:
        kb.append([InlineKeyboardButton(
            text=f"\U0001f381 {svc.name}",
            callback_data=f"free_sd:{svc.id}:{plat}:{page}")])
    if pages > 1:
        nav = []
        if page > 0:
            nav.append(InlineKeyboardButton(text="\u25c0\ufe0f", callback_data=f"free_plat:{plat}:{page-1}"))
        nav.append(InlineKeyboardButton(text=f"\U0001f4c4 {page+1}/{pages}", callback_data="noop"))
        if page + 1 < pages:
            nav.append(InlineKeyboardButton(text="\u25b6\ufe0f", callback_data=f"free_plat:{plat}:{page+1}"))
        kb.append(nav)
    kb.append([InlineKeyboardButton(
        text=_L(lang, "\u25c0\ufe0f \u0627\u0644\u062e\u062f\u0645\u0627\u062a \u0627\u0644\u0645\u062c\u0627\u0646\u064a\u0629", "\u25c0\ufe0f Free Services"),
        callback_data="plt:free")])
    kb.append(_footer(lang))
    await safe_edit(cb, header, InlineKeyboardMarkup(inline_keyboard=kb))
    await cb.answer()


@router.callback_query(F.data.startswith("free_sd:"))
async def show_free_service_detail(cb: CallbackQuery, db):
    """Show detail for a free service and allow ordering."""
    parts = cb.data.split(":")
    sid = int(parts[1])
    plat = parts[2] if len(parts) > 2 else ""
    page = parts[3] if len(parts) > 3 else "0"
    user = await get_or_create_user(db, cb.from_user.id)
    lang = user.language or "ar"
    svc = await get_service(db, sid)
    if not svc:
        await cb.answer(_L(lang, "الخدمة غير موجودة", "Service not found"), show_alert=True)
        return
    ico = _PLAT_EMOJI.get(plat, "\U0001f4e6")
    plat_info = PLATFORMS.get(plat, {"ar": plat, "en": plat})
    desc = (svc.description or "")[:120]
    text = (
        f"\U0001f381 <b>{svc.name}</b>\n"
        "\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\n"
        + (f"\U0001f4dd {desc}\n\n" if desc else "\n")
        + _L(lang,
            f"\U0001f4b0 \u0627\u0644\u0633\u0639\u0631: <b>\U0001f195 \u0645\u062c\u0627\u0646\u064a \U0001f195</b>\n"
            f"{ico} \u0627\u0644\u0645\u0646\u0635\u0629: <b>{plat_info['ar']}</b>\n"
            "\u23f1 \u0627\u0644\u062a\u0633\u0644\u064a\u0645: <b>1\u201324 \u0633\u0627\u0639\u0629</b>\n"
            "\u26a0\ufe0f \u0645\u0631\u0629 \u0648\u0627\u062d\u062f\u0629 \u0641\u0642\u0637 \u0644\u0643\u0644 \u0645\u0633\u062a\u062e\u062f\u0645",
            f"\U0001f4b0 Price: <b>\U0001f195 FREE \U0001f195</b>\n"
            f"{ico} Platform: <b>{plat_info['en']}</b>\n"
            "\u23f1 Delivery: <b>1\u201324 hours</b>\n"
            "\u26a0\ufe0f Once per user per service")
    )
    kb = [
        [InlineKeyboardButton(
            text=_L(lang, "\U0001f6d2 \u2756 \u0627\u0637\u0644\u0628 \u0645\u062c\u0627\u0646\u0627\u064b \u2756", "\U0001f6d2 \u2756 Order Free \u2756"),
            callback_data=f"order:{svc.id}")],
        [InlineKeyboardButton(
            text=_L(lang, "\u25c0\ufe0f \u0631\u062c\u0648\u0639", "\u25c0\ufe0f Back"),
            callback_data=f"free_plat:{plat}:{page}")],
        _footer(lang),
    ]
    await safe_edit(cb, text, InlineKeyboardMarkup(inline_keyboard=kb))
    await cb.answer()


# ═════════════════════════════════════════════════════════════════════════════
#  1 · PLATFORMS
# ═════════════════════════════════════════════════════════════════════════════

@router.callback_query(F.data == "new_order")
async def show_platforms(cb: CallbackQuery, db, screen="new_order", from_back=False):
    nav_enter(cb.from_user.id, "new_order", push=not from_back)
    user = await get_or_create_user(db, cb.from_user.id)
    lang = user.language or "ar"
    active = await get_active_platforms(db)
    hidden = settings_manager.get_hidden_platforms()
    custom_order = settings_manager.get_platform_order()
    columns = settings_manager.get_platform_columns()

    all_keys = [k for k in PLATFORMS.keys() if k != "other"]
    ordered = [p for p in custom_order if p in all_keys]
    for p in all_keys:
        if p not in ordered:
            ordered.append(p)

    avail = [(k, PLATFORMS[k]) for k in ordered if k in active and k not in hidden]
    has_other = "other" in active and "other" not in hidden

    if not avail:
        t = _L(lang,
            "ℹ️ لا توجد خدمات متاحة حالياً.\nيرجى المحاولة لاحقاً.",
            "ℹ️ No services available.\nPlease try again later.")
        await safe_edit(cb, t, InlineKeyboardMarkup(inline_keyboard=[_footer(lang)]))
        return await cb.answer()

    t = _L(lang,
        "╔══════════════════════════╗\n"
        "║  ◈  <b>𝑲𝒊𝒓𝒂 SMM</b>  ·  كيرا  ◈  \n"
        "╠══════════════════════════╣\n"
        "◆ <b>GROW · CONNECT · SUCCEED</b> ◆\n"
        "╠══════════════════════════╣\n"
        "  ⚡ <b>عزّز حضورك الرقمي الآن!</b>\n"
        "  ① 👥 <b>متابعين</b> حقيقيين ونشطين\n"
        "  ② 👁 <b>مشاهدات</b> فورية وعالية\n"
        "  ③ ❤️ <b>إعجابات</b> وتعليقات حقيقية\n"
        "  ④ 📊 <b>تفاعلات</b> ومشاركات\n"
        "╠══════════════════════════╣\n"
        "◆ <b>اختر منصتك من الأسفل</b> ◆\n"
        "╚══════════════════════════╝",
        "╔══════════════════════════╗\n"
        "║  ◈  <b>𝑲𝒊𝒓𝒂 SMM</b>  ·  Kira  ◈  \n"
        "╠══════════════════════════╣\n"
        "◆ <b>GROW · CONNECT · SUCCEED</b> ◆\n"
        "╠══════════════════════════╣\n"
        "  ⚡ <b>Boost your digital presence now!</b>\n"
        "  ① 👥 <b>Followers</b> — real & active\n"
        "  ② 👁 <b>Views</b> — instant & high quality\n"
        "  ③ ❤️ <b>Likes</b> — genuine engagement\n"
        "  ④ 📊 <b>Reactions</b> & shares\n"
        "╠══════════════════════════╣\n"
        "◆ <b>Choose your platform below</b> ◆\n"
        "╚══════════════════════════╝")

    kb = []

    # ── 🎁 Free services — always pinned at top ──
    kb.append([InlineKeyboardButton(
        text=_L(lang, "🎁 ✦ خدمات مجانية ✦ 🎁", "🎁 ✦ Free Services ✦ 🎁"),
        callback_data="plt:free")])

    row = []
    for k, v in avail:
        custom_name = settings_manager.get_platform_custom_name(k)
        ar_name = custom_name or v["ar"]
        en_name = v["en"]
        ico = v["ico"]
        btn_text = _platform_btn_text(lang, k, ico, ar_name, en_name)
        row.append(InlineKeyboardButton(text=btn_text, callback_data=f"plt:{k}"))
        if len(row) >= columns:
            kb.append(row)
            row = []
    if row:
        kb.append(row)

    if has_other:
        kb.append([InlineKeyboardButton(
            text=_L(lang, "📦✨ 【 خدمات أخرى 】", "📦✨ 【 Other Services 】"),
            callback_data="plt:other")])

    kb.append(_footer(lang))

    await safe_edit(cb, t, InlineKeyboardMarkup(inline_keyboard=kb))
    await cb.answer()


# ═════════════════════════════════════════════════════════════════════════════
#  2 · CATEGORIES
# ═════════════════════════════════════════════════════════════════════════════

@router.callback_query(F.data.startswith("plt:"))
async def choose_category(cb: CallbackQuery, db, screen=None, from_back=False):
    data = screen or cb.data
    nav_enter(cb.from_user.id, data, push=not from_back)
    user = await get_or_create_user(db, cb.from_user.id)
    lang = user.language or "ar"
    plat = data.split(":", 1)[1]
    info = PLATFORMS.get(plat, {"ar": plat, "en": plat, "ico": "📱"})
    cats = await get_categories_for_platform(db, plat)

    hidden_cats = settings_manager.get_hidden_categories(plat)
    cats = [c for c in cats if c not in hidden_cats]

    custom_order = settings_manager.get_category_order(plat)
    if custom_order:
        ordered = [c for c in custom_order if c in cats]
        for c in cats:
            if c not in ordered:
                ordered.append(c)
        cats = ordered

    columns = settings_manager.get_category_columns()
    custom_plat_name = settings_manager.get_platform_custom_name(plat)
    pn_ar = custom_plat_name or info["ar"]
    pn_en = info["en"]
    ico_plat = info["ico"]

    if not cats:
        t = _L(lang,
            f"ℹ️ لا توجد خدمات متاحة لـ {pn_ar} حالياً.",
            f"ℹ️ No services available for {pn_en}.")
        await safe_edit(cb, t, InlineKeyboardMarkup(inline_keyboard=[_footer(lang)]))
        return await cb.answer()

    # Use platform-specific welcome or default
    welcome_data = PLATFORM_WELCOME.get(plat, {})
    t = welcome_data.get(lang) or _L(lang,
        f"{ico_plat} <b>رشق {pn_ar}</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n"
        f"🌟 <b>اختر نوع الخدمة التي تريدها لـ {pn_ar}</b>\n\n"
        "✦ أسعار تنافسية وجودة عالية\n"
        "✦ تنفيذ فوري وسريع ⚡\n"
        "✦ ضمان على معظم الخدمات ♻️\n\n"
        "👇 <b>اختر الفئة المطلوبة:</b>",
        f"{ico_plat} <b>Boost {pn_en}</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n"
        "👇 <b>Choose a category below:</b>")

    kb = []
    row = []
    for c in cats:
        custom_cat_name = settings_manager.get_category_custom_name(c)
        display_name = custom_cat_name or c
        ico = _ico(c)
        btn_text = _category_btn_text(lang, display_name, ico)
        row.append(InlineKeyboardButton(
            text=btn_text, callback_data=f"sl:{plat}:{_cat_key(c)}:0"))
        if len(row) >= columns:
            kb.append(row)
            row = []
    if row:
        kb.append(row)

    kb.append(_footer(lang))

    await safe_edit(cb, t, InlineKeyboardMarkup(inline_keyboard=kb))
    await cb.answer()


# ═════════════════════════════════════════════════════════════════════════════
#  3 · SERVICE LIST
# ═════════════════════════════════════════════════════════════════════════════

@router.callback_query(F.data.startswith("sl:"))
async def show_list(cb: CallbackQuery, db, screen=None, from_back=False):
    data = screen or cb.data
    parts = data.split(":")
    plat, cat_key = parts[1], parts[2]
    cat = _cat_resolve(cat_key)
    page = int(parts[3]) if len(parts) > 3 and parts[3].isdigit() else 0
    sort = parts[4] if len(parts) > 4 and parts[4] in _VALID_SORTS else "best"

    nav_enter(cb.from_user.id, data, push=False if screen or page > 0 else not from_back)
    user = await get_or_create_user(db, cb.from_user.id)
    lang = user.language or "ar"
    cur = user.currency or "USD"

    items, total = await get_services_page(db, plat, cat, page, LIST_SIZE, "all", sort)

    if not items:
        if sort == "guarantee":
            empty_msg = _L(lang,
                "ℹ️ لا توجد خدمات بضمان في هذه الفئة. جرّب فلتر الأفضل.",
                "ℹ️ No guaranteed services here. Try the Best filter.")
        else:
            empty_msg = _L(lang, "ℹ️ لا توجد خدمات في هذه الفئة.", "ℹ️ No services in this category.")
        empty_kb = []
        if sort != "best":
            empty_kb.append([InlineKeyboardButton(
                text=_L(lang, "🏆 عرض كل الخدمات", "🏆 Show all services"),
                callback_data=f"sl:{plat}:{cat_key}:0:best",
            )])
        empty_kb.append(_footer(lang))
        await safe_edit(cb, empty_msg, InlineKeyboardMarkup(inline_keyboard=empty_kb))
        return await cb.answer()

    pages = (total + LIST_SIZE - 1) // LIST_SIZE
    info = PLATFORMS.get(plat, {"ar": plat, "en": plat, "ico": "📱"})
    pn_ar = info["ar"]
    pn_en = info["en"]
    ico_plat = info["ico"]
    cat_ico = _ico(cat)

    t = _L(lang,
        f"{ico_plat} <b>رشق {pn_ar}</b> — {cat_ico} <b>{cat}</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n"
        "🛒 <b>اختر الخدمة لعرض التفاصيل الكاملة والسعر</b>\n\n"
        f"📄 الصفحة {page+1} من {pages}",
        f"{ico_plat} <b>Boost {pn_en}</b> — {cat_ico} <b>{cat}</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n"
        "🛒 <b>Select a service to view full details & price</b>\n\n"
        f"📄 Page {page+1} of {pages}")

    # Filter row
    filter_row = []
    for s in _VALID_SORTS:
        ar_label, en_label = _SORT_LABELS[s]
        label = ar_label if lang == "ar" else en_label
        if s == sort:
            label = f"• {label} •"
        filter_row.append(InlineKeyboardButton(
            text=label,
            callback_data=f"sl:{plat}:{cat_key}:0:{s}" if s != sort else "noop",
        ))

    kb = [filter_row]
    for i, (svc, stats) in enumerate(items):
        # لا نحتاج provider_service هنا — أُزيل الـ await غير اللازم
        short_label = short_service_label(svc.name, lang)
        oc = stats.get("orders_count", 0)
        is_hot = oc > 100
        btn_text = _service_btn_text(short_label, is_hot)
        kb.append([InlineKeyboardButton(
            text=btn_text,
            callback_data=f"sd:{svc.id}:{plat}:{cat_key}:{page}:{sort}")])

    # Pagination
    if pages > 1:
        nav = []
        if page > 0:
            nav.append(InlineKeyboardButton(text="◀️ السابق", callback_data=f"sl:{plat}:{cat_key}:{page-1}:{sort}"))
        nav.append(InlineKeyboardButton(text=f"📄 {page+1}/{pages}", callback_data="noop"))
        if page + 1 < pages:
            nav.append(InlineKeyboardButton(text="التالي ▶️", callback_data=f"sl:{plat}:{cat_key}:{page+1}:{sort}"))
        kb.append(nav)

    kb.append(_footer(lang))

    await safe_edit(cb, t, InlineKeyboardMarkup(inline_keyboard=kb))
    await cb.answer()


# ═════════════════════════════════════════════════════════════════════════════
#  4 · SERVICE DETAIL
# ═════════════════════════════════════════════════════════════════════════════

@router.callback_query(F.data.startswith("sd:"))
async def show_detail(cb: CallbackQuery, db, screen=None, from_back=False):
    data = screen or cb.data
    parts = data.split(":")
    sid = int(parts[1])

    back = None
    if len(parts) >= 5:
        back = f"sl:{parts[2]}:{parts[3]}:{parts[4]}"
        if len(parts) >= 6 and parts[5] in _VALID_SORTS:
            back = f"{back}:{parts[5]}"

    nav_enter(cb.from_user.id, data, push=not from_back)
    user = await get_or_create_user(db, cb.from_user.id)
    lang = user.language or "ar"
    cur = user.currency or "USD"

    svc = await get_service(db, sid)
    if not svc:
        await cb.answer(_L(lang, "الخدمة غير موجودة", "Service not found"), show_alert=True)
        return

    ps = await get_provider_service(db, svc.provider_service_id) if svc.provider_service_id else None
    stats = await get_service_stats(db, sid)
    oc = stats.get("orders_count", 0)
    rt = stats.get("rating")

    if ps:
        fp = _price(ps, user)
        pr_str = _price_display(fp, cur)
        mn = int(ps.min) if ps.min else 100
        mx = int(ps.max) if ps.max else 100000
    else:
        fp = float(svc.price_per_1000)
        pr_str = _price_display(fp, cur)
        mn = 100
        mx = 100000

    display_name = format_service_name(svc.name, lang)
    raw = svc.name or ""
    desc = svc.description or ""

    # Extract real provider data
    speed_str   = _extract_speed(raw, desc)    or _L(lang, "فوري 🚀",   "Instant 🚀")
    quality_str = _extract_quality(raw)
    drop_str    = _extract_drop(raw)
    guarantee_str = _extract_guarantee(raw, ps)
    rating_str  = _rating_stars(rt, oc)

    lvl = get_vip_level(float(user.total_spent or 0))
    pct = get_vip_pct(lvl)

    # Clean description
    clean_desc = ""
    if desc and len(desc.strip()) > 5:
        clean_desc = desc.strip()
        for junk in ["Members |", "Speed |", "Instant Start", "| Start:",
                     "| Speed:", "Start time:", "Average time:"]:
            clean_desc = clean_desc.replace(junk, "").strip()
        while "  " in clean_desc:
            clean_desc = clean_desc.replace("  ", " ")
        if len(clean_desc) > 120:
            clean_desc = clean_desc[:120].rsplit(" ", 1)[0] + "…"

    plat_key = parts[2] if len(parts) > 2 else ""
    info = PLATFORMS.get(plat_key, {"ico": "📦"})
    ico_plat = info["ico"]

    # ── Header ──
    header_lines = [
        f"{ico_plat} <b>{display_name}</b>",
        "━━━━━━━━━━━━━━━━━━━━━━",
    ]
    if clean_desc:
        header_lines.append(f"📝 {clean_desc}")
    header_lines.append(
        _L(lang,
           "\n🤖 <i>أرسل رابط الحساب/المنشور بعد الضغط على طلب</i>",
           "\n🤖 <i>Send your link after tapping Order</i>")
    )
    header = "\n".join(header_lines)

    # ── Inline keyboard table (Tiger style) ──
    kb = []
    cat_name = svc.category or "—"
    cat_ico = _ico(cat_name)

    kb.append([
        InlineKeyboardButton(text=f"{cat_ico} {cat_name}", callback_data="noop"),
        InlineKeyboardButton(text="🔔 النوع", callback_data="noop"),
    ])
    kb.append([
        InlineKeyboardButton(text=f"💰 {pr_str}", callback_data="noop"),
        InlineKeyboardButton(text="💵 سعر / 1000", callback_data="noop"),
    ])
    kb.append([
        InlineKeyboardButton(text=f"📊 {mn:,} — {mx:,}", callback_data="noop"),
        InlineKeyboardButton(text="📊 الحد الأدنى/الأقصى", callback_data="noop"),
    ])
    kb.append([
        InlineKeyboardButton(text=f"🚀 {speed_str}", callback_data="noop"),
        InlineKeyboardButton(text="⚡ السرعة", callback_data="noop"),
    ])
    kb.append([
        InlineKeyboardButton(text=f"✨ {quality_str}", callback_data="noop"),
        InlineKeyboardButton(text="🏆 الجودة", callback_data="noop"),
    ])
    kb.append([
        InlineKeyboardButton(text=f"📉 {drop_str}", callback_data="noop"),
        InlineKeyboardButton(text="📉 نسبة النزول", callback_data="noop"),
    ])
    kb.append([
        InlineKeyboardButton(text=f"♻️ {guarantee_str}", callback_data="noop"),
        InlineKeyboardButton(text="🛡️ الضمان", callback_data="noop"),
    ])
    kb.append([
        InlineKeyboardButton(text=f"⏰ فوري", callback_data="noop"),
        InlineKeyboardButton(text="⏱️ وقت البدء", callback_data="noop"),
    ])
    kb.append([
        InlineKeyboardButton(text=f"🏅 {rating_str}", callback_data="noop"),
        InlineKeyboardButton(text="⭐ التقييم", callback_data="noop"),
    ])

    if pct > 0:
        vip_name = get_vip_name(lvl, lang)
        kb.append([
            InlineKeyboardButton(text=f"👑 {vip_name} — خصم {pct}%", callback_data="noop"),
            InlineKeyboardButton(text="🎁 خصم VIP", callback_data="noop"),
        ])

    kb.append([InlineKeyboardButton(
        text=_L(lang, "🛒 ✦ اطلب الآن ✦", "🛒 ✦ Order Now ✦"),
        callback_data=f"order:{svc.id}")])
    kb.append(_footer(lang))

    await safe_edit(cb, header, InlineKeyboardMarkup(inline_keyboard=kb))
    await cb.answer()


# ─── Legacy compatibility ─────────────────────────────────────────────────────

@router.callback_query(F.data.startswith("svc:"))
async def legacy_svc(cb: CallbackQuery, db, screen=None, from_back=False):
    data = screen or cb.data
    parts = data.split(":")
    new = f"sd:{parts[1]}"
    if len(parts) >= 5:
        new = f"sd:{parts[1]}:{parts[2]}:{parts[3]}:{parts[4]}"
    await show_detail(cb, db, screen=new, from_back=from_back)


@router.callback_query(F.data.startswith("svcl:"))
async def legacy_svclist(cb: CallbackQuery, db, screen=None, from_back=False):
    data = screen or cb.data
    parts = data.split(":")
    new = f"sl:{parts[1]}:{parts[2]}:0"
    await show_list(cb, db, screen=new, from_back=from_back)


@router.callback_query(F.data.startswith("svcp:"))
async def legacy_svcpage(cb: CallbackQuery, db, screen=None, from_back=False):
    data = screen or cb.data
    parts = data.split(":")
    new = f"sl:{parts[1]}:{parts[2]}:{parts[3]}"
    await show_list(cb, db, screen=new, from_back=from_back)


def register_screens():
    register_screen("new_order", show_platforms)
    register_screen("plt:", choose_category)
    register_screen("sl:", show_list)
    register_screen("sd:", show_detail)


register_screens()  # auto-register on import
