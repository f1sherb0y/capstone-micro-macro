"""Freeze original QS A01 opportunities, price sources and bounded preparation inputs."""
from dataclasses import dataclass
from typing import ClassVar

from integration.action_model_host import resolve_action_model_host
from integration.macro_views import AuthorizedMacroViewAssembler
from src.actions.contracts.qs_market_objects import (
    QSMarketStrategyView, QSMarketOpportunityView, QSMarketTriggerView,
    QSMarketPriceSourceView, QSMarketRequestView, QSMarketResearchAuthorityView, qs_market_schemas,
)
from src.actions.contracts.common import ActionContext, walk_references
from src.actions.contracts.domain import CandidateSet
from src.actions.contracts.owner_study_objects import unique_refs
from src.actions.contracts.references import ActionReadView, ReferenceResolver
from src.actions.runner import ActionRunner
from src.coordination.tasks import TaskConflict, task_digest
from src.organization.registry import scope_covers


@dataclass(frozen=True)
class PreparedQSMarket:
    ACTION_ID: ClassVar[str] = 'QS-A01'
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


class QSMarketActionAssembler:
    """Freeze original discovery sources under the application's current read guard.

    Permission, source authenticity/applicability, selected strategy and finite
    research effort/budget remain original processor decisions. A nullable
    research authority stays null. Assembly creates no observation, price,
    preparation task, commitment, fee or shared opportunity change.
    """
    ACTION_ID = 'QS-A01'
    SOURCE_SCHEMAS = staticmethod(qs_market_schemas)

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

    def build(self, context, *, scope, opportunity_refs, price_source_refs, strategy_ref, research_authority_ref):
        return self._prepare_supplied_snapshot(context, input_values={
            'scope': scope, 'opportunity_refs': opportunity_refs, 'price_source_refs': price_source_refs,
            'strategy_ref': strategy_ref, 'research_authority_ref': research_authority_ref},
            prepared_type=PreparedQSMarket, validate_sources=validate_qs_market_sources)

    def _prepare_supplied_snapshot(self, context, *, input_values, prepared_type, validate_sources):
        """Freeze QS sources while leaving action-specific checks explicit."""
        context = self._context(context)
        registration = self.registry.get(self.ACTION_ID)
        if registration.role != 'QS' or not registration.implemented or registration.skill is None:
            raise ValueError('Opportunity assembly requires its actual processor and bound QS Skill')
        action_input = registration.contract.validate_input(input_values)
        projection = self._views.assemble(context, self.ACTION_ID, 'QS')
        resolver = ReferenceResolver(context.run_id, source_mode=self.source_mode,
            schemas=self.SOURCE_SCHEMAS())
        for row in projection.objects:
            resolver.register_projection(row.ref, row.value)
        resolver.freeze_read(context.read_token, [row.ref for row in projection.objects])
        runner = ActionRunner(self.registry, organizations=self.organizations, references=resolver,
            methods=self.methods, audit_sink=self.audit_sink, policy_version=self.policy_version,
            model_version=self.model_version, decision_strategies=self.decision_strategies)
        reading = ActionReadView(context, resolver, self.organizations, self.ACTION_ID, 'QS',
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
            raise ValueError('QS assembly requires its original action contract and explicit source mode')
        return context

    def build_result_reading(self, context):
        """Create a fresh authorized boundary for explicit own-result reads."""
        context = self._context(context)
        resolver = self._views.build_resolver(context, self.ACTION_ID, 'QS')
        return ActionReadView(context, resolver, self.organizations, self.ACTION_ID, 'QS')


def validate_qs_market_sources(action_input, *, context, organization_id, sources):
    """Check original private strategy and supplied source identities only."""
    def read(ref, schema):
        row = sources.get(ref.key())
        if not isinstance(row, schema) or row.ref.key() != ref.key():
            raise TaskConflict('QS market lacks its exact original concrete source')
        if not scope_covers(row.scope, context.scope):
            raise TaskConflict('QS market source does not cover its original invocation scope')
        return row

    if action_input.scope != context.scope:
        raise TaskConflict('QS market changes its original invocation scope')
    unique_refs(action_input.opportunity_refs)
    unique_refs(action_input.price_source_refs)
    strategy = read(action_input.strategy_ref, QSMarketStrategyView)
    if strategy.organization_id != organization_id:
        raise TaskConflict('QS market strategy changes its original private organization')
    for ref in action_input.opportunity_refs:
        opportunity = read(ref, QSMarketOpportunityView)
        if opportunity.trigger_ref is not None and opportunity.trigger_ref.key() in sources:
            trigger = read(opportunity.trigger_ref, QSMarketTriggerView)
            if trigger.opportunity_ref.key() != opportunity.ref.key() or trigger.scope != opportunity.scope:
                raise TaskConflict('QS market trigger changes its original opportunity or scope')
    for ref in action_input.price_source_refs:
        read(ref, QSMarketPriceSourceView)
    request = None
    if strategy.preparation_ref is not None and strategy.preparation_ref.key() in sources:
        request = read(strategy.preparation_ref, QSMarketRequestView)
        if request.strategy_ref.key() != strategy.ref.key():
            raise TaskConflict('QS preparation request changes its original strategy')
    if action_input.research_authority_ref is not None:
        authority = read(action_input.research_authority_ref, QSMarketResearchAuthorityView)
        if (authority.organization_id != organization_id or authority.strategy_ref.key() != strategy.ref.key()
                or authority.delegate_actor_id != context.actor_id
                or authority.delegate_function_ref.key() != context.function_ref.key()
                or request is not None and authority.request_profile_ref.key() != request.ref.key()):
            raise TaskConflict('QS research authority changes its original organization, delegate or request')
    # The processor preserves unknown/secret/unauthorized source restrictions,
    # exact candidate coverage, finite preparation limits and all five choices.
