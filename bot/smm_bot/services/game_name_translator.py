"""
Game name translator (English ⇄ Arabic).

Used as fallback by handlers/user/game_handlers.py when Game.name_ar /
GameProduct.name_ar are not populated by the admin.

Strategy:
  • exact match against curated dictionary of popular games
  • normalized match (lowercase, strip emojis, strip "Mobile"/"PC" suffixes)
  • partial match (game name contained in the input)
  • generic product translation (UC, Diamonds, Robux, V-Bucks, ...)
"""
from __future__ import annotations
import re

# ─── Game name dictionary (English → Arabic) ────────────────────────────────
# Keys MUST be lowercase, no emojis, no extra punctuation.
_GAME_AR: dict[str, str] = {
    # Battle Royale / Shooter
    "pubg":                 "ببجي",
    "pubg mobile":          "ببجي موبايل",
    "pubg lite":            "ببجي لايت",
    "pubg new state":       "ببجي نيو ستيت",
    "free fire":            "فري فاير",
    "garena free fire":     "فري فاير",
    "free fire max":        "فري فاير ماكس",
    "call of duty":         "كول أوف ديوتي",
    "call of duty mobile":  "كول أوف ديوتي موبايل",
    "cod mobile":           "كول أوف ديوتي موبايل",
    "cod warzone":          "كول أوف ديوتي وارزون",
    "warzone":              "وارزون",
    "fortnite":             "فورتنايت",
    "apex legends":         "إيبكس ليجندز",
    "apex":                 "إيبكس",
    "valorant":             "فالورانت",
    "rainbow six":          "رينبو سكس",
    "counter strike":       "كاونتر سترايك",
    "cs:go":                "كاونتر سترايك",
    "csgo":                 "كاونتر سترايك",
    "cs2":                  "كاونتر سترايك 2",
    "rust":                 "راست",
    "tarkov":               "تاركوف",
    "escape from tarkov":   "تاركوف",

    # MOBA
    "mobile legends":       "موبايل ليجندز",
    "mobile legends bang bang": "موبايل ليجندز",
    "mlbb":                 "موبايل ليجندز",
    "league of legends":    "ليج أوف ليجندز",
    "lol":                  "ليج أوف ليجندز",
    "wild rift":            "وايلد ريفت",
    "league of legends wild rift": "وايلد ريفت",
    "dota 2":               "دوتا 2",
    "dota":                 "دوتا",
    "arena of valor":       "أرينا أوف فالور",
    "honor of kings":       "هونر أوف كينجز",
    "smite":                "سمايت",

    # MMORPG / RPG / Gacha
    "genshin impact":       "جنشن إمباكت",
    "genshin":              "جنشن",
    "honkai star rail":     "هونكاي ستار رايل",
    "honkai":               "هونكاي",
    "honkai impact":        "هونكاي إمباكت",
    "zenless zone zero":    "زنلس زون زيرو",
    "zzz":                  "زنلس زون زيرو",
    "wuthering waves":      "ووذرنغ ويفز",
    "tower of fantasy":     "تاور أوف فانتسي",
    "diablo immortal":      "ديابلو إيمورتال",
    "diablo":               "ديابلو",
    "world of warcraft":    "وورلد أوف ووركرافت",
    "wow":                  "وورلد أوف ووركرافت",
    "final fantasy xiv":    "فاينل فانتسي 14",
    "ffxiv":                "فاينل فانتسي 14",
    "elder scrolls online": "إلدر سكرولز أونلاين",
    "eso":                  "إلدر سكرولز أونلاين",
    "lost ark":             "لوست آرك",
    "black desert":         "بلاك ديزرت",
    "blade and soul":       "بليد آند سول",
    "rok":                  "رايز أوف كينجدمز",
    "rise of kingdoms":     "رايز أوف كينجدمز",

    # Sandbox / Builder
    "minecraft":            "ماين كرافت",
    "roblox":               "روبلوكس",
    "terraria":             "تيراريا",
    "growtopia":            "جروتوبيا",

    # Sports / Racing / Simulation
    "fifa":                 "فيفا",
    "fc 24":                "إي إيه إف سي 24",
    "fc 25":                "إي إيه إف سي 25",
    "ea sports fc":         "إي إيه إف سي",
    "ea sports fc 24":      "إي إيه إف سي 24",
    "ea sports fc 25":      "إي إيه إف سي 25",
    "fifa mobile":          "فيفا موبايل",
    "efootball":            "إي فوتبول",
    "pes":                  "بيس",
    "nba 2k":               "إن بي إيه 2 كي",
    "f1":                   "فورمولا 1",
    "forza horizon":        "فورزا هورايزن",

    # Strategy / Card / Casino
    "clash royale":         "كلاش رويال",
    "clash of clans":       "كلاش أوف كلانز",
    "coc":                  "كلاش أوف كلانز",
    "brawl stars":          "براول ستارز",
    "hay day":              "هاي داي",
    "boom beach":           "بوم بيتش",
    "hearthstone":          "هارث ستون",
    "magic the gathering":  "ماجك ذا غاذرنغ",
    "yu-gi-oh":             "يوغي يو",
    "pokemon go":           "بوكيمون جو",
    "pokemon":              "بوكيمون",

    # Casual / Mobile
    "candy crush":          "كاندي كراش",
    "subway surfers":       "صب واي سيرفرز",
    "8 ball pool":          "بلياردو 8 كرات",
    "ludo king":            "لودو كينج",
    "carrom pool":          "كاروم بول",
    "among us":             "أمونغ أس",
    "stumble guys":         "ستامبل غايز",
    "fall guys":            "فول غايز",

    # Gift cards / Subscriptions / Misc
    "google play":          "جوجل بلاي",
    "apple itunes":         "آبل آيتونز",
    "itunes":               "آيتونز",
    "app store":            "آب ستور",
    "playstation":          "بلايستيشن",
    "psn":                  "بلايستيشن نتورك",
    "ps plus":              "بلايستيشن بلس",
    "xbox":                 "إكس بوكس",
    "xbox live":            "إكس بوكس لايف",
    "xbox game pass":       "إكس بوكس جيم باس",
    "nintendo":             "نينتندو",
    "nintendo eshop":       "نينتندو إي شوب",
    "steam":                "ستيم",
    "razer gold":           "ريزر جولد",
    "amazon":               "أمازون",
    "netflix":              "نتفلكس",
    "spotify":              "سبوتيفاي",
    "youtube premium":      "يوتيوب بريميوم",
    "discord nitro":        "ديسكورد نيترو",

    # Shahid / regional
    "shahid":               "شاهد",
    "shahid vip":           "شاهد VIP",
    "anghami":              "أنغامي",
    "osn":                  "أو إس إن",
    "starz play":           "ستارز بلاي",
}

# ─── Generic product / currency translations ────────────────────────────────
# Used to translate things like "60 UC", "100 Diamonds", "1000 Robux"
_PRODUCT_AR: dict[str, str] = {
    "uc":                "شدة",
    "unknown cash":      "شدة",
    "diamonds":          "جواهر",
    "diamond":           "جوهرة",
    "gems":              "أحجار كريمة",
    "gem":               "حجر كريم",
    "gold":              "ذهب",
    "coins":             "عملات",
    "coin":              "عملة",
    "robux":             "روبكس",
    "v-bucks":           "في-باكس",
    "vbucks":            "في-باكس",
    "primogems":         "بريموجمز",
    "genesis crystals":  "كريستالات جينيسيس",
    "stellar jade":      "ستيلر جيد",
    "oneiric shard":     "أونيريك شارد",
    "polychrome":        "بوليكروم",
    "credits":           "كريديت",
    "tokens":            "توكنات",
    "token":             "توكن",
    "stars":             "نجوم",
    "star":              "نجمة",
    "points":            "نقاط",
    "point":             "نقطة",
    "cp":                "كول بوينت",
    "call of duty points": "كول بوينت",
    "fc points":         "إف سي بوينت",
    "fifa points":       "فيفا بوينت",
    "shahid points":     "شاهد بوينت",
    "subscription":      "اشتراك",
    "monthly":           "شهري",
    "yearly":            "سنوي",
    "weekly":            "أسبوعي",
    "daily":             "يومي",
    "bonus":             "مكافأة",
    "pack":              "باقة",
    "package":           "باقة",
    "membership":        "عضوية",
    "vip":               "VIP",
    "level":             "مستوى",
    "season":            "موسم",
    "battle pass":       "باتل باس",
    "elite pass":        "إيليت باس",
    "royale pass":       "رويال باس",
    "rp":                "رويال باس",
    "month":             "شهر",
    "months":            "شهور",
    "year":              "سنة",
    "days":              "يوم",
    "day":               "يوم",
}

# ─── Normalizer ─────────────────────────────────────────────────────────────
_EMOJI_RE = re.compile(
    "["
    "\U0001F600-\U0001F64F"
    "\U0001F300-\U0001F5FF"
    "\U0001F680-\U0001F6FF"
    "\U0001F700-\U0001F77F"
    "\U0001F780-\U0001F7FF"
    "\U0001F800-\U0001F8FF"
    "\U0001F900-\U0001F9FF"
    "\U0001FA00-\U0001FA6F"
    "\U0001FA70-\U0001FAFF"
    "\U00002600-\U000026FF"
    "\U00002700-\U000027BF"
    "]+",
    flags=re.UNICODE,
)


def _normalize(name: str) -> str:
    """Lowercase, strip emojis & punctuation, collapse whitespace."""
    if not name:
        return ""
    out = _EMOJI_RE.sub("", name)
    out = out.lower()
    out = re.sub(r"[®©™]", "", out)
    out = re.sub(r"\s+", " ", out).strip()
    out = out.strip(" -–—|·•:.,()[]")
    return out


# ─── Public API ─────────────────────────────────────────────────────────────

def translate_game_name(name: str, lang: str) -> str:
    """
    Return the translated game name for the given language.
    If lang != 'ar' or no translation found, returns the original cleaned name.
    """
    if not name:
        return name or ""
    if lang != "ar":
        return name

    norm = _normalize(name)
    if not norm:
        return name

    # 1. Exact match
    if norm in _GAME_AR:
        return _GAME_AR[norm]

    # 2. Strip common platform suffixes and retry
    for suffix in (" mobile", " pc", " online", " global", " sea", " mena"):
        if norm.endswith(suffix):
            stripped = norm[: -len(suffix)].strip()
            if stripped in _GAME_AR:
                return _GAME_AR[stripped]

    # 3. Longest containing key (e.g. "PUBG Mobile Global" → "pubg mobile")
    best = None
    for key in _GAME_AR:
        if key in norm and (best is None or len(key) > len(best)):
            best = key
    if best:
        return _GAME_AR[best]

    # 4. Fallback to original
    return name


def translate_product_name(name: str, lang: str) -> str:
    """
    Translate game product names like "60 UC", "100 + 10 Diamonds",
    "1 Month Subscription", "Royale Pass Season 25".
    Numbers and emojis are preserved, only known keywords are translated.
    """
    if not name:
        return name or ""
    if lang != "ar":
        return name

    # Token-by-token replacement (case-insensitive, longest-match-first)
    sorted_keys = sorted(_PRODUCT_AR.keys(), key=len, reverse=True)
    out = name

    # Replace multi-word keys first (e.g. "battle pass" before "pass")
    for key in sorted_keys:
        if " " not in key:
            continue
        pattern = re.compile(r"(?<![\w])" + re.escape(key) + r"(?![\w])", re.IGNORECASE)
        out = pattern.sub(_PRODUCT_AR[key], out)

    # Replace single-word keys with word boundaries
    for key in sorted_keys:
        if " " in key:
            continue
        pattern = re.compile(r"\b" + re.escape(key) + r"\b", re.IGNORECASE)
        out = pattern.sub(_PRODUCT_AR[key], out)

    # If the input still contains a known game name, translate it too
    for game_en, game_ar in _GAME_AR.items():
        if len(game_en) < 4:
            continue
        pattern = re.compile(r"\b" + re.escape(game_en) + r"\b", re.IGNORECASE)
        out = pattern.sub(game_ar, out)

    return out
