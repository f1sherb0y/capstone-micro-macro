"""Exact-request cache and fail-stop API ledger for lifecycle batch attempts."""
import hashlib
import json
import os
from pathlib import Path

from integration.model_client import CachedModelClient


class LifecycleModelCache(CachedModelClient):
    def __init__(self, client, directory, max_paid_attempts=4):
        super().__init__(client, directory)
        self.ledger = self.directory / 'attempts.jsonl'
        self.max_paid_attempts = max_paid_attempts
        self.stopped = False

    def request_policy(self):
        return {**super().request_policy(), 'lifecycle_cache_version': '1',
                'lifecycle_code_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                'max_paid_attempts_across_reassembly': self.max_paid_attempts}

    def _record(self, data):
        with self.ledger.open('a', encoding='utf-8') as stream:
            stream.write(json.dumps(data, ensure_ascii=False, allow_nan=False) + '\n')
            stream.flush()
            os.fsync(stream.fileno())

    def chat_with_metadata(self, messages, temperature=.2):
        path = self._path(messages, temperature)
        with self._request_lock(path):
            if self.stopped:
                raise RuntimeError('API stopped after earlier failure; explicit batch resume required')
            cached = self._cached(path)
            if cached is not None:
                self._record({'event': 'cache_hit', 'request_sha256': path.stem})
                return cached
            previous = [] if not self.ledger.exists() else [json.loads(line)
                for line in self.ledger.read_text(encoding='utf-8').splitlines()]
            if sum(row['event'] == 'started' for row in previous) >= self.max_paid_attempts:
                self.stopped = True
                self._record({'event': 'attempt_cap_exhausted', 'request_sha256': path.stem})
                raise RuntimeError('Case paid-attempt cap exhausted, including retained attempts')
            self._record({'event': 'started', 'request_sha256': path.stem})
            try:
                result = self.client.chat_with_metadata(messages, temperature)
                self._save(path, result)
                self._record({'event': 'succeeded', 'request_sha256': path.stem})
                return result
            except Exception as exc:
                self.stopped = True
                # Do not record credentials, request headers or arbitrary exception text.
                self._record({'event': 'failed', 'request_sha256': path.stem,
                    'error_type': type(exc).__name__, 'http_status': getattr(exc, 'status_code', None)})
                raise
