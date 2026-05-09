import asyncio
import logging
import uuid

from supabase import create_client, Client
from app.config import settings

logger = logging.getLogger(__name__)

supabase: Client = create_client(
    settings.SUPABASE_URL,
    settings.SUPABASE_KEY
)


async def create_user(chat_id: int):
    """
    Create a new PingHook user.
    On duplicate chat_id (race condition), returns the existing user.
    """
    data = {
        "chat_id": chat_id,
        "api_key": str(uuid.uuid4()),
    }

    def _insert():
        return supabase.table("users").insert(data).execute()

    try:
        response = await asyncio.to_thread(_insert)
        if response.data:
            return response.data[0]
        return None
    except Exception as e:
        logger.warning(f"[DB] create_user insert failed (possible duplicate): {e}")
        return await get_user_by_chat_id(chat_id)


async def get_user_by_api_key(api_key: str):
    """
    Resolve webhook API key → user.
    """
    def _query():
        return (
            supabase.table("users")
            .select("*")
            .eq("api_key", api_key)
            .limit(1)
            .execute()
        )

    try:
        response = await asyncio.to_thread(_query)
        if response.data:
            return response.data[0]
        return None
    except Exception as e:
        logger.error(f"[DB] get_user_by_api_key failed: {e}")
        return None


async def log_webhook(chat_id: int, labels: list[str], payload: str):
    """Store an incoming webhook payload for history/replay."""
    def _insert():
        return (
            supabase.table("webhook_logs")
            .insert({"chat_id": chat_id, "labels": labels, "payload": payload})
            .execute()
        )
    try:
        await asyncio.to_thread(_insert)
    except Exception as e:
        logger.error(f"[DB] log_webhook failed: {e}")


async def get_recent_webhooks(chat_id: int, limit: int = 10):
    """Fetch the N most recent webhook logs for a user."""
    def _query():
        return (
            supabase.table("webhook_logs")
            .select("*")
            .eq("chat_id", chat_id)
            .order("received_at", desc=True)
            .limit(limit)
            .execute()
        )
    try:
        response = await asyncio.to_thread(_query)
        return response.data or []
    except Exception as e:
        logger.error(f"[DB] get_recent_webhooks failed: {e}")
        return []


async def log_event(event_type: str, chat_id: int | None = None, metadata: dict | None = None):
    """
    Append a behaviour analytics event.

    event_type values:
      - rate_limited   — user exceeded request quota
      - send_failed    — Telegram delivery error
      - bot_command    — /start, /history, /replay used
    """
    def _insert():
        return (
            supabase.table("analytics_events")
            .insert({"event_type": event_type, "chat_id": chat_id, "metadata": metadata or {}})
            .execute()
        )
    try:
        await asyncio.to_thread(_insert)
    except Exception as e:
        logger.error(f"[DB] log_event failed: {e}")


async def get_user_by_chat_id(chat_id: int):
    def _query():
        return (
            supabase.table("users")
            .select("*")
            .eq("chat_id", chat_id)
            .limit(1)
            .execute()
        )

    try:
        response = await asyncio.to_thread(_query)
        if response.data:
            return response.data[0]
        return None
    except Exception as e:
        logger.error(f"[DB] get_user_by_chat_id failed: {e}")
        return None
