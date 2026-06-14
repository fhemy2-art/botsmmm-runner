"""
Free Services Seeder — seeds guaranteed-working free/demo services.
These are manually-fulfilled services with $0 cost for users.
Run via admin panel: /seedfree  or adm:seed_free
"""
import logging
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func

from models.service import Service

logger = logging.getLogger(__name__)

# ─── Free services catalogue ──────────────────────────────────────────────────
# These are real service types offered for free as a welcome / demo for new users.
# The admin fulfills them manually or via a free-tier SMM panel.

FREE_SERVICES: list[dict] = [
    # ── Instagram ──
    {
        "name": "📸 متابعين انستقرام مجاني | 50 متابع",
        "platform": "instagram",
        "category": "متابعين",
        "description": "خدمة مجانية — 50 متابع انستقرام حقيقي للحسابات الجديدة. مرة واحدة لكل مستخدم.",
        "price_per_1000": 0.00,
        "sort_order": 0,
    },
    {
        "name": "📸 إعجابات انستقرام مجانية | 100 إعجاب",
        "platform": "instagram",
        "category": "إعجابات",
        "description": "خدمة مجانية — 100 إعجاب على منشورك. مرة واحدة لكل مستخدم.",
        "price_per_1000": 0.00,
        "sort_order": 0,
    },
    # ── TikTok ──
    {
        "name": "🎵 متابعين تيك توك مجاني | 50 متابع",
        "platform": "tiktok",
        "category": "متابعين",
        "description": "خدمة مجانية — 50 متابع تيك توك. مرة واحدة لكل مستخدم.",
        "price_per_1000": 0.00,
        "sort_order": 0,
    },
    {
        "name": "🎵 مشاهدات تيك توك مجانية | 500 مشاهدة",
        "platform": "tiktok",
        "category": "مشاهدات",
        "description": "خدمة مجانية — 500 مشاهدة تيك توك للفيديو. مرة واحدة لكل مستخدم.",
        "price_per_1000": 0.00,
        "sort_order": 0,
    },
    # ── Telegram ──
    {
        "name": "💬 أعضاء تيليجرام مجاني | 50 عضو",
        "platform": "telegram",
        "category": "أعضاء",
        "description": "خدمة مجانية — 50 عضو لقناتك أو مجموعتك. مرة واحدة لكل مستخدم.",
        "price_per_1000": 0.00,
        "sort_order": 0,
    },
    {
        "name": "💬 مشاهدات منشور تيليجرام مجانية | 500",
        "platform": "telegram",
        "category": "مشاهدات",
        "description": "خدمة مجانية — 500 مشاهدة على منشور تيليجرام. مرة واحدة لكل مستخدم.",
        "price_per_1000": 0.00,
        "sort_order": 0,
    },
    # ── YouTube ──
    {
        "name": "▶️ مشتركين يوتيوب مجاني | 10 مشترك",
        "platform": "youtube",
        "category": "مشتركين",
        "description": "خدمة مجانية — 10 مشترك يوتيوب. مرة واحدة لكل مستخدم.",
        "price_per_1000": 0.00,
        "sort_order": 0,
    },
    {
        "name": "▶️ مشاهدات يوتيوب مجانية | 100 مشاهدة",
        "platform": "youtube",
        "category": "مشاهدات",
        "description": "خدمة مجانية — 100 مشاهدة يوتيوب. مرة واحدة لكل مستخدم.",
        "price_per_1000": 0.00,
        "sort_order": 0,
    },
    # ── Twitter/X ──
    {
        "name": "🐦 متابعين تويتر/X مجاني | 50 متابع",
        "platform": "twitter",
        "category": "متابعين",
        "description": "خدمة مجانية — 50 متابع تويتر/X. مرة واحدة لكل مستخدم.",
        "price_per_1000": 0.00,
        "sort_order": 0,
    },
    # ── Facebook ──
    {
        "name": "📘 إعجابات صفحة فيسبوك مجانية | 50",
        "platform": "facebook",
        "category": "إعجابات",
        "description": "خدمة مجانية — 50 إعجاب على صفحتك. مرة واحدة لكل مستخدم.",
        "price_per_1000": 0.00,
        "sort_order": 0,
    },
]

# ─── Also add known cheap real providers as presets ───────────────────────────
# These need a real API key to work — admin must set them up
PROVIDER_PRESETS: list[dict] = [
    {
        "name": "SMMTarget (Free Trial)",
        "api_url": "https://smmtarget.net/api/v2",
        "note": "يحتاج مفتاح API — أضف مفتاحك من الموقع",
    },
    {
        "name": "SocialPanel.io",
        "api_url": "https://socialpanel.io/api/v2",
        "note": "يحتاج مفتاح API",
    },
    {
        "name": "JustAnotherPanel",
        "api_url": "https://justanotherpanel.com/api/v2",
        "note": "لديه خدمات رخيصة جداً",
    },
    {
        "name": "Peakerr",
        "api_url": "https://peakerr.com/api/v2",
        "note": "خدمات مجانية وشبه مجانية",
    },
]


async def seed_free_services(db: AsyncSession) -> tuple[int, int]:
    """
    Seed free services into the database.
    Returns (added, already_existed) counts.
    Skips services that already exist (by name).
    """
    # Get existing free service names
    result = await db.execute(
        select(Service.name).where(
            Service.is_active == True,
            Service.price_per_1000 == 0,
        )
    )
    existing_names = {r[0] for r in result.all()}

    added = 0
    skipped = 0

    for svc_data in FREE_SERVICES:
        if svc_data["name"] in existing_names:
            skipped += 1
            continue

        svc = Service(
            name=svc_data["name"],
            platform=svc_data["platform"],
            category=svc_data["category"],
            description=svc_data["description"],
            price_per_1000=svc_data["price_per_1000"],
            is_active=True,
            sort_order=svc_data.get("sort_order", 0),
        )
        db.add(svc)
        added += 1

    if added > 0:
        await db.commit()

    logger.info("seed_free_services: added=%s skipped=%s", added, skipped)
    return added, skipped


def get_provider_presets() -> list[dict]:
    """Return list of known SMM provider presets (name + URL)."""
    return PROVIDER_PRESETS
