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
