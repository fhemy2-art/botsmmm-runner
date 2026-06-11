"""
Order repository — all DB access for Order model.
Uses JOIN + IN queries to avoid N+1 problems.
"""
import logging
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from models.order import Order
from models.service import Service

logger = logging.getLogger(__name__)


async def get_orders_with_services(
    db: AsyncSession,
    user_id: int,
    limit: int = 10,
    offset: int = 0,
) -> list[tuple[Order, Service | None]]:
    """
    Single JOIN query — replaces the N+1 loop in the original orders handler.
    Returns (Order, Service|None) tuples.
    """
    result = await db.execute(
        select(Order, Service)
        .outerjoin(Service, Order.service_id == Service.id)
        .where(Order.user_id == user_id)
        .order_by(Order.created_at.desc())
        .limit(limit)
        .offset(offset)
    )
    return result.all()


async def get_order_with_service(
    db: AsyncSession,
    user_id: int,
    order_id: int,
) -> tuple[Order, Service | None] | None:
    result = await db.execute(
        select(Order, Service)
        .outerjoin(Service, Order.service_id == Service.id)
        .where(Order.user_id == user_id, Order.id == order_id)
    )
    return result.first()


async def get_pending_orders(db: AsyncSession) -> list[Order]:
    """Fetches all active orders in one query for status updates."""
    result = await db.execute(
        select(Order).where(
            Order.status.in_(["pending", "processing"]),
            Order.external_order_id.isnot(None),
            Order.provider_id.isnot(None),
        )
    )
    return result.scalars().all()


async def count_orders(db: AsyncSession) -> int:
    return await db.scalar(select(func.count()).select_from(Order)) or 0


async def count_user_orders(db: AsyncSession, user_id: int) -> int:
    return await db.scalar(
        select(func.count()).select_from(Order).where(Order.user_id == user_id)
    ) or 0


async def total_revenue(db: AsyncSession) -> float:
    val = await db.scalar(select(func.sum(Order.charge)).select_from(Order))
    return float(val or 0)
