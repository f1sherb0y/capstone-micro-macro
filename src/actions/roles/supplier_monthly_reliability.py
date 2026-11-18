"""Original A05 validates backup inquiry inputs, then evaluates actual readiness."""
from copy import deepcopy
from decimal import Decimal
from src.actions.contracts.common import EvidenceRecord
from src.actions.contracts.supplier_monthly_reliability import SupplyReliabilityPolicy,SupplyReliabilityObservation,SupplyReliabilityJudgment


def analyze_reliability_review(context,action_input,reading,*,profile,mandate,inventory,capacity,request):
    policy=reading.resolve(profile.monthly_reliability_policy_ref);observation=reading.resolve(profile.monthly_reliability_observation_ref)
    org=reading.organization_id;now=context.business_time
    if not isinstance(policy,SupplyReliabilityPolicy) or not isinstance(observation,SupplyReliabilityObservation):
        raise ValueError('Typed reliability policy and actual observations are both required')
    if (policy.organization_id!=org or observation.organization_id!=org or policy.scope!=context.scope or observation.scope!=context.scope
            or context.scope.kind!='organization' or context.scope.ref.id!=org or observation.as_of!=now
            or not policy.effective_window.contains(now) or policy.authority_ref!=profile.authority_ref
            or policy.authority_ref not in context.authorization_refs):
        raise ValueError('Reliability review replaces current own scope, authority or time')
    if (profile.choice!='request_quote' or mandate.order_ref is not None or mandate.speculative_authority_ref is None
            or mandate.order_line_refs or inventory.coverage!='unknown' or inventory.lots
            or capacity.resource_coverage!='unknown' or capacity.commitment_coverage!='unknown' or capacity.resources or capacity.commitments
            or action_input.upstream_offer_refs or request['supplier_ids']!=profile.supplier_ids
            or request['required_lines']!=[line.model_dump(mode='python') for line in profile.required_lines]):
        raise ValueError('Background review cannot fabricate orders, stock, actual upstream offers or physical commitments')
    for ref in [*policy.evidence_refs,*observation.evidence_refs]:
        source=reading.resolve(ref)
        if not isinstance(source,EvidenceRecord) or source.content_hash is None or (
                source.effective_window is not None and not source.effective_window.contains(now)):
            raise ValueError('Reliability review requires current received evidence')
    def number(measure,unit):
        reading.resolve(measure.basis_ref);value=Decimal(measure.value)
        if measure.unit!=unit or not 0<=value<=1:raise ValueError('Reliability review uses bounded native indices and ratios, never physical quantities')
        return value
    actual=number(observation.native_reliability,'native_reliability_index')
    target=number(policy.target_native_reliability,'native_reliability_index')
    minimum=number(policy.minimum_shortfall,'native_reliability_index')
    free=number(observation.native_free_ratio,'ratio');free_limit=number(policy.minimum_free_ratio,'ratio')
    history=observation.prior_own_outcomes
    if len({h['event_id'] for h in history})!=len(history) or any(
            h['micro_identity']['organization_id']!=org or h['micro_identity']['run_id']!=context.run_id
            or h['micro_identity']['action_id']!='SUPPLIER-A05' or not 0<h['tick']<now.offset for h in history):
        raise ValueError('Reliability review consumes another firm, run, action or future outcome')
    previous=[]
    for h in history:
        prior=SupplyReliabilityJudgment.model_validate(h['review'])
        if (h['participated']!=prior.participate or h['operation']!=(prior.operation if prior.participate else 'maintain_operations')
                or h['backup_request']!=prior.current_backup_request):
            raise ValueError('Earlier backup request lacks its exact actually executed review')
        if h['participated']:previous.append(deepcopy(h['backup_request']))
    count=sum(h['participated'] for h in history);shortfall=target-actual
    participate=shortfall>=minimum and free>=free_limit and count<policy.maximum_prior_reviews
    # This is a private request candidate. Native monthly acceptance commits a
    # review activity, never sends the request or creates an upstream order.
    return SupplyReliabilityJudgment(participate=participate,native_reliability=observation.native_reliability,
        native_free_ratio=observation.native_free_ratio,target_native_reliability=policy.target_native_reliability,
        reliability_shortfall=str(shortfall),prior_actual_review_count=count,
        consumed_event_ids=[h['event_id'] for h in history],consumed_micro_result_sha256=[h['micro_result_sha256'] for h in history],
        prior_backup_requests=previous,current_backup_request=deepcopy(request),interpretation=(
            'Review the independently authorized own-risk backup inquiry candidate against observed native reliability and available background capacity.' if participate else
            'Retain the existing background sourcing position after checking current reliability, free ratio and earlier actually executed backup reviews.')+
            ' Private inquiry candidate only; no sent message, accepted offer, changed inventory, physical logistics improvement or completed supply is inferred.')
