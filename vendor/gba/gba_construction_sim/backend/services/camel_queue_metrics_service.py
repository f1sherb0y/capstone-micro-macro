from __future__ import annotations

from threading import RLock
from typing import Any


class CamelQueueMetricsService:
    def __init__(self) -> None:
        self._lock = RLock()
        self.reset()

    def reset(self) -> None:
        with getattr(self, "_lock", RLock()):
            self._queued = 0
            self._running = 0
            self._completed = 0
            self._failed = 0
            self._skipped_by_budget = 0
            self._skipped_by_rate_limit = 0
            self._model_ms_total = 0
            self._model_ms_count = 0
            self._queue_ms_total = 0
            self._queue_ms_count = 0
            self._last_error = None
            self._current_operation = "idle"
            self._rate_limited_until = None
            self._adaptive_min_interval_ms = 0

    def mark_queued(self, count: int = 1) -> None:
        with self._lock:
            self._queued += max(0, count)
            self._current_operation = "queued"

    def mark_started(self, queue_ms: int = 0) -> None:
        with self._lock:
            self._queued = max(0, self._queued - 1)
            self._running += 1
            self._queue_ms_total += max(0, queue_ms)
            self._queue_ms_count += 1
            self._current_operation = "running_model_decision"

    def mark_completed(self, model_ms: int = 0) -> None:
        with self._lock:
            self._running = max(0, self._running - 1)
            self._completed += 1
            self._model_ms_total += max(0, model_ms)
            self._model_ms_count += 1
            self._current_operation = "decision_completed"

    def mark_failed(self, error: str, model_ms: int = 0) -> None:
        with self._lock:
            self._running = max(0, self._running - 1)
            self._failed += 1
            self._model_ms_total += max(0, model_ms)
            self._model_ms_count += 1
            self._last_error = error
            self._current_operation = "decision_failed"

    def mark_skipped(self, count: int = 1, reason: str | None = None) -> None:
        with self._lock:
            self._queued = max(0, self._queued - max(0, count))
            if reason and "rate_limit" in reason:
                self._skipped_by_rate_limit += max(0, count)
                self._current_operation = "skipped_by_rate_limit"
            else:
                self._skipped_by_budget += max(0, count)
                self._current_operation = "skipped_by_budget"

    def mark_rate_limited(self, cooldown_until: float, adaptive_min_interval_ms: int) -> None:
        with self._lock:
            self._rate_limited_until = cooldown_until
            self._adaptive_min_interval_ms = max(0, int(adaptive_min_interval_ms))
            self._current_operation = "rate_limit_cooldown"

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            avg_model_ms = (
                self._model_ms_total / self._model_ms_count
                if self._model_ms_count
                else 0
            )
            avg_queue_ms = (
                self._queue_ms_total / self._queue_ms_count
                if self._queue_ms_count
                else 0
            )
            return {
                "queued": self._queued,
                "running": self._running,
                "completed": self._completed,
                "failed": self._failed,
                "skipped_by_budget": self._skipped_by_budget,
                "skipped_by_rate_limit": self._skipped_by_rate_limit,
                "avg_model_ms": round(avg_model_ms, 1),
                "avg_queue_ms": round(avg_queue_ms, 1),
                "current_operation": self._current_operation,
                "last_error": self._last_error,
                "rate_limited_until": self._rate_limited_until,
                "cooldown_remaining_ms": self._cooldown_remaining_ms(),
                "adaptive_min_interval_ms": self._adaptive_min_interval_ms,
            }

    def _cooldown_remaining_ms(self) -> int:
        if not self._rate_limited_until:
            return 0
        import time

        return max(0, int((self._rate_limited_until - time.time()) * 1000))


camel_queue_metrics_service = CamelQueueMetricsService()
