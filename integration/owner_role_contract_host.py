"""Explicit single-action Owner host using original assemblers and durable workers."""
from copy import deepcopy
from dataclasses import dataclass, fields
import importlib
import json
from pathlib import Path
from typing import Annotated, Callable

from pydantic import Field

from integration.action_model_host import ActionModelHost
from integration.module_host import module_factory_descriptor
from integration.owner_observation_actions import OwnerObservationActionAssembler
from integration.owner_observation_results import OwnerObservationResultWorker
from integration.role_contract_host import (
    RoleContractExecution, RoleContractHost, RoleContractHostConfiguration, RoleContractInvocation,
    prepare_role_contract_options,
)
from src.actions.contracts.common import StrictRecord, TextId, ref_type
from src.actions.registry import ActionRegistry
from src.coordination.invocations import InvocationSnapshotStore
from src.coordination.tasks import TaskConflict, TaskStore, canonical, task_digest
from src.methods.models import Digest
from src.organization.registry import OrganizationRegistry


class OwnerRoleFeedbackSettings(StrictRecord):
    version: TextId
    selections: dict[TextId, Annotated[list[Digest], Field(min_length=1)]]


class OwnerResearchComparisonSelection(StrictRecord):
    source_task_sha256: Digest
    receipt_ref: ref_type('ResearchComparisonReceipt')


class OwnerResearchComparisonSettings(StrictRecord):
    version: TextId
    selections: dict[TextId, OwnerResearchComparisonSelection]


class OwnerPaymentCertificateSelection(StrictRecord):
    source_task_sha256: Digest
    receipt_ref: ref_type('PaymentCertificateReceipt')
    receipt_sha256: Digest | None = None


class OwnerPaymentCertificateMappingSelection(StrictRecord):
    certificates: Annotated[list[OwnerPaymentCertificateSelection], Field(min_length=1)]


class OwnerPaymentCertificateSettings(StrictRecord):
    version: TextId
    selections: dict[TextId, OwnerPaymentCertificateSelection | OwnerPaymentCertificateMappingSelection]


class OwnerFinancingOfferSelection(StrictRecord):
    source_task_sha256: Digest
    receipt_ref: ref_type('FinanceOfferReceipt')
    receipt_sha256: Digest | None = None


class OwnerFinancingOfferSettings(StrictRecord):
    version: TextId
    selections: dict[TextId, OwnerFinancingOfferSelection]


class OwnerPaymentArrangementSelection(StrictRecord):
    source_task_sha256: Digest
    receipt_ref: ref_type('FinanceArrangementReceipt')
    receipt_sha256: Digest | None = None


class OwnerPaymentArrangementSettings(StrictRecord):
    version: TextId
    selections: dict[TextId, OwnerPaymentArrangementSelection]


class OwnerBankExecutionSelection(StrictRecord):
    source_task_sha256: Digest
    reception_ref: ref_type('BankExecutionReception')
    reception_sha256: Digest | None = None


class OwnerBankExecutionSettings(StrictRecord):
    version: TextId
    selections: dict[TextId, OwnerBankExecutionSelection]


class OwnerPaymentExecutionSelection(StrictRecord):
    source_task_sha256: Digest
    execution_refs: Annotated[list[ref_type('PaymentExecution')], Field(min_length=1)]


class OwnerPaymentExecutionGroup(StrictRecord):
    payments: Annotated[list[OwnerPaymentExecutionSelection], Field(min_length=1)]


class OwnerPaymentExecutionSettings(StrictRecord):
    version: TextId
    selections: dict[TextId, OwnerPaymentExecutionGroup]


class OwnerHandoverReceptionSelection(StrictRecord):
    source_task_sha256: Digest
    handover_ref: ref_type('HandoverSubmission')
    native_evidence_ref: ref_type('Evidence')


class OwnerHandoverReceptionSettings(StrictRecord):
    version: TextId
    selections: dict[TextId, OwnerHandoverReceptionSelection]


class OwnerCloseoutContinuationSelection(StrictRecord):
    feedback_record_sha256: Digest
    basis_ref: ref_type('CloseoutContinuationBasis')


class OwnerCloseoutContinuationSettings(StrictRecord):
    version: TextId
    selections: dict[TextId, OwnerCloseoutContinuationSelection]


class OwnerReceivedContractorBidSelection(StrictRecord):
    source_task_sha256: Digest
    bid_ref: ref_type('Bid')
    native_evidence_ref: ref_type('Evidence')


class OwnerReceivedContractorBidGroup(StrictRecord):
    bids: Annotated[list[OwnerReceivedContractorBidSelection], Field(min_length=1)]


class OwnerReceivedContractorBidSettings(StrictRecord):
    version: TextId
    selections: dict[TextId, OwnerReceivedContractorBidGroup]


class OwnerTenderEvaluationSelection(StrictRecord):
    source_task_sha256: Digest
    selected_bid_ref: ref_type('Bid')
    native_evidence_ref: ref_type('Evidence')


class OwnerTenderEvaluationSettings(StrictRecord):
    version: TextId
    selections: dict[TextId, OwnerTenderEvaluationSelection]


class OwnerSupplementNoticeSelection(StrictRecord):
    source_task_sha256: Digest
    notice_ref: ref_type('RegulatoryNotice')
    native_evidence_ref: ref_type('Evidence')


class OwnerSupplementNoticeSettings(StrictRecord):
    version: TextId
    selections: dict[TextId, OwnerSupplementNoticeSelection]


class OwnerRoleContractSettings(StrictRecord):
    action_id: TextId
    source_factory: TextId
    source_version: TextId
    source_settings: dict
    macro_version: TextId
    client_version: TextId
    policy_version: TextId
    model_version: TextId
    feedback_inputs: OwnerRoleFeedbackSettings | None = None
    certificate_inputs: OwnerPaymentCertificateSettings | None = None
    financing_offer_inputs: OwnerFinancingOfferSettings | None = None
    payment_arrangement_inputs: OwnerPaymentArrangementSettings | None = None
    bank_execution_inputs: OwnerBankExecutionSettings | None = None
    payment_execution_inputs: OwnerPaymentExecutionSettings | None = None
    handover_inputs: OwnerHandoverReceptionSettings | None = None
    closeout_continuation_inputs: OwnerCloseoutContinuationSettings | None = None
    research_comparison_inputs: OwnerResearchComparisonSettings | None = None
    received_contractor_bid_inputs: OwnerReceivedContractorBidSettings | None = None
    tender_evaluation_inputs: OwnerTenderEvaluationSettings | None = None
    supplement_notice_inputs: OwnerSupplementNoticeSettings | None = None


@dataclass(frozen=True)
class OwnerSourceValidators:
    invocation: Callable
    wait: Callable
    recovery: Callable

    def __post_init__(self):
        if not all(callable(getattr(self, item.name)) for item in fields(self)):
            raise ValueError('Owner invocation, wait and recovery require explicit host validation')


@dataclass(frozen=True)
class OwnerRoleContractSources:
    """Application owns original authorized sources and its persistent run journal.

    read_guard(context) holds the actual current source/authorization boundary.
    The source factory owns partial resources until returning this object.
    This host creates no native source, authorization or model client.
    """
    version: str
    registry: ActionRegistry
    organizations: OrganizationRegistry
    store: TaskStore
    provider: object
    read_guard: Callable
    validators: OwnerSourceValidators
    evidence: Callable
    close: Callable
    methods: object = None
    model_host: ActionModelHost | None = None
    feedback: object = None
    validate_feedback_input: Callable | None = None
    read_qs_payment: Callable | None = None
    validate_payment_certificate_reception: Callable | None = None
    validate_payment_certificate_mapping: Callable | None = None
    read_bank_quote: Callable | None = None
    validate_financing_offer_reception: Callable | None = None
    read_bank_arrangement: Callable | None = None
    validate_payment_arrangement_reception: Callable | None = None
    read_bank_execution: Callable | None = None
    validate_bank_execution_reception: Callable | None = None
    read_owner_payment_execution: Callable | None = None
    validate_owner_payment_execution_reception: Callable | None = None
    read_contractor_closeout: Callable | None = None
    validate_handover_reception: Callable | None = None
    read_closeout_feedback: Callable | None = None
    validate_closeout_continuation: Callable | None = None
    read_qs_research: Callable | None = None
    validate_research_reception: Callable | None = None
    read_contractor_bid: Callable | None = None
    validate_contractor_bid_reception: Callable | None = None
    read_tender_evaluation: Callable | None = None
    validate_tender_award_selection: Callable | None = None
    read_government_supplement: Callable | None = None
    validate_supplement_notice_reception: Callable | None = None

    def __post_init__(self):
        if (not isinstance(self.version, str) or not self.version.strip()
                or not isinstance(self.registry, ActionRegistry)
                or not isinstance(self.organizations, OrganizationRegistry)
                or not isinstance(self.store, TaskStore) or self.store.path is None
                or not isinstance(self.validators, OwnerSourceValidators)
                or not callable(getattr(self.provider, 'project', None))
                or not all(callable(callback) for callback in (self.read_guard, self.evidence, self.close))
                or self.model_host is not None and not isinstance(self.model_host, ActionModelHost)):
            raise ValueError('Owner sources require original registries, persistent journal, reader and callbacks')
        if ((self.read_government_supplement is None) != (self.validate_supplement_notice_reception is None)
                or self.read_government_supplement is not None and (
                    not callable(self.read_government_supplement) or not callable(self.validate_supplement_notice_reception))):
            raise ValueError('Supplement notices require paired original Government reader and independent reception validator')
        if ((self.read_tender_evaluation is None) != (self.validate_tender_award_selection is None)
                or self.read_tender_evaluation is not None and (
                    not callable(self.read_tender_evaluation) or not callable(self.validate_tender_award_selection))):
            raise ValueError('Award selection requires paired original tender evaluation reader and independent native selection validator')
        if ((self.read_contractor_bid is None) != (self.validate_contractor_bid_reception is None)
                or self.read_contractor_bid is not None and (
                    not callable(self.read_contractor_bid) or not callable(self.validate_contractor_bid_reception))):
            raise ValueError('Received bids require paired original Contractor journal reader and independent reception validator')
        if ((self.read_qs_research is None) != (self.validate_research_reception is None)
                or self.read_qs_research is not None and (
                    not callable(self.read_qs_research) or not callable(self.validate_research_reception))):
            raise ValueError('Owner research requires paired original QS reader and independent reception validator')
        certificate_validators = (self.validate_payment_certificate_reception, self.validate_payment_certificate_mapping)
        if ((self.read_qs_payment is None) != all(callback is None for callback in certificate_validators)
                or self.read_qs_payment is not None and not callable(self.read_qs_payment)
                or any(callback is not None and not callable(callback) for callback in certificate_validators)):
            raise ValueError('Owner certificate sources require original QS reader and explicit reception or mapping validators')
        if ((self.read_bank_quote is None) != (self.validate_financing_offer_reception is None)
                or self.read_bank_quote is not None and (
                    not callable(self.read_bank_quote) or not callable(self.validate_financing_offer_reception))):
            raise ValueError('Owner offer sources require paired original Bank reader and receiver validator')
        if ((self.read_bank_arrangement is None) != (self.validate_payment_arrangement_reception is None)
                or self.read_bank_arrangement is not None and (
                    not callable(self.read_bank_arrangement) or not callable(self.validate_payment_arrangement_reception))):
            raise ValueError('Owner arrangement sources require paired original Bank reader and receiver validator')
        if ((self.read_bank_execution is None) != (self.validate_bank_execution_reception is None)
                or self.read_bank_execution is not None and (
                    not callable(self.read_bank_execution) or not callable(self.validate_bank_execution_reception))):
            raise ValueError('Owner execution sources require paired original Bank reader and receiver validator')
        if ((self.read_owner_payment_execution is None) != (self.validate_owner_payment_execution_reception is None)
                or self.read_owner_payment_execution is not None and (
                    not callable(self.read_owner_payment_execution) or not callable(self.validate_owner_payment_execution_reception))):
            raise ValueError('Owner payment execution sources require paired original payment reader and receiver validator')
        if ((self.read_contractor_closeout is None) != (self.validate_handover_reception is None)
                or self.read_contractor_closeout is not None and (
                    not callable(self.read_contractor_closeout) or not callable(self.validate_handover_reception))):
            raise ValueError('Owner handover requires paired authorized Contractor journal reader and actual receiver validator')
        if ((self.read_closeout_feedback is None) != (self.validate_closeout_continuation is None)
                or self.read_closeout_feedback is not None and (
                    not callable(self.read_closeout_feedback) or not callable(self.validate_closeout_continuation))):
            raise ValueError('Owner closeout continuation requires paired original feedback reader and current native relation validator')
        if self.feedback is not None or self.validate_feedback_input is not None:
            # Keep role routing importable by submission and feedback modules.
            from integration.owner_submission_feedback import OwnerSubmissionFeedback
            if (not isinstance(self.feedback, OwnerSubmissionFeedback)
                    or self.feedback.host.store is not self.store or self.feedback.host.registry is not self.registry
                    or not callable(self.validate_feedback_input)):
                raise ValueError('Owner feedback sources require original same-journal feedback and an input validator')


# Closed routing: request data never names a processor, schema or result table.
_ACTIONS = {
    'OWN-A01': ('observation', 'Observation'), 'OWN-A02': ('study', 'Study'),
    'OWN-A03': ('investment', 'Investment'), 'OWN-A04': ('commission', 'Commission'),
    'OWN-A05': ('financing', 'Financing'), 'OWN-A06': ('payment', 'Payment'),
    'OWN-A07': ('design', 'Design'), 'OWN-A08': ('regulatory', 'Regulatory'),
    'OWN-A09': ('tender', 'Tender'), 'OWN-A10': ('award', 'Award'),
    'OWN-A11': ('contract', 'Contract'), 'OWN-A12': ('closeout', 'Closeout'),
    'OWN-A13': ('continuation', 'Continuation'), 'OWN-A14': ('asset', 'Asset'),
    'OWN-A15': ('operating', 'Operating'), 'OWN-A16': ('proposal', 'Proposal'),
}


def _load_factory(specification):
    if specification.count(':') != 1:
        raise ValueError('Owner source factory requires module:callable syntax')
    module, name = specification.split(':')
    if not module or not name.isidentifier():
        raise ValueError('Owner source factory requires an explicit module and callable')
    factory = getattr(importlib.import_module(module), name, None)
    if not callable(factory):
        raise ValueError('Owner source factory is not callable')
    return factory


def _descriptors(sources):
    callbacks = {item.name: getattr(sources.validators, item.name) for item in fields(sources.validators)}
    callbacks.update(provider=sources.provider.project, read_guard=sources.read_guard,
        evidence=sources.evidence, close=sources.close, option_preparation=prepare_role_contract_options)
    if sources.read_qs_research is not None:
        from integration.qs_research_investment_handoff import read_received_qs_research, validate_received_qs_research
        callbacks.update(read_qs_research=sources.read_qs_research,
            validate_research_reception=sources.validate_research_reception,
            research_comparison_handoff=read_received_qs_research,
            research_comparison_source_gate=validate_received_qs_research)
    if sources.read_contractor_bid is not None:
        from integration.contractor_owner_tender_handoff import read_received_contractor_bids
        from integration.contractor_bid_results import ContractorBidResultWorker
        from integration.contractor_submission_host import ContractorSubmissionHost
        callbacks.update(read_contractor_bid=sources.read_contractor_bid,
            validate_contractor_bid_reception=sources.validate_contractor_bid_reception,
            received_contractor_bid_handoff=read_received_contractor_bids,
            original_contractor_bid_record_gate=ContractorBidResultWorker.validate_saved_record,
            original_contractor_bid_receipt_reader=ContractorSubmissionHost.read_receipt)
    if sources.read_tender_evaluation is not None:
        from integration.owner_tender_award_handoff import read_selected_tender_evaluation
        from integration.owner_submission_host import OwnerSubmissionHost
        callbacks.update(read_tender_evaluation=sources.read_tender_evaluation,
            validate_tender_award_selection=sources.validate_tender_award_selection,
            tender_evaluation_handoff=read_selected_tender_evaluation,
            original_tender_evaluation_receipt_reader=OwnerSubmissionHost.read_receipt)
    if sources.read_government_supplement is not None:
        from integration.government_owner_supplement_handoff import read_received_supplement_notice
        from integration.government_submission_host import GovernmentSubmissionHost
        callbacks.update(read_government_supplement=sources.read_government_supplement,
            validate_supplement_notice_reception=sources.validate_supplement_notice_reception,
            supplement_notice_handoff=read_received_supplement_notice,
            original_government_supplement_receipt_reader=GovernmentSubmissionHost.read_receipt)
    if sources.feedback is not None:
        callbacks['validate_feedback_input'] = sources.validate_feedback_input
    if sources.read_qs_payment is not None:
        from integration.qs_certificate_owner_payment_handoff import (
            read_received_payment_certificate, read_received_payment_certificate_mapping,
        )
        callbacks['read_qs_payment'] = sources.read_qs_payment
        if sources.validate_payment_certificate_reception is not None:
            callbacks.update(validate_payment_certificate_reception=sources.validate_payment_certificate_reception,
                certificate_handoff=read_received_payment_certificate)
        if sources.validate_payment_certificate_mapping is not None:
            callbacks.update(validate_payment_certificate_mapping=sources.validate_payment_certificate_mapping,
                certificate_mapping_handoff=read_received_payment_certificate_mapping)
    if sources.read_bank_quote is not None:
        from integration.bank_quote_owner_financing_handoff import read_received_financing_offer
        callbacks.update(read_bank_quote=sources.read_bank_quote,
            validate_financing_offer_reception=sources.validate_financing_offer_reception,
            financing_offer_handoff=read_received_financing_offer)
    if sources.read_bank_arrangement is not None:
        from integration.bank_arrangement_owner_payment_handoff import read_received_payment_arrangement
        callbacks.update(read_bank_arrangement=sources.read_bank_arrangement,
            validate_payment_arrangement_reception=sources.validate_payment_arrangement_reception,
            payment_arrangement_handoff=read_received_payment_arrangement)
    if sources.read_bank_execution is not None:
        from integration.bank_execution_owner_payment_handoff import read_received_bank_execution
        callbacks.update(read_bank_execution=sources.read_bank_execution,
            validate_bank_execution_reception=sources.validate_bank_execution_reception,
            bank_execution_handoff=read_received_bank_execution)
    if sources.read_owner_payment_execution is not None:
        from integration.owner_payment_execution_reception import read_received_owner_payment_executions
        callbacks.update(read_owner_payment_execution=sources.read_owner_payment_execution,
            validate_owner_payment_execution_reception=sources.validate_owner_payment_execution_reception,
            owner_payment_execution_handoff=read_received_owner_payment_executions)
    if sources.read_contractor_closeout is not None:
        from integration.contractor_owner_handover import read_received_owner_handover
        callbacks.update(read_contractor_closeout=sources.read_contractor_closeout,
            validate_handover_reception=sources.validate_handover_reception,
            handover_reception=read_received_owner_handover)
    if sources.read_closeout_feedback is not None:
        from integration.owner_closeout_continuation_handoff import read_closeout_continuation_basis
        callbacks.update(read_closeout_feedback=sources.read_closeout_feedback,
            validate_closeout_continuation=sources.validate_closeout_continuation,
            closeout_continuation_handoff=read_closeout_continuation_basis)
    return {name: module_factory_descriptor(callback, name) for name, callback in callbacks.items()}


def build_role_host(*, request, output_directory, offline, configuration):
    """Prepare one exact authorized invocation; run only through its original worker."""
    request = RoleContractInvocation.model_validate(request).model_copy(deep=True)
    config = RoleContractHostConfiguration.model_validate(configuration).model_copy(deep=True)
    settings = OwnerRoleContractSettings.model_validate(config.settings)
    if (type(offline) is not bool or settings.action_id not in _ACTIONS
            or request.context.contract_ref.id != settings.action_id
            or request.context.execution_mode != ('offline_fixture' if offline else 'llm')):
        raise ValueError('Owner host requires an explicit matching Owner action and model mode')
    feedback_settings = settings.feedback_inputs
    certificate_settings = settings.certificate_inputs
    offer_settings = settings.financing_offer_inputs
    arrangement_settings = settings.payment_arrangement_inputs
    bank_execution_settings = settings.bank_execution_inputs
    payment_execution_settings = settings.payment_execution_inputs
    handover_settings = settings.handover_inputs
    closeout_continuation_settings = settings.closeout_continuation_inputs
    research_settings = settings.research_comparison_inputs
    contractor_bid_settings = settings.received_contractor_bid_inputs
    tender_evaluation_settings = settings.tender_evaluation_inputs
    supplement_notice_settings = settings.supplement_notice_inputs
    if supplement_notice_settings is not None and (settings.action_id != 'OWN-A08'
            or request.context.operation_id not in supplement_notice_settings.selections):
        raise ValueError('Supplement notices require explicit OWN-A08 selections for this operation')
    if tender_evaluation_settings is not None and (settings.action_id != 'OWN-A10'
            or request.context.operation_id not in tender_evaluation_settings.selections):
        raise ValueError('Tender evaluation inputs require explicit OWN-A10 selections for this operation')
    if contractor_bid_settings is not None and (settings.action_id != 'OWN-A09'
            or request.context.operation_id not in contractor_bid_settings.selections):
        raise ValueError('Received Contractor bids require explicit OWN-A09 selections for this operation')
    if research_settings is not None and (settings.action_id != 'OWN-A03'
            or request.context.operation_id not in research_settings.selections):
        raise ValueError('Research comparison inputs require explicit OWN-A03 selections for this operation')
    if closeout_continuation_settings is not None and (offline or settings.action_id != 'OWN-A13'
            or request.context.operation_id not in closeout_continuation_settings.selections):
        raise ValueError('Closeout continuation inputs require explicit formal OWN-A13 selections for this operation')
    if handover_settings is not None and (settings.action_id != 'OWN-A12'
            or request.context.operation_id not in handover_settings.selections):
        raise ValueError('Handover inputs require explicit OWN-A12 selections for this operation')
    if payment_execution_settings is not None and (offline or settings.action_id != 'OWN-A06'
            or request.context.operation_id not in payment_execution_settings.selections):
        raise ValueError('Payment execution inputs require explicit formal OWN-A06 selections for this operation')
    if bank_execution_settings is not None and (settings.action_id != 'OWN-A06'
            or request.context.operation_id not in bank_execution_settings.selections):
        raise ValueError('Bank execution inputs require explicit OWN-A06 selections for this operation')
    if arrangement_settings is not None and (settings.action_id != 'OWN-A06'
            or request.context.operation_id not in arrangement_settings.selections):
        raise ValueError('Payment arrangement inputs require explicit OWN-A06 selections for this operation')
    if offer_settings is not None and (settings.action_id != 'OWN-A05'
            or request.context.operation_id not in offer_settings.selections):
        raise ValueError('Financing offer inputs require explicit OWN-A05 selections for this operation')
    if certificate_settings is not None and (settings.action_id != 'OWN-A06'
            or request.context.operation_id not in certificate_settings.selections):
        raise ValueError('Payment certificate inputs require explicit OWN-A06 selections for this operation')
    if feedback_settings is not None and (offline or not feedback_settings.selections
            or request.context.operation_id not in feedback_settings.selections
            or any(len(set(values)) != len(values) for values in feedback_settings.selections.values())):
        raise ValueError('Owner feedback inputs require formal mode and unique saved feedback selections for this operation')
    factory = _load_factory(settings.source_factory)
    descriptor = module_factory_descriptor(factory, settings.source_factory)
    sources = factory(request=request.model_copy(deep=True), output_directory=Path(output_directory),
        offline=offline, settings=deepcopy(settings.source_settings))
    if not isinstance(sources, OwnerRoleContractSources):
        raise ValueError('Owner source factory must return OwnerRoleContractSources')
    try:
        if (sources.version != settings.source_version or sources.store.run_id != request.context.run_id
                or sources.organizations.run_id != request.context.run_id
                or module_factory_descriptor(factory, settings.source_factory) != descriptor):
            raise TaskConflict('Owner sources change their declared version, run or source factory')
        if (feedback_settings is None) != (sources.feedback is None):
            raise ValueError('Owner feedback source binding must match its explicit input configuration')
        if research_settings is not None and sources.read_qs_research is None:
            raise ValueError('Configured research comparison requires original QS journal and receiver callbacks')
        if certificate_settings is not None and sources.read_qs_payment is None:
            raise ValueError('Configured certificate requires original QS journal and actual receiver callbacks')
        if offer_settings is not None and sources.read_bank_quote is None:
            raise ValueError('Configured financing offer requires original Bank journal and actual receiver callbacks')
        if arrangement_settings is not None and sources.read_bank_arrangement is None:
            raise ValueError('Configured payment arrangement requires original Bank journal and actual receiver callbacks')
        if bank_execution_settings is not None and sources.read_bank_execution is None:
            raise ValueError('Configured Bank execution requires original journal and actual receiver callbacks')
        if payment_execution_settings is not None and sources.read_owner_payment_execution is None:
            raise ValueError('Configured payment executions require original Owner journal and actual receiver callbacks')
        if handover_settings is not None and sources.read_contractor_closeout is None:
            raise ValueError('Configured handover requires original Contractor journal and actual Owner receiver callbacks')
        if closeout_continuation_settings is not None and sources.read_closeout_feedback is None:
            raise ValueError('Configured closeout continuation requires original feedback and current native mapping callbacks')
        if certificate_settings is not None:
            certificate_selection = certificate_settings.selections[request.context.operation_id]
            mapping_selection = isinstance(certificate_selection, OwnerPaymentCertificateMappingSelection)
            required_validator = (sources.validate_payment_certificate_mapping if mapping_selection
                else sources.validate_payment_certificate_reception)
            if required_validator is None:
                raise ValueError('Configured certificate selection requires its actual reception or complete mapping validator')
        registration = sources.registry.get(settings.action_id)
        if registration.role != 'Owner' or not registration.implemented or registration.skill is None:
            raise ValueError('Owner host requires its original implemented processor and Skill')
        expected_path = 'deterministic' if offline else registration.strategy
        if request.execution_path not in {None, expected_path}:
            raise ValueError('Owner execution path must match its original versioned strategy')
        model_host = sources.model_host
        if offline:
            if model_host is not None:
                raise ValueError('Offline Owner host must not receive a model host')
        elif (model_host is None or model_host.store is not sources.store
                or model_host.registry is not sources.registry or model_host.model_version != settings.model_version
                or not any(settings.action_id in binding.action_ids and binding.strategy == registration.strategy
                    for binding in model_host.bindings)):
            raise ValueError('LLM Owner host requires its existing same-journal model host and budget')
        module, name = _ACTIONS[settings.action_id]
        assembler_type = getattr(importlib.import_module('integration.owner_' + module + '_actions'),
            'Owner' + name + 'ActionAssembler')
        worker_type = getattr(importlib.import_module('integration.owner_' + module + '_results'),
            'Owner' + name + 'ResultWorker')
        if not issubclass(assembler_type, OwnerObservationActionAssembler) or not issubclass(worker_type, OwnerObservationResultWorker):
            raise ValueError('Owner routing must retain the original assembler and result worker')
        assembler = assembler_type(registry=sources.registry, organizations=sources.organizations,
            provider=sources.provider, macro_version=settings.macro_version,
            source_mode='fixture' if offline else 'formal', methods=sources.methods,
            policy_version=settings.policy_version, model_version=settings.model_version, model_host=model_host)
        worker = worker_type(store=sources.store, snapshots=InvocationSnapshotStore(sources.store),
            registry=sources.registry, client_version=settings.client_version, model_version=settings.model_version,
            validate_invocation=sources.validators.invocation, validate_wait=sources.validators.wait,
            validate_recovery=sources.validators.recovery)
        feedback_assembler = feedback_input = None
        if feedback_settings is not None:
            from integration.owner_feedback_inputs import OwnerFeedbackInputAssembler
            feedback_assembler = OwnerFeedbackInputAssembler(assembler=assembler, worker=worker,
                feedback=sources.feedback, version=feedback_settings.version, read_guard=sources.read_guard,
                validate_current=sources.validate_feedback_input)
        callbacks = _descriptors(sources)
        declared = {'schema_version': 'owner-role-contract-host.v1', 'run_id': sources.store.run_id,
            'configuration_sha256': task_digest(config.model_dump(mode='json')),
            'source_factory': descriptor, 'source_version': sources.version, 'callbacks': callbacks,
            'action_id': settings.action_id, 'source_mode': assembler.source_mode,
            'assembler': module_factory_descriptor(assembler.build, settings.action_id),
            'worker': module_factory_descriptor(worker_type.execute, settings.action_id),
            'model_configuration_sha256': model_host.configuration_sha256 if model_host is not None else None}
        if feedback_assembler is not None:
            declared['feedback_input_configuration_sha256'] = task_digest(feedback_assembler._declared)
        # Configuration identity is stable across requests; invocation identity
        # remains in the original task and snapshots.
        key = 'owner_role_contract_host:' + config.host_id
        with sources.store._transaction():
            previous = sources.store._db.execute('SELECT value FROM metadata WHERE key=?', (key,)).fetchone()
            if previous is None:
                sources.store._db.execute('INSERT INTO metadata VALUES (?,?)', (key, canonical(declared)))
            elif json.loads(previous[0]) != declared:
                raise TaskConflict('Owner host configuration or code changed; explicit review required')
        if feedback_assembler is not None:
            feedback_input = feedback_assembler.prepare_and_register(context=request.context,
                action_input=request.action_input,
                feedback_sha256s=feedback_settings.selections[request.context.operation_id])
            prepared = feedback_input.prepared
        else:
            with sources.read_guard(request.context.model_copy(deep=True)):
                supplied = registration.contract.validate_input(request.action_input)
                values = supplied.model_dump(mode='json')
                prepared = assembler.build(request.context, **values)
                if prepared.action_input.model_dump(mode='json') != values:
                    raise TaskConflict('Owner assembly changes the original supplied input')
        supplement_notice_provenance = None
        if supplement_notice_settings is not None:
            from integration.government_owner_supplement_handoff import read_received_supplement_notice
            if sources.read_government_supplement is None:
                raise ValueError('Supplement notices require original Government reader and independent reception validator')
            supplement_notice_selection = supplement_notice_settings.selections[request.context.operation_id].model_dump(mode='json')
            with sources.read_guard(prepared.context.model_copy(deep=True)):
                supplement_notice_provenance = read_received_supplement_notice(prepared, **supplement_notice_selection,
                    read_supplement=sources.read_government_supplement, validate_reception=sources.validate_supplement_notice_reception)
        tender_evaluation_provenance = None
        if tender_evaluation_settings is not None:
            from integration.owner_tender_award_handoff import read_selected_tender_evaluation
            if sources.read_tender_evaluation is None:
                raise ValueError('Tender evaluation inputs require original reader and independent native selection validator')
            tender_evaluation_selection = tender_evaluation_settings.selections[request.context.operation_id].model_dump(mode='json')
            with sources.read_guard(prepared.context.model_copy(deep=True)):
                tender_evaluation_provenance = read_selected_tender_evaluation(prepared, **tender_evaluation_selection,
                    read_evaluation=sources.read_tender_evaluation, validate_selection=sources.validate_tender_award_selection)
        contractor_bid_provenance = None
        if contractor_bid_settings is not None:
            from integration.contractor_owner_tender_handoff import read_received_contractor_bids
            if sources.read_contractor_bid is None:
                raise ValueError('Received bids require original Contractor journal reader and independent reception validator')
            contractor_bid_selection = contractor_bid_settings.selections[request.context.operation_id].model_dump(mode='json')
            with sources.read_guard(prepared.context.model_copy(deep=True)):
                contractor_bid_provenance = read_received_contractor_bids(prepared, **contractor_bid_selection,
                    read_bid=sources.read_contractor_bid, validate_reception=sources.validate_contractor_bid_reception)
        research_provenance = None
        if research_settings is not None:
            from integration.qs_research_investment_handoff import read_received_qs_research
            research_selection = research_settings.selections[request.context.operation_id].model_dump(mode='json')
            with sources.read_guard(prepared.context.model_copy(deep=True)):
                research_provenance = read_received_qs_research(prepared, **research_selection,
                    read_qs_research=sources.read_qs_research, validate_reception=sources.validate_research_reception)
        closeout_continuation_provenance = None
        if closeout_continuation_settings is not None:
            from integration.owner_closeout_continuation_handoff import read_closeout_continuation_basis
            closeout_continuation_selection = closeout_continuation_settings.selections[request.context.operation_id].model_dump(mode='json')
            with sources.read_guard(prepared.context.model_copy(deep=True)):
                closeout_continuation_provenance = read_closeout_continuation_basis(prepared, **closeout_continuation_selection,
                    read_closeout_feedback=sources.read_closeout_feedback, validate_relation=sources.validate_closeout_continuation)
        handover_provenance = None
        if handover_settings is not None:
            from integration.contractor_owner_handover import read_received_owner_handover
            handover_selection = handover_settings.selections[request.context.operation_id].model_dump(mode='json')
            with sources.read_guard(prepared.context.model_copy(deep=True)):
                handover_provenance = read_received_owner_handover(prepared, **handover_selection,
                    read_contractor_closeout=sources.read_contractor_closeout,
                    validate_reception=sources.validate_handover_reception)
        payment_execution_provenance = None
        if payment_execution_settings is not None:
            from integration.owner_payment_execution_reception import read_received_owner_payment_executions
            payment_execution_selection = payment_execution_settings.selections[request.context.operation_id].model_dump(mode='json')
            with sources.read_guard(prepared.context.model_copy(deep=True)):
                payment_execution_provenance = read_received_owner_payment_executions(prepared, **payment_execution_selection,
                    read_owner_payment_execution=sources.read_owner_payment_execution,
                    validate_reception=sources.validate_owner_payment_execution_reception)
        bank_execution_provenance = None
        if bank_execution_settings is not None:
            from integration.bank_execution_owner_payment_handoff import read_received_bank_execution
            bank_execution_selection = bank_execution_settings.selections[request.context.operation_id].model_dump(mode='json')
            with sources.read_guard(prepared.context.model_copy(deep=True)):
                bank_execution_provenance = read_received_bank_execution(prepared, **bank_execution_selection,
                    read_bank_execution=sources.read_bank_execution,
                    validate_reception=sources.validate_bank_execution_reception)
        arrangement_provenance = None
        if arrangement_settings is not None:
            from integration.bank_arrangement_owner_payment_handoff import read_received_payment_arrangement
            arrangement_selection = arrangement_settings.selections[request.context.operation_id].model_dump(mode='json')
            with sources.read_guard(prepared.context.model_copy(deep=True)):
                arrangement_provenance = read_received_payment_arrangement(prepared, **arrangement_selection,
                    read_bank_arrangement=sources.read_bank_arrangement,
                    validate_reception=sources.validate_payment_arrangement_reception)
        offer_provenance = None
        if offer_settings is not None:
            from integration.bank_quote_owner_financing_handoff import read_received_financing_offer
            offer_selection = offer_settings.selections[request.context.operation_id].model_dump(mode='json')
            with sources.read_guard(prepared.context.model_copy(deep=True)):
                offer_provenance = read_received_financing_offer(prepared, **offer_selection,
                    read_bank_quote=sources.read_bank_quote,
                    validate_reception=sources.validate_financing_offer_reception)
        certificate_provenance = None
        if certificate_settings is not None:
            from integration.qs_certificate_owner_payment_handoff import (
                read_received_payment_certificate, read_received_payment_certificate_mapping,
            )
            certificate_values = certificate_selection.model_dump(mode='json')

            def read_certificate_input():
                if mapping_selection:
                    return read_received_payment_certificate_mapping(prepared, **certificate_values,
                        read_qs_payment=sources.read_qs_payment,
                        validate_mapping=sources.validate_payment_certificate_mapping)
                return read_received_payment_certificate(prepared, **certificate_values,
                    read_qs_payment=sources.read_qs_payment,
                    validate_reception=sources.validate_payment_certificate_reception)

            with sources.read_guard(prepared.context.model_copy(deep=True)):
                certificate_provenance = read_certificate_input()
        source_evidence = sources.evidence()
        if not isinstance(source_evidence, dict):
            raise ValueError('Owner source evidence must be an explicit object')
        original_request = request.model_dump(mode='json')
        executed = False

        def execute(invocation):
            nonlocal executed
            if executed or invocation.model_dump(mode='json') != original_request:
                raise TaskConflict('Owner executor requires its original invocation once, without replay')
            executed = True
            if (_descriptors(sources) != callbacks
                    or module_factory_descriptor(factory, settings.source_factory) != descriptor
                    or sources.registry is not worker.registry or prepared.runner.registry is not worker.registry
                    or prepared.runner.organizations is not sources.organizations
                    or assembler.provider is not sources.provider or worker.store is not sources.store
                    or assembler.methods is not sources.methods or sources.model_host is not model_host):
                raise TaskConflict('Owner original source components or callbacks changed before execution')
            with sources.read_guard(prepared.context.model_copy(deep=True)):
                if supplement_notice_settings is not None:
                    current_notice = read_received_supplement_notice(prepared, **supplement_notice_selection,
                        read_supplement=sources.read_government_supplement, validate_reception=sources.validate_supplement_notice_reception)
                    if current_notice != supplement_notice_provenance:
                        raise TaskConflict('Original Government supplement request or actual Owner notice intake changed before execution')
                if tender_evaluation_settings is not None:
                    current_evaluation = read_selected_tender_evaluation(prepared, **tender_evaluation_selection,
                        read_evaluation=sources.read_tender_evaluation, validate_selection=sources.validate_tender_award_selection)
                    if current_evaluation != tender_evaluation_provenance:
                        raise TaskConflict('Original tender evaluation or actual selected offer mapping changed before Owner award execution')
                if contractor_bid_settings is not None:
                    current_bids = read_received_contractor_bids(prepared, **contractor_bid_selection,
                        read_bid=sources.read_contractor_bid, validate_reception=sources.validate_contractor_bid_reception)
                    if current_bids != contractor_bid_provenance:
                        raise TaskConflict('Original Contractor bid journals or actual Owner intake mapping changed before execution')
                if research_settings is not None:
                    current_research = read_received_qs_research(prepared, **research_selection,
                        read_qs_research=sources.read_qs_research, validate_reception=sources.validate_research_reception)
                    if current_research != research_provenance:
                        raise TaskConflict('Original QS report reception or option mapping changed before Owner execution')
                if closeout_continuation_settings is not None:
                    current_closeout_continuation = read_closeout_continuation_basis(prepared, **closeout_continuation_selection,
                        read_closeout_feedback=sources.read_closeout_feedback, validate_relation=sources.validate_closeout_continuation)
                    if current_closeout_continuation != closeout_continuation_provenance:
                        raise TaskConflict('Original closeout feedback or current continuation duty mapping changed before execution')
                if handover_settings is not None:
                    current_handover = read_received_owner_handover(prepared, **handover_selection,
                        read_contractor_closeout=sources.read_contractor_closeout,
                        validate_reception=sources.validate_handover_reception)
                    if current_handover != handover_provenance:
                        raise TaskConflict('Original Contractor handover or actual reception changed before Owner execution')
                if payment_execution_settings is not None:
                    current_payment_execution = read_received_owner_payment_executions(prepared, **payment_execution_selection,
                        read_owner_payment_execution=sources.read_owner_payment_execution,
                        validate_reception=sources.validate_owner_payment_execution_reception)
                    if current_payment_execution != payment_execution_provenance:
                        raise TaskConflict('Original Owner payment commands, receipts or actual financial mapping changed before execution')
                if bank_execution_settings is not None:
                    current_bank_execution = read_received_bank_execution(prepared, **bank_execution_selection,
                        read_bank_execution=sources.read_bank_execution,
                        validate_reception=sources.validate_bank_execution_reception)
                    if current_bank_execution != bank_execution_provenance:
                        raise TaskConflict('Original Bank receipts or actual Owner execution changed before execution')
                if arrangement_settings is not None:
                    current_arrangement = read_received_payment_arrangement(prepared, **arrangement_selection,
                        read_bank_arrangement=sources.read_bank_arrangement,
                        validate_reception=sources.validate_payment_arrangement_reception)
                    if current_arrangement != arrangement_provenance:
                        raise TaskConflict('Original Bank confirmation or actual Owner arrangement changed before execution')
                if offer_settings is not None:
                    current_offer = read_received_financing_offer(prepared, **offer_selection,
                        read_bank_quote=sources.read_bank_quote,
                        validate_reception=sources.validate_financing_offer_reception)
                    if current_offer != offer_provenance:
                        raise TaskConflict('Original Bank quotation or actual received offer changed before execution')
                if certificate_settings is not None:
                    current_certificate = read_certificate_input()
                    if current_certificate != certificate_provenance:
                        raise TaskConflict('Original QS certificate or actual payment mapping changed before execution')
                option_preparation = prepare_role_contract_options(model_host=model_host, prepared=prepared)
                if feedback_input is None:
                    identity = worker.register(prepared, request_id=prepared.context.operation_id)
                else:
                    if sources.feedback is not feedback_assembler.feedback:
                        raise TaskConflict('Owner feedback source changed before execution')
                    identity = feedback_assembler.check_registration(feedback_input)
                outcome = worker.execute(identity, prepared)
                record = worker.get_record(identity)
                if record is None or record['result'] != outcome['result']:
                    raise TaskConflict('Owner execution lacks its original durable result')
                live_evidence = sources.evidence()
                if not isinstance(live_evidence, dict):
                    raise ValueError('Owner source evidence must be an explicit object')
                return RoleContractExecution(result=outcome['result'], evidence={
                    'identity': identity.as_dict(), 'task': outcome['task'], 'result_table': worker.RESULT_TABLE,
                    'record_sha256': record['record_sha256'], 'saved_audit': deepcopy(record['audit']),
                    'source_reading_sha256': record['source_reading_sha256'], 'sources': deepcopy(live_evidence),
                    'feedback_input': deepcopy(feedback_input.provenance) if feedback_input is not None else None,
                    'certificate_input': deepcopy(certificate_provenance),
                    'financing_offer_input': deepcopy(offer_provenance),
                    'payment_arrangement_input': deepcopy(arrangement_provenance),
                    'bank_execution_input': deepcopy(bank_execution_provenance),
                    'payment_execution_input': deepcopy(payment_execution_provenance),
                    'handover_input': deepcopy(handover_provenance),
                    'closeout_continuation_input': deepcopy(closeout_continuation_provenance),
                    'research_comparison_input': deepcopy(research_provenance),
                    'received_contractor_bid_input': deepcopy(contractor_bid_provenance),
                    'tender_evaluation_input': deepcopy(tender_evaluation_provenance),
                    'supplement_notice_input': deepcopy(supplement_notice_provenance),
                    'option_preparation': deepcopy(option_preparation),
                    'model_host': model_host.evidence() if model_host is not None else None})

        return RoleContractHost(runner=prepared.runner, version='owner-role-contract-host.v1',
            close=sources.close, evidence={'configuration': declared, 'sources': deepcopy(source_evidence),
                'certificate_input': deepcopy(certificate_provenance), 'financing_offer_input': deepcopy(offer_provenance),
                'payment_arrangement_input': deepcopy(arrangement_provenance),
                'bank_execution_input': deepcopy(bank_execution_provenance),
                'payment_execution_input': deepcopy(payment_execution_provenance),
                'handover_input': deepcopy(handover_provenance),
                'closeout_continuation_input': deepcopy(closeout_continuation_provenance),
                'research_comparison_input': deepcopy(research_provenance),
                'received_contractor_bid_input': deepcopy(contractor_bid_provenance),
                'tender_evaluation_input': deepcopy(tender_evaluation_provenance),
                'supplement_notice_input': deepcopy(supplement_notice_provenance)},
            execute=execute)
    except Exception:
        sources.close()
        raise
