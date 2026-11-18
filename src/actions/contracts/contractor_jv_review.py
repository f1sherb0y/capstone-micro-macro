"""Private JV candidate priority hypotheses; no partner agreement or promise."""
from typing import Literal
from pydantic import Field
from src.actions.contracts.common import StrictRecord,TextId,Measured,ScopeRef,TimeWindow,TimePoint,ref_type


class JVReviewOption(StrictRecord):
    disclosure_ref:ref_type('RegionalPartnerDisclosure')
    regional_review_weight:Measured
    own_review_effort_ratio:Measured


class JVPartnerReviewPolicy(StrictRecord):
    ref:ref_type('JVPartnerReviewPolicy')
    organization_id:TextId
    scope:ScopeRef
    authority_ref:ref_type('Authorization')
    effective_window:TimeWindow
    home_region:TextId
    target_region:TextId
    minimum_free_ratio:Measured
    options:list[JVReviewOption]=Field(min_length=1)
    purpose:Literal['private_cross_region_risk_sharing_candidate_review']
    evidence_refs:list[ref_type('Evidence')]=Field(min_length=1)


class JVPartnerReviewObservation(StrictRecord):
    ref:ref_type('JVPartnerReviewObservation')
    organization_id:TextId
    scope:ScopeRef
    as_of:TimePoint
    native_home_region:TextId
    native_friction:Measured
    native_free_ratio:Measured
    prior_own_outcomes:list[dict]
    evidence_refs:list[ref_type('Evidence')]=Field(min_length=1)


class JVPartnerReviewJudgment(StrictRecord):
    schema_version:Literal['contractor-jv-review-judgment.v1']='contractor-jv-review-judgment.v1'
    operation:Literal['seek_joint_venture_partner']='seek_joint_venture_partner'
    participate:bool
    screening_choice:Literal['participate','decline']
    screening_note:TextId
    native_friction:Measured
    native_free_ratio:Measured
    assessment:dict
    prior_actual_assessments:list[dict]
    consumed_event_ids:list[TextId]
    consumed_micro_result_sha256:list[TextId]
    unchanged_review:bool
    interpretation:TextId
