# PingHook

Turn any webhook into an instant Telegram notification — no signup, no dashboard, just a URL.

---

## Get Started

1. Open the bot: [@PingHookBot](https://t.me/PingHookBot)
2. Send `/start`
3. Copy your webhook URL
4. POST anything to it

That's it. Under 60 seconds.

---

## Sending a Notification

**JSON payload**

```bash
curl -X POST https://pinghook.dev/v1/user/send/{your-key} \
  -H "Content-Type: application/json" \
  -d '{"event": "deploy_success", "env": "production"}'
```

Received in Telegram as a formatted code block:

```
New Webhook Received

{
  "event": "deploy_success",
  "env": "production"
}
```

**Plain text with Markdown**

```bash
curl -X POST https://pinghook.dev/v1/user/send/{your-key} \
  -d "**Deploy succeeded** on main — _3 services restarted_"
```

Supports `**bold**`, `_italic_`, and `~~strikethrough~~` — rendered natively in Telegram.

---

## Labels

Append path segments after your key to tag the source of a notification.

```
https://pinghook.dev/v1/user/send/{key}/github
https://pinghook.dev/v1/user/send/{key}/grafana/prod
https://pinghook.dev/v1/user/send/{key}/n8n/prod/payments
```

The message shows:

```
📍 Source: grafana / prod

New Webhook Received
{ ...payload... }
```

Labels are lowercased automatically. Chain as many segments as you want.

---

## Webhook History & Replay

PingHook stores your recent webhooks so you can inspect and resend them without re-triggering your pipeline.

| Command | What it does |
|---|---|
| `/history` | Shows your last 10 webhooks — timestamp, labels, payload preview |
| `/replay N` | Resends webhook #N to your chat |

All history is accessible only through your own Telegram chat. Not via the URL, not via any dashboard.

---

## Limits

| | Free |
|---|---|
| Requests | 5 / minute |
| Payload size | 100 KB max |
| Message length | 3,000 chars (truncated beyond) |
| Formats | JSON, plain text |

---

## Works With

GitHub Actions, Grafana, n8n, Zapier, Make, Uptime Kuma, Prometheus AlertManager, cron jobs, Python scripts, Node.js — anything that sends a POST request.

---

## Self-Hosting

### Requirements
- Python 3.11+
- A Telegram bot token ([create via @BotFather](https://t.me/BotFather))
- A Supabase project

### 1. Clone & install

```bash
git clone https://github.com/asafmd/PingHook
cd PingHook
pip install -r requirements.txt
```

### 2. Environment variables

Create a `.env` file:

```ini
TELEGRAM_BOT_TOKEN=your-token
SUPABASE_URL=https://xyz.supabase.co
SUPABASE_KEY=your-supabase-anon-key
BASE_URL=http://localhost:8000
```

### 3. Database

Run `schema.sql` in your Supabase SQL Editor. This creates three tables:

- `users` — one row per Telegram user, holds the API key
- `webhook_logs` — recent webhook history per user
- `analytics_events` — behaviour events (rate limit hits, send failures, bot command usage)

### 4. Run

```bash
uvicorn app.main:app --reload
```

### 5. Register Telegram webhook

Run once after starting the server (re-run if `BASE_URL` changes):

```bash
python webhook.py
```

---

## Deployment (Render)

1. Connect your GitHub repo as a new Web Service
2. **Build command:** `pip install -r requirements.txt`
3. **Start command:** `uvicorn app.main:app --host 0.0.0.0 --port $PORT`
4. Add env vars: `TELEGRAM_BOT_TOKEN`, `SUPABASE_URL`, `SUPABASE_KEY`, `BASE_URL`
5. After deploy, run `python webhook.py` to register the Telegram webhook

---

## Stack

| Layer | Technology |
|---|---|
| Backend | FastAPI + Uvicorn |
| Bot | Aiogram 3.x |
| Database | Supabase (PostgreSQL) |
| Hosting | Render |
