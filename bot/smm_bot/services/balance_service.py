"""
Legacy balance_service shim — kept for backward compatibility.
New code should import from services.user_manager directly.
"""
from services.user_manager import get_or_create_user, add_balance

__all__ = ["get_or_create_user", "add_balance"]
