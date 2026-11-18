"""ENGINEER-A08 consumes visible observations; plans and replies do not create them."""
from fractions import Fraction

from src.actions.contracts.common import EvidenceRecord, Known, walk_references
from src.actions.contracts.engineer_inspection_objects import (
    EngineerInspectionTaskView, EngineerInspectionDesignView, EngineerInspectionMethodView,
    EngineerInspectionAccessView, EngineerInspectionScopeView, EngineerInspectionSpecView,
    EngineerInspectionObservationView, EngineerInspectionResultView, EngineerInspectionIssueView,
    EngineerInspectionQuestionView, EngineerInspectionDependencyView, EngineerAppointmentView,
    EngineerServiceTermsView, EngineerPlanningCalendarView, EngineerPlanningQualificationView,
    EngineerPlanningEstimateView, EngineerPlanningWorkFactView, EngineerPlanningAllocationView,
    EngineerInspectionCheckPreparation,
)
from src.actions.contracts.architect_appointment_objects import service_terms_digest
from src.actions.contracts.owner_study_objects import unique_refs
from src.actions.contracts.service_objects import ServiceWorkProfileView, ServiceResponseRequirementView
from src.actions.roles.owner import ObservationGap, _known, _needs, _unsupported
from src.methods.capacity import CAPACITY_METHOD, CapacityInput, CapacityReport, ExactAmount, compare_capacity
from src.methods.engineer_checks import ENGINEER_INTERFACE_METHOD, EngineerInterfaceInput, check_interface
from src.methods.pricing import decimal_fraction
from src.organization.models import Authorization, RoleAssignment
from src.organization.registry import scope_covers


def inspect_and_support(context, action_input, reading):
    return _inspect_and_support(context, action_input, reading)


def recheck_original_engineer_inspection_observation_wait(context, action_input, reading):
    """Reproduce the original missing-observation gate before report evaluation."""
    before = reading.method_evidence()
    try:
        result = _inspect_and_support(context, action_input, reading, original_observation_wait_only=True)
    finally:
        reading.recheck()
        if reading.method_evidence() != before:
            raise ValueError('Historical observation recovery cannot execute a method')
    if (not isinstance(result, dict) or result.get('kind') != 'deferred'
            or result.get('reason_code') != 'original_visible_inspection_observations_not_received'):
        raise ValueError('Original inspection sources do not reproduce the missing-observation wait')
    return result


def recheck_original_engineer_inspection_investment(context, action_input, reading):
    """Reproduce actual fully invested work before resource allocation or capacity methods."""
    before = reading.method_evidence()
    try:
        result = _inspect_and_support(context, action_input, reading, original_work_wait_only=True)
    finally:
        reading.recheck()
        if reading.method_evidence() != before:
            raise ValueError('Historical invested-work checks cannot execute a method')
    if (not isinstance(result, dict) or result.get('kind') != 'deferred'
            or result.get('reason_code') != 'original_inspection_work_already_invested'):
        raise ValueError('Original inspection sources do not reproduce actual fully invested work')
    return result


def recheck_original_engineer_inspection_personnel(context, action_input, reading):
    """Reproduce original personnel suitability before any capacity execution."""
    before = reading.method_evidence()
    try:
        result = _inspect_and_support(context, action_input, reading, original_personnel_wait_only=True)
    finally:
        reading.recheck()
        if reading.method_evidence() != before:
            raise ValueError('Historical personnel recovery cannot execute a method')
    if (not isinstance(result, dict) or result.get('kind') != 'deferred'
            or result.get('reason_code') != 'original_inspection_personnel_unsuitable'):
        raise ValueError('Original inspection sources do not reproduce the actual personnel suitability wait')
    return result


def recheck_original_engineer_inspection_qualification(context, action_input, reading):
    """Reproduce original personnel qualification failure before capacity execution."""
    before = reading.method_evidence()
    try:
        result = _inspect_and_support(context, action_input, reading, original_personnel_wait_only=True)
    finally:
        reading.recheck()
        if reading.method_evidence() != before:
            raise ValueError('Historical qualification recovery cannot execute a method')
    if (not isinstance(result, dict) or result.get('kind') != 'deferred'
            or result.get('reason_code') != 'original_inspection_personnel_qualification_unavailable'):
        raise ValueError('Original inspection sources do not reproduce the actual qualification wait')
    return result


def recheck_original_engineer_inspection_equipment(context, action_input, reading):
    """Reproduce original equipment eligibility failure before capacity execution."""
    before = reading.method_evidence()
    try:
        result = _inspect_and_support(context, action_input, reading, original_personnel_wait_only=True)
    finally:
        reading.recheck()
        if reading.method_evidence() != before:
            raise ValueError('Historical equipment recovery cannot execute a method')
    if (not isinstance(result, dict) or result.get('kind') != 'deferred'
            or result.get('reason_code') != 'original_inspection_equipment_unavailable'):
        raise ValueError('Original inspection sources do not reproduce the actual equipment wait')
    return result


def recheck_original_engineer_inspection_capacity(context, action_input, reading):
    """Reproduce original shared capacity with declared pure arithmetic and no old method invocation."""
    reading.check_method_context(reading._context, 'ENGINEER-A08')
    binding = reading._methods._bindings.get(CAPACITY_METHOD.key()) if reading._methods is not None else None
    if (CAPACITY_METHOD.key() not in reading._method_refs or binding is None
            or binding.executor is not compare_capacity or binding.input_model is not CapacityInput
            or binding.output_model is not CapacityReport or 'ENGINEER-A08' not in binding.definition.action_ids
            or binding.definition.effect_kind != 'pure_calculation'):
        raise ValueError('Original inspection capacity wait requires its declared pure capacity method')
    comparisons = []
    before = reading.method_evidence()
    try:
        result = _inspect_and_support(context, action_input, reading, historical_capacity=comparisons)
    finally:
        reading.recheck()
        if reading.method_evidence() != before:
            raise ValueError('Historical inspection capacity checks cannot execute a method')
    if (not isinstance(result, dict) or result.get('kind') != 'deferred'
            or result.get('reason_code') != 'shared_inspection_capacity_unavailable'):
        raise ValueError('Original inspection sources do not reproduce the actual shared capacity wait')
    return result, comparisons


def recheck_original_engineer_inspection_design_change(context, action_input, reading):
    """Reproduce the separate-design-change boundary without executing a revision."""
    task = reading.resolve(action_input.inspection_task_ref)
    if not isinstance(task, EngineerInspectionTaskView) or task.choice != 'respond':
        raise ValueError('Original separate design change wait requires its original response task')
    before = reading.method_evidence()
    try:
        result = _inspect_and_support(context, action_input, reading)
    finally:
        reading.recheck()
        if reading.method_evidence() != before:
            raise ValueError('Historical design change boundary cannot execute a method')
    if (not isinstance(result, dict) or result.get('kind') != 'deferred'
            or result.get('reason_code') != 'separate_original_professional_design_change_required'):
        raise ValueError('Original inspection sources do not reproduce the separate design change wait')
    return result


def prepare_engineer_inspection_check_input(context, action_input, reading, preparation):
    """Reuse actual observation/access/work gates without consuming the target."""
    preparation = EngineerInspectionCheckPreparation.model_validate(preparation).model_copy(deep=True)
    if context.contract_ref.kind != 'ActionContract' or context.contract_ref.id != 'ENGINEER-A08':
        raise ValueError('Inspection check preparation requires original Engineer A08 contract')
    reading.check_method_context(context, 'ENGINEER-A08')
    before = reading.method_evidence()

    def recheck_preparation():
        if reading.method_evidence() != before or preparation.calculation_ref.key() in reading._reads:
            raise ValueError('Inspection preparation cannot execute methods or consume its future result')

    recheck_preparation()
    try:
        return _inspect_and_support(context, action_input, reading, check_preparation=preparation)
    finally:
        reading.recheck()
        recheck_preparation()


def _inspect_and_support(context, action_input, reading, *, check_preparation=None, original_observation_wait_only=False,
        original_work_wait_only=False, original_personnel_wait_only=False, historical_capacity=None):
    now, organization = context.business_time, reading.organization_id

    def same(left,right): return left.key()==right.key()

    def keys(refs):
        unique_refs(refs);return {ref.key() for ref in refs}

    def clock(point):
        if point.clock_ref != now.clock_ref: _unsupported('engineer-inspection-clock-alignment')

    def evidence(refs,historical=False):
        records=[]
        for ref in refs:
            row=reading.resolve(ref)
            if not isinstance(row,EvidenceRecord): _unsupported('engineer-inspection-evidence-schema')
            if row.effective_window is not None:
                clock(row.effective_window.start)
                if not historical and not row.effective_window.contains(now): _needs('current_original_inspection_evidence',[ref])
            records.append(row)
        return records

    def read(ref,schema,historical=False):
        row=reading.resolve(ref)
        if not isinstance(row,schema): _unsupported('engineer-inspection-projection:'+ref.kind)
        if hasattr(row,'scope') and not scope_covers(action_input.scope,row.scope): raise ValueError('Inspection widens original task scope')
        if hasattr(row,'available_at'):
            clock(row.available_at)
            if row.available_at.offset > now.offset: _needs('received_original_inspection_record',[ref])
        if hasattr(row,'effective_window'):
            clock(row.effective_window.start)
            if not historical and not row.effective_window.contains(now): _needs('effective_original_inspection_record',[ref])
        evidence(getattr(row,'evidence_refs',[]),historical);return row

    def authorize(ref,actor,function_ref,org,action,at):
        grant=read(ref,Authorization);function=read(function_ref,RoleAssignment)
        roles={'ENGINEER':'Engineer','ARCHITECT':'Architect','QS':'QS','CONTRACTOR':'Contractor','SUPPLIER':'Supplier',
               'GOV':'Government','OWN':'Owner','BANK':'Bank'}
        if (grant.actor_id != actor or not same(grant.function_ref,function_ref) or grant.organization_id != org
                or action not in grant.action_ids or function.role != roles.get(action.split('-')[0])
                or not any(scope_covers(s,action_input.scope) for s in grant.scopes)):
            raise ValueError('Inspection lacks original independent author/function/action authority')
        clock(grant.validity.start);clock(at)
        if not grant.validity.contains(at): _needs('valid_original_inspection_authority',[ref])
        evidence([*grant.basis_refs,*function.basis_refs],at!=now)
        return grant

    def bound(row):
        if (not same(row.task_ref,task.ref) or not same(row.applicable_design_ref,design.ref)
                or row.design_content_sha256 != design.content_sha256): raise ValueError('Inspection changes original task/design version/content')

    def completed(choice,**fields):
        reading.recheck();return {'kind':'completed','payload':{'choice':choice,'scope':action_input.scope,'note':task.note,**fields}}

    def deferred(code,refs):
        reading.recheck();return {'kind':'deferred','reason_code':code,'resume_condition':{
            'trigger':'dependency_change','object_refs':refs,'earliest_time':None,'condition_code':code}}

    def method_domain(row):
        if (task.discipline_code not in row.discipline_codes or task.function_code not in row.function_codes
                or region not in row.region_ids or object_type not in row.object_types or task.requested_use not in row.allowed_uses):
            _unsupported('engineer-inspection-professional-method-domain')
        if not _known(row.supported,'original_inspection_method_support'): _unsupported('engineer-inspection-method-unavailable')

    def work_facts(refs,task_ref,executor_org):
        amount=Fraction();investments=set();rows=[];unit=None
        for ref in refs:
            fact=read(ref,EngineerPlanningWorkFactView,True);clock(fact.window.start)
            if not same(fact.task_ref,task_ref) or fact.organization_id!=executor_org or fact.investment_key in investments:
                raise ValueError('Inspection duplicates investment or borrows another task/executor')
            if fact.status!='committed' or fact.window.end.offset > min(now.offset,fact.available_at.offset):
                _needs('actual_confirmed_inspection_investment')
            value=decimal_fraction(fact.effort.value)
            if unit is not None and fact.effort.unit!=unit: _unsupported('engineer-inspection-investment-unit-conversion')
            unit=fact.effort.unit
            if value<0 or decimal_fraction(fact.internal_cost.value)<0: raise ValueError('Inspection investment/cost cannot be negative')
            evidence([fact.effort.basis_ref,fact.internal_cost.basis_ref],True)
            amount+=value;investments.add(fact.investment_key);rows.append(fact)
        return amount,rows

    def make_questions():
        output=[]
        keys(task.question_refs)
        for ref in task.question_refs:
            row=read(ref,EngineerInspectionQuestionView);bound(row);question=row.question
            if question.scope!=action_input.scope or not question.recipient_ids or ref.key() not in keys(question.target_refs):
                raise ValueError('Inspection test question changes original scope/target/recipient')
            response=read(question.response_requirement_ref,ServiceResponseRequirementView)
            if not same(response.request_ref,appointment.request_ref) or not set(question.recipient_ids)<=set(response.recipient_ids):
                raise ValueError('Inspection test question exceeds original response request/recipients')
            for target_ref in question.target_refs:
                target=read(target_ref,EngineerInspectionQuestionView);bound(target)
                if target.question!=question: raise ValueError('Inspection test request changes original question content')
            evidence(question.evidence_refs);output.append(question.model_dump(mode='python'))
        if not output: _needs('specific_original_inspection_test_questions')
        return output

    def plan_inspection():
        if task.work_profile_ref is None or task.estimate_ref is None or task.resource_calendar_ref is None:
            _needs('original_inspection_work_profile_estimate_and_calendar')
        profile=read(task.work_profile_ref,ServiceWorkProfileView)
        estimate=read(task.estimate_ref,EngineerPlanningEstimateView,True)
        calendar=read(task.resource_calendar_ref,EngineerPlanningCalendarView)
        if (profile.method!='constant_capacity_over_half_open_window_v1' or profile.clock_ref!=now.clock_ref
                or region not in profile.region_ids or object_type not in profile.object_types
                or _known(terms.service_code,'accepted_inspection_service') not in profile.service_codes):
            _unsupported('engineer-inspection-work-method-domain')
        if not same(estimate.task_ref,task.ref) or not same(estimate.work_profile_ref,profile.ref):
            raise ValueError('Inspection estimate borrows another task/profile')
        clock(estimate.executed_at)
        if estimate.status!='succeeded' or estimate.executed_at.offset>min(now.offset,estimate.available_at.offset): _needs('original_successful_inspection_work_estimate')
        if estimate.effort.unit!=profile.effort_unit: _unsupported('engineer-inspection-effort-unit-conversion')
        evidence([estimate.effort.basis_ref]);total=decimal_fraction(estimate.effort.value)
        if total<=0: raise ValueError('Inspection work estimate must be positive')
        if task.work_fact_coverage!='complete': _needs('complete_original_inspection_work_history')
        spent,facts=work_facts(task.work_fact_refs,task.ref,organization)
        if any(fact.effort.unit!=profile.effort_unit for fact in facts): _unsupported('engineer-inspection-investment-unit-conversion')
        if spent>total: raise ValueError('Inspection rework needs separate authorized effort increment')
        if spent==total:return deferred('original_inspection_work_already_invested',[task.ref])
        if original_work_wait_only:
            reading.recheck()
            return None
        if calendar.organization_id!=organization or calendar.coverage!='complete' or calendar.as_of!=now:
            _needs('complete_current_shared_inspection_resource_calendar')
        window=task.planned_window;clock(window.start)
        accepted_window=_known(terms.desired_window,'accepted_inspection_work_window');clock(accepted_window.start)
        if (window.bounds!='closed_open' or window.start.offset<now.offset or window.start.offset>=window.end.offset
                or not accepted_window.start.offset<=window.start.offset<window.end.offset<=accepted_window.end.offset
                or not profile.effective_window.start.offset<=window.start.offset<window.end.offset<=profile.effective_window.end.offset):
            _needs('original_current_inspection_plan_window')
        dependency_refs=list(task.dependency_refs);keys(dependency_refs)
        for ref in dependency_refs:
            dependency=read(ref,EngineerInspectionDependencyView)
            if not same(dependency.task_ref,task.ref):raise ValueError('Inspection plan borrows dependency')
            # Pending dependencies remain in the plan, never actual completion.
        if method.requires_site_access:
            access_known=False
            if action_input.access_ref is not None:
                access=read(action_input.access_ref,EngineerInspectionAccessView,True)
                access_known=(same(access.task_ref,task.ref) and organization in access.executor_organization_ids
                    and isinstance(access.allowed,Known) and access.allowed.value
                    and keys(task.engineering_scope_refs)<=keys(access.engineering_scope_refs)
                    and access.effective_window.start.offset<=window.start.offset and window.end.offset<=access.effective_window.end.offset)
            if not access_known:
                if task.access_dependency_ref is None: _needs('original_pending_site_access_dependency_for_arrangement')
                dep=read(task.access_dependency_ref,EngineerInspectionDependencyView)
                if not same(dep.task_ref,task.ref) or dep.purpose!='site_access':raise ValueError('Inspection pending access changes original task/purpose')
                if dep.ref.key() not in keys(dependency_refs):dependency_refs.append(dep.ref)
        keys([row.resource_ref for row in task.resource_shares]);keys([row.resource_ref for row in task.tool_demands])
        if not task.resource_shares or any(decimal_fraction(row.share)<=0 for row in task.resource_shares) or sum(decimal_fraction(row.share) for row in task.resource_shares)!=1:
            raise ValueError('Inspection personnel shares must conserve positive remaining effort')
        resources={row.resource_ref.key():row for row in calendar.resources};people=set()
        for row in calendar.resources:
            identities=_known(row.personnel_ids,'actual_shared_inspection_personnel')
            if row.asset_role=='equipment':
                if identities:raise ValueError('Inspection equipment cannot contribute personnel')
            elif not identities or len(set(identities))!=len(identities) or people.intersection(identities):
                raise ValueError('Inspection shared calendar duplicates or omits actual personnel')
            people.update(identities)
        excluded=set()
        if task.existing_allocation_ref is not None:
            original=read(task.existing_allocation_ref,EngineerPlanningAllocationView)
            if (original.organization_id!=organization or not same(original.task_ref,task.ref)
                    or not same(original.appointment_ref,appointment.ref) or original.as_of!=now
                    or not keys(original.work_fact_refs)<=keys(task.work_fact_refs)):raise ValueError('Inspection allocation changes original task/history')
            if original.status=='active':
                calendar_rows={row.commitment_ref.key():row for row in calendar.commitments}
                for row in original.commitments:
                    if calendar_rows.get(row.commitment_ref.key())!=row:raise ValueError('Inspection allocation loses original calendar commitment')
                    excluded.add(row.commitment_ref.key())
        demands={};remaining=total-spent;resource_ids=[]
        for share in task.resource_shares:
            row=resources.get(share.resource_ref.key())
            if row is None:_needs('original_inspection_personnel_resource')
            if (row.asset_role!='personnel' or row.resource_kind!=profile.resource_kind
                    or task.discipline_code not in row.discipline_codes or task.function_code not in row.function_codes
                    or _known(row.region_id,'inspection_personnel_region')!=region or not _known(row.suitable,'inspection_personnel_suitable')):
                return deferred('original_inspection_personnel_unsuitable',[row.resource_ref])
            if not row.qualification_refs:_needs('original_inspection_personnel_qualification')
            for ref in row.qualification_refs:
                qualification=read(ref,EngineerPlanningQualificationView)
                if (qualification.organization_id!=organization or region not in qualification.region_ids
                        or _known(terms.service_code,'accepted_inspection_qualification_service') not in qualification.service_codes
                        or task.discipline_code not in qualification.discipline_codes or task.function_code not in qualification.function_codes
                        or not set(_known(row.personnel_ids,'actual_inspection_personnel'))<=set(qualification.personnel_ids)
                        or not _known(qualification.standing,'current_inspection_qualification_standing')):
                    return deferred('original_inspection_personnel_qualification_unavailable',[qualification.ref])
            rate=remaining*decimal_fraction(share.share)/decimal_fraction(profile.effort_per_capacity_tick)/(window.end.offset-window.start.offset)
            demands[row.resource_ref.key()]=ExactAmount.from_fraction(rate);resource_ids.append(row.resource_ref.id)
        for tool in task.tool_demands:
            row=resources.get(tool.resource_ref.key())
            if row is None:_needs('original_inspection_equipment_resource')
            if (row.asset_role!='equipment' or _known(row.region_id,'inspection_equipment_region')!=region
                    or not _known(row.suitable,'inspection_equipment_suitable') or task.discipline_code not in row.discipline_codes
                    or task.function_code not in row.function_codes):return deferred('original_inspection_equipment_unavailable',[row.resource_ref])
            if tool.capacity.unit!=profile.capacity_unit:_unsupported('engineer-inspection-equipment-unit-conversion')
            evidence([tool.capacity.basis_ref])
            if decimal_fraction(tool.capacity.value)<=0:raise ValueError('Inspection equipment demand must be positive')
            if row.resource_ref.key() in demands:raise ValueError('Inspection duplicates personnel/equipment demand')
            demands[row.resource_ref.key()]=ExactAmount.from_fraction(decimal_fraction(tool.capacity.value));resource_ids.append(row.resource_ref.id)
        if original_personnel_wait_only:
            reading.recheck()
            return None
        for key,quantity in demands.items():
            resource=resources[key];capacity=_known(resource.total,'inspection_resource_capacity');evidence([capacity.basis_ref])
            if capacity.unit!=profile.capacity_unit:_unsupported('engineer-inspection-capacity-unit-conversion')
            data=CapacityInput(clock_ref=now.clock_ref,
                demands=[{'resource_kind':resource.resource_kind,'region_id':region,'unit':profile.capacity_unit,
                    'amount':quantity,'window':window,'basis_refs':[estimate.effort.basis_ref]}],
                resources=[{'resource_ref':resource.resource_ref,'resource_kind':resource.resource_kind,'region_id':region,
                    'total':capacity,'effective_window':resource.effective_window}],
                commitments=[row.model_dump(mode='python') for row in calendar.commitments if row.resource_ref.key()==key and row.commitment_ref.key() not in excluded],
                source_refs=[task.ref,profile.ref,estimate.ref,calendar.ref])
            if historical_capacity is not None:
                basis={ref.key():ref for ref in walk_references(data) if ref.kind=='Evidence'}
                if not data.source_refs or not basis:_needs('original_inspection_capacity_input_provenance')
                for ref in data.source_refs:
                    reading.resolve(ref)
                evidence(basis.values())
                reading.recheck()
                report=compare_capacity(data)
                historical_capacity.append(dict(method_ref=CAPACITY_METHOD.model_dump(mode='json'),
                    input=data.model_dump(mode='json'), comparison=report.model_dump(mode='json')))
            else:
                result=reading.calculate(CAPACITY_METHOD,data)
                if result.kind!='ok':
                    if result.kind=='invalid_input':_unsupported('engineer-inspection-capacity-domain')
                    raw=result.model_dump(mode='python')
                    if result.kind=='needs_information':raw['requested_refs']=[]
                    raise ObservationGap(raw)
                report=result.value
            if not report.feasible:return deferred('shared_inspection_capacity_unavailable',[calendar.ref])
        if historical_capacity is not None:
            reading.recheck()
            return None
        from src.methods.pricing import exact_decimal
        effort={'value':exact_decimal(remaining),'unit':profile.effort_unit,'basis_ref':estimate.effort.basis_ref}
        return completed('plan_inspection',plan={'work_profile_ref':profile.ref,'items':[{'task_ref':task.ref,
            'resource_ids':resource_ids,'window':window,'effort':effort,'dependency_refs':dependency_refs,
            'existing_allocation_ref':task.existing_allocation_ref}]})

    try:
        if action_input.scope!=context.scope:raise ValueError('Inspection changes original action scope')
        task=read(action_input.inspection_task_ref,EngineerInspectionTaskView)
        design=read(action_input.applicable_design_ref,EngineerInspectionDesignView)
        if not same(task.applicable_design_ref,design.ref) or task.design_content_sha256!=design.content_sha256:
            raise ValueError('Inspection task changes original applicable design version/content')
        if task.organization_id!=organization:raise ValueError('Inspection borrows another organization task')
        authorize(task.authority_ref,context.actor_id,context.function_ref,organization,'ENGINEER-A08',now)
        if task.status!='authorized':return deferred('original_inspection_task_waiting_or_closed',[task.ref])
        appointment=read(task.appointment_ref,EngineerAppointmentView)
        if appointment.provider_organization_id!=organization or appointment.status!='active':_needs('original_active_inspection_appointment')
        terms=read(appointment.terms_ref,EngineerServiceTermsView,True)
        if service_terms_digest(terms)!=appointment.terms_digest:raise ValueError('Inspection changes accepted terms content')
        if (task.discipline_code not in _known(terms.discipline_codes,'accepted_inspection_disciplines')
                or task.function_code!=_known(terms.function_code,'accepted_inspection_function')
                or task.requested_use not in _known(terms.requested_uses,'accepted_inspection_uses')
                or task.discipline_code not in design.discipline_codes):raise ValueError('Inspection changes accepted professional scope/use')
        if (design.status!='compiled' or task.requested_use not in design.valid_for_uses or task.requested_use in design.invalidated_uses):
            _needs('original_design_applicable_for_inspection_use',[design.ref])
        clock(design.authored_at)
        if design.authored_at.offset>min(now.offset,design.available_at.offset):_needs('inspection_design_authored_before_received')
        authorize(design.author_authority_ref,design.author_actor_id,design.author_function_ref,design.author_organization_id,design.author_action_id,design.authored_at)
        if not same(action_input.observation_method_ref,task.observation_method_ref):raise ValueError('Inspection changes original observation method')
        method=read(action_input.observation_method_ref,EngineerInspectionMethodView)
        region=_known(terms.region_id,'accepted_inspection_region');object_type=_known(terms.object_type,'accepted_inspection_object_type')
        if keys(action_input.observation_refs)!=keys(task.received_observation_refs) or keys(action_input.query_refs)!=keys(task.received_query_refs):
            _needs('all_original_visible_inspection_observations_and_queries')
        scopes={ref.key():read(ref,EngineerInspectionScopeView) for ref in task.engineering_scope_refs};keys(task.engineering_scope_refs)
        physical=set()
        for row in scopes.values():
            bound(row)
            if row.discipline_code!=task.discipline_code or not row.physical_keys or len(set(row.physical_keys))!=len(row.physical_keys) or physical.intersection(row.physical_keys):
                raise ValueError('Inspection scope duplicates physical coverage or changes discipline')
            physical.update(row.physical_keys)
        queries={ref.key():read(ref,EngineerInspectionIssueView) for ref in action_input.query_refs}
        for row in queries.values():
            bound(row)
            if row.engineering_scope_ref.key() not in scopes:raise ValueError('Inspection query leaves original scope')
        if original_observation_wait_only and task.choice != 'report':
            reading.recheck()
            return None
        if original_work_wait_only and task.choice != 'plan_inspection':
            reading.recheck()
            return None
        if original_personnel_wait_only and task.choice != 'plan_inspection':
            reading.recheck()
            return None
        if historical_capacity is not None and task.choice != 'plan_inspection':
            reading.recheck()
            return None
        if check_preparation is not None and task.choice != 'report':
            raise ValueError('Inspection check preparation requires original report branch')
        if task.choice=='respond':
            if task.response_issue_ref is None or task.response_issue_ref.key() not in queries:_needs('actual_received_inspection_technical_query')
            query=queries[task.response_issue_ref.key()]
            response=read(query.response_requirement_ref,ServiceResponseRequirementView)
            if (query.status!='received' or context.actor_id not in query.authorized_responder_actor_ids
                    or not same(response.request_ref,appointment.request_ref) or query.sender_id not in response.recipient_ids):
                _needs('original_authorized_remote_technical_response')
            if query.response_changes_design:return deferred('separate_original_professional_design_change_required',[query.ref,design.ref])
            if query.response is None or not query.response_basis_refs:_needs('original_remote_technical_response_and_evidence')
            evidence(query.response_basis_refs)
            return completed('respond',question_ref=query.ref,response=query.response,basis_refs=query.response_basis_refs)
        if task.choice=='request_test':
            if task.test_method_ref is None:_needs('original_requested_test_method')
            test_method=read(task.test_method_ref,EngineerInspectionMethodView);method_domain(test_method)
            if test_method.purpose!='test':raise ValueError('Inspection test request changes original method purpose')
            return completed('request_test',questions=make_questions(),method_ref=test_method.ref)
        method_domain(method)
        if task.choice=='plan_inspection':return plan_inspection()
        observations={ref.key():read(ref,EngineerInspectionObservationView,True) for ref in action_input.observation_refs}
        specs=[read(ref,EngineerInspectionSpecView) for ref in task.check_spec_refs];keys(task.check_spec_refs)
        if not observations:return deferred('original_visible_inspection_observations_not_received',[task.ref])
        if original_observation_wait_only:
            reading.recheck()
            return None
        prepared_check = None
        if check_preparation is not None:
            targets = [row.check_result_ref for row in observations.values() if row.check_result_ref is not None]
            keys(targets)
            if (check_preparation.check_spec_ref not in task.check_spec_refs
                    or check_preparation.observation_ref not in action_input.observation_refs
                    or check_preparation.calculation_ref not in targets
                    or type(check_preparation.calculation_ref.version) is not str):
                raise ValueError('Inspection preparation leaves original observation/spec/result target')
        checked_observations=set();items=[];uncovered=set(scopes);observed_coverage={key:set() for key in scopes}
        for spec in specs:
            bound(spec)
            if spec.engineering_scope_ref.key() not in scopes:raise ValueError('Inspection check invents engineering scope')
            item_issues={ref.key():ref for ref in spec.issue_refs};keys(spec.issue_refs)
            for issue in queries.values():
                if issue.status in {'open','unknown'} and same(issue.engineering_scope_ref,spec.engineering_scope_ref):item_issues[issue.ref.key()]=issue.ref
            observation=observations.get(spec.observation_ref.key()) if spec.observation_ref is not None else None
            value,missing,basis,saved,evidence_status=None,['observation'],[],None,'missing'
            if observation is not None:
                bound(observation);clock(observation.observed_window.start)
                if (not same(observation.method_ref,method.ref) or not same(observation.check_spec_ref,spec.ref)
                        or not same(observation.engineering_scope_ref,spec.engineering_scope_ref)
                        or observation.author_organization_id not in method.permitted_executor_organization_ids):
                    raise ValueError('Inspection observation changes original method/check/coverage/executor')
                if (len(set(observation.observed_physical_keys))!=len(observation.observed_physical_keys)
                        or not set(observation.observed_physical_keys)<=set(scopes[spec.engineering_scope_ref.key()].physical_keys)):
                    raise ValueError('Inspection observation invents or repeats physical coverage')
                if (observation.observed_window.start.offset>=observation.observed_window.end.offset
                        or observation.observed_window.end.offset>min(now.offset,observation.available_at.offset)):
                    _needs('actual_observation_finished_before_received')
                checked_observations.add(observation.ref.key());basis.extend(observation.evidence_refs)
                observation_grant=authorize(observation.author_authority_ref,observation.author_actor_id,observation.author_function_ref,
                          observation.author_organization_id,observation.author_action_id,observation.observed_window.start)
                if observation.status=='executed':
                    if not observation.observed_physical_keys: _needs('original_actual_observation_location_coverage')
                    if observation.observed_window.end.offset>observation_grant.validity.end.offset:
                        _needs('original_observation_authority_covers_execution_window')
                    if (design.authored_at.offset>observation.observed_window.start.offset
                            or design.effective_window.start.offset>observation.observed_window.start.offset
                            or observation.observed_window.end.offset>design.effective_window.end.offset):
                        _needs('original_design_applicable_when_observed')
                    if not method.effective_window.contains(observation.observed_window.start) or observation.observed_window.end.offset>method.effective_window.end.offset:
                        _needs('observation_method_applicable_when_executed')
                    if method.requires_site_access:
                        if action_input.access_ref is None or observation.access_ref is None or not same(action_input.access_ref,observation.access_ref):
                            _needs('original_actual_inspection_site_access')
                        access=read(observation.access_ref,EngineerInspectionAccessView,True)
                        if (not same(access.task_ref,task.ref) or observation.author_organization_id not in access.executor_organization_ids
                                or not isinstance(access.allowed,Known) or not access.allowed.value
                                or spec.engineering_scope_ref.key() not in keys(access.engineering_scope_refs)
                                or access.effective_window.start.offset>observation.observed_window.start.offset
                                or observation.observed_window.end.offset>access.effective_window.end.offset):
                            _needs('original_site_access_covering_actual_observation')
                        if access.available_at.offset>observation.observed_window.start.offset:
                            _needs('original_site_access_received_before_actual_observation')
                    invested,facts=work_facts(observation.work_fact_refs,task.ref,observation.author_organization_id)
                    if invested<=0 or not facts:_needs('actual_inspection_observation_investment')
                    if any(fact.available_at.offset>observation.available_at.offset for fact in facts):
                        raise ValueError('Observation borrows later investment confirmation')
                    if not any(fact.window.start.offset<=observation.observed_window.start.offset and observation.observed_window.end.offset<=fact.window.end.offset for fact in facts):
                        _needs('original_work_window_covering_actual_observation')
                    missing=['method_execution']
                    if check_preparation is not None and same(observation.ref, check_preparation.observation_ref):
                        if (not same(spec.ref, check_preparation.check_spec_ref)
                                or observation.check_result_ref != check_preparation.calculation_ref):
                            raise ValueError('Inspection preparation replaces original observation/spec mapping')
                        if spec.evaluation_method_ref != ENGINEER_INTERFACE_METHOD:
                            _unsupported('engineer-inspection-unbound-evaluation-method')
                        evaluation = read(spec.evaluation_method_ref, EngineerInspectionMethodView)
                        method_domain(evaluation)
                        if evaluation.purpose != 'test' or organization not in evaluation.permitted_executor_organization_ids:
                            _unsupported('engineer-inspection-evaluation-executor-purpose')
                        source_refs = list({ref.key(): ref for ref in [task.ref, appointment.ref, terms.ref,
                            design.ref, spec.ref, observation.ref, scopes[spec.engineering_scope_ref.key()].ref,
                            method.ref, evaluation.ref, *observation.work_fact_refs,
                            *task.evidence_refs, *design.evidence_refs, *spec.evidence_refs,
                            *observation.evidence_refs, *evaluation.evidence_refs]}.values())
                        if observation.access_ref is not None:
                            source_refs.append(observation.access_ref)
                            source_refs = list({ref.key(): ref for ref in source_refs}.values())
                        original = EngineerInterfaceInput(requested_check=spec.requested_check,
                            left_code=observation.observed_code, right_code=spec.expected_code, source_refs=source_refs)
                        if check_preparation.input != original:
                            raise ValueError('Inspection preparation changes observed/expected codes or original sources')
                        prepared_check = {'kind': 'prepared', 'preparation': check_preparation, 'task': task,
                            'design': design, 'spec': spec, 'observation': observation}
                    if observation.check_result_ref is not None and check_preparation is None:
                        saved=read(observation.check_result_ref,EngineerInspectionResultView,True);bound(saved);clock(saved.executed_at)
                        if (not same(saved.check_spec_ref,spec.ref) or not same(saved.observation_ref,observation.ref)
                                or spec.evaluation_method_ref is None or not same(saved.method_ref,spec.evaluation_method_ref)
                                or saved.executed_at.offset>min(now.offset,saved.available_at.offset)
                                or saved.executed_at.offset<observation.available_at.offset):raise ValueError('Inspection result changes original observed input/method/time')
                        authorize(saved.author_authority_ref,saved.author_actor_id,saved.author_function_ref,saved.author_organization_id,saved.author_action_id,saved.executed_at)
                        if saved.status!='ok' and saved.result is not None:raise ValueError('Failed inspection evaluation cannot retain substantive finding')
                        if saved.status=='ok':
                            if spec.available_at.offset>saved.executed_at.offset or not spec.effective_window.contains(saved.executed_at):
                                raise ValueError('Inspection evaluation borrows unavailable or inapplicable check specification')
                            if not same(saved.method_ref,ENGINEER_INTERFACE_METHOD):_unsupported('engineer-inspection-unbound-evaluation-method')
                            replay=check_interface(EngineerInterfaceInput(requested_check=spec.requested_check,left_code=observation.observed_code,
                                right_code=spec.expected_code,source_refs=[spec.ref,observation.ref]))
                            if saved.result!=replay:raise ValueError('Inspection saved finding differs from declared original evidence/method')
                            value,missing=replay.result,replay.missing_field_paths;basis.extend(spec.evidence_refs);basis.extend(saved.evidence_refs)
                            records=evidence(basis,True)
                            if isinstance(observation.observed_code,Known) and isinstance(spec.expected_code,Known):
                                evidence_status='sufficient' if all(row.basis_kind=='observed' for row in records) else 'assumption_based'
                        else:missing=['method_execution:'+saved.status]
                else:
                    if observation.check_result_ref is not None:raise ValueError('Unexecuted observation cannot carry substantive evaluation')
                    missing=['observation_execution:'+observation.status]
            for ref in item_issues.values():
                issue=read(ref,EngineerInspectionIssueView);bound(issue)
                if not same(issue.engineering_scope_ref,spec.engineering_scope_ref) or issue.status=='closed':
                    raise ValueError('Inspection invents problem coverage or closes original issue')
            if value=='satisfied' and evidence_status=='sufficient' and not item_issues:
                observed_coverage[spec.engineering_scope_ref.key()].update(observation.observed_physical_keys)
                if observed_coverage[spec.engineering_scope_ref.key()]==set(scopes[spec.engineering_scope_ref.key()].physical_keys):
                    uncovered.discard(spec.engineering_scope_ref.key())
            items.append({'check_spec_ref':spec.ref,'evidence_refs':list({ref.key():ref for ref in basis}.values()),
                'evidence_status':evidence_status,'method_result_ref':saved.ref if saved else None,'result':value,
                'missing_field_paths':missing,'issue_refs':list(item_issues.values())})
        if checked_observations!=set(observations):raise ValueError('Inspection report contains unrelated observations')
        if check_preparation is not None:
            if prepared_check is None:
                _needs('original_executed_inspection_observation_for_check', [check_preparation.observation_ref])
            reading.recheck()
            return prepared_check
        for spec,item in zip(specs,items):
            if item['result']!='satisfied' or item['evidence_status']!='sufficient' or item['issue_refs']:uncovered.add(spec.engineering_scope_ref.key())
        findings=[row['result'] for row in items]
        opinion=('revise' if 'conflict' in findings else 'investigate' if not findings or any(value in {None,'undetermined'} for value in findings)
            else 'reserve_interpretation' if uncovered or 'out_of_scope' in findings else 'support_limited_option')
        explanation=task.note+'; only original visible observations and explicitly covered locations; no zero-defect or whole-project claim'
        return completed('report',assessment={'target_ref':design.ref,'task_ref':task.ref,'check_items':items,'opinion':opinion,
            'requested_use':task.requested_use,'uncovered_scope_refs':[scopes[key].ref for key in sorted(uncovered)],'explanation':explanation},
            observation_refs=action_input.observation_refs)
    except ObservationGap as gap:
        reading.recheck();return gap.result
