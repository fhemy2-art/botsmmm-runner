"""
Database session management.
Uses a single async engine with a shared connection pool.
run_sync(Base.metadata.create_all) handles schema creation on startup.
Supports both SQLite (local dev) and PostgreSQL (production).
"""
import sqlite3
import logging
import os

from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from sqlalchemy import text as sa_text
from database.base import Base

logger = logging.getLogger(__name__)

engine = None
async_session = None  # type: ignore[assignment]


# ── Migrations ───────────────────────────────────────────────────────────────
# Each tuple is (table, column, SQL type+default).
_MIGRATIONS = [
    ("users",             "language",          "TEXT DEFAULT 'ar'"),
    ("users",             "vip_level",         "INTEGER DEFAULT 0"),
    ("users",             "currency",          "TEXT DEFAULT 'USD'"),
    ("users",             "referred_by",       "INTEGER"),
    ("users",             "referral_count",    "INTEGER DEFAULT 0"),
    ("users",             "referral_earnings", "NUMERIC DEFAULT 0"),
    ("orders",            "review_sent",       "INTEGER DEFAULT 0"),
    ("orders",            "provider_id",       "INTEGER"),
    ("provider_services", "type",              "TEXT"),
    ("provider_services", "description",       "TEXT"),
    ("provider_services", "refill",            "INTEGER"),
    ("provider_services", "cancel",            "INTEGER"),
    ("users",             "is_verified",       "INTEGER DEFAULT 0"),
    ("services",          "description_ar",    "TEXT"),
    ("moderators",        "can_services",      "INTEGER DEFAULT 0"),
    ("moderators",        "can_users",         "INTEGER DEFAULT 0"),
    ("moderators",        "can_balance",       "INTEGER DEFAULT 0"),
    ("moderators",        "can_broadcast",     "INTEGER DEFAULT 0"),
    ("moderators",        "can_orders",        "INTEGER DEFAULT 0"),
    ("moderators",        "can_providers",     "INTEGER DEFAULT 0"),
    ("moderators",        "can_stats",         "INTEGER DEFAULT 0"),
    ("moderators",        "can_games",         "INTEGER DEFAULT 0"),
    ("providers",         "provider_type",     "TEXT DEFAULT 'smm'"),
    ("game_products",     "active",            "INTEGER DEFAULT 0"),
    # ── Game enhancements (Arabic names, descriptions, sorting, validation) ──
    ("games",             "name_ar",           "TEXT"),
    ("games",             "icon_url",          "TEXT"),
    ("games",             "sort_order",        "INTEGER DEFAULT 0"),
    ("games",             "fc_game_id",        "TEXT"),
    ("game_products",     "name_ar",           "TEXT"),
    ("game_products",     "description",       "TEXT"),
    ("game_products",     "currency",          "TEXT DEFAULT 'USD'"),
    ("game_products",     "sort_order",        "INTEGER DEFAULT 0"),
    ("game_products",     "fields_json",       "TEXT"),
    ("game_products",     "min_quantity",      "INTEGER DEFAULT 1"),
    ("game_products",     "max_quantity",       "INTEGER DEFAULT 1"),
    ("game_products",     "region",            "TEXT"),
    # Idempotency reference for payments (Telegram Stars charge id, Binance trade no, etc.)
    ("transactions",      "external_ref",      "TEXT"),
    # Game manual category override (set by admin from "all packages" UI)
    ("games",             "category_key",      "TEXT"),
    # Track failed provider attempts for stuck pending orders
    ("orders",            "provider_attempts", "INTEGER DEFAULT 0"),
    ("orders",            "last_provider_error", "TEXT"),
    # Unique account number for each user (separate from Telegram ID)
    ("users",             "account_number",    "INTEGER"),
]


def _apply_sqlite_migrations(db_path: str) -> None:
    """Lightweight SQLite migration runner."""
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    for table, column, definition in _MIGRATIONS:
        try:
            cur.execute(f"SELECT {column} FROM {table} LIMIT 1")
        except sqlite3.OperationalError:
            try:
                cur.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")
                conn.commit()
                logger.info("Migration: added %s.%s", table, column)
            except sqlite3.OperationalError as exc:
                logger.debug("Migration skip %s.%s: %s", table, column, exc)
    conn.close()


async def _apply_pg_migrations(eng) -> None:
    """Lightweight PostgreSQL migration runner — adds missing columns."""
    async with eng.begin() as conn:
        for table, column, definition in _MIGRATIONS:
            # Convert SQLite types to PG-compatible
            pg_def = definition.replace("INTEGER", "INT")
            try:
                await conn.execute(sa_text(
                    f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS {column} {pg_def}"
                ))
            except Exception as exc:
                logger.debug("PG migration skip %s.%s: %s", table, column, exc)

        # ── Type alterations (safe to re-run) ──
        _type_alterations = [
            ("provider_services", "rate", "NUMERIC(20, 8)"),
            ("game_products", "active", "BOOLEAN USING active::boolean"),
            ("game_orders", "user_id", "BIGINT"),  # Fix int32 overflow for Telegram user IDs
        ]
        for table, column, new_type in _type_alterations:
            try:
                await conn.execute(sa_text(
                    f"ALTER TABLE {table} ALTER COLUMN {column} TYPE {new_type}"
                ))
                logger.info("Migration: altered %s.%s to %s", table, column, new_type)
            except Exception as exc:
                logger.debug("Type alter skip %s.%s: %s", table, column, exc)


async def init_db() -> None:
    """Create all tables and run schema migrations."""
    global engine, async_session
    from config import DATABASE_URL
    import models  # noqa: F401

    is_sqlite = "sqlite" in DATABASE_URL

    if is_sqlite:
        engine_kwargs = {
            "echo": False,
            "connect_args": {"timeout": 30},
            "pool_pre_ping": True,
        }
    else:
        # Auto-switch to Neon pooler endpoint — avoids cold-start 3-5s delays
        # The pooler (PgBouncer) keeps connections warm and handles bursts
        _db_url = DATABASE_URL
        if "neon.tech" in _db_url and "-pooler" not in _db_url:
            # ep-xxx.c-4.us-east-1.aws.neon.tech → ep-xxx-pooler.c-4.us-east-1.aws.neon.tech
            import re
            _db_url = re.sub(r"(ep-[^.]+)(\.)", r"\1-pooler\2", _db_url, count=1)
            logger.info("Auto-switched to Neon pooler endpoint for faster connections")
        DATABASE_URL = _db_url

        engine_kwargs = {
            "echo": False,
            "pool_pre_ping": True,
            "pool_size": 5,            # Neon pooler handles multiplexing — keep small
            "max_overflow": 10,        # Burst up to 15 total connections
            "pool_timeout": 10,        # Fail fast if pool exhausted
            "pool_recycle": 300,       # Recycle every 5 min to keep connections fresh
            "connect_args": {
                "server_settings": {
                    "application_name": "smm_bot",
                    "statement_timeout": "20000",  # 20s query timeout
                },
                "command_timeout": 20,
                "prepared_statement_cache_size": 0,  # Required for PgBouncer/Neon pooler
            },
        }

    engine = create_async_engine(DATABASE_URL, **engine_kwargs)
    async_session = async_sessionmaker(engine, expire_on_commit=False)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        if is_sqlite:
            await conn.execute(sa_text("PRAGMA journal_mode=WAL"))
            await conn.execute(sa_text("PRAGMA busy_timeout=30000"))

    # Run migrations
    if is_sqlite:
        db_path = DATABASE_URL.replace("sqlite+aiosqlite:///", "")
        if not os.path.isabs(db_path):
            db_path = os.path.join(os.getcwd(), db_path)
        try:
            _apply_sqlite_migrations(db_path)
        except Exception as exc:
            logger.warning("SQLite migration error: %s", exc)
    else:
        try:
            await _apply_pg_migrations(engine)
        except Exception as exc:
            logger.warning("PG migration error: %s", exc)

    # Log connection (hide password)
    safe_url = DATABASE_URL
    if "@" in safe_url:
        safe_url = safe_url.split("@")[0].rsplit(":", 1)[0] + "@****"
    logger.info("Database ready: %s", safe_url)
