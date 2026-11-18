# Micro Task Journal

`TaskStore` records technical task progress in a run-local SQLite database.
The host supplies the run, authorized recipient set, original external request
ID, action, purpose, exact input/context hashes, and seven execution versions.
The context hash must include current authorization, scope, business time and
reading version. A changed invocation with an existing request ID is rejected;
the host must obtain the protocol's next input version and invocation identity.

The states are `waiting_input`, `processing`, `output_formed`,
`waiting_receipt`, `receipt_unknown`, `reconciled`, and `technical_failure`.
Revision checks prevent two workers from starting or submitting the same task.
Each transition and its resulting task record commit together. Recipient views
contain only that organization's tasks. The host retains responsibility for
authorizing callers of these views.

`wait_for_input` retains opaque host-validated conditions for compatibility.
Computable scheduling uses `ContinuationJournal` below. The host must recheck
facts and authorization before starting after a condition changes.
Opening another connection never resets `processing`. After diagnosing that
the worker has stopped and has not crossed an external boundary, the host can
record `fail` at the current revision before retrying its pure decision work.

`GbaV1AgentClient(task_path=...)` uses the journal for proposal/final output
recovery, revalidates recovered responses and keeps their original IDs.
Returned output remains `output_formed`; it is not an execution receipt.
The client binds its task database to the attached actual simulation ID.
Building a fresh engine cannot stand in for a macro resume.

`integration.task_submission.TaskSubmission` is an adapter primitive requiring
an explicit action list, submit transport, fresh fact/authorization check and
receipt validator. It commits `waiting_receipt` before invoking transport.
A lost/invalid reply becomes `receipt_unknown`; retries query the original
request and never submit again. Missing query capability or an unconfirmed
receipt keeps the task unknown. A binding's read-only query must enforce current
receipt-read permission even when authority for new submissions has expired.
Receipts retain the raw macro evidence and correlate the run, organization,
original request, task/output hashes, binding and macro version.

No production binding of the 106 new actions is supplied by this module.
The submission tests use an explicitly synthetic transport. The journal owns
no contract, funds, inventory, capacity, permit or business clock, and does not
provide complete macro-engine recovery or automatic external idempotency.

`NegotiationJournal` separately stores exact draft versions, participant sets
and independently authored `accept`, `reject` or `revise` choices. The trusted
host supplies the authenticated organization and current validation callback;
neither argument may come from model output. A version's terms and context are
immutable. Revised drafts start with no choices, while historical choices and
withdrawals remain available in recipient-scoped history. Operation IDs reject
conflicting replay. Transactional writes recheck the draft after authorization
validation, so concurrent revision cannot receive a stale acceptance.

Shared views expose shared terms and choice reasons. Each party sees only its
own choice authorization/context digest. Hosts must pass a context containing
the exact input/authorization versions, scope and time, and revalidate facts,
authority and formation conditions. `unanimous()` proves only local agreement
on the current draft; it creates no formal `PartyAcceptance`, contract, funds,
resource reservation or receipt. Withdrawing a draft/choice does not terminate
existing obligations.

Recovery parses version/operation/event JSON with duplicate-field and finite-number
checks. Each saved choice must match the original participant, exact revision/terms
and independently recorded party operation; withdrawal is an explicit boolean.
A withdrawn current choice retains its original unwithdrawn decision record. Valid
existing layouts and operation keys stay unchanged; incomplete records are rejected,
never filled with an acceptance. Formation validation rechecks the same version
before returning local unanimity. These changes have only static inspection evidence;
negotiation and procurement recovery remain for the final business validation.

The legacy procurement `ProcurementSession` saves each contract party's choice
immediately, before asking the next party. Restarting the same frozen session
recovers its last draft and choices, checks their authorization contexts and
asks only undecided parties. Each amendment still requires every party's fresh
choice. `ContractCommitter` verifies the reviewed version and all independent
choices before the existing current-resource/budget checks and actual commit.
Historical checkpoints retain their original acceptance trace and are checked
without synthesizing new records.

The legacy consortium stage checkpoints its exact generated candidates before
member review, and persists each member's independent choice. Recovery checks
the frozen input and execution versions and asks only undecided members.
Accepted drafts are verified again before bid preparation and contract review.
Technical generation failures are retried as failures rather than cached as
business nonparticipation. The full generation checkpoint uses the private
`host-audit-checkpoint` purpose, excluded from ordinary recipient task queries;
only trusted-host queries may select `include_host_audit=True`. New-format
session markers reject a missing journal rather than falling back to historical
acceptance traces. New 106-action negotiation adapters remain unimplemented.

`ContinuationJournal` registers strict `ResumeCondition` records against
action-specific `ConditionProfile` codes, versions and evaluators. Registration
requires current host validation. Event and dependency signals carry stable
run/recipient/event identities; time gates compare the exact business clock
version, without advancing the macro clock. A changed dependency version is
only a hint to recompute every condition, never proof of available resources.
Unknown or unavailable evaluations stay pending; errors remain technical errors.

After all conditions pass, the host supplies a new protocol invocation with
exact input/context snapshots and current fact/authorization digests, then
explicitly revalidates it. The successor task, immutable continuation evidence
and old task transition commit in one transaction. Concurrent dispatchers link
only one successor. The old invocation retains its original conditions and
cannot restart; `ready()` exposes the recipient's new tasks together with their
saved input/context. Starting a successor still uses revision checks and normal
action validation. No model decision, external submission or receipt is made by
the scheduler, and existing acceptance/obligation records are not rewritten.

`integration.task_continuation.ObservationContinuationDispatcher` replays saved
recipient feedback through an explicit host signal projection. It rejects
changed event identities, recipients or payloads. `GbaV1AgentClient` accepts an
optional `continuation_dispatcher` host callback after inbox persistence, also
on duplicate delivery. Hosts replay the saved inbox on startup to cover crashes
between feedback persistence and wakeup; linked tasks deduplicate replay.

`owner_management_profile` computes OWN-A01's existing
`management_capacity_revalidated` condition from a fresh `ActionReadView`,
current capacity version, exact quantities, commitments and sourced evidence.
It rechecks authorization and reading contents. Only this local action profile
is supplied; other actions need their own computable profiles and real event
projections. The bundled macro has no asserted ManagementCapacity publication
binding. Formal 106-action task/event adapters and complete macro-engine recovery
remain incomplete.
