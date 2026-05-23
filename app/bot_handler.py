import html
import logging
import secrets

from app.config import settings
from app.database import (
    get_user_by_platform,
    create_user,
    get_channels,
    deactivate_channel,
    get_active_rules,
    add_rule,
    remove_rule,
    clear_rules,
    update_api_key,
    get_usage_stats,
    get_recent_webhooks,
)
from app.dispatcher import validate_and_save_webhook, dispatch
from app.rules import format_rule
from app.utils import relative_time

logger = logging.getLogger(__name__)

HELP_TEXT = (
    "PingHook commands:\n"
    "/start — get your webhook URL\n"
    "/mykey — show current URL\n"
    "/regen — regenerate API key\n"
    "/channels — list delivery channels\n"
    "/connect slack &lt;url&gt; — add Slack\n"
    "/connect discord &lt;url&gt; — add Discord\n"
    "/disconnect &lt;n&gt; — remove a channel\n"
    "/rules — manage alerting rules\n"
    "/usage — view ping stats\n"
    "/history — last 10 delivered pings\n"
    "/replay &lt;n&gt; — re-send ping #n\n"
    "/help — this message"
)


def _base_url() -> str:
    return settings.BASE_URL.rstrip("/")


def _webhook_url(api_key: str) -> str:
    return f"{_base_url()}/send/{api_key}"


def _connect_instructions(channel_type: str) -> str:
    if channel_type == "slack":
        return (
            "To get your Slack webhook URL:\n"
            "1. Go to api.slack.com/apps\n"
            "2. Create app → Enable Incoming Webhooks\n"
            "3. Add to workspace → Copy webhook URL\n"
            "4. Send: /connect slack https://hooks.slack.com/..."
        )
    elif channel_type == "discord":
        return (
            "To get your Discord webhook URL:\n"
            "1. Open channel settings → Integrations → Webhooks\n"
            "2. Create webhook → Copy URL\n"
            "3. Send: /connect discord https://discord.com/api/webhooks/..."
        )
    return ""


async def handle_message(
    platform: str,
    platform_user_id: str,
    text: str,
    send_reply,  # async callable: (str) -> None
):
    parts   = text.strip().split()
    if not parts:
        return

    command = parts[0].lower()
    args    = parts[1:]
    user    = await get_user_by_platform(platform, platform_user_id)

    # /start always works even without an existing account
    if command == "/start":
        if not user:
            user = await create_user(platform, platform_user_id)
        if not user:
            await send_reply("⚠️ Failed to create your account. Please try again.")
            return
        url = _webhook_url(user["api_key"])
        await send_reply(
            f"👋 <b>Welcome to PingHook!</b>\n\n"
            f"Your webhook URL:\n"
            f"<code>{url}/your-label</code>\n\n"
            f"<b>The label is the signal.</b>\n"
            f"Append it to describe what happened — your code decides when to fire:\n"
            f"<code>{url}/ci-failed</code>\n"
            f"<code>{url}/grafana-alert</code>\n"
            f"<code>{url}/payment-received</code>\n\n"
            f"<b>Quick test:</b>\n"
            f"<code>curl -X POST {url}/test -d \"Hello!\"</code>\n\n"
            f"──────────────────\n"
            f"<b>Fan out to Slack or Discord:</b>\n"
            f"/connect slack &lt;webhook-url&gt;\n"
            f"/connect discord &lt;webhook-url&gt;\n\n"
            f"<b>History &amp; replay:</b>\n"
            f"/history · /replay 1\n\n"
            f"<b>Advanced:</b> /rules — filter noise from sources you don't control\n"
            f"(Grafana, Uptime Kuma, GitHub webhooks)\n\n"
            f"/help — all commands\n\n"
            f"🌐 <a href=\"https://pinghook.dev\">pinghook.dev</a> — docs, examples &amp; more"
        )
        return

    if not user:
        await send_reply("Please /start first to get your API key.")
        return

    if command == "/mykey":
        url = _webhook_url(user["api_key"])
        await send_reply(f"🔑 Your webhook URL:\n<code>{url}/label</code>")

    elif command == "/regen":
        if args and args[0].lower() == "confirm":
            result  = await _regenerate_key(user)
            new_url = _webhook_url(result["new_key"])
            await send_reply(
                f"✅ New URL:\n<code>{new_url}/label</code>\n\n"
                f"⚠️ Old key is dead. Update all your scripts."
            )
        else:
            await send_reply(
                "⚠️ This will invalidate your current API key immediately.\n"
                "All scripts using the old URL will stop working.\n\n"
                "Reply /regen confirm to proceed."
            )

    elif command == "/channels":
        channels = await get_channels(user["id"])
        if not channels:
            await send_reply("No channels connected.")
            return
        lines = []
        for i, ch in enumerate(channels, 1):
            display = ch.get("label") or ch["destination"][:30]
            lines.append(f"{i}. {ch['type']} — {display} ✅")
        await send_reply("📡 <b>Connected channels:</b>\n" + "\n".join(lines))

    elif command == "/connect":
        if not args:
            await send_reply("Usage: /connect slack &lt;url&gt; or /connect discord &lt;url&gt;")
            return
        channel_type = args[0].lower()
        if channel_type not in ("slack", "discord"):
            await send_reply("Usage: /connect slack &lt;url&gt; or /connect discord &lt;url&gt;")
            return
        if len(args) < 2:
            await send_reply(_connect_instructions(channel_type))
            return
        webhook_url = args[1]
        label       = args[2] if len(args) > 2 else None
        success, message = await validate_and_save_webhook(
            user["id"], channel_type, webhook_url, label
        )
        await send_reply(("✅ " if success else "❌ ") + message)

    elif command == "/disconnect":
        if not args:
            await send_reply("Usage: /disconnect &lt;number from /channels&gt;")
            return
        channels = await get_channels(user["id"])
        try:
            idx     = int(args[0]) - 1
            if idx < 0 or idx >= len(channels):
                raise IndexError
            channel = channels[idx]
        except (ValueError, IndexError):
            await send_reply("Usage: /disconnect &lt;number from /channels&gt;")
            return
        if len(channels) == 1:
            await send_reply(
                "⚠️ This is your only channel. Removing it means you won't receive any pings.\n\n"
                "Connect another channel first with /connect slack or /connect discord."
            )
            return
        await deactivate_channel(channel["id"])
        await send_reply(f"✅ {channel['type']} channel removed.")

    elif command == "/rules":
        await _handle_rules(user, args, send_reply)

    elif command == "/usage":
        stats = await get_usage_stats(user["api_key"])
        await send_reply(
            f"📊 <b>Usage stats:</b>\n"
            f"Today: {stats['today']} pings ({stats['suppressed_today']} suppressed)\n"
            f"This week: {stats['this_week']} pings\n"
            f"All time: {stats['total']} pings\n"
            f"Last ping: {stats['last_ping_ago']} — label: {stats['last_label']}"
        )

    elif command == "/history":
        webhooks = await get_recent_webhooks(user["api_key"])
        if not webhooks:
            await send_reply("No successful pings yet.")
            return
        lines = []
        for i, w in enumerate(webhooks, 1):
            label   = w.get("label") or "(no label)"
            age     = relative_time(w["created_at"])
            preview = (w.get("payload") or "")[:60].replace("\n", " ")
            preview = html.escape(preview)
            if preview:
                lines.append(f"{i}. <b>{html.escape(label)}</b> — {age}\n   <code>{preview}</code>")
            else:
                lines.append(f"{i}. <b>{html.escape(label)}</b> — {age}")
        await send_reply("📜 <b>Last deliveries:</b>\n\n" + "\n\n".join(lines))

    elif command == "/replay":
        if not args:
            await send_reply("Usage: /replay &lt;number from /history&gt;")
            return
        try:
            n = int(args[0])
            if n < 1:
                raise ValueError
        except ValueError:
            await send_reply("Usage: /replay &lt;number from /history&gt;")
            return
        webhooks = await get_recent_webhooks(user["api_key"])
        if n > len(webhooks):
            await send_reply(f"Only {len(webhooks)} entries in history. Use /history to see them.")
            return
        entry    = webhooks[n - 1]
        payload  = entry.get("payload") or ""
        label    = entry.get("label") or ""
        channels = await get_channels(user["id"])
        ok_count = 0
        for ch in channels:
            if await dispatch(ch, label, payload):
                ok_count += 1
        age = relative_time(entry["created_at"])
        await send_reply(
            f"🔁 Replayed ping #{n} ({age})\n"
            f"Label: {html.escape(label) or '(none)'}\n"
            f"Delivered to {ok_count}/{len(channels)} channel(s)."
        )

    elif command == "/help":
        await send_reply(HELP_TEXT)

    else:
        await send_reply("Unknown command. Type /help to see available commands.")


async def _handle_rules(user: dict, args: list, send_reply):
    if not args:
        rules = await get_active_rules(user["id"])
        if not rules:
            await send_reply(
                "No rules set. Everything is delivered.\n"
                "Use /rules add to create rules."
            )
            return
        lines = [f"{i}. [{r['rule_type']}] {format_rule(r)}" for i, r in enumerate(rules, 1)]
        await send_reply(
            "📋 <b>Active rules</b> (all must pass for delivery):\n" +
            "\n".join(lines)
        )
        return

    subcmd = args[0].lower()

    if subcmd == "add" and len(args) >= 3:
        rule_type = args[1].lower()
        rule_args = args[2:]

        if rule_type == "keyword" and rule_args:
            await add_rule(user["id"], "keyword_match", {"keyword": rule_args[0]})
            await send_reply(f"✅ Added: notify only if contains '{rule_args[0]}'")

        elif rule_type == "dedup" and rule_args:
            try:
                minutes = int(rule_args[0])
            except ValueError:
                await send_reply("Usage: /rules add dedup &lt;minutes&gt;")
                return
            await add_rule(user["id"], "dedup", {"window_minutes": minutes})
            await send_reply(f"✅ Added: suppress same label repeated within {minutes} min")

        elif rule_type == "labels" and rule_args:
            await add_rule(user["id"], "label_filter", {"labels": rule_args})
            await send_reply(f"✅ Added: only notify for: {', '.join(rule_args)}")

        else:
            await send_reply(
                "Usage:\n"
                "/rules add keyword &lt;word&gt;\n"
                "/rules add dedup &lt;minutes&gt;\n"
                "/rules add labels &lt;label1&gt; &lt;label2&gt; ..."
            )

    elif subcmd == "remove" and len(args) >= 2:
        removed = await remove_rule(user["id"], args[1])
        if removed:
            await send_reply(f"✅ Rule #{args[1]} removed.")
        else:
            await send_reply(
                f"No rule at position #{args[1]}. Use /rules to see your rules."
            )

    elif subcmd == "clear":
        if len(args) > 1 and args[1].lower() == "confirm":
            await clear_rules(user["id"])
            await send_reply("✅ All rules cleared. Everything will be delivered again.")
        else:
            await send_reply(
                "⚠️ This removes ALL alerting rules.\n"
                "Reply /rules clear confirm to proceed."
            )

    else:
        await send_reply("Type /rules to see your rules, or /help for all commands.")


async def _regenerate_key(user: dict) -> dict:
    new_key = secrets.token_urlsafe(32)
    await update_api_key(user["id"], new_key)

    channels = await get_channels(user["id"])
    new_url  = _webhook_url(new_key)
    warning  = (
        f"⚠️ PingHook API key regenerated.\n"
        f"New URL: {new_url}/your-label\n"
        f"Old key is now dead. Update all scripts and pipelines."
    )
    for channel in channels:
        await dispatch(channel, "key-regenerated", warning)

    return {"new_key": new_key}
