"""Evaluate optional constraints inside the original A01 processor, not its adapter."""
from src.actions.contracts.common import EvidenceRecord
from src.actions.contracts.professional_outreach import ProfessionalOutreachObservation
from src.methods.pricing import decimal_fraction


def outreach_constraint(context,reading,limits):
    if limits is None:return None
    observation=reading.resolve(limits.observation_ref)
    if (not isinstance(observation,ProfessionalOutreachObservation)
            or observation.organization_id!=reading.organization_id or observation.scope!=context.scope
            or observation.as_of!=context.business_time):
        raise ValueError('Outreach constraint changes original own scope or current observation')
    demand,minimum=observation.market_demand,limits.minimum_market_demand
    if demand.unit!='index' or minimum.unit!='index':
        raise ValueError('Outreach demand and threshold require original dimensionless index units')
    for ref in [*observation.evidence_refs,demand.basis_ref,minimum.basis_ref]:
        evidence=reading.resolve(ref)
        if not isinstance(evidence,EvidenceRecord) or evidence.content_hash is None:
            raise ValueError('Outreach needs current independently sourced evidence')
        if evidence.effective_window is not None and not evidence.effective_window.contains(context.business_time):
            raise ValueError('Outreach evidence is not current')
    actual,threshold=decimal_fraction(demand.value),decimal_fraction(minimum.value)
    if actual<0 or threshold<0:raise ValueError('Outreach index or minimum is negative')
    eligible=actual>=threshold and observation.prior_outreach_count<limits.maximum_prior_outreach
    note=(f'Original outreach constraint: market_demand={demand.value}, minimum={minimum.value}; '
        f'own earlier actual outreach={observation.prior_outreach_count}, limit={limits.maximum_prior_outreach}; eligible={eligible}')
    return eligible,note
