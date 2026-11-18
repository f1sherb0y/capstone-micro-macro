"""Assemble original QS A07 change claims and independently saved valuations."""
from dataclasses import dataclass
from typing import ClassVar

from integration.qs_market_actions import QSMarketActionAssembler, PreparedQSMarket
from src.actions.contracts.common import EvidenceRecord
from src.actions.contracts.qs_change_objects import (
    QSChangeContractView, QSChangeClaimView, QSChangeInstructionView, QSChangeLineView,
    QSChangeStatementView, QSChangeResultView, QSChangeAuthorityView, QSChangeEntitlementView,
    QSChangeDeterminationView, QSChangeQuestionView, QSChangeResponseView, qs_change_schemas,
)
from src.actions.contracts.owner_study_objects import unique_refs
from src.coordination.tasks import TaskConflict


@dataclass(frozen=True)
class PreparedQSChange(PreparedQSMarket):
    ACTION_ID: ClassVar[str] = 'QS-A07'


class QSChangeActionAssembler(QSMarketActionAssembler):
    """Freeze supplied originals under the application's current read guard.

    Original arithmetic, complete cumulative history, entitlement amounts and
    independent determination authority remain processor checks. Assembly creates
    no successful valuation, recognized debt, payer, payment or contract effect.
    """
    ACTION_ID = 'QS-A07'
    SOURCE_SCHEMAS = staticmethod(qs_change_schemas)

    def build(self, context, *, scope, claim_or_change_ref, contract_ref,
            instruction_ref, evidence_refs, entitlement_ref, valuation_result_ref):
        return self._prepare_supplied_snapshot(context, input_values={
            'scope': scope, 'claim_or_change_ref': claim_or_change_ref,
            'contract_ref': contract_ref, 'instruction_ref': instruction_ref,
            'evidence_refs': evidence_refs, 'entitlement_ref': entitlement_ref,
            'valuation_result_ref': valuation_result_ref}, prepared_type=PreparedQSChange,
            validate_sources=validate_qs_change_sources)

    def prepare_calculation(self, context, *, calculation_ref, author_authority_ref,
            validate_current, **source_refs):
        """Prepare original change arithmetic under the caller's actual source guard."""
        from integration.qs_change_calculations import prepare_qs_change_calculation

        prepared = self.build(context, **source_refs)
        return prepare_qs_change_calculation(context=prepared.context, action_input=prepared.action_input,
            reading=prepared.reading, calculation_ref=calculation_ref,
            author_authority_ref=author_authority_ref, validate_current=validate_current)

    def publish_calculation(self, context, *, publications, next_context, read_guard,
            calculation_ref, author_authority_ref, validate_current, **source_refs):
        """Calculate once, save the execution, then publish under one source guard."""
        from integration.qs_change_calculation_publication import QSChangeCalculationPublicationStore
        from integration.qs_change_calculations import prepare_qs_change_calculation

        if (not isinstance(publications, QSChangeCalculationPublicationStore)
                or publications.registry is not self.registry or publications.organizations is not self.organizations
                or publications.methods is not self.methods or not callable(read_guard)):
            raise TaskConflict('Change publication requires original registries and the actual source writer guard')
        with read_guard(context):
            prepared = self.build(context, **source_refs)
            calculation = prepare_qs_change_calculation(context=prepared.context, action_input=prepared.action_input,
                reading=prepared.reading, calculation_ref=calculation_ref,
                author_authority_ref=author_authority_ref, validate_current=validate_current)
            if calculation['kind'] != 'prepared':
                return calculation
            record = publications.save(calculation, context=prepared.context,
                action_input=prepared.action_input, reading=prepared.reading)
            publication = publications.publish(record['record_sha256'],
                source_context=prepared.context, next_context=next_context)
            return {'kind': 'prepared', 'calculation': calculation, 'record': record, 'publication': publication}


def validate_qs_change_sources(action_input, *, context, organization_id, sources):
    """Check concrete original claim identities without deciding entitlement."""
    def read(ref, schema):
        row = sources.get(ref.key())
        if not isinstance(row, schema) or row.ref.key() != ref.key():
            raise TaskConflict('QS change lacks its exact original concrete source')
        if hasattr(row, 'scope') and row.scope != action_input.scope:
            raise TaskConflict('QS change source changes its original requested scope')
        return row

    if action_input.scope != context.scope:
        raise TaskConflict('QS change changes its original invocation scope')
    unique_refs(action_input.evidence_refs)
    contract = read(action_input.contract_ref, QSChangeContractView)
    claim = read(action_input.claim_or_change_ref, QSChangeClaimView)
    if (claim.contract_ref.key() != contract.ref.key() or claim.instruction_ref != action_input.instruction_ref
            or claim.claimant_id != claim.author_actor_id or claim.claimant_id not in contract.party_ids
            or contract.valuation_actor_id != context.actor_id
            or contract.valuation_organization_id != organization_id
            or contract.valuation_function_ref.key() != context.function_ref.key()):
        raise TaskConflict('QS change substitutes its original contract, claimant, instruction or valuation function')

    def related(ref, schema):
        row = read(ref, schema)
        if row.contract_ref.key() != contract.ref.key() or row.claim_ref.key() != claim.ref.key():
            raise TaskConflict('QS change source substitutes another original contract or claim version')
        return row

    def supplied_power(ref, row, purpose, actor=None, function=None):
        if ref.key() in sources:
            power = related(ref, QSChangeAuthorityView)
            if (power.actor_id != (actor or row.author_actor_id)
                    or power.function_ref != (function or row.author_function_ref)
                    or purpose not in power.purposes):
                raise TaskConflict('QS change power substitutes its original actor, function or purpose')

    for ref in action_input.evidence_refs:
        read(ref, EvidenceRecord)
    if action_input.instruction_ref is not None:
        instruction = related(action_input.instruction_ref, QSChangeInstructionView)
        supplied_power(instruction.instruction_authority_ref, instruction, 'instruct')
    if action_input.valuation_result_ref is not None:
        related(action_input.valuation_result_ref, QSChangeResultView)
    if action_input.entitlement_ref is not None:
        decision = related(action_input.entitlement_ref, QSChangeEntitlementView)
        supplied_power(decision.decision_authority_ref, decision, 'entitlement')
    for ref in claim.line_refs:
        if ref.key() in sources:
            related(ref, QSChangeLineView)
    for ref in claim.prior_statement_refs:
        if ref.key() not in sources:
            continue
        statement = read(ref, QSChangeStatementView)
        # Cumulative history retains the physical claim's earlier versions.
        if statement.contract_ref.key() != contract.ref.key() or statement.claim_ref.id != claim.ref.id:
            raise TaskConflict('QS prior statement borrows another contract or physical claim')
        if statement.calculation_ref.key() in sources:
            calculation = read(statement.calculation_ref, QSChangeResultView)
            if (calculation.contract_ref.key() != contract.ref.key()
                    or calculation.claim_ref.key() != statement.claim_ref.key()):
                raise TaskConflict('QS prior calculation changes its original statement claim version')
    for ref in claim.question_refs:
        if ref.key() not in sources:
            continue
        question = related(ref, QSChangeQuestionView)
        if question.response_requirement_ref.key() in sources:
            related(question.response_requirement_ref, QSChangeResponseView)
    if claim.determination_basis_ref is not None and claim.determination_basis_ref.key() in sources:
        basis = related(claim.determination_basis_ref, QSChangeDeterminationView)
        if basis.actor_id != context.actor_id or basis.function_ref != context.function_ref:
            raise TaskConflict('QS determination basis substitutes the acting QS function')
        supplied_power(basis.determination_authority_ref, basis, 'determine', context.actor_id, context.function_ref)
    # Missing valuation/evidence, original authors and dates, signed quantities,
    # arithmetic/digests, sequence completeness and monetary rights stay in the processor.
