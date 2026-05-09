import html
import json
import re
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


def _markdown_to_html(text: str) -> str:
    """
    Convert a subset of Markdown to Telegram-compatible HTML.
    Code spans are stashed with null-byte sentinels before HTML escaping
    so their contents are never touched by bold/italic/strikethrough regexes.
    """
    stash: list[str] = []

    def save(fragment: str) -> str:
        # Sentinel: \x00N\x00 — null bytes are not HTML-special and
        # contain no markdown characters (*_~`), so regexes never match inside.
        idx = len(stash)
        stash.append(fragment)
        return f"\x00{idx}\x00"

    # Fenced code blocks first (optional language hint stripped)
    text = re.sub(
        r"```(?:\w+\n)?(.*?)```",
        lambda m: save(f"<pre>{html.escape(m.group(1).strip())}</pre>"),
        text, flags=re.DOTALL
    )
    # Inline code
    text = re.sub(
        r"`([^`\n]+)`",
        lambda m: save(f"<code>{html.escape(m.group(1))}</code>"),
        text
    )

    # HTML-escape the remaining text (null bytes are not HTML-special)
    text = html.escape(text)

    # Bold: **text** or __text__
    text = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", text, flags=re.DOTALL)
    text = re.sub(r"__(.+?)__",     r"<b>\1</b>", text, flags=re.DOTALL)
    # Italic: *text* or _text_ (single, not double)
    text = re.sub(r"\*([^*\n]+)\*", r"<i>\1</i>", text)
    text = re.sub(r"_([^_\n]+)_",   r"<i>\1</i>", text)
    # Strikethrough: ~~text~~
    text = re.sub(r"~~(.+?)~~", r"<s>\1</s>", text, flags=re.DOTALL)

    # Restore stashed code fragments
    for idx, fragment in enumerate(stash):
        text = text.replace(f"\x00{idx}\x00", fragment)

    return text


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
        return _truncate(
            f"<b>New Webhook Received</b>\n\n"
            f"{label_text}"
            f"{_markdown_to_html(data)}"
        )

    if isinstance(data, dict):
        pretty_json = json.dumps(data, indent=2, ensure_ascii=False)
        safe_json = html.escape(pretty_json)
        return _truncate(
            f"<b>New Webhook Received</b>\n\n"
            f"{label_text}"
            f"<pre>{safe_json}</pre>"
        )

    return f"{label_text}<i>Unsupported payload format.</i>"
