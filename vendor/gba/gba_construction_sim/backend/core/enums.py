from enum import Enum


class ProjectStage(str, Enum):
    INITIATION = "initiation"
    FEASIBILITY = "feasibility"
    CONSULTANT_SELECTION = "consultant_selection"
    CONCEPT_DESIGN = "concept_design"
    DETAILED_DESIGN = "detailed_design"
    DESIGN = "design"
    STATUTORY_APPROVAL = "statutory_approval"
    APPROVAL = "approval"
    TENDER_PREPARATION = "tender_preparation"
    TENDERING = "tendering"
    BID_EVALUATION = "bid_evaluation"
    CONTRACT_AWARD = "contract_award"
    MOBILIZATION = "mobilization"
    CONSTRUCTION = "construction"
    COMPLETION = "completion"
    HANDOVER = "handover"
    FINAL_ACCOUNT = "final_account"
    CLOSED = "closed"
    SUSPENDED = "suspended"
    FAILED = "failed"


class EngagementStatus(str, Enum):
    NOT_INVOLVED = "not_involved"
    CANDIDATE = "candidate"
    INVITED = "invited"
    BIDDING = "bidding"
    ACTIVE = "active"
    STANDBY = "standby"
    RELEASED = "released"
    TERMINATED = "terminated"


class AgentMode(str, Enum):
    OUT_OF_PROJECT = "out_of_project"
    IN_PROJECT = "in_project"
    MIXED = "mixed"


class AgentRole(str, Enum):
    OWNER = "Owner"
    ARCHITECT = "Architect"
    ENGINEER = "Engineer"
    QS = "QS"
    CONTRACTOR = "Contractor"
    SUPPLIER = "Supplier"
    GOVERNMENT = "Government"
    BANK = "Bank"
