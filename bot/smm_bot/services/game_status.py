import logging
import asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from aiogram import Bot

from models.game import GameOrder, GameProduct
from models.provider import Provider
from services.game_services import game_api_check_status
from ui import section_card

logger = logging.getLogger(__name__)


async def update_game_order_statuses(db: AsyncSession, bot: Bot):
    """
    Background task to check and update game order statuses.
    Supports both SMM providers and FazerCards.
    """
    stmt = select(GameOrder).where(
        GameOrder.status.in_(["processing", "pending"]),
        GameOrder.external_order_id.isnot(None),
    )
    result = await db.execute(stmt)
    orders = result.scalars().all()

    if not orders:
        return

    # Cache providers to avoid redundant DB hits
    provider_cache: dict[int, Provider] = {}

    for order in orders:
        try:
            product = await db.get(GameProduct, order.product_id)
            if not product:
                continue

            provider_id = product.provider_id
            if provider_id not in provider_cache:
                provider_cache[provider_id] = await db.get(Provider, provider_id)

            provider = provider_cache[provider_id]
            if not provider:
                continue

            # Check status via API (auto-routes to FazerCards if applicable)
            status_data = await game_api_check_status(
                provider.api_url,
                provider.api_key,
                order.external_order_id,
            )

            if "status" in status_data:
                new_status = status_data["status"].lower()

                # Status mapping (covers both SMM and FazerCards normalized statuses)
                status_map = {
                    "pending": "pending",
                    "processing": "processing",
                    "in progress": "processing",
                    "completed": "completed",
                    "partial": "completed",
                    "canceled": "canceled",
                    "refunded": "canceled",
                }

                mapped_status = status_map.get(new_status, order.status)

                if mapped_status != order.status:
                    old_status = order.status
                    order.status = mapped_status
                    await db.commit()

                    # Notify user
                    await _notify_game_user(bot, order, mapped_status)
                    logger.info(
                        "Game Order %s status changed: %s -> %s",
                        order.id, old_status, mapped_status,
                    )

        except Exception as e:
            logger.error("Error updating game order %s: %s", order.id, e)
            continue


async def _notify_game_user(bot: Bot, order: GameOrder, status: str):
    try:
        status_emoji = {
            "completed": "✅",
            "canceled": "❌",
            "processing": "🔄",
            "pending": "⏳",
        }
        emoji = status_emoji.get(status, "ℹ️")

        text = section_card(emoji, "تحديث حالة الطلب", [
            f"رقم الطلب: <code>{order.id}</code>",
            f"الحالة الجديدة: <b>{status}</b>",
            "",
            "شكراً لاستخدامك خدماتنا!",
        ])

        await bot.send_message(order.user_id, text)
    except Exception as e:
        logger.error(
            "Failed to notify user %s for game order %s: %s",
            order.user_id, order.id, e,
        )