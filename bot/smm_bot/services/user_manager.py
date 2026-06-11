"""
User service layer — business logic for user operations.
Handlers call this; DB access goes through user_repo.
"""
import logging
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from repositories import user_repo
from models.user import User
from i18n import get_vip_level
from config import REFERRAL_REWARD

logger = logging.getLogger(__name__)


async def get_or_create_user(
    db: AsyncSession,
    user_id: int,
    username: str | None = None,
    first_name: str | None = None,
) -> User:
    return await user_repo.get_or_create_user(db, user_id, username, first_name)


async def process_referral(db: AsyncSession, new_user: User, ref_id: int) -> None:
    """Credit the referrer if the new user was not already referred."""
    if new_user.referred_by or ref_id == new_user.id:
        return

    referrer = await user_repo.get_referrer(db, ref_id)
    if not referrer:
        return

    new_user.referred_by = ref_id
    referrer.referral_count = (referrer.referral_count or 0) + 1
    reward = Decimal(str(REFERRAL_REWARD))
    referrer.referral_earnings = Decimal(str(referrer.referral_earnings or 0)) + reward
    referrer.balance = Decimal(str(referrer.balance)) + reward
    await db.commit()
    logger.info("Referral: user %s credited %s to referrer %s", new_user.id, reward, ref_id)


import time as _time_vip
_VIP_SYNC_CACHE: dict[int, float] = {}
_VIP_SYNC_INTERVAL = 120  # ثانية — لا تعيد الحساب إلا كل دقيقتين


async def sync_vip_level(db: AsyncSession, user: User) -> bool:
    """Recalculate and persist VIP level. Returns True if level changed.
    Throttled: skips recalculation if called too recently for the same user."""
    now = _time_vip.time()
    last = _VIP_SYNC_CACHE.get(user.id, 0)
    if now - last < _VIP_SYNC_INTERVAL:
        return False   # تخطِّ — لم يمر وقت كافٍ
    _VIP_SYNC_CACHE[user.id] = now

    new_level = get_vip_level(float(user.total_spent or 0))
    if user.vip_level != new_level:
        user.vip_level = new_level
        await db.commit()
        return True
    return False


async def add_balance(
    db: AsyncSession,
    user_id: int,
    amount: Decimal,
    description: str = "",
    external_ref: str | None = None,
) -> User:
    return await user_repo.add_balance(db, user_id, amount, description, external_ref)
