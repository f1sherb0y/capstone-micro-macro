"""Configured formal QS application assembly over original actual dependencies."""
from copy import deepcopy
from dataclasses import dataclass, field
import importlib
import json
from pathlib import Path
from typing import Callable

from pydantic import model_validator

from integration.module_host import module_factory_descriptor
from integration.observations import ObservationInbox
from integration.qs_bid_actions import QSBidActionAssembler
from integration.qs_intake_actions import QSIntakeActionAssembler
from integration.qs_intake_recovery_reader import (
    QSIntakeRecoveryReader, QSIntakeRecoverySettings, QSIntakeRecoveryBindings, build_assembled_qs_intake_dispatcher,
)
from integration.qs_bid_reader import QSBidReader, QSBidRecoverySettings, QSBidRecoveryBindings, build_assembled_qs_bid_dispatcher
from integration.qs_bid_calculation_publication import QSBidNormalizationPublicationStore, QSBidNormalizationPublishedViewProvider
from integration.qs_bid_calculation_validation import QSBidNormalizationSourceValidator
from integration.qs_bid_ranking_publication import QSBidRankingPublicationStore, QSBidRankingPublishedViewProvider
from integration.qs_bid_ranking_validation import QSBidRankingSourceValidator
from integration.qs_billing_actions import QSBillingActionAssembler
from integration.qs_billing_recovery_reader import (
    QSBillingRecoverySettings, QSBillingRecoveryBindings, QSBillingRecoveryReader,
    build_assembled_qs_billing_dispatcher,
)
from integration.qs_billing_calculation_publication import QSBillingCalculationPublicationStore, QSBillingCalculationPublishedViewProvider
from integration.qs_billing_calculation_validation import QSBillingCalculationSourceValidator
from integration.qs_change_actions import QSChangeActionAssembler
from integration.qs_change_reader import QSChangeReader, QSChangeRecoverySettings, QSChangeRecoveryBindings, build_assembled_qs_change_dispatcher
from integration.qs_change_calculation_publication import QSChangeCalculationPublicationStore, QSChangeCalculationPublishedViewProvider
from integration.qs_change_calculation_validation import QSChangeCalculationSourceValidator
from integration.qs_cost_actions import QSCostActionAssembler
from integration.qs_appointment_actions import QSAppointmentActionAssembler
from integration.qs_appointment_reader import (
    QSAppointmentReader, QSAppointmentRecoverySettings, QSAppointmentRecoveryBindings,
    build_assembled_qs_appointment_dispatcher,
)
from integration.qs_cost_reader import QSCostReader, QSCostRecoverySettings, QSCostRecoveryBindings, build_assembled_qs_cost_dispatcher
from integration.qs_cost_calculation_publication import QSCostCalculationPublicationStore, QSCostCalculationPublishedViewProvider
from integration.qs_cost_calculation_validation import QSCostCalculationSourceValidator
from integration.qs_final_account_actions import QSFinalAccountActionAssembler
from integration.qs_final_account_reader import (
    QSFinalAccountReader, QSFinalAccountRecoverySettings, QSFinalAccountRecoveryBindings,
    build_assembled_qs_final_account_dispatcher,
)
from integration.qs_final_account_calculation_publication import QSFinalAccountCalculationPublicationStore, QSFinalAccountCalculationPublishedViewProvider
from integration.qs_final_account_calculation_validation import QSFinalAccountCalculationSourceValidator
from integration.qs_learning_actions import QSLearningActionAssembler
from integration.qs_transition_actions import QSTransitionActionAssembler
from integration.qs_transition_reader import (
    QSTransitionReader, QSTransitionRecoverySettings, QSTransitionRecoveryBindings,
    build_assembled_qs_transition_dispatcher,
)
from integration.qs_learning_reader import (
    QSLearningReader, QSLearningRecoverySettings, QSLearningRecoveryBindings,
    build_assembled_qs_learning_dispatcher,
)
from integration.qs_learning_assessment_publication import QSLearningAssessmentPublicationStore, QSLearningAssessmentPublishedViewProvider
from integration.qs_learning_assessment_validation import QSLearningAssessmentSourceValidator
from integration.qs_learning_calculation_publication import QSLearningComparabilityPublicationStore, QSLearningComparabilityPublishedViewProvider
from integration.qs_learning_calculation_validation import QSLearningComparabilitySourceValidator
from integration.qs_learning_error_publication import QSLearningErrorPublicationStore, QSLearningErrorPublishedViewProvider
from integration.qs_learning_error_validation import QSLearningErrorSourceValidator
from integration.qs_training_estimate_publication import QSTrainingEstimatePublicationStore, QSTrainingEstimatePublishedViewProvider
from integration.qs_training_estimate_validation import QSTrainingEstimateSourceValidator
from integration.qs_research_actions import QSResearchActionAssembler
from integration.qs_research_recovery_reader import (
    QSResearchRecoveryReader, QSResearchRecoverySettings, QSResearchRecoveryBindings,
    build_assembled_qs_research_dispatcher,
)
from integration.qs_research_normalization_calculations import (
    prepare_qs_research_normalization_calculation, _prepare_qs_research_comparison_calculation,
)
from integration.qs_research_normalization_publication import (
    QSResearchNormalizationPublicationStore, QSResearchNormalizationPublishedViewProvider,
)
from integration.qs_research_normalization_validation import QSResearchNormalizationSourceValidator
from integration.qs_research_ranking_calculations import prepare_qs_research_ranking_calculation
from integration.qs_research_ranking_publication import QSResearchRankingPublicationStore, QSResearchRankingPublishedViewProvider
from integration.qs_research_ranking_validation import QSResearchRankingSourceValidator
from integration.qs_payment_actions import QSPaymentActionAssembler
from integration.qs_payment_reader import QSPaymentReader, QSPaymentRecoverySettings, QSPaymentRecoveryBindings, build_assembled_qs_payment_dispatcher
from integration.qs_payment_calculation_publication import QSPaymentCalculationPublicationStore, QSPaymentCalculationPublishedViewProvider
from integration.qs_payment_calculation_validation import QSPaymentCalculationSourceValidator
from integration.qs_procurement_actions import QSProcurementActionAssembler
from integration.qs_procurement_reader import QSProcurementReader, QSProcurementRecoverySettings, QSProcurementRecoveryBindings, build_assembled_qs_procurement_dispatcher
from integration.qs_procurement_document_publication import QSProcurementDocumentPublicationStore, QSProcurementDocumentPublishedViewProvider
from integration.qs_procurement_document_validation import QSProcurementDocumentSourceValidator
from integration.qs_procurement_results import QSProcurementResultWorker
from integration.qs_role_contract_host import QSRoleContractSources, _ACTIONS, _descriptors, _load_factory
from integration.qs_submission import QSSubmissionCallbacks
from integration.qs_submission_feedback import QSSubmissionFeedback
from integration.qs_submission_host import QSSubmissionHost, QSSubmissionHostConfiguration
from integration.role_contract_host import RoleContractInvocation
from src.actions.contracts.common import ActionContext, StrictRecord, TextId
from src.coordination.invocations import InvocationSnapshotStore
from src.coordination.tasks import TaskConflict, TaskIdentity, canonical, task_digest
from src.methods.registry import MethodRegistry
from src.actions.roles.qs_research import prepare_qs_research_normalization_input, prepare_qs_research_ranking_input
from src.methods.qs_research import (
    RESEARCH_NORMALIZE_METHOD, RESEARCH_RANK_METHOD, ResearchNormalizationInput, ResearchRankInput,
    normalize_plans, rank_plans,
)


class QSFormalFeedbackSettings(StrictRecord):
    version: TextId
    inbox_path: TextId
    input_enabled: bool = False


class QSFormalCostCalculationSettings(StrictRecord):
    version: TextId
    macro_version: TextId
    policy_version: TextId


class QSFormalChangeCalculationSettings(StrictRecord):
    version: TextId
    macro_version: TextId
    policy_version: TextId


class QSFormalPaymentCalculationSettings(StrictRecord):
    version: TextId
    macro_version: TextId
    policy_version: TextId


class QSFormalFinalAccountCalculationSettings(StrictRecord):
    version: TextId
    macro_version: TextId
    policy_version: TextId


class QSFormalProcurementDocumentSettings(StrictRecord):
    version: TextId
    macro_version: TextId


class QSFormalBidNormalizationSettings(StrictRecord):
    version: TextId
    macro_version: TextId
    policy_version: TextId


class QSFormalBidRankingSettings(StrictRecord):
    version: TextId
    macro_version: TextId
    policy_version: TextId


class QSFormalBillingCalculationSettings(StrictRecord):
    version: TextId
    macro_version: TextId
    policy_version: TextId


class QSFormalLearningComparabilitySettings(StrictRecord):
    version: TextId
    macro_version: TextId
    policy_version: TextId


class QSFormalLearningErrorSettings(StrictRecord):
    version: TextId
    macro_version: TextId
    policy_version: TextId


class QSFormalLearningAssessmentSettings(StrictRecord):
    version: TextId
    macro_version: TextId
    policy_version: TextId


class QSFormalTrainingEstimateSettings(StrictRecord):
    version: TextId
    macro_version: TextId
    policy_version: TextId


class QSFormalResearchNormalizationSettings(StrictRecord):
    version: TextId
    macro_version: TextId
    policy_version: TextId


class QSFormalResearchRankingSettings(StrictRecord):
    version: TextId
    macro_version: TextId
    policy_version: TextId


class QSFormalApplicationSettings(StrictRecord):
    action_id: TextId
    dependency_factory: TextId
    dependency_version: TextId
    dependency_settings: dict
    client_version: TextId
    model_version: TextId
    submission: QSSubmissionHostConfiguration | None = None
    feedback: QSFormalFeedbackSettings | None = None
    cost_calculations: QSFormalCostCalculationSettings | None = None
    change_calculations: QSFormalChangeCalculationSettings | None = None
    payment_calculations: QSFormalPaymentCalculationSettings | None = None
    final_account_calculations: QSFormalFinalAccountCalculationSettings | None = None
    procurement_documents: QSFormalProcurementDocumentSettings | None = None
    bid_normalization: QSFormalBidNormalizationSettings | None = None
    bid_ranking: QSFormalBidRankingSettings | None = None
    billing_calculations: QSFormalBillingCalculationSettings | None = None
    learning_comparability: QSFormalLearningComparabilitySettings | None = None
    learning_error: QSFormalLearningErrorSettings | None = None
    learning_assessment: QSFormalLearningAssessmentSettings | None = None
    training_estimates: QSFormalTrainingEstimateSettings | None = None
    research_normalizations: QSFormalResearchNormalizationSettings | None = None
    research_rankings: QSFormalResearchRankingSettings | None = None
    execution_recovery: QSTransitionRecoverySettings | QSPaymentRecoverySettings | QSChangeRecoverySettings | QSCostRecoverySettings | QSBidRecoverySettings | QSProcurementRecoverySettings | QSResearchRecoverySettings | QSIntakeRecoverySettings | QSAppointmentRecoverySettings | QSFinalAccountRecoverySettings | QSLearningRecoverySettings | QSBillingRecoverySettings | None = None

    @model_validator(mode='before')
    @classmethod
    def original_execution_recovery(cls, value):
        if not isinstance(value, dict) or value.get('execution_recovery') is None:
            return value
        types = {'QS-A02': QSIntakeRecoverySettings, 'QS-A10': QSBillingRecoverySettings,
            'QS-A04': QSCostRecoverySettings, 'QS-A05': QSProcurementRecoverySettings, 'QS-A06': QSBidRecoverySettings,
            'QS-A07': QSChangeRecoverySettings, 'QS-A08': QSPaymentRecoverySettings,
            'QS-A13': QSResearchRecoverySettings, 'QS-A03': QSAppointmentRecoverySettings,
            'QS-A09': QSFinalAccountRecoverySettings, 'QS-A12': QSLearningRecoverySettings,
            'QS-A11': QSTransitionRecoverySettings}
        action_id, recovery = value.get('action_id'), value['execution_recovery']
        if action_id not in types:
            raise ValueError('QS recovery requires original QS-A02/A03/A04/A05/A06/A07/A08/A09/A10/A11/A12/A13')
        settings_type = types[action_id]
        if isinstance(recovery, tuple(types.values())) and type(recovery) is not settings_type:
            raise ValueError('QS recovery configuration changes its original action type')
        return {**value, 'execution_recovery': settings_type.model_validate(recovery)}


@dataclass(frozen=True)
class QSFormalApplicationDependencies:
    """Actual application supplies original sources and an existing model host.

    The factory owns partial resources until returning this bundle. Original
    invocation/wait/recovery validators apply to all submission workers; actual
    action-specific transport and business validation are explicitly supplied.
    """
    version: str
    sources: QSRoleContractSources
    submission_callbacks: dict[str, QSSubmissionCallbacks] = field(default_factory=dict)
    submission_read_guard: Callable | None = None
    validate_feedback_relation: Callable | None = None
    validate_feedback_read: Callable | None = None
    validate_feedback_input: Callable | None = None
    validate_research_normalization_basis: Callable | None = None
    validate_research_ranking_basis: Callable | None = None
    execution_recovery: QSTransitionRecoveryBindings | QSPaymentRecoveryBindings | QSChangeRecoveryBindings | QSCostRecoveryBindings | QSBidRecoveryBindings | QSProcurementRecoveryBindings | QSResearchRecoveryBindings | QSAppointmentRecoveryBindings | QSFinalAccountRecoveryBindings | QSLearningRecoveryBindings | QSIntakeRecoveryBindings | QSBillingRecoveryBindings | None = None

    def __post_init__(self):
        if (not isinstance(self.version, str) or not self.version.strip()
                or not isinstance(self.sources, QSRoleContractSources)
                or self.execution_recovery is not None and type(self.execution_recovery) not in {
                    QSPaymentRecoveryBindings, QSChangeRecoveryBindings, QSCostRecoveryBindings, QSBidRecoveryBindings,
                    QSProcurementRecoveryBindings, QSResearchRecoveryBindings, QSAppointmentRecoveryBindings,
                    QSFinalAccountRecoveryBindings, QSLearningRecoveryBindings, QSTransitionRecoveryBindings, QSIntakeRecoveryBindings,
                    QSBillingRecoveryBindings}
                or self.sources.feedback is not None or self.sources.validate_feedback_input is not None
                or self.sources.publish_cost_calculation is not None or self.sources.publish_saved_cost_calculation is not None
                or self.sources.publish_change_calculation is not None or self.sources.publish_saved_change_calculation is not None
                or self.sources.publish_payment_calculations is not None or self.sources.publish_saved_payment_calculations is not None
                or self.sources.publish_final_account_reconciliation is not None
                or self.sources.publish_saved_final_account_reconciliation is not None
                or self.sources.save_procurement_document is not None
                or self.sources.publish_saved_procurement_document is not None
                or self.sources.save_bid_normalization is not None
                or self.sources.publish_saved_bid_normalization is not None
                or self.sources.save_bid_ranking is not None
                or self.sources.publish_saved_bid_ranking is not None
                or self.sources.save_billing_calculation is not None
                or self.sources.publish_saved_billing_calculation is not None
                or self.sources.save_learning_comparability is not None
                or self.sources.publish_saved_learning_comparability is not None
                or self.sources.save_learning_error is not None
                or self.sources.publish_saved_learning_error is not None
                or self.sources.save_learning_assessment is not None
                or self.sources.publish_saved_learning_assessment is not None
                or self.sources.save_training_estimate is not None
                or self.sources.publish_saved_training_estimate is not None
                or self.sources.save_research_normalization_calculation is not None
                or self.sources.publish_saved_research_normalization_calculation is not None
                or self.sources.save_research_ranking_calculation is not None
                or self.sources.publish_saved_research_ranking_calculation is not None
                or not isinstance(self.submission_callbacks, dict)
                or any(not isinstance(value, QSSubmissionCallbacks) for value in self.submission_callbacks.values())
                or any(callback is not None and not callable(callback) for callback in
                    (self.submission_read_guard, self.validate_feedback_relation,
                        self.validate_feedback_read, self.validate_feedback_input,
                        self.validate_research_normalization_basis, self.validate_research_ranking_basis))):
            raise ValueError('Formal QS dependencies require original sources and actual callback bindings')


class QSFormalApplication:
    """Assemble original workers and configured routes; business calls stay explicit.

    Source health and native endpoint effects require observed application
    evidence. Construction is configured_unverified and never runs an action,
    sends a submission, constructs a model client or invents a native source.
    Cost, procurement, valuation, certification, billing, learning and transition routes require actual
    application transport. Configuration and receipts do not prove quantities,
    publication, tender award, certification, settlement, applied learning, fees, cash or cleared obligations.
    """
    VERSION = 'qs-formal-application.v1'

    def __init__(self, *, request, settings, dependencies, factory_descriptor):
        self.settings = QSFormalApplicationSettings.model_validate(settings).model_copy(deep=True)
        request = RoleContractInvocation.model_validate(request).model_copy(deep=True)
        if not isinstance(dependencies, QSFormalApplicationDependencies):
            raise ValueError('Formal QS factory must return QSFormalApplicationDependencies')
        base = dependencies.sources
        config = self.settings
        model = base.model_host
        if ((config.research_rankings is not None) != (dependencies.validate_research_ranking_basis is not None)
                or config.research_rankings is not None and not callable(dependencies.validate_research_ranking_basis)):
            raise ValueError('QS research ranking configuration requires its explicit actual criteria/risk basis verifier')
        if config.research_rankings is not None and (config.research_normalizations is None
                or config.research_rankings.macro_version != config.research_normalizations.macro_version):
            raise ValueError('QS research ranking requires original configured normalization at the same macro version')
        if ((config.research_normalizations is not None) != (dependencies.validate_research_normalization_basis is not None)
                or config.research_normalizations is not None and not callable(dependencies.validate_research_normalization_basis)):
            raise ValueError('QS research normalization configuration requires its explicit actual adjustment basis verifier')
        if (config.action_id not in _ACTIONS or request.context.contract_ref.id != config.action_id
                or request.context.execution_mode != 'llm' or request.context.run_id != base.store.run_id
                or base.organizations.run_id != base.store.run_id or dependencies.version != config.dependency_version
                or model is None or model.store is not base.store or model.registry is not base.registry
                or model.model_version != config.model_version):
            raise ValueError('Formal QS assembly requires original same-run sources and configured model host')
        registration = base.registry.get(config.action_id)
        if (registration.role != 'QS' or not registration.implemented or registration.skill is None
                or request.execution_path not in {None, registration.strategy}
                or not any(config.action_id in binding.action_ids and binding.strategy == registration.strategy
                    for binding in model.bindings)):
            raise ValueError('Formal QS application requires its original implemented action and bound strategy')
        actions = {route.action_id for route in config.submission.routes} if config.submission is not None else set()
        if (not actions <= set(_ACTIONS) or set(dependencies.submission_callbacks) != actions
                or config.submission is not None and not callable(dependencies.submission_read_guard)
                or config.submission is None and dependencies.submission_read_guard is not None):
            raise ValueError('Configured QS submission must match its explicit callbacks and current read guard')
        if config.feedback is not None:
            if (config.submission is None or not actions
                    or not callable(dependencies.validate_feedback_relation)
                    or not callable(dependencies.validate_feedback_read)):
                raise ValueError('QS feedback requires configured submission routes and actual relation/read validators')
        elif dependencies.validate_feedback_relation is not None or dependencies.validate_feedback_read is not None:
            raise ValueError('QS feedback validators require an explicit feedback configuration')
        input_enabled = config.feedback is not None and config.feedback.input_enabled
        if (input_enabled and not callable(dependencies.validate_feedback_input)
                or not input_enabled and dependencies.validate_feedback_input is not None):
            raise ValueError('QS feedback input validation must match the explicit input-enabled configuration')
        recovery = dependencies.execution_recovery
        if (config.execution_recovery is None) != (recovery is None):
            raise ValueError('QS execution recovery must match its explicit configuration')
        if recovery is not None:
            binding_type = {'QS-A02': QSIntakeRecoveryBindings, 'QS-A10': QSBillingRecoveryBindings,
                'QS-A04': QSCostRecoveryBindings, 'QS-A05': QSProcurementRecoveryBindings,
                'QS-A06': QSBidRecoveryBindings, 'QS-A07': QSChangeRecoveryBindings,
                'QS-A08': QSPaymentRecoveryBindings, 'QS-A13': QSResearchRecoveryBindings,
                'QS-A03': QSAppointmentRecoveryBindings, 'QS-A09': QSFinalAccountRecoveryBindings,
                'QS-A12': QSLearningRecoveryBindings, 'QS-A11': QSTransitionRecoveryBindings}.get(config.action_id)
            if (binding_type is None or type(recovery) is not binding_type
                    or config.action_id not in actions or config.feedback is None):
                raise ValueError('QS recovery requires matching original action callbacks, submission and persisted feedback routes')
            publications = {'QS-A04': (config.cost_calculations,),
                'QS-A05': (config.procurement_documents,),
                'QS-A06': (config.bid_normalization, config.bid_ranking),
                'QS-A07': (config.change_calculations,), 'QS-A08': (config.payment_calculations,),
                'QS-A13': (config.research_normalizations, config.research_rankings),
                'QS-A02': (), 'QS-A03': (), 'QS-A11': (), 'QS-A09': (config.final_account_calculations,),
                'QS-A10': (config.billing_calculations,),
                'QS-A12': (config.learning_comparability, config.learning_error,
                    config.learning_assessment, config.training_estimates)}[config.action_id]
            if any(publication is not None and publication.macro_version != config.execution_recovery.macro_version
                    for publication in publications):
                raise ValueError('QS recovery must use its original action publication macro version')
        self.dependencies, self.base = dependencies, base
        self.factory_descriptor = deepcopy(factory_descriptor)
        self._components = (base, base.store, base.registry, base.organizations, base.provider, model)
        self._closed = False
        self.submissions = self.feedback = None
        # Keep the existing recovery slot names for A08 callers; their actual
        # assembler/reader types are selected from the configured action.
        self.payment_recovery_assembler = self.payment_reader = self.execution_dispatcher = None
        self._payment_recovery_components = None
        self.cost_validator = self.cost_publications = self.cost_assembler = None
        self.change_validator = self.change_publications = self.change_assembler = None
        self.payment_validator = self.payment_publications = self.payment_assembler = None
        self.final_account_validator = self.final_account_publications = self.final_account_assembler = None
        self.procurement_worker = self.procurement_validator = self.procurement_publications = None
        self.bid_validator = self.bid_publications = self.bid_assembler = None
        self.ranking_validator = self.ranking_publications = self.ranking_assembler = None
        self.billing_validator = self.billing_publications = self.billing_assembler = None
        self.comparability_validator = self.comparability_publications = self.comparability_assembler = None
        self.error_validator = self.error_publications = self.error_assembler = None
        self.assessment_validator = self.assessment_publications = self.assessment_assembler = None
        self.training_validator = self.training_publications = self.training_assembler = None
        self.research_normalization_validator = self.research_normalization_publications = self.research_normalization_assembler = None
        self.research_ranking_validator = self.research_ranking_publications = self.research_ranking_assembler = None
        self.provider = base.provider
        if config.cost_calculations is not None:
            if not isinstance(base.methods, MethodRegistry):
                raise ValueError('QS cost publication requires an explicit original bound method registry')
            cost = config.cost_calculations
            self.cost_validator = QSCostCalculationSourceValidator(registry=base.registry,
                organizations=base.organizations, provider=base.provider,
                macro_version=cost.macro_version, source_mode='formal')
            self.cost_publications = QSCostCalculationPublicationStore(store=base.store,
                registry=base.registry, methods=base.methods, organizations=base.organizations,
                validate_source=self.cost_validator.validate_source)
            self.cost_assembler = QSCostActionAssembler(registry=base.registry, organizations=base.organizations,
                provider=base.provider, macro_version=cost.macro_version, source_mode='formal', methods=base.methods,
                policy_version=cost.policy_version, model_version=config.model_version, model_host=model)
            self.provider = QSCostCalculationPublishedViewProvider(provider=base.provider, publications=self.cost_publications)
        self.cost_provider = self.provider
        if config.change_calculations is not None:
            if not isinstance(base.methods, MethodRegistry):
                raise ValueError('QS change publication requires an explicit original bound method registry')
            change = config.change_calculations
            self.change_validator = QSChangeCalculationSourceValidator(registry=base.registry,
                organizations=base.organizations, provider=base.provider,
                macro_version=change.macro_version, source_mode='formal')
            self.change_publications = QSChangeCalculationPublicationStore(store=base.store,
                registry=base.registry, methods=base.methods, organizations=base.organizations,
                validate_source=self.change_validator.validate_source)
            self.change_assembler = QSChangeActionAssembler(registry=base.registry, organizations=base.organizations,
                provider=base.provider, macro_version=change.macro_version, source_mode='formal', methods=base.methods,
                policy_version=change.policy_version, model_version=config.model_version, model_host=model)
            self.provider = QSChangeCalculationPublishedViewProvider(provider=self.cost_provider, publications=self.change_publications)
        self.change_provider = self.provider
        if config.payment_calculations is not None:
            if not isinstance(base.methods, MethodRegistry):
                raise ValueError('QS payment publication requires an explicit original bound method registry')
            payment = config.payment_calculations
            self.payment_validator = QSPaymentCalculationSourceValidator(registry=base.registry,
                organizations=base.organizations, provider=base.provider,
                macro_version=payment.macro_version, source_mode='formal')
            self.payment_publications = QSPaymentCalculationPublicationStore(store=base.store,
                registry=base.registry, methods=base.methods, organizations=base.organizations,
                validate_source=self.payment_validator.validate_source)
            self.payment_assembler = QSPaymentActionAssembler(registry=base.registry, organizations=base.organizations,
                provider=base.provider, macro_version=payment.macro_version, source_mode='formal', methods=base.methods,
                policy_version=payment.policy_version, model_version=config.model_version, model_host=model)
            self.provider = QSPaymentCalculationPublishedViewProvider(provider=self.change_provider, publications=self.payment_publications)
        self.payment_provider = self.provider
        if config.final_account_calculations is not None:
            if not isinstance(base.methods, MethodRegistry):
                raise ValueError('QS final-account publication requires an explicit original bound method registry')
            final = config.final_account_calculations
            self.final_account_validator = QSFinalAccountCalculationSourceValidator(registry=base.registry,
                organizations=base.organizations, provider=base.provider,
                macro_version=final.macro_version, source_mode='formal')
            self.final_account_publications = QSFinalAccountCalculationPublicationStore(store=base.store,
                registry=base.registry, methods=base.methods, organizations=base.organizations,
                validate_source=self.final_account_validator.validate_source)
            self.final_account_assembler = QSFinalAccountActionAssembler(registry=base.registry, organizations=base.organizations,
                provider=base.provider, macro_version=final.macro_version, source_mode='formal', methods=base.methods,
                policy_version=final.policy_version, model_version=config.model_version, model_host=model)
            self.provider = QSFinalAccountCalculationPublishedViewProvider(provider=self.payment_provider,
                publications=self.final_account_publications)
        self.final_account_provider = self.provider
        if config.procurement_documents is not None:
            self.procurement_worker = QSProcurementResultWorker(store=base.store,
                snapshots=InvocationSnapshotStore(base.store), registry=base.registry,
                client_version=config.client_version, model_version=config.model_version,
                validate_invocation=base.validators.invocation, validate_wait=base.validators.wait,
                validate_recovery=base.validators.recovery)
            self.procurement_validator = QSProcurementDocumentSourceValidator(worker=self.procurement_worker,
                organizations=base.organizations, provider=base.provider,
                macro_version=config.procurement_documents.macro_version, source_mode='formal')
            self.procurement_publications = QSProcurementDocumentPublicationStore(worker=self.procurement_worker,
                organizations=base.organizations, validate_source=self.procurement_validator.validate_source)
            self.provider = QSProcurementDocumentPublishedViewProvider(provider=self.final_account_provider,
                publications=self.procurement_publications)
        self.procurement_provider = self.provider
        if config.bid_normalization is not None:
            if not isinstance(base.methods, MethodRegistry):
                raise ValueError('QS bid normalization requires the original bound method registry')
            bid = config.bid_normalization
            self.bid_validator = QSBidNormalizationSourceValidator(registry=base.registry,
                organizations=base.organizations, provider=base.provider,
                macro_version=bid.macro_version, source_mode='formal')
            self.bid_publications = QSBidNormalizationPublicationStore(store=base.store,
                registry=base.registry, methods=base.methods, organizations=base.organizations,
                validate_source=self.bid_validator.validate_source)
            self.bid_assembler = QSBidActionAssembler(registry=base.registry, organizations=base.organizations,
                provider=base.provider, macro_version=bid.macro_version, source_mode='formal', methods=base.methods,
                policy_version=bid.policy_version, model_version=config.model_version, model_host=model)
            self.provider = QSBidNormalizationPublishedViewProvider(provider=self.procurement_provider,
                publications=self.bid_publications)
        self.bid_provider = self.provider
        if config.bid_ranking is not None:
            ranking = config.bid_ranking
            if (self.bid_publications is None or ranking.macro_version != config.bid_normalization.macro_version):
                raise ValueError('QS ranking requires the same-version configured original normalization store')
            self.ranking_validator = QSBidRankingSourceValidator(normalizations=self.bid_publications,
                registry=base.registry, organizations=base.organizations, provider=base.provider,
                macro_version=ranking.macro_version, source_mode='formal')
            self.ranking_publications = QSBidRankingPublicationStore(normalizations=self.bid_publications,
                store=base.store, registry=base.registry, methods=base.methods, organizations=base.organizations,
                validate_source=self.ranking_validator.validate_source)
            self.ranking_assembler = QSBidActionAssembler(registry=base.registry, organizations=base.organizations,
                provider=self.bid_provider, macro_version=ranking.macro_version, source_mode='formal', methods=base.methods,
                policy_version=ranking.policy_version, model_version=config.model_version, model_host=model)
            self.provider = QSBidRankingPublishedViewProvider(provider=self.bid_provider, publications=self.ranking_publications)
        self.ranking_provider = self.provider
        if config.billing_calculations is not None:
            billing = config.billing_calculations
            self.billing_validator = QSBillingCalculationSourceValidator(registry=base.registry,
                organizations=base.organizations, provider=base.provider,
                macro_version=billing.macro_version, source_mode='formal')
            self.billing_publications = QSBillingCalculationPublicationStore(store=base.store,
                registry=base.registry, organizations=base.organizations,
                validate_source=self.billing_validator.validate_source)
            self.billing_assembler = QSBillingActionAssembler(registry=base.registry, organizations=base.organizations,
                provider=base.provider, macro_version=billing.macro_version, source_mode='formal', methods=base.methods,
                policy_version=billing.policy_version, model_version=config.model_version, model_host=model)
            self.provider = QSBillingCalculationPublishedViewProvider(provider=self.ranking_provider,
                publications=self.billing_publications)
        self.billing_provider = self.provider
        if config.learning_comparability is not None:
            if not isinstance(base.methods, MethodRegistry):
                raise ValueError('QS forecast comparison requires the original bound method registry')
            comparison = config.learning_comparability
            self.comparability_validator = QSLearningComparabilitySourceValidator(registry=base.registry,
                organizations=base.organizations, provider=base.provider,
                macro_version=comparison.macro_version, source_mode='formal')
            self.comparability_publications = QSLearningComparabilityPublicationStore(store=base.store,
                registry=base.registry, methods=base.methods, organizations=base.organizations,
                validate_source=self.comparability_validator.validate_source)
            self.comparability_assembler = QSLearningActionAssembler(registry=base.registry, organizations=base.organizations,
                provider=base.provider, macro_version=comparison.macro_version, source_mode='formal', methods=base.methods,
                policy_version=comparison.policy_version, model_version=config.model_version, model_host=model)
            self.provider = QSLearningComparabilityPublishedViewProvider(provider=self.billing_provider,
                publications=self.comparability_publications)
        self.comparability_provider = self.provider
        if config.learning_error is not None:
            error = config.learning_error
            if (self.comparability_publications is None
                    or error.macro_version != config.learning_comparability.macro_version):
                raise ValueError('QS forecast error requires the same-version configured original comparison store')
            self.error_validator = QSLearningErrorSourceValidator(comparisons=self.comparability_publications,
                registry=base.registry, organizations=base.organizations, provider=base.provider,
                macro_version=error.macro_version, source_mode='formal')
            self.error_publications = QSLearningErrorPublicationStore(comparisons=self.comparability_publications,
                store=base.store, registry=base.registry, methods=base.methods, organizations=base.organizations,
                validate_source=self.error_validator.validate_source)
            self.error_assembler = QSLearningActionAssembler(registry=base.registry, organizations=base.organizations,
                provider=self.comparability_provider, macro_version=error.macro_version, source_mode='formal', methods=base.methods,
                policy_version=error.policy_version, model_version=config.model_version, model_host=model)
            self.provider = QSLearningErrorPublishedViewProvider(provider=self.comparability_provider,
                publications=self.error_publications)
        self.error_provider = self.provider
        if config.learning_assessment is not None:
            assessment = config.learning_assessment
            if (not isinstance(base.methods, MethodRegistry)
                    or config.learning_error is not None and assessment.macro_version != config.learning_error.macro_version):
                raise ValueError('QS learning assessment requires original methods and same-version configured cost dependencies')
            self.assessment_validator = QSLearningAssessmentSourceValidator(errors=self.error_publications,
                registry=base.registry, organizations=base.organizations, provider=base.provider,
                macro_version=assessment.macro_version, source_mode='formal')
            self.assessment_publications = QSLearningAssessmentPublicationStore(errors=self.error_publications,
                store=base.store, registry=base.registry, methods=base.methods, organizations=base.organizations,
                validate_source=self.assessment_validator.validate_source)
            self.assessment_assembler = QSLearningActionAssembler(registry=base.registry, organizations=base.organizations,
                provider=self.error_provider, macro_version=assessment.macro_version, source_mode='formal', methods=base.methods,
                policy_version=assessment.policy_version, model_version=config.model_version, model_host=model)
            self.provider = QSLearningAssessmentPublishedViewProvider(provider=self.error_provider,
                publications=self.assessment_publications)
        self.assessment_provider = self.provider
        if config.training_estimates is not None:
            training = config.training_estimates
            if not isinstance(base.methods, MethodRegistry):
                raise ValueError('QS training estimates require the original bound method registry')
            self.training_validator = QSTrainingEstimateSourceValidator(registry=base.registry,
                organizations=base.organizations, provider=base.provider,
                macro_version=training.macro_version, source_mode='formal')
            self.training_publications = QSTrainingEstimatePublicationStore(store=base.store,
                registry=base.registry, methods=base.methods, organizations=base.organizations,
                validate_source=self.training_validator.validate_source)
            self.training_assembler = QSLearningActionAssembler(registry=base.registry, organizations=base.organizations,
                provider=base.provider, macro_version=training.macro_version, source_mode='formal', methods=base.methods,
                policy_version=training.policy_version, model_version=config.model_version, model_host=model)
            self.provider = QSTrainingEstimatePublishedViewProvider(provider=self.assessment_provider,
                publications=self.training_publications)
        self.training_provider = self.provider
        if config.research_normalizations is not None:
            normalization = config.research_normalizations
            if not isinstance(base.methods, MethodRegistry):
                raise ValueError('QS research normalization requires its original method registry')
            self.research_normalization_validator = QSResearchNormalizationSourceValidator(registry=base.registry,
                organizations=base.organizations, provider=base.provider,
                macro_version=normalization.macro_version, source_mode='formal',
                validate_normalization_basis=dependencies.validate_research_normalization_basis)
            self.research_normalization_publications = QSResearchNormalizationPublicationStore(store=base.store,
                registry=base.registry, methods=base.methods, organizations=base.organizations,
                validate_source=self.research_normalization_validator.validate_source)
            self.research_normalization_assembler = QSResearchActionAssembler(registry=base.registry,
                organizations=base.organizations, provider=base.provider, macro_version=normalization.macro_version,
                source_mode='formal', methods=base.methods, policy_version=normalization.policy_version,
                model_version=config.model_version, model_host=model)
            self.provider = QSResearchNormalizationPublishedViewProvider(provider=self.training_provider,
                publications=self.research_normalization_publications)
        self.research_normalization_provider = self.provider
        if config.research_rankings is not None:
            ranking = config.research_rankings
            self.research_ranking_validator = QSResearchRankingSourceValidator(registry=base.registry,
                organizations=base.organizations, provider=base.provider, macro_version=ranking.macro_version,
                source_mode='formal', normalizations=self.research_normalization_publications,
                validate_ranking_basis=dependencies.validate_research_ranking_basis)
            self.research_ranking_publications = QSResearchRankingPublicationStore(store=base.store,
                registry=base.registry, methods=base.methods, organizations=base.organizations,
                normalizations=self.research_normalization_publications,
                validate_source=self.research_ranking_validator.validate_source)
            self.research_ranking_assembler = QSResearchActionAssembler(registry=base.registry,
                organizations=base.organizations, provider=self.research_normalization_provider, macro_version=ranking.macro_version,
                source_mode='formal', methods=base.methods, policy_version=ranking.policy_version,
                model_version=config.model_version, model_host=model)
            self.provider = QSResearchRankingPublishedViewProvider(provider=self.research_normalization_provider,
                publications=self.research_ranking_publications)
        self._research_ranking_components = (self.provider, self.research_ranking_validator,
            self.research_ranking_publications, self.research_ranking_assembler, base.methods,
            dependencies.validate_research_ranking_basis)
        self._research_ranking_source_components = (() if self.research_ranking_validator is None else (
            self.research_ranking_validator._views, self.research_ranking_validator._views.schemas,
            self.research_ranking_assembler._views, self.research_ranking_assembler._views.schemas,
            self.research_ranking_publications.schemas))
        self._research_normalization_components = (self.research_normalization_provider, self.research_normalization_validator,
            self.research_normalization_publications, self.research_normalization_assembler, base.methods,
            dependencies.validate_research_normalization_basis)
        self._research_normalization_source_components = (() if self.research_normalization_validator is None else (
            self.research_normalization_validator._views, self.research_normalization_validator._views.schemas,
            self.research_normalization_assembler._views, self.research_normalization_assembler._views.schemas,
            self.research_normalization_publications.schemas))
        self._training_components = (self.training_provider, self.training_validator, self.training_publications,
            self.training_assembler, base.methods)
        self._assessment_components = (self.assessment_provider, self.assessment_validator, self.assessment_publications,
            self.assessment_assembler, base.methods)
        self._error_components = (self.error_provider, self.error_validator, self.error_publications, self.error_assembler, base.methods)
        self._comparability_components = (self.comparability_provider, self.comparability_validator,
            self.comparability_publications, self.comparability_assembler, base.methods)
        self._billing_components = (self.billing_provider, self.billing_validator, self.billing_publications, self.billing_assembler)
        self._ranking_components = (self.ranking_provider, self.ranking_validator, self.ranking_publications, self.ranking_assembler, base.methods)
        self._bid_components = (self.bid_provider, self.bid_validator, self.bid_publications, self.bid_assembler, base.methods)
        self._procurement_components = (self.procurement_provider, self.procurement_worker,
            self.procurement_validator, self.procurement_publications)
        self._cost_components = (self.cost_provider, self.cost_validator, self.cost_publications, self.cost_assembler, base.methods)
        self._change_components = (self.change_provider, self.change_validator, self.change_publications, self.change_assembler, base.methods)
        self._payment_components = (self.payment_provider, self.payment_validator, self.payment_publications, self.payment_assembler, base.methods)
        self._final_account_components = (self.final_account_provider, self.final_account_validator,
            self.final_account_publications, self.final_account_assembler, base.methods)
        if config.submission is not None:
            snapshots = InvocationSnapshotStore(base.store)
            workers = {}
            for action_id in sorted(actions):
                if action_id == 'QS-A05' and self.procurement_worker is not None:
                    workers[action_id] = self.procurement_worker
                    continue
                module, name = _ACTIONS[action_id]
                worker_type = getattr(importlib.import_module('integration.qs_' + module + '_results'),
                    'QS' + name + 'ResultWorker')
                workers[action_id] = worker_type(store=base.store, snapshots=snapshots, registry=base.registry,
                    client_version=config.client_version, model_version=config.model_version,
                    validate_invocation=base.validators.invocation, validate_wait=base.validators.wait,
                    validate_recovery=base.validators.recovery)
            self.submissions = QSSubmissionHost(store=base.store, registry=base.registry, workers=workers,
                callbacks=dependencies.submission_callbacks, read_guard=dependencies.submission_read_guard,
                configuration=config.submission)
        if config.feedback is not None:
            inbox = ObservationInbox(base.store.run_id, base.store.organization_ids, Path(config.feedback.inbox_path))
            self.feedback = QSSubmissionFeedback(host=self.submissions, inbox=inbox,
                version=config.feedback.version, validate_relation=dependencies.validate_feedback_relation,
                validate_read=dependencies.validate_feedback_read)
        if recovery is not None:
            assembler_type, reader_type, dispatcher_factory = self._recovery_types()
            self.payment_recovery_assembler = assembler_type(registry=base.registry,
                organizations=base.organizations, provider=self.provider, methods=base.methods,
                macro_version=config.execution_recovery.macro_version, source_mode='formal',
                policy_version=config.execution_recovery.policy_version, model_version=config.model_version, model_host=model)
            self.payment_reader = reader_type(assembler=self.payment_recovery_assembler,
                snapshots=InvocationSnapshotStore(base.store), select_current=recovery.select_current)
            self.execution_dispatcher = dispatcher_factory(inbox=self.feedback.inbox, store=base.store,
                assembler=self.payment_recovery_assembler, select_current=recovery.select_current,
                read_guard=recovery.read_guard, validate_relation=recovery.validate_relation,
                project_signal=recovery.project_signal, prepare=recovery.prepare, revalidate=recovery.revalidate,
                **({'reader': self.payment_reader} if config.action_id in {'QS-A02', 'QS-A10', 'QS-A11', 'QS-A12'} else {}))
            self._payment_recovery_components = (recovery, *recovery.components(), self.payment_recovery_assembler,
                self.payment_reader, self.execution_dispatcher, self.feedback.inbox, self.provider)
        self._declared = self._configuration()
        self._key = 'qs_formal_application:' + task_digest([config.dependency_factory, config.action_id])
        with base.store._transaction():
            prior = base.store._db.execute('SELECT value FROM metadata WHERE key=?', (self._key,)).fetchone()
            if prior is None:
                base.store._db.execute('INSERT INTO metadata VALUES (?,?)', (self._key, canonical(self._declared)))
            elif json.loads(prior[0]) != self._declared:
                raise TaskConflict('Original formal QS application configuration changed; explicit review required')

    def _recovery_types(self):
        if self.settings.action_id == 'QS-A10':
            return QSBillingActionAssembler, QSBillingRecoveryReader, build_assembled_qs_billing_dispatcher
        if self.settings.action_id == 'QS-A02':
            return QSIntakeActionAssembler, QSIntakeRecoveryReader, build_assembled_qs_intake_dispatcher
        if self.settings.action_id == 'QS-A11':
            return QSTransitionActionAssembler, QSTransitionReader, build_assembled_qs_transition_dispatcher
        if self.settings.action_id == 'QS-A04':
            return QSCostActionAssembler, QSCostReader, build_assembled_qs_cost_dispatcher
        if self.settings.action_id == 'QS-A05':
            return QSProcurementActionAssembler, QSProcurementReader, build_assembled_qs_procurement_dispatcher
        if self.settings.action_id == 'QS-A06':
            return QSBidActionAssembler, QSBidReader, build_assembled_qs_bid_dispatcher
        if self.settings.action_id == 'QS-A07':
            return QSChangeActionAssembler, QSChangeReader, build_assembled_qs_change_dispatcher
        if self.settings.action_id == 'QS-A08':
            return QSPaymentActionAssembler, QSPaymentReader, build_assembled_qs_payment_dispatcher
        if self.settings.action_id == 'QS-A13':
            return QSResearchActionAssembler, QSResearchRecoveryReader, build_assembled_qs_research_dispatcher
        if self.settings.action_id == 'QS-A03':
            return QSAppointmentActionAssembler, QSAppointmentReader, build_assembled_qs_appointment_dispatcher
        if self.settings.action_id == 'QS-A09':
            return QSFinalAccountActionAssembler, QSFinalAccountReader, build_assembled_qs_final_account_dispatcher
        if self.settings.action_id == 'QS-A12':
            return QSLearningActionAssembler, QSLearningReader, build_assembled_qs_learning_dispatcher
        raise TaskConflict('QS execution recovery changes its supported original action')

    def _configuration(self):
        return {'schema_version': self.VERSION, 'run_id': self.base.store.run_id,
            'settings_sha256': task_digest(self.settings.model_dump(mode='json')),
            'dependency_version': self.dependencies.version, 'source_version': self.base.version,
            'dependency_factory': self.factory_descriptor, 'sources': _descriptors(self.base),
            'code': module_factory_descriptor(type(self).sources, self.VERSION),
            'model_configuration_sha256': self.base.model_host.configuration_sha256,
            'execution_recovery': None if self.payment_reader is None else {
                'reader': self.payment_reader.configuration_evidence(),
                'callbacks': self.dependencies.execution_recovery.configuration_evidence()},
            'submission_sha256': task_digest(self.submissions._declared) if self.submissions is not None else None,
            'feedback_sha256': task_digest(self.feedback._declared) if self.feedback is not None else None,
            'feedback_validators': {name: module_factory_descriptor(callback, name) if callback is not None else None
                for name, callback in (('validate_feedback_relation', self.dependencies.validate_feedback_relation),
                    ('validate_feedback_read', self.dependencies.validate_feedback_read),
                    ('validate_feedback_input', self.dependencies.validate_feedback_input))},
            'submission_read_guard': module_factory_descriptor(self.dependencies.submission_read_guard, 'submission_read_guard')
                if self.dependencies.submission_read_guard is not None else None,
            'cost_calculations': None if self.cost_validator is None else {
                'validator': deepcopy(self.cost_validator._declared),
                'method_registry_sha256': self.base.methods.content_digest,
                'provider': module_factory_descriptor(self.cost_provider.project, 'QS.cost_publication_provider'),
                'producer': module_factory_descriptor(type(self.cost_assembler).publish_calculation, 'QS.cost_calculation_producer'),
                'save': module_factory_descriptor(self.cost_publications.save, 'QS.cost_execution_save'),
                'publish': module_factory_descriptor(self.cost_publications.publish, 'QS.cost_execution_publish'),
                'read': module_factory_descriptor(self.cost_publications.read, 'QS.cost_execution_read')},
            'change_calculations': None if self.change_validator is None else {
                'validator': deepcopy(self.change_validator._declared),
                'method_registry_sha256': self.base.methods.content_digest,
                'provider': module_factory_descriptor(self.change_provider.project, 'QS.change_publication_provider'),
                'producer': module_factory_descriptor(type(self.change_assembler).publish_calculation, 'QS.change_calculation_producer'),
                'save': module_factory_descriptor(self.change_publications.save, 'QS.change_execution_save'),
                'publish': module_factory_descriptor(self.change_publications.publish, 'QS.change_execution_publish'),
                'read': module_factory_descriptor(self.change_publications.read, 'QS.change_execution_read')},
            'payment_calculations': None if self.payment_validator is None else {
                'validator': deepcopy(self.payment_validator._declared),
                'method_registry_sha256': self.base.methods.content_digest,
                'provider': module_factory_descriptor(self.payment_provider.project, 'QS.payment_publication_provider'),
                'producer': module_factory_descriptor(type(self.payment_assembler).publish_calculations, 'QS.payment_calculation_producer'),
                'save': module_factory_descriptor(self.payment_publications.save, 'QS.payment_execution_save'),
                'publish': module_factory_descriptor(self.payment_publications.publish, 'QS.payment_execution_publish'),
                'read': module_factory_descriptor(self.payment_publications.read, 'QS.payment_execution_read'),
                'bundle_validation': module_factory_descriptor(self.payment_publications._validate, 'QS.payment_bundle_validation'),
                'target_save': module_factory_descriptor(self.payment_publications._save_targets, 'QS.payment_target_save'),
                'target_read': module_factory_descriptor(self.payment_publications._validate_saved_targets, 'QS.payment_target_read')},
            'final_account_calculations': None if self.final_account_validator is None else {
                'validator': deepcopy(self.final_account_validator._declared),
                'method_registry_sha256': self.base.methods.content_digest,
                'provider': module_factory_descriptor(self.final_account_provider.project, 'QS.final_account_publication_provider'),
                'producer': module_factory_descriptor(type(self.final_account_assembler).publish_reconciliation,
                    'QS.final_account_calculation_producer'),
                'save': module_factory_descriptor(self.final_account_publications.save, 'QS.final_account_execution_save'),
                'publish': module_factory_descriptor(self.final_account_publications.publish, 'QS.final_account_execution_publish'),
                'read': module_factory_descriptor(self.final_account_publications.read, 'QS.final_account_execution_read'),
                'validation': module_factory_descriptor(self.final_account_publications._validate, 'QS.final_account_execution_validation')},
            'procurement_documents': None if self.procurement_validator is None else {
                'validator': deepcopy(self.procurement_validator._declared),
                'worker': deepcopy(self.procurement_validator._worker_declared),
                'provider': module_factory_descriptor(self.procurement_provider.project, 'QS.procurement_document_provider'),
                'prepare': module_factory_descriptor(self.procurement_worker.prepare_document, 'QS.procurement_document_prepare'),
                'save': module_factory_descriptor(self.procurement_publications.save, 'QS.procurement_document_save'),
                'publish': module_factory_descriptor(self.procurement_publications.publish, 'QS.procurement_document_publish'),
                'read': module_factory_descriptor(self.procurement_publications.read, 'QS.procurement_document_read'),
                'validation': module_factory_descriptor(self.procurement_publications._validate, 'QS.procurement_document_validation'),
                'retained_source': module_factory_descriptor(self.procurement_publications._validate_saved_targets,
                    'QS.procurement_document_retained_source')},
            'bid_normalization': None if self.bid_validator is None else {
                'validator': deepcopy(self.bid_validator._declared),
                'method_registry_sha256': self.base.methods.content_digest,
                'provider': module_factory_descriptor(self.bid_provider.project, 'QS.bid_normalization_provider'),
                'producer': module_factory_descriptor(self.bid_assembler.prepare_normalization, 'QS.bid_normalization_producer'),
                'save_entry': module_factory_descriptor(self.bid_assembler.save_normalization, 'QS.bid_normalization_save_entry'),
                'save': module_factory_descriptor(self.bid_publications.save, 'QS.bid_normalization_save'),
                'publish': module_factory_descriptor(self.bid_publications.publish, 'QS.bid_normalization_publish'),
                'read': module_factory_descriptor(self.bid_publications.read, 'QS.bid_normalization_read'),
                'validation': module_factory_descriptor(self.bid_publications._validate, 'QS.bid_normalization_validation')},
            'bid_ranking': None if self.ranking_validator is None else {
                'validator': deepcopy(self.ranking_validator._declared),
                'method_registry_sha256': self.base.methods.content_digest,
                'provider': module_factory_descriptor(self.ranking_provider.project, 'QS.bid_ranking_provider'),
                'save_entry': module_factory_descriptor(self.ranking_assembler.save_ranking, 'QS.bid_ranking_save_entry'),
                'save': module_factory_descriptor(self.ranking_publications.save, 'QS.bid_ranking_save'),
                'publish': module_factory_descriptor(self.ranking_publications.publish, 'QS.bid_ranking_publish'),
                'read': module_factory_descriptor(self.ranking_publications.read, 'QS.bid_ranking_read'),
                'validation': module_factory_descriptor(self.ranking_publications._validate, 'QS.bid_ranking_validation'),
                'dependencies': module_factory_descriptor(self.ranking_publications._publication_content, 'QS.bid_ranking_dependencies')},
            'billing_calculations': None if self.billing_validator is None else {
                'validator': deepcopy(self.billing_validator._declared),
                'provider': module_factory_descriptor(self.billing_provider.project, 'QS.billing_calculation_provider'),
                'producer': module_factory_descriptor(self.billing_assembler.prepare_calculation, 'QS.billing_calculation_producer'),
                'save_entry': module_factory_descriptor(self.billing_assembler.save_calculation, 'QS.billing_calculation_save_entry'),
                'save': module_factory_descriptor(self.billing_publications.save, 'QS.billing_calculation_save'),
                'publish': module_factory_descriptor(self.billing_publications.publish, 'QS.billing_calculation_publish'),
                'read': module_factory_descriptor(self.billing_publications.read, 'QS.billing_calculation_read'),
                'validation': module_factory_descriptor(self.billing_publications._validate, 'QS.billing_calculation_validation'),
                'binding': self.billing_publications._binding()},
            'learning_comparability': None if self.comparability_validator is None else {
                'validator': deepcopy(self.comparability_validator._declared),
                'method_registry_sha256': self.base.methods.content_digest,
                'provider': module_factory_descriptor(self.comparability_provider.project, 'QS.learning_comparability_provider'),
                'producer': module_factory_descriptor(self.comparability_assembler.prepare_comparability, 'QS.learning_comparability_producer'),
                'save_entry': module_factory_descriptor(self.comparability_assembler.save_comparability, 'QS.learning_comparability_save_entry'),
                'save': module_factory_descriptor(self.comparability_publications.save, 'QS.learning_comparability_save'),
                'publish': module_factory_descriptor(self.comparability_publications.publish, 'QS.learning_comparability_publish'),
                'read': module_factory_descriptor(self.comparability_publications.read, 'QS.learning_comparability_read'),
                'validation': module_factory_descriptor(self.comparability_publications._validate, 'QS.learning_comparability_validation')},
            'learning_error': None if self.error_validator is None else {
                'validator': deepcopy(self.error_validator._declared),
                'method_registry_sha256': self.base.methods.content_digest,
                'provider': module_factory_descriptor(self.error_provider.project, 'QS.learning_error_provider'),
                'producer': module_factory_descriptor(self.error_assembler.prepare_error, 'QS.learning_error_producer'),
                'save_entry': module_factory_descriptor(self.error_assembler.save_error, 'QS.learning_error_save_entry'),
                'save': module_factory_descriptor(self.error_publications.save, 'QS.learning_error_save'),
                'publish': module_factory_descriptor(self.error_publications.publish, 'QS.learning_error_publish'),
                'read': module_factory_descriptor(self.error_publications.read, 'QS.learning_error_read'),
                'validation': module_factory_descriptor(self.error_publications._validate, 'QS.learning_error_validation'),
                'dependencies': module_factory_descriptor(self.error_publications._publication_content, 'QS.learning_error_dependencies')},
            'learning_assessment': None if self.assessment_validator is None else {
                'validator': deepcopy(self.assessment_validator._declared),
                'method_registry_sha256': self.base.methods.content_digest,
                'provider': module_factory_descriptor(self.assessment_provider.project, 'QS.learning_assessment_provider'),
                'producer': module_factory_descriptor(self.assessment_assembler.prepare_assessment, 'QS.learning_assessment_producer'),
                'save_entry': module_factory_descriptor(self.assessment_assembler.save_assessment, 'QS.learning_assessment_save_entry'),
                'save': module_factory_descriptor(self.assessment_publications.save, 'QS.learning_assessment_save'),
                'publish': module_factory_descriptor(self.assessment_publications.publish, 'QS.learning_assessment_publish'),
                'read': module_factory_descriptor(self.assessment_publications.read, 'QS.learning_assessment_read'),
                'validation': module_factory_descriptor(self.assessment_publications._validate, 'QS.learning_assessment_validation'),
                'dependencies': module_factory_descriptor(self.assessment_publications._publication_content, 'QS.learning_assessment_dependencies')},
            'training_estimates': None if self.training_validator is None else {
                'validator': deepcopy(self.training_validator._declared),
                'method_registry_sha256': self.base.methods.content_digest,
                'provider': module_factory_descriptor(self.training_provider.project, 'QS.training_estimate_provider'),
                'producer': module_factory_descriptor(self.training_assembler.prepare_training_estimate, 'QS.training_estimate_producer'),
                'save_entry': module_factory_descriptor(self.training_assembler.save_training_estimate, 'QS.training_estimate_save_entry'),
                'save': module_factory_descriptor(self.training_publications.save, 'QS.training_estimate_save'),
                'publish': module_factory_descriptor(self.training_publications.publish, 'QS.training_estimate_publish'),
                'read': module_factory_descriptor(self.training_publications.read, 'QS.training_estimate_read'),
                'validation': module_factory_descriptor(self.training_publications._validate, 'QS.training_estimate_validation')},
            'research_normalizations': self._research_normalization_configuration(),
            'research_rankings': self._research_comparison_configuration(kind='ranking'),
            'submission_callbacks': {action: {name: module_factory_descriptor(callback, name) if callback is not None else None
                for name, callback in vars(callbacks).items()}
                for action, callbacks in sorted(self.dependencies.submission_callbacks.items())}}

    def _research_normalization_configuration(self):
        return self._research_comparison_configuration(kind='normalization')

    def _research_comparison_configuration(self, *, kind):
        validator = getattr(self, 'research_' + kind + '_validator')
        if validator is None:
            return None
        publications = getattr(self, 'research_' + kind + '_publications')
        assembler = getattr(self, 'research_' + kind + '_assembler')
        provider = self.research_normalization_provider if kind=='normalization' else self.provider
        callbacks = {
            'provider': provider.project,
            'producer': prepare_qs_research_normalization_calculation if kind=='normalization' else prepare_qs_research_ranking_calculation,
            'shared_production_runtime': _prepare_qs_research_comparison_calculation,
            'prepare_input': validator.PREPARE_INPUT,
            'arithmetic_runtime': publications.PURE_REPORT,
            'input_validation': ResearchNormalizationInput.sourced_domain if kind=='normalization' else ResearchRankInput.selected_domain,
            'assembler_schemas': assembler.SOURCE_SCHEMAS,
            'validator_schemas': validator.SOURCE_SCHEMAS,
            'publication_schemas': publications.SOURCE_SCHEMAS,
            'prepare_entry': getattr(assembler, 'prepare_' + kind + '_calculation'),
            'reading': getattr(assembler, '_build_' + kind + '_reading'),
            'shared_reading': assembler._build_comparison_reading,
            'save_entry': getattr(assembler, 'save_' + kind + '_calculation'),
            'save': publications.save, 'publish': publications.publish, 'read': publications.read,
            'validation': publications._validate, 'proof_validation': publications._validate_method_execution,
            'publication_validation_runtime': QSResearchNormalizationPublicationStore._validate,
            'current_validation': validator.validate_current, 'source_validation': validator.validate_source,
            'source_reading': validator._reading,
            'actual_basis_verifier': getattr(self.dependencies, 'validate_research_' + kind + '_basis'),
            'report_association': publications._matches_output,
            'preparation_payload': publications.PREPARATION_PAYLOAD,
            'publication_prepare_input': publications.PREPARE_INPUT,
            'result_projections': publications._result_projections,
            'publication_content': publications._publication_content,
            'publication_refs': publications._publication_refs,
        }
        if kind=='ranking':
            callbacks.update(provenance_validation=validator.validate_normalization_provenance,
                dependency_reading=validator._normalization_record,
                dependency_validation=publications._validate_normalization,
                published_objects=publications._published_objects,
                local_dependency_sources=validator._local_dependency_sources,
                normalization_producer_provider=self.research_normalization_provider.project,
                normalization_actual_source=self.research_normalization_publications.validate_source)
        schemas = {name: {kind: {
                'model': model.__module__ + ':' + model.__qualname__,
                'version_type': version_type.__name__, 'identity_field': registry._identity_fields[kind],
                'schema_sha256': task_digest(model.model_json_schema()),
            } for kind, (model, version_type) in sorted(registry._schemas.items())}
            for name, registry in (('assembler', assembler._views.schemas),
                ('validator', validator._views.schemas), ('publication', publications.schemas))}
        return {'validator': deepcopy(validator._declared),
            **{name: module_factory_descriptor(callback, 'QS.research_' + kind + '.' + name)
                for name, callback in callbacks.items()},
            'schema_bindings': schemas, 'publication_binding': publications._binding(),
            'record_schema': publications.SCHEMA, 'publication_schema': publications.PUBLICATION_SCHEMA,
            'records_table': publications.RECORDS_TABLE, 'publications_table': publications.PUBLICATIONS_TABLE,
            'action_id': publications.ACTION_ID, 'role': publications.ROLE,
            'method_ref': publications.METHOD_REF.model_dump(mode='json'),
            'method_registry_sha256': self.base.methods.content_digest}

    def _check(self):
        components = (self.base, self.base.store, self.base.registry,
            self.base.organizations, self.base.provider, self.base.model_host)
        if (self._closed or any(actual is not original for actual, original in zip(components, self._components))
                or self.dependencies.sources is not self.base
                or self.base.model_host.store is not self.base.store or self.base.model_host.registry is not self.base.registry
                or self.base.model_host.model_version != self.settings.model_version
                or module_factory_descriptor(_load_factory(self.settings.dependency_factory),
                    self.settings.dependency_factory) != self.factory_descriptor
                or self._configuration() != self._declared):
            raise TaskConflict('Original formal QS components or configuration changed, or application closed')
        recovery = self.dependencies.execution_recovery
        if self._payment_recovery_components is None:
            if any(value is not None for value in (recovery, self.payment_recovery_assembler, self.payment_reader, self.execution_dispatcher)):
                raise TaskConflict('Undeclared QS execution recovery components were added')
        else:
            current = (recovery, *recovery.components(), self.payment_recovery_assembler, self.payment_reader,
                self.execution_dispatcher, self.feedback.inbox, self.provider)
            assembler = self.payment_recovery_assembler
            assembler_type, reader_type, _ = self._recovery_types()
            if (len(current) != len(self._payment_recovery_components)
                    or any(now is not old for now, old in zip(current, self._payment_recovery_components))
                    or type(assembler) is not assembler_type or type(self.payment_reader) is not reader_type
                    or assembler.registry is not self.base.registry or assembler.organizations is not self.base.organizations
                    or assembler.provider is not self.provider or assembler.methods is not self.base.methods
                    or self.payment_reader.snapshots.store is not self.base.store or self.payment_reader.ACTION_ID != self.settings.action_id
                    or self.execution_dispatcher.action_id != self.settings.action_id
                    or len(assembler.decision_strategies) != len(self.base.model_host.bindings)
                    or any(now is not old for now, old in zip(assembler.decision_strategies, self.base.model_host.bindings))):
                raise TaskConflict('QS execution recovery changed original source/model/journal/recipient/callback bindings')
            self.payment_reader._check()
            self.execution_dispatcher._check()
        if self.submissions is not None:
            self.submissions._check()
            if (self.submissions.store is not self.base.store or self.submissions.registry is not self.base.registry
                    or self.submissions.read_guard is not self.dependencies.submission_read_guard
                    or any(self.submissions.callbacks[action] is not callback
                        for action, callback in self.dependencies.submission_callbacks.items())):
                raise TaskConflict('Formal QS submission components changed')
        if self.feedback is not None:
            self.feedback._check()
            if (self.feedback.host is not self.submissions
                    or self.feedback.validate_relation is not self.dependencies.validate_feedback_relation
                    or self.feedback.validate_read is not self.dependencies.validate_feedback_read):
                raise TaskConflict('Formal QS feedback components or validators changed')
        if any(actual is not original for actual, original in zip(
                (self.cost_provider, self.cost_validator, self.cost_publications, self.cost_assembler, self.base.methods), self._cost_components)):
            raise TaskConflict('Formal QS cost publication components changed')
        if self.cost_validator is not None:
            self.cost_validator._check()
            if (self.cost_validator.provider is not self.base.provider
                    or self.cost_validator.registry is not self.base.registry or self.cost_validator.organizations is not self.base.organizations
                    or self.cost_publications.store is not self.base.store or self.cost_publications.registry is not self.base.registry
                    or self.cost_publications.organizations is not self.base.organizations or self.cost_publications.methods is not self.base.methods
                    or self.cost_publications.validate_source != self.cost_validator.validate_source
                    or self.cost_provider.provider is not self.base.provider or self.cost_provider.publications is not self.cost_publications
                    or self.cost_assembler.provider is not self.base.provider or self.cost_assembler.registry is not self.base.registry
                    or self.cost_assembler.organizations is not self.base.organizations or self.cost_assembler.methods is not self.base.methods
                    or self.cost_assembler._views.provider is not self.base.provider
                    or self.cost_assembler._views.organizations is not self.base.organizations
                    or self.cost_assembler._views.macro_version != self.settings.cost_calculations.macro_version
                    or self.cost_assembler._views.source_mode != 'formal'
                    or self.cost_assembler.macro_version != self.settings.cost_calculations.macro_version
                    or self.cost_assembler.policy_version != self.settings.cost_calculations.policy_version
                    or self.cost_assembler.source_mode != 'formal' or self.cost_assembler.model_version != self.settings.model_version
                    or self.cost_assembler.decision_strategies != tuple(self.base.model_host.bindings)):
                raise TaskConflict('Formal QS cost source, registry or publication wiring changed')
        if any(actual is not original for actual, original in zip(
                (self.change_provider, self.change_validator, self.change_publications, self.change_assembler, self.base.methods),
                self._change_components)):
            raise TaskConflict('Formal QS change publication components changed')
        if self.change_validator is not None:
            self.change_validator._check()
            if (self.change_validator.provider is not self.base.provider
                    or self.change_validator.registry is not self.base.registry
                    or self.change_validator.organizations is not self.base.organizations
                    or self.change_publications.store is not self.base.store or self.change_publications.registry is not self.base.registry
                    or self.change_publications.organizations is not self.base.organizations or self.change_publications.methods is not self.base.methods
                    or self.change_publications.validate_source != self.change_validator.validate_source
                    or self.change_provider.provider is not self.cost_provider or self.change_provider.publications is not self.change_publications
                    or self.change_assembler.provider is not self.base.provider or self.change_assembler.registry is not self.base.registry
                    or self.change_assembler.organizations is not self.base.organizations or self.change_assembler.methods is not self.base.methods
                    or self.change_assembler._views.provider is not self.base.provider
                    or self.change_assembler._views.organizations is not self.base.organizations
                    or self.change_assembler._views.macro_version != self.settings.change_calculations.macro_version
                    or self.change_assembler._views.source_mode != 'formal'
                    or self.change_assembler.macro_version != self.settings.change_calculations.macro_version
                    or self.change_assembler.policy_version != self.settings.change_calculations.policy_version
                    or self.change_assembler.source_mode != 'formal' or self.change_assembler.model_version != self.settings.model_version
                    or self.change_assembler.decision_strategies != tuple(self.base.model_host.bindings)):
                raise TaskConflict('Formal QS change source, registry or publication wiring changed')
        elif self.change_provider is not self.cost_provider:
            raise TaskConflict('Unconfigured QS change publication replaced its original source provider')
        if any(actual is not original for actual, original in zip(
                (self.payment_provider, self.payment_validator, self.payment_publications, self.payment_assembler, self.base.methods),
                self._payment_components)):
            raise TaskConflict('Formal QS payment publication components changed')
        if self.payment_validator is not None:
            self.payment_validator._check()
            if (self.payment_validator.provider is not self.base.provider
                    or self.payment_validator.registry is not self.base.registry
                    or self.payment_validator.organizations is not self.base.organizations
                    or self.payment_publications.store is not self.base.store or self.payment_publications.registry is not self.base.registry
                    or self.payment_publications.organizations is not self.base.organizations or self.payment_publications.methods is not self.base.methods
                    or self.payment_publications.validate_source != self.payment_validator.validate_source
                    or self.payment_provider.provider is not self.change_provider or self.payment_provider.publications is not self.payment_publications
                    or self.payment_assembler.provider is not self.base.provider or self.payment_assembler.registry is not self.base.registry
                    or self.payment_assembler.organizations is not self.base.organizations or self.payment_assembler.methods is not self.base.methods
                    or self.payment_assembler._views.provider is not self.base.provider
                    or self.payment_assembler._views.organizations is not self.base.organizations
                    or self.payment_assembler._views.macro_version != self.settings.payment_calculations.macro_version
                    or self.payment_assembler._views.source_mode != 'formal'
                    or self.payment_assembler.macro_version != self.settings.payment_calculations.macro_version
                    or self.payment_assembler.policy_version != self.settings.payment_calculations.policy_version
                    or self.payment_assembler.source_mode != 'formal' or self.payment_assembler.model_version != self.settings.model_version
                    or self.payment_assembler.decision_strategies != tuple(self.base.model_host.bindings)):
                raise TaskConflict('Formal QS payment source, registry or publication wiring changed')
        elif self.payment_provider is not self.change_provider:
            raise TaskConflict('Unconfigured QS payment publication replaced its original source provider')
        if any(actual is not original for actual, original in zip(
                (self.final_account_provider, self.final_account_validator, self.final_account_publications, self.final_account_assembler, self.base.methods),
                self._final_account_components)):
            raise TaskConflict('Formal QS final-account publication components changed')
        if self.final_account_validator is not None:
            self.final_account_validator._check()
            if (self.final_account_validator.provider is not self.base.provider
                    or self.final_account_validator.registry is not self.base.registry
                    or self.final_account_validator.organizations is not self.base.organizations
                    or self.final_account_publications.store is not self.base.store
                    or self.final_account_publications.registry is not self.base.registry
                    or self.final_account_publications.organizations is not self.base.organizations
                    or self.final_account_publications.methods is not self.base.methods
                    or self.final_account_publications.validate_source != self.final_account_validator.validate_source
                    or self.final_account_provider.provider is not self.payment_provider
                    or self.final_account_provider.publications is not self.final_account_publications
                    or self.final_account_assembler.provider is not self.base.provider
                    or self.final_account_assembler.registry is not self.base.registry
                    or self.final_account_assembler.organizations is not self.base.organizations
                    or self.final_account_assembler.methods is not self.base.methods
                    or self.final_account_assembler._views.provider is not self.base.provider
                    or self.final_account_assembler._views.organizations is not self.base.organizations
                    or self.final_account_assembler._views.macro_version != self.settings.final_account_calculations.macro_version
                    or self.final_account_assembler._views.source_mode != 'formal'
                    or self.final_account_assembler.macro_version != self.settings.final_account_calculations.macro_version
                    or self.final_account_assembler.policy_version != self.settings.final_account_calculations.policy_version
                    or self.final_account_assembler.source_mode != 'formal'
                    or self.final_account_assembler.model_version != self.settings.model_version
                    or self.final_account_assembler.decision_strategies != tuple(self.base.model_host.bindings)):
                raise TaskConflict('Formal QS final-account source, registry or publication wiring changed')
        elif self.final_account_provider is not self.payment_provider:
            raise TaskConflict('Unconfigured QS final-account publication replaced its original source provider')
        if any(actual is not original for actual, original in zip(
                (self.procurement_provider, self.procurement_worker, self.procurement_validator, self.procurement_publications),
                self._procurement_components)):
            raise TaskConflict('Formal QS procurement document components changed')
        if self.procurement_validator is not None:
            self.procurement_validator._check()
            worker, validator, publications = self.procurement_worker, self.procurement_validator, self.procurement_publications
            if (worker.store is not self.base.store or worker.registry is not self.base.registry
                    or worker.snapshots.store is not self.base.store
                    or worker.client_version != self.settings.client_version or worker.model_version != self.settings.model_version
                    or worker.validate_invocation != self.base.validators.invocation
                    or worker.validate_wait != self.base.validators.wait or worker.validate_recovery != self.base.validators.recovery
                    or validator.worker is not worker or validator.provider is not self.base.provider
                    or validator.organizations is not self.base.organizations
                    or validator._views.macro_version != self.settings.procurement_documents.macro_version
                    or validator._views.source_mode != 'formal'
                    or publications.worker is not worker or publications.store is not self.base.store
                    or publications.registry is not self.base.registry or publications.organizations is not self.base.organizations
                    or publications.validate_source != validator.validate_source
                    or self.procurement_provider.provider is not self.final_account_provider
                    or self.procurement_provider.publications is not publications
                    or self.submissions is not None and 'QS-A05' in self.submissions.workers
                        and self.submissions.workers['QS-A05'] is not worker):
                raise TaskConflict('Formal QS procurement document source, worker or publication wiring changed')
        elif self.procurement_provider is not self.final_account_provider:
            raise TaskConflict('Unconfigured QS procurement publication replaced its original source provider')
        if any(actual is not original for actual, original in zip(
                (self.bid_provider, self.bid_validator, self.bid_publications, self.bid_assembler, self.base.methods),
                self._bid_components)):
            raise TaskConflict('Formal QS bid normalization components changed')
        if self.bid_validator is not None:
            self.bid_validator._check()
            validator, publications, assembler = self.bid_validator, self.bid_publications, self.bid_assembler
            settings = self.settings.bid_normalization
            if (validator.provider is not self.base.provider or validator.registry is not self.base.registry
                    or validator.organizations is not self.base.organizations
                    or validator._views.macro_version != settings.macro_version or validator._views.source_mode != 'formal'
                    or publications.store is not self.base.store or publications.registry is not self.base.registry
                    or publications.organizations is not self.base.organizations or publications.methods is not self.base.methods
                    or publications.validate_source != validator.validate_source
                    or self.bid_provider.provider is not self.procurement_provider or self.bid_provider.publications is not publications
                    or assembler.provider is not self.base.provider or assembler.registry is not self.base.registry
                    or assembler.organizations is not self.base.organizations or assembler.methods is not self.base.methods
                    or assembler._views.provider is not self.base.provider
                    or assembler._views.organizations is not self.base.organizations
                    or assembler._views.macro_version != settings.macro_version or assembler._views.source_mode != 'formal'
                    or assembler.macro_version != settings.macro_version or assembler.source_mode != 'formal'
                    or assembler.policy_version != settings.policy_version or assembler.model_version != self.settings.model_version
                    or assembler.decision_strategies != tuple(self.base.model_host.bindings)):
                raise TaskConflict('Formal QS bid normalization source, registry or publication wiring changed')
        elif self.bid_provider is not self.procurement_provider:
            raise TaskConflict('Unconfigured QS bid normalization replaced its original source provider')
        if any(actual is not original for actual, original in zip(
                (self.ranking_provider, self.ranking_validator, self.ranking_publications, self.ranking_assembler, self.base.methods),
                self._ranking_components)):
            raise TaskConflict('Formal QS bid ranking components changed')
        if self.ranking_validator is not None:
            self.ranking_validator._check()
            validator, publications, assembler = self.ranking_validator, self.ranking_publications, self.ranking_assembler
            settings = self.settings.bid_ranking
            if (validator.provider is not self.base.provider or validator.registry is not self.base.registry
                    or validator.organizations is not self.base.organizations or validator.normalizations is not self.bid_publications
                    or validator._views.macro_version != settings.macro_version or validator._views.source_mode != 'formal'
                    or publications.store is not self.base.store or publications.registry is not self.base.registry
                    or publications.organizations is not self.base.organizations or publications.methods is not self.base.methods
                    or publications.normalizations is not self.bid_publications or publications.validate_source != validator.validate_source
                    or self.ranking_provider.provider is not self.bid_provider or self.ranking_provider.publications is not publications
                    or assembler.provider is not self.bid_provider or assembler.registry is not self.base.registry
                    or assembler.organizations is not self.base.organizations or assembler.methods is not self.base.methods
                    or assembler._views.provider is not self.bid_provider or assembler._views.organizations is not self.base.organizations
                    or assembler._views.macro_version != settings.macro_version or assembler._views.source_mode != 'formal'
                    or assembler.macro_version != settings.macro_version or assembler.source_mode != 'formal'
                    or assembler.policy_version != settings.policy_version or assembler.model_version != self.settings.model_version
                    or assembler.decision_strategies != tuple(self.base.model_host.bindings)):
                raise TaskConflict('Formal QS bid ranking source, normalization or publication wiring changed')
        elif self.ranking_provider is not self.bid_provider:
            raise TaskConflict('Unconfigured QS bid ranking replaced its original source provider')
        if any(actual is not original for actual, original in zip(
                (self.billing_provider, self.billing_validator, self.billing_publications, self.billing_assembler),
                self._billing_components)):
            raise TaskConflict('Formal QS fee calculation components changed')
        if self.billing_validator is not None:
            self.billing_validator._check()
            validator, publications, assembler = self.billing_validator, self.billing_publications, self.billing_assembler
            settings = self.settings.billing_calculations
            if (validator.provider is not self.base.provider or validator.registry is not self.base.registry
                    or validator.organizations is not self.base.organizations
                    or validator._views.macro_version != settings.macro_version or validator._views.source_mode != 'formal'
                    or publications.store is not self.base.store or publications.registry is not self.base.registry
                    or publications.organizations is not self.base.organizations
                    or publications.validate_source != validator.validate_source
                    or self.billing_provider.provider is not self.ranking_provider or self.billing_provider.publications is not publications
                    or assembler.provider is not self.base.provider or assembler.registry is not self.base.registry
                    or assembler.organizations is not self.base.organizations or assembler.methods is not self.base.methods
                    or assembler._views.provider is not self.base.provider or assembler._views.organizations is not self.base.organizations
                    or assembler._views.macro_version != settings.macro_version or assembler._views.source_mode != 'formal'
                    or assembler.macro_version != settings.macro_version or assembler.source_mode != 'formal'
                    or assembler.policy_version != settings.policy_version or assembler.model_version != self.settings.model_version
                    or assembler.decision_strategies != tuple(self.base.model_host.bindings)):
                raise TaskConflict('Formal QS fee calculation source, registry or publication wiring changed')
        elif self.billing_provider is not self.ranking_provider:
            raise TaskConflict('Unconfigured QS fee calculation replaced its original source provider')
        if any(actual is not original for actual, original in zip(
                (self.comparability_provider, self.comparability_validator, self.comparability_publications,
                    self.comparability_assembler, self.base.methods), self._comparability_components)):
            raise TaskConflict('Formal QS forecast comparison components changed')
        if self.comparability_validator is not None:
            self.comparability_validator._check()
            validator, publications, assembler = self.comparability_validator, self.comparability_publications, self.comparability_assembler
            settings = self.settings.learning_comparability
            if (validator.provider is not self.base.provider or validator.registry is not self.base.registry
                    or validator.organizations is not self.base.organizations
                    or validator._views.macro_version != settings.macro_version or validator._views.source_mode != 'formal'
                    or publications.store is not self.base.store or publications.registry is not self.base.registry
                    or publications.organizations is not self.base.organizations or publications.methods is not self.base.methods
                    or publications.validate_source != validator.validate_source
                    or self.comparability_provider.provider is not self.billing_provider or self.comparability_provider.publications is not publications
                    or assembler.provider is not self.base.provider or assembler.registry is not self.base.registry
                    or assembler.organizations is not self.base.organizations or assembler.methods is not self.base.methods
                    or assembler._views.provider is not self.base.provider or assembler._views.organizations is not self.base.organizations
                    or assembler._views.macro_version != settings.macro_version or assembler._views.source_mode != 'formal'
                    or assembler.macro_version != settings.macro_version or assembler.source_mode != 'formal'
                    or assembler.policy_version != settings.policy_version or assembler.model_version != self.settings.model_version
                    or assembler.decision_strategies != tuple(self.base.model_host.bindings)):
                raise TaskConflict('Formal QS forecast comparison source, registry or publication wiring changed')
        elif self.comparability_provider is not self.billing_provider:
            raise TaskConflict('Unconfigured QS forecast comparison replaced its original source provider')
        if any(actual is not original for actual, original in zip(
                (self.error_provider, self.error_validator, self.error_publications, self.error_assembler, self.base.methods),
                self._error_components)):
            raise TaskConflict('Formal QS forecast error components changed')
        if self.error_validator is not None:
            self.error_validator._check()
            validator, publications, assembler = self.error_validator, self.error_publications, self.error_assembler
            settings = self.settings.learning_error
            if (validator.provider is not self.base.provider or validator.registry is not self.base.registry
                    or validator.organizations is not self.base.organizations or validator.comparisons is not self.comparability_publications
                    or validator._views.macro_version != settings.macro_version or validator._views.source_mode != 'formal'
                    or publications.store is not self.base.store or publications.registry is not self.base.registry
                    or publications.organizations is not self.base.organizations or publications.methods is not self.base.methods
                    or publications.comparisons is not self.comparability_publications
                    or publications.validate_source != validator.validate_source
                    or self.error_provider.provider is not self.comparability_provider or self.error_provider.publications is not publications
                    or assembler.provider is not self.comparability_provider or assembler.registry is not self.base.registry
                    or assembler.organizations is not self.base.organizations or assembler.methods is not self.base.methods
                    or assembler._views.provider is not self.comparability_provider or assembler._views.organizations is not self.base.organizations
                    or assembler._views.macro_version != settings.macro_version or assembler._views.source_mode != 'formal'
                    or assembler.macro_version != settings.macro_version or assembler.source_mode != 'formal'
                    or assembler.policy_version != settings.policy_version or assembler.model_version != self.settings.model_version
                    or assembler.decision_strategies != tuple(self.base.model_host.bindings)):
                raise TaskConflict('Formal QS forecast error source, original comparison or publication wiring changed')
        elif self.error_provider is not self.comparability_provider:
            raise TaskConflict('Unconfigured QS forecast error replaced its original source provider')
        if any(actual is not original for actual, original in zip(
                (self.assessment_provider, self.assessment_validator, self.assessment_publications, self.assessment_assembler,
                    self.base.methods), self._assessment_components)):
            raise TaskConflict('Formal QS learning assessment components changed')
        if self.assessment_validator is not None:
            self.assessment_validator._check()
            validator, publications, assembler = self.assessment_validator, self.assessment_publications, self.assessment_assembler
            settings = self.settings.learning_assessment
            if (validator.provider is not self.base.provider or validator.registry is not self.base.registry
                    or validator.organizations is not self.base.organizations or validator.errors is not self.error_publications
                    or validator._views.macro_version != settings.macro_version or validator._views.source_mode != 'formal'
                    or publications.store is not self.base.store or publications.registry is not self.base.registry
                    or publications.organizations is not self.base.organizations or publications.methods is not self.base.methods
                    or publications.errors is not self.error_publications or publications.validate_source != validator.validate_source
                    or self.assessment_provider.provider is not self.error_provider or self.assessment_provider.publications is not publications
                    or assembler.provider is not self.error_provider or assembler.registry is not self.base.registry
                    or assembler.organizations is not self.base.organizations or assembler.methods is not self.base.methods
                    or assembler._views.provider is not self.error_provider or assembler._views.organizations is not self.base.organizations
                    or assembler._views.macro_version != settings.macro_version or assembler._views.source_mode != 'formal'
                    or assembler.macro_version != settings.macro_version or assembler.source_mode != 'formal'
                    or assembler.policy_version != settings.policy_version or assembler.model_version != self.settings.model_version
                    or assembler.decision_strategies != tuple(self.base.model_host.bindings)):
                raise TaskConflict('Formal QS learning assessment source, original cost dependencies or publication wiring changed')
        elif self.assessment_provider is not self.error_provider:
            raise TaskConflict('Unconfigured QS learning assessment replaced its original source provider')
        if any(actual is not original for actual, original in zip(
                (self.training_provider, self.training_validator, self.training_publications, self.training_assembler,
                    self.base.methods), self._training_components)):
            raise TaskConflict('Formal QS training estimate components changed')
        if self.training_validator is not None:
            self.training_validator._check()
            validator, publications, assembler = self.training_validator, self.training_publications, self.training_assembler
            settings = self.settings.training_estimates
            if (validator.provider is not self.base.provider or validator.registry is not self.base.registry
                    or validator.organizations is not self.base.organizations
                    or validator._views.macro_version != settings.macro_version or validator._views.source_mode != 'formal'
                    or publications.store is not self.base.store or publications.registry is not self.base.registry
                    or publications.organizations is not self.base.organizations or publications.methods is not self.base.methods
                    or publications.validate_source != validator.validate_source
                    or self.training_provider.provider is not self.assessment_provider or self.training_provider.publications is not publications
                    or assembler.provider is not self.base.provider or assembler.registry is not self.base.registry
                    or assembler.organizations is not self.base.organizations or assembler.methods is not self.base.methods
                    or assembler._views.provider is not self.base.provider or assembler._views.organizations is not self.base.organizations
                    or assembler._views.macro_version != settings.macro_version or assembler._views.source_mode != 'formal'
                    or assembler.macro_version != settings.macro_version or assembler.source_mode != 'formal'
                    or assembler.policy_version != settings.policy_version or assembler.model_version != self.settings.model_version
                    or assembler.decision_strategies != tuple(self.base.model_host.bindings)):
                raise TaskConflict('Formal QS training estimate source, registry or publication wiring changed')
        elif self.training_provider is not self.assessment_provider:
            raise TaskConflict('Unconfigured QS training estimate replaced its original source provider')
        if any(actual is not original for actual, original in zip(
                (self.research_normalization_provider, self.research_normalization_validator, self.research_normalization_publications, self.research_normalization_assembler,
                    self.base.methods, self.dependencies.validate_research_normalization_basis), self._research_normalization_components)):
            raise TaskConflict('Formal QS research normalization components changed')
        if self.research_normalization_validator is not None:
            if any(actual is not original for actual, original in zip((
                    self.research_normalization_validator._views, self.research_normalization_validator._views.schemas,
                    self.research_normalization_assembler._views, self.research_normalization_assembler._views.schemas,
                    self.research_normalization_publications.schemas), self._research_normalization_source_components)):
                raise TaskConflict('Formal QS research normalization retained source views or schemas changed')
            self.research_normalization_validator._check()
            validator, publications, assembler = self.research_normalization_validator, self.research_normalization_publications, self.research_normalization_assembler
            settings = self.settings.research_normalizations
            if (settings is None or validator.validate_normalization_basis is not self.dependencies.validate_research_normalization_basis
                    or validator.ACTION_ID != 'QS-A13' or validator.ROLE != 'QS'
                    or assembler.ACTION_ID != 'QS-A13' or publications.ACTION_ID != 'QS-A13'
                    or publications.ROLE != 'QS' or publications.METHOD_REF != RESEARCH_NORMALIZE_METHOD
                    or validator.provider is not self.base.provider or validator.registry is not self.base.registry
                    or validator.organizations is not self.base.organizations
                    or validator._views.macro_version != settings.macro_version or validator._views.source_mode != 'formal'
                    or publications.store is not self.base.store or publications.registry is not self.base.registry
                    or publications.organizations is not self.base.organizations or publications.methods is not self.base.methods
                    or publications.validate_source != validator.validate_source
                    or self.research_normalization_provider.provider is not self.training_provider or self.research_normalization_provider.publications is not publications
                    or assembler.provider is not self.base.provider or assembler.registry is not self.base.registry
                    or assembler.organizations is not self.base.organizations or assembler.methods is not self.base.methods
                    or assembler._views.provider is not self.base.provider or assembler._views.organizations is not self.base.organizations
                    or assembler._views.macro_version != settings.macro_version or assembler._views.source_mode != 'formal'
                    or assembler.macro_version != settings.macro_version or assembler.source_mode != 'formal'
                    or assembler.policy_version != settings.policy_version or assembler.model_version != self.settings.model_version
                    or assembler.decision_strategies != tuple(self.base.model_host.bindings)):
                raise TaskConflict('Formal QS research normalization source, registry or publication wiring changed')
        elif self.research_normalization_provider is not self.training_provider:
            raise TaskConflict('Unconfigured QS research normalization replaced its original source provider')
        if any(actual is not original for actual, original in zip(
                (self.provider, self.research_ranking_validator, self.research_ranking_publications, self.research_ranking_assembler,
                    self.base.methods, self.dependencies.validate_research_ranking_basis), self._research_ranking_components)):
            raise TaskConflict('Formal QS research ranking components changed')
        if self.research_ranking_validator is not None:
            if any(actual is not original for actual, original in zip((
                    self.research_ranking_validator._views, self.research_ranking_validator._views.schemas,
                    self.research_ranking_assembler._views, self.research_ranking_assembler._views.schemas,
                    self.research_ranking_publications.schemas), self._research_ranking_source_components)):
                raise TaskConflict('Formal QS research ranking retained source views or schemas changed')
            self.research_ranking_validator._check()
            validator, publications, assembler = self.research_ranking_validator, self.research_ranking_publications, self.research_ranking_assembler
            settings = self.settings.research_rankings
            if (settings is None or validator.validate_ranking_basis is not self.dependencies.validate_research_ranking_basis
                    or validator.ACTION_ID != 'QS-A13' or validator.ROLE != 'QS'
                    or assembler.ACTION_ID != 'QS-A13' or publications.ACTION_ID != 'QS-A13'
                    or validator.normalizations is not self.research_normalization_publications
                    or publications.normalizations is not self.research_normalization_publications
                    or settings.macro_version != self.settings.research_normalizations.macro_version
                    or publications.ROLE != 'QS' or publications.METHOD_REF != RESEARCH_RANK_METHOD
                    or validator.provider is not self.base.provider or validator.registry is not self.base.registry
                    or validator.organizations is not self.base.organizations
                    or validator._views.macro_version != settings.macro_version or validator._views.source_mode != 'formal'
                    or publications.store is not self.base.store or publications.registry is not self.base.registry
                    or publications.organizations is not self.base.organizations or publications.methods is not self.base.methods
                    or publications.validate_source != validator.validate_source
                    or self.provider.provider is not self.research_normalization_provider or self.provider.publications is not publications
                    or assembler.provider is not self.research_normalization_provider or assembler.registry is not self.base.registry
                    or assembler.organizations is not self.base.organizations or assembler.methods is not self.base.methods
                    or assembler._views.provider is not self.research_normalization_provider or assembler._views.organizations is not self.base.organizations
                    or assembler._views.macro_version != settings.macro_version or assembler._views.source_mode != 'formal'
                    or assembler.macro_version != settings.macro_version or assembler.source_mode != 'formal'
                    or assembler.policy_version != settings.policy_version or assembler.model_version != self.settings.model_version
                    or assembler.decision_strategies != tuple(self.base.model_host.bindings)):
                raise TaskConflict('Formal QS research ranking source, registry or publication wiring changed')
        elif self.provider is not self.research_normalization_provider:
            raise TaskConflict('Unconfigured QS research ranking replaced its original source provider')
        with self.base.store._lock:
            saved = self.base.store._db.execute('SELECT value FROM metadata WHERE key=?', (self._key,)).fetchone()
            if saved is None or json.loads(saved[0]) != self._declared:
                raise TaskConflict('Formal QS application configuration evidence changed')

    def evidence(self):
        self._check()
        actual = self.base.evidence()
        if not isinstance(actual, dict):
            raise ValueError('Formal QS source evidence must be an explicit object')
        return {'schema_version': self.VERSION, 'configuration_sha256': task_digest(self._declared),
            'source_mode': 'formal', 'status': 'configured_unverified', 'sources': deepcopy(actual),
            'submission': self.submissions.capabilities() if self.submissions is not None else None,
            'feedback_configured': self.feedback is not None,
            'execution_recovery_configured': self.execution_dispatcher is not None,
            'cost_calculations_configured': self.cost_validator is not None,
            'change_calculations_configured': self.change_validator is not None,
            'payment_calculations_configured': self.payment_validator is not None,
            'final_account_calculations_configured': self.final_account_validator is not None,
            'procurement_documents_configured': self.procurement_validator is not None,
            'bid_normalization_configured': self.bid_validator is not None,
            'bid_ranking_configured': self.ranking_validator is not None,
            'billing_calculations_configured': self.billing_validator is not None,
            'learning_comparability_configured': self.comparability_validator is not None,
            'learning_error_configured': self.error_validator is not None,
            'learning_assessment_configured': self.assessment_validator is not None,
            'training_estimates_configured': self.training_validator is not None,
            'research_normalizations_configured': self.research_normalization_validator is not None,
            'research_rankings_configured': self.research_ranking_validator is not None,
            'feedback_input_enabled': self.settings.feedback is not None and self.settings.feedback.input_enabled}

    def sources(self):
        self._check()
        enabled = self.settings.feedback is not None and self.settings.feedback.input_enabled
        return QSRoleContractSources(version=self.VERSION, registry=self.base.registry,
            organizations=self.base.organizations, store=self.base.store, provider=self.provider,
            read_guard=self.base.read_guard, validators=self.base.validators, evidence=self.evidence,
            close=self.close, methods=self.base.methods, model_host=self.base.model_host,
            feedback=self.feedback if enabled else None,
            validate_feedback_input=self.dependencies.validate_feedback_input if enabled else None,
            publish_cost_calculation=self.publish_cost_calculation if self.cost_validator is not None else None,
            publish_saved_cost_calculation=self.publish_saved_cost_calculation if self.cost_validator is not None else None,
            publish_change_calculation=self.publish_change_calculation if self.change_validator is not None else None,
            publish_saved_change_calculation=self.publish_saved_change_calculation if self.change_validator is not None else None,
            publish_payment_calculations=self.publish_payment_calculations if self.payment_validator is not None else None,
            publish_saved_payment_calculations=self.publish_saved_payment_calculations if self.payment_validator is not None else None,
            publish_final_account_reconciliation=self.publish_final_account_reconciliation if self.final_account_validator is not None else None,
            publish_saved_final_account_reconciliation=self.publish_saved_final_account_reconciliation if self.final_account_validator is not None else None,
            save_procurement_document=self.save_procurement_document if self.procurement_validator is not None else None,
            publish_saved_procurement_document=self.publish_saved_procurement_document if self.procurement_validator is not None else None,
            save_bid_normalization=self.save_bid_normalization if self.bid_validator is not None else None,
            publish_saved_bid_normalization=self.publish_saved_bid_normalization if self.bid_validator is not None else None,
            save_bid_ranking=self.save_bid_ranking if self.ranking_validator is not None else None,
            publish_saved_bid_ranking=self.publish_saved_bid_ranking if self.ranking_validator is not None else None,
            save_billing_calculation=self.save_billing_calculation if self.billing_validator is not None else None,
            publish_saved_billing_calculation=self.publish_saved_billing_calculation if self.billing_validator is not None else None,
            save_learning_comparability=self.save_learning_comparability if self.comparability_validator is not None else None,
            publish_saved_learning_comparability=self.publish_saved_learning_comparability if self.comparability_validator is not None else None,
            save_learning_error=self.save_learning_error if self.error_validator is not None else None,
            publish_saved_learning_error=self.publish_saved_learning_error if self.error_validator is not None else None,
            save_learning_assessment=self.save_learning_assessment if self.assessment_validator is not None else None,
            publish_saved_learning_assessment=self.publish_saved_learning_assessment if self.assessment_validator is not None else None,
            save_training_estimate=self.save_training_estimate if self.training_validator is not None else None,
            publish_saved_training_estimate=self.publish_saved_training_estimate if self.training_validator is not None else None,
            save_research_normalization_calculation=self.save_research_normalization_calculation if self.research_normalization_validator is not None else None,
            publish_saved_research_normalization_calculation=self.publish_saved_research_normalization_calculation if self.research_normalization_validator is not None else None,
            save_research_ranking_calculation=self.save_research_ranking_calculation if self.research_ranking_validator is not None else None,
            publish_saved_research_ranking_calculation=self.publish_saved_research_ranking_calculation if self.research_ranking_validator is not None else None)

    def save_research_ranking_calculation(self, context, *, calculation_ref, author_authority_ref, **source_refs):
        """Save one original A13 ranking under independent actual source validation."""
        self._check()
        if self.research_ranking_assembler is None:
            raise ValueError('No QS research ranking persistence is configured')
        context = ActionContext.model_validate(context).model_copy(deep=True)
        result = self.research_ranking_assembler.save_ranking_calculation(context,
            publications=self.research_ranking_publications, read_guard=self.base.read_guard,
            calculation_ref=calculation_ref, author_authority_ref=author_authority_ref,
            validate_current=self.research_ranking_validator.validate_current,
            validate_normalization_provenance=self.research_ranking_validator.validate_normalization_provenance, **source_refs)
        self._check()
        return result

    def publish_saved_research_ranking_calculation(self, record_sha256, *, source_context, next_context):
        """Publish retained ranking at a fresh authorized read token."""
        self._check()
        if self.research_ranking_publications is None:
            raise ValueError('No QS research ranking publication is configured')
        source = ActionContext.model_validate(source_context).model_copy(deep=True)
        next_context = ActionContext.model_validate(next_context).model_copy(deep=True)
        with self.base.read_guard(source.model_copy(deep=True)):
            self._check()
            result = self.research_ranking_publications.publish(record_sha256,
                source_context=source, next_context=next_context)
            self._check()
            return result

    def save_research_normalization_calculation(self, context, *, calculation_ref, author_authority_ref, **source_refs):
        """Save one original A13 normalization under independent actual source validation."""
        self._check()
        if self.research_normalization_assembler is None:
            raise ValueError('No QS research normalization persistence is configured')
        context = ActionContext.model_validate(context).model_copy(deep=True)
        result = self.research_normalization_assembler.save_normalization_calculation(context,
            publications=self.research_normalization_publications, read_guard=self.base.read_guard,
            calculation_ref=calculation_ref, author_authority_ref=author_authority_ref,
            validate_current=self.research_normalization_validator.validate_current, **source_refs)
        self._check()
        return result

    def publish_saved_research_normalization_calculation(self, record_sha256, *, source_context, next_context):
        """Publish retained normalization at a fresh authorized read token."""
        self._check()
        if self.research_normalization_publications is None:
            raise ValueError('No QS research normalization publication is configured')
        source = ActionContext.model_validate(source_context).model_copy(deep=True)
        next_context = ActionContext.model_validate(next_context).model_copy(deep=True)
        with self.base.read_guard(source.model_copy(deep=True)):
            self._check()
            result = self.research_normalization_publications.publish(record_sha256,
                source_context=source, next_context=next_context)
            self._check()
            return result

    def save_training_estimate(self, context, *, estimate_ref, author_authority_ref, **source_refs):
        """Save original sourced training work estimate without approving investment."""
        self._check()
        if self.training_assembler is None:
            raise ValueError('No QS training estimate persistence is configured')
        context = ActionContext.model_validate(context).model_copy(deep=True)
        result = self.training_assembler.save_training_estimate(context, publications=self.training_publications,
            read_guard=self.base.read_guard, estimate_ref=estimate_ref, author_authority_ref=author_authority_ref,
            validate_current=self.training_validator.validate_current, **source_refs)
        self._check()
        return result

    def publish_saved_training_estimate(self, record_sha256, *, source_context, next_context):
        """Publish the retained work estimate under a fresh authorized token."""
        self._check()
        if self.training_publications is None:
            raise ValueError('No QS training estimate publication is configured')
        source = ActionContext.model_validate(source_context).model_copy(deep=True)
        next_context = ActionContext.model_validate(next_context).model_copy(deep=True)
        with self.base.read_guard(source.model_copy(deep=True)):
            self._check()
            result = self.training_publications.publish(record_sha256, source_context=source, next_context=next_context)
            self._check()
            return result

    def save_learning_assessment(self, context, *, assessment_ref, author_authority_ref, **source_refs):
        """Save finite feedback-rule output using independently retained cost reports."""
        self._check()
        if self.assessment_assembler is None:
            raise ValueError('No QS learning assessment persistence is configured')
        context = ActionContext.model_validate(context).model_copy(deep=True)
        result = self.assessment_assembler.save_assessment(context, publications=self.assessment_publications,
            read_guard=self.base.read_guard, assessment_ref=assessment_ref, author_authority_ref=author_authority_ref,
            validate_current=self.assessment_validator.validate_current, **source_refs)
        self._check()
        return result

    def publish_saved_learning_assessment(self, record_sha256, *, source_context, next_context):
        """Publish saved assessment and cost dependencies under a fresh read token."""
        self._check()
        if self.assessment_publications is None:
            raise ValueError('No QS learning assessment publication is configured')
        source = ActionContext.model_validate(source_context).model_copy(deep=True)
        next_context = ActionContext.model_validate(next_context).model_copy(deep=True)
        with self.base.read_guard(source.model_copy(deep=True)):
            self._check()
            result = self.assessment_publications.publish(record_sha256, source_context=source, next_context=next_context)
            self._check()
            return result

    def save_learning_error(self, context, *, calculation_ref, author_authority_ref, **source_refs):
        """Save error once using the already published original comparable report."""
        self._check()
        if self.error_assembler is None:
            raise ValueError('No QS forecast error persistence is configured')
        context = ActionContext.model_validate(context).model_copy(deep=True)
        result = self.error_assembler.save_error(context, publications=self.error_publications,
            read_guard=self.base.read_guard, calculation_ref=calculation_ref, author_authority_ref=author_authority_ref,
            validate_current=self.error_validator.validate_current, **source_refs)
        self._check()
        return result

    def publish_saved_learning_error(self, record_sha256, *, source_context, next_context):
        """Publish the saved error and original comparison dependency without replay."""
        self._check()
        if self.error_publications is None:
            raise ValueError('No QS forecast error publication is configured')
        source = ActionContext.model_validate(source_context).model_copy(deep=True)
        next_context = ActionContext.model_validate(next_context).model_copy(deep=True)
        with self.base.read_guard(source.model_copy(deep=True)):
            self._check()
            result = self.error_publications.publish(record_sha256, source_context=source, next_context=next_context)
            self._check()
            return result

    def save_learning_comparability(self, context, *, calculation_ref, author_authority_ref, **source_refs):
        """Save one comparison of the original immutable forecast and received outcome."""
        self._check()
        if self.comparability_assembler is None:
            raise ValueError('No QS forecast comparison persistence is configured')
        context = ActionContext.model_validate(context).model_copy(deep=True)
        result = self.comparability_assembler.save_comparability(context, publications=self.comparability_publications,
            read_guard=self.base.read_guard, calculation_ref=calculation_ref, author_authority_ref=author_authority_ref,
            validate_current=self.comparability_validator.validate_current, **source_refs)
        self._check()
        return result

    def publish_saved_learning_comparability(self, record_sha256, *, source_context, next_context):
        """Publish the retained comparison under a fresh token without rerunning its method."""
        self._check()
        if self.comparability_publications is None:
            raise ValueError('No QS forecast comparison publication is configured')
        source = ActionContext.model_validate(source_context).model_copy(deep=True)
        next_context = ActionContext.model_validate(next_context).model_copy(deep=True)
        with self.base.read_guard(source.model_copy(deep=True)):
            self._check()
            result = self.comparability_publications.publish(record_sha256, source_context=source, next_context=next_context)
            self._check()
            return result

    def save_billing_calculation(self, context, *, calculation_ref, author_authority_ref, **source_refs):
        """Save the declared fee formula output before explicit publication."""
        self._check()
        if self.billing_assembler is None:
            raise ValueError('No QS fee calculation persistence is configured')
        context = ActionContext.model_validate(context).model_copy(deep=True)
        result = self.billing_assembler.save_calculation(context, publications=self.billing_publications,
            read_guard=self.base.read_guard, calculation_ref=calculation_ref, author_authority_ref=author_authority_ref,
            validate_current=self.billing_validator.validate_current, **source_refs)
        self._check()
        return result

    def publish_saved_billing_calculation(self, record_sha256, *, source_context, next_context):
        """Publish a saved fee calculation under a fresh token without producing it again."""
        self._check()
        if self.billing_publications is None:
            raise ValueError('No QS fee calculation publication is configured')
        source = ActionContext.model_validate(source_context).model_copy(deep=True)
        next_context = ActionContext.model_validate(next_context).model_copy(deep=True)
        with self.base.read_guard(source.model_copy(deep=True)):
            self._check()
            result = self.billing_publications.publish(record_sha256, source_context=source, next_context=next_context)
            self._check()
            return result

    def save_bid_ranking(self, context, *, calculation_ref, author_authority_ref, **source_refs):
        """Save one ranking using the already published original normalization."""
        self._check()
        if self.ranking_assembler is None:
            raise ValueError('No QS bid ranking persistence is configured')
        context = ActionContext.model_validate(context).model_copy(deep=True)
        result = self.ranking_assembler.save_ranking(context, publications=self.ranking_publications,
            read_guard=self.base.read_guard, calculation_ref=calculation_ref, author_authority_ref=author_authority_ref,
            validate_current=self.ranking_validator.validate_current, **source_refs)
        self._check()
        return result

    def publish_saved_bid_ranking(self, record_sha256, *, source_context, next_context):
        """Publish the saved ranking with its normalization dependency, without replay."""
        self._check()
        if self.ranking_publications is None:
            raise ValueError('No QS bid ranking publication is configured')
        source = ActionContext.model_validate(source_context).model_copy(deep=True)
        next_context = ActionContext.model_validate(next_context).model_copy(deep=True)
        with self.base.read_guard(source.model_copy(deep=True)):
            self._check()
            result = self.ranking_publications.publish(record_sha256, source_context=source, next_context=next_context)
            self._check()
            return result

    def save_bid_normalization(self, context, *, calculation_ref, author_authority_ref, **source_refs):
        """Calculate once and return the saved record before fresh-token publication."""
        self._check()
        if self.bid_assembler is None:
            raise ValueError('No QS bid normalization persistence is configured')
        context = ActionContext.model_validate(context).model_copy(deep=True)
        result = self.bid_assembler.save_normalization(context, publications=self.bid_publications,
            read_guard=self.base.read_guard, calculation_ref=calculation_ref, author_authority_ref=author_authority_ref,
            validate_current=self.bid_validator.validate_current, **source_refs)
        self._check()
        return result

    def publish_saved_bid_normalization(self, record_sha256, *, source_context, next_context):
        """Publish an explicitly saved normalization without repeating its calculation."""
        self._check()
        if self.bid_publications is None:
            raise ValueError('No QS bid normalization publication is configured')
        source = ActionContext.model_validate(source_context).model_copy(deep=True)
        next_context = ActionContext.model_validate(next_context).model_copy(deep=True)
        with self.base.read_guard(source.model_copy(deep=True)):
            self._check()
            result = self.bid_publications.publish(record_sha256, source_context=source, next_context=next_context)
            self._check()
            return result

    def save_procurement_document(self, identity, *, context, execution_versions, document_ref, author_authority_ref):
        """Explicitly save a document from an existing compile result; return its durable SHA."""
        self._check()
        if self.procurement_publications is None:
            raise ValueError('No QS procurement document persistence is configured')
        identity = TaskIdentity(**identity.as_dict())
        context = ActionContext.model_validate(context).model_copy(deep=True)
        with self.base.read_guard(context.model_copy(deep=True)):
            self._check()
            _, reading = self.procurement_validator._reading(context)
            prepared = self.procurement_worker.prepare_document(identity, current_context=context,
                reading=reading, execution_versions=deepcopy(execution_versions),
                validate_history=self.procurement_validator.validate_history,
                document_ref=document_ref, author_authority_ref=author_authority_ref)
            record = self.procurement_publications.save(prepared, context=context, reading=reading)
            self._check()
            return record

    def publish_saved_procurement_document(self, record_sha256, *, source_context, next_context):
        """Expose an existing saved document at a fresh token without recompiling it."""
        self._check()
        if self.procurement_publications is None:
            raise ValueError('No QS procurement document publication is configured')
        source = ActionContext.model_validate(source_context).model_copy(deep=True)
        next_context = ActionContext.model_validate(next_context).model_copy(deep=True)
        with self.base.read_guard(source.model_copy(deep=True)):
            self._check()
            result = self.procurement_publications.publish(record_sha256,
                source_context=source, next_context=next_context)
            self._check()
            return result

    def publish_cost_calculation(self, context, *, next_context, calculation_ref, author_authority_ref, **source_refs):
        """Explicit pure calculation/save/publication; never a model or cost-plan submission."""
        self._check()
        if self.cost_assembler is None:
            raise ValueError('No QS cost calculation publication is configured')
        context = ActionContext.model_validate(context).model_copy(deep=True)
        next_context = ActionContext.model_validate(next_context).model_copy(deep=True)
        result = self.cost_assembler.publish_calculation(context, publications=self.cost_publications,
            next_context=next_context, read_guard=self.base.read_guard, calculation_ref=calculation_ref,
            author_authority_ref=author_authority_ref, validate_current=self.cost_validator.validate_current, **source_refs)
        self._check()
        return result

    def publish_saved_cost_calculation(self, record_sha256, *, source_context, next_context):
        """Publish one explicit existing execution after interruption without recomputing."""
        self._check()
        if self.cost_publications is None:
            raise ValueError('No QS cost calculation publication is configured')
        source = ActionContext.model_validate(source_context).model_copy(deep=True)
        with self.base.read_guard(source.model_copy(deep=True)):
            self._check()
            result = self.cost_publications.publish(record_sha256, source_context=source, next_context=next_context)
            self._check()
            return result

    def publish_change_calculation(self, context, *, next_context, calculation_ref, author_authority_ref, **source_refs):
        """Explicit arithmetic/save/publication; no entitlement or determination effect."""
        self._check()
        if self.change_assembler is None:
            raise ValueError('No QS change calculation publication is configured')
        context = ActionContext.model_validate(context).model_copy(deep=True)
        next_context = ActionContext.model_validate(next_context).model_copy(deep=True)
        result = self.change_assembler.publish_calculation(context, publications=self.change_publications,
            next_context=next_context, read_guard=self.base.read_guard, calculation_ref=calculation_ref,
            author_authority_ref=author_authority_ref, validate_current=self.change_validator.validate_current, **source_refs)
        self._check()
        return result

    def publish_saved_change_calculation(self, record_sha256, *, source_context, next_context):
        """Publish an explicit saved execution after interruption without recomputing."""
        self._check()
        if self.change_publications is None:
            raise ValueError('No QS change calculation publication is configured')
        source = ActionContext.model_validate(source_context).model_copy(deep=True)
        with self.base.read_guard(source.model_copy(deep=True)):
            self._check()
            result = self.change_publications.publish(record_sha256, source_context=source, next_context=next_context)
            self._check()
            return result

    def publish_payment_calculations(self, context, *, next_context, author_authority_ref, **source_refs):
        """Explicit one-execution result bundle publication; no certificate or cash effect."""
        self._check()
        if self.payment_assembler is None:
            raise ValueError('No QS payment calculation publication is configured')
        context = ActionContext.model_validate(context).model_copy(deep=True)
        next_context = ActionContext.model_validate(next_context).model_copy(deep=True)
        result = self.payment_assembler.publish_calculations(context, publications=self.payment_publications,
            next_context=next_context, read_guard=self.base.read_guard,
            author_authority_ref=author_authority_ref, validate_current=self.payment_validator.validate_current, **source_refs)
        self._check()
        return result

    def publish_saved_payment_calculations(self, record_sha256, *, source_context, next_context):
        """Publish the entire saved bundle after interruption without recalculation."""
        self._check()
        if self.payment_publications is None:
            raise ValueError('No QS payment calculation publication is configured')
        source = ActionContext.model_validate(source_context).model_copy(deep=True)
        with self.base.read_guard(source.model_copy(deep=True)):
            self._check()
            result = self.payment_publications.publish(record_sha256, source_context=source, next_context=next_context)
            self._check()
            return result

    def publish_final_account_reconciliation(self, context, *, next_context, calculation_ref, author_authority_ref, **source_refs):
        """Explicit reconciliation/save/publication; legal determination stays separate."""
        self._check()
        if self.final_account_assembler is None:
            raise ValueError('No QS final-account calculation publication is configured')
        context = ActionContext.model_validate(context).model_copy(deep=True)
        next_context = ActionContext.model_validate(next_context).model_copy(deep=True)
        result = self.final_account_assembler.publish_reconciliation(context, publications=self.final_account_publications,
            next_context=next_context, read_guard=self.base.read_guard, calculation_ref=calculation_ref,
            author_authority_ref=author_authority_ref, validate_current=self.final_account_validator.validate_current, **source_refs)
        self._check()
        return result

    def publish_saved_final_account_reconciliation(self, record_sha256, *, source_context, next_context):
        """Publish an existing original execution after interruption without recomputing."""
        self._check()
        if self.final_account_publications is None:
            raise ValueError('No QS final-account calculation publication is configured')
        source = ActionContext.model_validate(source_context).model_copy(deep=True)
        with self.base.read_guard(source.model_copy(deep=True)):
            self._check()
            result = self.final_account_publications.publish(record_sha256, source_context=source, next_context=next_context)
            self._check()
            return result

    def _dispatch_submission(self, identity, operation):
        self._check()
        if self.submissions is None:
            raise ValueError('No actual QS submission routes are configured')
        result = getattr(self.submissions, operation)(identity)
        self._check()
        return result

    def submit(self, identity):
        return self._dispatch_submission(identity, 'submit')

    def recover(self, identity):
        return self._dispatch_submission(identity, 'recover')

    def read_receipt(self, identity):
        return self._dispatch_submission(identity, 'read_receipt')

    def resume_execution_waits(self, *, run_id, organization_id):
        """Explicitly resume configured original QS waits for fresh judgment."""
        self._check()
        if self.execution_dispatcher is None:
            raise ValueError('No QS original execution recovery is configured')
        result = self.execution_dispatcher(run_id=run_id, organization_id=organization_id)
        self._check()
        return result

    def wait_recovery_sources(self, *, identity, journal_path):
        """Expose the original configured QS journal and protected callbacks to selected V7 waits."""
        self._check()
        if self.execution_dispatcher is None:
            raise ValueError('No QS original execution recovery is configured')
        result = self.execution_dispatcher.wait_recovery_sources(identity=identity, journal_path=journal_path,
            check_application=self._check, close=self.close)
        self._check()
        return result

    def _reconcile_billing_history(self, identity, *, signal, enabled_field, reconcile):
        """Read and archive original A10 history under the application's actual guard."""
        self._check()
        settings = self.settings.execution_recovery
        if (self.settings.action_id != 'QS-A10' or type(settings) is not QSBillingRecoverySettings
                or not getattr(settings, enabled_field) or self.execution_dispatcher is None):
            raise ValueError('QS fee archival requires its explicit A10 native history configuration')
        recovery = self.dependencies.execution_recovery
        with recovery.read_guard(run_id=identity.run_id, organization_id=identity.organization_id):
            self._check()
            result = reconcile(identity=identity, signal=signal, reader=self.payment_reader,
                dispatcher=self.execution_dispatcher.dispatcher, validate_relation=recovery.validate_relation)
            self._check()
            return result

    def reconcile_billing_claim(self, identity, *, signal):
        """Archive actual original fee status without producing another QS fee."""
        from integration.qs_billing_terminal import reconcile_qs_billing_claim
        return self._reconcile_billing_history(identity, signal=signal,
            enabled_field='terminal_claim_enabled', reconcile=reconcile_qs_billing_claim)

    def reconcile_billing_receipts(self, identity, *, signal):
        """Archive a covered reminder only after actual native receipt recognition."""
        from integration.qs_billing_terminal import reconcile_qs_billing_receipts
        return self._reconcile_billing_history(identity, signal=signal,
            enabled_field='terminal_receipt_enabled', reconcile=reconcile_qs_billing_receipts)

    def reconcile_billing_internal_cost(self, identity, *, signal):
        """Archive independently posted costs while retaining credits, debts and cash."""
        from integration.qs_billing_terminal import reconcile_qs_billing_internal_cost
        return self._reconcile_billing_history(identity, signal=signal,
            enabled_field='terminal_internal_cost_enabled', reconcile=reconcile_qs_billing_internal_cost)

    def reconcile_transition_execution(self, identity, *, signal):
        """Archive actual same-business A11 result under the original QS source guard."""
        from integration.qs_transition_terminal import reconcile_qs_transition_execution
        self._check()
        settings = self.settings.execution_recovery
        if (self.settings.action_id != 'QS-A11' or not isinstance(settings, QSTransitionRecoverySettings)
                or not settings.terminal_execution_enabled or self.execution_dispatcher is None):
            raise ValueError('QS service execution reconciliation requires explicit A11 terminal configuration')
        recovery = self.dependencies.execution_recovery
        with recovery.read_guard(run_id=identity.run_id, organization_id=identity.organization_id):
            self._check()
            result = reconcile_qs_transition_execution(identity=identity, signal=signal,
                reader=self.payment_reader, dispatcher=self.execution_dispatcher.dispatcher,
                validate_relation=recovery.validate_relation)
            self._check()
            return result

    def reconcile_learning_execution(self, identity, *, signal):
        """Archive actual original A12 outcome without repeating learning or training proposals."""
        from integration.qs_learning_terminal import reconcile_qs_learning_execution
        self._check()
        settings = self.settings.execution_recovery
        if (self.settings.action_id != 'QS-A12' or not isinstance(settings, QSLearningRecoverySettings)
                or not settings.terminal_execution_enabled or self.execution_dispatcher is None):
            raise ValueError('QS learning reconciliation requires explicit original A12 terminal configuration')
        recovery = self.dependencies.execution_recovery
        with recovery.read_guard(run_id=identity.run_id, organization_id=identity.organization_id):
            self._check()
            result = reconcile_qs_learning_execution(identity=identity, signal=signal,
                reader=self.payment_reader, dispatcher=self.execution_dispatcher.dispatcher,
                validate_relation=recovery.validate_relation)
            self._check()
            return result

    def reconcile_applied_feedback(self, identity, *, signal):
        """Archive actual original feedback application without applying private learning twice."""
        from integration.qs_learning_terminal import reconcile_qs_applied_feedback
        self._check()
        settings = self.settings.execution_recovery
        if (self.settings.action_id != 'QS-A12' or not isinstance(settings, QSLearningRecoverySettings)
                or not settings.terminal_applied_feedback_enabled or self.execution_dispatcher is None):
            raise ValueError('QS applied-feedback reconciliation requires explicit original A12 terminal configuration')
        recovery = self.dependencies.execution_recovery
        with recovery.read_guard(run_id=identity.run_id, organization_id=identity.organization_id):
            self._check()
            result = reconcile_qs_applied_feedback(identity=identity, signal=signal,
                reader=self.payment_reader, dispatcher=self.execution_dispatcher.dispatcher,
                validate_relation=recovery.validate_relation)
            self._check()
            return result

    def record_feedback(self, identity, *, context, reading, observation):
        """Explicitly correlate actual feedback under current source/authorization guard."""
        self._check()
        if self.feedback is None:
            raise ValueError('No QS actual feedback inbox is configured')
        context = ActionContext.model_validate(context).model_copy(deep=True)
        with self.base.read_guard(context.model_copy(deep=True)):
            self._check()
            result = self.feedback.record(identity, context=context, reading=reading, observation=observation)
            self._check()
            return result

    def read_feedback(self, *, context, reading):
        """Read original persisted feedback under current recipient/scope authority."""
        self._check()
        if self.feedback is None:
            raise ValueError('No QS actual feedback inbox is configured')
        context = ActionContext.model_validate(context).model_copy(deep=True)
        with self.base.read_guard(context.model_copy(deep=True)):
            self._check()
            result = self.feedback.read(context=context, reading=reading)
            self._check()
            return result

    def close(self):
        if not self._closed:
            self._closed = True
            self.base.close()


def build_sources(*, request, output_directory, offline, settings):
    """role_contract source factory; no source, credential or model construction."""
    config = QSFormalApplicationSettings.model_validate(settings).model_copy(deep=True)
    request = RoleContractInvocation.model_validate(request).model_copy(deep=True)
    if (offline is not False or request.context.execution_mode != 'llm'
            or request.context.contract_ref.id != config.action_id or config.action_id not in _ACTIONS):
        raise ValueError('Formal QS source factory requires its explicit non-offline original invocation')
    factory = _load_factory(config.dependency_factory)
    descriptor = module_factory_descriptor(factory, config.dependency_factory)
    dependencies = factory(request=request.model_copy(deep=True), output_directory=Path(output_directory),
        offline=False, settings=deepcopy(config.dependency_settings))
    if not isinstance(dependencies, QSFormalApplicationDependencies):
        raise ValueError('Actual QS dependency factory must return QSFormalApplicationDependencies')
    application = None
    try:
        if module_factory_descriptor(factory, config.dependency_factory) != descriptor:
            raise TaskConflict('Actual QS dependency factory changed during assembly')
        application = QSFormalApplication(request=request, settings=config,
            dependencies=dependencies, factory_descriptor=descriptor)
        return application.sources()
    except Exception:
        if application is not None:
            application.close()
        else:
            dependencies.sources.close()
        raise
