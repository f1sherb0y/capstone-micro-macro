"""Build Contractor A02 invocations from the host's original authorized facts."""
from dataclasses import dataclass
from types import SimpleNamespace

from integration.macro_views import AuthorizedMacroViewAssembler
from src.actions.contracts.common import ActionContext, Reference, walk_references
from src.actions.contracts.contractor_bid_objects import (
    ContractorBidCapacityView, ContractorBidCostView, ContractorBidPackageView,
    ContractorBidProfileView, contractor_bid_schemas,
)
from src.actions.contracts.domain import CandidateSet
from src.actions.contracts.owner_study_objects import unique_refs
from src.actions.contracts.references import ActionReadView
from src.actions.runner import ActionRunner
from src.coordination.tasks import task_digest


@dataclass(frozen=True)
class PreparedContractorBid:
    context: ActionContext
    action_input: object
    runner: ActionRunner
    reading: ActionReadView
    input_sha256: str
    context_sha256: str
    reading_sha256: str

    def execute(self, *, execution_path=None):
        """Run the registered business checks; this forms no macro bid or effect."""
        if (task_digest(self.action_input.model_dump(mode='json')) != self.input_sha256
                or task_digest(self.context.model_dump(mode='json')) != self.context_sha256):
            raise ValueError('Prepared bid changed; assemble its original authorized version again')
        self.reading.recheck()
        return self.runner.run_action(self.context, self.action_input, execution_path=execution_path)


class ContractorBidActionAssembler:
    """Read original package/profile references; require an explicit cost set.

    Source objects, quantities, methods, cost completeness, programme, rates,
    productivity and financial indicators are never guessed. Assembly checks
    identity and reference relationships. The original A02 processor retains
    the eligibility, coverage, programme, capacity and pricing business checks,
    including needs_information/unsupported and an explicit commercial decline.
    """

    @staticmethod
    def SOURCE_SCHEMAS():
        """Expose the same original schemas used by the action's source reader."""
        from integration.bindings.gba_v1_bid_capacity import gba_bid_capacity_source_schemas
        return gba_bid_capacity_source_schemas()

    def __init__(self, *, registry, organizations, provider, macro_version,
            source_mode, methods=None, audit_sink=None, policy_version=None,
            model_version=None, decision_strategies=(), model_host=None):
        from integration.action_model_host import resolve_action_model_host

        model_version, decision_strategies = resolve_action_model_host(registry=registry,
            run_id=organizations.run_id, model_version=model_version,
            decision_strategies=decision_strategies, model_host=model_host)
        self.registry, self.organizations = registry, organizations
        self.methods, self.audit_sink = methods, audit_sink
        self.policy_version, self.model_version = policy_version, model_version
        self.decision_strategies = tuple(decision_strategies)
        self.source_mode = source_mode
        self.provider, self.macro_version = provider, macro_version
        self._result_views = None
        schemas = self.SOURCE_SCHEMAS()
        self._views = AuthorizedMacroViewAssembler(organizations, provider, schemas,
            macro_version=macro_version, source_mode=source_mode)

    def check_execution_versions(self, identity, *, context):
        """Authenticate micro versions against this configured action runtime.

        Native transport versions describe the module, not the A02 Skill,
        prompt, contract, methods and strategy. Recompute all seven action
        versions without executing a processor or opening historical sources.
        """
        from integration.action_versions import prepared_action_execution_versions
        from src.coordination.tasks import TaskConflict

        context = ActionContext.model_validate(context)
        if (identity.run_id != self.organizations.run_id or identity.action_id != 'CONTRACTOR-A02'
                or identity.role != 'Contractor' or context.run_id != identity.run_id
                or context.contract_ref.id != identity.action_id
                or task_digest(context.model_dump(mode='json')) != identity.context_sha256):
            raise TaskConflict('Saved bid execution versions require the original action and context')
        runner = ActionRunner(self.registry, organizations=self.organizations,
            methods=self.methods, audit_sink=self.audit_sink, policy_version=self.policy_version,
            model_version=self.model_version, decision_strategies=self.decision_strategies,
            retain_reading_evidence=True)
        # The version function reads only context and runner configuration.
        configured = SimpleNamespace(context=context, runner=runner)
        expected = prepared_action_execution_versions(configured,
            client_version=identity.versions['client'], model_version=identity.versions['model'])
        if identity.versions != expected:
            raise TaskConflict('Saved bid Skill, prompt, contract, methods or strategy changed; no silent migration')

    def build_from_screening(self, context, *, screening, screening_result, screening_audit,
            handoff_basis_ref, validate_current, **bid_refs):
        """Connect an explicitly evidenced A01 participation to independently assembled A02."""
        from integration.contractor_procurement_handoff import prepare_contractor_procurement_handoff

        prepared = self.build(context, **bid_refs)
        return prepare_contractor_procurement_handoff(screening,screening_result,screening_audit,
            prepared,basis_ref=Reference.model_validate(handoff_basis_ref),validate_current=validate_current)

    def build_capacity_reading(self, context):
        """Read source mapping/facts before the capacity target has been published."""
        context = ActionContext.model_validate(context).model_copy(deep=True)
        if context.contract_ref.kind != 'ActionContract' or context.contract_ref.id != 'CONTRACTOR-A02':
            raise ValueError('Capacity source reading requires the actual A02 context')
        if self.source_mode == 'fixture' and context.execution_mode != 'offline_fixture':
            raise ValueError('Fixture source reading requires explicit offline_fixture execution')
        registration = self.registry.get('CONTRACTOR-A02')
        if not registration.implemented or registration.skill is None:
            raise ValueError('Capacity source reading requires its registered action and bound Skill')
        resolver = self._views.build_resolver(context,registration.action_id,registration.role)
        return ActionReadView(context,resolver,self.organizations,registration.action_id,registration.role)

    def prepare_cost_projection(self, context, *, adoption_ref, validate_current):
        """Produce one explicitly adopted original-price line before host publication."""
        from integration.contractor_bid_costs import prepare_contractor_bid_cost

        context = ActionContext.model_validate(context).model_copy(deep=True)
        return prepare_contractor_bid_cost(context=context, reading=self.build_capacity_reading(context),
            adoption_ref=adoption_ref, validate_current=validate_current)

    def prepare_quantity_projection(self, context, *, source_provider, mapping_ref, validate_current):
        """Use a separate original QS source provider without replacing A02 schemas."""
        from integration.contractor_bid_quantities import prepare_contractor_bid_quantity

        context = ActionContext.model_validate(context).model_copy(deep=True)
        reading = self.build_capacity_reading(context)
        source_reading = self.build_quantity_source_reading(context, source_provider=source_provider)
        return prepare_contractor_bid_quantity(context=context, reading=reading, source_reading=source_reading,
            mapping_ref=mapping_ref, validate_current=validate_current)

    def prepare_programme_projection(self, context, *, basis_ref, validate_current):
        """Produce whole-line task targets from original quantities and explicit host instructions."""
        from integration.contractor_bid_programme import prepare_contractor_bid_programme

        context = ActionContext.model_validate(context).model_copy(deep=True)
        return prepare_contractor_bid_programme(context=context, reading=self.build_capacity_reading(context),
            basis_ref=basis_ref, validate_current=validate_current)

    def build_quantity_source_reading(self, context, *, source_provider):
        """Expose the separate original QS reading for guarded quantity publication."""
        from integration.contractor_bid_quantities import contractor_quantity_source_schemas

        context = ActionContext.model_validate(context).model_copy(deep=True)
        if (context.contract_ref.kind != 'ActionContract' or context.contract_ref.id != 'CONTRACTOR-A02'
                or self.source_mode == 'fixture' and context.execution_mode != 'offline_fixture'):
            raise ValueError('Original quantity reading requires its explicit A02 source context')
        views = AuthorizedMacroViewAssembler(self.organizations, source_provider,
            contractor_quantity_source_schemas(), macro_version=self.macro_version, source_mode=self.source_mode)
        resolver = views.build_resolver(context, 'CONTRACTOR-A02', 'Contractor')
        return ActionReadView(context, resolver, self.organizations, 'CONTRACTOR-A02', 'Contractor')

    def build_result_reading(self, context):
        """Read original saved bid versions and a fresh independent GBA mapping."""
        from integration.bindings.gba_v1_tender_proposal import gba_tender_proposal_source_schemas

        context = ActionContext.model_validate(context).model_copy(deep=True)
        if (context.contract_ref.kind != 'ActionContract' or context.contract_ref.id != 'CONTRACTOR-A02'
                or context.execution_mode == 'offline_fixture' or self.source_mode != 'formal'):
            raise ValueError('Macro tender output reading requires its explicit formal A02 context')
        registration = self.registry.get('CONTRACTOR-A02')
        if self._result_views is None:
            self._result_views = AuthorizedMacroViewAssembler(self.organizations, self.provider,
                gba_tender_proposal_source_schemas(), macro_version=self.macro_version, source_mode='formal')
        resolver = self._result_views.build_resolver(context, registration.action_id, registration.role)
        return ActionReadView(context, resolver, self.organizations, registration.action_id, registration.role)

    def build(self, context, *, pricing_profile_ref, capacity_ref, cost_refs,
            allowed_method_refs=None):
        context = ActionContext.model_validate(context).model_copy(deep=True)
        if context.contract_ref.kind != 'ActionContract' or context.contract_ref.id != 'CONTRACTOR-A02':
            raise ValueError('Bid assembly requires an explicit original Contractor A02 contract')
        if self.source_mode == 'fixture' and context.execution_mode != 'offline_fixture':
            raise ValueError('Fixture bid projections require explicit offline_fixture execution')
        registration = self.registry.get('CONTRACTOR-A02')
        if not registration.implemented or registration.skill is None or registration.role != 'Contractor':
            raise ValueError('Bid assembly requires its actual registered processor and bound Contractor Skill')
        resolver = self._views.build_resolver(context, registration.action_id, registration.role)
        runner = ActionRunner(self.registry, organizations=self.organizations, references=resolver,
            methods=self.methods, audit_sink=self.audit_sink, policy_version=self.policy_version,
            model_version=self.model_version, decision_strategies=self.decision_strategies,
            retain_reading_evidence=True)
        reading = ActionReadView(context, resolver, self.organizations, registration.action_id,
            registration.role, methods=runner.methods, method_refs=registration.skill.manifest.method_refs)

        def read(ref, schema):
            ref = Reference.model_validate(ref)
            value = reading.resolve(ref)
            if not isinstance(value, schema) or value.ref != ref:
                raise ValueError('Bid assembly requires the exact original concrete object projection')
            return value

        try:
            profile = read(pricing_profile_ref, ContractorBidProfileView)
            package = read(profile.package_ref, ContractorBidPackageView)
            capacity = read(capacity_ref, ContractorBidCapacityView)
            if (profile.organization_id != reading.organization_id or capacity.organization_id != reading.organization_id
                    or reading.organization_id not in package.recipient_organization_ids):
                raise ValueError('Bid input substitutes its original enterprise or procurement recipient')
            costs = [Reference.model_validate(ref) for ref in cost_refs]
            methods = (list(package.allowed_method_refs) if allowed_method_refs is None else
                       [Reference.model_validate(ref) for ref in allowed_method_refs])
            for refs in (costs, methods, package.deliverable_refs, package.quantity_refs, package.allowed_method_refs):
                unique_refs(refs)
            if not set(methods) <= set(package.allowed_method_refs):
                raise ValueError('Bid input adds a method outside original procurement permission')
            for ref in costs:
                cost = read(ref, ContractorBidCostView)
                if (cost.organization_id != reading.organization_id or cost.package_ref != package.ref
                        or cost.quantity_basis_ref not in package.quantity_refs):
                    raise ValueError('Bid cost changes original enterprise, procurement package or quantity version')
            action_input = registration.contract.validate_input({
                'package_ref': package.ref, 'deliverable_refs': list(package.deliverable_refs),
                'quantity_refs': list(package.quantity_refs), 'cost_refs': costs,
                'capacity_ref': capacity.ref, 'pricing_profile_ref': profile.ref,
                'allowed_method_refs': methods})
            for ref in walk_references(action_input):
                reading.resolve(ref)
            candidates = reading.resolve(context.candidate_set_ref)
            if not isinstance(candidates, CandidateSet):
                raise ValueError('Bid assembly requires a typed current authorized candidate set')
            candidates.check_context(context, registration.contract.choices)
            for candidate in candidates.candidates:
                reading.resolve(candidate.ref)
            reading.recheck()
            return PreparedContractorBid(context, action_input, runner, reading,
                task_digest(action_input.model_dump(mode='json')),
                task_digest(context.model_dump(mode='json')), task_digest(reading.evidence()))
        finally:
            reading.recheck()
