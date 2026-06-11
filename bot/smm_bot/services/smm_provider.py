"""
Low-level SMM provider API calls.
All functions use the shared session pool (no per-call ClientSession creation).
Timeouts are enforced by the global DEFAULT_TIMEOUT in http_client.py.
"""
import logging
import aiohttp

from services.http_client import get_session

logger = logging.getLogger(__name__)


# Timeouts per operation type
_PLACE_TIMEOUT  = aiohttp.ClientTimeout(total=10)   # وضع الطلب: 10 ثانية
_STATUS_TIMEOUT = aiohttp.ClientTimeout(total=8)    # فحص الحالة: 8 ثوانٍ
_SYNC_TIMEOUT   = aiohttp.ClientTimeout(total=30)   # سحب الكتالوج: 30 ثانية


async def place_order(
    api_url: str,
    api_key: str,
    service_id: str,
    link: str,
    quantity: int,
) -> dict:
    payload = {
        "key": api_key,
        "action": "add",
        "service": service_id,
        "link": link,
        "quantity": quantity,
    }
    session = await get_session()
    async with session.post(api_url, data=payload, timeout=_PLACE_TIMEOUT) as resp:
        resp.raise_for_status()
        return await resp.json(content_type=None)


async def get_order_status(api_url: str, api_key: str, order_id: str) -> dict:
    payload = {"key": api_key, "action": "status", "order": order_id}
    session = await get_session()
    async with session.post(api_url, data=payload, timeout=_STATUS_TIMEOUT) as resp:
        resp.raise_for_status()
        return await resp.json(content_type=None)


async def fetch_services(api_url: str, api_key: str) -> list:
    """Fetch full service list from a provider. Returns [] on any error."""
    payload = {"key": api_key, "action": "services"}
    try:
        session = await get_session()
        async with session.post(api_url, data=payload, timeout=_SYNC_TIMEOUT) as resp:
            resp.raise_for_status()
            data = await resp.json(content_type=None)
            return data if isinstance(data, list) else []
    except aiohttp.ClientError as exc:
        logger.warning("fetch_services failed for %s: %s", api_url, exc)
        return []
    except Exception as exc:
        logger.error("fetch_services unexpected error: %s", exc, exc_info=True)
        return []
