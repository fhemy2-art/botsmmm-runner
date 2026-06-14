"""
Service repository — all DB access for Service and ProviderService models.
Improved with store stats (orders count, ratings) and caching.
"""
import logging
import time as _time_mod
from sqlalchemy import select, func, or_, desc
from sqlalchemy.ext.asyncio import AsyncSession

from models.service import Service
from models.provider_service import ProviderService
from models.order import Order
from models.service_review import ServiceReview

logger = logging.getLogger(__name__)

# Simple TTL Cache for store stats to improve performance
_stats_cache = {}
CACHE_TTL = 120  # 2 minutes

# ── Short-lived cache for platform/category lookups (30s TTL) ─────────────────
_PLATFORM_CACHE: tuple[set[str], float] | None = None
_CATEGORY_CACHE: dict[str, tuple[list[str], float]] = {}
_META_TTL = 30  # seconds


async def get_active_platforms(db: AsyncSession) -> set[str]:
    global _PLATFORM_CACHE
    now = _time_mod.time()
    if _PLATFORM_CACHE and now < _PLATFORM_CACHE[1]:
        return _PLATFORM_CACHE[0]
    result = await db.execute(
        select(Service.platform).where(Service.is_active == True).distinct()
    )
    platforms = {row[0] for row in result.all()}
    _PLATFORM_CACHE = (platforms, now + _META_TTL)
    return platforms


async def get_categories_for_platform(db: AsyncSession, platform: str) -> list[str]:
    now = _time_mod.time()
    cached = _CATEGORY_CACHE.get(platform)
    if cached and now < cached[1]:
        return cached[0]
    result = await db.execute(
        select(Service.category)
        .where(Service.platform == platform, Service.is_active == True)
        .distinct()
    )
    cats = [row[0] for row in result.all()]
    _CATEGORY_CACHE[platform] = (cats, now + _META_TTL)
    return cats


async def get_service_stats(db: AsyncSession, service_id: int) -> dict:
    """Get real orders count and average rating for a service with caching."""
    now = _time_mod.time()
    if service_id in _stats_cache:
        cached_val, expiry = _stats_cache[service_id]
        if now < expiry:
            return cached_val

    # Count real orders
    orders_count = await db.scalar(
        select(func.count(Order.id)).where(Order.service_id == service_id)
    ) or 0

    # Calculate average rating
    # We need to join Order and ServiceReview because ServiceReview is linked to Order
    rating_query = (
        select(func.avg(ServiceReview.rating))
        .join(Order, Order.id == ServiceReview.order_id)
        .where(Order.service_id == service_id)
    )
    avg_rating = await db.scalar(rating_query)
    
    stats = {
        "orders_count": orders_count,
        "rating": round(float(avg_rating), 1) if avg_rating else None
    }
    
    _stats_cache[service_id] = (stats, now + CACHE_TTL)
    return stats


# Valid user-facing sort modes. Default ("best") preserves current behaviour.
VALID_SORTS = ("best", "cheap", "fast", "guarantee")


def _speed_score(svc: Service, ps_speed: str | None = None) -> int:
    """
    Heuristic speed score (lower = faster). Combines the Service.speed string
    with the upstream provider name. We can't sort numerically without a real
    "average minutes" field, so we map common keywords to buckets.
    """
    text = " ".join(filter(None, [svc.speed or "", svc.name or "", svc.description or ""])).lower()
    if any(k in text for k in ("instant", "فوري", "immediate", "0-1", "0/1")):
        return 0
    if any(k in text for k in ("1-5", "1/5", "fast", "سريع")):
        return 1
    if any(k in text for k in ("5-30", "5/30", "30 min", "30m")):
        return 2
    if any(k in text for k in ("1h", "hour", "ساعة")):
        return 3
    if any(k in text for k in ("day", "يوم", "24h")):
        return 4
    return 5  # unknown — sorts after explicit speed labels


async def get_services_page(
    db: AsyncSession,
    platform: str,
    category: str,
    page: int,
    per_page: int,
    subcategory: str = "all",
    sort_key: str = "best",
) -> tuple[list[tuple[Service, dict]], int]:
    """
    Returns (services_with_stats, total_count).

    Sort modes:
      • best       — orders_count desc → rating desc → price asc  (default)
      • cheap      — price asc        → orders_count desc
      • fast       — speed bucket asc → orders_count desc
      • guarantee  — only services with a guarantee, then orders_count desc

    Backward-compat: legacy sort_key="store" maps to "best".
    Performance: fetches ALL services in ONE query + batch-cached stats.
    """
    if sort_key == "store" or sort_key not in VALID_SORTS:
        sort_key = "best"

    filters = [
        Service.platform == platform,
        Service.category == category,
        Service.is_active == True,
    ]

    # ── Single query to get ALL services at once (fixes N+1 problem) ──────────
    svcs_result = await db.execute(select(Service).where(*filters))
    services = svcs_result.scalars().all()

    if not services:
        return [], 0

    service_ids = [svc.id for svc in services]
    id_to_svc = {svc.id: svc for svc in services}

    # ── Batch-fetch order counts in ONE query ─────────────────────────────────
    now = _time_mod.time()
    uncached_ids = [
        sid for sid in service_ids
        if sid not in _stats_cache or now >= _stats_cache[sid][1]
    ]

    orders_by_id: dict[int, int] = {}
    ratings_by_id: dict[int, float | None] = {}

    if uncached_ids:
        # Batch order counts
        oc_result = await db.execute(
            select(Order.service_id, func.count(Order.id).label("cnt"))
            .where(Order.service_id.in_(uncached_ids))
            .group_by(Order.service_id)
        )
        for row in oc_result.all():
            orders_by_id[row[0]] = row[1]

        # Batch average ratings
        rt_result = await db.execute(
            select(Order.service_id, func.avg(ServiceReview.rating).label("avg_r"))
            .join(ServiceReview, ServiceReview.order_id == Order.id)
            .where(Order.service_id.in_(uncached_ids))
            .group_by(Order.service_id)
        )
        for row in rt_result.all():
            ratings_by_id[row[0]] = float(row[1]) if row[1] else None

        # Populate cache for uncached IDs
        for sid in uncached_ids:
            stats = {
                "orders_count": orders_by_id.get(sid, 0),
                "rating": round(ratings_by_id[sid], 1) if ratings_by_id.get(sid) else None,
            }
            _stats_cache[sid] = (stats, now + CACHE_TTL)

    all_stats: list[tuple[Service, dict]] = []
    for sid in service_ids:
        svc = id_to_svc.get(sid)
        if svc is None:
            continue
        cached_val, _ = _stats_cache.get(sid, ({"orders_count": 0, "rating": None}, 0))
        all_stats.append((svc, cached_val))

    # ── Apply filter (only "guarantee" actually filters; others just sort) ──
    if sort_key == "guarantee":
        def has_guarantee(item) -> bool:
            svc, _ = item
            if (svc.guarantee_days or 0) > 0:
                return True
            text = f"{svc.name or ''} {svc.description or ''}".lower()
            return any(k in text for k in ("guarantee", "refill", "ضمان", "ريفل", "lifetime", "مدى الحياة"))
        all_stats = [it for it in all_stats if has_guarantee(it)]

    # ── Apply sort ──
    def sort_best(item):
        svc, stats = item
        return (-stats["orders_count"], -(stats["rating"] or 0), float(svc.price_per_1000))

    def sort_cheap(item):
        svc, stats = item
        return (float(svc.price_per_1000), -stats["orders_count"])

    def sort_fast(item):
        svc, stats = item
        return (_speed_score(svc), -stats["orders_count"], float(svc.price_per_1000))

    sorters = {
        "best":      sort_best,
        "cheap":     sort_cheap,
        "fast":      sort_fast,
        "guarantee": sort_best,  # within guarantee filter, fall back to best ordering
    }
    all_stats.sort(key=sorters[sort_key])

    total = len(all_stats)
    start = page * per_page
    end = start + per_page

    return all_stats[start:end], total


async def get_service(db: AsyncSession, service_id: int) -> Service | None:
    result = await db.execute(select(Service).where(Service.id == service_id))
    return result.scalar_one_or_none()


async def get_provider_service(db: AsyncSession, ps_id: int) -> ProviderService | None:
    result = await db.execute(select(ProviderService).where(ProviderService.id == ps_id))
    return result.scalar_one_or_none()


async def count_services(db: AsyncSession, active_only: bool = False) -> int:
    q = select(func.count()).select_from(Service)
    if active_only:
        q = q.where(Service.is_active == True)
    return await db.scalar(q) or 0


async def get_admin_services_page(
    db: AsyncSession,
    platform: str,
    page: int,
    per_page: int,
) -> tuple[list[Service], int]:
    total = await db.scalar(
        select(func.count()).select_from(Service).where(Service.platform == platform)
    ) or 0
    result = await db.execute(
        select(Service)
        .where(Service.platform == platform)
        .order_by(Service.category, Service.id)
        .offset(page * per_page)
        .limit(per_page)
    )
    return result.scalars().all(), total


async def get_platform_service_counts(db: AsyncSession) -> list[tuple[str, int]]:
    result = await db.execute(
        select(Service.platform, func.count(Service.id).label("cnt"))
        .group_by(Service.platform)
        .order_by(Service.platform)
    )
    return result.all()
