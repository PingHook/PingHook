from datetime import datetime, timezone

from app.database import get_active_rules, get_dedup_timestamp


async def passes_alerting_rules(
    user_id: str, label: str, payload: str
) -> tuple[bool, str | None]:
    rules = await get_active_rules(user_id)
    for rule in rules:
        passed, reason = await evaluate_rule(rule, user_id, label, payload)
        if not passed:
            return False, reason
    return True, None


async def evaluate_rule(
    rule: dict, user_id: str, label: str, payload: str
) -> tuple[bool, str]:
    cfg = rule["config"]
    rt  = rule["rule_type"]

    if rt == "keyword_match":
        keyword = cfg["keyword"].lower()
        if keyword not in f"{label} {payload}".lower():
            return False, f"keyword_match:'{cfg['keyword']}'"

    elif rt == "dedup":
        window_minutes = cfg["window_minutes"]
        last_sent = await get_dedup_timestamp(user_id, label)
        if last_sent:
            elapsed = (datetime.now(timezone.utc) - last_sent).total_seconds()
            if elapsed < window_minutes * 60:
                remaining = max(0, int((window_minutes * 60 - elapsed) / 60))
                return False, f"dedup:{remaining}min_remaining"

    elif rt == "quiet_hours":
        start = cfg["start_hour"]
        end   = cfg["end_hour"]
        if is_in_quiet_window(datetime.now(timezone.utc).hour, start, end):
            return False, f"quiet_hours:{start}-{end}"

    elif rt == "label_filter":
        if label not in cfg["labels"]:
            return False, f"label_filter:'{label}'"

    return True, None


def is_in_quiet_window(current_hour: int, start: int, end: int) -> bool:
    # Handles overnight windows correctly e.g. start=22, end=8
    if start > end:
        return current_hour >= start or current_hour < end
    return start <= current_hour < end


def format_rule(rule: dict) -> str:
    rt  = rule["rule_type"]
    cfg = rule["config"]
    if rt == "keyword_match":
        return f"only notify if contains '{cfg['keyword']}'"
    elif rt == "dedup":
        return f"suppress same label within {cfg['window_minutes']} min"
    elif rt == "quiet_hours":
        return f"no pings {cfg['start_hour']}:00–{cfg['end_hour']}:00 UTC"
    elif rt == "label_filter":
        return f"only notify for: {', '.join(cfg['labels'])}"
    return str(cfg)
