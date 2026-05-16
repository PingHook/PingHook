import logging
from datetime import datetime, timezone

from app.database import (
    get_or_create_rate_limit,
    reset_hourly,
    reset_daily,
    increment_rate_counters,
)

logger = logging.getLogger(__name__)

HOURLY_LIMIT = 100
DAILY_LIMIT  = 1000


def _parse_ts(ts_str: str) -> datetime:
    return datetime.fromisoformat(ts_str.replace("Z", "+00:00"))


async def check_rate_limit(api_key: str) -> tuple[bool, str]:
    """Returns (allowed, resets_in). resets_in is '' when allowed."""
    record = await get_or_create_rate_limit(api_key)
    if not record:
        return True, ""  # fail open on DB error

    now           = datetime.now(timezone.utc)
    last_hourly   = _parse_ts(record["last_reset_hourly"])
    last_daily    = _parse_ts(record["last_reset_daily"])

    if (now - last_hourly).total_seconds() >= 3600:
        record = await reset_hourly(api_key, now) or record

    if (now - last_daily).days >= 1:
        record = await reset_daily(api_key, now) or record

    if record["requests_this_hour"] >= HOURLY_LIMIT:
        elapsed      = (now - _parse_ts(record["last_reset_hourly"])).total_seconds()
        remaining    = max(1, int((3600 - elapsed) / 60))
        return False, f"{remaining} minutes"

    if record["requests_today"] >= DAILY_LIMIT:
        elapsed      = (now - _parse_ts(record["last_reset_daily"])).total_seconds()
        remaining    = max(1, int((86400 - elapsed) / 3600))
        return False, f"{remaining} hours"

    await increment_rate_counters(api_key)
    return True, ""
