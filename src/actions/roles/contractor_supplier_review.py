"""Original A05 inquiry preparation plus own actual relationship risk review."""
from copy import deepcopy
from decimal import Decimal
from src.actions.contracts.common import EvidenceRecord,Measured
from src.actions.contracts.contractor_supplier_review import SupplierRelationshipReviewPolicy,SupplierRelationshipReviewObservation,SupplierRelationshipReviewJudgment


def analyze_supplier_review(context,reading,*,profile,supplier_ids):
    policy=reading.resolve(profile.monthly_supplier_policy_ref);observed=reading.resolve(profile.monthly_supplier_observation_ref)
    org=reading.organization_id;now=context.business_time
    if not isinstance(policy,SupplierRelationshipReviewPolicy) or not isinstance(observed,SupplierRelationshipReviewObservation):
        raise ValueError('Monthly supplier review needs exact typed sources')
    if (context.scope.kind!='organization' or context.scope.ref.id!=org or policy.scope!=context.scope or observed.scope!=context.scope
            or policy.organization_id!=org or observed.organization_id!=org or observed.as_of!=now
            or policy.authority_ref not in context.authorization_refs or not policy.effective_window.contains(now)):
        raise ValueError('Supplier review changes actual own scope, time or authority')
    def evidence(ref):
        e=reading.resolve(ref)
        if not isinstance(e,EvidenceRecord) or e.content_hash is None or e.effective_window is None or not e.effective_window.contains(now):
            raise ValueError('Supplier review lacks current bound evidence')
    def number(m):
        m=Measured.model_validate(m)
        evidence(m.basis_ref);v=Decimal(m.value)
        if m.unit!='ratio' or not 0<=v<=1:raise ValueError('Supplier review only uses bounded normalized indicators')
        return v
    for ref in [*policy.evidence_refs,*observed.evidence_refs]:evidence(ref)
    reliability_limit=number(policy.minimum_reliability);availability_limit=number(policy.minimum_availability)
    free=number(observed.native_free_ratio);free_limit=number(policy.minimum_free_ratio)
    prior=[];history=observed.prior_own_outcomes
    if len({h['event_id'] for h in history})!=len(history):raise ValueError('Repeated supplier review event')
    for h in history:
        j=SupplierRelationshipReviewJudgment.model_validate(h['review']);i=h['micro_identity']
        if (i['organization_id']!=org or i['run_id']!=context.run_id or i['action_id']!='CONTRACTOR-A05'
                or not 0<h['tick']<now.offset or h['participated']!=j.participate
                or h['operation']!=(j.operation if j.participate else 'maintain_operations')):
            raise ValueError('Supplier review consumes foreign, future or unexecuted history')
        if h['participated']:prior.extend(deepcopy(j.review_targets))
    assessments=[];targets=[];suppressed=[];seen=set()
    for row in observed.selected_relationships:
        origin=row['selection'];sid=origin['supplier_id']
        if (origin['contractor_id']!=org or sid not in supplier_ids or not 0<origin['tick']<now.offset
                or origin['event_id'] in seen or not origin['micro_result_sha256'] or not origin['micro_task_key']):
            raise ValueError('Supplier review needs an eligible independently prepared recipient and strictly earlier own actual selection')
        seen.add(origin['event_id'])
        reliability=number(row['native_reliability']);availability=number(row['native_material_availability'])
        issues=[]
        if reliability<reliability_limit:issues.append('normalized_reliability_below_private_threshold')
        if availability<availability_limit:issues.append('aggregate_material_availability_below_private_threshold')
        key={'selection_event_id':origin['event_id'],'project_id':origin['project_id'],'supplier_id':sid,'issues':issues}
        already=any(p['review_key']==key for p in prior)
        assessment={'selection':deepcopy(origin),'native_reliability':row['native_reliability'],'native_material_availability':row['native_material_availability'],
            'reliability_shortfall':str(max(Decimal(0),reliability_limit-reliability)),
            'availability_shortfall':str(max(Decimal(0),availability_limit-availability)),
            'review_key':key,'already_actually_reviewed':already}
        assessments.append(assessment)
        if issues and already:suppressed.append(deepcopy(assessment))
        if issues and not already and free>=free_limit:targets.append(deepcopy(assessment))
    return SupplierRelationshipReviewJudgment(participate=bool(targets),assessments=assessments,review_targets=targets,
        suppressed_targets=suppressed,prior_actual_reviews=prior,consumed_event_ids=[h['event_id'] for h in history],
        consumed_micro_result_sha256=[h['micro_result_sha256'] for h in history],
        interpretation=('Review actual selected suppliers with new reliability/material availability concerns for future bids.' if targets else
            'Retain supplier review position after actual selection history, normalized indicators and confirmed earlier assessments.')+
            ' Internal preliminary review and independently authorized future inquiry preparation only; no message delivery, consent, physical stock, remaining contractual obligations or changed supply terms is inferred.')
