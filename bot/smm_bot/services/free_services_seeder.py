"""
Free Services Seeder v2
────────────────────────
Seeds 10 pre-made $0 services AND stores a catalogue of known free/cheap
SMM providers with their API URLs so the admin can add them in one click.

HOW FREE SERVICES WORK:
  • Services with price_per_1000 = 0.00 appear in the 🎁 Free tab.
  • Orders are placed normally; the admin fulfills them (manually or via provider).
  • If a synced provider has services with rate=0, they auto-appear here too.
"""
import logging
from decimal import Decimal
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from models.service import Service

logger = logging.getLogger(__name__)

# ─── Free services catalogue ─────────────────────────────────────────────────
FREE_SERVICES: list[dict] = [
    # ── Instagram ──
    {"name": "📸 متابعين إنستقرام مجاني — 50 متابع",       "platform": "instagram", "category": "متابعين",   "min_q": 50,   "max_q": 50},
    {"name": "📸 إعجابات إنستقرام مجانية — 100 إعجاب",     "platform": "instagram", "category": "إعجابات",   "min_q": 100,  "max_q": 100},
    {"name": "📸 مشاهدات ريلز مجانية — 500 مشاهدة",        "platform": "instagram", "category": "مشاهدات",   "min_q": 500,  "max_q": 500},
    # ── TikTok ──
    {"name": "🎵 متابعين تيك توك مجاني — 50 متابع",        "platform": "tiktok",    "category": "متابعين",   "min_q": 50,   "max_q": 50},
    {"name": "🎵 مشاهدات تيك توك مجانية — 500 مشاهدة",    "platform": "tiktok",    "category": "مشاهدات",   "min_q": 500,  "max_q": 500},
    {"name": "🎵 إعجابات تيك توك مجانية — 100 إعجاب",     "platform": "tiktok",    "category": "إعجابات",   "min_q": 100,  "max_q": 100},
    # ── Telegram ──
    {"name": "💬 أعضاء تيليجرام مجاني — 50 عضو",           "platform": "telegram",  "category": "أعضاء",     "min_q": 50,   "max_q": 50},
    {"name": "💬 مشاهدات منشور تيليجرام — 500 مشاهدة",    "platform": "telegram",  "category": "مشاهدات",   "min_q": 500,  "max_q": 500},
    # ── YouTube ──
    {"name": "▶️ مشتركين يوتيوب مجاني — 10 مشترك",        "platform": "youtube",   "category": "مشتركين",   "min_q": 10,   "max_q": 10},
    {"name": "▶️ مشاهدات يوتيوب مجانية — 100 مشاهدة",    "platform": "youtube",   "category": "مشاهدات",   "min_q": 100,  "max_q": 100},
    # ── Twitter/X ──
    {"name": "🐦 متابعين تويتر/X مجاني — 50 متابع",        "platform": "twitter",   "category": "متابعين",   "min_q": 50,   "max_q": 50},
    {"name": "🐦 إعجابات تويتر/X مجانية — 100 إعجاب",     "platform": "twitter",   "category": "إعجابات",   "min_q": 100,  "max_q": 100},
    # ── Facebook ──
    {"name": "📘 إعجابات صفحة فيسبوك مجانية — 50",         "platform": "facebook",  "category": "إعجابات",   "min_q": 50,   "max_q": 50},
    {"name": "📘 متابعين فيسبوك مجاني — 50 متابع",         "platform": "facebook",  "category": "متابعين",   "min_q": 50,   "max_q": 50},
    # ── Snapchat ──
    {"name": "👻 متابعين سناب مجاني — 50 متابع",           "platform": "snapchat",  "category": "متابعين",   "min_q": 50,   "max_q": 50},
    # ── WhatsApp ──
    {"name": "💚 أعضاء واتساب قناة مجاني — 50 عضو",        "platform": "whatsapp",  "category": "أعضاء",     "min_q": 50,   "max_q": 50},
    # ── Threads ──
    {"name": "🔗 متابعين ثريدز مجاني — 50 متابع",          "platform": "threads",   "category": "متابعين",   "min_q": 50,   "max_q": 50},
    # ── Spotify ──
    {"name": "🎧 متابعين سبوتيفاي مجاني — 50 متابع",       "platform": "spotify",   "category": "متابعين",   "min_q": 50,   "max_q": 50},
    # ── LinkedIn ──
    {"name": "💼 متابعين لينكدإن مجاني — 50 متابع",         "platform": "linkedin",  "category": "متابعين",   "min_q": 50,   "max_q": 50},
    # ── Discord ──
    {"name": "🎮 أعضاء ديسكورد مجاني — 50 عضو",            "platform": "discord",   "category": "أعضاء",     "min_q": 50,   "max_q": 50},
]

FREE_DESC = "✅ خدمة مجانية | مرة واحدة لكل مستخدم | وقت التسليم: 1-24 ساعة"

# ─── Known free/cheap SMM providers ─────────────────────────────────────────
# These panels are known to have free or very cheap services.
# The admin must register on each site and get their own API key.
PROVIDER_PRESETS: list[dict] = [
    {
        "name": "🆓 Peakerr — مجاني/رخيص",
        "api_url": "https://peakerr.com/api/v2",
        "website": "https://peakerr.com",
        "note": "يوجد خدمات مجانية (rate=0) — سجّل واحصل على مفتاح API",
        "free": True,
    },
    {
        "name": "🆓 JustAnotherPanel — أرخص SMM",
        "api_url": "https://justanotherpanel.com/api/v2",
        "website": "https://justanotherpanel.com",
        "note": "أسعار تبدأ من $0.001 — مجاني تقريباً. سجّل واحصل على مفتاح",
        "free": True,
    },
    {
        "name": "🆓 SMMKings — ملك الأسعار الرخيصة",
        "api_url": "https://smmkings.com/api/v2",
        "website": "https://smmkings.com",
        "note": "خدمات مجانية ورخيصة جداً لجميع المنصات",
        "free": True,
    },
    {
        "name": "🆓 FollowersFace",
        "api_url": "https://followersface.com/api/v2",
        "website": "https://followersface.com",
        "note": "خدمات مجانية للمستخدمين الجدد",
        "free": True,
    },
    {
        "name": "💲 SocialPanel.io",
        "api_url": "https://socialpanel.io/api/v2",
        "website": "https://socialpanel.io",
        "note": "خدمات رخيصة جداً",
        "free": False,
    },
    {
        "name": "💲 SMMTarget",
        "api_url": "https://smmtarget.net/api/v2",
        "website": "https://smmtarget.net",
        "note": "مزود موثوق بأسعار منافسة",
        "free": False,
    },
    {
        "name": "💲 Growr",
        "api_url": "https://growr.io/api/v2",
        "website": "https://growr.io",
        "note": "متخصص في إنستقرام وتيك توك",
        "free": False,
    },
    {
        "name": "💲 DripFeedz",
        "api_url": "https://dripfeedz.com/api/v2",
        "website": "https://dripfeedz.com",
        "note": "خدمات drip feed تدريجية",
        "free": False,
    },
]


async def seed_free_services(db: AsyncSession) -> tuple[int, int]:
    """
    Seed free services. Returns (added, already_existed).
    Skips duplicates by name.
    """
    result = await db.execute(
        select(Service.name).where(Service.price_per_1000 == 0)
    )
    existing_names = {r[0] for r in result.all()}

    added = skipped = 0
    for svc_data in FREE_SERVICES:
        if svc_data["name"] in existing_names:
            skipped += 1
            continue
        svc = Service(
            name=svc_data["name"],
            platform=svc_data["platform"],
            category=svc_data["category"],
            description=FREE_DESC,
            price_per_1000=Decimal("0"),
            is_active=True,
            sort_order=0,
        )
        db.add(svc)
        added += 1

    if added > 0:
        await db.commit()

    logger.info("seed_free_services: added=%s skipped=%s", added, skipped)
    return added, skipped


def get_provider_presets() -> list[dict]:
    return PROVIDER_PRESETS


def get_free_provider_presets() -> list[dict]:
    return [p for p in PROVIDER_PRESETS if p.get("free")]
