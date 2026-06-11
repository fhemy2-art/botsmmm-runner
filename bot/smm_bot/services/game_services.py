import logging
import aiohttp
from services.http_client import get_session
from services import fazercards_provider

logger = logging.getLogger(__name__)

FAZERCARDS_MARKER = "fazercards"


def _is_fazercards(api_url: str) -> bool:
    """Detect FazerCards provider by checking the API URL."""
    return FAZERCARDS_MARKER in api_url.lower()


# ── Validate Player ID ───────────────────────────────────
# Maps fc_game_id (long) → short validation code used by /checkplayerid
_VALIDATION_CODES = {
    # PUBG Mobile variants
    "pubg_mobile_gl_auto": "pubgm",
    "pubg_mobile": "pubgm",
    "pubg_mobile_manual": "pubgm",
    "pubg_mobile_mena": "pubgm",
    # Mobile Legends variants (requires server_id)
    "mobile_legends_bang_bang": "mlbb",
    "mobile_legends": "mlbb",
    # Genshin Impact (requires server_id)
    "genshin_impact": "genshin",
    "genshin_v2": "genshin",
    "genshin_impact_br": "genshin",
    # Arena Breakout
    "arena_breakout": "arena_breakout",
    # Honor of Kings
    "honor_of_kings": "hok",
    # Undawn
    "undawn_global": "undawn_global",
}

# Games that require server_id for validation
_NEEDS_SERVER_ID = {"mlbb", "genshin"}


def get_validation_code(fc_game_id: str) -> str | None:
    """Get the short validation code for a FazerCards game_id."""
    if not fc_game_id:
        return None
    lower = fc_game_id.lower()
    # Direct match
    if lower in _VALIDATION_CODES:
        return _VALIDATION_CODES[lower]
    # Partial match (e.g. pubg_mobile_gl_auto_123 → pubgm)
    for long_id, short_code in _VALIDATION_CODES.items():
        if long_id in lower or lower.startswith(long_id):
            return short_code
    return None


def needs_server_id(validation_code: str) -> bool:
    """Check if this game requires a server_id for validation."""
    return validation_code in _NEEDS_SERVER_ID


async def validate_player_id(fc_game_id: str, player_id: str, server_id: str = "") -> dict | None:
    """
    Validate player ID via FazerCards /checkplayerid endpoint.
    Returns:
      - {"valid": True, "name": "PlayerName"} on success
      - {"valid": False, "error": "..."} on invalid ID
      - None if validation not available for this game
    """
    if not fc_game_id or not player_id:
        return None

    validation_code = get_validation_code(fc_game_id)
    if not validation_code:
        return None  # This game doesn't support validation

    try:
        result = await fazercards_provider.check_player_id(
            game_code=validation_code,
            user_id=player_id,
            server_id=server_id
        )
        if result and isinstance(result, dict):
            if result.get("valid"):
                return {
                    "valid": True,
                    "name": result.get("name", ""),
                    "openid": result.get("openid", ""),
                }
            if result.get("error"):
                return {
                    "valid": False,
                    "error": result.get("message", result.get("error", "Invalid player ID")),
                }
        return None
    except Exception as e:
        logger.warning(f"Player ID validation error for game={fc_game_id}: {e}")
        return None


# ── Place Order ────────────────────────────────────────────
async def game_api_place_order(
    api_url: str,
    api_key: str,
    service_id: str,
    account_id: str,
    extra_data: dict = None
) -> dict:
    """
    Place a game top-up order.
    Routes to FazerCards REST API or generic SMM API automatically.
    """
    if _is_fazercards(api_url):
        return await _fazercards_place_order(service_id, account_id, extra_data)

    # ── Generic SMM-style API (action=add) ──
    payload = {
        "key": api_key,
        "action": "add",
        "service": service_id,
        "link": account_id,
    }
    if extra_data:
        payload.update(extra_data)

    try:
        session = await get_session()
        async with session.post(api_url, data=payload) as resp:
            resp.raise_for_status()
            return await resp.json(content_type=None)
    except Exception as e:
        logger.error(f"Error placing game order: {e}")
        return {"error": str(e)}


async def _fazercards_place_order(product_id: str, account_id: str, extra_data: dict = None) -> dict:
    """Place order via FazerCards API and normalize the response."""
    game_fields = {"player_id": account_id}
    if extra_data:
        game_fields.update(extra_data)

    result = await fazercards_provider.create_topup_order(
        product_id=product_id,
        quantity=1,
        game_fields=game_fields,
    )

    if not result:
        return {"error": "No response from FazerCards API"}

    if isinstance(result, dict):
        # Normalize to expected {"order": "<id>"} format
        if "order_id" in result:
            return {"order": str(result["order_id"])}
        if "id" in result:
            return {"order": str(result["id"])}
        if "error" in result or "message" in result:
            return {"error": result.get("error", result.get("message", "Unknown FazerCards error"))}
        # If the response has an order-like structure, try to extract order identifier
        if "data" in result and isinstance(result["data"], dict):
            order_data = result["data"]
            if "order_id" in order_data:
                return {"order": str(order_data["order_id"])}
            if "id" in order_data:
                return {"order": str(order_data["id"])}
        return result

    return {"error": "Unexpected FazerCards response format"}


# ── Check Status ───────────────────────────────────────────
async def game_api_check_status(api_url: str, api_key: str, external_order_id: str) -> dict:
    """
    Check status of a game order.
    Routes to FazerCards or generic SMM API.
    """
    if _is_fazercards(api_url):
        return await _fazercards_check_status(external_order_id)

    # ── Generic SMM API (action=status) ──
    payload = {
        "key": api_key,
        "action": "status",
        "order": external_order_id,
    }
    try:
        session = await get_session()
        async with session.post(api_url, data=payload) as resp:
            resp.raise_for_status()
            return await resp.json(content_type=None)
    except Exception as e:
        logger.error(f"Error checking game order status: {e}")
        return {"error": str(e)}


async def _fazercards_check_status(order_id: str) -> dict:
    """Check FazerCards order status and normalize."""
    result = await fazercards_provider.get_order_status(order_id)
    if result and isinstance(result, dict):
        status = result.get("status", "unknown").lower()
        # Normalize FazerCards statuses
        fc_status_map = {
            "success": "completed",
            "done": "completed",
            "completed": "completed",
            "delivered": "completed",
            "processing": "processing",
            "pending": "pending",
            "in_progress": "processing",
            "failed": "canceled",
            "cancelled": "canceled",
            "canceled": "canceled",
            "refunded": "canceled",
        }
        return {"status": fc_status_map.get(status, status)}
    return {"error": "No response from FazerCards"}


# ── Get Products ───────────────────────────────────────────
async def game_api_get_products(api_url: str, api_key: str) -> list:
    """
    Fetch products from game provider.
    Routes to FazerCards or generic SMM API.
    """
    if _is_fazercards(api_url):
        return await _fazercards_get_products()

    # ── Generic SMM API (action=services) ──
    payload = {
        "key": api_key,
        "action": "services",
    }
    try:
        session = await get_session()
        async with session.post(api_url, data=payload) as resp:
            resp.raise_for_status()
            data = await resp.json(content_type=None)
            return data if isinstance(data, list) else []
    except Exception as e:
        logger.error(f"Error fetching game products: {e}")
        return []


async def _fazercards_get_products() -> list:
    """Fetch all FazerCards games + products, normalized with full details."""
    games = await fazercards_provider.get_games()
    if not games:
        logger.warning("FazerCards: No games returned from API")
        return []

    all_products = []
    for game in games:
        game_id = str(game.get("id", ""))
        game_name = game.get("name", "Unknown Game")
        game_icon = game.get("icon_url", "")

        products = await fazercards_provider.get_topup_products(game_id)
        if not products:
            continue

        for p in products:
            all_products.append({
                "service": str(p.get("id", "")),
                "name": p.get("display_name", p.get("name", "Unknown")),
                "rate": float(p.get("price", p.get("cost", p.get("amount", 0)))),
                "game_name": game_name,
                "game_id": game_id,
                "game_icon": game_icon,
                # ── New fields ──
                "description": p.get("note", ""),
                "currency": p.get("currency", "USD"),
                "fields": p.get("fields", []),
                "min_quantity": p.get("min_quantity", 1),
                "max_quantity": p.get("max_quantity", 1),
                "region": p.get("region", ""),
            })

    logger.info(f"FazerCards: Fetched {len(all_products)} products from {len(games)} games")
    return all_products
