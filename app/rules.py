import json
from datetime import datetime, timezone

from app.database import get_active_rules, get_dedup_timestamp


# ── Global bot rules (Layer 3) ────────────────────────────────────────────────

async def passes_global_rules(
    user_id: str, label: str, payload: str
) -> tuple[bool, str | None]:
    rules = await get_active_rules(user_id)
    for rule in rules:
        passed, reason = await _evaluate_rule(rule, user_id, label, payload)
        if not passed:
            return False, reason
    return True, None


async def _evaluate_rule(
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

    elif rt == "label_filter":
        if label not in cfg["labels"]:
            return False, f"label_filter:'{label}'"

    return True, None


def format_rule(rule: dict) -> str:
    rt  = rule["rule_type"]
    cfg = rule["config"]
    if rt == "keyword_match":
        return f"only notify if contains '{cfg['keyword']}'"
    elif rt == "dedup":
        return f"suppress same label within {cfg['window_minutes']} min"
    elif rt == "label_filter":
        return f"only notify for: {', '.join(cfg['labels'])}"
    return str(cfg)


# ── Condition evaluator (Layer 1 — pinghook_rules) ───────────────────────────

def evaluate_conditions(conditions: list, logic: str, payload) -> bool:
    if not conditions:
        return True

    if isinstance(payload, str):
        try:
            payload_dict = json.loads(payload)
        except Exception:
            payload_dict = {"_text": payload}
    elif isinstance(payload, dict):
        payload_dict = payload
    else:
        payload_dict = {}

    results = [
        _evaluate_operator(
            _get_nested_field(payload_dict, c.get("field", "")),
            c.get("operator", "eq"),
            c.get("value"),
        )
        for c in conditions
    ]

    return any(results) if logic == "OR" else all(results)


def _get_nested_field(data: dict, field_path: str):
    current = data
    for key in field_path.split("."):
        if isinstance(current, dict) and key in current:
            current = current[key]
        else:
            return None
    return current


def _evaluate_operator(actual, operator: str, expected) -> bool:
    if operator == "exists":
        return actual is not None
    if actual is None:
        return False
    if operator == "eq":
        return actual == expected
    if operator == "neq":
        return actual != expected
    if operator == "contains":
        return str(expected).lower() in str(actual).lower()
    try:
        if operator == "gt":
            return float(actual) > float(expected)
        if operator == "lt":
            return float(actual) < float(expected)
        if operator == "gte":
            return float(actual) >= float(expected)
        if operator == "lte":
            return float(actual) <= float(expected)
    except (TypeError, ValueError):
        return False
    return False


# ── Query param evaluators (Layer 2) ─────────────────────────────────────────

def parse_if_param(param: str) -> dict | None:
    """Parse 'field.path:operator:value' into a condition dict."""
    parts = param.split(":", 2)
    if len(parts) != 3:
        return None
    field, operator, value = parts
    return {"field": field.strip(), "operator": operator.strip(), "value": value.strip()}


def evaluate_if_params(if_params: list[str], body_json: dict) -> bool:
    """All ?if= conditions must pass (AND). Returns False if any param is malformed."""
    for param in if_params:
        condition = parse_if_param(param)
        if condition is None:
            return False
        actual = _get_nested_field(body_json, condition["field"])
        if not _evaluate_operator(actual, condition["operator"], condition["value"]):
            return False
    return True


def evaluate_textif_params(textif_params: list[str], body_str: str) -> bool:
    """All ?textif= words must appear in body (AND, case-insensitive)."""
    body_lower = body_str.lower()
    return all(word.lower() in body_lower for word in textif_params)
