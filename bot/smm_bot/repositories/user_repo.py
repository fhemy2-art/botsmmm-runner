"""
User repository — all DB access for User model lives here.
No handler or service should run raw SQL against the users table directly.
"""
import logging
from decimal import Decimal

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from models.user import User
from models.transaction import Transaction

logger = logging.getLogger(__name__)

# ── In-memory user cache (avoids repeated DB hits per message) ────────────────
import time as _time_mod
_USER_CACHE: dict[int, tuple["User", float]] = {}
_USER_TTL = 120  # seconds — increased for better performance under load
_USER_CACHE_MAX = 10000  # max entries to prevent unbounded memory growth


def invalidate_user_cache(user_id: int) -> None:
    """Call after writing user changes to keep cache consistent."""
    _USER_CACHE.pop(user_id, None)


def _user_cache_cleanup() -> None:
    """Drop expired entries if cache is getting large."""
    if len(_USER_CACHE) < _USER_CACHE_MAX:
        return
    now = _time_mod.time()
    expired = [uid for uid, (_, exp) in _USER_CACHE.items() if exp < now]
    for uid in expired:
        _USER_CACHE.pop(uid, None)


async def _next_account_number(db: AsyncSession) -> int:
    """Generate next sequential account number starting from 1000."""
    max_num = await db.scalar(
        select(func.max(User.account_number)).select_from(User)
    )
    return (max_num or 999) + 1


async def get_user(db: AsyncSession, user_id: int) -> User | None:
    result = await db.execute(select(User).where(User.id == user_id))
    return result.scalar_one_or_none()


async def get_user_by_account_number(db: AsyncSession, account_number: int) -> User | None:
    """Look up a user by their unique account number."""
    result = await db.execute(
        select(User).where(User.account_number == account_number)
    )
    return result.scalar_one_or_none()


async def get_user_by_username(db: AsyncSession, username: str) -> User | None:
    """Look up a user by their Telegram username (without @)."""
    clean = username.lstrip("@").strip().lower()
    result = await db.execute(
        select(User).where(func.lower(User.username) == clean)
    )
    return result.scalar_one_or_none()


async def get_or_create_user(
    db: AsyncSession,
    user_id: int,
    username: str | None = None,
    first_name: str | None = None,
) -> User:
    # ── Check in-memory cache first ───────────────────────────────────────────
    now = _time_mod.time()
    cached = _USER_CACHE.get(user_id)
    if cached and now < cached[1] and not username and not first_name:
        return cached[0]

    user = await get_user(db, user_id)
    if not user:
        try:
            acct_num = await _next_account_number(db)
            user = User(
                id=user_id,
                account_number=acct_num,
                username=username,
                first_name=first_name,
                balance=Decimal("0"),
                total_spent=Decimal("0"),
            )
            db.add(user)
            await db.commit()
            await db.refresh(user)
        except Exception:
            await db.rollback()
            user = await get_user(db, user_id)
            if not user:
                raise
    else:
        # Update username/first_name if changed; assign account_number if missing
        changed = False
        if username and user.username != username:
            user.username = username
            changed = True
        if first_name and user.first_name != first_name:
            user.first_name = first_name
            changed = True
        if not user.account_number:
            user.account_number = await _next_account_number(db)
            changed = True
        if changed:
            await db.commit()
            _USER_CACHE.pop(user_id, None)  # Invalidate stale cache entry

    # Store in cache (with periodic cleanup)
    _user_cache_cleanup()
    _USER_CACHE[user_id] = (user, now + _USER_TTL)
    return user


async def add_balance(
    db: AsyncSession,
    user_id: int,
    amount: Decimal,
    description: str = "",
    external_ref: str | None = None,
) -> User:
    """
    Credit user balance and create a Transaction record.

    If `external_ref` is provided (e.g. Telegram Stars charge id, Binance trade no),
    the call is idempotent: a duplicate ref returns the user untouched instead of
    crediting twice. This protects against duplicate Telegram update delivery.
    """
    # Idempotency: if a transaction with this external_ref already exists, skip.
    if external_ref:
        existing = await db.execute(
            select(Transaction).where(Transaction.external_ref == external_ref)
        )
        if existing.scalar_one_or_none():
            logger.info(
                "add_balance: duplicate external_ref=%s for user=%s — skipping credit",
                external_ref, user_id,
            )
            return await get_or_create_user(db, user_id)

    user = await get_or_create_user(db, user_id)
    user.balance = Decimal(str(user.balance)) + amount
    tx = Transaction(
        user_id=user_id,
        amount=amount,
        description=description,
        external_ref=external_ref,
    )
    db.add(tx)
    try:
        await db.commit()
    except Exception as exc:
        # Likely a unique-constraint race on external_ref.
        await db.rollback()
        logger.warning(
            "add_balance commit failed (likely duplicate external_ref=%s): %s",
            external_ref, exc,
        )
        return await get_or_create_user(db, user_id)
    await db.refresh(user)
    _USER_CACHE.pop(user_id, None)  # Invalidate after balance change
    return user


async def count_users(db: AsyncSession) -> int:
    return await db.scalar(select(func.count()).select_from(User)) or 0


async def get_all_user_ids(db: AsyncSession) -> list[int]:
    """Used for broadcast — returns only IDs to keep memory footprint low."""
    result = await db.execute(select(User.id))
    return [row[0] for row in result.all()]


async def get_referrer(db: AsyncSession, referrer_id: int) -> User | None:
    return await get_user(db, referrer_id)
