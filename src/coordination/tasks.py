"""Transactional, run-local task journal with immutable invocation identities."""
from __future__ import annotations

from contextlib import contextmanager
from copy import deepcopy
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import re
import sqlite3
import threading


class TaskConflict(ValueError):
    """The task identity, revision or lifecycle does not permit this operation."""


def canonical(value) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)


def task_digest(value) -> str:
    return hashlib.sha256(canonical(value).encode("utf-8")).hexdigest()


def _text(value):
    if not isinstance(value, str) or not value.strip():
        raise ValueError("Nonempty identity text is required")


@dataclass(frozen=True)
class TaskIdentity:
    run_id: str
    organization_id: str
    role: str
    action_id: str
    request_id: str
    purpose: str
    input_sha256: str
    context_sha256: str
    versions: dict[str, str]

    def as_dict(self):
        return {name: deepcopy(getattr(self, name)) for name in self.__dataclass_fields__}

    def __post_init__(self):
        for name in ("run_id", "organization_id", "role", "action_id", "request_id", "purpose"):
            _text(getattr(self, name))
        for name in ("input_sha256", "context_sha256"):
            value = getattr(self, name)
            if not isinstance(value, str) or re.fullmatch(r"[0-9a-f]{64}", value) is None:
                raise ValueError("SHA256 task input and context digests are required")
        if (not isinstance(self.versions, dict) or set(self.versions) != {
                "client", "skill", "prompt", "contract", "method", "model", "strategy"}):
            raise ValueError("All seven execution version identities are required")
        for value in self.versions.values():
            _text(value)
        object.__setattr__(self, "versions", deepcopy(self.versions))

    @property
    def key(self):
        return task_digest([self.run_id, self.organization_id, self.purpose, self.request_id])


class TaskStore:
    """Owns technical lifecycle and opaque evidence, never a domain ledger.

    SQLite transactions and revision checks serialize writers across processes.
    Interrupted processing is retained until the host explicitly diagnoses it;
    opening a second connection does not imply the first worker has stopped.
    """

    SCHEMA = "micro-task-store.v1"
    STATES = frozenset({"waiting_input", "processing", "output_formed", "waiting_receipt",
                        "receipt_unknown", "reconciled", "technical_failure", "wait_resolved"})

    def __init__(self, *, run_id: str, organization_ids, path: Path | None = None):
        _text(run_id)
        recipients = sorted(set(organization_ids))
        if not recipients:
            raise ValueError("Explicit task recipients are required")
        for recipient in recipients:
            _text(recipient)
        self.run_id = run_id
        self.organization_ids = frozenset(recipients)
        self.path = Path(path) if path is not None else None
        if self.path is not None:
            self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._db = sqlite3.connect(str(self.path) if self.path else ":memory:",
                                   isolation_level=None, check_same_thread=False, timeout=30)
        try:
            self._db.execute("PRAGMA synchronous=FULL")
            with self._transaction():
                self._db.execute("CREATE TABLE IF NOT EXISTS metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
                self._db.execute("CREATE TABLE IF NOT EXISTS tasks (key TEXT PRIMARY KEY, record TEXT NOT NULL)")
                self._db.execute("CREATE TABLE IF NOT EXISTS transitions (sequence INTEGER PRIMARY KEY, "
                                 "task_key TEXT NOT NULL, record TEXT NOT NULL)")
                self._db.execute("CREATE TABLE IF NOT EXISTS continuation_links (source_key TEXT PRIMARY KEY, "
                                 "successor_key TEXT UNIQUE NOT NULL, record TEXT NOT NULL)")
                self._db.execute("CREATE TABLE IF NOT EXISTS wait_resolutions (source_key TEXT PRIMARY KEY, record TEXT NOT NULL)")
                identity = {"schema_version": self.SCHEMA, "run_id": run_id, "organization_ids": recipients}
                saved = self._db.execute("SELECT value FROM metadata WHERE key='identity'").fetchone()
                if saved is None:
                    tables = {row[0] for row in self._db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
                    if any(self._db.execute(f"SELECT COUNT(*) FROM {name}").fetchone()[0]
                           for name in ('qs_cost_calculation_records', 'qs_cost_calculation_publications',
                                        'qs_change_calculation_records', 'qs_change_calculation_publications',
                                        'qs_payment_calculation_records', 'qs_payment_calculation_publications',
                                        'qs_payment_calculation_targets', 'qs_final_account_calculation_records',
                                        'qs_final_account_calculation_publications',
                                        'qs_procurement_document_records', 'qs_procurement_document_publications',
                                        'qs_bid_normalization_records', 'qs_bid_normalization_publications',
                                        'qs_bid_ranking_records', 'qs_bid_ranking_publications',
                                        'qs_billing_calculation_records', 'qs_billing_calculation_publications',
                                        'qs_learning_comparability_records', 'qs_learning_comparability_publications',
                                        'qs_learning_error_records', 'qs_learning_error_publications',
                                        'qs_learning_assessment_records', 'qs_learning_assessment_publications',
                                        'qs_training_estimate_records', 'qs_training_estimate_publications',
                                        'qs_research_normalization_records', 'qs_research_normalization_publications',
                                        'qs_research_ranking_records', 'qs_research_ranking_publications',
                                        'architect_learning_assessment_records',
                                        'architect_learning_assessment_publications',
                                        'architect_training_estimate_records',
                                        'architect_training_estimate_publications',
                                        'architect_area_calculation_records',
                                        'architect_area_calculation_publications',
                                        'architect_interface_consistency_records',
                                        'architect_interface_consistency_publications',
                                        'engineer_learning_assessment_records',
                                        'engineer_learning_assessment_publications',
                                        'engineer_training_estimate_records',
                                        'engineer_training_estimate_publications',
                                        'engineer_parameter_records',
                                        'engineer_parameter_publications',
                                        'engineer_interface_check_records',
                                        'engineer_interface_check_publications',
                                        'engineer_review_check_records',
                                        'engineer_review_check_publications',
                                        'engineer_research_check_records',
                                        'engineer_research_check_publications',
                                        'engineer_research_estimate_records',
                                        'engineer_research_estimate_publications',
                                        'engineer_inspection_check_records',
                                        'engineer_inspection_check_publications',
                                        'engineer_change_check_records',
                                        'engineer_change_check_publications',
                                        'engineer_change_parameter_records',
                                        'engineer_change_parameter_publications',
                                        'engineer_change_revision_check_records',
                                        'engineer_change_revision_check_publications',
                                        'architect_change_impact_records',
                                        'architect_change_impact_publications',
                                        'architect_research_estimate_records',
                                        'architect_research_estimate_publications') if name in tables):
                        raise TaskConflict('Stored QS calculation evidence is missing its run identity')
                    if any(self._db.execute(f"SELECT COUNT(*) FROM {name}").fetchone()[0]
                           for name in ("tasks", "continuation_links", "resume_waits", "resume_signals", "invocation_snapshots", "commercial_action_results", "contractor_bid_results", "contractor_screening_results", "contractor_amendment_results", "contractor_formation_results", "contractor_planning_results", "contractor_readiness_results", "contractor_execution_results", "contractor_quality_results", "contractor_claim_results", "contractor_payment_results", "contractor_closeout_results", "contractor_advice_results", "architect_opportunity_results", "architect_intake_results", "architect_appointment_results", "architect_planning_results", "architect_design_results", "architect_integration_results", "architect_deliverable_results", "architect_review_results", "architect_change_results", "architect_billing_results", "architect_transition_results", "architect_learning_results", "architect_research_results", "engineer_opportunity_results", "engineer_intake_results", "engineer_appointment_results", "engineer_planning_results", "engineer_design_results", "engineer_review_results", "engineer_deliverable_results", "engineer_inspection_results", "engineer_change_results", "engineer_billing_results", "engineer_transition_results", "engineer_learning_results", "engineer_research_results", "qs_market_results", "qs_intake_results", "qs_appointment_results", "qs_cost_results", "qs_procurement_results", "qs_bid_results", "qs_change_results", "qs_payment_results", "qs_final_account_results", "qs_billing_results", "qs_transition_results", "qs_learning_results", "qs_research_results", "government_advice_results", "government_intake_results", "government_scheduling_results", "government_review_results", "government_consultation_results", "government_supplement_results", "government_decision_results", "government_permit_results", "government_transition_results", "government_inspection_results", "government_use_results", "government_feedback_results", "owner_observation_results", "owner_proposal_results", "owner_study_results", "owner_investment_results", "owner_commission_results", "owner_financing_results", "owner_payment_results", "owner_design_results", "owner_regulatory_results", "owner_tender_results", "owner_award_results", "owner_contract_results", "owner_closeout_results", "owner_continuation_results", "owner_asset_results", "owner_operating_results", "bank_strategy_results", "bank_intake_results", "bank_credit_results", "bank_quote_results", "bank_arrangement_results", "bank_draw_results", "bank_execution_results", "bank_monitoring_results", "bank_debt_results", "bank_resolution_results", "bank_closeout_results", "bank_learning_results", "bank_advice_results", "supplier_screening_results", "supplier_product_results", "supplier_quote_results", "supplier_order_results", "supplier_planning_results", "supplier_execution_results", "supplier_quality_results", "supplier_logistics_results", "supplier_receiving_results", "supplier_payment_results", "supplier_remedy_results", "supplier_advice_results", "model_call_budgets", "model_call_reservations", "gba_tender_feedback", "gba_tender_publications", "gba_tender_published_objects", "supplier_quote_cost_publications", "supplier_quote_cost_objects", "supplier_quote_cost_read_points", "supplier_source_reads") if name in tables):
                        raise TaskConflict("Stored tasks are missing their run identity")
                    self._db.execute("INSERT INTO metadata VALUES ('identity', ?)", (canonical(identity),))
                elif json.loads(saved[0]) != identity:
                    raise TaskConflict("Task store belongs to another run, schema or recipient set")
        except BaseException:
            self._db.close()
            raise

    @contextmanager
    def _transaction(self):
        with self._lock:
            self._db.execute("BEGIN IMMEDIATE")
            try:
                yield
                self._db.execute("COMMIT")
            except BaseException:
                self._db.execute("ROLLBACK")
                raise

    def close(self):
        with self._lock:
            self._db.close()

    def attach_simulation(self, simulation_id: str):
        _text(simulation_id)
        with self._transaction():
            saved = self._db.execute("SELECT value FROM metadata WHERE key='simulation_id'").fetchone()
            if saved and json.loads(saved[0]) != simulation_id:
                raise TaskConflict("Task store is attached to another simulation; use its actual resume capability")
            if saved is None:
                self._db.execute("INSERT INTO metadata VALUES ('simulation_id', ?)", (canonical(simulation_id),))

    def _read(self, identity):
        # Reconstruct to detect mutated version maps even on a frozen dataclass.
        identity = TaskIdentity(**identity.as_dict())
        if identity.run_id != self.run_id or identity.organization_id not in self.organization_ids:
            raise TaskConflict("Task run or recipient mismatch")
        saved = self._db.execute("SELECT record FROM tasks WHERE key=?", (identity.key,)).fetchone()
        row = json.loads(saved[0]) if saved else None
        if row is not None and (not isinstance(row, dict) or "identity" not in row):
            raise TaskConflict("Stored task is missing its invocation identity")
        if row is not None and row["identity"] != identity.as_dict():
            raise TaskConflict("Original request ID was reused with different input, context, action or versions")
        if row is not None:
            fields = {"identity", "revision", "state", "output", "output_sha256", "submission",
                      "receipt", "conditions", "error_code"}
            if (set(row) != fields or row["state"] not in self.STATES
                    or type(row["revision"]) is not int or row["revision"] < 0):
                raise TaskConflict("Invalid stored task lifecycle")
            if row["output"] is None:
                if row["output_sha256"] is not None or row["state"] in {
                        "output_formed", "waiting_receipt", "receipt_unknown", "reconciled"}:
                    raise TaskConflict("Stored task is missing its formed output")
            elif task_digest(row["output"]) != row["output_sha256"]:
                raise TaskConflict("Stored task output digest changed")
            if row["state"] in {"waiting_receipt", "receipt_unknown", "reconciled"} and row["submission"] is None:
                raise TaskConflict("Stored task is missing its original submission identity")
            if row["state"] == "reconciled" and row["receipt"] is None:
                raise TaskConflict("Stored task is missing its reconciled receipt")
            if row['state'] == 'wait_resolved':
                resolution = self._read_wait_resolution(identity)
                if (resolution is None or resolution['source_revision'] + 1 != row['revision']
                        or resolution['conditions'] != row['conditions']
                        or any(row[field] is not None for field in ('output', 'output_sha256', 'submission', 'receipt'))):
                    raise TaskConflict('Resolved input wait differs from its terminal evidence or invents a submission')
        return row

    def _write(self, identity, row, event):
        encoded = canonical(row)
        self._db.execute("INSERT INTO tasks VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET record=excluded.record",
                         (identity.key, encoded))
        self._db.execute("INSERT INTO transitions(task_key, record) VALUES (?, ?)",
                         (identity.key, canonical({"revision": row["revision"], "state": row["state"],
                                                  "event": event})))
        return deepcopy(row)

    def _ensure_in_transaction(self, identity: TaskIdentity):
        row = self._read(identity)
        if row is None:
            row = {"identity": identity.as_dict(), "revision": 0, "state": "waiting_input",
                   "output": None, "output_sha256": None, "submission": None, "receipt": None,
                   "conditions": [], "error_code": None}
            return self._write(identity, row, "created")
        return row

    def ensure(self, identity: TaskIdentity):
        with self._transaction():
            return self._ensure_in_transaction(identity)

    def get(self, identity: TaskIdentity):
        with self._lock:
            row = self._read(identity)
            if row is None:
                raise TaskConflict("Task has not been registered")
            return row

    def _change(self, identity, revision, allowed, state, event, **changes):
        if type(revision) is not int or revision < 0:
            raise ValueError("A nonnegative task revision is required")
        with self._transaction():
            row = self._read(identity)
            if row is None or row["revision"] != revision:
                raise TaskConflict("Task revision changed or task is missing")
            self._check_not_continued(identity)
            if row["state"] not in allowed:
                raise TaskConflict(f"Task state {row['state']} does not permit {event}")
            row.update(changes, state=state, revision=revision + 1)
            return self._write(identity, row, event)

    def _check_not_continued(self, identity):
        if self._db.execute("SELECT 1 FROM continuation_links WHERE source_key=?", (identity.key,)).fetchone():
            raise TaskConflict("Task has a successor; the original invocation cannot be restarted")
        if self._db.execute('SELECT 1 FROM wait_resolutions WHERE source_key=?', (identity.key,)).fetchone():
            raise TaskConflict('Task wait has terminal evidence; the original invocation cannot be restarted')

    def _read_wait_resolution(self, identity):
        saved = self._db.execute('SELECT record FROM wait_resolutions WHERE source_key=?', (identity.key,)).fetchone()
        if saved is None:
            return None
        record = json.loads(saved[0])
        fields = {'source', 'source_revision', 'conditions', 'resolution', 'evidence_sha256'}
        if (not isinstance(record, dict) or set(record) != fields or record['source'] != identity.as_dict()
                or type(record['source_revision']) is not int or record['source_revision'] < 0
                or not isinstance(record['resolution'], dict) or not record['resolution']
                or task_digest({key: value for key, value in record.items() if key != 'evidence_sha256'}) != record['evidence_sha256']):
            raise TaskConflict('Stored terminal input-wait evidence changed')
        return record

    def wait_resolution(self, identity):
        with self._lock:
            row = self.get(identity)
            record = self._read_wait_resolution(identity)
            if record is not None and row['state'] != 'wait_resolved':
                raise TaskConflict('Terminal evidence differs from original task lifecycle')
            return deepcopy(record)

    def resolve_wait(self, identity, revision, *, resolution, validate_resolution):
        """Archive a natively resolved input wait without fabricating output or receipt."""
        if (type(revision) is not int or revision < 0 or not isinstance(resolution, dict)
                or not resolution or not callable(validate_resolution)):
            raise ValueError('Terminal wait resolution requires exact revision, evidence and independent validation')
        resolution = deepcopy(resolution)
        canonical(resolution)
        source = self.get(identity)
        if validate_resolution(deepcopy(source), deepcopy(resolution)) is not True:
            raise TaskConflict('Terminal input-wait evidence lacks actual native validation')
        with self._transaction():
            current = self._read(identity)
            saved = self._read_wait_resolution(identity)
            if saved is not None:
                if saved['source_revision'] != revision or saved['resolution'] != resolution:
                    raise TaskConflict('Immutable terminal wait resolution changed')
                return deepcopy(saved)
            self._check_not_continued(identity)
            if (current != source or current['revision'] != revision or current['state'] != 'waiting_input'
                    or not current['conditions'] or any(current[field] is not None for field in ('output', 'submission', 'receipt'))):
                raise TaskConflict('Original input wait changed before terminal reconciliation')
            record = dict(source=identity.as_dict(), source_revision=revision,
                conditions=deepcopy(current['conditions']), resolution=resolution)
            record['evidence_sha256'] = task_digest(record)
            self._db.execute('INSERT INTO wait_resolutions VALUES (?,?)', (identity.key, canonical(record)))
            current.update(state='wait_resolved', revision=revision + 1, error_code=None)
            self._write(identity, current, 'input_wait_resolved')
            return deepcopy(record)

    def continuation(self, identity):
        with self._lock:
            source = self.get(identity)
            saved = self._db.execute("SELECT record FROM continuation_links WHERE source_key=?", (identity.key,)).fetchone()
            if saved is None:
                return None
            link = json.loads(saved[0])
            fields = {"source", "successor", "source_revision", "conditions", "profile_versions", "signal",
                      "facts_sha256", "authorization_sha256", "next_input", "next_context", "evidence_sha256"}
            if (not isinstance(link, dict) or set(link) != fields
                    or task_digest({k: v for k, v in link.items() if k != "evidence_sha256"}) != link["evidence_sha256"]):
                raise TaskConflict("Stored continuation evidence changed")
            successor = TaskIdentity(**link["successor"])
            if (link["source"] != identity.as_dict() or type(link["source_revision"]) is not int
                    or source["revision"] != link["source_revision"] + 1
                    or source["state"] != "waiting_input" or source["conditions"] != link["conditions"]
                    or task_digest(link["next_input"]) != successor.input_sha256
                    or task_digest(link["next_context"]) != successor.context_sha256
                    or self._read(successor) is None):
                raise TaskConflict("Stored continuation differs from its source or successor task")
            return link

    def start(self, identity, revision):
        return self._change(identity, revision, {"waiting_input", "technical_failure"},
                            "processing", "started", error_code=None)

    def wait_for_input(self, identity, revision, *, conditions: list[dict]):
        if not isinstance(conditions, list) or not conditions or any(not isinstance(c, dict) or not c for c in conditions):
            raise ValueError("Explicit pending input conditions are required")
        canonical(conditions)
        return self._change(identity, revision, {"waiting_input", "processing"}, "waiting_input",
                            "waiting_input", conditions=deepcopy(conditions))

    def finish(self, identity, revision, *, output: dict):
        if not isinstance(output, dict) or not output:
            raise ValueError("A validated, nonempty output record is required")
        digest = task_digest(output)
        return self._change(identity, revision, {"processing"}, "output_formed", "output_formed",
                            output=deepcopy(output), output_sha256=digest, conditions=[])

    def fail(self, identity, revision, *, error_code: str):
        _text(error_code)
        return self._change(identity, revision, {"processing"}, "technical_failure",
                            "technical_failure", error_code=error_code)

    def begin_submission(self, identity, revision, *, binding_id: str, macro_version: str):
        _text(binding_id)
        _text(macro_version)
        return self._change(identity, revision, {"output_formed"}, "waiting_receipt", "submission_started",
                            submission={"binding_id": binding_id, "macro_version": macro_version,
                                        "request_id": identity.request_id}, error_code=None)

    def unknown_receipt(self, identity, revision, *, reason_code: str):
        _text(reason_code)
        return self._change(identity, revision, {"waiting_receipt", "receipt_unknown"},
                            "receipt_unknown", "receipt_unknown", error_code=reason_code)

    def reconcile(self, identity, revision, *, receipt: dict):
        if not isinstance(receipt, dict) or not receipt:
            raise ValueError("A validated original receipt is required")
        canonical(receipt)
        return self._change(identity, revision, {"waiting_receipt", "receipt_unknown"},
                            "reconciled", "receipt_reconciled", receipt=deepcopy(receipt), error_code=None)

    def for_organization(self, *, run_id, organization_id, include_host_audit=False):
        if run_id != self.run_id or organization_id not in self.organization_ids:
            raise TaskConflict("Task run or recipient mismatch")
        if type(include_host_audit) is not bool:
            raise ValueError("Host audit access must be selected explicitly by the trusted host")
        with self._lock:
            rows = [json.loads(row[0]) for row in self._db.execute("SELECT record FROM tasks ORDER BY key")]
            return [row for row in rows if row["identity"]["organization_id"] == organization_id
                    and (include_host_audit or row["identity"]["purpose"] != "host-audit-checkpoint")]

    def history(self, identity):
        with self._lock:
            self.get(identity)
            return [json.loads(row[0]) for row in self._db.execute(
                "SELECT record FROM transitions WHERE task_key=? ORDER BY sequence", (identity.key,))]
