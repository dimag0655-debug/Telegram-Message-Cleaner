import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from telethon import errors, types
from PySide6.QtWidgets import QApplication

from workers.runtime import Runtime, LoginConnectionError
from workers.control import Stopped
from telegram_client.safety import SafetyError


async def test_auth_step_has_hard_deadline_and_restores_write_policy():
    runtime = Runtime()
    runtime.client = SimpleNamespace(_request_retries=0)
    cancelled = []
    async def hangs():
        assert runtime.client._request_retries == 2
        try:
            await asyncio.sleep(60)
        finally:
            cancelled.append(True)
    with pytest.raises(LoginConnectionError, match="Проверка"):
        await asyncio.wait_for(runtime._auth_call(hangs, "Проверка", 0.03), 0.5)
    assert cancelled and runtime.client._request_retries == 0


async def test_login_cancel_interrupts_pending_request():
    runtime = Runtime()
    runtime.client = SimpleNamespace(_request_retries=0)
    async def hangs():
        await asyncio.sleep(60)
    task = asyncio.create_task(runtime._auth_call(hangs, "Подключение", 20))
    await asyncio.sleep(0.01)
    runtime.stop()
    with pytest.raises(Stopped):
        await asyncio.wait_for(task, 0.5)
    assert runtime.client._request_retries == 0


async def test_login_network_error_is_specific_and_does_not_leak_request():
    runtime = Runtime()
    async def fails():
        raise ConnectionError("PRIVATE_API_HASH")
    with pytest.raises(LoginConnectionError) as result:
        await runtime._auth_call(fails, "Подключение к Telegram", 20)
    assert "VPN" in str(result.value) and "PRIVATE" not in str(result.value)


async def test_auth_migration_retry_budget_only_applies_during_auth():
    runtime = Runtime()
    runtime.client = SimpleNamespace(_request_retries=0)
    async def response():
        assert runtime.client._request_retries == 2
        return 42
    assert await runtime._auth_call(response, "Проверка", 1) == 42
    assert runtime.client._request_retries == 0


async def test_invalid_code_keeps_connection_for_correction():
    runtime = Runtime()
    runtime.client = SimpleNamespace(_request_retries=0, disconnect=AsyncMock(),
                                     sign_in=AsyncMock(side_effect=errors.PhoneCodeInvalidError(None)))
    runtime.phone, runtime.phone_code_hash = "+79991234567", "MOCK"
    await runtime._dispatch("code", "12345")
    runtime.client.disconnect.assert_not_awaited()
    assert runtime.client._request_retries == 0


async def test_flood_wait_prevents_repeated_code_requests(monkeypatch):
    runtime = Runtime()
    runtime._code = AsyncMock(side_effect=errors.FloodWaitError(None, capture=60))
    await runtime._dispatch("code", "12345")
    assert runtime.login_allowed_at > asyncio.get_running_loop().time()
    created = []
    monkeypatch.setattr("workers.runtime.TelegramClient", lambda *a, **kw: created.append(a))
    with pytest.raises(SafetyError, match="ограничил"):
        await runtime._connect("12345", "a" * 32, "+79991234567")
    assert not created


async def test_network_probe_requires_no_credentials_and_closes_socket(monkeypatch):
    runtime = Runtime()
    writer = SimpleNamespace(close=lambda: None, wait_closed=AsyncMock())
    connect = AsyncMock(return_value=(None, writer))
    monkeypatch.setattr("workers.runtime.asyncio.open_connection", connect)
    assert await runtime._network() is True
    connect.assert_awaited_once()
    assert connect.call_args.args[1] == 443 and runtime.client is None
    writer.wait_closed.assert_awaited_once()


def test_login_statuses_visible_and_cancel_present(monkeypatch, tmp_path):
    from ui.window import MainWindow
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    app = QApplication.instance() or QApplication([])
    window = MainWindow(start_worker=False)
    window.on_event("auth_progress", ("Запрос кода", 25))
    assert "Запрос кода" in window.auth_status.text() and "25" in window.auth_status.text()
    window.busy = True
    window._update_actions()
    assert window.auth_cancel.isEnabled()
    window.stop()
    assert not window.auth_clock.isActive() and "Прерывание" in window.auth_status.text()
    window.on_event("auth_status", "Вход прерван.")
    window.on_event("idle", "connect")
    assert window.auth_status.text() == "Вход прерван."
    window.close()


def test_connection_test_enabled_on_first_start(monkeypatch, tmp_path):
    from ui.window import MainWindow
    from PySide6.QtTest import QTest
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    app = QApplication.instance() or QApplication([])
    window = MainWindow(start_worker=True)
    try:
        for _ in range(100):
            app.processEvents()
            if window.network_button.isEnabled():
                break
            QTest.qWait(10)
        assert window.network_button.isEnabled() and window.connect_button.isEnabled()
    finally:
        window.close()
        for _ in range(100):
            app.processEvents()
            if not window.runtime.isRunning():
                break
            QTest.qWait(10)
        assert not window.runtime.isRunning()
