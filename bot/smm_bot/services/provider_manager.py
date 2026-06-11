"""
Provider service layer — syncs remote provider catalogues into local DB.
Processes services in bulk to avoid N+1 individual INSERTs.
Now stores: type, description, refill, cancel from provider API.
"""
import logging
from decimal import Decimal, InvalidOperation

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from models.provider import Provider
from models.provider_service import ProviderService
from services.smm_provider import fetch_services
from repositories.provider_repo import get_active_providers

logger = logging.getLogger(__name__)

# Maximum rate value that NUMERIC(20, 8) can store safely
_MAX_RATE = Decimal("999999999999")


def _bool(val) -> bool | None:
    """Normalize provider boolean fields (True/False/1/0/'true'/'false')."""
    if val is None:
        return None
    if isinstance(val, bool):
        return val
    if isinstance(val, int):
        return bool(val)
    if isinstance(val, str):
        return val.lower() in ("true", "1", "yes")
    return None


def _safe_rate(raw) -> Decimal | None:
    """Convert rate to Decimal, return None if invalid or out of range."""
    if raw is None:
        return None
    try:
        val = Decimal(str(raw))
        if val < 0 or val > _MAX_RATE:
            return None
        return val
    except (InvalidOperation, ValueError, TypeError):
        return None


async def sync_provider_services(db: AsyncSession, provider: Provider) -> int:
    """
    Fetch and upsert all services from a single provider.
    Saves type, description, refill, cancel in addition to core fields.
    Returns count of newly inserted services.
    """
    raw = await fetch_services(provider.api_url, provider.api_key)
    if not raw:
        return 0

    # ── جلب كل الخدمات الموجودة مرة واحدة كـ dict — يُلغي N+1 ──────────────────
    result = await db.execute(
        select(ProviderService)
        .where(ProviderService.provider_id == provider.id)
    )
    existing: dict[str, ProviderService] = {ps.external_id: ps for ps in result.scalars().all()}

    new_count = 0
    skipped = 0
    for svc in raw:
        ext_id = str(svc.get("service", svc.get("id", ""))).strip()
        if not ext_id:
            continue

        svc_name = str(svc.get("name", ""))[:200]
        svc_category = str(svc.get("category", "other"))[:100]
        svc_type = str(svc.get("type", ""))[:100] if svc.get("type") else None
        svc_rate = _safe_rate(svc.get("rate"))
        svc_min = svc.get("min")
        svc_max = svc.get("max")
        svc_desc = str(svc.get("description", ""))[:500] if svc.get("description") else None
        svc_refill = _bool(svc.get("refill"))
        svc_cancel = _bool(svc.get("cancel"))

        if svc.get("rate") is not None and svc_rate is None:
            skipped += 1
            continue

        ps = existing.get(ext_id)
        if ps:
            # تحديث الحقول المتغيرة فقط
            ps.name = svc_name
            if svc_rate is not None: ps.rate = svc_rate
            if svc_min is not None: ps.min = svc_min
            if svc_max is not None: ps.max = svc_max
            if svc_type is not None: ps.type = svc_type
            if svc_desc is not None: ps.description = svc_desc
            if svc_refill is not None: ps.refill = svc_refill
            if svc_cancel is not None: ps.cancel = svc_cancel
        else:
            ps = ProviderService(
                provider_id=provider.id,
                external_id=ext_id,
                name=svc_name,
                category=svc_category,
                type=svc_type,
                rate=svc_rate,
                min=svc_min,
                max=svc_max,
                description=svc_desc,
                refill=svc_refill,
                cancel=svc_cancel,
            )
            db.add(ps)
            existing[ext_id] = ps
            new_count += 1

    await db.commit()
    logger.info(
        "sync_provider_services: provider=%s new=%s total=%s skipped=%s",
        provider.id, new_count, len(raw), skipped,
    )
    return new_count


async def sync_all_providers(db: AsyncSession) -> int:
    """Sync all active providers. Returns total new services inserted."""
    providers = await get_active_providers(db)
    total = 0
    for provider in providers:
        # Skip game-type providers — they use game_admin sync
        if getattr(provider, 'provider_type', 'smm') == 'game':
            continue
        pid = provider.id  # capture before try — avoids lazy-load on broken session
        try:
            count = await sync_provider_services(db, provider)
            total += count
        except Exception as exc:
            await db.rollback()  # reset session so next provider can proceed
            logger.error("sync failed for provider %s: %s", pid, exc, exc_info=True)
    return total
