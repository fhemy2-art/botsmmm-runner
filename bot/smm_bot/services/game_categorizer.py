"""
Game categorisation helpers.

Used by the admin "all packages" UI to group hundreds of games into a small
number of human-friendly buckets (battle royale, MOBA, gift cards, etc.) so
admins do not have to flip through dozens of raw paginated pages.

Each game is classified by name pattern only — there is no schema change
required. Admins can override classification through the new
`Game.category_key` column (set via the admin panel) which always wins.
"""
from __future__ import annotations

from collections import OrderedDict


# Stable category keys used in callback_data. Keep them short (≤ 12 chars)
# because callback_data has a 64-byte limit.
CATEGORIES: "OrderedDict[str, dict]" = OrderedDict([
    ("popular",    {"icon": "🔥", "ar": "الأكثر طلباً",     "en": "Most popular"}),
    ("battle",     {"icon": "🎯", "ar": "باتل رويال",       "en": "Battle Royale"}),
    ("moba",       {"icon": "⚔️", "ar": "ألعاب MOBA",       "en": "MOBA"}),
    ("rpg",        {"icon": "🗡️", "ar": "RPG ومغامرات",    "en": "RPG / Adventure"}),
    ("casual",     {"icon": "🎲", "ar": "ألعاب خفيفة",      "en": "Casual"}),
    ("sports",     {"icon": "⚽", "ar": "ألعاب رياضية",     "en": "Sports"}),
    ("strategy",   {"icon": "♟️", "ar": "ألعاب استراتيجية", "en": "Strategy"}),
    ("giftcards",  {"icon": "🎁", "ar": "بطاقات هدايا",     "en": "Gift Cards"}),
    ("subs",       {"icon": "📺", "ar": "اشتراكات",         "en": "Subscriptions"}),
    ("social",     {"icon": "💬", "ar": "تواصل اجتماعي",    "en": "Social"}),
    ("other",      {"icon": "📦", "ar": "أخرى",             "en": "Other"}),
])


# Hardcoded "popular" list — used as a baseline when there are not enough
# real GameOrder rows to derive popularity from data.
POPULAR_GAMES: tuple[str, ...] = (
    "pubg", "free fire", "mobile legends", "genshin impact", "honkai star rail",
    "roblox", "fortnite", "call of duty", "clash of clans", "clash royale",
    "brawl stars", "valorant", "minecraft", "efootball", "ea fc", "fifa",
    "honor of kings", "standoff", "stumble guys", "8 ball pool", "among us",
    "blood strike",
)


# Patterns drive automatic classification. Order matters: first match wins.
_PATTERNS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("battle", (
        "pubg", "free fire", "freefire", "fortnite", "call of duty", "cod ",
        "warzone", "blood strike", "arena breakout", "apex", "standoff",
    )),
    ("moba", (
        "mobile legends", "honor of kings", "league of legends", "dota",
        "wild rift", "vainglory",
    )),
    ("rpg", (
        "genshin", "honkai", "tower of fantasy", "ragnarok", "diablo",
        "raid shadow", "ragna", "lifeafter", "identity v", "punishing gray",
        "dragon ball", "naruto", "one punch", "lineage", "albion",
        "wuthering waves", "ashfall", "nikke",
    )),
    ("casual", (
        "stumble", "among us", "super sus", "8 ball", "ludo", "subway surfers",
        "candy crush", "temple run", "uno", "carrom", "fall guys",
    )),
    ("sports", (
        "fifa", "efootball", "ea fc", "nba", "f1 ", "ufc", "pes ", "cricket",
        "basketball", "volleyball",
    )),
    ("strategy", (
        "clash of clans", "clash royale", "rise of kingdoms", "lords mobile",
        "state of survival", "last shelter", "evony", "summoners war",
        "boom beach", "rush royale", "valorant", "rainbow six",
    )),
    ("giftcards", (
        "itunes", "google play", "steam", "playstation", "xbox", "nintendo",
        "amazon", "razer gold", "razer", "noon", "shahid", "anghami",
        "spotify card", "apple", "psn", "eshop", "blizzard",
    )),
    ("subs", (
        "netflix", "spotify", "disney", "shahid", "anghami", "youtube premium",
        "premium", "pass", "membership", "subscription", "tinder",
        "discord nitro", "crunchyroll",
    )),
    ("social", (
        "telegram", "whatsapp", "snapchat", "tiktok", "instagram", "twitter",
        "facebook", "discord",
    )),
)


def classify_game(name: str, override: str | None = None) -> str:
    """
    Return the category key for a game.
    Admin override (Game.category_key) always wins. Otherwise pattern-match
    on the (lower-cased) name. Falls back to "other".
    """
    if override and override in CATEGORIES:
        return override

    if not name:
        return "other"
    n = name.lower()

    for key, patterns in _PATTERNS:
        for pat in patterns:
            if pat in n:
                return key
    return "other"


def is_popular(name: str) -> bool:
    """Hardcoded popularity baseline used when no order data exists yet."""
    if not name:
        return False
    n = name.lower()
    return any(pat in n for pat in POPULAR_GAMES)


def category_label(key: str, lang: str = "ar") -> str:
    """Human-readable category name with icon."""
    info = CATEGORIES.get(key)
    if not info:
        return key
    return f"{info['icon']} {info['ar' if lang == 'ar' else 'en']}"


def all_category_keys() -> list[str]:
    """All category keys in display order, excluding the synthetic 'popular'."""
    return [k for k in CATEGORIES.keys() if k != "popular"]
