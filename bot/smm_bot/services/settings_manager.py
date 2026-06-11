"""
Runtime settings manager — reads/writes bot_settings.json.
Admin can change markup %, min order value, maintenance mode, etc.
without restarting the bot.
"""
import json
import logging
import os

logger = logging.getLogger(__name__)

_DEFAULTS: dict = {
    "markup_pct": 30.0,          # % added on top of provider price
    "min_order_usd": 0.01,       # minimum order charge in USD
    "maintenance": False,         # maintenance mode — blocks all user orders
    "referral_reward": 0.1,      # USD per successful referral
    "stars_per_usd": 100,        # how many stars = $1
    "platform_order": [],        # custom platform display order
    "platform_columns": 1,       # 1 or 2 platforms per row
    "platform_names": {},        # custom platform display names {"telegram": "تلقرام 🔥"}
    "hidden_platforms": [],      # platforms hidden from users
    "category_columns": 1,       # 1 or 2 categories per row
    "category_names": {},        # custom category names {"متابعين": "متابعين 🔥"}
    "hidden_categories": {},     # per-platform hidden categories {"telegram": ["خدمات أخرى"]}
    "category_order": {},        # per-platform category order {"telegram": ["متابعين", "مشاهدات"]}
    "game_markup_pct": 15.0,     # % markup for game products
}

_settings: dict = {}
_path: str = ""


def _load(path: str) -> None:
    global _settings, _path
    _path = path
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                _settings = json.load(f)
        except Exception as exc:
            logger.warning("Could not load settings: %s", exc)
            _settings = {}
    else:
        _settings = {}


def _save() -> None:
    try:
        with open(_path, "w", encoding="utf-8") as f:
            json.dump(_settings, f, ensure_ascii=False, indent=2)
    except Exception as exc:
        logger.error("Could not save settings: %s", exc)


def init_settings(path: str) -> None:
    _load(path)


def get(key: str):
    return _settings.get(key, _DEFAULTS.get(key))


def set_setting(key: str, value) -> None:
    _settings[key] = value
    _save()


def get_all() -> dict:
    merged = dict(_DEFAULTS)
    merged.update(_settings)
    return merged


def get_markup_pct() -> float:
    v = get("markup_pct")
    return float(v) if v is not None else 30.0


def get_markup_multiplier() -> float:
    return 1 + get_markup_pct() / 100


# ── Store layout helpers ─────────────────────────────────────────────────────

def get_platform_order() -> list[str]:
    return get("platform_order") or []

def set_platform_order(order: list[str]) -> None:
    set_setting("platform_order", order)

def get_platform_columns() -> int:
    return int(get("platform_columns") or 1)

def set_platform_columns(cols: int) -> None:
    set_setting("platform_columns", max(1, min(2, cols)))

def get_platform_custom_name(platform: str) -> str | None:
    names = get("platform_names") or {}
    return names.get(platform)

def set_platform_custom_name(platform: str, name: str) -> None:
    names = dict(get("platform_names") or {})
    names[platform] = name
    set_setting("platform_names", names)

def remove_platform_custom_name(platform: str) -> None:
    names = dict(get("platform_names") or {})
    names.pop(platform, None)
    set_setting("platform_names", names)

def get_hidden_platforms() -> list[str]:
    return get("hidden_platforms") or []

def set_hidden_platforms(hidden: list[str]) -> None:
    set_setting("hidden_platforms", hidden)

def get_category_columns() -> int:
    return int(get("category_columns") or 1)

def set_category_columns(cols: int) -> None:
    set_setting("category_columns", max(1, min(2, cols)))

def get_category_custom_name(category: str) -> str | None:
    names = get("category_names") or {}
    return names.get(category)

def set_category_custom_name(old_name: str, new_name: str) -> None:
    names = dict(get("category_names") or {})
    names[old_name] = new_name
    set_setting("category_names", names)

def get_hidden_categories(platform: str) -> list[str]:
    hidden = get("hidden_categories") or {}
    return hidden.get(platform, [])

def set_hidden_category(platform: str, category: str, hide: bool) -> None:
    hidden = dict(get("hidden_categories") or {})
    plat_list = list(hidden.get(platform, []))
    if hide and category not in plat_list:
        plat_list.append(category)
    elif not hide and category in plat_list:
        plat_list.remove(category)
    hidden[platform] = plat_list
    set_setting("hidden_categories", hidden)

def get_category_order(platform: str) -> list[str]:
    orders = get("category_order") or {}
    return orders.get(platform, [])

def set_category_order(platform: str, order: list[str]) -> None:
    orders = dict(get("category_order") or {})
    orders[platform] = order
    set_setting("category_order", orders)


# ── Game markup helpers ──────────────────────────────────────────────────────

def get_game_markup_pct() -> float:
    v = get("game_markup_pct")
    return float(v) if v is not None else 15.0

def set_game_markup_pct(pct: float) -> None:
    set_setting("game_markup_pct", pct)

def get_game_markup_multiplier() -> float:
    return 1 + get_game_markup_pct() / 100


# ── Agents (Resellers) helpers ───────────────────────────────────────────────

def get_agents() -> dict[str, float]:
    """Returns {str(user_id): discount_pct} for all registered agents."""
    return dict(get("agents") or {})


def is_agent(user_id: int) -> bool:
    agents = get_agents()
    return str(user_id) in agents


def get_agent_discount(user_id: int) -> float:
    """Returns the agent's discount percentage (0 if not an agent)."""
    agents = get_agents()
    return float(agents.get(str(user_id), 0))


def set_agent(user_id: int, discount_pct: float) -> None:
    agents = get_agents()
    agents[str(user_id)] = float(max(0, min(100, discount_pct)))
    set_setting("agents", agents)


def remove_agent(user_id: int) -> bool:
    agents = get_agents()
    key = str(user_id)
    if key not in agents:
        return False
    del agents[key]
    set_setting("agents", agents)
    return True
