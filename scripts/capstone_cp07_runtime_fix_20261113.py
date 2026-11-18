"""Narrow runtime-only repair; frozen CP07 prompts and generation stay intact.

Only the designated live budget view may be replaced. Requests, responses,
protocols, and prior-run evidence retain their original immutable save gate.
Local task errors are collected without cancelling other in-flight requests.
"""
import asyncio
import json
import os
from pathlib import Path
from threading import RLock
import uuid


class RuntimeProgressWriter:
    def __init__(self, *, budget_view_path, immutable_save):
        self.budget_view_path = Path(budget_view_path).resolve()
        self.immutable_save = immutable_save
        self._lock = RLock()

    def __call__(self, path, value):
        path = Path(path).resolve()
        if path != self.budget_view_path:
            return self.immutable_save(path, value)
        encoded = json.dumps(value, ensure_ascii=False, indent=2) + '\n'
        with self._lock:
            path.parent.mkdir(parents=True, exist_ok=True)
            temporary = path.with_name(path.name + '.' + uuid.uuid4().hex + '.tmp')
            created = False
            try:
                with temporary.open('x', encoding='utf-8', newline='\n') as stream:
                    created = True
                    stream.write(encoded)
                    stream.flush()
                    os.fsync(stream.fileno())
                os.replace(temporary, path)
            finally:
                if created:
                    temporary.unlink(missing_ok=True)


async def drain_job_results(awaitables):
    """A local error is an outcome; siblings finish and retain their receipts.

The original perform_job sets the shared halt before returning/raising a stop,
so queued jobs do not begin new requests. This gather must not propagate the
first exception while another already-started provider request is still alive.
Explicit process termination can still produce unknowns; none are replayed.
"""
    return await asyncio.gather(*awaitables, return_exceptions=True)
