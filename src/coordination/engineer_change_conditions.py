"""Recover an actual required revision instruction without rewriting prior work."""
from copy import deepcopy
from dataclasses import dataclass

from src.actions.contracts.catalog import ActionContract
from src.actions.contracts.common import ActionContext, EvidenceRecord, Reference
from src.actions.contracts.engineer_change_objects import (
    EngineerChangeDeliverableView, EngineerChangeIssueView, EngineerChangeObligationView,
    EngineerChangeProfileView, EngineerChangeInstructionView, EngineerChangeBasisView,
)
from src.actions.contracts.engineer_design_objects import EngineerDesignTaskView
from src.actions.contracts.references import ActionReadView
from src.actions.roles.engineer_change import handle_professional_change
from src.coordination.engineer_design_conditions import (
    AUTHORIZATION_CODE as DESIGN_AUTHORIZATION_CODE, CANDIDATE_CODE as DESIGN_CANDIDATE_CODE,
    WORK_CODE as DESIGN_WORK_CODE, SUBMISSION_CODE as DESIGN_SUBMISSION_CODE, EngineerDesignConditionReading,
)
from src.coordination.continuations import ConditionProfile
from src.coordination.tasks import TaskConflict, task_digest


INSTRUCTION_REQUIRED_CODE = 'original_revision_instruction_required'
INSTRUCTION_AUTHORIZATION_CODE = 'original_revision_instruction_not_authorized'
AUTHOR_HANDOFF_CODE = 'original_author_or_authorized_integrator_must_revise_other_design'
_REF_KINDS = {INSTRUCTION_REQUIRED_CODE: ('Issue', 'Obligation'), INSTRUCTION_AUTHORIZATION_CODE: ('Instruction',),
    AUTHOR_HANDOFF_CODE: ('Deliverable', 'Issue'), DESIGN_AUTHORIZATION_CODE: ('Task',), DESIGN_CANDIDATE_CODE: ('DesignLimit',),
    DESIGN_WORK_CODE: ('DesignLimit',), DESIGN_SUBMISSION_CODE: ('Submission',)}
_VERSIONED_KINDS = {'Issue', 'Obligation', 'EngineeringChangeProfile', 'Task', 'ChangeBasis', 'Instruction'}
_METADATA = {'ref', 'available_at', 'effective_window', 'evidence_refs'}


@dataclass(frozen=True)
class EngineerChangeConditionReading(EngineerDesignConditionReading):
    contract: ActionContract | None = None


def _physical_history(value):
    if isinstance(value, dict):
        if set(value) == {'kind', 'id', 'version'} and value['kind'] in _VERSIONED_KINDS:
            return value['kind'], value['id']
        return {key: _physical_history(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_physical_history(item) for item in value]
    return value


def check_engineer_change_instruction(check, selected, validate_relation):
    source, code = check.source['identity'], check.condition.condition_code
    if (source['action_id'] != 'ENGINEER-A09' or source['role'] != 'Engineer' or source['purpose'] != 'action'
            or code not in {INSTRUCTION_REQUIRED_CODE, INSTRUCTION_AUTHORIZATION_CODE} or check.condition.trigger != 'dependency_change'
            or tuple(ref.kind for ref in check.condition.object_refs) != _REF_KINDS.get(code)
            or check.signal.run_id != source['run_id'] or check.signal.organization_id != source['organization_id']
            or not isinstance(selected, EngineerChangeConditionReading) or not callable(validate_relation)
            or not isinstance(selected.context, ActionContext) or not isinstance(selected.original_context, ActionContext)
            or not isinstance(selected.reading, ActionReadView) or not isinstance(selected.history_ref, Reference)):
        raise TaskConflict('Revision recovery requires the original private instruction wait')
    context, original, reading = selected.context, selected.original_context, selected.reading
    raw, current_raw = deepcopy(selected.original_action_input), deepcopy(selected.action_input)
    if (task_digest(raw) != source['input_sha256'] or task_digest(original.model_dump(mode='json')) != source['context_sha256']
            or original.operation_id != source['request_id'] or context.operation_id == source['request_id']
            or context.run_id != source['run_id'] or context.contract_ref != original.contract_ref
            or context.contract_ref.id != 'ENGINEER-A09' or context.scope != original.scope or context.execution_mode != 'llm'
            or context.business_time != check.signal.business_time or context.business_time.clock_ref != original.business_time.clock_ref
            or context.business_time.offset < original.business_time.offset
            or reading.organization_id != source['organization_id'] or reading._resolver.source_mode != 'formal'):
        raise TaskConflict('Revision recovery substitutes original invocation, scope, time or read authority')
    reading.check_method_context(context, 'ENGINEER-A09')
    contract = selected.contract
    if not isinstance(contract, ActionContract) or contract.action_id != 'ENGINEER-A09' or contract.role != 'Engineer':
        raise TaskConflict('Revision recovery lacks its actual registered A09 contract')
    old_input, current_input = contract.validate_input(raw), contract.validate_input(current_raw)
    expected_refs = ([old_input.issue_ref, old_input.obligation_ref] if code == INSTRUCTION_REQUIRED_CODE
        else [old_input.instruction_ref])
    history_ref = current_input.issue_ref if code == INSTRUCTION_REQUIRED_CODE else current_input.instruction_ref
    if (old_input.scope != current_input.scope or old_input.scope != context.scope
            or old_input.prior_deliverable_ref != current_input.prior_deliverable_ref
            or not {ref.key() for ref in old_input.evidence_refs} <= {ref.key() for ref in current_input.evidence_refs}
            or not {ref.key() for ref in old_input.method_result_refs} <= {ref.key() for ref in current_input.method_result_refs}
            or list(check.condition.object_refs) != expected_refs or selected.history_ref != history_ref):
        raise TaskConflict('Revision recovery replaces original version, evidence, execution history or selected issue')

    def read(ref, schema, at):
        row = reading.resolve(ref)
        if not isinstance(row, schema) or row.ref != ref:
            raise TaskConflict('Revision recovery lacks exact typed original/current sources')
        available = getattr(row, 'available_at', None)
        if available is not None and (available.clock_ref != at.clock_ref or available.offset > at.offset):
            raise TaskConflict('Revision recovery introduces sources unavailable at their original/current time')
        return row

    versions = []
    for values, at in ((old_input, original.business_time), (current_input, context.business_time)):
        deliverable = read(values.prior_deliverable_ref, EngineerChangeDeliverableView, at)
        issue = read(values.issue_ref, EngineerChangeIssueView, at)
        obligation = read(values.obligation_ref, EngineerChangeObligationView, at)
        profile = read(issue.change_profile_ref, EngineerChangeProfileView, at)
        instruction = None if values.instruction_ref is None else read(values.instruction_ref, EngineerChangeInstructionView, at)
        task = None if profile.revision_task_ref is None else read(profile.revision_task_ref, EngineerDesignTaskView, at)
        basis = None if profile.change_basis_ref is None else read(profile.change_basis_ref, EngineerChangeBasisView, at)
        if (issue.used_deliverable_ref != deliverable.ref or issue.obligation_ref != obligation.ref
                or obligation.deliverable_ref != deliverable.ref or obligation.organization_id != source['organization_id']
                or profile.issue_ref != issue.ref or profile.obligation_ref != obligation.ref or profile.choice != 'revise'):
            raise TaskConflict('Revision recovery changes the original issue, obligation or revise branch')
        versions.append(dict(deliverable=deliverable, issue=issue, obligation=obligation, profile=profile,
            instruction=instruction, task=task, basis=basis))
    old, current = versions
    # Establish the early wait before historical processor evaluation; this branch cannot reach design methods.
    instruction_required = (old['obligation'].instruction_required_for_revision
        and not (old['issue'].kind == 'defect' and old['obligation'].defect_remedy_authorized))
    missing_authorization = old['instruction'] is None or old['instruction'].status != 'authorized'
    if (old['deliverable'].author_organization_id != source['organization_id']
            or old['deliverable'].author_action_id not in {'ENGINEER-A05', 'ENGINEER-A09'}
            or not missing_authorization
            or code == INSTRUCTION_REQUIRED_CODE and not instruction_required
            or code == INSTRUCTION_AUTHORIZATION_CODE and (instruction_required or old['instruction'] is None)):
        raise TaskConflict('Revision recovery does not reproduce the original instruction gate and branch precedence')
    original_gate = handle_professional_change(original, old_input, reading)
    if (original_gate.get('resume_condition', {}).get('condition_code') != code
            or original_gate.get('resume_condition', {}).get('object_refs') != list(check.condition.object_refs)):
        raise TaskConflict('Revision instruction wait differs from the actual original processor')

    def retain(before, after, *, excluded=()):
        if (after is None or before.ref.key()[:2] != after.ref.key()[:2]
                or before.ref == after.ref and before != after
                or _physical_history(before.model_dump(mode='json', exclude=_METADATA | set(excluded)))
                != _physical_history(after.model_dump(mode='json', exclude=_METADATA | set(excluded)))
                or not {ref.key() for ref in before.evidence_refs} <= {ref.key() for ref in after.evidence_refs}):
            raise TaskConflict('Revision recovery rewrites original purpose, draft, dependencies, investments or authority')

    for name in ('deliverable', 'issue', 'obligation'):
        retain(old[name], current[name])
    additions = tuple(name for name in ('revision_task_ref', 'change_basis_ref') if getattr(old['profile'], name) is None)
    retain(old['profile'], current['profile'], excluded=(*additions, 'input_evidence_refs', 'method_result_refs'))
    for name in ('input_evidence_refs', 'method_result_refs'):
        if not {ref.key() for ref in getattr(old['profile'], name)} <= {ref.key() for ref in getattr(current['profile'], name)}:
            raise TaskConflict('Revision recovery drops original profile evidence or execution history')
    for name in ('task', 'basis'):
        if old[name] is not None:
            retain(old[name], current[name], excluded=('instruction_ref',) if name == 'basis' and old_input.instruction_ref is None else ())
    instruction = current['instruction']
    if instruction is None or instruction.status != 'authorized':
        return 'waiting', None
    if old['instruction'] is not None:
        retain(old['instruction'], instruction, excluded=('status', 'issued_at'))
    if (instruction.issue_ref != current['issue'].ref or instruction.obligation_ref != current['obligation'].ref
            or instruction.used_deliverable_ref != current['deliverable'].ref
            or instruction.original_content_sha256 != current['deliverable'].content_sha256
            or instruction.contract_ref != current['obligation'].contract_ref
            or instruction.issued_at.clock_ref != context.business_time.clock_ref
            or not instruction.issued_at.offset <= instruction.available_at.offset <= context.business_time.offset):
        raise TaskConflict('Revision instruction changes its actual issue, contract, design content or issuance chronology')
    if not instruction.effective_window.contains(context.business_time):
        return 'unavailable', None
    evidence = []
    for ref in instruction.evidence_refs:
        row = read(ref, EvidenceRecord, context.business_time)
        if row.source_kind == 'synthetic' or row.basis_kind != 'observed':
            raise TaskConflict('Revision instruction recovery requires observed native issuance evidence')
        if row.effective_window is not None and not row.effective_window.contains(context.business_time):
            return 'unavailable', None
        evidence.append(row.model_dump(mode='json'))
    if not evidence:
        return 'unavailable', None

    def dump(version):
        return {name: None if row is None else row.model_dump(mode='json') for name, row in version.items()}

    resolution = dict(schema_version='engineer-change-instruction-resolution.v1', condition_code=code,
        original_action_input=raw, action_input=current_raw, original_context=original.model_dump(mode='json'),
        context=context.model_dump(mode='json'), original_sources=dump(old), current_sources=dump(current),
        evidence=evidence, sources=reading.evidence(),
        original_gate=contract.result_adapter.validate_python(original_gate).model_dump(mode='json'))
    if validate_relation(source_identity=deepcopy(source), condition_code=code, resolution=deepcopy(resolution),
            context=context.model_copy(deep=True), reading=reading) is not True:
        raise TaskConflict('Revision recovery lacks independent native instruction issuance and original-duty authentication')
    result = handle_professional_change(context, current_input, reading)
    if result.get('kind') != 'completed':
        return 'waiting', None
    if result['payload'].get('choice') != 'revise':
        raise TaskConflict('Revision instruction recovery substitutes a different remedy choice')
    contract.validate_decision(current_input, result['payload'])
    resolution.update(current_result=contract.result_adapter.validate_python(result).model_dump(mode='json'), sources=reading.evidence())
    if validate_relation(source_identity=deepcopy(source), condition_code=code, resolution=deepcopy(resolution),
            context=context.model_copy(deep=True), reading=reading) is not True:
        raise TaskConflict('Revision recovery lacks independent native validation of current revision and remaining duties')
    return 'ready', resolution


def engineer_original_change_profile(read_current, validate_relation, condition_code=INSTRUCTION_REQUIRED_CODE):
    if condition_code not in _REF_KINDS or not callable(read_current) or not callable(validate_relation):
        raise ValueError('Revision instruction recovery requires actual guarded sources and native authority validation')

    def evaluate(check):
        if check.condition.condition_code != condition_code:
            raise TaskConflict('Revision instruction profile substitutes its selected original wait branch')
        selected = read_current(deepcopy(check))
        try:
            if condition_code == AUTHOR_HANDOFF_CODE:
                from src.coordination.engineer_change_author_conditions import check_engineer_change_author_handoff
                return check_engineer_change_author_handoff(check, selected, validate_relation)[0]
            if condition_code == DESIGN_AUTHORIZATION_CODE:
                from src.coordination.engineer_change_design_conditions import check_engineer_change_design_authorization
                return check_engineer_change_design_authorization(check, selected, validate_relation)[0]
            if condition_code == DESIGN_CANDIDATE_CODE:
                from src.coordination.engineer_change_design_conditions import check_engineer_change_design_candidate_limit
                return check_engineer_change_design_candidate_limit(check, selected, validate_relation)[0]
            if condition_code == DESIGN_WORK_CODE:
                from src.coordination.engineer_change_design_conditions import check_engineer_change_design_work_limit
                return check_engineer_change_design_work_limit(check, selected, validate_relation)[0]
            if condition_code == DESIGN_SUBMISSION_CODE:
                from src.coordination.engineer_change_design_conditions import check_engineer_change_design_submission
                return check_engineer_change_design_submission(check, selected, validate_relation)[0]
            return check_engineer_change_instruction(check, selected, validate_relation)[0]
        finally:
            selected.reading.recheck()

    return ConditionProfile('ENGINEER-A09', condition_code, '1', frozenset({'dependency_change'}), evaluate)
