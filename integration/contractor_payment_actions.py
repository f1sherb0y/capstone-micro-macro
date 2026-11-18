"""Assemble original Contractor A10 measurement and payment inputs."""
from dataclasses import dataclass
from typing import ClassVar

from integration.contractor_amendment_actions import ContractorAmendmentActionAssembler, PreparedContractorAmendment
from src.actions.contracts.contractor_payment_objects import (
    ContractorMeasurementApplicationView, ContractorPaymentCertificateView,
    ContractorPaymentContractView, ContractorPaymentIssueView, ContractorRequestableComponentView,
    ContractorSettlementProcedureView, ContractorSettlementRuleView,
    ContractorWorkRecordView, ContractorMeasurementWorkRecordView, OwnerPaymentAccountView, OwnerPaymentExecutionView,
    OwnerPaymentObligationView, OwnerPaymentReceiptView, OwnerPaymentReservationView,
    contractor_payment_schemas,
)
from src.actions.contracts.owner_study_objects import unique_refs
from src.coordination.tasks import TaskConflict
from src.organization.registry import scope_covers


@dataclass(frozen=True)
class PreparedContractorPayment(PreparedContractorAmendment):
    ACTION_ID: ClassVar[str] = 'CONTRACTOR-A10'


class ContractorPaymentActionAssembler(ContractorAmendmentActionAssembler):
    """Freeze original work, certificates, obligations and explicit own accounts.

    The actual application holds its current source/authorization guard. Original
    processor checks measurement coverage, certificates, debt components, cash,
    financing and reconciliation. First measurement needs no prior certificate.
    Assembly creates no certified work, debt, financing acceptance or paid cash.
    """
    ACTION_ID = 'CONTRACTOR-A10'
    SOURCE_SCHEMAS = staticmethod(contractor_payment_schemas)

    def build(self, context, *, contract_ref, work_record_refs, certificate_refs,
            obligation_refs, account_refs, execution_refs, settlement_rule_ref):
        return self._prepare_supplied_snapshot(context, input_values={
            'contract_ref': contract_ref, 'work_record_refs': work_record_refs,
            'certificate_refs': certificate_refs, 'obligation_refs': obligation_refs,
            'account_refs': account_refs, 'execution_refs': execution_refs,
            'settlement_rule_ref': settlement_rule_ref}, prepared_type=PreparedContractorPayment,
            validate_sources=validate_contractor_payment_sources)


def validate_contractor_payment_sources(action_input, *, context, organization_id, sources):
    """Check original parties and command identities without posting money or net work."""
    def read(ref, schema):
        source = sources.get(ref.key())
        if not isinstance(source, schema) or source.ref.key() != ref.key():
            raise TaskConflict('Contractor payment lacks its exact original concrete source')
        return source

    for refs in (action_input.work_record_refs, action_input.certificate_refs,
            action_input.obligation_refs, action_input.account_refs, action_input.execution_refs):
        unique_refs(refs)
    contract = read(action_input.contract_ref, ContractorPaymentContractView)
    rule = read(action_input.settlement_rule_ref, ContractorSettlementRuleView)
    if (contract.contractor_id != organization_id or not scope_covers(contract.scope, context.scope)
            or contract.settlement_rule_ref.key() != rule.ref.key()
            or rule.contract_ref.key() != contract.ref.key() or rule.organization_id != organization_id):
        raise TaskConflict('Contractor payment changes original contract, contractor or settlement rule')
    for ref in action_input.work_record_refs:
        work = read(ref, ContractorWorkRecordView)
        if isinstance(work, ContractorMeasurementWorkRecordView) and work.occurred_at is not None:
            if (work.occurred_at.clock_ref != context.business_time.clock_ref
                    or work.available_at.clock_ref != context.business_time.clock_ref
                    or work.occurred_at.offset > work.available_at.offset):
                raise TaskConflict('Contractor measured work changes actual occurrence chronology')
            unique_refs(work.occurrence_evidence_refs)
        # Missing actual occurrence remains a processor needs-info result. Old
        # history still counts toward prior applications and occupied amounts.
    for ref in action_input.certificate_refs:
        if read(ref, ContractorPaymentCertificateView).contract_ref.key() != contract.ref.key():
            raise TaskConflict('Contractor payment certificate changes its original contract')
    for ref in action_input.obligation_refs:
        obligation = read(ref, OwnerPaymentObligationView)
        if organization_id not in {obligation.debtor_id, obligation.payee_id}:
            raise TaskConflict('Contractor payment substitutes another legal debtor or payee obligation')
        unique_refs(obligation.component_refs)
        for component_ref in obligation.component_refs:
            component = sources.get(component_ref.key())
            if component is not None and (not isinstance(component, ContractorRequestableComponentView)
                    or component.contract_ref.key() != contract.ref.key() or component.obligation_ref.key() != obligation.ref.key()
                    or component.debtor_id != obligation.debtor_id or component.payee_id != obligation.payee_id
                    or component.source_ref.key() != obligation.source_ref.key()
                    or component.debt_ref != obligation.debt_ref):
                raise TaskConflict('Contractor payment changes original obligation component, loan, parties or funding source')
    account_pending = {}
    for ref in action_input.account_refs:
        account = read(ref, OwnerPaymentAccountView)
        if account.organization_id != organization_id:
            raise TaskConflict('Contractor payment cannot substitute another organization cash account')
        unique_refs(account.pending_execution_refs)
        for pending_ref in account.pending_execution_refs:
            key = pending_ref.key()
            if key in account_pending and account_pending[key] != account.ref:
                raise TaskConflict('Contractor pending payment is attributed to multiple original accounts')
            account_pending[key] = account.ref
            prior = sources.get(key)
            if prior is not None and (not isinstance(prior, OwnerPaymentExecutionView)
                    or prior.organization_id != organization_id or prior.account_ref != account.ref):
                raise TaskConflict('Contractor account pending payment changes original legal payer or exact account')
        for reservation_ref in account.reservation_refs:
            reservation = sources.get(reservation_ref.key())
            if reservation is not None and (not isinstance(reservation, OwnerPaymentReservationView)
                    or reservation.organization_id != organization_id or reservation.account_ref.key() != account.ref.key()):
                raise TaskConflict('Contractor payment changes its original own cash reservation')
    for ref in action_input.execution_refs:
        execution = read(ref, OwnerPaymentExecutionView)
        if ref.key() not in {item.key() for item in contract.execution_refs} and ref.key() not in account_pending:
            raise TaskConflict('Contractor extra execution is absent from original contract and own-account pending history')
        if execution.organization_id != organization_id and not (
                execution.organization_id == contract.client_id and execution.beneficiary_id == organization_id):
            raise TaskConflict('Contractor payment execution changes original payer or beneficiary')
        if execution.receipt_ref is not None:
            receipt = sources.get(execution.receipt_ref.key())
            if receipt is not None and (not isinstance(receipt, OwnerPaymentReceiptView)
                    or receipt.execution_ref.key() != execution.ref.key() or receipt.command_id != execution.command_id
                    or receipt.business_key != execution.business_key or receipt.beneficiary_id != execution.beneficiary_id
                    or receipt.amount != execution.amount or receipt.status != execution.status):
                raise TaskConflict('Contractor payment changes the original execution receipt identity or result')
    procedure = sources.get(rule.procedure_ref.key())
    if procedure is not None and (not isinstance(procedure, ContractorSettlementProcedureView)
            or procedure.contract_ref.key() != contract.ref.key()):
        raise TaskConflict('Contractor settlement procedure changes its original contract')
    for ref in contract.measurement_application_refs:
        application = sources.get(ref.key())
        if application is not None and (not isinstance(application, ContractorMeasurementApplicationView)
                or application.organization_id != organization_id or application.request.contract_ref.key() != contract.ref.key()):
            raise TaskConflict('Contractor measurement history changes original contractor or contract')
    if rule.measurement is not None and rule.measurement.contract_ref.key() != contract.ref.key():
        raise TaskConflict('Contractor measurement draft changes its original contract')
    for ref in rule.issue_refs:
        issue = sources.get(ref.key())
        if issue is not None and (not isinstance(issue, ContractorPaymentIssueView)
                or issue.contract_ref.key() != contract.ref.key()):
            raise TaskConflict('Contractor payment issue changes its original contract')
    if rule.financing is not None and (rule.financing.borrower_id != organization_id
            or rule.financing.scope_ref != context.scope or rule.financing.applicant_authority_ref.key() != rule.authority_ref.key()):
        raise TaskConflict('Contractor financing draft changes original borrower, scope or applicant authority')
