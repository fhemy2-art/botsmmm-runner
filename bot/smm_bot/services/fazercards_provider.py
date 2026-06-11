"""
FazerCards API provider — game top-ups, gift cards, Steam, Roblox, Telegram.
Base URL: https://api.fazercards.com
Auth: x-api-key header
Docs: https://api.fazercards.com/docs
"""
import logging
from typing import Any

from services.http_client import get_session
from config import FAZERCARDS_API_KEY

logger = logging.getLogger(__name__)

BASE_URL = "https://api.fazercards.com/api/v1"
_HEADERS = {"x-api-key": FAZERCARDS_API_KEY, "Accept": "application/json", "Content-Type": "application/json"}


async def _get(path: str, params: dict | None = None) -> dict | list | None:
    """GET request to FazerCards API."""
    session = await get_session()
    try:
        async with session.get(f"{BASE_URL}{path}", headers=_HEADERS, params=params) as resp:
            if resp.status == 200:
                return await resp.json(content_type=None)
            logger.warning("FazerCards GET %s → %s", path, resp.status)
            return None
    except Exception as exc:
        logger.error("FazerCards GET %s error: %s", path, exc)
        return None


async def _post(path: str, body: dict | None = None) -> dict | list | None:
    """POST request to FazerCards API."""
    session = await get_session()
    try:
        async with session.post(f"{BASE_URL}{path}", headers=_HEADERS, json=body or {}) as resp:
            data = await resp.json(content_type=None)
            if resp.status == 200:
                return data
            logger.warning("FazerCards POST %s → %s: %s", path, resp.status, data)
            return data  # Return error details too
    except Exception as exc:
        logger.error("FazerCards POST %s error: %s", path, exc)
        return None


# ── Account ────────────────────────────────────────────────
async def get_balance() -> dict | None:
    """Get balance: {currency, available}"""
    return await _get("/balance")


async def get_me() -> dict | None:
    """Get account info."""
    return await _get("/me")


# ── Games & Top-ups ───────────────────────────────────────
async def get_games() -> list | None:
    """Get aggregated games list: [{id, name, icon_url, types, is_featured}]"""
    result = await _get("/games")
    if isinstance(result, dict) and "games" in result:
        return result["games"]
    return result if isinstance(result, list) else None


async def get_topup_products(game_id: str = "") -> list | None:
    """Get top-up products by game. Pass game_id as query param."""
    params = {"game_id": game_id} if game_id else {}
    result = await _get("/topup/products", params=params)
    if isinstance(result, dict) and "products" in result:
        return result["products"]
    return result if isinstance(result, list) else None


async def create_topup_order(product_id: str, quantity: int = 1, game_fields: dict | None = None) -> dict | None:
    """Create a game top-up order."""
    body = {"product_id": product_id, "quantity": quantity}
    if game_fields:
        body["game_fields"] = game_fields
    return await _post("/topup/order", body)


async def check_player_id(game_code: str, user_id: str, server_id: str = "") -> dict | None:
    """
    Validate player ID before placing order.
    API uses short game codes (pubgm, mlbb, genshin, arena_breakout).
    Params: game (required), user_id (required), server_id (optional).
    Returns: {"valid": "valid", "name": "PlayerName", "openid": "..."} on success
             {"error": "Validation failed", ...} on invalid ID
    """
    params = {"game": game_code, "user_id": user_id}
    if server_id:
        params["server_id"] = server_id
    return await _get("/checkplayerid", params=params)


# ── Gift Cards ─────────────────────────────────────────────
async def get_giftcard_products() -> list | None:
    """Get all gift card products."""
    result = await _get("/giftcards/products")
    if isinstance(result, dict) and "products" in result:
        return result["products"]
    return result if isinstance(result, list) else None


async def create_giftcard_order(product_id: str, quantity: int = 1) -> dict | None:
    """Create a gift card order."""
    return await _post("/giftcards/order", {"product_id": product_id, "quantity": quantity})


# ── Game Keys (Steam/Xbox/Other) ─────────────────────────
async def get_gamekey_categories() -> list | None:
    """List game key categories (steam/xbox/other)."""
    result = await _get("/gamekeys")
    if isinstance(result, dict):
        return result.get("categories", result.get("data", [result]))
    return result if isinstance(result, list) else None


async def get_gamekey_products(game_id: str) -> list | None:
    """Get products for a game key category."""
    return await _post("/gamekeys/products", {"game_id": game_id})


async def create_gamekey_order(product_id: str, quantity: int = 1) -> dict | None:
    """Create a game key order."""
    return await _post("/gamekeys/order", {"product_id": product_id, "quantity": quantity})


# ── Steam ──────────────────────────────────────────────────
async def get_steam_gift_games() -> list | None:
    """List Steam giftable games."""
    return await _get("/steamgifts/games")


async def get_steam_topup_rates() -> list | None:
    """Get Steam exchange rates."""
    return await _get("/steamtopup/rates")


async def create_steam_topup(username: str, amount_usd: float) -> dict | None:
    """Create Steam balance top-up order."""
    return await _post("/steamtopup/order", {"username": username, "amount_usd": amount_usd})


# ── Roblox ─────────────────────────────────────────────────
async def get_roblox_products() -> list | None:
    """Get Roblox packs products."""
    result = await _get("/roblox/packages/products")
    if isinstance(result, dict) and "products" in result:
        return result["products"]
    return result if isinstance(result, list) else None


# ── Telegram ───────────────────────────────────────────────
async def get_telegram_premium_offers() -> list | None:
    """Get Telegram Premium gift offers."""
    return await _get("/telegram/premium")


async def get_telegram_stars_offers() -> list | None:
    """Get Telegram Stars offers."""
    result = await _get("/telegram/stars")
    if isinstance(result, dict) and "offers" in result:
        return result["offers"]
    return result if isinstance(result, list) else None


async def buy_telegram_stars(username: str, amount: int) -> dict | None:
    """Buy Telegram Stars."""
    return await _post("/telegram/stars/buy", {"username": username, "amount": amount})


# ── Orders ─────────────────────────────────────────────────
async def get_orders() -> dict | None:
    """Get user orders."""
    return await _get("/orders")


async def get_order_status(order_id: str) -> dict | None:
    """Get specific order status."""
    return await _get(f"/orders/{order_id}")
