from dataclasses import dataclass, field
from datetime import datetime, timezone
from uuid import uuid4

UTC = timezone.utc


@dataclass(frozen=True)
class Group:
    id: int  # Telethon marked peer ID: negative chat ID or -100… channel ID
    title: str
    entity: object = field(repr=False, compare=False)


@dataclass(frozen=True)
class DateRange:
    start: datetime | None = None
    end: datetime | None = None  # exclusive

    def __post_init__(self):
        for value in (self.start, self.end):
            if value is not None and value.tzinfo is None:
                raise ValueError("Dates must include a timezone")
        if self.start and self.end and self.start >= self.end:
            raise ValueError("Начальная дата должна предшествовать конечной.")

    def contains(self, date):
        return bool(date and date.tzinfo and
                    (self.start is None or date >= self.start) and
                    (self.end is None or date < self.end))

    def label(self):
        if self.start is None and self.end is None:
            return "Вся доступная история"
        return f"{self.start.isoformat() if self.start else '…'} ≤ дата < {self.end.isoformat() if self.end else '…'}"


@dataclass(frozen=True)
class ScanResult:
    group: Group
    owner_id: int
    dates: DateRange
    ids: tuple[int, ...]
    examined: int
    preview: tuple[tuple[int, str, str], ...] = ()
    complete: bool = True
    token: str = field(default_factory=lambda: uuid4().hex)
    created: datetime = field(default_factory=lambda: datetime.now(UTC))


@dataclass(frozen=True)
class Confirmation:
    token: str
    group_id: int
    owner_id: int
    count: int
    word: str

    def matches(self, scan):
        return (self.word == "УДАЛИТЬ" and self.token == scan.token and
                self.group_id == scan.group.id and self.owner_id == scan.owner_id and
                self.count == len(scan.ids) and scan.complete and bool(scan.ids))


@dataclass
class DeleteReport:
    group_title: str
    group_id: int
    dates: str
    total: int
    deleted: int = 0
    skipped: int = 0
    errors: int = 0
    unconfirmed: int = 0
    processed: int = 0
    stopped: bool = False
    failure: str = ""
    started: datetime = field(default_factory=lambda: datetime.now(UTC))
    finished: datetime | None = None

    def text(self):
        return ("Telegram Message Cleaner — итоговый отчёт\n"
                f"Группа: {self.group_title}\nID группы: {self.group_id}\n"
                f"Период: {self.dates}\nНачало UTC: {self.started.isoformat()}\n"
                f"Завершение UTC: {self.finished.isoformat() if self.finished else '—'}\n"
                f"Найдено: {self.total}\nОбработано: {self.processed}\n"
                f"Удалено (ответ API + проверка отсутствия): {self.deleted}\n"
                f"Пропущено при повторной проверке: {self.skipped}\nОшибки: {self.errors}\n"
                f"Неподтверждённые результаты: {self.unconfirmed}\n"
                f"Не обработано: {self.total - self.processed}\n"
                f"Остановлено: {'да' if self.stopped else 'нет'}\n"
                f"Статус: {self.failure or 'завершено'}\n\n"
                "Удалено: API принял запрос, последующее чтение не вернуло сообщение.\n"
                "Это проверка доступной аккаунту истории, не независимая проверка устройств участников.\n"
                "Неподтверждённо: запрос мог выполниться, но надёжного ответа/проверки нет.\n"
                "Содержимое сообщений и реквизиты входа в отчёт не включаются.\n")
