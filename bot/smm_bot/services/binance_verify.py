"""
Binance Pay transaction verification via Binance Spot API.
Uses /sapi/v1/pay/transactions to check incoming Pay transfers.

Flow:
1. Query recent incoming transactions (last 2 hours, then 24 hours)
2. Match by Order ID if provided, OR match by amount (within $0.01)
3. Return verified=True if found

This mirrors the same logic used on the website.
"""
import hmac
import hashlib
import logging
import time
from urllib.parse import urlencode

from services.http_client import get_session
from config import PROXY_URL

logger = logging.getLogger(__name__)

BINANCE_API_BASE = "https://api.binance.com"
PAY_TRANSACTIONS_URL = f"{BINANCE_API_BASE}/sapi/v1/pay/transactions"
MAX_VERIFY_AGE_MS = 24 * 60 * 60 * 1000  # 24h


def _sign(params: dict, secret: str) -> str:
    """Generate HMAC SHA256 signature for Binance Spot API."""
    query = urlencode(params)
    return hmac.new(secret.encode(), query.encode(), hashlib.sha256).hexdigest()


def _order_match(order_id: str, tx_id: str, tx_order: str) -> bool:
    """Check if the user-supplied order ID matches this transaction."""
    if not order_id:
        return False
    order_id = str(order_id).strip()
    return (
        order_id == str(tx_id or "").strip()
        or order_id == str(tx_order or "").strip()
        or order_id in str(tx_id or "")
        or order_id in str(tx_order or "")
    )


async def _fetch_transactions(api_key: str, api_secret: str, start_ms: int, end_ms: int, tx_type: int | None = None) -> tuple[list, int]:
    """Fetch Pay transactions from Binance API. Returns (transactions, http_status)."""
    params: dict = {
        "startTime": start_ms,
        "endTime": end_ms,
        "limit": 100,
        "timestamp": int(time.time() * 1000),
        "recvWindow": 10000,
    }
    if tx_type is not None:
        params["transactionType"] = tx_type  # 1 = incoming
    params["signature"] = _sign(params, api_secret)

    headers = {"X-MBX-APIKEY": api_key}
    _proxy = PROXY_URL or None

    try:
        session = await get_session()
        async with session.get(PAY_TRANSACTIONS_URL, params=params, headers=headers, proxy=_proxy) as resp:
            data = await resp.json(content_type=None)
            return data.get("data") or [], resp.status, data
    except Exception as exc:
        logger.warning("Binance Pay API fetch error: %s", exc)
        return [], 0, {}


async def verify_binance_payment(
    api_key: str,
    api_secret: str,
    order_id: str,
    expected_amount: float,
) -> dict:
    """
    Verify a Binance Pay incoming transfer.

    Checks recent transactions for:
    - A match by Order ID (exact or partial)
    - OR a match by amount (positive incoming USDT within $0.01)

    Args:
        api_key: Binance API key (needs "Read" permission)
        api_secret: Binance API secret
        order_id: Order ID shown in Binance app after payment
        expected_amount: Expected USDT amount

    Returns:
        dict with 'verified' (bool), optional 'error', 'details'
    """
    api_key = (api_key or "").strip()
    api_secret = (api_secret or "").strip()

    if not api_key or not api_secret:
        return {"verified": False, "error": "api_keys_missing"}

    order_id = (order_id or "").strip()
    now_ms = int(time.time() * 1000)

    # ── Round 1: last 2 hours, incoming only ─────────────────────────────────
    two_h_ago = now_ms - (2 * 60 * 60 * 1000)
    txs, http_status, raw = await _fetch_transactions(api_key, api_secret, two_h_ago, now_ms, tx_type=1)

    if http_status == 0:
        return {"verified": False, "error": "connection_error"}

    if http_status != 200:
        code = raw.get("code")
        msg = raw.get("msg", str(raw))
        logger.warning("Binance API error: status=%s code=%s msg=%s", http_status, code, msg)
        if code == -2008:
            return {"verified": False, "error": "api_key_invalid"}
        if code == -2015:
            return {"verified": False, "error": "api_key_ip_restricted"}
        return {"verified": False, "error": f"api_error_{http_status}"}

    # ── Round 2: last 24 hours, all types (fallback if round 1 empty) ────────
    if not txs:
        one_day_ago = now_ms - MAX_VERIFY_AGE_MS
        txs, http_status2, _ = await _fetch_transactions(api_key, api_secret, one_day_ago, now_ms)
        if txs:
            logger.info("Binance verify: used 24h fallback query (order_id=%s)", order_id)

    if not txs:
        return {"verified": False, "error": "no_transactions_found"}

    # ── Match transactions ────────────────────────────────────────────────────
    amount_match_tx = None
    order_match_tx = None

    for tx in txs:
        tx_amount_raw = float(tx.get("amount", 0))
        tx_amount = abs(tx_amount_raw)
        tx_currency = (tx.get("currency") or "").upper()
        tx_id = tx.get("transactionId", "")
        tx_order_no = tx.get("orderNumber", "") or tx.get("orderId", "")
        tx_time = int(tx.get("transactionTime") or 0)

        # Only consider incoming (positive amount) USDT/USD
        if tx_amount_raw <= 0 or tx_currency not in ("USDT", "USD", "BUSD"):
            continue

        # Check order ID match
        if order_id and _order_match(order_id, tx_id, tx_order_no):
            order_match_tx = tx
            break  # Best possible match

        # Check amount match (within $0.01 tolerance)
        if abs(tx_amount - expected_amount) < 0.01:
            if amount_match_tx is None:
                amount_match_tx = tx  # Keep first amount match

    # Prefer order ID match, then amount match
    matched_tx = order_match_tx or amount_match_tx

    if matched_tx:
        tx_id = matched_tx.get("transactionId", "")
        tx_amount = abs(float(matched_tx.get("amount", expected_amount)))
        tx_currency = (matched_tx.get("currency") or "USDT").upper()
        tx_time = int(matched_tx.get("transactionTime") or 0)
        age_ms = now_ms - tx_time if tx_time else 0

        if age_ms > MAX_VERIFY_AGE_MS:
            logger.info("Binance: transaction found but too old: order_id=%s age_h=%.1f", order_id, age_ms / 3600000)
            return {"verified": False, "error": "order_found_but_too_old"}

        match_method = "order_id" if order_match_tx else "amount"
        logger.info("Binance payment verified (method=%s): order_id=%s tx_id=%s amount=%s", match_method, order_id, tx_id, tx_amount)
        return {
            "verified": True,
            "details": {
                "transaction_id": tx_id,
                "amount": tx_amount,
                "currency": tx_currency,
                "match_method": match_method,
            },
        }

    # ── No match found — give useful error ───────────────────────────────────
    if order_id:
        # Search wider history to see if the order exists at all
        ninety_days_ago = now_ms - (90 * 24 * 60 * 60 * 1000)
        history_txs, _, _ = await _fetch_transactions(api_key, api_secret, ninety_days_ago, now_ms)
        for tx in history_txs:
            tx_id = tx.get("transactionId", "")
            tx_order_no = tx.get("orderNumber", "") or tx.get("orderId", "")
            if not _order_match(order_id, tx_id, tx_order_no):
                continue
            tx_amount_raw = float(tx.get("amount", 0))
            tx_amount = abs(tx_amount_raw)
            tx_time = int(tx.get("transactionTime") or 0)
            age_ms = now_ms - tx_time if tx_time else MAX_VERIFY_AGE_MS + 1

            if age_ms > MAX_VERIFY_AGE_MS:
                return {"verified": False, "error": "order_found_but_too_old"}
            if abs(tx_amount - expected_amount) >= 0.01:
                return {"verified": False, "error": "order_found_amount_mismatch"}
            # Found it and amount matches — shouldn't happen if we get here, but handle it
            return {
                "verified": True,
                "details": {"transaction_id": tx_id, "amount": tx_amount, "currency": tx.get("currency", "USDT")},
            }

    logger.info("Binance: no match found: order_id=%s expected_amount=%s tx_count=%d", order_id, expected_amount, len(txs))
    return {"verified": False, "error": "amount_not_matched"}
