import json
import logging

import httpx

from app.bot import bot
from app.config import settings
from app.utils import format_telegram_message

logger = logging.getLogger(__name__)

_SLACK_MAX = 4000

_FOOTER_TG    = '\n\n<i>via <a href="https://pinghook.dev">pinghook.dev</a></i>'
_FOOTER_SLACK = "\n\n_via <https://pinghook.dev|pinghook.dev>_"


def _format_slack(label: str, payload: str) -> str:
    header = f"*[{label}]*\n" if label else ""
    if not payload:
        return (header + "Empty payload.").strip()
    try:
        parsed = json.loads(payload)
        body = "```" + json.dumps(parsed, indent=2) + "```"
    except (json.JSONDecodeError, ValueError):
        body = payload
    text = header + body
    return text[:_SLACK_MAX]



async def send_telegram(chat_id: str, label: str, payload: str, footer: bool = True) -> bool:
    text = format_telegram_message(label, payload)
    if footer:
        text += _FOOTER_TG
    await bot.send_message(chat_id=int(chat_id), text=text)
    return True


async def send_slack(webhook_url: str, label: str, payload: str, footer: bool = True) -> bool:
    text = _format_slack(label, payload)
    if footer:
        text += _FOOTER_SLACK
    async with httpx.AsyncClient() as client:
        resp = await client.post(webhook_url, json={"text": text}, timeout=10)
        return resp.status_code == 200



async def send_slack_native(slack_user_id: str, label: str, payload: str, footer: bool = True) -> bool:
    text = _format_slack(label, payload)
    if footer:
        text += _FOOTER_SLACK
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            "https://slack.com/api/chat.postMessage",
            headers={"Authorization": f"Bearer {settings.SLACK_BOT_TOKEN}"},
            json={"channel": slack_user_id, "text": text},
            timeout=10,
        )
        data = resp.json()
        return data.get("ok", False)


async def dispatch(channel: dict, label: str, payload: str, footer: bool = True) -> bool:
    try:
        ch_type = channel["type"]
        dest    = channel["destination"]
        if ch_type == "telegram":
            return await send_telegram(dest, label, payload, footer)
        elif ch_type == "slack":
            return await send_slack(dest, label, payload, footer)
        elif ch_type == "slack_native":
            return await send_slack_native(dest, label, payload, footer)
        return False
    except Exception as e:
        logger.error(f"Dispatch failed [{channel.get('type')}]: {e}")
        return False


async def validate_and_save_webhook(
    user_id: str,
    channel_type: str,
    webhook_url: str,
    label: str | None = None,
) -> tuple[bool, str]:
    test_payload = "✅ PingHook connected successfully!"
    if channel_type == "slack":
        success = await send_slack(webhook_url, "pinghook-test", test_payload, footer=False)
    else:
        return False, "Unknown channel type"

    if not success:
        return False, f"Could not reach that URL. Check your {channel_type} webhook settings."

    from app.database import save_channel
    await save_channel(user_id, channel_type, webhook_url, label)
    return True, "Connected successfully"
