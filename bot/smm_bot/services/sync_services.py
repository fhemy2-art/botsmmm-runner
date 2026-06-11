"""
Legacy sync_services shim — delegates to provider_manager.
Kept so existing admin handler imports continue to work.
"""
from services.provider_manager import sync_provider_services, sync_all_providers

__all__ = ["sync_provider_services", "sync_all_providers"]
