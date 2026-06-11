"""
🔷 𝑲𝒊𝒓𝒂 · NEXUS — Crystal Prism Strings v6 🔷
⟡  Plain HTML · RTL/LTR · Arabic & English  ⟡

تنسيق الحقل:
  icon  اسم الحقل  •  `قيمة`    ← عربي (RTL يعكسه تلقائياً في تيليجرام)
  icon  field name  •  `value`  ← إنجليزي LTR
"""

KIRA = "𝑲𝒊𝒓𝒂 | كيرا"

_SEP  = "┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄"
_SEP2 = "━━━━━━━━━━━━━━━━━━━"

def _fa(icon, name, val):
    """حقل عربي: icon  اسم  •  `قيمة`"""
    return f"{icon}  {name}  •  <code>{val}</code>"

def _fe(icon, name, val):
    """حقل إنجليزي: icon  name  •  `value`"""
    return f"{icon}  {name}  •  <code>{val}</code>"

def _sec(title):
    return f"\n  <b>◈ {title} ◈</b>\n{_SEP}"


# ══════════════════════════════════════════════════════════════════════════════
#  ⬥  ARABIC
# ══════════════════════════════════════════════════════════════════════════════

_AR = {

    "welcome": (
        "🔷  <b>𝑲𝒊𝒓𝒂 · كيـرا</b>  🔷\n"
        "<i>⟡  مركز التسويق الرقمي المتميز  ⟡</i>\n"
        "\n"
        + _sec("لماذا نحن؟") + "\n"
        "\n"
        "①  تنفيذ آني  •  <code>خلال دقائق ✅</code>\n"
        "②  جودة مضمونة  •  <code>100% ✅</code>\n"
        "③  ضمان الإعادة  •  <code>مجاناً 🔄</code>\n"
        "④  دعم VIP  •  <code>24/7 👑</code>\n"
        "\n"
        + _sec("منصاتنا") + "\n"
        "\n"
        "🤖  Telegram  ✦  📸  Instagram\n"
        "🎬  YouTube   ✦  🎵  TikTok\n"
        "💙  Twitter X  ✦  👥  Facebook\n"
        "\n"
        "<i>⟡  𝑲𝒊𝒓𝒂 · كيرا  ⟡\n"
        "✦  NEXUS SMM PANEL  ✦</i>"
    ),

    "start_btn":        "🔷 انطلق وابدأ الآن 🔷",
    "support_btn":      "⟡ تواصل مع الدعم ⟡",
    "instructions_btn": "◈ دليل وشروط الاستخدام",
    "channel_btn":      "✦ قناتنا الرسمية ↗",
    "new_order":        "⚡ اطلب تعزيزك الرقمي الآن ⚡",
    "free_balance":     "🎁 احصل على مكافأة مجانية",
    "recharge":         "💎 اشحن رصيدك الآن",
    "transfer_balance": "💸 أرسل رصيدك لآخر",
    "lang_switch":      "🌐 Switch to English",
    "my_stats":         "📊 ملفي الإحصائي",
    "my_orders":        "📦 سجل طلباتي الكاملة",
    "settings":         "⚙️ ضبط الحساب",
    "support":          "🎧 تواصل مع الدعم",
    "bot_channel":      "📢 القناة الرسمية",
    "act_channel":      "⚡ قناة التفعيلات",
    "disclaimer_btn":   "📋 الشروط والسياسات",
    "admin_btn":        "🔐 لوحة التحكم الإدارية",
    "vip_btn":          "👑 عضوية VIP الذهبية",
    "back":             "◀ رجوع",
    "main_menu":        "⌂ الرئيسية",

    # ── الواجهة الرئيسية ─────────────────────────────────────────────────────
    "menu_text": (
        "╔═══════════════════╗\n"
        "║  ✦ 𝑲𝒊𝒓𝒂 · <b>NEXUS SMM</b> ✦  ║\n"
        "╚═══════════════════╝\n"
        "\n"
        "👤  الاسم  ‣  <b>{username}</b>\n"
        "🆔  المعرّف  ‣  <code>{uid}</code>\n"
        "📧  الحساب  ‣  <code>{account_email}</code>\n"
        "\n"
        "💰  الرصيد  ‣  <b><code>{balance}</code></b>\n"
        "📊  المصروف  ‣  <code>{spent}</code>\n"
        "🏅  المستوى  ‣  <code>{tier}</code>\n"
        "💱  العملة  ‣  <code>{currency_name}</code>\n"
        "{vip_line}"
        "\n"
        "✦ ─── <i>NEXUS SMM · كيرا</i> ─── ✦"
    ),

    "vip_line": "👑  VIP 🎁  ‣  <code>{pct}% خصم</code>\n",

    "instructions": (
        "🔷  <b>دليل الاستخدام</b>  🔷\n"
        "\n"
        + _sec("خطوات الطلب") + "\n"
        "\n"
        "①  اضغط زر الطلب من القائمة\n"
        "②  اختر المنصة المطلوبة\n"
        "③  اختر نوع الخدمة\n"
        "④  راجع التفاصيل والسعر\n"
        "⑤  أرسل رابط حسابك\n"
        "⑥  حدد الكمية وأكد الطلب\n"
        "\n"
        + _SEP2 + "\n"
        "⚡  <b>التنفيذ تلقائي وآني</b>\n"
        "📌  للتسويق الرقمي فقط\n"
        "\n"
        "<i>⟡  𝑲𝒊𝒓𝒂 · كيرا  ⟡\n"
        "✦  NEXUS SMM PANEL  ✦</i>"
    ),

    "disclaimer": (
        "🔷  <b>الشروط والسياسات</b>  🔷\n"
        "\n"
        + _sec("السياسات الأساسية") + "\n"
        "\n"
        "✅  خدمات تسويق رقمي فقط\n"
        "⚠️  لا ضمان لبقاء المتابعين\n"
        "📋  الأسعار قابلة للتغيير\n"
        "🚫  لا مسؤولية على الحظر\n"
        "\n"
        + _SEP2 + "\n"
        "<b>الاستخدام = القبول الكامل</b>\n"
        "\n"
        "<i>⟡  𝑲𝒊𝒓𝒂 · كيرا  ⟡\n"
        "✦  NEXUS SMM PANEL  ✦</i>"
    ),

    "vip_info": (
        "🔷  <b>نظام العضويات VIP</b>  🔷\n"
        "\n"
        + _sec("مستويات الخصم") + "\n"
        "\n"
        + _fa("⚪", "عادي",    "بدون خصم") + "\n"
        + _fa("🥈", "فضي",    "10$+  ›  3%") + "\n"
        + _fa("🥇", "ذهبي",   "50$+  ›  7%") + "\n"
        + _fa("💎", "بلاتيني", "200$+  ›  12%") + "\n"
        "\n"
        + _sec("مستواك الحالي") + "\n"
        "\n"
        + _fa("🏆", "مستواك", "{tier}") + "\n"
        + _fa("🎁", "خصمك",  "{pct}%") + "\n"
        "\n"
        "<i>⟡  𝑲𝒊𝒓𝒂 · كيرا  ⟡\n"
        "✦  NEXUS SMM PANEL  ✦</i>"
    ),

    "lang_changed":  "🇸🇦  تم التبديل إلى <b>العربية</b>",
    "rate_service":  "⭐  كيف تقيّم جودة الخدمة؟",
    "rate_1": "😞 ضعيف جداً", "rate_2": "😐 ضعيف",
    "rate_3": "🙂 متوسط",     "rate_4": "😊 جيد جداً",
    "rate_5": "🤩 ممتاز!",
    "skip_review":   "⏭ تخطي التقييم",
    "review_thanks": "✅  شكراً على تقييمك",
    "review_prompt": "🎉  طلبك <b>#{order_id}</b> اكتمل!\n⭐  كيف كانت الخدمة؟",
    "currency_usd":  "🇺🇸  الدولار الأمريكي · USD",
    "currency_yer":  "🇾🇪  الريال اليمني · YER",
    "currency_sar":  "🇸🇦  الريال السعودي · SAR",
    "currency_changed": "✅  تم تغيير العملة  ›  <b>{cur}</b>",
}


# ══════════════════════════════════════════════════════════════════════════════
#  ⬥  ENGLISH
# ══════════════════════════════════════════════════════════════════════════════

_EN = {

    "welcome": (
        "🔷  <b>𝑲𝒊𝒓𝒂 · Kira</b>  🔷\n"
        "<i>⟡  Premium Digital Growth Hub  ⟡</i>\n"
        "\n"
        + _sec("Why Choose Us?") + "\n"
        "\n"
        "①  Instant delivery  •  <code>minutes ✅</code>\n"
        "②  Guaranteed quality  •  <code>100% ✅</code>\n"
        "③  Free refill  •  <code>free 🔄</code>\n"
        "④  VIP support  •  <code>24/7 👑</code>\n"
        "\n"
        + _sec("Our Platforms") + "\n"
        "\n"
        "🤖  Telegram  ✦  📸  Instagram\n"
        "🎬  YouTube   ✦  🎵  TikTok\n"
        "💙  Twitter X  ✦  👥  Facebook\n"
        "\n"
        "<i>⟡  𝑲𝒊𝒓𝒂 · Kira  ⟡\n"
        "✦  NEXUS SMM PANEL  ✦</i>"
    ),

    "start_btn":        "🔷 Launch Now 🔷",
    "support_btn":      "⟡ Contact Support ⟡",
    "instructions_btn": "◈ Usage Guide & Terms",
    "channel_btn":      "✦ Official Channel ↗",
    "new_order":        "⚡ Place Boost Order Now ⚡",
    "free_balance":     "🎁 Claim Free Bonus",
    "recharge":         "💎 Add Funds to Account",
    "transfer_balance": "💸 Send Balance to User",
    "lang_switch":      "🌐 التبديل للعربية",
    "my_stats":         "📊 My Statistics",
    "my_orders":        "📦 My Orders History",
    "settings":         "⚙️ Account Settings",
    "support":          "🎧 Contact Support",
    "bot_channel":      "📢 Official Channel",
    "act_channel":      "⚡ Activations",
    "disclaimer_btn":   "📋 Terms & Policies",
    "admin_btn":        "🔐 Admin Control Panel",
    "vip_btn":          "👑 VIP Gold Membership",
    "back":             "◀ Back",
    "main_menu":        "⌂ Home",

    # ── Main Menu Screen ───────────────────────────────────────────────────
    "menu_text": (
        "╔═══════════════════╗\n"
        "║  ✦ 𝑲𝒊𝒓𝒂 · <b>NEXUS SMM</b> ✦  ║\n"
        "╚═══════════════════╝\n"
        "\n"
        "  👤  Name       ‣  <b>{username}</b>\n"
        "  🆔  ID         ‣  <code>{uid}</code>\n"
        "  📧  Account    ‣  <code>{account_email}</code>\n"
        "\n"
        "  💰  Balance    ‣  <b><code>{balance}</code></b>\n"
        "  📊  Spent      ‣  <code>{spent}</code>\n"
        "  🏅  Level      ‣  <code>{tier}</code>\n"
        "  💱  Currency   ‣  <code>{currency_name}</code>\n"
        "{vip_line}"
        "\n"
        "✦ ─── <i>NEXUS SMM · Kira</i> ─── ✦"
    ),

    "vip_line": "  👑 VIP         ‣  <code>{pct}% discount</code> 🎁\n",

    "instructions": (
        "🔷  <b>Usage Guide</b>  🔷\n"
        "\n"
        + _sec("Order Steps") + "\n"
        "\n"
        "①  Tap the Order button\n"
        "②  Select your platform\n"
        "③  Choose service type\n"
        "④  Review details & pricing\n"
        "⑤  Send your profile link\n"
        "⑥  Set quantity & confirm\n"
        "\n"
        + _SEP2 + "\n"
        "⚡  <b>Auto & Instant Delivery</b>\n"
        "📌  Digital marketing only\n"
        "\n"
        "<i>⟡  𝑲𝒊𝒓𝒂 · Kira  ⟡\n"
        "✦  NEXUS SMM PANEL  ✦</i>"
    ),

    "disclaimer": (
        "🔷  <b>Terms & Policies</b>  🔷\n"
        "\n"
        + _sec("Core Policies") + "\n"
        "\n"
        "✅  Digital marketing only\n"
        "⚠️  No permanent guarantee\n"
        "📋  Prices may change\n"
        "🚫  Not liable for bans\n"
        "\n"
        + _SEP2 + "\n"
        "<b>Use = Full Agreement</b>\n"
        "\n"
        "<i>⟡  𝑲𝒊𝒓𝒂 · Kira  ⟡\n"
        "✦  NEXUS SMM PANEL  ✦</i>"
    ),

    "vip_info": (
        "🔷  <b>VIP Membership System</b>  🔷\n"
        "\n"
        + _sec("Discount Tiers") + "\n"
        "\n"
        + _fe("⚪", "Regular",  "No discount") + "\n"
        + _fe("🥈", "Silver",   "$10+  ›  3%") + "\n"
        + _fe("🥇", "Gold",     "$50+  ›  7%") + "\n"
        + _fe("💎", "Platinum", "$200+  ›  12%") + "\n"
        "\n"
        + _sec("Your Status") + "\n"
        "\n"
        + _fe("🏆", "Level",    "{tier}") + "\n"
        + _fe("🎁", "Discount", "{pct}%") + "\n"
        "\n"
        "<i>⟡  𝑲𝒊𝒓𝒂 · Kira  ⟡\n"
        "✦  NEXUS SMM PANEL  ✦</i>"
    ),

    "lang_changed":  "🇺🇸  Language set to <b>English</b>",
    "rate_service":  "⭐  Rate the service quality?",
    "rate_1": "😞 Very poor", "rate_2": "😐 Poor",
    "rate_3": "🙂 Average",   "rate_4": "😊 Very good",
    "rate_5": "🤩 Excellent!",
    "skip_review":   "⏭ Skip Review",
    "review_thanks": "✅  Thank you for your review",
    "review_prompt": "🎉  Order <b>#{order_id}</b> completed!\n⭐  How was the service?",
    "currency_usd":  "🇺🇸  US Dollar · USD",
    "currency_yer":  "🇾🇪  Yemeni Rial · YER",
    "currency_sar":  "🇸🇦  Saudi Riyal · SAR",
    "currency_changed": "✅  Currency changed  ›  <b>{cur}</b>",
}


# ══════════════════════════════════════════════════════════════════════════════
#  ⬥  ENGINE
# ══════════════════════════════════════════════════════════════════════════════

STRINGS = {"ar": _AR, "en": _EN}

def t(key: str, lang: str = "ar", **kwargs) -> str:
    text = STRINGS.get(lang, _AR).get(key, _AR.get(key, key))
    if kwargs:
        try:
            text = text.format(**kwargs)
        except (KeyError, ValueError):
            pass
    return text


# ══════════════════════════════════════════════════════════════════════════════
#  ⬥  VIP
# ══════════════════════════════════════════════════════════════════════════════

_VIP_TIERS = [
    (200, 3, {"ar": "💎 بلاتيني", "en": "💎 Platinum"}, 12),
    (50,  2, {"ar": "🥇 ذهبي",    "en": "🥇 Gold"},       7),
    (10,  1, {"ar": "🥈 فضي",     "en": "🥈 Silver"},      3),
    (0,   0, {"ar": "⚪ عادي",    "en": "⚪ Regular"},     0),
]

def get_vip_level(usd: float) -> int:
    for thr, lvl, _, __ in _VIP_TIERS:
        if usd >= thr: return lvl
    return 0

def get_vip_name(level: int, lang: str = "ar") -> str:
    for _, lvl, names, __ in _VIP_TIERS:
        if lvl == level: return names.get(lang, names["ar"])
    return "⚪ عادي"

def get_vip_pct(level: int) -> int:
    for _, lvl, __, pct in _VIP_TIERS:
        if lvl == level: return pct
    return 0


# ══════════════════════════════════════════════════════════════════════════════
#  ⬥  PRICING
# ══════════════════════════════════════════════════════════════════════════════

_YER = 530.0
_SAR = 3.75

def convert_price(usd: float, currency: str = "USD") -> str:
    if currency == "YER": return f"{usd * _YER:,.0f} ﷼"
    if currency == "SAR": return f"{usd * _SAR:.2f} ﷼"
    return f"${usd:.2f}"

def price_in_currency(usd: float, currency: str = "USD") -> float:
    if currency == "YER": return round(usd * _YER, 2)
    if currency == "SAR": return round(usd * _SAR, 2)
    return round(usd, 4)

def get_currency_name(currency: str, lang: str = "ar") -> str:
    n = {
        "USD": {"ar": "دولار أمريكي 🇺🇸", "en": "US Dollar 🇺🇸"},
        "YER": {"ar": "ريال يمني 🇾🇪",    "en": "Yemeni Rial 🇾🇪"},
        "SAR": {"ar": "ريال سعودي 🇸🇦",   "en": "Saudi Riyal 🇸🇦"},
    }
    return n.get(currency, {}).get(lang, currency)

