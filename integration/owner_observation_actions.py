"""Assemble explicit authorized OWN-A01 inputs without creating cases or rights."""
from dataclasses import dataclass
from typing import ClassVar

from integration.action_model_host import resolve_action_model_host
from integration.macro_views import AuthorizedMacroViewAssembler
from src.actions.contracts.common import ActionContext, walk_references
from src.actions.contracts.domain import CandidateSet
from src.actions.contracts.owner_objects import (
    OwnerCaseView, OwnerManagementCapacityView, OwnerObjectiveView, owner_observation_schemas,
)
from src.actions.contracts.references import ActionReadView, ReferenceResolver
from src.actions.runner import ActionRunner
from src.coordination.tasks import TaskConflict, task_digest


@dataclass(frozen=True)
class PreparedOwnerObservation:
    ACTION_ID: ClassVar[str] = 'OWN-A01'
    context: ActionContext
    action_input: object
    runner: ActionRunner
    reading: ActionReadView
    input_sha256: str
    context_sha256: str
    reading_sha256: str

    def execute(self, *, execution_path=None):
        if (task_digest(self.action_input.model_dump(mode='json')) != self.input_sha256
                or task_digest(self.context.model_dump(mode='json')) != self.context_sha256
                or task_digest(self.reading.evidence()) != self.reading_sha256
                or self.runner.references is not self.reading._resolver
                or self.runner.organizations is not self.reading._organizations):
            raise TaskConflict('Prepared owner observation changed its original input, context or authorized sources')
        self.reading.check_method_context(self.context, self.ACTION_ID)
        self.reading.recheck()
        return self.runner.run_action(self.context, self.action_input, execution_path=execution_path)


class OwnerObservationActionAssembler:
    """Freeze supplied projections and exact input; leave all branches to A01.

    The application supplies its provider and holds its source/authorization
    guard while preparing and executing. No observation, private case, project,
    right or management reservation is fabricated by this assembly boundary.
    """
    ACTION_ID = 'OWN-A01'
    SOURCE_SCHEMAS = staticmethod(owner_observation_schemas)

    def __init__(self, *, registry, organizations, provider, macro_version, source_mode,
            methods=None, audit_sink=None, policy_version=None, model_version=None,
            decision_strategies=(), model_host=None):
        model_version, bindings = resolve_action_model_host(registry=registry,
            run_id=organizations.run_id, model_version=model_version,
            decision_strategies=decision_strategies, model_host=model_host)
        self.registry, self.organizations, self.provider = registry, organizations, provider
        self.macro_version, self.source_mode = macro_version, source_mode
        self.methods, self.audit_sink = methods, audit_sink
        self.policy_version, self.model_version = policy_version, model_version
        self.decision_strategies = bindings
        self._views = AuthorizedMacroViewAssembler(organizations, provider, self.SOURCE_SCHEMAS(),
            macro_version=macro_version, source_mode=source_mode)

    def build(self, context, *, scope_ref, objective_ref, observations, opportunity_refs,
            existing_case_refs, capacity_ref):
        return self._prepare_supplied_snapshot(context,
            input_values={'scope_ref': scope_ref, 'objective_ref': objective_ref, 'observations': observations,
                'opportunity_refs': opportunity_refs, 'existing_case_refs': existing_case_refs, 'capacity_ref': capacity_ref},
            prepared_type=PreparedOwnerObservation, validate_sources=self._validate_observation_sources)

    @staticmethod
    def _validate_observation_sources(action_input, *, context, reading):
        validate_owner_observation_sources(action_input, context=context,
            organization_id=reading.organization_id, sources=reading._reads)

    def _prepare_supplied_snapshot(self, context, *, input_values, prepared_type, validate_sources):
        """Shared Owner source assembly; action-specific identity checks stay explicit."""
        context = ActionContext.model_validate(context).model_copy(deep=True)
        if (context.contract_ref.kind != 'ActionContract' or context.contract_ref.id != self.ACTION_ID
                or (self.source_mode == 'fixture') != (context.execution_mode == 'offline_fixture')):
            raise ValueError('Owner assembly requires its original action contract and explicit source mode')
        registration = self.registry.get(self.ACTION_ID)
        if registration.role != 'Owner' or not registration.implemented or registration.skill is None:
            raise ValueError('Owner observation requires its implemented processor and original Skill')
        action_input = registration.contract.validate_input(input_values)
        projection = self._views.assemble(context, self.ACTION_ID, 'Owner')
        resolver = ReferenceResolver(context.run_id, source_mode=self.source_mode, schemas=self.SOURCE_SCHEMAS())
        for row in projection.objects:
            resolver.register_projection(row.ref, row.value)
        resolver.freeze_read(context.read_token, [row.ref for row in projection.objects])
        runner = ActionRunner(self.registry, organizations=self.organizations, references=resolver,
            methods=self.methods, audit_sink=self.audit_sink, policy_version=self.policy_version,
            model_version=self.model_version, decision_strategies=self.decision_strategies)
        reading = ActionReadView(context, resolver, self.organizations, self.ACTION_ID, 'Owner',
            methods=runner.methods, method_refs=registration.skill.manifest.method_refs)
        try:
            # Include all actually supplied output-only dependencies in the
            # source digest without evaluating evidence, policy or methods.
            for row in projection.objects:
                reading.resolve(row.ref)
            for ref in walk_references(action_input):
                reading.resolve(ref)
            validate_sources(action_input, context=context, reading=reading)
            candidates = reading.resolve(context.candidate_set_ref)
            if not isinstance(candidates, CandidateSet):
                raise ValueError('Owner observation requires its original authorized candidate set')
            candidates.check_context(context, registration.contract.choices)
            for candidate in candidates.candidates:
                reading.resolve(candidate.ref)
            return prepared_type(context, action_input, runner, reading,
                task_digest(action_input.model_dump(mode='json')), task_digest(context.model_dump(mode='json')),
                task_digest(reading.evidence()))
        finally:
            reading.recheck()

    def build_result_reading(self, context):
        """Create a current A01 read boundary for explicit own-history access."""
        context = ActionContext.model_validate(context).model_copy(deep=True)
        if (context.contract_ref.kind != 'ActionContract' or context.contract_ref.id != self.ACTION_ID
                or (self.source_mode == 'fixture') != (context.execution_mode == 'offline_fixture')):
            raise ValueError('Owner observation history requires its explicit action and source mode')
        resolver = self._views.build_resolver(context, self.ACTION_ID, 'Owner')
        return ActionReadView(context, resolver, self.organizations, self.ACTION_ID, 'Owner')


def validate_owner_observation_sources(action_input, *, context, organization_id, sources):
    """Validate supplied/current or persisted original A01 sources without a judgment."""
    if action_input.scope_ref != context.scope:
        raise TaskConflict('Owner observation input changes the original invocation scope')
    for refs in (action_input.observations, action_input.opportunity_refs, action_input.existing_case_refs):
        if len({(ref.kind, ref.id) for ref in refs}) != len(refs):
            raise TaskConflict('Owner observation input repeats a physical source or case')
    objective = sources.get(action_input.objective_ref.key())
    capacity = sources.get(action_input.capacity_ref.key())
    if (not isinstance(objective, OwnerObjectiveView) or not isinstance(capacity, OwnerManagementCapacityView)
            or objective.organization_id != organization_id or capacity.organization_id != organization_id
            or context.scope.kind == 'organization' and context.scope.ref.id != organization_id):
        raise TaskConflict('Owner observation substitutes another organization objective, capacity or scope')
    for ref in action_input.existing_case_refs:
        case = sources.get(ref.key())
        if not isinstance(case, OwnerCaseView) or case.organization_id != organization_id:
            raise TaskConflict('Owner observation substitutes another owner private case')
