import hashlib
import hmac
import logging
import re
import time

import httpx

from app.config import settings

logger = logging.getLogger(__name__)

SLACK_API = "https://slack.com/api"


def verify_slack_signature(body: bytes, timestamp: str, signature: str) -> bool:
    try:
        if abs(time.time() - int(timestamp)) > 300:
            return False
    except (ValueError, TypeError):
        return False
    sig_base = f"v0:{timestamp}:{body.decode('utf-8', errors='replace')}"
    expected = "v0=" + hmac.new(
        settings.SLACK_SIGNING_SECRET.encode(),
        sig_base.encode(),
        hashlib.sha256,
    ).hexdigest()
    return hmac.compare_digest(expected, signature)


async def post_message(channel: str, text: str) -> bool:
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f"{SLACK_API}/chat.postMessage",
            headers={"Authorization": f"Bearer {settings.SLACK_BOT_TOKEN}"},
            json={"channel": channel, "text": text},
            timeout=10,
        )
        data = resp.json()
        if not data.get("ok"):
            logger.error(f"[Slack] post_message failed: {data.get('error')}")
        return data.get("ok", False)


def html_to_mrkdwn(text: str) -> str:
    text = re.sub(r"<b>(.*?)</b>", r"*\1*", text, flags=re.DOTALL)
    text = re.sub(r"<i>(.*?)</i>", r"_\1_", text, flags=re.DOTALL)
    text = re.sub(r"<code>(.*?)</code>", r"`\1`", text, flags=re.DOTALL)
    text = re.sub(r'<a href="([^"]+)">([^<]+)</a>', r"<\1|\2>", text)
    return (
        text
        .replace("&lt;", "<")
        .replace("&gt;", ">")
        .replace("&amp;", "&")
        .replace("&mdash;", "—")
        .replace("&middot;", "·")
        .replace("&rarr;", "→")
    )
