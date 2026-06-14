"""
Free Services Seeder — provider presets only.
No fake/dummy services. Free services come exclusively from real API providers
that return rate=0 in their service catalogue.
"""
import logging

logger = logging.getLogger(__name__)

# ─── Known providers that have free (rate=0) or very cheap services ──────────
# Admin must register on each site, get their own API key, then add it via bot.
# After adding + syncing, any service with rate=0 auto-appears in the 🎁 tab.

PROVIDER_PRESETS: list[dict] = [
    {
        "name": "🆓 Peakerr",
        "api_url": "https://peakerr.com/api/v2",
        "website": "https://peakerr.com",
        "note": "يوجد خدمات بسعر $0 — سجّل واحصل على مفتاح API مجاناً",
        "free": True,
    },
    {
        "name": "🆓 JustAnotherPanel",
        "api_url": "https://justanotherpanel.com/api/v2",
        "website": "https://justanotherpanel.com",
        "note": "أسعار تبدأ من $0.001 — سجّل واحصل على مفتاح",
        "free": True,
    },
    {
        "name": "🆓 SMMKings",
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


def get_provider_presets() -> list[dict]:
    return PROVIDER_PRESETS


def get_free_provider_presets() -> list[dict]:
    return [p for p in PROVIDER_PRESETS if p.get("free")]


async def delete_fake_free_services(db) -> int:
    """
    Delete all free services that have NO provider_service_id.
    These are the fake/dummy pre-seeded services.
    Real free services come from providers and have provider_service_id set.
    Returns count of deleted services.
    """
    from sqlalchemy import delete, select, func
    from sqlalchemy.ext.asyncio import AsyncSession
    from decimal import Decimal
    from models.service import Service

    result = await db.execute(
        select(func.count()).select_from(Service).where(
            Service.price_per_1000 == Decimal("0"),
            Service.provider_service_id.is_(None),
        )
    )
    count = result.scalar() or 0

    if count > 0:
        await db.execute(
            delete(Service).where(
                Service.price_per_1000 == Decimal("0"),
                Service.provider_service_id.is_(None),
            )
        )
        await db.commit()
        logger.info("delete_fake_free_services: deleted %s fake free services", count)

    return count
