"""Authenticate original research task readiness without resetting delegation or spending history."""
from copy import deepcopy
from dataclasses import dataclass

from src.actions.contracts.catalog import ActionContract
from src.actions.contracts.common import ActionContext, EvidenceRecord, Reference
from src.actions.contracts.architect_research_objects import (
    ArchitectResearchAuthorityView, ArchitectResearchTaskView, ArchitectResearchProfileView,
    ArchitectResearchScopeView, ArchitectResearchLimitView, ArchitectResearchRequestView,
)
from src.actions.contracts.qs_cost_objects import QSCostBriefView
from src.actions.contracts.qs_research_objects import QSResearchExpenseView, QSResearchCostFactView
from src.actions.contracts.references import ActionReadView
from src.actions.roles.architect_research import compare_preliminary_options, recheck_original_architect_research_wait
from src.coordination.contractor_closeout_conditions import ContractorCloseoutConditionReading
from src.coordination.continuations import ConditionProfile
from src.coordination.tasks import TaskConflict, task_digest
from src.organization.registry import scope_covers


CODE = 'architect.research.task_ready'


@dataclass(frozen=True)
class ArchitectResearchConditionReading(ContractorCloseoutConditionReading):
    contract: ActionContract | None = None


def check_architect_research_ready(check, selected, validate_relation):
    source = check.source['identity']
    if (source['action_id'] != 'ARCHITECT-A13' or source['role'] != 'Architect' or source['purpose'] != 'action'
            or check.condition.condition_code != CODE or check.condition.trigger != 'dependency_change'
            or tuple(ref.kind for ref in check.condition.object_refs) != ('Task',)
            or check.signal.run_id != source['run_id'] or check.signal.organization_id != source['organization_id']
            or not isinstance(selected, ArchitectResearchConditionReading) or not callable(validate_relation)
            or not isinstance(selected.context, ActionContext) or not isinstance(selected.original_context, ActionContext)
            or not isinstance(selected.reading, ActionReadView) or not isinstance(selected.history_ref, Reference)):
        raise TaskConflict('Research recovery requires the original private Architect task wait')
    context, original, reading = selected.context, selected.original_context, selected.reading
    raw, current_raw = deepcopy(selected.original_action_input), deepcopy(selected.action_input)
    if (task_digest(raw) != source['input_sha256'] or task_digest(original.model_dump(mode='json')) != source['context_sha256']
            or original.operation_id != source['request_id'] or context.operation_id == source['request_id']
            or context.run_id != source['run_id'] or context.contract_ref != original.contract_ref
            or context.contract_ref.id != 'ARCHITECT-A13' or context.scope != original.scope or context.execution_mode != 'llm'
            or context.business_time != check.signal.business_time or context.business_time.clock_ref != original.business_time.clock_ref
            or context.business_time.offset < original.business_time.offset
            or reading.organization_id != source['organization_id'] or reading._resolver.source_mode != 'formal'):
        raise TaskConflict('Research recovery replaces original snapshot, scope, time or current independent read authority')
    reading.check_method_context(context, 'ARCHITECT-A13')
    contract = selected.contract
    if not isinstance(contract, ActionContract) or contract.action_id != 'ARCHITECT-A13' or contract.role != 'Architect':
        raise TaskConflict('Research recovery lacks its actual original registered A13 contract')
    original_input, current_input = contract.validate_input(raw), contract.validate_input(current_raw)

    def physical(refs):
        result = {ref.key()[:2]: ref for ref in refs}
        if len(result) != len(refs):
            raise TaskConflict('Research recovery aliases original options, requirements or cost histories')
        return result

    def read(ref, schema, at):
        row = reading.resolve(ref)
        if (not isinstance(row, schema) or row.ref != ref
                or hasattr(row, 'scope') and not scope_covers(row.scope, context.scope)):
            raise TaskConflict('Research recovery lacks exact typed original/current scoped sources')
        point = getattr(row, 'available_at', None)
        if point is not None and (point.clock_ref != at.clock_ref or point.offset > at.offset):
            raise TaskConflict('Research recovery introduces a source unavailable at its original/query time')
        return row

    versions = []
    for values, at in ((original_input, original.business_time), (current_input, context.business_time)):
        task = read(values.task_ref, ArchitectResearchTaskView, at)
        authority = read(values.research_authority_ref, ArchitectResearchAuthorityView, at)
        brief = read(values.brief_ref, QSCostBriefView, at)
        profile = read(values.design_profile_ref, ArchitectResearchProfileView, at)
        scope = read(values.comparison_scope_ref, ArchitectResearchScopeView, at)
        limit = read(values.expenditure_limit_ref, ArchitectResearchLimitView, at)
        if (values.scope != context.scope or task.organization_id != source['organization_id']
                or limit.organization_id != source['organization_id'] or authority.delegate_organization_id != source['organization_id']
                or task.brief_ref != brief.ref or task.design_profile_ref != profile.ref or task.comparison_scope_ref != scope.ref
                or task.expenditure_limit_ref != limit.ref or authority.task_ref != task.ref or limit.task_ref != task.ref):
            raise TaskConflict('Research recovery substitutes original task, delegation, comparison, brief or spending limits')
        request = None if task.request_profile_ref is None else read(task.request_profile_ref, ArchitectResearchRequestView, at)
        expenses = {key: read(ref, QSResearchExpenseView, at) for key, ref in physical(limit.expense_refs).items()}
        fact_refs = {row.cost_fact_ref.key(): row.cost_fact_ref for row in expenses.values()}
        facts = {key: read(ref, QSResearchCostFactView, at) for key, ref in physical(list(fact_refs.values())).items()}
        versions.append(dict(task=task, authority=authority, brief=brief, profile=profile, scope=scope,
            limit=limit, request=request, expenses=expenses, facts=facts))
    old, current = versions
    for name in ('task', 'authority', 'brief', 'profile', 'scope', 'limit'):
        before, after = old[name], current[name]
        if before.ref.key()[:2] != after.ref.key()[:2] or before.ref == after.ref and before != after:
            raise TaskConflict('Research recovery replaces an original physical input or rewrites an immutable version')
    if old['task'].ref != check.condition.object_refs[0] or current['task'].ref != selected.history_ref:
        raise TaskConflict('Research recovery substitutes its actual original/current task query anchor')
    for name in ('client_organization_id', 'delegate_organization_id', 'terms_digest'):
        if getattr(old['authority'], name) != getattr(current['authority'], name):
            raise TaskConflict('Research recovery changes original client/provider or confirmed terms')
    for name in ('service_request_ref', 'appointment_ref', 'accepted_terms_ref', 'acceptance_ref', 'confirmation_ref'):
        if getattr(old['authority'], name).key()[:2] != getattr(current['authority'], name).key()[:2]:
            raise TaskConflict('Research recovery discards original accepted/confirmed appointment history')
    for name in ('available_option_refs', 'professional_refs', 'cost_refs', 'question_refs'):
        if not set(physical(getattr(old['task'], name))) <= set(physical(getattr(current['task'], name))):
            raise TaskConflict('Research recovery drops original options, assessments, costs or questions')
    before_request, after_request = old['request'], current['request']
    if before_request is not None:
        if (after_request is None or before_request.ref.key()[:2] != after_request.ref.key()[:2]
                or before_request.purpose != after_request.purpose):
            raise TaskConflict('Research recovery changes original investigation/preparation request identity or purpose')
        for name in ('input_refs', 'output_requirement_refs', 'dependency_refs'):
            if not set(physical(getattr(before_request, name))) <= set(physical(getattr(after_request, name))):
                raise TaskConflict('Research recovery drops original investigation inputs, dependencies or expected outputs')
    if (old['limit'].budget_cap.currency != current['limit'].budget_cap.currency
            or old['limit'].effort_cap.unit != current['limit'].effort_cap.unit):
        raise TaskConflict('Research recovery reinterprets original work or spending units')
    for group in ('expenses', 'facts'):
        if not set(old[group]) <= set(current[group]):
            raise TaskConflict('Research recovery removes original committed/incurred work or spending history')
        for key, before in old[group].items():
            after = current[group][key]
            if (before.ref == after.ref and before != after or before.task_ref.key()[:2] != after.task_ref.key()[:2]
                    or before.amount != after.amount or before.effort != after.effort
                    or before.status == 'incurred' and after.status != 'incurred'
                    or group == 'expenses' and before.cost_fact_ref.key()[:2] != after.cost_fact_ref.key()[:2]):
                raise TaskConflict('Research recovery erases actual costs, releases commitments or duplicates investment identity')
    original_gate = recheck_original_architect_research_wait(original, original_input, reading)
    if original_gate['resume_condition']['object_refs'] != list(check.condition.object_refs):
        raise TaskConflict('Research wait differs from the actual original bounded task processor')
    history = current['task']
    evidence = []
    for ref in history.evidence_refs:
        row = read(ref, EvidenceRecord, context.business_time)
        if row.source_kind == 'synthetic' or row.basis_kind != 'observed':
            raise TaskConflict('Research recovery requires observed actual task readiness or bounded closure evidence')
        if row.effective_window is not None and not row.effective_window.contains(context.business_time):
            return 'unavailable', None
        evidence.append(row.model_dump(mode='json'))
    if not evidence:
        return 'unavailable', None
    current_result = compare_preliminary_options(context, current_input, reading)
    if current_result.get('kind') != 'completed':
        return 'waiting', None
    contract.validate_decision(current_input, current_result['payload'])

    def dump(version):
        return {name: ({str(key): row.model_dump(mode='json') for key, row in value.items()}
            if isinstance(value, dict) else None if value is None else value.model_dump(mode='json'))
            for name, value in version.items()}

    resolution = dict(schema_version='architect-research-task-resolution.v1', condition_code=CODE,
        history=history.model_dump(mode='json'), original_action_input=raw, action_input=current_raw,
        original_context=original.model_dump(mode='json'), context=context.model_dump(mode='json'),
        original_sources=dump(old), current_sources=dump(current), evidence=evidence, sources=reading.evidence(),
        original_gate=contract.result_adapter.validate_python(original_gate).model_dump(mode='json'),
        current_result=contract.result_adapter.validate_python(current_result).model_dump(mode='json'))
    if validate_relation(source_identity=deepcopy(source), condition_code=CODE, resolution=deepcopy(resolution),
            context=context.model_copy(deep=True), reading=reading) is not True:
        raise TaskConflict('Research recovery lacks independent native delegation, task readiness and remaining-limit authentication')
    return 'ready', resolution


def architect_original_research_profile(read_current, validate_relation, condition_code=CODE):
    if condition_code != CODE or not callable(read_current) or not callable(validate_relation):
        raise ValueError('Research recovery requires actual guarded original task sources and native authority validation')
    def evaluate(check):
        selected = read_current(deepcopy(check))
        try:
            return check_architect_research_ready(check, selected, validate_relation)[0]
        finally:
            selected.reading.recheck()
    return ConditionProfile('ARCHITECT-A13', CODE, '1', frozenset({'dependency_change'}), evaluate)
