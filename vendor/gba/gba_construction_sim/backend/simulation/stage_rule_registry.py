from typing import Dict

from gba_construction_sim.backend.core.enums import ProjectStage
from gba_construction_sim.backend.models.stage_rule import StageRule


class StageRuleRegistry:
    def __init__(self) -> None:
        self.rules: Dict[ProjectStage, StageRule] = self._build_mvp_rules()

    def get(self, stage: ProjectStage) -> StageRule:
        return self.rules[stage]

    def _build_mvp_rules(self) -> Dict[ProjectStage, StageRule]:
        return {
            ProjectStage.INITIATION: StageRule(
                stage=ProjectStage.INITIATION,
                required_roles=["Owner"],
                allowed_actions={
                    "Owner": [
                        "evaluate_market_opportunity",
                        "initiate_project",
                        "define_project_scope",
                        "define_initial_budget",
                        "select_project_region",
                    ]
                },
                exit_conditions=["project_initiated"],
                next_stage=ProjectStage.DESIGN,
            ),
            ProjectStage.DESIGN: StageRule(
                stage=ProjectStage.DESIGN,
                required_roles=["Owner", "Architect", "QS"],
                allowed_actions={
                    "Architect": ["prepare_concept_design", "prepare_detailed_design", "revise_concept_design"],
                    "QS": ["prepare_cost_plan", "prepare_bill_of_quantities", "update_cost_estimate"],
                    "Owner": ["approve_concept_design", "request_design_revision"],
                },
                exit_conditions=["design_quality_threshold", "owner_approved_design"],
                next_stage=ProjectStage.APPROVAL,
            ),
            ProjectStage.APPROVAL: StageRule(
                stage=ProjectStage.APPROVAL,
                required_roles=["Owner", "Architect", "Government"],
                allowed_actions={
                    "Owner": ["submit_approval_application"],
                    "Architect": ["prepare_approval_documents", "revise_design_for_approval"],
                    "Government": ["review_submission", "approve", "reject", "request_revision"],
                },
                exit_conditions=["approval_approved"],
                failure_conditions=["approval_rejected"],
                next_stage=ProjectStage.TENDER_PREPARATION,
                rollback_stage=ProjectStage.DESIGN,
                release_roles_on_exit=["Government"],
                standby_roles_on_exit=["Architect"],
            ),
            ProjectStage.TENDER_PREPARATION: StageRule(
                stage=ProjectStage.TENDER_PREPARATION,
                required_roles=["Owner", "QS"],
                allowed_actions={
                    "Owner": ["approve_tender_documents", "define_procurement_strategy"],
                    "QS": ["prepare_tender_documents", "prepare_boq", "define_evaluation_criteria"],
                    "Architect": ["clarify_design_information"],
                },
                exit_conditions=["tender_documents_ready"],
                next_stage=ProjectStage.TENDERING,
            ),
            ProjectStage.TENDERING: StageRule(
                stage=ProjectStage.TENDERING,
                required_roles=["Owner", "QS", "Contractor"],
                allowed_actions={
                    "Owner": ["publish_tender", "invite_contractors"],
                    "QS": ["answer_tender_queries", "manage_tender_process"],
                    "Contractor": ["evaluate_tender", "decide_bid", "form_joint_venture", "submit_bid", "decline_bid"],
                },
                exit_conditions=["minimum_valid_bids"],
                failure_conditions=["tender_failed"],
                next_stage=ProjectStage.BID_EVALUATION,
                rollback_stage=ProjectStage.TENDER_PREPARATION,
            ),
            ProjectStage.BID_EVALUATION: StageRule(
                stage=ProjectStage.BID_EVALUATION,
                required_roles=["Owner", "QS", "Contractor"],
                allowed_actions={
                    "Owner": ["evaluate_technical_fit", "select_preferred_bidder"],
                    "QS": ["evaluate_bid_price", "evaluate_bid_compliance", "rank_bids"],
                    "Contractor": ["provide_clarification"],
                },
                exit_conditions=["preferred_bidder_selected"],
                next_stage=ProjectStage.CONTRACT_AWARD,
            ),
            ProjectStage.CONTRACT_AWARD: StageRule(
                stage=ProjectStage.CONTRACT_AWARD,
                required_roles=["Owner", "Contractor", "QS"],
                allowed_actions={
                    "Owner": ["award_contract", "negotiate_contract_terms"],
                    "Contractor": ["accept_contract", "negotiate_contract_terms"],
                    "QS": ["finalize_contract_sum"],
                },
                exit_conditions=["contract_signed"],
                next_stage=ProjectStage.CONSTRUCTION,
            ),
            ProjectStage.CONSTRUCTION: StageRule(
                stage=ProjectStage.CONSTRUCTION,
                required_roles=["Owner", "Contractor", "Supplier"],
                allowed_actions={
                    "Contractor": [
                        "execute_work",
                        "update_progress",
                        "request_payment",
                        "request_variation",
                        "submit_claim",
                        "respond_to_inspection",
                        "coordinate_supplier",
                    ],
                    "Supplier": ["deliver_materials", "report_supply_delay"],
                    "Owner": ["issue_variation", "approve_payment", "monitor_progress"],
                    "QS": ["evaluate_payment", "assess_variation_cost", "assess_claim"],
                    "Government": ["conduct_safety_inspection", "conduct_compliance_inspection"],
                    "Architect": ["clarify_design", "revise_design_for_variation"],
                },
                exit_conditions=["progress_complete", "quality_threshold"],
                failure_conditions=["serious_safety_or_quality_issue"],
                next_stage=ProjectStage.COMPLETION,
                rollback_stage=ProjectStage.TENDERING,
            ),
            ProjectStage.COMPLETION: StageRule(
                stage=ProjectStage.COMPLETION,
                required_roles=["Owner", "Contractor", "Government"],
                allowed_actions={
                    "Contractor": ["submit_completion_application", "complete_defect_rectification"],
                    "Government": ["conduct_final_inspection", "approve_completion"],
                    "Owner": ["accept_project", "request_rectification"],
                },
                exit_conditions=["completion_approved"],
                next_stage=ProjectStage.FINAL_ACCOUNT,
                release_roles_on_exit=["Government", "Supplier"],
            ),
            ProjectStage.FINAL_ACCOUNT: StageRule(
                stage=ProjectStage.FINAL_ACCOUNT,
                required_roles=["Owner", "Contractor", "QS"],
                allowed_actions={
                    "QS": ["prepare_final_account", "evaluate_claims", "settle_variations"],
                    "Contractor": ["submit_final_account", "negotiate_final_payment"],
                    "Owner": ["approve_final_account", "make_final_payment"],
                },
                exit_conditions=["final_account_settled"],
                next_stage=ProjectStage.CLOSED,
                release_roles_on_exit=["Contractor", "QS", "Architect", "Owner"],
            ),
            ProjectStage.CLOSED: StageRule(
                stage=ProjectStage.CLOSED,
                required_roles=[],
                allowed_actions={},
                next_stage=None,
            ),
            ProjectStage.SUSPENDED: StageRule(
                stage=ProjectStage.SUSPENDED,
                required_roles=[],
                allowed_actions={},
                next_stage=None,
            ),
            ProjectStage.FAILED: StageRule(
                stage=ProjectStage.FAILED,
                required_roles=[],
                allowed_actions={},
                next_stage=None,
            ),
        }
