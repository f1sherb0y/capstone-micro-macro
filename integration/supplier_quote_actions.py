"""Assemble Supplier A03 from actual authorized product, cost and logistics projections."""
from dataclasses import dataclass, replace

from integration.action_model_host import resolve_action_model_host
from integration.macro_views import AuthorizedMacroViewAssembler
from src.actions.contracts.common import ActionContext, Reference, walk_references
from src.actions.contracts.domain import CandidateSet
from src.actions.contracts.owner_study_objects import unique_refs
from src.actions.contracts.references import ActionReadView
from src.actions.contracts.supplier_quote_objects import (
    QuoteCapacityView, QuoteCostView, QuoteInquiryView, QuoteInventoryView,
    QuoteLogisticsView, QuoteProfileView, QuoteProposalView,
)
from src.actions.runner import ActionRunner
from src.coordination.tasks import task_digest


def supplier_quote_source_schemas():
    """Retain quote schemas and add explicit authorized source/adoption relations."""
    from integration.supplier_product_handoff import supplier_product_handoff_schemas
    from integration.supplier_quote_costs import add_supplier_cost_schemas
    from integration.supplier_quote_logistics_source import add_supplier_quote_logistics_schemas
    from integration.supplier_quote_inventory_source import add_supplier_quote_inventory_schemas
    from integration.supplier_quote_capacity_source import add_supplier_quote_capacity_schemas

    return add_supplier_quote_capacity_schemas(add_supplier_quote_inventory_schemas(
        add_supplier_quote_logistics_schemas(add_supplier_cost_schemas(supplier_product_handoff_schemas()))))


@dataclass(frozen=True)
class PreparedSupplierQuote:
    context: ActionContext
    action_input: object
    runner: ActionRunner
    reading: ActionReadView
    input_sha256: str
    context_sha256: str
    reading_sha256: str

    def execute(self, *, execution_path=None):
        """Run original quote checks; creating a proposal reserves no inventory or capacity."""
        if (task_digest(self.action_input.model_dump(mode='json')) != self.input_sha256
                or task_digest(self.context.model_dump(mode='json')) != self.context_sha256):
            raise ValueError('Prepared quote changed; rebuild its original authorized versions')
        self.reading.recheck()
        return self.runner.run_action(self.context, self.action_input, execution_path=execution_path)


class SupplierQuoteActionAssembler:
    """Connect explicit host-selected A03 sources to its original Runner and Skill.

    No product selection, price, cost, stock, delivery window or resource rate is
    invented. Formal and fixture providers remain explicit. The business checks
    retain original service-cost completeness, partial/unknown states, proposal
    confirmation conditions, and actual shared-pool occupancy. A quote is not
    an order, reservation, payment or native macro submission.
    """
    SOURCE_SCHEMAS = staticmethod(supplier_quote_source_schemas)

    def __init__(self, *, registry, organizations, provider, macro_version, source_mode,
            methods=None, audit_sink=None, policy_version=None, model_version=None,
            decision_strategies=(), model_host=None):
        model_version, decision_strategies = resolve_action_model_host(registry=registry,
            run_id=organizations.run_id, model_version=model_version,
            decision_strategies=decision_strategies, model_host=model_host)
        self.registry, self.organizations = registry, organizations
        self.methods, self.audit_sink = methods, audit_sink
        self.policy_version, self.model_version = policy_version, model_version
        self.decision_strategies = tuple(decision_strategies)
        self.source_mode = source_mode
        self._views = AuthorizedMacroViewAssembler(organizations, provider, self.SOURCE_SCHEMAS(),
            macro_version=macro_version, source_mode=source_mode)

    @property
    def view_provider(self):
        """Expose the configured host provider for same-source pipeline binding checks."""
        return self._views.provider

    def build_cost_source_reading(self, context):
        """Read professional cost/adoption sources before fresh-token publication, without running A03."""
        return self.build_source_reading(context)

    def build_source_reading(self, context):
        """Read explicit quote sources without running A03 or methods."""
        context = ActionContext.model_validate(context).model_copy(deep=True)
        if context.contract_ref.kind != 'ActionContract' or context.contract_ref.id != 'SUPPLIER-A03':
            raise ValueError('Quote source reading requires its original A03 context')
        if self.source_mode == 'fixture' and context.execution_mode != 'offline_fixture':
            raise ValueError('Fixture quote sources require explicit offline_fixture execution')
        registration = self.registry.get('SUPPLIER-A03')
        if not registration.implemented or registration.skill is None or registration.role != 'Supplier':
            raise ValueError('Quote source reading requires the original Supplier Skill and processor')
        resolver = self._views.build_resolver(context, registration.action_id, registration.role)
        runner = ActionRunner(self.registry, organizations=self.organizations, references=resolver,
            methods=self.methods, audit_sink=self.audit_sink, policy_version=self.policy_version,
            model_version=self.model_version, decision_strategies=self.decision_strategies)
        return ActionReadView(context, resolver, self.organizations, registration.action_id, registration.role,
            methods=runner.methods, method_refs=registration.skill.manifest.method_refs)

    def build(self, context, *, inquiry_ref, product_proposal_refs, cost_basis_refs,
            inventory_ref, capacity_ref, logistics_refs, pricing_profile_ref):
        context = ActionContext.model_validate(context).model_copy(deep=True)
        if context.contract_ref.kind != 'ActionContract' or context.contract_ref.id != 'SUPPLIER-A03':
            raise ValueError('Quote assembly requires the actual Supplier A03 context')
        if self.source_mode == 'fixture' and context.execution_mode != 'offline_fixture':
            raise ValueError('Fixture quote sources require explicit offline_fixture execution')
        registration = self.registry.get('SUPPLIER-A03')
        if not registration.implemented or registration.skill is None or registration.role != 'Supplier':
            raise ValueError('Quote assembly requires its bound processor and actual Supplier Skill')
        resolver = self._views.build_resolver(context, registration.action_id, registration.role)
        runner = ActionRunner(self.registry, organizations=self.organizations, references=resolver,
            methods=self.methods, audit_sink=self.audit_sink, policy_version=self.policy_version,
            model_version=self.model_version, decision_strategies=self.decision_strategies)
        reading = ActionReadView(context, resolver, self.organizations, registration.action_id,
            registration.role, methods=runner.methods, method_refs=registration.skill.manifest.method_refs)
        refs = {'product_proposal_refs': [Reference.model_validate(ref) for ref in product_proposal_refs],
                'cost_basis_refs': [Reference.model_validate(ref) for ref in cost_basis_refs],
                'logistics_refs': [Reference.model_validate(ref) for ref in logistics_refs]}
        for selected in refs.values():
            unique_refs(selected)
        action_input = registration.contract.validate_input({**refs,
            'inquiry_ref': Reference.model_validate(inquiry_ref), 'inventory_ref': Reference.model_validate(inventory_ref),
            'capacity_ref': Reference.model_validate(capacity_ref), 'pricing_profile_ref': Reference.model_validate(pricing_profile_ref)})

        def read(ref, schema):
            row = reading.resolve(ref)
            if not isinstance(row, schema) or row.ref != ref:
                raise ValueError('Quote input requires its original concrete projection and version')
            return row

        try:
            inquiry = read(action_input.inquiry_ref, QuoteInquiryView)
            profile = read(action_input.pricing_profile_ref, QuoteProfileView)
            inventory = read(action_input.inventory_ref, QuoteInventoryView)
            capacity = read(action_input.capacity_ref, QuoteCapacityView)
            if (inquiry.recipient_id != context.actor_id or inquiry.recipient_organization_id != reading.organization_id
                    or any(row.organization_id != reading.organization_id for row in (profile, inventory, capacity))):
                raise ValueError('Quote input changes original recipient or private Supplier sources')
            for ref in action_input.product_proposal_refs:
                row = read(ref, QuoteProposalView)
                if row.inquiry_ref != inquiry.ref or row.supplier_organization_id != reading.organization_id:
                    raise ValueError('Quote proposal changes original inquiry or Supplier')
            for ref in action_input.cost_basis_refs:
                if read(ref, QuoteCostView).supplier_organization_id != reading.organization_id:
                    raise ValueError('Quote cost belongs to another original Supplier')
            for ref in action_input.logistics_refs:
                row = read(ref, QuoteLogisticsView)
                if (row.supplier_organization_id != reading.organization_id or row.inquiry_ref != inquiry.ref
                        or row.product_proposal_ref not in action_input.product_proposal_refs):
                    raise ValueError('Quote logistics changes original Supplier, inquiry or selected proposal')
            for ref in walk_references(action_input):
                reading.resolve(ref)
            candidates = reading.resolve(context.candidate_set_ref)
            if not isinstance(candidates, CandidateSet):
                raise ValueError('Quote requires the typed current authorized candidate set')
            candidates.check_context(context, registration.contract.choices)
            for candidate in candidates.candidates:
                reading.resolve(candidate.ref)
            reading.recheck()
            return PreparedSupplierQuote(context, action_input, runner, reading,
                task_digest(action_input.model_dump(mode='json')), task_digest(context.model_dump(mode='json')),
                task_digest(reading.evidence()))
        finally:
            reading.recheck()

    def build_from_products(self, context, *, product_worker, product_identity,
            product_execution_versions, basis_ref, validate_history, validate_current, **quote_refs):
        """Prepare a quote from an explicit original A02 source; direct build remains available."""
        from integration.supplier_product_results import SupplierProductResultWorker

        if (not isinstance(product_worker, SupplierProductResultWorker) or product_worker.registry is not self.registry
                or product_worker.store.run_id != self.organizations.run_id):
            raise ValueError('Quote product handoff requires the original same-run A02 worker and registry')
        prepared = self.build(context, **quote_refs)
        handoff = product_worker.prepare_quote_handoff(product_identity, current_context=prepared.context,
            reading=prepared.reading, execution_versions=product_execution_versions, basis_ref=basis_ref,
            validate_history=validate_history, validate_current=validate_current)
        if handoff['kind'] != 'prepared':
            return handoff
        if {ref.key() for ref in handoff['product_proposal_refs']} != {
                ref.key() for ref in prepared.action_input.product_proposal_refs}:
            raise ValueError('Product handoff differs from the selected complete original A03 proposal set')
        prepared.reading.recheck()
        prepared = replace(prepared, reading_sha256=task_digest(prepared.reading.evidence()))
        return {**handoff, 'invocation': prepared}
