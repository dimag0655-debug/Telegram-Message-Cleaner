import os
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from telethon import types, utils

from telegram_client.engine import Engine
from telegram_client.models import Group, Confirmation
from workers.control import Control

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
NOW = datetime(2026, 10, 31, 12, tzinfo=timezone.utc)
OWNER = 7123


def chat(id=41, title="Тестовая группа"):
    return types.Chat(id, title, types.ChatPhotoEmpty(), 4, NOW, 1)


def channel(id=91, megagroup=True):
    return types.Channel(id, "Супергруппа", types.ChatPhotoEmpty(), NOW,
                         megagroup=megagroup, broadcast=not megagroup, access_hash=123)


def message(id=1, owner=OWNER, peer=None, date=NOW, **kwargs):
    return types.Message(id, peer or types.PeerChat(41), date=date,
                         from_id=types.PeerUser(owner) if owner is not None else None,
                         message="Тестовое собственное сообщение", **kwargs)


class FastControl(Control):
    def __init__(self):
        super().__init__()
        self.sleeps = []

    async def sleep(self, seconds):
        self.check()
        self.sleeps.append(seconds)


class FakeClient:
    """No real sockets. All write calls assert author and exact peer independently."""
    def __init__(self, count=20, entity=None):
        self.entity = entity or chat()
        self.peer = utils.get_peer(self.entity)
        self.owner = OWNER
        self.count = count
        self.removed = set()
        self.overrides = {}
        self.requests = []
        self.page_calls = 0
        self.id_calls = 0
        self.get_me_calls = 0
        self.delete_errors = []
        self.read_errors = []
        self.commit_then_timeout = False
        self.no_effect = False
        self.no_ack = False
        self.truncate_after = False
        self.on_delete = None

    def make(self, mid):
        if mid in self.removed:
            return None
        return self.overrides.get(mid, message(mid, peer=self.peer, date=NOW - timedelta(seconds=self.count-mid)))

    async def get_me(self):
        self.get_me_calls += 1
        return types.User(self.owner, is_self=True)

    async def get_entity(self, entity):
        return self.entity

    async def get_messages(self, entity, ids=None, limit=100, offset_id=0, offset_date=None):
        if self.read_errors:
            raise self.read_errors.pop(0)
        if ids is not None:
            self.id_calls += 1
            if self.truncate_after and self.requests:
                return []
            return [self.make(mid) for mid in ids]
        self.page_calls += 1
        top = min(self.count, offset_id-1) if offset_id else self.count
        return [self.make(mid) for mid in range(top, max(0, top-limit), -1) if mid not in self.removed]

    async def delete_messages(self, entity, ids, revoke):
        assert revoke is True
        assert 1 <= len(ids) <= 100
        assert utils.get_peer_id(entity) == utils.get_peer_id(self.entity)
        for mid in ids:
            m = self.make(mid)
            assert m is not None
            assert isinstance(m.from_id, types.PeerUser) and m.from_id.user_id == self.owner
            assert utils.get_peer_id(m.peer_id) == utils.get_peer_id(entity)
            assert m.action is None
        self.requests.append(tuple(ids))
        if self.on_delete:
            self.on_delete()
        if self.delete_errors:
            raise self.delete_errors.pop(0)
        if not self.no_effect:
            self.removed.update(ids)
        if self.commit_then_timeout:
            self.commit_then_timeout = False
            raise TimeoutError("lost response")
        return [] if self.no_ack else [types.messages.AffectedMessages(1, len(ids))]


def confirmation(scan, word="УДАЛИТЬ"):
    return Confirmation(scan.token, scan.group.id, scan.owner_id, len(scan.ids), word)


@pytest.fixture
def factory():
    def create(count=20, entity=None, emit=lambda *args: None):
        client = FakeClient(count, entity)
        engine = Engine(client, emit=emit, control=FastControl())
        group = Group(utils.get_peer_id(client.entity), client.entity.title, client.entity)
        return client, engine, group
    return create
