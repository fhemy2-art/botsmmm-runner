"""
Global HTTP session pool.
A single aiohttp.ClientSession is created once at startup and reused for all
outbound provider API calls. This eliminates the overhead of creating a new
TCP connection per request.

Usage:
    from services.http_client import get_session
    session = await get_session()
    async with session.post(...) as resp: ...
"""
import asyncio
import logging
import aiohttp
from config import HTTP_TIMEOUT_SECONDS

logger = logging.getLogger(__name__)

_session: aiohttp.ClientSession | None = None
_lock = asyncio.Lock()

DEFAULT_TIMEOUT = aiohttp.ClientTimeout(
    total=HTTP_TIMEOUT_SECONDS,
    connect=10,       # max 10s to establish connection
    sock_read=HTTP_TIMEOUT_SECONDS,
)


async def get_session() -> aiohttp.ClientSession:
    """Return the shared ClientSession, creating it if necessary."""
    global _session
    if _session is None or _session.closed:
        async with _lock:
            if _session is None or _session.closed:
                connector = aiohttp.TCPConnector(
                    limit=100,             # max open connections (to all hosts)
                    limit_per_host=20,     # max per provider API host
                    ttl_dns_cache=300,     # cache DNS 5 min
                    enable_cleanup_closed=True,
                )
                _session = aiohttp.ClientSession(
                    timeout=DEFAULT_TIMEOUT,
                    connector=connector,
                    headers={"User-Agent": "SMM-Bot/1.0"},
                )
                logger.info("HTTP session pool created (limit=100, per_host=20)")
    return _session


async def close_session() -> None:
    """Gracefully close the shared session on shutdown."""
    global _session
    if _session and not _session.closed:
        await _session.close()
        logger.info("HTTP session pool closed")
