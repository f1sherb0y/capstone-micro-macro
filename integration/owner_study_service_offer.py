"""Independently declared initial offers for bounded, private research decisions.

This input is an assumed standing offer, never a fabricated professional action
result, received message, executed appointment or research report.
"""
from copy import deepcopy
from decimal import Decimal
from typing import Literal

from pydantic import model_validator

from integration.contractor_tender_development import ref, known
from src.actions.contracts.common import DecimalString, StrictRecord, TextId, ValueState
from src.coordination.tasks import TaskConflict, task_digest


class OwnerStudyServiceOfferPolicy(StrictRecord):
    source_declaration: Literal['independent_initial_standing_offer']
    provider_organization_id: TextId
    currency: Literal['HKD']
    fee_amount: ValueState[DecimalString]
    qualified: ValueState[bool]
    research_permitted: ValueState[bool]
    supported_question_codes: ValueState[list[TextId]]

    @model_validator(mode='after')
    def finite_fee_and_distinct_questions(self):
        if self.fee_amount.state == 'known':
            amount = Decimal(self.fee_amount.value)
            if not amount.is_finite() or amount < 0:
                raise ValueError('Standing research offer requires a finite nonnegative fee')
        if self.supported_question_codes.state == 'known':
            codes = self.supported_question_codes.value
            if len(set(codes)) != len(codes):
                raise ValueError('Standing research offer repeats a supported question')
        return self


def validate_service_offer_policy(policy):
    offer = policy.study_service_offer
    if offer is not None and (policy.study_question_code is None
            or offer.provider_organization_id not in (policy.cost_organization_id, policy.schedule_organization_id)
            or not policy.allow_scoped_template_authorizations):
        raise ValueError('Standing research offer requires an explicit question and original scoped professional mandate')


def prepare_study_service_offer(source, policy, objects, *, scope, issue, planning, candidate, now, window):
    """Project declared terms onto the exact unresolved question and original actor."""
    declaration = policy.study_service_offer
    if declaration is None:
        return [], [], None
    validate_service_offer_policy(policy)
    provider = declaration.provider_organization_id
    role = 'QS' if provider == policy.cost_organization_id else 'Architect'
    grants = [r['value'] for r in source['objects'] if r['ref']['kind'] == 'Authorization'
              and r['value']['organization_id'] == provider]
    if len(grants) != 1:
        raise TaskConflict('Standing research offer lacks its original independently declared professional mandate')
    grant = deepcopy(grants[0])
    function = grant['function_ref']
    assignment, = [deepcopy(r) for r in source['objects'] if r['ref'] == function]
    if assignment['value']['role'] != role:
        raise TaskConflict('Standing research offer changes its original professional function')
    rr = lambda kind, name: ref(kind, source['context'].operation_id + '-study-' + name)
    offer_ref, authority_ref, basis = (rr(k, n) for k, n in (
        ('ServiceOffer', 'declared-standing-offer'), ('Authorization', 'standing-offer'),
        ('Evidence', 'independent-standing-offer')))
    declaration_value = declaration.model_dump(mode='json')
    evidence = {'ref': basis, 'value': {'ref': basis, 'source_kind': 'synthetic', 'basis_kind': 'assumed',
        'locator': 'independent-initial-standing-research-offer-not-a-professional-action-receipt',
        'content_hash': task_digest(declaration_value), 'effective_window': None}}
    fee = deepcopy(declaration_value['fee_amount'])
    if fee['state'] == 'known':
        fee = known({'value': fee['value'], 'currency': declaration.currency, 'basis_ref': basis})
    grant.update(ref=authority_ref, action_ids=[role.upper() + '-A02'], scopes=[deepcopy(scope)],
                 readable_refs=[], basis_refs=[*grant['basis_refs'], basis])
    offer = {'ref': offer_ref, 'value': {'ref': offer_ref, 'evidence_refs': [basis],
        'provider_organization_id': provider, 'author_actor_id': grant['actor_id'],
        'author_function_ref': function, 'authority_ref': authority_ref,
        'authority_action_id': role.upper() + '-A02', 'client_organization_id': policy.organization_id,
        'payer_organization_id': policy.organization_id, 'case_ref': scope['ref'], 'scope': deepcopy(scope),
        'issue_refs': [issue], 'supported_question_codes': declaration_value['supported_question_codes'],
        'qualified': declaration_value['qualified'], 'research_permitted': declaration_value['research_permitted'],
        'fee': fee, 'window_ref': planning, 'status': 'offered', 'available_at': deepcopy(now),
        'effective_window': deepcopy(window)}}
    objects.extend([evidence, assignment, {'ref': authority_ref, 'value': grant}, offer])
    # The offer author's mandate does not disclose the owner's funding or load.
    grant['readable_refs'] = [basis, function, authority_ref, offer_ref]
    selected, = [r['value'] for r in objects if r['ref'] == candidate]
    selected.update(choice='commission', allocations=[], offer_ref=offer_ref,
                    future_cost=deepcopy(fee), evidence_refs=[*selected['evidence_refs'], basis])
    provenance = {'source_declaration': declaration.source_declaration,
        'declaration_sha256': task_digest(declaration_value), 'offer_ref': offer_ref,
        'provider_organization_id': provider, 'authority_ref': authority_ref,
        'boundary': 'assumed standing offer; private authorization only, no professional action or appointment receipt'}
    return [offer_ref], [grant], provenance
