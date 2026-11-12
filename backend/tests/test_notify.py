import logging

import httpx
import pytest

from app.config import get_settings
from app.services import notify


@pytest.mark.parametrize("failure", [None, "status", "connection"])
async def test_telegram_token_is_not_logged(monkeypatch, caplog, failure):
    token = "123456:TEST_SECRET_TOKEN"
    monkeypatch.setattr(get_settings(), "telegram_bot_token", token)
    original_client = httpx.AsyncClient

    def handler(request):
        if failure == "connection":
            raise httpx.ConnectError(f"Cannot connect to {request.url}", request=request)
        return httpx.Response(500 if failure else 200, json={"ok": not failure})

    monkeypatch.setattr(
        notify.httpx, "AsyncClient",
        lambda **kwargs: original_client(transport=httpx.MockTransport(handler), **kwargs),
    )
    with caplog.at_level(logging.INFO):
        assert await notify.send_message(1, "Test") is (failure is None)
    assert token not in caplog.text
    if failure:
        assert "failed to send telegram message" in caplog.text
