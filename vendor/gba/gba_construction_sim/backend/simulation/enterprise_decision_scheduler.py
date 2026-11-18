from __future__ import annotations

import asyncio
from collections import Counter
import os
from threading import Thread
import time
from typing import Optional

from gba_construction_sim.backend.decision.decision_provider import DecisionProvider
from gba_construction_sim.backend.models.action import AgentAction
from gba_construction_sim.backend.models.agent import EnterpriseAgentProfile
from gba_construction_sim.backend.services.agent_cognitive_service import agent_cognitive_service
from gba_construction_sim.backend.services.camel_queue_metrics_service import camel_queue_metrics_service
from gba_construction_sim.backend.simulation.decision_request import (
    DecisionPriority,
    DecisionRequest,
    DecisionResult,
)


class EnterpriseDecisionScheduler:
    def __init__(
        self,
        decision_provider: DecisionProvider,
        *,
        concurrency_limit: Optional[int] = None,
        tick_max_decisions: Optional[int] = None,
        project_max_decisions: Optional[int] = None,
        agent_max_decisions: Optional[int] = None,
    ) -> None:
        self.decision_provider = decision_provider
        self.concurrency_limit = concurrency_limit or int(os.getenv("CAMEL_CONCURRENCY_LIMIT", "8"))
        self.tick_max_decisions = tick_max_decisions or int(os.getenv("CAMEL_TICK_MAX_DECISIONS", "200"))
        self.project_max_decisions = project_max_decisions or int(os.getenv("CAMEL_PROJECT_MAX_DECISIONS", "100"))
        self.agent_max_decisions = agent_max_decisions or int(os.getenv("CAMEL_AGENT_MAX_DECISIONS", "10"))
        self.model_min_interval_ms = self._default_model_min_interval_ms()
        self.rate_limit_cooldown_seconds = int(os.getenv("CAMEL_RATE_LIMIT_COOLDOWN_SECONDS", "60"))
        self.rate_limit_backoff_multiplier = max(1, int(os.getenv("CAMEL_RATE_LIMIT_BACKOFF_MULTIPLIER", "4")))
        self.rate_limit_skip_priority = self._rate_limit_skip_priority()
        self._current_tick: Optional[int] = None
        self._tick_count = 0
        self._project_counts: Counter[str] = Counter()
        self._agent_counts: Counter[str] = Counter()
        self._last_model_start = 0.0
        self._rate_limited_until = 0.0
        self._adaptive_min_interval_ms = self.model_min_interval_ms

    def decide_now(
        self,
        agent: EnterpriseAgentProfile,
        context: dict,
        *,
        decision_type: str,
        priority: DecisionPriority,
        project_id: Optional[str] = None,
    ) -> Optional[AgentAction]:
        request = self.build_request(
            agent,
            context,
            decision_type=decision_type,
            priority=priority,
            project_id=project_id,
        )
        result = self.run_sync([request])[0]
        if result.error:
            raise RuntimeError(result.error)
        if result.skipped_reason:
            return None
        return result.action

    def build_request(
        self,
        agent: EnterpriseAgentProfile,
        context: dict,
        *,
        decision_type: str,
        priority: DecisionPriority,
        project_id: Optional[str] = None,
    ) -> DecisionRequest:
        tick = int(context.get("tick", context.get("current_tick", 0)) or 0)
        project = context.get("project")
        resolved_project_id = project_id or getattr(project, "project_id", None)
        allowed_actions = list(context.get("allowed_actions") or [])
        request_id = self._request_id(tick, resolved_project_id, agent.agent_id, decision_type)
        return DecisionRequest(
            request_id=request_id,
            tick=tick,
            decision_type=decision_type,
            agent=agent,
            context={
                **context,
                "request_id": request_id,
                "decision_type": decision_type,
                "decision_priority": priority.name,
                "recent_messages": context.get("recent_messages", []),
            },
            priority=priority,
            project_id=resolved_project_id,
            allowed_actions=allowed_actions,
        )

    def run_sync(self, requests: list[DecisionRequest]) -> list[DecisionResult]:
        if not requests:
            return []
        coroutine = self.run_batch(requests)
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(coroutine)

        results: list[DecisionResult] = []
        error: list[BaseException] = []

        def runner() -> None:
            try:
                results.extend(asyncio.run(coroutine))
            except BaseException as exc:
                error.append(exc)

        thread = Thread(target=runner, daemon=True)
        thread.start()
        thread.join()
        if error:
            raise error[0]
        return results

    async def run_batch(self, requests: list[DecisionRequest]) -> list[DecisionResult]:
        if not requests:
            return []
        self._ensure_tick(requests[0].tick)
        ordered = sorted(requests, key=lambda request: (int(request.priority), request.project_id or "", request.agent_id))
        camel_queue_metrics_service.mark_queued(len(ordered))
        runnable: list[DecisionRequest] = []
        results: list[DecisionResult] = []
        for request in ordered:
            skipped_reason = self._budget_skip_reason(request)
            if skipped_reason:
                camel_queue_metrics_service.mark_skipped(reason=skipped_reason)
                results.append(DecisionResult(request=request, status="skipped", skipped_reason=skipped_reason))
                continue
            self._reserve_budget(request)
            runnable.append(request)

        completed = await self._drain_queue(runnable)
        results.extend(completed)
        order_by_id = {id(request): index for index, request in enumerate(ordered)}
        sorted_results = sorted(results, key=lambda result: order_by_id[id(result.request)])
        self._record_scheduler_traces(sorted_results)
        return sorted_results

    async def _drain_queue(self, requests: list[DecisionRequest]) -> list[DecisionResult]:
        if not requests:
            return []
        queue: asyncio.Queue[DecisionRequest] = asyncio.Queue()
        for request in requests:
            await queue.put(request)
        semaphore = asyncio.Semaphore(max(1, self.concurrency_limit))
        rate_lock = asyncio.Lock()
        completed: list[DecisionResult] = []

        async def worker() -> None:
            while True:
                request = await queue.get()
                try:
                    completed.append(await self._execute(request, semaphore, rate_lock))
                finally:
                    queue.task_done()

        worker_count = min(len(requests), max(1, self.concurrency_limit))
        workers = [asyncio.create_task(worker()) for _ in range(worker_count)]
        await queue.join()
        for worker_task in workers:
            worker_task.cancel()
        await asyncio.gather(*workers, return_exceptions=True)
        return completed

    async def _execute(
        self,
        request: DecisionRequest,
        semaphore: asyncio.Semaphore,
        rate_lock: asyncio.Lock,
    ) -> DecisionResult:
        async with semaphore:
            queue_ms = int((time.perf_counter() - request.created_at) * 1000)
            camel_queue_metrics_service.mark_started(queue_ms)
            request.context["scheduler"] = {
                "request_id": request.request_id,
                "queue_ms": queue_ms,
                "decision_type": request.decision_type,
                "priority": request.priority.name,
                "status": "running",
            }
            started = time.perf_counter()
            try:
                await self._wait_for_rate_limit(rate_lock)
                decide_async = getattr(self.decision_provider, "decide_async", None)
                if callable(decide_async):
                    action = await decide_async(request.agent, request.context)
                else:
                    action = await asyncio.to_thread(self.decision_provider.decide, request.agent, request.context)
                model_ms = int((time.perf_counter() - started) * 1000)
                request.context["scheduler"].update({"model_ms": model_ms, "status": "completed"})
                camel_queue_metrics_service.mark_completed(model_ms)
                return DecisionResult(
                    request=request,
                    action=action,
                    status="completed",
                    queue_ms=queue_ms,
                    model_ms=model_ms,
                )
            except Exception as exc:
                model_ms = int((time.perf_counter() - started) * 1000)
                request.context["scheduler"].update({"model_ms": model_ms, "status": "failed", "error": str(exc)})
                camel_queue_metrics_service.mark_failed(str(exc), model_ms)
                if self._is_rate_limit_error(exc):
                    self._enter_rate_limit_cooldown()
                return DecisionResult(
                    request=request,
                    status="failed",
                    error=str(exc),
                    queue_ms=queue_ms,
                    model_ms=model_ms,
                )

    async def _wait_for_rate_limit(self, rate_lock: asyncio.Lock) -> None:
        min_interval_ms = self._effective_model_min_interval_ms()
        if min_interval_ms <= 0:
            return
        min_interval = min_interval_ms / 1000
        async with rate_lock:
            now = time.perf_counter()
            wait_seconds = min_interval - (now - self._last_model_start)
            if wait_seconds > 0:
                await asyncio.sleep(wait_seconds)
            self._last_model_start = time.perf_counter()

    @staticmethod
    def _default_model_min_interval_ms() -> int:
        configured = os.getenv("CAMEL_MODEL_MIN_INTERVAL_MS")
        if configured is not None:
            return int(configured)
        platform = (os.getenv("CAMEL_MODEL_PLATFORM") or "").strip().upper().replace("-", "_")
        model = (os.getenv("CAMEL_DECISION_MODEL") or os.getenv("CAMEL_MODEL") or "").strip().lower()
        if platform == "ZHIPU" or model.startswith("glm"):
            return 1200
        return 0

    def _effective_model_min_interval_ms(self) -> int:
        if not self._is_in_rate_limit_cooldown():
            self._adaptive_min_interval_ms = self.model_min_interval_ms
            return self.model_min_interval_ms
        base = max(int(os.getenv("CAMEL_RATE_LIMIT_MIN_INTERVAL_MS", "2000")), self.model_min_interval_ms)
        self._adaptive_min_interval_ms = max(base, base * self.rate_limit_backoff_multiplier)
        return self._adaptive_min_interval_ms

    def _enter_rate_limit_cooldown(self) -> None:
        self._rate_limited_until = max(
            self._rate_limited_until,
            time.time() + max(1, self.rate_limit_cooldown_seconds),
        )
        camel_queue_metrics_service.mark_rate_limited(
            self._rate_limited_until,
            self._effective_model_min_interval_ms(),
        )

    def _is_in_rate_limit_cooldown(self) -> bool:
        return self._rate_limited_until > time.time()

    @staticmethod
    def _is_rate_limit_error(exc: Exception) -> bool:
        text = str(exc).lower()
        return "429" in text or "rate limit" in text or "too many requests" in text

    @staticmethod
    def _record_scheduler_traces(results: list[DecisionResult]) -> None:
        for result in results:
            if result.status == "completed" and result.action is not None and result.request.context.get("trace_recorded_by_provider"):
                continue
            try:
                agent_cognitive_service.record_scheduler_decision_trace(result)
            except Exception:
                continue

    def _ensure_tick(self, tick: int) -> None:
        if self._current_tick == tick:
            return
        self._current_tick = tick
        self._tick_count = 0
        self._project_counts.clear()
        self._agent_counts.clear()
        camel_queue_metrics_service.reset()
        if self._is_in_rate_limit_cooldown():
            camel_queue_metrics_service.mark_rate_limited(
                self._rate_limited_until,
                self._effective_model_min_interval_ms(),
            )

    def _budget_skip_reason(self, request: DecisionRequest) -> Optional[str]:
        if (
            self._is_in_rate_limit_cooldown()
            and int(request.priority) >= int(self.rate_limit_skip_priority)
        ):
            return "camel_rate_limit_cooldown_low_priority"
        if self._tick_count >= self.tick_max_decisions:
            return "camel_tick_budget_exhausted"
        if request.project_id and self._project_counts[request.project_id] >= self.project_max_decisions:
            return "camel_project_budget_exhausted"
        if self._agent_counts[request.agent_id] >= self.agent_max_decisions:
            return "camel_agent_budget_exhausted"
        return None

    @staticmethod
    def _rate_limit_skip_priority() -> DecisionPriority:
        configured = os.getenv("CAMEL_RATE_LIMIT_SKIP_PRIORITY", "P2_INTERACTION")
        try:
            return DecisionPriority[configured]
        except KeyError:
            return DecisionPriority.P2_INTERACTION

    def _reserve_budget(self, request: DecisionRequest) -> None:
        self._tick_count += 1
        if request.project_id:
            self._project_counts[request.project_id] += 1
        self._agent_counts[request.agent_id] += 1

    @staticmethod
    def _request_id(tick: int, project_id: Optional[str], agent_id: str, decision_type: str) -> str:
        project_part = project_id or "no_project"
        return f"tick{tick}-{project_part}-{agent_id}-{decision_type}"
