"""
Provider repository — DB access for Provider and ProviderService models.
"""
import logging
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from models.provider import Provider
from models.provider_service import ProviderService

logger = logging.getLogger(__name__)


async def get_active_providers(db: AsyncSession) -> list[Provider]:
    result = await db.execute(select(Provider).where(Provider.status == True))
    return result.scalars().all()


async def get_all_providers(db: AsyncSession) -> list[Provider]:
    result = await db.execute(select(Provider))
    return result.scalars().all()


async def get_provider(db: AsyncSession, provider_id: int) -> Provider | None:
    result = await db.execute(select(Provider).where(Provider.id == provider_id))
    return result.scalar_one_or_none()


async def get_provider_service(db: AsyncSession, ps_id: int) -> ProviderService | None:
    result = await db.execute(select(ProviderService).where(ProviderService.id == ps_id))
    return result.scalar_one_or_none()


async def count_provider_services(db: AsyncSession, provider_id: int) -> int:
    return await db.scalar(
        select(func.count()).select_from(ProviderService)
        .where(ProviderService.provider_id == provider_id)
    ) or 0


async def count_all_provider_services(db: AsyncSession) -> int:
    return await db.scalar(
        select(func.count()).select_from(ProviderService)
    ) or 0


async def get_provider_categories(db: AsyncSession, provider_id: int) -> list[str]:
    result = await db.execute(
        select(ProviderService.category)
        .where(ProviderService.provider_id == provider_id)
        .distinct()
    )
    return [r[0] for r in result.all()]


async def get_provider_services_in_categories(
    db: AsyncSession,
    provider_id: int,
    categories: list[str],
    limit: int = 10,
) -> list[ProviderService]:
    """Single query for cheapest services across a group of categories."""
    result = await db.execute(
        select(ProviderService)
        .where(
            ProviderService.provider_id == provider_id,
            ProviderService.category.in_(categories),
            ProviderService.rate.isnot(None),
        )
        .order_by(ProviderService.rate)
        .limit(limit)
    )
    return result.scalars().all()


async def find_existing_provider_service(
    db: AsyncSession,
    provider_id: int,
    external_id: str,
) -> ProviderService | None:
    result = await db.execute(
        select(ProviderService).where(
            ProviderService.provider_id == provider_id,
            ProviderService.external_id == external_id,
        )
    )
    return result.scalar_one_or_none()


async def service_already_added(db: AsyncSession, ps_id: int) -> bool:
    """Check if a ProviderService has already been promoted to a Service."""
    from models.service import Service
    count = await db.scalar(
        select(func.count()).select_from(Service)
        .where(Service.provider_service_id == ps_id)
    )
    return (count or 0) > 0
