import html
import json
import re
from datetime import datetime, timezone

MAX_MESSAGE_CHARS = 4000


def _markdown_to_html(text: str) -> str:
    text = html.escape(text)
    text = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", text, flags=re.DOTALL)
    text = re.sub(r"__(.+?)__",     r"<b>\1</b>", text, flags=re.DOTALL)
    text = re.sub(r"\*([^*\n]+)\*", r"<i>\1</i>", text)
    text = re.sub(r"_([^_\n]+)_",   r"<i>\1</i>", text)
    text = re.sub(r"~~(.+?)~~",     r"<s>\1</s>", text, flags=re.DOTALL)
    return text


def _truncate(text: str, max_chars: int = MAX_MESSAGE_CHARS) -> str:
    if len(text) > max_chars:
        return text[:max_chars] + "\n\n<i>[message truncated]</i>"
    return text


def format_telegram_message(label: str, payload: str) -> str:
    header = f"🔔 <b>[{html.escape(label)}]</b>\n\n" if label else ""
    if not payload:
        return (header + "<i>Empty payload.</i>").strip() or "<i>Empty payload.</i>"

    try:
        parsed = json.loads(payload)
        body = f"<pre>{html.escape(json.dumps(parsed, indent=2))}</pre>"
    except (json.JSONDecodeError, ValueError):
        body = _markdown_to_html(payload)

    return _truncate(header + body)


def relative_time(ts_str: str) -> str:
    try:
        dt   = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
        diff = int((datetime.now(timezone.utc) - dt).total_seconds())
        if diff < 60:
            return f"{diff}s ago"
        if diff < 3600:
            return f"{diff // 60}m ago"
        if diff < 86400:
            return f"{diff // 3600}h ago"
        return f"{diff // 86400}d ago"
    except Exception:
        return ts_str
