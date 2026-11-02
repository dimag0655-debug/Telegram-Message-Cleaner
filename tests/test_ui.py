import json
from datetime import datetime, timezone

import pytest
from PySide6.QtWidgets import QApplication, QDialog
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest

from conftest import chat, OWNER
from telegram_client.models import Group, ScanResult, DateRange
from telegram_client.engine import friendly_error
from ui.window import MainWindow, ConfirmDialog
from utils.settings import write_settings, read_settings


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def window(app, monkeypatch, tmp_path):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    w = MainWindow(start_worker=False)
    yield w
    w.close()


def test_confirmation_dialog_requires_manual_exact_text(app):
    scan = ScanResult(Group(-41, "Группа", chat()), OWNER, DateRange(), (1, 2), 2)
    dialog = ConfirmDialog(scan)
    assert not dialog.delete_button.isEnabled()
    for word in ("удалить", "УДАЛИТЬ ", "DELETE"):
        dialog.word.setText(word)
        assert not dialog.delete_button.isEnabled()
        dialog.accept()
        assert dialog.result() != QDialog.DialogCode.Accepted
    dialog.word.clear()
    for char in "УДАЛИТЬ":
        dialog.word.insert(char)
    assert dialog.delete_button.isEnabled()
    dialog.accept()
    assert dialog.result() == QDialog.DialogCode.Accepted


def test_scan_only_default_and_invalidation_on_selection_dates(window):
    window.demo = False
    groups = [Group(-41, "Первая", chat()), Group(-42, "Вторая", chat(42))]
    window._result("groups", groups)
    window.groups_list.setCurrentRow(0)
    scan = ScanResult(groups[0], OWNER, DateRange(), (1,), 9)
    window._result("scan", scan)
    window._update_actions()
    assert window.preview_only.isChecked() and not window.delete_button.isEnabled()
    window.preview_only.setChecked(False)
    assert window.delete_button.isEnabled()
    window.all_dates.setChecked(False)
    assert window.scan_result is None and not window.delete_button.isEnabled()
    window._result("scan", scan)
    window.groups_list.setCurrentRow(1)
    assert window.scan_result is None and not window.delete_button.isEnabled()


def test_search_never_keeps_hidden_selection(window):
    window._result("groups", [Group(-41, "Alpha", chat()), Group(-42, "Beta", chat(42))])
    window.groups_list.setCurrentRow(0)
    window.search.setText("Beta")
    assert window.group() is None and window.groups_list.item(0).isHidden()


def test_inclusive_local_dates(window):
    window.all_dates.setChecked(False)
    window.date_start.setDate(window.date_end.date())
    dates = window.dates()
    assert dates.start.tzinfo and dates.end.tzinfo
    assert dates.contains(dates.start)
    assert not dates.contains(dates.end)


def test_safe_settings_only_whitelisted(monkeypatch, tmp_path):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    write_settings(1200, 900, 1.2)
    assert read_settings() == {"width": 1200, "height": 900, "delay": 1.2}
    path = tmp_path / "TelegramMessageCleaner" / "settings.json"
    path.write_text('{"width":1200,"api_hash":"SECRET","phone":"SECRET"}', encoding="utf-8")
    assert read_settings() == {"width": 1200}


def test_error_text_never_contains_raw_private_request():
    for exc in (RuntimeError("SECRET_API_HASH OTP password"), ConnectionError("PRIVATE SESSION")):
        assert "SECRET" not in friendly_error(exc) and "PRIVATE" not in friendly_error(exc)


@pytest.mark.parametrize("payload", ['[]', '{"width":"bad","height":null,"delay":NaN}', 'not-json'])
def test_corrupted_settings_do_not_break_startup(monkeypatch, tmp_path, payload):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    target = tmp_path / "TelegramMessageCleaner"
    target.mkdir()
    (target / "settings.json").write_text(payload, encoding="utf-8")
    assert read_settings() == {}
