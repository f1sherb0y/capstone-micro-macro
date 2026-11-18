"""Resume an original Government A11 use-plan dependency without approving use."""
from copy import deepcopy
from dataclasses import dataclass

from pydantic import TypeAdapter

from src.actions.contracts.common import ActionContext, EvidenceRecord, ScopeRef, ref_type
from src.actions.contracts.government_use_objects import (
    GovUseApplicationView, GovUseCaseView, GovUseProcedureView, GovUsePlanView,
    GovSchedulingTaskView, GovSchedulingDependencyView,
)
from src.actions.contracts.references import ActionReadView
from src.coordination.continuations import ConditionProfile
from src.coordination.tasks import TaskConflict, task_digest
from src.coordination.government_use_capacity import read_use_capacity
from src.organization.registry import scope_covers


_DEPENDENCY_CODE = 'government-use-verification-dependency-wait'
_CAPACITY_CODE = 'government-use-resource-capacity-wait'
_CODES = (_DEPENDENCY_CODE, _CAPACITY_CODE)
_INPUT_REFS = {'case_ref': 'RegulatoryCase', 'use_application_ref': 'RegulatoryApplication', 'procedure_ref': 'Procedure'}
_INPUT_LISTS = {'completed_scope_refs': 'WorkFact', 'professional_proof_refs': 'Assessment',
    'test_result_refs': 'MethodResult', 'permit_refs': 'Permit', 'remaining_condition_refs': 'PermitCondition'}


@dataclass(frozen=True)
class GovernmentUseConditionReading:
    context: ActionContext
    reading: ActionReadView
    original_action_input: dict
    action_input: dict


def government_original_use_dependency_profile(read_current, validate_relation):
    """Wake a fresh A11 judgment after the same original dependency is known true.

    The original invocation is recovered from its journal snapshot. Independent
    native validation authenticates the full original/current application and
    independently authored plan lineage. Readiness signs no use decision,
    clears no permit condition and grants no inspection or supervision effect.
    """
    return _government_original_use_profile(_DEPENDENCY_CODE, read_current, validate_relation)


def government_original_use_capacity_profile(read_current, validate_relation):
    return _government_original_use_profile(_CAPACITY_CODE, read_current, validate_relation)


def government_original_use_profiles(read_current, validate_relation):
    return tuple(_government_original_use_profile(code, read_current, validate_relation) for code in _CODES)


def _government_original_use_profile(code, read_current, validate_relation):
    if code not in _CODES or not callable(read_current) or not callable(validate_relation):
        raise ValueError('Government use recovery requires actual reading and independent native relation validation')

    def identity(ref):
        return ref.kind, ref.id

    def identities(refs):
        result = {identity(ref) for ref in refs}
        if len(result) != len(refs):
            raise TaskConflict('Government use recovery duplicates a physical source identity')
        return result

    def evaluate(check):
        source, old_refs = check.source['identity'], check.condition.object_refs
        if (source['action_id'] != 'GOV-A11' or source['role'] != 'Government' or source['purpose'] != 'action'
                or check.condition.condition_code != code or check.condition.trigger != 'dependency_change'
                or check.signal.run_id != source['run_id'] or check.signal.organization_id != source['organization_id']
                or len(old_refs) != 1 or old_refs[0].kind != ('Dependency' if code == _DEPENDENCY_CODE else 'ResourceCalendar')):
            raise TaskConflict('Government use recovery replaces its original action, recipient or dependency wait')
        selected = read_current(deepcopy(check))
        if (not isinstance(selected, GovernmentUseConditionReading) or not isinstance(selected.context, ActionContext)
                or not isinstance(selected.reading, ActionReadView) or not isinstance(selected.original_action_input, dict)
                or not isinstance(selected.action_input, dict)):
            raise TaskConflict('Government use recovery requires typed current reading and original snapshot input')
        context, reading = selected.context.model_copy(deep=True), selected.reading
        try:
            old_input, action_input = deepcopy(selected.original_action_input), deepcopy(selected.action_input)
            fields = {'scope', *_INPUT_REFS, *_INPUT_LISTS}
            if (set(old_input) != fields or set(action_input) != fields
                    or context.run_id != source['run_id'] or reading.organization_id != source['organization_id']
                    or context.contract_ref.kind != 'ActionContract' or context.contract_ref.id != 'GOV-A11'
                    or context.execution_mode == 'offline_fixture' or reading._resolver.source_mode != 'formal'
                    or context.business_time != check.signal.business_time or context.operation_id == source['request_id']
                    or task_digest(old_input) != source['input_sha256'] or old_input['scope'] != action_input['scope']):
                raise TaskConflict('Government use recovery changes original snapshot, scope or current invocation')
            scope, now = TypeAdapter(ScopeRef).validate_python(action_input['scope']), context.business_time
            if not scope_covers(context.scope, scope):
                raise TaskConflict('Government use recovery leaves the original authorized application coverage')
            reading.check_method_context(context, 'GOV-A11')
            input_refs = []
            for raw in (old_input, action_input):
                parsed = {field: ref_type(kind).model_validate(raw[field]) for field, kind in _INPUT_REFS.items()}
                for field, kind in _INPUT_LISTS.items():
                    if not isinstance(raw[field], list):
                        raise TaskConflict('Government use recovery requires original received source lists')
                    parsed[field] = [ref_type(kind).model_validate(ref) for ref in raw[field]]
                input_refs.append(parsed)
            old_selected, current_selected = input_refs
            if (any(identity(old_selected[field]) != identity(current_selected[field]) for field in _INPUT_REFS)
                    or any(identities(old_selected[field]) != identities(current_selected[field]) for field in _INPUT_LISTS)):
                raise TaskConflict('Government use recovery substitutes original application/procedure or received proof/permit/conditions')
            versions, proof_rows = [], []
            for refs, current in ((old_selected, False), (current_selected, True)):
                case, application, procedure = (reading.resolve(refs[field]) for field in _INPUT_REFS)
                if (not isinstance(case, GovUseCaseView) or not isinstance(application, GovUseApplicationView)
                        or not isinstance(procedure, GovUseProcedureView) or case.ref != refs['case_ref']
                        or application.ref != refs['use_application_ref'] or procedure.ref != refs['procedure_ref']
                        or case.organization_id != source['organization_id'] or application.recipient_organization_id != source['organization_id']
                        or procedure.organization_id != source['organization_id'] or application.case_ref != case.ref
                        or application.applicant_id != case.applicant_id or application.scope != scope
                        or case.current_submission_ref != application.submission_ref
                        or procedure.case_ref != case.ref or procedure.application_ref != application.ref
                        or procedure.content_sha256 != application.content_sha256
                        or procedure.ref != case.procedure_ref or procedure.ref != application.procedure_ref
                        or procedure.choice not in {'plan_verification', 'continue_supervision'} or procedure.plan_ref is None
                        or any({ref.key() for ref in getattr(application, field)} != {ref.key() for ref in refs[field]} for field in _INPUT_LISTS)):
                    raise TaskConflict('Government use recovery changes original agency, current content or independently selected procedure')
                plan = reading.resolve(procedure.plan_ref)
                purpose = 'use_verification' if procedure.choice == 'plan_verification' else 'continuing_supervision'
                if (not isinstance(plan, GovUsePlanView) or plan.ref != procedure.plan_ref or plan.application_ref != application.ref
                        or plan.content_sha256 != application.content_sha256 or plan.purpose != purpose
                        or plan.author_action_id != 'GOV-A03' or plan.author_organization_id != source['organization_id']
                        or not plan.plan.items or identities(plan.task_refs) != identities([item.task_ref for item in plan.plan.items])
                        or {ref.key() for ref in plan.task_refs} != {item.task_ref.key() for item in plan.plan.items}):
                    raise TaskConflict('Government use recovery substitutes original independently authored plan or complete task set')
                for row in (case, procedure, plan):
                    if not scope_covers(scope, row.scope):
                        raise TaskConflict('Government use recovery source leaves original application scope')
                versions.append((case, application, procedure, plan))
                proof_rows.extend((row, current) for row in (case, application, procedure, plan))
            old_case, old_application, old_procedure, old_plan = versions[0]
            case, application, procedure, plan = versions[1]
            if (old_application.content_sha256 != application.content_sha256
                    or any(getattr(old_application, field) != getattr(application, field) for field in (
                        'applicant_id', 'submitter_id', 'submitted_at', 'use_codes'))
                    or identity(old_application.submission_ref) != identity(application.submission_ref)
                    or any(identity(getattr(old_case, field)) != identity(getattr(case, field)) for field in ('matter_ref', 'jurisdiction_ref'))
                    or old_procedure.choice != procedure.choice or identity(old_plan.ref) != identity(plan.ref)
                    or identity(old_plan.plan.work_profile_ref) != identity(plan.plan.work_profile_ref)
                    or identity(old_plan.resource_calendar_ref) != identity(plan.resource_calendar_ref)
                    or identities(old_plan.task_refs) != identities(plan.task_refs)):
                raise TaskConflict('Government use recovery replaces original use request, content, plan purpose, method or tasks')
            if any(row.available_at.clock_ref != now.clock_ref or row.available_at.offset > now.offset
                    or not row.effective_window.contains(now) for row in (case, application, procedure, plan)):
                return 'unavailable'
            if (case.history_coverage != 'complete' or application.history_coverage != 'complete'
                    or case.as_of != now or application.as_of != now or not procedure.modeled
                    or procedure.permitted.state != 'known' or procedure.permitted.value is not True):
                return 'waiting'
            if (procedure.actor_id != context.actor_id or procedure.function_ref != context.function_ref
                    or procedure.authorization_ref not in context.authorization_refs):
                raise TaskConflict('Government use recovery lacks its current own acting procedure authority')
            capacity, extra_refs = None, []
            original_task = task = original_dependency = dependency = None
            if code == _CAPACITY_CODE:
                capacity = read_use_capacity(reading=reading, original_plan=old_plan, plan=plan,
                    original_case=old_case, case=case, original_calendar_ref=old_refs[0], now=now)
                if isinstance(capacity, str):
                    return capacity
                if not capacity['ready']:
                    return 'waiting'
                proof_rows.extend(capacity['proof_rows'])
                extra_refs = capacity['proof_refs']
            else:
                original_dependency = reading.resolve(old_refs[0])
                if (not isinstance(original_dependency, GovSchedulingDependencyView) or original_dependency.ref.key() != old_refs[0].key()
                        or original_dependency.task_ref.key() not in {ref.key() for ref in old_plan.task_refs}):
                    raise TaskConflict('Government use dependency is absent from the original plan task set')
                original_task = reading.resolve(original_dependency.task_ref)
                task_ref = next(ref for ref in plan.task_refs if identity(ref) == identity(original_dependency.task_ref))
                task = reading.resolve(task_ref)
                if (not isinstance(original_task, GovSchedulingTaskView) or not isinstance(task, GovSchedulingTaskView)
                        or original_task.ref != original_dependency.task_ref or task.ref != task_ref
                        or original_task.case_ref != old_case.ref or task.case_ref != case.ref
                        or original_task.work_profile_ref != old_plan.plan.work_profile_ref or task.work_profile_ref != plan.plan.work_profile_ref
                        or original_task.organization_id != source['organization_id'] or task.organization_id != source['organization_id']
                        or task.execution_action_id != ('GOV-A11' if procedure.choice == 'plan_verification' else 'GOV-A10')
                        or any(getattr(original_task, field) != getattr(task, field) for field in (
                            'organization_id', 'scope', 'execution_action_id', 'function_code', 'discipline_codes', 'resource_shares'))
                        or any(identity(getattr(original_task, field)) != identity(getattr(task, field)) for field in (
                            'authority_ref', 'function_ref', 'estimate_ref'))
                        or identities(original_task.dependency_refs) != identities(task.dependency_refs)
                        or old_refs[0].key() not in {ref.key() for ref in original_task.dependency_refs}
                        or not identities(original_task.work_fact_refs) <= identities(task.work_fact_refs)):
                    raise TaskConflict('Government use dependency replaces original task function, resources or retained history')
                old_item = next(item for item in old_plan.plan.items if item.task_ref == original_task.ref)
                item = next(item for item in plan.plan.items if item.task_ref == task.ref)
                for row, selected_item in ((original_task, old_item), (task, item)):
                    if (selected_item.window != row.planned_window or selected_item.existing_assignment_ref != row.existing_assignment_ref
                            or set(selected_item.resource_ids) != {share.resource_ref.id for share in row.resource_shares}
                            or {ref.key() for ref in selected_item.dependency_refs} != {ref.key() for ref in row.dependency_refs}):
                        raise TaskConflict('Government use dependency plan item changes its exact task window or dependency set')
                if (len(set(old_item.resource_ids)) != len(old_item.resource_ids) or len(set(item.resource_ids)) != len(item.resource_ids)
                        or set(old_item.resource_ids) != set(item.resource_ids)):
                    raise TaskConflict('Government use dependency replaces original selected physical resources')
                dependency_ref = next(ref for ref in task.dependency_refs if identity(ref) == identity(old_refs[0]))
                dependency = reading.resolve(dependency_ref)
                if (not isinstance(dependency, GovSchedulingDependencyView) or dependency.ref != dependency_ref
                        or dependency.task_ref != task.ref or dependency.scope != original_dependency.scope
                        or not scope_covers(scope, task.scope) or not scope_covers(scope, dependency.scope)):
                    raise TaskConflict('Government use recovery substitutes original dependency association or coverage')
                if any(row.available_at.clock_ref != now.clock_ref or row.available_at.offset > now.offset
                        or not row.effective_window.contains(now) for row in (task, dependency)):
                    return 'unavailable'
                if (task.status != 'authorized' or task.as_of != now or dependency.as_of != now
                        or dependency.satisfied.state != 'known' or dependency.satisfied.value is not True):
                    return 'waiting'
                proof_rows.extend([(original_task, False), (task, True), (original_dependency, False), (dependency, True)])
            observed = {}
            evidence_refs = list(extra_refs)
            for row, current in proof_rows:
                evidence_refs.extend((ref, current) for ref in row.evidence_refs)
            for ref, current in evidence_refs:
                evidence = reading.resolve(ref)
                if (not isinstance(evidence, EvidenceRecord) or evidence.source_kind == 'synthetic' or evidence.basis_kind != 'observed'):
                    raise TaskConflict('Government use recovery requires actual observed native source evidence')
                if current and evidence.effective_window is not None and not evidence.effective_window.contains(now):
                    return 'unavailable'
                observed[ref.key()] = evidence.model_dump(mode='json')
            extra_validation = {} if capacity is None else {'condition_code': code, 'capacity_history': deepcopy(capacity['history'])}
            if validate_relation(source_identity=deepcopy(source), original_action_input=old_input, action_input=action_input,
                    original_case=old_case.model_copy(deep=True), case=case.model_copy(deep=True),
                    original_application=old_application.model_copy(deep=True), application=application.model_copy(deep=True),
                    original_procedure=old_procedure.model_copy(deep=True), procedure=procedure.model_copy(deep=True),
                    original_plan=old_plan.model_copy(deep=True), plan=plan.model_copy(deep=True),
                    original_task=None if original_task is None else original_task.model_copy(deep=True), task=None if task is None else task.model_copy(deep=True),
                    original_dependency=None if original_dependency is None else original_dependency.model_copy(deep=True), dependency=None if dependency is None else dependency.model_copy(deep=True),
                    evidence=deepcopy(list(observed.values())), context=context.model_copy(deep=True), reading=reading, **extra_validation) is not True:
                raise TaskConflict('Government use recovery lacks native original dependency/plan lineage and full current input validation')
            return 'ready'
        finally:
            reading.recheck()

    return ConditionProfile('GOV-A11', code, '1', frozenset({'dependency_change'}), evaluate)
