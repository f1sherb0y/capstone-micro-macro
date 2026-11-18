"""One explicit host assembly for Supplier quote sources, outcomes and order decisions."""
from copy import deepcopy
from dataclasses import dataclass, fields
from typing import Callable

from integration.action_model_host import ActionModelHost, resolve_action_model_host
from integration.commercial_actions import CommercialActionAssembler, PreparedCommercialAction
from integration.commercial_worker import CommercialTaskWorker
from integration.commercial_callbacks import CommercialNextSelection, build_commercial_successor_dispatcher
from integration.commercial_runtime import CommercialRuntimeNextSelection
from integration.task_continuation import ObservationContinuationDispatcher
from integration.supplier_execution_actions import PreparedSupplierExecution, SupplierExecutionActionAssembler
from integration.supplier_execution_results import SupplierExecutionResultWorker
from integration.supplier_order_actions import SupplierOrderActionAssembler
from integration.supplier_order_results import SupplierOrderResultWorker
from integration.supplier_product_actions import PreparedSupplierProduct, SupplierProductActionAssembler
from integration.supplier_product_results import SupplierProductResultWorker
from integration.supplier_planning_actions import PreparedSupplierPlanning, SupplierPlanningActionAssembler
from integration.supplier_planning_results import SupplierPlanningResultWorker
from integration.supplier_quality_actions import PreparedSupplierQuality, SupplierQualityActionAssembler
from integration.supplier_quality_results import SupplierQualityResultWorker
from integration.supplier_logistics_actions import PreparedSupplierLogistics, SupplierLogisticsActionAssembler
from integration.supplier_logistics_results import SupplierLogisticsResultWorker
from integration.supplier_receiving_actions import PreparedSupplierReceiving, SupplierReceivingActionAssembler
from integration.supplier_receiving_results import SupplierReceivingResultWorker
from integration.supplier_payment_actions import PreparedSupplierPayment, SupplierPaymentActionAssembler
from integration.supplier_payment_results import SupplierPaymentResultWorker
from integration.supplier_remedy_actions import PreparedSupplierRemedy, SupplierRemedyActionAssembler
from integration.supplier_remedy_results import SupplierRemedyResultWorker
from integration.supplier_advice_actions import PreparedSupplierAdvice, SupplierAdviceActionAssembler
from integration.supplier_advice_results import SupplierAdviceResultWorker
from integration.supplier_screening_actions import PreparedSupplierScreening, SupplierScreeningActionAssembler
from integration.supplier_screening_results import SupplierScreeningResultWorker
from integration.supplier_source_provider import SupplierActionViewProvider
from integration.supplier_procurement_pipeline import SupplierProcurementPipeline
from integration.supplier_quote_actions import SupplierQuoteActionAssembler
from integration.supplier_quote_cost_publication import (
    SupplierQuoteCostPublicationStore, SupplierQuoteCostPublishedViewProvider,
)
from integration.supplier_quote_results import SupplierQuoteResultWorker
from src.actions.contracts.common import ActionContext
from src.actions.registry import ActionRegistry
from src.coordination.invocations import InvocationSnapshotStore
from src.coordination.continuations import ContinuationJournal
from src.coordination.tasks import TaskConflict, TaskIdentity, TaskStore
from src.organization.registry import OrganizationRegistry


@dataclass(frozen=True)
class SupplierProcurementValidators:
    """Actual host checks; each callback retains its original worker/source signature."""
    publication_sources: Callable
    quote_invocation: Callable
    quote_wait: Callable
    quote_recovery: Callable
    order_invocation: Callable
    order_wait: Callable
    order_recovery: Callable
    quote_history: Callable
    native_offer: Callable

    def __post_init__(self):
        if any(not callable(getattr(self, field.name)) for field in fields(self)):
            raise ValueError('Every Supplier source, invocation, wait, recovery and handoff check must be explicit')


@dataclass(frozen=True)
class SupplierProductValidators:
    """A02 checks, A03 proposal relation and optional original A01 inquiry relation."""
    invocation: Callable
    wait: Callable
    recovery: Callable
    history: Callable
    proposal_source: Callable
    screening_history: Callable | None = None
    inquiry_source: Callable | None = None

    def __post_init__(self):
        if any(not callable(getattr(self, name)) for name in ('invocation', 'wait', 'recovery', 'history', 'proposal_source')):
            raise ValueError('All product execution, wait, recovery, history and actual proposal checks required')
        if (self.screening_history is not None or self.inquiry_source is not None) and (
                not callable(self.screening_history) or not callable(self.inquiry_source)):
            raise ValueError('Screening history and actual received inquiry checks must be configured together')


@dataclass(frozen=True)
class SupplierPlanningValidators:
    """Explicit A05 execution and original-order handoff checks."""
    invocation: Callable
    wait: Callable
    recovery: Callable
    order_history: Callable
    order_source: Callable

    def __post_init__(self):
        if any(not callable(getattr(self, field.name)) for field in fields(self)):
            raise ValueError('All planning execution, wait, recovery, order history and source checks required')


@dataclass(frozen=True)
class SupplierExecutionValidators:
    """Explicit A06 checks plus saved plan and actual task/release source checks."""
    invocation: Callable
    wait: Callable
    recovery: Callable
    planning_history: Callable
    task_source: Callable

    def __post_init__(self):
        if any(not callable(getattr(self, field.name)) for field in fields(self)):
            raise ValueError('All execution, wait, recovery, planning history and actual task checks required')


@dataclass(frozen=True)
class SupplierQualityValidators:
    """Actual quality checks and current production-receipt/batch relation."""
    invocation: Callable
    wait: Callable
    recovery: Callable
    execution_history: Callable
    batch_source: Callable

    def __post_init__(self):
        if any(not callable(getattr(self, field.name)) for field in fields(self)):
            raise ValueError('All quality, wait, recovery, execution history and actual batch checks required')


@dataclass(frozen=True)
class SupplierLogisticsValidators:
    """Explicit transport checks and saved quality-to-actual-release source checks."""
    invocation: Callable
    wait: Callable
    recovery: Callable
    quality_history: Callable
    release_source: Callable

    def __post_init__(self):
        if any(not callable(getattr(self, field.name)) for field in fields(self)):
            raise ValueError('All logistics, wait, recovery, quality history and actual release checks required')


@dataclass(frozen=True)
class SupplierReceivingValidators:
    """Explicit receiving checks plus original logistics and actual Shipment relation."""
    invocation: Callable
    wait: Callable
    recovery: Callable
    logistics_history: Callable
    shipment_source: Callable

    def __post_init__(self):
        if any(not callable(getattr(self, field.name)) for field in fields(self)):
            raise ValueError('All receiving, wait, recovery, logistics history and actual shipment checks required')


@dataclass(frozen=True)
class SupplierPaymentValidators:
    """Actual A10 checks and saved receiving-to-contract-delivery source checks."""
    invocation: Callable
    wait: Callable
    recovery: Callable
    receiving_history: Callable
    delivery_source: Callable

    def __post_init__(self):
        if any(not callable(getattr(self, field.name)) for field in fields(self)):
            raise ValueError('All payment, wait, recovery, receiving history and actual delivery checks required')


@dataclass(frozen=True)
class SupplierRemedyValidators:
    """Explicit checks for original remedy invocation, waiting and recovery."""
    invocation: Callable
    wait: Callable
    recovery: Callable

    def __post_init__(self):
        if any(not callable(getattr(self, field.name)) for field in fields(self)):
            raise ValueError('All remedy invocation, wait and recovery checks required')


@dataclass(frozen=True)
class SupplierAdviceValidators:
    """Explicit consultation invocation, waiting and recovery checks."""
    invocation: Callable
    wait: Callable
    recovery: Callable

    def __post_init__(self):
        if any(not callable(getattr(self, field.name)) for field in fields(self)):
            raise ValueError('All advice invocation, wait and recovery checks required')


@dataclass(frozen=True)
class SupplierScreeningValidators:
    """Explicit screening invocation, waiting and recovery checks."""
    invocation: Callable
    wait: Callable
    recovery: Callable

    def __post_init__(self):
        if any(not callable(getattr(self, field.name)) for field in fields(self)):
            raise ValueError('All screening invocation, wait and recovery checks required')


@dataclass(frozen=True)
class SupplierCommercialValidators:
    """Original A12 invocation, wait and saved-result recovery host checks."""
    invocation: Callable
    wait: Callable
    recovery: Callable

    def __post_init__(self):
        if any(not callable(getattr(self, field.name)) for field in fields(self)):
            raise ValueError('All commercial invocation, wait and recovery checks required')


@dataclass(frozen=True)
class SupplierCommercialFeedback:
    """Original recipient inbox and explicit current/next selection and signal projection."""
    inbox: object
    select_current: Callable
    select_next: Callable
    project_signal: Callable

    def __post_init__(self):
        if (not callable(getattr(self.inbox, 'for_organization', None))
                or any(not callable(getattr(self, name)) for name in ('select_current', 'select_next', 'project_signal'))):
            raise ValueError('Commercial feedback requires actual inbox and explicit host selection/signal callbacks')


class SupplierProcurementRuntime:
    """Construct same-store components without executing a Supplier action.

    Host owns the provider, guards, actual professional records and external
    client. Public pipeline operations remain explicit, including every next
    context/token and source adoption. This assembly opens no model connection,
    selects no source and performs no formal offer/order submission or polling.
    Existing snapshots/publications can be supplied for original-store reuse.
    """
    VERSION = 'supplier-procurement-runtime.v16'

    def __init__(self, *, store, registry, organizations, provider, macro_version,
            source_mode, client_version, validators, read_guard, model_version=None,
            snapshots=None, publications=None, methods=None, audit_sink=None,
            policy_version=None, decision_strategies=(), model_host=None, product_validators=None,
            planning_validators=None, execution_validators=None, quality_validators=None,
            logistics_validators=None, receiving_validators=None, payment_validators=None,
            remedy_validators=None, advice_validators=None, screening_validators=None,
            commercial_validators=None, commercial_journal=None, commercial_feedback=None):
        if (not isinstance(store, TaskStore) or not isinstance(registry, ActionRegistry)
                or not isinstance(organizations, OrganizationRegistry) or organizations.run_id != store.run_id
                or not isinstance(validators, SupplierProcurementValidators) or not callable(read_guard)
                or not callable(getattr(provider, 'project', None))):
            raise ValueError('Supplier runtime requires original same-run store/registry, actual provider, validators and guard')
        if (source_mode not in {'formal', 'fixture'}
                or any(not isinstance(value, str) or not value.strip() for value in (macro_version, client_version))):
            raise ValueError('Explicit source mode, macro version and client version required')
        if product_validators is not None and not isinstance(product_validators, SupplierProductValidators):
            raise ValueError('Product integration requires its actual typed host validators')
        if planning_validators is not None and not isinstance(planning_validators, SupplierPlanningValidators):
            raise ValueError('Planning integration requires its actual typed host validators')
        if execution_validators is not None and not isinstance(execution_validators, SupplierExecutionValidators):
            raise ValueError('Execution integration requires its actual typed host validators')
        if quality_validators is not None and not isinstance(quality_validators, SupplierQualityValidators):
            raise ValueError('Quality integration requires its actual typed host validators')
        if logistics_validators is not None and not isinstance(logistics_validators, SupplierLogisticsValidators):
            raise ValueError('Logistics integration requires its actual typed host validators')
        if receiving_validators is not None and not isinstance(receiving_validators, SupplierReceivingValidators):
            raise ValueError('Receiving integration requires its actual typed host validators')
        if payment_validators is not None and not isinstance(payment_validators, SupplierPaymentValidators):
            raise ValueError('Payment integration requires its actual typed host validators')
        if remedy_validators is not None and not isinstance(remedy_validators, SupplierRemedyValidators):
            raise ValueError('Remedy integration requires its actual typed host validators')
        if advice_validators is not None and not isinstance(advice_validators, SupplierAdviceValidators):
            raise ValueError('Advice integration requires its actual typed host validators')
        if screening_validators is not None and not isinstance(screening_validators, SupplierScreeningValidators):
            raise ValueError('Screening integration requires its actual typed host validators')
        if (commercial_validators is not None or commercial_journal is not None or commercial_feedback is not None) and (
                not isinstance(commercial_validators, SupplierCommercialValidators)
                or (commercial_journal is None) == (commercial_feedback is None)
                or commercial_journal is not None and (
                    not isinstance(commercial_journal, ContinuationJournal) or commercial_journal.store is not store)
                or commercial_feedback is not None and (
                    not isinstance(commercial_feedback, SupplierCommercialFeedback)
                    or getattr(commercial_feedback.inbox, 'run_id', None) != store.run_id
                    or getattr(commercial_feedback.inbox, 'organization_ids', None) != store.organization_ids)):
            raise ValueError('Commercial integration requires validators and exactly one original journal or same-run feedback configuration')
        action_ids = ('SUPPLIER-A03', 'SUPPLIER-A04')
        if product_validators is not None:
            action_ids = ('SUPPLIER-A02', *action_ids)
        if planning_validators is not None:
            action_ids = (*action_ids, 'SUPPLIER-A05')
        if execution_validators is not None:
            action_ids = (*action_ids, 'SUPPLIER-A06')
        if quality_validators is not None:
            action_ids = (*action_ids, 'SUPPLIER-A07')
        if logistics_validators is not None:
            action_ids = (*action_ids, 'SUPPLIER-A08')
        if receiving_validators is not None:
            action_ids = (*action_ids, 'SUPPLIER-A09')
        if payment_validators is not None:
            action_ids = (*action_ids, 'SUPPLIER-A10')
        if remedy_validators is not None:
            action_ids = (*action_ids, 'SUPPLIER-A11')
        if advice_validators is not None:
            action_ids = (*action_ids, 'SUPPLIER-A13')
        if screening_validators is not None:
            action_ids = ('SUPPLIER-A01', *action_ids)
        if commercial_validators is not None:
            action_ids = (*action_ids, 'SUPPLIER-A12')
        for action_id in action_ids:
            registration = registry.get(action_id)
            if not registration.implemented or registration.skill is None or registration.role != 'Supplier':
                raise ValueError('Supplier runtime requires original implemented contracts, Skills and processors for every configured action')
        for organization_id in store.organization_ids:
            organizations.get(organization_id)
        if snapshots is not None and (not isinstance(snapshots, InvocationSnapshotStore) or snapshots.store is not store):
            raise ValueError('Supplier invocation snapshots must use the original TaskStore')
        if model_host is not None and (not isinstance(model_host, ActionModelHost) or model_host.store is not store):
            raise ValueError('Supplier model host must share the exact original TaskStore and budget')
        bindings = tuple(decision_strategies)
        selected_model_version, _ = resolve_action_model_host(registry=registry, run_id=store.run_id,
            model_version=model_version, decision_strategies=bindings, model_host=model_host)
        if not isinstance(selected_model_version, str) or not selected_model_version.strip():
            raise ValueError('Explicit model/execution version required; runtime creates no default model')
        if isinstance(provider, SupplierQuoteCostPublishedViewProvider):
            if publications is not None and publications is not provider.publications:
                raise ValueError('Configured Supplier provider uses another publication store')
            publications = provider.publications
        if publications is not None and (not isinstance(publications, SupplierQuoteCostPublicationStore)
                or publications.store is not store or publications.organizations is not organizations
                or publications.validate_source != validators.publication_sources):
            raise ValueError('Supplier publications must retain original store/registry and selected source validator')

        self.store, self.registry, self.organizations = store, registry, organizations
        self.validators, self.read_guard = validators, read_guard
        self.product_validators = product_validators
        self.planning_validators = planning_validators
        self.execution_validators = execution_validators
        self.quality_validators = quality_validators
        self.logistics_validators = logistics_validators
        self.receiving_validators = receiving_validators
        self.payment_validators = payment_validators
        self.remedy_validators = remedy_validators
        self.advice_validators = advice_validators
        self.screening_validators = screening_validators
        self.commercial_validators, self.commercial_journal = commercial_validators, commercial_journal
        self.commercial_feedback = commercial_feedback
        self.client_version, self.model_version = client_version, selected_model_version
        self.macro_version, self.source_mode = macro_version, source_mode
        self.model_host = model_host
        self.snapshots = InvocationSnapshotStore(store) if snapshots is None else snapshots
        self.publications = (SupplierQuoteCostPublicationStore(store=store, organizations=organizations,
            validate_source=validators.publication_sources) if publications is None else publications)
        self.provider = (provider if isinstance(provider, SupplierQuoteCostPublishedViewProvider) else
            SupplierQuoteCostPublishedViewProvider(provider=provider, publications=self.publications))
        self.original_provider = self.provider.provider
        if isinstance(self.original_provider, SupplierActionViewProvider) and (
                self.original_provider.store is not store or self.original_provider.registry is not registry
                or self.original_provider.organizations is not organizations
                or self.original_provider.macro_version != macro_version or self.original_provider.source_mode != source_mode
                or not set(action_ids) <= set(self.original_provider.sources)):
            raise ValueError('Supplier source routes must share original store/registries/mode/version and cover configured actions')
        common = {'registry': registry, 'organizations': organizations, 'provider': self.provider,
            'macro_version': macro_version, 'source_mode': source_mode, 'methods': methods,
            'audit_sink': audit_sink, 'policy_version': policy_version, 'model_version': selected_model_version,
            'decision_strategies': bindings, 'model_host': model_host}
        self.quote_assembler = SupplierQuoteActionAssembler(**common)
        self.order_assembler = SupplierOrderActionAssembler(**common)
        worker_common = {'store': store, 'snapshots': self.snapshots, 'registry': registry,
            'client_version': client_version, 'model_version': selected_model_version}
        self.quote_worker = SupplierQuoteResultWorker(**worker_common,
            validate_invocation=validators.quote_invocation, validate_wait=validators.quote_wait,
            validate_recovery=validators.quote_recovery)
        self.order_worker = SupplierOrderResultWorker(**worker_common,
            validate_invocation=validators.order_invocation, validate_wait=validators.order_wait,
            validate_recovery=validators.order_recovery)
        self.product_assembler, self.product_worker = None, None
        if product_validators is not None:
            self.product_assembler = SupplierProductActionAssembler(**common)
            self.product_worker = SupplierProductResultWorker(**worker_common,
                validate_invocation=product_validators.invocation, validate_wait=product_validators.wait,
                validate_recovery=product_validators.recovery)
        self.planning_assembler, self.planning_worker = None, None
        if planning_validators is not None:
            self.planning_assembler = SupplierPlanningActionAssembler(**common)
            self.planning_worker = SupplierPlanningResultWorker(**worker_common,
                validate_invocation=planning_validators.invocation, validate_wait=planning_validators.wait,
                validate_recovery=planning_validators.recovery)
        self.execution_assembler, self.execution_worker = None, None
        if execution_validators is not None:
            self.execution_assembler = SupplierExecutionActionAssembler(**common)
            self.execution_worker = SupplierExecutionResultWorker(**worker_common,
                validate_invocation=execution_validators.invocation, validate_wait=execution_validators.wait,
                validate_recovery=execution_validators.recovery)
        self.quality_assembler, self.quality_worker = None, None
        if quality_validators is not None:
            self.quality_assembler = SupplierQualityActionAssembler(**common)
            self.quality_worker = SupplierQualityResultWorker(**worker_common,
                validate_invocation=quality_validators.invocation, validate_wait=quality_validators.wait,
                validate_recovery=quality_validators.recovery)
        self.logistics_assembler, self.logistics_worker = None, None
        if logistics_validators is not None:
            self.logistics_assembler = SupplierLogisticsActionAssembler(**common)
            self.logistics_worker = SupplierLogisticsResultWorker(**worker_common,
                validate_invocation=logistics_validators.invocation, validate_wait=logistics_validators.wait,
                validate_recovery=logistics_validators.recovery)
        self.receiving_assembler, self.receiving_worker = None, None
        if receiving_validators is not None:
            self.receiving_assembler = SupplierReceivingActionAssembler(**common)
            self.receiving_worker = SupplierReceivingResultWorker(**worker_common,
                validate_invocation=receiving_validators.invocation, validate_wait=receiving_validators.wait,
                validate_recovery=receiving_validators.recovery)
        self.payment_assembler, self.payment_worker = None, None
        if payment_validators is not None:
            self.payment_assembler = SupplierPaymentActionAssembler(**common)
            self.payment_worker = SupplierPaymentResultWorker(**worker_common,
                validate_invocation=payment_validators.invocation, validate_wait=payment_validators.wait,
                validate_recovery=payment_validators.recovery)
        self.remedy_assembler, self.remedy_worker = None, None
        if remedy_validators is not None:
            self.remedy_assembler = SupplierRemedyActionAssembler(**common)
            self.remedy_worker = SupplierRemedyResultWorker(**worker_common,
                validate_invocation=remedy_validators.invocation, validate_wait=remedy_validators.wait,
                validate_recovery=remedy_validators.recovery)
        self.advice_assembler, self.advice_worker = None, None
        if advice_validators is not None:
            self.advice_assembler = SupplierAdviceActionAssembler(**common)
            self.advice_worker = SupplierAdviceResultWorker(**worker_common,
                validate_invocation=advice_validators.invocation, validate_wait=advice_validators.wait,
                validate_recovery=advice_validators.recovery)
        self.screening_assembler, self.screening_worker = None, None
        if screening_validators is not None:
            self.screening_assembler = SupplierScreeningActionAssembler(**common)
            self.screening_worker = SupplierScreeningResultWorker(**worker_common,
                validate_invocation=screening_validators.invocation, validate_wait=screening_validators.wait,
                validate_recovery=screening_validators.recovery)
        self.commercial_assembler, self.commercial_worker = None, None
        self.commercial_dispatcher = None
        if commercial_validators is not None:
            self.commercial_assembler = CommercialActionAssembler(**common)
            if commercial_feedback is not None:
                def select_persisted_next(*, source, signal, request_id):
                    identity = TaskIdentity(**source['identity'])
                    if identity.action_id != 'SUPPLIER-A12' or identity.role != 'Supplier':
                        raise TaskConflict('Supplier feedback cannot select another role/action successor')
                    snapshot = self.snapshots.get(identity)
                    selected = commercial_feedback.select_next(source=deepcopy(source),
                        signal=signal.model_copy(deep=True), request_id=request_id, original_snapshot=deepcopy(snapshot))
                    if not isinstance(selected, CommercialRuntimeNextSelection):
                        raise TaskConflict('Supplier feedback requires typed current selection and retained original snapshot')
                    selected = deepcopy(selected)
                    return CommercialNextSelection(original_context=ActionContext.model_validate(snapshot['context']),
                        context=selected.context, profile_ref=selected.profile_ref,
                        current_refs=selected.current_refs, request_id=selected.request_id)

                self.commercial_dispatcher = build_commercial_successor_dispatcher(
                    inbox=commercial_feedback.inbox, store=store, assembler=self.commercial_assembler,
                    select_current=commercial_feedback.select_current, select_next=select_persisted_next,
                    project_signal=commercial_feedback.project_signal, client_version=client_version,
                    model_version=selected_model_version, action_ids={'SUPPLIER-A12'})
                self.commercial_journal = self.commercial_dispatcher.journal
            self.commercial_worker = CommercialTaskWorker(assembler=self.commercial_assembler,
                journal=self.commercial_journal, snapshots=self.snapshots, client_version=client_version,
                model_version=selected_model_version, validate_invocation=commercial_validators.invocation,
                validate_wait=commercial_validators.wait, validate_recovery=commercial_validators.recovery)
        self.pipeline = SupplierProcurementPipeline(quote_assembler=self.quote_assembler,
            quote_worker=self.quote_worker, order_assembler=self.order_assembler, order_worker=self.order_worker,
            read_guard=read_guard, validate_history=validators.quote_history, validate_offer=validators.native_offer)

    def source_health(self, context, *, required_refs=()):
        """Read original source health evidence under the guard without performing a source query."""
        context = ActionContext.model_validate(context).model_copy(deep=True)
        provider = self.original_provider
        if (not isinstance(provider, SupplierActionViewProvider) or provider.store is not self.store
                or provider.registry is not self.registry or provider.organizations is not self.organizations
                or provider.macro_version != self.macro_version or provider.source_mode != self.source_mode
                or self.provider.provider is not provider or context.run_id != self.store.run_id
                or context.contract_ref.kind != 'ActionContract'):
            raise TaskConflict('Supplier source health requires its original configured source provider and context')
        with self.read_guard():
            grants = self.organizations.grants(context, context.contract_ref.id, 'Supplier')
            return provider.health(context=context, organization_id=grants[0].organization_id, required_refs=required_refs)

    def _require_products(self):
        if (not isinstance(self.product_validators, SupplierProductValidators)
                or not isinstance(self.product_assembler, SupplierProductActionAssembler)
                or not isinstance(self.product_worker, SupplierProductResultWorker)
                or self.product_worker.store is not self.store or self.product_worker.snapshots is not self.snapshots
                or self.product_worker.registry is not self.registry
                or self.product_assembler.registry is not self.registry
                or self.product_assembler.organizations is not self.organizations
                or self.product_assembler.view_provider is not self.provider
                or self.product_worker.client_version != self.client_version
                or self.product_worker.model_version != self.model_version):
            raise TaskConflict('Product operation requires explicitly configured original same-store A02 components and validators')
        return self.product_assembler, self.product_worker

    def prepare_product(self, context, **product_refs):
        """Assemble explicit A02 sources without executing a product processor."""
        assembler, _ = self._require_products()
        with self.read_guard():
            return assembler.build(context, **product_refs)

    def prepare_product_from_screening(self, context, *, screening_identity,
            screening_execution_versions, basis_ref, **product_refs):
        """Use original same-store A01 history and independently received A02 inquiry."""
        assembler, _ = self._require_products()
        _, screening_worker = self._require_screening()
        if (not callable(self.product_validators.screening_history)
                or not callable(self.product_validators.inquiry_source)):
            raise TaskConflict('Product screening handoff requires explicit history and actual inquiry validators')
        with self.read_guard():
            return assembler.build_from_screening(context, screening_worker=screening_worker,
                screening_identity=screening_identity, screening_execution_versions=screening_execution_versions,
                basis_ref=basis_ref, validate_history=self.product_validators.screening_history,
                validate_current=self.product_validators.inquiry_source, **product_refs)

    def execute_product(self, prepared, *, request_id, purpose='action'):
        """Persist one original A02 outcome without creating an approved native proposal."""
        _, worker = self._require_products()
        if (not isinstance(prepared, PreparedSupplierProduct)
                or prepared.context.contract_ref.id != 'SUPPLIER-A02'):
            raise TaskConflict('Product execution requires its exact prepared A02 invocation')
        with self.read_guard():
            identity = worker.register(prepared, request_id=request_id, purpose=purpose)
            outcome = worker.execute(identity, prepared)
            return {**outcome, 'identity': identity}

    def prepare_quote_from_products(self, context, *, product_identity,
            product_execution_versions, basis_ref, **quote_refs):
        """Use explicitly selected saved A02 provenance and actual current proposals."""
        _, worker = self._require_products()
        return self.pipeline.prepare_quote_from_products(context, product_worker=worker,
            product_identity=product_identity, product_execution_versions=product_execution_versions,
            basis_ref=basis_ref, validate_product_history=self.product_validators.history,
            validate_product_source=self.product_validators.proposal_source, **quote_refs)

    def _require_planning(self):
        if (not isinstance(self.planning_validators, SupplierPlanningValidators)
                or not isinstance(self.planning_assembler, SupplierPlanningActionAssembler)
                or not isinstance(self.planning_worker, SupplierPlanningResultWorker)
                or self.planning_worker.store is not self.store
                or self.planning_worker.snapshots is not self.snapshots
                or self.planning_worker.registry is not self.registry
                or self.planning_assembler.registry is not self.registry
                or self.planning_assembler.organizations is not self.organizations
                or self.planning_assembler.view_provider is not self.provider
                or self.planning_worker.client_version != self.client_version
                or self.planning_worker.model_version != self.model_version):
            raise TaskConflict('Planning operation requires explicitly configured original same-store A05 components and validators')
        return self.planning_assembler, self.planning_worker

    def prepare_planning(self, context, **planning_refs):
        """Assemble explicit A05 sources without executing a planning processor."""
        assembler, _ = self._require_planning()
        with self.read_guard():
            return assembler.build(context, **planning_refs)

    def execute_planning(self, prepared, *, request_id, purpose='action'):
        """Persist one original A05 result without creating SupplyTask, stock or reservation effects."""
        _, worker = self._require_planning()
        if (not isinstance(prepared, PreparedSupplierPlanning)
                or prepared.context.contract_ref.id != 'SUPPLIER-A05'):
            raise TaskConflict('Planning execution requires its exact prepared A05 invocation')
        with self.read_guard():
            identity = worker.register(prepared, request_id=request_id, purpose=purpose)
            outcome = worker.execute(identity, prepared)
            return {**outcome, 'identity': identity}

    def prepare_planning_from_order(self, context, *, order_identity,
            order_execution_versions, basis_ref, **planning_refs):
        """Use an explicitly selected saved A04 acceptance and actual current order."""
        assembler, _ = self._require_planning()
        if (not isinstance(self.order_worker, SupplierOrderResultWorker)
                or self.order_worker.store is not self.store or self.order_worker.snapshots is not self.snapshots
                or self.order_worker.registry is not self.registry
                or self.order_worker.client_version != self.client_version
                or self.order_worker.model_version != self.model_version):
            raise TaskConflict('Planning order handoff requires the original same-store A04 worker')
        with self.read_guard():
            return assembler.build_from_order(context, order_worker=self.order_worker,
                order_identity=order_identity, order_execution_versions=order_execution_versions,
                basis_ref=basis_ref, validate_history=self.planning_validators.order_history,
                validate_current=self.planning_validators.order_source, **planning_refs)

    def _require_execution(self):
        if (not isinstance(self.execution_validators, SupplierExecutionValidators)
                or not isinstance(self.execution_assembler, SupplierExecutionActionAssembler)
                or not isinstance(self.execution_worker, SupplierExecutionResultWorker)
                or self.execution_worker.store is not self.store
                or self.execution_worker.snapshots is not self.snapshots
                or self.execution_worker.registry is not self.registry
                or self.execution_assembler.registry is not self.registry
                or self.execution_assembler.organizations is not self.organizations
                or self.execution_assembler.view_provider is not self.provider
                or self.execution_worker.client_version != self.client_version
                or self.execution_worker.model_version != self.model_version):
            raise TaskConflict('Execution requires configured original same-store A06 components and validators')
        return self.execution_assembler, self.execution_worker

    def prepare_execution(self, context, **execution_refs):
        """Assemble the explicit task/setup; construction requests no native execution."""
        assembler, _ = self._require_execution()
        with self.read_guard():
            return assembler.build(context, **execution_refs)

    def execute_execution(self, prepared, *, request_id, purpose='action'):
        """Persist one original A06 request/query result using the existing claim-once worker."""
        _, worker = self._require_execution()
        if (not isinstance(prepared, PreparedSupplierExecution)
                or prepared.context.contract_ref.id != 'SUPPLIER-A06'):
            raise TaskConflict('Execution requires its original prepared A06 invocation')
        with self.read_guard():
            identity = worker.register(prepared, request_id=request_id, purpose=purpose)
            outcome = worker.execute(identity, prepared)
            return {**outcome, 'identity': identity}

    def prepare_execution_from_planning(self, context, *, planning_identity,
            planning_execution_versions, basis_ref, **execution_refs):
        """Bind a selected saved A05 plan to the actual task and independent release."""
        assembler, _ = self._require_execution()
        _, planning_worker = self._require_planning()
        with self.read_guard():
            return assembler.build_from_planning(context, planning_worker=planning_worker,
                planning_identity=planning_identity, planning_execution_versions=planning_execution_versions,
                basis_ref=basis_ref, validate_history=self.execution_validators.planning_history,
                validate_current=self.execution_validators.task_source, **execution_refs)

    def _require_quality(self):
        if (not isinstance(self.quality_validators, SupplierQualityValidators)
                or not isinstance(self.quality_assembler, SupplierQualityActionAssembler)
                or not isinstance(self.quality_worker, SupplierQualityResultWorker)
                or self.quality_worker.store is not self.store or self.quality_worker.snapshots is not self.snapshots
                or self.quality_worker.registry is not self.registry
                or self.quality_assembler.registry is not self.registry
                or self.quality_assembler.organizations is not self.organizations
                or self.quality_assembler.view_provider is not self.provider
                or self.quality_worker.client_version != self.client_version
                or self.quality_worker.model_version != self.model_version):
            raise TaskConflict('Quality requires configured original same-store A07 components and validators')
        return self.quality_assembler, self.quality_worker

    def prepare_quality(self, context, **quality_refs):
        """Assemble the explicitly selected actual batch and quality sources."""
        assembler, _ = self._require_quality()
        with self.read_guard():
            return assembler.build(context, **quality_refs)

    def execute_quality(self, prepared, *, request_id, purpose='action'):
        """Persist one original quality request/decision without native inspection or stock effects."""
        _, worker = self._require_quality()
        if not isinstance(prepared, PreparedSupplierQuality) or prepared.context.contract_ref.id != 'SUPPLIER-A07':
            raise TaskConflict('Quality execution requires its original prepared A07 invocation')
        with self.read_guard():
            identity = worker.register(prepared, request_id=request_id, purpose=purpose)
            outcome = worker.execute(identity, prepared)
            return {**outcome, 'identity': identity}

    def prepare_quality_from_execution(self, context, *, execution_identity,
            execution_versions, basis_ref, **quality_refs):
        """Bind a selected saved A06 outcome and actual receipt to the current quality batch."""
        assembler, _ = self._require_quality()
        _, execution_worker = self._require_execution()
        with self.read_guard():
            return assembler.build_from_execution(context, execution_worker=execution_worker,
                execution_identity=execution_identity, execution_versions=execution_versions,
                basis_ref=basis_ref, validate_history=self.quality_validators.execution_history,
                validate_current=self.quality_validators.batch_source, **quality_refs)

    def _require_logistics(self):
        if (not isinstance(self.logistics_validators, SupplierLogisticsValidators)
                or not isinstance(self.logistics_assembler, SupplierLogisticsActionAssembler)
                or not isinstance(self.logistics_worker, SupplierLogisticsResultWorker)
                or self.logistics_worker.store is not self.store or self.logistics_worker.snapshots is not self.snapshots
                or self.logistics_worker.registry is not self.registry
                or self.logistics_assembler.registry is not self.registry
                or self.logistics_assembler.organizations is not self.organizations
                or self.logistics_assembler.view_provider is not self.provider
                or self.logistics_worker.client_version != self.client_version
                or self.logistics_worker.model_version != self.model_version):
            raise TaskConflict('Logistics requires configured original same-store A08 components and validators')
        return self.logistics_assembler, self.logistics_worker

    def prepare_logistics(self, context, **logistics_refs):
        """Assemble explicitly selected transport sources under the original host guard."""
        assembler, _ = self._require_logistics()
        with self.read_guard():
            return assembler.build(context, **logistics_refs)

    def execute_logistics(self, prepared, *, request_id, purpose='action'):
        """Persist one original A08 request/query; formal dispatch remains a host operation."""
        _, worker = self._require_logistics()
        if not isinstance(prepared, PreparedSupplierLogistics) or prepared.context.contract_ref.id != 'SUPPLIER-A08':
            raise TaskConflict('Logistics execution requires its original prepared A08 invocation')
        with self.read_guard():
            identity = worker.register(prepared, request_id=request_id, purpose=purpose)
            outcome = worker.execute(identity, prepared)
            return {**outcome, 'identity': identity}

    def prepare_logistics_from_quality(self, context, *, quality_identity,
            quality_execution_versions, basis_ref, **logistics_refs):
        """Use selected saved A07 evidence and independently confirmed current release."""
        assembler, _ = self._require_logistics()
        _, quality_worker = self._require_quality()
        with self.read_guard():
            return assembler.build_from_quality(context, quality_worker=quality_worker,
                quality_identity=quality_identity, quality_execution_versions=quality_execution_versions,
                basis_ref=basis_ref, validate_history=self.logistics_validators.quality_history,
                validate_current=self.logistics_validators.release_source, **logistics_refs)

    def _require_receiving(self):
        if (not isinstance(self.receiving_validators, SupplierReceivingValidators)
                or not isinstance(self.receiving_assembler, SupplierReceivingActionAssembler)
                or not isinstance(self.receiving_worker, SupplierReceivingResultWorker)
                or self.receiving_worker.store is not self.store or self.receiving_worker.snapshots is not self.snapshots
                or self.receiving_worker.registry is not self.registry
                or self.receiving_assembler.registry is not self.registry
                or self.receiving_assembler.organizations is not self.organizations
                or self.receiving_assembler.view_provider is not self.provider
                or self.receiving_worker.client_version != self.client_version
                or self.receiving_worker.model_version != self.model_version):
            raise TaskConflict('Receiving requires configured original same-store A09 components and validators')
        return self.receiving_assembler, self.receiving_worker

    def prepare_receiving(self, context, **receiving_refs):
        """Assemble explicitly selected shipment and receiving evidence under the host guard."""
        assembler, _ = self._require_receiving()
        with self.read_guard():
            return assembler.build(context, **receiving_refs)

    def execute_receiving(self, prepared, *, request_id, purpose='action'):
        """Save one original Supplier response with independent receiver rights preserved."""
        _, worker = self._require_receiving()
        if not isinstance(prepared, PreparedSupplierReceiving) or prepared.context.contract_ref.id != 'SUPPLIER-A09':
            raise TaskConflict('Receiving execution requires its original prepared A09 invocation')
        with self.read_guard():
            identity = worker.register(prepared, request_id=request_id, purpose=purpose)
            outcome = worker.execute(identity, prepared)
            return {**outcome, 'identity': identity}

    def prepare_receiving_from_logistics(self, context, *, logistics_identity,
            logistics_execution_versions, basis_ref, **receiving_refs):
        """Bind saved A08 evidence to actual current Shipment and independent receiving sources."""
        assembler, _ = self._require_receiving()
        _, logistics_worker = self._require_logistics()
        with self.read_guard():
            return assembler.build_from_logistics(context, logistics_worker=logistics_worker,
                logistics_identity=logistics_identity, logistics_execution_versions=logistics_execution_versions,
                basis_ref=basis_ref, validate_history=self.receiving_validators.logistics_history,
                validate_current=self.receiving_validators.shipment_source, **receiving_refs)

    def _require_payment(self):
        if (not isinstance(self.payment_validators, SupplierPaymentValidators)
                or not isinstance(self.payment_assembler, SupplierPaymentActionAssembler)
                or not isinstance(self.payment_worker, SupplierPaymentResultWorker)
                or self.payment_worker.store is not self.store or self.payment_worker.snapshots is not self.snapshots
                or self.payment_worker.registry is not self.registry
                or self.payment_assembler.registry is not self.registry
                or self.payment_assembler.organizations is not self.organizations
                or self.payment_assembler.view_provider is not self.provider
                or self.payment_worker.client_version != self.client_version
                or self.payment_worker.model_version != self.model_version):
            raise TaskConflict('Payment requires configured original same-store A10 components and validators')
        return self.payment_assembler, self.payment_worker

    def prepare_payment(self, context, **payment_refs):
        """Assemble explicit contract rights, delivery facts and cash sources under the host guard."""
        assembler, _ = self._require_payment()
        with self.read_guard():
            return assembler.build(context, **payment_refs)

    def execute_payment(self, prepared, *, request_id, purpose='action'):
        """Save the original A10 decision with actual claim recognition and cash effects left to the host."""
        _, worker = self._require_payment()
        if not isinstance(prepared, PreparedSupplierPayment) or prepared.context.contract_ref.id != 'SUPPLIER-A10':
            raise TaskConflict('Payment execution requires its original prepared A10 invocation')
        with self.read_guard():
            identity = worker.register(prepared, request_id=request_id, purpose=purpose)
            outcome = worker.execute(identity, prepared)
            return {**outcome, 'identity': identity}

    def prepare_payment_from_receiving(self, context, *, receiving_identity,
            receiving_execution_versions, basis_ref, handoff_delivery_refs, **payment_refs):
        """Verify an explicit actual delivery subset against saved A09 and current contract nodes."""
        assembler, _ = self._require_payment()
        _, receiving_worker = self._require_receiving()
        with self.read_guard():
            return assembler.build_from_receiving(context, receiving_worker=receiving_worker,
                receiving_identity=receiving_identity, receiving_execution_versions=receiving_execution_versions,
                basis_ref=basis_ref, handoff_delivery_refs=handoff_delivery_refs,
                validate_history=self.payment_validators.receiving_history,
                validate_current=self.payment_validators.delivery_source, **payment_refs)

    def _require_remedy(self):
        if (not isinstance(self.remedy_validators, SupplierRemedyValidators)
                or not isinstance(self.remedy_assembler, SupplierRemedyActionAssembler)
                or not isinstance(self.remedy_worker, SupplierRemedyResultWorker)
                or self.remedy_worker.store is not self.store or self.remedy_worker.snapshots is not self.snapshots
                or self.remedy_worker.registry is not self.registry
                or self.remedy_assembler.registry is not self.registry
                or self.remedy_assembler.organizations is not self.organizations
                or self.remedy_assembler.view_provider is not self.provider
                or self.remedy_worker.client_version != self.client_version
                or self.remedy_worker.model_version != self.model_version):
            raise TaskConflict('Remedy requires configured original same-store A11 components and validators')
        return self.remedy_assembler, self.remedy_worker

    def prepare_remedy(self, context, **remedy_refs):
        """Assemble selected contract, defect and disposition sources under the host guard."""
        assembler, _ = self._require_remedy()
        with self.read_guard():
            return assembler.build(context, **remedy_refs)

    def execute_remedy(self, prepared, *, request_id, purpose='action'):
        """Save the original remedy proposal with independent liability and formal effects preserved."""
        _, worker = self._require_remedy()
        if not isinstance(prepared, PreparedSupplierRemedy) or prepared.context.contract_ref.id != 'SUPPLIER-A11':
            raise TaskConflict('Remedy execution requires its original prepared A11 invocation')
        with self.read_guard():
            identity = worker.register(prepared, request_id=request_id, purpose=purpose)
            outcome = worker.execute(identity, prepared)
            return {**outcome, 'identity': identity}

    def _require_advice(self):
        if (not isinstance(self.advice_validators, SupplierAdviceValidators)
                or not isinstance(self.advice_assembler, SupplierAdviceActionAssembler)
                or not isinstance(self.advice_worker, SupplierAdviceResultWorker)
                or self.advice_worker.store is not self.store or self.advice_worker.snapshots is not self.snapshots
                or self.advice_worker.registry is not self.registry
                or self.advice_assembler.registry is not self.registry
                or self.advice_assembler.organizations is not self.organizations
                or self.advice_assembler.view_provider is not self.provider
                or self.advice_worker.client_version != self.client_version
                or self.advice_worker.model_version != self.model_version):
            raise TaskConflict('Advice requires configured original same-store A13 components and validators')
        return self.advice_assembler, self.advice_worker

    def prepare_advice(self, context, **advice_refs):
        """Assemble explicit advisory sources and disclosure policy under the host guard."""
        assembler, _ = self._require_advice()
        with self.read_guard():
            return assembler.build(context, **advice_refs)

    def execute_advice(self, prepared, *, request_id, purpose='action'):
        """Save original consultation evidence with the private source cache kept separate."""
        _, worker = self._require_advice()
        if not isinstance(prepared, PreparedSupplierAdvice) or prepared.context.contract_ref.id != 'SUPPLIER-A13':
            raise TaskConflict('Advice execution requires its original prepared A13 invocation')
        with self.read_guard():
            identity = worker.register(prepared, request_id=request_id, purpose=purpose)
            outcome = worker.execute(identity, prepared)
            return {**outcome, 'identity': identity}

    def _require_screening(self):
        if (not isinstance(self.screening_validators, SupplierScreeningValidators)
                or not isinstance(self.screening_assembler, SupplierScreeningActionAssembler)
                or not isinstance(self.screening_worker, SupplierScreeningResultWorker)
                or self.screening_worker.store is not self.store or self.screening_worker.snapshots is not self.snapshots
                or self.screening_worker.registry is not self.registry
                or self.screening_assembler.registry is not self.registry
                or self.screening_assembler.organizations is not self.organizations
                or self.screening_assembler.view_provider is not self.provider
                or self.screening_worker.client_version != self.client_version
                or self.screening_worker.model_version != self.model_version):
            raise TaskConflict('Screening requires configured original same-store A01 components and validators')
        return self.screening_assembler, self.screening_worker

    def prepare_screening(self, context, **screening_refs):
        """Assemble selected inquiries and own capability/capacity under the host guard."""
        assembler, _ = self._require_screening()
        with self.read_guard():
            return assembler.build(context, **screening_refs)

    def execute_screening(self, prepared, *, request_id, purpose='action'):
        """Save the original screening result with formal intentions and commitments separate."""
        _, worker = self._require_screening()
        if not isinstance(prepared, PreparedSupplierScreening) or prepared.context.contract_ref.id != 'SUPPLIER-A01':
            raise TaskConflict('Screening execution requires its original prepared A01 invocation')
        with self.read_guard():
            identity = worker.register(prepared, request_id=request_id, purpose=purpose)
            outcome = worker.execute(identity, prepared)
            return {**outcome, 'identity': identity}

    def _require_commercial(self):
        if (not isinstance(self.commercial_validators, SupplierCommercialValidators)
                or not isinstance(self.commercial_journal, ContinuationJournal)
                or self.commercial_journal.store is not self.store
                or not isinstance(self.commercial_assembler, CommercialActionAssembler)
                or not isinstance(self.commercial_worker, CommercialTaskWorker)
                or self.commercial_worker.assembler is not self.commercial_assembler
                or self.commercial_worker.store is not self.store or self.commercial_worker.snapshots is not self.snapshots
                or self.commercial_worker.journal is not self.commercial_journal
                or self.commercial_assembler.registry is not self.registry
                or self.commercial_assembler.organizations is not self.organizations
                or self.commercial_assembler.source_mode != self.source_mode
                or self.commercial_worker.client_version != self.client_version
                or self.commercial_worker.model_version != self.model_version):
            raise TaskConflict('Commercial operation requires original same-store Supplier A12 components and journal')
        views = self.commercial_assembler._views.get('SUPPLIER-A12')
        if views is None or views.provider is not self.provider or views.macro_version != self.macro_version:
            raise TaskConflict('Commercial operation changes the original Supplier source provider or macro version')
        return self.commercial_assembler, self.commercial_worker

    def prepare_commercial(self, context, *, profile_ref):
        """Assemble the explicitly selected original Supplier continuation profile."""
        context = ActionContext.model_validate(context).model_copy(deep=True)
        if context.contract_ref.kind != 'ActionContract' or context.contract_ref.id != 'SUPPLIER-A12':
            raise TaskConflict('Supplier commercial entry requires its original A12 context')
        assembler, _ = self._require_commercial()
        with self.read_guard():
            return assembler.build(context, profile_ref=profile_ref)

    def execute_commercial(self, prepared, *, request_id, purpose='action'):
        """Save and run one explicit A12 root with the original result/recovery rules."""
        _, worker = self._require_commercial()
        if (not isinstance(prepared, PreparedCommercialAction) or prepared.context.contract_ref.id != 'SUPPLIER-A12'
                or prepared.context.contract_ref.kind != 'ActionContract' or prepared.runner.registry is not self.registry):
            raise TaskConflict('Supplier commercial execution requires its original prepared A12 invocation')
        with self.read_guard():
            identity = worker.register(prepared, request_id=request_id, purpose=purpose)
            outcome = worker.run(identity)
            return {**outcome, 'identity': identity}

    def run_commercial(self, identity):
        """Run one selected original Supplier root/successor; never automatically replay it."""
        _, worker = self._require_commercial()
        if identity.action_id != 'SUPPLIER-A12' or identity.role != 'Supplier' or identity.run_id != self.store.run_id:
            raise TaskConflict('Supplier commercial consumption requires its original A12 identity')
        with self.read_guard():
            return worker.run(identity)

    def dispatch_commercial_feedback(self, *, organization_id):
        """Create validated Supplier A12 successors from persisted recipient feedback without executing them."""
        self._require_commercial()
        dispatcher, config = self.commercial_dispatcher, self.commercial_feedback
        if (not isinstance(config, SupplierCommercialFeedback)
                or not isinstance(dispatcher, ObservationContinuationDispatcher)
                or dispatcher.journal is not self.commercial_journal or dispatcher.inbox is not config.inbox
                or dispatcher.action_ids != frozenset({'SUPPLIER-A12'})
                or config.inbox.run_id != self.store.run_id or config.inbox.organization_ids != self.store.organization_ids
                or organization_id not in self.store.organization_ids):
            raise TaskConflict('Supplier feedback requires original configured inbox, journal, recipient and A12 action boundary')
        with self.read_guard():
            return dispatcher(run_id=self.store.run_id, organization_id=organization_id)
