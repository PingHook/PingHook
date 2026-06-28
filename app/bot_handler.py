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
    "<b>PingHook commands:</b>\n"
    "/pinghook start — get your webhook URL\n"
    "/pinghook mykey — show current URL\n"
    "/pinghook regen — regenerate API key\n"
    "/pinghook channels — list delivery channels\n"
    "/pinghook connect slack &lt;url&gt; — add a Slack incoming webhook\n"
    "/pinghook disconnect &lt;n&gt; — remove a channel\n"
    "/pinghook rules — manage alerting rules\n"
    "/pinghook usage — view ping stats\n"
    "/pinghook history — last 10 delivered pings\n"
    "/pinghook replay &lt;n&gt; — re-send ping #n\n"
    "/pinghook docs — explain each command with examples\n"
    "/pinghook help — this message"
)

DOCS_TEXT = (
    "<b>📖 PingHook — command reference</b>\n\n"

    "<b>/pinghook start</b>\n"
    "Creates your account and returns the webhook URL for this channel. "
    "Safe to run again — returns the same URL if you already have one.\n\n"

    "<b>/pinghook mykey</b>\n"
    "Shows your current webhook URL without creating anything.\n\n"

    "<b>/pinghook regen</b>\n"
    "Regenerates your API key. Old URL stops working immediately — "
    "update all scripts before confirming. Requires <code>/pinghook regen confirm</code>.\n\n"

    "<b>/pinghook channels</b>\n"
    "Lists all active delivery channels (Slack, Telegram, incoming webhooks).\n\n"

    "<b>/pinghook connect slack &lt;url&gt;</b>\n"
    "Adds a Slack incoming webhook as a fan-out destination. "
    "Useful for routing pings to additional workspaces.\n\n"

    "<b>/pinghook disconnect &lt;n&gt;</b>\n"
    "Removes channel number <code>n</code> from the list shown by <code>/pinghook channels</code>.\n\n"

    "<b>/pinghook rules</b>\n"
    "Lists active delivery rules. Rules run on every incoming ping — all must pass for delivery.\n"
    "  · <code>/pinghook rules add keyword error</code> — only deliver if payload contains 'error'\n"
    "  · <code>/pinghook rules add dedup 10</code> — suppress same label within 10 minutes\n"
    "  · <code>/pinghook rules add labels ci-failed payment-received</code> — allow-list specific labels\n"
    "  · <code>/pinghook rules remove 1</code> — remove rule #1\n"
    "  · <code>/pinghook rules clear confirm</code> — remove all rules\n\n"

    "<b>/pinghook usage</b>\n"
    "Shows ping counts for today, this week, and all time. Includes suppressed ping count.\n\n"

    "<b>/pinghook history</b>\n"
    "Shows the last 10 delivered pings with label, age, and payload preview.\n\n"

    "<b>/pinghook replay &lt;n&gt;</b>\n"
    "Re-delivers ping #n from history to all active channels. "
    "Useful after connecting a new channel or fixing a missed alert.\n\n"

    "🌐 <a href=\"https://pinghook.dev/docs\">pinghook.dev/docs</a> — full reference &amp; examples"
)


def _base_url() -> str:
    return settings.BASE_URL.rstrip("/")


def _webhook_url(api_key: str) -> str:
    return f"{_base_url()}/send/{api_key}"


def _connect_instructions(channel_type: str) -> str:
    if channel_type == "slack":
        return (
            "To get your Slack incoming webhook URL:\n"
            "1. Go to api.slack.com/apps\n"
            "2. Create app → Enable Incoming Webhooks\n"
            "3. Add to workspace → Copy webhook URL\n"
            "4. Send: /pinghook connect slack https://hooks.slack.com/..."
        )
    return ""


async def handle_message(
    platform: str,
    platform_user_id: str,
    text: str,
    send_reply,  # async callable: (str) -> None
    context: dict | None = None,
):
    parts   = text.strip().split()
    if not parts:
        return

    command = parts[0].lower()
    args    = parts[1:]

    # Normalize /pinghook <subcommand> → /<subcommand>
    if command == "/pinghook":
        if not args:
            command = "/start"
        else:
            command = "/" + args[0].lower()
            args    = args[1:]

    user    = await get_user_by_platform(platform, platform_user_id)

    # /start always works even without an existing account
    if command == "/start":
        if not user:
            user = await create_user(platform, platform_user_id)
        if not user:
            await send_reply("⚠️ Failed to create your account. Please try again.")
            return
        url = _webhook_url(user["api_key"])
        channel_display = (context or {}).get("channel_display")

        if channel_display:
            await send_reply(
                f"🔔 <b>PingHook connected to {channel_display}</b>\n\n"
                f"Webhook URL for this channel:\n"
                f"<code>{url}/your-label</code>\n\n"
                f"<b>Label = the signal.</b> Append it to the URL:\n"
                f"<code>{url}/ci-failed</code>\n"
                f"<code>{url}/grafana-alert</code>\n"
                f"<code>{url}/payment-received</code>\n\n"
                f"<b>Quick test:</b>\n"
                f"<code>curl -X POST {url}/test -d \"Hello\"</code>\n\n"
                f"<b>Reduce noise:</b> /pinghook rules — keyword filters, dedup, label allow-list\n\n"
                f"<b>Reduce noise:</b> /pinghook rules — keyword filters, dedup, label allow-list\n\n"
                f"/pinghook docs — command reference · /pinghook help — all commands\n"
                f"🌐 <a href=\"https://pinghook.dev\">pinghook.dev</a>"
            )
        else:
            await send_reply(
                f"👋 <b>Welcome to PingHook!</b>\n\n"
                f"Your webhook URL:\n"
                f"<code>{url}/your-label</code>\n\n"
                f"<b>Label = the signal.</b> Append it to the URL:\n"
                f"<code>{url}/ci-failed</code>\n"
                f"<code>{url}/grafana-alert</code>\n"
                f"<code>{url}/payment-received</code>\n\n"
                f"<b>Quick test:</b>\n"
                f"<code>curl -X POST {url}/test -d \"Hello\"</code>\n\n"
                f"──────────────────\n"
                f"<b>History &amp; replay:</b> /pinghook history · /pinghook replay 1\n"
                f"<b>Rules:</b> /pinghook rules — filter noise from Grafana, GitHub &amp; more\n\n"
                f"/pinghook help — all commands\n"
                f"🌐 <a href=\"https://pinghook.dev\">pinghook.dev</a>"
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
        if channel_type not in ("slack",):
            await send_reply("Usage: /pinghook connect slack &lt;url&gt;")
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
                "Connect another channel first with /pinghook connect slack."
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
        footer   = user.get("show_footer", True)
        ok_count = 0
        for ch in channels:
            if await dispatch(ch, label, payload, footer):
                ok_count += 1
        age = relative_time(entry["created_at"])
        await send_reply(
            f"🔁 Replayed ping #{n} ({age})\n"
            f"Label: {html.escape(label) or '(none)'}\n"
            f"Delivered to {ok_count}/{len(channels)} channel(s)."
        )

    elif command == "/help":
        await send_reply(HELP_TEXT)

    elif command == "/docs":
        await send_reply(DOCS_TEXT)

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
