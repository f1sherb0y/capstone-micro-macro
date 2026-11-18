"""CONTRACTOR-A07 submits bounded inputs and preserves original engineering history."""
from fractions import Fraction

from src.actions.contracts.common import EvidenceRecord, Known, TimeWindow
from src.actions.contracts import contractor_execution_objects as execution_objects
from src.actions.contracts.contractor_execution_objects import (
    ContractorExecutionTaskView, ContractorExecutionProfileView, ContractorTaskReleaseView,
    ContractorExecutionGateView, ContractorExecutionMethodView, ContractorProductionRuleView,
    ContractorInventoryView, ContractorInventoryAllocationView, ContractorExecutionConditionView,
    ContractorWorkExecutionView, ContractorExecutionRequestView, ContractorWorkRecordView,
    ContractorExecutionObservationView, ContractorExecutionRequirementView,
    ContractorExecutionInputView,
    ContractorReadyAllocationView, ContractorReadyInputView, ContractorReadyAllocationFactView,
    ContractorWorkMandateView,
)
from src.actions.contracts.owner_study_objects import unique_refs
from src.actions.roles.owner import ObservationGap, _needs, _unsupported
from src.actions.roles.qs_change import content_digest
from src.methods.pricing import decimal_fraction
from src.organization.models import Authorization, RoleAssignment
from src.organization.registry import scope_covers


def execute_or_report(context, action_input, reading):
    now, scope, org = context.business_time, action_input.scope_ref, reading.organization_id

    def keys(refs):
        unique_refs(refs)
        return {ref.key() for ref in refs}

    def positive(value):
        return isinstance(value, Known) and value.value is True

    def clock(point):
        if point.clock_ref != now.clock_ref:
            _unsupported('contractor-execution-clock-alignment')

    def evidence(refs, *, at=None, historic=False):
        point = now if at is None else at
        clock(point)
        if point.offset > now.offset:
            _needs('received_original_execution_evidence_time')
        for ref in refs:
            row = reading.resolve(ref)
            if not isinstance(row, EvidenceRecord) or row.ref != ref:
                _unsupported('contractor-execution-evidence-schema')
            if row.effective_window is not None:
                clock(row.effective_window.start)
                clock(row.effective_window.end)
                if row.effective_window.start.offset > now.offset:
                    _needs('received_original_execution_evidence', [ref])
                if (at is not None or not historic) and not row.effective_window.contains(point):
                    _needs('original_execution_evidence_valid_at_use', [ref])

    def actual(refs, *, at=None, historic=False):
        evidence(refs, at=at, historic=historic)
        for ref in refs:
            row = reading.resolve(ref)
            if row.basis_kind != 'observed' or (reading._resolver.source_mode == 'formal' and row.source_kind == 'synthetic'):
                _needs('actual_observed_original_execution_evidence', [ref])

    def read(ref, schema, historic=False, linked=False, *, evidence_at_field=None):
        row = reading.resolve(ref)
        if not isinstance(row, schema) or getattr(row, 'ref', getattr(row, 'function_ref', ref)) != ref:
            _unsupported('contractor-execution-projection:' + ref.kind)
        if hasattr(row, 'scope') and not linked and not scope_covers(scope, row.scope):
            raise ValueError('Execution source widens original authorized physical scope')
        if hasattr(row, 'available_at'):
            clock(row.available_at)
            if row.available_at.offset > now.offset:
                _needs('received_original_execution_source', [ref])
        if hasattr(row, 'effective_window'):
            clock(row.effective_window.start)
            clock(row.effective_window.end)
            if not historic and not row.effective_window.contains(now):
                _needs('current_original_execution_source', [ref])
        point = None if evidence_at_field is None else getattr(row, evidence_at_field)
        if point is not None:
            clock(point)
            if point.offset > row.available_at.offset:
                raise ValueError('Execution source precedes its original actual authorship')
        evidence(getattr(row, 'evidence_refs', []), at=point, historic=historic)
        return row

    def authorize(ref, actor, function, organization, action, at, target_scope):
        grant = read(ref, Authorization, True, True); assignment = read(function, RoleAssignment, True, True)
        roles = {'CONTRACTOR': 'Contractor', 'ENGINEER': 'Engineer', 'SUPPLIER': 'Supplier', 'GOV': 'Government',
            'OWN': 'Owner', 'ARCHITECT': 'Architect', 'QS': 'QS', 'BANK': 'Bank'}
        if (grant.actor_id != actor or grant.function_ref != function or grant.organization_id != organization
                or assignment.function_ref != function or assignment.role != roles.get(action.split('-')[0]) or action not in grant.action_ids
                or not any(scope_covers(s, target_scope) for s in grant.scopes)):
            raise ValueError('Execution changes original actor/function/action/scope authority')
        clock(at); clock(grant.validity.start); clock(grant.validity.end)
        if at.offset > now.offset:
            _needs('received_original_execution_author_time', [ref])
        if not grant.validity.contains(at):
            _needs('original_execution_authority_at_execution', [ref])
        for basis_ref in (*grant.basis_refs, *assignment.basis_refs):
            if basis_ref.kind == 'Evidence':
                evidence([basis_ref], at=at)
            else:
                basis = reading.resolve(basis_ref)
                if hasattr(basis, 'available_at'):
                    clock(basis.available_at)
                    if basis.available_at.offset > at.offset:
                        _needs('original_execution_authority_basis_available_at_use', [basis_ref])
        return grant

    def author(row):
        clock(row.authored_at)
        if row.authored_at.offset > row.available_at.offset or not row.effective_window.contains(row.authored_at):
            raise ValueError('Execution observation predates its actual original creation')
        return authorize(row.author_authority_ref, row.author_actor_id, row.author_function_ref,
            row.author_organization_id, row.author_action_id, row.authored_at, row.scope)

    def covers(outer, inner):
        clock(outer.start); clock(outer.end); clock(inner.start); clock(inner.end)
        if outer.bounds != 'closed_open' or inner.bounds != 'closed_open':
            _unsupported('contractor-execution-half-open-window')
        return outer.start.offset <= inner.start.offset < inner.end.offset <= outer.end.offset

    def complete(choice, **fields):
        reading.recheck()
        return {'kind': 'completed', 'payload': {'choice': choice, **fields,
            'note': 'Original input intention/report/history only. Engineering core computes actual gross/net work, consumption, costs and quality consequences and atomically records effects; no direct progress, cost or output write occurs.'}}

    def wait(code, refs):
        reading.recheck()
        return {'kind': 'deferred', 'reason_code': code, 'resume_condition': {'trigger': 'dependency_change',
            'object_refs': refs, 'earliest_time': None, 'condition_code': code}}

    def technical(code):
        raise ObservationGap({'kind': 'technical_error', 'error': {'kind': 'unrecorded',
            'correlation_id': context.operation_id, 'code': code}, 'retryability': 'unknown'})

    def unconsumed_material(allocation):
        quantity = decimal_fraction(allocation.quantity.value)
        consumed = decimal_fraction(allocation.already_consumed.value)
        if quantity < 0 or consumed < 0 or consumed > quantity:
            raise ValueError('Inventory allocation and consumed quantities must satisfy 0 <= consumed <= allocated')
        return quantity - consumed

    def executions(refs, task_ref=None):
        keys(refs); operations, business, events, physical = set(), set(), set(), set()
        rows = []
        for ref in refs:
            row = read(ref, ContractorWorkExecutionView, True)
            if (row.organization_id != org or row.run_id != context.run_id or task_ref is not None and row.task_ref != task_ref
                    or row.operation_id in operations or row.business_key in business):
                raise ValueError('Execution history repeats or substitutes original organization/run/task/operation/business')
            operations.add(row.operation_id); business.add(row.business_key)
            request = read(row.request_ref, ContractorExecutionRequestView, True)
            if (request.task_ref != row.task_ref or request.operation_id != row.operation_id or request.business_key != row.business_key
                    or request.scope_ref != row.scope or row.request_sha256 != content_digest(request)):
                raise ValueError('Execution history changes original submitted request content')
            if row.status == 'recorded':
                if row.core_event_id is None or row.core_event_id in events or row.recorded_at is None or row.query_status != 'present':
                    raise ValueError('Recorded execution requires distinct original core event and known receipt')
                events.add(row.core_event_id); clock(row.recorded_at)
                if row.recorded_at.offset > row.available_at.offset:
                    raise ValueError('Execution receipt was available before original core recording')
                if request.available_at.offset > row.recorded_at.offset:
                    raise ValueError('Execution receipt predates its original submitted request source')
                keys(row.work_record_refs)
                for record_ref in row.work_record_refs:
                    record = read(record_ref, ContractorWorkRecordView, True)
                    command = row if record.execution_ref == row.ref else read(record.execution_ref, ContractorWorkExecutionView, True)
                    execution_objects.validate_contractor_work_record_execution(row, record, command)
                    gross, net = decimal_fraction(record.gross_quantity.value), decimal_fraction(record.net_quantity.value)
                    if (record.core_event_id != row.core_event_id
                            or not scope_covers(row.scope, record.scope)
                            or record.gross_quantity.unit != record.net_quantity.unit or gross < 0 or net < 0 or net > gross):
                        raise ValueError('Work record changes original execution/event or exact gross/net quantities')
                    # WorkRecord has no actual occurrence time. Receipt recording
                    # and availability are not substitutes for physical occurrence.
                    actual([*record.evidence_refs, record.gross_quantity.basis_ref, record.net_quantity.basis_ref], historic=True)
                    if record.work_kind == 'rework':
                        if record.original_work_record_ref is None or net != 0:
                            raise ValueError('Rework must preserve original physical work and cannot count it again as net completion')
                        original = read(record.original_work_record_ref, ContractorWorkRecordView, True)
                        if (original.ref == record.ref or original.physical_work_key != record.physical_work_key
                                or original.available_at.offset > row.recorded_at.offset):
                            raise ValueError('Rework substitutes its original physical work record')
                        actual([*original.evidence_refs, original.gross_quantity.basis_ref,
                            original.net_quantity.basis_ref], historic=True)
                    elif net > 0:
                        if record.physical_work_key in physical:
                            raise ValueError('Execution history repeats net completion for the same original physical work slice')
                        physical.add(record.physical_work_key)
            elif row.work_record_refs or row.core_event_id is not None or row.recorded_at is not None:
                raise ValueError('Unknown or unexecuted command cannot pretend to have actual work effects')
            if row.status == 'failed':
                technical('contractor-execution-original-engineering-command-failed')
            rows.append(row)
        return rows

    try:
        if scope != context.scope:
            raise ValueError('Execution changes its original invocation scope')
        operation = action_input.execution_context
        if operation.kind == 'existing':
            if not operation.execution_refs:
                _needs('original_execution_history_for_reconciliation')
            rows = executions(operation.execution_refs)
            unresolved = [r.ref for r in rows if r.status == 'submitted_unknown' or r.query_status in {'unknown', 'not_queried'}]
            if unresolved:
                return wait('contractor-execution-query-original-command-before-any-replay', unresolved)
            return complete('reconcile', execution_refs=operation.execution_refs)
        task = read(operation.task_ref, ContractorExecutionTaskView, historic=operation.kind == 'report')
        profile = read(task.execution_profile_ref, ContractorExecutionProfileView)
        if (task.organization_id != org or task.scope != scope or profile.organization_id != org or profile.task_ref != task.ref
                or profile.authority_ref not in context.authorization_refs):
            raise ValueError('Execution changes original contractor, task, scope or acting authority')
        grant = authorize(profile.authority_ref, context.actor_id, context.function_ref, org, 'CONTRACTOR-A07', now, scope)
        if operation.kind == 'report':
            if profile.choice != 'report':
                raise ValueError('Report context cannot execute or rebalance work inputs')
            executions(operation.execution_refs, task.ref); keys(operation.observation_refs)
            observed_statuses, requirements = [], []
            for ref in operation.observation_refs:
                observation = read(ref, ContractorExecutionObservationView, True, evidence_at_field='authored_at')
                observation_grant = author(observation)
                actual(observation.evidence_refs, at=observation.authored_at)
                if observation.task_ref != task.ref or observation.author_organization_id != org or observation.author_action_id != 'CONTRACTOR-A07':
                    raise ValueError('Progress observation substitutes original contractor/task/function')
                if (task.available_at.offset > observation.authored_at.offset
                        or not {task.ref.key(), *(r.key() for r in observation.evidence_refs),
                            *(r.key() for r in observation.requirement_refs)} <= keys(observation_grant.readable_refs)):
                    raise ValueError('Progress observation lacks originally available task or source read authority')
                for requirement_ref in observation.requirement_refs:
                    original_requirement = read(requirement_ref, ContractorExecutionRequirementView, True)
                    if (original_requirement.task_ref != task.ref
                            or original_requirement.available_at.offset > observation.authored_at.offset):
                        raise ValueError('Progress observation substitutes an originally unavailable task requirement')
                observed_statuses.append(observation.status); requirements.extend(observation.requirement_refs)
            status = 'blocked' if 'blocked' in observed_statuses else ('awaiting_check' if 'awaiting_check' in observed_statuses else 'working')
            if not observed_statuses or status != profile.reported_status:
                _needs('actual_original_observation_supporting_reported_task_status')
            keys(profile.requested_requirement_refs)
            if not keys(profile.requested_requirement_refs) <= set(r.key() for r in requirements):
                raise ValueError('Report invents a requirement absent from original observations')
            issues = []
            for ref in profile.requested_requirement_refs:
                requirement = read(ref, ContractorExecutionRequirementView, True)
                if requirement.task_ref != task.ref:
                    raise ValueError('Progress report substitutes another original task requirement')
                issues.append({'scope_ref': requirement.scope, 'requirement_ref': ref, 'evidence_refs': requirement.evidence_refs,
                    'disposition': requirement.disposition, 'responsible': requirement.responsible.model_dump(mode='python')})
            return complete('report', report={'task_ref': task.ref, 'observation_refs': operation.observation_refs,
                'execution_refs': operation.execution_refs, 'issues': issues, 'reported_status': status,
                'requested_requirement_refs': profile.requested_requirement_refs})
        if profile.choice not in {'execute', 'rebalance'}:
            raise ValueError('Ready context cannot borrow report configuration')
        if task.history_coverage != 'complete' or task.as_of != now or keys(task.prior_execution_refs) != keys(operation.prior_execution_refs):
            _needs('complete_current_original_task_execution_history')
        rows = executions(operation.prior_execution_refs, task.ref)
        if any(r.status == 'submitted_unknown' or r.query_status in {'unknown', 'not_queried'} for r in rows):
            return wait('contractor-execution-query-before-reusing-uncertain-inputs', [r.ref for r in rows])
        if any(r.operation_id == context.operation_id for r in rows):
            return wait('contractor-execution-original-operation-already-recorded', [r.ref for r in rows if r.operation_id == context.operation_id])
        mandate = read(task.mandate_ref, ContractorWorkMandateView, linked=True)
        if (mandate.organization_id != org or not positive(mandate.effective) or not scope_covers(mandate.scope, task.scope)
                or task.purpose not in mandate.allowed_task_purposes or mandate.mandate_kind == 'preparation' and task.purpose != 'preparation'):
            _needs('effective_original_execution_mandate_for_task')
        work_window = read(operation.execution_window_ref, TimeWindow)
        if not work_window.contains(now) or work_window != task.execution_window or not covers(grant.validity, work_window):
            _needs('current_original_released_execution_window')
        release = read(operation.release_ref, ContractorTaskReleaseView)
        if (release.organization_id != org or release.task_ref != task.ref or release.action_ref != task.action_ref
                or release.work_method_ref != operation.work_method_ref or release.status != 'released'
                or task.state not in {'released', 'working'} or not covers(release.effective_window, work_window)):
            _needs('actual_current_core_task_release')
        gates = read(release.current_gate_ref, ContractorExecutionGateView)
        if (gates.task_ref != task.ref or gates.release_ref != release.ref or gates.as_of != now or gates.coverage != 'complete'
                or not gates.requirement_refs or keys(gates.requirement_refs) != keys(task.requirement_refs) or not positive(gates.satisfied)
                or not covers(gates.effective_window, work_window)):
            _needs('all_current_core_execution_gates_satisfied')
        method = read(operation.work_method_ref, ContractorExecutionMethodView, linked=True)
        if not scope_covers(method.scope, task.scope):
            raise ValueError('Work method does not cover the original execution task')
        if (task.work_method_ref != method.ref or mandate.region_id not in method.region_ids or mandate.object_type not in method.object_types
                or mandate.work_type not in method.work_types or not set(mandate.special_condition_codes) <= set(method.special_condition_codes)):
            _unsupported('contractor-execution-method-object-location-domain')
        rule = read(method.consequence_rule_ref, ContractorProductionRuleView, linked=True)
        if not scope_covers(rule.scope, task.scope):
            raise ValueError('Production rule does not cover the original execution task')
        if rule.work_method_ref != method.ref or not positive(rule.supported) or method.accelerated and not positive(rule.acceleration_modeled):
            _unsupported('contractor-execution-production-cost-quality-consequences-unmodeled')
        evidence([rule.throughput_basis_ref, rule.cost_basis_ref, rule.quality_basis_ref, method.productivity_basis_ref])
        if not covers(method.effective_window, work_window) or not covers(rule.effective_window, work_window) or not covers(mandate.effective_window, work_window):
            _needs('original_method_rule_and_mandate_for_full_execution_window')
        if (decimal_fraction(method.minimum_resource_quantity.value) <= 0 or method.minimum_resource_quantity.unit != method.capacity_unit
                or method.minimum_material_quantity is not None and decimal_fraction(method.minimum_material_quantity.value) <= 0):
            raise ValueError('Necessary work method inputs must declare positive exact minimum quantities')
        evidence([method.minimum_resource_quantity.basis_ref, *([method.minimum_material_quantity.basis_ref] if method.minimum_material_quantity else [])])
        if (keys(operation.condition_refs) != keys(task.condition_refs) or keys(operation.inventory_refs) != keys(task.inventory_refs)):
            _needs('complete_current_original_task_conditions_and_inventory')
        codes = set()
        for ref in operation.condition_refs:
            condition = read(ref, ContractorExecutionConditionView, evidence_at_field='authored_at'); author(condition)
            evidence(condition.evidence_refs, at=now)
            if condition.task_ref != task.ref or condition.as_of != now or not positive(condition.actual_satisfied):
                _needs('actual_current_site_condition_for_execution')
            if not covers(condition.effective_window, work_window):
                _needs('actual_site_conditions_for_full_execution_window')
            codes.add(condition.condition_code)
        if not set(method.required_condition_codes) <= codes:
            _needs('all_original_method_site_conditions')
        if not profile.allocations:
            _needs('actual_nonzero_resource_input_intention')
        keys(operation.available_input_refs); keys([r.resource_ref for r in profile.allocations])
        available_allocations = [read(ref, ContractorReadyAllocationView) for ref in operation.available_input_refs]
        total = Fraction()
        for allocation in profile.allocations:
            matching = [r for r in available_allocations if r.resource_ref == allocation.resource_ref]
            if len(matching) != 1:
                raise ValueError('Execution intention requires a unique original actual resource allocation')
            original = matching[0]; resource = read(original.resource_ref, ContractorExecutionInputView, linked=True)
            evidence([original.quantity.basis_ref])
            amount = decimal_fraction(allocation.quantity.value)
            if (original.task_ref != task.ref or original.organization_id != org or original.resource_kind != 'resource'
                    or original.status not in {'reserved', 'available'} or original.as_of != now or resource.as_of != now
                    or resource.history_coverage != 'complete' or resource.organization_id != org or not positive(resource.accepted)
                    or resource.region_id != mandate.region_id or resource.resource_kind != method.resource_kind
                    or not positive(resource.actually_present) or not covers(resource.effective_window, work_window)
                    or allocation.task_scope_ref != task.scope or allocation.window_ref != operation.execution_window_ref
                    or amount <= 0 or allocation.quantity.unit != method.capacity_unit or original.quantity.unit != method.capacity_unit
                    or amount > decimal_fraction(original.quantity.value) or not covers(original.execution_window, work_window)):
                _needs('actual_exclusive_nonzero_crew_or_equipment_for_execution')
            facts = [read(ref, ContractorReadyAllocationFactView, True, True) for ref in resource.allocations]
            keys(resource.allocations)
            if len({r.core_event_id for r in facts}) != len(facts):
                raise ValueError('Execution repeats an original core resource allocation event')
            selected = [r for r in facts if r.ref == original.commitment_ref]
            if (len(selected) != 1 or selected[0].allocation_ref != original.ref or selected[0].task_ref != task.ref
                    or selected[0].quantity != original.quantity or selected[0].status != 'reserved' or selected[0].execution_window != original.execution_window):
                raise ValueError('Execution input changes original actual core reservation')
            if not isinstance(resource.actual_available, Known) or resource.actual_available.value.unit != method.capacity_unit:
                _needs('known_actual_resource_quantity_for_execution')
            usable = decimal_fraction(resource.actual_available.value.value)
            actual([resource.actual_available.value.basis_ref])
            if usable <= 0:
                _needs('actual_observed_nonzero_resource_quantity')
            boundaries = {work_window.start.offset, work_window.end.offset}
            for fact in facts:
                clock(fact.execution_window.start); clock(fact.execution_window.end)
                evidence([fact.quantity.basis_ref], historic=True)
                if fact.resource_ref != resource.ref or fact.quantity.unit != method.capacity_unit:
                    raise ValueError('Execution resource ledger changes original physical resource/unit')
                if fact.execution_window.bounds != 'closed_open' or decimal_fraction(fact.quantity.value) <= 0:
                    raise ValueError('Actual resource reservation must use a positive quantity and half-open window')
                boundaries.update([max(work_window.start.offset, fact.execution_window.start.offset), min(work_window.end.offset, fact.execution_window.end.offset)])
            points = sorted(p for p in boundaries if work_window.start.offset <= p <= work_window.end.offset)
            if any(sum((decimal_fraction(f.quantity.value) for f in facts if f.status == 'reserved'
                    and f.execution_window.start.offset < end and start < f.execution_window.end.offset), Fraction()) > usable
                    for start, end in zip(points, points[1:])):
                _needs('actual_shared_resource_capacity_for_execution')
            evidence([allocation.quantity.basis_ref]); total += amount
        if method.minimum_resource_quantity.unit != method.capacity_unit or total < decimal_fraction(method.minimum_resource_quantity.value) or total <= 0:
            _needs('all_necessary_positive_method_resource_inputs')
        inventories = [read(ref, ContractorInventoryView) for ref in operation.inventory_refs]
        keys([r.batch_ref for r in inventories]); inventory_map = {r.batch_ref.key(): r for r in inventories}
        keys([r.allocation_ref for r in profile.materials]); material_total = Fraction()
        for material in profile.materials:
            inventory = inventory_map.get(material.batch_ref.key())
            if inventory is None or inventory.organization_id != org or inventory.as_of != now or inventory.coverage != 'complete':
                _needs('complete_current_actual_material_inventory')
            if inventory.product_ref != method.material_product_ref or not isinstance(inventory.usable, Known):
                _needs('actual_usable_material_for_original_work_method')
            batch = read(inventory.batch_ref, ContractorReadyInputView, linked=True)
            if batch.organization_id != org or batch.as_of != now or not positive(batch.accepted):
                _needs('actual_accepted_material_batch_for_execution')
            if (not isinstance(batch.actual_available, Known) or batch.actual_available.value.unit != inventory.usable.value.unit
                    or decimal_fraction(inventory.usable.value.value) > decimal_fraction(batch.actual_available.value.value)
                    or decimal_fraction(inventory.usable.value.value) <= 0):
                _needs('actual_accepted_batch_quantity_covers_usable_inventory')
            actual([batch.actual_available.value.basis_ref, inventory.usable.value.basis_ref])
            keys(inventory.allocation_refs)
            allocations = [read(ref, ContractorInventoryAllocationView) for ref in inventory.allocation_refs]
            selected = [r for r in allocations if r.ref == material.allocation_ref]
            if len(selected) != 1:
                raise ValueError('Material intention substitutes an original inventory allocation')
            allocated = selected[0]; amount = decimal_fraction(material.quantity.value)
            if (material.task_ref != task.ref or allocated.task_ref != task.ref or allocated.batch_ref != material.batch_ref
                    or allocated.inventory_ref != inventory.ref or allocated.status != 'allocated'
                    or material.quantity.unit != inventory.usable.value.unit or allocated.quantity.unit != material.quantity.unit
                    or allocated.already_consumed.unit != material.quantity.unit or amount <= 0
                    or amount > unconsumed_material(allocated)):
                _needs('original_allocated_unconsumed_positive_material_inputs')
            if len({r.core_event_id for r in allocations}) != len(allocations):
                raise ValueError('Inventory repeats the same original allocation event')
            outstanding = Fraction()
            for row in allocations:
                if row.inventory_ref != inventory.ref or row.batch_ref != inventory.batch_ref or row.quantity.unit != material.quantity.unit or row.already_consumed.unit != material.quantity.unit:
                    raise ValueError('Inventory ledger changes original batch/location/unit')
                evidence([row.quantity.basis_ref, row.already_consumed.basis_ref])
                remaining = unconsumed_material(row)
                if row.status in {'allocated', 'unknown'}:
                    outstanding += remaining
            if outstanding > decimal_fraction(inventory.usable.value.value):
                _needs('actual_usable_inventory_covers_all_outstanding_allocations')
            evidence([material.quantity.basis_ref, inventory.usable.value.basis_ref]); material_total += amount
        if method.minimum_material_quantity is not None:
            if any(m.quantity.unit != method.minimum_material_quantity.unit for m in profile.materials) or material_total < decimal_fraction(method.minimum_material_quantity.value) or material_total <= 0:
                _needs('all_necessary_positive_method_material_inputs')
        elif profile.materials:
            raise ValueError('Work method does not declare material input quantity support')
        return complete(profile.choice, task_ref=task.ref,
            allocations=[a.model_dump(mode='python') for a in profile.allocations], materials=[m.model_dump(mode='python') for m in profile.materials])
    except ObservationGap as gap:
        reading.recheck()
        return gap.result
