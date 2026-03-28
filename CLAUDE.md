# PingHook — Claude Context

## What This Is
A stateless webhook-to-Telegram microSaaS. Users get a unique URL from a Telegram bot and POST any payload to it — the message lands in their Telegram chat instantly. No signup, no dashboard, no config.

## Solo Project
Single developer, single machine. No team, no CI/CD review process.

## Stack
- **Backend:** FastAPI + Uvicorn (async Python)
- **Bot:** Aiogram 3.x (Telegram)
- **Database:** Supabase (PostgreSQL)
- **Hosting:** Render.com
- **Config:** Pydantic-settings via `.env`

## Project Structure
```
app/
  main.py       — FastAPI app, all HTTP endpoints, core webhook handler
  bot.py        — Telegram bot, /start command
  database.py   — Supabase client, all DB queries
  utils.py      — Rate limiter, message formatter
  config.py     — Settings loaded from environment
  templates/
    index.html  — Landing page
schema.sql      — PostgreSQL schema (apply manually in Supabase)
webhook.py      — One-time script to register Telegram webhook URL
```

## Key Design Decisions
- API key is embedded in the URL path (intentional — free tier is low-stakes, zero-friction)
- Labels are appended as path segments after the API key (e.g. `.../api-key/n8n/prod`)
- Supabase is called via `asyncio.to_thread()` — the client is sync, the app is async
- Rate limiting is in-memory (acceptable for MVP; Redis is a future improvement)
- No webhook logging table yet — `log_webhook` was removed as dead code

## Current Tier
Free tier only. Paid tier is planned once meaningful user growth happens.

## Deployment
- `render.yaml` defines the Render.com service
- `webhook.py` must be run manually once after each deployment to register the bot webhook URL with Telegram
- Environment variables: `TELEGRAM_BOT_TOKEN`, `SUPABASE_URL`, `SUPABASE_KEY`, `BASE_URL`

## Do Not Touch
- `.env` — never read, edit, or commit this file
