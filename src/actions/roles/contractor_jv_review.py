"""Original A01 eligibility plus a private public-candidate review priority."""
from copy import deepcopy
from decimal import Decimal
from src.actions.contracts.common import EvidenceRecord,Known
from src.actions.contracts.contractor_region_review import RegionalPartnerDisclosure
from src.actions.contracts.contractor_jv_review import JVPartnerReviewPolicy,JVPartnerReviewObservation,JVPartnerReviewJudgment


def analyze_jv_review(context,action_input,reading,*,profile,package,screening_choice,screening_note):
    policy=reading.resolve(profile.monthly_jv_policy_ref);observation=reading.resolve(profile.monthly_jv_observation_ref)
    org=reading.organization_id;now=context.business_time
    if not isinstance(policy,JVPartnerReviewPolicy) or not isinstance(observation,JVPartnerReviewObservation):
        raise ValueError('Exact typed JV candidate policy and current native observation required')
    if (context.scope.kind!='organization' or context.scope.ref.id!=org or policy.organization_id!=org or observation.organization_id!=org
            or policy.scope!=context.scope or observation.scope!=context.scope or observation.as_of!=now
            or policy.authority_ref not in context.authorization_refs or not policy.effective_window.contains(now)
            or policy.home_region!=observation.native_home_region or policy.home_region==policy.target_region
            or not isinstance(package.region_id,Known) or package.region_id.value!=policy.target_region
            or profile.outreach_limits is not None or package.access_mode!='public' or action_input.invitation_refs
            or screening_choice not in {'participate','decline'}):
        raise ValueError('JV candidate review changes own scope, current authority, original eligibility or public use')
    def evidence(ref):
        row=reading.resolve(ref)
        if not isinstance(row,EvidenceRecord) or row.content_hash is None or row.effective_window is None or not row.effective_window.contains(now):
            raise ValueError('JV review requires current received independent evidence')
    for ref in [*policy.evidence_refs,*observation.evidence_refs]:evidence(ref)
    def number(measure):
        evidence(measure.basis_ref);value=Decimal(measure.value)
        if measure.unit!='ratio' or not 0<=value<=1:raise ValueError('JV review only compares bounded dimensionless private priorities')
        return value
    friction=number(observation.native_friction);free=number(observation.native_free_ratio);free_limit=number(policy.minimum_free_ratio)
    if len({o.disclosure_ref.key() for o in policy.options})!=len(policy.options):raise ValueError('JV review repeats a public disclosure')
    candidates=[];seen=set()
    for option in policy.options:
        row=reading.resolve(option.disclosure_ref)
        if (not isinstance(row,RegionalPartnerDisclosure) or row.ref!=option.disclosure_ref or row.reviewing_organization_id!=org or row.scope!=context.scope
                or row.available_at.clock_ref!=now.clock_ref or row.available_at.offset>now.offset or not row.effective_window.contains(now)
                or row.partner_organization_id==org or row.partner_organization_id in seen):
            raise ValueError('JV public candidate changes its independent identity, receipt time or reviewing firm')
        seen.add(row.partner_organization_id)
        for ref in row.evidence_refs:evidence(ref)
        weight=number(option.regional_review_weight);effort=number(option.own_review_effort_ratio)
        eligible=policy.target_region in row.region_ids and isinstance(package.work_types,Known) and set(package.work_types.value)<=set(row.work_types)
        score=friction*weight-effort
        candidates.append({'partner_organization_id':row.partner_organization_id,'public_region_work_fit':eligible,
            'regional_review_weight':str(weight),'own_review_effort_ratio':str(effort),'private_review_priority':str(score)})
    candidates.sort(key=lambda c:(-Decimal(c['private_review_priority']),c['partner_organization_id']))
    eligible=[c for c in candidates if c['public_region_work_fit'] and Decimal(c['private_review_priority'])>0]
    preferred=eligible[0]['partner_organization_id'] if eligible and screening_choice=='participate' else None
    assessment={'home_region':policy.home_region,'target_region':policy.target_region,'screening_choice':screening_choice,
        'screening_note':screening_note,'native_friction':str(friction),'ranked_public_candidates':candidates,
        'preferred_private_review_candidate':preferred,'counterparty_consent':'unknown','committed_partner_capacity':'unknown',
        'formal_entry_permission':'unknown','joint_venture_formed':False,
        'priority_interpretation':'Own preliminary review priority; weights and effort are independent private assumptions, not promised risk transfer, actual mitigation or quoted money.'}
    previous=[];history=observation.prior_own_outcomes
    if len({h['event_id'] for h in history})!=len(history):raise ValueError('Duplicate JV execution history')
    for h in history:
        prior=JVPartnerReviewJudgment.model_validate(h['review']);identity=h['micro_identity']
        if (identity['organization_id']!=org or identity['run_id']!=context.run_id or identity['action_id']!='CONTRACTOR-A01'
                or not 0<h['tick']<now.offset or h['participated']!=prior.participate
                or h['operation']!=(prior.operation if prior.participate else 'maintain_operations')
                or h['assessment']!=prior.assessment):raise ValueError('JV review substitutes foreign, future or unexecuted candidate assessment')
        if h['participated']:previous.append(deepcopy(prior.assessment))
    unchanged=assessment in previous;participate=preferred is not None and free>=free_limit and not unchanged
    return JVPartnerReviewJudgment(participate=participate,screening_choice=screening_choice,screening_note=screening_note,
        native_friction=observation.native_friction,native_free_ratio=observation.native_free_ratio,assessment=assessment,
        prior_actual_assessments=previous,consumed_event_ids=[h['event_id'] for h in history],
        consumed_micro_result_sha256=[h['micro_result_sha256'] for h in history],unchanged_review=unchanged,
        interpretation=('Review the preferred public JV candidate for the privately assessed cross-region delivery risk-sharing opportunity.' if participate else
            'Retain the current JV search position after original eligibility, public candidate priorities, free ratio and earlier actual reviews.')+
            ' Private preliminary candidate review only; no contact, partner consent, JV agreement, committed capacity, transferred liability or actual risk reduction is inferred.')
