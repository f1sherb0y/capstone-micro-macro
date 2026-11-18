"""Extend the original A01 eligibility result with a bounded regional review."""
from copy import deepcopy
from decimal import Decimal
from src.actions.contracts.common import EvidenceRecord,Known
from src.actions.contracts.contractor_region_review import RegionEntryReviewPolicy,RegionEntryReviewObservation,RegionEntryReviewJudgment,RegionalPartnerDisclosure


def analyze_region_review(context,action_input,reading,*,profile,package,screening_choice,screening_note):
    policy=reading.resolve(profile.monthly_region_policy_ref);observation=reading.resolve(profile.monthly_region_observation_ref)
    org=reading.organization_id;now=context.business_time
    if not isinstance(policy,RegionEntryReviewPolicy) or not isinstance(observation,RegionEntryReviewObservation):
        raise ValueError('Exact typed regional policy and current observations required')
    if (context.scope.kind!='organization' or context.scope.ref.id!=org or policy.organization_id!=org or observation.organization_id!=org
            or policy.scope!=context.scope or observation.scope!=context.scope or observation.as_of!=now
            or policy.authority_ref not in context.authorization_refs or not policy.effective_window.contains(now)
            or policy.home_region!=observation.native_home_region or policy.home_region==policy.target_region
            or not isinstance(package.region_id,Known) or package.region_id.value!=policy.target_region
            or profile.outreach_limits is not None or package.access_mode!='public' or action_input.invitation_refs
            or screening_choice not in {'participate','decline'}):
        raise ValueError('Regional review changes own authorization, current scope, target or preliminary public use')
    def evidence(ref):
        row=reading.resolve(ref)
        if not isinstance(row,EvidenceRecord) or row.content_hash is None or row.effective_window is None or not row.effective_window.contains(now):
            raise ValueError('Regional review requires received current evidence')
    for ref in [*policy.evidence_refs,*observation.evidence_refs]:evidence(ref)
    def number(measure):
        evidence(measure.basis_ref);value=Decimal(measure.value)
        if measure.unit!='ratio' or not 0<=value<=1:raise ValueError('Regional friction and background resources are bounded ratios')
        return value
    friction=number(observation.native_friction);limit=number(policy.maximum_friction)
    free=number(observation.native_free_ratio);free_limit=number(policy.minimum_free_ratio)
    disclosures=[reading.resolve(ref) for ref in policy.partner_disclosure_refs]
    if not disclosures or len({ref.key() for ref in policy.partner_disclosure_refs})!=len(disclosures):
        raise ValueError('Explicit nonduplicate public local partner disclosures required')
    candidates=[]
    for row in disclosures:
        if (not isinstance(row,RegionalPartnerDisclosure) or row.reviewing_organization_id!=org or row.scope!=context.scope
                or row.available_at.clock_ref!=now.clock_ref or row.available_at.offset>now.offset or not row.effective_window.contains(now)
                or row.partner_organization_id==org):raise ValueError('Local partner disclosure changes its reviewing organization, source or receipt time')
        for ref in row.evidence_refs:evidence(ref)
        if policy.target_region in row.region_ids and isinstance(package.work_types,Known) and set(package.work_types.value)<=set(row.work_types):
            candidates.append(row.partner_organization_id)
    if len(candidates)!=len(set(candidates)):raise ValueError('Regional review repeats a public partner identity')
    assessment={'home_region':policy.home_region,'target_region':policy.target_region,'screening_choice':screening_choice,
        'screening_note':screening_note,'public_local_partner_candidates':sorted(candidates),
        'preliminary_fit':screening_choice=='participate' and bool(candidates),
        'friction_within_private_limit':friction<=limit,
        'formal_entry_permission':'unknown','counterparty_consent':'unknown','joint_venture_formed':False}
    history=observation.prior_own_outcomes;previous=[]
    if len({h['event_id'] for h in history})!=len(history):raise ValueError('Duplicate regional execution history')
    for h in history:
        identity=h['micro_identity'];prior=RegionEntryReviewJudgment.model_validate(h['review'])
        if (identity['organization_id']!=org or identity['run_id']!=context.run_id or identity['action_id']!='CONTRACTOR-A01'
                or not 0<h['tick']<now.offset or h['participated']!=prior.participate
                or h['operation']!=(prior.operation if prior.participate else 'maintain_operations')
                or h['assessment']!=prior.assessment):raise ValueError('Regional review substitutes foreign, future or unexecuted assessment')
        if h['participated']:previous.append(deepcopy(prior.assessment))
    unchanged=assessment in previous
    participate=friction<=limit and free>=free_limit and not unchanged
    return RegionEntryReviewJudgment(participate=participate,screening_choice=screening_choice,screening_note=screening_note,
        native_friction=observation.native_friction,native_free_ratio=observation.native_free_ratio,friction_margin=str(limit-friction),
        assessment=assessment,prior_actual_assessments=previous,consumed_event_ids=[h['event_id'] for h in history],
        consumed_micro_result_sha256=[h['micro_result_sha256'] for h in history],unchanged_review=unchanged,
        interpretation=('Review the original target-region qualification, work-method and capacity result with the declared public local partner candidates.' if participate else
            'Retain the existing regional position after checking current native friction, free ratio and earlier actually executed assessment.')+
            ' Preliminary private review only; no legal market entry, partner consent, JV, outreach, bid, resource reservation or financial commitment is created.')
