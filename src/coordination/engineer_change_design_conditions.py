"""Retain original A09 revision lineage while reusing professional design recovery."""
from types import SimpleNamespace

from src.actions.contracts.engineer_change_objects import (
    EngineerChangeDeliverableView, EngineerChangeIssueView, EngineerChangeObligationView,
    EngineerChangeProfileView, EngineerChangeBasisView, EngineerChangeInstructionView,
)
from src.actions.contracts.engineer_design_objects import EngineerDesignTaskView
from src.coordination.engineer_design_conditions import AUTHORIZATION_CODE, CANDIDATE_CODE, WORK_CODE, SUBMISSION_CODE, _check_engineer_design_history
from src.coordination.tasks import TaskConflict


def prepare_engineer_change_design_inputs(selected, original_input, current_input):
    """Derive the actual delegated design inputs; never replace the saved A09 snapshot."""
    from src.coordination.engineer_change_conditions import _physical_history
    reading = selected.reading

    def read(ref, schema, at):
        row = reading.resolve(ref)
        if not isinstance(row, schema) or row.ref != ref:
            raise TaskConflict('Revision design recovery lacks exact typed original/current lineage')
        if row.available_at.clock_ref != at.clock_ref or row.available_at.offset > at.offset:
            raise TaskConflict('Revision design recovery introduces lineage unavailable at its original/current time')
        return row

    versions, inputs = [], []
    for values, context in ((original_input, selected.original_context), (current_input, selected.context)):
        parent = read(values.prior_deliverable_ref, EngineerChangeDeliverableView, context.business_time)
        issue = read(values.issue_ref, EngineerChangeIssueView, context.business_time)
        obligation = read(values.obligation_ref, EngineerChangeObligationView, context.business_time)
        profile = read(issue.change_profile_ref, EngineerChangeProfileView, context.business_time)
        if profile.choice != 'revise' or profile.revision_task_ref is None or profile.change_basis_ref is None:
            raise TaskConflict('Revision design recovery replaces the original producing task or verified change basis')
        task = read(profile.revision_task_ref, EngineerDesignTaskView, context.business_time)
        basis = read(profile.change_basis_ref, EngineerChangeBasisView, context.business_time)
        instruction = None if values.instruction_ref is None else read(values.instruction_ref, EngineerChangeInstructionView, context.business_time)
        if (issue.used_deliverable_ref != parent.ref or issue.obligation_ref != obligation.ref
                or obligation.deliverable_ref != parent.ref or obligation.organization_id != reading.organization_id
                or profile.issue_ref != issue.ref or profile.obligation_ref != obligation.ref
                or task.appointment_ref != obligation.appointment_ref or task.brief_ref != parent.brief_ref
                or task.engineering_profile_ref != parent.engineering_profile_ref
                or basis.issue_ref != issue.ref or basis.obligation_ref != obligation.ref
                or basis.prior_deliverable_ref != parent.ref or basis.original_content_sha256 != parent.content_sha256
                or basis.instruction_ref != values.instruction_ref):
            raise TaskConflict('Revision design recovery changes original version, issue, work obligation or basis')
        versions.append(dict(parent=parent, issue=issue, obligation=obligation, profile=profile, basis=basis, instruction=instruction))
        inputs.append(SimpleNamespace(scope=values.scope, brief_ref=parent.brief_ref, task_ref=task.ref,
            engineering_profile_ref=parent.engineering_profile_ref, evidence_refs=values.evidence_refs,
            method_result_refs=values.method_result_refs, prior_option_ref=parent.option_ref))
    old, current = versions
    if (original_input.prior_deliverable_ref != current_input.prior_deliverable_ref
            or original_input.instruction_ref != current_input.instruction_ref
            or original_input.scope != current_input.scope
            or not {ref.key() for ref in original_input.evidence_refs} <= {ref.key() for ref in current_input.evidence_refs}
            or not {ref.key() for ref in original_input.method_result_refs} <= {ref.key() for ref in current_input.method_result_refs}):
        raise TaskConflict('Revision design recovery replaces original parent, instruction, scope or execution evidence')
    metadata = {'ref', 'available_at', 'effective_window', 'evidence_refs'}
    for name in ('parent', 'issue', 'obligation', 'profile', 'basis', 'instruction'):
        before, after = old[name], current[name]
        if before is None or after is None:
            if before != after:
                raise TaskConflict('Revision design recovery invents or drops its original instruction')
            continue
        excluded = metadata | ({'input_evidence_refs', 'method_result_refs'} if name == 'profile' else set())
        if name == 'basis':
            excluded.add('verified_at')
            if (after.verified_at.clock_ref != before.verified_at.clock_ref
                    or after.verified_at.offset < before.verified_at.offset):
                raise TaskConflict('Revision design recovery moves verified change authority backwards in time')
        if (before.ref.key()[:2] != after.ref.key()[:2] or before.ref == after.ref and before != after
                or _physical_history(before.model_dump(mode='json', exclude=excluded))
                != _physical_history(after.model_dump(mode='json', exclude=excluded))
                or not {ref.key() for ref in before.evidence_refs} <= {ref.key() for ref in after.evidence_refs}):
            raise TaskConflict('Revision design recovery rewrites original purpose, authority, changed parameters or obligations')
        if name == 'profile':
            for field in ('input_evidence_refs', 'method_result_refs'):
                if not {ref.key() for ref in getattr(before, field)} <= {ref.key() for ref in getattr(after, field)}:
                    raise TaskConflict('Revision design recovery drops original professional input or method history')

    def dump(version):
        return {name: None if row is None else row.model_dump(mode='json') for name, row in version.items()}

    return *inputs, dict(original=dump(old), current=dump(current))


def check_engineer_change_design_authorization(check, selected, validate_relation):
    if check.condition.condition_code != AUTHORIZATION_CODE:
        raise TaskConflict('Revision design authorization checker substitutes its original task wait')
    return _check_engineer_design_history(check, selected, validate_relation, action_id='ENGINEER-A09')


def check_engineer_change_design_candidate_limit(check, selected, validate_relation):
    if check.condition.condition_code != CANDIDATE_CODE:
        raise TaskConflict('Revision candidate checker substitutes its original engagement limit wait')
    return _check_engineer_design_history(check, selected, validate_relation, action_id='ENGINEER-A09')


def check_engineer_change_design_work_limit(check, selected, validate_relation):
    if check.condition.condition_code != WORK_CODE:
        raise TaskConflict('Revision work checker substitutes its original effort/cost limit wait')
    return _check_engineer_design_history(check, selected, validate_relation, action_id='ENGINEER-A09')


def check_engineer_change_design_submission(check, selected, validate_relation, *, terminal=False):
    if check.condition.condition_code != SUBMISSION_CODE:
        raise TaskConflict('Revision submission checker substitutes its original native command query')
    return _check_engineer_design_history(check, selected, validate_relation, action_id='ENGINEER-A09', terminal=terminal)
