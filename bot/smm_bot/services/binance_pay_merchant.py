"""Binance Pay Merchant API helpers.

This module supports:
1) Creating merchant payment orders (v2 order API)
2) Querying merchant payment status (v2 order query API)
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import time
import uuid
from decimal import Decimal

from services.http_client import get_session
from config import PROXY_URL

logger = logging.getLogger(__name__)

BINANCE_PAY_API_BASE = "https://bpay.binanceapi.com"
CREATE_ORDER_URL = f"{BINANCE_PAY_API_BASE}/binancepay/openapi/v2/order"
QUERY_ORDER_URL = f"{BINANCE_PAY_API_BASE}/binancepay/openapi/v2/order/query"

# Common "paid" aliases observed across Pay APIs.
PAID_STATUSES = {"PAID", "COMPLETED", "SUCCESS", "PAY_SUCCESS"}


def _random_nonce() -> str:
    return uuid.uuid4().hex[:32]


def _json_dumps(payload: dict) -> str:
    # Keep signing payload and request body exactly identical.
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


def _merchant_signature(secret: str, timestamp_ms: int, nonce: str, body_json: str) -> str:
    payload_to_sign = f"{timestamp_ms}\n{nonce}\n{body_json}\n"
    return hmac.new(
        secret.encode("utf-8"),
        payload_to_sign.encode("utf-8"),
        hashlib.sha512,
    ).hexdigest().upper()


def _headers(api_key: str, api_secret: str, body_json: str) -> dict[str, str]:
    timestamp_ms = int(time.time() * 1000)
    nonce = _random_nonce()
    return {
        "Content-Type": "application/json;charset=utf-8",
        "BinancePay-Timestamp": str(timestamp_ms),
        "BinancePay-Nonce": nonce,
        "BinancePay-Certificate-SN": api_key.strip(),
        "BinancePay-Signature": _merchant_signature(
            api_secret.strip(), timestamp_ms, nonce, body_json
        ),
    }


def _build_trade_no(user_id: int) -> str:
    # Merchant trade number must be unique. Keep it short and deterministic.
    return f"SMM{user_id}{int(time.time())}"


def _parse_pay_error(resp_data: dict, http_status: int) -> str:
    code = str(resp_data.get("code", ""))
    msg = (
        resp_data.get("errorMessage")
        or resp_data.get("msg")
        or resp_data.get("message")
        or "unknown_error"
    )
    if code == "400004":
        return (
            "invalid_key_ip_or_permissions"
            f" (code={code}, status={http_status}): {msg}"
        )
    if code:
        return f"code={code}, status={http_status}: {msg}"
    return f"status={http_status}: {msg}"


def _extract_order_status(data: dict) -> str:
    for key in ("status", "orderStatus", "bizStatus"):
        value = data.get(key)
        if value:
            return str(value).upper()
    return ""


async def create_merchant_order(
    api_key: str,
    api_secret: str,
    user_id: int,
    amount: Decimal,
    currency: str = "USDT",
) -> dict:
    """Create Binance Pay merchant order and return payment URLs."""
    api_key = (api_key or "").strip()
    api_secret = (api_secret or "").strip()
    if not api_key or not api_secret:
        return {"created": False, "error": "api_keys_missing"}

    trade_no = _build_trade_no(user_id)
    amount_str = str(amount.quantize(Decimal("0.01")))

    payload = {
        "env": {"terminalType": "APP"},
        "merchantTradeNo": trade_no,
        "orderAmount": amount_str,
        "currency": currency,
        "goods": {
            "goodsType": "01",
            "goodsCategory": "D000",
            "referenceGoodsId": trade_no,
            "goodsName": "Balance Recharge",
            "goodsDetail": f"SMM balance recharge for user {user_id}",
        },
    }
    body_json = _json_dumps(payload)
    headers = _headers(api_key, api_secret, body_json)

    try:
        session = await get_session()
        _proxy = PROXY_URL or None
        async with session.post(CREATE_ORDER_URL, data=body_json, headers=headers) as resp:
            raw = await resp.json(content_type=None)
    except Exception as exc:
        logger.warning("Binance Pay create order error: %s", exc, exc_info=True)
        return {"created": False, "error": str(exc)}

    status_txt = str(raw.get("status", "")).upper()
    code = str(raw.get("code", ""))
    if resp.status != 200 or status_txt != "SUCCESS" or code not in {"", "000000"}:
        return {
            "created": False,
            "error": _parse_pay_error(raw, resp.status),
            "raw": raw,
        }

    data = raw.get("data") or {}
    return {
        "created": True,
        "merchant_trade_no": trade_no,
        "prepay_id": data.get("prepayId", ""),
        "checkout_url": data.get("checkoutUrl", ""),
        "deeplink": data.get("deeplink", ""),
        "qrcode_link": data.get("qrcodeLink", ""),
        "qr_content": data.get("qrContent", ""),
        "raw": raw,
    }


async def query_merchant_order(
    api_key: str,
    api_secret: str,
    merchant_trade_no: str = "",
    prepay_id: str = "",
) -> dict:
    """Query Binance Pay merchant order status."""
    api_key = (api_key or "").strip()
    api_secret = (api_secret or "").strip()
    if not api_key or not api_secret:
        return {"ok": False, "paid": False, "error": "api_keys_missing"}

    payload: dict[str, str] = {}
    if prepay_id:
        payload["prepayId"] = prepay_id
    elif merchant_trade_no:
        payload["merchantTradeNo"] = merchant_trade_no
    else:
        return {"ok": False, "paid": False, "error": "missing_query_identifiers"}

    body_json = _json_dumps(payload)
    headers = _headers(api_key, api_secret, body_json)

    try:
        session = await get_session()
        async with session.post(QUERY_ORDER_URL, data=body_json, headers=headers) as resp:
            raw = await resp.json(content_type=None)
    except Exception as exc:
        logger.warning("Binance Pay query order error: %s", exc, exc_info=True)
        return {"ok": False, "paid": False, "error": str(exc)}

    status_txt = str(raw.get("status", "")).upper()
    code = str(raw.get("code", ""))
    if resp.status != 200 or status_txt != "SUCCESS" or code not in {"", "000000"}:
        return {
            "ok": False,
            "paid": False,
            "error": _parse_pay_error(raw, resp.status),
            "raw": raw,
        }

    data = raw.get("data") or {}
    order_status = _extract_order_status(data)
    paid = order_status in PAID_STATUSES

    return {
        "ok": True,
        "paid": paid,
        "order_status": order_status or "UNKNOWN",
        "transaction_id": data.get("transactionId", ""),
        "prepay_id": data.get("prepayId", prepay_id),
        "merchant_trade_no": data.get("merchantTradeNo", merchant_trade_no),
        "raw": raw,
    }
