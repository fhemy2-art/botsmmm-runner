"""
Service import logic — smart bulk import from providers.

Key improvements vs. old version:
- Names are UNIQUE: emoji + Arabic category + original provider name (trimmed)
- Speed / Quality / Guarantee extracted from real provider name, not hardcoded
- Description auto-generated in Arabic from extracted attributes
- Category detection improved with more aliases and two-pass matching
- Auto-add limit raised to 5 per (platform, category) group
"""
import re
import logging
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func

from models.service import Service
from models.provider_service import ProviderService
from repositories.provider_repo import get_active_providers, get_provider_categories

logger = logging.getLogger(__name__)

# ─── Platform map ─────────────────────────────────────────────────────────────

PLATFORM_MAP = {
    "instagram":  {"ar": "انستقرام",     "emoji": "📸"},
    "tiktok":     {"ar": "تيك توك",      "emoji": "🎵"},
    "telegram":   {"ar": "تيليجرام",     "emoji": "💬"},
    "youtube":    {"ar": "يوتيوب",       "emoji": "▶️"},
    "twitter":    {"ar": "تويتر / X",    "emoji": "🐦"},
    "facebook":   {"ar": "فيسبوك",       "emoji": "📘"},
    "whatsapp":   {"ar": "واتساب",       "emoji": "🟢"},
    "threads":    {"ar": "ثريدز",        "emoji": "🪩"},
    "snapchat":   {"ar": "سناب شات",     "emoji": "👻"},
    "linkedin":   {"ar": "لينكدإن",      "emoji": "💼"},
    "spotify":    {"ar": "سبوتيفاي",     "emoji": "🎧"},
    "soundcloud": {"ar": "ساوند كلاود",  "emoji": "🎸"},
    "pinterest":  {"ar": "بينتريست",     "emoji": "📌"},
    "twitch":     {"ar": "تويتش",        "emoji": "🎮"},
    "discord":    {"ar": "ديسكورد",      "emoji": "💜"},
}

# Platform keyword aliases (longer/more specific first)
# Includes both English and Arabic names for each platform
_PLATFORM_ALIASES: list[tuple[str, str]] = [
    # ── Instagram ──
    ("instagram", "instagram"), ("instagram", " ig "), ("instagram", " ig_"),
    ("instagram", "إنستغرام"), ("instagram", "انستغرام"),
    ("instagram", "إنستقرام"), ("instagram", "انستقرام"),
    ("instagram", "انستا"), ("instagram", "إنستا"),
    # ── TikTok ──
    ("tiktok", "tiktok"), ("tiktok", "tik tok"), ("tiktok", " tt "),
    ("tiktok", "تيك توك"), ("tiktok", "تيكتوك"),
    # ── Telegram ──
    ("telegram", "telegram"), ("telegram", " tg "),
    ("telegram", "تيليجرام"), ("telegram", "تليجرام"),
    ("telegram", "تلجرام"), ("telegram", "تلقرام"),
    # ── YouTube ──
    ("youtube", "youtube"), ("youtube", " yt "),
    ("youtube", "يوتيوب"),
    # ── Twitter / X ──
    ("twitter", "twitter"), ("twitter", " tw "), ("twitter", " x "),
    ("twitter", "تويتر"),
    # ── Facebook ──
    ("facebook", "facebook"), ("facebook", " fb "),
    ("facebook", "فيسبوك"), ("facebook", "فيس بوك"),
    # ── WhatsApp ──
    ("whatsapp", "whatsapp"), ("whatsapp", " wa "),
    ("whatsapp", "واتساب"), ("whatsapp", "واتس اب"), ("whatsapp", "واتس"),
    # ── Threads ──
    ("threads", "threads"),
    ("threads", "ثريدز"),
    # ── Snapchat ──
    ("snapchat", "snapchat"), ("snapchat", " sc "),
    ("snapchat", "سناب شات"), ("snapchat", "سنابشات"), ("snapchat", "سناب"),
    # ── LinkedIn ──
    ("linkedin", "linkedin"),
    ("linkedin", "لينكدإن"), ("linkedin", "لينكد"),
    # ── Spotify ──
    ("spotify", "spotify"),
    ("spotify", "سبوتيفاي"),
    # ── SoundCloud ──
    ("soundcloud", "soundcloud"),
    ("soundcloud", "ساوند كلاود"),
    # ── Pinterest ──
    ("pinterest", "pinterest"),
    ("pinterest", "بينتريست"), ("pinterest", "بنترست"),
    # ── Twitch ──
    ("twitch", "twitch"),
    ("twitch", "تويتش"),
    # ── Discord ──
    ("discord", "discord"),
    ("discord", "ديسكورد"),
]

# ─── Category map ──────────────────────────────────────────────────────────────

# Ordered by priority — MORE SPECIFIC (longer) keywords FIRST
_CAT_KEYWORDS: list[tuple[str, str]] = [
    # Watch time (must come before "watch" and "view")
    ("watch time",   "وقت مشاهدة"),
    ("hours watch",  "وقت مشاهدة"),
    ("watch hour",   "وقت مشاهدة"),
    ("4000 hour",    "وقت مشاهدة"),
    ("وقت مشاهدة",  "وقت مشاهدة"),
    # Subscribers / Members (before followers)
    ("subscriber",   "مشتركين"),
    ("member",       "أعضاء"),
    ("أعضاء",        "أعضاء"),
    ("مشتركين",      "مشتركين"),
    # Followers
    ("followers",    "متابعين"),
    ("follower",     "متابعين"),
    ("follow",       "متابعين"),
    ("fans",         "متابعين"),
    ("متابعين",      "متابعين"),
    ("متابعات",      "متابعين"),
    # Likes
    ("likes",        "إعجابات"),
    ("like",         "إعجابات"),
    ("heart",        "إعجابات"),
    ("إعجابات",      "إعجابات"),
    ("لايكات",       "إعجابات"),
    ("لايك",         "إعجابات"),
    # Views (after watch time)
    ("reel view",    "مشاهدات"),
    ("video view",   "مشاهدات"),
    ("impression",   "مشاهدات"),
    ("views",        "مشاهدات"),
    ("view",         "مشاهدات"),
    ("watch",        "مشاهدات"),
    ("مشاهدات",      "مشاهدات"),
    # Comments
    ("comment",      "تعليقات"),
    ("تعليقات",      "تعليقات"),
    ("تعليق",        "تعليقات"),
    # Shares / Reposts
    ("retweet",      "مشاركات"),
    ("repost",       "مشاركات"),
    ("share",        "مشاركات"),
    ("إعادة تغريد",  "مشاركات"),
    ("إعادة نشر",    "مشاركات"),
    ("مشاركات",      "مشاركات"),
    # Reactions
    ("reaction",     "تفاعلات"),
    ("تفاعلات",      "تفاعلات"),
    ("رياكشن",       "تفاعلات"),
    # Stories
    ("stories",      "ستوري"),
    ("story",        "ستوري"),
    ("stor",         "ستوري"),
    ("ستوري",        "ستوري"),
    # Streams / Plays
    ("stream",       "بث مباشر"),
    ("بث مباشر",     "بث مباشر"),
    ("plays",        "استماعات"),
    ("play",         "استماعات"),
    ("listen",       "استماعات"),
    ("استماعات",     "استماعات"),
    # Traffic / Visits
    ("traffic",      "زيارات"),
    ("visit",        "زيارات"),
    ("click",        "زيارات"),
    ("زيارات",       "زيارات"),
    # Saves
    ("save",         "حفظ"),
    ("حفظ",          "حفظ"),
    # Mentions / Tags
    ("mention",      "إشارات"),
    ("إشارات",       "إشارات"),
    # Votes / Polls
    ("vote",         "استفتاءات"),
    ("poll",         "استفتاءات"),
    ("تصويت",        "استفتاءات"),
    ("استفتاء",      "استفتاءات"),
    # Boost
    ("boost",        "تعزيز"),
    ("تعزيز",        "تعزيز"),
    ("بوست",         "تعزيز"),
]

CAT_AR_MAP: dict[str, str] = {kw: ar for kw, ar in _CAT_KEYWORDS}


# ─── Detection helpers ────────────────────────────────────────────────────────

def detect_platform(text: str) -> str:
    tl = " " + text.lower() + " "
    for plat, alias in _PLATFORM_ALIASES:
        # Arabic aliases don't need word-boundary spaces — check in raw text too
        if alias in tl or alias in text:
            return plat
    for plat in PLATFORM_MAP:
        if plat in tl:
            return plat
    return "other"


def detect_category_ar(text: str) -> str:
    tl = text.lower()
    for kw, ar in _CAT_KEYWORDS:
        if kw in tl:
            return ar
    return "خدمات"


# ─── Attribute extraction ─────────────────────────────────────────────────────

def extract_service_attributes(name: str, category: str = "") -> dict:
    """
    Extract real speed / quality / guarantee_days / description from provider name.
    Nothing is hardcoded — everything comes from the original text.
    """
    nl = (name + " " + category).lower()

    # ── Speed ──
    if any(k in nl for k in ("instant", "immediately", "real time", "realtime")):
        speed = "فوري ⚡"
    elif "1 hour" in nl or "1h " in nl or " 1h" in nl:
        speed = "خلال ساعة"
    elif any(k in nl for k in ("24h", "24 hour", "1 day", "same day")):
        speed = "خلال يوم"
    elif any(k in nl for k in ("slow", "gradual", "drip", "natural")):
        speed = "تدريجي 🐢"
    elif "fast" in nl:
        speed = "سريع"
    else:
        speed = "سريع"

    # ── Quality ──
    if "high quality" in nl or " hq" in nl or "hq " in nl:
        quality = "عالية الجودة 🏆"
    elif any(k in nl for k in ("real people", "real user", "genuine", "non drop", "nondrop")):
        quality = "حقيقية ✅"
    elif "real" in nl and "bot" not in nl:
        quality = "حقيقية ✅"
    elif any(k in nl for k in ("arab", "arabic", "middle east", "mena")):
        quality = "عربية 🌍"
    elif any(k in nl for k in ("bot", "auto generated")):
        quality = "بوت ⚙️"
    elif "mix" in nl:
        quality = "مخلوطة"
    elif any(k in nl for k in ("worldwide", "global", "international")):
        quality = "عالمية 🌐"
    elif "low quality" in nl or " lq" in nl:
        quality = "اقتصادية"
    else:
        quality = "قياسية"

    # ── Guarantee ──
    guarantee_days = 0
    if "lifetime" in nl or "life time" in nl:
        guarantee_days = 365
    else:
        # Look for patterns like "90 day", "90d", "30days"
        m = re.search(r"(\d+)\s*day", nl)
        if m:
            guarantee_days = int(m.group(1))
        elif re.search(r"(\d+)d\b", nl):
            m2 = re.search(r"(\d+)d\b", nl)
            if m2:
                guarantee_days = int(m2.group(1))

        if guarantee_days == 0:
            if "refill" in nl or "guarantee" in nl or "warranty" in nl:
                if "no refill" not in nl and "no guarantee" not in nl:
                    guarantee_days = 30

    # ── Description (Arabic) ──
    cat_ar = detect_category_ar(nl)
    plat = detect_platform(nl)
    plat_ar = PLATFORM_MAP.get(plat, {}).get("ar", "")

    desc_parts: list[str] = []
    if quality != "قياسية":
        desc_parts.append(quality)
    desc_parts.append(f"⚡ {speed}")
    if guarantee_days > 0:
        desc_parts.append(f"♻️ ضمان {guarantee_days} يوم")
    if plat_ar:
        desc_parts.append(f"| {plat_ar}")

    description = "  ".join(desc_parts) if desc_parts else None

    # ── description_ar: attractive Arabic marketing text ──
    description_ar = generate_arabic_description(cat_ar, plat_ar, quality, speed, guarantee_days)

    return {
        "speed":          speed,
        "quality":        quality,
        "guarantee_days": guarantee_days,
        "description":    description,
        "description_ar": description_ar,
    }


def generate_arabic_description(cat_ar: str, plat_ar: str, quality: str, speed: str, guarantee_days: int) -> str:
    """Generate an attractive Arabic marketing description for a service."""
    # Build catchy description based on service attributes
    parts = []

    # Quality-based opening
    quality_phrases = {
        "عالية الجودة 🏆": "جودة عالية ومضمونة",
        "حقيقية ✅": "حسابات حقيقية وفعالة",
        "عربية 🌍": "حسابات عربية حقيقية ومستهدفة",
        "عالمية 🌐": "حسابات عالمية متنوعة",
        "بوت ⚙️": "تنفيذ سريع وآلي",
        "قياسية": "خدمة موثوقة ومستقرة",
        "مخلوطة": "مزيج من حسابات متنوعة",
        "اقتصادية": "خدمة اقتصادية بسعر مناسب",
    }
    parts.append(quality_phrases.get(quality, "خدمة موثوقة"))

    # Category + platform combo
    if plat_ar:
        parts.append(f"زيادة {cat_ar} {plat_ar}")
    else:
        parts.append(f"زيادة {cat_ar}")

    # Speed info
    speed_phrases = {
        "فوري ⚡": "بدء فوري وتنفيذ سريع",
        "خلال ساعة": "تنفيذ خلال ساعة واحدة",
        "خلال يوم": "تنفيذ خلال 24 ساعة",
        "تدريجي 🐢": "زيادة تدريجية وطبيعية",
        "سريع": "سرعة فائقة في التنفيذ",
    }
    parts.append(speed_phrases.get(speed, "سرعة فائقة"))

    # Guarantee
    if guarantee_days >= 365:
        parts.append("ضمان مدى الحياة")
    elif guarantee_days > 0:
        parts.append(f"ضمان التعويض {guarantee_days} يوم")

    return " - ".join(parts)


# ─── Name builder ─────────────────────────────────────────────────────────────

def _strip_word(text: str, word: str) -> str:
    """Remove `word` from the start of `text` only if it ends at a word boundary."""
    tl = text.lower()
    wl = word.lower()
    if tl.startswith(wl):
        rest = text[len(wl):]
        if not rest or not rest[0].isalpha():
            return rest.lstrip(" -–|:")
    return text


def build_service_name(raw_name: str, category: str = "") -> str:
    """
    Build a UNIQUE, readable name:
      [emoji] [AR category] — [cleaned original name]

    The original name is kept (trimmed) to ensure no two services
    end up with identical names.
    """
    full = raw_name + " " + category
    platform = detect_platform(full)
    cat_ar   = detect_category_ar(full)
    emoji    = PLATFORM_MAP.get(platform, {}).get("emoji", "⚡")

    # Strip leading platform keyword from original name for brevity
    clean = raw_name.strip()
    for plat_key in PLATFORM_MAP:
        variants = [plat_key.capitalize(), plat_key.upper(), plat_key,
                    PLATFORM_MAP[plat_key]["ar"]]
        for v in variants:
            result = _strip_word(clean, v)
            if result != clean:
                clean = result
                break

    # Strip leading category keyword (word-boundary safe)
    for kw, _ in _CAT_KEYWORDS:
        result = _strip_word(clean, kw)
        if result != clean:
            clean = result
            break

    clean = clean.strip(" -–|:")

    if clean:
        name = f"{emoji} {cat_ar} — {clean}"
    else:
        name = f"{emoji} {cat_ar}"

    return name[:100]


# backward-compat alias used in other files
def translate_service_name(name: str, category: str = "") -> str:
    return build_service_name(name, category)


# ─── Auto-add ─────────────────────────────────────────────────────────────────

AUTO_ADD_PER_GROUP = 5   # was 2


async def auto_add_services(db: AsyncSession) -> tuple[int, int, dict[str, int]]:
    """
    Smart auto-add:
    • Groups provider services by (platform, category_ar)
    • Picks up to AUTO_ADD_PER_GROUP cheapest per group
    • Skips already-added ones
    • Uses real attribute extraction for speed/quality/guarantee
    Returns (added_total, skipped_total, platform_summary).
    """
    providers = await get_active_providers(db)
    added_total  = 0
    skipped_total = 0
    platform_summary: dict[str, int] = {}
    to_add: list[Service] = []

    for provider in providers:
        cats = await get_provider_categories(db, provider.id)

        # Group raw provider categories → (platform, category_ar)
        groups: dict[tuple[str, str], list[str]] = {}
        for cat in cats:
            plat     = detect_platform(cat)
            cat_type = detect_category_ar(cat)
            groups.setdefault((plat, cat_type), []).append(cat)

        for (plat, cat_type), cat_list in groups.items():
            if plat == "other":
                continue

            result = await db.execute(
                select(ProviderService)
                .where(
                    ProviderService.provider_id == provider.id,
                    ProviderService.category.in_(cat_list),
                    ProviderService.rate.isnot(None),
                )
                .order_by(ProviderService.rate)
                .limit(AUTO_ADD_PER_GROUP * 3)    # fetch extra to account for skips
            )
            candidates = result.scalars().all()

            added_in_group = 0
            for ps in candidates:
                if added_in_group >= AUTO_ADD_PER_GROUP:
                    break
                if ps.rate is None:
                    continue
                # rate=0 is valid — free service from provider

                already = await db.scalar(
                    select(func.count()).select_from(Service)
                    .where(Service.provider_service_id == ps.id)
                )
                if already:
                    skipped_total += 1
                    continue

                attrs = extract_service_attributes(ps.name, ps.category or "")
                svc_name = build_service_name(ps.name, ps.category or "")
                from services.settings_manager import get_markup_multiplier
                markup_rate = round(float(ps.rate) * get_markup_multiplier(), 6)

                svc = Service(
                    name=svc_name,
                    platform=plat,
                    category=cat_type,
                    description=attrs["description"],
                    description_ar=attrs.get("description_ar", ""),
                    price_per_1000=markup_rate,
                    provider_service_id=ps.id,
                    speed=attrs["speed"],
                    quality=attrs["quality"],
                    guarantee_days=attrs["guarantee_days"],
                    is_active=True,
                )
                to_add.append(svc)
                added_in_group += 1
                added_total += 1

                plat_info  = PLATFORM_MAP.get(plat, {"ar": plat, "emoji": "📱"})
                key_label  = f"{plat_info['emoji']} {plat_info['ar']}"
                platform_summary[key_label] = platform_summary.get(key_label, 0) + 1

                # Batch commit every 100
                if len(to_add) >= 100:
                    db.add_all(to_add)
                    await db.commit()
                    to_add.clear()

    if to_add:
        db.add_all(to_add)
        await db.commit()

    return added_total, skipped_total, platform_summary
