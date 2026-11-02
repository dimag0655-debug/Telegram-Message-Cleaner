from datetime import datetime, time, timedelta
from pathlib import Path
from time import monotonic

from PySide6.QtCore import Qt, QDate, QTimer
from PySide6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton,
    QStackedWidget, QFrame, QFormLayout, QListWidget, QListWidgetItem, QSplitter,
    QCheckBox, QDateEdit, QDoubleSpinBox, QProgressBar, QPlainTextEdit, QTableWidget,
    QTableWidgetItem, QHeaderView, QAbstractItemView, QDialog, QDialogButtonBox,
    QFileDialog, QMessageBox, QScrollArea,
)

from telegram_client.models import DateRange, Confirmation
from ui.theme import STYLE
from utils.settings import read_settings, write_settings
from workers.runtime import Runtime


def label(text, name=None, wrap=False):
    widget = QLabel(text)
    widget.setTextFormat(Qt.TextFormat.PlainText)
    widget.setWordWrap(wrap)
    if name:
        widget.setObjectName(name)
    return widget


def button(text, name=None):
    widget = QPushButton(text)
    if name:
        widget.setObjectName(name)
    widget.setCursor(Qt.CursorShape.PointingHandCursor)
    return widget


def card():
    widget = QFrame()
    widget.setObjectName("card")
    layout = QVBoxLayout(widget)
    layout.setContentsMargins(22, 20, 22, 20)
    layout.setSpacing(14)
    return widget, layout


class ConfirmDialog(QDialog):
    def __init__(self, scan, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Подтвердите удаление")
        self.setMinimumWidth(490)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(26, 24, 26, 24)
        layout.setSpacing(16)
        layout.addWidget(label("Удаление для всех участников", "heading"))
        layout.addWidget(label(f"Группа: {scan.group.title}\nID: {scan.group.id}\n"
                               f"Ваших сообщений: {len(scan.ids):,}\nПериод: {scan.dates.label()}", wrap=True))
        layout.addWidget(label("Действие необратимо. Перед каждым пакетом автор и группа будут проверены повторно.", "muted", True))
        layout.addWidget(label("Введите слово УДАЛИТЬ точно, без пробелов:"))
        self.word = QLineEdit()
        self.word.setAccessibleName("Слово подтверждения УДАЛИТЬ")
        self.word.setPlaceholderText("УДАЛИТЬ")
        layout.addWidget(self.word)
        self.buttons = QDialogButtonBox()
        self.cancel_button = self.buttons.addButton("Отмена", QDialogButtonBox.ButtonRole.RejectRole)
        self.delete_button = self.buttons.addButton("Подтвердить удаление", QDialogButtonBox.ButtonRole.AcceptRole)
        self.delete_button.setObjectName("danger")
        self.delete_button.setEnabled(False)
        self.delete_button.setAutoDefault(False)
        self.cancel_button.setDefault(True)
        self.word.textChanged.connect(lambda text: self.delete_button.setEnabled(text == "УДАЛИТЬ"))
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        layout.addWidget(self.buttons)

    def accept(self):
        if self.word.text() == "УДАЛИТЬ":
            super().accept()


class MainWindow(QMainWindow):
    def __init__(self, start_worker=True):
        super().__init__()
        self.setWindowTitle("Telegram Message Cleaner")
        self.setStyleSheet(STYLE)
        self.setMinimumSize(1000, 780)
        settings = read_settings()
        self.resize(max(1000, min(int(settings.get("width", 1240)), 2200)),
                    max(780, min(int(settings.get("height", 920)), 1500)))
        self.runtime = Runtime()
        self.runtime.event.connect(self.on_event)
        self.runtime.initialized.connect(self._update_actions)
        self.runtime.finished.connect(self._thread_finished)
        self.busy = False
        self.operation = None
        self.auth_stage = None
        self.auth_clock = QTimer(self)
        self.auth_clock.setInterval(250)
        self.auth_clock.timeout.connect(self.tick_auth)
        self.scan_result = None
        self.report = None
        self.closing = False
        self.shutdown_started = False
        self.demo = not start_worker
        self.pages = QStackedWidget()
        self.setCentralWidget(self.pages)
        self._auth_page()
        self._main_page(settings)
        self._update_actions()
        if start_worker:
            self.runtime.start()

    def _auth_page(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(70, 30, 70, 30)
        layout.addStretch()
        row = QHBoxLayout()
        intro = QVBoxLayout()
        intro.addWidget(label("TELEGRAM / ЛИЧНЫЙ АККАУНТ", "eyebrow"))
        intro.addWidget(label("История под\nвашим контролем.", "title"))
        intro.addWidget(label("Найдите и удалите свои сообщения\nиз выбранной группы Telegram.", "muted"))
        intro.addSpacing(26)
        intro.addWidget(label("01   Сканирование доступной истории\n\n02   Проверка автора и группы\n\n03   Подтверждение и удаление", "muted"))
        intro.addStretch()
        row.addLayout(intro, 1)
        frame, form_layout = card()
        frame.setMinimumWidth(440)
        frame.setMaximumWidth(510)
        form_layout.addWidget(label("Telegram Message Cleaner", "heading"))
        form_layout.addWidget(label("Вход через официальный Telegram API", "muted"))
        form = QFormLayout()
        form.setSpacing(13)
        self.api_id = QLineEdit()
        self.api_id.setPlaceholderText("Например, 12345678")
        self.api_hash = QLineEdit()
        self.api_hash.setEchoMode(QLineEdit.EchoMode.Password)
        self.api_hash.setPlaceholderText("32 символа")
        self.phone = QLineEdit()
        self.phone.setPlaceholderText("+79991234567")
        for title, widget in (("API ID", self.api_id), ("API Hash", self.api_hash), ("Телефон", self.phone)):
            widget.setAccessibleName(title)
            form.addRow(title, widget)
        form_layout.addLayout(form)
        self.connect_button = button("Подключиться / получить код", "primary")
        self.connect_button.setEnabled(False)
        self.connect_button.clicked.connect(self.connect_account)
        form_layout.addWidget(self.connect_button)
        network_row = QHBoxLayout()
        self.network_button = button("Проверить соединение")
        self.network_button.clicked.connect(lambda: self.run("network"))
        self.auth_cancel = button("Прервать вход")
        self.auth_cancel.clicked.connect(self.stop)
        self.auth_cancel.setEnabled(False)
        network_row.addWidget(self.network_button)
        network_row.addWidget(self.auth_cancel)
        form_layout.addLayout(network_row)
        self.code = QLineEdit()
        self.code.setPlaceholderText("Код из Telegram")
        self.code.setAccessibleName("Код подтверждения Telegram")
        self.code.setEchoMode(QLineEdit.EchoMode.Password)
        self.code_button = button("Подтвердить код", "primary")
        self.code_button.clicked.connect(self.submit_code)
        self.password = QLineEdit()
        self.password.setEchoMode(QLineEdit.EchoMode.Password)
        self.password.setAccessibleName("Пароль двухфакторной аутентификации")
        self.password.setPlaceholderText("Пароль двухфакторной аутентификации")
        self.password_button = button("Подтвердить пароль", "primary")
        self.password_button.clicked.connect(self.submit_password)
        for widget in (self.code, self.code_button, self.password, self.password_button):
            form_layout.addWidget(widget)
            widget.hide()
        self.auth_status = label("Введите реквизиты приложения с my.telegram.org → API development tools.", "muted", True)
        form_layout.addWidget(self.auth_status)
        form_layout.addWidget(label("Используете VPN? Он должен направлять трафик этой программы через туннель. Прокси из настроек Telegram Desktop сюда не переносится.", "muted", True))
        form_layout.addWidget(label("Сессия хранится в %LOCALAPPDATA%\\TelegramMessageCleaner. Реквизиты входа не записываются в настройки и журнал.", "muted", True))
        row.addWidget(frame, 1)
        layout.addLayout(row)
        layout.addStretch()
        layout.addWidget(label("Локальное приложение  •  Только ваши сообщения  •  Сначала предварительный просмотр", "muted"))
        self.pages.addWidget(page)

    def _main_page(self, settings):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(28, 24, 28, 24)
        layout.setSpacing(16)
        header = QHBoxLayout()
        titles = QVBoxLayout()
        titles.addWidget(label("TELEGRAM / MESSAGE CLEANER", "eyebrow"))
        titles.addWidget(label("Очистка сообщений", "title"))
        header.addLayout(titles)
        header.addStretch()
        self.account = label("Аккаунт подключён", "status")
        header.addWidget(self.account)
        self.logout_button = button("Выйти из аккаунта")
        self.logout_button.clicked.connect(lambda: self.run("logout"))
        header.addWidget(self.logout_button)
        layout.addLayout(header)
        splitter = QSplitter(Qt.Orientation.Horizontal)
        side, side_layout = card()
        side.setMinimumWidth(260)
        side.setMaximumWidth(410)
        side_layout.addWidget(label("Ваши группы", "heading"))
        self.search = QLineEdit()
        self.search.setPlaceholderText("Поиск по названию…")
        self.search.setAccessibleName("Поиск группы")
        self.search.textChanged.connect(self.filter_groups)
        side_layout.addWidget(self.search)
        self.groups_list = QListWidget()
        self.groups_list.setAccessibleName("Группы Telegram")
        self.groups_list.currentItemChanged.connect(self.selection_changed)
        side_layout.addWidget(self.groups_list, 1)
        self.group_count = label("Список ещё не загружен", "muted", True)
        side_layout.addWidget(self.group_count)
        self.refresh_button = button("Обновить группы")
        self.refresh_button.clicked.connect(lambda: self.run("groups"))
        side_layout.addWidget(self.refresh_button)
        splitter.addWidget(side)
        content = QWidget()
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(14)
        options, options_layout = card()
        self.group_title = label("Выберите группу слева", "heading", True)
        self.group_id = label("Личные переписки и каналы не отображаются", "muted")
        options_layout.addWidget(self.group_title)
        options_layout.addWidget(self.group_id)
        filters = QHBoxLayout()
        self.all_dates = QCheckBox("Вся история")
        self.all_dates.setChecked(True)
        self.date_start = QDateEdit(QDate.currentDate().addYears(-1))
        self.date_end = QDateEdit(QDate.currentDate())
        for date_widget in (self.date_start, self.date_end):
            date_widget.setMinimumWidth(146)
            date_widget.setDisplayFormat("dd.MM.yyyy")
            date_widget.setCalendarPopup(True)
            date_widget.setEnabled(False)
            date_widget.dateChanged.connect(self.invalidate_scan)
        self.date_start.setAccessibleName("Начало периода включительно")
        self.date_end.setAccessibleName("Конец периода включительно")
        self.all_dates.toggled.connect(self.dates_changed)
        filters.addWidget(self.all_dates)
        filters.addWidget(label("с"))
        filters.addWidget(self.date_start)
        filters.addWidget(label("по"))
        filters.addWidget(self.date_end)
        filters.addStretch()
        options_layout.addLayout(filters)
        pacing = QHBoxLayout()
        pacing.addWidget(label("Задержка между запросами, с", "muted"))
        self.delay = QDoubleSpinBox()
        self.delay.setRange(0.2, 60.0)
        self.delay.setSingleStep(0.2)
        self.delay.setValue(float(settings.get("delay", 1.0)))
        self.delay.setAccessibleName("Задержка между запросами в секундах")
        pacing.addWidget(self.delay)
        pacing.addStretch()
        options_layout.addLayout(pacing)
        self.preview_only = QCheckBox("Предварительный просмотр — удаление заблокировано")
        self.preview_only.setChecked(True)
        self.preview_only.toggled.connect(self._update_actions)
        options_layout.addWidget(self.preview_only)
        content_layout.addWidget(options)
        stats = QHBoxLayout()
        self.metrics = []
        for title in ("НАЙДЕНО СВОИХ", "ПРОСМОТРЕНО", "ОБРАБОТАНО"):
            frame, item_layout = card()
            item_layout.setContentsMargins(18, 12, 18, 12)
            item_layout.setSpacing(3)
            item_layout.addWidget(label(title, "eyebrow"))
            value = label("0", "metric")
            self.metrics.append(value)
            item_layout.addWidget(value)
            stats.addWidget(frame)
        content_layout.addLayout(stats)
        actions = QHBoxLayout()
        self.scan_button = button("Сканировать", "primary")
        self.scan_button.clicked.connect(self.start_scan)
        self.delete_button = button("Удалить все мои сообщения", "danger")
        self.delete_button.clicked.connect(self.confirm_delete)
        self.stop_button = button("Остановить")
        self.stop_button.clicked.connect(self.stop)
        for widget in (self.scan_button, self.delete_button, self.stop_button):
            actions.addWidget(widget)
        content_layout.addLayout(actions)
        self.progress = QProgressBar()
        self.progress.setTextVisible(False)
        self.progress.setValue(0)
        content_layout.addWidget(self.progress)
        self.status = label("Начните со сканирования. Ничего не удаляется автоматически.", "muted", True)
        content_layout.addWidget(self.status)
        content_layout.addWidget(label("Предпросмотр • до 50 ваших сообщений", "muted"))
        self.preview = QTableWidget(0, 3)
        self.preview.setHorizontalHeaderLabels(["ID", "Дата", "Сообщение"])
        self.preview.verticalHeader().hide()
        self.preview.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.preview.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.preview.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.preview.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.preview.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self.preview.setMinimumHeight(110)
        content_layout.addWidget(self.preview, 1)
        splitter.addWidget(content)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([300, 850])
        layout.addWidget(splitter, 1)
        log_header = QHBoxLayout()
        log_header.addWidget(label("Журнал выполнения", "muted"))
        log_header.addStretch()
        self.export_button = button("Экспорт отчёта TXT")
        self.export_button.clicked.connect(self.export_report)
        log_header.addWidget(self.export_button)
        layout.addLayout(log_header)
        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setMaximumBlockCount(1500)
        self.log.setFixedHeight(100)
        layout.addWidget(self.log)
        self.pages.addWidget(page)

    def group(self):
        item = self.groups_list.currentItem()
        return item.data(Qt.ItemDataRole.UserRole) if item and not item.isHidden() else None

    def dates(self):
        if self.all_dates.isChecked():
            return DateRange()
        start = self.date_start.date().toPython()
        end = self.date_end.date().toPython()
        if start > end:
            raise ValueError("Начальная дата позже конечной.")
        # Interpret each boundary in Windows local time, including historical DST.
        return DateRange(datetime.combine(start, time.min).astimezone(),
                         datetime.combine(end + timedelta(days=1), time.min).astimezone())

    def dates_changed(self, *_):
        self.date_start.setEnabled(not self.all_dates.isChecked() and not self.busy)
        self.date_end.setEnabled(not self.all_dates.isChecked() and not self.busy)
        self.invalidate_scan()

    def invalidate_scan(self, *_):
        self.scan_result = None
        self.preview.setRowCount(0)
        for value in self.metrics:
            value.setText("0")
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self._update_actions()

    def selection_changed(self, *_):
        self.invalidate_scan()
        group = self.group()
        self.group_title.setText(group.title if group else "Выберите группу слева")
        self.group_id.setText(f"ID группы: {group.id}" if group else "Личные переписки и каналы не отображаются")
        self.status.setText("Готово к сканированию." if group else "Выберите доступную группу.")

    def filter_groups(self, text):
        for index in range(self.groups_list.count()):
            item = self.groups_list.item(index)
            item.setHidden(text.casefold() not in item.text().casefold())
        if self.groups_list.currentItem() and self.groups_list.currentItem().isHidden():
            self.groups_list.setCurrentRow(-1)

    def _update_actions(self, *_):
        group = self.group()
        scan = self.scan_result
        self.scan_button.setEnabled(bool(group) and not self.busy and not self.demo)
        self.delete_button.setEnabled(bool(group and scan and scan.complete and scan.ids and
                                           scan.group.id == group.id) and not self.busy and
                                      not self.preview_only.isChecked() and not self.demo)
        self.stop_button.setEnabled(self.busy)
        self.export_button.setEnabled(self.report is not None and not self.busy)
        for widget in (self.groups_list, self.search, self.refresh_button, self.logout_button,
                       self.all_dates, self.delay, self.preview_only):
            widget.setEnabled(not self.busy and not self.demo)
        self.date_start.setEnabled(not self.all_dates.isChecked() and not self.busy)
        self.date_end.setEnabled(not self.all_dates.isChecked() and not self.busy)
        for widget in (self.api_id, self.api_hash, self.phone, self.code, self.code_button,
                       self.password, self.password_button):
            widget.setEnabled(not self.busy)
        self.connect_button.setEnabled(not self.busy and self.runtime.isRunning())
        self.network_button.setEnabled(not self.busy and self.runtime.isRunning())
        self.auth_cancel.setEnabled(self.busy and self.pages.currentIndex() == 0)

    def run(self, command, *args):
        if self.busy or self.demo or self.closing:
            return
        if not self.runtime.submit(command, *args):
            self.status.setText("Фоновая задача ещё завершается. Повторите действие.")
            return
        self.busy = True
        self.operation = command
        self._update_actions()
        if command in ("scan", "groups"):
            self.progress.setRange(0, 0)
        self.status.setText({"scan": "Сканирование доступной истории…", "groups": "Получение групп…",
                             "delete": "Повторная проверка и удаление…", "logout": "Выход из аккаунта…"}.get(command, "Подключение…"))
        if command in ("connect", "code", "password", "network"):
            self.auth_status.setText("Ожидание ответа Telegram…")

    def connect_account(self):
        if self.busy:
            return
        for widget in (self.code, self.code_button, self.password, self.password_button):
            widget.hide()
        self.run("connect", self.api_id.text().strip(), self.api_hash.text().strip(), self.phone.text().strip())

    def submit_code(self):
        self.run("code", self.code.text().strip())
        self.code.clear()

    def submit_password(self):
        self.run("password", self.password.text())
        self.password.clear()

    def start_scan(self):
        group = self.group()
        if not group:
            return
        try:
            dates = self.dates()
        except ValueError as exc:
            self.status.setText(str(exc))
            return
        self.invalidate_scan()
        self.report = None
        self.append_log("Запущено сканирование. Запросы на удаление не выполняются.")
        self.run("scan", group, dates, self.delay.value())

    def confirm_delete(self):
        group, scan = self.group(), self.scan_result
        if not self.delete_button.isEnabled() or not group or not scan:
            return
        dialog = ConfirmDialog(scan, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        confirmation = Confirmation(scan.token, group.id, scan.owner_id, len(scan.ids), dialog.word.text())
        self.progress.setRange(0, len(scan.ids))
        self.progress.setValue(0)
        self.scan_result = None
        self.preview.setRowCount(0)
        self.run("delete", scan, confirmation, group.id, self.delay.value())

    def stop(self):
        self.runtime.stop()
        self.stop_button.setEnabled(False)
        self.auth_cancel.setEnabled(False)
        self.auth_stage = None
        self.auth_clock.stop()
        if self.pages.currentIndex() == 0:
            self.auth_status.setText("Прерывание ожидания…")
        self.status.setText("Остановка: завершается текущий запрос. Отправленный запрос отменить нельзя.")

    def tick_auth(self):
        if self.auth_stage:
            stage, started, timeout = self.auth_stage
            self.auth_status.setText(f"{stage}… {min(int(monotonic() - started), int(timeout))} / {timeout:g} с")

    def append_log(self, message):
        self.log.appendPlainText(f"{datetime.now().strftime('%H:%M:%S')}  {message}")

    def on_event(self, kind, value):
        if kind == "log":
            self.append_log(value)
        elif kind == "error":
            self.auth_stage = None
            self.auth_clock.stop()
            self.auth_status.setText(value)
            self.status.setText(value)
            self.append_log(value)
        elif kind == "auth_progress":
            stage, timeout = value
            self.auth_stage = (stage, monotonic(), timeout)
            self.auth_clock.start()
            self.tick_auth()
        elif kind == "auth_status":
            self.auth_stage = None
            self.auth_clock.stop()
            self.auth_status.setText(value)
        elif kind == "auth_reset":
            for widget in (self.code, self.code_button, self.password, self.password_button):
                widget.hide()
            self.code.clear()
            self.password.clear()
        elif kind == "auth_step":
            self.auth_stage = None
            self.auth_clock.stop()
            self.code.setVisible(value == "code")
            self.code_button.setVisible(value == "code")
            self.password.setVisible(value == "password")
            self.password_button.setVisible(value == "password")
            self.auth_status.setText("Введите код, полученный в Telegram." if value == "code" else "Telegram запросил пароль двухфакторной аутентификации.")
        elif kind == "scan_progress":
            examined, found = value
            self.metrics[0].setText(f"{found:,}")
            self.metrics[1].setText(f"{examined:,}")
            self.status.setText(f"Просмотрено {examined:,} сообщений. Найдено своих: {found:,}.")
        elif kind == "delete_progress":
            self.metrics[2].setText(f"{value.processed:,}")
            self.progress.setValue(value.processed)
            self.status.setText(f"Удалено: {value.deleted:,} • пропущено: {value.skipped:,} • ошибки: {value.errors:,} • неподтверждено: {value.unconfirmed:,}")
        elif kind == "result":
            command, result = value
            self._result(command, result)
        elif kind == "idle":
            self.auth_stage = None
            self.auth_clock.stop()
            self.busy = False
            self.operation = None
            if self.progress.maximum() == 0:
                self.progress.setRange(0, 100)
                self.progress.setValue(0)
            self._update_actions()
            if self.closing:
                QTimer.singleShot(100, self.close)

    def _result(self, command, result):
        if command == "network":
            self.auth_status.setText("TCP-соединение с Telegram доступно. Это проверка сети без входа; успешный ответ MTProto и доставка кода проверяются отдельно при подключении.")
        elif command in ("connect", "code", "password") and result:
            for widget in (self.api_id, self.api_hash, self.phone, self.code, self.password):
                widget.clear()
            self.pages.setCurrentIndex(1)
            self.account.setText(f"Подключён • ID {result}")
            self.append_log("Аккаунт подтверждён. Загрузка групп…")
            QTimer.singleShot(100, lambda: self.run("groups"))
        elif command == "groups":
            self.invalidate_scan()
            self.groups_list.clear()
            for group in result:
                item = QListWidgetItem(group.title)
                item.setData(Qt.ItemDataRole.UserRole, group)
                item.setToolTip(f"ID: {group.id}")
                self.groups_list.addItem(item)
            self.group_count.setText(f"Доступных групп: {len(result)}")
            self.filter_groups(self.search.text())
            self.status.setText("Выберите группу и запустите сканирование." if result else "Доступных групп нет. Группы без доступа и покинутые группы не отображаются.")
        elif command == "scan":
            self.scan_result = result if result.complete else None
            self.metrics[0].setText(f"{len(result.ids):,}")
            self.metrics[1].setText(f"{result.examined:,}")
            self.preview.setRowCount(len(result.preview))
            for row, values in enumerate(result.preview):
                for col, value in enumerate(values):
                    self.preview.setItem(row, col, QTableWidgetItem(str(value)))
            message = (f"Сканирование завершено. Ваших сообщений: {len(result.ids):,}." if result.complete else
                       "Сканирование остановлено. Для удаления выполните полное сканирование заново.")
            self.status.setText(message)
            self.append_log(message)
        elif command == "delete":
            self.report = result
            self.metrics[2].setText(f"{result.processed:,}")
            self.progress.setValue(result.processed)
            summary = (f"{'Остановлено' if result.stopped else 'Завершено'}. Удалено: {result.deleted:,}; "
                       f"пропущено: {result.skipped:,}; ошибки: {result.errors:,}; "
                       f"неподтверждено: {result.unconfirmed:,}; не обработано: {result.total - result.processed:,}.")
            if result.failure:
                summary += " " + result.failure
            self.status.setText(summary)
            self.append_log(summary)
            self.append_log("Для проверки оставшейся истории выполните новое сканирование.")
        elif command == "logout":
            self.invalidate_scan()
            self.groups_list.clear()
            self.report = None
            self.log.clear()
            for widget in (self.code, self.code_button, self.password, self.password_button):
                widget.hide()
            self.auth_status.setText("Сессия завершена и удалена. Можно войти в другой аккаунт.")
            self.pages.setCurrentIndex(0)

    def export_report(self):
        if self.report is None:
            return
        path, _ = QFileDialog.getSaveFileName(self, "Экспорт итогового отчёта", "TelegramCleaner-report.txt", "Текст (*.txt)")
        if path:
            try:
                Path(path).write_text(self.report.text(), encoding="utf-8-sig")
                self.append_log("Итоговый отчёт сохранён в выбранный файл.")
            except OSError:
                QMessageBox.warning(self, "Экспорт", "Не удалось записать файл. Выберите другой каталог.")

    def closeEvent(self, event):
        if self.runtime.isRunning():
            event.ignore()
            self.closing = True
            if self.busy:
                self.stop()
                return
            if not self.shutdown_started:
                self.shutdown_started = True
                self.runtime.shutdown()
            return
        if not self.demo:
            try:
                write_settings(self.width(), self.height(), self.delay.value())
            except OSError:
                pass
        event.accept()

    def _thread_finished(self):
        if self.closing:
            self.close()
