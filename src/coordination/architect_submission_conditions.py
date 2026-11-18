"""Resolve original A07 submission receipts without duplicate version work or fees."""
from copy import deepcopy
from dataclasses import dataclass

from src.actions.contracts.architect_submission_objects import ArchitectSubmissionSavedView
from src.actions.contracts.common import ActionContext, EvidenceRecord, Reference
from src.actions.contracts.references import ActionReadView
from src.coordination.continuations import ConditionProfile
from src.coordination.tasks import TaskConflict


@dataclass(frozen=True)
class ArchitectSubmissionReceiptConditionReading:
    context: ActionContext
    reading: ActionReadView
    submission_ref: Reference


def architect_original_submission_receipt_profile(read_current, validate_relation):
    """Resolve the exact event wait emitted by the original Architect A07.

    The application holds actual source/authority/journal guards and supplies
    explicit authorized original/current submission versions. The independent
    native validator must authenticate original command coverage and confirm
    no duplicate version, work or fee effects before any retry judgment. Signals
    cannot prove that a committed submission was uncommitted or erase rejection.
    """
    return _professional_original_submission_receipt_profile(read_current, validate_relation,
        action_id='ARCHITECT-A07', role='Architect', submission_schema=ArchitectSubmissionSavedView,
        reading_type=ArchitectSubmissionReceiptConditionReading)


def _professional_original_submission_receipt_profile(read_current, validate_relation, *,
        action_id, role, submission_schema, reading_type, extra_identity_fields=()):
    """Share native uncommitted-command checks; each role retains its own schema."""
    if not callable(read_current) or not callable(validate_relation):
        raise ValueError('Professional receipt wait requires actual sources and independent native query validation')
    code = 'original_command_receipt_resolved_without_duplicate_version_work_or_fee'

    def evaluate(check):
        source, old_refs = check.source['identity'], check.condition.object_refs
        if (source['action_id'] != action_id or source['role'] != role or source['purpose'] != 'action'
                or check.condition.condition_code != code or check.condition.trigger != 'event'
                or check.signal.run_id != source['run_id'] or check.signal.organization_id != source['organization_id']
                or len(old_refs) != 1 or old_refs[0].kind != 'DeliverableSubmission'):
            raise TaskConflict('Professional receipt wait changes original action, recipient or submission selection')
        selected = read_current(deepcopy(check))
        if (not isinstance(selected, reading_type)
                or not isinstance(selected.context, ActionContext) or not isinstance(selected.reading, ActionReadView)
                or not isinstance(selected.submission_ref, Reference)):
            raise TaskConflict('Professional receipt wait requires typed current authorized submission sources')
        context, reading, ref = (selected.context.model_copy(deep=True), selected.reading,
            selected.submission_ref.model_copy(deep=True))
        old_ref, now = old_refs[0], context.business_time
        if (context.run_id != source['run_id'] or reading.organization_id != source['organization_id']
                or context.contract_ref.id != action_id or context.execution_mode != 'llm'
                or reading._resolver.source_mode != 'formal' or now != check.signal.business_time
                or context.operation_id == source['request_id'] or (ref.kind, ref.id) != (old_ref.kind, old_ref.id)
                or not {ref.key(), old_ref.key()} <= {item.key() for item in context.visible_refs}):
            raise TaskConflict('Professional receipt query substitutes current formal context or original submission')
        reading.check_method_context(context, action_id)
        try:
            original, current = reading.resolve(old_ref), reading.resolve(ref)
            if (not isinstance(original, submission_schema) or not isinstance(current, submission_schema)
                    or original.ref.key() != old_ref.key() or current.ref.key() != ref.key()
                    or current.organization_id != source['organization_id']
                    or original.status == 'confirmed_uncommitted'
                    or any(getattr(original, field) != getattr(current, field) for field in (
                        'organization_id', 'deliverable_ref', 'command_id', 'business_key', 'payload_sha256', 'scope',
                        *extra_identity_fields))
                    or original.status in {'committed', 'rejected'} and current.status != original.status):
                raise TaskConflict('Professional receipt query changes original command, exact deliverable, payload or known result')
            if (current.available_at.clock_ref != now.clock_ref or current.available_at.offset > now.offset
                    or not current.effective_window.contains(now)):
                return 'unavailable'
            if current.status == 'unknown':
                return 'waiting'
            if current.status != 'confirmed_uncommitted':
                return 'unavailable'
            observations = {}
            for evidence_ref in current.evidence_refs:
                evidence = reading.resolve(evidence_ref)
                if (not isinstance(evidence, EvidenceRecord) or evidence.source_kind == 'synthetic'
                        or evidence.basis_kind != 'observed'):
                    raise TaskConflict('Professional receipt query lacks actual observed native command evidence')
                if evidence.effective_window is not None and not evidence.effective_window.contains(now):
                    return 'unavailable'
                observations[evidence.ref.key()] = evidence.model_dump(mode='json')
            if not observations:
                return 'unavailable'
            reading.recheck()
            if validate_relation(source_identity=deepcopy(source), original_submission=original.model_dump(mode='json'),
                    current_submission=current.model_dump(mode='json'), evidence=deepcopy(list(observations.values())),
                    context=context.model_copy(deep=True), reading=reading) is not True:
                raise TaskConflict('Professional retry lacks authentic uncommitted command and duplicate-effects query coverage')
            return 'ready'
        finally:
            reading.recheck()

    return ConditionProfile(action_id, code, '1', frozenset({'event'}), evaluate)
