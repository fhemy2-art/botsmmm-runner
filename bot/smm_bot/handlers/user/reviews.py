"""Service review handler — saves ratings after order completion."""
import logging

from aiogram import Router, F
from aiogram.types import CallbackQuery
from sqlalchemy import select

from models.order import Order
from models.service_review import ServiceReview
from i18n import t
from services.user_manager import get_or_create_user

logger = logging.getLogger(__name__)
router = Router()


@router.callback_query(F.data.startswith("review:"))
async def handle_review(callback: CallbackQuery, db):
    parts = callback.data.split(":")
    if len(parts) < 3:
        await callback.answer("❌ بيانات غير صحيحة")
        return

    try:
        order_id = int(parts[1])
        rating = int(parts[2])
    except ValueError:
        await callback.answer("❌ بيانات غير صحيحة")
        return

    if rating < 1 or rating > 5:
        await callback.answer("❌ تقييم غير صحيح")
        return

    user = await get_or_create_user(db, callback.from_user.id)
    lang = user.language or "ar"

    result = await db.execute(select(Order).where(Order.id == order_id))
    order = result.scalar_one_or_none()
    if not order or order.user_id != callback.from_user.id:
        await callback.answer("❌ الطلب غير موجود")
        return

    review = ServiceReview(
        order_id=order_id,
        user_id=callback.from_user.id,
        rating=rating,
    )
    db.add(review)
    order.review_sent = True
    await db.commit()

    try:
        await callback.message.edit_text(
            t("review_thanks", lang), parse_mode="HTML"
        )
    except Exception:
        pass
    await callback.answer(t("review_thanks", lang))
    logger.info("Review saved: order=%s rating=%s user=%s", order_id, rating, callback.from_user.id)


@router.callback_query(F.data.startswith("skipreview:"))
async def skip_review(callback: CallbackQuery, db):
    parts = callback.data.split(":")
    if len(parts) < 2:
        await callback.answer()
        return
    try:
        order_id = int(parts[1])
    except ValueError:
        await callback.answer()
        return

    result = await db.execute(select(Order).where(Order.id == order_id))
    order = result.scalar_one_or_none()
    if order and order.user_id == callback.from_user.id:
        order.review_sent = True
        await db.commit()

    try:
        await callback.message.delete()
    except Exception:
        pass
    await callback.answer()
