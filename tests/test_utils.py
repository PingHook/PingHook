"""
Unit tests for app/utils.py — format_message and is_rate_limited.
No external dependencies; all logic is pure Python.
"""
import time
import pytest
from unittest.mock import patch

from app.utils import format_message, is_rate_limited, _rate_limit_store, RATE_LIMIT_REQUESTS


# ─────────────────────────────────────────────
# format_message — happy paths
# ─────────────────────────────────────────────

class TestFormatMessageHappyPaths:
    def test_none_payload_returns_empty_message(self):
        result = format_message(None)
        assert "empty payload" in result.lower()

    def test_string_payload_renders_header(self):
        result = format_message("hello world")
        assert "New Webhook Received" in result
        assert "hello world" in result

    def test_dict_payload_renders_json_in_pre_tag(self):
        result = format_message({"event": "push", "repo": "my-repo"})
        assert "<pre>" in result
        assert "push" in result
        assert "my-repo" in result

    def test_labels_render_source_header(self):
        result = format_message({"x": 1}, labels=["github", "prod"])
        assert "Source:" in result
        assert "github" in result
        assert "prod" in result

    def test_single_label(self):
        result = format_message("ping", labels=["n8n"])
        assert "n8n" in result

    def test_no_labels_no_source_header(self):
        result = format_message("ping")
        assert "Source:" not in result

    def test_empty_labels_list_treated_as_no_labels(self):
        result = format_message("ping", labels=[])
        assert "Source:" not in result


# ─────────────────────────────────────────────
# format_message — security (HTML escaping)
# ─────────────────────────────────────────────

class TestFormatMessageSecurity:
    def test_html_injection_in_string_payload_is_escaped(self):
        result = format_message("<script>alert('xss')</script>")
        assert "<script>" not in result
        assert "&lt;script&gt;" in result

    def test_html_injection_in_dict_value_is_escaped(self):
        result = format_message({"key": "<b>injected</b>"})
        assert "<b>injected</b>" not in result
        assert "&lt;b&gt;" in result

    def test_html_injection_in_dict_key_is_escaped(self):
        result = format_message({"<img src=x onerror=alert(1)>": "value"})
        assert "<img" not in result

    def test_ampersand_in_payload_is_escaped(self):
        result = format_message("a & b")
        assert "&amp;" in result
        assert "a & b" not in result

    def test_quotes_in_string_payload_are_escaped(self):
        result = format_message('"quoted"')
        assert "&quot;" in result or "&#x27;" in result or '"quoted"' not in result.split("<pre>")[0]
        # Acceptable: html.escape escapes < > & " '


# ─────────────────────────────────────────────
# format_message — truncation
# ─────────────────────────────────────────────

class TestFormatMessageTruncation:
    def test_message_under_3000_chars_is_not_truncated(self):
        result = format_message("a" * 100)
        assert "[message truncated]" not in result

    def test_message_over_3000_chars_is_truncated(self):
        result = format_message("a" * 5000)
        assert "[message truncated]" in result

    def test_truncated_message_does_not_exceed_safe_length(self):
        result = format_message("a" * 10_000)
        # Must stay well under Telegram's 4096-char limit
        assert len(result) < 4096

    def test_exact_3000_chars_not_truncated(self):
        # format_message wraps content in a header; the 3000-char limit applies
        # to the _truncate call's input. Build a string that sits just at the boundary.
        result = format_message("b" * 2950)  # header adds ~30 chars; total < 3000
        assert "[message truncated]" not in result


# ─────────────────────────────────────────────
# format_message — edge / unsupported types
# ─────────────────────────────────────────────

class TestFormatMessageEdgeCases:
    def test_list_payload_returns_unsupported_message(self):
        result = format_message([1, 2, 3])  # type: ignore[arg-type]
        assert "Unsupported" in result

    def test_integer_payload_returns_unsupported_message(self):
        result = format_message(42)  # type: ignore[arg-type]
        assert "Unsupported" in result

    def test_empty_string_payload(self):
        result = format_message("")
        # Empty string is still a string — should render (no crash)
        assert isinstance(result, str)

    def test_empty_dict_payload(self):
        result = format_message({})
        assert "<pre>" in result  # dict branch

    def test_unicode_in_dict_payload_renders_correctly(self):
        result = format_message({"emoji": "🚀", "arabic": "مرحبا"})
        assert "🚀" in result
        assert "مرحبا" in result

    def test_unicode_in_string_payload_renders_correctly(self):
        result = format_message("🚀 مرحبا")
        assert "🚀" in result

    def test_nested_dict_payload_renders_all_levels(self):
        result = format_message({"outer": {"inner": "value"}})
        assert "outer" in result
        assert "inner" in result


# ─────────────────────────────────────────────
# is_rate_limited
# ─────────────────────────────────────────────

class TestRateLimiter:
    def setup_method(self):
        """Clear store before each test for isolation."""
        _rate_limit_store.clear()

    def test_first_request_is_not_limited(self):
        assert is_rate_limited("key-1") is False

    def test_requests_up_to_limit_are_not_limited(self):
        for _ in range(RATE_LIMIT_REQUESTS):
            assert is_rate_limited("key-2") is False

    def test_request_over_limit_is_limited(self):
        for _ in range(RATE_LIMIT_REQUESTS):
            is_rate_limited("key-3")
        assert is_rate_limited("key-3") is True

    def test_different_keys_are_independent(self):
        for _ in range(RATE_LIMIT_REQUESTS):
            is_rate_limited("key-a")
        # key-a is exhausted; key-b should still be free
        assert is_rate_limited("key-b") is False

    def test_window_reset_allows_new_requests(self):
        for _ in range(RATE_LIMIT_REQUESTS):
            is_rate_limited("key-reset")
        assert is_rate_limited("key-reset") is True  # over limit

        # Simulate time advancing past the 60-second window
        future_time = int(time.time()) + 61
        with patch("app.utils.time.time", return_value=future_time):
            assert is_rate_limited("key-reset") is False

    def test_counter_increments_within_window(self):
        is_rate_limited("key-count")
        _, count = _rate_limit_store["key-count"]
        assert count == 1

        is_rate_limited("key-count")
        _, count = _rate_limit_store["key-count"]
        assert count == 2
