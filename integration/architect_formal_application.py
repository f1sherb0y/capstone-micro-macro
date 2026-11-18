"""Configured formal Architect application assembly over original actual dependencies."""
from copy import deepcopy
from dataclasses import dataclass, field, replace
import importlib
import json
from pathlib import Path
from typing import Callable
from pydantic import model_validator

from integration.module_host import module_factory_descriptor
from integration.observations import ObservationInbox
from integration.architect_role_contract_host import ArchitectRoleContractSources, _ACTIONS, _descriptors, _load_factory
from integration.architect_submission import ArchitectSubmissionCallbacks
from integration.architect_submission_feedback import ArchitectSubmissionFeedback
from integration.architect_deliverable_actions import ArchitectDeliverableActionAssembler
from integration.architect_submission_receipt_reader import (
    ArchitectSubmissionReceiptReader, ArchitectSubmissionRecoveryBindings, ArchitectSubmissionRecoverySettings,
    build_assembled_architect_submission_receipt_dispatcher,
)
from integration.architect_submission_host import ArchitectSubmissionHost, ArchitectSubmissionHostConfiguration
from integration.architect_learning_actions import ArchitectLearningActionAssembler
from integration.architect_transition_actions import ArchitectTransitionActionAssembler
from integration.architect_intake_actions import ArchitectIntakeActionAssembler
from integration.architect_intake_recovery_reader import (
    ArchitectIntakeRecoveryReader, ArchitectIntakeRecoverySettings, ArchitectIntakeRecoveryBindings,
    build_assembled_architect_intake_dispatcher,
)
from integration.architect_planning_actions import ArchitectPlanningActionAssembler
from integration.architect_billing_actions import ArchitectBillingActionAssembler
from integration.architect_billing_recovery_reader import (
    ArchitectBillingRecoveryReader, ArchitectBillingRecoverySettings, ArchitectBillingRecoveryBindings,
    build_assembled_architect_billing_dispatcher,
)
from integration.architect_planning_recovery_reader import (
    ArchitectPlanningRecoveryReader, ArchitectPlanningRecoverySettings, ArchitectPlanningRecoveryBindings,
    build_assembled_architect_planning_dispatcher,
)
from integration.architect_transition_reader import (
    ArchitectTransitionReader, ArchitectTransitionRecoveryBindings, ArchitectTransitionRecoverySettings,
    build_assembled_architect_transition_dispatcher,
)
from integration.architect_learning_reader import (
    ArchitectLearningReader, ArchitectLearningRecoveryBindings, ArchitectLearningRecoverySettings,
    build_assembled_architect_learning_dispatcher,
)
from integration.architect_learning_assessment_publication import (
    ArchitectLearningAssessmentPublicationStore, ArchitectLearningAssessmentPublishedViewProvider,
)
from integration.architect_learning_assessment_validation import ArchitectLearningAssessmentSourceValidator
from integration.architect_training_estimate_publication import (
    ArchitectTrainingEstimatePublicationStore, ArchitectTrainingEstimatePublishedViewProvider,
)
from integration.architect_training_estimate_validation import ArchitectTrainingEstimateSourceValidator
from integration.architect_design_actions import ArchitectDesignActionAssembler
from integration.architect_design_recovery_reader import (
    ArchitectDesignRecoveryReader, ArchitectDesignRecoverySettings, ArchitectDesignRecoveryBindings,
    build_assembled_architect_design_dispatcher,
)
from integration.architect_area_calculation_publication import (
    ArchitectAreaCalculationPublicationStore, ArchitectAreaCalculationPublishedViewProvider,
)
from integration.architect_area_calculation_validation import ArchitectAreaCalculationSourceValidator
from integration.architect_area_calculations import prepare_architect_area_calculation
from integration.architect_integration_actions import ArchitectIntegrationActionAssembler
from integration.architect_interface_consistency_publication import (
    ArchitectInterfaceConsistencyPublicationStore, ArchitectInterfaceConsistencyPublishedViewProvider,
)
from integration.architect_interface_consistency_validation import ArchitectInterfaceConsistencySourceValidator
from integration.architect_interface_consistency_calculations import prepare_architect_interface_consistency_calculation
from integration.architect_change_actions import ArchitectChangeActionAssembler
from integration.architect_change_impact_calculations import prepare_architect_change_impact_calculation
from integration.architect_change_impact_publication import (
    ArchitectChangeImpactPublicationStore, ArchitectChangeImpactPublishedViewProvider,
)
from integration.architect_change_impact_validation import ArchitectChangeImpactSourceValidator
from integration.architect_research_actions import ArchitectResearchActionAssembler
from integration.architect_research_recovery_reader import (
    ArchitectResearchRecoveryReader, ArchitectResearchRecoverySettings, ArchitectResearchRecoveryBindings,
    build_assembled_architect_research_dispatcher,
)
from integration.architect_research_estimate_calculations import prepare_architect_research_estimate_calculation
from integration.architect_research_estimate_publication import (
    ArchitectResearchEstimatePublicationStore, ArchitectResearchEstimatePublishedViewProvider,
)
from integration.architect_research_estimate_validation import ArchitectResearchEstimateSourceValidator
from integration.role_contract_host import RoleContractInvocation
from src.actions.contracts.common import ActionContext, StrictRecord, TextId
from src.actions.contracts.architect_design_objects import architect_design_schemas
from src.actions.roles.architect_design import prepare_architect_area_input
from src.actions.contracts.architect_integration_objects import architect_integration_schemas
from src.actions.roles.architect_integration import prepare_architect_interface_consistency_input
from src.actions.contracts.architect_change_objects import architect_change_schemas
from src.actions.roles.architect_change import prepare_architect_change_impact_input
from src.actions.contracts.architect_research_objects import architect_research_schemas
from src.actions.roles.architect_research import prepare_architect_research_estimate_input
from src.methods.architect_research_estimates import (
    ArchitectResearchEstimateInput, estimate_declared_architect_research,
)
from src.methods.engineer_research_estimates import estimate_declared_research
from src.coordination.invocations import InvocationSnapshotStore
from src.coordination.tasks import TaskConflict, canonical, task_digest
from src.methods.registry import MethodRegistry


class ArchitectFormalFeedbackSettings(StrictRecord):
    version: TextId
    inbox_path: TextId
    input_enabled: bool = False


class ArchitectFormalLearningAssessmentSettings(StrictRecord):
    version: TextId
    macro_version: TextId
    policy_version: TextId


class ArchitectFormalTrainingEstimateSettings(StrictRecord):
    version: TextId
    macro_version: TextId
    policy_version: TextId


class ArchitectFormalAreaCalculationSettings(StrictRecord):
    version: TextId
    macro_version: TextId
    policy_version: TextId


class ArchitectFormalInterfaceConsistencySettings(StrictRecord):
    version: TextId
    macro_version: TextId
    policy_version: TextId


class ArchitectFormalChangeImpactSettings(StrictRecord):
    version: TextId
    macro_version: TextId
    policy_version: TextId


class ArchitectFormalResearchEstimateSettings(StrictRecord):
    version: TextId
    macro_version: TextId
    policy_version: TextId


class ArchitectFormalApplicationSettings(StrictRecord):
    action_id: TextId
    dependency_factory: TextId
    dependency_version: TextId
    dependency_settings: dict
    client_version: TextId
    model_version: TextId
    submission: ArchitectSubmissionHostConfiguration | None = None
    feedback: ArchitectFormalFeedbackSettings | None = None
    execution_recovery: ArchitectTransitionRecoverySettings | ArchitectLearningRecoverySettings | ArchitectIntakeRecoverySettings | ArchitectPlanningRecoverySettings | ArchitectDesignRecoverySettings | ArchitectBillingRecoverySettings | ArchitectResearchRecoverySettings | ArchitectSubmissionRecoverySettings | None = None
    learning_assessment: ArchitectFormalLearningAssessmentSettings | None = None
    training_estimates: ArchitectFormalTrainingEstimateSettings | None = None
    area_calculations: ArchitectFormalAreaCalculationSettings | None = None
    interface_consistency: ArchitectFormalInterfaceConsistencySettings | None = None
    change_impacts: ArchitectFormalChangeImpactSettings | None = None
    research_estimates: ArchitectFormalResearchEstimateSettings | None = None

    @model_validator(mode='before')
    @classmethod
    def original_action_recovery(cls, value):
        if not isinstance(value, dict) or value.get('execution_recovery') is None:
            return value
        types = {'ARCHITECT-A02': ArchitectIntakeRecoverySettings,
            'ARCHITECT-A04': ArchitectPlanningRecoverySettings,
            'ARCHITECT-A05': ArchitectDesignRecoverySettings,
            'ARCHITECT-A10': ArchitectBillingRecoverySettings,
            'ARCHITECT-A13': ArchitectResearchRecoverySettings,
            'ARCHITECT-A07': ArchitectSubmissionRecoverySettings, 'ARCHITECT-A12': ArchitectLearningRecoverySettings,
            'ARCHITECT-A11': ArchitectTransitionRecoverySettings}
        action_id, recovery = value.get('action_id'), value['execution_recovery']
        if action_id not in types:
            raise ValueError('Architect recovery requires original A02 intake, A04 planning, A05 design, A07 submission, A10 billing, A11 transition, A12 learning or A13 research action')
        settings_type = types[action_id]
        if isinstance(recovery, ArchitectSubmissionRecoverySettings) and type(recovery) is not settings_type:
            raise ValueError('Architect recovery configuration changes its original action type')
        return {**value, 'execution_recovery': settings_type.model_validate(recovery)}


@dataclass(frozen=True)
class ArchitectFormalApplicationDependencies:
    """Actual application supplies original sources and an existing model host.

    The factory owns partial resources until returning this bundle. Original
    invocation/wait/recovery validators apply to all submission workers; actual
    action-specific transport and business validation are explicitly supplied.
    """
    version: str
    sources: ArchitectRoleContractSources
    submission_callbacks: dict[str, ArchitectSubmissionCallbacks] = field(default_factory=dict)
    submission_read_guard: Callable | None = None
    validate_feedback_relation: Callable | None = None
    validate_feedback_read: Callable | None = None
    validate_feedback_input: Callable | None = None
    validate_impact_basis: Callable | None = None
    validate_research_estimate_basis: Callable | None = None
    execution_recovery: ArchitectTransitionRecoveryBindings | ArchitectLearningRecoveryBindings | ArchitectSubmissionRecoveryBindings | ArchitectIntakeRecoveryBindings | ArchitectPlanningRecoveryBindings | ArchitectDesignRecoveryBindings | ArchitectBillingRecoveryBindings | ArchitectResearchRecoveryBindings | None = None

    def __post_init__(self):
        if (not isinstance(self.version, str) or not self.version.strip()
                or not isinstance(self.sources, ArchitectRoleContractSources)
                or self.sources.feedback is not None or self.sources.validate_feedback_input is not None
                or self.sources.save_learning_assessment is not None
                or self.sources.publish_saved_learning_assessment is not None
                or self.sources.save_training_estimate is not None
                or self.sources.publish_saved_training_estimate is not None
                or self.sources.save_area_calculation is not None
                or self.sources.publish_saved_area_calculations is not None
                or self.sources.save_consistency_calculation is not None
                or self.sources.publish_saved_consistency_calculations is not None
                or self.sources.save_change_impact_calculation is not None
                or self.sources.publish_saved_change_impact_calculations is not None
                or self.sources.save_research_estimate_calculation is not None
                or self.sources.publish_saved_research_estimate_calculations is not None
                or not isinstance(self.submission_callbacks, dict)
                or self.execution_recovery is not None and not isinstance(
                    self.execution_recovery, ArchitectSubmissionRecoveryBindings)
                or any(not isinstance(value, ArchitectSubmissionCallbacks) for value in self.submission_callbacks.values())
                or any(callback is not None and not callable(callback) for callback in
                    (self.submission_read_guard, self.validate_feedback_relation,
                        self.validate_feedback_read, self.validate_feedback_input, self.validate_impact_basis,
                        self.validate_research_estimate_basis))):
            raise ValueError('Formal Architect dependencies require original sources and actual callback bindings')


class ArchitectFormalApplication:
    """Assemble original workers and configured routes; business calls stay explicit.

    Source health and native endpoint effects require observed application
    evidence. Construction is configured_unverified and never runs an action,
    sends a submission, constructs a model client or invents a native source.
    Design, review, billing, learning and transition routes require actual
    application transport. Configuration and receipts do not prove acceptance,
    use rights, applied learning, fees, cash or released service obligations.
    """
    VERSION = 'architect-formal-application.v1'

    def __init__(self, *, request, settings, dependencies, factory_descriptor):
        self.settings = ArchitectFormalApplicationSettings.model_validate(settings).model_copy(deep=True)
        request = RoleContractInvocation.model_validate(request).model_copy(deep=True)
        if not isinstance(dependencies, ArchitectFormalApplicationDependencies):
            raise ValueError('Formal Architect factory must return ArchitectFormalApplicationDependencies')
        base = dependencies.sources
        config = self.settings
        model = base.model_host
        if (config.action_id not in _ACTIONS or request.context.contract_ref.id != config.action_id
                or request.context.execution_mode != 'llm' or request.context.run_id != base.store.run_id
                or base.organizations.run_id != base.store.run_id or dependencies.version != config.dependency_version
                or model is None or model.store is not base.store or model.registry is not base.registry
                or model.model_version != config.model_version):
            raise ValueError('Formal Architect assembly requires original same-run sources and configured model host')
        registration = base.registry.get(config.action_id)
        if (registration.role != 'Architect' or not registration.implemented or registration.skill is None
                or request.execution_path not in {None, registration.strategy}
                or not any(config.action_id in binding.action_ids and binding.strategy == registration.strategy
                    for binding in model.bindings)):
            raise ValueError('Formal Architect application requires its original implemented action and bound strategy')
        actions = {route.action_id for route in config.submission.routes} if config.submission is not None else set()
        if (not actions <= set(_ACTIONS) or set(dependencies.submission_callbacks) != actions
                or config.submission is not None and not callable(dependencies.submission_read_guard)
                or config.submission is None and dependencies.submission_read_guard is not None):
            raise ValueError('Configured Architect submission must match its explicit callbacks and current read guard')
        if config.feedback is not None:
            if (config.submission is None or not actions
                    or not callable(dependencies.validate_feedback_relation)
                    or not callable(dependencies.validate_feedback_read)):
                raise ValueError('Architect feedback requires configured submission routes and actual relation/read validators')
        elif dependencies.validate_feedback_relation is not None or dependencies.validate_feedback_read is not None:
            raise ValueError('Architect feedback validators require an explicit feedback configuration')
        input_enabled = config.feedback is not None and config.feedback.input_enabled
        if (input_enabled and not callable(dependencies.validate_feedback_input)
                or not input_enabled and dependencies.validate_feedback_input is not None):
            raise ValueError('Architect feedback input validation must match the explicit input-enabled configuration')
        if ((config.change_impacts is not None) != (dependencies.validate_impact_basis is not None)
                or config.change_impacts is not None and not callable(dependencies.validate_impact_basis)):
            raise ValueError('Architect impact configuration requires its explicit actual numeric scope/cost/time verifier')
        if ((config.research_estimates is not None) != (dependencies.validate_research_estimate_basis is not None)
                or config.research_estimates is not None and not callable(dependencies.validate_research_estimate_basis)):
            raise ValueError('Architect research estimate configuration requires its explicit actual numeric coverage/rate verifier')
        self.dependencies, self.base = dependencies, base
        self.factory_descriptor = deepcopy(factory_descriptor)
        self._components = (base, base.store, base.registry, base.organizations, base.provider, model)
        self._closed = False
        self.provider = base.provider
        self.assessment_validator = self.assessment_publications = self.assessment_assembler = None
        if config.learning_assessment is not None:
            assessment = config.learning_assessment
            if not isinstance(base.methods, MethodRegistry):
                raise ValueError('Architect learning assessment requires the original bound method registry')
            self.assessment_validator = ArchitectLearningAssessmentSourceValidator(registry=base.registry,
                organizations=base.organizations, provider=base.provider,
                macro_version=assessment.macro_version, source_mode='formal')
            self.assessment_publications = ArchitectLearningAssessmentPublicationStore(store=base.store,
                registry=base.registry, methods=base.methods, organizations=base.organizations,
                validate_source=self.assessment_validator.validate_source)
            self.assessment_assembler = ArchitectLearningActionAssembler(registry=base.registry,
                organizations=base.organizations, provider=base.provider, macro_version=assessment.macro_version,
                source_mode='formal', methods=base.methods, policy_version=assessment.policy_version,
                model_version=config.model_version, model_host=model)
            self.provider = ArchitectLearningAssessmentPublishedViewProvider(provider=base.provider,
                publications=self.assessment_publications)
        self.assessment_provider = self.provider
        self._assessment_components = (self.assessment_provider, self.assessment_validator,
            self.assessment_publications, self.assessment_assembler, base.methods)
        self.training_validator = self.training_publications = self.training_assembler = None
        if config.training_estimates is not None:
            training = config.training_estimates
            if not isinstance(base.methods, MethodRegistry):
                raise ValueError('Architect training estimates require the original bound method registry')
            self.training_validator = ArchitectTrainingEstimateSourceValidator(registry=base.registry,
                organizations=base.organizations, provider=base.provider,
                macro_version=training.macro_version, source_mode='formal')
            self.training_publications = ArchitectTrainingEstimatePublicationStore(store=base.store,
                registry=base.registry, methods=base.methods, organizations=base.organizations,
                validate_source=self.training_validator.validate_source)
            self.training_assembler = ArchitectLearningActionAssembler(registry=base.registry,
                organizations=base.organizations, provider=base.provider, macro_version=training.macro_version,
                source_mode='formal', methods=base.methods, policy_version=training.policy_version,
                model_version=config.model_version, model_host=model)
            self.provider = ArchitectTrainingEstimatePublishedViewProvider(provider=self.assessment_provider,
                publications=self.training_publications)
        self.training_provider = self.provider
        self._training_components = (self.training_provider, self.training_validator, self.training_publications,
            self.training_assembler, base.methods)
        self.area_validator = self.area_publications = self.area_assembler = None
        if config.area_calculations is not None:
            area = config.area_calculations
            if not isinstance(base.methods, MethodRegistry):
                raise ValueError('Architect area calculations require the original bound method registry')
            self.area_validator = ArchitectAreaCalculationSourceValidator(registry=base.registry,
                organizations=base.organizations, provider=base.provider,
                macro_version=area.macro_version, source_mode='formal')
            self.area_publications = ArchitectAreaCalculationPublicationStore(store=base.store,
                registry=base.registry, methods=base.methods, organizations=base.organizations,
                validate_source=self.area_validator.validate_source)
            self.area_assembler = ArchitectDesignActionAssembler(registry=base.registry,
                organizations=base.organizations, provider=base.provider, macro_version=area.macro_version,
                source_mode='formal', methods=base.methods, policy_version=area.policy_version,
                model_version=config.model_version, model_host=model)
            self.provider = ArchitectAreaCalculationPublishedViewProvider(provider=self.training_provider,
                publications=self.area_publications)
        self.area_provider = self.provider
        self._area_components = (self.area_provider, self.area_validator, self.area_publications, self.area_assembler, base.methods)
        self.consistency_validator = self.consistency_publications = self.consistency_assembler = None
        if config.interface_consistency is not None:
            consistency = config.interface_consistency
            if not isinstance(base.methods, MethodRegistry):
                raise ValueError('Architect interface consistency requires the original bound method registry')
            self.consistency_validator = ArchitectInterfaceConsistencySourceValidator(registry=base.registry,
                organizations=base.organizations, provider=base.provider,
                macro_version=consistency.macro_version, source_mode='formal')
            self.consistency_publications = ArchitectInterfaceConsistencyPublicationStore(store=base.store,
                registry=base.registry, methods=base.methods, organizations=base.organizations,
                validate_source=self.consistency_validator.validate_source)
            self.consistency_assembler = ArchitectIntegrationActionAssembler(registry=base.registry,
                organizations=base.organizations, provider=base.provider, macro_version=consistency.macro_version,
                source_mode='formal', methods=base.methods, policy_version=consistency.policy_version,
                model_version=config.model_version, model_host=model)
            self.provider = ArchitectInterfaceConsistencyPublishedViewProvider(provider=self.area_provider,
                publications=self.consistency_publications)
        self.consistency_provider = self.provider
        self._consistency_components = (self.consistency_provider, self.consistency_validator, self.consistency_publications,
            self.consistency_assembler, base.methods)
        self.impact_validator = self.impact_publications = self.impact_assembler = None
        if config.change_impacts is not None:
            impact = config.change_impacts
            if not isinstance(base.methods, MethodRegistry):
                raise ValueError('Architect impact calculations require the original bound method registry')
            self.impact_validator = ArchitectChangeImpactSourceValidator(registry=base.registry,
                organizations=base.organizations, provider=base.provider,
                macro_version=impact.macro_version, source_mode='formal',
                validate_impact_basis=dependencies.validate_impact_basis)
            self.impact_publications = ArchitectChangeImpactPublicationStore(store=base.store,
                registry=base.registry, methods=base.methods, organizations=base.organizations,
                validate_source=self.impact_validator.validate_source)
            self.impact_assembler = ArchitectChangeActionAssembler(registry=base.registry,
                organizations=base.organizations, provider=base.provider, macro_version=impact.macro_version,
                source_mode='formal', methods=base.methods, policy_version=impact.policy_version,
                model_version=config.model_version, model_host=model)
            self.provider = ArchitectChangeImpactPublishedViewProvider(provider=self.consistency_provider,
                publications=self.impact_publications)
        self.impact_provider = self.provider
        self._impact_components = (self.impact_provider, self.impact_validator, self.impact_publications,
            self.impact_assembler, base.methods, dependencies.validate_impact_basis)
        self._impact_source_components = () if self.impact_validator is None else (
            self.impact_validator._views, self.impact_validator._views.schemas,
            self.impact_assembler._views, self.impact_assembler._views.schemas, self.impact_publications.schemas)
        self.research_estimate_validator = self.research_estimate_publications = self.research_estimate_assembler = None
        if config.research_estimates is not None:
            research_estimate = config.research_estimates
            if not isinstance(base.methods, MethodRegistry):
                raise ValueError('Architect research estimate calculations require the original bound method registry')
            self.research_estimate_validator = ArchitectResearchEstimateSourceValidator(registry=base.registry,
                organizations=base.organizations, provider=base.provider,
                macro_version=research_estimate.macro_version, source_mode='formal',
                validate_estimate_basis=dependencies.validate_research_estimate_basis)
            self.research_estimate_publications = ArchitectResearchEstimatePublicationStore(store=base.store,
                registry=base.registry, methods=base.methods, organizations=base.organizations,
                validate_source=self.research_estimate_validator.validate_source)
            self.research_estimate_assembler = ArchitectResearchActionAssembler(registry=base.registry,
                organizations=base.organizations, provider=base.provider, macro_version=research_estimate.macro_version,
                source_mode='formal', methods=base.methods, policy_version=research_estimate.policy_version,
                model_version=config.model_version, model_host=model)
            self.provider = ArchitectResearchEstimatePublishedViewProvider(provider=self.impact_provider,
                publications=self.research_estimate_publications)
        self._research_estimate_components = (self.provider, self.research_estimate_validator, self.research_estimate_publications,
            self.research_estimate_assembler, base.methods, dependencies.validate_research_estimate_basis)
        self._research_estimate_source_components = () if self.research_estimate_validator is None else (
            self.research_estimate_validator._views, self.research_estimate_validator._views.schemas,
            self.research_estimate_assembler._views, self.research_estimate_assembler._views.schemas, self.research_estimate_publications.schemas)
        self.submissions = self.feedback = self.execution_dispatcher = None
        self.receipt_assembler = self.receipt_reader = None
        self._receipt_recovery_components = None
        if config.submission is not None:
            snapshots = InvocationSnapshotStore(base.store)
            workers = {}
            for action_id in sorted(actions):
                module, name = _ACTIONS[action_id]
                worker_type = getattr(importlib.import_module('integration.architect_' + module + '_results'),
                    'Architect' + name + 'ResultWorker')
                workers[action_id] = worker_type(store=base.store, snapshots=snapshots, registry=base.registry,
                    client_version=config.client_version, model_version=config.model_version,
                    validate_invocation=base.validators.invocation, validate_wait=base.validators.wait,
                    validate_recovery=base.validators.recovery)
            self.submissions = ArchitectSubmissionHost(store=base.store, registry=base.registry, workers=workers,
                callbacks=dependencies.submission_callbacks, read_guard=dependencies.submission_read_guard,
                configuration=config.submission)
        if config.feedback is not None:
            inbox = ObservationInbox(base.store.run_id, base.store.organization_ids, Path(config.feedback.inbox_path))
            self.feedback = ArchitectSubmissionFeedback(host=self.submissions, inbox=inbox,
                version=config.feedback.version, validate_relation=dependencies.validate_feedback_relation,
                validate_read=dependencies.validate_feedback_read)
        recovery = dependencies.execution_recovery
        if (config.execution_recovery is None) != (recovery is None):
            raise ValueError('Architect action recovery must match its explicit configuration')
        if recovery is not None:
            routes = {
                'ARCHITECT-A02': (ArchitectIntakeRecoverySettings, ArchitectIntakeRecoveryBindings,
                    ArchitectIntakeActionAssembler, build_assembled_architect_intake_dispatcher),
                'ARCHITECT-A04': (ArchitectPlanningRecoverySettings, ArchitectPlanningRecoveryBindings,
                    ArchitectPlanningActionAssembler, build_assembled_architect_planning_dispatcher),
                'ARCHITECT-A05': (ArchitectDesignRecoverySettings, ArchitectDesignRecoveryBindings,
                    ArchitectDesignActionAssembler, build_assembled_architect_design_dispatcher),
                'ARCHITECT-A10': (ArchitectBillingRecoverySettings, ArchitectBillingRecoveryBindings,
                    ArchitectBillingActionAssembler, build_assembled_architect_billing_dispatcher),
                'ARCHITECT-A13': (ArchitectResearchRecoverySettings, ArchitectResearchRecoveryBindings,
                    ArchitectResearchActionAssembler, build_assembled_architect_research_dispatcher),
                'ARCHITECT-A07': (ArchitectSubmissionRecoverySettings, ArchitectSubmissionRecoveryBindings,
                    ArchitectDeliverableActionAssembler, build_assembled_architect_submission_receipt_dispatcher),
                'ARCHITECT-A12': (ArchitectLearningRecoverySettings, ArchitectLearningRecoveryBindings,
                    ArchitectLearningActionAssembler, build_assembled_architect_learning_dispatcher),
                'ARCHITECT-A11': (ArchitectTransitionRecoverySettings, ArchitectTransitionRecoveryBindings,
                    ArchitectTransitionActionAssembler, build_assembled_architect_transition_dispatcher),
            }
            if config.action_id not in routes or config.action_id not in actions or self.feedback is None:
                raise ValueError('Architect recovery requires original A02, A04, A05, A07, A10, A11, A12 or A13 submission and feedback routes')
            settings_type, bindings_type, assembler_type, build_dispatcher = routes[config.action_id]
            if type(config.execution_recovery) is not settings_type or type(recovery) is not bindings_type:
                raise ValueError('Architect recovery settings and callbacks must match the original action')
            self.receipt_assembler = assembler_type(registry=base.registry,
                organizations=base.organizations, provider=self.provider,
                macro_version=config.execution_recovery.macro_version, source_mode='formal', methods=base.methods,
                policy_version=config.execution_recovery.policy_version, model_version=config.model_version,
                model_host=model)
            reader_options = {}
            if config.action_id in {'ARCHITECT-A02', 'ARCHITECT-A04', 'ARCHITECT-A05', 'ARCHITECT-A10', 'ARCHITECT-A11', 'ARCHITECT-A12', 'ARCHITECT-A13'}:
                reader_type = (ArchitectIntakeRecoveryReader if config.action_id == 'ARCHITECT-A02' else
                    ArchitectPlanningRecoveryReader if config.action_id == 'ARCHITECT-A04' else
                    ArchitectDesignRecoveryReader if config.action_id == 'ARCHITECT-A05' else
                    ArchitectBillingRecoveryReader if config.action_id == 'ARCHITECT-A10' else
                    ArchitectResearchRecoveryReader if config.action_id == 'ARCHITECT-A13' else
                    ArchitectTransitionReader if config.action_id == 'ARCHITECT-A11' else ArchitectLearningReader)
                self.receipt_reader = reader_type(assembler=self.receipt_assembler,
                    snapshots=InvocationSnapshotStore(base.store), select_current=recovery.select_current)
                reader_options['reader'] = self.receipt_reader
            else:
                self.receipt_reader = ArchitectSubmissionReceiptReader(assembler=self.receipt_assembler,
                    select_current=recovery.select_current)
            self.execution_dispatcher = build_dispatcher(
                inbox=self.feedback.inbox, store=base.store, assembler=self.receipt_assembler,
                select_current=recovery.select_current, read_guard=recovery.read_guard,
                validate_relation=recovery.validate_relation, project_signal=recovery.project_signal,
                prepare=recovery.prepare, revalidate=recovery.revalidate, **reader_options)
            self._receipt_recovery_components = (recovery, *recovery.components(), self.receipt_assembler,
                self.receipt_reader, self.execution_dispatcher, self.feedback.inbox, self.provider)
        self._declared = self._configuration()
        self._key = 'architect_formal_application:' + task_digest([config.dependency_factory, config.action_id])
        with base.store._transaction():
            prior = base.store._db.execute('SELECT value FROM metadata WHERE key=?', (self._key,)).fetchone()
            if prior is None:
                base.store._db.execute('INSERT INTO metadata VALUES (?,?)', (self._key, canonical(self._declared)))
            elif json.loads(prior[0]) != self._declared:
                raise TaskConflict('Original formal Architect application configuration changed; explicit review required')

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
                'provider': module_factory_descriptor(self.assessment_provider.project, 'Architect.learning_assessment_provider'),
                'producer': module_factory_descriptor(self.assessment_assembler.prepare_assessment, 'Architect.learning_assessment_producer'),
                'save_entry': module_factory_descriptor(self.assessment_assembler.save_assessment, 'Architect.learning_assessment_save_entry'),
                'save': module_factory_descriptor(self.assessment_publications.save, 'Architect.learning_assessment_save'),
                'publish': module_factory_descriptor(self.assessment_publications.publish, 'Architect.learning_assessment_publish'),
                'read': module_factory_descriptor(self.assessment_publications.read, 'Architect.learning_assessment_read'),
                'validation': module_factory_descriptor(self.assessment_publications._validate, 'Architect.learning_assessment_validation')},
            'submission_sha256': task_digest(self.submissions._declared) if self.submissions is not None else None,
            'training_estimates': None if self.training_validator is None else {
                'validator': deepcopy(self.training_validator._declared),
                'method_registry_sha256': self.base.methods.content_digest,
                'provider': module_factory_descriptor(self.training_provider.project, 'Architect.training_estimate_provider'),
                'producer': module_factory_descriptor(self.training_assembler.prepare_training_estimate, 'Architect.training_estimate_producer'),
                'save_entry': module_factory_descriptor(self.training_assembler.save_training_estimate, 'Architect.training_estimate_save_entry'),
                'save': module_factory_descriptor(self.training_publications.save, 'Architect.training_estimate_save'),
                'publish': module_factory_descriptor(self.training_publications.publish, 'Architect.training_estimate_publish'),
                'read': module_factory_descriptor(self.training_publications.read, 'Architect.training_estimate_read'),
                'validation': module_factory_descriptor(self.training_publications._validate, 'Architect.training_estimate_validation')},
            'area_calculations': None if self.area_validator is None else {
                'validator': deepcopy(self.area_validator._declared),
                'method_registry_sha256': self.base.methods.content_digest,
                'provider': module_factory_descriptor(self.area_provider.project, 'Architect.area_calculation_provider'),
                'producer': module_factory_descriptor(prepare_architect_area_calculation, 'Architect.area_calculation_producer'),
                'prepare_input': module_factory_descriptor(prepare_architect_area_input, 'Architect.area_calculation_prepare_input'),
                'source_schemas': module_factory_descriptor(architect_design_schemas, 'Architect.area_calculation_source_schemas'),
                'save_entry': module_factory_descriptor(self.area_assembler.save_area_calculation, 'Architect.area_calculation_save_entry'),
                'save': module_factory_descriptor(self.area_publications.save, 'Architect.area_calculation_save'),
                'publish': module_factory_descriptor(self.area_publications.publish, 'Architect.area_calculation_publish'),
                'publish_many': module_factory_descriptor(self.area_publications.publish_many, 'Architect.area_calculation_publish_many'),
                'read': module_factory_descriptor(self.area_publications.read, 'Architect.area_calculation_read'),
                'validation': module_factory_descriptor(self.area_publications._validate, 'Architect.area_calculation_validation')},
            'interface_consistency': None if self.consistency_validator is None else {
                'validator': deepcopy(self.consistency_validator._declared),
                'method_registry_sha256': self.base.methods.content_digest,
                'provider': module_factory_descriptor(self.consistency_provider.project, 'Architect.consistency_provider'),
                'producer': module_factory_descriptor(prepare_architect_interface_consistency_calculation, 'Architect.consistency_producer'),
                'prepare_input': module_factory_descriptor(prepare_architect_interface_consistency_input, 'Architect.consistency_prepare_input'),
                'source_schemas': module_factory_descriptor(architect_integration_schemas, 'Architect.consistency_source_schemas'),
                'save_entry': module_factory_descriptor(self.consistency_assembler.save_consistency_calculation, 'Architect.consistency_save_entry'),
                'save': module_factory_descriptor(self.consistency_publications.save, 'Architect.consistency_save'),
                'publish': module_factory_descriptor(self.consistency_publications.publish, 'Architect.consistency_publish'),
                'publish_many': module_factory_descriptor(self.consistency_publications.publish_many, 'Architect.consistency_publish_many'),
                'read': module_factory_descriptor(self.consistency_publications.read, 'Architect.consistency_read'),
                'validation': module_factory_descriptor(self.consistency_publications._validate, 'Architect.consistency_validation')},
            'change_impacts': None if self.impact_validator is None else {
                'validator': deepcopy(self.impact_validator._declared),
                'method_registry_sha256': self.base.methods.content_digest,
                'provider': module_factory_descriptor(self.impact_provider.project, 'Architect.change_impact_provider'),
                'producer': module_factory_descriptor(prepare_architect_change_impact_calculation, 'Architect.change_impact_producer'),
                'prepare_input': module_factory_descriptor(prepare_architect_change_impact_input, 'Architect.change_impact_prepare_input'),
                'source_schemas': module_factory_descriptor(architect_change_schemas, 'Architect.change_impact_source_schemas'),
                'assembler_schemas': module_factory_descriptor(self.impact_assembler.SOURCE_SCHEMAS, 'Architect.change_impact_assembler_schemas'),
                'validator_schemas': module_factory_descriptor(self.impact_validator.SOURCE_SCHEMAS, 'Architect.change_impact_validator_schemas'),
                'publication_schemas': module_factory_descriptor(self.impact_publications.SOURCE_SCHEMAS, 'Architect.change_impact_publication_schemas'),
                'schema_bindings': self._impact_schema_bindings(),
                'prepare_entry': module_factory_descriptor(self.impact_assembler.prepare_impact_calculation, 'Architect.change_impact_prepare_entry'),
                'reading': module_factory_descriptor(self.impact_assembler._build_impact_reading, 'Architect.change_impact_reading'),
                'save_entry': module_factory_descriptor(self.impact_assembler.save_impact_calculation, 'Architect.change_impact_save_entry'),
                'save': module_factory_descriptor(self.impact_publications.save, 'Architect.change_impact_save'),
                'publish': module_factory_descriptor(self.impact_publications.publish, 'Architect.change_impact_publish'),
                'publish_many': module_factory_descriptor(self.impact_publications.publish_many, 'Architect.change_impact_publish_many'),
                'read': module_factory_descriptor(self.impact_publications.read, 'Architect.change_impact_read'),
                'validation': module_factory_descriptor(self.impact_publications._validate, 'Architect.change_impact_validation'),
                'current_validation': module_factory_descriptor(self.impact_validator.validate_current, 'Architect.change_impact_current_validation'),
                'source_validation': module_factory_descriptor(self.impact_validator.validate_source, 'Architect.change_impact_source_validation'),
                'source_reading': module_factory_descriptor(self.impact_validator._reading, 'Architect.change_impact_source_reading'),
                'proof_validation': module_factory_descriptor(self.impact_publications._validate_method_execution, 'Architect.change_impact_proof_validation'),
                'numeric_scope_verifier': module_factory_descriptor(self.dependencies.validate_impact_basis, 'Architect.change_impact_numeric_scope'),
                'publication_binding': self.impact_publications._binding(),
                'record_schema': self.impact_publications.SCHEMA,
                'action_id': self.impact_publications.ACTION_ID,
                'role': self.impact_publications.ROLE,
                'method_ref': self.impact_publications.METHOD_REF.model_dump(mode='json'),
                'publication_schema': self.impact_publications.PUBLICATION_SCHEMA,
                'batch_publication_schema': self.impact_publications.BATCH_PUBLICATION_SCHEMA,
                'records_table': self.impact_publications.RECORDS_TABLE,
                'publications_table': self.impact_publications.PUBLICATIONS_TABLE},
            'research_estimates': None if self.research_estimate_validator is None else {
                'validator': deepcopy(self.research_estimate_validator._declared),
                'method_registry_sha256': self.base.methods.content_digest,
                'provider': module_factory_descriptor(self.provider.project, 'Architect.research_estimate_provider'),
                'producer': module_factory_descriptor(prepare_architect_research_estimate_calculation, 'Architect.research_estimate_producer'),
                'report_runtime': module_factory_descriptor(estimate_declared_architect_research, 'Architect.research_estimate_report_runtime'),
                'arithmetic_runtime': module_factory_descriptor(estimate_declared_research, 'Architect.research_estimate_arithmetic_runtime'),
                'numeric_input_validation': module_factory_descriptor(ArchitectResearchEstimateInput.exact_sourced_units, 'Architect.research_estimate_numeric_input_validation'),
                'prepare_input': module_factory_descriptor(prepare_architect_research_estimate_input, 'Architect.research_estimate_prepare_input'),
                'source_schemas': module_factory_descriptor(architect_research_schemas, 'Architect.research_estimate_source_schemas'),
                'assembler_schemas': module_factory_descriptor(self.research_estimate_assembler.SOURCE_SCHEMAS, 'Architect.research_estimate_assembler_schemas'),
                'validator_schemas': module_factory_descriptor(self.research_estimate_validator.SOURCE_SCHEMAS, 'Architect.research_estimate_validator_schemas'),
                'publication_schemas': module_factory_descriptor(self.research_estimate_publications.SOURCE_SCHEMAS, 'Architect.research_estimate_publication_schemas'),
                'schema_bindings': self._research_estimate_schema_bindings(),
                'prepare_entry': module_factory_descriptor(self.research_estimate_assembler.prepare_estimate_calculation, 'Architect.research_estimate_prepare_entry'),
                'reading': module_factory_descriptor(self.research_estimate_assembler._build_estimate_reading, 'Architect.research_estimate_reading'),
                'save_entry': module_factory_descriptor(self.research_estimate_assembler.save_estimate_calculation, 'Architect.research_estimate_save_entry'),
                'save': module_factory_descriptor(self.research_estimate_publications.save, 'Architect.research_estimate_save'),
                'publish': module_factory_descriptor(self.research_estimate_publications.publish, 'Architect.research_estimate_publish'),
                'publish_many': module_factory_descriptor(self.research_estimate_publications.publish_many, 'Architect.research_estimate_publish_many'),
                'read': module_factory_descriptor(self.research_estimate_publications.read, 'Architect.research_estimate_read'),
                'validation': module_factory_descriptor(self.research_estimate_publications._validate, 'Architect.research_estimate_validation'),
                'current_validation': module_factory_descriptor(self.research_estimate_validator.validate_current, 'Architect.research_estimate_current_validation'),
                'source_validation': module_factory_descriptor(self.research_estimate_validator.validate_source, 'Architect.research_estimate_source_validation'),
                'source_reading': module_factory_descriptor(self.research_estimate_validator._reading, 'Architect.research_estimate_source_reading'),
                'proof_validation': module_factory_descriptor(self.research_estimate_publications._validate_method_execution, 'Architect.research_estimate_proof_validation'),
                'numeric_scope_verifier': module_factory_descriptor(self.dependencies.validate_research_estimate_basis, 'Architect.research_estimate_numeric_scope'),
                'publication_binding': self.research_estimate_publications._binding(),
                'record_schema': self.research_estimate_publications.SCHEMA,
                'action_id': self.research_estimate_publications.ACTION_ID,
                'role': self.research_estimate_publications.ROLE,
                'method_ref': self.research_estimate_publications.METHOD_REF.model_dump(mode='json'),
                'publication_schema': self.research_estimate_publications.PUBLICATION_SCHEMA,
                'batch_publication_schema': self.research_estimate_publications.BATCH_PUBLICATION_SCHEMA,
                'records_table': self.research_estimate_publications.RECORDS_TABLE,
                'publications_table': self.research_estimate_publications.PUBLICATIONS_TABLE},
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

    def _impact_schema_bindings(self):
        """Bind actual retained projection schemas; construction is still unverified."""
        return {name: {kind: {
                'model': model.__module__ + ':' + model.__qualname__,
                'version_type': version_type.__name__,
                'identity_field': schemas._identity_fields[kind],
                'schema_sha256': task_digest(model.model_json_schema()),
            } for kind, (model, version_type) in sorted(schemas._schemas.items())}
            for name, schemas in (
                ('assembler', self.impact_assembler._views.schemas),
                ('validator', self.impact_validator._views.schemas),
                ('publication', self.impact_publications.schemas))}

    def _research_estimate_schema_bindings(self):
        """Bind actual retained projection schemas; construction is still unverified."""
        return {name: {kind: {
                'model': model.__module__ + ':' + model.__qualname__,
                'version_type': version_type.__name__,
                'identity_field': schemas._identity_fields[kind],
                'schema_sha256': task_digest(model.model_json_schema()),
            } for kind, (model, version_type) in sorted(schemas._schemas.items())}
            for name, schemas in (
                ('assembler', self.research_estimate_assembler._views.schemas),
                ('validator', self.research_estimate_validator._views.schemas),
                ('publication', self.research_estimate_publications.schemas))}

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
            raise TaskConflict('Original formal Architect components or configuration changed, or application closed')
        recovery = self.dependencies.execution_recovery
        if self._receipt_recovery_components is None:
            if any(value is not None for value in (recovery, self.receipt_assembler,
                    self.receipt_reader, self.execution_dispatcher)):
                raise TaskConflict('Undeclared Architect receipt recovery components were added')
        else:
            current = (recovery, *recovery.components(), self.receipt_assembler, self.receipt_reader,
                self.execution_dispatcher, self.feedback.inbox, self.provider)
            assembler = self.receipt_assembler
            expected = {
                'ARCHITECT-A02': (ArchitectIntakeRecoverySettings, ArchitectIntakeRecoveryBindings,
                    ArchitectIntakeActionAssembler, ArchitectIntakeRecoveryReader),
                'ARCHITECT-A04': (ArchitectPlanningRecoverySettings, ArchitectPlanningRecoveryBindings,
                    ArchitectPlanningActionAssembler, ArchitectPlanningRecoveryReader),
                'ARCHITECT-A05': (ArchitectDesignRecoverySettings, ArchitectDesignRecoveryBindings,
                    ArchitectDesignActionAssembler, ArchitectDesignRecoveryReader),
                'ARCHITECT-A10': (ArchitectBillingRecoverySettings, ArchitectBillingRecoveryBindings,
                    ArchitectBillingActionAssembler, ArchitectBillingRecoveryReader),
                'ARCHITECT-A13': (ArchitectResearchRecoverySettings, ArchitectResearchRecoveryBindings,
                    ArchitectResearchActionAssembler, ArchitectResearchRecoveryReader),
                'ARCHITECT-A07': (ArchitectSubmissionRecoverySettings, ArchitectSubmissionRecoveryBindings,
                    ArchitectDeliverableActionAssembler, ArchitectSubmissionReceiptReader),
                'ARCHITECT-A12': (ArchitectLearningRecoverySettings, ArchitectLearningRecoveryBindings,
                    ArchitectLearningActionAssembler, ArchitectLearningReader),
                'ARCHITECT-A11': (ArchitectTransitionRecoverySettings, ArchitectTransitionRecoveryBindings,
                    ArchitectTransitionActionAssembler, ArchitectTransitionReader),
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
                raise TaskConflict('Architect receipt recovery changed original source/model/recipient/callback bindings')
            if self.settings.action_id in {'ARCHITECT-A02', 'ARCHITECT-A04', 'ARCHITECT-A05', 'ARCHITECT-A10', 'ARCHITECT-A11', 'ARCHITECT-A12', 'ARCHITECT-A13'} and self.receipt_reader.snapshots.store is not self.base.store:
                raise TaskConflict('Architect learning recovery changed the original invocation journal')
            self.receipt_reader._check()
            self.execution_dispatcher._check()
        if any(actual is not original for actual, original in zip(
                (self.assessment_provider, self.assessment_validator, self.assessment_publications,
                    self.assessment_assembler, self.base.methods), self._assessment_components)):
            raise TaskConflict('Formal Architect learning assessment components changed')
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
                raise TaskConflict('Formal Architect learning assessment source, versions or publication wiring changed')
        elif self.assessment_provider is not self.base.provider:
            raise TaskConflict('Unconfigured Architect assessment replaced its original source provider')
        if any(actual is not original for actual, original in zip(
                (self.training_provider, self.training_validator, self.training_publications,
                    self.training_assembler, self.base.methods), self._training_components)):
            raise TaskConflict('Formal Architect training estimate components changed')
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
                raise TaskConflict('Formal Architect training estimate source, versions or publication wiring changed')
        elif self.training_provider is not self.assessment_provider:
            raise TaskConflict('Unconfigured Architect training estimate replaced its original source provider')
        if any(actual is not original for actual, original in zip(
                (self.area_provider, self.area_validator, self.area_publications, self.area_assembler, self.base.methods),
                self._area_components)):
            raise TaskConflict('Formal Architect area calculation components changed')
        if self.area_validator is not None:
            self.area_validator._check()
            validator, publications, assembler = self.area_validator, self.area_publications, self.area_assembler
            settings = self.settings.area_calculations
            if (settings is None or validator.provider is not self.base.provider
                    or validator.registry is not self.base.registry or validator.organizations is not self.base.organizations
                    or validator._views.macro_version != settings.macro_version or validator._views.source_mode != 'formal'
                    or publications.store is not self.base.store or publications.registry is not self.base.registry
                    or publications.organizations is not self.base.organizations or publications.methods is not self.base.methods
                    or publications.validate_source != validator.validate_source
                    or self.area_provider.provider is not self.training_provider or self.area_provider.publications is not publications
                    or assembler.provider is not self.base.provider or assembler.registry is not self.base.registry
                    or assembler.organizations is not self.base.organizations or assembler.methods is not self.base.methods
                    or assembler._views.provider is not self.base.provider
                    or assembler._views.organizations is not self.base.organizations
                    or assembler._views.macro_version != settings.macro_version or assembler._views.source_mode != 'formal'
                    or assembler.macro_version != settings.macro_version or assembler.source_mode != 'formal'
                    or assembler.policy_version != settings.policy_version or assembler.model_version != self.settings.model_version
                    or assembler.decision_strategies != tuple(self.base.model_host.bindings)):
                raise TaskConflict('Formal Architect area calculation source, versions or publication wiring changed')
        elif self.area_provider is not self.training_provider:
            raise TaskConflict('Unconfigured Architect area calculations replaced the original provider chain')
        if any(actual is not original for actual, original in zip(
                (self.consistency_provider, self.consistency_validator, self.consistency_publications,
                    self.consistency_assembler, self.base.methods), self._consistency_components)):
            raise TaskConflict('Formal Architect interface consistency components changed')
        if self.consistency_validator is not None:
            self.consistency_validator._check()
            validator, publications, assembler = self.consistency_validator, self.consistency_publications, self.consistency_assembler
            settings = self.settings.interface_consistency
            if (settings is None or validator.provider is not self.base.provider
                    or validator.registry is not self.base.registry or validator.organizations is not self.base.organizations
                    or validator._views.macro_version != settings.macro_version or validator._views.source_mode != 'formal'
                    or publications.store is not self.base.store or publications.registry is not self.base.registry
                    or publications.organizations is not self.base.organizations or publications.methods is not self.base.methods
                    or publications.validate_source != validator.validate_source
                    or self.consistency_provider.provider is not self.area_provider or self.consistency_provider.publications is not publications
                    or assembler.provider is not self.base.provider or assembler.registry is not self.base.registry
                    or assembler.organizations is not self.base.organizations or assembler.methods is not self.base.methods
                    or assembler._views.provider is not self.base.provider
                    or assembler._views.organizations is not self.base.organizations
                    or assembler._views.macro_version != settings.macro_version or assembler._views.source_mode != 'formal'
                    or assembler.macro_version != settings.macro_version or assembler.source_mode != 'formal'
                    or assembler.policy_version != settings.policy_version or assembler.model_version != self.settings.model_version
                    or assembler.decision_strategies != tuple(self.base.model_host.bindings)):
                raise TaskConflict('Formal Architect consistency source, versions or publication wiring changed')
        elif self.consistency_provider is not self.area_provider:
            raise TaskConflict('Unconfigured Architect interface consistency replaced the original provider chain')
        if any(actual is not original for actual, original in zip(
                (self.impact_provider, self.impact_validator, self.impact_publications, self.impact_assembler, self.base.methods,
                    self.dependencies.validate_impact_basis),
                self._impact_components)):
            raise TaskConflict('Formal Architect change impact calculation components changed')
        if self.impact_validator is not None:
            if any(actual is not original for actual, original in zip((
                    self.impact_validator._views, self.impact_validator._views.schemas,
                    self.impact_assembler._views, self.impact_assembler._views.schemas,
                    self.impact_publications.schemas), self._impact_source_components)):
                raise TaskConflict('Formal Architect impact retained source views or schemas changed')
            self.impact_validator._check()
            validator, publications, assembler = self.impact_validator, self.impact_publications, self.impact_assembler
            settings = self.settings.change_impacts
            if (settings is None or validator.validate_impact_basis is not self.dependencies.validate_impact_basis
                    or validator.ACTION_ID != 'ARCHITECT-A09' or assembler.ACTION_ID != 'ARCHITECT-A09'
                    or publications.ACTION_ID != 'ARCHITECT-A09' or validator.ROLE != 'Architect'
                    or validator.provider is not self.base.provider
                    or validator.registry is not self.base.registry or validator.organizations is not self.base.organizations
                    or validator._views.macro_version != settings.macro_version or validator._views.source_mode != 'formal'
                    or publications.store is not self.base.store or publications.registry is not self.base.registry
                    or publications.organizations is not self.base.organizations or publications.methods is not self.base.methods
                    or publications.validate_source != validator.validate_source
                    or self.impact_provider.provider is not self.consistency_provider or self.impact_provider.publications is not publications
                    or assembler.provider is not self.base.provider or assembler.registry is not self.base.registry
                    or assembler.organizations is not self.base.organizations or assembler.methods is not self.base.methods
                    or assembler._views.provider is not self.base.provider
                    or assembler._views.organizations is not self.base.organizations
                    or assembler._views.macro_version != settings.macro_version or assembler._views.source_mode != 'formal'
                    or assembler.macro_version != settings.macro_version or assembler.source_mode != 'formal'
                    or assembler.policy_version != settings.policy_version or assembler.model_version != self.settings.model_version
                    or assembler.decision_strategies != tuple(self.base.model_host.bindings)):
                raise TaskConflict('Formal Architect change impact calculation source, versions or publication wiring changed')
        elif self.impact_provider is not self.consistency_provider:
            raise TaskConflict('Unconfigured Architect change impact calculations replaced the original provider chain')
        if any(actual is not original for actual, original in zip(
                (self.provider, self.research_estimate_validator, self.research_estimate_publications, self.research_estimate_assembler, self.base.methods,
                    self.dependencies.validate_research_estimate_basis),
                self._research_estimate_components)):
            raise TaskConflict('Formal Architect research estimate calculation components changed')
        if self.research_estimate_validator is not None:
            if any(actual is not original for actual, original in zip((
                    self.research_estimate_validator._views, self.research_estimate_validator._views.schemas,
                    self.research_estimate_assembler._views, self.research_estimate_assembler._views.schemas,
                    self.research_estimate_publications.schemas), self._research_estimate_source_components)):
                raise TaskConflict('Formal Architect research estimate retained source views or schemas changed')
            self.research_estimate_validator._check()
            validator, publications, assembler = self.research_estimate_validator, self.research_estimate_publications, self.research_estimate_assembler
            settings = self.settings.research_estimates
            if (settings is None or validator.validate_estimate_basis is not self.dependencies.validate_research_estimate_basis
                    or validator.ACTION_ID != 'ARCHITECT-A13' or assembler.ACTION_ID != 'ARCHITECT-A13'
                    or publications.ACTION_ID != 'ARCHITECT-A13' or validator.ROLE != 'Architect'
                    or validator.provider is not self.base.provider
                    or validator.registry is not self.base.registry or validator.organizations is not self.base.organizations
                    or validator._views.macro_version != settings.macro_version or validator._views.source_mode != 'formal'
                    or publications.store is not self.base.store or publications.registry is not self.base.registry
                    or publications.organizations is not self.base.organizations or publications.methods is not self.base.methods
                    or publications.validate_source != validator.validate_source
                    or self.provider.provider is not self.impact_provider or self.provider.publications is not publications
                    or assembler.provider is not self.base.provider or assembler.registry is not self.base.registry
                    or assembler.organizations is not self.base.organizations or assembler.methods is not self.base.methods
                    or assembler._views.provider is not self.base.provider
                    or assembler._views.organizations is not self.base.organizations
                    or assembler._views.macro_version != settings.macro_version or assembler._views.source_mode != 'formal'
                    or assembler.macro_version != settings.macro_version or assembler.source_mode != 'formal'
                    or assembler.policy_version != settings.policy_version or assembler.model_version != self.settings.model_version
                    or assembler.decision_strategies != tuple(self.base.model_host.bindings)):
                raise TaskConflict('Formal Architect research estimate calculation source, versions or publication wiring changed')
        elif self.provider is not self.impact_provider:
            raise TaskConflict('Unconfigured Architect research estimate calculations replaced the original provider chain')
        if self.submissions is not None:
            self.submissions._check()
            if (self.submissions.store is not self.base.store or self.submissions.registry is not self.base.registry
                    or self.submissions.read_guard is not self.dependencies.submission_read_guard
                    or any(self.submissions.callbacks[action] is not callback
                        for action, callback in self.dependencies.submission_callbacks.items())):
                raise TaskConflict('Formal Architect submission components changed')
        if self.feedback is not None:
            self.feedback._check()
            if (self.feedback.host is not self.submissions
                    or self.feedback.validate_relation is not self.dependencies.validate_feedback_relation
                    or self.feedback.validate_read is not self.dependencies.validate_feedback_read):
                raise TaskConflict('Formal Architect feedback components or validators changed')
        with self.base.store._lock:
            saved = self.base.store._db.execute('SELECT value FROM metadata WHERE key=?', (self._key,)).fetchone()
            if saved is None or json.loads(saved[0]) != self._declared:
                raise TaskConflict('Formal Architect application configuration evidence changed')

    def evidence(self):
        self._check()
        actual = self.base.evidence()
        if not isinstance(actual, dict):
            raise ValueError('Formal Architect source evidence must be an explicit object')
        return {'schema_version': self.VERSION, 'configuration_sha256': task_digest(self._declared),
            'source_mode': 'formal', 'status': 'configured_unverified', 'sources': deepcopy(actual),
            'submission': self.submissions.capabilities() if self.submissions is not None else None,
            'feedback_configured': self.feedback is not None,
            'execution_recovery_configured': self.execution_dispatcher is not None,
            'learning_assessment_configured': self.assessment_validator is not None,
            'training_estimates_configured': self.training_validator is not None,
            'area_calculations_configured': self.area_validator is not None,
            'interface_consistency_configured': self.consistency_validator is not None,
            'change_impacts_configured': self.impact_validator is not None,
            'research_estimates_configured': self.research_estimate_validator is not None,
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
            save_area_calculation=self.save_area_calculation if self.area_validator is not None else None,
            publish_saved_area_calculations=self.publish_saved_area_calculations if self.area_validator is not None else None,
            save_consistency_calculation=self.save_consistency_calculation if self.consistency_validator is not None else None,
            publish_saved_consistency_calculations=self.publish_saved_consistency_calculations if self.consistency_validator is not None else None,
            save_change_impact_calculation=self.save_change_impact_calculation if self.impact_validator is not None else None,
            publish_saved_change_impact_calculations=self.publish_saved_change_impact_calculations if self.impact_validator is not None else None,
            save_research_estimate_calculation=self.save_research_estimate_calculation if self.research_estimate_validator is not None else None,
            publish_saved_research_estimate_calculations=self.publish_saved_research_estimate_calculations if self.research_estimate_validator is not None else None)

    def save_change_impact_calculation(self, context, *, preparation, author_authority_ref, **source_refs):
        """Save one original A09 impact without proposing or applying a design change."""
        self._check()
        if self.impact_assembler is None:
            raise ValueError('No Architect change impact calculation persistence is configured')
        context = ActionContext.model_validate(context).model_copy(deep=True)
        result = self.impact_assembler.save_impact_calculation(context, publications=self.impact_publications,
            read_guard=self.base.read_guard, preparation=preparation, author_authority_ref=author_authority_ref,
            validate_current=self.impact_validator.validate_current, **source_refs)
        self._check()
        return result

    def publish_saved_change_impact_calculations(self, record_sha256s, *, source_context, next_context):
        """Publish saved A09 impacts together under a fresh authorized read token."""
        self._check()
        if self.impact_publications is None:
            raise ValueError('No Architect change impact calculation publication is configured')
        source = ActionContext.model_validate(source_context).model_copy(deep=True)
        next_context = ActionContext.model_validate(next_context).model_copy(deep=True)
        with self.base.read_guard(source.model_copy(deep=True)):
            self._check()
            result = self.impact_publications.publish_many(record_sha256s, source_context=source, next_context=next_context)
            self._check()
            return result

    def save_research_estimate_calculation(self, context, *, preparation, author_authority_ref, **source_refs):
        """Save one original A13 estimate under independent actual source validation."""
        self._check()
        if self.research_estimate_assembler is None:
            raise ValueError('No Architect research estimate calculation persistence is configured')
        context = ActionContext.model_validate(context).model_copy(deep=True)
        result = self.research_estimate_assembler.save_estimate_calculation(context, publications=self.research_estimate_publications,
            read_guard=self.base.read_guard, preparation=preparation, author_authority_ref=author_authority_ref,
            validate_current=self.research_estimate_validator.validate_current, **source_refs)
        self._check()
        return result

    def publish_saved_research_estimate_calculations(self, record_sha256s, *, source_context, next_context):
        """Publish saved A13 estimates together under a fresh authorized read token."""
        self._check()
        if self.research_estimate_publications is None:
            raise ValueError('No Architect research estimate calculation publication is configured')
        source = ActionContext.model_validate(source_context).model_copy(deep=True)
        next_context = ActionContext.model_validate(next_context).model_copy(deep=True)
        with self.base.read_guard(source.model_copy(deep=True)):
            self._check()
            result = self.research_estimate_publications.publish_many(record_sha256s, source_context=source, next_context=next_context)
            self._check()
            return result

    def save_consistency_calculation(self, context, *, preparation, author_authority_ref, **source_refs):
        """Save one original reference report without running integration."""
        self._check()
        if self.consistency_assembler is None:
            raise ValueError('No Architect interface consistency persistence is configured')
        context = ActionContext.model_validate(context).model_copy(deep=True)
        result = self.consistency_assembler.save_consistency_calculation(context, publications=self.consistency_publications,
            read_guard=self.base.read_guard, preparation=preparation, author_authority_ref=author_authority_ref,
            validate_current=self.consistency_validator.validate_current, **source_refs)
        self._check()
        return result

    def publish_saved_consistency_calculations(self, record_sha256s, *, source_context, next_context):
        """Publish separately saved reference reports at a fresh authorized token."""
        self._check()
        if self.consistency_publications is None:
            raise ValueError('No Architect interface consistency publication is configured')
        source = ActionContext.model_validate(source_context).model_copy(deep=True)
        next_context = ActionContext.model_validate(next_context).model_copy(deep=True)
        with self.base.read_guard(source.model_copy(deep=True)):
            self._check()
            result = self.consistency_publications.publish_many(record_sha256s, source_context=source, next_context=next_context)
            self._check()
            return result

    def save_area_calculation(self, context, *, preparation, author_authority_ref, **source_refs):
        """Save one original draft's area report without running design compilation."""
        self._check()
        if self.area_assembler is None:
            raise ValueError('No Architect area calculation persistence is configured')
        context = ActionContext.model_validate(context).model_copy(deep=True)
        result = self.area_assembler.save_area_calculation(context, publications=self.area_publications,
            read_guard=self.base.read_guard, preparation=preparation, author_authority_ref=author_authority_ref,
            validate_current=self.area_validator.validate_current, **source_refs)
        self._check()
        return result

    def publish_saved_area_calculations(self, record_sha256s, *, source_context, next_context):
        """Publish separately saved draft reports together at a fresh read point."""
        self._check()
        if self.area_publications is None:
            raise ValueError('No Architect area calculation publication is configured')
        source = ActionContext.model_validate(source_context).model_copy(deep=True)
        next_context = ActionContext.model_validate(next_context).model_copy(deep=True)
        with self.base.read_guard(source.model_copy(deep=True)):
            self._check()
            result = self.area_publications.publish_many(record_sha256s, source_context=source, next_context=next_context)
            self._check()
            return result

    def save_training_estimate(self, context, *, estimate_ref, author_authority_ref, **source_refs):
        """Save one original work estimate using independently checked sources."""
        self._check()
        if self.training_assembler is None:
            raise ValueError('No Architect training estimate persistence is configured')
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
            raise ValueError('No Architect training estimate publication is configured')
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
            raise ValueError('No Architect learning assessment persistence is configured')
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
            raise ValueError('No Architect learning assessment publication is configured')
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
            raise ValueError('No actual Architect submission routes are configured')
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
        """Evaluate configured original waits and queue independently checked judgment."""
        self._check()
        if self.execution_dispatcher is None:
            raise ValueError('No Architect original action recovery is configured')
        result = self.execution_dispatcher(run_id=run_id, organization_id=organization_id)
        self._check()
        return result

    def wait_recovery_sources(self, *, identity, journal_path):
        """Expose the same configured action journal and guarded callbacks to V7."""
        self._check()
        if self.execution_dispatcher is None:
            raise ValueError('No Architect original action recovery is configured')
        result = self.execution_dispatcher.wait_recovery_sources(identity=identity, journal_path=journal_path,
            check_application=self._check, close=self.close)
        self._check()
        return result

    def reconcile_billing_internal_cost(self, identity, *, signal):
        """Archive actual native internal cost accounting without creating self fees or cash."""
        from integration.architect_billing_terminal import reconcile_architect_billing_internal_cost
        self._check()
        settings = self.settings.execution_recovery
        if (self.settings.action_id != 'ARCHITECT-A10' or not isinstance(settings, ArchitectBillingRecoverySettings)
                or not settings.terminal_internal_cost_enabled or self.execution_dispatcher is None):
            raise ValueError('Internal cost archival requires explicit A10 native accounting configuration')
        recovery = self.dependencies.execution_recovery
        with recovery.read_guard(run_id=identity.run_id, organization_id=identity.organization_id):
            self._check()
            result = reconcile_architect_billing_internal_cost(identity=identity, signal=signal,
                reader=self.receipt_reader, dispatcher=self.execution_dispatcher.dispatcher,
                validate_relation=recovery.validate_relation)
            self._check()
            return result

    def reconcile_billing_received_reminder(self, identity, *, signal):
        """Archive an unnecessary A10 reminder only after native receipt history authentication."""
        from integration.architect_billing_terminal import reconcile_architect_billing_received_reminder
        self._check()
        settings = self.settings.execution_recovery
        if (self.settings.action_id != 'ARCHITECT-A10' or not isinstance(settings, ArchitectBillingRecoverySettings)
                or not settings.terminal_receipt_enabled or self.execution_dispatcher is None):
            raise ValueError('Received fee reminder archival requires explicit A10 receipt configuration')
        recovery = self.dependencies.execution_recovery
        with recovery.read_guard(run_id=identity.run_id, organization_id=identity.organization_id):
            self._check()
            result = reconcile_architect_billing_received_reminder(identity=identity, signal=signal,
                reader=self.receipt_reader, dispatcher=self.execution_dispatcher.dispatcher,
                validate_relation=recovery.validate_relation)
            self._check()
            return result

    def reconcile_billing_claim(self, identity, *, signal):
        """Archive original A10 claim status without repeating billing or recording cash."""
        from integration.architect_billing_terminal import reconcile_architect_billing_claim
        self._check()
        settings = self.settings.execution_recovery
        if (self.settings.action_id != 'ARCHITECT-A10' or not isinstance(settings, ArchitectBillingRecoverySettings)
                or not settings.terminal_claim_enabled or self.execution_dispatcher is None):
            raise ValueError('Fee claim archival requires explicit A10 terminal configuration')
        recovery = self.dependencies.execution_recovery
        with recovery.read_guard(run_id=identity.run_id, organization_id=identity.organization_id):
            self._check()
            result = reconcile_architect_billing_claim(identity=identity, signal=signal,
                reader=self.receipt_reader, dispatcher=self.execution_dispatcher.dispatcher,
                validate_relation=recovery.validate_relation)
            self._check()
            return result

    def reconcile_design_submission(self, identity, *, signal):
        """Archive observed original A05 registration status without repeating design production."""
        from integration.architect_design_terminal import reconcile_architect_design_submission
        self._check()
        settings = self.settings.execution_recovery
        if (self.settings.action_id != 'ARCHITECT-A05' or not isinstance(settings, ArchitectDesignRecoverySettings)
                or not settings.terminal_submission_enabled or self.execution_dispatcher is None):
            raise ValueError('Design submission archival requires explicit A05 terminal configuration')
        recovery = self.dependencies.execution_recovery
        with recovery.read_guard(run_id=identity.run_id, organization_id=identity.organization_id):
            self._check()
            result = reconcile_architect_design_submission(identity=identity, signal=signal,
                reader=self.receipt_reader, dispatcher=self.execution_dispatcher.dispatcher,
                validate_relation=recovery.validate_relation)
            self._check()
            return result

    def reconcile_transition_execution(self, identity, *, signal):
        """Archive actual same-business A11 disposition without repeating the transition."""
        from integration.architect_transition_terminal import reconcile_architect_transition_execution
        self._check()
        settings = self.settings.execution_recovery
        if (self.settings.action_id != 'ARCHITECT-A11' or not isinstance(settings, ArchitectTransitionRecoverySettings)
                or not settings.terminal_execution_enabled or self.execution_dispatcher is None):
            raise ValueError('Service execution reconciliation requires explicit A11 terminal configuration')
        recovery = self.dependencies.execution_recovery
        with recovery.read_guard(run_id=identity.run_id, organization_id=identity.organization_id):
            self._check()
            result = reconcile_architect_transition_execution(identity=identity, signal=signal,
                reader=self.receipt_reader, dispatcher=self.execution_dispatcher.dispatcher,
                validate_relation=recovery.validate_relation)
            self._check()
            return result

    def reconcile_learning_execution(self, identity, *, signal):
        """Archive actual same-business A12 disposition under the original source guard."""
        from integration.architect_learning_terminal import reconcile_architect_learning_execution
        self._check()
        settings = self.settings.execution_recovery
        if (self.settings.action_id != 'ARCHITECT-A12' or not isinstance(settings, ArchitectLearningRecoverySettings)
                or not settings.terminal_execution_enabled or self.execution_dispatcher is None):
            raise ValueError('Learning execution reconciliation requires explicit A12 terminal configuration')
        recovery = self.dependencies.execution_recovery
        with recovery.read_guard(run_id=identity.run_id, organization_id=identity.organization_id):
            self._check()
            result = reconcile_architect_learning_execution(identity=identity, signal=signal,
                reader=self.receipt_reader, dispatcher=self.execution_dispatcher.dispatcher,
                validate_relation=recovery.validate_relation)
            self._check()
            return result

    def reconcile_applied_feedback(self, identity, *, signal):
        """Archive actual application of the original feedback without applying it again."""
        from integration.architect_learning_terminal import reconcile_architect_applied_feedback
        self._check()
        settings = self.settings.execution_recovery
        if (self.settings.action_id != 'ARCHITECT-A12' or not isinstance(settings, ArchitectLearningRecoverySettings)
                or not settings.terminal_applied_feedback_enabled or self.execution_dispatcher is None):
            raise ValueError('Applied-feedback reconciliation requires explicit A12 terminal configuration')
        recovery = self.dependencies.execution_recovery
        with recovery.read_guard(run_id=identity.run_id, organization_id=identity.organization_id):
            self._check()
            result = reconcile_architect_applied_feedback(identity=identity, signal=signal,
                reader=self.receipt_reader, dispatcher=self.execution_dispatcher.dispatcher,
                validate_relation=recovery.validate_relation)
            self._check()
            return result

    def record_feedback(self, identity, *, context, reading, observation):
        """Explicitly correlate actual feedback under current source/authorization guard."""
        self._check()
        if self.feedback is None:
            raise ValueError('No Architect actual feedback inbox is configured')
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
            raise ValueError('No Architect actual feedback inbox is configured')
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
    config = ArchitectFormalApplicationSettings.model_validate(settings).model_copy(deep=True)
    request = RoleContractInvocation.model_validate(request).model_copy(deep=True)
    if (offline is not False or request.context.execution_mode != 'llm'
            or request.context.contract_ref.id != config.action_id or config.action_id not in _ACTIONS):
        raise ValueError('Formal Architect source factory requires its explicit non-offline original invocation')
    factory = _load_factory(config.dependency_factory)
    descriptor = module_factory_descriptor(factory, config.dependency_factory)
    dependencies = factory(request=request.model_copy(deep=True), output_directory=Path(output_directory),
        offline=False, settings=deepcopy(config.dependency_settings))
    if not isinstance(dependencies, ArchitectFormalApplicationDependencies):
        raise ValueError('Actual Architect dependency factory must return ArchitectFormalApplicationDependencies')
    application = None
    try:
        if module_factory_descriptor(factory, config.dependency_factory) != descriptor:
            raise TaskConflict('Actual Architect dependency factory changed during assembly')
        application = ArchitectFormalApplication(request=request, settings=config,
            dependencies=dependencies, factory_descriptor=descriptor)
        return application.sources()
    except Exception:
        if application is not None:
            application.close()
        else:
            dependencies.sources.close()
        raise
