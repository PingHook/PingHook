import asyncio
from app.bot import bot
from app.config import settings


async def set_webhook():
    webhook_url = f"{settings.BASE_URL.rstrip('/')}/telegram/webhook"
    await bot.set_webhook(webhook_url)
    info = await bot.get_webhook_info()
    print(f"Webhook registered: {info.url}")
    await bot.session.close()


asyncio.run(set_webhook())
