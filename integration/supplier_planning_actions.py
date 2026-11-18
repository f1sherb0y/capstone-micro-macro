"""Assemble original Supplier A05 from explicit actual work and planning sources."""
from dataclasses import dataclass, replace

from integration.supplier_order_handoff import supplier_order_handoff_schemas
from integration.supplier_quote_actions import PreparedSupplierQuote, SupplierQuoteActionAssembler
from src.actions.contracts.common import ActionContext, Reference, walk_references
from src.actions.contracts.domain import CandidateSet
from src.actions.contracts.owner_study_objects import unique_refs
from src.actions.contracts.references import ActionReadView
from src.actions.contracts.supplier_planning_objects import (
    FormationOfferView, QuoteCapacityView, QuoteInventoryView,
    SupplierPlanningDesignView, SupplierPlanningMethodView,
    SupplierPlanningProfileView, SupplierPlanningRequirementView,
    SupplierWorkAuthorityView, supplier_planning_schemas,
)
from src.actions.runner import ActionRunner
from src.coordination.tasks import task_digest
from src.organization.registry import scope_covers


@dataclass(frozen=True)
class PreparedSupplierPlanning(PreparedSupplierQuote):
    """Original planning invocation; a plan creates no stock or reserved resources."""


class SupplierPlanningActionAssembler(SupplierQuoteActionAssembler):
    """Reuse host configuration while using A05's distinct original schemas.

    Work authorization, inventory, shared capacity and professional methods are
    selected by the host. The original processor checks effective orders or
    independent stocking authority, full requirements, productivity, material
    dependencies, procurement limits and shared occupancy. Unknown facts and
    requests to change delivery remain original result branches. An A04 local
    acceptance is never synthesized into SupplyWorkAuthorization.
    """
    ACTION_ID = 'SUPPLIER-A05'
    SOURCE_SCHEMAS = staticmethod(supplier_order_handoff_schemas)

    def build(self, context, *, work_authority_ref, requirement_refs, design_refs,
            inventory_ref, upstream_offer_refs, capacity_ref, method_refs):
        context = ActionContext.model_validate(context).model_copy(deep=True)
        if context.contract_ref.kind != 'ActionContract' or context.contract_ref.id != 'SUPPLIER-A05':
            raise ValueError('Supply planning assembly requires its original A05 context')
        if self.source_mode == 'fixture' and context.execution_mode != 'offline_fixture':
            raise ValueError('Fixture planning sources require explicit offline_fixture execution')
        registration = self.registry.get('SUPPLIER-A05')
        if not registration.implemented or registration.skill is None or registration.role != 'Supplier':
            raise ValueError('Supply planning assembly requires its original Supplier Skill and processor')
        resolver = self._views.build_resolver(context, registration.action_id, registration.role)
        runner = ActionRunner(self.registry, organizations=self.organizations, references=resolver,
            methods=self.methods, audit_sink=self.audit_sink, policy_version=self.policy_version,
            model_version=self.model_version, decision_strategies=self.decision_strategies)
        reading = ActionReadView(context, resolver, self.organizations, registration.action_id, registration.role,
            methods=runner.methods, method_refs=registration.skill.manifest.method_refs)
        selected = {name: [Reference.model_validate(ref) for ref in refs] for name, refs in (
            ('requirement_refs', requirement_refs), ('design_refs', design_refs),
            ('upstream_offer_refs', upstream_offer_refs), ('method_refs', method_refs))}
        for refs in selected.values():
            unique_refs(refs)
        action_input = registration.contract.validate_input({**selected,
            'work_authority_ref': Reference.model_validate(work_authority_ref), 'scope_ref': context.scope,
            'inventory_ref': Reference.model_validate(inventory_ref), 'capacity_ref': Reference.model_validate(capacity_ref)})

        def read(ref, schema):
            row = reading.resolve(ref)
            if not isinstance(row, schema) or row.ref.key() != ref.key():
                raise ValueError('Supply planning requires its exact original concrete source version')
            return row

        try:
            mandate = read(action_input.work_authority_ref, SupplierWorkAuthorityView)
            profile = read(mandate.profile_ref, SupplierPlanningProfileView)
            inventory = read(action_input.inventory_ref, QuoteInventoryView)
            capacity = read(action_input.capacity_ref, QuoteCapacityView)
            if (any(row.organization_id != reading.organization_id for row in (mandate, profile, inventory, capacity))
                    or not scope_covers(context.scope, mandate.scope)
                    or profile.work_authority_ref != mandate.ref or profile.scope != context.scope
                    or profile.actor_id != context.actor_id or profile.function_ref != context.function_ref
                    or profile.authority_ref not in context.authorization_refs):
                raise ValueError('Supply planning changes original Supplier, work scope or authorized profile actor')
            for refs, schema in ((action_input.requirement_refs, SupplierPlanningRequirementView),
                    (action_input.design_refs, SupplierPlanningDesignView)):
                for ref in refs:
                    row = read(ref, schema)
                    if row.work_authority_ref != mandate.ref:
                        raise ValueError('Supply planning source names another original work authorization')
            for ref in action_input.method_refs:
                read(ref, SupplierPlanningMethodView)
            for ref in action_input.upstream_offer_refs:
                read(ref, FormationOfferView)
            for ref in walk_references(action_input):
                reading.resolve(ref)
            candidates = reading.resolve(context.candidate_set_ref)
            if not isinstance(candidates, CandidateSet):
                raise ValueError('Supply planning requires its actual current authorized candidate set')
            candidates.check_context(context, registration.contract.choices)
            for candidate in candidates.candidates:
                reading.resolve(candidate.ref)
            if (profile.monthly_reliability_policy_ref is not None or profile.monthly_reliability_observation_ref is not None
                    or profile.monthly_inventory_policy_ref is not None or profile.monthly_inventory_observation_ref is not None):
                # The worker seals assembly-time projections. Include the
                # explicitly declared monthly dossier before that seal, so
                # later evidence retains the actual policy and observation.
                for ref in context.visible_refs:
                    reading.resolve(ref)
            reading.recheck()
            return PreparedSupplierPlanning(context, action_input, runner, reading,
                task_digest(action_input.model_dump(mode='json')), task_digest(context.model_dump(mode='json')),
                task_digest(reading.evidence()))
        finally:
            reading.recheck()

    def build_from_order(self, context, *, order_worker, order_identity, order_execution_versions,
            basis_ref, validate_history, validate_current, **planning_refs):
        """Attach original A04 acceptance provenance to the explicitly selected actual A05 order."""
        from integration.supplier_order_results import SupplierOrderResultWorker

        if (not isinstance(order_worker, SupplierOrderResultWorker) or order_worker.registry is not self.registry
                or order_worker.store.run_id != self.organizations.run_id
                or not callable(validate_history) or not callable(validate_current)):
            raise ValueError('Order planning source requires its original worker, registry and explicit host checks')
        invocation = self.build(context, **planning_refs)
        handoff = order_worker.prepare_planning_handoff(order_identity, current_context=invocation.context,
            reading=invocation.reading, execution_versions=order_execution_versions, basis_ref=basis_ref,
            work_authority_ref=invocation.action_input.work_authority_ref,
            validate_history=validate_history, validate_current=validate_current)
        if handoff['kind'] != 'prepared':
            return handoff
        invocation.reading.recheck()
        invocation = replace(invocation, reading_sha256=task_digest(invocation.reading.evidence()))
        return {**handoff, 'invocation': invocation}
