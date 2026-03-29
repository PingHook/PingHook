"""
Conftest — patches external dependencies (Supabase, Telegram) before any app
module is imported so the test process never touches real infrastructure.
"""
import os
os.environ.setdefault("TELEGRAM_BOT_TOKEN", "123456789:AAFakeTokenForTestingPurposesOnly12")
os.environ.setdefault("SUPABASE_URL", "https://fake.supabase.co")
os.environ.setdefault("SUPABASE_KEY", "fake-supabase-key")
os.environ.setdefault("BASE_URL", "https://example.com")

from unittest.mock import MagicMock, patch

# Patch supabase.create_client before app.database is imported
_mock_supabase_client = MagicMock()
_supabase_patcher = patch("supabase.create_client", return_value=_mock_supabase_client)
_supabase_patcher.start()
