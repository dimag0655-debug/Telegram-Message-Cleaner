import asyncio
import logging
import re

from PySide6.QtCore import QThread, Signal
from telethon import TelegramClient, errors, types
from telethon.client.telegrambaseclient import DEFAULT_IPV4_IP

from telegram_client.engine import Engine, friendly_error
from telegram_client.safety import SafetyError
from utils.settings import data_dir
from workers.control import Control, Stopped


class LoginConnectionError(SafetyError):
    pass


class Runtime(QThread):
    event = Signal(str, object)
    initialized = Signal()

    def __init__(self):
        super().__init__()
        self.loop = None
        self.client = None
        self.engine = None
        self.control = Control()
        self.active = None
        self.phone = None
        self.phone_code_hash = None
        self.login_allowed_at = 0.0

    def run(self):
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)
        self.initialized.emit()
        self.loop.run_forever()
        self.loop.close()

    def submit(self, command, *args):
        if self.loop is None or (self.active and not self.active.done()):
            return False
        self.control = Control()
        self.active = asyncio.run_coroutine_threadsafe(self._dispatch(command, *args), self.loop)
        return True

    def stop(self):
        self.control.stop()

    async def _dispatch(self, command, *args):
        try:
            if self.engine:
                self.engine.control = self.control
            method = getattr(self, "_" + command)
            result = await method(*args)
            self.event.emit("result", (command, result))
        except Stopped:
            message = ("Вход прерван. Если запрос кода уже ушёл, код всё ещё может прийти."
                       if command in ("connect", "code", "password") else "Операция остановлена.")
            self.event.emit("auth_status" if command in ("connect", "code", "password", "network") else "log", message)
            if command in ("connect", "code", "password"):
                await self._drop_connection()
                self.event.emit("auth_reset", None)
        except errors.SessionPasswordNeededError:
            self.event.emit("auth_step", "password")
        except errors.FloodWaitError as exc:
            if command in ("connect", "code", "password"):
                self.login_allowed_at = asyncio.get_running_loop().time() + exc.seconds
                self.event.emit("error", f"Telegram ограничил попытки входа. Подождите {exc.seconds} с перед повтором.")
            else:
                self.event.emit("error", friendly_error(exc))
        except Exception as exc:
            self.event.emit("error", friendly_error(exc))
            if command in ("connect", "code", "password") and isinstance(exc, LoginConnectionError):
                await self._drop_connection()
                self.event.emit("auth_reset", None)
        finally:
            self.event.emit("idle", command)

    async def _drop_connection(self):
        if self.client:
            try:
                await asyncio.wait_for(self.client.disconnect(), 2)
            except Exception:
                pass

    async def _auth_call(self, factory, stage, timeout):
        """One visible, bounded, cancellable auth step; no Engine.call retry loop.

        Telethon needs retries for phone/DC migration during login. Enable them
        only within this serialized auth step and always restore the zero-retry
        policy used by the destructive engine, including on cancellation.
        """
        self.control.check()
        self.event.emit("auth_progress", (stage, timeout))
        previous = getattr(self.client, "_request_retries", 0) if self.client else 0
        if self.client:
            self.client._request_retries = 2  # pinned Telethon 1.45's migration retry budget
        task = None
        deadline = asyncio.get_running_loop().time() + timeout
        try:
            task = asyncio.ensure_future(factory())
            while not task.done():
                self.control.check()
                remaining = deadline - asyncio.get_running_loop().time()
                if remaining <= 0:
                    raise asyncio.TimeoutError()
                await asyncio.wait({task}, timeout=min(0.1, remaining))
            self.control.check()
            return task.result()
        except (asyncio.TimeoutError, OSError):
            raise LoginConnectionError(f"Этап «{stage}»: ответа нет или соединение недоступно (лимит {timeout:g} с). "
                                       "Проверьте соединение кнопкой ниже. VPN должен охватывать TelegramMessageCleaner.exe.") from None
        finally:
            if self.client:
                self.client._request_retries = previous
            if task is not None and not task.done():
                task.cancel()
                await asyncio.wait({task}, timeout=1)
                if not task.done():
                    task.add_done_callback(lambda done: None if done.cancelled() else done.exception())
                elif not task.cancelled():
                    task.exception()
            elif task is not None and not task.cancelled():
                task.exception()

    def _check_login_delay(self):
        remaining = self.login_allowed_at - asyncio.get_running_loop().time()
        if remaining > 0:
            raise SafetyError(f"Telegram ограничил вход. До следующей попытки не менее {int(remaining) + 1} с.")

    async def _auth_me(self):
        me = await self._auth_call(self.client.get_me, "Проверка аккаунта", 15)
        if not isinstance(me, types.User) or not me.is_self or me.bot or not me.id:
            raise SafetyError("Не удалось подтвердить ID пользовательского аккаунта.")
        return me.id

    async def _network(self):
        async def probe():
            _, writer = await asyncio.open_connection(DEFAULT_IPV4_IP, 443)
            try:
                writer.close()
                await writer.wait_closed()
            finally:
                writer.close()
            return True
        return await self._auth_call(probe, "TCP-соединение с Telegram", 8)

    async def _connect(self, api_id, api_hash, phone):
        self._check_login_delay()
        if not re.fullmatch(r"[0-9]{1,12}", api_id) or int(api_id) <= 0:
            raise SafetyError("API ID должен быть положительным числом.")
        if not re.fullmatch(r"[a-fA-F0-9]{32}", api_hash):
            raise SafetyError("API Hash должен содержать 32 шестнадцатеричных символа.")
        if not re.fullmatch(r"\+[1-9][0-9]{6,14}", phone):
            raise SafetyError("Введите телефон в международном формате: +79991234567.")
        if self.client:
            await self._drop_connection()
        self.phone = self.phone_code_hash = None
        logger = logging.getLogger("cleaner.telegram")
        logger.handlers = [logging.NullHandler()]
        logger.propagate = False
        logger.setLevel(logging.CRITICAL + 1)
        self.client = TelegramClient(str(data_dir() / "account"), int(api_id), api_hash,
                                     flood_sleep_threshold=0, request_retries=0,
                                     raise_last_call_error=True,
                                     connection_retries=1, retry_delay=1, timeout=8,
                                     receive_updates=False, base_logger=logger,
                                     device_model="Telegram Message Cleaner", app_version="1.0.1")
        self.client.session.save_entities = False
        self.engine = Engine(self.client, self.event.emit, control=self.control)
        await self._auth_call(self.client.connect, "Подключение к Telegram", 20)
        if await self._auth_call(self.client.is_user_authorized, "Проверка сохранённой сессии", 15):
            return await self._auth_me()
        self.phone = phone
        # A lost login-code response is not blindly retried (may send a second code).
        response = await self._auth_call(lambda: self.client.send_code_request(phone), "Запрос кода входа", 25)
        if isinstance(response, types.auth.SentCodeSuccess):
            return await self._auth_me()
        if not isinstance(response, types.auth.SentCode) or not response.phone_code_hash:
            raise SafetyError("Telegram не предоставил код для этого способа входа. Проверьте вход в официальном клиенте Telegram.")
        self.phone_code_hash = response.phone_code_hash
        self.event.emit("auth_step", "code")
        delivery = type(response.type).__name__
        messages = {
            "SentCodeTypeApp": "Код отправлен в служебный чат Telegram на устройстве, где аккаунт уже открыт.",
            "SentCodeTypeSms": "Telegram сообщил, что код отправлен по SMS.",
            "SentCodeTypeCall": "Telegram сообщил, что код будет передан телефонным звонком.",
            "SentCodeTypeEmailCode": "Telegram сообщил, что код отправлен на привязанную почту.",
        }
        self.event.emit("auth_status", messages.get(delivery, "Telegram принял запрос кода. Проверьте способ доставки в официальном клиенте."))
        return None

    async def _code(self, code):
        self._check_login_delay()
        if not code or not code.isdigit():
            raise SafetyError("Введите цифровой код из Telegram.")
        await self._auth_call(lambda: self.client.sign_in(self.phone, code, phone_code_hash=self.phone_code_hash), "Проверка кода", 20)
        self.phone = self.phone_code_hash = None
        return await self._auth_me()

    async def _password(self, password):
        self._check_login_delay()
        await self._auth_call(lambda: self.client.sign_in(password=password), "Проверка пароля 2FA", 20)
        self.phone = self.phone_code_hash = None
        return await self._auth_me()

    async def _groups(self):
        return await self.engine.groups()

    async def _scan(self, group, dates, delay):
        self.engine.delay = delay
        return await self.engine.scan(group, dates)

    async def _delete(self, scan, confirmation, selected_id, delay):
        self.engine.delay = delay
        return await self.engine.delete(scan, confirmation, selected_id)

    async def _logout(self):
        result = await asyncio.wait_for(self.client.log_out(), 45)
        if not result:
            raise SafetyError("Выход не подтверждён Telegram. Повторите попытку.")
        self.client = None
        self.engine = None
        return True

    def shutdown(self):
        self.stop()
        if self.loop:
            asyncio.run_coroutine_threadsafe(self._shutdown(), self.loop)

    async def _shutdown(self):
        # Cancellation cannot undo a request already sent: never start new writes here.
        tasks = [t for t in asyncio.all_tasks() if t is not asyncio.current_task()]
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        if self.client:
            try:
                await asyncio.wait_for(self.client.disconnect(), 8)
            except Exception:
                pass
        self.loop.call_soon(self.loop.stop)
