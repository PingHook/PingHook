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
    count_active_users,
    count_pings_today,
    count_all_pings,
    get_usage_stats,
)
from app.dispatcher import dispatch
from app.rate_limiter import check_rate_limit
from app.rules import passes_alerting_rules

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

templates    = Jinja2Templates(directory="app/templates")
MAX_BODY_SIZE = 100_000  # 100 KB


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("PingHook V4 starting up...")
    yield
    logger.info("Shutting down...")
    await bot.session.close()


app = FastAPI(title="PingHook", version="4.0.0", lifespan=lifespan)


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


# ── Core send handler ─────────────────────────────────────────────────────────

async def _handle_send(
    request: Request,
    api_key: str,
    label: str,
    channel_filter: Optional[str] = None,
):
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
        await log_usage(api_key, label, len(raw_body), "rate_limited", None, 0)
        raise HTTPException(
            status_code=429,
            detail={"error": "Rate limit exceeded", "resets_in": resets_in},
        )

    payload = raw_body.decode("utf-8", errors="replace")

    passed, suppressed_by = await passes_alerting_rules(user["id"], label, payload)
    if not passed:
        await log_usage(api_key, label, len(raw_body), "suppressed", suppressed_by, 0)
        return {"status": "suppressed", "reason": suppressed_by}

    channels = await get_channels(user["id"])
    if channel_filter:
        channels = [c for c in channels if c["type"] == channel_filter]

    success_count = 0
    for ch in channels:
        ok = await dispatch(ch, label, payload)
        if ok:
            success_count += 1

    if success_count > 0:
        await update_dedup_log(user["id"], label)

    status = "success" if success_count > 0 else "failed"
    await log_usage(api_key, label, len(raw_body), status, None, success_count)

    return {"status": status, "channels_notified": success_count}


@app.post("/send/{api_key}")
async def send_no_label(
    request: Request,
    api_key: str,
    channel: Optional[str] = Query(None),
):
    return await _handle_send(request, api_key, "", channel)


@app.post("/send/{api_key}/{label:path}")
async def send_labeled(
    request: Request,
    api_key: str,
    label: str,
    channel: Optional[str] = Query(None),
):
    label = label.strip("/")
    return await _handle_send(request, api_key, label, channel)


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
        "active_users_30d":    await count_active_users(30),
        "active_users_7d":     await count_active_users(7),
        "total_pings_today":   await count_pings_today(),
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
