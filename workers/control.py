import asyncio
import threading


class Stopped(Exception):
    pass


class Control:
    def __init__(self):
        self.event = threading.Event()

    def stop(self):
        self.event.set()

    def check(self):
        if self.event.is_set():
            raise Stopped()

    async def sleep(self, seconds):
        loop = asyncio.get_running_loop()
        deadline = loop.time() + max(0, seconds)
        while True:
            self.check()
            remaining = deadline - loop.time()
            if remaining <= 0:
                return
            await asyncio.sleep(min(0.1, remaining))
