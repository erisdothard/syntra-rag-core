"""
core/db.py

Shared Supabase client. Single source of truth — every module imports from here.
"""

from __future__ import annotations

import os

from supabase import create_client, Client as SupabaseClient

_client: SupabaseClient | None = None


def get_supabase() -> SupabaseClient:
    """Return a shared Supabase client (created once, reused)."""
    global _client
    if _client is None:
        url = os.environ.get("SUPABASE_URL", "")
        key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "")
        if not url or not key:
            raise RuntimeError("SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY must be set")
        _client = create_client(url, key)
    return _client
