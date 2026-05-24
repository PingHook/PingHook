import json
import logging
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import FastAPI, Request, HTTPException, Query
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates

from app.bot import bot
from app.bot_handler import handle_message
from app.config import settings
from app.database import (
    get_user_by_api_key,
    get_channels,
    log_usage,
    update_dedup_log,
    check_dedup_window,
    count_active_users,
    count_pings_today,
    count_all_pings,
    get_usage_stats,
)
from app.dispatcher import dispatch
from app.rate_limiter import check_rate_limit
from app.rules import (
    passes_global_rules,
    evaluate_conditions,
    evaluate_if_params,
    evaluate_textif_params,
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

templates    = Jinja2Templates(directory="app/templates")
MAX_BODY_SIZE = 100_000  # 100 KB


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("PingHook starting up...")
    yield
    logger.info("Shutting down...")
    await bot.session.close()


app = FastAPI(
    title="PingHook",
    version="4.1.0",
    lifespan=lifespan,
    docs_url=None,      # disable Swagger UI — we have our own /docs page
    redoc_url=None,
    openapi_url=None,
)


# ── Landing page ──────────────────────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
async def root(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})


# ── Telegram webhook receiver ─────────────────────────────────────────────────

@app.post("/telegram/webhook")
async def telegram_webhook(request: Request):
    data    = await request.json()
    message = data.get("message", {})
    chat_id = str(message.get("chat", {}).get("id", ""))
    text    = message.get("text", "")

    if not chat_id or not text:
        return {"ok": True}

    async def send_reply(msg: str):
        await bot.send_message(chat_id=int(chat_id), text=msg)

    try:
        await handle_message("telegram", chat_id, text, send_reply)
    except Exception as e:
        logger.error(f"handle_message error: {e}")

    return {"ok": True}


# ── Rules resolver ────────────────────────────────────────────────────────────

async def _resolve_rules(
    user_id: str,
    label: str,
    raw_body: bytes,
    qp,  # request.query_params
) -> tuple[bool, str | None, str, dict]:
    """
    Returns (should_deliver, suppressed_reason, payload_to_deliver, delivery_options).
    delivery_options keys: channel, dedup, silent.

    Layer 1 — pinghook_rules in JSON body  (highest priority)
    Layer 2 — ?if= / ?textif= / ?dedup=   (per-request overrides)
    Layer 3 — global bot rules             (fallback)
    """
    delivery_options = {
        "channel": qp.get("channel"),
        "dedup":   int(qp["dedup"]) if qp.get("dedup", "").isdigit() else None,
        "silent":  qp.get("silent", "0") in ("1", "true", "yes"),
    }

    # Try to parse body as JSON
    body_json = None
    try:
        body_json = json.loads(raw_body)
    except Exception:
        pass

    # ── Layer 1: pinghook_rules ───────────────────────────────────────────────
    if isinstance(body_json, dict) and "pinghook_rules" in body_json:
        ph = body_json["pinghook_rules"]

        # pinghook_rules keys take priority over query params
        if "channel" in ph:
            delivery_options["channel"] = ph["channel"]
        if "dedup" in ph:
            delivery_options["dedup"] = int(ph["dedup"])

        # Strip pinghook_rules from delivered payload
        payload_dict = {k: v for k, v in body_json.items() if k != "pinghook_rules"}
        payload_str  = json.dumps(payload_dict, indent=2) if payload_dict else ""

        # Evaluate conditions against the clean payload dict
        if "conditions" in ph:
            passed = evaluate_conditions(
                ph["conditions"],
                ph.get("logic", "AND"),
                payload_dict,
            )
            if not passed:
                return False, "pinghook_rules", "", delivery_options

        # Layer 1 dedup check
        if delivery_options["dedup"]:
            if await check_dedup_window(user_id, label, delivery_options["dedup"]):
                return False, "dedup", "", delivery_options

        return True, None, payload_str, delivery_options

    # Plain text payload (Layers 2 and 3)
    payload_str = raw_body.decode("utf-8", errors="replace")

    # ── Layer 2: query param filters ──────────────────────────────────────────
    if_params     = qp.getlist("if")
    textif_params = qp.getlist("textif")

    if if_params:
        if body_json is None:
            # ?if= on a non-JSON body — fail closed
            return False, "query_if_unevaluable", payload_str, delivery_options
        if not evaluate_if_params(if_params, body_json):
            return False, "query_if_condition", payload_str, delivery_options

    if textif_params:
        if not evaluate_textif_params(textif_params, payload_str):
            return False, "query_textif_condition", payload_str, delivery_options

    # Layer 2 dedup check
    if delivery_options["dedup"]:
        if await check_dedup_window(user_id, label, delivery_options["dedup"]):
            return False, "dedup", payload_str, delivery_options

    # ── Layer 3: global bot rules ─────────────────────────────────────────────
    passed, reason = await passes_global_rules(user_id, label, payload_str)
    if not passed:
        return False, reason, payload_str, delivery_options

    return True, None, payload_str, delivery_options


# ── Core send handler ─────────────────────────────────────────────────────────

async def _handle_send(request: Request, api_key: str, label: str):
    raw_body = await request.body()
    if len(raw_body) > MAX_BODY_SIZE:
        raise HTTPException(
            status_code=413,
            detail={"error": "Payload too large", "code": "TOO_LARGE"},
        )

    user = await get_user_by_api_key(api_key)
    if not user:
        raise HTTPException(
            status_code=401,
            detail={"error": "Invalid API key", "code": "INVALID_KEY"},
        )
    if not user.get("is_active", True):
        raise HTTPException(
            status_code=403,
            detail={"error": "Account inactive", "code": "INACTIVE"},
        )

    allowed, resets_in = await check_rate_limit(api_key)
    if not allowed:
        payload_str = raw_body.decode("utf-8", errors="replace")
        await log_usage(api_key, label, len(raw_body), "rate_limited", None, 0, payload_str)
        raise HTTPException(
            status_code=429,
            detail={"error": "Rate limit exceeded", "resets_in": resets_in},
        )

    should_deliver, suppressed_by, payload_str, opts = await _resolve_rules(
        user["id"], label, raw_body, request.query_params
    )

    if not should_deliver:
        await log_usage(api_key, label, len(raw_body), "suppressed", suppressed_by, 0, payload_str or None)
        return {"status": "suppressed", "reason": suppressed_by}

    if opts["silent"]:
        await log_usage(api_key, label, len(raw_body), "suppressed", "silent", 0, payload_str)
        return {"status": "suppressed", "reason": "silent"}

    channels = await get_channels(user["id"])
    if opts["channel"]:
        channels = [c for c in channels if c["type"] == opts["channel"]]

    footer = user.get("show_footer", True)
    success_count = 0
    for ch in channels:
        if await dispatch(ch, label, payload_str, footer):
            success_count += 1

    if success_count > 0:
        await update_dedup_log(user["id"], label)

    status = "success" if success_count > 0 else "failed"
    await log_usage(api_key, label, len(raw_body), status, None, success_count, payload_str)

    return {"status": status, "channels_notified": success_count}


@app.post("/send/{api_key}")
async def send_no_label(request: Request, api_key: str):
    return await _handle_send(request, api_key, "")


@app.post("/send/{api_key}/{label:path}")
async def send_labeled(request: Request, api_key: str, label: str):
    return await _handle_send(request, api_key, label.strip("/"))


# ── Static pages ─────────────────────────────────────────────────────────────

@app.get("/docs", response_class=HTMLResponse)
async def docs_page(request: Request):
    return templates.TemplateResponse("docs.html", {"request": request})


@app.get("/blog", response_class=HTMLResponse)
async def blog_page(request: Request):
    return templates.TemplateResponse("blog.html", {"request": request})


@app.get("/blog/{slug}", response_class=HTMLResponse)
async def blog_post(request: Request, slug: str):
    try:
        return templates.TemplateResponse(f"blog/{slug}.html", {"request": request})
    except Exception:
        raise HTTPException(status_code=404, detail="Post not found")


# ── Public stats ──────────────────────────────────────────────────────────────

@app.get("/api/stats/public")
async def public_stats():
    return {"pings_today": await count_pings_today()}


# ── Admin endpoints ───────────────────────────────────────────────────────────

@app.get("/admin/stats")
async def admin_stats(admin_secret: str = Query(...)):
    if not settings.ADMIN_SECRET or admin_secret != settings.ADMIN_SECRET:
        raise HTTPException(status_code=403, detail="Forbidden")
    return {
        "active_users_30d":     await count_active_users(30),
        "active_users_7d":      await count_active_users(7),
        "total_pings_today":    await count_pings_today(),
        "total_pings_all_time": await count_all_pings(),
    }


@app.get("/admin/stats/{api_key}")
async def user_stats(api_key: str, admin_secret: str = Query(...)):
    if not settings.ADMIN_SECRET or admin_secret != settings.ADMIN_SECRET:
        raise HTTPException(status_code=403, detail="Forbidden")
    return await get_usage_stats(api_key)


# ── Health ────────────────────────────────────────────────────────────────────

@app.get("/health")
async def health():
    return JSONResponse(
        status_code=200,
        content={"status": "ok"},
        headers={"Cache-Control": "no-store"},
    )
