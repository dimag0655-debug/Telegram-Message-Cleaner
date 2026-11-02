"""All destructive calls live here. Every retry re-reads author and peer.

For basic groups Telegram's deleteMessages ignores the entity argument, so the
explicit peer check on the *fresh* getMessages result is a critical boundary.
"""
import asyncio
from datetime import datetime

from telethon import errors, types, utils

from telegram_client.models import Group, ScanResult, DeleteReport, UTC
from telegram_client.safety import SafetyError, validate_group, own_message, is_group
from workers.control import Control, Stopped

TRANSIENT = (OSError, ConnectionError, asyncio.TimeoutError, errors.ServerError)


class Engine:
    def __init__(self, client, emit=lambda kind, value: None, delay=1.0, control=None):
        self.client = client
        self.emit = emit
        self.delay = max(0.2, min(float(delay), 60.0))
        self.control = control or Control()
        self._next_call = 0.0
        self._scans = {}  # only results minted by this engine may authorize deletion

    async def call(self, factory):
        for attempt in range(4):
            self.control.check()
            loop = asyncio.get_running_loop()
            await self.control.sleep(max(0, self._next_call - loop.time()))
            self._next_call = loop.time() + self.delay
            try:
                return await asyncio.wait_for(factory(), timeout=45)
            except errors.FloodWaitError as exc:
                if attempt == 3:
                    raise
                self.emit("log", f"Telegram: ожидание {exc.seconds} с. Можно остановить операцию.")
                await self.control.sleep(exc.seconds)
            except TRANSIENT:
                if attempt == 3:
                    raise
                self.emit("log", f"Временный сетевой сбой. Повтор {attempt + 1}/3.")
                await self.control.sleep(min(2 ** attempt, 8))

    async def me(self):
        me = await self.call(lambda: self.client.get_me())
        if not isinstance(me, types.User) or not me.is_self or me.bot or not me.id:
            raise SafetyError("Не удалось подтвердить ID пользовательского аккаунта.")
        return me.id

    async def group(self, group):
        entity = await self.call(lambda: self.client.get_entity(group.entity))
        return validate_group(entity, group.id)

    async def groups(self):
        # Folder=None includes archived dialogs as well. Paging is bounded by Telegram.
        found, offset_date, offset_id, offset_peer = {}, None, 0, types.InputPeerEmpty()
        while True:
            page = await self.call(lambda: self.client.get_dialogs(
                limit=100, offset_date=offset_date, offset_id=offset_id, offset_peer=offset_peer,
                ignore_pinned=bool(offset_date or offset_id)))
            for dialog in page:
                if is_group(dialog.entity):
                    entity = dialog.entity
                    found[utils.get_peer_id(entity)] = Group(utils.get_peer_id(entity), entity.title, entity)
            if len(page) < 100:
                break
            last = page[-1]
            new_offset = (last.date, last.message.id if last.message else 0, last.input_entity)
            if new_offset[:2] == (offset_date, offset_id):
                raise SafetyError("Список групп не удалось прочитать полностью. Повторите загрузку.")
            offset_date, offset_id, offset_peer = new_offset
        return sorted(found.values(), key=lambda group: group.title.casefold())

    async def scan(self, group, dates):
        self._scans.clear()
        owner = await self.me()
        entity = await self.group(group)
        ids, seen, preview, examined, offset, complete = [], set(), [], 0, 0, True
        try:
            while True:
                page = await self.call(lambda: self.client.get_messages(
                    entity, limit=100, offset_id=offset, offset_date=dates.end))
                if not page:
                    break
                positive = [m.id for m in page if type(getattr(m, "id", None)) is int and m.id > 0]
                if not positive:
                    raise SafetyError("История не содержит корректных идентификаторов.")
                new_offset = min(positive)
                if offset and new_offset >= offset:
                    raise SafetyError("Telegram вернул повторную страницу истории. Сканирование прервано.")
                older = False
                for message in page:
                    self.control.check()
                    examined += 1
                    date = getattr(message, "date", None)
                    if dates.start and date and date.tzinfo and date < dates.start:
                        older = True
                        continue
                    if own_message(message, owner, group.id, dates) and message.id not in seen:
                        seen.add(message.id)
                        ids.append(message.id)
                        if len(preview) < 50:
                            text = " ".join((message.message or "[медиа без текста]").split())[:180]
                            preview.append((message.id, message.date.astimezone().strftime("%d.%m.%Y %H:%M"), text))
                self.emit("scan_progress", (examined, len(ids)))
                offset = new_offset
                if older:
                    break
        except Stopped:
            complete = False
        result = ScanResult(group, owner, dates, tuple(ids), examined, tuple(preview), complete)
        if complete:
            self._scans[result.token] = result
        return result

    async def delete(self, scan, confirmation, selected_group_id):
        if (not confirmation.matches(scan) or selected_group_id != scan.group.id or
                self._scans.get(scan.token) is not scan):
            raise SafetyError("Подтверждение не соответствует завершённому сканированию выбранной группы.")
        self._scans.pop(scan.token)  # one-use authorization, even on failure or Stop
        report = DeleteReport(scan.group.title, scan.group.id, scan.dates.label(), len(scan.ids))
        try:
            for index in range(0, len(scan.ids), 100):
                self.control.check()
                batch = scan.ids[index:index + 100]
                # Revalidate on EVERY write attempt, including after a FloodWait/network retry.
                outcome = await self._delete_batch(scan, batch)
                report.deleted += outcome[0]
                report.skipped += outcome[1]
                report.errors += outcome[2]
                report.unconfirmed += outcome[3]
                report.processed += len(batch)
                self.emit("delete_progress", report)
        except Stopped:
            report.stopped = True
        except Exception as exc:
            report.failure = friendly_error(exc)
            self.emit("log", report.failure)
        finally:
            report.stopped = report.stopped or self.control.event.is_set()
            report.finished = datetime.now(UTC)
        return report

    async def _delete_batch(self, scan, batch):
        states = {mid: "skipped" for mid in batch}
        uncertain = set()
        for attempt in range(4):
            try:
                self.control.check()
                if await self.me() != scan.owner_id:
                    raise SafetyError("Аккаунт изменился. Удаление остановлено.")
                entity = await self.group(scan.group)
                fresh = await self.call(lambda: self.client.get_messages(entity, ids=list(batch)))
                by_id = {m.id: m for m in fresh if isinstance(m, types.Message)}
                eligible = [mid for mid in batch if own_message(by_id.get(mid), scan.owner_id, scan.group.id, scan.dates)]
                for mid in batch:
                    if mid not in eligible:
                        states[mid] = "unconfirmed" if mid in uncertain else "skipped"
                if not eligible:
                    break
                loop = asyncio.get_running_loop()
                await self.control.sleep(max(0, self._next_call - loop.time()))
                self._next_call = loop.time() + self.delay
                self.control.check()
            except Exception as exc:
                if not uncertain:
                    raise
                for mid in uncertain:
                    states[mid] = "unconfirmed"
                self.emit("log", friendly_error(exc) if not isinstance(exc, Stopped) else "Операция остановлена.")
                break
            try:
                response = await asyncio.wait_for(self.client.delete_messages(entity, eligible, revoke=True), timeout=45)
                acknowledged = bool(response) and all(isinstance(r, types.messages.AffectedMessages) for r in response)
            except errors.FloodWaitError as exc:
                if attempt < 3:
                    self.emit("log", f"Telegram: ожидание {exc.seconds} с. Можно остановить операцию.")
                    try:
                        await self.control.sleep(exc.seconds)
                    except Stopped:
                        for mid in uncertain:
                            states[mid] = "unconfirmed"
                        if uncertain:
                            break
                        raise
                    continue
                for mid in eligible:
                    states[mid] = "unconfirmed" if mid in uncertain else "errors"
                break
            except TRANSIENT:
                # The server may have committed despite a lost response. Never count
                # messages missing on a subsequent retry as confirmed deletions.
                uncertain.update(eligible)
                if attempt < 3:
                    self.emit("log", f"Сетевой сбой при удалении. Повторная проверка, попытка {attempt + 1}/3.")
                    try:
                        await self.control.sleep(min(2 ** attempt, 8))
                    except Stopped:
                        for mid in uncertain:
                            states[mid] = "unconfirmed"
                        break
                    continue
                for mid in eligible:
                    states[mid] = "unconfirmed"
                break
            except Exception as exc:
                self.emit("log", friendly_error(exc))
                for mid in eligible:
                    rejected = isinstance(exc, errors.RPCError) and not isinstance(exc, errors.ServerError)
                    states[mid] = "errors" if rejected and mid not in uncertain else "unconfirmed"
                break
            # Acknowledgement alone is not evidence of per-message deletion.
            for mid in eligible:
                states[mid] = "unconfirmed"
            if self.control.event.is_set():
                break
            try:
                entity = await self.group(scan.group)
                after = await self.call(lambda: self.client.get_messages(entity, ids=eligible))
                if len(after) != len(eligible):
                    break
                for mid, message in zip(eligible, after):
                    absent = message is None or (isinstance(message, types.MessageEmpty) and message.id == mid)
                    if absent and acknowledged:
                        states[mid] = "deleted"
                    elif isinstance(message, types.Message) and message.id == mid and own_message(message, scan.owner_id, scan.group.id, scan.dates):
                        states[mid] = "errors"
            except Exception:
                pass
            break
        return tuple(sum(state == name for state in states.values())
                     for name in ("deleted", "skipped", "errors", "unconfirmed"))


def friendly_error(exc):
    # Never interpolate raw exceptions: Telegram errors can contain private request data.
    if isinstance(exc, SafetyError):
        return str(exc)
    if isinstance(exc, errors.FloodWaitError):
        return "Telegram повторно ограничил запросы. Операция остановлена; повторите позже."
    if isinstance(exc, TRANSIENT):
        return "Сеть или Telegram недоступны после ограниченного числа повторов."
    name = type(exc).__name__
    messages = {
        "PhoneCodeInvalidError": "Неверный код входа. Проверьте код в Telegram.",
        "PhoneCodeExpiredError": "Код истёк. Запросите новый код.",
        "PhoneNumberInvalidError": "Неверный формат номера телефона.",
        "PhoneNumberBannedError": "Telegram ограничил вход для этого номера.",
        "PasswordHashInvalidError": "Неверный пароль двухфакторной аутентификации.",
        "ApiIdInvalidError": "Telegram отклонил API ID или API Hash.",
        "AuthKeyUnregisteredError": "Сессия отозвана. Войдите в аккаунт заново.",
        "SessionRevokedError": "Сессия отозвана. Войдите в аккаунт заново.",
        "ChannelPrivateError": "Группа недоступна: нет доступа или вы покинули её.",
        "ChatAdminRequiredError": "Telegram не разрешает эту операцию в группе.",
        "MessageDeleteForbiddenError": "Telegram запретил удаление пакета. Часть сообщений может быть недоступна для удаления.",
        "ChatIdInvalidError": "Группа недоступна. Обновите список групп.",
        "UserBannedInChannelError": "Доступ аккаунта к группе ограничен.",
    }
    return messages.get(name, "Операция не выполнена. Проверьте подключение, доступ к группе и повторите попытку.")
