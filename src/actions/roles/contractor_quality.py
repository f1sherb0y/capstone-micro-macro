"""CONTRACTOR-A08 checks visible scope and requests remedy without defect closure."""
from fractions import Fraction

from src.actions.contracts.common import EvidenceRecord, Known, TimeWindow, walk_references
from src.actions.contracts.contractor_quality_objects import (
    ContractorInspectionProfileView, ContractorInspectionRequirementView, ContractorInspectionMethodView,
    ContractorInspectionEvidenceView, ContractorVisibleDefectView, ContractorInspectionResultView,
    ContractorIsolationAuthorityView, ContractorRemedyPlanView, ContractorRemedyCapacityView,
    ContractorWorkRecordView, ContractorBidMethodView,
    ContractorRemedyDependencyView, ContractorInspectionObservationMethodView,
)
from src.actions.contracts.contractor_objects import QualificationView
from src.actions.contracts.contractor_bid_objects import ContractorBidResourceView, ContractorBidCommitmentView, ContractorBidCapacityView
from src.actions.contracts.owner_study_objects import unique_refs
from src.actions.roles.owner import ObservationGap, _needs, _unsupported
from src.actions.roles.qs_change import content_digest
from src.methods.capacity import CAPACITY_METHOD, CapacityInput, ExactAmount
from src.methods.pricing import decimal_fraction
from src.organization.models import Authorization, RoleAssignment
from src.organization.registry import scope_covers


def inspect_and_remedy(context, action_input, reading):
    now, scope, org = context.business_time, action_input.scope_ref, reading.organization_id

    def keys(refs):
        unique_refs(refs)
        return {ref.key() for ref in refs}

    def true(value):
        return isinstance(value, Known) and value.value is True

    def clock(point):
        if point.clock_ref != now.clock_ref:
            _unsupported('contractor-quality-clock-alignment')

    def evidence(refs, *, at=None, historic=False):
        point = now if at is None else at
        clock(point)
        if point.offset > now.offset:
            _needs('received_original_quality_evidence_time')
        for ref in refs:
            row = reading.resolve(ref)
            if not isinstance(row, EvidenceRecord) or row.ref != ref:
                _unsupported('contractor-quality-evidence-schema')
            if row.effective_window is not None:
                clock(row.effective_window.start)
                clock(row.effective_window.end)
                if row.effective_window.start.offset > now.offset:
                    _needs('received_original_quality_evidence', [ref])
                if (at is not None or not historic) and not row.effective_window.contains(point):
                    _needs('original_quality_evidence_valid_at_use', [ref])

    def read(ref, schema, historic=False, linked=False, *, evidence_at_field=None, source_at=None):
        row = reading.resolve(ref)
        if not isinstance(row, schema) or getattr(row, 'ref', getattr(row, 'function_ref', ref)) != ref:
            _unsupported('contractor-quality-projection:' + ref.kind)
        if hasattr(row, 'scope') and not linked and not scope_covers(scope, row.scope):
            raise ValueError('Quality input expands the original actual inspection scope')
        use = now if source_at is None else source_at
        clock(use)
        if use.offset > now.offset:
            _needs('received_original_quality_source_time', [ref])
        if hasattr(row, 'available_at'):
            clock(row.available_at)
            if row.available_at.offset > use.offset:
                _needs('received_original_quality_source', [ref])
        if hasattr(row, 'effective_window'):
            clock(row.effective_window.start)
            clock(row.effective_window.end)
            if (source_at is not None or not historic) and not row.effective_window.contains(use):
                _needs('current_original_quality_source', [ref])
        point = source_at if evidence_at_field is None else getattr(row, evidence_at_field)
        if point is not None:
            clock(point)
            if evidence_at_field is not None and point.offset > row.available_at.offset:
                raise ValueError('Quality source precedes its actual authorship')
        evidence(getattr(row, 'evidence_refs', []), at=point, historic=historic)
        return row

    def authorize(ref, actor, function, organization, action, at, target_scope):
        grant = read(ref, Authorization, True, True); assignment = read(function, RoleAssignment, True, True)
        roles = {'CONTRACTOR': 'Contractor', 'ENGINEER': 'Engineer', 'GOV': 'Government', 'SUPPLIER': 'Supplier',
            'ARCHITECT': 'Architect', 'OWN': 'Owner', 'QS': 'QS', 'BANK': 'Bank'}
        if (grant.actor_id != actor or grant.function_ref != function or grant.organization_id != organization
                or assignment.function_ref != function or assignment.role != roles.get(action.split('-')[0])
                or action not in grant.action_ids
                or not any(scope_covers(s, target_scope) for s in grant.scopes)):
            raise ValueError('Quality source substitutes independent author/function/scope authority')
        clock(at); clock(grant.validity.start); clock(grant.validity.end)
        if at.offset > now.offset:
            _needs('received_original_quality_author_time', [ref])
        if not grant.validity.contains(at):
            _needs('original_quality_authority_at_execution', [ref])
        for basis_ref in (*grant.basis_refs, *assignment.basis_refs):
            if basis_ref.kind == 'Evidence':
                evidence([basis_ref], at=at)
            else:
                basis = reading.resolve(basis_ref)
                if hasattr(basis, 'available_at'):
                    clock(basis.available_at)
                    if basis.available_at.offset > at.offset:
                        _needs('original_quality_authority_basis_available_at_use', [basis_ref])
        return grant

    def author(row):
        clock(row.authored_at)
        if row.authored_at.offset > row.available_at.offset or not row.effective_window.contains(row.authored_at):
            raise ValueError('Quality source predates its original actual execution')
        return authorize(row.author_authority_ref, row.author_actor_id, row.author_function_ref,
            row.author_organization_id, row.author_action_id, row.authored_at, row.scope)

    def complete(choice, **fields):
        reading.recheck()
        return {'kind': 'completed', 'payload': {'choice': choice, 'scope_ref': scope, **fields,
            'note': profile.note + ' Scoped request only. Inspection/external acceptance, actual remedy, defect closure and recovery of work remain separately verified; no hidden quality, inventory return, liability or cost assignment is written.'}}

    def technical(code):
        raise ObservationGap({'kind': 'technical_error', 'error': {'kind': 'unrecorded',
            'correlation_id': context.operation_id, 'code': code}, 'retryability': 'unknown'})

    try:
        if scope != context.scope:
            raise ValueError('Inspection changes its original invocation scope')
        profile = read(action_input.inspection_profile_ref, ContractorInspectionProfileView)
        if profile.organization_id != org or profile.scope != scope or profile.authority_ref not in context.authorization_refs:
            raise ValueError('Inspection profile changes original contractor/scope or acting authority')
        authorize(profile.authority_ref, context.actor_id, context.function_ref, org, 'CONTRACTOR-A08', now, scope)
        if profile.history_coverage != 'complete' or profile.as_of != now:
            _needs('complete_current_original_inspection_profile')
        for field in ('work_record_refs', 'requirement_refs', 'defect_refs'):
            if keys(getattr(profile, field)) != keys(getattr(action_input, field)):
                _needs('complete_original_inspection_' + field)
        if keys(profile.evidence_refs_received) != keys(action_input.evidence_refs):
            _needs('complete_original_received_inspection_evidence')
        records = {ref.key(): read(ref, ContractorWorkRecordView, True) for ref in action_input.work_record_refs}
        for record in records.values():
            evidence([record.gross_quantity.basis_ref, record.net_quantity.basis_ref], historic=True)
        requirements = {ref.key(): read(ref, ContractorInspectionRequirementView) for ref in action_input.requirement_refs}
        for requirement in requirements.values():
            if not keys(requirement.work_record_refs) <= set(records):
                raise ValueError('Inspection requirement substitutes undeclared original work records')
        observed = {}; events = set()
        for ref in action_input.evidence_refs:
            row = read(ref, ContractorInspectionEvidenceView, True, evidence_at_field='authored_at')
            grant = author(row); clock(row.observed_at)
            record = records.get(row.work_record_ref.key())
            if (record is None or row.physical_work_key != record.physical_work_key or row.event_id in events
                    or row.observed_at.offset > row.authored_at.offset or not scope_covers(record.scope, row.scope)):
                raise ValueError('Inspection evidence substitutes observed original work, event, time or physical coverage')
            if (record.available_at.offset > row.authored_at.offset
                    or not {row.work_record_ref.key(), *(ref.key() for ref in row.evidence_refs)} <= keys(grant.readable_refs)):
                raise ValueError('Inspection author lacks originally available and readable work record')
            if row.kind not in {'actual_observation', 'actual_remedy'}:
                _needs('actual_original_observed_inspection_evidence', [ref])
            observed_basis = [reading.resolve(r) for r in row.evidence_refs]
            if any(basis.basis_kind != 'observed' or (reading._resolver.source_mode == 'formal'
                    and basis.source_kind == 'synthetic') for basis in observed_basis):
                _needs('actual_observed_inspection_basis', [ref])
            events.add(row.event_id); observed[row.ref.key()] = row
        defects = {}
        for ref in action_input.defect_refs:
            defect = read(ref, ContractorVisibleDefectView); observation = observed.get(defect.observation_ref.key())
            record = records.get(defect.work_record_ref.key())
            if (observation is None or record is None or defect.ref.key() not in keys(observation.defect_refs)
                    or defect.work_record_ref != observation.work_record_ref or defect.physical_work_key != record.physical_work_key
                    or not scope_covers(observation.scope, defect.scope) or not keys(defect.requirement_refs) <= set(requirements)):
                raise ValueError('Defect is absent from original visible observation or changes actual work/requirement coverage')
            for requirement_ref in defect.requirement_refs:
                requirement = requirements[requirement_ref.key()]
                if (defect.work_record_ref.key() not in keys(requirement.work_record_refs)
                        or not scope_covers(requirement.scope, defect.scope)):
                    raise ValueError('Defect cites an inspection requirement for different original work or scope')
            if defect.status == 'closed':
                _needs('original_open_observed_defect_for_disposition')
            defects[ref.key()] = defect
        choice = profile.choice
        if choice == 'isolate':
            if not defects or profile.isolation_authority_ref is None:
                _needs('original_visible_defects_and_independent_isolation_authority')
            authority = read(profile.isolation_authority_ref, ContractorIsolationAuthorityView, linked=True)
            if (authority.organization_id != org or authority.actor_id != context.actor_id or authority.function_ref != context.function_ref
                    or keys(authority.defect_refs) != set(defects) or not true(authority.permitted)
                    or not scope_covers(authority.scope, scope)):
                _needs('independent_original_own_work_isolation_authority')
            return complete(choice, issue_refs=action_input.defect_refs)
        if choice == 'rectify':
            if not defects or profile.remedy_plan_ref is None:
                _needs('original_scoped_remedy_plan_for_visible_defects')
            plan = read(profile.remedy_plan_ref, ContractorRemedyPlanView, evidence_at_field='authored_at'); author(plan)
            if plan.author_action_id != 'CONTRACTOR-A08' or plan.author_organization_id != org or keys(plan.defect_refs) != set(defects):
                raise ValueError('Remedy plan changes original responsible planner or visible defect set')
            if not plan.tasks or len({t.local_key for t in plan.tasks}) != len(plan.tasks) or set(plan.task_defect_refs) != {t.local_key for t in plan.tasks}:
                raise ValueError('Remedy plan requires locally unique task/defect bindings')
            saved = read(plan.capacity_result_ref, ContractorRemedyCapacityView, evidence_at_field='authored_at'); grant = author(saved)
            if saved.author_action_id != 'CONTRACTOR-A08' or saved.author_organization_id != org:
                raise ValueError('Remedy capacity result substitutes the original responsible planner')
            if saved.status == 'failed':
                technical('contractor-quality-original-remedy-plan-failed')
            if saved.status == 'unsupported':
                _unsupported('contractor-quality-remedy-capacity-unmodeled')
            if saved.status != 'ok' or saved.report is None:
                _needs('successful_original_remedy_capacity_result')
            snapshot = read(saved.capacity_ref, ContractorBidCapacityView)
            if snapshot.organization_id != org or snapshot.as_of != now or snapshot.coverage != 'complete':
                _needs('complete_current_original_remedy_resource_snapshot')
            if snapshot.qualification_coverage != 'complete':
                _needs('complete_current_original_remedy_qualification_snapshot')
            keys(snapshot.qualification_refs)
            qualifications = [read(ref, QualificationView, linked=True) for ref in snapshot.qualification_refs]
            if (keys([r.resource_ref for r in snapshot.resources]) != keys([r.resource_ref for r in saved.data.resources])
                    or snapshot.commitments != saved.data.commitments):
                raise ValueError('Remedy capacity evaluation drops original physical resources or occupied commitments')
            resources = {r.resource_ref.key(): r for r in saved.data.resources}; originals = {}
            demands = []; covered = set(); input_refs = [snapshot.ref, plan.ref, *action_input.defect_refs, *action_input.work_record_refs]
            input_refs.extend(snapshot.qualification_refs)
            task_map = {t.local_key: t for t in plan.tasks}; graph = {key: set() for key in task_map}
            keys([r.resource_ref for r in saved.data.resources]); keys([r.commitment_ref for r in saved.data.commitments])
            for resource in saved.data.resources:
                original = read(resource.resource_ref, ContractorBidResourceView, linked=True); input_refs.append(original.ref)
                if (original.organization_id != org or original.total != resource.total or original.region_id != resource.region_id
                        or resource.resource_kind != resource.resource_ref.id or original.effective_window != resource.effective_window):
                    raise ValueError('Remedy plan changes original physical resource snapshot')
                declared = next(r for r in snapshot.resources if r.resource_ref == original.ref)
                if (declared.total != original.total or declared.region_id != original.region_id
                        or declared.resource_kind != original.resource_kind or declared.effective_window != original.effective_window):
                    raise ValueError('Remedy resource snapshot changes original resource type or capacity')
                originals[original.ref.key()] = original
                evidence([resource.total.basis_ref])
            for commitment in saved.data.commitments:
                original = read(commitment.commitment_ref, ContractorBidCommitmentView, linked=True); input_refs.append(original.ref)
                if (original.organization_id != org or original.resource_ref != commitment.resource_ref
                        or original.quantity != commitment.quantity or original.window != commitment.window):
                    raise ValueError('Remedy plan changes original occupied resource')
                evidence([commitment.quantity.basis_ref])
            for task in plan.tasks:
                linked_defects = keys(plan.task_defect_refs[task.local_key]); covered.update(linked_defects)
                if not linked_defects or not linked_defects <= set(defects):
                    raise ValueError('Remedy task invents or omits observed defect coverage')
                defect_scope_refs = {ref.key() for key in linked_defects for ref in defects[key].scope.coverage_refs}
                if (not scope_covers(scope, task.scope_ref) or not scope_covers(plan.scope, task.scope_ref)
                        or not keys(task.scope_ref.coverage_refs) <= defect_scope_refs):
                    raise ValueError('Remedy task extends beyond actual affected defect coverage')
                method = read(task.work_method_ref, ContractorBidMethodView, linked=True); input_refs.append(method.ref)
                if not scope_covers(method.scope, task.scope_ref):
                    raise ValueError('Remedy method does not cover its original task scope')
                if plan.object_type not in method.object_types or plan.work_type not in method.work_types:
                    _unsupported('contractor-quality-remedy-object-work-method-domain')
                work_window = read(task.window_ref, TimeWindow); clock(work_window.start); clock(work_window.end); input_refs.append(task.window_ref)
                ticks = work_window.end.offset - work_window.start.offset
                if work_window.bounds != 'closed_open' or ticks <= 0 or work_window.start.offset < now.offset:
                    _unsupported('contractor-quality-remedy-finite-half-open-window')
                if (work_window.start.offset < method.effective_window.start.offset
                        or work_window.end.offset > method.effective_window.end.offset):
                    _needs('original_remedy_work_method_for_full_planned_window')
                for code in plan.required_qualification_codes:
                    if not any(q.organization_ref.id == org and q.qualification_code == code and plan.work_type in q.work_types
                            and isinstance(q.standing, Known) and q.standing.value
                            and q.effective_window.start.offset <= work_window.start.offset
                            and work_window.end.offset <= q.effective_window.end.offset for q in qualifications):
                        _needs('original_qualified_contractor_for_remedy_window')
                keys(task.dependency_refs)
                for ref in task.dependency_refs:
                    dependency = read(ref, ContractorRemedyDependencyView); input_refs.append(ref)
                    if (dependency.plan_ref != plan.ref or dependency.dependent_task_key != task.local_key
                            or not set(dependency.predecessor_task_keys) <= set(task_map)):
                        raise ValueError('Remedy dependency substitutes original plan or local task identities')
                    if not true(dependency.planning_permitted):
                        _needs('original_plannable_remedy_dependency')
                    graph[task.local_key].update(dependency.predecessor_task_keys)
                    for key in dependency.predecessor_task_keys:
                        predecessor_window = read(task_map[key].window_ref, TimeWindow)
                        if predecessor_window.end.offset > work_window.start.offset:
                            _needs('original_remedy_predecessor_before_dependent_task')
                if not task.allocations or not task.target_quantities:
                    _needs('explicit_original_remedy_inputs_and_targets')
                keys([a.resource_ref for a in task.allocations]); rate = method.quantity_per_capacity_tick
                if not isinstance(rate, Known) or decimal_fraction(rate.value) <= 0:
                    _unsupported('contractor-quality-remedy-productivity-method')
                evidence([method.productivity_basis_ref])
                target, amount = Fraction(), Fraction()
                for quantity in task.target_quantities:
                    evidence([quantity.basis_ref])
                    if quantity.unit != method.quantity_unit or decimal_fraction(quantity.value) <= 0:
                        raise ValueError('Remedy target changes exact method quantity unit or sign')
                    target += decimal_fraction(quantity.value)
                for allocation in task.allocations:
                    resource = resources.get(allocation.resource_ref.key())
                    if (resource is None or allocation.window_ref != task.window_ref or allocation.task_scope_ref != task.scope_ref
                            or allocation.quantity.unit != method.capacity_unit or resource.total.unit != method.capacity_unit
                            or originals[resource.resource_ref.key()].resource_kind != method.resource_kind or resource.region_id not in method.region_ids
                            or decimal_fraction(allocation.quantity.value) <= 0):
                        raise ValueError('Remedy allocation changes original resource/method/location/window or unit')
                    amount += decimal_fraction(allocation.quantity.value); evidence([allocation.quantity.basis_ref])
                    demands.append({'resource_kind': resource.resource_ref.id, 'region_id': resource.region_id,
                        'unit': method.capacity_unit, 'amount': ExactAmount.from_fraction(decimal_fraction(allocation.quantity.value)),
                        'window': work_window, 'basis_refs': [allocation.quantity.basis_ref]})
                if target > amount * decimal_fraction(rate.value) * ticks:
                    _needs('original_remedy_quantity_within_method_inputs_and_window')
            if covered != set(defects):
                raise ValueError('Remedy plan silently drops observed original defects')
            visiting, visited = set(), set()
            def visit(key):
                if key in visiting:
                    return False
                if key in visited:
                    return True
                visiting.add(key)
                if not all(visit(other) for other in graph[key]):
                    return False
                visiting.remove(key); visited.add(key)
                return True
            if not all(visit(key) for key in graph):
                _needs('original_remedy_circular_dependency_responsibility')
            # Name each physical pool separately in capacity arithmetic, retaining every supplied commitment.
            data = CapacityInput(clock_ref=now.clock_ref, demands=demands,
                resources=[r.model_copy(update={'resource_kind': r.resource_ref.id}) for r in saved.data.resources],
                commitments=saved.data.commitments, source_refs=saved.data.source_refs)
            if (saved.plan_ref != plan.ref or saved.plan_sha256 != content_digest(plan) or saved.method_ref != CAPACITY_METHOD
                    or saved.data != data or not {r.key() for r in input_refs} <= keys(saved.data.source_refs)
                    or not keys(saved.data.source_refs) <= keys(grant.readable_refs)):
                raise ValueError('Remedy result changes original full plan/inputs or independent read authority')
            for ref in saved.data.source_refs:
                source = reading.resolve(ref)
                if hasattr(source, 'available_at'):
                    clock(source.available_at)
                    if source.available_at.offset > saved.authored_at.offset:
                        raise ValueError('Remedy capacity execution predates its original readable source records')
            saved_evidence = [ref for ref in walk_references(saved.data) if ref.kind == 'Evidence']
            if not {ref.key() for ref in saved_evidence} <= keys(grant.readable_refs):
                raise ValueError('Remedy capacity author lacks original calculation evidence read authority')
            evidence(saved_evidence, at=saved.authored_at)
            result = reading.calculate(CAPACITY_METHOD, data)
            if result.kind != 'ok':
                if result.kind == 'invalid_input':
                    _unsupported('contractor-quality-remedy-capacity-method-domain')
                raw = result.model_dump(mode='python')
                if result.kind == 'needs_information':
                    raw['requested_refs'] = []
                raise ObservationGap(raw)
            if result.value != saved.report:
                raise ValueError('Remedy saved report differs from original exact capacity inputs')
            if not result.value.feasible:
                _needs('actual_shared_resource_capacity_for_remedy')
            return complete(choice, tasks=[t.model_dump(mode='python') for t in plan.tasks], defect_refs=action_input.defect_refs)
        if profile.method_ref is None:
            _unsupported('contractor-quality-no-inspection-method')
        method = read(profile.method_ref, ContractorInspectionMethodView, linked=True)
        if not true(method.supported):
            _unsupported('contractor-quality-inspection-method-unmodeled')
        if not requirements or keys(method.requirement_refs) != set(requirements):
            _needs('inspection_method_covers_original_requirements')
        for requirement in requirements.values():
            if method.ref.key() not in keys(requirement.allowed_method_refs):
                _unsupported('contractor-quality-method-requirement-domain')
        observation_method = read(method.observation_method_ref, ContractorInspectionObservationMethodView, linked=True)
        if (not true(observation_method.supported)
                or method.executor_action_id not in observation_method.allowed_author_action_ids):
            _unsupported('contractor-quality-observation-method-domain')
        if not scope_covers(method.scope, scope) or not scope_covers(observation_method.scope, scope):
            raise ValueError('Inspection or observation method does not cover the actual original inspection scope')
        authorize(method.executor_authority_ref, method.executor_actor_id, method.executor_function_ref,
            method.executor_organization_id, method.executor_action_id, now, scope)
        if choice == 'self_check' and (method.executor_organization_id != org or method.executor_action_id != 'CONTRACTOR-A08'):
            raise ValueError('Self-check substitutes external executor or another original function')
        if choice == 'request_external_check' and method.executor_organization_id == org:
            _needs('independent_original_external_inspection_executor')
        if method.requires_actual_evidence and not observed:
            _needs('actual_original_evidence_required_by_inspection_method')
        if choice == 'request_recheck':
            if any(r.external_verification_required for r in requirements.values()) and method.executor_organization_id == org:
                _needs('independent_original_recheck_executor_for_required_external_acceptance')
            if not defects or profile.prior_inspection_ref is None:
                _needs('original_inspection_and_open_defects_for_recheck')
            prior = read(profile.prior_inspection_ref, ContractorInspectionResultView, True, evidence_at_field='authored_at')
            prior_grant = author(prior)
            if not set(defects) <= keys(prior.defect_refs) or not keys(prior.work_record_refs) <= set(records):
                raise ValueError('Recheck substitutes original inspection/defect/work identities')
            if prior.status == 'failed':
                technical('contractor-quality-original-inspection-failed')
            if prior.status == 'unsupported':
                _unsupported('contractor-quality-original-inspection-unmodeled')
            prior_method = read(prior.method_ref, ContractorInspectionMethodView, historic=True, linked=True, source_at=prior.authored_at)
            prior_observation = read(prior_method.observation_method_ref, ContractorInspectionObservationMethodView,
                historic=True, linked=True, source_at=prior.authored_at)
            if (not true(prior_method.supported) or not true(prior_observation.supported)
                    or prior.author_action_id not in prior_observation.allowed_author_action_ids):
                _unsupported('contractor-quality-original-inspection-method-domain')
            if (prior_method.executor_organization_id != prior.author_organization_id
                    or prior_method.executor_actor_id != prior.author_actor_id
                    or prior_method.executor_function_ref != prior.author_function_ref
                    or prior_method.executor_authority_ref != prior.author_authority_ref
                    or prior_method.executor_action_id != prior.author_action_id
                    or not scope_covers(prior_method.scope, prior.scope)
                    or not scope_covers(prior_observation.scope, prior.scope)):
                raise ValueError('Recheck substitutes original inspection executor, method or supported scope')
            if not keys([prior.method_ref, prior_method.observation_method_ref,
                    *prior.work_record_refs, *prior.defect_refs]) <= keys(prior_grant.readable_refs):
                raise ValueError('Original inspection author lacks original method, work or defect read authority')
            for ref in (*prior.work_record_refs, *prior.defect_refs):
                source = reading.resolve(ref)
                clock(source.available_at)
                if source.available_at.offset > prior.authored_at.offset:
                    raise ValueError('Original inspection result predates its work or visible defects')
            if any(not scope_covers(prior.scope, defect.scope) for defect in defects.values()):
                raise ValueError('Recheck uses an original inspection outside actual defect coverage')
            for defect in defects.values():
                remedies = [r for r in observed.values() if r.kind == 'actual_remedy' and defect.ref.key() in keys(r.defect_refs)
                    and r.work_record_ref == defect.work_record_ref and scope_covers(r.scope, defect.scope)
                    and r.observed_at.offset > prior.authored_at.offset]
                if not remedies:
                    _needs('actual_original_remedy_evidence_before_recheck')
            return complete(choice, method_ref=method.ref, evidence_refs=action_input.evidence_refs,
                prior_inspection_ref=prior.ref, defect_refs=action_input.defect_refs)
        return complete(choice, method_ref=method.ref, evidence_refs=action_input.evidence_refs)
    except ObservationGap as gap:
        reading.recheck()
        return gap.result
