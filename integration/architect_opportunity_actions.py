"""Freeze original Architect A01 business-discovery and bounded preparation inputs."""
from dataclasses import dataclass
from typing import ClassVar

from integration.action_model_host import resolve_action_model_host
from integration.macro_views import AuthorizedMacroViewAssembler
from src.actions.contracts.architect_opportunity_objects import (
    ArchitectOpportunityView, ArchitectOpportunityStrategyView, ArchitectOpportunityTriggerView,
    ArchitectPreparationRequestView, ArchitectPreparationAuthorityView, ArchitectPreparationEstimateView,
    ArchitectOpportunityReferenceView, architect_opportunity_schemas,
)
from src.actions.contracts.common import ActionContext, walk_references
from src.actions.contracts.domain import CandidateSet
from src.actions.contracts.owner_study_objects import unique_refs
from src.actions.contracts.references import ActionReadView, ReferenceResolver
from src.actions.contracts.service_objects import ServiceResourceCalendarView
from src.actions.runner import ActionRunner
from src.coordination.tasks import TaskConflict, task_digest
from src.organization.registry import scope_covers


@dataclass(frozen=True)
class PreparedArchitectOpportunity:
    ACTION_ID: ClassVar[str] = 'ARCHITECT-A01'
    context: ActionContext
    action_input: object
    runner: ActionRunner
    reading: ActionReadView
    input_sha256: str
    context_sha256: str
    reading_sha256: str

    def execute(self, *, execution_path=None):
        """Evaluate the original invocation without sending or releasing anything."""
        if (task_digest(self.action_input.model_dump(mode='json')) != self.input_sha256
                or task_digest(self.context.model_dump(mode='json')) != self.context_sha256
                or task_digest(self.reading.evidence()) != self.reading_sha256
                or self.runner.references is not self.reading._resolver
                or self.runner.organizations is not self.reading._organizations):
            raise TaskConflict('Prepared opportunity changed its original input, context or authorized sources')
        self.reading.check_method_context(self.context, self.ACTION_ID)
        self.reading.recheck()
        return self.runner.run_action(self.context, self.action_input, execution_path=execution_path)


class ArchitectOpportunityActionAssembler:
    """Freeze original discovery sources under the application's current read guard.

    Permission, source confirmation, finite effort/budget, independent authority
    and capacity checks remain in the original processor. A null preparation
    authority stays null. Assembly creates no appointment, preparation task,
    resource reservation, fee, income or shared opportunity change.
    """
    ACTION_ID = 'ARCHITECT-A01'
    SOURCE_SCHEMAS = staticmethod(architect_opportunity_schemas)

    def __init__(self, *, registry, organizations, provider, macro_version,
            source_mode, methods=None, audit_sink=None, policy_version=None,
            model_version=None, decision_strategies=(), model_host=None):
        model_version, bindings = resolve_action_model_host(registry=registry,
            run_id=organizations.run_id, model_version=model_version,
            decision_strategies=decision_strategies, model_host=model_host)
        self.registry, self.organizations, self.provider = registry, organizations, provider
        self.macro_version, self.source_mode = macro_version, source_mode
        self.methods, self.audit_sink = methods, audit_sink
        self.policy_version, self.model_version = policy_version, model_version
        self.decision_strategies = bindings
        self._views = AuthorizedMacroViewAssembler(organizations, provider,
            self.SOURCE_SCHEMAS(), macro_version=macro_version, source_mode=source_mode)

    def build(self, context, *, scope, opportunity_ref, strategy_ref, capacity_ref, preparation_authority_ref):
        return self._prepare_supplied_snapshot(context, input_values={
            'scope': scope, 'opportunity_ref': opportunity_ref, 'strategy_ref': strategy_ref,
            'capacity_ref': capacity_ref, 'preparation_authority_ref': preparation_authority_ref},
            prepared_type=PreparedArchitectOpportunity, validate_sources=validate_architect_opportunity_sources)

    def _prepare_supplied_snapshot(self, context, *, input_values, prepared_type, validate_sources):
        """Freeze Architect sources while leaving action-specific checks explicit."""
        context = self._context(context)
        registration = self.registry.get(self.ACTION_ID)
        if registration.role != 'Architect' or not registration.implemented or registration.skill is None:
            raise ValueError('Opportunity assembly requires its actual processor and bound Architect Skill')
        action_input = registration.contract.validate_input(input_values)
        projection = self._views.assemble(context, self.ACTION_ID, 'Architect')
        resolver = ReferenceResolver(context.run_id, source_mode=self.source_mode,
            schemas=self.SOURCE_SCHEMAS())
        for row in projection.objects:
            resolver.register_projection(row.ref, row.value)
        resolver.freeze_read(context.read_token, [row.ref for row in projection.objects])
        runner = ActionRunner(self.registry, organizations=self.organizations, references=resolver,
            methods=self.methods, audit_sink=self.audit_sink, policy_version=self.policy_version,
            model_version=self.model_version, decision_strategies=self.decision_strategies)
        reading = ActionReadView(context, resolver, self.organizations, self.ACTION_ID, 'Architect',
            methods=runner.methods, method_refs=registration.skill.manifest.method_refs)
        try:
            # Preserve all supplied sources, including output dependencies,
            # without evaluating preparation effort, cost or business eligibility.
            for row in projection.objects:
                reading.resolve(row.ref)
            for ref in walk_references(action_input):
                reading.resolve(ref)
            validate_sources(action_input, context=context,
                organization_id=reading.organization_id, sources=reading._reads)
            candidates = reading.resolve(context.candidate_set_ref)
            if not isinstance(candidates, CandidateSet):
                raise ValueError('Opportunity assembly requires its original authorized candidate set')
            candidates.check_context(context, registration.contract.choices)
            for candidate in candidates.candidates:
                reading.resolve(candidate.ref)
            return prepared_type(context, action_input, runner, reading,
                task_digest(action_input.model_dump(mode='json')),
                task_digest(context.model_dump(mode='json')), task_digest(reading.evidence()))
        finally:
            reading.recheck()

    def _context(self, context):
        context = ActionContext.model_validate(context).model_copy(deep=True)
        if (context.contract_ref.kind != 'ActionContract' or context.contract_ref.id != self.ACTION_ID
                or (self.source_mode == 'fixture') != (context.execution_mode == 'offline_fixture')):
            raise ValueError('Architect assembly requires its original action contract and explicit source mode')
        return context

    def build_result_reading(self, context):
        """Create a fresh authorized boundary for explicit own-result reads."""
        context = self._context(context)
        resolver = self._views.build_resolver(context, self.ACTION_ID, 'Architect')
        return ActionReadView(context, resolver, self.organizations, self.ACTION_ID, 'Architect')



def validate_architect_opportunity_sources(action_input, *, context, organization_id, sources):
    """Preserve original opportunity and delegation identities without business evaluation."""
    def read(ref, schema):
        row = sources.get(ref.key())
        if not isinstance(row, schema) or row.ref.key() != ref.key():
            raise TaskConflict('Architect opportunity lacks its exact original concrete source')
        if hasattr(row, 'scope') and not scope_covers(row.scope, context.scope):
            raise TaskConflict('Architect opportunity source changes its original invocation scope')
        return row

    if action_input.scope != context.scope:
        raise TaskConflict('Architect opportunity input changes its original invocation scope')
    opportunity = read(action_input.opportunity_ref, ArchitectOpportunityView)
    strategy = read(action_input.strategy_ref, ArchitectOpportunityStrategyView)
    calendar = read(action_input.capacity_ref, ServiceResourceCalendarView)
    if (strategy.organization_id != organization_id or calendar.organization_id != organization_id
            or strategy.opportunity_ref.key() != opportunity.ref.key()
            or strategy.capacity_ref.key() != calendar.ref.key()):
        raise TaskConflict('Architect discovery changes original organization, opportunity, strategy or calendar')
    if opportunity.watch_condition_ref is not None and opportunity.watch_condition_ref.key() in sources:
        trigger = read(opportunity.watch_condition_ref, ArchitectOpportunityTriggerView)
        if trigger.organization_id != organization_id or trigger.opportunity_ref.key() != opportunity.ref.key():
            raise TaskConflict('Architect watch condition changes its original recipient or opportunity')
    request = None
    if strategy.preparation_ref is not None and strategy.preparation_ref.key() in sources:
        request = read(strategy.preparation_ref, ArchitectPreparationRequestView)
        if (request.opportunity_ref.key() != opportunity.ref.key() or request.strategy_ref.key() != strategy.ref.key()
                or request.scope != context.scope):
            raise TaskConflict('Architect preparation profile changes its original opportunity, strategy or scope')
        for refs in (request.input_refs, request.output_requirement_refs, request.authority_basis_refs, request.dependency_refs):
            unique_refs(refs)
        if request.estimate_result_ref is not None and request.estimate_result_ref.key() in sources:
            estimate = read(request.estimate_result_ref, ArchitectPreparationEstimateView)
            if (estimate.opportunity_ref.key() != opportunity.ref.key() or estimate.request_profile_ref.key() != request.ref.key()
                    or estimate.work_profile_ref != request.work_profile_ref or set(estimate.input_refs) != set(request.input_refs)
                    or estimate.estimated_cost != request.estimated_cost or estimate.effort_estimate != request.effort_estimate):
                raise TaskConflict('Architect preparation estimate changes original request, inputs or estimates')
            unique_refs(estimate.input_refs)
    for question in [*opportunity.questions, *(request.questions if request is not None else [])]:
        for ref in [*question.target_refs, question.response_requirement_ref]:
            if ref.key() in sources and read(ref, ArchitectOpportunityReferenceView).opportunity_ref.key() != opportunity.ref.key():
                raise TaskConflict('Architect question changes its original opportunity target')
    if action_input.preparation_authority_ref is not None:
        grant = read(action_input.preparation_authority_ref, ArchitectPreparationAuthorityView)
        if (grant.organization_id != organization_id or grant.actor_id != context.actor_id
                or grant.function_ref.key() != context.function_ref.key()
                or grant.opportunity_ref.key() != opportunity.ref.key()
                or request is not None and (grant.request_profile_ref.key() != request.ref.key()
                    or request.authority_basis_refs != [grant.ref])):
            raise TaskConflict('Architect preparation changes original delegate, opportunity or request authority')
