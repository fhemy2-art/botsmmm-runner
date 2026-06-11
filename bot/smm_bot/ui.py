"""
🔷 𝑲𝒊𝒓𝒂 · NEXUS — Crystal Prism UI v6 🔷
⟡  Plain HTML · RTL/LTR Fields · No pre · Copyable  ⟡

التنسيق:
  عربي   →  icon  اسم الحقل  •  `قيمة`
            (Telegram يعرض الـ RTL من اليمين فيبدو الرمز على اليمين)
  إنجليزي → icon  field name  •  `value`  (LTR طبيعي)
"""

# ══════════════════════════════════════════════════════════════════════════════
#  ⬥  SEPARATORS & GLYPHS
# ══════════════════════════════════════════════════════════════════════════════

SEP   = "┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄"
SEP2  = "━━━━━━━━━━━━━━━━━━━"
SEP3  = "· · · · · · · · · ·"
BLANK = ""

# ══════════════════════════════════════════════════════════════════════════════
#  ⬥  HEADERS & LOGOS
# ══════════════════════════════════════════════════════════════════════════════

def logo(name: str = "𝑲𝒊𝒓𝒂 · كيرا") -> str:
    return f"\n<i>⟡  {name}  ⟡\n✦  NEXUS SMM PANEL  ✦</i>"

def logo_en(name: str = "𝑲𝒊𝒓𝒂 · Kira") -> str:
    return f"\n<i>⟡  {name}  ⟡\n✦  NEXUS SMM PANEL  ✦</i>"

def header(title: str, sub: str = "") -> str:
    h = f"🔷  <b>{title}</b>  🔷"
    if sub:
        h += f"\n<i>⟡  {sub}  ⟡</i>"
    return h

def section(title: str) -> str:
    return f"\n  <b>◈ {title} ◈</b>\n{SEP}"

def section_en(title: str) -> str:
    return f"\n  <b>◈ {title} ◈</b>\n{SEP}"

# ══════════════════════════════════════════════════════════════════════════════
#  ⬥  FIELD ROWS
#
#  عربي   →  icon  اسم الحقل  •  `قيمة`
#  إنجليزي → icon  field name  •  `value`
#
#  كلاهما بنفس بنية الكود — Telegram يعكس العربي تلقائياً (RTL)
# ══════════════════════════════════════════════════════════════════════════════

def field_ar(icon: str, name: str, value) -> str:
    """حقل عربي — الرمز + الاسم + • + القيمة في mono"""
    return f"{icon}  {name}  •  <code>{value}</code>"

def field_en(icon: str, name: str, value) -> str:
    """حقل إنجليزي — icon + name + • + value في mono"""
    return f"{icon}  {name}  •  <code>{value}</code>"

# ══════════════════════════════════════════════════════════════════════════════
#  ⬥  INTERNAL ROW PROCESSOR
# ══════════════════════════════════════════════════════════════════════════════

def _proc(rows: list) -> str:
    out = []
    for r in rows:
        if r is None or r == "":
            out.append("")
        elif r == "---":
            out.append(SEP2)
        elif r == "···":
            out.append(SEP)
        elif r == "...":
            out.append(SEP3)
        else:
            out.append(r)
    return "\n".join(out)

# ══════════════════════════════════════════════════════════════════════════════
#  ⬥  CARD BUILDERS
# ══════════════════════════════════════════════════════════════════════════════

def card(title: str, rows: list, *, lang: str = "ar",
         with_logo: bool = False, bot_name: str = "𝑲𝒊𝒓𝒂 · كيرا") -> str:
    lines = [header(title), ""]
    lines.append(_proc(rows))
    if with_logo:
        lines.append(logo(bot_name) if lang == "ar" else logo_en(bot_name))
    return "\n".join(lines)


def diamond_card(title: str, rows: list, *, sub: str = "",
                 lang: str = "ar", with_logo: bool = True,
                 bot_name: str = "𝑲𝒊𝒓𝒂 · كيرا") -> str:
    lines = [header(title, sub), ""]
    lines.append(_proc(rows))
    if with_logo:
        lines.append(logo(bot_name) if lang == "ar" else logo_en(bot_name))
    return "\n".join(lines)


def elite_card(title: str, rows: list, *, lang: str = "ar",
               with_logo: bool = False, bot_name: str = "𝑲𝒊𝒓𝒂 · كيرا") -> str:
    h = f"⚡  <b>{title}</b>  ⚡"
    lines = [h, ""]
    lines.append(_proc(rows))
    if with_logo:
        lines.append(logo(bot_name) if lang == "ar" else logo_en(bot_name))
    return "\n".join(lines)


def section_card(emoji: str, title: str, rows: list, *, lang: str = "ar",
                 with_logo: bool = False, bot_name: str = "𝑲𝒊𝒓𝒂 · كيرا") -> str:
    h = f"✦  {emoji}  <b>{title}</b>  ✦"
    lines = [h, ""]
    lines.append(_proc(rows))
    if with_logo:
        lines.append(logo(bot_name) if lang == "ar" else logo_en(bot_name))
    return "\n".join(lines)


def premium_card(title: str, rows: list, footer: str = None, *,
                 lang: str = "ar", bot_name: str = "𝑲𝒊𝒓𝒂 · كيرا") -> str:
    lines = [header(title), ""]
    lines.append(_proc(rows))
    if footer:
        lines.append(f"\n<i>{footer}</i>")
    else:
        lines.append(logo(bot_name) if lang == "ar" else logo_en(bot_name))
    return "\n".join(lines)


def phantom_card(title: str, rows: list) -> str:
    lines = [f"◇  <b>{title}</b>  ◇", ""]
    lines.append(_proc(rows))
    return "\n".join(lines)


# ══════════════════════════════════════════════════════════════════════════════
#  ⬥  FIELD CARD  —  بطاقات الحقول الكاملة
# ══════════════════════════════════════════════════════════════════════════════

def field_card_ar(title: str, fields: list, *, sub: str = "",
                  with_logo: bool = False, bot_name: str = "𝑲𝒊𝒓𝒂 · كيرا") -> str:
    lines = [header(title, sub), ""]
    for item in fields:
        if item is None or item == "":
            lines.append("")
        elif item == "---":
            lines.append(SEP2)
        elif item == "···":
            lines.append(SEP)
        elif isinstance(item, tuple) and len(item) == 3:
            lines.append(field_ar(*item))
        elif isinstance(item, str) and item.startswith("§"):
            lines.append(section(item[1:]))
        else:
            lines.append(str(item))
    if with_logo:
        lines.append(logo(bot_name))
    return "\n".join(lines)


def field_card_en(title: str, fields: list, *, sub: str = "",
                  with_logo: bool = False, bot_name: str = "𝑲𝒊𝒓𝒂 · Kira") -> str:
    lines = [header(title, sub), ""]
    for item in fields:
        if item is None or item == "":
            lines.append("")
        elif item == "---":
            lines.append(SEP2)
        elif item == "···":
            lines.append(SEP)
        elif isinstance(item, tuple) and len(item) == 3:
            lines.append(field_en(*item))
        elif isinstance(item, str) and item.startswith("§"):
            lines.append(section_en(item[1:]))
        else:
            lines.append(str(item))
    if with_logo:
        lines.append(logo_en(bot_name))
    return "\n".join(lines)


# ══════════════════════════════════════════════════════════════════════════════
#  ⬥  OPEN / CLOSE SECTION
# ══════════════════════════════════════════════════════════════════════════════

def open_section(label: str = "") -> str:
    return f"\n  <b>◈ {label} ◈</b>\n{SEP}" if label else f"\n{SEP}"

def close_section(label: str = "") -> str:
    return SEP

# ══════════════════════════════════════════════════════════════════════════════
#  ⬥  UTILITIES
# ══════════════════════════════════════════════════════════════════════════════

def mini_card(title: str, value: str) -> str:
    return f"◇ <b>{title}</b>\n⟡ {value}"

def stats_row(label: str, value, emoji: str = "◆") -> str:
    return f"{emoji}  {label}  •  <b>{value}</b>"

def divider(style: str = "single") -> str:
    return {"double": SEP2, "single": SEP, "dotted": SEP3}.get(style, SEP)

def badge(text: str, style: str = "normal") -> str:
    icons = {"success": "✅", "error": "❌", "warning": "⚠️",
             "vip": "👑", "info": "🔷", "new": "✦"}
    return f"{icons.get(style, '◈')}  <b>{text}</b>"

def status_emoji(status: str) -> str:
    return {
        "pending": "⏳", "processing": "🔄", "in progress": "🔄",
        "completed": "✅", "partial": "⚠️", "canceled": "❌", "refunded": "↩️",
    }.get((status or "").lower(), "❓")

def status_label_ar(status: str) -> str:
    return {
        "pending":     "⏳ قيد الانتظار",
        "processing":  "🔄 قيد التنفيذ",
        "in progress": "🔄 قيد التنفيذ",
        "completed":   "✅ مكتمل",
        "partial":     "⚠️ مكتمل جزئياً",
        "canceled":    "❌ ملغي",
        "refunded":    "↩️ مسترد",
    }.get((status or "").lower(), f"❓ {status}")

def status_label_en(status: str) -> str:
    return {
        "pending":     "⏳ Pending",
        "processing":  "🔄 Processing",
        "in progress": "🔄 In Progress",
        "completed":   "✅ Completed",
        "partial":     "⚠️ Partial",
        "canceled":    "❌ Canceled",
        "refunded":    "↩️ Refunded",
    }.get((status or "").lower(), f"❓ {status}")

NUM = ["①","②","③","④","⑤","⑥","⑦","⑧","⑨","⑩",
       "⑪","⑫","⑬","⑭","⑮","⑯","⑰","⑱","⑲","⑳"]

def num(i: int) -> str:
    return NUM[i] if 0 <= i < len(NUM) else f"{i + 1}."

def bar(value: float, total: float, width: int = 10) -> str:
    if total <= 0: return "□" * width
    filled = min(int(round(value / total * width)), width)
    return "■" * filled + "□" * (width - filled)

def fmt_price(usd: float) -> str:
    if usd < 0.01: return f"${usd:.6f}"
    if usd < 1:    return f"${usd:.4f}"
    return f"${usd:.2f}"

def fmt_num(n: int | float) -> str:
    return f"{int(n):,}"

# ══════════════════════════════════════════════════════════════════════════════
#  ⬥  ACCOUNT EMAIL GENERATOR
# ══════════════════════════════════════════════════════════════════════════════

def account_to_email(account_number) -> str:
    """
    يحوّل رقم الحساب إلى بريد إلكتروني بأسلوب كيرا.
    مثال: 1042  →  kira01042@kira-smm.com
    """
    num_str = str(account_number).zfill(5)
    return f"kira{num_str}@kira-smm.com"
