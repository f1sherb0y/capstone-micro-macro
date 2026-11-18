from __future__ import annotations

import datetime as dt
import json
import os
import threading
import time
import traceback
from pathlib import Path
from typing import Any


SCHEMA_VERSION = 1


def utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="milliseconds")


def _json_default(value: Any) -> str:
    return str(value)


def atomic_write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    with temporary.open("w", encoding="utf-8") as handle:
        json.dump(data, handle, ensure_ascii=False, indent=2, default=_json_default)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)


def append_jsonl(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(data, ensure_ascii=False, default=_json_default) + "\n")
        handle.flush()
        os.fsync(handle.fileno())


def llm_client_metadata(client: Any) -> dict[str, Any]:
    config = getattr(client, "config", None)
    metadata = {"client_class": type(client).__name__}
    if config is not None:
        for field in ("provider", "model", "base_url", "timeout"):
            value = getattr(config, field, None)
            if value not in (None, ""):
                metadata[field] = value
    return metadata


def exception_details(exc: BaseException) -> dict[str, Any]:
    details: dict[str, Any] = {
        "type": type(exc).__name__,
        "message": str(exc),
        "traceback": "".join(traceback.format_exception(type(exc), exc, exc.__traceback__)),
    }
    for name in ("status_code", "request_id", "code"):
        value = getattr(exc, name, None)
        if value is not None:
            details[name] = value
    response = getattr(exc, "response", None)
    if response is not None:
        response_status = getattr(response, "status_code", None)
        response_body = getattr(response, "text", None)
        if response_status is not None:
            details["response_status_code"] = response_status
        if response_body:
            details["response_body"] = response_body
    return details


class LLMCallAuditLogger:
    """Append-only, durable audit events for every attempted LLM request."""

    def __init__(self, run_dir: Path, case_id: str, client: Any, attempt: int = 1):
        self.path = run_dir / "llm_calls.jsonl"
        self.recovery_path = run_dir / "recovery_events.jsonl"
        self.case_id = case_id
        self.attempt = attempt
        self.client = llm_client_metadata(client)
        self._counter = 0
        self._event_counter = 0
        self._lock = threading.Lock()
        self.path.touch(exist_ok=True)
        self.recovery_path.touch(exist_ok=True)

    def begin(self, marker: str, messages: list[dict[str, str]], temperature: float) -> tuple[str, float]:
        with self._lock:
            self._counter += 1
            call_id = f"attempt_{self.attempt:03d}_call_{self._counter:06d}"
        self._event(
            "request_started",
            call_id,
            marker=marker,
            request={"messages": messages, "temperature": temperature},
            client=self.client,
        )
        return call_id, time.perf_counter()

    def succeeded(self, call_id: str, started: float, content: str, metadata: dict[str, Any] | None = None) -> None:
        self._event(
            "request_succeeded",
            call_id,
            duration_seconds=round(time.perf_counter() - started, 6),
            response={"content": content, "metadata": metadata or {}},
        )

    def failed(self, call_id: str, started: float, exc: BaseException) -> None:
        self._event(
            "request_failed",
            call_id,
            duration_seconds=round(time.perf_counter() - started, 6),
            error=exception_details(exc),
        )

    def parsed(self, call_id: str, data: dict[str, Any]) -> None:
        self._event("response_parsed", call_id, parsed_response=data)

    def parse_failed(self, call_id: str, exc: BaseException) -> None:
        self._event("response_parse_failed", call_id, error=exception_details(exc))

    def contract_failed(self, call_id: str, exc: BaseException) -> None:
        self._event("response_contract_failed", call_id, error=exception_details(exc))

    def contract_validated(self, call_id: str) -> None:
        self._event("response_contract_validated", call_id)

    def normalized(self, call_id: str, marker: str, changes: list[str], data: dict[str, Any]) -> None:
        self._event(
            "response_normalized",
            call_id,
            marker=marker,
            changes=changes,
            normalized_response=data,
        )

    def recovery(self, kind: str, **payload: Any) -> dict[str, Any]:
        event = {
            "schema_version": SCHEMA_VERSION,
            "timestamp": utc_now(),
            "case_id": self.case_id,
            "attempt": self.attempt,
            "kind": kind,
            **payload,
        }
        append_jsonl(self.recovery_path, event)
        return event

    def recovery_events(self) -> list[dict[str, Any]]:
        if not self.recovery_path.exists():
            return []
        return [
            json.loads(line)
            for line in self.recovery_path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]

    @property
    def request_count(self) -> int:
        return self._counter

    def _event(self, event_type: str, call_id: str, **payload: Any) -> None:
        with self._lock:
            self._event_counter += 1
            event = {
                "schema_version": SCHEMA_VERSION,
                "event_sequence": self._event_counter,
                "timestamp": utc_now(),
                "event_type": event_type,
                "case_id": self.case_id,
                "attempt": self.attempt,
                "call_id": call_id,
                **payload,
            }
            append_jsonl(self.path, event)


def write_case_status(run_dir: Path, **values: Any) -> None:
    path = run_dir / "case_status.json"
    current: dict[str, Any] = {}
    if path.exists():
        current = json.loads(path.read_text(encoding="utf-8"))
    current.update(values)
    current["schema_version"] = SCHEMA_VERSION
    current["updated_at"] = utc_now()
    atomic_write_json(path, current)


def write_case_error(run_dir: Path, exc: BaseException, attempt: int = 1) -> None:
    payload = {
        "schema_version": SCHEMA_VERSION,
        "timestamp": utc_now(),
        "attempt": attempt,
        "error": exception_details(exc),
    }
    atomic_write_json(run_dir / "error.json", payload)
    atomic_write_json(run_dir / "errors" / f"attempt_{attempt:03d}.json", payload)


class BatchRunTracker:
    MANIFEST_NAME = "batch_manifest.json"
    EVENTS_NAME = "batch_events.jsonl"

    def __init__(self, batch_dir: Path, manifest: dict[str, Any]):
        self.batch_dir = batch_dir
        self.manifest_path = batch_dir / self.MANIFEST_NAME
        self.events_path = batch_dir / self.EVENTS_NAME
        self.manifest = manifest

    @classmethod
    def create(
        cls,
        output_dir: Path,
        case_ids: list[str],
        *,
        mode: str,
        profile: str,
        config_path: Path,
    ) -> "BatchRunTracker":
        stamp = dt.datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        batch_dir = output_dir / f"batch_{stamp}"
        created_at = utc_now()
        cases = {
            case_id: {
                "status": "pending",
                "attempts": 0,
                "run_dir": f"cases/{case_id.lower()}",
                "started_at": None,
                "completed_at": None,
                "last_error": None,
            }
            for case_id in case_ids
        }
        manifest = {
            "schema_version": SCHEMA_VERSION,
            "batch_id": batch_dir.name,
            "created_at": created_at,
            "updated_at": created_at,
            "status": "running",
            "mode": mode,
            "profile": profile,
            "config_path": str(config_path.resolve()),
            "case_order": case_ids,
            "counts": {},
            "cases": cases,
        }
        tracker = cls(batch_dir, manifest)
        batch_dir.mkdir(parents=True, exist_ok=False)
        tracker._save()
        tracker._event("batch_created", case_count=len(case_ids))
        return tracker

    @classmethod
    def resume(cls, batch_dir: Path) -> "BatchRunTracker":
        batch_dir = batch_dir.resolve()
        manifest_path = batch_dir / cls.MANIFEST_NAME
        if not manifest_path.exists():
            raise FileNotFoundError(f"Batch manifest not found: {manifest_path}")
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        tracker = cls(batch_dir, manifest)
        for case_id, case in manifest["cases"].items():
            if case["status"] == "running":
                case["status"] = "interrupted"
                case["last_error"] = "Previous process ended while this case was running."
                tracker._event("case_interrupted_detected", case_id=case_id)
        manifest["status"] = "running"
        manifest["completed_at"] = None
        tracker._save()
        tracker._event("batch_resumed")
        return tracker

    @property
    def profile(self) -> str:
        return str(self.manifest["profile"])

    @property
    def case_ids(self) -> list[str]:
        return list(self.manifest["case_order"])

    def remaining_case_ids(self) -> list[str]:
        return [
            case_id
            for case_id in self.case_ids
            if self.manifest["cases"][case_id]["status"] not in {"succeeded", "degraded"}
        ]

    def case_dir(self, case_id: str) -> Path:
        return self.batch_dir / self.manifest["cases"][case_id]["run_dir"]

    def start_case(self, case_id: str) -> Path:
        case = self.manifest["cases"][case_id]
        case["attempts"] += 1
        case["status"] = "running"
        case["started_at"] = utc_now()
        case["completed_at"] = None
        case["last_error"] = None
        run_dir = self.case_dir(case_id)
        run_dir.mkdir(parents=True, exist_ok=True)
        self._save()
        self._event("case_started", case_id=case_id, attempt=case["attempts"], run_dir=str(run_dir))
        return run_dir

    def succeed_case(self, case_id: str) -> None:
        self.complete_case(case_id, "succeeded")

    def complete_case(self, case_id: str, status: str) -> None:
        if status not in {"succeeded", "degraded"}:
            raise ValueError(f"Unsupported completed case status: {status}")
        case = self.manifest["cases"][case_id]
        case["status"] = status
        case["completed_at"] = utc_now()
        case["last_error"] = None
        self._save()
        self._event(
            "case_succeeded" if status == "succeeded" else "case_degraded",
            case_id=case_id,
            attempt=case["attempts"],
            status=status,
        )

    def fail_case(self, case_id: str, exc: BaseException, *, interrupted: bool = False) -> None:
        case = self.manifest["cases"][case_id]
        case["status"] = "interrupted" if interrupted else "failed"
        case["completed_at"] = utc_now()
        case["last_error"] = f"{type(exc).__name__}: {exc}"
        self._save()
        self._event(
            "case_interrupted" if interrupted else "case_failed",
            case_id=case_id,
            attempt=case["attempts"],
            error=exception_details(exc),
        )

    def finalize(self, *, interrupted: bool = False) -> None:
        statuses = [case["status"] for case in self.manifest["cases"].values()]
        if interrupted:
            status = "interrupted"
        elif all(item == "succeeded" for item in statuses):
            status = "completed"
        elif all(item in {"succeeded", "degraded"} for item in statuses):
            status = "completed_with_degraded"
        else:
            status = "completed_with_failures"
        self.manifest["status"] = status
        self.manifest["completed_at"] = utc_now()
        self._save()
        self._event("batch_finished", status=status, counts=self.manifest["counts"])

    def _save(self) -> None:
        counts: dict[str, int] = {}
        for case in self.manifest["cases"].values():
            status = case["status"]
            counts[status] = counts.get(status, 0) + 1
        self.manifest["counts"] = counts
        self.manifest["updated_at"] = utc_now()
        atomic_write_json(self.manifest_path, self.manifest)

    def _event(self, event_type: str, **payload: Any) -> None:
        append_jsonl(
            self.events_path,
            {
                "schema_version": SCHEMA_VERSION,
                "timestamp": utc_now(),
                "event_type": event_type,
                **payload,
            },
        )
