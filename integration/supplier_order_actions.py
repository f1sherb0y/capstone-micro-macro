"""Connect actual Supplier A04 order sources and optional saved quote provenance to Runner."""
from dataclasses import dataclass, replace

from integration.supplier_quote_actions import PreparedSupplierQuote, SupplierQuoteActionAssembler
from integration.supplier_quote_handoff import supplier_quote_handoff_schemas
from integration.supplier_quote_results import SupplierQuoteResultWorker
from src.actions.contracts.common import ActionContext, Reference, walk_references
from src.actions.contracts.domain import CandidateSet
from src.actions.contracts.owner_study_objects import unique_refs
from src.actions.contracts.references import ActionReadView
from src.actions.contracts.supplier_order_objects import (
    FormationAcceptanceView, FormationFundingView, FormationOfferView, FormationProfileView, OrderProposalView,
)
from src.actions.contracts.supplier_quote_objects import QuoteCapacityView, QuoteInventoryView
from src.actions.runner import ActionRunner
from src.coordination.tasks import TaskConflict, task_digest
from src.organization.registry import scope_covers


@dataclass(frozen=True)
class PreparedSupplierOrder(PreparedSupplierQuote):
    """Original A04 input and execution evidence; accepting a draft does not create an order."""


class SupplierOrderActionAssembler(SupplierQuoteActionAssembler):
    """Reuse explicit provider/model host setup; preserve every original A04 branch.

    Inventory, capacity, funding, formation policy and party acceptances are
    explicitly supplied actual versions. The original processor checks exact
    agreements, permitted changes, partial quantities and complete shared
    occupancy; assembly never asserts independent acceptance or creates an
    order, supply reservation or cash movement.
    """
    SOURCE_SCHEMAS = staticmethod(supplier_quote_handoff_schemas)

    def build(self, context, *, order_proposal_ref, offer_ref, counterpart_acceptance_refs,
            inventory_ref, capacity_ref, funding_ref, formation_profile_ref):
        context = ActionContext.model_validate(context).model_copy(deep=True)
        if context.contract_ref.kind != 'ActionContract' or context.contract_ref.id != 'SUPPLIER-A04':
            raise ValueError('Order assembly requires the actual Supplier A04 context')
        if self.source_mode == 'fixture' and context.execution_mode != 'offline_fixture':
            raise ValueError('Fixture order sources require explicit offline_fixture execution')
        registration = self.registry.get('SUPPLIER-A04')
        if not registration.implemented or registration.skill is None or registration.role != 'Supplier':
            raise ValueError('Order assembly requires the actual Supplier Skill and bound processor')
        resolver = self._views.build_resolver(context, registration.action_id, registration.role)
        runner = ActionRunner(self.registry, organizations=self.organizations, references=resolver,
            methods=self.methods, audit_sink=self.audit_sink, policy_version=self.policy_version,
            model_version=self.model_version, decision_strategies=self.decision_strategies)
        reading = ActionReadView(context, resolver, self.organizations, registration.action_id, registration.role,
            methods=runner.methods, method_refs=registration.skill.manifest.method_refs)
        acceptances = [Reference.model_validate(ref) for ref in counterpart_acceptance_refs]
        unique_refs(acceptances)
        action_input = registration.contract.validate_input({
            'order_proposal_ref': Reference.model_validate(order_proposal_ref), 'offer_ref': Reference.model_validate(offer_ref),
            'counterpart_acceptance_refs': acceptances, 'inventory_ref': Reference.model_validate(inventory_ref),
            'capacity_ref': Reference.model_validate(capacity_ref), 'funding_ref': Reference.model_validate(funding_ref),
            'formation_profile_ref': Reference.model_validate(formation_profile_ref)})

        try:
            sources = {ref.key(): reading.resolve(ref) for ref in walk_references(action_input)}
            validate_supplier_order_sources(action_input, context=context,
                organization_id=reading.organization_id, sources=sources)
            candidates = reading.resolve(context.candidate_set_ref)
            if not isinstance(candidates, CandidateSet):
                raise ValueError('Order assembly requires the actual current authorized candidate set')
            candidates.check_context(context, registration.contract.choices)
            for candidate in candidates.candidates:
                reading.resolve(candidate.ref)
            reading.recheck()
            return PreparedSupplierOrder(context, action_input, runner, reading,
                task_digest(action_input.model_dump(mode='json')), task_digest(context.model_dump(mode='json')),
                task_digest(reading.evidence()))
        finally:
            reading.recheck()

    def build_from_quote(self, context, *, quote_worker, quote_identity, quote_execution_versions,
            basis_ref, validate_history, validate_current, **order_refs):
        """Check saved A03 provenance of the actual offer; A04 business execution remains explicit."""
        if (not isinstance(quote_worker, SupplierQuoteResultWorker) or quote_worker.registry is not self.registry
                or quote_worker.store.run_id != self.organizations.run_id):
            raise ValueError('Order quote handoff requires its original same-run quote worker and registry')
        prepared = self.build(context, **order_refs)
        handoff = quote_worker.prepare_order_handoff(quote_identity, current_context=prepared.context,
            reading=prepared.reading, execution_versions=quote_execution_versions, basis_ref=basis_ref,
            validate_history=validate_history, validate_current=validate_current)
        if handoff['kind'] != 'prepared':
            return handoff
        if handoff['offer_ref'] != prepared.action_input.offer_ref:
            raise ValueError('Quote source relation names another original offer than the selected A04 input')
        prepared.reading.recheck()
        # Handoff resolves additional basis/native evidence. Retain the full
        # original assembly cache so persistence does not compare the extended
        # reading against the earlier order-only digest.
        prepared = replace(prepared, reading_sha256=task_digest(prepared.reading.evidence()))
        return {**handoff, 'invocation': prepared}


def validate_supplier_order_sources(action_input, *, context, organization_id, sources):
    """Keep original A04 input identities and private ownership in saved evidence.

    This checks the sources supplied during assembly, without evaluating the
    commercial policy, acceptance gates or current funding/stock/capacity.
    """
    def read(ref, schema):
        row = sources.get(ref.key())
        if not isinstance(row, schema) or row.ref.key() != ref.key():
            raise TaskConflict('Order sources lack their exact original concrete projection and version')
        return row

    proposal = read(action_input.order_proposal_ref, OrderProposalView)
    offer = read(action_input.offer_ref, FormationOfferView)
    profile = read(action_input.formation_profile_ref, FormationProfileView)
    private_sources = [profile, read(action_input.inventory_ref, QuoteInventoryView),
        read(action_input.capacity_ref, QuoteCapacityView), read(action_input.funding_ref, FormationFundingView)]
    if (offer.supplier_organization_id != organization_id
            or proposal.supplier_organization_id != organization_id
            or proposal.recipient_actor_id != context.actor_id or proposal.offer_ref != offer.ref
            or proposal.buyer_id != offer.buyer_id or proposal.scope != offer.scope
            or not scope_covers(context.scope, proposal.scope)
            or profile.offer_ref != offer.ref or profile.order_proposal_ref != proposal.ref
            or any(row.organization_id != organization_id for row in private_sources)):
        raise TaskConflict('Order sources change original recipient, scope, offer, proposal or private Supplier sources')
    unique_refs(action_input.counterpart_acceptance_refs)
    for ref in action_input.counterpart_acceptance_refs:
        read(ref, FormationAcceptanceView)
