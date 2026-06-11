"""
Smart Arabic translator for SMM service names.
Parses structured English service names and produces clean Arabic output.

Input pattern:  "📸 متابعين — 🟢 Instagram Followers | 30 Day Refill | Speed: 10-50K/Day | Max 1M"
Output (ar):    "متابعين انستقرام · حقيقيين · تعويض 30 يوم · سرعة 10-50K"
Output (en):    keeps original (cleaned)
"""
import re

# ─── Word-level translation dictionary ───────────────────────────────────────

_WORD_MAP = {
    # Platforms
    "instagram":    "انستقرام",
    "tiktok":       "تيكتوك",
    "youtube":      "يوتيوب",
    "telegram":     "تيليجرام",
    "twitter":      "تويتر",
    "x/twitter":    "تويتر",
    "facebook":     "فيسبوك",
    "threads":      "ثريدز",
    "whatsapp":     "واتس آب",
    "spotify":      "سبوتيفاي",
    "twitch":       "تويتش",
    "discord":      "ديسكورد",
    "snapchat":     "سناب شات",
    "pinterest":    "بنترست",
    "linkedin":     "لينكدإن",
    "soundcloud":   "ساوند كلاود",

    # Service types
    "followers":    "متابعين",
    "views":        "مشاهدات",
    "likes":        "إعجابات",
    "comments":     "تعليقات",
    "shares":       "مشاركات",
    "subscribers":  "مشتركين",
    "members":      "أعضاء",
    "reactions":    "تفاعلات",
    "saves":        "حفظ",
    "reach":        "وصول",
    "impressions":  "ظهور",
    "watch time":   "وقت مشاهدة",
    "watch hours":  "ساعات مشاهدة",
    "story views":  "مشاهدات ستوري",
    "live stream":  "بث مباشر",
    "live views":   "مشاهدات بث مباشر",
    "post shares":  "مشاركات منشور",
    "post views":   "مشاهدات منشور",
    "post likes":   "إعجابات منشور",
    "reel views":   "مشاهدات ريلز",
    "reels views":  "مشاهدات ريلز",
    "video views":  "مشاهدات فيديو",
    "tweet views":  "مشاهدات تغريدة",
    "tweet/video views": "مشاهدات تغريدة/فيديو",
    "profile visits": "زيارات بروفايل",
    "profile visit": "زيارات بروفايل",
    "split likes":  "إعجابات موزعة",
    "split views":  "مشاهدات موزعة",
    "split shares": "مشاركات موزعة",
    "split":        "موزع",
    "video/reels/tv views": "مشاهدات فيديو/ريلز",
    "reel views":   "مشاهدات ريلز",
    "reels views":  "مشاهدات ريلز",
    "live stream likes": "إعجابات بث مباشر",
    "live stream views": "مشاهدات بث مباشر",
    "auto likes":   "إعجابات تلقائية",
    "auto saves":   "حفظ تلقائي",
    "auto comments": "تعليقات تلقائية",
    "auto reach":   "وصول تلقائي",
    "auto views":   "مشاهدات تلقائية",
    "verified comments": "تعليقات موثقة",
    "verified comment": "تعليق موثق",
    "custom comments": "تعليقات مخصصة",
    "random comments": "تعليقات عشوائية",
    "post share":   "مشاركة منشور",
    "poll votes":   "أصوات استفتاء",
    "channel views": "مشاهدات قناة",
    "post views":   "مشاهدات منشور",
    "engagements":  "تفاعلات",
    "engagement":   "تفاعل",
    "service":      "",
    "fast service":  "سريع",
    "direct":       "مباشر",
    "comment":      "تعليق",
    "details":      "تفاصيل",

    # Quality
    "real":         "حقيقي",
    "hq":           "جودة عالية",
    "uhq":          "جودة فائقة",
    "shq":          "جودة ممتازة",
    "premium":      "مميز",
    "organic":      "طبيعي",
    "targeted":     "مستهدف",
    "random":       "عشوائي",
    "active":       "نشط",
    "female":       "إناث",
    "male":         "ذكور",
    "arab":         "عرب",
    "natural increase": "زيادة طبيعية",
    "high retention": "بقاء عالي",
    "low drop":     "نسبة انخفاض قليلة",
    "no drop":      "بدون انخفاض",
    "fast":         "سريع",
    "slow":         "بطيء",
    "stable":       "مستقر",
    "high quality": "جودة عالية",
    "ultra high quality": "جودة فائقة",
    "blue tick verified": "موثق بالعلامة الزرقاء",
    "influencer account": "حساب مؤثر",

    # Refill / Guarantee
    "lifetime guaranteed": "ضمان مدى الحياة",
    "lifetime guarantee":  "ضمان مدى الحياة",
    "30 day refill":       "تعويض 30 يوم",
    "60 day refill":       "تعويض 60 يوم",
    "90 day refill":       "تعويض 90 يوم",
    "365 day refill":      "تعويض سنة",
    "30 days refill":      "تعويض 30 يوم",
    "60 days refill":      "تعويض 60 يوم",
    "no refill":           "بدون تعويض",
    "refill":              "تعويض",
    "guaranteed":          "مضمون",
    "guarantee":           "ضمان",

    # Misc
    "instant start":  "بدء فوري",
    "new":            "جديد",
    "new!":           "جديد",
    "drip-feed":      "تغذية تدريجية",
    "drip feed":      "تغذية تدريجية",

    # Countries
    "united kingdom": "بريطانيا",
    "united states":  "أمريكا",
    "brazil":         "البرازيل",
    "mexico":         "المكسيك",
    "philippines":    "الفلبين",
    "indonesian":     "إندونيسي",
    "indonesia":      "إندونيسيا",
    "vietnam":        "فيتنام",
    "india":          "الهند",
    "turkey":         "تركيا",
    "russia":         "روسيا",
    "germany":        "ألمانيا",
    "france":         "فرنسا",
    "spain":          "إسبانيا",
    "italy":          "إيطاليا",
    "japan":          "اليابان",
    "korea":          "كوريا",
    "china":          "الصين",
    "worldwide":      "عالمي",
    "global":         "عالمي",
}

# ─── Junk patterns to strip entirely ─────────────────────────────────────────

_STRIP_PATTERNS = [
    r"Speed:?\s*[\d.,]+[-–]?[\d.,]*[KMkm]?/Day",   # Speed: 10-50K/Day
    r"Max\s*[\d.,]+[KMBkmb]?",                       # Max 1M
    r"[\d.,]+[-–][\d.,]*[KMkm]/Day",                 # 10-100K/Day standalone
    r"⌊",
    r"⌉",
    r"Flag Must Be Disabl\w*",
    r"Provided By \w+!?",
    r"Enter Username",
    r"All Links",
    r"\d+ Posts?$",
    r"Latest \d+ Videos?",
    r"Latest \d+ Posts?",
    r"\d+ Comments?(?=\s*$|\s*\|)",
    r"Dri\w*$",                                       # Truncated "Drip-feed"
    r"Drip-?Fee\w*",                                    # "Drip-Feed" / "Drip-Fee"
    r"Instant St\w*$",                                  # Truncated "Instant Start"
    r"NEW!?$",
]

_STRIP_RE = [re.compile(p, re.IGNORECASE) for p in _STRIP_PATTERNS]


# ─── Main translation function ───────────────────────────────────────────────

def translate_service_name(raw_name: str, lang: str) -> str:
    """
    Translate a service name intelligently.
    For English: clean up junk, return readable name.
    For Arabic: full smart translation.
    """
    if lang != "ar":
        return _clean_en(raw_name)
    return _translate_ar(raw_name)


def _clean_en(name: str) -> str:
    """Clean English name — remove Arabic prefix and junk."""
    # Remove Arabic prefix pattern: "📸 متابعين — "
    name = re.sub(r'^[\U0001F000-\U0001FFFF\s]*[\u0600-\u06FF\s]+[—–\-]+\s*', '', name)
    # Remove color circles
    name = re.sub(r'[🟡🟢🔵🔴⚪⚫]\s*', '', name)
    # Remove flag emojis but keep the rest
    name = re.sub(r'[\U0001F1E0-\U0001F1FF]{2}\s*', '', name)
    # Clean pipes and extra spaces
    name = name.strip().strip('|').strip()
    # Remove junk patterns
    for rx in _STRIP_RE:
        name = rx.sub('', name)
    # Clean leftover pipes and whitespace
    name = re.sub(r'\|\s*\|', '|', name)
    name = re.sub(r'\|\s*\|', '|', name)  # second pass
    name = re.sub(r'\|\s*$', '', name)
    name = re.sub(r'^\s*\|', '', name)
    name = re.sub(r'\s{2,}', ' ', name).strip().strip('|').strip()
    # Remove trailing junk from truncated DB fields
    name = re.sub(r'\s*\|\s*$', '', name)
    return name if name else "Service"


def _translate_ar(name: str) -> str:
    """Smart Arabic translation of service name."""
    # Step 1: Extract the English part (after — or after color circle)
    en_part = name
    # Remove Arabic prefix: "📸 متابعين — "
    en_part = re.sub(r'^[\U0001F000-\U0001FFFF\s]*[\u0600-\u06FF\s]+[—–\-]+\s*', '', en_part)
    # Remove color circles
    en_part = re.sub(r'[🟡🟢🔵🔴⚪⚫]\s*', '', en_part)

    if not en_part.strip():
        # No English part — return original cleaned
        return re.sub(r'[🟡🟢🔵🔴⚪⚫]', '', name).strip()

    # Step 2: Split by pipe
    segments = [s.strip() for s in en_part.split('|') if s.strip()]

    if not segments:
        return name.strip()

    # Step 3: Translate each segment
    translated = []
    for seg in segments:
        t = _translate_segment(seg)
        if t:
            translated.append(t)

    if not translated:
        return name.strip()

    # Step 4: Join with clean separator
    return " · ".join(translated)


def _translate_segment(seg: str) -> str | None:
    """Translate a single pipe-separated segment."""
    seg = seg.strip()
    if not seg:
        return None

    # Remove flag emojis
    seg_clean = re.sub(r'[\U0001F1E0-\U0001F1FF]{2}\s*', '', seg).strip()

    # Check if it's a junk pattern to skip
    for rx in _STRIP_RE:
        if rx.fullmatch(seg_clean):
            return None
        # Also check if the whole segment is mostly junk
        cleaned = rx.sub('', seg_clean).strip()
        if not cleaned or len(cleaned) < 3:
            return None

    seg_lower = seg_clean.lower().strip()

    # Try longest-match first from dictionary
    result = _match_and_translate(seg_lower)
    if result:
        return result

    # If segment is very short and untranslatable, skip it
    if len(seg_clean) < 3:
        return None

    # Strip junk from segment and try again
    for rx in _STRIP_RE:
        seg_clean = rx.sub('', seg_clean).strip()

    seg_lower = seg_clean.lower().strip()
    if not seg_lower:
        return None

    result = _match_and_translate(seg_lower)
    if result:
        return result

    # Can't translate — return cleaned original
    return seg_clean if len(seg_clean) > 2 else None


def _match_and_translate(text: str) -> str | None:
    """Try to translate text using word map, longest match first."""
    text = text.strip().rstrip('!').strip()

    # Direct full match
    if text in _WORD_MAP:
        return _WORD_MAP[text]

    # Try to decompose into known parts
    # Sort keys by length (longest first) for greedy matching
    remaining = text
    parts = []
    matched_any = False

    # Sorted keys longest first
    sorted_keys = sorted(_WORD_MAP.keys(), key=len, reverse=True)

    while remaining.strip():
        found = False
        for key in sorted_keys:
            if remaining.lower().startswith(key):
                parts.append(_WORD_MAP[key])
                remaining = remaining[len(key):].strip().lstrip('|').lstrip('-').lstrip('–').strip()
                matched_any = True
                found = True
                break

        if not found:
            # Take next word and keep as-is or skip
            words = remaining.split(None, 1)
            if words:
                w = words[0].lower().strip('|').strip()
                if w in _WORD_MAP:
                    parts.append(_WORD_MAP[w])
                    matched_any = True
                elif len(w) > 2 and not w.isdigit():
                    # Keep unrecognized words only if they look meaningful
                    parts.append(words[0].strip('|').strip())
                remaining = words[1] if len(words) > 1 else ""
            else:
                break

    if matched_any and parts:
        return " ".join(parts)

    return None


# ─── High-level name formatter ───────────────────────────────────────────────

def format_service_name(raw_name: str, lang: str, max_len: int = 0) -> str:
    """
    Main entry point: returns a clean, translated service name.
    If max_len > 0, truncates with ellipsis.
    """
    result = translate_service_name(raw_name, lang)

    # Final cleanup
    result = result.strip()
    while "  " in result:
        result = result.replace("  ", " ")
    result = re.sub(r'\s*·\s*·\s*', ' · ', result)  # no double dots
    result = result.strip(' ·').strip()

    if max_len > 0 and len(result) > max_len:
        result = result[:max_len - 1].rsplit(" ", 1)[0] + "…"

    return result


def short_service_label(raw_name: str, lang: str = "ar") -> str:
    """
    Generate a SHORT button label for the service list.
    Must fit in a Telegram inline button (~35 chars for Arabic).

    Extracts from Arabic/English names:
    - Service type (أعضاء, متابعين, مشاهدات...)
    - Key quality (جودة عالية, بريميوم, عربي...)
    - Guarantee (ضمان 7 يوم, مدى الحياة, بدون ضمان...)
    - Target (جروب, قناة, هندي...)

    Examples:
        "💬 أعضاء تيليجرام | ضمان 7 يوم | 0-1 ساعة"
        → "أعضاء · ضمان 7 يوم"

        "💬 أعضاء تليجرام عربي | بدون نقصان | جودة عالية | ضمان مدى الحياة"
        → "أعضاء عربي · جودة عالية · ♻️دائم"

        "💬 أعضاء جروب تيليجرام | بدون ضمان"
        → "أعضاء جروب · بدون ضمان"
    """
    name = raw_name

    # ── 1. Remove emoji prefix and platform name ──
    # Strip leading emojis
    name = re.sub(r'^[\U0001F000-\U0001FFFF\s🟡🟢🔵🔴⚪⚫📸💬🎬💙🤖🏆🎮]+', '', name).strip()
    # Remove platform names (they're redundant - user already chose the platform)
    for plat in ['تيليجرام', 'تليجرام', 'انستقرام', 'انستا', 'يوتيوب', 'تويتر',
                 'فيسبوك', 'تيكتوك', 'واتس', 'سناب', 'ثريدز', 'سبوتيفاي',
                 'telegram', 'instagram', 'youtube', 'twitter', 'facebook',
                 'tiktok', 'whatsapp', 'snapchat', 'threads', 'spotify',
                 'twitch', 'discord', 'pinterest', 'linkedin', 'soundcloud']:
        name = re.sub(rf'\b{plat}\b', '', name, flags=re.IGNORECASE)

    # ── 2. Split by pipe separator ──
    segments = [s.strip().strip('|').strip() for s in re.split(r'[|]', name) if s.strip().strip('|').strip()]

    if not segments:
        return "خدمة" if lang == "ar" else "Service"

    # ── 3. Classify each segment ──
    svc_type = ""
    qualifiers = []  # quality, target audience, etc.
    guarantee = ""

    # Junk patterns to skip entirely
    _junk_re = re.compile(
        r'(0-\d+\s*ساع|فوري|instant|speed|ألف/يوم|الف/يوم|حد أقصى|'
        r'max\s*\d|start|بدء|\d+[KMkm]/[Dd]ay|\d+ ألف/يوم|بيانات تطبيق|'
        r'\d+ ألف$|حد أدنى)',
        re.IGNORECASE
    )

    # Type detection (first segment usually has the type)
    _type_keywords = {
        'أعضاء': 'أعضاء', 'اعضاء': 'أعضاء', 'عضو': 'أعضاء',
        'متابعين': 'متابعين', 'متابع': 'متابعين',
        'مشاهدات': 'مشاهدات', 'مشاهدة': 'مشاهدات',
        'إعجابات': 'إعجابات', 'اعجابات': 'إعجابات', 'لايكات': 'إعجابات', 'لايك': 'إعجابات',
        'تعليقات': 'تعليقات', 'تعليق': 'تعليقات',
        'تفاعلات': 'تفاعلات', 'تفاعل': 'تفاعلات', 'رياكشن': 'تفاعلات',
        'مشاركات': 'مشاركات', 'مشاركة': 'مشاركات',
        'ستوري': 'ستوري', 'قصص': 'ستوري',
        'تصويت': 'تصويت', 'استفتاء': 'تصويت',
        'تشغيل بوت': 'تشغيل بوت',
        'ريلز': 'ريلز', 'reel': 'ريلز',
        'مشتركين': 'مشتركين', 'مشترك': 'مشتركين',
        'followers': 'متابعين', 'follower': 'متابعين',
        'members': 'أعضاء', 'member': 'أعضاء',
        'views': 'مشاهدات', 'view': 'مشاهدات',
        'likes': 'إعجابات', 'like': 'إعجابات',
        'comments': 'تعليقات', 'comment': 'تعليقات',
        'reactions': 'تفاعلات', 'reaction': 'تفاعلات',
        'shares': 'مشاركات', 'share': 'مشاركات',
        'subscribers': 'مشتركين', 'subscriber': 'مشتركين',
        'poll': 'تصويت', 'votes': 'تصويت',
    }

    for seg in segments:
        seg_lower = seg.lower().strip()
        seg_clean = seg.strip()

        # Skip junk segments (speed, time, max, etc.)
        if _junk_re.search(seg_lower):
            # But check if it also has useful info before skipping
            if not any(k in seg_lower for k in ['ضمان', 'جودة', 'عربي', 'بريميوم', 'premium']):
                continue

        # Detect service type from first meaningful segment
        if not svc_type:
            for keyword, type_label in _type_keywords.items():
                if keyword in seg_lower:
                    svc_type = type_label
                    # Check if segment has extra info beyond the type
                    # e.g. "أعضاء جروب" or "أعضاء بريميوم"
                    extras = seg_clean
                    for rm in [svc_type, 'اعضاء', 'أعضاء', 'متابعين', 'مشاهدات',
                               'إعجابات', 'تعليقات', 'تفاعلات', 'مشاركات',
                               'تشغيل بوت', 'تصويت', 'مشتركين', 'ستوري']:
                        extras = extras.replace(rm, '')
                    extras = extras.strip()
                    if extras and len(extras) > 1:
                        # Has qualifier like "جروب" or "بريميوم"
                        qualifiers.append(extras)
                    break
            if svc_type:
                continue

        # Detect guarantee
        if not guarantee:
            if 'ضمان مدى الحياة' in seg_lower or 'lifetime' in seg_lower:
                guarantee = "♻️دائم"
                continue
            m = re.search(r'(\d+)\s*(يوم|أيام|ايام|يوما|days?)\s*ضمان', seg_lower)
            if m:
                guarantee = f"♻️{m.group(1)}ي"
                continue
            m = re.search(r'ضمان\s*(\d+)\s*(يوم|أيام|ايام|يوما|days?)', seg_lower)
            if m:
                guarantee = f"♻️{m.group(1)}ي"
                continue
            m = re.search(r'(\d+)\s*days?\s*refill', seg_lower)
            if m:
                guarantee = f"♻️{m.group(1)}ي"
                continue
            if 'بدون ضمان' in seg_lower or 'no refill' in seg_lower or 'بدون تعويض' in seg_lower:
                guarantee = "بدون ضمان"
                continue
            if 'lifetime' in seg_lower:
                guarantee = "♻️دائم"
                continue

        # Detect quality/target qualifiers
        if 'جودة عالية' in seg_lower or 'high quality' in seg_lower or 'hq' == seg_lower.strip():
            qualifiers.append("جودة عالية")
            continue
        if 'بريميوم' in seg_lower or 'premium' in seg_lower:
            qualifiers.append("بريميوم 🏆")
            continue
        if 'عربي' in seg_lower or 'arab' in seg_lower:
            qualifiers.append("عربي")
            continue
        if 'هندي' in seg_lower or 'india' in seg_lower:
            qualifiers.append("هندي")
            continue
        if 'تركي' in seg_lower or 'turkey' in seg_lower or 'تركيا' in seg_lower:
            qualifiers.append("تركي")
            continue
        if 'بدون نقصان' in seg_lower or 'بدون نقص' in seg_lower or 'no drop' in seg_lower:
            qualifiers.append("ثابت ✅")
            continue
        if 'حقيقي' in seg_lower or 'real' in seg_lower:
            qualifiers.append("حقيقي ✅")
            continue
        if 'نشط' in seg_lower or 'active' in seg_lower:
            qualifiers.append("نشط")
            continue
        if 'سريع' in seg_lower or 'fast' in seg_lower:
            qualifiers.append("سريع 🚀")
            continue
        if 'عشوائي' in seg_lower or 'random' in seg_lower:
            qualifiers.append("عشوائي")
            continue
        if 'جروب' in seg_lower or 'group' in seg_lower or 'مجموعة' in seg_lower:
            qualifiers.insert(0, "جروب")
            continue
        if 'قناة' in seg_lower or 'channel' in seg_lower:
            qualifiers.insert(0, "قناة")
            continue
        if 'قناة/جروب' in seg_lower:
            qualifiers.insert(0, "قناة/جروب")
            continue
        if '+ مشاهدات' in seg_lower or '+مشاهدات' in seg_lower:
            qualifiers.append("+مشاهدات")
            continue

    # ── 4. Build label ──
    if not svc_type:
        # Fallback: use first segment cleaned
        svc_type = segments[0][:15] if segments else "خدمة"

    parts = [svc_type]
    # Add max 2 qualifiers to keep it short
    for q in qualifiers[:2]:
        parts.append(q)
    if guarantee:
        parts.append(guarantee)

    label = " · ".join(parts)

    # Truncate if too long
    if len(label) > 38:
        label = label[:37] + "…"

    return label
