"""Recover unchanged-judgment waits using original finite rules and saved assessments."""
from copy import deepcopy

from src.actions.contracts.architect_learning_objects import ArchitectLearningAssessmentView
from src.actions.contracts.common import EvidenceRecord, ScopeRef, StrictRecord, ref_type, walk_references
from src.actions.roles.architect_learning import prepare_architect_learning_assessment_input
from src.actions.roles.qs_change import content_digest
from src.coordination.architect_learning_applied_feedback import JUDGMENT_CODE, check_applied_feedback
from src.coordination.continuations import ConditionProfile
from src.coordination.tasks import TaskConflict
from src.methods.architect_learning import LEARNING_METHOD, apply_declared_feedback_rules
from src.organization.models import Authorization, RoleAssignment
from src.organization.registry import scope_covers


class _LearningInput(StrictRecord):
    scope: ScopeRef
    strategy_ref: ref_type('Strategy')
    capability_ref: ref_type('Capability')
    feedback_refs: list[ref_type('Feedback')]
    learning_profile_ref: ref_type('LearningProfile') | None


def read_judgment_change(selected, old, current, *, engineer=False, qs=False):
    """Reconstruct both exact assessment inputs without executing or applying an action."""
    action_id, role = ('ENGINEER-A12', 'Engineer') if engineer else ('ARCHITECT-A12', 'Architect')
    input_type, assessment_type, prepare_input = _LearningInput, ArchitectLearningAssessmentView, prepare_architect_learning_assessment_input
    if engineer:
        from src.actions.contracts.engineer_learning_objects import EngineerLearningAssessmentView
        from src.actions.roles.engineer_learning import prepare_engineer_learning_assessment_input
        from src.coordination.engineer_learning_conditions import _EngineerLearningInput
        input_type, assessment_type, prepare_input = _EngineerLearningInput, EngineerLearningAssessmentView, prepare_engineer_learning_assessment_input
    if qs:
        if engineer:
            raise TaskConflict('Judgment-change recovery requires one original role route')
        from src.actions.contracts.qs_learning_objects import QSLearningAssessmentView
        from src.actions.roles.qs_learning import prepare_qs_learning_assessment_input
        from src.coordination.qs_training_conditions import _QSTrainingInput
        action_id, role = 'QS-A12', 'QS'
        input_type, assessment_type, prepare_input = _QSTrainingInput, QSLearningAssessmentView, prepare_qs_learning_assessment_input
    reading, versions, proof_refs = selected.reading, [], []
    if old['profile'].ref.key()[:2] != current['profile'].ref.key()[:2]:
        raise TaskConflict('Judgment-change recovery replaces original private learning profile')
    for raw, context, source in (
            (selected.original_action_input, selected.original_context, old),
            (selected.action_input, selected.context, current)):
        original = source is old
        prepared = prepare_input(context, input_type.model_validate(raw), reading)
        if prepared['kind'] != 'prepared':
            if original:
                raise TaskConflict('Original judgment-change wait bypasses its feedback/catalog/authority gates')
            return 'waiting', None
        if source['decision'].assessment_ref is None:
            if original:
                raise TaskConflict('Original unchanged-judgment wait lacks its saved assessment')
            return 'waiting', None
        saved = reading.resolve(source['decision'].assessment_ref)
        data = prepared['input']
        if (not isinstance(saved, assessment_type) or saved.ref != source['decision'].assessment_ref
                or saved.organization_id != reading.organization_id or saved.author_organization_id != reading.organization_id
                or saved.strategy_ref != source['strategy'].ref or saved.learning_profile_ref != source['profile'].ref
                or saved.scope != context.scope or saved.data != data or saved.input_sha256 != content_digest(data)):
            raise TaskConflict('Judgment-change recovery rewrites exact original feedback/rules/assessment input')
        if saved.status != 'ok' or saved.report is None:
            if original:
                raise TaskConflict('Original unchanged-judgment wait lacks its successful assessment')
            return 'waiting', None
        grant, function = reading.resolve(saved.author_authority_ref), reading.resolve(saved.author_function_ref)
        if (not isinstance(grant, Authorization) or grant.actor_id != saved.author_actor_id
                or grant.organization_id != saved.author_organization_id or grant.function_ref != saved.author_function_ref
                or saved.author_action_id != action_id or saved.author_action_id not in grant.action_ids
                or not grant.validity.contains(saved.authored_at)
                or not any(scope_covers(scope, saved.scope) for scope in grant.scopes)
                or not isinstance(function, RoleAssignment) or function.role != role
                or function.function_ref != saved.author_function_ref
                or any(point.clock_ref != context.business_time.clock_ref for point in (saved.authored_at, saved.available_at))
                or not saved.authored_at.offset <= saved.available_at.offset <= context.business_time.offset
                or not saved.effective_window.contains(saved.authored_at) or not saved.effective_window.contains(context.business_time)):
            raise TaskConflict('Judgment-change recovery lacks actual saved assessment authorship/chronology')
        if original:
            report = apply_declared_feedback_rules(data)
        else:
            result = reading.calculate(LEARNING_METHOD, data)
            if result.kind != 'ok':
                return 'unavailable', None
            report = result.value
        if report != saved.report:
            raise TaskConflict('Judgment-change assessment conflicts with actual declared-rule calculation')
        judgments = {row.dimension_ref.key(): row.selected_value_ref for row in source['strategy'].judgments}
        changed = [selection for selection in report.selections
            if judgments.get(selection.dimension_ref.key()) != selection.selected_value_ref]
        if original and changed:
            raise TaskConflict('Original unchanged-judgment wait actually has a declared change')
        proof_refs.extend([*grant.basis_refs, *function.basis_refs,
            *(ref for ref in walk_references(saved) if ref.kind == 'Evidence')])
        versions.append(dict(assessment=saved.model_dump(mode='json'), data=data.model_dump(mode='json'),
            report=report.model_dump(mode='json'), changed=[row.model_dump(mode='json') for row in changed]))
    if not versions[1]['changed']:
        return 'waiting', None
    evidence = {}
    for ref in proof_refs:
        row = reading.resolve(ref)
        if not isinstance(row, EvidenceRecord) or row.ref != ref or row.source_kind == 'synthetic' or row.basis_kind != 'observed':
            raise TaskConflict('Judgment-change recovery requires observed original/current assessment evidence')
        evidence[ref.key()] = row.model_dump(mode='json')
    return 'ready', dict(original=versions[0], current=versions[1], evidence=list(evidence.values()))


def architect_original_judgment_change_profile(read_current, validate_relation):
    if not callable(read_current) or not callable(validate_relation):
        raise ValueError('Judgment-change recovery requires guarded sources and independent native validation')

    def evaluate(check):
        selected = read_current(deepcopy(check))
        try:
            return check_applied_feedback(check, selected, validate_relation, judgment_change=True)[0]
        finally:
            selected.reading.recheck()

    return ConditionProfile('ARCHITECT-A12', JUDGMENT_CODE, '1', frozenset({'dependency_change'}), evaluate)
