import html
import json
from datetime import datetime, timezone

from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.enums import ParseMode
from aiogram.client.bot import DefaultBotProperties

from app.config import settings
from app.database import create_user, get_user_by_chat_id, get_recent_webhooks, log_event
from app.utils import format_message

bot = Bot(
    token=settings.TELEGRAM_BOT_TOKEN,
    default=DefaultBotProperties(parse_mode=ParseMode.HTML)
)

dp = Dispatcher()


def _relative_time(received_at: str) -> str:
    try:
        dt = datetime.fromisoformat(received_at.replace("Z", "+00:00"))
        diff = int((datetime.now(timezone.utc) - dt).total_seconds())
        if diff < 60:
            return f"{diff}s ago"
        if diff < 3600:
            return f"{diff // 60}m ago"
        if diff < 86400:
            return f"{diff // 3600}h ago"
        return f"{diff // 86400}d ago"
    except Exception:
        return received_at


@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    chat_id = message.chat.id
    await log_event("bot_command", chat_id=chat_id, metadata={"command": "start"})

    user = await get_user_by_chat_id(chat_id)
    if not user:
        user = await create_user(chat_id)

    if not user:
        await message.answer("⚠️ Failed to create your account.")
        return

    api_key = user["api_key"]
    webhook_url = f"{settings.BASE_URL.rstrip('/')}/v1/user/send/{api_key}"

    await message.answer(
        "👋 <b>Welcome to PingHook</b>\n\n"
        "PingHook forwards webhooks, API events, and alerts "
        "directly to this Telegram chat — instantly.\n\n"

        "<b>🔗 Your Webhook URL</b>\n"
        f"<code>{webhook_url}</code>\n\n"

        "<b>How it works</b>\n"
        "• Send a <b>POST</b> request to the URL above\n"
        "• Any payload (JSON or text) is delivered here\n"
        "• No setup, no dashboards\n\n"

        "<b>Optional labels (recommended)</b>\n"
        "Add path segments after the URL to tag events by source or environment.\n\n"
        "<i>Example</i>\n"
        f"<code>{webhook_url}/github</code>\n"
        f"<code>{webhook_url}/n8n/prod</code>\n\n"

        "<b>Commands</b>\n"
        "• /history — view your last 10 webhooks\n"
        "• /replay N — resend webhook #N to this chat\n\n"

        "That's it. Start sending events 🚀"
    )


@dp.message(Command("history"))
async def cmd_history(message: types.Message):
    chat_id = message.chat.id
    await log_event("bot_command", chat_id=chat_id, metadata={"command": "history"})
    logs = await get_recent_webhooks(chat_id, limit=10)

    if not logs:
        await message.answer(
            "📭 <b>No webhooks yet.</b>\n\n"
            "Send a POST request to your webhook URL and it will appear here."
        )
        return

    lines = ["📋 <b>Last webhooks</b> — use /replay N to resend\n"]
    for i, log in enumerate(logs, 1):
        labels = log.get("labels") or []
        payload = (log.get("payload") or "").replace("\n", " ")
        preview = html.escape(payload[:80]) + ("…" if len(payload) > 80 else "")
        label_str = " / ".join(labels) if labels else "—"
        when = _relative_time(log.get("received_at", ""))

        lines.append(
            f"<b>{i}.</b> {when}  |  {html.escape(label_str)}\n"
            f"    <code>{preview}</code>"
        )

    await message.answer("\n\n".join(lines))


@dp.message(Command("replay"))
async def cmd_replay(message: types.Message):
    chat_id = message.chat.id
    await log_event("bot_command", chat_id=chat_id, metadata={"command": "replay"})

    parts = (message.text or "").split()
    index = 1
    if len(parts) > 1:
        try:
            index = max(1, int(parts[1]))
        except ValueError:
            await message.answer("Usage: /replay N  (e.g. /replay 2 to resend the 2nd most recent webhook)")
            return

    logs = await get_recent_webhooks(chat_id, limit=index)
    if not logs or len(logs) < index:
        await message.answer(f"No webhook found at position #{index}.")
        return

    log = logs[index - 1]
    labels = log.get("labels") or []
    raw = log.get("payload") or ""

    try:
        body = json.loads(raw)
    except Exception:
        body = raw

    when = _relative_time(log.get("received_at", ""))
    await message.answer(f"↩️ <b>Replaying webhook #{index}</b> (from {when})")
    await bot.send_message(chat_id=chat_id, text=format_message(body, labels=labels))
