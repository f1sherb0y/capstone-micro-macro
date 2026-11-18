"""Versioned micro drafts and independently authored decisions, not contracts."""
from __future__ import annotations

from copy import deepcopy
import re

from src.json_input import parse_json_object
from src.coordination.tasks import TaskConflict, TaskStore, canonical, task_digest, _text


class NegotiationJournal:
    """Local evidence only. Hosts authenticate each party and recheck its access.

    Versions preserve the exact draft and input/authorization context. Revising
    leaves historical choices in place but never transfers them to a new draft.
    A unanimous local draft still requires the actual formation/submission gate.
    """

    def __init__(self, *, run_id, organization_ids, path=None):
        self.store = TaskStore(run_id=run_id, organization_ids=organization_ids, path=path)
        self.run_id = run_id
        try:
            with self.store._transaction():
                self.store._db.execute("CREATE TABLE IF NOT EXISTS negotiation_heads "
                                       "(id TEXT PRIMARY KEY, revision INTEGER NOT NULL)")
                self.store._db.execute("CREATE TABLE IF NOT EXISTS negotiation_versions "
                                       "(id TEXT NOT NULL, revision INTEGER NOT NULL, record TEXT NOT NULL, "
                                       "PRIMARY KEY(id, revision))")
                self.store._db.execute("CREATE TABLE IF NOT EXISTS negotiation_events "
                                       "(sequence INTEGER PRIMARY KEY, id TEXT NOT NULL, record TEXT NOT NULL)")
                self.store._db.execute("CREATE TABLE IF NOT EXISTS negotiation_operations "
                                       "(party TEXT NOT NULL, operation TEXT NOT NULL, record TEXT NOT NULL, "
                                       "PRIMARY KEY(party, operation))")
        except BaseException:
            self.store.close()
            raise

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()

    def close(self):
        self.store.close()

    def _party(self, party):
        _text(party)
        if party not in self.store.organization_ids:
            raise TaskConflict("Negotiation party is outside this run's recipient set")

    @staticmethod
    def _revision(revision):
        if type(revision) is not int or revision < 0:
            raise ValueError("An explicit nonnegative negotiation revision is required")

    @staticmethod
    def _stored_object(raw):
        try:
            return parse_json_object(raw)
        except ValueError as exc:
            raise TaskConflict("Stored negotiation JSON is ambiguous or invalid") from exc

    @staticmethod
    def _digest(value):
        return isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value) is not None

    def _read(self, negotiation_id, revision):
        _text(negotiation_id)
        self._revision(revision)
        saved = self.store._db.execute("SELECT record FROM negotiation_versions WHERE id=? AND revision=?",
                                       (negotiation_id, revision)).fetchone()
        if saved is None:
            raise TaskConflict("Negotiation version is missing")
        row = self._stored_object(saved[0])
        fields = {"run_id", "negotiation_id", "revision", "proposer_id", "participants", "terms",
                  "terms_sha256", "context_sha256", "state", "choices"}
        if (not isinstance(row, dict) or set(row) != fields or row["run_id"] != self.run_id
                or row["negotiation_id"] != negotiation_id or type(row["revision"]) is not int
                or row["revision"] != revision
                or not isinstance(row["state"], str) or row["state"] not in {"open", "superseded", "withdrawn"}
                or not isinstance(row["terms"], dict) or not row["terms"]
                or not self._digest(row["terms_sha256"]) or not self._digest(row["context_sha256"])
                or task_digest(row["terms"]) != row["terms_sha256"]):
            raise TaskConflict("Stored negotiation version is inconsistent")
        participants, choices = row["participants"], row["choices"]
        if (not isinstance(participants, list) or not participants
                or any(not isinstance(party, str) or not party.strip() for party in participants)
                or participants != sorted(set(participants))
                or not set(participants) <= self.store.organization_ids
                or row["proposer_id"] not in participants
                or not isinstance(choices, dict) or not set(choices) <= set(participants)):
            raise TaskConflict("Stored negotiation substitutes original participants or choice authors")
        choice_fields = {"party_id", "operation_id", "revision", "terms_sha256", "action", "reason",
            "context_sha256", "withdrawn"}
        for party, choice in choices.items():
            if (not isinstance(choice, dict) or set(choice) != choice_fields
                    or choice["party_id"] != party or type(choice["revision"]) is not int
                    or choice["revision"] != revision or choice["terms_sha256"] != row["terms_sha256"]
                    or not isinstance(choice["action"], str) or choice["action"] not in {"accept", "reject", "revise"}
                    or type(choice["withdrawn"]) is not bool
                    or not isinstance(choice["operation_id"], str) or not choice["operation_id"].strip()
                    or not isinstance(choice["reason"], str) or not choice["reason"].strip()
                    or not self._digest(choice["context_sha256"])):
                raise TaskConflict("Stored independent choice changes its author, version, terms or closed decision schema")
            # Operation identities are scoped to a party, so two different
            # parties may legally use the same operation text.
            operation_key = (party, choice["operation_id"])
            original = self.store._db.execute(
                "SELECT record FROM negotiation_operations WHERE party=? AND operation=?", operation_key).fetchone()
            expected = {"negotiation_id": negotiation_id, "choice": {**choice, "withdrawn": False}}
            if original is None or task_digest(self._stored_object(original[0])) != task_digest(expected):
                raise TaskConflict("Stored choice lacks its exact original independently recorded operation")
        return row

    def _write(self, row, event):
        self.store._db.execute("INSERT INTO negotiation_versions VALUES (?, ?, ?) "
                               "ON CONFLICT(id, revision) DO UPDATE SET record=excluded.record",
                               (row["negotiation_id"], row["revision"], canonical(row)))
        self.store._db.execute("INSERT INTO negotiation_events(id, record) VALUES (?, ?)",
                               (row["negotiation_id"], canonical(event)))
        return deepcopy(row)

    def latest(self, *, negotiation_id, recipient_id):
        self._party(recipient_id)
        _text(negotiation_id)
        with self.store._lock:
            head = self.store._db.execute("SELECT revision FROM negotiation_heads WHERE id=?", (negotiation_id,)).fetchone()
            if head is None:
                return None
            return self._view(self._read(negotiation_id, head[0]), recipient_id)

    def get(self, *, negotiation_id, revision, recipient_id):
        self._party(recipient_id)
        with self.store._lock:
            return self._view(self._read(negotiation_id, revision), recipient_id)

    @staticmethod
    def _view(row, recipient_id):
        if recipient_id not in row["participants"]:
            raise TaskConflict("Recipient is not a party to this negotiation version")
        # Choice and shared reason may be delivered to counterparties. Each
        # party's authorization/read context remains private to that party.
        for party, choice in row["choices"].items():
            if party != recipient_id:
                choice.pop("context_sha256", None)
        return row

    def propose(self, *, negotiation_id, revision, proposer_id, participants,
                terms, context, authenticated_party, revalidate):
        _text(negotiation_id)
        self._revision(revision)
        self._party(proposer_id)
        if authenticated_party != proposer_id:
            raise TaskConflict("Authenticated party cannot propose for another organization")
        if (not isinstance(participants, (list, tuple)) or not participants
                or len(set(participants)) != len(participants) or proposer_id not in participants):
            raise ValueError("Explicit distinct participants must include the proposer")
        for party in participants:
            self._party(party)
        if not isinstance(terms, dict) or not terms or not isinstance(context, dict) or not context:
            raise ValueError("Exact nonempty draft terms and current context are required")
        row = {"run_id": self.run_id, "negotiation_id": negotiation_id, "revision": revision,
               "proposer_id": proposer_id, "participants": sorted(participants), "terms": deepcopy(terms),
               "terms_sha256": task_digest(terms), "context_sha256": task_digest(context),
               "state": "open", "choices": {}}
        if not callable(revalidate) or revalidate(deepcopy(row)) is not None:
            raise TaskConflict("Current proposer authorization must be revalidated")
        with self.store._transaction():
            head = self.store._db.execute("SELECT revision FROM negotiation_heads WHERE id=?", (negotiation_id,)).fetchone()
            if head is None:
                if revision != 0:
                    raise TaskConflict("The first negotiation revision must be zero")
            else:
                previous = self._read(negotiation_id, head[0])
                if head[0] == revision:
                    immutable = {key: value for key, value in previous.items() if key not in {"state", "choices"}}
                    if task_digest(immutable) != task_digest({key: value for key, value in row.items()
                            if key not in {"state", "choices"}}):
                        raise TaskConflict("An existing draft revision cannot change terms, parties or context")
                    return self._view(previous, proposer_id)
                if head[0] + 1 != revision or previous["state"] != "open":
                    raise TaskConflict("Revision must follow the current open draft")
                if previous["proposer_id"] != proposer_id:
                    raise TaskConflict("A counterproposal by another party requires its own negotiation identity")
                previous["state"] = "superseded"
                self._write(previous, {"event": "superseded", "revision": head[0], "by_revision": revision})
            self.store._db.execute("INSERT INTO negotiation_heads VALUES (?, ?) "
                                   "ON CONFLICT(id) DO UPDATE SET revision=excluded.revision", (negotiation_id, revision))
            return self._write(row, {"event": "proposed", "revision": revision,
                                     "terms_sha256": row["terms_sha256"], "proposer_id": proposer_id})

    def record_choice(self, *, negotiation_id, revision, party_id, operation_id,
                      terms_sha256, choice, context, authenticated_party, revalidate):
        self._party(party_id)
        _text(operation_id)
        if authenticated_party != party_id:
            raise TaskConflict("Authenticated party cannot accept for another organization")
        if (not isinstance(choice, dict) or set(choice) != {"action", "reason"}
                or choice["action"] not in {"accept", "reject", "revise"}
                or not isinstance(choice["reason"], str) or not choice["reason"].strip()
                or not isinstance(context, dict) or not context):
            raise ValueError("An explicit independent choice and current context are required")
        saved_choice = {"party_id": party_id, "operation_id": operation_id, "revision": revision,
                        "terms_sha256": terms_sha256, "action": choice["action"], "reason": choice["reason"],
                        "context_sha256": task_digest(context), "withdrawn": False}
        # Check exact revision membership before passing shared terms to a
        # party-scoped host validator. Recheck inside the write transaction.
        view = self.get(negotiation_id=negotiation_id, revision=revision, recipient_id=party_id)
        if view["state"] != "open" or view["terms_sha256"] != terms_sha256:
            raise TaskConflict("Choice does not target the current open terms version")
        if not callable(revalidate) or revalidate(deepcopy(view), deepcopy(saved_choice)) is not None:
            raise TaskConflict("Current party authorization and terms must be revalidated")
        operation = {"negotiation_id": negotiation_id, "choice": saved_choice}
        with self.store._transaction():
            row = self._read(negotiation_id, revision)
            if row["state"] != "open" or row["terms_sha256"] != terms_sha256:
                raise TaskConflict("Draft changed while the party choice was being validated")
            prior = self.store._db.execute("SELECT record FROM negotiation_operations WHERE party=? AND operation=?",
                                           (party_id, operation_id)).fetchone()
            if prior:
                if task_digest(self._stored_object(prior[0])) != task_digest(operation):
                    raise TaskConflict("Party operation identity was reused with a different decision or version")
                return self._view(row, party_id)
            if party_id in row["choices"]:
                raise TaskConflict("Party already decided this draft; revise terms or withdraw the choice explicitly")
            row["choices"][party_id] = saved_choice
            self.store._db.execute("INSERT INTO negotiation_operations VALUES (?, ?, ?)",
                                   (party_id, operation_id, canonical(operation)))
            self._write(row, {"event": "party_decided", "revision": revision, "party_id": party_id,
                              "operation_id": operation_id, "action": saved_choice["action"]})
            return self._view(row, party_id)

    def withdraw_choice(self, *, negotiation_id, revision, party_id, operation_id,
                        authenticated_party, revalidate):
        self._party(party_id)
        _text(operation_id)
        if authenticated_party != party_id:
            raise TaskConflict("Only the party that decided may withdraw its choice")
        view = self.get(negotiation_id=negotiation_id, revision=revision, recipient_id=party_id)
        if not callable(revalidate) or revalidate(deepcopy(view)) is not None:
            raise TaskConflict("Current withdrawal authority must be revalidated")
        operation = {"negotiation_id": negotiation_id, "revision": revision, "event": "choice_withdrawn"}
        with self.store._transaction():
            row = self._read(negotiation_id, revision)
            if row["state"] != "open" or party_id not in row["choices"]:
                raise TaskConflict("Only an existing choice on open draft terms can be withdrawn")
            prior = self.store._db.execute("SELECT record FROM negotiation_operations WHERE party=? AND operation=?",
                                           (party_id, operation_id)).fetchone()
            if prior:
                if task_digest(self._stored_object(prior[0])) != task_digest(operation):
                    raise TaskConflict("Withdrawal identity was reused")
                return self._view(row, party_id)
            if row["choices"][party_id]["withdrawn"]:
                raise TaskConflict("Choice was already withdrawn")
            row["choices"][party_id]["withdrawn"] = True
            self.store._db.execute("INSERT INTO negotiation_operations VALUES (?, ?, ?)",
                                   (party_id, operation_id, canonical(operation)))
            self._write(row, {"event": "choice_withdrawn", "revision": revision, "party_id": party_id,
                              "operation_id": operation_id})
            return self._view(row, party_id)

    def unanimous(self, *, negotiation_id, revision, terms_sha256, recipient_id, revalidate):
        self._party(recipient_id)
        with self.store._transaction():
            row = self._read(negotiation_id, revision)
            view = self._view(deepcopy(row), recipient_id)
            if row["state"] != "open" or row["terms_sha256"] != terms_sha256:
                raise TaskConflict("Formation review targets a stale or withdrawn draft")
            if set(row["choices"]) != set(row["participants"]):
                return False
            if any(choice["action"] != "accept" or choice["withdrawn"] for choice in row["choices"].values()):
                return False
            if not callable(revalidate) or revalidate(deepcopy(view)) is not None:
                raise TaskConflict("Current formation conditions must be revalidated")
            if task_digest(self._read(negotiation_id, revision)) != task_digest(row):
                raise TaskConflict("Draft or independent choices changed during formation validation")
            return True

    def withdraw_draft(self, *, negotiation_id, revision, proposer_id, authenticated_party, revalidate):
        self._party(proposer_id)
        if authenticated_party != proposer_id:
            raise TaskConflict("Only the authenticated proposer can withdraw its draft")
        view = self.get(negotiation_id=negotiation_id, revision=revision, recipient_id=proposer_id)
        if view["proposer_id"] != proposer_id:
            raise TaskConflict("Only the proposer can withdraw its draft")
        if not callable(revalidate) or revalidate(deepcopy(view)) is not None:
            raise TaskConflict("Current draft withdrawal authority must be revalidated")
        with self.store._transaction():
            row = self._read(negotiation_id, revision)
            if row["state"] == "withdrawn":
                return self._view(row, proposer_id)
            if row["state"] != "open":
                raise TaskConflict("Only current open draft terms can be withdrawn")
            row["state"] = "withdrawn"
            self._write(row, {"event": "draft_withdrawn", "revision": revision, "proposer_id": proposer_id})
            return self._view(row, proposer_id)

    def history(self, *, negotiation_id, recipient_id):
        self._party(recipient_id)
        _text(negotiation_id)
        with self.store._lock:
            # Each historical revision may have a different participant set.
            revisions = self.store._db.execute("SELECT revision FROM negotiation_versions WHERE id=? ORDER BY revision",
                                               (negotiation_id,)).fetchall()
            visible = [self._view(row, recipient_id) for (revision,) in revisions
                       if recipient_id in (row := self._read(negotiation_id, revision))["participants"]]
            if not visible:
                raise TaskConflict("Recipient has no visible negotiation versions")
            return visible

    def events(self, *, negotiation_id, recipient_id):
        visible = {row["revision"] for row in self.history(negotiation_id=negotiation_id, recipient_id=recipient_id)}
        with self.store._lock:
            rows = [self._stored_object(saved[0]) for saved in self.store._db.execute(
                "SELECT record FROM negotiation_events WHERE id=? ORDER BY sequence", (negotiation_id,))]
            return [row for row in rows if row["revision"] in visible]
