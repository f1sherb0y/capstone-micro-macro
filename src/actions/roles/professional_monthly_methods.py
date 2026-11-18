"""A12 records a sourced monthly improvement judgment while formal history stays unknown."""
from decimal import Decimal
from src.actions.contracts.common import EvidenceRecord
from src.actions.contracts.professional_monthly_methods import MonthlyMethodPolicy, MonthlyMethodObservation, MonthlyMethodJudgment
from src.coordination.tasks import task_digest


def analyze_monthly_methods(context, action_input, reading, *, decision, state, capability, action_id):
    policy=reading.resolve(decision.monthly_method_policy_ref)
    observation=reading.resolve(decision.monthly_method_observation_ref)
    if not isinstance(policy,MonthlyMethodPolicy) or not isinstance(observation,MonthlyMethodObservation):
        raise ValueError('Monthly methods require their independently declared typed policy and actual observations')
    if (policy.organization_id!=reading.organization_id or observation.organization_id!=reading.organization_id
            or policy.role!=observation.role or action_id!=policy.role.upper()+'-A12'
            or policy.scope!=context.scope or observation.scope!=context.scope
            or observation.as_of!=context.business_time or state.as_of!=context.business_time or not policy.effective_window.contains(context.business_time)
            or policy.authority_ref!=decision.authority_ref or policy.authority_ref not in context.authorization_refs):
        raise ValueError('Monthly methods change original organization, action, authority, current clock or scope')
    # This mode neither asserts complete private learning/credential histories
    # nor applies formal training, qualification or judgment changes.
    if (decision.choice!='record_feedback' or state.coverage!='unknown' or capability.status!='unknown'
            or action_input.learning_profile_ref is not None or action_input.feedback_refs
            or getattr(action_input,'qualification_refs',[]) or state.received_feedback_refs or state.applied_feedback_refs
            or state.execution_refs or capability.verified_capability_codes or capability.qualification_refs):
        raise ValueError('Native monthly analysis cannot replace detailed private learning, qualifications or training')
    for ref in [*policy.evidence_refs,*observation.evidence_refs]:
        source=reading.resolve(ref)
        if not isinstance(source,EvidenceRecord) or (source.effective_window is not None and not source.effective_window.contains(context.business_time)):
            raise ValueError('Monthly method analysis lacks current original evidence')
    def number(value,unit):
        reading.resolve(value.basis_ref)
        result=Decimal(value.value)
        if value.unit!=unit or not 0<=result<=1:raise ValueError('Monthly method indices require bounded explicit units')
        return result
    pressure=number(observation.regulatory_pressure,'index')
    actual_capability=number(observation.native_capability,'native_capability_index')
    free=number(observation.native_free_ratio,'ratio')
    base=number(policy.baseline_requirement,'native_capability_index')
    weight=number(policy.regulatory_pressure_weight,'ratio')
    minimum=number(policy.minimum_shortfall,'native_capability_index')
    free_limit=number(policy.minimum_free_ratio,'ratio')
    required=min(Decimal(1),base+weight*pressure);shortfall=required-actual_capability
    history=observation.prior_own_outcomes
    if len({h['event_id'] for h in history})!=len(history) or any(
            h['micro_identity']['organization_id']!=reading.organization_id or h['micro_identity']['action_id']!=action_id
            or not 0<h['tick']<context.business_time.offset for h in history):
        raise ValueError('Monthly method analysis borrows another firm, role or future result')
    count=sum(h['participated'] for h in history)
    construction_reviews=None
    if (policy.construction_review is None)!=(observation.construction_results is None):
        raise ValueError('Construction feedback requires an explicit policy and unprefilled actual observations')
    if policy.construction_review is not None:
        if policy.design_review is not None or observation.design_results is not None or policy.qualification_maintenance_pressure is not None:
            raise ValueError('Construction feedback must remain separate from design and qualification modes')
        from src.actions.roles.professional_construction_feedback import review_construction
        construction_reviews=review_construction(observation.construction_results,policy.construction_review,
            organization_id=reading.organization_id,role=policy.role,run_id=context.run_id,tick=context.business_time.offset)
    if policy.qualification_maintenance_pressure is not None:
        if policy.role!='Engineer' or policy.design_review is not None or observation.design_results is not None:
            raise ValueError('Qualification background maintenance requires Engineer-only observations, separate from design feedback')
        threshold=number(policy.qualification_maintenance_pressure,'index')
        if any(h.get('operation') not in {'maintain_professional_qualifications','maintain_operations'} for h in history):
            raise ValueError('Qualification maintenance cannot count another background activity as an executed upkeep')
        pressure_gap=pressure-threshold
        participate=pressure_gap>=0 and free>=free_limit and count<policy.maximum_prior_improvements
        focus=policy.method_focus+'; observed regulatory pressure '+str(pressure)+'; upkeep pressure gap '+str(pressure_gap)
        interpretation=('Allocate background capacity to reviewing professional obligations and regional compliance knowledge.' if participate else
            'Defer another qualification-knowledge review after evaluating pressure, free capacity and actually executed earlier upkeep.')
        judgment=MonthlyMethodJudgment(role='Engineer',operation='maintain_professional_qualifications',participate=participate,
            regulatory_pressure=observation.regulatory_pressure,native_capability=observation.native_capability,
            native_free_ratio=observation.native_free_ratio,required_capability_index=str(required),capability_shortfall=str(shortfall),
            prior_actual_improvement_count=count,consumed_event_ids=[h['event_id'] for h in history],
            prior_method_focus=[h['method_focus'] for h in history if h['participated']],method_focus=focus,interpretation=interpretation,
            qualification_maintenance={'pressure_threshold':str(threshold),'pressure_gap':str(pressure_gap),
                'decision_basis':'regulatory_pressure_free_ratio_and_actual_prior_upkeep_count',
                'technical_capability_used_as_credential':False,'credential_status':'unknown','credential_effect_applied':False})
        reading.recheck()
        return judgment.model_dump_json()
    reviews=None
    if (policy.design_review is None)!=(observation.design_results is None):
        raise ValueError('Aggregate design review requires both an explicit policy and actual observations')
    if policy.design_review is not None:
        reviews=[];seen=set();limits=policy.design_review
        for result in observation.design_results:
            event=result.event;appointment=result.appointment_event;transition=result.coordination_transition
            role_field={'Architect':'architect_id','Engineer':'engineer_id'}[policy.role]
            if (result.project_id in seen or result.tick!=context.business_time.offset
                    or event.get('event_type')!='project_state_updated' or event.get('stage')!='design'
                    or event.get('project_id')!=result.project_id or event.get('tick')!=result.tick
                    or task_digest(event)!=result.event_sha256
                    or any(event['data'][k]!=getattr(result,k) for k in ('design_quality','information_quality'))
                    or event['data']['planned_cost']!=result.estimated_cost
                    or appointment.get('event_type')!='consultant_team_appointed'
                    or appointment.get('project_id')!=result.project_id or appointment.get('tick',result.tick+1)>result.tick
                    or appointment['data'].get(role_field)!=reading.organization_id
                    or result.appointment_identity.get('organization_id')!=reading.organization_id
                    or result.appointment_identity.get('action_id')!=policy.role.upper()+'-A03'
                    or task_digest(appointment)!=result.appointment_event_sha256
                    or transition.get('event_type')!='stage_transition' or transition.get('project_id')!=result.project_id
                    or transition['data'].get('to_stage')!='design' or transition.get('tick',result.tick+1)>result.tick
                    or task_digest(transition)!=result.coordination_transition_sha256):
                raise ValueError('Aggregate design result changes actual event, own appointment, coordination transition or clock')
            seen.add(result.project_id)
            design_gap=max(Decimal(0),Decimal(str(limits.minimum_design_quality))-Decimal(str(result.design_quality)))
            information_gap=max(Decimal(0),Decimal(str(limits.minimum_information_quality))-Decimal(str(result.information_quality)))
            ratio=Decimal(str(result.estimated_cost))/Decimal(str(result.initial_budget))
            cost_excess=max(Decimal(0),ratio-Decimal(str(limits.maximum_estimate_budget_ratio)))
            priority='cost_review' if cost_excess>0 else 'information_coordination' if information_gap>0 else 'design_review' if design_gap>0 else 'no_aggregate_gap'
            previous=[h for h in history if any(p['project_id']==result.project_id for p in h.get('design_review',[]) or [])]
            reviews.append({'project_id':result.project_id,'event_id':event['event_id'],'event_sha256':result.event_sha256,
                'design_gap':str(design_gap),'information_gap':str(information_gap),'estimate_budget_ratio':str(ratio),
                'cost_excess':str(cost_excess),'priority':priority,'needs_review':bool(design_gap or information_gap or cost_excess),
                'prior_review_event_ids':[p['event_id'] for h in previous for p in h['design_review'] if p['project_id']==result.project_id],
                'prior_executed_operation_ids':[h['event_id'] for h in previous if h['participated']]})
    design_need=any(r['needs_review'] for r in reviews or [])
    construction_need=any(r['needs_review'] for r in construction_reviews or [])
    participate=(shortfall>=minimum or design_need or construction_need) and free>=free_limit and count<policy.maximum_prior_improvements
    focus=policy.method_focus+'; observed regulatory pressure '+str(pressure)+'; native capability shortfall '+str(shortfall)
    if reviews:
        focus+='; aggregate design priorities '+', '.join(r['project_id']+':'+r['priority'] for r in reviews)
    if construction_reviews:
        focus+='; aggregate construction priorities '+', '.join(r['project_id']+':'+r['priority'] for r in construction_reviews)
    interpretation=('Allocate available background capacity to the sourced method-improvement focus.' if participate else
        'Defer a new background improvement after evaluating pressure, observed native capability, aggregate design gaps, free ratio and earlier actually executed improvements.')
    judgment=MonthlyMethodJudgment(role=policy.role,operation={'Architect':'improve_design_capability','Engineer':'improve_engineering_capability'}[policy.role],
        participate=participate,regulatory_pressure=observation.regulatory_pressure,native_capability=observation.native_capability,
        native_free_ratio=observation.native_free_ratio,required_capability_index=str(required),capability_shortfall=str(shortfall),
        prior_actual_improvement_count=count,consumed_event_ids=[h['event_id'] for h in history],
        prior_method_focus=[h['method_focus'] for h in history if h['participated']],method_focus=focus,interpretation=interpretation,
        design_review=reviews,construction_review=construction_reviews)
    reading.recheck()
    return judgment.model_dump_json()
