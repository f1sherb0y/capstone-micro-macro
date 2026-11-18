"""Engineer feedback application recovery retains independent issuer credentials."""
from copy import deepcopy
from pydantic import Field

from src.actions.contracts.common import Known, ref_type
from src.actions.contracts.engineer_learning_objects import EngineerQualificationView, EngineerQualificationEventView
from src.coordination.architect_learning_applied_feedback import (
    APPLIED_CODE, ArchitectAppliedFeedbackQueryRecord, check_applied_feedback,
)
from src.coordination.continuations import ConditionProfile
from src.coordination.tasks import TaskConflict


class EngineerAppliedFeedbackQueryRecord(ArchitectAppliedFeedbackQueryRecord):
    original_state_ref: ref_type('EngineerLearningState')
    current_state_ref: ref_type('EngineerLearningState')
    application_execution_refs: list[ref_type('EngineerLearningExecution')] = Field(min_length=1)


def preserve_applied_feedback_qualifications(raw, current_raw, old, current, read, original_context, context, *, terminal=False):
    """Exact credential versions stay observed; private learning cannot alter issuer facts."""
    credentials = []
    for inputs, version, invocation in ((raw, old, original_context), (current_raw, current, context)):
        refs = (version['state'].qualification_refs if terminal and version is current
            else [ref_type('Qualification').model_validate(ref) for ref in inputs['qualification_refs']])
        keys = {ref.key() for ref in refs}
        if (len(keys) != len(refs) or len({ref.key()[:2] for ref in refs}) != len(refs)
                or keys != {ref.key() for ref in version['state'].qualification_refs}
                or keys != {ref.key() for ref in version['capability'].qualification_refs}):
            raise TaskConflict('Engineer feedback application recovery substitutes complete credential inputs')
        rows, credential_keys = {}, set()
        for ref in refs:
            row = read(ref, EngineerQualificationView)
            if (row.organization_id != version['state'].organization_id or row.author_organization_id != row.issuer_organization_id
                    or row.coverage != 'complete' or row.as_of != invocation.business_time or row.credential_key in credential_keys
                    or row.available_at.clock_ref != invocation.business_time.clock_ref
                    or row.available_at.offset > invocation.business_time.offset):
                raise TaskConflict('Engineer feedback recovery lacks complete original issuer credential history')
            credential_keys.add(row.credential_key)
            rows[ref.key()[:2]] = row.model_dump(exclude={'ref', 'as_of', 'authored_at', 'available_at', 'effective_window'})
        credentials.append(rows)
        events = version['state'].applied_qualification_event_refs
        if len({ref.key() for ref in events}) != len(events):
            raise TaskConflict('Engineer feedback recovery duplicates applied issuer events')
        for ref in events:
            event = read(ref, EngineerQualificationEventView)
            if (event.organization_id != version['state'].organization_id or event.author_organization_id != event.issuer_organization_id
                    or event.status != 'verified' or not isinstance(event.verified, Known) or event.verified.value is not True
                    or event.received_at.clock_ref != invocation.business_time.clock_ref
                    or event.received_at.offset > invocation.business_time.offset):
                raise TaskConflict('Engineer feedback recovery changes actual applied issuer event history')
    if (credentials[0] != credentials[1]
            or old['state'].applied_qualification_event_refs != current['state'].applied_qualification_event_refs):
        raise TaskConflict('Engineer feedback application changes independent qualification/issuer history')


def check_engineer_applied_feedback(check, selected, validate_relation, *, terminal=False):
    return check_applied_feedback(check, selected, validate_relation, terminal=terminal, engineer=True)


def engineer_original_applied_feedback_profile(read_current, validate_relation):
    if not callable(read_current) or not callable(validate_relation):
        raise ValueError('Engineer applied-feedback recovery requires guarded sources and native application validation')

    def evaluate(check):
        selected = read_current(deepcopy(check))
        try:
            return check_engineer_applied_feedback(check, selected, validate_relation)[0]
        finally:
            selected.reading.recheck()

    return ConditionProfile('ENGINEER-A12', APPLIED_CODE, '1', frozenset({'dependency_change'}), evaluate)
