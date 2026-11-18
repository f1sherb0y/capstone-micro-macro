"""Authorized private follow-up records for actual own selected collaboration parties."""
from typing import Literal
from pydantic import Field
from src.actions.contracts.common import StrictRecord,TextId,Measured,ScopeRef,TimePoint,TimeWindow,ValueState,ref_type
from src.actions.contracts.architect_monthly_portfolio import PortfolioEntry


class ClientRelationshipTask(StrictRecord):
    ref:ref_type('ClientRelationshipTask')
    organization_id:TextId
    scope:ScopeRef
    authority_ref:ref_type('Authorization')
    responsible_actor_id:TextId
    effective_window:TimeWindow
    permitted:ValueState[bool]
    allowed_party_roles:list[Literal['Owner','Engineer','QS']]=Field(min_length=1)
    allowed_party_ids:list[TextId]=Field(min_length=1)
    private_review_weight:Measured
    minimum_priority:Measured
    minimum_free_ratio:Measured
    review_interval_ticks:int=Field(ge=1,strict=True)
    purpose:Literal['internal_selected_client_and_consultant_followup_record']
    external_contact_consent:ValueState[bool]
    evidence_refs:list[ref_type('Evidence')]=Field(min_length=1)


class SelectedRelationshipParty(StrictRecord):
    organization_id:TextId
    role:Literal['Owner','Engineer','QS']
    selection:PortfolioEntry


class ClientRelationshipObservation(StrictRecord):
    ref:ref_type('ClientRelationshipObservation')
    organization_id:TextId
    scope:ScopeRef
    as_of:TimePoint
    market_demand:Measured
    native_free_ratio:Measured
    parties:list[SelectedRelationshipParty]
    prior_own_outcomes:list[dict]
    evidence_refs:list[ref_type('Evidence')]=Field(min_length=1)


class ClientRelationshipJudgment(StrictRecord):
    schema_version:Literal['architect-client-relationship-judgment.v1']='architect-client-relationship-judgment.v1'
    operation:Literal['maintain_client_relationship']='maintain_client_relationship'
    participate:bool
    market_demand:Measured
    private_priority:Measured
    priority_gate:bool
    capacity_gate:bool
    proposed_records:list[dict]
    updated_party_ids:list[TextId]
    not_due_party_ids:list[TextId]
    adopted_records:list[dict]
    consumed_monthly_event_ids:list[TextId]
    consumed_micro_result_sha256:list[TextId]
    interpretation:TextId
