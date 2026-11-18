"""Configured formal Engineer application assembly over original actual dependencies."""
from copy import deepcopy
from dataclasses import dataclass, field, replace
import importlib
import json
from pathlib import Path
from typing import Callable
from pydantic import model_validator

from integration.module_host import module_factory_descriptor
from integration.observations import ObservationInbox
from integration.engineer_role_contract_host import EngineerRoleContractSources, _ACTIONS, _descriptors, _load_factory
from integration.engineer_submission import EngineerSubmissionCallbacks
from integration.engineer_submission_feedback import EngineerSubmissionFeedback
from integration.engineer_deliverable_actions import EngineerDeliverableActionAssembler
from integration.engineer_submission_receipt_reader import (
    EngineerSubmissionReceiptReader, EngineerSubmissionRecoveryBindings, EngineerSubmissionRecoverySettings,
    build_assembled_engineer_submission_receipt_dispatcher,
)
from integration.engineer_submission_host import EngineerSubmissionHost, EngineerSubmissionHostConfiguration
from integration.engineer_learning_actions import EngineerLearningActionAssembler
from integration.engineer_transition_actions import EngineerTransitionActionAssembler
from integration.engineer_intake_actions import EngineerIntakeActionAssembler
from integration.engineer_planning_actions import EngineerPlanningActionAssembler
from integration.engineer_planning_recovery_reader import (
    EngineerPlanningRecoveryReader, EngineerPlanningRecoverySettings, EngineerPlanningRecoveryBindings,
    build_assembled_engineer_planning_dispatcher,
)
from integration.engineer_intake_recovery_reader import (
    EngineerIntakeRecoveryReader, EngineerIntakeRecoverySettings, EngineerIntakeRecoveryBindings,
    build_assembled_engineer_intake_dispatcher,
)
from integration.engineer_transition_reader import (
    EngineerTransitionReader, EngineerTransitionRecoveryBindings, EngineerTransitionRecoverySettings,
    build_assembled_engineer_transition_dispatcher,
)
from integration.engineer_learning_reader import (
    EngineerLearningReader, EngineerLearningRecoveryBindings, EngineerLearningRecoverySettings,
    build_assembled_engineer_learning_dispatcher,
)
from integration.engineer_learning_assessment_publication import (
    EngineerLearningAssessmentPublicationStore, EngineerLearningAssessmentPublishedViewProvider,
)
from integration.engineer_learning_assessment_validation import EngineerLearningAssessmentSourceValidator
from integration.engineer_training_estimate_publication import (
    EngineerTrainingEstimatePublicationStore, EngineerTrainingEstimatePublishedViewProvider,
)
from integration.engineer_training_estimate_validation import EngineerTrainingEstimateSourceValidator
from integration.engineer_design_actions import EngineerDesignActionAssembler
from integration.engineer_design_recovery_reader import (
    EngineerDesignRecoveryReader, EngineerDesignRecoverySettings, EngineerDesignRecoveryBindings,
    build_assembled_engineer_design_dispatcher,
)
from integration.engineer_parameter_publication import EngineerParameterPublicationStore, EngineerParameterPublishedViewProvider
from integration.engineer_parameter_validation import EngineerParameterSourceValidator
from integration.engineer_parameter_calculations import prepare_engineer_parameter_calculation, _prepare_engineer_design_calculation
from integration.engineer_interface_check_calculations import prepare_engineer_interface_check_calculation
from integration.engineer_interface_check_publication import EngineerInterfaceCheckPublicationStore, EngineerInterfaceCheckPublishedViewProvider
from integration.engineer_interface_check_validation import EngineerInterfaceCheckSourceValidator
from integration.engineer_design_calculation_publication import publish_engineer_design_calculations
from integration.engineer_design_calculation_publication import _publish_engineer_joint_calculations
from integration.engineer_change_revision_calculation_publication import publish_engineer_change_revision_calculations
from integration.engineer_review_actions import EngineerReviewActionAssembler
from integration.engineer_review_check_calculations import prepare_engineer_review_check_calculation
from integration.engineer_review_check_publication import EngineerReviewCheckPublicationStore, EngineerReviewCheckPublishedViewProvider
from integration.engineer_review_check_validation import EngineerReviewCheckSourceValidator
from integration.engineer_research_actions import EngineerResearchActionAssembler
from integration.engineer_research_recovery_reader import (
    EngineerResearchRecoveryReader, EngineerResearchRecoverySettings, EngineerResearchRecoveryBindings,
    build_assembled_engineer_research_dispatcher,
)
from integration.engineer_research_check_calculations import prepare_engineer_research_check_calculation
from integration.engineer_research_check_publication import EngineerResearchCheckPublicationStore, EngineerResearchCheckPublishedViewProvider
from integration.engineer_research_check_validation import EngineerResearchCheckSourceValidator
from integration.engineer_research_estimate_calculations import prepare_engineer_research_estimate_calculation
from integration.engineer_research_estimate_publication import EngineerResearchEstimatePublicationStore, EngineerResearchEstimatePublishedViewProvider
from integration.engineer_research_estimate_validation import EngineerResearchEstimateSourceValidator
from integration.engineer_inspection_actions import EngineerInspectionActionAssembler
from integration.engineer_inspection_recovery_reader import (
    EngineerInspectionRecoveryReader, EngineerInspectionRecoverySettings, EngineerInspectionRecoveryBindings,
    build_assembled_engineer_inspection_dispatcher,
)
from integration.engineer_inspection_check_calculations import prepare_engineer_inspection_check_calculation
from integration.engineer_inspection_check_publication import EngineerInspectionCheckPublicationStore, EngineerInspectionCheckPublishedViewProvider
from integration.engineer_inspection_check_validation import EngineerInspectionCheckSourceValidator
from integration.engineer_billing_actions import EngineerBillingActionAssembler
from integration.engineer_billing_recovery_reader import (
    EngineerBillingRecoveryReader, EngineerBillingRecoverySettings, EngineerBillingRecoveryBindings,
    build_assembled_engineer_billing_dispatcher,
)
from integration.engineer_change_actions import EngineerChangeActionAssembler
from integration.engineer_change_recovery_reader import (
    EngineerChangeRecoveryReader, EngineerChangeRecoverySettings, EngineerChangeRecoveryBindings,
    build_assembled_engineer_change_dispatcher,
)
from integration.engineer_change_check_calculations import prepare_engineer_change_check_calculation
from integration.engineer_change_check_publication import EngineerChangeCheckPublicationStore, EngineerChangeCheckPublishedViewProvider
from integration.engineer_change_check_validation import EngineerChangeCheckSourceValidator
from integration.engineer_change_parameter_calculations import prepare_engineer_change_parameter_calculation
from integration.engineer_change_revision_check_calculations import prepare_engineer_change_revision_check_calculation
from integration.engineer_change_parameter_publication import EngineerChangeParameterPublicationStore, EngineerChangeParameterPublishedViewProvider
from integration.engineer_change_revision_check_publication import EngineerChangeRevisionCheckPublicationStore, EngineerChangeRevisionCheckPublishedViewProvider
from integration.engineer_change_parameter_validation import EngineerChangeParameterSourceValidator
from integration.engineer_change_revision_check_validation import EngineerChangeRevisionCheckSourceValidator
from integration.role_contract_host import RoleContractInvocation
from src.actions.contracts.common import ActionContext, StrictRecord, TextId
from src.actions.contracts.engineer_design_objects import engineer_design_schemas
from src.actions.roles.engineer_design import prepare_engineer_parameter_input, prepare_engineer_interface_check_input
from src.actions.contracts.engineer_review_objects import engineer_review_schemas
from src.actions.roles.engineer_review import prepare_engineer_review_check_input
from src.actions.contracts.engineer_research_objects import engineer_research_schemas
from src.actions.roles.engineer_research import prepare_engineer_research_check_input
from src.actions.roles.engineer_research import prepare_engineer_research_estimate_input
from src.actions.contracts.engineer_inspection_objects import engineer_inspection_schemas
from src.actions.roles.engineer_inspection import prepare_engineer_inspection_check_input
from src.actions.contracts.engineer_change_objects import engineer_change_schemas
from src.actions.roles.engineer_change import prepare_engineer_change_check_input
from src.actions.roles.engineer_change import prepare_engineer_change_parameter_input
from src.actions.roles.engineer_change import prepare_engineer_change_revision_check_input
from src.coordination.invocations import InvocationSnapshotStore
from src.coordination.tasks import TaskConflict, canonical, task_digest
from src.methods.registry import MethodRegistry


class EngineerFormalFeedbackSettings(StrictRecord):
    version: TextId
    inbox_path: TextId
    input_enabled: bool = False


class EngineerFormalLearningAssessmentSettings(StrictRecord):
    version: TextId
    macro_version: TextId
    policy_version: TextId


class EngineerFormalTrainingEstimateSettings(StrictRecord):
    version: TextId
    macro_version: TextId
    policy_version: TextId


class EngineerFormalParameterCalculationSettings(StrictRecord):
    version: TextId
    macro_version: TextId
    policy_version: TextId


class EngineerFormalInterfaceCheckSettings(StrictRecord):
    version: TextId
    macro_version: TextId
    policy_version: TextId


class EngineerFormalReviewCheckSettings(StrictRecord):
    version: TextId
    macro_version: TextId
    policy_version: TextId


class EngineerFormalResearchCheckSettings(StrictRecord):
    version: TextId
    macro_version: TextId
    policy_version: TextId


class EngineerFormalInspectionCheckSettings(StrictRecord):
    version: TextId
    macro_version: TextId
    policy_version: TextId


class EngineerFormalChangeCheckSettings(StrictRecord):
    version: TextId
    macro_version: TextId
    policy_version: TextId


class EngineerFormalChangeParameterSettings(StrictRecord):
    version: TextId
    macro_version: TextId
    policy_version: TextId


class EngineerFormalChangeRevisionCheckSettings(StrictRecord):
    version: TextId
    macro_version: TextId
    policy_version: TextId


class EngineerFormalResearchEstimateSettings(StrictRecord):
    version: TextId
    macro_version: TextId
    policy_version: TextId


class EngineerFormalApplicationSettings(StrictRecord):
    action_id: TextId
    dependency_factory: TextId
    dependency_version: TextId
    dependency_settings: dict
    client_version: TextId
    model_version: TextId
    submission: EngineerSubmissionHostConfiguration | None = None
    feedback: EngineerFormalFeedbackSettings | None = None
    execution_recovery: EngineerTransitionRecoverySettings | EngineerLearningRecoverySettings | EngineerIntakeRecoverySettings | EngineerPlanningRecoverySettings | EngineerDesignRecoverySettings | EngineerInspectionRecoverySettings | EngineerChangeRecoverySettings | EngineerBillingRecoverySettings | EngineerResearchRecoverySettings | EngineerSubmissionRecoverySettings | None = None
    learning_assessment: EngineerFormalLearningAssessmentSettings | None = None
    training_estimates: EngineerFormalTrainingEstimateSettings | None = None
    parameter_calculations: EngineerFormalParameterCalculationSettings | None = None
    interface_checks: EngineerFormalInterfaceCheckSettings | None = None
    review_checks: EngineerFormalReviewCheckSettings | None = None
    research_checks: EngineerFormalResearchCheckSettings | None = None
    research_estimates: EngineerFormalResearchEstimateSettings | None = None
    inspection_checks: EngineerFormalInspectionCheckSettings | None = None
    change_checks: EngineerFormalChangeCheckSettings | None = None
    change_parameters: EngineerFormalChangeParameterSettings | None = None
    change_revision_checks: EngineerFormalChangeRevisionCheckSettings | None = None

    @model_validator(mode='before')
    @classmethod
    def original_action_recovery(cls, value):
        if not isinstance(value, dict) or value.get('execution_recovery') is None:
            return value
        types = {'ENGINEER-A02': EngineerIntakeRecoverySettings,
            'ENGINEER-A04': EngineerPlanningRecoverySettings,
            'ENGINEER-A05': EngineerDesignRecoverySettings,
            'ENGINEER-A08': EngineerInspectionRecoverySettings,
            'ENGINEER-A09': EngineerChangeRecoverySettings,
            'ENGINEER-A10': EngineerBillingRecoverySettings,
            'ENGINEER-A13': EngineerResearchRecoverySettings,
            'ENGINEER-A07': EngineerSubmissionRecoverySettings, 'ENGINEER-A12': EngineerLearningRecoverySettings,
            'ENGINEER-A11': EngineerTransitionRecoverySettings}
        action_id, recovery = value.get('action_id'), value['execution_recovery']
        if action_id not in types:
            raise ValueError('Engineer recovery requires original A02 intake, A04 planning, A05 design, A07 submission, A08 inspection, A09 change, A10 billing, A11 transition, A12 learning or A13 research action')
        settings_type = types[action_id]
        if isinstance(recovery, EngineerSubmissionRecoverySettings) and type(recovery) is not settings_type:
            raise ValueError('Engineer recovery configuration changes its original action type')
        return {**value, 'execution_recovery': settings_type.model_validate(recovery)}


@dataclass(frozen=True)
class EngineerFormalApplicationDependencies:
    """Actual application supplies original sources and an existing model host.

    The factory owns partial resources until returning this bundle. Original
    invocation/wait/recovery validators apply to all submission workers; actual
    action-specific transport and business validation are explicitly supplied.
    """
    version: str
    sources: EngineerRoleContractSources
    submission_callbacks: dict[str, EngineerSubmissionCallbacks] = field(default_factory=dict)
    submission_read_guard: Callable | None = None
    validate_feedback_relation: Callable | None = None
    validate_feedback_read: Callable | None = None
    validate_feedback_input: Callable | None = None
    execution_recovery: EngineerTransitionRecoveryBindings | EngineerLearningRecoveryBindings | EngineerSubmissionRecoveryBindings | EngineerIntakeRecoveryBindings | EngineerPlanningRecoveryBindings | EngineerDesignRecoveryBindings | EngineerInspectionRecoveryBindings | EngineerChangeRecoveryBindings | EngineerBillingRecoveryBindings | EngineerResearchRecoveryBindings | None = None

    def __post_init__(self):
        if (not isinstance(self.version, str) or not self.version.strip()
                or not isinstance(self.sources, EngineerRoleContractSources)
                or self.sources.feedback is not None or self.sources.validate_feedback_input is not None
                or self.sources.save_learning_assessment is not None
                or self.sources.publish_saved_learning_assessment is not None
                or self.sources.save_training_estimate is not None
                or self.sources.publish_saved_training_estimate is not None
                or self.sources.save_parameter_calculation is not None
                or self.sources.publish_saved_parameter_calculations is not None
                or self.sources.save_interface_check_calculation is not None
                or self.sources.publish_saved_interface_check_calculations is not None
                or self.sources.publish_saved_design_calculations is not None
                or self.sources.publish_saved_change_revision_calculations is not None
                or self.sources.save_review_check_calculation is not None
                or self.sources.publish_saved_review_check_calculations is not None
                or self.sources.save_research_check_calculation is not None
                or self.sources.publish_saved_research_check_calculations is not None
                or self.sources.save_inspection_check_calculation is not None
                or self.sources.publish_saved_inspection_check_calculations is not None
                or self.sources.save_change_check_calculation is not None
                or self.sources.publish_saved_change_check_calculations is not None
                or self.sources.save_change_parameter_calculation is not None
                or self.sources.publish_saved_change_parameter_calculations is not None
                or self.sources.save_change_revision_check_calculation is not None
                or self.sources.publish_saved_change_revision_check_calculations is not None
                or self.sources.save_research_estimate_calculation is not None
                or self.sources.publish_saved_research_estimate_calculations is not None
                or not isinstance(self.submission_callbacks, dict)
                or self.execution_recovery is not None and not isinstance(
                    self.execution_recovery, EngineerSubmissionRecoveryBindings)
                or any(not isinstance(value, EngineerSubmissionCallbacks) for value in self.submission_callbacks.values())
                or any(callback is not None and not callable(callback) for callback in
                    (self.submission_read_guard, self.validate_feedback_relation,
                        self.validate_feedback_read, self.validate_feedback_input))):
            raise ValueError('Formal Engineer dependencies require original sources and actual callback bindings')


class EngineerFormalApplication:
    """Assemble original workers and configured routes; business calls stay explicit.

    Source health and native endpoint effects require observed application
    evidence. Construction is configured_unverified and never runs an action,
    sends a submission, constructs a model client or invents a native source.
    Professional design, inspection, review, billing, learning and transition routes require actual
    application transport. Configuration and receipts do not prove acceptance,
    signing, use rights, qualification renewal, applied learning, fees, cash or released service obligations.
    """
    VERSION = 'engineer-formal-application.v1'

    def __init__(self, *, request, settings, dependencies, factory_descriptor):
        self.settings = EngineerFormalApplicationSettings.model_validate(settings).model_copy(deep=True)
        request = RoleContractInvocation.model_validate(request).model_copy(deep=True)
        if not isinstance(dependencies, EngineerFormalApplicationDependencies):
            raise ValueError('Formal Engineer factory must return EngineerFormalApplicationDependencies')
        base = dependencies.sources
        config = self.settings
        model = base.model_host
        if (config.action_id not in _ACTIONS or request.context.contract_ref.id != config.action_id
                or request.context.execution_mode != 'llm' or request.context.run_id != base.store.run_id
                or base.organizations.run_id != base.store.run_id or dependencies.version != config.dependency_version
                or model is None or model.store is not base.store or model.registry is not base.registry
                or model.model_version != config.model_version):
            raise ValueError('Formal Engineer assembly requires original same-run sources and configured model host')
        registration = base.registry.get(config.action_id)
        if (registration.role != 'Engineer' or not registration.implemented or registration.skill is None
                or request.execution_path not in {None, registration.strategy}
                or not any(config.action_id in binding.action_ids and binding.strategy == registration.strategy
                    for binding in model.bindings)):
            raise ValueError('Formal Engineer application requires its original implemented action and bound strategy')
        actions = {route.action_id for route in config.submission.routes} if config.submission is not None else set()
        if (not actions <= set(_ACTIONS) or set(dependencies.submission_callbacks) != actions
                or config.submission is not None and not callable(dependencies.submission_read_guard)
                or config.submission is None and dependencies.submission_read_guard is not None):
            raise ValueError('Configured Engineer submission must match its explicit callbacks and current read guard')
        if config.feedback is not None:
            if (config.submission is None or not actions
                    or not callable(dependencies.validate_feedback_relation)
                    or not callable(dependencies.validate_feedback_read)):
                raise ValueError('Engineer feedback requires configured submission routes and actual relation/read validators')
        elif dependencies.validate_feedback_relation is not None or dependencies.validate_feedback_read is not None:
            raise ValueError('Engineer feedback validators require an explicit feedback configuration')
        input_enabled = config.feedback is not None and config.feedback.input_enabled
        if (input_enabled and not callable(dependencies.validate_feedback_input)
                or not input_enabled and dependencies.validate_feedback_input is not None):
            raise ValueError('Engineer feedback input validation must match the explicit input-enabled configuration')
        self.dependencies, self.base = dependencies, base
        self.factory_descriptor = deepcopy(factory_descriptor)
        self._components = (base, base.store, base.registry, base.organizations, base.provider, model)
        self._closed = False
        self.provider = base.provider
        self.assessment_validator = self.assessment_publications = self.assessment_assembler = None
        if config.learning_assessment is not None:
            assessment = config.learning_assessment
            if not isinstance(base.methods, MethodRegistry):
                raise ValueError('Engineer learning assessment requires the original bound method registry')
            self.assessment_validator = EngineerLearningAssessmentSourceValidator(registry=base.registry,
                organizations=base.organizations, provider=base.provider,
                macro_version=assessment.macro_version, source_mode='formal')
            self.assessment_publications = EngineerLearningAssessmentPublicationStore(store=base.store,
                registry=base.registry, methods=base.methods, organizations=base.organizations,
                validate_source=self.assessment_validator.validate_source)
            self.assessment_assembler = EngineerLearningActionAssembler(registry=base.registry,
                organizations=base.organizations, provider=base.provider, macro_version=assessment.macro_version,
                source_mode='formal', methods=base.methods, policy_version=assessment.policy_version,
                model_version=config.model_version, model_host=model)
            self.provider = EngineerLearningAssessmentPublishedViewProvider(provider=base.provider,
                publications=self.assessment_publications)
        self.assessment_provider = self.provider
        self._assessment_components = (self.assessment_provider, self.assessment_validator,
            self.assessment_publications, self.assessment_assembler, base.methods)
        self.training_validator = self.training_publications = self.training_assembler = None
        if config.training_estimates is not None:
            training = config.training_estimates
            if not isinstance(base.methods, MethodRegistry):
                raise ValueError('Engineer training estimates require the original bound method registry')
            self.training_validator = EngineerTrainingEstimateSourceValidator(registry=base.registry,
                organizations=base.organizations, provider=base.provider,
                macro_version=training.macro_version, source_mode='formal')
            self.training_publications = EngineerTrainingEstimatePublicationStore(store=base.store,
                registry=base.registry, methods=base.methods, organizations=base.organizations,
                validate_source=self.training_validator.validate_source)
            self.training_assembler = EngineerLearningActionAssembler(registry=base.registry,
                organizations=base.organizations, provider=base.provider, macro_version=training.macro_version,
                source_mode='formal', methods=base.methods, policy_version=training.policy_version,
                model_version=config.model_version, model_host=model)
            self.provider = EngineerTrainingEstimatePublishedViewProvider(provider=self.assessment_provider,
                publications=self.training_publications)
        self.training_provider = self.provider
        self._training_components = (self.training_provider, self.training_validator, self.training_publications,
            self.training_assembler, base.methods)
        self.parameter_validator = self.parameter_publications = self.parameter_assembler = None
        if config.parameter_calculations is not None:
            parameter = config.parameter_calculations
            if not isinstance(base.methods, MethodRegistry):
                raise ValueError('Engineer parameter calculations require the original bound method registry')
            self.parameter_validator = EngineerParameterSourceValidator(registry=base.registry,
                organizations=base.organizations, provider=base.provider,
                macro_version=parameter.macro_version, source_mode='formal')
            self.parameter_publications = EngineerParameterPublicationStore(store=base.store,
                registry=base.registry, methods=base.methods, organizations=base.organizations,
                validate_source=self.parameter_validator.validate_source)
            self.parameter_assembler = EngineerDesignActionAssembler(registry=base.registry,
                organizations=base.organizations, provider=base.provider, macro_version=parameter.macro_version,
                source_mode='formal', methods=base.methods, policy_version=parameter.policy_version,
                model_version=config.model_version, model_host=model)
            self.provider = EngineerParameterPublishedViewProvider(provider=self.training_provider,
                publications=self.parameter_publications)
        self.parameter_provider = self.provider
        self._parameter_components = (self.parameter_provider, self.parameter_validator, self.parameter_publications,
            self.parameter_assembler, base.methods)
        self.check_validator = self.check_publications = self.check_assembler = None
        if config.interface_checks is not None:
            check = config.interface_checks
            if not isinstance(base.methods, MethodRegistry):
                raise ValueError('Engineer interface checks require the original bound method registry')
            self.check_validator = EngineerInterfaceCheckSourceValidator(registry=base.registry,
                organizations=base.organizations, provider=base.provider,
                macro_version=check.macro_version, source_mode='formal')
            self.check_publications = EngineerInterfaceCheckPublicationStore(store=base.store,
                registry=base.registry, methods=base.methods, organizations=base.organizations,
                validate_source=self.check_validator.validate_source)
            self.check_assembler = EngineerDesignActionAssembler(registry=base.registry,
                organizations=base.organizations, provider=base.provider, macro_version=check.macro_version,
                source_mode='formal', methods=base.methods, policy_version=check.policy_version,
                model_version=config.model_version, model_host=model)
            self.provider = EngineerInterfaceCheckPublishedViewProvider(provider=self.parameter_provider,
                publications=self.check_publications)
        self.interface_check_provider = self.provider
        self._check_components = (self.interface_check_provider, self.check_validator, self.check_publications,
            self.check_assembler, base.methods)
        self.review_check_validator = self.review_check_publications = self.review_check_assembler = None
        if config.review_checks is not None:
            check = config.review_checks
            if not isinstance(base.methods, MethodRegistry):
                raise ValueError('Engineer review checks require the original bound method registry')
            self.review_check_validator = EngineerReviewCheckSourceValidator(registry=base.registry,
                organizations=base.organizations, provider=base.provider,
                macro_version=check.macro_version, source_mode='formal')
            self.review_check_publications = EngineerReviewCheckPublicationStore(store=base.store,
                registry=base.registry, methods=base.methods, organizations=base.organizations,
                validate_source=self.review_check_validator.validate_source)
            self.review_check_assembler = EngineerReviewActionAssembler(registry=base.registry,
                organizations=base.organizations, provider=base.provider, macro_version=check.macro_version,
                source_mode='formal', methods=base.methods, policy_version=check.policy_version,
                model_version=config.model_version, model_host=model)
            self.provider = EngineerReviewCheckPublishedViewProvider(provider=self.interface_check_provider,
                publications=self.review_check_publications)
        self.review_check_provider = self.provider
        self._review_check_components = (self.review_check_provider, self.review_check_validator, self.review_check_publications,
            self.review_check_assembler, base.methods)
        self.research_check_validator = self.research_check_publications = self.research_check_assembler = None
        if config.research_checks is not None:
            check = config.research_checks
            if not isinstance(base.methods, MethodRegistry):
                raise ValueError('Engineer research checks require the original bound method registry')
            self.research_check_validator = EngineerResearchCheckSourceValidator(registry=base.registry,
                organizations=base.organizations, provider=base.provider,
                macro_version=check.macro_version, source_mode='formal')
            self.research_check_publications = EngineerResearchCheckPublicationStore(store=base.store,
                registry=base.registry, methods=base.methods, organizations=base.organizations,
                validate_source=self.research_check_validator.validate_source)
            self.research_check_assembler = EngineerResearchActionAssembler(registry=base.registry,
                organizations=base.organizations, provider=base.provider, macro_version=check.macro_version,
                source_mode='formal', methods=base.methods, policy_version=check.policy_version,
                model_version=config.model_version, model_host=model)
            self.provider = EngineerResearchCheckPublishedViewProvider(provider=self.review_check_provider,
                publications=self.research_check_publications)
        self.research_check_provider = self.provider
        self._research_check_components = (self.research_check_provider, self.research_check_validator, self.research_check_publications,
            self.research_check_assembler, base.methods)
        self.research_estimate_validator = self.research_estimate_publications = self.research_estimate_assembler = None
        if config.research_estimates is not None:
            check = config.research_estimates
            if not isinstance(base.methods, MethodRegistry):
                raise ValueError('Engineer research estimates require the original bound method registry')
            self.research_estimate_validator = EngineerResearchEstimateSourceValidator(registry=base.registry,
                organizations=base.organizations, provider=base.provider,
                macro_version=check.macro_version, source_mode='formal')
            self.research_estimate_publications = EngineerResearchEstimatePublicationStore(store=base.store,
                registry=base.registry, methods=base.methods, organizations=base.organizations,
                validate_source=self.research_estimate_validator.validate_source)
            self.research_estimate_assembler = EngineerResearchActionAssembler(registry=base.registry,
                organizations=base.organizations, provider=base.provider, macro_version=check.macro_version,
                source_mode='formal', methods=base.methods, policy_version=check.policy_version,
                model_version=config.model_version, model_host=model)
            self.provider = EngineerResearchEstimatePublishedViewProvider(provider=self.research_check_provider,
                publications=self.research_estimate_publications)
        self.research_estimate_provider = self.provider
        self._research_estimate_components = (self.research_estimate_provider, self.research_estimate_validator, self.research_estimate_publications,
            self.research_estimate_assembler, base.methods)
        self.inspection_check_validator = self.inspection_check_publications = self.inspection_check_assembler = None
        if config.inspection_checks is not None:
            check = config.inspection_checks
            if not isinstance(base.methods, MethodRegistry):
                raise ValueError('Engineer inspection checks require the original bound method registry')
            self.inspection_check_validator = EngineerInspectionCheckSourceValidator(registry=base.registry,
                organizations=base.organizations, provider=base.provider,
                macro_version=check.macro_version, source_mode='formal')
            self.inspection_check_publications = EngineerInspectionCheckPublicationStore(store=base.store,
                registry=base.registry, methods=base.methods, organizations=base.organizations,
                validate_source=self.inspection_check_validator.validate_source)
            self.inspection_check_assembler = EngineerInspectionActionAssembler(registry=base.registry,
                organizations=base.organizations, provider=base.provider, macro_version=check.macro_version,
                source_mode='formal', methods=base.methods, policy_version=check.policy_version,
                model_version=config.model_version, model_host=model)
            self.provider = EngineerInspectionCheckPublishedViewProvider(provider=self.research_estimate_provider,
                publications=self.inspection_check_publications)
        self.inspection_check_provider = self.provider
        self._inspection_check_components = (self.inspection_check_provider, self.inspection_check_validator, self.inspection_check_publications,
            self.inspection_check_assembler, base.methods)
        self.change_check_validator = self.change_check_publications = self.change_check_assembler = None
        if config.change_checks is not None:
            check = config.change_checks
            if not isinstance(base.methods, MethodRegistry):
                raise ValueError('Engineer change checks require the original bound method registry')
            self.change_check_validator = EngineerChangeCheckSourceValidator(registry=base.registry,
                organizations=base.organizations, provider=base.provider,
                macro_version=check.macro_version, source_mode='formal')
            self.change_check_publications = EngineerChangeCheckPublicationStore(store=base.store,
                registry=base.registry, methods=base.methods, organizations=base.organizations,
                validate_source=self.change_check_validator.validate_source)
            self.change_check_assembler = EngineerChangeActionAssembler(registry=base.registry,
                organizations=base.organizations, provider=base.provider, macro_version=check.macro_version,
                source_mode='formal', methods=base.methods, policy_version=check.policy_version,
                model_version=config.model_version, model_host=model)
            self.provider = EngineerChangeCheckPublishedViewProvider(provider=self.inspection_check_provider,
                publications=self.change_check_publications)
        self.change_check_provider = self.provider
        self._change_check_components = (self.change_check_provider, self.change_check_validator, self.change_check_publications,
            self.change_check_assembler, base.methods)
        self.change_parameter_validator = self.change_parameter_publications = self.change_parameter_assembler = None
        if config.change_parameters is not None:
            check = config.change_parameters
            if not isinstance(base.methods, MethodRegistry):
                raise ValueError('Engineer revision parameters require the original bound method registry')
            self.change_parameter_validator = EngineerChangeParameterSourceValidator(registry=base.registry,
                organizations=base.organizations, provider=base.provider,
                macro_version=check.macro_version, source_mode='formal')
            self.change_parameter_publications = EngineerChangeParameterPublicationStore(store=base.store,
                registry=base.registry, methods=base.methods, organizations=base.organizations,
                validate_source=self.change_parameter_validator.validate_source)
            self.change_parameter_assembler = EngineerChangeActionAssembler(registry=base.registry,
                organizations=base.organizations, provider=base.provider, macro_version=check.macro_version,
                source_mode='formal', methods=base.methods, policy_version=check.policy_version,
                model_version=config.model_version, model_host=model)
            self.provider = EngineerChangeParameterPublishedViewProvider(provider=self.change_check_provider,
                publications=self.change_parameter_publications)
        self.change_parameter_provider = self.provider
        self._change_parameter_components = (self.change_parameter_provider, self.change_parameter_validator, self.change_parameter_publications,
            self.change_parameter_assembler, base.methods)
        self.change_revision_check_validator = self.change_revision_check_publications = self.change_revision_check_assembler = None
        if config.change_revision_checks is not None:
            check = config.change_revision_checks
            if not isinstance(base.methods, MethodRegistry):
                raise ValueError('Engineer revision interface checks require the original bound method registry')
            self.change_revision_check_validator = EngineerChangeRevisionCheckSourceValidator(registry=base.registry,
                organizations=base.organizations, provider=base.provider,
                macro_version=check.macro_version, source_mode='formal')
            self.change_revision_check_publications = EngineerChangeRevisionCheckPublicationStore(store=base.store,
                registry=base.registry, methods=base.methods, organizations=base.organizations,
                validate_source=self.change_revision_check_validator.validate_source)
            self.change_revision_check_assembler = EngineerChangeActionAssembler(registry=base.registry,
                organizations=base.organizations, provider=base.provider, macro_version=check.macro_version,
                source_mode='formal', methods=base.methods, policy_version=check.policy_version,
                model_version=config.model_version, model_host=model)
            self.provider = EngineerChangeRevisionCheckPublishedViewProvider(provider=self.change_parameter_provider,
                publications=self.change_revision_check_publications)
        self._change_revision_check_components = (self.provider, self.change_revision_check_validator, self.change_revision_check_publications,
            self.change_revision_check_assembler, base.methods)
        self.submissions = self.feedback = self.execution_dispatcher = None
        self.receipt_assembler = self.receipt_reader = None
        self._receipt_recovery_components = None
        if config.submission is not None:
            snapshots = InvocationSnapshotStore(base.store)
            workers = {}
            for action_id in sorted(actions):
                module, name = _ACTIONS[action_id]
                worker_type = getattr(importlib.import_module('integration.engineer_' + module + '_results'),
                    'Engineer' + name + 'ResultWorker')
                workers[action_id] = worker_type(store=base.store, snapshots=snapshots, registry=base.registry,
                    client_version=config.client_version, model_version=config.model_version,
                    validate_invocation=base.validators.invocation, validate_wait=base.validators.wait,
                    validate_recovery=base.validators.recovery)
            self.submissions = EngineerSubmissionHost(store=base.store, registry=base.registry, workers=workers,
                callbacks=dependencies.submission_callbacks, read_guard=dependencies.submission_read_guard,
                configuration=config.submission)
        if config.feedback is not None:
            inbox = ObservationInbox(base.store.run_id, base.store.organization_ids, Path(config.feedback.inbox_path))
            self.feedback = EngineerSubmissionFeedback(host=self.submissions, inbox=inbox,
                version=config.feedback.version, validate_relation=dependencies.validate_feedback_relation,
                validate_read=dependencies.validate_feedback_read)
        recovery = dependencies.execution_recovery
        if (config.execution_recovery is None) != (recovery is None):
            raise ValueError('Engineer receipt recovery must match its explicit configuration')
        if recovery is not None:
            routes = {
                'ENGINEER-A02': (EngineerIntakeRecoverySettings, EngineerIntakeRecoveryBindings,
                    EngineerIntakeActionAssembler, build_assembled_engineer_intake_dispatcher),
                'ENGINEER-A04': (EngineerPlanningRecoverySettings, EngineerPlanningRecoveryBindings,
                    EngineerPlanningActionAssembler, build_assembled_engineer_planning_dispatcher),
                'ENGINEER-A05': (EngineerDesignRecoverySettings, EngineerDesignRecoveryBindings,
                    EngineerDesignActionAssembler, build_assembled_engineer_design_dispatcher),
                'ENGINEER-A08': (EngineerInspectionRecoverySettings, EngineerInspectionRecoveryBindings,
                    EngineerInspectionActionAssembler, build_assembled_engineer_inspection_dispatcher),
                'ENGINEER-A09': (EngineerChangeRecoverySettings, EngineerChangeRecoveryBindings,
                    EngineerChangeActionAssembler, build_assembled_engineer_change_dispatcher),
                'ENGINEER-A10': (EngineerBillingRecoverySettings, EngineerBillingRecoveryBindings,
                    EngineerBillingActionAssembler, build_assembled_engineer_billing_dispatcher),
                'ENGINEER-A13': (EngineerResearchRecoverySettings, EngineerResearchRecoveryBindings,
                    EngineerResearchActionAssembler, build_assembled_engineer_research_dispatcher),
                'ENGINEER-A07': (EngineerSubmissionRecoverySettings, EngineerSubmissionRecoveryBindings,
                    EngineerDeliverableActionAssembler, build_assembled_engineer_submission_receipt_dispatcher),
                'ENGINEER-A12': (EngineerLearningRecoverySettings, EngineerLearningRecoveryBindings,
                    EngineerLearningActionAssembler, build_assembled_engineer_learning_dispatcher),
                'ENGINEER-A11': (EngineerTransitionRecoverySettings, EngineerTransitionRecoveryBindings,
                    EngineerTransitionActionAssembler, build_assembled_engineer_transition_dispatcher),
            }
            if config.action_id not in routes or config.action_id not in actions or self.feedback is None:
                raise ValueError('Engineer recovery requires original A02, A04, A05, A07, A08, A09, A10, A11, A12 or A13 submission and feedback routes')
            settings_type, bindings_type, assembler_type, build_dispatcher = routes[config.action_id]
            if type(config.execution_recovery) is not settings_type or type(recovery) is not bindings_type:
                raise ValueError('Engineer recovery settings and callbacks must match the original action')
            self.receipt_assembler = assembler_type(registry=base.registry,
                organizations=base.organizations, provider=self.provider,
                macro_version=config.execution_recovery.macro_version, source_mode='formal', methods=base.methods,
                policy_version=config.execution_recovery.policy_version, model_version=config.model_version,
                model_host=model)
            reader_options = {}
            if config.action_id in {'ENGINEER-A02', 'ENGINEER-A04', 'ENGINEER-A05', 'ENGINEER-A08', 'ENGINEER-A09', 'ENGINEER-A10', 'ENGINEER-A11', 'ENGINEER-A12', 'ENGINEER-A13'}:
                reader_type = (EngineerIntakeRecoveryReader if config.action_id == 'ENGINEER-A02' else
                    EngineerPlanningRecoveryReader if config.action_id == 'ENGINEER-A04' else
                    EngineerDesignRecoveryReader if config.action_id == 'ENGINEER-A05' else
                    EngineerInspectionRecoveryReader if config.action_id == 'ENGINEER-A08' else
                    EngineerChangeRecoveryReader if config.action_id == 'ENGINEER-A09' else
                    EngineerBillingRecoveryReader if config.action_id == 'ENGINEER-A10' else
                    EngineerResearchRecoveryReader if config.action_id == 'ENGINEER-A13' else
                    EngineerTransitionReader if config.action_id == 'ENGINEER-A11' else EngineerLearningReader)
                self.receipt_reader = reader_type(assembler=self.receipt_assembler,
                    snapshots=InvocationSnapshotStore(base.store), select_current=recovery.select_current)
                reader_options['reader'] = self.receipt_reader
            else:
                self.receipt_reader = EngineerSubmissionReceiptReader(assembler=self.receipt_assembler,
                    select_current=recovery.select_current)
            self.execution_dispatcher = build_dispatcher(
                inbox=self.feedback.inbox, store=base.store, assembler=self.receipt_assembler,
                select_current=recovery.select_current, read_guard=recovery.read_guard,
                validate_relation=recovery.validate_relation, project_signal=recovery.project_signal,
                prepare=recovery.prepare, revalidate=recovery.revalidate, **reader_options)
            self._receipt_recovery_components = (recovery, *recovery.components(), self.receipt_assembler,
                self.receipt_reader, self.execution_dispatcher, self.feedback.inbox, self.provider)
        self._declared = self._configuration()
        self._key = 'engineer_formal_application:' + task_digest([config.dependency_factory, config.action_id])
        with base.store._transaction():
            prior = base.store._db.execute('SELECT value FROM metadata WHERE key=?', (self._key,)).fetchone()
            if prior is None:
                base.store._db.execute('INSERT INTO metadata VALUES (?,?)', (self._key, canonical(self._declared)))
            elif json.loads(prior[0]) != self._declared:
                raise TaskConflict('Original formal Engineer application configuration changed; explicit review required')

    def _configuration(self):
        return {'schema_version': self.VERSION, 'run_id': self.base.store.run_id,
            'settings_sha256': task_digest(self.settings.model_dump(mode='json')),
            'dependency_version': self.dependencies.version, 'source_version': self.base.version,
            'dependency_factory': self.factory_descriptor, 'sources': _descriptors(self.base),
            'code': module_factory_descriptor(type(self).sources, self.VERSION),
            'model_configuration_sha256': self.base.model_host.configuration_sha256,
            'execution_recovery': None if self.receipt_reader is None else {
                'reader': self.receipt_reader.configuration_evidence(),
                'callbacks': self.dependencies.execution_recovery.configuration_evidence(),
                'policy_version': self.receipt_assembler.policy_version},
            'learning_assessment': None if self.assessment_validator is None else {
                'validator': deepcopy(self.assessment_validator._declared),
                'method_registry_sha256': self.base.methods.content_digest,
                'provider': module_factory_descriptor(self.assessment_provider.project, 'Engineer.learning_assessment_provider'),
                'producer': module_factory_descriptor(self.assessment_assembler.prepare_assessment, 'Engineer.learning_assessment_producer'),
                'save_entry': module_factory_descriptor(self.assessment_assembler.save_assessment, 'Engineer.learning_assessment_save_entry'),
                'save': module_factory_descriptor(self.assessment_publications.save, 'Engineer.learning_assessment_save'),
                'publish': module_factory_descriptor(self.assessment_publications.publish, 'Engineer.learning_assessment_publish'),
                'read': module_factory_descriptor(self.assessment_publications.read, 'Engineer.learning_assessment_read'),
                'validation': module_factory_descriptor(self.assessment_publications._validate, 'Engineer.learning_assessment_validation')},
            'submission_sha256': task_digest(self.submissions._declared) if self.submissions is not None else None,
            'training_estimates': None if self.training_validator is None else {
                'validator': deepcopy(self.training_validator._declared),
                'method_registry_sha256': self.base.methods.content_digest,
                'provider': module_factory_descriptor(self.training_provider.project, 'Engineer.training_estimate_provider'),
                'producer': module_factory_descriptor(self.training_assembler.prepare_training_estimate, 'Engineer.training_estimate_producer'),
                'save_entry': module_factory_descriptor(self.training_assembler.save_training_estimate, 'Engineer.training_estimate_save_entry'),
                'save': module_factory_descriptor(self.training_publications.save, 'Engineer.training_estimate_save'),
                'publish': module_factory_descriptor(self.training_publications.publish, 'Engineer.training_estimate_publish'),
                'read': module_factory_descriptor(self.training_publications.read, 'Engineer.training_estimate_read'),
                'validation': module_factory_descriptor(self.training_publications._validate, 'Engineer.training_estimate_validation')},
            'parameter_calculations': None if self.parameter_validator is None else {
                'validator': deepcopy(self.parameter_validator._declared),
                'method_registry_sha256': self.base.methods.content_digest,
                'provider': module_factory_descriptor(self.parameter_provider.project, 'Engineer.parameter_provider'),
                'producer': module_factory_descriptor(prepare_engineer_parameter_calculation, 'Engineer.parameter_producer'),
                'prepare_input': module_factory_descriptor(prepare_engineer_parameter_input, 'Engineer.parameter_prepare_input'),
                'source_schemas': module_factory_descriptor(engineer_design_schemas, 'Engineer.parameter_source_schemas'),
                'save_entry': module_factory_descriptor(self.parameter_assembler.save_parameter_calculation, 'Engineer.parameter_save_entry'),
                'save': module_factory_descriptor(self.parameter_publications.save, 'Engineer.parameter_save'),
                'publish': module_factory_descriptor(self.parameter_publications.publish, 'Engineer.parameter_publish'),
                'publish_many': module_factory_descriptor(self.parameter_publications.publish_many, 'Engineer.parameter_publish_many'),
                'read': module_factory_descriptor(self.parameter_publications.read, 'Engineer.parameter_read'),
                'validation': module_factory_descriptor(self.parameter_publications._validate, 'Engineer.parameter_validation')},
            'interface_checks': None if self.check_validator is None else {
                'validator': deepcopy(self.check_validator._declared),
                'method_registry_sha256': self.base.methods.content_digest,
                'provider': module_factory_descriptor(self.interface_check_provider.project, 'Engineer.interface_check_provider'),
                'producer': module_factory_descriptor(prepare_engineer_interface_check_calculation, 'Engineer.interface_check_producer'),
                'execution_runtime': module_factory_descriptor(_prepare_engineer_design_calculation, 'Engineer.interface_check_execution_runtime'),
                'prepare_input': module_factory_descriptor(prepare_engineer_interface_check_input, 'Engineer.interface_check_prepare_input'),
                'source_schemas': module_factory_descriptor(engineer_design_schemas, 'Engineer.interface_check_source_schemas'),
                'save_entry': module_factory_descriptor(self.check_assembler.save_interface_check_calculation, 'Engineer.interface_check_save_entry'),
                'save': module_factory_descriptor(self.check_publications.save, 'Engineer.interface_check_save'),
                'publish': module_factory_descriptor(self.check_publications.publish, 'Engineer.interface_check_publish'),
                'publish_many': module_factory_descriptor(self.check_publications.publish_many, 'Engineer.interface_check_publish_many'),
                'read': module_factory_descriptor(self.check_publications.read, 'Engineer.interface_check_read'),
                'validation': module_factory_descriptor(self.check_publications._validate, 'Engineer.interface_check_validation'),
                'result_association': module_factory_descriptor(self.check_publications._result_matches_input, 'Engineer.interface_check_result_association')},
            'joint_design_publication': None if self.parameter_validator is None or self.check_validator is None else
                module_factory_descriptor(publish_engineer_design_calculations, 'Engineer.joint_design_publication'),
            'joint_publication_runtime': None if not (
                self.parameter_validator is not None and self.check_validator is not None
                or self.change_parameter_validator is not None and self.change_revision_check_validator is not None) else
                module_factory_descriptor(_publish_engineer_joint_calculations, 'Engineer.joint_publication_runtime'),
            'joint_revision_publication': None if self.change_parameter_validator is None or self.change_revision_check_validator is None else
                module_factory_descriptor(publish_engineer_change_revision_calculations, 'Engineer.joint_revision_publication'),
            'review_checks': None if self.review_check_validator is None else {
                'validator': deepcopy(self.review_check_validator._declared),
                'method_registry_sha256': self.base.methods.content_digest,
                'provider': module_factory_descriptor(self.review_check_provider.project, 'Engineer.review_check_provider'),
                'producer': module_factory_descriptor(prepare_engineer_review_check_calculation, 'Engineer.review_check_producer'),
                'execution_runtime': module_factory_descriptor(_prepare_engineer_design_calculation, 'Engineer.review_check_execution_runtime'),
                'prepare_input': module_factory_descriptor(prepare_engineer_review_check_input, 'Engineer.review_check_prepare_input'),
                'source_schemas': module_factory_descriptor(engineer_review_schemas, 'Engineer.review_check_source_schemas'),
                'save_entry': module_factory_descriptor(self.review_check_assembler.save_check_calculation, 'Engineer.review_check_save_entry'),
                'save': module_factory_descriptor(self.review_check_publications.save, 'Engineer.review_check_save'),
                'publish': module_factory_descriptor(self.review_check_publications.publish, 'Engineer.review_check_publish'),
                'publish_many': module_factory_descriptor(self.review_check_publications.publish_many, 'Engineer.review_check_publish_many'),
                'read': module_factory_descriptor(self.review_check_publications.read, 'Engineer.review_check_read'),
                'validation': module_factory_descriptor(self.review_check_publications._validate, 'Engineer.review_check_validation'),
                'result_association': module_factory_descriptor(self.review_check_publications._result_matches_input, 'Engineer.review_check_result_association')},
            'research_checks': None if self.research_check_validator is None else {
                'validator': deepcopy(self.research_check_validator._declared),
                'method_registry_sha256': self.base.methods.content_digest,
                'provider': module_factory_descriptor(self.research_check_provider.project, 'Engineer.research_check_provider'),
                'producer': module_factory_descriptor(prepare_engineer_research_check_calculation, 'Engineer.research_check_producer'),
                'execution_runtime': module_factory_descriptor(_prepare_engineer_design_calculation, 'Engineer.research_check_execution_runtime'),
                'prepare_input': module_factory_descriptor(prepare_engineer_research_check_input, 'Engineer.research_check_prepare_input'),
                'source_schemas': module_factory_descriptor(engineer_research_schemas, 'Engineer.research_check_source_schemas'),
                'save_entry': module_factory_descriptor(self.research_check_assembler.save_check_calculation, 'Engineer.research_check_save_entry'),
                'save': module_factory_descriptor(self.research_check_publications.save, 'Engineer.research_check_save'),
                'publish': module_factory_descriptor(self.research_check_publications.publish, 'Engineer.research_check_publish'),
                'publish_many': module_factory_descriptor(self.research_check_publications.publish_many, 'Engineer.research_check_publish_many'),
                'read': module_factory_descriptor(self.research_check_publications.read, 'Engineer.research_check_read'),
                'validation': module_factory_descriptor(self.research_check_publications._validate, 'Engineer.research_check_validation'),
                'result_association': module_factory_descriptor(self.research_check_publications._result_matches_input, 'Engineer.research_check_result_association')},
            'research_estimates': None if self.research_estimate_validator is None else {
                'validator': deepcopy(self.research_estimate_validator._declared),
                'method_registry_sha256': self.base.methods.content_digest,
                'provider': module_factory_descriptor(self.research_estimate_provider.project, 'Engineer.research_estimate_provider'),
                'producer': module_factory_descriptor(prepare_engineer_research_estimate_calculation, 'Engineer.research_estimate_producer'),
                'execution_runtime': module_factory_descriptor(_prepare_engineer_design_calculation, 'Engineer.research_estimate_execution_runtime'),
                'prepare_input': module_factory_descriptor(prepare_engineer_research_estimate_input, 'Engineer.research_estimate_prepare_input'),
                'source_schemas': module_factory_descriptor(engineer_research_schemas, 'Engineer.research_estimate_source_schemas'),
                'save_entry': module_factory_descriptor(self.research_estimate_assembler.save_estimate_calculation, 'Engineer.research_estimate_save_entry'),
                'save': module_factory_descriptor(self.research_estimate_publications.save, 'Engineer.research_estimate_save'),
                'publish': module_factory_descriptor(self.research_estimate_publications.publish, 'Engineer.research_estimate_publish'),
                'publish_many': module_factory_descriptor(self.research_estimate_publications.publish_many, 'Engineer.research_estimate_publish_many'),
                'read': module_factory_descriptor(self.research_estimate_publications.read, 'Engineer.research_estimate_read'),
                'validation': module_factory_descriptor(self.research_estimate_publications._validate, 'Engineer.research_estimate_validation'),
                'result_report': module_factory_descriptor(self.research_estimate_publications._result_matches_report, 'Engineer.research_estimate_result_report'),
                'result_author': module_factory_descriptor(self.research_estimate_publications._result_author_matches, 'Engineer.research_estimate_result_author'),
                'result_association': module_factory_descriptor(self.research_estimate_publications._result_matches_input, 'Engineer.research_estimate_result_association')},
            'inspection_checks': None if self.inspection_check_validator is None else {
                'validator': deepcopy(self.inspection_check_validator._declared),
                'method_registry_sha256': self.base.methods.content_digest,
                'provider': module_factory_descriptor(self.inspection_check_provider.project, 'Engineer.inspection_check_provider'),
                'producer': module_factory_descriptor(prepare_engineer_inspection_check_calculation, 'Engineer.inspection_check_producer'),
                'execution_runtime': module_factory_descriptor(_prepare_engineer_design_calculation, 'Engineer.inspection_check_execution_runtime'),
                'prepare_input': module_factory_descriptor(prepare_engineer_inspection_check_input, 'Engineer.inspection_check_prepare_input'),
                'source_schemas': module_factory_descriptor(engineer_inspection_schemas, 'Engineer.inspection_check_source_schemas'),
                'save_entry': module_factory_descriptor(self.inspection_check_assembler.save_check_calculation, 'Engineer.inspection_check_save_entry'),
                'save': module_factory_descriptor(self.inspection_check_publications.save, 'Engineer.inspection_check_save'),
                'publish': module_factory_descriptor(self.inspection_check_publications.publish, 'Engineer.inspection_check_publish'),
                'publish_many': module_factory_descriptor(self.inspection_check_publications.publish_many, 'Engineer.inspection_check_publish_many'),
                'read': module_factory_descriptor(self.inspection_check_publications.read, 'Engineer.inspection_check_read'),
                'validation': module_factory_descriptor(self.inspection_check_publications._validate, 'Engineer.inspection_check_validation'),
                'result_association': module_factory_descriptor(self.inspection_check_publications._result_matches_input, 'Engineer.inspection_check_result_association')},
            'change_checks': None if self.change_check_validator is None else {
                'validator': deepcopy(self.change_check_validator._declared),
                'method_registry_sha256': self.base.methods.content_digest,
                'provider': module_factory_descriptor(self.change_check_provider.project, 'Engineer.change_check_provider'),
                'producer': module_factory_descriptor(prepare_engineer_change_check_calculation, 'Engineer.change_check_producer'),
                'execution_runtime': module_factory_descriptor(_prepare_engineer_design_calculation, 'Engineer.change_check_execution_runtime'),
                'prepare_input': module_factory_descriptor(prepare_engineer_change_check_input, 'Engineer.change_check_prepare_input'),
                'source_schemas': module_factory_descriptor(engineer_change_schemas, 'Engineer.change_check_source_schemas'),
                'save_entry': module_factory_descriptor(self.change_check_assembler.save_check_calculation, 'Engineer.change_check_save_entry'),
                'save': module_factory_descriptor(self.change_check_publications.save, 'Engineer.change_check_save'),
                'publish': module_factory_descriptor(self.change_check_publications.publish, 'Engineer.change_check_publish'),
                'publish_many': module_factory_descriptor(self.change_check_publications.publish_many, 'Engineer.change_check_publish_many'),
                'read': module_factory_descriptor(self.change_check_publications.read, 'Engineer.change_check_read'),
                'validation': module_factory_descriptor(self.change_check_publications._validate, 'Engineer.change_check_validation'),
                'result_association': module_factory_descriptor(self.change_check_publications._result_matches_input, 'Engineer.change_check_result_association')},
            'change_parameters': None if self.change_parameter_validator is None else {
                'validator': deepcopy(self.change_parameter_validator._declared),
                'method_registry_sha256': self.base.methods.content_digest,
                'provider': module_factory_descriptor(self.change_parameter_provider.project, 'Engineer.change_parameter_provider'),
                'producer': module_factory_descriptor(prepare_engineer_change_parameter_calculation, 'Engineer.change_parameter_producer'),
                'execution_runtime': module_factory_descriptor(_prepare_engineer_design_calculation, 'Engineer.change_parameter_execution_runtime'),
                'prepare_input': module_factory_descriptor(prepare_engineer_change_parameter_input, 'Engineer.change_parameter_prepare_input'),
                'source_schemas': module_factory_descriptor(engineer_change_schemas, 'Engineer.change_parameter_source_schemas'),
                'save_entry': module_factory_descriptor(self.change_parameter_assembler.save_parameter_calculation, 'Engineer.change_parameter_save_entry'),
                'save': module_factory_descriptor(self.change_parameter_publications.save, 'Engineer.change_parameter_save'),
                'publish': module_factory_descriptor(self.change_parameter_publications.publish, 'Engineer.change_parameter_publish'),
                'publish_many': module_factory_descriptor(self.change_parameter_publications.publish_many, 'Engineer.change_parameter_publish_many'),
                'read': module_factory_descriptor(self.change_parameter_publications.read, 'Engineer.change_parameter_read'),
                'validation': module_factory_descriptor(self.change_parameter_publications._validate, 'Engineer.change_parameter_validation'),
                'result_association': module_factory_descriptor(self.change_parameter_publications._result_matches_input, 'Engineer.change_parameter_result_association')},
            'change_revision_checks': None if self.change_revision_check_validator is None else {
                'validator': deepcopy(self.change_revision_check_validator._declared),
                'method_registry_sha256': self.base.methods.content_digest,
                'provider': module_factory_descriptor(self.provider.project, 'Engineer.change_revision_check_provider'),
                'producer': module_factory_descriptor(prepare_engineer_change_revision_check_calculation, 'Engineer.change_revision_check_producer'),
                'execution_runtime': module_factory_descriptor(_prepare_engineer_design_calculation, 'Engineer.change_revision_check_execution_runtime'),
                'prepare_input': module_factory_descriptor(prepare_engineer_change_revision_check_input, 'Engineer.change_revision_check_prepare_input'),
                'source_schemas': module_factory_descriptor(engineer_change_schemas, 'Engineer.change_revision_check_source_schemas'),
                'save_entry': module_factory_descriptor(self.change_revision_check_assembler.save_revision_check_calculation, 'Engineer.change_revision_check_save_entry'),
                'save': module_factory_descriptor(self.change_revision_check_publications.save, 'Engineer.change_revision_check_save'),
                'publish': module_factory_descriptor(self.change_revision_check_publications.publish, 'Engineer.change_revision_check_publish'),
                'publish_many': module_factory_descriptor(self.change_revision_check_publications.publish_many, 'Engineer.change_revision_check_publish_many'),
                'read': module_factory_descriptor(self.change_revision_check_publications.read, 'Engineer.change_revision_check_read'),
                'validation': module_factory_descriptor(self.change_revision_check_publications._validate, 'Engineer.change_revision_check_validation'),
                'result_association': module_factory_descriptor(self.change_revision_check_publications._result_matches_input, 'Engineer.change_revision_check_result_association')},
            'feedback_sha256': task_digest(self.feedback._declared) if self.feedback is not None else None,
            'feedback_validators': {name: module_factory_descriptor(callback, name) if callback is not None else None
                for name, callback in (('validate_feedback_relation', self.dependencies.validate_feedback_relation),
                    ('validate_feedback_read', self.dependencies.validate_feedback_read),
                    ('validate_feedback_input', self.dependencies.validate_feedback_input))},
            'submission_read_guard': module_factory_descriptor(self.dependencies.submission_read_guard, 'submission_read_guard')
                if self.dependencies.submission_read_guard is not None else None,
            'submission_callbacks': {action: {name: module_factory_descriptor(callback, name) if callback is not None else None
                for name, callback in vars(callbacks).items()}
                for action, callbacks in sorted(self.dependencies.submission_callbacks.items())}}

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
            raise TaskConflict('Original formal Engineer components or configuration changed, or application closed')
        recovery = self.dependencies.execution_recovery
        if self._receipt_recovery_components is None:
            if any(value is not None for value in (recovery, self.receipt_assembler,
                    self.receipt_reader, self.execution_dispatcher)):
                raise TaskConflict('Undeclared Engineer receipt recovery components were added')
        else:
            current = (recovery, *recovery.components(), self.receipt_assembler, self.receipt_reader,
                self.execution_dispatcher, self.feedback.inbox, self.provider)
            assembler = self.receipt_assembler
            expected = {
                'ENGINEER-A02': (EngineerIntakeRecoverySettings, EngineerIntakeRecoveryBindings,
                    EngineerIntakeActionAssembler, EngineerIntakeRecoveryReader),
                'ENGINEER-A04': (EngineerPlanningRecoverySettings, EngineerPlanningRecoveryBindings,
                    EngineerPlanningActionAssembler, EngineerPlanningRecoveryReader),
                'ENGINEER-A05': (EngineerDesignRecoverySettings, EngineerDesignRecoveryBindings,
                    EngineerDesignActionAssembler, EngineerDesignRecoveryReader),
                'ENGINEER-A08': (EngineerInspectionRecoverySettings, EngineerInspectionRecoveryBindings,
                    EngineerInspectionActionAssembler, EngineerInspectionRecoveryReader),
                'ENGINEER-A09': (EngineerChangeRecoverySettings, EngineerChangeRecoveryBindings,
                    EngineerChangeActionAssembler, EngineerChangeRecoveryReader),
                'ENGINEER-A10': (EngineerBillingRecoverySettings, EngineerBillingRecoveryBindings,
                    EngineerBillingActionAssembler, EngineerBillingRecoveryReader),
                'ENGINEER-A13': (EngineerResearchRecoverySettings, EngineerResearchRecoveryBindings,
                    EngineerResearchActionAssembler, EngineerResearchRecoveryReader),
                'ENGINEER-A07': (EngineerSubmissionRecoverySettings, EngineerSubmissionRecoveryBindings,
                    EngineerDeliverableActionAssembler, EngineerSubmissionReceiptReader),
                'ENGINEER-A12': (EngineerLearningRecoverySettings, EngineerLearningRecoveryBindings,
                    EngineerLearningActionAssembler, EngineerLearningReader),
                'ENGINEER-A11': (EngineerTransitionRecoverySettings, EngineerTransitionRecoveryBindings,
                    EngineerTransitionActionAssembler, EngineerTransitionReader),
            }.get(self.settings.action_id)
            if (expected is None or type(self.settings.execution_recovery) is not expected[0]
                    or type(recovery) is not expected[1] or not isinstance(assembler, expected[2])
                    or not isinstance(self.receipt_reader, expected[3]) or assembler.ACTION_ID != self.settings.action_id
                    or self.receipt_reader.assembler is not assembler
                    or self.receipt_reader.select_current is not recovery.select_current
                    or any(actual is not original for actual, original in zip(current, self._receipt_recovery_components))
                    or assembler.registry is not self.base.registry or assembler.organizations is not self.base.organizations
                    or assembler.provider is not self.provider or assembler.methods is not self.base.methods
                    or len(assembler.decision_strategies) != len(self.base.model_host.bindings)
                    or any(actual is not original for actual, original in zip(
                        assembler.decision_strategies, self.base.model_host.bindings))):
                raise TaskConflict('Engineer receipt recovery changed original source/model/recipient/callback bindings')
            if self.settings.action_id in {'ENGINEER-A02', 'ENGINEER-A04', 'ENGINEER-A05', 'ENGINEER-A08', 'ENGINEER-A09', 'ENGINEER-A10', 'ENGINEER-A11', 'ENGINEER-A12'} and self.receipt_reader.snapshots.store is not self.base.store:
                raise TaskConflict('Engineer learning recovery changed the original invocation journal')
            self.receipt_reader._check()
            self.execution_dispatcher._check()
        if any(actual is not original for actual, original in zip(
                (self.assessment_provider, self.assessment_validator, self.assessment_publications,
                    self.assessment_assembler, self.base.methods), self._assessment_components)):
            raise TaskConflict('Formal Engineer learning assessment components changed')
        if self.assessment_validator is not None:
            self.assessment_validator._check()
            validator, publications, assembler = self.assessment_validator, self.assessment_publications, self.assessment_assembler
            settings = self.settings.learning_assessment
            if (settings is None or validator.provider is not self.base.provider
                    or validator.registry is not self.base.registry or validator.organizations is not self.base.organizations
                    or validator._views.macro_version != settings.macro_version or validator._views.source_mode != 'formal'
                    or publications.store is not self.base.store or publications.registry is not self.base.registry
                    or publications.organizations is not self.base.organizations or publications.methods is not self.base.methods
                    or publications.validate_source != validator.validate_source
                    or self.assessment_provider.provider is not self.base.provider
                    or self.assessment_provider.publications is not publications
                    or assembler.provider is not self.base.provider or assembler.registry is not self.base.registry
                    or assembler.organizations is not self.base.organizations or assembler.methods is not self.base.methods
                    or assembler._views.provider is not self.base.provider
                    or assembler._views.organizations is not self.base.organizations
                    or assembler._views.macro_version != settings.macro_version or assembler._views.source_mode != 'formal'
                    or assembler.macro_version != settings.macro_version or assembler.source_mode != 'formal'
                    or assembler.policy_version != settings.policy_version or assembler.model_version != self.settings.model_version
                    or assembler.decision_strategies != tuple(self.base.model_host.bindings)):
                raise TaskConflict('Formal Engineer learning assessment source, versions or publication wiring changed')
        elif self.assessment_provider is not self.base.provider:
            raise TaskConflict('Unconfigured Engineer assessment replaced its original source provider')
        if any(actual is not original for actual, original in zip(
                (self.training_provider, self.training_validator, self.training_publications,
                    self.training_assembler, self.base.methods), self._training_components)):
            raise TaskConflict('Formal Engineer training estimate components changed')
        if self.training_validator is not None:
            self.training_validator._check()
            validator, publications, assembler = self.training_validator, self.training_publications, self.training_assembler
            settings = self.settings.training_estimates
            if (settings is None or validator.provider is not self.base.provider
                    or validator.registry is not self.base.registry or validator.organizations is not self.base.organizations
                    or validator._views.macro_version != settings.macro_version or validator._views.source_mode != 'formal'
                    or publications.store is not self.base.store or publications.registry is not self.base.registry
                    or publications.organizations is not self.base.organizations or publications.methods is not self.base.methods
                    or publications.validate_source != validator.validate_source
                    or self.training_provider.provider is not self.assessment_provider or self.training_provider.publications is not publications
                    or assembler.provider is not self.base.provider or assembler.registry is not self.base.registry
                    or assembler.organizations is not self.base.organizations or assembler.methods is not self.base.methods
                    or assembler._views.provider is not self.base.provider
                    or assembler._views.organizations is not self.base.organizations
                    or assembler._views.macro_version != settings.macro_version or assembler._views.source_mode != 'formal'
                    or assembler.macro_version != settings.macro_version or assembler.source_mode != 'formal'
                    or assembler.policy_version != settings.policy_version or assembler.model_version != self.settings.model_version
                    or assembler.decision_strategies != tuple(self.base.model_host.bindings)):
                raise TaskConflict('Formal Engineer training estimate source, versions or publication wiring changed')
        elif self.training_provider is not self.assessment_provider:
            raise TaskConflict('Unconfigured Engineer training estimate replaced its original source provider')
        if any(actual is not original for actual, original in zip(
                (self.parameter_provider, self.parameter_validator, self.parameter_publications,
                    self.parameter_assembler, self.base.methods), self._parameter_components)):
            raise TaskConflict('Formal Engineer parameter calculation components changed')
        if self.parameter_validator is not None:
            self.parameter_validator._check()
            validator, publications, assembler = self.parameter_validator, self.parameter_publications, self.parameter_assembler
            settings = self.settings.parameter_calculations
            if (settings is None or validator.provider is not self.base.provider
                    or validator.registry is not self.base.registry or validator.organizations is not self.base.organizations
                    or validator._views.macro_version != settings.macro_version or validator._views.source_mode != 'formal'
                    or publications.store is not self.base.store or publications.registry is not self.base.registry
                    or publications.organizations is not self.base.organizations or publications.methods is not self.base.methods
                    or publications.validate_source != validator.validate_source
                    or self.parameter_provider.provider is not self.training_provider or self.parameter_provider.publications is not publications
                    or assembler.provider is not self.base.provider or assembler.registry is not self.base.registry
                    or assembler.organizations is not self.base.organizations or assembler.methods is not self.base.methods
                    or assembler._views.provider is not self.base.provider
                    or assembler._views.organizations is not self.base.organizations
                    or assembler._views.macro_version != settings.macro_version or assembler._views.source_mode != 'formal'
                    or assembler.macro_version != settings.macro_version or assembler.source_mode != 'formal'
                    or assembler.policy_version != settings.policy_version or assembler.model_version != self.settings.model_version
                    or assembler.decision_strategies != tuple(self.base.model_host.bindings)):
                raise TaskConflict('Formal Engineer parameter sources, versions or publication wiring changed')
        elif self.parameter_provider is not self.training_provider:
            raise TaskConflict('Unconfigured Engineer parameter calculations replaced the original provider chain')
        if any(actual is not original for actual, original in zip(
                (self.interface_check_provider, self.check_validator, self.check_publications,
                    self.check_assembler, self.base.methods), self._check_components)):
            raise TaskConflict('Formal Engineer interface check calculation components changed')
        if self.check_validator is not None:
            self.check_validator._check()
            validator, publications, assembler = self.check_validator, self.check_publications, self.check_assembler
            settings = self.settings.interface_checks
            if (settings is None or validator.provider is not self.base.provider
                    or validator.registry is not self.base.registry or validator.organizations is not self.base.organizations
                    or validator._views.macro_version != settings.macro_version or validator._views.source_mode != 'formal'
                    or publications.store is not self.base.store or publications.registry is not self.base.registry
                    or publications.organizations is not self.base.organizations or publications.methods is not self.base.methods
                    or publications.validate_source != validator.validate_source
                    or self.interface_check_provider.provider is not self.parameter_provider
                    or self.interface_check_provider.publications is not publications
                    or assembler.provider is not self.base.provider or assembler.registry is not self.base.registry
                    or assembler.organizations is not self.base.organizations or assembler.methods is not self.base.methods
                    or assembler._views.provider is not self.base.provider
                    or assembler._views.organizations is not self.base.organizations
                    or assembler._views.macro_version != settings.macro_version or assembler._views.source_mode != 'formal'
                    or assembler.macro_version != settings.macro_version or assembler.source_mode != 'formal'
                    or assembler.policy_version != settings.policy_version or assembler.model_version != self.settings.model_version
                    or assembler.decision_strategies != tuple(self.base.model_host.bindings)):
                raise TaskConflict('Formal Engineer interface check sources, versions or publication wiring changed')
        elif self.interface_check_provider is not self.parameter_provider:
            raise TaskConflict('Unconfigured Engineer interface check calculations replaced the original provider chain')
        if any(actual is not original for actual, original in zip(
                (self.review_check_provider, self.review_check_validator, self.review_check_publications,
                    self.review_check_assembler, self.base.methods), self._review_check_components)):
            raise TaskConflict('Formal Engineer review check calculation components changed')
        if self.review_check_validator is not None:
            self.review_check_validator._check()
            validator, publications, assembler = self.review_check_validator, self.review_check_publications, self.review_check_assembler
            settings = self.settings.review_checks
            if (settings is None or validator.provider is not self.base.provider
                    or validator.registry is not self.base.registry or validator.organizations is not self.base.organizations
                    or validator._views.macro_version != settings.macro_version or validator._views.source_mode != 'formal'
                    or publications.store is not self.base.store or publications.registry is not self.base.registry
                    or publications.organizations is not self.base.organizations or publications.methods is not self.base.methods
                    or publications.validate_source != validator.validate_source
                    or self.review_check_provider.provider is not self.interface_check_provider or self.review_check_provider.publications is not publications
                    or assembler.provider is not self.base.provider or assembler.registry is not self.base.registry
                    or assembler.organizations is not self.base.organizations or assembler.methods is not self.base.methods
                    or assembler._views.provider is not self.base.provider
                    or assembler._views.organizations is not self.base.organizations
                    or assembler._views.macro_version != settings.macro_version or assembler._views.source_mode != 'formal'
                    or assembler.macro_version != settings.macro_version or assembler.source_mode != 'formal'
                    or assembler.policy_version != settings.policy_version or assembler.model_version != self.settings.model_version
                    or assembler.decision_strategies != tuple(self.base.model_host.bindings)):
                raise TaskConflict('Formal Engineer review check sources, versions or publication wiring changed')
        elif self.review_check_provider is not self.interface_check_provider:
            raise TaskConflict('Unconfigured Engineer review checks replaced the original provider chain')
        if any(actual is not original for actual, original in zip(
                (self.research_check_provider, self.research_check_validator, self.research_check_publications,
                    self.research_check_assembler, self.base.methods), self._research_check_components)):
            raise TaskConflict('Formal Engineer research check calculation components changed')
        if self.research_check_validator is not None:
            self.research_check_validator._check()
            validator, publications, assembler = self.research_check_validator, self.research_check_publications, self.research_check_assembler
            settings = self.settings.research_checks
            if (settings is None or validator.provider is not self.base.provider
                    or validator.registry is not self.base.registry or validator.organizations is not self.base.organizations
                    or validator._views.macro_version != settings.macro_version or validator._views.source_mode != 'formal'
                    or publications.store is not self.base.store or publications.registry is not self.base.registry
                    or publications.organizations is not self.base.organizations or publications.methods is not self.base.methods
                    or publications.validate_source != validator.validate_source
                    or self.research_check_provider.provider is not self.review_check_provider or self.research_check_provider.publications is not publications
                    or assembler.provider is not self.base.provider or assembler.registry is not self.base.registry
                    or assembler.organizations is not self.base.organizations or assembler.methods is not self.base.methods
                    or assembler._views.provider is not self.base.provider
                    or assembler._views.organizations is not self.base.organizations
                    or assembler._views.macro_version != settings.macro_version or assembler._views.source_mode != 'formal'
                    or assembler.macro_version != settings.macro_version or assembler.source_mode != 'formal'
                    or assembler.policy_version != settings.policy_version or assembler.model_version != self.settings.model_version
                    or assembler.decision_strategies != tuple(self.base.model_host.bindings)):
                raise TaskConflict('Formal Engineer research check sources, versions or publication wiring changed')
        elif self.research_check_provider is not self.review_check_provider:
            raise TaskConflict('Unconfigured Engineer research checks replaced the original provider chain')
        if any(actual is not original for actual, original in zip(
                (self.research_estimate_provider, self.research_estimate_validator, self.research_estimate_publications,
                    self.research_estimate_assembler, self.base.methods), self._research_estimate_components)):
            raise TaskConflict('Formal Engineer research estimate calculation components changed')
        if self.research_estimate_validator is not None:
            self.research_estimate_validator._check()
            validator, publications, assembler = self.research_estimate_validator, self.research_estimate_publications, self.research_estimate_assembler
            settings = self.settings.research_estimates
            if (settings is None or validator.provider is not self.base.provider
                    or validator.registry is not self.base.registry or validator.organizations is not self.base.organizations
                    or validator._views.macro_version != settings.macro_version or validator._views.source_mode != 'formal'
                    or publications.store is not self.base.store or publications.registry is not self.base.registry
                    or publications.organizations is not self.base.organizations or publications.methods is not self.base.methods
                    or publications.validate_source != validator.validate_source
                    or self.research_estimate_provider.provider is not self.research_check_provider or self.research_estimate_provider.publications is not publications
                    or assembler.provider is not self.base.provider or assembler.registry is not self.base.registry
                    or assembler.organizations is not self.base.organizations or assembler.methods is not self.base.methods
                    or assembler._views.provider is not self.base.provider
                    or assembler._views.organizations is not self.base.organizations
                    or assembler._views.macro_version != settings.macro_version or assembler._views.source_mode != 'formal'
                    or assembler.macro_version != settings.macro_version or assembler.source_mode != 'formal'
                    or assembler.policy_version != settings.policy_version or assembler.model_version != self.settings.model_version
                    or assembler.decision_strategies != tuple(self.base.model_host.bindings)):
                raise TaskConflict('Formal Engineer research estimate sources, versions or publication wiring changed')
        elif self.research_estimate_provider is not self.research_check_provider:
            raise TaskConflict('Unconfigured Engineer research estimates replaced the original provider chain')
        if any(actual is not original for actual, original in zip(
                (self.inspection_check_provider, self.inspection_check_validator, self.inspection_check_publications,
                    self.inspection_check_assembler, self.base.methods), self._inspection_check_components)):
            raise TaskConflict('Formal Engineer inspection check calculation components changed')
        if self.inspection_check_validator is not None:
            self.inspection_check_validator._check()
            validator, publications, assembler = self.inspection_check_validator, self.inspection_check_publications, self.inspection_check_assembler
            settings = self.settings.inspection_checks
            if (settings is None or validator.provider is not self.base.provider
                    or validator.registry is not self.base.registry or validator.organizations is not self.base.organizations
                    or validator._views.macro_version != settings.macro_version or validator._views.source_mode != 'formal'
                    or publications.store is not self.base.store or publications.registry is not self.base.registry
                    or publications.organizations is not self.base.organizations or publications.methods is not self.base.methods
                    or publications.validate_source != validator.validate_source
                    or self.inspection_check_provider.provider is not self.research_estimate_provider or self.inspection_check_provider.publications is not publications
                    or assembler.provider is not self.base.provider or assembler.registry is not self.base.registry
                    or assembler.organizations is not self.base.organizations or assembler.methods is not self.base.methods
                    or assembler._views.provider is not self.base.provider
                    or assembler._views.organizations is not self.base.organizations
                    or assembler._views.macro_version != settings.macro_version or assembler._views.source_mode != 'formal'
                    or assembler.macro_version != settings.macro_version or assembler.source_mode != 'formal'
                    or assembler.policy_version != settings.policy_version or assembler.model_version != self.settings.model_version
                    or assembler.decision_strategies != tuple(self.base.model_host.bindings)):
                raise TaskConflict('Formal Engineer inspection check sources, versions or publication wiring changed')
        elif self.inspection_check_provider is not self.research_estimate_provider:
            raise TaskConflict('Unconfigured Engineer inspection checks replaced the original provider chain')
        if any(actual is not original for actual, original in zip(
                (self.change_check_provider, self.change_check_validator, self.change_check_publications,
                    self.change_check_assembler, self.base.methods), self._change_check_components)):
            raise TaskConflict('Formal Engineer change check calculation components changed')
        if self.change_check_validator is not None:
            self.change_check_validator._check()
            validator, publications, assembler = self.change_check_validator, self.change_check_publications, self.change_check_assembler
            settings = self.settings.change_checks
            if (settings is None or validator.provider is not self.base.provider
                    or validator.registry is not self.base.registry or validator.organizations is not self.base.organizations
                    or validator._views.macro_version != settings.macro_version or validator._views.source_mode != 'formal'
                    or publications.store is not self.base.store or publications.registry is not self.base.registry
                    or publications.organizations is not self.base.organizations or publications.methods is not self.base.methods
                    or publications.validate_source != validator.validate_source
                    or self.change_check_provider.provider is not self.inspection_check_provider or self.change_check_provider.publications is not publications
                    or assembler.provider is not self.base.provider or assembler.registry is not self.base.registry
                    or assembler.organizations is not self.base.organizations or assembler.methods is not self.base.methods
                    or assembler._views.provider is not self.base.provider
                    or assembler._views.organizations is not self.base.organizations
                    or assembler._views.macro_version != settings.macro_version or assembler._views.source_mode != 'formal'
                    or assembler.macro_version != settings.macro_version or assembler.source_mode != 'formal'
                    or assembler.policy_version != settings.policy_version or assembler.model_version != self.settings.model_version
                    or assembler.decision_strategies != tuple(self.base.model_host.bindings)):
                raise TaskConflict('Formal Engineer change check sources, versions or publication wiring changed')
        elif self.change_check_provider is not self.inspection_check_provider:
            raise TaskConflict('Unconfigured Engineer change checks replaced the original provider chain')
        if any(actual is not original for actual, original in zip(
                (self.change_parameter_provider, self.change_parameter_validator, self.change_parameter_publications,
                    self.change_parameter_assembler, self.base.methods), self._change_parameter_components)):
            raise TaskConflict('Formal Engineer revision parameter calculation components changed')
        if self.change_parameter_validator is not None:
            self.change_parameter_validator._check()
            validator, publications, assembler = self.change_parameter_validator, self.change_parameter_publications, self.change_parameter_assembler
            settings = self.settings.change_parameters
            if (settings is None or validator.provider is not self.base.provider
                    or validator.registry is not self.base.registry or validator.organizations is not self.base.organizations
                    or validator._views.macro_version != settings.macro_version or validator._views.source_mode != 'formal'
                    or publications.store is not self.base.store or publications.registry is not self.base.registry
                    or publications.organizations is not self.base.organizations or publications.methods is not self.base.methods
                    or publications.validate_source != validator.validate_source
                    or self.change_parameter_provider.provider is not self.change_check_provider or self.change_parameter_provider.publications is not publications
                    or assembler.provider is not self.base.provider or assembler.registry is not self.base.registry
                    or assembler.organizations is not self.base.organizations or assembler.methods is not self.base.methods
                    or assembler._views.provider is not self.base.provider
                    or assembler._views.organizations is not self.base.organizations
                    or assembler._views.macro_version != settings.macro_version or assembler._views.source_mode != 'formal'
                    or assembler.macro_version != settings.macro_version or assembler.source_mode != 'formal'
                    or assembler.policy_version != settings.policy_version or assembler.model_version != self.settings.model_version
                    or assembler.decision_strategies != tuple(self.base.model_host.bindings)):
                raise TaskConflict('Formal Engineer revision parameter sources, versions or publication wiring changed')
        elif self.change_parameter_provider is not self.change_check_provider:
            raise TaskConflict('Unconfigured Engineer revision parameters replaced the original provider chain')
        if any(actual is not original for actual, original in zip(
                (self.provider, self.change_revision_check_validator, self.change_revision_check_publications,
                    self.change_revision_check_assembler, self.base.methods), self._change_revision_check_components)):
            raise TaskConflict('Formal Engineer revision interface check calculation components changed')
        if self.change_revision_check_validator is not None:
            self.change_revision_check_validator._check()
            validator, publications, assembler = self.change_revision_check_validator, self.change_revision_check_publications, self.change_revision_check_assembler
            settings = self.settings.change_revision_checks
            if (settings is None or validator.provider is not self.base.provider
                    or validator.registry is not self.base.registry or validator.organizations is not self.base.organizations
                    or validator._views.macro_version != settings.macro_version or validator._views.source_mode != 'formal'
                    or publications.store is not self.base.store or publications.registry is not self.base.registry
                    or publications.organizations is not self.base.organizations or publications.methods is not self.base.methods
                    or publications.validate_source != validator.validate_source
                    or self.provider.provider is not self.change_parameter_provider or self.provider.publications is not publications
                    or assembler.provider is not self.base.provider or assembler.registry is not self.base.registry
                    or assembler.organizations is not self.base.organizations or assembler.methods is not self.base.methods
                    or assembler._views.provider is not self.base.provider
                    or assembler._views.organizations is not self.base.organizations
                    or assembler._views.macro_version != settings.macro_version or assembler._views.source_mode != 'formal'
                    or assembler.macro_version != settings.macro_version or assembler.source_mode != 'formal'
                    or assembler.policy_version != settings.policy_version or assembler.model_version != self.settings.model_version
                    or assembler.decision_strategies != tuple(self.base.model_host.bindings)):
                raise TaskConflict('Formal Engineer revision interface check sources, versions or publication wiring changed')
        elif self.provider is not self.change_parameter_provider:
            raise TaskConflict('Unconfigured Engineer revision interface checks replaced the original provider chain')
        if self.submissions is not None:
            self.submissions._check()
            if (self.submissions.store is not self.base.store or self.submissions.registry is not self.base.registry
                    or self.submissions.read_guard is not self.dependencies.submission_read_guard
                    or any(self.submissions.callbacks[action] is not callback
                        for action, callback in self.dependencies.submission_callbacks.items())):
                raise TaskConflict('Formal Engineer submission components changed')
        if self.feedback is not None:
            self.feedback._check()
            if (self.feedback.host is not self.submissions
                    or self.feedback.validate_relation is not self.dependencies.validate_feedback_relation
                    or self.feedback.validate_read is not self.dependencies.validate_feedback_read):
                raise TaskConflict('Formal Engineer feedback components or validators changed')
        with self.base.store._lock:
            saved = self.base.store._db.execute('SELECT value FROM metadata WHERE key=?', (self._key,)).fetchone()
            if saved is None or json.loads(saved[0]) != self._declared:
                raise TaskConflict('Formal Engineer application configuration evidence changed')

    def evidence(self):
        self._check()
        actual = self.base.evidence()
        if not isinstance(actual, dict):
            raise ValueError('Formal Engineer source evidence must be an explicit object')
        return {'schema_version': self.VERSION, 'configuration_sha256': task_digest(self._declared),
            'source_mode': 'formal', 'status': 'configured_unverified', 'sources': deepcopy(actual),
            'submission': self.submissions.capabilities() if self.submissions is not None else None,
            'feedback_configured': self.feedback is not None,
            'execution_recovery_configured': self.execution_dispatcher is not None,
            'learning_assessment_configured': self.assessment_validator is not None,
            'training_estimates_configured': self.training_validator is not None,
            'parameter_calculations_configured': self.parameter_validator is not None,
            'interface_checks_configured': self.check_validator is not None,
            'review_checks_configured': self.review_check_validator is not None,
            'research_checks_configured': self.research_check_validator is not None,
            'research_estimates_configured': self.research_estimate_validator is not None,
            'inspection_checks_configured': self.inspection_check_validator is not None,
            'change_checks_configured': self.change_check_validator is not None,
            'change_parameters_configured': self.change_parameter_validator is not None,
            'change_revision_checks_configured': self.change_revision_check_validator is not None,
            'joint_revision_publication_configured': self.change_parameter_validator is not None
                and self.change_revision_check_validator is not None,
            'feedback_input_enabled': self.settings.feedback is not None and self.settings.feedback.input_enabled}

    def sources(self):
        self._check()
        enabled = self.settings.feedback is not None and self.settings.feedback.input_enabled
        return replace(self.base, version=self.VERSION,
            provider=self.provider,
            evidence=self.evidence,
            close=self.close,
            feedback=self.feedback if enabled else None,
            validate_feedback_input=self.dependencies.validate_feedback_input if enabled else None,
            save_learning_assessment=self.save_learning_assessment if self.assessment_validator is not None else None,
            publish_saved_learning_assessment=self.publish_saved_learning_assessment if self.assessment_validator is not None else None,
            save_training_estimate=self.save_training_estimate if self.training_validator is not None else None,
            publish_saved_training_estimate=self.publish_saved_training_estimate if self.training_validator is not None else None,
            save_parameter_calculation=self.save_parameter_calculation if self.parameter_validator is not None else None,
            publish_saved_parameter_calculations=self.publish_saved_parameter_calculations if self.parameter_validator is not None else None,
            save_interface_check_calculation=self.save_interface_check_calculation if self.check_validator is not None else None,
            publish_saved_interface_check_calculations=self.publish_saved_interface_check_calculations if self.check_validator is not None else None,
            save_review_check_calculation=self.save_review_check_calculation if self.review_check_validator is not None else None,
            publish_saved_review_check_calculations=self.publish_saved_review_check_calculations if self.review_check_validator is not None else None,
            save_research_check_calculation=self.save_research_check_calculation if self.research_check_validator is not None else None,
            publish_saved_research_check_calculations=self.publish_saved_research_check_calculations if self.research_check_validator is not None else None,
            save_inspection_check_calculation=self.save_inspection_check_calculation if self.inspection_check_validator is not None else None,
            publish_saved_inspection_check_calculations=self.publish_saved_inspection_check_calculations if self.inspection_check_validator is not None else None,
            save_change_check_calculation=self.save_change_check_calculation if self.change_check_validator is not None else None,
            publish_saved_change_check_calculations=self.publish_saved_change_check_calculations if self.change_check_validator is not None else None,
            save_change_parameter_calculation=self.save_change_parameter_calculation if self.change_parameter_validator is not None else None,
            publish_saved_change_parameter_calculations=self.publish_saved_change_parameter_calculations if self.change_parameter_validator is not None else None,
            save_change_revision_check_calculation=self.save_change_revision_check_calculation if self.change_revision_check_validator is not None else None,
            publish_saved_change_revision_check_calculations=self.publish_saved_change_revision_check_calculations if self.change_revision_check_validator is not None else None,
            save_research_estimate_calculation=self.save_research_estimate_calculation if self.research_estimate_validator is not None else None,
            publish_saved_research_estimate_calculations=self.publish_saved_research_estimate_calculations if self.research_estimate_validator is not None else None,
            publish_saved_design_calculations=self.publish_saved_design_calculations
                if self.parameter_validator is not None and self.check_validator is not None else None,
            publish_saved_change_revision_calculations=self.publish_saved_change_revision_calculations
                if self.change_parameter_validator is not None and self.change_revision_check_validator is not None else None)

    def publish_saved_change_revision_calculations(self, *, parameter_record_sha256s, check_record_sha256s,
            source_context, next_context):
        """Publish complete A09 revision results atomically under the source guard."""
        self._check()
        if self.change_parameter_publications is None or self.change_revision_check_publications is None:
            raise ValueError('Joint revision publication requires configured A09 parameter and check chains')
        source = ActionContext.model_validate(source_context).model_copy(deep=True)
        next_context = ActionContext.model_validate(next_context).model_copy(deep=True)
        with self.base.read_guard(source.model_copy(deep=True)):
            self._check()
            result = publish_engineer_change_revision_calculations(parameters=self.change_parameter_publications,
                checks=self.change_revision_check_publications, parameter_record_sha256s=parameter_record_sha256s,
                check_record_sha256s=check_record_sha256s, source_context=source, next_context=next_context)
            self._check()
            return result

    def publish_saved_design_calculations(self, *, parameter_record_sha256s, check_record_sha256s,
            source_context, next_context):
        """Publish complete mixed A05 results atomically under the actual source guard."""
        self._check()
        if self.parameter_publications is None or self.check_publications is None:
            raise ValueError('Joint design publication requires configured parameter and check chains')
        source = ActionContext.model_validate(source_context).model_copy(deep=True)
        next_context = ActionContext.model_validate(next_context).model_copy(deep=True)
        with self.base.read_guard(source.model_copy(deep=True)):
            self._check()
            result = publish_engineer_design_calculations(parameters=self.parameter_publications,
                checks=self.check_publications, parameter_record_sha256s=parameter_record_sha256s,
                check_record_sha256s=check_record_sha256s, source_context=source, next_context=next_context)
            self._check()
            return result

    def save_parameter_calculation(self, context, *, preparation, author_authority_ref, **source_refs):
        """Save one original parameter result without compiling a professional design."""
        self._check()
        if self.parameter_assembler is None:
            raise ValueError('No Engineer parameter calculation persistence is configured')
        context = ActionContext.model_validate(context).model_copy(deep=True)
        result = self.parameter_assembler.save_parameter_calculation(context, publications=self.parameter_publications,
            read_guard=self.base.read_guard, preparation=preparation, author_authority_ref=author_authority_ref,
            validate_current=self.parameter_validator.validate_current, **source_refs)
        self._check()
        return result

    def publish_saved_parameter_calculations(self, record_sha256s, *, source_context, next_context):
        """Publish saved parameter results together at a fresh authorized read point."""
        self._check()
        if self.parameter_publications is None:
            raise ValueError('No Engineer parameter calculation publication is configured')
        source = ActionContext.model_validate(source_context).model_copy(deep=True)
        next_context = ActionContext.model_validate(next_context).model_copy(deep=True)
        with self.base.read_guard(source.model_copy(deep=True)):
            self._check()
            result = self.parameter_publications.publish_many(record_sha256s,
                source_context=source, next_context=next_context)
            self._check()
            return result

    def save_interface_check_calculation(self, context, *, preparation, author_authority_ref, **source_refs):
        """Save one original interface-check result without compiling a professional design."""
        self._check()
        if self.check_assembler is None:
            raise ValueError('No Engineer interface-check persistence is configured')
        context = ActionContext.model_validate(context).model_copy(deep=True)
        result = self.check_assembler.save_interface_check_calculation(context, publications=self.check_publications,
            read_guard=self.base.read_guard, preparation=preparation, author_authority_ref=author_authority_ref,
            validate_current=self.check_validator.validate_current, **source_refs)
        self._check()
        return result

    def publish_saved_interface_check_calculations(self, record_sha256s, *, source_context, next_context):
        """Publish saved interface-check results together at a fresh authorized read point."""
        self._check()
        if self.check_publications is None:
            raise ValueError('No Engineer interface-check publication is configured')
        source = ActionContext.model_validate(source_context).model_copy(deep=True)
        next_context = ActionContext.model_validate(next_context).model_copy(deep=True)
        with self.base.read_guard(source.model_copy(deep=True)):
            self._check()
            result = self.check_publications.publish_many(record_sha256s,
                source_context=source, next_context=next_context)
            self._check()
            return result

    def save_review_check_calculation(self, context, *, preparation, author_authority_ref, **source_refs):
        """Save an original A06 check under its current reviewer/source guard."""
        self._check()
        if self.review_check_assembler is None:
            raise ValueError('No Engineer review-check persistence is configured')
        context = ActionContext.model_validate(context).model_copy(deep=True)
        result = self.review_check_assembler.save_check_calculation(context, publications=self.review_check_publications,
            read_guard=self.base.read_guard, preparation=preparation, author_authority_ref=author_authority_ref,
            validate_current=self.review_check_validator.validate_current, **source_refs)
        self._check()
        return result

    def publish_saved_review_check_calculations(self, record_sha256s, *, source_context, next_context):
        """Publish retained A06 checks together at a fresh authorized read token."""
        self._check()
        if self.review_check_publications is None:
            raise ValueError('No Engineer review-check publication is configured')
        source = ActionContext.model_validate(source_context).model_copy(deep=True)
        next_context = ActionContext.model_validate(next_context).model_copy(deep=True)
        with self.base.read_guard(source.model_copy(deep=True)):
            self._check()
            result = self.review_check_publications.publish_many(record_sha256s,
                source_context=source, next_context=next_context)
            self._check()
            return result

    def save_research_check_calculation(self, context, *, preparation, author_authority_ref, **source_refs):
        """Save an original A13 check under its current delegate/source guard."""
        self._check()
        if self.research_check_assembler is None:
            raise ValueError('No Engineer research-check persistence is configured')
        context = ActionContext.model_validate(context).model_copy(deep=True)
        result = self.research_check_assembler.save_check_calculation(context, publications=self.research_check_publications,
            read_guard=self.base.read_guard, preparation=preparation, author_authority_ref=author_authority_ref,
            validate_current=self.research_check_validator.validate_current, **source_refs)
        self._check()
        return result

    def publish_saved_research_check_calculations(self, record_sha256s, *, source_context, next_context):
        """Publish retained A13 checks together at a fresh authorized read token."""
        self._check()
        if self.research_check_publications is None:
            raise ValueError('No Engineer research-check publication is configured')
        source = ActionContext.model_validate(source_context).model_copy(deep=True)
        next_context = ActionContext.model_validate(next_context).model_copy(deep=True)
        with self.base.read_guard(source.model_copy(deep=True)):
            self._check()
            result = self.research_check_publications.publish_many(record_sha256s,
                source_context=source, next_context=next_context)
            self._check()
            return result

    def save_research_estimate_calculation(self, context, *, preparation, author_authority_ref, **source_refs):
        """Save an original A13 check under its current delegate/source guard."""
        self._check()
        if self.research_estimate_assembler is None:
            raise ValueError('No Engineer research-estimate persistence is configured')
        context = ActionContext.model_validate(context).model_copy(deep=True)
        result = self.research_estimate_assembler.save_estimate_calculation(context, publications=self.research_estimate_publications,
            read_guard=self.base.read_guard, preparation=preparation, author_authority_ref=author_authority_ref,
            validate_current=self.research_estimate_validator.validate_current, **source_refs)
        self._check()
        return result

    def publish_saved_research_estimate_calculations(self, record_sha256s, *, source_context, next_context):
        """Publish retained A13 estimates together at a fresh authorized read token."""
        self._check()
        if self.research_estimate_publications is None:
            raise ValueError('No Engineer research-estimate publication is configured')
        source = ActionContext.model_validate(source_context).model_copy(deep=True)
        next_context = ActionContext.model_validate(next_context).model_copy(deep=True)
        with self.base.read_guard(source.model_copy(deep=True)):
            self._check()
            result = self.research_estimate_publications.publish_many(record_sha256s,
                source_context=source, next_context=next_context)
            self._check()
            return result

    def save_inspection_check_calculation(self, context, *, preparation, author_authority_ref, **source_refs):
        """Save an original A08 check under its current executor/source guard."""
        self._check()
        if self.inspection_check_assembler is None:
            raise ValueError('No Engineer inspection-check persistence is configured')
        context = ActionContext.model_validate(context).model_copy(deep=True)
        result = self.inspection_check_assembler.save_check_calculation(context, publications=self.inspection_check_publications,
            read_guard=self.base.read_guard, preparation=preparation, author_authority_ref=author_authority_ref,
            validate_current=self.inspection_check_validator.validate_current, **source_refs)
        self._check()
        return result

    def publish_saved_inspection_check_calculations(self, record_sha256s, *, source_context, next_context):
        """Publish retained A08 checks together at a fresh authorized read token."""
        self._check()
        if self.inspection_check_publications is None:
            raise ValueError('No Engineer inspection-check publication is configured')
        source = ActionContext.model_validate(source_context).model_copy(deep=True)
        next_context = ActionContext.model_validate(next_context).model_copy(deep=True)
        with self.base.read_guard(source.model_copy(deep=True)):
            self._check()
            result = self.inspection_check_publications.publish_many(record_sha256s,
                source_context=source, next_context=next_context)
            self._check()
            return result

    def save_change_check_calculation(self, context, *, preparation, author_authority_ref, **source_refs):
        """Save an original A09 check under its current author/source guard."""
        self._check()
        if self.change_check_assembler is None:
            raise ValueError('No Engineer change-check persistence is configured')
        context = ActionContext.model_validate(context).model_copy(deep=True)
        result = self.change_check_assembler.save_check_calculation(context, publications=self.change_check_publications,
            read_guard=self.base.read_guard, preparation=preparation, author_authority_ref=author_authority_ref,
            validate_current=self.change_check_validator.validate_current, **source_refs)
        self._check()
        return result

    def publish_saved_change_check_calculations(self, record_sha256s, *, source_context, next_context):
        """Publish retained A09 checks together at a fresh authorized read token."""
        self._check()
        if self.change_check_publications is None:
            raise ValueError('No Engineer change-check publication is configured')
        source = ActionContext.model_validate(source_context).model_copy(deep=True)
        next_context = ActionContext.model_validate(next_context).model_copy(deep=True)
        with self.base.read_guard(source.model_copy(deep=True)):
            self._check()
            result = self.change_check_publications.publish_many(record_sha256s,
                source_context=source, next_context=next_context)
            self._check()
            return result

    def save_change_parameter_calculation(self, context, *, preparation, author_authority_ref, **source_refs):
        """Save an original A09 parameter under its current author/source guard."""
        self._check()
        if self.change_parameter_assembler is None:
            raise ValueError('No Engineer revision-parameter persistence is configured')
        context = ActionContext.model_validate(context).model_copy(deep=True)
        result = self.change_parameter_assembler.save_parameter_calculation(context, publications=self.change_parameter_publications,
            read_guard=self.base.read_guard, preparation=preparation, author_authority_ref=author_authority_ref,
            validate_current=self.change_parameter_validator.validate_current, **source_refs)
        self._check()
        return result

    def publish_saved_change_parameter_calculations(self, record_sha256s, *, source_context, next_context):
        """Publish retained A09 parameters together at a fresh authorized read token."""
        self._check()
        if self.change_parameter_publications is None:
            raise ValueError('No Engineer revision-parameter publication is configured')
        source = ActionContext.model_validate(source_context).model_copy(deep=True)
        next_context = ActionContext.model_validate(next_context).model_copy(deep=True)
        with self.base.read_guard(source.model_copy(deep=True)):
            self._check()
            result = self.change_parameter_publications.publish_many(record_sha256s,
                source_context=source, next_context=next_context)
            self._check()
            return result

    def save_change_revision_check_calculation(self, context, *, preparation, author_authority_ref, **source_refs):
        """Save an original A09 revision check under its current author/source guard."""
        self._check()
        if self.change_revision_check_assembler is None:
            raise ValueError('No Engineer revision-check persistence is configured')
        context = ActionContext.model_validate(context).model_copy(deep=True)
        result = self.change_revision_check_assembler.save_revision_check_calculation(context, publications=self.change_revision_check_publications,
            read_guard=self.base.read_guard, preparation=preparation, author_authority_ref=author_authority_ref,
            validate_current=self.change_revision_check_validator.validate_current, **source_refs)
        self._check()
        return result

    def publish_saved_change_revision_check_calculations(self, record_sha256s, *, source_context, next_context):
        """Publish retained A09 revision checks together at a fresh authorized read token."""
        self._check()
        if self.change_revision_check_publications is None:
            raise ValueError('No Engineer revision-check publication is configured')
        source = ActionContext.model_validate(source_context).model_copy(deep=True)
        next_context = ActionContext.model_validate(next_context).model_copy(deep=True)
        with self.base.read_guard(source.model_copy(deep=True)):
            self._check()
            result = self.change_revision_check_publications.publish_many(record_sha256s,
                source_context=source, next_context=next_context)
            self._check()
            return result

    def save_training_estimate(self, context, *, estimate_ref, author_authority_ref, **source_refs):
        """Save one original work estimate using independently checked sources."""
        self._check()
        if self.training_assembler is None:
            raise ValueError('No Engineer training estimate persistence is configured')
        context = ActionContext.model_validate(context).model_copy(deep=True)
        result = self.training_assembler.save_training_estimate(context, publications=self.training_publications,
            read_guard=self.base.read_guard, estimate_ref=estimate_ref, author_authority_ref=author_authority_ref,
            validate_current=self.training_validator.validate_current, **source_refs)
        self._check()
        return result

    def publish_saved_training_estimate(self, record_sha256, *, source_context, next_context):
        """Publish an already saved estimate under a fresh authorized read token."""
        self._check()
        if self.training_publications is None:
            raise ValueError('No Engineer training estimate publication is configured')
        source = ActionContext.model_validate(source_context).model_copy(deep=True)
        next_context = ActionContext.model_validate(next_context).model_copy(deep=True)
        with self.base.read_guard(source.model_copy(deep=True)):
            self._check()
            result = self.training_publications.publish(record_sha256, source_context=source, next_context=next_context)
            self._check()
            return result

    def save_learning_assessment(self, context, *, assessment_ref, author_authority_ref, **source_refs):
        """Save one finite-rule assessment using independently checked actual sources."""
        self._check()
        if self.assessment_assembler is None:
            raise ValueError('No Engineer learning assessment persistence is configured')
        context = ActionContext.model_validate(context).model_copy(deep=True)
        result = self.assessment_assembler.save_assessment(context, publications=self.assessment_publications,
            read_guard=self.base.read_guard, assessment_ref=assessment_ref, author_authority_ref=author_authority_ref,
            validate_current=self.assessment_validator.validate_current, **source_refs)
        self._check()
        return result

    def publish_saved_learning_assessment(self, record_sha256, *, source_context, next_context):
        """Publish an already saved assessment under a fresh authorized read token."""
        self._check()
        if self.assessment_publications is None:
            raise ValueError('No Engineer learning assessment publication is configured')
        source = ActionContext.model_validate(source_context).model_copy(deep=True)
        next_context = ActionContext.model_validate(next_context).model_copy(deep=True)
        with self.base.read_guard(source.model_copy(deep=True)):
            self._check()
            result = self.assessment_publications.publish(record_sha256, source_context=source, next_context=next_context)
            self._check()
            return result

    def _dispatch_submission(self, identity, operation):
        self._check()
        if self.submissions is None:
            raise ValueError('No actual Engineer submission routes are configured')
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
        """Explicitly evaluate original A07 receipts and queue independently checked judgment."""
        self._check()
        if self.execution_dispatcher is None:
            raise ValueError('No Engineer original submission receipt recovery is configured')
        result = self.execution_dispatcher(run_id=run_id, organization_id=organization_id)
        self._check()
        return result

    def wait_recovery_sources(self, *, identity, journal_path):
        """Expose the same A07 journal and protected callbacks to selected V7 waits."""
        self._check()
        if self.execution_dispatcher is None:
            raise ValueError('No Engineer original submission receipt recovery is configured')
        result = self.execution_dispatcher.wait_recovery_sources(identity=identity, journal_path=journal_path,
            check_application=self._check, close=self.close)
        self._check()
        return result

    def record_feedback(self, identity, *, context, reading, observation):
        """Explicitly correlate actual feedback under current source/authorization guard."""
        self._check()
        if self.feedback is None:
            raise ValueError('No Engineer actual feedback inbox is configured')
        context = ActionContext.model_validate(context).model_copy(deep=True)
        with self.base.read_guard(context.model_copy(deep=True)):
            self._check()
            result = self.feedback.record(identity, context=context, reading=reading, observation=observation)
            self._check()
            return result

    def reconcile_billing_internal_cost(self, identity, *, signal):
        """Archive independently posted native costs while preserving fees, cash and debts."""
        from integration.engineer_billing_terminal import reconcile_engineer_billing_internal_cost
        self._check()
        settings = self.settings.execution_recovery
        if (self.settings.action_id != 'ENGINEER-A10' or not isinstance(settings, EngineerBillingRecoverySettings)
                or not settings.terminal_internal_cost_enabled or self.execution_dispatcher is None):
            raise ValueError('Internal cost archival requires explicit A10 native accounting configuration')
        recovery = self.dependencies.execution_recovery
        with recovery.read_guard(run_id=identity.run_id, organization_id=identity.organization_id):
            self._check()
            result = reconcile_engineer_billing_internal_cost(identity=identity, signal=signal,
                reader=self.receipt_reader, dispatcher=self.execution_dispatcher.dispatcher,
                validate_relation=recovery.validate_relation)
            self._check()
            return result

    def reconcile_billing_receipts(self, identity, *, signal):
        """Archive actually covered A10 reminder waits without writing cash or another fee."""
        from integration.engineer_billing_terminal import reconcile_engineer_billing_receipts
        self._check()
        settings = self.settings.execution_recovery
        if (self.settings.action_id != 'ENGINEER-A10' or not isinstance(settings, EngineerBillingRecoverySettings)
                or not settings.terminal_receipt_enabled or self.execution_dispatcher is None):
            raise ValueError('Fee receipt archival requires explicit A10 terminal configuration')
        recovery = self.dependencies.execution_recovery
        with recovery.read_guard(run_id=identity.run_id, organization_id=identity.organization_id):
            self._check()
            result = reconcile_engineer_billing_receipts(identity=identity, signal=signal,
                reader=self.receipt_reader, dispatcher=self.execution_dispatcher.dispatcher,
                validate_relation=recovery.validate_relation)
            self._check()
            return result

    def reconcile_billing_claim(self, identity, *, signal):
        """Archive actual existing A10 fee status without another claim or cash settlement."""
        from integration.engineer_billing_terminal import reconcile_engineer_billing_claim
        self._check()
        settings = self.settings.execution_recovery
        if (self.settings.action_id != 'ENGINEER-A10' or not isinstance(settings, EngineerBillingRecoverySettings)
                or not settings.terminal_claim_enabled or self.execution_dispatcher is None):
            raise ValueError('Fee claim archival requires explicit A10 terminal configuration')
        recovery = self.dependencies.execution_recovery
        with recovery.read_guard(run_id=identity.run_id, organization_id=identity.organization_id):
            self._check()
            result = reconcile_engineer_billing_claim(identity=identity, signal=signal,
                reader=self.receipt_reader, dispatcher=self.execution_dispatcher.dispatcher,
                validate_relation=recovery.validate_relation)
            self._check()
            return result

    def reconcile_change_submission(self, identity, *, signal):
        """Archive observed original revision registration status without another production."""
        from integration.engineer_change_submission_terminal import reconcile_engineer_change_submission
        self._check()
        settings = self.settings.execution_recovery
        if (self.settings.action_id != 'ENGINEER-A09' or not isinstance(settings, EngineerChangeRecoverySettings)
                or not settings.terminal_submission_enabled or self.execution_dispatcher is None):
            raise ValueError('Revision submission archival requires explicit A09 terminal configuration')
        recovery = self.dependencies.execution_recovery
        with recovery.read_guard(run_id=identity.run_id, organization_id=identity.organization_id):
            self._check()
            result = reconcile_engineer_change_submission(identity=identity, signal=signal,
                reader=self.receipt_reader, dispatcher=self.execution_dispatcher.dispatcher,
                validate_relation=recovery.validate_relation)
            self._check()
            return result

    def reconcile_change_author_handoff(self, identity, *, signal):
        """Archive native acceptance of separate author work while retaining original duties."""
        from integration.engineer_change_author_terminal import reconcile_engineer_change_author_handoff
        self._check()
        settings = self.settings.execution_recovery
        if (self.settings.action_id != 'ENGINEER-A09' or not isinstance(settings, EngineerChangeRecoverySettings)
                or not settings.terminal_author_handoff_enabled or self.execution_dispatcher is None):
            raise ValueError('Author handoff archival requires explicit A09 terminal configuration')
        recovery = self.dependencies.execution_recovery
        with recovery.read_guard(run_id=identity.run_id, organization_id=identity.organization_id):
            self._check()
            result = reconcile_engineer_change_author_handoff(identity=identity, signal=signal,
                reader=self.receipt_reader, dispatcher=self.execution_dispatcher.dispatcher,
                validate_relation=recovery.validate_relation)
            self._check()
            return result

    def reconcile_inspection_investment(self, identity, *, signal):
        """Archive actual fully invested A08 planning waits without certifying inspection completion."""
        from integration.engineer_inspection_terminal import reconcile_engineer_inspection_investment
        self._check()
        settings = self.settings.execution_recovery
        if (self.settings.action_id != 'ENGINEER-A08' or not isinstance(settings, EngineerInspectionRecoverySettings)
                or not settings.terminal_investment_enabled or self.execution_dispatcher is None):
            raise ValueError('Inspection investment archival requires explicit A08 terminal configuration')
        recovery = self.dependencies.execution_recovery
        with recovery.read_guard(run_id=identity.run_id, organization_id=identity.organization_id):
            self._check()
            result = reconcile_engineer_inspection_investment(identity=identity, signal=signal,
                reader=self.receipt_reader, dispatcher=self.execution_dispatcher.dispatcher,
                validate_relation=recovery.validate_relation)
            self._check()
            return result

    def reconcile_design_submission(self, identity, *, signal):
        """Archive observed original A05 registration status without repeating professional production."""
        from integration.engineer_design_terminal import reconcile_engineer_design_submission
        self._check()
        settings = self.settings.execution_recovery
        if (self.settings.action_id != 'ENGINEER-A05' or not isinstance(settings, EngineerDesignRecoverySettings)
                or not settings.terminal_submission_enabled or self.execution_dispatcher is None):
            raise ValueError('Professional submission archival requires explicit A05 terminal configuration')
        recovery = self.dependencies.execution_recovery
        with recovery.read_guard(run_id=identity.run_id, organization_id=identity.organization_id):
            self._check()
            result = reconcile_engineer_design_submission(identity=identity, signal=signal,
                reader=self.receipt_reader, dispatcher=self.execution_dispatcher.dispatcher,
                validate_relation=recovery.validate_relation)
            self._check()
            return result

    def reconcile_transition_execution(self, identity, *, signal):
        """Archive actual same-business A11 disposition without repeating engineering work."""
        from integration.engineer_transition_terminal import reconcile_engineer_transition_execution
        self._check()
        settings = self.settings.execution_recovery
        if (self.settings.action_id != 'ENGINEER-A11' or not isinstance(settings, EngineerTransitionRecoverySettings)
                or not settings.terminal_execution_enabled or self.execution_dispatcher is None):
            raise ValueError('Engineering service reconciliation requires explicit A11 terminal configuration')
        recovery = self.dependencies.execution_recovery
        with recovery.read_guard(run_id=identity.run_id, organization_id=identity.organization_id):
            self._check()
            result = reconcile_engineer_transition_execution(identity=identity, signal=signal,
                reader=self.receipt_reader, dispatcher=self.execution_dispatcher.dispatcher,
                validate_relation=recovery.validate_relation)
            self._check()
            return result

    def reconcile_learning_execution(self, identity, *, signal):
        """Archive the actual original A12 execution under the same source/authority guard."""
        from integration.engineer_learning_terminal import reconcile_engineer_learning_execution
        self._check()
        settings = self.settings.execution_recovery
        if (self.settings.action_id != 'ENGINEER-A12' or not isinstance(settings, EngineerLearningRecoverySettings)
                or not settings.terminal_execution_enabled or self.execution_dispatcher is None):
            raise ValueError('Engineer execution reconciliation requires explicit A12 terminal configuration')
        recovery = self.dependencies.execution_recovery
        with recovery.read_guard(run_id=identity.run_id, organization_id=identity.organization_id):
            self._check()
            result = reconcile_engineer_learning_execution(identity=identity, signal=signal,
                reader=self.receipt_reader, dispatcher=self.execution_dispatcher.dispatcher,
                validate_relation=recovery.validate_relation)
            self._check()
            return result

    def read_feedback(self, *, context, reading):
        """Read original persisted feedback under current recipient/scope authority."""
        self._check()
        if self.feedback is None:
            raise ValueError('No Engineer actual feedback inbox is configured')
        context = ActionContext.model_validate(context).model_copy(deep=True)
        with self.base.read_guard(context.model_copy(deep=True)):
            self._check()
            result = self.feedback.read(context=context, reading=reading)
            self._check()
            return result

    def reconcile_applied_feedback(self, identity, *, signal):
        """Archive actual original feedback application while preserving issuer credentials."""
        from integration.engineer_learning_terminal import reconcile_engineer_applied_feedback
        self._check()
        settings = self.settings.execution_recovery
        if (self.settings.action_id != 'ENGINEER-A12' or not isinstance(settings, EngineerLearningRecoverySettings)
                or not settings.terminal_applied_feedback_enabled or self.execution_dispatcher is None):
            raise ValueError('Engineer applied-feedback reconciliation requires explicit A12 terminal configuration')
        recovery = self.dependencies.execution_recovery
        with recovery.read_guard(run_id=identity.run_id, organization_id=identity.organization_id):
            self._check()
            result = reconcile_engineer_applied_feedback(identity=identity, signal=signal,
                reader=self.receipt_reader, dispatcher=self.execution_dispatcher.dispatcher,
                validate_relation=recovery.validate_relation)
            self._check()
            return result

    def close(self):
        if not self._closed:
            self._closed = True
            self.base.close()

    def reconcile_qualification_application(self, identity, *, signal):
        """Archive actual issuer application of the original event under the source guard."""
        from integration.engineer_learning_terminal import reconcile_engineer_qualification_application
        self._check()
        settings = self.settings.execution_recovery
        if (self.settings.action_id != 'ENGINEER-A12' or not isinstance(settings, EngineerLearningRecoverySettings)
                or not settings.terminal_qualification_enabled or self.execution_dispatcher is None):
            raise ValueError('Qualification reconciliation requires explicit Engineer A12 terminal configuration')
        recovery = self.dependencies.execution_recovery
        with recovery.read_guard(run_id=identity.run_id, organization_id=identity.organization_id):
            self._check()
            result = reconcile_engineer_qualification_application(identity=identity, signal=signal,
                reader=self.receipt_reader, dispatcher=self.execution_dispatcher.dispatcher,
                validate_relation=recovery.validate_relation)
            self._check()
            return result


def build_sources(*, request, output_directory, offline, settings):
    """role_contract source factory; no source, credential or model construction."""
    config = EngineerFormalApplicationSettings.model_validate(settings).model_copy(deep=True)
    request = RoleContractInvocation.model_validate(request).model_copy(deep=True)
    if (offline is not False or request.context.execution_mode != 'llm'
            or request.context.contract_ref.id != config.action_id or config.action_id not in _ACTIONS):
        raise ValueError('Formal Engineer source factory requires its explicit non-offline original invocation')
    factory = _load_factory(config.dependency_factory)
    descriptor = module_factory_descriptor(factory, config.dependency_factory)
    dependencies = factory(request=request.model_copy(deep=True), output_directory=Path(output_directory),
        offline=False, settings=deepcopy(config.dependency_settings))
    if not isinstance(dependencies, EngineerFormalApplicationDependencies):
        raise ValueError('Actual Engineer dependency factory must return EngineerFormalApplicationDependencies')
    application = None
    try:
        if module_factory_descriptor(factory, config.dependency_factory) != descriptor:
            raise TaskConflict('Actual Engineer dependency factory changed during assembly')
        application = EngineerFormalApplication(request=request, settings=config,
            dependencies=dependencies, factory_descriptor=descriptor)
        return application.sources()
    except Exception:
        if application is not None:
            application.close()
        else:
            dependencies.sources.close()
        raise
