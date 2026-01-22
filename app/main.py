from fastapi import FastAPI, Request, HTTPException, Path
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from app.bot import bot, dp
from app.config import settings
from app.database import get_user_by_api_key
from app.utils import is_rate_limited, format_message
import logging
import asyncio
from contextlib import asynccontextmanager
from aiogram.types import Update

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


templates = Jinja2Templates(directory="app/templates")

# --- Lifespan context for startup/shutdown ---
@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("App starting up... Telegram webhooks require a public URL for testing.")
    # You could start polling here for local testing if needed
    yield
    logger.info("App shutting down...")
    await bot.session.close()  # Close Telegram session properly

app = FastAPI(title="PingHook", version="1.0.0", lifespan=lifespan)

# --- Root page ---
@app.get("/", response_class=HTMLResponse)
async def root(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})

# --- Webhook endpoint for Telegram updates ---
@app.post("/webhook/{bot_id}")
async def telegram_webhook(request: Request, bot_id: str):
    update_json = await request.json()
    logger.info(f"Incoming Telegram update: {update_json}")
    update = Update(**update_json)
    await dp.feed_update(bot, update)
    return {"status": "ok"}

# --- Webhook endpoint for sending messages manually ---
@app.post("/send/{api_key}")
async def receive_webhook(
    request: Request,
    api_key: str = Path(..., description="Your unique API Key")
):
    # Rate limit
    if is_rate_limited(api_key):
        raise HTTPException(status_code=429, detail="Rate limit exceeded.")

    # Validate user
    user = await get_user_by_api_key(api_key)
    if not user:
        raise HTTPException(status_code=401, detail="Invalid API Key.")
    if not user.get("is_active", True):
        raise HTTPException(status_code=403, detail="User is inactive.")

    # Parse body
    try:
        content_type = request.headers.get("Content-Type", "")
        if "application/json" in content_type:
            body = await request.json()
        else:
            body = (await request.body()).decode("utf-8")
    except Exception:
        body = "Error parsing body"

    # Format message
    message_text = format_message(body)

    # Send to Telegram
    try:
        await bot.send_message(chat_id=user["chat_id"], text=message_text)
    except Exception as e:
        logger.error(f"Failed to send message: {e}")
        raise HTTPException(status_code=500, detail="Failed to forward message to Telegram.")

    return {"status": "ok", "message": "Notification sent."}

@app.get("/health")
def health():
    return JSONResponse(
        status_code=200,
        content={"status": "ok"},
        headers={"Cache-Control": "no-store"}
    )
