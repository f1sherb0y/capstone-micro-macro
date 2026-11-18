"""Private review thresholds and actual own selected-supplier observations."""
from typing import Literal
from pydantic import Field
from src.actions.contracts.common import StrictRecord,TextId,Measured,ScopeRef,TimeWindow,TimePoint,ref_type


class SupplierRelationshipReviewPolicy(StrictRecord):
    ref:ref_type('SupplierRelationshipReviewPolicy')
    organization_id:TextId
    scope:ScopeRef
    authority_ref:ref_type('Authorization')
    effective_window:TimeWindow
    minimum_reliability:Measured
    minimum_availability:Measured
    minimum_free_ratio:Measured
    purpose:Literal['private_future_bid_supplier_availability_review']
    evidence_refs:list[ref_type('Evidence')]=Field(min_length=1)


class SupplierRelationshipReviewObservation(StrictRecord):
    ref:ref_type('SupplierRelationshipReviewObservation')
    organization_id:TextId
    scope:ScopeRef
    as_of:TimePoint
    native_free_ratio:Measured
    selected_relationships:list[dict]
    prior_own_outcomes:list[dict]
    evidence_refs:list[ref_type('Evidence')]=Field(min_length=1)


class SupplierRelationshipReviewJudgment(StrictRecord):
    schema_version:Literal['contractor-supplier-review-judgment.v1']='contractor-supplier-review-judgment.v1'
    operation:Literal['maintain_supplier_relationship']='maintain_supplier_relationship'
    participate:bool
    assessments:list[dict]
    review_targets:list[dict]
    suppressed_targets:list[dict]
    prior_actual_reviews:list[dict]
    consumed_event_ids:list[TextId]
    consumed_micro_result_sha256:list[TextId]
    interpretation:TextId
