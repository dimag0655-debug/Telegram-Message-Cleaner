import asyncio
from dataclasses import replace
from datetime import timedelta
from types import SimpleNamespace

import pytest
from telethon import errors, types, utils

from conftest import OWNER, NOW, message, chat, channel, confirmation, FastControl
from telegram_client.models import DateRange, Group, ScanResult
from telegram_client.safety import own_message, SafetyError
from workers.control import Control, Stopped


async def test_own_id_comes_from_get_me(factory):
    c, e, group = factory()
    result = await e.scan(group, DateRange())
    assert result.owner_id == OWNER and c.get_me_calls == 1
    assert c.requests == []


@pytest.mark.parametrize("bad", [None, types.User(7), types.User(7, is_self=True, bot=True)])
async def test_unconfirmed_account_never_scans(factory, bad):
    c, e, group = factory()
    async def get_me():
        return bad
    c.get_me = get_me
    with pytest.raises(SafetyError):
        await e.scan(group, DateRange())
    assert not c.requests


async def test_foreign_unknown_service_anonymous_private_and_other_group_excluded(factory):
    c, e, group = factory(count=9)
    c.overrides = {
        1: message(1, owner=999),
        2: message(2, owner=None, out=True),
        3: message(3, peer=types.PeerChat(42)),
        4: message(4, peer=types.PeerUser(OWNER)),
        5: message(5, action=types.MessageActionHistoryClear()),
        6: types.Message(6, types.PeerChat(41), date=NOW, from_id=types.PeerChannel(41), out=True),
        7: types.MessageEmpty(7, types.PeerChat(41)),
        8: message(8, owner=999, out=True, fwd_from=types.MessageFwdHeader(NOW, from_id=types.PeerUser(OWNER))),
    }
    scan = await e.scan(group, DateRange())
    assert scan.ids == (9,)
    report = await e.delete(scan, confirmation(scan), group.id)
    assert c.requests == [(9,)] and report.deleted == 1


@pytest.mark.parametrize("count", [1000, 10000, 100001])
async def test_large_history_paged_and_batched(factory, count):
    c, e, group = factory(count=count)
    scan = await e.scan(group, DateRange())
    assert len(scan.ids) == count and len(set(scan.ids)) == count
    assert len(scan.preview) == 50 and scan.examined == count
    report = await e.delete(scan, confirmation(scan), group.id)
    assert report.deleted == count and report.processed == count
    assert report.errors == report.unconfirmed == report.skipped == 0
    assert len(c.requests) == (count + 99) // 100


@pytest.mark.parametrize("entity", [channel(), chat()])
async def test_basic_and_supergroup(factory, entity):
    c, e, group = factory(entity=entity)
    scan = await e.scan(group, DateRange())
    report = await e.delete(scan, confirmation(scan), group.id)
    assert report.deleted == 20


async def test_fresh_author_and_peer_checked_before_delete(factory):
    c, e, group = factory(count=5)
    scan = await e.scan(group, DateRange())
    c.overrides[1] = message(1, owner=8)
    c.overrides[2] = message(2, peer=types.PeerChat(999))
    c.overrides[3] = message(3, action=types.MessageActionHistoryClear())
    report = await e.delete(scan, confirmation(scan), group.id)
    assert c.requests == [(5, 4)] and report.deleted == 2 and report.skipped == 3


async def test_flood_wait_then_rechecks_ownership(factory):
    c, e, group = factory(count=2)
    scan = await e.scan(group, DateRange())
    c.delete_errors = [errors.FloodWaitError(None, capture=7)]
    def change_author():
        if len(c.requests) == 1:
            c.overrides[1] = message(1, owner=22)
    c.on_delete = change_author
    report = await e.delete(scan, confirmation(scan), group.id)
    assert c.requests == [(2, 1), (2,)]
    assert 7 in e.control.sleeps and report.deleted == 1 and report.skipped == 1


async def test_flood_wait_is_bounded(factory):
    c, e, group = factory(count=1)
    scan = await e.scan(group, DateRange())
    c.delete_errors = [errors.FloodWaitError(None, capture=1) for _ in range(10)]
    report = await e.delete(scan, confirmation(scan), group.id)
    assert len(c.requests) == 4 and report.errors == 1 and report.deleted == 0


async def test_network_errors_are_bounded_and_retried(factory):
    c, e, group = factory(count=1)
    c.read_errors = [ConnectionError("secret data"), TimeoutError("secret")]
    scan = await e.scan(group, DateRange())
    c.delete_errors = [ConnectionError("secret")]
    report = await e.delete(scan, confirmation(scan), group.id)
    assert report.deleted == 1 and len(c.requests) == 2


async def test_permanent_network_error_never_deletes(factory):
    c, e, group = factory()
    c.read_errors = [ConnectionError() for _ in range(8)]
    with pytest.raises(ConnectionError):
        await e.scan(group, DateRange())
    assert len(c.read_errors) == 4 and not c.requests


async def test_lost_ack_is_not_reported_as_confirmed(factory):
    c, e, group = factory(count=3)
    scan = await e.scan(group, DateRange())
    c.commit_then_timeout = True
    report = await e.delete(scan, confirmation(scan), group.id)
    assert report.deleted == 0 and report.unconfirmed == 3 and report.processed == 3
    assert len(c.requests) == 1


@pytest.mark.parametrize("mode,deleted,errors_count,unknown", [
    ("no_ack", 0, 0, 4), ("no_effect", 0, 4, 0), ("truncate_after", 0, 0, 4)])
async def test_response_alone_is_not_success(factory, mode, deleted, errors_count, unknown):
    c, e, group = factory(count=4)
    scan = await e.scan(group, DateRange())
    setattr(c, mode, True)
    report = await e.delete(scan, confirmation(scan), group.id)
    assert (report.deleted, report.errors, report.unconfirmed) == (deleted, errors_count, unknown)


async def test_stop_before_delete(factory):
    c, e, group = factory()
    scan = await e.scan(group, DateRange())
    e.control.stop()
    report = await e.delete(scan, confirmation(scan), group.id)
    assert report.stopped and report.processed == 0 and not c.requests


async def test_stop_after_first_batch_never_sends_next(factory):
    c, e, group = factory(count=250)
    scan = await e.scan(group, DateRange())
    c.on_delete = e.control.stop
    report = await e.delete(scan, confirmation(scan), group.id)
    assert len(c.requests) == 1 and report.processed == 100 and report.stopped
    assert report.unconfirmed == 100


async def test_stop_interrupts_flood_wait():
    control = Control()
    task = asyncio.create_task(control.sleep(99999))
    await asyncio.sleep(0.01)
    control.stop()
    with pytest.raises(Stopped):
        await asyncio.wait_for(task, 0.5)


@pytest.mark.parametrize("word", ["", "удалить", "DELETE", " УДАЛИТЬ", "УДАЛИТЬ "])
async def test_exact_confirmation_required(factory, word):
    c, e, group = factory()
    scan = await e.scan(group, DateRange())
    with pytest.raises(SafetyError):
        await e.delete(scan, confirmation(scan, word), group.id)
    assert not c.requests


@pytest.mark.parametrize("field,value", [("token", "wrong"), ("group_id", -99), ("owner_id", 999), ("count", 999)])
async def test_confirmation_bound_to_scan(factory, field, value):
    c, e, group = factory()
    scan = await e.scan(group, DateRange())
    with pytest.raises(SafetyError):
        await e.delete(scan, replace(confirmation(scan), **{field: value}), group.id)
    assert not c.requests


async def test_changed_selection_or_group_or_account_never_deletes(factory):
    for change in ("selection", "group", "account"):
        c, e, group = factory()
        scan = await e.scan(group, DateRange())
        selected = -88 if change == "selection" else group.id
        if change == "group":
            c.entity = chat(88)
        if change == "account":
            c.owner = 999
        try:
            report = await e.delete(scan, confirmation(scan), selected)
            assert report.failure and report.deleted == 0
        except SafetyError:
            pass
        assert not c.requests


async def test_forged_stale_reused_scan_never_authorizes(factory):
    c, e, group = factory()
    scan = await e.scan(group, DateRange())
    forged = replace(scan, ids=(999,))
    with pytest.raises(SafetyError):
        await e.delete(forged, confirmation(forged), group.id)
    newer = await e.scan(group, DateRange())
    with pytest.raises(SafetyError):
        await e.delete(scan, confirmation(scan), group.id)
    await e.delete(newer, confirmation(newer), group.id)
    with pytest.raises(SafetyError):
        await e.delete(newer, confirmation(newer), group.id)


async def test_date_filter_applies_again_at_delete(factory):
    c, e, group = factory(count=10)
    dates = DateRange(NOW - timedelta(seconds=4), NOW + timedelta(seconds=1))
    scan = await e.scan(group, dates)
    assert set(scan.ids) == {6, 7, 8, 9, 10}
    c.overrides[7] = message(7, date=NOW-timedelta(days=2))
    report = await e.delete(scan, confirmation(scan), group.id)
    assert report.deleted == 4 and report.skipped == 1


@pytest.mark.parametrize("entity", [channel(megagroup=False), types.User(77), chat(99)])
async def test_wrong_entity_rejected(factory, entity):
    c, e, group = factory()
    c.entity = entity
    with pytest.raises(SafetyError):
        await e.scan(group, DateRange())
    assert not c.requests


async def test_history_unavailable_never_authorizes_partial_scan(factory):
    c, e, group = factory()
    c.read_errors = [errors.ChannelPrivateError(None)]
    with pytest.raises(errors.ChannelPrivateError):
        await e.scan(group, DateRange())
    assert not e._scans and not c.requests


async def test_scan_stop_returns_incomplete_and_no_authorization(factory):
    c, e, group = factory(count=200)
    e.emit = lambda *args: e.control.stop()
    scan = await e.scan(group, DateRange())
    assert not scan.complete and not e._scans and not c.requests


async def test_repeated_history_page_rejected(factory):
    c, e, group = factory()
    async def repeated(*args, **kwargs):
        return [message(1)]
    c.get_messages = repeated
    with pytest.raises(SafetyError):
        await e.scan(group, DateRange())
    assert not e._scans


async def test_group_listing_filters_private_channels_left_and_archived(factory):
    c, e, group = factory()
    left = chat(77)
    left.left = True
    entities = [chat(), channel(), channel(92, False), types.User(6), left]
    async def get_dialogs(**kwargs):
        return [SimpleNamespace(entity=value) for value in entities]
    c.get_dialogs = get_dialogs
    groups = await e.groups()
    assert {g.id for g in groups} == {-41, -1000000000091}


async def test_unknown_write_failure_is_unconfirmed(factory):
    c, e, group = factory(count=2)
    scan = await e.scan(group, DateRange())
    c.delete_errors = [ValueError("ambiguous response")]
    report = await e.delete(scan, confirmation(scan), group.id)
    assert report.unconfirmed == 2 and report.deleted == 0


async def test_explicit_rpc_rejection_is_error(factory):
    c, e, group = factory(count=2)
    scan = await e.scan(group, DateRange())
    c.delete_errors = [errors.MessageDeleteForbiddenError(None)]
    report = await e.delete(scan, confirmation(scan), group.id)
    assert report.errors == 2 and report.deleted == 0


async def test_account_changes_between_batches_stops_next_write(factory):
    c, e, group = factory(count=200)
    scan = await e.scan(group, DateRange())
    c.on_delete = lambda: setattr(c, "owner", 999)
    report = await e.delete(scan, confirmation(scan), group.id)
    assert len(c.requests) == 1 and report.failure
    assert report.processed == 100


async def test_group_pagination_includes_more_than_one_page(factory):
    c, e, _ = factory()
    offsets = []
    async def pages(**kwargs):
        offsets.append(kwargs)
        start, stop = (1, 101) if kwargs["offset_id"] == 0 else (101, 116)
        return [SimpleNamespace(entity=chat(i), date=NOW-timedelta(seconds=i),
                                message=SimpleNamespace(id=i), input_entity=types.InputPeerChat(i))
                for i in range(start, stop)]
    c.get_dialogs = pages
    groups = await e.groups()
    assert len(groups) == 115
    assert offsets[1]["offset_id"] == 100 and offsets[1]["ignore_pinned"] is True
