"""SUPPLIER-A07 uses visible facts and requests inspection or scoped disposition."""
from fractions import Fraction

from src.actions.contracts.common import EvidenceRecord, Known, TimeWindow
from src.actions.contracts.supplier_quality_objects import (
    SupplierQualityBatchView, SupplierQualityProfileView, SupplierQualityRequirementView,
    SupplierQualityMethodView, SupplierQualityObservationMethodView, SupplierQualityEvidenceView,
    SupplierVisibleDefectView, SupplierBatchDispositionRightView, SupplierBatchLineageLedgerView,
    SupplierBatchDispositionExecutionView, SupplierBatchRemedyPlanView,
    SupplierBatchReworkSliceView,
    SupplierBatchRemedyDependencyView, SupplierQualityProductRequirementView, SupplierQualityDeviationView,
    SupplierPlanningMethodView, SupplierPlanningResourceView, SupplierPlanningRequirementView,
    SupplierWorkAuthorityView,
    SupplierActualInventoryAllocationView, SupplierActualMaterialView,
)
from src.actions.contracts.owner_study_objects import unique_refs
from src.actions.roles.owner import ObservationGap, _needs, _known, _unsupported
from src.actions.roles.supplier_quality_history import validate_isolation_release_recheck
from src.methods.pricing import decimal_fraction
from src.organization.models import Authorization, RoleAssignment
from src.organization.registry import scope_covers


def request_batch_quality(context, action_input, reading):
    now, org, scope = context.business_time, reading.organization_id, context.scope

    def keys(refs):
        unique_refs(refs)
        return {r.key() for r in refs}

    def clock(point):
        if point.clock_ref != now.clock_ref:
            _unsupported('supplier-quality-clock-alignment')

    def evidence(refs, *, at=None, historic=False):
        point = now if at is None else at
        clock(point)
        if point.offset > now.offset:
            _needs('received_original_batch_quality_evidence_time')
        for ref in refs:
            row = reading.resolve(ref)
            if not isinstance(row, EvidenceRecord):
                _unsupported('supplier-quality-evidence-schema')
            if row.effective_window is not None:
                clock(row.effective_window.start)
                if row.effective_window.start.offset > now.offset:
                    _needs('received_original_batch_quality_evidence', [ref])
                if (at is not None or not historic) and not row.effective_window.contains(point):
                    _needs('original_batch_quality_evidence_valid_at_use', [ref])

    def read(ref, schema, historic=False, linked=False, *, evidence_at_field=None):
        row = reading.resolve(ref)
        if not isinstance(row, schema):
            _unsupported('supplier-quality-projection:' + ref.kind)
        if hasattr(row, 'scope') and not linked and not scope_covers(scope, row.scope):
            raise ValueError('Quality source expands original authorized batch scope')
        if hasattr(row, 'available_at'):
            clock(row.available_at)
            if row.available_at.offset > now.offset:
                _needs('received_original_batch_quality_source', [ref])
        if hasattr(row, 'effective_window'):
            clock(row.effective_window.start)
            if not historic and not row.effective_window.contains(now):
                _needs('current_original_batch_quality_source', [ref])
        point = None if evidence_at_field is None else getattr(row, evidence_at_field)
        if point is not None:
            clock(point)
            if point.offset > now.offset:
                _needs('received_original_batch_quality_evidence_time', [ref])
            if point.offset > row.available_at.offset:
                raise ValueError('Quality source receipt precedes original authorship')
        evidence(getattr(row, 'evidence_refs', []), at=point, historic=historic)
        return row

    def true(value):
        return isinstance(value, Known) and value.value is True

    def quantity(value, positive=False, *, at=None, historic=False):
        evidence([value.basis_ref], at=at, historic=historic)
        q = decimal_fraction(value.value)
        if value.unit != batch.actual_quantity.unit or q < 0 or positive and q == 0:
            raise ValueError('Batch quantities require positive original physical units')
        return q

    def authorize(ref, actor, function, organization, action, at, target):
        grant = read(ref, Authorization, historic=True, linked=True)
        assignment = read(function, RoleAssignment, historic=True, linked=True)
        roles = {'SUPPLIER':'Supplier', 'CONTRACTOR':'Contractor', 'OWN':'Owner', 'ENGINEER':'Engineer',
            'ARCHITECT':'Architect', 'QS':'QS', 'GOV':'Government'}
        if (grant.actor_id != actor or grant.organization_id != organization or grant.function_ref != function
                or assignment.function_ref != function
                or action not in grant.action_ids or assignment.role != roles.get(action.split('-')[0])
                or not any(scope_covers(s,target) for s in grant.scopes)):
            raise ValueError('Batch quality source substitutes actual independent author/role/scope authority')
        clock(at); clock(grant.validity.start)
        if at.offset > now.offset:
            _needs('received_original_batch_quality_author_time', [ref])
        if not grant.validity.contains(at):
            _needs('original_quality_authority_at_execution', [ref])
        for basis_ref in [*grant.basis_refs, *assignment.basis_refs]:
            if basis_ref.kind == 'Evidence':
                evidence([basis_ref], at=at)
            else:
                reading.resolve(basis_ref)

    def author(row):
        clock(row.authored_at)
        if row.authored_at.offset > row.available_at.offset or not row.effective_window.contains(row.authored_at):
            raise ValueError('Quality source precedes original actual author execution')
        authorize(row.author_authority_ref,row.author_actor_id,row.author_function_ref,
            row.author_organization_id,row.author_action_id,row.authored_at,row.scope)

    def complete(choice, **fields):
        reading.recheck()
        return {'kind':'completed', 'payload':{'choice':choice, **fields,
            'note':profile.note + ' Inspection/disposition/task/proposal request only. Self-report, independent verification and customer acceptance remain separate. Core changes original physical lineage once; no isolation release, usable stock, restored inputs or defect closure is created.'}}

    def wait(code, refs):
        reading.recheck()
        return {'kind':'deferred','reason_code':code,'resume_condition':{'trigger':'dependency_change',
            'object_refs':refs,'earliest_time':None,'condition_code':code}}

    def right(ref):
        row = read(ref,SupplierBatchDispositionRightView,evidence_at_field='authored_at');author(row)
        if (row.organization_id != org or row.owner_id != batch.owner_id or row.physical_batch_key != batch.physical_batch_key
                or row.batch_ref != batch.ref or not scope_covers(row.scope,batch.scope)
                or profile.choice not in row.permitted_choices or not true(row.permitted)):
            _needs('independent_original_actual_batch_disposition_right')
        if row.authority_kind == 'custody_isolation':
            if profile.choice != 'isolate' or row.author_organization_id != org:
                raise ValueError('Custodian isolation cannot authorize scrap or rework of another owner stock')
        elif row.authority_kind == 'own_title':
            if batch.owner_id != org or row.author_organization_id != org:
                raise ValueError('Supplier cannot substitute another owner title for disposition')
        elif row.author_organization_id != batch.owner_id:
            raise ValueError('Delegated batch disposition lacks original actual owner authorization')
        quantity(row.maximum_quantity,positive=True)
        return row

    try:
        if action_input.scope_ref != scope:
            raise ValueError('Batch quality changes original invocation scope')
        batch = read(action_input.batch_ref,SupplierQualityBatchView)
        profile = read(action_input.inspection_profile_ref,SupplierQualityProfileView)
        clock(batch.as_of)
        if (batch.organization_id != org or batch.as_of != now or profile.batch_ref != batch.ref
                or profile.organization_id != org or profile.actor_id != context.actor_id
                or profile.function_ref != context.function_ref or profile.scope != scope
                or profile.authority_ref not in context.authorization_refs):
            raise ValueError('Batch quality substitutes actual batch/organization/actor/authority or snapshot')
        authorize(profile.authority_ref,context.actor_id,context.function_ref,org,'SUPPLIER-A07',now,scope)
        quantity(batch.actual_quantity)
        for input_field, profile_field in [('requirement_refs','requirement_refs'),('evidence_refs','evidence_refs_received'),('known_defect_refs','known_defect_refs')]:
            if keys(getattr(action_input,input_field)) != keys(getattr(profile,profile_field)):
                _needs('complete_original_visible_batch_' + input_field)
        if keys(action_input.requirement_refs) != keys(batch.requirement_refs) or keys(action_input.known_defect_refs) != keys(batch.known_defect_refs):
            _needs('complete_original_batch_requirements_and_visible_defects')
        requirements = {}
        for ref in action_input.requirement_refs:
            row = read(ref,SupplierQualityRequirementView)
            if row.batch_ref != batch.ref or row.product_ref != batch.product_ref or not row.use_codes:
                raise ValueError('Inspection requirement replaces actual batch/product or supported use')
            requirements[ref.key()] = row
        observed = {}; events = set()
        def observation(ref):
            if ref.key() in observed:return observed[ref.key()]
            row = read(ref,SupplierQualityEvidenceView,historic=True,evidence_at_field='authored_at');author(row);clock(row.observed_at)
            if (row.batch_ref != batch.ref or row.physical_batch_key != batch.physical_batch_key
                    or row.observed_at.offset > row.authored_at.offset or row.event_id in events):
                raise ValueError('Inspection evidence repeats or substitutes actual original batch/event/time')
            quantity(row.sample_quantity,positive=True,at=row.observed_at);events.add(row.event_id)
            observed[ref.key()] = row
            return row
        for ref in action_input.evidence_refs:observation(ref)
        defects = {}
        for ref in action_input.known_defect_refs:
            row = read(ref,SupplierVisibleDefectView)
            original = observation(row.observation_ref)
            if (row.batch_ref != batch.ref or row.physical_batch_key != batch.physical_batch_key
                    or row.ref.key() not in keys(original.defect_refs) or original.kind not in {'actual_observation','actual_test'}
                    or not keys(row.requirement_refs) <= set(requirements)):
                raise ValueError('Visible defect lacks original actual observation and scoped requirements')
            defects[ref.key()] = row
        evidence(profile.basis_refs)

        if profile.choice in {'self_check','request_external_check'}:
            if profile.method_ref is None or not requirements:
                _needs('original_supported_batch_inspection_method_and_requirements')
            method = read(profile.method_ref,SupplierQualityMethodView)
            if not true(method.supported) or keys(method.requirement_refs) != set(requirements):
                _unsupported('original_batch_inspection_method_domain')
            for req in requirements.values():
                if method.ref.key() not in keys(req.allowed_method_refs):
                    _unsupported('original_batch_inspection_requirement_method')
            model = read(method.observation_method_ref,SupplierQualityObservationMethodView)
            if not true(model.supported) or method.executor_action_id not in model.allowed_author_action_ids:
                _unsupported('original_batch_observation_method_support')
            authorize(method.executor_authority_ref,method.executor_actor_id,method.executor_function_ref,
                method.executor_organization_id,method.executor_action_id,now,scope)
            if profile.choice == 'self_check' and (method.executor_organization_id != org or method.executor_action_id != 'SUPPLIER-A07'):
                raise ValueError('Supplier self-check substitutes an independent executor')
            if profile.choice == 'request_external_check' and method.executor_organization_id == org:
                raise ValueError('Supplier self-check cannot substitute requested external inspection')
            actual = [r for r in observed.values() if r.kind in {'actual_observation','actual_test','actual_remedy'}]
            if method.requires_actual_evidence and not actual:
                _needs('original_actual_batch_inspection_observations')
            allowed_uses = {code for req in requirements.values() for code in req.use_codes}
            if any(not set(row.use_codes) <= allowed_uses for row in actual):
                raise ValueError('Batch inspection evidence widens actual covered product uses')
            # Even when independent verification is required, self-check remains
            # a valid internal request and cannot confer external recognition.
            return complete(profile.choice,method_ref=method.ref,evidence_refs=action_input.evidence_refs)

        if profile.choice == 'propose_deviation':
            if not profile.deviation_refs:
                _needs('concrete_original_specification_deviation_proposal')
            keys(profile.deviation_refs)
            for ref in profile.deviation_refs:
                row = read(ref,SupplierQualityDeviationView,evidence_at_field='authored_at');author(row)
                if (row.batch_ref != batch.ref or row.physical_batch_key != batch.physical_batch_key
                        or row.product_ref != batch.product_ref or row.author_organization_id != org
                        or row.author_action_id != 'SUPPLIER-A07' or row.status not in {'proposal','pending'}
                        or not row.description.strip() or not row.inspection_requirement_refs
                        or not keys(row.inspection_requirement_refs) <= set(requirements)
                        or not keys(row.defect_refs) <= set(defects)):
                    raise ValueError('Deviation proposal substitutes actual batch, requirements, known defects or original author')
                uses = {code for req in row.inspection_requirement_refs for code in requirements[req.key()].use_codes}
                if not row.use_codes or not set(row.use_codes) <= uses:
                    raise ValueError('Deviation proposal widens original product use or hides affected requirements')
            return complete('propose_deviation',deviation_refs=profile.deviation_refs)

        if profile.choice not in {'isolate','scrap','rework'} or profile.disposition_right_ref is None:
            _needs('original_actual_batch_disposition_authority')
        permission = right(profile.disposition_right_ref)
        ledger = read(batch.lineage_ledger_ref,SupplierBatchLineageLedgerView,linked=True);clock(ledger.as_of)
        if (ledger.physical_batch_key != batch.physical_batch_key or ledger.organization_id != org
                or ledger.as_of != now or ledger.coverage != 'complete'):
            _needs('complete_current_original_physical_batch_lineage_ledger')
        initial = quantity(ledger.original_quantity);remaining = quantity(ledger.actual_remaining)
        scrapped = quantity(ledger.scrapped_quantity);outflow = quantity(ledger.other_outflow);isolated = quantity(ledger.isolated_quantity)
        if initial - scrapped - outflow != remaining or remaining != quantity(batch.actual_quantity) or isolated > remaining:
            raise ValueError('Batch aliases change original physical stock or restore scrapped/consumed inputs')
        original_scrap = Fraction(0);original_isolation = Fraction(0);commands = set();business = set();core_events = set();pending = []
        released_rechecks = {}
        keys(ledger.execution_refs)
        for ref in ledger.execution_refs:
            row = read(ref,SupplierBatchDispositionExecutionView,historic=True,linked=True)
            if (row.physical_batch_key != batch.physical_batch_key or row.organization_id != org
                    or row.operation_id in commands or row.business_key in business):
                raise ValueError('Disposition history repeats original command/business or substitutes physical batch')
            commands.add(row.operation_id);business.add(row.business_key)
            # The source has no actual disposition occurrence timestamp. Keep
            # original stock effects without using availability as event time.
            q = quantity(row.quantity,positive=True,historic=True)
            decrease = quantity(row.isolated_quantity_decrease,historic=True)
            if decrease > q or row.choice == 'isolate' and decrease != 0 or row.choice == 'release_isolation' and decrease != q:
                raise ValueError('Original disposition changes actual isolated quantity allocation')
            if row.status == 'recorded':
                if row.query_status != 'present' or row.core_event_id is None or row.core_event_id in core_events:
                    raise ValueError('Recorded batch disposition lacks original distinct core event')
                core_events.add(row.core_event_id)
                if row.choice == 'scrap':
                    original_scrap += q;original_isolation -= decrease
                elif row.choice == 'isolate':original_isolation += q
                else:
                    if row.release_basis_ref is None:
                        _needs('original_passed_recheck_before_isolation_release', [ref])
                    validate_isolation_release_recheck(row, batch, now=now, resolve=reading.resolve,
                        amount=lambda value: quantity(value,historic=True), released=released_rechecks)
                    original_isolation -= q
            elif row.core_event_id is not None or decrease != 0:
                raise ValueError('Unknown/rejected/failed disposition carries invented recorded physical effect')
            if row.status == 'submitted_unknown' or row.query_status in {'unknown','not_queried'}:pending.append(ref)
            if row.business_key == profile.business_key or row.operation_id == context.operation_id:
                if profile.choice != row.choice or profile.quantity is None or row.quantity != profile.quantity:
                    raise ValueError('Existing disposition business identity changes original choice or quantity')
                return wait('continue_original_batch_disposition',[ref])
        if pending:return wait('query_original_batch_disposition_before_new_effect',pending)
        if original_scrap != scrapped or original_isolation != isolated:
            raise ValueError('Current physical batch ledger differs from original recorded disposition history')

        if profile.choice in {'isolate','scrap'}:
            if profile.quantity is None or not profile.basis_refs:
                _needs('concrete_original_disposition_quantity_and_basis')
            q = quantity(profile.quantity,positive=True)
            available = remaining - isolated if profile.choice == 'isolate' else remaining
            if q > min(available,quantity(permission.maximum_quantity)):
                raise ValueError('Batch disposition exceeds actual unprocessed physical stock or owner-authorized scope')
            if not any(row.status != 'closed' for row in defects.values()) and not any(r.kind in {'actual_observation','actual_test'} for r in observed.values()):
                _needs('original_actual_basis_for_batch_quality_disposition')
            return complete(profile.choice,batch_ref=batch.ref,quantity=profile.quantity,basis_refs=profile.basis_refs)

        if profile.remedy_plan_ref is None:
            _needs('original_batch_rework_task_plan')
        plan = read(profile.remedy_plan_ref,SupplierBatchRemedyPlanView,evidence_at_field='authored_at');author(plan)
        if (plan.batch_ref != batch.ref or plan.physical_batch_key != batch.physical_batch_key
                or plan.disposition_right_ref != permission.ref or plan.author_organization_id != org
                or plan.author_action_id != 'SUPPLIER-A07' or not plan.tasks):
            raise ValueError('Rework plan substitutes original actual damaged batch, author or disposition right')
        task_keys = {t.local_key for t in plan.tasks}
        if (len(task_keys) != len(plan.tasks) or set(plan.task_defect_refs) != task_keys
                or set(plan.task_slice_refs) != task_keys):
            raise ValueError('Batch rework needs unique original task keys and exact defect bindings')
        graph = {};windows = {};input_refs = set();slices = {};slice_tasks = {}
        for task in plan.tasks:
            if (task.mode != 'rework' or not scope_covers(scope,task.scope_ref)
                    or not scope_covers(task.scope_ref,task.target.destination_scope_ref) or task.target.product_ref != batch.product_ref
                    or task.target.deviation_refs):
                raise ValueError('Batch rework draft substitutes original physical product/scope or applies an unapproved deviation')
            target = quantity(task.target.quantity,positive=True)
            bindings = plan.task_defect_refs[task.local_key]
            if not bindings or not keys(bindings) <= set(defects):
                raise ValueError('Batch rework task omits original visible defects')
            for ref in bindings:
                if defects[ref.key()].status == 'closed' or not scope_covers(task.scope_ref,defects[ref.key()].scope):
                    raise ValueError('Rework task targets closed or unrelated original defect')
            refs = plan.task_slice_refs[task.local_key];keys(refs);slice_total = Fraction(0)
            if not refs:raise ValueError('Rework task omits original physical slice coverage')
            for ref in refs:
                original = read(ref,SupplierBatchReworkSliceView)
                if (original.plan_ref != plan.ref or original.physical_batch_key != batch.physical_batch_key
                        or not keys(original.defect_refs) <= keys(bindings) or not original.defect_refs
                        or not scope_covers(task.scope_ref,original.scope)):
                    raise ValueError('Rework slice replaces original batch, task defects or concrete scope')
                physical = original.physical_slice_key
                if physical in slices and slices[physical].ref != original.ref:
                    raise ValueError('Rework slices alias the same original physical quantity')
                slices[physical] = original;slice_tasks.setdefault(physical,set()).add(task.local_key)
                slice_total += quantity(original.quantity,positive=True)
            if slice_total != target:
                raise ValueError('Rework task target differs from exact original physical slices')
            if not task.target.requirement_refs:
                _needs('original_rework_product_requirements')
            for ref in task.target.requirement_refs:
                req = read(ref,SupplierQualityProductRequirementView)
                if req.batch_ref != batch.ref or req.product_ref != batch.product_ref:
                    raise ValueError('Rework target substitutes original batch specification requirements')
            method = read(task.method_ref,SupplierPlanningMethodView)
            if method.mode != 'rework' or method.product_ref != batch.product_ref or not true(method.supported):
                _unsupported('original_supplier_rework_method_support')
            if method.quantity_unit != task.target.quantity.unit:
                raise ValueError('Rework draft changes original method output units')
            if not scope_covers(method.scope,task.scope_ref):
                raise ValueError('Rework method leaves original supported task scope')
            keys([i.product_ref for i in task.planned_inputs]);keys([i.product_ref for i in method.material_inputs])
            recipe = {i.product_ref.key():i for i in method.material_inputs}
            if keys([i.product_ref for i in task.planned_inputs]) != set(recipe):
                raise ValueError('Rework task drops original supported material recipe')
            for planned in task.planned_inputs:
                ingredient = recipe[planned.product_ref.key()];evidence([ingredient.basis_ref,planned.required.basis_ref])
                ratio = decimal_fraction(ingredient.quantity_per_output)
                if (ratio <= 0 or planned.required.unit != ingredient.unit
                        or decimal_fraction(planned.required.value) != ratio * decimal_fraction(task.target.quantity.value)):
                    raise ValueError('Rework material demand substitutes original conversion recipe')
                keys(planned.available_allocation_refs);keys(planned.acquisition_requirement_refs)
                for ref in planned.available_allocation_refs:
                    physical = (ref.kind,ref.id)
                    if physical in input_refs:raise ValueError('Rework draft repeats original planned stock allocation')
                    allocation = read(ref,SupplierActualInventoryAllocationView,linked=True)
                    material = read(allocation.batch_ref,SupplierActualMaterialView,linked=True)
                    if (allocation.organization_id != org or allocation.status != 'reserved' or material.organization_id != org
                            or material.product_ref != planned.product_ref or not true(material.actual_received)):
                        _needs('original_actual_available_material_for_rework_draft',[ref])
                    input_refs.add(physical)
                for ref in planned.acquisition_requirement_refs:
                    demand = read(ref,SupplierPlanningRequirementView)
                    mandate = read(demand.work_authority_ref,SupplierWorkAuthorityView,linked=True)
                    if demand.purpose != 'material' or demand.target.product_ref != planned.product_ref or not true(demand.permitted):
                        raise ValueError('Rework acquisition substitutes original authorized material requirement')
                    if mandate.organization_id != org or not true(mandate.permitted) or ref.key() not in keys(mandate.requirement_refs):
                        raise ValueError('Rework material procurement substitutes another enterprise work mandate')
            windows[task.local_key] = [];graph[task.local_key] = set();keys(task.dependency_refs)
            keys([r.resource_ref for r in task.resources])
            for requested in task.resources:
                resource = read(requested.resource_ref,SupplierPlanningResourceView,linked=True)
                if (resource.organization_id != org or resource.resource_kind != method.resource_kind
                        or requested.scope_ref != task.scope_ref or requested.quantity.unit != method.capacity_unit
                        or decimal_fraction(requested.quantity.value) <= 0):
                    raise ValueError('Rework resource draft substitutes original own resource/method/scope')
                evidence([requested.quantity.basis_ref]);window = read(requested.window_ref,TimeWindow)
                clock(window.start);clock(window.end)
                if window.start.offset < now.offset:raise ValueError('New rework draft precedes original request')
                windows[task.local_key].append(window)
        if sum((quantity(row.quantity) for row in slices.values()),Fraction(0)) > min(remaining,quantity(permission.maximum_quantity)):
            raise ValueError('Split rework drafts duplicate physical batch quantity or exceed original owner authority')
        for task in plan.tasks:
            for ref in task.dependency_refs:
                row = read(ref,SupplierBatchRemedyDependencyView)
                if row.plan_ref != plan.ref or row.dependent_task_key != task.local_key:
                    raise ValueError('Rework task replaces original dependency plan')
                for predecessor in row.predecessor_task_keys:
                    if predecessor not in task_keys or predecessor == task.local_key:raise ValueError('Rework predecessor is missing or self-referential')
                    graph[task.local_key].add(predecessor)
                    before,after = windows[predecessor],windows[task.local_key]
                    if before and after and max(w.end.offset for w in before) > min(w.start.offset for w in after):
                        _needs('original_rework_predecessor_window_completion')
        active = set();visited = set()
        def visit(key):
            if key in active:raise ValueError('Rework draft dependency cycle')
            if key not in visited:
                active.add(key)
                for predecessor in graph[key]:visit(predecessor)
                active.remove(key);visited.add(key)
        for key in task_keys:visit(key)
        def precedes(before,after):
            return before in graph[after] or any(precedes(before,p) for p in graph[after])
        for tasks in slice_tasks.values():
            ordered = list(tasks)
            for i,before in enumerate(ordered):
                for after in ordered[i+1:]:
                    if not precedes(before,after) and not precedes(after,before):
                        raise ValueError('Parallel rework tasks duplicate the same original physical slice')
        return complete('rework',tasks=[task.model_dump(mode='python') for task in plan.tasks])
    except ObservationGap as gap:
        reading.recheck()
        return gap.result
