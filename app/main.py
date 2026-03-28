import json
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, HTTPException, Path
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from aiogram.types import Update

from app.bot import bot, dp
from app.database import get_user_by_api_key
from app.utils import is_rate_limited, format_message

# -------------------------------------------------
# Logging
# -------------------------------------------------
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

templates = Jinja2Templates(directory="app/templates")

MAX_BODY_SIZE = 100_000  # 100 KB

# -------------------------------------------------
# Lifespan
# -------------------------------------------------
@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("App starting up...")
    yield
    logger.info("App shutting down...")
    await bot.session.close()


app = FastAPI(title="PingHook", version="1.0.0", lifespan=lifespan)

# -------------------------------------------------
# Root
# -------------------------------------------------
@app.get("/", response_class=HTMLResponse)
async def root(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})

# -------------------------------------------------
# Telegram Webhook
# -------------------------------------------------
@app.post("/webhook/{bot_id}")
async def telegram_webhook(request: Request, bot_id: str):
    update_json = await request.json()
    logger.info(f"Incoming Telegram update: {update_json}")
    update = Update(**update_json)
    await dp.feed_update(bot, update)
    return {"status": "ok"}

# -------------------------------------------------
# Shared handler (CORE LOGIC)
# -------------------------------------------------
async def handle_webhook(
    request: Request,
    api_key: str,
    labels: list[str]
):
    # Body size limit
    raw_body = await request.body()
    if len(raw_body) > MAX_BODY_SIZE:
        raise HTTPException(status_code=413, detail="Payload too large.")

    # Validate user first
    user = await get_user_by_api_key(api_key)
    if not user:
        raise HTTPException(status_code=401, detail="Invalid API Key.")
    if not user.get("is_active", True):
        raise HTTPException(status_code=403, detail="User is inactive.")

    # Then rate limit
    if is_rate_limited(api_key):
        raise HTTPException(status_code=429, detail="Rate limit exceeded.")

    # Parse body
    try:
        content_type = request.headers.get("Content-Type", "")
        if "application/json" in content_type:
            body = json.loads(raw_body)
        else:
            body = raw_body.decode("utf-8")
    except Exception:
        body = "Error parsing body"

    # Format and send
    message_text = format_message(body, labels=labels)

    try:
        await bot.send_message(
            chat_id=user["chat_id"],
            text=message_text
        )
    except Exception as e:
        logger.error(f"Failed to send message: {e}")
        raise HTTPException(
            status_code=500,
            detail="Failed to forward message to Telegram."
        )

    return {"status": "ok", "message": "Notification sent."}


@app.post("/send/{api_key}")
async def send_base(
    request: Request,
    api_key: str = Path(..., description="Your unique API Key")
):
    return await handle_webhook(request, api_key, labels=[])


@app.post("/send/{api_key}/{labels:path}")
async def send_labeled(
    request: Request,
    api_key: str = Path(..., description="Your unique API Key"),
    labels: str = Path(..., description="Optional labels")
):
    label_list = [seg.lower() for seg in labels.split("/") if seg]
    return await handle_webhook(request, api_key, labels=label_list)

# -------------------------------------------------
# /v1/user/send endpoints
# -------------------------------------------------
@app.post("/v1/user/send/{api_key}")
async def v1_send_base(request: Request, api_key: str):
    return await handle_webhook(request, api_key, labels=[])


@app.post("/v1/user/send/{api_key}/{labels:path}")
async def v1_send_labeled(request: Request, api_key: str, labels: str):
    label_list = [seg.lower() for seg in labels.split("/") if seg]
    return await handle_webhook(request, api_key, labels=label_list)

# -------------------------------------------------
# Health
# -------------------------------------------------
@app.get("/health")
async def health():
    return JSONResponse(
        status_code=200,
        content={"status": "ok"},
        headers={"Cache-Control": "no-store"}
    )
