"""Actual Engineer A12 execution lookup preserves independent qualification history."""
from copy import deepcopy

from src.actions.contracts.common import ref_type
from src.actions.contracts.engineer_learning_objects import EngineerLearningExecutionView, EngineerQualificationView, EngineerQualificationEventView
from src.coordination.architect_learning_execution_query import ArchitectLearningExecutionQueryRecord, EXECUTION_CODE, check_learning_execution
from src.coordination.continuations import ConditionProfile
from src.coordination.tasks import TaskConflict


class EngineerLearningExecutionQueryRecord(ArchitectLearningExecutionQueryRecord):
    execution_ref: ref_type('EngineerLearningExecution')
    execution: EngineerLearningExecutionView


def preserve_engineer_query_qualifications(raw, current_raw, old, current, read):
    if (raw['qualification_refs'] != current_raw['qualification_refs']
            or old['state'].qualification_refs != current['state'].qualification_refs
            or old['state'].applied_qualification_event_refs != current['state'].applied_qualification_event_refs):
        raise TaskConflict('Engineer execution lookup rewrites independent qualification history')
    for inputs, version in ((raw, old), (current_raw, current)):
        refs = [ref_type('Qualification').model_validate(ref) for ref in inputs['qualification_refs']]
        if (len({ref.key() for ref in refs}) != len(refs)
                or {ref.key() for ref in refs} != {ref.key() for ref in version['state'].qualification_refs}
                or {ref.key() for ref in refs} != {ref.key() for ref in version['capability'].qualification_refs}):
            raise TaskConflict('Engineer execution lookup substitutes complete original credential inputs')
        for ref in refs:
            qualification = read(ref, EngineerQualificationView)
            if (qualification.organization_id != version['state'].organization_id
                    or qualification.author_organization_id != qualification.issuer_organization_id):
                raise TaskConflict('Engineer execution lookup borrows another holder/issuer qualification')
        for ref in version['state'].applied_qualification_event_refs:
            event = read(ref, EngineerQualificationEventView)
            if event.organization_id != version['state'].organization_id or event.author_organization_id != event.issuer_organization_id:
                raise TaskConflict('Engineer execution lookup borrows another holder/issuer applied event')


def check_engineer_learning_execution(check, selected, validate_relation, *, terminal=False):
    return check_learning_execution(check, selected, validate_relation, terminal=terminal, engineer=True)


def engineer_original_learning_execution_profile(read_current, validate_relation):
    if not callable(read_current) or not callable(validate_relation):
        raise ValueError('Engineer learning execution recovery requires guarded sources and native query authentication')

    def evaluate(check):
        selected = read_current(deepcopy(check))
        try:
            return check_engineer_learning_execution(check, selected, validate_relation)[0]
        finally:
            selected.reading.recheck()

    return ConditionProfile('ENGINEER-A12', EXECUTION_CODE, '2', frozenset({'dependency_change'}), evaluate)
