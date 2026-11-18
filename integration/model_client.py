"""Persist successful model responses so a technical retry need not repay for them."""
from contextlib import contextmanager
from copy import deepcopy
from pathlib import Path
import threading

from src.llm_client import LLMResponse
from src.json_input import read_json_object
from integration.contracts import digest
from integration.sessions import atomic_json


class CachedModelClient:
    def __init__(self, client, directory, on_call=None):
        self.client, self.config = client, client.config
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)
        self.on_call = on_call
        self.lock = threading.RLock()
        self._inflight = {}
        self.calls, self.cached_calls, self.input_tokens, self.output_tokens = 0, 0, 0, 0

    def _path(self, messages, temperature):
        return self.directory / (digest({"provider": self.config.provider, "model": self.config.model,
             "endpoint": self.config.base_url, "messages": messages, "temperature": temperature}) + ".json")

    def request_policy(self):
        """Forward the actual underlying request limit; a cache miss performs one call."""
        import hashlib

        describe = getattr(self.client, 'request_policy', None)
        if not callable(describe):
            raise ValueError('Bounded cache client requires an explicit underlying transport policy')
        return {**describe(), 'cache_mode': 'successful-response',
                'cache_concurrency': 'per-request-single-flight.v1',
                'cache_record_validation': 'strict-content-metadata.v1',
                'cache_code_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}

    @contextmanager
    def _request_lock(self, path):
        """Count active/waiting callers so one request lock survives every waiter."""
        with self.lock:
            flight = self._inflight.setdefault(path, {'lock': threading.RLock(), 'users': 0})
            flight['users'] += 1
        try:
            with flight['lock']:
                yield
        finally:
            with self.lock:
                flight['users'] -= 1
                if flight['users'] == 0:
                    del self._inflight[path]

    @staticmethod
    def _validate_record(data):
        if (not isinstance(data, dict) or set(data) != {'content', 'metadata'}
                or not isinstance(data['content'], str) or not isinstance(data['metadata'], dict)):
            raise ValueError('Model cache requires exact content and metadata fields with their original types')
        digest(data)
        return data

    def _cached(self, path):
        if not path.exists():
            return None
        _, raw = read_json_object(path)
        data = self._validate_record(raw)
        with self.lock:
            self.cached_calls += 1
        return LLMResponse(data["content"], {"cache_hit": True, "original_metadata": data["metadata"], "usage_metadata": {}})

    def _start(self, messages):
        marker = messages[-1]["content"].splitlines()[0]
        if self.on_call:
            self.on_call(marker)

    def _save(self, path, result):
        record = self._validate_record(deepcopy({'content': result.content, 'metadata': result.metadata}))
        usage = record['metadata'].get('usage_metadata') or {}
        input_tokens = int(usage.get('input_tokens', 0))
        output_tokens = int(usage.get('output_tokens', 0))
        with self.lock:
            atomic_json(path, record)
            self.calls += 1
            self.input_tokens += input_tokens
            self.output_tokens += output_tokens
        return result

    def chat_with_metadata(self, messages, temperature=.2):
        messages = deepcopy(messages)
        path = self._path(messages, temperature)
        with self._request_lock(path):
            cached = self._cached(path)
            if cached:
                return cached
            self._start(messages)
            return self._save(path, self.client.chat_with_metadata(messages, temperature))

    async def achat_with_metadata(self, messages, temperature=.2):
        # GBA opens a short asyncio decision window per synchronous tick. Keep
        # the reusable HTTP pool synchronous and execute it in worker threads;
        # an async HTTP pool would remain bound to a closed earlier loop.
        import asyncio
        return await asyncio.to_thread(self.chat_with_metadata, deepcopy(messages), temperature)

    def chat(self, messages, temperature=.2):
        return self.chat_with_metadata(messages, temperature).content

    async def achat(self, messages, temperature=.2):
        return (await self.achat_with_metadata(messages, temperature)).content

    def usage(self):
        with self.lock:
            return {"model": self.config.model, "provider": self.config.provider, "requests": self.calls,
                    "cache_hits": self.cached_calls, "input_tokens": self.input_tokens, "output_tokens": self.output_tokens}

    def reject_response(self, messages, temperature):
        path = self._path(deepcopy(messages), temperature)
        with self._request_lock(path):
            path.unlink(missing_ok=True)
