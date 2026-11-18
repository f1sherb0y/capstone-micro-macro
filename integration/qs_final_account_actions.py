"""Assemble original QS A09 final-account histories and settlement evidence."""
from dataclasses import dataclass
from typing import ClassVar

from integration.qs_market_actions import QSMarketActionAssembler, PreparedQSMarket
from src.actions.contracts.qs_final_account_objects import (
    QSFinalContractView, QSFinalProfileView, QSFinalEntitlementView,
    QSFinalEntitlementAuthorityView, QSFinalCashExecutionView, QSFinalAdjustmentView,
    QSFinalAdjustmentBasisView, QSFinalResultView, QSFinalDeterminationView,
    QSFinalMechanismView, QSFinalConsentView, QSFinalPowerBasisView,
    QSFinalQuestionView, QSFinalResponseView, QSFinalExecutionView,
    QSPaymentCertificateView, QSPaymentStatementView, QSChangeClaimView,
    qs_final_account_schemas,
)
from src.actions.contracts.qs_payment_objects import QSPaymentReceiptView
from src.actions.contracts.owner_study_objects import unique_refs
from src.coordination.tasks import TaskConflict
from src.organization.registry import scope_covers


@dataclass(frozen=True)
class PreparedQSFinalAccount(PreparedQSMarket):
    ACTION_ID: ClassVar[str] = 'QS-A09'


class QSFinalAccountActionAssembler(QSMarketActionAssembler):
    """Freeze supplied originals under the application's current read guard.

    Original coverage, certificate history, cash reconciliation, adjustments and
    independently authorized settlement remain processor checks. Assembly creates
    no determined price, cash clearance or resolution of uncovered claims.
    """
    ACTION_ID = 'QS-A09'
    SOURCE_SCHEMAS = staticmethod(qs_final_account_schemas)

    def build(self, context, *, scope, contract_ref, determined_change_refs,
            certificate_refs, payment_receipt_refs, unresolved_claim_refs,
            reconciliation_result_ref):
        return self._prepare_supplied_snapshot(context, input_values={
            'scope': scope, 'contract_ref': contract_ref,
            'determined_change_refs': determined_change_refs, 'certificate_refs': certificate_refs,
            'payment_receipt_refs': payment_receipt_refs, 'unresolved_claim_refs': unresolved_claim_refs,
            'reconciliation_result_ref': reconciliation_result_ref}, prepared_type=PreparedQSFinalAccount,
            validate_sources=validate_qs_final_account_sources)

    def prepare_reconciliation(self, context, *, calculation_ref, author_authority_ref,
            validate_current, **source_refs):
        """Prepare the original registered reconciliation under the caller's source guard."""
        from integration.qs_final_account_calculations import prepare_qs_final_account_calculation

        prepared = self.build(context, **source_refs)
        return prepare_qs_final_account_calculation(context=prepared.context, action_input=prepared.action_input,
            reading=prepared.reading, calculation_ref=calculation_ref,
            author_authority_ref=author_authority_ref, validate_current=validate_current)

    def publish_reconciliation(self, context, *, publications, next_context, read_guard,
            calculation_ref, author_authority_ref, validate_current, **source_refs):
        """Calculate once, retain the original execution, then publish a fresh read point."""
        from integration.qs_final_account_calculation_publication import QSFinalAccountCalculationPublicationStore
        from integration.qs_final_account_calculations import prepare_qs_final_account_calculation

        if (not isinstance(publications, QSFinalAccountCalculationPublicationStore)
                or publications.registry is not self.registry or publications.organizations is not self.organizations
                or publications.methods is not self.methods or not callable(read_guard)):
            raise TaskConflict('Final reconciliation publication requires original registries and actual source writer guard')
        with read_guard(context):
            prepared = self.build(context, **source_refs)
            calculation = prepare_qs_final_account_calculation(context=prepared.context, action_input=prepared.action_input,
                reading=prepared.reading, calculation_ref=calculation_ref,
                author_authority_ref=author_authority_ref, validate_current=validate_current)
            if calculation['kind'] != 'prepared':
                return calculation
            record = publications.save(calculation, context=prepared.context,
                action_input=prepared.action_input, reading=prepared.reading)
            publication = publications.publish(record['record_sha256'],
                source_context=prepared.context, next_context=next_context)
            return {'kind': 'prepared', 'calculation': calculation, 'record': record, 'publication': publication}


def validate_qs_final_account_sources(action_input, *, context, organization_id, sources):
    """Check original contract associations without declaring obligations cleared."""
    def read(ref, schema):
        row = sources.get(ref.key())
        if not isinstance(row, schema) or row.ref.key() != ref.key():
            raise TaskConflict('QS final account lacks its exact original concrete source')
        if not scope_covers(action_input.scope, row.scope):
            raise TaskConflict('QS final account source expands its original requested scope')
        return row

    if action_input.scope != context.scope:
        raise TaskConflict('QS final account changes its original invocation scope')
    for refs in (action_input.determined_change_refs, action_input.certificate_refs,
            action_input.payment_receipt_refs, action_input.unresolved_claim_refs):
        unique_refs(refs)
    contract = read(action_input.contract_ref, QSFinalContractView)
    profile = read(contract.final_profile_ref, QSFinalProfileView)
    if (contract.valuation_organization_id != organization_id or contract.valuation_actor_id != context.actor_id
            or contract.valuation_function_ref != context.function_ref or profile.contract_ref != contract.ref
            or profile.author_organization_id != organization_id or profile.actor_id != context.actor_id
            or profile.function_ref != context.function_ref or profile.scope != context.scope
            or profile.authority_ref not in context.authorization_refs):
        raise TaskConflict('QS final account substitutes its original contract, firm, function or current authority')

    def related(ref, schema):
        row = read(ref, schema)
        if row.contract_ref != contract.ref:
            raise TaskConflict('QS final account source substitutes another original contract version')
        return row

    def supplied_mechanism(ref):
        if ref.key() not in sources:
            return
        mechanism = related(ref, QSFinalMechanismView)
        if mechanism.power_basis_ref is not None and mechanism.power_basis_ref.key() in sources:
            power = related(mechanism.power_basis_ref, QSFinalPowerBasisView)
            if power.mechanism_ref != mechanism.ref:
                raise TaskConflict('QS settlement power substitutes another original mechanism')
        for consent_ref in mechanism.party_consent_refs:
            if consent_ref.key() in sources:
                consent = related(consent_ref, QSFinalConsentView)
                if (consent.mechanism_ref != mechanism.ref or consent.party_id != consent.author_actor_id
                        or consent.party_id not in contract.party_ids):
                    raise TaskConflict('QS settlement consent substitutes its original mechanism or contract party')

    for ref in action_input.determined_change_refs:
        change = related(ref, QSFinalEntitlementView)
        if change.decision_authority_ref.key() in sources:
            power = related(change.decision_authority_ref, QSFinalEntitlementAuthorityView)
            if (power.claim_ref != change.claim_ref or power.actor_id != change.author_actor_id
                    or power.function_ref != change.author_function_ref):
                raise TaskConflict('QS final entitlement power substitutes its original claim or author')
    for ref in action_input.unresolved_claim_refs:
        related(ref, QSChangeClaimView)
    for ref in action_input.certificate_refs:
        certificate = related(ref, QSPaymentCertificateView)
        if certificate.statement_ref.key() in sources:
            statement = related(certificate.statement_ref, QSPaymentStatementView)
            if statement.certificate_ref != certificate.ref or statement.calculation_ref != certificate.calculation_ref:
                raise TaskConflict('QS final certificate substitutes its original statement or calculation')
    for ref in action_input.payment_receipt_refs:
        receipt = related(ref, QSPaymentReceiptView)
        if receipt.payer_id != contract.payer_id or receipt.beneficiary_id != contract.beneficiary_id:
            raise TaskConflict('QS final payment receipt substitutes its original payer or beneficiary')
        if receipt.execution_ref.key() in sources:
            related(receipt.execution_ref, QSFinalCashExecutionView)
    for ref in contract.payment_execution_refs:
        if ref.key() in sources:
            execution = related(ref, QSFinalCashExecutionView)
            if execution.run_id != context.run_id:
                raise TaskConflict('QS final cash execution substitutes another run')
    for ref in contract.adjustment_refs:
        if ref.key() not in sources:
            continue
        adjustment = related(ref, QSFinalAdjustmentView)
        if adjustment.authority_ref.key() in sources:
            basis = related(adjustment.authority_ref, QSFinalAdjustmentBasisView)
            if basis.adjustment_ref != adjustment.ref or basis.kind != adjustment.kind:
                raise TaskConflict('QS final adjustment basis substitutes its original adjustment or kind')
            supplied_mechanism(basis.mechanism_ref)
    for ref in profile.question_refs:
        if ref.key() not in sources:
            continue
        question = related(ref, QSFinalQuestionView)
        if question.response_requirement_ref.key() in sources:
            related(question.response_requirement_ref, QSFinalResponseView)
    if action_input.reconciliation_result_ref is not None:
        related(action_input.reconciliation_result_ref, QSFinalResultView)
    if profile.determination_basis_ref is not None and profile.determination_basis_ref.key() in sources:
        basis = related(profile.determination_basis_ref, QSFinalDeterminationView)
        supplied_mechanism(basis.mechanism_ref)
    for ref in contract.execution_refs:
        if ref.key() in sources:
            execution = read(ref, QSFinalExecutionView)
            # An earlier contract projection may own an existing business execution.
            if execution.contract_ref.id != contract.ref.id or execution.run_id != context.run_id:
                raise TaskConflict('QS final account execution substitutes its physical contract or run')
            if execution.profile_ref.key() in sources:
                original = read(execution.profile_ref, QSFinalProfileView)
                if (original.contract_ref != execution.contract_ref or original.scope != execution.scope
                        or original.business_key != execution.business_key
                        or original.author_organization_id != organization_id):
                    raise TaskConflict('QS final account execution substitutes its exact original profile contract, scope or business')
    # Current coverage, historic authority, complete sets/chains, execution waits,
    # unknown cash, exact arithmetic/digests and settlement permission stay in the processor.
