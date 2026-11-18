"""Registered, computable resume conditions and transactional successor tasks.

Signals and callbacks belong to a trusted host. A signal is a scheduling hint,
never proof of current facts, authorization, an acceptance or a receipt.
"""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
import json
from typing import Callable, Literal

from src.actions.contracts.common import Reference, ResumeCondition, StrictRecord, TextId, TimePoint
from src.coordination.tasks import TaskConflict, TaskIdentity, TaskStore, canonical, task_digest, _text


class ResumeSignal(StrictRecord):
    run_id: TextId
    organization_id: TextId
    event_id: TextId
    trigger: Literal["event", "time", "dependency_change"]
    business_time: TimePoint
    object_refs: list[Reference]
    payload: dict


@dataclass(frozen=True)
class ConditionProfile:
    action_id: str
    condition_code: str
    version: str
    triggers: frozenset[str]
    evaluate: Callable

    def __post_init__(self):
        for value in (self.action_id, self.condition_code, self.version):
            _text(value)
        if (not isinstance(self.triggers, frozenset) or not self.triggers
                or not self.triggers <= {"event", "time", "dependency_change"}
                or not callable(self.evaluate)):
            raise ValueError("A computable condition profile and explicit supported triggers are required")


class ConditionRegistry:
    def __init__(self, profiles):
        self._profiles = {}
        for profile in profiles:
            if not isinstance(profile, ConditionProfile):
                raise ValueError("Only explicit condition profiles may be registered")
            key = (profile.action_id, profile.condition_code)
            if key in self._profiles:
                raise ValueError("Duplicate condition profile")
            self._profiles[key] = profile

    def get(self, action_id, condition):
        profile = self._profiles.get((action_id, condition.condition_code))
        if profile is None or condition.trigger not in profile.triggers:
            raise TaskConflict("Resume condition is not registered for this action and trigger")
        return profile


@dataclass(frozen=True)
class ConditionCheck:
    source: dict
    condition: ResumeCondition
    signal: ResumeSignal


@dataclass(frozen=True)
class ContinuationPreparation:
    successor: TaskIdentity
    facts_sha256: str
    authorization_sha256: str
    next_input: dict
    next_context: dict

    def __post_init__(self):
        # Reuse the exact digest validation of task identities.
        TaskIdentity(**(self.successor.as_dict() | {
            "input_sha256": self.facts_sha256, "context_sha256": self.authorization_sha256}))
        if (not isinstance(self.next_input, dict) or not self.next_input
                or not isinstance(self.next_context, dict) or not self.next_context
                or task_digest(self.next_input) != self.successor.input_sha256
                or task_digest(self.next_context) != self.successor.context_sha256):
            raise ValueError("Exact successor input and context snapshots must match their invocation digests")


class ContinuationJournal:
    """Persist conditions and link one successor without replaying old decisions.

    All conditions must be recomputed against current authorized host views.
    Unsupported/unknown conditions remain pending. The host prepares the next
    protocol invocation and revalidates it before the atomic queue insertion;
    execution of that new task still performs the normal action checks.
    """

    def __init__(self, store: TaskStore, registry: ConditionRegistry):
        self.store, self.registry = store, registry
        with store._transaction():
            store._db.execute("CREATE TABLE IF NOT EXISTS resume_waits (source_key TEXT PRIMARY KEY, record TEXT NOT NULL)")
            store._db.execute("CREATE TABLE IF NOT EXISTS resume_signals (signal_key TEXT PRIMARY KEY, record TEXT NOT NULL)")

    def register(self, identity, revision, *, conditions, validate_wait):
        if type(revision) is not int or revision < 0:
            raise ValueError("A nonnegative task revision is required")
        conditions = [ResumeCondition.model_validate(condition).model_dump(mode="json") for condition in conditions]
        if not conditions or len({canonical(c) for c in conditions}) != len(conditions):
            raise ValueError("Nonempty, distinct resume conditions are required")
        profiles = []
        for raw in conditions:
            condition = ResumeCondition.model_validate(raw)
            if condition.trigger == "time" and condition.earliest_time is None:
                raise ValueError("Time scheduling requires an explicit business time")
            if condition.trigger == "dependency_change" and not condition.object_refs:
                raise ValueError("Dependency scheduling requires explicit object references")
            if len({(ref.kind, ref.id) for ref in condition.object_refs}) != len(condition.object_refs):
                raise ValueError("A dependency cannot contain multiple versions of the same object")
            profiles.append(self.registry.get(identity.action_id, condition).version)
        row = self.store.get(identity)
        if identity.purpose == "host-audit-checkpoint":
            raise TaskConflict("Private host audit tasks cannot become organization continuations")
        if validate_wait(deepcopy(row), deepcopy(conditions)) is not True:
            raise TaskConflict("Current wait facts and authorization must be explicitly validated")
        with self.store._transaction():
            current = self.store._read(identity)
            self.store._check_not_continued(identity)
            if [self.registry.get(identity.action_id, ResumeCondition.model_validate(raw)).version
                    for raw in conditions] != profiles:
                raise TaskConflict("Resume condition profile changed during wait validation")
            if current != row or current["revision"] != revision or current["state"] not in {"waiting_input", "processing"}:
                raise TaskConflict("Task revision or lifecycle changed during wait validation")
            current.update(state="waiting_input", revision=revision + 1, conditions=deepcopy(conditions), error_code=None)
            wait = {"identity": identity.as_dict(), "revision": current["revision"],
                    "conditions": conditions, "profile_versions": profiles}
            self.store._db.execute("INSERT INTO resume_waits VALUES (?, ?) ON CONFLICT(source_key) "
                                   "DO UPDATE SET record=excluded.record", (identity.key, canonical(wait)))
            return self.store._write(identity, current, "resume_conditions_registered")

    def _signal(self, signal):
        signal = ResumeSignal.model_validate(signal).model_dump(mode="json")
        if signal["run_id"] != self.store.run_id or signal["organization_id"] not in self.store.organization_ids:
            raise TaskConflict("Resume signal run or recipient mismatch")
        key = task_digest([signal["run_id"], signal["organization_id"], signal["event_id"]])
        encoded = canonical(signal)
        with self.store._transaction():
            old = self.store._db.execute("SELECT record FROM resume_signals WHERE signal_key=?", (key,)).fetchone()
            if old is not None and old[0] != encoded:
                raise TaskConflict("Immutable resume signal changed for its event and recipient")
            self.store._db.execute("INSERT OR IGNORE INTO resume_signals VALUES (?, ?)", (key, encoded))
        return ResumeSignal.model_validate(signal)

    def pending(self, *, run_id, organization_id):
        if run_id != self.store.run_id or organization_id not in self.store.organization_ids:
            raise TaskConflict("Pending continuation run or recipient mismatch")
        with self.store._lock:
            rows = self.store._db.execute("SELECT w.record FROM resume_waits w LEFT JOIN continuation_links l "
                                         "ON w.source_key=l.source_key WHERE l.source_key IS NULL ORDER BY w.source_key").fetchall()
            return [json.loads(row[0]) for row in rows
                    if json.loads(row[0])["identity"]["organization_id"] == organization_id
                    and self.store._read(TaskIdentity(**json.loads(row[0])['identity']))['state'] != 'wait_resolved']

    @staticmethod
    def _matches(condition, signal):
        if condition.trigger != signal.trigger:
            return False
        if condition.trigger == "time":
            return True
        if not condition.object_refs:
            return condition.trigger == "event"
        # Tokens are opaque versions. A change is an invalidation hint, not an
        # ordering assertion or permission to adopt the signal's object data.
        for old in condition.object_refs:
            for current in signal.object_refs:
                if (old.kind, old.id) == (current.kind, current.id):
                    if condition.trigger == "event" or old.version != current.version:
                        return True
        return False

    def wake(self, signal, *, prepare, revalidate, action_ids=None, source_keys=None):
        signal = self._signal(signal)
        selected_actions = None if action_ids is None else frozenset(action_ids)
        selected_sources = None if source_keys is None else frozenset(source_keys)
        linked = []
        for wait in self.pending(run_id=signal.run_id, organization_id=signal.organization_id):
            if selected_actions is not None and wait['identity']['action_id'] not in selected_actions:
                continue
            if selected_sources is not None and TaskIdentity(**wait['identity']).key not in selected_sources:
                continue
            conditions = [ResumeCondition.model_validate(raw) for raw in wait["conditions"]]
            if not any(self._matches(condition, signal) for condition in conditions):
                continue
            identity = TaskIdentity(**wait["identity"])
            source = self.store.get(identity)
            if source["revision"] != wait["revision"] or source["state"] != "waiting_input":
                # A worker may have started the original task legitimately.
                continue
            if source["conditions"] != wait["conditions"]:
                raise TaskConflict("Stored resume conditions no longer match the source task")
            ready = True
            for condition, version in zip(conditions, wait["profile_versions"], strict=True):
                profile = self.registry.get(identity.action_id, condition)
                if profile.version != version:
                    raise TaskConflict("Resume condition profile version changed; re-register with current facts")
                earliest = condition.earliest_time
                if earliest is not None and (earliest.clock_ref != signal.business_time.clock_ref
                                              or signal.business_time.offset < earliest.offset):
                    ready = False
                    break
                outcome = profile.evaluate(ConditionCheck(deepcopy(source), condition.model_copy(deep=True),
                                                         signal.model_copy(deep=True)))
                if outcome not in {"ready", "waiting", "unavailable"}:
                    raise TaskConflict("Condition evaluator must return ready, waiting or unavailable")
                if outcome != "ready":
                    ready = False
                    break
            if not ready:
                continue
            preparation = prepare(deepcopy(source), signal.model_copy(deep=True))
            if not isinstance(preparation, ContinuationPreparation):
                raise TaskConflict("Host must supply a validated next invocation and fact/authorization digests")
            # Defensive reconstruction isolates mutable maps supplied by callbacks.
            preparation = ContinuationPreparation(TaskIdentity(**preparation.successor.as_dict()),
                                                 preparation.facts_sha256, preparation.authorization_sha256,
                                                 deepcopy(preparation.next_input), deepcopy(preparation.next_context))
            if revalidate(deepcopy(source), deepcopy(preparation), signal.model_copy(deep=True)) is not True:
                raise TaskConflict("Fresh continuation facts and authorization must be explicitly validated")
            linked.append(self._link(wait, source, preparation, signal))
        return linked

    def _link(self, wait, source, preparation, signal):
        previous = TaskIdentity(**source["identity"])
        successor = TaskIdentity(**preparation.successor.as_dict())
        fields = ("run_id", "organization_id", "role", "action_id", "purpose")
        if any(getattr(previous, name) != getattr(successor, name) for name in fields):
            raise TaskConflict("A continuation cannot switch run, recipient, role, action or purpose")
        if previous.key == successor.key or all(getattr(previous, name) == getattr(successor, name)
                for name in ("input_sha256", "context_sha256", "versions")):
            raise TaskConflict("Continuation requires a new request ID and fresh input, context or execution versions")
        evidence = {"source": previous.as_dict(), "successor": successor.as_dict(),
                    "source_revision": source["revision"], "conditions": wait["conditions"],
                    "profile_versions": wait["profile_versions"], "signal": signal.model_dump(mode="json"),
                    "facts_sha256": preparation.facts_sha256, "authorization_sha256": preparation.authorization_sha256,
                    "next_input": deepcopy(preparation.next_input), "next_context": deepcopy(preparation.next_context)}
        evidence["evidence_sha256"] = task_digest(evidence)
        with self.store._transaction():
            saved = self.store.continuation(previous)
            if saved is not None:
                # Another dispatcher may have won while callbacks ran. Never
                # create a second successor even if the host proposed a new ID.
                return saved
            current_wait = self.store._db.execute("SELECT record FROM resume_waits WHERE source_key=?", (previous.key,)).fetchone()
            if current_wait is None or json.loads(current_wait[0]) != wait or self.store._read(previous) != source:
                raise TaskConflict("Waiting task changed during continuation validation")
            if [self.registry.get(previous.action_id, ResumeCondition.model_validate(raw)).version
                    for raw in wait["conditions"]] != wait["profile_versions"]:
                raise TaskConflict("Resume condition profile changed during continuation validation")
            if self.store._read(successor) is not None:
                raise TaskConflict("Next invocation already exists outside this continuation")
            new = {"identity": successor.as_dict(), "revision": 0, "state": "waiting_input",
                   "output": None, "output_sha256": None, "submission": None, "receipt": None,
                   "conditions": [], "error_code": None}
            self.store._write(successor, new, "continuation_created")
            old = deepcopy(source)
            old["revision"] += 1
            self.store._write(previous, old, "continued_with_new_invocation")
            self.store._db.execute("INSERT INTO continuation_links VALUES (?, ?, ?)",
                                   (previous.key, successor.key, canonical(evidence)))
        return deepcopy(evidence)

    def ready(self, *, run_id, organization_id):
        if run_id != self.store.run_id or organization_id not in self.store.organization_ids:
            raise TaskConflict("Ready continuation run or recipient mismatch")
        with self.store._lock:
            links = [json.loads(row[0]) for row in self.store._db.execute("SELECT record FROM continuation_links ORDER BY source_key")]
            ready = []
            for link in links:
                if link["successor"]["organization_id"] != organization_id:
                    continue
                link = self.store.continuation(TaskIdentity(**link["source"]))
                row = self.store.get(TaskIdentity(**link["successor"]))
                if (row["state"] == "waiting_input" and not row["conditions"]
                        and self.store.continuation(TaskIdentity(**row["identity"])) is None):
                    ready.append({"task": row, "continuation": link})
            return ready
