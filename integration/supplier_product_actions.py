"""Assemble Supplier A02 from actual inquiry, product and independent design sources."""
from dataclasses import dataclass, replace

from integration.supplier_screening_handoff import supplier_screening_handoff_schemas
from integration.supplier_quote_actions import PreparedSupplierQuote, SupplierQuoteActionAssembler
from src.actions.contracts.common import ActionContext, Reference, walk_references
from src.actions.contracts.domain import CandidateSet
from src.actions.contracts.owner_study_objects import unique_refs
from src.actions.contracts.references import ActionReadView
from src.actions.contracts.supplier_product_objects import (
    ProductCompatibilityMethodView, ProductDesignView, ProductRequirementView,
    ProductSpecificationView, SupplyInquiryView, supplier_product_schemas,
)
from src.actions.runner import ActionRunner
from src.coordination.tasks import task_digest
from src.organization.models import Authorization
from src.organization.registry import scope_covers


@dataclass(frozen=True)
class PreparedSupplierProduct(PreparedSupplierQuote):
    """Original product proposal invocation; no independent design approval is created."""


class SupplierProductActionAssembler(SupplierQuoteActionAssembler):
    """Reuse explicit host setup with A02's distinct original product schemas.

    Host refs select inquiry requirements, products, received design reviews,
    compatibility method and independent design authorizations. The processor
    checks exact requirement coverage, actual factory/use/property evidence,
    substitutions, deviations, unresolved design dependencies and priorities.
    Empty candidates and clarification retain their original branches. A01
    screening does not invent product evidence or waive independent design
    authority; assembly does not reserve stock or create a formal offer.
    """
    SOURCE_SCHEMAS = staticmethod(supplier_screening_handoff_schemas)

    def build(self, context, *, inquiry_ref, requirement_refs, design_refs,
            product_candidates, compatibility_method_ref, design_authority_refs):
        context = ActionContext.model_validate(context).model_copy(deep=True)
        if context.contract_ref.kind != 'ActionContract' or context.contract_ref.id != 'SUPPLIER-A02':
            raise ValueError('Supplier product assembly requires its original A02 context')
        if self.source_mode == 'fixture' and context.execution_mode != 'offline_fixture':
            raise ValueError('Fixture product sources require explicit offline_fixture execution')
        registration = self.registry.get('SUPPLIER-A02')
        if not registration.implemented or registration.skill is None or registration.role != 'Supplier':
            raise ValueError('Supplier product assembly requires its original Skill and processor')
        resolver = self._views.build_resolver(context, registration.action_id, registration.role)
        runner = ActionRunner(self.registry, organizations=self.organizations, references=resolver,
            methods=self.methods, audit_sink=self.audit_sink, policy_version=self.policy_version,
            model_version=self.model_version, decision_strategies=self.decision_strategies)
        reading = ActionReadView(context, resolver, self.organizations, registration.action_id, registration.role,
            methods=runner.methods, method_refs=registration.skill.manifest.method_refs)
        selected = {name: [Reference.model_validate(ref) for ref in refs] for name, refs in (
            ('requirement_refs', requirement_refs), ('design_refs', design_refs),
            ('product_candidates', product_candidates), ('design_authority_refs', design_authority_refs))}
        for refs in selected.values():
            unique_refs(refs)
        action_input = registration.contract.validate_input({**selected,
            'inquiry_ref': Reference.model_validate(inquiry_ref),
            'compatibility_method_ref': Reference.model_validate(compatibility_method_ref)})

        def read(ref, schema):
            row = reading.resolve(ref)
            if not isinstance(row, schema) or row.ref != ref:
                raise ValueError('Supplier product requires its exact original concrete source version')
            return row

        try:
            inquiry = read(action_input.inquiry_ref, SupplyInquiryView)
            if (inquiry.recipient_id != context.actor_id or inquiry.recipient_organization_id != reading.organization_id
                    or not scope_covers(context.scope, inquiry.scope)):
                raise ValueError('Supplier product changes original inquiry recipient or scope')
            method = read(action_input.compatibility_method_ref, ProductCompatibilityMethodView)
            if method.organization_id != reading.organization_id:
                raise ValueError('Supplier compatibility method belongs to another organization')
            for refs, schema in ((action_input.requirement_refs, ProductRequirementView),
                    (action_input.design_refs, ProductDesignView)):
                for ref in refs:
                    if read(ref, schema).inquiry_ref != inquiry.ref:
                        raise ValueError('Product requirement or design names another original inquiry')
            for ref in action_input.product_candidates:
                read(ref, ProductSpecificationView)
            for ref in action_input.design_authority_refs:
                read(ref, Authorization)
            for ref in walk_references(action_input):
                reading.resolve(ref)
            candidates = reading.resolve(context.candidate_set_ref)
            if not isinstance(candidates, CandidateSet):
                raise ValueError('Supplier product requires its actual current authorized candidate set')
            candidates.check_context(context, registration.contract.choices)
            for candidate in candidates.candidates:
                reading.resolve(candidate.ref)
            reading.recheck()
            return PreparedSupplierProduct(context, action_input, runner, reading,
                task_digest(action_input.model_dump(mode='json')), task_digest(context.model_dump(mode='json')),
                task_digest(reading.evidence()))
        finally:
            reading.recheck()

    def build_from_screening(self, context, *, screening_worker, screening_identity,
            screening_execution_versions, basis_ref, validate_history, validate_current, **product_refs):
        """Bind selected product inquiry to original saved screening and actual received demand."""
        from integration.supplier_screening_results import SupplierScreeningResultWorker

        if (not isinstance(screening_worker, SupplierScreeningResultWorker) or screening_worker.registry is not self.registry
                or screening_worker.store.run_id != self.organizations.run_id
                or not callable(validate_history) or not callable(validate_current)):
            raise ValueError('Product screening source requires original worker/registry and explicit host checks')
        invocation = self.build(context, **product_refs)
        handoff = screening_worker.prepare_product_handoff(screening_identity, current_context=invocation.context,
            reading=invocation.reading, execution_versions=screening_execution_versions, basis_ref=basis_ref,
            inquiry_ref=invocation.action_input.inquiry_ref, requirement_refs=invocation.action_input.requirement_refs,
            validate_history=validate_history, validate_current=validate_current)
        if handoff['kind'] != 'prepared':
            return handoff
        invocation.reading.recheck()
        return {**handoff, 'invocation': replace(invocation,
            reading_sha256=task_digest(invocation.reading.evidence()))}
