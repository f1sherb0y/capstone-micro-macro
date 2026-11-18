"""ENGINEER-A11 uses original personnel/tools and independent successor checks."""
from fractions import Fraction

from src.actions.contracts.common import Known
from src.actions.contracts.engineer_transition_objects import (
    engineer_transition_types, EngineerTransitionTaskView, EngineerTransitionMethodView,
    EngineerPlanningQualificationView, EngineerPlanningAccessView,
)
from src.actions.contracts.owner_study_objects import unique_refs
from src.actions.roles.owner import _needs, _unsupported
from src.actions.roles.service_transition import transition_service
from src.methods.capacity import CapacityDemand, ExactAmount
from src.methods.pricing import decimal_fraction
from src.organization.models import Authorization
from src.organization.registry import scope_covers


def transition_engineering_service(context, action_input, reading):
    now,org=context.business_time,reading.organization_id
    physical=set();people=set()

    def true(value): return isinstance(value,Known) and value.value is True

    def keys(refs):
        unique_refs(refs)
        return {ref.key() for ref in refs}

    def resource_check(resource,read,evidence):
        if resource.organization_id!=org or resource.physical_resource_key in physical:
            raise ValueError('Engineering recall duplicates actual staff/tool or substitutes another firm resource')
        physical.add(resource.physical_resource_key)
        if resource.asset_role=='personnel':
            if (not resource.personnel_ids or len(set(resource.personnel_ids))!=len(resource.personnel_ids)
                    or people.intersection(resource.personnel_ids) or resource.effort_per_capacity_tick is None):
                raise ValueError('Engineering recall duplicates personnel or omits original productivity')
            people.update(resource.personnel_ids)
        elif resource.personnel_ids or resource.effort_per_capacity_tick is not None:
            raise ValueError('Engineering tool capacity cannot be disguised as personnel or substitute their productivity')

    def method_check(task,read,author):
        if not task.professional_method_refs: _needs('original_supported_engineering_recall_method',[task.ref])
        keys(task.professional_method_refs)
        for ref in task.professional_method_refs:
            method=read(ref,EngineerTransitionMethodView,linked=True);author(method)
            if method.organization_id!=task.organization_id or method.author_organization_id!=task.organization_id:
                raise ValueError('Engineering method substitutes original task firm')
            if (task.discipline_code not in method.discipline_codes or task.function_code not in method.function_codes
                    or not true(method.supported)):
                _unsupported('engineering-recall-professional-method-domain')

    def recall_demands(task,item,resources,read,author,evidence,clock):
        method_check(task,read,author)
        labor=set(task.resource_effort_shares);tools={d.resource_ref.id:d for d in task.tool_demands}
        keys([d.resource_ref for d in task.tool_demands])
        if (not labor or labor.intersection(tools) or not item.resource_ids
                or len(set(item.resource_ids))!=len(item.resource_ids) or set(item.resource_ids)!=labor|set(tools)):
            raise ValueError('Engineering recall changes original personnel/tool demands')
        shares=[decimal_fraction(v) for v in task.resource_effort_shares.values()]
        if any(v<=0 for v in shares) or sum(shares,Fraction())!=1:
            raise ValueError('Engineering recall labor shares must partition original method work')
        if task.site_access_ref is not None:
            access=read(task.site_access_ref,EngineerPlanningAccessView,linked=True)
            if access.organization_id!=org or access.task_ref!=task.ref or not true(access.allowed):
                _needs('original_engineering_recall_site_permission',[access.ref])
            if not access.effective_window.contains(item.window.start) or access.effective_window.end.offset<item.window.end.offset:
                _needs('engineering_site_permission_through_recall_window',[access.ref])
        demands=[]
        for identity in item.resource_ids:
            resource=resources.get(identity)
            if resource is None: _needs('original_engineering_recall_resource_version')
            if task.discipline_code not in resource.discipline_codes or task.function_code not in resource.function_codes:
                _needs('engineering_recall_professional_resource_fit',[resource.ref])
            if identity in labor:
                if resource.asset_role!='personnel' or resource.effort_per_capacity_tick is None:
                    raise ValueError('Engineering labor cannot be supplied by equipment')
                qualified=set();keys(resource.qualification_refs)
                for ref in resource.qualification_refs:
                    qualification=read(ref,EngineerPlanningQualificationView,linked=True)
                    if (qualification.organization_id!=org or not true(qualification.standing)
                            or task.discipline_code not in qualification.discipline_codes
                            or task.function_code not in qualification.function_codes or resource.region_id not in qualification.region_ids):
                        _needs('current_original_engineering_recall_qualification',[ref])
                    clock(qualification.effective_window.start);clock(qualification.effective_window.end)
                    if (not qualification.effective_window.contains(item.window.start)
                            or qualification.effective_window.end.offset<item.window.end.offset):
                        _needs('engineering_qualification_through_recall_window',[ref])
                    qualified.update(qualification.personnel_ids)
                if not set(resource.personnel_ids)<=qualified: _needs('all_original_qualified_engineering_recall_personnel')
                rate=resource.effort_per_capacity_tick
                if rate.unit!=item.effort.unit or decimal_fraction(rate.value)<=0:
                    _unsupported('engineering-recall-productivity-unit-domain')
                amount=decimal_fraction(item.effort.value)*decimal_fraction(task.resource_effort_shares[identity])/decimal_fraction(rate.value)/(item.window.end.offset-item.window.start.offset)
                refs=[item.effort.basis_ref,rate.basis_ref]
            else:
                tool=tools[identity];evidence([tool.capacity.basis_ref])
                if resource.asset_role!='equipment' or tool.resource_ref!=resource.ref or tool.capacity.unit!=resource.total.unit:
                    _unsupported('engineering-recall-original-tool-capacity-domain')
                amount=decimal_fraction(tool.capacity.value)
                if amount<=0: raise ValueError('Engineering recall requires positive original tool capacity')
                refs=[tool.capacity.basis_ref]
            demands.append(CapacityDemand(resource_kind=resource.ref.id,region_id=resource.region_id,
                unit=resource.total.unit,amount=ExactAmount.from_fraction(amount),window=item.window,basis_refs=refs))
        return demands

    def acceptance_check(acceptance,package,deliverables,read,author,evidence,clock):
        if keys(acceptance.reviewed_deliverable_refs)!=set(deliverables):
            raise ValueError('Engineering successor omits original handover conclusions')
        missing=set()
        for document in deliverables.values():
            if not scope_covers(context.scope,document.conclusion_scope):
                raise ValueError('Engineering handover broadens original conclusion scope')
            keys(document.professional_method_refs);keys(document.input_refs)
            missing.update(keys(document.missing_dependency_refs))
        if keys(acceptance.declared_missing_dependency_refs)!=missing:
            raise ValueError('Engineering successor must retain original missing analysis dependencies')
        task=read(acceptance.review_task_ref,EngineerTransitionTaskView,linked=True);author(task)
        if (task.organization_id!=acceptance.author_organization_id or task.author_organization_id!=task.organization_id
                or task.engagement_ref!=package.engagement_ref or not scope_covers(acceptance.independent_review_scope,task.scope)
                or not true(task.permitted) or task.status in {'complete','cancelled'}
                or keys(task.review_target_refs)!=set(deliverables) or not missing<=keys(task.dependency_refs)):
            _needs('successor_own_authorized_engineering_review_task',[task.ref])
        grant=read(acceptance.author_authority_ref,Authorization,historic=True,linked=True)
        if not any(scope_covers(s,acceptance.independent_review_scope) for s in grant.scopes):
            raise ValueError('Engineering successor lacks permission for its independent review scope')
        method_check(task,read,author)
        if not isinstance(task.method_remaining_effort,Known) or not isinstance(task.remaining_effort,Known):
            _needs('successor_original_method_review_investment',[task.ref])
        effort=task.method_remaining_effort.value;remaining=task.remaining_effort.value
        evidence([effort.basis_ref,remaining.basis_ref]);clock(task.planned_window.start);clock(task.planned_window.end)
        if (effort.unit!=remaining.unit or decimal_fraction(effort.value)!=decimal_fraction(remaining.value)
                or decimal_fraction(effort.value)<=0 or task.planned_window.bounds!='closed_open'
                or task.planned_window.start.offset<now.offset or task.planned_window.end.offset<=task.planned_window.start.offset):
            _needs('successor_own_positive_review_work_and_time',[task.ref])

    return transition_service(context,action_input,reading,action_id='ENGINEER-A11',document_input='deliverable_refs',
        transition_types=engineer_transition_types(),resource_check=resource_check,
        recall_demands=recall_demands,acceptance_check=acceptance_check)
