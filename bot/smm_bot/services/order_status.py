"""
Background order status updater.
Runs every ORDER_UPDATE_INTERVAL seconds.
Uses the shared HTTP session pool and loads orders in bulk.

Two responsibilities each tick:
1. Status sync   — for orders that already have an external_order_id, fetch
                    their current status from the provider and update locally.
2. Recovery      — for orders that are still "pending" without an
                    external_order_id (the initial provider call failed),
                    retry placement up to MAX_PROVIDER_ATTEMPTS times. After
                    that, auto-refund the user and mark the order canceled
                    so balances are never silently consumed.
"""
import logging

from aiogram import Bot
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from decimal import Decimal

from models.order import Order
from models.provider import Provider
from models.user import User
from repositories.order_repo import get_pending_orders
from repositories.user_repo import invalidate_user_cache
from repositories import service_repo
from services.smm_provider import get_order_status, place_order
from i18n import t

logger = logging.getLogger(__name__)

STATUS_MAP = {
    "completed": "completed",
    "partial":   "partial",
    "canceled":  "canceled",
    "refunded":  "refunded",
}

NOTIFY_STATUSES = ("completed", "partial", "canceled", "refunded")

# Stuck-order recovery: how many times we retry sending an order to the
# provider before giving up and refunding the user automatically.
MAX_PROVIDER_ATTEMPTS = 5


async def update_order_statuses(db: AsyncSession, bot: Bot | None = None) -> None:
    """
    Fetch all pending/processing orders in one query, then batch status checks
    and recover any orders stuck without an external_order_id.
    """
    orders = await get_pending_orders(db)
    if not orders:
        return

    # ── (1) Recover stuck orders that never got placed at the provider ──
    stuck = [o for o in orders if not o.external_order_id]
    if stuck:
        await _recover_stuck_orders(db, bot, stuck)

    # ── (2) Status sync for orders that have an external_order_id ──
    sync_orders = [o for o in orders if o.external_order_id and o.provider_id]
    provider_ids = list({o.provider_id for o in sync_orders})
    if not provider_ids:
        return

    result = await db.execute(
        select(Provider).where(Provider.id.in_(provider_ids))
    )
    providers: dict[int, Provider] = {p.id: p for p in result.scalars().all()}

    for order in sync_orders:
        provider = providers.get(order.provider_id)  # type: ignore[arg-type]
        if not provider:
            continue

        try:
            data = await get_order_status(
                provider.api_url, provider.api_key, order.external_order_id
            )
            new_status = STATUS_MAP.get(data.get("status", "").lower())
            if not new_status:
                continue

            old_status = order.status
            order.status = new_status
            await db.commit()

            if bot and old_status != new_status and new_status in NOTIFY_STATUSES:
                await _notify_user(db, bot, order, new_status)

        except Exception as exc:
            logger.warning("Status check failed for order #%s: %s", order.id, exc)


async def _recover_stuck_orders(db: AsyncSession, bot: Bot | None, stuck: list[Order]) -> None:
    """
    Re-attempt provider placement for orders that are pending without an
    external_order_id. After MAX_PROVIDER_ATTEMPTS, auto-refund and cancel.
    """
    for order in stuck:
        attempts = order.provider_attempts or 0

        # Hard cap reached → refund and cancel so the balance is restored.
        if attempts >= MAX_PROVIDER_ATTEMPTS:
            await _refund_and_cancel(db, bot, order, reason="provider_unreachable")
            continue

        service = await service_repo.get_service(db, order.service_id)
        if not service or not service.provider_service_id:
            await _refund_and_cancel(db, bot, order, reason="service_removed")
            continue

        ps = await service_repo.get_provider_service(db, service.provider_service_id)
        if not ps:
            await _refund_and_cancel(db, bot, order, reason="provider_service_removed")
            continue

        # Pick provider — fall back to the one already recorded on the order.
        from repositories import provider_repo
        provider = await provider_repo.get_provider(db, ps.provider_id)
        if not provider or not provider.status:
            order.provider_attempts = attempts + 1
            order.last_provider_error = "provider_inactive"
            await db.commit()
            continue

        try:
            resp = await place_order(
                provider.api_url, provider.api_key,
                ps.external_id, order.link, order.quantity,
            )
            ext_id = str(resp.get("order", "")) or None
            if ext_id:
                order.external_order_id = ext_id
                order.provider_id = provider.id
                order.status = "processing"
                order.provider_attempts = attempts + 1
                order.last_provider_error = None
                await db.commit()
                logger.info("Recovered stuck order #%s on attempt %d", order.id, attempts + 1)
            else:
                order.provider_attempts = attempts + 1
                order.last_provider_error = f"no_order_in_response: {str(resp)[:120]}"
                await db.commit()
        except Exception as exc:
            order.provider_attempts = attempts + 1
            order.last_provider_error = str(exc)[:255]
            await db.commit()
            logger.warning("Recovery attempt %d failed for order #%s: %s", attempts + 1, order.id, exc)


async def _refund_and_cancel(db: AsyncSession, bot: Bot | None, order: Order, reason: str) -> None:
    """Refund the user's balance and mark the order canceled."""
    user = (await db.execute(
        select(User).where(User.id == order.user_id).with_for_update()
    )).scalar_one_or_none()
    if not user:
        order.status = "canceled"
        order.last_provider_error = f"refund_skipped_no_user: {reason}"
        await db.commit()
        return

    refund = Decimal(str(order.charge))
    user.balance = Decimal(str(user.balance)) + refund
    # Roll back lifetime spend so VIP level stays accurate.
    user.total_spent = max(Decimal("0"), Decimal(str(user.total_spent or 0)) - refund)

    order.status = "canceled"
    order.last_provider_error = f"auto_refund: {reason}"
    await db.commit()
    invalidate_user_cache(user.id)  # Keep cache consistent after direct balance update

    logger.warning(
        "Auto-refunded order #%s for user %s ($%.2f) — reason=%s",
        order.id, order.user_id, float(refund), reason,
    )

    if bot:
        try:
            lang = (user.language or "ar")
            msg = (
                f"⚠️ <b>تم إلغاء طلبك #{order.id} واسترداد المبلغ</b>\n"
                f"💵 المبلغ المسترد: <b>${float(refund):.2f}</b>\n"
                f"السبب: تعذر الوصول إلى المزود بعد عدة محاولات.\n"
                f"رصيدك الجديد: <b>${float(user.balance):.2f}</b>"
            ) if lang == "ar" else (
                f"⚠️ <b>Order #{order.id} canceled and refunded</b>\n"
                f"💵 Refund: <b>${float(refund):.2f}</b>\n"
                f"Reason: provider unreachable after retries.\n"
                f"New balance: <b>${float(user.balance):.2f}</b>"
            )
            await bot.send_message(order.user_id, msg, parse_mode="HTML")
        except Exception as exc:
            logger.debug("Refund notify failed for user %s: %s", order.user_id, exc)


async def _notify_user(
    db: AsyncSession,
    bot: Bot,
    order: Order,
    new_status: str,
) -> None:
    """Send status change notification and review prompt to user."""
    result = await db.execute(select(User).where(User.id == order.user_id))
    user = result.scalar_one_or_none()
    lang = (user.language or "ar") if user else "ar"

    status_labels = {
        "completed": "✅ مكتمل" if lang == "ar" else "✅ Completed",
        "partial":   "⚠️ مكتمل جزئياً" if lang == "ar" else "⚠️ Partial",
        "canceled":  "❌ ملغي" if lang == "ar" else "❌ Canceled",
    }
    notif_msg = (
        f"📦 {'تحديث الطلب' if lang == 'ar' else 'Order Update'} "
        f"<b>#{order.id}</b>\n"
        f"{'الحالة الجديدة' if lang == 'ar' else 'New status'}: "
        f"{status_labels.get(new_status, new_status)}"
    )
    try:
        await bot.send_message(order.user_id, notif_msg, parse_mode="HTML")
    except Exception as exc:
        logger.debug("Notify failed user %s: %s", order.user_id, exc)

    if new_status == "completed" and not order.review_sent:
        try:
            review_kb = InlineKeyboardMarkup(inline_keyboard=[
                [
                    InlineKeyboardButton(text=t("rate_1", lang), callback_data=f"review:{order.id}:1"),
                    InlineKeyboardButton(text=t("rate_2", lang), callback_data=f"review:{order.id}:2"),
                    InlineKeyboardButton(text=t("rate_3", lang), callback_data=f"review:{order.id}:3"),
                    InlineKeyboardButton(text=t("rate_4", lang), callback_data=f"review:{order.id}:4"),
                    InlineKeyboardButton(text=t("rate_5", lang), callback_data=f"review:{order.id}:5"),
                ],
                [InlineKeyboardButton(text=t("skip_review", lang), callback_data=f"skipreview:{order.id}")],
            ])
            await bot.send_message(
                order.user_id,
                t("review_prompt", lang, order_id=order.id),
                reply_markup=review_kb,
                parse_mode="HTML",
            )
            order.review_sent = True
            await db.commit()
        except Exception as exc:
            logger.debug("Review prompt failed user %s: %s", order.user_id, exc)
