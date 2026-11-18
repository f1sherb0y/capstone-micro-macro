from __future__ import annotations

import asyncio
import os


class LLMThrottle:
    def __init__(self) -> None:
        limit = int(os.getenv("CODEDEMO_LLM_CONCURRENCY", "3"))
        self.limit = limit
        self.min_interval = float(os.getenv("CODEDEMO_LLM_MIN_INTERVAL", "0"))
        self.semaphore = asyncio.Semaphore(limit)
        self.lock = asyncio.Lock()
        self.last_request = 0.0

    async def wait_turn(self) -> None:
        if self.min_interval <= 0:
            return
        async with self.lock:
            loop = asyncio.get_running_loop()
            now = loop.time()
            wait = self.min_interval - (now - self.last_request)
            if wait > 0:
                await asyncio.sleep(wait)
            self.last_request = loop.time()
