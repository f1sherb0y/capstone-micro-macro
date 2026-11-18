"""Submission recovery through host-supplied bindings; no built-in macro writes."""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass

from src.coordination.tasks import TaskConflict, TaskIdentity, TaskStore, task_digest, _text


@dataclass(frozen=True)
class SubmissionRequest:
    identity: TaskIdentity
    output: dict
    output_sha256: str
    binding_id: str
    macro_version: str

    def receipt_identity(self):
        return {"run_id": self.identity.run_id, "organization_id": self.identity.organization_id,
                "request_id": self.identity.request_id, "task_sha256": task_digest(self.identity.as_dict()),
                "output_sha256": self.output_sha256, "binding_id": self.binding_id,
                "macro_version": self.macro_version}


class TaskSubmission:
    """A host must supply actual transport, receipt validation and fresh checks.

    Receipt validation translates the macro's original reply to an envelope;
    the original receipt remains attached as evidence. Query returning None
    means unknown, including 'not found' unless a versioned protocol proves
    definitively that execution never happened. No automatic resubmit exists.
    """

    def __init__(self, store: TaskStore, *, binding_id: str, macro_version: str,
                 action_ids, submit, validate_receipt, revalidate, query=None):
        _text(binding_id)
        _text(macro_version)
        if not all(callable(value) for value in (submit, validate_receipt, revalidate)):
            raise ValueError("Explicit submit, receipt validator and fresh authorization checks are required")
        if query is not None and not callable(query):
            raise ValueError("Receipt query must be callable or explicitly unavailable")
        self.action_ids = frozenset(action_ids)
        if not self.action_ids:
            raise ValueError("Explicit supported action identities are required")
        for action_id in self.action_ids:
            _text(action_id)
        self.store, self.binding_id, self.macro_version = store, binding_id, macro_version
        self.submit, self.query = submit, query
        self.validate_receipt, self.revalidate = validate_receipt, revalidate

    def _request(self, identity, row):
        if identity.action_id not in self.action_ids:
            raise TaskConflict("Action is outside this submission binding")
        if row["submission"] is not None and row["submission"] != {
                "binding_id": self.binding_id, "macro_version": self.macro_version,
                "request_id": identity.request_id}:
            raise TaskConflict("Submission binding, macro version or original request changed")
        if row["output"] is None or task_digest(row["output"]) != row["output_sha256"]:
            raise TaskConflict("Submission requires an intact validated output")
        return SubmissionRequest(TaskIdentity(**identity.as_dict()), deepcopy(row["output"]),
                                 row["output_sha256"], self.binding_id, self.macro_version)

    def _receipt(self, request, raw):
        original = deepcopy(raw)
        if not isinstance(original, dict) or not original:
            raise TaskConflict("Original macro receipt evidence is required")
        original_sha256 = task_digest(original)
        # Own the validated result too: a transport/validator may retain its
        # returned dictionaries and change them after this boundary returns.
        receipt = deepcopy(self.validate_receipt(deepcopy(request), deepcopy(original)))
        fields = {*request.receipt_identity(), "receipt_id", "disposition", "original_receipt"}
        if not isinstance(receipt, dict) or set(receipt) != fields:
            raise TaskConflict("Receipt validator must return an exact correlated receipt envelope")
        if any(receipt[key] != value for key, value in request.receipt_identity().items()):
            raise TaskConflict("Receipt belongs to another invocation, output or macro binding")
        _text(receipt["receipt_id"])
        if receipt["disposition"] not in {"accepted", "rejected"}:
            raise TaskConflict("Receipt disposition must be explicit")
        if not isinstance(receipt["original_receipt"], dict) or not receipt["original_receipt"]:
            raise TaskConflict("Original macro receipt evidence is required")
        if task_digest(receipt['original_receipt']) != original_sha256:
            raise TaskConflict("Receipt validator changed the original macro reply")
        task_digest(receipt)
        return receipt

    def _check_receipt_observation(self, request, receipt):
        """Check an authenticated envelope against current submission history.

        Native effect readers also use this read-only check: observing cash or
        an issued document must not contradict a confirmed registration reply.
        """
        with self.store._lock:
            row = self.store.get(request.identity)
            current = self._request(request.identity, row)
            if current.receipt_identity() != request.receipt_identity():
                raise TaskConflict('Late receipt changes its original submission identity')
            if row['state'] == 'reconciled':
                if receipt is not None and task_digest(receipt) != task_digest(row['receipt']):
                    raise TaskConflict('Late receipt conflicts with the confirmed original receipt')
            elif row['state'] not in {'waiting_receipt', 'receipt_unknown'}:
                raise TaskConflict('Late receipt has no original uncertain submission')
            return row

    def _finish_observation(self, request, *, receipt=None, reason_code=None):
        """Reconcile once; failed/empty late queries preserve confirmed results.

        Transport and receipt validation stay outside the journal lock. Another
        observer may have confirmed the receipt while they were in progress.
        """
        with self.store._lock:
            row = self._check_receipt_observation(request, receipt)
            if row['state'] == 'reconciled':
                return row
            if receipt is None:
                return self.store.unknown_receipt(request.identity, row['revision'], reason_code=reason_code)
            return self.store.reconcile(request.identity, row['revision'], receipt=receipt)

    def execute(self, identity):
        row = self.store.get(identity)
        request = self._request(identity, row)
        if row["state"] == "reconciled":
            return row
        if row["state"] in {"waiting_receipt", "receipt_unknown"}:
            return self.recover(identity)
        if row["state"] != "output_formed":
            raise TaskConflict("Only formed output can be submitted")
        if self.revalidate(deepcopy(request)) is not None:
            raise TaskConflict("Fresh fact and authorization validation must succeed explicitly")
        # Commit uncertainty before crossing the transport boundary. A crash
        # anywhere after this point can only be resolved via the original ID.
        row = self.store.begin_submission(identity, row["revision"],
                                          binding_id=self.binding_id, macro_version=self.macro_version)
        try:
            raw = self.submit(deepcopy(request))
            receipt = self._receipt(request, raw)
        except Exception as exc:
            return self._finish_observation(request, reason_code=type(exc).__name__)
        return self._finish_observation(request, receipt=receipt)

    def recover(self, identity):
        row = self.store.get(identity)
        request = self._request(identity, row)
        if row["state"] == "reconciled":
            return row
        if row["state"] not in {"waiting_receipt", "receipt_unknown"}:
            raise TaskConflict("Task has no uncertain submission to reconcile")
        if self.query is None:
            return self._finish_observation(request, reason_code="receipt_query_unavailable")
        # Query is read-only and must remain possible after submit authority
        # expires. Its binding is responsible for current receipt-read access.
        try:
            raw = self.query(deepcopy(request))
            receipt = self._receipt(request, raw) if raw is not None else None
        except Exception as exc:
            return self._finish_observation(request, reason_code=type(exc).__name__)
        if receipt is None:
            return self._finish_observation(request, reason_code="receipt_not_confirmed")
        return self._finish_observation(request, receipt=receipt)
