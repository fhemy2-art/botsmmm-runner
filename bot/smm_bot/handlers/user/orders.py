"""طلباتي — 𝑲𝒊𝒓𝒂 | كيرا"""
import logging
from aiogram import Router, F
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from repositories.order_repo import get_orders_with_services, get_order_with_service, count_user_orders
from services.user_manager import get_or_create_user
from handlers.common import add_nav, nav_enter, register_screen, safe_edit
from ui import status_emoji

logger = logging.getLogger(__name__)
router = Router()
ORDERS_PER_PAGE = 8
KIRA = "𝑲𝒊𝒓𝒂 | كيرا"

STATUS_AR = {
    "pending":"⏳ قيد الانتظار","processing":"🔄 جارٍ التنفيذ",
    "completed":"✅ مكتمل","partial":"⚠️ مكتمل جزئياً",
    "canceled":"❌ ملغي","refunded":"💰 مسترد",
}
STATUS_EN = {
    "pending":"⏳ Pending","processing":"🔄 Processing",
    "completed":"✅ Completed","partial":"⚠️ Partial",
    "canceled":"❌ Canceled","refunded":"💰 Refunded",
}

def _L(lang, ar, en): return ar if lang=="ar" else en


@router.callback_query(F.data == "my_orders")
@router.callback_query(F.data.startswith("orders:"))
async def show_orders(cb: CallbackQuery, db, screen=None, from_back=False):
    data = screen or cb.data
    page = 0
    if data.startswith("orders:"):
        parts = data.split(":")
        page = int(parts[1]) if len(parts)>1 and parts[1].isdigit() else 0
    nav_enter(cb.from_user.id, data if data.startswith("orders:") else "my_orders", push=not from_back)

    user = await get_or_create_user(db, cb.from_user.id)
    lang = user.language or "ar"
    status_map = STATUS_AR if lang=="ar" else STATUS_EN
    total = await count_user_orders(db, cb.from_user.id)
    rows = await get_orders_with_services(db, cb.from_user.id, limit=ORDERS_PER_PAGE, offset=page*ORDERS_PER_PAGE)

    if not rows:
        _msg = '🛒 لا توجد طلبات بعد!' if lang=='ar' else '🛒 No orders yet!'
        _ttl = '📦 طلباتي' if lang=='ar' else '📦 My Orders'
        text = (
            f"💠  <b>𝑲𝒊𝒓𝒂 · {_ttl}</b>  💠\n"
            "<i>◈  لا توجد طلبات بعد  ◈</i>\n"
            "\n"
            f"{_msg}\n"
            "\n"
            "<i>◇  𝑲𝒊𝒓𝒂 · كيرا  ◇</i>\n"
            "<i>✦  NEXUS SMM PANEL  ✦</i>"
        )
        kb = InlineKeyboardMarkup(inline_keyboard=add_nav([
            [InlineKeyboardButton(
                text=_L(lang,"🛒 ✦ طلب جديد الآن ✦","🛒 ✦ New Order Now ✦"),
                callback_data="new_order")],
        ], lang))
        await safe_edit(cb, text, kb)
        return await cb.answer()

    total_pages = max(1,(total+ORDERS_PER_PAGE-1)//ORDERS_PER_PAGE)
    _ttl2 = "طلباتي" if lang=="ar" else "My Orders"
    _tot_lbl = "إجمالي" if lang=="ar" else "Total"
    _pg_lbl = "صفحة" if lang=="ar" else "Page"
    _hint = "👇 اضغط على الطلب للتفاصيل" if lang=="ar" else "👇 Tap an order for details"
    header = (
        f"🔷  <b>𝑲𝒊𝒓𝒂 · {_ttl2}</b>  🔷\n"
        f"<i>⟡  {_tot_lbl}: <b>{total}</b>  ·  {_pg_lbl} {page+1}/{total_pages}  ⟡</i>\n"
        "\n"
        f"  <b>◈ {_hint} ◈</b>"
    )

    buttons = []
    for order, service in rows:
        svc_name = service.name[:22] if service else _L(lang,"غير معروف","Unknown")
        st = status_map.get(order.status, order.status)
        date_str = order.created_at.strftime("%m/%d") if order.created_at else "-"
        charge_str = f"${float(order.charge):.4f}"
        buttons.append([InlineKeyboardButton(
            text=f"#{order.id} {status_emoji(order.status)} {svc_name[:20]}",
            callback_data=f"order_detail:{order.id}")])
        buttons.append([InlineKeyboardButton(
            text=f"  📊 {order.quantity:,}  💰 {charge_str}  📅 {date_str}",
            callback_data=f"order_detail:{order.id}")])

    pager = []
    if page > 0:
        pager.append(InlineKeyboardButton(text="◀️", callback_data=f"orders:{page-1}"))
    pager.append(InlineKeyboardButton(text=f"📄 {page+1}/{total_pages}", callback_data="noop"))
    if page+1 < total_pages:
        pager.append(InlineKeyboardButton(text="▶️", callback_data=f"orders:{page+1}"))
    if pager: buttons.append(pager)

    buttons.append([InlineKeyboardButton(
        text=_L(lang,"🛒 ✦ طلب جديد ✦","🛒 ✦ New Order ✦"), callback_data="new_order")])
    buttons.extend(add_nav([], lang))

    await safe_edit(cb, header, InlineKeyboardMarkup(inline_keyboard=buttons))
    await cb.answer()


@router.callback_query(F.data.startswith("order_detail:"))
async def order_detail(cb: CallbackQuery, db, screen=None, from_back=False):
    data = screen or cb.data
    parts = data.split(":")
    if len(parts)<2 or not parts[1].isdigit():
        await cb.answer("❌"); return
    oid = int(parts[1])
    nav_enter(cb.from_user.id, data, push=not from_back)
    user = await get_or_create_user(db, cb.from_user.id)
    lang = user.language or "ar"
    status_map = STATUS_AR if lang=="ar" else STATUS_EN
    result = await get_order_with_service(db, cb.from_user.id, oid)

    if not result:
        await cb.answer(_L(lang,"❌ الطلب غير موجود","❌ Order not found"), show_alert=True); return

    order, service = result
    svc_name = service.name if service else _L(lang,"غير معروف","Unknown")
    st = status_map.get(order.status, order.status)
    date_str = order.created_at.strftime("%Y/%m/%d %H:%M") if order.created_at else "-"

    if lang=="ar":
        text = (
            f"💠  <b>𝑲𝒊𝒓𝒂 · تفاصيل الطلب</b>  💠\n"
            "<i>◈  بيانات الطلب كاملة  ◈</i>\n"
            "\n"
            "▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬\n"
            f"︾  <b>طلب رقم #{order.id}</b>  ︾\n"
            "\n"
            f"📦 الخدمة  •  <code>{svc_name[:50]}</code>\n"
            f"📊 الكمية  •  <code>{order.quantity:,}</code>\n"
            f"💰 التكلفة  •  <code>${float(order.charge):.4f}</code>\n"
            f"🔄 الحالة  •  <code>{st}</code>\n"
            f"📅 التاريخ  •  <code>{date_str}</code>\n"
            f"🔗 الرابط  •  <code>{order.link or '—'}</code>\n"
            "\n"
            "<i>◇  𝑲𝒊𝒓𝒂 · كيرا  ◇</i>\n"
            "<i>✦  NEXUS SMM PANEL  ✦</i>"
        )
    else:
        text = (
            f"💠  <b>𝑲𝒊𝒓𝒂 · Order Details</b>  💠\n"
            "<i>◈  Full Order Info  ◈</i>\n"
            "\n"
            "▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬\n"
            f"︾  <b>Order #{order.id}</b>  ︾\n"
            "\n"
            f"📦 Service  •  <code>{svc_name[:50]}</code>\n"
            f"📊 Quantity  •  <code>{order.quantity:,}</code>\n"
            f"💰 Cost  •  <code>${float(order.charge):.4f}</code>\n"
            f"🔄 Status  •  <code>{st}</code>\n"
            f"📅 Date  •  <code>{date_str}</code>\n"
            f"🔗 Link  •  <code>{order.link or '—'}</code>\n"
            "\n"
            "<i>◇  𝑲𝒊𝒓𝒂 · Kira  ◇</i>\n"
            "<i>✦  NEXUS SMM PANEL  ✦</i>"
        )

    buttons = [[InlineKeyboardButton(
        text=_L(lang,"📋 رجوع للطلبات","📋 Back to Orders"),
        callback_data="my_orders")]]
    buttons.extend(add_nav([], lang))
    await safe_edit(cb, text, InlineKeyboardMarkup(inline_keyboard=buttons))
    await cb.answer()


def register_screens():
    register_screen("my_orders", show_orders)
    register_screen("orders:",   show_orders, prefix=True)
    register_screen("order_detail:", order_detail, prefix=True)
