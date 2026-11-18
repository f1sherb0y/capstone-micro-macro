"""QS-A11 retains original price/measurement access and separate unpaid duties."""
from src.actions.contracts.common import Known
from src.actions.contracts.qs_transition_objects import (
    qs_transition_types, QSTransitionTaskView, QSTransitionSourceView, QSTransitionSourceAccessView,
    QSTransitionContractView, QSReviewEstimateView,
)
from src.actions.contracts.owner_study_objects import unique_refs
from src.actions.roles.owner import _needs, _unsupported
from src.actions.roles.qs_change import content_digest
from src.actions.roles.service_transition import transition_service
from src.methods.pricing import decimal_fraction
from src.organization.models import Authorization
from src.organization.registry import scope_covers


def transition_qs_service(context, action_input, reading):
    now,org=context.business_time,reading.organization_id
    physical=set()

    def keys(refs):
        unique_refs(refs)
        return {r.key() for r in refs}

    def obligation_check(obligation,engagement,read):
        if (obligation.as_of!=now or obligation.engagement_ref!=engagement.ref
                or obligation.physical_obligation_key in physical):
            raise ValueError('QS handover substitutes current original obligation or repeats physical debt')
        physical.add(obligation.physical_obligation_key)
        contract=read(obligation.contract_ref,QSTransitionContractView,linked=True)
        if obligation.debtor_id!=contract.debtor_id or obligation.payee_id!=contract.payee_id:
            raise ValueError('QS handover substitutes original contract debtor or payee')
        if obligation.obligation_role=='qs_service_fee':
            if obligation.contract_ref!=engagement.service_contract_ref or org not in {obligation.debtor_id,obligation.payee_id}:
                raise ValueError('QS fee obligation cannot be used to clear another client contract')
        elif obligation.contract_ref.key() not in keys(engagement.client_contract_refs):
            raise ValueError('Client settlement/support duty must retain its original associated contract')
        if not keys(obligation.supporting_task_refs)<=keys(engagement.task_refs):
            raise ValueError('QS obligation changes original continuing support tasks')
        continuing = obligation.obligation_role=='dispute_support' and obligation.status in {'effective','disputed'}
        if continuing and not obligation.supporting_task_refs:
            _needs('original_continuing_dispute_support_task',[obligation.ref])
        for ref in obligation.supporting_task_refs:
            task=read(ref,QSTransitionTaskView,linked=True)
            if (task.engagement_ref!=engagement.ref or task.organization_id!=org
                    or task.author_organization_id!=org
                    or not (scope_covers(task.scope,obligation.origin_scope)
                        or scope_covers(obligation.origin_scope,task.scope))):
                raise ValueError('QS remaining duty borrows another service, firm or out-of-scope support task')
            if continuing and task.status in {'complete','cancelled'}:
                _needs('current_original_continuing_dispute_support_task',[obligation.ref,task.ref])

    def estimate_check(task,read,author,evidence,clock):
        estimate=read(task.work_estimate_ref,QSReviewEstimateView,linked=True);author(estimate);clock(estimate.executed_at)
        if (estimate.task_ref!=task.ref or estimate.work_profile_ref!=task.work_profile_ref
                or estimate.organization_id!=task.organization_id or estimate.author_organization_id!=task.organization_id
                or estimate.function_code!=task.function_code or estimate.executed_at.offset>estimate.authored_at.offset):
            raise ValueError('QS review/recall work substitutes its original task method estimate')
        if estimate.status=='unsupported': _unsupported('qs-recall-review-work-method-domain')
        if estimate.status!='succeeded' or not isinstance(task.method_remaining_effort,Known):
            _needs('successful_original_qs_remaining_work_estimate',[estimate.ref])
        remaining=task.method_remaining_effort.value;evidence([estimate.effort.basis_ref,remaining.basis_ref])
        if (estimate.effort.unit!=remaining.unit or decimal_fraction(estimate.effort.value)!=decimal_fraction(remaining.value)
                or decimal_fraction(estimate.effort.value)<=0):
            raise ValueError('QS review/recall effort differs from original positive remaining method work')

    def recall_task_check(task,item,resources,read,author,evidence,clock):
        estimate_check(task,read,author,evidence,clock)

    def acceptance_check(acceptance,package,deliverables,read,author,evidence,clock):
        if keys(acceptance.reviewed_deliverable_refs)!=set(deliverables):
            raise ValueError('QS successor omits original price or measurement handover scope')
        sources={}
        for document in deliverables.values():
            if not scope_covers(context.scope,document.conclusion_scope):
                raise ValueError('QS handover expands original conclusion scope')
            keys(document.private_client_record_refs)
            keys(document.price_source_refs);keys(document.measurement_trace_refs)
            for ref in [*document.price_source_refs,*document.measurement_trace_refs]:
                source=read(ref,QSTransitionSourceView,historic=True,linked=True);author(source)
                if source.provider_organization_id!=source.author_organization_id:
                    raise ValueError('QS handover substitutes original price/measurement provider')
                sources[ref.key()]=source
        grants=set();keys(acceptance.source_access_refs)
        for ref in acceptance.source_access_refs:
            grant=read(ref,QSTransitionSourceAccessView,linked=True);author(grant)
            source=sources.get(grant.source_ref.key())
            if (source is None or grant.source_sha256!=content_digest(source)
                    or grant.recipient_id!=acceptance.recipient_id or grant.author_organization_id!=source.provider_organization_id
                    or grant.source_ref.key() in grants or not isinstance(grant.permitted,Known) or not grant.permitted.value):
                _needs('original_lawful_successor_price_measurement_access',[ref])
            grants.add(grant.source_ref.key())
        if grants!=set(sources): _needs('all_original_successor_quantity_price_source_permissions')
        task=read(acceptance.review_task_ref,QSTransitionTaskView,linked=True);author(task)
        if (task.organization_id!=acceptance.author_organization_id or task.author_organization_id!=task.organization_id
                or task.engagement_ref!=package.engagement_ref or keys(task.review_target_refs)!=set(deliverables)
                or not scope_covers(acceptance.independent_review_scope,task.scope)
                or not isinstance(task.permitted,Known) or not task.permitted.value or task.status in {'complete','cancelled'}):
            _needs('successor_own_original_qs_review_task_permission',[task.ref])
        grant=read(acceptance.author_authority_ref,Authorization,historic=True,linked=True)
        if not any(scope_covers(s,acceptance.independent_review_scope) for s in grant.scopes):
            raise ValueError('QS successor lacks original independent review scope authority')
        estimate_check(task,read,author,evidence,clock)
        if not isinstance(task.remaining_effort,Known): _needs('successor_original_remaining_qs_review_effort',[task.ref])
        remaining=task.remaining_effort.value;method=task.method_remaining_effort.value
        evidence([remaining.basis_ref]);clock(task.planned_window.start);clock(task.planned_window.end)
        if (remaining.unit!=method.unit or decimal_fraction(remaining.value)!=decimal_fraction(method.value)
                or task.planned_window.bounds!='closed_open' or task.planned_window.start.offset<now.offset
                or task.planned_window.end.offset<=task.planned_window.start.offset):
            _needs('successor_own_qs_review_investment_and_time',[task.ref])

    return transition_service(context,action_input,reading,action_id='QS-A11',document_input='deliverable_refs',
        transition_types=qs_transition_types(),acceptance_check=acceptance_check,
        obligation_check=obligation_check,recall_task_check=recall_task_check)
