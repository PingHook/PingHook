# PingHook

Turn any webhook into an instant Telegram notification — no setup, no dashboard, just a URL.

---

## Get Started

1. Open the bot: [@pinghookbot](https://t.me/pinghookbot)
2. Send `/start`
3. Copy your webhook URL
4. POST anything to it

That's it.

---

## Sending a Notification

```bash
curl -X POST https://api.pinghook.dev/v1/user/send/{your-api-key} \
  -H "Content-Type: application/json" \
  -d '{"status": "deploy complete", "env": "production"}'
```

You'll receive this in Telegram instantly:

```
New Webhook Received

{
  "status": "deploy complete",
  "env": "production"
}
```

Supports JSON, plain text, and form data.

---

## Labels

Append path segments after your API key to tag where the notification came from.

```
https://api.pinghook.dev/v1/user/send/{api-key}/github
https://api.pinghook.dev/v1/user/send/{api-key}/n8n/prod
```

Your Telegram message will show:

```
📍 Source: n8n / prod

New Webhook Received
{ ...payload... }
```

Useful when you have multiple workflows or services sending to the same URL.

---

## Limits

| | Free |
|---|---|
| Requests | 5 / minute |
| Payload size | 100 KB |
| Message length | 3000 chars (truncated beyond) |

---

---

## Self-Hosting

### Requirements
- Python 3.11+
- A Telegram bot token ([create one via @BotFather](https://t.me/BotFather))
- A Supabase project

### 1. Clone & Install

```bash
git clone https://github.com/pinghook/pinghook
cd pinghook
pip install -r requirements.txt
```

### 2. Environment Variables

Create a `.env` file:

```ini
TELEGRAM_BOT_TOKEN=your-token
SUPABASE_URL=https://xyz.supabase.co
SUPABASE_KEY=your-supabase-anon-key
BASE_URL=http://localhost:8000
```

### 3. Database

Run the contents of `schema.sql` in your Supabase SQL Editor.

### 4. Run

```bash
uvicorn app.main:app --reload
```

### 5. Register Telegram Webhook

Run once after starting the server:

```bash
python webhook.py
```

This tells Telegram where to send bot updates. Re-run if your `BASE_URL` changes.

---

## Deployment (Render)

1. Connect your GitHub repo as a new Web Service
2. **Build command:** `pip install -r requirements.txt`
3. **Start command:** `uvicorn app.main:app --host 0.0.0.0 --port $PORT`
4. Add environment variables: `TELEGRAM_BOT_TOKEN`, `SUPABASE_URL`, `SUPABASE_KEY`, `BASE_URL`
5. After deploy, run `python webhook.py` to register the Telegram webhook

---

## Stack

- **Backend:** FastAPI + Uvicorn
- **Bot:** Aiogram 3.x
- **Database:** Supabase (PostgreSQL)
- **Hosting:** Render
