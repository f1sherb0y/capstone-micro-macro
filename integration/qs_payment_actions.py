"""Assemble original QS A08 work, certificate history and payment evidence."""
from dataclasses import dataclass
from typing import ClassVar

from integration.qs_market_actions import QSMarketActionAssembler, PreparedQSMarket
from src.actions.contracts.qs_payment_objects import (
    QSPaymentContractView, QSPaymentApplicationView, QSPaymentWorkView,
    QSPaymentRateView, QSPaymentConditionView, QSPaymentResultView,
    QSPaymentCertificateView, QSPaymentStatementView, QSPaymentAdjustmentView,
    QSPaymentCreditView, QSPaymentCreditAllocation, QSPaymentReceiptView,
    QSPaymentExecutionView, QSPaymentAuthorityView, QSPaymentCertificationView,
    QSPaymentCorrectionView, QSPaymentQuestionView, QSPaymentResponseView,
    qs_payment_schemas,
)
from src.actions.contracts.owner_study_objects import unique_refs
from src.coordination.tasks import TaskConflict


@dataclass(frozen=True)
class PreparedQSPayment(PreparedQSMarket):
    ACTION_ID: ClassVar[str] = 'QS-A08'


class QSPaymentActionAssembler(QSMarketActionAssembler):
    """Freeze supplied originals under the application's current read guard.

    The original processor retains work eligibility, history completeness,
    retention/offset arithmetic, cash reconciliation and certificate permissions.
    Assembly creates no work, successful calculation, certificate or paid cash.
    """
    ACTION_ID = 'QS-A08'
    SOURCE_SCHEMAS = staticmethod(qs_payment_schemas)

    def build(self, context, *, scope, application_ref, contract_ref,
            performed_work_refs, prior_certificate_refs, payment_receipt_refs,
            measurement_result_refs, certification_authority_ref):
        return self._prepare_supplied_snapshot(context, input_values={
            'scope': scope, 'application_ref': application_ref, 'contract_ref': contract_ref,
            'performed_work_refs': performed_work_refs, 'prior_certificate_refs': prior_certificate_refs,
            'payment_receipt_refs': payment_receipt_refs, 'measurement_result_refs': measurement_result_refs,
            'certification_authority_ref': certification_authority_ref}, prepared_type=PreparedQSPayment,
            validate_sources=validate_qs_payment_sources)

    def prepare_calculations(self, context, *, author_authority_ref, validate_current, **source_refs):
        """Prepare all declared measurement results from one original method execution."""
        from integration.qs_payment_calculations import prepare_qs_payment_calculations

        prepared = self.build(context, **source_refs)
        return prepare_qs_payment_calculations(context=prepared.context, action_input=prepared.action_input,
            reading=prepared.reading, author_authority_ref=author_authority_ref, validate_current=validate_current)

    def publish_calculations(self, context, *, publications, next_context, read_guard,
            author_authority_ref, validate_current, **source_refs):
        """Calculate once, save all targets atomically, then publish the full bundle."""
        from integration.qs_payment_calculation_publication import QSPaymentCalculationPublicationStore
        from integration.qs_payment_calculations import prepare_qs_payment_calculations

        if (not isinstance(publications, QSPaymentCalculationPublicationStore)
                or publications.registry is not self.registry or publications.organizations is not self.organizations
                or publications.methods is not self.methods or not callable(read_guard)):
            raise TaskConflict('Payment publication requires original registries and the actual source writer guard')
        with read_guard(context):
            prepared = self.build(context, **source_refs)
            calculations = prepare_qs_payment_calculations(context=prepared.context, action_input=prepared.action_input,
                reading=prepared.reading, author_authority_ref=author_authority_ref, validate_current=validate_current)
            if calculations['kind'] != 'prepared':
                return calculations
            record = publications.save(calculations, context=prepared.context,
                action_input=prepared.action_input, reading=prepared.reading)
            publication = publications.publish(record['record_sha256'],
                source_context=prepared.context, next_context=next_context)
            return {'kind': 'prepared', 'calculations': calculations, 'record': record, 'publication': publication}


def validate_qs_payment_sources(action_input, *, context, organization_id, sources):
    """Check concrete original payment associations without recognizing cash."""
    def read(ref, schema):
        row = sources.get(ref.key())
        if not isinstance(row, schema) or row.ref.key() != ref.key():
            raise TaskConflict('QS payment lacks its exact original concrete source')
        if row.scope != action_input.scope:
            raise TaskConflict('QS payment source changes its original requested scope')
        return row

    if action_input.scope != context.scope:
        raise TaskConflict('QS payment changes its original invocation scope')
    for refs in (action_input.performed_work_refs, action_input.prior_certificate_refs,
            action_input.payment_receipt_refs, action_input.measurement_result_refs):
        unique_refs(refs)
    contract = read(action_input.contract_ref, QSPaymentContractView)
    application = read(action_input.application_ref, QSPaymentApplicationView)
    if (application.contract_ref.key() != contract.ref.key()
            or application.applicant_id != application.author_actor_id
            or application.applicant_id != contract.beneficiary_id
            or contract.valuation_actor_id != context.actor_id
            or contract.valuation_organization_id != organization_id
            or contract.valuation_function_ref.key() != context.function_ref.key()):
        raise TaskConflict('QS payment substitutes its original contract, beneficiary or valuation function')

    def related(ref, schema, application_ref=None):
        row = read(ref, schema)
        if (row.contract_ref.key() != contract.ref.key()
                or (application_ref is not None and row.application_ref != application_ref)):
            raise TaskConflict('QS payment source substitutes another original contract or application')
        return row

    def supplied_power(ref, actor, function, purpose, application_ref=None, key=None):
        if ref.key() in sources:
            power = related(ref, QSPaymentAuthorityView)
            if (power.actor_id != actor or power.function_ref != function or purpose not in power.purposes
                    or power.application_ref not in (None, application_ref or application.ref)
                    or (key is not None and power.certificate_key != key)):
                raise TaskConflict('QS payment power changes its original actor, application or purpose')

    for ref in action_input.performed_work_refs:
        work = related(ref, QSPaymentWorkView)
        if work.rate_ref.key() in sources:
            related(work.rate_ref, QSPaymentRateView)
        if work.condition_ref.key() in sources:
            condition = related(work.condition_ref, QSPaymentConditionView)
            if condition.work_ref.key() != work.ref.key():
                raise TaskConflict('QS payment condition substitutes another original work version')
            supplied_power(condition.condition_authority_ref, condition.author_actor_id,
                condition.author_function_ref, 'condition')
    for ref in action_input.prior_certificate_refs:
        certificate = related(ref, QSPaymentCertificateView)
        supplied_power(certificate.certification_authority_ref, certificate.author_actor_id,
            certificate.author_function_ref, 'correct' if certificate.predecessor_ref is not None else 'certify',
            certificate.application_ref, certificate.certificate_key)
        if certificate.statement_ref.key() in sources:
            statement = related(certificate.statement_ref, QSPaymentStatementView)
            if statement.certificate_ref != certificate.ref or statement.calculation_ref != certificate.calculation_ref:
                raise TaskConflict('QS certificate substitutes its original statement or calculation')
        if certificate.calculation_ref.key() in sources:
            related(certificate.calculation_ref, QSPaymentResultView, certificate.application_ref)
    for ref in action_input.measurement_result_refs:
        related(ref, QSPaymentResultView, application.ref)
    for ref in action_input.payment_receipt_refs:
        receipt = related(ref, QSPaymentReceiptView)
        if receipt.payer_id != contract.payer_id or receipt.beneficiary_id != contract.beneficiary_id:
            raise TaskConflict('QS payment receipt changes its original payer or beneficiary')
        if receipt.execution_ref.key() in sources:
            execution = related(receipt.execution_ref, QSPaymentExecutionView)
            fields = ('certificate_ref', 'credit_ref', 'purpose', 'payer_id', 'beneficiary_id', 'command_id', 'business_key')
            if any(getattr(receipt, field) != getattr(execution, field) for field in fields) or ref not in execution.receipt_refs:
                raise TaskConflict('QS payment receipt changes its original execution or command')
    for ref in contract.deduction_refs:
        if ref.key() in sources:
            deduction = related(ref, QSPaymentAdjustmentView, application.ref)
            supplied_power(deduction.deduction_authority_ref, deduction.author_actor_id,
                deduction.author_function_ref, 'deduct')
    for ref in contract.advance_credit_refs:
        if ref.key() not in sources:
            continue
        credit = related(ref, QSPaymentCreditView, application.ref)
        for allocation_ref in credit.allocation_refs:
            if allocation_ref.key() in sources:
                allocation = related(allocation_ref, QSPaymentCreditAllocation)
                if allocation.credit_ref != credit.ref:
                    raise TaskConflict('QS advance allocation substitutes another original credit')
    for ref in application.question_refs:
        if ref.key() not in sources:
            continue
        question = related(ref, QSPaymentQuestionView, application.ref)
        if question.response_requirement_ref.key() in sources:
            related(question.response_requirement_ref, QSPaymentResponseView, application.ref)
    if action_input.certification_authority_ref is not None:
        related(action_input.certification_authority_ref, QSPaymentAuthorityView)
    for ref, schema, purpose in (
            (application.certification_basis_ref, QSPaymentCertificationView, 'certify'),
            (application.correction_basis_ref, QSPaymentCorrectionView, 'correct')):
        if ref is None or ref.key() not in sources:
            continue
        basis = related(ref, schema, application.ref)
        # Independent bases are used by the processor only when certification is requested.
        if action_input.certification_authority_ref is not None:
            if (basis.actor_id != context.actor_id or basis.function_ref != context.function_ref
                    or basis.authority_ref != action_input.certification_authority_ref):
                raise TaskConflict('QS certificate basis substitutes its acting function or independent authority')
            supplied_power(basis.authority_ref, context.actor_id, context.function_ref,
                purpose, key=basis.certificate_key)
    # Original authors/dates, complete sets, prior certificate/correction chains,
    # cash stream semantics, money arithmetic and statement hashes stay in the processor.
