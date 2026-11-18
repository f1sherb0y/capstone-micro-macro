"""Original change, valuation, entitlement and independent determination records."""
from typing import Annotated, Literal

from pydantic import Field, model_validator

from src.actions.contracts.common import Money, TextId, TimePoint, TimeWindow, ValueState, ref_type
from src.actions.contracts.domain import common_projection_schemas
from src.actions.contracts.owner_study_objects import unique_refs
from src.actions.contracts.qs_cost_objects import CostSource
from src.actions.contracts.service_objects import ServiceUse, ServiceClockView, ServiceScopeCaseView, ServiceScopeProjectView, ServiceWorkScopeView
from src.methods.qs_change import ChangeLine


class ChangeAuthored(CostSource):
    author_actor_id: TextId
    author_function_ref: ref_type('FunctionAssignment')
    author_authority_ref: ref_type('Authorization')
    author_action_id: TextId
    authored_at: TimePoint


class QSChangeContractView(CostSource):
    ref: ref_type('Contract')
    party_ids: Annotated[list[TextId], Field(min_length=2)]
    currency: TextId
    decimal_places: Annotated[int, Field(ge=0, le=8)]
    valuation_actor_id: TextId
    valuation_organization_id: TextId
    valuation_function_ref: ref_type('FunctionAssignment')
    valuation_authority_ref: ref_type('Authorization')


class QSChangeClaimView(ChangeAuthored):
    ref: ref_type('ChangeClaim')
    contract_ref: ref_type('Contract')
    instruction_ref: ref_type('Instruction') | None
    claimant_id: TextId
    period: TimeWindow
    basis: Literal['incremental', 'cumulative']
    line_refs: list[ref_type('ChangeLine')]
    prior_statement_refs: list[ref_type('ValuationStatement')]
    prior_statement_count: Annotated[int, Field(ge=0)]
    question_refs: list[ref_type('EvidenceTarget')]
    unresolved_question_refs: list[ref_type('EvidenceTarget')]
    determination_basis_ref: ref_type('DeterminationBasis') | None
    status: Literal['submitted', 'withdrawn']

    @model_validator(mode='after')
    def originals(self):
        for refs in (self.line_refs, self.prior_statement_refs, self.question_refs, self.unresolved_question_refs):
            unique_refs(refs)
        if not set(self.unresolved_question_refs) <= set(self.question_refs):
            raise ValueError('Unresolved questions must be original claim questions')
        if self.basis == 'incremental' and self.prior_statement_refs:
            raise ValueError('Incremental claim cannot subtract cumulative history')
        if len(self.prior_statement_refs) != self.prior_statement_count:
            raise ValueError('Claim must carry the complete declared original prior statement history')
        return self


class QSChangeInstructionView(ChangeAuthored):
    ref: ref_type('Instruction')
    contract_ref: ref_type('Contract')
    claim_ref: ref_type('ChangeClaim')
    instruction_authority_ref: ref_type('Authority')


class QSChangeLineView(ChangeAuthored):
    ref: ref_type('ChangeLine')
    contract_ref: ref_type('Contract')
    claim_ref: ref_type('ChangeClaim')
    calculation_line: ChangeLine


class QSChangeStatementView(ChangeAuthored):
    ref: ref_type('ValuationStatement')
    contract_ref: ref_type('Contract')
    claim_ref: ref_type('ChangeClaim')
    calculation_ref: ref_type('MethodResult')
    sequence: Annotated[int, Field(ge=1)]
    period_delta: Money


class QSChangeResultView(ChangeAuthored):
    ref: ref_type('MethodResult')
    method_ref: ref_type('Method')
    contract_ref: ref_type('Contract')
    claim_ref: ref_type('ChangeClaim')
    input_sha256: TextId
    status: Literal['ok', 'failed', 'unsupported']
    assessed_amount: Money | None
    period_delta: Money | None


class QSChangeAuthorityView(CostSource):
    ref: ref_type('Authority')
    contract_ref: ref_type('Contract')
    claim_ref: ref_type('ChangeClaim')
    actor_id: TextId
    function_ref: ref_type('FunctionAssignment')
    purposes: list[Literal['instruct', 'entitlement', 'determine']]


class QSChangeEntitlementView(ChangeAuthored):
    ref: ref_type('EntitlementDecision')
    contract_ref: ref_type('Contract')
    claim_ref: ref_type('ChangeClaim')
    calculation_ref: ref_type('MethodResult') | None
    decision_authority_ref: ref_type('Authority')
    status: Literal['pending', 'decided']
    payer_id: ValueState[TextId]
    recognized_amount: ValueState[Money]
    disputed_amount: ValueState[Money]


class QSChangeDeterminationView(ChangeAuthored):
    ref: ref_type('DeterminationBasis')
    contract_ref: ref_type('Contract')
    claim_ref: ref_type('ChangeClaim')
    calculation_ref: ref_type('MethodResult')
    valuation_sha256: TextId
    actor_id: TextId
    function_ref: ref_type('FunctionAssignment')
    determination_authority_ref: ref_type('Authority')


class QSChangeQuestionView(CostSource):
    ref: ref_type('EvidenceTarget')
    contract_ref: ref_type('Contract')
    claim_ref: ref_type('ChangeClaim')
    issue: Literal['valuation', 'quantity', 'price', 'entitlement', 'delay_disruption']
    question: TextId
    recipient_ids: Annotated[list[TextId], Field(min_length=1)]
    blocking_uses: Annotated[list[ServiceUse], Field(min_length=1)]
    response_requirement_ref: ref_type('ResponseRequirement')


class QSChangeResponseView(CostSource):
    ref: ref_type('ResponseRequirement')
    contract_ref: ref_type('Contract')
    claim_ref: ref_type('ChangeClaim')
    recipient_ids: Annotated[list[TextId], Field(min_length=1)]


def qs_change_schemas():
    registry = common_projection_schemas()
    for kind, schema in {
        'Contract': QSChangeContractView, 'ChangeClaim': QSChangeClaimView,
        'Instruction': QSChangeInstructionView, 'ChangeLine': QSChangeLineView,
        'ValuationStatement': QSChangeStatementView, 'MethodResult': QSChangeResultView,
        'Authority': QSChangeAuthorityView, 'EntitlementDecision': QSChangeEntitlementView,
        'DeterminationBasis': QSChangeDeterminationView, 'EvidenceTarget': QSChangeQuestionView,
        'ResponseRequirement': QSChangeResponseView, 'ClockProfile': ServiceClockView,
        'OwnerCase': ServiceScopeCaseView, 'Project': ServiceScopeProjectView, 'WorkScope': ServiceWorkScopeView,
    }.items():
        registry.register_kind(kind, schema, str)
    return registry
