"""OWN-A04 forms the owner's procurement decision, never an appointment."""
from src.actions.contracts.common import EvidenceRecord, TimeWindow
from src.actions.contracts.domain import CandidateSet
from src.actions.contracts.owner_commission_objects import (
    CommissionOrganizationView, CommissionCaseView, CommissionProjectView,
    CommissionProfileView, CommissionServiceScopeView, CommissionWorkView,
    CommissionDeliverableView, CommissionProviderView, CommissionCapabilityView,
    CommissionQualificationView, CommissionMethodView, CommissionOfferView,
    CommissionTermsView, CommissionConditionView, CommissionIssueView,
    CommissionResourceView, CommissionManagementView, CommissionInternalPlanView,
    CommissionTaskView,
)
from src.actions.contracts.owner_study_objects import unique_refs
from src.actions.roles.owner import ObservationGap, _known, _needs, _unsupported
from src.actions.roles.owner_investment import ROLE_ACTIONS
from src.methods.capacity import CAPACITY_METHOD, CapacityInput, ExactAmount
from src.methods.owner_commission import COMMISSION_METHOD, ServiceSelectionInput, ServiceSelectionCandidate
from src.methods.pricing import decimal_fraction
from src.organization.models import Authorization, RoleAssignment
from src.organization.registry import scope_covers


def commission_services(context, action_input, reading):
    now, owner = context.business_time, reading.organization_id

    def clock(point):
        if point.clock_ref != now.clock_ref:
            _unsupported('owner-commission-clock')

    def available(point, field):
        clock(point)
        if point.offset > now.offset:
            _needs(field)

    def active(window):
        clock(window.start)
        return window.contains(now)

    def current(window, field):
        if not active(window):
            _needs(field)

    def evidence(refs):
        for ref in refs:
            record = reading.resolve(ref)
            if not isinstance(record,EvidenceRecord):
                _unsupported('owner-commission-evidence-schema')
            if record.effective_window is not None:
                current(record.effective_window,'current_commission_evidence')

    def read(ref, schema):
        row = reading.resolve(ref)
        if not isinstance(row,schema):
            _unsupported(f'owner-commission-projection:{ref.kind}')
        if hasattr(row,'evidence_refs'):
            evidence(row.evidence_refs)
        return row

    def method(ref, data):
        result = reading.calculate(ref,data)
        if result.kind == 'ok':
            return result.value
        if result.kind == 'invalid_input':
            raise ValueError('Invalid sourced professional-procurement method input')
        raw = result.model_dump(mode='python')
        if result.kind == 'needs_information':
            raw['requested_refs'] = []
        raise ObservationGap(raw)

    def completed(choice, note, **fields):
        reading.recheck()
        return {'kind':'completed','payload':{'choice':choice,'note':note,**fields}}

    def deferred():
        reading.recheck()
        return {'kind':'deferred','reason_code':'owner_service_procurement_dependencies_pending',
            'resume_condition':{'trigger':'dependency_change','object_refs':[profile.ref,service.ref,capacity.ref],
                'earliest_time':None,'condition_code':'owner.commission.inputs_changed'}}

    def unavailable(reason):
        policy = _known(profile.on_unavailable,'declared_commission_unavailable_policy')
        if policy == 'defer':
            return deferred()
        return completed(policy,reason+'; existing services, fees and obligations are preserved')

    def function(ref):
        row = read(ref,RoleAssignment)
        evidence(row.basis_refs)
        return row

    def authority(ref, organization, actor, function_ref, action, scope):
        row = read(ref,Authorization)
        assignment = function(function_ref)
        evidence(row.basis_refs)
        if (row.organization_id != organization or row.actor_id != actor or row.function_ref != function_ref):
            raise ValueError('Service authority changes organization, actor or assigned function')
        prefix,count = ROLE_ACTIONS[assignment.role]
        if action not in {f'{prefix}-A{i:02}' for i in range(1,count+1)}:
            raise ValueError('Service authorization action does not belong to its assigned function')
        if assignment.role in {'Architect','Engineer','QS'} and action != f'{prefix}-A02':
            return False
        return (active(row.validity) and action in row.action_ids
                and any(scope_covers(value,scope) for value in row.scopes))

    def scope_inside(value):
        return (bool(value.coverage_refs) and scope_covers(service.scope_ref,value)
                and scope_covers(context.scope,value) and scope_covers(profile.scope_ref,value))

    def conditions(refs, terms_ref=None):
        unique_refs(refs)
        for ref in refs:
            row = read(ref,CommissionConditionView)
            if row.service_scope_ref != service.ref or not scope_covers(row.scope_ref,service.scope_ref):
                raise ValueError('Service condition changes the exact service or required scope')
            if row.terms_ref is not None and row.terms_ref != terms_ref:
                _needs('same_version_service_conditions',[row.ref])
            current(row.effective_window,'current_commission_condition')
            available(row.verified_at,'available_commission_condition')
            if not _known(row.permitted,'verified_commission_condition'):
                return False
        return True

    def capability(ref, organization, function_ref, requested_scope):
        row = read(ref,CommissionCapabilityView)
        if row.organization_id != organization or row.function_ref != function_ref:
            raise ValueError('Professional capability changes organization or function')
        if not active(row.effective_window):
            return False
        role = function(function_ref).role
        if role not in service.permitted_roles or role not in profile.permitted_roles:
            return False
        works = [work_by_ref[ref.key()] for ref in requested_scope.coverage_refs]
        services = {code for work in works for code in work.service_codes}
        uses = {code for work in works for code in work.requested_uses}
        responsibilities = {code for work in works for code in work.responsibility_codes}
        if (service.region_id not in _known(row.region_ids,'professional_service_regions')
                or not services <= set(_known(row.service_codes,'professional_service_codes'))
                or not uses <= set(_known(row.allowed_uses,'professional_service_uses'))
                or not responsibilities <= set(_known(row.responsibility_codes,'professional_responsibilities'))):
            return False
        if row.qualification_coverage != 'complete':
            _needs('complete_applicable_professional_qualifications',[row.ref])
        qualified = set()
        for ref in row.qualification_refs:
            qualification = read(ref,CommissionQualificationView)
            if qualification.organization_id != organization or qualification.function_ref != function_ref:
                raise ValueError('Professional qualification belongs to another organization/function')
            available(qualification.verified_at,'available_professional_qualification')
            if (not active(qualification.effective_window) or service.region_id not in qualification.region_ids
                    or not services <= set(qualification.service_codes)):
                continue
            if _known(qualification.standing,'current_professional_qualification_standing'):
                qualified.add(qualification.code)
        if not set(service.required_qualification_codes) <= qualified:
            return False
        supported = _known(row.method_refs,'professional_service_methods')
        if not set(service.required_method_refs) <= set(supported):
            return False
        for ref in service.required_method_refs:
            support = read(ref,CommissionMethodView)
            available(support.available_at,'available_professional_service_method')
            if (not active(support.effective_window) or service.region_id not in support.region_ids
                    or role not in support.permitted_roles or not services <= set(support.service_codes)
                    or not uses <= set(support.allowed_uses)):
                return False
        return True

    def provider(ref, choice):
        if ref not in action_input.candidate_provider_refs:
            raise ValueError('Service provider is outside the supplied eligible candidates')
        row = read(ref,CommissionProviderView)
        available(row.available_at,'received_service_provider')
        assignment = function(row.function_ref)
        if assignment.role not in service.permitted_roles or assignment.role not in profile.permitted_roles:
            return None
        cap = read(row.capability_ref,CommissionCapabilityView)
        if cap.organization_id != row.organization_id or cap.function_ref != row.function_ref:
            raise ValueError('Eligible provider imports another function/organization capability')
        if row.status != 'active' or not active(row.effective_window):
            return None
        if choice in {'invite','clarify'}:
            if not _known(row.invitation_permitted,'service_provider_invitation_permission'):
                return None
            candidates.check_selected(choice,[row.ref])
        return row

    def allocation_scope(allocation):
        target = allocation.task_target
        if target.kind == 'proposed':
            value = target.scope_ref
            prior = proposed_tasks.get(target.local_key)
            if prior is not None and prior != value:
                raise ValueError('One proposed task key cannot name different service work')
            proposed_tasks[target.local_key] = value
        else:
            task = read(target.task_ref,CommissionTaskView)
            if task.organization_id != owner or task.service_scope_ref != service.ref:
                raise ValueError('Internal service task changes owner or service version')
            available(task.available_at,'available_internal_service_task')
            current(task.effective_window,'current_internal_service_task')
            if task.status != 'active':
                _needs('active_internal_service_task',[task.ref])
            value = task.scope_ref
        if not scope_inside(value):
            raise ValueError('Resource allocation imports unrelated service work')
        return value

    def within_capacity(internal_allocations=()):
        if capacity.as_of != now or capacity.coverage != 'complete':
            _needs('current_complete_service_management_load')
        if not profile.management_allocations:
            _needs('declared_service_management_allocations')
        resources, demands, loads, source_refs = {}, [], [], [profile.ref,service.ref,capacity.ref]
        if internal_allocations:
            source_refs.append(profile.internal_plan_ref)
        service_coverage,management_coverage = set(),set()
        for allocations,purpose in ((profile.management_allocations,'management'),(internal_allocations,'internal_service')):
            for allocation in allocations:
                if allocation.resource_ref not in capacity.resource_refs:
                    raise ValueError('Service allocation uses a pool absent from the shared capacity snapshot')
                requested_scope = allocation_scope(allocation)
                source_refs.append(allocation.window_ref)
                if allocation.task_target.kind == 'existing':
                    source_refs.append(allocation.task_target.task_ref)
                if purpose == 'management':
                    management_coverage.update(ref.key() for ref in requested_scope.coverage_refs)
                pool = read(allocation.resource_ref,CommissionResourceView)
                if pool.organization_id != owner:
                    raise ValueError('Internal procurement cannot allocate another organization resources')
                if pool.as_of != now or pool.coverage != 'complete':
                    _needs('current_complete_service_resource_load')
                if purpose not in pool.purpose_codes or pool.region_id != service.region_id:
                    return False
                if not authority(pool.authority_ref,owner,context.actor_id,context.function_ref,'OWN-A04',requested_scope):
                    return False
                if purpose == 'internal_service':
                    if (not capability(pool.capability_ref,owner,pool.function_ref,requested_scope)
                            or not authority(pool.service_authority_ref,owner,pool.service_actor_id,pool.function_ref,
                                             pool.service_authority_action_id,requested_scope)):
                        return False
                    service_coverage.update(ref.key() for ref in requested_scope.coverage_refs)
                desired = read(allocation.window_ref,TimeWindow)
                clock(desired.start)
                clock(pool.effective_window.start)
                if desired.bounds != 'closed_open' or pool.effective_window.bounds != 'closed_open':
                    _unsupported('owner-commission-half-open-capacity-window')
                if desired.start.offset < now.offset or desired.start.offset >= desired.end.offset:
                    _needs('future_nonempty_service_allocation_window')
                if desired != work_window:
                    raise ValueError('Service allocations change the exact declared work window')
                total = _known(pool.total,'actual_owner_service_resource_capacity')
                evidence([total.basis_ref,allocation.quantity.basis_ref])
                if allocation.quantity.unit != total.unit:
                    _unsupported('owner-commission-resource-unit-conversion')
                demands.append({'resource_kind':pool.ref.id,'region_id':pool.region_id,'unit':total.unit,
                    'amount':ExactAmount.from_fraction(decimal_fraction(allocation.quantity.value)),
                    'window':desired,'basis_refs':[allocation.quantity.basis_ref]})
                if pool.ref.key() not in resources:
                    resources[pool.ref.key()] = {'resource_ref':pool.ref,'resource_kind':pool.ref.id,
                        'region_id':pool.region_id,'total':total,'effective_window':pool.effective_window}
                    source_refs.append(pool.ref)
                    for load in pool.commitments:
                        clock(load.window.start)
                        evidence([load.quantity.basis_ref])
                        if load.window.bounds != 'closed_open':
                            _unsupported('owner-commission-commitment-window')
                        if load.quantity.unit != total.unit:
                            _unsupported('owner-commission-commitment-unit-conversion')
                        loads.append({'commitment_ref':load.ref,'resource_ref':pool.ref,'quantity':load.quantity,'window':load.window})
        if internal_allocations and service_coverage != set(work_by_ref):
            raise ValueError('Internal service allocations omit required professional work')
        if management_coverage != set(work_by_ref):
            raise ValueError('Management arrangement omits required service work')
        return method(CAPACITY_METHOD,CapacityInput(clock_ref=now.clock_ref,resources=list(resources.values()),
            demands=demands,commitments=loads,source_refs=list(dict.fromkeys(source_refs)))).feasible

    try:
        unique_refs(action_input.candidate_provider_refs)
        unique_refs(action_input.candidates)
        profile = read(action_input.procurement_profile_ref,CommissionProfileView)
        service = read(action_input.service_scope_ref,CommissionServiceScopeView)
        capacity = read(action_input.capacity_ref,CommissionManagementView)
        candidates = read(context.candidate_set_ref,CandidateSet)
        if (profile.organization_id != owner or service.employer_organization_id != owner or capacity.organization_id != owner
                or profile.service_scope_ref != service.ref or profile.scope_ref != action_input.scope_ref
                or service.scope_ref != action_input.scope_ref or not scope_covers(context.scope,service.scope_ref)):
            raise ValueError('Professional procurement changes owner, service version or invocation scope')
        for row,name in ((profile,'procurement_profile'),(service,'service_scope')):
            available(row.available_at,'available_'+name)
            current(row.effective_window,'current_'+name)
        if not authority(action_input.authority_ref,owner,context.actor_id,context.function_ref,'OWN-A04',service.scope_ref):
            _needs('current_owner_service_commission_authority',[action_input.authority_ref])
        if function(context.function_ref).role != 'Owner':
            raise ValueError('Professional advice cannot replace the owner commission decision')
        parent_type = {'organization':CommissionOrganizationView,'assessment_case':CommissionCaseView,'project':CommissionProjectView}[service.scope_ref.kind]
        parent = read(service.scope_ref.ref,parent_type)
        parent_owner = getattr(parent,'owner_organization_id',getattr(parent,'organization_id',None))
        if parent_owner != owner:
            raise ValueError('Service belongs to another owner scope')
        if hasattr(parent,'available_at'):
            available(parent.available_at,'available_commission_scope')
        policy = _known(profile.policy,'declared_service_procurement_policy')
        if policy in {'reject_all','retender'}:
            return completed(policy,'No new appointment is formed; existing services, fees and obligations are preserved')
        if policy == 'defer':
            return deferred()
        if getattr(parent,'status','active') == 'closed':
            return unavailable('The service scope is closed')
        work_by_ref,proposed_tasks = {},{}
        for ref in service.scope_ref.coverage_refs:
            work = read(ref,CommissionWorkView)
            current(work.effective_window,'current_professional_service_work')
            if not scope_inside(work.scope_ref):
                raise ValueError('Service includes work from another case/project')
            work_by_ref[ref.key()] = work
        for name in ('service_codes','requested_uses','responsibility_codes','deliverable_refs'):
            if {value for work in work_by_ref.values() for value in getattr(work,name)} != set(getattr(service,name)):
                raise ValueError('Service scope omits or imports work responsibilities, uses or deliverables')
        for ref in service.deliverable_refs:
            requirement = read(ref,CommissionDeliverableView)
            if (requirement.service_scope_ref != service.ref or requirement.work_ref.key() not in work_by_ref
                    or ref not in work_by_ref[requirement.work_ref.key()].deliverable_refs
                    or requirement.requested_use not in work_by_ref[requirement.work_ref.key()].requested_uses):
                raise ValueError('Deliverable belongs to another service/work or unauthorized use')
        if policy == 'invite':
            if not profile.invitation_provider_refs:
                _needs('explicit_service_invitation_targets')
            recipients = []
            for ref in profile.invitation_provider_refs:
                target = provider(ref,'invite')
                if target is not None and target.organization_id not in recipients:
                    recipients.append(target.organization_id)
            if not recipients:
                return unavailable('No permitted active service invitation target is available')
            return completed('invite','Invite only the declared eligible providers; no qualification, contract or reservation is inferred',
                recipient_ids=recipients,issue_refs=[])
        if policy == 'clarify':
            if not profile.clarification_issue_refs:
                _needs('registered_service_clarification_issues')
            recipients = []
            for ref in profile.clarification_issue_refs:
                issue = read(ref,CommissionIssueView)
                if issue.service_scope_ref != service.ref or not scope_inside(issue.scope_ref):
                    raise ValueError('Clarification changes service version or imports unrelated work')
                available(issue.available_at,'available_service_clarification_issue')
                current(issue.effective_window,'current_service_clarification_issue')
                if issue.status != 'unresolved':
                    _needs('unresolved_service_clarification_issue',[issue.ref])
                for provider_ref in issue.provider_refs:
                    target = provider(provider_ref,'clarify')
                    if target is None:
                        _needs('active_permitted_service_clarification_recipient',[provider_ref])
                    if target.organization_id not in recipients:
                        recipients.append(target.organization_id)
                for offer_ref in issue.offer_refs:
                    if offer_ref not in action_input.candidates:
                        raise ValueError('Clarification imports an unreceived service offer')
                    offer = read(offer_ref,CommissionOfferView)
                    if offer.provider_ref not in issue.provider_refs or offer.service_scope_ref != service.ref:
                        raise ValueError('Service issue imports another recipient offer or service')
            return completed('clarify','Request the registered bounded service clarifications; no commercial acceptance or payment is authorized',
                recipient_ids=recipients,issue_refs=profile.clarification_issue_refs)
        work_window = read(service.window_ref,TimeWindow)
        clock(work_window.start)
        if work_window.bounds != 'closed_open':
            _unsupported('owner-commission-service-window-model')
        if work_window.start.offset < now.offset or work_window.start.offset >= work_window.end.offset:
            _needs('future_nonempty_professional_service_window')
        if policy == 'internal':
            if profile.internal_plan_ref is None:
                _needs('explicit_internal_service_plan')
            plan = read(profile.internal_plan_ref,CommissionInternalPlanView)
            if plan.organization_id != owner or plan.service_scope_ref != service.ref:
                raise ValueError('Internal service plan changes owner or service version')
            available(plan.available_at,'available_internal_service_plan')
            current(plan.effective_window,'current_internal_service_plan')
            if not conditions(profile.required_condition_refs) or not within_capacity(plan.allocations):
                return unavailable('The internal professional or shared management arrangement is not currently feasible')
            return completed('internal','Arrange only this organization qualified and authorized service work; task creation and allocation remain formal-core operations',
                allocations=[row.model_dump(mode='python') for row in plan.allocations])
        fee_cap = _known(profile.fee_cap,'declared_service_procurement_fee_cap')
        evidence([fee_cap.basis_ref])
        feasible, selection = {},[]
        for ref in action_input.candidates:
            offer = read(ref,CommissionOfferView)
            available(offer.received_at,'received_professional_service_offer')
            if offer.service_scope_ref != service.ref:
                raise ValueError('Service offer changes the exact requested service version')
            if offer.status != 'offered' or not active(offer.effective_window):
                continue
            target = provider(offer.provider_ref,'accept')
            if target is None:
                continue
            if target.organization_id == owner:
                raise ValueError('The same organization service must use internal tasks, not a self appointment')
            if offer.author_actor_id != target.actor_id or offer.author_function_ref != target.function_ref:
                raise ValueError('Received service offer changes the provider author/function')
            if not authority(offer.authority_ref,target.organization_id,target.actor_id,target.function_ref,
                    offer.authority_action_id,service.scope_ref):
                continue
            terms = read(offer.terms_ref,CommissionTermsView)
            available(terms.issued_at,'issued_service_terms')
            if (terms.service_scope_ref != service.ref or terms.scope_ref != service.scope_ref
                    or terms.employer_organization_id != owner or terms.provider_organization_id != target.organization_id
                    or terms.window_ref != service.window_ref):
                raise ValueError('Service terms change employer, provider, scope, version or deadline')
            if terms.status != 'offered' or not active(terms.effective_window):
                continue
            for name in ('service_codes','requested_uses','responsibility_codes'):
                if set(_known(getattr(terms,name),'exact_service_terms_'+name)) != set(getattr(service,name)):
                    raise ValueError('Service terms omit or expand required professional responsibilities or uses')
            if set(terms.deliverable_refs) != set(service.deliverable_refs):
                raise ValueError('Service terms change required deliverables')
            if not set(_known(terms.authority_limits,'service_contract_authority_limits')) <= set(_known(profile.permitted_authority_codes,'permitted_service_contract_authority')):
                continue
            if function(terms.payer_function_ref).role != 'Owner' or terms.payer_authority_action_id != 'OWN-A04':
                raise ValueError('Service advice cannot authorize the payer commercial commitment')
            if not authority(terms.payer_authority_ref,terms.payer_organization_id,terms.payer_actor_id,
                    terms.payer_function_ref,terms.payer_authority_action_id,service.scope_ref):
                continue
            refs = list(dict.fromkeys([*profile.required_condition_refs,*terms.condition_refs]))
            if (not conditions(refs,terms.ref) or not capability(target.capability_ref,target.organization_id,target.function_ref,service.scope_ref)):
                continue
            candidates.check_selected('accept',[offer.ref])
            fee = _known(terms.fee,'received_exact_professional_service_fee')
            evidence([fee.basis_ref])
            if fee.currency != fee_cap.currency:
                _unsupported('owner-commission-fee-currency-conversion')
            selection.append(ServiceSelectionCandidate(offer_ref=offer.ref,terms_ref=terms.ref,
                priority=_known(offer.priority,'explicit_owner_service_offer_priority'),fee=fee))
            feasible[offer.ref.key()] = terms
        if not selection:
            return unavailable('No current applicable professional service offer is available')
        if not within_capacity():
            return unavailable('Existing shared management commitments conflict with the proposed service')
        report = method(COMMISSION_METHOD,ServiceSelectionInput(fee_cap=fee_cap,candidates=selection,
            source_refs=[profile.ref,*[row.offer_ref for row in selection],*[row.terms_ref for row in selection]]))
        if report.ambiguous_refs:
            _needs('distinct_declared_professional_service_preference',report.ambiguous_refs)
        if report.selected_ref is None:
            return unavailable('All applicable service fees exceed the declared procurement cap')
        terms = feasible[report.selected_ref.key()]
        return completed('accept','Accept only the owner side of this exact offer and terms; independent parties and the formal core must still accept and commit',
            offer_ref=report.selected_ref,terms_ref=terms.ref)
    except ObservationGap as gap:
        return gap.result
