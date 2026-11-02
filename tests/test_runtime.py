import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from telethon import errors, types
from PySide6.QtWidgets import QApplication
from PySide6.QtTest import QTest

from workers.runtime import Runtime


async def test_auth_code_two_factor_and_logout_are_offline(monkeypatch, tmp_path):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    client = SimpleNamespace(
        session=SimpleNamespace(save_entities=True),
        connect=AsyncMock(), disconnect=AsyncMock(),
        is_user_authorized=AsyncMock(return_value=False),
        send_code_request=AsyncMock(return_value=types.auth.SentCode(types.auth.SentCodeTypeApp(5), "MOCK_HASH")),
        sign_in=AsyncMock(side_effect=[errors.SessionPasswordNeededError(None), types.User(42, is_self=True)]),
        get_me=AsyncMock(return_value=types.User(42, is_self=True)), log_out=AsyncMock(return_value=True),
    )
    calls = []
    def create(*args, **kwargs):
        calls.append((args, kwargs))
        return client
    monkeypatch.setattr("workers.runtime.TelegramClient", create)
    r = Runtime()
    assert await r._connect("12345", "a" * 32, "+79991234567") is None
    assert not client.session.save_entities
    assert str(tmp_path) in calls[0][0][0]
    assert calls[0][1]["flood_sleep_threshold"] == 0
    assert calls[0][1]["request_retries"] == 0
    with pytest.raises(errors.SessionPasswordNeededError):
        await r._code("12345")
    assert await r._password("MOCK_PASSWORD") == 42
    assert client._request_retries == 0
    assert r.phone is None and r.phone_code_hash is None
    assert await r._logout() is True and r.client is None


async def test_invalid_credentials_never_connect(monkeypatch):
    created = []
    monkeypatch.setattr("workers.runtime.TelegramClient", lambda *a, **kw: created.append(a))
    r = Runtime()
    with pytest.raises(Exception):
        await r._connect("not-an-id", "secret", "not-a-phone")
    assert not created


def test_real_qthread_loop_runs_and_closes_without_network():
    app = QApplication.instance() or QApplication([])
    runtime = Runtime()
    received = []
    runtime.event.connect(lambda kind, value: received.append((kind, value)))
    runtime.start()
    for _ in range(100):
        if runtime.loop:
            break
        QTest.qWait(10)
    assert runtime.loop is not None
    async def offline():
        await asyncio.sleep(0.01)
        return 42
    runtime._offline = offline
    assert runtime.submit("offline")
    for _ in range(100):
        app.processEvents()
        if ("result", ("offline", 42)) in received:
            break
        QTest.qWait(10)
    assert ("result", ("offline", 42)) in received
    runtime.shutdown()
    assert runtime.wait(3000)
