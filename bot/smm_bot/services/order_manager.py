"""
Order service layer — all order business logic.
Handlers must NOT call repositories or smm_provider directly.
"""
import logging
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from repositories import order_repo, service_repo, provider_repo, user_repo
from models.user import User
from models.order import Order
from services.smm_provider import place_order
from i18n import get_vip_level
from services.notify import notify_activation

logger = logging.getLogger(__name__)


async def create_order(
    db: AsyncSession,
    user_id: int,
    service_id: int,
    link: str,
    quantity: int,
    bot=None,
    vip_discount_pct: int = 0,
) -> tuple[Order | None, str | None]:
    """
    Create an order end-to-end:
    1. Validate service exists
    2. Calculate charge with VIP discount
    3. Check user balance
    4. Place order with provider (non-fatal if it fails)
    5. Deduct balance and persist order

    Returns (order, None) on success, (None, error_message) on failure.
    """
    service = await service_repo.get_service(db, service_id)
    if not service:
        return None, "الخدمة غير موجودة"

    base_charge = Decimal(str(service.price_per_1000)) * quantity / 1000
    if vip_discount_pct > 0:
        discount = base_charge * Decimal(str(vip_discount_pct)) / 100
        charge = base_charge - discount
    else:
        charge = base_charge

    # Row-lock the user to prevent concurrent orders from double-spending the
    # same balance. Without FOR UPDATE, two simultaneous order requests can
    # both pass the balance check before either commits.
    # SQLite ignores FOR UPDATE silently — that is acceptable for local dev.
    locked = await db.execute(
        select(User).where(User.id == user_id).with_for_update()
    )
    user = locked.scalar_one_or_none()
    if not user:
        return None, "المستخدم غير موجود"

    if Decimal(str(user.balance)) < charge:
        return None, (
            f"رصيدك غير كافٍ. الرصيد: ${float(user.balance):.2f} | "
            f"المطلوب: ${float(charge):.2f}"
        )

    # Deduct balance
    user.balance = Decimal(str(user.balance)) - charge

    order = Order(
        user_id=user_id,
        service_id=service_id,
        link=link,
        quantity=quantity,
        charge=charge,
        status="pending",
        review_sent=False,
    )
    db.add(order)
    await db.flush()  # Get order ID

    # Send notification to activations channel immediately — ALWAYS
    try:
        vip_lvl = get_vip_level(float(user.total_spent or 0))
        await notify_activation(
            bot, "order_received",
            amount=float(charge),
            service=service.name,
            order_id=order.id,
            user_id=user_id,
            service_id=service_id,
            quantity=quantity,
            link=link,
            platform=service.platform or "",
            category=service.category or "",
            vip_level=vip_lvl,
        )
    except Exception as e:
        logger.error(f"Failed to send order notification: {e}")

    # Try to place with provider — failure is non-fatal (order stays pending)
    external_order_id = None
    provider_id = None
    last_error: str | None = None

    ps = await service_repo.get_provider_service(db, service.provider_service_id) if service.provider_service_id else None
    if ps:
        provider = await provider_repo.get_provider(db, ps.provider_id)
        if provider and provider.status:
            # Always remember which provider was attempted, even on failure,
            # so the background recovery loop can retry instead of leaving the
            # order orphaned and silently consuming the user's balance.
            provider_id = provider.id
            try:
                resp = await place_order(
                    provider.api_url, provider.api_key,
                    ps.external_id, link, quantity,
                )
                external_order_id = str(resp.get("order", "")) or None
            except Exception as exc:
                last_error = str(exc)[:255]
                logger.warning("Provider order placement failed (will retry): %s", exc)

    order.provider_id = provider_id
    if external_order_id:
        order.external_order_id = external_order_id
        order.status = "processing"
        order.provider_attempts = 1
    else:
        # Stays "pending" — order_status background task will retry placement.
        order.provider_attempts = 1 if provider_id else 0
        if last_error is not None:
            order.last_provider_error = last_error

    await db.commit()
    await db.refresh(order)

    # Update VIP level after spending
    user.total_spent = Decimal(str(user.total_spent or 0)) + Decimal(str(order.charge))
    user.vip_level = get_vip_level(float(user.total_spent))
    await db.commit()

    logger.info(
        "Order #%s created: user=%s svc=%s qty=%s charge=%s ext_id=%s",
        order.id, user_id, service_id, quantity, charge, external_order_id,
    )
    return order, None
