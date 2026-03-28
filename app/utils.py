import html
import json
import time
from collections import defaultdict
from typing import Dict, Tuple

# -------------------------------------------------
# Rate Limiter — fixed window, in-memory
# -------------------------------------------------
_rate_limit_store: Dict[str, Tuple[int, int]] = defaultdict(lambda: (0, 0))
RATE_LIMIT_REQUESTS = 5
RATE_LIMIT_WINDOW = 60  # seconds


def is_rate_limited(api_key: str) -> bool:
    """Returns True if the user has exceeded the rate limit."""
    current_time = int(time.time())
    window_start, count = _rate_limit_store[api_key]

    if current_time - window_start > RATE_LIMIT_WINDOW:
        _rate_limit_store[api_key] = (current_time, 1)
        return False

    if count >= RATE_LIMIT_REQUESTS:
        return True

    _rate_limit_store[api_key] = (window_start, count + 1)
    return False


# -------------------------------------------------
# Message Formatter
# -------------------------------------------------
MAX_MESSAGE_CHARS = 3000  # Telegram hard limit is 4096; leave headroom for headers


def _truncate(text: str) -> str:
    if len(text) > MAX_MESSAGE_CHARS:
        return text[:MAX_MESSAGE_CHARS] + "\n\n<i>[message truncated]</i>"
    return text


def format_message(
    data: dict | str | None,
    labels: list[str] | None = None
) -> str:
    """Formats incoming webhook data into a Telegram-safe HTML message."""
    labels = labels or []

    label_text = ""
    if labels:
        label_text = f"📍 <b>Source:</b> {' / '.join(labels)}\n\n"

    if data is None:
        return f"{label_text}<i>Received empty payload.</i>"

    if isinstance(data, str):
        safe_text = html.escape(data)
        return _truncate(
            f"<b>New Webhook Received</b>\n\n"
            f"{label_text}"
            f"{safe_text}"
        )

    if isinstance(data, dict):
        pretty_json = json.dumps(data, indent=2)
        safe_json = html.escape(pretty_json)
        return _truncate(
            f"<b>New Webhook Received</b>\n\n"
            f"{label_text}"
            f"<pre>{safe_json}</pre>"
        )

    return f"{label_text}<i>Unsupported payload format.</i>"
