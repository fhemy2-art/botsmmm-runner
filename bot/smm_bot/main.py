"""
SMM Bot — main entry point.

Architecture:
  • aiogram 3.x dispatcher with SQLiteStorage for persistent FSM
  • Shared aiohttp ClientSession pool (single connection, re-used across all calls)
  • DB session injected into handlers via middleware
  • Rate limiting middleware (30 updates / 60 s per user)
  • Background task scheduler (asyncio.Task, NOT APScheduler):
      - sync_providers: every SYNC_INTERVAL seconds
      - update_orders:  every ORDER_UPDATE_INTERVAL seconds
"""
import asyncio
import logging
import sys
import time
from collections import defaultdict

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import Update, TelegramObject
from aiogram import BaseMiddleware

try:
    from aiogram.fsm.storage.redis import RedisStorage
    _redis_available = True
except ImportError:
    _redis_available = False

from config import (
    BOT_TOKEN, ADMIN_IDS, OWNER_IDS,
    SYNC_INTERVAL, ORDER_UPDATE_INTERVAL, SETTINGS_FILE, DEFAULT_MARKUP_PCT,
)

RATE_LIMIT_CALLS = 30
RATE_LIMIT_PERIOD = 60

from database.session import init_db
import database.session as _db_session
from services import settings_manager


def get_session():
    """Context-manager wrapper for async_session."""
    return _db_session.async_session()


from services.http_client import close_session
from services.order_status import update_order_statuses
from services.game_status import update_game_order_statuses
from services.provider_manager import sync_all_providers

# ─── Handlers ──────────────────────────────────────────────────────────────────
from handlers.common import router as common_router
from handlers.user.services import router as services_router, register_screens as _rs
from handlers.user.order_flow import router as order_flow_router
from handlers.user.orders import router as orders_router
from handlers.user.vip import router as vip_router
from handlers.user.reviews import router as reviews_router
from handlers.user.recharge import router as recharge_router
from handlers.admin.services import router as admin_services_router, set_moderator_ids
from handlers.admin.providers import router as admin_providers_router
from handlers.admin.users import router as admin_users_router
from handlers.admin.moderators import router as admin_moderators_router, get_moderator_ids
from handlers.user.game_handlers import router as game_handlers_router
from handlers.admin.game_admin import router as game_admin_router
from handlers.admin.owner import router as owner_router
from handlers.admin.store_manager import router as store_manager_router
from handlers.user.ready_accounts import router as ready_accounts_router
from handlers.admin.ready_accounts_admin import router as ready_accounts_admin_router

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    stream=sys.stdout,
)
logger = logging.getLogger(__name__)


# ─── DB Middleware ─────────────────────────────────────────────────────────────

class DbSessionMiddleware(BaseMiddleware):
    """Injects a fresh AsyncSession as `db` into every handler's data dict."""

    async def __call__(self, handler, event: TelegramObject, data: dict):
        async with get_session() as session:
            data["db"] = session
            return await handler(event, data)


# ─── Rate-limit Middleware ─────────────────────────────────────────────────────

class RateLimitMiddleware(BaseMiddleware):
    """
    Sliding-window rate limiter: allows RATE_LIMIT_CALLS per RATE_LIMIT_PERIOD (seconds).
    Admins are excluded.
    Uses deque (O(1) popleft) instead of list.pop(0) (O(n)).
    Cleans up empty buckets to prevent memory leak under many users.
    """
    from collections import deque as _deque

    def __init__(self) -> None:
        from collections import deque
        self._deque = deque
        self._buckets: dict[int, "deque[float]"] = {}
        self._cleanup_counter = 0

    async def __call__(self, handler, event: TelegramObject, data: dict):
        user_id: int | None = None
        if hasattr(event, "from_user") and event.from_user:
            user_id = event.from_user.id
        elif hasattr(event, "message") and event.message and event.message.from_user:
            user_id = event.message.from_user.id

        if user_id and user_id not in ADMIN_IDS:
            now = time.monotonic()
            if user_id not in self._buckets:
                self._buckets[user_id] = self._deque()
            bucket = self._buckets[user_id]
            # Evict timestamps outside the window (O(1) each)
            while bucket and now - bucket[0] > RATE_LIMIT_PERIOD:
                bucket.popleft()
            if len(bucket) >= RATE_LIMIT_CALLS:
                logger.info("Rate limit hit for user %s", user_id)
                return
            bucket.append(now)

            # Periodic cleanup of idle users every 500 requests
            self._cleanup_counter += 1
            if self._cleanup_counter >= 500:
                self._cleanup_counter = 0
                cutoff = now - RATE_LIMIT_PERIOD
                dead = [uid for uid, bkt in self._buckets.items() if not bkt or bkt[-1] < cutoff]
                for uid in dead:
                    del self._buckets[uid]

        return await handler(event, data)


# ─── Background tasks ──────────────────────────────────────────────────────────

async def _run_db_keepalive() -> None:
    """Ping the DB every 4 minutes to prevent Neon free-tier from sleeping.
    Neon pauses the compute after 5 min of inactivity — this keeps it warm."""
    await asyncio.sleep(30)
    while True:
        try:
            async with get_session() as db:
                from sqlalchemy import text as _sa_text
                await db.execute(_sa_text("SELECT 1"))
        except Exception as exc:
            logger.debug("DB keepalive ping failed: %s", exc)
        await asyncio.sleep(240)  # Every 4 minutes


async def _run_sync_loop() -> None:
    """Sync provider catalogues every SYNC_INTERVAL seconds."""
    await asyncio.sleep(60)  # Initial delay — let the bot start cleanly
    while True:
        try:
            async with get_session() as db:
                new_count = await sync_all_providers(db)
                if new_count:
                    logger.info("Background sync: %s new provider services", new_count)
        except Exception as exc:
            logger.error("Background sync error: %s", exc, exc_info=True)
        await asyncio.sleep(SYNC_INTERVAL)


async def _run_status_loop(bot: Bot) -> None:
    """Update pending order statuses every ORDER_UPDATE_INTERVAL seconds."""
    await asyncio.sleep(10)  # Quick initial start
    while True:
        try:
            async with get_session() as db:
                # Update SMM orders
                await update_order_statuses(db, bot)
                # Update Game orders
                await update_game_order_statuses(db, bot)
        except Exception as exc:
            logger.error("Background status update error: %s", exc, exc_info=True)
        await asyncio.sleep(ORDER_UPDATE_INTERVAL)


# ─── Startup / shutdown ────────────────────────────────────────────────────────

async def on_startup(bot: Bot) -> None:
    me = await bot.get_me()
    logger.info("Bot started: @%s (id=%s)", me.username, me.id)

    # ─── Set Bot Command Menu ──────────────────────────────────────────────────
    from aiogram.types import BotCommand, BotCommandScopeDefault, BotCommandScopeChat
    from aiogram.types import BotCommandScopeAllPrivateChats

    default_commands = [
        BotCommand(command="start",    description="🏠 القائمة الرئيسية"),
        BotCommand(command="orders",   description="📋 متابعة طلباتي"),
        BotCommand(command="recharge", description="💰 شحن الرصيد"),
        BotCommand(command="support",  description="💬 الدعم الفني"),
        BotCommand(command="stats",    description="📊 إحصائياتي"),
        BotCommand(command="vip",      description="👑 عضويتي VIP"),
        BotCommand(command="neworder", description="🚀 طلب جديد"),
        BotCommand(command="balance",  description="💳 رصيدي الحالي"),
    ]
    try:
        await bot.set_my_commands(default_commands, scope=BotCommandScopeAllPrivateChats())
        logger.info("Bot commands menu set successfully")
    except Exception as exc:
        logger.warning("Failed to set commands: %s", exc)

    # ─── Cleanup fake free services (one-time, idempotent) ───────────────────
    try:
        from database import get_db_session
        from services.free_services_seeder import delete_fake_free_services
        async with get_db_session() as _db:
            _deleted = await delete_fake_free_services(_db)
            if _deleted:
                logger.info("Startup cleanup: deleted %s fake free services", _deleted)
    except Exception as _e:
        logger.warning("Startup cleanup skipped: %s", _e)

    # ─── Notify admins ─────────────────────────────────────────────────────────
    for admin_id in ADMIN_IDS:
        try:
            await bot.send_message(
                admin_id,
                f"✅ البوت يعمل الآن!\n🤖 @{me.username}\n"
                f"💡 أرسل /start للدخول",
            )
        except Exception:
            pass


async def on_shutdown(bot: Bot) -> None:
    logger.info("Bot shutting down...")
    await close_session()


# ─── Main ─────────────────────────────────────────────────────────────────────

async def main() -> None:
    if not BOT_TOKEN:
        sys.exit("ERROR: BOT_TOKEN is required. Check your .env file.")
    if not ADMIN_IDS:
        sys.exit("ERROR: ADMIN_IDS is required. Check your .env file.")

    _rs()  # Register all screen handlers
    await init_db()
    settings_manager.init_settings(SETTINGS_FILE)
    if not settings_manager.get("markup_pct"):
        settings_manager.set_setting("markup_pct", DEFAULT_MARKUP_PCT)

    # Load moderators from DB into memory cache
    async with get_session() as db:
        mod_ids = await get_moderator_ids(db)
        set_moderator_ids(mod_ids)
        logger.info("Loaded %s moderators from database", len(mod_ids))

    bot = Bot(
        token=BOT_TOKEN,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )

    # Use Redis for persistent FSM if REDIS_URL is set, otherwise MemoryStorage
    from config import REDIS_URL
    storage = None
    if REDIS_URL:
        try:
            from aiogram.fsm.storage.redis import RedisStorage
            storage = RedisStorage.from_url(REDIS_URL)
            logger.info("Using RedisStorage for FSM (states survive restart)")
        except Exception as exc:
            logger.warning("Redis FSM failed, falling back to MemoryStorage: %s", exc)
    if storage is None:
        storage = MemoryStorage()
        logger.info("Using MemoryStorage for FSM (states lost on restart)")

    dp = Dispatcher(storage=storage)

    # Middlewares
    dp.update.middleware(DbSessionMiddleware())
    dp.update.middleware(RateLimitMiddleware())

    # Register routers (order matters for overlapping filters)
    dp.include_router(common_router)
    dp.include_router(services_router)
    dp.include_router(order_flow_router)
    dp.include_router(orders_router)
    dp.include_router(game_handlers_router)
    dp.include_router(vip_router)
    dp.include_router(reviews_router)
    dp.include_router(recharge_router)
    dp.include_router(admin_services_router)
    dp.include_router(admin_providers_router)
    dp.include_router(admin_users_router)
    dp.include_router(admin_moderators_router)
    dp.include_router(game_admin_router)
    dp.include_router(owner_router)
    dp.include_router(store_manager_router)
    dp.include_router(ready_accounts_router)
    dp.include_router(ready_accounts_admin_router)

    # Lifecycle hooks
    dp.startup.register(on_startup)
    dp.shutdown.register(on_shutdown)

    # Start background tasks
    asyncio.create_task(_run_db_keepalive())   # Keep Neon DB warm (no cold-start lag)
    asyncio.create_task(_run_sync_loop())
    asyncio.create_task(_run_status_loop(bot))

    logger.info("Starting polling...")
    logger.info("OWNER_IDS loaded: %s", OWNER_IDS)
    logger.info("ADMIN_IDS loaded: %s", ADMIN_IDS)

    # Drop ALL pending updates on restart — avoids processing stale messages
    # from the ~2-minute gap between GitHub Actions runs (every 5 hours)
    try:
        await bot.delete_webhook(drop_pending_updates=True)
        logger.info("Webhook cleared + pending updates dropped — polling mode active")
    except Exception as exc:
        logger.warning("Could not clear webhook: %s", exc)

    await dp.start_polling(
        bot,
        allowed_updates=[
            "message",
            "callback_query",
            "pre_checkout_query",
            "successful_payment",
            "chat_member",
        ],
        limit=30,          # Smaller batches = lower latency per update
        timeout=25,        # Long-poll 25s — reduces empty requests to Telegram
    )


if __name__ == "__main__":
    asyncio.run(main())
