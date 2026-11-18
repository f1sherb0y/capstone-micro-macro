"""Private preliminary regional review; independent public candidate disclosures."""
from typing import Literal
from src.actions.contracts.common import StrictRecord,TextId,Measured,ScopeRef,TimeWindow,TimePoint,ref_type


class RegionalPartnerDisclosure(StrictRecord):
    ref:ref_type('RegionalPartnerDisclosure')
    reviewing_organization_id:TextId
    partner_organization_id:TextId
    scope:ScopeRef
    available_at:TimePoint
    effective_window:TimeWindow
    region_ids:list[TextId]
    work_types:list[TextId]
    disclosure_use:Literal['public_preliminary_candidate_review']
    evidence_refs:list[ref_type('Evidence')]


class RegionEntryReviewPolicy(StrictRecord):
    ref:ref_type('RegionEntryReviewPolicy')
    organization_id:TextId
    scope:ScopeRef
    authority_ref:ref_type('Authorization')
    effective_window:TimeWindow
    home_region:TextId
    target_region:TextId
    maximum_friction:Measured
    minimum_free_ratio:Measured
    partner_disclosure_refs:list[ref_type('RegionalPartnerDisclosure')]
    purpose:Literal['preliminary_qualification_and_local_partner_review']
    evidence_refs:list[ref_type('Evidence')]


class RegionEntryReviewObservation(StrictRecord):
    ref:ref_type('RegionEntryReviewObservation')
    organization_id:TextId
    scope:ScopeRef
    as_of:TimePoint
    native_home_region:TextId
    native_friction:Measured
    native_free_ratio:Measured
    prior_own_outcomes:list[dict]
    evidence_refs:list[ref_type('Evidence')]


class RegionEntryReviewJudgment(StrictRecord):
    schema_version:Literal['contractor-region-review-judgment.v1']='contractor-region-review-judgment.v1'
    operation:Literal['evaluate_region_entry']='evaluate_region_entry'
    participate:bool
    screening_choice:Literal['participate','decline']
    screening_note:TextId
    native_friction:Measured
    native_free_ratio:Measured
    friction_margin:str
    assessment:dict
    prior_actual_assessments:list[dict]
    consumed_event_ids:list[TextId]
    consumed_micro_result_sha256:list[TextId]
    unchanged_review:bool
    interpretation:TextId
