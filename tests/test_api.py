"""
Integration tests for FastAPI endpoints in app/main.py.
External calls (Supabase, Telegram) are mocked at the function level.

Uses httpx.AsyncClient with ASGITransport (compatible with httpx>=0.28).
"""
import pytest
import pytest_asyncio
import httpx
from unittest.mock import AsyncMock, MagicMock, patch

from app.utils import _rate_limit_store

# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------

VALID_API_KEY = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
ACTIVE_USER = {
    "id": 123456789,
    "chat_id": 123456789,
    "api_key": VALID_API_KEY,
    "is_active": True,
}
INACTIVE_USER = {**ACTIVE_USER, "is_active": False}

pytestmark = pytest.mark.anyio


@pytest.fixture(autouse=True)
def clear_rate_limiter():
    _rate_limit_store.clear()
    yield
    _rate_limit_store.clear()


@pytest.fixture()
def mock_bot():
    with patch("app.main.bot") as m:
        m.session.close = AsyncMock()
        m.send_message = AsyncMock(return_value=MagicMock())
        yield m


@pytest_asyncio.fixture()
async def client(mock_bot):
    from app.main import app
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as c:
        yield c, mock_bot


async def _send(client, path, body=None, content_type="application/json"):
    headers = {"Content-Type": content_type}
    body = body if body is not None else '{"event": "test"}'
    return await client.post(path, content=body, headers=headers)


# ─────────────────────────────────────────────
# Infrastructure endpoints
# ─────────────────────────────────────────────

class TestInfrastructureEndpoints:
    async def test_health_returns_200_ok(self, client):
        c, _ = client
        resp = await c.get("/health")
        assert resp.status_code == 200
        assert resp.json() == {"status": "ok"}

    async def test_health_has_no_cache_header(self, client):
        c, _ = client
        resp = await c.get("/health")
        assert resp.headers.get("cache-control") == "no-store"

    async def test_root_returns_html(self, client):
        c, _ = client
        resp = await c.get("/")
        assert resp.status_code == 200
        assert "text/html" in resp.headers["content-type"]

    async def test_root_html_contains_pinghook(self, client):
        c, _ = client
        resp = await c.get("/")
        assert "PingHook" in resp.text


# ─────────────────────────────────────────────
# Webhook — authentication
# ─────────────────────────────────────────────

class TestWebhookAuthentication:
    async def test_invalid_api_key_returns_401(self, client):
        c, _ = client
        with patch("app.main.get_user_by_api_key", return_value=None):
            resp = await _send(c, "/send/invalid-key")
        assert resp.status_code == 401

    async def test_inactive_user_returns_403(self, client):
        c, _ = client
        with patch("app.main.get_user_by_api_key", return_value=INACTIVE_USER):
            resp = await _send(c, f"/send/{VALID_API_KEY}")
        assert resp.status_code == 403

    async def test_valid_active_user_returns_200(self, client):
        c, _ = client
        with patch("app.main.get_user_by_api_key", return_value=ACTIVE_USER):
            resp = await _send(c, f"/send/{VALID_API_KEY}")
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"

    async def test_valid_key_on_v1_endpoint_returns_200(self, client):
        c, _ = client
        with patch("app.main.get_user_by_api_key", return_value=ACTIVE_USER):
            resp = await _send(c, f"/v1/user/send/{VALID_API_KEY}")
        assert resp.status_code == 200


# ─────────────────────────────────────────────
# Webhook — rate limiting
# ─────────────────────────────────────────────

class TestWebhookRateLimiting:
    async def test_sixth_request_returns_429(self, client):
        c, _ = client
        with patch("app.main.get_user_by_api_key", return_value=ACTIVE_USER):
            for _ in range(5):
                await _send(c, f"/send/{VALID_API_KEY}")
            resp = await _send(c, f"/send/{VALID_API_KEY}")
        assert resp.status_code == 429

    async def test_fifth_request_still_succeeds(self, client):
        c, _ = client
        with patch("app.main.get_user_by_api_key", return_value=ACTIVE_USER):
            for _ in range(4):
                await _send(c, f"/send/{VALID_API_KEY}")
            resp = await _send(c, f"/send/{VALID_API_KEY}")
        assert resp.status_code == 200

    async def test_rate_limit_is_per_api_key(self, client):
        """Exhausting one key must not affect another key."""
        c, _ = client
        other_key = "ffffffff-ffff-ffff-ffff-ffffffffffff"
        other_user = {**ACTIVE_USER, "api_key": other_key}

        def _resolve(key):
            return ACTIVE_USER if key == VALID_API_KEY else other_user

        with patch("app.main.get_user_by_api_key", side_effect=_resolve):
            for _ in range(6):
                await _send(c, f"/send/{VALID_API_KEY}")
            resp = await _send(c, f"/send/{other_key}")
        assert resp.status_code == 200


# ─────────────────────────────────────────────
# Webhook — payload size
# ─────────────────────────────────────────────

class TestWebhookPayloadSize:
    async def test_payload_under_100kb_is_accepted(self, client):
        c, _ = client
        body = "x" * 50_000
        with patch("app.main.get_user_by_api_key", return_value=ACTIVE_USER):
            resp = await _send(c, f"/send/{VALID_API_KEY}", body=body, content_type="text/plain")
        assert resp.status_code == 200

    async def test_payload_over_100kb_returns_413(self, client):
        c, _ = client
        body = "x" * 101_000
        with patch("app.main.get_user_by_api_key", return_value=ACTIVE_USER):
            resp = await _send(c, f"/send/{VALID_API_KEY}", body=body, content_type="text/plain")
        assert resp.status_code == 413

    async def test_empty_body_is_handled_gracefully(self, client):
        c, _ = client
        with patch("app.main.get_user_by_api_key", return_value=ACTIVE_USER):
            resp = await _send(c, f"/send/{VALID_API_KEY}", body="", content_type="text/plain")
        assert resp.status_code == 200


# ─────────────────────────────────────────────
# Webhook — content types
# ─────────────────────────────────────────────

class TestWebhookContentTypes:
    async def test_json_content_type_uses_pre_tag(self, client):
        c, mock_bot = client
        with patch("app.main.get_user_by_api_key", return_value=ACTIVE_USER):
            resp = await _send(
                c, f"/send/{VALID_API_KEY}",
                body='{"event": "deploy", "status": "ok"}',
                content_type="application/json",
            )
        assert resp.status_code == 200
        sent_text = mock_bot.send_message.call_args.kwargs["text"]
        assert "<pre>" in sent_text

    async def test_plain_text_content_type_has_no_pre_tag(self, client):
        c, mock_bot = client
        with patch("app.main.get_user_by_api_key", return_value=ACTIVE_USER):
            resp = await _send(
                c, f"/send/{VALID_API_KEY}",
                body="plain alert message",
                content_type="text/plain",
            )
        assert resp.status_code == 200
        sent_text = mock_bot.send_message.call_args.kwargs["text"]
        assert "<pre>" not in sent_text

    async def test_malformed_json_with_json_content_type_does_not_crash(self, client):
        c, _ = client
        with patch("app.main.get_user_by_api_key", return_value=ACTIVE_USER):
            resp = await _send(
                c, f"/send/{VALID_API_KEY}",
                body="{not valid json",
                content_type="application/json",
            )
        assert resp.status_code == 200


# ─────────────────────────────────────────────
# Webhook — labels
# ─────────────────────────────────────────────

class TestWebhookLabels:
    async def test_single_label_appears_in_telegram_message(self, client):
        c, mock_bot = client
        with patch("app.main.get_user_by_api_key", return_value=ACTIVE_USER):
            resp = await _send(c, f"/send/{VALID_API_KEY}/github")
        assert resp.status_code == 200
        sent_text = mock_bot.send_message.call_args.kwargs["text"]
        assert "github" in sent_text

    async def test_multi_segment_labels_in_telegram_message(self, client):
        c, mock_bot = client
        with patch("app.main.get_user_by_api_key", return_value=ACTIVE_USER):
            resp = await _send(c, f"/send/{VALID_API_KEY}/n8n/prod")
        assert resp.status_code == 200
        sent_text = mock_bot.send_message.call_args.kwargs["text"]
        assert "n8n" in sent_text
        assert "prod" in sent_text

    async def test_labels_are_lowercased(self, client):
        c, mock_bot = client
        with patch("app.main.get_user_by_api_key", return_value=ACTIVE_USER):
            resp = await _send(c, f"/send/{VALID_API_KEY}/GitHub/PROD")
        assert resp.status_code == 200
        sent_text = mock_bot.send_message.call_args.kwargs["text"]
        assert "github" in sent_text
        assert "prod" in sent_text

    async def test_v1_labeled_endpoint_works(self, client):
        c, mock_bot = client
        with patch("app.main.get_user_by_api_key", return_value=ACTIVE_USER):
            resp = await _send(c, f"/v1/user/send/{VALID_API_KEY}/alertmanager/critical")
        assert resp.status_code == 200
        sent_text = mock_bot.send_message.call_args.kwargs["text"]
        assert "alertmanager" in sent_text
        assert "critical" in sent_text


# ─────────────────────────────────────────────
# Webhook — Telegram send failure
# ─────────────────────────────────────────────

class TestWebhookTelegramFailure:
    async def test_telegram_send_failure_returns_500(self, client):
        c, mock_bot = client
        mock_bot.send_message = AsyncMock(side_effect=Exception("Telegram down"))
        with patch("app.main.get_user_by_api_key", return_value=ACTIVE_USER):
            resp = await _send(c, f"/send/{VALID_API_KEY}")
        assert resp.status_code == 500

    async def test_telegram_send_failure_error_message_is_informative(self, client):
        c, mock_bot = client
        mock_bot.send_message = AsyncMock(side_effect=Exception("Telegram down"))
        with patch("app.main.get_user_by_api_key", return_value=ACTIVE_USER):
            resp = await _send(c, f"/send/{VALID_API_KEY}")
        detail = resp.json()["detail"].lower()
        assert "telegram" in detail or "forward" in detail or "message" in detail


# ─────────────────────────────────────────────
# Security
# ─────────────────────────────────────────────

class TestWebhookSecurity:
    async def test_html_in_text_payload_is_escaped(self, client):
        c, mock_bot = client
        malicious = "<script>alert('xss')</script>"
        with patch("app.main.get_user_by_api_key", return_value=ACTIVE_USER):
            await _send(c, f"/send/{VALID_API_KEY}", body=malicious, content_type="text/plain")
        sent_text = mock_bot.send_message.call_args.kwargs["text"]
        assert "<script>" not in sent_text
        assert "&lt;script&gt;" in sent_text

    async def test_html_in_json_value_is_escaped(self, client):
        c, mock_bot = client
        body = '{"key": "<img src=x onerror=alert(1)>"}'
        with patch("app.main.get_user_by_api_key", return_value=ACTIVE_USER):
            await _send(c, f"/send/{VALID_API_KEY}", body=body, content_type="application/json")
        sent_text = mock_bot.send_message.call_args.kwargs["text"]
        assert "<img" not in sent_text

    async def test_chat_id_comes_from_db_not_request(self, client):
        """chat_id must always come from the stored user record, never user-supplied."""
        c, mock_bot = client
        with patch("app.main.get_user_by_api_key", return_value=ACTIVE_USER):
            await _send(c, f"/send/{VALID_API_KEY}")
        assert mock_bot.send_message.call_args.kwargs["chat_id"] == ACTIVE_USER["chat_id"]

    async def test_413_check_happens_before_db_lookup(self, client):
        """Oversized payloads must be rejected before incurring a DB call."""
        c, _ = client
        db_mock = AsyncMock(return_value=ACTIVE_USER)
        with patch("app.main.get_user_by_api_key", db_mock):
            body = "x" * 101_000
            resp = await _send(c, f"/send/{VALID_API_KEY}", body=body, content_type="text/plain")
        assert resp.status_code == 413
        db_mock.assert_not_called()
