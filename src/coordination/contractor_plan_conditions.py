"""Authenticate original plan waits and actual dependency/capacity resolutions."""
from copy import deepcopy

from src.actions.contracts.catalog import ActionContract
from src.actions.contracts.common import ActionContext, EvidenceRecord, Reference
from src.actions.contracts.contractor_planning_objects import (
    ContractorWorkMandateView, ContractorPlanningProfileView, ContractorWorkPlanView,
    ContractorPlanDependencyView, ContractorBidCapacityView,
    ContractorSupplyCommitmentView,
)
from src.actions.contracts.references import ActionReadView
from src.actions.roles import contractor_planning as planning_role
from src.coordination.tasks import TaskConflict, task_digest


CYCLE_CODE = 'contractor-plan-circular-dependency-requires-responsible-party-resolution'
CAPACITY_CODE = 'contractor-plan-shared-resource-capacity-conflict'


def check_contractor_plan_cycle(check, selected, validate_relation, *, terminal=False):
    return _check_contractor_plan_wait(check, selected, validate_relation, code=CYCLE_CODE, terminal=terminal)


def check_contractor_plan_capacity(check, selected, validate_relation, *, terminal=False):
    return _check_contractor_plan_wait(check, selected, validate_relation, code=CAPACITY_CODE, terminal=terminal)


def _check_contractor_plan_wait(check, selected, validate_relation, *, code, terminal=False):
    from src.coordination.contractor_supply_conditions import ContractorSupplyConditionReading
    source = check.source['identity']
    if (terminal or source['action_id'] != 'CONTRACTOR-A05' or source['role'] != 'Contractor' or source['purpose'] != 'action'
            or check.condition.condition_code != code or check.condition.trigger != 'dependency_change'
            or not check.condition.object_refs
            or code == CAPACITY_CODE and len(check.condition.object_refs) != 1
            or any(ref.kind != ('Dependency' if code == CYCLE_CODE else 'ContractorCapacity') for ref in check.condition.object_refs)
            or check.signal.run_id != source['run_id'] or check.signal.organization_id != source['organization_id']
            or not isinstance(selected, ContractorSupplyConditionReading) or not callable(validate_relation)
            or not isinstance(selected.context, ActionContext) or not isinstance(selected.original_context, ActionContext)
            or not isinstance(selected.reading, ActionReadView) or not isinstance(selected.history_ref, Reference)):
        raise TaskConflict('Cycle recovery requires the original multi-dependency wait and private Contractor')
    context, original, reading = selected.context, selected.original_context, selected.reading
    raw, current_raw = deepcopy(selected.original_action_input), deepcopy(selected.action_input)
    if (task_digest(raw) != source['input_sha256'] or task_digest(original.model_dump(mode='json')) != source['context_sha256']
            or original.operation_id != source['request_id'] or context.operation_id == source['request_id']
            or context.run_id != source['run_id'] or context.contract_ref != original.contract_ref
            or context.contract_ref.id != 'CONTRACTOR-A05' or context.scope != original.scope or context.execution_mode != 'llm'
            or context.business_time != check.signal.business_time or context.business_time.clock_ref != original.business_time.clock_ref
            or context.business_time.offset < original.business_time.offset
            or reading.organization_id != source['organization_id'] or reading._resolver.source_mode != 'formal'):
        raise TaskConflict('Cycle recovery changes original snapshot, private scope, current time or authority')
    reading.check_method_context(context, 'CONTRACTOR-A05')
    contract = selected.contract
    if not isinstance(contract, ActionContract) or contract.action_id != 'CONTRACTOR-A05' or contract.role != 'Contractor':
        raise TaskConflict('Cycle recovery lacks its actual registered original action contract')
    original_input, current_input = contract.validate_input(raw), contract.validate_input(current_raw)
    if original_input.work_basis.kind != current_input.work_basis.kind or original_input.authorized_scope_ref != current_input.authorized_scope_ref:
        raise TaskConflict('Cycle recovery promotes preparation to construction or changes authorized work scope')

    def validate_evidence(refs, at, *, historic=False):
        for ref in refs:
            row = reading.resolve(ref)
            if not isinstance(row, EvidenceRecord) or row.ref != ref:
                raise TaskConflict('Plan recovery substitutes an exact Evidence source')
            if row.effective_window is not None:
                window = row.effective_window
                if (window.start.clock_ref != at.clock_ref or window.end.clock_ref != at.clock_ref
                        or window.start.offset > at.offset or not historic and not window.contains(at)):
                    raise TaskConflict('Plan recovery evidence is not valid at its original invocation or signing time')

    def read(ref, schema, at):
        row = reading.resolve(ref)
        if not isinstance(row, schema) or row.ref != ref:
            raise TaskConflict('Cycle recovery lacks exact typed original/current plan sources')
        if hasattr(row, 'available_at') and (row.available_at.clock_ref != at.clock_ref or row.available_at.offset > at.offset):
            raise TaskConflict('Cycle recovery injects future or unrelated-clock source history')
        window = getattr(row, 'effective_window', None)
        if window is not None and (window.start.clock_ref != at.clock_ref or window.end.clock_ref != at.clock_ref):
            raise TaskConflict('Plan recovery changes original source window clock')
        point = getattr(row, 'authored_at', at)
        if point.clock_ref != at.clock_ref or point.offset > at.offset:
            raise TaskConflict('Plan recovery injects a future or unrelated signing time')
        validate_evidence(getattr(row, 'evidence_refs', []), point, historic=isinstance(row, ContractorSupplyCommitmentView))
        if isinstance(row, ContractorSupplyCommitmentView):
            validate_evidence([row.amount.basis_ref], at, historic=True)
        return row

    def physical(refs):
        result = {ref.key()[:2]: ref for ref in refs}
        if len(result) != len(refs):
            raise TaskConflict('Cycle recovery repeats physical dependency/resource/plan history')
        return result

    versions = []
    for action_input, invocation in ((original_input, original), (current_input, context)):
        basis = action_input.work_basis
        ref = basis.contract_ref if basis.kind == 'contract' else basis.authorization_ref
        mandate = read(ref, ContractorWorkMandateView, invocation.business_time)
        profile = read(mandate.planning_profile_ref, ContractorPlanningProfileView, invocation.business_time)
        if (mandate.organization_id != source['organization_id'] or mandate.mandate_kind != basis.kind
                or profile.mandate_ref != mandate.ref or profile.organization_id != source['organization_id']
                or profile.choice not in {'plan', 'revise_plan'} or profile.plan_ref is None):
            raise TaskConflict('Cycle recovery substitutes original Contractor/mandate/planning branch')
        plan = read(profile.plan_ref, ContractorWorkPlanView, invocation.business_time)
        capacity = read(action_input.capacity_ref, ContractorBidCapacityView, invocation.business_time)
        if plan.mandate_ref != mandate.ref or capacity.organization_id != source['organization_id']:
            raise TaskConflict('Cycle recovery borrows another work mandate or resource calendar')
        dependencies = [read(ref, ContractorPlanDependencyView, invocation.business_time) for ref in action_input.dependency_refs]
        versions.append(dict(mandate=mandate, profile=profile, plan=plan, capacity=capacity, dependencies=dependencies))
    old, current = versions
    if (old['mandate'].ref.key()[:2] != current['mandate'].ref.key()[:2]
            or old['profile'].choice != current['profile'].choice or old['plan'].ref.key()[:2] != current['plan'].ref.key()[:2]
            or old['plan'].purpose != current['plan'].purpose
            or any(getattr(old['mandate'], field) != getattr(current['mandate'], field)
                for field in ('mandate_kind', 'region_id', 'object_type', 'work_type', 'special_condition_codes', 'required_qualification_codes'))):
        raise TaskConflict('Cycle recovery replaces original plan, work mandate, purpose or qualification domain')
    for field in ('dependency_refs', 'design_refs', 'work_method_refs', 'supplier_offer_refs'):
        if not set(physical(getattr(original_input, field))) <= set(physical(getattr(current_input, field))):
            raise TaskConflict('Cycle recovery omits original dependency, design, method or supply-offer history')
    original_tasks = {task.local_key: task for task in old['plan'].tasks}
    current_tasks = {task.local_key: task for task in current['plan'].tasks}
    if len(current_tasks) != len(current['plan'].tasks) or set(original_tasks) != set(current_tasks):
        raise TaskConflict('Cycle recovery drops, duplicates or substitutes original tasks')
    for key, before in original_tasks.items():
        after = current_tasks[key]
        if (before.scope_ref != after.scope_ref or before.work_method_ref.key()[:2] != after.work_method_ref.key()[:2]
                or before.target_quantities and before.target_quantities != after.target_quantities
                or set(physical(before.dependency_refs)) != set(physical(after.dependency_refs))):
            raise TaskConflict('Cycle recovery rewrites original task scope, work method, known targets or dependency identities')
    before_prior, after_prior = old['profile'].prior_plan_ref, current['profile'].prior_plan_ref
    if ((before_prior is None) != (after_prior is None)
            or before_prior is not None and before_prior.key()[:2] != after_prior.key()[:2]):
        raise TaskConflict('Cycle recovery substitutes original effective plan under revision')
    if before_prior is not None:
        before = read(before_prior, ContractorWorkPlanView, original.business_time)
        after = read(after_prior, ContractorWorkPlanView, context.business_time)
        if not set(physical(before.commitment_refs)) <= set(physical(after.commitment_refs)):
            raise TaskConflict('Cycle recovery drops existing formal reservations of the original prior plan')
    old_occupations = {row.commitment_ref.key()[:2]: row for row in old['capacity'].commitments}
    new_occupations = {row.commitment_ref.key()[:2]: row for row in current['capacity'].commitments}
    if (len(old_occupations) != len(old['capacity'].commitments)
            or len(new_occupations) != len(current['capacity'].commitments)):
        raise TaskConflict('Plan recovery duplicates known original resource occupation history')
    released_occupations = [row.model_dump(mode='json') for key, row in old_occupations.items() if key not in new_occupations]
    for key, before in old_occupations.items():
        if key not in new_occupations:
            # Preserve the old row as history. The independent native callback
            # below must authenticate its actual release, never omission alone.
            continue
        after = new_occupations[key]
        if (before.resource_ref.key()[:2] != after.resource_ref.key()[:2]
                or before.quantity != after.quantity or before.window != after.window):
            raise TaskConflict('Cycle recovery rewrites original resource occupation quantity or window')
    old_procurement = physical(old['mandate'].procurement_history_refs)
    new_procurement = physical(current['mandate'].procurement_history_refs)
    if not set(old_procurement) <= set(new_procurement):
        raise TaskConflict('Cycle recovery drops original supply or payment history')
    for key, ref in old_procurement.items():
        before = read(ref, ContractorSupplyCommitmentView, original.business_time)
        after = read(new_procurement[key], ContractorSupplyCommitmentView, context.business_time)
        excluded = {'ref', 'mandate_ref', 'status', 'available_at', 'effective_window', 'evidence_refs'}
        if (before.mandate_ref != old['mandate'].ref or after.mandate_ref != current['mandate'].ref
                or before.model_dump(exclude=excluded) != after.model_dump(exclude=excluded)
                or before.status == 'released' and after.status != 'released'
                or before.status == 'paid' and after.status == 'committed'):
            raise TaskConflict('Cycle recovery rewrites existing supply business, amount, payment or release history')
    historical_comparisons = []
    if code == CYCLE_CODE:
        original_gate = planning_role.recheck_original_contractor_plan_cycle(original, original_input, reading)
    else:
        original_gate, historical_comparisons = planning_role.recheck_original_contractor_plan_capacity(original, original_input, reading)
    if original_gate.get('resume_condition', {}).get('object_refs') != list(check.condition.object_refs):
        raise TaskConflict('Plan wait differs from the actual original dependency/capacity gate')
    original_dependencies = {row.ref.key()[:2]: row for row in old['dependencies']}
    current_dependencies = {row.ref.key()[:2]: row for row in current['dependencies']}
    physical([row.ref for row in old['dependencies']]); physical([row.ref for row in current['dependencies']])
    ref = selected.history_ref
    if ref.key()[:2] != check.condition.object_refs[0].key()[:2]:
        raise TaskConflict('Cycle query must select the actual first original/current dependency')
    if code == CYCLE_CODE:
        if ref != current_dependencies[ref.key()[:2]].ref:
            raise TaskConflict('Cycle query is absent from the actual current dependency history')
        history = current_dependencies[ref.key()[:2]]
    else:
        if check.condition.object_refs[0] != old['capacity'].ref or ref != current['capacity'].ref:
            raise TaskConflict('Capacity query must name the actual original/current shared calendar')
        history = current['capacity']
    changes, evidence = [], {}
    for key, before in original_dependencies.items():
        after = current_dependencies[key]
        if (before.mandate_ref != old['mandate'].ref or after.mandate_ref != current['mandate'].ref
                or before.dependent_task_key != after.dependent_task_key
                or before.responsible_organization_id != after.responsible_organization_id or before.scope != after.scope):
            raise TaskConflict('Cycle recovery changes original dependency/task/responsible party/scope identity')
        if not after.effective_window.contains(context.business_time):
            return 'unavailable', None
        if set(before.predecessor_task_keys) != set(after.predecessor_task_keys):
            if not after.evidence_refs:
                return 'waiting', None
            changes.append(dict(original=before.model_dump(mode='json'), current=after.model_dump(mode='json')))
            for evidence_ref in after.evidence_refs:
                row = read(evidence_ref, EvidenceRecord, context.business_time)
                if row.source_kind == 'synthetic' or row.basis_kind != 'observed':
                    raise TaskConflict('Cycle resolution requires actual observed responsible-party evidence')
                if row.effective_window is not None and not row.effective_window.contains(context.business_time):
                    return 'unavailable', None
                evidence[evidence_ref.key()] = row.model_dump(mode='json')
    if code == CAPACITY_CODE or released_occupations:
        capacity = current['capacity']
        if not capacity.effective_window.contains(context.business_time):
            return 'unavailable', None
        if not capacity.evidence_refs:
            return 'waiting', None
        for evidence_ref in capacity.evidence_refs:
            row = read(evidence_ref, EvidenceRecord, context.business_time)
            if row.source_kind == 'synthetic' or row.basis_kind != 'observed':
                raise TaskConflict('Capacity recovery requires actual observed independent shared resource evidence')
            if row.effective_window is not None and not row.effective_window.contains(context.business_time):
                return 'unavailable', None
            evidence[evidence_ref.key()] = row.model_dump(mode='json')
    if code == CYCLE_CODE and not changes:
        return 'waiting', None
    current_result = planning_role.plan_work_and_supply(context, current_input, reading)
    if current_result.get('kind') != 'completed':
        return 'waiting', None
    contract.validate_decision(current_input, current_result['payload'])
    resolution = dict(schema_version=('contractor-plan-cycle-resolution.v1' if code == CYCLE_CODE
            else 'contractor-plan-capacity-resolution.v1'), condition_code=code,
        disposition='actual_responsible_party_cycle_resolution' if code == CYCLE_CODE else 'current_shared_capacity',
        history=history.model_dump(mode='json'),
        original_action_input=raw, action_input=current_raw, original_context=original.model_dump(mode='json'),
        context=context.model_dump(mode='json'), dependency_changes=changes, evidence=list(evidence.values()),
        original_plan=old['plan'].model_dump(mode='json'), current_plan=current['plan'].model_dump(mode='json'),
        original_mandate=old['mandate'].model_dump(mode='json'), current_mandate=current['mandate'].model_dump(mode='json'),
        original_capacity=old['capacity'].model_dump(mode='json'), current_capacity=current['capacity'].model_dump(mode='json'),
        original_gate=contract.result_adapter.validate_python(original_gate).model_dump(mode='json'),
        historical_comparisons=historical_comparisons,
        released_original_occupations=released_occupations,
        current_result=contract.result_adapter.validate_python(current_result).model_dump(mode='json'), sources=reading.evidence())
    if released_occupations:
        release_resolution = dict(schema_version='contractor-plan-occupation-release-resolution.v1',
            original_capacity=resolution['original_capacity'], current_capacity=resolution['current_capacity'],
            released_original_occupations=released_occupations, evidence=resolution['evidence'],
            sources=resolution['sources'])
        if validate_relation(source_identity=deepcopy(source), condition_code=code, terminal_supply_history=False,
                resolution=deepcopy(release_resolution), context=context.model_copy(deep=True), reading=reading) is not True:
            raise TaskConflict('Plan recovery lacks independent native proof of actual original occupation release')
    if validate_relation(source_identity=deepcopy(source), condition_code=code, terminal_supply_history=False,
            resolution=deepcopy(resolution), context=context.model_copy(deep=True), reading=reading) is not True:
        raise TaskConflict('Cycle recovery lacks native responsible-party resolution/remaining duty/current authority authentication')
    return 'ready', resolution
